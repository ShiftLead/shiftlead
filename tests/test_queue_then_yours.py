"""TD-1949 (TD-1926's reading half), design §4.4 *The card's status*, *A `decision (paul)` member that still waits on
open work is no need*: a held member with counted open work — an open id in its `Blocked by:` or an open entry
`Part of` it, less the person's own and less work that waits on the member itself — reads *waiting, then yours*
where no earlier word stands, keeps its `needs`, draws no Lift, gives its card no *needs you*, is left out of the
counts, and the home refuses an answer or a lift on it."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_queue import NOW, _entry, _repo
from test_queue_board_hold import HELD, _open, _read, _row
from test_queue_lift_here import _setup

from sessionorc import queue, settle
from sessionorc.agent_common import RpcError
from sessionorc.agent_inbox import InboxMixin
from shiftlead.ui.app import ledger_for_you
from shiftlead.ui.inbox import ledger_rows, rail_rows, row_find
from shiftlead.ui.queue import _seg, asked_once, branch, line_then_yours

PART = {"Priority": "High", "Part_of": "TD-001"}
WORD = "waiting, then yours"


def _card(q: dict, ref: str) -> dict:
    return next(c for c in q["cards"] if ref in [c["top"]["qid"], *(r["qid"] for r in c["rows"])])


def _one(tmp_path, *entries, archive=(), name="r") -> tuple[str, dict]:
    return _repo(tmp_path, name, list(entries), list(archive))


@pytest.mark.unit
def test_a_design_whose_only_open_parts_carry_the_gate_still_needs_the_person(tmp_path):
    root, r = _one(
        tmp_path, _entry(1, "the design", **HELD), _entry(2, "a held build", **PART, Blocked_by="decision (paul)")
    )
    q = _read({root: r})
    row = _row(q, "r#TD-001")
    assert row["state"] == "" and row["needs"] == "decision" and not row["then_yours"] and row["open_work"] == []
    assert _card(q, "r#TD-001")["status"] == "needs you"
    assert queue._own(r["ledger"]["entries"][0] | {"open_work": []})


@pytest.mark.unit
def test_a_design_with_an_open_round_part_reads_the_word_keeps_its_need_and_has_no_lift(tmp_path):
    root, r = _one(tmp_path, _entry(1, "the design", **HELD), _entry(2, "the round", **PART))
    q = _read({root: r})
    row, c = _row(q, "r#TD-001"), _card(q, "r#TD-001")
    assert row["state"] == WORD and row["needs"] == "decision" and row["then_yours"] == ["r#TD-002"]
    assert row["lift_here"] is False and c["status"] != "needs you"
    assert "r#TD-001" in queue.card_entries(c)[0], "*waits on me* still names it"
    assert asked_once(["r#TD-001"], c) == ["r#TD-001 — asked once r#TD-002 closes"]
    # the tree draws it teal, its segment titled with its word
    assert branch(row) == "waiting" and _seg({**row, "show": "TD-001"})["title"] == f"TD-001: {WORD}"
    # the word ends once the last counted id archives
    root, r = _one(tmp_path / "b", _entry(1, "the design", **HELD), archive=[_entry(2, "the round", **PART)])
    assert _row(_read({root: r}), "r#TD-001")["state"] == ""


@pytest.mark.unit
def test_an_answered_member_with_open_work_keeps_its_word_and_draws_no_lift(tmp_path):
    root, r = _setup(tmp_path, [_entry(1, "the design", **HELD), _entry(2, "the round", **PART)], _open("TD-001"))
    row = _row(_read({root: r}), "r#TD-001")
    assert row["state"] == "answered — waiting on a pick" and row["lift_here"] is False
    assert row["open_work"] == ["r#TD-002"] and not row["then_yours"]


@pytest.mark.unit
def test_a_lone_marked_member_waits_with_its_blocker(tmp_path):
    dated = _entry(2, "dated", Priority="High", Blocked_by="until 2026-12-01")
    root, r = _one(tmp_path, _entry(1, "held", Priority="High", Blocked_by="TD-002, decision (paul)"), dated)
    settle.mark_waits(r["ledger"]["entries"], NOW)  # the gates marked as the home marks them
    c = _card(_read({root: r}), "r#TD-001")
    assert c["status"] == "waiting" and c["wait"] is not None
    root, r = _one(tmp_path / "b", _entry(1, "held", Priority="High", Blocked_by="TD-002, decision (paul)"),
                   _entry(2, "in progress", Priority="High"))  # fmt: skip
    c = _card(_read({root: r}), "r#TD-001")
    assert _row(_read({root: r}), "r#TD-001")["state"] == WORD
    assert c["status"] == "ready" and c["wait"] is None


@pytest.mark.unit
def test_a_cross_repo_open_blocker_counts_and_an_unresolved_one_does_not(tmp_path):
    a, ra = _one(tmp_path, _entry(1, "held", Priority="High", Blocked_by="s#TD-005, decision (paul)"), name="r")
    b, rb = _one(tmp_path, _entry(5, "theirs", Priority="High"), name="s")
    assert _row(_read({a: ra, b: rb}), "r#TD-001")["then_yours"] == ["s#TD-005"]
    a, ra = _one(tmp_path / "x", _entry(1, "held", Priority="High", Blocked_by="zz#TD-009, decision (paul)"))
    row = _row(_read({a: ra}), "r#TD-001")
    assert row["state"] == "" and not row["then_yours"]


@pytest.mark.unit
def test_work_that_waits_on_the_member_itself_is_not_counted(tmp_path):
    root, r = _one(
        tmp_path,
        _entry(1, "the design", **HELD),
        _entry(2, "a part", **PART, Blocked_by="TD-003"),
        _entry(3, "waits on the design", Priority="High", Blocked_by="TD-001"),
    )
    row = _row(_read({root: r}), "r#TD-001")
    assert row["state"] == "" and row["needs"] == "decision" and row["open_work"] == []


@pytest.mark.unit
def test_the_inbox_row_carries_the_mark_and_the_counts_leave_it_out(tmp_path):
    root, r = _one(tmp_path, _entry(1, "the design", **HELD), _entry(2, "the round", **PART),
                   _entry(3, "plain held", **HELD))  # fmt: skip
    lf = ledger_for_you({root: r}, [], {})
    rows = {x["id"]: x for g in lf["groups"] for x in g["rows"]}
    assert rows["TD-001"]["then_yours"] == ["r#TD-002"] and rows["TD-001"]["lift_item"] is False
    assert not rows["TD-003"]["then_yours"] and rows["TD-003"]["lift_item"] is True
    assert lf["n"] == 1 and lf["groups"][0]["n"] == 1, "the row stays in the list, counted nowhere"
    assert [x["id"] for x in ledger_rows(lf)] == ["TD-001", "TD-003"], "the Repo page still lists it for you"
    assert [x["find"] for x in rail_rows({}, (), ledger_rows(lf))] == [row_find(rows["TD-003"], "later")]
    assert lf["entries"]["r#TD-001"]["open_work"] == ["r#TD-002"]


@pytest.mark.unit
def test_an_undecided_line_covering_a_marked_member_carries_then_yours(tmp_path):
    root, r = _one(tmp_path, _entry(1, "the design", **HELD), _entry(2, "the round", **PART),
                   _entry(3, "plain held", **HELD))  # fmt: skip
    entries = ledger_for_you({root: r}, [], {})["entries"]
    line = {"row": "board", "kind": "decide", "repo_name": "r", "context": "TD-001"}
    assert line_then_yours(line, entries) == ["r#TD-002"]
    mixed = {**line, "context": "TD-001, TD-003"}
    assert line_then_yours(mixed, entries) == ["r#TD-002"], "a marked and an unmarked member: marked"
    assert line_then_yours({**line, "context": "TD-003"}, entries) is None
    assert line_then_yours({**line, "decided": {"text": "Go"}}, entries) is None


def _home(repos: dict) -> SimpleNamespace:
    fake = SimpleNamespace(_repos=repos)
    fake._open_work = lambda: InboxMixin._open_work(fake)
    return fake


@pytest.mark.unit
def test_the_home_refuses_a_press_on_a_member_with_the_fact(tmp_path):
    root, r = _setup(tmp_path, [_entry(1, "the design", **HELD), _entry(2, "the round", **PART),
                                _entry(3, "plain held", **HELD)], _open("TD-001, TD-003", decided=None))  # fmt: skip
    home = _home({root: r})
    with pytest.raises(RpcError, match="TD-001 waits on TD-002: it is asked once that closes"):
        InboxMixin._refuse_waiting(home, ["r#TD-001"])
    InboxMixin._refuse_waiting(home, ["r#TD-003"])  # no fact: nothing refused
    key = r["boards"]["boards"][0]["items"][0]["key"]
    covered = InboxMixin._line_covers(home, root, key, "")
    assert covered == ["r#TD-001", "r#TD-003"]
    with pytest.raises(RpcError, match="waits on TD-002"):
        InboxMixin._refuse_waiting(home, covered)


@pytest.mark.unit
def test_a_marked_top_entry_draws_its_word_in_the_card_header(tmp_path):
    from shiftlead.ui.app import templates
    from shiftlead.ui.queue import queue_view

    root, r = _one(tmp_path, _entry(1, "the design", **HELD), _entry(2, "the round", **PART))
    view = queue_view(_read({root: r}), NOW)
    c = next(c for g in ("in_progress", "waiting", "up_next") for c in view.get(g) or () if c["id"] == "r#TD-001")
    html = str(templates.env.get_template("queue_card.html").module.card(c))
    head = html[: html.index('data-qid="r#TD-002"')]
    assert WORD in head and "needsyou" not in head
