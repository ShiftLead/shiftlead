"""Rule 14's up half (design §6 rule 14 *Scale with the work*, §4.9 *Scaling with the work*; td-max, TD-1546 slice 1):
a worker line whose every live member holds a lease, its lane holding a pickable entry nobody holds, fills its
lowest-placed held extra at the event that made it short — an entry becoming pickable, a member's claim — never on a
timer; one guard holds a second fill until the first claims, closes or sticks ten minutes; and the balance mark, a
gated profile, an unstaffed line, a wind-down and the host cap hold a fill back, the cap's written *stopped*."""

from __future__ import annotations

import dataclasses
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
        _entries(agent, repo, "TD-5")  # an event: the filled extra holds no lease, free, so the line is not short
        await _pass(agent)
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


@pytest.mark.parametrize("guard", ["balance", "gated", "unstaffed", "wind-down", "finished", "ceiling"])
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
        elif guard == "finished":  # the tick read the team finished, no `wrapup_at` yet (TD-1640)
            agent._finished_first[TEAM] = datetime.now(UTC)
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


async def test_an_unstuck_extra_that_claimed_is_free_between_items(agent, tmp_path):
    """Review of slice 1: `unstuck` passes over a start that stuck only until it claims."""
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        await _pass(agent)
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        e = _rec(agent, "grind-3")
        e.scale = {**e.scale, "last": {"at": datetime.now(UTC).isoformat(), "did": "unstuck", "why": "x"}}
        e.progress = [ProgressEntry(ref="TD-3", status="done")]  # it claimed, finished and sits between items
        _entries(agent, repo, "TD-6")
        await _pass(agent)
        assert not _live(agent, "grind-4"), "an extra between items is free: the line is not short"


async def test_a_design_or_live_check_in_the_lane_is_no_pickable_entry(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        await _pass(agent)
        agent._repos[str(repo)]["ledger"]["entries"] += [
            {**_e("TD-7"), "for_page": "design"},
            {**_e("TD-8"), "for_page": "live-check"},
        ]
        await _pass(agent)
        assert not _live(agent, "grind-3")


async def test_a_failed_fill_is_read_again_next_tick(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        await _pass(agent)
        real = agent._replay

        async def failed(*a, **k):
            return None  # the replay made nothing

        monkeypatch.setattr(agent, "_replay", failed)
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        assert not _live(agent, "grind-3")
        monkeypatch.setattr(agent, "_replay", real)
        await _pass(agent)  # no new event: the failed fill was held back, and is read again
        assert _live(agent, "grind-3")


async def test_a_claim_while_the_ledger_cannot_be_read_waits_for_the_reading(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path, ids=("TD-1", "TD-2", "TD-3", "TD-4"))
        made[1].progress = []
        await _pass(agent)
        await person.call("progress", id=made[1].id, ref="TD-2")
        good = agent._repos[str(repo)]["ledger"]
        agent._repos[str(repo)]["ledger"] = {"error": "unreadable"}
        await _pass(agent)
        assert not _live(agent, "grind-3")
        agent._repos[str(repo)]["ledger"] = good
        await _pass(agent)  # the claim was kept for the reading
        assert _live(agent, "grind-3")


async def test_a_standing_guard_survives_a_homes_restart(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path, ids=("TD-1", "TD-2", "TD-3", "TD-4"))
        await _pass(agent)
        _entries(agent, repo, "TD-5")
        await _pass(agent)
        e = _rec(agent, "grind-3")
        e.state = "limited"  # it cannot pick: the line is still short, and its guard stands
        agent._scale_init()  # the home restarted: its memory is gone
        await _pass(agent)
        assert not _live(agent, "grind-4")
        e.progress = [ProgressEntry(ref="TD-3")]  # the guard lifts with its claim
        await _pass(agent)  # no new entry and no claim event: the guard read from the records brings it back
        assert _live(agent, "grind-4")


async def test_a_held_extra_a_lowered_max_is_dropping_is_passed_over_for_the_next(agent, tmp_path):
    """The fill's pick (#3383, TD-1639): a held extra marked `scale.drop` is never refilled; the next one fills."""
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path)
        made[2].scale = {**made[2].scale, "drop": "now"}
        await _pass(agent)
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        assert not _live(agent, "grind-3") and _live(agent, "grind-4")


async def test_a_crashed_extra_rule_1_restarts_is_not_filled(agent, tmp_path):
    """The fill's pick (#3383, TD-1639): an extra exited with a crash rule 1 restarts is no held extra to fill, so
    filling it would start it twice; the next one fills."""
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path)
        await _pass(agent)
        made[2].state, made[2].pane = "exited", True
        assert agent._crashed(made[2], datetime.now(UTC))
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        assert _rec(agent, "grind-3").state == "exited" and not _rec(agent, "grind-3").restarts
        assert _live(agent, "grind-4")


async def test_a_node_runs_no_pass_and_records_no_claim(agent, tmp_path):
    """The home alone fills (#3383, TD-1641): a node's host agent reads no line and keeps no claim event, so an
    extra the home owns is never filled from a node."""
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path, ids=("TD-1", "TD-2", "TD-3", "TD-4"))
        made[1].progress = []
        await _pass(agent)  # the home's baseline: grind-2 is free, nothing pickable is new
        agent.mode = "node"
        agent._scale_claimed(made[1])
        assert not agent._scale_claims, "a claim off the home is no event of rule 14's"
        _entries(agent, repo, "TD-5")
        made[1].progress = [ProgressEntry(ref="TD-2")]
        await _pass(agent)
        assert not _live(agent, "grind-3"), "a node runs no pass"
        agent.mode = "home"
        agent._scale_claimed(made[1])
        assert agent._scale_claims, "the home keeps it"
        await _pass(agent)
        assert _live(agent, "grind-3"), "the event the node passed over is the home's to read"


async def test_a_line_on_a_remote_host_is_read_and_its_held_extra_filled(agent, tmp_path, monkeypatch):
    """The pass reads `agent.remote` beside its own records (#3383, TD-1641): a line whose members and extras run
    on a node is read at the home, and its held extra there filled."""
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path)
        node = agent.remote.setdefault("laptop", {})
        for r in made:
            del agent.sessions[r.id]
            r.host = "laptop"
            node[r.id] = r
        filled = []

        async def replay(s, why, **kw):
            filled.append((s.name, why))
            node[s.id] = dataclasses.replace(s, state="idle")

        monkeypatch.setattr(agent, "_replay", replay)
        await _pass(agent)
        assert not filled, "the first reading is a baseline"
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        assert filled == [("grind-3", "fill")], "the lowest-placed remote extra, once"
        assert node[made[2].id].scale["last"]["did"] == "fill"


async def test_a_fill_keeps_the_held_extras_mail(agent, tmp_path):
    """The fill creates the held extra with `keep_mail` (§6 rule 14 *Fill*, TD-1642): the record it replaces is
    superseded with its mail carried (`supersedes[].mail`), so what was sent to the held seat waits for the new run."""
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path)
        held = made[2]
        await _pass(agent)
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        got = _rec(agent, "grind-3")
        assert got is not held and _live(agent, "grind-3"), "a new record, created over the held one"
        assert got.supersedes[-1] == {**got.supersedes[-1], "id": held.id, "mail": True}, "the held record's mail kept"


async def test_the_fill_ceiling_counts_only_fills_inside_the_window(agent, tmp_path):
    """The ceiling counts the line's extras' `fill` restarts inside `FILL_WINDOW` (§6 rule 14, TD-1642): six fills
    older than the window and six restarts for another reason hold nothing back."""
    from sessionorc.agent_common import FILL_CEILING, FILL_WINDOW

    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path)
        await _pass(agent)
        now = datetime.now(UTC)
        old = (now - FILL_WINDOW - timedelta(minutes=5)).isoformat()
        made[3].restarts = [{"at": old, "why": "fill"}] * FILL_CEILING + [
            {"at": now.isoformat(), "why": "crash"}
        ] * FILL_CEILING
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        assert _live(agent, "grind-3"), "neither old fills nor other restarts reach the ceiling"


async def test_an_unserved_repos_pickable_entries_fill_nothing(agent, tmp_path):
    """An unserved repo's lane reads empty (§5 *The seams*, §6 rule 14; TD-1643): an entry becoming pickable there is
    no event, and the line is not filled."""
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        agent._repos[str(repo)]["seams"] = {"serve": {"ok": False, "lacks": [{"key": "sync", "words": "not synced"}]}}
        await _pass(agent)
        _entries(agent, repo, "TD-3", "TD-4")
        await _pass(agent)
        assert not _live(agent, "grind-3")


async def test_a_work_order_in_the_lane_makes_the_line_short(agent, tmp_path):
    """The lane's pickable entries include its repo's work orders (§6 rule 14, `_orders`; TD-1643): a decided board
    line becoming an order, every member leased, fills an extra."""
    from sessionorc import workorders

    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        await _pass(agent)
        order = workorders.entry({"id": "board:0123abcd", "title": "Keep the backup?", "decided": {"text": "keep"}})
        agent._repos[str(repo)]["work_orders"] = {"orders": [order]}
        await _pass(agent)
        assert _live(agent, "grind-3")
        assert _rec(agent, "grind-3").scale["last"]["why"] == "filled: 1 pickable, every grind claimed"


async def test_a_derived_claim_is_a_lease(agent, tmp_path):
    """A derived claim holds a lease whatever its age (§6 rule 14, §4.8 *A claim is a lease*; TD-1643): members whose
    claims the tick derived, older than `LEASE_TTL`, are busy, so the line is short and fills."""
    from sessionorc.agent_common import LEASE_TTL

    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path)
        old = (datetime.now(UTC) - LEASE_TTL - timedelta(hours=1)).isoformat()
        for m, ref in zip(made[:2], ("TD-1", "TD-2"), strict=True):
            m.progress = [ProgressEntry(ref=ref, at=old, source="derived", branch=f"{ref.lower()}-x")]
        await _pass(agent)
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        assert _live(agent, "grind-3"), "every member holds a derived lease: the line is short"


async def test_a_line_with_no_extra_left_forgets_its_memory(agent, tmp_path):
    """Rule 14's memory is per line with an extra (TD-1643): once a line's last extra record is gone, its last
    reading and its held-back mark go with it."""
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, made = await _line(agent, person, tmp_path)
        await _pass(agent)
        made[3].restarts = [{"at": datetime.now(UTC).isoformat(), "why": "fill"}] * 6  # the ceiling holds it back
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        key = (TEAM, LINE)
        assert key in agent._scale_seen and key in agent._scale_held
        for extra in made[2:]:
            del agent.sessions[extra.id]
        await _pass(agent)
        assert key not in agent._scale_seen, "the line's last reading goes with its last extra"
        assert key not in agent._scale_held, "and so does its held-back mark"


async def test_a_filled_extra_that_claimed_is_never_marked_unstuck(agent, tmp_path):
    """The guard's ten minutes lift only a start that has not claimed (§6 rule 14; TD-1643): an extra filled past
    `SCALE_STEP` ago that claimed keeps its `fill`."""
    await park_ticks(agent)
    async with LocalClient() as person:
        repo, _ = await _line(agent, person, tmp_path)
        await _pass(agent)
        _entries(agent, repo, "TD-3")
        await _pass(agent)
        first = _rec(agent, "grind-3")
        await person.call("progress", id=first.id, ref="TD-3")
        await _pass(agent, datetime.now(UTC) + SCALE_STEP + timedelta(seconds=30))
        assert first.scale["last"]["did"] == "fill", "it claimed: its start did not stick"
