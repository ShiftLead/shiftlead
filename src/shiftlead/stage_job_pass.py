"""One built-in seat's pass over its jobs (design §4.9d *How each one runs*, TD-2053).

`reading_on` makes a job's `JobReading` from what the pass read once (`JobFacts`): whether its object still asks, the
state of a board answer's own pull request, the home's line it waits on, its team, its holder, and whether the seat
already runs a job session. `seat_pass` takes one act on each of the seat's jobs, by `stage_job.choose`, and writes it
by `stage_job_make.make`: the records already open first, then the objects with none, in `stage_job.order`'s order.
**Each seat runs one job session at a time in a repo**, so once an offer this pass started one, no other job of the
seat is offered until the next. A job with no reading this pass (its pull request's row missing, its holder's node not
read, its team's flow not read) is left as it is. Nothing calls this yet; its wiring into the tick is a later slice.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sessionorc import workorders
from sessionorc.models import Session
from shiftlead import flow3, stage_job, stage_job_make
from shiftlead.stage_job import SEATS, JobAct, JobReading
from shiftlead.stage_job_make import JobReach
from shiftlead.stage_job_start import job_stage, lane_of
from shiftlead.stage_make import Made
from shiftlead.stage_read import holder_on
from shiftlead.stagerecord import StageStore, StateError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobFacts:
    """What the pass read for a repo's jobs.

    `live` holds the key of each object that still asks for its job: a decided board line still open and decided, a
    pull request still open (`live_keys`). `rows` are the repo's pull requests, for a board answer's own. `lines_open`
    the ids of the board's open items, for the home's line a job waits on (None: not read). `sessions` the sessions by
    address, of the nodes in `read_nodes`, and `open_asks` those with an open ask of their own. `started` the repo's
    started teams and `docs` each one's flow; `may_start` whether the first of them may start a session now."""

    now: datetime
    live: Collection[str]
    rows: tuple[Mapping[str, Any], ...] = ()
    lines_open: Collection[str] | None = None
    sessions: Mapping[str, Session] = field(default_factory=dict)
    read_nodes: Collection[str] = ()
    open_asks: Collection[str] = ()
    started: Collection[str] = ()
    docs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    may_start: bool = False

    @property
    def first_started(self) -> str | None:
        return min(self.started) if self.started else None


def live_keys(orders: Iterable[Mapping[str, Any]], rows: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """`JobFacts.live` from a repo reading's work orders (`teamrun.work_orders`, the board's open decided lines) and its
    pull request rows. A pull request is live while it is open, whoever holds it: its job's own session claims it."""
    out = set()
    for o in orders:
        oid = str(o.get("id") or "")
        if oid.startswith(workorders.PREFIX):
            out.add(f"board-{oid[len(workorders.PREFIX) :]}")
    for r in rows:
        num = r.get("number")
        if r.get("state") == "open" and isinstance(num, int) and not isinstance(num, bool):
            out.add(f"pr-{num}")
    return frozenset(out)


def _session(f: JobFacts, holder: str) -> tuple[bool, Session | None]:
    """Whether `holder`'s node was read, and its session (None: gone)."""
    _, at, node = holder.partition("@")
    if at and node not in f.read_nodes:
        return False, None
    return True, f.sessions.get(holder)


def _busy(record: Mapping[str, Any], f: JobFacts) -> bool:
    """Whether `record`'s holder is a job session still running, or one whose node was not read, which may be."""
    holder = str(record.get("holder") or "")
    if not holder or record.get("closed_at"):
        return False
    read, s = _session(f, holder)
    return not read or (s is not None and s.state not in ("exited", "closed"))


def _stage_known(record: Mapping[str, Any], doc: Mapping[str, Any]) -> bool:
    stage = record.get("stage")
    if stage is None:
        return True
    return any(isinstance(st, Mapping) and flow3.key_of(st.get("name")) == stage for st in doc.get("stages") or [])


def reading_on(record: Mapping[str, Any] | None, key: str, f: JobFacts, *, seat_busy: bool) -> JobReading | None:
    """The `JobReading` of the job `key` (`record` None: an object with no record yet). None: no reading this pass —
    its own pull request's row, the home's line it waits on, its holder's node or its team's flow was not read."""
    common = {"live": key in f.live, "first_started": f.first_started, "may_start": f.may_start, "seat_busy": seat_busy}
    if record is None or record.get("closed_at"):
        return JobReading(**common)
    team = str(record.get("team") or "")
    own_pr = None
    if record.get("seat") == "board-answers" and isinstance(record.get("pr"), int):
        row = next((r for r in f.rows if r.get("number") == record["pr"]), None)
        own_pr = row.get("state") if row else None
        if own_pr not in ("open", "merged", "closed"):
            return None
    person_line = None
    if record.get("waits") == "person" and record.get("person_line"):
        if f.lines_open is None:
            return None
        person_line = "open" if str(record["person_line"]) in f.lines_open else "closed"
    doc = f.docs.get(team)
    if doc is None and record.get("stage") is not None:
        return None
    holder = None
    if h := str(record.get("holder") or ""):
        read, s = _session(f, h)
        if not read:
            return None
        holder = holder_on(s, lane_of(record), f.now, open_ask=h in f.open_asks)
    return JobReading(
        own_pr=own_pr,
        person_line=person_line,
        team_started=team in f.started,
        at_job_stage=record.get("stage") in (None, job_stage(doc or {})),
        stage_known=_stage_known(record, doc or {}),
        holder=holder,
        **common,
    )


@dataclass(frozen=True)
class JobStep:
    """What one job's turn did, as `stage_pass.Step` says of an entry's."""

    key: str
    read: bool = True
    act: JobAct | None = None
    made: Made | None = None
    unended: str | None = None


def _object_of(key: str) -> str | int:
    kind, _, obj = key.partition("-")
    return int(obj) if kind == "pr" else obj


def step(
    store: StageStore,
    seat: str,
    key: str,
    record: Mapping[str, Any] | None,
    f: JobFacts,
    reach: JobReach,
    *,
    asked_at: str,
    seat_busy: bool,
) -> JobStep:
    """Take the job `key`'s one act this pass, if it has one."""
    s = reading_on(record, key, f, seat_busy=seat_busy)
    if s is None:
        return JobStep(key, read=False)
    act = stage_job.choose(record, s)
    if act is None:
        return JobStep(key)
    team = str(record["team"]) if record is not None and not record.get("closed_at") else f.first_started
    if team is None:
        return JobStep(key)  # a new job with no started team to run under: Offer's own condition, read again
    try:
        made = stage_job_make.make(
            store, key, act, s, reach, seat=seat, obj=_object_of(key), team=team, opened_at=asked_at
        )
    except Exception as e:  # noqa: BLE001 — one job's failure must not stop the pass over the others
        log.exception("the job act %s %s on %s failed", act.name, act.case, key)
        return JobStep(key, act=act, made=Made(False, f"the act failed: {e}"))
    if not made.end:
        return JobStep(key, act=act, made=made)
    try:
        reach.end(made.end)
    except Exception:  # noqa: BLE001 — the act is written; the session left running is reported, never raised
        log.exception("ending %s after the job act on %s failed", made.end, key)
        return JobStep(key, act=act, made=made, unended=made.end)
    return JobStep(key, act=act, made=made)


def _started_one(got: JobStep) -> bool:
    return got.act is not None and got.act.name in ("offer", "offer-again") and bool(got.made and got.made.made)


def seat_pass(
    store: StageStore, seat: str, objects: Mapping[str, str], f: JobFacts, reach: JobReach
) -> tuple[JobStep, ...] | None:
    """One pass over `seat`'s jobs. `objects` is the seat's trigger (`stage_job.board_objects` or `pr_objects`): each
    object's key and when it asked. Every open record of the seat takes its act, those waiting for a job session in
    `stage_job.order`'s order, then each object with no open record, oldest first; while a job session of the seat is
    live, or once this pass started one, no other is offered. None: the records could not be read."""
    if seat not in SEATS:
        raise ValueError(f"a job's seat is one of {SEATS}, not {seat!r}")
    try:
        records = {k: r for k, r in store.jobs().items() if isinstance(r, dict) and r.get("seat") == seat}
    except (StateError, ValueError):
        log.exception("the job records of seat %s could not be read", seat)
        return None
    opened = {k: r for k, r in records.items() if not r.get("closed_at")}
    first = f.first_started
    queued = stage_job.order(opened.values(), objects, job_stage(f.docs.get(first) or {}) if first else None)
    rest = sorted((k for k in opened if k not in queued), key=lambda k: (str(opened[k].get("entered_at") or ""), k))
    busy = any(_busy(r, f) for r in opened.values())
    steps = []
    for key in [*rest, *queued]:
        record = opened.get(key) or records.get(key)
        mine = record is not None and key in opened and _busy(record, f)
        got = step(store, seat, key, record, f, reach, asked_at=objects.get(key, ""), seat_busy=busy and not mine)
        busy = busy or _started_one(got)
        steps.append(got)
    return tuple(steps)
