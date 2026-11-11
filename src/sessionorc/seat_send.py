"""The send's choice of record for a scaled seat (design §4.9 *Mail to a scaled seat*, §6 rule 3 *An extra seat*,
td-max, TD-1547): a seat and its extras are one seat, so mail addressed to the seat's name goes to its first free live
record in place order, else stays on the own record, else — the own record live and busy, no live record free, an
`ask` — fills the seat's lowest-placed held extra and lands there. Pure: the host agent (`MailMixin._seat_pick`)
reads the records, the gate and the host cap, and lands the mail; this module only reads what it is handed."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sessionorc import work as work_mod
from sessionorc.agent_common import on_its_own
from sessionorc.models import TOLD, Session

DEAD = work_mod.DEAD
BUSY = ("working", "needs-you")


@dataclass
class Choice:
    """Where the send lands: `to` the record's id; `fill` the held extra the send fills (it is `to`); `words` the
    keyword `mail.read_when` takes as `extras` (`{fill: name}`, `{waits: why}` or `{lands: True}`), or None."""

    to: str
    fill: Session | None = None
    words: dict[str, Any] | None = None


def line_of(r: Session) -> str:
    """The seat a record is an extra of (its `scale.line`), or '' — a record carrying `seat` alone is a seat's own."""
    return str(r.scale.get("line") or "") if r.seat is not None and isinstance(r.scale, dict) else ""


def place(r: Session, line: str) -> tuple[int, str]:
    """An extra's place among its seat's extras: the number its name carries after `<line>-`, read, never stored."""
    k = r.name[len(line) + 1 :] if (r.name or "").startswith(f"{line}-") else ""
    return (int(k) if k.isdigit() else 1 << 30, r.name or "")


def extras_in_place(own: Session, records: Iterable[Session]) -> list[Session]:
    """The seat's extras, lowest-placed first: records carrying `seat` whose `scale.line` names the own record's
    name, of its team and repo (as `mail.seat_records` reads them), never one superseded."""
    name = own.name
    out = [
        r
        for r in records
        if r is not own
        and r.id != own.id
        and line_of(r) == name
        and r.team == own.team
        and r.repo == own.repo
        and not r.superseded_by
    ]
    return sorted(out, key=lambda r: place(r, name))


def stopping(r: Session, now: datetime) -> bool:
    """A wrap-up under way, its run's end passed, paused by the usage gate, or suspended: live and neither busy nor
    free (§4.9 *An own record that is live but neither busy nor free*)."""
    if r.wrapup_sent_at or r.wrapup_at or r.gated or r.suspended:
        return True
    if r.run_until:
        try:
            return datetime.fromisoformat(r.run_until.replace("Z", "+00:00")) <= now
        except ValueError:
            return False
    return False


def unreported(r: Session) -> bool:
    """Filled and not yet reported on by any hook (§4.2: before its first hook): it reads its mailbox at its first
    turn, so it counts as free — a burst of asks fills one extra, not one each."""
    return r.hook_seen_at is None and r.confidence not in TOLD


def free(r: Session, now: datetime, *, away: bool = False) -> bool:
    """Free (§4.9 *Mail to a scaled seat*): live, reachable, not stopping, and idle at the composer — neither
    working (on its own included) nor waiting on the person — or filled and not yet reported on by any hook."""
    if r.state in DEAD or away or stopping(r, now):
        return False
    if r.state in ("working", "idle") and unreported(r):
        return True
    return r.state == "idle" and not on_its_own(r, now)


def busy(r: Session, now: datetime, *, away: bool = False) -> bool:
    """Busy: live, reachable, not stopping, and `working` (on its own included, §4.2) or `needs-you`."""
    if r.state in DEAD or away or stopping(r, now) or unreported(r):
        return False
    return r.state in BUSY or (r.state == "idle" and on_its_own(r, now))


def choose(
    own: Session,
    extras: list[Session],
    *,
    kind: str,
    now: datetime,
    root: str = "",
    pr: int | None = None,
    closes_seat_question: bool = False,
    away: Callable[[Session], bool] = lambda r: False,
    filling: Iterable[str] = (),
    evicting: Iterable[str] = (),
    held: list[Session] | None = None,
    guard: Callable[[Session], str | None] = lambda r: None,
    skip: str = "",
) -> Choice:
    """The record of the seat `own` (its extras `extras`, in place order) that takes mail of `kind`, in the order
    §4.9 *Mail to a scaled seat* gives:

    1. a `note`, and a `reply` that closes no question a record of the seat asked (`closes_seat_question`), goes to
       the own record alone, never moved — on a thread an extra answered too (§4.9: *the extras never see it*);
    2. on a thread (`root`) a live record of the seat sent or answered — its outbox holds an entry of the thread —
       that record keeps it;
    3. an `ask` carrying `pr` that a live record of the seat already holds an ask about stays with that record;
    4. the first free live record in place order — the own record, then the extras — a held extra the send is
       filling (`filling`) among them, one the eviction is closing (`evicting`) never;
    5. the own record not live (held, never filled, `exited`): the own record, filled on its cause as today;
    6. the own record live and busy, an `ask`: the lowest-placed of `held` (the held extras that may be filled,
       in place order) unless `guard` says why not (*host full, <n> live*, *its profile is paused*) or there is
       none (*every extra busy*) — then the own record, where it waits;
    7. the own record live and neither busy nor free (`limited`, `unreachable`, paused, wrapping up, `stalled?`):
       the own record, no extra filled.

    `skip` is the id of the ask being chosen again (the tick's mover): it is never its own reason to stay."""
    filling, evicting = set(filling), set(evicting)
    seat = [own, *extras]

    def live(r: Session) -> bool:
        return r.id not in evicting and (r.state not in DEAD or r.id in filling)

    ask = kind == "ask"
    if kind == "note" or (kind == "reply" and not closes_seat_question):
        return Choice(own.id)
    if root:
        for r in seat:
            if live(r) and any(e.root == root for e in r.outbox):
                return Choice(r.id, words={"lands": True} if ask and r is not own else None)
    if ask and pr is not None:
        for r in seat:
            if live(r) and any(e.kind == "ask" and e.pr == pr and e.id != skip for e in r.inbox):
                return Choice(r.id, words={"lands": True} if r is not own else None)
    for r in seat:
        if r.id in evicting:
            continue
        if r.id in filling:  # a held extra this home's send is filling now: it takes the burst, no second fill
            return Choice(r.id, words={"fill": r.name} if ask else None)
        if free(r, now, away=away(r)):
            return Choice(r.id, words={"lands": True} if ask and r is not own else None)
    if own.state in DEAD or not ask or not busy(own, now, away=away(own)):
        return Choice(own.id)
    pool = [r for r in held or [] if r.id not in filling and r.id not in evicting]
    if not pool:
        return Choice(own.id, words={"waits": "every extra busy"})
    why = guard(pool[0])
    if why:
        return Choice(own.id, words={"waits": why})
    return Choice(pool[0].id, fill=pool[0], words={"fill": pool[0].name})
