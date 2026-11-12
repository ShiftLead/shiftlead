"""The note to the taker of an entry no lane takes (design §4.4 *An entry no lane takes is marked*, *The note to
the taker*, TD-1573, built by TD-1686): `no_lane_noted.json`'s clocks and spent ids, and which marked ids a pass
tells the session the id was given to. Pure: the host agent's step loads, sends and saves."""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from sessionorc import ledger as ledger_mod
from sessionorc import paths
from sessionorc.store import _atomic_write

NO_LANE_NOTE_AFTER = timedelta(minutes=30)  # a mark stands this long before its taker is told


def norm(tid: Any) -> str | None:
    """An id as the ledger normalises it (`ledger._norm`), None for what is no ledger id (`board:…`, `pr:…`)."""
    try:
        return ledger_mod._norm(str(tid))
    except (ValueError, TypeError):
        return None


def note_text(tid: str, repo: str, why: str, waits: bool) -> str:
    """The note's words (§4.4 *The note to the taker*); an entry that already waits on a gate is not told to
    block it."""
    head = f"{tid}: no lane of {repo}'s teams takes it — {why}. "
    fix = f"Change its header (agent-cadence run ledger.py set {tid} --owner, --kind or --field Team=…)"
    return head + fix + ("." if waits else ", or block it on what it waits for.")


def load() -> dict[str, Any]:
    try:
        raw = json.loads(paths.no_lane_noted_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save(store: dict[str, Any]) -> None:
    paths.no_lane_noted_file().parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(paths.no_lane_noted_file(), json.dumps(store, indent=1, sort_keys=True))


def drop_root(store: dict[str, Any], root: str) -> bool:
    """A checkout the registry dropped (`gone`) loses its key under whichever origin holds it; True where one did."""
    hit = False
    for rec in store.values():
        roots = rec.get("roots") if isinstance(rec, dict) else None
        if isinstance(roots, dict) and root in roots:
            del roots[root]
            hit = True
    return hit


def _since(at: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(at))
    except ValueError:
        return None


def step(
    store: dict[str, Any],
    key: str,
    root: str,
    entries: Iterable[Any],
    lanes_read: bool,
    claimed: Collection[str],
    now: datetime,
) -> list[dict[str, Any]]:
    """One pass of a checkout's reading over the store, in place: `root` the checkout's resolved path, `entries`
    the marked reading's open entries, `lanes_read` whether a lane of the checkout was read (False: unserved, or
    no record carries one), `claimed` the normalised ids a live record of the repo holds claimed. Returns the
    entries whose taker is due a note now — their ids already written to `ids`, the caller resolving each
    taker and sending where it resolves, since an id whose taker does not resolve is spent all the same."""
    rec = store.get(key) if isinstance(store.get(key), dict) else {}
    roots = rec.get("roots") if isinstance(rec.get("roots"), dict) else {}
    spent = [i for i in rec.get("ids") or [] if isinstance(i, str)]
    mine = roots.get(root) if isinstance(roots.get(root), dict) else {}
    was = mine.get("marked") if isinstance(mine.get("marked"), dict) else {}
    opened: dict[str, dict[str, Any]] = {}
    marks: dict[str, dict[str, Any]] = {}
    for e in entries:
        if isinstance(e, dict) and (tid := norm(e.get("id"))):
            opened[tid] = e
            if lanes_read and isinstance(e.get("no_lane"), dict):
                marks[tid] = e
    stamp = now.isoformat()
    due: list[dict[str, Any]] = []
    if not lanes_read:
        mine = {**mine, "marked": {}}  # a pass that marks nothing empties its clocks, `from` kept
    elif not mine.get("from"):  # a first pass: every mark clocked, the owner ones spent, nothing sent
        clocks = {i: {"why": e["no_lane"].get("why"), "since": stamp} for i, e in marks.items()}
        mine = {"from": stamp, "marked": clocks}
        spent += [i for i, e in marks.items() if e["no_lane"].get("case") == "owner" and i not in spent]
    else:
        marked: dict[str, dict[str, Any]] = {}
        for tid, e in marks.items():
            why = e["no_lane"].get("why")
            old = was.get(tid) if isinstance(was.get(tid), dict) else {}
            keep = old.get("why") == why and _since(old.get("since")) is not None
            marked[tid] = {"why": why, "since": old["since"] if keep else stamp}
        mine = {**mine, "marked": marked}
        for tid, m in marked.items():
            e = marks[tid]
            since = _since(m["since"])
            if tid in spent or since is None or now - since < NO_LANE_NOTE_AFTER:
                continue
            if e["no_lane"].get("case") != "owner" or tid in claimed:
                continue  # skipped: its clock runs on
            spent.append(tid)
            due.append(e)
    if lanes_read or root in roots:  # a checkout no lane was ever read for gets no key
        roots = {**roots, root: mine}
    held = {i for r in roots.values() if isinstance(r, dict) for i in (r.get("marked") or {})}
    spent = [i for i in spent if i in opened or i in held]
    store[key] = {"roots": roots, "ids": spent}
    return due


def taker(given: Iterable[Any], tid: str) -> str | None:
    """Who `ids.json`'s `given` says the id was given to — its newest record's `by` — None where it holds none."""
    by = None
    for g in given:
        if isinstance(g, Mapping) and norm(g.get("id")) == tid and isinstance(g.get("by"), str):
            by = g["by"]
    return by
