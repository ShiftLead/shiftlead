"""TD-1091, design §4.9b *The switch*, §6 rule 3 *A switch-made sweep seat*: `sweep:` and
`repos.<repo>.sweep` in `settings.yml`, the `sweep_switch` read, and the tick's choice of the one
switch-made sweeper seat per repo whose `swept` cause is computed."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import identity
from sessionorc import settings as settings_mod
from sessionorc.client import AgentError, LocalClient


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


# ── settings.yml ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_the_switch_reads_off_with_seven_days_when_absent_and_names_each_repo_turned_off():
    assert settings_mod.sweep({}) == {"on": False, "every": "7d", "off": []}
    doc = {
        "sweep": {"on": True, "every": "36h", "profile": "grind"},
        "repos": {"shiftlead": {"sweep": False}, "samscrape": {"sweep": True}, "other": {"pull": False}},
    }
    assert settings_mod.sweep(doc) == {"on": True, "every": "36h", "profile": "grind", "off": ["shiftlead"]}
    # a hand edit that does not parse reads as absent, field by field
    assert settings_mod.sweep({"sweep": {"on": "yes", "every": "1w"}}) == {"on": False, "every": "7d", "off": []}
    for bad in ({"every": "0d"}, {"every": "7"}, {"on": 1}, {"profile": " "}, {"when": "7d"}):
        with pytest.raises(ValueError):
            settings_mod.parse_sweep(bad)
    with pytest.raises(ValueError, match="sweep is on or off"):
        settings_mod.parse_repo({"sweep": "off"})


@pytest.mark.integration
async def test_set_settings_writes_the_switch_and_a_session_reads_it(agent):
    assert "sweep_switch" in identity.READS, "a session's call is served, as `gate` is"
    async with LocalClient() as person:
        got = await person.call("set_settings", sweep={"on": True, "every": "5d", "profile": "grind"})
        assert got["sweep"] == {"on": True, "every": "5d", "profile": "grind", "off": []}
        got = await person.call("set_settings", repos={"shiftlead": {"sweep": False}}, sweep={"profile": None})
        assert got["sweep"] == {"on": True, "every": "5d", "off": ["shiftlead"]}
        assert (await person.call("settings"))["sweep"] == got["sweep"]
        assert await person.call("sweep_switch") == got["sweep"]
        for bad in ({"every": "soon"}, {"when": "7d"}, {}):
            with pytest.raises(AgentError):
                await person.call("set_settings", sweep=bad)
    assert settings_mod.load()["sweep"] == {"on": True, "every": "5d"}


# ── the tick: one filled per repo ──────────────────────────────────────────────────────────────


async def _seat(person, tmp_path, team: str, by: str | None = "settings", after: str = "7d") -> str:
    mark = {"trigger": "swept", "after": after, **({"by": by} if by else {})}
    params = {
        "name": f"sweep-{team}",
        "dir": str(tmp_path),
        "repo": str(tmp_path),
        "adapter": "shell",
        "argv": ["bash", "--norc", "--noprofile"],
        "unattended": True,
        "supervised": True,
        "team": team,
        "prompt": "the sweeper's brief",
        "seat": mark,
    }
    return (await person.call("create", **params))["id"]


def _stamp(agent, tmp_path, at: str | None) -> None:
    board = {"label": tmp_path.name, "root": str(tmp_path), "items": [], "swept": {"at": at, "deep_at": None}}
    agent._repos[str(tmp_path)] = {"boards": {"boards": [board]}}


def _switch(**fields) -> None:
    settings_mod.save({"sweep": {"on": True, **fields}})


@pytest.mark.integration
async def test_only_the_first_live_teams_switch_made_seat_is_due_and_a_stop_hands_it_on(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    _switch()
    async with LocalClient() as person:
        a, b = await _seat(person, tmp_path, "ao-a"), await _seat(person, tmp_path, "ao-b")
        _stamp(agent, tmp_path, None)
        await agent._keep_running(now)
        assert agent.sessions[a].seat_due and agent.sessions[a].seat_due["by"] == "swept"
        assert agent.sessions[b].seat_due is None, "one filled per repo, not one per team"
        await person.call("kill", id=a)  # its team's one live session: the team stopped
        await agent._keep_running(now)
        assert agent.sessions[b].seat_due and agent.sessions[b].seat_due["by"] == "swept", "the next live team's"
        await person.call("kill", id=b)


@pytest.mark.integration
async def test_a_teams_own_sweeper_wins_and_an_off_switch_clears_a_standing_due(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    _switch()
    async with LocalClient() as person:
        a = await _seat(person, tmp_path, "ao-a")
        _stamp(agent, tmp_path, _ago(8))
        await agent._keep_running(now)
        first = agent.sessions[a].seat_due
        assert first and first["by"] == "swept"
        own = await _seat(person, tmp_path, "ao-own", by=None)
        await agent._keep_running(now)
        assert agent.sessions[a].seat_due is None, "a live team's own sweeper: no switch-made seat is due"
        assert agent.sessions[own].seat_due and agent.sessions[own].seat_due["by"] == "swept"
        await person.call("kill", id=own)
        await agent._keep_running(now)
        assert agent.sessions[a].seat_due, "due again once the team's own sweeper's team stopped"
        settings_mod.save({"sweep": {"on": False}})
        await agent._keep_running(now)
        assert agent.sessions[a].seat_due is None, "the switch turned off clears the standing due"
        settings_mod.save({"sweep": {"on": True}, "repos": {tmp_path.name: {"sweep": False}}})
        await agent._keep_running(now)
        assert agent.sessions[a].seat_due is None, "the repo turned off"
        await person.call("kill", id=a)


@pytest.mark.integration
async def test_the_switch_made_seats_duration_is_the_switchs_every_at_the_next_tick(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    _switch(every="7d")
    async with LocalClient() as person:
        a = await _seat(person, tmp_path, "ao-a", after="7d")
        _stamp(agent, tmp_path, _ago(4))
        await agent._keep_running(now)
        assert agent.sessions[a].seat_due is None, "4 days old under 7d"
        _switch(every="3d")
        await agent._keep_running(now)
        assert agent.sessions[a].seat_due and agent.sessions[a].seat_due["by"] == "swept", "not the mark's 7d"
        await person.call("kill", id=a)


# ── what the cards and the Settings page say (slice 2) ─────────────────────────────────────────


@pytest.mark.integration
async def test_the_tick_records_why_a_switch_made_seat_is_held_back(agent, tmp_path):
    """§4.9b *What a sweep seat's card says*: the seat the tick holds back carries why, in `seat_count`
    — `other` while another team's seat sweeps the repo, `off` with the switch off — and loses it once
    it is the repo's again."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    _switch()
    async with LocalClient() as person:
        a, b = await _seat(person, tmp_path, "ao-a"), await _seat(person, tmp_path, "ao-b")
        _stamp(agent, tmp_path, None)
        await agent._keep_running(now)
        assert agent.sessions[a].seat_count is None and agent.sessions[b].seat_count == {"swept": "other"}
        settings_mod.save({"sweep": {"on": False}})
        await agent._keep_running(now)
        assert agent.sessions[a].seat_count == {"swept": "off"} == agent.sessions[b].seat_count
        _switch()
        await person.call("kill", id=a)
        await agent._keep_running(now)
        assert agent.sessions[b].seat_count is None, "the repo's seat again: nothing to say"
        await person.call("kill", id=b)


@pytest.mark.unit
def test_a_switch_made_seats_card_says_another_team_sweeps_or_off(tmp_path):
    from shiftlead.ui.cards import view

    rec = {
        "id": "ao-sweep",
        "name": "sweep-ao-b",
        "state": "closed",
        "repo": str(tmp_path / "shiftlead"),
        "seat": {"trigger": "swept", "after": "7d", "by": "settings"},
    }
    seats = {"ao-sweep": "sweeps when unswept 7 d"}

    def text(why):
        return view({**rec, "seat_count": {"swept": why} if why else None}, seats=seats)["slot"]["text"]

    assert text(None) == "on call — sweeps when unswept 7 d"
    assert text("other") == "on call — another team's seat sweeps shiftlead"
    assert text("off") == "off — the sweep switch is off for shiftlead"


@pytest.mark.unit
def test_the_sweep_cards_line_per_repo_says_what_sweeps_it(tmp_path):
    from shiftlead.ui import settings_page as setmod

    roots = {n: tmp_path / n for n in ("a", "b", "c", "d", "e")}
    for r in roots.values():
        r.mkdir()

    def rec(name, repo, team, **kw):
        return {
            "id": name,
            "name": name,
            "repo": str(roots[repo]),
            "team": team,
            "unattended": True,
            "state": "idle",
            **kw,
        }

    made, own = {"trigger": "swept", "after": "7d", "by": "settings"}, {"trigger": "swept", "after": "7d"}
    fleet = [
        rec("w-a", "a", "ao-a"),
        rec("sweep-ao-a", "a", "ao-a", state="closed", seat=made),
        rec("sweep-ao-x", "a", "ao-x", state="closed", seat=made, seat_count={"swept": "other"}),
        rec("w-b", "b", "ao-b"),
        rec("sweep-1", "b", "ao-b", state="closed", seat=own),
        rec("w-c", "c", "ao-c"),
        rec("old", "e", "gone", state="closed", seat=made),  # a stopped team: nothing of it counts
    ]
    board = {"root": str(roots["a"]), "label": "a", "items": [], "swept": {"at": _ago(3), "deep_at": None}}
    readings = {str(roots["a"]): {"boards": {"boards": [board]}}}
    switch = {"on": True, "every": "7d", "off": ["d"]}
    card = setmod.sweep_card(switch, [str(p) for p in roots.values()], fleet, readings, {"grind": 1, "paul": 2})
    assert [(line["name"], line["on"], line["what"]) for line in card["lines"]] == [
        ("a", True, "sweep-ao-a (ao-a) · swept 3 d ago"),
        ("b", True, "the team's own sweep-1"),
        ("c", True, "ao-c running: its seat comes at its next start"),
        ("d", False, "off"),
        ("e", True, "no team"),
    ]
    assert card["read"] and card["on"] and card["every"] == "" and card["profiles"] == ["grind", "paul"]
    board["swept"] = {"at": None, "deep_at": None}
    readings[str(roots["e"])] = {"boards": {"boards": [{**board, "root": str(roots["e"])}]}}
    off = setmod.sweep_card(
        {"on": False, "every": "3d", "off": []}, [str(roots["e"]), str(roots["c"])], fleet, readings, {}
    )
    assert [line["what"] for line in off["lines"]] == ["no team: never swept", "the switch is off"]
    assert off["every"] == "3d" and not off["on"]
    assert not setmod.sweep_card(None, [], [], {}, {})["read"], "an older agent: no card"


def test_the_sweep_card_saves_the_switch_and_each_repos_line(subprocess_agent):
    from fastapi.testclient import TestClient

    from sessionorc.client import call_sync
    from shiftlead.ui.app import create_app

    with TestClient(create_app()) as client:
        page = client.get("/settings").text
        assert 'id="setsweep"' in page and "a team gets its seat at its next start" in page
        assert "profile holds from each team's next start" in page and ">the role's</option>" in page
        ok = client.post("/api/settings/sweep", json={"on": True, "every": "5d", "profile": ""})
        assert ok.status_code == 200 and ok.json()["sweep"] == {"on": True, "every": "5d", "off": []}
        bad = client.post("/api/settings/sweep", json={"on": True, "every": "soon"})
        assert bad.status_code == 400 and "duration" in bad.json()["detail"]
        assert client.post("/api/settings/sweep", json={"every": "5d"}).status_code == 400
        assert client.post("/api/settings/repos", json={"repo": "shiftlead", "sweep": False}).json()["ok"]
        assert call_sync("sweep_switch") == {"on": True, "every": "5d", "off": ["shiftlead"]}
        assert client.post("/api/settings/repos", json={"repo": "shiftlead", "sweep": "off"}).status_code == 400
        assert client.post("/api/settings/sweep", json={"on": False, "every": ""}).json()["sweep"]["every"] == "7d"
