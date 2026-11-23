"""The disk sweep's cache rule (design §4.6 *The disk sweep*, *caches*, TD-1945).

A tree under agent-cadence's `~/.cache/agent-cadence/trees/<commit>/` that is the pin of no registered repo's
`origin` default branch and whose newest write (its fetch) is older than `cache_keep_days` goes, only on a host
agent whose `SHIFTLEAD_HOME` is the default path, so a scratch home with no roster never takes a live repo's pin.
The removal holds agent-cadence's cache lock (`~/.cache/agent-cadence/lock`), renames the tree aside under a
`.tmp-` name (which the launcher itself clears under that lock, should a removal die midway), makes it writable
(trees are made read-only) and removes it. A tree is fetched again when next wanted: its removal costs time, never
work. A pin a checkout of a registered repo names (a branch's bump, in its own working tree) is
kept too. A repo's own precheck cache is never this rule's.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import re
import shutil
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from sessionorc import diskbook, gitinfo, paths

log = logging.getLogger(__name__)

COMMIT = re.compile(r"[0-9a-f]{40}")
PIN_FILE = "docs/cadence.toml"
GIT_STEP = 20.0
NODE_ASIDE = re.compile(r"\.tmp-sweep-[0-9a-f]{40}-\d+")


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
    if has != 0:  # absent only where the commit's tree lists no such file; a broken object store is no reading
        listed = gitinfo._git(root, "ls-tree", "--name-only", base, "--", PIN_FILE, timeout=GIT_STEP)
        return (True, None) if listed is not None and not listed.strip() else (False, None)
    return _parse(gitinfo._git(root, "show", spec, timeout=GIT_STEP))


def _parse(text: str | None) -> tuple[bool, str | None]:
    """(read, ref) of a `docs/cadence.toml`'s text, None being no reading."""
    if text is None:
        return False, None
    try:
        import tomllib

        table = tomllib.loads(text).get("agent-cadence")
    except (ImportError, ValueError):
        return False, None
    ref = table.get("ref") if isinstance(table, dict) else None
    return True, (ref if isinstance(ref, str) and COMMIT.fullmatch(ref) else None)


def checkout_pins(root: str | Path) -> tuple[bool, set[str]]:
    """The pins the repo's checkouts name as written in each one's own `docs/cadence.toml` — the main checkout's
    and every worktree's (`git worktree list`), since the launcher runs a branch's own pin — read or not."""
    out = gitinfo._git(root, "worktree", "list", "--porcelain", timeout=GIT_STEP)
    if out is None:
        return False, set()
    found: set[str] = set()
    for line in out.splitlines():
        if not line.startswith("worktree "):
            continue
        f = Path(line.removeprefix("worktree ")) / PIN_FILE
        try:
            text = f.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        except OSError:
            return False, set()
        ok, ref = _parse(text)
        if not ok:
            return False, set()
        if ref:
            found.add(ref)
    return True, found


def pins(roots: Iterable[str | Path]) -> set[str] | None:
    """Every registered repo's pin on its `origin` default branch and in each of its checkouts, or None where
    any cannot be read."""
    out: set[str] = set()
    for root in roots:
        ok, ref = pin_of(root)
        ok2, local = checkout_pins(root)
        if not (ok and ok2):
            log.warning("cache sweep: a pin of %s cannot be read, so no tree is removed this pass", root)
            return None
        out |= local | ({ref} if ref else set())
    return out


def _newest_write(path: Path) -> float:
    """The newest modification time under `path`, itself included, never following a symlink; an entry that
    cannot be read counts as written now."""
    newest = path.lstat().st_mtime
    unread: list[OSError] = []
    for d, dirs, files in os.walk(path, onerror=unread.append):
        for name in dirs + files:
            try:
                newest = max(newest, os.lstat(os.path.join(d, name)).st_mtime)
            except FileNotFoundError:
                continue
            except OSError:
                return time.time()
    return time.time() if unread else newest


def _writable(path: Path) -> None:
    """Give back write permission on every directory under `path` (trees are read-only), never through a link."""
    os.chmod(path, 0o755)
    for d, dirs, _files in os.walk(path):  # os.walk never descends a symlink
        for name in dirs:
            p = os.path.join(d, name)
            if not os.path.islink(p):
                with contextlib.suppress(OSError):
                    os.chmod(p, 0o755)


def tally_trees(
    tally: Any, pinned: set[str] | None = None, keep_days: float = 0, now_s: float = 0, cache: Path | None = None
) -> None:
    """List every tree for the sweep's reading (`tally`, a `diskbook.Tally`), sizing each one nothing has sized
    yet (a tree is named by its commit and never changes); a pinned one older than `keep_days` is kept *pinned*."""
    trees = (cache or cache_dir()) / "trees"
    try:
        entries = sorted(os.scandir(trees), key=lambda e: e.name)
    except FileNotFoundError:
        return  # no trees: none held
    except OSError:
        tally.unlisted = True  # the last reading stands, *partial*
        return
    for e in entries:
        if not COMMIT.fullmatch(e.name) or e.is_symlink() or not e.is_dir(follow_symlinks=False):
            continue
        if not tally.known(e.path):
            tally.measure(e.path, deadline=diskbook.deadline())
        tally.list(e.path)
        if pinned and e.name in pinned and keep_days > 0:
            with contextlib.suppress(OSError):
                if now_s - _newest_write(Path(e.path)) >= keep_days * 86400:
                    tally.keep(e.path, "pinned")


def sweep_trees(
    pinned: set[str],
    keep_days: float,
    now_s: float,
    cache: Path | None = None,
    tally: Any = None,
    dry: bool = False,
    deadline: float | None = None,
) -> list[str]:
    """Remove the trees no pin in `pinned` names whose newest write is older than `keep_days`, under the cache's
    lock taken without waiting (busy: none this pass). Returns the removed trees' paths; `tally` (a
    `diskbook.Tally`) is given every tree, each removed one's bytes counted. `dry` takes no lock and removes
    nothing, returning (and counting as gone) what it would remove, and stops past `deadline` (monotonic), the tally
    *partial* (a dry run's, §4.6 *The sweep's reading*, TD-1946)."""
    cache = cache or cache_dir()
    trees = cache / "trees"
    removed: list[str] = []
    if tally is not None:
        tally_trees(tally, pinned, keep_days, now_s, cache)
    if keep_days <= 0 or not trees.is_dir():
        return removed
    if dry:
        for e in sorted(os.scandir(trees), key=lambda e: e.name):
            if deadline is not None and time.monotonic() > deadline:
                if tally is not None:
                    tally.unlisted = True
                break
            if (
                not COMMIT.fullmatch(e.name)
                or e.name in pinned
                or e.is_symlink()
                or not e.is_dir(follow_symlinks=False)
            ):
                continue
            with contextlib.suppress(OSError):
                if now_s - _newest_write(Path(e.path)) >= keep_days * 86400:
                    removed.append(e.path)
                    if tally is not None:
                        tally.gone(e.path)
        return removed
    with open(cache / "lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.info("cache sweep: agent-cadence's cache lock is held, so no tree is removed this pass")
            return removed
        try:
            for e in os.scandir(trees):  # an aside a pass left half removed: gone first, under the lock
                if e.name.startswith(".tmp-sweep-") and not e.is_symlink():
                    with contextlib.suppress(OSError):
                        _writable(Path(e.path))
                    shutil.rmtree(e.path, ignore_errors=True)
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
                    if aside.exists():
                        log.warning("agent-cadence tree %s was moved aside but not wholly removed", tree)
                        continue
                    removed.append(str(tree))
                    if tally is not None:
                        tally.gone(tree)
                    log.info("removed agent-cadence tree %s (no registered repo pins it)", tree)
                except OSError as err:
                    log.warning("could not remove agent-cadence tree %s: %s", tree, err)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return removed


def node_pins(base: set[str] | None, checkout: str | Path) -> set[str] | None:
    """The commits a node's shipped trees keep: the home's pins and those of the node's devcontainer checkout, None
    where either cannot be read."""
    if base is None:
        return None
    own = pins([checkout])
    return None if own is None else base | own


def sweep_node_trees(
    directory: Path,
    pinned: Callable[[], set[str] | None],
    keep_days: float,
    now_s: float,
    tally: Any = None,
    dry: bool = False,
    deadline: float | None = None,
) -> list[str]:
    """One container node's `cadence/` directory (§4.6 *A node's shipped trees*, TD-2116), holding `<commit>/` directly:
    every tree is listed, and one no pin names past `keep_days` is renamed aside, made writable and removed, `pinned`
    read again just before each rename. No pin read removes none that pass. It takes no lock: only `ship_cadence` and
    this pass write here, and a ship's commit is pinned. A `.ship-*` is never read; an aside a dead pass left goes.
    Returns the removed paths (`dry`: those it would remove, nothing touched)."""
    removed: list[str] = []
    try:
        entries = sorted(os.scandir(directory), key=lambda e: e.name)
    except FileNotFoundError:
        return removed
    except OSError:
        if tally is not None:
            tally.unlisted = True
        return removed
    if keep_days > 0 and not dry:
        for e in entries:
            if NODE_ASIDE.fullmatch(e.name) and not e.is_symlink() and e.is_dir(follow_symlinks=False):
                with contextlib.suppress(OSError):
                    _writable(Path(e.path))
                shutil.rmtree(e.path, ignore_errors=True)
    held = pinned() if keep_days > 0 else None
    for e in entries:
        if not COMMIT.fullmatch(e.name) or e.is_symlink() or not e.is_dir(follow_symlinks=False):
            continue
        if deadline is not None and time.monotonic() > deadline:
            if tally is not None:
                tally.unlisted = True
            break
        if tally is not None:
            if not tally.known(e.path):
                tally.measure(e.path, deadline=diskbook.deadline())
            tally.list(e.path)
        if keep_days <= 0:
            continue
        tree = Path(e.path)
        try:
            if now_s - _newest_write(tree) < keep_days * 86400:
                continue
        except OSError:
            continue
        if held is not None and e.name in held:
            if tally is not None:
                tally.keep(e.path, "pinned")
            continue
        if held is None:
            continue
        if dry:
            removed.append(e.path)
            if tally is not None:
                tally.gone(e.path)
            continue
        held = pinned()  # a pin that moved since keeps its tree
        if held is None:
            continue
        if e.name in held:
            if tally is not None:
                tally.keep(e.path, "pinned")
            continue
        aside = directory / f".tmp-sweep-{e.name}-{os.getpid()}"
        try:
            os.rename(tree, aside)
            _writable(aside)
        except OSError as err:
            log.warning("could not remove node tree %s: %s", tree, err)
            continue
        shutil.rmtree(aside, ignore_errors=True)
        if aside.exists():
            log.warning("node tree %s was moved aside but not wholly removed", tree)
            continue
        removed.append(str(tree))
        if tally is not None:
            tally.gone(tree)
        log.info("removed shipped agent-cadence tree %s (no pin names it)", tree)
    return removed
