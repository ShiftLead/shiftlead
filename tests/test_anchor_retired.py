"""The anchor seat retired (design §4.9b *No anchor seat*, §4.9 *A definition written before TD-722*,
TD-757): a red PR's order is on every `free-pick` lane with no `anchor` record anywhere; `anchor` is no
lane word; an evaluation is flagged, since no lane takes it; the home's tick retires each leftover
record whose role is `anchor` — a closed one forgotten, a live one closed first; and `create` with
`held` still writes a seat's record alone for a manager on call and a replay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import park_ticks

from sessionorc import ledger as ledger_mod
from sessionorc import models
from sessionorc.client import AgentError, LocalClient


def _order(n: int = 7) -> dict:
    return {"id": f"pr:{n}", "pickable": "yes", "work_order": True, "pr_order": True, "kind": "", "blocked_by": []}


@pytest.mark.unit
def test_a_red_prs_order_is_every_free_pick_lanes_and_no_other_word_takes_it():
    order = _order()
    assert ledger_mod.lane_matches(["free-pick"], order)
    assert ledger_mod.lane_matches(["free-pick", "owner:grinder"], order)  # no owner narrows an order out
    assert not ledger_mod.lane_matches(["design-first"], order)
    assert not ledger_mod.lane_matches(["anchor"], order), "anchor is no lane word"
    assert not ledger_mod.lane_matches(["free-pick"], {**order, "pickable": "no"})


@pytest.mark.unit
def test_anchor_is_no_lane_word_and_takes_nothing():
    assert "anchor" not in models.LANE_WORDS
    entry = {"id": "TD-1", "pickable": "yes", "owner": "anchor", "kind": "", "blocked_by": []}
    assert not ledger_mod.lane_matches(["anchor"], entry)
    assert not ledger_mod.lane_matches(["anchor"], {**entry, "kind": "evaluation"})
    assert not ledger_mod.lane_matches(["anchor"], {**entry, "pickable": "no", "blocked_by": ["decision (anchor)"]})


@pytest.mark.unit
def test_an_evaluation_is_its_page_kind_flagged_as_no_lanes_and_a_decision_not_the_persons_is_other():
    ev = {"id": "TD-2", "pickable": "yes", "owner": "anchor", "kind": "evaluation", "blocked_by": []}
    dec = {"id": "TD-3", "pickable": "yes", "owner": "anchor", "kind": "decision", "blocked_by": []}
    held = {"id": "TD-4", "pickable": "no", "owner": "grinder", "kind": "", "blocked_by": ["decision (anchor)"]}
    assert [ledger_mod.kind_of(e) for e in (ev, dec, held)] == ["evaluation", "other", "other"]
    assert not any(ledger_mod.lane_matches(["free-pick"], e) for e in (ev, dec, held))
    flagged = ledger_mod.flags([{**e, "for_page": ledger_mod.kind_of(e)} for e in (ev, dec)])
    assert flagged == [f"TD-3: {ledger_mod.NO_KIND}", f"TD-2: {ledger_mod.NO_LANE}"]
    assert ledger_mod.NO_LANE.startswith("no lane takes an evaluation")


def _shell(tmp_path: Path, name: str, **kw) -> dict:
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    return {
        "name": name,
        "dir": str(d),
        "adapter": "shell",
        "argv": ["bash", "--norc", "--noprofile"],
        "unattended": True,
        "supervised": True,
        **kw,
    }


@pytest.mark.integration
async def test_the_tick_forgets_a_closed_anchor_record_and_closes_then_forgets_a_live_clean_one(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        closed = (
            await person.call(
                "create", **_shell(tmp_path, "a-anchor", role="anchor", seat={"trigger": "asks"}, held=True)
            )
        )["id"]
        live = (await person.call("create", **_shell(tmp_path, "b-anchor", role="anchor")))["id"]
        other = (await person.call("create", **_shell(tmp_path, "c-grinder", role="grinder")))["id"]
        rec = agent.sessions[live]
        rec.state, rec.confidence = "idle", "hook"
        rec.git = {"dirty": 0, "unpushed": 0}
        await agent._retire_anchors()
        assert closed not in agent.sessions, "a closed anchor record is forgotten"
        assert live not in agent.sessions, "a live clean one is closed, then forgotten"
        assert agent.sessions[other].state not in ("exited", "closed"), "another role is left alone"
        later = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
        sched = (await person.call("create", **_shell(tmp_path, "e-anchor", role="anchor", start_at=later)))["id"]
        assert agent.sessions[sched].state == "scheduled"
        await agent._retire_anchors()
        assert sched not in agent.sessions, "a scheduled anchor's start is cancelled"
        await person.call("kill", id=other)


@pytest.mark.integration
async def test_a_live_anchor_record_with_work_left_or_working_is_left_and_looked_at_next_tick(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = (await person.call("create", **_shell(tmp_path, "d-anchor", role="anchor")))["id"]
        rec = agent.sessions[sid]
        rec.state, rec.confidence, rec.git = "idle", "hook", {"dirty": 2, "unpushed": 0}
        await agent._retire_anchors()
        assert agent.sessions[sid].state == "idle", "work left: never closed over it"
        rec.state = "working"
        rec.git = {"dirty": 0, "unpushed": 0}
        await agent._retire_anchors()
        assert agent.sessions[sid].state == "working"
        rec.state = "exited"
        rec.git = {"dirty": 0, "unpushed": 3}
        await agent._retire_anchors()
        assert sid in agent.sessions, "an exited one with unpushed work is the person's row"
        rec.git = {"dirty": 0, "unpushed": 0}
        await agent._retire_anchors()
        assert sid not in agent.sessions


@pytest.mark.integration
async def test_a_held_create_writes_the_seat_closed_with_no_pane_and_never_over_a_running_one(agent, tmp_path):
    await park_ticks(agent)
    seat = {"trigger": "asks"}
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="held writes a seat's record alone"):
            await person.call("create", **_shell(tmp_path, "t-lead", held=True))
        for bad in ({"unattended": False}, {"resume": "abc"}):
            with pytest.raises(AgentError, match="held writes a seat's record alone"):
                await person.call("create", **_shell(tmp_path, "t-lead", held=True, seat=seat, **bad))
        sid = (await person.call("create", **_shell(tmp_path, "t-lead", held=True, seat=seat)))["id"]
        rec = agent.sessions[sid]
        assert rec.state == "closed" and rec.closer == {"by": "start", "why": "held"}
        assert sid not in {p.session for p in agent.tmux.list_panes()}, "no pane"
        assert not hasattr(rec, "seat_held")
        run = (await person.call("create", **_shell(tmp_path, "t-run", seat=seat)))["id"]
        with pytest.raises(AgentError, match="is running|the seat is already there"):
            await person.call("create", **_shell(tmp_path, "t-run", held=True, seat=seat))
        assert agent.sessions[run].state not in ("exited", "closed")
        await person.call("kill", id=run)


@pytest.mark.integration
async def test_checkout_held_is_no_rpc(agent):
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="unknown method|checkout_held"):
            await person.call("checkout_held", dir="/tmp")


@pytest.mark.integration
async def test_a_suspended_anchor_record_is_the_persons_and_never_forgotten(agent, tmp_path):
    """A suspended one is the person's (§4.8a) and never forgotten here (TD-774)."""
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create", **_shell(tmp_path, "s-anchor", role="anchor", seat={"trigger": "asks"}, held=True)
            )
        )["id"]
    rec = agent.sessions[sid]
    rec.git = {"dirty": 0, "unpushed": 0}
    rec.suspended = {"at": datetime.now(UTC).isoformat(), "by": "paul", "why": "identity alarm"}
    await agent._retire_anchors()
    assert sid in agent.sessions and agent.sessions[sid].state == "closed"


@pytest.mark.integration
async def test_a_nodes_anchor_record_is_removed_over_its_link_and_left_while_the_link_is_down(agent, monkeypatch):
    """A node's anchor record is removed at its node over the link; with the link down it stays and is
    looked at again next tick (§4.4a, TD-774)."""
    await park_ticks(agent)
    r = models.Session(id="ao-x-anchor", name="a", kind="interactive", adapter="shell", dir="/tmp/x", host="laptop")
    r.role, r.state = "anchor", "closed"
    agent.remote["laptop"] = {r.id: r}
    routed: list[tuple] = []

    async def route(method, params, caller, host):
        routed.append((method, params, host))
        return {}

    monkeypatch.setattr(agent, "_route_act", route)
    try:
        await agent._retire_anchors()
        assert routed == [], "the link is down: nothing is routed"
        assert r.id in agent.remote["laptop"]
        agent._link_muxes["laptop"] = SimpleNamespace(close=lambda *a, **k: None)  # the home closes it at stop
        await agent._retire_anchors()
        assert routed == [("remove", {"id": r.id}, "laptop")]
    finally:
        agent.remote.pop("laptop", None)
        agent._link_muxes.pop("laptop", None)


@pytest.mark.integration
async def test_a_scheduled_anchor_records_start_is_cancelled(agent, tmp_path, monkeypatch):
    """A scheduled anchor's start not yet made is cancelled through `_cancel_start` (TD-774), not
    merely forgotten."""
    await park_ticks(agent)
    cancelled: list[str] = []
    cancel = agent._cancel_start

    async def spy(s):
        cancelled.append(s.id)
        return await cancel(s)

    monkeypatch.setattr(agent, "_cancel_start", spy)
    later = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    async with LocalClient() as person:
        sid = (await person.call("create", **_shell(tmp_path, "f-anchor", role="anchor", start_at=later)))["id"]
    assert agent.sessions[sid].state == "scheduled"
    await agent._retire_anchors()
    assert cancelled == [sid]
    assert sid not in agent.sessions
