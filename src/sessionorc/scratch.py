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
import secrets
import stat
import subprocess
import time
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


def check_root(root: str | Path) -> None:
    """Refused at the host agent's start (§4.6): a `scratch_root` longer than `MAX_ROOT` bytes."""
    if len(os.fsencode(str(root))) > MAX_ROOT:
        raise ScratchError(
            f"scratch_root {str(root)!r} is longer than {MAX_ROOT} bytes: a scratch home's socket under it "
            "would not bind (design §4.6 A session's scratch)"
        )


def overlaps(a: str | Path, b: str | Path) -> bool:
    """Whether `a` is `b`, lies inside it or holds it, read both as written (made absolute) and with every
    symlink resolved, so a link to either side is caught too (§4.6, §9 invariant 16)."""
    for x, y in ((os.path.abspath(a), os.path.abspath(b)), (os.path.realpath(a), os.path.realpath(b))):
        px, py = Path(x), Path(y)
        if px == py or px.is_relative_to(py) or py.is_relative_to(px):
            return True
    return False


def check_transcripts(root: str | Path, transcript_roots: list[Path]) -> None:
    """Refused at the host agent's start (§4.6, §9 invariant 16, TD-1945): a `scratch_root` inside, or holding, a
    tool's transcript store, which the disk sweep would otherwise weigh as scratch."""
    for t in transcript_roots:
        if overlaps(root, t):
            raise ScratchError(
                f"scratch_root {str(root)!r} is inside or holds {str(t)!r}, where a tool keeps its transcripts: "
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
GIT_WORK = "git work"
GIT_STEP = 20.0  # each git read's own timeout


def _git_dirs(path: Path) -> list[tuple[str, Path]]:
    """Every git store under `path`, not following a symlink: (`clone`, its directory) for a `.git` directory or a
    bare repo (a directory holding `HEAD`, `objects` and `refs`), (`worktree`, its directory) for a `.git` file. A
    store's own insides are not walked. Raises OSError where a directory cannot be read: kept as *git work*."""
    found: list[tuple[str, Path]] = []
    todo = [path]
    while todo:
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
                todo.append(Path(e.path))
    return found


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


def git_work(path: str | Path) -> bool:
    """Whether a scratch directory holds git work and is kept (*git work*, §4.6): any store under it that holds
    some, or a tree or store that cannot be read."""
    try:
        stores = _git_dirs(Path(path))
    except OSError:
        return True
    return any(_store_holds(kind, d) for kind, d in stores)


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


def _newest_write(path: Path) -> float:
    """The newest modification time of anything under `path`, itself included, not following a symlink; an entry
    that cannot be read counts as written now, so it never ages a directory past its hour."""
    newest = path.lstat().st_mtime
    todo = [path]
    while todo:
        try:
            entries = list(os.scandir(todo.pop()))
        except OSError:
            return time.time()
        for e in entries:
            try:
                newest = max(newest, e.stat(follow_symlinks=False).st_mtime)
                if e.is_dir(follow_symlinks=False):
                    todo.append(Path(e.path))
            except FileNotFoundError:
                continue
            except OSError:
                return time.time()
    return newest


def _remove(path: Path) -> None:
    """Remove a scratch directory whole, a symlink inside it as a link, read-only directories made writable."""
    import shutil

    def again(fn, p, _exc):
        with contextlib.suppress(OSError):
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
    one naming another home that exists is kept *another home*, its bytes that home's."""
    import logging
    import shutil

    log = logging.getLogger(__name__)
    p = parent(root)
    kept: list[tuple[str, str]] = []
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
    for e in entries:
        path = Path(e.path)
        if not _under(path, p) or e.is_symlink() or not e.is_dir(follow_symlinks=False):
            continue
        try:
            if e.stat(follow_symlinks=False).st_uid != os.getuid():
                continue
            got = owner(path)
            if not got or not isinstance(got.get("home"), str):
                _keep(kept, tally, path, "no owner")
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
                    _measure_once(tally, path, ended is None)
                    continue
            elif now_s - _newest_write(path) < UNNAMED_AFTER_S:
                _measure_once(tally, path, False)
                continue
            if live_now(str(path)):
                _keep(kept, tally, path, "live record")
                continue
            if any(overlaps(path, t) for t in transcript_roots):
                _keep(kept, tally, path, "transcripts")
                continue
            if git_work(path):
                _keep(kept, tally, path, GIT_WORK)
                continue
            mains = _worktree_mains(path)
            if live_now(str(path)):  # read again just before the removal: the weigh can take a while
                _keep(kept, tally, path, "live record")
                continue
            size = None
            if tally is not None:
                size = tally.measure(path, deadline=diskbook.deadline())  # None past it: removed as last measured
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
