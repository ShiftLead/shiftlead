"""The disk sweep's pass result (design §4.6 *The sweep's reading*, TD-1945): per kind (scratch, worktrees, runs,
caches, home files) the bytes held, each item's size as last measured and kept in the host agent's memory so a walk
stays inside its pass's bounds, the total *partial* until every listed item has been measured (after a host-agent
restart, the memory is empty); the bytes the pass removed; and each item it kept that a rule would otherwise take,
with why. Each pass writes it to `disk.json` in the host's home with the free space under `scratch_root` and a dated
line per pass kept 30 days, from which the reading's 30-day totals are read (TD-1946, `write` and `read`)."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc.store import _atomic_write

KINDS = ("scratch", "worktrees", "runs", "caches", "home")
WALK_S = 10.0  # one item's size walk at most, so a huge tree never spends a pass's budget (TD-1945 review)
FILE = "disk.json"  # in the host's home (`SHIFTLEAD_HOME`)
BRANCH_ROWS = 200  # `branches.kept` holds at most this many rows, `kept_more` the count past them
KEEP_DAYS = 30  # a pass's dated line is kept this long; the reading's `removed_30d` sums them
LOW = 0.1  # under a tenth free, of bytes or of inodes, is drawn as a warning (§4.6 *The sweep's reading*)
MOUNTINFO = "/proc/self/mountinfo"
_WRITE = threading.Lock()  # the hourly pass and a reclaim each rewrite `disk.json` (§4.6 *The pressure pass*)


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
        self.gone_paths: dict[str, int] = {}  # each removed path (a dry run's: each it would remove) and its bytes
        self.kept: list[tuple[str, str]] = []
        self.held_gone = 0  # the removed bytes that were among those held (a dry run reads them back as held)
        self.unlisted = False  # the rule could not list its items this pass: the last reading stands, *partial*
        self.seat: dict[str, dict[str, Any]] | None = None  # scratch's: each live seat's inodes (TD-2133)

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
        if p in self.gone_paths:  # a dry run's second rule over a path it already counted: once
            return
        if size is None:
            size = self.measured.get(p, self._known.get(p, 0))
        if p in self.listed:
            self.held_gone += size
        self.removed += size
        self.gone_paths[p] = size
        self.listed.discard(p)
        self.measured.pop(p, None)

    def keep(self, path: str | Path, why: str) -> None:
        self.kept.append((str(path), why))


class Book:
    """The sizes the sweep has measured, by kind, across passes; in memory alone, so a restart starts it empty."""

    def __init__(self) -> None:
        self.sizes: dict[str, dict[str, int]] = {k: {} for k in KINDS}

    def copy(self) -> Book:
        """A book of the same sizes that a dry run folds into and then drops, so the pass's own memory stays."""
        other = Book()
        other.sizes = {k: dict(v) for k, v in self.sizes.items()}
        return other

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

    def dry(self, tallies: dict[str, Tally]) -> dict[str, Any]:
        """A dry run's result (§4.6 *The sweep's reading*): `close`'s per kind, `removed` read as the bytes it would
        remove, `held` the bytes held now (what it would remove among them), and `would_remove`, each path it would
        remove with its bytes."""
        out = self.close(tallies)
        for kind in KINDS:
            t = tallies.get(kind)
            out[kind]["held"] += t.held_gone if t else 0
            out[kind]["would_remove"] = [
                {"path": p, "bytes": s} for p, s in sorted((t.gone_paths if t else {}).items())
            ]
        return out


def free_space(path: str | Path) -> dict[str, Any]:
    """The free space of the file system that holds `path`, in bytes and in inodes (`os.statvfs`); `error` in
    place of the counts where it cannot be read. A file system that reports no inode count has `inodes_total` 0.
    A `path` not made yet (a fresh host's `scratch_root`) is read at its nearest existing parent."""
    at = Path(path)
    while not at.exists() and at.parent != at:
        at = at.parent
    try:
        st = os.statvfs(at)
    except OSError as e:
        return {"path": str(path), "error": e.strerror or str(e)}
    return {
        "path": str(path),
        "bytes_free": st.f_bavail * st.f_frsize,
        "bytes_total": st.f_blocks * st.f_frsize,
        "inodes_free": st.f_favail,
        "inodes_total": st.f_files,
    }


def fs_type(path: str | Path, mountinfo: str = MOUNTINFO) -> str | None:
    """The file system type of the longest mount point over `path`, the last mounted where two share one; None
    where the table cannot be read (§4.6 *The pressure pass*)."""
    at = os.path.realpath(path)
    best: tuple[int, str] | None = None
    try:
        with open(mountinfo, encoding="utf-8", errors="surrogateescape") as f:
            for line in f:
                left, sep, right = line.partition(" - ")
                fields = left.split()
                if not sep or len(fields) < 5 or not right.split():
                    continue
                point = os.fsdecode(
                    re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m.group(1), 8)]), os.fsencode(fields[4]))
                )
                over = at == point or point == "/" or at.startswith(point.rstrip("/") + "/")
                if over and (best is None or len(point) >= best[0]):
                    best = (len(point), right.split()[0])
    except OSError:
        return None
    return best[1] if best else None


def share_free(path: str | Path, mountinfo: str = MOUNTINFO) -> float | None:
    """The pool's share free, 0 to 1 (§4.6 *The pressure pass*): on a `tmpfs` the lower of its free inodes and free
    bytes, since only there are the bytes the pool's own; elsewhere its free inodes alone. None where there is no
    reading: no inode count on a file system that is not a `tmpfs`, or a `statvfs` that failed."""
    free = free_space(path)
    if "error" in free:
        return None
    shares = []
    if free["inodes_total"]:
        shares.append(free["inodes_free"] / free["inodes_total"])
    if free["bytes_total"] and fs_type(path, mountinfo) == "tmpfs":
        shares.append(free["bytes_free"] / free["bytes_total"])
    return min(shares) if shares else None


def note_pressure(home: str | Path, host: str, removed: int, weak: bool, now: datetime) -> None:
    """One reclaim's dated line in `disk.json`, its bytes under `scratch` (§4.6 *The pressure pass*). A `weak` pass
    (it raised the share free under one point) directly after another is folded into that one's line, with a count."""
    path = Path(home) / FILE
    cutoff = now - timedelta(days=KEEP_DAYS)
    with _WRITE:
        got = _load(path)
        lines = []
        for line in got.get("passes") or []:
            at = _when(line.get("at")) if isinstance(line, dict) else None
            if at is not None and at >= cutoff:
                lines.append(line)
        last = (lines[-1].get("pressure") if lines else None) or {}
        if weak and last.get("weak"):
            kinds = lines[-1].get("removed") or {}
            kinds["scratch"] = int(kinds.get("scratch") or 0) + removed
            lines[-1].update(at=_stamp(now), removed=kinds, pressure={"weak": True, "count": int(last["count"]) + 1})
        else:
            kinds = dict.fromkeys(KINDS, 0)
            kinds["scratch"] = removed
            lines.append({"at": _stamp(now), "removed": kinds, "pressure": {"weak": weak, "count": 1}})
        _atomic_write(path, json.dumps({"host": host, **got, "passes": lines}, indent=1) + "\n")


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


def branch_rows(deleted: int, kept: dict[tuple[str, str], str]) -> dict[str, Any]:
    """The branch rule's part of a pass (§4.6 *The sweep's reading*): its `deleted` count and the kept map as rows, by
    repo then branch, at most `BRANCH_ROWS`, with `kept_more` the count past them."""
    rows = [{"repo": r, "branch": b, "why": kept[(r, b)]} for r, b in sorted(kept)]
    return {"deleted": deleted, "kept": rows[:BRANCH_ROWS], "kept_more": max(0, len(rows) - BRANCH_ROWS)}


def branch_kept(home: str | Path) -> dict[tuple[str, str], str]:
    """The kept rows `disk.json` holds, as the map the host agent seeds at its first pass."""
    got = _load(Path(home) / FILE).get("branches")
    rows = got.get("kept") if isinstance(got, dict) else None
    return {
        (str(x["repo"]), str(x["branch"])): str(x.get("why") or "")
        for x in rows or []
        if isinstance(x, dict) and x.get("repo") and x.get("branch")
    }


def _branches_30d(lines: list[Any], cutoff: datetime) -> int:
    total = 0
    for line in lines:
        at = _when(line.get("at")) if isinstance(line, dict) else None
        if at is None or at < cutoff:
            continue
        try:
            total += int(line.get("branches_deleted") or 0)
        except (TypeError, ValueError):
            continue
    return total


def write(
    home: str | Path,
    host: str,
    result: dict[str, Any],
    free: dict[str, Any],
    started: str,
    now: datetime,
    seat_free: dict[str, Any] | None = None,
    branches: dict[str, Any] | None = None,
    seats: dict[str, dict[str, Any]] | None = None,
    seat_spells: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write one pass's `result` (`Book.close`'s) to `disk.json` in `home`: the pass's kinds, `free`, `seat_free`
    where the host sets a `seat_root` (TD-2082), the host agent's `started` (a reading by a later run says *partial*,
    its memory being empty), the branch rule's `branches` (`branch_rows`; None: no delete, the file's rows stand), and
    the dated lines of the passes in the last `KEEP_DAYS`, this one's appended. `seats` (`tally.seat`, None where the
    pass walked no seat) puts each live seat's inodes on this pass's line, and `seat_spells` (`scratch.seat_step`'s;
    None: as the file holds them) the seats' spells (§4.6 *A seat is told instead*, TD-2133). Through a temporary
    file and one rename; returns what it wrote."""
    path = Path(home) / FILE
    cutoff = now - timedelta(days=KEEP_DAYS)
    with _WRITE:
        lines = []
        for line in _load(path).get("passes") or []:
            at = _when(line.get("at")) if isinstance(line, dict) else None
            if at is not None and at >= cutoff:
                lines.append(line)
        if branches is None:
            old = _load(path).get("branches")
            old = old if isinstance(old, dict) else {}
            branches = {"deleted": 0, "kept": old.get("kept") or [], "kept_more": int(old.get("kept_more") or 0)}
        line: dict[str, Any] = {
            "at": _stamp(now),
            "removed": {k: int((result.get(k) or {}).get("removed") or 0) for k in KINDS},
            "branches_deleted": int(branches.get("deleted") or 0),
        }
        if seats is not None:  # what the week's check reads (TD-2134)
            line["seats"] = {
                r: int(one.get("inodes") or 0) for r, one in sorted(seats.items()) if not one.get("skipped")
            }
        lines.append(line)
        branches = {**branches, "deleted_30d": _branches_30d(lines, cutoff)}
        out = {
            "host": host,
            "at": _stamp(now),
            "started": started,
            "kinds": result,
            "branches": branches,
            "free": free,
            "passes": lines,
        }
        if seat_free is not None:
            out["seat_free"] = seat_free
        kept = _load(path)
        if isinstance(low := kept.get("low"), dict):  # each pool's *low* state outlives a pass (TD-2083)
            out["low"] = low
        if isinstance(memory := kept.get("memory"), dict):  # and each memory half's (TD-2136)
            out["memory"] = memory
        if isinstance(left := kept.get("left_behind"), dict):  # and the left-behind spell (TD-2137)
            out["left_behind"] = left
        if seat_spells is None and isinstance(kept.get("seats_over"), dict):
            seat_spells = kept["seats_over"]  # and each seat's spell (TD-2133), written by the hourly pass alone
        if seat_spells:
            out["seats_over"] = seat_spells
        _atomic_write(path, json.dumps(out, indent=1) + "\n")
    return out


def seat_state(home: str | Path) -> dict[str, dict[str, Any]]:
    """Each seat's spell in `disk.json` (§4.6 *A seat is told instead*, TD-2133), by record, an odd entry dropped."""
    got = _load(Path(home) / FILE).get("seats_over")
    return {str(k): v for k, v in got.items() if isinstance(v, dict)} if isinstance(got, dict) else {}


def low_state(home: str | Path) -> dict[str, dict[str, Any]]:
    """Each pool's *low* state in `disk.json` (§4.6 *Told before the pool is full*), an odd entry dropped."""
    got = _load(Path(home) / FILE).get("low")
    return {str(k): v for k, v in got.items() if isinstance(v, dict)} if isinstance(got, dict) else {}


def set_low(home: str | Path, host: str, low: dict[str, dict[str, Any]]) -> None:
    """Write the pools' *low* state into `disk.json`, leaving the rest of the file as it stands."""
    path = Path(home) / FILE
    with _WRITE:
        got = _load(path)
        got.pop("low", None)
        out = {"host": host, **got, **({"low": low} if low else {})}
        _atomic_write(path, json.dumps(out, indent=1) + "\n")


def memory_state(home: str | Path) -> dict[str, dict[str, Any]]:
    """Each memory half's *low* state in `disk.json` (§4.6 *Told when memory runs short*), an odd entry dropped."""
    got = _load(Path(home) / FILE).get("memory")
    return {str(k): v for k, v in got.items() if isinstance(v, dict)} if isinstance(got, dict) else {}


def set_memory(home: str | Path, host: str, memory: dict[str, dict[str, Any]]) -> None:
    """Write the memory halves' *low* state into `disk.json`, leaving the rest of the file as it stands."""
    path = Path(home) / FILE
    with _WRITE:
        got = _load(path)
        got.pop("memory", None)
        out = {"host": host, **got, **({"memory": memory} if memory else {})}
        _atomic_write(path, json.dumps(out, indent=1) + "\n")


def left_state(home: str | Path) -> dict[str, Any]:
    """The left-behind spell and the latest `LEFT_EVERY` walk's figures in `disk.json` (§4.6 *Told what finished
    sessions left running*); an odd entry reads as none."""
    got = _load(Path(home) / FILE).get("left_behind")
    return dict(got) if isinstance(got, dict) else {}


def set_left(home: str | Path, host: str, left: dict[str, Any]) -> None:
    """Write the left-behind state into `disk.json`, leaving the rest of the file as it stands."""
    path = Path(home) / FILE
    with _WRITE:
        got = _load(path)
        got.pop("left_behind", None)
        out = {"host": host, **got, **({"left_behind": left} if left else {})}
        _atomic_write(path, json.dumps(out, indent=1) + "\n")


def left_spells(old: dict[str, Any], answers: dict[str, Any], now: str) -> dict[str, dict[str, Any]]:
    """The home's `left_behind` spells after one round of `disk` answers (§4.6 *Told what finished sessions left
    running*), keyed by host: begun by the first answer whose `left_behind` has `since` set and ended by the first
    where it is not, holding the latest processes, bytes, `cut`, the walk's time and the three largest trees. A host
    whose answer is an error or lacks `left_behind` (an older build) keeps its spell as it stands; a host no longer
    asked has none."""
    out: dict[str, dict[str, Any]] = {}
    for host, answer in answers.items():
        left = answer.get("left_behind") if isinstance(answer, dict) and "error" not in answer else None
        if not isinstance(left, dict):
            if isinstance(was := old.get(str(host)), dict):
                out[str(host)] = was
            continue
        if not left.get("since"):
            continue
        was = old.get(str(host)) if isinstance(old.get(str(host)), dict) else {}
        trees = [t for t in left.get("trees") or [] if isinstance(t, dict)]
        out[str(host)] = {
            "host": str(host),
            "since": str(was.get("since") or now),
            "at": left.get("at"),
            "processes": int(left.get("processes") or 0),
            "bytes": int(left.get("bytes") or 0),
            "cut": bool(left.get("cut")),
            "largest": [{"name": t.get("name"), "bytes": t.get("bytes")} for t in trees[:3]],
        }
    return out


def memory_spells(old: dict[str, Any], answers: dict[str, Any], now: str) -> dict[str, dict[str, Any]]:
    """The home's `memory_low` spells after one round of `disk` answers (§4.6 *Told what finished sessions left
    running*), keyed `<host>:<half>`: begun by the first answer whose half has `low` true and ended by the first where
    it is false or the half is absent, holding the latest share free, holders and `cut`. A host whose answer is an
    error or lacks `memory` (an older build, no memory reading) keeps its spells as they stand; a host no longer asked
    has none."""
    out: dict[str, dict[str, Any]] = {}
    for host, answer in answers.items():
        memory = answer.get("memory") if isinstance(answer, dict) and "error" not in answer else None
        if not isinstance(memory, dict):
            out.update({k: v for k, v in old.items() if isinstance(v, dict) and v.get("host") == host})
            continue
        for half, one in memory.items():
            if not isinstance(one, dict) or not one.get("low"):
                continue
            key = f"{host}:{half}"
            was = old.get(key) if isinstance(old.get(key), dict) else {}
            share = one.get("share_free")
            out[key] = {
                "host": str(host),
                "half": str(half),
                "since": str(was.get("since") or now),
                "share_free": share if isinstance(share, int | float) else was.get("share_free"),
                "holders": [h for h in one.get("holders") or [] if isinstance(h, dict)],
                "cut": bool(one.get("cut")),
            }
    return out


def low_spells(old: dict[str, Any], answers: dict[str, Any], now: str) -> dict[str, dict[str, Any]]:
    """The home's `disk_low` spells after one round of `disk` answers (§4.6 *Told before the pool is full*), keyed
    `<host>:<pool>`: begun by the first answer with `pressure` for the pool and ended by the first without it, holding
    the latest share free and holders. A host whose answer is an error keeps its spells as they stand; a host no longer
    asked has none."""
    out: dict[str, dict[str, Any]] = {}
    for host, answer in answers.items():
        if not isinstance(answer, dict) or "error" in answer:
            out.update({k: v for k, v in old.items() if isinstance(v, dict) and v.get("host") == host})
            continue
        pressure = answer.get("pressure")
        for pool, one in (pressure if isinstance(pressure, dict) else {}).items():
            if not isinstance(one, dict):
                continue
            key = f"{host}:{pool}"
            was = old.get(key) if isinstance(old.get(key), dict) else {}
            share = one.get("share_free")
            out[key] = {
                "host": str(host),
                "pool": str(pool),
                "since": str(was.get("since") or now),
                "share_free": share if isinstance(share, int | float) else was.get("share_free"),
                "holders": [h for h in one.get("holders") or [] if isinstance(h, dict)],
            }
    return out


def read(
    home: str | Path,
    host: str,
    started: str,
    now: datetime,
    free: dict[str, Any],
    seat_free: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The reading `ao disk` prints for this host (§4.6 *The sweep's reading*): `disk.json`'s last pass, each kind's
    `removed_30d` summed over the dated lines inside `KEEP_DAYS` of `now`, every kind *partial* where the file was
    written by an earlier run of the host agent than `started`, `free` as read now, and `warnings` from it; with a
    `seat_root`, `seat_free` as read now and `seat_warnings` from it (TD-2082). Before any pass, `at` is None and
    every kind holds nothing and is *partial*."""
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
    raw = got.get("branches")
    raw = raw if isinstance(raw, dict) else {}
    branches = {
        "deleted": int(raw.get("deleted") or 0),
        "deleted_30d": _branches_30d(got.get("passes") or [], cutoff),
        "kept": [x for x in raw.get("kept") or [] if isinstance(x, dict)],
        "kept_more": int(raw.get("kept_more") or 0),
    }
    out = {
        "host": host,
        "at": got.get("at"),
        "kinds": kinds,
        "branches": branches,
        "free": free,
        "warnings": warnings(free),
    }
    if seat_free is not None:
        out["seat_free"] = seat_free
        out["seat_warnings"] = warnings(seat_free)
    return out
