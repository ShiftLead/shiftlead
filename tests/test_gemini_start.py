"""Gemini CLI's start context, mail and the repo's start hooks (design §4.3 *The second adapter: Gemini CLI*,
TD-786 slice 2): `SessionStart` hands the tool the launch's start-context file and what the main checkout's
cadence runner printed as `additionalContext`, read before it reports; `BeforeAgent` hands it the unread line
the `hook` RPC counted, never at the doorbell's own prompt."""

from __future__ import annotations

import io
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from test_gemini_adapter import home  # noqa: F401 — the fixture: a scratch home, the layer installed

from sessionorc import adapters, mail
from sessionorc.client import LocalClient
from shiftlead.adapters import gemini
from shiftlead.adapters.gemini import GeminiAdapter, hook


def _run(monkeypatch, capsys, payload: dict, reply=None) -> tuple[list[dict], dict | None]:
    sent: list[dict] = []
    monkeypatch.setattr(hook, "call_agent", lambda params, timeout: sent.append(dict(params)) or reply)
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x-g")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert hook.main() == 0
    out = capsys.readouterr().out
    return sent, (json.loads(out) if out else None)


def test_the_start_hook_outlasts_the_runner_and_the_rest_stay_short():
    layer = gemini.layer_settings("/v/bin/shiftlead-hook")["hooks"]
    start = layer["SessionStart"][0]["hooks"][0]["timeout"]
    assert start >= (hook.START_HOOKS_TIMEOUT + 10 + 3) * 1000  # the runner, its `git` read, the report
    assert {ev: h[0]["hooks"][0]["timeout"] for ev, h in layer.items() if ev != "SessionStart"} == {
        ev: gemini.HOOK_TIMEOUT_MS for ev in gemini.HOOK_EVENTS if ev != "SessionStart"
    }


def test_a_launch_names_its_start_context_file_never_the_text(home):  # noqa: F811
    ad = GeminiAdapter(binary="/opt/gemini")
    assert ad.start_context is True
    spec = ad.launch(
        profile="", resume=None, prompt=None, unattended=True, cwd=home, start_context="PREFACE\n\nbe brief"
    )
    f = Path(spec.env[hook.START_CONTEXT_ENV])
    assert f.read_text() == "PREFACE\n\nbe brief" and stat.S_IMODE(f.stat().st_mode) == 0o600
    assert not any("be brief" in a for a in spec.argv)  # no prose in the argv (§4.1)
    again = ad.launch(profile="", resume=spec.adapter_id, prompt=None, unattended=True, cwd=home, start_context="X")
    assert again.env[hook.START_CONTEXT_ENV] == str(f) and f.read_text() == "X"  # a resume is handed it again
    bare = ad.launch(profile="", resume=None, prompt=None, unattended=True, cwd=home)
    assert hook.START_CONTEXT_ENV not in bare.env


def _repo_with_runner(tmp_path: Path, script: str, executable: bool = True) -> tuple[Path, Path]:
    """A main checkout whose `scripts/cadence_hooks.sh` runs `script`, and a worktree of it with none."""
    main = tmp_path / "repo"
    (main / "scripts").mkdir(parents=True)
    runner = main / "scripts" / "cadence_hooks.sh"
    runner.write_text(f"#!/bin/sh\n{script}\n")
    runner.chmod(0o755 if executable else 0o644)
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*git, "init", "-q", str(main)], check=True)
    subprocess.run([*git, "-C", str(main), "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    wt = tmp_path / "wt"
    subprocess.run([*git, "-C", str(main), "worktree", "add", "-q", "--detach", str(wt)], check=True)
    (wt / "scripts" / "cadence_hooks.sh").unlink(missing_ok=True)  # untracked: the worktree has no copy
    return main, wt


def test_session_start_hands_the_start_context_and_the_main_checkouts_runner_before_it_reports(
    tmp_path, monkeypatch, capsys
):
    main, wt = _repo_with_runner(tmp_path, f'echo "due: TD-1 ($1)"; pwd > {tmp_path / "ran"}')
    told = tmp_path / "ctx"
    told.write_text("PREFACE\n\nthe brief's start\n")
    monkeypatch.setenv(hook.START_CONTEXT_ENV, str(told))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(wt))
    payload = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "s1", "cwd": str(wt)}
    ran_at_report: list[bool] = []
    monkeypatch.setattr(
        hook, "report", lambda params, session: ran_at_report.append((tmp_path / "ran").exists()) or sent.append(params)
    )
    sent: list[dict] = []
    _, out = _run(monkeypatch, capsys, payload)
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "PREFACE\n\nthe brief's start\n\ndue: TD-1 (--session-start)",
        }
    }
    assert ran_at_report == [True] and sent[0]["state"] == "idle" and "mail" not in sent[0]  # run, then reported
    assert (tmp_path / "ran").read_text().strip() == str(wt)  # in the session's directory, as the tool's line runs
    # a resume and a `/clear` are handed it again
    for source in ("resume", "clear"):
        _, again = _run(monkeypatch, capsys, {**payload, "source": source})
        assert again == out


@pytest.mark.parametrize("case", ["not-executable", "no-repo", "fails"])
def test_no_runner_to_run_hands_the_start_context_alone(tmp_path, monkeypatch, capsys, case):
    if case == "no-repo":
        wt = tmp_path / "plain"
        wt.mkdir()
    else:
        script = "echo partial; exit 3" if case == "fails" else "echo never"
        _, wt = _repo_with_runner(tmp_path, script, executable=case != "not-executable")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(wt))
    told = tmp_path / "ctx"
    told.write_text("PREFACE")
    monkeypatch.setenv(hook.START_CONTEXT_ENV, str(told))
    _, out = _run(monkeypatch, capsys, {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(wt)})
    # a runner that fails still says what it printed, as the tool's own line would
    want = "PREFACE\n\npartial" if case == "fails" else "PREFACE"
    assert out["hookSpecificOutput"]["additionalContext"] == want
    # nothing told and nothing run: the hook prints nothing, the tool's JSON channel stays empty
    monkeypatch.delenv(hook.START_CONTEXT_ENV)
    told.unlink()
    if case != "fails":
        _, none = _run(monkeypatch, capsys, {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(wt)})
        assert none is None


def test_before_agent_hands_the_unread_line_the_host_agent_counted(monkeypatch, capsys):
    prompt = {"hook_event_name": "BeforeAgent", "prompt": "carry on", "session_id": "s1"}
    sent, out = _run(monkeypatch, capsys, prompt, reply={"unread": 2})
    assert sent[0]["mail"] is True and sent[0]["prompt"] is True
    assert out == {"hookSpecificOutput": {"hookEventName": "BeforeAgent", "additionalContext": mail.unread_line(2)}}
    for reply in (None, {"unread": 0}, {}):  # nothing unread, or a host agent that predates the count
        assert _run(monkeypatch, capsys, prompt, reply=reply)[1] is None
    # the doorbell's own prompt is that line already
    rung = {**prompt, "prompt": mail.unread_line(2)}
    assert _run(monkeypatch, capsys, rung, reply={"unread": 2})[1] is None
    # no other event asks for the count
    sent, out = _run(monkeypatch, capsys, {"hook_event_name": "AfterAgent"}, reply={"unread": 2})
    assert "mail" not in sent[0] and out is None


def test_an_unreached_host_agent_queues_before_agent_without_the_ask(monkeypatch, capsys):
    def down(params, timeout):
        raise OSError("no socket")

    queued: list[tuple] = []
    monkeypatch.setattr(hook, "call_agent", down)
    monkeypatch.setattr(hook.EventQueue, "append", lambda self, sid, ev: queued.append((sid, ev)))
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x-g")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "BeforeAgent", "prompt": "go"})))
    assert hook.main() == 0
    assert capsys.readouterr().out == ""
    assert queued and queued[0][1]["prompt"] is True and "mail" not in queued[0][1] and "session" not in queued[0][1]


def test_the_adapter_declares_its_mail_a_turns():
    ad = adapters.get("gemini")
    assert "mail" in adapters.implements(ad)
    assert ad.mail() == adapters.MailDelivery(how="turn", event="BeforeAgent")
    assert ad.mail().how in adapters.MAIL_HOWS


@pytest.mark.integration
async def test_the_hook_rpc_counts_unread_mail_only_when_asked(agent, composerstubs, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="g", dir=str(tmp_path), adapter="composer0", unattended=True))["id"]
        assert await agent.rpc_hook(sid, state="working", prompt=True, mail=True) == {"unread": 0}
        await c.call("msg", to=sid, text="hello")
        assert await agent.rpc_hook(sid, state="working", prompt=True, mail=True) == {"unread": 1}
        assert await agent.rpc_hook(sid, state="idle") is None
        assert await agent.rpc_hook("ao-nobody", state="idle", mail=True) == {"unread": 0}
