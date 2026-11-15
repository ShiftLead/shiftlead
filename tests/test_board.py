"""Board write-back (design §4.4, TD-069 step 3): Snooze and Done on one board item, committed in
the repo's main checkout with the fixed message — and refused, touching nothing, whenever the
checkout is not in a state to take that commit."""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from _v3board import item, load, ref_of, write_board
from conftest import copy_pinned_ledgerboard, park_ticks, pinned_script, served

from sessionorc import board, ledgerboard
from sessionorc import ledger as ledger_mod
from sessionorc.agent import RpcError
from sessionorc.client import AgentError, LocalClient

ITEM = (
    "2026-09-20 (session `grinder-ao-1` on kmaster) — **Merged, live check pending: the doorbell.** Look. "
    "Due: 2026-09-22."
)
UNDATED = "2026-09-21 (n/a) — undated."  # dated: ledgerboard v3.0's split gives every item an id from its date
BOARD_TEXT = f"# User attention\n\nFormat: `- [ ] …`\n\n## Needs the user\n\n- [ ] {ITEM}\n- [ ] {UNDATED}\n"
REF, UNDATED_REF = ref_of(ITEM), ref_of(UNDATED)  # the references the split items keep (TD-1881)


def _own(tmp_path, name: str) -> str:
    """A directory of its own: a stand-in for an agent keeps the anchor rule (§9 invariant 2)."""
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    return str(d)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, forge) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    write_board(root, BOARD_TEXT)  # a v3 board, the directory and its stub (ledgerboard v3.0, TD-1881)
    (root / "other.txt").write_text("x\n")
    served(root)  # registered by the tests that talk to the home, which reads it once a tick comes (TD-1040)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    forge(root)
    return root


def on_origin(root: Path, *args: str) -> str:
    """What origin's `main` holds after a landed edit (§4.4): fetched, then read."""
    git(root, "fetch", "-q", "origin")
    return git(root, *args)


def origin(root: Path) -> ledgerboard.Board:
    """Origin's board after a landed edit, as `load_board()` reads it at `origin/main` (TD-1881)."""
    git(root, "fetch", "-q", "origin")
    return ledgerboard.load_board(board.BOARD.as_posix(), *ledger_mod.git_io(root, "origin/main", under="docs"))


def origin_item(root: Path, ref: str) -> ledgerboard.BoardItem | None:
    """Origin's item whose id ends with `ref`'s eight hex digits, open or closed, else None."""
    nonce = ref.removeprefix("board:")
    b = origin(root)
    return next((it for it in [*b.items, *b.closed] if it.id and it.id.endswith("-" + nonce)), None)


def push_board(root: Path, text: str, msg: str = "the board", archive: str = "") -> None:
    """The checkout's board rewritten from the v2 `text` (`write_board`), committed whole and pushed to origin."""
    write_board(root, text, archive)
    git(root, "add", "-A")
    git(root, "commit", "-qm", msg)
    git(root, "push", "-q", "origin", "main")


def origin_docs(root: Path) -> str:
    """The tree id of origin's `docs/`: the board's files and stub unchanged while it is."""
    return on_origin(root, "rev-parse", "origin/main:docs")


def board_files(root: Path, rev: str = "origin/main") -> set[str]:
    """The paths of the board's files a commit at `rev` touched."""
    return set(on_origin(root, "show", "--no-renames", "--name-only", "--format=", rev).splitlines())


def keep_ledger(agent, monkeypatch) -> None:
    """A test that hands the home a ledger reading of its own keeps it over a press's re-read, which reads the
    whole ledger against origin (`_read_ledger`, TD-1471): the step answers with the reading as it stands."""
    monkeypatch.setattr(agent, "_read_ledger", lambda root, old_led, *a, **kw: (dict(old_led), []))


def _items(tmp_path) -> dict[str, ledgerboard.BoardItem]:
    """The fixture's two items, split into a v3 board under `tmp_path` and read back, by their references."""
    write_board(tmp_path, BOARD_TEXT)
    return {r: item(tmp_path, r) for r in (REF, UNDATED_REF)}


def test_an_item_is_done_or_snoozed_only_while_it_is_open(tmp_path):
    its = _items(tmp_path)
    it = its[REF]

    def read(text: str) -> ledgerboard.BoardItem:
        return ledgerboard.parse_item(text, it.path)

    # Done closes it today: ledgerboard's edit (TD-585; v3.0 writes the item file's `Closed:`, TD-1881)
    assert read(board.edit_item(it, "done", today="2026-10-13")).closed == (datetime(2026, 10, 13).date(), None)
    # ledgerboard v2.3 (TD-1330): Snooze hides the item until the date and leaves its Due: alone; `due` moves it
    got = read(board.edit_item(it, "snooze", "2026-10-01"))
    assert got.hide_until.isoformat() == "2026-10-01" and got.due.isoformat() == "2026-09-22"
    assert read(board.edit_item(it, "due", "2026-10-01")).due.isoformat() == "2026-10-01"
    # an undated item gains a date by `due`
    assert read(board.edit_item(its[UNDATED_REF], "due", "2026-10-01")).due.isoformat() == "2026-10-01"
    shut = read(board.edit_item(it, "done", today="2026-10-13"))
    for bad in (
        lambda: board.edit_item(shut, "done"),  # already done
        lambda: board.edit_item(it, "snooze", "next week"),
        lambda: board.edit_item(it, "delete"),
    ):
        with pytest.raises(board.Refused):
            bad()
    # retired (TD-1881): v2's refusal of a snooze on a line with no Due: and no Context: — an item file's
    # `Hide until:` is a field of its own, which no reader takes for the item's words


def test_the_message_names_the_item_its_id_and_the_session_that_raised_it():
    iid = "2026-09-20-aced0c18"
    words = "**Merged, live check pending: the doorbell.** Look."
    assert board.message(words, "snooze", "2026-10-01", id=iid, session="grinder-ao-1") == (
        f"shiftlead: snooze {iid} Merged, live check pending: the doorbell. Look. to 2026-10-01 (session grinder-ao-1)"
    )  # ledgerboard v3.0's subject (TD-1881): the id after the action, the head the words', the session as given
    assert board.message("undated.", "done", id=iid) == f"shiftlead: done {iid} undated. (session n/a)"
    assert board.message(words, "append", id=iid).startswith(f"shiftlead: append {iid} Merged")
    long = board.message(words, "snooze", "2026-10-01", id=iid, session="g" * 300)  # the PR's title: 256 at most
    assert len(long) <= board.SUBJECT_MAX and long.startswith("shiftlead: snooze") and long.endswith(")")


def test_write_back_lands_the_one_item_on_origin_and_leaves_the_checkout_alone(repo):
    """TD-264 (design §4.4): the edit is made in the host agent's own tree at origin's head and lands
    there by a PR it opens and squash-merges — the item's file, the fixed message as its title — and the
    person's checkout, its own edits included, is never written."""
    (repo / "other.txt").write_text("the anchor's own edit, uncommitted\n")
    head = git(repo, "rev-parse", "HEAD")
    mine = load(repo)
    got = board.write_back(repo, None, "", "snooze", "2026-10-01", key=REF)
    assert got["pr"] == 1 and got["key"] == REF and got["id"].endswith(REF[-8:])
    assert got["commit"] == on_origin(repo, "rev-parse", "--short", "origin/main")
    assert on_origin(repo, "log", "-1", "--format=%s", "origin/main") == f"{got['message']} (#1)"
    assert board_files(repo) == {f"docs/user_attention/{got['id']}.md"}
    it = origin_item(repo, REF)
    assert it.due.isoformat() == "2026-09-22" and it.hide_until.isoformat() == "2026-10-01"  # v2.3: Due: stays
    assert load(repo) == mine and git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "status", "--porcelain") == "M other.txt"  # someone else's edit, untouched
    assert "board/" not in git(repo, "ls-remote", "--heads", "origin")  # the PR's branch is deleted
    # found by a v2 line's text alone, as a press from before the split names it; done moves the file to archive/
    done = board.write_back(repo, 8, UNDATED, "done")
    assert origin_item(repo, UNDATED_REF).closed is not None
    month = date.today().isoformat()[:7]
    assert board_files(repo) == {
        f"docs/user_attention/{done['id']}.md",
        f"docs/user_attention/archive/{month}/{done['id']}.md",
    }
    assert board.tree_dir(repo).exists()  # kept between presses


@pytest.mark.parametrize("state", ["branch", "dirty", "rebase"])
def test_the_checkouts_state_refuses_nothing(repo, state):
    """§4.4: the checkout's branch, a dirty board or a rebase under way refuses nothing now."""
    if state == "branch":
        git(repo, "checkout", "-q", "-b", "td-feature")
    elif state == "dirty":
        write_board(repo, BOARD_TEXT + "- [ ] 2026-09-29 (n/a) — an item being written. Due: 2026-09-30.\n")
    elif state == "rebase":
        (Path(git(repo, "rev-parse", "--absolute-git-dir")) / "rebase-merge").mkdir()
    before = load(repo)
    board.write_back(repo, 7, ITEM, "done")
    assert origin_item(repo, REF).closed is not None and load(repo) == before


def test_an_item_only_the_checkout_holds_is_named_and_one_done_on_origin_is_the_moved_refusal(repo):
    """§4.4: origin's item is found by its reference wherever its file is (a v3 board has no lines, TD-1881); an
    item the checkout alone holds is *not on origin yet*; an item origin no longer holds open is the closed,
    moved-item refusal. Nothing lands for either refusal."""
    write_board(
        repo, BOARD_TEXT.replace("## Needs the user\n\n", "## Needs the user\n\n- [ ] 2026-09-19 (n/a) — new.\n")
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "an item above")
    git(repo, "push", "-q", "origin", "main")
    got = board.write_back(repo, 7, ITEM, "done")  # the reader read line 7; the item is found by its key
    assert got["key"] == REF and origin_item(repo, REF).closed is not None
    before = on_origin(repo, "rev-parse", "origin/main")
    with pytest.raises(board.Refused, match="no longer holds this item"):
        board.write_back(repo, 8, ITEM, "done")  # done on origin; the checkout, behind, still shows it
    write_board(repo, BOARD_TEXT + "- [ ] 2026-09-29 (n/a) — unpushed. Due: 2026-09-30.\n")
    with pytest.raises(board.Refused, match="not on origin yet: push the checkout first"):
        board.write_back(repo, 9, "2026-09-29 (n/a) — unpushed. Due: 2026-09-30.", "done")  # uncommitted
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "unpushed")
    with pytest.raises(board.Refused, match="not on origin yet: push the checkout first"):
        board.write_back(repo, None, "unpushed.", "done")  # committed, not pushed; named by its words
    assert on_origin(repo, "rev-parse", "origin/main") == before


def test_origin_out_of_reach_refuses_the_press_and_lands_nothing(repo, monkeypatch, tmp_path):
    """§4.4: no `gh`, a PR the forge will not open, an origin that cannot be fetched — each is
    *origin could not be reached (<why>): the edit was not made*, the tree reset, no branch left."""
    before = on_origin(repo, "rev-parse", "origin/main")
    monkeypatch.setenv("FAKE_GH_FAIL", "create")
    with pytest.raises(board.Refused, match=r"origin could not be reached \(gh pr create: .*\): the edit was not made"):
        board.write_back(repo, 7, ITEM, "done")
    assert "board/" not in git(repo, "ls-remote", "--heads", "origin")
    assert git(board.tree_dir(repo), "status", "--porcelain") == ""
    assert git(board.tree_dir(repo), "rev-parse", "HEAD") == before
    monkeypatch.delenv("FAKE_GH_FAIL")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # no gh at all
    if __import__("shutil").which("gh") is None:
        with pytest.raises(board.Refused, match="gh is not installed"):
            board.write_back(repo, 7, ITEM, "done")
    monkeypatch.undo()
    git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    with pytest.raises(board.Refused, match=r"origin could not be reached \(git fetch: "):
        board.write_back(repo, 7, ITEM, "done")


def test_a_push_the_forge_refuses_reads_apart_from_an_unreachable_origin(repo, tmp_path, monkeypatch):
    """TD-1242, design §4.4 *Board write-back*: a push origin took and refused reads *origin refused the push
    (<the forge's reason>)*, its `remote: error:` line else its status line's parenthesis, the tree reset and no
    branch left; a push that cannot connect still reads *origin could not be reached*. The push runs under
    `LC_ALL=C` whatever the process's locale, so the words read are git's English ones (TD-1251)."""
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    monkeypatch.setenv("LANGUAGE", "de")
    before = on_origin(repo, "rev-parse", "origin/main")
    hook = Path(git(repo, "remote", "get-url", "origin")) / "hooks" / "pre-receive"
    seen = tmp_path / "push-locale"
    hook.write_text(
        f'#!/bin/sh\nprintf %s "$LC_ALL" > {seen}\n'
        "echo 'error: GH007: Your push would publish a private email address.' >&2\nexit 1\n"
    )
    hook.chmod(0o755)
    with pytest.raises(board.Refused) as e:
        board.write_back(repo, 7, ITEM, "done")
    assert str(e.value) == (
        "origin refused the push (GH007: Your push would publish a private email address.): the edit was not made"
    )
    assert seen.read_text() == "C"
    assert "could not be reached" not in str(e.value)
    assert "board/" not in git(repo, "ls-remote", "--heads", "origin")
    assert git(board.tree_dir(repo), "status", "--porcelain") == ""
    assert git(board.tree_dir(repo), "rev-parse", "HEAD") == before
    hook.write_text("#!/bin/sh\nexit 1\n")
    with pytest.raises(board.Refused) as e:
        board.write_back(repo, 7, ITEM, "done")
    assert str(e.value) == "origin refused the push (pre-receive hook declined): the edit was not made"
    hook.unlink()
    git(repo, "config", "remote.origin.pushurl", str(tmp_path / "gone.git"))
    with pytest.raises(board.Refused, match=r"origin could not be reached \(git push: "):
        board.write_back(repo, 7, ITEM, "done")
    assert "board/" not in git(repo, "ls-remote", "--heads", "origin")


def test_a_refused_push_without_a_remote_error_reads_its_status_line_else_the_last_line():
    """TD-1252, design §4.4 *Board write-back*: with no `remote: error:` line, a plain `! [rejected]` (git's
    non-fast-forward) gives its parenthesis, a rejection with none gives git's last line, and an output with
    neither reads as no forge reached (None)."""

    def cp(err: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["git", "push"], 1, "", err)

    to = "To github.com:o/r.git\n"
    assert board._push_refusal(cp(to + " ! [rejected]        HEAD -> board/x (fetch first)\n")) == "fetch first"
    bare = to + " ! [remote rejected] HEAD -> board/x\nerror: failed to push some refs to 'github.com:o/r.git'\n"
    assert board._push_refusal(cp(bare)) == "error: failed to push some refs to 'github.com:o/r.git'"
    assert board._push_refusal(cp("fatal: unable to access 'https://x/': Could not resolve host: x\n")) is None


def test_a_merge_the_forge_refuses_closes_the_pr_and_names_a_moved_line(repo, monkeypatch, forge):
    """§4.4: origin moving elsewhere between fetch and merge refuses nothing (the squash lands); a
    refused merge closes the PR and deletes its branch, and is the moved-line refusal when origin
    no longer holds the item, else unreachable."""
    import json

    monkeypatch.setenv("FAKE_GH_FAIL", "merge")
    with pytest.raises(board.Refused, match=r"origin could not be reached \(gh pr merge: "):
        board.write_back(repo, 7, ITEM, "done")
    bare = Path(git(repo, "remote", "get-url", "origin"))
    assert json.loads((bare / "fake-gh.json").read_text())["prs"]["1"]["state"] == "closed"
    assert "board/" not in git(repo, "ls-remote", "--heads", "origin")
    # the line itself moved on origin while the press was out: the merge fails, and says so
    real = board._land

    def land(root, t, want, msg, clock, still, **kw):
        other = Path(str(t) + "-other")
        git(repo, "clone", "-q", str(bare), str(other))
        write_board(other, BOARD_TEXT.replace(f"- [ ] {ITEM}", f"- [x] {ITEM} Closed: 2026-10-01."))
        git(other, "add", "-A")
        git(other, "-c", "user.name=o", "-c", "user.email=o@x", "commit", "-qm", "done elsewhere")
        git(other, "push", "-q", "origin", "main")
        return real(root, t, want, msg, clock, still, **kw)

    monkeypatch.setattr(board, "_land", land)
    with pytest.raises(board.Refused, match="no longer holds this item"):
        board.write_back(repo, 7, ITEM, "snooze", "2026-10-09")
    # origin moved elsewhere in between — another file — refuses nothing: the squash lands on it
    monkeypatch.delenv("FAKE_GH_FAIL")

    def land_elsewhere(root, t, want, msg, clock, still, **kw):
        other = Path(str(t) + "-third")
        git(repo, "clone", "-q", str(bare), str(other))
        (other / "other.txt").write_text("moved on\n")
        git(other, "-c", "user.name=o", "-c", "user.email=o@x", "commit", "-qam", "elsewhere")
        git(other, "push", "-q", "origin", "main")
        return real(root, t, want, msg, clock, still, **kw)

    monkeypatch.setattr(board, "_land", land_elsewhere)
    git(repo, "fetch", "-q", "origin")
    board.write_back(repo, 8, UNDATED, "done")
    assert origin_item(repo, UNDATED_REF).closed is not None
    assert on_origin(repo, "show", "origin/main:other.txt") == "moved on"


def test_a_failed_commit_leaves_the_board_as_it_was(repo):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'no commits today' >&2\nexit 1\n")
    hook.chmod(0o755)
    before = origin_docs(repo)
    with pytest.raises(board.Refused, match="no commits today"):
        board.write_back(repo, 7, ITEM, "done")
    assert origin_docs(repo) == before and git(board.tree_dir(repo), "status", "--porcelain") == ""


def test_a_commit_that_does_not_finish_leaves_the_board_as_it_was(repo, monkeypatch):
    """Review of PR #474: a timeout raised past the returncode check and left the edit uncommitted."""
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nsleep 5\n")
    hook.chmod(0o755)
    monkeypatch.setattr(board, "GIT_TIMEOUT", 0.5)
    before = origin_docs(repo)
    with pytest.raises(board.Refused, match="did not finish"):
        board.write_back(repo, 7, ITEM, "done")
    assert origin_docs(repo) == before


def test_two_edits_at_once_are_made_one_after_the_other(repo):
    """Review of PR #474: two interleaved read-write-commits left *done* in the log and undone on disk."""
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        a = pool.submit(board.write_back, repo, 7, ITEM, "done")
        b = pool.submit(board.write_back, repo, 8, UNDATED, "done")
        a.result(), b.result()
    assert origin_item(repo, REF).closed is not None and origin_item(repo, UNDATED_REF).closed is not None


async def test_board_edit_is_the_persons_and_only_on_a_known_board(agent, repo, tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    path = str(repo / board.BOARD)
    async with LocalClient(caller="ao-some-worker") as worker:
        with pytest.raises(AgentError, match="a person's own act"):
            await worker.call("board_edit", board=path, line=7, text=ITEM, action="done")
    async with LocalClient() as me:
        with pytest.raises(AgentError, match="not the board of a repo this host knows"):
            await me.call("board_edit", board=str(tmp_path / "elsewhere.md"), line=7, text=ITEM, action="done")
        with pytest.raises(AgentError, match="no longer holds this item"):
            await me.call("board_edit", board=path, line=7, text="something else", action="done")
        got = await me.call("board_edit", board=path, line=7, text=ITEM, action="snooze", due="2026-10-01")
    assert got["action"] == "snooze" and got["message"].startswith(f"shiftlead: snooze {got['id']} Merged")
    assert on_origin(repo, "log", "-1", "--format=%s", "origin/main") == f"{got['message']} (#{got['pr']})"


def _key(root: Path) -> str:
    """The reference of the item ITEM is (§4.4 *A board line's id*): its v2 key's eight hex, kept by the split."""
    return REF


def test_now_writes_the_host_agents_today_and_the_next_reading_draws_the_item(repo):
    """The Snoozed fold's *now* (§4.4 *Board write-back*, TD-1349): a `snooze` with no date writes the host agent's
    today as the item's `Hide until:`, in the item and its commit subject, and answers the date written; the next
    reading draws the item, no longer hidden. A *now* on an item whose hide is past writes today and commits too."""
    from datetime import timedelta

    today = date.today()
    later = (today + timedelta(days=5)).isoformat()
    board.write_back(repo, 7, ITEM, "snooze", later)
    hidden = origin_item(repo, REF)
    assert hidden.hidden(today) and hidden.hide_until.isoformat() == later
    got = board.write_back(repo, None, "", "snooze", key=_key(repo))
    assert got["due"] == today.isoformat() and got["pr"]
    assert got["message"].endswith(f"to {today.isoformat()} (session grinder-ao-1)")
    assert on_origin(repo, "log", "-1", "--format=%s", "origin/main") == f"{got['message']} (#{got['pr']})"
    shown = origin_item(repo, REF)
    assert shown.hide_until == today and shown.due.isoformat() == "2026-09-22"  # one field, rewritten
    assert not shown.hidden(today) and sum(1 for f, _ in shown.fields if f == "Hide until") == 1
    # a hide already past (an item hidden until a day gone): *now* writes today and lands it
    board.write_back(repo, None, "", "snooze", "2026-01-05", key=_key(repo))
    got = board.write_back(repo, None, "", "snooze", key=_key(repo))
    assert got["pr"] and origin_item(repo, REF).hide_until == today


def test_now_on_an_item_that_already_says_today_lands_nothing(repo):
    """§4.4 *Board write-back* (TD-1349): a *now* whose filled date already stands on the item — the day
    turned under an open page — changes nothing: answered as done with origin's head, its subject and the
    date, no `pr`, and no commit or branch on origin."""
    board.write_back(repo, 7, ITEM, "snooze", date.today().isoformat())
    before = on_origin(repo, "rev-parse", "origin/main")
    got = board.write_back(repo, None, "", "snooze", key=_key(repo))
    assert "pr" not in got and got["due"] == date.today().isoformat() and got["key"] == REF
    assert got["commit"] == on_origin(repo, "rev-parse", "--short", "origin/main")
    assert on_origin(repo, "rev-parse", "origin/main") == before
    assert got["message"].startswith(f"shiftlead: snooze {got['id']} Merged") and got["text"].startswith("**Merged")
    assert "board/" not in git(repo, "ls-remote", "--heads", "origin")
    tree = board.tree_dir(repo)
    assert git(tree, "status", "--porcelain") == ""  # the tree left at origin's head


async def test_board_edit_answers_a_now_with_the_date_it_wrote(agent, repo, tmp_path):
    """`board_edit` (§4.4, TD-1349): a snooze sent with no date is the fold's *now* — the RPC answers the
    date the write-back wrote, never the request's, and a *now* that changed nothing is a success with
    no PR opened."""
    from datetime import date

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    path = str(repo / board.BOARD)
    today = date.today().isoformat()
    async with LocalClient() as me:
        got = await me.call("board_edit", board=path, line=7, text=ITEM, action="snooze")
        assert got["due"] == today and got["pr"]
        again = await me.call("board_edit", board=path, line=7, text="", action="snooze", key=_key(repo))
    assert again["due"] == today and "pr" not in again and again["action"] == "snooze"


def test_put_on_the_board_writes_one_item_file_and_commits_it(repo):
    """TD-140 (design §4.4, §4.5a): the one add — an item file in the board's own format (ledgerboard v3.0's
    `item_file`, its id drawn, TD-1881), committed with the message naming it, no other file touched."""
    before = load(repo)
    got = board.add(
        repo, "Check the fetcher Friday.", "2026-10-02", session="grinder-ao-2", host="kmaster",
        context="TD-900", today="2026-09-25",
    )  # fmt: skip
    it = origin_item(repo, got["key"])
    assert (it.words, it.session, it.host, it.context) == (
        "Check the fetcher Friday.",
        "grinder-ao-2",
        "kmaster",
        "TD-900",
    )
    assert it.due == date(2026, 10, 2) and it.added == date(2026, 9, 25) and got["id"] == it.id
    assert got["id"].startswith("2026-09-25-") and got["key"] == "board:" + got["id"][-8:]
    assert got["message"] == f"shiftlead: append {got['id']} Check the fetcher Friday. (session grinder-ao-2)"
    assert board_files(repo) == {f"docs/user_attention/{got['id']}.md"}
    assert on_origin(repo, "log", "-1", "--format=%s", "origin/main") == f"{got['message']} (#{got['pr']})"
    assert load(repo) == before  # the checkout catches up by the pull
    # no sender, no about: none of either
    bare = ledgerboard.parse_item(board.item_file("x", "2026-10-02", "2026-09-25", None, None, None))
    assert (bare.words, bare.session, bare.context, bare.due) == ("x", None, "none", date(2026, 10, 2))
    for bad in (("", "2026-10-02"), ("two\nlines", "2026-10-02"), ("x", "Friday")):
        with pytest.raises(board.Refused):
            board.add(repo, *bad)
    assert on_origin(repo, "rev-list", "--count", "origin/main") == "2"


def test_the_add_on_a_board_with_no_items_writes_its_one_file(repo):
    write_board(repo, "# User attention\n\n## Needs the user\n\n## Later\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "empty")
    git(repo, "push", "-q", "origin", "main")
    got = board.add(repo, "First", "2026-10-02", today="2026-09-25")
    assert [(it.id, it.words) for it in origin(repo).items] == [(got["id"], "First")]


def test_the_add_is_refused_touching_nothing_where_an_edit_is(repo, monkeypatch):
    git(repo, "checkout", "-q", "-b", "feature")  # refuses nothing now (§4.4)
    board.add(repo, "x", "2026-10-02")
    before = on_origin(repo, "rev-parse", "origin/main")
    monkeypatch.setenv("FAKE_GH_FAIL", "merge")
    with pytest.raises(board.Refused, match="origin could not be reached"):
        board.add(repo, "y", "2026-10-02")
    assert on_origin(repo, "rev-parse", "origin/main") == before


async def test_put_on_the_board_is_the_persons_from_an_fyi_row_and_dismisses_it(agent, repo, tmp_path, monkeypatch):
    """TD-140: `board_edit` with `action: add` takes an FYI row — a `note` here — writes the item
    naming its sender and `about`, commits, then dismisses the row; an open question is refused, as
    is an entry the person inbox does not hold, a session, and a refused commit, which leaves the
    row where it was."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    path = str(repo / board.BOARD)
    async with LocalClient() as me:
        w = (
            await me.call(
                "create", name="w", dir=str(tmp_path), adapter="shell", role="worker", argv=["bash", "--norc"]
            )
        )["id"]
        async with LocalClient(caller=w) as worker:
            note = (await worker.call("msg", to="person", text="check this Friday", about="TD-900"))["entry"]
            asked = (await worker.call("msg", to="person", text="which?", kind="ask"))["entry"]
            with pytest.raises(AgentError, match="a person's own act"):
                await worker.call("board_edit", board=path, action="add", text="x", due="2026-10-02", entry=note["id"])
        with pytest.raises(AgentError, match="open ask"):
            await me.call("board_edit", board=path, action="add", text="x", due="2026-10-02", entry=asked["id"])
        with pytest.raises(AgentError, match="holds no entry m-nope"):
            await me.call("board_edit", board=path, action="add", text="x", due="2026-10-02", entry="m-nope")
        with monkeypatch.context() as m:  # a refused landing: the row stays
            m.setenv("FAKE_GH_FAIL", "create")
            with pytest.raises(AgentError, match="origin could not be reached"):
                await me.call("board_edit", board=path, action="add", text="x", due="2026-10-02", entry=note["id"])
        assert note["id"] in [e["id"] for e in (await me.call("inbox"))["entries"]]
        got = await me.call(
            "board_edit", board=path, action="add", text="Check the fetcher", due="2026-10-02", entry=note["id"]
        )
        assert got["dismissed"] == [note["id"]]
        assert got["message"].startswith(f"shiftlead: append {got['id']} Check the fetcher")
        it = origin_item(repo, got["key"])
        assert it.closed is None and it.session == "w" and it.context == "TD-900" and it.due == date(2026, 10, 2)
        assert note["id"] not in [e["id"] for e in (await me.call("inbox"))["entries"]]
        await me.call("kill", id=w)


# retired (TD-1881): test_the_add_lands_in_needs_the_user_never_above_another_sections_items — a v3 board is a
# directory of item files with no sections, so an add has no place among other items to land in


async def test_put_on_the_board_twice_at_once_writes_one_line_and_a_refused_dismiss_is_said(
    agent, repo, tmp_path, monkeypatch
):
    """Review of PR #578: two presses on one entry at once write one line, the second refused; and
    a dismiss refused after the commit landed is reported beside the commit, not raised."""
    import asyncio

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    path = str(repo / board.BOARD)
    async with LocalClient() as me:
        w = (await me.call("create", name="w", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
        async with LocalClient(caller=w) as worker:
            one = (await worker.call("msg", to="person", text="one"))["entry"]
            two = (await worker.call("msg", to="person", text="two"))["entry"]
        args = dict(board=path, action="add", text="Check it", due="2026-10-02")
        async with LocalClient() as a, LocalClient() as b:
            got = await asyncio.gather(
                a.call("board_edit", **args, entry=one["id"]), b.call("board_edit", **args, entry=one["id"]),
                return_exceptions=True,
            )  # fmt: skip
        assert sum(isinstance(g, dict) for g in got) == 1
        # refused while the first is under way — or, had it already finished, because the row is gone
        refused = str(next(g for g in got if not isinstance(g, dict)))
        assert "already being put on the board" in refused or "holds no entry" in refused
        assert sum(it.words == "Check it" for it in origin(repo).items) == 1

        async def refuse(**_):
            from sessionorc.agent import RpcError

            raise RpcError("refused for the test")

        monkeypatch.setattr(agent, "rpc_inbox_dismiss", refuse)
        got = await me.call("board_edit", **args, entry=two["id"])
        assert got["dismissed"] == [] and got["dismiss_refused"] == "refused for the test" and got["commit"]
        await me.call("kill", id=w)


def test_a_reply_is_appended_to_the_items_log_signed_and_committed(repo):
    """TD-142 slice 1 (design §4.4): Reply appends a Log line `- <date>: <name>: <reply>` to the item's file
    (ledgerboard v3.0, TD-1881), the name the checkout's git `user.name`, one commit with the fixed message, the
    item still open."""
    git(repo, "config", "user.name", "Paul")
    got = board.write_back(repo, 7, ITEM, "reply", reply="  rebase it,\nthen merge  ")
    today = date.today().isoformat()
    it = origin_item(repo, REF)
    assert it.replies == [("Paul", today, "rebase it, then merge")] and it.closed is None
    assert got["message"] == (
        f"shiftlead: reply {got['id']} Merged, live check pending: the doorbell. Look. (session grinder-ao-1)"
    )
    assert (
        on_origin(repo, "log", "-1", "--format=%s", "origin/main") == f"{got['message']} (#{got['pr']})"
        and git(repo, "status", "--porcelain") == ""
    )
    # the item is still open, so a second reply or a Done finds it by its words
    board.write_back(repo, None, got["text"], "done")
    assert origin_item(repo, REF).closed is not None


def test_a_reply_is_refused_touching_nothing_where_an_edit_is(repo, tmp_path):
    before = origin_docs(repo)
    for args, why in (
        ((7, ITEM, "reply"), "needs its text"),
        ((8, "not an item", "reply"), "no longer holds this item"),
    ):
        with pytest.raises(board.Refused, match=why):
            board.write_back(repo, *args, reply="" if why == "needs its text" else "x")
    assert origin_docs(repo) == before
    # retired (TD-1881): v2's refusal of a reply carrying `Due:` on an item with none — a v3 reply is a Log line of
    # its own, which no reader takes for the item's Due
    it = _items(tmp_path / "b")[REF]
    signed = ledgerboard.parse_item(board.edit_item(it, "reply", reply="y", by="the person", today="2026-09-25"))
    assert signed.replies == [("the person", "2026-09-25", "y")]


async def test_board_reply_is_the_persons_and_mails_nobody_without_a_holder(agent, repo, tmp_path):
    """The RPC (§4.4): person-only, a known board only, the file half written and, with nobody
    holding a lease on the item's refs, `sent` empty — and `board_edit` will not take a reply,
    which is `board_reply`'s."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    path = str(repo / board.BOARD)
    async with LocalClient(caller="ao-some-worker") as worker:
        with pytest.raises(AgentError, match="a person's own act"):
            await worker.call("board_reply", board=path, line=7, text=ITEM, reply="x")
    async with LocalClient() as me:
        with pytest.raises(AgentError, match="not the board of a repo this host knows"):
            await me.call("board_reply", board=str(tmp_path / "elsewhere.md"), line=7, text=ITEM, reply="x")
        with pytest.raises(AgentError, match="is board_reply"):
            await me.call("board_edit", board=path, line=7, text=ITEM, action="reply")
        with pytest.raises(AgentError, match="no longer holds this item"):
            await me.call("board_reply", board=path, line=8, text="not an item", reply="x")
        with pytest.raises(AgentError, match="names the item's line"):
            await me.call("board_reply", board=path, text="", reply="x")  # neither its id nor its words
        got = await me.call("board_reply", board=path, line=7, text=ITEM, reply="rebase it", refs=["TD-122"])
    assert got["action"] == "reply" and got["sent"] == [] and got["note"] == "written on the board"
    assert on_origin(repo, "log", "-1", "--format=%s", "origin/main") == f"{got['message']} (#{got['pr']})"
    assert got["message"].startswith(f"shiftlead: reply {got['id']} Merged")
    assert origin_item(repo, REF).replies[-1][2] == "rebase it"
    async with LocalClient() as me:  # no holder: no mail, and the trail line is still owed (§4.5a)
        trail = [t for t in (await me.call("inbox"))["trail"] if t["kind"] == "board reply"]
    assert [t["how"] for t in trail] == ["written on the board"]


def test_board_refs_are_named_as_a_lease_names_them():
    """The reader's `refs` (§4.4) against a claim's reference (§4.8): canonical ids, `PR #N` as `#N`."""
    from sessionorc.agent_inbox import board_refs

    assert board_refs(["td-122", "PR #1020", "TD-122", " ", "pr#7"]) == ["TD-122", "#1020", "#7"]
    assert board_refs(None) == []


async def test_board_reply_hands_a_note_to_each_live_lease_holder(agent, repo, tmp_path):
    """TD-142 slice 2 (§4.5a *Inbox board row → Reply*, §4.10 *A board reply owes an outcome too*):
    after the commit, each live record with a declared lease on one of the line's refs gets one
    `note` from the person, `about` the ref, marked `handed` — a holder of two refs once, a
    session holding none nothing — and the result says where it went."""
    _registry(tmp_path, repo)
    path = str(repo / board.BOARD)
    async with LocalClient() as me:
        mk = lambda n: me.call("create", name=n, dir=_own(tmp_path, n), adapter="agentshell", argv=["bash", "--norc"])  # noqa: E731
        h, both, idle = [(await mk(n))["id"] for n in ("holder", "both", "idle")]
        for sid, refs in ((h, ["td-122"]), (both, ["#1020", "TD-123"])):
            async with LocalClient(caller=sid) as s:
                for ref in refs:
                    await s.call("progress", id=sid, ref=ref)
        got = await me.call(
            "board_reply", board=path, line=7, text=ITEM, reply="rebase it", refs=["TD-122", "PR #1020", "td-123"]
        )
        assert sorted((x["session"], x["ref"]) for x in got["sent"]) == [("both", "#1020"), ("holder", "TD-122")]
        assert got["note"].startswith("written on the board · sent to ") and "holder (holds TD-122)" in got["note"]
        assert origin_item(repo, REF).replies[-1][2] == "rebase it"  # the file half first
        for sid in (h, both):
            notes = [e for e in (await me.call("inbox", id=sid))["entries"] if e["from"] == "person"]
            assert len(notes) == 1 and notes[0]["kind"] == "note" and notes[0]["handed"]
            assert (
                notes[0]["about"] == ("TD-122" if sid == h else "#1020") and notes[0]["outcome"] is None
            )  # owes an outcome (§4.10)
            assert notes[0]["text"].startswith("board: Merged, live check pending: the doorbell.\n\n")
            assert notes[0]["text"].endswith(": rebase it")
        assert not [e for e in (await me.call("inbox", id=idle))["entries"] if e["from"] == "person"]
        # the trail says what the result says (§4.5a *Inbox board row → Reply*): one entry, no record
        trail = [t for t in (await me.call("inbox"))["trail"] if t["kind"] == "board reply"]
        assert len(trail) == 1 and trail[0]["how"] == got["note"] and trail[0]["sid"] == ""
        assert trail[0]["name"] == repo.name and trail[0]["text"].endswith(": rebase it")
        for sid in (h, both, idle):
            await me.call("kill", id=sid)


async def _orphan(me, repo, tmp_path, text, about, **kw):
    """A question from a session in `repo` that names `about`, orphaned by closing its asker."""
    w = (await me.call("create", name="asker", dir=str(repo), adapter="agentshell", argv=["bash", "--norc"]))["id"]
    async with LocalClient(caller=w) as s:
        mid = (await s.call("msg", to="person", text=text, about=about, **kw))["entry"]["id"]
    await me.call("close", id=w)
    return mid


def _registry(tmp_path, repo):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")


async def test_an_answer_to_an_orphaned_question_is_written_on_the_board_and_sent_to_its_holder(agent, repo, tmp_path):
    """TD-216 (design §4.10 *A question about a reference outlives its asker*, §4.4 the second add):
    with no holder the answer is one item on the asker's repo's board and nothing is mailed; with a
    holder it is the item and one `handed` note that owes an outcome; *Go with it* writes the
    default; the entry closes, its own debt settled, since nobody is left to report it."""
    _registry(tmp_path, repo)
    async with LocalClient() as me:
        q = await _orphan(
            me, repo, tmp_path, "Which fetcher first?\n\nThe reading, for the record.", "TD-149", kind="ask"
        )
        got = await me.call("msg", text="the DIU one", kind="reply", reply_to=q)
        assert got["sent"] == [] and got["closed"] == q
        assert got["note"] == "written on the board · left in asker's mailbox for its next run"
        # the closed asker's own record keeps the handed note for the name's next create (TD-271)
        left = [e for e in (await me.call("inbox", id=got["asker"]))["entries"] if e["from"] == "person"]
        assert len(left) == 1 and left[0]["handed"] and left[0]["text"].startswith("the DIU one")
        # the answer stays off the subject
        assert got["message"] == f"shiftlead: append {got['id']} Which fetcher first? (session asker)"
        it = origin_item(repo, got["key"])
        assert it.session == "asker" and it.words == "Which fetcher first?" and it.context == "TD-149"
        assert [(by, words) for by, _, words in it.replies] == [("t", "the DIU one")] and it.due is not None
        assert "The reading" not in it.raw  # the first paragraph only
        e = [e for e in (await me.call("inbox"))["entries"] if e["id"] == q][0]
        assert e["closed_reason"] == "replied" and e["outcome"]["state"] == "asker_gone"  # owes nothing
        assert git(repo, "status", "--porcelain") == ""  # committed, never left dirty

        # with a holder: the item, and one handed note to the session that holds the reference
        h = (await me.call("create", name="holder", dir=str(tmp_path), adapter="agentshell", argv=["bash", "--norc"]))[
            "id"
        ]
        async with LocalClient(caller=h) as s:
            await s.call("progress", id=h, ref="td-149")
        steer = await _orphan(me, repo, tmp_path, "Drop the key?", "td-149", kind="steer", default="drop it")
        got = await me.call("inbox_go_with_it", msg=steer)
        assert (
            got["sent"] == [h] and got["closed_reason"] == "go_with_it" and f"sent to {h} (holds TD-149)" in got["note"]
        )
        it = origin_item(repo, got["key"])
        assert it.context == "td-149" and it.replies[0][2] == "go with the default: drop it"
        handed = [e for e in (await me.call("inbox", id=h))["entries"] if e["from"] == "person"]
        assert len(handed) == 1 and handed[0]["handed"] and handed[0]["about"] == "TD-149"
        assert handed[0]["text"].startswith("go with the default: drop it")
        assert handed[0]["outcome"] is None  # handed and unsettled: the holder owes an outcome (§4.10)
        assert agent.sessions[h].inbox[-1].owes_for(session_inbox=True)
        await me.call("kill", id=h)


async def test_a_full_closed_askers_mailbox_never_keeps_the_answer_from_the_holder(agent, repo, tmp_path, monkeypatch):
    """TD-274 slice 3 (review of the slice): the holder's note and the closed asker's are two
    sends, so an asker whose mailbox is at depth is said beside the press and the holder is still
    mailed."""
    from sessionorc import mail

    _registry(tmp_path, repo)
    async with LocalClient() as me:
        h = (await me.call("create", name="holder", dir=str(tmp_path), adapter="agentshell", argv=["bash", "--norc"]))[
            "id"
        ]
        async with LocalClient(caller=h) as s:
            await s.call("progress", id=h, ref="TD-149")
        q = await _orphan(me, repo, tmp_path, "Which?", "TD-149", kind="ask")
        asker = next(r.id for r in agent.sessions.values() if r.name == "asker")
        monkeypatch.setattr(mail, "MAILBOX_DEPTH", 1)
        agent._system_note(asker, "filler")  # the asker's mailbox at depth
        got = await me.call("msg", text="this one", kind="reply", reply_to=q)
        assert got["sent"] == [h] and "asker" not in got and got["asker_refused"]
        assert "not left in asker's mailbox" in got["note"]
        assert [e["text"] for e in (await me.call("inbox", id=h))["entries"] if e["from"] == "person"][0].startswith(
            "this one"
        )
        await me.call("kill", id=h)


async def test_an_answer_to_an_orphaned_question_is_refused_touching_nothing_when_the_board_cannot_take_it(
    agent, repo, tmp_path, monkeypatch
):
    """TD-216: origin out of reach refuses the press and the entry stays open; a second press while the
    first is in flight is refused; a reply naming another addressee, or a suggested answer that is
    not word for word, is refused; Pause stays refused (no session to hold)."""
    import asyncio

    _registry(tmp_path, repo)
    async with LocalClient() as me:
        q = await _orphan(me, repo, tmp_path, "Which?", "#702", kind="ask", answers=["this", "that"])
        with monkeypatch.context() as m:
            m.setenv("FAKE_GH_FAIL", "merge")
            with pytest.raises(AgentError, match="origin could not be reached"):
                await me.call("msg", text="this", kind="reply", reply_to=q, answer=0)
        e = [e for e in (await me.call("inbox"))["entries"] if e["id"] == q][0]
        assert e["closed_reason"] is None and e["orphaned"]
        with pytest.raises(AgentError, match="suggested answers"):
            await me.call("msg", text="thus", kind="reply", reply_to=q, answer=0)
        async with LocalClient() as a, LocalClient() as b:
            got = await asyncio.gather(
                a.call("msg", text="this", kind="reply", reply_to=q, answer=0),
                b.call("msg", text="this", kind="reply", reply_to=q, answer=0),
                return_exceptions=True,
            )  # fmt: skip
        assert sum(isinstance(g, dict) for g in got) == 1
        refused = str(next(g for g in got if not isinstance(g, dict)))
        assert "already being answered" in refused or "already closed" in refused
        assert sum(it.context == "#702" and it.replies[0][2] == "this" for it in origin(repo).items) == 1
        e = [e for e in (await me.call("inbox"))["entries"] if e["id"] == q][0]
        assert e["answer"] == 0


async def test_an_orphaned_question_is_answered_by_its_label_or_its_whole_line(agent, repo, tmp_path):
    """TD-919 (§4.10 *The answers' split*, TD-913): an orphaned `ask` whose stored answers are
    `<label> — <consequence>` is answered by the label the page draws, and by the whole stored line;
    a press whose text is neither is refused and the entry stays open."""
    _registry(tmp_path, repo)
    answers = ["Keep it — the window stays as it is", "Lift it — the cap goes for a week"]
    async with LocalClient() as me:
        q = await _orphan(me, repo, tmp_path, "Which window?", "TD-190", kind="ask", answers=answers)
        with pytest.raises(AgentError, match="suggested answers"):
            await me.call("msg", text="Lift", kind="reply", reply_to=q, answer=1)
        e = [e for e in (await me.call("inbox"))["entries"] if e["id"] == q][0]
        assert e["closed_reason"] is None and e["orphaned"]
        got = await me.call("msg", text="Lift it", kind="reply", reply_to=q, answer=1)
        assert got["closed"] == q
        e = [e for e in (await me.call("inbox"))["entries"] if e["id"] == q][0]
        assert e["closed_reason"] == "replied" and e["answer"] == 1
        assert sum(it.context == "TD-190" and it.replies[0][2] == "Lift it" for it in origin(repo).items) == 1

        whole = await _orphan(me, repo, tmp_path, "Which window again?", "TD-191", kind="ask", answers=answers)
        got = await me.call("msg", text=answers[0], kind="reply", reply_to=whole, answer=0)
        assert got["closed"] == whole
        e = [e for e in (await me.call("inbox"))["entries"] if e["id"] == whole][0]
        assert e["closed_reason"] == "replied" and e["answer"] == 0


async def test_a_refused_note_to_the_holder_is_said_beside_the_committed_line_and_closes_the_entry(
    agent, repo, tmp_path, monkeypatch
):
    """Review of PR #717: the line is committed before the holder is mailed, so a refused send is
    reported with the result and the entry closes — a second press must not write the line twice.
    A reply naming another addressee, and a reply to a closed orphaned entry, are refused."""
    from sessionorc.agent_common import RpcError

    _registry(tmp_path, repo)
    async with LocalClient() as me:
        h = (await me.call("create", name="holder", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
        async with LocalClient(caller=h) as s:
            await s.call("progress", id=h, ref="TD-5")
        q = await _orphan(me, repo, tmp_path, "Which?", "TD-5", kind="ask")
        with pytest.raises(AgentError, match="a reply alone"):
            await me.call("msg", to=[h], text="x", kind="reply", reply_to=q)

        real = agent._msg

        async def full(sender, text, to, kind, *a, **k):
            if kind == "note":  # the holder's note, not the person's reply that leads to it
                raise RpcError("its mailbox is full")
            return await real(sender, text, to, kind, *a, **k)

        monkeypatch.setattr(agent, "_msg", full)
        got = await me.call("msg", text="this one", kind="reply", reply_to=q)
        monkeypatch.undo()
        assert got["sent"] == [] and got["mail_refused"] == "its mailbox is full" and "not sent to" in got["note"]
        e = [e for e in (await me.call("inbox"))["entries"] if e["id"] == q][0]
        assert e["closed_reason"] == "replied" and "its mailbox is full" in e["outcome"]["text"]
        with pytest.raises(AgentError, match="already closed"):
            await me.call("msg", text="again", kind="reply", reply_to=q)
        assert sum(it.context == "TD-5" and it.replies[0][2] == "this one" for it in origin(repo).items) == 1
        await me.call("kill", id=h)


ASKED = (
    "decide 2026-09-27 (session `grinder-ao-1` on kmaster) — **Which window?** Say. Context: TD-190. "
    "Due: 2026-10-04. Answers: Keep it (default) | Lift it."
)
LOOK = (
    "watch 2026-09-30 (session `grinder-ao-2` on kmaster) — **Merged, live look pending: the keys.** Look. "
    "Due: 2026-10-01. Answers: Works | Not right: <what>."
)


def test_a_decide_writes_the_items_decided_field_and_its_message(tmp_path):
    """TD-255 slice 1 (design §4.4 *Decide*): the edit `board_edit.py decide` makes, on an item file (TD-1881)."""
    write_board(tmp_path, BOARD_TEXT + f"- [ ] {ASKED}\n")
    it = item(tmp_path, ref_of(ASKED))
    got = ledgerboard.parse_item(board.edit_item(it, "decide", answer="Lift it", today="2026-10-01"), it.path)
    assert got.decided == ("Lift it", date(2026, 10, 1)) and got.closed is None
    assert board.message(it.words, "decide", answer="Lift it", id=it.id, session=it.session) == (
        f"shiftlead: decide {it.id} Which window? Say.: Lift it (session grinder-ao-1)"
    )
    long = board.message(it.words, "decide", answer="Not right: " + "the ring is amber " * 9, id=it.id, session="g")
    assert long.endswith("… (session g)") and len(long) < 160  # a sentence is clipped
    for bad in (
        lambda: board.edit_item(it, "decide", answer="  "),  # no answer
        lambda: board.edit_item(got, "decide", answer="Keep it"),  # already decided
    ):
        with pytest.raises(board.Refused):
            bad()
    # retired (TD-1881): v2's refusals of an answer or a reply carrying a field's name (`Decided:`, `Answers:`) — an
    # item file writes each field on a line of its own, so no words are read as one


# retired (TD-1881): read_back(), agent-cadence's v2 reader of one board line — a v3 item is read back by
# ledgerboard's own `parse_item()`


def test_a_reply_and_a_decide_compose_in_either_order(tmp_path):
    """§4.4 *The two compose*: a reply is a Log line of the item's file and a decide its `Decided:` field
    (ledgerboard v3.0, TD-1881), so each leaves the other, the `Answers:` and the `Due:` as they were, in either
    order."""
    write_board(tmp_path, BOARD_TEXT + f"- [ ] {ASKED}\n")
    it = item(tmp_path, ref_of(ASKED))

    def read(text: str) -> ledgerboard.BoardItem:
        return ledgerboard.parse_item(text, it.path)

    decided = read(board.edit_item(it, "decide", answer="Lift it", today="2026-10-01"))
    both = read(board.edit_item(decided, "reply", reply="the node first", by="Paul", today="2026-10-02"))
    assert both.decided == ("Lift it", date(2026, 10, 1)) and both.replies == [("Paul", "2026-10-02", "the node first")]
    assert (both.answers, both.default, both.due) == (["Keep it", "Lift it"], "Keep it", date(2026, 10, 4))
    replied = read(board.edit_item(it, "reply", reply="say more", by="Paul", today="2026-10-02"))
    both = read(board.edit_item(replied, "decide", answer="Keep it", today="2026-10-03"))
    assert both.decided == ("Keep it", date(2026, 10, 3)) and both.answers == ["Keep it", "Lift it"]
    assert both.replies == [("Paul", "2026-10-02", "say more")]


def test_a_decide_is_committed_and_refused_where_every_edit_is(repo):
    push_board(repo, BOARD_TEXT + f"- [ ] {ASKED}\n", "asked")
    got = board.write_back(repo, 9, ASKED, "decide", answer="Keep it")
    assert got["message"] == f"shiftlead: decide {got['id']} Which window? Say.: Keep it (session grinder-ao-1)"
    assert (
        on_origin(repo, "log", "-1", "--format=%s", "origin/main") == f"{got['message']} (#{got['pr']})"
        and git(repo, "status", "--porcelain") == ""
    )
    # v2.3 (TD-1330): who answered is on the item — a board with no People: names the checkout's user
    it = origin_item(repo, ref_of(ASKED))
    assert it.decided[0] == "Keep it" and it.decided_by == "t"
    head = on_origin(repo, "rev-parse", "origin/main")
    git(repo, "pull", "-q", "--ff-only", "origin", "main")  # the checkout catches up (§6 *Pull*)
    for line, text in ((9, ASKED), (6, "not an item")):  # already decided; moved
        with pytest.raises(board.Refused):
            board.write_back(repo, line, text, "decide", answer="Keep it")
        assert on_origin(repo, "rev-parse", "origin/main") == head


async def test_board_edit_decides_only_with_one_of_the_items_answers(agent, repo, tmp_path):
    """The RPC's half: the answer is one of the reader's `answers` word for word, or `Not right:`
    and words where the pair is among them; anything else is a Reply, and a session is refused."""
    push_board(repo, BOARD_TEXT + f"- [ ] {ASKED}\n- [ ] {LOOK}\n", "asked")
    path, answers, pair = str(repo / board.BOARD), ["Keep it", "Lift it"], ["Works", "Not right: <what>"]
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    async with LocalClient(caller="ao-some-worker") as worker:
        with pytest.raises(AgentError, match="person's own"):
            await worker.call("board_edit", board=path, line=9, text=ASKED, action="decide", answer="Keep it")
    async with LocalClient() as me:
        for bad, offered in (("Keep", answers), ("", answers), ("Keep it", None), ("Not right: x", answers)):
            with pytest.raises(AgentError, match="word for word"):
                await me.call(
                    "board_edit", board=path, line=9, text=ASKED, action="decide", answer=bad, answers=offered
                )
        for bad in ("Not right:", "Not right: <what>"):
            with pytest.raises(AgentError, match="needs its words"):
                await me.call("board_edit", board=path, line=10, text=LOOK, action="decide", answer=bad, answers=pair)
        got = await me.call("board_edit", board=path, line=9, text=ASKED, action="decide", answer="Keep it",
                            answers=["Keep  it", "Lift it"])  # fmt: skip
        assert got["answer"] == "Keep it"
        assert got["message"].startswith(f"shiftlead: decide {got['id']} Which window? Say.: Keep it")
        got = await me.call("board_edit", board=path, line=10, text=LOOK, action="decide",
                            answer="Not right: the ring is amber", answers=pair)  # fmt: skip
        assert got["answer"] == "Not right: the ring is amber"
    asked, look = origin_item(repo, ref_of(ASKED)), origin_item(repo, ref_of(LOOK))
    assert (asked.decided[0], asked.decided_by) == ("Keep it", "t")  # v2.3: who answered
    assert (look.decided[0], look.decided_by) == ("Not right: the ring is amber", "t")


@pytest.mark.unit
def test_an_offered_answer_word_for_word_comes_before_the_not_right_form():
    """Review of PR #863: an item whose own answer is a complete *Not right: wrong repo* is decided
    by it word for word; the form is only `Not right: <what>` (or the bare prefix), pressed as
    written it is refused, and typed words pass only where the form is offered."""
    from sessionorc.agent_inbox import InboxMixin as A

    own = ["Right repo", "Not right: wrong repo"]
    assert A._board_answer("decide", "Not right:  wrong repo", own) == "Not right: wrong repo"
    with pytest.raises(board.Refused, match="word for word"):
        A._board_answer("decide", "Not right: something else", own)  # no form offered: a Reply
    both = ["Works", "Not right: <what>", "Not right: wrong repo"]
    assert A._board_answer("decide", "Not right: wrong repo", both) == "Not right: wrong repo"
    assert A._board_answer("decide", "Not right: the ring is amber", both) == "Not right: the ring is amber"
    # a slot of its own is the form again, not words (ledgerboard's `fill_not_right`, TD-585)
    for bad in ("Not right: <what>", "Not right:", "Not right: <b>"):
        with pytest.raises(board.Refused, match="needs its words"):
            A._board_answer("decide", bad, both)
    assert A._board_answer("snooze", "anything", both) == ""


@pytest.mark.unit
def test_a_form_is_filled_never_pressed_on_a_decide():
    """TD-1698 (§4.4 *A form's press is the decide*): any form among an item's answers is filled through
    ledgerboard, `<head>: <words>` on one line, its head as offered whatever case was typed; a form as written,
    its head alone or with a placeholder is refused with *<head> needs its words*. With `form`, that form alone
    is filled, its head put back where the words lack it, never falling through to a plain answer."""
    from sessionorc.agent_inbox import InboxMixin as A

    hold = ["Go", "Hold: <note>"]
    assert A._board_answer("decide", "Hold: drop Dismiss", hold) == "Hold: drop Dismiss"
    assert A._board_answer("decide", "hold : x", hold) == "Hold: x"
    assert A._board_answer("decide", "Hold: first\nsecond  line", hold) == "Hold: first second line"
    assert A._board_answer("decide", "Go", hold) == "Go"
    for bad in ("Hold: <note>", "Hold:", "Hold: <b>"):
        with pytest.raises(board.Refused, match="Hold needs its words"):
            A._board_answer("decide", bad, hold)
    with pytest.raises(board.Refused, match="word for word"):
        A._board_answer("decide", "Wait: a day", hold)  # no such form: a Reply
    # a form handed with its consequence, pressed as written, is the form unfilled (review of #3894)
    with pytest.raises(board.Refused, match="Hold needs its words"):
        A._board_answer("decide", "Hold: <note> — pauses it", ["Go", "Hold: <note> — pauses it"])
    assert A._board_answer("decide", "Hold: soon", ["Go", "Hold: <note> — pauses it"]) == "Hold: soon"
    # with `form`: the head goes back, and only that form fills
    assert A._board_answer("decide", "Holding it", hold, 1) == "Hold: Holding it"
    assert A._board_answer("decide", "Go", hold, 1) == "Hold: Go"
    two = ["Works", "Not right: <what>", "Hold: <note>"]
    assert A._board_answer("decide", "Not right: x", two, 2) == "Hold: Not right: x"
    assert A._board_answer("decide", "not right: x", two) == "Not right: x"
    for words in ("", "<note>", "Hold:"):
        with pytest.raises(board.Refused, match="Hold needs its words"):
            A._board_answer("decide", words, hold, 1)
    with pytest.raises(board.Refused, match="complete answer"):
        A._board_answer("decide", "x", hold, 0)
    with pytest.raises(board.Refused, match="index of one of"):
        A._board_answer("decide", "x", hold, 5)


@pytest.mark.unit
def test_a_board_lines_head_is_ledgerboards_bold_head():
    """TD-585: the work order's title and the Inbox's head read ledgerboard's `bold_head` — a blank
    bold run is no head, and bold inside a reply's words is the person's, never the head; each
    falls back as it did, and the work order keeps its clipping and its trailing stop."""
    from sessionorc import workorders
    from shiftlead.ui.inbox import board_head

    plain = "[act] 2026-10-14 (session w on kmaster) — Rotate the key. Due: 2026-10-15."
    replied = plain + " — Paul, 2026-10-14: **not yet**"
    assert workorders.head("[act] **Rotate the key.** Due: 2026-10-15.") == "Rotate the key"
    assert workorders.head(plain.replace("Rotate", "** ** Rotate")) == "** ** Rotate the key. Due: 2026-10-15"
    assert workorders.head(replied).startswith("Rotate the key")
    assert board_head("[act] **Rotate  the key** Due: 2026-10-15.") == "Rotate the key"
    assert board_head("** ** x") == "** ** x"
    assert "not yet" not in board_head(replied)


def test_board_reply_hand_is_the_homes_edit():
    """The mail half is the home's (§4.4a, review of PR #1019): a node forwards it, never serves it."""
    from sessionorc import modes

    assert "board_reply_hand" in modes.HOME_EDITS and "board_reply" not in modes.HOME_EDITS
    assert "kmaster (home) is unreachable" in modes.offline_refusal(
        "board_reply_hand", None, {}, host="laptop", home="kmaster"
    )


async def test_a_node_writes_the_board_and_hands_the_mail_to_the_home(agent, repo, tmp_path, monkeypatch):
    """At a node (§4.4a) `board_reply` writes the line where the registry holds the repo and hands
    the mail half to the home as `board_reply_hand`; with the link down it mails nobody and says
    so beside the committed line. Nothing is written to the node's own mailbox."""
    _registry(tmp_path, repo)
    path = str(repo / board.BOARD)
    async with LocalClient() as me:
        h = (
            await me.call(
                "create", name="holder", dir=str(tmp_path), adapter="shell", role="worker", argv=["bash", "--norc"]
            )
        )["id"]
        async with LocalClient(caller=h) as s:
            await s.call("progress", id=h, ref="TD-122")
        with pytest.raises(AgentError, match="a person's own act"):
            async with LocalClient(caller=h) as s:
                await s.call("board_reply_hand", head="x", by="p", reply="y", refs=["TD-122"])
        monkeypatch.setattr(agent, "mode", "node")
        monkeypatch.setattr(agent, "home", "kmaster")
        monkeypatch.setitem(agent.home_link, "up", False)
        got = await agent.rpc_board_reply(board=path, line=7, text=ITEM, reply="rebase it", refs=["TD-122"])
        assert got["sent"] == [] and "mail is the home's: kmaster (home) is unreachable" in got["note"]
        assert origin_item(repo, REF).replies[-1][2] == "rebase it"
        forwarded = []

        async def forward(rid, name, params, caller):
            forwarded.append((name, params, caller))
            return {
                "id": rid,
                "result": {"sent": [{"session": "holder", "id": "h@kmaster", "ref": "TD-122"}], "refused": []},
            }

        monkeypatch.setattr(agent, "_forward", forward)
        monkeypatch.setitem(agent.home_link, "up", True)
        line = origin_item(repo, REF).words  # the item named by its words now (TD-1881)
        got = await agent.rpc_board_reply(board=path, line=7, text=line, reply="and push", refs=["TD-122"])
        assert got["note"] == "written on the board · sent to holder (holds TD-122)"
        assert [(n, p["head"], p["reply"], p["repo"], c) for n, p, c in forwarded] == [
            ("board_reply_hand", "Merged, live check pending: the doorbell.", "and push", repo.name, None)
        ]
        assert not [e for e in agent.sessions[h].inbox if e.from_ == "person"]  # the node's store untouched
        # the trail is the home's too (§4.10): handed over with no refs as well, never written here
        await agent.rpc_board_reply(board=path, line=7, text=line, reply="thanks", refs=[])
        assert forwarded[-1][1]["refs"] == [] and forwarded[-1][1]["repo"] == repo.name
        assert not [t for t in agent.trail if t["kind"] == "board reply"]

        async def broken(rid, name, params, caller):
            return {"id": rid, "error": "link dropped"}

        monkeypatch.setattr(agent, "_forward", broken)  # a failed hand with nobody to mail: nothing to say
        got = await agent.rpc_board_reply(board=path, line=7, text=line, reply="once more", refs=[])
        assert got["note"] == "written on the board"
        monkeypatch.setitem(agent.home_link, "up", False)  # down, and nobody to mail: nothing to say
        got = await agent.rpc_board_reply(board=path, line=7, text=line, reply="again", refs=None)
        assert got["note"] == "written on the board"
        monkeypatch.setattr(agent, "mode", "home")
        await me.call("kill", id=h)


def test_a_merge_that_landed_though_the_forge_said_otherwise_is_a_landed_edit(repo, monkeypatch):
    """Review of PR #1036: `gh pr merge` failing after the forge took the merge (a timeout, a lost
    reply) is read from origin — the edit landed — so the press succeeds and a retried add never
    writes its line twice. The forge's word on the PR is not to be had here (`pr view` fails), so it
    is origin's board that says so."""
    monkeypatch.setenv("FAKE_GH_FAIL", "merge-after")
    monkeypatch.setenv("FAKE_GH_VIEW_FAIL", "1")
    got = board.add(repo, "Once only", "2026-10-02", today="2026-09-25")
    assert got["pr"] == 1 and sum(it.words == "Once only" for it in origin(repo).items) == 1
    board.write_back(repo, 8, ITEM, "done")
    assert origin_item(repo, REF).closed is not None


def test_a_merge_the_forge_took_while_origins_board_moved_elsewhere_is_a_landed_edit(repo, monkeypatch):
    """TD-264 (d): the merge's reply lost **and** origin's board changed elsewhere in the same moment —
    the board differs from the commit's, so only the forge's word on the PR says it landed: a Done
    is not refused as a moved line, and an add is not refused as unreachable (a retry would write
    its line twice)."""
    monkeypatch.setenv("FAKE_GH_FAIL", "merge-after-moved")
    got = board.add(repo, "Once only", "2026-10-02", today="2026-09-25")
    assert got["pr"] == 1 and sum(it.words == "Once only" for it in origin(repo).items) == 1
    assert "A neighbour's edit." in on_origin(repo, "show", f"origin/main:{board.BOARD.as_posix()}")
    board.write_back(repo, 8, ITEM, "done")
    assert origin_item(repo, REF).closed is not None


def test_a_landing_whose_fetch_fails_lands_the_press_and_reports_the_reread_failing(repo, monkeypatch):
    """TD-1515 (§4.4 *Every write the home lands is read at once*): the press merged, and the fetch after it
    failed — the press stands (its line on origin, its PR named), no `commit` is reported, and `reread_error`
    says the re-read failed and why; the tree is reset all the same, so the next press lands."""
    real, merged = board._fetch, []
    real_quiet = board._git_quiet

    def quiet(t, *args):
        if "--delete" in args:  # the branch deleted after the merge: the landing's fetch is next
            merged.append(True)
        return real_quiet(t, *args)

    def fetch(root, at, want, timeout):
        if merged:
            return subprocess.CompletedProcess(["git", "fetch"], 128, "", "fatal: unable to access origin\n")
        return real(root, at, want, timeout)

    monkeypatch.setattr(board, "_git_quiet", quiet)
    monkeypatch.setattr(board, "_fetch", fetch)
    got = board.write_back(repo, 7, ITEM, "done")
    assert got["pr"] == 1 and got["commit"] == ""
    assert got["reread_error"].startswith(board.REREAD_FAILED) and "unable to access origin" in got["reread_error"]
    assert origin_item(repo, REF).closed is not None
    merged.clear()
    monkeypatch.setattr(board, "_fetch", real)
    got = board.write_back(repo, 8, UNDATED, "done")
    assert "reread_error" not in got and got["commit"] == on_origin(repo, "rev-parse", "--short", "origin/main")


async def test_the_home_writes_the_trail_line_a_node_handed_it(agent):
    """`board_reply_hand` with `repo` (a node's Reply, §4.4a): the home writes the trail line in the
    result's words, holder or none — the trail is the home's, beside the person inbox (§4.10)."""
    got = await agent.rpc_board_reply_hand(head="A line.", by="Paul", reply="go on", refs=["TD-999"], repo="cm")
    assert got == {"sent": [], "refused": []}
    t = next(t for t in agent.trail if t["kind"] == "board reply")
    assert (t["name"], t["sid"], t["how"], t["text"]) == ("cm", "", "written on the board", "A line. — Paul: go on")
    await agent.rpc_board_reply_hand(head="B", by="Paul", reply="x", refs=["TD-999"])  # no repo: no line
    assert len([t for t in agent.trail if t["kind"] == "board reply"]) == 1


def _push_elsewhere(repo: Path, other: Path, edit) -> None:
    """Another writer's commit on origin's board, made between the press's fetch and its merge: `edit(clone)`."""
    git(repo, "clone", "-q", git(repo, "remote", "get-url", "origin"), str(other))
    edit(other)
    git(other, "add", "-A")
    git(other, "-c", "user.name=o", "-c", "user.email=o@x", "commit", "-qm", "a neighbour")
    git(other, "push", "-q", "origin", "main")


@pytest.mark.parametrize("press", ["done", "add"])
def test_a_squash_refused_for_a_neighbouring_change_is_made_again_on_origins_new_head(
    repo, monkeypatch, tmp_path, press
):
    """TD-264 (c), §4.4: origin moving in between refuses nothing unless the item itself closed — so a squash the
    forge refuses because the item's own file changed under it (another's reply on it: v3.0 writes one file per
    item, TD-1881) is made once more on origin's new head, and both edits stand. An add writes a file of its own,
    so a neighbour's change never refuses its squash: it lands at once."""
    real, calls = board._land, []

    def reply(other: Path) -> None:
        f = next((other / "docs" / "user_attention").glob(f"*-{REF[-8:]}.md"))
        f.write_text(ledgerboard.edit_item(f.read_text(), "reply", reply="Look again.", by="o", today=date.today()))

    def land(root, t, want, msg, clock, still, **kw):
        calls.append(msg)
        if len(calls) == 1:
            _push_elsewhere(repo, tmp_path / "other", reply)
        return real(root, t, want, msg, clock, still, **kw)

    monkeypatch.setattr(board, "_land", land)
    if press == "done":
        board.write_back(repo, 7, ITEM, "done")
        assert len(calls) == 2 and origin_item(repo, REF).closed is not None
    else:
        board.add(repo, "Next to it", "2026-10-02", today="2026-09-25")
        assert len(calls) == 1 and sum(it.words == "Next to it" for it in origin(repo).items) == 1
    assert origin_item(repo, REF).replies[-1][2] == "Look again."
    assert "board/" not in git(repo, "ls-remote", "--heads", "origin")


def test_the_trees_commit_is_authored_by_the_identity_the_checkout_resolves(repo, monkeypatch, tmp_path):
    """TD-264 (c), §4.4: the commit is the checkout's identity — one an `includeIf "gitdir:…"` gives
    the checkout's path alone, which the tree's own path does not reach, included."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global"))
    inc = tmp_path / "ident.gitconfig"
    inc.write_text("[user]\n\tname = Inc\n\temail = inc@example.com\n")
    git(repo, "config", "--unset", "user.name")
    git(repo, "config", "--unset", "user.email")
    git(repo, "config", "user.useConfigOnly", "true")  # no identity guessed from the host
    git(repo, "config", f"includeIf.gitdir:{repo}/.git.path", str(inc))
    seen = []
    real = board._git

    def spy(root, *args, **kw):
        if "commit" in args:
            seen.append(args)
        return real(root, *args, **kw)

    monkeypatch.setattr(board, "_git", spy)
    board.write_back(repo, 7, ITEM, "done")
    assert origin_item(repo, REF).closed is not None
    assert seen and "user.name=Inc" in seen[0] and "user.email=inc@example.com" in seen[0]


def test_no_second_press_when_the_forge_cannot_say_or_origin_moved_off_the_board(repo, monkeypatch, tmp_path):
    """Review of #1096: the press is made again only on the forge's own word that the PR did not merge
    **and** a change to origin's board. A forge that cannot be asked, with the add landed and the
    board moved after it, is the unreachable refusal and never a second line; a merge refused while
    only another file moved is refused once, with one PR."""
    import json

    monkeypatch.setenv("FAKE_GH_FAIL", "merge-after-moved")
    monkeypatch.setenv("FAKE_GH_VIEW_FAIL", "1")
    with pytest.raises(board.Refused, match="origin could not be reached"):
        board.add(repo, "Once only", "2026-10-02", today="2026-09-25")
    assert sum(it.words == "Once only" for it in origin(repo).items) == 1
    monkeypatch.delenv("FAKE_GH_VIEW_FAIL")
    monkeypatch.setenv("FAKE_GH_FAIL", "merge")
    real, calls = board._land, []

    def land(root, t, want, msg, clock, still, **kw):
        calls.append(msg)
        other = tmp_path / f"other-{len(calls)}"
        git(repo, "clone", "-q", git(repo, "remote", "get-url", "origin"), str(other))
        (other / "other.txt").write_text(f"moved {len(calls)}\n")
        git(other, "-c", "user.name=o", "-c", "user.email=o@x", "commit", "-qam", "elsewhere")
        git(other, "push", "-q", "origin", "main")
        return real(root, t, want, msg, clock, still, **kw)

    monkeypatch.setattr(board, "_land", land)
    with pytest.raises(board.Refused, match="origin could not be reached"):
        board.write_back(repo, 8, UNDATED, "done")
    bare = Path(git(repo, "remote", "get-url", "origin"))
    assert len(calls) == 1 and len(json.loads((bare / "fake-gh.json").read_text())["prs"]) == 2


LEDGER_TITLE = "When should a team start on its own?"


def test_a_ledger_answer_is_one_decided_item_the_reader_reads_as_a_work_order(tmp_path):
    """TD-565 (design §4.5 screen 6 *The ledger's entries that wait on you*): the person's answer to a
    ledger entry is a decided `decide` item — the title, `Context:` the id, due today, the entry's
    answers with its default marked, the words as `Decided:` (ledgerboard v3.0's `decided_file`, TD-1881) — which
    the repo's own reader lists as a work order naming the id; empty words are refused."""
    import shutil

    from sessionorc import workorders

    text = board.decided_file(
        LEDGER_TITLE + ".", "TD-133", ["At the reset", "At 9|10"], 0, "At  the reset", "2026-10-12"
    )
    it = ledgerboard.parse_item(text)
    assert (it.kind, it.words, it.context, it.due, it.session) == (
        "decide",
        LEDGER_TITLE + ".",
        "TD-133",
        date(2026, 10, 12),
        None,
    )
    assert it.answers == ["At the reset", "At 9|10"] and it.default == "At the reset"
    assert it.decided == ("At the reset", date(2026, 10, 12))
    bare = ledgerboard.parse_item(
        board.decided_file(LEDGER_TITLE, "TD-133", [], None, "Not this quarter", "2026-10-12")
    )
    assert bare.answers == [] and bare.decided == ("Not this quarter", date(2026, 10, 12))
    root = tmp_path / "r"
    (root / "docs").mkdir(parents=True)
    (root / "scripts").mkdir()
    shutil.copy2(pinned_script("nudge_user_attention.py"), root / "scripts")
    copy_pinned_ledgerboard(root / "scripts")
    write_board(root, BOARD_TEXT)
    (root / "docs" / "user_attention" / "2026-10-12-0000abcd.md").write_text(text)
    (o,) = workorders.read(root, fetch=False)["orders"]
    assert o["decided"] == {"text": "At the reset", "date": "2026-10-12"} and "TD-133" in o["refs"]
    # a field's name in the title or an answer stays words: each field is a line of its own (review of #1542)
    odd = board.decided_file("Add a Context: field. Due: soon", "TD-9", ["Due: Friday", "No"], 0, "No", "2026-10-12")
    got = ledgerboard.parse_item(odd)
    assert got.context == "TD-9" and got.words == "Add a Context: field. Due: soon" and got.answers[0] == "Due: Friday"
    (root / "docs" / "user_attention" / "2026-10-12-0000abcd.md").write_text(odd)
    (o,) = workorders.read(root, fetch=False)["orders"]
    assert o["refs"] == ["TD-9"] and o["decided"]["text"] == "No"
    for words in ("", "  "):
        with pytest.raises(board.Refused):
            board.decided_file(LEDGER_TITLE, "TD-133", [], None, words, "2026-10-12")


def test_the_third_add_lands_the_decided_item_committed_by_its_id(repo):
    before = load(repo)
    got = board.add_decided(repo, LEDGER_TITLE, "TD-133", ["Yes", "No"], 1, "No", "2026-10-12")
    # ledgerboard's plan_add writes it, naming who answered (v2.3, TD-1330): the checkout's user, as no People: does
    it = origin_item(repo, got["key"])
    assert (it.words, it.context, it.answers, it.default) == (LEDGER_TITLE, "TD-133", ["Yes", "No"], "No")
    assert it.decided == ("No", date(2026, 10, 12)) and it.decided_by == "t" and it.kind == "decide"
    assert got["message"] == f"shiftlead: append {got['id']} When should a team start on its own? (session n/a)"
    assert on_origin(repo, "log", "-1", "--format=%s", "origin/main") == f"{got['message']} (#{got['pr']})"
    assert load(repo) == before  # the checkout is never written


async def test_a_ledger_answer_is_the_persons_and_written_from_the_homes_reading(agent, repo, tmp_path, monkeypatch):
    """`ledger_decide` (§4.5a *Inbox row: ledger entry*, TD-565): an answer by index, Go with it or a
    Reply's words, for an entry the home's repo facts sort *for you*; refused to a session, for an
    entry no longer *for you*, one an open decided line already names, Go with it with no default, an
    index out of range, and a repo the home does not read. The ledger is never written."""
    import shutil

    shutil.copytree(Path(__file__).resolve().parent.parent / "scripts", repo / "scripts", dirs_exist_ok=True)
    root = str(repo)

    async def held() -> None:  # the reading is this test's: the tick reads no registry over it
        return None

    monkeypatch.setattr(agent, "_refresh_repos", held)
    keep_ledger(agent, monkeypatch)  # the ledger reading below is the test's own
    await park_ticks(agent)  # a repos pass already in flight would land after `_repos` below (TD-1050)
    entry = {
        "id": "TD-133", "title": LEDGER_TITLE, "for_page": "for-you", "owner": "grinder",
        "answers": ["At the reset", "At a fixed time"], "default": 0,
    }  # fmt: skip
    agent._repos = {
        root: {
            "name": "repo", "root": root,
            "ledger": {"entries": [entry, {"id": "TD-134", "title": "x", "for_page": "for-you", "answers": []},
                                   {"id": "TD-10", "title": "y", "for_page": "pickable"}]},
            "work_orders": {"orders": []},
        }
    }  # fmt: skip
    async with LocalClient() as me:
        w = (
            await me.call(
                "create", name="w", dir=str(tmp_path), adapter="shell", role="worker", argv=["bash", "--norc"]
            )
        )["id"]
        async with LocalClient(caller=w) as worker:
            with pytest.raises(AgentError, match="a person's own act"):
                await worker.call("ledger_decide", repo=root, id="TD-133", go=True)
        for kw, why in (
            ({"repo": root, "id": "TD-10", "go": True}, "no longer waits on you"),
            ({"repo": str(tmp_path / "nope"), "id": "TD-133", "go": True}, "not a repo this home reads"),
            ({"repo": root, "id": "TD-134", "go": True}, "marks no answer"),
            ({"repo": root, "id": "TD-133", "answer": 2}, "has no answer 2"),
            ({"repo": root, "id": "TD-133", "words": "  "}, "needs its words"),
        ):
            with pytest.raises(AgentError, match=why):
                await me.call("ledger_decide", **kw)
        # two presses at once (two tabs): one line, the other refused (review of #1542)
        async with LocalClient() as tab:
            both = await asyncio.gather(
                me.call("ledger_decide", repo=root, id="TD-133", go=True),
                tab.call("ledger_decide", repo=root, id="TD-133", go=True),
                return_exceptions=True,
            )
        refused = [x for x in both if isinstance(x, AgentError)]
        assert len(refused) == 1 and "already" in str(refused[0])
        got = next(x for x in both if isinstance(x, dict))
        assert sum(it.context == "TD-133" for it in origin(repo).items) == 1
        assert (
            got["decided"] == "At the reset"
            and got["message"] == f"shiftlead: append {got['id']} When should a team start on its own? (session n/a)"
        )
        it = origin_item(repo, got["key"])
        assert it.kind == "decide" and it.session is None and it.words == "When should a team start on its own?"
        assert it.context == "TD-133" and it.decided[0] == "At the reset" and it.decided_by == "t"
        # the home read the board again: the line is a work order naming the id, and a second press is refused
        orders = agent._repos[root]["work_orders"]["orders"]
        assert [o["decided"]["text"] for o in orders] == ["At the reset"] and "TD-133" in orders[0]["refs"]
        with pytest.raises(AgentError, match="already decided"):
            await me.call("ledger_decide", repo=root, id="TD-133", answer=1)
        got = await me.call("ledger_decide", repo=root, id="TD-134", words="Drop it — the cost is not worth it")
        assert origin_item(repo, got["key"]).decided[0] == "Drop it — the cost is not worth it"
        await me.call("kill", id=w)


async def test_a_ledger_entrys_form_is_filled_never_pressed(agent, repo, tmp_path, monkeypatch):
    """TD-1698 (§4.4 *A form's press is the decide*): on a ledger entry, an answer index naming a form is
    refused, and so are words that are the form unfilled; `form` with words puts its head back. A form marked
    the default is no default (`ledger.answers_of`), so Go with it meets *marks no answer*."""
    import shutil

    from sessionorc import ledger as ledger_mod

    labels, _cons, default, heads = ledger_mod.answers_of("Go | Hold: <note> (default)")
    assert labels == ["Go", "Hold: <note>"] and default is None and heads == ["", "Hold"]
    assert ledger_mod.answers_of("Go (default) | Hold: <note>")[2] == 0
    shutil.copytree(Path(__file__).resolve().parent.parent / "scripts", repo / "scripts", dirs_exist_ok=True)
    root = str(repo)

    async def held() -> None:
        return None

    monkeypatch.setattr(agent, "_refresh_repos", held)
    keep_ledger(agent, monkeypatch)
    await park_ticks(agent)
    entry = {"id": "TD-133", "title": LEDGER_TITLE, "for_page": "for-you", "answers": ["Go", "Hold: <note>"]}
    agent._repos = {root: {"name": "repo", "root": root, "ledger": {"entries": [entry]}, "work_orders": {"orders": []}}}
    async with LocalClient() as me:
        for kw in ({"answer": 1}, {"words": "Hold: <note>"}, {"words": "hold:"}, {"form": 1, "words": ""}):
            with pytest.raises(AgentError, match="Hold needs its words"):
                await me.call("ledger_decide", repo=root, id="TD-133", **kw)
        with pytest.raises(AgentError, match="marks no answer"):
            await me.call("ledger_decide", repo=root, id="TD-133", go=True)
        got = await me.call("ledger_decide", repo=root, id="TD-133", form=1, words="Holding it")
        assert got["decided"] == "Hold: Holding it"
        it = origin_item(repo, got["key"])
        assert (it.decided[0], it.decided_by) == ("Hold: Holding it", "t")


async def test_done_and_back_to_design_tell_the_holder_clear_the_hold_then_write_the_line(
    agent, repo, tmp_path, monkeypatch
):
    """TD-905 (§4.5 screen 12 *any open row*, §4.4 *The tell*): `ledger_decide` with `road` — Done… on a row
    that is not *yours to do*, Back to design… on a pickable, live check or id-blocked one — tells the
    entry's unattended holder first, then writes *done — <words>* or *back to design — <words>* as one
    decided line; refused, writing nothing, where a holder could not be told. The clock records no hold
    for it to clear (TD-1297)."""
    import shutil
    from datetime import UTC, datetime

    from sessionorc import settle
    from sessionorc.agent_common import RpcError
    from sessionorc.models import PERSON, ProgressEntry, Session

    shutil.copytree(Path(__file__).resolve().parent.parent / "scripts", repo / "scripts", dirs_exist_ok=True)
    root = str(repo)

    async def held() -> None:
        return None

    monkeypatch.setattr(agent, "_refresh_repos", held)
    keep_ledger(agent, monkeypatch)  # the ledger reading below is the test's own
    # a repos pass the fixture's first tick started before the patch lands after `_repos` is set below and
    # empties it (*…/repo is not a repo this home reads*, under a loaded run): finished first (TD-1050)
    await park_ticks(agent)
    entries = [
        {"id": "TD-20", "title": "a build", "for_page": "pickable"},
        {"id": "TD-21", "title": "a design", "for_page": "design"},
        {"id": "TD-22", "title": "mine", "for_page": "for-you", "owner": "paul"},
        {"id": "TD-23", "title": "after a sibling", "for_page": "blocked", "blocked_by": ["TD-20"]},
        {"id": "TD-24", "title": "another build", "for_page": "pickable"},
        {"id": "TD-25", "title": "after an archived one", "for_page": "blocked", "blocked_by": ["TD-9"]},
        {"id": "TD-26", "title": "a parent", "for_page": "blocked", "parts_open": ["TD-20"]},  # TD-1130
    ]
    settle.observe(entries, "o/r", {}, datetime.now(UTC))  # the repo's first reading: every id settled
    agent._repos = {
        root: {"name": "repo", "root": root, "remote": "https://github.com/o/r.git",
               "ledger": {"entries": entries}, "work_orders": {"orders": []}}
    }  # fmt: skip
    w = Session(id="ao-gw", name="gw", kind="agent", adapter="claude-code", dir="", unattended=True)
    w.progress.append(ProgressEntry(ref="TD-20"))
    agent.sessions["ao-gw"] = w
    async with LocalClient() as me:
        for kw, why in (
            ({"id": "TD-22", "road": "done"}, "TD-22 is yours to do"),
            ({"id": "TD-21", "road": "design"}, "TD-21 is design: Back to design is on a pickable"),
            ({"id": "TD-25", "road": "design"}, "TD-25 is blocked: Back to design is on a pickable"),
            ({"id": "TD-99", "road": "done"}, "TD-99 is not an open entry"),
            ({"id": "TD-20", "road": "close"}, "a ledger row's road is done or design, not 'close'"),
        ):
            with pytest.raises(AgentError, match=why):
                await me.call("ledger_decide", repo=root, words="x", **kw)

        async def refuse(*a, **k):
            raise RpcError("gw's inbox is full")

        real = agent._msg
        monkeypatch.setattr(agent, "_msg", refuse)
        with pytest.raises(AgentError, match="nothing was written: could not tell ao-gw: gw's inbox is full"):
            await me.call("ledger_decide", repo=root, id="TD-20", road="design", words="split it")
        assert not [it for it in origin(repo).items if it.context == "TD-20"]
        monkeypatch.setattr(agent, "_msg", real)
        # retired (TD-1881): words carrying a field's name (`see Context: TD-1`) refused before anyone is told — an
        # item file writes each field on a line of its own, so v3.0 refuses no field's name in words
        assert not [e for e in w.inbox if e.about == "TD-20"], "nobody was told"
        got = await me.call("ledger_decide", repo=root, id="TD-20", road="design", words=" split  it ")
        assert got["decided"] == "back to design — split it" and got["told"] == ["ao-gw"]
        it = origin_item(repo, got["key"])
        assert it.context == "TD-20" and it.due is not None and it.decided[0] == "back to design — split it"
        notes = [e.text for e in w.inbox if e.from_ == PERSON and e.about == "TD-20"]
        assert notes and notes[0].startswith("TD-20 goes back to design — split it: stop at the step in hand")
        got = await me.call("ledger_decide", repo=root, id="TD-24", road="done")
        assert got["decided"] == "done" and got["told"] == []
        assert "held" not in json.dumps(settle._load()), "the clock records no hold"
        got = await me.call("ledger_decide", repo=root, id="TD-23", road="design", words="w")
        assert got["decided"] == "back to design — w"
        with pytest.raises(AgentError, match="already decided"):
            await me.call("ledger_decide", repo=root, id="TD-23", road="done")


async def test_a_ledger_answer_finds_its_repo_by_path_and_the_reading_after_it_lands(
    agent, repo, tmp_path, monkeypatch
):
    """`ledger_decide` (TD-576, the test audit of #1542): the repo named by a symlink to its checkout is
    the registry's; an open decided line naming `Repo#id` decides it already; `answer=True` is no
    index; the re-read after the line lands saves the registry and broadcasts one `repos` event, and a
    read that fails — an `error` or a raise — leaves the work orders alone and the press landed."""
    import shutil

    from sessionorc import workorders

    shutil.copytree(Path(__file__).resolve().parent.parent / "scripts", repo / "scripts", dirs_exist_ok=True)
    root = str(repo)

    async def held() -> None:
        return None

    monkeypatch.setattr(agent, "_refresh_repos", held)
    keep_ledger(agent, monkeypatch)  # the ledger reading below is the test's own
    await park_ticks(agent)  # a repos pass already in flight would land after `_repos` below (TD-1050)
    real_read = workorders.read_boards
    events: list[dict] = []
    real_broadcast = agent._broadcast

    async def broadcast(ev: dict) -> None:
        if ev.get("event") == "repos":  # the tick's own `queue` pushes are not the re-read's (TD-769)
            events.append(ev)
        await real_broadcast(ev)

    monkeypatch.setattr(agent, "_broadcast", broadcast)

    def entry(id: str) -> dict:
        return {"id": id, "title": f"Entry {id}", "for_page": "for-you", "answers": ["Yes", "No"], "default": 0}

    stale = {"orders": [{"refs": ["repo#TD-7"], "decided": {"text": "Yes", "date": "2026-10-01"}}]}
    agent._repos = {
        root: {
            "name": "repo", "root": root,
            "ledger": {"entries": [entry("TD-7"), entry("TD-8"), entry("TD-9"), entry("TD-10")]},
            "work_orders": stale,
            # the line itself, which `ledger_decide`'s check reads (covers, TD-1368)
            "boards": {"boards": [{"items": [
                {"kind": "decide", "refs": ["repo#TD-7"], "decided": stale["orders"][0]["decided"]}
            ]}]},
        }
    }  # fmt: skip
    link = tmp_path / "link"
    link.symlink_to(repo)
    async with LocalClient() as me:
        with pytest.raises(AgentError, match="TD-7 is already decided on repo's board"):
            await me.call("ledger_decide", repo=root, id="TD-7", go=True)
        with pytest.raises(AgentError, match="has no answer True"):
            await me.call("ledger_decide", repo=root, id="TD-8", answer=True)
        # a failed re-read: the line lands, the press answers, the reading is the one before it
        for failing in ({"error": "boom"}, RuntimeError("boom")):

            def read(_root, failing=failing, **_):
                if isinstance(failing, Exception):
                    raise failing
                return failing

            monkeypatch.setattr(workorders, "read_boards", read)
            id = "TD-8" if isinstance(failing, dict) else "TD-9"
            got = await me.call("ledger_decide", repo=str(link), id=id, go=True)
            assert got["repo"] == root and origin_item(repo, got["key"]).context == id
            assert agent._repos[root]["work_orders"] is stale
            # the press mark's own pushes alone (TD-1508): the reading in them is the one before the line
            assert events and all(e["repo"]["work_orders"] == stale for e in events)
            last = events[-1]["repo"]
            assert not any(e.get("applying") for e in last["ledger"]["entries"]), "the last push carries no mark"
            events.clear()
        monkeypatch.setattr(workorders, "read_boards", real_read)
        got = await me.call("ledger_decide", repo=str(link), id="TD-10", answer=1)
        assert got["repo"] == root and got["decided"] == "No"
        saved = agent.repos_store.load()[root]["work_orders"]["orders"]
        assert {r for o in saved for r in o["refs"]} >= {"TD-8", "TD-9", "TD-10"}
        landed = [e for e in events if e.get("event") == "repos" and e["repo"]["work_orders"] != stale]
        assert landed and all(e["root"] == root for e in landed)
        assert landed[-1]["repo"]["work_orders"]["orders"] == saved


def test_ledger_decide_is_the_homes_edit():
    """A node holds no repo facts (§4.4a, TD-565): `ledger_decide` waits for the link by the
    home-edits rule, never served at a node as *not a repo this home reads* (TD-576)."""
    from sessionorc import mail, modes

    assert "ledger_decide" in modes.HOME_EDITS and "ledger_decide" in mail.PERSON_ONLY
    assert "ledger_decide edits what the home owns" in modes.offline_refusal(
        "ledger_decide", None, {}, host="laptop", home="kmaster"
    )


@pytest.fixture
def keyed(tmp_path, forge) -> Path:
    """The `repo` fixture's board with the repo's own reader beside it, which a line's id needs."""
    root = tmp_path / "keyed"
    (root / "docs").mkdir(parents=True)
    (root / "scripts").mkdir()
    reader = pinned_script("nudge_user_attention.py")
    (root / "scripts" / "nudge_user_attention.py").write_text(reader.read_text())
    # the reader imports its sibling: without it, it loads only where an earlier test left one importable
    copy_pinned_ledgerboard(root / "scripts")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    write_board(root, BOARD_TEXT)
    served(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    forge(root)
    return root


def test_a_press_with_the_items_id_finds_it_moved_and_snoozed_and_a_stale_id_is_refused(keyed):
    """§4.4 *A board line's id* (TD-603, TD-607): with `key`, the write-back finds the open item whose id ends with
    it (ledgerboard v3.0, TD-1881) whatever the page sent — its `Due:` moved since the page drew it — and edits the
    item as it is now; an id no open item holds is refused in its words, nothing landed."""
    key = REF
    moved = ITEM.replace("2026-09-22", "2026-09-30")
    push_board(keyed, BOARD_TEXT.replace(f"- [ ] {ITEM}", f"- [ ] 2026-09-19 (n/a) — new.\n- [ ] {moved}"), "moved")
    assert ref_of(moved) == key  # a snooze never changes the id
    got = board.write_back(keyed, 7, ITEM, "reply", reply="still on it", key=key)  # the page's stale line and text
    assert got["key"] == key and got["text"] == item(keyed, key).words
    it = origin_item(keyed, key)
    assert it.due == date(2026, 9, 30) and it.replies[-1][2] == "still on it"
    before = on_origin(keyed, "rev-parse", "origin/main")
    with pytest.raises(board.Refused, match="no line board:00000000 on the board — reworded or closed"):
        board.write_back(keyed, None, "", "done", key="board:00000000")
    with pytest.raises(board.Refused, match="not a board line's id"):
        board.write_back(keyed, None, "", "done", key="TD-607")
    board.write_back(keyed, None, "", "done", key=key)  # by its id alone
    with pytest.raises(board.Refused, match=f"{key} was closed"):
        board.write_back(keyed, None, "", "done", key=key)  # closed: no open item holds it, the closed one says so
    assert on_origin(keyed, "rev-parse", "origin/main") != before


async def test_board_edit_and_board_reply_find_the_item_by_its_id_alone(agent, keyed, tmp_path):
    """§4.4 *A board line's id* (TD-607): the RPCs take `key` in place of the item's words — the reply's head is
    the found item's — and refuse an id no open item holds in its words."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{keyed}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    path = str(keyed / board.BOARD)
    key = REF
    async with LocalClient() as me:
        got = await me.call("board_reply", board=path, reply="on it", key=key)
        assert got["key"] == key and "the doorbell" in got["message"]
        got = await me.call("board_edit", board=path, action="snooze", due="2026-10-01", key=key)
        assert got["key"] == key and got["action"] == "snooze"
        with pytest.raises(AgentError, match="no line board:00000000 on the board — reworded or closed"):
            await me.call("board_edit", board=path, action="done", key="board:00000000")
        with pytest.raises(AgentError, match="names the item's line or its id"):
            await me.call("board_edit", board=path, action="done")
    it = origin_item(keyed, key)
    assert it.replies[-1][2] == "on it" and it.hide_until == date(2026, 10, 1)


def test_of_two_open_items_sharing_a_reference_the_one_shown_word_for_word_is_found():
    """Review of #1606: two open items share a reference only when their ids' eight hex digits do (two days'
    items, TD-1881). With the reference, the item whose words are the ones the person was shown is found before
    the first; with words neither holds, the first."""
    a = ledgerboard.BoardItem(due=None, id="2026-09-20-abcd1234", words="first")
    b = ledgerboard.BoardItem(due=None, id="2026-09-21-abcd1234", words="second")
    bd = ledgerboard.Board(form="dir", path="docs/user_attention.md", major=3, items=[a, b])
    assert board._find(bd, "board:abcd1234", "second") is b
    assert board._find(bd, "board:abcd1234", "first") is a
    assert board._find(bd, "board:abcd1234", "") is a
    assert board._find(bd, "board:00000000", "second") is b  # a stale key falls back to the words


async def test_a_persons_session_presses_done_and_back_to_design_but_answers_no_decision(
    agent, repo, tmp_path, monkeypatch
):
    """TD-1127 (§4.8 *A person's session passes one of them*): a session the person started by hand presses
    **Done…** and **Back to design…** — the commit names it, the holder's note names it once — and is
    refused Done on an entry that waits on the person's decision, which the person's shell closes as the
    person, *n/a* in the commit and *the person* in the note."""
    import shutil
    from datetime import UTC, datetime

    from sessionorc import settle
    from sessionorc.agent_common import RpcError
    from sessionorc.models import PERSON, ProgressEntry, Session

    shutil.copytree(Path(__file__).resolve().parent.parent / "scripts", repo / "scripts", dirs_exist_ok=True)
    root = str(repo)

    async def held() -> None:
        return None

    monkeypatch.setattr(agent, "_refresh_repos", held)
    keep_ledger(agent, monkeypatch)  # the ledger reading below is the test's own
    await park_ticks(agent)
    entries = [
        {"id": "TD-30", "title": "a build", "for_page": "pickable"},
        {"id": "TD-31", "title": "the person's call", "for_page": "for-you", "blocked_by": ["decision (paul)"]},
        {"id": "TD-32", "title": "a third build", "for_page": "pickable"},
        {"id": "TD-33", "title": "another build", "for_page": "pickable"},
    ]
    settle.observe(entries, "o/r", {}, datetime.now(UTC))
    agent._repos = {
        root: {"name": "repo", "root": root, "remote": "https://github.com/o/r.git",
               "ledger": {"entries": entries}, "work_orders": {"orders": []}}
    }  # fmt: skip
    agent.sessions["ao-me"] = Session(id="ao-me", name="me", kind="interactive", adapter="claude-code", dir="")
    agent.sessions["ao-sh"] = Session(id="ao-sh", name="sh", kind="interactive", adapter="shell", dir="")
    w = Session(id="ao-gw", name="gw", kind="agent", adapter="claude-code", dir="", unattended=True)
    w.progress += [ProgressEntry(ref=t) for t in ("TD-30", "TD-31", "TD-32")]
    agent.sessions["ao-gw"] = w

    def notes(tid: str) -> list[str]:
        return [e.text for e in w.inbox if e.from_ == PERSON and e.about == tid]

    got = await agent.rpc_ledger_decide(repo=root, id="TD-30", road="done", words="built", caller="ao-me")
    assert got["decided"] == "done — built" and got["told"] == ["ao-gw"] and got["readers"] == []
    assert got["message"] == f"shiftlead: append {got['id']} a build (session me)"
    assert notes("TD-30") == [
        "TD-30 is closed by the person's session me — built: stop at the step in hand, push, leave its PR open and "
        'unmerged, and drop the entry: `ao progress drop TD-30 --why "closed by the person\'s session me — built"`.'
    ]
    with pytest.raises(RpcError, match="TD-31 waits on the person's decision"):
        await agent.rpc_ledger_decide(repo=root, id="TD-31", road="done", caller="ao-me")
    assert not [it for it in origin(repo).items if it.context == "TD-31"]
    with pytest.raises(RpcError, match="ao-me cannot answer a ledger entry"):
        await agent.rpc_ledger_decide(repo=root, id="TD-31", words="yes", caller="ao-me")
    got = await agent.rpc_ledger_decide(repo=root, id="TD-31", road="done", caller="ao-sh")
    assert got["message"].endswith("(session n/a)"), "the person's shell is the person"
    assert notes("TD-31")[0].startswith("TD-31 is closed by the person: stop"), notes("TD-31")
    got = await agent.rpc_ledger_decide(repo=root, id="TD-32", road="done", caller="ao-me")
    assert notes("TD-32")[0].startswith("TD-32 is closed by the person's session me: stop"), notes("TD-32")
    got = await agent.rpc_ledger_decide(repo=root, id="TD-33", road="design", words="split it", caller="ao-me")
    assert got["decided"] == "back to design — split it" and got["message"].endswith("(session me)")
    # a person's session on a node, by its id in the home's graph
    agent.remote = {
        "laptop": {"ao-me": Session(id="ao-me", name="lap", kind="interactive", adapter="claude-code", dir="")}
    }
    # the reading the home stores: a press's re-read marks a copy (§4.4 *An entry no lane takes is marked*)
    stored = agent._repos[root]["ledger"]["entries"]
    stored.append({"id": "TD-36", "title": "on a node", "for_page": "pickable"})
    settle.observe(stored, "o/r", {}, datetime.now(UTC))
    got = await agent.rpc_ledger_decide(repo=root, id="TD-36", road="done", caller="ao-me@laptop")
    assert got["message"].endswith("(session lap)")


def test_the_inbox_reads_needs_you_so_a_hidden_item_is_the_snoozed_folds_alone(tmp_path):
    """TD-1330 (ledgerboard v2.3): a Snooze writes `Hide until:`; `board_items` carries each item's
    `needs_you` class as `needs`, None while hidden, and the Inbox's `board_rows` keeps it as a `hidden`
    row (TD-1349), which `board_horizon` puts under `snoozed` alone — until the date, when it is back
    with its Due: as it was. Read from the v3 board the snooze leaves (`load_board()`, TD-1881)."""
    from sessionorc import workorders
    from shiftlead.ui.inbox import board_horizon, board_rows

    it = _items(tmp_path)[REF]
    hidden = board.edit_item(it, "snooze", "2026-10-01")
    (tmp_path / "docs" / "user_attention" / it.path).write_text(hidden)

    def snoozed_first(xs: list[dict]) -> list[dict]:  # the snoozed item, then the undated one, whatever the order
        return sorted(xs, key=lambda x: "doorbell" not in str(x.get("text")))

    for today, shown in ((date(2026, 9, 25), 1), (date(2026, 10, 1), 2)):
        items = snoozed_first(workorders.board_items(load(tmp_path), today))
        assert [i["needs"] is None for i in items] == [shown == 1, False]
        report = {"today": today.isoformat(), "boards": [{"root": "/r", "board": "/r/b.md", "items": items}]}
        rows = snoozed_first(board_rows(report))
        assert [r["hidden"] for r in rows] == [shown == 1, False]
        assert rows[0]["hide_until"] == ("2026-10-01" if shown == 1 else "")
        hz = board_horizon(rows, "all")
        drawn = hz["due"] + hz["ahead"] + hz["hidden"] + hz["waiting"]
        assert len(drawn) == shown and any(str(d["text"]).startswith("undated") for d in drawn)
        assert len(hz["snoozed"]) == 2 - shown
    got = ledgerboard.parse_item(hidden)
    assert got.due == date(2026, 9, 22) and got.hide_until == date(2026, 10, 1)  # its deadline stands


GATED = (
    "decide 2026-11-05 (session `grinder-ao-2` on kmaster) — **Go on TD-190?** Say. Context: TD-190 decision (paul). "
    "Due: 2026-11-06. Answers: Go | Not yet."
)
GATED_ENTRY = """## TD-190: A window to keep

**Priority:** Low
**Added:** 2026-11-01
**Owner:** paul
**Status:** Open
**Blocked by:** decision (paul)

**Ask:** Go on TD-190?

**Why:** a test's.
"""


def _gated(repo: Path) -> None:
    """A v2 ledger with one entry gated on the person, and the board's decide item that covers it, on origin."""
    (repo / "docs" / "ledger").mkdir()
    (repo / "docs" / "ledger" / "README.md").write_text("# Ledger\n\nLedgerboard: 2\n")
    (repo / "docs" / "ledger" / "TD-190.md").write_text(GATED_ENTRY)
    write_board(repo, BOARD_TEXT.replace("## Needs", "People: paul\n\n## Needs") + f"- [ ] {GATED}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "gated")
    git(repo, "push", "-q", "origin", "main")


def test_a_go_on_a_gated_decide_lifts_the_gate_in_the_same_write(repo):
    """TD-1375 (design §4.4 *Board write-back*): a lifting answer on a decide item whose Context names one entry
    and one gate is ledgerboard v2.4's decide lift — the board line closed and the entry's gate lifted, its Log
    dated the UTC day, landed as one commit; the checkout is never written."""
    _gated(repo)
    at = None  # a v3 board has no lines: found by its text (TD-1881)
    got = board.write_back(repo, at, GATED, "decide", answer="Go")
    assert got["entries"] == ["TD-190"]
    assert git(repo, "status", "--porcelain") == ""
    month = date.today().isoformat()[:7]
    assert board_files(repo) == {
        "docs/ledger/TD-190.md",
        f"docs/user_attention/{got['id']}.md",
        f"docs/user_attention/archive/{month}/{got['id']}.md",
    }
    entry = on_origin(repo, "show", "origin/main:docs/ledger/TD-190.md")
    assert "**Blocked by:**" not in entry
    day = datetime.now(UTC).date().isoformat()
    assert f"- {day}: gate lifted: decision (paul)" in entry
    it = origin_item(repo, ref_of(GATED))
    assert it.closed is not None and it.decided[0] == "Go"  # the lift closes the item (ledgerboard's closes())


def test_a_not_yet_on_a_gated_decide_keeps_it_waiting_in_the_same_write(repo):
    """A waiting-only answer logs *kept waiting* on the entry, which keeps its gate, and closes the item."""
    _gated(repo)
    at = None  # a v3 board has no lines: found by its text (TD-1881)
    got = board.write_back(repo, at, GATED, "decide", answer="Not yet")
    assert got["entries"] == ["TD-190"]
    month = date.today().isoformat()[:7]
    assert board_files(repo) == {
        "docs/ledger/TD-190.md",
        f"docs/user_attention/{got['id']}.md",
        f"docs/user_attention/archive/{month}/{got['id']}.md",
    }
    entry = on_origin(repo, "show", "origin/main:docs/ledger/TD-190.md")
    assert "**Blocked by:** decision (paul)" in entry and "kept waiting: decision (paul)" in entry
    it = origin_item(repo, ref_of(GATED))
    assert it.closed is not None and it.decided[0] == "Not yet" and "kept waiting" in (it.closed[1] or "")


async def test_a_go_lifts_the_entrys_card_at_once_and_it_stays_lifted_on_the_stale_checkout(
    agent, repo, tmp_path, monkeypatch
):
    """TD-1471 (§4.4 *The ledger is read against origin, as the board is*; TD-1433's outcome): after a Go on a
    gated decide item the write-back re-reads the whole ledger against origin, whose ref its landing moved, so the
    reading pushed right after the press has the gate gone and no *for you* row (no **Lift the hold**) while the
    checkout's ledger still holds the gate; a tick's later read of the stale checkout reads origin's file too, with
    no hold of its own, and after the pull the checkout's."""
    from sessionorc import reports
    from shiftlead.ui.inbox import ledger_for_you

    _gated(repo)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    await park_ticks(agent)
    monkeypatch.setattr(reports, "pr_reading", lambda d, now, **kw: {"open": [], "at": now.isoformat()})
    root = str(repo)
    pushed: list[dict] = []
    real_broadcast = agent._broadcast

    async def broadcast(ev: dict) -> None:
        if ev.get("event") == "repos":
            pushed.append(ev)
        await real_broadcast(ev)

    monkeypatch.setattr(agent, "_broadcast", broadcast)

    async def tick() -> dict:
        agent._repos_read_at = float("-inf")
        await agent._refresh_repos()
        return next(e for e in agent._repos[root]["ledger"]["entries"] if e["id"] == "TD-190")

    assert (await tick())["for_page"] == "for-you"
    pushed.clear()
    at = None  # a v3 board has no lines: found by its text (TD-1881)
    async with LocalClient() as me:
        got = await me.call(
            "board_edit", board=str(repo / board.BOARD), line=at, text=GATED, action="decide", answer="Go",
            answers=["Go", "Not yet"],
        )  # fmt: skip
    assert got["action"] == "decide"
    assert "decision (paul)" in (repo / "docs" / "ledger" / "TD-190.md").read_text(), "the checkout has not pulled"

    def lifted(e: dict) -> bool:
        return e["for_page"] != "for-you" and not any("decision" in str(b) for b in e.get("blocked_by") or ())

    (ev,) = pushed  # the press's own `repos` push, with no fetch cadence waited
    assert lifted(next(e for e in ev["repo"]["ledger"]["entries"] if e["id"] == "TD-190"))
    assert ev["repo"]["ledger"]["origin"]["source"] == "origin"
    assert not [r for g in ledger_for_you(agent._repos, [])["groups"] for r in g["rows"] if r.get("id") == "TD-190"]
    assert lifted(await tick()), "a tick's read of the stale checkout reads origin's file"
    assert not hasattr(agent, "_ledger_pressed")
    git(repo, "pull", "-q", "--ff-only", "origin", "main")
    assert lifted(await tick()) and agent._repos[root]["ledger"]["origin"]["source"] == "checkout"


async def test_a_pass_begun_before_a_go_lands_after_its_reread_keeps_the_lift(agent, repo, tmp_path, monkeypatch):
    """TD-1471: a tick's pass that began before a press, whose ledger read took origin from before the landing,
    lands after the press's re-read: the pass keeps the re-read's ledger as it keeps its board (`_boards_pressed`),
    so the stale read never lands over it, and the archive it read with stands too."""
    import asyncio

    _gated(repo)
    tick = await _press_go_meanwhile(agent, repo, tmp_path, monkeypatch)
    root = str(repo)
    e = next(e for e in agent._repos[root]["ledger"]["entries"] if e["id"] == "TD-190")
    assert _lifted(e), "the pass's stale read did not land over the press's re-read"
    assert await asyncio.wait_for(tick(), 60) and _lifted((await tick())["TD-190"])


async def _press_go_meanwhile(agent, repo: Path, tmp_path: Path, monkeypatch):
    """Register `repo`, read it once, then run a due pass whose read is taken before a Go lands and returned after
    the press's re-read; returns the tick."""
    import asyncio

    from sessionorc import reports

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    await park_ticks(agent)
    monkeypatch.setattr(reports, "pr_reading", lambda d, now, **kw: {"open": [], "at": now.isoformat()})
    root = str(repo)

    async def tick() -> dict[str, dict]:
        agent._repos_read_at = float("-inf")
        await agent._refresh_repos()
        return {e["id"]: e for e in agent._repos[root]["ledger"]["entries"]}

    assert (await tick())["TD-190"]["for_page"] == "for-you"
    real = agent._read_repos
    loop = asyncio.get_running_loop()

    def press_meanwhile(*args):
        got = real(*args)  # read before the press: the gate stands on origin still
        at = None  # a v3 board has no lines: found by its text (TD-1881)
        board.write_back(repo, at, GATED, "decide", answer="Go")
        asyncio.run_coroutine_threadsafe(agent._reread_board(root), loop).result(60)
        return got

    monkeypatch.setattr(agent, "_read_repos", press_meanwhile)
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()
    monkeypatch.setattr(agent, "_read_repos", real)
    return tick


async def _press_go(agent, repo: Path, tmp_path: Path, monkeypatch, text: str):
    """Register `repo` on a scratch home, read it once, press Go on the board's `text` item; returns the tick."""
    from sessionorc import reports

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    await park_ticks(agent)
    monkeypatch.setattr(reports, "pr_reading", lambda d, now, **kw: {"open": [], "at": now.isoformat()})

    async def tick() -> dict[str, dict]:
        agent._repos_read_at = float("-inf")
        await agent._refresh_repos()
        return {e["id"]: e for e in agent._repos[str(repo)]["ledger"]["entries"]}

    await tick()
    at = None  # a v3 board has no lines: found by its text (TD-1881)
    async with LocalClient() as me:
        got = await me.call(
            "board_edit", board=str(repo / board.BOARD), line=at, text=text, action="decide", answer="Go",
            answers=["Go", "Not yet"],
        )  # fmt: skip
    assert got["action"] == "decide"
    return tick


def _lifted(e: dict) -> bool:
    return e["for_page"] != "for-you" and not any("decision" in str(b) for b in e.get("blocked_by") or ())


async def test_a_narrowed_fetch_still_moves_origins_ref_and_the_lift_reads_at_once(agent, repo, tmp_path, monkeypatch):
    """TD-1471: every fetch the compare relies on uses the explicit refspec, so a repo whose `remote.origin.fetch`
    is narrowed to another branch still moves `origin/main` at a press's landing, and the lift reads at once."""
    _gated(repo)
    # a bare `git fetch origin` moves another ref than `origin/main`
    git(repo, "config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/elsewhere")
    before = git(repo, "rev-parse", "refs/remotes/origin/main")
    tick = await _press_go(agent, repo, tmp_path, monkeypatch, GATED)
    root = str(repo)
    assert git(repo, "rev-parse", "refs/remotes/origin/main") != before, "the landing moved the ref"
    assert _lifted(next(e for e in agent._repos[root]["ledger"]["entries"] if e["id"] == "TD-190"))
    assert _lifted((await tick())["TD-190"])


async def test_a_reread_resolves_and_settles_as_the_ticks_reading_does(agent, repo, tmp_path, monkeypatch):
    """TD-1471: a press's re-read is the pass's own ledger step: entries still carry `pickable`, `live`, `waiting`
    and `settling` as the tick's reading gives them, and an entry new on origin, first seen by the re-read (after a
    first settled reading of the repo), is settling, not pickable."""
    from sessionorc import reports

    _gated(repo)
    later = (datetime.now(UTC).date().replace(year=datetime.now(UTC).year + 1)).isoformat()
    (repo / "docs" / "ledger" / "TD-195.md").write_text(
        GATED_ENTRY.replace("TD-190: A window to keep", "TD-195: Waits for a day").replace(
            "**Blocked by:** decision (paul)", f"**Blocked by:** until {later}"
        )
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a waiting one")
    git(repo, "push", "-q", "origin", "main")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    await park_ticks(agent)
    monkeypatch.setattr(reports, "pr_reading", lambda d, now, **kw: {"open": [], "at": now.isoformat()})
    root = str(repo)
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()
    tick = {e["id"]: e for e in agent._repos[root]["ledger"]["entries"]}
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", git(repo, "remote", "get-url", "origin"), str(other))
    (other / "docs" / "ledger" / "TD-196.md").write_text(
        GATED_ENTRY.replace("TD-190: A window to keep", "TD-196: New on origin").replace(
            "**Blocked by:** decision (paul)\n", "**Kind:** design-first\n"
        )
    )
    git(other, "add", "-A")
    git(other, "-c", "user.name=o", "-c", "user.email=o@x", "commit", "-qm", "new")
    git(other, "push", "-q", "origin", "main")
    at = None  # a v3 board has no lines: found by its text (TD-1881)
    async with LocalClient() as me:
        await me.call(
            "board_edit", board=str(repo / board.BOARD), line=at, text=ITEM, action="snooze", due="2099-01-01"
        )
    got = {e["id"]: e for e in agent._repos[root]["ledger"]["entries"]}
    for i in ("TD-190", "TD-195"):
        assert {k: got[i].get(k) for k in ("pickable", "live", "waiting", "settling")} == {
            k: tick[i].get(k) for k in ("pickable", "live", "waiting", "settling")
        }, i
    assert got["TD-195"].get("waiting"), "a wait is marked on the re-read"
    assert got["TD-196"].get("settling"), "first seen by the re-read: it settles, not yet pickable"


async def test_a_pass_begun_before_a_reread_keeps_the_entry_the_press_archived(agent, repo, tmp_path, monkeypatch):
    """TD-1471: a pass begun before a press's re-read lands after it: the entry origin archived, which the re-read
    took, stays archived in the Queue — the pass installs neither its ledger nor its archive over the re-read's."""
    import asyncio

    from sessionorc import reports

    _gated(repo)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    await park_ticks(agent)
    monkeypatch.setattr(reports, "pr_reading", lambda d, now, **kw: {"open": [], "at": now.isoformat()})
    root = str(repo)
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()
    real = agent._read_repos
    loop = asyncio.get_running_loop()
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", git(repo, "remote", "get-url", "origin"), str(other))

    def done_meanwhile(*args):
        got = real(*args)  # read before the Done… lands
        (other / "docs" / "ledger" / "archive").mkdir()
        git(other, "mv", "docs/ledger/TD-190.md", "docs/ledger/archive/TD-190.md")
        git(other, "-c", "user.name=o", "-c", "user.email=o@x", "commit", "-qm", "TD-190: done (#9)")
        git(other, "push", "-q", "origin", "main")
        git(repo, "fetch", "-q", "origin")  # the landing's own fetch
        asyncio.run_coroutine_threadsafe(agent._reread_board(root), loop).result(60)
        return got

    monkeypatch.setattr(agent, "_read_repos", done_meanwhile)
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()
    assert "TD-190" not in {e["id"] for e in agent._repos[root]["ledger"]["entries"]}
    assert "TD-190" in {e["id"] for e in agent._archived[root]}
    await agent._queue_pass(datetime.now(UTC))
    assert not [c for c in agent._queue["cards"] if c["id"].endswith("#TD-190")]


GATED_PARTS = (
    "decide 2026-11-05 (session `grinder-ao-2` on kmaster) — **Go on TD-190?** Say. Context: TD-190 decision (paul). "
    "Parts: TD-191, TD-192. Due: 2026-11-06. Answers: Go | Not yet."
)


async def test_a_go_on_a_design_and_its_parts_lifts_every_entry_it_wrote_at_once(agent, repo, tmp_path, monkeypatch):
    """TD-1433, TD-1471: a lift that writes several entries (a design and its `Parts:`) lands them on origin, and the
    re-read against origin reads each one, so no part stays on the Queue with **Lift the hold** while the checkout
    has not pulled."""
    from shiftlead.ui.inbox import ledger_for_you

    _gated(repo)
    for n in (191, 192):
        part = GATED_ENTRY.replace("TD-190: A window to keep", f"TD-{n}: A part").replace(
            "**Blocked by:** decision (paul)", "**Blocked by:** decision (paul)\n**Part of:** TD-190"
        )
        (repo / "docs" / "ledger" / f"TD-{n}.md").write_text(part)
    write_board(repo, BOARD_TEXT.replace("## Needs", "People: paul\n\n## Needs") + f"- [ ] {GATED_PARTS}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "parts")
    git(repo, "push", "-q", "origin", "main")
    tick = await _press_go(agent, repo, tmp_path, monkeypatch, GATED_PARTS)
    root = str(repo)
    for n in (191, 192):
        assert "decision (paul)" in (repo / "docs" / "ledger" / f"TD-{n}.md").read_text(), "the checkout has not pulled"
    ids = ("TD-190", "TD-191", "TD-192")
    for reading in (agent._repos[root]["ledger"]["entries"], (await tick()).values()):
        got = {e["id"]: e for e in reading if e["id"] in ids}
        assert sorted(got) == list(ids) and all(_lifted(e) for e in got.values()), got
    rows = [r.get("id") for g in ledger_for_you(agent._repos, [])["groups"] for r in g["rows"]]
    assert not set(rows) & set(ids), rows


def test_a_go_on_another_repos_gated_entry_is_answered_on_the_board_alone(repo):
    """An item naming another repo's entry is answered on the board alone and stays open: its lift is a tool PR
    there (ledgerboard's `_decide_ledger`), so no ledger is passed and nothing beside the board lands."""
    _gated(repo)
    other = GATED.replace("Context: TD-190", "Context: other#TD-190")
    push_board(repo, BOARD_TEXT.replace("## Needs", "People: paul\n\n## Needs") + f"- [ ] {other}\n", "another's")
    at = None  # a v3 board has no lines: found by its text (TD-1881)
    got = board.write_back(repo, at, other, "decide", answer="Go")
    assert "entries" not in got
    assert board_files(repo) == {f"docs/user_attention/{got['id']}.md"}
    assert origin_item(repo, ref_of(other)).closed is None


async def _registered(agent, repo: Path, tmp_path: Path, monkeypatch) -> list[dict]:
    """Register `repo`, read it once, and return the `repos` pushes from then on."""
    from sessionorc import reports

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    await park_ticks(agent)
    monkeypatch.setattr(reports, "pr_reading", lambda d, now, **kw: {"open": [], "at": now.isoformat()})
    pushed: list[dict] = []
    real_broadcast = agent._broadcast

    async def broadcast(ev: dict) -> None:
        if ev.get("event") == "repos":
            pushed.append(ev)
        await real_broadcast(ev)

    monkeypatch.setattr(agent, "_broadcast", broadcast)
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()
    assert str(repo) in agent._repos
    pushed.clear()
    return pushed


async def test_an_orphaned_questions_answer_is_read_at_once_on_the_stale_checkout(agent, repo, tmp_path, monkeypatch):
    """TD-1508 (§4.4 *Every write the home lands is read at once*): the person's answer to an orphaned question
    lands a board line through the write-back, and the board is read again at once — the line is in the `repos`
    push the answer makes, while the checkout has not pulled."""
    from sessionorc.models import MailEntry

    _gated(repo)
    pushed = await _registered(agent, repo, tmp_path, monkeypatch)
    o = {"at": "2026-10-02T09:00:00Z", "how": "closed", "ref": "TD-190", "name": "designer", "repo": str(repo),
         "host": "h", "team": "g"}  # fmt: skip
    e = MailEntry(id="m-orph", from_="ao-t-designer", to=["person"], at="2026-10-02T08:00:00Z", kind="ask",
                  text="Shall the widget be blue?", about="TD-190", orphaned=o)  # fmt: skip
    agent.person_inbox.append(e)
    got = await agent._answer_orphan(e, "Blue, yes", "replied")
    assert got["closed"] == "m-orph"
    assert "Shall the widget be blue?" not in (repo / board.BOARD).read_text(), "the checkout has not pulled"
    assert pushed, "the answer pushed `repos` at once, with no tick"
    assert "Shall the widget be blue?" in json.dumps(pushed[-1]["repo"]["boards"])


def _member(agent, ref: str) -> dict:
    """The Queue's row for `ref` (`<repo>#TD-n`) in the home's last reading."""
    for c in (agent._queue or {}).get("cards") or ():
        for r in [c.get("top"), *(c.get("rows") or [])]:
            if isinstance(r, dict) and r.get("qid") == ref:
                return r
    raise AssertionError(f"{ref} is on no card")


def _item(push: dict, key: str) -> dict:
    """The board item `key` of a `repos` push."""
    return next(it for b in push["repo"]["boards"]["boards"] for it in b["items"] if it.get("key") == key)


async def test_a_decide_press_reads_answered_applying_until_it_lands(agent, repo, tmp_path, monkeypatch):
    """TD-1508 (§4.4 *A press is drawn as it lands*): from the press until its re-read, the line's item carries
    `applying` in the `repos` push and the Queue's member reads *answered — applying* with no need; a tick's read in
    that window keeps it (the mark is not in the reading), and after the landing the mark is gone."""
    import threading

    from sessionorc import agent_inbox

    _gated(repo)
    pushed = await _registered(agent, repo, tmp_path, monkeypatch)
    name = repo.name
    await agent._queue_pass(datetime.now(UTC))
    assert _member(agent, f"{name}#TD-190")["needs"], "the gated member needs the person before the press"
    item = next(
        it for b in agent._repos[str(repo)]["boards"]["boards"] for it in b["items"] if it.get("kind") == "decide"
    )
    key, at = item["key"], item.get("line")
    release, started = threading.Event(), threading.Event()
    real = agent_inbox.board_mod.write_back

    def slow(*a, **kw):
        started.set()
        assert release.wait(30)
        return real(*a, **kw)

    monkeypatch.setattr(agent_inbox.board_mod, "write_back", slow)
    press = asyncio.create_task(
        agent.rpc_board_edit(board=str(repo / board.BOARD), line=at, text=GATED, action="decide", answer="Go",
                             answers=["Go", "Not yet"], key=key)
    )  # fmt: skip
    while not started.is_set():
        await asyncio.sleep(0.01)
    assert _item(pushed[-1], key)["applying"]["act"] == "decide"
    assert _item(pushed[-1], key)["applying"]["answer"] == "Go"
    m = _member(agent, f"{name}#TD-190")
    assert m["state"] == "answered — applying" and m["needs"] is None and m["applying"]["act"] == "decide"
    assert "applying" not in json.dumps(agent._repos[str(repo)]), "kept apart from the reading"
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()  # a tick's read in the window
    await agent._queue_pass(datetime.now(UTC))
    assert _member(agent, f"{name}#TD-190")["state"] == "answered — applying", "a tick's read keeps the mark"
    release.set()
    got = await press
    assert got["action"] == "decide"
    assert agent._applying == {}
    assert all(not it.get("applying") for b in pushed[-1]["repo"]["boards"]["boards"] for it in b["items"])
    assert "applying" not in json.dumps(agent.repos_store.load())


async def test_a_failed_or_refused_press_leaves_no_mark(agent, repo, tmp_path, monkeypatch):
    """TD-1508: a write-back that fails, one the board refuses, and a re-read that fails each clear the mark and
    push `repos` again, the press's error returned; two presses on one key, the second refused, leave the first's
    words standing until the first returns."""
    from sessionorc import agent_inbox

    _gated(repo)
    pushed = await _registered(agent, repo, tmp_path, monkeypatch)
    item = next(
        it for b in agent._repos[str(repo)]["boards"]["boards"] for it in b["items"] if it.get("kind") == "decide"
    )
    key, path = item["key"], str(repo / board.BOARD)

    def boom(*a, **kw):
        raise OSError("disk gone")

    monkeypatch.setattr(agent_inbox.board_mod, "write_back", boom)
    with pytest.raises(OSError):
        await agent.rpc_board_edit(
            board=path, line=item.get("line"), text=GATED, action="snooze", due="2099-01-01", key=key
        )
    assert agent._applying == {} and not _item(pushed[-1], key).get("applying")
    with pytest.raises(RpcError):
        await agent.rpc_board_edit(board=path, line=item.get("line"), text=GATED, action="decide", answer="Maybe",
                                   answers=["Go", "Not yet"], key=key)  # fmt: skip
    assert agent._applying == {}

    # two presses: the first's token stands while the second's is refused and cleared
    async with agent._applying_mark(repo, key, "decide", "Go"):

        def refused(*a, **kw):
            raise board.Refused("the line moved")

        monkeypatch.setattr(agent_inbox.board_mod, "write_back", refused)
        with pytest.raises(RpcError, match="the line moved"):
            await agent.rpc_board_edit(board=path, line=item.get("line"), text=GATED, action="done", key=key)
        assert _item(pushed[-1], key)["applying"] == {**_item(pushed[-1], key)["applying"], "act": "decide"}
    assert agent._applying == {} and not _item(pushed[-1], key).get("applying")

    async def reread_fails(root, **kw):
        raise RuntimeError("origin unreachable")

    monkeypatch.setattr(
        agent_inbox.board_mod, "write_back", lambda *a, **kw: {"message": "m", "line": item.get("line")}
    )
    monkeypatch.setattr(agent, "_reread_board", reread_fails)
    with pytest.raises(RuntimeError):
        await agent.rpc_board_edit(board=path, line=item.get("line"), text=GATED, action="done", key=key)
    assert agent._applying == {}


async def test_a_ledger_decide_marks_the_entrys_member(agent, repo, tmp_path, monkeypatch):
    """TD-1508: a ledger decide marks `ledger:<repo>#TD-n` — the entry in the `repos` push carries `applying`
    while the write lands, and the mark is gone once the call returns."""
    import threading

    from sessionorc import agent_inbox

    _gated(repo)
    pushed = await _registered(agent, repo, tmp_path, monkeypatch)
    seen: list[dict] = []
    real = agent_inbox.board_mod.add_decided
    ran = threading.Event()

    def watch(*a, **kw):
        ran.set()
        return real(*a, **kw)

    monkeypatch.setattr(agent_inbox.board_mod, "add_decided", watch)
    real_mark = agent._applying_push

    async def push(root):
        await real_mark(root)
        seen.append(json.loads(json.dumps(agent._applying.get(root) or {})))

    monkeypatch.setattr(agent, "_applying_push", push)
    await agent.rpc_ledger_decide(repo=str(repo), id="TD-190", words="blue", caller=None)
    assert ran.is_set()
    k = f"ledger:{repo.name}#TD-190"
    assert list(seen[0]) == [k] and list(seen[0][k].values())[0] == {**list(seen[0][k].values())[0], "act": "decide",
                                                                      "answer": "blue"}  # fmt: skip
    assert agent._applying == {} and seen[-1] == {}
    assert pushed


async def test_a_press_cancelled_during_its_first_push_leaves_no_mark(agent, repo, tmp_path, monkeypatch):
    """TD-1508 review: a press cancelled while its mark's first push runs still clears its token."""
    _gated(repo)
    await _registered(agent, repo, tmp_path, monkeypatch)
    gate = asyncio.Event()

    async def hang(root):
        if not gate.is_set():
            gate.set()
            await asyncio.sleep(30)

    monkeypatch.setattr(agent, "_applying_push", hang)

    async def press():
        async with agent._applying_mark(repo, "board:k", "done"):
            raise AssertionError("never reached")

    t = asyncio.create_task(press())
    await gate.wait()
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    assert agent._applying == {}


HOLD = (
    "decide 2026-11-12 (session `designer-ao-1` on kmaster) — **End the rounds?** Say. "
    "Due: 2026-11-20. Answers: Go | Hold: <note>."
)


def _hold_board(repo: Path, *items: str) -> None:
    push_board(repo, BOARD_TEXT + "".join(f"- [ ] {i}\n" for i in items), "asked")


def test_a_reply_that_fills_a_form_decides_the_line_in_one_commit(repo):
    """TD-1698 (§4.4 *A Reply that fills a form decides*): a Reply whose words begin with a form's head and a colon,
    on an open undecided decide line, is that form's decide — `Decided:` by the person, the decide's subject, no
    reply trail, `decided` answered and the callback told; any case of the head is written as offered."""
    _hold_board(repo, HOLD)
    told: list[str] = []
    got = board.write_back(repo, 9, HOLD, "reply", reply="hold :  drop\nDismiss", on_decide=told.append)
    it = origin_item(repo, ref_of(HOLD))
    assert got["decided"] == "Hold: drop Dismiss" and told and set(told) == {"Hold: drop Dismiss"}
    assert (it.decided[0], it.decided_by, it.replies) == ("Hold: drop Dismiss", "t", [])
    assert got["message"].startswith(f"shiftlead: decide {got['id']} End the rounds? Say.: Hold: drop Dismiss")
    assert on_origin(repo, "log", "-1", "--format=%s", "origin/main") == f"{got['message']} (#{got['pr']})"


def test_a_reply_that_fills_no_form_stays_a_reply_and_an_empty_fill_is_refused(repo):
    """TD-1698: words that begin with no form's head stay a Reply and leave the line due; the form as written, its
    head alone, its head with a placeholder, or a fill ending `(by …)`, are refused with nothing written."""
    _hold_board(repo, HOLD)
    before = origin_docs(repo)
    for bad, why in (
        ("Hold: <note>", "Hold needs its words"),
        ("Hold:", "Hold needs its words"),
        ("hold: <b>", "Hold needs its words"),
        # retired (TD-1881): a fill ending `(by …)` — v3.0's `Decided` value reads such an answer as words
    ):
        with pytest.raises(board.Refused, match=why):
            board.write_back(repo, 9, HOLD, "reply", reply=bad, on_decide=lambda _a: None)
        assert origin_docs(repo) == before
    got = board.write_back(repo, 9, HOLD, "reply", reply="Wait: a day, then ask")
    assert "decided" not in got and got["message"].startswith("shiftlead: reply")
    it = origin_item(repo, ref_of(HOLD))
    assert it.replies[-1][2] == "Wait: a day, then ask" and it.decided is None


LONG_NOTE = (
    "Findings aren't shrinking and this design keeps overlapping TD-1829. Leave everything about Lift (when it is "
    "drawn, what a press may lift) to TD-1829 alone; this design puts the same answer bar on every card and calls "
    "TD-1829's helpers. Build TD-1842 as designed. Move the one-press lift-and-reply into a follow-up entry. TD-1843 "
    "is blocked by TD-1829's builds, and its next review round runs only after TD-1829's Go."
)


def test_a_long_hold_note_is_written_whole_on_the_line_and_the_ledger_log(repo):
    """TD-1883 (design §4.4 *A person's words are written whole*): a Hold note past 300 characters, filled as the page
    sends it (its words and `form`), reaches the line's `Decided:` and the entry's *kept waiting* Log line whole;
    only the commit's subject is shortened, with its `…`. Paul's 2026-11-14 note was cut to 297 characters."""
    assert len(LONG_NOTE) > 400
    from sessionorc.agent_inbox import InboxMixin as A

    _gated(repo)
    held = GATED.replace("Answers: Go | Not yet.", "Answers: Go | Hold: <note>. Lifts: Go.")
    (repo / board.BOARD).write_text(origin_board(repo).replace(GATED, held))
    git(repo, "commit", "-qam", "a form")
    git(repo, "push", "-q", "origin", "main")
    said = A._board_answer("decide", LONG_NOTE, ["Go", "Hold: <note>"], 1)
    assert said == f"Hold: {LONG_NOTE}"
    at = origin_board(repo).splitlines().index(f"- [ ] {held}") + 1
    got = board.write_back(repo, at, held, "decide", answer=said)
    assert got["entries"] == ["TD-190"] and got["message"].endswith("… (session `grinder-ao-2`)")
    line = origin_board(repo).splitlines()[at - 1]
    assert f"Decided: Hold: {LONG_NOTE} (by paul)" in line
    entry = on_origin(repo, "show", "origin/main:docs/ledger/TD-190.md")
    assert f'kept waiting: decision (paul) — by paul; answer "Hold: {LONG_NOTE}"' in entry


def test_a_long_reply_is_written_whole_and_one_filling_a_form_decides_whole(repo):
    """TD-1883: a Reply past 300 characters is written on the line whole, and one whose words begin with a form's
    head decides it with the whole fill, as a pressed form does."""
    _hold_board(repo, HOLD, HOLD.replace("End the rounds?", "Another round?"))
    got = board.write_back(repo, 9, HOLD, "reply", reply=f"Hold: {LONG_NOTE}")
    assert got["decided"] == f"Hold: {LONG_NOTE}"
    assert f"Decided: Hold: {LONG_NOTE} (by t)" in origin_board(repo).splitlines()[8]
    other = HOLD.replace("End the rounds?", "Another round?")
    at = origin_board(repo).splitlines().index(f"- [ ] {other}") + 1
    got = board.write_back(repo, at, other, "reply", reply=LONG_NOTE)
    assert "decided" not in got and f": {LONG_NOTE}" in origin_board(repo).splitlines()[at - 1]


@pytest.mark.unit
def test_which_lines_a_replys_form_decides():
    """TD-1698: an open undecided `decide` or `look` line offering a form, or a `watch` with the look's pair; not a
    decided line, a line with no form, an `act` line, or a `watch` with another form. `live_look_pair` is exactly
    *Works* and the *Not right: <what>* form on a look kind."""
    assert board.reply_fills(HOLD, "Hold: x") == "Hold: x"
    assert board.reply_fills(HOLD, "Go") is None and board.reply_fills(HOLD, "Later: x") is None
    assert board.reply_fills(HOLD + " Decided: Go (by t) (2026-11-13).", "Hold: x") is None
    assert board.reply_fills(ASKED, "Keep it: x") is None  # no form offered
    assert board.reply_fills(LOOK, "not right: the ring is amber") == "Not right: the ring is amber"
    look = LOOK.replace("watch ", "look ", 1).replace("Not right: <what>", "Hold: <note>")
    assert board.reply_fills(look, "Hold: x") == "Hold: x"
    assert board.reply_fills(LOOK.replace("Not right: <what>", "Hold: <note>"), "Hold: x") is None  # a watch, no pair
    assert board.reply_fills(HOLD.replace("decide ", "act ", 1), "Hold: x") is None
    assert board.live_look_pair("look", ["Works", "Not right: <what>"]) and board.live_look_pair("watch", [
        "Works", "not right: <what>"])  # fmt: skip
    assert not board.live_look_pair("look", ["Works", "Hold: <note>"])
    assert not board.live_look_pair("decide", ["Works", "Not right: <what>"])


async def test_board_reply_that_fills_a_form_answers_decided_and_mails_nobody(agent, repo, tmp_path):
    """TD-1698: the RPC's half — a Reply that fills a form answers `decided`, its action `decide`, and writes no
    reply trail line; a refused fill is the decide's words."""
    _hold_board(repo, HOLD)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{repo}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")
    path = str(repo / board.BOARD)
    async with LocalClient() as me:
        with pytest.raises(AgentError, match="Hold needs its words"):
            await me.call("board_reply", board=path, line=9, text=HOLD, reply="Hold: <note>")
        got = await me.call("board_reply", board=path, line=9, text=HOLD, reply="Hold: drop Dismiss", refs=["TD-1"])
        assert got["decided"] == "Hold: drop Dismiss" and got["action"] == "decide" and "sent" not in got
        trail = [t for t in (await me.call("inbox"))["trail"] if t["kind"] == "board reply"]
    assert trail == []
    it = origin_item(repo, ref_of(HOLD))
    assert (it.decided[0], it.decided_by) == ("Hold: drop Dismiss", "t")


def test_a_reply_filling_a_lifting_form_on_a_gated_decide_lifts_it(repo):
    """TD-1698: on a gated item, a Reply that fills `Hold:` where `Hold: <note>` is in `Lifts:` is the decide, with
    its lift: the entry's gate lifted and the item closed in one commit, as a pressed lifting answer does."""
    _gated(repo)
    held = GATED.replace("Answers: Go | Not yet.", "Answers: Go | Hold: <note>. Lifts: Hold: <note>.")
    push_board(repo, BOARD_TEXT.replace("## Needs", "People: paul\n\n## Needs") + f"- [ ] {held}\n", "a form lifts")
    at = None  # a v3 board has no lines: found by its text (TD-1881)
    got = board.write_back(repo, at, held, "reply", reply="Hold: until the release")
    assert got["decided"] == "Hold: until the release" and got["entries"] == ["TD-190"]
    entry = on_origin(repo, "show", "origin/main:docs/ledger/TD-190.md")
    assert "**Blocked by:**" not in entry and "gate lifted: decision (paul)" in entry
    it = origin_item(repo, ref_of(held))
    assert it.closed is not None and it.decided[0] == "Hold: until the release"
