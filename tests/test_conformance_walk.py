"""`scripts/conformance.py`, the conformance suite's live walk (design §4.3 *The conformance suite*, TD-784):
its refusals, the scratch home's profile, the hook's capture, and the steps against a recorded host agent.
The walk itself runs by hand against a real tool, never here."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

from sessionorc.adapters import CAPTURE_ENV

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "conformance.py"


def _load():
    spec = importlib.util.spec_from_file_location("conformance_walk", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_it_refuses_ci_and_a_walk_with_no_profile(monkeypatch, capsys):
    cw = _load()
    assert "CI" in cw.refusal({"CI": "true"}, "conformance")
    assert "--profile" in cw.refusal({}, None)
    assert cw.refusal({}, "conformance") is None
    monkeypatch.setenv("CI", "1")
    assert cw.main(["claude-code", "--profile", "conformance"]) == 2
    monkeypatch.delenv("CI")
    assert cw.main(["claude-code"]) == 2
    assert capsys.readouterr().err.count("refused") == 2


def test_it_refuses_an_adapter_with_no_agent(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    assert _load().main(["shell", "--profile", "p"]) == 2
    assert "no agent adapter" in capsys.readouterr().err


def _profiles(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "profiles.yml"
    p.write_text(body, encoding="utf-8")
    return p


def test_the_scratch_profile_is_the_named_ones_asking_its_permissions(tmp_path):
    cw = _load()
    live = _profiles(
        tmp_path,
        "default: grind\nprofiles:\n"
        "  grind: {account: a}\n"
        "  conformance: {adapter: claude-code, account: c, config_dir: ~/.claude-conformance, model: sonnet}\n"
        "  other: {adapter: gemini-cli, account: g, config_dir: /tmp/g}\n",
    )
    got = cw.scratch_profile("claude-code", "conformance", live)
    assert got["permission_prompts"] == "all" and got["model"] == "sonnet" and got["account"] == "c"
    assert got["config_dir"] == str(Path("~/.claude-conformance").expanduser())
    assert "extra_args" not in got  # the adapter's `asking_args` come with `all` (§4.3, TD-823)
    with pytest.raises(cw.Refused, match="no profile 'missing'"):
        cw.scratch_profile("claude-code", "missing", live)
    with pytest.raises(cw.Refused, match="runs gemini-cli"):
        cw.scratch_profile("claude-code", "other", live)
    with pytest.raises(cw.Refused, match="no config_dir"):
        cw.scratch_profile("claude-code", "grind", live)  # the person's own tool home is never walked
    with pytest.raises(cw.Refused, match="no profile"):
        cw.scratch_profile("claude-code", "default", tmp_path / "absent.yml")


def test_a_config_dir_shared_or_the_tools_default_is_refused(tmp_path, monkeypatch):
    cw = _load()
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    live = _profiles(
        tmp_path,
        "profiles:\n"
        "  mine: {config_dir: ~/.claude}\n"
        f"  a: {{config_dir: {tmp_path / 'x'}}}\n"
        f"  b: {{config_dir: {tmp_path / 'x'}}}\n",
    )
    with pytest.raises(cw.Refused, match="the tool's default home"):
        cw.scratch_profile("claude-code", "mine", live)
    with pytest.raises(cw.Refused, match="shares it with b"):
        cw.scratch_profile("claude-code", "a", live)


def test_the_agent_env_names_the_capture_and_no_tool_home(tmp_path):
    cw = _load()
    env = cw.agent_env(tmp_path, "ao-conf-x", tmp_path / "captured")
    assert env[CAPTURE_ENV] == str(tmp_path / "captured")
    assert "CLAUDE_CONFIG_DIR" not in env and "SHIFTLEAD_SESSION" not in env
    assert env["SHIFTLEAD_HOME"] == str(tmp_path) and env["SHIFTLEAD_TMUX_SOCKET"] == "ao-conf-x"
    assert env["PATH"].split(":")[0] == str(Path(sys.executable).parent)  # this checkout's hook, not the install's
    assert CAPTURE_ENV not in cw.agent_env(tmp_path, "ao-conf-x", None)


def test_the_hook_captures_each_payload_as_handed_it(tmp_path, monkeypatch):
    from shiftlead.adapters.claude_code import hook

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x")
    monkeypatch.setattr(hook, "call_agent", lambda params, timeout: None)
    payload = {"hook_event_name": "Stop", "session_id": "s-1", "stop_hook_active": False}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert hook.main() == 0
    assert not list(tmp_path.glob("*.jsonl"))  # no capture unless asked
    monkeypatch.setenv(CAPTURE_ENV, str(tmp_path))
    for p in (payload, {**payload, "hook_event_name": "UserPromptSubmit", "prompt": "hi"}):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(p)))
        assert hook.main() == 0
    lines = (tmp_path / "hooks.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["hook_event_name"] for x in lines] == ["Stop", "UserPromptSubmit"]
    assert json.loads(lines[1])["prompt"] == "hi"  # every field as the tool handed it
    hook.capture("hooks", '{"a":  1, "b":"x"}\n')
    assert (tmp_path / "hooks.jsonl").read_text(encoding="utf-8").splitlines()[-1] == '{"a":  1, "b":"x"}'  # its bytes
    hook.capture("hooks", '{"a":\n 1}')
    assert (tmp_path / "hooks.jsonl").read_text(encoding="utf-8").splitlines()[-1] == '{"a": 1}'  # one line of JSONL
    hook.capture("hooks", '{"a": "x\u2028y"}')  # a line separator inside a string splits a line too
    assert (tmp_path / "hooks.jsonl").read_text(encoding="utf-8").splitlines()[-1] == '{"a": "x\\u2028y"}'
    hook.capture("statusline", "not json")  # never fails the hook
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"\xff\xfe"), encoding="utf-8"))
    assert hook.main() == 0  # stdin that is not UTF-8 is no payload, and nothing is captured
    assert len((tmp_path / "hooks.jsonl").read_text(encoding="utf-8").splitlines()) == 5
    assert not (tmp_path / "statusline.jsonl").exists()


class FakeAgent:
    """A host agent the walk drives: each call moves one record the way the real tool's hooks would."""

    def __init__(self, work: Path, *, permission: bool = True, lag: int = 0, late_end: int = 0, channel: bool = True):
        self.work, self.permission, self.lag, self.late_end = work, permission, lag, late_end
        self.channel = channel  # False: a tool with no permission channel (Gemini CLI), answered by an Enter
        self.ending = 0
        self.pending_after: dict | None = None
        self.rec: dict = {}
        self.calls: list[str] = []
        self.inbox_read = False

    def _settle(self, **kw):
        self.rec.update(state="idle", confidence="hook", pending=None, **kw)

    def __call__(self, method: str, **p):
        self.calls.append(method)
        if method == "create":
            assert not self.ending, "resumed before the killed process's own end hook landed"
            n = len([c for c in self.calls if c == "create"])
            self.rec = {"id": f"ao-walk-{n}", "adapter_id": p.get("resume") or "tool-1", "state": "working"}
            self._settle(unread=0, wakes=[], sends=[])
            if not self.channel:
                self.rec["permission_channel"] = False
            return dict(self.rec)
        if method == "get":
            if self.ending:
                self.ending -= 1
                if not self.ending:
                    self.rec["confidence"] = "hook"  # the killed process's `SessionEnd`, late
            if self.pending_after is not None:
                # the prompt's own hook has not landed: the last turn's idle reads `lag` times first
                if self.lag:
                    self.lag -= 1
                else:
                    self.rec.update(self.pending_after)
                    self.pending_after = None
            if self.rec.get("unread") and not self.inbox_read:
                # rung: the tool asks to run `ao inbox`, then reads it once allowed
                self.rec.update(
                    state="needs-you", pending={"kind": "permission", "text": "Bash: ao inbox", "tool_use_id": "t-2"}
                )
            return dict(self.rec)
        if method == "send":
            if p.get("wait"):
                self._settle(sends=[{"text": p["text"]}])
                return dict(self.rec)
            if self.permission:
                pending = {"kind": "permission", "text": "Bash: touch …", "tool_use_id": "t-1"}
                self.pending_after = {"state": "needs-you", "pending": pending}
            return None
        if method == "keys":
            assert not self.channel and p["keys"] == ["Enter"] and self.rec.get("state") == "needs-you"
            method, p = "decide", {"tool_use_id": self.rec["pending"]["tool_use_id"]}
        if method == "decide":
            assert self.channel or self.calls[-1] == "keys", "decide on a tool with no permission channel"
            if p["tool_use_id"] == "t-1":
                (self.work / "conformance-permission.txt").touch()
                self._settle()
            else:
                self.inbox_read = True
                self._settle(unread=0, wakes=[{"via": "doorbell"}])
            return None
        if method == "msg":
            self.rec["unread"] = 1
            return {"entry": {"id": "m-1"}}
        if method == "kill":
            self.rec["state"] = "exited"
            if self.late_end:
                self.rec["confidence"], self.ending = "tick", self.late_end
            return None
        if method == "transcript":
            cw = _load()
            return {
                "entries": [
                    {"kind": "prompt", "text": cw.SHORT_PROMPT},
                    {"kind": "prompt", "text": cw.PERMISSION_PROMPT},
                ]
            }
        raise AssertionError(method)


def test_the_walk_takes_every_step_in_order(tmp_path):
    cw = _load()
    fake, said = FakeAgent(tmp_path), []
    walk = cw.Walk("claude-code", "conformance", tmp_path, fake, out=said.append)
    assert walk.run()
    assert [n for n, ok, _ in walk.results if ok] == [
        "launch", "first hook", "a short prompt", "a permission", "a doorbell", "a resume", "the transcript"
    ]  # fmt: skip
    assert walk.id == "ao-walk-2" and walk.adapter_id == "tool-1"  # resumed on the same tool session
    assert "allowed: Bash: ao inbox" in said[4]


def test_the_last_turns_idle_is_not_the_permission_turns_end(tmp_path, monkeypatch):
    """The record reads the previous turn's `idle` until the prompt's own hook lands (the review of TD-784)."""
    cw = _load()
    monkeypatch.setattr(cw.time, "sleep", lambda _s: None)
    walk = cw.Walk("claude-code", "conformance", tmp_path, FakeAgent(tmp_path, lag=3), out=lambda _s: None)
    assert walk.run(), walk.results


def test_the_resume_waits_for_the_killed_processs_own_end(tmp_path, monkeypatch):
    """The killed tool's `SessionEnd` lands after the kill: a resume made first read it as its own end (TD-822)."""
    cw = _load()
    monkeypatch.setattr(cw.time, "sleep", lambda _s: None)
    walk = cw.Walk("claude-code", "conformance", tmp_path, FakeAgent(tmp_path, late_end=3), out=lambda _s: None)
    assert walk.run(), walk.results


def test_a_step_that_fails_says_what_it_read_and_stops_the_walk(tmp_path, monkeypatch):
    cw = _load()
    monkeypatch.setattr(cw, "TURN_WAIT", 0.0)
    fake, said = FakeAgent(tmp_path, permission=False), []
    walk = cw.Walk("claude-code", "conformance", tmp_path, fake, out=said.append)
    assert not walk.run()
    assert walk.results[-1][:2] == ("a permission", False)
    assert said[-1].startswith("FAIL  a permission: no permission was seen: state idle (hook)")
    assert "msg" not in fake.calls  # nothing after a failed step


def test_the_scratch_home_holds_the_one_profile_as_default_and_a_committed_walk_directory(tmp_path):
    """TD-797: `write_home`'s `profiles.yml` is read back by `profiles.load`, and the walk's directory is a repo."""
    import subprocess

    from shiftlead import profiles

    cw = _load()
    cfg = tmp_path / "claude-conformance"
    live = _profiles(
        tmp_path, f"profiles:\n  conformance: {{adapter: claude-code, account: c, model: sonnet, config_dir: {cfg}}}\n"
    )
    home = tmp_path / "home"
    home.mkdir()
    work = cw.write_home(home, "conformance", cw.scratch_profile("claude-code", "conformance", live))
    got, default = profiles.load(home / "profiles.yml")
    assert default == "conformance" and set(got) == {"conformance"}
    p = got["conformance"]
    assert (p.adapter, p.account, p.model, p.permission_prompts) == ("claude-code", "c", "sonnet", "all")
    assert p.config_dir == cfg
    assert work == home / "walk"
    head = subprocess.run(["git", "-C", str(work), "log", "--format=%s"], capture_output=True, text=True, check=True)
    assert head.stdout.split() == ["walk"]


def test_save_capture_copies_the_payloads_and_writes_the_pane_titles(tmp_path, monkeypatch):
    """TD-797: every `*.jsonl` of the capture directory and `titles.json` from the walk's tmux server
    land in `dest`; an empty capture copies no payload."""
    cw = _load()
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return cw.subprocess.CompletedProcess(cmd, 0, stdout="claude · walk\n✳ thinking\n", stderr="")

    monkeypatch.setattr(cw.subprocess, "run", run)
    capture = tmp_path / "capture"
    capture.mkdir()
    (capture / "Stop.jsonl").write_text('{"hook": "Stop"}\n', encoding="utf-8")
    (capture / "statusline.jsonl").write_text('{"model": "m"}\n', encoding="utf-8")
    (capture / "notes.txt").write_text("not a payload", encoding="utf-8")
    dest = tmp_path / "fixtures" / "claude-code" / "captured"
    out = cw.save_capture(capture, dest, "ao-walk")
    assert sorted(p.name for p in out) == ["Stop.jsonl", "statusline.jsonl", "titles.json"]
    assert (dest / "Stop.jsonl").read_text(encoding="utf-8") == '{"hook": "Stop"}\n'
    assert not (dest / "notes.txt").exists()
    assert json.loads((dest / "titles.json").read_text(encoding="utf-8")) == ["claude · walk", "✳ thinking"]
    assert calls == [["tmux", "-L", "ao-walk", "list-panes", "-a", "-F", "#{pane_title}"]]
    empty, dest2 = tmp_path / "empty", tmp_path / "dest2"
    empty.mkdir()
    assert [p.name for p in cw.save_capture(empty, dest2, "ao-walk")] == ["titles.json"]
    assert sorted(p.name for p in dest2.iterdir()) == ["titles.json"]


def test_a_tool_with_no_permission_channel_is_answered_by_an_enter_in_its_terminal(tmp_path):
    """TD-875: for `permission_channel = False` the walk, as the person, presses Enter (*Allow once*) by the
    `keys` RPC, for the permission step and the doorbell's `ao inbox` alike, and never calls `decide`."""
    cw = _load()
    fake, said = FakeAgent(tmp_path, channel=False), []
    walk = cw.Walk("gemini-cli", "conformance", tmp_path, fake, out=said.append)
    assert walk.run(), walk.results
    assert fake.calls.count("keys") == 2 and "decide" not in fake.calls
    assert "allowed in the terminal (Enter: Allow once)" in said[3]
    assert "allowed: Bash: ao inbox" in said[4]
    channel = FakeAgent(tmp_path)
    assert cw.Walk("claude-code", "conformance", tmp_path, channel, out=lambda _s: None).run()
    assert channel.calls.count("decide") == 2 and "keys" not in channel.calls


def test_an_enter_that_leaves_the_dialog_up_fails_the_step(tmp_path, monkeypatch):
    cw = _load()
    monkeypatch.setattr(cw, "TURN_WAIT", 0.0)
    fake, said = FakeAgent(tmp_path, channel=False), []
    real = fake.__call__

    def stuck(method, **p):
        return None if method == "keys" else real(method, **p)

    walk = cw.Walk("gemini-cli", "conformance", tmp_path, stuck, out=said.append)
    assert not walk.run()
    assert said[-1].startswith("FAIL  a permission: Enter pressed on Bash: touch …, and it still reads state needs-you")


def test_capture_saves_each_steps_pane_and_title(tmp_path, monkeypatch):
    """TD-875: under `--capture` every step, held or failed, snaps the session's pane (`capture-pane -e`)
    and the title the tool set, into `panes/<n>-<step>.txt`, which `save_capture` copies beside the hooks."""
    cw = _load()
    snaps = []
    fake = FakeAgent(tmp_path)
    walk = cw.Walk("claude-code", "conformance", tmp_path, fake, out=lambda _s: None, snap=lambda *a: snaps.append(a))
    assert walk.run()
    steps = [n for n, _ok, _s in walk.results]
    assert [n for n, _id in snaps] == [
        *steps[:3],
        "a permission needs-you",
        *steps[3:4],
        "a doorbell needs-you",
        *steps[4:],
    ]
    assert snaps[0] == ("launch", "ao-walk-1") and snaps[-1] == ("the transcript", "ao-walk-2")
    seen = []  # the dialog is snapped while it is up, before the press answers it
    dialog = FakeAgent(tmp_path, channel=False)
    real = dialog.__call__

    def watched(method, **p):
        if method == "keys":
            assert seen[-1].endswith("needs-you")
        return real(method, **p)

    assert cw.Walk("gemini-cli", "c", tmp_path, watched, out=lambda _s: None, snap=lambda n, _i: seen.append(n)).run()

    def boom(*_a):
        raise OSError("no tmux")

    assert cw.Walk("claude-code", "conformance", tmp_path, FakeAgent(tmp_path), out=lambda _s: None, snap=boom).run()

    monkeypatch.setattr(cw, "TURN_WAIT", 0.0)
    failed = []  # a failed step is snapped too
    walk = cw.Walk(
        "c",
        "c",
        tmp_path,
        FakeAgent(tmp_path, permission=False),
        out=lambda _s: None,
        snap=lambda n, _i: failed.append(n),
    )
    assert not walk.run() and failed[-1] == "a permission"

    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        out = "\x1b[2mType your message\x1b[0m\n" if "capture-pane" in cmd else "◇ Ready (walk)\n"
        return cw.subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(cw.subprocess, "run", run)
    capture = tmp_path / "capture"
    got = cw.save_pane(capture, "ao-walk", 4, "a permission", "ao-walk-1")
    assert got == capture / "panes" / "4-a-permission.txt"
    assert got.read_text(encoding="utf-8") == "title: ◇ Ready (walk)\n\x1b[2mType your message\x1b[0m\n"
    assert calls[0] == ["tmux", "-L", "ao-walk", "capture-pane", "-e", "-p", "-t", "=ao-walk-1:"]
    assert calls[1][-3:] == ["-t", "=ao-walk-1:", "#{pane_title}"]
    monkeypatch.setattr(
        cw.subprocess, "run", lambda cmd, **kw: cw.subprocess.CompletedProcess(cmd, 1, "", "no session")
    )
    with pytest.raises(OSError, match="no session"):
        cw.save_pane(capture, "ao-walk", 5, "a resume", "ao-gone")
    assert not (capture / "panes" / "5-a-resume.txt").exists()
    dest = tmp_path / "dest"
    out = cw.save_capture(capture, dest, "ao-walk")
    assert dest / "panes" / "4-a-permission.txt" in out
    assert (dest / "panes" / "4-a-permission.txt").read_text(encoding="utf-8") == got.read_text(encoding="utf-8")
