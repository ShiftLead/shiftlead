"""After the cut-over a built-in seat is filled only where design §4.9d *When they run* allows it (TD-2065): a tech
lead's while its team is started and on while that team's sessions finish, a repo's seat while any of the repo's teams
is started, and the tagging seat is the tech lead of the repo's first started team."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from conftest import park_ticks

from sessionorc import paths
from sessionorc.models import Session

SETTINGS = """cut_over: 2026-12-01
teams:
  a: {repo: repo, host: home, flow: build, logins: []}
  b: {repo: repo, host: home, flow: build, logins: []}
  c: {repo: other, host: home, flow: build, logins: []}
"""
STARTED = {"started": {"since": "2026-12-01T09:00:00Z", "by": "person"}}


def _stopped(by: str = "person", at: str = "2026-12-01T10:00:00Z") -> dict:
    return {"stopped": {"at": at, "by": by}}


async def _cut(agent, **marks) -> None:
    await park_ticks(agent)
    paths.home().mkdir(parents=True, exist_ok=True)
    (paths.home() / "settings.yml").write_text(SETTINGS)
    agent._read_cut_over()
    assert agent._first_shape_off
    agent._host_rec["teams"] = marks


def _seat(agent, name: str, builtin: str, team: str = "", trigger: dict | None = None, **kw) -> Session:
    s = Session(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="shell", dir="/tmp/x", state="closed", team=team,
        repo="/tmp/repo", supervised=True, unattended=True, builtin=builtin,
        seat=trigger or {"trigger": "asks", "tags": True}, **kw,
    )  # fmt: skip
    agent.sessions[s.id] = s
    return s


def _member(agent, name: str, team: str, state: str = "working") -> Session:
    s = Session(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="shell", dir="/tmp/x", state=state, team=team,
        repo="/tmp/repo", supervised=True, unattended=True,
    )  # fmt: skip
    agent.sessions[s.id] = s
    return s


async def test_a_tech_lead_runs_while_its_team_is_started(agent):
    await _cut(agent, a=STARTED)
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    assert agent._builtin_hold(lead, [lead]) is None


async def test_a_wound_down_team_s_tech_lead_answers_while_a_session_finishes(agent):
    await _cut(agent, a=_stopped())
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    finishing = _member(agent, "w", "a")
    assert agent._builtin_hold(lead, [lead, finishing]) is None
    finishing.state = "closed"
    assert agent._builtin_hold(lead, [lead, finishing]) == {"at": "2026-12-01T10:00:00Z", "by": "person", "team": "a"}


async def test_another_team_s_session_keeps_no_tech_lead_running(agent):
    await _cut(agent, a=_stopped("until"), b=STARTED)
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    other = _member(agent, "w", "b")
    assert agent._builtin_hold(lead, [lead, other])["by"] == "until"


@pytest.mark.parametrize("key", ["sweeper", "prompts"])
async def test_a_repo_s_seat_runs_while_any_of_its_teams_is_started(agent, key):
    await _cut(agent, a=_stopped(), b=STARTED, c=STARTED)
    seat = _seat(agent, f"{key}-repo", key, trigger={"trigger": "prompt"})
    assert agent._builtin_hold(seat, [seat]) is None
    agent._host_rec["teams"]["b"] = _stopped(at="2026-12-01T11:00:00Z")  # c is another repo's, never this one's
    assert agent._builtin_hold(seat, [seat]) == {"at": "2026-12-01T11:00:00Z", "by": "person", "team": ""}


@pytest.mark.parametrize(("key", "held"), [("prompts", False), ("sweeper", True)])
async def test_only_the_prompts_seat_runs_on_while_a_repo_s_session_finishes(agent, key, held):
    await _cut(agent, a=_stopped(), b=_stopped())
    seat = _seat(agent, f"{key}-repo", key, trigger={"trigger": "prompt"})
    finishing = _member(agent, "w", "b")
    assert (agent._builtin_hold(seat, [seat, finishing]) is not None) is held


async def test_a_held_built_in_seat_is_not_filled_and_carries_its_hold(agent, monkeypatch):
    await _cut(agent, a=_stopped())
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    lead.host = agent.host
    lead.seat_due = {"at": "2026-12-01T10:30:00Z", "by": "asks", "ask": "m-1"}
    monkeypatch.setattr(agent, "_seat_due", lambda s, now, records: s.seat_due)
    fill = AsyncMock()
    monkeypatch.setattr(agent, "_fill", fill)
    await agent._seat_pass(lead, datetime.now(UTC), [lead])
    fill.assert_not_awaited()
    assert lead.stop_held == {"at": "2026-12-01T10:00:00Z", "by": "person", "team": "a"}
    agent._host_rec["teams"]["a"] = STARTED
    await agent._seat_pass(lead, datetime.now(UTC), [lead])
    fill.assert_awaited_once()
    assert lead.stop_held is None


async def test_the_tagging_seat_is_the_first_started_team_s_tech_lead(agent):
    await _cut(agent, a=STARTED, b=STARTED)
    a = _seat(agent, "techlead-a", "techlead", team="a")
    b = _seat(agent, "techlead-b", "techlead", team="b")
    assert a.seat["tags"] and b.seat["tags"]
    assert agent._tagging_seat("/tmp/repo", [a, b]) is a
    agent._host_rec["teams"]["a"] = _stopped()
    assert agent._tagging_seat("/tmp/repo", [a, b]) is b
    agent._host_rec["teams"]["b"] = _stopped()
    assert agent._tagging_seat("/tmp/repo", [a, b]) is None


async def test_a_repo_s_sweeper_record_is_the_repo_s_while_a_team_is_started(agent, monkeypatch):
    from sessionorc import agent_tick

    monkeypatch.setattr(agent_tick.settings_mod, "sweep", lambda _doc: {"on": True, "off": [], "every": "1d"})
    await _cut(agent, b=STARTED)
    sweeper = _seat(agent, "sweeper-repo", "sweeper", trigger={"trigger": "swept", "after": "1d", "by": "settings"})
    assert agent._sweep_idle(sweeper, [sweeper]) == ""
    agent._host_rec["teams"]["b"] = _stopped()
    assert agent._sweep_idle(sweeper, [sweeper]) == "other"
