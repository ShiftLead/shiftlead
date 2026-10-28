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
    (two / "tasks").mkdir()
    (two / "tasks" / "TD-001.md").write_text("## TD-001: a\n", encoding="utf-8")
    _commit(two)
    tasks_ls, _ = ledger.git_io(two, "HEAD", rel="tasks")  # a set top-level directory is listed too
    assert tasks_ls("tasks") == ["TD-001.md"]


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


def _fault(root: Path) -> str:
    """Breaks one entry file of the v2 ledger at `root`: its heading names another id. The fault's words."""
    led = root / "docs" / "ledger"
    first = next(p for p in sorted(led.glob("TD-*.md")))
    text = first.read_text(encoding="utf-8")
    first.write_text(text.replace("## TD-", "## TD-9", 1), encoding="utf-8")
    (problem,) = lb.v2_problems("docs/ledger", *ledger.fs_io(root))
    return problem


def test_a_faulted_v2_ledger_is_reported_not_read(tmp_path):
    """§4.4 *A faulted v2 ledger is reported, not read*: the reading's ledger is an error with
    `v2_problems()`'s words, an id of it keeps its block, and at a past revision it reads as none."""
    two = _v2(tmp_path / "two")
    words = _fault(two)
    got = ledger.reading(two, NOW, with_history=False)
    assert "entries" not in got and got["error"] == f"docs/ledger is faulted: {words}"
    open_id = next(e["id"] for e in lb.entries(LEDGER))
    state, why = ledger.Registry([str(two)])(f"two#{open_id}")
    assert state == "unresolved" and why.endswith(f"docs/ledger is faulted: {words}")
    (two / ".shiftlead.yml").write_text("ledger: docs/technical_debt.md\n", encoding="utf-8")  # set, and gone
    assert ledger.Registry([str(two)])(f"two#{open_id}")[1].endswith(f"docs/ledger is faulted: {words}")
    (two / ".shiftlead.yml").unlink()
    _commit(two)
    _git(two, "update-ref", "refs/remotes/origin/main", "HEAD")
    none, why = ledger.entries_before(two, "docs/ledger", None)
    assert none is None and why.startswith(f"docs/ledger is faulted: {words} at origin/main ")


def test_a_directory_whose_readme_declares_no_v2_is_faulted(tmp_path):
    two = _v2(tmp_path / "two")
    readme = two / "docs" / "ledger" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8").replace("Ledgerboard: 2", ""), encoding="utf-8")
    got = ledger.reading(two, NOW, with_history=False)
    assert "entries" not in got and "README.md declares no `Ledgerboard: 2`" in got["error"]
    readme.unlink()
    assert "README.md declares no `Ledgerboard: 2`" in ledger.reading(two, NOW, with_history=False)["error"]


def test_the_seams_read_a_v2_ledger_as_its_v1_twin(tmp_path):
    """§4.4 *The seams*: a v2 directory's major from its README, its entry count as its v1 twin's; a faulted
    one *unreadable* with the words; a path neither a file nor a directory *absent*."""
    from sessionorc import seams

    one, two = _v1(tmp_path / "one"), _v2(tmp_path / "two")
    a, b = seams.ledger(one), seams.ledger(two)
    assert (a["state"], a["major"], a["directory"]) == ("ok", 1, False)
    assert (b["path"], b["state"], b["major"], b["directory"]) == ("docs/ledger", "ok", 2, True)
    assert a["entries"] == b["entries"] == len(lb.entries(LEDGER))
    words = _fault(two)
    got = seams.ledger(two)
    assert got["state"] == "unreadable" and got["why"] == words and got["entries"] is None
    assert seams.ledger_lack(got, two) == f"unserved: the ledger at docs/ledger does not parse — {words}"
    (two / ".shiftlead.yml").write_text("ledger: work/todo\n", encoding="utf-8")
    assert seams.ledger(two)["state"] == "absent"


def test_a_set_ledger_gone_from_the_tree_reads_the_other_layout_and_is_warned_of(tmp_path):
    """§4.4 *Either layout*: a set `ledger:` read live goes through `layout_at`, and the seams warn."""
    from sessionorc import seams

    two = _v2(tmp_path / "two")
    (two / ".shiftlead.yml").write_text("ledger: docs/technical_debt.md\n", encoding="utf-8")
    got = seams.reading(two)
    assert got["ledger"]["path"] == "docs/ledger" and got["ledger"]["state"] == "ok"
    assert "`ledger:` names docs/technical_debt.md, which is gone: reading docs/ledger" in got["warnings"]
    read = ledger.reading(two, NOW, with_history=False)
    assert read["path"] == "docs/ledger" and read["entries"]
    (two / ".shiftlead.yml").unlink()
    assert not any("which is gone" in w for w in seams.reading(two)["warnings"])


@pytest.mark.parametrize("pinned", [False, True])
def test_a_v2_ledger_under_a_tree_that_predates_its_reader_is_unserved(tmp_path, monkeypatch, pinned):
    """§5 *Which dev-cadence*: a directory under a dev-cadence older than `OLDEST_V2` lacks *predates*,
    which the sync cures (its key passed over by the sync pass); a v1 file under the same tree does not."""
    from sessionorc import cadence, seams

    asked: list[str] = []

    def descends(commit, roster, source="", oldest=None):
        oldest = oldest or cadence.OLDEST
        asked.append(oldest)
        return oldest != cadence.OLDEST_V2, None

    monkeypatch.setattr(seams, "descends", descends)
    monkeypatch.setattr(seams.cadence, "pinned", lambda root: pinned)
    monkeypatch.setattr(seams, "_lock", lambda root: ({"source": "x", "files_commit": "abc1234def"}, None))
    one, two = _v1(tmp_path / "one"), _v2(tmp_path / "two")
    assert seams.reading(one)["ledger"]["state"] == "ok" and asked == [cadence.OLDEST]
    got = seams.reading(two)
    assert got["ledger"]["state"] == "predates"
    cure = "bump the pin" if pinned else "sync it"
    words = f"unserved: the ledger is a directory and dev-cadence at abc1234 predates its v2 reader (b9236c8) — {cure}"
    assert {"key": "ledger_age", "words": words} in got["serve"]["lacks"]
    assert words not in seams.unserved({"seams": got}, but=("age", "ledger_age"))
    asked.clear()
    seams.reading(two, old=got)  # the age is carried: ancestry never changes
    assert asked == []


_HEAD = "# Technical debt\n\n"


def _entry(n: int, title: str) -> str:
    return f"## TD-{n:03d}: {title}\n\n**Priority:** Low\n**Status:** Open.\n\n---\n"


def _commit_as(root: Path, subject: str) -> None:
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", subject)


def _split_history(tmp_path: Path) -> Path:
    """A v1 ledger with TD-001 and TD-002; TD-002 archived (#5); the split (#6); TD-003 added as a file (#7);
    TD-001 moved into `archive/` (#8). `origin/main` at the tip."""
    root = tmp_path / "h"
    (root / "docs").mkdir(parents=True)
    _git(tmp_path, "init", "-q", str(root))
    led, arch = root / "docs" / "technical_debt.md", root / "docs" / "technical_debt_archive.md"
    led.write_text(_HEAD + _entry(1, "one") + "\n" + _entry(2, "two"), encoding="utf-8")
    arch.write_text("# Archive\n\n", encoding="utf-8")
    _commit_as(root, "open both (#4)")
    led.write_text(_HEAD + _entry(1, "one"), encoding="utf-8")
    arch.write_text("# Archive\n\n" + _entry(2, "two"), encoding="utf-8")
    _commit_as(root, "archive TD-002 (#5)")
    files = lb.split(led.read_text(encoding="utf-8"), arch.read_text(encoding="utf-8"))
    led.unlink()
    arch.unlink()
    for rel, text in files.items():
        p = root / "docs" / "ledger" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _commit_as(root, "split the ledger (#6)")
    (root / "docs" / "ledger" / "TD-003.md").write_text(_entry(3, "three"), encoding="utf-8")
    _commit_as(root, "TD-003 (#7)")
    _git(root, "mv", "docs/ledger/TD-001.md", "docs/ledger/archive/TD-001.md")
    _commit_as(root, "archive TD-001 (#8)")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def test_a_v2_ledgers_history_reads_across_its_split(tmp_path):
    """§4.4 *Either layout*, *Across a split*: the split opens and closes nothing, an entry keeps its v1
    opening, one closed before the split stays closed, a file added under the directory opens and one moved
    into `archive/` closes, with its PR."""
    root = _split_history(tmp_path)
    text = lb.load("docs/ledger", *ledger.fs_io(root))[0]
    life = ledger.history(root, "docs/ledger", text)
    assert life is not None and set(life) == {"TD-001", "TD-002", "TD-003"}
    assert life["TD-002"].closed is not None and life["TD-002"].pr == 5
    assert life["TD-001"].opened == life["TD-002"].opened  # its v1 opening, through the split
    assert life["TD-001"].closed is not None and life["TD-001"].pr == 8
    assert life["TD-003"].closed is None and life["TD-003"].title == "three"
    got = ledger.reading(root, datetime.now(UTC))
    assert "history_error" not in got and {e["id"] for e in got["recent"]} >= {"TD-001", "TD-003"}


def test_a_ledger_born_v2_opens_its_first_files(tmp_path):
    """A commit adding `README.md` with no v1 headings removed is no split: its entry files open."""
    two = _v2(tmp_path / "two")
    _commit_as(two, "a v2 ledger (#3)")
    text = lb.load("docs/ledger", *ledger.fs_io(two))[0]
    life = ledger.history(two, "docs/ledger", text)
    assert life and {e["id"] for e in lb.entries(LEDGER)} <= set(life)


def test_the_rows_a_merged_pr_added_read_a_v2_ledger(tmp_path):
    """§4.4 *Either layout*: `_ledger_rows_on_main` takes the `TD-NNN.md` files a squash commit adds directly
    under the directory, none for the split, none for a move into `archive/`; a carried v1 path still reads."""
    from sessionorc import reports

    root = _split_history(tmp_path)
    assert reports._ledger_rows_on_main(root, 7, "docs/ledger") == ["TD-003"]
    assert reports._ledger_rows_on_main(root, 7, "docs/technical_debt.md") == ["TD-003"]  # carried from before
    assert reports._ledger_rows_on_main(root, 6, "docs/ledger") == []  # the split adds its README
    assert reports._ledger_rows_on_main(root, 8, "docs/ledger") == []  # a move into archive/
    assert reports._ledger_rows_on_main(root, 4, "docs/ledger") == ["TD-001", "TD-002"]  # before it: the file


def test_the_ticks_change_test_reads_a_directory_but_not_its_rank_file(tmp_path):
    """§4.4 *What changes with no one file*: the newest mtime among the directory, `archive/`, the entry
    files of both and `README.md`, with the resolved path; `rank.yml` alone moves nothing."""
    import os

    two = _v2(tmp_path / "two")
    base = two / "docs" / "ledger"
    rank = two / lb.rank_path("docs/ledger")
    rank.write_text("TD-001: 0\n", encoding="utf-8")
    for p in [base, *base.rglob("*")]:
        os.utime(p, (1000, 1000))
    first = ledger.stamp(two)
    assert first == ("docs/ledger", 1000)
    rank.write_text("TD-001: 1\n", encoding="utf-8")  # a rank write, in place: the directory's mtime stays
    assert rank.stat().st_mtime > 1000 and ledger.stamp(two) == first
    entry = next(base.glob("TD-*.md"))
    os.utime(entry, (2000, 2000))
    assert ledger.stamp(two) == ("docs/ledger", 2000)
    archived = next((base / lb.LEDGER_ARCHIVE).glob("TD-*.md"))  # an archived entry edited in place
    os.utime(archived, (3000, 3000))
    assert ledger.stamp(two) == ("docs/ledger", 3000)
    os.utime(base / lb.LEDGER_README, (4000, 4000))
    assert ledger.stamp(two) == ("docs/ledger", 4000)
    one = _v1(tmp_path / "one")
    assert ledger.stamp(one)[0] == "docs/technical_debt.md"


def test_the_queues_archive_reads_a_v2_archive_as_its_v1_twin(tmp_path):
    """§4.4 *Completed cards*' cache: a v2 `archive/` reads the v1 archive's entries (a set by id), and an
    unchanged directory is served from the cache."""
    from sessionorc import queue

    one, two = _v1(tmp_path / "one"), _v2(tmp_path / "two")
    a = queue.archive_entries(ledger.archive_of(one, "docs/technical_debt.md"))
    path = ledger.archive_of(two, "docs/ledger")
    assert path == two / "docs" / "ledger" / "archive"
    b = queue.archive_entries(path)
    assert a and {e["id"] for e in a} == {e["id"] for e in b}
    assert queue.archive_entries(path) is b
    (path / "TD-999.md").write_text(_entry(999, "late"), encoding="utf-8")
    assert "TD-999" in {e["id"] for e in queue.archive_entries(path)}


def test_the_rank_prunes_archive_reads_a_v2_archive(tmp_path):
    """§4.4 *The rank file*: `_rank_lined` weighs a v2 ledger's `archive/` as it does a v1 archive file."""
    from sessionorc.agent_rank import RankMixin

    got = {}
    for name, root in (("one", _v1(tmp_path / "one")), ("two", _v2(tmp_path / "two"))):
        rel = "docs/technical_debt.md" if name == "one" else "docs/ledger"
        archived = next(e["id"] for e in lb.entries(ARCHIVE))
        open_id = next(e["id"] for e in lb.entries(LEDGER))
        rank = root / lb.rank_path(rel)
        rank.write_text(f"{archived}: 0\n{open_id}: 1\nTD-9999: 2\n", encoding="utf-8")
        led = ledger.reading(root, NOW, with_history=False)
        got[name] = RankMixin._rank_lined(None, {name: (str(root), lb.rank_path(rel), led)})[name]
    assert got["one"] == got["two"] and len(got["one"]) == 2
