"""Rule 14's up half (design §6 rule 14 *Scale with the work*, §4.9 *Scaling with the work*; td-max, TD-1546 slice 1):
a worker line whose every live member holds a lease, its lane holding a pickable entry nobody holds, fills its
lowest-placed held extra at the event that made it short — an entry becoming pickable, a member's claim — never on a
timer; one guard holds a second fill until the first claims, closes or sticks ten minutes; and the balance mark, a
gated profile, an unstaffed line, a wind-down and the host cap hold a fill back, the cap's written *stopped*."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks
from test_anchor_retired import _shell

from sessionorc.agent_common import SCALE_STEP
from sessionorc.client import LocalClient
from sessionorc.models import ProgressEntry

pytestmark = pytest.mark.integration

TEAM, LINE = "t", "grind"


def _e(i: str) -> dict:
    return {"id": i, "title": i, "owner": "grinder", "kind": "build", "pickable": "yes", "for_page": "pickable"}


async def _line(agent, person, tmp_path, members: int = 2, extras: int = 2, ids=("TD-1", "TD-2")):
    """A team's worker line: `members` kept members each holding a lease on one of `ids` in turn, `extras` held
    extras past them, and the repo's ledger reading holding `ids`."""
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    kw = {"team": TEAM, "lane": ["free-pick"]}
    made = []
    for k in range(1, members + extras + 1):
        name = f"{LINE}-{k}"
        extra = {"held": True, "scale": {"line": LINE}} if k > members else {}
        sid = (await person.call("create", **_shell(tmp_path, name, **kw, **extra)))["id"]
        rec = agent.sessions[sid]
        rec.repo = str(repo)
        if k <= members and k <= len(ids):
            rec.progress = [ProgressEntry(ref=ids[k - 1])]
        made.append(rec)
    agent._repos[str(repo)] = {"name": "r", "root": str(repo), "ledger": {"entries": [_e(i) for i in ids]}}
    return repo, made


def _entries(agent, repo, *ids: str) -> None:
    agent._repos[str(repo)]["ledger"]["entries"] += [_e(i) for i in ids]


def _rec(agent, name: str):
    return next(r for r in agent.sessions.values() if r.name == name and not r.superseded_by)


def _live(agent, name: str) -> bool:
    return _rec(agent, name).state not in ("exited", "closed")


async def _pass(agent, at: datetime | None = None) -> None:
    await agent._scale_pass(at or datetime.now(UTC))


async def test_an_entry_becoming_pickable_with_every_member_leased_fills_exactly_one_extra(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        await _pass(agent)  # the first reading is a baseline: nothing pickable nobody holds, nothing filled
        assert not _live(agent, "grind-3")
        _entries(agent, repo, "TD-3", "TD-4")
        await _pass(agent)
        assert _live(agent, "grind-3") and not _live(agent, "grind-4"), "the lowest-placed, and one"
        got = _rec(agent, "grind-3")
        assert got.scale["line"] == LINE
        assert got.scale["last"]["did"] == "fill"
        assert got.scale["last"]["why"] == "filled: 2 pickable, every grind claimed"
        assert got.restarts[-1]["why"] == "fill"
        await _pass(agent)  # the filled extra holds no lease: free, so the line is not short
        assert not _live(agent, "grind-4")


async def test_no_event_no_fill_and_a_free_member_means_no_fill(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path, ids=("TD-1", "TD-2", "TD-3"))
        await _pass(agent)
        await _pass(agent)
        assert not _live(agent, "grind-3"), "a backlog standing since the baseline is no event"
        made[1].progress = []  # grind-2 between items: free, it picks
        _entries(agent, repo, "TD-4")
        await _pass(agent)
        assert not _live(agent, "grind-3")


async def test_a_members_claim_with_pickable_work_left_fills(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        _, made = await _line(agent, person, tmp_path, ids=("TD-1", "TD-2", "TD-3", "TD-4"))
        made[1].progress = []
        await _pass(agent)  # grind-2 is free: not short
        assert not _live(agent, "grind-3")
        await person.call("progress", id=made[1].id, ref="TD-2")
        await _pass(agent)  # the claim is the event; TD-3 and TD-4 are left
        assert _live(agent, "grind-3") and not _live(agent, "grind-4")


async def test_a_line_whose_free_members_are_limited_or_gated_is_short(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path, members=3, ids=("TD-1",))
        made[1].state, made[1].progress = "limited", []
        made[2].gated, made[2].progress = {"since": "2026-11-11T00:00:00Z"}, []
        await _pass(agent)
        _entries(agent, repo, "TD-9")
        await _pass(agent)
        assert _live(agent, "grind-4")


async def test_a_member_awaiting_rule_1s_restart_means_no_fill(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path)
        await _pass(agent)
        made[1].state, made[1].pane, made[1].progress = "exited", True, []
        assert agent._crashed(made[1], datetime.now(UTC))
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        assert not _live(agent, "grind-3"), "it picks on its return"


async def test_no_second_fill_until_the_first_claims(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        await _pass(agent)
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        first = _rec(agent, "grind-3")
        first.state = "limited"  # cannot pick and holds no lease: the line reads short, the guard holds it
        _entries(agent, repo, "TD-4")
        await _pass(agent)
        assert not _live(agent, "grind-4"), "the guard: the last extra filled has not claimed"
        first.state = "idle"
        await person.call("progress", id=first.id, ref="TD-3")
        await _pass(agent)
        assert _live(agent, "grind-4")


async def test_ten_minutes_with_no_claim_lifts_the_guard_as_unstuck(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        await _pass(agent)
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        first = _rec(agent, "grind-3")
        await _pass(agent, datetime.now(UTC) + SCALE_STEP - timedelta(seconds=30))
        assert first.scale["last"]["did"] == "fill", "not yet ten minutes"
        later = datetime.now(UTC) + SCALE_STEP + timedelta(seconds=30)
        await _pass(agent, later)
        assert first.scale["last"] == {**first.scale["last"], "did": "unstuck", "why": "not claimed in 10 min"}
        assert not _live(agent, "grind-4"), "the guard's lifting fills nothing alone: no event"
        _entries(agent, repo, "TD-4")
        await _pass(agent, later)
        assert _live(agent, "grind-4"), "a start that stuck is no reason to wait"


async def test_a_closed_extra_holds_no_guard(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        await _pass(agent)
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        first = _rec(agent, "grind-3")
        first.state = "limited"
        _entries(agent, repo, "TD-4")
        await _pass(agent)
        assert not _live(agent, "grind-4")
        first.state = "idle"
        await person.call("close", id=first.id)
        assert not _live(agent, "grind-3")
        _entries(agent, repo, "TD-5")
        await _pass(agent)
        assert _live(agent, "grind-3"), "held again, it is the lowest-placed and fills"


@pytest.mark.parametrize("guard", ["balance", "gated", "unstaffed", "wind-down", "ceiling"])
async def test_each_guard_holds_a_fill_back(agent, tmp_path, monkeypatch, guard):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path)
        await _pass(agent)
        if guard == "balance":
            agent._host_rec.setdefault("teams", {})[TEAM] = {"balance": {"since": "x", "crossed": ["prs"]}}
        elif guard == "gated":
            made[2].profile = "gated"
            monkeypatch.setattr(agent, "_profile_gated", lambda p, now, team="": p == "gated")
        elif guard == "unstaffed":
            for m in made[:2]:
                m.state, m.out_of_work = "closed", {"at": "2026-11-11T00:00:00Z", "why": "none"}
        elif guard == "wind-down":
            made[0].wrapup_at = "2026-11-11T00:00:00Z"
        else:
            now = datetime.now(UTC).isoformat()
            made[3].restarts = [{"at": now, "why": "fill"}] * 6
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        assert not _live(agent, "grind-3") and not _live(agent, "grind-4")
        assert (TEAM, LINE) in agent._scale_held, "held back: read again each tick"
        if guard == "balance":
            agent._host_rec["teams"][TEAM] = {}
            await _pass(agent)  # the mark lifting is read by the next tick, with no new event
            assert _live(agent, "grind-3")


async def test_the_host_cap_writes_stopped_and_fills_the_tick_after_a_session_closes(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        mine = (await person.call("create", **_shell(tmp_path, "mine")))["id"]
        agent._machine_cap = 3  # grind-1, grind-2 and mine
        await _pass(agent)
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        held = _rec(agent, "grind-3")
        assert held.state == "closed" and held.scale["last"]["did"] == "stopped"
        assert held.scale["last"]["why"] == "host full, 3 live"
        assert _rec(agent, "grind-4").scale.get("last") is None, "on the lowest-placed alone"
        await _pass(agent)
        assert not _live(agent, "grind-3")
        await person.call("close", id=mine)
        agent._scale_held.clear()  # the stopped mark on the record is what carries it, as across a restart
        await _pass(agent)
        assert _live(agent, "grind-3"), "no claim needed: the stopped fill is read again"
        assert _rec(agent, "grind-3").scale["last"]["did"] == "fill"


async def test_the_host_cap_with_an_idle_extra_seat_to_close_fills(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        seat = agent.sessions[(await person.call("create", **_shell(tmp_path, "tl-2")))["id"]]
        seat.seat, seat.scale = {"trigger": "asks"}, {"line": "tl"}
        seat.state, seat.confidence, seat.pending = "idle", "hook", None
        seat.git = {"dirty": 0, "unpushed": 0}
        seat.since = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        agent._machine_cap = 3
        await _pass(agent)
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        assert _live(agent, "grind-3") and seat.state == "closed"
        assert seat.scale["last"]["why"] == "host full, room for grind-3"


async def test_the_tick_runs_the_pass(agent, monkeypatch):
    await park_ticks(agent)
    seen = []

    async def took(now):
        seen.append(now)

    monkeypatch.setattr(agent, "_scale_pass", took)
    await agent.tick()
    assert len(seen) == 1
