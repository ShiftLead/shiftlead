"""Stuck work (design §6 rule 13 *Stuck work*, TD-1470, built by TD-1496): whether open work has a live session
able to act on it, read at the home each tick.

The work is of two kinds, each with its **actors**: an open `ask` to a session (its addressees, each walked to
its newest record) and a decided board line waiting on a session (its holders, else its lanes' records). This
module holds the parts that need no host agent: which asks are open (`open_asks`), whether one actor is acting
and, where it is not, its reason and its clock (`judge`), and the work's reading from its actors (`reading`).
The tick's `_stuck_pass` gathers the inputs — the walk, `unanswered.read`'s stamp, rule 3's `unfillable` — and
keeps the result on `host.json` as `stuck`. It rings no session and presses nothing."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sessionorc import agent_common, mail
from sessionorc.models import PERSON, MailEntry, Session

ENDED = ("exited", "closed")


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def iso(t: datetime) -> str:
    return t.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _latest(*values: Any) -> datetime | None:
    times = [t for v in values if (t := v if isinstance(v, datetime) else _when(v)) is not None]
    return max(times) if times else None


def persons_own(r: Session) -> bool:
    """A person's own live session (§6 rule 13 *Never stuck*): started by hand (`mail.by_person`), not unattended,
    in no team. Beside other actors it is passed over; work whose only actors are such is never stuck. A member
    the person took over is not one: it reads `taken_over`."""
    return r.state not in mail._NOT_LIVE and not r.unattended and not r.team and mail.by_person(r)


def open_asks(records: Mapping[str, Session]) -> list[MailEntry]:
    """Every open `ask` to a session (§6 rule 13 *The work it reads*), once per id, in the order the records hold
    them: an `ask` open in a session's mailbox — a handed entry among them — never one whose `to` includes the
    person, nor one a seat passed up (`passed_up`). A `steer` is never one: it lapses to its default."""
    seen: set[str] = set()
    out: list[MailEntry] = []
    for r in records.values():
        for e in r.inbox:
            if e.id in seen or e.kind != "ask" or not e.open or e.passed_up or PERSON in e.to:
                continue
            seen.add(e.id)
            out.append(e)
    return out


def fillable_seat(r: Session, unfillable: Mapping[str, str]) -> bool | str:
    """For a supervised, unattended seat whose record is not live (§6 rule 13 *Acting*, `seat_unable`'s exited or
    closed branch): True where rule 3 fills it — no `unfillable` word this tick and not held (`stop_held`) —, the
    word where `unfillable` holds one; False for any other record."""
    if not r.seat or not (r.supervised and r.unattended) or r.state not in ENDED:
        return False
    if why := unfillable.get(r.id):
        return str(why)
    return not isinstance(r.stop_held, Mapping)


@dataclass
class Actor:
    """One actor's reading: `acting`, else its `reason` and its clock `since` (floored at the work's open time).
    `own` marks a person's own session, which is passed over."""

    id: str
    host: str
    name: str
    acting: bool = False
    reason: dict[str, Any] | None = None
    since: datetime | None = None
    own: bool = False


def judge(
    r: Session | None,
    address: str,
    stamp: Mapping[str, Any],
    *,
    unfillable: Mapping[str, str],
    open_at: datetime,
    idle_clock: datetime | None,
    now: datetime,
) -> Actor:
    """One actor read as rule 13 reads it. `stamp` is `unanswered.read`'s for `r` (the walk's last record, None:
    gone), `idle_clock` what an `idle` actor gives for this work (an ask: its copy's `read_at`; an order: its
    `stuck_open` `at`), `open_at` the work's open time, which floors every figure."""
    if r is None:
        return Actor(address, "", address, reason={k: v for k, v in stamp.items() if k != "at"}, since=open_at)
    a = Actor(address, r.host or "", r.name or address)
    if persons_own(r):
        a.own = True
        return a
    seat = fillable_seat(r, unfillable)
    figure: datetime | None
    if seat is True:
        a.acting = True
        return a
    if isinstance(seat, str):
        # a seat rule 3 would not fill: this rule's own reason, its word drawn as is (never through `words`)
        a.reason, figure = {"state": "unfillable", "why": seat}, agent_common.idle_from(r)
    elif r.state == "stalled?" and r.stalled_ticks >= 2:
        # the instant nothing new began: the later of its work and screen clocks (§4.2 *Liveness cross-check*)
        figure = _latest(r.work_at, r.screen_at)
        a.reason = {"state": "stalled", **({"since": iso(figure)} if figure else {})}
    elif stamp.get("state") == "working":
        a.acting = True
        return a
    elif stamp.get("state") == "idle":
        if agent_common.on_its_own(r, now):
            a.acting = True  # a live subagent or background shell is working (§4.2 *Working on its own*)
            return a
        start = agent_common.idle_from(r)
        a.reason = {"state": "idle", **({"since": iso(start)} if start else {})}
        figure = _latest(idle_clock, r.subagent_at, r.shells_at)
    else:
        # the stamp without its read instant, so a reason that stands is the same reason every tick (no rewrite)
        a.reason, figure = {k: v for k, v in stamp.items() if k != "at"}, agent_common.idle_from(r)
    a.since = max(figure, open_at) if figure is not None else open_at
    return a


def ask_idle_clock(r: Session | None, ask_id: str) -> datetime | None:
    """An `idle` actor's clock for a question (§6 rule 13 *The clock*): the later of its copy's `read_at` in the
    walk's last record's mailbox and that record's `created`, or, unread there, the record's `since` — a turn that
    woke for other mail and ended with it open moved nothing."""
    if r is None:
        return None
    copy = next((e for e in r.inbox if e.id == ask_id), None)
    if copy is not None and copy.read_at:
        return _latest(copy.read_at, r.created)
    return _when(r.since)


def reading(actors: Iterable[Actor], now: datetime, wait: timedelta) -> dict[str, Any] | None:
    """The work's `stuck` entry, `{since, reason, actor}`, or None while it is not stuck (§6 rule 13): an actor
    acting, `since` (the newest figure among the actors) not yet older than `wait`, or its only actors the
    person's own sessions. `reason` and `actor` are the first actor's (in the order given), `more` the rest."""
    others = [a for a in actors if not a.own]
    if not others or any(a.acting for a in others):
        return None
    since = max(a.since for a in others if a.since is not None)
    if now - since <= wait:
        return None
    first = others[0]
    actor = {"id": first.id, "host": first.host, "name": first.name, "more": len(others) - 1}
    return {"since": iso(since), "reason": dict(first.reason or {}), "actor": actor}


def shape_ok(key: str, value: Any) -> bool:
    """A `stuck` entry as `HostStore.load` keeps it: a key `ask:<id>` or `board:<key>`, a `since` and a `reason`;
    a `board:` entry carries its `repo`."""
    if not isinstance(value, Mapping) or not isinstance(value.get("since"), str):
        return False
    if not isinstance(value.get("reason"), Mapping) or not isinstance(value["reason"].get("state"), str):
        return False
    if key.startswith("board:"):
        return isinstance(value.get("repo"), str) and bool(value["repo"])
    return key.startswith("ask:")


def open_shape_ok(key: str, value: Any) -> bool:
    """A `stuck_open` entry as `HostStore.load` keeps it: `board:<key>` → `{at, repo, holder?, asked?}`."""
    if not key.startswith("board:") or not isinstance(value, Mapping):
        return False
    if not isinstance(value.get("at"), str) or _when(value["at"]) is None:
        return False
    if not isinstance(value.get("repo"), str) or not value["repo"]:
        return False
    with contextlib.suppress(KeyError):
        if not isinstance(value["holder"], bool):
            return False
    with contextlib.suppress(KeyError):
        if not isinstance(value["asked"], bool):
            return False
    return True
