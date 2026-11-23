"""After the switch-over's marker the tick's rules for lanes and team members act on nothing (design §4.9e *What decides
which shape runs*, TD-2076), and before it they run as they did."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import park_ticks

from sessionorc import paths
from sessionorc.agent_common import RpcError
from sessionorc.client import LocalClient
from sessionorc.models import Session

PER_RECORD = (
    "_extra_drop",
    "_scale_down",
    "_crash_restart",
    "_extra_hold",
    "_wanted_restart",
    "_seat_pass",
    "_sit_out_close",
    "_brief_restart",
    "_idle_nudge",
    "_idle_open",
    "_context_line",
    "_cadence_line",
    "_held_line",
    "_lane_news",
)
KEPT_FOR_A_SEAT = ("_crash_restart", "_seat_pass", "_sit_out_close", "_idle_nudge", "_idle_open", "_context_line")
DETACHED = ("_cadence_pass", "_conventions_pass", "_held_pass", "_brief_pass")


def _mark(text: str = "cut_over: 2026-12-01\n") -> None:
    paths.home().mkdir(parents=True, exist_ok=True)
    (paths.home() / "settings.yml").write_text(text)


def _spied(agent, monkeypatch) -> dict[str, AsyncMock]:
    spies = {n: AsyncMock(return_value=False) for n in (*PER_RECORD, *DETACHED)}
    for name, spy in spies.items():
        monkeypatch.setattr(agent, name, spy)
    for name in ("_join_orders", "_scheduled_start", "_commit_defs", "_count_seats"):
        monkeypatch.setattr(agent, name, AsyncMock())
    monkeypatch.setattr(agent, "_lost_brief", AsyncMock(return_value=False))
    agent.sessions["ao-t-w"] = Session(
        id="ao-t-w", name="w", kind="interactive", adapter="shell", dir="/tmp/x", state="idle", team="g"
    )  # fmt: skip
    return spies


async def _keep_running(agent) -> None:
    await park_ticks(agent)
    agent._read_cut_over()
    long_ago = datetime(2020, 1, 1, tzinfo=UTC)  # every detached reading is due, so one that stays off is the marker's
    agent._cadence_read_at = agent._conventions_read_at = agent._held_read_at = agent._brief_read_at = long_ago
    await agent._keep_running(datetime.now(UTC))
    for task in (agent._cadence_task, agent._conventions_task, agent._held_task, agent._brief_task):
        if task is not None:
            await task


@pytest.mark.parametrize("marked", [True, False], ids=["after", "before"])
async def test_the_member_and_lane_rules_follow_the_marker(agent, monkeypatch, marked):
    spies = _spied(agent, monkeypatch)
    if marked:
        _mark()
    await _keep_running(agent)
    for name, spy in spies.items():
        assert spy.await_count == (0 if marked else 1), name
    assert agent._lost_brief.await_count == (0 if marked else 1)


@pytest.mark.parametrize(
    "mark",
    [{"builtin": "techlead", "seat": {"trigger": "asks"}}, {"seat": {"trigger": "prompt"}}],
    ids=["built-in", "director"],
)
async def test_rules_1_3_4_and_5_still_reach_a_built_in_seat_and_the_director(agent, monkeypatch, mark):
    spies = _spied(agent, monkeypatch)
    for k, v in mark.items():
        setattr(agent.sessions["ao-t-w"], k, v)
    _mark()
    await _keep_running(agent)
    for name, spy in spies.items():
        assert spy.await_count == (1 if name in KEPT_FOR_A_SEAT else 0), name
    assert agent._lost_brief.await_count == 1


async def test_a_first_shape_seat_is_not_read_by_rule_3_after_the_marker(agent, monkeypatch):
    spies = _spied(agent, monkeypatch)
    agent.sessions["ao-t-w"].seat = {"trigger": "asks"}
    agent.unfillable["ao-t-w"] = "paused"
    _mark()
    await _keep_running(agent)
    assert spies["_seat_pass"].await_count == 0
    assert "ao-t-w" not in agent.unfillable


async def test_a_member_s_idle_open_goes_at_the_marker(agent, monkeypatch):
    _spied(agent, monkeypatch)
    agent.sessions["ao-t-w"].idle_open = {"at": "2026-11-23T00:00:00Z", "ref": "TD-1"}
    _mark()
    await _keep_running(agent)
    assert agent.sessions["ao-t-w"].idle_open is None


@pytest.mark.parametrize("marked", [True, False], ids=["after", "before"])
async def test_a_restart_from_a_stage_s_session_is_refused_after_the_marker(agent, monkeypatch, marked):
    await park_ticks(agent)
    if marked:
        _mark()
    agent._read_cut_over()
    s = Session(
        id="ao-t-s", name="s", kind="interactive", adapter="shell", dir="/tmp/x", state="idle", team="g", lane=["TD-7"]
    )  # fmt: skip
    agent.sessions[s.id] = s
    monkeypatch.setattr(agent, "_is_self", lambda *_: True)
    if marked:
        with pytest.raises(RpcError, match="a stage's session ends its stage"):
            await agent.rpc_progress(s.id, status="restart", why="context bound", caller="x")
        assert s.restart_wanted is None
    else:
        await agent.rpc_progress(s.id, status="restart", why="context bound", caller="x")
        assert s.restart_wanted


@pytest.mark.parametrize(
    "mark",
    [{"builtin": "techlead", "seat": {"trigger": "asks"}}, {"seat": {"trigger": "prompt"}}],
    ids=["built-in", "director"],
)
async def test_a_restart_from_a_built_in_seat_or_the_director_is_not_refused(agent, monkeypatch, mark):
    await park_ticks(agent)
    _mark()
    agent._read_cut_over()
    s = Session(
        id="ao-t-s", name="s", kind="interactive", adapter="shell", dir="/tmp/x", state="idle", team="g", lane=["TD-7"]
    )  # fmt: skip
    for k, v in mark.items():
        setattr(s, k, v)
    agent.sessions[s.id] = s
    monkeypatch.setattr(agent, "_is_self", lambda *_: True)
    await agent.rpc_progress(s.id, status="restart", why="context bound", caller="x")
    assert s.restart_wanted


async def test_a_settings_file_that_breaks_after_the_marker_keeps_the_rules_off(agent):
    await park_ticks(agent)
    _mark()
    agent._read_cut_over()
    _mark("cut_over: [unclosed\n")
    agent._read_cut_over()
    assert agent._first_shape_off


async def test_a_new_agent_on_a_broken_file_keeps_the_rules_off(agent):
    await park_ticks(agent)
    _mark()
    agent._read_cut_over()
    _mark("cut_over: [unclosed\n")
    again = type(agent)(tmux=agent.tmux)  # the restart: nothing of the first run's memory, before its first tick
    assert again._first_shape_off


async def test_a_marker_taken_away_is_remembered_as_gone(agent):
    await park_ticks(agent)
    _mark()
    agent._read_cut_over()
    _mark("{}\n")
    agent._read_cut_over()
    assert not agent._first_shape_off
    _mark("cut_over: [unclosed\n")
    assert not type(agent)(tmux=agent.tmux)._first_shape_off


async def test_the_wound_down_marks_go_at_the_marker_and_none_is_written(agent, monkeypatch):
    await park_ticks(agent)
    agent._host_rec["teams"] = {
        "g": {"work_waiting": {"members": {"w": ["TD-1"]}}},
        "h": {"other": 1, "work_waiting": {}},
    }
    monkeypatch.setattr(agent, "_work_mark", lambda *a, **k: pytest.fail("rule 8 read a lane after the marker"))
    _mark()
    agent._read_cut_over()
    await agent._work_marks(datetime.now(UTC))
    assert agent._host_rec["teams"] == {"h": {"other": 1}}


@pytest.mark.parametrize("name", ["_finished_pass", "_finished_closed_managers", "_seat_move"])
async def test_a_team_pass_reads_no_record_after_the_marker(agent, monkeypatch, name):
    await park_ticks(agent)
    _mark()
    agent._read_cut_over()
    monkeypatch.setattr(agent, "_graph", lambda: pytest.fail("the pass read the records after the marker"))
    agent.sessions.clear()
    await getattr(agent, name)(datetime.now(UTC))


@pytest.mark.parametrize("marked", [True, False], ids=["after", "before"])
async def test_no_line_scales_after_the_marker(agent, monkeypatch, marked):
    await park_ticks(agent)
    if marked:
        _mark()
    agent._read_cut_over()
    agent.sessions["ao-t-w"] = Session(
        id="ao-t-w", name="w", kind="interactive", adapter="shell", dir="/tmp/x", state="idle", team="g"
    )  # fmt: skip
    monkeypatch.setattr("sessionorc.agent_scale._scale_line", lambda r: "w")
    spy = AsyncMock()
    monkeypatch.setattr(agent, "_scale_line_pass", spy)
    await agent._scale_pass(datetime.now(UTC))
    assert spy.await_count == (0 if marked else 1)


async def test_a_question_that_ends_after_the_marker_writes_no_work_mark(agent, monkeypatch):
    await park_ticks(agent)
    _mark()
    agent._read_cut_over()
    monkeypatch.setattr(agent, "_graph", lambda: pytest.fail("rule 8 read the team after the marker"))
    orphaned = {"team": "g", "name": "w", "ref": "TD-1", "repo": "r"}
    agent._question_end(SimpleNamespace(id="m-1", kind="ask", orphaned=orphaned), "lapsed")
    assert "work_waiting" not in (agent._host_rec.get("teams") or {}).get("g", {})


async def test_a_press_of_start_after_the_marker_starts_nobody(agent, monkeypatch):
    await park_ticks(agent)
    _mark()
    agent._read_cut_over()
    agent._host_rec["teams"] = {"g": {"work_waiting": {"members": {"w": ["TD-1"]}}}}
    monkeypatch.setattr(agent, "_work_start", AsyncMock(side_effect=AssertionError("started a team after the marker")))
    got = await agent.rpc_work_start(team="g")
    assert got == {"team": "g", "started": False, "ids": [], "held": None}


@pytest.mark.parametrize("why", ["crash", "seat_due"])
async def test_a_built_in_seat_keeps_its_mark_across_a_replay(agent, tmp_path, why):
    await park_ticks(agent)
    async with LocalClient() as person:
        made = await person.call(
            "create",
            name="lead",
            dir=str(tmp_path),
            adapter="shell",
            unattended=True,
            supervised=True,
            seat={"trigger": "asks"},
            builtin="techlead",
        )
        sid = made["id"]
        assert agent._read_launch(sid)["builtin"] == "techlead"
        _mark()
        agent._read_cut_over()
        agent.sessions[sid].set_state("exited", confidence="hook")
        await agent._replay(agent.sessions[sid], why, keep_mail=True)
        assert agent.sessions[sid].builtin == "techlead"
        assert agent._rules_reach(agent.sessions[sid])
        await person.call("kill", id=sid)
