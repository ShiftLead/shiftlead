"""After the switch-over's marker the tick's rules for lanes and team members act on nothing (design §4.9e *What decides
which shape runs*, TD-2076), and before it they run as they did."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
import yaml
from conftest import park_ticks

from sessionorc import paths
from sessionorc.models import Session

PER_RECORD = ("_extra_drop", "_scale_down", "_brief_restart", "_cadence_line", "_held_line", "_lane_news")
DETACHED = ("_cadence_pass", "_conventions_pass", "_held_pass", "_brief_pass")


def _mark(text: str = "cut_over: 2026-12-01\n") -> None:
    paths.home().mkdir(parents=True, exist_ok=True)
    (paths.home() / "settings.yml").write_text(text)


def _spied(agent, monkeypatch) -> dict[str, AsyncMock]:
    spies = {n: AsyncMock(return_value=False) for n in (*PER_RECORD, *DETACHED)}
    for name, spy in spies.items():
        monkeypatch.setattr(agent, name, spy)
    for name in ("_join_orders", "_scheduled_start", "_crash_restart", "_extra_hold", "_wanted_restart", "_seat_pass"):
        monkeypatch.setattr(agent, name, AsyncMock())
    for name in ("_sit_out_close", "_idle_nudge", "_idle_open", "_context_line", "_commit_defs", "_count_seats"):
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


async def test_a_settings_file_that_breaks_after_the_marker_keeps_the_rules_off(agent):
    await park_ticks(agent)
    _mark()
    agent._read_cut_over()
    _mark("cut_over: [unclosed\n")
    agent._read_cut_over()
    assert agent._first_shape_off


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
    assert yaml.safe_load((paths.home() / "settings.yml").read_text())["cut_over"]


@pytest.mark.parametrize("name", ["_finished_pass", "_finished_closed_managers", "_scale_pass", "_seat_move"])
async def test_a_team_pass_reads_no_record_after_the_marker(agent, monkeypatch, name):
    await park_ticks(agent)
    _mark()
    agent._read_cut_over()
    monkeypatch.setattr(agent, "_graph", lambda: pytest.fail("the pass read the records after the marker"))
    agent.sessions.clear()
    await getattr(agent, name)(datetime.now(UTC))
