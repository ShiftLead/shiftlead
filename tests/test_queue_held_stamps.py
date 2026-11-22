"""TD-2026 slice 2, design §4.4 *A design's question is asked once, on the design* (TD-2021): each held build carries
`held_by` (its design) on its entry, and a design with a question `go_builds` (its held builds, in key order) on its
Queue row, its `ledger_for_you` row and its `answered.lift`; case (d) reads over the set (its held builds no other
gated entry), through `held_map`'s map threaded to `lift_here`, `ledger_for_you` and `lift_ask_target`; and, as an
interim TD-2027 step 1 removes, a design with held builds draws no **Lift the hold**, which would lift it alone."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from test_queue import _entry
from test_queue_board_hold import HELD, _open, _read, _row
from test_queue_lift_here import _setup

from sessionorc import queue

PART = {"Priority": "High", "Part_of": "TD-001", "Blocked_by": "decision (paul)"}
GO = "Go (2026-10-15)"


def _opens(r: dict) -> dict[str, dict]:
    return {queue.qid("r", e["id"]): {**e, "repo": "r"} for e in r["ledger"]["entries"]}


def _closed_line(parts: str) -> str:
    p = f" Parts: {parts}." if parts else ""
    return (f"- [x] decide 2026-10-14 (session n/a) — **Another round?** Context: TD-001 decision (paul).{p} "
            f"Due: 2026-10-20. Answers: Go | One more round. Decided: One more round (2026-10-15). "
            f"Closed: 2026-10-15 — carried to TD-099.")  # fmt: skip


def _ledger_row(r: dict, root: str, ref: str) -> dict:
    from shiftlead.ui.app import ledger_for_you

    got = ledger_for_you({root: r}, [], {}, datetime(2026, 10, 16, tzinfo=UTC))
    return next(x for g in got["groups"] for x in g["rows"] if x["id"] == ref)


@pytest.mark.unit
def test_the_design_row_carries_go_builds_and_each_build_its_design(tmp_path):
    entries = [_entry(1, "the design", **HELD), _entry(3, "build b", **PART), _entry(2, "build a", **PART)]
    root, r = _setup(tmp_path, entries, _open("TD-001 decision (paul)", decided=GO, parts="TD-003, TD-002"))
    q = _read({root: r})
    assert _row(q, "r#TD-001")["go_builds"] == ["TD-002", "TD-003"], "the held builds in key order, bare ids"
    assert _row(q, "r#TD-002")["go_builds"] == []
    held = queue.held_map(_opens(r), {"r": r["boards"]["boards"]}, queue.open_refs(_opens(r)))
    assert queue.go_builds(held, _opens(r)) == {"r#TD-001": ["TD-002", "TD-003"]}


@pytest.mark.unit
def test_interim_no_lift_here_on_a_design_with_held_builds(tmp_path):
    entries = [_entry(1, "the design", **HELD), _entry(2, "build a", **PART)]
    root, r = _setup(tmp_path, entries, _open("TD-001 decision (paul)", decided=GO, parts="TD-002"))
    assert _row(_read({root: r}), "r#TD-001")["lift_here"] is False, "Go now (TD-2027) is drawn there, not a Lift"
    # the same answered line with no Parts: no held build, and the design's row draws its Lift as before
    root, r = _setup(tmp_path / "b", entries, _open("TD-001 decision (paul)", decided=GO))
    row = _row(_read({root: r}), "r#TD-001")
    assert row["lift_here"] is True and row["go_builds"] == []


@pytest.mark.unit
def test_interim_no_lift_item_on_a_design_with_held_builds_and_its_go_builds(tmp_path):
    entries = [_entry(1, "the design", **HELD), _entry(2, "build a", **PART)]
    root, r = _setup(tmp_path, entries, _closed_line("TD-002"))
    row = _ledger_row(r, root, "TD-001")
    assert row["go_builds"] == ["TD-002"] and row["lift_item"] is False
    root, r = _setup(tmp_path / "b", entries, _closed_line(""))
    row = _ledger_row(r, root, "TD-001")
    assert row["go_builds"] == [] and row["lift_item"] is True


@pytest.mark.unit
def test_answered_lift_carries_go_builds():
    from shiftlead.ui.inbox import _held_answered

    got = {"mid": "m-1", "asker": "ao-r-w", "kind": "ask", "closed_at": "2026-10-15T00:00:00Z"}
    now = datetime(2026, 10, 16, tzinfo=UTC)
    a = _held_answered(got, [], {}, now, lift={"root": "/r", "id": "TD-001", "go_builds": ["TD-002"]})
    assert a["lift"] == {"root": "/r", "id": "TD-001", "go_builds": ["TD-002"]}
    assert _held_answered(got, [], {}, now, lift={"root": "/r", "id": "TD-001"})["lift"]["go_builds"] == []


@pytest.mark.unit
def test_case_d_reads_over_the_set(tmp_path):
    entries = [_entry(1, "the design", **HELD), _entry(2, "build a", **PART)]
    root, r = _setup(tmp_path, entries, _open("TD-001 decision (paul)", decided=None, parts="TD-002"))
    opens, boards = _opens(r), {"r": r["boards"]["boards"]}
    held = queue.held_map(opens, boards, queue.open_refs(opens))
    assert held == {"r#TD-002": "r#TD-001"}
    design = opens["r#TD-001"]
    assert queue.lift_case_d(design, boards, opens, "r") is False, "without the map the build is another gated entry"
    assert queue.lift_case_d(design, boards, opens, "r", held) is True, "the item covers the set alone"
    t = queue.lift_ask_target({root: r}, "TD-001", "r")
    assert t is not None and t["asked"] == queue.lift_case_d_item(design, boards, opens, "r", held) is not None


@pytest.mark.unit
def test_lay_held_stamps_the_held_build_and_its_designs_work_on_copies(tmp_path, monkeypatch):
    entries = [
        _entry(1, "the design", **HELD),
        _entry(2, "build a", Priority="High", Part_of="TD-001", Blocked_by="TD-004, decision (paul)"),
        _entry(4, "the build's blocker", Priority="High"),
    ]
    root, r = _setup(tmp_path, entries, _open("TD-001 decision (paul)", decided=None, parts="TD-002"))
    before = _read({root: r})
    marked = queue.lay_applying(r, {"ledger:r#TD-002": {"t": {"act": "lift", "at": "x"}}}, "r")
    seen: list[list] = []
    real = queue._status
    monkeypatch.setattr(queue, "_status", lambda rows, ents: seen.append(ents) or real(rows, ents))
    queue.lay_held(before, {root: marked})
    (ents,) = seen
    by = {e["id"]: e for e in ents}
    assert by["TD-002"]["held_by"] == "r#TD-001" and by["TD-001"]["open_work"] == ["r#TD-004"]
    assert "held_by" not in marked["ledger"]["entries"][1] and "open_work" not in marked["ledger"]["entries"][0]
