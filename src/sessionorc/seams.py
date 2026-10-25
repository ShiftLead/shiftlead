"""A repo's seams as the host agent keeps them (design §4.4 *Repo facts*, *The seams*; §5 *The seams*;
TD-584, built by TD-591): whether its ledger at `ledger:` parses through `ledgerboard.py` and its
`Ledgerboard:` major, and for each of `board:`, `gate:` and `worktree_setup:` whether it is *set*,
*defaulted* (the dev-cadence file the checkout holds) or *absent*. The Repo page's missing-seam lines
(§4.5a) and `ao doctor`'s **repos** check (§4.7) draw this reading and read nothing themselves. It also
carries the release the repo's vendored `ledgerboard.py` names in its header beside the wheel's (§5
*ledgerboard by its header*, TD-1013)."""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any

from sessionorc import cadence, gitinfo, workorders
from sessionorc import ledger as ledger_mod
from sessionorc import ledgerboard as lb

# a vendored copy's first line: the tagged release it came from and the hash of every byte after it
RELEASE_HEADER = re.compile(r"^# ledgerboard v(\S+) sha256:([0-9a-f]{64})$")
# where a repo keeps its copy: a consumer's, then dev-cadence's own source
LEDGERBOARD_COPIES = ("scripts/ledgerboard.py", "files/scripts/ledgerboard.py")


def ledgerboard_release(text: str) -> str | None:
    """The release a `ledgerboard.py`'s first line names (*1.3* of `# ledgerboard v1.3 sha256:…`), or None
    when that line is not a release header."""
    m = RELEASE_HEADER.match(text.split("\n", 1)[0].rstrip("\r"))
    return m.group(1) if m else None


def _file_release(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8") as f:
            return ledgerboard_release(f.readline())
    except (OSError, UnicodeDecodeError):
        return None


@functools.cache
def wheel_release() -> str | None:
    """The release of the `ledgerboard.py` this build carries (`sessionorc/ledgerboard.py`), read once."""
    return _file_release(Path(lb.__file__))


def ledgerboard(root: Path | str) -> dict[str, Any]:
    """`{release, wheel}`: the release the repo's copy names (the first of `LEDGERBOARD_COPIES` there;
    None for a copy with no release header, or a repo with neither file) and the wheel's."""
    copy = next((Path(root) / rel for rel in LEDGERBOARD_COPIES if (Path(root) / rel).is_file()), None)
    return {"release": _file_release(copy) if copy is not None else None, "wheel": wheel_release()}


def ledger(root: Path | str) -> dict[str, Any]:
    """The ledger seam: `{path, state, major, entries, why}` — `state` *ok* (it parses and its major is
    one `ledgerboard.py` knows; `entries` its count), *absent* (no file at `ledger:`), *unreadable*
    (the file could not be read as text, or `ledger:` names a path outside the repo) or *newer* (its
    `Ledgerboard:` major is past the module's), `why` the reader's reason when not *ok*."""
    rel = ledger_mod.ledger_path(root)
    out: dict[str, Any] = {"path": rel, "state": "ok", "major": None, "entries": None, "why": None}
    if not workorders.inside(Path(rel)):
        return {**out, "state": "unreadable", "why": f"ledger: {rel} is not a path inside the repo"}
    path = Path(root) / rel
    if not path.is_file():
        return {**out, "state": "absent", "why": f"no ledger at {rel}"}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {**out, "state": "unreadable", "why": f"{rel}: {getattr(e, 'strerror', None) or e}"}
    out["major"] = lb.format_major(text)
    why = lb.version_problem(text)
    if why is not None:
        return {**out, "state": "newer", "why": why}
    try:
        out["entries"] = len(lb.entries(text))
    except Exception as e:  # noqa: BLE001 — a ledger the module cannot parse is named, never a failed reading
        return {**out, "state": "unreadable", "why": f"{rel} does not parse: {e}"}
    return out


def reading(root: Path | str) -> dict[str, Any]:
    """The repo's seams: `{ledger, board, gate, worktree_setup, ledgerboard}` — `ledger` as `ledger()`
    gives it, `ledgerboard` as `ledgerboard()` does, each other `{state, value}`, `value` the board's path
    or the command (None when *absent*)."""
    board_state, board_rel = workorders.board_path(root)
    out: dict[str, Any] = {
        "ledger": ledger(root),
        "board": {"state": board_state, "value": board_rel.as_posix() if board_rel is not None else None},
    }
    for key, (state, value) in (("gate", cadence.gate(root)), ("worktree_setup", gitinfo.worktree_setup(root))):
        out[key] = {"state": state, "value": value}
    out["ledgerboard"] = ledgerboard(root)
    return out
