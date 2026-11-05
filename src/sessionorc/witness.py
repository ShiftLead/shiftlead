"""The home's witness log (design §4.4 *The home keeps a log of what it witnesses*, TD-1295, TD-1386).

One line a record, `{id, at, kind, repo, text}`, in `witnessed/<YYYY-MM>.jsonl` under the home's store, one
file per UTC month of `at`, appended to and never rewritten; `witnessed/start` is the instant the home first
ran with the log, written once at the agent's start, and nothing dated before it is written. Every writer goes
through `append`, which the agent runs on its loop. Kept `WITNESS_KEEP_MONTHS`: the current month and the
twelve before it. A record of a kind not in `KINDS` is never written."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import paths

log = logging.getLogger(__name__)

WITNESS_KEEP_MONTHS = 13  # the current month and the twelve before it (a constant, not a setting)

# Each kind's text and the most private class of repo its records may be answered for (TD-045 rule 7).
KINDS: dict[str, dict[str, str]] = {
    "precheck-fail": {
        "text": "<repo>#<n> or <repo>@main, the head's first 12 hex, status <id>, then the failing tests it holds",
        "class": "public",
    },
    "press": {"text": "<word> <target>", "class": "public"},
}

# The press words (`witness_press`), each saying whether it carries a `dir` the record's repo is mapped from.
PRESS_WORDS: dict[str, bool] = {
    "apply": True,
    "start": True,
    "new-session": True,
    "host-rebuild": False,
    "send-to-reviewer": True,
    "push-on": False,
}

ID_RE = re.compile(r"[A-Za-z0-9_.@/-]+")
_MONTH_RE = re.compile(r"(\d{4})-(\d{2})\.jsonl")


def directory() -> Path:
    return paths.home() / "witnessed"


def _utc(at: datetime) -> datetime:
    return at.astimezone(UTC) if at.tzinfo else at.replace(tzinfo=UTC)


def _iso(at: datetime) -> str:
    return _utc(at).isoformat().replace("+00:00", "Z")


def _parse(v: Any) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return _utc(at)


def month_file(at: datetime, root: Path | None = None) -> Path:
    at = _utc(at)
    return (root or directory()) / f"{at.year:04d}-{at.month:02d}.jsonl"


def start(root: Path | None = None) -> datetime | None:
    """The instant the log begins, or None before it was written (or when it cannot be read)."""
    try:
        return _parse((root or directory()).joinpath("start").read_text(encoding="utf-8").strip())
    except OSError:
        return None


def ensure_start(now: datetime | None = None, root: Path | None = None) -> datetime:
    """Write `start` once, at the agent's start, when it is absent; the instant the log begins."""
    got = start(root)
    if got is not None:
        return got
    d = root or directory()
    d.mkdir(parents=True, exist_ok=True)
    at = _utc(now or datetime.now(UTC))
    (d / "start").write_text(_iso(at) + "\n", encoding="utf-8")
    return at


def _month_index(at: datetime) -> int:
    return at.year * 12 + at.month - 1


def boundary(now: datetime | None = None) -> datetime:
    """The first instant of the oldest month kept, counted from the calendar, never from the files present."""
    i = _month_index(_utc(now or datetime.now(UTC))) - (WITNESS_KEEP_MONTHS - 1)
    return datetime(i // 12, i % 12 + 1, 1, tzinfo=UTC)


def covers_from(now: datetime | None = None, root: Path | None = None) -> datetime:
    """How far back the log covers: the later of `start` and the retention boundary."""
    b = boundary(now)
    s = start(root)
    return max(b, s) if s is not None else b


def read_month(f: Path) -> list[dict[str, Any]]:
    """A month file's records; an unreadable line is skipped."""
    out: list[dict[str, Any]] = []
    try:
        lines = f.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and _parse(r.get("at")) is not None:
            out.append(r)
    return out


def records(root: Path | None = None) -> list[dict[str, Any]]:
    """Every record kept, sorted by `at`."""
    d = root or directory()
    files = sorted(f for f in d.glob("*.jsonl") if _MONTH_RE.fullmatch(f.name)) if d.is_dir() else []
    got = [r for f in files for r in read_month(f)]
    return sorted(got, key=lambda r: _parse(r["at"]) or datetime.min.replace(tzinfo=UTC))


def new_id(at: datetime, taken: Iterable[str] = ()) -> str:
    """`w-<YYYYMMDDTHHMMSSZ>-<4 hex>`, drawn again while it collides with one in `taken`."""
    held = set(taken)
    stem = f"w-{_utc(at).strftime('%Y%m%dT%H%M%SZ')}-"
    while True:
        got = stem + secrets.token_hex(2)
        if got not in held:
            return got


def append(kind: str, repo: str, text: str, at: datetime | None = None, root: Path | None = None) -> dict | None:
    """Write one record — the one entry point, run on the agent's loop. None, and nothing written, for a
    kind not in `KINDS`, an `at` before `start`, or a log with no `start` yet. `text` is one line."""
    if kind not in KINDS:
        raise ValueError(f"{kind!r} is not a witness kind ({', '.join(KINDS)})")
    when = _utc(at or datetime.now(UTC))
    begun = start(root)
    if begun is None or when < begun:
        return None
    f = month_file(when, root)
    taken = [str(r.get("id")) for r in read_month(f)]
    rec = {
        "id": new_id(when, taken),
        "at": _iso(when),
        "kind": kind,
        "repo": repo or "",
        "text": " ".join(str(text).split()),
    }
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def prune(now: datetime | None = None, root: Path | None = None) -> list[str]:
    """Delete the month files older than the months kept; the names removed."""
    d = root or directory()
    if not d.is_dir():
        return []
    oldest = _month_index(boundary(now))
    gone: list[str] = []
    for f in d.glob("*.jsonl"):
        m = _MONTH_RE.fullmatch(f.name)
        if m and int(m[1]) * 12 + int(m[2]) - 1 < oldest:
            try:
                f.unlink()
            except OSError as e:
                log.warning("pruning the witness log's %s failed: %s", f.name, e)
                continue
            gone.append(f.name)
    return sorted(gone)


def repo_named(dir: Any, roots: Iterable[str]) -> str | None:
    """The registry name (the root's basename) of the registered repo `dir` is in — its real path matched
    against each root's — else None; an empty `dir` is in none."""
    if not isinstance(dir, str) or not dir.strip():
        return None
    try:
        here = Path(os.path.realpath(dir))
    except (OSError, ValueError):
        return None
    best: Path | None = None
    for r in roots:
        try:
            root = Path(os.path.realpath(r))
        except (OSError, ValueError):
            continue
        if (here == root or here.is_relative_to(root)) and (best is None or len(root.parts) > len(best.parts)):
            best = root
    return best.name if best is not None else None
