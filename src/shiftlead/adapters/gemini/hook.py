"""`shiftlead-hook --adapter gemini`: the one command every Gemini CLI hook event runs (design §4.3
*The second adapter: Gemini CLI*, TD-785).

Reads the hook payload on stdin, finds its shiftlead session in `SHIFTLEAD_SESSION`, and tells the host
agent what happened — fire-and-forget, socket first, `events/<session>.jsonl` if the agent is down, as
Claude Code's hook does. No event waits: no Gemini hook answers a confirmation, so a permission is
reported as `needs-you` and answered in the terminal (§4.3 *Permissions: no channel*). A `BeforeTool` of
`run_shell_command` whose command the kill guard refuses exits 2 with the reason on stderr, the tool's
own block, with no call to the host agent: the tool never runs, and its turn's `AfterAgent` reports.
One the kill guard passes that is a foreground CI watch (`wait_guard`), in a session launched under a
layer whose background end wakes it (`WAKES_ENV`), goes with `wait: true`, and is blocked the same way
when the reply says the record is unattended (`refuse_wait`, design §4.3 *A wait the guard refuses*).

Two events hand the tool context as `additionalContext`, the one stdout the tool reads as context
rather than an on-screen message: `SessionStart` the launch's start context and the repo's start hooks'
output (§4.3 `start_context`, *The repo's start hooks*), read before it reports, since the host agent
types the first prompt once that report lands; `BeforeAgent` the unread line, the host agent's words for
the session's mail (§4.3 `mail`), never at a doorbell's own prompt, which is that line already.

Exits 0 otherwise, printing nothing but that JSON.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from sessionorc.mail import unread_line
from sessionorc.store import EventQueue
from shiftlead import wait_guard
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
# the launch's start-context file (design §4.3 `start_context`), which `SessionStart` hands the tool as
# `additionalContext`: a path in the environment, never the text in the argv (§4.1, TD-339)
START_CONTEXT_ENV = "SHIFTLEAD_START_CONTEXT_FILE"
# `1` when the launch read a layer under which a background command's end wakes the session (design §4.3
# *A wait the guard refuses*): the tool reads its settings once, at launch, so the hook reads this, never the file
WAKES_ENV = "SHIFTLEAD_GEMINI_WAKES"
# dev-cadence's runner (design §4.3 *A repo's start hooks are every adapter's to run*), the main checkout's
START_HOOKS = ("scripts", "cadence_hooks.sh")
START_HOOKS_TIMEOUT = 150  # seconds: the runner's own bound, > 5 children × its 25 s child timeout
# a pinned repo's (design §4.2, TD-1023): the launcher's word, from PATH, and the two sentences dev-cadence's
# seed line prints when it cannot run the pin (exit 2) or there is none, copied from the seed (a parity test)
PINNED_HOOK = ("dev-cadence", "hook", "session-start")
PIN_FAILED = (
    "dev-cadence: the launcher could not run the pin in docs/cadence.toml (it said why above), "
    "so the cadence session-start hooks did not run (TD-129)"
)
NO_LAUNCHER = (
    "dev-cadence: this repo pins dev-cadence in docs/cadence.toml but no dev-cadence launcher is on PATH, "
    "so the cadence session-start hooks did not run; install it once per machine: clone dev-cadence at its "
    "latest tag, then run: install -m 755 launcher/dev_cadence.py ~/.local/bin/dev-cadence"
)


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


def waits_in_the_foreground(payload: dict[str, Any]) -> bool:
    """A `BeforeTool` of `run_shell_command` that runs a CI watch in the foreground (§4.3): its
    `is_background` not the JSON `true` (missing, or a string, is the foreground), in a session whose
    launch layer wakes it. No main-thread test: Gemini CLI's `BeforeTool` carries no subagent marker."""
    if payload.get("hook_event_name") != "BeforeTool" or payload.get("tool_name") != SHELL_TOOL:
        return False
    ti = payload.get("tool_input") or {}
    command = ti.get("command") if isinstance(ti, dict) else None
    if not isinstance(command, str) or ti.get("is_background") is True:
        return False
    return wait_guard.waits(command) and os.environ.get(WAKES_ENV) == "1"


def start_context(payload: dict[str, Any]) -> str:
    """`SessionStart`'s context: the launch's start-context file, then what the repo's start hooks printed."""
    told = ""
    if where := os.environ.get(START_CONTEXT_ENV):
        with contextlib.suppress(OSError, ValueError):  # read as the launch wrote it (`write_context_file`)
            told = Path(where).read_text(encoding="utf-8", errors="surrogateescape").strip()
    return "\n\n".join(x for x in (told, start_hooks(payload).strip()) if x)


def start_hooks(payload: dict[str, Any]) -> str:
    """Run the repo's start hooks, as Claude Code's layer line does (`CADENCE_HOOK_LINE`). In a pinned repo
    (`cadence.hook_pinned`), `dev-cadence hook session-start` from PATH in `cwd`, the payload on its stdin:
    its stdout whatever its exit, then `PIN_FAILED` after an exit 2; `PIN_FAILED` alone on a timeout, and
    `NO_LAUNCHER` with none on PATH — never "" (design §4.2, TD-1023). Otherwise the main checkout's
    runner — the first entry of `git worktree list` — else the project's own copy, only where it is
    executable; its stdout, or "" when there is none or it failed."""
    from sessionorc import cadence  # here, not at the top: every other event's import path stays light

    cwd = Path(str(payload.get("cwd") or os.getcwd()))
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
    if cadence.hook_pinned(project):
        return _pinned_hooks(payload, cwd)
    try:
        listed = subprocess.run(
            ["git", "-C", str(project), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        listed = ""
    first = listed.splitlines()[0] if listed else ""
    root = Path(first.removeprefix("worktree ")) if first.startswith("worktree ") else project
    runner = root.joinpath(*START_HOOKS)
    if not (runner.is_file() and os.access(runner, os.X_OK)):
        return ""
    try:
        done = subprocess.run(
            [str(runner), "--session-start"],
            capture_output=True,
            text=True,
            cwd=cwd if cwd.is_dir() else None,
            timeout=START_HOOKS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    return done.stdout


def _pinned_hooks(payload: dict[str, Any], cwd: Path) -> str:
    """The seed line's pinned mode: the launcher's `hook session-start` and what it printed (`start_hooks`)."""
    if shutil.which(PINNED_HOOK[0]) is None:
        return NO_LAUNCHER
    try:
        done = subprocess.run(
            list(PINNED_HOOK),
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=cwd if cwd.is_dir() else None,
            timeout=START_HOOKS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError, ValueError):  # a timeout too: a first fetch can outlast the bound
        return PIN_FAILED
    if done.returncode == 2:
        return "\n".join(x for x in (done.stdout.rstrip("\n"), PIN_FAILED) if x)
    return done.stdout


def mail_context(payload: dict[str, Any], reply: Any) -> str:
    """`BeforeAgent`'s context: the unread line while mail is unread, never at the doorbell's own prompt."""
    n = reply.get("unread") if isinstance(reply, dict) else None
    if not isinstance(n, int) or n <= 0 or str(payload.get("prompt") or "").strip() == unread_line(n):
        return ""
    return unread_line(n)


def report(params: dict[str, Any], session: str) -> Any:
    """Tell the host agent, queued when it is down; its reply, None when it gave none."""
    try:
        return call_agent(params, timeout=3)
    except Refused as e:
        print(f"shiftlead-hook: {session}: the host agent refused the event: {e}", file=sys.stderr)
    except Exception:  # noqa: BLE001
        # the queued copy carries no `mail` and no `wait`: a drained event is applied unanswered (§4.3)
        queued = {k: v for k, v in params.items() if k not in ("session", "mail", "wait")}
        with contextlib.suppress(OSError):
            EventQueue().append(session, {**queued, "at": time.time()})
    return None


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
    ev = payload.get("hook_event_name")
    # read before the report: the host agent types the first prompt once `SessionStart` reports
    context = start_context(payload) if ev == "SessionStart" else ""
    params["session"] = session
    if ev == "BeforeAgent":
        params["mail"] = True
    ask_wait = waits_in_the_foreground(payload)
    if ask_wait:
        params["wait"] = True
    reply = report(params, session)
    if ask_wait and isinstance(reply, dict) and reply.get("refuse_wait"):
        print(wait_guard.GEMINI_REASON, file=sys.stderr)
        return BLOCK
    if ev == "BeforeAgent":
        context = mail_context(payload, reply)
    if context:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": ev, "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
