"""TD-1842 (TD-1832's design), §4.5 screen 12 *One answer set*, §4.5a *Queue card: the answer bar*: on the Queue and
a card's page every Decide, Do and grey item ends in one answer bar, its slots in order — the item's answers (the
recommended outlined), **Answer…**, Start session after a thin rule, a gap, then **Dismiss** (a `blocked` outcome or an
exited asker's owed question alone), a fork's PR's **Copy**, **Open** and **⋯** — a slot it has no use for left out;
no item's heading holds a button but its team badge; an item's ⋯ holds no Open and is not drawn where it would hold
nothing; the Inbox's own rows keep their controls."""

from __future__ import annotations

import re

import pytest
from test_queue_board_item import rows as board_world
from test_queue_item_shape import card, inbox
from test_ui_answered_hold import _ask, _pressed, _render, _repos, _rows
from test_ui_inbox import entry
from test_ui_queue_cards import _fold_world

from shiftlead.ui.app import ledger_for_you

START = {"repo": "r", "ref": "TD-1", "card": "r#TD-1", "item": "m-1"}
RULE, RIGHT, DOTS, WHY = "|", "»", "⋯", "why?"


def bar(html: str) -> str:
    """The item's answer bar, whole; '' where it draws none."""
    m = re.search(r'<div class="row gap wrap qabar">(.*?)</div>\s*<div class="st rowerr"', html, re.S)
    return m.group(1) if m else ""


def slots(html: str) -> list[str]:
    """The bar's controls in the order drawn: each button's or link's words, `why?` for the Deny box, `|` for the thin
    rule before Start session, `»` where the right group starts and `⋯` for the item's menu (its items left out)."""
    b = re.sub(r'<div class="menu".*?</div></details>', "</details>", bar(html), flags=re.S)
    tok = re.compile(
        r'class="qrule"|class="row gap qabarright"|class="qdotsbtn"|<input class="denywhy"'
        r"|<(?:button|a)\b[^>]*>(?:<span class=\"alabel\">)?([^<]*)"
    )
    out = []
    for m in tok.finditer(b):
        t = m.group(0)
        out.append(
            RULE
            if "qrule" in t
            else RIGHT
            if "qabarright" in t
            else DOTS
            if "qdotsbtn" in t
            else WHY
            if "denywhy" in t
            else m.group(1).strip()
        )
    return out


def headings(html: str) -> list[str]:
    return re.findall(r'<div class="row gap wrap mhead">(.*?)</div>', html, re.S)


def bare_heading(html: str) -> None:
    """No heading holds a button but the team badge, nor any `.btn` link (§4.5 screen 12 *One answer set*)."""
    hs = headings(html)
    assert hs, "the item draws its heading"
    for h in hs:
        buttons = re.findall(r"<button\b[^>]*>", h)
        assert all('class="badge team"' in b for b in buttons), h
        assert 'class="btn' not in h and "whole entry" not in h, h


# ── mail: ask, steer, a look, a blocked outcome, an exited asker's owed question ──


def test_an_ask_draws_its_answers_answer_start_then_open_and_its_dots():
    e = entry("m-1", "ask", text="Which account?", answers=["work", "home"], recommended=0, start=START)
    html = card(e, "decide")
    assert slots(html) == ["Work", "Home", "Answer…", RULE, "Start session", RIGHT, "Open", DOTS]
    assert '<button class="btn sm answer rec"' in bar(html)  # the recommended one outlined
    assert "Dismiss" not in html, "an open ask is declined by Delete, in its ⋯, never dismissed"
    bare_heading(html)
    # the asker's name opens its Focus, as a holder's word does; the heading's Open is the bar's
    assert '<a class="ref" href="/focus/ao-w1"' in headings(html)[0]
    # an asker with no session: no Open
    assert slots(card({**e, "from_open": None}, "decide")) == ["Work", "Home", "Answer…", RULE, "Start session",
                                                               RIGHT, DOTS]  # fmt: skip


def test_a_steer_draws_go_with_it_among_its_answers_and_no_dismiss():
    e = entry("m-3", "steer", text="Take the work seat?", answers=["work", "home"], default="work", recommended=0)
    html = card({**e, "bound": "2026-09-19T12:00:00Z", "left": "1h"}, "decide")
    assert slots(html) == ["Work", "Home", "Go with it", "Answer…", RIGHT, "Open", DOTS]
    assert "Dismiss" not in html
    assert html.index("1h left") < html.index('class="row gap wrap qabar"'), "its foot above the bar"
    bare_heading(html)


def test_a_look_draws_works_and_not_right_in_slot_one():
    e = entry("m-4", "ask", text="Does it read right?", answers=["Works", "Not right: <what>"], shots=["a.png"])
    html = card(e, "decide")
    assert slots(html) == ["Works", "Not right…", "Answer…", RIGHT, "Open", DOTS]
    bare_heading(html)


def _blocked():
    return entry(
        "m-5", "ask", text="Merge it?", answers=["yes", "no"], closed_reason="replied", answer_given="yes",
        outcome={"state": "blocked", "text": "the PR is red"}, start=START,
    )  # fmt: skip


def test_a_blocked_outcome_draws_answer_start_dismiss_open_and_no_dots():
    html = card(_blocked(), "do")
    assert slots(html) == ["Answer…", RULE, "Start session", RIGHT, "Dismiss", "Open"]
    assert "qdots" not in html
    bare_heading(html)


def test_an_exited_askers_owed_question_draws_dismiss_too():
    e = entry("m-6", "ask", text="Merge it?", answers=["yes", "no"], closed_reason="replied", answer_given="yes")
    e.update(owes=True, asker_gone_quiet=True, asker_state="exited", from_open=None)
    html = card(e, "do")
    assert slots(html) == ["Answer…", RIGHT, "Dismiss"]
    assert "exited without reporting" in html
    bare_heading(html)


def test_a_handed_entrys_blocked_outcome_draws_start_dismiss_open_less_answer():
    e = entry("m-7", "note", text="Draft an entry for the cap", start=START)
    e.update(handed_row=True, holder="ao-tl", holder_name="tl", holder_open="ao-tl", entry={"repo": "r"},
             outcome={"state": "blocked", "text": "cannot reach the repo"})  # fmt: skip
    html = card(e, "do")
    assert slots(html) == [RULE, "Start session", RIGHT, "Dismiss", "Open"]
    assert "Answer…" not in html and "qdots" not in html
    bare_heading(html)


# ── board: decide, act ──


def test_a_board_decide_draws_its_answers_answer_then_open_and_its_dots(tmp_path, monkeypatch):
    _, d = board_world(tmp_path, monkeypatch)
    html = card({**d, "start": START}, "decide")
    assert slots(html) == ["Alpha", "Beta", "Answer…", RULE, "Start session", RIGHT, "Open", DOTS]
    assert 'href="/repo/samscrape#waiting"' in bar(html)  # its row on the Repo page's board
    menu = bar(html).split('class="more qdots"')[1]
    assert ">Done</button>" in menu and ">Open<" not in menu
    bare_heading(html)


def test_an_act_lines_answer_leaves_its_dots_for_slot_two(tmp_path, monkeypatch):
    a, _ = board_world(tmp_path, monkeypatch)
    html = card(a, "do")
    assert slots(html) == ["Done", "Answer…", RIGHT, "Open", DOTS]
    assert re.findall(r'role="menuitem"[^>]*>([^<]*)<', bar(html)) == ["Open board"], "Answer… left its ⋯"
    bare_heading(html)
    # with no editor link its ⋯ would hold nothing, so none is drawn
    assert slots(card({**a, "editor": None}, "do")) == ["Done", "Answer…", RIGHT, "Open"]
    # the Inbox's own row keeps its Reply and Done in its footer, no bar
    page = inbox(a)
    assert "qabar" not in page and ">Reply</button>" in page


# ── ledger: a decision, yours to do, with you, and the grey items ──


def _ledger(tmp_path, monkeypatch, **kw):
    rs, _ = _fold_world(tmp_path, monkeypatch)
    led = rs[next(iter(rs))]["ledger"]["entries"][0]
    led.update(answers=["now", "later"], default=1, **kw)
    row = next(r for g in ledger_for_you(rs, [], {})["groups"] for r in g["rows"])
    return {**row, "home": "queue", "start": START}


def test_a_ledger_decision_draws_its_answers_lift_answer_start_then_open_and_no_dots(tmp_path, monkeypatch):
    row = _ledger(tmp_path, monkeypatch)
    html = card({**row, "why": "decision"}, "decide")
    assert slots(html) == ["Now", "Later", "Lift the hold", "Answer…", RULE, "Start session", RIGHT, "Open"]
    assert "qdots" not in html, "a ledger item's ⋯ held Open alone: it is gone"
    bare_heading(html)
    yours = card({**row, "why": "yours"}, "do")
    assert slots(yours) == ["Now", "Later", "Done", "Answer…", RULE, "Start session", RIGHT, "Open"]


def test_a_with_you_item_draws_no_dots(tmp_path, monkeypatch):
    row = _ledger(tmp_path, monkeypatch)
    html = card({**row, "why": "decision", "with_you": "my-session", "start": {**START, "own": True}}, "with_you")
    assert slots(html) == ["Now", "Later", "Lift the hold", "Answer…", RULE, "Open session", RIGHT, "Open"]
    assert "qdots" not in html
    bare_heading(html)


def test_an_answered_item_draws_open_and_its_dots_none_on_an_entry_you_own(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask()])
    html = _render(row, mode="card", home="queue")
    assert slots(html)[:2] == [RIGHT, "Open"] and "Answer…" not in html and "Start session" not in html
    assert ">Open<" not in html.split('class="more qdots"')[1]
    bare_heading(html)
    # an `Owner: paul` entry: its Done answers it, so no Lift the hold, and no ⋯ to hold it (TD-1829)
    owned = _render({**row, "why": "yours"}, mode="card", home="queue")
    assert slots(owned) == [RIGHT, "Open"] and "Lift the hold" not in owned


def test_a_waits_until_item_draws_open_and_its_dots_none_on_an_entry_you_own(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask()])
    until = {**row, "answered": {**row["answered"], "until": "2026-11-20"}}
    html = _render(until, mode="card", home="queue")
    assert "waits until" in html and slots(html)[:2] == [RIGHT, "Open"]
    bare_heading(html)
    assert slots(_render({**until, "why": "yours"}, mode="card", home="queue")) == [RIGHT, "Open"]


def test_a_handed_item_and_an_applying_item(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask()])
    handed = {**row, "answered": {**row["answered"], "kind": "handed", "name": "tl", "words": "handed"}}
    html = _render(handed, mode="card", home="queue")
    assert "handed to tl" in html and slots(html)[:2] == [RIGHT, "Open"]
    bare_heading(html)
    applying = _render(_pressed(tmp_path), mode="card", home="queue")
    assert slots(applying) == [RIGHT, "Open"], "Open alone"
    bare_heading(applying)


# ── a stopped holder's state row, a red PR, a fork's PR, a stuck row ──


def test_a_permission_draws_allow_deny_and_why_in_slot_one_then_open():
    s = {"id": "st-1", "row": "permission", "sid": "ao-x", "name": "x", "team": "t", "text": "wants to run ls",
         "call": "c1", "deadline": "", "left": "4 min", "state_label": "needs you", "state_class": "needs"}  # fmt: skip
    html = card(s, "do")
    assert slots(html) == ["Allow", "Deny", WHY, RIGHT, "Open"]
    bare_heading(html)


def test_a_red_pr_a_forks_pr_and_a_stuck_row_draw_their_right_group_alone():
    red = {"id": "red_pr:s:7", "row": "red_pr", "repo": "s", "pr": 7, "text": "#7 red", "url": "https://x/7"}
    assert slots(card(red, "do")) == [RIGHT, "Open"]
    fork = {"id": "fork_pr:s:9", "row": "fork_pr", "repo": "s", "pr": 9, "text": "#9", "line": "precheck --pr 9",
            "url": "https://x/9"}  # fmt: skip
    assert slots(card(fork, "do")) == [RIGHT, "Copy", "Open"]
    stuck = {"id": "stuck:1", "row": "stuck", "name": "w1", "text": "stuck 2h: an ask — stalled", "open": "ao-w1"}
    assert slots(card(stuck, "do")) == [RIGHT, "Open"]
    for e in (red, fork, stuck):
        html = card(e, "do")
        assert "qdots" not in html and not re.findall(r"<button\b", "".join(headings(html)))


# ── the Inbox's own rows are unchanged ──


@pytest.mark.parametrize("kind", ["ask", "steer"])
def test_the_inboxs_own_mail_rows_keep_their_heading_open_and_whole_entry(kind):
    e = entry("m-9", kind, text="Which?", answers=["a", "b"], default="a")
    page = inbox(e)
    assert "qabar" not in page and "qrule" not in page
    assert '<a class="btn sm ghost" href="/focus/ao-w1"' in headings(page)[0] and "whole entry ›" in page
    assert ">Reply</button>" in page
    # a blocked outcome keeps its Open, Reply and Dismiss in its footer
    owed = inbox(_blocked())
    assert "qabar" not in owed and ">Reply</button>" in owed and ">Dismiss</button>" in owed


def test_the_inboxs_own_ledger_row_keeps_its_open_and_answered_dots(tmp_path, monkeypatch):
    row = _ledger(tmp_path, monkeypatch)
    page = inbox({**row, "home": "inbox"})
    assert "qabar" not in page and '<a class="btn sm ghost" href="' in page and ">Reply</button>" in page
    (ans,) = _rows(_repos(tmp_path, "r"), [_ask()])
    plain = _render(ans)
    assert "qabar" not in plain and ">Open</a>" in plain.split('class="more qdots"')[1]
