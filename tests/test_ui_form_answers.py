"""TD-1699 (TD-1557's design), §4.5 screen 12 *Three verbs: Answer*, screen 6 *A board line's Reply*, §4.5a **<head>…**:
the page draws a form answer as `<head>…` from the reader's `heads`, its press opens its road's box begun with the head
and sends `form`; the reply box's foot says which words decide a line; a Reply the agent answers `decided` is redrawn
decided."""

from __future__ import annotations

import pathlib
import re

import pytest
from test_queue_item_shape import card, inbox
from test_ui_board import host, item, look_item, report, rows_html
from test_ui_inbox import entry

from shiftlead.ui.app import board_rows, ledger_for_you, templates

pytestmark = pytest.mark.unit

JS = (pathlib.Path(__file__).resolve().parent.parent / "src/shiftlead/ui/static/app.js").read_text()
HOLD = ("Go", "One more round", "Hold: <note>")


def hold_item(answers=HOLD, decided=None, kind="decide"):
    tail = " | ".join(answers)
    text = f"**End of rounds for TD-9.** Context: TD-9. Due: 2026-09-20. Answers: {tail}."
    return {
        **item(7, text, "2026-09-20", "2d overdue"),
        "answers": list(answers),
        "default": None,
        "decided": decided,
        "kind": kind,
    }


def buttons(html: str) -> list[tuple[str, str]]:
    """Each answer button's attributes and label, in order."""
    return re.findall(r'<button class="btn sm answer[^"]*"([^>]*)><span class="alabel">(.*?)</span>', html)


def test_a_board_rows_form_is_drawn_head_and_opens_its_box_begun_sending_a_decide(tmp_path, monkeypatch):
    rows, html = rows_html(tmp_path, monkeypatch, hold_item())
    assert rows[0]["heads"] == ["", "", "Hold"] and rows[0]["reply_decides"]
    btns = buttons(html)
    assert [label for _, label in btns] == ["&ldquo;Go&rdquo;", "&ldquo;One more round&rdquo;", "Hold…"]
    form = btns[2][0]
    assert 'data-act="board_notright"' in form and 'data-begun="Hold: "' in form and 'data-form="2"' in form
    assert "data-pair" not in form and "data-answer=" not in form  # a form is never sent as written
    assert 'data-board-act="decide"' in btns[0][0]
    # the foot is drawn on Reply, its words the forms' heads
    reply = re.search(r'<button[^>]*data-act="board_reply"[^>]*>', html).group(0)
    assert 'data-foot="words starting Hold: decide this line; anything else is a reply"' in reply


def test_the_foot_is_absent_on_a_decided_line_and_two_forms_are_joined_by_or(tmp_path, monkeypatch):
    _rows, html = rows_html(tmp_path, monkeypatch, hold_item(decided={"text": "Go", "date": "2026-09-19"}))
    assert 'data-foot=""' in html or 'data-act="board_reply"' not in html
    assert "words starting" not in html
    _rows, html = rows_html(tmp_path, monkeypatch, hold_item(answers=("Go", "Hold: <note>", "Not right: <what>")))
    assert "words starting Hold: or Not right: decide this line; anything else is a reply" in html
    # a line with no form: no foot
    _rows, html = rows_html(tmp_path, monkeypatch, hold_item(answers=("Go", "Stop")))
    assert "words starting" not in html


def test_a_look_keeps_its_pair_and_its_reply_carries_the_hand_off(tmp_path, monkeypatch):
    rows, html = rows_html(tmp_path, monkeypatch, look_item())
    btns = buttons(html)
    assert [label for _, label in btns] == ["Works", "Not right…"]
    assert 'data-pair="1"' in btns[1][0] and 'data-begun="Not right: "' in btns[1][0]
    reply = re.search(r'<button[^>]*data-act="board_reply"[^>]*>', html).group(0)
    assert 'data-pair="1"' in reply and 'data-repo="samscrape"' in reply and 'data-head="One look at the ring"' in reply


def test_a_card_draws_hold_and_its_answer_box_carries_the_foot(tmp_path, monkeypatch):
    host(tmp_path, monkeypatch)
    (b,) = board_rows(report(tmp_path / "samscrape", hold_item()))
    html = card(b, "decide")
    row = html[html.index('class="row gap wrap sugg qanswers"') :]
    btns = re.findall(
        r'<button class="btn sm answer([^"]*)" type="button"([^>]*)><span class="alabel">(.*?)</span>', row
    )
    assert [label for *_, label in btns] == ["Go", "One more round", "Hold…"]
    assert 'data-act="board_notright"' in btns[2][1] and 'data-form="2"' in btns[2][1] and not btns[2][0]
    answer = re.search(r'<button[^>]*data-act="board_reply"[^>]*>Answer…', html).group(0)
    assert "words starting Hold: decide this line" in answer


def test_a_mail_asks_form_draws_hold_and_replies_with_its_index():
    e = entry("m-5", "ask", text="Go or hold?", answers=["Go", "Hold: <note>"], recommended=0)
    e["heads"] = ["", "Hold"]
    for html in (inbox(e), card(e, "decide")):
        btns = buttons(html)
        labels = [label for _, label in btns]
        assert "Hold…" in labels
        form = btns[labels.index("Hold…")][0]
        assert 'data-act="reply"' in form and 'data-begun="Hold: "' in form and 'data-form="1"' in form
        assert "data-index" not in form


def test_a_ledger_entrys_form_draws_hold_and_sends_form_to_ledger_decide(tmp_path, monkeypatch):
    from test_form_heads import boards_reading

    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    rs = boards_reading(report(root))
    led = {"for_page": "for-you", "priority": "medium", "owner": "paul", "id": "TD-60", "title": "yours",
           "answers": ["Go", "Hold: <note>"]}  # fmt: skip
    rs[str(root)]["ledger"] = {"path": "docs/ledger", "entries": [led]}
    groups = ledger_for_you(rs, [], {})["groups"]
    html = templates.get_template("inbox_rows.html").render(
        rows=[r for g in groups for r in g["rows"]], section="needs"
    )
    btns = buttons(html)
    form = next(a for a, label in btns if label == "Hold…")
    assert 'data-act="ledger_reply"' in form and 'data-begun="Hold: "' in form and 'data-form="1"' in form
    assert "want.form = Number(at.form)" in JS


def test_the_page_matches_no_form_and_reads_the_filled_answer_back():
    # the mail reply sends the form's index; the look's regex is gone
    assert 'if (action === "reply" && at.form) { AO.formFilled(m.text, at.begun); body.form = Number(at.form); }' in JS
    assert "/^not right" not in JS
    # a board Reply the agent answered `decided` is drawn decided, its card item off, a look's handed on
    at = JS.index('if (action === "board_reply") {')
    block = JS[at : JS.index('if (action === "board_notright") {', at)]
    assert "foot: at.foot" in block and "if (res.decided) {" in block
    assert "answered(`decided: ${res.decided} · ${AO.today()}`);" in block and "AO.qcardOff(r, msgOf)" in block
    assert (
        'say("decided — written on the board", true);' in block and "AO.handOn(at.repo, at.head, res.decided)" in block
    )
    # a Hold… press hands nothing on; an empty fill is refused before anything is sent
    nr = JS[JS.index('if (action === "board_notright") {') :]
    nr = nr[: nr.index('if (action === "board_add") {')]
    assert nr.index("if (!at.pair)") < nr.index("AO.handOn") and nr.index("AO.formFilled") < nr.index("pressed(said)")
    assert (
        'id="mailfoot"'
        in (pathlib.Path(__file__).resolve().parent.parent / "src/shiftlead/ui/templates/base.html").read_text()
    )


def test_the_answer_box_caps_no_words_and_the_form_press_sends_them_as_typed():
    """TD-1883 (design §4.4 *A person's words are written whole*): the box a form's press and a Reply open (`#mailtext`)
    has no `maxlength`, and the form's press sends the composer's words, whitespace folded, never sliced."""
    base = (pathlib.Path(__file__).resolve().parent.parent / "src/shiftlead/ui/templates/base.html").read_text()
    box = re.search(r'<textarea[^>]*id="mailtext"[^>]*>', base).group(0)
    assert "maxlength" not in box
    press = JS[JS.index('if (action === "board_notright")') :]
    press = press[: press.index("return;\n      }")]
    assert 'const said = m.text.split(/\\s+/).filter(Boolean).join(" ");' in press and "answer: said" in press
    assert ".slice(" not in press and ".substring(" not in press
    # a Reply and a ledger entry's Reply send the composer's words as typed
    reply = JS[JS.index('if (action === "board_reply")') :]
    reply = reply[: reply.index('if (action === "board_notright")')]
    assert "reply: m.text" in reply and ".slice(" not in reply and ".substring(" not in reply
    assert "want.words = m.text;" in JS
