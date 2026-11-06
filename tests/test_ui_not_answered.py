"""design §4.5a **Inbox row: taken up** (§4.9b *Why it did not answer*, TD-1431): an `ask` or a `steer` carrying the
home's `unanswered` stamp draws one line, *not answered by <name> (as read at <time>):* and the home's fixed words
for the state, as text — on the Inbox row, the message page and the Queue card's mail item, all through the row
macro — and an entry without the stamp draws none. The held-PR author's brief offers the two answers in order."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_ui_inbox import entry, rows
from test_ui_queue import client, fake, mail, queue

from sessionorc import unanswered
from shiftlead.ui.app import templates

STAMP = {
    "by": "ao-shiftlead-techlead-ao-1",
    "name": "techlead-ao-1",
    "seat": True,
    "state": "fills_exhausted",
    "since": "2026-09-19T09:04:00Z",
    "held": True,
    "at": "2026-09-19T10:00:00Z",
}
LABEL = f"not answered by techlead-ao-1 (as read at {unanswered.clock(STAMP['at'])}):"
WORDS = unanswered.words(STAMP)
SRC = Path(__file__).resolve().parents[1] / "src" / "shiftlead"


@pytest.mark.unit
@pytest.mark.parametrize("kind,section", [("ask", "needs"), ("steer", "steering")])
def test_the_row_draws_the_line_under_the_text_and_no_button(kind, section):
    e = entry("m-1", kind, text="may I merge #12?", pr=12, unanswered=STAMP, default="yes")
    html = rows(section, [e])
    assert LABEL in html and WORDS in html and "tripped twice running" in html
    line = html[html.index('class="st dflt notanswered"') :]
    line = line[: line.index("</div>")]
    assert "<button" not in line and "<a " not in line  # display only: the press is on the seat's own row
    assert html.index('class="body md"') < html.index("notanswered")  # under the question's text


@pytest.mark.unit
@pytest.mark.parametrize("kind,section", [("ask", "needs"), ("steer", "steering")])
def test_an_entry_without_the_stamp_draws_no_line(kind, section):
    assert "not answered by" not in rows(section, [entry("m-1", kind, text="may I merge #12?", default="yes")])


@pytest.mark.unit
def test_the_queue_mail_item_draws_the_same_line():
    e = entry("m-1", "ask", text="may I merge #12?", unanswered=STAMP)
    card = templates.get_template("queue_mail.html").render(e={**e, "want": "decide"}, section="needs")
    assert LABEL in card and WORDS in card
    plain = templates.get_template("queue_mail.html").render(
        e={**entry("m-2", "ask", text="may I merge #12?"), "want": "decide"}, section="needs"
    )
    assert "not answered by" not in plain


@pytest.mark.unit
def test_a_malformed_stamp_reads_as_the_plain_line():
    e = entry("m-1", "ask", text="may I merge #12?", unanswered={"by": "ao-x", "state": "nonsense", "at": ""})
    assert "not answered by ao-x (as read at ):</span> ao-x did not answer." in rows("needs", [e])


def test_the_message_page_draws_the_line(tmp_path, monkeypatch):
    m = mail("m1", "may I merge #12?", unanswered=STAMP)
    page = client(monkeypatch, tmp_path, fake(queue(), [m])).get("/inbox/m1").text
    assert LABEL in page and WORDS in page
    other = client(monkeypatch, tmp_path, fake(queue(), [mail("m2", "may I merge #12?")])).get("/inbox/m2").text
    assert "not answered by" not in other


@pytest.mark.unit
@pytest.mark.parametrize("path", ["briefs/grinder.stage.md", "flows/td/build.md", "flows/build-review/build.md"])
def test_the_held_pr_authors_past_the_bound_ask_offers_both_answers_in_order(path):
    text = (SRC / path).read_text()
    a = text.index('--answer "Ask the reader again — I brought it back"')
    assert a < text.index('--answer "I\'ll read it"')
    assert "saying the reader did not answer" not in text


@pytest.mark.unit
@pytest.mark.parametrize("path", ["briefs/grinder.md", "briefs/hunter.md"])
def test_the_techlead_wait_take_up_says_nothing_of_why(path):
    text = (SRC / path).read_text()
    assert "saying the techlead did not answer" not in text and "the home adds why the techlead did not answer" in text
