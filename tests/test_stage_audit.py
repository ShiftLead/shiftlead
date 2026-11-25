"""An audit's run record: its clock, its lease and its outcomes (design §4.9c *Audits start on a clock*, TD-2053)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from shiftlead.stage_acts import SILENT_AFTER, Holder
from shiftlead.stage_audit import (
    AuditAct,
    AuditReading,
    Clock,
    again,
    choose,
    clock,
    due,
    end_refusal,
    finished,
    holds_lease,
    lease_ref,
    next_round,
    rested,
    started,
)

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
GO = {"may_start": True}


def run(**over: Any) -> dict[str, Any]:
    return {**started("audit-docs", "abc123", NOW - timedelta(hours=7)), **over}


def done_run(**over: Any) -> dict[str, Any]:
    return finished(run(**over), "nothing-found", "all fine", NOW - timedelta(hours=6))


@pytest.mark.parametrize(
    ("every", "want"),
    [
        ("10 merged-pull-requests", Clock(10, "merged-pull-requests")),
        ("6 hours", Clock(6, "hours")),
        ("1 days", Clock(1, "days")),
        ("0 hours", None),
        ("6 weeks", None),
        (None, None),
    ],
)
def test_clock_reads_every(every: Any, want: Clock | None) -> None:
    assert clock(every) == want


def test_hours_and_days_run_from_the_start() -> None:
    r = done_run()
    assert due(r, Clock(6, "hours"), AuditReading(), NOW) is True
    assert due(r, Clock(8, "hours"), AuditReading(), NOW) is False
    assert due(r, Clock(1, "days"), AuditReading(), NOW) is False
    assert due({**r, "started_at": "garbled"}, Clock(6, "hours"), AuditReading(), NOW) is None


def test_merged_pull_requests_count_since_the_base() -> None:
    r, every = done_run(), Clock(10, "merged-pull-requests")
    assert due(r, every, AuditReading(merged_since=10), NOW) is True
    assert due(r, every, AuditReading(merged_since=9), NOW) is False
    assert due(r, every, AuditReading(), NOW) is None  # the count was not read: no reading


def test_a_finished_run_starts_on_its_clock_only_while_the_team_may_start() -> None:
    every = Clock(6, "hours")
    assert choose(done_run(), every, AuditReading(**GO), NOW) == AuditAct("start")
    assert choose(done_run(), every, AuditReading(), NOW) is None
    assert choose(done_run(), Clock(8, "hours"), AuditReading(**GO), NOW) is None


def test_a_run_that_holds_its_lease_is_never_started_again() -> None:
    live = AuditReading(holder=Holder(), merged_since=50, **GO)
    r = run()
    assert holds_lease(r, live)
    assert choose(r, Clock(1, "merged-pull-requests"), live, NOW) is None
    assert choose(r, Clock(1, "hours"), live, NOW) is None
    assert holds_lease(r, AuditReading())  # its holder not read: still held
    assert not holds_lease(done_run(), live)


@pytest.mark.parametrize(
    ("holder", "want"),
    [
        (Holder(ended=True), AuditAct("offer-again", "lost")),
        (Holder(lease_lapsed=True), AuditAct("offer-again", "lost")),
        (Holder(idle_for=SILENT_AFTER), AuditAct("offer-again", "silent")),
        (Holder(ended=True, stopped=True), AuditAct("offer-again", "stopped", counted=False)),
        (Holder(idle_for=SILENT_AFTER, waiting=True), None),
        (Holder(held=True, ended=True), None),
        (Holder(), None),
    ],
)
def test_a_lost_or_silent_run_is_offered_again(holder: Holder, want: AuditAct | None) -> None:
    assert choose(run(), Clock(6, "hours"), AuditReading(holder=holder, **GO), NOW) == want


@pytest.mark.parametrize(
    ("holder", "want"),
    [
        (Holder(idle_for=SILENT_AFTER), AuditAct("rest", "silent")),
        (Holder(ended=True, stopped=True), AuditAct("offer-again", "stopped", counted=False)),
        (Holder(held=True, ended=True), None),
        (Holder(person=True, ended=True), None),
    ],
)
def test_at_a_second_offer(holder: Holder, want: AuditAct | None) -> None:
    assert choose(run(offers=2), Clock(6, "hours"), AuditReading(holder=holder, **GO), NOW) == want
    assert choose(run(offers=2), Clock(6, "hours"), AuditReading(holder=holder), NOW) is None


def test_an_empty_holder_is_no_holder() -> None:
    r = run(holder="")
    assert not holds_lease(r, AuditReading())
    assert choose(r, Clock(6, "hours"), AuditReading(**GO), NOW) == AuditAct("start")


def test_again_on_a_record_with_no_offers() -> None:
    r = {k: v for k, v in run().items() if k != "offers"}
    assert again(r, "audit-docs-2", AuditAct("offer-again", "lost"))["offers"] == 1


def test_offer_again_waits_while_the_team_may_not_start() -> None:
    assert choose(run(), Clock(6, "hours"), AuditReading(holder=Holder(ended=True)), NOW) is None


def test_a_second_loss_rests_the_audit_until_its_next_clock() -> None:
    lost, every = AuditReading(holder=Holder(ended=True), merged_since=40, **GO), Clock(10, "merged-pull-requests")
    act = choose(run(offers=2), every, lost, NOW)
    assert act == AuditAct("rest", "lost")
    r = rested(run(offers=2), act, "def456", NOW)
    assert r["holder"] is None and r["base"] == "def456" and r["started_at"] == "2026-11-25T12:00:00Z"
    assert r["ended"]["outcome"] == "lost" and "next clock" in r["ended"]["reason"]
    # its count now runs from the second loss: what was merged before it does not start it again at once
    assert choose(r, every, AuditReading(merged_since=0, **GO), NOW) is None
    assert choose(r, Clock(6, "hours"), AuditReading(**GO), NOW + timedelta(hours=1)) is None


def test_again_keeps_the_run_and_spends_an_offer_only_for_a_counted_loss() -> None:
    r = run()
    twice = again(r, "audit-docs-2", AuditAct("offer-again", "lost"))
    assert twice["holder"] == "audit-docs-2" and twice["offers"] == 2
    assert twice["started_at"] == r["started_at"] and twice["base"] == r["base"]
    assert again(r, "audit-docs-2", AuditAct("offer-again", "stopped", counted=False))["offers"] == 1


def test_started_writes_a_fresh_run() -> None:
    r = started("audit-docs", "abc123", NOW)
    want = {"started_at": "2026-11-25T12:00:00Z", "holder": "audit-docs", "base": "abc123", "offers": 1}
    assert r == {**want, "ended": None}


def test_an_audit_with_no_run_yet_is_due_at_once_while_the_team_may_start() -> None:
    for every in (Clock(6, "hours"), Clock(3, "merged-pull-requests"), Clock(7, "days")):
        assert choose(None, every, AuditReading(**GO), NOW) == AuditAct("start", "first")
        assert choose(None, every, AuditReading(), NOW) is None  # the team may not start


def test_an_audit_with_no_clock_is_never_chosen() -> None:
    assert choose(None, None, AuditReading(**GO), NOW) is None
    assert choose(done_run(), None, AuditReading(**GO), NOW) is None


def test_a_runs_lease_is_a_claim_on_the_audits_own_reference() -> None:
    assert lease_ref("core", "docs") == "audit:core/docs"


@pytest.mark.parametrize(
    ("outcome", "reason", "filed", "refused"),
    [
        ("findings-filed", "", ["TD-9"], False),
        ("findings-filed", "two problems", [], True),
        ("findings-filed", "", [" "], True),
        ("nothing-found", "the docs match the code", [], False),
        ("nothing-found", " ", [], True),
        ("other", "the checkout is gone", [], False),
        ("other", "", [], True),
        ("done", "x", [], True),
        ("work-pushed", "x", [], True),
    ],
)
def test_end_refusal_checks_an_audits_outcome(outcome: str, reason: str, filed: list[str], refused: bool) -> None:
    assert (end_refusal(outcome, reason, filed) is not None) is refused


def test_finished_clears_the_holder_and_keeps_the_clock() -> None:
    r = run()
    f = finished(r, "findings-filed", "", NOW)
    assert f["holder"] is None and f["started_at"] == r["started_at"] and f["base"] == r["base"]
    assert f["ended"] == {"outcome": "findings-filed", "reason": "", "at": "2026-11-25T12:00:00Z"}


@pytest.mark.parametrize(
    ("record", "every", "merged", "want"),
    [
        (None, "6 hours", None, "due now"),
        (run(), "6 hours", None, "running now"),
        (done_run(), "6 hours", None, "due now"),
        (done_run(), "10 hours", None, "in 3h"),
        (done_run(started_at="2026-11-25T09:50:00Z"), "6 hours", None, "in 3h 50m"),
        (done_run(started_at="2026-11-25T11:59:30Z"), "6 hours", None, "in 5h 59m"),
        (done_run(), "2 days", None, "in 1d 17h"),
        (done_run(started_at="2026-11-24T12:00:00Z"), "2 days", None, "in 1d"),
        (done_run(), "10 merged-pull-requests", 6, "4 to go"),
        (done_run(), "10 merged-pull-requests", 10, "due now"),
        (done_run(), "10 merged-pull-requests", None, ""),
        (done_run(started_at="junk"), "6 hours", None, ""),
        (done_run(), "6 weeks", None, ""),
    ],
)
def test_next_round_says_when_the_audit_next_comes_round(record, every, merged, want) -> None:
    assert next_round(record, clock(every), merged, NOW) == want
