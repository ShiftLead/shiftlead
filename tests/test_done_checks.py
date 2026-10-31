"""TD-639, design §4.8 *A `done` with a PR is told what its checks read*: `ao progress done <ref>
--pr <n>` reads the PR's checks once at the declaration, against the required checks of its base
branch — refused while a required one failed or still runs on the head (TD-658), accepted merged,
green, with no CI, or (as *unknown*) when the home could not read them. An `ask` carrying `pr` from a
session is read the same way (design §4.9b *The reader*, TD-664)."""

from __future__ import annotations

import json
import subprocess

import pytest
from conftest import park_ticks

from sessionorc import cadence, reports
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import report_line

SHA = "9c1e0f2aaaabbbbccccdddd"
PRECHECK = 0  # `views`' key for what `cadence.precheck_command` answers


def _run(name: str, status: str = "COMPLETED", conclusion: str = "SUCCESS") -> dict:
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def _status(context: str, state: str) -> dict:
    return {"__typename": "StatusContext", "context": context, "state": state}


def _view(*checks: dict, state: str = "OPEN", merged: str | None = None) -> dict:
    return {
        "state": state,
        "mergedAt": merged,
        "headRefOid": SHA,
        "baseRefName": "main",
        "statusCheckRollup": list(checks),
    }


# -- the verdict, pure -----------------------------------------------------------------------------


def test_a_required_check_red_on_the_head_is_refused_by_the_repo_readings_rule():
    for bad in (_run("test", conclusion="FAILURE"), _run("test", conclusion="STARTUP_FAILURE")):
        got = reports.at_done(_view(_run("lint"), bad), ["test", "lint"])
        assert (got["word"], got["failed"], got["sha"]) == ("refused", ["test"], SHA)
    for state in ("FAILURE", "ERROR"):
        assert reports.at_done(_view(_status("ci/x", state)), ["ci/x"])["failed"] == ["ci/x"]


def test_a_failed_check_no_rule_requires_refuses_nothing_and_is_named():
    got = reports.at_done(_view(_run("test"), _run("docs", conclusion="FAILURE")), ["test"])
    assert (got["word"], got["failed"], got["other"]) == ("green", [], ["docs"])
    # one still running that is not required is not *pending* either
    assert reports.at_done(_view(_run("test"), _run("slow", "IN_PROGRESS", "")), ["test"])["word"] == "green"


def test_pending_merged_closed_and_no_checks():
    got = reports.at_done(_view(_run("test", "QUEUED", ""), _status("ci/x", "PENDING")), ["test", "ci/x"])
    assert (got["word"], got["running"]) == ("pending", ["test", "ci/x"])
    # red outranks pending, as the reading folds it
    assert reports.at_done(_view(_run("a", "QUEUED", ""), _run("b", conclusion="FAILURE")), None)["word"] == "refused"
    assert reports.at_done(_view(_run("t", conclusion="FAILURE"), state="MERGED", merged="2026-10-13"), ["t"]) == {
        "sha": SHA,
        "failed": [],
        "not_run": [],
        "other": [],
        "running": [],
        "word": "merged",
    }
    assert reports.at_done(_view(state="CLOSED"), None)["word"] == "closed"
    assert reports.at_done(_view(), [])["word"] == "green"


def test_with_nothing_required_or_the_set_never_read_every_check_counts():
    for required in (None, []):
        got = reports.at_done(_view(_run("anything", conclusion="TIMED_OUT")), required)
        assert (got["word"], got["failed"]) == ("refused", ["anything"])


def test_where_the_repo_sets_precheck_it_is_required_on_an_open_head():
    """TD-1036: absent, it is still running, named last; failed, a required failure; a real failure and
    a run never started outrank its absence; green with it, accepted; not set, as before."""
    pre = _status(reports.PRECHECK_CONTEXT, "SUCCESS")
    got = reports.at_done(_view(_run("test")), ["test"], precheck=True)
    assert (got["word"], got["running"], got["precheck_absent"]) == ("pending", ["cadence/precheck"], True)
    got = reports.at_done(_view(_run("test", "IN_PROGRESS", "")), None, precheck=True)
    assert (got["word"], got["running"]) == ("pending", ["test", "cadence/precheck"])
    got = reports.at_done(_view(_run("test"), _status(reports.PRECHECK_CONTEXT, "FAILURE")), ["test"], precheck=True)
    assert (got["word"], got["failed"], got["other"]) == ("refused", ["cadence/precheck"], [])
    got = reports.at_done(_view(_run("test", conclusion="FAILURE")), ["test"], precheck=True)
    assert (got["word"], got["failed"]) == ("refused", ["test"])
    got = reports.at_done(_view(_run("test", conclusion="FAILURE")), ["test"], {}, precheck=True)
    assert got["word"] == "refused"
    for required in (["test"], None, []):
        got = reports.at_done(_view(_run("test"), pre), required, precheck=True)
        assert (got["word"], got["running"], "precheck_absent" in got) == ("green", [], False)
    assert reports.at_done(_view(), [], precheck=True)["word"] == "pending"  # no checks at all is no precheck
    # not set: the status is one more check, outside a required set
    got = reports.at_done(_view(_run("test"), _status(reports.PRECHECK_CONTEXT, "FAILURE")), ["test"])
    assert (got["word"], got["other"]) == ("green", ["cadence/precheck"])
    assert reports.at_done(_view(_run("test")), ["test"])["word"] == "green"
    # merged and closed are as they were
    merged = _view(state="MERGED", merged="2026-10-26T00:00:00Z")
    assert reports.at_done(merged, ["test"], precheck=True)["word"] == "merged"
    assert reports.at_done(_view(state="CLOSED"), ["test"], precheck=True)["word"] == "closed"


def test_a_never_started_run_outranks_an_absent_precheck():
    view = _view(_job_run("test", 11))
    got = reports.at_done(view, ["test"], {"11": {"started": False, "reason": "billing", "kind": "billing"}}, True)
    assert (got["word"], got["not_run"], got["running"]) == ("not_run", ["test"], ["cadence/precheck"])


# -- the required set, read with the repo reading ---------------------------------------------------


def _fake_api(monkeypatch, answers: dict[str, tuple[int, str, str]]) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(argv, **kw):
        calls.append(argv)
        for key, (rc, out, err) in answers.items():
            if key in argv[-1]:
                return subprocess.CompletedProcess(argv, rc, out, err)
        raise AssertionError(argv)

    monkeypatch.setattr(reports.subprocess, "run", run)
    return calls


def test_the_required_set_is_the_protections_and_the_rulesets_union(tmp_path, monkeypatch):
    protection = {"contexts": ["test (3.12)", "lint"], "checks": [{"context": "lint", "app_id": 1}]}
    rules = [
        {"type": "deletion"},
        {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "ci/build"}]}},
    ]
    calls = _fake_api(
        monkeypatch,
        {"/protection/": (0, json.dumps(protection), ""), "/rules/branches/": (0, json.dumps(rules), "")},
    )
    assert reports.required_checks(tmp_path, "release/1") == ["ci/build", "lint", "test (3.12)"]
    assert "branches/release%2F1/protection" in calls[0][-1]


def test_a_branch_not_protected_requires_none_from_it_and_a_403_is_an_error(tmp_path, monkeypatch):
    not_protected = (1, '{"message":"Branch not protected"}', "gh: Branch not protected (HTTP 404)")
    _fake_api(monkeypatch, {"/protection/": not_protected, "/rules/branches/": (0, "[]", "")})
    assert reports.required_checks(tmp_path, "main") == []
    _fake_api(monkeypatch, {"/protection/": (1, "", "gh: Resource not accessible by integration (HTTP 403)")})
    assert "HTTP 403" in reports.required_checks(tmp_path, "main")
    not_found = (1, "", "gh: Branch not found (HTTP 404)")
    _fake_api(monkeypatch, {"/protection/": not_found})
    assert "Branch not found" in reports.required_checks(tmp_path, "gone")


def test_a_failed_read_keeps_the_last_set_with_its_error(tmp_path, monkeypatch):
    got = iter([["test"], "HTTP 403", "HTTP 403"])
    monkeypatch.setattr(reports, "required_checks", lambda d, base, timeout=30.0: next(got))
    required, errors = reports._required_reading(tmp_path, {"main"}, None, 1.0)
    assert (required, errors) == ({"main": ["test"]}, {})
    required, errors = reports._required_reading(tmp_path, {"main"}, {"required": required}, 1.0)
    assert (required, errors) == ({"main": ["test"]}, {"main": "HTTP 403"})
    # a base never read is absent: the declaration then takes every run
    required, errors = reports._required_reading(tmp_path, {"dev"}, None, 1.0)
    assert required == {} and errors == {"dev": "HTTP 403"}


# -- the declaration ----------------------------------------------------------------------------------


@pytest.fixture
async def worker(agent, tmp_path, monkeypatch):
    """A session on a checkout the home reads, `gh pr view` answered from `views` (a `str` is a read
    that failed), and `main` requiring `test` — what the repo reading would hold."""
    await park_ticks(agent)
    views: dict[int, dict | str] = {}
    monkeypatch.setattr(reports, "pr_view", lambda root, pr, timeout=30.0: views.get(pr, "no such PR"))
    # the repo's `precheck` on origin/<default> (TD-1036): none set unless a test says, under `PRECHECK`
    monkeypatch.setattr(cadence, "precheck_command", lambda root, rev: views.get(PRECHECK, (None, None)))
    made = {
        "dir": str(tmp_path),
        "adapter": "agentshell",
        "argv": ["bash", "--norc", "--noprofile"],
        "unattended": True,
    }
    async with LocalClient() as person:
        sid = (await person.call("create", name="w", **made))["id"]
        rec = agent.sessions[sid]
        rec.repo = str(tmp_path)
        agent._repos[str(tmp_path)] = {"prs": {"required": {"main": ["test"]}}}
        async with LocalClient(caller=sid) as w:
            yield w, sid, rec, views
        await person.call("kill", id=sid)


async def test_a_failed_required_check_refuses_the_done_and_writes_nothing(worker):
    w, sid, rec, views = worker
    await w.call("progress", id=sid, ref="TD-1")
    views[842] = _view(_run("test", conclusion="FAILURE"), _run("lint"))
    with pytest.raises(AgentError, match=r"PR #842's required checks failed on 9c1e0f2: test — fix them"):
        await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    (e,) = rec.progress
    assert (e.status, e.pr, e.ci) == ("claimed", None, None)


async def test_pending_is_refused_naming_the_running_checks_and_writes_nothing(worker):
    """TD-658: a required check still running refuses the declaration, as a failed one does; a
    non-required one still running refuses nothing."""
    w, sid, rec, views = worker
    await w.call("progress", id=sid, ref="TD-1")
    views[842] = _view(_run("test", "IN_PROGRESS", ""), _run("docs", conclusion="FAILURE"))
    with pytest.raises(
        AgentError,
        match=r"PR #842's required checks are still running on 9c1e0f2: test — report done once they pass "
        r"\(`gh pr checks 842 --watch`\)",
    ):
        await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    (e,) = rec.progress
    assert (e.status, e.pr, e.ci) == ("claimed", None, None)
    views[842] = _view(_run("test"), _run("slow", "QUEUED", ""), _run("docs", conclusion="FAILURE"))
    got = await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    assert got["progress"][0]["ci"] is None
    assert got["checks_said"] == "PR #842: checks green on 9c1e0f2; not required, failed: docs"
    assert report_line(got) == "TD-001 → #842 · 1/1 done"


async def test_green_merged_closed_and_no_checks_are_accepted(worker):
    w, sid, rec, views = worker
    views[1] = _view(_run("test"))
    views[2] = _view(_run("test", conclusion="FAILURE"), state="MERGED", merged="2026-10-13T00:00:00Z")
    views[3] = _view(state="CLOSED")
    views[4] = _view()
    said = {}
    for pr in (1, 2, 3, 4):
        got = await w.call("progress", id=sid, ref=f"TD-{pr}", status="done", pr=pr)
        assert got["progress"][-1]["ci"] is None
        said[pr] = got.get("checks_said")
    assert said == {1: "PR #1: checks green on 9c1e0f2", 2: None, 3: "PR #3: closed unmerged", 4: "PR #4: no checks"}


async def test_a_read_the_home_could_not_make_is_accepted_as_unknown(worker):
    w, sid, rec, views = worker
    views[842] = "gh could not be asked: TimeoutExpired"
    got = await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    assert got["progress"][0]["ci"] == "unknown"
    assert got["checks_said"] == "PR #842: checks unknown: gh could not be asked: TimeoutExpired"


async def test_a_base_never_read_takes_every_run_and_says_so(worker, agent):
    w, sid, rec, views = worker
    agent._repos[rec.repo] = {}
    views[842] = _view(_run("anything", conclusion="FAILURE"))
    with pytest.raises(AgentError, match="failed on 9c1e0f2: anything — required set unknown, every check read — fix"):
        await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    views[842] = _view(_run("anything"))
    got = await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    assert "required set unknown" in got["checks_said"]


async def test_a_slice_on_a_pr_not_merged_is_refused(worker):
    w, sid, rec, views = worker
    await w.call("progress", id=sid, ref="TD-1")
    views[842] = _view(_run("test"))
    with pytest.raises(AgentError, match="a slice is a merged PR — #842 is open"):
        await w.call("progress", id=sid, ref="TD-1", status="done", pr=842, slice=True)
    views[842] = _view(state="MERGED", merged="2026-10-13T00:00:00Z")
    got = await w.call("progress", id=sid, ref="TD-1", status="done", pr=842, slice=True)
    assert "stays claimed" in got["slice"] and [x["pr"] for x in rec.progress[0].slices] == [842]


async def test_where_the_repo_sets_precheck_a_head_without_it_refuses_the_done_with_its_line(worker):
    """TD-1036, design §4.8: absent alone, *carries no cadence/precheck* and the line to run; beside a
    required check still running, the still-running refusal with that line, never `--watch`; failed, a
    required failure; present and green, accepted; a `docs/cadence.toml` that does not parse, unknown."""
    w, sid, rec, views = worker
    await w.call("progress", id=sid, ref="TD-1")
    views[PRECHECK] = ("pdm run test", None)
    views[842] = _view(_run("test"))
    with pytest.raises(
        AgentError,
        match=r"PR #842's head 9c1e0f2 carries no cadence/precheck — run `python3 scripts/precheck.py --pr 842` "
        r"\(in the background\), then report done again \(ao progress done TD-001 --pr 842\)$",
    ):
        await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    views[842] = _view(_run("test", "IN_PROGRESS", ""))
    with pytest.raises(AgentError) as e:
        await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    assert "still running on 9c1e0f2: test, cadence/precheck — run `python3 scripts/precheck.py --pr 842`" in str(
        e.value
    )
    assert "--watch" not in str(e.value)
    views[842] = _view(_run("test"), _status(reports.PRECHECK_CONTEXT, "FAILURE"))
    with pytest.raises(AgentError, match=r"required checks failed on 9c1e0f2: cadence/precheck — fix them"):
        await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    (e,) = rec.progress
    assert (e.status, e.pr) == ("claimed", None)
    views[842] = _view(_run("test"), _status(reports.PRECHECK_CONTEXT, "SUCCESS"))
    got = await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    assert got["checks_said"] == "PR #842: checks green on 9c1e0f2"
    views[PRECHECK] = (None, "docs/cadence.toml does not parse")
    views[843] = _view(_run("test"))
    got = await w.call("progress", id=sid, ref="TD-2", status="done", pr=843)
    assert got["checks_said"] == "PR #843: checks unknown: docs/cadence.toml does not parse"
    # a merged PR is not read for it, so a file that does not parse leaves it merged; a slice too
    await w.call("progress", id=sid, ref="TD-3")
    views[844] = _view(state="MERGED", merged="2026-10-26T00:00:00Z")
    got = await w.call("progress", id=sid, ref="TD-3", status="done", pr=844, slice=True)
    assert "stays claimed" in got["slice"]
    with pytest.raises(AgentError, match="a slice is a merged PR — #843 is open"):
        await w.call("progress", id=sid, ref="TD-3", status="done", pr=843, slice=True)


async def test_a_forks_pr_is_judged_on_the_forges_ci_and_never_given_the_precheck_line(worker):
    """TD-1285: where the repo sets `precheck`, a fork's PR is not asked for `cadence/precheck` and its
    `done` is never told the line — running a fork's code here is the person's call, after its CI."""
    w, sid, rec, views = worker
    await w.call("progress", id=sid, ref="TD-1")
    views[PRECHECK] = ("pdm run test", None)
    views[842] = {**_view(_run("test", "IN_PROGRESS", "")), "isCrossRepository": True}
    with pytest.raises(AgentError) as e:
        await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    assert "still running on 9c1e0f2: test" in str(e.value) and "precheck" not in str(e.value)
    views[842] = {**_view(_run("test")), "isCrossRepository": True}
    got = await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    assert got["checks_said"] == "PR #842: checks green on 9c1e0f2"


async def test_a_cadence_toml_not_read_is_no_precheck_and_the_fold_runs_as_before(worker):
    """A rev that is not there, or a read that timed out, is not *unknown* (TD-1036): only a file that
    does not parse is."""
    w, sid, rec, views = worker
    for why in ("docs/cadence.toml could not be read: no origin/main here", "docs/cadence.toml could not be read: X"):
        views[PRECHECK] = (None, why)
        views[842] = _view(_run("test", conclusion="FAILURE"))
        with pytest.raises(AgentError, match=r"required checks failed on 9c1e0f2: test — fix them"):
            await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
        views[842] = _view(_run("test"))
        got = await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
        assert got["checks_said"] == "PR #842: checks green on 9c1e0f2"


# -- the hand-off: an `ask` carrying `pr` (design §4.9b *The reader*, TD-658) ------------------------


async def test_an_ask_with_a_pr_whose_head_carries_no_precheck_is_refused_with_its_line(worker, agent):
    w, sid, rec, views = worker
    views[PRECHECK] = ("pdm run test", None)
    views[842] = _view(_run("test"))
    with pytest.raises(
        AgentError,
        match=r"carries no cadence/precheck — run `python3 scripts/precheck.py --pr 842` \(in the background\), "
        r"then ask again$",
    ):
        await w.call("msg", to=["person"], text="read #842", kind="ask", pr=842)
    views[842] = _view(_run("test", "IN_PROGRESS", ""))
    with pytest.raises(AgentError) as e:
        await w.call("msg", to=["person"], text="read #842", kind="ask", pr=842, nonce="n-3")
    assert str(e.value).endswith(
        "still running on 9c1e0f2: test, cadence/precheck — run `python3 scripts/precheck.py --pr 842` "
        "(in the background), then ask again"
    )
    assert rec.outbox == [] and agent.person_inbox == []
    views[842] = _view(_run("test"), _status(reports.PRECHECK_CONTEXT, "SUCCESS"))
    got = await w.call("msg", to=["person"], text="read #842", kind="ask", pr=842)
    assert got["entry"]["pr"] == 842 and "checks_said" not in got


async def test_an_ask_with_a_pr_is_refused_on_failed_and_on_pending_and_sends_nothing(worker, agent):
    w, sid, rec, views = worker
    views[842] = _view(_run("test", conclusion="FAILURE"))
    with pytest.raises(AgentError, match=r"PR #842's required checks failed on 9c1e0f2: test — fix them and ask again"):
        await w.call("msg", to=["person"], text="read #842", kind="ask", pr=842)
    views[842] = _view(_run("test", "IN_PROGRESS", ""))
    with pytest.raises(
        AgentError, match=r"still running on 9c1e0f2: test — ask again once they pass \(`gh pr checks 842 --watch`\)"
    ):
        await w.call("msg", to=["person"], text="read #842", kind="ask", pr=842, nonce="n-1")
    assert rec.outbox == [] and agent.person_inbox == []
    # green now: a fresh send goes, where the refused nonce answers as it did
    views[842] = _view(_run("test"))
    with pytest.raises(AgentError, match="still running"):
        await w.call("msg", to=["person"], text="read #842", kind="ask", pr=842, nonce="n-1")
    got = await w.call("msg", to=["person"], text="read #842", kind="ask", pr=842, nonce="n-2")
    assert got["entry"]["pr"] == 842 and "checks_said" not in got
    assert [e.pr for e in agent.person_inbox] == [842]


async def test_an_ask_with_a_pr_sends_on_green_merged_closed_and_no_checks(worker, agent):
    w, sid, rec, views = worker
    views[1] = _view(_run("test"))
    views[2] = _view(_run("test", conclusion="FAILURE"), state="MERGED", merged="2026-10-13T00:00:00Z")
    views[3] = _view(state="CLOSED")
    views[4] = _view()
    for pr in (1, 2, 3, 4):
        got = await w.call("msg", to=["person"], text=f"read #{pr}", kind="ask", pr=pr)
        assert got["entry"]["pr"] == pr and "checks_said" not in got


async def test_an_ask_whose_read_failed_sends_saying_checks_unknown(worker, agent):
    w, sid, rec, views = worker
    views[842] = "gh could not be asked: TimeoutExpired"
    got = await w.call("msg", to=["person"], text="read #842", kind="ask", pr=842)
    assert got["entry"]["pr"] == 842
    assert got["checks_said"] == "PR #842: checks unknown: gh could not be asked: TimeoutExpired"
    assert got["checks_said"] in got["advice"]
    # a record that names no checkout here (a node's session) is the same
    rec.repo = None
    got = await w.call("msg", to=["person"], text="read #843", kind="ask", pr=843)
    assert got["checks_said"] == "PR #843: checks unknown: the record names no checkout here"


async def test_the_persons_ask_and_an_ask_with_no_pr_are_not_read(worker, agent, monkeypatch):
    w, sid, rec, views = worker
    read: list[int] = []
    monkeypatch.setattr(
        reports, "pr_view", lambda root, pr, timeout=30.0: read.append(pr) or _view(_run("test", "QUEUED", ""))
    )
    await w.call("msg", to=["person"], text="which entry next?", kind="ask")
    await w.call("msg", to=["person"], text="note", kind="note")
    async with LocalClient() as person:
        await person.call("msg", to=[sid], text="read #842 for me", kind="ask", pr=842)
    assert read == []
    # an ask again on the thread — the reply to findings — is read as the first was
    views[842] = _view(_run("test"))
    monkeypatch.setattr(reports, "pr_view", lambda root, pr, timeout=30.0: read.append(pr) or views[pr])
    first = (await w.call("msg", to=["person"], text="read #842", kind="ask", pr=842))["entry"]["id"]
    async with LocalClient() as person:
        findings = await person.call("msg", reply_to=first, text="one finding: the test name", kind="reply")
    views[842] = _view(_run("test", "QUEUED", ""))
    with pytest.raises(AgentError, match="still running"):
        await w.call("msg", reply_to=findings["entry"]["id"], text="fixed", kind="ask", pr=842)
    assert read == [842, 842]


# -- CI that never started (TD-686 slice 2, design §4.4 *A `done`'s read*) ------------------------------

NEVER = {
    "started": False,
    "reason": "The job was not started because recent account payments have failed",
    "kind": "billing",
}


def _job_run(name: str, job: int, conclusion: str = "FAILURE") -> dict:
    url = f"https://github.com/ContractMatch/samscrape/actions/runs/77/job/{job}"
    return {**_run(name, conclusion=conclusion), "detailsUrl": url}


async def test_a_required_check_that_never_started_refuses_the_done_naming_the_person(worker, agent, monkeypatch):
    """From the repo reading's `jobs` for this head: nothing is read and nothing is written."""
    w, sid, rec, views = worker
    read: list[int] = []
    monkeypatch.setattr(reports, "job_verdict", lambda d, job, t: read.append(job) or NEVER)
    agent._repos[str(tmp := rec.repo)]["prs"]["open"] = [
        {
            "number": 842,
            "url": "https://github.com/ContractMatch/samscrape/pull/842",
            "jobs": {"head": SHA, "read": {"5": NEVER}},
        }
    ]
    await w.call("progress", id=sid, ref="TD-1")
    views[842] = _view(_job_run("test", 5), _run("lint"))
    with pytest.raises(
        AgentError,
        match=r"PR #842's checks never started on 9c1e0f2: billing or spending limit in ContractMatch — the person's "
        r"to fix \(the Inbox says so\); push nothing for it, report done again once CI runs, or drop the claim with "
        r'`ao progress drop TD-001 --why "CI never ran"`',
    ):
        await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    assert read == [] and tmp
    (e,) = rec.progress
    assert (e.status, e.pr) == ("claimed", None)
    # a real failure beside it refuses as before, and wins
    views[842] = _view(_job_run("test", 5), _job_run("lint", 6))
    agent._repos[rec.repo]["prs"]["required"] = {"main": ["test", "lint"]}
    monkeypatch.setattr(reports, "job_verdict", lambda d, job, t: {"started": True})
    monkeypatch.setattr(reports, "git_origin", lambda d: "git@github.com:ContractMatch/samscrape.git")
    with pytest.raises(AgentError, match=r"required checks failed on 9c1e0f2: lint — fix them"):
        await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)


async def test_the_done_reads_the_jobs_itself_when_the_reading_holds_none_for_the_head(worker, monkeypatch):
    w, sid, rec, views = worker
    read: list[int] = []
    monkeypatch.setattr(reports, "job_verdict", lambda d, job, t: read.append(job) or NEVER)
    monkeypatch.setattr(reports, "git_origin", lambda d: "https://github.com/Paulw/other.git")
    await w.call("progress", id=sid, ref="TD-1")
    views[842] = _view(_job_run("test", 5), _job_run("docs", 6))  # docs is not required: never read
    with pytest.raises(
        AgentError, match=r"PR #842's checks never started on 9c1e0f2: billing or spending limit in Paulw"
    ):
        await w.call("progress", id=sid, ref="TD-1", status="done", pr=842)
    assert read == [5]


async def test_an_ask_on_a_pr_whose_checks_never_started_sends_saying_so(worker, agent, monkeypatch):
    w, sid, rec, views = worker
    monkeypatch.setattr(reports, "job_verdict", lambda d, job, t: NEVER)
    monkeypatch.setattr(reports, "git_origin", lambda d: "git@github.com:ContractMatch/samscrape.git")
    views[842] = _view(_job_run("test", 5))
    got = await w.call("msg", to=["person"], text="read #842", kind="ask", pr=842)
    assert got["entry"]["pr"] == 842
    assert got["checks_said"] == f"PR #842: checks never started on 9c1e0f2: {NEVER['reason']}"
