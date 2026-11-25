"""One entry's turn in the tick's pass (design §4.9c *The home acts only where no session will*, TD-2051), on a real
`shiftlead/state` branch in a scratch repo and its bare origin."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sessionorc.client import AgentError, AgentUnavailable
from sessionorc.models import Session
from shiftlead import stage_fetch, stage_pass, stage_size, stage_start
from shiftlead.stage_acts import Act
from shiftlead.stage_fetch import LedgerRead, RepoFacts, SessionsRead
from shiftlead.stage_make import Made
from shiftlead.stage_pass import Reach, Step, step
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
    team = SimpleNamespace(name="t")
    return stage_pass.reach_for(call, object(), team, {}, lambda *a: None, lambda *a: None, host="", here="h")


def test_a_start_creates_the_session_and_names_its_holder(monkeypatch: pytest.MonkeyPatch) -> None:
    call = Calls()
    assert reach(monkeypatch, call).start("build", Work("TD-7")) == "build-td-7"
    assert [m for m, _ in call.seen] == ["host", "name_check", "create"]


def test_a_start_on_a_node_names_the_holder_by_its_address(monkeypatch: pytest.MonkeyPatch) -> None:
    assert reach(monkeypatch, Calls(), host="n1").start("build", Work("TD-7")) == "build-td-7@n1"


def test_a_team_not_started_starts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    call = Calls()
    assert reach(monkeypatch, call, started=False).start("build", Work("TD-7")) is None
    assert [m for m, _ in call.seen] == ["host"]


def test_a_live_name_starts_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    call = Calls(verdict="live")
    assert reach(monkeypatch, call).start("build", Work("TD-7")) is None
    assert [m for m, _ in call.seen] == ["host", "name_check"]


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
    "error",
    [
        AgentError("a runs on n1: this call does not cross the link"),
        AgentUnavailable("down"),
        # an unreachable agent is a failure even worded as a local session already gone (TD-2138)
        AgentUnavailable("no session a"),
    ],
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
    assert got == stage_pass.TeamPass(seen=("a",), read=False) and world.ended == []


def test_the_flow_copy_is_stored_once_the_records_are_read(store, read_as_given):
    order: list[str] = []
    entries, put_flow = store.entries, store.put_flow
    store.entries = lambda: (order.append("read"), entries())[1]  # type: ignore[method-assign]
    store.put_flow = lambda team, text: (order.append("put"), put_flow(team, text))[1]  # type: ignore[method-assign]
    stage_pass.team_pass(store, repo_facts(store), no_sessions(), World().reach, local="h", put="name: f\n")
    assert order == ["read", "put"] and store.flow("t") == "name: f\n"


def test_a_stranded_session_never_holds_back_the_acts_on_an_open_record(store, read_as_given, monkeypatch):
    put(store, holder=None, waits="parts")
    monkeypatch.setattr(stage_pass, "facts_on", lambda _r, tid, _rec: facts(tid=tid, ledger=EntryLedger("archived")))
    world = World(end_fails=True)
    read = SessionsRead({"a": stage_session()}, frozenset(), frozenset())
    got = stage_pass.team_pass(store, repo_facts(store), read, world.reach, local="home", before=("a",))
    assert got.unended == ("a",) and [s.tid for s in got.steps] == [TID]
    assert store.entry(TID)["closed_at"]


@pytest.mark.parametrize("error", [StateError("refused"), ValueError("not a team name")])
def test_a_flow_copy_that_cannot_be_stored_steps_no_entry(store, read_as_given, monkeypatch, error):
    def refuse(_team: str, _text: str) -> str:
        raise error

    monkeypatch.setattr(store, "put_flow", refuse)
    got = stage_pass.team_pass(
        store, repo_facts(store, row()), no_sessions(), World().reach, local="h", put="name: f\n"
    )
    assert got.flow_unstored and got.steps == () and store.entry(TID) is None


def test_a_record_that_is_not_an_object_never_stops_the_pass(store, read_as_given, monkeypatch):
    monkeypatch.setattr(store, "entries", lambda: {"TD-9": ["not", "a", "record"]})
    monkeypatch.setattr(store, "put_entry", lambda *_a: "sha")
    got = stage_pass.team_pass(store, repo_facts(store), no_sessions(), World().reach, local="h")
    assert got == stage_pass.TeamPass()


# -- one repo's pass ---------------------------------------------------------------------------------------------


def test_a_session_here_is_found_by_the_homes_own_address_too() -> None:
    here, there = stage_session(), stage_session("build-td-8", ("TD-8",))
    read = SessionsRead({"a": here, "b@node": there}, frozenset({"node"}), frozenset({"a", "b@node"}))
    got = stage_pass.addressed(read, "home")
    assert got.sessions["a"] is here and got.sessions["a@home"] is here and got.sessions["b@node"] is there
    assert "b@node@home" not in got.sessions and got.read_nodes == {"node", "home"}
    assert got.open_asks == {"a", "a@home", "b@node"}


def flow_of(doc: dict[str, Any] = FLOW) -> stage_fetch.TeamFlow:
    return stage_fetch.TeamFlow(doc)


def made(store: StageStore, **over: Any) -> RepoFacts | None:
    asked: list[int] = over.pop("asked", [])
    args: dict[str, Any] = {
        "person": "paul",
        "team": "t",
        "now": NOW,
        "flow": flow_of(),
        "entries": [row()],
        "prs": {"open": [], "recent": []},
        "read_one": lambda n: (asked.append(n), None)[1],
        "records": {},
        "sessions": no_sessions(),
        "checkouts": {},
        "local": "home",
        "host_teams": {},
        "protected": [],
        **over,
    }
    return stage_pass.repo_facts(
        store.root, "origin/main", LedgerRead("docs/ledger", TEXT, None, lambda _p: None), **args
    )


def test_no_reading_of_the_pull_requests_is_no_reading_of_the_team(store):
    assert made(store, prs={"error": "gh failed"}) is None
    assert made(store, prs=None) is None


def test_the_facts_carry_the_flow_that_runs_and_the_one_its_records_were_written_under(store):
    was = {**FLOW, "name": "old"}
    got = made(store, flow=stage_fetch.TeamFlow(FLOW, was=was, put="x"))
    assert got is not None and got.doc == FLOW and got.was == was and got.entries == (row(),)


def test_an_open_records_pull_request_the_reading_lacks_is_read_by_its_number(store):
    asked: list[int] = []
    records = {"TD-1": {"pr": 5}, "TD-2": {"pr": 6, "closed_at": "2026-11-01"}, "TD-3": {"pr": None}, "TD-4": []}
    made(store, records=records, asked=asked)
    assert asked == [5]


@pytest.mark.parametrize(
    ("started", "host_teams", "may"),
    [
        (True, {}, True),
        (True, {"t": {"balance": {"crossed": True}}}, False),
        (True, {"other": {"balance": {"crossed": True}}}, True),
        (False, {}, False),
    ],
)
def test_a_team_over_its_line_may_not_start_a_session(store, started, host_teams, may):
    got = made(store, started=started, host_teams=host_teams, within_size=True)
    assert got is not None and got.may_start is may and got.within_size


def test_a_holder_written_in_the_homes_address_form_is_read_as_the_session_here(store):
    s = stage_session()
    repo = made(store, sessions=SessionsRead({"a": s}, frozenset(), frozenset({"a"})))
    assert repo is not None
    got = stage_fetch.facts_on(repo, TID, {**new_record(TID, "f", "build", team="t"), "holder": "a@home"})
    assert got is not None and got.session is s and got.open_ask


def test_held_is_unknown_while_a_node_with_a_checkout_of_the_repo_is_unread(store):
    pr = {"number": 4, "state": "open", "branch": "build-td-7"}
    unknown = made(store, prs={"open": [pr], "recent": []}, checkouts={"node": ["/r"]})
    assert unknown is not None and unknown.held is None
    known = made(store, prs={"open": [pr], "recent": []}, checkouts={"home": ["/r"]})
    assert known is not None and known.held == frozenset()


class Teams:
    """A `FactsFor` that records the flows it was given, and a `Reach` per team."""

    def __init__(self, store: StageStore, *, none_for: tuple[str, ...] = ()) -> None:
        self.store, self.none_for = store, none_for
        self.flows: dict[str, stage_fetch.TeamFlow] = {}
        self.reached: dict[str, Any] = {}
        self.world = World()

    def facts(self, team: str, flow: stage_fetch.TeamFlow, _records: Any) -> RepoFacts | None:
        self.flows[team] = flow
        return None if team in self.none_for else replace(repo_facts(self.store), team=team, doc=flow.doc)

    def reach(self, team: str, doc: Any) -> Reach:
        self.reached[team] = doc
        return self.world.reach


GOOD = "format: 3\nname: f\nstages:\n- {name: build, does: build, model: m, takes: any}\n"


def test_a_failing_flow_runs_its_last_good_copy_and_is_told_once(store, read_as_given):
    store.put_flow("t", GOOD)
    state, teams = stage_pass.RepoState(), Teams(store)
    first = stage_pass.repo_pass(
        store, state, {"t": ("bad", ["no stages"])}, teams.facts, no_sessions(), teams.reach, local="h"
    )
    assert first.tell == {"t": ("no stages",)} and teams.flows["t"].doc["name"] == "f" and "t" in first.teams
    assert teams.reached["t"]["name"] == "f", "a session starts from the last good copy, never the failing flow"
    again = stage_pass.repo_pass(
        store, state, {"t": ("bad", ["no stages"])}, teams.facts, no_sessions(), teams.reach, local="h"
    )
    assert again.tell == {}
    other = stage_pass.repo_pass(
        store, state, {"t": ("bad", ["a loop"])}, teams.facts, no_sessions(), teams.reach, local="h"
    )
    assert other.tell == {"t": ("a loop",)}
    stage_pass.repo_pass(store, state, {"t": (GOOD, [])}, teams.facts, no_sessions(), teams.reach, local="h")
    assert state.told == {}
    back = stage_pass.repo_pass(
        store, state, {"t": ("bad", ["a loop"])}, teams.facts, no_sessions(), teams.reach, local="h"
    )
    assert back.tell == {"t": ("a loop",)}


def test_a_flow_that_fails_with_no_good_copy_is_told_and_its_team_unread(store):
    state, teams = stage_pass.RepoState(), Teams(store)
    got = stage_pass.repo_pass(store, state, {"t": (None, [])}, teams.facts, no_sessions(), teams.reach, local="h")
    assert got.unread == ("t",) and got.tell == {"t": ("the flow could not be read",)} and teams.flows == {}


def test_a_passing_flow_replaces_the_copy_after_the_pass_reads_the_records(store, read_as_given):
    state, teams = stage_pass.RepoState(), Teams(store)
    stage_pass.repo_pass(store, state, {"t": (GOOD, [])}, teams.facts, no_sessions(), teams.reach, local="h")
    assert store.flow("t") == GOOD and teams.flows["t"].put == GOOD


def test_a_team_with_no_facts_is_unread_and_the_others_go_on(store, read_as_given):
    state, teams = stage_pass.RepoState(), Teams(store, none_for=("a",))
    flows = {"a": (GOOD, []), "b": (GOOD, [])}
    got = stage_pass.repo_pass(store, state, flows, teams.facts, no_sessions(), teams.reach, local="h")
    assert got.unread == ("a",) and list(got.teams) == ["b"]


def test_each_teams_sightings_are_kept_for_its_next_pass_and_a_gone_team_forgotten(store, read_as_given):
    read = SessionsRead({"a": stage_session()}, frozenset(), frozenset())
    state, teams = stage_pass.RepoState(told={"gone": ("x",)}, seen={"gone": ("z",)}), Teams(store)
    stage_pass.repo_pass(store, state, {"t": (GOOD, [])}, teams.facts, read, teams.reach, local="home")
    assert state.seen == {"t": ("a",)} and state.told == {} and teams.world.ended == []
    stage_pass.repo_pass(store, state, {"t": (GOOD, [])}, teams.facts, read, teams.reach, local="home")
    assert teams.world.ended == ["a"]


def test_the_closed_records_are_swept_once_for_the_repo(store, monkeypatch):
    calls: list[Any] = []
    monkeypatch.setattr(stage_pass.stage_make, "sweep_closed", lambda s, now: (calls.append(now), ["TD-1"])[1])
    teams = Teams(store)
    flows = {"a": (None, []), "b": (None, [])}
    got = stage_pass.repo_pass(
        store, stage_pass.RepoState(), flows, teams.facts, no_sessions(), teams.reach, local="h", now=NOW
    )
    assert calls == [NOW] and got.swept == ("TD-1",)


def test_a_sweep_that_fails_never_fails_the_pass(store, monkeypatch):
    def refuse(_s: Any, _now: Any) -> list[str]:
        raise TypeError("a closed date that is not a string")

    monkeypatch.setattr(stage_pass.stage_make, "sweep_closed", refuse)
    teams = Teams(store)
    got = stage_pass.repo_pass(store, stage_pass.RepoState(), {}, teams.facts, no_sessions(), teams.reach, local="h")
    assert got == stage_pass.RepoPass()


@pytest.mark.parametrize("where", ["facts", "reach"])
def test_one_teams_failure_never_stops_the_other_teams_or_the_sweep(store, read_as_given, monkeypatch, where):
    swept: list[Any] = []
    monkeypatch.setattr(stage_pass.stage_make, "sweep_closed", lambda _s, now: (swept.append(now), [])[1])
    teams = Teams(store)

    def facts(team: str, flow: stage_fetch.TeamFlow, records: Any) -> RepoFacts | None:
        if where == "facts" and team == "a":
            raise RuntimeError("the forge did not answer")
        return teams.facts(team, flow, records)

    def reach(team: str, _doc: Any) -> Reach:
        if where == "reach" and team == "a":
            raise KeyError(team)
        return teams.reach(team, _doc)

    state = stage_pass.RepoState()
    flows = {"a": ("bad", ["no stages"]), "b": (GOOD, [])}
    store.put_flow("a", GOOD)
    got = stage_pass.repo_pass(store, state, flows, facts, no_sessions(), reach, local="h")
    assert got.unread == ("a",) and list(got.teams) == ["b"] and swept == [None]
    assert got.tell == {"a": ("no stages",)}


def test_records_that_cannot_be_read_read_no_pull_request_by_number(store, read_as_given, monkeypatch):
    def broken() -> dict[str, Any]:
        raise TypeError("not a mapping")

    given: list[Any] = []
    teams = Teams(store)
    monkeypatch.setattr(store, "entries", broken)
    monkeypatch.setattr(stage_pass.stage_make, "sweep_closed", lambda _s, _n: [])
    stage_pass.repo_pass(
        store,
        stage_pass.RepoState(),
        {"t": (GOOD, [])},
        lambda t, f, r: (given.append(r), None)[1],
        no_sessions(),
        teams.reach,
        local="h",
    )
    assert given == [{}]


def test_a_refusal_stands_after_three_passes_over_ten_minutes_and_is_told_once() -> None:
    """TD-2051 (§4.9c *A refusal that stands*): the same act refused for the same reason on three passes running, the
    first at least ten minutes before the last, is told once; a pass with no reading neither counts nor ends it."""
    from datetime import timedelta

    state = stage_pass.RepoState()
    no = Step("TD-7", act=Act("reconcile", "merged"), made=Made(False, "the ledger refused"))
    at = [NOW + timedelta(minutes=m) for m in (0, 4, 8, 12, 13)]
    got = [stage_pass.note_refusals(state, "t", [no], a) for a in at[:3]]
    assert got == [[], [], []], "three passes, but only eight minutes"
    assert stage_pass.note_refusals(state, "t", [Step("TD-7", read=False)], at[3]) == []
    [told] = stage_pass.note_refusals(state, "t", [no], at[3])
    assert (told.tid, told.team, told.act, told.why, told.since) == (
        "TD-7",
        "t",
        "reconcile (merged)",
        "the ledger refused",
        NOW,
    )
    assert stage_pass.note_refusals(state, "t", [no], at[4]) == [], "told once"


def test_a_made_act_another_reason_or_an_entry_not_turned_to_ends_the_spell() -> None:
    from datetime import timedelta

    state = stage_pass.RepoState()
    no = Step("TD-7", act=Act("answer"), made=Made(False, "x"))
    later = [NOW + timedelta(minutes=10 * i) for i in range(12)]
    for a in later[:2]:
        stage_pass.note_refusals(state, "t", [no], a)
    stage_pass.note_refusals(state, "t", [Step("TD-7", act=Act("answer"), made=Made(True))], later[2])
    assert ("t", "TD-7") not in state.spells
    for a in later[3:5]:
        stage_pass.note_refusals(state, "t", [no], a)
    stage_pass.note_refusals(state, "t", [Step("TD-7", act=Act("answer"), made=Made(False, "y"))], later[5])
    assert state.spells[("t", "TD-7")].why == "y" and state.spells[("t", "TD-7")].passes == 1, (
        "another reason starts a spell anew"
    )
    stage_pass.note_refusals(state, "t", [], later[6])
    assert state.spells == {}, "an entry the pass did not turn to"
    stage_pass.note_refusals(state, "t", [no], later[7])
    stage_pass.note_refusals(state, "u", [], later[7])
    assert ("t", "TD-7") in state.spells, "another team's pass leaves this team's spells alone"


def test_a_team_pass_with_no_reading_keeps_its_refusal_runs(store, read_as_given, monkeypatch):
    """A team whose records could not be read this pass has no reading of any entry, so its runs stand."""
    from datetime import timedelta

    state, teams = stage_pass.RepoState(), Teams(store)
    no = Step("TD-7", act=Act("answer"), made=Made(False, "x"))
    stage_pass.note_refusals(state, "t", [no], NOW)
    monkeypatch.setattr(stage_pass, "team_pass", lambda *a, **k: stage_pass.TeamPass(read=False))
    got = stage_pass.repo_pass(store, state, {"t": (GOOD, [])}, teams.facts, no_sessions(), teams.reach, local="h")
    assert got.refused == () and state.spells[("t", "TD-7")].passes == 1
    for m in (5, 11):
        stage_pass.note_refusals(state, "t", [no], NOW + timedelta(minutes=m))
    assert state.spells[("t", "TD-7")].told
    gone = stage_pass.repo_pass(store, state, {"u": (GOOD, [])}, teams.facts, no_sessions(), teams.reach, local="h")
    assert gone.refused == () and state.spells == {}, "a team gone from the repo's flows takes its runs with it"


# -- the team's numbers (TD-2065, §4.9d *Sessions at once*) ---------------------------------------------------------


def limited(store: StageStore, limits: stage_size.Limits, *entries: dict[str, Any]) -> RepoFacts:
    return replace(repo_facts(store, *entries), limits=limits)


def as_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each entry's facts may start a session and read as outside the team's size, so only the room lets one in."""
    monkeypatch.setattr(stage_pass, "facts_on", lambda _repo, tid, _record: replace(offerable(tid), within_size=False))


def test_a_stage_never_holds_more_sessions_than_its_number(store, monkeypatch):
    as_offered(monkeypatch)
    world = World()
    rows = (row("TD-1"), row("TD-2"), row("TD-3"))
    got = stage_pass.team_pass(
        store, limited(store, stage_size.Limits({"build": 2}), *rows), no_sessions(), world.reach, local="home"
    )
    assert [(s.tid, s.act.name if s.act else None) for s in got.steps] == [
        ("TD-1", "offer"),
        ("TD-2", "offer"),
        ("TD-3", None),
    ]
    again = stage_pass.team_pass(
        store, limited(store, stage_size.Limits({"build": 2}), *rows), no_sessions(), world.reach, local="home"
    )
    assert all(s.act is None or s.act.name != "offer" for s in again.steps)


def test_a_stage_with_no_number_runs_one_and_a_held_record_counts(store, monkeypatch):
    as_offered(monkeypatch)
    put(store, holder="s1")  # TD-7 held in build
    world = World()
    got = stage_pass.team_pass(
        store, limited(store, stage_size.Limits(), row("TD-1")), no_sessions(), world.reach, local="home"
    )
    assert [s.act for s in got.steps if s.tid == "TD-1"] == [None]
    assert store.entry("TD-1") is None


def test_the_team_limit_counts_its_audits_and_holds_back_a_stage_with_room(store, monkeypatch):
    as_offered(monkeypatch)
    store.put_audit("t", "docs", {"holder": "a1", "base": "b0"})
    doc = {**FLOW, "audits": [{"name": "docs", "model": "m", "every": "6 hours"}]}
    world = World()
    facts_ = replace(limited(store, stage_size.Limits({"build": 3}, 2), row("TD-1"), row("TD-2")), doc=doc)
    got = stage_pass.team_pass(store, facts_, no_sessions(), world.reach, local="home")
    assert [(s.tid, s.act.name if s.act else None) for s in got.steps] == [("TD-1", "offer"), ("TD-2", None)]


def test_an_offer_that_fails_takes_no_room(store, monkeypatch):
    as_offered(monkeypatch)
    world = World(started=None)
    got = stage_pass.team_pass(
        store, limited(store, stage_size.Limits(), row("TD-1"), row("TD-2")), no_sessions(), world.reach, local="home"
    )
    assert [s.act.name for s in got.steps] == ["offer", "offer"] and not any(s.made.made for s in got.steps)


def test_without_numbers_the_reading_s_own_within_size_stands(store, monkeypatch):
    as_offered(monkeypatch)
    got = stage_pass.team_pass(store, repo_facts(store, row("TD-1")), no_sessions(), World().reach, local="home")
    assert [s.act for s in got.steps] == [None]
