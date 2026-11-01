# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-771 slice 1, design §4.5 screen 12 *Queue* and §4.5a *Queue page*, *Sessions top bar: Queue tab*: the
page draws the home's `queue` reading in three groups — Recently completed with its window picker and
its counts, In progress with the other work, Up next numbered with the grip and ⤒ ↑ ↓ — by the partials
the Repo page shares; the top bar carries a Queue tab after Inbox, with no number of its own."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from sessionorc.client import AgentError
from shiftlead.ui.inbox import horizon_left, inbox_sections, rail_rows
from shiftlead.ui.queue import (
    apply_picks,
    attach,
    card_index,
    filter_chips,
    item_home,
    picks_query,
    queue_picks,
    queue_view,
    split_later,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 16, 20, 0, tzinfo=UTC)


def row(repo: str, tid: str, title: str, **kw) -> dict:
    return {"qid": f"{repo}#{tid}", "repo": repo, "id": tid, "title": title, "priority": "Medium", "state": "ready",
            "needs": None, "pr": None, "holder": None, "key": "", "lined": False, "archived": False, **kw}  # fmt: skip


def card(top: dict, rows=(), group="up_next", place=None, status="ready", **kw) -> dict:
    members = [top["qid"], *(r["qid"] for r in rows if not r["archived"])]
    done = sum(1 for r in rows if r["archived"])
    return {"id": top["qid"], "key": "0i", "lined": True, "top": {**top, "parent": None, "depth": 0, "after": []},
            "rows": list(rows), "done": done, "of": len(members) + done, "status": status, "group": group, "place": place,
            "order": members, "repos": sorted({top["repo"], *(r["repo"] for r in rows)}), "passed_over": [], **kw}  # fmt: skip


def done_entry(tid: str, title: str, closed: str, pr: int, resolved: str = "", repo: str = "s") -> dict:
    return {
        "qid": f"{repo}#{tid}",
        "id": tid,
        "title": title,
        "priority": "high",
        "closed": closed,
        "pr": pr,
        "resolved": resolved,
    }


def at(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat()


def queue(repo2: bool = False) -> dict:
    """In progress: s#TD-10 held by grinder-1, with an archived row closed 2h ago. Up next: s#TD-20 and its
    build, s#TD-30 on the person's decision. Completed: a two-entry card 3h ago, one 30h ago, one 10 days ago, one
    40 days ago (outside every window). Other work: a board line grinder-2 holds."""
    g1 = {"id": "g1", "name": "grinder-1", "state": "working"}
    cards = [
        card(
            row("s", "TD-10", "recover stuck notices", state="held by grinder-1", holder=g1),
            [
                row(
                    "s",
                    "TD-9",
                    "its first step",
                    state="done #70",
                    pr=70,
                    archived=True,
                    depth=1,
                    parent="s#TD-10",
                    closed=at(2),
                    resolved="2026-10-16 (grinder-1, #70) — the first step.",
                )
            ],
            group="in_progress",
        ),
        card(
            row("s", "TD-20", "the queue's design", priority="High"),
            [row("s", "TD-21", "build the queue", state="waiting", depth=1, parent="s#TD-20", after=["s#TD-20"])],
            place=1,
        ),
        card(row("s", "TD-30", "keep this one back", state="", needs="decision"), place=2, status="needs you"),
    ]
    if repo2:
        cards.append(card(row("db", "TD-5", "a db entry"), place=3))
    return {
        "cards": cards,
        "completed": [
            {"id": "s#TD-1", "ids": ["s#TD-1", "s#TD-2"], "titles": {}, "closed": "2026-10-16", "pr": 12, "at": at(3),
             "entries": [done_entry("TD-2", "its build", at(3), 12, "built (#12)."), done_entry("TD-1", "a design", at(5), 11, "designed (#11).")]},
            {"id": "s#TD-3", "ids": ["s#TD-3"], "titles": {}, "closed": "2026-10-15", "pr": 13, "at": at(30),
             "entries": [done_entry("TD-3", "yesterday's", at(30), 13, "")]},
            {"id": "s#TD-4", "ids": ["s#TD-4"], "titles": {}, "closed": "2026-10-06", "pr": 14, "at": at(240),
             "entries": [done_entry("TD-4", "ten days ago", at(240), 14, "done.")]},
            {"id": "s#TD-6", "ids": ["s#TD-6"], "titles": {}, "closed": "2026-09-06", "pr": 15, "at": at(24 * 40),
             "entries": [done_entry("TD-6", "long ago", at(24 * 40), 15, "done.")]},
        ],
        "other_work": [{"ref": "board:keep-it", "pr": None, "holder": {"id": "g2", "name": "grinder-2", "state": "working"}}],
        "at": NOW.isoformat(),
    }  # fmt: skip


def test_the_groups_and_the_headers_counts():
    v = queue_view(queue(), NOW)
    assert [c["id"] for c in v["in_progress"]] == ["s#TD-10"]
    assert [c["id"] for c in v["up_next"]] == ["s#TD-20", "s#TD-30"] and v["upnext"] == ["s#TD-20", "s#TD-30"]
    assert v["n"] == {"cards": 3, "in_progress": 1, "waiting": 0, "up_next": 2, "needs_you": 1, "decide": 0, "do": 0}
    # one repo: the ids are written `TD-n`, and a `/queue#TD-n` finds an open row
    assert v["up_next"][0]["top"]["show"] == "TD-20" and v["up_next"][0]["rows"][0]["anchor"] == "TD-21"
    assert v["other"] == [
        {"ref": "board:keep-it", "pr": None, "holder": {"id": "g2", "name": "grinder-2", "state": "working"}}
    ]


def test_two_repos_write_the_repo_in_each_id():
    v = queue_view(queue(repo2=True), NOW)
    assert [c["top"]["show"] for c in v["up_next"]] == ["s#TD-20", "s#TD-30", "db#TD-5"]


def test_recently_completed_by_window_newest_first_with_its_counts():
    done = queue_view(queue(), NOW)["completed"]
    lines = [(ln["kind"], ln["show"], ln["wins"]) for ln in done["lines"]]
    assert lines == [
        ("row", "TD-9", ["4h", "day", "week", "month"]),  # the open card's archived row, 2h ago
        ("card", "TD-1", ["4h", "day", "week", "month"]),  # 3h ago
        ("card", "TD-3", ["week", "month"]),
        ("card", "TD-4", ["month"]),
    ]  # 40 days ago: in no window, on no list
    # a completed card counts all its entries; a row one
    assert done["counts"] == {"4h": 3, "day": 3, "week": 4, "month": 5}
    two, row_line = done["lines"][1], done["lines"][0]
    assert two["n"] == 2 and [e["resolved"] for e in two["entries"]] == ["built (#12).", "designed (#11)."]
    assert row_line["on"] == "TD-10" and row_line["entries"][0]["pr"] == 70
    # one entry with nothing more to say does not open
    assert done["lines"][2]["entries"] == []


def test_a_resolved_date_with_no_time_is_in_the_day_it_names():
    q = {"cards": [], "other_work": [], "at": NOW.isoformat(),
         "completed": [{"id": "s#TD-1", "ids": ["s#TD-1"], "closed": "2026-10-16", "at": "2026-10-16", "pr": 1,
                        "entries": [done_entry("TD-1", "today", "2026-10-16", 1, "done.")]}]}  # fmt: skip
    (ln,) = queue_view(q, NOW.replace(hour=1))["completed"]["lines"]
    assert ln["wins"] == ["day", "week", "month"]  # no time of day: never in *4 h*


def fake(q: dict | None, entries: list | None = None, repos: dict | None = None, calls: list | None = None):
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "queue":
                if q is None:
                    raise AgentError("unknown method: queue")
                return q
            if method == "inbox":
                return {"entries": [dict(e) for e in entries or ()]}
            if method == "repos" and repos is not None:
                return repos
            if method == "ledger_decide" and calls is not None:
                calls.append(kw)
                return {"decided": kw.get("words")}
            return {"list": [], "usage": {}, "host": {"name": "kmaster"}}.get(method, {})

    return Fake


def client(monkeypatch, tmp_path, Fake):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)

    class Frozen(datetime):  # the page's clock is the fixture's, so its windows hold whenever the suite runs
        @classmethod
        def now(cls, tz=None):
            return NOW if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(ui, "datetime", Frozen)
    return TestClient(ui.create_app())


def test_the_page_draws_three_groups_and_up_next_alone_moves(tmp_path, monkeypatch):
    html = client(monkeypatch, tmp_path, fake(queue())).get("/queue").text
    assert html.index('id="qcompleted"') < html.index('id="qinprogress"') < html.index('id="qupnext"')
    inprog = html[html.index('id="qinprogress"') : html.index('id="qupnext"')]
    upnext = html[html.index('id="qupnext"') :]
    assert 'data-card="s#TD-10"' in inprog and "1/2 done" in inprog and "qmove" not in inprog
    assert "other work" in inprog and "board:keep-it" in inprog and "grinder-2" in inprog
    assert re.search(r'id="qcards" data-upnext=\'\["s#TD-20", "s#TD-30"\]\'', upnext)
    assert upnext.count('data-move="top"') == 2 and '<span class="qplace">1</span>' in upnext
    assert "3 cards: 1 in progress, 2 up next." in html and "1 needs you." in html


def test_the_window_picker_carries_each_windows_count(tmp_path, monkeypatch):
    html = client(monkeypatch, tmp_path, fake(queue())).get("/queue").text
    done = html[html.index('id="qcompleted"') : html.index('id="qinprogress"')]
    assert [m for m in re.findall(r'data-win="(\w+)" aria-pressed="(\w+)">([^<]+)<', done)] == [
        ("4h", "false", "4 h (3)"), ("day", "true", "Day (3)"), ("week", "false", "Week (4)"), ("month", "false", "Month (5)")]  # fmt: skip
    assert "on TD-10's card" in done and "2 entries" in done and "built (#12)." in done
    # only the day's lines are sent at load, every window's count with them (§4.5 *Page loads*, TD-882)
    assert 'data-loaded="day"' in done and 'data-w="week month"' not in done
    assert len(re.findall(r'class="qdline', done)) == 2  # three entries: one card holds two
    # a wider window is sent on its pick, by the lists' read: its lines past the day drawn hidden until shown
    part = client(monkeypatch, tmp_path, fake(queue())).get("/queue?part=1&win=week").text
    week = part[part.index('id="qcompleted"') : part.index('id="qinprogress"')]
    assert 'data-loaded="week"' in week and re.search(r'data-w="week month" hidden', week)
    assert len(re.findall(r'class="qdline', week)) == 3 and "Month (5)" in week
    assert 'data-loaded="day"' in client(monkeypatch, tmp_path, fake(queue())).get("/queue?win=year").text


def test_the_bar_draws_three_tabs_in_their_keys_order_then_the_readings_and_the_tools(tmp_path, monkeypatch):
    """§4.5a *the bar's three groups* (TD-931, built by TD-932): Sessions, Inbox, Queue in one strip of tabs, the
    open page lit, no glyph on a tab; the readings in one strip; Settings a gear among the tools, named for a reader."""
    html = client(monkeypatch, tmp_path, fake(queue())).get("/queue").text
    tabs = html[html.index('<div class="tabs">') : html.index('<div class="grow">')]
    assert re.findall(r'<a class="tab(?: on)?" href="([^"]+)"', tabs) == ["/", "/inbox", "/queue"]
    assert '<a class="tab on" href="/queue" id="queuetab"' in tabs and "✉" not in tabs  # lit, no glyph
    assert re.search(r'id="queueneeds">\s*</span>', tabs) and 'hidden" id="queueneeds"' in tabs  # nothing at zero
    readings = html[html.index('<span class="readings"') : html.index('<span class="tools">')]
    assert all(f'id="{c}"' in readings for c in ("usagechip", "buildchip", "hostchip")) and "btn" not in readings
    tools = html[html.index('<span class="tools">') : html.index('id="newmenu"')]
    assert re.findall(r'id="(settingstab|theme|keyhelpbtn)"', tools) == ["settingstab", "theme", "keyhelpbtn"]
    gear = re.search(
        r'<a class="btn ghost light" href="/settings" id="settingstab" aria-label="Settings" title="([^"]+)"><svg',
        tools,
    )
    assert gear and gear.group(1).startswith("Settings: ")  # its word on hover and as its accessible name
    # TD-937: a toothed ring round a hub, not a sun — the sun's eight rays read as the brightness control beside it
    svg = tools[tools.index('<svg class="gear"') : tools.index("</svg>")]
    assert "<circle" in svg and svg.count("a1.65") >= 8 and "v2M" not in svg
    assert html.index('id="newmenu"') > html.index('<span class="tools">')  # + New ▾ closes the bar


def test_the_lists_alone_and_an_older_home(tmp_path, monkeypatch):
    part = client(monkeypatch, tmp_path, fake(queue())).get("/queue?part=1").text
    assert 'id="qupnext"' in part and "<html" not in part and 'id="queuetab"' not in part
    old = client(monkeypatch, tmp_path, fake(None)).get("/queue").text
    assert 'id="noqueue"' in old and "unknown method: queue" in old and 'id="qupnext"' not in old


def test_a_close_with_no_time_reads_today_or_its_days():
    q = {"cards": [], "other_work": [], "at": NOW.isoformat(),
         "completed": [{"id": f"s#TD-{n}", "ids": [f"s#TD-{n}"], "closed": d, "at": d, "pr": n,
                        "entries": [done_entry(f"TD-{n}", "x", d, n, "done.")]} for n, d in ((1, "2026-10-16"), (2, "2026-10-13"))]}  # fmt: skip
    assert [ln["age"] for ln in queue_view(q, NOW)["completed"]["lines"]] == ["today", "3d"]


def test_a_resolved_line_is_drawn_without_its_marks():
    q = queue()
    q["completed"][0]["entries"][0]["resolved"] = "2026-10-16 — **Hold** on every *held* row; `rpc_td_hold` and 2*3."
    assert queue_view(q, NOW)["completed"]["lines"][1]["entries"][0]["resolved"] == (
        "2026-10-16 — Hold on every held row; rpc_td_hold and 2*3."
    )


# -- slice 2: the mail on its card (§4.5 screen 6 *Where a row is drawn*, screen 12 *What is attached to a card*)


def mail(mid: str, text: str, kind: str = "ask", **kw) -> dict:
    return {"id": mid, "from": "g1", "to": ["person"], "kind": kind, "text": text, "at": at(1), "state": "open", **kw}


def test_an_item_is_drawn_where_its_entry_is():
    idx = card_index(queue())
    assert idx["TD-021"] == ("s#TD-20", "s#TD-21") and idx["s#TD-009"] == ("s#TD-10", "s#TD-9")
    assert item_home(mail("m1", "x", about="TD-21"), idx)["on_row"] == "s#TD-21"  # `about` first
    got = item_home(mail("m2", "TD-20: shall I split it? TD-30 waits on it"), idx)
    assert got == {"home": "queue", "on_card": "s#TD-20", "on_row": "s#TD-20", "mentions": ["s#TD-30"]}
    # an entry on a completed card, or on none, a state row and mail about nothing: the Inbox's
    for e in (mail("m3", "TD-1 is done"), mail("m4", "TD-99?"), mail("m5", "no id"), {"row": "state", "id": "x"}):
        assert item_home(e, idx)["home"] == "inbox"
    board = {"row": "board", "id": "b", "text": "**Pick** one. Context: TD-30 · the design. Due: 2026-10-17"}
    assert item_home(board, idx)["on_row"] == "s#TD-30"
    secs = inbox_sections([], now=NOW, boards=[{**board, "due": "2026-10-16"}], cards=idx)
    assert secs["needs"][0]["row"] == "board" and secs["needs"][0]["on_row"] == "s#TD-30"  # its kind kept
    red = {"row": "red_pr", "id": "red_pr:s:5", "title": "TD-10 slice 2: the thing"}
    assert item_home(red, idx)["on_row"] == "s#TD-10"
    # a bare id two repos hold resolves to neither; the repo's form still does
    two = card_index(queue(repo2=True) | {"cards": [*queue()["cards"], card(row("db", "TD-20", "same id"))]})
    assert "TD-020" not in two and two["db#TD-020"][0] == "db#TD-20"


def test_a_question_about_a_td_is_on_its_card_and_still_counted():
    entries = [
        mail("m1", "TD-21: which?"),
        mail("m2", "about nothing"),
        mail("m3", "TD-20 steer", kind="steer", bound=at(-1)),
    ]
    plain = inbox_sections(entries, now=NOW)
    secs = inbox_sections(entries, now=NOW, cards=card_index(queue()))
    assert secs["count"] == plain["count"] == 2 and secs["queue_n"] == 1 and plain["queue_n"] == 0
    assert {e["id"]: e["home"] for e in secs["needs"]} == {"m1": "queue", "m2": "inbox"}
    assert [e["home"] for e in plain["needs"]] == ["inbox", "inbox"]
    # the rail counts what the Inbox draws
    assert len([r for r in rail_rows(secs) if r["section"] == "needs"]) == 1
    got = attach(secs, lambda e, sec: f"<{e['id']}>")
    # TD-828: by card and section, not by row — TD-21 is a row of TD-20's card
    assert got["cards"]["s#TD-20"]["needs"] == [
        {"section": "needs", "id": "m1", "item": "", "html": "<m1>", "kind": "decide", "want": "decide", "red": False, "fork": False,
         "running": False, "on_row": "s#TD-21"}
    ]  # fmt: skip
    assert got["cards"]["s#TD-20"]["steering"][0]["on_row"] == "s#TD-20"
    view = queue_view(queue(), NOW, got)
    status = {c["id"]: c["status"] for c in view["up_next"]}
    assert status["s#TD-20"] == "needs you" and view["n"]["needs_you"] == 2


def test_a_steer_alone_raises_the_card_to_steer():
    secs = inbox_sections([mail("m3", "TD-20 steer", kind="steer", bound=at(-1))], now=NOW, cards=card_index(queue()))
    view = queue_view(queue(), NOW, attach(secs, lambda e, sec: ""))
    assert {c["id"]: c["status"] for c in view["up_next"]}["s#TD-20"] == "steer"


def test_the_page_draws_the_question_on_its_card_and_the_inbox_does_not(tmp_path, monkeypatch):
    entries = [mail("m1", "TD-21: which one?"), mail("m9", "TD-20 is the parent, also TD-30")]
    c = client(monkeypatch, tmp_path, fake(queue(), entries))
    html = c.get("/queue").text
    card20 = html[html.index('data-card="s#TD-20"') : html.index('data-card="s#TD-30"')]
    assert 'class="qmail inboxrows"' in card20 and "which one?" in card20  # on its row
    assert ">mentioned in 1 item<" in html[html.index('data-card="s#TD-30"') :]
    assert "Decide 2</span>" in card20 and "Decide (2)" in card20  # the pill, and the want in the header (m1, m9)
    css = c.get("/static/app.css").text
    assert ".qmail details.more:not(.qdots) { display: none; }" in css  # no Snooze on the Queue; its ⋯ drawn
    inbox = c.get("/inbox").text
    rows = inbox[inbox.index('id="rows-needs"') : inbox.index('id="sec-fyi"')]
    assert "which one?" not in rows and "TD-20 is the parent" not in rows
    # each tab its own number (§4.5a *the bar's three groups*, TD-932): the two on the cards are the Queue's, the
    # Inbox's is the rest (none here), and no number is a link of its own; no *+ n on the Queue* line in the rail
    assert 'class="badge needs" id="queueneeds">2</span>' in inbox and 'hidden" id="personneeds"></span>' in inbox
    assert "data-href" not in inbox[inbox.index('id="personinbox"') : inbox.index('id="settingstab"')]
    assert 'id="railqueue"' not in inbox
    got = c.get("/api/person/inbox?counts=1").json()
    assert got["queue_n"] == 2 and got["needs"] == 2


def test_each_request_reads_the_board_choices_once_however_many_rows(tmp_path, monkeypatch):
    """§4.5 *Page loads* (*Each fact once per request*, TD-879): the Queue's attached rows share one
    `board_choices()`, as do the Inbox page and its poll."""
    from shiftlead.ui import app as ui

    entries = [mail(f"m{i}", f"TD-{tid}: question {i}?") for i, tid in enumerate((20, 21, 30, 20, 21))]
    c = client(monkeypatch, tmp_path, fake(queue(), entries))
    calls = []
    real = ui.board_choices

    def counted(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(ui, "board_choices", counted)
    html = c.get("/queue").text
    assert all(f"question {i}?" in html for i in range(5))
    assert len(calls) == 1
    for url in ("/inbox", "/api/person/inbox"):
        calls.clear()
        assert c.get(url).status_code == 200
        assert len(calls) <= 1, url


def test_with_nothing_on_the_queue_the_inbox_tab_holds_the_number(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(queue(), [mail("m2", "about nothing")]))
    inbox = c.get("/inbox").text
    assert 'class="badge needs" id="personneeds">1</span>' in inbox and 'hidden" id="queueneeds"></span>' in inbox
    assert "about nothing" in inbox


def ledger_repos() -> dict:
    """The repo facts' *for you* entries of repo `s`: TD-21 yours to do (`Owner: paul`), TD-20 your
    decision (`decision (paul)`); TD-30 with an old clock's `held` mark, no row since TD-1297; and TD-99,
    which no card holds."""
    e = lambda i, **kw: {"id": i, "title": f"entry {i}", "priority": "medium", "for_page": "for-you", **kw}  # noqa: E731
    return {"/r/s": {"name": "s", "root": "/r/s", "ledger": {"entries": [
        e("TD-21", owner="paul"),
        e("TD-20", owner="grinder", blocked_by=["decision (paul)"]),
        e("TD-30", owner="grinder", for_page="pickable", held={"at": at(2)}),
        e("TD-99", owner="paul"),
    ]}}}  # fmt: skip


def test_the_ledger_rows_leave_later_for_their_cards(tmp_path, monkeypatch):
    """§4.5 screen 6 *Where a row is drawn*, screen 12 *What needs the person* (TD-771 slice 3): a ledger row
    whose entry a card holds is drawn on that row — *yours to do* with Done, a decision with Lift the hold (Start
    session is the card header's alone) — and leaves the Inbox's *Later*; one no card holds stays there. An old
    clock's `held` mark draws nothing (TD-1297)."""
    c = client(monkeypatch, tmp_path, fake(queue(), [], ledger_repos()))
    html = c.get("/queue").text
    card20 = html[html.index('data-card="s#TD-20"') : html.index('data-card="s#TD-30"')]
    card30 = html[html.index('data-card="s#TD-30"') :]
    assert "held until your decision" in card20 and ">Lift the hold</button>" in card20
    assert 'data-words="go ahead"' in card20
    assert "yours to do" in card20 and 'data-words="done"' in card20 and ">Done</button>" in card20
    # no row draws Start session: it is the card's, once, in its header (TD-912, TD-914)
    assert card20.count('data-act="ledger_start"') == card20.count("qstart")
    assert "held (person)" not in card30 and "ledger_release" not in card30 and "Release" not in card30
    assert "entry TD-99" not in html
    inbox = c.get("/inbox").text
    later = inbox[inbox.index('id="ledgerforyou"') :]
    assert "entry TD-99" in later and "entry TD-21" not in later and "entry TD-20" not in later
    rail = inbox[inbox.index('id="railh-kind"') :]
    assert 'data-value="ledger"' in rail  # TD-99 is still the Inbox's
    poll = c.get("/api/person/inbox").json()["html"]["ledger"]
    assert "entry TD-99" in poll and "entry TD-21" not in poll


def test_a_hold_reads_the_words_after_its_dash(tmp_path, monkeypatch):
    """§4.5a *Queue card: what needs the person* (TD-795): *held until <the words after the dash>*."""
    repos = ledger_repos()
    repos["/r/s"]["ledger"]["entries"][1]["until"] = "after the trial"
    html = client(monkeypatch, tmp_path, fake(queue(), [], repos)).get("/queue").text
    card20 = html[html.index('data-card="s#TD-20"') : html.index('data-card="s#TD-30"')]
    assert "held until after the trial" in card20 and "held until your decision" not in card20


def test_the_ledger_kind_leaves_the_rail_once_every_row_is_on_a_card(tmp_path, monkeypatch):
    repos = ledger_repos()
    repos["/r/s"]["ledger"]["entries"].pop()  # TD-99: every row is now on a card
    inbox = client(monkeypatch, tmp_path, fake(queue(), [], repos)).get("/inbox").text
    assert 'data-value="ledger"' not in inbox[inbox.index('id="railh-kind"') :]


def test_lift_the_hold_and_done_send_the_ledger_rows_reply_road(tmp_path, monkeypatch):
    """§4.5a *Queue card: what needs the person*: each press is the ledger row's Reply with its fixed words —
    one `ledger_decide`, one decided board line."""
    calls: list = []
    c = client(monkeypatch, tmp_path, fake(queue(), [], ledger_repos(), calls))
    for words in ("go ahead", "done"):
        got = c.post("/api/person/ledger", json={"repo": "/r/s", "id": "TD-20", "words": words})
        assert got.status_code == 200 and got.json()["decided"] == words
    assert calls == [
        {"repo": "/r/s", "id": "TD-20", "words": "go ahead"},
        {"repo": "/r/s", "id": "TD-20", "words": "done"},
    ]


def test_a_card_on_the_persons_decision_reads_needs_you():
    v = queue_view(queue(), NOW)
    (c30,) = [c for c in v["up_next"] if c["id"] == "s#TD-30"]
    assert c30["status"] == "needs you" and v["n"]["needs_you"] == 1


def test_a_board_line_not_yet_due_is_under_its_cards_needs_you_and_leaves_later():
    """§4.5 screen 12 *What is attached to a card* (TD-828): a board line about the card's entries is under its
    *Needs you* whether or not it is due, and whether or not the Inbox's mode folds it — it leaves *Not due
    yet* and the *not shown* fold for it — drawn with its due date; the card's status is *needs you*."""
    ahead = [
        {"row": "board", "id": "b1", "text": "decide the layout. Context: TD-21. Due: 2026-10-30."},
        {"row": "board", "id": "b2", "text": "something else. Due: 2026-10-30."},
    ]
    hidden = [
        {"row": "board", "id": "b3", "text": "far off. Context: TD-30. Due: 2026-12-30."},
        {"row": "board", "id": "b4", "text": "far off too. Due: 2026-12-30."},
    ]
    lf, rest, moved, unshown = split_later({"n": 0, "groups": []}, ahead, card_index(queue()), hidden)
    assert [e["id"] for e in rest] == ["b2"] and [e["id"] for e in unshown] == ["b4"] and lf["n"] == 0
    assert [(e["id"], e["on_row"], e["later_section"]) for e in moved] == [
        ("b1", "s#TD-21", "coming"),
        ("b3", "s#TD-30", "coming"),
    ]
    got = attach({}, lambda e, sec: f"<{e['id']}:{sec}>", moved)
    assert got["cards"]["s#TD-20"] == {
        "needs": [{"section": "needs", "id": "b1", "item": "", "html": "<b1:coming>", "kind": "decide", "want": "decide",
                   "red": False, "fork": False, "running": False, "on_row": "s#TD-21"}]
    }  # fmt: skip
    v = queue_view(queue(), NOW, got)
    c20 = next(c for c in v["up_next"] if c["id"] == "s#TD-20")
    assert c20["status"] == "needs you" and v["n"]["needs_you"] == 2
    assert c20["wants"]["decide"][0]["on"] == "TD-21"  # about a lower row: *on TD-21*


def test_the_inbox_fold_loses_a_line_a_card_draws():
    """§4.5 screen 6 *The board's horizon*, TD-828: a line the Inbox's mode folds that a card draws leaves the
    *not shown* fold and its count, and the line's next date is read from what is left."""
    hz = {"mode": "next:1", "ahead": [], "today": "2026-10-16", "line": {"n": 2},
          "hidden": [{"id": "b3", "due": "2026-10-20"}, {"id": "b4", "due": "2026-12-30"}]}  # fmt: skip
    got = horizon_left(hz, [], [hz["hidden"][1]])
    assert [r["id"] for r in got["hidden"]] == ["b4"] and got["next_due"] == "2026-12-30"
    assert got["line"]["n"] == 1 and got["line"]["rest"].startswith("1 not shown")


def sections_of(*items: tuple[str, str, str]) -> dict:
    """A card's attached items as `attach` answers them: (section, id, the row it is about)."""
    got: dict = {}
    for sec, mid, on_row in items:
        got.setdefault("needs" if sec == "do" else sec, []).append(
            {
                "section": sec,
                "id": mid,
                "html": f'<div class="mailrow" data-msg="{mid}">{mid}</div>',
                "kind": "",
                "want": {"needs": "decide", "do": "do"}.get(sec, "read"),
                "on_row": on_row,
            }
        )
    return {"cards": {"s#TD-20": got}, "mentioned": {}}


def test_a_cards_wants_draw_their_counts_and_none_at_zero(tmp_path, monkeypatch):
    """§4.5 screen 12 *Three wants*, §4.5a *Queue page: card*, *Queue card: Read n* (TD-911): Decide and Do in
    the header, open, counted on the pill; Read under the rows, folded with its count, its lines each with its
    count and not drawn at 0; *Read n* on the header for a folded card; an item about a lower row says *on
    TD-n*; Dismiss all on answered for you and fyi alone."""
    from markupsafe import Markup

    from shiftlead.ui.app import templates

    mail = sections_of(("needs", "m1", "s#TD-20"), ("do", "d1", "s#TD-20"), ("answered", "a1", "s#TD-21"),
                       ("answered", "a2", "s#TD-20"), ("fyi", "f1", "s#TD-20"))  # fmt: skip
    for items in mail["cards"]["s#TD-20"].values():
        for m in items:
            m["html"] = Markup(m["html"])
    view = queue_view(queue(), NOW, mail)
    c20 = next(c for c in view["up_next"] if c["id"] == "s#TD-20")
    html = templates.env.get_template("queue_card.html").module.card(c20)
    head, body = html.split('<div class="qrows">')
    assert "Decide (1)" in head and "Do (1)" in head and "answered for you" not in head
    assert ">Decide 1 · Do 1</span>" in head and ">Read 3</span>" in head  # the pill; Read n, drawn when folded
    assert head.index(">Read 3</span>") < head.index(">Decide 1 · Do 1</span>")  # the status ends the line
    assert (
        '<details class="qread"><summary class="qsech">Read (3)</summary>' in body
        and "answered for you (2)" in body
        and "fyi (1)" in body
        and "waiting on them" not in body
    )
    assert body.index("fyi (1)") > body.index('data-qid="s#TD-21"')  # under the rows
    assert body.count(">Dismiss all</button>") == 2 and "Dismiss all" not in head
    assert 'class="qcard edge-needs g-up_next st-needs-you wants hasrows"' in html  # amber
    assert body.count('class="qon qsub" href="#TD-21"') == 1  # a1 is about TD-21; a2 is the top entry's
    assert c20["status"] == "needs you"


def test_a_group_heading_carries_its_count_and_its_share_under_a_pick(tmp_path, monkeypatch):
    """§4.5a *Queue page: group heading* (TD-828): *Recently completed (n)* the window's count, *In progress
    (n)*, *Up next (n)*, *(n of m)* while a pick or a find is on; the bare number beside it is gone; a press on
    the heading folds the group, which the browser remembers (`qgfold`)."""
    c = client(monkeypatch, tmp_path, fake(queue(), []))
    html = c.get("/queue").text
    assert 'Up next <span class="qshare" data-of="2">(2)</span>' in html
    assert 'In progress <span class="qshare" data-of="1">(1)</span>' in html
    head = html[html.index('id="qcompleted"') : html.index('class="qsub qgfoldword"')]
    assert (
        'Recently completed<span class="qwinword"' in head
        and '<span class="qwinword" data-wv="day"> <span class="qshare" data-of="3">(3)</span></span>' in head
    )
    assert 'Waiting <span class="qshare" data-of="0">(0)</span>' in html  # TD-918: between, even empty
    assert html.count('class="h2 qghead" role="button"') == 4 and 'data-group="up_next"' in html
    html = c.get("/queue?find=queue").text
    assert 'data-of="2">(1 of 2)</span>' in html and 'data-of="1">(0 of 1)</span>' in html
    js = c.get("/static/app.js").text
    assert 'const groupKey = "qgfold"' in js and "toggleGroup(g, true)" in js


def test_dismiss_all_is_the_inboxs_hoisted_press():
    """§4.5 screen 12 (TD-828): the Inbox's Dismiss all is one function, `AO.dismissOnScreen`, which the Inbox
    and the Queue's card sections both call with their own re-read."""
    from pathlib import Path

    js = (Path(__file__).parents[1] / "src/shiftlead/ui/static/app.js").read_text()
    assert "AO.dismissOnScreen = (btn, rows, empty, ask, refresh)" in js
    assert 'AO.dismissOnScreen($("#dismissall"), "#rows-fyi .mailrow"' in js and "refreshInbox);" in js
    assert 'AO.dismissOnScreen(b, () => $$(".mailrow", sec)' in js
    assert "const dismissOnScreen" not in js


# -- slice 4: the filter row, find, the addresses (§4.5 screen 12 *Filters*, *Addresses*; §4.5a *Queue page: filters, find*)


def shown(v: dict) -> list[str]:
    return [c["id"] for c in [*v["in_progress"], *v["up_next"]] if not c["off"]]


def test_the_picks_read_from_the_url_and_toggle_back():
    p = queue_picks({"filter": "needs-you", "team": "a,b", "kind": "do,yours", "repo": "s", "find": "  the   queue "})
    assert p == {"filter": "needs-you", "team": ["a", "b"], "find": "the queue"}  # no repo or kind pick (TD-1287)
    assert queue_picks({"filter": "bogus"})["filter"] == ""  # a stale link reads as not picked
    assert queue_picks({"filter": "steering"})["filter"] == ""  # the Steering pick is gone: not picked, no error
    assert picks_query(p, filter="needs-you") == "/queue?team=a%2Cb&find=the%20queue"  # pressed again: off
    assert picks_query(p, team="a") == "/queue?filter=needs-you&team=b&find=the%20queue"
    # a list replaces the chips: `team=[]` is **All**, which keeps the switch and the find
    assert picks_query(p, team=[]) == "/queue?filter=needs-you&find=the%20queue"
    assert picks_query(p, team=["c"]) == "/queue?filter=needs-you&team=c&find=the%20queue"


def test_the_needs_you_switch_filters_the_cards_and_hides_the_completed():
    v = apply_picks(queue_view(queue(), NOW), queue_picks({"filter": "needs-you"}), {})
    assert shown(v) == ["s#TD-30"] and v["shown"] == 1 and v["filtered"]
    assert all(ln["off"] for ln in v["completed"]["lines"]) and all(o["off"] for o in v["other"])
    # a running steer about TD-21 makes its card *steer*, outside the switch; `filter=steering` picks nothing
    secs = inbox_sections([mail("m3", "TD-21 steer", kind="steer", bound=at(-1))], now=NOW, cards=card_index(queue()))
    v = apply_picks(queue_view(queue(), NOW, attach(secs, lambda e, sec: "")), queue_picks({"filter": "steering"}), {})
    assert len(shown(v)) == 3 and not v["filtered"]
    # a running steer is Decide, on the pill, and leaves the status *steer* (§4.5 screen 12 *Three wants*)
    c20 = queue_view(queue(), NOW, attach(secs, lambda e, sec: ""))["up_next"][0]
    assert c20["status"] == "steer" and c20["wants"]["n"]["decide"] == 1 and "kinds" not in c20
    v = apply_picks(queue_view(queue(), NOW, attach(secs, lambda e, sec: "")), queue_picks({"filter": "needs-you"}), {})
    assert "s#TD-20" not in shown(v)


def test_an_old_repo_or_kind_pick_draws_the_page_unpicked():
    for old in ({"kind": "held-person"}, {"kind": "decide"}, {"repo": "s"}, {"repo": "nowhere"}):
        v = apply_picks(queue_view(queue(repo2=True), NOW), queue_picks(old), {})
        assert len(shown(v)) == 4 and not v["filtered"], old


def test_a_team_chip_and_a_repo_chip_read_the_cards_repos():
    v = apply_picks(queue_view(queue(repo2=True), NOW), queue_picks({"team": "dbteam"}), {"dbteam": "db"})
    assert shown(v) == ["db#TD-5"]
    assert [ln["off"] for ln in v["completed"]["lines"]] == [True] * len(v["completed"]["lines"])  # all repo s
    # a repo chip is a `team` pick naming no team: it narrows to that repo
    v = apply_picks(queue_view(queue(repo2=True), NOW), queue_picks({"team": "s"}), {"dbteam": "db"})
    assert "db#TD-5" not in shown(v) and len(shown(v)) == 3
    assert not any(ln["off"] for ln in v["completed"]["lines"])  # a completed line answers the chips
    assert all(o["off"] for o in v["other"])  # an *other work* line is hidden while a chip is picked
    # a picked name no team holds and no repo the home reads names holds no card
    assert apply_picks(queue_view(queue(), NOW), queue_picks({"team": "ghost"}), {})["shown"] == 0


def test_find_matches_an_id_or_a_title_and_falls_through_to_the_archive():
    find = lambda f: apply_picks(queue_view(queue(), NOW), queue_picks({"find": f}), {})  # noqa: E731
    assert shown(find("td-21")) == ["s#TD-20"] and shown(find("TD-021")) == ["s#TD-20"]  # a row's id finds its card
    assert shown(find("keep back")) == ["s#TD-30"] and find("keep back")["find_miss"] is None
    # an id no open card holds: the completed line that has it, and the Repo page in the archive
    v = find("TD-3")
    assert v["shown"] == 0 and [ln["show"] for ln in v["completed"]["lines"] if not ln["off"]] == ["TD-3"]
    assert v["find_miss"] == {"id": "TD-003", "repos": [{"name": "s", "url": "/repo/s#TD-003"}]}
    # an archived row of an open card is on no open card either, but its card is found by it
    assert find("TD-9")["find_miss"]["id"] == "TD-009" and shown(find("TD-9")) == ["s#TD-10"]


def test_the_chips_add_up_and_the_switch_and_find_narrow_them():
    teams = {"dbteam": "db"}
    v = apply_picks(queue_view(queue(repo2=True), NOW), queue_picks({"team": "dbteam,s"}), teams)
    assert len(shown(v)) == 4  # a team chip and a repo chip OR'd
    v = apply_picks(queue_view(queue(repo2=True), NOW), queue_picks({"team": "dbteam,s", "filter": "needs-you"}), teams)
    assert shown(v) == ["s#TD-30"]  # ANDed with the switch
    v = apply_picks(queue_view(queue(repo2=True), NOW), queue_picks({"team": "dbteam,s", "find": "TD-21"}), teams)
    assert shown(v) == ["s#TD-20"]  # and with the find
    # a team named like a repo is the team: its chip narrows to the team's repo, not the repo of its name
    v = apply_picks(queue_view(queue(repo2=True), NOW), queue_picks({"team": "s"}), {"s": "db"})
    assert shown(v) == ["db#TD-5"]


def test_the_chips_are_a_team_each_then_a_repo_no_team_names():
    assert filter_chips({"dbteam": "db"}, ["db", "s"], []) == {"team": ["dbteam"], "repo": ["s"]}
    assert filter_chips({}, ["s"], []) == {"team": [], "repo": ["s"]}  # a one-repo home with no team draws it too
    # a repo named like a team with a repo draws no chip, whatever repo that team services
    assert filter_chips({"s": "db"}, ["db", "s"], []) == {"team": ["s"], "repo": []}
    # a team whose repo the Queue does not read is drawn only while picked; a picked unknown name, as a repo chip
    assert filter_chips({"dbteam": "db", "far": "x"}, ["db", "s"], ["far", "gone"]) == {
        "team": ["dbteam", "far"],
        "repo": ["gone", "s"],
    }


def test_a_find_naming_an_id_an_open_card_holds_offers_no_archive():
    v = apply_picks(queue_view(queue(), NOW), queue_picks({"find": "TD-21"}), {})
    assert shown(v) == ["s#TD-20"] and v["find_miss"] is None


def test_a_card_with_a_steering_item_keeps_its_status_and_is_under_the_switch():
    # a running steer about TD-30: its card stays *needs you* (held by the person), so the switch keeps it
    secs = inbox_sections([mail("m3", "TD-30 steer", kind="steer", bound=at(-1))], now=NOW, cards=card_index(queue()))
    v = queue_view(queue(), NOW, attach(secs, lambda e, sec: ""))
    assert [c["status"] for c in v["up_next"] if c["id"] == "s#TD-30"] == ["needs you"]
    assert shown(apply_picks(v, queue_picks({"filter": "needs-you"}), {})) == ["s#TD-30"]


def test_an_archived_rows_need_is_no_need_of_its_card():
    q = queue()
    q["cards"][0]["rows"][0]["needs"] = "owner"  # TD-10's archived TD-9: its owner need was met when it closed
    v = queue_view(q, NOW)
    assert v["in_progress"][0]["status"] == "ready"
    assert "s#TD-10" not in shown(apply_picks(v, queue_picks({"filter": "needs-you"}), {}))


def test_the_page_draws_the_filter_row_and_hides_what_a_pick_hides(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(queue(), [mail("m2", "about nothing")]))
    html = c.get("/queue").text
    row = html[html.index('id="qfilters"') : html.index('id="qcompleted"')]
    assert 'aria-pressed="true">All</a>' in row and 'Needs you (<span id="qfneedsn">1</span>)' in row
    assert "qininbox" not in row  # the question about nothing is the Inbox tab's number (TD-932)
    # the teams, the switch and the find, and nothing else (TD-1287): no Steering, no repo or kind pick
    assert 'name="find"' in row and "Steering" not in row and "held (person)</a>" not in row
    assert 'data-k="repo"' not in row and 'data-k="kind"' not in row and "qkinds" not in row
    assert '<span class="qsub">teams</span>' in row and row.index("qsub") < row.index(">All</a>") < row.index("qswitch")
    assert re.search(
        r'id="qfneeds" role="switch" data-k="filter" data-v="needs-you" href="[^"]*" aria-checked="false"', row
    )
    # one repo the home reads and no team on it: its chip is drawn, muted, on a one-repo home too
    assert re.search(
        r'class="qf qfrepo" data-k="team" data-v="s" href="/queue\?team=s" aria-pressed="false" title="no team services this repo"',
        row,
    )
    html = c.get("/queue?filter=needs-you").text
    assert re.search(
        r'id="qfneeds" role="switch" data-k="filter" data-v="needs-you" href="/queue" aria-checked="true"', html
    )  # again: off
    # **All** is pressed with the switch on and no chip, and its link keeps the switch
    assert 'data-k="all" href="/queue?filter=needs-you" aria-pressed="true">All</a>' in html
    for old in ("filter=steering", "repo=x", "kind=do"):
        got = c.get(f"/queue?{old}")
        assert got.status_code == 200 and 'data-k="all" href="/queue" aria-pressed="true">All</a>' in got.text, old
        assert 'aria-checked="false"' in got.text and " qoff" not in got.text[got.text.index('id="queuelists"') :], old
    upnext = html[html.index('id="qupnext"') :]
    # what a pick hides is hidden, never dropped: the whole Up next order is still on the page
    assert re.search(r'class="qcard edge-ended g-up_next st-ready hasrows qoff" data-card="s#TD-20"', upnext)
    assert 'data-card="s#TD-30"' in upnext and "s#TD-20" in upnext[upnext.index("data-upnext") :]
    part = c.get("/queue?part=1&find=TD-3").text
    assert 'id="qfindmiss" data-for="TD-3"' in part and 'href="/repo/s#TD-003"' in part
    assert '<div class="qnote" id="qnone">' in part  # drawn hidden otherwise, for the browser's apply (TD-829)
    assert '<div class="qnote" id="qnone" hidden>' in c.get("/queue?part=1").text
    # the row stands outside the lists the page re-reads (typed find words survive); the lists carry its numbers
    html = c.get("/queue").text
    assert html.index('id="qfilters"') < html.index('id="queuelists"')
    part = c.get("/queue?part=1").text
    assert 'id="qfilters"' not in part and 'id="qcounts" hidden data-needs="1">' in part


def test_a_passed_over_flag_is_drawn_on_its_card(tmp_path, monkeypatch):
    q = queue()
    q["cards"][1]["passed_over"] = [
        {"by": "g1", "name": "grinder-1", "holding": "s#TD-10", "ids": ["s#TD-20"], "why": "TD-10 first"}
    ]
    html = client(monkeypatch, tmp_path, fake(q)).get("/queue").text
    card20 = html[html.index('data-card="s#TD-20"') : html.index('data-card="s#TD-30"')]
    assert "passed over by grinder-1: TD-10 first" in card20
    # the reading flags no card for a waiting row (`sessionorc.queue._passed_over`): none is drawn without one
    assert "passed over" not in html[html.index('data-card="s#TD-30"') :]


def test_the_message_page_returns_to_the_queue_for_an_item_drawn_there(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(queue(), [mail("m1", "TD-21: which one?")]))
    page = c.get("/inbox/m1?back=" + quote("/queue?filter=needs-you")).text
    assert 'id="msgback" href="/queue?filter=needs-you#m1"' in page
    assert 'id="msgback" href="/inbox#m1"' in c.get("/inbox/m1?back=//evil.example").text  # nothing else is a list
    assert 'id="msgback" href="/inbox?sec=needs#m1"' in c.get("/inbox/m1?back=" + quote("?sec=needs")).text


def test_an_id_in_find_matches_that_id_whole():
    q = queue()
    q["cards"].append(card(row("s", "TD-200", "a later one"), place=3))
    q["cards"].append(card(row("s", "TD-2000", "much later, after TD-20"), place=4))
    assert shown(apply_picks(queue_view(q, NOW), queue_picks({"find": "TD-20"}), {})) == ["s#TD-20"]  # not TD-200
    assert shown(apply_picks(queue_view(q, NOW), queue_picks({"find": "s#TD-200"}), {})) == ["s#TD-200"]
    assert shown(apply_picks(queue_view(q, NOW), queue_picks({"find": "later"}), {})) == ["s#TD-200", "s#TD-2000"]


def test_the_rows_on_cards_and_in_the_inbox_add_up_to_the_top_bars_number(tmp_path, monkeypatch):
    """The top bar counts both homes (§4.5 screen 6 *Where a row is drawn*, §4.5a *the bar's three groups*,
    TD-932): the Queue tab's number is the counted rows drawn on cards, the Inbox tab's the rest, and the two make
    `needs`. *Needs you (n)* counts cards whose status is *needs you* (the held TD-30 among them, which no number
    counts), so it is the cards, not a part of this sum."""
    entries = [mail("m1", "TD-21: which one?"), mail("m2", "TD-20: and this?"), mail("m3", "about nothing"),
               mail("m4", "nor this")]  # fmt: skip
    c = client(monkeypatch, tmp_path, fake(queue(), entries))
    top = c.get("/api/person/inbox?counts=1").json()
    html = c.get("/queue").text
    m = int(re.search(r'id="personneeds">(\d+)<', html)[1])
    q = int(re.search(r'id="queueneeds">(\d+)<', html)[1])
    assert top["needs"] == 4 and top["queue_n"] == q == 2 and m == 2 and q + m == top["needs"]
    assert 'Needs you (<span id="qfneedsn">2</span>)' in html  # TD-20's card and the held TD-30's


DISMISS_PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
const sent = [], asked = [];
global.fetch = (url, opts) => { sent.push({ url, body: JSON.parse(opts.body) }); return Promise.resolve({ ok: true, json: () => ({}) }); };
global.confirm = (t) => { asked.push(t); return true; };
eval(fs.readFileSync(process.argv[2], "utf8"));
window.AO.toast = noop;
let click = null, refreshed = 0;
const btn = { addEventListener: (k, f) => { click = f; } };
// a card's FYI section: two rows on screen and one a pick hides; the card beside it is not read
const rows = [{ dataset: { msg: "f1" } }, { dataset: { msg: "f2" } }, { hidden: true, dataset: { msg: "f3" } }];
window.AO.dismissOnScreen(btn, () => rows, "nothing", window.AO.DISMISS_ASK.fyi, () => refreshed++);
click({ preventDefault: noop, stopPropagation: noop }).then(() => console.log(JSON.stringify({ sent, asked, refreshed })));
"""


def test_dismiss_all_on_a_card_dismisses_that_sections_rows_on_screen(tmp_path):
    """§4.5 screen 12 *What is attached to a card* (TD-828): Dismiss all confirms once with the number and
    dismisses the ids on screen in that section of that card, then re-reads the page it is on."""
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = tmp_path / "dismiss_probe.js"
    probe.write_text(DISMISS_PROBE)
    js = Path(__file__).resolve().parents[1] / "src/shiftlead/ui/static/app.js"
    out = subprocess.run([node, str(probe), str(js)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["sent"] == [{"url": "/api/person/dismiss", "body": {"msg": ["f1", "f2"]}}]
    assert got["asked"] == [
        "Dismiss 2 FYI entries? Only the ones on screen now — anything that arrives after this is untouched."
    ]
    assert got["refreshed"] == 1


def test_the_completed_share_counts_only_the_lines_a_pick_leaves_on():
    """TD-860: `shown_in["completed"]` is what *Completed (n of m)* draws (`queue_part.html`), per window."""
    v = apply_picks(queue_view(queue(), NOW), queue_picks({}), {})
    assert v["shown_in"]["completed"] == v["completed"]["counts"] == {"4h": 3, "day": 3, "week": 4, "month": 5}
    v = apply_picks(queue_view(queue(), NOW), queue_picks({"find": "TD-3"}), {})
    assert v["shown_in"]["completed"] == {"4h": 0, "day": 0, "week": 1, "month": 1}
    v = apply_picks(queue_view(queue(), NOW), queue_picks({"filter": "needs-you"}), {})
    assert v["shown_in"]["completed"] == {"4h": 0, "day": 0, "week": 0, "month": 0}


def test_two_repos_number_each_card_per_repo_with_its_chip(tmp_path, monkeypatch):
    """§4.5 screen 12 *Up next*, §4.5a *Queue page, Up next: the number* (TD-901): where the home reads more
    than one repo, each card's number is its place in its repo, drawn with the repo's chip — two repos'
    leaders both read 1 — and one repo's Queue draws the plain number."""
    q = queue(repo2=True)
    for c in q["cards"]:
        c["places"] = {"s#TD-20": [{"repo": "s", "n": 1}], "s#TD-30": [{"repo": "s", "n": 2}],
                       "db#TD-5": [{"repo": "db", "n": 1}]}.get(c["id"], [])  # fmt: skip
    html = client(monkeypatch, tmp_path, fake(q)).get("/queue").text
    upnext = html[html.index('id="qupnext"') :]
    assert 'class="qcards multi" id="qcards"' in upnext
    assert '<span class="qpn"><span class="qn">1</span><span class="qprepo"' in upnext
    assert upnext.count('<span class="qn">1</span>') == 2 and ">db</span>" in upnext and ">s</span>" in upnext
    one = client(monkeypatch, tmp_path, fake(queue())).get("/queue").text
    assert 'class="qcards" id="qcards"' in one and "qprepo" not in one


def test_each_tab_has_its_number_and_the_rollup_reads_the_inboxs_beside_an_overdue_count_over_both():
    """§4.5a *the bar's three groups* and §4.5 screen 1 (TD-931, built by TD-932): a question about an open card
    and a board line past its date about another are the Queue tab's, a state row the Inbox tab's; the two make
    `count`. The rollup's *in the Inbox* is the Inbox tab's number, while *m overdue* counts both homes, so it
    can exceed it."""
    from shiftlead.ui import app as ui

    board = {"row": "board", "id": "b", "text": "**Pick** one. Context: TD-30. Due: 2026-10-10", "due": "2026-10-10"}
    secs = inbox_sections(
        [mail("m1", "TD-21: which one?")], states=[{"row": "state", "id": "s1", "state": "needs-you"}],
        boards=[board], now=NOW, cards=card_index(queue()),
    )  # fmt: skip
    tabs = ui.tab_counts(secs)
    assert tabs["person_queue_n"] == 2 and tabs["person_needs"] == 1 and secs["count"] == 3
    assert secs["overdue_n"] == 1
    ro = {"agents": [], "n_agents": 0, "phases": [], "motion": 0, "prs_open": 0, "has_repo": False,
          "answer_needed": 0, "answer_team": ""}  # fmt: skip
    html = ui.templates.get_template("rollup.html").render(ro=ro, person_needs=0, person_overdue=1)
    assert "data-inbox-needs>0<" in html and "data-inbox-overdue>1</span> overdue" in html  # 1 overdue over 0


def test_a_cards_items_fit_a_phone_width():
    """TD-985 (design §4.5 screen 12 *Narrow (below 720 px)*): a card's items never widen it past the screen.
    The header's last column is `minmax(0, 1fr)` (a bare `1fr`'s least width is its content's, so a long
    word in a Decide item widened it under the card's `overflow: hidden`), a section may shrink, an item's
    words break, and below 720 px the items drop the desktop indent under the number, as the notes do.
    Read at 390 px on a scratch home: the page's scrollWidth was its innerWidth and no item passed its card."""
    from pathlib import Path

    css = (Path(__file__).parent.parent / "src" / "shiftlead" / "ui" / "static" / "app.css").read_text()
    narrow = css[css.index("  .qhead { grid-template-columns: 1em") :]
    narrow = narrow[: narrow.index("\n}\n")]
    for rule in (
        ".qhead { display: grid; grid-template-columns: 1.4em 2.6em minmax(0, 1fr);",
        ".qcards.multi .qhead { grid-template-columns: 1.4em 5.5em minmax(0, 1fr); }",
        ".qwaits .qhead, .qwaits.multi .qhead { grid-template-columns: 1.4em 8.5em minmax(0, 1fr); }",
        ".qsec { flex: 1 0 100%; min-width: 0; }",
        ".qmail .mailrow { min-width: 0; } .qmail .body { overflow-wrap: anywhere; }",
    ):
        assert rule in css, rule
    assert not re.search(r"\.qhead \{[^}]*grid-template-columns:[^;}]*[^,] 1fr", css)  # every one, wide and narrow
    assert ".qcards.multi .qhead { grid-template-columns: 1em 4.5em minmax(0, 1fr); }" in narrow
    assert (
        ".qsech, .qmail, .qrows > .qsec .qsech, .qrows > .qsec .qmail, .qread > summary.qsech,\n"
        "  .qread .qsec .qsech, .qread .qsec .qmail { padding-left: 0; }"
    ) in narrow


def test_a_waiting_row_is_teal_in_the_tree():
    """TD-1130: the reading's *waiting* word (an open blocker or an open part) colours the rail teal."""
    from shiftlead.ui.queue import branch

    assert branch({"state": "waiting"}) == "waiting" and branch({"state": "waits until 2026-10-30"}) == "waiting"
    assert branch({"state": "ready"}) == "open"
