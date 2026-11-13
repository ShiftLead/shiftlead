"""TD-1763, design §4.5 screen 12 *Previews: the Queue reads, the card's page acts*; §4.5a *Queue card: Open card ›,
Answer on its card ›*. On the Queue every item is one line — its kind mark, its sentence (whole in its `title`), its
one-press answers alone, then **Answer on its card ›** — and the header draws **Open card ›** where **Start session**
and **⋯** were; no row draws a ⋯. The card's page, the Inbox and the Repo page draw as before."""

from __future__ import annotations

import pathlib
import re

import pytest
from test_ui_inbox import entry
from test_ui_queue import client, fake, ledger_repos, mail, queue

from shiftlead.ui.app import templates

pytestmark = pytest.mark.unit

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
ADDR = "/card/s%23TD-20?row=s%23TD-21&item=m-1"


def preview(e: dict, want: str = "decide", section: str = "needs") -> str:
    return templates.get_template("queue_mail.html").render(
        e={"addr": ADDR, **e, "want": want}, section=section, preview=True
    )


def buttons(html: str) -> list[str]:
    """Every pressable label in `html`, in order."""
    return [re.sub(r"<[^>]+>", "", b).strip() for b in re.findall(r"<(?:button|a)\b[^>]*>(.*?)</(?:button|a)>", html)]


def test_an_ask_keeps_its_recommended_answer_alone_and_links_its_card():
    text = "Which account should pay for the seat?\n\nwork: the paid seat\n\nmore words"
    e = entry("m-1", "ask", text=text, answers=["work", "home"], consequences=["the paid seat", ""], recommended=1)
    html = preview(e)
    assert buttons(html) == ["Which account should pay for the seat?", "home", "Answer on its card ›"]
    assert html.count("qpreview") == 1 and 'data-msg="m-1"' in html and 'class="btn sm answer rec"' in html
    assert 'data-act="answer" data-id="person" data-msg="m-1" data-index="1"' in html
    # the sentence is the card's page at the item, whole in its title; no consequence, no box, no ⋯
    assert f'<a class="qpsent" href="{ADDR.replace("&", "&amp;")}" data-cardhref title="Which account' in html
    assert "the paid seat" not in html and "more words" not in html
    for gone in (
        "Answer…",
        "qdots",
        "qstart",
        "Go with it",
        "Delete",
        "Pause",
        'rowerr" role="alert" hidden></div>\n</div>\n<',
    ):
        assert gone not in html, gone


def test_with_no_recommended_answer_or_a_looks_pair_nothing_is_pressed_on_the_queue():
    plain = entry("m-1", "ask", text="Which one?", answers=["this", "that"])
    assert buttons(preview(plain)) == ["Which one?", "Answer on its card ›"]
    look = entry("m-1", "ask", text="Does it look right?", answers=["Works", "Not right: <what>"], default="Works")
    got = preview({**look, "shots": ["a.png"]})  # a look: its pair outlines neither, and Not right… is a form
    assert buttons(got) == ["Does it look right?", "Answer on its card ›"] and "Works" not in got


def test_a_steer_keeps_its_default_and_no_go_with_it():
    e = entry(
        "m-1", "steer", text="Ship it tonight?", answers=["ship", "hold"], default="ship", bound="2026-09-19T12:00:00Z"
    )
    assert buttons(preview(e)) == ["Ship it tonight?", "ship", "Answer on its card ›"]


def test_an_act_line_keeps_done_and_not_have_a_session_do_it():
    line = {"row": "board", "id": "board:/r:3", "key": "board:k1", "kind": "act", "repo_name": "r", "repo": "r",
            "board": "/r/docs/user_attention.md", "line": 3, "text": "**Rotate it.** Context: TD-050.",
            "lead": "Rotate it.", "parts": [], "decided": None, "session_do": True}  # fmt: skip
    html = preview(line, "do")
    assert buttons(html) == ["Rotate it.", "Done", "Answer on its card ›"]
    assert 'data-board-act="done"' in html and "Have a session do it" not in html and 'data-text="' in html
    assert 'class="mailrow qpreview boardrow"' in html


def test_a_ledger_row_keeps_no_done_and_no_lift_the_hold():
    row = {"row": "ledger", "id": "TD-021", "row_id": "ledger:s:TD-021", "name": "s", "root": "/r/s", "title": "t",
           "why": "yours", "home": "queue", "on_card": "s#TD-20", "on_row": "s#TD-21"}  # fmt: skip
    assert buttons(preview(row, "do")) == ["TD-021 t", "Answer on its card ›"]
    decision = {**row, "why": "decision", "answers": ["go", "stop"], "default": "stop"}
    html = preview(decision)
    assert buttons(html) == ["TD-021 t", "stop", "Answer on its card ›"] and "Lift the hold" not in html
    assert 'data-msg="ledger:s:TD-021"' in html and 'class="mailrow qpreview ledgerrow"' in html


@pytest.mark.parametrize(
    ("section", "act", "confirm"),
    [("fyi", "unmail", "Dismiss this entry?"), ("waiting", "dismiss", "the debt ends and w1 is told"),
     ("answered", "dismiss", "")],
)  # fmt: skip
def test_a_read_item_keeps_dismiss_in_its_rows_own_words_and_nothing_else(section, act, confirm):
    extra = {"answered": {"asker": "ao-x", "question": "q?", "source": "s"}} if section == "answered" else {}
    html = preview(entry("m-1", "note", text="It merged.", **extra), "read", section)
    assert buttons(html) == ["It merged.", "Dismiss", "Answer on its card ›"]
    assert f'data-act="{act}"' in html and (confirm in html if confirm else "data-confirm" not in html)
    assert "Put on the board" not in html and "Overrule" not in html


def test_a_permission_keeps_allow_and_a_deny_with_no_reason_and_a_question_its_open():
    perm = {"row": "permission", "id": "state:ao-w1", "sid": "ao-w1", "name": "w1", "call": "c-1", "text": "Bash: ls"}
    html = preview(perm, "decide")
    assert buttons(html) == ["Bash: ls", "Allow", "Deny", "Answer on its card ›"]
    assert "denywhy" not in html and 'data-act="deny" data-id="ao-w1" data-call="c-1"' in html
    q = {**perm, "row": "question"}
    assert buttons(preview(q, "decide")) == ["Bash: ls", "Open", "Answer on its card ›"]
    red = {"row": "red_pr", "id": "red:s:9", "repo": "s", "pr": 9, "url": "https://x/pull/9", "text": "#9 failing"}
    assert buttons(preview(red, "do")) == ["#9 failing", "Open", "Answer on its card ›"]


def test_the_queue_header_draws_open_card_and_no_row_or_header_draws_a_dots(tmp_path, monkeypatch):
    c = client(
        monkeypatch, tmp_path, fake(queue(), [mail("m1", "TD-21: which one?", answers=["a", "b"])], ledger_repos())
    )
    html = c.get("/queue").text
    card20 = html[html.index('data-card="s#TD-20"') : html.index('data-card="s#TD-30"')]
    head = card20[: card20.index('class="qgap"')]
    assert head.count("Open card ›") == 1 and 'href="/card/s%23TD-20" data-cardhref' in head
    assert "qdots" not in html and "qstart" not in html and "Answer…" not in html
    # every item a preview, each linking its card's page at it
    assert card20.count('class="mailrow qpreview') == card20.count("Answer on its card ›") == 3
    assert 'href="/card/s%23TD-20?row=s%23TD-21&amp;item=m1"' in card20
    # the part the page re-reads draws the same
    part = c.get("/queue?part=1").text
    assert "Open card ›" in part and "qpreview" in part and "qdots" not in part


def test_the_cards_page_the_inbox_and_the_repo_rows_keep_their_controls(tmp_path, monkeypatch):
    c = client(
        monkeypatch, tmp_path, fake(queue(), [mail("m1", "TD-21: which one?", answers=["a", "b"])], ledger_repos())
    )
    page = c.get("/card/s%23TD-20").text
    assert "qpreview" not in page and "Open card ›" not in page and "Answer on its card ›" not in page
    assert "qdots" in page and ">Answer…</button>" in page and ">Lift the hold</button>" in page
    inbox = c.get("/inbox").text
    assert "qpreview" not in inbox


def test_the_queue_writes_its_card_before_opening_its_page_and_anchors_on_it_coming_back():
    js = (UI / "static" / "app.js").read_text(encoding="utf-8")
    q = js[js.index("AO.queue = function") :]
    # a plain press on a card's link writes the card and its screen place; a modifier or a middle click does not
    assert "e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey" in q
    assert "AO.qSess.set(CARD_FROM, { card: c.dataset.card, group:" in q
    # a back-forward return reads it, clears it, and draws whole on it; a plain load only clears it
    show = q[q.index('window.addEventListener("pageshow"') :]
    show = show[: show.index("});")]
    assert show.index("AO.qSess.set(CARD_FROM, null)") < show.index('nav.type === "back_forward"')
    assert "anchorOn = o && o.card ? o : null;" in show and "whole = true;" in show
    draw = q[q.index("function drawWhole(") : q.index("function slide(")]
    assert "ownG.dataset.group === at.group ? own : (at.after || []).map(at1).find(Boolean)" in draw
    # the card's page goes back in history only when the Queue opened it in this tab (TD-1762's side)
    assert 'from.card === id && ref === "/queue" && history.length > 1' in js
