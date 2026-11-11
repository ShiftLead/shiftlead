"""TD-1574 slice 1, design §6 rule 3 *A stopped team's seats are held* (TD-1564): `work.seats_held_by` reads a
team's last end, rule 3's own seat closes left out; `work.held_for` is the one predicate; the tick's every pass
over a held seat writes `stop_held`, fills it for no cause, gives it no `unfillable` word, keeps its `seat_due`,
and clears the mark once the hold lifts or the seat is suspended."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import work
from sessionorc.agent_common import FINISHED_SETTLE
from sessionorc.client import LocalClient
from sessionorc.models import Session

T0 = datetime(2026, 11, 10, 18, 0, tzinfo=UTC)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _rec(name: str, team: str = "g", **kw) -> Session:
    base = dict(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="shell", dir="/tmp/x", state="exited",
        team=team, unattended=True, supervised=True, pane=False, lane=["free-pick"],
    )  # fmt: skip
    return Session(**{**base, **kw})


def _seat(name: str = "tl", **kw) -> Session:
    return _rec(name, seat={"trigger": "asks"}, lane=[], **kw)


def _killed(by: str, at: datetime, why: str | None = None) -> dict:
    return {"how": "kill", "at": _iso(at), "by": by, **({"why": why} if why else {})}


def _seat_closed(at: datetime) -> dict:
    """Rule 3's own close of an idle seat between questions: no `ended`, `closer.why` `seat`."""
    return {"closer": {"by": "tick", "why": "seat", "at": _iso(at)}, "state": "closed"}


# -- the reading ---------------------------------------------------------------------------------------------


def test_the_persons_stop_close_or_kill_and_a_wind_down_left_undeclared_hold_and_the_stop_time_too():
    stop = [_rec("m", ended=_killed("person", T0)), _seat(ended=_killed("person", T0))]
    assert work.seats_held_by(stop) == {"by": "person", "at": T0.isoformat()}
    close = [_rec("m", closer={"by": "person", "at": _iso(T0)}, state="closed"), _seat()]
    assert work.seats_held_by(close)["by"] == "person"
    wind = [_rec("m", ended={"how": "tool", "at": _iso(T0)}, wrapup_by="person", wrapup_at=_iso(T0))]
    assert work.seats_held_by([*wind, _seat()])["by"] == "person", "a Wind down left undeclared is the person's"
    clock = [_rec("m", ended=_killed("tick", T0, "stop time")), _seat(ended=_killed("tick", T0, "stop time"))]
    assert work.seats_held_by(clock) == {"by": "until", "at": T0.isoformat()}


def test_a_crash_a_sessions_kill_a_finish_and_a_team_of_seat_closes_alone_hold_nothing():
    crash = [_rec("m", ended={"how": "pane", "at": _iso(T0), "code": 1}), _seat()]
    assert work.seats_held_by(crash) is None
    by_session = [_rec("m", ended=_killed("ao-t-boss", T0)), _seat()]
    assert work.seats_held_by(by_session) is None
    finished = [_rec("m", closer={"by": "tick", "why": "finished", "at": _iso(T0)}, state="closed"), _seat()]
    assert work.seats_held_by(finished) is None
    alone = [_seat("tl", **_seat_closed(T0)), _seat("fc", **_seat_closed(T0 + timedelta(minutes=3)))]
    assert work.seats_held_by(alone) is None, "a team of seats alone between questions is filled as ever"
    assert work.stopped_by(alone) == {"by": "other", "at": (T0 + timedelta(minutes=3)).isoformat()}, (
        "its `at` stays the newest end, seat closes included, so its stopped.at is not blank"
    )


def test_a_live_or_scheduled_member_holds_nothing():
    stop = [_rec("m", ended=_killed("person", T0)), _seat(ended=_killed("person", T0))]
    assert work.seats_held_by([*stop, _rec("w", state="idle")]) is None
    assert work.seats_held_by([*stop, _rec("w", state="scheduled")]) is None, "a start time's member is live"
    assert work.seats_held_by([]) is None


def test_a_seat_closed_by_rule_three_after_a_wind_down_keeps_the_persons_word():
    wind = _rec("m", ended={"how": "tool", "at": _iso(T0)}, wrapup_by="person", wrapup_at=_iso(T0))
    later = _seat(**_seat_closed(T0 + timedelta(minutes=20)))
    assert T0 + timedelta(minutes=20) - T0 > FINISHED_SETTLE
    assert work.seats_held_by([wind, later]) == {"by": "person", "at": T0.isoformat()}
    assert work.stopped_by([wind, later]) == {"by": "person", "at": (T0 + timedelta(minutes=20)).isoformat()}, (
        "rule 8's word reads the same as the hold; its `at` the newest end"
    )


def test_the_person_closing_a_wound_down_teams_seat_holds_it():
    out = {"at": _iso(T0), "why": "nothing pickable"}
    done = _rec("m", out_of_work=out, closer={"by": "tick", "why": "finished", "at": _iso(T0)}, state="closed")
    seat = _seat(closer={"by": "person", "at": _iso(T0 + timedelta(hours=1))}, state="closed")
    assert work.team_wound_down([done, seat]) is not None
    assert work.seats_held_by([done, seat])["by"] == "person", "it reads ends, not whether the team wound down"


def test_the_person_closing_one_member_within_the_settle_of_the_rest_finishing_holds():
    fin = _rec("a", closer={"by": "tick", "why": "finished", "at": _iso(T0)}, state="closed")
    mine = _rec("b", closer={"by": "person", "at": _iso(T0 + timedelta(seconds=30))}, state="closed")
    assert work.seats_held_by([fin, mine, _seat()])["by"] == "person"


def test_held_for_is_a_supervised_unattended_current_seat_of_a_held_team():
    member = _rec("m", ended=_killed("person", T0))
    seat = _seat(ended=_killed("person", T0))
    assert work.held_for(seat, [member, seat])
    assert not work.held_for(member, [member, seat]), "a member is no seat"
    for bad in ({"team": None}, {"supervised": False}, {"unattended": False}, {"suspended": {"at": _iso(T0)}},
                {"sit_out": {"at": _iso(T0)}}, {"superseded_by": "ao-t-tl2"}):  # fmt: skip
        other = _seat(ended=_killed("person", T0), **bad)
        assert not work.held_for(other, [member, other]), bad
    # every team's records may be passed: the seat's own team is read
    elsewhere = _rec("x", team="h", state="idle")
    assert work.held_for(seat, [member, seat, elsewhere])
    assert not work.held_for(seat, [member, seat, _rec("w", state="idle")])


def test_an_old_seat_held_mark_loads_and_holds_nothing():
    rec = Session.from_dict({**_seat().to_dict(), "seat_held": {"by": "checkout", "why": "branch td-x"}})
    assert not hasattr(rec, "seat_held") and rec.stop_held is None


# -- the tick's pass -------------------------------------------------------------------------------------------


async def _team(person, tmp_path, team: str = "g") -> tuple[str, str]:
    """An `asks` seat and one member of `team`, as `ao team start` writes them."""
    common = {"dir": str(tmp_path), "adapter": "shell", "argv": ["bash", "--norc", "--noprofile"],
              "unattended": True, "supervised": True, "team": team, "repo": str(tmp_path)}  # fmt: skip
    seat = (await person.call("create", name=f"tl-{team}", prompt="b", seat={"trigger": "asks"}, **common))["id"]
    member = (await person.call("create", name=f"w-{team}", **common))["id"]
    return seat, member


def _stop(agent, sid: str, at: datetime, by: str = "person") -> None:
    rec = agent.sessions[sid]
    rec.state, rec.pane, rec.ended = "exited", False, _killed(by, at, "stop time" if by == "tick" else None)
    agent.store.save(rec)


async def test_a_held_seat_fills_for_no_cause_takes_no_unfillable_word_and_carries_stop_held(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        seat, member = await _team(person, tmp_path)
        _stop(agent, member, now - timedelta(minutes=2))
        _stop(agent, seat, now - timedelta(minutes=2))
        rec = agent.sessions[seat]
        rec.asks_ids = lambda **kw: ["m-q1"]
        agent._profile_gated = lambda *a: True  # a gated profile would say `gated`: a held seat says nothing
        await agent._keep_running(now)
        assert agent.sessions[seat] is rec, "not filled"
        assert rec.seat_due and rec.seat_due["by"] == "asks", "its seat_due stands"
        assert rec.stop_held == {"at": rec.stop_held["at"], "by": "person", "team": "g"}
        assert seat not in agent.unfillable, "no unfillable word: its questions land and wait"
        del agent._profile_gated
        await agent._keep_running(now + timedelta(hours=2))
        assert agent.sessions[seat] is rec, "still not filled, ungated"
        # suspended: it keeps its own word and loses the hold's
        rec.suspended = {"at": _iso(now), "by": "person"}
        await agent._keep_running(now)
        assert rec.stop_held is None and agent.unfillable.get(seat) == "suspended"
        rec.suspended = None
        await agent._keep_running(now)
        assert rec.stop_held and rec.stop_held["by"] == "person"
        await person.call("kill", id=seat)


async def test_the_stop_time_holds_until_and_a_live_member_lifts_it_and_the_seat_fills(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        seat, member = await _team(person, tmp_path)
        _stop(agent, member, now, by="tick")
        _stop(agent, seat, now, by="tick")
        rec = agent.sessions[seat]
        rec.asks_ids = lambda **kw: ["m-q1"]
        await agent._keep_running(now)
        assert rec.stop_held["by"] == "until" and agent.sessions[seat] is rec
        # the person's Restart (or a Start) makes the crew live: the hold lifts and the seat fills on its cause
        agent.sessions[member].state = "idle"
        await agent._keep_running(now)
        assert rec.stop_held is None
        new = agent.sessions[seat]
        assert new is not rec and new.stop_held is None, "filled; the fresh record carries no stop_held"
        await person.call("kill", id=seat)
        await person.call("kill", id=member)


async def test_a_seat_with_no_team_and_a_team_ended_by_a_crash_are_filled_as_ever(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        seat, member = await _team(person, tmp_path)
        _stop(agent, member, now, by="ao-other-session")
        _stop(agent, seat, now, by="ao-other-session")
        rec = agent.sessions[seat]
        rec.asks_ids = lambda **kw: ["m-q1"]
        await agent._keep_running(now)
        assert rec.stop_held is None and agent.sessions[seat] is not rec, "a session's kill is no stop: filled"
        await person.call("kill", id=seat)
        lone = (
            await person.call(
                "create", name="lone", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc", "--noprofile"],
                unattended=True, supervised=True, prompt="b", seat={"trigger": "asks"},
            )
        )["id"]  # fmt: skip
        _stop(agent, lone, now)
        one = agent.sessions[lone]
        one.asks_ids = lambda **kw: ["m-q1"]
        await agent._keep_running(now)
        assert one.stop_held is None and agent.sessions[lone] is not one, "a seat with no team is never held"
        await person.call("kill", id=lone)


@pytest.mark.parametrize("trigger", ["every", "prs"])
async def test_a_held_seat_on_any_trigger_is_not_filled(agent, tmp_path, trigger):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        seat, member = await _team(person, tmp_path)
        rec = agent.sessions[seat]
        rec.seat = {"trigger": trigger, "after": "1h" if trigger == "every" else "1"}
        rec.seat_due = {"at": _iso(now), "by": trigger}
        _stop(agent, member, now)
        _stop(agent, seat, now)
        await agent._keep_running(now + timedelta(hours=3))
        assert agent.sessions[seat] is rec and rec.stop_held and rec.seat_due, trigger
        await person.call("kill", id=seat)
