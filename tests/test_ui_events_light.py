"""TD-572 (§4.5a *team groups*, §4.6): the events stream's cost. The groups — every team header and the
rollup, read over the whole fleet — ride on a delta only when it can move them (`SHAPE_KEYS`, or the
stream's first), are otherwise re-read by one `groups` event at most every `HEADS_EVERY` seconds, and
are not re-sent unchanged; a light stream (`?light=1`, the Focus and Inbox pages) carries no card markup
and no groups, another record only when it moves (`SHAPE_KEYS`, `LIGHT_KEYS`), and its `focus` record whole."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_ui_waiting_wiring import NOW, member, reading

pytestmark = pytest.mark.unit


def client(monkeypatch, tmp_path, hold=0.0, moves=None):
    """g1 holds TD-301, g2 works. The agent pushes: g1's tail moves, g2 goes idle, g1's tail moves
    again, g1 drops its claim (no shape field: the groups wait for the flush) — and stays open long
    enough for one."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    root = str(tmp_path / "samscrape")
    claim = [{"ref": "TD-301", "status": "claimed", "at": NOW, "pr": 811}]
    g1, g2 = member("g1", root, progress=claim, tail=["a"]), member("g2", root, state="working")
    pushed = (moves or (lambda g1, g2: None))(g1, g2) or [
        {**g1, "tail": ["b"]},
        {**g2, "state": "idle"},
        {**g1, "tail": ["c"]},
        {**g1, "tail": ["c"], "progress": []},
    ]
    replies = {"repos": {root: reading(root)}, "doing_log": {}, "list": [g1, g2], "usage": {}, "host": {}}

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "inbox":
                return {"entries": []}
            return replies.get(method, {})

        async def subscribe(self, omit=None):
            await asyncio.sleep(hold)  # for the pages that join the one subscription before it pushes
            for s in pushed:
                yield {"event": "session", "session": s}
            await asyncio.sleep(1.6)  # one HEADS_EVERY and some: the flush's turn

    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    return TestClient(ui.create_app())


def received(c, path):
    """Every event the stream sent but the Inbox's `counts`, which the keeper pushes on every stream
    on its own clock (TD-616, `test_ui_counts.py`)."""
    got = []
    with c.websocket_connect(path) as ws:
        try:
            while True:
                if (ev := json.loads(ws.receive_text())).get("event") != "counts":
                    got.append(ev)
        except WebSocketDisconnect:
            pass
    return got


def test_the_full_stream_sends_the_groups_with_a_shape_change_and_coalesces_the_rest(tmp_path, monkeypatch):
    evs = received(client(monkeypatch, tmp_path), "/events")
    deltas = [e for e in evs if e["event"] == "session"]
    assert [(e["id"], "groups" in e) for e in deltas] == [("g1", True), ("g2", True), ("g1", False), ("g1", False)]
    assert all("html" in e for e in deltas)
    # the claim's drop moved the team's summary, so the flush sent one reading of the groups, after it
    (flushed,) = [e for e in evs if e["event"] == "groups"]
    assert evs[-1] is flushed and flushed["groups"] != deltas[1]["groups"]


def test_a_light_stream_carries_its_focus_whole_and_another_record_only_when_it_moves(tmp_path, monkeypatch):
    evs = received(client(monkeypatch, tmp_path), "/events?light=1&focus=g1")
    assert [e["id"] for e in evs] == ["g1", "g2", "g1", "g1"] and {e["event"] for e in evs} == {"session"}
    assert all("groups" not in e and "rollup" not in e and "html" not in e for e in evs)
    assert evs[0]["session"]["name"] == "g1" and evs[0]["rank"] is not None  # the focus record's view
    assert evs[1] == {"event": "session", "id": "g2", "state": "idle"}  # another's: that it moved


def test_a_light_stream_without_a_focus_hears_only_moves(tmp_path, monkeypatch):
    """The Inbox's stream: g1's tail is not a move; g2's state is (`SHAPE_KEYS`), and so is g1's dropped
    claim (`LIGHT_KEYS`: a light page draws claims, lanes and reports, which move no group)."""
    evs = received(client(monkeypatch, tmp_path), "/events?light=1")
    assert evs == [{"event": "session", "id": "g2", "state": "idle"}, {"event": "session", "id": "g1", "state": "idle"}]


def test_a_look_that_clears_the_unseen_mark_on_a_working_record_reaches_a_light_stream(tmp_path, monkeypatch):
    """§4.2 *Unseen* (TD-1228): the mark can change with no state change — Focus setting `seen_at` on a
    working record — so `seen_at` is a light key and the Inbox's stream hears it; the `turn_at` alone, which
    moves only with a state, is not."""
    turn = "2026-10-29T10:00:00Z"

    def moves(g1, g2):
        return [{**g2, "turn_at": turn}, {**g2, "turn_at": turn, "seen_at": turn}]

    evs = received(client(monkeypatch, tmp_path, moves=moves), "/events?light=1")
    assert evs == [{"event": "session", "id": "g2", "state": "working"}]


def test_three_pages_share_one_subscription_and_each_delta_is_computed_once(tmp_path, monkeypatch):
    """§4.4 *Per-session views* (TD-617): one subscriber per UI process computes a delta's view, compact
    form and card once, and every connected stream takes its part of that one result — two Sessions pages
    get what a lone one gets, and a Focus page its record whole, with the deltas computed once."""
    import threading

    from shiftlead.ui import app as ui

    c = client(monkeypatch, tmp_path, hold=0.5)
    subscribed, computed = [], []
    real_compact = ui.compact_in
    monkeypatch.setattr(ui, "compact_in", lambda *a, **k: computed.append(1) or real_compact(*a, **k))
    Fake = ui.LocalClient
    real_sub = Fake.subscribe

    def counting(self, omit=None):
        subscribed.append(1)
        return real_sub(self, omit)

    monkeypatch.setattr(Fake, "subscribe", counting)
    got: dict[str, list] = {}

    def drain(ws, key):
        got[key] = []
        try:
            while True:
                if (ev := json.loads(ws.receive_text())).get("event") != "counts":
                    got[key].append(ev)
        except WebSocketDisconnect:
            pass

    with (
        c,
        c.websocket_connect("/events") as a,
        c.websocket_connect("/events") as b,
        c.websocket_connect("/events?light=1&focus=g1") as f,
    ):
        ts = [threading.Thread(target=drain, args=(w, k)) for w, k in ((a, "a"), (b, "b"), (f, "f"))]
        for t in ts:
            t.start()
        for t in ts:
            t.join(10)
    # two: the events stream's one, and the counts keeper's (TD-616) — never one per page
    assert subscribed == [1, 1], "every page made a subscription of its own"
    assert len(computed) == 4, f"{len(computed)} views computed for 4 deltas and 3 pages"
    assert got["a"] == got["b"] and [e["id"] for e in got["a"] if e["event"] == "session"] == ["g1", "g2", "g1", "g1"]
    assert [e["id"] for e in got["f"]] == ["g1", "g2", "g1", "g1"] and "session" in got["f"][0]
    full_alone = received(client(monkeypatch, tmp_path), "/events")
    assert [(e["event"], e.get("id"), "groups" in e) for e in got["a"]] == [
        (e["event"], e.get("id"), "groups" in e) for e in full_alone
    ]


def test_the_focus_and_inbox_pages_ask_for_the_light_stream():
    import pathlib

    js = (pathlib.Path(__file__).parents[1] / "src/shiftlead/ui/static/app.js").read_text()
    # the Repo page took the light stream until TD-740: its cards are the Org's now, kept by the full one
    repo = js[js.index("AO.repo = function") :]
    assert "groupsEvent(ev, repo);" in repo and '"light=1"' not in repo[: repo.index("AO.newSession = function")]
    assert "}, `light=1&focus=${encodeURIComponent(id)}`);" in js  # Focus


def test_a_focus_page_takes_its_members_and_controllers_from_its_own_stream(tmp_path, monkeypatch):
    """§4.4 *Per-session views* (TD-617 fix 3): Focus's members and *under* chip are read across
    records, so when a member moves, a member is released, or a controller goes, the server sends the
    focused record's delta again from the fleet it keeps; a peer that is neither moves nothing of it."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    root = str(tmp_path / "samscrape")
    lead = member("lead", root, controllers=["boss"], capabilities=["control"])
    w, other, boss = member("w", root, controllers=["lead"]), member("x", root), member("boss", root)
    pushed = [
        {"event": "session", "session": {**w, "state": "working"}},  # a member moves
        {"event": "session", "session": {**other, "state": "working"}},  # a stranger moves
        {"event": "session", "session": {**w, "state": "working", "controllers": []}},  # released
        {"event": "session", "session": {**other, "state": "idle", "controllers": ["lead"]}},  # joins
        {"event": "gone", "id": "boss"},  # the controller goes
    ]
    replies = {"repos": {root: reading(root)}, "doing_log": {}, "list": [lead, w, other, boss], "usage": {}, "host": {}}

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            return {"entries": []} if method == "inbox" else replies.get(method, {})

        async def subscribe(self, omit=None):
            for ev in pushed:
                yield ev

    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    evs = received(TestClient(ui.create_app()), "/events?light=1&focus=lead")
    mine = [e["session"] for e in evs if e.get("id") == "lead"]
    assert len(mine) == 4, evs  # a member's move, its release, a joining, the controller's going — not the stranger
    assert mine[0]["members"][0]["id"] == "w" and mine[0]["members"][0]["state"] == "working"
    assert mine[1]["members"] == []
    assert [m["id"] for m in mine[2]["members"]] == ["x"]
    assert mine[3]["under"] == [{"id": "boss", "name": "boss", "gone": True}]


def test_the_focus_page_reads_no_sessions_list():
    """TD-617 fix 3: Focus re-reads nothing on a peer's delta; its own stream carries its membership."""
    import pathlib
    import re

    js = (pathlib.Path(__file__).parents[1] / "src/shiftlead/ui/static/app.js").read_text()
    assert not re.search(r"""fetch\(\s*["'`]/api/sessions[/]?["'`?]""", js)
