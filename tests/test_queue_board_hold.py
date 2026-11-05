"""TD-1368 slice 2, design §4.4 *The card's status* (*A question the person answered on the board holds the member
the same way*): a `decision (paul)` member a decided board `decide` line covers reads *answered — waiting on
<holder>* and is no need while the line's test holds — an open decided line while open, a closed one *carried to
TD-m* while TD-m is open and filed for the answer, one closed in other words while a live claim holds a covered
member within `BOARD_WAIT_DAYS`, one closed `— kept waiting.` until its re-ask — the newest covering line alone
deciding, and a mail question that holds winning."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from test_queue import NOW, _by_id, _cards, _entry, _rec, _repo
from test_queue_answered_hold import _asker, _q

from sessionorc import ledger, queue, workorders

HELD = {"Priority": "High", "Blocked_by": "decision (paul)", "Added": "2026-10-01"}


def _board(root: str, *lines: str, archive: tuple[str, ...] = ()) -> dict:
    d = Path(root) / "docs"
    (d / "user_attention.md").write_text("\n".join(["# Board", "", *lines, ""]), encoding="utf-8")
    if archive:
        (d / "user_attention_archive.md").write_text("\n".join(["# Archive", "", *archive, ""]), encoding="utf-8")
    return workorders.read_boards(root, fetch=False)


def _open(ctx: str, *, decided: str | None = "Go (2026-10-15)", session: str = "n/a", parts: str = "") -> str:
    tail = f" Decided: {decided}." if decided else ""
    p = f" Parts: {parts}." if parts else ""
    return (f"- [ ] decide 2026-10-14 (session {session}) — **Ship it?** Context: {ctx}.{p} Due: 2026-10-20. "
            f"Answers: Go | Not yet.{tail}")  # fmt: skip


def _closed(ctx: str, why: str, *, decided: str = "One more round (2026-10-15)", closed: str = "2026-10-15") -> str:
    tail = f" — {why}" if why else ""
    return (f"- [x] decide 2026-10-14 (session n/a) — **Another round?** Context: {ctx}. Due: 2026-10-20. "
            f"Answers: Go | One more round. Decided: {decided}. Closed: {closed}{tail}.")  # fmt: skip


def _setup(tmp_path, entries, *board, archive=(), name="r"):
    root, r = _repo(tmp_path, name, entries)
    r["boards"] = _board(root, *board, archive=archive)
    return root, r


def _row(q: dict, ref: str) -> dict:
    for c in q["cards"]:
        for row in [c["top"], *c["rows"]]:
            if row["qid"] == ref:
                return row
    raise AssertionError(ref)


def _worker(rid: str = "ao-r-grinder", *refs: str):
    s = _rec(rid, "/x", *refs)
    s.name = rid.removeprefix("ao-r-")
    return s


def _read(repos, records=(), questions=()):
    q = _cards(repos, list(records), questions=list(questions))
    return q


@pytest.mark.unit
def test_an_open_decided_line_holds_its_member_while_open_naming_its_holder(tmp_path):
    root, r = _setup(tmp_path, [_entry(1, "the held one", **HELD)], _open("TD-001"))
    key = r["boards"]["boards"][0]["items"][0]["key"]
    # a live record holds the line's work order: its holder; one holding the member itself likewise
    for refs in ((key,), ("TD-001",)):
        rec = _worker("ao-r-grinder", *refs)
        rec.repo = rec.dir = root
        row = _row(_read({root: r}, [rec]), "r#TD-001")
        assert row["state"] == "answered — waiting on grinder" and row["needs"] == "decision", refs
        assert row["answered"]["kind"] == "board"
        assert row["answered"]["line"] == {"key": key, "open": True, "to": [], "said": "Go"}
        assert row["answered"]["closed_at"] == "2026-10-15" and "mid" not in row["answered"]
    c = _by_id(_read({root: r}))["r#TD-001"]
    assert c["top"]["state"] == "answered — waiting on a pick" and c["status"] != "needs you"
    # an expired claim holds nothing; nor does the person's own session (it reads *with you* instead)
    stale = _worker("ao-r-grinder", key)
    stale.repo = stale.dir = root
    stale.progress[0].at = (NOW - timedelta(hours=13)).isoformat()
    assert _row(_read({root: r}, [stale]), "r#TD-001")["state"] == "answered — waiting on a pick"
    # the line's live `session` names the wait with no claim
    root2, r2 = _setup(tmp_path / "s", [_entry(1, "the held one", **HELD)], _open("TD-001", session="designer"))
    assert _row(_read({root2: r2}, [_asker()]), "r#TD-001")["state"] == "answered — waiting on designer"


@pytest.mark.unit
def test_an_undecided_covering_line_asks_again_and_a_line_decided_by_another_holds_nothing(tmp_path):
    root, r = _setup(tmp_path, [_entry(1, "the held one", **HELD)], _closed("TD-001", "carried to TD-002"),
                     _open("TD-001", decided=None))  # fmt: skip
    c = _by_id(_read({root: r}))["r#TD-001"]
    assert c["top"]["answered"] is None and c["status"] == "needs you"
    root2, r2 = _setup(
        tmp_path / "b", [_entry(1, "the held one", **HELD)], _open("TD-001", decided="Go (by sam) (2026-10-15)")
    )
    assert _row(_read({root2: r2}), "r#TD-001")["answered"] is None
    root3, r3 = _setup(
        tmp_path / "c", [_entry(1, "the held one", **HELD)], _open("TD-001", decided="Go (by paul) (2026-10-15)")
    )
    assert _row(_read({root3: r3}), "r#TD-001")["state"] == "answered — waiting on a pick"


@pytest.mark.unit
def test_the_line_covers_a_part_carrying_its_own_hold_a_parts_id_a_second_context_ref(tmp_path):
    design = _entry(1, "the design", Priority="High", Kind="design-first", Blocked_by="decision (paul)")
    build = _entry(2, "a build", Priority="High", Part_of="TD-001", Blocked_by="decision (paul)", Added="2026-10-01")
    loose = _entry(3, "listed in Parts", **HELD)
    second = _entry(4, "named second", **HELD)
    root, r = _setup(tmp_path, [design, build, loose, second], _open("TD-001, TD-004", parts="TD-003"))
    q = _read({root: r})
    for ref in ("r#TD-001", "r#TD-002", "r#TD-003", "r#TD-004"):
        assert _row(q, ref)["state"] == "answered — waiting on a pick", ref


@pytest.mark.unit
def test_a_line_on_another_repos_board_covers_a_qualified_entry(tmp_path):
    root, r = _repo(tmp_path, "r", [_entry(1, "the held one", **HELD)])
    other, o = _setup(tmp_path, [_entry(9, "theirs", Priority="Low")], _open("r#TD-001"), name="o")
    assert _row(_read({root: r, other: o}), "r#TD-001")["state"] == "answered — waiting on a pick"
    # a bare id on another repo's board is that repo's entry, not this one's
    other2, o2 = _setup(tmp_path / "x", [_entry(9, "theirs", Priority="Low")], _open("TD-001"), name="o")
    assert _row(_read({root: r, other2: o2}), "r#TD-001")["answered"] is None


@pytest.mark.unit
def test_a_line_carried_to_an_entry_holds_while_it_is_open_filed_for_the_answer_and_not_the_persons(tmp_path):
    held = _entry(1, "the held one", **HELD)
    rnd = _entry(5, "the round", Priority="High", Kind="design-first", Added="2026-10-15")
    root, r = _setup(tmp_path, [held, rnd], _closed("TD-001", "carried to TD-005 and TD-006"))
    row = _row(_read({root: r}), "r#TD-001")
    assert row["state"] == "answered — waiting on TD-005"
    assert row["answered"]["line"]["to"] == ["TD-005", "TD-006"] and row["answered"]["line"]["open"] is False
    # its holder, where a live record holds it
    rec = _worker("ao-r-designer", "TD-005")
    rec.repo = rec.dir = root
    assert _row(_read({root: r}, [rec]), "r#TD-001")["state"] == "answered — waiting on designer"
    # archived: the person's again
    root2, r2 = _setup(tmp_path / "a", [held], _closed("TD-001", "carried to TD-005"))
    assert _row(_read({root2: r2}), "r#TD-001")["answered"] is None
    # filed before the answer (with a day's slack), or the person's own: no hold
    for i, fields in enumerate(({"Added": "2026-10-13"}, {"Added": "2026-10-15", "Owner": "paul"},
                                {"Added": "2026-10-15", "Blocked_by": "decision (paul)"})):  # fmt: skip
        sub = tmp_path / f"f{i}"
        root3, r3 = _setup(
            sub, [held, _entry(5, "the round", Priority="High", **fields)], _closed("TD-001", "carried to TD-005")
        )
        assert _row(_read({root3: r3}), "r#TD-001")["answered"] is None, fields
    root4, r4 = _setup(tmp_path / "s", [held, _entry(5, "r", Priority="High", Added="2026-10-14")],
                       _closed("TD-001", "carried to TD-005"))  # fmt: skip
    assert _row(_read({root4: r4}), "r#TD-001")["state"] == "answered — waiting on TD-005", "a day's slack"
    # *carried to TD-9 — see TD-4*: TD-9 alone
    root5, r5 = _setup(tmp_path / "d", [held, _entry(4, "seen", Priority="High", Added="2026-10-15")],
                       _closed("TD-001", "carried to TD-009 — see TD-004"))  # fmt: skip
    assert _row(_read({root5: r5}), "r#TD-001")["answered"] is None


@pytest.mark.unit
def test_an_archived_carried_line_is_read_from_the_archive(tmp_path):
    held = _entry(1, "the held one", **HELD)
    rnd = _entry(5, "the round", Priority="High", Added="2026-10-15")
    root, r = _setup(tmp_path, [held, rnd], "- [ ] act 2026-10-14 (session n/a) — **Other.** Due: 2026-10-30.",
                     archive=(_closed("TD-001", "carried to TD-005"),))  # fmt: skip
    assert _row(_read({root: r}), "r#TD-001")["state"] == "answered — waiting on TD-005"


@pytest.mark.unit
def test_a_line_closed_in_other_words_holds_only_while_a_covered_member_is_claimed_within_the_bound(tmp_path):
    held = _entry(1, "the held one", **HELD)
    root, r = _setup(tmp_path, [held], _closed("TD-001", "One more round, recorded on TD-001", closed="2026-10-15"))
    assert _row(_read({root: r}), "r#TD-001")["answered"] is None, "nobody holds it"
    rec = _worker("ao-r-designer", "TD-001")
    rec.repo = rec.dir = root
    assert _row(_read({root: r}, [rec]), "r#TD-001")["state"] == "answered — waiting on designer"
    old = (NOW.astimezone().date() - timedelta(days=queue.BOARD_WAIT_DAYS)).isoformat()
    root2, r2 = _setup(tmp_path / "o", [held], _closed("TD-001", "", decided=f"Go ({old})", closed=old))
    rec.repo = rec.dir = root2
    assert _row(_read({root2: r2}, [rec]), "r#TD-001")["answered"] is None, "past BOARD_WAIT_DAYS"
    # a lift leaves it unheld
    root3, r3 = _setup(tmp_path / "l", [held], _closed("TD-001", "lifted"))
    rec.repo = rec.dir = root3
    assert _row(_read({root3: r3}, [rec]), "r#TD-001")["answered"] is None


@pytest.mark.unit
def test_one_line_answers_the_newest_and_on_a_tie_an_open_line_before_a_closed_one(tmp_path):
    held = _entry(1, "the held one", **HELD)
    rnd = _entry(5, "the round", Priority="High", Added="2026-10-15")
    # a Lift the hold's `go ahead` line and an older-closed carried line on the same `Decided:` date: the open one
    root, r = _setup(
        tmp_path, [held, rnd], _closed("TD-001", "carried to TD-005"), _open("TD-001", decided="go ahead (2026-10-15)")
    )
    assert _row(_read({root: r}), "r#TD-001")["state"] == "answered — waiting on a pick"
    # a newest line whose test has ended returns the need, though an older line would hold
    root2, r2 = _setup(tmp_path / "n", [held, rnd], _closed("TD-001", "carried to TD-005", decided="Go (2026-10-12)"),
                       _closed("TD-001", "", decided="Go (2026-10-15)"))  # fmt: skip
    assert _row(_read({root2: r2}), "r#TD-001")["answered"] is None
    # the `at` tie-break: the nearer-the-top of two otherwise equal closed lines
    a = _closed("TD-001", "carried to TD-005")
    b = _closed("TD-001", "", decided="Again (2026-10-15)")
    root3, r3 = _setup(tmp_path / "t", [held, rnd], a, b)
    assert _row(_read({root3: r3}), "r#TD-001")["state"] == "answered — waiting on TD-005"
    root4, r4 = _setup(tmp_path / "u", [held, rnd], b, a)
    assert _row(_read({root4: r4}), "r#TD-001")["answered"] is None


@pytest.mark.unit
def test_a_kept_waiting_close_reads_waits_until_its_reask_and_needs_the_person_without_a_log_date(tmp_path):
    log = '\n**Log:**\n- 2026-10-10: kept waiting: decision (paul) — by paul; answer "Not yet"\n'
    held = _entry(1, "the held one", **HELD) + log
    root, r = _setup(
        tmp_path, [held], _closed("TD-001", "kept waiting", decided="Not yet (2026-10-10)", closed="2026-10-10")
    )
    row = _row(_read({root: r}), "r#TD-001")
    assert row["state"] == "waits until 2026-11-09" and row["answered"]["until"] == "2026-11-09"
    assert "asker" not in row["answered"]
    assert _by_id(_read({root: r}))["r#TD-001"]["status"] != "needs you"
    waited = _closed("TD-001", "kept waiting", decided="Not yet (2026-10-10)", closed="2026-10-10")
    root2, r2 = _setup(tmp_path / "n", [_entry(1, "the held one", **HELD)], waited)
    assert _row(_read({root2: r2}), "r#TD-001")["answered"] is None
    # the re-ask's date passed: the person's again
    old = '\n**Log:**\n- 2026-09-01: kept waiting: decision (paul) — by paul; answer "Not yet"\n'
    waited = _closed("TD-001", "kept waiting", decided="Not yet (2026-09-01)", closed="2026-09-01")
    root3, r3 = _setup(tmp_path / "o", [_entry(1, "the held one", **HELD) + old], waited)
    assert _row(_read({root3: r3}), "r#TD-001")["answered"] is None


@pytest.mark.unit
def test_a_mail_question_that_holds_wins_over_a_board_line(tmp_path):
    root, r = _setup(tmp_path, [_entry(1, "the held one", **HELD)], _open("TD-001"))
    row = _row(_read({root: r}, [_asker()], [_q()]), "r#TD-001")
    assert row["answered"]["kind"] == "ask" and row["state"] == "answered — waiting on designer"


@pytest.mark.unit
def test_answered_hold_reads_no_board_where_its_caller_passes_none(tmp_path):
    """The Inbox's call passes no boards until its slice: the mail half alone, as before."""
    root, r = _setup(tmp_path, [_entry(1, "the held one", **HELD)], _open("TD-001"))
    (e,) = [{**x, "repo": "r"} for x in r["ledger"]["entries"]]
    assert queue.answered_hold(e, [], {}, {"r#TD-001": "r#TD-001"}, NOW) is None
    got = queue.answered_hold(e, [], {}, {"r#TD-001": "r#TD-001"}, NOW, boards={"r": r["boards"]["boards"]})
    assert got is not None and got["asker"] == "a pick"
    assert ledger.decided_by(e, "paul")


@pytest.mark.unit
def test_the_orders_holder_names_the_wait_before_a_covered_members_holder(tmp_path):
    root, r = _setup(tmp_path, [_entry(1, "the held one", **HELD)], _open("TD-001"))
    key = r["boards"]["boards"][0]["items"][0]["key"]
    member, order = _worker("ao-r-alpha", "TD-001"), _worker("ao-r-zulu", key)
    for rec in (member, order):
        rec.repo = rec.dir = root
    assert _row(_read({root: r}, [member, order]), "r#TD-001")["state"] == "answered — waiting on zulu"
