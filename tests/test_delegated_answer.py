"""A delegated answer on the board (ledgerboard v3.4, TD-1939): a `Decided:` written `by <delegate> for <person>
(<scope>)` is read as the person's answer, and every place that draws who answered names the delegate and its scope
beside it (design §4.4 *Board write-back*, §4.5 screen 6 and screen 12)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from _v3board import ref_of, write_board  # noqa: E402 — tests/ is on the path

from sessionorc import queue as queue_mod
from sessionorc import workorders
from shiftlead.ui import inbox

OPEN = (
    "- [ ] decide 2026-11-10 (session n/a) — **Merge TD-90's PR?** Context: TD-90 decision (paul). Due: 2026-11-20. "
    "Answers: Merge | Hold. Decided: Merge (by paul) (2026-11-12)."
)
CLOSED = (
    "- [x] decide 2026-11-01 (session n/a) — **Ship TD-70's parts?** Context: TD-70 decision (paul). "
    "Due: 2026-11-02. Answers: Go | Not yet. Decided: Go (by paul) (2026-11-04). Closed: 2026-11-04 — lifted."
)
PLAIN = (
    "- [x] decide 2026-11-01 (session n/a) — **Keep TD-71?** Context: TD-71 decision (paul). "
    "Due: 2026-11-02. Answers: Keep | Drop. Decided: Keep (by paul) (2026-11-05). Closed: 2026-11-05 — lifted."
)


def _delegate(root: Path, text: str) -> None:
    """Rewrite the one item file holding `text`'s `Decided:` as a delegated answer: director for paul (merge-line)."""
    hits = [p for p in (root / "docs" / "user_attention").rglob("*.md") if text in p.read_text(encoding="utf-8")]
    assert len(hits) == 1, hits
    body = hits[0].read_text(encoding="utf-8")
    old = next(ln for ln in body.splitlines() if ln.startswith("**Decided:**"))
    date, _, said = old.removeprefix("**Decided:** ").partition(" by paul — ")
    new = f"**Decided:** {date} by director for paul (merge-line) — {said}"
    hits[0].write_text(body.replace(old, new), encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    write_board(root, "\n".join(["# Board", "", OPEN, CLOSED, PLAIN, ""]))
    _delegate(root, "Merge TD-90's PR?")
    _delegate(root, "Ship TD-70's parts?")
    return root


@pytest.mark.unit
def test_the_reading_keeps_a_delegated_answer_the_persons_and_names_its_delegate_and_scope(tmp_path):
    """An open item's record and a closed one's `carried` row read `decided_by` as the person, with the delegate and
    the scope beside it; a plain answer's carried row has neither key, as before v3.4."""
    (b,) = workorders.read_boards(_repo(tmp_path), fetch=False)["boards"]
    (it,) = b["items"]
    assert (it["decided_by"], it["decided_delegate"], it["decided_scope"]) == ("paul", "director", "merge-line")
    shipped, kept = sorted(b["carried"], key=lambda c: c["ref"])
    assert (shipped["decided_by"], shipped["decided_delegate"], shipped["decided_scope"]) == (
        "paul",
        "director",
        "merge-line",
    )
    assert kept["decided_by"] == "paul" and "decided_delegate" not in kept and "decided_scope" not in kept


@pytest.mark.unit
def test_a_delegated_answer_is_a_work_order_naming_its_delegate(tmp_path):
    """The work order of a decided line carries `delegate` and `scope` in `decided` for a delegated answer alone."""
    root = _repo(tmp_path)
    (order,) = workorders.orders(workorders.read_boards(root, fetch=False))
    assert order["id"] == ref_of(OPEN)
    assert order["decided"] == {"text": "Merge", "date": "2026-11-12", "delegate": "director", "scope": "merge-line"}


@pytest.mark.unit
def test_the_queues_board_lines_carry_the_delegate_and_scope(tmp_path):
    """`_board_lines`, open and closed alike, carry `delegate` and `scope`; `by` stays the person, so the hold reads
    the line as the person's answer."""
    reading = workorders.read_boards(_repo(tmp_path), fetch=False)
    lines = {ln["said"]: ln for ln in queue_mod._board_lines({"repo": reading["boards"]})}
    assert {s: (ln["by"], ln["delegate"], ln["scope"]) for s, ln in lines.items()} == {
        "Merge": ("paul", "director", "merge-line"),
        "Go": ("paul", "director", "merge-line"),
        "Keep": ("paul", None, None),
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("delegate", "scope", "words"),
    [
        ("director", "merge-line", "director for you (merge-line)"),
        ("director", None, "director for you"),
        (None, "merge-line", ""),
        ("  ", None, ""),
    ],
)
def test_delegated_for_names_the_delegate_and_its_scope(delegate, scope, words):
    assert inbox.delegated_for(delegate, scope) == words


@pytest.mark.unit
def test_a_board_rows_decided_line_names_the_delegate():
    """The board row's *decided: <text> · <date>* gains *· <delegate> for you (<scope>)*; a person's own, no `for`."""
    got = inbox._decided(
        {"decided": {"text": "Go", "date": "2026-11-12"}, "decided_delegate": "director", "decided_scope": "merge-line"}
    )
    assert got == {"text": "Go", "date": "Nov 12", "for": "director for you (merge-line)"}
    assert "for" not in inbox._decided({"decided": {"text": "Go", "date": "2026-11-12"}, "decided_by": "paul"})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("line", "words"),
    [
        (
            {"said": "Go", "delegate": "director", "scope": "merge-line"},
            "director answered “Go” for you on the board (merge-line)",
        ),
        (
            {"said": "", "delegate": "director", "scope": "merge-line"},
            "director answered for you on the board (merge-line)",
        ),
        ({"said": "Go"}, "you answered “Go” on the board"),
        ({"said": ""}, "you answered on the board"),
    ],
)
def test_a_board_answers_foot_names_the_delegate(line, words):
    """The Queue's foot for a board answer (§4.5 screen 12 *A held entry the person has answered*)."""
    got = {"kind": "board", "asker": "s-1", "closed_at": "2026-11-12"}
    got["line"] = {"key": "board:1", "open": False, **line}
    now = datetime(2026, 11, 14, 12, tzinfo=UTC)
    assert inbox._held_answered(got, [], {"s-1": "grinder"}, now)["words"] == words
