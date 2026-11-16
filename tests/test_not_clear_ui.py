"""TD-1853 slice 2, design §4.5a row **Not clear** (§4.10 *Text a person reads is checked at its writer*, rule 6):
the answer drawn on an `ask` or `steer` to the person, a board `decide` or `act` line and a ledger entry that waits
on the person — never on a look, a rerouted question or any other item; on the Queue the last of the item's answers,
on the Inbox's row among its own controls after **Reply**; never outlined, no confirm, titled *the writer rewrites
it*. `app.js` sends it down the item's own road, marked `not_clear` (slice 1 built the roads and the count)."""

from __future__ import annotations

import pathlib
import re

import pytest
from test_ui_press_draw import APP_JS

from sessionorc import board as board_mod
from shiftlead.ui.app import templates
from shiftlead.ui.inbox import LEDGER_NOT_CLEAR, not_clear_on

pytestmark = pytest.mark.unit

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
JS = APP_JS.read_text(encoding="utf-8")


def _mod(mode: str):
    return templates.get_template("inbox_row.html").make_module({"mode": mode})


def _mail(kind: str = "ask", **kw) -> dict:
    e = {"id": "m1", "from": "g1", "to": ["person"], "kind": kind, "text": "which one?", "state": "open"}
    e.update(answers=["a", "b"], **kw)
    if kind == "steer":
        e.setdefault("default", "a")
    return e


def _board(kind: str = "decide", **kw) -> dict:
    e = {"row": "board", "id": "b1", "kind": kind, "text": "**Pick** one?", "board": "/r/docs/user_attention/",
         "key": "abcd1234", "line": 3, "repo": "s", "repo_name": "s", "name": "s", "answers": ["a", "b"]}
    e.update(kw)
    return e


def _ledger(**kw) -> dict:
    e = {"row": "ledger", "id": "TD-7", "title": "a thing", "root": "/r", "name": "s", "url": "/repo/s#TD-7",
         "pri": "Medium", "home": "queue", "why": "decision", "answers": ["Yes", "No"]}
    e.update(kw)
    return e


def _buttons(html: str) -> list[str]:
    return re.findall(r"<button[^>]*>.*?</button>", html, re.S)


def _label(b: str) -> str:
    return re.sub(r"<[^>]+>", "", b).strip()


def test_it_is_drawn_on_the_named_kinds_alone():
    assert not_clear_on(_mail("ask"), "mail") and not_clear_on(_mail("steer"), "mail")
    assert not_clear_on(_mail(passed_up=True, recommend={"by": "t1"}), "mail")  # a passed-up one among them
    assert not not_clear_on(_mail("note"), "mail") and not not_clear_on(_mail("reply"), "mail")
    assert not not_clear_on(_mail(shots=["a.png"]), "mail"), "a look"
    assert not not_clear_on(_mail(routed={"name": "techlead-ao-1", "why": "limited"}), "mail"), "routed around"
    assert not not_clear_on(_mail(**{"from": "system"}), "mail") and not not_clear_on(_mail(closed_reason="x"), "mail")
    assert not_clear_on(_board("decide"), "board") and not_clear_on(_board("act"), "board")
    for no in (_board("watch"), _board("look"), _board(pair=True), _board(decided={"text": "a", "date": "d"})):
        assert not not_clear_on(no, "board"), no
    assert not_clear_on(_ledger(), "ledger") and not not_clear_on(_mail(), "owed")


def test_on_the_inbox_row_it_follows_reply_and_never_sits_among_the_suggested_answers():
    m = _mod("inbox")
    for e, draw in ((_mail("ask"), m.ask), (_mail("steer", bound="2026-11-17T00:00:00Z"), m.steer)):
        html = str(draw(e, "needs"))
        labels = [_label(b) for b in _buttons(html)]
        assert labels[labels.index("Reply") + 1] == "Not clear", labels
        sugg = html[html.index('class="row gap wrap sugg"') : html.index('class="row gap wrap mfoot"')]
        assert "Not clear" not in sugg
        b = next(b for b in _buttons(html) if "Not clear" in b)
        assert 'data-act="not-clear"' in b and 'data-via="mail"' in b and 'data-msg="m1"' in b
        assert 'title="the writer rewrites it"' in b and "data-confirm" not in b and " rec" not in b
    # a look and a routed-around question draw none
    for e in (_mail(shots=["a.png"]), _mail(routed={"name": "techlead-ao-1", "why": "limited"})):
        assert "Not clear" not in str(m.ask(e, "needs"))
    # a board line: after its Reply, its road the decide with the fixed answer and the line's kind
    html = str(m.board(_board("act"), "needs"))
    labels = [_label(b) for b in _buttons(html)]
    assert labels[labels.index("Reply") + 1] == "Not clear", labels
    b = next(b for b in _buttons(html) if ">Not clear<" in b)
    assert 'data-via="board"' in b and 'data-board-act="decide"' in b and 'data-kind="act"' in b
    assert f'data-answer="{board_mod.NOT_CLEAR}"' in b and 'data-key="abcd1234"' in b
    # a waiting or decided line draws none
    assert ">Not clear<" not in str(m.board(_board(), "waiting"))
    assert ">Not clear<" not in str(m.board(_board(decided={"text": "a", "date": "2026-11-16"}), "needs"))
    # a ledger entry: after its Reply, its road the entry's decide with the fixed words
    html = str(m.ledger(_ledger(home="inbox"), "needs"))
    labels = [_label(b) for b in _buttons(html)]
    assert labels[labels.index("Reply") + 1] == "Not clear", labels
    b = next(b for b in _buttons(html) if ">Not clear<" in b)
    assert 'data-via="ledger"' in b and 'data-ref="TD-7"' in b and f'data-answer="{LEDGER_NOT_CLEAR}"' in b
    # an answered entry draws none
    assert ">Not clear<" not in str(m.ledger(_ledger(answered={"name": "g1", "words": "Yes"}), "waiting"))


def test_on_the_queue_it_is_the_last_answer_before_answer_and_never_outlined():
    m = _mod("card")
    cases = (
        (_mail("ask", want="decide"), m.ask),
        (_mail("steer", want="decide", bound="2026-11-17T00:00:00Z"), m.steer),
        (_board("decide", want="decide"), m.board),
        (_board("act", want="do"), m.board),
        (_ledger(want="decide"), m.ledger),
    )
    for e, draw in cases:
        html = str(draw(e, "needs"))
        bar = html[html.index('class="row gap wrap sugg qanswers"') :]
        labels = [_label(b) for b in _buttons(bar)]
        assert labels.count("Not clear") == 1 and labels[labels.index("Not clear") + 1] == "Answer…", (e, labels)
        b = next(b for b in _buttons(bar) if ">Not clear<" in b)
        assert 'class="btn sm answer notclear"' in b, b  # never outlined (`rec`)
        assert "Reply" not in labels  # a card has no Reply word
    # a look on a card draws none
    assert ">Not clear<" not in str(m.ask(_mail(shots=["a.png"], want="decide"), "needs"))


def test_the_page_sends_it_down_the_items_own_road():
    head = JS[JS.index("const notClear = ") :][:600]
    assert '"board" ? "board"' in head and '"ledger" ? "ledger"' in head and '"notclear"' in head
    assert '["pause", "resume", "gowithit", "notclear"].includes(action)' in JS
    assert "if (notClear) { body.not_clear = true; body.kind = b.dataset.kind" in JS
    assert "else if (notClear) want.not_clear = true;" in JS
    assert '"notclear"' in JS[JS.index("const PRESS_LEAVES") :][:400]


def test_a_question_so_closed_reads_marked_not_clear():
    m = _mod("inbox")
    assert str(m.state_line({"closed_reason": "not_clear", "from": "g1"}, "grinder-1")).strip() == (
        "marked Not clear — back to grinder-1"
    )
    assert 'e.closed_reason === "not_clear" ? `marked Not clear — back to' in JS
