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
from pathlib import Path

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
