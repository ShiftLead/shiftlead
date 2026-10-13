"""Work orders (design §4.4 *Board write-back*, §6 rule 6, TD-380; built — TD-384): every open
*decided* line of a repo's attention board, listed by the repo reading beside the ledger's entries
as **`board:<key>`** — the first eight hex digits of a sha256 of the line's `item_key()`, which a
snooze, a reply and the decide itself leave unchanged — pickable, High, in every `free-pick` lane
of a team servicing the repo, and counted by rule 8, until a session closes the line.

The board is dev-cadence's file and its reader is dev-cadence's own `nudge_user_attention.py
--report --json` (never a second parser here, as the Inbox's §4.4 rule says): the repo's copy is run
with its own `--fetch`, so a board merely behind origin is read from origin, as the Inbox reads it,
and `item_key` is that same file's function, loaded from it. A `fyi` line and a closed line are
never work orders; a line whose `Decided:` is gone leaves on the next reading."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

BOARD = Path("docs") / "user_attention.md"
READER = Path("scripts") / "nudge_user_attention.py"
PREFIX = "board:"
FETCH_TIMEOUT = 45.0  # the reader's fetch is serial and its own; a read past this is a plain one
READ_TIMEOUT = 20.0
HEAD_MOST = 120
_REF_RE = re.compile(r"board:[0-9a-f]{8}")
# one loaded reader per file, or None for one that will not load, kept while its mtime holds
_readers: dict[str, tuple[float, types.ModuleType | None]] = {}
# one load at a time: a load swaps the process's `sys.path`, `sys.modules['ledgerboard']` and
# `sys.dont_write_bytecode` and puts them back, and `read` runs on threads
_load = threading.Lock()
NO_LINE = "no line {ref} on the board — reworded or closed"


def is_work_order(ref: str) -> bool:
    """Whether a reference names a work order: `board:` and eight hex digits."""
    return bool(_REF_RE.fullmatch(str(ref)))


def _reader(script: Path) -> types.ModuleType | None:
    """The repo's own reader, loaded from that file and kept while its mtime holds — a reader that
    will not load is kept as None too, so a page asking per row never runs it again (TD-384)."""
    try:
        stamp = script.stat().st_mtime
    except OSError:
        return None
    held = _readers.get(str(script))
    if held is not None and held[0] == stamp:
        return held[1]
    got: types.ModuleType | None = None
    # compiled from its text, never imported: an import writes `scripts/__pycache__` into the repo's
    # checkout, which reads as the person's uncommitted work to everything that asks (TD-386's gate)
    mod = types.ModuleType(f"_ao_board_reader_{abs(hash(str(script)))}")
    mod.__file__ = str(script)
    try:
        code = compile(script.read_text(encoding="utf-8"), str(script), "exec")
        sys.modules[mod.__name__] = mod  # a dataclass in the reader looks its module up by name
        # the reader imports its sibling `ledgerboard.py` through a `sys.path` entry of its own: write no
        # bytecode for it, leave neither that entry nor that module behind, so the next repo's reader
        # imports its own copy
        with _load:
            path, sibling, nobytes = list(sys.path), sys.modules.pop("ledgerboard", None), sys.dont_write_bytecode
            sys.dont_write_bytecode = True
            try:
                # whatever it prints at load is not the caller's: `ao repo --json` prints to the same stdout
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(code, mod.__dict__)  # noqa: S102 — the repo's own reader, as `read` runs it
            finally:
                sys.modules.pop(mod.__name__, None)
                sys.path[:], sys.dont_write_bytecode = path, nobytes
                sys.modules.pop("ledgerboard", None)
                if sibling is not None:
                    sys.modules["ledgerboard"] = sibling
        got = mod
    except (Exception, SystemExit):  # noqa: BLE001 — a reader that will not load lists no work orders
        got = None
    _readers[str(script)] = (stamp, got)
    return got


def _item_key(script: Path) -> Callable[[str], str] | None:
    """The reader's own `item_key`, or None where the repo's reader will not load or has none."""
    got = getattr(_reader(script), "item_key", None)
    return got if callable(got) else None


def key(text: str, item_key: Callable[[str], str]) -> str:
    """`board:<key>` for an open item's text as the report gives it — its line less the open tick."""
    return PREFIX + hashlib.sha256(item_key(f"- [ ] {text}").encode("utf-8")).hexdigest()[:8]


def ref(root: str | Path, text: str) -> str:
    """`board:<key>` for a line of the board under `root`, by that repo's own reader — **every board
    line's id** (design §4.4 *A board line's id*, TD-603): the one derivation the Inbox's board rows,
    the write-back's presses, `ao board show`, `ao repo` and the work orders all use — or empty where
    the repo has no reader or its key cannot take the line. `text` is the item less its tick."""
    item_key = _item_key(Path(root) / READER) if root and text else None
    if item_key is None:
        return ""
    try:
        return key(text, item_key)
    except Exception:  # noqa: BLE001 — a line the reader's own key cannot take has no reference
        return ""


def head(text: str) -> str:
    """A line's head text, the work order's title: its bold head where it has one, else what
    follows the `(session …) —` lead, clipped."""
    bold = re.search(r"\*\*(.+?)\*\*", text)
    out = bold.group(1) if bold else text.split(" — ", 1)[-1]
    out = " ".join(out.split()).rstrip(" .")
    return out if len(out) <= HEAD_MOST else out[: HEAD_MOST - 1].rstrip() + "…"


def _report(argv: list[str], timeout: float) -> dict[str, Any] | None:
    try:
        # no `scripts/__pycache__` for the reader's `ledgerboard` import in the repo's checkout (TD-386's gate)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if cp.returncode != 0:
        return None
    try:
        got = json.loads(cp.stdout)
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def read(root: str | Path, *, fetch: bool = True) -> dict[str, Any]:
    """The repo's work orders: `{orders: [...], at_origin}` — each `{id, title, text, line, decided:
    {text, date}, refs, session, kind}` — or `{error}` when the board could not be read. No board,
    or no reader in the repo, is no work orders and no error."""
    root = Path(root)
    board, script = root / BOARD, root / READER
    if not board.is_file() or not script.is_file():
        return {"orders": []}
    base = [sys.executable, str(script), "--report", "--json", "--board", str(board)]
    got = _report([*base, "--fetch"], FETCH_TIMEOUT) if fetch else None
    if got is None:
        got = _report(base, READ_TIMEOUT)
    if got is None:
        return {"error": f"{READER} --report --json could not be read"}
    item_key = _item_key(script)
    if item_key is None:
        return {"error": f"{READER} has no item_key to name a line by"}
    orders: list[dict[str, Any]] = []
    for b in got.get("boards") or []:
        for it in (b.get("items") or []) if isinstance(b, dict) else []:
            if not isinstance(it, dict) or not isinstance(it.get("decided"), dict) or it.get("kind") == "fyi":
                continue
            text = str(it.get("text") or "")
            if not text:
                continue
            try:
                ref = key(text, item_key)
            except Exception:  # noqa: BLE001 — a line the reader's own key cannot take is skipped, not fatal
                continue
            orders.append(
                {
                    "id": ref,
                    "title": head(text),
                    "text": text,
                    "line": it.get("line"),
                    "decided": {"text": str(it["decided"].get("text") or ""), "date": it["decided"].get("date")},
                    "refs": [str(r) for r in it.get("refs") or []],
                    "session": it.get("session"),
                    "kind": it.get("kind"),
                }
            )
    return {"orders": orders}


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
        "line": order.get("line"),
        "text": order.get("text") or "",
    }


def board_lines(root: str | Path, *, fetch: bool = True) -> tuple[list[str], str]:
    """The board under the checkout `root` as lines, and where they were read: origin's default
    branch after a fetch (`origin/<branch>`), else the checkout's file (`checkout`) — design §4.7
    `ao board show`. No board is `([], "")`."""
    root = Path(root)
    if fetch:
        try:
            # a fetch that failed leaves origin's ref as stale as the checkout: the checkout it is
            fetched = subprocess.run(
                ["git", "-C", str(root), "fetch", "-q", "origin"], capture_output=True, timeout=FETCH_TIMEOUT
            )
            cp = subprocess.run(
                ["git", "-C", str(root), "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"],
                capture_output=True, text=True, timeout=READ_TIMEOUT,
            )  # fmt: skip
            heads = [cp.stdout.strip()] if cp.stdout.strip() else ["origin/main", "origin/master"]
            for head in heads if fetched.returncode == 0 else ():
                cp = subprocess.run(
                    ["git", "-C", str(root), "show", f"{head}:{BOARD.as_posix()}"],
                    capture_output=True, text=True, errors="replace", timeout=READ_TIMEOUT,
                )  # fmt: skip
                if cp.returncode == 0:
                    return cp.stdout.splitlines(), head
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        return (root / BOARD).read_text(encoding="utf-8").splitlines(), "checkout"
    except OSError:
        return [], ""


def can_name(root: str | Path) -> bool:
    """Whether the repo under `root` has a reader whose `item_key` can name its board's lines."""
    return _item_key(Path(root) / READER) is not None


def show(root: str | Path, want: str, *, fetch: bool = True) -> dict[str, Any] | None:
    """The line of the board under `root` whose id is `want` (design §4.7 `ao board show`): `{key,
    line, text, detail, open, source}` — `text` the whole line less its tick, `detail` the reader's
    detail block under it — open or closed, the first that holds it; None when no line does."""
    root = Path(root)
    mod = _reader(root / READER)
    item_key = getattr(mod, "item_key", None)
    # the line shapes are the reader's own, open and closed (design §8): none is written here
    shapes = [getattr(mod, name, None) for name in ("ITEM_RE", "CLOSED_ITEM_RE")]
    if not callable(item_key) or not all(isinstance(r, re.Pattern) for r in shapes):
        return None
    opened, closed = shapes
    lines, source = board_lines(root, fetch=fetch)
    for n, ln in enumerate(lines, 1):
        m = opened.match(ln) or closed.match(ln)
        if m is None:
            continue
        try:
            got = key(m.group("text"), item_key)
        except Exception:  # noqa: BLE001 — a line the reader's own key cannot take has no id
            continue
        if got != want:
            continue
        block = getattr(mod, "detail_block", None)
        try:
            detail = [str(d) for d in block(lines, n)] if callable(block) else []
        except Exception:  # noqa: BLE001 — the line is found; a block the reader cannot give is none
            detail = []
        return {
            "key": got,
            "line": n,
            "text": m.group("text").strip(),
            "detail": detail,
            "open": m.re is opened,
            "source": source,
        }
    return None
