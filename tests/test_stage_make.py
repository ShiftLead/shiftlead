"""Making the acts that only write a stage record (design §4.9c *The home acts only where no session will*, TD-2051),
on a real `shiftlead/state` branch in a scratch repo and its bare origin."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from shiftlead.stage_acts import Act, Holder, Reading, choose
from shiftlead.stage_end import ARCHIVE
from shiftlead.stage_make import make, sweep_closed
from shiftlead.stagerecord import OTHER, StageStore, new_record

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


def test_the_archive_answer_is_left_for_its_own_slice(store):
    before = put(store, waits="person", answers={"Archive the entry": {"archive": True}, OTHER: None})
    assert not act_on(store, Reading(lifted="Archive the entry")).made
    assert store.entry(TID) == before


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
