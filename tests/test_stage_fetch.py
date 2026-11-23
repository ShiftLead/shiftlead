"""What the tick's wiring fetches for an entry's facts (design §4.9c, TD-2051)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sessionorc.models import Session
from shiftlead import stage_fetch
from shiftlead.stage_fetch import (
    EntryOn,
    RepoFacts,
    entry_on,
    entry_text,
    facts_on,
    files_at,
    ledger_read,
    protected_at,
)
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


def test_a_v1_ledger_in_a_directory_reads(tmp_path: Path) -> None:
    root = tmp_path / "v1"
    root.mkdir()
    git(root, "init", "-q")
    commit(root, {"docs/technical_debt.md": f"# Ledger\n\n{entry(7)}", "docs/technical_debt_archive.md": entry(8)})
    read = ledger_read(root, "docs/technical_debt.md", "HEAD")
    assert read is not None
    assert entry_on(root, "HEAD", read, "TD-7").ledger == EntryLedger("open")
    assert entry_on(root, "HEAD", read, "TD-8").ledger == EntryLedger("archived")


def test_a_padded_file_renumbered_is_found_from_an_unpadded_id(repo: Path) -> None:
    commit(repo, {"docs/ledger/TD-015.md": entry(15)})
    git(repo, "mv", "docs/ledger/TD-015.md", "docs/ledger/TD-016.md")
    commit(repo, {"docs/ledger/TD-016.md": entry(16)})
    read = ledger_read(repo, "docs/ledger", "HEAD")
    assert read is not None
    assert entry_on(repo, "HEAD", read, "TD-15") == EntryOn(renumbered_to="TD-016")


def test_a_heading_in_a_code_fence_does_not_cut_the_entry_off(repo: Path) -> None:
    body = entry(21, "") + "\n```\n## not a heading\n```\n\n**Log:**\n- 2026-11-20: asked by the stage record: n1\n"
    commit(repo, {"docs/ledger/TD-021.md": body})
    read = ledger_read(repo, "docs/ledger", "HEAD")
    assert read is not None
    got = entry_on(repo, "HEAD", read, "TD-21").text
    assert got is not None and "asked by the stage record: n1" in got


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


FLOW = {
    "name": "f",
    "stages": [{"name": "Build", "does": "build"}, {"name": "Read", "does": "review", "only-when": "protected-files"}],
}


def pass_read(repo: Path, **over: Any) -> RepoFacts:
    read = ledger_read(repo, "docs/ledger", "HEAD")
    assert read is not None
    base: dict[str, Any] = {
        "root": repo,
        "ref": "HEAD",
        "read": read,
        "person": "paul",
        "team": "t",
        "now": datetime(2026, 11, 23, tzinfo=UTC),
        "doc": FLOW,
    }
    return RepoFacts(**{**base, **over})


def session(sid: str) -> Session:
    return Session(id=sid, name=sid, dir="/r", kind="agent", adapter="claude-code", state="working")


def test_facts_take_the_entrys_own_row_text_and_team_line(repo: Path) -> None:
    row = {"id": "TD-7", "team": "other"}
    got = facts_on(pass_read(repo, entries=({"id": "TD-8"}, row), teams=("t", "other")), "TD-7", None)
    assert got is not None
    assert got.entry is row and got.named == "other" and got.ledger == EntryLedger("open")
    assert got.text is not None and got.text.startswith("## TD-7:")


def test_an_entry_with_no_team_line_names_none(repo: Path) -> None:
    got = facts_on(pass_read(repo, entries=({"id": "TD-7", "team": ""},)), "TD-7", None)
    assert got is not None and got.named is None


def test_the_holders_session_and_open_ask_are_read_by_its_address(repo: Path) -> None:
    s = session("s1")
    record = {"tid": "TD-7", "stage": "build", "flow": "f", "holder": "s1@node"}
    got = facts_on(pass_read(repo, sessions={"s1@node": s}, read_nodes={"node"}, open_asks={"s1@node"}), "TD-7", record)
    assert got is not None and got.session is s and got.open_ask


def test_a_holder_on_an_unread_node_is_no_reading(repo: Path) -> None:
    record = {"tid": "TD-7", "stage": "build", "flow": "f", "holder": "s1@node"}
    assert facts_on(pass_read(repo, sessions={}, read_nodes={"other"}), "TD-7", record) is None


def test_a_holder_with_no_session_read_at_all_is_no_reading(repo: Path) -> None:
    record = {"tid": "TD-7", "stage": "build", "flow": "f", "holder": "s1"}
    assert facts_on(pass_read(repo), "TD-7", record) is None


def test_a_holder_on_a_node_that_was_read_and_lacks_it_is_gone(repo: Path) -> None:
    record = {"tid": "TD-7", "stage": "build", "flow": "f", "holder": "s1@node"}
    got = facts_on(pass_read(repo, sessions={}, read_nodes={"node"}), "TD-7", record)
    assert got is not None and got.session is None


def test_a_bare_holder_is_found_by_its_id(repo: Path) -> None:
    s = session("s1")
    record = {"tid": "TD-7", "stage": "build", "flow": "f", "holder": "s1"}
    got = facts_on(pass_read(repo, sessions={"s1": s}), "TD-7", record)
    assert got is not None and got.session is s


def test_a_padded_row_is_the_entrys_and_a_work_order_never_is(repo: Path) -> None:
    row = {"id": "TD-007", "team": "t"}
    orders = ({"id": "pr:12", "work_order": True}, {"id": "2026-01-05-67209175"}, {"id": "TD-7", "work_order": True})
    got = facts_on(pass_read(repo, entries=(*orders, row)), "TD-7", None)
    assert got is not None and got.entry is row


def test_a_holder_read_as_gone_has_no_session(repo: Path) -> None:
    record = {"tid": "TD-7", "stage": "build", "flow": "f", "holder": "s1"}
    got = facts_on(pass_read(repo, sessions={}), "TD-7", record)
    assert got is not None and got.session is None


def test_a_closed_records_old_holder_on_an_unread_node_stops_nothing(repo: Path) -> None:
    record = {"tid": "TD-7", "holder": "s1@node", "closed_at": "2026-11-20T00:00:00Z"}
    got = facts_on(pass_read(repo), "TD-7", record)
    assert got is not None and got.session is None


def test_the_flow_a_record_was_written_under_is_passed_only_when_it_is_that_flow(repo: Path) -> None:
    was = {"name": "old", "stages": []}
    under_old = {"tid": "TD-7", "stage": "build", "flow": "old"}
    under_other = {**under_old, "flow": "older"}
    assert facts_on(pass_read(repo, was=was), "TD-7", under_old).was is was
    assert facts_on(pass_read(repo, was=was), "TD-7", under_other).was is None


def test_an_entry_in_flight_to_merge_reads_as_merge_running(repo: Path) -> None:
    assert facts_on(pass_read(repo, merging={"TD-7"}), "TD-7", None).merge_running
    assert not facts_on(pass_read(repo, merging={"TD-8"}), "TD-7", None).merge_running


def test_files_are_read_at_the_open_head_for_an_only_when_stage(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[int, str | None]] = []
    monkeypatch.setattr(stage_fetch, "files_at", lambda _r, pr, head: asked.append((pr, head)) or ["a.py"])
    record = {"tid": "TD-7", "stage": "read", "flow": "f", "pr": 5}
    rows = ({"number": 5, "state": "open", "head": "abc"},)
    got = facts_on(pass_read(repo, rows=rows, protected=["src/**"]), "TD-7", record)
    assert asked == [(5, "abc")] and got.read_at == "abc" and got.files == ["a.py"]


@pytest.mark.parametrize(
    ("stage", "rows", "protected"),
    [
        ("build", ({"number": 5, "state": "open", "head": "abc"},), ["src/**"]),  # not an only-when stage
        ("read", ({"number": 5, "state": "merged", "head": "abc"},), ["src/**"]),  # no open head
        ("read", ({"number": 5, "state": "open", "head": "abc"},), None),  # the protected files were not read
    ],
)
def test_no_files_are_asked_of_the_forge_where_they_decide_nothing(
    repo: Path, monkeypatch: pytest.MonkeyPatch, stage: str, rows: tuple, protected: list[str] | None
) -> None:
    monkeypatch.setattr(stage_fetch, "files_at", lambda *_: pytest.fail("asked the forge"))
    record = {"tid": "TD-7", "stage": stage, "flow": "f", "pr": 5}
    got = facts_on(pass_read(repo, rows=rows, protected=protected), "TD-7", record)
    assert got is not None and got.read_at is None and got.files is None
