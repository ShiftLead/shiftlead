# ruff: noqa: E501 — the recorded API answers read as one line each
"""TD-686 slice 1, design §4.4 *CI that never started is the person's, not a lane's*: the PR reading
tells an Actions job that never started from a red one (`checks: not_run`, `not_run: {reason, kind,
runs}`, the verdicts kept by job id per head), and no reader of `checks` takes `not_run` for red."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from sessionorc import reports, workorders

pytestmark = pytest.mark.unit

T0 = datetime(2026, 10, 14, 16, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)

# Recorded 2026-10-14 from ContractMatch/samscrape #1097 (`gh pr view --json statusCheckRollup`,
# `gh api …/actions/jobs/115939556123`, `gh api …/check-runs/115939556123/annotations`), trimmed.
BILLING = "The job was not started because recent account payments have failed or your spending limit needs to be increased. Please check the 'Billing & plans' section in your settings"
RUN = 38589294456


def _check(job: int, name: str, conclusion: str = "FAILURE", run: int = RUN) -> dict:
    return {
        "__typename": "CheckRun",
        "completedAt": "2026-10-14T15:26:19Z",
        "conclusion": conclusion,
        "detailsUrl": f"https://github.com/ContractMatch/samscrape/actions/runs/{run}/job/{job}",
        "name": name,
        "startedAt": "2026-10-14T15:26:16Z",
        "status": "COMPLETED",
        "workflowName": "CI",
    }


def _job(job: int, run: int = RUN, steps: list | None = None, runner: str = "") -> dict:
    return {
        "completed_at": "2026-10-14T15:26:19Z",
        "conclusion": "failure",
        "id": job,
        "labels": ["ubuntu-latest"],
        "name": "Lint",
        "run_id": run,
        "runner_id": 0,
        "runner_name": runner,
        "started_at": "2026-10-14T15:26:16Z",
        "status": "completed",
        "steps": steps or [],
    }


def _notes(message: str = BILLING) -> list:
    return [
        {"path": ".github", "annotation_level": "failure", "title": "", "message": message, "raw_details": ""},
        {
            "path": ".github",
            "annotation_level": "notice",
            "title": "",
            "message": '"The ubuntu-latest label will migrate to Ubuntu 26 beginning October 19, 2026."',
            "raw_details": "",
        },
    ]


def _open(n: int, rollup: list, head: str = "a" * 40, **kw) -> dict:
    return {
        "number": n,
        "title": f"pr {n}",
        "url": f"https://x/{n}",
        "state": "OPEN",
        "createdAt": "2026-10-14T10:00:00Z",
        "headRefName": f"b{n}",
        "headRefOid": head,
        "baseRefName": "main",
        "author": {"login": "eye"},
        "isDraft": False,
        "statusCheckRollup": rollup,
        "mergeStateStatus": "CLEAN",
        **kw,
    }


def _fake(
    monkeypatch, open_prs: list, jobs: dict, notes: dict, origin: str = "git@github.com:ContractMatch/samscrape.git"
):
    """`gh` and `git` as the reading calls them: `jobs`/`notes` by job id (a missing one answers 404)."""
    calls: list[list[str]] = []

    def run(argv, **kw):
        calls.append(argv)
        if argv[0] == "git":
            return subprocess.CompletedProcess(argv, 0, origin + "\n", "")
        if argv[1] == "pr":
            return subprocess.CompletedProcess(argv, 0, json.dumps(open_prs if "open" in argv else []), "")
        path = argv[2]
        if "/actions/jobs/" in path or "/check-runs/" in path:
            job = int(path.split("/")[-1] if "/actions/jobs/" in path else path.split("/")[-2])
            got = (jobs if "/actions/jobs/" in path else notes).get(job)
            if got is None:
                return subprocess.CompletedProcess(argv, 1, "", "gh: Not Found (HTTP 404)")
            return subprocess.CompletedProcess(argv, 0, json.dumps(got), "")
        if path == "graphql":
            fields = [argv[i + 1].split("=", 1)[0] for i, a in enumerate(argv) if a == "-F"]
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"data": {k: {"issueCount": 0} for k in fields}}), ""
            )
        return subprocess.CompletedProcess(argv, 0, "[]" if "/rules/" in path else "{}", "")

    monkeypatch.setattr(reports.subprocess, "run", run)
    return calls


def _job_reads(calls) -> list[int]:
    return [int(c[2].split("/")[-1]) for c in calls if c[0] == "gh" and "/actions/jobs/" in c[2]]


def _read(tmp_path, monkeypatch, prs, jobs, notes, old=None, now=T0, **kw):
    calls = _fake(monkeypatch, prs, jobs, notes, **kw)
    r = reports.pr_reading(tmp_path, now, old=old)
    return {p["number"]: p for p in r["open"]}, r, calls


def test_a_pr_whose_jobs_all_never_started_for_billing_reads_not_run(tmp_path, monkeypatch):
    pr = _open(1097, [_check(1, "Preflight"), _check(2, "Lint", run=RUN + 1), _check(3, "ok", "SUCCESS")])
    by, _, calls = _read(tmp_path, monkeypatch, [pr], {1: _job(1), 2: _job(2, RUN + 1)}, {1: _notes(), 2: _notes()})
    p = by[1097]
    assert (p["checks"], p["failing"]) == ("not_run", [])
    assert p["not_run"] == {"reason": BILLING, "kind": "billing", "runs": [RUN, RUN + 1]}
    assert "red_since" not in p  # no red spell, so no order and no hour counting
    assert p["jobs"] == {
        "head": "a" * 40,
        "read": {
            "1": {"started": False, "reason": BILLING, "kind": "billing"},
            "2": {"started": False, "reason": BILLING, "kind": "billing"},
        },
    }
    assert _job_reads(calls) == [1, 2]
    # still not_run whatever else is pending: the account blocks every run to come as well
    pending = _open(1097, [_check(1, "Preflight"), {**_check(9, "later"), "status": "QUEUED", "conclusion": ""}])
    by, _, _ = _read(tmp_path, monkeypatch, [pending], {1: _job(1)}, {1: _notes()})
    assert by[1097]["checks"] == "not_run"


def test_another_reason_is_kind_other(tmp_path, monkeypatch):
    why = "The job was not started because the workflow is disabled."
    by, _, _ = _read(tmp_path, monkeypatch, [_open(5, [_check(1, "Lint")])], {1: _job(1)}, {1: _notes(why)})
    assert by[5]["not_run"] == {"reason": why, "kind": "other", "runs": [RUN]}


def test_a_job_cancelled_while_queued_has_no_steps_and_no_runner_too_and_reads_red(tmp_path, monkeypatch):
    cancelled = _open(6, [_check(1, "Lint", "CANCELLED")])
    by, _, _ = _read(
        tmp_path, monkeypatch, [cancelled], {1: _job(1)}, {1: [{"message": "The operation was canceled."}]}
    )
    assert (by[6]["checks"], by[6]["failing"], by[6]["red_since"]) == ("red", ["Lint"], T0.isoformat())
    assert "not_run" not in by[6]
    # a job that ran (steps or a runner) is a real failure without reading its annotations
    by, _, calls = _read(
        tmp_path, monkeypatch, [_open(7, [_check(1, "Lint")])], {1: _job(1, runner="GitHub Actions 3")}, {}
    )
    assert by[7]["checks"] == "red" and not [c for c in calls if "/check-runs/" in str(c)]


def test_a_failing_commit_status_or_another_check_run_beside_a_not_started_job_keeps_it_red(tmp_path, monkeypatch):
    status = {"__typename": "StatusContext", "context": "ci/ext", "state": "FAILURE"}
    other = {**_check(2, "codecov"), "detailsUrl": "https://codecov.io/x"}
    for extra in (status, other):
        by, _, calls = _read(tmp_path, monkeypatch, [_open(8, [_check(1, "Lint"), extra])], {1: _job(1)}, {1: _notes()})
        assert by[8]["checks"] == "red" and by[8]["red_since"] == T0.isoformat()
        assert _job_reads(calls) == []  # red whatever the job says: nothing is read


def test_a_mix_with_one_real_failure_stays_red_and_leaves_the_not_started_names_out(tmp_path, monkeypatch):
    pr = _open(9, [_check(1, "Preflight"), _check(2, "test (3.13)"), _check(3, "Lint")])
    by, _, calls = _read(
        tmp_path,
        monkeypatch,
        [pr],
        {1: _job(1), 2: _job(2, steps=[{"name": "run"}]), 3: _job(3)},
        {1: _notes(), 3: _notes()},
    )
    assert (by[9]["checks"], by[9]["failing"]) == ("red", ["test (3.13)", "Lint"])
    assert _job_reads(calls) == [1, 2]  # the first job that started ends the read


def test_past_the_cap_with_none_started_stays_red(tmp_path, monkeypatch):
    n = reports.JOBS_CAP + 1
    pr = _open(10, [_check(j, f"job {j}") for j in range(1, n + 1)])
    by, _, calls = _read(
        tmp_path, monkeypatch, [pr], {j: _job(j) for j in range(1, n + 1)}, {j: _notes() for j in range(1, n + 1)}
    )
    assert by[10]["checks"] == "red" and by[10]["failing"] == [f"job {n}"]
    assert len(_job_reads(calls)) == reports.JOBS_CAP


def test_an_unreadable_job_is_no_evidence_and_is_not_kept(tmp_path, monkeypatch):
    pr = _open(11, [_check(1, "Lint")])
    by, first, _ = _read(tmp_path, monkeypatch, [pr], {}, {})
    assert by[11]["checks"] == "red" and by[11]["jobs"]["read"] == {}
    # the next reading tries it again, and this time it reads
    by, _, calls = _read(tmp_path, monkeypatch, [pr], {1: _job(1)}, {1: _notes()}, old=first, now=T0 + HOUR)
    assert by[11]["checks"] == "not_run" and _job_reads(calls) == [1]
    assert "red_since" not in by[11]  # the red spell ends the reading it turns not_run


def test_a_job_is_read_once_per_head_a_new_head_or_a_rerun_reads_afresh(tmp_path, monkeypatch):
    pr = _open(12, [_check(1, "Lint")])
    by, first, _ = _read(tmp_path, monkeypatch, [pr], {1: _job(1)}, {1: _notes()})
    _, second, calls = _read(tmp_path, monkeypatch, [pr], {}, {}, old=first)
    assert second["open"][0]["checks"] == "not_run" and _job_reads(calls) == []  # from the kept verdict
    # a Re-run's new attempt: new job ids on the same head
    rerun = _open(12, [_check(2, "Lint", run=RUN + 7)])
    _, third, calls = _read(
        tmp_path, monkeypatch, [rerun], {2: _job(2, RUN + 7, steps=[{"name": "x"}])}, {}, old=second
    )
    assert third["open"][0]["checks"] == "red" and _job_reads(calls) == [2]
    assert set(third["open"][0]["jobs"]["read"]) == {"2"}  # the earlier attempt's job is no longer kept
    # a new head replaces the map
    moved = _open(12, [_check(1, "Lint")], head="b" * 40)
    _, fourth, calls = _read(tmp_path, monkeypatch, [moved], {1: _job(1)}, {1: _notes()}, old=third)
    assert _job_reads(calls) == [1] and fourth["open"][0]["jobs"] == {
        "head": "b" * 40,
        "read": {"1": {"started": False, "reason": BILLING, "kind": "billing"}},
    }


def test_a_repo_whose_origin_is_not_github_reads_as_before(tmp_path, monkeypatch):
    by, _, calls = _read(
        tmp_path,
        monkeypatch,
        [_open(13, [_check(1, "Lint")])],
        {1: _job(1)},
        {1: _notes()},
        origin="git@gitlab.com:x/y.git",
    )
    assert by[13]["checks"] == "red" and "jobs" not in by[13] and _job_reads(calls) == []


def test_a_conflicting_not_run_pr_keeps_red_since_and_is_an_order_by_its_conflict_alone(tmp_path, monkeypatch):
    pr = _open(14, [_check(1, "Lint")], mergeStateStatus="DIRTY")
    by, _, _ = _read(tmp_path, monkeypatch, [pr], {1: _job(1)}, {1: _notes()})
    p = by[14]
    assert (p["checks"], p["conflicting"], p["red_since"]) == ("not_run", True, T0.isoformat())
    assert workorders.red_prs([p], [], T0 + 30 * timedelta(minutes=1), {}, HOUR)[0] == []  # not before ORPHAN_AFTER
    (o,) = workorders.red_prs([p], [], T0 + 2 * HOUR, {}, HOUR)[0]
    assert o["id"] == "pr:14" and o["context"] == "https://x/14 · conflicting · CI never ran"
    # red then, not_run and conflicting now: the conflict's clock starts afresh; already conflicting, it keeps
    old = {"open": [{"number": 14, "red_since": (T0 - 3 * HOUR).isoformat(), "conflicting": False}]}
    by, _, _ = _read(tmp_path, monkeypatch, [pr], {1: _job(1)}, {1: _notes()}, old=old)
    assert by[14]["red_since"] == T0.isoformat()
    old["open"][0]["conflicting"] = True
    by, _, _ = _read(tmp_path, monkeypatch, [pr], {1: _job(1)}, {1: _notes()}, old=old)
    assert by[14]["red_since"] == (T0 - 3 * HOUR).isoformat()


def test_no_reader_of_checks_takes_not_run_for_red():
    """Every switch on `checks` with `not_run` and no conflict: no order, no holder told, no red row
    on the pages, no Inbox row; the Repo page and the facet draw it *CI never ran*, counted apart."""
    from shiftlead import teamrun
    from shiftlead.ui.inbox import red_pr_rows
    from shiftlead.ui.org import repo_facet
    from shiftlead.ui.repo import pr_rows

    not_run = {"reason": BILLING, "kind": "billing", "runs": [RUN]}
    p = {
        "number": 1097,
        "title": "sync",
        "url": "https://x/1097",
        "author": "eye",
        "branch": "td9",
        "created": T0.isoformat(),
        "checks": "not_run",
        "failing": [],
        "conflicting": False,
        "not_run": not_run,
    }
    holder = type(
        "R", (), {"id": "g1", "name": "g1", "state": "idle", "branch": "td9", "repo": "/r", "dir": "/r", "pr": 1097}
    )()
    later = T0 + 5 * HOUR
    assert workorders.red_prs([p], [holder], later, {}, HOUR) == ([], {}, [])
    assert workorders.red_holders([p], [holder], later, HOUR) == {}
    r = {
        "name": "samscrape",
        "root": "/r",
        "prs": {"open": [p], "windows": None},
        "pr_orders": {"orders": [], "told": {}, "held": {}},
        "ledger": {},
        "at": T0.isoformat(),
    }
    assert teamrun.red_prs(r, [], later) == []
    assert red_pr_rows({"/r": r}, [], later) == []
    (row,) = pr_rows(r, [], {}, later)
    assert (row["red"], row["not_run"]) == (None, not_run)
    facet = repo_facet(r, later)["prs"]
    assert (facet["red"], facet["not_run"]) == ([], 1)
    assert facet["not_run_title"] == f"#1097 · {BILLING}"


def test_the_repo_page_tags_it_ci_never_ran_and_the_card_counts_it_apart(tmp_path, monkeypatch):
    from test_ui_red_prs import client, fake, reading, rec

    root = str(tmp_path / "samscrape")
    r = reading(root)
    r["prs"]["open"].append(
        {
            "number": 1097,
            "title": "sync dev-cadence 517a2b5",
            "created": T0.isoformat(),
            "author": "eye",
            "branch": "s",
            "url": "https://x/1097",
            "checks": "not_run",
            "failing": [],
            "conflicting": False,
            "not_run": {"reason": BILLING, "kind": "billing", "runs": [RUN]},
        }
    )
    c = client(monkeypatch, tmp_path, fake({root: r}, [rec("g1", root, git={"branch": "td9"})]))
    html = c.get("/repo/samscrape").text
    assert (
        f'<span class="tag notrun" title="{BILLING.replace("&", "&amp;").replace(chr(39), "&#39;")}">CI never ran</span>'
        in html
    )
    assert html.count(">CI never ran</span>") == 1  # the red rows carry no such tag
    page = c.get("/").text
    assert ">· 3 red</span>" in page and ">· 1 CI never ran</span>" in page


def test_a_sync_pr_whose_ci_never_ran_waits_and_is_an_order_from_the_reading_it_conflicts(tmp_path, monkeypatch):
    """§4.4: a sync PR `not_run` and not conflicting waits with no timeout, the Inbox being the signal;
    a conflicting one is an order at once, its `sync_since` counted from then."""
    head = "a" * 40
    pr = _open(1097, [_check(1, "Lint")], head=head, headRefName="cadence-sync-517a2b5")
    flag = {"number": 1097, "sync": True, "sync_head": head, "sync_since": (T0 - 5 * HOUR).isoformat()}
    by, first, _ = _read(tmp_path, monkeypatch, [pr], {1: _job(1)}, {1: _notes()}, old={"open": [flag]})
    p = by[1097]
    assert (p["checks"], p["sync"], p["sync_since"]) == ("not_run", True, T0.isoformat())  # waiting: no clock runs
    assert not workorders.is_sync_order(p) and workorders.red_prs([p], [], T0 + 9 * HOUR, {}, HOUR)[0] == []
    t1 = T0 + 3 * HOUR
    by, _, _ = _read(tmp_path, monkeypatch, [{**pr, "mergeStateStatus": "DIRTY"}], {}, {}, old=first, now=t1)
    p = by[1097]
    assert (p["checks"], p["conflicting"], p["sync_since"]) == ("not_run", True, T0.isoformat())
    (o,) = workorders.red_prs([p], [], t1, {}, HOUR)[0]
    assert (o["id"], o["sync"], o["reason"]) == ("pr:1097", True, "conflicting, CI never ran")


# -- slice 2: the `done`'s read, the promote's checks, `ci_not_run` ----------------------------------


def _view(*checks: dict, head: str = "a" * 40) -> dict:
    return {
        "state": "OPEN",
        "mergedAt": None,
        "headRefOid": head,
        "baseRefName": "main",
        "statusCheckRollup": list(checks),
    }


NEVER = {"started": False, "reason": BILLING, "kind": "billing"}


def test_at_done_puts_a_required_job_that_never_started_in_not_run_and_a_real_failure_wins():
    view = _view(_check(1, "Lint"), _check(2, "test"), _check(3, "docs"))
    got = reports.at_done(view, ["Lint", "test"], {"1": NEVER, "2": NEVER})
    assert (got["word"], got["not_run"], got["failed"], got["other"]) == ("not_run", ["Lint", "test"], [], ["docs"])
    assert got["not_run_why"] == {"reason": BILLING, "kind": "billing"}
    # one that started beside it is a real failure, and wins
    got = reports.at_done(view, ["Lint", "test"], {"1": NEVER, "2": {"started": True}})
    assert (got["word"], got["failed"], got["not_run"]) == ("refused", ["test"], ["Lint"])
    # with no verdict a failing job is failed, as before
    assert reports.at_done(view, ["Lint"], None)["word"] == "refused"
    # not_run outranks a required check still running
    queued = {**_check(9, "test"), "status": "QUEUED", "conclusion": ""}
    got = reports.at_done(_view(_check(1, "Lint"), queued), ["Lint", "test"], {"1": NEVER})
    assert (got["word"], got["running"]) == ("not_run", ["test"])


def test_done_verdicts_take_the_readings_jobs_for_this_head_else_read_the_required_ones(tmp_path, monkeypatch):
    view = _view(_check(1, "Lint"), _check(2, "test"), _check(3, "docs"))
    kept = {"head": "a" * 40, "read": {"1": NEVER, "2": NEVER}}
    calls = _fake(monkeypatch, [], {}, {})
    assert reports.done_verdicts(tmp_path, view, ["Lint", "test"], kept, 5) == kept["read"]
    assert _job_reads(calls) == []  # the reading held them: nothing read
    # another head's map is not this head's: the required failing jobs are read, the unrequired one not
    calls = _fake(monkeypatch, [], {1: _job(1), 2: _job(2), 3: _job(3)}, {1: _notes(), 2: _notes(), 3: _notes()})
    got = reports.done_verdicts(tmp_path, view, ["Lint", "test"], {**kept, "head": "b" * 40}, 5)
    assert got == {"1": NEVER, "2": NEVER} and _job_reads(calls) == [1, 2]
    # stops at the first that started; an unreadable one is no evidence and is not kept
    calls = _fake(monkeypatch, [], {1: _job(1, runner="r"), 2: _job(2)}, {2: _notes()})
    assert reports.done_verdicts(tmp_path, view, ["Lint", "test"], None, 5) == {"1": {"started": True}}
    assert _job_reads(calls) == [1]
    calls = _fake(monkeypatch, [], {2: _job(2)}, {2: _notes()})
    assert reports.done_verdicts(tmp_path, view, ["Lint", "test"], None, 5) == {}
    # a repo whose origin is not GitHub reads nothing
    calls = _fake(monkeypatch, [], {1: _job(1)}, {1: _notes()}, origin="https://gitlab.com/x/y.git")
    assert reports.done_verdicts(tmp_path, view, ["Lint"], None, 5) == {} and _job_reads(calls) == []


def _fake_promote(monkeypatch, runs: list, jobs: dict, notes: dict):
    from sessionorc import promote

    calls = _fake(monkeypatch, [], jobs, notes)
    real = reports.subprocess.run

    def run(argv, **kw):
        if argv[0] == "gh" and "/commits/" in argv[2]:
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"check_runs": runs}), "")
        return real(argv, **kw)

    monkeypatch.setattr(promote.subprocess, "run", run)
    return promote, calls


def _run_of(job: int, conclusion: str = "failure", run: int = RUN) -> dict:
    url = f"https://github.com/ContractMatch/samscrape/actions/runs/{run}/job/{job}"
    return {"id": job, "name": f"j{job}", "status": "completed", "conclusion": conclusion, "details_url": url}


def test_the_promotes_checks_say_ci_never_ran_failed_or_pending(tmp_path, monkeypatch):
    sha = "c" * 40
    promote, calls = _fake_promote(
        monkeypatch, [_run_of(1), _run_of(2, run=RUN + 1)], {1: _job(1), 2: _job(2)}, {1: _notes(), 2: _notes()}
    )
    monkeypatch.setattr(promote, "_jobs", {})
    got = promote.read_checks(tmp_path, sha)
    assert got == (
        "unknown",
        f"CI never ran: {BILLING}",
        {"reason": BILLING, "kind": "billing", "runs": [RUN, RUN + 1]},
    )
    assert _job_reads(calls) == [1, 2]
    # kept per sha: the same head reads no job again; a new one does
    assert promote.read_checks(tmp_path, sha) == got and _job_reads(calls) == [1, 2]
    # a rollback's commit is read without replacing main's kept verdicts
    assert promote.read_checks(tmp_path, "9" * 40, False)[0] == "unknown" and _job_reads(calls) == [1, 2, 1, 2]
    assert promote.read_checks(tmp_path, sha) == got and _job_reads(calls) == [1, 2, 1, 2]
    assert promote.read_checks(tmp_path, "d" * 40)[0] == "unknown" and _job_reads(calls) == [1, 2, 1, 2, 1, 2]
    # a real failure beside them is failed
    promote, _ = _fake_promote(
        monkeypatch, [_run_of(1), _run_of(3)], {1: _job(1), 3: _job(3, runner="r")}, {1: _notes()}
    )
    assert promote.read_checks(tmp_path, "e" * 40) == ("failed", "", None)
    # nothing failed and one still running is pending, as before
    promote, _ = _fake_promote(monkeypatch, [_run_of(1, "success"), {"status": "queued"}], {}, {})
    assert promote.read_checks(tmp_path, "f" * 40) == ("pending", "", None)


def test_ci_not_run_groups_by_owner_and_leaves_out_a_non_github_origin():
    nr = {"reason": BILLING, "kind": "billing", "runs": [RUN]}
    pr = {
        "number": 1097,
        "checks": "not_run",
        "not_run": nr,
        "url": "https://github.com/ContractMatch/samscrape/pull/1097",
    }
    repos = {
        "/r/samscrape": {
            "prs": {
                "open": [pr, {"number": 1, "checks": "red", "url": "https://github.com/ContractMatch/samscrape/pull/1"}]
            }
        },
        "/r/cm": {"prs": {"open": [{**pr, "number": 7, "url": "https://github.com/contractmatch/cm/pull/7"}]}},
        "/r/other": {"prs": {"open": [{**pr, "number": 3, "url": "https://github.com/Paulw/other/pull/3"}]}},
        "/r/lab": {"prs": {"open": [{**pr, "number": 4, "url": "https://gitlab.com/x/lab/-/merge_requests/4"}]}},
    }
    promotes = {
        "samscrape": {
            "root": "/r/samscrape",
            "main": "m" * 40,
            "checks_not_run": nr,
            "origin": "git@github.com:ContractMatch/samscrape.git",
        },
        "shiftlead": {
            "root": "/r/sl",
            "main": "s" * 40,
            "checks_not_run": None,
            "origin": "git@github.com:ShiftLead/shiftlead.git",
        },
        "lab": {"root": "/r/lab", "main": "l" * 40, "checks_not_run": nr, "origin": "git@gitlab.com:x/lab.git"},
    }
    got = workorders.ci_not_run(repos, promotes)
    assert sorted(got) == ["contractmatch", "paulw"]
    cm = got["contractmatch"]
    assert (cm["reason"], cm["kind"]) == (BILLING, "billing")
    assert [(i["repo"], i.get("pr"), i.get("main")) for i in cm["items"]] == [
        ("cm", 7, None),
        ("samscrape", 1097, None),
        ("samscrape", None, "m" * 40),
    ]
    assert cm["items"][2]["root"] == "/r/samscrape" and cm["items"][0]["runs"] == [RUN]
