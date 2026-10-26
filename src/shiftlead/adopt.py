"""dev-cadence's adoption as `ao repo add` offers it and opens it (design §4.7 **`ao repo add`**, §5 *The
seams*; TD-1010): run in the person's own shell on the home, never by the host agent. dev-cadence's adopt
(`<dev-cadence>/sync.sh`, until dev-cadence TD-129's launcher) runs in a **scratch clone** of the repo
under `$TMPDIR` — never a worktree, whose common directory is the person's checkout, where `sync.sh`
writes per-clone settings — and a temp root, so `sync.sh` registers nothing on dev-cadence's own roster
(dev-cadence TD-068). The offer lists what it wrote; the adopt commits it on `cadence-adopt`, pushes that
branch and opens it as a PR, never touching the default branch. The clone is removed either way."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sessionorc import cadence, reports, sync, workorders
from sessionorc.seams import ADOPT_BRANCH

GIT_TIMEOUT = 120.0  # a clone or a fetch of the person's repo
SYNC_TIMEOUT = 300.0  # dev-cadence's adopt, bounded at birth
PR_URL = re.compile(r"https://\S+/pull/(\d+)")


class AdoptError(Exception):
    """The adopt could not run or was refused, in words for the person."""


def dev_cadence(roster: list[str], root: Path) -> Path | None:
    """The roster's dev-cadence checkout — the first whose root holds `sync.sh` and `files/` — or None;
    never `root` itself."""
    for line in roster:
        here = Path(line).expanduser().resolve()
        if here != root and cadence.is_source(here):
            return here
    return None


def _run(argv: list[str], cwd: Path | None, timeout: float = GIT_TIMEOUT) -> str:
    """One call, bounded; its stdout, or AdoptError naming the command and the tail of what it said."""
    try:
        cp = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AdoptError(f"{' '.join(argv[:3])} ran past {timeout:.0f}s") from None
    except OSError as e:
        raise AdoptError(f"{argv[0]}: {e.strerror or e}") from None
    if cp.returncode != 0:
        said = (cp.stderr or cp.stdout).strip().splitlines()[-3:]
        raise AdoptError(f"{' '.join(argv[:3])} failed: {' / '.join(said) or f'exit {cp.returncode}'}")
    return cp.stdout


def origin(root: Path) -> str:
    """The checkout's `origin` URL, or AdoptError: the adopt reads `origin/<default>`."""
    with contextlib.suppress(AdoptError):
        # as configured, not as an `insteadOf` rewrites it: the clone's `origin` keeps the rewrite
        if url := _run(["git", "-C", str(root), "config", "--get", "remote.origin.url"], None).strip():
            return url
    raise AdoptError(f"{root} has no origin: ao repo add adopts dev-cadence on origin's default branch")


def temp_root() -> str | None:
    """Where the scratch clone is made: `$CADENCE_TEMP_ROOTS`'s first root where it is set, since `sync.sh`
    then counts those alone as temporary, else None — `$TMPDIR`, which it counts (its TD-068)."""
    return next((r for r in os.environ.get("CADENCE_TEMP_ROOTS", "").split(":") if r), None)


@contextlib.contextmanager
def scratch_clone(root: Path) -> Iterator[tuple[Path, str]]:
    """A `--shared` clone of `root` under `$TMPDIR`, its `origin` the checkout's own, fetched and
    detached at `origin/<default>`; yields `(clone, default)` and removes it after, whatever happened."""
    url, default = origin(root), workorders.default_branch(root)
    tmp = Path(tempfile.mkdtemp(prefix="ao-adopt-", dir=temp_root()))  # a dev-cadence temp root (its TD-068)
    try:
        clone = tmp / root.name
        _run(["git", "clone", "-q", "--shared", "--no-checkout", str(root), str(clone)], None)
        _run(["git", "remote", "set-url", "origin", url], clone)
        _run(["git", "fetch", "-q", "origin"], clone)
        _run(["git", "checkout", "-q", "--detach", f"origin/{default}"], clone)
        yield clone, default
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _sync(dc: Path, clone: Path) -> list[str]:
    """dev-cadence's adopt in the clone; the paths it wrote, as `git status --porcelain -z` names them (a
    rename's new path alone)."""
    _run([str(dc / "sync.sh"), str(clone)], clone, SYNC_TIMEOUT)
    records = iter(_run(["git", "status", "--porcelain", "-z", "--untracked-files=all"], clone).split("\0"))
    out: list[str] = []
    for rec in records:
        if len(rec) > 3:
            out.append(rec[3:])
            if "R" in rec[:2] or "C" in rec[:2]:
                next(records, None)  # the path it was renamed or copied from
    return out


def _identity(root: Path) -> list[str]:
    """`-c` options carrying the checkout's own `user.name` and `user.email`, which a clone does not inherit
    where they are set in the checkout's config alone."""
    out: list[str] = []
    for key in ("user.name", "user.email"):
        with contextlib.suppress(AdoptError):
            if value := _run(["git", "-C", str(root), "config", "--get", key], None).strip():
                out += ["-c", f"{key}={value}"]
    return out


def open_pr(clone: Path, gh: str) -> dict[str, Any] | None:
    """The open PR whose head is `cadence-adopt`, `{number, url}`, or None."""
    out = _run([gh, "pr", "list", "--head", ADOPT_BRANCH, "--state", "open", "--json", "number,url"], clone)
    try:
        prs = json.loads(out or "[]")
    except json.JSONDecodeError:
        raise AdoptError("gh pr list printed something that is not JSON") from None
    return next((p for p in prs if isinstance(p, dict) and isinstance(p.get("number"), int)), None)


def offer(root: Path, dc: Path) -> dict[str, Any]:
    """`ao repo add <path>` on a checkout without dev-cadence: what its adoption would write, `{root, name,
    paths}`; nothing is committed, pushed or added."""
    with scratch_clone(root) as (clone, _):
        paths = _sync(dc, clone)
    return {"root": str(root), "name": root.name, "paths": paths}


def body(commit: str, dc: Path, root: Path) -> str:
    """The adoption PR's body: dev-cadence's commit, and the person's own run once it merges."""
    return (
        f"Adopts dev-cadence at {commit}, written by `{dc}/sync.sh` in a scratch clone (`ao repo add --adopt`,"
        " ShiftLead design §4.7).\n\n"
        "ShiftLead serves this repo once this PR is merged and the checkout is pulled; it never merges it.\n\n"
        f"After the merge, run `{dc}/sync.sh {root}` in the checkout: it sets up dev-cadence's hook shim there and"
        " puts the checkout on dev-cadence's roster, so later syncs reach it.\n"
    )


def adopt(root: Path, dc: Path, gh: str = "gh") -> dict[str, Any]:
    """`ao repo add <path> --adopt`: the offer's run committed on `cadence-adopt`, pushed, and opened as a
    PR against the default branch; `{root, name, paths, commit, pr, url}`. An `origin` not on GitHub is
    refused, as is a default branch that already holds what the adopt writes. Where origin holds
    `cadence-adopt` already, its open PR is the answer, `open` true and nothing pushed (a re-run, or one
    whose `add_repo` failed after the PR was opened); a `cadence-adopt` with no open PR is refused."""
    url = origin(root)
    if not reports.GITHUB_ORIGIN.search(url):
        raise AdoptError(f"ao repo add opens its PR on GitHub: {root}'s origin is {url}")
    with scratch_clone(root) as (clone, default):
        if _run(["git", "branch", "-r", "--list", f"origin/{ADOPT_BRANCH}"], clone).strip():
            if pr := open_pr(clone, gh):
                return {"root": str(root), "name": root.name, "paths": [], "commit": None, "pr": pr["number"],
                        "url": str(pr.get("url") or ""), "open": True}  # fmt: skip
            raise AdoptError(
                f"origin of {root} holds a branch {ADOPT_BRANCH} with no open PR: open its PR or delete the branch,"
                " then run this again"
            )
        paths = _sync(dc, clone)
        if not paths:
            raise AdoptError(f"origin/{default} of {root} holds dev-cadence already: pull the checkout")
        lock = (
            sync.parse_lock((clone / sync.LOCK).read_text(encoding="utf-8")) if (clone / sync.LOCK).is_file() else None
        )
        commit = (lock or {}).get("commit") or "?"
        _run(["git", "switch", "-q", "-c", ADOPT_BRANCH], clone)
        _run(["git", "add", "-A"], clone)
        _run(["git", *_identity(root), "commit", "-q", "-m", f"adopt dev-cadence {commit}"], clone)
        _run(["git", "push", "-q", "-u", "origin", ADOPT_BRANCH], clone)
        note = clone.parent / "pr-body.md"
        note.write_text(body(commit, dc, root), encoding="utf-8")
        title = f"Adopt dev-cadence {commit}"
        out = _run(
            [gh, "pr", "create", "--head", ADOPT_BRANCH, "--base", default, "--title", title, "--body-file", str(note)],
            clone,
        )
    m = PR_URL.search(out)
    return {
        "root": str(root),
        "name": root.name,
        "paths": paths,
        "commit": commit,
        "pr": int(m[1]) if m else None,
        "url": m[0] if m else out.strip(),
    }
