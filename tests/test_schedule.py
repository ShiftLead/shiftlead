"""TD-133 slice 1, design §6 *Schedule*: a team start at a window's reset. The person's standing press
is `teams.<team>.schedule: {start: reset, profile, window}`; at the window's `resets` in the profile's
reading the home replays the team as rule 8's start does, `why: schedule`, once per reset."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from conftest import park_ticks

from sessionorc import paths
from sessionorc import settings as settings_mod
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
    await agent._schedules(now)
    assert replays.calls == []


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
