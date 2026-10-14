#!/usr/bin/env python3
# SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/scripts/agent_sessions.py
# Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one).
"""The session adapter (TD-100): what the safety nets know about agent sessions, read
through one module with a backend per tool (docs/plans/2026-10-12-session-introspection-adapter.md
in dev-cadence).

The nets — the anchor guard (check_anchor.py), the reaper's idle gate (reap_worktrees.sh),
the session index (list_sessions.py) and the sweep row (nudge_user_attention.py) — ask
here, never a tool's files directly. Every answer says what it saw AND which tools it could
not look at (`Seen.blind`): a tool whose state is absent or unreadable is "cannot see",
never "nobody here" — for a detector an empty disk is not evidence (cadence.md §7).

Which tools: every backend whose state is on this machine is asked, and the `agents`
setting (cadence_config.py, default "claude") names the ones that MUST be seen — a listed
tool with no backend, or no readable state, goes into `blind`.

Backends: claude (the live registry ~/.claude/sessions/*.json and the transcripts under
~/.claude/projects/<munged path>/, both undocumented Claude Code internals — TD-050's
canary watches the registry); gemini (TD-109: ~/.gemini's projects.json and its
tmp/<slug>/chats/*.jsonl, liveness from /proc — Gemini CLI keeps no live registry). Codex
is TD-102's.

Stdlib only; imported by the scripts beside it.
"""

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

BACKENDS = ("claude", "gemini")


@dataclass
class Seen:
    """What a query found (`items`) and, one line per tool, what it could not look at."""
    items: list = field(default_factory=list)
    blind: list = field(default_factory=list)


def cannot_see(seen: Seen) -> str:
    """The one line a net prints in place of "clean" when its answer is partial."""
    return "cannot see " + "; ".join(seen.blind)


def wanted(repo: "Path | str | None" = None) -> list[str]:
    """The tools the `agents` setting says must be seen (default ["claude"]). When the
    settings cannot be read, CADENCE_AGENTS still counts, and the answer carries a "!"
    entry naming the problem — every query turns it into a blind line, since the file
    may have listed a tool the nets now cannot know to look for."""
    raw, extra = "claude", []
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import cadence_config as C
        root = C.repo_root(str(repo or "."))
        raw, _ = C.resolve("agents", C.sources(root))
    except Exception as e:  # noqa: BLE001 — no helper, or an unreadable file
        raw = os.environ.get("CADENCE_AGENTS", "").strip() or "claude"
        if not isinstance(e, ImportError):
            extra = [f"!the agents setting could not be read ({e})"]
    tools = [t.strip().lower() for t in str(raw or "").split(",") if t.strip()]
    return (tools or ["claude"]) + extra


def _blind_line(tool: str, what: str) -> str:
    """Why a listed tool is blind for `what` (sessions, transcripts)."""
    if tool.startswith("!"):
        return tool[1:]
    return f"{tool} {what}: no backend for {tool} (TD-102)"


def _gemini_dir(*parts: str) -> Path:
    return Path.home().joinpath(".gemini", *parts)


def _claude_dir(*parts: str) -> Path:
    return Path.home().joinpath(".claude", *parts)


def _unreadable(d: Path) -> "str | None":
    """Why directory d cannot be read, or None. os.listdir, not is_dir(): is_dir() only needs
    the PARENT searchable, and pathlib's glob() swallows a PermissionError and yields nothing
    — chmod 000 on a populated registry read as empty and reaped a live worktree in review."""
    try:
        os.listdir(d)
    except FileNotFoundError:
        return f"no {d}"
    except OSError as e:
        return f"{d} unreadable ({e.strerror or e})"
    return None


# ----------------------------------------------------------------------------------------
# The neutral operations
# ----------------------------------------------------------------------------------------

def live(repo: "Path | str | None" = None) -> Seen:
    """Live sessions on this machine: items are dicts with at least tool, id, pid, cwd
    (Claude's own registry keys — sessionId, startedAt, procStart — are kept alongside)."""
    out, want = Seen(), wanted(repo)
    for tool in sorted(set(BACKENDS) | set(want)):
        if tool == "claude":
            why = _unreadable(_claude_dir("sessions"))
            if why:
                if tool in want:
                    out.blind.append(f"claude sessions: {why}")
                continue
            out.items += [{**s, "tool": "claude", "id": s.get("sessionId")} for s in live_sessions()]
        elif tool == "gemini":
            why = _unreadable(_gemini_dir()) or (None if procfs_available() else "no /proc to find its processes by")
            if why:
                if tool in want:
                    out.blind.append(f"gemini sessions: {why}")
                continue
            out.items += gemini_live()
        else:
            out.blind.append(_blind_line(tool, "sessions"))
    return out


def history_dirs(repo: Path) -> Seen:
    """Where each tool keeps this repo's transcripts: items are (tool, dir, worktree name or
    None). A listed tool with no transcript store at all is blind; one whose store exists
    but holds nothing for this repo is simply empty."""
    out, want = Seen(), wanted(repo)
    for tool in sorted(set(BACKENDS) | set(want)):
        if tool == "claude":
            why = _unreadable(_claude_dir("projects"))
            if why:
                if tool in want:
                    out.blind.append(f"claude transcripts: {why}")
                continue
            for d in project_dirs(repo):
                wt = d.name.split(WORKTREE_MARKER, 1)[1] if WORKTREE_MARKER in d.name else None
                out.items.append(("claude", d, wt))
        elif tool == "gemini":
            why = _unreadable(_gemini_dir("tmp"))
            if why:
                if tool in want:
                    out.blind.append(f"gemini transcripts: {why}")
                continue
            out.items += [("gemini", d, wt) for d, wt in gemini_chat_dirs(repo)]
        else:
            out.blind.append(_blind_line(tool, "transcripts"))
    return out


def ever_ran(repo: Path) -> "bool | None":
    """Whether any session ever ran in this repo, its worktrees or a subdirectory: True,
    False, or None when a listed tool cannot be looked at. Deliberately broad for Claude:
    every project dir whose name starts with the repo's munged path counts, which also
    counts a sibling repo sharing the prefix — that only ever says "ran", the safe
    direction for the line that hides a warning (TD-28). Gemini's is broad the same way:
    a history in any directory under the repo counts."""
    blind, want = False, wanted(repo)
    for tool in sorted(set(BACKENDS) | set(want)):
        if tool == "claude":
            base = _claude_dir("projects")
            if _unreadable(base):
                blind = blind or tool in want
                continue
            me = munge(repo)
            try:
                if any(any(d.glob("*.jsonl")) for d in base.iterdir()
                       if d.is_dir() and (d.name == me or d.name.startswith(me + "-"))):
                    return True
            except OSError:
                blind = True
        elif tool == "gemini":
            if _unreadable(_gemini_dir("tmp")):
                blind = blind or tool in want
                continue
            me = str(Path(repo).resolve())
            for path, slug in gemini_projects().items():
                if (path == me or path.startswith(me + "/")) and any(_gemini_dir("tmp", slug, "chats").glob("*.jsonl")):
                    return True
        else:
            blind = True
    return None if blind else False


def resume_hint(session_id: str, tool: str = "claude") -> str:
    # gemini --resume <uuid> resumed that session when read (TD-109), though its --help names
    # only `latest` and an index; it is per project, so it runs in the session's directory
    return {"claude": f"claude --resume {session_id}",
            "gemini": f"gemini --resume {session_id}"}.get(tool, f"resume {tool} session {session_id}")


def scan(tool: str, path: Path) -> "dict | None":
    """A non-Claude transcript's head and tail, unclipped, in list_sessions' keys (id, start,
    last, first_user, last_assistant, summary); None when it cannot be read or says nothing.
    Claude's scan stays list_sessions.scan_session — its format is that script's history."""
    return gemini_scan(path) if tool == "gemini" else None


def format_canary() -> "str | None":
    """Each backend's format warning, or None (TD-050)."""
    notes = [n for n in (registry_format_note(), gemini_format_note()) if n]
    return "\n".join(notes) or None


# ----------------------------------------------------------------------------------------
# The Gemini CLI backend (TD-109), on the facts read off Gemini CLI 0.64.0 on 2026-10-13
# (docs/plans/2026-10-12-session-introspection-adapter.md in dev-cadence, *Gemini CLI, as
# read*): ~/.gemini/projects.json maps an absolute path to a slug (the basename,
# lowercased); tmp/<slug>/.project_root holds the path again; each session is
# tmp/<slug>/chats/session-<time>-<uuid8>.jsonl, its first record {sessionId, projectHash,
# startTime, lastUpdated, kind}, then messages {id, timestamp, type: user|gemini, content}
# among {"$set": {...}} patches. No cwd field and no live registry.
# ----------------------------------------------------------------------------------------

# A Gemini CLI process: comm is node (the npm install) — or gemini, for an install that is
# its own binary — and its script is .../bin/gemini. comm alone matches every node process.
GEMINI_COMMS = {"node", "gemini"}


def gemini_projects() -> dict[str, str]:
    """Absolute project path -> slug: projects.json, then each tmp/<slug>/.project_root
    (which also covers a slug projects.json has lost). Unreadable parts are skipped —
    gemini_format_note() is what says the shape moved."""
    out: dict[str, str] = {}
    try:
        reg = json.loads(_gemini_dir("projects.json").read_text(encoding="utf-8"))
        for path, slug in (reg.get("projects") or {}).items():
            if isinstance(path, str) and isinstance(slug, str) and "/" not in slug:
                out[path.rstrip("/") or "/"] = slug
    except (OSError, ValueError, AttributeError):
        pass
    try:
        for d in _gemini_dir("tmp").iterdir():
            try:
                path = (d / ".project_root").read_text(encoding="utf-8").strip().rstrip("/")
            except OSError:
                continue
            if path:
                out.setdefault(path, d.name)
    except OSError:
        pass
    return out


def gemini_chat_dirs(repo: "Path | str") -> list[tuple[Path, "str | None"]]:
    """(chats dir, worktree name or None) for the repo itself and each Claude-layout
    worktree under it (<repo>/.claude/worktrees/<name>, the dirs the Claude backend finds)."""
    me = str(Path(repo).resolve())
    wt_dir = me + "/.claude/worktrees/"
    out = []
    for path, slug in sorted(gemini_projects().items()):
        if path == me:
            wt = None
        elif path.startswith(wt_dir) and "/" not in path[len(wt_dir):]:
            wt = path[len(wt_dir):]
        else:
            continue
        d = _gemini_dir("tmp", slug, "chats")
        if d.is_dir():
            out.append((d, wt))
    return out


def _gemini_argv(pid: int) -> "list[str] | None":
    """The pid's argv when it is a Gemini CLI process, else None."""
    try:
        comm = Path(f"/proc/{pid}/comm").read_text(encoding="ascii", errors="replace").strip()
        if comm not in GEMINI_COMMS:
            return None
        argv = [a for a in Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace").split("\0") if a]
    except OSError:
        return None
    if not argv:
        return None
    if os.path.basename(argv[0]) == "gemini":
        return argv
    script = next((a for a in argv[1:] if not a.startswith("-")), "")
    return argv if script.endswith("/bin/gemini") or script == "gemini" else None


def _ppid(pid: int) -> "int | None":
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        return int(stat[stat.rindex(")") + 2:].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def gemini_live() -> list[dict]:
    """Running Gemini CLI sessions, from /proc: one per process pair (the npm shim relaunches
    itself as a child, so a gemini process whose parent is one is the same session and is
    left out). The session id is not knowable from the process — no live registry, and the
    chat file names no pid — so `id` is gemini:<pid>, which never matches a transcript."""
    pids = set()
    try:
        for name in os.listdir("/proc"):
            if name.isdigit() and _gemini_argv(int(name)) is not None:
                pids.add(int(name))
    except OSError:
        return []
    out = []
    for pid in sorted(pids):
        if _ppid(pid) in pids:
            continue
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            cwd = ""
        started = _proc_start_epoch(pid)
        out.append({"tool": "gemini", "id": f"gemini:{pid}", "pid": pid, "cwd": cwd,
                    **({"startedAt": started * 1000} if started is not None else {})})
    return out


def _gemini_text(content) -> str:
    """A Gemini message's text: a string, or a list of {text} parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("text"))
    return ""


def gemini_scan(path: Path) -> "dict | None":
    """One chat file: its id and start from the first record, `last` from the newest
    lastUpdated (a $set's, else the file's mtime), the first user text past Gemini's own
    <session_context> preamble, the last model reply and a $set summary."""
    from datetime import datetime, timezone
    info = {"id": None, "file": path, "start": None, "last": None, "first_user": "", "last_assistant": "", "summary": ""}
    last = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if i == 0:
                    info["id"], info["start"] = obj.get("sessionId"), obj.get("startTime")
                    last = obj.get("lastUpdated") or last
                    continue
                patch = obj.get("$set")
                if isinstance(patch, dict):
                    last = patch.get("lastUpdated") or last
                    if isinstance(patch.get("summary"), str):
                        info["summary"] = patch["summary"]
                    continue
                text = _gemini_text(obj.get("content"))
                if obj.get("type") == "user" and not info["first_user"] and text.strip() \
                        and not text.lstrip().startswith("<session_context>"):
                    info["first_user"] = text
                elif obj.get("type") == "gemini" and text.strip():
                    info["last_assistant"] = text
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    try:
        info["last"] = datetime.fromisoformat(str(last).replace("Z", "+00:00")) if last else mtime
    except ValueError:
        info["last"] = mtime
    if info["last"].tzinfo is None:
        info["last"] = info["last"].replace(tzinfo=timezone.utc)
    if not info["id"] or not (info["first_user"] or info["last_assistant"] or info["summary"]):
        return None
    return info


def gemini_format_note() -> "str | None":
    """TD-050's canary for Gemini CLI (read on 0.64.0, and it updates itself): projects.json
    must be {"projects": {path: slug}}, and the newest settled chat file's first record must
    carry sessionId and startTime. Silent when ~/.gemini has no such file yet."""
    bad = []
    pj = _gemini_dir("projects.json")
    try:
        reg = json.loads(pj.read_text(encoding="utf-8"))
        if not (isinstance(reg, dict) and isinstance(reg.get("projects"), dict)):
            bad.append(f"{pj} is not {{\"projects\": {{path: slug}}}}")
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        bad.append(f"{pj} does not parse ({e})")
    now = time.time()
    try:
        settled = sorted(((f.stat().st_mtime, f) for f in _gemini_dir("tmp").glob("*/chats/*.jsonl")
                          if now - f.stat().st_mtime >= REGISTRY_SETTLE_S), reverse=True)
    except OSError:
        settled = []
    if settled:
        newest = settled[0][1]
        try:
            with open(newest, encoding="utf-8", errors="replace") as f:
                head = json.loads(f.readline())
            ok = isinstance(head, dict) and "sessionId" in head and "startTime" in head
        except (OSError, ValueError):
            ok = False
        if not ok:
            bad.append(f"the newest chat file ({newest}) does not open with a session record")
    if not bad:
        return None
    return ("⚠ Gemini CLI's session files have moved on (read on 0.64.0): " + "; ".join(bad)
            + " — until the scripts are updated, the session index and the sweep row may miss Gemini sessions.")


# ----------------------------------------------------------------------------------------
# The Claude backend (moved from check_anchor.py and list_sessions.py, TD-100)
# ----------------------------------------------------------------------------------------

# A registry pid must belong to a process that plausibly IS its Claude Code
# session. Claude Code's own comm varies by install (native binary vs. a node
# launcher), so this is an allowlist of plausible names, not an identity test —
# its job is only to reject the obvious impostors a recycled pid produces (bash,
# python, vite, sleep). Widen it rather than narrowing it: a name missing here
# resurrects the false-conflict bug this filter exists to kill.
SESSION_COMMS = {"claude", "node"}

# Clock skew allowance between the entry's startedAt (wall clock, written by the
# session process) and the process start derived from /proc. Both come from the
# same kernel, so the real spread is sub-second; this is slack, not a threshold.
START_SKEW_SEC = 120


def _proc_start_ticks(pid: int) -> int | None:
    """Field 22 of /proc/<pid>/stat — process start in clock ticks since boot.

    The comm field is parenthesized and may itself contain spaces or parens, so
    split after the LAST ')'. Raw ticks, deliberately unconverted: this is the
    unit the registry records, and comparing raw values avoids every rounding
    and clock-correction question that converting to wall-clock introduces.
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
        return int(stat[stat.rindex(")") + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _proc_start_epoch(pid: int) -> float | None:
    """Wall-clock start time of PID, or None if it can't be determined.

    btime in /proc/stat is the boot epoch; both it and the tick count are
    host-kernel values readable from inside a container, which is precisely the
    case this exists to serve.
    """
    ticks = _proc_start_ticks(pid)
    if ticks is None:
        return None
    try:
        hz = os.sysconf("SC_CLK_TCK")
        btime = None
        for line in Path("/proc/stat").read_text(encoding="ascii", errors="replace").splitlines():
            if line.startswith("btime "):
                btime = int(line.split()[1])
                break
        if btime is None or not hz:
            return None
        return btime + ticks / hz
    except (OSError, ValueError, AttributeError):
        return None


def _entry_proc_start(entry: dict) -> int | None:
    """The entry's recorded procStart in clock ticks (Claude Code writes it as a string)."""
    try:
        return int(entry["procStart"])
    except (KeyError, TypeError, ValueError):
        return None


def _pid_is_dead(entry: dict) -> bool:
    """True only when the entry's pid is POSITIVELY not this session's process.

    Undeterminable cases return False (keep the entry) — a guard that stays
    quiet is worse than one that occasionally warns twice.
    """
    pid = _entry_pid(entry)
    if pid is None:
        return False  # no pid recorded — nothing to disprove
    if not procfs_available():
        # No procfs at all (macOS, some sandboxes): a missing /proc/<pid> proves
        # nothing, and reading it as "dead" silenced the guard and made every
        # worktree look idle to the reaper (TD-043). Undeterminable — keep it.
        return False
    if not Path(f"/proc/{pid}").exists():
        return True  # stale registry entry (same-namespace case)

    # PRIMARY, and exact: the registry records procStart in the same units and
    # epoch as /proc/<pid>/stat field 22, so equality identifies the SAME
    # PROCESS rather than merely a plausible one. Both values come from the one
    # kernel, so this is namespace-independent, and it needs neither the comm
    # allowlist nor btime — no wall-clock conversion means no exposure to a
    # post-boot clock correction shifting derived start times. Present on every
    # entry from Claude Code versions in circulation; the heuristics below exist
    # only for entries that predate the field.
    recorded = _entry_proc_start(entry)
    actual = _proc_start_ticks(pid)
    if recorded is not None and actual is not None:
        return recorded != actual

    # FALLBACK, in order of strength. Start time is checked first and decides on
    # its own: the session writes its own registry entry, so its process always
    # predates the entry, and a process that started after it took the pid later.
    started = entry.get("startedAt")
    proc_start = _proc_start_epoch(pid)
    if isinstance(started, (int, float)) and proc_start is not None:
        return proc_start > started / 1000 + START_SKEW_SEC

    # Weakest, and only when nothing better is available: an unrecognized comm.
    # Deliberately last — comm is an allowlist, and /proc/<pid>/comm truncates at
    # 15 chars, so a future Claude Code launched under a different name would be
    # judged dead here and the guard would stop reporting real conflicts. That
    # silent-permissive direction is why this never runs while procStart or a
    # usable start time is available.
    try:
        comm = Path(f"/proc/{pid}/comm").read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        comm = ""
    return bool(comm) and comm not in SESSION_COMMS


def procfs_available() -> bool:
    """Whether this host has a procfs to judge liveness by (TD-043)."""
    return Path("/proc/self").exists()


def live_sessions() -> list[dict]:
    reg = Path.home() / ".claude" / "sessions"
    if not reg.is_dir():
        return []
    out = []
    for f in reg.glob("*.json"):
        try:
            obj = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(obj, dict) or "sessionId" not in obj:
            continue
        if _pid_is_dead(obj):
            continue
        out.append(obj)
    return out


REGISTRY_SETTLE_S = 5  # a registry file younger than this may still be being written


def registry_format_note() -> str | None:
    """TD-050 canary: the session registry is an undocumented Claude Code internal
    (verified against Claude Code 2.1.280). When the NEWEST settled entry does not parse as
    a session, the format moved — and the anchor guard, the reaper's idle gate and
    list_sessions all degrade to "nobody is here" without a word. Judged on the newest
    file older than REGISTRY_SETTLE_S, never on this session's own entry (written as the
    session starts, racing the hooks) and never on "any file parses" (one stale entry in the
    old format would mask a change forever); a file younger than that may be mid-write."""
    reg = Path.home() / ".claude" / "sessions"
    now = time.time()
    try:
        settled = sorted(((f.stat().st_mtime, f) for f in reg.glob("*.json")
                          if now - f.stat().st_mtime >= REGISTRY_SETTLE_S), reverse=True)
    except OSError:
        return None
    if not settled:
        return None
    newest = settled[0][1]
    try:
        obj = json.loads(newest.read_text(encoding="utf-8", errors="replace"))
        if isinstance(obj, dict) and "sessionId" in obj and "pid" in obj:
            return None
    except (json.JSONDecodeError, OSError):
        pass
    return (f"⚠ the newest entry in Claude Code's session registry ({newest}) does not read as a "
            "session — its format may have changed (verified against 2.1.280). Until the scripts "
            "are updated, the anchor guard, the reaper's idle gate and list_sessions see no sessions.")


def _ancestor_pids() -> set[int]:
    """Pids identifying THIS session: us up to our own claude process, via /proc.

    The hook runs as a descendant of the claude process, so the session that
    spawned it is always an ancestor. The walk stops at (and includes) the
    first ancestor whose comm is "claude" — that one is our session; anything
    ABOVE it is foreign, possibly a different claude session that spawned the
    shell this one was started from, and excluding it would silently suppress
    a genuine conflict. If no claude ancestor is identifiable (no /proc, or a
    wrapper changes comm), the walk runs to the top — over-inclusive fallback,
    trading the rare nested-session false negative for never regressing the
    /resume fix. On systems without /proc entirely the walk stops at the first
    miss and returns whatever it collected (worst case just our own pid — the
    pre-fix behavior, never worse).
    """
    pids: set[int] = set()
    pid = os.getpid()
    while pid > 1 and pid not in pids and len(pids) < 64:
        pids.add(pid)
        try:
            comm = Path(f"/proc/{pid}/comm").read_text(encoding="ascii", errors="replace").strip()
        except OSError:
            comm = ""
        if comm == "claude" and pid != os.getpid():
            break  # our own session process — its ancestors are not us
        try:
            status = Path(f"/proc/{pid}/status").read_text(encoding="ascii", errors="replace")
        except OSError:
            break
        m = re.search(r"^PPid:\s*(\d+)", status, re.MULTILINE)
        if not m:
            break
        pid = int(m.group(1))
    return pids


def _entry_pid(s: dict) -> int | None:
    try:
        return int(s.get("pid"))
    except (TypeError, ValueError):
        return None


# Claude Code's own rule (TD-11), read from its bundle (2.1.283: `k`, `qx`, `Le`, `KJ`):
#   n = path.replace(/[^a-zA-Z0-9]/g, "-")      # per UTF-16 code unit
#   n.length <= 200 ? n : n.slice(0, 200) + "-" + Math.abs(javaHash(path)).toString(36)
# Parity (§7): check_claude_memory.sh's ENCODED calls this function for any path its sed
# fast path cannot get right (non-ASCII, or past the cap); tests/test_list_sessions.sh
# holds the expectations, taken from that JS run under node. Not modelled: Claude Code's
# CLAUDE_CODE_PROJECT_DIR_NAME override (honoured only with CLAUDE_CONFIG_DIR set), and
# a caller passing a Path has already had `//` collapsed, where the JS sees the raw string.
PROJECT_DIR_MAX = 200


def munge(path: Path) -> str:
    """Path -> Claude Code's project-dir name.

    Claude Code replaces every non-alphanumeric character with '-', not just
    '/' and '.'. Spelling out only those two silently loses any repo whose path
    contains '_' (or anything else): /workspaces/work_history lives in
    ~/.claude/projects/-workspaces-work-history, and the two-replace version
    looked for -workspaces-work_history, found nothing, and reported "no
    project dirs" — indistinguishable from a repo that genuinely has no
    sessions. The character class is a superset of the old behavior ('-' maps
    to itself), so it changes nothing for paths that already worked.

    JavaScript strings are UTF-16, so the replace counts code units: an accented
    letter (NFC) is one '-', a decomposed one is its base letter plus one '-', and a
    character outside the BMP (an emoji) is TWO. A name past 200 units is cut there
    and suffixed with a base-36 hash of the whole path (TD-11).
    """
    s = str(path)
    units = s.encode("utf-16-le", "surrogatepass")
    out = "".join(c if c.isascii() and c.isalnum() else "-" * (len(c.encode("utf-16-le", "surrogatepass")) // 2)
                  for c in s)
    if len(out) <= PROJECT_DIR_MAX:
        return out
    h = 0
    for i in range(0, len(units), 2):   # Java's String.hashCode, as int32
        h = (h * 31 + int.from_bytes(units[i:i + 2], "little")) & 0xFFFFFFFF
    h = abs(h - (1 << 32) if h >= 1 << 31 else h)
    digits = ""
    while True:
        h, r = divmod(h, 36)
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + digits
        if not h:
            break
    return f"{out[:PROJECT_DIR_MAX]}-{digits}"


def project_dirs(repo: Path) -> list[Path]:
    """The repo's own project dir plus worktree-variant dirs."""
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return []
    dirs = []
    exact = base / munge(repo)
    if exact.is_dir():
        dirs.append(exact)
    # worktrees live under <repo>/.claude/worktrees/<name> → munged prefix match
    wt_prefix = munge(repo) + WORKTREE_MARKER
    dirs += [d for d in base.iterdir() if d.is_dir() and d.name.startswith(wt_prefix)]
    return dirs

# Claude Code's own worktree layout, <repo>/.claude/worktrees/<name>, munged
WORKTREE_MARKER = "--claude-worktrees-"
