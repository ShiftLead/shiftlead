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
    assert got["permission_prompts"] == "ask" and got["model"] == "sonnet" and got["account"] == "c"
    assert got["config_dir"] == str(Path("~/.claude-conformance").expanduser())
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
    hook.capture("statusline", "not json")  # never fails the hook
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"\xff\xfe"), encoding="utf-8"))
    assert hook.main() == 0  # stdin that is not UTF-8 is no payload, and nothing is captured
    assert len((tmp_path / "hooks.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert not (tmp_path / "statusline.jsonl").exists()


class FakeAgent:
    """A host agent the walk drives: each call moves one record the way the real tool's hooks would."""

    def __init__(self, work: Path, *, permission: bool = True, lag: int = 0):
        self.work, self.permission, self.lag = work, permission, lag
        self.pending_after: dict | None = None
        self.rec: dict = {}
        self.calls: list[str] = []
        self.inbox_read = False

    def _settle(self, **kw):
        self.rec.update(state="idle", confidence="hook", pending=None, **kw)

    def __call__(self, method: str, **p):
        self.calls.append(method)
        if method == "create":
            n = len([c for c in self.calls if c == "create"])
            self.rec = {"id": f"ao-walk-{n}", "adapter_id": p.get("resume") or "tool-1", "state": "working"}
            self._settle(unread=0, wakes=[], sends=[])
            return dict(self.rec)
        if method == "get":
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
        if method == "decide":
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


def test_a_step_that_fails_says_what_it_read_and_stops_the_walk(tmp_path, monkeypatch):
    cw = _load()
    monkeypatch.setattr(cw, "TURN_WAIT", 0.0)
    fake, said = FakeAgent(tmp_path, permission=False), []
    walk = cw.Walk("claude-code", "conformance", tmp_path, fake, out=said.append)
    assert not walk.run()
    assert walk.results[-1][:2] == ("a permission", False)
    assert said[-1].startswith("FAIL  a permission: no permission was seen: state idle (hook)")
    assert "msg" not in fake.calls  # nothing after a failed step
