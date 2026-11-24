"""What the tick's wiring fetches for an entry's facts (design §4.9c, TD-2051)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sessionorc.models import MailEntry, ProgressEntry, Session
from shiftlead import stage_fetch, stage_work
from shiftlead.stage_fetch import (
    EntryOn,
    RepoFacts,
    entry_on,
    entry_text,
    facts_on,
    files_at,
    held_read,
    ledger_read,
    over_line,
    protected_at,
    rows_of,
    sessions_read,
    stranded,
    team_flow,
    teams_on,
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


def no_read(n: int) -> None:
    pytest.fail(f"read #{n} by its number")


def test_an_open_rows_marks_survive_its_copy_in_the_recent_read() -> None:
    opened = {"number": 5, "state": "open", "fork": True, "filing": False, "filing_head": "a", "head": "a"}
    recent = {"number": 5, "state": "open", "head": "a"}
    assert rows_of({"open": [opened], "recent": [recent]}, [5], no_read) == (opened,)


def test_a_merge_in_the_later_read_hides_the_stale_open_row() -> None:
    opened = {"number": 5, "state": "open", "head": "a"}
    merged = {"number": 5, "state": "merged", "head": "a"}
    assert rows_of({"open": [opened], "recent": [merged]}, [5], no_read) == (merged,)


def test_a_pull_request_opened_between_the_reads_is_kept_and_unread_as_filing() -> None:
    recent = {"number": 6, "state": "open", "branch": "td7-a", "head": "b"}
    got = rows_of({"open": [], "recent": [recent]}, [], no_read)
    assert got == (recent,)
    assert stage_work.entry_work("TD-7", got).state == "unread"


def test_a_record_pull_request_outside_the_reads_is_read_by_number() -> None:
    row = {"number": 9, "state": "merged"}
    assert rows_of({"open": [], "recent": []}, [9], lambda n: row if n == 9 else None) == (row,)


@pytest.mark.parametrize("prs", [None, {"error": "gh failed", "open": [{"number": 5, "state": "open"}]}])
def test_a_failed_reading_is_no_rows(prs: dict | None) -> None:
    assert rows_of(prs, [5], no_read) is None


def sent(kind: str, **over: Any) -> MailEntry:
    return MailEntry(id="m-1", from_="s1", to=["s2"], text="q", at="2026-11-23T00:00:00Z", kind=kind, **over)


@pytest.mark.parametrize(
    ("entry", "waits"),
    [
        (sent("ask"), True),
        (sent("steer", default="go"), True),
        (sent("note"), False),
        (sent("ask", closed_reason="answered"), False),
    ],
)
def test_an_open_ask_or_steer_it_sent_is_a_sessions_own_wait(entry: MailEntry, waits: bool) -> None:
    s = session("s1")
    s.outbox.append(entry)
    assert ("s1@node" in sessions_read({"s1@node": s}, {"node"}).open_asks) is waits


def test_only_a_snapshotted_node_counts_as_read(repo: Path) -> None:
    got = sessions_read({}, {"up"})
    record = {"tid": "TD-7", "stage": "build", "flow": "f", "holder": "s1@down"}
    assert got.read_nodes == {"up"}
    assert facts_on(pass_read(repo, sessions=got.sessions, read_nodes=got.read_nodes), "TD-7", record) is None


OLD_FLOW = "name: f\nstages:\n- name: Build\n"
NEW_FLOW = "name: f\nstages:\n- name: Make\n"


def test_a_passing_flow_runs_and_is_to_replace_the_copy_after_the_pass() -> None:
    got = team_flow(NEW_FLOW, [], OLD_FLOW)
    assert got is not None and got.doc["stages"][0]["name"] == "Make"
    assert got.was is not None and got.was["stages"][0]["name"] == "Build"
    assert got.put == NEW_FLOW and not got.problems


def test_a_first_passing_flow_has_nothing_it_replaces() -> None:
    got = team_flow(NEW_FLOW, [], None)
    assert got is not None and got.was is None and got.put == NEW_FLOW


def test_an_unchanged_flow_writes_nothing() -> None:
    got = team_flow(OLD_FLOW, [], OLD_FLOW)
    assert got is not None and got.was is None and got.put is None


@pytest.mark.parametrize(
    ("current", "problems", "told"),
    [
        (NEW_FLOW, ["a stage has no way out"], ("a stage has no way out",)),
        (None, [], ("the flow could not be read",)),
        ("a: [", [], ("the flow could not be read",)),
        ("- a list", [], ("the flow could not be read",)),
        ("[" * 5000, [], ("the flow could not be read",)),
        ("", [], ("the flow could not be read",)),
    ],
)
def test_a_flow_that_fails_keeps_the_last_good_copy(current: str | None, problems: list[str], told: tuple) -> None:
    got = team_flow(current, problems, OLD_FLOW)
    assert got is not None and got.doc["stages"][0]["name"] == "Build"
    assert got.put is None and got.was is None and got.problems == told


def test_a_passing_flow_over_an_unreadable_copy_replaces_it() -> None:
    got = team_flow(NEW_FLOW, [], "a: [")
    assert got is not None and got.was is None and got.put == NEW_FLOW


@pytest.mark.parametrize("kept", [None, "", "a: ["])
def test_no_passing_flow_and_no_good_copy_is_no_reading(kept: str | None) -> None:
    assert team_flow(NEW_FLOW, ["broken"], kept) is None


def holder(sid: str, repo: str, pr: int | None = None, branch: str | None = None) -> Session:
    s = session(sid)
    s.repo = repo
    s.git = {"branch": branch} if branch else None
    if pr is not None:
        s.progress = [ProgressEntry(ref=f"pr:{pr}", status="claimed", at="2026-11-23T00:00:00Z")]
    return s


OPEN_ROWS = ({"number": 7, "state": "open", "branch": "td7-x"}, {"number": 8, "state": "open", "branch": "td8-x"})


def test_a_live_session_of_the_repo_holds_its_pull_request_by_claim_or_branch(tmp_path: Path) -> None:
    root = str(tmp_path)
    graph = {"a": holder("a", root, pr=7), "b": holder("b", root, branch="td8-x")}
    assert held_read(OPEN_ROWS, sessions_read(graph, ()), {"": [root]}, local="home") == {7, 8}


def test_a_session_of_another_repo_holds_nothing_here(tmp_path: Path) -> None:
    graph = {"a": holder("a", str(tmp_path / "other"), pr=7)}
    assert held_read(OPEN_ROWS, sessions_read(graph, ()), {"": [str(tmp_path)]}, local="home") == frozenset()


def test_the_same_path_on_another_node_is_another_repo() -> None:
    graph = {"a@n2": holder("a", "/r", pr=7), "b@n1": holder("b", "/r", pr=8)}
    assert held_read(OPEN_ROWS, sessions_read(graph, {"n1", "n2"}), {"n1": ["/r"]}, local="home") == {8}


@pytest.mark.parametrize(("session_path", "checkout"), [("/r/./x", "/r/x"), ("/r/x/", "/r/x"), ("/r/x", "/r//x/")])
def test_a_node_path_differing_only_in_form_is_the_same_checkout(session_path: str, checkout: str) -> None:
    graph = {"a@n1": holder("a", session_path, pr=7)}
    assert held_read(OPEN_ROWS, sessions_read(graph, {"n1"}), {"n1": [checkout]}, local="home") == {7}


def test_a_node_with_a_checkout_that_was_not_read_leaves_held_unknown() -> None:
    assert held_read(OPEN_ROWS, sessions_read({}, ()), {"n1": ["/r"]}, local="home") is None


def test_an_unread_node_with_no_checkout_of_the_repo_changes_nothing(tmp_path: Path) -> None:
    graph = {"a": holder("a", str(tmp_path), pr=7)}
    assert held_read(OPEN_ROWS, sessions_read(graph, ()), {"": [str(tmp_path)]}, local="home") == {7}


def test_unknown_held_is_no_reading_for_an_entry_with_no_live_record(repo: Path) -> None:
    facts = pass_read(repo, held=None, sessions={})
    assert facts_on(facts, "TD-7", None) is None
    assert facts_on(facts, "TD-7", {"holder": "", "closed_at": "2026-11-20"}) is None
    assert facts_on(facts, "TD-7", {"holder": "", "stage": "Build"}) is not None


@pytest.mark.parametrize("key", ["", "home"])
def test_a_key_naming_the_homes_own_host_is_the_homes_session(tmp_path: Path, key: str) -> None:
    graph = {"a@home": holder("a", str(tmp_path), pr=7)}
    assert held_read(OPEN_ROWS, sessions_read(graph, ()), {key: [str(tmp_path)]}, local="home") == {7}


def test_a_symlink_loop_is_no_session_of_the_repo_and_stops_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    resolve = Path.resolve

    def resolving(self: Path, strict: bool = False) -> Path:
        if self == loop:  # as 3.12 does; 3.13 resolves a self-loop to itself, so the guard is pinned on both
            raise RuntimeError(f"Symlink loop from {self!r}")
        return resolve(self, strict)

    monkeypatch.setattr(Path, "resolve", resolving)
    graph = {"a": holder("a", str(loop), pr=7), "b": holder("b", str(tmp_path), pr=8)}
    assert held_read(OPEN_ROWS, sessions_read(graph, ()), {"": [str(tmp_path)]}, local="home") == {8}


def test_a_live_record_is_read_whether_or_not_held_is_known(repo: Path) -> None:
    record = {"holder": "", "stage": "Build", "flow": "f", "team": "t"}
    known, unknown = (facts_on(pass_read(repo, held=h, sessions={}), "TD-7", record) for h in ((), None))
    assert known == unknown is not None


def test_the_teams_are_those_the_ledger_declares(repo: Path) -> None:
    commit(repo, {"docs/ledger/README.md": README + "\nFields: Team = Build | docs\n"})
    read = ledger_read(repo, "docs/ledger", "HEAD")
    assert read is not None and teams_on(read) == ("build", "docs")


def test_a_ledger_declaring_no_team_has_none(repo: Path) -> None:
    read = ledger_read(repo, "docs/ledger", "HEAD")
    assert read is not None and teams_on(read) == ()


@pytest.mark.parametrize(
    ("host", "over"),
    [
        ({"t": {"balance": {"crossed": True}}}, True),
        ({"t": {"balance": {"crossed": False}}}, False),
        ({"t": {"balance": "crossed"}}, False),
        ({"t": "not a record"}, False),
        ({"t": {}}, False),
        ({"other": {"balance": {"crossed": True}}}, False),
        ({}, False),
        (None, False),
    ],
)
def test_a_team_is_over_its_line_only_where_its_own_mark_is_crossed(host: dict | None, over: bool) -> None:
    assert over_line(host, "t") is over


STAGED = {"stages": [{"name": "Build"}, {"name": "Read Twice"}]}


def staged(name: str = "build-td-7", lane: tuple[str, ...] = ("TD-7",), **over: Any) -> Session:
    s = session("a")
    s.name, s.team, s.lane, s.unattended = name, "t", list(lane), True
    for k, v in over.items():
        setattr(s, k, v)
    return s


def strand(graph: dict[str, Session], records: dict | None = None, nodes: tuple[str, ...] = ()) -> tuple[str, ...]:
    return stranded(sessions_read(graph, nodes), records or {}, "t", STAGED, local="home").seen


def test_a_live_stage_session_no_record_names_is_stranded() -> None:
    assert strand({"a": staged()}) == ("a",)
    assert strand({"a": staged("read-twice-td-7")}) == ("a",)


def test_a_claimed_session_no_record_names_is_stranded() -> None:
    assert strand({"a": staged(progress=[ProgressEntry(ref="TD-7", status="claimed")])}) == ("a",)


@pytest.mark.parametrize("holder", ["a", "a@home"])
def test_the_records_holder_is_not_stranded_in_either_address_form(holder: str) -> None:
    assert strand({"a": staged()}, {"TD-7": {"holder": holder}}) == ()


def test_a_closed_records_old_holder_is_stranded() -> None:
    assert strand({"a": staged()}, {"TD-7": {"holder": "a", "closed_at": "2026-11-20"}}) == ("a",)


@pytest.mark.parametrize("status", ["done", "dropped"])
def test_a_session_that_reported_its_stage_over_is_left_to_exit(status: str) -> None:
    assert strand({"a": staged(progress=[ProgressEntry(ref="TD-7", status=status)])}) == ()


def test_a_session_on_a_node_not_read_is_left_alone() -> None:
    assert strand({"a@n1": staged()}) == ()
    assert strand({"a@n1": staged()}, nodes=("n1",)) == ("a@n1",)


@pytest.mark.parametrize(
    "s",
    [
        staged(team="other"),
        staged(state="exited"),
        staged(state="closed"),
        staged(unattended=False),
        staged(seat="techlead"),
        staged(superseded_by="b"),
        staged(lane=("free-pick",)),
        staged(lane=("TD-7", "TD-8")),
        staged("grinder-td-7"),
        staged("build-td-8"),
    ],
)
def test_anything_else_is_not_a_stranded_stage_session(s: Session) -> None:
    assert strand({"a": s}) == ()


def test_only_a_session_stranded_on_two_passes_running_is_to_be_ended() -> None:
    read = sessions_read({"a": staged()}, ())
    first = stranded(read, {}, "t", STAGED, local="home")
    assert first.seen == ("a",) and first.end == ()
    assert stranded(read, {}, "t", STAGED, local="home", before=first.seen).end == ("a",)


def test_a_session_that_reported_between_the_passes_is_not_ended() -> None:
    done = staged(progress=[ProgressEntry(ref="TD-7", status="done")])
    assert stranded(sessions_read({"a": done}, ()), {}, "t", STAGED, local="home", before=("a",)).end == ()


def test_a_padded_id_matches_its_session_name_and_its_done_row() -> None:
    assert strand({"a": staged("build-td-007", lane=("TD-007",))}) == ("a",)
    done = [ProgressEntry(ref="TD-007", status="done")]
    assert strand({"a": staged("build-td-007", lane=("TD-007",), progress=done)}) == ()
