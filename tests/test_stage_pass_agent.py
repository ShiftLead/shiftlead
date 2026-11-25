"""The host agent's half of the stage pass (design §4.9c *The home acts only where no session will*, TD-2051): the
home starts one detached pass a minute after the cut-over, hands each repo with switched teams to
`shiftlead.stage_tick` in a thread of its own with what only it holds, and tells the person once of a failing flow."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest

from sessionorc import agent_stage, hosts
from sessionorc.agent_stage import STAGE_EVERY, StageMixin, refused_words, rested_words, stage_teams, told
from sessionorc.client import AgentError

pytestmark = pytest.mark.unit


def settings_doc() -> dict[str, Any]:
    return {
        "cut_over": "2026-12-01",
        "teams": {
            "build-r": {"repo": "r", "host": "here", "flow": "build"},
            "other-r": {"repo": "r", "host": "here", "flow": "build"},
            "s-team": {"repo": "s", "host": "here", "flow": "build"},
            "old-shape": {"flow": "build", "on_work": "free-pick"},  # no repo: not switched
        },
    }


def test_switched_teams_are_grouped_by_their_repos_name() -> None:
    got = stage_teams(settings_doc())
    assert sorted(got) == ["r", "s"] and sorted(got["r"]) == ["build-r", "other-r"]
    assert "old-shape" not in {t for teams in got.values() for t in teams}
    assert stage_teams({}) == {} and stage_teams({"teams": "nonsense"}) == {}


def test_the_person_is_told_the_flows_problems() -> None:
    text = told("t", ("stage x has no reader",))
    assert text.startswith("Team t's flow stopped passing its check") and "- stage x has no reader" in text


class _Agent(StageMixin):
    """The home: a registry of `/c/r` and `/c/s`, readings for `/c/r` only, a node `n` whose roster is `roster`."""

    host = "here"

    def __init__(self, roster: list[str] | None = None) -> None:
        self.mode = "home"
        self._first_shape_off = True
        self._repos = {"/c/r": {"ledger": {"entries": [{"id": "TD-7"}]}, "prs": {"open": [], "recent": []}}}
        self._intent_sent: dict[str, dict] = {"n": {}}
        self._host_rec = {"teams": {"build-r": {"balance": {"crossed": False}}}}
        self.remote: dict[str, dict] = {"n": {}}
        self.roster = roster if roster is not None else []
        self.notes: list[tuple[str, str, str | None]] = []
        self.dispatched: list[dict] = []
        self.answer: dict[str, Any] = {"result": {"ok": True}}
        self.sessions: dict[str, Any] = {}

    def _graph(self) -> dict[str, Any]:
        return {
            "w1": SimpleNamespace(repo="/c/r", outbox=[]),
            "w2@n": SimpleNamespace(repo="/n/r", outbox=[]),
            "w3@n": SimpleNamespace(repo="/n/q", outbox=[]),
        }

    async def _host_roster(self, host: str) -> list[str]:
        return list(self.roster)

    def _system_note(self, to: str, text: str, *, team: str | None = None) -> None:
        self.notes.append((to, text, team))

    async def _dispatch_inner(self, req: dict[str, Any]) -> dict[str, Any]:
        self.dispatched.append(req)
        return {"id": req["id"], **self.answer}


@pytest.fixture
def body(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """`stage_tick` as a module that records each repo's arguments and tells of team `build-r` once."""
    calls: list[dict[str, Any]] = []

    def call(**kw: Any) -> Any:
        calls.append(kw)
        return SimpleNamespace(tell={"build-r": ("flow build is not found",)})

    module = SimpleNamespace(call=call, Kept=lambda: SimpleNamespace(kept=True))
    monkeypatch.setattr(agent_stage, "home_call", lambda name: module if name == "stage_tick" else pytest.fail(name))
    monkeypatch.setattr(agent_stage.settings_mod, "read", settings_doc)
    monkeypatch.setattr(hosts, "local_host", lambda: SimpleNamespace(repos=lambda: ["/c/r", "/c/s"]))
    monkeypatch.setattr(hosts, "nodes", lambda: {"n": {}})
    return calls


def test_a_repo_read_is_passed_with_what_only_the_home_holds(body: list[dict[str, Any]]) -> None:
    agent = _Agent(roster=["/n/r", "/n/q"])
    asyncio.run(agent._stage_pass())
    assert [c["root"] for c in body] == ["/c/r"], "a repo the home has not read yet waits for its reading"
    got = body[0]
    assert sorted(got["teams"]) == ["build-r", "other-r"]
    assert got["entries"] == [{"id": "TD-7"}] and got["prs"] == {"open": [], "recent": []}
    assert got["entries"] is not agent._repos["/c/r"]["ledger"]["entries"], "the thread gets copies"
    assert got["snapshotted"] == frozenset({"n"}) and got["local"] == "here"
    assert got["checkouts"] == {"here": ["/c/r"], "n": ["/n/r"]}
    assert got["host_teams"] == agent._host_rec["teams"] and got["host_teams"] is not agent._host_rec["teams"]
    assert set(got["graph"]) == {"w1", "w2@n", "w3@n"}
    kept = got["kept"]
    asyncio.run(agent._stage_pass())
    assert body[1]["kept"] is kept, "one Kept per repo, held between passes"
    assert agent.notes == [("person", told("build-r", ("flow build is not found",)), "build-r")] * 2


def test_a_node_whose_roster_gave_nothing_is_named_with_its_sessions_repos(body: list[dict[str, Any]]) -> None:
    asyncio.run(_Agent(roster=[])._stage_pass())
    assert body[0]["checkouts"]["n"] == ["/n/r"]


def test_a_node_with_no_checkout_of_the_repo_is_left_out(body: list[dict[str, Any]]) -> None:
    agent = _Agent(roster=["/n/q"])
    agent._graph = lambda: {"w3@n": SimpleNamespace(repo="/n/q", outbox=[])}  # type: ignore[method-assign]
    asyncio.run(agent._stage_pass())
    assert body[0]["checkouts"] == {"here": ["/c/r"]}


def test_one_repos_failure_never_stops_the_pass(monkeypatch: pytest.MonkeyPatch, body: list[dict[str, Any]]) -> None:
    agent = _Agent()
    agent._repos["/c/s"] = agent._repos["/c/r"]
    seen: list[str] = []

    def call(**kw: Any) -> Any:
        seen.append(kw["root"])
        if kw["root"] == "/c/r":
            raise RuntimeError("boom")
        return None

    monkeypatch.setattr(agent_stage, "home_call", lambda _name: SimpleNamespace(call=call, Kept=object))
    asyncio.run(agent._stage_pass())
    assert sorted(seen) == ["/c/r", "/c/s"] and agent.notes == []


def test_the_pass_starts_only_at_the_home_after_the_cut_over_once_a_minute() -> None:
    async def go() -> None:
        agent = _Agent()
        ran: list[int] = []

        async def stage_pass() -> None:
            ran.append(1)

        agent._stage_pass = stage_pass  # type: ignore[method-assign]
        agent._first_shape_off = False
        agent._stage_due()
        agent.mode, agent._first_shape_off = "node", True
        agent._stage_due()
        assert agent._stage_task is None
        agent.mode = "home"
        agent._stage_due()
        await agent._stage_task
        agent._stage_due()
        assert ran == [1], "not again within the minute"
        agent._stage_at = time.monotonic() - STAGE_EVERY
        agent._stage_due()
        await agent._stage_task
        assert ran == [1, 1]

    asyncio.run(go())


def test_a_pass_still_running_is_never_joined_by_a_second() -> None:
    async def go() -> None:
        agent = _Agent()
        gate = asyncio.Event()
        ran: list[int] = []

        async def stage_pass() -> None:
            ran.append(1)
            await gate.wait()

        agent._stage_pass = stage_pass  # type: ignore[method-assign]
        agent._stage_due()
        await asyncio.sleep(0)
        agent._stage_at = float("-inf")
        agent._stage_due()
        gate.set()
        await agent._stage_task
        assert ran == [1]

    asyncio.run(go())


def test_the_threads_call_is_dispatched_on_the_loop_with_no_session_caller() -> None:
    async def go() -> None:
        agent = _Agent()
        call = agent._stage_call(asyncio.get_running_loop())
        assert await asyncio.to_thread(call, "close", id="x", closer={"by": "tick"}) == {"ok": True}
        assert agent.dispatched[0]["method"] == "close" and "caller" not in agent.dispatched[0]
        agent.answer = {"error": "no session x", "error_data": {"id": "x"}}
        with pytest.raises(AgentError, match="no session x") as e:
            await asyncio.to_thread(call, "close", id="x")
        assert e.value.data == {"id": "x"}

    asyncio.run(go())


def test_the_arguments_handed_over_are_the_ones_stage_tick_run_takes(body: list[dict[str, Any]]) -> None:
    import inspect

    from shiftlead import stage_tick

    asyncio.run(_Agent(roster=["/n/r"])._stage_pass())
    inspect.signature(stage_tick.run).bind(**body[0])


def test_a_call_that_times_out_is_left_to_finish_and_never_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_stage, "STAGE_CALL_WAIT", 0.2)

    async def go() -> None:
        agent = _Agent()
        finished: list[str] = []

        async def slow(req: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(1.5)
            finished.append(req["method"])
            return {"id": req["id"], "result": None}

        agent._dispatch_inner = slow  # type: ignore[method-assign]
        call = agent._stage_call(asyncio.get_running_loop())
        with pytest.raises(agent_stage.AgentUnavailable, match="did not answer create"):
            await asyncio.to_thread(call, "create")
        await asyncio.sleep(1.5)
        assert finished == ["create"], "the create ran to its end on the loop"

    asyncio.run(go())


def test_an_entry_whose_refusal_stands_is_told_to_the_person_once_by_its_team(
    monkeypatch: pytest.MonkeyPatch, body: list[dict[str, Any]]
) -> None:
    """TD-2051: each refusal the pass names as newly standing is one system note to the person, under its team."""
    from datetime import UTC, datetime

    r = SimpleNamespace(
        tid="TD-7",
        team="build-r",
        act="reconcile (merged)",
        why="the ledger refused the archive",
        since=datetime(2026, 11, 24, 23, 0, tzinfo=UTC),
    )
    module = SimpleNamespace(call=lambda **kw: SimpleNamespace(tell={}, refused=(r,)), Kept=lambda: None)
    monkeypatch.setattr(agent_stage, "home_call", lambda name: module)
    agent = _Agent()
    asyncio.run(agent._stage_pass())
    assert agent.notes == [("person", refused_words(r), "build-r")]
    text = refused_words(r)
    assert text.startswith("The home cannot move TD-7 (team build-r): its reconcile (merged) step was refused")
    assert "since 2026-11-24 23:00 UTC" in text and "- the ledger refused the archive" in text


def test_an_audit_that_rested_is_told_to_the_person_once_by_its_team(monkeypatch: pytest.MonkeyPatch, body) -> None:
    """TD-2053: an audit whose run is lost a second time rests, and the person is told with one note; a step that
    started or offered a run again tells nothing."""
    rested = SimpleNamespace(team="build-r", audit="docs", act=SimpleNamespace(case="silent"), tell=True)
    started = SimpleNamespace(team="build-r", audit="tests", act=SimpleNamespace(case=""), tell=False)
    module = SimpleNamespace(call=lambda **kw: SimpleNamespace(tell={}, audits=(started, rested)), Kept=lambda: None)
    monkeypatch.setattr(agent_stage, "home_call", lambda name: module)
    agent = _Agent()
    asyncio.run(agent._stage_pass())
    assert agent.notes == [("person", rested_words(rested), "build-r")]
    assert rested_words(rested).startswith(
        "The audit docs of team build-r lost its run twice (the second time, its session went silent)"
    )


def _jobs_reading() -> dict[str, Any]:
    return {
        "ledger": {"entries": [{"id": "TD-7"}]},
        "prs": {"open": [], "recent": []},
        "work_orders": {"orders": [{"id": "board:0123abcd", "kind": "decided"}, {"kind": "no id"}]},
        "pr_orders": {"orders": [{"id": "pr:12", "kind": "red"}]},
        "boards": {"boards": [{"items": [{"key": "board:0123abcd"}]}]},
    }


def test_the_jobs_readings_are_handed_over_as_copies(body: list[dict[str, Any]]) -> None:
    agent = _Agent(roster=["/n/r"])
    agent._repos["/c/r"] = _jobs_reading()
    asyncio.run(agent._stage_pass())
    got = body[0]
    assert got["orders"] == [{"id": "board:0123abcd", "kind": "decided"}], "an order with no id is no job's"
    assert got["pr_orders"] == [{"id": "pr:12", "kind": "red"}]
    assert got["boards"] == agent._repos["/c/r"]["boards"] and got["boards"] is not agent._repos["/c/r"]["boards"]
    assert got["orders"][0] is not agent._repos["/c/r"]["work_orders"]["orders"][0], "the thread gets copies"
    import inspect

    from shiftlead import stage_tick

    inspect.signature(stage_tick.run).bind(**got)


@pytest.mark.parametrize(
    "spoil",
    [
        lambda r: r.pop("work_orders"),
        lambda r: r.update(work_orders=None),
        lambda r: r.pop("boards"),
        lambda r: r.update(boards={"error": "unreadable"}),
        lambda r: r.update(work_orders={"error": "unreadable"}),
        lambda r: r.update(pr_orders={"error": "unreadable"}),
        lambda r: r.update(prs={"error": "gh failed"}),
        lambda r: r.update(seams={"serve": {"ok": False, "lacks": [{"key": "gate", "words": "unserved: no gate"}]}}),
    ],
    ids=[
        "no-orders",
        "orders-none",
        "no-boards",
        "boards-error",
        "orders-error",
        "pr-orders-error",
        "prs-error",
        "unserved",
    ],
)
def test_no_job_reading_is_handed_over_where_one_cannot_be_judged_by(spoil: Any) -> None:
    reading = _jobs_reading()
    spoil(reading)
    assert agent_stage.job_readings(reading) == {}, "the pass then passes over no job, closing none as gone"


def test_a_served_repos_readings_are_its_jobs() -> None:
    reading = {**_jobs_reading(), "seams": {"serve": {"ok": True, "lacks": []}}}
    assert set(agent_stage.job_readings(reading)) == {"orders", "pr_orders", "boards"}


def test_a_repo_never_red_has_no_pr_orders_and_still_its_jobs() -> None:
    reading = _jobs_reading()
    reading.pop("pr_orders")
    got = agent_stage.job_readings(reading)
    assert got["pr_orders"] == [] and got["orders"] == [{"id": "board:0123abcd", "kind": "decided"}]
