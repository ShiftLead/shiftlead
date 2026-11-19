"""The disk sweep's worktree rule (design §4.6 *The disk sweep*, *worktrees*, TD-1945).

A worktree under a registered repo's worktree root (its `docs/cadence.toml` `worktree-root`, `.claude/worktrees`
where unset) goes once it passes the five tests agent-cadence's `reap_worktrees.sh` states — *landed* (ported into
`gitinfo.landed_of`), then *clean*, *idle*, *unlocked* and *nested* (`gitinfo.worktree_holds`, the close-time reap's)
— and its newest write is older than `worktree_keep_days`. A worktree that is not *landed* is weighed by §4.2's one
measure only for its why (a commit only on this machine), and is kept either way. It is taken out by
`git worktree remove` without `--force`, never by `gitinfo.reap_worktree`; no branch is deleted. Never the main
checkout, a detached worktree, a locked one, one that is, is inside or holds a transcript root.

Only the default home's host agent runs it (the caller gives that scope), and a pass weighs worktrees in path order
for at most `SWEEP_WORKTREE_S`, the next carrying on after the path the last one weighed (`cursor`).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sessionorc import gitinfo
from sessionorc.scratch import overlaps

log = logging.getLogger(__name__)

SWEEP_WORKTREE_S = 60.0  # a pass's budget for weighing worktrees; the next carries on from the cursor
DEFAULT_ROOT = ".claude/worktrees"
LANDED = ("yes", "since", "empty")  # `landed_of`'s answers the sweep reads *landed*; *empty* is the script's keep
STEP = gitinfo.REAP_STEP


def worktree_root(repo: Path) -> Path:
    """The repo's worktree root: `docs/cadence.toml`'s top-level `worktree-root`, a directory inside the clone, else
    `.claude/worktrees` (agent-cadence's `cadence_config`, TD-101). A file that cannot be read or a value that is not
    a relative path inside the clone reads the default."""
    rel = DEFAULT_ROOT
    try:
        import tomllib

        got = tomllib.loads((repo / gitinfo.PIN_FILE).read_text(encoding="utf-8")).get("worktree-root")
    except (OSError, ValueError):
        got = None
    if isinstance(got, str) and got.strip() and not os.path.isabs(got):
        parts = [p for p in Path(got.strip()).parts if p != "."]
        if parts and ".." not in parts:
            inside = Path(os.path.realpath(repo / Path(*parts)))
            if inside != Path(os.path.realpath(repo)) and inside.is_relative_to(os.path.realpath(repo)):
                rel = str(Path(*parts))
    return repo / rel


def listed(repo: Path, timeout: float = STEP) -> list[tuple[Path, str | None]] | None:
    """`git worktree list --porcelain` in `repo`: each worktree's path and its branch (None: detached), the main
    checkout left out; None when it cannot be read."""
    out = gitinfo._git(repo, "worktree", "list", "--porcelain", timeout=timeout)
    if out is None:
        return None
    got: list[tuple[Path, str | None]] = []
    path: Path | None = None
    branch: str | None = None
    first = True
    for line in [*out.splitlines(), ""]:
        if line.startswith("worktree "):
            path, branch = Path(line[len("worktree ") :]), None
        elif line.startswith("branch refs/heads/"):
            branch = line[len("branch refs/heads/") :]
        elif not line and path is not None:
            if not first:
                got.append((path, branch))
            first, path = False, None
    return got


def newest_write(wt: Path, timeout: float = STEP) -> float | None:
    """The newest of the worktree's `HEAD`'s, its index's and its tracked files' modification times (`git ls-files`,
    so an ignored tree is not walked); None when it cannot be read."""
    times: list[float] = []
    for name in ("HEAD", "index"):
        p = gitinfo._git(wt, "rev-parse", "--path-format=absolute", "--git-path", name, timeout=timeout)
        if p is None:
            return None
        try:
            times.append(Path(p.strip()).stat().st_mtime)
        except OSError:
            continue
    files = gitinfo._git(wt, "ls-files", "-z", timeout=timeout)
    if files is None:
        return None
    for f in files.split("\0"):
        if f:
            try:
                times.append((wt / f).lstat().st_mtime)
            except OSError:
                continue
    return max(times) if times else None


def weigh(
    wt: Path,
    repo: Path,
    branch: str | None,
    *,
    now: float,
    keep_days: float,
    deadline: float,
    idle: Callable[[], str | None] | None = None,
    transcript_roots: Iterable[Path] = (),
) -> str | None:
    """Why worktree `wt` of `repo` is kept, or None when the sweep may remove it (the module's rule, in its order:
    the guards, the age filter, *landed*, then `worktree_holds`)."""
    if Path(os.path.realpath(wt)) == Path(os.path.realpath(repo)):
        return "main checkout"
    if wt.is_symlink() or not wt.is_dir():
        return "not a directory"
    if branch is None:
        return "detached"
    if any(overlaps(wt, t) for t in transcript_roots):
        return "transcripts"
    newest = newest_write(wt)
    if newest is None:
        return gitinfo.UNKNOWN
    if now - newest < keep_days * 86400:
        return f"written within {keep_days:g} days"
    landed = gitinfo.landed_of(wt, branch, root=repo)
    if landed not in LANDED:
        upstream = gitinfo._git(wt, "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}", timeout=STEP)
        up = upstream.strip() if upstream and upstream.strip() else None
        ahead = 0
        if up:
            n = gitinfo._git(wt, "rev-list", "--count", f"{up}..{branch}", timeout=STEP)
            ahead = int(n.strip()) if n and n.strip().isdigit() else 0
        only, _ = gitinfo._unpushed(wt, branch, up, ahead, STEP, ref=branch)
        if only:
            return f"{only} commit{'s' if only != 1 else ''} only on this machine"
        return "not landed" if landed in ("no", "reverted") else f"not landed ({landed})"
    return gitinfo.worktree_holds(wt, repo, deadline, idle=idle)


def remove(wt: Path, repo: Path, timeout: float = STEP) -> bool:
    """`git worktree remove` without `--force`: git itself refuses a worktree with changes or a lock."""
    cp = gitinfo._run(["git", "-C", str(repo), "worktree", "remove", str(wt)], timeout)
    return cp is not None and cp.returncode == 0


@dataclass
class Pass:
    """One pass's outcome: what it removed, what it kept and why, and the path it weighed last (the next cursor)."""

    removed: list[str] = field(default_factory=list)
    kept: list[tuple[str, str]] = field(default_factory=list)
    cursor: str = ""


def sweep(
    repos: Iterable[Path | str],
    *,
    cursor: str,
    keep_days: float,
    idle: Callable[[Path], str | None] | None = None,
    hold: Callable[[Path, Path], Callable[[], None] | None] | None = None,
    transcript_roots: Iterable[Path] = (),
    budget: float = SWEEP_WORKTREE_S,
    now: float | None = None,
) -> Pass:
    """One pass of the worktree rule over every worktree under each repo's worktree root, in path order from the
    first path after `cursor` (wrapping), until `budget` seconds are spent. `idle(wt)` is the host agent's
    `_reap_idle`; `hold(wt, main)` takes the create's locks without waiting and returns their release, or None when
    either is busy (*busy: a start is using it*); it is asked, and `idle` again, just before each removal."""
    now = time.time() if now is None else now
    troots = list(transcript_roots)
    found: list[tuple[Path, Path, str | None]] = []
    seen: set[str] = set()  # two roots naming one repo list its worktrees twice: each is weighed once
    for r in sorted({str(Path(x)) for x in repos}):
        repo = Path(r)
        root = worktree_root(repo)
        got = listed(repo)
        if got is None:
            log.warning("worktree sweep: %s's worktrees could not be listed", repo)
            continue
        for wt, branch in got:
            real = os.path.realpath(wt)
            if Path(real).parent == Path(os.path.realpath(root)) and real not in seen:
                seen.add(real)
                found.append((wt, repo, branch))
    found.sort(key=lambda x: str(x[0]))
    after = [x for x in found if str(x[0]) > cursor] if cursor else found
    order = after + [x for x in found if x not in after]
    out = Pass(cursor=cursor)
    start = time.monotonic()
    for wt, repo, branch in order:
        if time.monotonic() - start >= budget:
            break
        out.cursor = str(wt)
        try:
            why = _one(wt, repo, branch, now, keep_days, idle, hold, troots)
        except Exception:  # noqa: BLE001 — one worktree that cannot be weighed never starves the rest
            log.exception("worktree sweep: %s could not be weighed", wt)
            why = gitinfo.NOT_WEIGHED
        if why is None:
            out.removed.append(str(wt))
            log.info("worktree sweep: removed %s", wt)
        else:
            out.kept.append((str(wt), why))
    return out


def _one(
    wt: Path,
    repo: Path,
    branch: str | None,
    now: float,
    keep_days: float,
    idle: Callable[[Path], str | None] | None,
    hold: Callable[[Path, Path], Callable[[], None] | None] | None,
    troots: list[Path],
) -> str | None:
    """One worktree's weigh and, where nothing keeps it, its removal under the create's locks: its why, or None."""
    deadline = time.monotonic() + gitinfo.REAP_WITHIN
    why = weigh(
        wt,
        repo,
        branch,
        now=now,
        keep_days=keep_days,
        deadline=deadline,
        idle=(lambda w=wt: idle(w)) if idle is not None else None,
        transcript_roots=troots,
    )
    if why is None:
        release = hold(wt, repo) if hold is not None else (lambda: None)
        if release is None:
            why = "busy: a start is using it"
        else:
            try:
                why = idle(wt) if idle is not None else None
                if why is None and not remove(wt, repo):
                    why = "git worktree remove refused"
            finally:
                release()
    return why
