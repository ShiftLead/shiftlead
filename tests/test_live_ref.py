"""The live ref (design §6 *The live ref*, TD-1437; TD-1450): the home keeps `promote/live` on each promoted
repo's origin at the live commit, only while a run finished at it, read on every full pass that may tag and
moved once per change; each note once per ref and sha; a landed push or a changed lease makes the repo's gates
due for a sweep on the next tick."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime

import pytest
from test_promote import _commit, _git, _merge, _pass, _press, _smoke_block, checkout  # noqa: F401 — the fixture

from sessionorc import promote

TAG, BRANCH = promote.LIVE_TAG, promote.LIVE_BRANCH


def _origin(root) -> str:
    return _git(root, "remote", "get-url", "origin")


def _refs(root) -> dict[str, str]:
    out = _git(root, "ls-remote", "--refs", "origin", TAG, BRANCH)
    return {ref: sha for sha, ref in (line.split("\t") for line in out.splitlines() if line)}


def _put(root, ref: str, sha: str) -> None:
    _git(root, "push", "-q", "--force", "origin", f"{sha}:{ref}")


def _delete(root, ref: str) -> None:
    _git(root, "push", "-q", "origin", f":{ref}")


def _finish(repo: str, sha: str, done: bool = True) -> None:
    d = promote.repo_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    got = {"sha": sha, "from": None, "at": datetime.now(UTC).isoformat(), "by": "person", "kind": "promote"}
    (d / "last.json").write_text(json.dumps({**got, **({"done": got["at"]} if done else {})}))


def _head(root) -> str:
    return _git(root, "rev-parse", "HEAD")


@pytest.mark.unit
def test_an_absent_tag_is_pushed_once_and_an_unchanged_reading_pushes_nothing(checkout):  # noqa: F811
    live = _head(checkout)
    assert promote.keep_live_ref(checkout, "repo", live) == ([], True)
    assert _refs(checkout) == {TAG: live} and promote.live_ref("repo") == live
    assert promote.keep_live_ref(checkout, "repo", live) == ([], False)


@pytest.mark.unit
def test_a_tag_at_the_lease_is_pushed_with_it(checkout):  # noqa: F811
    first = _head(checkout)
    promote.keep_live_ref(checkout, "repo", first)
    second = _merge(checkout, "b")
    assert promote.keep_live_ref(checkout, "repo", second) == ([], True)
    assert _refs(checkout)[TAG] == second and promote.live_ref("repo") == second


@pytest.mark.unit
def test_a_tag_already_at_live_is_adopted_with_no_note(checkout):  # noqa: F811
    first = _head(checkout)
    second = _merge(checkout, "b")
    _put(checkout, TAG, second)  # a push whose lease write was lost
    assert promote.keep_live_ref(checkout, "repo", second) == ([], True)
    assert promote.live_ref("repo") == second
    assert promote.keep_live_ref(checkout, "repo", second) == ([], False)  # the lease is live: nothing changed
    promote._set_live_ref("repo", first)  # an older lease
    assert promote.keep_live_ref(checkout, "repo", second) == ([], True) and promote.live_ref("repo") == second


@pytest.mark.unit
def test_someone_elses_tag_is_noted_once_per_sha_and_the_lease_cleared(checkout):  # noqa: F811
    first = _head(checkout)
    promote.keep_live_ref(checkout, "repo", first)
    second = _merge(checkout, "b")
    third = _merge(checkout, "c")
    _put(checkout, TAG, second)  # at neither the lease (first) nor live (third)
    notes, moved = promote.keep_live_ref(checkout, "repo", third)
    assert notes == [promote.tag_note("repo")] and not moved
    assert promote.live_ref("repo") is None and _refs(checkout)[TAG] == second  # nothing pushed
    assert promote.keep_live_ref(checkout, "repo", third) == ([], False)  # noted once, across reads
    _delete(checkout, TAG)
    assert promote.keep_live_ref(checkout, "repo", third) == ([], True)  # deleted: pushed on the next pass
    assert _refs(checkout)[TAG] == third
    _put(checkout, TAG, second)  # moved back to the same sha: noted again
    assert promote.keep_live_ref(checkout, "repo", third)[0] == [promote.tag_note("repo")]


@pytest.mark.unit
def test_a_tag_at_another_commit_with_no_lease_is_someone_elses(checkout):  # noqa: F811
    first = _head(checkout)
    second = _merge(checkout, "b")
    _put(checkout, TAG, first)
    assert promote.keep_live_ref(checkout, "repo", second) == ([promote.tag_note("repo")], False)
    assert _refs(checkout)[TAG] == first


@pytest.mark.unit
def test_a_branch_of_the_name_is_noted_once_and_nothing_is_pushed(checkout):  # noqa: F811
    first = _head(checkout)
    second = _merge(checkout, "b")
    promote.keep_live_ref(checkout, "repo", first)
    _put(checkout, BRANCH, first)
    assert promote.keep_live_ref(checkout, "repo", second) == ([promote.branch_note("repo")], False)
    assert _refs(checkout)[TAG] == first and promote.live_ref("repo") == first  # the lease kept
    assert promote.keep_live_ref(checkout, "repo", second) == ([], False)
    _delete(checkout, BRANCH)
    assert promote.keep_live_ref(checkout, "repo", second) == ([], True)  # gone: the tag read as the list says
    assert _refs(checkout)[TAG] == second
    _put(checkout, BRANCH, first)  # pushed again at the same sha after its deletion was read: noted again
    assert promote.keep_live_ref(checkout, "repo", second)[0] == [promote.branch_note("repo")]


@pytest.mark.unit
def test_a_branch_note_never_stands_for_a_tag_note_at_the_same_sha(checkout):  # noqa: F811
    first = _head(checkout)
    second = _merge(checkout, "b")
    _put(checkout, BRANCH, first)
    assert promote.keep_live_ref(checkout, "repo", second)[0] == [promote.branch_note("repo")]
    _put(checkout, TAG, first)
    _delete(checkout, BRANCH)
    assert promote.keep_live_ref(checkout, "repo", second) == ([promote.tag_note("repo")], False)


@pytest.mark.unit
def test_a_tag_noted_before_a_branch_came_and_went_is_not_noted_again(checkout):  # noqa: F811
    first = _head(checkout)
    second = _merge(checkout, "b")
    _put(checkout, TAG, first)
    assert promote.keep_live_ref(checkout, "repo", second)[0] == [promote.tag_note("repo")]
    _put(checkout, BRANCH, second)
    assert promote.keep_live_ref(checkout, "repo", second)[0] == [promote.branch_note("repo")]
    _delete(checkout, BRANCH)
    assert promote.keep_live_ref(checkout, "repo", second) == ([], False)
    assert promote.live_ref_noted("repo") == {TAG: first}


@pytest.mark.unit
def test_a_failed_read_keeps_the_lease_and_the_noted_lines(checkout):  # noqa: F811
    first = _head(checkout)
    second = _merge(checkout, "b")
    promote.keep_live_ref(checkout, "repo", first)
    _put(checkout, TAG, second)
    third = _merge(checkout, "c")
    assert promote.keep_live_ref(checkout, "repo", third)[0] == [promote.tag_note("repo")]
    url = _origin(checkout)
    _git(checkout, "remote", "set-url", "origin", str(checkout.parent / "nowhere.git"))
    assert promote.keep_live_ref(checkout, "repo", third) == ([], False)  # no reading: nothing absent
    assert promote.live_ref_noted("repo") == {TAG: second}
    _git(checkout, "remote", "set-url", "origin", url)
    assert promote.keep_live_ref(checkout, "repo", third) == ([], False)  # the same tag: no second note


@pytest.mark.unit
def test_a_push_refused_for_its_lease_changes_nothing(checkout, monkeypatch):  # noqa: F811
    first = _head(checkout)
    promote.keep_live_ref(checkout, "repo", first)
    second = _merge(checkout, "b")
    third = _merge(checkout, "c")
    _put(checkout, TAG, third)  # moved between the read and the push
    monkeypatch.setattr(promote, "read_live_refs", lambda root: {TAG: first})
    assert promote.keep_live_ref(checkout, "repo", second) == ([], False)
    assert _refs(checkout)[TAG] == third and promote.live_ref("repo") == first
    monkeypatch.undo()
    # the next read acts on what is there: someone else's
    assert promote.keep_live_ref(checkout, "repo", second)[0] == [promote.tag_note("repo")]


@pytest.mark.unit
def test_an_annotated_tag_reads_by_its_own_object(checkout):  # noqa: F811
    live = _head(checkout)
    _git(checkout, "tag", "-a", "-m", "x", "promote/live", live)
    _git(checkout, "push", "-q", "origin", "refs/tags/promote/live")
    assert promote.read_live_refs(checkout)[TAG] != live  # its tag object, never the peeled line
    assert promote.keep_live_ref(checkout, "repo", live) == ([promote.tag_note("repo")], False)


@pytest.mark.unit
def test_the_lease_survives_a_restart_between_two_pushes(checkout):  # noqa: F811
    promote.keep_live_ref(checkout, "repo", _head(checkout))
    second = _merge(checkout, "b")
    # nothing held in memory: a new home reads the files
    assert promote.keep_live_ref(checkout, "repo", second) == ([], True) and _refs(checkout)[TAG] == second


# ── the pass ──────────────────────────────────────────────────────────────────────────────────────


def _survey(checkout, prev=None, full=True):  # noqa: F811
    return promote.survey([str(checkout)], prev or {}, full, {}, datetime.now(UTC))


@pytest.mark.unit
def test_a_full_pass_tags_a_commit_a_run_finished_at_and_names_it_moved(checkout):  # noqa: F811
    live = _head(checkout)
    readings, notes, _, moved = _survey(checkout)
    assert moved == [] and TAG not in _refs(checkout), "no run finished there: nothing read or pushed"
    _finish("repo", live, done=False)  # a run that did not finish
    assert _survey(checkout, readings)[3] == [] and TAG not in _refs(checkout)
    _finish("repo", live)
    readings, notes, _, moved = _survey(checkout, readings)
    assert moved == [str(checkout)] and _refs(checkout)[TAG] == live and notes == []
    assert readings["repo"]["live_ref"] == live
    assert _survey(checkout, readings)[3] == []  # unchanged: nothing pushed


@pytest.mark.unit
def test_a_pass_with_a_run_in_flight_or_live_off_main_reads_nothing(checkout, tmp_path):  # noqa: F811
    live = _head(checkout)
    _finish("repo", live)
    d = promote.repo_dir("repo")
    nxt = _merge(checkout, "b")  # a run toward the next commit, still running (this test's own pid)
    at = datetime.now(UTC).isoformat()
    (d / "inflight.json").write_text(json.dumps({"sha": nxt, "from": live, "pid": os.getpid(), "at": at}))
    readings, *_ = _survey(checkout)
    assert promote.inflight("repo") and TAG not in _refs(checkout), "a run in flight"
    (d / "inflight.json").unlink()
    # a commit `origin/main` does not hold
    _git(checkout, "checkout", "-q", "-b", "side")
    off = _commit(checkout, "off")
    _git(checkout, "checkout", "-q", "main")
    (tmp_path / "live").write_text(off + "\n")
    _finish("repo", off)
    assert _survey(checkout)[3] == [] and TAG not in _refs(checkout)


@pytest.mark.unit
def test_a_watch_pass_reads_only_when_it_concludes(checkout, tmp_path):  # noqa: F811
    live = _head(checkout)
    readings, *_ = _survey(checkout)
    _finish("repo", live)
    assert _survey(checkout, readings, full=False)[3] == [], "a watch pass with nothing concluding reads nothing"
    assert TAG not in _refs(checkout)


@pytest.mark.unit
def test_the_watch_pass_that_concludes_a_run_pushes_and_its_smoke_pass_before_it_does_not(checkout):  # noqa: F811
    _smoke_block(checkout)
    frm = _head(checkout)
    main = _merge(checkout, "b")
    readings = _press(checkout, main, frm=frm)
    readings, _ = _pass(checkout, readings)  # check reads main: the smoke runs, the promote in flight
    assert readings["repo"]["inflight"]["phase"] == "smoke" and TAG not in _refs(checkout)
    readings, notes = _pass(checkout, readings)  # the smoke passed: concluded, `done`, and tagged
    assert readings["repo"]["inflight"] is None and promote.finished("repo", main)
    assert _refs(checkout)[TAG] == main and readings["repo"]["live_ref"] == main


@pytest.mark.unit
def test_a_failed_smoke_tags_nothing_and_its_rollback_finds_the_tag_at_the_lease(checkout):  # noqa: F811
    _, code = _smoke_block(checkout)
    frm = _head(checkout)
    _finish("repo", frm)
    promote.keep_live_ref(checkout, "repo", frm)  # the tag at the last commit a run finished at
    main = _merge(checkout, "b")
    readings = _press(checkout, main, frm=frm)
    code.write_text("4")
    readings, _ = _pass(checkout, readings)
    readings, _ = _pass(checkout, readings)  # the smoke failed: the rollback starts
    assert readings["repo"]["inflight"]["kind"] == "rollback" and _refs(checkout)[TAG] == frm
    code.write_text("0")
    readings, _ = _pass(checkout, readings)
    readings, _ = _pass(checkout, readings)  # the rollback concludes at frm
    assert readings["repo"]["inflight"] is None and readings["repo"]["live"] == frm
    assert _refs(checkout)[TAG] == frm and promote.live_ref("repo") == frm  # nothing pushed


# ── the sweep after it ────────────────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_a_moved_ref_makes_the_repo_due_also_while_its_sweep_runs(agent, monkeypatch):
    from conftest import park_ticks

    await park_ticks(agent)
    today = date.today()
    agent._swept_on["/r"] = today
    agent._live_ref_moved(["/r"])
    assert "/r" not in agent._swept_on

    agent._repos = {"/r": {}}
    seen: list[bool] = []

    async def run(root, roots, day, by):
        agent._live_ref_moved([root])  # the push lands while the sweep runs
        seen.append(root in agent._resweep and agent._swept_on.get(root) == day)

    monkeypatch.setattr(agent, "_sweep_root", run)
    await agent._sweep_pass(today)
    assert seen == [True]
    assert "/r" not in agent._swept_on and not agent._resweep and not agent._sweeping
