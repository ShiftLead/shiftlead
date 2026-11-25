"""The home's merge of a job marked `merging` (design §4.9d *How each one runs*, §4.9c *The merge gate under a flow*,
TD-2053): the gate on the head the job pushed, the merge on a pass, the job stage's `refused` move on a cause a session
can cure, the person on a row only they can cure, and an hour of no reading before the person."""

from __future__ import annotations

import copy
import threading
from datetime import UTC, datetime, timedelta

import pytest

from shiftlead import stage_job, stage_job_merge, stage_job_tick
from shiftlead.stage_job_make import JobReach
from shiftlead.stage_job_pass import JobStep

pytestmark = pytest.mark.unit

HEAD = "c" * 40
KEY = "pr-41"
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def flow(refused=None) -> dict:
    pushed: dict = {"to": "merge"}
    if refused is not None:
        pushed["refused"] = refused
    return {
        "format": 3,
        "name": "t",
        "max-moves": 25,
        "stages": [
            {"name": "Build", "does": "build", "model": "opus", "takes": "any", "work-pushed": pushed},
            {"name": "Review", "does": "review", "model": "sonnet", "ship": "merge", "changes-wanted": "build"},
        ],
    }


def merging_record(**kw) -> dict:
    base = stage_job.new_job("unheld-pull-requests", 41, "core", "2026-11-20T00:00:00Z")
    return {
        **base,
        "pr": 41,
        "branch": "fix",
        "stage": "build",
        "waits": "merging",
        "merging": {"head": HEAD, "stage": "build", "outcome": "work-pushed"},
        **kw,
    }


class Store:
    def __init__(self, *records):
        self.records = {r["id"]: copy.deepcopy(r) for r in records}
        self.writes: list[str] = []
        self.lock = threading.RLock()

    def locked(self):
        return self.lock

    def job(self, key):
        return copy.deepcopy(self.records.get(key))

    def jobs(self):
        return copy.deepcopy(self.records)

    def put_job(self, record, why):
        self.records[record["id"]] = copy.deepcopy(dict(record))
        self.writes.append(why)


class Lines:
    def __init__(self, give="9f9f9f9f"):
        self.give, self.written = give, []

    def __call__(self, record, reason):
        self.written.append((record["id"], reason))
        return self.give


def gate_of(verdict="pass", failed=(), raises=None):
    ran: list[tuple[int, str]] = []

    def gate(pr, head):
        ran.append((pr, head))
        if raises:
            raise raises
        return None if verdict is None else {"verdict": verdict, "failed": list(failed)}

    return gate, ran


def land_of(why=None):
    landed: list[tuple[int, str]] = []

    def land(pr, head):
        landed.append((pr, head))
        return why

    return land, landed


def a_run(store, *, head=HEAD, doc=None, gate=None, land=None, line=None, now=NOW):
    gate = gate or gate_of()[0]
    land = land or land_of()[0]
    return stage_job_merge.run(store, KEY, head, doc or flow(), gate, land, line or Lines(), now)


def test_merging_lists_the_open_jobs_waiting_on_the_merge():
    other = {**merging_record(), "id": "pr-42", "waits": None}
    gone = {**merging_record(), "id": "pr-43", "closed_at": "2026-11-24T00:00:00Z"}
    assert stage_job_merge.merging(Store(merging_record(), other, gone)) == [KEY]


def test_a_pass_merges_at_the_head_the_job_pushed_and_leaves_the_record_to_reconcile():
    store = Store(merging_record())
    gate, ran = gate_of()
    land, landed = land_of()
    made = a_run(store, gate=gate, land=land)
    assert made.made and ran == [(41, HEAD)] and landed == [(41, HEAD)]
    assert store.records[KEY]["waits"] == "merging", "Reconcile closes it once the merge is read"


def test_a_head_moved_takes_the_refused_move_back_to_the_job_stage_and_counts_it():
    store = Store(merging_record())
    gate, ran = gate_of()
    made = a_run(store, head="d" * 40, gate=gate, doc=flow(refused="build"))
    r = store.records[KEY]
    assert made.made and not ran, "no gate runs on a head the job did not push"
    assert (r["stage"], r["waits"], r["merging"], r["holder"], r["offers"]) == ("build", None, None, None, 0)
    assert r["counts"] == {"build:refused": 1} and r["moves"] == 1
    step = r["history"][-1]
    assert (step["outcome"], step["to"], step["by"]) == ("refused", "build", "home")
    assert step["reason"].startswith("the head is dddddddddddd")


def test_a_session_row_names_the_failing_rows_and_goes_back_to_the_job_stage():
    store = Store(merging_record())
    made = a_run(store, gate=gate_of("fail", ("ci", "board"))[0], doc=flow(refused="build"))
    r = store.records[KEY]
    assert made.made and r["stage"] == "build" and r["history"][-1]["reason"] == "the merge gate failed on ci, board"


def test_a_session_row_may_go_back_to_a_review_stage():
    store = Store(merging_record())
    assert a_run(store, gate=gate_of("fail", ("review",))[0], doc=flow(refused="review")).made
    assert store.records[KEY]["stage"] == "review"


def test_a_refused_merge_after_a_reviews_ship_takes_the_review_stages_refused_move():
    doc = flow()
    doc["stages"][1]["ship"] = {"to": "merge", "refused": "build"}
    merging = {"head": HEAD, "stage": "review", "outcome": "ship"}
    store = Store(merging_record(stage="review", merging=merging))
    made = a_run(store, gate=gate_of("fail", ("ci",))[0], doc=doc)
    r = store.records[KEY]
    assert made.made and (r["stage"], r["waits"], r["holder"]) == ("build", None, None)
    assert r["counts"] == {"review:refused": 1} and r["moves"] == 1
    assert (r["history"][-1]["from"], r["history"][-1]["to"]) == ("review", "build")


def test_a_refused_move_left_to_its_default_goes_to_the_person_by_the_homes_line():
    store, lines = Store(merging_record()), Lines()
    made = a_run(store, gate=gate_of("fail", ("ci",))[0], line=lines)
    r = store.records[KEY]
    assert made.made and (r["waits"], r["person_line"], r["merging"]) == ("person", "9f9f9f9f", None)
    assert lines.written == [(KEY, "the merge was refused: the merge gate failed on ci")]
    step = r["history"][-1]
    assert (step["outcome"], step["to"], step["by"], step["head"]) == ("refused", "person", "home", HEAD)


def test_a_refused_move_past_its_limit_goes_to_the_person():
    store, lines = Store(merging_record(counts={"build:refused": 1})), Lines()
    made = a_run(store, gate=gate_of("fail", ("ci",))[0], doc=flow(refused={"to": "build", "limit": 1}), line=lines)
    assert made.made and store.records[KEY]["waits"] == "person" and "limit" in lines.written[0][1]
    assert store.records[KEY]["counts"] == {"build:refused": 1}, "a move not made is not counted"


def test_a_refused_move_to_a_stage_a_job_never_goes_to_is_the_persons():
    doc = flow(refused="design")
    doc["stages"].insert(0, {"name": "Design", "does": "design", "model": "opus", "takes": "design-first"})
    store = Store(merging_record())
    assert a_run(store, gate=gate_of("fail", ("ci",))[0], doc=doc).made
    assert store.records[KEY]["waits"] == "person"


@pytest.mark.parametrize("failed", [("reach",), ("ci", "person"), ("a-row-a-later-pin-adds",), ()])
def test_a_row_only_a_person_can_cure_goes_to_the_person_spending_no_limit(failed):
    store, lines = Store(merging_record()), Lines()
    made = a_run(store, gate=gate_of("fail", failed)[0], doc=flow(refused="build"), line=lines)
    r = store.records[KEY]
    assert made.made and r["waits"] == "person" and not r.get("counts") and "needs a person" in lines.written[0][1]


def test_no_reading_waits_an_hour_and_then_goes_to_the_person():
    store, lines = Store(merging_record()), Lines()
    first = a_run(store, gate=gate_of(None)[0], line=lines)
    assert not first.made and store.records[KEY]["merging"]["unread_since"] == "2026-11-25T12:00:00Z"
    soon = a_run(store, gate=gate_of(None)[0], line=lines, now=NOW + timedelta(minutes=59))
    assert not soon.made and store.records[KEY]["waits"] == "merging" and not lines.written
    late = a_run(store, gate=gate_of(None)[0], line=lines, now=NOW + timedelta(hours=1))
    assert late.made and store.records[KEY]["waits"] == "person" and "no reading for an hour" in lines.written[0][1]


@pytest.mark.parametrize(
    "over",
    [
        {"head": None},
        {"gate": gate_of(raises=RuntimeError("no script"))[0]},
        {"land": land_of("the pull request conflicts")[0]},
    ],
    ids=["head-unread", "gate-raises", "land-fails"],
)
def test_what_gives_no_reading_leaves_the_record_merging(over):
    store = Store(merging_record())
    assert not a_run(store, **over).made
    r = store.records[KEY]
    assert r["waits"] == "merging" and r["merging"]["unread_since"]


def test_a_record_that_moved_is_left_as_it_is():
    store = Store(merging_record(waits=None))
    gate, ran = gate_of()
    assert not a_run(store, gate=gate).made and not ran and not store.writes


def test_a_record_moved_while_the_gate_ran_is_never_merged():
    store = Store(merging_record())
    land, landed = land_of()

    def gate(pr, head):
        store.records[KEY]["waits"] = None  # an answer landed meanwhile
        return {"verdict": "pass", "failed": []}

    made = a_run(store, gate=gate, land=land)
    assert not made.made and not landed


def test_the_tick_merges_each_job_waiting_by_its_open_rows_head_and_its_teams_flow():
    other = {**merging_record(), "id": "board-1a2b3c4d", "seat": "board-answers", "pr": 7, "team": "gone"}
    store = Store(merging_record(), other)
    gate, ran = gate_of()
    land, landed = land_of()
    reach = JobReach(lambda r, c: None, lambda h, r: None, Lines(), lambda i: None, lambda h: None)
    rows = [{"number": 41, "state": "open", "head": HEAD}, {"number": 7, "state": "open", "head": "e" * 40}]
    got = stage_job_tick.merges(store, rows, {"core": flow()}, (gate, land), reach)
    assert ran == [(41, HEAD)], "a job whose team's flow is not read this pass is left as it is"
    assert list(got) == ["unheld-pull-requests"]
    (step,) = got["unheld-pull-requests"]
    assert isinstance(step, JobStep) and step.key == KEY and step.act == stage_job_tick.MERGING and step.made.made


def test_a_refused_move_to_merge_itself_is_the_persons():
    store = Store(merging_record())
    assert a_run(store, gate=gate_of("fail", ("ci",))[0], doc=flow(refused="merge")).made
    assert store.records[KEY]["waits"] == "person" and not store.records[KEY].get("counts")


def test_a_refused_move_at_the_flows_cap_goes_to_the_person_uncounted():
    store, lines = Store(merging_record(moves=25)), Lines()
    assert a_run(store, gate=gate_of("fail", ("ci",))[0], doc=flow(refused="build"), line=lines).made
    r = store.records[KEY]
    assert r["waits"] == "person" and r["moves"] == 25 and "cap" in lines.written[0][1]


@pytest.mark.parametrize("line", [Lines(give=None), lambda record, reason: 1 / 0], ids=["none", "raises"])
def test_a_line_that_cannot_be_written_leaves_the_record_merging(line):
    store = Store(merging_record())
    assert not a_run(store, gate=gate_of("fail", ("reach",))[0], line=line).made
    assert store.records[KEY]["waits"] == "merging" and not store.writes


def test_a_failure_read_after_the_record_moved_writes_nothing():
    store = Store(merging_record())

    def gate(pr, head):
        store.records[KEY]["merging"]["head"] = "a" * 40  # a fresh work-pushed landed meanwhile
        return {"verdict": "fail", "failed": ["ci"]}

    assert not a_run(store, gate=gate, doc=flow(refused="build")).made and not store.writes
