"""TD-133 slice 1, design §6 *Schedule*: a team start at a window's reset. The person's standing press
is `teams.<team>.schedule: {start: reset, profile, window}`; at the window's `resets` in the profile's
reading the home replays the team as rule 8's start does, `why: schedule`, once per reset."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from conftest import park_ticks

from sessionorc import paths
from sessionorc import settings as settings_mod
from sessionorc.agent_common import SCHEDULE_LATE
from sessionorc.agent_tick import NOT_RESTARTS
from sessionorc.models import Session

DECLARED = {"at": "2026-09-28T06:56:00Z", "why": "nothing pickable"}
RULE = {"start": "reset", "profile": "grind", "window": "week"}


def _iso(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rec(name: str, **kw) -> Session:
    base = dict(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="agentshell", dir="/tmp/x", state="closed",
        team="g", unattended=True, supervised=True, out_of_work=DECLARED, lane=["free-pick"], profile="grind",
    )  # fmt: skip
    return Session(**{**base, **kw})


class _Replays:
    """`_replay` stood in for: what the pass would start, in order, with its arguments."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict]] = []

    async def __call__(self, s, why, *, mark=None, **extra):
        self.calls.append((s.name, why, mark or {}, extra))


def _team(agent, *recs: Session) -> None:
    for r in recs:
        r.host = agent.host
        agent.sessions[r.id] = r
        paths.launch_dir().mkdir(parents=True, exist_ok=True)
        (paths.launch_dir() / f"{r.id}.json").write_text(json.dumps({"name": r.id}), encoding="utf-8")


def _reading(agent, resets: datetime | None) -> None:
    w = {"label": "week", "pct": 12}
    if resets is not None:
        w["resets"] = _iso(resets)
    agent._usage["grind"] = {"windows": [w]}


def _rec_of(agent) -> dict:
    return (agent._host_rec.get("teams") or {}).get("g") or {}


async def _setup(agent, monkeypatch, *recs: Session) -> _Replays:
    await park_ticks(agent)
    settings_mod.save({"teams": {"g": {"schedule": RULE, "on_work": "off"}}})
    replays = _Replays()
    monkeypatch.setattr(agent, "_replay", replays)
    _team(agent, *recs)
    return replays


async def test_the_reset_replays_a_wound_down_team_once(agent, monkeypatch):
    replays = await _setup(
        agent, monkeypatch,
        _rec("grinder-ao-1", controllers=["ao-t-manager-ao"]),
        _rec("manager-ao", lane=["TD-900"]),
        _rec("techlead-ao", seat={"trigger": "asks"}, out_of_work=None, controllers=["ao-t-manager-ao"]),
    )  # fmt: skip
    now = datetime.now(UTC)
    reset = now + timedelta(hours=1)
    _reading(agent, reset)
    await agent._schedules(now)
    assert replays.calls == [], "not before the reset"
    assert _rec_of(agent)["schedule_next"] == {**{k: RULE[k] for k in ("profile", "window")}, "at": _iso(reset)}

    # past the reset the reading has already rolled to next week: the remembered instant still fires
    _reading(agent, reset + timedelta(days=7))
    agent._host_rec["teams"]["g"]["work_waiting"] = {"at": "x", "members": {}}
    later = reset + timedelta(minutes=1)
    await agent._schedules(later)
    names = [c[0] for c in replays.calls]
    assert names[0] == "manager-ao" and sorted(names[1:]) == ["grinder-ao-1", "techlead-ao"], "the lead first"
    assert {c[1] for c in replays.calls} == {"schedule"}
    about = replays.calls[0][2]
    assert set(about) == {"start", "of"} and about["of"] == 3 and all(c[2] == about for c in replays.calls)
    assert all(c[3]["keep_mail"] is True for c in replays.calls)
    assert {c[0]: c[3]["held"] for c in replays.calls} == {
        "manager-ao": False,
        "grinder-ao-1": False,
        "techlead-ao": True,
    }
    rec = _rec_of(agent)
    assert rec["schedule_fired"] == _iso(reset) and "work_waiting" not in rec, "a schedule's start clears rule 8's mark"
    assert rec["schedule_next"]["at"] == _iso(reset + timedelta(days=7))
    assert agent.host_store.load()["teams"]["g"]["schedule_fired"] == _iso(reset), "saved, so a restart fires no twice"

    replays.calls.clear()
    await agent._schedules(later + timedelta(minutes=1))
    assert replays.calls == [], "once per reset"


async def test_a_reading_not_rolled_past_its_reset_fires_it(agent, monkeypatch):
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    now = datetime.now(UTC)
    _reading(agent, now - timedelta(minutes=5))
    await agent._schedules(now)
    assert [c[0] for c in replays.calls] == ["grinder-ao-1"]
    assert _rec_of(agent)["schedule_fired"] == _iso(now - timedelta(minutes=5))


async def test_no_reading_no_fire(agent, monkeypatch):
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    now = datetime.now(UTC)
    _reading(agent, None)
    await agent._schedules(now)
    agent._usage.pop("grind")
    await agent._schedules(now)
    assert replays.calls == [] and "schedule_fired" not in _rec_of(agent)


async def test_a_live_or_stopped_team_is_left_alone_and_the_reset_counted(agent, monkeypatch):
    now = datetime.now(UTC)
    past = now - timedelta(minutes=1)
    # anything live at the reset: left alone
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"), _rec("grinder-ao-2", state="working"))
    _reading(agent, past)
    await agent._schedules(now)
    assert replays.calls == [] and _rec_of(agent)["schedule_fired"] == _iso(past)


async def test_a_team_a_person_stopped_is_never_started_by_its_schedule(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1", out_of_work=None))  # closed with nothing declared
    _reading(agent, now - timedelta(minutes=1))
    agent._host_rec.setdefault("teams", {})["g"] = {"work_waiting": {"at": "x", "members": {}, "stopped": True}}
    await agent._schedules(now)
    assert replays.calls == [] and "schedule_fired" in _rec_of(agent), "the reset counts as fired"
    assert "work_waiting" in _rec_of(agent), "nothing started: rule 8's mark (the card's Start row) stands"


async def test_no_launch_record_starts_nothing(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    (paths.launch_dir() / "ao-t-grinder-ao-1.json").unlink()
    _reading(agent, now - timedelta(minutes=1))
    await agent._schedules(now)
    assert replays.calls == [] and "schedule_fired" in _rec_of(agent), "a schedule never invents a team"


async def test_a_cleared_schedule_forgets_its_upcoming_reset(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    _reading(agent, now + timedelta(hours=1))
    await agent._schedules(now)
    assert "schedule_next" in _rec_of(agent)
    settings_mod.save({"teams": {"g": {"on_work": "off"}}})
    await agent._schedules(now + timedelta(hours=2))
    assert replays.calls == [] and "schedule_next" not in _rec_of(agent)


def test_a_schedules_start_is_no_restart_of_rule_9():
    assert "schedule" in NOT_RESTARTS


async def test_a_reset_found_late_is_counted_and_starts_nothing(agent, monkeypatch):
    # a stale reading when the schedule is set, or an agent down across the reset: never an arbitrary hour
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    old = now - SCHEDULE_LATE - timedelta(minutes=5)
    _reading(agent, old)
    await agent._schedules(now)
    assert replays.calls == [] and _rec_of(agent)["schedule_fired"] == _iso(old)


async def test_a_stored_reset_fires_with_the_reading_gone_and_after_a_reload(agent, monkeypatch):
    # the profile's reading is dropped once no session runs under it: the reset read while it ran still fires,
    # from the host record as saved (an agent restart between the read and the reset)
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    reset = now + timedelta(minutes=30)
    _reading(agent, reset)
    await agent._schedules(now)
    agent._usage.pop("grind")
    agent._host_rec = agent.host_store.load()
    await agent._schedules(reset + timedelta(minutes=2))
    assert [c[0] for c in replays.calls] == ["grinder-ao-1"]


async def test_one_reset_spelled_two_ways_fires_once(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    past = (now - timedelta(minutes=3)).replace(microsecond=0)
    agent._usage["grind"] = {"windows": [{"label": "week", "pct": 1, "resets": _iso(past)}]}
    await agent._schedules(now)
    agent._usage["grind"] = {"windows": [{"label": "week", "pct": 1, "resets": past.isoformat()[:19] + ".400+00:00"}]}
    await agent._schedules(now + timedelta(minutes=1))
    assert len(replays.calls) == 1


async def test_a_changed_window_forgets_the_old_ones_reset(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    _reading(agent, now + timedelta(minutes=10))
    await agent._schedules(now)
    settings_mod.save({"teams": {"g": {"schedule": {**RULE, "window": "5h"}, "on_work": "off"}}})
    agent._usage.pop("grind")
    await agent._schedules(now + timedelta(minutes=20))
    assert replays.calls == [], "the stored reset was read for the week, not for 5h"


async def test_a_member_behind_a_down_link_holds_the_reset_to_the_next_tick(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    far = agent.sessions["ao-t-grinder-ao-1"]
    far.host = "far"
    (paths.launch_dir() / f"{agent._address(far)}.json").write_text(json.dumps({"name": far.id}), encoding="utf-8")
    past = now - timedelta(minutes=2)
    _reading(agent, past + timedelta(days=7))  # the reading already rolled
    agent._host_rec.setdefault("teams", {})["g"] = {
        "schedule_next": {"profile": "grind", "window": "week", "at": _iso(past)}
    }
    await agent._schedules(now)
    assert replays.calls == [] and "schedule_fired" not in _rec_of(agent)
    assert _rec_of(agent)["schedule_next"]["at"] == _iso(past), "the same reset, tried again"
    await agent._schedules(now + SCHEDULE_LATE + timedelta(minutes=5))
    assert replays.calls == [] and "schedule_fired" not in _rec_of(agent), "a held reset is never counted late"
    agent._link_muxes["far"] = object()
    await agent._schedules(now + SCHEDULE_LATE + timedelta(minutes=6))
    assert [c[0] for c in replays.calls] == ["grinder-ao-1"] and _rec_of(agent)["schedule_fired"] == _iso(past)


async def test_a_surprise_mid_pass_loses_no_reset(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    past = now - timedelta(minutes=2)
    _reading(agent, past + timedelta(days=7))
    agent._host_rec.setdefault("teams", {})["g"] = {
        "schedule_next": {"profile": "grind", "window": "week", "at": _iso(past)}
    }

    def boom(*a, **k):
        raise RuntimeError("surprise")

    real = agent._work_replays
    monkeypatch.setattr(agent, "_work_replays", boom)
    await agent._schedules(now)
    assert _rec_of(agent)["schedule_next"]["at"] == _iso(past) and "schedule_fired" not in _rec_of(agent)
    monkeypatch.setattr(agent, "_work_replays", real)
    await agent._schedules(now + timedelta(minutes=1))
    assert [c[0] for c in replays.calls] == ["grinder-ao-1"]
