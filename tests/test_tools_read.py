"""The Tools page's read (design §4.2b *The page*, *Controls and verbs*, TD-1973): the tool cards, their versions, the
found rows and *Not ready to run here*, before the switch-over; `ao tools` and `ao tools check`."""

from __future__ import annotations

from pathlib import Path

import pytest

from sessionorc import adapters, tools


class _Stub:
    """An agent adapter with the Tools page's reads, its answers set per test."""

    implements = frozenset({"find", "install_command", "identity", "credentials_ok"})

    def __init__(self, name, *, found, home, identity=None, creds=None, own_home=None, version="1.2.3 (Stub)"):
        self.name, self.label, self._found, self._home = name, name.title(), found, home
        self._identity, self._creds, self._version = identity, creds, version
        if own_home is not None:
            self.own_home = own_home

    def find(self):
        return self._found

    def install_command(self):
        return f"curl https://example.invalid/{self.name} | sh"

    def default_home(self, env):
        return self._home

    def tool_version(self, env):
        return self._version

    def identity(self, home, salt):
        return self._identity

    def credentials_ok(self, home):
        return self._creds


def _registry(monkeypatch, *stubs, known=()):
    reg = {s.name: s for s in stubs}
    monkeypatch.setattr(adapters, "names", lambda: sorted([*reg, "shell"]))
    monkeypatch.setattr(adapters, "has_agent", lambda n: n != "shell")
    monkeypatch.setattr(adapters, "get", lambda n: reg[n])
    monkeypatch.setattr(adapters, "known_tools", lambda: list(known))


def test_a_found_tool_is_a_card_and_one_not_found_is_not_ready_with_its_install(monkeypatch, tmp_path):
    _registry(
        monkeypatch,
        _Stub("alpha", found="/bin/alpha", home=tmp_path / "a", identity={"match": "m", "display": "Paul"}),
        _Stub("beta", found=None, home=tmp_path / "b"),
    )
    r = tools.read(b"s" * 32, env={}, home=tmp_path)
    assert r["switched"] is False and r["host"] and r["read_at"]
    [alpha] = r["tools"]
    assert alpha["adapter"] == "alpha" and alpha["installed"] and alpha["supported"]
    assert alpha["version"] == "1.2.3 (Stub)" and alpha["binary"] == "/bin/alpha"
    assert alpha["accounts"] == [] and alpha["logins"] == []  # before the switch-over, no accounts or logins
    assert alpha["found"] == [{"folder": str(tmp_path / "a"), "own_home": False}]
    [beta] = r["not_ready"]
    assert beta["adapter"] == "beta" and not beta["installed"] and beta["supported"]
    assert beta["install_command"].startswith("curl ") and beta["version"] is None and beta["found"] == []
    # an identity's match never leaves the read: nothing of it is in the reply
    assert "'m'" not in repr(r) and "Paul" not in repr(r)


def test_a_found_row_is_drawn_only_for_a_signed_in_default_home(monkeypatch, tmp_path):
    _registry(
        monkeypatch,
        _Stub("keyed", found="/bin/k", home=tmp_path / "k", creds=True),  # an API key, no identity: signed in
        _Stub("expired", found="/bin/e", home=tmp_path / "e", creds=False),
        _Stub("fresh", found="/bin/f", home=tmp_path / "f"),  # nothing recorded
    )
    got = {t["adapter"]: t["found"] for t in tools.read(b"s" * 32, env={}, home=tmp_path)["tools"]}
    assert got == {"keyed": [{"folder": str(tmp_path / "k"), "own_home": False}], "expired": [], "fresh": []}


def test_an_own_home_tools_found_row_says_so(monkeypatch, tmp_path):
    own = tmp_path / ".grok"
    _registry(monkeypatch, _Stub("own", found="/bin/o", home=own, creds=True, own_home=own))
    [card] = tools.read(b"s" * 32, env={}, home=tmp_path)["tools"]
    assert card["found"] == [{"folder": str(own), "own_home": True}]


def test_one_tools_failing_read_leaves_the_others_and_says_nothing_of_it(monkeypatch, tmp_path):
    class Broken(_Stub):
        def identity(self, home, salt):
            raise ValueError("secret-key-in-the-words")

    _registry(monkeypatch, Broken("broken", found="/bin/x", home=tmp_path, creds=True))
    r = tools.read(b"s" * 32, env={}, home=tmp_path)
    assert r["tools"][0]["found"]  # its credentials still stand
    assert "secret-key-in-the-words" not in repr(r)


def test_a_known_tool_is_not_ready_with_its_version_and_no_install(monkeypatch, tmp_path):
    stub = tmp_path / "codex"
    stub.write_text("#!/bin/sh\necho 'codex-cli 0.163.0'\n", encoding="utf-8")
    stub.chmod(0o755)
    _registry(
        monkeypatch,
        known=[
            {"name": "codex", "label": "Codex", "binary": "codex", "path": str(stub)},
            {"name": "opencode", "label": "opencode", "binary": "opencode", "path": None},
        ],
    )
    r = tools.read(b"s" * 32, env={"PATH": str(tmp_path)}, home=tmp_path)
    codex, opencode = r["not_ready"]
    assert codex["installed"] and not codex["supported"] and codex["install_command"] is None
    assert codex["version"] == "codex-cli 0.163.0" and tools.short_version(codex["version"]) == "0.163.0"
    assert not opencode["installed"] and opencode["version"] is None


def test_switched_is_a_logins_file(tmp_path):
    assert not tools.switched(tmp_path)
    (tmp_path / "logins.yml").write_text("logins: {}\n", encoding="utf-8")
    assert tools.switched(tmp_path)


def test_short_version():
    assert tools.short_version("2.1.327 (Claude Code)") == "2.1.327"
    assert tools.short_version("grok 1.0.77 (50ca579fa996) [stable]") == "1.0.77"
    assert tools.short_version("nightly") == "nightly" and tools.short_version(None) is None


def test_core_names_no_tool():
    src = Path(tools.__file__).read_text(encoding="utf-8").lower()
    assert not any(t in src for t in ('"claude', '"gemini', '"grok', '"codex'))


def test_the_cli_reads_or_checks(monkeypatch, capsys):
    from shiftlead import cli

    asked = []
    reply = {
        "host": "h",
        "read_at": "2026-11-19T00:00:00+00:00",
        "switched": False,
        "tools": [
            {
                "adapter": "alpha",
                "label": "Alpha",
                "binary": "/bin/alpha",
                "version": "1.2.3",
                "found": [{"folder": "/home/p/.alpha", "own_home": False}],
            }
        ],
        "not_ready": [
            {"adapter": "beta", "label": "Beta", "installed": False, "supported": True, "install_command": "x"},
            {"adapter": "codex", "label": "Codex", "installed": True, "supported": False, "version": "0.1.0"},
        ],
    }
    monkeypatch.setattr(cli, "call_sync", lambda m, **k: asked.append(m) or reply)
    p = cli.build_parser()
    for argv in (["tools"], ["tools", "check"]):
        a = p.parse_args(argv)
        assert a.fn(a) == 0
    assert asked == ["tools", "tools_check"]
    out = capsys.readouterr().out
    assert "Alpha  1.2.3" in out and "found here, signed in" in out
    assert "ao tools install beta" in out and "no adapter for it yet" in out


@pytest.mark.integration
async def test_the_read_is_kept_and_check_again_is_the_persons(agent, monkeypatch, tmp_path):
    from conftest import park_ticks

    from sessionorc.client import AgentError, LocalClient

    await park_ticks(agent)
    started = getattr(agent, "_tools_task", None)
    if started is not None:  # the start's own read, settled before the stub stands in
        await started
    reads = []
    monkeypatch.setattr(
        tools, "read", lambda salt, env=None, home=None, memory=None: reads.append(salt) or {"n": len(reads)}
    )
    agent._tools_kept = None
    async with LocalClient() as c:
        assert await c.call("tools") == {"n": 1}
        assert await c.call("tools") == {"n": 1}  # kept: a read makes none
        assert await c.call("tools_check") == {"n": 2}
        assert await c.call("tools") == {"n": 2}
        async with LocalClient(caller="ao-repo-worker") as w:
            assert await w.call("tools") == {"n": 2}  # a read, any caller's
            with pytest.raises(AgentError, match="cannot check this host's tools again"):
                await w.call("tools_check")
    assert len(set(reads)) == 1 and len(reads[0]) == 32  # one salt for the run


@pytest.mark.integration
def test_the_page_draws_the_hosts_tools_and_settings_links_it(subprocess_agent):
    from fastapi.testclient import TestClient

    from shiftlead.ui.app import create_app

    with TestClient(create_app()) as c:
        page = c.get("/tools")
        settings = c.get("/settings")
    assert page.status_code == 200
    assert 'id="toolspage"' in page.text and 'id="toolscheck"' in page.text and "Check again" in page.text
    assert "host agent unreachable" in page.text and 'class="warn hidden" id="agentdown"' in page.text
    assert 'href="/tools"' in settings.text


def test_the_reads_thread_never_holds_the_loops_end():
    """TD-2002: the read ran on the loop's default executor, which `asyncio.run` joins at its end, so a host agent
    told to stop waited for every `--version` its read had left — a child agent of the suite outlived its SIGTERM.
    The read's own daemon thread is awaited like the executor was, and holds no end."""
    import asyncio
    import threading
    import time

    from sessionorc.agent import _in_daemon_thread

    release = threading.Event()

    async def cut_short():
        task = asyncio.create_task(_in_daemon_thread(release.wait, 30))
        await asyncio.sleep(0.05)
        task.cancel()

    t0 = time.monotonic()
    asyncio.run(cut_short())
    assert time.monotonic() - t0 < 5, "the loop's end waited for the read"
    release.set()

    async def whole():
        assert await _in_daemon_thread(lambda a, b: a + b, 2, 3) == 5
        with pytest.raises(ZeroDivisionError):
            await _in_daemon_thread(lambda: 1 / 0)

    asyncio.run(whole())


@pytest.mark.integration
async def test_a_test_agent_makes_no_start_read(agent, monkeypatch):
    """TD-2002: the suite's host agents make no start read (conftest's `_no_start_tools_read`); one asked for still
    answers `tools` with a read of its own."""
    from sessionorc.client import LocalClient

    assert agent._tools_task is None and agent._tools_kept is None
    monkeypatch.setattr(tools, "read", lambda salt, env=None, home=None, memory=None: {"read": True})
    async with LocalClient() as c:
        assert await c.call("tools") == {"read": True}


@pytest.mark.integration
def test_a_stop_is_never_held_by_the_start_read(tmp_path, monkeypatch):
    """TD-2002: a child agent whose start read is stuck in a slow `--version` stops at its SIGTERM, exit 0."""
    import os
    import signal
    import subprocess
    import sys
    import time

    from conftest import CHILD, kill_private_server, private_socket_name, wait_for_sync

    from sessionorc.tmux import Tmux

    slow = tmp_path / "slow-bin"
    slow.mkdir()
    token = f"12.{os.getpid()}{time.monotonic_ns() % 10**6}"  # past the 10 s bound, and this run's own `sleep`
    for name in ("claude", "gemini"):  # each found on the PATH; its `--version` sits out its whole bound
        b = slow / name
        b.write_text(f"#!/bin/sh\nexec sleep {token} # {name}\n")
        b.chmod(0o755)
    home = tmp_path / "home"
    sock_name = private_socket_name()
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    monkeypatch.setenv("SHIFTLEAD_TMUX_SOCKET", sock_name)
    monkeypatch.setenv("AO_TEST_TOOLS_AT_START", "1")
    monkeypatch.setenv("PATH", f"{slow}{os.pathsep}{os.environ['PATH']}")
    proc = subprocess.Popen(
        [sys.executable, str(CHILD), sock_name],
        env=dict(os.environ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        sock = home / "agent.sock"
        assert wait_for_sync(lambda: sock.exists() or proc.poll() is not None, timeout=10.0)
        assert proc.poll() is None, proc.communicate(timeout=5)[1]
        ps = ["ps", "-eo", "args"]
        assert wait_for_sync(lambda: f"sleep {token}".encode() in subprocess.run(ps, capture_output=True).stdout)
        t0 = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        _, err = proc.communicate(timeout=8)
        assert proc.returncode == 0, err
        assert time.monotonic() - t0 < 5, "the stop waited for the start's read"
    finally:
        if proc.poll() is None:
            proc.kill()
        kill_private_server(Tmux(socket_name=sock_name))
