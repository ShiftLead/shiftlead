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

from sessionorc import ledger
from sessionorc.models import PR_CLOSED, FindingEntry, ProgressEntry, normalize_ref

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sessionorc.models import Session

# A work branch is named for its ledger reference (cadence §4: `tdNNN-<slug>`). Only that one shape
# is read: anything looser would turn `release-2` and `ui-3-fix` into ledger references.
BRANCH_RE = re.compile(r"^td-?(\d{1,4})(?:[-_].*)?$", re.IGNORECASE)
# A row the ledger gained: an entry body's heading, or its row in the summary table.
LEDGER_ROW_RE = re.compile(r"^\+(?:#{1,4}\s*(TD-\d+)|\|\s*(TD-\d+)\s*\|)", re.IGNORECASE | re.MULTILINE)
LEDGER_DEFAULT = "docs/technical_debt.md"  # §5's `ledger:` key overrides it per record (`Session.ledger`)
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
        if s.dir and s.state != "closed":
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
OPEN_PR_FIELDS = f"{PR_FIELDS},statusCheckRollup,mergeStateStatus"  # the open read alone (TD-613)

RED_CONCLUSIONS = frozenset({"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"})
RED_STATES = frozenset({"FAILURE", "ERROR"})  # a commit status's (`StatusContext`) words for red


def fold_checks(rollup: Any) -> tuple[str, list[str]]:
    """An open PR's `statusCheckRollup` folded into one word and the failing checks' names (design
    §4.4 *Repo facts*, TD-613): *red* when any check run concluded one of `RED_CONCLUSIONS` (failed,
    cancelled, timed out, waiting on an approval, never started) or a commit status reads one of
    `RED_STATES`, *pending* while any runs, *green* when all passed, *none* with no checks. Red outranks pending:
    one failed check is red however many still run."""
    if not isinstance(rollup, list) or not rollup:
        return "none", []
    failing: list[str] = []
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
                failing.append(name)
        else:  # a commit status (`StatusContext`)
            state = str(c.get("state") or "").upper()
            if state in RED_STATES:
                failing.append(name)
            elif state != "SUCCESS":
                pending = True
    return ("red" if failing else "pending" if pending else "green"), failing


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
            "author": str(author.get("login") or "") if isinstance(author, dict) else "",
            "draft": bool(p.get("isDraft")),
            "created": p.get("createdAt") or None,
            "closed": p.get("mergedAt") or p.get("closedAt") or None,
        }
        if fields == OPEN_PR_FIELDS:
            row["checks"], row["failing"] = fold_checks(p.get("statusCheckRollup"))
            row["merge_state"] = str(p.get("mergeStateStatus") or "").upper()
            row["conflicting"] = row["merge_state"] == "DIRTY"
        prs.append(row)
    return prs


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


def pr_reading(
    directory: Path | str,
    now: datetime,
    limit: int = 1000,
    timeout: float = 30.0,
    old: dict[str, Any] | None = None,
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
    `old` (the last reading) by number and dropped the reading it is neither (TD-613)."""
    if not Path(directory).is_dir():
        return {"error": f"{directory} is not a directory here"}
    since = now - PR_WINDOWS["month"]
    open_ = _gh_prs(directory, ["--state", "open", "--limit", "200"], timeout, OPEN_PR_FIELDS)
    if isinstance(open_, str):
        return {"error": open_}
    olds = {p.get("number"): p for p in (old or {}).get("open") or [] if isinstance(p, dict)}
    for p in open_:
        # gh says UNKNOWN while it recomputes the merge state (just after a push): keep the last word
        if p.pop("merge_state", "") == "UNKNOWN" and olds.get(p["number"], {}).get("conflicting"):
            p["conflicting"] = True
        if p["checks"] == "red" or p["conflicting"]:
            p["red_since"] = olds.get(p["number"], {}).get("red_since") or now.isoformat()
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


def _ledger_rows_on_main(directory: Path | str, pr: int, ledger: str) -> list[str]:
    """The ledger references a merged PR added to main, from its squash-merge commit. Empty unless
    that commit is in this clone's `origin/<default>` — a clone that has not fetched since the merge
    simply derives nothing yet."""
    base = _default_ref(directory)
    if base is None:
        return []
    sha = _git(directory, "log", base, "-n", "1", "--format=%H", "-F", f"--grep=(#{pr})")
    if not (sha := (sha or "").strip()):
        return []
    diff = _git(directory, "show", "--format=", "-U0", sha, "--", ledger)
    if not diff:
        return []
    rows = [normalize_ref(m[1] or m[2]) for m in LEDGER_ROW_RE.finditer(diff)]
    return list(dict.fromkeys(rows))
