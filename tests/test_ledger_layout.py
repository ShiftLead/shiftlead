"""Either layout (design §4.4 *Repo facts* — **Either layout**, TD-1144): a v1 ledger file and its v2 twin
— the same entries split by `lb.split()` into `docs/ledger/` — read alike through one road, `lb.load()`
with `fs_io` or `git_io`, and a path from before or after a split still reads (`layout_at`)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import pinned_script
from test_ledger_derived import ARCHIVE, LEDGER

from sessionorc import ledger
from sessionorc import ledgerboard as lb


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _commit(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ledger")


def _v1(root: Path) -> Path:
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "technical_debt.md").write_text(LEDGER, encoding="utf-8")
    (root / "docs" / "technical_debt_archive.md").write_text(ARCHIVE, encoding="utf-8")
    _git(root.parent, "init", "-q", str(root))
    return root


def _v2(root: Path) -> Path:
    for rel, text in lb.split(LEDGER, ARCHIVE).items():
        p = root / "docs" / "ledger" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(root.parent, "init", "-q", str(root))
    return root


def _by_id(entries: list[dict]) -> dict[str, tuple]:
    return {e["id"]: (e["title"], e["priority"], e["pickable"], e["for_page"], e["blocked_ids"]) for e in entries}


NOW = datetime(2026, 10, 27, tzinfo=UTC)


def test_a_v2_twin_reads_as_its_v1_ledger(tmp_path):
    one, two = _v1(tmp_path / "one"), _v2(tmp_path / "two")
    a = ledger.reading(one, NOW, with_history=False)
    b = ledger.reading(two, NOW, with_history=False)
    assert a["path"] == "docs/technical_debt.md" and b["path"] == "docs/ledger"  # the default rule
    assert _by_id(a["entries"]) and _by_id(a["entries"]) == _by_id(b["entries"])
    assert set(a["archived"]) == set(b["archived"])  # an archive compared as a set: load() orders it by id
    assert a["declared_teams"] == b["declared_teams"] and a["by_kind"] == b["by_kind"]


def test_a_ledger_read_at_a_commit_takes_either_layout_and_a_carried_path_from_before_a_split(tmp_path):
    one, two = _v1(tmp_path / "one"), _v2(tmp_path / "two")
    for root in (one, two):
        _commit(root)
        _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    a, at_a = ledger.entries_before(one, "docs/technical_debt.md", None)
    b, at_b = ledger.entries_before(two, "docs/ledger", None)
    assert at_a.startswith("origin/main at ") and at_b.startswith("origin/main at ")
    assert a and _by_id(a) == _by_id(b)
    # a record's `ledger` written before the split is never trusted as is: it reads the directory beside it
    carried, _ = ledger.entries_before(two, "docs/technical_debt.md", None)
    assert carried is not None and _by_id(carried) == _by_id(a)
    # and one written after a split read at a commit from before it reads the file
    back, _ = ledger.entries_before(one, "docs/ledger", None)
    assert back is not None and _by_id(back) == _by_id(a)
    none, why = ledger.entries_before(one, "notes/todo.md", None)
    assert none is None and why.startswith("no notes/todo.md at origin/main ")


def test_another_repos_item_resolves_through_its_v2_ledger(tmp_path):
    two = _v2(tmp_path / "two")
    reg = ledger.Registry([str(two)])  # no origin/<default> there: its working tree, by the default rule
    open_id = next(e["id"] for e in lb.entries(LEDGER))
    archived = next(e["id"] for e in lb.entries(ARCHIVE))
    assert reg(f"two#{open_id}") == ("open", "")
    assert reg(f"two#{archived}") == ("archived", "")
    _commit(two)
    _git(two, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert ledger.Registry([str(two)])(f"two#{archived}") == ("archived", "")  # at origin/main, through git_io


def test_the_default_rule(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    assert ledger.ledger_path(root) == "docs/technical_debt.md"
    (root / "docs" / "ledger").mkdir(parents=True)
    assert ledger.ledger_path(root) == "docs/ledger"
    (root / ".shiftlead.yml").write_text("ledger: work/todo/\n", encoding="utf-8")
    assert ledger.ledger_path(root) == "work/todo"  # set wins, a trailing / dropped
    missing = ledger.reading(root, NOW, with_history=False)
    assert missing["error"] == "work/todo: No such file or directory"


def test_git_io_reads_a_directory_and_batches_only_entry_files(tmp_path):
    two = _v2(tmp_path / "two")
    (two / "docs" / "ledger" / "notes.txt").write_text("not an entry\n", encoding="utf-8")
    _commit(two)
    ls, read = ledger.git_io(two, "HEAD", "docs")
    names = ls("docs/ledger")
    assert "README.md" in names and "notes.txt" in names and "archive" not in names
    assert ls("docs/ledger/README.md") is None and ls("docs/nothing") is None
    assert lb.load("docs/ledger", ls, read) == lb.load("docs/ledger", *ledger.fs_io(two))
    assert read("docs/ledger/notes.txt") == "not an entry\n"  # fetched alone, when asked
    assert ledger.git_io(two, "no-such-ref", "docs") is None
    (two / "todo.md").write_text("# Todo\n", encoding="utf-8")
    (two / "ledger").mkdir()
    (two / "ledger" / "README.md").write_text("# Ledger\n", encoding="utf-8")
    _commit(two)
    top_ls, top_read = ledger.git_io(two, "HEAD")  # empty `under`: the top level and its `ledger/`, never all of it
    assert "todo.md" in top_ls("") and top_ls("ledger") == ["README.md"] and top_read("todo.md") == "# Todo\n"
    assert top_ls("docs/ledger") is None and top_read("docs/ledger/README.md") is None


_PARITY = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("dc_ledger", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
cases = json.loads(sys.argv[2])
present = set(json.loads(sys.argv[3]))
io = (lambda p: [] if p in present and not p.endswith(".md") else None,
      lambda p: "" if p in present and p.endswith(".md") else None)
print(json.dumps({"consts": [m.LEDGER_REL, m.ARCHIVE_REL, m.LEDGER_DIR_REL],
                  "out": [list(m.layout_at(r, a, io)) for r, a in cases]}))
"""


def test_layout_at_is_dev_cadences_rule():
    """`sessionorc.ledger.layout_at` is a copy of the pinned tree's, as `test_ledger_derived.py` holds
    `pickable` equal: its constants and its answer on each shape of path, with either layout present."""
    script = pinned_script("ledger.py")
    cases = [
        ["docs/technical_debt.md", "docs/technical_debt_archive.md"],
        ["docs/ledger", None],
        ["work/todo.md", "work/todo_archive.md"],
        ["work/todo", None],
        ["todo.md", "todo_archive.md"],
    ]
    for present in (["docs/technical_debt.md", "work/todo.md", "todo.md"], ["docs/ledger", "work/todo", "ledger"]):
        cp = subprocess.run(
            [sys.executable, "-c", _PARITY, str(script), json.dumps(cases), json.dumps(present)],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        theirs = json.loads(cp.stdout)
        here = set(present)
        io = (
            lambda p, here=here: [] if p in here and not p.endswith(".md") else None,
            lambda p, here=here: "" if p in here and p.endswith(".md") else None,
        )
        assert theirs["consts"] == [ledger.LEDGER_REL, ledger.ARCHIVE_REL, ledger.LEDGER_DIR_REL]
        assert theirs["out"] == [list(ledger.layout_at(r, a, io)) for r, a in cases]


@pytest.mark.parametrize("rel", ["docs/technical_debt.md", "docs/ledger"])
def test_a_ledger_in_neither_layout_reads_as_an_error(tmp_path, rel):
    root = tmp_path / "r"
    root.mkdir()
    got = ledger.reading(root, NOW, with_history=False, rel=rel)
    assert "entries" not in got and got["error"].endswith("No such file or directory")
