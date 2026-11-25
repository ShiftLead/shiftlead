"""The write of the one act the tick takes on a built-in seat's job (design §4.9d *How each one runs*, TD-2053).

`stage_job.choose` names the act; `make` writes it on the job's record under the store's lock, as `stage_make` writes an
entry's, after a fresh read still chooses it. What reaches the world — a session's start and its claim on the job's
work order, the home's plain board line and its close — is given as a `JobReach`, so one job's failure is that job's.
A session the write took the record from is named in `Made.end` for the caller to end. Nothing calls this yet; the
home's board line is a later slice of TD-2053.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from shiftlead import stage_job
from shiftlead.stage_job import JobAct, JobReading
from shiftlead.stage_job_start import lane_of
from shiftlead.stage_make import Made, _came
from shiftlead.stagerecord import StageStore

LOST_TWICE = "two job sessions in a row were lost or went silent"
PR_CLOSED = "its pull request was closed unmerged, and its line is still decided"


@dataclass(frozen=True)
class JobReach:
    """How a job's act reaches the world. `start(record, came)` starts the job's session and returns its address, or
    None; `claim(holder, ref)` writes the holder's claim on the job's work order and returns why it was refused, or
    None; `line(record, reason)` adds the home's plain board line naming the seat, the object and the reason and
    returns its id, or None; `close_line(id)` closes that line."""

    start: Callable[[Mapping[str, Any], str | None], str | None]
    claim: Callable[[str, str], str | None]
    line: Callable[[Mapping[str, Any], str], str | None]
    close_line: Callable[[str], None]


def _offer(store: StageStore, record: dict[str, Any], act: JobAct, reach: JobReach) -> Made:
    """Offer and Offer again: a fresh session of the seat holds the job, with its claim, and the record says so. A
    session whose claim or record could not be written is named for the caller to end; the next pass offers afresh."""
    stage = record.get("stage")
    came = _came(record, str(stage))[0] if stage else None  # a job sent back by a review is told why
    holder = reach.start(record, came)
    if holder is None:
        return Made(False, "no session was started")
    try:
        if refused := reach.claim(holder, lane_of(record)):
            return Made(False, f"the claim was refused: {refused}", end=holder)
        store.put_job(stage_job.offered(record, holder, act), f"offered to {holder}")
    except Exception as e:  # noqa: BLE001 — whatever failed, a started session must not be left unnamed
        return Made(False, f"the offer did not finish: {e}", end=holder)
    return Made(True)


def _to_person(store: StageStore, record: dict[str, Any], reason: str, reach: JobReach) -> Made:
    """The job waits on the person: the home's plain line written first, its id kept on the record."""
    line = reach.line(record, reason)
    if not line:
        return Made(False, "the home's board line could not be written")
    store.put_job(stage_job.to_person(record, line), f"to the person: {reason}")
    return Made(True)


def _gone(store: StageStore, record: dict[str, Any], reach: JobReach) -> Made:
    """The object is gone: the home's own line closed where the job waited on the person, then the record."""
    line = record.get("person_line")
    if record.get("waits") == "person" and line:
        reach.close_line(str(line))
    store.put_job(stage_job.closed(record), "closed: its object is gone")
    return Made(True)


def make(
    store: StageStore,
    key: str,
    act: JobAct,
    s: JobReading,
    reach: JobReach,
    *,
    seat: str,
    obj: str | int,
    team: str,
    opened_at: str,
) -> Made:
    """Write `act` on the job `key`, if a fresh read under the lock still chooses it. `seat`, `obj`, `team` and
    `opened_at` make the record of an object with none, or one whose record closed (a new job, written over it)."""
    with store.locked():
        found = store.job(key)
        if stage_job.choose(found, s) != act:
            return Made(False, "the record moved since it was read")
        if found is None or found.get("closed_at"):
            record = stage_job.new_job(seat, obj, team, opened_at)
            if record["id"] != key:
                return Made(False, f"{seat} {obj} is not the job {key}")
        else:
            record = dict(found)
        held = record.get("holder")
        if act.name == "offer":
            got = _offer(store, record, act, reach)
        elif act.name == "offer-again" and act.case == "to-person":
            got = _to_person(store, record, LOST_TWICE, reach)
        elif act.name == "offer-again":
            got = _offer(store, {**record, "holder": None}, act, reach)
        elif act.case == "object-gone":
            got = _gone(store, record, reach)
        elif act.case == "pr-closed":
            got = _to_person(store, record, PR_CLOSED, reach)
        elif act.case == "person-cleared":
            store.put_job(stage_job.cleared(record), "the person closed the home's line: offered afresh")
            got = Made(True)
        elif act.case == "stage-gone":
            moved = {**stage_job.moved(record, str(record["team"])), "holder": None}  # its holder ended first
            store.put_job(moved, "its stage left the flow: offered afresh")
            got = Made(True)
        elif act.case == "team-moved" and s.first_started:
            store.put_job(stage_job.moved(record, s.first_started), f"given to team {s.first_started}")
            got = Made(True)
        else:
            return Made(False, f"{act.name} {act.case} is no job's act")
        if got.made and held and got.end is None:
            return Made(True, got.why, end=str(held))  # the session the act took the record from
        return got
