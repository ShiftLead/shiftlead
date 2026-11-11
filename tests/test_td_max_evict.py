"""The host cap's eviction (design §4.9 *Scaling with the work*, §6 rule 3, td-max; TD-1545): a start when the
host's live count is at or above `scale.live` first closes the longest-idle clean extra seat back to held, its
`scale.last` saying why; the start is never refused for want of room, and an extra seat's start never evicts an
extra of its own seat. Two starts at the cap in one moment take two different seats."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc.agent_common import SEAT_PR_WAIT
from sessionorc.client import LocalClient
from sessionorc.models import MailEntry, ProgressEntry


async def _start(person, tmp_path, name, **kw):
    (tmp_path / name).mkdir()
    return (await person.call("create", name=name, dir=str(tmp_path / name), **kw))["id"]


def _extra_seat(agent, sid, line, idle_for):
    rec = agent.sessions[sid]
    rec.seat, rec.scale = {"trigger": "asks"}, {"line": line}
    rec.state, rec.confidence, rec.pending = "idle", "hook", None
    rec.git = {"dirty": 0, "unpushed": 0}
    rec.since = (datetime.now(UTC) - idle_for).isoformat()
    return rec


@pytest.mark.integration
async def test_a_start_at_the_cap_closes_the_longest_idle_clean_extra_seat(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        a = _extra_seat(agent, await _start(person, tmp_path, "tl-2"), "tl", timedelta(minutes=5))
        b = _extra_seat(agent, await _start(person, tmp_path, "tl-3"), "tl", timedelta(minutes=50))
        agent._machine_cap = 2
        sid = await _start(person, tmp_path, "mine")  # the person's own start: never refused
        assert agent.sessions[sid].state not in ("exited", "closed")
        assert b.state == "closed" and a.state == "idle"  # the longest idle went back to held
        assert b.scale["line"] == "tl" and b.scale["last"]["did"] == "hold"
        assert b.scale["last"]["why"] == "host full, room for mine"
        assert "last" not in a.scale


@pytest.mark.integration
async def test_below_the_cap_nothing_is_closed(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        a = _extra_seat(agent, await _start(person, tmp_path, "tl-2"), "tl", timedelta(minutes=50))
        agent._machine_cap = 3
        await _start(person, tmp_path, "mine")
        assert a.state == "idle" and "last" not in a.scale


@pytest.mark.integration
async def test_only_a_clean_quiet_extra_seat_of_another_seat_is_taken_else_the_start_goes_on(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        dirty = _extra_seat(agent, await _start(person, tmp_path, "tl-2"), "tl", timedelta(hours=3))
        dirty.git = {"dirty": 1, "unpushed": 0}
        mail = _extra_seat(agent, await _start(person, tmp_path, "tl-3"), "tl", timedelta(hours=3))
        mail.inbox.append(
            MailEntry(id="m-1", at=datetime.now(UTC).isoformat(), from_="person", to=mail.id, kind="ask", text="?")
        )
        member = agent.sessions[await _start(person, tmp_path, "grind-1")]  # a member is no extra seat
        member.state, member.git = "idle", {"dirty": 0, "unpushed": 0}
        own = _extra_seat(agent, await _start(person, tmp_path, "fc-2"), "fc", timedelta(hours=3))
        agent._machine_cap = 4
        # an extra of fc's own seat starting: fc-2 never trades places with it, and nothing else is clean
        sid = await _start(person, tmp_path, "fc-3", unattended=True, seat={"trigger": "asks"}, scale={"line": "fc"})
        assert agent.sessions[sid].state not in ("exited", "closed")  # the start went on with no room made
        assert [r.state for r in (dirty, mail, member, own)] == ["idle"] * 4
        # a start of another kind at the cap takes fc-2, now the only clean one
        await _start(person, tmp_path, "mine")
        assert own.state == "closed" and own.scale["last"]["why"] == "host full, room for mine"
        assert mail.state == dirty.state == "idle"  # unread mail and work left keep a seat open


@pytest.mark.integration
async def test_two_starts_at_the_cap_in_one_moment_take_two_different_seats(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        seats = [
            _extra_seat(agent, await _start(person, tmp_path, f"tl-{i}"), "tl", timedelta(minutes=10 * i))
            for i in (2, 3, 4)
        ]
        agent._machine_cap = 3
        (tmp_path / "x").mkdir()
        (tmp_path / "y").mkdir()
        async with LocalClient() as other:  # two connections: one carries one call at a time
            await asyncio.gather(
                person.call("create", name="x", dir=str(tmp_path / "x")),
                other.call("create", name="y", dir=str(tmp_path / "y")),
            )
        assert [s.state for s in seats] == ["idle", "closed", "closed"]  # the two longest idle, one each


@pytest.mark.integration
async def test_a_start_that_replaces_its_names_record_takes_its_slot_and_closes_nothing(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        a = _extra_seat(agent, await _start(person, tmp_path, "tl-2"), "tl", timedelta(minutes=5))
        b = _extra_seat(agent, await _start(person, tmp_path, "tl-3"), "tl", timedelta(minutes=50))
        agent._machine_cap = 2
        # a start replacing tl-2's record (a scheduled one it starts, its name's holder): that slot is the
        # start's, so the host is not over, and the record it replaces is never the one closed for it
        held = await agent._evict_for_room("tl-2", None, {a.id})
        assert a.state == b.state == "idle" and "last" not in a.scale and "last" not in b.scale
        held.clear()


@pytest.mark.integration
async def test_a_cancelled_start_holds_no_slot(agent, tmp_path):
    await park_ticks(agent)
    agent._machine_cap = 1
    async with agent._evict_lock:  # the reading waits on the lock, and is cancelled there
        task = asyncio.create_task(agent._evict_for_room("x", None, set()))
        await asyncio.sleep(0)
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not any(agent._room_held)


@pytest.mark.integration
async def test_working_on_its_own_a_pr_waiting_or_a_suspended_or_superseded_seat_is_not_taken(agent, tmp_path):
    """TD-1627: `_evictable`'s other clauses (§6 rule 3) — a live subagent or shell, a PR of its own within
    `SEAT_PR_WAIT` of its idle start (one past it is taken), a suspended seat and a superseded one."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        idle = timedelta(minutes=30)
        made = {}
        for name in ("clean", "subagent", "shell", "pr-young", "pr-old", "suspended", "superseded"):
            idle_for = SEAT_PR_WAIT + timedelta(minutes=5) if name == "pr-old" else idle
            made[name] = _extra_seat(agent, await _start(person, tmp_path, name), "tl", idle_for)
        made["subagent"].subagents, made["subagent"].subagent_at = 1, now.isoformat()
        made["shell"].shells = [{"id": "b1", "since": now.isoformat()}]
        made["pr-young"].progress = [ProgressEntry(ref="TD-1", pr=11)]
        made["pr-old"].progress = [ProgressEntry(ref="TD-2", pr=12)]
        made["suspended"].suspended = {"at": now.isoformat(), "by": "person", "why": "identity"}
        made["superseded"].superseded_by = made["clean"].id
        got = {name: agent._evictable(r, now, None) for name, r in made.items()}
        assert got == {
            "clean": True,
            "subagent": False,
            "shell": False,
            "pr-young": False,
            "pr-old": True,
            "suspended": False,
            "superseded": False,
        }
