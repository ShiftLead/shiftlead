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


def client(monkeypatch, tmp_path):
    """g1 holds TD-301, g2 works. The agent pushes: g1's tail moves, g2 goes idle, g1's tail moves
    again, g1 drops its claim (no shape field: the groups wait for the flush) — and stays open long
    enough for one."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    root = str(tmp_path / "samscrape")
    claim = [{"ref": "TD-301", "status": "claimed", "at": NOW, "pr": 811}]
    g1, g2 = member("g1", root, progress=claim, tail=["a"]), member("g2", root, state="working")
    pushed = [
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

        async def subscribe(self):
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


def test_the_focus_and_inbox_pages_ask_for_the_light_stream():
    import pathlib

    js = (pathlib.Path(__file__).parents[1] / "src/shiftlead/ui/static/app.js").read_text()
    assert '}, "light=1");' in js  # the Inbox
    assert "}, `light=1&focus=${encodeURIComponent(id)}`);" in js  # Focus
