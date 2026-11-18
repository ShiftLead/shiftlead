"""TD-1950 (TD-1926's drawing half), design §4.5 screen 12 *A press is never left stranded*, §4.5a *Queue card: the
answer bar* and *press line*, §4.4 *The card's status*: a held entry whose question waits on open work, an undecided
line covering one, and an open `ask --lift` on one are drawn as one grey item — its question's words as its head, its
press line *Asked once TD-n closes* in the *Still with a session* tint, its bar **Open** alone — counted for neither the
header nor its walk; the Repo page's *for you* row and the Inbox's *Later* row draw *Asked once TD-n closes* in their
answers' place, with no Lift."""

from __future__ import annotations

import re

import pytest
from markupsafe import Markup
from test_queue_answer_bar import RIGHT, slots
from test_queue_covers_once import ENTRIES, index, ledger_row, line
from test_queue_item_shape import card
from test_queue_then_yours import HELD, PART, _entry, _one

from shiftlead.ui.app import ledger_for_you, templates
from shiftlead.ui.common import asked_once_words
from shiftlead.ui.queue import (
    answered_case,
    attach,
    card_wants,
    item_home,
    items_n,
    mail_then_yours,
    walk_mine,
)

THEN = ["r#TD-002"]
START = {"repo": "r", "ref": "TD-1", "card": "r#TD-001", "item": "r#TD-001"}


def press(html: str) -> str:
    m = re.search(r'<div class="qpress qp-idle qthen" role="status">(.*?)</div>', html, re.S)
    return m.group(1) if m else ""


def _row(tmp_path) -> dict:
    """`ledger_for_you`'s row for TD-001, a held design whose round TD-002 is open (the fact, TD-1949)."""
    root, r = _one(tmp_path, _entry(1, "the design", **HELD), _entry(2, "the round", **PART))
    row = next(x for g in ledger_for_you({root: r}, [], {})["groups"] for x in g["rows"] if x["id"] == "TD-001")
    assert row["then_yours"] == THEN
    return row


def drawn(e, sec):
    return Markup(e.get("key") or e.get("row_id") or e.get("id"))


@pytest.mark.unit
def test_the_words_name_the_first_counted_id_bare_in_its_own_repo():
    assert asked_once_words(["r#TD-002"], "r") == "Asked once TD-002 closes"
    assert asked_once_words(["s#TD-009"], "r") == "Asked once s#TD-009 closes", "another repo's is qualified"
    assert asked_once_words(["r#TD-002", "r#TD-004", "s#TD-1"], "r") == "Asked once TD-002 and 2 more close"
    assert asked_once_words([], "r") == "" and asked_once_words(None, "r") == ""


@pytest.mark.unit
def test_its_grey_kind_comes_after_every_other():
    assert answered_case({"then_yours": THEN}) == "then_yours"
    assert answered_case({"then_yours": THEN, "applying": {"act": "decide"}}) == "applying"
    assert answered_case({"then_yours": THEN, "answered": {"asker": "g"}}) == "waiting"
    assert answered_case({"then_yours": THEN, "answered": {"until": "2026-12-01"}}) == "until"
    assert answered_case({}) == ""


@pytest.mark.unit
def test_a_marked_ledger_item_is_grey_counted_nowhere_and_starts_nothing():
    marked = ledger_row(1, then_yours=THEN)
    plain = ledger_row(3, "r#TD-001")
    started = []

    def start(card_id, ref, on_row):
        started.append(ref)
        return {"repo": "r", "ref": ref}

    got = attach({}, drawn, [marked, plain], start)["cards"]["r#TD-001"]["needs"]
    assert [(m["item"], m["want"], m["kind"]) for m in got] == [
        ("r#TD-001", "answered", ""),
        ("r#TD-003", "decide", got[1]["kind"]),
    ]
    assert started == ["r#TD-003"] and "starts" not in got[0], "no Start session on the grey item"
    w = card_wants({"needs": got}, "r#TD-001", True)
    assert w["n"]["decide"] == 1 and [m["item"] for m in w["answered"]] == ["r#TD-001"]
    assert items_n(w) == 1, "not counted for the header's Start session"
    assert walk_mine(["r#TD-001", "r#TD-003"], w) == ["r#TD-003"], "not in the header's walk"


@pytest.mark.unit
def test_a_covering_line_stands_in_each_covered_entrys_place():
    work = {**ENTRIES, "r#TD-051": {**ENTRIES["r#TD-051"], "open_work": ["r#TD-055"]}}
    idx = index(("r#TD-050", [50, 51, 52]))
    home = item_home(line(), idx, entries=work)
    assert home["then_yours"] == ["r#TD-055"]
    placed = {**line(), **home}
    later = [ledger_row(n, "r#TD-050") for n in (50, 52)] + [ledger_row(51, "r#TD-050", then_yours=["r#TD-055"])]
    got = attach({"needs": [placed]}, drawn, later)["cards"]["r#TD-050"]["needs"]
    assert [(m["html"], m["want"]) for m in got] == [("board:k1", "answered")], "one grey item, nothing beside it"
    # a line covering no marked member is asked as any
    plain = attach({"needs": [{**line(), **item_home(line(), idx, entries=ENTRIES)}]}, drawn, [])
    assert [m["want"] for m in plain["cards"]["r#TD-050"]["needs"]] == ["decide"]


def _lift_ask(**kw) -> dict:
    return {"id": "m-9", "kind": "ask", "from": "ao-r-designer", "to": ["person"], "about": "TD-051",
            "text": "Go with the design?", "lift": ["Go"], "answers": ["Go — a session builds it", "Not yet"],
            "repo": "r", **kw}  # fmt: skip


@pytest.mark.unit
def test_an_open_lifting_ask_on_a_marked_entry_is_grey():
    work = {**ENTRIES, "r#TD-051": {**ENTRIES["r#TD-051"], "open_work": ["r#TD-055"]}}
    assert mail_then_yours(_lift_ask(), {}, work) == ("r", ["r#TD-055"])
    assert mail_then_yours(_lift_ask(lift=None), {}, work) is None, "an ask that lifts nothing is asked as any"
    assert mail_then_yours(_lift_ask(about="TD-052"), {}, work) is None, "its entry has no open work"
    assert mail_then_yours(_lift_ask(closed_reason="replied"), {}, work) is None, "answered already"
    home = item_home(_lift_ask(), index(("r#TD-050", [50, 51])), entries=work)
    assert (home["on_row"], home["then_yours"], home["then_repo"]) == ("r#TD-051", ["r#TD-055"], "r")
    got = attach({"needs": [{**_lift_ask(), **home}]}, drawn, [])["cards"]["r#TD-050"]["needs"]
    assert [m["want"] for m in got] == ["answered"]


@pytest.mark.unit
def test_the_ledger_item_draws_its_press_line_and_open_alone(tmp_path):
    row = {**_row(tmp_path), "home": "queue", "start": START}
    html = card(row, "answered")
    assert slots(html) == [RIGHT, "Open"]
    assert press(html) == "Asked once TD-002 closes."
    for gone in ("Lift the hold", "Answer…", "Not clear", "Start session", "qdots", "qanswers"):
        assert gone not in html, gone
    assert "the design" in html, "its question's words stay, for the record"


@pytest.mark.unit
def test_the_board_line_draws_its_press_line_and_open_alone():
    e = {**line(), "then_yours": ["r#TD-055"], "answers": ["Go", "Hold it back"], "default": "Go",
         "board": "docs/user_attention/", "start": START, "editor": None}  # fmt: skip
    html = card(e, "answered")
    assert slots(html) == [RIGHT, "Open"] and 'href="/repo/r#waiting"' in html
    assert press(html) == "Asked once TD-055 closes."
    assert 'k-decide">Decide</span>' in html, "it keeps its kind"
    for gone in ("Hold it back", "Answer…", "Not clear", "qdots"):
        assert gone not in html, gone


@pytest.mark.unit
def test_the_lifting_ask_draws_its_press_line_and_open_alone():
    e = {**_lift_ask(), "then_yours": ["r#TD-055", "s#TD-3"], "then_repo": "r", "from_open": "s-1",
         "from_name": "designer"}  # fmt: skip
    html = card(e, "answered")
    assert slots(html) == [RIGHT, "Open"] and 'href="/focus/s-1"' in html
    assert press(html) == "Asked once TD-055 and 1 more close."
    for gone in ("Not yet", "Answer…", "Not clear", "Delete", "open · no bound"):
        assert gone not in html, gone


@pytest.mark.unit
def test_the_inbox_later_row_and_the_repo_pages_for_you_row_withhold_its_answers(tmp_path):
    row = _row(tmp_path)
    html = str(templates.env.get_template("inbox_row.html").module.row({**row, "lift_item": True}, "later"))
    assert '<span class="st qthen">Asked once TD-002 closes</span>' in html
    assert '<span class="st qans">waiting, then yours</span>' in html
    for gone in ("its answers", "Lift the hold", ">Reply</button>", "Not clear", "Go with it", "Start session"):
        assert gone not in html, gone
    assert f'href="{row["url"]}"' in html, "its Open stays"
