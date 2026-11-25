"""Which one act the tick takes on a built-in seat's job (design §4.9d *How each one runs*, TD-2053)."""

from __future__ import annotations

from typing import Any

import pytest

from shiftlead.stage_acts import SILENT_AFTER, Holder
from shiftlead.stage_job import (
    JobAct,
    JobReading,
    choose,
    cleared,
    closed,
    key_of,
    moved,
    new_job,
    offered,
    order,
    to_person,
)

GO = {"may_start": True}


def job(seat: str = "board-answers", obj: str | int = "9099da3b", **over: Any) -> dict[str, Any]:
    return {**new_job(seat, obj, "ao-grind", "2026-11-25T01:00:00Z"), **over}


def held(**over: Any) -> dict[str, Any]:
    return job(**{"holder": "board-answers-1", "offers": 1, **over})


def named(act: JobAct | None) -> tuple[str, str] | None:
    return (act.name, act.case) if act else None


def test_keys() -> None:
    assert key_of("board-answers", "9099da3b") == "board-9099da3b"
    assert key_of("unheld-pull-requests", 4490) == "pr-4490"
    with pytest.raises(ValueError):
        key_of("sweeper", 1)


@pytest.mark.parametrize(
    ("record", "reading", "want"),
    [
        (None, JobReading(**GO), ("offer", "new")),
        (None, JobReading(), None),
        (None, JobReading(seat_busy=True, **GO), None),
        (None, JobReading(live=False, **GO), None),
        (job(closed_at="2026-11-20T00:00:00Z"), JobReading(**GO), ("offer", "new")),
        (job(), JobReading(**GO), ("offer", "")),
        (job(), JobReading(seat_busy=True, **GO), None),
        (job(), JobReading(), None),
    ],
)
def test_offer(record: dict[str, Any] | None, reading: JobReading, want: tuple[str, str] | None) -> None:
    assert named(choose(record, reading)) == want


@pytest.mark.parametrize(
    ("record", "reading", "want"),
    [
        (held(), JobReading(live=False), "object-gone"),
        (job(waits="person", person_line="cf5d2dfc"), JobReading(live=False), "object-gone"),
        (held(pr=12), JobReading(own_pr="closed"), "pr-closed"),
        (job(seat="unheld-pull-requests", obj=12, holder="x"), JobReading(own_pr="closed"), None),
        (job(waits="person", pr=12), JobReading(own_pr="closed"), None),
        (job(waits="person", person_line="cf5d2dfc"), JobReading(person_line="closed"), "person-cleared"),
        (job(waits="person", person_line="cf5d2dfc"), JobReading(person_line="open", **GO), None),
        (job(waits="person", person_line="cf5d2dfc"), JobReading(**GO), None),
        (job(), JobReading(team_started=False, first_started="ao-two", **GO), "team-moved"),
        (job(), JobReading(team_started=False, **GO), None),
        (held(), JobReading(team_started=False, first_started="ao-two"), None),
        (job(stage="review"), JobReading(stage_known=False, **GO), "stage-gone"),
        (job(waits="merging"), JobReading(team_started=False, first_started="ao-two"), None),
    ],
)
def test_reconcile(record: dict[str, Any], reading: JobReading, want: str | None) -> None:
    act = choose(record, reading)
    assert (act.case if act and act.name == "reconcile" else None) == want


@pytest.mark.parametrize(
    ("holder", "offers", "want"),
    [
        (Holder(ended=True), 1, ("offer-again", "lost")),
        (Holder(lease_lapsed=True), 1, ("offer-again", "lost")),
        (Holder(idle_for=SILENT_AFTER), 1, ("offer-again", "silent")),
        (Holder(ended=True), 2, ("offer-again", "to-person")),
        (Holder(ended=True, stopped=True), 2, ("offer-again", "stopped")),
        (Holder(held=True, ended=True), 1, None),
        (Holder(), 1, None),
    ],
)
def test_a_lost_or_silent_job_is_offered_again_once(holder: Holder, offers: int, want: Any) -> None:
    assert named(choose(held(offers=offers), JobReading(holder=holder, **GO))) == want
    assert choose(held(offers=offers), JobReading(holder=holder)) is None  # only while the team may start


def test_a_job_in_its_teams_flow_is_moved_by_an_entrys_acts() -> None:
    r = held(stage="review")
    assert choose(r, JobReading(holder=Holder(ended=True), at_job_stage=False, **GO)) is None
    assert named(choose(r, JobReading(live=False, at_job_stage=False))) == ("reconcile", "object-gone")
    back = job(stage="build")  # moved back to the stage that takes `other` entries: a fresh job session
    assert named(choose(back, JobReading(**GO))) == ("offer", "")


def test_order_puts_begun_jobs_first_then_new_objects_oldest_first() -> None:
    begun = [
        job(obj="0000000b", entered_at="2026-11-25T03:00:00Z"),
        job(obj="0000000a", entered_at="2026-11-25T02:00:00Z"),
        held(obj="0000000c"),
        job(obj="0000000d", waits="person"),
        job(obj="0000000e", closed_at="2026-11-24T00:00:00Z"),
    ]
    objects = {
        "board-0000000f": "2026-11-25T00:30:00Z",
        "board-0000000e": "2026-11-25T00:10:00Z",
        "board-0000000a": "2026-11-20T00:00:00Z",
    }
    assert order(begun, objects) == ["board-0000000a", "board-0000000b", "board-0000000e", "board-0000000f"]


def test_writes() -> None:
    r = job()
    one = offered(r, "board-answers-1", JobAct("offer"))
    assert one["holder"] == "board-answers-1" and one["offers"] == 1
    assert offered(one, "board-answers-2", JobAct("offer-again", "lost"))["offers"] == 2
    assert offered(one, "board-answers-2", JobAct("offer-again", "stopped", counted=False))["offers"] == 1
    waiting = to_person({**one, "offers": 2, "counts": {"review:changes-wanted": 1}}, "cf5d2dfc")
    assert waiting["holder"] is None and waiting["waits"] == "person" and waiting["person_line"] == "cf5d2dfc"
    fresh = cleared(waiting)
    assert fresh["waits"] is None and fresh["person_line"] is None and fresh["offers"] == 0 and fresh["counts"] == {}
    gone = moved({**one, "branch": "b", "pr": 7, "stage": "review", "counts": {"x": 1}}, "ao-two")
    assert gone["team"] == "ao-two" and gone["branch"] == "b" and gone["pr"] == 7
    assert gone["stage"] is None and gone["counts"] == {} and gone["offers"] == 0
    shut = closed(one)
    assert shut["closed_at"] and shut["holder"] is None
