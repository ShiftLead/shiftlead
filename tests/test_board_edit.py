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
    """A checkout with no scripts/ — a repo without agent-cadence — on a work branch."""
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
    assert "Hide until: 2026-11-01." in (root / "docs/user_attention.md").read_text().splitlines()[5]


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
    for text in ("board: ''\n", "board: [a]\n", "board: 3\n", "board: /etc/board.md\n", "board: ../x.md\n"):
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


def carried(root: Path, monkeypatch, capsys, *extra: str, line: str = "5", expect: str = "act 2026-10-10"):
    from shiftlead import cli

    monkeypatch.chdir(root)
    rc = cli.main(["board", "edit", "done", "--line", line, "--expect", expect, *extra])
    out = capsys.readouterr()
    return rc, out.out + out.err, (root / "docs/user_attention.md").read_text().splitlines()


@pytest.mark.unit
def test_carried_to_writes_the_reason_the_queue_reads(tmp_path, monkeypatch, capsys):
    root = ledger_repo(tmp_path)
    rc, out, lines = carried(root, monkeypatch, capsys, "--carried-to", "TD-5")
    assert rc == 0, out
    assert lines[4].startswith("- [x] act 2026-10-10") and lines[4].endswith("— carried to TD-5.")
    why = lines[4].rsplit("Closed: ", 1)[1].split(" — ", 1)[1].rstrip(".")
    assert workorders.carried_to(why) == ["TD-5"]
    # several, with a why; the archived one counts; the reader reads back the ids given
    rc, out, lines = carried(
        root, monkeypatch, capsys, "--carried-to", "TD-5, TD-006,TD-7", "--why", "the bought round",
        line="6", expect="act 2026-10-11",
    )  # fmt: skip
    assert rc == 0, out
    assert lines[5].endswith("— carried to TD-5, TD-006 and TD-7: the bought round.")
    why = lines[5].rsplit("Closed: ", 1)[1].split(" — ", 1)[1]
    assert workorders.carried_to(why) == ["TD-5", "TD-006", "TD-7"]


@pytest.mark.unit
def test_carried_to_lists_a_repeat_once_and_works_by_key(tmp_path, monkeypatch, capsys):
    root = ledger_repo(tmp_path)
    key = workorders.ref(root, ITEM)
    from shiftlead import cli

    monkeypatch.chdir(root)
    assert cli.main(["board", "edit", "done", "--key", key, "--carried-to", "TD-5, TD-5"]) == 0
    assert (root / "docs/user_attention.md").read_text().splitlines()[4].endswith("— carried to TD-5.")


@pytest.mark.unit
@pytest.mark.parametrize("value", ["TD-9", "td-5", "5", "TD-5,", "TD-5,,TD-6", ""])
def test_carried_to_refuses_an_unknown_or_malformed_id_writing_nothing(tmp_path, monkeypatch, capsys, value):
    root = ledger_repo(tmp_path)
    head = git(root, "rev-parse", "HEAD")
    rc, out, lines = carried(root, monkeypatch, capsys, "--carried-to", value)
    assert rc == 1 and "refused" in out
    assert ("TD-9" in out and "neither open nor archived" in out) if value == "TD-9" else "is not one" in out
    assert lines[4] == f"- [ ] {ITEM}" and git(root, "rev-parse", "HEAD") == head


@pytest.mark.unit
def test_carried_to_is_for_done_alone(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    root = ledger_repo(tmp_path)
    monkeypatch.chdir(root)
    argv = [
        "board",
        "edit",
        "snooze",
        "--line",
        "5",
        "--expect",
        "act",
        "--until",
        "2026-11-02",
        "--carried-to",
        "TD-5",
    ]
    assert cli.main(argv) == 1
    assert "--carried-to is for done only" in capsys.readouterr().err
    assert "Hide until" not in (root / "docs/user_attention.md").read_text()


@pytest.mark.unit
def test_carried_to_reads_a_v1_ledger_and_an_untracked_entry(tmp_path, monkeypatch, capsys):
    root = ledger_repo(tmp_path, "v1")
    rc, out, lines = carried(root, monkeypatch, capsys, "--carried-to", "TD-7")  # archived, in the v1 archive
    assert rc == 0, out
    assert lines[4].endswith("— carried to TD-7.")
    two = ledger_repo(tmp_path / "two")
    entry = ledgerboard.split(V1_LEDGER.replace("TD-006", "TD-008").replace("Six", "Eight"), "")
    rel = next(r for r in entry if r.startswith("TD-008"))
    (two / "docs/ledger" / rel).write_text(entry[rel], encoding="utf-8")  # filed by ledger.py new, not staged
    rc, out, lines = carried(two, monkeypatch, capsys, "--carried-to", "TD-8")
    assert rc == 0, out
    assert lines[4].endswith("— carried to TD-8.")


@pytest.mark.unit
def test_carried_to_checks_its_own_repos_name_and_takes_anothers_as_written(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    root = ledger_repo(tmp_path)  # a checkout no registry names: its own name is its directory's
    monkeypatch.setattr(cli, "_td_repo", lambda repo: (_ for _ in ()).throw(cli.AgentError("not registered")))
    rc, out, _ = carried(root, monkeypatch, capsys, "--carried-to", f"{root.name}#TD-9")
    assert rc == 1 and f"{root.name}#TD-9" not in out and "TD-9" in out and "neither open nor archived" in out
    rc, out, lines = carried(root, monkeypatch, capsys, "--carried-to", f"{root.name}#TD-5,agent-cadence#TD-999")
    assert rc == 0, out
    assert lines[4].endswith(f"— carried to {root.name}#TD-5 and agent-cadence#TD-999.")


@pytest.mark.unit
def test_carried_to_on_main_gives_the_branch_refusal(tmp_path, monkeypatch, capsys):
    root = ledger_repo(tmp_path)
    git(root, "switch", "-q", "main")
    rc, out, _ = carried(root, monkeypatch, capsys, "--carried-to", "TD-9")
    assert rc == 1 and "a default branch" in out and "TD-9" not in out


@pytest.mark.unit
def test_the_briefs_close_anothers_work_with_carried_to():
    """§4.9a *What a session does with a decided line* (TD-1540): the briefs that close a line for another entry's
    work name the option, so no session types *see TD-n* again."""
    top = Path(__file__).parents[1]
    for rel in ("src/shiftlead/briefs/grinder.md", "docs/briefs/designer-ao-1.md"):
        text = (top / rel).read_text(encoding="utf-8")
        assert "ao board edit done" in text and "--carried-to TD-n" in text, rel
        assert '--why "see TD-n"' not in text and '--why "carried to TD-n"' not in text, rel
