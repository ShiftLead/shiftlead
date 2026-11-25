"""TD-2026 slice 1, design §4.4 *A design's question is asked once, on the design* (TD-2021): a design's **held
builds** are the ids its newest end-of-rounds line lists in `Parts:` — each open, its part, gated, not the person's
own, and asked by no open line of its own — read once by `held_map`; and `with_held` adds a held build's counted
open work to its design's, so the design waits on it, on the Queue, the Inbox and the home's stale-press refusal."""

from __future__ import annotations

import pytest
from test_queue import _entry
from test_queue_board_hold import HELD, _open, _read, _row
from test_queue_lift_here import _setup

from sessionorc import queue

PART = {"Priority": "High", "Part_of": "TD-001", "Blocked_by": "decision (paul)"}
ASK = "TD-001 decision (paul)"


def _ask(parts: str, ctx: str = ASK) -> str:
    return _open(ctx, decided=None, parts=parts)


def _closed_line(parts: str, why: str, *, ctx: str = ASK, decided: str = "One more round (2026-10-15)") -> str:
    return (f"- [x] decide 2026-10-14 (session n/a) — **Another round?** Context: {ctx}. Parts: {parts}. "
            f"Due: 2026-10-20. Answers: Go | One more round. Decided: {decided}. "
            f"Closed: 2026-10-15 — {why}.")  # fmt: skip


def _held(r: dict) -> dict[str, str]:
    opens = {queue.qid("r", e["id"]): {**e, "repo": "r"} for e in r["ledger"]["entries"]}
    boards = {"r": list(r["boards"]["boards"])}
    return queue.held_map(opens, boards, queue.open_refs(opens))


@pytest.mark.unit
def test_the_newest_end_of_rounds_line_names_the_held_builds(tmp_path):
    root, r = _setup(
        tmp_path,
        [_entry(1, "the design", **HELD), _entry(2, "build a", **PART), _entry(3, "build b", **PART)],
        _ask("TD-002, TD-003"),
    )
    assert r["boards"]["boards"][0]["items"][0]  # the line was read
    assert _held(r) == {"r#TD-002": "r#TD-001", "r#TD-003": "r#TD-001"}
    opens = {queue.qid("r", e["id"]): {**e, "repo": "r"} for e in r["ledger"]["entries"]}
    design = opens["r#TD-001"]
    assert queue.held_builds(design, opens, {"r": r["boards"]["boards"]}, queue.open_refs(opens)) == [
        "r#TD-002",
        "r#TD-003",
    ]


@pytest.mark.unit
def test_a_design_the_person_owns_has_no_held_builds(tmp_path):
    root, r = _setup(
        tmp_path, [_entry(1, "the design", **HELD, Owner="paul"), _entry(2, "build a", **PART)], _ask("TD-002")
    )
    assert _held(r) == {}


@pytest.mark.unit
def test_only_the_listed_gated_parts_not_the_persons_own_are_held(tmp_path):
    entries = [
        _entry(1, "the design", **HELD),
        _entry(2, "held", **PART),
        _entry(3, "not its part", Priority="High", Blocked_by="decision (paul)"),
        _entry(4, "ungated part", Priority="High", Part_of="TD-001"),
        _entry(5, "the person's own", **PART, Owner="paul"),
        _entry(6, "a gated part the line does not list", **PART),
    ]
    root, r = _setup(tmp_path, entries, _ask("TD-002, TD-003, TD-004, TD-005"))
    assert _held(r) == {"r#TD-002": "r#TD-001"}


@pytest.mark.unit
def test_a_build_asked_by_an_open_line_of_its_own_reads_its_own_hold(tmp_path):
    entries = [_entry(1, "the design", **HELD), _entry(2, "build a", **PART), _entry(3, "build b", **PART)]
    root, r = _setup(tmp_path, entries, _ask("TD-002, TD-003"), _ask("", ctx="TD-003 decision (paul)"))
    assert _held(r) == {"r#TD-002": "r#TD-001"}


@pytest.mark.unit
def test_the_sweeps_parts_less_re_ask_never_empties_the_set(tmp_path):
    entries = [_entry(1, "the design", **HELD), _entry(2, "build a", **PART)]
    root, r = _setup(tmp_path, entries, _closed_line("TD-002", "carried to TD-002"), _ask(""))
    assert _held(r) == {"r#TD-002": "r#TD-001"}, "a closed carried-to line yields the set, its gate read by carried()"
    assert r["boards"]["boards"][0]["carried"][0]["gate"] == "decision (paul)"


@pytest.mark.unit
def test_the_newest_line_alone_names_the_set(tmp_path):
    entries = [_entry(1, "the design", **HELD), _entry(2, "build a", **PART), _entry(3, "build b", **PART)]
    root, r = _setup(tmp_path, entries, _closed_line("TD-002", "carried to TD-099"), _ask("TD-003"))
    assert _held(r) == {"r#TD-003": "r#TD-001"}, "the undecided open line is the newest"


@pytest.mark.unit
def test_a_line_naming_another_entry_or_no_gate_holds_nothing(tmp_path):
    entries = [_entry(1, "the design", **HELD), _entry(2, "build a", **PART)]
    root, r = _setup(tmp_path, entries, _ask("TD-002", ctx="TD-001"))
    assert _held(r) == {}
    root, r = _setup(tmp_path / "b", entries, _ask("TD-002", ctx="TD-001, TD-002 decision (paul)"))
    assert _held(r) == {}


@pytest.mark.unit
def test_with_held_merges_innermost_first_in_key_order():
    entries = {f"r#TD-00{n}": {"id": f"TD-00{n}", "key": f"0|{n}"} for n in range(1, 8)}
    held = {"r#TD-002": "r#TD-001", "r#TD-003": "r#TD-002"}  # TD-002 is itself a design with a question
    work = {"r#TD-003": ["r#TD-007"], "r#TD-002": ["r#TD-005"], "r#TD-001": ["r#TD-006", "r#TD-005"]}
    got = queue.with_held(work, held, entries)
    assert got["r#TD-002"] == ["r#TD-005", "r#TD-007"]
    assert got["r#TD-001"] == ["r#TD-005", "r#TD-006", "r#TD-007"], "the outer design takes in the inner's merged work"
    assert got["r#TD-003"] == ["r#TD-007"] and work["r#TD-002"] == ["r#TD-005"], "a build keeps its own; a copy"
    assert queue.with_held({"r#TD-002": ["r#TD-004"]}, {"r#TD-002": "r#TD-001"}, entries)["r#TD-001"] == ["r#TD-004"]


@pytest.mark.unit
def test_a_held_builds_open_part_makes_its_design_wait_on_the_queue(tmp_path):
    """A held build's open part is its design's (TD-2172): the design has the fact, so it waits; a held build's
    blocker alone is a wait, and a design with a question is asked as any over it, its Go now written (TD-2184)."""
    entries = [
        _entry(1, "the design", **HELD),
        _entry(2, "build a", Priority="High", Part_of="TD-001", Blocked_by="TD-004, decision (paul)"),
        _entry(4, "the build's blocker", Priority="High"),
    ]
    root, r = _setup(tmp_path, entries, _ask("TD-002"))
    row = _row(_read({root: r}), "r#TD-001")
    assert row["open_work"] == [] and row["state"] == "" and row["needs"] == "decision"
    assert not row["then_yours"] and not row["early"] and row["go_builds"] == ["TD-002"]
    entries.append(_entry(5, "build a's round", Priority="High", Part_of="TD-002"))
    root, r = _setup(tmp_path / "p", entries, _ask("TD-002"))
    row = _row(_read({root: r}), "r#TD-001")
    assert row["open_work"] == ["r#TD-004", "r#TD-005"] and row["state"] == "waiting, then yours"
    assert row["lift_here"] is False
    entries.pop()
    # the same line with no Parts: no held build, and the design asks as before
    root, r = _setup(tmp_path / "b", entries, _ask(""))
    assert _row(_read({root: r}), "r#TD-001")["open_work"] == []


@pytest.mark.unit
def test_the_inbox_and_the_homes_refusal_read_the_held_builds_work(tmp_path):
    from types import SimpleNamespace

    from sessionorc.agent_common import RpcError
    from sessionorc.agent_inbox import InboxMixin
    from shiftlead.ui.app import ledger_for_you

    entries = [
        _entry(1, "the design", **HELD),
        _entry(2, "build a", Priority="High", Part_of="TD-001", Blocked_by="TD-004, decision (paul)"),
        _entry(4, "the build's blocker", Priority="High"),
    ]
    root, r = _setup(tmp_path, entries, _ask("TD-002"))
    # the build's blocker alone is a wait: the design is asked as any, pressed as any (TD-2172)
    assert ledger_for_you({root: r}, [], {})["entries"]["r#TD-001"]["open_work"] == []
    home = SimpleNamespace(_repos={root: r})
    home._open_work = lambda: InboxMixin._open_work(home)
    InboxMixin._refuse_waiting(home, ["r#TD-001"])
    # the build's own open part is the design's fact
    entries.append(_entry(5, "build a's round", Priority="High", Part_of="TD-002"))
    root, r = _setup(tmp_path / "p", entries, _ask("TD-002"))
    assert ledger_for_you({root: r}, [], {})["entries"]["r#TD-001"]["open_work"] == ["r#TD-004", "r#TD-005"]
    home = SimpleNamespace(_repos={root: r})
    home._open_work = lambda: InboxMixin._open_work(home)
    with pytest.raises(RpcError, match="TD-001 waits on TD-004: it is asked once that closes"):
        InboxMixin._refuse_waiting(home, ["r#TD-001"])


@pytest.mark.unit
def test_a_held_builds_blocker_that_waits_on_the_design_is_not_its_work(tmp_path):
    """TD-2058: as `open_work` drops a blocker whose chain reaches the member, `with_held` drops one reaching the
    design, so the design never waits on what waits on it."""
    entries = [
        _entry(1, "the design", **HELD),
        _entry(2, "build a", Priority="High", Part_of="TD-001", Blocked_by="TD-004, decision (paul)"),
        _entry(4, "waits on the design", Priority="High", Blocked_by="TD-005"),
        _entry(5, "waits on the design too", Priority="High", Blocked_by="TD-001"),
    ]
    root, r = _setup(tmp_path, entries, _ask("TD-002"))
    row = _row(_read({root: r}), "r#TD-001")
    assert row["open_work"] == [] and row["state"] != "waiting, then yours"
    # the chain ending short of the design still makes it wait
    entries[3] = _entry(5, "free", Priority="High")
    root, r = _setup(tmp_path / "b", entries, _ask("TD-002"))
    opens = {queue.qid("r", e["id"]): {**e, "repo": "r"} for e in r["ledger"]["entries"]}
    assert queue.counted_work(opens, lambda _x: None, _held(r)).work["r#TD-001"] == ["r#TD-004"]
    work = {"r#TD-002": ["r#TD-004"]}
    opens = {queue.qid("r", e["id"]): {**e, "repo": "r"} for e in r["ledger"]["entries"]}
    assert queue.with_held(work, {"r#TD-002": "r#TD-001"}, opens)["r#TD-001"] == ["r#TD-004"]
