"""TD-1660 slice 4 (TD-1543's build), design §4.5 screen 12 *Three verbs: Have a session do it*: an entry a handed
ask's `refs` name, that waits on the person and is not *with you*, is drawn grey *handed to <seat> · <age>* — on its
Queue card, in the Inbox's Later and on the Repo page, uncounted, with no answers, Answer… or Start session, its ⋯
keeping the entry's own answer — while the ask is open: no outcome, for fewer than `BOARD_WAIT_DAYS` civil days, or
a `blocked` one with no day bound (TD-1556). A mail or board answer wins; an open undecided `decide` line covering
the entry asks again (`covered_by_open_line`, the test `board_hold` makes, extracted)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_queue import NOW, _entry, _rec
from test_queue_board_hold import HELD, _board, _open, _read, _row, _setup

from sessionorc import queue
from sessionorc.agent_mail import handed_list
from sessionorc.models import MailEntry

SENT = NOW - timedelta(hours=5)


def _handed(*refs: str, at=SENT, outcome=None, holder="ao-other-techlead", **kw) -> dict:
    """The person's handed ask as the `inbox` read lists it (`handed_list`): the holder's copy with its `entry`."""
    e = {
        "id": "m-h1",
        "from": "person",
        "kind": "ask",
        "handed": True,
        "at": at.isoformat(),
        "outcome": outcome,
        "entry": {"refs": list(refs), "key": "r:board:0123abcd", "doer": "other", "handed_at": at.isoformat()},
        "holder": holder,
        "holder_name": "techlead",
        "holder_state": "idle",
    }
    return {**e, **kw}


def _seat(rid: str = "ao-other-techlead"):
    s = _rec(rid, "/elsewhere")
    s.name = "techlead"
    return s


def _q(tmp_path, handed, *board, records=(), entries=None):
    root, r = _setup(tmp_path, entries or [_entry(1, "held", **HELD)], *board)
    return (
        _read({root: r}, [_seat(), *records])
        if not handed
        else queue.reading({root: r}, [_seat(), *records], NOW, handed=handed, archived={})
    )


@pytest.mark.unit
def test_a_handed_ask_draws_its_entry_handed_to_the_seat(tmp_path):
    row = _row(_q(tmp_path, [_handed("r#TD-001")]), "r#TD-001")
    assert row["state"] == "handed to techlead" and row["needs"] == "decision"
    a = row["answered"]
    assert a["kind"] == "handed" and a["mid"] == "m-h1" and a["asker"] == "ao-other-techlead"
    assert a["closed_at"] == SENT.isoformat() and a["outcome"] is None
    # an ask naming another entry, or none, leaves it the person's
    assert _row(_q(tmp_path / "b", [_handed("r#TD-002")]), "r#TD-001")["answered"] is None
    assert _row(_q(tmp_path / "c", []), "r#TD-001")["answered"] is None


@pytest.mark.unit
def test_an_outcome_ends_the_cover_save_blocked_which_has_no_day_bound(tmp_path):
    done = {"state": "done", "text": "filed", "at": NOW.isoformat()}
    assert _row(_q(tmp_path, [_handed("r#TD-001", outcome=done)]), "r#TD-001")["answered"] is None
    old = NOW - timedelta(days=queue.BOARD_WAIT_DAYS + 2)
    blocked = {"state": "blocked", "text": "needs your login", "at": NOW.isoformat()}
    a = _row(_q(tmp_path / "b", [_handed("r#TD-001", at=old, outcome=blocked)]), "r#TD-001")["answered"]
    assert a["kind"] == "handed" and a["outcome"] == blocked, "a blocked ask's cover stands past the bound"


@pytest.mark.unit
def test_with_no_outcome_the_cover_ends_after_board_wait_days_civil_days(tmp_path):
    inside = NOW - timedelta(days=queue.BOARD_WAIT_DAYS - 1)
    assert _row(_q(tmp_path, [_handed("r#TD-001", at=inside)]), "r#TD-001")["answered"]["kind"] == "handed"
    past = NOW - timedelta(days=queue.BOARD_WAIT_DAYS)
    row = _row(_q(tmp_path / "b", [_handed("r#TD-001", at=past)]), "r#TD-001")
    assert row["answered"] is None and row["state"] == "", "it comes back counted"


@pytest.mark.unit
def test_a_rerouted_copy_is_skipped(tmp_path):
    row = _row(_q(tmp_path, [_handed("r#TD-001", closed_reason="rerouted")]), "r#TD-001")
    assert row["answered"] is None


@pytest.mark.unit
def test_an_open_undecided_decide_line_covering_the_entry_asks_again(tmp_path):
    row = _row(_q(tmp_path, [_handed("r#TD-001")], _open("TD-001", decided=None)), "r#TD-001")
    assert row["answered"] is None and row["state"] == ""


@pytest.mark.unit
def test_a_board_answer_wins_over_the_handed_cover(tmp_path):
    row = _row(_q(tmp_path, [_handed("r#TD-001")], _open("TD-001")), "r#TD-001")
    assert row["answered"]["kind"] == "board"


@pytest.mark.unit
def test_an_entry_with_you_or_needing_nothing_keeps_its_own_word(tmp_path):
    mine = _rec("ao-r-mine", "/x", "TD-001")
    mine.name, mine.unattended = "mine", False
    root, r = _setup(tmp_path, [_entry(1, "held", **HELD)])
    mine.repo = mine.dir = root
    row = _row(queue.reading({root: r}, [_seat(), mine], NOW, handed=[_handed("r#TD-001")], archived={}), "r#TD-001")
    assert row["state"] == "with you in mine" and row["answered"] is None
    free = _row(_q(tmp_path / "b", [_handed("r#TD-001")], entries=[_entry(1, "free", Priority="High")]), "r#TD-001")
    assert free["answered"] is None and free["needs"] is None


@pytest.mark.unit
def test_covered_by_open_line_reads_the_member_and_its_parent(tmp_path):
    root, r = _setup(
        tmp_path,
        [_entry(1, "design", Priority="High"), _entry(2, "build", Part_of="TD-001", **HELD)],
        _open("TD-001", decided=None),
    )
    lines = queue._board_lines({"r": r["boards"]["boards"]})
    linked = {"r#TD-001": "r#TD-001", "r#TD-002": "r#TD-002"}
    assert queue.covered_by_open_line({"repo": "r", "id": "TD-001"}, lines, linked)
    assert queue.covered_by_open_line({"repo": "r", "id": "TD-002", "part_of": "TD-001"}, lines, linked)
    assert not queue.covered_by_open_line({"repo": "r", "id": "TD-003"}, lines, linked)
    decided = queue._board_lines({"r": _board(root, _open("TD-001"))["boards"]})
    assert not queue.covered_by_open_line({"repo": "r", "id": "TD-001"}, decided, linked), "a decided line answers"


@pytest.mark.unit
def test_handed_list_is_the_inbox_reads_open_and_blocked_handed_asks():
    def ask(mid, **kw):
        at = NOW.isoformat()
        return MailEntry(id=mid, from_="person", to=["ao-x"], kind="ask", text="t", at=at, handed=True, **kw)

    rec = SimpleNamespace(
        name="x",
        state="idle",
        inbox=[
            ask("m-1"),
            ask("m-2", outcome={"state": "blocked", "text": "no"}),
            ask("m-3", outcome={"state": "done", "text": "ok"}),
            ask("m-4", closed_reason="rerouted"),
            MailEntry(id="m-5", from_="ao-y", to=["ao-x"], kind="ask", text="t", at=NOW.isoformat()),
        ],
    )
    got = handed_list({"ao-x": rec})
    assert [g["id"] for g in got] == ["m-1", "m-2"]
    assert got[0]["holder"] == "ao-x" and got[0]["holder_name"] == "x" and got[0]["holder_state"] == "idle"


# -- the page: the Inbox's Later, the Repo page, a card ------------------------------------------------------------


def _ui_repos(tmp_path, owner=False) -> dict:
    root = tmp_path / "r"
    led = {
        "for_page": "for-you",
        "priority": "medium",
        "id": "TD-60",
        "title": "held",
        "blocked_by": ["decision (paul)"],
        **({"owner": "paul"} if owner else {}),
        "answers": ["Yes", "No"],
        "default": 0,
    }
    return {str(root): {"name": "r", "root": str(root), "ledger": {"path": "docs/ledger", "entries": [led]}}}


FLEET = [{"id": "ao-other-techlead", "name": "techlead", "state": "idle", "repo": "/x/other"}]


def _rows(repos, handed, fleet=FLEET):
    from shiftlead.ui.inbox import ledger_for_you

    got = ledger_for_you(repos, fleet, {}, NOW, [], handed=handed)
    return [r for g in got["groups"] for r in g["rows"]]


def _render(row, mode=None, home=None) -> str:
    from shiftlead.ui.app import templates

    e = {**row, **({"home": home} if home else {})}
    if mode == "card":
        e["want"] = "answered"
        return templates.get_template("queue_mail.html").render(e=e, section="needs")
    return templates.env.get_template("inbox_row.html").module.row(e, "later")


@pytest.mark.unit
def test_ledger_for_you_draws_the_handed_row_grey_with_lift_the_hold_in_its_dots(tmp_path):
    (row,) = _rows(_ui_repos(tmp_path), [_handed("r#TD-60")])
    a = row["answered"]
    assert a["kind"] == "handed" and a["name"] == "techlead" and a["age"] == "5h 0m" and a["mid"] == "m-h1"
    html = _render(row)
    assert '<span class="st qans">handed to techlead · 5h 0m</span>' in html
    assert "you handed this step on to techlead — its outcome ends this hold" in html
    assert "its answers" not in html and ">Reply<" not in html and ">Start session<" not in html
    dots = html.split('class="more qdots"')[1]
    assert ">Lift the hold</button>" in dots and ">Open</a>" in dots and ">Done</button>" not in dots
    assert _rows(_ui_repos(tmp_path), [])[0]["answered"] is None


@pytest.mark.unit
def test_an_owner_paul_row_is_covered_too_and_keeps_done_in_its_dots(tmp_path):
    (row,) = _rows(_ui_repos(tmp_path, owner=True), [_handed("r#TD-60")])
    assert row["answered"]["kind"] == "handed"
    dots = _render(row).split('class="more qdots"')[1]
    assert ">Done</button>" in dots and 'data-words="done"' in dots and ">Lift the hold<" not in dots


@pytest.mark.unit
def test_a_blocked_handed_row_says_why(tmp_path):
    blocked = {"state": "blocked", "text": "needs your login", "at": NOW.isoformat()}
    (row,) = _rows(_ui_repos(tmp_path), [_handed("r#TD-60", outcome=blocked)])
    assert "techlead could not do it: needs your login" in _render(row)


@pytest.mark.unit
def test_the_persons_own_session_on_the_entry_keeps_it_with_you(tmp_path):
    repos = _ui_repos(tmp_path)
    root = next(iter(repos))
    mine = {"id": "ao-r-mine", "name": "mine", "state": "idle", "repo": root, "unattended": False,
            "progress": [{"ref": "TD-60", "status": "claimed", "at": NOW.isoformat()}]}  # fmt: skip
    (row,) = _rows(repos, [_handed("r#TD-60")], [*FLEET, mine])
    assert row["answered"] is None


@pytest.mark.unit
def test_on_a_card_the_handed_item_is_grey_with_its_answer_in_its_dots(tmp_path):
    (row,) = _rows(_ui_repos(tmp_path), [_handed("r#TD-60")])
    html = _render(row, mode="card", home="queue")
    assert "handed to techlead" in html and "Answer…" not in html and ">Start session<" not in html
    assert html.count(">Lift the hold<") == 1
