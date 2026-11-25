"""The two built-in seats' passes over their jobs as the tick takes them (design §4.9d *How each one runs*, TD-2053).

`run` is called by `stage_tick.run` after the repo's teams' pass, with the parts of the home's repo reading the jobs
read: its work orders (the board's open decided lines), its pull request orders, its boards and its pull request rows.
It makes each seat's trigger (`stage_job.board_objects`, `pr_objects`), one `JobFacts`, and takes
`stage_job_pass.seat_pass` for each seat. `reach_for` is how a job's act reaches the world: its session launched by
`stage_job_start.launch` on the seat's model (`builtinstore`, the set the repo uses) and created through the host
agent, its claim on the job's work order, and the home's plain board line (`board.add`) and its close.

Nothing starts a session yet: `stage_start.team_started` is false until TD-2065, so no team is started and no job is
offered; and the home hands this its reading only once its own half is wired.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sessionorc import board, builtinstore, workorders
from sessionorc import settings as settings_mod
from shiftlead import org as orgmod
from shiftlead import stage_job, stage_job_pass, stage_job_start, stage_pass, stage_start
from shiftlead.stage_fetch import SessionsRead, held_read
from shiftlead.stage_job_make import JobReach
from shiftlead.stage_job_pass import JobFacts, JobStep
from shiftlead.stage_read import pickable_on
from shiftlead.stagerecord import StageStore, StateError

log = logging.getLogger(__name__)


def lines_open(boards: Mapping[str, Any] | None) -> frozenset[str] | None:
    """The eight hex digits of each open item on the repo's board (`workorders.read_boards`), the form a job keeps its
    `person_line` in. None: the board could not be read."""
    if not isinstance(boards, Mapping) or "error" in boards:
        return None
    out = set()
    for b in boards.get("boards") or []:
        for item in (b.get("items") or []) if isinstance(b, Mapping) else []:
            key = str(item.get("key") or "") if isinstance(item, Mapping) else ""
            if key.startswith(workorders.PREFIX):
                out.add(key[len(workorders.PREFIX) :])
    return frozenset(out)


def line_text(record: Mapping[str, Any], reason: str) -> str:
    """The home's plain board line for a job sent to the person: the seat, the line or pull request, and the reason."""
    seat = stage_job_start.SEAT_WORDS.get(str(record.get("seat")), str(record.get("seat")))
    lane = stage_job_start.lane_of(record)
    return f"The built-in seat for {seat} stopped on {lane}: {reason}. Close this line to have it offered again."


def reach_for(
    call: Callable[..., Any],
    org: Callable[[], orgmod.Org | None],
    root: Path,
    repo: str,
    *,
    local: str,
    hosts: Mapping[str, str],
    docs: Mapping[str, Mapping[str, Any]],
    settings: Callable[[], Mapping[str, Any] | None] = settings_mod.read,
    today: Callable[[], str] = lambda: date.today().isoformat(),
) -> JobReach:
    """A `JobReach` through the host agent's `call`. A job's session launches on the host of its record's team
    (`hosts`, each team's `host`, the home where none), from that team's flow (`docs`), on the seat's model from the
    built-in set the repo uses. A team the org does not define starts nothing."""

    def start(record: Mapping[str, Any], came: str | None) -> str | None:
        read = org()
        team = str(record.get("team") or "")
        teamdef = read.teams.get(team) if read is not None else None
        doc = docs.get(team)
        if read is None or teamdef is None or doc is None:
            return None
        sdoc = settings() or {}
        entry = builtinstore.sets(sdoc)[builtinstore.repo_set(sdoc, repo)]
        model = builtinstore.model(entry, str(record["seat"]))
        host = hosts.get(team) or local
        got = stage_job_start.launch(read, teamdef, dict(doc), record, model, host=host, here=local, came=came)
        made = stage_start.start(call, read, teamdef, got)
        return stage_start.holder_of(got, made) if made else None

    def line(record: Mapping[str, Any], reason: str) -> str | None:
        got = board.add(root, line_text(record, reason), today())
        key = str(got.get("key") or "")
        return key[len(workorders.PREFIX) :] if key.startswith(workorders.PREFIX) else None

    def close_line(line_id: str) -> None:
        board.write_back(root, None, "", "done", key=f"{workorders.PREFIX}{line_id}", why="its job's object is gone")

    return JobReach(
        start=start,
        claim=lambda holder, ref: stage_start.claim(call, holder, ref),
        line=line,
        close_line=close_line,
        end=lambda holder: stage_start.end(call, holder, "its job record no longer names it"),
    )


def run(
    store: StageStore,
    reach: JobReach,
    *,
    now: datetime,
    orders: Iterable[Mapping[str, Any]],
    pr_orders: Iterable[Mapping[str, Any]],
    boards: Mapping[str, Any] | None,
    rows: Iterable[Mapping[str, Any]],
    entries: Iterable[Mapping[str, Any]],
    sessions: SessionsRead,
    checkouts: Mapping[str, Collection[str]],
    local: str,
    started: Collection[str],
    docs: Mapping[str, Mapping[str, Any]],
    may_start: bool,
) -> dict[str, tuple[JobStep, ...] | None]:
    """Both seats' passes. `entries` are the ledger's rows, for which pull requests are a pickable entry's work;
    `started` the repo's started teams and `docs` their flows. A seat whose records could not be read is None; with
    the stage records unread, neither seat's trigger can be told, so neither runs."""
    rows = tuple(rows)
    orders, pr_orders = list(orders), list(pr_orders)
    try:
        records = {k: r for k, r in store.entries().items() if isinstance(r, Mapping)}
        jobs = {k: r for k, r in store.jobs().items() if isinstance(r, Mapping)}
    except (StateError, ValueError):
        log.exception("the stage records could not be read for the jobs' triggers")
        return dict.fromkeys(stage_job.SEATS)
    held = held_read(rows, sessions, checkouts, local=local)
    first = min(started) if started else None
    pickable = [str(e.get("id")) for e in entries if first and pickable_on(dict(e), first)]
    work = stage_job.entries_work(pickable, records, rows, held=held or ())
    objects = {
        "board-answers": stage_job.board_objects(orders, records),
        "unheld-pull-requests": stage_job.pr_objects(pr_orders, records, jobs, work=work),
    }
    if held is None:
        objects["unheld-pull-requests"] = {}  # a node not read may hold any pull request: none is nobody's this pass
    seen = stage_pass.addressed(sessions, local)  # a holder may be written in the home's `id@<local>` form
    f = JobFacts(
        now=now,
        live=stage_job_pass.live_keys(orders, rows),
        rows=rows,
        lines_open=lines_open(boards),
        sessions=seen.sessions,
        read_nodes=seen.read_nodes,
        open_asks=seen.open_asks,
        started=tuple(started),
        docs=docs,
        may_start=may_start,
    )
    out: dict[str, tuple[JobStep, ...] | None] = {}
    for seat in stage_job.SEATS:
        try:
            out[seat] = stage_job_pass.seat_pass(store, seat, objects[seat], f, reach)
        except Exception:  # noqa: BLE001 — one seat's failure is that seat's
            log.exception("the job pass of seat %s failed", seat)
            out[seat] = None
    return out
