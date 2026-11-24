"""A session's scratch (design §4.6 *A session's scratch*, TD-1921, TD-1944).

Every run of a record has one scratch directory, `<scratch_root>/shiftlead-<uid>/<token>/`, made `0700` by
the host agent at the run's start, `<token>` eight random hex digits; it holds `owner.json` (the record's id
and the home, nothing more), and the record holds its path as `scratch`. The core puts it in the session's
env as `SHIFTLEAD_SCRATCH`, `TMPDIR` and the adapter's `scratch_env` (§4.2, §4.3). A restart and a Resume
keep it (`kept`); a fresh start and a refill get a new one (`make`).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import stat
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sessionorc import diskbook

MAX_ROOT = 48  # bytes: a scratch home's `agent.sock` at `$SHIFTLEAD_SCRATCH/home` binds within 107 (§4.6)
OWNER = "owner.json"


class ScratchError(Exception):
    """A `scratch_root` the host agent refuses at start, or a parent it will not use (§4.6)."""


def parent(root: str | Path) -> Path:
    """`<scratch_root>/shiftlead-<uid>/`: every run's directory on this host lies under it."""
    return Path(root) / f"shiftlead-{os.getuid()}"


def check_root(root: str | Path, name: str = "scratch_root") -> None:
    """Refused at the host agent's start (§4.6): a `scratch_root` or `seat_root` longer than `MAX_ROOT` bytes."""
    if len(os.fsencode(str(root))) > MAX_ROOT:
        raise ScratchError(
            f"{name} {str(root)!r} is longer than {MAX_ROOT} bytes: a scratch home's socket under it "
            "would not bind (design §4.6 A session's scratch)"
        )


def check_seat_root(seat: str | Path, root: str | Path, transcript_roots: list[Path]) -> None:
    """Refused at the host agent's start (§4.6 *Temporary space is a pool of its own*, TD-2082): a `seat_root` past
    the length, overlapping `scratch_root` without being equal to it as written, or overlapping a transcript store.
    Its directory is never made here, so a mount missing after a reboot stops no host agent."""
    check_root(seat, "seat_root")
    if str(seat) != str(root) and overlaps(seat, root):
        raise ScratchError(
            f"seat_root {str(seat)!r} overlaps scratch_root {str(root)!r} without being equal to it: refused "
            "(design §4.6 Temporary space is a pool of its own)"
        )
    check_transcripts(seat, transcript_roots, "seat_root")


def root_of(given: str | None, roots: tuple[str, ...]) -> str | None:
    """The root whose `shiftlead-<uid>/` holds `given` straight under it, of `roots`; None for neither (§4.6)."""
    if not given:
        return None
    return next((r for r in roots if r and Path(given).parent == parent(r)), None)


def has_reading(root: str | Path) -> bool:
    """Whether a `seat_root` has a reading (§4.6): a mount point, or its `shiftlead-<uid>/` exists. Otherwise it is
    *not mounted*, and neither the sweep nor `ao disk` reads it or makes anything there."""
    return os.path.ismount(root) or os.path.lexists(parent(root))


def overlaps(a: str | Path, b: str | Path) -> bool:
    """Whether `a` is `b`, lies inside it or holds it, read both as written (made absolute) and with every
    symlink resolved, so a link to either side is caught too (§4.6, §9 invariant 16)."""
    for x, y in ((os.path.abspath(a), os.path.abspath(b)), (os.path.realpath(a), os.path.realpath(b))):
        px, py = Path(x), Path(y)
        if px == py or px.is_relative_to(py) or py.is_relative_to(px):
            return True
    return False


def check_transcripts(root: str | Path, transcript_roots: list[Path], name: str = "scratch_root") -> None:
    """Refused at the host agent's start (§4.6, §9 invariant 16, TD-1945): a `scratch_root` or `seat_root` inside, or
    holding, a tool's transcript store, which the disk sweep would otherwise weigh as scratch."""
    for t in transcript_roots:
        if overlaps(root, t):
            raise ScratchError(
                f"{name} {str(root)!r} is inside or holds {str(t)!r}, where a tool keeps its transcripts: "
                "refused (design §4.6 A session's scratch, §9 invariant 16)"
            )


def ensure_parent(root: str | Path) -> Path:
    """Make `shiftlead-<uid>/` (`0700`) under `root`, or refuse it: a symlink, or not this uid's (§4.6)."""
    check_root(root)
    p = parent(root)
    with contextlib.suppress(FileExistsError):
        p.mkdir(mode=0o700, parents=True)
    st = p.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise ScratchError(f"{p} is not a directory of its own (a symlink, or a file): refused (design §4.6)")
    if st.st_uid != os.getuid():
        raise ScratchError(f"{p} is uid {st.st_uid}'s, not this host agent's ({os.getuid()}): refused (design §4.6)")
    if stat.S_IMODE(st.st_mode) != 0o700:
        p.chmod(0o700)
    return p


def write_owner(path: str | Path, record: str, home: str | Path) -> None:
    """`owner.json` in a run's directory: the record's id and the home, nothing more (§4.6)."""
    f = Path(path) / OWNER
    tmp = f.with_name(OWNER + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump({"id": record, "home": str(home)}, out)
    tmp.replace(f)


def owner(path: str | Path) -> dict[str, str] | None:
    """A run's `owner.json`, or None where it has none or cannot be read."""
    try:
        got = json.loads((Path(path) / OWNER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def make(root: str | Path, record: str, home: str | Path) -> str:
    """A new run's directory: `<token>/` under the parent, `0700`, with `owner.json` (§4.6)."""
    p = ensure_parent(root)
    for _ in range(8):
        d = p / secrets.token_hex(4)
        try:
            d.mkdir(mode=0o700)
        except FileExistsError:
            continue
        write_owner(d, record, home)
        return str(d)
    raise ScratchError(f"no free scratch directory under {p}")


def _under(path: Path, p: Path) -> bool:
    """`path` is one directory straight under `p`, its name a token, and no symlink on the way."""
    return path.parent == p and len(path.name) == 8 and all(c in "0123456789abcdef" for c in path.name)


def kept(root: str | Path, given: str | None, record: str, home: str | Path) -> str | None:
    """The old run's `scratch` a restart or a Resume hands the create (§4.6), when it may be kept: a path
    straight under this host's `shiftlead-<uid>/` whose `owner.json` names `record` and `home`, or that is
    gone, when it is made again — `0700`, `owner.json`, empty. None: the create makes a new one."""
    if not given:
        return None
    p = ensure_parent(root)
    path = Path(given)
    if not path.is_absolute() or not _under(path, p):
        return None
    try:
        st = path.lstat()
    except FileNotFoundError:
        try:
            path.mkdir(mode=0o700)
        except OSError:
            return None
        write_owner(path, record, home)
        return str(path)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        return None
    got = owner(path)
    if not got or got.get("id") != record or got.get("home") != str(home):
        return None
    return str(path)


def env(path: str, scratch_env: str | None) -> dict[str, str]:
    """The run's env for its scratch (§4.2, §4.3): set after the adapter's launch env, so ours win."""
    out = {"SHIFTLEAD_SCRATCH": path, "TMPDIR": path}
    if scratch_env:
        out[scratch_env] = path
    return out


SWEEP_TOUCH_FILES = 200_000  # files a record a pass the sweep touches at most; past it, *large scratch* (§4.6)
TOUCH_AFTER_S = 86_400  # a file not accessed for a day is touched (§4.6)


def _touch(path: Path, now_ns: int, cap: int, size: list[int] | None = None) -> bool:
    """Move the access time of every file under `path` not accessed for a day to `now_ns`, its modification
    time left true (§4.6): `systemd-tmpfiles` ages a file by its own times, so a seat that runs past its age
    keeps what it wrote. A symlink is skipped, never touched through; a `.git` is descended into as any
    directory. True where more than `cap` files wanted touching: the rest wait for the next pass. A walk that
    reaches the end appends the bytes it saw to `size` (each entry's own size, the sweep's reading)."""
    stale = now_ns - TOUCH_AFTER_S * 1_000_000_000
    touched = 0
    total = 0
    todo = [path]
    while todo:
        try:
            entries = list(os.scandir(todo.pop()))
        except OSError:  # gone meanwhile, or unreadable
            continue
        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
                total += st.st_size
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    todo.append(Path(e.path))
                    continue
                if not e.is_file(follow_symlinks=False):
                    continue
                if st.st_atime_ns >= stale:
                    continue
                if touched >= cap:
                    return True
                os.utime(e.path, ns=(now_ns, st.st_mtime_ns), follow_symlinks=False)
                touched += 1
            except OSError:
                continue
    if size is not None:
        size.append(total)
    return False


def keep_alive(
    root: str | Path, records: dict[str, str], home: str | Path, now_ns: int, tally: Any = None
) -> list[str]:
    """The hourly sweep's part for live records (§4.6): `records` maps each live record of this host to its
    `scratch`. A directory straight under this host's `shiftlead-<uid>/` that is gone is made again (`0700`,
    `owner.json`, empty), one missing its `owner.json` gains it, and its stale files are touched (`_touch`).
    One elsewhere, not this uid's, or whose `owner.json` names another record or home is left alone. Returns
    the ids past `SWEEP_TOUCH_FILES`, each logged *large scratch* by the caller. `tally` (a `diskbook.Tally`)
    lists each directory touched and takes its size where the walk reached the end."""
    try:
        p = ensure_parent(root)
    except (ScratchError, OSError):
        return []
    large: list[str] = []
    for record, given in records.items():
        path = Path(given)
        if not path.is_absolute() or not _under(path, p):
            continue
        try:
            try:
                st = path.lstat()
            except FileNotFoundError:
                path.mkdir(mode=0o700)
                write_owner(path, record, home)
                continue
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
                continue
            got = owner(path)
            if got is None and not (path / OWNER).exists():
                write_owner(path, record, home)
            elif not got or got.get("id") != record or got.get("home") != str(home):
                continue
        except OSError:
            continue
        size: list[int] = []
        if _touch(path, now_ns, SWEEP_TOUCH_FILES, size):
            large.append(record)
        if tally is not None:
            if size:
                tally.measure(path, size[0] + st.st_size)  # the directory's own entry too, as `size_of` counts
            else:  # a large scratch's touch walk stopped short: sized by a bounded walk of its own, else as last
                tally.measure(path, deadline=diskbook.deadline())
    return large


# -- the disk sweep's scratch rule (design §4.6 *The disk sweep*, TD-1945) ----------------------------------------

UNNAMED_AFTER_S = 3600  # a directory no record names (or naming a gone home) goes an hour after its newest write
FUTURE_AFTER_S = 86_400  # a modification time further than this past now says nothing of a write (§4.6, TD-2126)
GIT_WORK = "git work"
GIT_STEP = 20.0  # each git read's own timeout


def _git_dirs(path: Path, weigh_tests: bool = True, limit: float | None = None) -> list[tuple[str, Path]]:
    """Every git store under `path`, not following a symlink: (`clone`, its directory) for a `.git` directory or a
    bare repo (a directory holding `HEAD`, `objects` and `refs`), (`worktree`, its directory) for a `.git` file. A
    store's own insides are not walked. Raises OSError where a directory cannot be read: kept as *git work*. With
    `weigh_tests` false, a `pytest-of-*/` or a marked test root directly under `path` is not walked (§4.6 *The
    pressure pass*, rule 2): its fixture repos are no one's work. Past `limit` (monotonic) it raises `TimeoutError`,
    an OSError, so a walk cut short reads as held."""
    found: list[tuple[str, Path]] = []
    todo = [path]
    while todo:
        if limit is not None and time.monotonic() > limit:
            raise TimeoutError(f"git walk of {path} cut short")
        d = todo.pop()
        names = {e.name: e for e in os.scandir(d)}
        if "HEAD" in names and "objects" in names and "refs" in names:
            found.append(("clone", d))  # a bare repo
            continue
        for name, e in names.items():
            if e.is_symlink():
                continue
            if name == ".git":
                found.append(("clone" if e.is_dir(follow_symlinks=False) else "worktree", d))
            elif e.is_dir(follow_symlinks=False):
                if not weigh_tests and d == path and _test_root(e):
                    continue
                todo.append(Path(e.path))
    return found


def _test_root(e: os.DirEntry[str]) -> bool:
    """A directory entry that is a test run's own: `pytest-of-*`, or one holding the suite's mark, whatever its pid."""
    return e.name.startswith("pytest-of-") or os.path.lexists(os.path.join(e.path, TEST_RUN_MARK))


def _repo_root(d: Path) -> Path | None:
    """The checkout of the repo a store names, whose `docs/cadence.toml` the *landed* test reads; None for a
    bare repo."""
    from sessionorc import gitinfo

    common = gitinfo._git(d, "rev-parse", "--path-format=absolute", "--git-common-dir", timeout=GIT_STEP)
    if not common:
        return None
    c = Path(common.strip())
    return c.parent if c.name == ".git" else None


def _branch_holds(d: Path, ref: str, branch: str, upstream: str | None, root: Path | None) -> bool:
    """Whether one branch (or a detached `HEAD`, `branch` empty) holds work: not *landed* and commits only on this
    machine by §4.2's one measure, its `ahead` read against its upstream."""
    from sessionorc import gitinfo

    if branch and gitinfo.landed_of(d, ref, root=root, need_pin=True, timeout=GIT_STEP) in gitinfo.LANDED:
        return False
    ahead = 0
    if upstream:
        out = gitinfo._git(d, "rev-list", "--count", f"{upstream}..{ref}", timeout=GIT_STEP)
        if out is None or not out.strip().isdigit():
            return True
        ahead = int(out.strip())
    n, against = gitinfo._unpushed(d, branch or "(detached)", upstream, ahead, GIT_STEP, ref=ref)
    return n > 0 or not against


def _store_holds(kind: str, d: Path) -> bool:
    """Whether one store under scratch holds git work (§4.6): a clone over every local branch and its stash, a
    worktree over its own checked-out branch or detached `HEAD`; a work tree with modified or untracked files; or
    a read that failed."""
    from sessionorc import gitinfo

    root = _repo_root(d)
    bare = gitinfo._git(d, "rev-parse", "--is-bare-repository", timeout=GIT_STEP)
    if bare is None:
        return True
    if bare.strip() != "true":
        status = gitinfo._git(d, "status", "--porcelain", "--untracked-files=all", timeout=GIT_STEP)
        if status is None or status.strip():
            return True
    if kind == "worktree":
        branch = (gitinfo._git(d, "symbolic-ref", "-q", "--short", "HEAD", timeout=GIT_STEP) or "").strip()
        if not branch:
            return _branch_holds(d, "HEAD", "", None, root)
        refs = [(branch, f"refs/heads/{branch}")]
    else:
        out = gitinfo._git(d, "for-each-ref", "--format=%(refname:short)", "refs/heads", timeout=GIT_STEP)
        if out is None:
            return True
        refs = [(b, f"refs/heads/{b}") for b in out.split()]
        head = (gitinfo._git(d, "symbolic-ref", "-q", "--short", "HEAD", timeout=GIT_STEP) or "").strip()
        has_head = gitinfo._git(d, "rev-parse", "--verify", "-q", "HEAD^{commit}", timeout=GIT_STEP) is not None
        if not head and has_head and _branch_holds(d, "HEAD", "", None, root):
            return True
        stash = gitinfo._git(d, "rev-parse", "--verify", "-q", "refs/stash", timeout=GIT_STEP)
        if stash is not None:
            n = gitinfo._git(d, "rev-list", "--count", "refs/stash", "--not", "--remotes", timeout=GIT_STEP)
            if n is None or not n.strip().isdigit() or int(n.strip()):
                return True
    for branch, ref in refs:
        up = gitinfo._git(
            d, "rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{branch}@{{upstream}}", timeout=GIT_STEP
        )
        upstream = (up or "").strip() or None
        if upstream and gitinfo._git(d, "rev-parse", "--verify", "-q", upstream, timeout=GIT_STEP) is None:
            upstream = None  # an upstream gone: passed as none, so `<ref> --not --remotes` answers
        if _branch_holds(d, ref, branch, upstream, root):
            return True
    return False


def git_work(path: str | Path, weigh_tests: bool = True, limit: float | None = None) -> bool:
    """Whether a scratch directory holds git work and is kept (*git work*, §4.6): any store under it that holds
    some, or a tree or store that cannot be read. `weigh_tests` false is the pressure pass's rule 2 alone. Past
    `limit` (monotonic), read in the walk and between stores, it is held (§4.6 *tool temp*)."""
    try:
        stores = _git_dirs(Path(path), weigh_tests, limit)
    except OSError:
        return True
    for kind, d in stores:
        if limit is not None and time.monotonic() > limit:
            return True
        if _store_holds(kind, d):
            return True
    return False


def _worktree_mains(path: Path) -> list[Path]:
    """The repos whose worktrees lie under `path` (by each `.git` file's `gitdir:`), for `git worktree prune` once
    it is gone."""
    mains: list[Path] = []
    try:
        stores = _git_dirs(path)
    except OSError:
        return mains
    for kind, d in stores:
        if kind != "worktree":
            continue
        try:
            line = (d / ".git").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if line.startswith("gitdir:"):
            g = Path(line.removeprefix("gitdir:").strip())
            if g.parent.name == "worktrees":
                common = g.parent.parent
                mains.append(common.parent if common.name == ".git" else common)
    return mains


def _written_at(mtime: float, now: float) -> float:
    """A modification time as a write's time: 0 where it lies more than `FUTURE_AFTER_S` past `now`, which says
    nothing about when the entry was written (§4.6 *A live seat's rebuildable copies*, part 1)."""
    return mtime if mtime <= now + FUTURE_AFTER_S else 0.0


def _newest_write(path: Path, now: float) -> float:
    """The newest write under `path`, itself included, by `_written_at` against `now`, not following a symlink and
    still walking a directory dated far ahead; an entry that cannot be read counts as written now, so it never ages
    a directory past its hour."""
    newest = _written_at(path.lstat().st_mtime, now)
    todo = [path]
    while todo:
        try:
            entries = list(os.scandir(todo.pop()))
        except OSError:
            return time.time()
        for e in entries:
            try:
                newest = max(newest, _written_at(e.stat(follow_symlinks=False).st_mtime, now))
                if e.is_dir(follow_symlinks=False):
                    todo.append(Path(e.path))
            except FileNotFoundError:
                continue
            except OSError:
                return time.time()
    return newest


def _remove(path: Path, floor: Path | None = None) -> None:
    """Remove a scratch directory whole, a symlink inside it as a link, read-only directories made writable. With
    `floor`, the retry never makes `floor`'s parent writable, which for *tool temp* is `/tmp` or the tool's root."""
    import shutil

    def again(fn, p, exc):
        if isinstance(exc, FileNotFoundError):  # the other remover took it (§4.6 *The pressure pass*)
            return
        with contextlib.suppress(OSError):
            if floor is None or os.path.abspath(p) != os.path.abspath(floor):
                os.chmod(os.path.dirname(p), 0o700)
            if not os.path.islink(p) and os.path.isdir(p):
                os.chmod(p, 0o700)
        fn(p)

    shutil.rmtree(path, onexc=again)


def _keep(kept: list[tuple[str, str]], tally: Any, path: Path, why: str) -> None:
    """A directory a rule would otherwise take, kept: with why, and measured for the sweep's reading."""
    kept.append((str(path), why))
    if tally is not None:
        tally.measure(path, deadline=diskbook.deadline())
        tally.keep(path, why)


def _measure_once(tally: Any, path: Path, live: bool) -> None:
    """A directory no rule takes this pass is measured only where nothing has sized it yet; a live record's is
    sized by `keep_alive`'s touch walk."""
    if tally is not None and not live and not tally.known(path):
        tally.measure(path, deadline=diskbook.deadline())


def sweep(
    root: str | Path,
    home: str | Path,
    named: dict[str, tuple[str, float | None]],
    keep_hours: float,
    now_s: float,
    live_now,
    transcript_roots: list[Path],
    tally: Any = None,
    dry: bool = False,
    deadline: float | None = None,
    stop: Callable[[], bool] | None = None,
) -> list[tuple[str, str]]:
    """The hourly sweep's scratch rule for directories no live record holds (§4.6 *The disk sweep*). `named` maps
    a directory to the record naming it in the snapshot and when that record ended (None: live). A directory
    straight under this host's `shiftlead-<uid>/` whose `owner.json` names this home goes once its record has
    been ended `keep_hours`, or, named by no record or naming a home that no longer exists, an hour after its
    newest write — unless `live_now(path)` (the records read again just before the removal) says a live record
    holds it, or it holds git work or a transcript store. Never one naming another home that exists, nor one with
    no readable `owner.json`. After a removal, `git worktree prune` runs in each repo a worktree under it named.
    Returns the kept directories with why, and logs each removal. `tally` (a `diskbook.Tally`) lists each directory
    this home holds, measures each one the pass removes or keeps and each it has no size for, and counts what goes;
    one naming another home that exists is kept *another home*, its bytes that home's. `dry` removes nothing, each
    directory it would remove counted as gone in `tally`; past `deadline` (monotonic) it stops, the tally *partial*
    (a dry run's, §4.6 *The sweep's reading*, TD-1946). `stop` is the pressure pass's rule 2 (§4.6 *The pressure
    pass*): directories go longest-ended first, its answer is read before each, and a test run's fixture repos are
    not weighed as git work."""
    import logging
    import shutil

    log = logging.getLogger(__name__)
    p = parent(root)
    kept: list[tuple[str, str]] = []
    weigh = None if stop is not None else tally  # under pressure only what goes is measured
    try:
        st = p.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            return kept
        entries = sorted(os.scandir(p), key=lambda e: e.name)
    except FileNotFoundError:
        return kept  # no scratch yet: none held
    except OSError:
        if tally is not None:
            tally.unlisted = True  # the last reading stands, *partial*
        return kept
    if stop is not None:  # a directory no record names has no end to wait for: first
        entries.sort(key=lambda e: named.get(e.path, (None, None))[1] or 0.0)
    for e in entries:
        if deadline is not None and time.monotonic() > deadline:
            if tally is not None:
                tally.unlisted = True
            break
        if stop is not None and stop():
            break
        path = Path(e.path)
        if not _under(path, p) or e.is_symlink() or not e.is_dir(follow_symlinks=False):
            continue
        try:
            if e.stat(follow_symlinks=False).st_uid != os.getuid():
                continue
            got = owner(path)
            if not got or not isinstance(got.get("home"), str):
                _keep(kept, weigh, path, "no owner")
                continue
            rid, ended = named.get(str(path), (None, None))
            if got["home"] != str(home):
                if Path(got["home"]).exists():
                    # another home's own agent sweeps it, never this one: reported kept, its bytes that home's
                    kept.append((str(path), "another home"))
                    if tally is not None:
                        tally.keep(path, "another home")
                    continue
                rid = None
            if tally is not None:
                tally.list(path)
            if rid is not None:
                if ended is None or now_s - ended < keep_hours * 3600:
                    _measure_once(weigh, path, ended is None)
                    continue
            elif now_s - _newest_write(path, now_s) < UNNAMED_AFTER_S:
                _measure_once(weigh, path, False)
                continue
            if live_now(str(path)):
                _keep(kept, weigh, path, "live record")
                continue
            if any(overlaps(path, t) for t in transcript_roots):
                _keep(kept, weigh, path, "transcripts")
                continue
            if git_work(path) if stop is None else git_work(path, weigh_tests=False):
                _keep(kept, weigh, path, GIT_WORK)
                continue
            mains = _worktree_mains(path)
            if live_now(str(path)):  # read again just before the removal: the weigh can take a while
                _keep(kept, weigh, path, "live record")
                continue
            size = None
            if tally is not None:
                size = tally.measure(path, deadline=diskbook.deadline())  # None past it: removed as last measured
            if dry:
                if tally is not None:
                    tally.gone(path, size)
                continue
            _remove(path)
            if tally is not None:
                tally.gone(path, size)
            log.info("removed scratch %s (%s)", path, f"ended {rid}" if rid else "named by no live record")
            for m in mains:
                git = shutil.which("git") or "git"
                with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                    subprocess.run([git, "-C", str(m), "worktree", "prune"], capture_output=True, timeout=GIT_STEP)
        except OSError as err:
            log.warning("could not weigh or remove scratch %s: %s", path, err)
    return kept


# -- the pressure pass (design §4.6 *The pressure pass*, TD-2081) --------------------------------------------------

PRESSURE_EVERY = 60  # seconds between readings of the pool's share free
PRESSURE_LOW = 0.25  # under this share free a reclaim starts
PRESSURE_CLEAR = 0.35  # a reclaim stops once back over this
PRESSURE_BACKOFF = 1800  # seconds no reclaim follows one that raised the share under `PRESSURE_RISE`
PRESSURE_RISE = 0.01  # one point of share free
PRESSURE_FALL = 0.05  # five more points down ends a backoff early
PRESSURE_KEEP_HOURS = 1.0  # rule 2's keep in place of `scratch_keep_hours`
PRESSURE_TELL = 0.15  # under this share free, once reclaimed from, a pool is *low* (TD-2083)
PRESSURE_WALK_S = 30.0  # the one walk that names a low pool's largest holders
PRESSURE_HOLDERS = 3
# told when memory runs short (§4.6, TD-2127, built by TD-2136): read every `PRESSURE_EVERY` too (`sessionorc.memory`)
MEMORY_LOW = 0.10  # two readings running under this share free make a half *turning*
MEMORY_CLEAR = 0.20  # the first reading over this ends it
LEFT_EVERY = 600  # seconds between walks of `/proc` (§4.6 *The process reading*)
LEFT_WALK_S = 10.0  # one walk's bound; twice this and it is cut with no holders
LEFT_SLACK = 60  # seconds a process may start before its record's `created` and still be that run's
# told what finished sessions left running (§4.6, TD-2127, built by TD-2137)
LEFT_AGE = 3600  # a process younger than this is never named
LEFT_RAISE = (512 * 1024**2, 25)  # bytes or processes, trees included: two `LEFT_EVERY` walks at or over start a spell
LEFT_CLEAR = (256 * 1024**2, 10)  # the first complete `LEFT_EVERY` walk under both ends it
LEFT_ENDED_KEEP = 90 * 86_400  # an `ended_runs` span is kept this long after its `to`
LEFT_ENDED_RUNS = 20  # and at most this many runs an id
TEST_RUN_MARK = ".shiftlead-test-run"  # a suite's scratch root, holding its pid (TD-2084)
RUN_QUIET_S = 600  # rule 1: nothing under a run written for ten minutes
BUILD_QUIET_S = 86_400  # rule 3: nothing under a build leftover written for a day
BUILD_LEFTOVERS = ("pdm-build-", "pdm-wheel-cache-")
_PYTEST_RUN = re.compile(r"pytest-\d+")
TEST_KEEP_S = 7200  # a live seat's ended test run stays readable this long (§4.6 *A live seat's rebuildable copies*)
RELEASE_WALK_S = 60.0  # the hourly release's bound on one candidate's walk
WALK_CUT = "walk cut short"
TEST_RUNS_DIR = ".shiftlead-test-runs"  # in a seat: one file per hand-run suite with its own `--basetemp`
RUN_LIST_MAX = 4096  # bytes read of a list file or a mark; a longer one is not ours
_RUN_FILE = re.compile(r"(\d+)-\d+")


class Backoff:
    """Whether a low reading starts a reclaim: none for `PRESSURE_BACKOFF` after one that raised the share free under
    a point, unless the share falls `PRESSURE_FALL` below that reclaim's last reading."""

    def __init__(self) -> None:
        self.until = 0.0
        self.floor: float | None = None

    def due(self, share: float | None, now: float) -> bool:
        if share is None or share >= PRESSURE_LOW:
            return False
        return now >= self.until or self.floor is None or share <= self.floor - PRESSURE_FALL

    def after(self, start: float, end: float | None, skipped: bool, now: float) -> bool:
        """Record a finished reclaim; True where it was weak (it raised the share under a point). One that skipped
        rule 2 starts no backoff and leaves any standing one, so the next reading tries again."""
        weak = end is None or end - start < PRESSURE_RISE
        if not weak:
            self.until, self.floor = 0.0, None
        elif not skipped:
            self.until, self.floor = now + PRESSURE_BACKOFF, start if end is None else end
        return weak


def _pid_gone(text: str) -> bool:
    """Whether a lock's text names a pid not running. Empty or unreadable, or another uid's pid, counts as live."""
    try:
        pid = int(text.strip())
        if pid <= 0:
            return False
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (ValueError, OSError, OverflowError):
        return False
    return False


def _run_over(run: Path) -> bool:
    """A pytest run's `.lock` is absent (it finished) or names a pid not running."""
    try:
        return _pid_gone((run / ".lock").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        return False


def _quiet_reading(path: Path, now: float, quiet_s: float, changed: bool = False, walk_s: float | None = None) -> str:
    """`quiet` where nothing under `path` was written for `quiet_s`, each time read by `_written_at`; `cut` where the
    walk passed its bound (`walk_s`, else `diskbook.WALK_S`); `written` otherwise, an entry that cannot be read
    included. `changed` also reads each entry's change time, which a copy or a move into the tree cannot set back
    (§4.6 *tool temp*)."""
    cut = now - quiet_s
    limit = diskbook.deadline() if walk_s is None else time.monotonic() + walk_s

    def at(st: os.stat_result) -> float:
        written = _written_at(st.st_mtime, now)
        return max(written, st.st_ctime) if changed else written

    try:
        if at(path.lstat()) > cut:
            return "written"
        todo = [path]
        while todo:
            if time.monotonic() > limit:
                return "cut"
            for e in list(os.scandir(todo.pop())):
                try:
                    if at(e.stat(follow_symlinks=False)) > cut:
                        return "written"
                    if e.is_dir(follow_symlinks=False):
                        todo.append(Path(e.path))
                except FileNotFoundError:
                    continue
    except OSError:
        return "written"
    return "quiet"


def _quiet(path: Path, now: float, quiet_s: float, changed: bool = False, walk_s: float | None = None) -> bool:
    """Whether `_quiet_reading` reads `path` as quiet; a walk cut short is not."""
    return _quiet_reading(path, now, quiet_s, changed, walk_s) == "quiet"


def _seats(root: str | Path, home: str | Path) -> list[Path]:
    """The run directories under the pool's `shiftlead-<uid>/` a reclaim reads: this uid's, not a symlink, with an
    `owner.json` naming this home or one that no longer exists. Another home's are that home's to reclaim. A parent
    that is a symlink, not a directory or another uid's is refused, as `sweep` and `ensure_parent` refuse it."""
    p = parent(root)
    out: list[Path] = []
    try:
        st = p.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            return out
        entries = sorted(os.scandir(p), key=lambda e: e.name)
    except OSError:
        return out
    for e in entries:
        path = Path(e.path)
        try:
            if not _under(path, p) or e.is_symlink() or not e.is_dir(follow_symlinks=False):
                continue
            if e.stat(follow_symlinks=False).st_uid != os.getuid():
                continue
        except OSError:
            continue
        got = owner(path)
        if not got or not isinstance(got.get("home"), str):
            continue
        if got["home"] == str(home) or not Path(got["home"]).exists():
            out.append(path)
    return out


def _dirs(path: Path) -> list[os.DirEntry[str]]:
    """The real directories straight under `path`, never a symlink; none where it cannot be read."""
    try:
        return [e for e in os.scandir(path) if e.is_dir(follow_symlinks=False)]
    except OSError:
        return []


def _test_runs(seat: Path, current: bool = False) -> list[Path]:
    """Rule 1's candidates directly under a seat: each `pytest-of-*/pytest-<N>/` that is over and not `pytest-current`'s
    target (`current`, the hourly release's: its target too, by the same test), and each directory whose
    `.shiftlead-test-run` names a pid not running."""
    out: list[Path] = []
    for e in _dirs(seat):
        if e.name.startswith("pytest-of-"):
            target = None if current else os.path.realpath(os.path.join(e.path, "pytest-current"))
            out += [
                Path(r.path)
                for r in _dirs(Path(e.path))
                if _PYTEST_RUN.fullmatch(r.name) and os.path.realpath(r.path) != target and _run_over(Path(r.path))
            ]
            continue
        try:
            if _pid_gone(Path(e.path, TEST_RUN_MARK).read_text(encoding="utf-8")):
                out.append(Path(e.path))
        except (OSError, ValueError):
            continue
    return out


def _read_small(path: Path) -> str | None:
    """A regular file of this uid, up to `RUN_LIST_MAX` bytes, never through a symlink; None for anything else."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            return None
        data = os.read(fd, RUN_LIST_MAX + 1)
        return None if len(data) > RUN_LIST_MAX else data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        os.close(fd)


def _listed_base(seat: Path, text: str) -> tuple[Path | None, bool]:
    """The base temp a list file names, with whether it is gone. None, not gone, where it is not a real directory of
    this uid strictly under the seat with no symlink on the way (§4.6 *A hand-run suite is marked*)."""
    real = Path(os.path.realpath(seat))
    if not os.path.isabs(text) or os.path.normpath(text) != text:
        return None, False
    try:
        parts = Path(text).relative_to(real).parts
    except ValueError:
        return None, False
    if not parts:
        return None, False
    at = real
    try:
        for part in parts:
            at = at / part
            st = at.lstat()
            if stat.S_ISLNK(st.st_mode):
                return None, False
    except FileNotFoundError:
        return None, True
    except OSError:
        return None, False
    return (at, False) if stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() else (None, False)


def _listed_runs(seat: Path, dry: bool = False) -> list[Path]:
    """The hand-run suites a seat's run list names whose process has ended. A file whose path is gone, or whose mark
    names another pid (a later run reused the `--basetemp`), is removed, except by a dry run."""
    d = seat / TEST_RUNS_DIR
    try:
        st = d.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            return []
        entries = list(os.scandir(d))
    except OSError:
        return []
    out: list[Path] = []
    for e in entries:
        got = _RUN_FILE.fullmatch(e.name)
        text = _read_small(Path(e.path)) if got else None
        if text is None:
            continue
        base, gone = _listed_base(seat, text.rstrip("\n"))
        mark = None if base is None else _read_small(base / TEST_RUN_MARK)
        pid = None if mark is None else mark.strip()
        if gone or (pid is not None and pid.isdecimal() and pid != got[1]):
            if not dry:
                with contextlib.suppress(OSError):
                    os.unlink(e.path)
        elif pid is not None and _pid_gone(pid):
            out.append(base)
    return out


def _candidates(seat: Path, current: bool = False, dry: bool = False) -> list[Path]:
    """A seat's ended test runs, each once: rule 1's and the listed ones."""
    runs: dict[str, Path] = {}
    for run in [*_test_runs(seat, current), *_listed_runs(seat, dry)]:
        runs.setdefault(os.path.realpath(run), run)
    return list(runs.values())


def release(
    root: str | Path,
    home: str | Path,
    transcript_roots: list[Path],
    now_s: float,
    tally: Any = None,
    dry: bool = False,
    deadline: float | None = None,
) -> list[tuple[str, str]]:
    """The hourly release of ended test runs from every directory `_seats` returns (§4.6 *A live seat's rebuildable
    copies*, part 3): each goes once nothing under it was written for `TEST_KEEP_S`, `pytest-current` unlinked while it
    still names it. A path overlapping a transcript store is skipped, and past `deadline` (monotonic) the pass stops,
    its tally *partial*. A dry run counts what would go and removes nothing. Returns the runs kept, with why."""
    import logging

    log = logging.getLogger(__name__)
    kept: list[tuple[str, str]] = []
    for seat in _seats(root, home):
        for run in _candidates(seat, current=True, dry=dry):
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                if tally is not None:
                    tally.unlisted = True
                return kept
            if any(overlaps(run, t) for t in transcript_roots):
                continue
            walk_s = RELEASE_WALK_S if left is None else min(RELEASE_WALK_S, left)
            reading = _quiet_reading(run, now_s, TEST_KEEP_S, walk_s=walk_s)
            if reading == "cut":
                kept.append((str(run), WALK_CUT))
                if tally is not None:
                    tally.keep(run, WALK_CUT)
            if reading != "quiet":
                continue
            size = diskbook.size_of(run, diskbook.deadline()) if tally is not None else None
            if dry:
                if tally is not None:
                    tally.gone(run, size)
                continue
            link = run.parent / "pytest-current"
            target = os.path.realpath(run)
            try:
                _remove(run)
            except OSError as err:
                log.warning("could not release %s: %s", run, err)
                continue
            if tally is not None:
                tally.gone(run, size)
            log.info("released test run %s", run)
            with contextlib.suppress(OSError):
                if link.is_symlink() and os.path.realpath(link) == target:
                    link.unlink()
    return kept


COPIES_DIR = "copies"  # in a seat: the one place for a review copy or an exported tree (TD-2132)
COPY_KEEP_S = 86_400  # the hourly pass takes a copy after a quiet day
COPY_PRESSURE_S = 7200  # the pressure pass's rule 4 after two quiet hours
GONE = ".gone-"  # a copy renamed on its way out, so a reader gets *no such file* rather than a partial tree
IN_USE = "in use"
PROC_UNREAD = "processes unreadable"


def _copies(seat: Path) -> Path | None:
    """A seat's `copies/`, where it is a real directory of this uid; None for anything else."""
    d = seat / COPIES_DIR
    try:
        st = d.lstat()
    except OSError:
        return None
    return d if stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() else None


def _copy_dirs(copies: Path, gone: bool) -> list[Path]:
    """The real directories straight under `copies` that resolved lie under it: the `.gone-*` ones (`gone`), or the
    candidates. A plain file there is never aged."""
    real = os.path.realpath(copies)
    out: list[Path] = []
    for e in sorted(_dirs(copies), key=lambda e: e.name):
        if e.name.startswith(GONE) != gone:
            continue
        if os.path.dirname(os.path.realpath(e.path)) != real:
            continue
        out.append(Path(e.path))
    return out


def _proc_paths(base: str) -> set[str]:
    """The paths the process at `base` (`/proc/<pid>`) holds: its working directory, root, executable, mapped files
    and open files."""
    got: set[str] = set()

    def link(p: str) -> None:
        with contextlib.suppress(FileNotFoundError):  # a zombie's, or an fd closed while it was read
            got.add(os.readlink(p).removesuffix(" (deleted)"))

    for name in ("cwd", "root", "exe"):
        link(f"{base}/{name}")
    with open(f"{base}/maps", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split(None, 5)
            if len(parts) == 6 and parts[5].startswith("/"):
                got.add(parts[5].removesuffix(" (deleted)"))
    for fd in os.listdir(f"{base}/fd"):
        link(f"{base}/fd/{fd}")
    return got


def held_paths(proc: str = "/proc") -> set[str] | None:
    """Every path a process of this uid holds (§4.6 *A live seat's rebuildable copies*, part 4), read once a pass. A
    process that has gone is skipped, and so is one the kernel refuses to show (it holds capabilities this process
    lacks, or is marked not dumpable: `systemd --user`, `gpg-agent`, a container's), which is not seen, as one in
    another pid namespace is not; None where `proc` cannot be listed or a process of this uid cannot be read for any
    other reason, so every copy is kept."""
    uid = os.getuid()
    try:
        pids = [e.name for e in os.scandir(proc) if e.name.isdecimal()]
    except OSError:
        return None
    held: set[str] = set()
    for pid in pids:
        try:
            if os.stat(f"{proc}/{pid}").st_uid != uid:
                continue
            held |= _proc_paths(f"{proc}/{pid}")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        except OSError:
            return None
    return held


def _copy_reading(
    path: Path, now_s: float, quiet_s: float, walk_s: float | None, held: Callable[[], set[str] | None]
) -> str:
    """`take` where a copy may go; `written` where something under it was written within `quiet_s`, by modification
    and directory change times; else why it is kept: the walk cut short, a process in it, `/proc` unreadable, git
    work."""
    reading = _quiet_reading(path, now_s, quiet_s, changed=True, walk_s=walk_s)
    if reading == "cut":
        return WALK_CUT
    if reading != "quiet":
        return "written"
    got = held()
    if got is None:
        return PROC_UNREAD
    real = os.path.realpath(path)
    if any(p == real or p.startswith(real + os.sep) for p in got):
        return IN_USE
    if git_work(path, limit=time.monotonic() + (RELEASE_WALK_S if walk_s is None else walk_s)):
        return GIT_WORK  # past its bound too: a read cut short holds the copy
    return "take"


def _gone_to(copies: Path, name: str) -> Path:
    """A free `.gone-<name>`, with a suffix `-<n>` where that name exists, the name cut to fit a file name's bound."""
    name = name.encode()[:200].decode(errors="ignore")
    at, n = copies / f"{GONE}{name}", 0
    while os.path.lexists(at):
        n += 1
        at = copies / f"{GONE}{name}-{n}"
    return at


def _drop_copy(path: Path, copies: Path) -> None:
    """Rename a copy to a free `.gone-*`, remove it, then `git worktree prune` where it carried a worktree."""
    import shutil

    mains = _worktree_mains(path)
    gone = _gone_to(copies, path.name)
    os.rename(path, gone)
    try:
        _remove(gone)
    finally:  # a removal that failed leaves a .gone-* the next pass finishes, and the worktrees pruned now
        for m in mains:
            git = shutil.which("git") or "git"
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run([git, "-C", str(m), "worktree", "prune"], capture_output=True, timeout=GIT_STEP)


def _finish_gone(copies: Path, transcript_roots: list[Path], log: Any) -> None:
    """Remove the `.gone-*` a pass left behind, with no age test."""
    for g in _copy_dirs(copies, gone=True):
        if any(overlaps(g, t) for t in transcript_roots):
            continue
        try:
            _remove(g)
        except OSError as err:
            log.warning("could not finish %s: %s", g, err)


def held_once() -> Callable[[], set[str] | None]:
    """`held_paths`, read at the first call and kept for the pass."""
    got: list[set[str] | None] = []

    def held() -> set[str] | None:
        if not got:
            got.append(held_paths())
        return got[0]

    return held


def release_copies(
    root: str | Path,
    home: str | Path,
    transcript_roots: list[Path],
    now_s: float,
    tally: Any = None,
    dry: bool = False,
    deadline: float | None = None,
    held: Callable[[], set[str] | None] | None = None,
) -> list[tuple[str, str]]:
    """The hourly release of a seat's `copies/` (§4.6 *A live seat's rebuildable copies*, part 4), over the directories
    `_seats` returns: the `.gone-*` left behind are finished first, then each copy goes once nothing under it was
    written for `COPY_KEEP_S`, unless a process of this uid holds a path under it, it holds git work, or `/proc` cannot
    be read. A path overlapping a transcript store is skipped; past `deadline` the pass stops, its tally *partial*. A
    dry run counts what would go and removes nothing. `held` is the pass's one `/proc` reading (`held_once`), shared
    by every root. Returns the copies kept, with why."""
    import logging

    log = logging.getLogger(__name__)
    kept: list[tuple[str, str]] = []
    held = held or held_once()
    for seat in _seats(root, home):
        copies = _copies(seat)
        if copies is None:
            continue
        if deadline is not None and time.monotonic() >= deadline:
            if tally is not None:
                tally.unlisted = True
            return kept
        if not dry:
            _finish_gone(copies, transcript_roots, log)
        for copy in _copy_dirs(copies, gone=False):
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                if tally is not None:
                    tally.unlisted = True
                return kept
            if any(overlaps(copy, t) for t in transcript_roots):
                continue
            walk_s = RELEASE_WALK_S if left is None else min(RELEASE_WALK_S, left)
            reading = _copy_reading(copy, now_s, COPY_KEEP_S, walk_s, held)
            if reading == "written":
                continue
            if reading != "take":
                kept.append((str(copy), reading))
                if tally is not None:
                    tally.keep(copy, reading)
                continue
            size = diskbook.size_of(copy, diskbook.deadline()) if tally is not None else None
            if not dry:
                try:
                    _drop_copy(copy, copies)
                except OSError as err:
                    log.warning("could not release %s: %s", copy, err)
                    continue
                log.info("released copy %s", copy)
            if tally is not None:
                tally.gone(copy, size)
    return kept


def reclaim(
    root: str | Path,
    home: str | Path,
    named: dict[str, tuple[str, float | None]],
    live_now: Callable[[str], bool],
    transcript_roots: list[Path] | None,
    share: Callable[[], float | None],
    now_s: float,
    sweep_lock: Any,
) -> dict[str, Any]:
    """One reclaim of the pool at `root` (§4.6 *The pressure pass*): test runs, then ended runs' directories under
    `PRESSURE_KEEP_HOURS`, then build leftovers, then copies after `COPY_PRESSURE_S`, stopping once `share()` is back
    over `PRESSURE_CLEAR`. Rule 2 takes
    `sweep_lock` without waiting and is `skipped` if it is held. No rule removes a path that overlaps a transcript
    store (§9 invariant 16), and with `transcript_roots` None (an adapter that cannot name its stores, so one could
    lie inside any candidate) nothing is removed. Returns the bytes `removed` and `skipped`."""
    import logging

    log = logging.getLogger(__name__)
    if transcript_roots is None:
        return {"removed": 0, "skipped": False}
    removed = 0
    skipped = False

    def done() -> bool:
        got = share()
        return got is None or got >= PRESSURE_CLEAR

    def take(path: Path, quiet_s: float) -> None:
        nonlocal removed
        if any(overlaps(path, t) for t in transcript_roots):
            return
        reading = _quiet_reading(path, now_s, quiet_s)
        if reading == "cut":
            log.warning("reclaim kept %s: %s", path, WALK_CUT)
        if reading != "quiet":
            return
        try:
            size = diskbook.size_of(path, diskbook.deadline()) or 0
            _remove(path)
        except OSError as err:
            log.warning("could not reclaim %s: %s", path, err)
            return
        removed += size
        log.info("reclaimed %s", path)

    for seat in _seats(root, home):
        for run in _candidates(seat):
            if done():
                return {"removed": removed, "skipped": False}
            take(run, RUN_QUIET_S)
    if done():
        return {"removed": removed, "skipped": False}
    if sweep_lock.acquire(blocking=False):
        try:
            tally = diskbook.Tally()
            sweep(root, home, named, PRESSURE_KEEP_HOURS, now_s, live_now, transcript_roots, tally, stop=done)
            removed += tally.removed
        finally:
            sweep_lock.release()
    else:
        skipped = True
    for seat in _seats(root, home):
        for e in _dirs(seat):
            if e.name.startswith(BUILD_LEFTOVERS):
                if done():
                    return {"removed": removed, "skipped": skipped}
                take(Path(e.path), BUILD_QUIET_S)
    held = held_once()
    for seat in _seats(root, home):  # rule 4: copies, after two quiet hours
        copies = _copies(seat)
        if copies is None:
            continue
        _finish_gone(copies, transcript_roots, log)
        for copy in _copy_dirs(copies, gone=False):
            if done():
                return {"removed": removed, "skipped": skipped}
            if any(overlaps(copy, t) for t in transcript_roots):
                continue
            reading = _copy_reading(copy, now_s, COPY_PRESSURE_S, None, held)
            if reading == WALK_CUT:
                log.warning("reclaim kept %s: %s", copy, WALK_CUT)
            if reading != "take":
                continue
            try:
                size = diskbook.size_of(copy, diskbook.deadline()) or 0
                _drop_copy(copy, copies)
            except OSError as err:
                log.warning("could not reclaim %s: %s", copy, err)
                continue
            removed += size
            log.info("reclaimed copy %s", copy)
    return {"removed": removed, "skipped": skipped}


# -- told before the pool is full (design §4.6, TD-2083) ------------------------------------------------------------


def _inodes(path: str, limit: float) -> tuple[int, bool]:
    """How many inodes lie at and under `path`, never through a symlink, and whether the walk was cut at `limit`."""
    n, todo = 1, [path]
    try:
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            return n, False
    except OSError:
        return n, False
    while todo:
        if time.monotonic() > limit:
            return n, True
        try:
            with os.scandir(todo.pop()) as it:
                for e in it:
                    n += 1
                    if not n % 4096 and time.monotonic() > limit:  # one huge flat directory is bounded too
                        return n, True
                    with contextlib.suppress(OSError):
                        if e.is_dir(follow_symlinks=False):
                            todo.append(e.path)
        except OSError:
            continue
    return n, False


def holders(root: str | Path, walk_s: float = PRESSURE_WALK_S) -> list[dict[str, Any]]:
    """A low pool's three largest holders by inodes (§4.6 *Told before the pool is full*): each directory under
    `shiftlead-<uid>/`, named by the record in its `owner.json`, and each other top-level entry. One walk bounded by
    `walk_s`; a count it cut short has `cut`, read as *at least*."""
    limit = time.monotonic() + walk_s
    ours = parent(root)
    found: list[dict[str, Any]] = []

    def count(path: str, name: str) -> None:
        n, cut = _inodes(path, limit)
        found.append({"name": name, "inodes": n, "cut": cut})

    try:
        with os.scandir(root) as it:
            top = sorted(it, key=lambda e: e.name)
    except OSError:
        return []
    for e in top:
        if Path(e.path) != ours or e.is_symlink():
            count(e.path, e.name)
            continue
        try:
            with os.scandir(e.path) as it:
                seats = sorted(it, key=lambda s: s.name)
        except OSError:
            count(e.path, e.name)
            continue
        for s in seats:
            got = owner(s.path) if s.is_dir(follow_symlinks=False) else None
            count(s.path, str((got or {}).get("id") or s.name))
    found.sort(key=lambda h: -h["inodes"])
    return found[:PRESSURE_HOLDERS]


def same_fs(a: str | Path, b: str | Path) -> bool:
    """Whether two paths lie on one file system (`st_dev`), each read at its nearest existing parent. Unreadable, no."""

    def dev(path: str | Path) -> int:
        at = Path(path)
        while not at.exists() and at.parent != at:
            at = at.parent
        return at.stat().st_dev

    try:
        return dev(a) == dev(b)
    except OSError:
        return False


def step_low(
    state: dict[str, dict[str, Any]],
    readings: list[tuple[str, str, bool, float | None]],
    keep: set[str],
    reclaimed: str | None,
    walk: Callable[[str], list[dict[str, Any]]],
    now: str,
) -> dict[str, dict[str, Any]]:
    """The pools' *low* state after one reading (§4.6 *Told before the pool is full*). `readings` is `(pool, path,
    reclaims, share)`. A pool reclaimed from turns low under `PRESSURE_TELL` once a reclaim has run since it was last
    over `PRESSURE_CLEAR`; one that is not (`shared` beside `seats`) on the reading alone. It stays low until back over
    `PRESSURE_CLEAR`; no reading changes nothing, and a pool not in `keep` is forgotten."""
    out = {k: dict(v) for k, v in state.items() if k in keep}
    for name, path, reclaims, share in readings:
        if name == reclaimed:  # kept even where this reading failed: the reclaim did run
            out.setdefault(name, {})["reclaimed"] = True
        if share is None:
            continue
        if share >= PRESSURE_CLEAR:
            out.pop(name, None)
            continue
        one = out.get(name) or {}
        if not one.get("low") and share < PRESSURE_TELL and (one.get("reclaimed") or not reclaims):
            one.update(low=True, since=now, share_free=share, holders=walk(path))
        if one:
            out[name] = one
    return out
