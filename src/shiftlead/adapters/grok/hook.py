"""`shiftlead-hook --adapter grok`'s state feed (design §4.3 *The third adapter: Grok Build*, *The state feed*,
TD-1637).

`translate` maps one Grok Build hook payload to the host agent's `hook` params, read against the payloads
captured from the installed 1.0.77 (`tests/conformance/fixtures/grok/captured/hooks-scratch.jsonl`):

- `SessionStart` with `source` `new` (a launch, and a `/clear`'s new conversation) or `load` (a resume) → `idle`
  with `subagents_reset`; its `sessionId` is the record's `adapter_id`, which a `/clear` changes. Any other
  `source` changes no state.
- `UserPromptSubmit` → `working` with the prompt mark, starting a turn: its `promptId` as `turn`, `turn_start`.
- `PreToolUse` → `working`, but for the three tools that wait on the person (`ask_user_question`,
  `enter_plan_mode`, `exit_plan_mode`) → `needs-you`, a question; `PostToolUse`, `PostToolUseFailure` and
  `PermissionDenied` → `working`, clearing a pending. A tool event carries its call (`tool_use_id`, `call`).
- `Notification` `permission_prompt` → `needs-you`, a permission, its text the payload's `message`;
  `idle_prompt` → `idle`, the backstop.
- `Stop` with `reason` `end_turn`, `StopFailure` and `StopCancelled` → `idle`, a turn-end report (`turn_end`,
  its `promptId` as `turn` where it carries one); a `Stop` of any other `reason` (the session end's
  `shutdown`) is dropped.
- `SessionEnd` → `exited` with its `reason`, but a clear's, which is dropped.

A subagent's payload (one carrying `subagentType`) is dropped here, `SubagentStart` and `SubagentStop` with it:
what a child's events carry is captured before the slice that forwards them (§4.3 *A subagent's events*).
The guards, `main` and the dispatch from `shiftlead-hook --adapter grok` are later slices; nothing calls this yet.
"""

from __future__ import annotations

from typing import Any

# `SessionStart` sources that land at the composer: 1.0.77 writes `new` for a launch and for `/clear`, and its
# guide `load` for a resume; `startup`, `resume` and `clear` are Claude Code's names, kept should a version
# write them (§4.3 *The state feed*)
START_SOURCES = {"new", "load", "startup", "resume", "clear"}
# tools that wait on the person: a `PreToolUse` of one is a question (§4.3 *The tool's questions*)
QUESTION_TOOLS = {"ask_user_question", "enter_plan_mode", "exit_plan_mode"}
# tool events that end a pending, the tool's call going on or refused (§4.3: the order of a permission)
AFTER_TOOL = {"PostToolUse", "PostToolUseFailure", "PermissionDenied"}
CALL_EDGE = {"PreToolUse": "start", "PostToolUse": "end", "PostToolUseFailure": "end"}
TURN_ENDS = {"StopFailure", "StopCancelled"}
END_TURN = "end_turn"  # the one `Stop` reason that ends a turn; the session end's is `shutdown`
TEXT_CAP = 200


def _get(payload: dict[str, Any], camel: str, snake: str) -> Any:
    """A field the tool writes twice, camelCase and snake_case: the camel one first."""
    v = payload.get(camel)
    return payload.get(snake) if v is None else v


def translate(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Hook payload → agent `hook` params (without the session). None = nothing to report."""
    ev = payload.get("hook_event_name") or ""
    if payload.get("subagentType") or payload.get("subagent_type") or ev in ("SubagentStart", "SubagentStop"):
        return None
    out: dict[str, Any] = {}
    if (sid := _get(payload, "sessionId", "session_id")) and isinstance(sid, str):
        out["adapter_id"] = sid  # a `/clear`'s `SessionStart` carries the new conversation's id
    if (path := payload.get("transcript_path")) and isinstance(path, str):
        out["transcript"] = path
    turn = payload.get("promptId")
    turn = turn if isinstance(turn, str) and turn else None
    if ev == "SessionStart":
        if payload.get("source") not in START_SOURCES:
            return out or None  # the id still counts; the state is what it was
        return {**out, "state": "idle", "pending": None, "subagents_reset": True}
    if ev == "SessionEnd":
        reason = payload.get("reason") or ""
        if reason == "clear":
            return None  # the same process goes on
        return {**out, "state": "exited", "pending": None, **({"reason": reason} if reason else {})}
    if ev == "UserPromptSubmit":
        return {**out, "state": "working", "pending": None, "prompt": True, **_turn(turn, start=True)}
    if ev == "PreToolUse" or ev in AFTER_TOOL:
        tool = _get(payload, "toolName", "tool_name")
        event = {"event": f"{ev}:{tool}" if tool else ev, **_call(ev, payload)}
        if ev == "PreToolUse" and tool in QUESTION_TOOLS:
            return {**out, **event, "state": "needs-you", "pending": {"kind": "question", "text": _ask(payload, tool)}}
        return {**out, **event, "state": "working", "pending": None}
    if ev == "Notification":
        kind = _get(payload, "notificationType", "notification_type")
        if kind == "permission_prompt":
            text = str(payload.get("message") or "a tool asks for permission")[:TEXT_CAP]
            return {**out, "state": "needs-you", "pending": {"kind": "permission", "text": text}}
        if kind == "idle_prompt":
            return {**out, "state": "idle", "pending": None, **_turn(None, start=False)}
        return None
    if ev == "Stop" and payload.get("reason") != END_TURN:
        return None  # the observe-only stop at the session's end, whatever its `promptId`
    if ev == "Stop" or ev in TURN_ENDS:
        return {**out, "state": "idle", "pending": None, **_turn(turn, start=False)}
    return None


def _turn(turn: str | None, *, start: bool) -> dict[str, Any]:
    """A turn's mark (design §4.2 *A turn's id*): `turn_start` or `turn_end`, with `turn` where it is named."""
    return {"turn_start" if start else "turn_end": True, **({"turn": turn} if turn else {})}


def _call(ev: str, payload: dict[str, Any]) -> dict[str, Any]:
    """A tool event's call: its edge and its `tool_use_id`, which the tool names on each tool event."""
    if ev not in CALL_EDGE:
        return {}
    tid = _get(payload, "toolUseId", "tool_use_id")
    return {"call": CALL_EDGE[ev], **({"tool_use_id": tid} if isinstance(tid, str) and tid else {})}


def _ask(payload: dict[str, Any], tool: str) -> str:
    """A question tool's text: the question it puts, else what the tool is."""
    ti = _get(payload, "toolInput", "tool_input")
    if isinstance(ti, dict):
        for key in ("question", "prompt", "plan", "message"):
            if isinstance(ti.get(key), str) and ti[key].strip():
                return ti[key].strip()[:TEXT_CAP]
        qs = ti.get("questions")
        if isinstance(qs, list) and qs and isinstance(qs[0], dict) and isinstance(qs[0].get("question"), str):
            return qs[0]["question"].strip()[:TEXT_CAP]
    return {"enter_plan_mode": "enter plan mode?", "exit_plan_mode": "approve the plan?"}.get(tool, "a question")
