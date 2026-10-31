"""Derived report entries (design §4.8, TD-028 step 3): what the tick can work out about a
session's `progress` and `findings` from its branch, its PRs, and the ledger rows those PRs put on
main — so a worker that forgot to declare still shows something, marked `derived`.

Everything here runs in a thread (subprocesses only) and returns plain data. A failure — no git, no
`gh`, no network, a repo without an origin — yields nothing and is never an error: this fills in
what a session forgot and may never gate anything. §9 invariant 10 keeps what it produces out of
the way of what the session declared; that check lives on the record, not here.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from sessionorc import adapters, cadence, held, ledger
from sessionorc import ledgerboard as lb
from sessionorc.models import PR_CLOSED, FindingEntry, ProgressEntry, normalize_ref

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sessionorc.models import Session

# A work branch is named for its ledger reference (cadence §4: `tdNNN-<slug>`). Only that one shape
# is read: anything looser would turn `release-2` and `ui-3-fix` into ledger references.
BRANCH_RE = re.compile(r"^td-?(\d{1,4})(?:[-_].*)?$", re.IGNORECASE)
# a record with no `ledger` (one made before the client carried it): `derive` reads it through `layout_at`,
# so a v2 checkout's `docs/ledger` is found beside it (§4.4 *Either layout*)
LEDGER_DEFAULT = ledger.DEFAULT
DEFAULT_REFS = ("origin/HEAD", "origin/main", "origin/master")


def branch_ref(branch: str | None) -> str | None:
    """`td028-report-channels` → `TD-028`; anything else → None."""
    m = BRANCH_RE.match((branch or "").strip())
    return normalize_ref(f"TD-{m[1]}") if m else None


def holds_directory(sessions: Iterable[Session]) -> set[str]:
    """The ids of the records that *currently occupy* their directory (TD-034).

    A directory is reused run after run, and what is checked out there now belongs to whoever holds
    it now — so the branch half of `derive` is attributed by occupancy in time, not by the directory
    alone, or an exited predecessor is credited with work it never saw. The holder is the live
    record (the most recently created, when a directory has several — `shell` sessions are exempt
    from the anchor rule, §9 invariant 2), or the most recently created of the rest when none is
    live. A `closed` record never holds a directory: nothing is derived for one, so letting it hold
    would leave the directory's last real occupant uncredited.
    Records that do not hold their directory still get the `pending`-by-PR re-check, which is
    attributed by a PR the record already claimed rather than by what is checked out now (TD-032).
    """
    by_dir: dict[str, list[Session]] = {}
    for s in sessions:
        if s.dir and s.state != "closed" and adapters.has_agent(s.adapter):
            by_dir.setdefault(os.path.normpath(s.dir), []).append(s)
    holders: set[str] = set()
    for group in by_dir.values():
        live = [s for s in group if s.state != "exited"]
        holders.add(max(live or group, key=lambda s: (s.created, s.id)).id)
    return holders


def derive(
    directory: Path | str,
    branch: str | None,
    pending: list[tuple[str, int]] | None = None,
    ledger: str = LEDGER_DEFAULT,
    left: list[tuple[str, str | None]] | None = None,
    reviews: list[tuple[str, int]] | None = None,
) -> tuple[list[ProgressEntry], list[FindingEntry], list[str]]:
    """Everything this session's repo can say about it, all entries `derived` (design §4.8):

    - the checked-out branch is named for a reference → that reference is `claimed`;
    - a PR whose head is that branch → the reference carries its number, and a *merged* PR makes it
      `done`. `pending` is the (ref, pr) pairs already derived as claimed, re-checked here so a
      merge still lands after the session has moved on to its next branch;
    - the ledger rows a merged PR of this session put on main, other than the reference itself →
      findings. The squash-merge commit is found by its `(#N)` subject, which is what survives the
      branch (GitHub deletes a merged head, and the session checks out something else next).

    `left` is the branch-only claims the session has since moved off — `(ref, the branch it came
    from)`. Each is looked up one last time by branch name (`_prs_for_head`, which asks `gh` about
    that one branch and says so when it cannot be asked at all): a PR from it makes the claim real
    (and merged makes it `done`), and no PR at all puts its reference in the third return value, the
    refs to retire — while an unreachable `gh` retires nothing, because this is the one delete in
    either channel and an outage must never look like an answer. That is the whole answer to
    TD-045: a branch created and abandoned before its PR existed used to leave a `claimed` entry
    nothing could ever remove. A claim with no branch
    recorded is retired too — those are the entries written before the field existed, and they are
    the immortal ones already on the records.

    `reviews` is the (ref, pr) pairs a *declared* claim carries as `review_pr` (TD-150), re-checked
    by number after the session has left the branch: merged is `done`, closed without a merge is a
    claim whose `why` is `PR_CLOSED` — each of which clears the claim's `review_pr` — and still open
    is nothing. A PR on the checked-out branch that was closed unmerged is marked `PR_CLOSED` too.
    """
    prs = _prs(directory)
    by_head = {p.get("headRefName"): p for p in prs if p.get("headRefName")}
    by_number = {p["number"]: p for p in prs if isinstance(p.get("number"), int)}
    progress: list[ProgressEntry] = []
    merged: dict[int, str] = {}  # PR number → the reference it carries

    retire: list[str] = []
    if ref := branch_ref(branch):
        pr = by_head.get(branch)
        number = pr.get("number") if pr else None
        done = bool(pr) and _merged(pr)
        progress.append(
            ProgressEntry(
                ref=ref,
                status="done" if done else "claimed",
                pr=number,
                source="derived",
                branch=branch,
                why=PR_CLOSED if pr and not done and _closed(pr) else None,
            )
        )
        if done and isinstance(number, int):
            merged[number] = ref
    for ref, from_branch in left or []:
        pr = by_head.get(from_branch) if from_branch else None
        if pr is None and from_branch:
            # Ask about this branch by name rather than trusting the one page above: a PR older than
            # that page would otherwise read as "no PR ever", and retiring is a delete.
            found = _prs_for_head(directory, from_branch)
            if found is None:
                continue  # `gh` could not be asked at all — an outage retires nothing (PR #126 review)
            pr = found[0] if found else None
        if pr is None:
            retire.append(ref)
            continue
        number = pr.get("number")
        done = _merged(pr)
        progress.append(
            ProgressEntry(
                ref=ref, status="done" if done else "claimed", pr=number, source="derived", branch=from_branch
            )
        )
        if done and isinstance(number, int):
            merged[number] = ref
    for ref, number in pending or []:
        pr = by_number.get(number)
        if pr and _merged(pr):
            progress.append(ProgressEntry(ref=ref, status="done", pr=number, source="derived"))
            merged[number] = ref

    for ref, number in reviews or []:
        pr = by_number.get(number)
        if pr and _merged(pr):
            progress.append(ProgressEntry(ref=ref, status="done", pr=number, source="derived"))
            merged[number] = ref
        elif pr and _closed(pr):
            progress.append(ProgressEntry(ref=ref, status="claimed", pr=number, source="derived", why=PR_CLOSED))

    findings: list[FindingEntry] = []
    seen = {p.ref for p in progress}
    for number, ref in merged.items():
        for row in _ledger_rows_on_main(directory, number, ledger):
            if row != ref and row not in seen:
                seen.add(row)
                findings.append(FindingEntry(ref=row, source="derived"))
    return progress, findings, retire


def omitted(value: Any, paths: Iterable[str]) -> Any:
    """`value` without each dotted path of `paths` (the `repos` RPC's `omit`, design §4.4 *Repo facts*,
    TD-746): a path walks a mapping by key and every item of a list alike, and its last key is left out
    wherever it lands — `prs.recent.head` takes `head` from every PR of `recent`. A path that names
    nothing leaves the value as it was, so a reader's omit never fails on an older or a failed
    reading. `value` itself is never changed."""
    tree: dict[str, Any] = {}
    for path in paths:
        *head, last = str(path).split(".")
        node: dict[str, Any] | None = tree
        for k in head:
            node = node.setdefault(k, {}) if node is not None else None
        if node is not None:  # under a key already left out whole: nothing more to leave out
            node[last] = None
    return _omit(value, tree)


def _omit(value: Any, tree: dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [_omit(x, tree) for x in value]
    if not isinstance(value, dict) or not tree:
        return value
    return {k: _omit(v, tree[k]) if k in tree else v for k, v in value.items() if not (k in tree and tree[k] is None)}


def _merged(pr: dict[str, Any]) -> bool:
    return bool(pr.get("mergedAt")) or str(pr.get("state", "")).upper() == "MERGED"


def _closed(pr: dict[str, Any]) -> bool:
    """Closed without a merge: `gh`'s `CLOSED`, which it never says of a merged PR."""
    return str(pr.get("state", "")).upper() == "CLOSED" and not _merged(pr)


def _git(directory: Path | str, *args: str, timeout: float = 10.0) -> str | None:
    """stdout, or None for anything that went wrong — including a non-zero exit."""
    try:
        cp = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return cp.stdout if cp.returncode == 0 else None


def _prs(directory: Path | str, limit: int = 100, timeout: float = 20.0) -> list[dict[str, Any]]:
    """This repo's recent PRs through `gh` — the only thing that knows a squash merge happened.
    One page, newest first: a claim on a PR older than that window never resolves to `done` from
    here, which is the sort of gap `derived` is allowed to have. No `gh`, no auth, no network, not
    a GitHub repo: an empty list, and nothing is derived."""
    try:
        cp = subprocess.run(
            [
                "gh", "pr", "list",
                "--state", "all",
                "--json", "number,state,mergedAt,headRefName",
                "--limit", str(limit),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(directory),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return []
    if cp.returncode != 0:
        return []
    try:
        out = json.loads(cp.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [p for p in out if isinstance(p, dict)] if isinstance(out, list) else []


def merged_prs(directory: Path | str, limit: int = 100, timeout: float = 20.0) -> list[datetime] | None:
    """When each of the repo's recent PRs merged to its **default branch** (design §6 rule 3, a seat's
    `prs:` trigger), newest page only — or **None when `gh` could not be asked**, since for a count
    "no merges" and "could not look" must not read the same. A `directory` that is not one here (a
    node's checkout the home cannot see) is a failure to ask, not zero."""
    if not Path(directory).is_dir():
        return None
    try:
        cp = subprocess.run(
            ["gh", "repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
            capture_output=True, text=True, timeout=timeout, cwd=str(directory),
        )  # fmt: skip
        base = cp.stdout.strip() if cp.returncode == 0 else ""
        if not base:
            return None
        cp = subprocess.run(
            [
                "gh", "pr", "list",
                "--state", "merged",
                "--base", base,
                "--json", "mergedAt",
                "--limit", str(limit),
            ],
            capture_output=True, text=True, timeout=timeout, cwd=str(directory),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return None
    if cp.returncode != 0:
        return None
    try:
        out = json.loads(cp.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(out, list):
        return None
    times: list[datetime] = []
    for p in out:
        m = p.get("mergedAt") if isinstance(p, dict) else None
        try:
            times.append(datetime.fromisoformat(str(m).replace("Z", "+00:00")))
        except ValueError:
            continue
    return times


PR_WINDOWS = ledger.WINDOWS  # one set of windows for the ledger and the PRs


def _when(v: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
    except ValueError:
        return None


PR_FIELDS = "number,title,url,state,createdAt,closedAt,mergedAt,headRefName,headRefOid,author,isDraft"
PRECHECK_CONTEXT = "cadence/precheck"  # the commit status agent-cadence's `precheck.py` records (§4.12, TD-1033)


def prechecked(rollup: Any) -> bool:
    """Whether a `statusCheckRollup` carries a `PRECHECK_CONTEXT` status, whatever its state (TD-1036)."""
    return any(isinstance(c, dict) and c.get("context") == PRECHECK_CONTEXT for c in rollup or [])


# what a `done` reads of one PR (TD-637); `isCrossRepository`, whether it is a fork's (TD-1285)
PR_VIEW_FIELDS = "state,mergedAt,headRefOid,baseRefName,statusCheckRollup,isCrossRepository"
OPEN_PR_FIELDS = (
    f"{PR_FIELDS},statusCheckRollup,mergeStateStatus,baseRefName,isCrossRepository"  # the open read alone (TD-613)
)
# a sync PR (design §4.4 *A sync PR is the team's at once*, TD-684): its head branch as agent-cadence's
# `sync-all.sh` names it, and the lock among its changed files — or, a bump of a pin, the pin's file (TD-1015)
SYNC_BRANCH = "cadence-sync-"
SYNC_LOCK = cadence.LOCK
SYNC_PIN = cadence.PIN
JOB_URL = re.compile(r"/actions/runs/(\d+)/job/(\d+)")  # an Actions job's check run (`detailsUrl`, TD-686)
NOT_STARTED = "The job was not started because"  # GitHub's annotation on a job it never ran (TD-686)
GITHUB_ORIGIN = re.compile(r"(^|[@/])github\.com[:/]")  # a remote on GitHub, ssh or https (TD-686)
JOBS_CAP = 50  # failing jobs read per PR per head (design §4.4 *CI that never started*, TD-686)

RED_CONCLUSIONS = frozenset({"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"})
RED_STATES = frozenset({"FAILURE", "ERROR"})  # a commit status's (`StatusContext`) words for red


def failing_items(rollup: Any) -> tuple[list[dict[str, Any]], bool]:
    """The items of a `statusCheckRollup` that `fold_checks` calls failing, in order, and whether any
    still runs. Each item is `{name, run, job}`: `run` and `job` the ids of an Actions job's check run
    (`detailsUrl` `…/actions/runs/<run>/job/<job>`), None for a commit status or another check run."""
    if not isinstance(rollup, list):
        return [], False
    failing: list[dict[str, Any]] = []
    pending = False
    for c in rollup:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or c.get("context") or "")
        kind = c.get("__typename") or ("CheckRun" if "status" in c or "conclusion" in c else "StatusContext")
        if kind == "CheckRun":
            if str(c.get("status") or "COMPLETED").upper() != "COMPLETED":
                pending = True
            elif str(c.get("conclusion") or "").upper() in RED_CONCLUSIONS:
                m = JOB_URL.search(str(c.get("detailsUrl") or ""))
                failing.append({"name": name, "run": int(m[1]) if m else None, "job": int(m[2]) if m else None})
        else:  # a commit status (`StatusContext`)
            state = str(c.get("state") or "").upper()
            if state in RED_STATES:
                failing.append({"name": name, "run": None, "job": None})
            elif state != "SUCCESS":
                pending = True
    return failing, pending


def fold_checks(rollup: Any) -> tuple[str, list[str]]:
    """An open PR's `statusCheckRollup` folded into one word and the failing checks' names (design
    §4.4 *Repo facts*, TD-613): *red* when any check run concluded one of `RED_CONCLUSIONS` (failed,
    cancelled, timed out, waiting on an approval, never started) or a commit status reads one of
    `RED_STATES`, *pending* while any runs, *green* when all passed, *none* with no checks. Red outranks pending:
    one failed check is red however many still run."""
    if not isinstance(rollup, list) or not rollup:
        return "none", []
    items, pending = failing_items(rollup)
    return ("red" if items else "pending" if pending else "green"), [i["name"] for i in items]


# `ao pr wait`'s words and exit codes (design §4.7 *ao pr wait*, TD-940): `pending` is no word it
# returns, `gone` a number the reading does not hold
PR_WAIT_EXIT = {"green": 0, "red": 1, "conflicting": 2, "none": 3, "timeout": 4, "gone": 5}


def pr_wait_word(row: dict[str, Any]) -> str:
    """An open PR's row of the `prs` reading as one of `ao pr wait`'s words (TD-940): *conflicting*
    first — a PR that conflicts with its base gets no `pull_request` run, so its checks say nothing
    a wait could outlast — then *red* (a `not_run` one too: its CI never started), *green*, *none*,
    and *pending* while any check runs."""
    if row.get("conflicting"):
        return "conflicting"
    checks = str(row.get("checks") or "none")
    return "red" if checks in ("red", "not_run") else checks if checks in ("green", "pending") else "none"


def job_verdict(directory: Path | str, job: int, timeout: float) -> dict[str, Any] | None:
    """Whether Actions job `job` ever started (design §4.4 *CI that never started is the person's*,
    TD-686): `{started: False, reason, kind}` for a `completed` job with no steps, no runner and an
    annotation beginning `NOT_STARTED` (`kind` *billing* when it names account payments or a spending
    limit, else *other*), `{started: True}` for any other job — one cancelled while queued among them —
    and None for a job that could not be read, which is no evidence."""
    got, why = _gh_api(directory, f"repos/{{owner}}/{{repo}}/actions/jobs/{job}", timeout)
    if why is not None or not isinstance(got, dict):
        return None
    if str(got.get("status") or "") != "completed" or got.get("steps") or got.get("runner_name"):
        return {"started": True}
    notes, why = _gh_api(directory, f"repos/{{owner}}/{{repo}}/check-runs/{job}/annotations", timeout)
    if why is not None or not isinstance(notes, list):
        return None
    for a in notes:
        msg = str(a.get("message") or "").strip() if isinstance(a, dict) else ""
        if msg.startswith(NOT_STARTED):
            low = msg.lower()
            billing = "account payments" in low or "spending limit" in low
            return {"started": False, "reason": msg[:300], "kind": "billing" if billing else "other"}
    return {"started": True}


def _verdict_ok(v: Any) -> bool:
    """A kept verdict is `job_verdict`'s shape, else it is read again."""
    return isinstance(v, dict) and (v.get("started", True) is not False or bool(v.get("reason")))


def classify_failing(
    directory: Path | str, items: list[dict[str, Any]], head: str, old: dict[str, Any] | None, timeout: float
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    """A red PR's failing items read for jobs that never started (TD-686): `(not_run, failing, jobs)`.
    `not_run` is `{reason, kind, runs}` when **every** failing item is an Actions job that never
    started, else None; `failing` the names left once the not-started ones are out; `jobs` the
    verdicts kept by job id for `head` (`{head, read}`; `old`'s map only while its head is `head`). A
    commit status or another check run keeps the PR red with no read; the jobs are read in order, at
    most `JOBS_CAP`, stopping at the first that started or could not be read."""
    old = old if isinstance(old, dict) else {}
    ids = {str(i["job"]) for i in items if i["job"] is not None}  # an earlier attempt's jobs are not kept
    kept = old.get("read") if old.get("head") == head and isinstance(old.get("read"), dict) else {}
    read: dict[str, Any] = {k: v for k, v in kept.items() if k in ids and _verdict_ok(v)}
    names = [i["name"] for i in items]
    if not items or any(i["job"] is None for i in items):
        out = [i["name"] for i in items if i["job"] is None or (read.get(str(i["job"])) or {}).get("started", True)]
        return None, out, {"head": head, "read": read}
    gone: set[int] = set()
    whole = len(items) <= JOBS_CAP
    for i in items[:JOBS_CAP]:
        key = str(i["job"])
        v = read.get(key)
        if v is None and (v := job_verdict(directory, i["job"], timeout)) is not None:
            read[key] = v
        if v is None or v.get("started", True):
            whole = False
            break
        gone.add(i["job"])
    failing = [i["name"] for i in items if i["job"] not in gone]
    if not whole:
        return None, failing or names, {"head": head, "read": read}
    first = read[str(items[0]["job"])]
    runs = sorted({i["run"] for i in items if i["run"] is not None})
    return {"reason": first["reason"], "kind": first["kind"], "runs": runs}, [], {"head": head, "read": read}


def _gh_api(directory: Path | str, path: str, timeout: float) -> tuple[Any, str | None]:
    """One `gh api <path>` read as its JSON, or `(None, why)`; `why` begins *HTTP 404* for a 404."""
    try:
        cp = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=timeout, cwd=str(directory))
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"gh could not be asked: {type(e).__name__}"
    if cp.returncode != 0:
        last = ((cp.stderr or "").strip().splitlines() or ["gh api failed"])[-1][:200]
        return None, ("HTTP 404: " + last) if "HTTP 404" in last else last
    try:
        return json.loads(cp.stdout or "null"), None
    except json.JSONDecodeError:
        return None, "gh api printed something that is not JSON"


def required_checks(directory: Path | str, base: str, timeout: float = 30.0) -> list[str] | str:
    """The check names base branch `base` requires (design §4.8 *A `done` with a PR is told what its
    checks read*, TD-637): the union of its protection's required contexts and its rulesets'
    `required_status_checks`, sorted — or why it could not be read. A protection that answers *not
    protected* (or *not enabled*) requires none; an empty list is a base that requires nothing."""
    branch = quote(base, safe="")
    names: set[str] = set()
    path = f"repos/{{owner}}/{{repo}}/branches/{branch}/protection/required_status_checks"
    got, why = _gh_api(directory, path, timeout)
    if why is not None:
        if not (why.startswith("HTTP 404") and ("not protected" in why or "not enabled" in why)):
            return why
    elif isinstance(got, dict):
        names.update(str(c) for c in got.get("contexts") or [] if c)
        names.update(str(c["context"]) for c in got.get("checks") or [] if isinstance(c, dict) and c.get("context"))
    rules, why = _gh_api(directory, f"repos/{{owner}}/{{repo}}/rules/branches/{branch}", timeout)
    if why is not None:
        return why
    for r in rules if isinstance(rules, list) else []:
        if isinstance(r, dict) and r.get("type") == "required_status_checks":
            for c in (r.get("parameters") or {}).get("required_status_checks") or []:
                if isinstance(c, dict) and c.get("context"):
                    names.add(str(c["context"]))
    return sorted(names)


def _required_reading(
    directory: Path | str, bases: set[str], old: dict[str, Any] | None, timeout: float
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """`required` and `required_error` for the bases the open PRs name (TD-637): a read that failed
    keeps the last names with its error; a base never read is absent from `required`."""
    last = (old or {}).get("required") or {}
    required: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    for base in sorted(bases):
        got = required_checks(directory, base, timeout)
        if isinstance(got, str):
            errors[base] = got
            if isinstance(last.get(base), list):
                required[base] = last[base]
        else:
            required[base] = got
    return required, errors


def at_done(
    view: dict[str, Any], required: list[str] | None, verdicts: dict[str, Any] | None = None, precheck: bool = False
) -> dict[str, Any]:
    """What a `done` naming a PR is told (design §4.8 *A `done` with a PR is told what its checks
    read*, TD-637), from `gh pr view`'s `state,mergedAt,headRefOid,baseRefName,statusCheckRollup`
    and its base's required names (None: never read). `precheck`, the repo sets one (TD-1036):
    `PRECHECK_CONTEXT` joins a required set read, and an open head carrying none is still running it,
    named last in `running` with `precheck_absent` set. `{word, sha, failed, not_run, other}`: *merged*,
    *closed* (unmerged), *refused* (a required check red by `fold_checks`'s rule, named in `failed`),
    *not_run* (every red required check an Actions job that never started, by `verdicts` — `job_verdict`'s
    answers by job id — named in `not_run`, the first one's `{reason, kind}` as `not_run_why`, TD-686),
    *pending* (a required one not completed, named in `running`), else *green* — no checks at all
    included; `other` the red checks no rule requires. A real failure wins over `not_run`, and
    `not_run` over *pending*. With nothing required, or the set never read, every check counts."""
    out: dict[str, Any] = {
        "sha": str(view.get("headRefOid") or ""), "failed": [], "not_run": [], "other": [], "running": [],
    }  # fmt: skip
    state = str(view.get("state") or "").upper()
    if state == "MERGED" or view.get("mergedAt"):
        return {**out, "word": "merged"}
    if state == "CLOSED":
        return {**out, "word": "closed"}
    wanted = set(required or [])
    if wanted and precheck:
        wanted.add(PRECHECK_CONTEXT)
    verdicts = verdicts if isinstance(verdicts, dict) else {}
    for c in view.get("statusCheckRollup") or []:
        if not isinstance(c, dict):
            continue
        word, failing = fold_checks([c])
        if wanted and str(c.get("name") or c.get("context") or "") not in wanted:
            out["other"].extend(failing)
        elif word == "red":
            item = failing_items([c])[0][0]
            v = verdicts.get(str(item["job"])) if item["job"] is not None else None
            if isinstance(v, dict) and v.get("started", True) is False:
                out["not_run"].append(item["name"])
                out.setdefault("not_run_why", {"reason": v.get("reason") or "", "kind": v.get("kind") or "other"})
            else:
                out["failed"].append(item["name"])
        elif word == "pending":
            out["running"].append(str(c.get("name") or c.get("context") or "?"))
    if precheck and not prechecked(view.get("statusCheckRollup")):
        out["running"].append(PRECHECK_CONTEXT)  # after the fold: a failure and a run never started outrank it
        out["precheck_absent"] = True
    if out["failed"]:
        return {**out, "word": "refused"}
    if out["not_run"]:
        return {**out, "word": "not_run"}
    return {**out, "word": "pending" if out["running"] else "green"}


def done_verdicts(
    directory: Path | str, view: dict[str, Any], required: list[str] | None, kept: dict[str, Any] | None, timeout: float
) -> dict[str, Any]:
    """The verdicts `at_done` reads for PR view `view` (design §4.4 *A `done`'s read*, TD-686), by job id:
    `kept` — the repo reading's `jobs` for the PR — when its `head` is the view's, then, in a repo whose
    `origin` is GitHub, the failing *required* Actions jobs it lacks read with `job_verdict`, in order, at
    most `JOBS_CAP`, stopping at the first that started or could not be read. A read that fails is no
    evidence: the job stays failed."""
    head = str(view.get("headRefOid") or "")
    if str(view.get("state") or "").upper() != "OPEN" or view.get("mergedAt"):
        return {}  # merged or closed: `at_done` reads no check of it
    kept = kept if isinstance(kept, dict) else {}
    read: dict[str, Any] = dict(kept.get("read") or {}) if head and kept.get("head") == head else {}
    read = {k: v for k, v in read.items() if _verdict_ok(v)}
    wanted = set(required or [])
    items = [i for i in failing_items(view.get("statusCheckRollup"))[0] if not wanted or i["name"] in wanted]
    if not items or any(i["job"] is None for i in items):
        return read  # a commit status or another check run fails as it is: nothing to read
    todo = [i for i in items if str(i["job"]) not in read]
    if not todo or not GITHUB_ORIGIN.search(git_origin(directory)):
        return read
    if any(read[str(i["job"])].get("started", True) for i in items if str(i["job"]) in read):
        return read  # one started already: the PR is red whatever the rest say
    for i in todo[:JOBS_CAP]:
        v = job_verdict(directory, i["job"], timeout)
        if v is None:
            break
        read[str(i["job"])] = v
        if v.get("started", True):
            break
    return read


def git_origin(directory: Path | str) -> str:
    """The checkout's `origin` URL, or "" when it has none or git cannot say."""
    return (_git(directory, "remote", "get-url", "origin") or "").strip()


GITHUB_OWNER = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/\s]+@)?github\.com[:/]+([^/\s]+)/", re.I)
LOGIN = re.compile(r"[A-Za-z0-9-]+")


def github_owner(url: str | None) -> str | None:
    """The org or user a GitHub `origin` (ssh or https) or PR URL names, when it is a GitHub login
    (`[A-Za-z0-9-]+`), else None (design §4.4 *The person is told once per account*, TD-686)."""
    m = GITHUB_OWNER.search(str(url or ""))
    return m[1] if m and LOGIN.fullmatch(m[1]) else None


def pr_view(directory: Path | str, pr: int, timeout: float = 30.0) -> dict[str, Any] | str:
    """`gh pr view <pr>` with the fields `at_done` reads, or why it could not be read (TD-637)."""
    try:
        cp = subprocess.run(
            ["gh", "pr", "view", str(pr), "--json", PR_VIEW_FIELDS],
            capture_output=True, text=True, timeout=timeout, cwd=str(directory),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"gh could not be asked: {type(e).__name__}"
    if cp.returncode != 0:
        return ((cp.stderr or "").strip().splitlines() or ["gh pr view failed"])[-1][:200]
    try:
        out = json.loads(cp.stdout or "{}")
    except json.JSONDecodeError:
        return "gh pr view printed something that is not JSON"
    return out if isinstance(out, dict) else "gh pr view printed something that is not an object"


def run_status(directory: Path | str, run: int, timeout: float = 30.0) -> str | None:
    """An Actions run's `status` (`queued`, `in_progress`, `completed`, …) by `gh api
    repos/{owner}/{repo}/actions/runs/<run>` from the checkout, or None when it could not be read
    (design §4.4 *A Re-run's runs are read*, TD-687)."""
    try:
        cp = subprocess.run(
            ["gh", "api", f"repos/{{owner}}/{{repo}}/actions/runs/{int(run)}", "--jq", ".status"],
            capture_output=True, text=True, timeout=timeout, cwd=str(directory),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    status = (cp.stdout or "").strip()
    return status if cp.returncode == 0 and status and status != "null" else None


def run_rerun(directory: Path | str, run: int, timeout: float = 30.0) -> str | None:
    """`gh run rerun <run> --failed` from the checkout (design §4.5a *Inbox row: CI not starting*'s
    **Re-run**, TD-687): None when GitHub took it, else why not, in one line."""
    try:
        cp = subprocess.run(
            ["gh", "run", "rerun", str(int(run)), "--failed"],
            capture_output=True, text=True, timeout=timeout, cwd=str(directory),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return f"gh could not be asked: {type(e).__name__}"
    if cp.returncode != 0:
        return ((cp.stderr or "").strip().splitlines() or ["gh run rerun failed"])[-1][:200]
    return None


def _gh_prs(
    directory: Path | str, args: list[str], timeout: float, fields: str = PR_FIELDS
) -> list[dict[str, Any]] | str:
    """One `gh pr list` read as the PR rows `pr_reading` keeps, or why it could not be made. Read
    with `OPEN_PR_FIELDS`, each row also carries `checks`, `failing` and `conflicting` (TD-613)."""
    try:
        cp = subprocess.run(
            ["gh", "pr", "list", *args, "--json", fields],
            capture_output=True, text=True, timeout=timeout, cwd=str(directory),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"gh could not be asked: {type(e).__name__}"
    if cp.returncode != 0:
        return ((cp.stderr or "").strip().splitlines() or ["gh pr list failed"])[-1][:200]
    try:
        out = json.loads(cp.stdout or "[]")
    except json.JSONDecodeError:
        return "gh pr list printed something that is not JSON"
    if not isinstance(out, list):
        return "gh pr list printed something that is not a list"
    prs: list[dict[str, Any]] = []
    for p in out:
        if not isinstance(p, dict) or not isinstance(p.get("number"), int):
            continue
        author = p.get("author")
        row = {
            "number": p["number"],
            "title": str(p.get("title") or ""),
            "url": str(p.get("url") or ""),
            "state": str(p.get("state") or "").lower(),  # open · closed · merged
            "branch": str(p.get("headRefName") or ""),
            "head": str(p.get("headRefOid") or ""),  # rule 10 reads an open PR's head here (TD-332)
            "base": str(p.get("baseRefName") or ""),  # whose required checks a `done` reads (TD-637)
            "author": str(author.get("login") or "") if isinstance(author, dict) else "",
            "draft": bool(p.get("isDraft")),
            "created": p.get("createdAt") or None,
            "closed": p.get("mergedAt") or p.get("closedAt") or None,
        }
        if fields == OPEN_PR_FIELDS:
            row["checks"], row["failing"] = fold_checks(p.get("statusCheckRollup"))
            row["prechecked"] = prechecked(p.get("statusCheckRollup"))  # `ao pr wait`'s *none* (TD-1036)
            if row["checks"] == "red":  # what `pr_reading` reads for jobs that never started (TD-686)
                row["failing_items"] = failing_items(p.get("statusCheckRollup"))[0]
            row["merge_state"] = str(p.get("mergeStateStatus") or "").upper()
            row["conflicting"] = row["merge_state"] == "DIRTY"
            row["fork"] = bool(p.get("isCrossRepository"))
        prs.append(row)
    return prs


def pr_files(directory: Path | str, pr: int, timeout: float) -> list[str] | str:
    """Every file an open PR changes, read whole — the forge's paginated list, never `gh pr view
    --json files`, which stops at 100 — or why it could not be read (TD-684)."""
    try:
        cp = subprocess.run(
            ["gh", "api", f"repos/{{owner}}/{{repo}}/pulls/{pr}/files", "--paginate", "--jq", ".[].filename"],
            capture_output=True, text=True, timeout=timeout, cwd=str(directory),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"gh could not be asked: {type(e).__name__}"
    if cp.returncode != 0:
        return ((cp.stderr or "").strip().splitlines() or ["gh api failed"])[-1][:200]
    return [line.strip() for line in (cp.stdout or "").splitlines() if line.strip()]


def _sync_flag(directory: Path | str, p: dict[str, Any], was: dict[str, Any], timeout: float) -> None:
    """Sets `sync` on an open PR (design §4.4 *A sync PR is the team's at once*, TD-684): whether its
    branch is `SYNC_BRANCH`-named and `SYNC_LOCK` or `SYNC_PIN` among its files, and `sync_head`, the head its files
    were read at — once per head, the last reading's word kept while the head is the same. A read
    that failed keeps the last word and its head, so the next reading asks again; never read, no
    flag. Not a candidate: neither."""
    if not p["branch"].startswith(SYNC_BRANCH):
        return
    if isinstance(was.get("sync"), bool) and (was.get("sync_head") == p["head"] or not p["head"]):
        p["sync"], p["sync_head"] = was["sync"], was.get("sync_head")
        return
    files = pr_files(directory, p["number"], timeout)
    if not isinstance(files, str):
        p["sync"], p["sync_head"] = SYNC_LOCK in files or SYNC_PIN in files, p["head"]
    elif isinstance(was.get("sync"), bool):
        p["sync"], p["sync_head"] = was["sync"], was.get("sync_head")


def _held_flags(
    directory: Path | str,
    prs: list[dict[str, Any]],
    olds: dict[Any, dict[str, Any]],
    key: list[str] | None,
    timeout: float,
) -> None:
    """Sets `held` on the open PRs (design §4.4 *A held PR nobody asked is marked, never ordered*,
    TD-789): the changed files `key`'s globs name (`held.match`), with `held_head` and `held_key`, the
    head and the key they were read at — carried from `olds` as `sync_head` is, and read again for a
    changed head or key. A sync PR is never read; a draft is. At most `held.HELD_READS` reads, of
    the rows never read or read at another head or key, oldest first. A read that failed keeps the
    last word, and a PR never read carries no `held`. No key (None, or empty): nothing is read, and
    the last word is kept, so a repo whose readers are gone keeps its key and its `held`."""
    todo = []
    for p in prs:
        if p.get("sync"):
            continue
        was = olds.get(p["number"]) or {}
        if isinstance(was.get("held"), list):
            p["held"], p["held_head"], p["held_key"] = was["held"], was.get("held_head"), was.get("held_key")
        if key and p["head"] and (p.get("held_head"), p.get("held_key")) != (p["head"], key):
            todo.append(p)
    todo.sort(key=lambda p: p["created"] or "")
    for p in todo[: held.HELD_READS]:
        files = pr_files(directory, p["number"], timeout)
        if not isinstance(files, str):
            p["held"], p["held_head"], p["held_key"] = held.match(files, key or []), p["head"], list(key or [])


def _gh_counts(directory: Path | str, now: datetime, timeout: float) -> dict[str, dict[str, int]] | str:
    """Each window's PRs *opened* (`created` in it) and *closed* (`closed` in it, a merge being one)
    as GitHub counts them — `issueCount` of one search per window and word, six in one GraphQL
    request, the repo the checkout's (`{owner}/{repo}`, which `gh api` fills in) — or why it could not
    be read (TD-625). A count, not a list: `gh pr list --search` stops at 1000 results, so a busy
    month's list is a floor."""
    keys = {f"{w}_{word}": (w, word) for w in PR_WINDOWS for word in ("opened", "closed")}
    query = "query({}){{{}}}".format(
        ",".join(f"${k}:String!" for k in keys),
        " ".join(f"{k}:search(query:${k},type:ISSUE){{issueCount}}" for k in keys),
    )
    fields: list[str] = []
    for k, (w, word) in keys.items():
        start = (now - PR_WINDOWS[w]).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        qualifier = "created" if word == "opened" else "closed"
        fields += ["-F", f"{k}=repo:{{owner}}/{{repo}} is:pr {qualifier}:>{start}"]
    try:
        cp = subprocess.run(
            ["gh", "api", "graphql", "-f", f"query={query}", *fields],
            capture_output=True, text=True, timeout=timeout, cwd=str(directory),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"gh could not be asked: {type(e).__name__}"
    if cp.returncode != 0:
        return ((cp.stderr or "").strip().splitlines() or ["gh api graphql failed"])[-1][:200]
    try:
        data = (json.loads(cp.stdout or "{}") or {}).get("data") or {}
    except (json.JSONDecodeError, AttributeError):
        return "gh api graphql printed something that is not JSON"
    windows: dict[str, dict[str, int]] = {w: {} for w in PR_WINDOWS}
    for k, (w, word) in keys.items():
        n = (data.get(k) or {}).get("issueCount") if isinstance(data, dict) else None
        if not isinstance(n, int):
            return f"gh api graphql gave no count for {k}"
        windows[w][word] = n
    return windows


# The forge a checkout's origin names (design §4.4 *Repo facts*, TD-940), as the cadence's `forge.py`
# picks it by host (TD-104): github.com is GitHub, gitlab.com or a host whose first label is `gitlab`
# is GitLab; an origin with no host (a local path, `file://`: every test fixture) is read as GitHub,
# as before; anything else is a forge with no reading
_REMOTE_URL = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*)://(?:[^@/]*@)?([^/:]*)(?::\d*)?(/.*)?")
_REMOTE_SCP = re.compile(r"[^/@:]+@([^/:]+):(.*)")
# a head pipeline's status as one of the fold's words (GitLab's `Ci::Pipeline` statuses): `manual` is a
# pipeline stopped on a job a person must press, which GitHub's fold reads as red (`ACTION_REQUIRED`)
PIPELINE_WORD = {
    "success": "green",
    "failed": "red",
    "canceled": "red",
    "manual": "red",
    "skipped": "none",
    **dict.fromkeys(
        (
            "created",
            "waiting_for_resource",
            "preparing",
            "waiting_for_callback",
            "pending",
            "running",
            "canceling",
            "scheduled",
        ),
        "pending",
    ),
}
GITLAB_UNREAD = "windows, recent and held are not read on GitLab: its open MRs alone, each with its required jobs"


def forge_of(remote: str) -> tuple[str, str]:
    """`(forge, where)` of an origin URL (TD-940): `("github", "")`; `("gitlab", "<host>/<group/…/repo>")`;
    `("other", <host>)` for any other host, or a GitLab origin naming no project — read through `gh`,
    which answers for a GitHub Enterprise host and fails in its own words for anything else."""
    raw = (remote or "").strip()
    if m := _REMOTE_URL.fullmatch(raw):
        if m[1].lower() == "file":
            return "github", ""
        host, path = m[2].lower(), m[3] or ""
    elif m := _REMOTE_SCP.fullmatch(raw):
        host, path = m[1].lower(), m[2]
    else:
        return "github", ""  # a local path: `gh` answers or fails on its own, as before
    if not host or host == "github.com":
        return "github", ""
    if host == "gitlab.com" or host.split(".", 1)[0] == "gitlab":
        slug = re.sub(r"\.git$", "", path.strip("/"))
        return ("gitlab", f"{host}/{slug}") if re.fullmatch(r"[^/]+(/[^/]+)+", slug) else ("other", host)
    return "other", host


def fold_pipeline(mr: dict[str, Any]) -> tuple[str, list[str]]:
    """A merge request's head pipeline folded into `fold_checks`'s words (TD-940): *none* with no
    pipeline, else `PIPELINE_WORD` of its status (an unknown status *pending*: a status GitLab adds
    later is never read as settled), and a red one's failing name `pipeline <id>`."""
    pipe = mr.get("head_pipeline")
    if not isinstance(pipe, dict) or not pipe:
        return "none", []
    word = PIPELINE_WORD.get(str(pipe.get("status") or "").lower(), "pending")
    return word, [f"pipeline {pipe.get('id')}"] if word == "red" else []


def _glab_api(directory: Path | str, host: str, path: str, timeout: float) -> tuple[Any, str | None]:
    """One `glab api --hostname <host> <path>` read as its JSON, or `(None, why)` — `_gh_api`'s shape."""
    try:
        cp = subprocess.run(
            ["glab", "api", "--hostname", host, path],
            capture_output=True, text=True, timeout=timeout, cwd=str(directory),
            env={**os.environ, "NO_PROMPT": "1", "GLAB_NO_PROMPT": "1"},
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"glab could not be asked: {type(e).__name__}"
    if cp.returncode != 0:
        return None, ((cp.stderr or "").strip().splitlines() or ["glab api failed"])[-1][:200]
    try:
        return json.loads(cp.stdout or "null"), None
    except json.JSONDecodeError:
        return None, "glab api printed something that is not JSON"


def _gitlab_reading(directory: Path | str, where: str, now: datetime, timeout: float, old: dict[str, Any] | None):
    """A GitLab origin's PR reading (TD-940): its open merge requests, oldest first, each one GET for
    its head pipeline (`fold_pipeline`) and merge status — `conflicting` when `has_conflicts` or
    `detailed_merge_status` is *conflict* — in GitHub's row shape, `red_since` kept as `pr_reading`
    keeps it, and `required` on the row: the head pipeline's jobs with `allow_failure` false
    (`required_error` when they could not be read); `unread` says what else is not read here. A read
    that could not be made is `{"error"}`."""
    host, _, path = where.partition("/")
    project = f"projects/{quote(path, safe='')}"
    got, why = _glab_api(
        directory, host, f"{project}/merge_requests?state=opened&order_by=created_at&sort=asc&per_page=100", timeout
    )
    if why is not None:
        return {"error": why}
    if not isinstance(got, list):
        return {"error": "glab api printed something that is not a list"}
    olds = {p.get("number"): p for p in (old or {}).get("open") or [] if isinstance(p, dict)}
    open_: list[dict[str, Any]] = []
    for m in got:
        if not isinstance(m, dict) or not isinstance(m.get("iid"), int):
            continue
        one, why = _glab_api(directory, host, f"{project}/merge_requests/{m['iid']}", timeout)
        if why is not None:
            return {"error": why}
        mr = {**m, **one} if isinstance(one, dict) else m
        author = mr.get("author")
        row: dict[str, Any] = {
            "number": mr["iid"],
            "title": str(mr.get("title") or ""),
            "url": str(mr.get("web_url") or ""),
            "state": "open",
            "branch": str(mr.get("source_branch") or ""),
            "head": str(mr.get("sha") or ""),
            "base": str(mr.get("target_branch") or ""),
            "author": str(author.get("username") or "") if isinstance(author, dict) else "",
            "draft": bool(mr.get("draft") or mr.get("work_in_progress")),
            "created": mr.get("created_at") or None,
            "closed": None,
            "fork": mr.get("source_project_id") not in (None, mr.get("target_project_id")),
        }
        row["checks"], row["failing"] = fold_pipeline(mr)
        pipe = mr.get("head_pipeline")
        if isinstance(pipe, dict) and pipe.get("id") is not None:
            # GitLab's required checks are the head pipeline's jobs that may not fail: per MR, not per base
            jobs, why = _glab_api(directory, host, f"{project}/pipelines/{pipe['id']}/jobs?per_page=100", timeout)
            if why is None and isinstance(jobs, list):
                if len(jobs) >= 100:  # one page: a pipeline of more jobs may require one past it
                    row["required_cut"] = True
                row["required"] = sorted(
                    {
                        str(j.get("name"))
                        for j in jobs
                        if isinstance(j, dict) and j.get("name") and not j.get("allow_failure")
                    }
                )
            else:
                row["required_error"] = why or "glab api printed something that is not a list"
        row["conflicting"] = bool(mr.get("has_conflicts")) or str(mr.get("detailed_merge_status") or "") == "conflict"
        if row["checks"] == "red" or row["conflicting"]:
            was = olds.get(row["number"]) or {}
            row["red_since"] = was.get("red_since") or now.isoformat()
        open_.append(row)
    return {"open": open_, "forge": "gitlab", "unread": GITLAB_UNREAD, "at": now.isoformat()}


def pr_reading(
    directory: Path | str,
    now: datetime,
    limit: int = 1000,
    timeout: float = 30.0,
    old: dict[str, Any] | None = None,
    held: list[str] | None = None,
    remote: str = "",
) -> dict[str, Any]:
    """The repo's pull requests as the Repo facet counts them (design §4.4 *Repo facts*, TD-176): three
    `gh` reads — the open PRs, every PR updated in the longest window, and the windows' counts — kept as `open` (oldest
    first), `windows` (`{day|week|month: {opened, closed}}`: `createdAt` in the window is an
    opening, `closedAt` or `mergedAt` a close, a merge being one) and `recent` (every PR opened or
    closed in the longest window, newest first, at most `limit` of them: `recent_cut` when the read
    filled it). The window counts are GitHub's own totals (`_gh_counts`), never the list's length:
    its search stops at 1000 results whatever the limit (TD-625). **A read that could not be made is `{"error":
    why}`**, never an empty reading: for a count, *no PRs* and *could not look* must not read the
    same — `merged_prs`'s rule, not `_prs`'s. Each open PR carries `checks`, `failing`, `conflicting`
    and, while it is red or conflicting, `red_since`: the first reading that saw it so, taken from
    `old` (the last reading) by number and dropped the reading it is neither (TD-613); `fork`, whether
    its head is another repository's; and on a `cadence-sync-*` branch `sync`, whether it is a sync PR
    (`_sync_flag`), and for one `sync_since`, the first reading that saw it open, kept as `red_since`
    is (TD-684). In a repo whose `origin` is GitHub, a red PR whose failing items all are Actions jobs
    that never started reads `checks: not_run` with `not_run: {reason, kind, runs}`, and every red one
    keeps its jobs' verdicts as `jobs` (`classify_failing`, TD-686). `held` is the repo's held key
    (`held.repo_key`): each open PR but a sync PR carries `held`, the paths of it the key names, read
    once per head and key (`_held_flags`, TD-789). `remote` is the checkout's origin URL: on GitLab
    the reading is `_gitlab_reading`'s, on another forge an error (`forge_of`, TD-940)."""
    if not Path(directory).is_dir():
        return {"error": f"{directory} is not a directory here"}
    forge, where = forge_of(remote)  # the origin the caller read; none given reads as GitHub
    if forge == "gitlab":  # the fold per forge (TD-940): a GitLab origin's open MRs, nothing more yet
        return _gitlab_reading(directory, where, now, timeout, old)
    # another host is read through `gh` as before: a GitHub Enterprise origin answers, any other fails in
    # gh's own words (the cadence's `forge` setting is not read here: forge.py is the cadence's)
    since = now - PR_WINDOWS["month"]
    open_ = _gh_prs(directory, ["--state", "open", "--limit", "200"], timeout, OPEN_PR_FIELDS)
    if isinstance(open_, str):
        return {"error": open_}
    olds = {p.get("number"): p for p in (old or {}).get("open") or [] if isinstance(p, dict)}
    origin: list[str] = []  # read once, and only for a red PR with an Actions job among its failing items
    for p in open_:
        # gh says UNKNOWN while it recomputes the merge state (just after a push): keep the last word
        if p.pop("merge_state", "") == "UNKNOWN" and olds.get(p["number"], {}).get("conflicting"):
            p["conflicting"] = True
        items = p.pop("failing_items", None)
        if items and any(i["job"] for i in items):
            origin = origin or [_git(directory, "remote", "get-url", "origin") or ""]
        if items and GITHUB_ORIGIN.search((origin or [""])[0]):
            not_run, failing, p["jobs"] = classify_failing(
                directory, items, p["head"], olds.get(p["number"], {}).get("jobs"), timeout
            )
            if not_run:
                p["checks"], p["not_run"] = "not_run", not_run
            p["failing"] = failing
        if p["checks"] == "red" or p["conflicting"]:
            was = olds.get(p["number"]) or {}
            # a `not_run` one is red by its conflict alone: a red spell's hour is not the conflict's (TD-686)
            kept = was.get("red_since") if p["checks"] == "red" or was.get("conflicting") else None
            p["red_since"] = kept or now.isoformat()
        was = olds.get(p["number"]) or {}
        _sync_flag(directory, p, was, timeout)
        if p.get("sync"):
            # one waiting on CI that never started counts from the reading it conflicts (TD-686)
            waits = p["checks"] == "not_run" and not p["conflicting"]
            p["sync_since"] = (not waits and was.get("sync_since")) or now.isoformat()
    _held_flags(directory, open_, olds, held, timeout)
    day = since.date().isoformat()
    prs = _gh_prs(directory, ["--state", "all", "--search", f"updated:>={day}", "--limit", str(limit)], timeout)
    if isinstance(prs, str):
        return {"error": prs}
    windows = _gh_counts(directory, now, timeout)
    if isinstance(windows, str):
        return {"error": windows}
    recent = [p for p in prs if ((t := _when(p["created"])) and t > since) or ((c := _when(p["closed"])) and c > since)]
    recent.sort(key=lambda p: max(filter(None, (_when(p["created"]), _when(p["closed"])))), reverse=True)
    open_.sort(key=lambda p: p["created"] or "")
    out = {"open": open_, "windows": windows, "recent": recent, "at": now.isoformat()}
    # each open PR's base branch's required check names (TD-637), read where the PRs are
    out["required"], errors = _required_reading(directory, {p["base"] for p in open_ if p["base"]}, old, timeout)
    if errors:
        out["required_error"] = errors
    return {**out, "recent_cut": True} if len(prs) >= limit else out


def _prs_for_head(directory: Path | str, branch: str, timeout: float = 10.0) -> list[dict[str, Any]] | None:
    """The PRs whose head is exactly `branch`, or **None when `gh` could not be asked**.

    The distinction matters only here. Retirement is the one delete in the report channels (TD-045),
    and `_prs`'s "any failure is an empty list" contract — right for a source that only ever fills
    things in — would turn a `gh` outage, a lapsed token or an offline laptop into "that branch
    never had a PR", deleting a live claim on every session at once (found by the PR #126 review).
    Asking by name closes the other half of the same hole: a PR older than the single page `_prs`
    fetches is found here, where for the fill-in half it was only ever a delay."""
    try:
        cp = subprocess.run(
            [
                "gh", "pr", "list",
                "--head", branch,
                "--state", "all",
                "--json", "number,state,mergedAt,headRefName",
                "--limit", "20",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(directory),
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return None
    if cp.returncode != 0:
        return None
    try:
        out = json.loads(cp.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return [x for x in out if isinstance(x, dict)] if isinstance(out, list) else None


def _default_ref(directory: Path | str) -> str | None:
    for ref in DEFAULT_REFS:
        if _git(directory, "rev-parse", "--verify", "-q", ref) is not None:
            return ref
    return None


def _ledger_rows_on_main(directory: Path | str, pr: int, rel: str) -> list[str]:
    """The ledger references a merged PR added to main, from its squash-merge commit, the ledger at `rel` read
    there through `ledger.layout_at` (§4.4 *Either layout*): a v1 file's added headings and rows; a v2
    directory's `TD-NNN.md` files added directly under it (`--no-renames`, so a move into `archive/` adds
    nothing there, and a file added straight into `archive/` is not counted), none for the commit that adds
    its `README.md` (the split). Empty unless
    that commit is in this clone's `origin/<default>` — a clone that has not fetched since the merge
    simply derives nothing yet."""
    base = _default_ref(directory)
    if base is None:
        return []
    sha = _git(directory, "log", base, "-n", "1", "--format=%H", "-F", f"--grep=(#{pr})")
    if not (sha := (sha or "").strip()):
        return []
    io = ledger.git_io(directory, sha, ledger.common_parent(rel), rel=rel)
    rel = ledger.layout_at(rel, None, io)[0] if io is not None else rel  # a carried path from before a split
    if io is not None and io[0](rel) is not None:
        # a v2 directory: the entry files the commit adds directly under it; none for the split (its README)
        names = _git(directory, "show", "--format=", "--no-renames", "--name-status", sha, "--", rel) or ""
        added = [p for st, _, p in (x.partition("\t") for x in names.splitlines()) if st == "A"]
        if f"{rel}/{lb.LEDGER_README}" in added:
            return []
        files = (p.rpartition("/") for p in added)
        return list(
            dict.fromkeys(
                normalize_ref(m.group(0)[:-3]) for d, _, n in files if d == rel and (m := lb.ENTRY_FILE_RE.match(n))
            )
        )
    diff = _git(directory, "show", "--format=", "-U0", sha, "--", rel)
    if not diff:
        return []
    # a row the ledger gained: an entry's heading, or its row in the summary table (ledgerboard's predicates)
    added = (line[1:] for line in diff.splitlines() if line.startswith("+"))
    rows = [normalize_ref(tid) for line in added if (tid := lb.entry_id(line) or lb.row_id(line))]
    return list(dict.fromkeys(rows))
