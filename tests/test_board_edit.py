"""§4.7 `ao board edit done|snooze` and §5 *The seams* `board:` (TD-587): a session's own edit of one
board item, on the branch it is on, through the vendored ledgerboard — no host agent, no scripts/. The board is
ledgerboard v3.0's directory of item files, each named by its id (TD-1881)."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest
from _v3board import item, ref_of, write_board

from sessionorc import board, ledgerboard, workorders
from shiftlead import repoconfig

ITEM = "act 2026-10-10 (session `w1` on kmaster) — **Rotate the key.** Context: TD-001. Due: 2026-10-12."
OTHER = "act 2026-10-11 (session `w2` on kmaster) — **Renew the cert.** Due: 2026-10-20."
BOARD_TEXT = f"# User attention\n\n## Needs the user\n\n- [ ] {ITEM}\n- [ ] {OTHER}\n"
REF, OTHER_REF = ref_of(ITEM), ref_of(OTHER)  # the references the split items keep (ledgerboard v3.0, TD-1881)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def make_repo(tmp_path: Path, rel: str = "docs/user_attention.md", branch: str = "td1-work") -> Path:
    """A checkout with no scripts/ — a repo without agent-cadence — on a work branch, its board a v3 one."""
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    write_board(root, BOARD_TEXT, rel=rel)
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@t")
    if branch:
        git(root, "switch", "-q", "-c", branch)
    return root


def files(root: Path, rel: str = "docs/user_attention.md") -> dict[str, bytes]:
    """Every file of the board at `rel` (its directory and stub), by path: the board unchanged while they are."""
    d = (root / rel).with_suffix("")
    return {str(p.relative_to(root)): p.read_bytes() for p in [root / rel, *sorted(d.rglob("*"))] if p.is_file()}


@pytest.mark.unit
def test_done_and_snooze_commit_the_one_item_on_the_branch_with_ledgerboards_subject(tmp_path):
    root = make_repo(tmp_path)
    assert not (root / "scripts").exists()
    it = item(root, REF)
    got = board.branch_edit(root, "done", key=REF, why="rotated in #12", today="2026-10-14")
    assert got["line"] is None and got["id"] == it.id and got["branch"] == "td1-work" and got["key"] == REF
    assert got["message"] == ledgerboard.subject("shiftlead", "done", it.words, id=it.id, session="w1")
    assert git(root, "log", "-1", "--format=%s") == got["message"]
    # the open file moves into archive/<YYYY-MM>/ in the one commit (TD-1881)
    assert set(git(root, "show", "--no-renames", "--name-only", "--format=", "HEAD").splitlines()) == {
        f"docs/user_attention/{it.id}.md",
        f"docs/user_attention/archive/2026-10/{it.id}.md",
    }
    shut = item(root, REF)
    assert shut.closed == (date(2026, 10, 14), "rotated in #12")
    assert item(root, OTHER_REF).closed is None
    assert git(root, "status", "--porcelain") == ""

    other = item(root, OTHER_REF)
    got = board.branch_edit(root, "snooze", key=other.id, until="2026-11-01")  # the whole id names it too
    assert got["key"] == OTHER_REF and got["id"] == other.id
    assert git(root, "log", "-1", "--format=%s") == ledgerboard.subject(
        "shiftlead", "snooze", other.words, id=other.id, to="2026-11-01", session="w2"
    )
    assert item(root, OTHER_REF).hide_until == date(2026, 11, 1)


@pytest.mark.unit
@pytest.mark.parametrize("action", ["decide", "reply"])
def test_decide_and_reply_are_the_persons_words_and_refused(tmp_path, action):
    root = make_repo(tmp_path)
    with pytest.raises(board.Refused, match="person's words"):
        board.branch_edit(root, action, key=REF)
    assert git(root, "rev-list", "--count", "HEAD") == "1"


@pytest.mark.unit
def test_an_unknown_id_main_a_detached_head_and_a_dirty_index_are_refused_touching_nothing(tmp_path):
    root = make_repo(tmp_path)
    before = files(root)
    with pytest.raises(board.Refused, match=workorders.NO_LINE.format(ref="board:00000000")):
        board.branch_edit(root, "done", key="board:00000000")
    (root / "x.txt").write_text("x")
    git(root, "add", "x.txt")
    with pytest.raises(board.Refused, match="staged changes"):
        board.branch_edit(root, "done", key=REF)
    git(root, "reset", "-q")
    (root / "x.txt").unlink()
    path = root / "docs/user_attention" / item(root, REF).path
    path.write_text(path.read_text() + "\n")
    with pytest.raises(board.Refused, match="uncommitted changes"):
        board.branch_edit(root, "done", key=REF)
    git(root, "checkout", "-q", "--", "docs/user_attention")
    git(root, "switch", "-q", "main")
    with pytest.raises(board.Refused, match="a default branch"):
        board.branch_edit(root, "done", key=REF)
    git(root, "switch", "-q", "--detach")
    with pytest.raises(board.Refused, match="detached"):
        board.branch_edit(root, "done", key=REF)
    assert git(root, "rev-list", "--count", "--all") == "1"
    assert files(root) == before
    # retired (TD-1881): a moved line (`--expect` no longer the line's start) and a line that is no open item —
    # ledgerboard v3.0 names an item by its id alone; `--line` and `--expect` are refused by name below


@pytest.mark.unit
def test_a_closed_item_is_said_closed(tmp_path):
    root = make_repo(tmp_path)
    board.branch_edit(root, "done", key=REF, today="2026-10-14")
    with pytest.raises(board.Refused, match=f"{REF} was closed 2026-10-14"):
        board.branch_edit(root, "done", key=REF)


@pytest.mark.unit
def test_the_flags_are_checked_before_anything_is_read(tmp_path):
    root = make_repo(tmp_path)
    for kw, words in (
        ({"key": REF, "until": "2026-11-01"}, "for snooze only"),
        ({"key": REF, "why": "x", "until": "nope"}, "YYYY-MM-DD"),
        ({}, "name the item"),
        ({"line": 5}, "named by its id"),
        ({"line": 5, "expect": "act", "key": "board:00000000"}, "named by its id"),
        ({"expect": "act"}, "named by its id"),
        ({"key": "TD-1"}, "not a board line's id"),
    ):
        action = "snooze" if "until" in kw and kw["until"] == "nope" else "done"
        with pytest.raises(board.Refused, match=words):
            board.branch_edit(root, action, **kw)


@pytest.mark.unit
def test_the_board_seam_is_set_defaulted_or_absent(tmp_path):
    root = make_repo(tmp_path, rel="notes/board.md")
    assert board.board_path(root) == ("absent", None)
    with pytest.raises(board.Refused, match="no board here"):
        board.branch_edit(root, "done", key=REF)
    (root / ".shiftlead.yml").write_text("board: notes/board.md\n")
    git(root, "add", ".shiftlead.yml")
    git(root, "commit", "-q", "-m", "board seam")
    assert board.board_path(root) == ("set", Path("notes/board.md"))
    sub = root / "notes"
    got = board.branch_edit(sub, "done", key=REF)  # from a subdirectory: the tree's top
    assert got["board"] == str((root / "notes/board.md").resolve())
    assert item(root, REF, rel="notes/board.md").closed is not None
    assert git(root, "status", "--porcelain") == ""
    other = make_repo(tmp_path / "b")
    assert board.board_path(other) == ("defaulted", board.BOARD)
    assert repoconfig.load_text("board: notes/board.md\n", tmp_path).board == "notes/board.md"
    assert repoconfig.load_text("ledger: docs/debt.md\n", tmp_path).board is None
    for text in ("board: ''\n", "board: [a]\n", "board: 3\n", "board: /etc/board.md\n", "board: ../x.md\n"):
        with pytest.raises(ValueError, match="board file's path"):
            repoconfig.load_text(text, tmp_path)


@pytest.mark.unit
def test_a_v2_board_is_refused_by_the_writer_in_its_words(tmp_path):
    root = make_repo(tmp_path)
    for p in sorted((root / "docs/user_attention").rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    (root / "docs/user_attention").rmdir()
    (root / "docs/user_attention.md").write_text(BOARD_TEXT)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "back to v2")
    head = git(root, "rev-parse", "HEAD")
    with pytest.raises(board.Refused, match="split first"):
        board.branch_edit(root, "done", key=REF)
    assert git(root, "rev-parse", "HEAD") == head and (root / "docs/user_attention.md").read_text() == BOARD_TEXT


@pytest.mark.unit
def test_ao_board_edit_needs_no_host_agent(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    root = make_repo(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(cli, "call_sync", lambda *a, **k: pytest.fail("ao board edit called the host agent"))
    assert cli.main(["board", "edit", "done", "--key", REF, "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["action"] == "done" and got["commit"] == git(root, "rev-parse", "--short", "HEAD")
    assert cli.main(["board", "edit", "done", "--line", "6", "--expect", "nothing like it"]) == 1
    assert "named by its id" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["board", "edit", "decide", "--key", OTHER_REF])
    assert cli.main(["board", "edit", "snooze", "--key", OTHER_REF, "--until", "2026-11-02"]) == 0
    assert "committed" in capsys.readouterr().out


@pytest.mark.unit
def test_origins_default_is_refused_whatever_its_name_and_unknown_main_and_master_are(tmp_path):
    """Review of TD-587 slice 1: the default branch is origin's `HEAD` where the clone knows it, else
    `main`, `master` and `init.defaultBranch` are each refused."""
    root = make_repo(tmp_path, branch="trunk")
    git(root, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    with pytest.raises(board.Refused, match="trunk, a default branch"):
        board.branch_edit(root, "done", key=REF)
    git(root, "switch", "-q", "main")  # origin says trunk: main is a branch like any other
    assert board.branch_edit(root, "done", key=REF)["branch"] == "main"
    other = make_repo(tmp_path / "b", branch="master")
    with pytest.raises(board.Refused, match="master, a default branch"):
        board.branch_edit(other, "done", key=REF)


@pytest.mark.unit
def test_a_crlf_item_file_keeps_its_line_ending(tmp_path):
    root = make_repo(tmp_path)
    it = item(root, OTHER_REF)
    path = root / "docs/user_attention" / it.path
    path.write_bytes(path.read_text().replace("\n", "\r\n").encode())
    git(root, "commit", "-qam", "crlf")
    got = board.branch_edit(root, "done", key=OTHER_REF, today="2026-10-14")
    raw = (root / "docs/user_attention/archive/2026-10" / f"{got['id']}.md").read_bytes().decode()
    assert "**Closed:** 2026-10-14\r\n" in raw and "\n" not in raw.replace("\r\n", "")
    # retired (TD-1881): `--expect` as the item's text or its raw line — an item is named by its id alone


@pytest.mark.unit
def test_a_commit_git_refuses_restores_the_board(tmp_path):
    root = make_repo(tmp_path)
    before = files(root)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho no commits today >&2\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(board.Refused, match="git commit failed.*no commits today.*restored"):
        board.branch_edit(root, "done", key=REF)
    assert files(root) == before
    assert git(root, "rev-list", "--count", "HEAD") == "1" and git(root, "status", "--porcelain") == ""


# `--carried-to` (design §4.7, TD-1528/TD-1540): the reason the Queue reads, its ids checked before the write
V1_LEDGER = (
    "# Technical debt\n\n| ID | Title | Priority | Status |\n|---|---|---|---|\n"
    "| TD-005 | Five | Low | Open |\n| TD-006 | Six | Low | Open |\n\n"
    "## TD-005: Five\n\n**Priority:** Low\n**Added:** 2026-10-01\n**Status:** Open\n\n"
    "**Why:** five.\n\n**Fix:** five.\n\n"
    "## TD-006: Six\n\n**Priority:** Low\n**Added:** 2026-10-01\n**Status:** Open\n\n"
    "**Why:** six.\n\n**Fix:** six.\n"
)
V1_ARCHIVE = (
    "# Technical debt archive\n\n## TD-007: Seven\n\n**Priority:** Low\n**Added:** 2026-10-01\n"
    "**Status:** Resolved 2026-10-02\n\n**Why:** seven.\n\n**Resolved:** 2026-10-02\n"
)


def ledger_repo(tmp_path: Path, layout: str = "v2") -> Path:
    root = make_repo(tmp_path, branch="")
    if layout == "v1":
        (root / "docs/technical_debt.md").write_text(V1_LEDGER, encoding="utf-8")
        (root / "docs/technical_debt_archive.md").write_text(V1_ARCHIVE, encoding="utf-8")
    else:
        for rel, text in ledgerboard.split(V1_LEDGER, V1_ARCHIVE).items():
            (root / "docs/ledger" / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / "docs/ledger" / rel).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "ledger")
    git(root, "switch", "-q", "-c", "td1-work")
    return root


def carried(root: Path, monkeypatch, capsys, *extra: str, ref: str = REF):
    """`ao board edit done --key <ref> <extra>`: (exit, what it printed, the item's `Closed:` why or None while
    it is open)."""
    from shiftlead import cli

    monkeypatch.chdir(root)
    rc = cli.main(["board", "edit", "done", "--key", ref, *extra])
    out = capsys.readouterr()
    it = item(root, ref)
    return rc, out.out + out.err, (it.closed[1] or "") if it.closed else None


@pytest.mark.unit
def test_carried_to_writes_the_reason_the_queue_reads(tmp_path, monkeypatch, capsys):
    root = ledger_repo(tmp_path)
    rc, out, why = carried(root, monkeypatch, capsys, "--carried-to", "TD-5")
    assert rc == 0, out
    assert why == "carried to TD-5" and workorders.carried_to(why) == ["TD-5"]
    # several, with a why; the archived one counts; the reader reads back the ids given
    rc, out, why = carried(
        root, monkeypatch, capsys, "--carried-to", "TD-5, TD-006,TD-7", "--why", "the bought round", ref=OTHER_REF,
    )  # fmt: skip
    assert rc == 0, out
    assert why == "carried to TD-5, TD-006 and TD-7: the bought round"
    assert workorders.carried_to(why) == ["TD-5", "TD-006", "TD-7"]


@pytest.mark.unit
def test_carried_to_lists_a_repeat_once_and_works_by_key(tmp_path, monkeypatch, capsys):
    root = ledger_repo(tmp_path)
    rc, out, why = carried(root, monkeypatch, capsys, "--carried-to", "TD-5, TD-5")
    assert rc == 0, out
    assert why == "carried to TD-5"


@pytest.mark.unit
@pytest.mark.parametrize("value", ["TD-9", "td-5", "5", "TD-5,", "TD-5,,TD-6", ""])
def test_carried_to_refuses_an_unknown_or_malformed_id_writing_nothing(tmp_path, monkeypatch, capsys, value):
    root = ledger_repo(tmp_path)
    head = git(root, "rev-parse", "HEAD")
    rc, out, why = carried(root, monkeypatch, capsys, "--carried-to", value)
    assert rc == 1 and "refused" in out
    assert ("TD-9" in out and "neither open nor archived" in out) if value == "TD-9" else "is not one" in out
    assert why is None and git(root, "rev-parse", "HEAD") == head


@pytest.mark.unit
def test_carried_to_is_for_done_alone(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    root = ledger_repo(tmp_path)
    monkeypatch.chdir(root)
    argv = [
        "board",
        "edit",
        "snooze",
        "--key",
        REF,
        "--until",
        "2026-11-02",
        "--carried-to",
        "TD-5",
    ]
    assert cli.main(argv) == 1
    assert "--carried-to is for done only" in capsys.readouterr().err
    assert item(root, REF).hide_until is None


@pytest.mark.unit
def test_carried_to_reads_a_v1_ledger_and_an_untracked_entry(tmp_path, monkeypatch, capsys):
    root = ledger_repo(tmp_path, "v1")
    rc, out, why = carried(root, monkeypatch, capsys, "--carried-to", "TD-7")  # archived, in the v1 archive
    assert rc == 0, out
    assert why == "carried to TD-7"
    two = ledger_repo(tmp_path / "two")
    entry = ledgerboard.split(V1_LEDGER.replace("TD-006", "TD-008").replace("Six", "Eight"), "")
    rel = next(r for r in entry if r.startswith("TD-008"))
    (two / "docs/ledger" / rel).write_text(entry[rel], encoding="utf-8")  # filed by ledger.py new, not staged
    rc, out, why = carried(two, monkeypatch, capsys, "--carried-to", "TD-8")
    assert rc == 0, out
    assert why == "carried to TD-8"


@pytest.mark.unit
def test_carried_to_checks_its_own_repos_name_and_takes_anothers_as_written(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    root = ledger_repo(tmp_path)  # a checkout no registry names: its own name is its directory's
    monkeypatch.setattr(cli, "_td_repo", lambda repo: (_ for _ in ()).throw(cli.AgentError("not registered")))
    rc, out, _ = carried(root, monkeypatch, capsys, "--carried-to", f"{root.name}#TD-9")
    assert rc == 1 and f"{root.name}#TD-9" not in out and "TD-9" in out and "neither open nor archived" in out
    rc, out, why = carried(root, monkeypatch, capsys, "--carried-to", f"{root.name}#TD-5,agent-cadence#TD-999")
    assert rc == 0, out
    assert why == f"carried to {root.name}#TD-5 and agent-cadence#TD-999"


@pytest.mark.unit
def test_carried_to_on_main_gives_the_branch_refusal(tmp_path, monkeypatch, capsys):
    root = ledger_repo(tmp_path)
    git(root, "switch", "-q", "main")
    for value in ("TD-9", "td-5"):
        rc, out, _ = carried(root, monkeypatch, capsys, "--carried-to", value)
        assert rc == 1 and "a default branch" in out and value not in out


@pytest.mark.unit
def test_carried_to_refuses_an_id_too_long_for_any_ledger(tmp_path, monkeypatch, capsys):
    root = ledger_repo(tmp_path)
    rc, out, why = carried(root, monkeypatch, capsys, "--carried-to", "TD-" + "9" * 5000)
    assert rc == 1 and "neither open nor archived" in out and why is None


@pytest.mark.unit
def test_the_briefs_close_anothers_work_with_carried_to():
    """§4.9a *What a session does with a decided line* (TD-1540): the briefs that close a line for another entry's
    work name the option, so no session types *see TD-n* again."""
    top = Path(__file__).parents[1]
    for rel in ("src/shiftlead/briefs/grinder.md", "docs/briefs/designer-ao-1.md"):
        text = (top / rel).read_text(encoding="utf-8")
        assert "ao board edit done" in text and "--carried-to TD-n" in text, rel
        assert '--why "see TD-n"' not in text and '--why "carried to TD-n"' not in text, rel
