"""The disk sweep's *tool temp* rule (design §4.6, TD-2106): what runs outside a run's scratch leave in the machine's
shared temp space. Build leftovers in `/tmp` go after a quiet day, and an entry under a tool's temp root after three
quiet days, once nothing live can be using it. The caller hands in every root and reader, so a test never reads the
real `/tmp` and this module imports no `Agent`."""

from __future__ import annotations

import logging
import os
import stat
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sessionorc import diskbook, scratch

log = logging.getLogger(__name__)

TOOL_TEMP_QUIET_S = 3 * 86_400  # the age agent-cadence's reaper gives a Claude Code session folder
TOOL_TEMP_BUDGET_S = 60.0  # a real pass's time here; the next hour's pass takes the rest
MAX_KEPT = 20  # kept paths a pass names
_YOUNG = "young"  # written within the age: not a keep the reading names


@dataclass
class _Seen:
    """One read of what is live: the entry names held, and per adapter its oldest outside session's start."""

    names: set[str] | None = None  # None: a `temp_entry` failed, so every entry is kept
    oldest: dict[str, float] = field(default_factory=dict)
    no_start: set[str] = field(default_factory=set)  # adapters with an outside session of no start time


def _read(
    externals: Callable[[], dict[str, Any]],
    tool_ids: Callable[[], set[str]],
    live_cwds: Callable[[], Iterable[str]],
    namers: list[Callable[[Path], str | None]],
) -> _Seen:
    got = externals()
    ours = tool_ids()
    seen = _Seen()
    cwds = list(live_cwds())
    for ext in got["items"]:
        cwds.append(ext.cwd)
        if ext.tool_id and ext.tool_id in ours:
            continue  # a managed session's start never extends the age
        if ext.started is None:
            seen.no_start.add(ext.adapter)
        else:
            seen.oldest[ext.adapter] = min(ext.started, seen.oldest.get(ext.adapter, ext.started))
    names: set[str] = set()
    try:
        for cwd in cwds:
            for path in (Path(cwd), Path(cwd).resolve()):
                for namer in namers:
                    name = namer(path)
                    if name:
                        names.add(name)
    except Exception:  # noqa: BLE001 — a name that cannot be read could be any entry's
        log.exception("tool temp: a session's temp entry could not be named")
        return seen
    seen.names = names
    return seen


def _entries(root: Path, tally: Any, owned: bool) -> list[os.DirEntry[str]]:
    """The entries directly under `root`. `owned` holds it to a real directory of this uid, since `/tmp` is
    world-writable and a link planted at its name would aim the rule elsewhere. An absent root holds nothing; any
    other refusal sets `unlisted`."""
    try:
        if owned:
            st = root.lstat()
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
                tally.unlisted = True
                return []
        with os.scandir(root) as it:
            return sorted(it, key=lambda e: e.name)
    except FileNotFoundError:
        return []
    except OSError:
        tally.unlisted = True
        return []


def _candidate(e: os.DirEntry[str]) -> bool | None:
    """True for a real directory of this uid, False for a regular file of it, None for anything else."""
    try:
        st = e.stat(follow_symlinks=False)
    except OSError:
        return None
    if st.st_uid != os.getuid():
        return None
    if stat.S_ISDIR(st.st_mode):
        return True
    return False if stat.S_ISREG(st.st_mode) else None


def _quiet(path: Path, is_dir: bool, now: float, age: float) -> bool:
    """Nothing written for `age`, by the newer of the modification and change times."""
    if is_dir:
        return scratch._quiet(path, now, age, changed=True)
    try:
        st = path.lstat()
    except OSError:
        return False
    return max(scratch._written_at(st.st_mtime, now), st.st_ctime) <= now - age


def sweep(
    tmp: Path,
    tools: list[tuple[str, Path]],
    transcripts: list[Path],
    tally: Any,
    *,
    now: float,
    idle: Callable[[Path], str | None],
    externals: Callable[[], dict[str, Any]],
    tool_ids: Callable[[], set[str]],
    live_cwds: Callable[[], Iterable[str]],
    namers: list[Callable[[Path], str | None]],
    dry: bool = False,
    deadline: float | None = None,
) -> None:
    """One pass of *tool temp* (§4.6): `tmp`'s build leftovers, then each `(adapter, root)` of `tools`. What goes is
    counted by `tally.gone` and adds nothing to what the kind holds. Past `deadline` (monotonic) it stops, the tally
    *partial*; a real pass also stops past `TOOL_TEMP_BUDGET_S`, and the next pass takes the rest."""
    budget = None if dry else time.monotonic() + TOOL_TEMP_BUDGET_S
    named = 0

    def over() -> bool:
        t = time.monotonic()
        if deadline is not None and t > deadline:
            tally.unlisted = True
            return True
        return budget is not None and t > budget

    def keep(path: Path, why: str) -> None:
        nonlocal named
        if named < MAX_KEPT:
            tally.keep(path, why)
        named += 1

    def take(path: Path, is_dir: bool) -> None:
        size = diskbook.size_of(path, diskbook.deadline())  # None past it: counted as last measured
        if not dry:
            try:
                if is_dir:
                    scratch._remove(path, floor=path)
                else:
                    path.unlink()
            except OSError as err:
                log.warning("tool temp: could not remove %s: %s", path, err)
                return
            log.info("tool temp removed %s", path)
        tally.gone(path, size)

    def stored(path: Path) -> bool:
        return any(scratch.overlaps(path, t) for t in transcripts)

    def held(path: Path, is_dir: bool, adapter: str, seen: _Seen) -> str | None:
        """Why the entry stays, the tests in the design's order; None where it can go."""
        age = max(TOOL_TEMP_QUIET_S, now - seen.oldest.get(adapter, now))
        if not _quiet(path, is_dir, now, age):
            return _YOUNG
        why = idle(path)
        if why:
            return why
        if seen.names is None:
            return "session names unreadable"
        if path.name in seen.names:
            return "live session"
        if is_dir and scratch.git_work(path, limit=diskbook.deadline()):
            return scratch.GIT_WORK
        return None

    def read() -> _Seen:
        return _read(externals, tool_ids, live_cwds, namers)

    for e in _entries(tmp, tally, owned=False):
        if over():
            return
        if not e.name.startswith(scratch.BUILD_LEFTOVERS) or _candidate(e) is not True:
            continue
        path = Path(e.path)
        if _quiet(path, True, now, scratch.BUILD_QUIET_S):
            if stored(path):
                keep(path, "transcripts")
            else:
                take(path, True)

    for adapter, root in tools:
        entries = _entries(root, tally, owned=True)
        if not entries:
            continue
        seen = read()
        for e in entries:
            if over():
                return
            if adapter in seen.no_start:
                log.warning("tool temp: an outside %s session has no start time, so %s is kept", adapter, root)
                break
            is_dir = _candidate(e)
            if is_dir is None:
                continue
            path = Path(e.path)
            why = held(path, is_dir, adapter, seen)
            if why is None and stored(path):
                why = "transcripts"
            if why is None:  # read again just before the removal
                seen = read()
                if adapter in seen.no_start:
                    continue  # the next turn of the loop says so and stops
                why = held(path, is_dir, adapter, seen)
            if why == _YOUNG:
                continue
            if why:
                keep(path, why)
                continue
            take(path, is_dir)
