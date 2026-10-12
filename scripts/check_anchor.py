#!/usr/bin/env python3
# SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/scripts/check_anchor.py
# Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one).
"""SessionStart anchor guard — detect a second session in the main checkout.

Cadence rule (docs/cadence.md §1): ONE anchor session per checkout; every other
concurrent session isolates in a worktree. This hook makes the rule mechanical:
at session start it reads the live sessions through the session adapter
(agent_sessions.py, TD-100 — for Claude Code, its registry: one file per running
process) and, if another live session already
occupies this checkout, prints a loud warning — which SessionStart hooks inject
into the new session's context — telling it to isolate before touching
anything. One session per checkout applies to worktrees too: starting in an
already-occupied worktree warns the same way. Silent when this session is the
first (anchor) in its checkout — and when a tool the repo lists (the `agents`
setting) cannot be looked at, it says so rather than calling this session the anchor.
Always exits 0 (non-blocking).

Self-exclusion is by session id AND by process ancestry: after /resume the new
session id differs from the one in the registry entry for this very process
(the registry updates only after SessionStart hooks run), so id equality alone
made a resumed session flag ITSELF as a conflicting occupant. Any registry
entry whose pid is this hook's own ancestor is self, whatever id it carries.

Liveness is CORROBORATED, not assumed from `/proc/<pid>` existing: the registry
is a directory of pid-named files, and a pid is only meaningful within the pid
namespace that issued it. Where `~/.claude` is shared across namespaces — the
durable-storage bind cadence.md §1 + appendix recommend for containers, which necessarily
shares `sessions/` too — a dead entry's pid is read against a *different*
namespace's `/proc`, where low pids are readily in use by unrelated processes.
Existence alone then reports a long-dead session as live and manufactures anchor
conflicts out of nothing (the same failure the cadence.md appendix warns about
for restored mirrors, made permanent by the bind). An entry survives only when nothing *positively*
establishes that its pid is no longer its session. The proof is exact wherever
the registry allows it: entries record `procStart` in the same clock ticks as
/proc/<pid>/stat field 22, so equality identifies the same PROCESS, needing
neither a name allowlist nor any wall-clock conversion. Entries predating that
field fall back to start-time ordering (a session writes its own entry, so its
process always predates it), and last to the process command. Anything
undeterminable keeps the entry, so the guard degrades toward a redundant
warning, never toward silence.

Usage:
    check_anchor.py            # standalone: prints anchor status for cwd
    check_anchor.py --hook     # SessionStart hook: reads {session_id, cwd} JSON
                               # from stdin; silent unless there's a conflict
"""

import functools
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# The live-session registry, liveness and the self walk are the session adapter's (TD-100):
# the Claude backend lives in agent_sessions.py beside this script. Re-exported here, since
# reap_worktrees.sh and older callers import them from this module.
# NB patch agent_sessions.procfs_available, not this module's copy: liveness runs there.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import agent_sessions  # noqa: E402,F401
except ImportError:  # a partial sync: one line, never a traceback in SessionStart
    print("⚠ anchor check did not run: agent_sessions.py is missing beside check_anchor.py — re-run sync.sh")
    sys.exit(0)
from agent_sessions import (  # noqa: E402
    SESSION_COMMS,  # noqa: F401
    _ancestor_pids,
    _entry_pid,
    _pid_is_dead,  # noqa: F401
    cannot_see,
    format_canary,
    live,
    live_sessions,  # noqa: F401
    procfs_available,  # noqa: F401
    registry_format_note,  # noqa: F401
)

# Occupancy resolution runs per registry entry, so its git calls need tighter
# bounds than the single call main() makes for its own cwd. A hung `git` — stale
# NFS, a dead bind mount, exactly the container hazards the cadence.md appendix
# is about — would otherwise stall SessionStart for the full timeout PER ENTRY,
# serially.
OCCUPANCY_GIT_TIMEOUT = 2     # seconds per call
OCCUPANCY_GIT_BUDGET = 4.0    # seconds across all occupancy calls in one run
_repo_root_cache: dict[str, "Path | None"] = {}
_occupancy_git_spent = 0.0


def repo_root(cwd: Path, timeout: int = 10) -> Path | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True, timeout=timeout,
        )
        return Path(r.stdout.strip()).resolve()
    except (subprocess.SubprocessError, OSError):
        return None


# git's "there is no checkout here" answers — nothing to guard, so silence. Matched
# on git's own text, so the call runs in the C locale (gettext translates it). A bare
# repo, or GIT_DIR without a work tree, answers the second (PR #107 review).
NOT_A_CHECKOUT = ("not a git repository", "must be run in a work tree")
GIT_C_LOCALE = {**os.environ, "LC_ALL": "C", "LANGUAGE": ""}


def repo_root_or_error(cwd: Path, timeout: int = 10) -> "tuple[Path | None, str | None]":
    """(root, None) in a repo; (None, None) when cwd is simply not a git repo; and
    (None, "<why>") on any OTHER failure — dubious ownership, a timeout, git missing.
    The last used to read as "not a repo" and the guard said nothing (TD-043)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=timeout, check=False,
            env=GIT_C_LOCALE,
        )
    except subprocess.TimeoutExpired:
        return None, f"git rev-parse timed out after {timeout}s"
    except OSError as e:
        return None, f"git could not run ({e.strerror or e})"
    if r.returncode == 0:
        return Path(r.stdout.strip()).resolve(), None
    err = (r.stderr or "").strip()
    if any(m in err for m in NOT_A_CHECKOUT):
        return None, None
    return None, (err.splitlines() or [f"git rev-parse exited {r.returncode}"])[0]


def _occupancy_repo_root(p: Path) -> "Path | None":
    """repo_root() for occupancy checks: memoized, time-bounded, fail-safe.

    Stale registries commonly hold many entries sharing one cwd, so the cache
    turns a per-entry spawn into a per-distinct-path one. Past the budget the
    remaining entries resolve as undeterminable, which occupies() keeps — the
    same degrade-toward-warning direction as every other unknown here.
    """
    global _occupancy_git_spent
    key = str(p)
    if key in _repo_root_cache:
        return _repo_root_cache[key]
    if _occupancy_git_spent >= OCCUPANCY_GIT_BUDGET:
        return None
    t0 = time.monotonic()
    result = repo_root(p, timeout=OCCUPANCY_GIT_TIMEOUT)
    _occupancy_git_spent += time.monotonic() - t0
    _repo_root_cache[key] = result
    return result


@functools.lru_cache(maxsize=None)
def _worktree_parts(root: Path) -> tuple[str, ...]:
    """The `worktree-root` setting as path parts (cadence_config.py, TD-101). A setting that
    cannot be read falls back to the default: the guard degrades, it never fails here."""
    try:
        import cadence_config as C
        value, _ = C.resolve("worktree-root", C.sources(str(root)))
    except Exception:  # noqa: BLE001 — no helper, an unreadable file, an invalid value
        value = ".claude/worktrees"
    return Path(str(value)).parts


def occupies(session_cwd: str, root: Path) -> bool:
    """True if a session started at session_cwd is working in ROOT's main checkout."""
    try:
        p = Path(session_cwd).resolve()
    except OSError:
        return False
    if p == root:
        return True
    if root not in p.parents:
        return False
    # sessions inside <root>/<worktree-root>/<name> are isolated, not occupants — the
    # worktree root is the setting open_worktree.sh creates them under (TD-101). Only a
    # fast path: a worktree anywhere else is cleared by the nested-root test below.
    rel = p.relative_to(root).parts
    wt = _worktree_parts(root)
    if len(rel) > len(wt) and rel[: len(wt)] == wt:
        return False
    # Being UNDER root's directory is not the same as being IN root's checkout.
    # An independent repo nested in the working dir — a sibling checkout kept
    # under an umbrella repo, a submodule, a vendored clone, a gitignored
    # subproject — shares no HEAD, index, or working files with root, so a
    # session there collides with nothing here. Path nesting alone reported it as
    # an occupant and made the umbrella session warn about a checkout it does not
    # share. Only nested paths pay this git call; the p == root fast path above
    # covers the common case.
    nested_root = _occupancy_repo_root(p)
    if nested_root is None:
        # UNDETERMINABLE, not disproved — git failed, or the cwd has since been
        # deleted. Keep it an occupant: this check exists to REMOVE false
        # conflicts, and letting it invent false *clearances* would trade a
        # visible annoyance for a silent one, against the same degrade-toward-
        # warning rule the liveness filter follows.
        return True
    return nested_root == root


def main() -> int:
    hook = "--hook" in sys.argv
    data = {}
    if hook:
        try:
            data = json.load(sys.stdin)
        except (json.JSONDecodeError, OSError):
            data = {}
    self_id = data.get("session_id", "")
    cwd = Path(data.get("cwd") or os.getcwd()).resolve()

    note = format_canary()
    if note:
        print(note)

    root, err = repo_root_or_error(cwd)
    if err:
        # One line, never silence: a guard that cannot run must say so (TD-043).
        print(f"⚠ anchor check did not run: {err}")
        return 0
    if root is None:
        return 0  # not a git repo — nothing to guard
    if root != cwd and not occupies(str(cwd), root):
        if not hook:
            print(f"OK: this session is isolated in a worktree ({cwd}).")
        return 0

    self_pids = _ancestor_pids()
    seen = live(root)
    others = [
        s for s in seen.items
        if s.get("id") != self_id
        and _entry_pid(s) not in self_pids  # self after /resume: old id, our own pid
        and occupies(s.get("cwd", ""), root)
    ]
    if not others:
        if seen.blind:
            # A tool the repo lists cannot be looked at: unknown, never "you are the anchor" (TD-100)
            print(f"⚠ anchor check: {cannot_see(seen)} — whether another session is in {root} is unknown.")
        elif not hook:
            print(f"OK: no other live session in {root} — this session is the anchor.")
        return 0

    lines = [f"⚠ ANCHOR CONFLICT: {root} already hosts {len(others)} other live session(s):"]
    for s in others:
        started = s.get("startedAt")
        when = (
            datetime.fromtimestamp(started / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if isinstance(started, (int, float)) else "?"
        )
        lines.append(
            f"  • {s.get('tool', '?')} session {(s.get('id') or '?')[:8]} (pid {s.get('pid', '?')}, started {when}) "
            f"in {s.get('cwd', '?')}"
        )
    lines.append(
        "Per docs/cadence.md §1 there is ONE anchor session per checkout — the earlier session holds that role. "
        "Before making ANY changes here (no commits, branch switches, or file edits in this shared checkout), "
        "this session must isolate itself: move to a fresh worktree now (EnterWorktree), or tell the user to restart it "
        "with `claude --worktree <name>`. Shared-checkout collisions have caused real damage before."
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
