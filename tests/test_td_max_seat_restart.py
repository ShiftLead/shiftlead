"""Rule 1 and an extra seat (design §6 rule 1, §4.9 *Scaling with the work*, TD-1547): an extra seat that exits on
its own is restarted while it holds unread mail or an unanswered ask, and closed back to held otherwise — its
`scale.last` saying so; any extra ended by a road no rule restarts (a kill, past its ceiling) is closed held too.
One with work left or gated is left as it stands; a seat's own record is never rule 1's."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc.client import LocalClient
from sessionorc.models import MailEntry

pytestmark = pytest.mark.integration

AGENT = {"adapter": "agentshell", "argv": ["bash", "--norc", "--noprofile"]}


async def _seat_extra(person, agent, tmp_path, name="tl-2", scale=True):
    (tmp_path / name).mkdir()
    kw = {"scale": {"line": "tl"}} if scale else {}
    sid = (
        await person.call(
            "create",
            name=name,
            dir=str(tmp_path / name),
            unattended=True,
            supervised=True,
            prompt="p",
            seat={"trigger": "asks"},
            **kw,
            **AGENT,
        )
    )["id"]
    rec = agent.sessions[sid]
    rec.state, rec.pane, rec.confidence = "exited", True, "hook"  # a natural exit
    rec.git = {"dirty": 0, "unpushed": 0}
    return sid, rec


@pytest.fixture
def replays(agent, monkeypatch):
    calls: list[tuple[str, str]] = []

    async def replay(s, why, **kw):
        calls.append((s.id, why))

    monkeypatch.setattr(agent, "_replay", replay)
    return calls


def _ask(sid: str, mid: str = "m-1", kind: str = "ask", read: bool = False) -> MailEntry:
    e = MailEntry(id=mid, from_="ao-x-w", to=[sid], at="2026-11-11T08:00:00Z", kind=kind, text="read #12", pr=12)
    if read:
        e.read_at = "2026-11-11T08:01:00Z"
    return e


async def test_an_exited_extra_holding_an_ask_is_restarted_by_rule_1(agent, tmp_path, replays):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _seat_extra(person, agent, tmp_path)
        now = datetime.now(UTC)
        assert not agent._crashed(rec, now), "nothing waiting on it: no restart"
        rec.inbox.append(_ask(sid, read=True))  # read, never answered: still owed
        assert agent._crashed(rec, now)
        await agent._crash_restart(rec, now)
        assert replays == [(sid, "crash")]
        # unread mail of any kind owes a reading too
        rec.inbox = [_ask(sid, kind="note")]
        assert agent._crashed(rec, now)
        # a copy of an ask is not addressed to it: read, it owes nothing
        copy = _ask(sid, mid="m-2", read=True)
        copy.to = ["ao-x-other"]
        rec.inbox = [copy]
        assert not agent._crashed(rec, now)
        rec.inbox = [_ask(sid, kind="note")]
        # gated, or a kill (no pane), is not restarted
        rec.gated = {"at": "x"}
        assert not agent._crashed(rec, now)
        rec.gated, rec.pane = None, False
        assert not agent._crashed(rec, now)


async def test_a_seats_own_record_is_never_rule_1s(agent, tmp_path, replays):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _seat_extra(person, agent, tmp_path, name="tl", scale=False)
        rec.inbox.append(_ask(sid))
        assert not agent._crashed(rec, datetime.now(UTC))
        await agent._extra_hold(rec, datetime.now(UTC))
        assert rec.state == "exited", "a seat's own record is no extra: its ending is its own"


async def test_an_exited_extra_seat_with_nothing_waiting_is_closed_held_at_the_tick(agent, tmp_path, replays):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _seat_extra(person, agent, tmp_path)
        rec.git = {"dirty": 1, "unpushed": 0}  # work left: kept as it stands, for a person
        now = datetime.now(UTC)
        await agent._extra_hold(rec, now)
        assert rec.state == "exited"
        rec.git = {"dirty": 0, "unpushed": None}  # not known clean: kept as it stands too
        await agent._extra_hold(rec, now)
        assert rec.state == "exited"
        rec.git = {"dirty": 0, "unpushed": 0}
        rec.inbox.append(_ask(sid, read=True))  # an ask unanswered: rule 1's, never held
        await agent._extra_hold(rec, now)
        assert rec.state == "exited"
        rec.inbox[0].closed_reason = "replied"
        await agent._keep_running(now + timedelta(seconds=1))
        assert rec.state == "closed" and replays == []
        assert rec.closer["by"] == "tick" and rec.closer["why"] == "extra_held"
        assert rec.scale["line"] == "tl" and rec.scale["last"]["did"] == "hold"


async def test_each_guard_of_the_hold_leaves_an_exited_extra_as_it_stands(agent, tmp_path, replays):
    """Every guard `_extra_hold` reads, alone, keeps the extra `exited` (TD-1656): superseded, being dropped by
    a lowered max, just restarted, suspended, gated, a restart wanted and another host's record; with all of them
    cleared, the same record is closed held — so each guard is what kept it."""
    await park_ticks(agent)
    async with LocalClient() as person:
        sid, rec = await _seat_extra(person, agent, tmp_path)
        now = datetime.now(UTC)
        recent = (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
        guards = [
            ("superseded_by", "ao-x-tl-3", None),
            ("scale", {**rec.scale, "drop": "2026-11-11T08:00:00Z"}, rec.scale),
            ("restarts", [{"at": recent, "why": "crash"}], []),
            ("suspended", {"at": "2026-11-11T08:00:00Z", "why": "x"}, None),
            ("gated", {"at": "2026-11-11T08:00:00Z"}, None),
            ("restart_wanted", {"at": "2026-11-11T08:00:00Z", "why": "x"}, None),
            ("host", "elsewhere", rec.host),
        ]
        for attr, value, clear in guards:
            setattr(rec, attr, value)
            await agent._extra_hold(rec, now)
            assert rec.state == "exited", f"{attr} set: left to the road that holds it"
            setattr(rec, attr, clear)
        assert agent._just_restarted(rec, now) is False
        await agent._extra_hold(rec, now)
        assert rec.state == "closed" and rec.closer["why"] == "extra_held", "every guard cleared: held"
        assert replays == []


async def test_an_extra_ended_by_a_road_no_rule_restarts_is_closed_held(agent, tmp_path, replays):
    """Held is an extra's one non-live state (§4.9 *Scaling with the work*): a killed extra seat holding an unread ask,
    one past `RESTART_CEILING` holding one, and a worker line's killed extra are each closed held at the tick, their
    `scale.last` naming the road — rule 1 restarts none of them, and the mover takes the ask from a held extra."""
    await park_ticks(agent)
    async with LocalClient() as person:
        now = datetime.now(UTC)
        sid, killed = await _seat_extra(person, agent, tmp_path, name="tl-2")
        killed.pane = False
        killed.inbox.append(_ask(sid))
        sid3, ceiling = await _seat_extra(person, agent, tmp_path, name="tl-3")
        ceiling.restart_ceiling = {"at": "x", "count": 3}
        ceiling.inbox.append(_ask(sid3))
        (tmp_path / "w-3").mkdir()
        wid = (
            await person.call(
                "create",
                name="w-3",
                dir=str(tmp_path / "w-3"),
                unattended=True,
                supervised=True,
                prompt="p",
                scale={"line": "w"},
                **AGENT,
            )
        )["id"]
        worker = agent.sessions[wid]
        worker.state, worker.pane, worker.git = "exited", False, {"dirty": 0, "unpushed": 0}
        for rec, why in ((killed, "killed"), (ceiling, "exited past its restart ceiling"), (worker, "killed")):
            assert not agent._crashed(rec, now)
            await agent._extra_hold(rec, now)
            assert rec.state == "closed" and rec.closer["why"] == "extra_held", rec.name
            assert rec.scale["last"]["did"] == "hold" and rec.scale["last"]["why"] == why
        assert replays == []


async def test_a_worker_extra_rule_1_restarts_is_not_held(agent, tmp_path, replays, monkeypatch):
    """A worker line's extra that exits on its own with nothing declared is rule 1's crash restart, never held; the
    same exit with its profile paused waits for rule 1 too, left as it stands."""
    await park_ticks(agent)
    async with LocalClient() as person:
        (tmp_path / "w-3").mkdir()
        wid = (
            await person.call(
                "create",
                name="w-3",
                dir=str(tmp_path / "w-3"),
                unattended=True,
                supervised=True,
                prompt="p",
                scale={"line": "w"},
                **AGENT,
            )
        )["id"]
        rec = agent.sessions[wid]
        rec.state, rec.pane, rec.confidence, rec.git = "exited", True, "hook", {"dirty": 0, "unpushed": 0}
        now = datetime.now(UTC)
        assert agent._crashed(rec, now)
        await agent._extra_hold(rec, now)
        assert rec.state == "exited"
        monkeypatch.setattr(agent, "_profile_gated", lambda *a, **k: True)
        await agent._extra_hold(rec, now)
        assert rec.state == "exited", "its profile paused: rule 1 restarts it once the pause ends"
