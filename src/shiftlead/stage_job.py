"""Which one act the tick takes on a built-in seat's job (design §4.9d *How each one runs*, TD-2053).

Board answers and pull requests nobody holds are jobs: a decided board line, or a pull request, is the job's
**object**, and its record on the state branch (`StageStore.job`, `jobs/<key>.json`, keyed `board-<item id>` or
`pr-<number>`) names the seat, the team whose host and flow it runs under, its holder and its offers, and what it waits
on. This module is pure, as `stage_acts` is: `choose` names the first act whose condition holds, and `order` says which
of a seat's jobs is offered next, since **each seat runs one job session at a time in a repo**. Starting the session,
writing the record and the home's board line are later slices of TD-2053.

A job's record enters its team's flow at `work-pushed`, as a record of the stage that takes `other` entries would; from
then on, while it is not at that stage, an entry's acts (`stage_acts`) move it, and only Reconcile's job cases here
still apply. `JobReading.at_job_stage` says which.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from shiftlead.stage_acts import SECOND_LOSS, Holder

SEATS = ("board-answers", "unheld-pull-requests")

JobActName = Literal["reconcile", "offer", "offer-again"]


def key_of(seat: str, obj: str | int) -> str:
    """A job's key: `board-<item id>` for a decided board line, `pr-<number>` for a pull request nobody holds."""
    if seat == "board-answers":
        return f"board-{obj}"
    if seat == "unheld-pull-requests":
        return f"pr-{int(obj)}"
    raise ValueError(f"a job's seat is one of {SEATS}, not {seat!r}")


@dataclass(frozen=True)
class JobReading:
    """What the home read about one job's object, its record's team and its holder.

    `live`: the object still asks for the job — a board line open and decided, or a pull request open. `own_pr`: the
    state of the pull request a board answer's job opened (None: none yet). `person_line`: the home's own board line the
    job waits on, `open` or `closed` (None: not read, or the record names none). `team_started`: the record's team is
    started; `first_started`: the first, by name, of the repo's started teams. `seat_busy`: a job session of this seat
    is live in the repo, so no other job of the seat starts one."""

    live: bool = True
    own_pr: Literal["open", "merged", "closed"] | None = None
    person_line: Literal["open", "closed"] | None = None
    team_started: bool = True
    first_started: str | None = None
    at_job_stage: bool = True  # the record is at the job's own stage, or has not yet entered the flow
    stage_known: bool = True  # the record's stage is in its team's flow
    holder: Holder | None = None
    may_start: bool = False  # the team is started, inside its schedule and not held by the usage gate
    seat_busy: bool = False


@dataclass(frozen=True)
class JobAct:
    name: JobActName
    case: str = ""
    counted: bool = True  # offer-again: whether this loss spends an offer


def new_job(seat: str, obj: str | int, team: str, opened_at: str) -> dict[str, Any]:
    """A job's record, written when the job is first offered; `opened_at` is when its object asked for it."""
    return {
        "id": key_of(seat, obj),
        "seat": seat,
        "object": str(obj),
        "team": team,
        "flow": None,
        "stage": None,
        "holder": None,
        "branch": None,
        "pr": None,
        "entered_at": opened_at,
        "counts": {},
        "moves": 0,
        "offers": 0,
        "waits": None,
        "person_line": None,
        "verdicts": {},
        "history": [],
        "closed_at": None,
    }


def _reconcile(record: Mapping[str, Any], s: JobReading) -> str | None:
    waits = record.get("waits")
    if not s.live:
        return "object-gone"  # closed, its holder ended and the home's own line closed
    if record.get("seat") == "board-answers" and s.own_pr == "closed" and waits != "person":
        return "pr-closed"  # its line still decided: to the person, never offered again until that line is closed
    if waits == "person":
        return "person-cleared" if s.person_line == "closed" else None
    if waits == "merging":
        return None  # the home's own merge closes the record itself
    if not record.get("holder"):
        if not s.team_started and s.first_started and s.first_started != record.get("team"):
            return "team-moved"
        if not s.stage_known:
            return "stage-gone"  # as team-moved: a fresh job session, never the person
    return None


def _offer_again(record: Mapping[str, Any], holder: Holder, s: JobReading) -> JobAct | None:
    if not s.may_start:
        return None
    if holder.ended_by_stop:
        return JobAct("offer-again", "stopped", counted=False)
    if int(record.get("offers") or 0) >= SECOND_LOSS:
        return JobAct("offer-again", "to-person")
    return JobAct("offer-again", "lost" if holder.lost else "silent")


def choose(record: Mapping[str, Any] | None, s: JobReading) -> JobAct | None:
    """The one act this pass takes on a job (`record` None: an object with no record yet), or None."""
    if record is None or record.get("closed_at"):
        if s.live and s.may_start and not s.seat_busy:
            return JobAct("offer", "new")  # an object back after its record closed is a new job
        return None
    if case := _reconcile(record, s):
        return JobAct("reconcile", case)
    if record.get("waits") or not s.at_job_stage:
        return None  # waiting, or in its team's flow past the job's stage, where an entry's acts move it
    if record.get("holder"):
        h = s.holder
        if h is not None and (h.lost or h.silent or h.ended_by_stop):
            return _offer_again(record, h, s)
        return None
    return JobAct("offer") if s.may_start and not s.seat_busy else None


def order(records: Iterable[Mapping[str, Any]], objects: Mapping[str, str]) -> list[str]:
    """The keys of one seat's jobs that want a session, in the order they are offered: records already begun (open,
    no holder, waiting on nothing) before objects with no open record, each oldest first. `objects` maps the key of
    each object the seat's trigger names to when it asked (an ISO time)."""
    begun = [r for r in records if not r.get("closed_at") and not r.get("holder") and not r.get("waits")]
    keys = {str(r["id"]) for r in begun}
    first = sorted(begun, key=lambda r: (str(r.get("entered_at") or ""), str(r["id"])))
    rest = sorted(((at, k) for k, at in objects.items() if k not in keys), key=lambda p: (str(p[0]), p[1]))
    return [str(r["id"]) for r in first] + [k for _at, k in rest]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def offered(record: Mapping[str, Any], holder: str, act: JobAct) -> dict[str, Any]:
    """The record an offer writes: `holder` named, and a counted offer spent."""
    offers = int(record.get("offers") or 0)
    spent = offers + 1 if act.counted else max(offers, 1)
    return {**record, "holder": holder, "offers": spent}


def to_person(record: Mapping[str, Any], line: str) -> dict[str, Any]:
    """The job waits on the person: the home's plain board line `line` (its id) named, and no holder."""
    return {**record, "holder": None, "waits": "person", "person_line": line}


def cleared(record: Mapping[str, Any]) -> dict[str, Any]:
    """The person closed the home's line: the wait and the counts cleared, the job offered afresh."""
    return {**record, "waits": None, "person_line": None, "offers": 0, "counts": {}, "moves": 0}


def moved(record: Mapping[str, Any], team: str) -> dict[str, Any]:
    """Given to `team`: its branch and pull request kept, its counts dropped, to start again at a fresh job session."""
    return {**record, "team": team, "flow": None, "stage": None, "offers": 0, "counts": {}, "moves": 0}


def closed(record: Mapping[str, Any]) -> dict[str, Any]:
    """The job's object is gone: the record closed and its holder cleared."""
    return {**record, "holder": None, "waits": None, "closed_at": _now()}
