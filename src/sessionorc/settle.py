"""A new ledger entry settles before it is pickable (design §4.4 *A new entry settles before it is
pickable*, TD-707, built by TD-710). The clock is the home's: `ledger_seen.json` beside `ids.json`,
`{<origin>: {<id>: {at, sig, held?}}}`, written beside each ledger reading, so the reader stays a
function of the checkout's text. `observe` records what a fresh reading holds and marks it; `mark`
marks a reading the clock has already seen (a carried one, or rule 6's reading at a declaration) from
the store as it stands. A marked entry — `settling: {until}`, or `held: {at}` — matches no lane
(`ledger.lane_matches`), and its page kind is unchanged."""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from sessionorc import paths
from sessionorc.store import _atomic_write

# The built-in layer under the install's `settle:` and the repo's (§5): a Kind no layer lists settles 0.
DEFAULT = {"design-first": "5m"}
EPOCH = "1970-01-01T00:00:00+00:00"
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_STORE = threading.Lock()  # one read-modify-write of the file at a time: two checkouts of one origin


def parse_duration(value: Any) -> int:
    """Seconds from `5m`, `1h`, `2d`, `30s`, `0` or a whole number of seconds; raises on anything else."""
    if isinstance(value, bool):
        raise ValueError(f"a settle duration is like 5m, 1h or 0 — not {value!r}")
    m = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", str(value)) if isinstance(value, int | str) else None
    if m is None:
        raise ValueError(f"a settle duration is like 5m, 1h or 0 — not {value!r}")
    return int(m.group(1)) * _UNITS[m.group(2) or "s"]


def _layer(value: Any) -> dict[str, int]:
    """One layer's `settle:` as `{kind: seconds}`; a key whose value cannot be read is left out, so a
    typo in one key falls through to the layer below rather than freezing or freeing every Kind."""
    out: dict[str, int] = {}
    for k, v in (value or {}).items() if isinstance(value, dict) else ():
        try:
            out[str(k).strip().lower()] = parse_duration(v)
        except ValueError:
            continue
    return out


def repo_settle(root: Path | str) -> dict[str, Any]:
    """The repo's `.shiftlead.yml` `settle:` as written, `{}` when it has none or cannot be read."""
    f = paths.repo_file(root)
    try:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    got = doc.get("settle") if isinstance(doc, dict) else None
    return got if isinstance(got, dict) else {}


def durations(install: Any, repo: Any) -> dict[str, int]:
    """`{kind: seconds}`: the repo's `settle:` wins key by key over the install's, which wins over
    `DEFAULT` (§4.4, §5)."""
    return {**_layer(DEFAULT), **_layer(install), **_layer(repo)}


def _when(value: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _kind(entry: dict[str, Any]) -> str:
    return str(entry.get("kind") or "").lower() or "build"  # no `Kind:` line reads as `build` (§4.4)


def _marks(entries: list[dict[str, Any]], seen: dict[str, Any], spans: dict[str, int], now: datetime) -> None:
    """Each entry's `settling` or `held` from its record, dropping a stale one: a held entry is held
    whatever the clock says; an unsettled one settles at `at` plus its Kind's duration."""
    for e in entries:
        e.pop("settling", None)
        e.pop("held", None)
        rec = seen.get(str(e.get("id")))
        if not isinstance(rec, dict):
            continue
        if isinstance(rec.get("held"), dict):
            e["held"] = {"at": str(rec["held"].get("at") or "")}
            continue
        at = _when(rec.get("at"))
        if at is None:
            continue
        until = at + timedelta(seconds=spans.get(_kind(e), 0))
        if until > now:
            e["settling"] = {"until": until.isoformat()}


def _load() -> dict[str, Any]:
    try:
        raw = json.loads(paths.ledger_seen_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def observe(
    entries: list[dict[str, Any]], key: str, spans: dict[str, int], now: datetime
) -> list[dict[str, Any]]:
    """Record a fresh reading of origin `key` and mark its entries in place (§4.4 *The clock*): an id
    first seen is recorded at `now`, except that **a repo's first reading records every id at the
    epoch**, settled; an edit (a changed `sig`) to an entry still settling, or held, restarts its
    window from `now` and ends the hold, and one to a settled entry only records the new `sig`. An id
    the reading does not hold keeps its record — a partial reading, or a second checkout of the origin
    behind the first, must not drop a hold or bring a settled entry back as new — so the record grows
    by one line per id the ledger ever held. Returns `entries`."""
    stamp = now.isoformat()
    with _STORE:
        store = _load()
        first = not isinstance(store.get(key), dict)
        old: dict[str, Any] = {} if first else store[key]
        seen: dict[str, Any] = dict(old)
        for e in entries:
            i, sig = str(e.get("id") or ""), str(e.get("sig") or "")
            if not i:
                continue
            rec = old.get(i) if isinstance(old.get(i), dict) else None
            if rec is None:
                seen[i] = {"at": EPOCH if first else stamp, "sig": sig}
                continue
            rec = dict(rec)
            if rec.get("sig") != sig:
                at = _when(rec.get("at"))
                settled = at is not None and at + timedelta(seconds=spans.get(_kind(e), 0)) <= now
                if isinstance(rec.get("held"), dict) or not settled:
                    rec = {"at": stamp, "sig": sig}  # the person still adding thoughts: the window again
                else:
                    rec["sig"] = sig
            seen[i] = rec
        if seen != old or first:
            store[key] = seen
            _atomic_write(paths.ledger_seen_file(), json.dumps(store, indent=1, sort_keys=True))
    _marks(entries, seen, spans, now)
    return entries


def mark(entries: list[dict[str, Any]], key: str, spans: dict[str, int], now: datetime) -> list[dict[str, Any]]:
    """Mark a reading from the record as it stands, writing nothing: a reading carried from an earlier
    pass (so a window ends when its time does, not at the next read), or one of another commit. An id
    the record does not hold is not marked. Returns `entries`."""
    with _STORE:
        seen = _load().get(key)
    _marks(entries, seen if isinstance(seen, dict) else {}, spans, now)
    return entries
