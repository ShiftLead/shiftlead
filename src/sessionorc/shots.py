"""A look's screenshots, read where the repo is (design §4.5a **Inbox row: a look**, §4.10 *A look*,
*A look's shots are the pushed commit's*; TD-292 slice 3, TD-300, TD-1307): one `.png` of
`docs/mockups/reviews/` of a checkout in this host's registry, and nothing else. The page serves this
host's from here, and asks another host's through the home (`host_shot`, the link's `shot`), so a
look whose sender runs on a node draws its images too.

A look names the commit it was sent at (`shots_at`) and the origin branch it was pushed to
(`shots_ref`), and a reader draws the first of three that holds the file: the commit's, while some
`refs/remotes/origin/*` contains it; else `origin/<shots_ref>`'s; else `origin/<default>`'s. A miss
on the commit, with a branch, in a presence read (`fetch=True`: the row's test, a node's `head`)
fetches that one branch in the background, at most once a `SHOT_TTL`; until a fetch of the branch
has ended since the commit was first read, such a read answers a miss at once, never the branch
ref's possibly stale file. The image read never fetches. Never the working tree: what a look shows
is what was pushed.
"""

from __future__ import annotations

import base64
import contextlib
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sessionorc import hosts, mail
from sessionorc import ledger as ledger_mod
from sessionorc.models import clean_shots_at, clean_shots_ref

SHOT_DIR = Path("docs") / "mockups" / "reviews"
SHOT_BYTES_MAX = 4 * 1024 * 1024  # one image; a frame on the link is 8 MiB and base64 grows it by a third
SHOT_TTL = 60.0  # seconds a containment answer is kept, and a branch's last fetch bars the next
FETCH_TIMEOUT = 30.0  # seconds one branch's fetch may take


def root_of(repo: str) -> Path | None:
    """The registered checkout of this host named `repo` (its directory's name, as `/repo/<name>`
    and Add entry name a repo), or None — the only checkouts a screenshot is read from."""
    for p in hosts.local_host().repos():
        if repo and Path(p).expanduser().name == repo:
            return Path(p).expanduser().resolve()
    return None


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=10.0)
    except (OSError, subprocess.TimeoutExpired):
        return None


def where(at: Any, ref: Any) -> tuple[str, str]:
    """`(at, ref)` as a reader takes them: each cleaned as the envelope cleans it (§4.10), `ref` read
    only with `at` — a lone `ref` reads `origin/<default>` alone — and "" for absent."""
    a = clean_shots_at(at) or ""
    return a, (clean_shots_ref(ref) or "") if a else ""


# -- the background branch fetch (§4.10 *The fetch never holds a read up*) ------------------------


@dataclass
class _Branch:
    """What a reader keeps per `(checkout, shots_ref)`: `reads`, each commit's last presence read
    (hit or miss; one not read for two `SHOT_TTL`s leaves); `fetched`, the commits a fetch of the
    branch has ended since they were first read; `last_end`, when its last fetch ended; `running`,
    the fetch in flight; `gen`, bumped at every fetch's end, so a presence answer kept elsewhere
    (the page's) is read again at once."""

    reads: dict[str, float] = field(default_factory=dict)
    fetched: set[str] = field(default_factory=set)
    last_end: float = float("-inf")
    running: threading.Thread | None = None
    gen: int = 0


_lock = threading.Lock()
_branches: dict[tuple[str, str], _Branch] = {}
_contained: dict[tuple[str, str, str], tuple[float, bool]] = {}  # (checkout, at, ref) → (when, answer)


def fetch_gen(root: Path, ref: str) -> int:
    """How many fetches of `ref` have ended in `root` since this reader started: a presence answer
    kept under an older count is stale (a fetch's end drops every look on its branch)."""
    with _lock:
        b = _branches.get((str(root), ref))
        return b.gen if b else 0


def _fetch_branch(root: Path, ref: str) -> None:
    """One branch, `--no-prune`, at most `FETCH_TIMEOUT`, never asking for a login. A failed fetch
    ends as a good one does: the branch's kept ref, then the default's file."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    refspec = f"+refs/heads/{ref}:refs/remotes/origin/{ref}"
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(
            ["git", "-C", str(root), "fetch", "-q", "--no-prune", "origin", refspec],
            capture_output=True,
            timeout=FETCH_TIMEOUT,
            env=env,
            stdin=subprocess.DEVNULL,
        )


def _run_fetch(key: tuple[str, str], began: set[str]) -> None:
    try:
        _fetch_branch(Path(key[0]), key[1])
    finally:
        with _lock:
            b = _branches.setdefault(key, _Branch())
            b.fetched |= began & set(b.reads)
            b.last_end = time.monotonic()
            b.running = None
            b.gen += 1
            for k in [k for k in _contained if (k[0], k[2]) == key]:
                del _contained[k]


def _start_fetch(key: tuple[str, str], b: _Branch, now: float) -> None:
    """Start the branch's fetch when none runs and its last ended over `SHOT_TTL` ago; the caller
    holds `_lock`. The commits read so far are the ones its end marks `fetched`."""
    if b.running is not None or now - b.last_end <= SHOT_TTL:
        return
    b.running = threading.Thread(target=_run_fetch, args=(key, set(b.reads)), daemon=True, name=f"shot-fetch {key[1]}")
    b.running.start()


def _note_read(root: Path, at: str, ref: str) -> bool:
    """Record a presence read of `at` on `ref`, start the branch's fetch as §4.10 says, and say
    whether a fetch of the branch has ended since `at` was first read (`fetched`)."""
    key, now = (str(root), ref), time.monotonic()
    with _lock:
        b = _branches.setdefault(key, _Branch())
        for old in [a for a, t in b.reads.items() if now - t > 2 * SHOT_TTL]:
            del b.reads[old]
            b.fetched.discard(old)
        b.reads[at] = now
        done = at in b.fetched
        _start_fetch(key, b, now)  # unset: the first fetch; set: a re-fetch, once `last_end` allows
        return done


def wait_fetches(timeout: float = FETCH_TIMEOUT + 5.0) -> None:
    """Join every fetch in flight (for tests and a clean stop)."""
    with _lock:
        running = [b.running for b in _branches.values() if b.running is not None]
    for t in running:
        t.join(timeout)


def _forget() -> None:
    """Drop every answer, branch and fetch record (a restart's empty reader; tests)."""
    wait_fetches()
    with _lock:
        _branches.clear()
        _contained.clear()


# -- the three steps ------------------------------------------------------------------------------


def _contains(root: Path, at: str, ref: str) -> bool:
    """Whether some `refs/remotes/origin/*` of `root` contains `at`, kept `SHOT_TTL` under
    `(checkout, at, ref)` and dropped when a fetch of `ref` ends. An object the checkout lacks makes
    `--contains` fail, and reads as not contained."""
    key, now = (str(root), at, ref), time.monotonic()
    with _lock:
        got = _contained.get(key)
    if got is not None and now - got[0] <= SHOT_TTL:
        return got[1]
    cp = _git(root, "for-each-ref", "--contains", at, "--format=%(refname)", "refs/remotes/origin")
    held = cp is not None and cp.returncode == 0 and bool(cp.stdout.strip())
    with _lock:
        _contained[key] = (now, held)
    return held


def _size_ok(root: Path, spec: str) -> bool:
    cp = _git(root, "cat-file", "-s", spec)
    if cp is None or cp.returncode != 0:
        return False
    try:
        return int(cp.stdout.strip()) <= SHOT_BYTES_MAX
    except ValueError:
        return False


def locate(root: Path, name: str, at: Any = "", ref: Any = "", fetch: bool = False) -> tuple[str, str]:
    """`(spec, from)`: the first of the three that holds `docs/mockups/reviews/<name>` in `root` at
    most `SHOT_BYTES_MAX` — `<at>:…` while an origin ref contains `at` (`commit`), else
    `origin/<ref>:…` (`ref`), else `origin/<default>:…` (`default`) — or `("", "")`: a name that is
    not a bare `.png` name, a checkout with no origin, a file none of the three holds. With `fetch`
    (a presence read) a miss on the commit with a `ref` records the read and fetches the branch in the
    background as §4.10 says, and answers a miss until a fetch of it has ended since the commit was
    first read; without it (the image read) nothing is fetched and the checkout is read as it is."""
    if not mail.SHOT_NAME.fullmatch(str(name or "")):
        return "", ""
    at, ref = where(at, ref)
    path = (SHOT_DIR / name).as_posix()
    if at:
        if _contains(root, at, ref) and _size_ok(root, f"{at}:{path}"):
            return f"{at}:{path}", "commit"
        if ref:
            if fetch and not _note_read(root, at, ref):
                return "", ""
            if _size_ok(root, spec := f"refs/remotes/origin/{ref}:{path}"):
                return spec, "ref"
    default = ledger_mod.default_ref(root)
    if default is not None and _size_ok(root, spec := f"{default}:{path}"):
        return spec, "default"
    return "", ""


def read_from(root: Path, name: str, at: Any = "", ref: Any = "") -> tuple[bytes | None, str]:
    """The image and which step served it (`commit`, `ref`, `default`), or `(None, "")`. Never fetches."""
    spec, src = locate(root, name, at, ref)
    cp = _git(root, "show", spec) if spec else None
    if cp is None or cp.returncode != 0 or len(cp.stdout) > SHOT_BYTES_MAX:
        return None, ""
    return cp.stdout, src


def read(root: Path, name: str, at: Any = "", ref: Any = "") -> bytes | None:
    """`docs/mockups/reviews/<name>` as `locate` finds it in `root`, or None. Never fetches."""
    return read_from(root, name, at, ref)[0]


def exists(root: Path, name: str, at: Any = "", ref: Any = "", fetch: bool = False) -> bool:
    """Whether `read` would return `docs/mockups/reviews/<name>` in `root` — the row's address test,
    without reading the image; with `fetch`, the presence read that may fetch the branch."""
    return bool(locate(root, name, at, ref, fetch)[0])


def reading(repo: str, name: str, at: Any = "", ref: Any = "", head: bool = False) -> dict[str, Any]:
    """`host_shot`'s reading on this host, and the link's `shot` on a node: `{at, from, exists, png}`
    — `at` the request's, echoed verbatim; `from` the step that served it (`commit`, `ref`,
    `default`; "" when none did); the image in base64, empty with `head`. Only a `head` read (the
    presence test's) fetches. A repo this host does not register reads as not there. Blocking."""
    echo = at if isinstance(at, str) else ""
    root = root_of(repo)
    if root is None:
        return {"at": echo, "from": "", "exists": False, "png": ""}
    if head:
        spec, src = locate(root, name, at, ref, fetch=True)
        return {"at": echo, "from": src, "exists": bool(spec), "png": ""}
    data, src = read_from(root, name, at, ref)
    return {
        "at": echo,
        "from": src,
        "exists": data is not None,
        "png": base64.b64encode(data).decode("ascii") if data else "",
    }
