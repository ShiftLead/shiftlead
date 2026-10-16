"""TD-616 slice 2 (design §4.4 *The Inbox's counts*, §4.10 *Told on Telegram*): the UI process keeps the
top bar's numbers once and pushes them as `counts` on every page's stream, only when they change; a
counts read is the fallback for a page whose stream is down and answers `{unchanged: true}` to the
`since=<rev>` it already holds; and a page's stream carries *Looking* — `{visible}` — which the
keeper hands the home on its recount, so a visible page that polls nothing still keeps Telegram quiet."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from conftest import wait_for

from shiftlead.ui import counts as counts_mod
from shiftlead.ui.counts import CountsKeeper


class Sock:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


class Client:
    """A host agent that answers `list` and pushes what a test puts on `events`."""

    events: asyncio.Queue[dict[str, Any]]

    def __init__(self) -> None:
        self.events = asyncio.Queue()

    async def __aenter__(self) -> Client:
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False

    async def call(self, method: str, **kw: Any) -> Any:
        return [{"id": "w", "state": "idle"}] if method == "list" else {}

    async def subscribe(self, omit=None):
        while True:
            yield await self.events.get()


def keeper(numbers: dict[str, Any], seen: list[bool]) -> tuple[CountsKeeper, Client]:
    client = Client()

    async def count(watching: bool) -> dict[str, Any]:
        seen.append(watching)
        return dict(numbers)

    return CountsKeeper(count, client=lambda: client), client


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(counts_mod, "COUNTS_EVERY", 0.02)
    monkeypatch.setattr(counts_mod, "COUNTS_TICK", 3600.0)


@pytest.mark.unit
async def test_a_stream_gets_the_numbers_once_per_change_and_never_an_unchanged_recount(fast):
    numbers, seen = {"needs": 1, "fyi_n": 0}, []
    k, client = keeper(numbers, seen)
    ws = Sock()
    await k.join(ws)
    assert await wait_for(lambda: ws.sent, timeout=2.0, step=0.01), "the first stream never got a count"
    assert ws.sent == [{"event": "counts", "needs": 1, "fyi_n": 0, "rev": 1}]
    await client.events.put({"event": "repos"})  # an input moved, the numbers did not
    assert await wait_for(lambda: len(seen) == 2, timeout=2.0, step=0.01)
    await asyncio.sleep(0.05)
    assert len(ws.sent) == 1 and k.rev == 1
    numbers["needs"] = 2
    await client.events.put({"event": "inbox", "rev": 7})
    assert await wait_for(lambda: len(ws.sent) == 2, timeout=2.0, step=0.01)
    assert ws.sent[-1] == {"event": "counts", "needs": 2, "fyi_n": 0, "rev": 2}
    late = Sock()
    await k.join(late)  # a page opened later gets what is held at once, no recount of its own
    assert late.sent == [ws.sent[-1]]
    await k.leave(ws)
    await k.leave(late)


@pytest.mark.unit
async def test_a_session_delta_recounts_only_when_it_moves_a_state_row(fast):
    seen: list[bool] = []
    k, client = keeper({"needs": 0}, seen)
    ws = Sock()
    await k.join(ws)
    assert await wait_for(lambda: len(seen) == 1, timeout=2.0, step=0.01)
    await client.events.put({"event": "session", "session": {"id": "w", "state": "idle"}})  # as listed
    await asyncio.sleep(0.1)
    assert len(seen) == 1
    await client.events.put({"event": "session", "session": {"id": "w", "state": "needs-you"}})
    assert await wait_for(lambda: len(seen) == 2, timeout=2.0, step=0.01)
    await k.leave(ws)


@pytest.mark.unit
async def test_since_the_held_rev_answers_unchanged_and_a_down_agent_is_never_held(fast):
    numbers, seen = {"needs": 3}, []
    k, _ = keeper(numbers, seen)
    got = await k.read(False)
    assert got == {"needs": 3, "rev": 1}
    assert await k.read(False, since="1") == {"unchanged": True, "rev": 1}
    numbers["needs"] = 4
    assert await k.read(True, since="1") == {"needs": 4, "rev": 2}  # it moved: the numbers, not unchanged
    assert seen == [False, False, True]  # each read carries its page's `watching` to the home
    numbers.clear()
    numbers.update({"needs": None, "agent_down": True})
    assert (await k.read(False, since="2"))["agent_down"] is True  # never `unchanged` over a down agent
    assert k.reading == {"needs": 4, "rev": 2}


@pytest.mark.unit
async def test_a_visible_stream_is_looking_and_a_hidden_or_closed_one_stops_at_once(fast):
    seen: list[bool] = []
    k, _ = keeper({"needs": 0}, seen)
    a, b = Sock(), Sock()
    await k.join(a)
    await k.join(b)
    assert await wait_for(lambda: seen, timeout=2.0, step=0.01)
    assert seen == [False] and not k.watching
    k.visible(a, True)  # the first visible page is a recount now, not at the minute
    assert await wait_for(lambda: seen[-1] is True, timeout=2.0, step=0.01)
    k.visible(b, True)
    k.visible(a, False)
    assert k.watching  # b still looks
    await k.leave(b)
    assert not k.watching  # a closed tab drops out of *any visible* the moment it goes
    k.visible(b, True)  # a page that left says nothing more
    assert not k.watching
    await k.leave(a)
    assert k._task is None and k.reading is None  # the last stream stops the keeper


async def _events(app):
    """An `/events` stream driven through the ASGI app (as `test_ui_stop.py`): its inbound queue
    and every `counts` it was sent."""
    inbound: asyncio.Queue[dict] = asyncio.Queue()
    counts: list[dict] = []

    async def send(msg: dict) -> None:
        if msg.get("type") == "websocket.send" and (ev := json.loads(msg.get("text") or "{}")).get("event") == "counts":
            counts.append(ev)

    scope = {"type": "websocket", "path": "/events", "raw_path": b"/events", "query_string": b"light=1", "headers": []}
    await inbound.put({"type": "websocket.connect"})
    return inbound, counts, asyncio.ensure_future(app(scope, inbound.get, send))


@pytest.mark.integration
async def test_the_stream_carries_counts_and_looking_with_no_inbox_request(agent, tmp_path, monkeypatch):
    """A person-inbox write reaches an open stream as `counts`; a visible stream keeps the home's
    *Looking* time fresh by the keeper's recount alone — no `/api/person/inbox` request is made, the
    app is driven only through its socket — and a hidden one stops it (the techlead's conditions on
    the steer of 2026-10-12, m-d5e63070e1e2)."""
    from sessionorc.client import LocalClient
    from shiftlead.ui.app import create_app

    monkeypatch.setattr(counts_mod, "COUNTS_EVERY", 0.05)
    monkeypatch.setattr(counts_mod, "COUNTS_TICK", 0.3)
    inbound, counts, handler = await _events(create_app())
    try:
        assert await wait_for(lambda: counts, timeout=10.0, step=0.05), "the stream never carried counts"
        first = counts[-1]
        assert first["needs"] == 0 and first["agent_down"] is False
        async with LocalClient() as person:
            w = (
                await person.call(
                    "create", name="w", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"], unattended=True
                )
            )["id"]
            async with LocalClient(caller=w) as c:
                await c.call("msg", to="person", kind="ask", text="may I?")
            assert await wait_for(lambda: counts[-1]["needs"] == 1, timeout=10.0, step=0.05), counts[-1]
            assert counts[-1]["rev"] > first["rev"]

            assert agent._notify_watched_at is None  # nothing visible yet: the keeper read without it
            await inbound.put({"type": "websocket.receive", "text": json.dumps({"visible": True})})
            assert await wait_for(lambda: agent._notify_watched_at is not None, timeout=5.0, step=0.05)
            t1 = agent._notify_watched_at
            assert await wait_for(lambda: agent._notify_watched_at > t1, timeout=5.0, step=0.05), "Looking went stale"

            await inbound.put({"type": "websocket.receive", "text": json.dumps({"visible": False})})
            await asyncio.sleep(0.5)  # a recount already under way may still say visible
            t2 = agent._notify_watched_at
            await asyncio.sleep(1.0)  # three ticks
            assert agent._notify_watched_at == t2, "a hidden page still counted as looking"
            await person.call("kill", id=w)
    finally:
        await inbound.put({"type": "websocket.disconnect", "code": 1001})
        done, _ = await asyncio.wait({handler}, timeout=3.0)
        if not done:
            handler.cancel()
    assert handler in done, "the /events handler outlived its browser"
    assert await wait_for(lambda: not agent._subscribers, timeout=3.0, step=0.05), "the keeper's subscription leaked"


@pytest.mark.unit
def test_the_top_bar_draws_the_streams_counts_and_polls_only_while_no_stream_is_up():
    """§4.4 *The top bar draws from the stream and polls nothing*; §4.10 *Looking* on the stream."""
    from pathlib import Path

    js = (Path(__file__).parents[1] / "src" / "shiftlead" / "ui" / "static" / "app.js").read_text()
    assert 'ev.event === "counts") AO.drawCounts(ev)' in js
    assert "else if (!streamsUp) AO.refreshInboxCount();" in js  # the 20 s poll, only with no stream up
    assert "if (!up) { up = true; streamsUp++; }" in js and "if (up) { up = false; streamsUp--; }" in js
    assert "since=${countsRev}" in js and "if (got.unchanged) return got;" in js
    say = js.split("const say = () => { if (sock")[1].split("\n")[0]
    assert "visible: document.visibilityState" in say and "sock.send(" in say
    assert 'document.addEventListener("visibilitychange", say)' in js
    # the backoff is put back at the first message that is not `error`, never at the open (TD-694)
    assert "ws.onopen = () => { say(); };" in js
    assert 'if (ev.event === "error") {' in js and "return; }\n        delay = 500;\n        setDown(false);" in js


@pytest.mark.unit
async def test_a_stream_joining_while_the_last_one_leaves_gets_a_keeper_of_its_own(fast):
    """A quick reload: the old page's leave awaits its keeper's end, and the new page joins in that
    window — it must not be left with no keeper (and, its stream up, no poll either)."""
    seen: list[bool] = []
    k, _ = keeper({"needs": 1}, seen)
    old, new = Sock(), Sock()
    await k.join(old)
    assert await wait_for(lambda: old.sent, timeout=2.0, step=0.01)
    leaving = asyncio.ensure_future(k.leave(old))
    await asyncio.sleep(0)  # leave is awaiting the cancelled keeper
    await k.join(new)
    await leaving
    assert k._task is not None and not k._task.done()
    assert await wait_for(lambda: new.sent, timeout=2.0, step=0.01), "the new page never got its counts"
    await k.leave(new)


@pytest.mark.unit
async def test_a_stalled_socket_holds_no_other_page_back(fast, monkeypatch):
    monkeypatch.setattr(counts_mod, "SEND_WAIT", 0.05)

    class Stalled(Sock):
        async def send_text(self, text: str) -> None:
            await asyncio.sleep(3600)

    k, _ = keeper({"needs": 1}, [])
    stuck, ok = Stalled(), Sock()
    await k.join(stuck)
    await k.join(ok)
    assert await wait_for(lambda: ok.sent, timeout=2.0, step=0.01)
    await k.leave(stuck)
    await k.leave(ok)
