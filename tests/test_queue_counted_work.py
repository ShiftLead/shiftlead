"""TD-2184, design §4.4 *A question whose entry only waits is asked early* (TD-2172): `queue.counted_work`, the one
builder of a `decision (paul)` member's counted open work in its two kinds — open parts and waits — with a gated
blocker that itself waits counted, a chain counted at each link, a cycle counting for nothing, and the member's own
date or event waits read apart."""

from __future__ import annotations

import pytest

from sessionorc import queue

GATE = "decision (paul)"
TODAY = "2026-11-25"


def _e(n: int, *blocked: str, part_of: int | None = None, owner: str = "", until=(), events=()) -> tuple[str, dict]:
    ids = [b for b in blocked if b.startswith("TD-")]
    gates = {"until": list(until), "events": [{"name": x, "why": ""} for x in events]} if until or events else None
    words = [*blocked, *(f"until {d}" for d in until), *(f"event ({x})" for x in events)]
    e = {
        "id": f"TD-{n:03d}",
        "repo": "r",
        "key": "",
        "blocked_by": words,
        "blocked_ids": ids,
        "part_of": f"TD-{part_of:03d}" if part_of else None,
        "owner": owner,
        "gates": gates,
    }
    return f"r#TD-{n:03d}", e


def _count(*es: tuple[str, dict], held: dict[str, str] | None = None) -> queue.Counted:
    return queue.counted_work(dict(es), lambda _item: None, held or {}, today=TODAY)


@pytest.mark.unit
def test_a_gated_blocker_that_waits_on_open_work_counts_as_a_wait_at_each_link():
    # TD-001 gated, blocked by A (gated, no work) and B (gated, blocked by open C that waits until a later day)
    c = _count(
        _e(1, "TD-002", "TD-003", GATE),
        _e(2, GATE),
        _e(3, "TD-004", GATE),
        _e(4, until=["2026-12-20"]),
    )
    assert c.work["r#TD-003"] == ["r#TD-004"]
    assert c.work["r#TD-001"] == ["r#TD-003"], "B counts, A with nothing counts for nothing"
    assert not c.parts, "a wait is no open part"
    # blocked by A alone: no counted work, asked as any
    c = _count(_e(1, "TD-002", GATE), _e(2, GATE))
    assert "r#TD-001" not in c.work


@pytest.mark.unit
def test_a_members_own_unreached_until_or_event_gate_is_a_date_or_event_wait():
    c = _count(_e(1, GATE, until=["2026-12-01"]), _e(2, GATE, until=["2026-11-25"]), _e(3, GATE, events=["live"]))
    assert c.gates == {"r#TD-001": ["until 2026-12-01"], "r#TD-003": ["event (live)"]}, "a day come is no wait"
    assert not c.work
    # a gated blocker whose only wait is its own date counts as a wait id
    c = _count(_e(1, "TD-002", GATE), _e(2, GATE, until=["2026-12-01"]))
    assert c.work == {"r#TD-001": ["r#TD-002"]} and "r#TD-002" in c.gates


@pytest.mark.unit
def test_open_parts_are_the_counted_ids_part_of_the_member_or_its_held_build():
    c = _count(_e(1, "TD-002", GATE), _e(2), _e(3, part_of=1))
    assert c.work["r#TD-001"] == ["r#TD-002", "r#TD-003"] and c.parts == {"r#TD-001": ["r#TD-003"]}
    # a held build's own open part is among its design's open parts; its blocker is a wait
    c = _count(
        _e(1, GATE),
        _e(2, "TD-003", GATE, part_of=1),
        _e(3),
        _e(4, part_of=2),
        held={"r#TD-002": "r#TD-001"},
    )
    assert c.work["r#TD-001"] == ["r#TD-003", "r#TD-004"] and c.parts["r#TD-001"] == ["r#TD-004"]


@pytest.mark.unit
def test_a_held_build_whose_only_blocker_is_a_gated_entry_that_waits_passes_the_wait_to_its_design():
    c = _count(
        _e(1, GATE),
        _e(2, "TD-003", GATE, part_of=1),
        _e(3, "TD-004", GATE),
        _e(4),
        held={"r#TD-002": "r#TD-001"},
    )
    assert c.work["r#TD-002"] == ["r#TD-003"] and c.work["r#TD-001"] == ["r#TD-003"]
    assert "r#TD-001" not in c.parts


@pytest.mark.unit
def test_a_cycle_of_gated_blockers_counts_for_nothing():
    c = _count(_e(1, "TD-002", GATE), _e(2, "TD-001", GATE))
    assert not c.work
    # even where one link of the cycle has open work of its own
    c = _count(_e(1, "TD-002", "TD-003", GATE), _e(2, "TD-001", GATE), _e(3))
    assert c.work == {"r#TD-001": ["r#TD-003"]}


@pytest.mark.unit
def test_the_fact_is_an_open_part_or_any_counted_work_on_a_gated_owner_paul_entry():
    es = dict([_e(1, "TD-002", GATE), _e(2), _e(3, "TD-002", GATE, owner="paul"), _e(4, GATE), _e(5, part_of=4)])
    c = queue.counted_work(es, lambda _item: None, {}, today=TODAY)
    assert not queue.has_fact("r#TD-001", c, es), "a blocker alone is a wait"
    assert queue.has_fact("r#TD-003", c, es) and queue.has_fact("r#TD-004", c, es)
