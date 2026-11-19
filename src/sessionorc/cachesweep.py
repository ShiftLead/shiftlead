"""The disk sweep's cache rule (design §4.6 *The disk sweep*, *caches*, TD-1945).

A tree under agent-cadence's `~/.cache/agent-cadence/trees/<commit>/` that is the pin of no registered repo's
`origin` default branch and whose newest write (its fetch) is older than `cache_keep_days` goes, only on a host
agent whose `SHIFTLEAD_HOME` is the default path, so a scratch home with no roster never takes a live repo's pin.
The removal holds agent-cadence's cache lock (`~/.cache/agent-cadence/lock`), renames the tree aside under a
`.tmp-` name (which the launcher itself clears under that lock, should a removal die midway), makes it writable
(trees are made read-only) and removes it. A tree is fetched again when next wanted: its removal costs time, never
work. A repo's own precheck cache is never this rule's.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import re
import shutil
import time
from collections.abc import Iterable
from pathlib import Path

from sessionorc import gitinfo, paths

log = logging.getLogger(__name__)

COMMIT = re.compile(r"[0-9a-f]{40}")
PIN_FILE = "docs/cadence.toml"
GIT_STEP = 20.0


def cache_dir() -> Path:
    """agent-cadence's cache, as its launcher finds it: `${XDG_CACHE_HOME:-~/.cache}/agent-cadence`."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "agent-cadence"


def default_home() -> bool:
    """Whether this host agent's `SHIFTLEAD_HOME` is the default path (a symlink to it is), the one home whose
    sweep takes caches and worktrees (§4.6)."""
    try:
        return paths.home().resolve() == paths.DEFAULT_HOME.expanduser().resolve()
    except OSError:
        return False


def pin_of(root: str | Path) -> tuple[bool, str | None]:
    """(read, ref): the `[agent-cadence]` `ref` that `docs/cadence.toml` names on the repo's `origin/<default>`.
    `(True, None)` where that commit has no such file, or no pin in it; `(False, None)` where it cannot be read
    — no `origin/<default>`, a failed read, a file that does not parse — so the pass removes nothing."""
    base = f"origin/{gitinfo.default_branch(root, GIT_STEP)}"
    if gitinfo._git(root, "rev-parse", "--verify", "-q", f"{base}^{{commit}}", timeout=GIT_STEP) is None:
        return False, None
    spec = f"{base}:{PIN_FILE}"
    has = gitinfo._git_rc(root, "cat-file", "-e", spec, timeout=GIT_STEP)
    if has is None:
        return False, None
    if has != 0:
        return True, None
    text = gitinfo._git(root, "show", spec, timeout=GIT_STEP)
    if text is None:
        return False, None
    try:
        import tomllib

        table = tomllib.loads(text).get("agent-cadence")
    except (ImportError, ValueError):
        return False, None
    ref = table.get("ref") if isinstance(table, dict) else None
    return True, (ref if isinstance(ref, str) and COMMIT.fullmatch(ref) else None)


def pins(roots: Iterable[str | Path]) -> set[str] | None:
    """Every registered repo's pin on its `origin` default branch, or None where any cannot be read."""
    out: set[str] = set()
    for root in roots:
        ok, ref = pin_of(root)
        if not ok:
            log.warning("cache sweep: the pin of %s cannot be read, so no tree is removed this pass", root)
            return None
        if ref:
            out.add(ref)
    return out


def _newest_write(path: Path) -> float:
    """The newest modification time under `path`, itself included, never following a symlink; an entry that
    cannot be read counts as written now."""
    newest = path.lstat().st_mtime
    for d, dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in dirs + files:
            try:
                newest = max(newest, os.lstat(os.path.join(d, name)).st_mtime)
            except FileNotFoundError:
                continue
            except OSError:
                return time.time()
    return newest


def _writable(path: Path) -> None:
    """Give back write permission on every directory under `path` (trees are read-only), never through a link."""
    os.chmod(path, 0o755)
    for d, dirs, _files in os.walk(path):  # os.walk never descends a symlink
        for name in dirs:
            p = os.path.join(d, name)
            if not os.path.islink(p):
                with contextlib.suppress(OSError):
                    os.chmod(p, 0o755)


def sweep_trees(pinned: set[str], keep_days: float, now_s: float, cache: Path | None = None) -> list[str]:
    """Remove the trees no pin in `pinned` names whose newest write is older than `keep_days`, under the cache's
    lock taken without waiting (busy: none this pass). Returns the removed trees' paths."""
    cache = cache or cache_dir()
    trees = cache / "trees"
    removed: list[str] = []
    if keep_days <= 0 or not trees.is_dir():
        return removed
    with open(cache / "lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.info("cache sweep: agent-cadence's cache lock is held, so no tree is removed this pass")
            return removed
        try:
            for e in sorted(os.scandir(trees), key=lambda e: e.name):
                if not COMMIT.fullmatch(e.name) or e.name in pinned:
                    continue
                if e.is_symlink() or not e.is_dir(follow_symlinks=False):
                    continue
                tree = Path(e.path)
                try:
                    if now_s - _newest_write(tree) < keep_days * 86400:
                        continue
                    aside = trees / f".tmp-sweep-{e.name}-{os.getpid()}"
                    os.rename(tree, aside)
                    _writable(aside)
                    shutil.rmtree(aside, ignore_errors=True)
                    removed.append(str(tree))
                    log.info("removed agent-cadence tree %s (no registered repo pins it)", tree)
                except OSError as err:
                    log.warning("could not remove agent-cadence tree %s: %s", tree, err)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return removed
