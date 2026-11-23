"""After the switch-over's marker rule 13 reads no lane and no first-shape member, a team's schedule replays nobody and
the page draws no *concluded* (design §4.9e *What decides which shape runs*, TD-2076); before it each runs as it did."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from conftest import park_ticks
from test_ui_teams import badged, client, org_doc, world, write_org  # noqa: F401 — fixtures

from sessionorc import mail, paths, stuck
from sessionorc.client import LocalClient
from sessionorc.models import Session

NOW = datetime(2026, 12, 2, 12, tzinfo=UTC)


def _mark(text: str = "cut_over: 2026-12-01\n") -> None:
    paths.home().mkdir(parents=True, exist_ok=True)
    (paths.home() / "settings.yml").write_text(text)


def _rec(**kw) -> Session:
    base = {"id": "ao-t-w", "name": "w", "kind": "agent", "adapter": "shell", "dir": "/tmp/x", "state": "idle"}
    return Session(**{**base, "team": "g", "unattended": True, "created": "2026-11-20T00:00:00Z", **kw})


@pytest.mark.parametrize(
    ("kw", "cut", "expected"),
    [
        ({}, "2026-12-01", True),
        ({"builtin": "techlead"}, "2026-12-01", False),
        ({"unattended": False}, "2026-12-01", False),
        ({"team": None}, "2026-12-01", False),
        ({"created": "2026-12-01T09:00:00Z"}, "2026-12-01", False),
        ({}, None, False),
    ],
    ids=["member", "built-in", "person's", "no team", "made that day", "no date"],
)
def test_who_is_a_first_shape_record(kw, cut, expected):
    assert stuck.first_shape_record(_rec(**kw), cut) is expected


def test_no_record_is_no_first_shape_record():
    assert stuck.first_shape_record(None, "2026-12-01") is False


@pytest.mark.parametrize("marked", [True, False], ids=["after", "before"])
def test_a_decided_line_names_no_lane_after_the_marker(agent, monkeypatch, marked):
    if marked:
        _mark()
    agent._read_cut_over()
    monkeypatch.setattr(stuck, "lane_records", lambda *a, **k: [])
    order = {"id": "board:abc", "entry": {}}
    got = agent._stuck_order({}, {}, "/r", order, [], NOW - timedelta(hours=3), NOW)
    if marked:
        assert got is None
    else:
        assert got is not None and got[0]["reason"] == {"state": "no_lane"}


def test_a_line_held_by_a_first_shape_member_is_not_reported_after_the_marker(agent):
    _mark()
    agent._read_cut_over()
    r = _rec()
    order = {"id": "board:abc", "entry": {}}
    assert agent._stuck_order({"ao-t-w": r}, {}, "/r", order, ["ao-t-w"], NOW - timedelta(hours=3), NOW) is None


async def test_a_schedule_replays_nobody_after_the_marker(agent, monkeypatch):
    _mark("cut_over: 2026-12-01\nteams:\n  g:\n    schedule: {start: reset, profile: p, window: week}\n")
    agent._read_cut_over()
    spy = AsyncMock()
    monkeypatch.setattr(agent, "_schedule_team", spy)
    await agent._schedules(NOW)
    assert spy.await_count == 0


async def test_a_schedule_is_read_before_the_marker(agent, monkeypatch):
    _mark("teams:\n  g:\n    schedule: {start: reset, profile: p, window: week}\n")
    agent._read_cut_over()
    spy = AsyncMock()
    monkeypatch.setattr(agent, "_schedule_team", spy)
    await agent._schedules(NOW)
    assert spy.await_count == 1


def test_the_marker_date_survives_a_restart_with_an_unreadable_file(agent):
    _mark()
    agent._read_cut_over()
    _mark("cut_over: [unclosed\n")
    again = type(agent)(tmux=agent.tmux)
    assert again._first_shape_off and again._first_shape_cut == "2026-12-01"


def test_the_page_draws_no_concluded_after_the_marker(world, client):  # noqa: F811
    tmp_path, fleet = world
    write_org(tmp_path, org_doc(tmp_path))
    out = {"at": "2026-11-12T08:00:00Z", "why": "nothing pickable"}
    fleet.sessions = [
        {**badged("orc-ao", "ao-grind", state="idle"), "tail": [], "out_of_work": out},
        {**badged("grind-1", "ao-grind", state="idle"), "tail": [], "out_of_work": out},
    ]

    def row() -> dict:
        (got,) = [r for r in client.get("/api/teams").json()["teams"] if r["name"] == "ao-grind"]
        return got

    assert row()["concluded"] is not None
    _mark()
    assert row()["concluded"] is None and row()["not_concluded"] == []


@pytest.mark.integration
@pytest.mark.parametrize(
    ("marked", "builtin", "reported"),
    [(True, None, False), (True, "techlead", True), (False, None, True)],
    ids=["first-shape seat after", "built-in seat after", "first-shape seat before"],
)
async def test_an_open_ask_to_a_first_shape_seat_is_not_reported_after_the_marker(
    agent, tmp_path, marked, builtin, reported
):
    await park_ticks(agent)
    if marked:
        _mark("cut_over: 2099-01-01\n")  # every record here was made before it
    agent._read_cut_over()
    async with LocalClient() as person:

        async def mk(n: str, **kw) -> str:
            d = tmp_path / n
            d.mkdir(exist_ok=True)
            got = await person.call(
                "create", name=n, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], unattended=True, **kw
            )
            return got["id"]

        rv = await mk("rv", team="beta", seat={"trigger": "asks"})
        w = await mk("w", team="beta")
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=rv, text="which test covers this?", kind="ask", about="TD-9")
        mid = got["entry"]["id"]
        agent.sessions[rv].state, agent.sessions[rv].limited_reset = "limited", None
        agent.sessions[rv].builtin = builtin
        await agent._stuck_pass(datetime.now(UTC) + mail.STUCK_ASK_AFTER + timedelta(minutes=1))
        assert (f"ask:{mid}" in (agent._host_rec.get("stuck") or {})) is reported
