"""The design's history, one file per ledger entry (design §4.4 *Two PRs' records merge in either order*, TD-1513):
`docs/history/`'s shape, the frozen `docs/design-history.md`, and `scripts/history.py`'s reading order."""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "history.py"

# docs/design-history.md as TD-1513's cut left it. It is never written again: a new line goes to docs/history/.
FROZEN_SHA256 = "8d8f35eba15e9716fd4df7eaca069207faaae9503675d2e814c523e0463f19c5"


def _load():
    spec = importlib.util.spec_from_file_location("history", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["history"] = mod  # a dataclass reads its module
    spec.loader.exec_module(mod)
    return mod


history = _load()


def frozen_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root(tmp_path: Path, files: dict[str, str], frozen: str = "", entries: tuple[str, ...] = ()) -> Path:
    """A scratch repo root: the real design index, a frozen file, the ledger entries named, and `files`
    under docs/history/."""
    docs = tmp_path / "docs"
    (docs / "history").mkdir(parents=True)
    (docs / "ledger" / "archive").mkdir(parents=True)
    shutil.copy(ROOT / "docs" / "design.md", docs / "design.md")
    (docs / "design-history.md").write_text(frozen, encoding="utf-8")
    for e in entries:
        (docs / "ledger" / f"{e}.md").write_text(f"## {e}: x\n", encoding="utf-8")
    for name, text in files.items():
        (docs / "history" / name).write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.unit
def test_the_frozen_file_is_never_written_again(tmp_path):
    assert frozen_sha(ROOT / "docs" / "design-history.md") == FROZEN_SHA256, (
        "docs/design-history.md is frozen at TD-1513's cut: write the line to docs/history/TD-<n>.md instead"
    )
    copy = tmp_path / "design-history.md"
    shutil.copy(ROOT / "docs" / "design-history.md", copy)
    copy.write_bytes(copy.read_bytes() + b"- 2026-11-08 (TD-1): a line from an old habit.\n")
    assert frozen_sha(copy) != FROZEN_SHA256


@pytest.mark.unit
def test_the_frozen_file_says_where_the_history_lives():
    text = (ROOT / "docs" / "design-history.md").read_text(encoding="utf-8")
    first = next(ln for ln in text.splitlines()[1:] if ln.strip())
    assert "history/" in first and "TD-1513" in first


@pytest.mark.unit
def test_the_repo_history_is_sound():
    assert history.check(ROOT) == []


@pytest.mark.unit
def test_names_headings_and_lines_are_held(tmp_path):
    good = "## §6\n\n- 2026-11-07 (TD-7): a line.\n  its continuation.\n\n## §title\n- 2026-11-07 (TD-7): t.\n"
    root = _root(
        tmp_path,
        {
            "TD-7.md": good,
            "2026-11-07-td-fix-board-edit.md": "## §4.4a\n- 2026-11-07 (no entry): x.\n",
            "td-8.md": good,  # misnamed
            "2026-11-07-Board_Edit.md": good,  # slug not lowercased
            "TD-9.md": good,  # no such entry
            "TD-10.md": "## §6\n- 2026-11-07 (TD-x): x.\n## §4.11\n- 2026-11-07 (TD-x): y.\n## §6.\n",  # not indexed
            "TD-14.md": "## §6\n- 2026-13-45 (TD-x): no such day.\n",
            "TD-11.md": "# A title\n## §6\n- 2026-11-07 (TD-x): x.\n",  # a title
            "TD-12.md": "## §6\n- 2026-11-07 (TD-x): x.\nprose under it\n- undated: x.\n",  # prose, an undated line
            "TD-13.md": "- 2026-11-07 (TD-x): before any heading.\n",
            "README.md": "# anything goes here\n",
        },
        entries=("TD-7", "TD-10", "TD-11", "TD-12", "TD-13", "TD-14"),
    )
    (root / "docs" / "history" / "sub").mkdir()
    problems = "\n".join(history.check(root))
    assert "TD-7.md" not in problems and "td-fix-board-edit" not in problems and "README" not in problems
    assert "td-8.md: not named" in problems
    assert "2026-11-07-Board_Edit.md: not named" in problems
    assert "TD-9.md: names TD-9, which the ledger does not hold" in problems
    assert "TD-10.md:3: `## §4.11` names no section" in problems and "TD-10.md:1" not in problems
    assert "TD-11.md:1:" in problems
    assert "TD-12.md:3:" in problems and "TD-12.md:4:" in problems
    assert "TD-13.md:1:" in problems
    assert "TD-10.md:5: `## §6.` names no section" in problems  # the frozen file's `6.`, not the index's `§6`
    assert "TD-14.md:2:" in problems
    assert "docs/history/sub: a subdirectory" in problems


@pytest.mark.unit
def test_an_archived_entry_names_its_file(tmp_path):
    root = _root(tmp_path, {"TD-5.md": "## §6\n- 2026-11-07 (TD-x): x.\n"})
    assert history.check(root)
    (root / "docs" / "ledger" / "archive" / "TD-5.md").write_text("## TD-5: x\n", encoding="utf-8")
    assert history.check(root) == []


@pytest.mark.unit
def test_the_slug_is_the_branch_lowercased():
    assert history.slug("td-fix/Board_Edit") == "td-fix-board-edit"
    assert history.slug("TD1513--history..per entry") == "td1513-history-per-entry"


FROZEN = """# ShiftLead — design history

Preamble.

## 4.1 Session substrate

- 2026-09-01 (TD-1): four-one.

## 4.10 Messages (first part)

- 2026-10-01 (TD-2): ten, first.
- undated: kept where it is.
- 2026-09-01 (TD-3): older, below, not re-sorted.

## §4.10 (middle)

- 2026-10-02 (TD-4): ten, middle.

## Title and status

- 2026-09-04: the title.
"""


@pytest.mark.unit
def test_the_reader_orders_new_lines_then_the_frozen_file_as_written(tmp_path):
    root = _root(
        tmp_path,
        {
            "TD-9.md": "## §4.10\n- 2026-11-01 (TD-9): nine, early.\n- 2026-11-03 (TD-9): nine, late.\n",
            "TD-10.md": "## §4.10\n- 2026-11-03 (TD-10): ten, a.\n- 2026-11-03 (TD-10): ten, b.\n  continued.\n",
            "TD-11.md": "## §4.1\n- 2026-11-05 (TD-11): four-one only.\n",
        },
        frozen=FROZEN,
    )
    out = history.render("4.10", root=root)
    order = [
        "TD-10.md: - 2026-11-03 (TD-10): ten, b.\n  continued.",  # a tie: TD-10.md before TD-9.md, later first
        "TD-10.md: - 2026-11-03 (TD-10): ten, a.",
        "TD-9.md: - 2026-11-03 (TD-9): nine, late.",
        "TD-9.md: - 2026-11-01 (TD-9): nine, early.",
        "## 4.10 Messages (first part)",
        "- 2026-10-01 (TD-2): ten, first.\n- undated: kept where it is.\n- 2026-09-01 (TD-3): older",
        "## §4.10 (middle)",
        "- 2026-10-02 (TD-4): ten, middle.",
    ]
    at = [out.index(s) for s in order]
    assert at == sorted(at)
    assert "four-one" not in out  # 4.1 is not 4.10
    four_one = history.render("4.1", root=root)
    assert "four-one only" in four_one and "four-one." in four_one and "ten," not in four_one
    assert "the title" in history.render("title", root=root)
    narrowed = history.render("4.10", grep="middle", root=root)
    assert "ten, middle" in narrowed and "ten, first" not in narrowed and "nine" not in narrowed


@pytest.mark.unit
def test_the_cli_refuses_a_section_not_indexed(capsys):
    assert history.main(["99"]) == 1
    assert "not a section" in capsys.readouterr().err
    assert history.main(["§6"]) == 0
    assert "## 6. Policies" in capsys.readouterr().out
