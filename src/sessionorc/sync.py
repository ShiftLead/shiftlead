"""The home's sync check (design §6 *Sync: a mechanical sync PR is merged at the home*, TD-681,
TD-685): whether a sync PR (§4.4 *A sync PR is the team's at once*) is mechanical — its files are
dev-cadence's (step 1) and replaying them, with the repo's `post_sync`, gives the PR's head (step 2).

`check` reads git only — the repo's checkout, the dev-cadence clone the lock names, and the home's
own replay tree `~/.shiftlead/sync/<repo>/tree` — and is called off the loop by the pass (TD-685
slice 2), which posts the review evidence, runs the gate and merges. It answers
`{verdict, why, …}`: *mechanical*; *refused* with the first reason that held, worded as §6 words
it; *moved* — the head on origin is not the one asked about, so nothing was checked; or *error* —
the home's own failure (a fetch, the tree, git), which is no reading."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from sessionorc import cadence, paths
from sessionorc import held as held_mod
from sessionorc.workorders import _git as _git_bytes
from sessionorc.workorders import default_branch

LOCK = "docs/cadence-sync.lock"  # dev-cadence's lock (`sync.sh`), as §4.4's sync test reads it
TOML = "docs/cadence.toml"  # where `post_sync` is read, from the merge base's copy (dev-cadence#TD-113)
SYNC_BOUND = 300.0  # seconds `post_sync` may run before its process group is killed (§6)
GIT_TIMEOUT = 60.0
FETCH_TIMEOUT = 120.0
TERM_GRACE = 2.0
ENV_KEPT = ("PATH", "HOME", "LANG")  # `post_sync`'s whole environment: no token, no Doppler, no SHIFTLEAD_*
FILE_LINE = re.compile(r"^file:\s+(\S+)\s+([0-9a-f]{64})\s+([0-7]{3,6})\s*$")


class _Error(Exception):
    """The home's own failure: no reading, never a verdict on the PR."""


class _Moved(Exception):
    """The PR's head is not the one asked about: the pass drops it, and checks the new head next."""


def _git(root: Path | str, *args: str, timeout: float = GIT_TIMEOUT) -> subprocess.CompletedProcess[bytes]:
    try:
        return _git_bytes(Path(root), list(args), timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise _Error(f"git {args[0]}: {type(e).__name__}") from None


def _out(root: Path | str, *args: str, timeout: float = GIT_TIMEOUT) -> str:
    """stdout of a git call that must succeed, else the home's own error."""
    cp = _git(root, *args, timeout=timeout)
    if cp.returncode != 0:
        lines = cp.stderr.decode(errors="replace").strip().splitlines()
        raise _Error(f"git {args[0]}: {lines[-1][:200] if lines else f'exit {cp.returncode}'}")
    return cp.stdout.decode(errors="replace")


def _blob(root: Path | str, rev: str, path: str) -> bytes | None:
    """The bytes of `path` at `rev`, or None where it has none."""
    cp = _git(root, "cat-file", "blob", f"{rev}:{path}")
    return cp.stdout if cp.returncode == 0 else None


def _lit(path: str) -> str:
    """A path as git reads it literally: no glob, no pathspec magic in a name the PR chose."""
    return f":(literal){path}"


def _text(root: Path | str, rev: str, path: str) -> str | None:
    data = _blob(root, rev, path)
    return None if data is None else data.decode(errors="replace")


def _mode(root: Path | str, rev: str, path: str) -> str | None:
    """`path`'s mode at `rev` as the lock writes it (`644`, `755`), or None where it has none."""
    line = _out(root, "ls-tree", rev, "--", _lit(path)).strip()
    return line.split(" ", 1)[0][-3:] if line else None


def parse_lock(text: str | None) -> dict[str, Any] | None:
    """A `cadence-sync.lock` as `{source, commit, files_commit, files: {path: (sha256, mode)}}`, or
    None for no lock."""
    if text is None:
        return None
    out: dict[str, Any] = {"source": "", "commit": "", "files_commit": "", "files": {}}
    for line in text.splitlines():
        if m := FILE_LINE.match(line.strip()):
            out["files"][m[1]] = (m[2], m[3][-3:])
            continue
        key, sep, value = line.partition(":")
        if sep and key.strip() in ("source", "commit", "files_commit"):
            out[key.strip()] = value.strip()
    return out


def _norm_url(url: str) -> str:
    """An origin compared as one repository: scheme, user, `.git` and a trailing slash dropped, the
    ssh form's `host:path` as `host/path`, lower case."""
    u = url.strip().lower().removesuffix("/").removesuffix(".git")
    u = re.sub(r"^[a-z][a-z0-9+.-]*://", "", u)
    u = re.sub(r"^[^@/]+@", "", u)
    return u.replace(":", "/", 1) if "/" not in u.split(":", 1)[0] else u


def find_clone(source: str, clones: Iterable[Path | str]) -> Path | None:
    """The registry checkout whose `origin` is the lock's `source:`, or None."""
    want = _norm_url(source)
    for c in clones:
        cp = _git(c, "remote", "get-url", "origin")
        if cp.returncode == 0 and _norm_url(cp.stdout.decode().strip()) == want:
            return Path(c)
    return None


def tree_dir(root: Path | str) -> Path:
    """The home's own replay tree for the repo at `root`: `~/.shiftlead/sync/<repo>/tree` (§6)."""
    return paths.home() / "sync" / Path(root).name / "tree"


def _tree(root: Path, rev: str) -> Path:
    """The replay tree, detached at `rev` with nothing else in it: made as the board's tree is when
    missing or another checkout's, remade once when it cannot be reset."""
    t = tree_dir(root)
    common = _out(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    why = ""
    for _ in range(2):
        mine = (t / ".git").exists() and _git(t, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if not mine or mine.returncode != 0 or mine.stdout.decode().strip() != common:
            _drop_tree(root, t)
            t.parent.mkdir(parents=True, exist_ok=True)
            cp = _git(root, "worktree", "add", "-q", "--detach", str(t), rev)
            if cp.returncode != 0:
                why = cp.stderr.decode(errors="replace").strip()[-200:]
                continue
        reset = _git(t, "reset", "-q", "--hard", rev)
        clean = _git(t, "clean", "-q", "-ffdx") if reset.returncode == 0 else reset
        if clean.returncode == 0:
            return t
        why = (clean.stderr or b"").decode(errors="replace").strip()[-200:]
        _drop_tree(root, t)
    raise _Error(f"the sync tree {t} cannot be made or reset ({why})")


def _drop_tree(root: Path, t: Path) -> None:
    if t.exists():
        _git(root, "worktree", "remove", "--force", str(t))
        if t.exists():
            shutil.rmtree(t, ignore_errors=True)
    _git(root, "worktree", "prune")


def post_sync_command(root: Path | str, rev: str) -> str | None:
    """The repo's `post_sync` from `docs/cadence.toml` at `rev`, or None where it has none (a file
    that does not parse has none: the replay runs nothing, and the comparison decides)."""
    text = _blob(root, rev, TOML)
    if text is None:
        return None
    try:
        got = tomllib.loads(text.decode(errors="replace")).get("post_sync")
    except tomllib.TOMLDecodeError:
        return None
    return got.strip() if isinstance(got, str) and got.strip() else None


def run_post_sync(tree: Path, command: str, bound: float = SYNC_BOUND) -> str | None:
    """`command` run by the shell in `tree` with `ENV_KEPT` alone, its group killed at `bound`: None
    when it exited 0, else §6's reason."""
    env = {k: os.environ[k] for k in ENV_KEPT if k in os.environ}
    with subprocess.Popen(
        ["/bin/sh", "-c", command], cwd=str(tree), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    ) as p:  # fmt: skip
        try:
            code: int | None = p.wait(timeout=bound)
        except subprocess.TimeoutExpired:
            code = None
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(p.pid, signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                p.wait(timeout=TERM_GRACE)
        # whatever it left running is killed on every road, so nothing writes the tree after the read
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(p.pid, signal.SIGKILL)
        p.wait()
    if code is None:
        return f"post_sync did not end in {bound / 60:g} min"
    return None if code == 0 else f"post_sync exited {code}"


def _changes(root: Path | str, base: str, head: str) -> list[tuple[str, str]]:
    """`(status, path)` for every path the PR changes, from `git diff --name-status`, renames as a
    deletion and an addition, never a capped list."""
    out = _out(root, "diff", "--no-renames", "--name-status", "-z", base, head)
    parts = [p for p in out.split("\0") if p]
    return [(parts[i][0], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]


def check(
    root: Path | str,
    number: int,
    head: str,
    branch: str,
    *,
    clones: Iterable[Path | str],
    held: Iterable[str] = (),
    bound: float = SYNC_BOUND,
) -> dict[str, Any]:
    """Steps 1 and 2 of §6 *Sync* on sync PR `number` at `head` (its `branch` on origin): `{verdict,
    why, head}` with, for a mechanical one, `commit` (the lock's `commit:`), `files` (the lock-listed
    paths it changes) and `post_sync` (whether one ran). `clones` are the registry's checkouts, among
    which the lock's `source:` is found; `held` the globs of the flow that serves the repo."""
    root = Path(root)
    out: dict[str, Any] = {"head": head}
    try:
        why = _check(root, number, head, branch, list(clones), list(held), bound, out)
    except _Error as e:
        return {**out, "verdict": "error", "why": str(e)}
    except _Moved as e:
        return {**out, "verdict": "moved", "why": str(e)}
    return {**out, "verdict": "refused", "why": why} if why else {**out, "verdict": "mechanical", "why": ""}


def _check(
    root: Path, number: int, head: str, branch: str, clones: list[Path | str], held: list[str], bound: float,
    out: dict[str, Any],
) -> str | None:  # fmt: skip
    want = default_branch(root)
    _out(root, "fetch", "-q", "origin", f"refs/heads/{branch}", timeout=FETCH_TIMEOUT)
    if _out(root, "rev-parse", "FETCH_HEAD").strip() != head:
        raise _Moved(f"#{number}'s head moved from {head[:7]}: the PR was not checked")
    _out(root, "fetch", "-q", "origin", want, timeout=FETCH_TIMEOUT)
    base = _out(root, "merge-base", head, f"origin/{want}").strip()
    head_lock, base_lock = (parse_lock(_text(root, rev, LOCK)) for rev in (head, base))
    if head_lock is None:
        return f"{LOCK} is not in the PR's head"
    # -- step 1: the files are dev-cadence's ---------------------------------------------------------
    if base_lock is None or head_lock["source"] != base_lock["source"]:
        return "the lock's source changed"
    clone = find_clone(head_lock["source"], clones)
    if clone is None:
        return "no dev-cadence clone to check the lock against"
    fc = head_lock["files_commit"]
    if fc.endswith("+dirty"):
        return "files_commit is +dirty"
    dc = default_branch(clone)
    _out(clone, "fetch", "-q", "origin", dc, timeout=FETCH_TIMEOUT)
    on = re.fullmatch(r"[0-9a-f]{7,40}", fc) and _git(clone, "merge-base", "--is-ancestor", fc, f"origin/{dc}")
    if not on or on.returncode != 0:
        return f"files_commit {fc[:7] or '(none)'} is not on dev-cadence's {dc}"
    changes = _changes(root, base, head)
    listed, was = head_lock["files"], base_lock["files"]
    for status, path in changes:
        if path not in listed:
            continue
        if status == "D":
            return f"{path} deleted but still in the lock"
        data = _blob(root, head, path) or b""
        if (hashlib.sha256(data).hexdigest(), _mode(root, head, path)) != listed[path]:
            return f"{path} differs from its lock line"
    for path in sorted(set(was) - set(listed)):  # a line dropped: dev-cadence retired the file too
        if _blob(clone, fc, f"files/{path}") is not None:
            return f"lock not dev-cadence's: {path}"
    for path, line in listed.items():
        if was.get(path) == line:
            continue
        data = _blob(clone, fc, f"files/{path}")
        if data is None or (hashlib.sha256(data).hexdigest(), _mode(clone, fc, f"files/{path}")) != line:
            return f"lock not dev-cadence's: {path}"
    # -- step 2: the replay ----------------------------------------------------------------------------
    tree = _tree(root, base)
    take = [LOCK, *(p for s, p in changes if p in listed and s != "D")]
    _out(tree, "checkout", head, "--", *(_lit(p) for p in dict.fromkeys(take)))
    for status, path in changes:
        if status == "D" and path in was and path not in listed:
            _out(tree, "rm", "-q", "--", _lit(path))
    _out(tree, "add", "-A")
    command = post_sync_command(root, base)
    failed = run_post_sync(tree, command, bound) if command else None
    wrote = set(_out(tree, "diff", "--name-only", "-z").split("\0")) if command else set()
    wrote |= set(_out(tree, "ls-files", "-o", "--exclude-standard", "-z").split("\0")) if command else set()
    for status, path in changes:
        if path == LOCK or path in listed:
            continue
        if status == "D":
            if path not in was:
                return f"{path} deleted but not in the base lock"
        elif path not in wrote:
            return f"{path} is not in the lock"
    _out(tree, "add", "-A")
    unlike = [p for p in _out(tree, "diff", "--cached", "--name-only", "-z", head).split("\0") if p]
    if unlike:  # §6's order: the comparison's reason, then post_sync's own failure
        return f"post_sync left {unlike[0]} unlike the PR"
    if failed:
        return failed
    for _, path in changes:
        if any(held_mod.matches(path, g) for g in held):
            return f"{path} is a held path"
    out.update(commit=head_lock["commit"], files=[p for s, p in changes if p in listed], post_sync=bool(command))
    return None


# -- the pass (§6 *Sync*, steps 3 to 5; TD-685 slice 2) ---------------------------------------------------

SYNC_TRIES = 3  # passes at one head with no reading before its verdict is *error* (§6 step 4)
GH_TIMEOUT = 30.0
GATE_TIMEOUT = 300.0
SETTLED = ("merged", "refused", "gate", "error")  # a verdict at a head is final for that head; *off* is not
REVIEWER = "sync-check"  # named for what it is, never a model (§6 step 3)


def settled(entry: dict[str, Any] | None, head: str) -> bool:
    """Whether the pass has a verdict for this head, so it is never checked again."""
    return bool(entry) and entry.get("head") == head and entry.get("verdict") in SETTLED


def candidates(prs: list[dict[str, Any]], sync: dict[str, Any], held_by: Any) -> list[dict[str, Any]]:
    """The open sync PRs the pass takes up (§6 *Sync*): flagged `sync` (§4.4's test), not a draft, not
    conflicting, *green*, held by no live record (`held_by(pr)`), and with no verdict at their head."""
    return [
        pr
        for pr in prs
        if isinstance(pr, dict)
        and pr.get("sync") is True
        and not pr.get("draft")
        and not pr.get("conflicting")
        and pr.get("checks") == "green"
        and pr.get("head")
        and not settled(sync.get(str(pr.get("number"))), str(pr["head"]))
        and not held_by(pr)
    ]


def prune(sync: dict[str, Any], prs: list[dict[str, Any]], gated: bool) -> dict[str, Any]:
    """The kept outcomes, pruned to the open PRs; a *no gate* refusal dropped once the repo has a gate,
    so the PR is judged again (§6 *Sync*)."""
    open_ = {str(p.get("number")) for p in prs if isinstance(p, dict)}
    return {
        n: e
        for n, e in sync.items()
        if n in open_
        and isinstance(e, dict)
        and not (gated and e.get("verdict") == "refused" and e.get("why") == cadence.NO_GATE)
    }


def decline(pr: dict[str, Any], login: str | None, gated: bool) -> str | None:
    """Why a green sync PR is not the home's to check, or None (§6 *Sync*'s three kinds, the gate first)."""
    if not gated:
        return cadence.NO_GATE
    if pr.get("fork"):
        return "forked"
    author = str(pr.get("author") or "")
    if not login or author.lower() != login.lower():
        return f"author {author or '(unknown)'} is not the home's"
    return None


def review_body(got: dict[str, Any]) -> str:
    """The SHIP comment for a mechanical PR (§6 step 3): the first line the cadence check reads, then
    the lock's `commit:`, the files checked, the replay and the head."""
    files = got.get("files") or []
    return "\n".join(
        [
            f"cadence-review: SHIP · {REVIEWER} · code · 0 findings",
            "",
            f"A sync of dev-cadence {got.get('commit') or '(no commit:)'}, checked by the home (design §6 *Sync*).",
            "",
            f"- {len(files)} file(s) checked against dev-cadence's `files/` at the lock's `files_commit`"
            + (": " + ", ".join(f"`{p}`" for p in files) if files else ""),
            "- post_sync replayed" if got.get("post_sync") else "- no post_sync",
            f"- head {got.get('head')}",
        ]
    )


def block_body(line: str) -> str:
    """The BLOCK comment for a gate that failed (§6 step 4), with the gate's line."""
    return f"cadence-review: BLOCK · {REVIEWER} · code · 1 findings\n\nThe gate failed: {line}"


def _gh(root: Path | str, args: list[str], timeout: float = GH_TIMEOUT) -> tuple[str | None, str]:
    """`gh <args>` in the checkout: `(None, stdout)`, or `(why, "")` in one line."""
    try:
        cp = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout, cwd=str(root))
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"gh could not be asked: {type(e).__name__}", ""
    if cp.returncode != 0:
        return ((cp.stderr or "").strip().splitlines() or [f"gh {args[0]} failed"])[-1][:200], ""
    return None, cp.stdout or ""


def gh_login() -> str | None:
    """The home's own `gh` login (`gh api user`), the account `sync-all.sh` pushes as; None unread."""
    why, out = _gh(Path.home(), ["api", "user", "--jq", ".login"])
    return out.strip() or None if why is None else None


def comment(root: Path | str, number: int, body: str) -> str | None:
    """One PR comment through `--body-file`; None when posted, else why not."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8") as f:
        f.write(body)
        f.flush()
        return _gh(root, ["pr", "comment", str(number), "--body-file", f.name])[0]


def merge(root: Path | str, number: int, head: str) -> str | None:
    """`gh pr merge <n> --squash --match-head-commit <head>`, no body (§6 step 5); None when merged."""
    return _gh(root, ["pr", "merge", str(number), "--squash", "--match-head-commit", head], GATE_TIMEOUT)[0]


def held_globs(root: Path | str) -> list[str]:
    """The repo's `held:` from its `.shiftlead.yml` (§4.9c *What is the repo's*): what every review stage
    holds, so a sync PR touching one is the team's. An unreadable file holds nothing."""
    try:
        doc = yaml.safe_load(paths.repo_file(root).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    got = doc.get("held") if isinstance(doc, dict) else None
    return [str(g) for g in got if isinstance(g, str) and g.strip()] if isinstance(got, list) else []


def _no_reading(entry: dict[str, Any], why: str, at: str) -> dict[str, Any]:
    tries = int(entry.get("tries") or 0) + 1
    return {**entry, "tries": tries, "verdict": "error" if tries >= SYNC_TRIES else "", "why": why, "at": at}


def judge(
    root: Path | str, pr: dict[str, Any], entry: dict[str, Any] | None, clones: Iterable[Path | str], at: str,
    *, gate: Any = None,
) -> dict[str, Any] | None:  # fmt: skip
    """Steps 1 to 4 on one candidate, blocking (called off the loop): the entry to keep, `ready` set on
    one the gate passed — the merge is the caller's, after it reads the holders again — or None for a
    head that moved (nothing written). A retry keeps `posted`, so the SHIP comment is posted once per
    head; no reading counts `tries`, and at `SYNC_TRIES` the verdict is *error*."""
    number, head = int(pr["number"]), str(pr["head"])
    e = dict(entry) if entry and entry.get("head") == head else {"head": head, "tries": 0, "posted": False}
    e.pop("ready", None)
    got = check(root, number, head, str(pr.get("branch") or ""), clones=clones, held=held_globs(root))
    if got["verdict"] == "moved":
        return None
    if got["verdict"] == "error":
        return _no_reading(e, got["why"], at)
    if got["verdict"] == "refused":
        return {**e, "verdict": "refused", "why": got["why"], "at": at}
    if not e.get("posted"):
        if why := comment(root, number, review_body(got)):
            return _no_reading(e, f"the review comment was not posted: {why}", at)
        e["posted"] = True
    g = (gate or cadence.check)(root, number, GATE_TIMEOUT)
    if g is None or g.get("verdict") not in ("pass", "fail"):
        return _no_reading(e, "the gate gave no reading", at)
    if g["verdict"] == "fail":
        line = "; ".join(g.get("failed") or []) or "the gate failed"
        if why := comment(root, number, block_body(line)):
            return _no_reading(e, f"the BLOCK comment was not posted: {why}", at)
        return {**e, "verdict": "gate", "why": line, "at": at}
    return {**e, "verdict": "", "why": "", "at": at, "ready": True,
            "commit": got.get("commit") or "", "files": len(got.get("files") or [])}  # fmt: skip


def mark(prs: list[dict[str, Any]], sync: dict[str, Any], auto: bool) -> list[dict[str, Any]]:
    """The open PRs as TD-684's order reads them once the home merges (§6 *Sync*): a sync PR the home
    holds — merged at its head, or green with no verdict at its head while the switch is on — carries
    `sync_home`, and is no order; one with a verdict at its head carries `sync_why`, its order's
    `Context`. Copies; the reading is never changed."""
    out = []
    for pr in prs:
        if not isinstance(pr, dict) or pr.get("sync") is not True:
            out.append(pr)
            continue
        e = sync.get(str(pr.get("number")))
        head = str(pr.get("head") or "")
        if settled(e, head):
            pr = {**pr, "sync_home": True} if e["verdict"] == "merged" else {**pr, "sync_why": str(e.get("why") or "")}
        elif auto and pr.get("checks") == "green" and not pr.get("draft") and not pr.get("conflicting"):
            pr = {**pr, "sync_home": True}
        out.append(pr)
    return out
