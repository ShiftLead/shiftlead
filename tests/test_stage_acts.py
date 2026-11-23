"""Which one act the tick takes on a stage record (design §4.9c *The home acts only where no session will*, TD-2051)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from shiftlead.stage_acts import SILENT_AFTER, Holder, Reading, choose, closed_expired
from shiftlead.stage_work import EntryWork
from shiftlead.stagerecord import OTHER, answer_move, new_record

GO = {"may_start": True, "within_size": True}


def rec(**over: Any) -> dict[str, Any]:
    return {**new_record("TD-7", "build-review", "build"), **over}


def held(**over: Any) -> dict[str, Any]:
    return rec(**{"holder": "build-td-7", "offers": 1, **over})


def named(act: Any) -> tuple[str, str] | None:
    return (act.name, act.case) if act else None


@pytest.mark.parametrize(
    ("record", "reading", "want"),
    [
        (held(), Reading(entry="archived"), ("reconcile", "close")),
        (held(), Reading(renumbered_to="TD-9"), ("reconcile", "renumbered")),
        (held(intent={"ask": "?"}), Reading(), ("reconcile", "land-intent")),
        (held(pr=4), Reading(pr_state="merged"), ("reconcile", "merged-entry-open")),
        (held(pr=4), Reading(pr_state="closed"), ("reconcile", "pr-closed")),
        (rec(pr=4), Reading(pr_state="merged", design=True, open_parts=2), ("reconcile", "wait-for-parts")),
        (rec(pr=4), Reading(pr_state="merged", design=True, had_parts=True), ("reconcile", "archive-design")),
        (rec(pr=4), Reading(pr_state="merged", design=True), ("reconcile", "merged-entry-open")),
        (rec(waits="merging"), Reading(), ("reconcile", "merging")),
        (held(), Reading(team_moved=True), ("reconcile", "team-moved")),
        (held(), Reading(stage_known=False), ("reconcile", "re-enter")),
        (held(moves=1), Reading(stage_known=False), ("reconcile", "stage-gone")),
        (held(), Reading(flow_current=False), ("reconcile", "rewrite-flow")),
        (held(), Reading(gate=True), ("reconcile", "mark-waiting")),
        (rec(waits="person"), Reading(), ("reconcile", "gate-again")),
        (rec(waits="merging", pr=4), Reading(pr_state="merged"), ("reconcile", "merged-entry-open")),
        (
            rec(waits="parts", pr=4),
            Reading(pr_state="merged", design=True, open_parts=1, team_moved=True),
            ("reconcile", "team-moved"),
        ),
        (
            rec(waits="parts", pr=4, moves=1),
            Reading(pr_state="merged", design=True, open_parts=1, stage_known=False),
            ("reconcile", "stage-gone"),
        ),
    ],
)
def test_reconciles_each_case(record: dict[str, Any], reading: Reading, want: tuple[str, str]) -> None:
    assert named(choose(record, reading)) == want


@pytest.mark.parametrize(
    ("record", "reading"),
    [
        (rec(waits="parts", pr=4), Reading(pr_state="merged", design=True, open_parts=1, **GO)),
        (rec(waits="parts", pr=4), Reading(pr_state="merged", design=True, had_parts=True, archive_open=True, **GO)),
        (rec(waits="merging"), Reading(merge_running=True, **GO)),
        (rec(waits="merging", pr=4), Reading(pr_state="merged", merge_running=True, **GO)),
        (rec(waits="merging", pr=4), Reading(pr_state="merged", design=True, open_parts=1, merge_running=True, **GO)),
        (rec(waits="merging", pr=4), Reading(entry="archived", pr_state="merged", merge_running=True, **GO)),
        (rec(waits="parts", pr=4), Reading(pr_state="merged", design=True, open_parts=1, gate=True, **GO)),
        (rec(waits="person", pr=4), Reading(pr_state="merged", gate=True, **GO)),
        (rec(waits="person", pr=4), Reading(pr_state="closed", gate=True, **GO)),
        (rec(waits="person"), Reading(stage_known=False, gate=True, **GO)),
    ],
)
def test_a_record_already_as_it_should_be_takes_no_act(record: dict[str, Any], reading: Reading) -> None:
    assert choose(record, reading) is None


def test_a_pass_takes_the_first_act_only() -> None:
    lost = Holder(ended=True)
    assert named(choose(held(pr=4), Reading(pr_state="merged", holder=lost, **GO))) == (
        "reconcile",
        "merged-entry-open",
    )
    assert named(choose(rec(waits="person"), Reading(gate=True, lifted="Go", **GO))) == ("answer", "")
    assert named(choose(rec(), Reading(nothing_to_read=True, **GO))) == ("pass", "")


def test_a_merged_entry_waiting_on_the_person_still_takes_their_answer() -> None:
    assert named(choose(rec(waits="person", pr=4), Reading(pr_state="merged", gate=True, lifted="Archive"))) == (
        "answer",
        "",
    )


def test_pass_needs_no_started_team() -> None:
    assert named(choose(rec(), Reading(nothing_to_read=True))) == ("pass", "")


@pytest.mark.parametrize(
    "holder",
    [
        Holder(ended=True),
        Holder(lease_lapsed=True),
        Holder(idle_for=SILENT_AFTER),
    ],
)
def test_a_lost_or_silent_holder_is_offered_again_then_goes_to_the_person(holder: Holder) -> None:
    first = choose(held(), Reading(holder=holder, **GO))
    assert first is not None and first.name == "offer-again" and first.counted
    assert named(choose(held(offers=2), Reading(holder=holder, **GO))) == ("offer-again", "to-person")


@pytest.mark.parametrize(
    "holder",
    [
        Holder(),
        Holder(idle_for=SILENT_AFTER - timedelta(seconds=1)),
        Holder(idle_for=SILENT_AFTER, waiting=True),
        Holder(idle_for=SILENT_AFTER, permission=True),
        Holder(idle_for=SILENT_AFTER, person=True),
        Holder(ended=True, person=True),
        Holder(idle_for=SILENT_AFTER, held=True),
        Holder(lease_lapsed=True, held=True),
        Holder(ended=True, stopped=True, held=True),
        Holder(idle_for=SILENT_AFTER, stopped=True, lease_lapsed=True),
    ],
)
def test_a_holder_neither_lost_nor_silent_keeps_its_entry(holder: Holder) -> None:
    assert choose(held(), Reading(holder=holder, **GO)) is None


def test_a_holder_ended_by_a_stop_spends_no_offer() -> None:
    stopped = Holder(ended=True, stopped=True)
    for offers in (1, 2):
        act = choose(held(offers=offers), Reading(holder=stopped, **GO))
        assert act is not None and (act.name, act.case, act.counted) == ("offer-again", "stopped", False)


@pytest.mark.parametrize("gate", [{"may_start": False, "within_size": True}, {"may_start": False}])
def test_the_acts_that_start_a_session_wait_for_the_team(gate: dict[str, bool]) -> None:
    assert choose(held(), Reading(holder=Holder(ended=True), **gate)) is None
    assert choose(rec(), Reading(**gate)) is None
    assert choose(None, Reading(pickable=True, **gate)) is None


def test_offer_stays_within_the_teams_size() -> None:
    assert choose(rec(), Reading(may_start=True)) is None
    assert named(choose(rec(), Reading(**GO))) == ("offer", "")


def test_a_pickable_entry_with_no_record_is_offered_with_its_work() -> None:
    pr = {"number": 4, "branch": "td7-x"}
    act = choose(None, Reading(pickable=True, work=EntryWork("take", pr), **GO))
    assert act is not None and act.name == "offer" and act.work == EntryWork("take", pr)


@pytest.mark.parametrize("state", ["wait", "unread"])
def test_an_entry_whose_work_waits_is_offered_to_nobody(state: Any) -> None:
    assert choose(None, Reading(pickable=True, work=EntryWork(state), **GO)) is None


def test_an_unpickable_entry_is_not_offered() -> None:
    assert choose(None, Reading(**GO)) is None


def test_a_closed_record_is_offered_afresh_only_when_reopened_and_pickable() -> None:
    closed = rec(closed_at="2026-11-01T00:00:00Z", pr=4)
    assert choose(closed, Reading(entry="archived", pickable=True, **GO)) is None
    assert choose(closed, Reading(**GO)) is None
    act = choose(closed, Reading(pickable=True, **GO))
    assert act is not None and act.name == "offer" and act.work == EntryWork("none")


def test_an_answer_maps_to_its_move() -> None:
    answers = {"Go": "build", "Hold: <note>": "design", OTHER: None}
    assert answer_move(answers, "Go") == ("build", "Go")
    assert answer_move(answers, "hold: not yet") == ("design", "hold: not yet")


@pytest.mark.parametrize("label", ["Nope", "Hold", "Something else: rework it"])
def test_a_label_not_in_the_map_is_something_else(label: str) -> None:
    answers = {"Go": "build", "Hold: <note>": "design", OTHER: "review"}
    assert answer_move(answers, label) == ("review", label)


def test_a_closed_record_is_removed_after_thirty_days() -> None:
    record = rec(closed_at="2026-10-24T00:00:00Z")
    assert not closed_expired(record, datetime(2026, 11, 22, 23, 59, tzinfo=UTC))
    assert closed_expired(record, datetime(2026, 11, 23, tzinfo=UTC))
    assert not closed_expired(rec(), datetime(2026, 11, 23, tzinfo=UTC))
