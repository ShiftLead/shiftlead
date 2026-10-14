"""§5 *The seams* `board:` (TD-587 slice 2): every board reader reads the board `.shiftlead.yml`
names in place of the fixed `docs/user_attention.md` — the host agent's `boards` reading, `ao board
show`, the write-back and its adds, the Inbox's *Put on the board* choices — and a repo with no
board reads as *no board: the Inbox is the person's channel*."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sessionorc import board, workorders
from sessionorc.client import AgentError, LocalClient

ITEM = "act 2026-10-10 (session `w1` on kmaster) — **Rotate the key.** Context: TD-001. Due: 2026-10-12."
BOARD_TEXT = f"# User attention\n\n## Needs the user\n\n- [ ] {ITEM}\n"
REL = "notes/board.md"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def make_repo(tmp_path: Path, rel: str | None = REL, name: str = "repo") -> Path:
    """A committed checkout whose board is `rel`, named by `board:` — no `docs/user_attention.md` —
    or, with `rel` None, a checkout with no board at all."""
    root = tmp_path / name
    root.mkdir()
    if rel is not None:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(BOARD_TEXT, encoding="utf-8")
        (root / ".shiftlead.yml").write_text(f"board: {rel}\n", encoding="utf-8")
    (root / "README").write_text("x\n")
    git(tmp_path, "init", "-q", "-b", "main", str(root))
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@t")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


@pytest.mark.unit
def test_the_boards_reading_and_board_show_read_the_board_board_names(tmp_path):
    root = make_repo(tmp_path)
    assert not (root / workorders.BOARD).exists()
    assert workorders.board_rel(root) == Path(REL)
    got = workorders.read_boards(root, fetch=False)
    [b] = got["boards"]
    assert b["board"] == str(root / REL) and [it["text"] for it in b["items"]] == [ITEM]
    key = b["items"][0]["key"]
    assert workorders.board_lines(root, fetch=False) == (BOARD_TEXT.splitlines(), "checkout")
    shown = workorders.show(root, key, fetch=False)
    assert shown is not None and shown["line"] == 5 and shown["open"] is True
    # a board: naming a file that does not exist is no board, never docs/user_attention.md
    (root / workorders.BOARD).parent.mkdir()
    (root / workorders.BOARD).write_text(BOARD_TEXT)
    (root / ".shiftlead.yml").write_text("board: gone.md\n")
    assert workorders.read_boards(root, fetch=False) == {"boards": []}
    assert workorders.board_lines(root, fetch=False) == ([], "")


@pytest.mark.unit
def test_the_boards_reading_against_origin_reads_origins_copy_of_that_file(tmp_path, forge):
    root = make_repo(tmp_path)
    forge(root)
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(root.parent / "repo-origin.git"), str(other))
    later = BOARD_TEXT + "- [ ] act 2026-10-11 (n/a) — **Renew the cert.** Due: 2026-10-20.\n"
    (other / REL).write_text(later)
    git(other, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "more")
    git(other, "push", "-q", "origin", "main")
    [b] = workorders.read_boards(root)["boards"]
    assert b["fetch_case"] == "behind" and len(b["items"]) == 2
    assert workorders.board_lines(root) == (later.splitlines(), "origin/main")


@pytest.mark.unit
def test_no_board_is_no_boards_and_ao_board_show_says_the_seams_words(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    root = make_repo(tmp_path, None)
    assert workorders.board_path(root) == ("absent", None)
    assert workorders.read_boards(root, fetch=False) == {"boards": []}
    assert workorders.board_lines(root, fetch=False) == ([], "")
    assert workorders.show(root, "board:00000000", fetch=False) is None
    monkeypatch.chdir(root)
    repos = {str(root): {"root": str(root), "boards": {"boards": []}}}
    monkeypatch.setattr(cli, "call_sync", lambda method, **k: repos if method == "repos" else pytest.fail(method))
    assert cli.main(["board", "show", "board:00000000"]) == 1
    assert workorders.NO_BOARD in capsys.readouterr().err


@pytest.mark.unit
def test_ao_board_show_names_the_file_it_read(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    root = make_repo(tmp_path)
    monkeypatch.chdir(root)
    repos = {str(root): {"root": str(root), "boards": workorders.read_boards(root, fetch=False)}}
    monkeypatch.setattr(cli, "call_sync", lambda method, **k: repos if method == "repos" else pytest.fail(method))
    key = workorders.ref(root, ITEM)
    assert cli.main(["board", "show", key]) == 0
    assert f"{key}  line 5 of {REL} on checkout" in capsys.readouterr().out
    assert cli.main(["board", "show", key, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["line"] == 5


@pytest.mark.unit
def test_the_write_back_and_its_add_land_on_the_board_board_names(tmp_path, forge):
    root = make_repo(tmp_path)
    forge(root)
    got = board.write_back(root, 5, ITEM, "snooze", "2026-11-01")
    git(root, "fetch", "-q", "origin")
    assert git(root, "show", "--name-only", "--format=", "origin/main") == REL
    assert "Due: 2026-11-01." in git(root, "show", f"origin/main:{REL}")
    assert got["line"] == 5 and (root / REL).read_text() == BOARD_TEXT  # the checkout is never written
    added = board.add(root, "Check the fetcher.", "2026-10-20", today="2026-10-14")
    git(root, "fetch", "-q", "origin")
    assert git(root, "show", "--name-only", "--format=", "origin/main") == REL
    assert git(root, "show", f"origin/main:{REL}").splitlines()[added["line"] - 1].startswith(
        "- [ ] 2026-10-14 (n/a) — Check the fetcher."
    )
    assert not git(root, "ls-tree", "-r", "--name-only", "origin/main", "docs")  # nothing at the default


@pytest.mark.unit
def test_put_on_the_boards_choices_are_each_repos_own_board(tmp_path, monkeypatch):
    from shiftlead.ui.inbox import board_choices

    named, none = make_repo(tmp_path), make_repo(tmp_path, None, "plain")
    got = board_choices([named, none])
    assert got == [{"label": "repo", "root": str(named.resolve()), "board": str((named / REL).resolve())}]


async def test_board_edit_takes_the_board_board_names_and_refuses_the_default_path(agent, tmp_path, forge):
    root = make_repo(tmp_path)
    forge(root)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{root}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    async with LocalClient() as me:
        with pytest.raises(AgentError, match="not the board of a repo this host knows"):
            await me.call("board_edit", board=str(root / workorders.BOARD), line=5, text=ITEM, action="done")
        got = await me.call("board_edit", board=str(root / REL), line=5, text=ITEM, action="done")
    assert got["action"] == "done"
    git(root, "fetch", "-q", "origin")
    assert git(root, "show", f"origin/main:{REL}").splitlines()[4].startswith("- [x] act 2026-10-10")
