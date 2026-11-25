"""`ao stage end` from a built-in seat's job session (design §4.9d *How each one runs*, §4.7, TD-2053): `work-pushed`
checked as a build stage's with no entry archived, the board line closed or the given pull request, the move the flow
gives the stage that takes `other` entries, and `other`, a stage a job never goes to and a limit sending it to the
person by the home's own board line."""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass

import pytest

from shiftlead import stage_end, stage_job, stage_job_end, stage_make
from shiftlead.stage_end import PullRequest, Refused
from shiftlead.stage_job_end import closes_line, end_job, is_ref, key_of_ref

pytestmark = pytest.mark.unit

ME = "ao-repo-job-board-1a2b3c4d"
HEAD = "b" * 40
ITEM = "1a2b3c4d"


def flow(work_pushed="review", **build) -> dict:
    return {
        "format": 3,
        "name": "t",
        "max-moves": 25,
        "stages": [
            {"name": "Design", "does": "design", "model": "opus", "takes": "design-first", "work-pushed": "build"},
            {"name": "Build", "does": "build", "model": "opus", "takes": "any", "work-pushed": work_pushed, **build},
            {"name": "Review", "does": "review", "model": "sonnet", "ship": "merge", "changes-wanted": "build"},
        ],
    }


class Store:
    def __init__(self, record):
        self.record = record
        self.writes: list[str] = []

    def locked(self):
        return threading.RLock()

    def job(self, _key):
        return copy.deepcopy(self.record)

    def put_job(self, record, why):
        self.record = copy.deepcopy(dict(record))
        self.writes.append(why)


@dataclass
class Fake:
    pr: PullRequest | None
    on: str | None = "fix-board-line"
    local: str = HEAD
    read: str | None = HEAD

    def branch(self):
        return self.on

    def worktree_head(self):
        return self.local

    def fetched_head(self, _branch):
        return self.read

    def post_review(self, number, body):
        self.posted = (number, body)

    def pull_request(self, branch, number):
        self.asked = (branch, number)
        return self.pr


def _pr(**kw) -> PullRequest:
    base = {
        "number": 41,
        "head": HEAD,
        "branch": "fix-board-line",
        "state": "OPEN",
        "fork": False,
        "precheck": True,
        "files": ("src/x.py", f"docs/user_attention/archive/2026-11/2026-11-20-{ITEM}.md"),
    }
    return PullRequest(**{**base, **kw})


def _record(seat="board-answers", obj=ITEM, **kw) -> dict:
    return {**stage_job.new_job(seat, obj, "core", "2026-11-20T00:00:00Z"), "holder": ME, "offers": 1, **kw}


class Lines:
    def __init__(self, give="9f9f9f9f"):
        self.give, self.written = give, []

    def __call__(self, record, reason):
        self.written.append((record["id"], reason))
        return self.give


def _end(store, outcome="work-pushed", reason="", facts=None, doc=None, ref=f"board:{ITEM}", lines=None):
    return end_job(store, ref, ME, outcome, reason, doc or flow(), facts or Fake(_pr()), lines or Lines())


def test_a_job_reference_is_its_key():
    assert key_of_ref(f"board:{ITEM}") == f"board-{ITEM}"
    assert key_of_ref("pr:12") == "pr-12"
    assert is_ref("pr:12") and is_ref(f"board:{ITEM}")
    assert not is_ref("TD-12") and not is_ref("pr:0") and not is_ref("board:XYZ")


def test_work_pushed_takes_the_destination_of_the_stage_that_takes_other_entries():
    store = Store(_record())
    got = _end(store)
    assert got == {"entry": f"board:{ITEM}", "outcome": "work-pushed", "went": "review", "repeat": False}
    r = store.record
    assert (r["stage"], r["holder"], r["branch"], r["pr"], r["offers"]) == ("review", None, "fix-board-line", 41, 0)
    assert r["counts"] == {"build:work-pushed": 1} and r["moves"] == 1
    assert r["history"][-1]["from"] == "build" and r["history"][-1]["head"] == HEAD


def test_work_pushed_to_merge_waits_merging():
    store = Store(_record())
    assert _end(store, doc=flow("merge"))["went"] == "merge"
    assert store.record["waits"] == "merging" and store.record["stage"] == "build"
    assert store.record["merging"] == {"head": HEAD, "stage": "build", "outcome": "work-pushed"}


@pytest.mark.parametrize(
    "pr, words",
    [
        (None, "has no open pull request"),
        (_pr(state="CLOSED"), "is not open"),
        (_pr(fork=True), "is not open"),
        (_pr(precheck=False), "precheck is not green"),
        (_pr(head="c" * 40), "push your work"),
        (_pr(files=("src/x.py", "docs/ledger/archive/TD-7.md")), f"does not close the board line {ITEM}"),
        (_pr(files=(f"docs/user_attention/2026-11-20-{ITEM}.md",)), f"does not close the board line {ITEM}"),
    ],
)
def test_work_pushed_is_refused_when_its_fact_does_not_hold(pr, words):
    store = Store(_record())
    with pytest.raises(Refused, match=words):
        _end(store, facts=Fake(pr))
    assert store.writes == []


def test_a_job_archives_no_entry():
    assert closes_line(_pr().files, ITEM)
    store = Store(_record())
    assert _end(store, doc=flow("merge"))["went"] == "merge"  # no docs/ledger/archive/ file asked for


def test_a_pull_request_job_ends_on_the_pull_request_it_was_given():
    store = Store(_record("unheld-pull-requests", "41"))
    facts = Fake(_pr(files=("src/x.py",)), on=None)
    assert _end(store, ref="pr:41", facts=facts)["went"] == "review"
    assert facts.asked == (None, 41)
    other = Store(_record("unheld-pull-requests", "40"))
    with pytest.raises(Refused, match="not #40"):
        _end(other, ref="pr:40", facts=Fake(_pr()))


@pytest.mark.parametrize("to", ["design", "person"])
def test_a_stage_a_job_never_goes_to_sends_it_to_the_person(to):
    store, lines = Store(_record()), Lines()
    assert _end(store, doc=flow(to), lines=lines)["went"] == "person"
    r = store.record
    assert (r["waits"], r["person_line"], r["holder"], r["stage"]) == ("person", "9f9f9f9f", None, "build")
    assert r["pr"] == 41 and len(lines.written) == 1


def test_a_limit_reached_sends_the_job_to_the_person():
    store, lines = Store(_record(counts={"build:work-pushed": 2})), Lines()
    doc = flow()
    doc["stages"][1]["work-pushed"] = {"to": "review", "limit": 2}
    assert _end(store, doc=doc, lines=lines)["went"] == "person"
    assert "limit of 2" in lines.written[0][1] and store.record["counts"] == {"build:work-pushed": 2}


def test_other_needs_a_reason_and_goes_to_the_person_by_the_homes_line():
    store, lines = Store(_record()), Lines()
    with pytest.raises(Refused, match="needs --reason"):
        _end(store, "other", lines=lines)
    got = _end(store, "other", "the line asks for a login only the person has", lines=lines)
    assert got["went"] == "person" and lines.written == [
        (f"board-{ITEM}", "the line asks for a login only the person has")
    ]
    assert store.record["waits"] == "person" and store.record["person_line"] == "9f9f9f9f"


def test_a_line_not_written_writes_nothing():
    store = Store(_record())
    with pytest.raises(Refused, match="could not be written"):
        _end(store, "other", "stuck", lines=Lines(give=None))
    assert store.writes == []


def test_an_entrys_outcome_is_refused():
    with pytest.raises(Refused, match="not an outcome of a job"):
        _end(Store(_record()), "not-needed", "x")


def test_a_call_from_a_session_the_record_does_not_name_is_refused():
    with pytest.raises(Refused, match="not yours"):
        _end(Store(_record(holder="ao-repo-job-other")))
    with pytest.raises(Refused, match="has no job record"):
        _end(Store(None))


def test_a_repeated_call_is_answered_with_where_the_job_went():
    store = Store(_record())
    _end(store)
    again = _end(store)
    assert again["repeat"] and again["went"] == "review" and len(store.writes) == 1


def test_a_closed_job_is_refused_as_closed():
    with pytest.raises(Refused, match="the job is closed"):
        _end(Store(_record(closed_at="2026-11-21T00:00:00Z", holder=None)))


def test_a_job_past_its_own_stage_is_not_ended_by_a_job_session():
    with pytest.raises(Refused, match="work-pushed is not an outcome of a review stage"):
        _end(Store(_record(stage="review")))
    with pytest.raises(Refused, match="stands at stage design, which is no review stage"):
        _end(Store(_record(stage="design")), "other", "x")


def _reviewed(**kw) -> dict:
    """A job the flow sent to its review stage, held by that stage's session."""
    return _record(
        **{
            "stage": "review",
            "branch": "fix-board-line",
            "pr": 41,
            "counts": {"build:work-pushed": 1},
            "moves": 1,
            **kw,
        }
    )


def test_a_review_stages_ship_on_a_job_waits_merging_and_posts_its_review():
    store, facts = Store(_reviewed()), Fake(_pr())
    got = _end(store, "ship", facts=facts)
    assert got == {"entry": f"board:{ITEM}", "outcome": "ship", "went": "merge", "repeat": False}
    r = store.record
    assert (r["stage"], r["holder"], r["waits"]) == ("review", None, "merging")
    assert r["merging"] == {"head": HEAD, "stage": "review", "outcome": "ship"}
    assert r["verdicts"] == {"review": {"head": HEAD, "stage": "review", "outcome": "ship"}}
    assert r["counts"] == {"build:work-pushed": 1} and r["moves"] == 1, "a move to merge is never counted"
    number, body = facts.posted
    assert number == 41 and body.startswith("cadence-review: SHIP · sonnet · code · 0 findings")
    step = r["history"][-1]
    assert (step["from"], step["outcome"], step["to"], step["head"]) == ("review", "ship", "merge", HEAD)
    assert "run" not in step and "findings" not in step, "a job's rows carry no run and no findings"


def test_a_reviews_repeat_is_answered_and_a_verdict_sent_to_the_person_keeps_its_stage():
    store = Store(_reviewed())
    _end(store, "ship")
    again = _end(store, "ship")
    assert again["repeat"] and again["went"] == "merge" and len(store.writes) == 1
    doc = flow()
    doc["stages"][2]["ship"] = "person"
    store = Store(_reviewed())
    assert _end(store, "ship", doc=doc)["went"] == "person"
    r = store.record
    assert (r["stage"], r["waits"], r["verdicts"]["review"]["outcome"]) == ("review", "person", "ship")


def test_a_ship_on_a_head_the_review_did_not_read_is_refused_and_writes_nothing():
    store = Store(_reviewed())
    with pytest.raises(Refused, match="not what you read"):
        _end(store, "ship", facts=Fake(_pr(), read="d" * 40))
    assert store.writes == []
    with pytest.raises(Refused, match="no open pull request to give a verdict on"):
        _end(store, "ship", facts=Fake(_pr(state="CLOSED")))


def test_changes_wanted_sends_the_job_back_to_a_fresh_job_session_told_the_review():
    store, facts = Store(_reviewed()), Fake(_pr())
    with pytest.raises(Refused, match="changes-wanted needs --reason"):
        _end(store, "changes-wanted", facts=facts)
    assert _end(store, "changes-wanted", "the test misses the closed line", facts=facts)["went"] == "build"
    r = store.record
    assert (r["stage"], r["holder"], r["offers"], r["waits"]) == ("build", None, 0, None)
    assert r["counts"] == {"build:work-pushed": 1, "review:changes-wanted": 1} and r["moves"] == 2
    assert facts.posted[1].startswith("cadence-review: BLOCK · sonnet · code · 1 findings")
    assert stage_job.choose(r, stage_job.JobReading(may_start=True)) == stage_job.JobAct("offer")
    came, _answer = stage_make._came(r, "build")
    assert came == "the test misses the closed line (`changes-wanted` at `review`)"


def test_changes_wanted_on_a_job_is_taken_when_the_head_moved_since_it_was_read():
    store, facts = Store(_reviewed()), Fake(_pr(), read="d" * 40)
    assert _end(store, "changes-wanted", "the test misses the closed line", facts=facts)["went"] == "build"
    assert facts.posted[1].startswith("cadence-review: BLOCK · sonnet · code · 1 findings")
    assert store.record["verdicts"]["review"]["head"] == "d" * 40, "the verdict names the head the review read"


def test_a_reviews_move_past_its_limit_or_the_cap_goes_to_the_person():
    doc = flow()
    doc["stages"][2]["changes-wanted"] = {"to": "build", "limit": 1}
    store, lines = Store(_reviewed(counts={"review:changes-wanted": 1})), Lines()
    assert _end(store, "changes-wanted", "again", doc=doc, lines=lines)["went"] == "person"
    assert lines.written == [(f"board-{ITEM}", "changes-wanted from review reached its limit of 1")]
    assert store.record["stage"] == "review" and store.record["person_line"] == "9f9f9f9f"
    doc = flow()
    doc["max-moves"] = 1
    store, lines = Store(_reviewed()), Lines()
    assert _end(store, "changes-wanted", "again", doc=doc, lines=lines)["went"] == "person"
    assert lines.written[0][1] == "the job reached the flow's cap of 1 moves"


def test_a_reviews_other_and_a_stage_a_job_never_goes_to_are_the_persons():
    store, lines = Store(_reviewed()), Lines()
    assert _end(store, "other", "the diff is not what the line asked", lines=lines)["went"] == "person"
    assert lines.written == [(f"board-{ITEM}", "the diff is not what the line asked")]
    doc = flow()
    doc["stages"][2]["changes-wanted"] = "design"
    store, lines = Store(_reviewed()), Lines()
    assert _end(store, "changes-wanted", "x", doc=doc, lines=lines)["went"] == "person"
    assert lines.written[0][1] == "the flow sends changes-wanted from review to design, a stage a job never goes to"


def test_a_job_outcome_is_refused_from_a_review_stages_session_and_a_review_outcome_from_a_job_session():
    with pytest.raises(Refused, match="not an outcome of a review stage"):
        _end(Store(_reviewed()), "work-pushed")
    with pytest.raises(Refused, match="ship is not an outcome of a job"):
        _end(Store(_record()), "ship")


def test_a_flow_with_no_stage_that_takes_other_entries_refuses():
    doc = flow()
    doc["stages"][1]["takes"] = "build"
    with pytest.raises(Refused, match="no stage that takes other entries"):
        _end(Store(_record()), doc=doc)


def test_the_call_routes_a_job_reference_to_the_job_end(monkeypatch, tmp_path):
    seen = {}

    class FakeStore:
        def __init__(self, root):
            pass

        def flow(self, team):
            return "format: 3\nname: t\nstages: []\n"

    def fake_end_job(store, ref, caller, outcome, reason, doc, facts, line, *, board):
        seen.update(ref=ref, caller=caller, outcome=outcome, doc=doc, line=callable(line), board=board)
        return {"entry": ref, "outcome": outcome, "went": "review", "repeat": False}

    monkeypatch.setattr(stage_end, "StageStore", FakeStore)
    monkeypatch.setattr(stage_job_end, "end_job", fake_end_job)
    got = stage_end.call(
        root=str(tmp_path),
        directory=str(tmp_path),
        team="core",
        tid="pr:41",
        caller=ME,
        outcome="work-pushed",
        reason="",
    )
    assert got["went"] == "review"
    assert seen == {
        "ref": "pr:41",
        "caller": ME,
        "outcome": "work-pushed",
        "doc": {"format": 3, "name": "t", "stages": []},
        "line": True,
        "board": "docs/user_attention",
    }


def test_a_move_to_merge_is_never_counted_against_a_limit_or_the_cap():
    store = Store(_record(moves=25, counts={"build:work-pushed": 3}))
    doc = flow()
    doc["stages"][1]["work-pushed"] = {"to": "merge", "limit": 3}
    assert _end(store, doc=doc)["went"] == "merge"
    assert store.record["moves"] == 25 and store.record["counts"] == {"build:work-pushed": 3}


def test_the_line_is_closed_only_under_the_boards_own_archive():
    moved = (f"docs/user_attention/archive/2026-11/2026-11-20-{ITEM}.md",)
    assert closes_line(moved, ITEM) and not closes_line(moved, ITEM, "ops/board")
    assert not closes_line((f"docs/other/archive/2026-11/2026-11-20-{ITEM}.md",), ITEM)
    assert closes_line((f"ops/board/archive/2026-11/2026-11-20-{ITEM}.md",), ITEM, "ops/board")
    store = Store(_record())
    with pytest.raises(Refused, match="does not close the board line"):
        end_job(store, f"board:{ITEM}", ME, "work-pushed", "", flow(), Fake(_pr()), Lines(), board="ops/board")


def test_a_move_back_to_the_jobs_own_stage_is_counted_and_offered_afresh():
    store = Store(_record())
    assert _end(store, doc=flow("build"))["went"] == "build"
    r = store.record
    assert (r["stage"], r["holder"], r["offers"], r["moves"], r["waits"]) == ("build", None, 0, 1, None)
    assert stage_job.choose(r, stage_job.JobReading(may_start=True)) == stage_job.JobAct("offer")


def test_a_job_at_a_review_stage_is_offered_that_stages_session_not_a_job_session():
    store = Store(_record())
    _end(store)
    reading = stage_job.JobReading(may_start=True, at_job_stage=False, seat_busy=True)
    assert stage_job.choose(store.record, reading) == stage_job.JobAct("offer", "review")
    assert stage_job.order([store.record], {}, "build") == []  # never queued among the seat's job sessions


def test_the_board_directory_is_the_stubs_name_less_md(tmp_path):
    (tmp_path / "docs" / "user_attention").mkdir(parents=True)
    (tmp_path / "docs" / "user_attention.md").write_text("stub\n")
    assert stage_job_end.board_dir(tmp_path) == "docs/user_attention"
