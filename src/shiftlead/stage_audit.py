"""An audit's run record: its clock, its lease and its outcomes (design §4.9c, act 6, TD-2053).

An audit is no stage and takes no entry. Its file on the state branch (`StageStore.audit`, `audits/<team>/<name>.json`)
carries its last run: `started_at`, the `holder` whose claim is the run's lease, the `base` commit that was the default
branch's head when it started, `offers`, and `ended` (`{outcome, reason, at}`) once the run is over: its session's
outcome, one of `OUTCOMES`, or `lost` for a run rested at its second loss.

This module is pure, as `stage_acts` is: `choose` names the one act a pass takes on an audit, and `started`, `again`,
`rested` and `finished` are the record each writes. It reads nothing and writes nothing; starting the session, writing
the record and telling the person are later slices of TD-2053. An audit with no run record yet is not chosen here.

A run lost or silent is offered again once, as an entry's holder is (act 4); lost again, the audit **rests**: the run
ends as `lost`, its clock runs afresh from the second loss (so a `merged-pull-requests` count already past its number
does not start it at once), and the caller tells the person once.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from shiftlead.flow3 import EVERY
from shiftlead.stage_acts import SECOND_LOSS, Holder

OUTCOMES = ("findings-filed", "nothing-found", "other")

AuditActName = Literal["start", "offer-again", "rest"]


@dataclass(frozen=True)
class Clock:
    """An audit's `every`: `n` merged pull requests since the run's base, or `n` hours or days since its start."""

    n: int
    unit: Literal["merged-pull-requests", "hours", "days"]


def clock(every: Any) -> Clock | None:
    """The clock an audit's `every` writes, or None for one the flow check would refuse."""
    text = str(every or "").strip()
    if not EVERY.fullmatch(text):
        return None
    n, unit = text.split(" ", 1)
    return Clock(int(n), unit)  # type: ignore[arg-type]  # EVERY admits only the three units


@dataclass(frozen=True)
class AuditReading:
    """What the home read for one audit. `holder`: the run's holder as `stage_read.holder_on` reads it (None: not read,
    or the run has none). `merged_since`: pull requests merged since the run's base (None: not read)."""

    holder: Holder | None = None
    merged_since: int | None = None
    may_start: bool = False  # the team is started, inside its schedule and not held by the usage gate


@dataclass(frozen=True)
class AuditAct:
    name: AuditActName
    case: str = ""
    counted: bool = True  # offer-again: whether this loss spends an offer


def _at(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def due(run: Mapping[str, Any], every: Clock, s: AuditReading, now: datetime) -> bool | None:
    """Whether the audit's clock has come round since `run` started; None where the count was not read, or the run's
    start cannot be read (a pass with no reading of the audit)."""
    if every.unit == "merged-pull-requests":
        return None if s.merged_since is None else s.merged_since >= every.n
    start = _at(run.get("started_at"))
    if start is None:
        return None
    span = timedelta(hours=every.n) if every.unit == "hours" else timedelta(days=every.n)
    return now - start >= span


def holds_lease(run: Mapping[str, Any], s: AuditReading) -> bool:
    """Whether the run still holds its lease: it has a holder the home has not read as lost (§4.9c, act 6)."""
    if not run.get("holder"):
        return False
    return s.holder is None or not s.holder.lost


def choose(run: Mapping[str, Any] | None, every: Clock | None, s: AuditReading, now: datetime) -> AuditAct | None:
    """The one act this pass takes on an audit whose last run is `run`, or None."""
    if run is None or every is None:
        return None  # an audit's first run, and one whose clock cannot be read, are not chosen here
    if run.get("holder"):
        h = s.holder  # None: the holder was not read, so the run waits for a pass that reads it
        if h is None or not s.may_start or not (h.lost or h.silent or h.ended_by_stop):
            return None
        if h.ended_by_stop:
            return AuditAct("offer-again", "stopped", counted=False)
        if int(run.get("offers") or 0) >= SECOND_LOSS:
            return AuditAct("rest", "lost" if h.lost else "silent")
        return AuditAct("offer-again", "lost" if h.lost else "silent")
    if not holds_lease(run, s) and s.may_start and due(run, every, s, now):
        return AuditAct("start")
    return None


def started(holder: str, base: str, now: datetime) -> dict[str, Any]:
    """The run record a start writes: a fresh run, its clock and count from now and `base`."""
    return {"started_at": _stamp(now), "holder": holder, "base": base, "offers": 1, "ended": None}


def again(run: Mapping[str, Any], holder: str, act: AuditAct) -> dict[str, Any]:
    """The same run offered to `holder`: its start and base stand, and a counted loss spends an offer."""
    offers = int(run.get("offers") or 0)
    return {**run, "holder": holder, "offers": offers + 1 if act.counted else max(offers, 1)}


def rested(run: Mapping[str, Any], act: AuditAct, base: str, now: datetime) -> dict[str, Any]:
    """The run ended by its second loss: no holder, and the clock and count running afresh from now and `base`."""
    why = f"{act.case or 'lost'} twice; the audit waits for its next clock"
    return {
        **run,
        "holder": None,
        "started_at": _stamp(now),
        "base": base,
        "ended": {"outcome": "lost", "reason": why, "at": _stamp(now)},
    }


def end_refusal(outcome: str, reason: str, filed: Sequence[str]) -> str | None:
    """Why `ao stage end` refuses an audit's outcome, or None (§4.9c's outcome table): `findings-filed` names at least
    one entry filed in this run, and `nothing-found` and `other` give a reason."""
    if outcome not in OUTCOMES:
        return f"`{outcome}` is no outcome of an audit; it ends with {', '.join(OUTCOMES)}"
    if outcome == "findings-filed" and not [t for t in filed if str(t).strip()]:
        return "`findings-filed` names at least one entry filed in this run"
    if outcome != "findings-filed" and not reason.strip():
        return f"`{outcome}` needs a reason"
    return None


def finished(run: Mapping[str, Any], outcome: str, reason: str, now: datetime) -> dict[str, Any]:
    """The run ended by its session's outcome: no holder; its start and base stand, so the next clock runs from them."""
    return {**run, "holder": None, "ended": {"outcome": outcome, "reason": reason, "at": _stamp(now)}}
