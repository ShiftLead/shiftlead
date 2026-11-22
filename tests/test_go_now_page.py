"""TD-2027 slice 2, design §4.4 *Board write-back*: *Go now lifts the design and its builds* and §4.5a *Queue card: Go
now*: on a design with a question every surface that stamps its lift draws **Go now — build …** in **Lift the hold**'s
place (label up to three builds then *and <n> more*, title and confirm naming every entry it lifts), every lift press
sends the `builds` the page drew (an empty list under a plain Lift), the routes forward them, and a refusal the home
marks `conflict` (the builds changed since the page was read) is a 409."""

from __future__ import annotations

import pathlib
import re

import pytest

pytest.importorskip("fastapi")

import shiftlead.ui.app  # noqa: E402, F401 — registers every template global the rows read
from shiftlead.ui.common import go_now, templates  # noqa: E402

pytestmark = pytest.mark.unit

APP_JS = (pathlib.Path(shiftlead.ui.app.__file__).parent / "static" / "app.js").read_text()
CONFIRM = "Go now on TD-1? The holds on TD-1, TD-2 and TD-3 are lifted now, and their lanes can pick the builds."


def test_go_now_names_up_to_three_builds_then_and_n_more():
    plain = go_now("TD-1", [])
    assert plain == {
        "label": "Lift the hold",
        "title": "lifts the hold on TD-1",
        "confirm": "Lift the hold on TD-1? Its decision (paul) is lifted now, and the entry can be picked.",
        "builds": [],
    }
    two = go_now("TD-1", ["TD-2", "TD-3"])
    assert two["label"] == "Go now — build TD-2, TD-3"
    assert two["title"] == "lifts the hold on TD-1 and its builds" and two["confirm"] == CONFIRM
    five = go_now("TD-1", ["TD-2", "TD-3", "TD-4", "TD-5", "TD-6"])
    assert five["label"] == "Go now — build TD-2, TD-3, TD-4 and 2 more"
    assert "TD-1, TD-2, TD-3, TD-4, TD-5 and TD-6 are lifted now" in five["confirm"], "the confirm names every one"
    assert five["builds"] == ["TD-2", "TD-3", "TD-4", "TD-5", "TD-6"]
    assert go_now("TD-1", ["TD-2"])["confirm"].startswith("Go now on TD-1? The holds on TD-1 and TD-2 are lifted")


def _button(html: str, label: str) -> str:
    m = re.search(r"<button[^>]*>" + re.escape(label) + "</button>", html)
    assert m, f"no {label} button in {html}"
    return m.group(0)


def test_the_queue_rows_dots_draw_go_now_on_a_design_and_lift_the_hold_elsewhere():
    t = templates.env.from_string('{% import "queue_row.html" as q %}{{ q.menu(r) }}')
    r = {
        "id": "TD-1",
        "repo": "s",
        "lift_here": True,
        "go_builds": ["TD-2", "TD-3"],
        "page": "blocked",
        "needs": "decision",
    }
    html = t.render(r=r)
    b = _button(html, "Go now — build TD-2, TD-3")
    assert 'data-builds="TD-2,TD-3"' in b and 'title="lifts the hold on TD-1 and its builds"' in b
    assert f'data-confirm="{CONFIRM}"' in b and 'data-lift="1"' in b
    assert "Go now · " in html and "Lift the hold" not in html, "the ⋯'s names say Go now"
    plain = t.render(r={**r, "go_builds": []})
    assert 'data-builds=""' in _button(plain, "Lift the hold")


def test_the_entrys_own_item_draws_go_now_where_lift_item_is_set(tmp_path, monkeypatch):
    from test_queue_answer_bar import _ledger, slots
    from test_queue_item_shape import card

    row = _ledger(tmp_path, monkeypatch)
    html = card({**row, "why": "decision", "lift_item": True, "go_builds": ["TD-2"]}, "decide")
    assert "Go now — build TD-2" in slots(html) and "Lift the hold" not in slots(html)
    b = _button(html, "Go now — build TD-2")
    assert 'data-builds="TD-2"' in b and f'data-ref="{row["id"]}"' in b and "Go now lifts it" in html


def test_a_blocked_outcomes_lift_on_a_design_is_go_now():
    from test_queue_could_not_be_done import _owed, press_line
    from test_queue_item_shape import card

    e = _owed(answer=0, answer_given="yes", outcome={"state": "blocked", "text": "the PR is red"})
    e["lift_reply"] = {"root": "/x/r", "id": "TD-1", "go_builds": ["TD-2", "TD-3"]}
    html = card(e, "do")
    b = _button(html, "Go now — build TD-2, TD-3")
    assert 'data-lift-reply="m-5"' in b and 'data-builds="TD-2,TD-3"' in b and f'data-confirm="{CONFIRM}"' in b
    assert "Go now, reply, start a session, or dismiss it." in press_line(html)


def test_the_mail_rows_lifting_answer_about_a_design_is_go_nows():
    ask = {
        "id": "m-1", "kind": "ask", "from": "ao-w", "from_name": "w", "about": "s#TD-1", "text": "May it go?",
        "answers": ["Go — a session builds it", "Wait — nobody picks it"], "lift": ["Go"],
        "go_builds": ["TD-2", "TD-3"],
    }  # fmt: skip
    t = templates.env.from_string('{% from "inbox_row.html" import answers %}{{ answers(e) }}')
    html = t.render(e=ask)
    assert html.count('data-builds="TD-2,TD-3"') == 1 and html.count(f'data-confirm="{CONFIRM}"') == 1
    assert 'title="lifts the hold on TD-1 and its builds"' in html
    plain = t.render(e={**ask, "go_builds": []})
    assert 'data-builds=""' in plain and "Lift the hold on TD-1? Its decision (paul)" in plain


def test_every_lift_press_sends_the_builds_it_drew():
    assert "want.builds = liftBuilds(at);" in APP_JS.split("if (lifting && at.liftReply) {")[1].split("return;")[0]
    lift = APP_JS.split("if (lifting) {")[1].split("return;")[0]
    assert "want.lift = true;" in lift and "want.builds = liftBuilds(at);" in lift
    assert 'if (action === "answer" && b.dataset.lift) body.builds = liftBuilds(b.dataset);' in APP_JS


def _client(monkeypatch, tmp_path, calls: list, refuse: bool = False, inbox: list | None = None):
    from test_ui_queue import client

    from sessionorc import hosts
    from sessionorc.client import AgentError

    checkout = tmp_path / "s"
    checkout.mkdir(exist_ok=True)
    monkeypatch.setattr(type(hosts.local_host()), "repos", lambda self: [str(checkout)])

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "inbox":
                return {"entries": [dict(e) for e in inbox or ()]}
            if method in ("ledger_decide", "ledger_lift_reply", "msg"):
                calls.append((method, kw))
                if refuse:
                    raise AgentError("TD-1's builds changed: read the card again", {"conflict": True})
                if method == "msg":
                    return {"entry": {"id": "m-9"}, "delivered": True, "lifted": "TD-1"}
                return {"lifted": True, "builds": kw.get("builds") or []}
            return {"list": [], "usage": {}, "host": {"name": "kmaster"}}.get(method, {})

    return client(monkeypatch, tmp_path, Fake), str(checkout)


def test_the_routes_forward_builds_and_a_conflict_is_a_409(monkeypatch, tmp_path):
    calls: list = []
    c, root = _client(monkeypatch, tmp_path, calls)
    got = c.post("/api/person/ledger", json={"repo": "s", "id": "TD-1", "lift": True, "builds": ["TD-2", "TD-3"]})
    assert got.status_code == 200 and got.json()["builds"] == ["TD-2", "TD-3"]
    assert calls[-1] == ("ledger_decide", {"repo": root, "id": "TD-1", "lift": True, "builds": ["TD-2", "TD-3"]})
    got = c.post("/api/person/ledger", json={"repo": root, "id": "TD-1", "lift_reply": "m-5", "builds": []})
    assert got.status_code == 200
    assert calls[-1] == ("ledger_lift_reply", {"repo": root, "id": "TD-1", "msg": "m-5", "builds": []})
    assert (
        c.post("/api/person/ledger", json={"repo": "s", "id": "TD-1", "lift": True, "builds": "TD-2"}).status_code
        == 400
    )
    calls.clear()
    c, root = _client(monkeypatch, tmp_path, calls, refuse=True)
    got = c.post("/api/person/ledger", json={"repo": "s", "id": "TD-1", "lift": True, "builds": []})
    assert got.status_code == 409 and "builds changed" in got.json()["detail"]


def test_the_reply_route_forwards_a_lifting_answers_builds(monkeypatch, tmp_path):
    ask = {"id": "m-1", "kind": "ask", "from": "ao-w", "answers": ["Go — a session builds it", "Wait — nobody"]}
    calls: list = []
    c, _ = _client(monkeypatch, tmp_path, calls, inbox=[ask])
    got = c.post("/api/person/reply", json={"reply_to": "m-1", "answer": 0, "builds": ["TD-2"]})
    assert got.status_code == 200 and calls[-1][1]["builds"] == ["TD-2"]
    c.post("/api/person/reply", json={"reply_to": "m-1", "answer": 1})
    assert "builds" not in calls[-1][1], "an answer drawn with no lift sends none"
    calls.clear()
    c, _ = _client(monkeypatch, tmp_path, calls, refuse=True, inbox=[ask])
    assert c.post("/api/person/reply", json={"reply_to": "m-1", "answer": 0, "builds": []}).status_code == 409


def test_lift_ask_target_carries_a_designs_go_builds(tmp_path):
    from test_queue import _entry
    from test_queue_board_hold import HELD, _open
    from test_queue_held_stamps import GO, PART
    from test_queue_lift_here import _setup

    from sessionorc import queue

    entries = [_entry(1, "the design", **HELD), _entry(3, "build b", **PART), _entry(2, "build a", **PART)]
    root, r = _setup(tmp_path, entries, _open("TD-001 decision (paul)", decided=GO, parts="TD-003, TD-002"))
    assert queue.lift_ask_target({root: r}, "TD-001", "r")["go_builds"] == ["TD-002", "TD-003"]
    assert queue.lift_ask_target({root: r}, "TD-002", "r")["go_builds"] == []
