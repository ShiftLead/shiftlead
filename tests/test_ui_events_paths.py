"""TD-575 (TD-572's other paths, §4.5a *team groups*, §4.6): what the events stream sends for an event
that is not a session delta, and the two guards on its groups. A `gone` carries the groups on the full
stream, even when they equal the last reading, and nothing but itself on a light one; a `doing` or a
`repos` event marks the groups for the flush; a reading equal to the last one sent is not sent again;
a flush whose reading failed tries again on its next turn."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from test_ui_events_light import received
from test_ui_waiting_wiring import NOW, member
from test_ui_waiting_wiring import reading as fresh

# the repo reading three days old: its ages (*read 3d ago*) do not move while a test runs, so a
# reading the stream takes twice is the same reading
OLD = (datetime.now(UTC) - timedelta(days=3)).isoformat().replace("+00:00", "Z")


def reading(root: str) -> dict:
    r = fresh(root)
    return {**r, "at": OLD, "prs": {"open": [{**r["prs"]["open"][0], "created": OLD}]}}


pytestmark = pytest.mark.unit


def client(monkeypatch, tmp_path, pushed, *, wait=1.6):
    """g1 holds TD-301, g2 works; `subscribe` yields `pushed(g1, g2)` and stays open `wait` seconds:
    one `HEADS_EVERY` and some, the flush's turn."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    root = str(tmp_path / "samscrape")
    claim = [{"ref": "TD-301", "status": "claimed", "at": NOW, "pr": 811}]
    g1, g2 = member("g1", root, progress=claim, tail=["a"]), member("g2", root, state="working")
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
            for ev in pushed(g1, g2):
                yield ev
            await asyncio.sleep(wait)

    from fastapi.testclient import TestClient

    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    monkeypatch.setattr(ui, "read_boards", lambda *a, **k: ([], ""))
    return TestClient(ui.create_app())


def first_then(*evs):
    """g1's tail moves first — the stream's first delta, which carries the groups — then `evs`."""
    return lambda g1, g2: [{"event": "session", "session": {**g1, "tail": ["b"]}}, *evs]


def test_a_gone_carries_the_groups_on_the_full_stream_even_unchanged_and_nothing_on_a_light_one(tmp_path, monkeypatch):
    """A record nobody knew went: the groups read the same, and still ride on the `gone` (`always`),
    so the page drops the card from its team count; a light page gets the `gone` alone."""
    pushed = first_then({"event": "gone", "id": "ghost"})
    evs = received(client(monkeypatch, tmp_path, pushed, wait=0), "/events")
    (went,) = [e for e in evs if e["event"] == "gone"]
    assert went["id"] == "ghost" and went["groups"] == evs[0]["groups"] and "rollup" in went
    light = received(client(monkeypatch, tmp_path, pushed, wait=0), "/events?light=1")
    assert [e for e in light if e["event"] == "gone"] == [{"event": "gone", "id": "ghost"}]


def test_a_doing_line_is_passed_through_and_marks_the_groups_for_the_flush(tmp_path, monkeypatch):
    """A member said what it is doing: the team card's summary moves, so one `groups` follows it."""
    entry = {"at": NOW, "id": "g1", "name": "g1", "text": "TD-301: reading the fetcher"}
    pushed = first_then({"event": "doing", "team": "grind", "entry": entry})
    evs = received(client(monkeypatch, tmp_path, pushed), "/events")
    assert [e["event"] for e in evs] == ["session", "doing", "groups"]
    assert evs[1]["entry"] == entry and evs[2]["groups"] != evs[0]["groups"]


def test_a_repos_reading_is_passed_through_and_marks_the_groups_for_the_flush(tmp_path, monkeypatch):
    """A checkout's repo facts changed: kept, passed through as sent, and the groups re-read."""

    def pushed(g1, g2):
        root = g1["repo"]
        merged = {**reading(root), "prs": {"open": []}}  # PR #811 merged: the claim's chip moves
        return first_then({"event": "repos", "root": root, "repo": merged})(g1, g2)

    evs = received(client(monkeypatch, tmp_path, pushed), "/events")
    assert [e["event"] for e in evs] == ["session", "repos", "groups"]
    assert evs[2]["groups"] != evs[0]["groups"]


def test_a_reading_equal_to_the_last_one_sent_is_not_sent_again(tmp_path, monkeypatch):
    """g1's tail moves twice: the second marks the groups, the flush reads them, and they are the
    same as the first delta's — so nothing is sent."""

    def pushed(g1, g2):
        return first_then({"event": "session", "session": {**g1, "tail": ["c"]}})(g1, g2)

    evs = received(client(monkeypatch, tmp_path, pushed), "/events")
    assert [e["event"] for e in evs] == ["session", "session"]


def test_a_flush_whose_reading_failed_tries_again_on_its_next_turn(tmp_path, monkeypatch):
    """g1 drops its claim (the groups wait for the flush); the flush's first reading fails, and the
    next turn, `HEADS_EVERY` later, sends it."""
    from shiftlead.ui import app as ui

    real, calls = ui.render_heads, []

    def flaky(groups):
        calls.append(1)
        if len(calls) == 2:  # the first delta's reading is the first call; the flush's is the second
            raise RuntimeError("the agent did not answer")
        return real(groups)

    monkeypatch.setattr(ui, "render_heads", flaky)

    def pushed(g1, g2):
        return first_then({"event": "session", "session": {**g1, "tail": ["b"], "progress": []}})(g1, g2)

    evs = received(client(monkeypatch, tmp_path, pushed, wait=2.8), "/events")
    assert len(calls) == 3
    assert [e["event"] for e in evs] == ["session", "session", "groups"]
