"""TD-911 (3), design §4.5 screen 12 *An item's shape*: each kind's renderer takes a mode, `inbox` or `card` — the
Queue's `queue_mail.html` sets `card` — and there is no second renderer. In `card` mode a Read item is one line
opening to its row, and a Decide or Do item is drawn whole: its kind line, its one sentence, what each answer
leads to, *context* folded in place of *details*, and its answers. The Inbox draws as before."""

import re

from fastapi.testclient import TestClient
from test_ui_inbox import entry
from test_ui_queue_cards import _fold_body, _fold_fake, _fold_world

from shiftlead.ui.app import ledger_for_you, templates
from shiftlead.ui.common import card_shape

THREE = (
    "Which account should the walk sign in with?\n\nWork leads to the paid seat; home to the free one.\n\n"
    "TD-9 asked; see §4.4."
)


def card(e: dict, want: str, section: str = "needs") -> str:
    return templates.get_template("queue_mail.html").render(e={**e, "want": want}, section=section)


def inbox(*es: dict, section: str = "needs") -> str:
    return templates.get_template("inbox_rows.html").render(rows=list(es), section=section)


def test_a_mail_items_shape_is_its_sentence_its_leads_and_its_context():
    c = card_shape(THREE)
    assert c["one"] and "Which account" in c["sentence"] and "paid seat" in c["leads"] and "TD-9 asked" in c["context"]
    two = card_shape("Merge it? It is green.\n\nmore")  # a first paragraph of two sentences
    assert (
        not two["one"]
        and not two["sentence"]
        and "Merge it? It is green." in two["context"]
        and "more" in two["context"]
    )


def test_a_decide_ask_is_drawn_whole_with_context_folded():
    e = entry("m-1", "ask", text=THREE, subject="which account", answers=["work", "home"])
    html = card(e, "decide")
    assert '<div class="body md sentence">' in html and "Which account should the walk" in html
    assert '<div class="body md leads">' in html and "paid seat" in html
    # the rest under *context*, sent closed and read on its first open
    assert 'data-fold="card:m-1" data-lazy="1"><summary>context</summary></details>' in html
    assert ">TD-9 asked" not in html and '<div class="subj">' not in html and 'class="cardline"' not in html
    assert 'data-act="answer"' in html  # its answers, the renderer's own
    # the Inbox draws the same entry as before, a want on it or not
    for e2 in (e, {**e, "want": "decide"}):
        page = inbox(e2)
        assert "<summary>details</summary>" in page and "<summary>context</summary>" not in page
        assert '<div class="subj">which account</div>' in page and "sentence" not in page


def test_a_mail_item_of_more_than_one_sentence_leads_with_its_subject_and_folds_its_whole_text():
    e = entry("m-2", "ask", text="Merge it? It is green.\n\nmore words", subject="merge PR 9")
    html = card(e, "decide")
    assert '<div class="subj sentence">merge PR 9</div>' in html
    assert 'data-fold="card:m-2" data-lazy="1"><summary>context</summary>' in html
    assert "<p>Merge it? It is green.</p>" not in html  # the whole text is under *context*, read on its first open


def test_a_read_item_is_one_line_opening_to_its_row():
    e = entry("m-3", "note", text="the build is live.\n\nthe rest.", subject="the build is live")
    html = card(e, "read", "fyi")
    line = re.search(r'<details class="cardline" data-fold="line:m-3"><summary[^>]*>(.*?)</summary>', html, re.S)
    assert line, html
    assert "w1" in line.group(1) and ">note<" in line.group(1) and "the build is live" in line.group(1)
    assert "1h 0m" in line.group(1)
    # inside, the row whole with its controls
    assert 'data-act="unmail"' in html.split("</summary>", 1)[1]
    assert 'class="cardline"' not in inbox(e, section="fyi")


def test_a_ledger_item_leads_with_its_ask_and_says_what_each_answer_leads_to(tmp_path, monkeypatch):
    rs, _ = _fold_world(tmp_path, monkeypatch)
    led = rs[next(iter(rs))]["ledger"]["entries"][0]
    led.update(owner="", ask="Should the walk use the work account?", answers=["work", "home"])
    led["consequences"] = ["the paid seat", ""]
    row = next(r for g in ledger_for_you(rs, [], {})["groups"] for r in g["rows"])
    assert row["ask"] and row["consequences"] == ["the paid seat", ""]
    html = card(row, "decide")
    assert '<div class="body sentence">Should the walk use the work account?</div>' in html
    assert "<li><b>work</b> — the paid seat</li>" in html and "<b>home</b>" not in html
    # its *context* is drawn closed and read on its first open, though it has answers to press
    assert f'data-fold="{row['row_id']}" data-lazy="1"><summary>context</summary></details>' in html
    # with no `Ask:`, its title is the sentence
    no_ask = card({**row, "ask": ""}, "do")
    assert '<div class="body sentence"><b class="mono">TD-60</b> yours</div>' in no_ask
    # the Inbox's own ledger row is unchanged
    page = inbox(row)
    assert "sentence" not in page and "<li><b>work</b>" not in page and "<summary>details</summary>" in page


def test_the_fold_route_answers_a_cards_context(tmp_path, monkeypatch):
    from shiftlead.ui import app as ui

    rs, mail = _fold_world(tmp_path, monkeypatch)
    mail = {**mail, "text": THREE}
    monkeypatch.setattr(ui, "LocalClient", _fold_fake(rs, mail, []))
    c = TestClient(ui.create_app())
    got = c.get("/api/fold", params={"key": "card:m-7"})
    assert got.status_code == 200 and "TD-9 asked" in got.text and "Which account" not in got.text
    # the open fold, drawn whole, holds what the route answers
    page = templates.get_template("queue_mail.html").render(
        e={**mail, "want": "decide"}, section="needs", fold_open=True
    )
    whole = re.search(r'data-fold="card:m-7" open><summary>context</summary>(.*?)</details>', page, re.S)
    assert whole and whole.group(1).strip() == got.text.strip()
    assert _fold_body(inbox(mail), "m-7")  # the Inbox's fold keeps its key and its word
