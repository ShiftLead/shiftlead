"""Lift the hold is a lift on the press (design §4.4 *Board write-back*, TD-1829, built by TD-1831): the write
`board.lift_on_press` lifts an entry's `decision (paul)` itself, in one commit landed on origin by its own PR, and
writes no work order — each of `covers()`'s four cases, a gone entry, and the person check, on a scratch repo and
its bare origin; every landed commit passes ledgerboard's tripwire."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from _v3board import ref_of, write_board

from sessionorc import board, ledgerboard
from sessionorc import ledger as ledger_mod

BOARD_HEAD = "# User attention\n\nFormat: `- [ ] …`\n\nPeople: paul\n\n## Needs the user\n\n"
FILLER = "2026-09-21 (n/a) — an unrelated item."
ENTRY = """## TD-{n}: {title}

**Priority:** Low
**Added:** 2026-11-01
**Owner:** grinder
**Status:** Open
**Blocked by:** decision (paul)
{extra}
**Ask:** Go on TD-{n}?

**Why:** a test's.
"""
ASKED = (
    "decide 2026-11-05 (session `designer-ao-1` on kmaster) — **Go on TD-190?** Say. Context: TD-190 decision (paul). "
    "Due: 2026-11-06. Answers: Go | Not yet."
)
DECIDED = ASKED.replace("Answers: Go | Not yet.", "Answers: Go | Not yet. Decided: Not yet (by paul) (2026-11-15).")
SHARED = ASKED.replace("Context: TD-190 decision (paul).", "Context: TD-189 decision (paul). Parts: TD-190, TD-191.")
NO_GATE = "2026-11-15 (n/a) — **Go ahead on TD-190.** Context: TD-190. Due: 2026-11-15."


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def _entry(n: int, title: str = "A window to keep", extra: str = "") -> str:
    return ENTRY.format(n=n, title=title, extra=extra)


@pytest.fixture
def repo(tmp_path, forge) -> Path:
    root = tmp_path / "repo"
    (root / "docs" / "ledger").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    (root / "docs" / "ledger" / "README.md").write_text("# Ledger\n\nLedgerboard: 2\n")
    (root / "docs" / "ledger" / "TD-190.md").write_text(_entry(190))
    write_board(root, BOARD_HEAD + f"- [ ] {FILLER}\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    forge(root)
    return root


def _push(root: Path, items: list[str], entries: dict[int, str] | None = None) -> None:
    """The board rewritten with `items` (after the filler) and `entries` added to the ledger, pushed to origin."""
    write_board(root, BOARD_HEAD + "".join(f"- [ ] {it}\n" for it in [FILLER, *items]))
    for n, text in (entries or {}).items():
        (root / "docs" / "ledger" / f"TD-{n}.md").write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "the case")
    git(root, "push", "-q", "origin", "main")


def _tree(root: Path, rev: str) -> dict[str, str]:
    names = git(root, "ls-tree", "-r", "--name-only", rev, "--", "docs").splitlines()
    return {p: git(root, "show", f"{rev}:{p}") + "\n" for p in names}


def _landed(root: Path) -> tuple[str, str]:
    """Origin's head after the press: (the entry's text, the commit's subject), the commit checked by ledgerboard's
    tripwire against its parent."""
    git(root, "fetch", "-q", "origin")
    subject = git(root, "log", "-1", "--format=%s", "origin/main")
    flags = ledgerboard.tripwire(_tree(root, "origin/main~1"), _tree(root, "origin/main"), subject, "repo")
    assert flags == [], flags
    return git(root, "show", "origin/main:docs/ledger/TD-190.md"), subject


def _item(root: Path, text: str) -> ledgerboard.BoardItem | None:
    nonce = ref_of(text).removeprefix("board:")
    b = ledgerboard.load_board(board.BOARD.as_posix(), *ledger_mod.git_io(root, "origin/main", under="docs"))
    return next((it for it in [*b.items, *b.closed] if it.id and it.id.endswith("-" + nonce)), None)


def _lift_line(entry: str) -> str:
    day = datetime.now(UTC).date().isoformat()
    return next(ln for ln in entry.splitlines() if ln.startswith(f"- {day}: gate lifted: decision (paul)"))


def test_a_lift_with_no_board_item_lands_one_commit_and_no_work_order(repo):
    """Case (a): nothing covers the gate — the lift's suffix `no board item`, the subject the design's, no board
    file written."""
    before = git(repo, "rev-parse", "origin/main")
    got = board.lift_on_press(repo, "TD-190")
    assert got["lifted"] is True and got["suffix"] == "no board item" and got["closed"] == []
    entry, subject = _landed(repo)
    assert got["message"] == "shiftlead: lift decision (paul) on TD-190 (session n/a)"
    assert subject.startswith(got["message"])  # the forge's squash adds its `(#n)`
    assert "**Blocked by:**" not in entry
    assert _lift_line(entry).endswith('— by paul; answer "go ahead"; no board item')
    changed = git(repo, "diff", "--name-only", before, "origin/main").splitlines()
    assert changed == ["docs/ledger/TD-190.md"]
    assert git(repo, "status", "--porcelain") == ""  # the checkout is never written


def test_an_open_decided_line_is_closed_lifted_in_the_same_commit(repo):
    """Case (b): an open decided item covers the gate and lists no other gated entry — closed `— lifted.` beside
    the lift, which takes no suffix; an open no-gate line naming the entry is no cover and is left open."""
    _push(repo, [DECIDED, NO_GATE])
    got = board.lift_on_press(repo, "TD-190")
    assert got["suffix"] == "" and got["closed"] == [ref_of(DECIDED)]
    entry, _ = _landed(repo)
    assert _lift_line(entry).endswith('answer "go ahead"')
    closed = _item(repo, DECIDED)
    assert closed.closed is not None and closed.closed[1] == "lifted"
    assert _item(repo, NO_GATE).closed is None


def test_a_held_decided_line_or_a_held_entry_refuses_case_b_and_writes_nothing(repo):
    """Case (b) with a holder: a `board:<key>` claim on the covering item, or one on the entry itself, refuses the
    press in the design's words, origin untouched."""
    _push(repo, [DECIDED])
    head = git(repo, "rev-parse", "origin/main")
    key = ref_of(DECIDED)
    holder = {"id": "ao-shiftlead-grinder-ao-2", "name": "grinder-ao-2"}
    with pytest.raises(board.Refused, match=f"{key} is being acted on by grinder-ao-2: lift the hold once it lands"):
        board.lift_on_press(repo, "TD-190", held={key: holder})
    with pytest.raises(board.Refused, match=f"{key} is being acted on by grinder-ao-2"):
        board.lift_on_press(repo, "TD-190", entry_holder=holder)
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "origin/main") == head


@pytest.mark.parametrize("shared", [False, True], ids=["a", "c"])
def test_a_claim_on_the_entry_refuses_neither_case_a_nor_case_c(repo, shared):
    """The entry's holder is read in case (b) alone: a claim on the entry refuses neither (a) nor (c)."""
    if shared:
        _push(repo, [SHARED], {
            189: _entry(189, "A design"),
            190: _entry(190, extra="**Part of:** TD-189\n"),
            191: _entry(191, "A part", "**Part of:** TD-189\n"),
        })  # fmt: skip
    got = board.lift_on_press(repo, "TD-190", entry_holder={"id": "x", "name": "grinder-ao-2"})
    assert got["lifted"] is True and got["suffix"] == ("shared board item left open" if shared else "no board item")


def test_a_shared_item_listing_another_gated_entry_stays_open(repo):
    """Case (c): the covering item (the parent's, through `Part of`) lists another entry still carrying the gate —
    the lift's suffix `shared board item left open`, the item open for the entries it still holds."""
    _push(
        repo,
        [SHARED],
        {
            189: _entry(189, "A design"),
            190: _entry(190, extra="**Part of:** TD-189\n"),
            191: _entry(191, "A part", "**Part of:** TD-189\n"),
        },
    )
    got = board.lift_on_press(repo, "TD-190")
    assert got["suffix"] == "shared board item left open" and got["closed"] == []
    entry, _ = _landed(repo)
    assert _lift_line(entry).endswith("; shared board item left open")
    assert _item(repo, SHARED).closed is None
    assert "decision (paul)" in git(repo, "show", "origin/main:docs/ledger/TD-191.md")


def test_an_open_undecided_item_that_asks_the_hold_refuses_the_press(repo):
    """Case (d): an open, undecided item covers the gate and lists no other gated entry — the hold is asked there,
    and the press is refused naming it, nothing written; tried before (b), so a decided line beside it changes
    nothing."""
    _push(repo, [ASKED, DECIDED.replace("**Go on TD-190?**", "**Go on TD-190, again?**")])
    head = git(repo, "rev-parse", "origin/main")
    with pytest.raises(board.Refused, match=f"TD-190's hold is asked on {ref_of(ASKED)}: answer it there"):
        board.lift_on_press(repo, "TD-190")
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "origin/main") == head


def test_an_entry_archived_or_no_longer_held_is_gone_and_writes_nothing(repo):
    """`{gone: true}`: the entry has no `decision (paul)` (lifted elsewhere), or is archived — nothing written."""
    (repo / "docs" / "ledger" / "TD-190.md").write_text(_entry(190).replace("**Blocked by:** decision (paul)\n", ""))
    git(repo, "commit", "-qam", "lifted elsewhere")
    git(repo, "push", "-q", "origin", "main")
    head = git(repo, "rev-parse", "origin/main")
    assert board.lift_on_press(repo, "TD-190") == {"gone": True}
    assert board.lift_on_press(repo, "TD-404") == {"gone": True}
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "origin/main") == head


def test_only_the_gates_person_lifts_it(repo):
    """*only <p> lifts <p>'s hold*: a board whose `People:` names several reads the host's author, who is not the
    gate's person — refused, nothing written."""
    write_board(repo, BOARD_HEAD.replace("People: paul", "People: paul, t") + f"- [ ] {FILLER}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "two people")
    git(repo, "push", "-q", "origin", "main")
    with pytest.raises(board.Refused, match="only paul lifts paul's hold"):
        board.lift_on_press(repo, "TD-190")


# -- Go now: a design's lift with its held builds (design §4.4 *Go now lifts the design and its builds*, TD-2027) ---

ROUNDS = (
    "decide 2026-11-05 (session `designer-ao-1` on kmaster) — **Should the grinders build TD-190?** Say. "
    "Context: TD-190 decision (paul). Parts: TD-191, TD-192. Due: 2026-11-06. Answers: Go | One more round."
)
ROUNDS_DECIDED = ROUNDS.replace("Answers: Go | One more round.", "Answers: Go | One more round. "
                                "Decided: One more round (by paul) (2026-11-15).")  # fmt: skip


def _design(root: Path, items: list[str]) -> None:
    """TD-190 a design whose builds TD-191 and TD-192 are `Part of` it, each carrying `decision (paul)`."""
    _push(root, items, {
        190: _entry(190, "A design"),
        191: _entry(191, "A build", "**Part of:** TD-190\n"),
        192: _entry(192, "Another build", "**Part of:** TD-190\n"),
    })  # fmt: skip


def _gated(root: Path, n: int) -> bool:
    return "**Blocked by:** decision (paul)" in git(root, "show", f"origin/main:docs/ledger/TD-{n}.md")


@pytest.mark.parametrize("decided", [False, True], ids=["no-line", "decided-line"])
def test_go_now_lifts_the_design_and_each_build_in_one_commit(repo, decided):
    """One commit lifts the design's gate and each build's, each by `plan_lift` with *go ahead*, the subject naming
    the builds; with no line each lift's suffix is `no board item`, and a decided end-of-rounds line covering the
    set alone is case (b), closed `— lifted.`, no suffix on any; ledgerboard's tripwire passes either way."""
    _design(repo, [ROUNDS_DECIDED] if decided else [])
    before = git(repo, "rev-parse", "origin/main")
    got = board.lift_on_press(repo, "TD-190", builds=["TD-191", "TD-192"])
    assert got["lifted"] is True and got["builds"] == ["TD-191", "TD-192"]
    assert got["message"] == "shiftlead: lift decision (paul) on TD-190 and its builds TD-191, TD-192 (session n/a)"
    _landed(repo)
    assert git(repo, "rev-list", "--count", f"{before}..origin/main") == "1"
    for n in (190, 191, 192):
        assert not _gated(repo, n)
        line = _lift_line(git(repo, "show", f"origin/main:docs/ledger/TD-{n}.md"))
        assert line.endswith('answer "go ahead"' if decided else 'answer "go ahead"; no board item'), line
    if decided:
        assert got["closed"] == [ref_of(ROUNDS_DECIDED)] and _item(repo, ROUNDS_DECIDED).closed[1] == "lifted"


def test_go_now_with_an_open_end_of_rounds_line_is_case_d_over_the_set(repo):
    """Case (d) read over the set: an open undecided item covering the design and its builds alone lists no entry
    outside the set, so it asks the hold — refused, nothing written."""
    _design(repo, [ROUNDS])
    head = git(repo, "rev-parse", "origin/main")
    with pytest.raises(board.Refused, match=f"TD-190's hold is asked on {ref_of(ROUNDS)}: answer it there"):
        board.lift_on_press(repo, "TD-190", builds=["TD-191", "TD-192"])
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "origin/main") == head


def test_go_now_claim_on_one_build_is_case_bs_holder(repo):
    """(b)'s holder test reads a claim on any entry of the set: the caller hands it as the entry's holder."""
    _design(repo, [ROUNDS_DECIDED])
    with pytest.raises(board.Refused, match="is being acted on by grinder-ao-2"):
        board.lift_on_press(
            repo, "TD-190", entry_holder={"id": "x", "name": "grinder-ao-2"}, builds=["TD-191", "TD-192"]
        )


@pytest.mark.parametrize("how", ["ungated", "archived"])
def test_go_now_whose_build_changed_at_origin_is_refused_and_writes_nothing(repo, how):
    """A build ungated or archived at origin's head between the read and the write: `BuildsChanged`, the tree reset,
    origin untouched; the design ungated there is `{gone: true}`."""
    _design(repo, [])
    led = repo / "docs" / "ledger"
    if how == "ungated":
        (led / "TD-192.md").write_text(_entry(192, "Another build", "**Part of:** TD-190\n").replace(
            "**Blocked by:** decision (paul)\n", ""))  # fmt: skip
    else:
        (led / "archive").mkdir(exist_ok=True)
        git(repo, "mv", "docs/ledger/TD-192.md", "docs/ledger/archive/TD-192.md")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a build changed")
    git(repo, "push", "-q", "origin", "main")
    head = git(repo, "rev-parse", "origin/main")
    with pytest.raises(board.BuildsChanged, match="TD-190's builds changed: read the card again"):
        board.lift_on_press(repo, "TD-190", builds=["TD-191", "TD-192"])
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "rev-parse", "origin/main") == head
    assert _gated(repo, 190) and _gated(repo, 191)
    (led / "TD-190.md").write_text(_entry(190, "A design").replace("**Blocked by:** decision (paul)\n", ""))
    git(repo, "commit", "-qam", "the design lifted elsewhere")
    git(repo, "push", "-q", "origin", "main")
    assert board.lift_on_press(repo, "TD-190", builds=["TD-191"]) == {"gone": True}
