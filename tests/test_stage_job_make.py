"""The write of a built-in seat's job act (design §4.9d *How each one runs*, TD-2053)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shiftlead import stage_job, stage_job_make
from shiftlead.stage_acts import Holder
from shiftlead.stage_job import JobAct, JobReading
from shiftlead.stagerecord import StageStore

pytestmark = pytest.mark.unit


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
    def __init__(self, holder: str | None = "s-1", refused: str | None = None, line: str | None = "line-1"):
        self.holder, self.refused, self.line_id = holder, refused, line
        self.started: list[tuple[dict, str | None]] = []
        self.claims: list[tuple[str, str]] = []
        self.lines: list[tuple[str, str]] = []
        self.closed: list[str] = []
        self.ended: list[str] = []
        self.end_fails = False

    def reach(self) -> stage_job_make.JobReach:
        def start(record, came):
            self.started.append((dict(record), came))
            return self.holder

        def claim(holder, ref):
            self.claims.append((holder, ref))
            return self.refused

        def line(record, reason):
            self.lines.append((record["id"], reason))
            return self.line_id

        def end(holder):
            if self.end_fails:
                raise RuntimeError("no answer")
            self.ended.append(holder)

        return stage_job_make.JobReach(start, claim, line, self.closed.append, end)


GO = JobReading(may_start=True)
KEY = "board-1a2b3c4d"


def make(store, act, s, w, key=KEY, seat="board-answers", obj="1a2b3c4d"):
    return stage_job_make.make(store, key, act, s, w.reach(), seat=seat, obj=obj, team="t", opened_at="2026-11-24")


def put(store, **kw):
    record = {**stage_job.new_job("board-answers", "1a2b3c4d", "t", "2026-11-24"), **kw}
    store.put_job(record, "test")
    return record


def test_an_object_with_no_record_is_offered_its_record_written_with_its_holder_and_claim(store):
    w = World()
    got = make(store, JobAct("offer", "new"), GO, w)
    assert got.made and got.end is None
    r = store.job(KEY)
    assert (r["holder"], r["offers"], r["team"], r["entered_at"]) == ("s-1", 1, "t", "2026-11-24")
    assert w.claims == [("s-1", "board:1a2b3c4d")] and w.started[0][1] is None


def test_a_pull_requests_job_claims_its_pr_order(store):
    w = World()
    act = JobAct("offer", "new")
    assert make(store, act, GO, w, key="pr-42", seat="unheld-pull-requests", obj=42).made
    assert w.claims == [("s-1", "pr:42")] and store.job("pr-42")["object"] == "42"


def test_no_session_started_writes_nothing(store):
    got = make(store, JobAct("offer", "new"), GO, World(holder=None))
    assert not got.made and store.job(KEY) is None


def test_a_refused_claim_writes_nothing_and_names_the_session_to_end(store):
    got = make(store, JobAct("offer", "new"), GO, World(refused="held by s-9"))
    assert not got.made and got.end == "s-1" and "held by s-9" in got.why and store.job(KEY) is None


def test_an_act_the_record_no_longer_chooses_is_refused(store):
    put(store, holder="s-0")
    w = World()
    assert make(store, JobAct("offer", "new"), GO, w).why == "the record moved since it was read" and not w.started


def test_a_closed_record_is_written_over_by_a_new_job(store):
    put(store, closed_at="2026-11-01T00:00:00Z", offers=2, history=[{"x": 1}])
    assert make(store, JobAct("offer", "new"), GO, World()).made
    r = store.job(KEY)
    assert (r["closed_at"], r["offers"], r["history"], r["holder"]) == (None, 1, [], "s-1")


def test_a_lost_job_is_offered_again_once_and_the_lost_session_named_to_end(store):
    put(store, holder="s-0", offers=1)
    s = JobReading(may_start=True, holder=Holder(ended=True))
    act = stage_job.choose(store.job(KEY), s)
    assert act == JobAct("offer-again", "lost")
    w = World(holder="s-2")
    got = make(store, act, s, w)
    assert got.made and got.end is None and w.ended == ["s-0"]
    assert (store.job(KEY)["holder"], store.job(KEY)["offers"]) == ("s-2", 2)
    assert w.started[0][0]["holder"] is None


def test_a_second_loss_goes_to_the_person_by_the_homes_line(store):
    put(store, holder="s-2", offers=2)
    s = JobReading(may_start=True, holder=Holder(ended=True))
    act = stage_job.choose(store.job(KEY), s)
    assert act == JobAct("offer-again", "to-person")
    w = World()
    got = make(store, act, s, w)
    assert got.made and got.end == "s-2" and not w.started
    r = store.job(KEY)
    assert (r["waits"], r["person_line"], r["holder"]) == ("person", "line-1", None)
    assert w.lines == [(KEY, stage_job_make.LOST_TWICE)]


def test_no_line_written_leaves_the_record_for_the_next_pass(store):
    put(store, holder="s-2", offers=2)
    s = JobReading(may_start=True, holder=Holder(ended=True))
    got = make(store, JobAct("offer-again", "to-person"), s, World(line=None))
    assert not got.made and store.job(KEY)["holder"] == "s-2"


def test_an_object_gone_closes_the_record_and_the_homes_line(store):
    put(store, waits="person", person_line="line-7")
    w = World()
    got = make(store, JobAct("reconcile", "object-gone"), JobReading(live=False), w)
    assert got.made and w.closed == ["line-7"] and store.job(KEY)["closed_at"]


def test_an_object_gone_under_a_holder_ends_it(store):
    put(store, holder="s-3")
    got = make(store, JobAct("reconcile", "object-gone"), JobReading(live=False), World())
    assert got.end == "s-3" and store.job(KEY)["holder"] is None


def test_a_board_answers_pull_request_closed_unmerged_goes_to_the_person(store):
    put(store, holder="s-3", pr=9)
    w = World()
    got = make(store, JobAct("reconcile", "pr-closed"), JobReading(own_pr="closed"), w)
    assert got.made and got.end == "s-3" and store.job(KEY)["waits"] == "person"
    assert w.lines == [(KEY, stage_job_make.PR_CLOSED)]


def test_the_persons_line_closed_clears_the_wait_and_the_counts(store):
    put(store, waits="person", person_line="line-1", offers=2, counts={"a": 1}, moves=3)
    got = make(store, JobAct("reconcile", "person-cleared"), JobReading(person_line="closed"), World())
    r = store.job(KEY)
    assert got.made and (r["waits"], r["person_line"], r["offers"], r["counts"], r["moves"]) == (None, None, 0, {}, 0)


def test_a_record_given_to_the_first_started_team_keeps_its_branch(store):
    put(store, team="old", branch="b", pr=9, offers=1)
    s = JobReading(team_started=False, first_started="new")
    assert make(store, JobAct("reconcile", "team-moved"), s, World()).made
    r = store.job(KEY)
    assert (r["team"], r["branch"], r["pr"], r["offers"]) == ("new", "b", 9, 0)


def test_a_stage_gone_starts_again_on_its_own_team_never_the_person(store):
    put(store, stage="build", flow="f", holder="s-4", offers=1)
    w = World()
    got = make(store, JobAct("reconcile", "stage-gone"), JobReading(stage_known=False), w)
    r = store.job(KEY)
    assert got.made and got.end == "s-4" and (r["team"], r["stage"], r["waits"]) == ("t", None, None)
    assert r["holder"] is None, "its holder ended first: the record offered afresh names none"
    assert not w.lines


def test_a_job_sent_back_by_a_move_is_told_that_moves_reason(store):
    back = {"from": "review", "to": "build", "outcome": "changes-wanted", "reason": "the test asserts nothing"}
    put(store, stage="build", flow="f", holder="s-0", offers=1, history=[back])
    s = JobReading(may_start=True, holder=Holder(ended=True))
    act = stage_job.choose(store.job(KEY), s)
    assert act == JobAct("offer-again", "lost")
    w = World(holder="s-2")
    assert make(store, act, s, w).made
    assert w.started[0][1] == "the test asserts nothing (`changes-wanted` at `review`)"


def test_a_silent_holder_is_ended_before_another_session_starts(store):
    put(store, holder="s-0", offers=1)
    s = JobReading(may_start=True, holder=Holder(lease_lapsed=True))
    act = stage_job.choose(store.job(KEY), s)
    assert act is not None and act.name == "offer-again"
    w = World()
    w.end_fails = True
    got = make(store, act, s, w)
    assert not got.made and not w.started and store.job(KEY)["holder"] == "s-0"


def test_offer_again_with_no_session_started_keeps_the_count_for_the_next_pass(store):
    put(store, holder="s-0", offers=1)
    s = JobReading(may_start=True, holder=Holder(ended=True))
    got = make(store, JobAct("offer-again", "lost"), s, World(holder=None))
    assert not got.made and got.end is None and store.job(KEY)["offers"] == 1


def test_a_start_that_raises_is_that_jobs_failure(store):
    w = World()

    def boom(_r, _c):
        raise RuntimeError("tmux")

    reach = w.reach()
    reach = stage_job_make.JobReach(boom, reach.claim, reach.line, reach.close_line, reach.end)
    got = stage_job_make.make(
        store, KEY, JobAct("offer", "new"), GO, reach, seat="board-answers", obj="1a2b3c4d", team="t", opened_at="x"
    )
    assert not got.made and "tmux" in got.why and store.job(KEY) is None


@pytest.mark.parametrize("fails", ["claim", "record"])
def test_an_offer_that_fails_after_its_session_started_names_that_session_to_end(store, monkeypatch, fails):
    """TD-2166: a started session whose claim or record could not be written is named in `end`, never left running."""
    w = World()
    reach = w.reach()

    def boom(*_a, **_k):
        raise RuntimeError("disk full")

    if fails == "claim":
        reach = stage_job_make.JobReach(reach.start, boom, reach.line, reach.close_line, reach.end)
    else:
        monkeypatch.setattr(store, "put_job", boom)
    got = stage_job_make.make(
        store, KEY, JobAct("offer", "new"), GO, reach, seat="board-answers", obj="1a2b3c4d", team="t", opened_at="x"
    )
    assert len(w.started) == 1 and not got.made
    assert got.end == "s-1" and "the offer did not finish: disk full" in got.why


def test_an_object_gone_not_waiting_on_the_person_closes_no_line(store):
    put(store)
    w = World()
    assert make(store, JobAct("reconcile", "object-gone"), JobReading(live=False), w).made and w.closed == []


def test_a_review_offer_on_a_record_moved_back_to_the_jobs_stage_is_refused(store):
    put(store, stage="build")  # read at the review stage, moved back to the job's own stage under the lock
    w = World()
    got = make(store, JobAct("offer", "review"), JobReading(may_start=True, at_job_stage=False, job_stage="build"), w)
    assert not got.made and "moved" in got.why and w.started == []


def test_a_review_offer_on_a_record_still_at_its_review_stage_starts_that_session(store):
    put(store, stage="review")
    w = World()
    got = make(store, JobAct("offer", "review"), JobReading(may_start=True, at_job_stage=False, job_stage="build"), w)
    assert got.made and store.job(KEY)["holder"] == "s-1" and store.job(KEY)["stage"] == "review"
