"""§4.7 `ao board edit done|snooze` and §5 *The seams* `board:` (TD-587): a session's own edit of one
board line, on the branch it is on, through the vendored ledgerboard — no host agent, no scripts/."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sessionorc import board, ledgerboard, workorders
from shiftlead import repoconfig

ITEM = "act 2026-10-10 (session `w1` on kmaster) — **Rotate the key.** Context: TD-001. Due: 2026-10-12."
OTHER = "act 2026-10-11 (session `w2` on kmaster) — **Renew the cert.** Due: 2026-10-20."
BOARD_TEXT = f"# User attention\n\n## Needs the user\n\n- [ ] {ITEM}\n- [ ] {OTHER}\n"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def make_repo(tmp_path: Path, rel: str = "docs/user_attention.md", branch: str = "td1-work") -> Path:
    """A checkout with no scripts/ — a repo without dev-cadence — on a work branch."""
    root = tmp_path / "repo"
    (root / rel).parent.mkdir(parents=True)
    (root / rel).write_text(BOARD_TEXT, encoding="utf-8")
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@t")
    if branch:
        git(root, "switch", "-q", "-c", branch)
    return root


@pytest.mark.unit
def test_done_and_snooze_commit_the_one_line_on_the_branch_with_ledgerboards_subject(tmp_path):
    root = make_repo(tmp_path)
    assert not (root / "scripts").exists()
    got = board.branch_edit(root, "done", line=5, expect="act 2026-10-10", why="rotated in #12", today="2026-10-14")
    assert got["line"] == 5 and got["branch"] == "td1-work"
    assert got["message"] == ledgerboard.subject("shiftlead", "done", ITEM)
    assert git(root, "log", "-1", "--format=%s") == got["message"]
    assert git(root, "show", "--name-only", "--format=", "HEAD") == "docs/user_attention.md"
    lines = (root / "docs/user_attention.md").read_text().splitlines()
    assert lines[4].startswith("- [x] act 2026-10-10") and lines[4].endswith("Closed: 2026-10-14 — rotated in #12.")
    assert lines[5] == f"- [ ] {OTHER}"
    assert git(root, "status", "--porcelain") == ""

    key = workorders.ref(root, OTHER)
    got = board.branch_edit(root, "snooze", key=key, until="2026-11-01")
    assert got["line"] == 6 and got["key"] == key
    assert git(root, "log", "-1", "--format=%s") == ledgerboard.subject("shiftlead", "snooze", OTHER, to="2026-11-01")
    assert "Due: 2026-11-01." in (root / "docs/user_attention.md").read_text().splitlines()[5]


@pytest.mark.unit
@pytest.mark.parametrize("action", ["decide", "reply"])
def test_decide_and_reply_are_the_persons_words_and_refused(tmp_path, action):
    root = make_repo(tmp_path)
    with pytest.raises(board.Refused, match="person's words"):
        board.branch_edit(root, action, line=5, expect="act")
    assert git(root, "rev-list", "--count", "HEAD") == "1"


@pytest.mark.unit
def test_a_moved_line_main_a_detached_head_and_a_dirty_index_are_refused_touching_nothing(tmp_path):
    root = make_repo(tmp_path)
    with pytest.raises(board.Refused, match="board moved"):
        board.branch_edit(root, "done", line=5, expect="act 2026-10-11")
    with pytest.raises(board.Refused, match="not an open item"):
        board.branch_edit(root, "done", line=1, expect="#")
    with pytest.raises(board.Refused, match=workorders.NO_LINE.format(ref="board:00000000")):
        board.branch_edit(root, "done", key="board:00000000")
    (root / "x.txt").write_text("x")
    git(root, "add", "x.txt")
    with pytest.raises(board.Refused, match="staged changes"):
        board.branch_edit(root, "done", line=5, expect="act")
    git(root, "reset", "-q")
    (root / "docs/user_attention.md").write_text(BOARD_TEXT + "\n")
    with pytest.raises(board.Refused, match="uncommitted changes"):
        board.branch_edit(root, "done", line=5, expect="act")
    git(root, "checkout", "-q", "--", "docs/user_attention.md")
    git(root, "switch", "-q", "main")
    with pytest.raises(board.Refused, match="a default branch"):
        board.branch_edit(root, "done", line=5, expect="act")
    git(root, "switch", "-q", "--detach")
    with pytest.raises(board.Refused, match="detached"):
        board.branch_edit(root, "done", line=5, expect="act")
    assert git(root, "rev-list", "--count", "--all") == "1"
    assert (root / "docs/user_attention.md").read_text() == BOARD_TEXT


@pytest.mark.unit
def test_the_flags_are_checked_before_anything_is_read(tmp_path):
    root = make_repo(tmp_path)
    for kw, words in (
        ({"line": 5, "expect": "act", "until": "2026-11-01"}, "for snooze only"),
        ({"line": 5, "expect": "act", "why": "x", "until": "nope"}, "YYYY-MM-DD"),
        ({"line": 5}, "name the line"),
        ({"line": 5, "expect": "act", "key": "board:00000000"}, "not both"),
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
        board.branch_edit(root, "done", line=5, expect="act")
    (root / ".shiftlead.yml").write_text("board: notes/board.md\n")
    git(root, "add", ".shiftlead.yml")
    git(root, "commit", "-q", "-m", "board seam")
    assert board.board_path(root) == ("set", Path("notes/board.md"))
    sub = root / "notes"
    got = board.branch_edit(sub, "done", line=5, expect="act")  # from a subdirectory: the tree's top
    assert got["board"] == str((root / "notes/board.md").resolve())
    other = make_repo(tmp_path / "b")
    assert board.board_path(other) == ("defaulted", board.BOARD)
    assert repoconfig.load_text("board: notes/board.md\n", tmp_path).board == "notes/board.md"
    assert repoconfig.load_text("ledger: docs/debt.md\n", tmp_path).board is None
    for text in ("board: ''\n", "board: [a]\n", "board: 3\n"):
        with pytest.raises(ValueError, match="board file's path"):
            repoconfig.load_text(text, tmp_path)


@pytest.mark.unit
def test_ao_board_edit_needs_no_host_agent(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    root = make_repo(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(cli, "call_sync", lambda *a, **k: pytest.fail("ao board edit called the host agent"))
    assert cli.main(["board", "edit", "done", "--line", "5", "--expect", "act 2026-10-10", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["action"] == "done" and got["commit"] == git(root, "rev-parse", "--short", "HEAD")
    assert cli.main(["board", "edit", "done", "--line", "6", "--expect", "nothing like it"]) == 1
    assert "board moved" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["board", "edit", "decide", "--line", "6", "--expect", "act"])
    assert cli.main(["board", "edit", "snooze", "--line", "6", "--expect", "act", "--until", "2026-11-02"]) == 0
    assert "committed" in capsys.readouterr().out


@pytest.mark.unit
def test_origins_default_is_refused_whatever_its_name_and_unknown_main_and_master_are(tmp_path):
    """Review of TD-587 slice 1: the default branch is origin's `HEAD` where the clone knows it, else
    `main`, `master` and `init.defaultBranch` are each refused."""
    root = make_repo(tmp_path, branch="trunk")
    git(root, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    with pytest.raises(board.Refused, match="trunk, a default branch"):
        board.branch_edit(root, "done", line=5, expect="act")
    git(root, "switch", "-q", "main")  # origin says trunk: main is a branch like any other
    assert board.branch_edit(root, "done", line=5, expect="act")["branch"] == "main"
    other = make_repo(tmp_path / "b", branch="master")
    with pytest.raises(board.Refused, match="master, a default branch"):
        board.branch_edit(other, "done", line=5, expect="act")


@pytest.mark.unit
def test_the_expect_is_the_text_or_the_raw_line_and_crlf_lines_keep_their_ending(tmp_path):
    root = make_repo(tmp_path)
    path = root / "docs/user_attention.md"
    path.write_bytes(BOARD_TEXT.replace("\n", "\r\n").encode())
    git(root, "commit", "-qam", "crlf")
    got = board.branch_edit(root, "done", line=6, expect="- [ ] act 2026-10-11")
    assert got["line"] == 6
    raw = path.read_bytes().decode()
    assert raw.split("\r\n")[5].startswith("- [x] act 2026-10-11") and raw.count("\r\n") == BOARD_TEXT.count("\n")


@pytest.mark.unit
def test_a_commit_git_refuses_restores_the_board(tmp_path):
    root = make_repo(tmp_path)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho no commits today >&2\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(board.Refused, match="git commit failed.*no commits today.*restored"):
        board.branch_edit(root, "done", line=5, expect="act")
    assert (root / "docs/user_attention.md").read_text() == BOARD_TEXT
    assert git(root, "rev-list", "--count", "HEAD") == "1"
