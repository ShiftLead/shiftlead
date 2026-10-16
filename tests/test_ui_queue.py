# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-771 slice 1, design §4.5 screen 12 *Queue* and §4.5a *Queue page*, *Org top bar: Queue tab*: the
page draws the home's `queue` reading in three groups — Recently completed with its window picker and
its counts, In progress with the other work, Up next numbered with the grip and ⤒ ↑ ↓ — by the partials
the Repo page shares; the top bar carries a Queue tab after Inbox, with no number of its own."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sessionorc.client import AgentError
from shiftlead.ui.inbox import inbox_sections, rail_rows
from shiftlead.ui.queue import attach, card_index, item_home, queue_view

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 16, 20, 0, tzinfo=UTC)


def row(repo: str, tid: str, title: str, **kw) -> dict:
    return {"qid": f"{repo}#{tid}", "repo": repo, "id": tid, "title": title, "priority": "Medium", "state": "ready",
            "needs": None, "pr": None, "holder": None, "key": "", "lined": False, "archived": False, **kw}  # fmt: skip


def card(top: dict, rows=(), group="up_next", place=None, status="ready", **kw) -> dict:
    members = [top["qid"], *(r["qid"] for r in rows if not r["archived"])]
    done = sum(1 for r in rows if r["archived"])
    return {"id": top["qid"], "key": "0i", "lined": True, "top": {**top, "parent": None, "depth": 0, "also_after": []},
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
    build, s#TD-30 the person holds. Completed: a two-entry card 3h ago, one 30h ago, one 10 days ago, one
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
            [row("s", "TD-21", "build the queue", state="after TD-20", depth=1, parent="s#TD-20")],
            place=1,
        ),
        card(row("s", "TD-30", "keep this one back", state="held (person)"), place=2, status="needs you"),
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
    assert v["n"] == {"cards": 3, "in_progress": 1, "up_next": 2, "needs_you": 1}
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


def fake(q: dict | None, entries: list | None = None):
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
    # a line outside *day* is drawn hidden until its window is picked
    assert re.search(r'data-w="week month" hidden', done)


def test_the_queue_tab_follows_inbox_with_no_number(tmp_path, monkeypatch):
    html = client(monkeypatch, tmp_path, fake(queue())).get("/queue").text
    nav = html[html.index('id="personinbox"') : html.index('id="settingstab"')]
    tab = re.search(r'<a class="btn light on" href="/queue" id="queuetab"[^>]*>([^<]*)</a>', nav)
    assert tab and tab.group(1) == "Queue"  # the active tab, its word alone


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


# -- slice 2: the mail on its card (§4.5 screen 6 *Where a row is drawn*, screen 12 *What is attached to a row*)


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
    assert got["s#TD-21"]["items"] == [{"section": "needs", "id": "m1", "html": "<m1>"}]
    assert got["s#TD-20"]["items"][0]["section"] == "steering"
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
    assert "also mentioned in TD-20 is the parent" in html[html.index('data-card="s#TD-30"') :]
    assert "Needs you</span>" in card20
    css = c.get("/static/app.css").text
    assert ".qmail details.more { display: none; }" in css  # no Snooze on the Queue
    inbox = c.get("/inbox").text
    rows = inbox[inbox.index('id="rows-needs"') : inbox.index('id="sec-fyi"')]
    assert "which one?" not in rows and "TD-20 is the parent" not in rows
    assert 'id="railqueue"' in inbox and '<span id="railqueuen">2</span> on the Queue' in inbox
    # the number is unchanged and links to the Queue's needs-you filter
    assert 'data-href="/queue?filter=needs-you"' in inbox and 'class="badge needs" id="personneeds">2</span>' in inbox
    assert c.get("/api/person/inbox?counts=1").json()["queue_n"] == 2


def test_with_nothing_on_the_queue_the_number_links_to_the_inbox(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(queue(), [mail("m2", "about nothing")]))
    inbox = c.get("/inbox").text
    assert "data-href" not in inbox[inbox.index('id="personinbox"') : inbox.index('id="queuetab"')]
    assert 'id="railqueue"' in inbox and "about nothing" in inbox
