"""`shiftlead-hook --adapter grok`'s state feed (design §4.3 *The third adapter: Grok Build*, *The state feed*,
TD-1637).

`translate` maps one Grok Build hook payload to the host agent's `hook` params, read against the payloads
captured from the installed 1.0.77 (`tests/conformance/fixtures/grok/captured/hooks.jsonl`):

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

A subagent's payload (one carrying `subagentType`) is forwarded only where it can end a prompt or moves the count
(§4.3 *A subagent's events*, TD-1817): its `PostToolUse`, `PostToolUseFailure`, `PermissionDenied` and a
`StopCancelled` of a permission's refusal, with `subagent` (its `sessionId`) and `subagent_seen` and no state,
`adapter_id` or `transcript`, so core ends the main thread's permissions on it (a child's prompt names no thread,
§4.2 *A subagent's event, for a tool with no channel*); `SubagentStart` (+1, `subagent` its `subagentId`) and
`SubagentStop` (−1). Every other child payload is dropped; a `Notification` is never a child's. A `PostToolUse` of
`kill_command_or_subagent`, on either thread, names the task it stopped (`subagent_stopped`): the tool sends no
`SubagentStop` for a killed subagent.

`main` is what `shiftlead-hook --adapter grok` runs (`hook_entry`): with no `SHIFTLEAD_SESSION` it exits 0 at
once; otherwise it reports the translated event to the host agent, queued when it is down, and decides
nothing — writing no decision and exiting 0 — but for the two guards on a `PreToolUse` (§4.3 *The kill guard
and the wait guard*), which answer in the tool's own block form, `{"decision": "deny", "reason": …}` on
stdout. **The kill guard** reads `toolInput.command` of `run_terminal_command` and of `monitor`, on every
thread, and decides alone, with no call to the host agent: a main-thread event still reports `working`, a
child's reports nothing. **The wait guard** is asked on the main thread only, for a `run_terminal_command`
whose command `wait_guard.waits` reads as a CI watch run in the foreground: the event goes with `wait: true`,
and the hook denies with `wait_guard.GROK_REASON` only on the reply's `refuse_wait`.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from typing import Any

from sessionorc.store import EventQueue
from shiftlead import wait_guard
from shiftlead.adapters.claude_code.hook import Refused, call_agent, capture
from shiftlead.kill_guard import refuse

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
# a child's `StopCancelled` reasons that answer a permission: the only ones forwarded (§4.3 *A subagent's events*)
PERMISSION_STOPS = {"permission_rejected", "permission_cancelled"}
KILL_TOOL = "kill_command_or_subagent"  # its `PostToolUse` names the task it stopped (`toolInput.task_id`)
TEXT_CAP = 200
SHELL_TOOL = "run_terminal_command"  # the tool's shell tool, both guards' (§4.3 *The kill guard and the wait guard*)
# tools whose `toolInput.command` runs a shell command unasked under `--always-approve`: the kill guard's
COMMAND_TOOLS = {SHELL_TOOL, "monitor"}


def _get(payload: dict[str, Any], camel: str, snake: str) -> Any:
    """A field the tool writes twice, camelCase and snake_case: the camel one first."""
    v = payload.get(camel)
    return payload.get(snake) if v is None else v


def translate(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Hook payload → agent `hook` params (without the session). None = nothing to report."""
    ev = payload.get("hook_event_name") or ""
    child = not _main_thread(payload)
    if ev in ("SubagentStart", "SubagentStop") or (child and ev != "Notification"):
        return _child(payload, ev)
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
        event = {"event": f"{ev}:{tool}" if tool else ev, **_call(ev, payload), **_stopped(ev, payload)}
        if ev == "PreToolUse" and tool in QUESTION_TOOLS:
            return {**out, **event, "state": "needs-you", "pending": {"kind": "question", "text": _ask(payload, tool)}}
        return {**out, **event, "state": "working", "pending": None}
    if ev == "Notification":
        if child:  # never a child's (uncaptured with `subagentType`): the main session's, naming none of its own
            out.pop("adapter_id", None)
            out.pop("transcript", None)
        kind = _get(payload, "notificationType", "notification_type")
        if kind == "permission_prompt":
            text = str(payload.get("message") or "a tool asks for permission")[:TEXT_CAP]
            return {**out, "state": "needs-you", "pending": {"kind": "permission", "text": text}}
        if kind == "idle_prompt":
            return {**out, "state": "idle", "pending": None, **_turn(turn, start=False)}
        return None
    if ev == "Stop" and payload.get("reason") != END_TURN:
        return None  # the observe-only stop at the session's end, whatever its `promptId`
    if ev == "Stop" or ev in TURN_ENDS:
        return {**out, "state": "idle", "pending": None, **_turn(turn, start=False)}
    return None


def _child(payload: dict[str, Any], ev: str) -> dict[str, Any] | None:
    """A subagent's payload, or a `SubagentStart` / `SubagentStop` (§4.3 *A subagent's events*): what can end a
    prompt and the count's moves, each naming the child (`subagent`) with `subagent_seen`, and never a state, an
    `adapter_id`, a `transcript`, a `turn` or a `call`. None: dropped."""
    if ev == "SubagentStart":  # on the parent's `sessionId`: the child's id is its `subagentId`
        sid = _get(payload, "subagentId", "subagent_id")
        if not (isinstance(sid, str) and sid):
            return {"subagent_delta": 1}  # an id-less start (§4.2), which ends no permission
        return {"subagent_delta": 1, "subagent": sid, "subagent_seen": True}
    sid = _get(payload, "sessionId", "session_id")
    thread = {"subagent": sid, "subagent_seen": True} if isinstance(sid, str) and sid else {}
    if ev == "SubagentStop":
        return {"subagent_delta": -1, **thread}
    if not thread:
        return None  # a child's event that names no child cannot be told from the main thread's
    if ev in AFTER_TOOL:
        tool = _get(payload, "toolName", "tool_name")
        tid = _get(payload, "toolUseId", "tool_use_id")
        return {
            **thread,
            "event": f"{ev}:{tool}" if tool else ev,
            **({"tool_use_id": tid} if isinstance(tid, str) and tid else {}),
            **_stopped(ev, payload),
        }
    if ev == "StopCancelled" and payload.get("reason") in PERMISSION_STOPS:
        return thread
    return None


def _stopped(ev: str, payload: dict[str, Any]) -> dict[str, Any]:
    """A `PostToolUse` of `kill_command_or_subagent` names the task it stopped, a command's or a subagent's
    (§4.3 *A subagent's events*): core moves no count for an id it does not list."""
    if ev != "PostToolUse" or _get(payload, "toolName", "tool_name") != KILL_TOOL:
        return {}
    ti = _get(payload, "toolInput", "tool_input")
    task = ti.get("task_id") if isinstance(ti, dict) else None
    return {"subagent_stopped": task} if isinstance(task, str) and task else {}


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


def _main_thread(payload: dict[str, Any]) -> bool:
    """A payload of the session's own agent: a child's carries `subagentType` (§4.3 *A subagent's events*)."""
    return not (payload.get("subagentType") or payload.get("subagent_type"))


def _command(payload: dict[str, Any], tools: set[str] | frozenset[str]) -> tuple[str | None, dict[str, Any]]:
    """A `PreToolUse` of one of `tools`: its `toolInput.command` (None where it is no string) and its input."""
    if payload.get("hook_event_name") != "PreToolUse" or _get(payload, "toolName", "tool_name") not in tools:
        return None, {}
    ti = _get(payload, "toolInput", "tool_input")
    ti = ti if isinstance(ti, dict) else {}
    command = ti.get("command")
    return (command if isinstance(command, str) else None), ti


def refused_command(payload: dict[str, Any]) -> str | None:
    """The kill guard's reason for a `PreToolUse` of `run_terminal_command` or `monitor`, on any thread (§4.3)."""
    command, _ = _command(payload, COMMAND_TOOLS)
    return refuse(command) if command is not None else None


def in_the_background(ti: dict[str, Any]) -> bool:
    """The call's background form: `block_until_ms` the number 0 (the 1.0.77 guide's *Background Tasks*), or
    `background` the JSON `true` (the form the tool's other shell schema takes). Anything else — missing, a
    string, a positive wait — is the foreground."""
    wait = ti.get("block_until_ms")
    return ti.get("background") is True or (isinstance(wait, int | float) and not isinstance(wait, bool) and wait == 0)


def waits_in_the_foreground(payload: dict[str, Any]) -> bool:
    """A main-thread `PreToolUse` of `run_terminal_command`, run in the foreground, that is a CI watch (§4.3)."""
    command, ti = _command(payload, {SHELL_TOOL})
    if command is None or not _main_thread(payload) or in_the_background(ti):
        return False
    return wait_guard.waits(command)


def deny(reason: str) -> str:
    """The tool's own block form for a `PreToolUse` (the guide's *Output (Blocking Hooks)*)."""
    return json.dumps({"decision": "deny", "reason": reason})


def report(params: dict[str, Any], session: str) -> Any:
    """Tell the host agent, queued when it is down; its reply, None when it gave none (§4.3, as Claude Code's)."""
    try:
        return call_agent(params, timeout=float(os.environ.get("SHIFTLEAD_EVENT_WAIT", "3")))
    except Refused as e:
        print(f"shiftlead-hook: {session}: the host agent refused the event: {e}", file=sys.stderr)
    except Exception:  # noqa: BLE001
        # the queued copy carries no `wait`: a drained event is applied unanswered (§4.3)
        queued = {k: v for k, v in params.items() if k not in ("session", "wait")}
        with contextlib.suppress(OSError):
            EventQueue().append(session, {**queued, "at": time.time()})
    return None


def main() -> int:
    session = os.environ.get("SHIFTLEAD_SESSION")
    if not session:
        return 0  # a hand-started `grok` on the same home reports nothing (§4.3 *The hooks*)
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw or "{}")
    except ValueError:  # not JSON, or not UTF-8
        return 0
    capture("hooks", raw)
    if not isinstance(payload, dict):
        return 0
    ask_wait = False
    if reason := refused_command(payload):
        # the hook's own decision, before the host agent is asked anything: one it cannot reach still
        # refuses; a main-thread event below still reports `working`, a child's nothing
        print(deny(reason))
        sys.stdout.flush()
    else:
        ask_wait = waits_in_the_foreground(payload)
    params = translate(payload)
    if params is None:
        return 0
    params["session"] = session
    if ask_wait:
        params["wait"] = True  # the record's mode is the host agent's to say (§4.3 *A wait the guard refuses*)
    reply = report(params, session)
    if ask_wait and isinstance(reply, dict) and reply.get("refuse_wait"):
        print(deny(wait_guard.GROK_REASON))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
