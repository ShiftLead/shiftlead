"""Making the acts that only write a stage record (design §4.9c *The home acts only where no session will*, TD-2051),
on a real `shiftlead/state` branch in a scratch repo and its bare origin."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sessionorc import board
from shiftlead.stage_acts import Act, Holder, Reading, choose
from shiftlead.stage_end import ARCHIVE
from shiftlead.stage_make import _offer_again, make, offer, sweep_closed
from shiftlead.stage_start import Work
from shiftlead.stage_work import EntryWork
from shiftlead.stagerecord import OTHER, StageStore, StateError, flow_version, new_record, run_of

TID = "TD-7"
FLOW: dict[str, Any] = {
    "format": 3,
    "name": "new-flow",
    "stages": [
        {"name": "build", "does": "build", "model": "m", "takes": "any", "work-pushed": "review"},
        {"name": "review", "does": "review", "model": "m", "only-when": "protected-files", "ship": "merge"},
        {"name": "polish", "does": "build", "model": "m", "work-pushed": "review"},
    ],
}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)


@pytest.fixture
def store(tmp_path: Path) -> StageStore:
    origin, root = tmp_path / "o.git", tmp_path / "r"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "remote", "add", "origin", str(origin))
    git(root, "commit", "-q", "--allow-empty", "-m", "init")
    git(root, "push", "-q", "origin", "main")
    s = StageStore(root)
    s.ensure_branch()
    return s


def put(store: StageStore, **over: Any) -> dict[str, Any]:
    record = {**new_record(TID, "build-review", "build"), **over}
    store.put_entry(record, "test")
    return record


def act_on(store: StageStore, reading: Reading, doc: dict[str, Any] = FLOW) -> Any:
    record = store.entry(TID)
    act = choose(record, reading)
    assert act is not None
    return make(store, TID, act, reading, doc, "paul")


def test_an_archived_entry_closes_its_record(store):
    put(store, holder="s1", intent={"ask": "?"})
    assert act_on(store, Reading(entry="archived")).made
    got = store.entry(TID)
    assert got["closed_at"] and got["holder"] is None and got["intent"] is None


def test_a_renumbered_entry_moves_its_record_in_one_commit(store):
    put(store, holder="s1")
    assert act_on(store, Reading(renumbered_to="TD-9")).made
    assert store.entry(TID) is None
    assert store.entry("TD-9")["id"] == "TD-9"


def test_a_renumber_renames_its_copies_and_rewrites_their_id_in_the_same_commit(store):
    put(store, closed_at="2026-10-01T00:00:00Z", stage="polish")
    offer_it(store)  # one closed copy, and a live record
    store.write({"closed/TD-9@2026-10-01.json": json.dumps({"id": "TD-9"})}, "an old TD-9's copy")
    tip = store.tip()
    assert act_on(store, Reading(renumbered_to="TD-9")).made
    assert commits_since(store, tip) == 1
    names = store._list(store.tip(), "closed")
    assert names == ["closed/TD-9@2026-10-01-2.json", "closed/TD-9@2026-10-01.json"]
    assert json.loads(store._read(store.tip(), "closed/TD-9@2026-10-01-2.json"))["id"] == "TD-9"
    assert store.closed(TID) == []


def test_a_renumber_keeps_a_days_copies_in_their_order(store):
    for name, at in (("", "2026-10-01T01:00:00Z"), ("-2", "2026-10-01T02:00:00Z")):
        store.write({f"closed/{TID}@2026-10-01{name}.json": json.dumps({"id": TID, "closed_at": at})}, "a copy")
    put(store)
    assert act_on(store, Reading(renumbered_to="TD-9")).made
    first = json.loads(store._read(store.tip(), "closed/TD-9@2026-10-01.json"))
    assert first == {"id": "TD-9", "closed_at": "2026-10-01T01:00:00Z"}


def test_a_renumber_onto_a_record_writes_nothing(store):
    put(store)
    store.put_entry(new_record("TD-9", "f", "build"), "there")
    got = act_on(store, Reading(renumbered_to="TD-9"))
    assert not got.made and "already" in got.why
    assert store.entry(TID) is not None


def test_a_design_merged_with_open_parts_waits_for_them(store):
    put(store, pr=4, holder="s1")
    assert act_on(store, Reading(pr_state="merged", design=True, open_parts=2)).made
    got = store.entry(TID)
    assert got["waits"] == "parts" and got["holder"] is None


def test_an_entry_carrying_the_gate_is_marked_waiting(store):
    put(store, holder="s1")
    assert act_on(store, Reading(gate=True)).made
    assert store.entry(TID)["waits"] == "person"


def test_a_rewritten_record_keeps_its_stage_and_holder_and_only_the_counts_the_flow_has(store):
    put(store, holder="s1", counts={"build:work-pushed": 2, "build:gone": 1, "dropped:ship": 1})
    assert act_on(store, Reading(flow_current=False)).made
    got = store.entry(TID)
    assert (got["flow"], got["stage"], got["holder"]) == ("new-flow", "build", "s1")
    assert got["counts"] == {"build:work-pushed": 2}


def test_the_persons_answer_makes_its_move_and_keeps_the_words(store):
    put(store, waits="person", stage="build", moves=3, answers={"Polish it": "polish", OTHER: None})
    assert act_on(store, Reading(gate=False, lifted="Polish it")).made
    got = store.entry(TID)
    assert (got["stage"], got["waits"], got["answer"], got["offers"]) == ("polish", None, "Polish it", 0)
    assert got["moves"] == 3, "an answer's move is not counted"
    assert got["history"][-1]["by"] == "paul"


def test_something_else_goes_back_to_the_stage_that_asked_with_the_words(store):
    put(store, waits="person", stage="build", answers={"Polish it": "polish", OTHER: None})
    assert act_on(store, Reading(lifted="Something else: try the cache")).made
    got = store.entry(TID)
    assert (got["stage"], got["answer"]) == ("build", "Something else: try the cache")


@pytest.mark.parametrize("label", ["Carry on", "Something else: use a smaller batch"])
def test_an_answer_at_a_limit_takes_the_stopped_move_and_restarts_its_counts(store, label):
    put(
        store,
        waits="person",
        stage="build",
        moves=9,
        counts={"build:work-pushed": 3, "review:ship": 1},
        blocked={"to": "polish", "count": "build:work-pushed"},
        answers={"Carry on": {"blocked": True}, OTHER: None},
    )
    assert act_on(store, Reading(lifted=label)).made
    got = store.entry(TID)
    assert (got["stage"], got["moves"], got["blocked"], got["answer"]) == ("polish", 0, None, label)
    assert got["counts"] == {"review:ship": 1}


def test_an_answer_that_names_no_stage_of_the_flow_is_asked_once_more(store):
    put(store, waits="person", answers={"Gone": "nowhere", OTHER: None})
    assert act_on(store, Reading(lifted="Gone")).made
    got = store.entry(TID)
    assert got["stage"] == "build", "the record stays until the new answer"
    assert list(got["intent"]["answers"])[:3] == [
        "build — a session takes it to this stage",
        "review — a session takes it to this stage",
        "polish — a session takes it to this stage",
    ]


def test_a_merged_entry_still_open_asks_with_the_archive_answer_and_ends_the_holder(store):
    put(store, pr=4, holder="s1", waits="merging")
    got = act_on(store, Reading(pr_state="merged"))
    assert got.made and got.end == "s1"
    record = store.entry(TID)
    assert record["holder"] is None and record["waits"] is None
    assert record["intent"]["answers"][ARCHIVE] == {"archive": True}


def test_a_closed_pull_request_asks_and_its_answer_starts_from_no_pull_request(store):
    put(store, pr=4, branch="td7", holder="s1")
    assert act_on(store, Reading(pr_state="closed")).end == "s1"
    record = store.entry(TID)
    back = next(a for a in record["intent"]["answers"] if a.startswith("Back to build"))
    label = back.split(" — ")[0]
    record.update(intent=None, waits="person", answers={label: "build", OTHER: None})
    store.put_entry(record, "landed")
    assert act_on(store, Reading(pr_state="closed", lifted=label)).made
    got = store.entry(TID)
    assert (got["pr"], got["branch"], got["waits"]) == (None, None, None)
    assert choose(got, Reading(may_start=True, within_size=True)) == Act("offer")


def test_an_entry_already_carrying_a_gate_is_not_asked_again(store):
    put(store, pr=4, holder="s1")
    assert act_on(store, Reading(pr_state="closed", gate=True)).made
    got = store.entry(TID)
    assert got["waits"] == "person" and got["intent"] is None


def test_an_answered_question_leaves_no_mark_to_refuse_a_later_gates_answer(store):
    asked = {"nonce": "n1", "ask": "?", "context": "c", "answers": {}}
    put(store, waits="person", asked=asked, answers={"Polish it": "polish", OTHER: None})
    assert act_on(store, Reading(lifted="Polish it", lifted_for="n1")).made
    assert store.entry(TID)["asked"] is None
    assert act_on(store, Reading(gate=True)).made  # a gate placed by hand: marked as waiting
    assert choose(store.entry(TID), Reading(lifted="Go")) == Act("answer")


def test_a_gate_met_by_a_move_to_the_person_drops_the_earlier_question(store):
    put(store, pr=4, asked={"nonce": "n1"}, answers={"Old": "polish"})
    assert act_on(store, Reading(pr_state="closed", gate=True)).made
    got = store.entry(TID)
    assert (got["waits"], got["asked"], got["answers"]) == ("person", None, None)


def test_a_stage_gone_asks_with_the_flows_stages(store):
    put(store, stage="dropped", moves=2, holder="s1")
    got = act_on(store, Reading(stage_known=False))
    assert got.made and got.end == "s1"
    assert "polish — a session takes it to this stage" in store.entry(TID)["intent"]["answers"]


def test_a_lost_gate_is_asked_again_in_the_same_words_under_a_new_mark(store):
    asked = {"nonce": "n1", "ask": "Why?", "context": "c", "answers": {"Go — a session goes": "build"}}
    put(store, waits="person", asked=asked, blocked={"to": "polish", "count": "build:work-pushed"})
    assert act_on(store, Reading()).made
    intent = store.entry(TID)["intent"]
    assert (intent["ask"], intent["context"]) == ("Why?", "c") and intent["nonce"] != "n1"
    assert "Go — a session goes" in intent["answers"]
    assert store.entry(TID)["blocked"] == {"to": "polish", "count": "build:work-pushed"}


def test_a_lift_of_an_earlier_question_is_not_applied_to_the_new_one(store):
    put(store, waits="person", asked={"nonce": "new"}, answers={"Polish it": "polish", OTHER: None})
    stale = Reading(gate=True, lifted="Polish it", lifted_for="old")
    assert choose(store.entry(TID), stale) is None
    assert act_on(store, Reading(lifted="Polish it", lifted_for="new")).made


def test_the_archive_answer_archives_and_leaves_the_record_until_the_ledger_reads_it(store, monkeypatch):
    before = put(store, waits="person", answers={"Archive the entry": {"archive": True}, OTHER: None})
    asked = []
    monkeypatch.setattr(store, "archive", lambda tid, why: asked.append((tid, why)) or {"pr": 5})
    assert act_on(store, Reading(lifted="Archive the entry")).made
    assert asked == [(TID, "the person's answer: Archive the entry")]
    assert store.entry(TID) == before
    assert act_on(store, Reading(entry="archived")).made and store.entry(TID)["closed_at"]


DESIGN_DONE = Reading(pr_state="merged", design=True, had_parts=True)


def test_a_design_left_open_after_its_last_part_is_archived_by_the_home(store, monkeypatch):
    before = put(store, pr=4, waits="parts")
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(store, "archive", lambda tid, why: asked.append((tid, why)) or {"pr": 5})
    assert act_on(store, DESIGN_DONE).made
    assert [tid for tid, _ in asked] == [TID]
    assert store.entry(TID) == before  # it closes when the ledger reads the entry archived
    assert choose(store.entry(TID), replace(DESIGN_DONE, archive_open=True)) is None
    assert act_on(store, replace(DESIGN_DONE, entry="archived")).made and store.entry(TID)["closed_at"]


def test_a_design_archive_the_ledger_refuses_leaves_the_record(store, monkeypatch):
    before = put(store, pr=4, waits="parts")

    def refuse(_tid: str, _why: str) -> None:
        raise board.Refused("no")

    monkeypatch.setattr(store, "archive", refuse)
    got = act_on(store, DESIGN_DONE)
    assert not got.made and "could not be archived" in got.why
    assert store.entry(TID) == before


def test_an_archive_the_ledger_refuses_leaves_the_record_waiting(store, monkeypatch):
    before = put(store, waits="person", answers={"Archive the entry": {"archive": True}, OTHER: None})

    def refuse(*_a: Any) -> dict[str, Any]:
        raise board.Refused("parts are open")

    monkeypatch.setattr(store, "archive", refuse)
    got = act_on(store, Reading(lifted="Archive the entry"))
    assert not got.made and "parts are open" in got.why and store.entry(TID) == before


def test_a_lift_after_a_hand_merge_is_applied_to_nothing_and_the_merge_is_reconciled(store, monkeypatch):
    put(store, pr=4, branch="td7-work", waits="person", answers={"Polish it": "build"}, asked={"nonce": "n1"})
    seen = []

    def note(tid, label, mark):
        seen.append((tid, label, mark, store.entry(TID)["waits"]))
        return {"commit": "abc"}

    monkeypatch.setattr(store, "note_unapplied", note)
    reading = Reading(pr_state="merged", lifted="Polish it", lifted_for="n1")
    assert act_on(store, reading).made
    assert seen == [(TID, "Polish it", "n1", "person")]  # the Log first, with the record still waiting
    record = store.entry(TID)
    assert record["stage"] == "build" and record["pr"] == 4 and record["branch"] == "td7-work"
    assert record["waits"] is None and record["asked"] is None and record["answers"] is None
    assert choose(record, Reading(pr_state="merged")) == Act("reconcile", "merged-entry-open")


def test_a_log_that_cannot_be_written_leaves_the_record_waiting(store, monkeypatch):
    put(store, pr=4, waits="person", answers={"Polish it": "build"}, asked={"nonce": "n1"})

    def refused(*_a):
        raise board.Refused("the forge is away")

    monkeypatch.setattr(store, "note_unapplied", refused)
    got = act_on(store, Reading(pr_state="merged", lifted="Polish it", lifted_for="n1"))
    assert not got.made and "the forge is away" in got.why
    assert store.entry(TID)["waits"] == "person"


def test_a_question_asked_after_the_merge_is_answered_as_usual(store, monkeypatch):
    put(store, pr=4, waits="person", answers={ARCHIVE: {"archive": True}}, asked={"nonce": "n1", "after_merge": True})
    monkeypatch.setattr(store, "note_unapplied", lambda *_a: pytest.fail("this answer is about the merge"))
    archived = []
    monkeypatch.setattr(store, "archive", lambda tid, why: archived.append(tid) or {"commit": "abc"})
    assert act_on(store, Reading(pr_state="merged", lifted=ARCHIVE, lifted_for="n1")).made
    assert archived == [TID]


def test_a_gate_met_by_the_merged_question_has_its_answer_applied(store, monkeypatch):
    put(store, pr=4, branch="td7-work")
    assert act_on(store, Reading(pr_state="merged", gate=True)).made
    record = store.entry(TID)
    assert record["waits"] == "person" and record["asked"] is None and record["gate_after_merge"] is True
    monkeypatch.setattr(store, "note_unapplied", lambda *_a: pytest.fail("this gate was met after the merge"))
    assert act_on(store, Reading(pr_state="merged", lifted="Something else: go on")).made
    record = store.entry(TID)
    assert (
        record["waits"] is None and record["gate_after_merge"] is False and record["answer"] == "Something else: go on"
    )


def test_a_stage_with_nothing_to_read_passes_as_ship_to_merge_with_the_head(store):
    put(store, stage="review", pr=4, branch="td7")
    assert act_on(store, Reading(nothing_to_read=True, head="a" * 40)).made
    got = store.entry(TID)
    assert got["waits"] == "merging" and got["merging"]["head"] == "a" * 40
    assert got["history"][-1]["by"] == "home"
    assert "findings" not in got["history"][-1] and "run" not in got["history"][-1], "a pass is no review (§4.9c)"
    assert got["verdicts"] == {"review": {"head": "a" * 40, "passed": True}}


def test_a_pass_to_merge_with_no_head_read_writes_nothing(store):
    before = put(store, stage="review", pr=4)
    assert not act_on(store, Reading(nothing_to_read=True)).made
    assert store.entry(TID) == before


def test_a_pass_needs_an_only_when_stage(store):
    before = put(store, stage="build")
    assert not act_on(store, Reading(nothing_to_read=True, head="a" * 40)).made
    assert store.entry(TID) == before


def test_a_record_that_moved_after_the_reading_is_not_overwritten(store):
    put(store, holder="s1")
    reading = Reading(holder=Holder(ended=True), gate=True)
    act = choose(store.entry(TID), reading)
    moved = put(store, holder=None, waits="merging", stage="review")
    assert not make(store, TID, act, reading, FLOW, "paul").made
    assert store.entry(TID) == moved


def _moved_waiting(store, **kw):
    return put(store, pr=4, branch="td7-work", waits="person", answers={OTHER: None}, asked={"nonce": "n1"}, **kw)


CHECKED = Reading(pr_state="merged")


def test_a_live_checks_merge_closes_its_record_with_no_carried_and_its_next_check_starts_fresh(store):
    put(store, holder=None, pr=4, branch="td7-check", check_waits=4, waits="merging", merging={"head": "a" * 40})
    got = act_on(store, CHECKED)
    assert got.made
    closed = store.entry(TID)
    assert closed["closed_at"] and closed["carried"] is None and closed["waits"] is None and closed["merging"] is None
    got, started, _ = offer_it(store, replace(READY, live_check=True, carried_open=True))
    assert got.made and started == [("build", Work(TID, live_check=True))]  # a new branch: none carried over


@pytest.mark.parametrize("where", ["asked", "intent"])
def test_a_live_check_merged_by_hand_clears_the_homes_own_question_first(store, monkeypatch, where):
    put(store, pr=4, check_waits=4, waits="person" if where == "asked" else None, **{where: {"nonce": "n1"}})
    seen = []

    def clear(tid, person, nonce, why):
        seen.append((tid, person, nonce, why, store.entry(TID)["clearing"], store.entry(TID)["closed_at"]))
        return {"commit": "abc"} if where == "asked" else {"nothing": True}  # an unlanded intent clears nothing

    monkeypatch.setattr(store, "clear_question", clear)
    assert act_on(store, replace(CHECKED, gate=where == "asked")).made
    assert seen == [(TID, "paul", "n1", "its entry waits behind the blocker its live check merged", "n1", None)]
    closed = store.entry(TID)
    assert closed["closed_at"] and closed["clearing"] is None and closed["intent"] is None and closed["asked"] is None


def test_a_live_check_whose_clear_is_refused_waits_for_the_next_pass(store, monkeypatch):
    put(store, pr=4, check_waits=4, waits="person", asked={"nonce": "n1"})

    def refused(*_a):
        raise board.Refused("the forge is away")

    monkeypatch.setattr(store, "clear_question", refused)
    got = act_on(store, replace(CHECKED, gate=True))
    assert not got.made and "the forge is away" in got.why
    record = store.entry(TID)
    assert record["clearing"] == "n1" and not record.get("closed_at")
    monkeypatch.setattr(store, "clear_question", lambda *_a: {"nothing": True})  # a crash after the clear merged
    assert act_on(store, CHECKED).made and store.entry(TID)["closed_at"]


def test_a_live_check_with_no_question_of_the_homes_closes_at_once_and_clears_nothing(store, monkeypatch):
    put(store, pr=4, check_waits=4, waits="person", asked=None)  # a decision the check's own pull request wrote
    monkeypatch.setattr(store, "clear_question", lambda *_a: pytest.fail("not this record's question"))
    assert act_on(store, replace(CHECKED, gate=True)).made and store.entry(TID)["closed_at"]


def test_another_pull_requests_merge_does_not_act_on_the_mark(store):
    put(store, pr=5, check_waits=4)
    act = choose(store.entry(TID), CHECKED)
    assert act is not None and act.case == "merged-entry-open"


def test_a_moved_entry_closes_only_after_its_question_is_cleared(store, monkeypatch):
    _moved_waiting(store)
    seen = []

    def clear(tid, person, nonce):
        seen.append((tid, person, nonce, store.entry(TID)["clearing"], store.entry(TID)["closed_at"]))
        return {"commit": "abc"}

    monkeypatch.setattr(store, "clear_question", clear)
    reading = Reading(team_moved=True, gate=True, pr_state="open")
    got = make(store, TID, Act("reconcile", "team-moved"), reading, FLOW, "paul")
    assert got.made
    assert seen == [(TID, "paul", "n1", "n1", None)]  # the intent is on the record, and the record open, at the PR
    closed = store.entry(TID)
    assert closed["closed_at"] and closed["clearing"] is None and closed["waits"] is None
    assert closed["carried"] == {"branch": "td7-work", "pr": 4}


def test_a_refused_clear_leaves_the_record_waiting_for_the_next_pass(store, monkeypatch):
    _moved_waiting(store)

    def refused(*_a):
        raise board.Refused("the forge is away")

    monkeypatch.setattr(store, "clear_question", refused)
    act = Act("reconcile", "team-moved")
    got = make(store, TID, act, Reading(team_moved=True, gate=True), FLOW, "paul")
    assert not got.made and "the forge is away" in got.why
    record = store.entry(TID)
    assert record["waits"] == "person" and record["clearing"] == "n1" and not record.get("closed_at")

    monkeypatch.setattr(store, "clear_question", lambda *_a: {"nothing": True})  # as after a crash past the merge
    assert make(store, TID, act, Reading(team_moved=True), FLOW, "paul").made
    assert store.entry(TID)["closed_at"]


def test_a_moved_entry_under_a_gate_this_record_did_not_ask_clears_nothing(store, monkeypatch):
    put(store, pr=4, waits="person", answers=None, asked=None)
    monkeypatch.setattr(store, "clear_question", lambda *_a: pytest.fail("not this record's question"))
    assert make(store, TID, Act("reconcile", "team-moved"), Reading(team_moved=True, gate=True), FLOW, "paul").made
    assert store.entry(TID)["closed_at"]


def test_a_moved_entry_closes_here_and_its_new_team_carries_on_from_its_pull_request(store):
    put(store, holder="s1", branch="td7-work", pr=4, team="old")
    got = act_on(store, Reading(team_moved=True, pr_state="open"))
    assert got.made and got.end == "s1"
    closed = store.entry(TID)
    assert closed["closed_at"] and closed["holder"] is None
    ready = Reading(pickable=True, may_start=True, within_size=True, carried_open=True)
    started: list[Work] = []
    made = offer(
        store,
        TID,
        choose(closed, ready),
        ready,
        FLOW,
        lambda _k, w: started.append(w) or "s2",
        lambda *_a: None,
        team="new",
    )
    assert made.made and started == [Work(TID, "td7-work", 4)]
    record = store.entry(TID)
    assert (record["team"], record["branch"], record["pr"], record["holder"]) == ("new", "td7-work", 4, "s2")
    assert "carried" not in record and record["closed_at"] is None


@pytest.mark.parametrize("live", [False, True])
def test_carried_work_needs_a_live_reading_and_yields_to_a_fresher_pull_request(store, live):
    put(store, holder="s1", branch="td7-old", pr=4, team="old")
    assert act_on(store, Reading(team_moved=True, pr_state="open")).made
    work = EntryWork("take", {"branch": "td7-new", "number": 9}) if live else EntryWork("none")
    ready = Reading(pickable=True, may_start=True, within_size=True, carried_open=live, work=work)
    started: list[Work] = []
    start = lambda _k, w: started.append(w) or "s2"  # noqa: E731
    assert offer(store, TID, choose(store.entry(TID), ready), ready, FLOW, start, lambda *_a: None, team="new").made
    assert started == [Work(TID, "td7-new", 9) if live else Work(TID, None, None)]


def test_a_moved_entry_with_nothing_pushed_carries_nothing(store):
    put(store, holder="s1", team="old")
    assert act_on(store, Reading(team_moved=True)).made
    assert store.entry(TID)["carried"] is None


def test_a_moved_entry_whose_pull_request_is_over_carries_nothing(store):
    put(store, holder="s1", branch="td7-work", pr=4, waits="parts")
    assert act_on(store, Reading(team_moved=True, pr_state="merged", design=True, open_parts=1)).made
    assert store.entry(TID)["carried"] is None


def test_a_record_with_no_move_re_enters_by_the_way_in_keeping_its_work(store):
    put(store, stage="dropped", flow="old-flow", holder="s1", branch="td7", pr=4, offers=2)
    got = act_on(store, Reading(stage_known=False))
    assert got.made and got.end == "s1"
    record = store.entry(TID)
    assert (record["stage"], record["flow"], record["holder"], record["offers"]) == ("build", "new-flow", None, 0)
    assert (record["branch"], record["pr"]) == ("td7", 4)
    assert record["history"][-1]["outcome"] == "re-enter"


def test_a_design_entry_re_enters_at_the_stage_that_takes_designs(store):
    doc = {
        **FLOW,
        "stages": [{"name": "design", "does": "design", "model": "m", "takes": "design-first"}, *FLOW["stages"]],
    }
    put(store, stage="dropped", holder="s1")
    assert act_on(store, Reading(stage_known=False, design=True), doc).made
    assert store.entry(TID)["stage"] == "design"


def test_a_re_entry_with_no_way_in_writes_nothing(store):
    before = put(store, stage="dropped", holder="s1")
    doc = {**FLOW, "stages": [{"name": "review", "does": "review", "model": "m"}]}
    assert not act_on(store, Reading(stage_known=False), doc).made
    assert store.entry(TID) == before


@pytest.mark.parametrize("holder", [Holder(ended=True), Holder(lease_lapsed=True), Holder(idle_for=timedelta(hours=3))])
def test_a_first_loss_clears_the_holder_and_counts_the_offer(store, holder):
    put(store, holder="s1", offers=1)
    got = act_on(store, Reading(holder=holder, may_start=True))
    assert got.made and got.end == "s1"
    record = store.entry(TID)
    assert (record["holder"], record["offers"], record["intent"]) == (None, 2, None)


def test_a_holder_ended_by_a_stop_spends_no_offer(store):
    put(store, holder="s1", offers=1)
    assert act_on(store, Reading(holder=Holder(ended=True, stopped=True), may_start=True)).made
    record = store.entry(TID)
    assert (record["holder"], record["offers"]) == (None, 1)


def test_a_second_loss_goes_to_the_person_with_the_stage_to_start_again(store):
    put(store, holder="s1", offers=2)
    got = act_on(store, Reading(holder=Holder(ended=True), may_start=True))
    assert got.made and got.end == "s1"
    record = store.entry(TID)
    assert record["holder"] is None and record["offers"] == 2
    assert "Back to build — a session starts this stage again" in record["intent"]["answers"]


def commits_since(store: StageStore, tip: str | None) -> int:
    got = subprocess.run(
        ["git", "-C", str(store.root), "rev-list", "--count", f"{tip}..{store.tip()}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(got.stdout.strip())


def test_closed_records_move_to_their_copies_after_thirty_days_in_one_commit(store):
    now = datetime(2026, 11, 23, tzinfo=UTC)
    old = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    young = (now - timedelta(days=29)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for tid, closed in (("TD-1", old), ("TD-2", old), ("TD-3", young), ("TD-4", None)):
        store.put_entry({**new_record(tid, "f", "build"), "closed_at": closed}, "test")
    tip = store.tip()
    before = {t: store._read(tip, f"entries/{t}.json") for t in ("TD-1", "TD-2")}
    assert sweep_closed(store, now) == ["TD-1", "TD-2"]
    assert sorted(store.entries()) == ["TD-3", "TD-4"], "the pass's reading ignores closed/"
    assert commits_since(store, tip) == 1
    day = old[:10]
    for t in ("TD-1", "TD-2"):
        assert store._read(store.tip(), f"closed/{t}@{day}.json") == before[t], "moved with its bytes unchanged"
        assert [c["closed_at"] for c in store.closed(t)] == [old]


def test_a_second_copy_on_one_day_takes_2_and_is_printed_after_the_first(store):
    first, second = "2026-11-01T09:00:00Z", "2026-11-01T17:00:00Z"
    put(store, closed_at=first, stage="polish")
    offer_it(store)  # reopened: its first closing is copied
    store.put_entry({**store.entry(TID), "closed_at": second}, "closed again")
    offer_it(store)
    names = store._list(store.tip(), "closed")
    assert names == [f"closed/{TID}@2026-11-01-2.json", f"closed/{TID}@2026-11-01.json"]
    assert [c["closed_at"] for c in store.closed(TID)] == [first, second]


def test_stage_show_closed_prints_the_copies_by_closed_at(store):
    from shiftlead.stage_end import show

    store.write({f"closed/{TID}@2026-11-01.json": json.dumps({"id": TID, "closed_at": "2026-11-01T10:00:00Z"})}, "a")
    store.write({f"closed/{TID}@2026-10-09.json": json.dumps({"id": TID, "closed_at": "2026-10-09T10:00:00Z"})}, "b")
    got = show(root=str(store.root), tid=TID, closed=True)
    assert got["entry"] == TID
    assert [c["closed_at"] for c in got["closed"]] == ["2026-10-09T10:00:00Z", "2026-11-01T10:00:00Z"]
    assert show(root=str(store.root), tid="TD-8", closed=True) == {"entry": "TD-8", "closed": []}
    assert "refused" in show(root=str(store.root), tid="nope", closed=True)


def test_copies_are_read_by_closed_at_never_by_name(store):
    store.write({f"closed/{TID}@2026-11-01.json": json.dumps({"id": TID, "closed_at": "2026-11-01T10:00:00Z"})}, "a")
    store.write({f"closed/{TID}@2026-10-09.json": json.dumps({"id": TID, "closed_at": "2026-10-09T10:00:00Z"})}, "b")
    store.write({"closed/TD-70@2026-10-01.json": json.dumps({"id": "TD-70", "closed_at": "x"})}, "another entry")
    assert [c["closed_at"] for c in store.closed(TID)] == ["2026-10-09T10:00:00Z", "2026-11-01T10:00:00Z"]


def test_a_malformed_closed_date_does_not_stop_the_sweep(store):
    now = datetime(2026, 11, 23, tzinfo=UTC)
    store.put_entry({**new_record("TD-1", "f", "build"), "closed_at": "yesterday"}, "test")
    store.put_entry({**new_record("TD-2", "f", "build"), "closed_at": "2026-01-01T00:00:00Z"}, "test")
    assert sweep_closed(store, now) == ["TD-2"]


READY = Reading(pickable=True, may_start=True, within_size=True)


def offer_it(store: StageStore, reading: Reading = READY, refused: str | None = None, holder: str | None = "s9") -> Any:
    started: list[tuple[str, Work]] = []
    claims: list[tuple[str, str]] = []

    def start(key: str, work: Work) -> str | None:
        started.append((key, work))
        return holder

    def claim(who: str, tid: str) -> str | None:
        claims.append((who, tid))
        return refused

    act = choose(store.entry(TID), reading)
    assert act is not None and act.name == "offer"
    return offer(store, TID, act, reading, FLOW, start, claim, team="t"), started, claims


def test_a_first_offer_starts_the_way_in_claims_and_writes_the_record(store):
    got, started, claims = offer_it(store)
    assert got.made and started == [("build", Work(TID))] and claims == [("s9", TID)]
    record = store.entry(TID)
    assert (record["flow"], record["stage"], record["holder"], record["offers"]) == ("new-flow", "build", "s9", 1)
    assert record["team"] == "t"


def test_a_first_offer_tells_the_session_a_live_check_is_one(store):
    got, started, _ = offer_it(store, replace(READY, live_check=True))
    assert got.made and started == [("build", Work(TID, live_check=True))]


def test_a_first_offer_carries_the_pull_request_that_is_its_work(store):
    work = EntryWork("take", {"number": 12, "branch": "td7-x"})
    got, started, _ = offer_it(store, replace(READY, work=work))
    assert got.made and started[0][1] == Work(TID, "td7-x", 12)
    record = store.entry(TID)
    assert (record["branch"], record["pr"]) == ("td7-x", 12)


def test_an_offer_after_a_loss_keeps_the_count_and_the_work(store):
    put(store, stage="polish", offers=2, branch="b", pr=3)
    got, started, _ = offer_it(store)
    assert got.made and started == [("polish", Work(TID, "b", 3))]
    record = store.entry(TID)
    assert (record["holder"], record["offers"], record["pr"]) == ("s9", 2, 3)


def test_an_offer_after_a_refused_merge_tells_the_session_the_failing_row(store):
    step = {"from": "review", "outcome": "refused", "reason": "the merge gate failed on ci", "to": "build"}
    put(store, stage="build", branch="b", pr=3, history=[step])
    got, started, _ = offer_it(store)
    came = "the merge gate failed on ci (`refused` at `review`)"
    assert got.made and started == [("build", Work(TID, "b", 3, came))]


def test_an_offer_after_the_persons_answer_gives_their_words_and_what_raised_the_question(store):
    history = [
        {"from": "review", "outcome": "refused", "reason": "the merge gate failed on ci", "to": "person"},
        {"from": "review", "outcome": "answer", "reason": "fix the flaky test", "to": "build"},
    ]
    put(store, stage="build", history=history, answer="fix the flaky test")
    got, started, _ = offer_it(store)
    work = started[0][1]
    assert got.made and work.came == "the merge gate failed on ci (`refused` at `review`)"
    assert work.answer == "fix the flaky test"


def test_an_answer_with_no_move_to_the_person_before_it_tells_no_older_reason(store):
    history = [
        {"from": "build", "outcome": "work-pushed", "reason": "old", "to": "review"},
        {"from": "review", "outcome": "answer", "reason": "go on", "to": "build"},
    ]
    put(store, stage="build", history=history, answer="go on")
    _, started, _ = offer_it(store)
    assert (started[0][1].came, started[0][1].answer) == (None, "go on")


def test_an_offer_tells_no_reason_for_a_move_into_another_stage(store):
    put(store, stage="polish", history=[{"from": "build", "outcome": "work-pushed", "reason": "x", "to": "review"}])
    _, started, _ = offer_it(store)
    assert started[0][1].came is None


def test_a_reopened_entry_is_offered_afresh_with_nothing_carried_over(store):
    put(store, stage="polish", closed_at="2026-11-01T00:00:00Z", branch="old", pr=3, offers=2)
    got, started, _ = offer_it(store)
    assert got.made and started == [("build", Work(TID))]
    record = store.entry(TID)
    assert record["closed_at"] is None and record["pr"] is None and record["offers"] == 1


def test_a_reopen_copies_the_closed_record_in_the_commit_that_writes_the_fresh_one(store):
    put(store, stage="polish", closed_at="2026-11-01T00:00:00Z", pr=3)
    text = store._read(store.tip(), f"entries/{TID}.json")
    tip = store.tip()
    assert offer_it(store)[0].made
    assert commits_since(store, tip) == 1
    assert store._read(store.tip(), f"closed/{TID}@2026-11-01.json") == text
    assert store.entry(TID)["closed_at"] is None


def test_a_first_offer_copies_nothing(store):
    assert offer_it(store)[0].made
    assert store._list(store.tip(), "closed") == []


def test_no_session_started_writes_nothing(store):
    got, _, claims = offer_it(store, holder=None)
    assert not got.made and got.end is None and claims == []
    assert store.entry(TID) is None


def test_a_refused_claim_writes_nothing_and_names_the_session_to_end(store):
    got, _, _ = offer_it(store, refused="claimed by another")
    assert not got.made and got.end == "s9" and "claimed by another" in got.why
    assert store.entry(TID) is None


def test_a_record_that_cannot_be_written_names_the_session_to_end(store, monkeypatch):
    def refuse(*_a: Any, **_k: Any) -> str:
        raise StateError("no push")

    monkeypatch.setattr(store, "put_entry", refuse)
    got, _, _ = offer_it(store)
    assert not got.made and got.end == "s9" and "no push" in got.why


def test_any_failure_after_the_start_names_the_session_to_end(store):
    def broken(*_a: Any) -> str | None:
        raise ValueError("a bad reply")

    got = offer(store, TID, choose(None, READY), READY, FLOW, lambda *_a: "s9", broken, team="t")
    assert not got.made and got.end == "s9" and "a bad reply" in got.why
    assert store.entry(TID) is None


def test_an_offer_whose_record_moved_starts_nothing(store):
    act = choose(None, READY)
    put(store, holder="other")
    got = offer(store, TID, act, READY, FLOW, lambda *_a: pytest.fail("started"), lambda *_a: None, team="t")
    assert not got.made and store.entry(TID)["holder"] == "other"


SUMS = {"opus": {"input": 10, "output": 2, "turns": 3, "unweighed": 0, "figure": {"≈$": 0.4}}}


def _offer_spent(store: StageStore, spent: Any, holder: str = "s9", refused: str | None = None) -> Any:
    act = choose(store.entry(TID), READY)
    return offer(store, TID, act, READY, FLOW, lambda *_a: holder, lambda *_a: refused, team="t", spent=spent)


def test_an_offer_keeps_the_holders_sums_under_its_bare_id(store):
    asked: list[str] = []
    got = _offer_spent(store, lambda sid: asked.append(sid) or SUMS, holder="s9@node")
    assert got.made and asked == ["s9"]
    assert store.entry(TID)["spent_before"] == {"s9": SUMS}


def test_an_offer_to_a_reused_id_replaces_its_value_and_keeps_the_others(store):
    put(store, stage="build", spent_before={"s9": {"old": {}}, "s1": SUMS})
    assert _offer_spent(store, lambda _sid: {}).made  # an id never seen reads as zero
    assert store.entry(TID)["spent_before"] == {"s9": {}, "s1": SUMS}


def _boom(_sid: str) -> Any:
    raise OSError("no seat ledger")


@pytest.mark.parametrize("spent", [None, _boom])
def test_an_offer_with_no_reading_is_made_and_drops_the_ids_value(store, spent):
    put(store, stage="build", spent_before={"s9": SUMS, "s1": SUMS})
    assert _offer_spent(store, spent).made
    record = store.entry(TID)
    assert record["holder"] == "s9" and record["spent_before"] == {"s1": SUMS}


def test_a_refused_claim_writes_no_sums(store):
    got = _offer_spent(store, lambda _sid: SUMS, refused="held elsewhere")
    assert not got.made and store.entry(TID) is None


# -- the flow's content hash (§4.9c *The flow's content hash*, TD-2158) -------------------------------------------

VERSION = flow_version("format: 3\nname: f\n", [{"stage": "build", "text": "Build — it."}])


def test_an_offer_writes_its_hash_and_keeps_the_text_once_in_its_own_commit(store, monkeypatch):
    writes: list[list[str]] = []
    real = store.write
    monkeypatch.setattr(store, "write", lambda changes, msg: writes.append(sorted(changes)) or real(changes, msg))
    act = choose(None, READY)
    assert offer(store, TID, act, READY, FLOW, lambda *_a: "s9", lambda *_a: None, team="t", version=VERSION).made
    path = f"flows/versions/{VERSION[1]}.json"
    assert writes == [[f"entries/{TID}.json", path]], "the text and the record in one commit"
    assert store.entry(TID)["flow_hash"] == VERSION[1] and store.version(VERSION[1]) == VERSION[0]
    other = "TD-8"
    got = offer(store, other, act, READY, FLOW, lambda *_a: "s8", lambda *_a: None, team="u", version=VERSION)
    assert got.made and writes[-1] == [f"entries/{other}.json"], "another team's offer of one text keeps no second"
    assert store.entry(other)["flow_hash"] == VERSION[1]


def test_a_reopen_under_a_new_hash_writes_record_copy_and_text_in_one_commit(store, monkeypatch):
    put(store, closed_at="2026-11-01T00:00:00Z")
    writes: list[list[str]] = []
    real = store.write
    monkeypatch.setattr(store, "write", lambda changes, msg: writes.append(sorted(changes)) or real(changes, msg))
    act = choose(store.entry(TID), READY)
    assert offer(store, TID, act, READY, FLOW, lambda *_a: "s9", lambda *_a: None, team="t", version=VERSION).made
    assert writes == [[f"closed/{TID}@2026-11-01.json", f"entries/{TID}.json", f"flows/versions/{VERSION[1]}.json"]]


def test_an_offer_with_no_version_writes_a_null_hash_and_keeps_no_text(store):
    put(store, stage="build", flow_hash="f" * 64)
    assert offer(
        store, TID, choose(store.entry(TID), READY), READY, FLOW, lambda *_a: "s9", lambda *_a: None, team="t"
    ).made
    assert store.entry(TID)["flow_hash"] is None
    assert store._list(store.tip(), "flows/versions") == []


def test_a_refused_claim_keeps_no_version(store):
    act = choose(None, READY)
    got = offer(store, TID, act, READY, FLOW, lambda *_a: "s9", lambda *_a: "no", team="t", version=VERSION)
    assert not got.made and store.version(VERSION[1]) is None


# -- the lost holder's row (§4.9c *Each holder leaves a `run`*, TD-2158) ------------------------------------------

FIELDS = {
    "model": "opus",
    "tool": "claude-code",
    "tool_version": "2.1",
    "login": None,
    "login_moves": None,
    "created": "2026-11-25T10:00:00Z",
    "person_asks": 2,
}
NOW_SUMS = {"opus": {"input": 15, "output": 3, "turns": 5, "unweighed": 0, "figure": {"≈$": 0.6}}}


def _lose(store: StageStore, holder: Holder, *, session: Any = FIELDS, spent: Any = None, **over: Any) -> Any:
    reading = Reading(holder=holder, may_start=True)
    act = choose(store.entry(TID), reading)
    return act, make(store, TID, act, reading, FLOW, "paul", session=session, spent=spent, **over)


@pytest.mark.parametrize(
    ("holder", "offers", "case"),
    [
        (Holder(ended=True), 1, "lost"),
        (Holder(idle_for=timedelta(hours=3)), 1, "silent"),
        (Holder(ended=True, stopped=True), 1, "stopped"),
        (Holder(ended=True), 2, "to-person"),
    ],
)
def test_each_loss_writes_a_lost_row_carrying_the_holders_run(store, holder, offers, case):
    put(store, holder="s1@node", offers=offers, team="t", flow_hash="h" * 64, spent_before={"s1": SUMS})
    asked: list[str] = []
    act, got = _lose(store, holder, spent=lambda sid: asked.append(sid) or NOW_SUMS)
    assert act.case == case and got.made and asked == ["s1"]
    record = store.entry(TID)
    row = record["history"][0]
    assert {k: row[k] for k in ("from", "to", "outcome", "by", "reason")} == {
        "from": "build",
        "to": "build",
        "outcome": "lost",
        "by": "home",
        "reason": case,
    }
    run = row["run"]
    assert (run["session"], run["team"], run["flow_hash"], run["spent_before"]) == ("s1", "t", "h" * 64, SUMS)
    assert (run["model"], run["tool"], run["tool_version"], run["started"], run["asks"]) == (
        "opus",
        "claude-code",
        "2.1",
        "2026-11-25T10:00:00Z",
        2,
    )
    assert run["models"]["opus"]["turns"] == 2 and run["models"]["opus"]["input"] == 5
    if case == "to-person":  # its question's ask row, in the same commit, carries no run: the lost row has it
        assert [h["outcome"] for h in record["history"]] == ["lost", "ask"] and "run" not in record["history"][1]
        assert record["history"][1]["reason"] == "to-person" and record["intent"]
    else:
        assert len(record["history"]) == 1


def test_a_lost_row_of_a_forgotten_session_record_keeps_what_the_home_holds(store):
    put(store, holder="s1", offers=1, team="t", flow="build-review", flow_hash="h" * 64, spent_before={"s1": SUMS})
    _, got = _lose(store, Holder(ended=True), session=None, spent=lambda _sid: NOW_SUMS)
    run = store.entry(TID)["history"][-1]["run"]
    assert got.made
    assert all(run[k] is None for k in ("model", "tool", "tool_version", "login", "login_moves", "started", "asks"))
    assert (run["session"], run["team"], run["flow"], run["flow_hash"], run["spent_before"]) == (
        "s1",
        "t",
        "build-review",
        "h" * 64,
        SUMS,
    )
    assert run["ended"] and run["models"] is not None


def _raises(_sid: str) -> Any:
    raise OSError("no seat ledger")


@pytest.mark.parametrize("spent", [None, _raises])
def test_a_lost_row_whose_reading_fails_has_null_models_and_is_written(store, spent):
    put(store, holder="s1", offers=1, spent_before={"s1": SUMS})
    _, got = _lose(store, Holder(ended=True), spent=spent)
    assert got.made and store.entry(TID)["history"][-1]["run"]["models"] is None


def test_a_lost_row_tells_a_fresh_session_nothing(store):
    step = {"from": "review", "outcome": "refused", "reason": "the merge gate failed on ci", "to": "build"}
    put(store, stage="build", branch="b", pr=3, holder="s1", offers=1, history=[step])
    _lose(store, Holder(ended=True))
    assert store.entry(TID)["history"][-1]["outcome"] == "lost"
    got, started, _ = offer_it(store)
    assert got.made and started[0][1].came == "the merge gate failed on ci (`refused` at `review`)"


def test_a_later_offer_under_the_same_id_counts_from_its_own_offer(store):
    """Two rows of one record under one id: the later's spent_before is at least the earlier's plus its models."""
    put(store, holder="s9", offers=1, spent_before={"s9": SUMS})
    _lose(store, Holder(ended=True), session=None, spent=lambda _sid: NOW_SUMS)
    first = store.entry(TID)["history"][-1]["run"]
    assert _offer_spent(store, lambda _sid: NOW_SUMS).made
    later = {"opus": {"input": 20, "output": 3, "turns": 6, "unweighed": 0, "figure": {"≈$": 0.7}}}
    _lose(store, Holder(ended=True), spent=lambda _sid: later)
    second = next(h for h in reversed(store.entry(TID)["history"]) if h["outcome"] == "lost")["run"]
    assert second["spent_before"] == NOW_SUMS and second["models"]["opus"]["turns"] == 1
    for k in ("input", "output", "turns"):
        assert second["spent_before"]["opus"][k] >= first["spent_before"]["opus"][k] + first["models"]["opus"][k]


# -- the home's other rows: a reconcile case's, an `ended` row, an `ask` row and the answer's (§4.9c, TD-2158) -------


def _home(store: StageStore, reading: Reading, doc: dict[str, Any] = FLOW) -> Any:
    act = choose(store.entry(TID), reading)
    assert act is not None
    return make(store, TID, act, reading, doc, "paul", session=FIELDS, spent=lambda _sid: NOW_SUMS)


def _commits(store: StageStore) -> int:
    out = subprocess.run(
        ["git", "-C", str(store.root), "rev-list", "--count", str(store.tip())], capture_output=True, text=True
    )
    return int(out.stdout)


def _run_is_s1(row: dict[str, Any]) -> None:
    run = row["run"]
    assert (run["session"], run["model"], run["spent_before"]) == ("s1", "opus", SUMS)
    assert run["models"]["opus"]["turns"] == 2


ENDS = {
    "close": ({}, Reading(entry="archived")),
    "wait-for-parts": ({"pr": 4}, Reading(pr_state="merged", design=True, open_parts=2)),
    "team-moved": ({"pr": 4}, Reading(team_moved=True, pr_state="open")),
    "check-merged": (
        {"pr": 4, "check_waits": 4, "waits": "merging", "merging": {"head": "a" * 40}},
        Reading(pr_state="merged"),
    ),
}


@pytest.mark.parametrize("case", list(ENDS))
def test_a_reconcile_case_that_clears_a_holder_writes_an_ended_row_with_its_run(store, case):
    over, reading = ENDS[case]
    put(store, holder="s1@node", spent_before={"s1": SUMS}, **over)
    got = _home(store, reading)
    assert got.made and got.end == "s1@node"
    (row,) = store.entry(TID)["history"]
    assert {k: row[k] for k in ("from", "to", "outcome", "by", "reason")} == {
        "from": "build",
        "to": "build",
        "outcome": "ended",
        "by": "home",
        "reason": case,
    }
    _run_is_s1(row)


@pytest.mark.parametrize("case", list(ENDS))
def test_a_reconcile_case_with_no_holder_writes_no_row(store, case):
    over, reading = ENDS[case]
    put(store, **over)
    assert _home(store, reading).made
    assert not store.entry(TID)["history"]


def test_a_re_entry_row_carries_the_holders_run(store):
    put(store, stage="dropped", holder="s1", spent_before={"s1": SUMS})
    assert _home(store, Reading(stage_known=False)).made
    (row,) = store.entry(TID)["history"]
    assert row["outcome"] == "re-enter"
    _run_is_s1(row)


@pytest.mark.parametrize(
    "reading",
    [Reading(flow_current=False), Reading(renumbered_to="TD-9"), Reading(gate=True)],
    ids=["rewrite-flow", "renumbered", "mark-waiting"],
)
def test_a_write_that_keeps_or_moves_its_holder_writes_no_run(store, reading):
    put(store, holder="s1", spent_before={"s1": SUMS})
    got = _home(store, reading)
    record = store.entry(TID) or store.entry("TD-9")
    assert got.made and got.end is None and record["holder"] == "s1"
    assert not record["history"]


QUESTIONS = {
    "merged-entry-open": ({"pr": 4}, Reading(pr_state="merged")),
    "pr-closed": ({"pr": 4}, Reading(pr_state="closed")),
    "stage-gone": ({"stage": "dropped", "moves": 2}, Reading(stage_known=False)),
}


@pytest.mark.parametrize("case", list(QUESTIONS))
def test_a_question_the_home_asks_writes_an_ask_row_with_the_cleared_holders_run_in_its_intents_commit(store, case):
    over, reading = QUESTIONS[case]
    put(store, holder="s1", spent_before={"s1": SUMS}, **over)
    before = _commits(store)
    assert _home(store, reading).made
    record = store.entry(TID)
    (row,) = record["history"]
    assert (row["to"], row["outcome"], row["by"], row["reason"]) == ("person", "ask", "home", case)
    _run_is_s1(row)
    assert record["intent"] and record["holder"] is None and _commits(store) == before + 1


@pytest.mark.parametrize("case", list(QUESTIONS))
def test_a_question_with_no_holder_writes_its_ask_row_with_no_run(store, case):
    over, reading = QUESTIONS[case]
    put(store, **over)
    assert _home(store, reading).made
    (row,) = store.entry(TID)["history"]
    assert row["outcome"] == "ask" and row["reason"] == case and "run" not in row


@pytest.mark.parametrize("case", list(QUESTIONS))
def test_an_ask_case_on_an_entry_carrying_the_gate_writes_an_ended_row_and_no_ask_row(store, case):
    over, reading = QUESTIONS[case]
    put(store, holder="s1", spent_before={"s1": SUMS}, **over)
    assert _home(store, replace(reading, gate=True)).made
    record = store.entry(TID)
    (row,) = record["history"]
    assert (row["outcome"], row["reason"]) == ("ended", case) and record["waits"] == "person"
    assert record["intent"] is None
    _run_is_s1(row)


def test_a_second_loss_on_an_entry_carrying_the_gate_writes_its_lost_row_alone(store):
    """`choose` reconciles a gate before a loss, so `_offer_again` is called as `make` would call it."""
    record = put(store, holder="s1", offers=2, spent_before={"s1": SUMS})
    run = run_of(record, "s1", FIELDS, NOW_SUMS)
    act = Act("offer-again", "to-person")
    reading = Reading(holder=Holder(ended=True), may_start=True, gate=True)
    assert _offer_again(store, record, act, reading, FLOW, "paul", run).made
    record = store.entry(TID)
    assert record["waits"] == "person" and record["intent"] is None
    (row,) = record["history"]
    assert row["outcome"] == "lost"
    _run_is_s1(row)


def test_a_gate_asked_again_writes_no_row(store):
    asked = {"nonce": "n1", "ask": "Why?", "context": "c", "answers": {"Go — a session goes": "build"}}
    put(store, waits="person", asked=asked)
    assert _home(store, Reading()).made
    assert store.entry(TID)["intent"] and not store.entry(TID)["history"]


def test_an_answer_that_moves_a_kept_holders_stage_carries_its_run(store):
    put(store, holder="s1", waits="person", spent_before={"s1": SUMS}, answers={"Polish it": "polish", OTHER: None})
    got = _home(store, Reading(lifted="Polish it"))
    assert got.made and got.end == "s1"
    (row,) = store.entry(TID)["history"]
    assert (row["outcome"], row["by"], row["to"]) == ("answer", "paul", "polish")
    _run_is_s1(row)


def test_an_answer_with_no_holder_carries_no_run(store):
    put(store, waits="person", answers={"Polish it": "polish", OTHER: None})
    assert _home(store, Reading(lifted="Polish it")).made
    (row,) = store.entry(TID)["history"]
    assert row["outcome"] == "answer" and "run" not in row


def test_an_answer_naming_a_stage_gone_asks_with_the_kept_holders_run(store):
    put(store, holder="s1", waits="person", spent_before={"s1": SUMS}, answers={"Gone": "nowhere", OTHER: None})
    assert _home(store, Reading(lifted="Gone")).made
    record = store.entry(TID)
    (row,) = record["history"]
    assert (row["outcome"], row["reason"]) == ("ask", "answer-stage-gone") and record["intent"]
    _run_is_s1(row)


def test_an_answer_applied_to_nothing_writes_no_row_and_keeps_its_holder(store, monkeypatch):
    monkeypatch.setattr(store, "note_unapplied", lambda *_a: {"commit": "abc"})
    put(store, holder="s1", pr=4, waits="person", answers={"Polish it": "polish", OTHER: None})
    got = _home(store, Reading(pr_state="merged", lifted="Polish it"))
    record = store.entry(TID)
    assert got.made and got.end is None and record["holder"] == "s1" and not record["history"]


def test_the_homes_rows_tell_a_fresh_session_nothing(store):
    step = {"from": "review", "outcome": "refused", "reason": "the merge gate failed on ci", "to": "build"}
    put(store, stage="build", branch="b", pr=4, holder="s1", history=[step])
    assert _home(store, Reading(pr_state="closed", gate=True)).made  # an ended row
    record = store.entry(TID)
    record.update(waits=None, history=[*record["history"], {"from": "build", "to": "person", "outcome": "ask"}])
    store.put_entry(record, "an ask row as well")
    got, started, _ = offer_it(store, replace(READY, work=None))
    assert got.made and started[0][1].came == "the merge gate failed on ci (`refused` at `review`)"
