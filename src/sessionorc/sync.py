"""The home's sync check (design §6 *Sync: a mechanical sync PR is merged at the home*, TD-681,
TD-685, TD-1015): whether a sync PR (§4.4 *A sync PR is the team's at once*) is a routine bump of the repo's
dev-cadence pin — its pin lines alone moved, to a commit of the same source's default branch that descends
from the old one. A repo that still held a `cadence-sync.lock` was checked by replaying the lock's files; that
road left once no served repo held a lock (TD-1015), and a merge base with no pin is refused.

`check` reads git only — the repo's checkout and the dev-cadence clone the pin names — and is called off the
loop by the pass (TD-685 slice 2), which posts the review evidence, runs the gate and merges. It answers
`{verdict, why, …}`: *mechanical*; *refused* with the first reason that held, worded as §6 words
it; *moved* — the head on origin is not the one asked about, so nothing was checked; or *error* —
the home's own failure (a fetch, git), which is no reading."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import tomllib
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from sessionorc import cadence, paths, promote
from sessionorc import held as held_mod
from sessionorc.workorders import _git as _git_bytes
from sessionorc.workorders import default_branch

LOCK = "docs/cadence-sync.lock"  # dev-cadence's old lock (`sync.sh`), read by the seams and `ao repo add`
GIT_TIMEOUT = 60.0
FETCH_TIMEOUT = 120.0
FILE_LINE = re.compile(r"^file:\s+(\S+)\s+([0-9a-f]{64})\s+([0-7]{3,6})\s*$")
PIN = cadence.PIN  # a pinned repo's `[dev-cadence]` table, the one file a routine bump changes (TD-1015)
PIN_TABLES = ("[dev-cadence]", '["dev-cadence"]')
TABLE_LINE = re.compile(r"^\s*\[")
# the pin's `ref` line, its value whatever it holds and its tag comment, as `dev-cadence bump` writes it
REF_LINE = re.compile(r'^\s*ref\s*=\s*"[^"]*"\s*(#.*)?$')


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


def _text(root: Path | str, rev: str, path: str) -> str | None:
    data = _blob(root, rev, path)
    return None if data is None else data.decode(errors="replace")


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
) -> dict[str, Any]:
    """Steps 1 and 2 of §6 *Sync* on sync PR `number` at `head` (its `branch` on origin), as one check of a
    bump of the pin (`_check_bump`, TD-1015): `{verdict, why, head}` with, for a mechanical one, `kind: bump`,
    `commit` the new `ref`, `old` the one it moves from and `files` the pin's file. `clones` are the registry's
    checkouts, among which the pin's `source` is found; `held` the globs of the flow that serves the repo. A
    merge base with no pin is refused: the lock's replay left once no served repo held a lock."""
    root = Path(root)
    out: dict[str, Any] = {"head": head}
    try:
        why = _check(root, number, head, branch, list(clones), list(held), out)
    except _Error as e:
        return {**out, "verdict": "error", "why": str(e)}
    except _Moved as e:
        return {**out, "verdict": "moved", "why": str(e)}
    return {**out, "verdict": "refused", "why": why} if why else {**out, "verdict": "mechanical", "why": ""}


def _check(
    root: Path, number: int, head: str, branch: str, clones: list[Path | str], held: list[str], out: dict[str, Any],
) -> str | None:  # fmt: skip
    want = default_branch(root)
    _out(root, "fetch", "-q", "origin", f"refs/heads/{branch}", timeout=FETCH_TIMEOUT)
    if _out(root, "rev-parse", "FETCH_HEAD").strip() != head:
        raise _Moved(f"#{number}'s head moved from {head[:7]}: the PR was not checked")
    _out(root, "fetch", "-q", "origin", want, timeout=FETCH_TIMEOUT)
    base = _out(root, "merge-base", head, f"origin/{want}").strip()
    if (old_pin := pin_at(root, base)) is None:
        return f"no [dev-cadence] pin at the merge base: {PIN} holds none"
    return _check_bump(root, base, head, old_pin, clones, held, out)


def pin_at(root: Path | str, rev: str) -> tuple[str, str] | None:
    """`(source, ref)` of the `[dev-cadence]` table in `docs/cadence.toml` at `rev`, or None where there is
    none or it does not parse. The `ref` is kept as written, so a padded one is no full commit."""
    text = _text(root, rev, PIN)
    try:
        got = tomllib.loads(text).get("dev-cadence") if text is not None else None
    except tomllib.TOMLDecodeError:
        return None
    if not isinstance(got, dict) or not isinstance(got.get("source"), str) or not isinstance(got.get("ref"), str):
        return None
    return got["source"].strip(), got["ref"]


def only_ref_moved(before: str, after: str) -> bool:
    """Whether `after` differs from `before` in the `[dev-cadence]` table's `ref` line alone, its tag comment
    with it (TD-1015): every other line, in number and in bytes, the same."""
    a, b = before.splitlines(), after.splitlines()
    if len(a) != len(b):
        return False
    table = ""
    for x, y in zip(a, b, strict=True):
        if TABLE_LINE.match(x):
            table = x.split("#", 1)[0].strip().replace(" ", "")
        if x != y and not (table in PIN_TABLES and REF_LINE.match(x) and REF_LINE.match(y)):
            return False
    return True


def _check_bump(
    root: Path, base: str, head: str, old: tuple[str, str], clones: list[Path | str], held: list[str],
    out: dict[str, Any],
) -> str | None:  # fmt: skip
    """§6 *Sync* in a repo that pins dev-cadence (TD-1015): the PR is a routine bump — it changes
    `docs/cadence.toml` alone, there the pin's `ref` line alone, under the same `source`, to a full commit on
    that source's default branch that descends from the old `ref`. None when it is, else the first reason."""
    for _, path in _changes(root, base, head):
        if path != PIN:
            return f"not a routine bump: {path} changed"
    new = pin_at(root, head)
    if new is None:
        return f"not a routine bump: {PIN} holds no [dev-cadence] pin"
    if new[0] != old[0]:
        return "the pin's source changed"
    if not only_ref_moved(_text(root, base, PIN) or "", _text(root, head, PIN) or ""):
        return f"not a routine bump: {PIN} changed beyond the pin's ref"
    if new[1] == old[1]:
        return "not a routine bump: the pin's ref did not move"
    clone = find_clone(new[0], clones)
    if clone is None:
        return "no dev-cadence clone to check the pin against"
    dc = default_branch(clone)
    _out(clone, "fetch", "-q", "origin", dc, timeout=FETCH_TIMEOUT)
    ref = new[1]
    full = re.fullmatch(r"[0-9a-f]{40}", ref) and _git(clone, "cat-file", "-e", f"{ref}^{{commit}}").returncode == 0
    if not full or _git(clone, "merge-base", "--is-ancestor", ref, f"origin/{dc}").returncode != 0:
        return f"ref {ref[:7] or '(none)'} is not a full commit on dev-cadence's {dc}"
    if _git(clone, "merge-base", "--is-ancestor", old[1], ref).returncode != 0:
        return f"ref {ref[:7]} does not descend from {old[1][:7]}"
    if any(held_mod.matches(PIN, g) for g in held):
        return f"{PIN} is a held path"
    out.update(kind="bump", commit=ref, old=old[1], files=[PIN], post_sync=False)
    return None


# -- the pass (§6 *Sync*, steps 3 to 5; TD-685 slice 2) ---------------------------------------------------

SYNC_TRIES = 3  # passes at one head with no reading before its verdict is *error* (§6 step 4)
SYNC_PRECHECK_WAIT = 86400.0  # seconds a PR waits at one head for its precheck before *refused* (§6 step 4)
GH_TIMEOUT = 30.0
GATE_TIMEOUT = 300.0
SETTLED = ("merged", "refused", "gate", "error")  # a verdict at a head is final for that head; *off* is not
REVIEWER = "sync-check"  # named for what it is, never a model (§6 step 3)
REVIEW_LINE = re.compile(r"^\s*cadence-review:\s*(SHIP|FIXED|BLOCK)\b(.*)$", re.IGNORECASE)  # the gate's REVIEW_RE
SHA_RUN = re.compile(r"\b[0-9a-f]{7,40}\b")


def settled(entry: dict[str, Any] | None, head: str) -> bool:
    """Whether the pass has a verdict for this head, so it is never checked again."""
    return bool(entry) and entry.get("head") == head and entry.get("verdict") in SETTLED


def unprechecked(pr: dict[str, Any]) -> bool:
    """A PR whose checks read *none* with no `cadence/precheck` on its head: in a repo that sets `precheck`,
    step 4's precheck is what makes it green (§6 *Sync*, TD-1039)."""
    return pr.get("checks") == "none" and not pr.get("prechecked")


def candidates(
    prs: list[dict[str, Any]], sync: dict[str, Any], held_by: Any, precheck: bool = False
) -> list[dict[str, Any]]:
    """The open sync PRs the pass takes up (§6 *Sync*): flagged `sync` (§4.4's test), not a draft, not
    conflicting, *green* — or, where the repo sets `precheck`, `unprechecked` — held by no live record
    (`held_by(pr)`), and with no verdict at their head."""
    return [
        pr
        for pr in prs
        if isinstance(pr, dict)
        and pr.get("sync") is True
        and not pr.get("draft")
        and not pr.get("conflicting")
        and (pr.get("checks") == "green" or (precheck and unprechecked(pr)))
        and pr.get("head")
        and not settled(sync.get(str(pr.get("number"))), str(pr["head"]))
        and not held_by(pr)
    ]


def prune(sync: dict[str, Any], prs: list[dict[str, Any]]) -> dict[str, Any]:
    """The kept outcomes, pruned to the open PRs and the newest *merged* one, which the Repos card names
    (§4.5a) and which neither the pass nor the order reads, since both walk the open PRs."""
    open_ = {str(p.get("number")) for p in prs if isinstance(p, dict)}
    merged = [
        (str(e.get("at") or ""), n) for n, e in sync.items() if isinstance(e, dict) and e.get("verdict") == "merged"
    ]
    last = max(merged)[1] if merged else None
    return {n: e for n, e in sync.items() if (n in open_ or n == last) and isinstance(e, dict)}


def decline(pr: dict[str, Any], login: str | None) -> str | None:
    """Why a green sync PR is not the home's to check, or None (§6 *Sync*'s two kinds)."""
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


def compare_review(root: Path | str, number: int, head: str) -> tuple[str | None, bool]:
    """Whether bump PR `number` carries a review of its compare at `head` (§6 *Sync* step 3 for a bump,
    TD-1015): a `cadence-review:` SHIP or FIXED comment whose reviewer is not `sync-check` and whose body names
    the head (seven characters or more), with no BLOCK after it. `(why, False)` when the comments were not
    read."""
    why, text = _gh(root, ["pr", "view", str(number), "--json", "comments"])
    if why:
        return why, False
    try:
        comments = json.loads(text).get("comments") or []
    except (ValueError, AttributeError):
        return "gh gave no comments", False
    seen = False
    for c in comments if isinstance(comments, list) else []:  # oldest first, as gh gives them
        body = str(c.get("body") or "") if isinstance(c, dict) else ""
        m = next((hit for line in reversed(body.splitlines()) if (hit := REVIEW_LINE.match(line))), None)
        if m is None:
            continue
        if m[1].upper() == "BLOCK":
            seen = False
            continue
        reviewer = m[2].strip(" ·-").split("·", 1)[0].strip()
        if reviewer.lower() != REVIEWER and any(head.startswith(s) for s in SHA_RUN.findall(body)):
            seen = True
    return None, seen


def merge(root: Path | str, number: int, head: str) -> str | None:
    """`gh pr merge <n> --squash --match-head-commit <head>`, no body (§6 step 5); None when merged."""
    return _gh(root, ["pr", "merge", str(number), "--squash", "--match-head-commit", head], GATE_TIMEOUT)[0]


def held_globs(root: Path | str) -> list[str] | None:
    """The repo's `held:` from its `.shiftlead.yml` (§4.9c *What is the repo's*): what every review stage
    holds, so a sync PR touching one is the team's: the list, or the union of its named sets (§4.9c *A repo
    names its path sets*). No file holds nothing; a file that cannot be read, or a `held:` that is neither
    a list nor a mapping of lists, is None — no reading, never *nothing held*."""
    f = paths.repo_file(root)
    if not f.exists():
        return []
    try:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    got = doc.get("held", []) if isinstance(doc, dict) else [] if doc is None else None
    if isinstance(got, dict):
        if not all(isinstance(v, list) for v in got.values()):
            return None
        got = [g for globs in got.values() for g in globs]
    if not isinstance(got, list):
        return None
    return list(dict.fromkeys(str(g) for g in got if isinstance(g, str) and g.strip()))


def _no_reading(entry: dict[str, Any], why: str, at: str) -> dict[str, Any]:
    tries = int(entry.get("tries") or 0) + 1
    return {**entry, "tries": tries, "verdict": "error" if tries >= SYNC_TRIES else "", "why": why, "at": at}


def judge(
    root: Path | str, pr: dict[str, Any], entry: dict[str, Any] | None, clones: Iterable[Path | str], at: str,
    *, gate: Any = None, precheck: bool = False,
) -> dict[str, Any] | None:  # fmt: skip
    """Steps 1 to 4 on one candidate, blocking (called off the loop): the entry to keep, `ready` set on
    one the gate passed — the merge is the caller's, after it reads the holders again — or None for a
    head that moved (nothing written). A retry keeps `posted`, so the SHIP comment is posted once per
    head; no reading counts `tries`, and at `SYNC_TRIES` the verdict is *error*. With `precheck` (a PR
    awaiting its precheck) the gate is not run: a mechanical one comes back with `prestart` set, and the
    start is the caller's, under the promote lock."""
    number, head = int(pr["number"]), str(pr["head"])
    e = dict(entry) if entry and entry.get("head") == head else {"head": head, "tries": 0, "posted": False}
    e.pop("ready", None)
    e.pop("prestart", None)
    held = held_globs(root)
    if held is None:
        return _no_reading(e, "the repo's .shiftlead.yml held: could not be read", at)
    got = check(root, number, head, str(pr.get("branch") or ""), clones=clones, held=held)
    if got["verdict"] == "moved":
        return None
    if got["verdict"] == "error":
        return _no_reading(e, got["why"], at)
    if got["verdict"] == "refused":
        return {**e, "verdict": "refused", "why": got["why"], "at": at}
    bump = got.get("kind") == "bump"
    if bump:  # the home posts no evidence of its own for a bump: it waits on a review of the compare (TD-1015)
        why, read = compare_review(root, number, head)
        if why:
            return _no_reading(e, f"the PR's comments could not be read: {why}", at)
        if not read:
            return {**wait_entry(e, head, f"no review of the compare at {head[:7]}", at, "review"), "waits": "review"}
        if e.pop("waits", None):
            e.pop("waiting_since", None)
    elif not e.get("posted"):
        if why := comment(root, number, review_body(got)):
            return _no_reading(e, f"the review comment was not posted: {why}", at)
        e["posted"] = True
    if precheck:
        return {**e, "at": at, "prestart": True}
    g = (gate or cadence.check)(root, number, GATE_TIMEOUT)
    if g is None or g.get("verdict") not in ("pass", "fail"):
        return _no_reading(e, "the gate gave no reading", at)
    if g["verdict"] == "fail":
        line = "; ".join(g.get("failed") or []) or "the gate failed"
        if why := comment(root, number, block_body(line)):
            return _no_reading(e, f"the BLOCK comment was not posted: {why}", at)
        return {**e, "verdict": "gate", "why": line, "at": at}
    return {**e, "verdict": "", "why": "", "at": at, "ready": True, "kind": got.get("kind") or "sync",
            "commit": got.get("commit") or "", "files": len(got.get("files") or [])}  # fmt: skip


def mark(prs: list[dict[str, Any]], sync: dict[str, Any], auto: bool) -> list[dict[str, Any]]:
    """The open PRs as TD-684's order reads them once the home merges (§6 *Sync*): a sync PR the home
    holds — merged at its head, or green with no verdict at its head while the switch is on — carries
    `sync_home`, and is no order; one with a verdict at its head carries `sync_why`, its order's
    `Context`, and so does one *off* at its head the home does not hold (*sync is off*), and a bump waiting on
    the review of its compare, which is the team's to give (TD-1015). Copies; the
    reading is never changed. A PR the pass left waiting on its precheck at its head (`waiting_since`)
    waits as a green one does."""
    out = []
    for pr in prs:
        if not isinstance(pr, dict) or pr.get("sync") is not True:
            out.append(pr)
            continue
        e = sync.get(str(pr.get("number")))
        head = str(pr.get("head") or "")
        if settled(e, head):
            pr = {**pr, "sync_home": True} if e["verdict"] == "merged" else {**pr, "sync_why": str(e.get("why") or "")}
        elif e and e.get("head") == head and e.get("waits") == "review" and not e.get("verdict"):
            pr = {**pr, "sync_why": str(e.get("why") or "")}  # a bump's review is the team's to give (TD-1015)
        elif (
            auto
            and not pr.get("draft")
            and not pr.get("conflicting")
            and (pr.get("checks") == "green" or (waiting(e, head) and unprechecked(pr)))
        ):
            pr = {**pr, "sync_home": True}  # a PR awaiting its precheck waits as a green one (§4.4, TD-1039)
        elif e and e.get("verdict") == "off" and e.get("head") == head:
            pr = {**pr, "sync_why": str(e.get("why") or "sync is off")}
        out.append(pr)
    return out


# -- step 4's precheck (§6 *Sync* step 4, TD-1039) --------------------------------------------------------


def waiting(entry: dict[str, Any] | None, head: str) -> bool:
    """Whether the pass left this head waiting on its precheck: an entry at it with `waiting_since` and
    no verdict."""
    return bool(entry) and entry.get("head") == head and bool(entry.get("waiting_since")) and not entry.get("verdict")


def checkout_why(root: Path | str) -> str | None:
    """Why the registry checkout cannot run `precheck.py`, which reads the command from the tree it runs
    in: None on `origin/<default>`'s head with a clean tree, else the reason."""
    want = default_branch(Path(root))
    try:
        head = _out(root, "rev-parse", "HEAD").strip()
        tip = _out(root, "rev-parse", f"origin/{want}").strip()
        status = _out(root, "status", "--porcelain")
    except _Error as e:
        return f"the checkout cannot be read: {e}"
    if head != tip:
        return f"the checkout is at {head[:7]}, not origin/{want}'s head {tip[:7]}"
    if status.strip():
        n = len(status.splitlines())
        return f"the checkout has {n} uncommitted change{'' if n == 1 else 's'}"
    return None


def precheck_blocked(root: Path | str, repo: str) -> str | None:
    """Why no precheck can start now — a run of the repo going (main's or a PR's: one at a time), or the
    checkout — or None. Read again under the promote lock just before the start."""
    if promote._going(promote.precheck_run(repo)) or promote._going(promote.precheck_pr_run(repo)):
        return f"a precheck of {repo} is running"
    return checkout_why(root)


def tend_precheck(root: Path | str, repo: str, prs: list[dict[str, Any]], sync: dict[str, Any], at: str) -> str | None:
    """The life of `precheck-pr.json`, once a pass under the promote lock, before the candidates (§6 *Sync*
    step 4): a `pid: null` file is dropped, uncounted; a PR no longer open, or a head that moved, kills a
    live run and drops the file; a run gone with no status on its head counts one pass with no reading
    toward `SYNC_TRIES`, once (`counted`), after which a later pass may start a new one; a status on the
    head ends it, whatever the exit. Changes `sync` in place; returns the PR it counted, which this pass
    leaves waiting. The bound is judged first, as the readings' pass judges it."""
    promote.precheck_pr_bound(root, repo, datetime.fromisoformat(at))
    f = promote.precheck_pr_run(repo)
    if not f:
        return None
    if f.get("pid") is None:
        promote.clear(repo, "precheck-pr")
        return None
    n, sha = str(f.get("pr")), str(f.get("sha") or "")
    pr = next((p for p in prs if isinstance(p, dict) and str(p.get("number")) == n), None)
    if pr is None or str(pr.get("head") or "") != sha:
        promote.kill_precheck(root, f)  # only while its start time matches; the cleanup either way
        promote.clear(repo, "precheck-pr")
        return None
    if promote._going(f):
        return None
    if not unprechecked(pr):
        promote.clear(repo, "precheck-pr")  # its status is the gate's to read
        return None
    if f.get("counted") or settled(sync.get(n), sha):
        return None
    e = sync.get(n) if (sync.get(n) or {}).get("head") == sha else {"head": sha, "tries": 0, "posted": False}
    why = f"precheck on {sha[:7]} ended and recorded nothing" + (f" ({f['why']})" if f.get("why") else "")
    sync[n] = {**_no_reading(dict(e), why, at), "waiting_since": e.get("waiting_since") or at}
    promote._write(promote.repo_dir(repo) / "precheck-pr.json", {**f, "counted": True})
    return n


def wait_entry(entry: dict[str, Any] | None, head: str, why: str, at: str, what: str = "precheck") -> dict[str, Any]:
    """A pass that waits on the precheck — or, for a bump, on the review of its compare (`what`) — uncounted:
    the entry at `head` with `waiting_since` (set on the first waiting pass, reset by a new head) and the
    wait's reason; at `SYNC_PRECHECK_WAIT` the verdict is *refused*, *<what> waited a day: <the reason>*, and
    the PR the team's."""
    e = dict(entry) if entry and entry.get("head") == head else {"head": head, "tries": 0, "posted": False}
    e.pop("prestart", None)
    since = e.get("waiting_since") or at
    e.update(waiting_since=since, why=why, at=at, verdict=e.get("verdict") or "")
    age = promote._age(since, datetime.fromisoformat(at))
    if age is not None and age >= SYNC_PRECHECK_WAIT:
        e.update(verdict="refused", why=f"{what} waited a day: {why}")
    return e
