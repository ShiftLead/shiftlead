#!/usr/bin/env python3
# SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/scripts/ledger_next_id.py
# Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one).
"""Hand out the next ledger id from the counter on origin (TD-124, cadence.md §2.10).

    ledger_next_id.py [--count n] [--by who] [--floor N] [--prs] [--ledger PATH] [--archive PATH] [--json]

The counter is a branch on origin, ``cadence/ledger-ids``: never merged, never checked out, never a
local branch. Its tip's tree holds one file, ``LAST``, the last id given as a number. A take is one
commit whose parent is the tip it read, pushed with a plain (fast-forward) push: the server takes it
only if nobody moved the tip, so the branch is a lock with no server of ours. The design is
docs/plans/2026-10-22-ledger-ids.md in dev-cadence.

1. Probe ``git ls-remote --heads origin cadence/ledger-ids``: present, absent (the first take), or
   failed — the last goes to the fallback.
2. Fetch ``origin/<default>`` and, when present, the counter, in one ``git fetch``.
3. The next id is one above the highest of ``LAST`` (absent or not a number: ignored, a warning), the
   ids in the ledger and archive on ``origin/<default>`` (headings and table rows, read as numbers, so
   ``TD-28`` is 28), and ``--floor``. The first take also reads the open PRs (``--prs`` forces it on
   a later one): before the counter exists, ids typed by hand into open PRs are the only ones it
   cannot otherwise see. A PR it could not read is named in ``unread``; the take still reserves.
4. Write the commit (``git commit-tree``, no checkout; author and committer fixed, so a clone with no
   git identity can write it) and push it with ``git push --porcelain``.
5. On any refusal, probe again rather than trust the reason's text. The tip moved: a race — back to
   1 after a short random wait, until 30 seconds have passed, then refuse (exit 2). The tip did not
   move: the refusal is the push's own (protected, permission, hook) — the fallback.

The fallback reads main, the counter if it could be fetched, and the open PRs; it pushes nothing and
exits 3 with ``why`` naming the cause. What it cannot see (an id given and not pushed, a PR opened
after the read) is left to the cadence check's ``ledger`` row, the backstop for every unreserved id.

The commit's subject is the id or the range (``TD-967..TD-968``) then ``[skip ci]``; its body says
``by`` (``--by``, else ``git config user.email``, else unknown), ``branch`` (left out when detached),
``take`` (a nonce, so no two takes are ever one commit) and ``host`` (left out in a cloud session or a container, and when the repo's ``docs/cadence.toml``
says ``ledger-ids-host = "off"``). They are for a person reading the log; nothing decides on them.

Output: the ids, one a line; ``--json``: ``{ids, reserved, why, unread, warnings}``. Exit 0 reserved
on the counter; 3 printed but not reserved (the fallback); 2 refused, nothing printed (a fetch of
``origin/<default>`` failed, so main cannot be the floor; or 30 seconds of a moving tip) — with
``--json`` the object still prints, its ``ids`` empty and ``why`` saying why. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cadence_config as C  # noqa: E402  # sibling SYNC script: the one settings reader (§9.18)
import forge as F  # noqa: E402  # sibling SYNC script: the forge's open PRs and their head refs
import ledger as L  # noqa: E402  # sibling SYNC script: the ledger paths and the format's readers

COUNTER = "cadence/ledger-ids"
COUNTER_REF = f"refs/heads/{COUNTER}"
TRACKING_REF = f"refs/remotes/origin/{COUNTER}"
PR_NS = "refs/cadence/pr"          # where the PR read fetches heads; deleted afterwards
RACE_SECONDS = float(os.environ.get("LEDGER_IDS_RACE_SECONDS", "30"))   # tests shorten it
PR_BUDGET = 30.0
PR_LIMIT = 100
MAX_COUNT = 10
IDENTITY = {"GIT_AUTHOR_NAME": "cadence", "GIT_AUTHOR_EMAIL": "cadence@noreply",
            "GIT_COMMITTER_NAME": "cadence", "GIT_COMMITTER_EMAIL": "cadence@noreply"}
_QUIET = {"GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": os.environ.get(
    "GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=10")}


def git(root: Path, *args: str, timeout: float = 60, env: dict | None = None,
        stdin: str | None = None) -> subprocess.CompletedProcess:
    """One git call; a timeout or a missing git reads as a failed call (rc 124), never raises."""
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              timeout=max(timeout, 1), check=False, input=stdin,
                              env={**os.environ, **_QUIET, **(env or {})})
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 124, "", str(e))


def ids_in(text: str | None) -> set[int]:
    """Every id a ledger or archive holds, as numbers: its headings and its table rows."""
    t = L.LB.COMMENT_RE.sub("", text or "")
    return L.LB.heading_nums(t) | {int(m.group(2)) for m in L.ROW_RE.finditer(t)}


def ids_at(root: Path, ref: str, ledger: str, archive: str) -> set[int]:
    out: set[int] = set()
    for rel in (ledger, archive):
        r = git(root, "show", f"{ref}:{rel}")
        if r.returncode == 0:
            out |= ids_in(r.stdout)
    return out


def tid(n: int) -> str:
    """§2.2's width: three digits, more past 999."""
    return f"TD-{n:03d}"


# -- the open PRs: one read, shared with check_cadence.py's ledger row -------------------------

def read_prs(root: Path, ledger: str, archive: str, budget: float = PR_BUDGET, base: bool = False,
             notes: list | None = None, be=None) -> tuple[dict, list]:
    """({n: {"head": ids, "base": ids | None, "sha": head}}, unread) for the forge's open PRs. Each head is
    fetched by the forge's head_ref into PR_NS (one fetch, head by head if the batch fails), and
    its ledger and archive read whole. With base, the ids at each head's merge-base with
    origin/<default> too (more history fetched where a shallow clone lacks it); None where there is
    none. unread names what was not read: a PR whose head could not be fetched, one past the
    budget, a list cut at the limit, a list that could not be had. With no forge to ask (none,
    other, no CLI) the read is skipped and ``notes`` says so; nothing is unread. ``be`` is a
    caller's own forge backend (check_cadence.py's), asked as it is instead of origin's."""
    say = notes.append if notes is not None else (lambda _m: None)
    end = time.monotonic() + budget
    if be is None:
        kind, host = F.origin_forge(root)
        if kind in ("none", "other"):
            say("open PRs not read: " + ("origin names no forge" if kind == "none"
                                         else F.forge_unread_line(host or "?")))
            return {}, []
        try:
            be = F.backend(root, cwd=str(root))
        except F.ForgeUnreadable as e:
            say(f"open PRs not read: {e}")
            return {}, []
    gone = be.missing()
    if gone:
        say(f"open PRs not read: {gone}")
        return {}, []
    try:
        listed = be.open_prs(PR_LIMIT, max(end - time.monotonic(), 1))
    except (F.ForgeUnreadable, ValueError, TypeError) as e:
        return {}, [f"the open PR list ({e})"]
    unread: list[str] = []
    if len(listed) >= PR_LIMIT:
        unread.append(f"the list (cut at {PR_LIMIT})")
    nums = [p["number"] for p in listed if p.get("number") is not None]
    local = {n: f"{PR_NS}/{n}" for n in nums}
    default = L.N.default_branch(root)
    out: dict = {}
    try:
        if nums:
            specs = [f"+{be.head_ref(n)}:{local[n]}" for n in nums]
            r = git(root, "fetch", "--quiet", "--no-tags", "origin", *specs,
                    timeout=end - time.monotonic())
            fetched = set(nums) if r.returncode == 0 else set()
            if r.returncode != 0:   # one PR closed between the list and the fetch aborts the batch
                for n in nums:
                    left = end - time.monotonic()
                    if left <= 0.5:
                        break
                    if git(root, "fetch", "--quiet", "--no-tags", "origin",
                           f"+{be.head_ref(n)}:{local[n]}", timeout=left).returncode == 0:
                        fetched.add(n)
            deepened = False
            for n in nums:
                if n not in fetched:
                    unread.append(be.ref(n))
                    continue
                rec = {"head": ids_at(root, local[n], ledger, archive), "base": None,
                       "sha": git(root, "rev-parse", local[n]).stdout.strip()}
                if base:
                    mb = git(root, "merge-base", local[n], f"refs/remotes/origin/{default}")
                    if mb.returncode != 0 and not deepened and end - time.monotonic() > 1 and git(
                            root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
                        deepened = True
                        git(root, "fetch", "--quiet", "--no-tags", "--unshallow", "origin",
                            f"+refs/heads/{default}:refs/remotes/origin/{default}",
                            *[f"+{be.head_ref(m)}:{local[m]}" for m in sorted(fetched)],
                            timeout=end - time.monotonic())
                        mb = git(root, "merge-base", local[n], f"refs/remotes/origin/{default}")
                    if mb.returncode == 0:
                        rec["base"] = ids_at(root, mb.stdout.strip(), ledger, archive)
                    else:
                        unread.append(f"{be.ref(n)} (no merge-base with {default})")
                out[n] = rec
    finally:
        for n in nums:
            git(root, "update-ref", "-d", local[n])
    return out, unread


# -- the take ------------------------------------------------------------------------------

def probe(root: Path) -> str | None:
    """The counter's sha on origin, "" when there is none, None when origin could not be asked."""
    r = git(root, "ls-remote", "--heads", "origin", COUNTER_REF, timeout=30)
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.strip() == COUNTER_REF:
            return sha.strip()
    return ""


def read_last(root: Path, tip: str, warnings: list) -> int:
    r = git(root, "show", f"{tip}:LAST")
    raw = r.stdout.strip() if r.returncode == 0 else ""
    if raw.isascii() and raw.isdigit():
        return int(raw)
    warnings.append(f"the counter's LAST is {'not a number (' + raw[:20] + ')' if raw else 'absent'}"
                    " — ignored; the ledger, archive and --floor decide")
    return 0


def host_line(root: Path, warnings: list) -> str | None:
    if os.environ.get("CLAUDE_CODE_REMOTE") or any(
            os.path.exists(p) for p in ("/.dockerenv", "/run/.containerenv")):
        return None
    try:
        v, _ = C.resolve("ledger-ids-host", C.sources(str(root)))
    except C.ConfigError as e:
        warnings.append(f"host left out: {e}")
        return None
    if str(v or "").strip().lower() == "off":
        return None
    return socket.gethostname() or None


def message(ids: list[int], by: str, branch: str | None, host: str | None) -> str:
    subject = tid(ids[0]) if len(ids) == 1 else f"{tid(ids[0])}..{tid(ids[-1])}"
    # take: a nonce, so two takes from the same tip in the same second (fixed identity, same by,
    # branch and host) are never one commit — the second push would read "[up to date]" and exit 0
    body = ([f"by: {by}"] + ([f"branch: {branch}"] if branch else []) + ([f"host: {host}"] if host else [])
            + [f"take: {uuid.uuid4().hex}"])
    return f"{subject} [skip ci]\n\n" + "\n".join(body) + "\n"


def commit(root: Path, last: int, parent: str | None, msg: str) -> str | None:
    blob = git(root, "hash-object", "-w", "--stdin", stdin=f"{last}\n")
    if blob.returncode != 0:
        return None
    tree = git(root, "mktree", stdin=f"100644 blob {blob.stdout.strip()}\tLAST\n")
    if tree.returncode != 0:
        return None
    r = git(root, "commit-tree", tree.stdout.strip(), *(["-p", parent] if parent else []), "-F", "-",
            stdin=msg, env=IDENTITY)
    return r.stdout.strip() if r.returncode == 0 else None


def pushed(out: str) -> bool:
    """The push moved the counter: its porcelain line's flag is `*` (new) or ` ` (fast-forward),
    never `=` (up to date: somebody else's identical commit is already there)."""
    return any(COUNTER_REF in ln and ln[:1] in ("*", " ") for ln in out.splitlines())


def porcelain_line(out: str, err: str) -> str:
    """The push's own line for the counter (``!\t<src>:<dst>\t[rejected] (why)``), else its error."""
    for line in out.splitlines():
        if COUNTER_REF in line:
            return line.strip()
    lines = [ln.strip() for ln in (err or out).splitlines() if ln.strip()]
    return lines[-1] if lines else "push failed"


def take(root: Path, a: argparse.Namespace) -> tuple[int, dict]:
    res: dict = {"ids": [], "reserved": False, "why": "", "unread": [], "warnings": []}
    warnings = res["warnings"]
    default = L.N.default_branch(root)
    main_ref = f"refs/remotes/origin/{default}"
    by = a.by or git(root, "config", "user.email").stdout.strip() or "unknown"
    branch = git(root, "branch", "--show-current").stdout.strip() or None
    start = time.monotonic()

    def fallback(why: str, counter_fetched: bool) -> tuple[int, dict]:
        known = ids_at(root, main_ref, a.ledger, a.archive)
        if counter_fetched:
            known.add(read_last(root, TRACKING_REF, []))
        prs, unread = read_prs(root, a.ledger, a.archive, notes=warnings)
        for rec in prs.values():
            known |= rec["head"]
        first = max([*known, a.floor or 0]) + 1
        res.update(ids=list(range(first, first + a.count)), reserved=False, why=why, unread=unread)
        return 3, res

    while True:
        tip = probe(root)
        if tip is None:
            r = git(root, "fetch", "--quiet", "--no-tags", "origin", f"+refs/heads/{default}:{main_ref}")
            if r.returncode != 0:
                res["why"] = f"could not fetch origin/{default}: {porcelain_line('', r.stderr)}"
                return 2, res
            return fallback("origin could not be asked about the counter (ls-remote failed)", False)
        specs = [f"+refs/heads/{default}:{main_ref}"] + ([f"+{COUNTER_REF}:{TRACKING_REF}"] if tip else [])
        r = git(root, "fetch", "--quiet", "--no-tags", "origin", *specs)
        if r.returncode != 0 and tip and probe(root) not in (None, tip) \
                and time.monotonic() - start <= RACE_SECONDS:
            continue   # the counter moved (or went) between the probe and the fetch: probe again
        if r.returncode != 0:
            res["why"] = f"could not fetch origin/{default}: {porcelain_line('', r.stderr)}"
            return 2, res
        parent = None
        known = ids_at(root, main_ref, a.ledger, a.archive)
        if tip:
            parent = git(root, "rev-parse", "--verify", "-q", TRACKING_REF).stdout.strip() or None
            known.add(read_last(root, parent or tip, warnings))
        res["unread"] = []
        if not tip or a.prs:
            prs, res["unread"] = read_prs(root, a.ledger, a.archive, notes=warnings)
            for rec in prs.values():
                known |= rec["head"]
        first = max([*known, a.floor or 0]) + 1
        ids = list(range(first, first + a.count))
        sha = commit(root, ids[-1], parent, message(ids, by, branch, host_line(root, warnings)))
        if sha is None:
            res["why"] = "could not write the counter's commit"
            res["ids"] = ids
            return 3, res
        # A push that timed out here but landed there reads as refused; the probe below then sees
        # the tip moved and retries — one id is burnt, never given twice.
        p = git(root, "push", "--porcelain", "origin", f"{sha}:{COUNTER_REF}")
        if p.returncode == 0 and pushed(p.stdout):
            git(root, "update-ref", TRACKING_REF, sha)
            res.update(ids=ids, reserved=True, why="")
            return 0, res
        why = porcelain_line(p.stdout, p.stderr)
        now = probe(root)
        if now is None:
            return fallback(f"the push was refused and origin could not be asked again: {why}", bool(tip))
        if now == (parent or ""):
            return fallback(f"the push was refused with the counter unmoved: {why}", bool(tip))
        if time.monotonic() - start > RACE_SECONDS:
            res.update(ids=[], why=f"the counter kept moving for {RACE_SECONDS:g}s; nothing taken")
            return 2, res
        time.sleep(random.uniform(0.05, 0.5))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--count", type=int, default=1, help=f"how many ids, 1 to {MAX_COUNT}")
    ap.add_argument("--by", help="who takes them (a front end passes its caller's name)")
    ap.add_argument("--floor", type=int, help="a front end's own last-given id: every id is above it")
    ap.add_argument("--prs", action="store_true", help="read the open PRs on a later take too")
    ap.add_argument("--ledger", default=L.LEDGER_REL)
    ap.add_argument("--archive", default=L.ARCHIVE_REL)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not 1 <= a.count <= MAX_COUNT:
        ap.error(f"--count is 1 to {MAX_COUNT}")
    if a.floor is not None and a.floor < 0:
        ap.error("--floor is a number of 0 or more")
    top = git(Path.cwd(), "rev-parse", "--show-toplevel")
    if top.returncode != 0 or not top.stdout.strip():
        print("ledger_next_id: not inside a git work tree", file=sys.stderr)
        return 2
    rc, res = take(Path(top.stdout.strip()), a)
    if rc == 2:
        res["ids"] = []
    res["warnings"] = list(dict.fromkeys(res["warnings"]))   # a retried pass repeats its warnings
    if a.json:
        print(json.dumps({**res, "ids": [tid(n) for n in res["ids"]]}, indent=1))
    else:
        for n in res["ids"]:
            print(tid(n))
        for w in res["warnings"]:
            print(f"ledger_next_id: {w}", file=sys.stderr)
        if res["unread"]:
            print("ledger_next_id: open PRs not read: " + ", ".join(res["unread"]), file=sys.stderr)
        if rc == 3:
            print(f"ledger_next_id: NOT reserved — {res['why']}", file=sys.stderr)
        elif rc == 2:
            print(f"ledger_next_id: refused — {res['why']}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
