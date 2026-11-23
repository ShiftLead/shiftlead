"""Which one act the tick takes on a stage record (design §4.9c *The home acts only where no session will*, TD-2051).

A pure decision: `choose` is given a record and what the home has read about its entry, and names the first act whose
condition holds, so two acts never meet on one record. It reads nothing and writes nothing; making an act is a later
slice of TD-2051, and the sixth act, starting an audit, is TD-2053's.

Reconcile's cases are named in `Act.case`. An act that starts a session is withheld unless the team may start one, and
what is withheld is not passed on to a later act: the record waits for the next pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from shiftlead.stage_work import EntryWork

SILENT_AFTER = timedelta(hours=2)
CLOSED_KEPT = timedelta(days=30)
SECOND_LOSS = 2

ActName = Literal["reconcile", "answer", "pass", "offer-again", "offer"]


@dataclass(frozen=True)
class Holder:
    """What the home read of a record's holder. `held`: stopped, paused or being moved to another login, and still
    there, so its entry waits with it. `stopped`: its session was ended by a Stop or a hold, which spends no offer."""

    ended: bool = False
    lease_lapsed: bool = False
    held: bool = False
    stopped: bool = False
    person: bool = False
    idle_for: timedelta = timedelta(0)
    waiting: bool = False  # an open ask or wait of its own
    permission: bool = False

    @property
    def lost(self) -> bool:
        return not self.person and not self.held and not self.stopped and (self.ended or self.lease_lapsed)

    @property
    def ended_by_stop(self) -> bool:
        return self.ended and self.stopped and not self.held

    @property
    def silent(self) -> bool:
        return (
            not self.person
            and not self.held
            and not self.stopped
            and not self.ended
            and not self.waiting
            and not self.permission
            and self.idle_for >= SILENT_AFTER
        )


@dataclass(frozen=True)
class Reading:
    """What the home read about one entry, from the forge, the ledger, the board, its flow and its sessions."""

    entry: Literal["open", "archived"] = "open"
    pr_state: Literal["open", "merged", "closed"] | None = None
    head: str | None = None  # the open pull request's head, which a passed stage's move to merge carries
    renumbered_to: str | None = None
    design: bool = False
    open_parts: int = 0
    had_parts: bool = False
    archive_open: bool = False  # the home's own pull request archiving this entry is open
    merge_running: bool = False
    team_moved: bool = False
    stage_known: bool = True
    flow_current: bool = True
    gate: bool = False  # the entry carries the home's `decision` gate
    lifted: str | None = None  # the label of the person's answer that lifted it
    nothing_to_read: bool = False  # an `only-when` stage with nothing to read
    holder: Holder | None = None
    may_start: bool = False  # the team is started, inside its schedule and not held by the usage gate
    within_size: bool = False
    pickable: bool = False
    work: EntryWork = EntryWork("none")


@dataclass(frozen=True)
class Act:
    name: ActName
    case: str = ""
    counted: bool = True  # offer-again: whether this loss spends an offer
    work: EntryWork | None = None  # offer: the open pull request an entry's first record carries


_SETTLED = "settled"  # reconcile found the record as it should be, and no later act may take it


def _merged(record: Mapping[str, Any], s: Reading) -> str | None:
    waits = record.get("waits")
    if s.design:
        if s.open_parts:
            return _SETTLED if waits == "parts" else "wait-for-parts"
        if s.had_parts:
            return _SETTLED if s.archive_open else "archive-design"
    return None if waits == "person" else "merged-entry-open"


def _reconcile(record: Mapping[str, Any], s: Reading) -> str | None:
    waits = record.get("waits")
    if waits == "merging" and s.merge_running:  # the home's own merge closes the record itself
        return _SETTLED
    if s.renumbered_to:
        return "renumbered"
    if s.entry == "archived":
        return "close"
    if record.get("intent"):
        return "land-intent"
    settled = False
    if s.pr_state == "merged":
        case = _merged(record, s)
        if case == _SETTLED:
            settled = True  # no later act takes it, but a later case of reconcile still may
        elif case:
            return case
    elif s.pr_state == "closed" and waits != "person":
        return "pr-closed"
    if waits == "merging":
        return "merging"
    if s.team_moved:
        return "team-moved"
    if waits != "person":
        if not s.stage_known:
            return "re-enter" if not record.get("moves") else "stage-gone"
        if not s.flow_current:
            return "rewrite-flow"
        if s.gate and waits is None:
            return "mark-waiting"
    elif not s.gate and s.lifted is None:
        return "gate-again"
    return _SETTLED if settled else None


def _first_offer(s: Reading) -> Act | None:
    """An entry with no record, or a closed record of an entry reopened (§4.9c *Ways in*)."""
    if s.entry != "open" or not s.pickable or s.work.state in ("wait", "unread"):
        return None
    return Act("offer", work=s.work) if s.may_start and s.within_size else None


def _offer_again(record: Mapping[str, Any], holder: Holder, s: Reading) -> Act | None:
    if not s.may_start:
        return None
    if holder.ended_by_stop:
        return Act("offer-again", "stopped", counted=False)
    if int(record.get("offers") or 0) >= SECOND_LOSS:
        return Act("offer-again", "to-person")
    return Act("offer-again", "lost" if holder.lost else "silent")


def choose(record: Mapping[str, Any] | None, s: Reading) -> Act | None:
    """The one act this pass takes on `record` (None for an entry with no record yet), or None."""
    if record is None or record.get("closed_at"):
        return _first_offer(s)
    case = _reconcile(record, s)
    if case == _SETTLED:
        return None
    if case:
        return Act("reconcile", case)
    waits = record.get("waits")
    if waits == "person":
        return Act("answer") if s.lifted is not None else None
    holder = s.holder if record.get("holder") else None
    if holder is None and not record.get("holder") and waits is None:
        if s.nothing_to_read:
            return Act("pass")
        return Act("offer") if s.may_start and s.within_size else None
    if holder is not None and (holder.lost or holder.silent or holder.ended_by_stop):
        return _offer_again(record, holder, s)
    return None


def closed_expired(record: Mapping[str, Any], now: datetime | None = None) -> bool:
    """Whether a closed record has been kept its thirty days and leaves the branch's head."""
    closed = record.get("closed_at")
    if not closed:
        return False
    at = datetime.strptime(str(closed), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - at >= CLOSED_KEPT
