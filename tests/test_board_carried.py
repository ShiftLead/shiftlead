"""The boards' `carried` (design §4.4 *The boards*, *The card's status*, TD-1368): the closed decided lines of a
board and its archive, which may still hold a member's `decision (paul)` after the person answered on the
board; and the ledger's newest `kept waiting` date per gate, which a `— kept waiting.` close is read with."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sessionorc import ledger as ledger_mod
from sessionorc import workorders

CARRIED = (
    "- [x] decide 2026-11-01 (session designer-ao-1 on kmaster) — **One more round on TD-50?** Context: TD-50. "
    "Due: 2026-11-02. Answers: Go | One more round. Decided: One more round (2026-11-03). "
    "Closed: 2026-11-03 — carried to TD-61 and TD-62."
)
OTHER = (
    "- [x] decide 2026-11-01 (session n/a) — **Ship TD-70's parts?** Context: TD-70 decision (paul), TD-71. "
    "Parts: TD-72, TD-73. Due: 2026-11-02. Answers: Go | Not yet. Decided: Not yet (by paul) (2026-11-04). "
    "Closed: 2026-11-04 — kept waiting."
)
NOT_DECIDE = (
    "- [x] act 2026-11-01 (session n/a) — **Rotate.** Context: TD-80. Decided: done (2026-11-02). Closed: 2026-11-02."
)
NO_REF = (
    "- [x] decide 2026-11-01 (session n/a) — **Which?** Answers: a | b. Decided: a (2026-11-02). Closed: 2026-11-02."
)
OPEN = "- [ ] act 2026-10-01 (session n/a) — **Rotate the token.** Context: TD-778. Due: 2026-10-02."


def _repo(tmp_path: Path, board: list[str], archive: list[str] | None = None) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "user_attention.md").write_text("\n".join(["# Board", "", *board, ""]), encoding="utf-8")
    if archive is not None:
        (root / "docs" / "user_attention_archive.md").write_text("\n".join(["# Archive", "", *archive, ""]))
    return root


@pytest.mark.unit
@pytest.mark.parametrize(
    ("reason", "to"),
    [
        ("carried to TD-1310", ["TD-1310"]),
        ("carried to TD-1310 and TD-1311.", ["TD-1310", "TD-1311"]),
        ("carried to TD-1, TD-2 & TD-3", ["TD-1", "TD-2", "TD-3"]),
        ("carried to TD-1, and TD-2", ["TD-1", "TD-2"]),
        ("carried to TD-9 — see TD-4", ["TD-9"]),
        ("carried to TD-9 and see TD-4", ["TD-9"]),
        ("carried to ledgerboard#TD-9", ["ledgerboard#TD-9"]),
        ("Go", []),
        ("", []),
        ("done: carried to TD-9", []),
    ],
)
def test_a_closes_carried_to_ids_end_at_the_first_other_word_dash_or_sentence_end(reason, to):
    assert workorders.carried_to(reason) == to


@pytest.mark.unit
def test_carried_reads_each_closed_decided_decide_line_that_names_an_entry_with_its_closed_cut(tmp_path):
    """A closed `decide` line's `Decided:` is read with its trailing `Closed:` cut; its refs, gate words read
    past, and its `Parts:`; a closed line of another kind, or naming no entry, is not carried; open items are not."""
    root = _repo(tmp_path, [OPEN, CARRIED, NOT_DECIDE, NO_REF, OTHER])
    (b,) = workorders.read_boards(root, fetch=False)["boards"]
    first, second = b["carried"]
    assert first == {
        "key": workorders.ref("", CARRIED[6:]),
        "ref": "TD-50",
        "decided": {"text": "One more round", "date": "2026-11-03"},
        "decided_by": None,
        "closed": {"date": "2026-11-03", "why": "carried to TD-61 and TD-62."},
        "to": ["TD-61", "TD-62"],
        "at": 4,
        "refs": ["TD-50"],
        "parts": [],
    }
    assert (second["ref"], second["refs"], second["parts"]) == ("TD-70", ["TD-70", "TD-71"], ["TD-72", "TD-73"])
    assert (second["decided"], second["decided_by"]) == ({"text": "Not yet", "date": "2026-11-04"}, "paul")
    assert (second["closed"], second["to"], second["at"]) == ({"date": "2026-11-04", "why": "kept waiting."}, [], 7)
    # the key is the open line's: the decide and the close move no key (§4.4 *A board line's id*)
    assert first["key"] == workorders.ref("", CARRIED[6:].split(" Decided:")[0].replace("[x]", "[ ]"))


@pytest.mark.unit
def test_the_archive_beside_the_board_is_read_after_it_and_at_runs_on_over_both_files(tmp_path):
    root = _repo(tmp_path, [OPEN, CARRIED], archive=[OTHER])
    (b,) = workorders.read_boards(root, fetch=False)["boards"]
    board_lines = len((root / "docs" / "user_attention.md").read_text().splitlines())
    assert [(c["ref"], c["at"]) for c in b["carried"]] == [("TD-50", 4), ("TD-70", board_lines + 3)]
    assert b["items"][0]["line"] == 3  # an open item's `line` is its index on the same scale
    # an archive re-read once its file moves, and none at all once it is gone
    (root / "docs" / "user_attention_archive.md").write_text(f"# Archive\n\n{CARRIED}\n{OTHER}\n")
    (b,) = workorders.read_boards(root, fetch=False)["boards"]
    assert [c["ref"] for c in b["carried"]] == ["TD-50", "TD-50", "TD-70"]
    (root / "docs" / "user_attention_archive.md").unlink()
    (b,) = workorders.read_boards(root, fetch=False)["boards"]
    assert [c["ref"] for c in b["carried"]] == ["TD-50"]


@pytest.mark.unit
def test_a_write_back_trees_board_reads_the_archive_beside_it(tmp_path):
    root = _repo(tmp_path, [OPEN])
    tree = tmp_path / "tree" / "docs"
    tree.mkdir(parents=True)
    (tree / "user_attention.md").write_text(f"{OPEN}\n{CARRIED}\n")
    (tree / "user_attention_archive.md").write_text(f"{OTHER}\n")
    (b,) = workorders.read_boards(root, board=tree / "user_attention.md")["boards"]
    assert [(c["ref"], c["at"]) for c in b["carried"]] == [("TD-50", 2), ("TD-70", 3)]


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.mark.unit
def test_a_board_read_from_origin_reads_origins_archive(tmp_path):
    """The archive comes from the same copy as the board: origin's where the board is read from origin."""
    origin, seed, clone = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "clone"
    _git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    _git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    _git("config", "user.email", "t@t", cwd=seed)
    _git("config", "user.name", "t", cwd=seed)
    (seed / "docs").mkdir()
    (seed / "docs" / "user_attention.md").write_text(f"{OPEN}\n")
    _git("add", "-A", cwd=seed)
    _git("commit", "-qm", "board", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    _git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    (seed / "docs" / "user_attention.md").write_text(f"{OPEN}\n{CARRIED}\n")
    (seed / "docs" / "user_attention_archive.md").write_text(f"{OTHER}\n")
    _git("add", "-A", cwd=seed)
    _git("commit", "-qm", "closed and archived", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    (b,) = workorders.read_boards(clone)["boards"]
    assert b["fetch_case"] == "behind"
    assert [c["ref"] for c in b["carried"]] == ["TD-50", "TD-70"]
    assert not (clone / "docs" / "user_attention_archive.md").exists()  # nothing written into the checkout
    plain = workorders.read_boards(clone, fetch=False)["boards"][0]
    assert plain["carried"] == []  # the checkout's own copy holds neither


ENTRY = """## TD-90: A held build

**Priority:** Medium
**Type:** debt
**Added:** 2026-11-01
**Owner:** grinder
**Kind:** build
**Status:** Open
**Blocked by:** decision (paul)

**Why:** a reason.

**Log:**
- 2026-11-01: gate added: decision (paul)
- 2026-11-02: kept waiting: decision (paul) — by paul; answer "Not yet"
- 2026-11-04: kept waiting: decision (Paul) — by paul; answer "Not yet"
- 2026-11-05: gate lifted: decision (paul) — by paul; answer "Go"
"""


@pytest.mark.unit
def test_the_ledger_reading_carries_the_newest_kept_waiting_date_per_gate():
    """Read from the Log's `kept waiting` lines alone — never `gate added` or a lift — the gate's name folded."""
    assert ledger_mod.kept_waiting_of(ENTRY) == {"decision (paul)": "2026-11-04"}
    (e,) = ledger_mod.entries(ENTRY)
    assert e["kept_waiting"] == {"decision (paul)": "2026-11-04"}
    (plain,) = ledger_mod.entries(ENTRY.split("**Log:**")[0])
    assert "kept_waiting" not in plain
