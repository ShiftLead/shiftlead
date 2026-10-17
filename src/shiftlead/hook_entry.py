"""`shiftlead-hook`'s entry point (design §4.1 *The hook keeps its traceback*, TD-720 slice 3).

A module of the standard library alone: `shiftlead.adapters.claude_code`'s `__init__` imports
`sessionorc`, so an install half replaced under a running session (a promote) fails in that import,
before the hook could write anything. Here the hook is imported inside a `try`, and what it raised is
appended to `<home>/hook-errors.log` (`sessionorc.paths.hook_errors_file()` names it for readers), the
home found from `SHIFTLEAD_HOME` or `~/.shiftlead` without `sessionorc.paths`. The exit stays non-zero,
so Claude Code still shows its one-line *hook error* and goes on.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

LOG_NAME = "hook-errors.log"
LOG_LIMIT = 256 * 1024  # the log keeps its last 256 KB


def log_path() -> Path:
    return Path(os.environ.get("SHIFTLEAD_HOME", "~/.shiftlead")).expanduser() / LOG_NAME


def _event() -> str:
    if "--statusline" in sys.argv[1:]:
        return "statusline"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:  # noqa: BLE001 — no stdin, or not JSON: the entry is still written
        return "?"
    return str(payload.get("hook_event_name") or "?") if isinstance(payload, dict) else "?"


def record(exc: BaseException) -> None:
    """Append one entry for `exc` to the log, then cut it to its last `LOG_LIMIT` bytes."""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    session = os.environ.get("SHIFTLEAD_SESSION") or "-"
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{stamp} session={session} event={_event()}\n{tb}\n")
        if path.stat().st_size > LOG_LIMIT:
            tail = path.read_bytes()[-LOG_LIMIT:]
            cut = tail.find(b"\n")  # start at a whole line
            path.write_bytes(tail[cut + 1 :] if cut >= 0 else tail)
    except OSError:
        pass


def adapter() -> str:
    """The adapter the hook runs for: `--adapter <name>` in argv, else Claude Code's, whose layer passes
    none. Read before any import, since a Gemini CLI payload names no adapter and shares event names
    with Claude Code's (design §4.3 *The second adapter*, TD-785)."""
    argv = sys.argv[1:]
    if "--adapter" in argv and argv.index("--adapter") + 1 < len(argv):
        return argv[argv.index("--adapter") + 1]
    return "claude-code"


def main() -> int:
    try:
        if adapter() == "gemini":
            from shiftlead.adapters.gemini import hook
        else:
            from shiftlead.adapters.claude_code import hook
    except Exception as e:  # noqa: BLE001 — whatever a half-replaced install raises
        record(e)
        print(f"shiftlead-hook: import failed, see {log_path()}: {e!r}", file=sys.stderr)
        return 1
    return hook.main()
