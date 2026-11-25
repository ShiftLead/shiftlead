"""Which one act the tick takes on a built-in seat's job (design §4.9d *How each one runs*, TD-2053)."""

from __future__ import annotations

from typing import Any

import pytest

from shiftlead.stage_acts import SILENT_AFTER, Holder
from shiftlead.stage_job import (
    JobAct,
    JobReading,
    PrObject,
    board_objects,
    choose,
    cleared,
    closed,
    entries_work,
    fork_sync,
    key_of,
    moved,
    new_job,
    offered,
    order,
    pr_objects,
    to_person,
)
from shiftlead.stagerecord import new_record

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
    for seat, bad in (("sweeper", 1), ("board-answers", "xyz"), ("board-answers", "../a"), ("unheld-pull-requests", 0)):
        with pytest.raises(ValueError):
            key_of(seat, bad)


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
        (held(stage="review"), JobReading(stage_known=False, at_job_stage=False), "stage-gone"),
        (held(pr=12), JobReading(own_pr="merged"), None),
        (job(waits="merging", pr=12), JobReading(own_pr="closed"), "pr-closed"),
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


def test_a_lost_job_waits_while_another_job_session_of_the_seat_is_live() -> None:
    busy = {"seat_busy": True, **GO}
    assert choose(held(offers=1), JobReading(holder=Holder(ended=True), **busy)) is None
    assert choose(held(offers=1), JobReading(holder=Holder(ended=True, stopped=True), **busy)) is None
    second = choose(held(offers=2), JobReading(holder=Holder(ended=True), **busy))
    assert named(second) == ("offer-again", "to-person")  # starts no session, so it never waits


def test_a_job_at_a_review_stage_is_offered_that_stages_session() -> None:
    at = {"at_job_stage": False, **GO}
    assert named(choose(job(stage="review"), JobReading(**at))) == ("offer", "review")
    assert named(choose(job(stage="review"), JobReading(seat_busy=True, **at))) == ("offer", "review")
    assert choose(job(stage="review"), JobReading(at_job_stage=False)) is None  # only while the team may start
    assert choose(job(stage="review", waits="merging"), JobReading(**at)) is None
    assert choose(held(stage="review"), JobReading(holder=Holder(), **at)) is None
    r = held(stage="review")
    assert named(choose(r, JobReading(live=False, at_job_stage=False))) == ("reconcile", "object-gone")
    back = job(stage="build")  # moved back to the stage that takes `other` entries: a fresh job session
    assert named(choose(back, JobReading(**GO))) == ("offer", "")


@pytest.mark.parametrize(
    ("holder", "offers", "want"),
    [
        (Holder(ended=True), 1, ("offer-again", "review-lost")),
        (Holder(idle_for=SILENT_AFTER), 1, ("offer-again", "review-silent")),
        (Holder(ended=True), 2, ("offer-again", "to-person")),
        (Holder(ended=True, stopped=True), 2, ("offer-again", "review-stopped")),
    ],
)
def test_a_lost_review_session_on_a_job_is_offered_again_once(holder: Holder, offers: int, want: Any) -> None:
    s = JobReading(holder=holder, at_job_stage=False, seat_busy=True, **GO)  # no job session of the seat holds it
    act = choose(held(stage="review", offers=offers), s)
    assert named(act) == want and act.review == (act.case != "to-person")


def test_only_a_review_stages_offer_is_a_review_act() -> None:
    assert JobAct("offer", "review").review and JobAct("offer-again", "review-lost").review
    assert not JobAct("offer").review and not JobAct("offer-again", "lost").review
    assert not JobAct("reconcile", "stage-gone").review


def test_order_puts_begun_jobs_first_then_new_objects_oldest_first() -> None:
    begun = [
        job(obj="0000000b", entered_at="2026-11-25T03:00:00Z"),
        job(obj="0000000a", entered_at="2026-11-25T02:00:00Z"),
        held(obj="0000000c"),
        job(obj="0000000d", waits="person"),
        job(obj="0000000e", closed_at="2026-11-24T00:00:00Z"),
        job(obj="00000010", stage="review", entered_at="2026-11-25T00:00:00Z"),  # in the flow: an entry's acts
    ]
    objects = {
        "board-0000000f": "2026-11-25T00:30:00Z",
        "board-0000000e": "2026-11-25T00:10:00Z",
        "board-0000000a": "2026-11-20T00:00:00Z",
        "board-0000000c": "2026-11-19T00:00:00Z",  # held: that record's, never a new job
        "board-0000000d": "2026-11-19T00:00:00Z",  # waiting on the person
        "board-00000010": "2026-11-19T00:00:00Z",
    }
    want = ["board-0000000a", "board-0000000b", "board-0000000e", "board-0000000f"]
    assert order(begun, objects, "build") == want
    back = job(obj="00000011", stage="build", entered_at="2026-11-25T02:30:00Z")  # sent back to the job's stage
    assert order([*begun, back], objects, "build") == [*want[:1], "board-00000011", *want[1:]]


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


# -- the two seats' triggers (design §4.9c *Two of the five are not seats today*) -----------------------------------


def decided(item: str, context: str | None = None, date: str = "2026-11-24") -> dict[str, Any]:
    return {"id": f"board:{item}", "context": context, "decided": {"text": "Go", "date": date}}


def waiting(tid: str, **over: Any) -> dict[str, Any]:
    return {**new_record(tid, "build", "build", team="ao-grind"), **over}


def test_a_decided_line_asks_for_a_job_keyed_by_its_item() -> None:
    got = board_objects([decided("9099da3b"), decided("6bca1e0d", date="2026-11-21")], {})
    assert got == {"board-9099da3b": "2026-11-24", "board-6bca1e0d": "2026-11-21"}


def test_a_covering_item_of_an_entry_waiting_on_the_person_is_the_homes() -> None:
    lines = [decided("9099da3b", "TD-2053 decision (paul)"), decided("6bca1e0d", "TD-2054 decision (paul)")]
    entries = {"TD-2053": waiting("TD-2053", waits="person"), "TD-2054": waiting("TD-2054", intent={"nonce": "x"})}
    assert board_objects(lines, entries) == {}


def test_a_covering_item_asks_for_a_job_where_its_entry_does_not_wait() -> None:
    lines = [decided("9099da3b", "TD-2053 decision (paul)"), decided("6bca1e0d", "TD-2054 decision (paul)")]
    entries = {
        "TD-2053": waiting("TD-2053"),  # open, waiting on nothing
        "TD-2054": waiting("TD-2054", waits="person", closed_at="2026-11-24T00:00:00Z"),  # closed
    }
    assert set(board_objects(lines, entries)) == {"board-9099da3b", "board-6bca1e0d"}


def test_a_line_whose_context_is_no_entrys_gate_asks_for_a_job() -> None:
    entries = {"TD-2053": waiting("TD-2053", waits="person")}
    assert set(board_objects([decided("9099da3b", "TD-2053, TD-2054 decision (paul)")], entries)) == {"board-9099da3b"}


def test_an_order_with_no_board_id_is_no_board_answer() -> None:
    assert board_objects([{"id": "pr:12", "decided": {}}, {"id": "board:nothex!"}], {}) == {}


def red(n: int, **over: Any) -> dict[str, Any]:
    return {"id": f"pr:{n}", "pr_order": True, "pr": n, "red_since": "2026-11-24T01:00:00Z", **over}


def test_a_red_and_a_filing_pr_ask_for_a_job() -> None:
    orders = [red(12), red(13, filing=True, filing_since="2026-11-23T00:00:00Z", red_since=None)]
    assert pr_objects(orders, {}, {}) == {
        "pr-12": PrObject("2026-11-24T01:00:00Z", "red"),
        "pr-13": PrObject("2026-11-23T00:00:00Z", "filing"),
    }


def test_a_sync_lift_and_sweep_pr_each_ask_for_a_job_on_their_own_stamp_and_kind() -> None:
    orders = [
        red(
            1,
            sync=True,
            sync_since="2026-11-22T00:00:00Z",
            red_since=None,
            reason="src/x.py is not in the lock",
            fork=False,
        ),
        red(2, lift=True, lift_since="2026-11-21T00:00:00Z", red_since=None, reason="kept off a lift"),
        red(3, sweep=True, sweep_since="2026-11-20T00:00:00Z", red_since=None),
    ]
    assert pr_objects(orders, {}, {}) == {
        "pr-1": PrObject("2026-11-22T00:00:00Z", "sync", "src/x.py is not in the lock"),
        "pr-2": PrObject("2026-11-21T00:00:00Z", "lift"),
        "pr-3": PrObject("2026-11-20T00:00:00Z", "sweep"),
    }


def test_a_forks_sync_asks_for_none_and_a_sync_row_with_no_fork_is_read_as_a_forks() -> None:
    sync = {"sync": True, "sync_since": "2026-11-22T00:00:00Z", "red_since": None}
    assert pr_objects([red(1, **sync, fork=True), red(2, **sync)], {}, {}) == {}
    assert fork_sync({"sync": True}) and fork_sync({"sync": True, "fork": True})
    assert not fork_sync({"sync": True, "fork": False}) and not fork_sync({"fork": True}), "a fork's red is no sync"


def test_another_logins_sync_and_a_sync_draft_ask_for_a_job() -> None:
    sync = {"sync": True, "sync_since": "2026-11-22T00:00:00Z", "red_since": None, "fork": False}
    got = pr_objects([red(1, **sync, author="someone-else"), red(2, **sync, draft=True)], {}, {})
    assert {k: o.kind for k, o in got.items()} == {"pr-1": "sync", "pr-2": "sync"}


def test_a_lift_pr_whose_entry_is_pickable_is_still_the_jobs() -> None:
    prs = [row(12, "lift/TD-2053/until-2026-11-24", filing_head="sha12")]
    work = entries_work(["TD-2053"], {}, prs)
    assert work == set()
    lift = red(12, lift=True, lift_since="2026-11-24T00:00:00Z", red_since=None)
    assert pr_objects([lift], {}, {}, work=work) == {"pr-12": PrObject("2026-11-24T00:00:00Z", "lift")}


def test_a_pr_a_record_names_is_that_records() -> None:
    entries = {"TD-7": waiting("TD-7", pr=12), "TD-8": waiting("TD-8", pr=13, closed_at="2026-11-24T00:00:00Z")}
    jobs = {
        "board-9099da3b": job(pr=14),
        "pr-15": job("unheld-pull-requests", 15),  # its own seat's record: `order` reads it as that record's
    }
    got = pr_objects([red(12), red(13), red(14), red(15)], entries, jobs)
    assert set(got) == {"pr-13", "pr-15"}


def test_a_pickable_entrys_work_is_the_offer_acts() -> None:
    assert pr_objects([red(12), red(13)], {}, {}, work={12}) == {"pr-13": PrObject("2026-11-24T01:00:00Z", "red")}


def row(n: int, branch: str, **over: Any) -> dict[str, Any]:
    head = f"sha{n}"
    return {"number": n, "state": "open", "branch": branch, "head": head, "filing_head": head, "filing": False, **over}


def test_entries_work_is_a_pickable_entry_with_no_record() -> None:
    prs = [row(12, "td2053-triggers"), row(13, "td2054-x"), row(14, "td2055-y"), row(15, "td2056-z", filing_head=None)]
    entries = {"TD-2054": waiting("TD-2054")}  # has a record: the Offer act took it already
    got = entries_work(["TD-2053", "TD-2054", "TD-2056", "TD-9999"], entries, prs)
    assert got == {12, 15}  # #15's files unread at its head: maybe an entry's, so skipped this reading


def test_a_number_no_pull_request_has_is_skipped() -> None:
    assert pr_objects([red(0), red(-3), red(12)], {}, {}) == {"pr-12": PrObject("2026-11-24T01:00:00Z", "red")}


def test_order_offers_the_first_keys_before_older_objects_but_after_begun_records() -> None:
    begun = [job("unheld-pull-requests", 9, entered_at="2026-11-25T05:00:00Z")]
    objects = {
        "pr-11": PrObject("2026-11-20T00:00:00Z", "red"),
        "pr-12": PrObject("2026-11-25T04:00:00Z", "sync", "conflicting"),
        "pr-13": PrObject("2026-11-25T03:00:00Z", "sync", "red"),
        "pr-14": PrObject("2026-11-19T00:00:00Z", "filing"),
    }
    assert order(begun, objects, "build", first={"pr-12", "pr-13"}) == ["pr-9", "pr-13", "pr-12", "pr-14", "pr-11"]
    assert order(begun, objects, "build") == ["pr-9", "pr-14", "pr-11", "pr-13", "pr-12"]


def test_a_pull_requests_job_keeps_its_kind_and_a_syncs_its_reason() -> None:
    assert new_job("unheld-pull-requests", 12, "t", "x", kind="red")["kind"] == "red"
    assert "reason" not in new_job("unheld-pull-requests", 12, "t", "x", kind="lift", reason="ignored")
    got = new_job("unheld-pull-requests", 12, "t", "x", kind="sync", reason="conflicting")
    assert (got["kind"], got["reason"]) == ("sync", "conflicting")
    assert "kind" not in new_job("board-answers", "9099da3b", "t", "x")
    with pytest.raises(ValueError):
        new_job("board-answers", "9099da3b", "t", "x", kind="red")
    with pytest.raises(ValueError):
        new_job("unheld-pull-requests", 12, "t", "x", kind="merge")
