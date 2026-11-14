"""TD-1809, design §4.5 screen 12 *The Queue's words* (TD-1801): the Queue and the card's page draw for a person —
dates in words by one Jinja global, `short_date`, against the host's local today; a row's *waits until <ISO date>*
rewritten and every other state passed through; ids bare in the card's own repo and another repo's qualified, their
`data-` values and hrefs kept qualified; titles without raw markup; kind lines that say where an item comes from;
labels with a capital. The Inbox and the Repo page, which pass no `words`, keep their words. The counts in words and
their JS twin are `test_ui_qcard_press.py`'s."""

from __future__ import annotations

from datetime import date, timedelta

from markupsafe import Markup
from test_queue_item_shape import card, inbox
from test_ui_queue_cards import _fold_world

from shiftlead.ui.app import ledger_for_you, templates
from shiftlead.ui.common import bare_id, own_repo, short_date, state_words

TODAY = date(2026, 11, 14)
ROW = templates.env.get_template("queue_row.html").module


def test_short_date_draws_the_designs_table():
    due = {
        d: short_date(TODAY + timedelta(days=d), due=True, today=TODAY) for d in (0, 1, 2, 5, 13, 14, 40, -1, -2, -45)
    }
    assert due == {
        0: "due today", 1: "due tomorrow", 2: "due in 2 days", 5: "due in 5 days", 13: "due in 13 days",
        14: "due Nov 28", 40: "due Dec 24", -1: "due yesterday", -2: "due 2 days ago", -45: "due 45 days ago",
    }  # fmt: skip
    assert short_date("2026-11-19", due=True, today=TODAY) == "due in 5 days"  # an ISO string as the reading has it
    assert short_date("2027-01-05", due=True, today=TODAY) == "due Jan 5 2027"  # another year's carries its year
    assert short_date("", due=True, today=TODAY) == "no due date"  # an item with no Due: keeps its words
    # any other ISO date: the month and day, the year where it is not this year's
    assert short_date("2026-11-19", today=TODAY) == "Nov 19"
    assert short_date("2025-11-19", today=TODAY) == "Nov 19 2025"
    assert short_date(date(2026, 3, 1), today=TODAY) == "Mar 1"
    assert short_date("", today=TODAY) == "" and short_date("someday", today=TODAY) == ""  # nothing that reads
    # against the host's local today by default
    assert short_date(date.today(), due=True) == "due today"


def test_a_waits_until_state_is_rewritten_and_every_other_state_passed_through():
    assert state_words("waits until 2026-11-19", today=TODAY) == "waits until Nov 19"
    assert state_words("waits until 2027-02-01", today=TODAY) == "waits until Feb 1 2027"
    for s in ("waits on an event", "waits until Paul says", "held by grinder-1", "done #12", "ready", ""):
        assert state_words(s, today=TODAY) == s
    assert state_words("waits until 2026-11-19 or later", today=TODAY) == "waits until 2026-11-19 or later"


def test_the_cards_own_repo_and_bare_ids():
    assert own_repo("shiftlead#TD-1551") == "shiftlead" and own_repo("loose:other#TD-009") == "other"
    assert bare_id("shiftlead#TD-1774", "shiftlead") == "TD-1774"
    assert bare_id("agent-cadence#TD-243", "shiftlead") == "agent-cadence#TD-243"
    assert bare_id("TD-12", "shiftlead") == "TD-12" and bare_id("shiftlead#TD-1", "") == "shiftlead#TD-1"


def _row(**kw):
    return {"qid": "s#TD-21", "show": "s#TD-21", "title": "Fix `ao msg` for *everyone*", "priority": "high",
            "afters": ["s#TD-20", "db#TD-5"], "state": "waits until 2026-11-19", **kw}  # fmt: skip


def test_a_rows_words_on_the_queue_and_the_repo_page_unchanged():
    on_queue = str(ROW.row(_row(), "", True, "s"))
    # ids bare in the card's own repo, another repo's qualified; the anchor and `data-on` kept qualified
    assert (
        '<a class="qon" href="#s#TD-20" data-on="s#TD-20" title="waits on s#TD-20: scroll to it">TD-20</a>' in on_queue
    )
    assert 'href="#db#TD-5" data-on="db#TD-5" title="waits on db#TD-5: scroll to it">db#TD-5</a>' in on_queue
    # the title's inline code and emphasis drawn, no raw mark left; the date in words
    assert "Fix <code>ao msg</code> for <em>everyone</em>" in on_queue and "`" not in on_queue
    assert ">waits until " + short_date("2026-11-19") + "<" in on_queue and "2026-11-19" not in on_queue
    # the row's own id keeps its repo: a card's repo is drawn nowhere else
    assert '<span class="qid mono">s#TD-21</span>' in on_queue
    # the Repo page passes no `words`: its row is as before
    repo_page = str(ROW.row(_row()))
    assert ">s#TD-20</a>" in repo_page and ">waits until 2026-11-19<" in repo_page
    assert "Fix `ao msg` for *everyone*" in repo_page


def test_an_item_about_another_row_says_on_its_bare_id():
    ms = [{"on": "s#TD-21", "html": Markup("<p>x</p>")}, {"on": "db#TD-5", "html": Markup("<p>y</p>")}]
    html = str(ROW.items(ms, True, "s"))
    assert 'href="#s#TD-21" data-on="s#TD-21" title="the row it is about">on TD-21</a>' in html
    assert ">on db#TD-5</a>" in html
    assert ">on s#TD-21</a>" in str(ROW.items(ms))  # without `words`, as before


def _board(tmp_path, monkeypatch, due: str) -> dict:
    from test_ui_board import host, item, report

    from shiftlead.ui.app import board_rows

    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    of = {"name": "samscrape", "label": "samscrape", "teams": ["sam"]}
    (b,) = board_rows(
        report(root, item(9, f"pick a `name`. Due: {due}.", due, "3d overdue")), {str(root.resolve()): of}
    )
    return b


def test_a_board_item_says_where_it_comes_from_and_its_due_date_in_words(tmp_path, monkeypatch):
    due = (date.today() - timedelta(days=3)).isoformat()
    b = _board(tmp_path, monkeypatch, due)
    html = card(b, "do")
    assert '<span class="badge kindmark k-do">Do</span><span class="st">· from samscrape\'s board</span>' in html
    assert "board line" not in html
    assert f'title="Due: {due}">due 3 days ago</span>' in html and "overdue" not in html
    # coming, unshown and snoozed draw the same table over `Due:`, never `ahead`'s words
    ahead = (date.today() + timedelta(days=6)).isoformat()
    later = card({**b, "due": ahead, "ahead": "due in 6 d · Oct 4"}, "do", "coming")
    assert ">due in 6 days</span>" in later and "6 d ·" not in later
    assert ">no due date</span>" in card({**b, "due": "", "due_tag": "no due date"}, "do")
    # a Read line: *Read · from <repo>'s board*, its subject without its markup, its due words
    read = card(b, "read", "fyi")
    assert '<span class="badge kindmark k-board">Read</span><span class="st">· from samscrape\'s board</span>' in read
    assert "board · " not in read and ">due 3 days ago</span>" in read
    # the Inbox's own row keeps its words
    page = inbox(b)
    assert ">board</span>" in page and "3d overdue" in page and "from samscrape's board" not in page


def test_a_board_lines_holds_are_bare_in_the_cards_own_repo(tmp_path, monkeypatch):
    b = _board(tmp_path, monkeypatch, date.today().isoformat())
    holds = [
        {"id": "samscrape#TD-3", "show": "TD-3", "href": "#samscrape#TD-3", "repo_href": "/repo/samscrape#TD-3"},
        {"id": "db#TD-5", "show": "TD-5", "href": "/repo/db#TD-5", "repo_href": "/repo/db#TD-5"},
    ]
    one = templates.get_template("queue_mail.html")
    html = one.render(e={**b, "holds": holds, "want": "do"}, section="needs", own="samscrape")
    assert 'href="#samscrape#TD-3" data-repo-href="/repo/samscrape#TD-3">TD-3</a>' in html
    assert 'href="/repo/db#TD-5" data-repo-href="/repo/db#TD-5">db#TD-5</a>' in html  # another repo's keeps it
    assert ">due today</span>" in html


def test_a_ledger_items_kind_line_title_and_kept_wait(tmp_path, monkeypatch):
    rs, _ = _fold_world(tmp_path, monkeypatch)
    led = rs[next(iter(rs))]["ledger"]["entries"][0]
    led.update(owner="paul")
    row = next(r for g in ledger_for_you(rs, [], {})["groups"] for r in g["rows"])
    row = {**row, "home": "queue", "title": "Rename `ao td` to *ao entry*", "ask": ""}
    assert row["kind"] == "ledger · yours"
    do = card(row, "do")
    assert '<span class="badge kindmark k-ledger">Do</span><span class="st">· from the ledger</span>' in do
    assert "Rename <code>ao td</code> to <em>ao entry</em>" in do and "ledger · yours" not in do
    decide = card({**row, "kind": "ledger · your decision", "why": "decision"}, "decide")
    assert '<span class="badge kindmark k-ledger">Decide</span><span class="st">· from the ledger</span>' in decide
    # a *Not yet* kept waiting: its date in words at both sites; the Inbox's row keeps the ISO date
    ans = {"until": "2026-12-01", "words": 'you answered "not yet"', "age": "1d", "kind": "board", "board": {},
           "name": "techlead"}  # fmt: skip
    kept = card({**row, "kind": "ledger · your decision", "answered": ans}, "decide")
    words = short_date("2026-12-01")
    assert f">waits until {words}</span>" in kept and f"it waits until {words}, then you are asked again" in kept
    assert "2026-12-01" not in kept.replace('data-at="2026-12-01"', "")
    page = inbox({**row, "home": "inbox", "kind": "ledger · your decision", "answered": ans})
    assert ">ledger · your decision</span>" in page and "waits until 2026-12-01" in page


def test_a_mail_items_kind_mark_and_labels_start_with_a_capital_on_a_card_alone():
    from test_ui_inbox import entry

    e = entry("m-1", "ask", text="Which account?", answers=["work", "home"])
    html = card(e, "decide")
    assert '<span class="badge kindmark k-ask">Ask</span>' in html
    assert '<span class="alabel">Work</span>' in html and 'data-index="0"' in html
    page = inbox(e)
    assert '<span class="badge kindmark k-ask">ask</span>' in page
