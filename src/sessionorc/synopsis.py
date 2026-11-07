"""A design's synopsis, as the repo reading answers it (design §4.5 screen 6 *A design links its synopsis*, TD-1527,
built by TD-1536).

A design entry's synopsis is the file `docs/synopses/TD-<design>.md` in its repo. Whether it is there is read in the
host agent's repo reading, beside `prs.open`, never at render time: one `git ls-tree --name-only <sha>
docs/synopses/` per commit — `origin/<default>` resolved to its commit, and each open design PR's `head` — answers
every entry at that commit and is kept per commit, so a commit is asked once; the checkout's `git worktree list
--porcelain`, read once per reading, says which worktree holds a PR's branch, where the editor's copy lies before the
merge. `entry` turns one entry's design link into its `synopsis`, `{sha, exists, editor_path, branch, path,
root}`."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DIR = "docs/synopses"
TIMEOUT = 10.0


def path_of(tid: str) -> str:
    """The synopsis of the design entry `TD-n`, relative to its repo's root."""
    return f"{DIR}/{tid}.md"


def _git(root: str, *args: str, timeout: float = TIMEOUT) -> str | None:
    """A git read in the checkout at `root`: its stdout, or None where git failed or could not be run."""
    try:
        cp = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return cp.stdout if cp.returncode == 0 else None


def worktrees(root: str) -> dict[str, str]:
    """`{branch: worktree path}` from the checkout's `git worktree list --porcelain`: a worktree on a branch alone, a
    detached one holds none; {} where git cannot say."""
    out: dict[str, str] = {}
    at = ""
    for line in (_git(root, "worktree", "list", "--porcelain") or "").splitlines():
        if line.startswith("worktree "):
            at = line[len("worktree ") :]
        elif line.startswith("branch refs/heads/") and at:
            out.setdefault(line[len("branch refs/heads/") :], at)
    return out


def present(root: str, sha: str) -> list[str] | None:
    """The synopses at commit `sha`: `git ls-tree --name-only <sha> docs/synopses/`, the paths it names; None where
    the commit is not in the checkout's objects (a PR pushed from elsewhere this host has not fetched)."""
    got = _git(root, "ls-tree", "--name-only", sha, f"{DIR}/")
    return None if got is None else [p for p in got.splitlines() if p]


def reading(
    root: str, prs: Mapping[str, Any] | None, branch: str | None, old: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The repo's synopsis reading: `{default, default_sha, present, worktrees}`. `present` maps each commit asked —
    `origin/<branch>` resolved, and the `head` of each open design PR (`design_title`) not from a fork — to the
    synopsis paths it holds, taken from `old` where that commit was asked before; a commit not in the objects is not
    kept, so a later fetch brings it. `worktrees` is `worktrees(root)`."""
    from .queue import DESIGN_TITLE  # the open-design-PR title rule is TD-1531's, in one place

    branch = branch or str((old or {}).get("default") or "") or "main"
    kept: Mapping[str, Any] = (old or {}).get("present") or {}
    shas: list[str] = []
    default_sha = (_git(root, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}^{{commit}}") or "").strip()
    if default_sha:
        shas.append(default_sha)
    for p in (prs or {}).get("open") or () if isinstance(prs, Mapping) else ():
        if isinstance(p, Mapping) and not p.get("fork") and p.get("head") and DESIGN_TITLE.match(str(p.get("title"))):
            shas.append(str(p["head"]))
    found: dict[str, list[str]] = {}
    for sha in shas:
        if sha in found:
            continue
        got = list(kept[sha]) if isinstance(kept.get(sha), list) else present(root, sha)
        if got is not None:
            found[sha] = got
    return {"default": branch, "default_sha": default_sha, "present": found, "worktrees": worktrees(root)}


def entry(tid: str, pr: Mapping[str, Any] | None, syn: Mapping[str, Any] | None, root: str) -> dict[str, Any] | None:
    """The `synopsis` of the design entry `tid` whose design link is `pr` (its open design PR's `prs.open` row) or,
    with `pr` None, its `Design PR:` section's last number (merged): `{sha, exists, editor_path, branch, path, root}`.
    Before the merge the copy is the PR's `head`, the editor's the file in the worktree on the PR's `branch`; after
    it `origin/<default>`'s commit, the editor's the file in the main checkout. `exists` is whether `present` holds
    the file at that commit (a fork's PR, or a head not in the objects, reads absent); `editor_path` the file on this
    host's disk, else None. None where the repo has no synopsis reading."""
    if not isinstance(syn, Mapping):
        return None
    rel = path_of(tid)
    if pr is not None:
        sha, branch = str(pr.get("head") or ""), str(pr.get("branch") or "")
        where = None if pr.get("fork") else (syn.get("worktrees") or {}).get(branch)
    else:
        sha, branch, where = str(syn.get("default_sha") or ""), str(syn.get("default") or ""), root
    files = (syn.get("present") or {}).get(sha) if sha else None
    exists = bool(not (pr or {}).get("fork") and isinstance(files, list) and rel in files)
    on_disk = str(Path(where) / rel) if where and exists and (Path(where) / rel).is_file() else None
    return {"sha": sha, "exists": exists, "editor_path": on_disk, "branch": branch, "path": rel, "root": root}
