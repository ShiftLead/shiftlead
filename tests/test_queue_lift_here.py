"""TD-1831 slice 2, design §4.4 *Where Lift the hold is drawn*: a Queue row's `lift_here` — set where an open decided
line covers a `decision (paul)` entry, no claim nor live recorded session holds the line, the entry or another entry
it covers, and case (d) does not hold (an open, undecided `decide` line on the entry's own board asks about its hold
and lists no other gated entry); never on an archived, an applying, a *with you* row nor an entry the person owns."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_queue import _entry, _repo
from test_queue_answered_hold import _asker, _q
from test_queue_board_hold import HELD, _open, _read, _row, _worker

from sessionorc import queue, workorders

PEOPLE = "People: paul"


def _board(root: str, *lines: str, people: bool = True) -> dict:
    d = Path(root) / "docs"
    head = ["# Board", "", PEOPLE, ""] if people else ["# Board", ""]
    (d / "user_attention.md").write_text("\n".join([*head, *lines, ""]), encoding="utf-8")
    return workorders.read_boards(root, fetch=False)


def _setup(tmp_path, entries, *board, name="r", people=True):
    root, r = _repo(tmp_path, name, entries)
    r["boards"] = _board(root, *board, people=people)
    return root, r


def _ask(ctx: str, parts: str = "") -> str:
    """An open, undecided `decide` line: the sweep's ask about a hold."""
    return _open(ctx, decided=None, parts=parts)


@pytest.mark.unit
def test_a_row_an_open_decided_line_covers_draws_the_lift(tmp_path):
    root, r = _setup(tmp_path, [_entry(1, "the held one", **HELD)], _open("TD-001"))
    assert r["boards"]["boards"][0]["people"] == ["paul"]
    row = _row(_read({root: r}), "r#TD-001")
    assert row["state"] == "answered — waiting on a pick" and row["lift_here"] is True
    # a mail answer drawn under such a line draws it too: the word is the mail's, the Lift the line's
    row = _row(_read({root: r}, [_asker()], [_q()]), "r#TD-001")
    assert row["state"] == "answered — waiting on designer" and row["lift_here"] is True


@pytest.mark.unit
def test_no_lift_where_nothing_open_and_decided_covers_the_entry(tmp_path):
    # no line at all; a mail answer no open line covers
    root, r = _setup(tmp_path, [_entry(1, "the held one", **HELD)])
    assert _row(_read({root: r}), "r#TD-001")["lift_here"] is False
    assert _row(_read({root: r}, [_asker()], [_q()]), "r#TD-001")["lift_here"] is False
    # a line decided by someone else is not the person's answer
    root, r = _setup(
        tmp_path / "b", [_entry(1, "the held one", **HELD)], _open("TD-001", decided="Go (by sam) (2026-10-15)")
    )
    assert _row(_read({root: r}), "r#TD-001")["lift_here"] is False


@pytest.mark.unit
def test_a_holder_of_the_line_the_entry_or_a_covered_sibling_clears_the_lift(tmp_path):
    entries = [_entry(1, "the held one", **HELD), _entry(2, "its sibling", **HELD)]
    root, r = _setup(tmp_path, entries, _open("TD-001, TD-002"))
    key = r["boards"]["boards"][0]["items"][0]["key"]
    assert _row(_read({root: r}), "r#TD-001")["lift_here"] is True
    for refs in ((key,), ("TD-001",), ("r#TD-001",), ("TD-002",)):
        rec = _worker("ao-r-grinder", *refs)
        rec.repo = rec.dir = root
        row = _row(_read({root: r}, [rec]), "r#TD-001")
        assert row["lift_here"] is False, refs
        if refs != ("TD-002",):
            assert row["state"] == "answered — waiting on grinder", refs
    # the line's live recorded session holds it with no claim
    root2, r2 = _setup(tmp_path / "s", [_entry(1, "the held one", **HELD)], _open("TD-001", session="designer"))
    row = _row(_read({root2: r2}, [_asker()]), "r#TD-001")
    assert row["state"] == "answered — waiting on designer" and row["lift_here"] is False


@pytest.mark.unit
def test_no_lift_on_a_persons_entry_an_ungated_one_an_applying_row_or_an_archived_one(tmp_path):
    mine = _entry(1, "the person's own", Owner="paul", **HELD)
    loose = _entry(2, "lifted already", Priority="High")
    root, r = _setup(tmp_path, [mine, loose], _open("TD-001, TD-002"))
    q = _read({root: r})
    assert _row(q, "r#TD-001")["lift_here"] is False
    # after the lift the entry carries no gate: the row reads no answer and draws no Lift, the line still open
    two = _row(q, "r#TD-002")
    assert two["answered"] is None and two["lift_here"] is False
    led = r["ledger"]
    assert "r#TD-002" in queue.open_decided_covers(
        {"r": r["boards"]["boards"]}, {f"r#{e['id']}": {**e, "repo": "r"} for e in led["entries"]}, {}
    )
    # under a press's mark the row reads *applying lift* and draws no second Lift, in the reading and held back
    root2, r2 = _setup(tmp_path / "a", [_entry(1, "the held one", **HELD)], _open("TD-001"))
    before = _read({root2: r2})
    assert _row(before, "r#TD-001")["lift_here"] is True
    marked = queue.lay_applying(r2, {"ledger:r#TD-001": {"t": {"act": "lift", "at": "x"}}}, "r")
    row = _row(_read({root2: marked}), "r#TD-001")
    assert row["state"] == "applying lift" and row["lift_here"] is False
    held = queue.lay_held(before, {root2: marked})
    assert _row(held, "r#TD-001")["lift_here"] is False


def _member(n: int = 1, part_of: str | None = None) -> dict:
    e = {"id": f"TD-{n:03d}", "repo": "r", "blocked_by": "decision (paul)", "part_of": part_of}
    return e


def _gated(*ns: int, part_of: dict[int, str] | None = None) -> dict:
    return {
        f"r#TD-{n:03d}": {"id": f"TD-{n:03d}", "repo": "r", "blocked_by_raw": "decision (paul)",
                          "blocked_by": ["decision (paul)"], "part_of": (part_of or {}).get(n)}
        for n in ns
    }  # fmt: skip


def _case_d(tmp_path, ctx: str, *, parts: str = "", people: bool = True, member=None, entries=None, own=True):
    root = tmp_path / "r"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    boards = _board(str(root), _ask(ctx, parts), people=people)["boards"]
    m = member or _member()
    return queue.lift_case_d(m, {"r" if own else "o": boards}, entries or _gated(1), "o/r")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ctx", "want"),
    [
        ("TD-001 decision (paul)", True),
        ("o/r#TD-001 decision (paul)", True),  # a ref naming the entry's own repo by its origin path
        ("x/y#TD-001 decision (paul)", False),  # another repo's
        ("r#TD-001 decision (paul)", False),  # `_ours` reads a qualified ref against the origin path alone
        ("TD-001", False),  # a ref with no gate
        ("TD-001, TD-002 decision (paul)", False),  # two refs
        ("TD-001 decision (paul) lift", False),  # a qualifier after the gate
        ("TD-001 decision (sam)", False),  # another person's gate
    ],
)
def test_case_d_reads_the_context_as_covers_does(tmp_path, ctx, want):
    assert _case_d(tmp_path, ctx) is want


@pytest.mark.unit
def test_case_d_needs_the_entrys_own_board_and_its_people(tmp_path):
    assert _case_d(tmp_path / "a", "TD-001 decision (paul)", people=False) is False
    assert _case_d(tmp_path / "b", "TD-001 decision (paul)", own=False) is False


@pytest.mark.unit
def test_case_d_through_the_parent_and_a_listed_gated_entry(tmp_path):
    part = _member(2, part_of="TD-001")
    # the parent named with the gate, the entry among its Parts: case (d) — unless the parent itself is open and gated
    assert _case_d(tmp_path / "a", "TD-001 decision (paul)", parts="TD-002", member=part, entries=_gated(2)) is True
    assert _case_d(tmp_path / "b", "TD-001 decision (paul)", parts="o/r#TD-002", member=part, entries=_gated(2)) is True
    assert _case_d(tmp_path / "c", "TD-001 decision (paul)", parts="TD-002", member=part, entries=_gated(1, 2)) is False
    # a bare Parts id of another gated entry is listed; a qualified one never counts in the listing
    assert _case_d(tmp_path / "d", "TD-001 decision (paul)", parts="TD-002", entries=_gated(1, 2)) is False
    assert _case_d(tmp_path / "e", "TD-001 decision (paul)", parts="o/r#TD-002", entries=_gated(1, 2)) is True
    # not among the Parts: the parent's line asks about the parent alone
    assert _case_d(tmp_path / "f", "TD-001 decision (paul)", parts="TD-003", member=part, entries=_gated(2)) is False


@pytest.mark.unit
def test_a_row_case_d_holds_for_draws_no_lift(tmp_path):
    entries = [_entry(1, "the held one", **HELD)]
    root, r = _setup(tmp_path, entries, _open("TD-001"), _ask("TD-001 decision (paul)"))
    assert _row(_read({root: r}), "r#TD-001")["lift_here"] is False
    # a board with no People line: no cover, no case (d), and the row draws the Lift (the press refuses in its words)
    root2, r2 = _setup(tmp_path / "n", entries, _open("TD-001"), _ask("TD-001 decision (paul)"), people=False)
    assert _row(_read({root2: r2}), "r#TD-001")["lift_here"] is True
    # the ask on a board that is not the entry's own is no case (d)
    root3, r3 = _setup(tmp_path / "o", entries, _open("TD-001"))
    other, o = _setup(tmp_path / "o", [_entry(9, "theirs", Priority="Low")], _ask("TD-001 decision (paul)"), name="x")
    assert _row(_read({root3: r3, other: o}), "r#TD-001")["lift_here"] is True


@pytest.mark.unit
def test_case_d_item_names_the_asking_item_for_an_ask_lifts_refusal(tmp_path):
    """`lift_case_d_item` (TD-1833): the `board:<key>` an `ask --lift`'s refusal names; None where none asks."""
    root = tmp_path / "r"
    (root / "docs").mkdir(parents=True)
    boards = _board(str(root), _ask("TD-001 decision (paul)", ""), people=True)["boards"]
    key = queue.lift_case_d_item(_member(), {"r": boards}, _gated(1), "o/r")
    assert key is not None and key.startswith("board:") and len(key) == len("board:") + 8
    assert queue.lift_case_d_item(_member(), {"o": boards}, _gated(1), "o/r") is None
