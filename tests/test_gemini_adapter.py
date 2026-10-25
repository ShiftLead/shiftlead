"""The Gemini CLI adapter (design §4.3 *The second adapter: Gemini CLI*, TD-785 slice 2): the launch and
its settings layer, trust by environment, the hook's mapping of each event to a state, the kill guard's
block, the title's glyphs, the credential check, and `shiftlead-hook --adapter gemini`'s dispatch."""

from __future__ import annotations

import io
import json
import os
import stat
import sys
import uuid
from pathlib import Path

import pytest

from sessionorc import adapters
from shiftlead import hook_entry
from shiftlead.adapters import gemini
from shiftlead.adapters.gemini import GeminiAdapter, hook
from shiftlead.kill_guard import REASON


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text(
        "default: gem\nprofiles:\n  gem: {adapter: gemini, account: paul, model: gemini-3-pro}\n"
        f"  grind: {{adapter: gemini, account: grind, config_dir: {tmp_path / 'g'}}}\n"
        "  asks: {adapter: gemini, permission_prompts: ask}\n"
        "  close: {adapter: gemini, permission_prompts: all}\n"
    )
    machine = tmp_path / "etc" / "gemini-settings.json"
    monkeypatch.setattr(gemini, "MACHINE_LAYER", machine)
    monkeypatch.setattr(gemini, "_lstat", rooted())
    machine.parent.mkdir()
    machine.write_text(gemini.write_layer().read_text())  # installed: the person ran the line
    return tmp_path


def rooted(mine: str | None = None, writable: str | None = None):
    """An `lstat` that reads every path root-owned and 0755 but the one named `mine` (the user's) and
    the one named `writable` (group-writable): the tool's test, run on a test's files."""

    def lstat(p):
        st = os.lstat(p)
        uid = os.getuid() if mine is not None and str(p) == mine else 0
        mode = stat.S_IFMT(st.st_mode) | 0o755 | (stat.S_IWGRP if writable is not None and str(p) == writable else 0)
        return os.stat_result((mode, st.st_ino, st.st_dev, st.st_nlink, uid, 0, st.st_size, 0, 0, 0))

    return lstat


def test_launch_argv_and_env(home):
    ad = GeminiAdapter(binary="/opt/gemini")
    spec = ad.launch(profile="", resume=None, prompt="do it", unattended=False, cwd=home, name="t1")
    assert spec.argv[:3] == ["/opt/gemini", "--session-id", spec.adapter_id] and uuid.UUID(spec.adapter_id)
    assert spec.argv[3:] == ["--model", "gemini-3-pro"] and spec.model == "gemini-3-pro"
    assert spec.first_prompt == "do it" and not any("do it" in a for a in spec.argv)  # typed, never passed
    env = spec.env
    assert env["GEMINI_CLI_TRUST_WORKSPACE"] == "true"  # trust by environment; no trust file written
    assert env["GEMINI_FORCE_FILE_STORAGE"] == "true" and env["GOOGLE_API_KEY"] == ""
    assert env["CLI_TITLE"] == "t1" and "GEMINI_CLI_HOME" not in env  # no config_dir: the tool's own `~`
    assert not (home / ".gemini").exists()
    assert env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"] == str(gemini.MACHINE_LAYER)
    layer = json.loads(Path(env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"]).read_text())
    assert set(layer["hooks"]) == set(gemini.HOOK_EVENTS)
    cmd = layer["hooks"]["BeforeTool"][0]["hooks"][0]
    assert cmd["command"].endswith(" --adapter gemini") and cmd["timeout"] == 10_000  # the tool's milliseconds
    assert layer["hooksConfig"] == {"notifications": False} and layer["general"] == {"enableAutoUpdate": False}
    assert layer["ui"] == {
        "hideTips": True,
        "hideBanner": True,
        "dynamicWindowTitle": True,
        "hideWindowTitle": False,
        "showStatusInTitle": False,
    }
    # a background command's end wakes the session (TD-1007, design §4.3 *A wait the guard refuses*)
    assert layer["tools"] == {"shell": {"backgroundCompletionBehavior": "inject"}}
    assert layer["experimental"] == {"modelSteering": True}
    assert gemini.layer_wakes() and env[hook.WAKES_ENV] == "1"


def test_a_resume_an_unattended_launch_and_ask(home):
    ad = GeminiAdapter(binary="gemini")
    g = ad.launch(profile="grind", resume="abc-123", prompt=None, unattended=True, cwd=home)
    assert g.adapter_id == "abc-123" and g.argv[1:3] == ["--resume", "abc-123"] and "--session-id" not in g.argv
    assert g.argv[-2:] == ["--approval-mode", "yolo"]  # `permission_prompts: skip`, the default
    assert g.env["GEMINI_CLI_HOME"] == str(home / "g") and "CLI_TITLE" not in g.env
    assert g.env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"] == str(gemini.MACHINE_LAYER)  # one layer for every shape
    a = ad.launch(profile="asks", resume=None, prompt=None, unattended=True, cwd=home)
    assert "yolo" not in a.argv  # under `ask` the tool asks
    c = ad.launch(profile="close", resume=None, prompt=None, unattended=True, cwd=home)
    assert c.argv[3:] == a.argv[3:]  # no `asking_args`: under `all` the launch is `ask`'s (§4.3, TD-823)
    assert gemini._without_yolo(["--approval-mode", "yolo", "-s", "--yolo", "--approval-mode", "auto_edit"]) == [
        "-s",
        "--approval-mode",
        "auto_edit",
    ]


def test_the_adapter_has_no_permission_channel(monkeypatch):
    # registered here alone: its entry point waits for the slice that ships its conformance fixtures
    adapters.names()
    monkeypatch.setitem(adapters._REGISTRY, "gemini", GeminiAdapter())
    assert adapters.permission_channel("gemini") is False and adapters.has_agent("gemini")
    assert adapters.get("gemini").classify(None, ["anything"]) is None  # hook-fed


@pytest.mark.parametrize(
    ("payload", "want"),
    [
        ({"hook_event_name": "SessionStart", "source": "startup"}, {"state": "idle", "pending": None}),
        ({"hook_event_name": "SessionStart", "source": "resume"}, {"state": "idle", "pending": None}),
        ({"hook_event_name": "SessionEnd", "reason": "exit"}, {"state": "exited", "pending": None, "reason": "exit"}),
        ({"hook_event_name": "SessionEnd", "reason": "clear"}, None),
        ({"hook_event_name": "BeforeAgent", "prompt": "hi"}, {"state": "working", "pending": None, "prompt": True}),
        ({"hook_event_name": "AfterAgent"}, {"state": "idle", "pending": None}),
        (
            {"hook_event_name": "AfterTool", "tool_name": "read_file"},
            {"state": "working", "pending": None, "event": "AfterTool:read_file"},
        ),
        ({"hook_event_name": "PreCompress"}, None),
        ({"hook_event_name": "Notification", "notification_type": "Other"}, None),
    ],
)
def test_each_event_maps_to_its_state(payload, want):
    assert hook.translate(payload) == want


def test_the_ids_and_the_first_transcript_ride_every_report():
    p = {"hook_event_name": "SessionStart", "source": "clear", "session_id": "new-id", "transcript_path": ""}
    assert hook.translate(p) == {"adapter_id": "new-id", "state": "idle", "pending": None}  # a `/clear` adopts it
    p = {"hook_event_name": "AfterAgent", "session_id": "s", "transcript_path": "/h/.gemini/tmp/x/chats/s.jsonl"}
    assert hook.translate(p)["transcript"] == "/h/.gemini/tmp/x/chats/s.jsonl"


def test_a_confirmation_is_a_permission_or_a_question_with_no_tool_use_id():
    exec_ = {
        "hook_event_name": "Notification",
        "notification_type": "ToolPermission",
        "message": "Tool Shell requires execution",
        "details": {"type": "exec", "title": "Shell", "command": "rm -rf build", "rootCommand": "rm"},
    }
    r = hook.translate(exec_)
    assert r == {
        "state": "needs-you",
        "pending": {"kind": "permission", "text": "Tool Shell requires execution: rm -rf build"},
    }
    assert "kind" not in r  # never the waiting path: no Gemini hook answers a confirmation
    ask = {**exec_, "message": "Tool requires confirmation", "details": {"type": "ask_user", "title": "Ask"}}
    assert hook.translate(ask)["pending"] == {"kind": "question", "text": "Tool requires confirmation"}


def test_the_kill_guard_blocks_a_shell_command_with_exit_2(home, monkeypatch, capsys):
    sent: list[dict] = []
    monkeypatch.setattr(hook, "call_agent", lambda params, timeout: sent.append(params))
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x-g")
    payload = {
        "hook_event_name": "BeforeTool",
        "tool_name": "run_shell_command",
        "tool_input": {"command": "pkill -f x"},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert hook.main() == hook.BLOCK
    out = capsys.readouterr()
    assert REASON in out.err and out.out == ""  # stdout is the tool's JSON channel: nothing on it
    assert sent == []  # no call to the host agent: the tool never runs (§4.3 *The kill guard*)
    ok = {**payload, "tool_input": {"command": "kill 1234"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(ok)))
    assert hook.main() == 0
    assert sent and sent[0]["state"] == "working" and sent[0]["session"] == "ao-x-g"  # a call it passes reports
    other = {**payload, "tool_name": "write_file", "tool_input": {"command": "pkill -f x"}}
    assert hook.refused_command(other) is None


WATCH = "timeout 1800 gh pr checks 12 --watch"


def _shell(monkeypatch, command: str, **tool_input) -> None:
    payload = {
        "hook_event_name": "BeforeTool",
        "tool_name": "run_shell_command",
        "tool_input": {"command": command, **tool_input},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))


def test_the_wait_guard_blocks_an_unattended_foreground_ci_watch(home, monkeypatch, capsys):
    """TD-1007 (design §4.3 *A wait the guard refuses*): a foreground CI watch goes with `wait: true`,
    and the reply's `refuse_wait` blocks it with Gemini's words; `is_background: true`, an interactive
    record, no reply, and a launch under a layer that does not wake let it run; a command the kill
    guard refuses is refused for that alone, and the wait is not asked."""
    from shiftlead import wait_guard

    sent: list[dict] = []
    reply: dict = {"refuse_wait": True}

    def agent(params, timeout):
        sent.append(params)
        return reply

    monkeypatch.setattr(hook, "call_agent", agent)
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x-g")
    monkeypatch.setenv(hook.WAKES_ENV, "1")
    for extra in ({}, {"is_background": False}, {"is_background": "true"}):
        _shell(monkeypatch, WATCH, **extra)
        assert hook.main() == hook.BLOCK
        out = capsys.readouterr()
        assert out.err.strip() == wait_guard.GEMINI_REASON and out.out == ""
        assert sent[-1]["wait"] is True and sent[-1]["state"] == "working"
    assert "`is_background: true`" in wait_guard.GEMINI_REASON and wait_guard.REASON != wait_guard.GEMINI_REASON
    sent.clear()
    _shell(monkeypatch, WATCH, is_background=True)  # the background form: run, unasked
    assert hook.main() == 0 and "wait" not in sent[-1]
    reply = {}  # an interactive record: the host agent sends no `refuse_wait`
    _shell(monkeypatch, WATCH)
    assert hook.main() == 0 and sent[-1]["wait"] is True
    reply = None  # no reply (past the wait): the watch runs
    _shell(monkeypatch, WATCH)
    assert hook.main() == 0
    reply = {"refuse_wait": True}
    _shell(monkeypatch, "gh pr checks 12")  # one poll is no watch
    assert hook.main() == 0 and "wait" not in sent[-1]
    sent.clear()
    _shell(monkeypatch, f"pkill -f x; {WATCH}")  # the kill guard's refusal alone, nothing sent
    assert hook.main() == hook.BLOCK
    assert capsys.readouterr().err.strip() == REASON and sent == []
    monkeypatch.delenv(hook.WAKES_ENV)  # launched under a layer whose background end wakes nothing
    _shell(monkeypatch, WATCH)
    assert hook.main() == 0 and "wait" not in sent[-1]


def test_an_unreached_host_agent_queues_the_watch_without_wait(home, monkeypatch):
    def down(params, timeout):
        raise OSError("no socket")

    queued: list[tuple] = []
    monkeypatch.setattr(hook, "call_agent", down)
    monkeypatch.setattr(hook.EventQueue, "append", lambda self, sid, ev: queued.append((sid, ev)))
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x-g")
    monkeypatch.setenv(hook.WAKES_ENV, "1")
    _shell(monkeypatch, WATCH)
    assert hook.main() == 0  # a wait, not a kill: the call runs
    assert queued and queued[0][1]["state"] == "working" and "wait" not in queued[0][1]


def test_an_unreached_host_agent_queues_the_event(home, monkeypatch):
    def down(params, timeout):
        raise OSError("no socket")

    queued: list[tuple] = []
    monkeypatch.setattr(hook, "call_agent", down)
    monkeypatch.setattr(hook.EventQueue, "append", lambda self, sid, ev: queued.append((sid, ev)))
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x-g")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "AfterAgent"})))
    assert hook.main() == 0
    assert queued and queued[0][0] == "ao-x-g" and queued[0][1]["state"] == "idle" and "session" not in queued[0][1]


def test_the_title_maps_its_leading_glyph_alone():
    pad = " " * 40
    assert gemini.title_state(f"◇  Ready (t1){pad}") == "idle"
    assert gemini.title_state(f"✦  Working… (t1){pad}") == "working"
    assert gemini.title_state(f"⏲  Working… (t1){pad}") == "working"
    assert gemini.title_state(f"✋  Action Required (t1){pad}") == "needs-you"
    assert gemini.title_state("kmaster@box: ~/src") is None and gemini.title_state("") is None


def test_credentials_read_the_homes_auth_type_and_credential(home, monkeypatch):
    from shiftlead import profiles

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    prof = profiles.get("grind")
    ad = GeminiAdapter(binary="gemini")
    assert ad.credentials_ok(prof) is None  # no settings: the auth picker would open
    gem = home / "g" / ".gemini"
    gem.mkdir(parents=True)
    (gem / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": "oauth-personal"}}}))
    assert ad.credentials_ok(prof) is None  # an auth type and no credential
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert ad.credentials_ok(prof) is True  # …or the key in the environment
    monkeypatch.delenv("GEMINI_API_KEY")
    (gem / "oauth_creds.json").write_text("{}")
    assert ad.credentials_ok(prof) is True
    rows = {r["profile"]: r for r in ad.doctor_profiles()}
    assert set(rows) == {"gem", "grind", "asks", "close"}
    assert rows["grind"]["config_dir"] == str(home / "g") and rows["grind"]["credentials"] is True
    assert "key" not in rows["grind"] and "note" not in rows["grind"]


def test_a_metered_profile_its_extra_args_its_key_and_the_precautions_note(home, monkeypatch):
    """A profile's `extra_args` reach the argv; `ao doctor`'s row of a metered profile says whether its key
    is set, and a `GOOGLE_API_KEY` in the host agent's environment is noted (design §4.3, §4.7, TD-843)."""
    (home / "home" / "profiles.yml").write_text(
        "profiles:\n  api: {adapter: gemini, billing: metered, extra_args: [--debug, --sandbox],\n"
        f"    config_dir: {home / 'api'}}}\n"
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    ad = GeminiAdapter(binary="gemini")
    spec = ad.launch(profile="api", resume=None, prompt=None, unattended=False, cwd=home)
    assert spec.argv[3:] == ["--debug", "--sandbox"]
    (row,) = ad.doctor_profiles()
    assert row["metered"] is True and row["credentials"] is None and row["key"] is False and "note" not in row
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    (row,) = ad.doctor_profiles()
    assert row["key"] is True and "GOOGLE_API_KEY" in row["note"]


def test_one_wanted_copy_whatever_the_profile_naming_the_hook_beside_the_interpreter(home, monkeypatch, tmp_path):
    """TD-875: `write_layer` writes one file for every profile and launch, removes the per-profile layers
    earlier builds wrote, and names `shiftlead-hook` beside the interpreter, whatever `PATH` finds first."""
    sets = home / "home" / "gemini-settings"
    (sets / "grind+unattended.json").write_text("{}")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "shiftlead-hook").write_text("#!/bin/sh\n")
    (elsewhere / "shiftlead-hook").chmod(0o755)
    monkeypatch.setenv("PATH", f"{elsewhere}{os.pathsep}{os.environ['PATH']}")
    p = gemini.write_layer()
    assert p == sets / "layer.json" and sorted(x.name for x in sets.iterdir()) == ["layer.json"]
    cmd = json.loads(p.read_text())["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert cmd == f"{Path(sys.executable).parent / 'shiftlead-hook'} --adapter gemini"
    ad = GeminiAdapter(binary="gemini")
    for prof, unattended in (("gem", False), ("grind", True), ("asks", True)):
        ad.launch(profile=prof, resume=None, prompt=None, unattended=unattended, cwd=home)
        assert (
            sorted(x.name for x in sets.iterdir()) == ["layer.json"]
            and p.read_text() == gemini.MACHINE_LAYER.read_text()
        )


@pytest.mark.parametrize(
    ("case", "why"),
    [
        ("missing", "not installed"),
        ("mine", "is not root-owned"),
        ("writable", "is writable by group or others"),
        ("dir", "etc is not root-owned"),
        ("unresolved", "names no hook command that resolves"),
    ],
)
def test_a_launch_is_refused_without_a_layer_the_tool_would_read(home, monkeypatch, case, why):
    """A missing layer, one the user owns, one group-writable, one under a directory not root's, and one
    naming no hook that resolves: the launch is refused in words naming `ao doctor`, and doctor reads lacking."""
    from shiftlead import doctor

    machine = gemini.MACHINE_LAYER
    if case == "missing":
        machine.unlink()
    elif case == "mine":
        monkeypatch.setattr(gemini, "_lstat", rooted(mine=str(machine)))
    elif case == "writable":
        monkeypatch.setattr(gemini, "_lstat", rooted(writable=str(machine)))
    elif case == "dir":
        monkeypatch.setattr(gemini, "_lstat", rooted(mine=str(machine.parent)))
    else:
        doc = json.loads(machine.read_text())
        for g in doc["hooks"].values():
            g[0]["hooks"][0]["command"] = "/nowhere/shiftlead-hook --adapter gemini"
        machine.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="the Gemini layer is not installed — run the line `ao doctor` prints") as e:
        GeminiAdapter(binary="gemini").launch(profile="gem", resume=None, prompt=None, unattended=False, cwd=home)
    assert why in str(e.value)
    rows = doctor.hooks(
        {"layers": [{"profile": r["profile"], "layers": r["layers"]} for r in GeminiAdapter().doctor_profiles()]}, None
    )
    (row,) = rows  # one line for the one file, though four profiles name it
    assert row["verdict"] == "lacking" and row["text"].endswith(gemini.INSTALL_LINE)
    words = {"missing": "not installed", "unresolved": "names no hook command that resolves"}.get(
        case, "not root-owned"
    )
    assert f"hooks — Gemini layer {words}" in row["text"]


def test_a_layer_differing_in_a_setting_launches_and_doctor_reads_it_stale(home):
    from shiftlead import doctor

    def lines():
        return doctor.hooks(
            {"layers": [{"profile": r["profile"], "layers": r["layers"]} for r in GeminiAdapter().doctor_profiles()]},
            None,
        )

    assert [r["verdict"] for r in lines() if "Gemini" in r["text"]] == []  # the same bytes: ok
    doc = json.loads(gemini.MACHINE_LAYER.read_text())
    doc["ui"]["hideTips"] = False
    gemini.MACHINE_LAYER.write_text(json.dumps(doc))
    spec = GeminiAdapter(binary="gemini").launch(profile="gem", resume=None, prompt=None, unattended=False, cwd=home)
    assert spec.env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"] == str(gemini.MACHINE_LAYER)
    (row,) = [r for r in lines() if "Gemini" in r["text"]]
    assert row["verdict"] == "warning" and row["text"] == f"hooks — Gemini layer stale: {gemini.INSTALL_LINE}"


def test_the_tools_test_follows_a_symlink_to_where_it_points(tmp_path, monkeypatch):
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    monkeypatch.setattr(gemini, "_lstat", rooted(mine=str(real)))
    assert gemini.insecure(link) == f"{real} is not root-owned"
    monkeypatch.setattr(gemini, "_lstat", rooted())
    assert gemini.insecure(link) is None


def test_the_hook_entry_dispatches_on_the_adapter_flag(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(hook, "main", lambda: called.append("gemini") or 0)
    monkeypatch.setattr(sys, "argv", ["shiftlead-hook", "--adapter", "gemini"])
    assert hook_entry.adapter() == "gemini" and hook_entry.main() == 0 and called == ["gemini"]
    monkeypatch.setattr(sys, "argv", ["shiftlead-hook"])
    assert hook_entry.adapter() == "claude-code"
    monkeypatch.setattr(sys, "argv", ["shiftlead-hook", "--adapter"])  # a flag with no name: the default
    assert hook_entry.adapter() == "claude-code"
