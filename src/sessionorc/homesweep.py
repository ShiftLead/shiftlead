"""The disk sweep's *home files* rule (design §4.6 *The disk sweep*, TD-2105): what the host agent's own home keeps per
session and nothing else expires. Status-line files, start-context files and long-command launch scripts go past
`runs_keep_days` once no record names them; a dead writer's `*.tmp` beside the status-line files goes on age alone.

Only the names below are read. A launch record (`launch/*.json`) is never one of them: a node's member has no record
here, so *no record* cannot be read for it. Each path is weighed by its own modification time and never followed
through a symlink, and just before its removal it is read again, with the records, so a file rewritten or a record
made since keeps it.

A board's own tree (`boards/<name>/tree`) goes past the age once no registered repo has that basename, under the board's
edit lock taken without waiting, by `git worktree remove` where its repo still registers it, and as a directory where
that repo or registration is gone. Any other `.git` keeps it."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import stat
import subprocess
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from sessionorc import board as board_mod
from sessionorc import cachesweep, diskbook
from sessionorc.diskbook import Tally
from sessionorc.scratch import overlaps

log = logging.getLogger(__name__)

DAY = 86400
LIVE_RECORD = "live record"
NOT_REMOVED = "could not be removed"
REGISTERED = "registered repo"
BUSY = "busy: a board press"
NOT_BOARD = "not a board tree"
HOLDS_TRANSCRIPTS = "holds a transcript store"


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


def _repo_names(repos: Iterable[tuple[str, Any]]) -> set[str]:
    """The basenames a board tree is keyed by: each registry key's, and each reading's `root`'s."""
    out: set[str] = set()
    for key, reading in repos:
        out.add(Path(key).name)
        if isinstance(reading, dict) and reading.get("root"):
            out.add(Path(str(reading["root"])).name)
    return out


def _real_dir(path: Path) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _removal(tree: Path) -> tuple[str, Path | None]:
    """How a board tree goes, from its `.git` file: `("git", <common>)` where `<common>/worktrees/<x>` registers this
    very tree, `("directory", None)` where that repo or registration no longer exists, `("", None)` for anything
    else."""
    dot_git = tree / ".git"
    try:
        if not stat.S_ISREG(os.lstat(dot_git).st_mode):
            return "", None
        text = dot_git.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "", None
    named = text.removeprefix("gitdir:").strip() if text.startswith("gitdir:") else ""
    if not named:
        return "", None
    admin = Path(os.path.normpath(os.path.join(os.path.realpath(tree), named)))  # `..` from the physical tree
    if admin.parent.name != "worktrees":
        return "", None
    common = admin.parent.parent
    try:
        os.lstat(common)
        os.lstat(admin)
    except (FileNotFoundError, NotADirectoryError):
        return "directory", None
    except OSError:
        return "", None
    try:
        said = (admin / "gitdir").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return "", None
    if not said or os.path.realpath(admin / said) != os.path.realpath(dot_git):
        return "", None
    return "git", common


def _drop_tree(tree: Path, how: str, common: Path | None) -> bool:
    """Remove the tree as `_removal` said; never `worktree prune`, which would act on the repo's other worktrees."""
    if how == "git":
        argv = ["git", f"--git-dir={common}", "worktree", "remove", "--force", str(tree)]
        try:
            cp = subprocess.run(argv, capture_output=True, text=True, timeout=cachesweep.GIT_STEP)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("home sweep: git could not remove %s: %s", tree, e)
            return False
        if cp.returncode != 0:
            log.warning("home sweep: git refused to remove %s: %s", tree, cp.stderr.strip()[:200])
            return False
    else:
        shutil.rmtree(tree, ignore_errors=True)
    return not os.path.lexists(tree)


def _remove_tree(
    tree: Path,
    cutoff: float,
    repos: Callable[[], Iterable[tuple[str, Any]]],
    transcripts: Iterable[Path] | None,
    tally: Tally,
    dry: bool,
) -> None:
    """Remove one unregistered repo's board tree past the age, reading the repos and its age again under the lock."""
    path = str(tree)
    if transcripts is None or any(overlaps(tree, t) for t in transcripts):
        tally.keep(path, HOLDS_TRANSCRIPTS)  # an adapter that names no store could have one here (§9 invariant 16)
        return
    if dry:  # takes no lock, so a tree a press holds counts as one it would remove
        if _removal(tree)[0]:
            tally.gone(path)
        else:
            tally.keep(path, NOT_BOARD)
        return
    if not board_mod._EDIT.acquire(blocking=False):
        tally.keep(path, BUSY)
        return
    try:
        if not _real_dir(tree):
            _forget(tally, path)
            return
        names = _repo_names(repos())
        if tree.parent.name in names:
            tally.keep(path, REGISTERED)
            return
        if not names:
            return
        try:
            if cachesweep._newest_write(tree) >= cutoff:
                return  # written since the weigh
        except OSError:
            return
        how, common = _removal(tree)
        if not how:
            tally.keep(path, NOT_BOARD)
            return
        if not _drop_tree(tree, how, common):
            tally.keep(path, NOT_REMOVED)
            return
        with contextlib.suppress(OSError):
            os.rmdir(tree.parent)  # only if empty
        tally.gone(path)
    finally:
        board_mod._EDIT.release()


def _sweep_boards(
    root: Path,
    cutoff: float | None,
    repos: Callable[[], Iterable[tuple[str, Any]]],
    transcripts: Iterable[Path] | None,
    tally: Tally,
    dry: bool,
    deadline: float | None,
) -> None:
    """Every `boards/<name>/tree` is held by the kind, measured once; one past the age whose name no registered repo
    has goes. A home that registers no repo removes none."""
    boards = root / "boards"
    registered = _repo_names(repos())
    for name in _names(boards):
        if deadline is not None and time.monotonic() > deadline:
            tally.unlisted = True
            return
        tree = boards / name / "tree"
        if not _real_dir(boards / name) or not _real_dir(tree):
            continue
        path = str(tree)
        if not tally.known(path):
            tally.measure(path, deadline=diskbook.deadline())
        tally.list(path)
        if cutoff is None:
            continue
        try:
            if cachesweep._newest_write(tree) >= cutoff:
                continue
        except OSError:
            continue
        if name in registered:
            tally.keep(path, REGISTERED)
        elif registered:
            _remove_tree(tree, cutoff, repos, transcripts, tally, dry)


def sweep(
    home: str | Path,
    keep_days: int,
    now: float,
    records: Callable[[], list[Any]],
    tally: Tally,
    dry: bool = False,
    deadline: float | None = None,
    repos: Callable[[], Iterable[tuple[str, Any]]] | None = None,
    transcripts: Iterable[Path] | None = (),
) -> None:
    """One pass over the home's files: every name below is measured into `tally`, and, with `keep_days` above 0, each
    past the age that no record holds is removed (`dry`: counted, and left). `records` gives a list copy of the
    records in any state, read at the weigh and again before each removal. Past `deadline` (monotonic) the kind stops
    and reads *partial*. `repos` gives a list copy of the registry's `(key, reading)` pairs for the board trees (None:
    they are not read), and `transcripts` the tools' transcript stores, None where one could not be named."""
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
    if repos is not None:
        _sweep_boards(root, cutoff, repos, transcripts, tally, dry, deadline)
