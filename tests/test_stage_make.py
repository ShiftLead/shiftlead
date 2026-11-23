"""Making the acts that only write a stage record (design §4.9c *The home acts only where no session will*, TD-2051),
on a real `shiftlead/state` branch in a scratch repo and its bare origin."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sessionorc import board
from shiftlead.stage_acts import Act, Holder, Reading, choose
from shiftlead.stage_end import ARCHIVE
from shiftlead.stage_make import make, offer, sweep_closed
from shiftlead.stage_start import Work
from shiftlead.stage_work import EntryWork
from shiftlead.stagerecord import OTHER, StageStore, StateError, new_record

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


def test_a_stage_with_nothing_to_read_passes_as_ship_to_merge_with_the_head(store):
    put(store, stage="review", pr=4, branch="td7")
    assert act_on(store, Reading(nothing_to_read=True, head="a" * 40)).made
    got = store.entry(TID)
    assert got["waits"] == "merging" and got["merging"]["head"] == "a" * 40
    assert got["history"][-1]["by"] == "home"
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


def test_a_case_of_a_later_slice_writes_nothing(store):
    before = put(store, pr=4, holder="s1")
    got = make(store, TID, Act("reconcile", "team-moved"), Reading(team_moved=True), FLOW, "paul")
    assert not got.made and "later" in got.why
    assert store.entry(TID) == before


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


def test_closed_records_leave_after_thirty_days_in_one_commit(store):
    now = datetime(2026, 11, 23, tzinfo=UTC)
    old = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    young = (now - timedelta(days=29)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for tid, closed in (("TD-1", old), ("TD-2", old), ("TD-3", young), ("TD-4", None)):
        store.put_entry({**new_record(tid, "f", "build"), "closed_at": closed}, "test")
    tip = store.tip()
    assert sweep_closed(store, now) == ["TD-1", "TD-2"]
    assert sorted(store.entries()) == ["TD-3", "TD-4"]
    count = subprocess.run(
        ["git", "-C", str(store.root), "rev-list", "--count", f"{tip}..{store.tip()}"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert count.stdout.strip() == "1"


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


def test_a_reopened_entry_is_offered_afresh_with_nothing_carried_over(store):
    put(store, stage="polish", closed_at="2026-11-01T00:00:00Z", branch="old", pr=3, offers=2)
    got, started, _ = offer_it(store)
    assert got.made and started == [("build", Work(TID))]
    record = store.entry(TID)
    assert record["closed_at"] is None and record["pr"] is None and record["offers"] == 1


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
