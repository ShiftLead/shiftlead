"""Which one act the tick takes on a built-in seat's job (design §4.9d *How each one runs*, TD-2053).

Board answers and pull requests nobody holds are jobs: a decided board line, or a pull request, is the job's
**object**, and its record on the state branch (`StageStore.job`, `jobs/<key>.json`, keyed `board-<item id>` or
`pr-<number>`) names the seat, the team whose host and flow it runs under, its holder and its offers, and what it waits
on. This module is pure, as `stage_acts` is: `choose` names the first act whose condition holds, and `order` says which
of a seat's jobs is offered next, since **each seat runs one job session at a time in a repo**; `board_objects` and
`pr_objects` are the two seats' triggers, the objects `order` is given.

A job's record enters its team's flow at `work-pushed`, as a record of the stage that takes `other` entries would; from
then on, while it stands at one of its flow's review stages, that stage reads its pull request with a fresh session of
its own (§4.9d *Its pull request is reviewed and merged by the team's flow*): `choose` offers it (case `review`), and
offers it again once where its holder was lost or went silent (cases `review-lost`, `review-silent`, `review-stopped`),
the second loss going to the person as a job session's does. A review stage's session is no job session of the seat,
so the seat's one job session at a time never holds it back. `JobReading.at_job_stage` says which stage the record is
at; a record at a stage that is neither the job's nor a review stage reads as its stage gone.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sessionorc import workorders
from shiftlead import stage_work
from shiftlead.stage_acts import SECOND_LOSS, Holder
from shiftlead.stagerecord import JOB_KEY

SEATS = ("board-answers", "unheld-pull-requests")

JobActName = Literal["reconcile", "offer", "offer-again"]


def key_of(seat: str, obj: str | int) -> str:
    """A job's key: `board-<item id>` for a decided board line, `pr-<number>` for a pull request nobody holds."""
    if seat == "board-answers":
        key = f"board-{obj}"
    elif seat == "unheld-pull-requests":
        key = f"pr-{int(obj)}"
    else:
        raise ValueError(f"a job's seat is one of {SEATS}, not {seat!r}")
    if not JOB_KEY.fullmatch(key):
        raise ValueError(
            f"{obj!r} is no {seat} object: a board item's id is eight hex digits, a pull request's a number"
        )
    return key


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
    at_job_stage: bool = True  # the record is at the job's own stage, or has not yet entered the flow; else a review's
    stage_known: bool = True  # the record's stage is in its team's flow, the job's own or a review stage
    holder: Holder | None = None
    job_stage: str | None = None  # the key of the job's own stage in the record's flow, where it was read
    may_start: bool = False  # the team is started, inside its schedule and not held by the usage gate
    seat_busy: bool = False


@dataclass(frozen=True)
class JobAct:
    name: JobActName
    case: str = ""
    counted: bool = True  # offer-again: whether this loss spends an offer

    @property
    def review(self) -> bool:
        """Whether the act starts a review stage's session on the job, which is no job session of the seat."""
        return self.name in ("offer", "offer-again") and self.case.startswith("review")


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
    if not s.stage_known:
        return "stage-gone"  # as team-moved, its holder ended first: a fresh job session, never the person
    if not record.get("holder") and not s.team_started and s.first_started and s.first_started != record.get("team"):
        return "team-moved"
    return None


def _offer_again(record: Mapping[str, Any], holder: Holder, s: JobReading) -> JobAct | None:
    if not s.may_start:
        return None
    review = not s.at_job_stage  # a review stage's session: the seat's one job session never holds it back
    pre = "review-" if review else ""
    busy = s.seat_busy and not review
    if holder.ended_by_stop:
        return JobAct("offer-again", f"{pre}stopped", counted=False) if not busy else None
    if int(record.get("offers") or 0) >= SECOND_LOSS:
        return JobAct("offer-again", "to-person")
    if busy:
        return None  # another job session of the seat is live: this one waits, its lost holder named until then
    return JobAct("offer-again", f"{pre}lost" if holder.lost else f"{pre}silent")


def choose(record: Mapping[str, Any] | None, s: JobReading) -> JobAct | None:
    """The one act this pass takes on a job (`record` None: an object with no record yet), or None."""
    if record is None or record.get("closed_at"):
        if s.live and s.may_start and not s.seat_busy:
            return JobAct("offer", "new")  # an object back after its record closed is a new job
        return None
    if case := _reconcile(record, s):
        return JobAct("reconcile", case)
    if record.get("waits"):
        return None  # on the person, or on the home's merge
    if record.get("holder"):
        h = s.holder
        if h is not None and (h.lost or h.silent or h.ended_by_stop):
            return _offer_again(record, h, s)
        return None
    if not s.at_job_stage:  # at a review stage, a cleared wait among them: that stage's fresh session reads it
        return JobAct("offer", "review") if s.may_start else None
    return JobAct("offer") if s.may_start and not s.seat_busy else None


def order(records: Iterable[Mapping[str, Any]], objects: Mapping[str, str], job_stage: str | None) -> list[str]:
    """The keys of one seat's jobs that want a job session, in the order they are offered: records already begun
    (open, no holder, waiting on nothing, and at the job's own stage `job_stage` or not yet in the flow) before objects
    with no open record, each oldest first. `objects` maps the key of each object the seat's trigger names to when it
    asked (an ISO time); one with an open record is that record's, never a new job."""
    records = list(records)
    open_keys = {str(r["id"]) for r in records if not r.get("closed_at")}
    begun = [
        r
        for r in records
        if not r.get("closed_at") and not r.get("holder") and not r.get("waits") and r.get("stage") in (None, job_stage)
    ]
    first = sorted(begun, key=lambda r: (str(r.get("entered_at") or ""), str(r["id"])))
    rest = sorted(((at, k) for k, at in objects.items() if k not in open_keys), key=lambda p: (str(p[0]), p[1]))
    return [str(r["id"]) for r in first] + [k for _at, k in rest]


def _open(record: object) -> bool:
    return isinstance(record, Mapping) and not record.get("closed_at")


def board_objects(orders: Iterable[Mapping[str, Any]], entries: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """The board-answers seat's trigger (design §4.9c *Two of the five are not seats today*): of a repo reading's work
    orders (`teamrun.work_orders`, each a decided board line), the key of each that asks for a job, mapped to the day
    it was decided. A line that is the covering item of an entry — its Context names that one entry and its
    `decision (…)` gate — whose open stage record (`entries`, by id) waits on the person, or is about to (its question
    recorded and not yet landed), is the home's to apply and asks for no job."""
    out: dict[str, str] = {}
    for o in orders:
        oid = str(o.get("id") or "")
        if not oid.startswith(workorders.PREFIX):
            continue
        key = f"board-{oid[len(workorders.PREFIX) :]}"
        if not JOB_KEY.fullmatch(key):
            continue
        tid = workorders.design_of(dict(o))
        r = entries.get(tid) if tid else None
        if r is not None and _open(r) and (r.get("waits") == "person" or r.get("intent")):
            continue
        out[key] = str((o.get("decided") or {}).get("date") or "")
    return out


def entries_work(
    pickable: Iterable[str],
    entries: Mapping[str, Mapping[str, Any]],
    prs: Iterable[Mapping[str, Any]],
    *,
    held: Collection[int] = (),
) -> frozenset[int]:
    """The numbers of the open pull requests that are the work of a pickable entry with no open stage record, which
    the Offer act takes and the seat for pull requests nobody holds skips (design §4.9c *Ways in*, §4.9e *Work in
    flight*): `stage_work.entry_work`'s match, the one the Offer act reads. One whose files are not read at its head
    yet may be an entry's, so it is skipped on this reading too."""
    rows = list(prs)
    out: set[int] = set()
    for tid in pickable:
        if _open(entries.get(tid)):
            continue
        got = stage_work.entry_work(tid, rows, held=held)
        if got.pr is not None and isinstance(got.pr.get("number"), int):
            out.add(got.pr["number"])
    return frozenset(out)


def pr_objects(
    orders: Iterable[Mapping[str, Any]],
    entries: Mapping[str, Mapping[str, Any]],
    jobs: Mapping[str, Mapping[str, Any]],
    *,
    work: Collection[int] = (),
) -> dict[str, str]:
    """The trigger of the seat for pull requests nobody holds (design §4.9c *Two of the five are not seats today*): of
    a repo reading's pull request orders (`teamrun.pr_orders`, each unheld, past its bound and never a fork's or a
    draft's), the key of each red or filing pull request that asks for a job, mapped to when it went red or opened. A
    pull request an open stage record names (`entries`), or a board answer's open job (`jobs`), is that record's;
    one in `work` is a pickable entry's (`entries_work`). A sync's and the gate sweep's are no red or filing pull
    request of the seat's."""
    named = {str(r.get("pr")) for r in entries.values() if _open(r) and r.get("pr") is not None}
    named |= {str(r.get("pr")) for r in jobs.values() if _open(r) and r.get("seat") == "board-answers" and r.get("pr")}
    out: dict[str, str] = {}
    for o in orders:
        num = o.get("pr")
        if not o.get("pr_order") or not isinstance(num, int) or isinstance(num, bool):
            continue
        if o.get("sync") or o.get("lift") or o.get("sweep"):
            continue
        if str(num) in named or num in work:
            continue
        key = f"pr-{num}"
        if not JOB_KEY.fullmatch(key):
            continue  # no pull request's number: never a job, and never a raise that stops the pass
        since = o.get("filing_since") if o.get("filing") else o.get("red_since")
        out[key] = str(since or "")
    return out


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
