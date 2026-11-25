"""`ao stage end` from an audit's session (design §4.9c *Audits start on a clock* and its outcome table, §4.7,
TD-2053): `findings-filed` names entries whose ids the home gave the run's holder since the run started,
`nothing-found` and `other` give a reason, `other` adds the home's plain board line, and the run record is written as
finished, its start and base standing."""

from __future__ import annotations

import copy
import threading
from datetime import UTC, datetime, timedelta

import pytest

from shiftlead import stage_audit_end, stage_end
from shiftlead.stage_audit_end import end_audit, filed_in_run, is_ref, line_text, named, split_ref
from shiftlead.stage_end import Refused

pytestmark = pytest.mark.unit

ME = "ao-repo-audit-core-docs"
REF = "audit:core/docs"
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
START = "2026-11-25T10:00:00Z"


def run(**over) -> dict:
    return {"started_at": START, "holder": ME, "base": "a" * 40, "offers": 1, "ended": None, **over}


class Store:
    def __init__(self, record):
        self.record = record
        self.writes: list[tuple[str, str, dict]] = []

    def locked(self):
        return threading.RLock()

    def audit(self, team, key):
        return copy.deepcopy(self.record)

    def put_audit(self, team, key, record):
        self.record = copy.deepcopy(dict(record))
        self.writes.append((team, key, self.record))


def given(*ids, by=ME, at="2026-11-25T10:30:00Z"):
    return [{"id": i, "by": by, "at": at} for i in ids]


def _end(store, outcome, reason="", *, caller=ME, team="core", ids=(), lines=None):
    lines = [] if lines is None else lines

    def line(text):
        lines.append(text)
        return "1a2b3c4d"

    return end_audit(
        store, REF, caller, outcome, reason, team=team, given=lambda: list(ids), line=line, now=lambda: NOW
    )


def test_an_audit_reference_is_its_lease():
    assert is_ref("audit:core/docs") and split_ref("audit:core/docs") == ("core", "docs")
    for bad in ("audit:core", "audit:/docs", "audit:core/", "audit:core/docs/x", "TD-12", "pr:3", ""):
        assert not is_ref(bad)


def test_findings_filed_ends_the_run_as_done_with_its_start_and_base_standing():
    store = Store(run())
    got = _end(store, "findings-filed", "filed TD-12 and TD-13", ids=given("TD-12", "TD-13"))
    assert got == {"entry": REF, "outcome": "findings-filed", "went": "done", "repeat": False}
    rec = store.record
    assert rec["holder"] is None and rec["started_at"] == START and rec["base"] == "a" * 40
    assert rec["ended"] == {
        "outcome": "findings-filed",
        "reason": "filed TD-12 and TD-13",
        "at": "2026-11-25T12:00:00Z",
        "by": ME,
    }


def test_findings_filed_names_at_least_one_entry():
    store = Store(run())
    with pytest.raises(Refused, match="at least one entry"):
        _end(store, "findings-filed", "I filed some", ids=given("TD-12"))
    assert store.writes == []


@pytest.mark.parametrize(
    "ids",
    [
        given("TD-12", at="2026-11-25T09:59:59Z"),  # given before the run started
        given("TD-12", by="ao-repo-someone-else"),  # given to another session
        given("TD-99"),  # another id
        [],  # given nothing
    ],
)
def test_an_entry_not_filed_in_this_run_is_refused(ids):
    store = Store(run())
    with pytest.raises(Refused, match="TD-12 was not filed in this run"):
        _end(store, "findings-filed", "TD-12", ids=ids)
    assert store.writes == []


def test_every_named_entry_must_be_the_runs():
    store = Store(run())
    with pytest.raises(Refused, match="TD-14 was not filed"):
        _end(store, "findings-filed", "TD-12, TD-14", ids=given("TD-12"))


@pytest.mark.parametrize("outcome", ["nothing-found", "other"])
def test_nothing_found_and_other_need_a_reason(outcome):
    store = Store(run())
    with pytest.raises(Refused, match="needs a reason"):
        _end(store, outcome, "   ")
    assert store.writes == []


def test_nothing_found_finishes_the_run_and_writes_no_line():
    store, lines = Store(run()), []
    got = _end(store, "nothing-found", "read docs/design 4.9c", lines=lines)
    assert got["went"] == "done" and lines == []
    assert store.record["ended"]["outcome"] == "nothing-found" and "line" not in store.record["ended"]


def test_other_writes_the_homes_plain_line_first_and_keeps_its_id():
    store, lines = Store(run()), []
    got = _end(store, "other", "the  docs tree\nwould not build", lines=lines)
    assert got["went"] == "person"
    assert lines == [
        "The audit docs of team core stopped in its run started 2026-11-25 10:00:00 UTC: the docs tree would not "
        "build. Its next run comes on its clock."
    ]
    assert store.record["ended"]["line"] == "1a2b3c4d" and store.record["holder"] is None


def test_a_line_not_written_writes_nothing():
    store = Store(run())

    def fails(_text):
        raise OSError("board locked")

    with pytest.raises(Refused, match="board line could not be written"):
        end_audit(store, REF, ME, "other", "why", team="core", given=list, line=fails)
    with pytest.raises(Refused, match="board line could not be written"):
        end_audit(store, REF, ME, "other", "why", team="core", given=list, line=lambda _t: None)
    assert store.writes == []


def test_a_stage_outcome_is_refused():
    with pytest.raises(Refused, match="no outcome of an audit"):
        _end(Store(run()), "work-pushed")


def test_a_call_from_a_session_the_run_does_not_name_is_refused():
    with pytest.raises(Refused, match="this run is not yours"):
        _end(Store(run()), "nothing-found", "looked", caller="ao-repo-other")


def test_a_repeated_call_is_answered_with_where_the_run_went():
    store = Store(run())
    _end(store, "nothing-found", "looked")
    got = _end(store, "nothing-found", "looked")
    assert got == {"entry": REF, "outcome": "nothing-found", "went": "done", "repeat": True}
    assert len(store.writes) == 1
    with pytest.raises(Refused, match="the run is over"):
        _end(store, "other", "changed my mind")


def test_a_run_rested_is_over_for_its_last_session():
    store = Store(run(holder=None, ended={"outcome": "lost", "reason": "lost twice", "at": START}))
    with pytest.raises(Refused, match="the run is over"):
        _end(store, "nothing-found", "looked")


def test_no_run_record_and_another_teams_audit_are_refused():
    with pytest.raises(Refused, match="has no run record"):
        _end(Store(None), "nothing-found", "looked")
    with pytest.raises(Refused, match="an audit of team core, not of web"):
        _end(Store(run()), "nothing-found", "looked", team="web")


def test_filed_in_run_reads_the_holders_ids_since_the_start():
    rows = [
        *given("TD-1", at="2026-11-25T09:00:00Z"),
        *given("TD-2", at=START),
        *given("TD-3", by="other"),
        {"id": "TD-4", "by": ME, "at": "not a time"},
    ]
    assert filed_in_run(rows, ME, START) == {"TD-2"}
    assert filed_in_run(rows, ME, None) == set()


def test_named_reads_each_entry_once_in_order():
    assert named("TD-3, TD-1 and TD-3 again; not XTD-9 or TD-0") == ["TD-3", "TD-1"]


def test_the_line_names_a_run_with_no_start_plainly():
    assert (
        line_text("core", "docs", {}, "why")
        == "The audit docs of team core stopped in its run: why. Its next run comes on its clock."
    )


def test_the_call_routes_an_audit_reference_to_the_audit_end(monkeypatch, tmp_path):
    seen = {}

    class FakeStore:
        def __init__(self, root):
            pass

        def flow(self, team):
            return "format: 3\nname: t\nstages: []\n"

    def fake_end_audit(store, ref, caller, outcome, reason, *, team, given, line):
        seen.update(ref=ref, caller=caller, outcome=outcome, team=team, given=callable(given), line=callable(line))
        return {"entry": ref, "outcome": outcome, "went": "done", "repeat": False}

    monkeypatch.setattr(stage_end, "StageStore", FakeStore)
    monkeypatch.setattr(stage_audit_end, "end_audit", fake_end_audit)
    got = stage_end.call(
        root=str(tmp_path),
        directory=str(tmp_path),
        team="core",
        tid=REF,
        caller=ME,
        outcome="nothing-found",
        reason="looked",
    )
    assert got["went"] == "done"
    assert seen == {"ref": REF, "caller": ME, "outcome": "nothing-found", "team": "core", "given": True, "line": True}


def test_the_homes_given_ids_are_read_by_the_repos_origin(monkeypatch, tmp_path):
    from sessionorc import agent_ids, gatesweep

    monkeypatch.setattr(gatesweep, "origin_url", lambda root: "git@github.com:Owner/Repo.git")
    monkeypatch.setattr(agent_ids, "given_of", lambda key: [{"id": "TD-1", "key": key}])
    assert stage_end._given(tmp_path) == [{"id": "TD-1", "key": "owner/repo"}]
    monkeypatch.setattr(gatesweep, "origin_url", lambda root: "")
    assert stage_end._given(tmp_path) == []


def test_a_finished_run_is_due_again_on_its_clock_from_its_start():
    from shiftlead import stage_audit
    from shiftlead.stage_audit import AuditReading

    store = Store(run())
    _end(store, "nothing-found", "looked")
    every = stage_audit.clock("1 days")
    s = AuditReading(may_start=True)
    assert stage_audit.choose(store.record, every, s, NOW) is None
    assert stage_audit.choose(store.record, every, s, NOW + timedelta(hours=22)).name == "start"


def test_a_node_holders_ids_are_matched_by_its_bare_id():
    node = f"{ME}@box"
    assert filed_in_run(given("TD-5", by=ME), node, START) == {"TD-5"}
    assert filed_in_run(given("TD-5", by=node), ME, START) == {"TD-5"}
    assert filed_in_run(given("TD-5", by="ao-repo-other@box"), node, START) == set()


def test_a_repeated_other_writes_no_second_line():
    store, lines = Store(run()), []
    _end(store, "other", "stuck", lines=lines)
    got = _end(store, "other", "stuck", lines=lines)
    assert got["repeat"] and got["went"] == "person" and len(lines) == 1 and len(store.writes) == 1
