"""One built-in seat's pass over its jobs (design §4.9d *How each one runs*, TD-2053)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sessionorc.models import ProgressEntry, Session
from shiftlead import stage_job, stage_job_make, stage_job_pass
from shiftlead.stage_job_pass import JobFacts
from shiftlead.stagerecord import StageStore

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
FLOW = {"stages": [{"name": "build", "takes": "other"}, {"name": "review", "takes": "none"}]}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


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


class World:
    """A reach whose every session started is named `s-<n>`."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.claims: list[tuple[str, str]] = []
        self.lines: list[tuple[str, str]] = []
        self.closed: list[str] = []
        self.ended: list[str] = []

    def reach(self) -> stage_job_make.JobReach:
        def start(record, _came):
            self.started.append(record["id"])
            return f"s-{len(self.started)}"

        def line(record, reason):
            self.lines.append((record["id"], reason))
            return "aaaa0001"

        return stage_job_make.JobReach(
            start, lambda h, ref: self.claims.append((h, ref)), line, self.closed.append, self.ended.append
        )


def session(sid: str, *, state: str = "working", ref: str = "board:1a2b3c4d") -> Session:
    s = Session(id=sid, name=sid, dir="/r", kind="agent", adapter="claude-code", state=state, unattended=True)
    s.created = s.turn_at = (NOW - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    s.progress = [ProgressEntry(ref=ref, at=(NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))]
    return s


def facts(**kw) -> JobFacts:
    base = {"now": NOW, "live": set(), "started": ("t",), "docs": {"t": FLOW}, "may_start": True}
    return JobFacts(**{**base, **kw})


def put(store, key="board-1a2b3c4d", seat="board-answers", **kw):
    obj = key.partition("-")[2]
    record = {**stage_job.new_job(seat, obj, "t", kw.pop("entered_at", "2026-11-24")), **kw}
    store.put_job(record, "test")
    return record


# -- what is live ----------------------------------------------------------------------------------------------------


def test_live_keys_are_the_decided_lines_and_the_open_pull_requests():
    orders = [{"id": "board:1a2b3c4d"}, {"id": "TD-9"}]
    rows = [{"number": 4, "state": "open"}, {"number": 5, "state": "merged"}, {"number": True, "state": "open"}]
    assert stage_job_pass.live_keys(orders, rows) == {"board-1a2b3c4d", "pr-4"}


# -- a job's reading -------------------------------------------------------------------------------------------------


def test_an_object_with_no_record_reads_its_liveness_and_the_seats_business():
    s = stage_job_pass.reading_on(None, "pr-4", facts(live={"pr-4"}), seat_busy=True)
    assert (s.live, s.seat_busy, s.may_start, s.first_started) == (True, True, True, "t")


def test_a_board_answers_own_pull_request_is_read_from_the_rows_and_a_missing_row_is_no_reading():
    record = {**stage_job.new_job("board-answers", "1a2b3c4d", "t", "x"), "pr": 7}
    f = facts(live={"board-1a2b3c4d"}, rows=({"number": 7, "state": "closed"},))
    assert stage_job_pass.reading_on(record, "board-1a2b3c4d", f, seat_busy=False).own_pr == "closed"
    assert stage_job_pass.reading_on(record, "board-1a2b3c4d", facts(live={"board-1a2b3c4d"}), seat_busy=False) is None


def test_the_homes_line_is_read_open_or_closed_and_unread_is_no_reading():
    record = {**stage_job.new_job("board-answers", "1a2b3c4d", "t", "x"), "waits": "person", "person_line": "aaaa0001"}
    key = "board-1a2b3c4d"
    assert stage_job_pass.reading_on(record, key, facts(lines_open={"aaaa0001"}), seat_busy=False).person_line == "open"
    assert stage_job_pass.reading_on(record, key, facts(lines_open=set()), seat_busy=False).person_line == "closed"
    assert stage_job_pass.reading_on(record, key, facts(), seat_busy=False) is None


def test_a_holder_on_a_node_not_read_is_no_reading_and_a_gone_one_reads_ended():
    record = {**stage_job.new_job("board-answers", "1a2b3c4d", "t", "x"), "holder": "s-1@node2"}
    assert stage_job_pass.reading_on(record, "board-1a2b3c4d", facts(live={"board-1a2b3c4d"}), seat_busy=False) is None
    got = stage_job_pass.reading_on(record, "board-1a2b3c4d", facts(read_nodes={"node2"}), seat_busy=False)
    assert got.holder.ended and got.holder.lost


def test_a_record_past_the_jobs_stage_or_on_a_stage_gone_reads_so():
    base = stage_job.new_job("board-answers", "1a2b3c4d", "t", "x")
    at_review = stage_job_pass.reading_on({**base, "stage": "review"}, "k", facts(), seat_busy=False)
    assert (at_review.at_job_stage, at_review.stage_known) == (False, True)
    gone = stage_job_pass.reading_on({**base, "stage": "qa"}, "k", facts(), seat_busy=False)
    assert not gone.stage_known
    assert stage_job_pass.reading_on({**base, "stage": "build"}, "k", facts(docs={}), seat_busy=False) is None


def test_a_record_whose_team_is_not_started_reads_so():
    record = stage_job.new_job("board-answers", "1a2b3c4d", "old", "x")
    s = stage_job_pass.reading_on(record, "k", facts(), seat_busy=False)
    assert (s.team_started, s.first_started) == (False, "t")


# -- the seat's pass -------------------------------------------------------------------------------------------------


def test_one_session_a_pass_the_oldest_object_first(store):
    w = World()
    objects = {"board-1a2b3c4d": "2026-11-24", "board-0000aaaa": "2026-11-20"}
    steps = stage_job_pass.seat_pass(store, "board-answers", objects, facts(live=set(objects)), w.reach())
    assert w.started == ["board-0000aaaa"]
    assert [s.key for s in steps] == ["board-0000aaaa", "board-1a2b3c4d"] and steps[1].act is None
    assert store.job("board-0000aaaa")["holder"] == "s-1" and store.job("board-1a2b3c4d") is None


def test_a_live_job_session_holds_every_other_object_back(store):
    put(store, holder="s-9")
    w = World()
    f = facts(live={"board-1a2b3c4d", "board-0000aaaa"}, sessions={"s-9": session("s-9")})
    stage_job_pass.seat_pass(store, "board-answers", {"board-0000aaaa": "2026-11-20"}, f, w.reach())
    assert w.started == []


def test_a_record_already_begun_goes_before_an_older_new_object(store):
    put(store, key="board-1a2b3c4d", entered_at="2026-11-24")
    w = World()
    objects = {"board-0000aaaa": "2026-11-01"}
    f = facts(live={"board-1a2b3c4d", "board-0000aaaa"})
    stage_job_pass.seat_pass(store, "board-answers", objects, f, w.reach())
    assert w.started == ["board-1a2b3c4d"]


def test_a_lost_holder_is_offered_again_and_the_old_one_ended(store):
    put(store, holder="s-9", offers=1)
    w = World()
    f = facts(live={"board-1a2b3c4d"}, sessions={"s-9": session("s-9", state="exited")})
    steps = stage_job_pass.seat_pass(store, "board-answers", {}, f, w.reach())
    assert steps[0].act.name == "offer-again" and steps[0].made.made
    r = store.job("board-1a2b3c4d")
    assert (r["holder"], r["offers"]) == ("s-1", 2) and w.ended == ["s-9"]


def test_an_object_gone_closes_its_record_and_ends_its_session(store):
    put(store, holder="s-9")
    w = World()
    f = facts(sessions={"s-9": session("s-9")})
    steps = stage_job_pass.seat_pass(store, "board-answers", {}, f, w.reach())
    assert steps[0].act.case == "object-gone" and store.job("board-1a2b3c4d")["closed_at"] and w.ended == ["s-9"]


def test_a_job_whose_holder_is_unread_is_left_and_holds_the_seat(store):
    put(store, holder="s-9@node2")
    w = World()
    f = facts(live={"board-1a2b3c4d", "board-0000aaaa"})
    steps = stage_job_pass.seat_pass(store, "board-answers", {"board-0000aaaa": "2026-11-20"}, f, w.reach())
    assert not steps[0].read and steps[1].read and w.started == []  # the unread holder may still run


def test_a_job_with_no_reading_is_left_and_the_pass_goes_on(store):
    put(store, pr=7)  # its own pull request's row was not read
    w = World()
    f = facts(live={"board-1a2b3c4d", "board-0000aaaa"})
    steps = stage_job_pass.seat_pass(store, "board-answers", {"board-0000aaaa": "2026-11-20"}, f, w.reach())
    assert not steps[0].read and w.started == ["board-0000aaaa"]


def test_a_lost_holder_waits_while_another_job_session_of_the_seat_is_live(store):
    put(store, key="board-1a2b3c4d", holder="s-9", offers=1)
    put(store, key="board-0000aaaa", holder="s-8")
    w = World()
    sessions = {"s-9": session("s-9", state="exited"), "s-8": session("s-8", ref="board:0000aaaa")}
    f = facts(live={"board-1a2b3c4d", "board-0000aaaa"}, sessions=sessions)
    stage_job_pass.seat_pass(store, "board-answers", {}, f, w.reach())
    assert w.started == [] and store.job("board-1a2b3c4d")["holder"] == "s-9"


def test_two_lost_holders_in_one_pass_start_one_session(store):
    put(store, key="board-1a2b3c4d", holder="s-9", offers=1, entered_at="2026-11-20")
    put(store, key="board-0000aaaa", holder="s-8", offers=1, entered_at="2026-11-21")
    w = World()
    sessions = {"s-9": session("s-9", state="exited"), "s-8": session("s-8", state="exited")}
    f = facts(live={"board-1a2b3c4d", "board-0000aaaa"}, sessions=sessions)
    stage_job_pass.seat_pass(store, "board-answers", {}, f, w.reach())
    assert w.started == ["board-1a2b3c4d"]


def test_a_second_loss_to_the_person_starts_nothing_so_the_next_object_is_offered(store):
    put(store, holder="s-9", offers=2, entered_at="2026-11-20")
    w = World()
    f = facts(live={"board-1a2b3c4d", "board-0000aaaa"}, sessions={"s-9": session("s-9", state="exited")})
    steps = stage_job_pass.seat_pass(store, "board-answers", {"board-0000aaaa": "2026-11-24"}, f, w.reach())
    assert steps[0].act.case == "to-person" and w.lines == [("board-1a2b3c4d", stage_job_make.LOST_TWICE)]
    assert w.started == ["board-0000aaaa"]


def test_a_record_in_its_teams_review_does_not_hold_the_seat(store):
    put(store, stage="review", holder="s-8")
    w = World()
    f = facts(live={"board-1a2b3c4d", "board-0000aaaa"}, sessions={"s-8": session("s-8")})
    stage_job_pass.seat_pass(store, "board-answers", {"board-0000aaaa": "2026-11-24"}, f, w.reach())
    assert w.started == ["board-0000aaaa"]


def test_a_gone_object_closes_though_its_own_pull_requests_row_is_not_read(store):
    put(store, pr=7)
    steps = stage_job_pass.seat_pass(store, "board-answers", {}, facts(), World().reach())
    assert steps[0].act.case == "object-gone" and store.job("board-1a2b3c4d")["closed_at"]


def test_the_other_seats_records_are_not_this_seats(store):
    put(store, key="pr-4", seat="unheld-pull-requests", holder="s-9")
    w = World()
    f = facts(live={"board-1a2b3c4d", "pr-4"}, sessions={"s-9": session("s-9", ref="pr:4")})
    steps = stage_job_pass.seat_pass(store, "board-answers", {"board-1a2b3c4d": "2026-11-20"}, f, w.reach())
    assert [s.key for s in steps] == ["board-1a2b3c4d"] and w.started == ["board-1a2b3c4d"]


def test_no_started_team_offers_nothing(store):
    w = World()
    f = facts(live={"pr-4"}, started=(), may_start=False)
    steps = stage_job_pass.seat_pass(store, "unheld-pull-requests", {"pr-4": "2026-11-20"}, f, w.reach())
    assert steps[0].act is None and w.started == []


def test_a_failed_act_is_that_jobs_and_the_pass_goes_on(store, monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(a[1])
        raise RuntimeError("no store")

    monkeypatch.setattr(stage_job_make, "make", boom)
    f = facts(live={"board-1a2b3c4d"}, may_start=True)
    steps = stage_job_pass.seat_pass(store, "board-answers", {"board-1a2b3c4d": "x"}, f, World().reach())
    assert not steps[0].made.made and "no store" in steps[0].made.why and calls == ["board-1a2b3c4d"]


def test_an_unknown_seat_is_refused(store):
    with pytest.raises(ValueError):
        stage_job_pass.seat_pass(store, "sweeper", {}, facts(), World().reach())
