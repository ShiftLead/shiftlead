"""The disk sweep's branch rule (design §4.6 *The disk sweep*, *branches*, TD-2104, TD-2112).

A local branch of a registered repo is deleted only when its work has **landed**, proved in one of two ways: its tip
is on `origin/<default>`, or it is exactly the head of a PR merged into `<default>` whose merge commit is on
`origin/<default>`. The weigh runs the cheapest test first and gives each branch one why: never the default or the
counter branch; kept when checked out, moved within `worktree_keep_days`, tracking a live upstream, holding a commit
only in its reflog, or proved by neither. Just before `git branch -D` a name a worktree can have has the two locks a
create holds taken without waiting, and the tip and the reflog are read again.

Only the default home's host agent runs it (the caller gives that scope), at most once a day for at most
`SWEEP_BRANCH_S`, sorted by repo then branch; a run the budget stops carries on after `cursor`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sessionorc import gitinfo
from sessionorc.ledgerboard import COUNTER_BRANCH

log = logging.getLogger(__name__)

SWEEP_BRANCH_S = 60.0  # a run's budget; the next hourly pass carries on from the cursor
SWEEP_BRANCH_EVERY = 86400.0  # a run starts at most once a day
STEP = gitinfo.REAP_STEP
NOT_WEIGHED = gitinfo.NOT_WEIGHED
NO_FORGE = "no forge answer"
BUSY = "busy: a start is using it"
MOVED = "moved"
_REFUSED = re.compile(r"(?:used by worktree|checked out) at '([^']+)'")

Hold = Callable[[Path, str, Path], Callable[[], None] | None]


@dataclass
class Pass:
    """One run's outcome. `deleted` is `(repo, branch, commit, proof)` (a dry run's: what it would delete), `kept`
    `(repo, branch, why)`, `cursor` the pair weighed last (None once a run reaches the end), `present` every branch
    listed and `unread` the repos whose branches could not be listed, whose rows a finished run must not drop."""

    deleted: list[tuple[str, str, str, str]] = field(default_factory=list)
    kept: list[tuple[str, str, str]] = field(default_factory=list)
    cursor: tuple[str, str] | None = None
    stopped: bool = False
    present: set[tuple[str, str]] = field(default_factory=set)
    unread: set[str] = field(default_factory=set)


@dataclass
class _Repo:
    """What one repo's branches share within a run, read once."""

    path: Path
    default: str
    base: str  # `refs/remotes/origin/<default>`
    git_dir: str  # the clone's own git directory, absolute: a linked worktree of a bare repo reads as not bare
    holders: dict[str, str]  # each branch a worktree has checked out, and where
    logging: bool | None = None  # ref logging on or off; None until read, or where it could not be
    logging_read: bool = False
    forge: bool = True  # False after the first read with no forge answer


def _call(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str] | None:
    """One read-only git command with its exit code, or None when it could not be run."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=STEP,
            env=gitinfo.read_only_env(),
            input=stdin,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _branches(repo: Path) -> list[str] | None:
    got = gitinfo._git(repo, "for-each-ref", "--format=%(refname)", "refs/heads/", timeout=STEP)
    return None if got is None else [r.removeprefix("refs/heads/") for r in got.splitlines() if r]


def _holders(repo: Path) -> dict[str, str] | None:
    """`git worktree list --porcelain`: each checked-out branch and its worktree, the main checkout's included."""
    out = gitinfo._git(repo, "worktree", "list", "--porcelain", timeout=STEP)
    if out is None:
        return None
    got: dict[str, str] = {}
    path = ""
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree ") :]
        elif line.startswith("branch refs/heads/"):
            got[line[len("branch refs/heads/") :]] = path
    return got


def _context(repo: Path) -> _Repo | None:
    """The repo's shared reads, or None where one failed or `refs/remotes/origin/<default>` does not exist."""
    default = gitinfo.default_branch(repo, STEP)
    base = f"refs/remotes/origin/{default}"
    if gitinfo._git(repo, "rev-parse", "--verify", "-q", f"{base}^{{commit}}", timeout=STEP) is None:
        return None
    common = gitinfo._git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir", timeout=STEP)
    holders = _holders(repo)
    if not common or not common.strip() or holders is None:
        return None
    return _Repo(repo, default, base, common.strip(), holders)


def _logging(ctx: _Repo) -> bool | None:
    """Whether the clone logs ref updates (git's own rule), read once a run; None where a read failed."""
    if ctx.logging_read:
        return ctx.logging
    ctx.logging_read = True
    ctx.logging = _read_logging(ctx)
    return ctx.logging


def _read_logging(ctx: _Repo) -> bool | None:
    at = f"--git-dir={ctx.git_dir}"
    raw = _call(ctx.path, at, "config", "--get", "core.logAllRefUpdates")
    if raw is None or raw.returncode not in (0, 1):
        return None
    if raw.returncode == 1:  # unset: git's default logs only in a non-bare repo
        bare = _call(ctx.path, at, "rev-parse", "--is-bare-repository")
        if bare is None or bare.returncode != 0 or bare.stdout.strip() not in ("true", "false"):
            return None
        return bare.stdout.strip() == "false"
    if raw.stdout.strip() == "always":
        return True
    typed = _call(ctx.path, at, "config", "--type=bool", "core.logAllRefUpdates")
    if typed is None or typed.returncode != 0 or typed.stdout.strip() not in ("true", "false"):
        return None
    return typed.stdout.strip() == "true"


def _age_why(ctx: _Repo, branch: str, now: float, keep_days: float) -> str | None:
    """Step 3: why the branch's age keeps it, or None when it is past the age."""
    got = gitinfo._git(
        ctx.path,
        f"--git-dir={ctx.git_dir}",
        "log",
        "-g",
        "-1",
        "--date=unix",
        "--format=%gd",
        f"refs/heads/{branch}",
        timeout=STEP,
    )
    if got is None:
        return NOT_WEIGHED
    text = got.strip()
    if not text:  # exit 0 with nothing: an expired reflog, but only where the repo logs ref updates
        on = _logging(ctx)
        if on is None:
            return NOT_WEIGHED
        return None if on else "no reflog"
    m = re.search(r"@\{(\d+)\}$", text)
    if m is None:
        return NOT_WEIGHED
    return f"moved within {keep_days:g} days" if now - int(m.group(1)) < keep_days * 86400 else None


def _upstream_why(ctx: _Repo, branch: str) -> str | None:
    """Step 4: the live upstream that keeps the branch, or None; `origin/<default>` and a gone one keep nothing."""
    got = gitinfo._git(
        ctx.path, "for-each-ref", "--format=%(upstream) %(upstream:track)", f"refs/heads/{branch}", timeout=STEP
    )
    if got is None:
        return NOT_WEIGHED
    upstream, _, track = got.strip("\n").partition(" ")
    if not upstream or "[gone]" in track or upstream == ctx.base:
        return None
    return f"tracks {upstream.removeprefix('refs/remotes/').removeprefix('refs/heads/')}"


def _reflog(ctx: _Repo, branch: str) -> list[str] | None:
    got = gitinfo._git(
        ctx.path, f"--git-dir={ctx.git_dir}", "log", "-g", "--format=%H", f"refs/heads/{branch}", timeout=STEP
    )
    return None if got is None else list(dict.fromkeys(got.split()))


def _only_in_reflog(ctx: _Repo, commits: list[str]) -> int | None:
    """How many of the reflog's commits nothing else reaches; `--branches` covers the tip and its ancestors."""
    if not commits:
        return 0
    got = gitinfo._git(
        ctx.path,
        "rev-list",
        "--stdin",
        "--not",
        "--remotes",
        "--tags",
        "--branches",
        input="".join(f"{c}\n" for c in commits),
        timeout=STEP,
    )
    return None if got is None else len(got.splitlines())


def _tip(ctx: _Repo, branch: str) -> str | None:
    got = gitinfo._git(ctx.path, "rev-parse", "--verify", "-q", f"refs/heads/{branch}^{{commit}}", timeout=STEP)
    return got.strip() or None if got else None


def _on_default(ctx: _Repo, commit: str) -> bool | None:
    rc = gitinfo._git_rc(ctx.path, "merge-base", "--is-ancestor", commit, ctx.base, timeout=STEP)
    return True if rc == 0 else False if rc == 1 else None


def _forge_prs(ctx: _Repo, branch: str) -> list[dict] | None:
    """The merged PRs headed by `branch`, or None for *no forge answer*: no `gh`, a failure, a timeout, bad output."""
    cp = gitinfo._run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "merged",
            "--head",
            branch,
            "--limit",
            "100",
            "--json",
            "number,headRefOid,baseRefName,mergeCommit",
        ],
        STEP,
        cwd=ctx.path,
    )
    if cp is None or cp.returncode != 0:
        return None
    try:
        got = json.loads(cp.stdout)
    except ValueError:
        return None
    return [p for p in got if isinstance(p, dict)] if isinstance(got, list) else None


def _proof(ctx: _Repo, branch: str, tip: str) -> tuple[str | None, str | None]:
    """Step 6: `(proof, None)` where the branch has landed, else `(None, why)`."""
    on = _on_default(ctx, tip)
    if on is None:
        return None, NOT_WEIGHED
    if on:
        return f"on {ctx.default}", None
    asked = False
    failed = False
    if ctx.forge:
        prs = _forge_prs(ctx, branch)
        if prs is None:
            ctx.forge = False  # the rest of this repo's branches are weighed by the first proof alone
        else:
            asked = True
            for pr in prs:
                merge = pr.get("mergeCommit")
                oid = merge.get("oid") if isinstance(merge, dict) else None
                if pr.get("headRefOid") != tip or pr.get("baseRefName") != ctx.default or not isinstance(oid, str):
                    continue
                landed = _on_default(ctx, oid)
                if landed:
                    return f"PR #{pr.get('number')}", None
                failed = failed or landed is None
    if failed:
        return None, NOT_WEIGHED
    if not asked:
        return None, NO_FORGE
    count = gitinfo._git(ctx.path, "rev-list", "--count", f"{ctx.base}..refs/heads/{branch}", timeout=STEP)
    if count is None or not count.strip().isdigit():
        return None, NOT_WEIGHED
    n = int(count)
    return None, f"not landed: {n} commit{'s' if n != 1 else ''}"


def weigh(ctx: _Repo, branch: str, now: float, keep_days: float) -> tuple[str | None, str, str, list[str]]:
    """Steps 2 to 6 for one branch: `(why, proof, tip, reflog)`, `why` None where it has landed and may go."""
    if branch in ctx.holders:
        return f"checked out in {ctx.holders[branch]}", "", "", []
    if why := _age_why(ctx, branch, now, keep_days):
        return why, "", "", []
    if why := _upstream_why(ctx, branch):
        return why, "", "", []
    tip = _tip(ctx, branch)
    commits = _reflog(ctx, branch)
    if tip is None or commits is None:
        return NOT_WEIGHED, "", "", []
    only = _only_in_reflog(ctx, commits)
    if only is None:
        return NOT_WEIGHED, "", "", []
    if only:
        return f"{only} commit{'s' if only != 1 else ''} only in its reflog", "", "", []
    proof, why = _proof(ctx, branch, tip)
    return why, proof or "", tip, commits


def _no_lock() -> None:
    """The release of a name no worktree can have, which takes no lock."""


def _delete(ctx: _Repo, branch: str, tip: str, commits: list[str], hold: Hold | None) -> str | None:
    """The delete under the create's locks: None once it is gone, else why the branch stays."""
    release: Callable[[], None] | None = _no_lock
    if gitinfo.WORKTREE_NAME.fullmatch(branch):
        if hold is None:
            return BUSY
        try:
            main = gitinfo.main_checkout(ctx.path, STEP)
            path = gitinfo.worktree_path(main, branch, STEP)
        except gitinfo.WorktreeError:
            return NOT_WEIGHED
        release = hold(main, branch, path)
        if release is None:
            return BUSY
    try:
        if _tip(ctx, branch) != tip or _reflog(ctx, branch) != commits:
            return MOVED
        cp = gitinfo._run(["git", "-C", str(ctx.path), "branch", "-D", "--", branch], STEP)
        if cp is None:
            return NOT_WEIGHED
        if cp.returncode == 0:
            return None
        m = _REFUSED.search(cp.stderr)
        return f"checked out in {m.group(1)}" if m else NOT_WEIGHED
    finally:
        release()


def sweep(
    repos: Iterable[Path | str],
    *,
    cursor: tuple[str, str] | None,
    keep_days: float,
    hold: Hold | None = None,
    budget: float = SWEEP_BRANCH_S,
    now: float | None = None,
    dry: bool = False,
) -> Pass:
    """One run over every repo's branches, sorted by repo then name, from the first pair after `cursor`, until
    `budget` seconds are spent. `hold(main, name, path)` takes the create's two locks without waiting and returns their
    release, or None when either is busy. `dry` asks the forge but takes no lock and deletes nothing."""
    now = time.time() if now is None else now
    out = Pass(cursor=cursor)
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for r in sorted({str(Path(x)) for x in repos}):
        common = gitinfo._git(r, "rev-parse", "--path-format=absolute", "--git-common-dir", timeout=STEP)
        real = os.path.realpath(common.strip() if common and common.strip() else r)
        if real in seen:  # two roots of one clone (a checkout and its worktree) weigh its branches once
            continue
        seen.add(real)
        names = _branches(Path(r))
        if names is None:
            out.unread.add(r)
            log.warning("branch sweep: %s's branches could not be listed", r)
            continue
        default = gitinfo.default_branch(r, STEP)
        pairs += [(r, b) for b in names if b not in (default, COUNTER_BRANCH)]
    pairs.sort()
    out.present = set(pairs)
    contexts: dict[str, _Repo | None] = {}
    start = time.monotonic()
    for repo, branch in pairs:
        if cursor is not None and (repo, branch) <= cursor:
            continue
        if time.monotonic() - start >= budget:
            out.stopped = True
            return out
        out.cursor = (repo, branch)
        try:
            if repo not in contexts:
                contexts[repo] = _context(Path(repo))
            ctx = contexts[repo]
            if ctx is None:
                out.kept.append((repo, branch, NOT_WEIGHED))
                continue
            why, proof, tip, commits = weigh(ctx, branch, now, keep_days)
            if why is None and not dry:
                why = _delete(ctx, branch, tip, commits, hold)
        except Exception:  # noqa: BLE001 — one branch that cannot be weighed never starves the rest
            log.exception("branch sweep: %s %s could not be weighed", repo, branch)
            why = NOT_WEIGHED
        if why is not None:
            out.kept.append((repo, branch, why))
            continue
        out.deleted.append((repo, branch, tip, proof))
        if not dry:
            log.info("branch sweep: deleted %s in %s at %s (%s)", branch, repo, tip, proof)
    out.cursor = None
    return out
