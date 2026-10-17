"""`shiftlead-hook --adapter gemini`: the one command every Gemini CLI hook event runs (design §4.3
*The second adapter: Gemini CLI*, TD-785).

Reads the hook payload on stdin, finds its shiftlead session in `SHIFTLEAD_SESSION`, and tells the host
agent what happened — fire-and-forget, socket first, `events/<session>.jsonl` if the agent is down, as
Claude Code's hook does. No event waits: no Gemini hook answers a confirmation, so a permission is
reported as `needs-you` and answered in the terminal (§4.3 *Permissions: no channel*). A `BeforeTool` of
`run_shell_command` whose command the kill guard refuses exits 2 with the reason on stderr, the tool's
own block, with no call to the host agent: the tool never runs, and its turn's `AfterAgent` reports.

Exits 0 otherwise, printing nothing: the tool parses a hook's stdout as JSON.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from typing import Any

from sessionorc.store import EventQueue
from shiftlead.adapters.claude_code.hook import Refused, call_agent, capture
from shiftlead.kill_guard import refuse

SHELL_TOOL = "run_shell_command"
TOOL_EVENTS = {"BeforeTool", "AfterTool"}
# a confirmation's `details.type` that is a permission; anything else (`ask_user`, `exit_plan_mode`, …)
# reaches the person as a question (design §4.3)
PERMISSION_TYPES = {"exec", "edit", "mcp", "info"}
# each confirmation's own detail, read after the tool's message: what is run, edited, called or fetched
DETAIL_KEYS = ("command", "filePath", "toolName", "prompt")
BLOCK = 2  # the exit code that blocks the tool's action, its stderr the reason


def translate(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Hook payload → agent `hook` params (without the session). None = nothing to report."""
    ev = payload.get("hook_event_name", "")
    out: dict[str, Any] = {}
    if sid := payload.get("session_id"):
        out["adapter_id"] = sid  # a `/clear`'s `SessionStart` carries the new id, which the record adopts
    # `""` until the tool starts recording: the record's transcript is the first payload that names one
    if (path := payload.get("transcript_path")) and isinstance(path, str):
        out["transcript"] = path
    if ev == "SessionStart":
        # `startup`, `resume` and `clear` all land at the composer: the first hook the first prompt waits for
        return {**out, "state": "idle", "pending": None}
    if ev == "SessionEnd":
        reason = payload.get("reason") or ""
        if reason == "clear":
            return None  # `/clear`: the same process, a `SessionStart` with the new id follows
        return {**out, "state": "exited", "pending": None, **({"reason": reason} if reason else {})}
    if ev == "BeforeAgent":
        # `prompt`: a prompt went in, which confirms a `send` and the typed brief (§4.1, TD-339)
        return {**out, "state": "working", "pending": None, "prompt": True}
    if ev in TOOL_EVENTS:
        tool = payload.get("tool_name")
        return {**out, "state": "working", "pending": None, "event": f"{ev}:{tool}" if tool else ev}
    if ev == "AfterAgent":
        return {**out, "state": "idle", "pending": None}
    if ev == "Notification" and payload.get("notification_type") == "ToolPermission":
        details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
        kind = "permission" if details.get("type") in PERMISSION_TYPES else "question"
        return {**out, "state": "needs-you", "pending": {"kind": kind, "text": pending_text(payload, details)}}
    return None


def pending_text(payload: dict[str, Any], details: dict[str, Any]) -> str:
    """The confirmation's text: the tool's message, then what it would run, edit, call or fetch."""
    message = str(payload.get("message") or "")
    detail = next((str(details[k]) for k in DETAIL_KEYS if details.get(k)), "")
    return f"{message}: {detail[:200]}" if message and detail else (message or detail[:200])


def refused_command(payload: dict[str, Any]) -> str | None:
    """The kill guard's reason for a `BeforeTool` of `run_shell_command` (design §4.3), None for anything else."""
    if payload.get("hook_event_name") != "BeforeTool" or payload.get("tool_name") != SHELL_TOOL:
        return None
    command = (payload.get("tool_input") or {}).get("command")
    return refuse(command) if isinstance(command, str) else None


def main() -> int:
    session = os.environ.get("SHIFTLEAD_SESSION")
    if not session:
        return 0  # not an shiftlead session; the layer is only ever passed to ours, but be safe
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw or "{}")
    except ValueError:  # not JSON, or not UTF-8
        return 0
    capture("hooks", raw)
    if not isinstance(payload, dict):
        return 0
    if reason := refused_command(payload):
        # the tool's own block, with no call to the host agent: one it cannot reach still refuses
        print(reason, file=sys.stderr)
        return BLOCK
    params = translate(payload)
    if params is None:
        return 0
    params["session"] = session
    try:
        call_agent(params, timeout=3)
    except Refused as e:
        print(f"shiftlead-hook: {session}: the host agent refused the event: {e}", file=sys.stderr)
    except Exception:  # noqa: BLE001
        with contextlib.suppress(OSError):
            EventQueue().append(session, {**{k: v for k, v in params.items() if k != "session"}, "at": time.time()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
