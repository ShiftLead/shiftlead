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

    def __init__(self, ws: Any, light: bool = False, focus: str = "", page: str = "", at: str = "") -> None:
        self.ws, self.light, self.focus = ws, light, focus
        self.page, self.at = page, at  # the `app.js` hash the page loaded and its path, as it says them (TD-694)
        self.heads_key: str | None = None  # the groups this page last got, as their JSON
        self._queue: asyncio.Queue[tuple[str, str | None]] = asyncio.Queue()
        self.ended = False

    def put(self, text: str) -> None:
        if self.ended:
            return
        if self._queue.qsize() >= QUEUE_MAX:
            log.warning("an events stream fell %d messages behind; it is ended to reconnect", QUEUE_MAX)
            self.end()
            return
        self._queue.put_nowait(("send", text))

    def end(self, error: str | None = None) -> None:
        """No more for this page: `pump` sends `error`, when there is one, and returns."""
        if not self.ended:
            self.ended = True
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


# design §4.5 *A reconnect reloads once, never in a loop* (TD-692, TD-694): one client address opening
# `/events` from one path more than `OPENS_LIMIT` times in `OPENS_WINDOW` seconds is a page in a loop,
# warned of at most once per address and path every `OPENS_QUIET` seconds.
OPENS_WINDOW, OPENS_LIMIT, OPENS_QUIET = 60.0, 20, 600.0
SAID_MAX = 100  # `page` and `at` come from the client: each is cut to this many characters


class OpenRate:
    """The `/events` accepts per client address and path over the last minute, and when each pair was last
    warned of. Each accept drops what has aged out of both tables, so they hold only the last minute's
    pairs and the last ten minutes' warnings."""

    def __init__(self) -> None:
        self._opens: dict[tuple[str, str], list[float]] = {}
        self._told: dict[tuple[str, str], float] = {}

    def opened(self, addr: str, at: str, now: float) -> int | None:
        """Count one accept; the count when it is past the limit and a warning is due, else None."""
        for k in list(self._opens):
            if not (kept := [t for t in self._opens[k] if now - t < OPENS_WINDOW]):
                del self._opens[k]
            else:
                self._opens[k] = kept
        for k in [k for k, t in self._told.items() if now - t >= OPENS_QUIET]:
            del self._told[k]
        key = (addr, at)
        self._opens.setdefault(key, []).append(now)
        if len(self._opens[key]) > OPENS_LIMIT and key not in self._told:
            self._told[key] = now
            return len(self._opens[key])
        return None


class Every:
    """At most once per `seconds`: `due(now)` is true the first time and then once the time has passed."""

    def __init__(self, seconds: float) -> None:
        self.seconds, self._last = seconds, None

    def due(self, now: float) -> bool:
        if self._last is not None and now - self._last < self.seconds:
            return False
        self._last = now
        return True


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
    def live(self) -> list[Stream]:
        return [s for s in self.streams if not s.ended]

    @property
    def full(self) -> list[Stream]:
        return [s for s in self.live if not s.light]

    def light(self, *, focus: str | None = None, other: str | None = None) -> list[Stream]:
        """The light streams — those focused on `focus`, or those not focused on `other`."""
        out = [s for s in self.live if s.light]
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
                            try:
                                await self._step(self, ev)
                            except (AgentUnavailable, ConnectionError):
                                raise
                            except Exception:  # noqa: BLE001 — one event that fails to draw costs that event,
                                # never every page: before the fan-out it cost one page its stream
                                log.warning("an event could not be drawn: %s", ev.get("event"), exc_info=True)
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
