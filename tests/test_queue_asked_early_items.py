"""TD-2184 slice 3, design §4.4 *A question whose entry only waits is asked early* (TD-2172), §4.5 screen 12 *A question
asked early is no want while its entry waits*: an open undecided line all of whose covered members are asked early is
drawn early in their place — grey on its card, its whole bar under its press line, counted in no **Needs you (n)**, top
bar or rail — and so is an open `ask --lift` on an early entry; a Start session's prompt says the id is asked early;
and the item's edge, and its card's, are amber on a Waiting card and its own edge grey on any other."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from markupsafe import Markup
from test_queue import NOW, _entry
from test_queue_asked_early import LATER, _gated, _one
from test_queue_covers_once import ENTRIES, index, line
from test_queue_item_shape import card

from shiftlead.ui.app import ledger_for_you
from shiftlead.ui.inbox import inbox_sections
from shiftlead.ui.queue import (
    answered_case,
    asked_once,
    attach,
    card_edge,
    card_wants,
    item_home,
    items_n,
    line_early,
    line_then_yours,
    mail_early,
)

EARLY = "once TD-060 closes"


def _early(*ns: int, line_of: str = EARLY) -> dict:
    """`ENTRIES` with each of `ns` asked early, as `ledger_for_you`'s `entries` carries it."""
    return {**ENTRIES, **{f"r#TD-{n:03d}": {**ENTRIES[f"r#TD-{n:03d}"], "early_line": line_of} for n in ns}}


def drawn(e, sec):
    return Markup(e.get("key") or e.get("row_id") or e.get("id"))


def _lift_ask(**kw) -> dict:
    return {"id": "m-9", "kind": "ask", "from": "ao-r-designer", "to": ["person"], "about": "TD-051",
            "text": "Go with the design?", "lift": ["Go"], "answers": ["Go — a session builds it", "Not yet"],
            "repo": "r", **kw}  # fmt: skip


@pytest.mark.unit
def test_a_line_covering_only_early_members_is_early_and_one_covering_a_need_is_a_need():
    every = _early(50, 51, 52, 53, 54)
    assert line_early(line(), every) == EARLY
    assert line_early(line(), _early(51, 52, 53, 54)) is None, "TD-050 is asked as any: the line is a need"
    fact = {**every, "r#TD-052": {**every["r#TD-052"], "open_work": ["r#TD-055"]}}
    assert line_early(line(), fact) is None and line_then_yours(line(), fact) == ["r#TD-055"], "the fact stays grey"
    assert line_early({**line(), "decided": {"text": "Go"}}, every) is None
    assert line_early({**line(), "kind": "act"}, every) is None
    assert line_early(line(), None) is None


@pytest.mark.unit
def test_an_early_line_is_grey_on_its_card_on_no_pill_and_counts_for_the_header():
    idx = index(("r#TD-050", [50, 51, 52]))
    home = item_home(line(), idx, entries=_early(50, 51, 52, 53, 54))
    assert home["early"] and home["early_line"] == EARLY and "then_yours" not in home
    placed = {**line(), **home}
    assert answered_case(placed) == "early"
    got = attach({"needs": [placed]}, drawn, [], lambda c, ref, on: {"repo": "r", "ref": ref})
    items = got["cards"]["r#TD-050"]["needs"]
    assert [(m["html"], m["want"]) for m in items] == [("board:k1", "answered")]
    assert items[0]["early"] and items[0]["starts"]
    w = card_wants({"needs": items}, "r#TD-050", True)
    assert not w["n"]["decide"] and w["n"]["early"] == 1 and items_n(w) == 1


@pytest.mark.unit
def test_an_open_lifting_ask_on_an_early_entry_is_drawn_early():
    work = _early(51)
    assert mail_early(_lift_ask(), {}, work) == EARLY
    assert mail_early(_lift_ask(lift=None), {}, work) is None, "an ask that lifts nothing is asked as any"
    assert mail_early(_lift_ask(about="TD-052"), {}, work) is None, "its entry is not early"
    assert mail_early(_lift_ask(closed_reason="replied"), {}, work) is None, "answered already"
    home = item_home(_lift_ask(), index(("r#TD-050", [50, 51])), entries=work)
    assert (home["on_row"], home["early"], home["early_line"]) == ("r#TD-051", True, EARLY)
    got = attach({"needs": [{**_lift_ask(), **home}]}, drawn, [])["cards"]["r#TD-050"]["needs"]
    assert [(m["want"], m.get("early")) for m in got] == [("answered", True)]
    html = card({**_lift_ask(), **home}, "answered")
    assert f'<div class="qpress qp-idle qearly" role="status">Asked early: your answer acts {EARLY}.</div>' in html
    assert "Go — a session builds it" in html, "its answers drawn whole"


@pytest.mark.unit
def test_the_early_line_draws_its_press_line_above_its_whole_bar():
    e = {**line(), "text": "Go with the design?", "answers": ["Go", "Not yet"], "board": "docs/user_attention/"}
    html = card({**e, "early": True, "early_line": EARLY}, "answered")
    assert f'<div class="qpress qp-idle qearly" role="status">Asked early: your answer acts {EARLY}.</div>' in html
    assert "Not yet" in html and "Answer…" in html, "its answers and Answer… drawn"
    assert "qearly" not in card(e, "decide"), "a line asked as any draws no early line"


@pytest.mark.unit
def test_the_inbox_counts_leave_an_early_line_out():
    now = datetime(2026, 11, 25, 12, tzinfo=UTC)
    idx = index(("r#TD-050", [50, 51, 52]))
    row = {**line(), "text": "Go with the design?", "answers": ["Go", "Not yet"], "due": "2026-11-20"}
    early = inbox_sections([], now=now, boards=[row], cards=idx, entries_open=_early(50, 51, 52, 53, 54))
    asked = inbox_sections([], now=now, boards=[row], cards=idx, entries_open=ENTRIES)
    assert [e.get("early") for e in early["needs"]] == [True], "still listed, so its card draws it"
    assert (early["count"], early["queue_n"]) == (0, 0)
    assert (asked["count"], asked["queue_n"]) == (1, 1)


@pytest.mark.unit
def test_ledger_for_you_hands_each_early_members_line_to_its_covering_line(tmp_path):
    root, r = _one(
        tmp_path,
        _gated(1, "the question", "TD-002"),
        _entry(2, "dated", Priority="High", Blocked_by=f"until {LATER}"),
        _gated(3, "asked as any"),
    )
    entries = ledger_for_you({root: r}, [], {}, now=NOW)["entries"]
    assert entries["r#TD-001"]["early_line"] == "once TD-002 closes" and entries["r#TD-003"]["early_line"] == ""
    board = {"row": "board", "kind": "decide", "repo_name": "r", "context": "TD-001"}
    assert line_early(board, entries) == "once TD-002 closes"
    assert line_early({**board, "context": "TD-001, TD-003"}, entries) is None


@pytest.mark.unit
def test_a_start_sessions_prompt_says_the_id_is_asked_early():
    c = {"top": {"qid": "r#TD-001", "early": True, "early_line": "once TD-002 closes"}, "rows": [{"qid": "r#TD-003"}]}
    assert asked_once(["r#TD-001", "r#TD-003"], c) == [
        "r#TD-001 — asked early; it acts once TD-002 closes",
        "r#TD-003",
    ]


@pytest.mark.unit
def test_a_waiting_card_holding_an_early_item_has_an_amber_edge():
    early = {"n": {"decide": 0, "do": 0, "early": 1}}
    assert card_edge("waiting", "waiting", early) == "needs"
    assert card_edge("waiting", "waiting", {"n": {}}) == "waiting"
    assert card_edge("in_progress", "", early) == "working", "In progress takes nothing from it"
    assert card_edge("up_next", "", early) == "ended"


@pytest.mark.unit
def test_the_early_press_line_is_grey_and_amber_on_a_waiting_card():
    from pathlib import Path

    import shiftlead.ui as ui

    css = (Path(ui.__file__).parent / "static" / "app.css").read_text()
    assert ".qpress.qearly { border-left-color: var(--muted); }" in css
    assert ".qcard.g-waiting .qpress.qearly { border-left-color: var(--needs); }" in css
