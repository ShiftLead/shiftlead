"""The Inbox's counts, kept once by the UI process and pushed (design §4.4 *Each reading has one owner*,
*The Inbox's counts*; TD-616).

The top bar's numbers — *Needs you*, FYI, overdue, the *answered for you* marks, the build chip — are
the Inbox's sections, classified by `shiftlead` code, so the UI process owns them rather than the host
agent. `CountsKeeper` recounts them when an input moves — an `inbox` or `repos` push, a `gone`, a
session delta that moves `SHAPE_KEYS` or `LIGHT_KEYS` — and once a minute for what falls due, and
sends `{event: "counts", rev, …}` to every page's `/events` stream, only when they differ from the
last sent. `rev` is the keeper's own: it moves when the numbers do, which is what a polling page's
`since=<rev>` asks about.

**Looking** (§4.10 *Told on Telegram*): a page's stream says whether its document is visible
(`{visible: …}`, the one thing a page sends on it), and every recount reads the person inbox with
`watching` while any stream is visible. The minute's recount keeps that read inside
`NOTIFY_WATCHED`, so a page that polls nothing still counts as looking.

The keeper runs only while a stream is connected: the first stream starts it, the last one's going
stops it, and a polling page with no stream gets a fresh count on each read."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sessionorc.client import LocalClient

from .org import LIGHT_KEYS, SHAPE_KEYS

COUNTS_EVERY = 5.0  # seconds between two recounts at most: a burst of deltas is one recount
COUNTS_TICK = 60.0  # the minute's recount — what falls due, the build chip, and Looking's read
RETRY = 5.0  # a lost subscription is tried again after this, while a stream wants it
SEND_WAIT = 2.0  # one page's socket that takes longer than this to take a push is skipped, not waited on

Count = Callable[[bool], Awaitable[dict[str, Any]]]


def _shape(s: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(json.dumps(s.get(k), sort_keys=True) for k in SHAPE_KEYS + LIGHT_KEYS)


class CountsKeeper:
    def __init__(self, count: Count, client: Callable[[], LocalClient] = LocalClient):
        self._count = count  # `watching` → the numbers, or the agent-down shape (`agent_down: True`)
        self._client = client
        self.streams: dict[Any, bool] = {}  # each page's socket → its document is visible
        self.reading: dict[str, Any] | None = None  # the last numbers sent, `rev` among them
        self.rev = 0
        self._dirty = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._at = 0.0  # when the last recount began

    @property
    def watching(self) -> bool:
        return any(self.streams.values())

    async def join(self, ws: Any) -> None:
        """A page's stream opened: it gets the numbers held now, and the keeper runs while it is open."""
        self.streams[ws] = False
        if self._task is None or self._task.done():
            # a reading held by a counts read while no keeper ran is not current: a recount follows
            self.reading = None
            self._task = asyncio.ensure_future(self._run())
        elif self.reading is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(ws.send_text(json.dumps({"event": "counts", **self.reading})), SEND_WAIT)

    async def leave(self, ws: Any) -> None:
        self.streams.pop(ws, None)
        if not self.streams and self._task is not None:
            # detached before the await, so a stream joining meanwhile starts a keeper of its own
            task, self._task = self._task, None
            self.reading = None  # nothing keeps it current now: the next stream starts from a recount
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def visible(self, ws: Any, shown: bool) -> None:
        """The page said whether its document is visible: becoming the first visible page is a
        recount at once, so the home hears Looking without waiting for the minute."""
        if ws not in self.streams:
            return
        was = self.watching
        self.streams[ws] = bool(shown)
        if self.watching and not was:
            self._dirty.set()

    def stir(self) -> None:
        """An input the keeper does not hear pushed moved — the person's settings, written through
        this process — so recount soon."""
        self._dirty.set()

    def _take(self, got: dict[str, Any]) -> dict[str, Any] | None:
        """Hold a fresh count; the message to push when the numbers moved, else None. A count with
        the host agent down is never held: the streams close with it, and a page polls instead."""
        if got.get("agent_down"):
            return None
        if self.reading is not None and {k: v for k, v in self.reading.items() if k != "rev"} == got:
            return None
        self.rev += 1
        self.reading = {**got, "rev": self.rev}
        return {"event": "counts", **self.reading}

    async def _push(self, msg: dict[str, Any]) -> None:
        line = json.dumps(msg)

        async def one(ws: Any) -> None:
            # a closing page's socket, or a stalled one: its own handler cleans up, and no page waits on it
            with contextlib.suppress(Exception):
                await asyncio.wait_for(ws.send_text(line), SEND_WAIT)

        await asyncio.gather(*(one(ws) for ws in list(self.streams)))

    async def recount(self) -> None:
        self._dirty.clear()
        self._at = time.monotonic()
        msg = self._take(await self._count(self.watching))
        if msg is not None:
            await self._push(msg)

    async def read(self, watching: bool, since: str | None = None) -> dict[str, Any]:
        """The counts read (`/api/person/inbox?counts=1`, TD-611 slice 1): the fallback for a page
        whose stream is down. Always a fresh count — it carries that page's `watching` to the home —
        held and pushed like any other when it moved; `{unchanged: true}` when the page already holds
        this `rev`."""
        got = await self._count(watching or self.watching)
        if got.get("agent_down"):
            return got
        msg = self._take(got)
        held = {k: v for k, v in (msg or {"event": "counts", **(self.reading or {})}).items() if k != "event"}
        if msg is not None:
            await self._push(msg)
        if since is not None and since == str(held.get("rev")):
            return {"unchanged": True, "rev": held["rev"]}
        return held

    async def _recounter(self) -> None:
        while True:
            await self._dirty.wait()
            await asyncio.sleep(max(0.0, self._at + COUNTS_EVERY - time.monotonic()))
            try:
                await self.recount()
            except Exception:  # noqa: BLE001 — an agent that could not answer: tried again after COUNTS_EVERY
                self._dirty.set()

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(COUNTS_TICK)
            self._dirty.set()

    async def _run(self) -> None:
        workers = [asyncio.ensure_future(self._recounter()), asyncio.ensure_future(self._ticker())]
        try:
            while True:
                try:
                    await self._follow()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 — the host agent went: try again while a page wants it
                    pass
                await asyncio.sleep(RETRY)
        finally:
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def _follow(self) -> None:
        known: dict[str, tuple[Any, ...]] = {}
        async with self._client() as c:
            with contextlib.suppress(Exception):
                known = {s["id"]: _shape(s) for s in await c.call("list")}
            self._dirty.set()  # a (re)subscribed keeper counts at once
            async for ev in c.subscribe():
                kind = ev.get("event")
                if kind == "session":
                    s = ev.get("session") or {}
                    shape = _shape(s)
                    if known.get(str(s.get("id"))) != shape:
                        known[str(s.get("id"))] = shape
                        self._dirty.set()
                elif kind in ("inbox", "repos", "gone"):
                    if kind == "gone":
                        known.pop(str(ev.get("id")), None)
                    self._dirty.set()
