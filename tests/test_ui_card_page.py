"""A card's page (design §4.5 screen 12 *The card's page*, *Opening a card's page*, *Addresses*; §4.5a *Card page*;
TD-1558, built by TD-1762): `/card/<card id>` draws the one card whose own id is the page's, with every control,
under its line and its bar; `?part=1` is its re-read; `/queue?card=…` redirects to it; a mail item's Back returns
to it."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from test_ui_queue import NOW, client, fake, mail, queue

from shiftlead.ui.queue import card_page_find, card_page_goto, queue_view

UI = Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui"


def page(c, cid: str, q: str = "") -> str:
    return c.get(f"/card/{quote(cid, safe='')}{q}").text


def test_the_page_draws_one_card_with_its_controls_under_its_line_and_bar(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(queue()))
    html = page(c, "s#TD-20")
    assert html.count('class="qcard ') == 1 and 'data-card="s#TD-20"' in html
    assert 'id="cardpage" data-card="s#TD-20"' in html and 'id="qbar"' in html and "AO.cardPage()" in html
    assert '<a href="/queue#s%23TD-20" id="cardback" class="cardback">‹ Queue</a>' in html
    where = html[html.index('id="cardwhere"') : html.index("cardlive")]
    assert re.findall(r'class="cw\d">([^<]+)<', where) == ["Up next", "1", "s"]  # group, place, repo
    assert "● live — values update in place; nothing here moves" in html
    assert 'id="boardadd"' in html  # Put on the board's dialog, a box the page holds for
    assert "Counts what changed on this card since it was drawn" in html  # the bar's own help entry
    assert 'class="qmoves"' in html  # drawn by the Queue's renderer; the page's stylesheet hides the moves


def test_the_part_is_the_card_alone_and_names_its_group(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(queue()))
    part = page(c, "s#TD-10", "?part=1")
    assert 'id="qcounts"' in part and "<html" not in part and 'id="qbar"' not in part
    assert 'data-found="1" data-group="in_progress"' in part
    assert '<section class="qgroup" data-group="in_progress">' in part and 'data-card="s#TD-10"' in part


def test_a_cards_own_id_alone_never_a_row_it_holds(tmp_path, monkeypatch):
    """`/card/<a row's id>` is not the card holding the row: with no `item=` or `row=` it opens the Queue's find."""
    c = client(monkeypatch, tmp_path, fake(queue()))
    part = page(c, "s#TD-21", "?part=1")
    assert 'data-found=""' in part and 'data-goto="/queue#s%23TD-21"' in part and "qcard " not in part
    # with `row=` the page opens on the card that draws the row
    part = page(c, "s#TD-21", "?part=1&row=s%23TD-21")
    assert 'data-goto="/card/s%23TD-20?row=s%23TD-21"' in part


def test_an_old_links_item_opens_the_card_that_draws_it(tmp_path, monkeypatch):
    entries = [mail("m1", "which one?", about="TD-21")]
    c = client(monkeypatch, tmp_path, fake(queue(), entries))
    part = page(c, "s#TD-99", "?part=1&row=s%23TD-99&item=m1")
    assert 'data-goto="/card/s%23TD-20?row=s%23TD-99&amp;item=m1"' in part


def test_a_completed_card_with_no_item_is_its_line_opened(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(queue()))
    part = page(c, "s#TD-1", "?part=1")
    assert 'data-found="1" data-group="completed"' in part and "qcard " not in part
    assert "Recently completed · " in part and "built (#12)." in part and "designed (#11)." in part
    assert 'data-ids="s#TD-2 s#TD-1"' in part


def test_a_kept_and_a_loose_card_by_their_ids_padded_or_typed(tmp_path, monkeypatch):
    entries = [mail("m1", "merge #13?", about="TD-3"), mail("m4", "is other#TD-9 done?")]
    c = client(monkeypatch, tmp_path, fake(queue(), entries))
    kept = page(c, "s#TD-3", "?part=1")
    assert 'data-group="kept"' in kept and '<section class="qgroup" data-group="completed">' in kept
    for cid in ("loose:other#TD-009", "loose:other#TD-9"):  # the padded id and the hand-typed one are one page
        part = page(c, cid, "?part=1")
        assert 'data-found="1" data-group="loose"' in part and 'data-card="loose:other#TD-009"' in part


def test_a_merged_or_left_card_is_not_followed(tmp_path, monkeypatch):
    """A page whose id the view no longer holds draws no other card: the client marks it *gone*, its bar *done*
    where its top entry is among the completed ids."""
    c = client(monkeypatch, tmp_path, fake(queue()))
    part = page(c, "s#TD-2", "?part=1")  # a completed card's member, not its id
    assert 'data-found=""' in part and 'data-topdone="1"' in part and "qcard " not in part
    assert 'data-topdone=""' in page(c, "s#TD-77", "?part=1")


def test_the_old_queue_address_redirects_with_its_row_and_item(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(queue()))
    got = c.get("/queue?card=s%23TD-20&row=s%23TD-21&item=m-1", follow_redirects=False)
    assert got.status_code == 303 and got.headers["location"] == "/card/s%23TD-20?row=s%23TD-21&item=m-1"
    got = c.get("/queue?card=loose%3Aother%23TD-9&item=m-1", follow_redirects=False)
    assert got.headers["location"] == "/card/loose%3Aother%23TD-9?item=m-1"
    assert c.get("/queue?part=1&card=s%23TD-20", follow_redirects=False).status_code == 200


def test_a_mail_items_back_from_a_card_page_rings_it_there(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(queue(), [mail("m1", "which one?", about="TD-21")]))
    html = c.get("/inbox/m1?back=" + quote("/card/s%23TD-20")).text
    assert 'id="msgback" href="/card/s%23TD-20?item=m1"' in html
    # anything else under /card is no Back: a path with more in it reads as the Inbox's
    html = c.get("/inbox/m1?back=" + quote("/card/s%23TD-20/../x")).text
    assert 'id="msgback" href="/inbox#m1"' in html


def test_card_page_find_and_goto_read_the_view():
    v = queue_view(queue(), NOW)
    assert card_page_find(v, "s#TD-20")["group"] == "up_next"
    assert card_page_find(v, "s#TD-020")["card"]["id"] == "s#TD-20"  # spelled, as `_refs` writes it
    assert card_page_find(v, "s#TD-21") is None
    assert card_page_find(v, "s#TD-3")["group"] == "completed"
    assert card_page_goto(v, {}, "", "") == ""


def test_the_client_reads_the_card_page_and_the_bar_words():
    js = (UI / "static" / "app.js").read_text(encoding="utf-8")
    assert "AO.cardPage = function" in js and "AO.cardBarParts" in js and "AO.cardDiff" in js
    for words in ("new item", "moved to ", "no longer on the Queue", " changed", "could not read the Queue — retrying"):
        assert words in js, words
    assert "location.replace(found.dataset.goto)" in js  # the opening fallback, in the first client read
    assert "function showAddress" not in js[js.index("AO.queue = function") :]  # /queue?card= is the server's now
