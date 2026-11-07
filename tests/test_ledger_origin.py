"""TD-1507 (TD-1471 slice 1), design §4.4 *The ledger is read against origin, as the board is*: the ledger reading
— entries, `archive/`, the README and the rank file — reads each id from `origin/<default>` as last fetched or from
the checkout by one rule, by id, and says where it came from in `origin` `{source, case, files}`; its history,
`written`, the stamp, the Queue's archive and the rank's prune read the same files. Each test is a scratch repo with
a bare origin, a second clone that pushes to it, and the checkout left behind."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from conftest import with_origin
from test_queue import NOW, archives

from sessionorc import ledger, queue, workorders
from sessionorc import ledgerboard as lb


def git(root: Path, *args: str, when: datetime | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}  # fmt: skip
    if when is not None:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = when.isoformat()
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()


def entry(n: int, title: str, **fields: str) -> str:
    head = "".join(f"**{k.replace('_', ' ').capitalize()}:** {v}\n" for k, v in fields.items())
    return f"## TD-{n:03d}: {title}\n\n{head or '**Priority:** Low\n'}\n"


V1 = "# Technical Debt\n\n"
V1_ARCHIVE = "# Archive\n\n"


def write(root: Path, files: dict[str, str | None]) -> None:
    for rel, text in files.items():
        p = root / rel
        if text is None:
            p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")


def v2_files(open_: list[str], archived: list[str] = ()) -> dict[str, str]:
    """A v2 ledger's files, `lb.split()` of the v1 twin."""
    return {f"docs/ledger/{rel}": t for rel, t in lb.split(V1 + "".join(open_), V1_ARCHIVE + "".join(archived)).items()}


def scratch(tmp_path: Path, files: dict[str, str], when: datetime | None = None) -> tuple[Path, Path]:
    """(the checkout, another clone) of one bare origin holding `files` on `main`."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root, files)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "seed", when=when)
    with_origin(root)
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(root.parent / "repo-origin.git"), str(other))
    return root, other


def land(other: Path, files: dict[str, str | None], msg: str = "change", when: datetime | None = None) -> None:
    """A merge on origin by another clone: the checkout is not pulled."""
    write(other, files)
    git(other, "add", "-A")
    git(other, "commit", "-qm", msg, when=when)
    git(other, "push", "-q", "origin", "main")


def fetch(root: Path) -> None:
    assert workorders.fetch_origin(root).ok


def by_id(led: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in led["entries"]}


def test_an_entry_merged_on_origin_reads_after_the_fetch_without_the_pull(tmp_path):
    """A gate lifted and merged on origin by another clone: before the fetch the checkout's, after it origin's,
    `origin` naming the file it read; the Queue, the lanes and the Inbox's ledger rows read it."""
    from shiftlead.ui.inbox import ledger_for_you

    gated = entry(1, "a gated one", Priority="High", Blocked_by="decision (paul)")
    root, other = scratch(tmp_path, v2_files([gated, entry(2, "free")]))
    land(other, {"docs/ledger/TD-001.md": entry(1, "a gated one", Priority="High")}, "TD-001: Go (#5)")
    led = ledger.reading(root, NOW, with_history=False)
    assert by_id(led)["TD-001"]["blocked_by"] and led["origin"] == {"source": "checkout", "case": "matches", "files": 0}
    fetch(root)
    led = ledger.reading(root, NOW, with_history=False)
    e = by_id(led)["TD-001"]
    assert e["blocked_by"] == [] and e["for_page"] == "pickable"
    assert led["origin"] == {"source": "origin", "case": "behind", "files": 1}
    assert "decision (paul)" in (root / "docs/ledger/TD-001.md").read_text(), "the checkout was not pulled"
    repos = {str(root): {"name": "repo", "root": str(root), "remote": "", "ledger": led, "prs": {"open": []}}}
    card = next(c for c in queue.reading(repos, [], NOW, archived=archives(repos))["cards"] if c["id"] == "repo#TD-001")
    assert card["status"] != "needs you"
    rows = [r.get("id") for g in ledger_for_you(repos, [])["groups"] for r in g["rows"]]
    assert "TD-001" not in rows
    lanes = ledger.in_lanes(led["entries"], [{"id": "w", "name": "w", "lane": ["free-pick"]}])
    assert lanes is not None and "TD-001" in lanes["pickable"]


def test_an_entry_archived_on_origin_reads_archived_once_beside_an_uncommitted_edit(tmp_path):
    """Origin moved TD-001 into `archive/` while the checkout holds an uncommitted edit to its open file: one entry,
    archived — the ledger not faulted — and `case` *both*; an entry added on origin is listed."""
    root, other = scratch(tmp_path, v2_files([entry(1, "done soon"), entry(2, "stays")]))
    land(other, {"docs/ledger/TD-001.md": None, "docs/ledger/archive/TD-001.md": entry(1, "done soon"),
                 "docs/ledger/TD-003.md": entry(3, "new on origin")}, "TD-001: archived (#7)")  # fmt: skip
    write(root, {"docs/ledger/TD-001.md": entry(1, "done soon, edited here")})
    fetch(root)
    led, gone = ledger.read(root, NOW, with_history=False)
    assert "error" not in led, led
    assert sorted(by_id(led)) == ["TD-002", "TD-003"]
    assert [e["id"] for e in gone or []] == ["TD-001"]
    assert led["origin"]["case"] == "both" and led["origin"]["source"] == "origin"


def test_an_archived_entry_on_origin_is_completed_and_drawn_done_before_the_pull(tmp_path):
    """An entry archived on origin: its `completed` row names the PR (the history reads origin's log) and the Queue
    draws it done — a Completed card — before the pull."""
    root, other = scratch(tmp_path, v2_files([entry(1, "a")]), when=NOW - timedelta(days=2))
    done_entry = entry(1, "a") + f"**Resolved:** {NOW.date().isoformat()} (PR #7)\n"
    archived = {"docs/ledger/TD-001.md": None, "docs/ledger/archive/TD-001.md": done_entry}
    land(other, archived, "TD-001: done (#7)", when=NOW - timedelta(hours=1))
    fetch(root)
    led, gone = ledger.read(root, NOW)
    assert by_id(led) == {}
    (c,) = [c for c in led["recent"] if c["closed"]]
    assert (c["id"], c["pr"]) == ("TD-001", 7)
    done = ledger.completed(led["recent"], [])
    assert done[0]["pr"] == 7
    repos = {str(root): {"name": "repo", "root": str(root), "remote": "", "ledger": led, "prs": {"open": []},
                         "completed": done}}  # fmt: skip
    assert archives(repos)[str(root)] == [], "the checkout's own archive has none of it"
    got = queue.reading(repos, [], NOW, archived={str(root): gone or []})
    assert [x["ids"] for x in got["completed"]] == [["repo#TD-001"]] and got["completed"][0]["pr"] == 7


def test_a_v1_ledger_split_on_origin_reads_the_directory_and_its_history(tmp_path):
    """A v1 ledger split into a directory on origin, not pulled: the reading reads the directory, and its `windows`
    and `recent` read the directory's history."""
    v1 = {"docs/technical_debt.md": V1 + entry(1, "one"), "docs/technical_debt_archive.md": V1_ARCHIVE}
    root, other = scratch(tmp_path, v1, when=NOW - timedelta(days=3))
    gone = {"docs/technical_debt.md": None, "docs/technical_debt_archive.md": None}
    land(other, {**gone, **v2_files([entry(1, "one")])}, "split", when=NOW - timedelta(days=2))
    land(other, {"docs/ledger/TD-002.md": entry(2, "two after the split")}, when=NOW - timedelta(hours=1))
    fetch(root)
    led = ledger.reading(root, NOW)
    assert led["path"] == "docs/ledger" and sorted(by_id(led)) == ["TD-001", "TD-002"]
    assert (root / "docs/technical_debt.md").is_file() and not (root / "docs/ledger").exists()
    assert {c["id"] for c in led["recent"]} == {"TD-001", "TD-002"}
    assert led["windows"]["week"]["opened"] == 2 and led["windows"]["day"]["opened"] == 1


def test_a_v1_entry_origin_archived_while_the_checkout_edited_reads_from_one_side(tmp_path):
    """A v1 ledger and its archive are one unit: origin moved TD-001 into its archive while the checkout edited
    the file — both files the checkout's, so TD-001 reads once."""
    root, other = scratch(tmp_path, {"docs/technical_debt.md": V1 + entry(1, "one") + entry(2, "two"),
                                     "docs/technical_debt_archive.md": V1_ARCHIVE})  # fmt: skip
    land(other, {"docs/technical_debt.md": V1 + entry(2, "two"),
                 "docs/technical_debt_archive.md": V1_ARCHIVE + entry(1, "one")})  # fmt: skip
    write(root, {"docs/technical_debt.md": V1 + entry(1, "one, edited") + entry(2, "two")})
    fetch(root)
    led, gone = ledger.read(root, NOW, with_history=False)
    assert sorted(by_id(led)) == ["TD-001", "TD-002"] and gone == []
    assert led["origin"] == {"source": "checkout", "case": "both", "files": 0}
    # the checkout's edit undone: the unit is origin's, both files
    write(root, {"docs/technical_debt.md": V1 + entry(1, "one") + entry(2, "two")})
    led, gone = ledger.read(root, NOW, with_history=False)
    assert sorted(by_id(led)) == ["TD-002"] and [e["id"] for e in gone or []] == ["TD-001"]
    assert led["origin"] == {"source": "origin", "case": "behind", "files": 2}


def test_the_checkouts_own_edit_is_read_both_and_local(tmp_path):
    """The checkout's uncommitted edit to an entry origin also changed: the checkout's copy, `case` *both*; an edit
    to an entry origin did not change: the checkout's, `case` *local*."""
    root, other = scratch(tmp_path, v2_files([entry(1, "one"), entry(2, "two")]))
    write(root, {"docs/ledger/TD-002.md": entry(2, "two, mine")})
    led = ledger.reading(root, NOW, with_history=False)
    assert by_id(led)["TD-002"]["title"] == "two, mine" and led["origin"]["case"] == "local"
    land(other, {"docs/ledger/TD-002.md": entry(2, "two, theirs"), "docs/ledger/TD-001.md": entry(1, "one, theirs")})
    fetch(root)
    led = ledger.reading(root, NOW, with_history=False)
    assert by_id(led)["TD-002"]["title"] == "two, mine" and by_id(led)["TD-001"]["title"] == "one, theirs"
    assert led["origin"] == {"source": "origin", "case": "both", "files": 1}


def test_written_is_origins_last_commit_time_for_a_file_read_from_origin(tmp_path):
    """Two commits on origin touching one entry: `written` is the later one's committer time; an entry read from
    the checkout keeps its mtime."""
    root, other = scratch(tmp_path, v2_files([entry(1, "one"), entry(2, "two")]))
    first, second = NOW - timedelta(hours=3), NOW - timedelta(hours=1)
    land(other, {"docs/ledger/TD-001.md": entry(1, "one, a")}, when=first)
    land(other, {"docs/ledger/TD-001.md": entry(1, "one, b")}, when=second)
    os.utime(root / "docs/ledger/TD-002.md", (1000, 1000))
    fetch(root)
    got = by_id(ledger.reading(root, NOW, with_history=False))
    assert got["TD-001"]["written"] == second.timestamp() and got["TD-002"]["written"] == 1000


def test_after_done_the_hold_ends_once_origin_writes_the_entry_unpulled(tmp_path):
    """TD-1316's hold (§4.4 *The card's status*): a `done` outcome holds the word while the entry's file is not
    written after the answer — and a file changed on origin and not pulled is written at origin's commit time."""
    from test_queue_answered_hold import ANSWERED, _q, _top

    gated = entry(1, "the held one", Priority="High", Blocked_by="decision (paul)")
    root, other = scratch(tmp_path, v2_files([gated]), when=ANSWERED - timedelta(hours=3))
    os.utime(root / "docs/ledger/TD-001.md", ((ANSWERED - timedelta(hours=2)).timestamp(),) * 2)
    done = {"state": "done", "text": "#9 merged", "at": (NOW - timedelta(minutes=5)).isoformat(), "by": "m-9"}

    def card() -> dict[str, Any]:
        led = ledger.reading(root, NOW, with_history=False)
        repos = {str(root): {"name": "r", "root": str(root), "remote": "", "ledger": led, "prs": {"open": []}}}
        return _top(repos, [_q(outcome=done)])[1]["r#TD-001"]["top"]

    assert card()["answered"] is not None, "held: the file is not written after the answer"
    land(other, {"docs/ledger/TD-001.md": gated + "Log: picked up.\n"}, when=NOW - timedelta(minutes=10))
    fetch(root)
    assert card()["answered"] is None, "origin wrote it after the answer: the hold ends"


def test_a_ledger_first_added_on_origin_stamps_and_reads_origins(tmp_path):
    """A ledger first added on origin, the checkout without it: the stamp moves with origin and the reading reads
    origin's files."""
    root, other = scratch(tmp_path, {"README.md": "x\n"})
    before = ledger.stamp(root, "main")
    assert before is not None and before[1] == 0 and before[2]
    land(other, v2_files([entry(1, "first")]))
    assert ledger.stamp(root, "main") == before, "nothing fetched: nothing moved"
    fetch(root)
    after = ledger.stamp(root, "main")
    assert after is not None and after[2] != before[2]
    led = ledger.reading(root, NOW, with_history=False, rel="docs/ledger")
    assert sorted(by_id(led)) == ["TD-001"] and led["origin"]["source"] == "origin"


def test_a_rank_file_changed_on_origin_orders_the_queue_and_the_prune_reads_it(tmp_path):
    """The rank file is one id of its own: changed on origin it gives the entries their keys before the pull, and
    the prune (`_rank_lined`) weighs origin's lines."""
    from sessionorc.agent_rank import RankMixin

    root, other = scratch(tmp_path, {**v2_files([entry(1, "one"), entry(2, "two")]),
                                     "docs/ledger/rank.yml": "TD-001: 0|1\nTD-002: 0|2\n"})  # fmt: skip
    land(other, {"docs/ledger/rank.yml": "TD-001: 0|2\nTD-002: 0|1\nTD-009: 0|3\n"})
    fetch(root)
    led = ledger.reading(root, NOW, with_history=False)
    assert by_id(led)["TD-002"]["key"] == "0|1" and by_id(led)["TD-001"]["key"] == "0|2"
    lined = RankMixin._rank_lined(None, {"repo": (str(root), "docs/ledger/rank.yml", led)})
    assert lined == {"repo": ["TD-001", "TD-002"]}, "TD-009 is on origin's rank file and in neither ledger file"


def test_a_failed_fetch_a_failed_compare_and_no_origin_ref(tmp_path, monkeypatch):
    """A failed fetch moves no ref: the reading of origin as last fetched stands; a compare whose own git fails is an
    error (the tick keeps the last good reading beside it); no `origin/<default>`: the checkout's, *skipped*."""
    from sessionorc.agent_tick import TickMixin

    root, other = scratch(tmp_path, v2_files([entry(1, "one")]))
    land(other, {"docs/ledger/TD-001.md": entry(1, "one, theirs")})
    fetch(root)
    land(other, {"docs/ledger/TD-001.md": entry(1, "one, later")})
    git(root, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    assert not workorders.fetch_origin(root).ok
    good = ledger.reading(root, NOW, with_history=False)
    assert by_id(good)["TD-001"]["title"] == "one, theirs", "origin as last fetched"

    def broken(*a: Any, **kw: Any) -> ledger.Compare:
        return ledger.Compare(ledger.fs_io(root), {}, error="git could not compare the ledger with origin/main")

    monkeypatch.setattr(ledger, "compare", broken)
    led, arch = TickMixin._read_ledger(str(root), good, False, NOW)
    assert arch is None and led["error"].startswith("git could not compare") and led["entries"] == good["entries"]
    monkeypatch.undo()
    git(root, "update-ref", "-d", "refs/remotes/origin/main")
    git(root, "remote", "set-head", "origin", "-d")
    led = ledger.reading(root, NOW, with_history=False)
    assert by_id(led)["TD-001"]["title"] == "one" and led["origin"] == {"source": "checkout", "case": "skipped",
                                                                        "files": 0}  # fmt: skip


def test_a_repo_with_a_ledger_and_no_board_reads_a_merge_after_the_next_due_pass(tmp_path, monkeypatch):
    """The due pass fetches every registered repo with a ledger — one with no board too — before it reads the
    ledger: a merge on origin reaches the reading after the next due pass, unpulled, and the archive with it."""
    from sessionorc import reports
    from sessionorc.agent_tick import TickMixin

    monkeypatch.setattr(reports, "pr_reading", lambda d, now, **kw: {"open": [], "at": now.isoformat()})
    root, other = scratch(tmp_path, v2_files([entry(1, "one"), entry(2, "two")]))
    r = str(root)
    side: dict[str, Any] = {}
    first = TickMixin._read_repos([r], {}, {r}, None, None, None, False, None, None, side)
    assert sorted(by_id(first[r]["ledger"])) == ["TD-001", "TD-002"] and first[r]["boards"]["boards"] == []
    land(other, {"docs/ledger/TD-002.md": None, "docs/ledger/archive/TD-002.md": entry(2, "two")})
    side = {}
    again = TickMixin._read_repos([r], first, {r}, None, None, None, False, None, None, side)
    assert sorted(by_id(again[r]["ledger"])) == ["TD-001"]
    assert [e["id"] for e in side["archived"][r]] == ["TD-002"]
    assert (root / "docs/ledger/TD-002.md").is_file(), "the checkout was not pulled"


async def test_the_queue_keeps_its_last_cards_until_a_repo_has_an_archive(tmp_path, agent):
    """After a restart the Queue keeps each repo's last cards until its first ledger read hands it an archive."""
    from conftest import park_ticks

    await park_ticks(agent)
    root, _ = scratch(tmp_path, v2_files([entry(1, "one"), entry(2, "two")]))
    led = ledger.reading(root, NOW, with_history=False)
    r = {"name": "repo", "root": str(root), "remote": "", "ledger": led, "prs": {"open": []}}
    agent._repos = {str(root): r}
    agent._archived = archives(agent._repos)
    await agent._queue_pass(NOW)
    cards = [c["id"] for c in agent._queue["cards"]]
    assert cards == ["repo#TD-001", "repo#TD-002"] or sorted(cards) == ["repo#TD-001", "repo#TD-002"]
    agent._archived = {}  # a restart: no ledger read yet
    agent._repos = {str(root): {**r, "ledger": {**led, "entries": led["entries"][:1]}}}
    await agent._queue_pass(NOW + timedelta(seconds=2))
    assert sorted(c["id"] for c in agent._queue["cards"]) == sorted(cards), "the last cards stand"
    agent._archived = archives(agent._repos)
    await agent._queue_pass(NOW + timedelta(seconds=4))
    assert [c["id"] for c in agent._queue["cards"]] == ["repo#TD-001"]


async def test_a_repo_whose_ledger_read_failed_holds_no_queue_back(tmp_path, agent):
    """A repo with no archive whose ledger reading carries an error (its read failing since the restart) holds
    nothing back: the Queue is drawn from the other repos' readings (#3151's review)."""
    from conftest import park_ticks

    await park_ticks(agent)
    root, _ = scratch(tmp_path, v2_files([entry(1, "one"), entry(2, "two")]))
    led = ledger.reading(root, NOW, with_history=False)
    r = {"name": "repo", "root": str(root), "remote": "", "ledger": led, "prs": {"open": []}}
    agent._repos = {str(root): r}
    agent._archived = archives(agent._repos)
    await agent._queue_pass(NOW)
    agent._archived = {}  # a restart, and the first ledger read failed: entries kept, an error beside them
    agent._repos = {str(root): {**r, "ledger": {**led, "entries": led["entries"][:1], "error": "faulted"}}}
    await agent._queue_pass(NOW + timedelta(seconds=2))
    assert [c["id"] for c in agent._queue["cards"]] == ["repo#TD-001"]


def test_a_blob_git_cannot_give_is_an_error_never_an_absent_entry(tmp_path, monkeypatch):
    """`git cat-file --batch` failing for a file origin lists is the compare's error, not an entry gone."""
    root, other = scratch(tmp_path, v2_files([entry(1, "one")]))
    land(other, {"docs/ledger/TD-001.md": entry(1, "one, edited")})
    fetch(root)
    monkeypatch.setattr(ledger, "_batch", lambda *a, **k: {})
    cmp = ledger.compare(root, "docs/ledger", "main")
    assert cmp.error and "could not read" in cmp.error


def test_the_rule_is_by_id_and_takes_no_rename(tmp_path):
    """Both diffs run `--no-renames`: a move into `archive/` reads as a delete and an add, so the id is origin's
    placement and the open file is gone from the listing."""
    root, other = scratch(tmp_path, v2_files([entry(1, "one")]))
    land(other, {"docs/ledger/TD-001.md": None, "docs/ledger/archive/TD-001.md": entry(1, "one")})
    fetch(root)
    cmp = ledger.compare(root, "docs/ledger", "main")
    assert cmp.io[0]("docs/ledger") == ["README.md"] and cmp.io[0]("docs/ledger/archive") == ["TD-001.md"]
    assert cmp.io[1]("docs/ledger/TD-001.md") is None
    assert {"docs/ledger/TD-001.md", "docs/ledger/archive/TD-001.md"} <= cmp.taken
