"""Where a page's time goes (design §4.5 *Page loads*, *Measured on every load*; TD-881): each page route
answers a `Server-Timing` header — each RPC by name, the person inbox, the board and ledger reads, the
render, the total — and the last `KEPT` per route are kept here, in memory, never on disk.

A request's steps live in a context variable the page middleware sets (`begin`), so every `step` the
request runs — on the loop or on a worker thread `asyncio.to_thread` started, which copies the context —
adds to its own request's figures, and one outside any page request (the counts keeper, the events
stream) adds to nothing."""

from __future__ import annotations

import functools
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

KEPT = 20  # the last loads kept per route
# The page routes, each with the key its loads are kept under (§4.5 *Page loads*): a fragment (`part=1`)
# is kept apart, so a page's poll does not push its loads out of the twenty.
PAGE_ROUTES = (
    (re.compile(r"/"), "/"),
    (re.compile(r"/inbox"), "/inbox"),
    (re.compile(r"/queue"), "/queue"),
    (re.compile(r"/settings"), "/settings"),
    (re.compile(r"/spend"), "/spend"),
    (re.compile(r"/repo/[^/]+"), "/repo/{name}"),
    (re.compile(r"/transcript/[^/]+"), "/transcript/{sid}"),
)

_STEPS: ContextVar[dict[str, Any] | None] = ContextVar("server_timing", default=None)
RECENT: dict[str, deque[dict[str, float]]] = {}


def route_key(path: str, part: bool = False) -> str | None:
    """The key a page route's loads are kept under, or None for a path that is no page."""
    for pattern, key in PAGE_ROUTES:
        if pattern.fullmatch(path):
            return f"{key}?part=1" if part else key
    return None


def begin() -> dict[str, Any]:
    """A request's figures, set for everything it runs: `{"ms": {name: ms}, "open": set()}`."""
    steps: dict[str, Any] = {"ms": {}, "open": set()}
    _STEPS.set(steps)
    return steps


@contextmanager
def step(name: str, nests: bool = True) -> Iterator[None]:
    """Time the block under `name`, summed per name. A step that `nests` and runs inside another of its
    name (the board read inside the state rows' own) is counted once, by the outer; an RPC does not nest,
    so two of one name gathered at once are both counted."""
    steps = _STEPS.get()
    if steps is None or (nests and name in steps["open"]):
        yield
        return
    if nests:
        steps["open"].add(name)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        if nests:
            steps["open"].discard(name)
        steps["ms"][name] = steps["ms"].get(name, 0.0) + (time.perf_counter() - t0) * 1000


def timed(name: str) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """An async reading timed as the step `name` (`step`)."""

    def wrap(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def run(*a: Any, **k: Any) -> Any:
            with step(name):
                return await fn(*a, **k)

        return run

    return wrap


def finish(steps: dict[str, Any], key: str, total_ms: float) -> str:
    """The request's `Server-Timing` value, its steps in the order first run and `total` last; the load
    kept under `key`, the oldest past `KEPT` dropped."""
    got = {**steps["ms"], "total": total_ms}
    RECENT.setdefault(key, deque(maxlen=KEPT)).append({k: round(v, 1) for k, v in got.items()})
    return ", ".join(f"{name};dur={ms:.1f}" for name, ms in got.items())
