"""Integration tests against a private tmux server (`-L`), never the user's."""

import os
import subprocess
import threading
import time

import conftest
import pytest
from conftest import kill_private_server, private_socket_name
from conftest import wait_for_sync as wait_for

from sessionorc.tmux import DuplicateSession, Tmux, TmuxError

pytestmark = pytest.mark.integration


@pytest.fixture
def tmux():
    t = Tmux(socket_name=private_socket_name())
    t.ensure_server()
    yield t
    kill_private_server(t)


def test_server_survives_empty(tmux):
    tmux.new_session("ao-t-a", "/", ["sleep", "0.1"], {})
    assert wait_for(lambda: any(p.dead for p in tmux.list_panes()))
    tmux.kill_session("ao-t-a")
    assert tmux.list_panes() == []
    assert tmux.run("list-sessions", check=False).returncode == 0  # server still up: exit-empty off


def test_env_pipe_pane_and_paste(tmux, tmp_path):
    log = tmp_path / "run.log"
    tmux.new_session("ao-t-b", str(tmp_path), ["bash", "--norc", "--noprofile"], {"SHIFTLEAD_SESSION": "ao-t-b"})
    tmux.pipe_pane("ao-t-b", log)
    tmux.send_literal("ao-t-b", "echo env=$SHIFTLEAD_SESSION")
    tmux.send_enter("ao-t-b")
    assert wait_for(lambda: log.exists() and "env=ao-t-b" in log.read_text())
    tmux.paste("ao-t-b", "echo one\necho two")
    tmux.send_enter("ao-t-b")
    assert wait_for(lambda: "one" in log.read_text() and "two" in log.read_text())
    tail = tmux.capture_tail("ao-t-b", 4)
    assert any("two" in row for row in tail)
    info = {p.session: p for p in tmux.list_panes()}["ao-t-b"]
    assert info.current_command == "bash" and not info.dead


def test_send_prompt_leaves_copy_mode_first(tmux, tmp_path):
    """TD-667, design §4.3 *Prompt injection*: in copy mode the Enter is the mode's, so the blind send
    leaves the mode before it pastes; a pane in no mode is left as it is."""
    log = tmp_path / "cm.log"
    tmux.new_session("ao-t-cm", str(tmp_path), ["bash", "--norc", "--noprofile"], {})
    tmux.pipe_pane("ao-t-cm", log)

    def in_mode() -> str:
        return tmux.run("display-message", "-p", "-t", "=ao-t-cm:", "#{pane_in_mode}").stdout.strip()

    tmux.send_prompt("ao-t-cm", "echo first-$((40+2))")  # no mode: copy-mode -q is no error
    assert wait_for(lambda: log.exists() and "first-42" in log.read_text())
    tmux.run("copy-mode", "-u", "-t", "=ao-t-cm:")
    assert in_mode() == "1"
    tmux.send_prompt("ao-t-cm", "echo second-$((40+3))")
    assert wait_for(lambda: "second-43" in log.read_text())
    assert in_mode() == "0"


def test_concurrent_pastes_do_not_share_one_buffer(tmux, tmp_path):
    """TD-043: a fixed buffer name made two concurrent pastes fight over one server-wide buffer —
    the first `paste-buffer -d` deleted it and the others failed `no buffer ao-paste`."""
    logs = {}
    for n in ("d", "e", "f", "g"):
        name = f"ao-t-{n}"
        logs[name] = tmp_path / f"{name}.log"
        tmux.new_session(name, str(tmp_path), ["bash", "--norc", "--noprofile"], {})
        tmux.pipe_pane(name, logs[name])

    errors: list[BaseException] = []

    def paste(name: str) -> None:
        try:
            tmux.paste(name, f"echo mine={name}")
            tmux.send_enter(name)
        except BaseException as exc:  # noqa: BLE001 - reported through `errors`
            errors.append(exc)

    threads = [threading.Thread(target=paste, args=(name,)) for name in logs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    for name, log in logs.items():
        assert wait_for(lambda log=log, name=name: log.exists() and f"mine={name}" in log.read_text())
        # Nobody received anybody else's text.
        text = log.read_text()
        assert not [other for other in logs if other != name and f"mine={other}" in text]
    assert tmux.run("list-buffers", check=False).stdout.strip() == ""


def test_pane_title_rides_with_the_pane_list(tmux):
    """TD-074 step 3: the terminal title the program in the pane set (`#{pane_title}`) comes back
    with the pane list the tick already reads — no second tmux call per session. It is the last
    field of the format, and the split is bounded, so whatever is in it keeps the fields before it
    in their places (tmux itself drops the control bytes a title might carry)."""
    tmux.new_session("ao-t-title", "/", ["bash", "--norc", "--noprofile"], {})
    assert wait_for(lambda: {p.session: p for p in tmux.list_panes()}.get("ao-t-title") is not None)
    # a program sets it with the usual OSC 2 escape; tmux holds it on the pane
    tmux.send_literal("ao-t-title", r"printf '\033]2;\342\234\263 Error Checker\007'")
    tmux.send_enter("ao-t-title")
    assert wait_for(lambda: {p.session: p for p in tmux.list_panes()}["ao-t-title"].title.endswith("Checker"))
    info = {p.session: p for p in tmux.list_panes()}["ao-t-title"]
    assert info.title == "✳ Error Checker"
    assert info.current_command == "bash" and not info.dead and info.window == 0


def test_exit_status_readable(tmux):
    tmux.new_session("ao-t-c", "/", ["sh", "-c", "exit 3"], {})
    assert wait_for(lambda: any(p.dead and p.session == "ao-t-c" for p in tmux.list_panes()))
    info = {p.session: p for p in tmux.list_panes()}["ao-t-c"]
    assert info.dead_status == 3


def test_the_stale_server_sweep_leaves_a_concurrent_runs_server_alone():
    """TD-025: the sweep exists for servers a killed run left behind, and it used to kill every live
    `ao-test-*` server — including the one a *concurrent* pytest process was in the middle of using,
    which is how a suite run beside a review lost its panes mid-test. A server whose owning process
    is still alive is now left alone; once that process is gone it is swept as before."""
    name = private_socket_name()
    sock = f"/tmp/tmux-{os.getuid()}/{name}"
    t = Tmux(socket_name=name)
    t.ensure_server()
    owner = subprocess.Popen(["sleep", "60"])
    try:
        (conftest.OWNERS / name).write_text(str(owner.pid))  # as another pytest process would
        conftest.sweep_stale_test_servers()
        assert os.path.exists(sock) and t.run("list-sessions", check=False).returncode == 0
        owner.terminate()
        owner.wait(timeout=5)
        # the owner is gone: the server is a leak, and the sweep takes it and its bookkeeping
        conftest.sweep_stale_test_servers()
        assert not os.path.exists(sock) and not (conftest.OWNERS / name).exists()
    finally:
        if owner.poll() is None:
            owner.terminate()
            owner.wait(timeout=5)
        kill_private_server(t)  # a failed assertion above must not leave a server behind


def test_the_sweep_removes_an_owner_file_only_when_its_owner_ended_and_it_has_no_socket():
    """TD-2101: an owner file is written before its server exists, so one with no socket used to stay for good. It goes
    once its pid has ended; a live owner's stays, this run's own stays, and so does one whose pid cannot be read yet."""
    ended = subprocess.Popen(["true"])
    ended.wait(timeout=5)
    live = subprocess.Popen(["sleep", "60"])
    names = {k: f"ao-test-td2101{k}{os.getpid()}" for k in ("ended", "live", "own", "blank")}
    other = f"aoscr-td2101{os.getpid()}"  # a scratch root's owner, the other sweep's
    try:
        conftest.OWNERS.mkdir(exist_ok=True)
        (conftest.OWNERS / names["ended"]).write_text(str(ended.pid))
        (conftest.OWNERS / names["live"]).write_text(str(live.pid))
        (conftest.OWNERS / names["own"]).write_text(str(os.getpid()))
        (conftest.OWNERS / names["blank"]).write_text("")
        (conftest.OWNERS / other).write_text(str(ended.pid))
        conftest.sweep_stale_test_servers()
        assert not (conftest.OWNERS / names["ended"]).exists()
        assert all((conftest.OWNERS / names[k]).exists() for k in ("live", "own", "blank"))
        assert (conftest.OWNERS / other).exists()
    finally:
        live.terminate()
        live.wait(timeout=5)
        for name in (*names.values(), other):
            conftest._forget_owner(name)


def test_a_command_too_long_for_tmux_is_launched_through_a_script(tmux, tmp_path, monkeypatch):
    """2026-09-20: `ao team start` failed with tmux's *command too long* — a session's brief rides in
    its argv, and one had grown to 16,194 bytes. Past `LONG_COMMAND` the argv goes through a launch
    script that `exec`s it; every byte arrives, the pane's first process is still the command, and
    a short command is passed exactly as before."""
    from sessionorc import tmux as tmux_mod

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    brief = "- a brief with 'quotes', \"doubles\", $dollars, `ticks` and a\nnewline; " * 600  # ~40 KB
    assert len(brief.encode()) > 16_384
    argv = ["sh", "-c", 'printf %s "$1" > "$2"; printf %s "$0" > "$2.zero"; sleep 30', "marker", brief, str(out)]
    tmux.new_session("ao-long", tmp_path, argv, {"X": "1"})
    for _ in range(100):
        if out.exists() and out.read_text() == brief:
            break
        time.sleep(0.05)
    assert out.read_text() == brief  # every byte, quoting and newlines intact
    assert (tmp_path / "out.zero").read_text() == "marker"  # and the argv's own shape
    script = tmp_path / "home" / "launch" / "ao-long.sh"
    assert script.exists() and oct(script.stat().st_mode & 0o777) == "0o700"
    pane = tmux.main_panes("ao-")["ao-long"]
    assert pane.current_command == "sh" and not pane.dead  # `exec`: the command itself is the pane's process

    assert tmux_mod.Tmux._fit("ao-short", ["bash", "--norc"]) == ["bash", "--norc"]  # short: untouched
    # the room is the whole tmux command line's, so a large environment sends a modest argv through
    # the script too; and an argument no process could be started with is refused here, in words
    assert tmux_mod.Tmux._fit("ao-env", ["bash", "--norc"], around=9000) == [
        "/bin/sh",
        str(script.parent / "ao-env.sh"),
    ]
    with pytest.raises(tmux_mod.TmuxError, match="past what a process can be started with"):
        tmux_mod.Tmux._fit("ao-huge", ["claude", "x" * 130_000])
    assert not (tmp_path / "home" / "launch" / "ao-short.sh").exists()


def test_a_new_session_has_no_status_bar(tmux):
    """Focus's header says what tmux's bar would, and a resize by another client would leave stale
    copies of the bar in the browser's terminal (design §4.6, TD-1410)."""
    tmux.new_session("ao-t-bar", "/", ["sleep", "30"], {})
    assert tmux.run("show-options", "-v", "-t", "=ao-t-bar:", "status").stdout.strip() == "off"
    assert tmux.status_off() == [], "nothing left to turn off"


def test_the_agents_start_turns_off_the_bar_on_older_ao_sessions_only(tmux):
    """A session made before TD-1410 keeps tmux's default bar until the host agent's start takes it in;
    a session not named `ao-…` is the person's and keeps its own."""
    for name in ("ao-t-old", "mine"):
        tmux.run("new-session", "-d", "-s", name, "sleep", "30")
    assert tmux.status_off() == ["ao-t-old"]
    show = lambda n: tmux.run("show-options", "-v", "-t", f"={n}:", "status").stdout.strip()  # noqa: E731
    assert show("ao-t-old") == "off"
    assert show("mine") != "off" and tmux.run("show-options", "-gv", "status").stdout.strip() == "on"


def test_a_new_session_is_pinned_at_its_grid(tmux):
    """`new-session -x -y` starts the tool at the person's grid and `window-size manual` pins it, so no
    client sizes the window after (design §4.6 *Attach behaviour with another client present*, TD-1919);
    tmux 3.5a makes a detached window exactly that grid with its status line off."""
    tmux.new_session("ao-t-pin", "/", ["sleep", "30"], {}, grid=(97, 31))
    read = lambda f: tmux.run("display-message", "-p", "-t", "=ao-t-pin:", f).stdout.strip()  # noqa: E731
    assert tmux.run("show-options", "-wv", "-t", "=ao-t-pin:", "window-size").stdout.strip() == "manual"
    assert (read("#{pane_width}"), read("#{pane_height}")) == ("97", "31")
    tmux.new_session("ao-t-pin-default", "/", ["sleep", "30"], {})
    w = tmux.run("display-message", "-p", "-t", "=ao-t-pin-default:", "#{pane_width}x#{pane_height}")
    assert w.stdout.strip() == "120x40", "no setting: 120 x 40"


def test_the_pin_resizes_nothing_while_the_tool_starts(tmux, monkeypatch):
    """No `resize-window` in the invocation: the grid is the window's from its first byte (TD-1919)."""
    seen: list[tuple[str, ...]] = []
    real = tmux.run
    monkeypatch.setattr(tmux, "run", lambda *a, **k: (seen.append(a), real(*a, **k))[1])
    tmux.new_session("ao-t-argv", "/", ["sleep", "30"], {}, grid=(80, 24))
    (args,) = seen
    assert "resize-window" not in args
    assert args[args.index("-x") + 1 : args.index("-x") + 4] == ("80", "-y", "24")
    i = args.index("window-size")
    assert args[i - 4 : i + 2] == ("set-option", "-w", "-t", "=ao-t-argv:", "window-size", "manual")


def test_the_agents_start_pins_every_ao_window_at_its_size(tmux):
    """A session made before the pin follows its clients until the host agent's start pins it, at the size it
    has; a session not named `ao-…` is the person's and keeps following its clients, and the server's global
    option is untouched (TD-1919)."""
    for name in ("ao-t-unpinned", "mine"):
        tmux.run("new-session", "-d", "-s", name, "-x", "88", "-y", "22", "sleep", "30")
    assert "ao-t-unpinned" in tmux.pin_windows() and "mine" not in tmux.pin_windows()
    read = lambda n, f: tmux.run("display-message", "-p", "-t", f"={n}:", f).stdout.strip()  # noqa: E731
    opt = lambda n: tmux.run("show-options", "-wv", "-t", f"={n}:", "window-size").stdout.strip()  # noqa: E731
    assert opt("ao-t-unpinned") == "manual"
    assert read("ao-t-unpinned", "#{window_width}x#{window_height}") == "88x22"
    assert opt("mine") != "manual"
    assert tmux.run("show-options", "-gwv", "window-size").stdout.strip() != "manual"


def test_the_pins_default_grid_is_the_settings():
    from sessionorc import settings
    from sessionorc import tmux as tmux_module

    assert tmux_module.GRID_DEFAULT == settings.TERMINAL_GRID_DEFAULT


def _a_later_step_fails(tmux, monkeypatch):
    """`new_session`'s chain with one more step that fails after `new-session` has made the session."""
    run = tmux.run

    def failing(*args, **kw):
        if args and args[0] == "new-session":
            args = (*args, ";", "set-option", "-t", "=ao-t-nobody:", "status", "off")
        return run(*args, **kw)

    monkeypatch.setattr(tmux, "run", failing)


def test_a_later_step_that_fails_takes_the_session_it_made_with_it(tmux, monkeypatch):
    """TD-2144: a chained step that failed after `new-session` left the session up with no record."""
    _a_later_step_fails(tmux, monkeypatch)
    with pytest.raises(TmuxError, match="ao-t-nobody") as e:
        tmux.new_session("ao-t-late", "/", ["sleep", "30"], {})
    assert not isinstance(e.value, DuplicateSession)
    assert not tmux.has_session("ao-t-late")


def test_a_duplicate_session_is_never_killed(tmux, monkeypatch):
    """TD-2144: `new-session` refused the name, so it made nothing, and the session of that name is another's."""
    tmux.new_session("ao-t-other", "/", ["sleep", "30"], {})
    _a_later_step_fails(tmux, monkeypatch)
    with pytest.raises(DuplicateSession):
        tmux.new_session("ao-t-other", "/", ["sleep", "30"], {})
    assert tmux.has_session("ao-t-other")
