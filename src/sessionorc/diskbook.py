"""The disk sweep's pass result (design §4.6 *The sweep's reading*, TD-1945): per kind (scratch, worktrees, runs,
caches) the bytes held, each item's size as last measured and kept in the host agent's memory so a walk stays inside
its pass's bounds, the total *partial* until every listed item has been measured (after a host-agent restart, the
memory is empty); the bytes the pass removed; and each item it kept that a rule would otherwise take, with why.
Each pass writes it to `disk.json` in the host's home with the free space under `scratch_root` and a dated line per
pass kept 30 days, from which the reading's 30-day totals are read (TD-1946, `write` and `read`)."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc.store import _atomic_write

KINDS = ("scratch", "worktrees", "runs", "caches")
WALK_S = 10.0  # one item's size walk at most, so a huge tree never spends a pass's budget (TD-1945 review)
FILE = "disk.json"  # in the host's home (`SHIFTLEAD_HOME`)
KEEP_DAYS = 30  # a pass's dated line is kept this long; the reading's `removed_30d` sums them
LOW = 0.1  # under a tenth free, of bytes or of inodes, is drawn as a warning (§4.6 *The sweep's reading*)


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


def free_space(path: str | Path) -> dict[str, Any]:
    """The free space of the file system that holds `path`, in bytes and in inodes (`os.statvfs`); `error` in
    place of the counts where it cannot be read. A file system that reports no inode count has `inodes_total` 0."""
    try:
        st = os.statvfs(path)
    except OSError as e:
        return {"path": str(path), "error": e.strerror or str(e)}
    return {
        "path": str(path),
        "bytes_free": st.f_bavail * st.f_frsize,
        "bytes_total": st.f_blocks * st.f_frsize,
        "inodes_free": st.f_favail,
        "inodes_total": st.f_files,
    }


def warnings(free: dict[str, Any]) -> list[str]:
    """What the reading draws as a warning: under a tenth free of bytes, or of inodes where the file system counts
    them (`inodes_total` 0 draws none)."""
    out = []
    if free.get("bytes_total") and free.get("bytes_free", 0) < LOW * free["bytes_total"]:
        out.append("under a tenth of its bytes free")
    if free.get("inodes_total") and free.get("inodes_free", 0) < LOW * free["inodes_total"]:
        out.append("under a tenth of its inodes free")
    return out


def _stamp(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _when(s: Any) -> datetime | None:
    try:
        return datetime.strptime(str(s), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _load(path: Path) -> dict[str, Any]:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def write(
    home: str | Path, host: str, result: dict[str, Any], free: dict[str, Any], started: str, now: datetime
) -> dict[str, Any]:
    """Write one pass's `result` (`Book.close`'s) to `disk.json` in `home`: the pass's kinds, `free`, the host agent's
    `started` (a reading by a later run says *partial*, its memory being empty), and the dated lines of the passes
    in the last `KEEP_DAYS`, this one's appended. Through a temporary file and one rename; returns what it wrote."""
    path = Path(home) / FILE
    cutoff = now - timedelta(days=KEEP_DAYS)
    lines = []
    for line in _load(path).get("passes") or []:
        at = _when(line.get("at")) if isinstance(line, dict) else None
        if at is not None and at >= cutoff:
            lines.append(line)
    lines.append({"at": _stamp(now), "removed": {k: int((result.get(k) or {}).get("removed") or 0) for k in KINDS}})
    out = {"host": host, "at": _stamp(now), "started": started, "kinds": result, "free": free, "passes": lines}
    _atomic_write(path, json.dumps(out, indent=1) + "\n")
    return out


def read(home: str | Path, host: str, started: str, now: datetime, free: dict[str, Any]) -> dict[str, Any]:
    """The reading `ao disk` prints for this host (§4.6 *The sweep's reading*): `disk.json`'s last pass, each kind's
    `removed_30d` summed over the dated lines inside `KEEP_DAYS` of `now`, every kind *partial* where the file was
    written by an earlier run of the host agent than `started`, `free` as read now, and `warnings` from it. Before
    any pass, `at` is None and every kind holds nothing and is *partial*."""
    got = _load(Path(home) / FILE)
    cutoff = now - timedelta(days=KEEP_DAYS)
    totals = dict.fromkeys(KINDS, 0)
    for line in got.get("passes") or []:
        at = _when(line.get("at")) if isinstance(line, dict) else None
        if at is None or at < cutoff:
            continue
        for k in KINDS:
            try:
                totals[k] += int((line.get("removed") or {}).get(k) or 0)
            except (TypeError, ValueError, AttributeError):
                continue
    stale = got.get("started") != started
    kinds: dict[str, Any] = {}
    for k in KINDS:
        one = (got.get("kinds") or {}).get(k)
        one = one if isinstance(one, dict) else {}
        kinds[k] = {
            "held": int(one.get("held") or 0),
            "partial": bool(one.get("partial", True)) or stale or not got,
            "removed": int(one.get("removed") or 0),
            "removed_30d": totals[k],
            "kept": [x for x in one.get("kept") or [] if isinstance(x, dict)],
        }
    return {"host": host, "at": got.get("at"), "kinds": kinds, "free": free, "warnings": warnings(free)}
