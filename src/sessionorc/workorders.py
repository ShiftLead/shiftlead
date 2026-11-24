"""Work orders (design §4.4 *Board write-back*, §6 rule 6, TD-380; built — TD-384): every open
*decided* item of a repo's attention board, listed by the repo reading beside the ledger's entries
as **`board:<8 hex>`** — the last eight hex digits of the item's id (`YYYY-MM-DD-<8 hex>`, ledgerboard v3.0,
TD-1881), which a snooze, a reply and the decide itself leave unchanged, and which a split v2 item keeps from its
old `board:<key>` — pickable, High, in every `free-pick` lane of a team servicing the repo, and counted by rule 8,
until a session closes the item.

The board is read in-process through the vendored package `sessionorc.ledgerboard` (design §8 *Which side a thing
lives on*, ADR 2026-10-12, TD-585): its `load_board`, `needs_you` and `item_record`, never a second parser here and
no agent-cadence script, so a repo with a board needs no agent-cadence. A v3 board is a directory, one file per
item (`ref_of`, `find`); the stub `docs/user_attention.md` names it, and a v2 board file still reads.
Origin's side is this module's own fetch (`_against_origin`, §4.5 screen 6 *Boards are read against
origin*): a board merely behind origin is read from origin. A `fyi` item and a closed item are never
work orders; an item whose `Decided` is gone leaves on the next reading.

The board itself is read once, into the repo reading's `boards` (`read_boards`, design §4.4 *Each
reading has one owner*, TD-615), and the orders are a filter over that reading (`orders`)."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import signal
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from sessionorc import gitinfo, ledger, ledgerboard, paths, reports, yamltext

BOARD = Path("docs") / "user_attention.md"  # `board:`'s default (§5 *The seams*): a v3 board's stub, or a v2 file
BOARD_DIR = Path(ledgerboard.BOARD_DIR)  # a v3 board's directory, the default where no stub names it (TD-1881)
NO_BOARD = "no board: the Inbox is the person's channel"  # the seam's fixed words (§5)
PREFIX = "board:"
PR_PREFIX = "pr:"  # a red PR nobody holds (§4.4, TD-613)
FETCH_TIMEOUT = 45.0  # the fetch's bound; a fetch past it is a plain read, *fetch skipped (timeout)*
READ_TIMEOUT = 20.0
TERM_GRACE = 2.0  # a fetch past its bound is sent SIGTERM, then SIGKILL after this
HEAD_MOST = 120
_REF_RE = re.compile(r"board:[0-9a-f]{8}")
_PR_REF_RE = re.compile(r"pr:\d{1,6}")
NO_LINE = "no line {ref} on the board — reworded or closed"
# what a read against origin found (§4.5 screen 6): skipped — no comparison (`why` says why) · none —
# origin has no board · matches · behind — only origin moved, its copy is read · local — only this
# checkout moved · both — both moved, or no common history to tell
FETCH_CASES = ("skipped", "none", "matches", "behind", "local", "both")
# The board's sweep stamps (cadence §3.10), the cadence reader's own (agent-cadence `nudge_user_attention.py`
# `SWEEP_RE` and `SWEEP_DEEP_RE`), ported verbatim so the sweep seat and `/attention` never disagree on
# whether a board is swept (design §4.9b *The sweep*, TD-1090); read from the board's preamble, a v3 board's
# `README.md` (TD-1881)
SWEEP_RE = re.compile(r"^Swept:\s*(?P<date>\d{4}-\d{2}-\d{2})\s*(?:\((?P<meta>[^)]*)\))?", re.MULTILINE)
SWEEP_DEEP_RE = re.compile(r"^Swept-deep:\s*(?P<date>\d{4}-\d{2}-\d{2})\s*(?:\((?P<meta>[^)]*)\))?", re.MULTILINE)


def is_work_order(ref: str) -> bool:
    """Whether a reference names a board line's work order: `board:` and eight hex digits."""
    return bool(_REF_RE.fullmatch(str(ref)))


def is_pr_order(ref: str) -> bool:
    """Whether a reference names a red PR's work order: `pr:` and the PR's number (TD-613)."""
    return bool(_PR_REF_RE.fullmatch(str(ref)))


def ref_of(item: ledgerboard.BoardItem) -> str:
    """`board:<8 hex>` of a board item — **every board item's id** (design §4.4 *A board line's id*, TD-603;
    ledgerboard v3.0, TD-1881): the last eight hex digits of its id, which no edit moves and which a split v2 item
    keeps from its old `board:<key>`, so a persisted reference still names it. A v2 line with no date has no id:
    its line's key's eight hex (the v2 derivation). Empty for an item with neither. The one derivation the Inbox's
    board rows, the write-back's presses, `ao board show`, `ao repo` and the work orders all use."""
    if item.id:
        return PREFIX + item.id[-8:]
    if not item.path and item.raw.strip():
        try:
            return PREFIX + ledgerboard.key_id(ledgerboard.item_key(item.raw.splitlines()[0]))
        except Exception:  # noqa: BLE001 — a line the key cannot take has no reference
            return ""
    return ""


def find(board: ledgerboard.Board, want: str) -> ledgerboard.BoardItem | None:
    """The item of `board` whose reference (`ref_of`) is `want`, a `board:<8 hex>`: the open items first, then
    the closed ones (the archive read before reporting none, TD-1881); None when no item holds it."""
    if not is_work_order(want):
        return None
    return next((it for it in [*board.items, *board.closed] if ref_of(it) == want), None)


def load(root: Path | str, rel: Path | str | None = None) -> ledgerboard.Board:
    """The board of the working tree `root` at `rel` (default `board_path`'s), read whole through ledgerboard's
    `load_board()` (v3.0, TD-1881): a stub follows to its directory, a directory reads its archive, a v2 file its
    archive beside it. `rel` may be absolute (a write-back's tree). No board is an empty Board, `form` None."""
    if rel is None:
        rel = board_path(root)[1]
        if rel is None:
            return ledgerboard.Board(None, "", None)
    return ledgerboard.load_board(Path(rel).as_posix(), *ledger.fs_io(root))


def load_at(root: Path | str, at: str, rel: Path | str) -> ledgerboard.Board | None:
    """The board at `rel` in the tree of `at` (a commit or ref) in `root`, read whole (v3.0, TD-1881), or None when
    git cannot list that tree."""
    rel = PurePosixPath(Path(rel).as_posix())
    parent = rel.parent.as_posix()
    io = ledger.git_io(root, at, "" if parent == "." else parent, rel="" if parent != "." else rel.stem)
    return ledgerboard.load_board(rel.as_posix(), *io) if io is not None else None


def head(text: str) -> str:
    """A line's head text, the work order's title: its bold head where it has one, else what
    follows the `(session …) —` lead, clipped."""
    out = ledgerboard.bold_head(text) or text.split(" — ", 1)[-1]
    out = " ".join(out.split()).rstrip(" .")
    return out if len(out) <= HEAD_MOST else out[: HEAD_MOST - 1].rstrip() + "…"


@dataclass
class Origin:
    """What one board's read against origin found: `case` (`FETCH_CASES`), `note` — the sentence for
    people, in the phrases the Inbox's origin note reads (§4.5a **origin note**) — `why` for a skip,
    `content`/`source` when origin's copy is the one to read (*behind*: `content` origin's `Board`), and `theirs`,
    origin's `Board` in every case that read it, whichever copy is shown — the sweep stamp is read from it (§4.9b
    *The sweep*). A board is compared as the files it is (`board_files`), never one file's text (TD-1881)."""

    case: str
    note: str
    why: str | None = None
    content: ledgerboard.Board | None = None
    source: str | None = None
    theirs: ledgerboard.Board | None = None


def _git(root: Path, args: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    """One git call under `root`, bounded: never a prompt, ssh in batch mode; past `timeout` its
    process group — git and the ssh or helper it started, which hold the pipes — is sent SIGTERM,
    then SIGKILL, and `TimeoutExpired` raised."""
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=5",
        **(gitinfo.READ_ONLY_ENV if args[:1] == ["status"] else {}),
    }
    argv = ["git", "-C", str(root), *args]
    with subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        start_new_session=True,
    ) as p:  # fmt: skip
        try:
            out, err = p.communicate(timeout=max(timeout, 0.0))
        except subprocess.TimeoutExpired:
            # the group this call started, and nothing else: SIGTERM, a grace for git, then SIGKILL to
            # whatever of the group is left — an ssh that ignored the SIGTERM outlives git otherwise
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(p.pid, sig)
                except (ProcessLookupError, PermissionError):
                    break
                if sig == signal.SIGTERM:
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        p.wait(timeout=TERM_GRACE)
            p.wait()
            raise subprocess.TimeoutExpired(argv, timeout) from None
        return subprocess.CompletedProcess(argv, p.returncode, out, err)


def default_branch(root: Path) -> str:
    """The repo's default branch: the first of origin/HEAD's target, `init.defaultBranch`, `main`
    and `master` that origin has, else `main` (agent-cadence's rule, cadence §9)."""
    got = _git(root, ["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], READ_TIMEOUT)
    named = got.stdout.decode().strip().removeprefix("origin/") if got.returncode == 0 else ""
    cfg = _git(root, ["config", "init.defaultBranch"], READ_TIMEOUT)
    configured = cfg.stdout.decode().strip() if cfg.returncode == 0 else ""
    for b in (named, configured, "main", "master"):
        if b and _git(root, ["rev-parse", "--verify", "-q", f"refs/remotes/origin/{b}"], READ_TIMEOUT).returncode == 0:
            return b
    return "main"


_FETCH_LOCKS: dict[str, threading.Lock] = {}
_FETCH_LOCKS_LOCK = threading.Lock()


def fetch_lock(root: Path | str) -> threading.Lock:
    """The home's one lock per checkout around each `git fetch` it runs there or in its board tree (§4.4 *The
    ledger is read against origin*, TD-1471), held around the fetch alone: the tick's fetch and a press's never
    race for the ref's lock, so a press never fails as *origin unreachable* on the tick's fetch."""
    key = str(Path(root))
    with _FETCH_LOCKS_LOCK:
        return _FETCH_LOCKS.setdefault(key, threading.Lock())


def refspec(branch: str) -> str:
    """The explicit refspec every fetch the compares rely on uses: a narrowed `remote.origin.fetch` still moves,
    or makes, `origin/<branch>` (`fetch origin <branch>` alone moves only FETCH_HEAD there)."""
    return f"+refs/heads/{branch}:refs/remotes/origin/{branch}"


@dataclass
class Fetched:
    """One fetch of the default branch (`fetch_origin`): `ok`, `why` it failed, the `branch` fetched, and `moved`
    — `origin/HEAD` names another branch than `branch`, or `origin/<branch>` is gone — so a caller that keeps the
    branch's name drops it."""

    ok: bool
    branch: str
    why: str | None = None
    moved: bool = False


def fetch_origin(root: Path | str, branch: str | None = None, timeout: float = FETCH_TIMEOUT) -> Fetched:
    """Fetch `origin`'s default branch into `origin/<branch>` with the explicit refspec, never `--prune`, no local
    branch or working file moved, under `fetch_lock(root)` (§4.4 *The ledger is read against origin*, TD-1471).
    Never raises: a fetch that fails or passes its bound is `ok` False with its `why`."""
    root = Path(root)
    try:
        branch = branch or default_branch(root)
        with fetch_lock(root):
            got = _git(root, ["fetch", "-q", "--no-prune", "origin", refspec(branch)], timeout)
        if got.returncode != 0:
            err = got.stderr.decode("utf-8", errors="replace").strip().splitlines()
            return Fetched(False, branch, why=err[-1] if err else "git fetch failed")
        head = _git(root, ["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], READ_TIMEOUT)
        named = head.stdout.decode().strip().removeprefix("origin/") if head.returncode == 0 else ""
        have = _git(root, ["rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}"], READ_TIMEOUT)
        return Fetched(True, branch, moved=bool(named and named != branch) or have.returncode != 0)
    except subprocess.TimeoutExpired:
        return Fetched(False, branch or "", why="timeout")
    except Exception as e:  # noqa: BLE001 — a read without origin beats no read
        return Fetched(False, branch or "", why=str(e))


def board_files(rel: Path | str) -> list[str]:
    """The paths a board at `rel` is, POSIX strings relative to the repo's root (ledgerboard v3.0, TD-1881): a
    `.md` path is the stub or v2 file, its v2 archive beside it (`archive_rel`) and the directory its name less
    `.md` names; any other path the directory alone. What a compare of two trees' boards, and a filing PR, reads."""
    rel = Path(rel)
    if rel.suffix != ".md":
        return [rel.as_posix()]
    return [rel.as_posix(), archive_rel(rel).as_posix(), rel.with_suffix("").as_posix()]


def _blob_sha(data: bytes) -> str:
    """git's blob id of `data` (sha1 of `blob <n>\\0` and the bytes): a working file compared with a tree's."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _local_tree(root: Path, rel: Path | str) -> list[tuple[str, str]]:
    """The board's files in the working tree of `root` (`board_files`), as sorted `(path, blob id)`."""
    out: list[tuple[str, str]] = []
    for name in board_files(rel):
        p = root / name
        files = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else []
        for f in files:
            try:
                out.append((f.relative_to(root).as_posix(), _blob_sha(f.read_bytes())))
            except OSError:
                continue
    return sorted(out)


def board_stamp(root: Path | str) -> list[int] | None:
    """What the checkout's board was last read at, for a clock that re-reads only a moved board (design §4.4 *Each
    reading has one owner*, TD-615): `[newest mtime_ns, total size, file count]` over its files (`board_files`: a v3
    board's directory too, where an edit moves an item's file and no stub, TD-1881), or None for no board."""
    root = Path(root)
    rel = board_path(root)[1]
    if rel is None:
        return None
    newest = size = count = 0
    for name in board_files(rel):
        p = root / name
        for f in [p] if p.is_file() else p.rglob("*") if p.is_dir() else []:
            try:
                st = f.stat()
            except OSError:
                continue
            newest, size, count = max(newest, st.st_mtime_ns), size + st.st_size, count + 1
    return [newest, size, count] if count else None


def _tree_at(root: Path, at: str, rel: Path | str) -> list[tuple[str, str]] | None:
    """The board's files in the tree of `at` (`board_files`), as sorted `(path, blob id)`; None where git cannot
    list it."""
    got = _git(root, ["ls-tree", "-r", "-z", "--full-tree", at, "--", *board_files(rel)], READ_TIMEOUT)
    if got.returncode != 0:
        return None
    out: list[tuple[str, str]] = []
    for rec in got.stdout.decode("utf-8", errors="replace").split("\0"):
        meta, tab, path = rec.partition("\t")
        if tab and meta.split()[1:2] == ["blob"]:
            out.append((path, meta.split()[2]))
    return sorted(out)


def _against_origin(root: Path, board: Path, timeout: float = FETCH_TIMEOUT, fetched: Fetched | None = None) -> Origin:
    """The checkout's board against `origin/<default>` (§4.5 screen 6 *Boards are read against
    origin*), never raising: one fetch of the default branch alone (`fetch_origin`) — or none, where the
    caller fetched already and hands its outcome in `fetched` (the repo reading's pass, TD-1471) — then the
    three-way compare of the checkout's board, origin's and their merge-base's, each the board's files and their
    blobs (`board_files`: a v3 board's directory, or a v2 file and its archive, TD-1881). Merely behind (the
    checkout's untouched since the merge-base) reads origin's copy; anything else reads the checkout's and says
    which way it differs. A failed fetch reads the checkout's, *fetch skipped (<why>)*."""
    try:
        fetched = fetched or fetch_origin(root, timeout=timeout)
        if not fetched.ok:
            why = fetched.why or "git fetch failed"
            return Origin("skipped", f"fetch skipped ({why})", why=why)
        branch = fetched.branch
        at = f"origin/{branch}"
        rel = board.relative_to(root) if board.is_relative_to(root) else board_rel(root)
        theirs_tree = _tree_at(root, at, rel)
        theirs = load_at(root, at, rel) if theirs_tree else None
        if not theirs_tree or theirs is None or theirs.form is None:
            return Origin("none", f"fetched; no board at {at}")
        ours = _local_tree(root, rel)
        if theirs_tree == ours:
            return Origin("matches", f"fetched; board matches {at}", theirs=theirs)
        mb = _git(root, ["merge-base", "HEAD", at], READ_TIMEOUT)
        if mb.returncode != 0:
            note = f"fetched; board DIFFERS from {at} (no common history to compare) — showing local"
            return Origin("both", note, theirs=theirs)
        base = _tree_at(root, mb.stdout.decode().strip(), rel) or []
        if ours == base:
            note = f"fetched; local clone is behind — showing {at}'s board"
            return Origin("behind", note, content=theirs, source=at, theirs=theirs)
        if theirs_tree == base:
            return Origin("local", f"fetched; board DIFFERS from {at} (local edits not pushed)", theirs=theirs)
        return Origin("both", f"fetched; board DIFFERS from {at} (both sides changed) — showing local", theirs=theirs)
    except subprocess.TimeoutExpired:
        return Origin("skipped", "fetch skipped (timeout)", why="timeout")
    except Exception as e:  # noqa: BLE001 — a board read without origin beats no board
        return Origin("skipped", f"fetch skipped ({e})", why=str(e))


def board_path(root: Path | str) -> tuple[str, Path | None]:
    """The checkout's board (§5 *The seams* `board:`, TD-587): `("set", path)` for its `.shiftlead.yml`
    `board:`, relative to `root`; `("defaulted", BOARD)` when the key is unset and `docs/user_attention.md` (a v3
    board's stub, or a v2 file) exists, `("defaulted", BOARD_DIR)` when only the directory `docs/user_attention/`
    does (ledgerboard v3.0, TD-1881); `("absent", None)` otherwise — the person's channel is the Inbox alone. A
    file that cannot be read, or a key that is not a non-empty string or is not a path inside the repo (absolute,
    or with a `..`: the write-back edits it in a tree of its own), is the key unset: the clients
    (`shiftlead.repoconfig`) refuse such a file by name."""
    try:
        doc = yamltext.load(paths.repo_file(root).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        doc = None
    got = doc.get("board") if isinstance(doc, dict) else None
    if isinstance(got, str) and got.strip() and inside(Path(got.strip())):
        return "set", Path(got.strip())
    if (Path(root) / BOARD).is_file():
        return "defaulted", BOARD
    if (Path(root) / BOARD_DIR).is_dir():
        return "defaulted", BOARD_DIR
    return "absent", None


def inside(rel: Path) -> bool:
    """Whether `rel` is a path from a repo's root that stays inside it: relative, with no `..`."""
    return not rel.is_absolute() and ".." not in rel.parts


def board_rel(root: Path | str) -> Path:
    """The board's path under `root` that the write-back edits on origin's head: `board_path`'s, else
    `docs/user_attention.md` — the checkout may lack a file origin holds."""
    return board_path(root)[1] or BOARD


def filing_paths(root: Path | str) -> list[str]:
    """The paths a filing PR touches alone (design §4.4 *A filing PR nobody holds is a work order*, TD-1810),
    POSIX strings relative to `root`: the ledger (`ledger.ledger_path`, a v2 directory with its `archive/`, or a
    v1 file) and its archive file (`ledger.archive_path`, always, with no layout test — a path that names
    nothing matches nothing), the board (`board_rel`) and the board's archive (`archive_rel`). The tick hands
    them to `reports.pr_reading` as `filing=`. The board is
    its files (`board_files`): a v3 board's directory too (TD-1881)."""
    led = ledger.ledger_path(root)
    archive = Path(ledger.archive_path(led)).as_posix()
    return [Path(led).as_posix(), archive, *board_files(board_rel(root))]


def _stamp(rx: re.Pattern[str], content: str) -> str | None:
    """The first line of `content` that `rx` matches with a date, as `YYYY-MM-DD` — None when there is
    none, or its date is not a calendar date (it reads as absent: the sweep rewrites it)."""
    m = rx.search(content)
    if m is None:
        return None
    try:
        return date.fromisoformat(m.group("date")).isoformat()
    except ValueError:
        return None


def swept(board: ledgerboard.Board | str) -> dict[str, str | None]:
    """A board's sweep stamps (design §4.9b *The sweep*, TD-1090): `{at, deep_at}`, each the date of
    the first `Swept:` / `Swept-deep:` line carrying one, or None — `{at: None}` is a board never swept. Read from
    a `Board`'s preamble (a v3 board's `README.md`, a v2 file's text above its first item, TD-1881), or a
    preamble's text."""
    content = board.preamble if isinstance(board, ledgerboard.Board) else board
    return {"at": _stamp(SWEEP_RE, content), "deep_at": _stamp(SWEEP_DEEP_RE, content)}


def board_items(board: ledgerboard.Board, today: date) -> list[dict[str, Any]]:
    """The open items of a board, each ledgerboard's `item_record` with its reference as `key` (`ref_of`), its
    class in ledgerboard's `needs_you` as `needs` (v2.3, TD-1330) — None for an item hidden today (a
    `Hide until:` still ahead), which the Inbox leaves out (design §4.4 *Board write-back*) — and `at`, its place
    among the board's items, 1 first (v3.0: an item has no line, TD-1881)."""
    needs = {id(it): cls for it, cls, _ in ledgerboard.needs_you(board, today)}
    return [
        {**ledgerboard.item_record(it, today), "key": ref_of(it), "needs": needs.get(id(it)), "at": n}
        for n, it in enumerate(board.items, 1)
    ]


_ID = rf"(?:{ledgerboard.REPO}#)?TD-\d+"
# a `Closed:` reason's leading *carried to* or *see* ids (§4.4 *The boards*, TD-1368; *see* TD-1528), either case of
# the first letter: joined only by `,`, `and` or `&`, ending at the first other word, dash, colon or sentence end —
# *carried to TD-9 — see TD-4* is TD-9, *see TD-1525: the bought sixth round* is TD-1525
_JOIN = r"(?:\s*,\s*(?:(?:and|&)\s+)?|\s+(?:and|&)\s+)"
CARRIED_RE = re.compile(rf"^[\s—–-]*(?:[Cc]arried to|[Ss]ee)\s+(?P<ids>{_ID}(?:{_JOIN}{_ID})*)")
_ID_RE = re.compile(_ID)
# a v2 board's archive file beside the board's (§4.4 *The boards*): `<board stem>_archive.md`
ARCHIVE_SUFFIX = "_archive"


def archive_rel(board: Path) -> Path:
    """A v2 board archive's path beside `board`'s: `docs/user_attention.md` → `docs/user_attention_archive.md`."""
    return board.with_name(f"{board.stem}{ARCHIVE_SUFFIX}{board.suffix}")


def carried_to(reason: str) -> list[str]:
    """The ids a `Closed:` reason's leading *carried to* or *see* lists, as written, each once — [] for any other
    reason (§4.4 *The boards*, TD-1368; *see*, the form sessions came to write, read as the same words, TD-1528)."""
    m = CARRIED_RE.match(reason)
    return list(dict.fromkeys(x.group(0) for x in _ID_RE.finditer(m.group("ids")))) if m else []


def carried(board: ledgerboard.Board) -> list[dict[str, Any]]:
    """The closed decided items that may still hold a member (§4.4 *The boards* `carried`, *The card's status*,
    TD-1368): every closed `decide` item with a `Decided` whose `Context` names an entry, the board's closed items
    read whole (its archive too), as `{key, ref, decided, decided_by, closed, to, at, refs, parts, gate}`, and
    `decided_delegate` and `decided_scope` for a delegated answer alone (v3.4, TD-1939) — `ref` the
    `Context`'s first entry ref, `refs` all of them (gate words after a ref read past), `parts` its `Parts` ids,
    `gate` the `Context`'s one gate or None (`_context_gate`, TD-2026), `closed` `{date, why}` (the item's `Closed`
    fields, ledgerboard v3.0, TD-1881: `why` '' for none), `to` the
    reason's *carried to* or *see* ids, and `at` one index over every item of the board — the open items', then the
    closed ones' after the last open one's."""
    out: list[dict[str, Any]] = []
    base = len(board.items)
    for n, it in enumerate(board.closed, base + 1):
        if it.kind != "decide" or it.decided is None or it.closed is None:
            continue
        refs = [r for r in ledgerboard.context_refs(it.context or "") if _ID_RE.fullmatch(r)]
        if not refs:
            continue
        day, why = it.closed
        why = (why or "").strip()
        out.append(
            {
                "key": ref_of(it),
                "ref": refs[0],
                "decided": {"text": it.decided[0], "date": it.decided[1].isoformat()},
                "decided_by": it.decided_by,
                **(
                    {"decided_delegate": it.decided_delegate, "decided_scope": it.decided_scope}
                    if it.decided_delegate
                    else {}
                ),
                "closed": {"date": day.isoformat() if day else "", "why": why},
                "to": carried_to(why),
                "at": n,
                "refs": refs,
                "parts": list(it.parts),
                "gate": ledgerboard._context_gate(it.context or "")[1],  # its Context's one gate (TD-2026)
            }
        )
    return out


def read_boards(
    root: str | Path, *, fetch: bool = True, board: str | Path | None = None, fetched: Fetched | None = None
) -> dict[str, Any]:
    """The repo's board as the host agent keeps it (design §4.4 *Each reading has one owner*, *The
    boards*, TD-615), read in-process through ledgerboard (TD-585), whole, by `load_board()` (v3.0, TD-1881):
    `{boards: [...], today}`, each board `{label, board, root, source, fetch_note, fetch_case, fetch_why, items,
    people}` — and `swept`, once it was read against origin (below) — `people` its `People:` names (`board_people`,
    None for no such line, TD-1831), and each open item ledgerboard's record of it (`id`, `path`, text — its words —
    due, answers, decided, context, refs, session, detail, …) with its reference beside it as `key` (`board:<8 hex>`,
    `ref_of`, *A board line's id*) — or `{error}` when the board could not be read:
    one newer than this ledgerboard reads (`version_problem`), or a stub whose directory is missing. No board is no
    boards and no error. `fetch` reads against origin (`_against_origin`, *Boards are read against origin*); a
    fetch that fails or passes its bound reads the checkout's board, its `fetch_note` *fetch skipped (<why>)*, so
    the page says origin could not be reached.

    `board` reads the board at that path (a stub, a v2 file or a directory) in place of the checkout's, named as
    the checkout's board read from origin: the host agent's own tree after a write-back (`board.tree_dir`), which
    is origin's head with the press landed, so the press is in the reading before the checkout pulls it.

    `carried` (§4.4 *The boards*, TD-1368) is the board's closed decided items (`carried`), read from the same copy
    as the open ones — origin's where origin's board is the one read.

    `swept` (§4.9b *The sweep*, TD-1090) is the stamp of origin's copy, whichever copy is shown: written
    only by a read against origin — `{at, deep_at}` (`swept`), or None when origin holds no board — and
    by `board`, the tree a write-back pushed. A read of the checkout alone (no fetch, or a fetch
    skipped) has no `swept` key, and the caller carries the last one forward.

    `fetched` is the outcome of the fetch the caller ran (the repo reading's pass fetches before it reads the
    ledger, TD-1471): the read against origin reuses it and fetches nothing."""
    root = Path(root)
    rel = board_path(root)[1]
    if rel is None:
        return {"boards": []}  # NO_BOARD (§5 *The seams*)
    checkout = root / rel
    path = Path(board) if board is not None else checkout
    today = datetime.now().date()  # the board's dates are civil dates, local
    found = _against_origin(root, checkout, fetched=fetched) if fetch and board is None else None
    if found is not None and found.content is not None:
        read = found.content
    else:
        read = load(root, path if board is not None else rel)
        if read.form is None:
            if read.problems:
                return {"error": f"{path} could not be read ({read.problems[0][1]})"}
            return {"boards": []}
    why = ledgerboard.version_problem(read)
    if why:
        return {"error": f"{path} could not be read ({why})"}
    items = board_items(read, today)
    try:
        held = carried(read)
    except Exception:  # noqa: BLE001 — an item ledgerboard cannot read holds nothing; the board still reads
        held = []
    b: dict[str, Any] = {
        "label": root.name,
        "board": str(checkout),
        "root": str(root),
        "source": found.source if found is not None and found.content is not None else None,
        "fetch_note": found.note if found is not None else None,
        "fetch_case": found.case if found is not None else None,
        "fetch_why": found.why if found is not None else None,
        "items": items,
        "carried": held,
        # its `People:` names (TD-1831): a row's case (d) reads them as ledgerboard's `covers()` does
        "people": ledgerboard.board_people(read),
    }
    if found is not None and found.case != "skipped":
        b["swept"] = swept(found.theirs) if found.theirs is not None else None
    if board is not None:
        # as the checkout's board, read from origin: the *behind* case (§4.5a **origin note**)
        b.update(source="origin", fetch_case="behind", swept=swept(read))
    return {"boards": [b], "today": today.isoformat()}


def orders(reading: dict[str, Any]) -> list[dict[str, Any]]:
    """The work orders of a `read_boards` reading — its open decided items that are not `fyi`, each
    `{id, title, text, context, decided: {text, date[, delegate, scope]}, refs, session, kind}` — `text` the item's
    words, `context` its `Context` (ledgerboard v3.0, TD-1881), `decided` gaining `delegate` and `scope` for a
    delegated answer alone (v3.4, TD-1939) — a filter over the one reading, never a second read of the board
    (§4.4 *The boards*)."""
    out: list[dict[str, Any]] = []
    for b in reading.get("boards") or []:
        for it in (b.get("items") or []) if isinstance(b, dict) else []:
            if not isinstance(it, dict) or not isinstance(it.get("decided"), dict) or it.get("kind") == "fyi":
                continue
            if not it.get("key") or not it.get("text"):
                continue
            out.append(
                {
                    "id": it["key"],
                    "title": head(str(it["text"])),
                    "text": str(it["text"]),
                    "context": it.get("context"),
                    "decided": {
                        "text": str(it["decided"].get("text") or ""),
                        "date": it["decided"].get("date"),
                        **(
                            {"delegate": it["decided_delegate"], "scope": it.get("decided_scope")}
                            if it.get("decided_delegate")
                            else {}
                        ),
                    },
                    "refs": [str(r) for r in it.get("refs") or []],
                    "session": it.get("session"),
                    "kind": it.get("kind"),
                }
            )
    return out


def read(root: str | Path, *, fetch: bool = True) -> dict[str, Any]:
    """The repo's work orders: `{orders: [...]}` (`orders`), or `{error}` when the board could not be
    read — `read_boards` and its filter, for a caller that wants the orders alone."""
    got = read_boards(root, fetch=fetch)
    return got if "error" in got else {"orders": orders(got)}


def entry(order: dict[str, Any]) -> dict[str, Any]:
    """A work order as the lanes and the pages read an entry (§4.4 *Repo facts*): High, pickable,
    `free-pick`'s kind, no owner — `owner:<word>` never narrows one out (§6 rule 6) — and marked
    `work_order`, so a reader that counts the ledger's priorities can leave it out."""
    return {
        "id": order["id"],
        "title": order.get("title") or "",
        "priority": "High",
        "owner": "",
        "kind": "",
        "type": "debt",
        "blocked_by": [],
        "pickable": "yes",
        "for_page": "pickable",
        "work_order": True,
        "decided": order.get("decided"),
        "refs": order.get("refs") or [],
        "session": order.get("session"),
        "context": order.get("context"),
        "text": order.get("text") or "",
    }


# the fields the join writes on a stored order (§6 rule 6 *save a design's answer*, TD-1705); `owner` is `entry()`'s own
ROUTED = ("lane", "design", "owner", "for")
ROUTE_WORDS = ("claimed", "done")  # a designer's own word on its design that makes it the order's `for`
_BARE_TD_RE = re.compile(r"TD-\d+")  # this repo's own entry: another repo's design is never routed here


def design_of(order: dict[str, Any]) -> str | None:
    """The design a decided item answers (§6 rule 6 *save a design's answer*, TD-1705): the bare `TD-n` of its
    `Context` where that Context names exactly one entry and exactly one gate, `decision (<any person>)` — read
    from the order's `context` as ledgerboard reads an item's gate (v3.0, TD-1881), since `refs` holds bare ids;
    else None."""
    ref, gate = ledgerboard._context_gate(str(order.get("context") or ""))
    if ref is None or gate is None or not gate.startswith("decision (") or not _BARE_TD_RE.fullmatch(ref):
        return None
    return ref


def _routed(order: dict[str, Any], designs: dict[str, dict[str, Any]], designers: list[dict[str, Any]]) -> dict:
    """The routed fields one order should carry (`join`): `{owner: ""}` for one that stays `free-pick`'s."""
    d = design_of(order)
    if d is None or d not in designs:
        return {"owner": ""}
    owner = str(designs[d].get("owner") or "")
    probe = {**{k: v for k, v in order.items() if k not in ROUTED}, "lane": "design-first", "owner": owner}
    dec = order.get("decided") if isinstance(order.get("decided"), dict) else {}
    answer = {"text": str(dec.get("text") or ""), "date": dec.get("date")}
    reach = [
        x
        for x in designers
        if ledger.lane_matches(list(x.get("lane") or []), probe, None, x.get("id"))
        and ((x.get("released") or {}).get(order["id"]) or {}).get("at_drop") != answer
    ]
    if not reach:
        return {"owner": ""}
    words = [(str(w[1]), x["id"]) for x in reach if (w := (x.get("words") or {}).get(d)) and w[0] in ROUTE_WORDS]
    got = {"lane": "design-first", "design": d, "owner": owner}
    return {**got, "for": max(words)[1]} if words else got


def join(
    orders: list[dict[str, Any]], entries: list[dict[str, Any]], designers: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The board's stored orders (`entry()`'s) with a design's answer routed (design §6 rule 6 *save a design's
    answer*, TD-1705): a decided line whose one `Context:` gate is `TD-n decision (<who>)` (`design_of`), TD-n an
    open `Kind: design-first` entry of `entries`, goes to the `design-first` lanes where the repo has a designer to
    reach — `designers`, each `{id, lane, released, words}` as the tick reads them: its address, its lane, its
    `released` marks, and its newest progress word on each ref along its line of successors as `(status, at)`. One
    whose lane takes the order and whose `released` mark for it was not written at its present answer is to reach.
    A routed order carries `lane: "design-first"`, `design`, `owner` (the design's `Owner:`) and, where a designer
    to reach last said `claimed` or `done` on the design, `for`: the newest such designer's address. Any other
    order carries none of them, its `owner` `entry()`'s empty one. An order whose fields already read so is the
    same object, so a caller that compares sees no change."""
    designs = {str(e["id"]): e for e in entries if isinstance(e, dict) and e.get("kind") == "design-first"}
    out = []
    for o in orders:
        if not isinstance(o, dict) or not o.get("id"):
            out.append(o)
            continue
        want = _routed(o, designs, designers)
        cur = {k: o[k] for k in ROUTED if k in o}
        out.append(o if cur == want else {**{k: v for k, v in o.items() if k not in ROUTED}, **want})
    return out


def carry(orders: list[dict[str, Any]], was: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`orders` with the routed fields `was` holds for each id (`ROUTED`), where the join cannot be made (a ledger
    reading that carries `error`, TD-1705): a fresh read of the board keeps the stored routing, an order `was` does
    not hold keeps its own fields, and one whose fields already read so is the same object."""
    by_id = {o["id"]: o for o in was if isinstance(o, dict) and o.get("id")}
    out = []
    for o in orders:
        old = by_id.get(o.get("id")) if isinstance(o, dict) else None
        if old is None:
            out.append(o)
            continue
        want, cur = {k: old[k] for k in ROUTED if k in old}, {k: o[k] for k in ROUTED if k in o}
        out.append(o if want == cur else {**{k: v for k, v in o.items() if k not in ROUTED}, **want})
    return out


def shown_board(root: str | Path, *, fetch: bool = True) -> tuple[ledgerboard.Board | None, str]:
    """The board under the checkout `root`, read whole, and where it was read: origin's default branch after a
    fetch (`origin/<branch>`), else the checkout's (`checkout`) — design §4.7 `ao board show` (v3.0: a `Board`,
    never its lines, TD-1881). No board is `(None, "")`."""
    root = Path(root)
    rel = board_path(root)[1]
    if rel is None:
        return None, ""
    if fetch:
        try:
            # a fetch that failed leaves origin's ref as stale as the checkout: the checkout it is
            with fetch_lock(root):
                fetched = subprocess.run(
                    ["git", "-C", str(root), "fetch", "-q", "origin"], capture_output=True, timeout=FETCH_TIMEOUT
                )
            cp = subprocess.run(
                ["git", "-C", str(root), "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"],
                capture_output=True, text=True, timeout=READ_TIMEOUT,
            )  # fmt: skip
            heads = [cp.stdout.strip()] if cp.stdout.strip() else ["origin/main", "origin/master"]
            for head in heads if fetched.returncode == 0 else ():
                got = load_at(root, head, rel)
                if got is not None and got.form is not None:
                    return got, head
        except (OSError, subprocess.SubprocessError):
            pass
    got = load(root, rel)
    return (got, "checkout") if got.form is not None else (None, "")


def show(root: str | Path, want: str, *, fetch: bool = True) -> dict[str, Any] | None:
    """The item of the board under `root` whose reference is `want` (design §4.7 `ao board show`, `find`): `{key,
    id, path, text, detail, open, source}` — `text` its words, `path` its file in the board's directory ('' for a v2
    item), `detail` its detail block — open or closed, the open ones first and the archive read before reporting
    none (v3.0, TD-1881); None when no item holds it. The item shapes are ledgerboard's (design §8): none is
    written here."""
    board, source = shown_board(Path(root), fetch=fetch)
    it = find(board, want) if board is not None else None
    if it is None:
        return None
    return {
        "key": want,
        "id": it.id,
        "path": it.path,
        "text": it.words,
        "detail": list(it.detail),
        "open": it.closed is None,
        "source": source,
    }


# -- a red PR nobody holds (design §4.4 *A red PR nobody holds is a work order*, TD-613) -----------


def holds_pr(record: Any, pr: dict[str, Any]) -> bool:
    """Whether a live record holds an open PR: not `exited` or `closed`, not superseded, no
    `out_of_work`, and either a `progress` entry names it (`pr:<n>`, its `pr`, claimed or done, or the
    `review_pr` a claim keeps while its PR is with a reader, TD-150, TD-1701) or its checkout's branch is
    the PR's head."""
    if record.state in ("exited", "closed") or record.superseded_by or record.out_of_work:
        return False
    n = pr.get("number")
    if any(e.ref == f"{PR_PREFIX}{n}" or e.pr == n or e.review_pr == n for e in record.progress):
        return True
    branch = (record.git or {}).get("branch")
    return bool(branch) and branch == pr.get("branch")


def red_holders(
    open_prs: list[dict[str, Any]],
    records: list[Any],
    now: datetime,
    after: timedelta,
    *,
    filing_after: timedelta | None = None,
    key: list[str] | None = None,
    reads: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[str]]:
    """Who holds each red PR past `after`, by number as a string: the names of the live records
    `holds_pr` finds, for the pages' *held by <name>* (TD-652; the reading carries them, so no page
    re-derives the test). A PR nobody holds, or not yet red for `after`, is not listed. With
    `filing_after`, a filing row is gated by `is_filing_order` in place of `red_since` (§4.4 *A filing PR
    nobody holds is a work order*, TD-1811); absent, no filing row is read. A PR the gate sweep opened
    (`reports.gate_head`) is listed while `is_gate_order` passes it, keyed on its stamp with no `after` and
    whatever its checks, in an unserved repo too, and is never read as red or filing (TD-1854)."""
    out: dict[str, list[str]] = {}
    for pr in open_prs:
        if not isinstance(pr, dict) or not isinstance(pr.get("number"), int):
            continue
        if reports.gate_head(pr.get("branch")):
            if is_gate_order(pr, reads) and (held := [str(r.name or r.id) for r in records if holds_pr(r, pr)]):
                out[str(pr["number"])] = held
            continue
        if filing_after is not None and is_filing_order(pr, now, filing_after, key, reads):
            if held := [str(r.name or r.id) for r in records if holds_pr(r, pr)]:
                out[str(pr["number"])] = held
            continue
        since = pr.get("red_since")
        if not since:
            continue
        try:
            red_since = datetime.fromisoformat(str(since))
        except ValueError:
            continue
        if red_since.tzinfo is None:  # a stamp with no offset is UTC, as every stamp in the store is
            red_since = red_since.replace(tzinfo=UTC)
        if now - red_since < after:
            continue
        if held := [str(r.name or r.id) for r in records if holds_pr(r, pr)]:
            out[str(pr["number"])] = held
    return out


def is_sync_order(pr: dict[str, Any]) -> bool:
    """A sync PR the reading can order (design §4.4 *A sync PR is the team's at once*, TD-684): any
    `checks` but *pending*, and *not_run* (CI that never started is the person's, TD-686), which wait —
    unless it is conflicting, when no check will run and a team can cure that part — and one the home
    holds (`sync.mark`'s `sync_home`, §6 *Sync*, TD-685). Every other is an order."""
    waits = pr.get("checks") in ("pending", "not_run") and not pr.get("conflicting")
    # the home's: merged at its head, or green with no verdict there while the switch is on (§6 *Sync*, TD-685)
    waits = waits or bool(pr.get("sync_home"))
    return bool(pr.get("sync")) and bool(pr.get("sync_since")) and not waits


def is_lift_order(pr: dict[str, Any]) -> bool:
    """A lift PR the gate sweep opened (design §4.4 *A PR the gate sweep opens is the team's at once*, TD-1437,
    TD-1854): a head `reports.lift_of` reads (the reading's `lift`, stamped `lift_since` — an `until-<date>`
    head's only from its day), not a draft and not a fork. Whatever its checks, red and pending included:
    its taker runs its precheck and takes the step its head names. Pure: the row's stamps alone."""
    lift = bool(pr.get("lift")) and bool(pr.get("lift_since")) and reports.lift_of(pr.get("branch")) is not None
    return lift and not pr.get("draft") and not pr.get("fork")


def is_sweep_order(pr: dict[str, Any]) -> bool:
    """A sweep PR the gate sweep opened (§4.4, TD-1854): a head `reports.sweep_of` reads (the reading's `sweep`,
    stamped `sweep_since`), not a draft and not a fork, whatever its checks. Pure, as `is_lift_order`."""
    sweep = bool(pr.get("sweep")) and bool(pr.get("sweep_since")) and reports.sweep_of(pr.get("branch")) is not None
    return sweep and not pr.get("draft") and not pr.get("fork")


def read_open(pr: dict[str, Any], reads: dict[str, list[dict[str, Any]]] | None) -> bool:
    """Whether any addressee's read of the PR is open in `reads` (the pass's reads by PR number, the person's
    included, §4.4 *The PR's reads*): an order that waits on its reader is none meanwhile (TD-1811, TD-1854)."""
    got = (reads or {}).get(str(pr.get("number"))) or []
    return any(isinstance(x, dict) and x.get("state") == "open" for x in got)


def _held_names_a_path(pr: dict[str, Any]) -> bool:
    """`held` read at the PR's head and naming a path; an unread one, or one read at another head, counts as
    empty, and one kept from an earlier key as read (§4.4 *What the taker does*, TD-1854)."""
    held = pr.get("held")
    return isinstance(held, list) and bool(held) and bool(pr.get("head")) and pr.get("held_head") == pr.get("head")


def is_gate_order(pr: dict[str, Any], reads: dict[str, list[dict[str, Any]]] | None = None) -> bool:
    """The one test of a PR the gate sweep opened (§4.4 *A PR the gate sweep opens is the team's at once*,
    TD-1854), which `red_prs`, `red_holders` and the reading's `pr_orders.gate` all call: `is_lift_order` or
    `is_sweep_order`, and, where its `held` names a path, no read of it open (`read_open`)."""
    if not isinstance(pr, dict) or not (is_lift_order(pr) or is_sweep_order(pr)):
        return False
    return not (_held_names_a_path(pr) and read_open(pr, reads))


def _instant(stamp: Any) -> datetime | None:
    """A stored stamp as an aware instant (UTC where it has no offset, as every stamp in the store is), else None."""
    try:
        at = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at


def filing_row(pr: dict[str, Any]) -> bool:
    """A row the filing rule reads rather than the red rule (§4.4 *A filing PR nobody holds is a work order*,
    TD-1811): stamped `filing` true, not a sync PR nor one on a head the gate sweep opens (`reports.gate_head`,
    TD-1854), its checks neither *red* nor `not_run`, and not conflicting — a red or conflicting filing PR is
    the red rule's alone, one order, never two."""
    if pr.get("filing") is not True or pr.get("sync") or reports.gate_head(pr.get("branch")):
        return False
    return pr.get("checks") not in ("red", "not_run") and not pr.get("conflicting")


def is_filing_order(
    pr: dict[str, Any],
    now: datetime,
    after: timedelta,
    key: list[str] | None,
    reads: dict[str, list[dict[str, Any]]] | None,
) -> bool:
    """The one test of a filing PR's row (§4.4 *A filing PR nobody holds is a work order*, TD-1811), at every
    call site: `filing_row`, its `filing` read at its head (`filing_head`); with a held `key` (the one the
    reading reads at, `_held_keys`), `held` read at that head and key and empty — unread, it waits; with an
    empty key, no fresh `held` is needed, but a row carrying a non-empty `held`, kept from an earlier key, is
    never one; not a draft or a fork; opened (`created`) at least `after` ago; and no read of it open in
    `reads` (the pass's reads by PR number, any addressee's, the person's included)."""
    if not isinstance(pr, dict) or not isinstance(pr.get("number"), int) or not filing_row(pr):
        return False
    head = pr.get("head")
    if not head or pr.get("filing_head") != head or pr.get("draft") or pr.get("fork"):
        return False
    if key:
        read = pr.get("held_head") == head and list(pr.get("held_key") or []) == list(key)
        if not read or not isinstance(pr.get("held"), list) or pr["held"]:
            return False
    elif pr.get("held"):
        return False
    created = _instant(pr.get("created")) if pr.get("created") else None
    if created is None or now - created < after:
        return False
    return not read_open(pr, reads)


SWEEP_CONTEXT = "the gate sweep's board items"  # a sweep order's words beside its URL (§4.4, TD-1854)


def lift_context(pr: dict[str, Any]) -> str:
    """A lift order's words beside its URL: the gate it lifts on its entry, `lifts TD-n until 2026-11-20`."""
    tid, gate, _ = reports.lift_of(pr.get("branch")) or ("", "", False)
    return f"lifts {tid} {gate}" if tid else ""


def sync_reason(pr: dict[str, Any]) -> str:
    """Why a sync PR waits on someone, in its order's words: the failing checks, *conflicting*,
    *draft*, else *green: review and merge it* — or, where the home judged it (§6 *Sync*), its verdict's `why`."""
    if pr.get("sync_why"):
        return str(pr["sync_why"])
    why = [*(pr.get("failing") or []), *(["conflicting"] if pr.get("conflicting") else [])]
    why += ["CI never ran"] if pr.get("checks") == "not_run" else []
    why += ["draft"] if pr.get("draft") else []
    return ", ".join(why) or "green: review and merge it"


def pr_note(pr: dict[str, Any]) -> str:
    """The one line an idle holder of a red PR, or of a sync PR, is told."""
    if is_sync_order(pr):
        return (
            f"sync PR #{pr['number']} has been open since {pr.get('sync_since')}: {sync_reason(pr)} — fix it or say why"
        )
    if is_lift_order(pr):
        since = pr.get("lift_since")
        return f"lift PR #{pr['number']} has been open since {since}: {lift_context(pr)} — take it or say why"
    if is_sweep_order(pr):
        since = pr.get("sweep_since")
        return f"sweep PR #{pr['number']} has been open since {since}: {SWEEP_CONTEXT} — take it or say why"
    if filing_row(pr):
        return f"filing PR #{pr['number']} has been open since {pr.get('created')}: merge it or say why"
    why = ", ".join(pr.get("failing") or []) or ("conflicting with its base" if pr.get("conflicting") else "red")
    return f"PR #{pr['number']} has been red since {pr.get('red_since')}: {why} — fix it or say why"


def pr_order(pr: dict[str, Any], priorities: dict[str, str] | None = None) -> dict[str, Any]:
    """A red PR nobody holds as the lanes and the pages read an entry: `pr:<n>`, the PR's title, High,
    pickable, its `Context` the URL and the failing checks. `pr_order` marks it, and every `free-pick`
    lane takes it: the grinders' pick list (§4.9b *No anchor seat*, TD-757). A sync PR's (TD-684) is marked `sync`, with
    `sync_since` and its `reason` (`sync_reason`), which is its `Context` beside the URL. A lift PR's
    (TD-1450, TD-1854) is marked `lift`, with `lift_since`, its `entry` and `gate`; its priority is its entry's,
    from `priorities` (the repo's ledger, by id, lower-case as the reading keeps it), High where it is not there,
    and its `Context` the URL and the gate. A sweep PR's (TD-1854) is marked `sweep`, with `sweep_since`,
    Medium, its `Context` the URL and *the gate sweep's board items*."""
    failing = list(pr.get("failing") or [])
    sync = is_sync_order(pr)
    lift = not sync and is_lift_order(pr)
    sweep = not sync and not lift and is_sweep_order(pr)
    filing = not sync and not lift and not sweep and filing_row(pr)
    since = str(pr.get("created") or "")
    why = sync_reason(pr) if sync else lift_context(pr) if lift else SWEEP_CONTEXT if sweep else ""
    if filing:
        why = f"filing, open since {since[:10]}, nobody holds it: review and merge it, or close it if superseded"
    tid, gate, _ = (reports.lift_of(pr.get("branch")) or ("", "", False)) if lift else ("", "", False)
    priority = str((priorities or {}).get(tid) or "high").capitalize() if lift else "High"
    priority = "Medium" if filing or sweep else priority
    red = [", ".join(failing), "conflicting" * bool(pr.get("conflicting"))]
    red += ["CI never ran"] if pr.get("checks") == "not_run" else []  # ordered by its conflict alone (TD-686)
    context = " · ".join(filter(None, [str(pr.get("url") or ""), *([why] if sync or lift or sweep or filing else red)]))
    return {
        "id": f"{PR_PREFIX}{pr['number']}",
        "title": str(pr.get("title") or ""),
        "priority": priority,
        "owner": "",
        "kind": "",
        "type": "debt",
        "blocked_by": [],
        "pickable": "yes",
        "for_page": "pickable",
        "work_order": True,
        "pr_order": True,
        "pr": pr["number"],
        "url": str(pr.get("url") or ""),
        "author": str(pr.get("author") or ""),
        "checks": pr.get("checks"),
        "failing": failing,
        "conflicting": bool(pr.get("conflicting")),
        "red_since": pr.get("red_since"),
        "context": context,
        "refs": [],
        "text": "",
        **({"sync": True, "sync_since": pr.get("sync_since"), "reason": why} if sync else {}),
        **({"lift": True, "lift_since": pr.get("lift_since"), "entry": tid, "gate": gate} if lift else {}),
        **({"sweep": True, "sweep_since": pr.get("sweep_since")} if sweep else {}),
        **({"filing": True, "filing_since": since} if filing else {}),
    }


def red_prs(
    open_prs: list[dict[str, Any]],
    records: list[Any],
    now: datetime,
    told: dict[str, dict[str, str]],
    after: timedelta,
    priorities: dict[str, str] | None = None,
    *,
    filing_after: timedelta | None = None,
    key: list[str] | None = None,
    reads: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]], list[tuple[str, dict[str, Any]]]]:
    """A repo's red PRs read against its live records: the `pr:<n>` orders, the memory of whom was
    told (`{n: {red_since, at}}`, one per red spell), and the notes to send now `(record id, pr)`.

    A PR red or conflicting for `after` (from `red_since`) with no holder is an order. Held, and
    every holder `idle`: each is told once, and `after` later, still red and the holders still idle,
    they no longer count and it is an order. A holder at work keeps it off the list.

    A sync PR (`is_sync_order`, TD-684) is an order from the first reading, with no `after`: unheld,
    at once, whatever its checks but *pending*; its idle holders are told and passed over as a red
    PR's, keyed on `sync_since` in place of `red_since`. Sync orders come first in the list.

    A PR the gate sweep opened (`is_gate_order`, TD-1450, TD-1854) is one the same way, keyed on `lift_since`
    or `sweep_since`, whatever its checks, pending included; a lift's priority its entry's in `priorities`
    (`pr_order`). A PR on a head the gate sweep opens (`reports.gate_head`) that `is_gate_order` does not pass
    is no order of any rule, red or filing (§4.4 *One predicate decides*). A PR with none of the stamps is
    skipped.

    A draft (the reading's `draft`) that `is_sync_order` does not order is no order and no note, however
    long it is red (design §4.4 *A draft is no work order*, TD-745); its spell's memory is kept, so a PR
    marked ready red past `after` is an order at once and a holder told before the draft is not told again.

    A fork's PR (the reading's `fork`) is no order and no note either (design §4.4 *A fork's PR is no work
    order*, TD-1285): its fix is its author's, and running its code here is the person's call.

    With `filing_after` (absent: none), a filing PR (`filing_row`) is one too (§4.4 *A filing PR nobody holds
    is a work order*, TD-1811): its spell's stamp is its `created`, kept while the row stays a filing row
    whether or not it passes; it is read once `is_filing_order` passes it (`key` and `reads` its held key and
    its reads), with no `red_since`-past-`after` line; unheld, an order; held with every holder idle, told
    once and an order `after` later. Filing orders come after every other PR order."""
    orders: list[dict[str, Any]] = []
    kept: dict[str, dict[str, str]] = {}
    notes: list[tuple[str, dict[str, Any]]] = []
    for pr in open_prs:
        if not isinstance(pr, dict) or not isinstance(pr.get("number"), int):
            continue
        sync = is_sync_order(pr)
        gate = not sync and reports.gate_head(pr.get("branch"))
        if gate and not is_gate_order(pr, reads):
            continue  # the gate sweep's head, not its order now: never a red or filing order (TD-1854)
        lift = gate and is_lift_order(pr)
        sweep = gate and not lift
        filing = not sync and not gate and filing_after is not None and filing_row(pr)
        since = pr.get("sync_since") if sync else pr.get("lift_since") if lift else pr.get("red_since")
        since = pr.get("sweep_since") if sweep else pr.get("created") if filing else since
        if not since:
            continue
        try:
            red_since = datetime.fromisoformat(str(since))
        except ValueError:
            continue
        if red_since.tzinfo is None:  # a stamp with no offset is UTC, as every stamp in the store is
            red_since = red_since.replace(tzinfo=UTC)
        num = str(pr["number"])
        # the memory's key is `red_since` whatever the spell: a sync PR's is its `sync_since`
        was = told.get(num) if (told.get(num) or {}).get("red_since") == since else None
        if was:
            kept[num] = was  # this red spell's memory stays while it lasts
        if pr.get("draft") and not sync:
            continue  # a draft is no order and no note, its memory kept for when it is ready (TD-745)
        if pr.get("fork") and not sync:
            continue  # a fork's PR is no order and no note: its precheck is the person's (TD-1285)
        if filing and not is_filing_order(pr, now, filing_after or after, key, reads):
            continue  # not yet, or not now: its spell's memory kept while it is a filing row (TD-1811)
        holders = [r for r in records if holds_pr(r, pr)]
        if not holders and (sync or gate):
            orders.append(pr_order(pr, priorities))
            continue
        if not filing and now - red_since < after:
            continue  # a filing row's age is `is_filing_order`'s
        if not holders:
            orders.append(pr_order(pr, priorities))
            continue
        if any(r.state != "idle" for r in holders):
            continue
        if was is None:
            kept[num] = {"red_since": since, "at": now.isoformat()}
            notes.extend((r.id, pr) for r in holders)
        elif now - datetime.fromisoformat(was["at"]) >= after:
            orders.append(pr_order(pr, priorities))
    orders.sort(key=lambda o: (not o.get("sync"), bool(o.get("filing"))))  # sync first, filing last (stable)
    return orders, kept, notes


def ci_not_run(repos: dict[str, dict[str, Any]], promotes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Everything the home's registry holds whose CI never started, by account (design §4.4 *The person
    is told once per account*, TD-686): `repos` the repo readings by root (each open PR reading
    `checks: not_run`), `promotes` the promote readings by repo (each default branch whose reading
    carries `checks_not_run`). Keyed by the `origin` owner in lower case — a GitHub login, else the
    repo is left out — each `{owner, reason, kind, items}`, `reason` and `kind` the first item's and
    each item `{repo, root, runs}` with `pr` and `url` for a PR or `main` (its sha) for a default
    branch. TD-687's Inbox row and Telegram line read it."""
    out: dict[str, dict[str, Any]] = {}

    def add(owner: str | None, why: dict[str, Any], item: dict[str, Any]) -> None:
        if not owner:
            return
        got = out.setdefault(owner.lower(), {"owner": owner, "reason": "", "kind": "", "items": []})
        if not got["items"]:
            got["reason"], got["kind"] = str(why.get("reason") or ""), str(why.get("kind") or "other")
        got["items"].append({**item, "runs": list(why.get("runs") or [])})

    for root in sorted(repos):
        reading = repos[root] if isinstance(repos[root], dict) else {}
        for pr in (reading.get("prs") or {}).get("open") or []:
            if not isinstance(pr, dict) or pr.get("checks") != "not_run" or not isinstance(pr.get("not_run"), dict):
                continue
            url = str(pr.get("url") or "")
            m = re.search(r"github\.com/[^/]+/([^/]+)/pull/", url)
            repo = m[1] if m else Path(root).name
            item = {"repo": repo, "root": root, "pr": pr.get("number"), "url": url}
            add(reports.github_owner(url), pr["not_run"], item)
    for name in sorted(promotes):
        r = promotes[name] if isinstance(promotes[name], dict) else {}
        if isinstance(r.get("checks_not_run"), dict) and r.get("main"):
            item = {"repo": name, "root": str(r.get("root") or ""), "main": r["main"]}
            add(reports.github_owner(r.get("origin")), r["checks_not_run"], item)
    return out


CI_SPELL_CLEAR = 2  # successful readings in a row that group nothing for an owner, with no re-run pending
RUN_DONE = "completed"  # an Actions run's `status` once it has ended; every other status is pending


def ci_failed_owners(repos: dict[str, dict[str, Any]]) -> set[str]:
    """The owners, in lower case, of every repo whose last PR read failed (design §4.4 *Its spell*): for
    them this reading is no reading, and their spells' clear counts are left as they were (TD-687)."""
    out: set[str] = set()
    for reading in repos.values():
        prs = (reading or {}).get("prs") if isinstance(reading, dict) else None
        if isinstance(prs, dict) and prs.get("error") and (owner := reports.github_owner(reading.get("remote"))):
            out.add(owner.lower())
    return out


def ci_rerun_pending(spell: dict[str, Any]) -> bool:
    """Whether any run a **Re-run** asked for is still queued or running, as last read (a failed read
    is pending, design §4.4 *A Re-run's runs are read*)."""
    return any(r.get("pending") for r in ((spell.get("rerun") or {}).get("runs") or []) if isinstance(r, dict))


def ci_spells(
    spells: dict[str, dict[str, Any]], grouped: dict[str, dict[str, Any]], failed: set[str], now: str
) -> dict[str, dict[str, Any]]:
    """One successful reading's step of every **spell** (design §4.4 *Its spell*, TD-687): `spells` as the
    home keeps them, `{<owner>: {owner, since, clear, row, rerun?}}`, keyed in lower case; `grouped`
    `ci_not_run`'s reading; `failed` the owners `ci_failed_owners` names. An owner grouped begins a spell
    at `now` or keeps its own, its `clear` back to 0 and its `row` the grouping's; one not grouped counts
    the reading toward `CI_SPELL_CLEAR` — unless its reading failed (no change) or a re-run's run is
    pending (back to 0) — and its spell ends at the count. Never mutates `spells`."""
    out: dict[str, dict[str, Any]] = {}
    for key, row in grouped.items():
        old = spells.get(key) or {"owner": row.get("owner") or key, "since": now}
        out[key] = {**old, "clear": 0, "row": {k: row.get(k) for k in ("owner", "reason", "kind", "items")}}
    for key, old in spells.items():
        if key in out:
            continue
        if key in failed:
            out[key] = dict(old)
            continue
        clear = 0 if ci_rerun_pending(old) else int(old.get("clear") or 0) + 1
        if clear < CI_SPELL_CLEAR:
            out[key] = {**old, "clear": clear}
    return out


def ci_rerun_runs(spell: dict[str, Any]) -> list[tuple[str, int]]:
    """Every `(root, run)` the spell's row names, once each and in the row's order: what **Re-run** asks
    GitHub to re-run (design §4.5a *Inbox row: CI not starting*)."""
    seen: dict[tuple[str, int], None] = {}
    for item in (spell.get("row") or {}).get("items") or []:
        if not isinstance(item, dict) or not item.get("root"):
            continue
        for run in item.get("runs") or []:
            with contextlib.suppress(TypeError, ValueError):
                seen.setdefault((str(item["root"]), int(run)), None)
    return list(seen)
