"""TD-743 (TD-734's build), design §4.2 *Working on its own*: an `idle` session with a live subagent —
`subagents` above zero and a subagent's hook within `STALL_AFTER` (`subagent_at`) — is working on its
own. One helper, `subagents_live`, is the reading the view carries and §6 rules 3, 4 and 9 call; the
count is reset by a fresh conversation and by the record's exit; a queued event never moves the time
back; and the tick pushes a record whose reading flips with no event behind it."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks, wait_for

from sessionorc import agent_common, reports, work
from sessionorc.agent import IDLE_NUDGE, SEAT_IDLE_GRACE, STALL_AFTER
from sessionorc.client import LocalClient
from sessionorc.models import ProgressEntry, Session

pytestmark = pytest.mark.integration

SHELL = {"adapter": "agentshell", "argv": ["bash", "--norc", "--noprofile"], "unattended": True, "supervised": True}


def _iso(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


@pytest.fixture(autouse=True)
def _no_gh(monkeypatch):
    monkeypatch.setattr(reports, "merged_prs", lambda *a, **kw: None)


async def _create(person, tmp_path, name: str, **kw) -> str:
    (tmp_path / name).mkdir(exist_ok=True)
    params = {"name": name, "dir": str(tmp_path / name), "prompt": "the brief"}
    return (await person.call("create", **{**SHELL, **params, **kw}))["id"]


def _idle(rec: Session, now: datetime, ago: timedelta) -> None:
    rec.state, rec.confidence, rec.since = "idle", "hook", _iso(now - ago)
    rec.git = {"branch": "main", "dirty": 0, "unpushed": 0}


def test_the_helper_reads_the_count_and_its_time():
    now = datetime.now(UTC)
    rec = Session(id="x", name="x", dir="/tmp", kind="interactive", adapter="claude-code")
    assert not agent_common.subagents_live(rec, now)
    rec.subagents, rec.subagent_at = 2, _iso(now - timedelta(minutes=1))
    assert agent_common.subagents_live(rec, now)
    # a lost SubagentStop: the count stands, but nothing has been heard within STALL_AFTER
    rec.subagent_at = _iso(now - STALL_AFTER - timedelta(seconds=1))
    assert not agent_common.subagents_live(rec, now)
    rec.subagents, rec.subagent_at = 0, _iso(now)
    assert not agent_common.subagents_live(rec, now)
    # the idle stretch counts from the later of `since` and `subagent_at`
    rec.since = _iso(now - timedelta(hours=1))
    assert agent_common.idle_from(rec) == now.replace(microsecond=0)


async def test_a_subagents_events_set_its_time_and_leave_the_state_alone(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w")
        rec = agent.sessions[sid]
        await agent.rpc_hook(sid, state="idle")
        await agent.rpc_hook(sid, subagent_delta=1, subagent_seen=True)
        await agent.rpc_hook(sid, subagent_delta=1, subagent_seen=True)
        assert rec.subagents == 2 and rec.subagent_at and rec.state == "idle"
        # a subagent's tool hook refreshes the time and says nothing about the main composer
        rec.subagent_at = _iso(datetime.now(UTC) - timedelta(minutes=5))
        await agent.rpc_hook(sid, adapter_id="u1", subagent_seen=True)
        assert datetime.now(UTC) - agent_common._parse(rec.subagent_at) < timedelta(seconds=5)
        assert rec.state == "idle"
        view = agent._view(rec)
        assert view["subagents_live"] is True and view["state"] == "idle", "idle stays idle in every payload"
        # a compaction keeps the count; a fresh conversation resets it
        await agent.rpc_hook(sid, adapter_id="u1")
        assert rec.subagents == 2
        await agent.rpc_hook(sid, state="working", pending=None, subagents_reset=True)
        assert rec.subagents == 0 and rec.subagent_at is None
        await person.call("kill", id=sid)


async def test_a_queued_event_never_moves_the_time_back_and_a_stale_reset_is_not_applied(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w")
        rec = agent.sessions[sid]
        await agent.rpc_hook(sid, state="idle")
        then = time.time() - 600
        # replayed late, a queued subagent event stamps its own time, not the drain's
        agent._apply_event(sid, {"subagent_delta": 1, "subagent_seen": True, "at": then}, queued=True)
        assert rec.subagents == 1 and rec.subagent_at == _iso(datetime.fromtimestamp(then, UTC))
        await agent.rpc_hook(sid, subagent_seen=True)
        live = rec.subagent_at
        agent._apply_event(sid, {"subagent_seen": True, "at": then + 60}, queued=True)
        assert rec.subagent_at == live, "an older event never moves it back"
        # a queued start older than the subagent's last word is not a new conversation
        agent._apply_event(sid, {"subagents_reset": True, "at": then + 60}, queued=True)
        assert rec.subagents == 1 and rec.subagent_at == live
        await person.call("kill", id=sid)


async def test_the_records_exit_resets_the_count(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w")
        rec = agent.sessions[sid]
        await agent.rpc_hook(sid, subagent_delta=1, subagent_seen=True)
        await agent.rpc_hook(sid, state="exited", pending=None)
        assert rec.subagents == 0 and rec.subagent_at is None
        await person.call("kill", id=sid)


async def test_the_view_and_the_tick_agree_and_a_flip_is_pushed(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w")
        rec = agent.sessions[sid]
        _idle(rec, now, timedelta(hours=1))
        rec.subagents, rec.subagent_at = 1, _iso(now - STALL_AFTER + timedelta(seconds=30))
        assert agent._view(rec)["subagents_live"] is True
        assert agent._finished_view(rec, now)["subagents_live"] is True
        pushes = []
        real = agent._push_changes

        async def counted():
            pushes.append(1)
            await real()

        monkeypatch.setattr(agent, "_push_changes", counted)
        await agent._subagent_flips(now)
        await agent._subagent_flips(now + timedelta(seconds=10))
        assert pushes == [], "nothing flipped"
        # STALL_AFTER passes with no event: the reading flips, and the tick pushes the record
        later = now + timedelta(minutes=1)
        assert not agent_common.subagents_live(rec, later)
        assert agent._finished_view(rec, later)["subagents_live"] is False
        await agent._subagent_flips(later)
        assert pushes == [1]
        await person.call("kill", id=sid)


async def test_the_nudge_passes_over_a_live_subagent_and_counts_from_its_end(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w")
        rec = agent.sessions[sid]
        rec.progress = [ProgressEntry(ref="TD-001", status="claimed", source="declared")]
        _idle(rec, now, IDLE_NUDGE + timedelta(minutes=5))
        rec.subagents, rec.subagent_at = 1, _iso(now - timedelta(minutes=1))
        sent = []

        async def send(s, line):
            sent.append(line)
            return True

        agent._policy_send = send
        await agent._idle_nudge(rec, now)
        assert sent == [] and rec.nudged_at is None, "its own work runs"
        # its last subagent ended a minute ago: the stretch counts from then
        rec.subagents = 0
        await agent._idle_nudge(rec, now)
        assert sent == [], "not nudged on the tick after its last subagent ends"
        await agent._idle_nudge(rec, now + IDLE_NUDGE)
        assert len(sent) == 1
        await person.call("kill", id=sid)


async def test_a_seat_with_a_live_subagent_is_not_closed(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "audit", seat={"trigger": "every", "after": "6h"})
        rec = agent.sessions[sid]
        _idle(rec, now, SEAT_IDLE_GRACE + timedelta(minutes=10))
        rec.subagents, rec.subagent_at = 1, _iso(now - timedelta(minutes=1))
        assert not agent._seat_has_run(rec, now), "it ended its turn on a reviewer subagent"
        # the subagent ended after a long idle stretch: the grace counts from its end
        rec.subagents, rec.subagent_at = 0, _iso(now - timedelta(seconds=30))
        assert not agent._seat_has_run(rec, now)
        assert agent._seat_has_run(rec, now + SEAT_IDLE_GRACE)
        await person.call("kill", id=sid)


async def test_a_standing_idle_open_beside_a_live_subagent_is_no_cause(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        mgr = await _create(person, tmp_path, "mgr", seat={"trigger": "team"})
        w = await _create(person, tmp_path, "w", controllers=[mgr])
        rec = agent.sessions[w]
        _idle(rec, now, 2 * IDLE_NUDGE)
        rec.idle_open = {"at": _iso(now), "ref": "TD-001"}
        records = list(agent.sessions.values())
        assert [c["by"] for c in agent._team_causes(agent.sessions[mgr], records)] == ["open"]
        rec.subagents, rec.subagent_at = 1, _iso(datetime.now(UTC))
        assert agent._team_causes(agent.sessions[mgr], records) == []
        # nor is a new mark written while it runs
        rec.idle_open, rec.nudged_at = None, _iso(now - IDLE_NUDGE - timedelta(minutes=1))
        rec.since = _iso(now - 2 * IDLE_NUDGE)
        rec.lane = ["TD-1"]
        await agent._idle_open(rec, now)
        assert rec.idle_open is None
        for sid in (w, mgr):
            await person.call("kill", id=sid)


def test_a_team_whose_member_has_a_live_subagent_is_not_finished():
    said = {"at": "2026-10-15T10:00:00Z", "why": "nothing open"}
    member = {"id": "a", "name": "grinder-dc-1", "state": "idle", "unattended": True, "out_of_work": said}
    seat = {"id": "s", "name": "techlead", "state": "idle", "unattended": True, "seat": {"trigger": "asks"}}
    assert work.finished([member, seat])["why"] == []
    got = work.finished([{**member, "subagents_live": True}, seat])
    assert got["why"] == ["grinder-dc-1 idle, subagent live"]
    got = work.finished([member, {**seat, "subagents_live": True}])
    assert got["why"] == ["techlead idle, subagent live"]


async def test_an_exited_record_is_not_live(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w")
        rec = agent.sessions[sid]
        await agent.rpc_hook(sid, subagent_delta=1, subagent_seen=True)
        assert await wait_for(lambda: agent._view(rec)["subagents_live"], timeout=2)
        await person.call("kill", id=sid)
        assert agent._view(agent.sessions[sid])["subagents_live"] is False
