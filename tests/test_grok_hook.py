"""Grok Build's state feed (design §4.3 *The third adapter: Grok Build*, *The state feed*, TD-1637), read
against the payloads captured from the installed 1.0.77 (`fixtures/grok/captured/hooks.jsonl`)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from shiftlead.adapters.grok.hook import translate

CAPTURED = Path(__file__).parent / "conformance" / "fixtures" / "grok" / "captured" / "hooks.jsonl"
FIRST, SECOND = "11111111-2222-4333-8444-555555555555", "01a1d787-8d98-7951-a058-825197037226"


def _payloads() -> list[dict]:
    return [json.loads(line) for line in CAPTURED.read_text(encoding="utf-8").splitlines() if line.strip()]


def _strip(params: dict | None) -> dict | None:
    return None if params is None else {k: v for k, v in params.items() if k != "transcript"}


def test_the_captured_session_maps_event_by_event():
    got = [(p["hook_event_name"], _strip(translate(p))) for p in _payloads()]
    ids = {"adapter_id": FIRST}
    p1, p2 = "c7b876f3-db7c-4527-aa18-ca3555551909", "21208347-531e-48a0-95cc-ebb3f4b3f2fb"
    call1, call2 = "call-01eeb328-0e63-48bc-a46a-5ef3a12a90b8", "call-b547ec8e-61e7-47b8-801c-ef728f86f4e5"
    tool = "run_terminal_command"
    c1 = {"tool_use_id": pre1["tool_use_id"]} if (pre1 := got[2][1]) else {}
    assert [e for e, _ in got] == [
        "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop",
        "UserPromptSubmit", "PreToolUse", "Notification", "PostToolUse", "Stop",
        "SessionStart", "SessionEnd", "Stop", "SessionEnd", "Stop",
    ]  # fmt: skip
    post1 = got[3][1]
    assert pre1 is not None and post1 is not None
    assert pre1["tool_use_id"].startswith(call1[:30]) and post1["tool_use_id"] == pre1["tool_use_id"]
    expect = [
        {**ids, "state": "idle", "pending": None, "subagents_reset": True},
        {**ids, "state": "working", "pending": None, "prompt": True, "turn_start": True, "turn": p1},
        {**ids, "state": "working", "pending": None, "event": f"PreToolUse:{tool}", "call": "start", **c1},
        {**ids, "state": "working", "pending": None, "event": f"PostToolUse:{tool}", "call": "end", **c1},
        {**ids, "state": "idle", "pending": None, "turn_end": True, "turn": p1},
        {**ids, "state": "working", "pending": None, "prompt": True, "turn_start": True, "turn": p2},
        None,
        {**ids, "state": "needs-you", "pending": {"kind": "permission", "text": "Tool permission requested"}},
        None,
        {**ids, "state": "idle", "pending": None, "turn_end": True, "turn": p2},
        {"adapter_id": SECOND, "state": "idle", "pending": None, "subagents_reset": True},  # `/clear`: a new id
        {"adapter_id": SECOND, "state": "exited", "pending": None, "reason": "shutdown"},
        None,  # the session end's `Stop` (`shutdown`) is dropped
        {**ids, "state": "exited", "pending": None, "reason": "shutdown"},  # the first conversation's: core drops it
        None,
    ]  # fmt: skip
    assert got[6][1] is not None and got[6][1]["tool_use_id"].startswith(call2[:30])
    assert got[8][1] is not None and got[8][1]["tool_use_id"] == got[6][1]["tool_use_id"]
    for i in (6, 8):
        assert got[i][1]["state"] == "working" and got[i][1]["pending"] is None
    for i, want in enumerate(expect):
        if want is not None:
            assert got[i][1] == want, (i, got[i])


@pytest.mark.parametrize(
    ("tool", "tool_input", "text"),
    [
        ("ask_user_question", {"questions": [{"question": "Which branch?"}]}, "Which branch?"),
        ("ask_user_question", {"question": "Go on?"}, "Go on?"),
        ("enter_plan_mode", {}, "enter plan mode?"),
        ("exit_plan_mode", {"plan": "1. do it"}, "1. do it"),
    ],
)
def test_a_question_tool_is_a_question(tool, tool_input, text):
    p = {"hook_event_name": "PreToolUse", "sessionId": FIRST, "toolName": tool, "toolInput": tool_input}
    out = translate(p)
    assert out is not None and out["state"] == "needs-you"
    assert out["pending"] == {"kind": "question", "text": text}


@pytest.mark.parametrize(
    ("payload", "want"),
    [
        ({"hook_event_name": "StopFailure", "promptId": "t1"}, {"state": "idle", "turn_end": True, "turn": "t1"}),
        ({"hook_event_name": "StopCancelled", "reason": "permission_rejected"}, {"state": "idle", "turn_end": True}),
        ({"hook_event_name": "Notification", "notificationType": "idle_prompt"}, {"state": "idle", "turn_end": True}),
        (
            {"hook_event_name": "Notification", "notificationType": "idle_prompt", "promptId": "t2"},
            {"state": "idle", "turn_end": True, "turn": "t2"},
        ),
        ({"hook_event_name": "PostToolUseFailure", "toolName": "x"}, {"state": "working", "call": "end"}),
        ({"hook_event_name": "Stop"}, None),
        ({"hook_event_name": "PermissionDenied", "toolName": "x"}, {"state": "working", "pending": None}),
        ({"hook_event_name": "SessionStart", "source": "load"}, {"state": "idle", "subagents_reset": True}),
        ({"hook_event_name": "SessionEnd", "reason": "clear"}, None),
        ({"hook_event_name": "SessionStart", "source": "compact", "sessionId": FIRST}, {"adapter_id": FIRST}),
        ({"hook_event_name": "Notification", "notificationType": "other"}, None),
        ({"hook_event_name": "PostToolUse", "subagentType": "explore", "toolName": "x"}, None),  # names no child
        # an id-less start: its count alone
        ({"hook_event_name": "SubagentStart"}, {"subagent_delta": 1, "subagent": None, "state": None}),
    ],
)
def test_the_feed_beyond_the_capture(payload, want):
    out = translate(payload)
    if want is None:
        assert out is None
    else:
        assert out is not None and {k: out.get(k) for k in want} == want
        if "turn" not in want:
            assert "turn" not in out


# --- the hook's `main` and its two guards (§4.3 *The kill guard and the wait guard*, TD-1637 slice 11) ---

WATCH = "timeout 1800 gh pr checks 12 --watch"


def _pre_tool(command: str, tool: str = "run_terminal_command", **tool_input) -> dict:
    """The captured `PreToolUse` of `run_terminal_command`, its command and tool replaced."""
    base = next(p for p in _payloads() if p["hook_event_name"] == "PreToolUse")
    ti = {**base["toolInput"], "command": command, **tool_input}
    return {**base, "toolName": tool, "tool_name": tool, "toolInput": ti, "tool_input": ti}


@pytest.fixture
def hooked(tmp_path, monkeypatch):
    """The hook's `main` in a session, the host agent a stub that records each event and answers `reply`."""
    from shiftlead.adapters.grok import hook

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x-k")
    sent: list[dict] = []
    state: dict = {"reply": None}

    def agent(params, timeout):
        sent.append(params)
        return state["reply"]

    monkeypatch.setattr(hook, "call_agent", agent)

    def run(payload: dict, reply: dict | None = None) -> None:
        state["reply"] = reply
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        assert hook.main() == 0  # the tool's block is the JSON on stdout, never an exit code

    return run, sent


def _decision(out: str) -> dict | None:
    return json.loads(out) if out.strip() else None


@pytest.mark.parametrize("tool", ["run_terminal_command", "monitor"])
def test_the_kill_guard_denies_alone_and_the_event_still_reports(hooked, capsys, tool):
    from shiftlead import kill_guard

    run, sent = hooked
    run(_pre_tool("pkill -f grok", tool), reply={"refuse_wait": True})
    assert _decision(capsys.readouterr().out) == {"decision": "deny", "reason": kill_guard.REASON}
    [ev] = sent  # one report, the event's own, asking nothing
    assert ev["state"] == "working" and ev["session"] == "ao-x-k" and "wait" not in ev
    run(_pre_tool("kill 1234", tool))
    assert capsys.readouterr().out == "" and sent[-1]["state"] == "working"


def test_a_childs_kill_is_denied_and_reports_nothing(hooked, capsys):
    run, sent = hooked
    run({**_pre_tool("killall grok", "monitor"), "subagentType": "explore"})
    assert _decision(capsys.readouterr().out)["decision"] == "deny"
    assert sent == []


def test_a_kill_inside_a_watch_is_the_kill_guards_alone(hooked, capsys):
    from shiftlead import kill_guard

    run, sent = hooked
    run(_pre_tool(f"{WATCH}; kill $PPID"), reply={"refuse_wait": True})
    out = capsys.readouterr().out
    assert len(out.splitlines()) == 1 and _decision(out)["reason"] == kill_guard.REASON
    assert all("wait" not in e for e in sent)


@pytest.mark.parametrize("extra", [{}, {"block_until_ms": 120000}, {"block_until_ms": "0"}, {"background": "true"}])
def test_an_unattended_foreground_watch_is_denied_with_groks_words(hooked, capsys, extra):
    from shiftlead import wait_guard

    run, sent = hooked
    run(_pre_tool(WATCH, **extra), reply={"refuse_wait": True})
    assert _decision(capsys.readouterr().out) == {"decision": "deny", "reason": wait_guard.GROK_REASON}
    assert sent[-1]["wait"] is True and sent[-1]["state"] == "working"


@pytest.mark.parametrize(
    ("payload", "reply"),
    [
        (_pre_tool(WATCH, block_until_ms=0), {"refuse_wait": True}),
        (_pre_tool(WATCH, background=True), {"refuse_wait": True}),
        ({**_pre_tool(WATCH), "subagentType": "explore"}, {"refuse_wait": True}),
        (_pre_tool(WATCH, "monitor"), {"refuse_wait": True}),
        (_pre_tool("gh pr checks 12"), {"refuse_wait": True}),
        (_pre_tool(WATCH), None),
    ],
    ids=["block_until_ms-0", "background-true", "a-child", "monitor", "a-single-poll", "interactive"],
)
def test_what_is_no_unattended_foreground_watch_runs(hooked, capsys, payload, reply):
    run, sent = hooked
    run(payload, reply=reply)
    assert capsys.readouterr().out == ""
    if reply is None:  # asked, and answered nothing: the record is interactive, so the watch runs
        assert sent[-1]["wait"] is True
    else:
        assert all("wait" not in e for e in sent)


def test_three_reasons_and_groks_names_its_background_form():
    from shiftlead import wait_guard

    assert len({wait_guard.REASON, wait_guard.GEMINI_REASON, wait_guard.GROK_REASON}) == 3
    assert "`block_until_ms: 0`" in wait_guard.GROK_REASON and "do not wait on its output" in wait_guard.GROK_REASON


def test_with_the_host_agent_down_the_watch_runs_and_the_queued_event_has_no_wait(tmp_path, monkeypatch, capsys):
    from shiftlead.adapters.grok import hook

    home = tmp_path / "home"
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x-k")

    def down(params, timeout):
        raise ConnectionRefusedError

    monkeypatch.setattr(hook, "call_agent", down)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_pre_tool(WATCH))))
    assert hook.main() == 0 and capsys.readouterr().out == ""
    got = json.loads((home / "events" / "ao-x-k.jsonl").read_text().strip())
    assert got["state"] == "working" and "wait" not in got and "session" not in got


def test_the_captured_session_reports_and_decides_nothing(hooked, capsys):
    run, sent = hooked
    for p in _payloads():
        run(p, reply={"refuse_wait": True})
    assert capsys.readouterr().out == ""  # no decision written on any event
    assert [e["state"] for e in sent][:2] == ["idle", "working"] and all(e["session"] == "ao-x-k" for e in sent)
    assert all("wait" not in e for e in sent)


def test_no_session_exits_at_once(monkeypatch, capsys):
    from shiftlead.adapters.grok import hook

    monkeypatch.delenv("SHIFTLEAD_SESSION", raising=False)
    monkeypatch.setattr(hook, "call_agent", lambda params, timeout: pytest.fail("called the host agent"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_pre_tool("pkill -f x"))))
    assert hook.main() == 0 and capsys.readouterr().out == ""


def test_shiftlead_hook_dispatches_adapter_grok(monkeypatch):
    from shiftlead import hook_entry
    from shiftlead.adapters.grok import hook

    monkeypatch.setattr(sys, "argv", ["shiftlead-hook", "--adapter", "grok"])
    monkeypatch.setattr(hook, "main", lambda: 7)
    assert hook_entry.main() == 7


# --- a subagent, a question tool and a killed background subagent, captured (TD-1637 slice 12) ---

SUBAGENTS = CAPTURED.parent / "hooks-subagents.jsonl"


def _sub_payloads() -> list[dict]:
    return [json.loads(line) for line in SUBAGENTS.read_text(encoding="utf-8").splitlines() if line.strip()]


CHILD = "01a1d7e"  # the captured children's ids all start so


def test_a_childs_prompt_ending_events_and_its_start_and_stop_are_forwarded_and_its_end_never_exits():
    """TD-1817 (§4.3 *A subagent's events*): a child's `PostToolUse`, `SubagentStart` and `SubagentStop` are sent
    with `subagent` and `subagent_seen` and no state, `adapter_id`, `transcript`, `turn` or `call`; the rest of a
    child's payloads (its prompt, `PreToolUse`, `SessionEnd`) are dropped."""
    got = [(p, translate(p)) for p in _sub_payloads()]
    children = [(p, out) for p, out in got if p.get("subagentType")]
    sent = {p["hook_event_name"] for p, out in children if out is not None}
    assert sent == {"SubagentStart", "PostToolUse", "SubagentStop"}
    dropped = {p["hook_event_name"] for p, out in children if out is None}
    assert dropped == {"UserPromptSubmit", "PreToolUse", "SessionEnd"}
    banned = {"state", "pending", "adapter_id", "transcript", "turn", "turn_start", "turn_end", "call"}
    for p, out in children:
        if out is not None:
            assert not banned & set(out), f"{p['hook_event_name']}: {sorted(banned & set(out))}"
            assert out["subagent"].startswith(CHILD) and out["subagent_seen"] is True
    start = next((p, out) for p, out in children if p["hook_event_name"] == "SubagentStart")
    assert start[0]["sessionId"].startswith("2222") and start[1]["subagent"] == start[0]["subagentId"]
    assert start[1]["subagent_delta"] == 1
    stop = next(out for p, out in children if p["hook_event_name"] == "SubagentStop")
    assert stop["subagent_delta"] == -1
    post = next(out for p, out in children if p["hook_event_name"] == "PostToolUse")
    assert post["event"] == "PostToolUse:run_terminal_command" and post["tool_use_id"]
    exits = [p for p, out in got if out and out.get("state") == "exited"]
    assert [p["sessionId"] for p in exits] == ["22222222-3333-4444-8555-666666666666"]  # the main one's, at /exit


def test_a_childs_stop_cancelled_is_forwarded_only_for_a_permission_and_carries_no_state():
    child = {"hook_event_name": "StopCancelled", "subagentType": "explore", "sessionId": "c-1", "promptId": "t"}
    for reason in ("permission_rejected", "permission_cancelled"):
        assert translate({**child, "reason": reason}) == {"subagent": "c-1", "subagent_seen": True}
    for reason in ("user_interrupt", "end_turn", "cancelled"):  # no permission's: dropped
        assert translate({**child, "reason": reason}) is None
    assert translate({"hook_event_name": "SubagentStart", "subagentType": "x", "sessionId": "p-1"}) == {
        "subagent_delta": 1
    }
    assert translate({**child, "reason": "permission_rejected", "subagentType": None, "subagent_type": "x"}) == {
        "subagent": "c-1",
        "subagent_seen": True,
    }
    failed = {"hook_event_name": "PostToolUseFailure", "subagentType": "x", "sessionId": "c-1", "toolName": "t"}
    denied = {**failed, "hook_event_name": "PermissionDenied"}
    for p in (failed, denied):
        out = translate({**p, "transcript_path": "/c/updates.jsonl"})
        assert out is not None and out["subagent"] == "c-1" and not {"state", "transcript", "call"} & set(out)


def test_a_notification_is_never_a_childs_and_the_kill_names_the_task_on_either_thread():
    note = {"hook_event_name": "Notification", "notificationType": "permission_prompt", "message": "Allow?"}
    marked = translate({**note, "subagentType": "x", "sessionId": "c-1", "transcript_path": "/c/updates.jsonl"})
    assert marked == {"state": "needs-you", "pending": {"kind": "permission", "text": "Allow?"}}
    idle = translate({"hook_event_name": "Notification", "notificationType": "idle_prompt", "sessionId": "p-1"})
    assert idle is not None and (idle["state"], idle["adapter_id"]) == ("idle", "p-1")
    kill = {"hook_event_name": "PostToolUse", "toolName": "kill_command_or_subagent", "toolInput": {"task_id": "t-9"}}
    main = translate({**kill, "sessionId": "p-1"})
    assert main is not None and main["subagent_stopped"] == "t-9" and "subagent_seen" not in main
    child = translate({**kill, "sessionId": "c-1", "subagentType": "x"})
    assert child is not None and (child["subagent_stopped"], child["subagent"], child["subagent_seen"]) == (
        "t-9",
        "c-1",
        True,
    )
    assert "subagent_stopped" not in translate({**kill, "toolInput": {"task_id": 7}})
    posts = [p for p in _sub_payloads() if p["hook_event_name"] == "PostToolUse"]
    captured = next(p for p in posts if p["toolName"] == "kill_command_or_subagent")
    assert translate(captured)["subagent_stopped"] == captured["toolInput"]["task_id"]


def test_the_captured_child_key_and_the_kill():
    subs = _sub_payloads()
    starts = [p for p in subs if p["hook_event_name"] == "SubagentStart"]
    child_ids = {p["sessionId"] for p in subs if p.get("subagentType") and p["hook_event_name"] != "SubagentStart"}
    assert {p["subagentId"] for p in starts} <= child_ids  # a child's events carry its subagentId as sessionId
    assert all(p["sessionId"].startswith("2222") for p in starts)  # a start is on the parent's sessionId
    stop_events = [p for p in subs if p["hook_event_name"] == "SubagentStop"]
    assert stop_events and all(p["sessionId"] == p["subagentId"] for p in stop_events)  # a stop on the child's
    kill = next(
        p for p in subs if p["hook_event_name"] == "PostToolUse" and p["toolName"] == "kill_command_or_subagent"
    )
    killed = kill["toolInput"]["task_id"]
    assert killed in {p["subagentId"] for p in starts}
    stops = {p["subagentId"] for p in subs if p["hook_event_name"] == "SubagentStop"}
    assert killed not in stops  # a killed background subagent fires no SubagentStop (§4.3)


def test_a_childs_prompt_carries_no_marker_and_reads_as_the_main_sessions():
    """TD-1815: the child's `permission_prompt` names the parent and nothing of the child's, so it is sent as the
    main session's permission; the child's next event ends it in core (TD-1817)."""
    subs = _sub_payloads()
    prompts = [p for p in subs if p.get("notificationType") == "permission_prompt"]
    assert prompts and all(not p.get("subagentType") and p["sessionId"].startswith("2222") for p in prompts)
    assert all(translate(p)["pending"]["kind"] == "permission" for p in prompts)


def test_the_question_tool_is_a_question_and_its_notification_is_dropped():
    subs = _sub_payloads()
    ask = next(p for p in subs if p["hook_event_name"] == "PreToolUse" and p["toolName"] == "ask_user_question")
    out = translate(ask)
    assert out["state"] == "needs-you" and out["pending"] == {"kind": "question", "text": "Red or blue?"}
    note = next(p for p in subs if p.get("notificationType") == "elicitation_dialog")
    assert translate(note) is None and subs.index(note) > subs.index(ask)  # after the PreToolUse
    after = next(p for p in subs if p["hook_event_name"] == "PostToolUse" and p["toolName"] == "ask_user_question")
    assert translate(after)["pending"] is None and translate(after)["state"] == "working"


def test_the_kill_guard_reads_a_childs_captured_shell_call():
    from shiftlead.adapters.grok.hook import refused_command

    child = next(p for p in _sub_payloads() if p.get("subagentType") and p.get("toolName") == "run_terminal_command")
    assert refused_command(child) is None
    ti = {**child["toolInput"], "command": "pkill -f grok"}
    assert refused_command({**child, "toolInput": ti, "tool_input": ti}) is not None
