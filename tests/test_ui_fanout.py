"""TD-617 (design §4.4 *Per-session views*): the events stream's one subscriber — started by the first
page's stream, stopped by the last one's going, each event handed to `step` once, and a run that fails
ending every stream it holds so each page reconnects to a run of its own."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from conftest import wait_for

from shiftlead.ui import fanout as fan_mod
from shiftlead.ui.fanout import FAILED, Fanout, Stream

pytestmark = pytest.mark.unit


class Sock:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))


class Client:
    def __init__(self, events: asyncio.Queue, opened: list[int]) -> None:
        self.events = events
        opened.append(1)

    async def __aenter__(self) -> Client:
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False

    async def subscribe(self, omit=None):
        while (ev := await self.events.get()) is not None:
            if isinstance(ev, BaseException):
                raise ev
            yield ev


def hub() -> tuple[Fanout, asyncio.Queue, list[int], list[dict[str, Any]]]:
    events: asyncio.Queue = asyncio.Queue()
    opened: list[int] = []
    stepped: list[dict[str, Any]] = []

    async def seed() -> dict[str, Any]:
        return {}

    async def step(run, ev) -> None:
        stepped.append(ev)
        if ev.get("bad"):
            raise ValueError("this record does not draw")
        run.to_all(run.live, ev)

    async def regroup(state) -> dict[str, Any]:
        return {"groups": []}

    return Fanout(lambda: Client(events, opened), seed, step, regroup), events, opened, stepped


def joined(f: Fanout, n: int) -> list[tuple[Stream, Sock, asyncio.Task]]:
    out = []
    for _ in range(n):
        ws = Sock()
        s = Stream(ws)
        f.join(s)
        out.append((s, ws, asyncio.ensure_future(s.pump())))
    return out


async def test_every_stream_gets_each_event_from_one_step_and_the_last_leave_stops_the_run():
    f, events, opened, stepped = hub()
    pages = joined(f, 3)
    await events.put({"event": "doing", "n": 1})
    assert await wait_for(lambda: all(ws.sent for _, ws, _ in pages), timeout=2.0, step=0.01)
    assert opened == [1] and stepped == [{"event": "doing", "n": 1}]
    assert all(ws.sent == [{"event": "doing", "n": 1}] for _, ws, _ in pages)
    run = f.run
    for s, _, t in pages:
        f.leave(s)
        t.cancel()
    assert f.run is None
    assert await wait_for(lambda: run.task.done(), timeout=2.0, step=0.01)
    joined(f, 1)  # a page after the last left: a run of its own
    assert await wait_for(lambda: opened == [1, 1], timeout=2.0, step=0.01)


async def test_a_failed_run_ends_every_stream_saying_so_and_a_lost_agent_ends_them_quietly():
    f, events, _, _ = hub()
    pages = joined(f, 2)
    await events.put(RuntimeError("boom"))
    assert await wait_for(lambda: all(t.done() for _, _, t in pages), timeout=2.0, step=0.01)
    assert all(ws.sent == [{"event": "error", "text": FAILED}] for _, ws, _ in pages)
    assert f.run is None
    pages = joined(f, 1)
    await events.put(ConnectionError("gone"))
    assert await wait_for(lambda: pages[0][2].done(), timeout=2.0, step=0.01)
    assert pages[0][1].sent == []


async def test_an_event_that_fails_to_draw_is_skipped_and_every_stream_goes_on():
    f, events, _, _ = hub()
    pages = joined(f, 2)
    await events.put({"event": "session", "bad": True})
    await events.put({"event": "doing", "n": 2})
    assert await wait_for(lambda: all(ws.sent for _, ws, _ in pages), timeout=2.0, step=0.01)
    assert all(ws.sent == [{"event": "doing", "n": 2}] for _, ws, _ in pages)
    assert not any(t.done() for _, _, t in pages) and f.run is not None
    for s, _, t in pages:
        f.leave(s)
        t.cancel()


async def test_a_page_too_far_behind_is_ended_to_reconnect(monkeypatch):
    monkeypatch.setattr(fan_mod, "QUEUE_MAX", 3)
    s = Stream(Sock())
    for i in range(5):
        s.put(json.dumps({"n": i}))
    await asyncio.wait_for(s.pump(), 2.0)  # ends by itself: the fourth put ended it
    assert [e["n"] for e in s.ws.sent] == [0, 1, 2]
