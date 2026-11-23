"""The disk sweep's *home files* rule (design §4.6 *The disk sweep*, TD-2105): what the host agent's own home keeps per
session and nothing else expires. Status-line files, start-context files and long-command launch scripts go past
`runs_keep_days` once no record names them; a dead writer's `*.tmp` beside the status-line files goes on age alone.

Only the names below are read. A launch record (`launch/*.json`) is never one of them: a node's member has no record
here, so *no record* cannot be read for it. Each path is weighed by its own modification time and never followed
through a symlink, and just before its removal it is read again, with the records, so a file rewritten or a record
made since keeps it."""

from __future__ import annotations

import logging
import os
import stat
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from sessionorc.diskbook import Tally

log = logging.getLogger(__name__)

DAY = 86400
LIVE_RECORD = "live record"
NOT_REMOVED = "could not be removed"


def _by_id(name: str, records: Iterable[Any]) -> bool:
    return any(r.id == name for r in records)


def _by_conversation(name: str, records: Iterable[Any]) -> bool:
    return any(r.adapter_id == name for r in records)


def _by_context(name: str, records: Iterable[Any]) -> bool:
    return any(name in (r.adapter_id, r.context_id) for r in records)


# (directory under the home, the name's suffix, whether a record holds it, whether a `*.tmp` beside it is the writer's)
_RULES: tuple[tuple[str, str, Callable[[str, Iterable[Any]], bool], bool], ...] = (
    ("statusline", ".json", _by_id, True),
    ("statusline/context", ".json", _by_conversation, True),
    ("launch", ".context.md", _by_context, False),
    ("launch", ".sh", _by_id, False),
)


def _file_stat(path: str) -> os.stat_result | None:
    """`path`'s own `lstat`, for a file or a link; None for a directory, anything else, or a path gone."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return st if stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode) else None


def _names(directory: Path) -> list[str]:
    try:
        with os.scandir(directory) as entries:
            return sorted(e.name for e in entries)
    except OSError:
        return []


def _forget(tally: Tally, path: str) -> None:
    """A path that went by another hand: held no more, and removed by nobody this pass counts."""
    tally.listed.discard(path)
    tally.measured.pop(path, None)


def _remove(
    path: str,
    cutoff: float,
    held: Callable[[], bool] | None,
    tally: Tally,
    dry: bool,
) -> None:
    """Remove one path past the age, reading it and the records (`held`, None for a `*.tmp`) once more first."""
    st = _file_stat(path)
    if st is None:
        _forget(tally, path)
        return
    if st.st_mtime >= cutoff:
        return  # rewritten since the weigh
    if held is not None and held():
        tally.keep(path, LIVE_RECORD)
        return
    if not dry:
        try:
            os.unlink(path)
        except FileNotFoundError:
            _forget(tally, path)
            return
        except OSError as e:
            log.warning("home sweep: could not remove %s: %s", path, e)
            tally.keep(path, NOT_REMOVED)
            return
    tally.gone(path, st.st_size)


def sweep(
    home: str | Path,
    keep_days: int,
    now: float,
    records: Callable[[], list[Any]],
    tally: Tally,
    dry: bool = False,
    deadline: float | None = None,
) -> None:
    """One pass over the home's files: every name below is measured into `tally`, and, with `keep_days` above 0, each
    past the age that no record holds is removed (`dry`: counted, and left). `records` gives a list copy of the
    records in any state, read at the weigh and again before each removal. Past `deadline` (monotonic) the kind stops
    and reads *partial*."""
    cutoff = now - keep_days * DAY if keep_days > 0 else None
    root = Path(home)
    seen: set[str] = set()
    weighed = records()
    for sub, suffix, holds, has_tmp in _RULES:
        directory = root / sub
        for name in _names(directory):
            if deadline is not None and time.monotonic() > deadline:
                tally.unlisted = True
                return
            path = str(directory / name)
            is_tmp = has_tmp and name.endswith(".tmp")
            if path in seen or not (is_tmp or name.endswith(suffix)):
                continue
            stem = name[: -len(suffix)] if not is_tmp else ""
            if not is_tmp and not stem:
                continue
            st = _file_stat(path)
            if st is None:
                continue
            seen.add(path)
            tally.measure(path, st.st_size)
            if cutoff is None or st.st_mtime >= cutoff:
                continue
            if is_tmp:
                _remove(path, cutoff, None, tally, dry)
            elif holds(stem, weighed):
                tally.keep(path, LIVE_RECORD)
            else:
                _remove(path, cutoff, lambda s=stem, h=holds: h(s, records()), tally, dry)
