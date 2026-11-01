"""A new ledger entry settles before it is pickable (design §4.4 *A new entry settles before it is
pickable*, TD-707, built by TD-710). The clock is the home's: `ledger_seen.json` beside `ids.json`,
`{<origin>: {<id>: {at, sig}}}`, written beside each ledger reading, so the reader stays a
function of the checkout's text. `observe` records what a fresh reading holds and marks it; `mark`
marks a reading the clock has already seen (a carried one, or rule 6's reading at a declaration) from
the store as it stands. A marked entry — `settling: {until}` — matches no lane (`ledger.lane_matches`),
and its page kind is unchanged. The clock records settling only: an entry held out of the lanes is a
`decision (<person>)` row (§4.4 *Holding an entry is a decision on it*, TD-1297), and a record's `held`
written before that is ignored on load."""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from sessionorc import paths
from sessionorc import settings as settings_mod
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


def spans(root: Path | str) -> dict[str, int]:
    """The durations a checkout's entries settle by: its `.shiftlead.yml` `settle:` over the install's
    `settings.yml` `settle:` over the built-in."""
    return durations(settings_mod.load().get("settle"), repo_settle(root))


def _when(value: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _kind(entry: dict[str, Any]) -> str:
    return str(entry.get("kind") or "").lower() or "build"  # no `Kind:` line reads as `build` (§4.4)


def mark_waits(entries: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Each entry's `waiting: {on, until}` while its `**Waits:**` line stands (design §4.4 *What a wait
    does*, TD-716), dropping a stale one: an `until` stands while the home's local date is before its
    date — one that names no date waits with no end — and an `event` while the line is there. It needs
    no record and no `settle:` span, so a repo with neither, or a clock that cannot be written, still
    marks waits. Returns `entries`."""
    today = now.astimezone().date().isoformat()
    for e in entries:
        e.pop("waiting", None)
        w = e.get("waits")
        if not isinstance(w, dict) or w.get("on") not in ("until", "event"):
            continue
        date = str(w.get("date") or "")
        if w["on"] == "until" and date and date <= today:
            continue  # its day has begun: the line reads as unwritten
        e["waiting"] = {"on": w["on"], "until": date}
    return entries


def wait_refusal(entry: dict[str, Any] | None) -> str | None:
    """Why a declared claim on a waiting entry is refused (design §4.4 *What a wait does*, TD-716), or
    None: *TD-463 waits until 2026-10-16*, *TD-685 waits: the next cadence-sync PR*. `--force` passes
    it, since the session may know the event has come; that session's PR removes the line."""
    if not isinstance(entry, dict) or not isinstance(entry.get("waiting"), dict):
        return None
    i, w = str(entry.get("id") or ""), entry.get("waits") if isinstance(entry.get("waits"), dict) else {}
    if entry["waiting"].get("on") == "until" and entry["waiting"].get("until"):
        said = f"{i} waits until {entry['waiting']['until']}"
    else:
        said = f"{i} waits: {w.get('why') or entry['waiting'].get('on') or 'an event'}"
    return f"{said} (design §4.4 *An entry says what it waits for*); claim it anyway with --force if the wait is over"


def team_refusal(entry: dict[str, Any] | None, team: str, who: str = "") -> str | None:
    """Why a declared claim is refused by the entry's team (design §4.4 *An entry names its team*, TD-730),
    or None: on an entry marked `needs_team`, for every claimer, *TD-801 needs a team (untagged)*; on
    another team's entry, *TD-801 is db's: compliance-grinder-1 is compliance's*, never for a claimer with
    no team (`team` ''). `who` is the claimer's name. `--force` passes both, as for a waiting entry."""
    if not isinstance(entry, dict):
        return None
    i = str(entry.get("id") or "")
    tail = " (design §4.4 *An entry names its team*); claim it anyway with --force"
    if isinstance(entry.get("needs_team"), dict):
        return f"{i} needs a team ({entry['needs_team'].get('why') or 'untagged'}){tail}"
    theirs = str(entry.get("team") or "")
    if team and theirs and theirs.casefold() != team.casefold():
        return f"{i} is {theirs}'s: {who or 'this session'} is {team}'s{tail}"
    return None


def _marks(entries: list[dict[str, Any]], seen: dict[str, Any], spans: dict[str, int], now: datetime) -> None:
    """Each entry's `settling` from its record, dropping a stale one: an unsettled entry settles at `at`
    plus its Kind's duration. A record's `held`, written before TD-1297, is ignored. Each entry's
    `waiting` too (`mark_waits`)."""
    mark_waits(entries, now)
    for e in entries:
        e.pop("settling", None)
        rec = seen.get(str(e.get("id")))
        if not isinstance(rec, dict):
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


def observe(entries: list[dict[str, Any]], key: str, spans: dict[str, int], now: datetime) -> list[dict[str, Any]]:
    """Record a fresh reading of origin `key` and mark its entries in place (§4.4 *The clock*): an id
    first seen is recorded at `now`, except that **a repo's first reading records every id at the
    epoch**, settled — the first being the first that finds no record with an `at` under the key, so a
    record written before TD-1297 by the retired `--held` (no `at`) does not make every other id settle
    as new. An edit (a changed `sig`) to an entry still settling restarts its window from `now`, and one
    to a settled entry only records the new `sig`. A record's old `held` is dropped as it is rewritten,
    and one with no `at` reads as an id first seen. An id the reading does not hold keeps its record — a
    partial reading, or a second checkout of the origin behind the first, must not bring a settled entry
    back as new — so the record grows by one line per id the ledger ever held. Returns `entries`."""
    stamp = now.isoformat()
    with _STORE:
        store = _load()
        read = isinstance(store.get(key), dict)
        old: dict[str, Any] = store[key] if read else {}
        # no reading yet, or only records with no `at` (an empty ledger's first reading leaves `{}`, a reading)
        first = not read or (bool(old) and not any(isinstance(r, dict) and r.get("at") for r in old.values()))
        seen: dict[str, Any] = dict(old)
        for e in entries:
            i, sig = str(e.get("id") or ""), str(e.get("sig") or "")
            if not i:
                continue
            rec = old.get(i) if isinstance(old.get(i), dict) else None
            if rec is None or not rec.get("at"):
                seen[i] = {"at": EPOCH if first else stamp, "sig": sig}
                continue
            rec = {k: v for k, v in rec.items() if k != "held"}  # a hold recorded before TD-1297 is ignored
            if rec.get("sig") != sig:
                at = _when(rec.get("at"))
                if at is None or at + timedelta(seconds=spans.get(_kind(e), 0)) > now:
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


def claim_refusal(entry: dict[str, Any] | None, now: datetime) -> str | None:
    """Why a declared claim on this entry of the home's reading is refused (design §4.8 *A claim is a
    lease*, §4.4 *What settling withholds*), or None: it settles. `--force` does not pass it — the
    window is the person's, not another session's lease."""
    if not isinstance(entry, dict):
        return None
    i = str(entry.get("id") or "")
    tail = "(design §4.4 *A new entry settles before it is pickable*); --force does not pass it"
    until = _when((entry.get("settling") or {}).get("until")) if isinstance(entry.get("settling"), dict) else None
    if until is not None and until > now:
        return f"{i} settles until {until.astimezone():%H:%M}: the person's window to change it {tail}"
    return None


def _span(secs: int) -> str:
    """A span in its largest whole unit: `45s`, `7m`, `2h`, `3d`."""
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= n:
            return f"{secs // n}{unit}"
    return f"{max(0, secs)}s"


def words(entry: dict[str, Any], now: datetime) -> str:
    """What the settle clock's mark on a reading's entry says where the entry is drawn — after its owner
    in `ao repo` and on the Repo page's row (design §4.4 *Shown where it is read*, TD-710): *settles in
    7m*, else ''."""
    until = _when((entry.get("settling") or {}).get("until")) if isinstance(entry.get("settling"), dict) else None
    left = int((until - now).total_seconds()) if until else 0
    return f"settles in {_span(left)}" if left > 0 else ""


def parse(value: Any) -> dict[str, str]:
    """A `settle:` mapping as `set_settings` writes it (§5): `{kind: duration}`, each Kind a word and each
    duration `parse_duration`'s, kept as written; raises ValueError naming the first that is not."""
    if not isinstance(value, dict):
        raise ValueError("settle is a mapping of Kind to duration, like {design-first: 5m}")
    out: dict[str, str] = {}
    for k, v in value.items():
        kind = str(k or "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9-]*", kind):
            raise ValueError(f"settle: {k!r} is not a Kind (a word like design-first)")
        parse_duration(v)
        out[kind] = str(v).strip()
    return out


def parse_text(text: str) -> dict[str, str]:
    """The Settings page's **settle** field (§4.5a): Kind and duration pairs, `design-first 5m,
    live-check 0` — commas or new lines between pairs — as `parse`'s mapping; empty is `{}`."""
    pairs = [p.split() for p in re.split(r"[,\n;]+", str(text or "")) if p.strip()]
    for p in pairs:
        if len(p) != 2:
            raise ValueError(f"settle: {' '.join(p)!r} is not a Kind and a duration, like design-first 5m")
    return parse(dict(pairs))


def text_of(value: Any) -> str:
    """A `settle:` mapping as the **settle** field and a Repos card draw it: `design-first 5m, …`."""
    return ", ".join(f"{k} {v}" for k, v in value.items()) if isinstance(value, dict) else ""
