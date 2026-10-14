"""A repo's seams as the host agent keeps them (design §4.4 *Repo facts*, *The seams*; §5 *The seams*;
TD-584, built by TD-591): whether its ledger at `ledger:` parses through `ledgerboard.py` and its
`Ledgerboard:` major, and for each of `board:`, `gate:` and `worktree_setup:` whether it is *set*,
*defaulted* (the dev-cadence file the checkout holds) or *absent*. The Repo page's missing-seam lines
(§4.5a) and `ao doctor`'s **repos** check (§4.7) draw this reading and read nothing themselves."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sessionorc import cadence, gitinfo, workorders
from sessionorc import ledger as ledger_mod
from sessionorc import ledgerboard as lb


def ledger(root: Path | str) -> dict[str, Any]:
    """The ledger seam: `{path, state, major, entries, why}` — `state` *ok* (it parses and its major is
    one `ledgerboard.py` knows; `entries` its count), *absent* (no file at `ledger:`), *unreadable*
    (the file could not be read as text) or *newer* (its `Ledgerboard:` major is past the module's),
    `why` the reader's reason when not *ok*."""
    rel = ledger_mod.ledger_path(root)
    out: dict[str, Any] = {"path": rel, "state": "ok", "major": None, "entries": None, "why": None}
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
    """The repo's seams: `{ledger, board, gate, worktree_setup}` — `ledger` as `ledger()` gives it, each
    other `{state, value}`, `value` the board's path or the command (None when *absent*)."""
    board_state, board_rel = workorders.board_path(root)
    out: dict[str, Any] = {
        "ledger": ledger(root),
        "board": {"state": board_state, "value": board_rel.as_posix() if board_rel is not None else None},
    }
    for key, (state, value) in (("gate", cadence.gate(root)), ("worktree_setup", gitinfo.worktree_setup(root))):
        out[key] = {"state": state, "value": value}
    return out
