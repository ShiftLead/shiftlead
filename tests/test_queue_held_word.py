"""TD-2026 slice 3, design §4.4 *A design's question is asked once, on the design* (TD-2021), the Fix's step 2: a held
build reads *waits on TD-<design>'s question*, teal, in place of *your decision* and a covering line's answer, yielding
to a press's mark; it is no need — no item on the Queue, no answers, Lift or count on the Inbox and the Repo page, out
of *Later* — never makes its card wait or block, counts as the person's own member in `_wait`, is passed over by
Start session, and its Start session line ends *— asked on TD-<design>'s question*."""

from __future__ import annotations

import pytest
from markupsafe import escape
from test_queue import NOW, _entry
from test_queue_board_hold import HELD, _open, _read, _row
from test_queue_lift_here import _setup

from sessionorc import queue
from shiftlead.ui.app import ledger_for_you
from shiftlead.ui.inbox import rail_rows
from shiftlead.ui.queue import _seg, asked_once, branch

PART = {"Priority": "High", "Part_of": "TD-001", "Blocked_by": "decision (paul)"}
WORD = "waits on TD-001's question"


def _ask(parts: str) -> str:
    return _open("TD-001 decision (paul)", decided=None, parts=parts)


def _card(q: dict, ref: str) -> dict:
    return next(c for c in q["cards"] if ref in [c["top"]["qid"], *(r["qid"] for r in c["rows"])])


def _design_and_build(tmp_path, *more, line="TD-002"):
    entries = [_entry(1, "the design", **HELD), _entry(2, "build a", **PART), *more]
    return _setup(tmp_path, entries, _ask(line))


@pytest.mark.unit
def test_a_held_build_reads_its_designs_question_teal_with_no_need(tmp_path):
    root, r = _design_and_build(tmp_path)
    q = _read({root: r})
    row = _row(q, "r#TD-002")
    assert row["state"] == WORD and row["held_by"] == "r#TD-001"
    assert row["then_yours"] is None and row["lift_here"] is False and row["needs"] == "decision"
    assert branch(row) == "waiting" and _seg(row)["title"].endswith(WORD)
    assert "held_by" not in _row(q, "r#TD-001"), "the design reads its own word"
    # with no Parts the build reads its own hold, as before
    root, r = _design_and_build(tmp_path / "b", line="")
    assert "held_by" not in _row(_read({root: r}), "r#TD-002")


@pytest.mark.unit
def test_a_held_build_yields_to_a_press_mark_in_the_reading_and_held_back(tmp_path):
    root, r = _design_and_build(tmp_path)
    before = _read({root: r})
    marked = queue.lay_applying(r, {"ledger:r#TD-002": {"t": {"act": "decide", "at": "x"}}}, "r")
    row = _row(_read({root: marked}), "r#TD-002")
    assert "held_by" not in row and row["state"] != WORD
    held = _row(queue.lay_held(before, {root: marked}), "r#TD-002")
    assert "held_by" not in held and held["state"] != WORD


@pytest.mark.unit
def test_the_rendered_row_is_teal_with_no_needsyou(tmp_path):
    from shiftlead.ui.app import templates
    from shiftlead.ui.queue import queue_view

    root, r = _design_and_build(tmp_path)
    view = queue_view(_read({root: r}), NOW)
    c = next(c for g in ("in_progress", "waiting", "up_next") for c in view.get(g) or () if c["id"] == "r#TD-001")
    html = str(templates.env.get_template("queue_card.html").module.card(c))
    at = html.index('data-qid="r#TD-002"')
    row = html[html.rindex("<div", 0, at) : html.index("</div>", at)]
    assert "needsyou" not in row
    assert f'<span class="qstate s-waiting">{escape(WORD)}</span>' in html[at:]


@pytest.mark.unit
def test_status_wait_and_start_pass_over_a_held_build():
    design = {"id": "TD-001", "repo": "r", "blocked_by": ["decision (paul)"], "for_page": "for-you"}
    build = {"id": "TD-002", "repo": "r", "blocked_by": ["decision (paul)"], "for_page": "for-you",
             "held_by": "r#TD-001", "no_lane": True, "open_work": ["r#TD-003"]}  # fmt: skip
    held_row = {"qid": "r#TD-002", "needs": "decision", "state": WORD, "held_by": "r#TD-001"}
    design_row = {"qid": "r#TD-001", "needs": "decision", "state": "your decision"}
    # no lane on the build, its counted work: neither blocks nor waits the card; the design is read
    assert queue._status([held_row], [design, build]) == "ready"
    assert queue._status([design_row, held_row], [design, build]) == "needs you"
    # the build keyed first: Start session opens on the design
    open_ = {"r#TD-001": design, "r#TD-002": build}
    keyed = {"r#TD-001": "0|2", "r#TD-002": "0|1"}
    assert queue._start(["r#TD-002", "r#TD-001"], open_, keyed, "r#TD-002") == "r#TD-001"
    # another member blocked by the held build counts it as the person's own: no wait
    other = {"id": "TD-004", "repo": "r", "blocked_by": ["TD-002"]}
    open_["r#TD-004"] = other
    members = ["r#TD-001", "r#TD-002", "r#TD-004"]
    blockers = {"r#TD-001": set(), "r#TD-002": set(), "r#TD-004": {"r#TD-002"}}
    parts = {m: set() for m in members}
    keyed["r#TD-004"] = "0|4"
    assert queue._wait(members, open_, blockers, parts, keyed, "r#TD-001") is None


@pytest.mark.unit
def test_a_cycle_through_a_held_builds_blocker_and_the_design_is_walked(tmp_path):
    entries = [
        _entry(1, "the design", Priority="High", Blocked_by="TD-004, decision (paul)"),
        _entry(2, "build a", Priority="High", Part_of="TD-001", Blocked_by="TD-004, decision (paul)"),
        _entry(4, "blocked by the design", Priority="High", Blocked_by="TD-001"),
    ]
    root, r = _setup(tmp_path, entries, _ask("TD-002"))
    card = _card(_read({root: r}), "r#TD-001")  # no error
    assert card["status"] in ("needs you", "waiting", "blocked", "ready")


@pytest.mark.unit
def test_the_inbox_and_repo_rows_draw_the_word_with_no_answers_lift_or_count(tmp_path):
    from shiftlead.ui.app import templates

    root, r = _design_and_build(tmp_path)
    got = ledger_for_you({root: r}, [], {}, NOW)
    rows = {x["id"]: x for g in got["groups"] for x in g["rows"]}
    b = rows["TD-002"]
    assert b["held_by"] == "r#TD-001" and b["held_word"] == WORD
    assert b["answers"] == [] and b["lift_item"] is False and b["answered"] is None and b["then_yours"] is None
    assert got["groups"][0]["n"] == sum(1 for x in rows.values() if not x.get("held_by"))
    html = str(templates.env.get_template("ledger_for_you.html").render(lf=got))
    assert 'data-msg="ledger:r:TD-002"' not in html and "ledger:r:TD-002" not in html, "skipped in Later"
    assert not [x for x in rail_rows({}, [], [b]) if x.get("section") == "later"], "out of the rail's Later"


@pytest.mark.unit
def test_start_sessions_line_and_the_queue_item():
    card = {"top": {"qid": "r#TD-001"}, "rows": [{"qid": "r#TD-002", "held_by": "r#TD-001"}]}
    assert asked_once(["r#TD-001", "r#TD-002"], card) == ["r#TD-001", "r#TD-002 — asked on TD-001's question"]
