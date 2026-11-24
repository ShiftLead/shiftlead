"""One entry's turn in the tick's pass (design §4.9c *The home acts only where no session will*, TD-2051), on a real
`shiftlead/state` branch in a scratch repo and its bare origin."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sessionorc.client import AgentError, AgentUnavailable
from sessionorc.models import Session
from shiftlead import stage_pass, stage_start
from shiftlead.stage_fetch import LedgerRead, RepoFacts, SessionsRead
from shiftlead.stage_pass import Reach, step
from shiftlead.stage_read import EntryFacts, EntryLedger
from shiftlead.stage_start import Work
from shiftlead.stagerecord import StageStore, StateError, new_record

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


def test_an_entry_with_no_record_is_offered_and_its_record_written(store):
    world = World()
    entry = {"id": TID, "kind": "build", "owner": "grinder", "pickable": "yes", "team": ""}
    got = step(store, None, facts(entry=entry, may_start=True, within_size=True), world.reach)
    assert got.act.name == "offer" and got.made.made
    assert (store.entry(TID)["holder"], store.entry(TID)["stage"]) == ("s2", "build")


def test_a_lost_holder_is_ended_and_its_offer_counted(store):
    world = World()
    got = step(store, put(store, holder="s1", offers=1), facts(may_start=True, within_size=True), world.reach)
    assert (got.act.name, got.act.case) == ("offer-again", "lost") and got.made.made
    assert world.ended == ["s1"]
    assert (store.entry(TID)["holder"], store.entry(TID)["offers"]) == (None, 2)


def test_a_record_that_moved_since_its_reading_ends_no_session(store):
    world = World()
    stale = put(store, holder="s1")
    store.put_entry({**stale, "holder": None, "closed_at": "2026-11-23T11:00:00Z"}, "closed meanwhile")
    got = step(store, stale, facts(ledger=EntryLedger("archived")), world.reach)
    assert got.act.case == "close" and not got.made.made
    assert world.ended == []


class Calls:
    def __init__(self, fail: Exception | None = None, verdict: str = "free") -> None:
        self.fail, self.verdict, self.seen = fail, verdict, []

    def __call__(self, method: str, **kw: Any) -> dict[str, Any]:
        self.seen.append((method, kw))
        if self.fail is not None:
            raise self.fail
        return {"verdict": self.verdict} if method == "name_check" else {"id": "build-td-7"}


def launched(host: str = "") -> stage_start.StageLaunch:
    x = SimpleNamespace(host=host, dir="/r", name="build-td-7")
    got = SimpleNamespace(launch=x, create_params=lambda controllers: {"name": x.name, "controllers": controllers})
    return got  # type: ignore[return-value]


def reach(monkeypatch: pytest.MonkeyPatch, call: Calls, *, started: bool = True, host: str = "") -> stage_pass.Reach:
    monkeypatch.setattr(stage_start, "launch", lambda *a, **k: launched(host))
    monkeypatch.setattr(stage_start, "team_started", lambda *a: started)
    return stage_pass.reach_for(call, object(), object(), {}, lambda *a: None, lambda *a: None, host="", here="h")


def test_a_start_creates_the_session_and_names_its_holder(monkeypatch: pytest.MonkeyPatch) -> None:
    call = Calls()
    assert reach(monkeypatch, call).start("build", Work("TD-7")) == "build-td-7"
    assert [m for m, _ in call.seen] == ["name_check", "create"]


def test_a_start_on_a_node_names_the_holder_by_its_address(monkeypatch: pytest.MonkeyPatch) -> None:
    assert reach(monkeypatch, Calls(), host="n1").start("build", Work("TD-7")) == "build-td-7@n1"


def test_a_team_not_started_starts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    call = Calls()
    assert reach(monkeypatch, call, started=False).start("build", Work("TD-7")) is None
    assert call.seen == []


def test_a_live_name_starts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    call = Calls(verdict="live")
    assert reach(monkeypatch, call).start("build", Work("TD-7")) is None
    assert [m for m, _ in call.seen] == ["name_check"]


def test_a_claim_is_written_on_the_holder_and_a_refusal_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    call = Calls()
    assert reach(monkeypatch, call).claim("a", "TD-7") is None
    assert call.seen == [("progress", {"id": "a", "ref": "TD-7", "status": "claimed"})]
    assert reach(monkeypatch, Calls(AgentError("over its line"))).claim("a", "TD-7") == "over its line"


def test_an_end_closes_the_session_as_the_tick() -> None:
    call = Calls()
    stage_start.end(call, "a@n1", "why")
    assert call.seen == [("close", {"id": "a@n1", "closer": {"by": "tick", "why": "why"}})]


def test_an_end_of_a_session_already_gone_is_no_failure() -> None:
    stage_start.end(Calls(AgentError("no session a")), "a")


@pytest.mark.parametrize(
    "error", [AgentError("a runs on n1: this call does not cross the link"), AgentUnavailable("down")]
)
def test_an_end_that_could_not_reach_the_session_is_a_failure(error: AgentError) -> None:
    with pytest.raises(AgentError):
        stage_start.end(Calls(error), "a")


@pytest.mark.parametrize(
    ("holder", "words"),
    [("a@n1", "no session a@n1"), ("a@n1", "n1: no session a"), ("a@home", "no session a@home")],
)
def test_a_no_session_for_a_node_address_does_not_prove_it_gone(holder: str, words: str) -> None:
    with pytest.raises(AgentError):
        stage_start.end(Calls(AgentError(words)), holder)


def test_the_reach_ends_a_session_through_the_close(monkeypatch: pytest.MonkeyPatch) -> None:
    call = Calls()
    reach(monkeypatch, call).end("a")
    assert [m for m, _ in call.seen] == ["close"]


# -- one team's pass -----------------------------------------------------------------------------------------


def row(tid: str = TID, **over: Any) -> dict[str, Any]:
    return {"id": tid, "kind": "build", "pickable": "yes", **over}


def stage_session(name: str = "build-td-7", lane: tuple[str, ...] = (TID,)) -> Session:
    s = Session(id="a", name=name, dir="/r", kind="agent", adapter="claude-code", state="working")
    s.team, s.lane, s.unattended = "t", list(lane), True
    return s


def repo_facts(store: StageStore, *entries: dict[str, Any]) -> RepoFacts:
    return RepoFacts(
        root=store.root,
        ref="origin/main",
        read=LedgerRead("docs/ledger", "", None, lambda _path: None),
        person="paul",
        team="t",
        now=NOW,
        doc=FLOW,
        entries=entries,
        sessions={},
    )


def offerable(tid: str) -> EntryFacts:
    text = TEXT.replace(TID, tid)
    return facts(tid=tid, text=text, entry=row(tid), may_start=True, within_size=True)


def no_sessions() -> SessionsRead:
    return SessionsRead({}, frozenset(), frozenset())


@pytest.fixture
def read_as_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each entry's facts without a ledger on disk: the pass's own order is what these tests read."""
    monkeypatch.setattr(stage_pass, "facts_on", lambda _repo, tid, _record: offerable(tid))


def test_a_pass_turns_to_its_open_records_then_what_its_lane_may_take() -> None:
    records = {
        "TD-1": {"team": "t"},
        "TD-2": {"team": "other"},
        "TD-3": {"team": "t", "closed_at": "2026-11-01"},
        "TD-4": {"team": "other"},
    }
    entries = [row("TD-3"), row("TD-4"), row("TD-5"), row("TD-6", pickable="no"), row("board:x")]
    assert stage_pass.targets(records, entries, "t") == ["TD-1", "TD-3", "TD-5"]


def test_a_reopened_entry_is_turned_to_under_its_records_own_key() -> None:
    assert stage_pass.targets({"TD-007": {"team": "t", "closed_at": "x"}}, [row("TD-7")], "t") == ["TD-007"]


def test_a_pickable_entry_with_no_record_is_offered(store, read_as_given):
    world = World()
    got = stage_pass.team_pass(store, repo_facts(store, row()), no_sessions(), world.reach, local="home")
    assert [s.act.name for s in got.steps] == ["offer"]
    assert store.entry(TID)["holder"] == "s2"


def test_a_stranded_session_is_ended_on_its_second_pass_and_its_entry_waits(store, read_as_given):
    world = World()
    read = SessionsRead({"a": stage_session()}, frozenset(), frozenset())
    first = stage_pass.team_pass(store, repo_facts(store, row()), read, world.reach, local="home")
    assert (first.seen, first.steps, world.ended) == (("a",), (), [])
    second = stage_pass.team_pass(store, repo_facts(store, row()), read, world.reach, local="home", before=first.seen)
    assert world.ended == ["a"] and second.steps == () and store.entry(TID) is None


def test_a_stranded_session_that_cannot_be_ended_is_tried_again(store, read_as_given):
    world = World(end_fails=True)
    read = SessionsRead({"a": stage_session()}, frozenset(), frozenset())
    got = stage_pass.team_pass(store, repo_facts(store), read, world.reach, local="home", before=("a",))
    assert got.unended == ("a",) and got.seen == ("a",)


def test_one_entrys_failed_read_never_stops_the_pass(store, monkeypatch):
    def read(_repo: Any, tid: str, _record: Any) -> EntryFacts:
        if tid == "TD-1":
            raise OSError("the ledger could not be read")
        return offerable(tid)

    monkeypatch.setattr(stage_pass, "facts_on", read)
    world = World()
    repo = repo_facts(store, row("TD-1"), row("TD-2"))
    got = stage_pass.team_pass(store, repo, no_sessions(), world.reach, local="h")
    assert [(s.tid, s.read) for s in got.steps] == [("TD-1", False), ("TD-2", True)]
    assert store.entry("TD-2")["holder"] == "s2"


def test_unreadable_records_take_no_act_and_keep_the_last_passs_sightings(store, monkeypatch):
    def broken() -> dict[str, Any]:
        raise StateError("origin did not answer")

    monkeypatch.setattr(store, "entries", broken)
    world = World()
    got = stage_pass.team_pass(store, repo_facts(store, row()), no_sessions(), world.reach, local="h", before=("a",))
    assert got == stage_pass.TeamPass(seen=("a",)) and world.ended == []


def test_the_flow_copy_is_stored_once_the_records_are_read(store, read_as_given):
    order: list[str] = []
    entries, put_flow = store.entries, store.put_flow
    store.entries = lambda: (order.append("read"), entries())[1]  # type: ignore[method-assign]
    store.put_flow = lambda team, text: (order.append("put"), put_flow(team, text))[1]  # type: ignore[method-assign]
    stage_pass.team_pass(store, repo_facts(store), no_sessions(), World().reach, local="h", put="name: f\n")
    assert order == ["read", "put"] and store.flow("t") == "name: f\n"
