"""On-disk session records and the hook event queue under `~/.shiftlead/`.

The host agent is the only writer of `sessions/*.json`. Hook scripts talk to the agent's socket;
when the agent is down they append to `events/<session>.jsonl`, which the agent drains on its
next tick, so a hook never blocks on the agent and no state transition is lost.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc import paths
from sessionorc.models import MailEntry, Session


def _read_umask() -> int:
    old = os.umask(0)
    os.umask(old)
    return old


# read once, at import: `os.umask` is process-wide, so reading it per write would race other threads
_UMASK = _read_umask()


def _atomic_write(path: Path, text: str, *, mode: int | None = None) -> None:
    """`text` to `path` through a temporary file of its own in the same directory, then one rename.
    Each write's temporary is unique (TD-643): two saves of one path on two threads once shared a
    fixed `<name>.tmp`, and the second rename found it already moved (*No such file or directory*)."""
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        # A file whose contents are evidence is created with its mode, never chmod'ed after: a
        # world-readable window, however short, is a window (design §4.8a). mkstemp creates it 0600.
        os.fchmod(fd, mode if mode is not None else 0o666 & ~_UMASK)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise


class SessionStore:
    def __init__(self, root: Path | None = None):
        self.root = root or paths.sessions_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, session_id: str) -> Path:
        return self.root / f"{session_id}.json"

    def load(self, session_id: str) -> Session | None:
        p = self.path(session_id)
        if not p.is_file():
            return None
        return Session.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def load_all(self) -> dict[str, Session]:
        out: dict[str, Session] = {}
        for p in sorted(self.root.glob("*.json")):
            try:
                s = Session.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError):
                continue  # a half-written or foreign file never takes the agent down
            out[s.id] = s
        return out

    def save(self, session: Session) -> None:
        _atomic_write(self.path(session.id), json.dumps(session.to_dict(), indent=1))

    def delete(self, session_id: str) -> None:
        self.path(session_id).unlink(missing_ok=True)


class PersonInboxStore:
    """The person inbox's file (design §4.10): a list of entries, written whole on every change and
    reloaded on restart. A missing or unreadable file is an empty inbox, never a crash.

    `rev` is the inbox's revision (design §4.4 *Each reading has one owner*, TD-616): bumped by every
    save, and `on_save` told it, which is how the host agent pushes `inbox` on every change without
    each writer remembering to. It starts at the clock's milliseconds, so a restart never hands a
    reader a revision it already holds for other contents."""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.person_inbox_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rev = time.time_ns() // 1_000_000
        self.on_save: Callable[[int], None] | None = None

    def load(self) -> list[MailEntry]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [MailEntry.from_dict(d) for d in raw.get("entries", [])]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return []

    def save(self, entries: list[MailEntry]) -> None:
        _atomic_write(self.path, json.dumps({"entries": [e.to_dict() for e in entries]}, indent=1))
        self.rev += 1
        if self.on_save is not None:
            self.on_save(self.rev)


class AttentionStore:
    """The attention trail and the state-row snoozes (design §4.10 *The Inbox is a queue*, TD-079).
    One file holding two things that belong to the **home** rather than to any record: `trail`, the
    endings of the state rows the Inbox showed, newest first; and `snoozed`, a person's *not now*
    per record and row kind. Written whole on every change; a missing or unreadable file is an
    empty trail and no snoozes, never a crash — the same rule the person inbox follows.

    A third, `notified` (§4.10 *Told on Telegram when nobody is looking*, TD-319): the rows the home
    told the person about, `{row key: when}`, held on the store itself and written with every save, so
    a restart does not tell a standing row twice. A key leaves when its row ends."""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.attention_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.notified: dict[str, str] = {}

    def load(self) -> tuple[list[dict[str, Any]], dict[str, str]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            trail = [d for d in raw.get("trail", []) if isinstance(d, dict) and d.get("id")]
            snoozed = {str(k): str(v) for k, v in (raw.get("snoozed") or {}).items() if v}
            told = raw.get("notified") or {}
            self.notified = {str(k): str(v) for k, v in told.items() if v} if isinstance(told, dict) else {}
            return trail, snoozed
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return [], {}

    def save(self, trail: list[dict[str, Any]], snoozed: dict[str, str]) -> None:
        doc = {"trail": trail, "snoozed": snoozed, **({"notified": self.notified} if self.notified else {})}
        _atomic_write(self.path, json.dumps(doc, indent=1))


class UsageStore:
    """The last good usage reading per profile (TD-087), `{profile: {windows, fetched}}`.

    In memory it was forgotten by every promote, and the agent then polled at once — eight
    promotes in one day against an endpoint that answers 429 — and the chip vanished each time
    rather than going stale. The agent seeds its first poll from the kept `fetched`, so a promote
    keeps the allowance as well as the chip. Only a **reading** is kept: why the last poll failed is the running
    agent's business and means nothing after a restart. A missing or unreadable file is no
    readings, never a crash."""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.usage_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(k): v for k, v in raw.items() if isinstance(v, dict) and v.get("windows") is not None}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return {}

    def save(self, readings: dict[str, dict[str, Any]]) -> None:
        keep = {k: {"windows": v.get("windows"), "fetched": v.get("fetched")} for k, v in readings.items()}
        _atomic_write(self.path, json.dumps(keep, indent=1))


class RepoStore:
    """The repo facts per checkout (design §4.4 *Repo facts*, TD-176), `{root: reading}`, written
    whole each time a reading changes. A missing or unreadable file is no readings, never a crash:
    the next read, five minutes on, fills it."""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.repos_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            return {}

    def save(self, readings: dict[str, dict[str, Any]]) -> None:
        _atomic_write(self.path, json.dumps(readings, indent=1))


class HostStore:
    """The home's own `host` record (design §6 *Balance*, TD-239), `{teams: {<team>: {...}},
    last_tick?, ci_spells?}` — `last_tick` the agent's newest tick (§4.5 row 5 (b), TD-490), `ci_spells`
    the *CI not starting* rows' spells by owner (§4.4, TD-687) — written whole each
    time it changes. A missing or unreadable file is an empty record, never a crash: the
    next tick writes what stands."""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.host_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"teams": {}}
        teams = raw.get("teams") if isinstance(raw, dict) else None
        rec: dict[str, Any] = {
            "teams": {str(k): v for k, v in teams.items() if isinstance(v, dict)} if isinstance(teams, dict) else {}
        }
        if isinstance(raw, dict) and isinstance(raw.get("last_tick"), str):
            rec["last_tick"] = raw["last_tick"]
        spells = raw.get("ci_spells") if isinstance(raw, dict) else None
        if isinstance(spells, dict) and (kept := {str(k): v for k, v in spells.items() if isinstance(v, dict)}):
            rec["ci_spells"] = kept
        return rec

    def save(self, record: dict[str, Any]) -> None:
        _atomic_write(self.path, json.dumps(record, indent=1))


def _instant(at: Any) -> datetime | None:
    """An entry's `at` as an aware instant, or None where it cannot be read as one."""
    try:
        t = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def kept(
    ring: list[dict[str, Any]], now: datetime, keep: int = 50, per_doer: int = 5, quiet_days: int = 30
) -> list[dict[str, Any]]:
    """What a team's doing log keeps (design §4.8 *the doing log*, TD-702): its last `keep` calls,
    and beside them each doer's newest `per_doer` — a doer is the call's `id`, `""` for none — for
    every doer whose newest call is younger than `quiet_days`, in the ring's order. *Newest* is the
    latest position; `at` is read only to judge quiet, and one that cannot be read is quiet."""
    keep_at = set(range(max(0, len(ring) - keep), len(ring)))
    by: dict[str, list[int]] = {}
    for i, e in enumerate(ring):
        by.setdefault(str(e.get("id") or ""), []).append(i)
    quiet = timedelta(days=quiet_days)
    for at in by.values():
        newest = _instant(ring[at[-1]].get("at"))
        if newest is not None and now - newest < quiet:
            keep_at.update(at[-per_doer:])
    return [ring[i] for i in sorted(keep_at)]


class DoingLogStore:
    """The doing log (design §4.8 *the doing log*, TD-176 slice 2): per team, the last `keep` `ao
    doing` calls and each doer's newest `per_doer` (`kept`, TD-702), in memory and in `doing.jsonl`
    — one line appended per call, the file rewritten from the rings once it holds `compact_at`
    lines, so it stays bounded without a rewrite per call. The rule is applied at load and to a
    team's ring at each of its calls, by the home's clock. A missing file is an empty log; an
    unreadable line is skipped, never a crash."""

    def __init__(self, path: Path | None = None, keep: int = 50, compact_at: int = 2000, per_doer: int = 5):
        self.path = path or paths.doing_log_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.keep, self.compact_at, self.per_doer = keep, compact_at, per_doer
        self.rings: dict[str, list[dict[str, Any]]] = {}
        self._lines = 0
        try:
            # a line cut short mid-character by a crash decodes as garbage and is skipped below, never a crash
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("team"):
                self._ring(str(e["team"])).append(e)
        now = datetime.now(UTC)
        for team, ring in self.rings.items():
            self.rings[team] = kept(ring, now, self.keep, self.per_doer)
        self._lines = len(lines)

    def _ring(self, team: str) -> list[dict[str, Any]]:
        return self.rings.setdefault(team, [])

    def append(self, entry: dict[str, Any]) -> None:
        team = str(entry["team"])
        self.rings[team] = kept([*self._ring(team), entry], datetime.now(UTC), self.keep, self.per_doer)
        if self._lines + 1 >= self.compact_at:
            _atomic_write(self.path, "".join(json.dumps(e) + "\n" for r in self.rings.values() for e in r))
            self._lines = sum(len(r) for r in self.rings.values())
            return
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        self._lines += 1


class IdentityAlarmStore:
    """The host's **own** identity alarms (design §4.8a, TD-077 step 2): the ones about no record —
    a claim from outside every pane, an unreadable peer — which have nowhere else to live, since a
    record's alarms ride that record's file. One small `0600` file beside `sessions/`, written
    whole. A missing or unreadable file is no alarms, never a crash; the agent's log has every one
    of them either way, so nothing is lost by a file that could not be read.

    `identity_tally` is deliberately *not* here: it counts connections **since the agent started**
    (§4.8a), and a number that outlived the process would say something else."""

    def __init__(self, path: Path | None = None):
        self.path = path or paths.identity_alarms_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [a for a in raw.get("alarms", []) if isinstance(a, dict)]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return []

    def save(self, alarms: list[dict[str, Any]]) -> None:
        _atomic_write(self.path, json.dumps({"alarms": alarms}, indent=1), mode=0o600)


class EventQueue:
    """Append-only per-session JSONL, drained by the agent."""

    def __init__(self, root: Path | None = None):
        self.root = root or paths.events_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, session_id: str, event: dict[str, Any]) -> None:
        with (self.root / f"{session_id}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def drain(self) -> list[tuple[str, dict[str, Any]]]:
        """Return and remove every queued event, oldest first per session."""
        out: list[tuple[str, dict[str, Any]]] = []
        for p in sorted(self.root.glob("*.jsonl")):
            sid = p.stem
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
                p.unlink()
            except OSError:
                continue
            for line in lines:
                try:
                    out.append((sid, json.loads(line)))
                except ValueError:
                    continue
        return out
