"""One entry's turn in the tick's pass (design §4.9c *The home acts only where no session will*, TD-2051), on a real
`shiftlead/state` branch in a scratch repo and its bare origin."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from shiftlead.stage_pass import Reach, step
from shiftlead.stage_read import EntryFacts, EntryLedger
from shiftlead.stagerecord import StageStore, new_record

TID = "TD-7"
HEAD = "a" * 40
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
TEXT = "## TD-7: An entry\n\n**Priority:** Low\n**Status:** Open\n\n**Why:** It matters.\n"
FLOW: dict[str, Any] = {
    "format": 3,
    "name": "f",
    "stages": [
        {"name": "build", "does": "build", "model": "m", "takes": "any", "work-pushed": "review"},
        {"name": "review", "does": "review", "model": "m", "ship": "merge"},
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


def facts(**over: Any) -> EntryFacts:
    base: dict[str, Any] = {
        "tid": TID,
        "person": "paul",
        "team": "t",
        "now": NOW,
        "doc": FLOW,
        "ledger": EntryLedger("open"),
        "text": TEXT,
    }
    return EntryFacts(**{**base, **over})


class World:
    """A `Reach` that records what was called."""

    def __init__(self, *, started: str | None = "s2", refused: str | None = None, end_fails: bool = False) -> None:
        self.started, self.refused, self.end_fails = started, refused, end_fails
        self.gates: list[tuple[int, str]] = []
        self.landed: list[tuple[int, str]] = []
        self.ended: list[str] = []
        self.reach = Reach(self.gate, self.land, self.start, self.claim, self.end)

    def gate(self, pr: int, head: str) -> dict[str, Any]:
        self.gates.append((pr, head))
        return {"verdict": "pass", "failed": []}

    def land(self, pr: int, head: str) -> None:
        self.landed.append((pr, head))

    def start(self, _key: str, _work: Any) -> str | None:
        return self.started

    def claim(self, _holder: str, _tid: str) -> str | None:
        return self.refused

    def end(self, sid: str) -> None:
        if self.end_fails:
            raise OSError("no such session")
        self.ended.append(sid)


def put(store: StageStore, **over: Any) -> dict[str, Any]:
    record = {**new_record(TID, "f", "build", team="t"), **over}
    store.put_entry(record, "test")
    return record


def test_no_reading_of_the_entry_takes_no_act(store):
    world = World()
    got = step(store, put(store, holder="s1"), facts(ledger=None), world.reach)
    assert (got.read, got.act, got.made) == (False, None, None)
    assert store.entry(TID)["holder"] == "s1"


def test_a_record_with_nothing_to_do_takes_no_act(store):
    world = World()
    got = step(store, put(store, holder=None, waits="parts"), facts(), world.reach)
    assert got.read and got.act is None and got.made is None


def test_a_write_that_takes_the_record_from_its_holder_ends_that_session(store):
    world = World()
    got = step(store, put(store, holder="s1"), facts(ledger=EntryLedger("archived")), world.reach)
    assert got.made.made and got.unended is None
    assert world.ended == ["s1"]
    assert store.entry(TID)["closed_at"]


def test_a_session_that_cannot_be_ended_is_reported_and_the_write_stands(store):
    world = World(end_fails=True)
    got = step(store, put(store, holder="s1"), facts(ledger=EntryLedger("archived")), world.reach)
    assert got.made.made and got.unended == "s1"
    assert store.entry(TID)["closed_at"]


def test_a_record_with_no_holder_is_offered_through_the_start_and_the_claim(store):
    world = World()
    got = step(store, put(store, holder=None), facts(may_start=True, within_size=True), world.reach)
    assert got.act.name == "offer" and got.made.made
    assert store.entry(TID)["holder"] == "s2"
    assert world.ended == []


def test_an_offer_whose_claim_is_refused_ends_the_session_it_started(store):
    world = World(refused="over its line")
    got = step(store, put(store, holder=None), facts(may_start=True, within_size=True), world.reach)
    assert not got.made.made and "over its line" in got.made.why
    assert world.ended == ["s2"]
    assert store.entry(TID)["holder"] is None


def test_a_record_marked_merging_runs_the_gate_and_the_merge(store):
    world = World()
    record = put(
        store,
        stage="review",
        holder=None,
        pr=7,
        waits="merging",
        merging={"head": HEAD, "stage": "review", "outcome": "ship"},
    )
    rows = ({"number": 7, "state": "open", "head": HEAD},)
    got = step(store, record, facts(rows=rows), world.reach)
    assert got.act.case == "merging" and got.made.made
    assert world.gates == [(7, HEAD)] and world.landed == [(7, HEAD)]


def test_an_act_that_raises_is_that_entrys_failure_and_never_the_pass(store, monkeypatch):
    world = World()
    record = put(store, holder="s1")

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("the disk is full")

    monkeypatch.setattr(store, "put_entry", boom)
    got = step(store, record, facts(ledger=EntryLedger("archived")), world.reach)
    assert not got.made.made and "the disk is full" in got.made.why
    assert world.ended == []
