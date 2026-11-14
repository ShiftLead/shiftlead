"""TD-1637 (TD-1550's design), design §4.2 *A turn's id*: an adapter whose tool names each turn sends it as
the neutral `turn`, `turn_start` on the event that starts it and `turn_end` on a report that ends one. The
core keeps the last eight started on the record (`turns`, newest last, emptied on a new `adapter_id`) and
reads a turn-end report by it: one of a turn in the list but not its newest is dropped (a cancelled turn's,
landing late), one naming no turn settles the session unless it is `exited`, one of a turn not in the list is
applied. An event with neither mark is read as before."""

from __future__ import annotations

import time

import pytest

from sessionorc.agent_tick import TURNS_KEPT, TickMixin
from sessionorc.client import LocalClient
from sessionorc.models import HOME_OWNED, NODE_OWNED, Session

pytestmark = pytest.mark.integration


async def _hook(c, sid, **event):
    await c.call("hook", session=sid, **event)
    return await c.call("get", id=sid)


async def _start(c, sid, turn, **kw):
    return await _hook(c, sid, state="working", prompt=True, turn=turn, turn_start=True, **kw)


async def _end(c, sid, turn, **kw):
    return await _hook(c, sid, state="idle", pending=None, turn=turn, turn_end=True, **kw)


def test_turns_is_the_nodes():
    assert "turns" in NODE_OWNED and "turns" not in HOME_OWNED


async def test_a_late_report_of_an_older_turn_is_dropped(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="t", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await _hook(c, sid, state="idle", adapter_id="a1")
        rec = await _start(c, sid, "p1")
        assert rec["state"] == "working" and agent.sessions[sid].turns == ["p1"]
        await _start(c, sid, "p2")  # p1 was cancelled; the next prompt started p2
        rec = await _end(c, sid, "p1")  # p1's StopCancelled, landing after p2 started
        assert rec["state"] == "working"
        rec = await _end(c, sid, "p2")
        assert rec["state"] == "idle"
        assert agent.sessions[sid].turns == ["p1", "p2"]


async def test_a_turn_never_seen_to_start_reads_idle(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="t", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await _start(c, sid, "p1")
        rec = await _end(c, sid, "zz")
        assert rec["state"] == "idle"


async def test_a_report_with_no_turn_settles_unless_exited(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="t", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await _start(c, sid, "p1")
        await _start(c, sid, "p2")
        rec = await _end(c, sid, None)  # an idle_prompt with no promptId
        assert rec["state"] == "idle"
        rec = await _hook(c, sid, state="exited", pending=None)
        assert rec["state"] == "exited"
        rec = await _end(c, sid, None)
        assert rec["state"] == "exited"


async def test_the_list_keeps_the_last_eight_and_a_new_conversation_empties_it(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="t", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await _hook(c, sid, state="idle", adapter_id="a1")
        for n in range(TURNS_KEPT + 2):
            await _start(c, sid, f"p{n}")
        await _start(c, sid, "p3")  # a start seen twice (a replayed queue) moves to the newest, once
        turns = agent.sessions[sid].turns
        assert len(turns) == TURNS_KEPT and turns[-1] == "p3" and turns.count("p3") == 1 and "p0" not in turns
        rec = await _end(c, sid, "p0")  # older than the list: applied
        assert rec["state"] == "idle"
        await _hook(c, sid, state="idle", adapter_id="a2", subagents_reset=True)  # a /clear
        assert agent.sessions[sid].turns == []
        assert agent.store.load(sid).turns == []


async def test_a_subagents_event_and_an_event_with_no_mark_are_read_as_before(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="t", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await _start(c, sid, "p1")
        await _start(c, sid, "p2")
        rec = await _hook(c, sid, state="idle", pending=None)
        assert rec["state"] == "idle"
        await _start(c, sid, "p3")
        # a child's event never reads the parent's list, whatever it carries
        await _hook(c, sid, subagent="k1", subagent_seen=True, turn="p9", turn_start=True)
        rec = await _hook(c, sid, subagent="k1", subagent_seen=True, turn="p1", turn_end=True)
        assert agent.sessions[sid].turns == ["p1", "p2", "p3"] and rec["state"] == "working"


async def test_a_queued_start_older_than_a_live_event_adds_nothing(agent, hookstub, tmp_path):
    """A start replayed from the offline queue after the next turn's live start: added, it would stand newest
    and drop the live turn's own report."""
    async with LocalClient() as c:
        sid = (await c.call("create", name="t", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await _start(c, sid, "p2")
        old = {"state": "working", "prompt": True, "turn": "p1", "turn_start": True, "at": time.time() - 60}
        agent._apply_event(sid, old, queued=True)
        assert agent.sessions[sid].turns == ["p2"]
        rec = await _end(c, sid, "p2")
        assert rec["state"] == "idle"


@pytest.mark.parametrize("state", ["exited", "closed"])
def test_a_dying_runs_own_end_never_empties_the_new_conversations_turns(state):
    """TD-1806: `_late_turn` empties the list on a new `adapter_id` except on an `exited` or `closed` event — a
    run's own end, which names the run that is going, not a conversation that replaced it. Read on the method
    itself: through `hook`, `_apply_event` already drops an end naming a run the record no longer holds
    (TD-186) before the turns are read, so only this reaches the exemption."""
    s = Session(id="t", name="t", kind="agent", adapter="hookstub", dir="/x", adapter_id="a1", turns=["p1"])
    assert TickMixin._late_turn(s, {"state": state, "adapter_id": "a2"}) is False
    assert s.turns == ["p1"]
    TickMixin._late_turn(s, {"state": "idle", "adapter_id": "a2"})  # a live event of a new conversation: emptied
    assert s.turns == []
