"""An entry says what it waits for (design §4.4, TD-715, built by TD-716 slice 1; its gates since TD-1395,
the `**Waits:**` line no longer read since TD-1398): the home's `waiting` mark while a gate stands, no lane
taking a waiting entry, `in_lanes` counting it apart, and a claim on it refused unless forced."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import ledger, settle
from sessionorc.client import AgentError, LocalClient

NOW = datetime.now(UTC)
TODAY = NOW.date()  # a wait's day is a UTC day (TD-1395)
TOMORROW = (TODAY + timedelta(days=1)).isoformat()
GRINDER = ["free-pick", "owner:grinder"]


def _entry(n: int, waits: str = "") -> str:
    """An entry whose wait is `until <date>` or `event — <why>`, written as its gate: `until <date>`, or
    `event (e)` with an Event section whose line is the why."""
    head = f"## TD-{n:03d}: entry {n}\n\n**Priority:** Medium\n**Owner:** grinder\n**Kind:** build\n"
    body = "\n**Why:** a reason.\n"
    if waits.startswith("until "):
        head += f"**Blocked by:** until {waits.split()[1]}\n"
    elif waits.startswith("event"):
        head += "**Blocked by:** event (e)\n"
        body += f"\n**Event (e):** {waits.partition('— ')[2]}\ncheck: pr-merged o/r#5\n"
    return head + "**Status:** Open\n" + body


def _read(*parts: str, now: datetime = NOW) -> dict[str, dict]:
    got = settle.mark_waits(ledger.entries("# Ledger\n\n" + "\n".join(parts)), now)
    return {e["id"]: e for e in got}


def test_a_waits_line_still_standing_is_not_read():
    """The `**Waits:**` line is retired (TD-1398): one still standing marks no wait and no flag, and the
    entry stays pickable."""
    head = "## TD-001: entry 1\n\n**Priority:** Medium\n**Owner:** grinder\n**Kind:** build\n"
    got = _read(head + f"**Waits:** until {TOMORROW} — CI\n**Status:** Open\n\n**Why:** a reason.\n")["TD-001"]
    assert "waits" not in got and "waiting" not in got and got["pickable"] == "yes"
    assert ledger.lane_matches(GRINDER, got) and ledger.flags([got]) == []
    assert not hasattr(ledger, "waits_of") and settle.wait_refusal(got) is None


def test_a_wait_stands_until_its_day_and_an_event_until_the_gate_goes():
    got = _read(_entry(1, f"until {TOMORROW} — CI"), _entry(2, "event — a sync"))
    assert got["TD-001"]["waiting"] == {"on": "until", "until": TOMORROW, "name": "", "why": ""}
    assert got["TD-002"]["waiting"] == {"on": "event", "until": "", "name": "e", "why": "a sync"}
    later = settle.mark_waits(list(got.values()), NOW + timedelta(days=1))
    assert [e["id"] for e in later if e.get("waiting")] == ["TD-002"], "its day has begun"
    assert _read(_entry(1, f"until {TODAY.isoformat()} — today"))["TD-001"].get("waiting") is None
    assert "waiting" not in _read(_entry(2))["TD-002"], "the gate lifted: no wait"


def test_a_waiting_entry_matches_no_lane_and_is_counted_apart():
    got = _read(_entry(1), _entry(2, f"until {TOMORROW} — CI"), _entry(3, "event — a sync"))
    entries = list(got.values())
    assert ledger.lane_matches(GRINDER, got["TD-001"]) and not ledger.lane_matches(GRINDER, got["TD-002"])
    assert got["TD-002"]["for_page"] == "pickable", "its page kind is unchanged"
    records = [
        {"id": "w1", "name": "w1", "lane": GRINDER, "state": "idle", "out_of_work": {"at": "x"}},
        {"id": "w2", "name": "w2", "lane": GRINDER, "state": "idle"},
    ]
    lanes = ledger.in_lanes(entries, records, held={"TD-001"})
    assert lanes["pickable"] == ["TD-001"] and lanes["rest"] == []
    assert lanes["waiting"] == {"until": ["TD-002"], "event": ["TD-003"]}
    assert lanes["members"][0]["ids"] == [] and lanes["members"][0]["waiting"] == ["TD-002", "TD-003"]
    assert lanes["out_of_work"] == [], "a member whose lane only waits is not out of work with n"
    assert lanes["out_of_work_waiting"] == [{"id": "w1", "name": "w1", "waiting": ["TD-002", "TD-003"]}]
    free = ledger.in_lanes(entries, records)
    assert free["out_of_work"] == [{"id": "w1", "name": "w1", "ids": ["TD-001"]}] and free["out_of_work_waiting"] == []


def test_a_wait_is_marked_with_no_settle_record():
    """A repo with no `settle:` and no clock record still marks waits (`mark` over an empty record)."""
    entries = ledger.entries("# Ledger\n\n" + _entry(1, "event — a sync"))
    settle.mark(entries, "o/nothing-recorded", {}, NOW)
    assert entries[0]["waiting"] == {"on": "event", "until": "", "name": "e", "why": "a sync"}


@pytest.mark.integration
async def test_a_claim_on_a_waiting_entry_is_refused_and_force_passes_it(agent, tmp_path):
    await park_ticks(agent)
    root = str(tmp_path / "r")
    got = _read(_entry(1, f"until {TOMORROW} — CI"), _entry(2, "event — the next cadence-sync PR"))
    agent._repos[root] = {"name": "r", "root": root, "ledger": {"entries": list(got.values())}}
    async with LocalClient() as person:
        g = (await person.call("create", name="g", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
        agent.sessions[g].repo = root
        with pytest.raises(AgentError, match=f"TD-001 waits until {TOMORROW}"):
            await person.call("progress", id=g, ref="TD-001", status="claimed")
        with pytest.raises(AgentError, match=r"TD-002 waits on event \(e\)"):
            await person.call("progress", id=g, ref="TD-002", status="claimed")
        await person.call("progress", id=g, ref="TD-002", status="claimed", force=True)
        assert [e.ref for e in agent.sessions[g].progress] == ["TD-002"]


# -- TD-742: the behaviours the test audit of #1843 found unheld ------------------------------------------


@pytest.mark.integration
async def test_a_second_write_on_a_claimed_waiting_entry_is_not_refused(agent, tmp_path):
    """Only a claim is refused (`new_claim`): the claimer's next `progress` on the waiting entry it took
    with `force` — its `done` — passes without `force`, or it could not say what became of its work."""
    await park_ticks(agent)
    root = str(tmp_path / "r")
    got = _read(_entry(2, "event — the next cadence-sync PR"))
    agent._repos[root] = {"name": "r", "root": root, "ledger": {"entries": list(got.values())}}
    async with LocalClient() as person:
        g = (await person.call("create", name="g", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
        agent.sessions[g].repo = root
        await person.call("progress", id=g, ref="TD-002", status="claimed", force=True)
        await person.call("progress", id=g, ref="TD-002", status="done", why="built")  # no refusal, no force
        assert [(e.ref, e.status) for e in agent.sessions[g].progress] == [("TD-002", "done")]


def test_a_held_waiting_entry_is_in_no_members_waiting():
    got = _read(_entry(1, f"until {TOMORROW} — CI"), _entry(2, "event — a sync"))
    records = [{"id": "w1", "name": "w1", "lane": GRINDER, "state": "idle", "out_of_work": {"at": "x"}}]
    lanes = ledger.in_lanes(list(got.values()), records, held={"TD-001"})
    assert lanes["members"][0]["waiting"] == ["TD-002"]
    assert lanes["out_of_work_waiting"] == [{"id": "w1", "name": "w1", "waiting": ["TD-002"]}]
