"""An entry says what it waits for (design §4.4, TD-715, built by TD-716 slice 1): a `**Waits:**`
line read into `waits`, the home's `waiting` mark while it stands, no lane taking a waiting entry,
`in_lanes` counting it apart, and a claim on it refused unless forced."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import ledger, settle
from sessionorc.client import AgentError, LocalClient

NOW = datetime.now(UTC)
TODAY = NOW.astimezone().date()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()
GRINDER = ["free-pick", "owner:grinder"]


def _entry(n: int, waits: str = "", where: str = "head") -> str:
    head = f"## TD-{n:03d}: entry {n}\n\n**Priority:** Medium\n**Owner:** grinder\n**Kind:** build\n"
    if waits and where == "head":
        head += f"**Waits:** {waits}\n"
    body = f"\n**Why:** a reason.\n\n**Waits:** {waits}\n" if waits and where == "body" else "\n**Why:** a reason.\n"
    return head + "**Status:** Open\n" + body


def _read(*parts: str, now: datetime = NOW) -> dict[str, dict]:
    got = settle.mark_waits(ledger.entries("# Ledger\n\n" + "\n".join(parts)), now)
    return {e["id"]: e for e in got}


def test_the_line_is_read_from_the_header_block_alone():
    got = _read(
        _entry(1, f"until {TOMORROW} — CI runs on or after then"),
        _entry(2, "event — the next cadence-sync PR"),
        _entry(3, "until a date nobody wrote"),
        _entry(4, "sometime"),
        _entry(5, "event — below the block", where="body"),
        _entry(6),
    )
    assert got["TD-001"]["waits"] == {"on": "until", "date": TOMORROW, "why": "CI runs on or after then"}
    assert got["TD-002"]["waits"] == {"on": "event", "date": "", "why": "the next cadence-sync PR"}
    assert got["TD-003"]["waits"] == {"on": "until", "date": "", "why": "a date nobody wrote"}
    for i in ("TD-004", "TD-005", "TD-006"):
        assert "waits" not in got[i] and "waiting" not in got[i], i
    assert ledger.flags(list(got.values())) == ["TD-003: Waits: until names no date"]


def test_a_wait_stands_until_its_day_and_an_event_until_the_line_goes():
    got = _read(_entry(1, f"until {TOMORROW} — CI"), _entry(2, "event — a sync"), _entry(3, "until no date"))
    assert got["TD-001"]["waiting"] == {"on": "until", "until": TOMORROW}
    assert got["TD-002"]["waiting"] == {"on": "event", "until": ""}
    assert got["TD-003"]["waiting"] == {"on": "until", "until": ""}, "no date: it waits with no end"
    later = settle.mark_waits(list(got.values()), NOW + timedelta(days=1))
    assert [e["id"] for e in later if e.get("waiting")] == ["TD-002", "TD-003"], "its day has begun"
    assert _read(_entry(1, f"until {TODAY.isoformat()} — today"))["TD-001"].get("waiting") is None
    assert "waiting" not in _read(_entry(2))["TD-002"], "the line edited away: no wait"


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
    assert entries[0]["waiting"] == {"on": "event", "until": ""}


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
        with pytest.raises(AgentError, match="TD-002 waits: the next cadence-sync PR"):
            await person.call("progress", id=g, ref="TD-002", status="claimed")
        await person.call("progress", id=g, ref="TD-002", status="claimed", force=True)
        assert [e.ref for e in agent.sessions[g].progress] == ["TD-002"]
