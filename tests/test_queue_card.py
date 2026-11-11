# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-1413, design §4.7 *`ao card`*, §4.5 screen 6 *What tied it*, §4.4 *One owner*: the UI cuts one Queue card from
its own view (`card_view`), each attached item saying how its entry was found (`tied`), and serves it at
`/api/queue/card` with the person's mail cut to ids; `Readings.card` is the one read behind both of `ao card`'s roads."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from test_ui_queue import NOW, at, card, client, fake, ledger_repos, mail, queue, row

from sessionorc.client import AgentError, AgentUnavailable
from shiftlead.ui.inbox import inbox_sections
from shiftlead.ui.queue import attach, card_index, card_view, item_home, ledger_home, queue_view

pytestmark = pytest.mark.unit

SECRETS = ("SECRET-ASK", "SECRET-MENTION", "SECRET-HELD", "SECRET-OUTCOME", "SECRET-ROW", "SECRET-LINE")


def test_item_home_says_how_each_item_found_its_entry():
    idx = card_index(queue(repo2=True))
    assert item_home(mail("m1", "TD-20 too", about="TD-21"), idx)["tied"] == {"by": "about", "ref": "s#TD-021"}
    assert item_home(mail("m2", "TD-20: split it?"), idx)["tied"] == {"by": "words", "ref": "s#TD-020"}
    board = {"row": "board", "id": "b", "text": "Pick. Context: TD-30 · the design. Due: 2026-10-17"}
    assert item_home(board, idx)["tied"] == {"by": "context", "ref": "TD-030"}
    # a bare ref on another repo's board is that repo's: qualified with the line's own repo
    assert item_home({**board, "repo_name": "s"}, idx)["tied"] == {"by": "context", "ref": "s#TD-030"}
    red = {"row": "red_pr", "id": "red_pr:s:5", "repo": "s", "title": "slice 2", "branch": "TD-10-thing"}
    assert item_home(red, idx)["tied"] == {"by": "pr", "ref": "s#TD-010"}
    fork = {"row": "fork_pr", "id": "fork_pr:s:6", "title": "fix TD-20", "repo": "s", "pr": 6}
    assert item_home(fork, idx)["tied"] == {"by": "title", "ref": "s#TD-020"}  # its own repo's (TD-1509)
    assert item_home(mail("m3", "about nothing"), idx)["tied"] is None
    assert item_home({"row": "state", "id": "x"}, idx)["tied"] is None
    assert ledger_home({"name": "s", "id": "TD-21"}, idx)["tied"] == {"by": "entry", "ref": "s#TD-021"}
    assert ledger_home({"name": "s", "id": "TD-99"}, idx)["tied"] is None
    # the Inbox's rows carry it (its payload is these rows)
    secs = inbox_sections([mail("m1", "TD-21: which?")], now=NOW, cards=idx)
    assert secs["needs"][0]["tied"] == {"by": "words", "ref": "s#TD-021"}


def fixture() -> tuple[dict, dict]:
    """The queue, with answered marks whose words are the person's, and `attach(raw=True)` over an ask on TD-21
    that mentions TD-30, a board line on TD-21, a red PR, a fork's PR and a ledger row the person answered."""
    q = queue(repo2=True)
    q["origins"] = {"s": "shiftlead/s"}
    c20 = next(c for c in q["cards"] if c["id"] == "s#TD-20")
    c20["top"]["answered"] = {"mid": "m-9", "asker": "g1", "name": "grinder-1", "kind": "ask", "until": "", "closed_at": None,
                              "outcome": {"text": "SECRET-OUTCOME"}, "line": "SECRET-LINE"}  # fmt: skip
    c20["rows"][0]["answered"] = {"mid": "", "asker": "g1", "name": "grinder-1", "kind": "board", "until": "",
                                  "closed_at": "2026-10-16", "outcome": None, "line": "SECRET-ROW"}  # fmt: skip
    idx = card_index(q)
    entries = [mail("m1", "TD-21: SECRET-ASK? TD-30 SECRET-MENTION waits on it")]
    boards = [{"row": "board", "id": "b1", "key": "board:k1", "kind": "decide", "repo_name": "s", "due": "2026-10-16",
               "text": "**Pick** one. Context: TD-21. Due: 2026-10-16"}]  # fmt: skip
    secs = inbox_sections(entries, now=NOW, boards=boards, cards=idx)
    secs["needs"] += [
        {"row": "red_pr", "id": "red_pr:s:5", "repo": "s", "pr": 5, "title": "TD-20 slice", **item_home({"row": "red_pr", "repo": "s", "title": "TD-20 slice"}, idx)},
        {"row": "fork_pr", "id": "fork_pr:s:6", "repo": "s", "pr": 6, "title": "fix TD-20", **item_home({"row": "fork_pr", "repo": "s", "title": "fix TD-20"}, idx)},
    ]  # fmt: skip
    held = {"asker": "g1", "name": "grinder-1", "kind": "ask", "words": "SECRET-HELD", "age": "1h", "mid": "m-8",
            "outcome": {"text": "SECRET-OUTCOME"}, "until": ""}  # fmt: skip
    later = [{"row": "ledger", "id": "TD-20", "name": "s", "title": "entry", "why": "decision", "answered": held,
              "later_section": "later", "row_id": "ledger:s:TD-20", **ledger_home({"name": "s", "id": "TD-20"}, idx)}]  # fmt: skip
    return q, attach(secs, lambda e, sec: f"<{e.get('id')}>", later, raw=True)


def test_attach_raw_carries_each_items_row_tied_and_repo_and_keeps_the_page_unchanged():
    q, got = fixture()
    items = {m["id"]: m for sec in got["cards"]["s#TD-20"].values() for m in sec}
    assert items["m1"]["row"]["text"].startswith("TD-21:") and "html" not in items["m1"]["row"]
    assert items["m1"]["tied"] == {"by": "words", "ref": "s#TD-021"} and items["m1"]["repo"] == ""
    assert items["b1"]["repo"] == "s" and items["b1"]["tied"] == {"by": "context", "ref": "s#TD-021"}
    assert items["red_pr:s:5"]["repo"] == "s" and items["red_pr:s:5"]["tied"]["by"] == "pr"
    assert items["fork_pr:s:6"]["repo"] == "s" and items["fork_pr:s:6"]["tied"]["by"] == "title"
    assert items["ledger:s:TD-20"]["repo"] == "s" and items["ledger:s:TD-20"]["tied"] == {
        "by": "entry",
        "ref": "s#TD-020",
    }
    # `mentioned` keeps its shape; `mentioned_items` names the item, its row kind, kind and words
    assert got["mentioned"] == {"s#TD-30": {"m1": "TD-21: SECRET-ASK? TD-30 SECRET-MENTION waits on it"}}
    assert got["mentioned_items"] == {"s#TD-30": [{"item": "m1", "row_kind": "", "kind": "ask",
                                                    "words": "TD-21: SECRET-ASK? TD-30 SECRET-MENTION waits on it"}]}  # fmt: skip
    # the page's call is unchanged, and its view runs on the raw answer
    plain = attach({"needs": []}, lambda e, sec: "")
    assert "mentioned_items" not in plain
    assert queue_view(q, NOW, got)["n"]["cards"] == 4


def test_card_view_finds_a_card_by_any_entry_it_holds():
    q, got = fixture()

    def view(i: str):
        return card_view(q, got, i, NOW, [], words=True)

    for i in ("s#TD-20", "s#TD-21", "TD-21", "s#TD-021", "ShiftLead/s#TD-21"):
        assert view(i)["card"]["id"] == "s#TD-20", i
    assert view("s#TD-9")["card"]["id"] == "s#TD-10"  # an archived row
    assert view("TD-5")["card"]["id"] == "db#TD-5"  # unnormalised, the one repo holding it
    v = view("TD-21")
    assert set(v) == {"card", "wants", "mentioned", "mail", "at"} and v["mail"] == "full" and v["at"] == NOW.isoformat()
    assert "lines" not in v["card"] and "wants" not in v["card"] and v["card"]["status"] == "needs you"
    assert v["wants"]["n"]["decide"] >= 2 and v["wants"]["n"]["do"] == 2
    ids = {m["item"] for w in ("decide", "do", "with_you", "answered") for m in v["wants"][w]}
    assert {"m1", "board:k1", "s#5", "fork PR s#6", "s#TD-020"} <= ids
    assert all("html" not in m and "row" in m for w in ("decide", "do") for m in v["wants"][w])
    assert view("s#TD-30")["mentioned"] == {"s#TD-30": got["mentioned_items"]["s#TD-30"]}
    assert view("s#TD-30")["card"]["top"]["mentioned"][0]["item"] == "m1"
    assert view("s#TD-99") is None and view("TD-99") is None and view("ShiftLead/s#TD-1") is None
    assert view("s#TD-2") == {"completed": {"closed": at(3), "pr": 12}}


def test_a_card_in_no_group_the_page_draws_is_none():
    q = queue()
    q["cards"][0]["group"] = "elsewhere"
    assert card_view(q, {}, "s#TD-10", NOW, [], words=True) is None


def test_a_bare_id_two_repos_hold_is_ambiguous():
    q = queue()
    q["cards"].append(card(row("db", "TD-21", "db's own"), place=3))
    got = card_view(q, {}, "TD-21", NOW, [], words=True)
    assert got == {"ambiguous": ["db#TD-021", "s#TD-021"]}


def test_without_words_no_mail_is_in_the_card_and_the_rest_is_whole():
    q, got = fixture()
    for i in ("TD-20", "TD-30"):
        full = json.dumps(card_view(q, got, i, NOW, [], words=True), default=str)
        cut = card_view(q, got, i, NOW, [], words=False)
        text = json.dumps(cut, default=str)
        assert cut["mail"] == "ids"
        for s in SECRETS:
            assert s not in text, (i, s)
        if i == "TD-20":
            assert all(s in full for s in SECRETS if s != "SECRET-MENTION")
    cut = card_view(q, got, "TD-20", NOW, [], words=False)
    (m1,) = [m for m in cut["wants"]["decide"] if m["item"] == "m1"]
    assert m1["row"] == {"id": "m1", "kind": "ask", "from": "g1", "at": at(1)} and m1["tied"]["by"] == "words"
    (b1,) = [m for m in cut["wants"]["decide"] if m["item"] == "board:k1"]
    assert b1["row"]["text"].startswith("**Pick** one.")  # a board line keeps its text
    (held,) = cut["wants"]["answered"]
    assert held["row"]["answered"] == {
        "asker": "g1",
        "name": "grinder-1",
        "kind": "ask",
        "age": "1h",
        "mid": "m-8",
        "until": "",
    }
    assert cut["card"]["top"]["answered"] == {
        "mid": "m-9",
        "asker": "g1",
        "name": "grinder-1",
        "kind": "ask",
        "until": "",
        "closed_at": None,
    }
    assert card_view(q, got, "TD-30", NOW, [], words=False)["mentioned"]["s#TD-30"] == [
        {"item": "m1", "row_kind": "", "kind": "ask"}
    ]


def test_the_endpoint_answers_its_five_statuses(tmp_path, monkeypatch):
    q = queue()
    entries = [mail("m1", "TD-21: SECRET-ASK?")]
    c = client(monkeypatch, tmp_path, fake(q, entries, ledger_repos()))
    got = c.get("/api/queue/card", params={"id": "TD-21"})
    assert got.status_code == 200 and got.json()["card"]["id"] == "s#TD-20" and got.json()["mail"] == "ids"
    assert "SECRET-ASK" not in got.text and any(m["item"] == "m1" for m in got.json()["wants"]["decide"])
    assert c.get("/api/queue/card", params={"id": "s#TD-2"}).json() == {"completed": {"closed": at(3), "pr": 12}}
    nope = c.get("/api/queue/card", params={"id": "TD-99"})
    assert nope.status_code == 404 and nope.json() == {"error": "no open card holds TD-99"}
    old = client(monkeypatch, tmp_path, fake(None)).get("/api/queue/card", params={"id": "TD-21"})
    assert old.status_code == 502 and old.json()["error"].startswith("the home did not serve the Queue: ")

    class Down(fake(q)):
        async def call(self, method, **kw):
            raise AgentUnavailable("no socket")

    down = client(monkeypatch, tmp_path, Down).get("/api/queue/card", params={"id": "TD-21"})
    assert down.status_code == 503 and down.json() == {"agent_down": True}

    class Refused(fake(q)):
        async def call(self, method, **kw):
            if method == "inbox":
                raise AgentError("the person inbox is the person's")
            return await super().call(method, **kw)

    no = client(monkeypatch, tmp_path, Refused).get("/api/queue/card", params={"id": "TD-21"})
    assert no.status_code == 400 and no.json() == {"error": "the person inbox is the person's"}


def test_the_in_process_road_carries_the_mail_and_draws_the_pages_card(tmp_path, monkeypatch):
    q = queue()
    entries = [mail("m1", "TD-21: SECRET-ASK?")]
    c = client(monkeypatch, tmp_path, fake(q, entries, ledger_repos()))  # patches the app's client and clock
    from shiftlead.ui import app as ui

    got = asyncio.run(ui.Readings().card("TD-21", True))
    assert got["mail"] == "full" and "SECRET-ASK" in json.dumps(got, default=str)
    served = c.get("/api/queue/card", params={"id": "TD-21"}).json()
    assert served["card"]["status"] == got["card"]["status"] == "needs you"
    assert served["wants"]["n"] == got["wants"]["n"]
    assert [m["item"] for m in served["wants"]["decide"]] == [m["item"] for m in got["wants"]["decide"]]
    # the page draws the same card: its wants, by the page's own read
    html = c.get("/queue").text
    card20 = html[html.index('data-card="s#TD-20"') : html.index('data-card="s#TD-30"')]
    assert "SECRET-ASK" in card20 and "Lift the hold" in card20
    assert json.loads(json.dumps(got, default=str))["card"]["id"] == "s#TD-20"


@pytest.mark.parametrize(
    ("fail", "status", "kind"),
    [("queue", 503, "down"), ("queue", 400, "no_queue"), ("inbox", 400, "refused"), ("list", 503, "down")],
)
def test_a_refused_read_is_a_card_refused(fail, status, kind):
    from shiftlead.ui import app as ui

    async def call(method, **kw):
        if method == fail:
            raise HTTPException(status, f"no {method}")
        return {"queue": queue(), "list": [], "inbox": {"entries": []}}.get(method, {})

    with pytest.raises(ui.CardRefused) as e:
        asyncio.run(ui.Readings(call).card("TD-21", False))
    assert e.value.kind == kind and e.value.why == f"no {fail}"


def test_the_answer_is_json_with_dates_in_its_rows():
    q, got = fixture()
    q["cards"][0]["top"]["closed"] = datetime(2026, 10, 16, tzinfo=NOW.tzinfo)
    v = card_view(q, got, "TD-10", NOW, [], words=False)
    assert json.loads(json.dumps(v, default=str))["card"]["top"]["closed"].startswith("2026-10-16")
