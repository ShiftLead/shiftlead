"""The home's merge of a record marked `merging` (design §4.9c *The merge gate under a flow*, TD-2051), on a real
`shiftlead/state` branch in a scratch repo and its bare origin."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from shiftlead.stage_acts import Act, Reading, choose
from shiftlead.stage_end import TRY_AGAIN
from shiftlead.stage_make import make
from shiftlead.stage_merge import MERGING, NO_READING_FOR, run
from shiftlead.stagerecord import StageStore, new_record

TID = "TD-7"
HEAD = "a" * 40
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
FLOW: dict[str, Any] = {
    "format": 3,
    "name": "f",
    "stages": [
        {"name": "build", "does": "build", "model": "m", "takes": "any", "work-pushed": "review"},
        {
            "name": "review",
            "does": "review",
            "model": "m",
            "ship": {"to": "merge", "refused": {"to": "build", "limit": 1}},
        },
        {"name": "plain", "does": "review", "model": "m", "ship": "merge"},
    ],
}
READ = Reading(pr_state="open", head=HEAD)


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


def put(store: StageStore, stage: str = "review", **over: Any) -> None:
    merging = {"head": HEAD, "stage": stage, "outcome": "ship"}
    store.put_entry({**new_record(TID, "f", stage), "pr": 4, "waits": "merging", "merging": merging, **over}, "test")


def go(store: StageStore, got: Any, s: Reading = READ, land: Any = None, now: datetime = NOW) -> Any:
    landed: list[tuple[int, str]] = []

    def default(pr: int, head: str) -> None:
        landed.append((pr, head))

    made = run(store, TID, MERGING, s, FLOW, "paul", lambda _p, _h: got, land or default, now)
    return made, landed


def test_a_passing_gate_merges_that_head_and_leaves_the_close_to_reconcile(store):
    put(store)
    made, landed = go(store, {"verdict": "pass", "failed": []})
    assert made.made and landed == [(4, HEAD)]
    assert store.entry(TID)["waits"] == "merging"
    assert choose(store.entry(TID), Reading(entry="archived", pr_state="merged")) == Act("reconcile", "close")


def test_a_row_a_session_can_cure_takes_the_refused_move_and_counts_it(store):
    put(store)
    made, landed = go(store, {"verdict": "fail", "failed": ["ci"]})
    r = store.entry(TID)
    assert made.made and not landed
    assert (r["stage"], r["waits"], r["merging"]) == ("build", None, None)
    assert r["counts"]["review:refused"] == 1 and r["history"][-1]["by"] == "home"


def test_a_refused_move_past_its_limit_goes_to_the_person(store):
    put(store, counts={"review:refused": 1})
    made, _ = go(store, {"verdict": "fail", "failed": ["review"]})
    r = store.entry(TID)
    assert made.made and r["intent"] and r["blocked"]["count"] == "review:refused" and r["stage"] == "review"


def test_a_refused_move_unwritten_goes_to_the_person(store):
    put(store, stage="plain")
    made, _ = go(store, {"verdict": "fail", "failed": ["ci"]})
    assert made.made and "refused" in store.entry(TID)["intent"]["ask"]


def test_a_moved_head_is_refused_without_running_the_gate(store):
    put(store)
    ran: list[int] = []
    s = Reading(pr_state="open", head="b" * 40)
    made = run(store, TID, MERGING, s, FLOW, "paul", lambda p, _h: ran.append(p), lambda _p, _h: None, NOW)
    assert made.made and not ran and store.entry(TID)["stage"] == "build"


@pytest.mark.parametrize("row", ["reach", "person"])
def test_a_row_only_a_person_can_cure_asks_with_try_again_and_spends_no_limit(store, row):
    put(store)
    made, landed = go(store, {"verdict": "fail", "failed": ["ci", row]})
    r = store.entry(TID)
    assert made.made and not landed and r["intent"]["answers"][TRY_AGAIN] == {"merge": True}
    assert not r.get("counts") and r["stage"] == "review" and r["merging"]["head"] == HEAD


def test_try_the_merge_again_marks_the_record_merging_at_its_head(store):
    put(store, waits="person", answers={TRY_AGAIN: {"merge": True}})
    r = store.entry(TID)
    r["merging"]["unread_since"] = "2026-11-23T10:00:00Z"
    store.put_entry(r, "test")
    s = Reading(gate=False, lifted=TRY_AGAIN, pr_state="open", head=HEAD)
    assert make(store, TID, Act("answer"), s, FLOW, "paul").made
    got = store.entry(TID)
    assert got["waits"] == "merging" and got["merging"] == {"head": HEAD, "stage": "review", "outcome": "ship"}


@pytest.mark.parametrize("got", [None, {"verdict": "unknown", "failed": []}])
def test_no_reading_stays_merging_and_goes_to_the_person_after_an_hour(store, got):
    put(store)
    made, _ = go(store, got)
    r = store.entry(TID)
    assert not made.made and r["waits"] == "merging" and r["merging"]["unread_since"] == "2026-11-23T12:00:00Z"
    made, _ = go(store, got, now=NOW + NO_READING_FOR - timedelta(seconds=1))
    assert not made.made and not store.entry(TID).get("intent")
    made, _ = go(store, got, now=NOW + NO_READING_FOR)
    r = store.entry(TID)
    assert made.made and r["intent"]["answers"][TRY_AGAIN] == {"merge": True} and not r.get("counts")


def test_a_gate_that_raises_is_no_reading(store):
    put(store)

    def boom(_p: int, _h: str) -> None:
        raise OSError("no gh")

    made = run(store, TID, MERGING, READ, FLOW, "paul", boom, lambda _p, _h: None, NOW)
    assert not made.made and "no gh" in made.why and store.entry(TID)["waits"] == "merging"


def test_a_merge_that_fails_stays_merging(store):
    put(store)
    made, _ = go(store, {"verdict": "pass", "failed": []}, land=lambda _p, _h: "conflict")
    assert not made.made and made.why == "conflict" and store.entry(TID)["merging"]["unread_since"]


def test_a_record_that_moved_during_the_gate_is_neither_merged_nor_written(store):
    put(store)
    landed: list[int] = []

    def gate(_p: int, _h: str) -> dict[str, Any]:
        r = store.entry(TID)
        r.update(waits=None, merging=None, stage="build")
        store.put_entry(r, "moved")
        return {"verdict": "pass", "failed": []}

    made = run(store, TID, MERGING, READ, FLOW, "paul", gate, lambda p, _h: landed.append(p), NOW)
    assert not made.made and not landed and store.entry(TID)["stage"] == "build"


def test_another_act_is_not_made(store):
    put(store)
    made, landed = None, []
    made = run(store, TID, Act("offer"), READ, FLOW, "paul", lambda _p, _h: None, lambda p, _h: landed.append(p), NOW)
    assert not made.made and not landed
