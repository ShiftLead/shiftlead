"""The disk sweep's pass result (design §4.6 *The sweep's reading*, TD-1945): per kind (scratch, worktrees, runs,
caches) the bytes held, each item's size as last measured and kept in the host agent's memory so a walk stays inside
its pass's bounds, the total *partial* until every listed item has been measured (after a host-agent restart, the
memory is empty); the bytes the pass removed; and each item it kept that a rule would otherwise take, with why.
TD-1946 writes it to `disk.json` and reads it back."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

KINDS = ("scratch", "worktrees", "runs", "caches")
WALK_S = 10.0  # one item's size walk at most, so a huge tree never spends a pass's budget (TD-1945 review)


def deadline() -> float:
    """The monotonic time one item's size walk stops at."""
    return time.monotonic() + WALK_S


def size_of(path: str | Path, deadline: float | None = None) -> int | None:
    """The bytes under `path`, itself included, by each entry's own `lstat` size: a symlink counts as the link and
    is never followed, an entry gone meanwhile or unreadable counts nothing. None past `deadline` (monotonic)."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    total = st.st_size
    if not os.path.isdir(path) or os.path.islink(path):
        return total
    todo = [str(path)]
    while todo:
        if deadline is not None and time.monotonic() > deadline:
            return None
        try:
            entries = list(os.scandir(todo.pop()))
        except OSError:
            continue
        for e in entries:
            try:
                total += e.stat(follow_symlinks=False).st_size
                if e.is_dir(follow_symlinks=False):
                    todo.append(e.path)
            except OSError:
                continue
    return total


class Tally:
    """One kind's book for one pass: what it listed, measured, removed and kept. `known` is the kind's sizes from
    earlier passes, read only."""

    def __init__(self, known: dict[str, int] | None = None) -> None:
        self._known = known or {}
        self.listed: set[str] = set()
        self.measured: dict[str, int] = {}
        self.removed = 0
        self.gone_paths: set[str] = set()
        self.kept: list[tuple[str, str]] = []
        self.unlisted = False  # the rule could not list its items this pass: the last reading stands, *partial*

    def list(self, path: str | Path) -> None:
        self.listed.add(str(path))

    def known(self, path: str | Path) -> bool:
        return str(path) in self.measured or str(path) in self._known

    def measure(self, path: str | Path, size: int | None = None, deadline: float | None = None) -> int | None:
        """Record `path`'s size (`size`, else walked now), listing it; None where it could not be measured."""
        p = str(path)
        self.listed.add(p)
        if size is None:
            size = size_of(p, deadline)
        if size is not None:
            self.measured[p] = size
        return size

    def gone(self, path: str | Path, size: int | None = None) -> None:
        """`path` was removed: its bytes (`size`, else as last measured) count as removed, and it is held no more."""
        p = str(path)
        if size is None:
            size = self.measured.get(p, self._known.get(p, 0))
        self.removed += size
        self.gone_paths.add(p)
        self.listed.discard(p)
        self.measured.pop(p, None)

    def keep(self, path: str | Path, why: str) -> None:
        self.kept.append((str(path), why))


class Book:
    """The sizes the sweep has measured, by kind, across passes; in memory alone, so a restart starts it empty."""

    def __init__(self) -> None:
        self.sizes: dict[str, dict[str, int]] = {k: {} for k in KINDS}

    def tallies(self) -> dict[str, Tally]:
        return {k: Tally(self.sizes[k]) for k in KINDS}

    def close(self, tallies: dict[str, Tally]) -> dict[str, Any]:
        """Fold one pass's tallies into the memory and return the pass result: per kind `held` (bytes), `partial`,
        `removed` (bytes) and `kept` (`{"path", "why"}` each)."""
        out: dict[str, Any] = {}
        for kind in KINDS:
            t = tallies.get(kind) or Tally(self.sizes[kind])
            old = self.sizes[kind]
            if t.unlisted:
                known = {p: s for p, s in {**old, **t.measured}.items() if p not in t.gone_paths}
                partial = True
            else:
                known = {p: s for p, s in {**old, **t.measured}.items() if p in t.listed}
                partial = any(p not in known for p in t.listed)
            self.sizes[kind] = known
            out[kind] = {
                "held": sum(known.values()),
                "partial": partial,
                "removed": t.removed,
                "kept": [{"path": p, "why": w} for p, w in t.kept],
            }
        return out
