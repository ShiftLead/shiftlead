"""The events stream's one subscriber, fanned out to every page (design §4.4 *Each reading has one owner*,
*Per-session views*; §4.5 *Live state*; TD-617).

Every page's `/events` socket is a `Stream`: a queue the page's own task drains onto its socket. One
`Fanout` per UI process holds the host agent's subscription — the first stream starts it, the last one's
going stops it — and hands each event to `step` once, which computes what the event costs (the session's
view, its compact form, its rendered card, the groups) once and puts each stream its part: a full stream
the card and, when it can move them, the groups; a light one `{id, state}` or its focus record whole.
`step` runs under the run's lock, as does the groups' coalescing `flush`, so a flush's reading is never
put after a newer delta's.

A run whose subscription ends — the host agent gone, or a failure — ends every stream it holds, each
page reconnects, and the next stream starts a run of its own, seeded afresh."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sessionorc.client import AgentUnavailable

from .org import HEADS_EVERY

log = logging.getLogger(__name__)

QUEUE_MAX = 2000  # a page this far behind is ended rather than buffered; it reconnects and reloads
FAILED = "events stream failed; reconnecting"


class Stream:
    """One page's `/events` socket: what the run puts for it, sent in order by `pump`."""

    def __init__(self, ws: Any, light: bool = False, focus: str = "") -> None:
        self.ws, self.light, self.focus = ws, light, focus
        self.heads_key: str | None = None  # the groups this page last got, as their JSON
        self._queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
        self._ended = False

    def put(self, text: str) -> None:
        if self._ended:
            return
        if self._queue.qsize() >= QUEUE_MAX:
            log.warning("an events stream fell %d messages behind; it is ended to reconnect", QUEUE_MAX)
            self.end()
            return
        self._queue.put_nowait(("send", text))

    def end(self, error: str | None = None) -> None:
        """No more for this page: `pump` sends `error`, when there is one, and returns."""
        if not self._ended:
            self._ended = True
            self._queue.put_nowait(("end", error))

    async def pump(self) -> None:
        while True:
            what, text = await self._queue.get()
            if what == "end":
                if text:
                    with contextlib.suppress(Exception):
                        await self.ws.send_text(json.dumps({"event": "error", "text": text}))
                return
            await self.ws.send_text(text or "")


Step = Callable[["Run", dict[str, Any]], Awaitable[None]]


class Run:
    """One subscription and the fleet it keeps, for the streams that joined it."""

    def __init__(
        self,
        open_client: Callable[[], Any],
        seed: Callable[[], Awaitable[Any]],
        step: Step,
        regroup: Callable[[Any], Awaitable[dict[str, Any]]],
    ) -> None:
        self._open, self._seed, self._step, self._regroup = open_client, seed, step, regroup
        self.streams: list[Stream] = []
        self.state: Any = None
        self.dirty = asyncio.Event()  # a delta moved what the groups read; `flush` re-reads them
        self.lock = asyncio.Lock()
        self._at = 0.0  # when the groups were last read
        self.task: asyncio.Task[None] | None = None

    @property
    def full(self) -> list[Stream]:
        return [s for s in self.streams if not s.light]

    def light(self, *, focus: str | None = None, other: str | None = None) -> list[Stream]:
        """The light streams — those focused on `focus`, or those not focused on `other`."""
        out = [s for s in self.streams if s.light]
        if focus is not None:
            out = [s for s in out if s.focus == focus]
        if other is not None:
            out = [s for s in out if s.focus != other]
        return out

    async def heads(self) -> dict[str, Any]:
        """The groups, read now: `dirty` is cleared first, so a delta that lands meanwhile marks the next."""
        self.dirty.clear()
        self._at = time.monotonic()
        return await self._regroup(self.state)

    def to_all(self, streams: list[Stream], msg: dict[str, Any]) -> None:
        if streams:
            text = json.dumps(msg)
            for s in streams:
                s.put(text)

    async def to_full(self, msg: dict[str, Any], *, always: bool) -> None:
        """`msg` to every full stream, the groups on it where they are due: on every stream when
        `always` (a delta that can move them, a `gone`), else on a stream that has none yet — and,
        once read, on any whose last groups differ. Otherwise the groups wait for `flush`."""
        full = self.full
        if not full:
            return
        if not always and all(s.heads_key is not None for s in full):
            self.dirty.set()
            self.to_all(full, msg)
            return
        got = await self.heads()
        key = json.dumps(got, sort_keys=True)
        plain, carried = json.dumps(msg), json.dumps({**msg, **got})
        for s in full:
            if always or s.heads_key != key:
                s.heads_key = key
                s.put(carried)
            else:
                s.put(plain)

    async def _flush(self) -> None:
        while True:
            await self.dirty.wait()
            await asyncio.sleep(max(0.0, self._at + HEADS_EVERY - time.monotonic()))
            async with self.lock:
                if not self.dirty.is_set():
                    continue
                if not self.full:
                    self.dirty.clear()
                    continue
                try:
                    got = await self.heads()
                except Exception:  # noqa: BLE001 — an agent that could not answer: try again next time
                    self.dirty.set()
                    continue
                key = json.dumps(got, sort_keys=True)
                text = json.dumps({"event": "groups", **got})
                for s in self.full:
                    if s.heads_key != key:
                        s.heads_key = key
                        s.put(text)

    async def main(self) -> None:
        error: str | None = None
        try:
            async with self._open() as c:
                self.state = await self._seed()
                flusher = asyncio.ensure_future(self._flush())
                try:
                    async for ev in c.subscribe():
                        async with self.lock:
                            await self._step(self, ev)
                finally:
                    flusher.cancel()
                    await asyncio.gather(flusher, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except (AgentUnavailable, ConnectionError):
            pass
        except Exception:  # noqa: BLE001 — every page is told, and reconnects
            log.warning("the events stream failed", exc_info=True)
            error = FAILED
        finally:
            for s in self.streams:
                s.end(error)


class Fanout:
    """The UI process's one subscription, run while any page's stream is connected."""

    def __init__(
        self,
        open_client: Callable[[], Any],
        seed: Callable[[], Awaitable[Any]],
        step: Step,
        regroup: Callable[[Any], Awaitable[dict[str, Any]]],
    ) -> None:
        self._parts = (open_client, seed, step, regroup)
        self.run: Run | None = None

    def join(self, s: Stream) -> None:
        run = self.run
        if run is None or run.task is None or run.task.done():
            run = self.run = Run(*self._parts)
            run.streams.append(s)
            run.task = asyncio.ensure_future(self._main(run))
        else:
            run.streams.append(s)

    async def _main(self, run: Run) -> None:
        try:
            await run.main()
        finally:
            if self.run is run:
                self.run = None

    def leave(self, s: Stream) -> None:
        run = self.run
        if run is None or s not in run.streams:
            return
        run.streams.remove(s)
        if not run.streams:
            self.run = None
            if run.task is not None:
                run.task.cancel()
