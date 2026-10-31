"""TD-1245 (TD-1066's design), §4.5 screen 12 *Three wants*, *An item's shape* (*A board item says where its task
is*), *Three verbs*; §4.5a *Queue card: what needs the person*, *Queue card: answers, Answer…*: on a card an `act`
board line is a Do whose answer is **Done**, its sentence the line's bold head, its kind line *do · in <repo> · board
line*, its prefix and key under *context*, its standing Answer…'s title, and no *on the board —* footer; a `decide`
line stays Decide with its answers, and the Inbox's board row is as it was."""

from __future__ import annotations

import re

from markupsafe import Markup
from test_queue_card_verbs import dots
from test_queue_item_shape import card, inbox
from test_queue_wants import NOW, queue
from test_ui_board import host, item, report

from shiftlead.ui import inbox as inbox_mod
from shiftlead.ui.app import board_rows, templates
from shiftlead.ui.queue import attach, queue_view, want_of

ACT = (
    "act 2026-10-26 (session `designer-ao-1` on kmaster) — **File one entry in agent-cadence's ledger, so the "
    "promote can check main's head.** Until it is filed, auto cannot promote this repo. The full text is in TD-1025. "
    "Context: agent-cadence#TD-151, TD-1033. Due: 2026-10-29."
)
DECIDE = "decide 2026-10-27 (session `d-1` on kmaster) — **Which name?** Context: TD-1033. Due: 2026-10-29."
STANDING = {"text": "still on TD-1033 — grinder-ao-2 holds it"}


def rows(tmp_path, monkeypatch):
    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    of = {"name": "samscrape", "label": "samscrape", "teams": ["sam"]}
    act = {**item(9, ACT, "2026-10-29", "1d overdue"), "kind": "act", "key": "741e117b", "session": "designer-ao-1"}
    act["detail"] = ["- the entry's text is in TD-1025"]
    dec = {**item(12, DECIDE, "2026-10-29", "1d overdue"), "kind": "decide", "key": "91aa0000"}
    dec["answers"], dec["default"] = ["Alpha", "Beta"], "Alpha"
    a, d = board_rows(report(root, act, dec), {str(root.resolve()): of})
    return {**a, "key": "board:741e117b", "standing": STANDING}, {**d, "key": "board:91aa0000", "standing": STANDING}


def test_an_act_line_is_a_do_and_its_card_item_leads_with_its_task(tmp_path, monkeypatch):
    a, _ = rows(tmp_path, monkeypatch)
    assert want_of(a, "needs") == "do"
    assert a["card"]["in_repo"] == "agent-cadence"
    html = card(a, "do")
    head = html[: html.index('class="body md sentence"')]
    assert 'k-do">do</span>' in head and "in agent-cadence</b>" in head and "board line</span>" in head
    assert "still on TD-1033" not in head and "board:741e117b" not in head  # no standing, no key in the head
    sentence = re.search(r'class="body md sentence">(.*?)</div>', html, re.S).group(1)
    assert "File one entry in agent-cadence" in sentence and "act 2026-10-26" not in sentence
    assert "Until it is filed, auto cannot promote this repo." in html  # the next sentence, its consequence
    # the Answer row: Done alone, outlined; Answer… in the ⋯, its title the standing
    ans = html[html.index("qanswers") : html.index("</div>", html.index("qanswers"))]
    assert re.findall(r">([^<>]+)</button>", ans) == ["Done"] and 'class="btn sm answer rec"' in ans
    assert "landed on its origin by shiftlead's own pull request" in ans  # the footer's words, Done's title
    assert dots(html) == ["Answer…, Open board"]
    assert re.search(r'role="menuitem" type="button" data-act="board_reply"[^>]*title="designer-ao-1 · still on', html)
    assert "on the board —" not in html
    # *context*: lazy on a card, its body the prefix, the rest of the line, the key and the sub-bullets
    assert 'data-fold="cb:board:' in html
    body = templates.get_template("fold_body.html").render(kind="boardcard", e=a)
    assert "act 2026-10-26" in body and "The full text is in TD-1025." in body and "board:741e117b" in body
    assert "agent-cadence#TD-151" in body and "the entry&#x27;s text is in TD-1025" in body


def test_a_decide_line_on_the_same_card_stays_decide_and_the_card_counts_the_act_as_do(tmp_path, monkeypatch):
    a, d = rows(tmp_path, monkeypatch)
    html = card(d, "decide")
    assert want_of(d, "needs") == "decide" and 'k-decide">decide</span>' in html and "in agent-cadence" not in html
    assert d["card"]["in_repo"] == "" and "Which name?" in html
    ans = html[html.index("qanswers") :]
    assert ">Alpha</span>" in ans and ">Beta</span>" in ans and ">Answer…</button>" in ans
    assert dots(html) == ["Done, Open board"]  # a decide line's Done stays behind its ⋯
    on = {"home": "queue", "on_card": "s#TD-2", "on_row": "s#TD-2"}
    got = attach({"needs": [{**a, **on}, {**d, **on}]}, lambda e, sec: Markup(f"<{e['key']}>"))
    v = queue_view(queue(), NOW, got)
    two = v["up_next"][1]
    assert two["wants"]["n"]["do"] == 1 and two["wants"]["n"]["decide"] == 1 and v["n"]["do"] == 1
    pill = templates.env.get_template("queue_card.html").module.card(two)
    assert ">Decide 1 · Do 1</span>" in pill


def test_the_inbox_board_row_is_unchanged(tmp_path, monkeypatch):
    a, _ = rows(tmp_path, monkeypatch)
    page = inbox(a)
    assert "on the board —" in page and ">Reply</button>" in page and "still on TD-1033" in page
    assert "board line</span>" not in page and "in agent-cadence</b>" not in page


def test_a_line_with_no_bold_head_is_its_own_sentence():
    got = inbox_mod.board_card("act 2026-10-26 — run the setup once. Context: TD-9.", {}, "samscrape")
    assert got["sentence"] == "act 2026-10-26 — run the setup once." and got["leads"] == "" and got["in_repo"] == ""
    assert got["context"] == "Context: TD-9"


def test_a_bold_word_past_the_heads_reach_is_no_head():
    late = "decide 2026-10-01 — " + "word " * 60 + "**foo** bar."
    got = inbox_mod.board_card(late, {}, "samscrape")
    assert got["sentence"].startswith("decide 2026-10-01") and got["sentence"].endswith("**foo** bar.")
