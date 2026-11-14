"""Grok Build's state feed (design §4.3 *The third adapter: Grok Build*, *The state feed*, TD-1637), read
against the payloads captured from the installed 1.0.77 (`fixtures/grok/captured/hooks-scratch.jsonl`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shiftlead.adapters.grok.hook import translate

CAPTURED = Path(__file__).parent / "conformance" / "fixtures" / "grok" / "captured" / "hooks-scratch.jsonl"
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
        ({"hook_event_name": "PostToolUse", "subagentType": "explore", "toolName": "x"}, None),
        ({"hook_event_name": "SubagentStart"}, None),
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
