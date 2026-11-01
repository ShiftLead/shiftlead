"""TD-914, design §4.5 screen 12 *Three verbs* (Answer, ⋯), *No dates of the person's on a card*; §4.5a *Queue card:
answers, Answer…*, *Queue card: ⋯*, *Queue card: what needs the person*. On a card a Decide or Do item draws its
answers as buttons, the recommended one outlined with no caption, each with what it leads to beside it, then its
kind's own answers and **Answer…**; its own controls (Delete, Pause / Resume, Send to reviewer, a board line's Done)
are behind its ⋯, as a row's and the header's are. No Reply word on a card, no Snooze; the Inbox draws as before."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from test_queue_item_shape import card, inbox
from test_ui_inbox import entry
from test_ui_queue import client, fake, mail, queue
from test_ui_queue_cards import _fold_world

from shiftlead.ui.app import ledger_for_you, templates

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"


def dots(html: str) -> list[str]:
    """The names inside each ⋯ in `html`, in order: the label after *the team's controls:*."""
    return re.findall(r'class="qdotsbtn"[^>]*aria-label="the team\'s controls: ([^"]*)"', html)


def test_a_decide_ask_draws_its_answer_row_and_its_controls_behind_its_dots():
    e = entry(
        "m-1",
        "ask",
        text="Which account?",
        answers=["work", "home"],
        consequences=["the paid seat", ""],
        recommended=0,
    )
    html = card(e, "decide")
    row = html[html.index('class="row gap wrap sugg qanswers"') :]
    assert '<button class="btn sm answer rec" type="button" data-act="answer"' in row  # the recommended, outlined
    assert '<span class="alabel">work</span></button><span class="st alead">the paid seat</span>' in row
    assert '<span class="alabel">home</span></button></span>' in row  # no consequence, nothing beside it
    assert ">Answer…</button>" in row and 'data-act="reply"' in row
    assert "default</span>" not in html and "suggested by" not in html  # no caption: the outline is the convention
    assert dots(html) == ["Delete"] and 'role="menuitem" type="button" data-act="unmail"' in html
    assert not re.search(r"\bReply\b", html) and ">Snooze" not in html
    # a question with a default and no `recommended` outlines its default
    plain = card({**e, "recommended": None, "default": "home"}, "decide")
    assert (
        '<button class="btn sm answer rec" type="button" data-act="answer" data-id="person" data-msg="m-1" '
        'data-index="1"' in plain
    )
    # the Inbox's own row is unchanged
    page = inbox(e)
    assert ">Reply</button>" in page and "qanswers" not in page and "qdots" not in page and ">Snooze<" in page


def test_a_look_sent_for_review_has_send_to_reviewer_behind_its_dots():
    e = entry("m-2", "ask", text="Does it read right?", answers=["work", "home"])
    html = card({**e, "review_seat": "ao-tl", "review_name": "techlead", "team": "t"}, "decide")
    assert dots(html) == ["Delete, Send to reviewer"]
    assert 'role="menuitem" type="button" data-act="hand_look"' in html


def test_a_steer_goes_with_it_in_its_answer_row_and_pauses_behind_its_dots():
    e = entry("m-3", "steer", text="Take the work seat?", answers=["work", "home"], default="work", recommended=0)
    html = card({**e, "bound": "2026-09-19T12:00:00Z", "left": "1h"}, "decide")
    row = html[html.index("qanswers") : html.index('class="row gap wrap mfoot"')]
    assert 'data-act="gowithit"' in row and ">Go with it</button>" in row and ">Answer…</button>" in row
    assert 'class="btn sm answer rec"' in row
    assert dots(html) == ["Pause"] and 'data-act="pause"' in html.split('class="qdotsbtn"', 1)[1]
    assert dots(card({**e, "paused_at": "2026-09-19T10:30:00Z"}, "decide")) == ["Resume"]
    assert not re.search(r"\bReply\b", html)


def test_a_ledger_item_answers_done_or_lift_the_hold_in_its_row_and_opens_behind_its_dots(tmp_path, monkeypatch):
    rs, _ = _fold_world(tmp_path, monkeypatch)
    led = rs[next(iter(rs))]["ledger"]["entries"][0]
    led.update(owner="paul", answers=["now", "later"], default=1)
    row = next(r for g in ledger_for_you(rs, [], {})["groups"] for r in g["rows"])
    row = {**row, "home": "queue"}
    html = card(row, "do")
    ans = html[html.index("qanswers") : html.index('class="row gap wrap mfoot"')]
    assert 'class="btn sm answer rec" type="button" data-act="ledger"' in ans and ">later<" in ans  # the default
    assert 'data-words="done"' in ans and ">Done</button>" in ans and 'data-act="ledger_reply"' in ans
    assert ">Answer…</button>" in ans and "Lift the hold" not in ans
    assert dots(html) == ["Open"] and not re.search(r"\bReply\b", html) and "Go with it" not in html
    assert 'data-act="ledger_start"' not in html  # Start session is the card's header's alone (TD-912)
    decision = card({**row, "why": "decision"}, "decide")
    assert ">Lift the hold</button>" in decision[decision.index("qanswers") :]
    # the Inbox's own ledger row keeps Reply, Go with it and its controls inline (§4.5a *Inbox row: ledger entry*)
    page = inbox({**row, "home": "inbox"})
    assert ">Reply</button>" in page and ">Go with it</button>" in page and "qdots" not in page
    assert 'data-road="done"' not in page and "Hold…" not in page and "ledger_hold" not in page  # yours: no Done…


def test_a_board_line_answers_on_its_line_and_checks_off_behind_its_dots(tmp_path, monkeypatch):
    from test_ui_board import host, item, report

    from shiftlead.ui.app import board_rows

    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    of = {"name": "samscrape", "label": "samscrape", "teams": ["sam"]}
    (b,) = board_rows(
        report(root, item(9, "pick a name. Due: 2026-09-20.", "2026-09-20", "2d")), {str(root.resolve()): of}
    )
    html = card(b, "decide")
    ans = html[html.index("qanswers") :]
    assert 'data-act="board_reply"' in ans and ">Answer…</button>" in ans
    assert dots(html) == ["Done, Open board"]
    assert 'role="menuitem" data-file-link' in html  # the arrows reach Open board too
    assert 'role="menuitem" type="button" data-act="board" data-id="person" data-board-act="done"' in html
    assert not re.search(r"\bReply\b", html) and "Snooze" not in html
    # a decided line under *waiting on them*, opened from its Read line: no Answer row, its Done behind its ⋯
    waiting = card(
        {**b, "decided": {"text": "go", "date": "2026-09-19"}, "waiting_on": "waiting on w1"}, "read", "waiting"
    )
    assert "qanswers" not in waiting and dots(waiting) == ["Done, Open board"] and not re.search(r"\bReply\b", waiting)
    page = inbox(b)
    assert ">Reply</button>" in page and "qdots" not in page


def test_a_look_on_a_card_draws_works_and_not_right_and_not_right_opens_the_composer(tmp_path, monkeypatch):
    """§4.5a **Works** / **Not right…** on a card (TD-922): a look — a mail `ask` with `shots`, or a board line with
    the pair — draws its two answers as the pair, **Not right…** opening the composer rather than answering, with no
    `rec` outline and no caption on either."""
    from test_ui_board import host, look_item, report

    from shiftlead.ui.app import board_rows

    def pair(html):
        row = html[html.index('class="row gap wrap sugg qanswers"') :]
        btns = re.findall(
            r'<button class="btn sm answer([^"]*)" type="button"([^>]*)><span class="alabel">(.*?)</span>', row
        )
        assert [label for _, _, label in btns] == ["Works", "Not right…"]
        assert all(not cls for cls, _, _ in btns)  # no outline on either
        assert "default</span>" not in html and "suggested by" not in html
        return btns[0][1], btns[1][1]

    e = entry("m-4", "ask", text="Does the ring read right?", answers=["Works", "Not right: <what>"], recommended=0)
    works, form = pair(card({**e, "shots": ["a.png"]}, "decide"))
    assert 'data-act="answer"' in works and 'data-index="0"' in works
    assert 'data-act="reply"' in form and 'data-begun="Not right: "' in form and 'data-msg="m-4"' in form
    assert "data-index" not in form

    host(tmp_path, monkeypatch)
    (b,) = board_rows(report(tmp_path / "samscrape", look_item()))
    assert b["pair"]
    works, form = pair(card(b, "decide"))
    assert 'data-act="board"' in works and 'data-answer="Works"' in works
    assert 'data-act="board_notright"' in form and 'data-head="One look at the ring"' in form
    assert "data-answer=" not in form and "data-board-act" not in form


def test_a_red_pr_item_has_no_answer_row_and_no_dots():
    src = (UI / "templates" / "inbox_row.html").read_text(encoding="utf-8")
    red = src[src.index("{% macro red_pr_row(e, section) -%}") :]
    red = red[: red.index("{%- endmacro %}")]
    assert "answer_row" not in red and "qrow.dots" not in red


def test_a_rows_dots_hold_its_controls_in_order_and_the_headers_act_on_the_top_entry():
    q = templates.get_template("queue_row.html").module
    r = {"id": "TD-5", "title": "t", "repo": "s", "page": "pickable", "state": "ready", "needs": ""}
    html = str(q.menu(r))
    assert dots(html) == ["Back to design…, Done…, Open"]
    # bare at every width: its names in its title and label, never drawn beside it on hover (TD-926)
    assert 'title="Back to design… · Done… · Open"' in html
    assert 'aria-label="the team\'s controls: Back to design…, Done…, Open">⋯</summary>' in html
    assert "qdotsnames" not in html
    assert "qdotsnames" not in (UI / "static" / "app.css").read_text(encoding="utf-8")
    acts = re.findall(
        r'<button role="menuitem" type="button" data-act="(\w+)"(?: data-id="person")?(?: data-road="(\w+)")?'
        r'|<a href="([^"]+)" role="menuitem"',
        html,
    )
    assert [(a, road) if a else c for a, road, c in acts] == [
        ("ledger", "design"),
        ("ledger", "done"),
        "/repo/s#TD-5",
    ]
    assert "btn sm ghost" not in html  # the menu's own items, not the inline buttons
    # no Hold… and no Release (TD-1297): an entry held out of the lanes is a `decision (<person>)` row
    design = str(q.menu({**r, "page": "design"}))
    assert dots(design) == ["Done…, Open"] and 'title="Done… · Open"' in design
    assert 'aria-label="the team\'s controls: Done…, Open"' in design and "ledger_release" not in design
    assert dots(str(q.menu({**r, "archived": True}))) == ["Open"]
    assert dots(str(q.menu({**r, "needs": "owner", "page": "for-you"}))) == ["Open"]  # its Done is an answer


def test_the_queue_page_draws_no_reply_word_and_the_headers_dots(tmp_path, monkeypatch):
    entries = [mail("m1", "TD-21: which one?", answers=["this", "that"]), mail("m9", "TD-20 is the parent")]
    c = client(monkeypatch, tmp_path, fake(queue(), entries))
    html = c.get("/queue").text
    body = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    assert not re.search(r"\bReply\b", body) and ">Snooze" not in body
    card20 = html[html.index('data-card="s#TD-20"') : html.index('data-card="s#TD-30"')]
    head = card20[: card20.index('class="qgap"')]
    assert 'class="more qdots"' in head and 'href="/repo/s#TD-20" role="menuitem"' in head  # the top entry's
    assert ">Answer…</button>" in card20
    inbox_page = c.get("/inbox").text
    assert "qdots" not in inbox_page


PROBE = """
const fs = require("fs");
const noop = () => {};
const heard = {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: (type, f) => (heard[type] = heard[type] || []).push(f), createElement: el, activeElement: null };
global.window = {}; global.document = document; global.Event = class { constructor(t) { this.type = t; } };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const focusable = (name) => { const o = { name, focus: () => { document.activeElement = o; } }; return o; };
const mark = focusable("mark"), items = ["Design", "Done", "Open"].map(focusable);
const d = { open: false, querySelector: (s) => (s === "summary" ? mark : null), querySelectorAll: () => items };
const at = (t) => ({ closest: (s) => (s === "details.qdots" ? d : null), ...t });
const press = (key, target) => AO.qDots({ key, target: at(target || {}) });
const out = {};
document.activeElement = mark;
out.down = press("ArrowDown"); out.opened = d.open; out.first = document.activeElement.name;
press("ArrowDown"); out.second = document.activeElement.name;
press("ArrowUp"); press("ArrowUp"); out.wrapped = document.activeElement.name;
out.esc = press("Escape"); out.closed = !d.open; out.back = document.activeElement.name;
out.esc_closed = press("Escape");
out.other = press("x");
out.outside = AO.qDots({ key: "ArrowDown", target: { closest: () => null } });
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_dots_keyboard_model_opens_moves_and_closes_back_on_the_mark(tmp_path):
    probe = tmp_path / "dots_probe.js"
    probe.write_text(PROBE)
    got = subprocess.run(
        ["node", str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=60, check=True
    )
    out = json.loads(got.stdout.strip().splitlines()[-1])
    assert out == {
        "down": True,
        "opened": True,
        "first": "Design",
        "second": "Done",
        "wrapped": "Open",
        "esc": True,
        "closed": True,
        "back": "mark",
        "esc_closed": False,
        "other": False,
        "outside": False,
    }
