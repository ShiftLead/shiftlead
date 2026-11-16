"""TD-1843 steps 4 (design §4.5 screen 12 *A press is never left stranded*, case *could not be done*; §4.5a *Queue
card: press line*): a `blocked` outcome and an exited asker's owed question, on a card, say what became of the press in
one press line (`--needs`) and draw the question's answers again as plain replies — the one taken ticked and not
pressable, each other one its words sent as a reply on the thread, none a lift — then **Answer…**, Start session,
**Dismiss** and **Open**, with no ⋯. The Inbox's own rows keep their outcome line and foot."""

from __future__ import annotations

import pathlib
import re

from test_queue_answer_bar import START, bar, slots
from test_queue_item_shape import card, inbox
from test_ui_inbox import entry

APP_JS = (pathlib.Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui" / "static" / "app.js").read_text()


def _owed(**kw):
    e = entry("m-5", "ask", text="Merge it?", answers=["yes", "no"], closed_reason="replied", start=START)
    e.update(kw)
    return e


def press_line(html: str) -> str:
    m = re.search(r'<div class="qpress qp-needs" role="status">(.*?)</div>', html, re.S)
    return m.group(1) if m else ""


def test_a_blocked_outcome_says_who_could_not_do_it_and_what_the_bar_offers():
    e = _owed(answer=0, answer_given="yes", outcome={"state": "blocked", "text": "the PR is red"})
    html = card(e, "do")
    assert press_line(html) == "You answered &ldquo;yes&rdquo;. w1 could not do it: the PR is red. " + (
        "Reply, start a session, or dismiss it."
    )
    # the press line is its only status words: no outcome badge, no answer line, no foot
    assert "outcome · blocked" not in html and "k-outcome" not in html
    assert 'class="st dflt"' not in html and "mfoot" not in html
    assert html.index("qp-needs") < html.index('class="row gap wrap qabar"'), "above the bar"


def test_a_typed_reply_and_a_steers_default_have_their_own_first_sentence():
    typed = card(_owed(outcome={"state": "blocked", "text": "no"}), "do")
    assert press_line(typed).startswith("You answered. w1 could not do it: no.")
    steer = _owed(kind="steer", closed_reason="go_with_it", default="yes", outcome={"state": "blocked", "text": "no"})
    assert press_line(card(steer, "do")).startswith("You let it go with its default. w1 could not do it: no.")


def test_an_exited_asker_is_named_with_its_state():
    e = _owed(answer=1, answer_given="no", owes=True, asker_gone_quiet=True, asker_state="exited", from_open=None)
    assert press_line(card(e, "do")) == (
        "You answered &ldquo;no&rdquo;. w1 exited without reporting what came of it. "
        "Reply, start a session, or dismiss it."
    )
    assert slots(card(e, "do"))[:2] == ["Yes", "✓ No"], "the taken one by its index"


def test_its_answers_are_plain_replies_and_the_taken_one_is_not_pressable():
    e = _owed(answer=0, answer_given="yes", outcome={"state": "blocked", "text": "red"}, lift="TD-9")
    b = bar(card(e, "do"))
    taken = re.search(r"<button[^>]*>(?:<span class=\"alabel\">)✓ Yes", b).group(0)
    assert "disabled" in taken and 'aria-pressed="true"' in taken and "data-act" not in taken
    other = re.search(r"<button[^>]*>(?:<span class=\"alabel\">)No<", b).group(0)
    assert 'data-act="reply"' in other and 'data-msg="m-5"' in other and 'data-says="no"' in other
    # none of them a lift, whatever the question's answers lifted (TD-1833)
    assert "data-lift" not in b and 'data-act="answer"' not in b


def test_the_inbox_keeps_its_outcome_line_and_foot():
    e = _owed(answer=0, answer_given="yes", outcome={"state": "blocked", "text": "the PR is red"})
    html = inbox(e)
    assert "qp-needs" not in html and "data-says" not in html
    assert "outcome · blocked" in html.lower() or "o-blocked" in html
    assert "you answered &ldquo;yes&rdquo;" in html


def test_a_plain_reply_sends_its_words_with_no_box():
    assert 'if (action === "reply" && at.says) body = { reply_to: at.msg, text: at.says };' in APP_JS
    assert APP_JS.index("at.says) body =") < APP_JS.index("const m = await AO.compose({")
