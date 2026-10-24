"""Per-directory git status for cards and the Focus side panel (design §4.4): branch, dirty,
ahead/behind, cheap enough to refresh on a tick."""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from sessionorc import paths


@dataclass
class GitInfo:
    branch: str
    dirty: int  # changed + untracked paths
    ahead: int
    behind: int
    upstream: str | None
    files: list[str]  # up to 20 porcelain lines ("M path", "?? path")
    # **One measure of pushed** (design §4.2, 2026-09-20, TD-080): *does this work exist only on
    # this machine*, never *is it merged*. Computed once here and read by the card's flag, Ready to
    # close, the Inbox's unpushed row and `ao team stop --close`, which had three tests between
    # them. `pushed_against` says what it was measured against, so a page can show it.
    unpushed: int = 0
    pushed_against: str = ""
    # the commit HEAD is at, so a detached HEAD can be named by it (design §4.5 *The card's
    # anatomy*, row 3, TD-095: *detached at <short sha>*); "" in a repo with no commit yet
    oid: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class WorktreeError(RuntimeError):
    pass


WORKTREES_DIR = ".claude/worktrees"  # design §5 default; Claude Code's own `--worktree` uses the same place


def worktree_path(repo: Path, name: str, timeout: float | None = None) -> Path:
    """Where `ensure_worktree` puts (or finds) the worktree `name` of `repo`: under the MAIN
    checkout's `.claude/worktrees/`, even when `repo` is a worktree or a subdirectory of it —
    `--show-toplevel` would answer with the worktree and nest the new one under it (cadence §9
    path-resolution; review 2026-09-06). Read-only: the one resolution every check of that path
    shares (review of PR #215). `timeout` bounds the read, as a reap's every git call is (TD-979)."""
    try:
        common = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise WorktreeError(f"{repo}: git did not say where its checkout is within {timeout:g} s") from None
    if common.returncode != 0:
        raise WorktreeError(f"{repo} is not a git repository")
    return Path(common.stdout.strip()).parent / WORKTREES_DIR / name


def toplevel(directory: Path | str, timeout: float = 5.0) -> str:
    """The top level of the checkout `directory` is in — a worktree's own, as git says — or "" outside
    one: the `stat` link method's `root` (design §4.4a *The New session form on another host*)."""
    return (_git(directory, "rev-parse", "--show-toplevel", timeout=timeout) or "").strip()


def absolute_git_dir(directory: Path | str, timeout: float = 5.0) -> str:
    """`git rev-parse --absolute-git-dir` in `directory` — a worktree's own — or "" outside a git tree."""
    return (_git(directory, "rev-parse", "--absolute-git-dir", timeout=timeout) or "").strip()


HYDRATE = "scripts/hydrate_worktree.sh"


def worktree_setup(repo: Path | str) -> tuple[str, str | None]:
    """The checkout's worktree setup (§5 *The seams*, TD-589): `("set", command)` for its
    `.shiftlead.yml` `worktree_setup:`, `("defaulted", HYDRATE)` when the key is unset and the checkout
    holds an executable `scripts/hydrate_worktree.sh` (dev-cadence's), `("absent", None)` otherwise. A
    file that cannot be read, or a key that is not a non-empty string, is the key unset: the clients
    (`shiftlead.repoconfig`) refuse such a file by name."""
    try:
        doc = yaml.safe_load(paths.repo_file(repo).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        doc = None
    got = doc.get("worktree_setup") if isinstance(doc, dict) else None
    if isinstance(got, str) and got.strip():
        return "set", got.strip()
    hydrate = Path(repo) / HYDRATE
    if hydrate.is_file() and os.access(hydrate, os.X_OK):
        return "defaulted", HYDRATE
    return "absent", None


def ensure_worktree(repo: Path, name: str, timeout: float = 60.0, *, resume: bool = False) -> tuple[Path, bool]:
    """`(path, created)`: `<repo>/.claude/worktrees/<name>` on branch <name>, created from origin's default branch
    (after a fetch with `--prune`) or from HEAD when there is no origin. A local `<name>` is checked out as it
    stands; a `resume` bases a new one on `origin/<name>` when that exists and `origin/HEAD` does not already
    contain it, so a Resume of a reaped record takes up its pushed work (design §4.1 *Started again*). Reused
    when it already exists. A new one is
    then set up by the repo's `worktree_setup` (§5 *The seams*, TD-589): a configured command, run by
    the shell in the new worktree with its path as `$1`, or by default the repo's own `scripts/hydrate_worktree.sh` when
    present (dev-cadence repos), so the worktree gets the untracked pieces git leaves out. `created` is whether
    this call made it, which the record keeps as `worktree_made` (design §4.1 *A close reaps the worktree it made*)."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name):
        raise WorktreeError(f"worktree name {name!r}: letters, digits, . _ - only")
    path = worktree_path(repo, name)
    repo = path.parent.parent.parent
    if path.is_dir():
        if subprocess.run(["git", "-C", str(path), "rev-parse", "--git-dir"], capture_output=True).returncode != 0:
            raise WorktreeError(f"{path} exists but is not a worktree")
        return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "--prune", "origin"], capture_output=True, timeout=timeout)

    def git_ok(*args: str) -> bool:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout).returncode == 0

    base = "origin/HEAD" if git_ok("rev-parse", "--verify", "-q", "origin/HEAD") else "HEAD"
    if (
        resume
        and base == "origin/HEAD"
        and git_ok("rev-parse", "--verify", "-q", f"refs/remotes/origin/{name}")
        and not git_ok("merge-base", "--is-ancestor", f"refs/remotes/origin/{name}", "origin/HEAD")
    ):
        base = f"origin/{name}"  # one pruned, or already in origin/HEAD, starts from origin/HEAD
    has_branch = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "-q", f"refs/heads/{name}"], capture_output=True
    )
    args = ["git", "-C", str(repo), "worktree", "add", "-q"]
    args += [str(path), name] if has_branch.returncode == 0 else ["-b", name, str(path), base]
    cp = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if cp.returncode != 0:
        raise WorktreeError(f"git worktree add failed: {cp.stderr.strip() or cp.stdout.strip()}")
    kind, command = worktree_setup(repo)
    if kind == "absent" or not command:
        return path, True
    if kind == "set":
        what, argv, cwd = command, ["sh", "-c", command, "sh", str(path)], str(path)  # the path its `$1`
    else:
        what, argv, cwd = "hydrate_worktree.sh", [str(repo / HYDRATE), str(path)], None
    try:
        hp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise WorktreeError(f"worktree created at {path}, but {what} could not run: {type(e).__name__}") from None
    if hp.returncode != 0:
        # The worktree exists and is usable; say what the setup left out rather than hide it.
        raise WorktreeError(f"worktree created at {path}, but {what} failed: {(hp.stderr or hp.stdout).strip()[-400:]}")
    return path, True


def git_info(directory: Path | str, timeout: float = 5.0) -> GitInfo | None:
    try:
        cp = subprocess.run(
            ["git", "-C", str(directory), "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=normal"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if cp.returncode != 0:
        return None
    branch, upstream, ahead, behind, files, oid = "?", None, 0, 0, [], ""
    # -z: each entry ends in NUL and no path is C-quoted (TD-869); a rename's source is the next field
    fields, i = cp.stdout.split("\0"), 0
    while i < len(fields):
        line = fields[i]
        i += 1
        if line.startswith("# branch.oid "):
            oid = line.split(" ", 2)[2]
            oid = "" if oid == "(initial)" else oid
        elif line.startswith("# branch.head "):
            branch = line.split(" ", 2)[2]
        elif line.startswith("# branch.upstream "):
            upstream = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            parts = line.split()
            ahead, behind = int(parts[2].lstrip("+")), int(parts[3].lstrip("-"))
        elif line.startswith("1 "):
            # 1 XY sub mH mI mW hH hI path   — the path may contain spaces
            parts = line.split(" ", 8)
            files.append(f"{parts[1].replace('.', '')} {parts[8]}")
        elif line.startswith("2 "):
            # 2 XY sub mH mI mW hH hI Xscore path, then origPath as a field of its own
            parts = line.split(" ", 9)
            files.append(f"{parts[1].replace('.', '')} {parts[9]}")
            i += 1
        elif line.startswith("? "):
            files.append(f"?? {line[2:]}")
        elif line.startswith("u "):
            # u XY sub m1 m2 m3 mW h1 h2 h3 path
            files.append(f"UU {line.split(' ', 10)[10]}")
    unpushed, against = _unpushed(directory, branch, upstream, ahead, timeout)
    return GitInfo(
        branch=branch,
        dirty=len(files),
        ahead=ahead,
        behind=behind,
        upstream=upstream,
        files=files[:20],
        unpushed=unpushed,
        pushed_against=against,
        oid=oid,
    )


def changed_files(directory: Path | str, base_ref: str | None, limit: int, timeout: float = 5.0) -> list[dict] | None:
    """The paths the work in `directory` has changed against its base, `{path, at, sha}` newest first, a
    path once, the newest `limit` (design §4.2 *The record's `files`*, TD-538): `git diff --name-only`
    from `merge-base HEAD <base_ref>` and the untracked paths — the tree alone where `base_ref` is None
    (no origin) or shares no merge base with `HEAD` — each path absolute. One the porcelain holds is the
    file's own: its modification time and no `sha` (a deleted one the newest commit's time, else the
    read's); any other is the newest of the branch's commits that touched it, from one `git log
    --name-only`. None when a read fails, so the record keeps what it had. Computed on each read and never
    kept; nothing is fetched."""
    top = toplevel(directory, timeout=timeout)
    if not top:
        return None
    status = _git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all", timeout=timeout)
    if status is None:
        return None
    dirty: list[str] = []
    fields = status.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        dirty.append(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            i += 1  # a rename's or copy's source follows its path, on either side: no longer in the tree
    paths = dict.fromkeys(dirty)
    commits: dict[str, tuple[str, int]] = {}  # path → the newest commit since the base that touched it
    # no merge base (an unborn HEAD, unrelated histories) reads as no origin: the tree alone
    base = (_git(top, "merge-base", "HEAD", base_ref, timeout=timeout) or "").strip() if base_ref else ""
    if base:
        diff = _git(top, "diff", "--name-only", "-z", base, timeout=timeout)
        log_out = _git(top, "log", "--name-only", "-z", "--format=%x01%H %ct", f"{base}..HEAD", timeout=timeout)
        if diff is None or log_out is None:
            return None
        paths.update(dict.fromkeys(p for p in diff.split("\0") if p))
        for chunk in log_out.split("\x01")[1:]:  # `<sha> <time>\0\n<path>\0…`, newest first as git gives them
            head, _, names = chunk.partition("\0")
            sha, _, ct = head.partition(" ")
            for name in names.removeprefix("\n").split("\0"):
                if name and name not in commits and ct.isdigit():
                    commits[name] = (sha, int(ct))
    now = datetime.now(UTC).timestamp()
    dirty_set = set(dirty)
    out: list[tuple[float, dict]] = []
    for rel in paths:
        path = os.path.join(top, rel)
        if rel in dirty_set:
            try:
                at = os.stat(path).st_mtime
            except OSError:  # deleted: the commit's time, or the read's
                at = commits[rel][1] if rel in commits else now
            out.append((at, {"path": path, "at": _iso(at)}))
        elif rel in commits:
            sha, ct = commits[rel]
            out.append((ct, {"path": path, "at": _iso(ct), "sha": sha}))
    out.sort(key=lambda t: -t[0])
    return [f for _, f in out[:limit]]


GIT_PICK_COMMITS = 10  # the Git card's pick: the newest commits on HEAD's first-parent line (§4.2)
GIT_PICK_SESSION = 100  # and Session's paths, *n more* past it
GIT_PICK_TREE = 20  # Working tree: the porcelain's lines, as `GitInfo.files` keeps them


class GitPickError(ValueError):
    """A `git_files` pick that cannot be answered, in words the card shows (§4.2 *The Git card's pick*)."""


def pick_files(directory: Path | str, base_ref: str | None, pick: str, timeout: float = 5.0) -> dict[str, Any]:
    """The Git card's pick (design §4.2 *The Git card's pick*, TD-856): `commits`, the newest ten on
    `HEAD`'s first-parent line, each `{ref, sha, subject, at, author}`, `ref` git's own `HEAD` … `HEAD~9`;
    and `files` by `pick`, each `{code, path}` repo-relative with `gone: true` on one not in the tree now —
    `tree` the porcelain's lines (at most twenty), a sha of the ten the paths that commit changed against
    its first parent (the empty tree for a root commit), `session` `changed_files` at a hundred with each
    path's code (the porcelain's for one it holds, else its letter against the base) and `more`, the count
    past it. A sha outside the ten and any other pick raise `GitPickError`. Runs git and stat and nothing
    else; nothing is kept."""
    top = toplevel(directory, timeout=timeout)
    if not top:
        raise GitPickError("not a git directory")
    log_out = _git(
        top, "log", "--first-parent", "-z", f"-n{GIT_PICK_COMMITS}", "--format=%H%x01%s%x01%ct%x01%an", timeout=timeout
    )
    if log_out is None and _git(top, "rev-parse", "--verify", "-q", "HEAD", timeout=timeout) is not None:
        raise GitPickError("git log failed")
    commits = []
    for i, rec in enumerate(r for r in (log_out or "").split("\0") if r.strip()):
        sha, subject, ct, author = (rec.lstrip("\n").split("\x01") + ["", "", ""])[:4]
        at = _iso(int(ct)) if ct.isdigit() else ""
        commits.append(
            {"ref": "HEAD" if i == 0 else f"HEAD~{i}", "sha": sha, "subject": subject, "at": at, "author": author}
        )
    out: dict[str, Any] = {"commits": commits}
    if pick == "tree":  # `GitInfo.files`' lines, read with -z so a path git would quote comes whole
        status = _git(top, "status", "--porcelain=v1", "-z", "--untracked-files=normal", timeout=timeout)
        if status is None:
            raise GitPickError("git status failed")
        files = [{"code": code, "path": path} for path, code in _porcelain(status).items()][:GIT_PICK_TREE]
    elif pick == "session":
        files, out["more"] = _session_files(top, base_ref, timeout)
    elif isinstance(pick, str) and pick and any(c["sha"] == pick for c in commits):
        files = _commit_files(top, pick, timeout)
    elif isinstance(pick, str) and re.fullmatch(r"[0-9a-f]{4,64}", pick):
        raise GitPickError("not among the last ten commits")
    else:
        raise GitPickError(f"pick is tree, session or a sha of the last ten commits, not {pick!r}")
    for f in files:
        if not os.path.lexists(os.path.join(top, f["path"])):
            f["gone"] = True
    out["files"] = files
    return out


def _name_status(raw: str) -> list[dict[str, Any]]:
    """`git diff --name-status -z`'s fields as `{code, path}`, a rename or copy by its new path."""
    fields, files, i = raw.split("\0"), [], 0
    while i < len(fields):
        status = fields[i]
        if not status:
            i += 1
            continue
        if status[0] in "RC":
            files.append({"code": status[0], "path": fields[i + 2] if i + 2 < len(fields) else ""})
            i += 3
        else:
            files.append({"code": status[0], "path": fields[i + 1] if i + 1 < len(fields) else ""})
            i += 2
    return [f for f in files if f["path"]]


def _porcelain(status: str) -> dict[str, str]:
    """`git status --porcelain=v1 -z`'s paths in its order, each with its code as `GitInfo.files` writes it
    (the blanks dropped: `M`, `MD`, `??`), a rename by its new path."""
    codes: dict[str, str] = {}
    fields, i = status.split("\0"), 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        codes[entry[3:]] = entry[:2].replace(" ", "")
        if "R" in entry[:2] or "C" in entry[:2]:
            i += 1  # the source follows the path: no longer in the tree
    return codes


def _commit_files(top: str, sha: str, timeout: float) -> list[dict[str, Any]]:
    parents = _git(top, "rev-list", "--parents", "-n1", sha, timeout=timeout)
    if parents is None:
        raise GitPickError(f"could not read {sha[:7]}")
    if len(parents.split()) > 1:
        base = f"{sha}^1"
    else:  # a root commit: against the empty tree
        base = (_git(top, "hash-object", "-t", "tree", "/dev/null", timeout=timeout) or "").strip()
    raw = _git(top, "diff", "--name-status", "-M", "-z", base, sha, timeout=timeout) if base else None
    if raw is None:
        raise GitPickError(f"git diff failed on {sha[:7]}")
    return _name_status(raw)


def _session_files(top: str, base_ref: str | None, timeout: float) -> tuple[list[dict[str, Any]], int]:
    every = changed_files(top, base_ref, limit=1 << 30, timeout=timeout)
    if every is None:
        raise GitPickError("git read failed")
    codes = _porcelain(_git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all", timeout=timeout) or "")
    base = (_git(top, "merge-base", "HEAD", base_ref, timeout=timeout) or "").strip() if base_ref else ""
    if base and (raw := _git(top, "diff", "--name-status", "-z", base, timeout=timeout)) is not None:
        for f in _name_status(raw):
            codes.setdefault(f["path"], f["code"])
    files = []
    for f in every[:GIT_PICK_SESSION]:
        rel = os.path.relpath(f["path"], top)
        files.append({"code": codes.get(rel, "M"), "path": rel})
    return files, max(0, len(every) - GIT_PICK_SESSION)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


UNKNOWN = "git state unknown"


def work_left(git: Any) -> str | None:
    """Why a checkout is not *clean and pushed*, from a record's `git` fields, or None when it is
    (design §6 rule 2, §4.2 *One measure*). **Unknown is work left**: no fields yet, or a count
    that is not a number, reads `UNKNOWN` — known, not merely absent. The one test the tick's
    wanted restart, a person's Restart and `ao team stop --close` share (TD-250), so the three
    cannot drift; `unpushed` is the host agent's one measure (TD-080) and nothing is run here."""
    if not isinstance(git, dict) or not all(
        isinstance(git.get(k), int) and not isinstance(git.get(k), bool) for k in ("dirty", "unpushed")
    ):
        return UNKNOWN
    if git["dirty"]:
        return f"{git['dirty']} uncommitted"
    if git["unpushed"]:
        return f"{git['unpushed']} unpushed (vs {git.get('pushed_against') or 'its remote'})"
    return None


def _git(directory: Path | str, *args: str, timeout: float) -> str | None:
    """One read-only git command, or None when it could not be run or failed. The host agent never
    fetches for any of this: it reads the refs it has (design §4.2)."""
    try:
        cp = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return cp.stdout if cp.returncode == 0 else None


def _unpushed(directory: Path | str, branch: str, upstream: str | None, ahead: int, timeout: float) -> tuple[int, str]:
    """How many commits exist **only on this machine**, and what that was measured against (design
    §4.2 *one measure*, TD-080). The first rule that applies answers:

    1. the branch has its own remote-tracking ref, `origin/<branch>` — count against it, whatever
       the upstream is, because *ahead of `origin/main`* is *unmerged* and that is a different
       question (a launch branch tracking `origin/main` and pushed to its own ref read *308
       unpushed* for ever, TD-080);
    2. no such ref but an upstream — the commits ahead of it whose patch it does not hold, and 0
       when it holds the branch's content whole: a branch cut from `origin/main` and squash-merged,
       its remote branch deleted, is pushed (TD-701);
    3. neither — a detached `HEAD`, or a branch never pushed — the commits on no remote-tracking
       branch at all, which is 0 exactly when `HEAD` is contained in one (a worker that merged and
       sits on a detached `origin/main`) and otherwise **not pushed**, which is the stranded work
       the check exists for.

    A read that cannot be made leaves the count at the porcelain's, never at a confident 0."""
    if branch and branch != "(detached)":
        ref = f"refs/remotes/origin/{branch}"
        if _git(directory, "rev-parse", "--verify", "-q", ref, timeout=timeout) is not None:
            out = _git(directory, "rev-list", "--count", f"origin/{branch}..HEAD", timeout=timeout)
            if out is not None and out.strip().isdigit():
                return int(out.strip()), f"origin/{branch}"
    if upstream:
        return _not_in_upstream(directory, upstream, ahead, timeout), upstream
    out = _git(directory, "rev-list", "--count", "HEAD", "--not", "--remotes", timeout=timeout)
    if out is not None and out.strip().isdigit():
        return int(out.strip()), "remote branches"
    return ahead, ""


def _not_in_upstream(directory: Path | str, upstream: str, ahead: int, timeout: float) -> int:
    """Rule 2's count (TD-701): of the commits ahead of `upstream`, those whose patch it does not
    hold — a squash merge lands one under another sha. A squash of several commits matches no
    single patch, so when some remain, the branch is 0 if merging `HEAD` into the upstream would
    leave its tree as it is; a commit of its own on top of such a squash leaves the patch count,
    which is never 0 then. A read that cannot be made leaves the porcelain's *ahead*."""
    if not ahead:
        return 0
    out = _git(directory, "rev-list", "--count", "--cherry-pick", "--right-only", f"{upstream}...HEAD", timeout=timeout)
    if out is None or not out.strip().isdigit():
        return ahead
    left = int(out.strip())
    if left:
        merged = _git(directory, "merge-tree", "--write-tree", upstream, "HEAD", timeout=timeout)
        tree = _git(directory, "rev-parse", f"{upstream}^{{tree}}", timeout=timeout)
        if merged and tree and merged.split("\n", 1)[0].strip() == tree.strip():
            return 0
    return left


# -- a close's reap of the worktree it made (design §4.1 *A close reaps the worktree it made*, TD-979) ----------
# The tests are dev-cadence's `reap_worktrees.sh`'s *clean*, *unlocked* and *nested*, ported here because that
# script is synced and has no one-worktree mode; *idle* reads ShiftLead's own records, so the caller gives it.

REAP_WITHIN = 60.0  # the deadline the reap reads between steps: no step starts past it
REAP_STEP = 20.0  # each git and script call's own timeout; `--dehydrate` never starts past REAP_WITHIN − REAP_STEP
# ignored directories rebuilt by a run or a sync, so removing them loses nothing: a knowing departure from the
# reaper, which exempts only `__pycache__` — every worktree a worker ran its tests or linter in holds the rest
DISPOSABLE_IGNORED = (
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".pdm-build", ".pdm-python", "*.egg-info", ".venv",
)  # fmt: skip
NESTED_REPOS = "docs/nested-repos.txt"
TIMED_OUT = "timed out"
NOT_WEIGHED = "could not be weighed"


def main_checkout(directory: Path | str, timeout: float = REAP_STEP) -> Path:
    """The main checkout of the repo `directory` is in, as `worktree_path` resolves it, the read bounded."""
    return worktree_path(Path(directory), "x", timeout).parent.parent.parent


def _hydrate_script(repo: Path) -> Path | None:
    """The main checkout's `hydrate_worktree.sh` when it is there and executable, as the reaper runs it."""
    script = repo / HYDRATE
    return script if script.is_file() and os.access(script, os.X_OK) else None


def _run(argv: list[str], timeout: float, cwd: Path | str | None = None) -> subprocess.CompletedProcess | None:
    """One call bounded by `timeout`, or None when it could not be run or ran out."""
    try:
        env = {**os.environ, "LC_ALL": "C"}  # git's refusals are matched in English
        return subprocess.run(argv, capture_output=True, text=True, timeout=max(timeout, 0.1), cwd=cwd, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _nested_depth(repo: Path) -> int:
    """How deep a nested worktree may sit (the reaper's and hydrate's `nested_depth`): the deepest path in
    `docs/nested-repos.txt`, every word but the last, never less than 3."""
    deepest = 3
    try:
        lines = (repo / NESTED_REPOS).read_text(encoding="utf-8").splitlines()
    except OSError:
        return deepest
    for line in lines:
        words = line.split("#", 1)[0].split()
        if len(words) >= 2:
            p = " ".join(words[:-1]).removeprefix("./").rstrip("/")
            deepest = max(deepest, len(p.split("/")))
    return deepest


def _disposable(rel: str, wt: Path) -> bool:
    """Whether an ignored path lies under one of `DISPOSABLE_IGNORED`'s derived directories (a `.venv` only
    when it is a real directory, a symlinked one being exempt as a symlink)."""
    parts = rel.split("/")
    for i, part in enumerate(parts):
        if part == ".venv":
            if (wt / "/".join(parts[: i + 1])).is_dir():
                return True
        elif any(re.fullmatch(p.replace(".", r"\.").replace("*", ".*"), part) for p in DISPOSABLE_IGNORED):
            return True
    return False


def ignored_blockers(wt: Path, repo: Path, timeout: float = REAP_STEP) -> list[str] | None:
    """The ignored paths in worktree `wt` that removing it would destroy (the reaper's `ignored_blockers`), or
    None when git could not say. Every ignored path blocks except a symlink, a `.claude/settings.local.json`
    the hydrate script calls disposable, a nested worktree its `--check` judges, and a path under
    `DISPOSABLE_IGNORED`; a nested `.git` directory always blocks."""
    cp = _run(["git", "-C", str(wt), "status", "--porcelain", "-z", "--ignored", "--untracked-files=all"], timeout)
    if cp is None or cp.returncode != 0:
        return None
    hydrate = _hydrate_script(repo)
    depth = _nested_depth(repo)
    out = []
    for entry in cp.stdout.split("\0"):
        if not entry.startswith("!! "):
            continue
        p = entry[3:]
        rel = p.rstrip("/")
        if (wt / rel).is_symlink():
            continue  # removing a link never touches its target
        if (wt / rel / ".git").is_dir():
            out.append(p)  # a nested clone, with whatever it holds unpushed
            continue
        if _disposable(rel, wt):
            continue
        if rel == ".claude/settings.local.json" and hydrate:
            sp = _run([str(hydrate), "--settings-disposable", str(wt)], timeout)
            if sp is not None and sp.returncode == 0:
                continue
        nested = p.endswith("/") and (wt / rel / ".git").is_file() and hydrate
        if nested and "node_modules" not in rel.split("/") and rel.count("/") <= depth - 1:
            continue  # a nested worktree: the hydrate script's `--check` judges it
        out.append(p)
    return out


def _dirty(wt: Path, timeout: float) -> int | None:
    """The tracked and untracked files `git_info` counts as `dirty`, read in one `git status` and none of
    `git_info`'s follow-up reads, so the test stays inside one step's allowance; None when git could not say."""
    cp = _run(["git", "-C", str(wt), "status", "--porcelain=v2", "-z", "--untracked-files=normal"], timeout)
    if cp is None or cp.returncode != 0:
        return None
    n, fields, i = 0, cp.stdout.split("\0"), 0
    while i < len(fields):
        line = fields[i]
        i += 1
        if line[:2] in ("1 ", "2 ", "? ", "u "):
            n += 1
            i += line.startswith("2 ")  # a rename's source is the next field
    return n


def _locked(repo: Path, wt: Path, timeout: float) -> bool | None:
    """`git worktree list --porcelain`'s `locked` for `wt`, or None when it could not be read."""
    out = _git(repo, "worktree", "list", "--porcelain", timeout=timeout)
    if out is None:
        return None
    here = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            here = Path(line[len("worktree ") :]).resolve() == wt.resolve()
        elif here and (line == "locked" or line.startswith("locked ")):
            return True
    return False


def worktree_holds(wt: Path, repo: Path, deadline: float, *, idle=None) -> str | None:
    """Why worktree `wt` of `repo` must be kept, or None when removing it loses nothing: the reaper's *clean*
    (tracked, untracked, then ignored one by one), the caller's *idle* (a callable answering a why or None),
    *unlocked* and *nested*, each read fresh, each started only before `deadline` (`time.monotonic()`)."""

    def left() -> float:
        return min(REAP_STEP, deadline - time.monotonic())

    if left() <= 0:
        return TIMED_OUT
    dirty = _dirty(wt, left())
    if dirty is None:
        return UNKNOWN
    if dirty:
        return f"{dirty} uncommitted"
    if left() <= 0:
        return TIMED_OUT
    blockers = ignored_blockers(wt, repo, left())
    if blockers is None:
        return UNKNOWN
    if blockers:
        more = f" and {len(blockers) - 1} more" if len(blockers) > 1 else ""
        return f"ignored: {blockers[0]}{more}"
    if idle is not None:
        if left() <= 0:
            return TIMED_OUT
        why = idle()
        if why:
            return why
    if left() <= 0:
        return TIMED_OUT
    locked = _locked(repo, wt, left())
    if locked is None:
        return UNKNOWN
    if locked:
        return "locked"
    hydrate = _hydrate_script(repo)
    if hydrate:
        if left() <= 0:
            return TIMED_OUT
        cp = _run([str(hydrate), "--check", "--quiet", str(wt)], left())
        if cp is None:
            return TIMED_OUT
        if cp.returncode != 0:
            return "nested work unsaved"
    return None


def _branch_of(wt: Path, timeout: float) -> tuple[bool, str | None]:
    """(read, branch) — the branch checked out in `wt`, None when HEAD is detached; `read` False when git failed."""
    cp = _run(["git", "-C", str(wt), "symbolic-ref", "-q", "--short", "HEAD"], timeout)
    if cp is None or cp.returncode not in (0, 1):
        return False, None
    return True, (cp.stdout.strip() or None) if cp.returncode == 0 else None


def _commits(n: int) -> str:
    return f"{n} commit{'s' if n != 1 else ''} never on origin"


def weigh_branches(
    repo: Path, branches: list[str | None], within: float = REAP_STEP
) -> tuple[list[str], dict[str, str]]:
    """Delete each of `branches` whose tip origin has held (design §4.1 *The branches: was it ever on origin*):
    `git branch -d`'s test widened to every `origin` ref and every value of `origin/<b>`'s reflog. Answers
    `(deleted, kept)`, `kept` a map of branch to why. The default branch, a missing branch and a repeat are
    skipped, named in neither; the whole step is bounded by `within`, and nothing raises."""
    end = time.monotonic() + within
    names = list(dict.fromkeys(b for b in branches if b))
    deleted: list[str] = []
    kept: dict[str, str] = {}

    def left() -> float:
        return end - time.monotonic()

    def git(*args: str) -> subprocess.CompletedProcess | None:
        return _run(["git", "-C", str(repo), *args], left()) if left() > 0 else None

    remotes = git("remote")
    if remotes is None or remotes.returncode != 0:
        return [], dict.fromkeys(names, NOT_WEIGHED)
    if "origin" not in remotes.stdout.split():
        return [], dict.fromkeys(names, "no origin")
    head = git("symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    if head is None or head.returncode not in (0, 1):
        return [], dict.fromkeys(names, NOT_WEIGHED)
    if head.returncode != 0 or not head.stdout.strip():
        return [], dict.fromkeys(names, "no origin/HEAD")
    default = head.stdout.strip().removeprefix("refs/remotes/origin/")
    for b in names:
        if b == default:
            continue
        there = git("show-ref", "--verify", "--quiet", f"refs/heads/{b}")
        if there is None or there.returncode not in (0, 1):
            kept[b] = NOT_WEIGHED
            continue
        if there.returncode == 1:
            continue  # nothing to delete
        held: list[str] = []
        logged = git("reflog", "exists", f"refs/remotes/origin/{b}")
        if logged is None:
            kept[b] = NOT_WEIGHED
            continue
        if logged.returncode == 0:
            values = git("reflog", "show", "--format=%H", f"refs/remotes/origin/{b}")
            if values is None or values.returncode != 0:
                kept[b] = NOT_WEIGHED
                continue
            held = sorted({v for v in values.stdout.split() if v})
        never = git("rev-list", f"refs/heads/{b}", "--not", "--remotes=origin", *held)
        if never is None or never.returncode != 0:
            kept[b] = NOT_WEIGHED
            continue
        n = len(never.stdout.split())
        if n:
            kept[b] = _commits(n)
            continue
        cp = git("branch", "-D", b)
        if cp is None:
            kept[b] = NOT_WEIGHED
        elif cp.returncode == 0:
            deleted.append(b)
        else:
            where = re.search(r"(?:checked out at|used by worktree at) '([^']+)'", cp.stderr)
            kept[b] = f"checked out in {where.group(1)}" if where else NOT_WEIGHED
    return deleted, kept


def reweigh_gone(
    repo: Path, wt: Path | str, launch: str | None, kept: dict[str, str] | None, reaped: bool
) -> tuple[list[str], dict[str, str]] | None:
    """`ao close`'s retry on a closed record whose worktree directory is gone (design §4.1): a reaped one weighs
    again the branches `kept` names; one never reaped (a directory removed by hand) reads its checked-out branch
    from `git worktree list --porcelain`'s stale entry at `wt` (none when it has none or reads `detached`), runs
    `git worktree prune` and weighs that branch and `launch`. Answers `(deleted, kept)` as `weigh_branches`
    does, or None when the registration could not be read or pruned, so nothing is stamped; never raises."""
    if reaped:
        return weigh_branches(repo, list(kept or {}))
    cp = _run(["git", "-C", str(repo), "worktree", "list", "--porcelain"], REAP_STEP)
    if cp is None or cp.returncode != 0:
        return None
    want = os.path.realpath(wt)
    branch = None
    for block in cp.stdout.split("\n\n"):
        lines = block.splitlines()
        if lines and lines[0].startswith("worktree ") and os.path.realpath(lines[0][9:]) == want:
            branch = next((x[7:].removeprefix("refs/heads/") for x in lines if x.startswith("branch ")), None)
            break
    pruned = _run(["git", "-C", str(repo), "worktree", "prune"], REAP_STEP)  # frees the branch and the path
    if pruned is None or pruned.returncode != 0:
        return None
    return weigh_branches(repo, [branch, launch])


def rehydrate(repo: Path, wt: Path) -> None:
    """Hydrate `wt` again after a `--dehydrate` that was not followed by a remove; exempt from the deadline."""
    hydrate = _hydrate_script(repo)
    if hydrate and wt.is_dir():
        _run([str(hydrate), "--quiet", str(wt)], REAP_STEP)


def reap_worktree(
    wt: Path | str, launch: str | None, *, deadline: float | None = None, idle=None, on_reaping=None
) -> dict[str, Any]:
    """Remove worktree `wt` when nothing in it would be lost, then weigh its branches (design §4.1 *A close
    reaps the worktree it made*). `launch` is the launch branch `<name>`; `idle` the caller's *idle* test;
    `on_reaping(branch)` is called before `--dehydrate`, so the caller stamps `worktree_reaping`. Answers
    `{"kept": why}` or `{"reaped": True, "branches_deleted": [...], "branch_kept": {...}}`; never raises."""
    wt = Path(wt)
    deadline = time.monotonic() + REAP_WITHIN if deadline is None else deadline
    try:
        repo = main_checkout(wt)
    except WorktreeError:
        return {"kept": UNKNOWN}
    if time.monotonic() >= deadline:
        return {"kept": TIMED_OUT}
    read, branch = _branch_of(wt, min(REAP_STEP, deadline - time.monotonic()))
    if not read:
        return {"kept": UNKNOWN}
    why = worktree_holds(wt, repo, deadline, idle=idle)
    if why:
        return {"kept": why}
    hydrate = _hydrate_script(repo)
    if time.monotonic() > (deadline - REAP_STEP if hydrate else deadline):
        return {"kept": TIMED_OUT}  # no step starts past the deadline, and `--dehydrate` none past its own
    if on_reaping is not None:
        on_reaping(branch)
    if hydrate:
        cp = _run([str(hydrate), "--dehydrate", "--quiet", str(wt)], REAP_STEP)
        if cp is None or cp.returncode != 0:
            rehydrate(repo, wt)
            return {"kept": "nested work unsaved"}
    cp = _run(["git", "-C", str(repo), "worktree", "remove", str(wt)], REAP_STEP)
    if cp is None or cp.returncode != 0:
        rehydrate(repo, wt)
        said = (cp.stderr or cp.stdout).strip().splitlines() if cp is not None else []
        return {"kept": said[-1].removeprefix("fatal: ") if said else TIMED_OUT}
    deleted, kept = weigh_branches(repo, [branch, launch])
    return {"reaped": True, "branches_deleted": deleted, "branch_kept": kept}
