"""What the tick's wiring fetches for an entry's facts (design §4.9c, TD-2051)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shiftlead import stage_fetch
from shiftlead.stage_fetch import EntryOn, entry_on, entry_text, files_at, ledger_read, protected_at
from shiftlead.stage_read import EntryLedger

README = "# Ledger\n\nLedgerboard: 2\n"


def entry(n: int, extra: str = "") -> str:
    return f"## TD-{n}: Entry {n}\n\n**Priority:** Low\n**Status:** Open\n{extra}\n**Why:** because.\n"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def commit(root: Path, files: dict[str, str | None]) -> str:
    for rel, text in files.items():
        path = root / rel
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "c")
    return git(root, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    root.mkdir()
    git(root, "init", "-q")
    commit(root, {"docs/ledger/README.md": README, "docs/ledger/TD-7.md": entry(7), "docs/ledger/TD-8.md": entry(8)})
    return root


def test_an_open_entry_reads_with_its_own_text_alone(repo: Path) -> None:
    read = ledger_read(repo, "docs/ledger", "HEAD")
    assert read is not None
    got = entry_on(repo, "HEAD", read, "TD-7")
    assert got.ledger == EntryLedger("open")
    assert got.text is not None and got.text.startswith("## TD-7:") and "TD-8" not in got.text


def test_an_archived_entry_reads_as_archived_with_no_text(repo: Path) -> None:
    commit(repo, {"docs/ledger/TD-7.md": None, "docs/ledger/archive/TD-7.md": entry(7)})
    read = ledger_read(repo, "docs/ledger", "HEAD")
    assert read is not None
    assert entry_on(repo, "HEAD", read, "TD-7") == EntryOn(EntryLedger("archived"))


def test_an_entry_renamed_away_reads_as_renumbered(repo: Path) -> None:
    git(repo, "mv", "docs/ledger/TD-7.md", "docs/ledger/TD-9.md")
    commit(repo, {"docs/ledger/TD-9.md": entry(9)})
    read = ledger_read(repo, "docs/ledger", "HEAD")
    assert read is not None
    assert entry_on(repo, "HEAD", read, "TD-7") == EntryOn(renumbered_to="TD-9")


def test_an_entry_in_neither_file_is_no_reading(repo: Path) -> None:
    read = ledger_read(repo, "docs/ledger", "HEAD")
    assert read is not None
    assert entry_on(repo, "HEAD", read, "TD-70") == EntryOn()


def test_a_ledger_that_is_not_there_or_a_bad_ref_is_no_read(repo: Path) -> None:
    assert ledger_read(repo, "docs/elsewhere", "HEAD") is None
    assert ledger_read(repo, "docs/ledger", "no-such-ref") is None


def test_entry_text_matches_by_number_and_skips_a_commented_template() -> None:
    text = f"<!--\n{entry(7)}-->\n{entry(70)}{entry(7, '**Type:** debt')}## Notes\n\nnot the entry\n"
    got = entry_text(text, "TD-007")
    assert got is not None and "**Type:** debt" in got and "not the entry" not in got
    assert entry_text(text, "TD-71") is None


@pytest.mark.parametrize(
    ("body", "want"),
    [
        ("held:\n  - src/**\n", ["src/**"]),
        ("held:\n  core: [src/**]\n  ui: [web/**]\n", ["src/**", "web/**"]),
        ("ledger: docs/ledger\n", []),
        ("held: [\n", None),
        ("no_such_key: 1\n", None),
    ],
)
def test_protected_files_are_read_from_the_ref(repo: Path, body: str, want: list[str] | None) -> None:
    commit(repo, {".shiftlead.yml": body})
    assert protected_at(repo, "HEAD") == want


def test_a_tree_with_no_repo_file_protects_nothing_and_a_bad_ref_is_no_reading(repo: Path) -> None:
    assert protected_at(repo, "HEAD") == []
    assert protected_at(repo, "no-such-ref") is None


def test_protected_files_come_from_the_ref_not_the_working_tree(repo: Path) -> None:
    commit(repo, {".shiftlead.yml": "held: [src/**]\n"})
    (repo / ".shiftlead.yml").write_text("held: [other/**]\n", encoding="utf-8")
    assert protected_at(repo, "HEAD") == ["src/**"]


@pytest.mark.parametrize(
    ("files", "row", "want"),
    [
        (["a.py"], {"state": "open", "head": "h1"}, ["a.py"]),
        ("gh failed", {"state": "open", "head": "h1"}, None),
        (["a.py"], {"state": "open", "head": "h2"}, None),
        (["a.py"], {"state": "merged"}, None),
        (["a.py"], None, None),
    ],
)
def test_files_count_only_while_the_head_stands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, files: object, row: object, want: list[str] | None
) -> None:
    monkeypatch.setattr(stage_fetch.held, "paged_files", lambda *_a, **_k: files)
    monkeypatch.setattr(stage_fetch.reports, "pr_state_row", lambda *_a, **_k: row)
    assert files_at(tmp_path, 5, "h1") == want


def test_no_head_reads_no_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def never(*_a: object, **_k: object) -> list[str]:
        raise AssertionError("no head: the forge is not asked")

    monkeypatch.setattr(stage_fetch.held, "paged_files", never)
    assert files_at(tmp_path, 5, None) is None
