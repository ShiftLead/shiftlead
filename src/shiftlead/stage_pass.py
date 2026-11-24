"""One entry's turn in the tick's pass over the stage records (design §4.9c *The home acts only where no session will*,
TD-2051).

`step` reads the entry, chooses its one act and makes it, by the module that makes that act, then ends the session the
act took the record from. What it is given to reach the world (`gate`, `land`, `start`, `claim`, `end`) is the tick's
wiring, so one entry's failure is that entry's: it is returned as a `Step` and the pass goes on to the next.
`team_pass` is one team's whole pass: it ends the sessions a crash stranded, stores the team's flow copy once the
records are read, and takes a step on each open record and each entry the team's lane may take. Nothing calls this yet.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sessionorc import ledgerboard
from shiftlead import org as orgmod
from shiftlead import stage_make, stage_merge, stage_start
from shiftlead.stage_acts import Act, Reading, choose
from shiftlead.stage_fetch import TD_ID, RepoFacts, SessionsRead, facts_on, stranded
from shiftlead.stage_make import Made
from shiftlead.stage_read import EntryFacts, pickable_on, reading_on
from shiftlead.stage_start import Work
from shiftlead.stagerecord import StageStore, StateError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reach:
    """How an act reaches the world: the merge gate and the merge, a session's start and claim, and a session's end."""

    gate: stage_merge.Gate
    land: stage_merge.Land
    start: Callable[[str, Work], str | None]
    claim: Callable[[str, str], str | None]
    end: Callable[[str], None]


def reach_for(
    call: Callable[..., Any],
    org: orgmod.Org,
    team: orgmod.TeamDef,
    doc: dict[str, Any],
    gate: stage_merge.Gate,
    land: stage_merge.Land,
    **where: Any,
) -> Reach:
    """A `Reach` through the host agent's `call`. `where` is `stage_start.launch`'s placing of the session (`host`,
    `here`, `place`, `flow_dir`, `files`). The team's started mark is read at each start."""

    def start(key: str, work: Work) -> str | None:
        got = stage_start.launch(org, team, doc, key, work, **where)
        made = stage_start.start(call, org, team, got)
        return stage_start.holder_of(got, made) if made else None

    return Reach(
        gate=gate,
        land=land,
        start=start,
        claim=lambda holder, tid: stage_start.claim(call, holder, tid),
        end=lambda holder: stage_start.end(call, holder),
    )


@dataclass(frozen=True)
class Step:
    """What one entry's turn did. `read` False: no reading of it this pass. `act` None: nothing to do. `unended`: a
    session the act took the record from and that could not be ended, which no record names any more."""

    tid: str
    read: bool = True
    act: Act | None = None
    made: Made | None = None
    unended: str | None = None


def _make(store: StageStore, act: Act, s: Reading, f: EntryFacts, reach: Reach) -> Made:
    doc = dict(f.doc)
    if act == stage_merge.MERGING:
        return stage_merge.run(store, f.tid, act, s, doc, f.person, reach.gate, reach.land, f.now)
    if act.name == "offer":
        return stage_make.offer(store, f.tid, act, s, doc, reach.start, reach.claim, team=f.team)
    return stage_make.make(store, f.tid, act, s, doc, f.person)


def step(store: StageStore, record: Mapping[str, Any] | None, f: EntryFacts, reach: Reach) -> Step:
    """Take `f.tid`'s one act this pass, if it has one."""
    s = reading_on(record, f)
    if s is None:
        return Step(f.tid, read=False)
    act = choose(record, s)
    if act is None:
        return Step(f.tid)
    try:
        made = _make(store, act, s, f, reach)
    except Exception as e:  # noqa: BLE001 — one entry's failure must not stop the pass over the others
        log.exception("the stage act %s %s on %s failed", act.name, act.case, f.tid)
        return Step(f.tid, act=act, made=Made(False, f"the act failed: {e}"))
    if not made.end:
        return Step(f.tid, act=act, made=made)
    try:
        reach.end(made.end)
    except Exception:  # noqa: BLE001 — the act is written; the session left running is reported, never raised
        log.exception("ending %s after the stage act on %s failed", made.end, f.tid)
        return Step(f.tid, act=act, made=made, unended=made.end)
    return Step(f.tid, act=act, made=made)


@dataclass(frozen=True)
class TeamPass:
    """What one team's pass did. `seen` is the next pass's `before`; `unended` the stranded sessions that could not be
    ended, which stay in `seen` so the next pass tries again. `flow_unstored`: the team's flow copy could not be stored,
    so no entry was stepped, since a session's `ao stage end` reads that copy."""

    steps: tuple[Step, ...] = ()
    seen: tuple[str, ...] = ()
    unended: tuple[str, ...] = ()
    flow_unstored: bool = False


def targets(records: Mapping[str, Mapping[str, Any]], entries: Iterable[Mapping[str, Any]], team: str) -> list[str]:
    """The entries `team`'s pass turns to: its open records, then each entry its lane may take that no open record
    names. A closed record does not hold its entry back, since a reopened entry is offered afresh, under the record's
    own key where the id is padded differently."""
    keys = {ledgerboard._num(k): k for k in records if TD_ID.fullmatch(k)}
    out = [k for k, r in records.items() if TD_ID.fullmatch(k) and r.get("team") == team and not r.get("closed_at")]
    for e in entries:
        tid = str(e.get("id"))
        if not TD_ID.fullmatch(tid) or not pickable_on(dict(e), team):
            continue
        key = keys.get(ledgerboard._num(tid))
        if key is None or records[key].get("closed_at"):
            out.append(key or tid)
    return out


def team_pass(
    store: StageStore,
    repo: RepoFacts,
    read: SessionsRead,
    reach: Reach,
    *,
    local: str,
    before: Collection[str] = (),
    put: str | None = None,
) -> TeamPass:
    """One pass over `repo.team`'s entries. `read` was taken before this call, so a session an offer starts after it
    cannot read as stranded; the records are read under the store's lock. `put` is the flow text to store as the team's
    copy, written only now that the records written under the old copy have been read. An entry a stranded session
    names with no open record is left for a later pass, since that session still holds the stage's name; an open
    record's acts go on beside it."""
    try:
        with store.locked():
            records = {k: r for k, r in store.entries().items() if isinstance(r, dict)}
            found = stranded(read, records, repo.team, repo.doc, local=local, before=before)
    except (StateError, ValueError):
        log.exception("the stage records of team %s could not be read", repo.team)
        return TeamPass(seen=tuple(before))
    unended = []
    for address in found.end:
        try:
            reach.end(address)
        except Exception:  # noqa: BLE001 — a session left running is reported and tried again next pass
            log.exception("ending the stranded session %s failed", address)
            unended.append(address)
    if put is not None:
        try:
            store.put_flow(repo.team, put)
        except (StateError, ValueError):
            log.exception("the flow copy of team %s could not be stored", repo.team)
            return TeamPass(seen=found.seen, unended=tuple(unended), flow_unstored=True)
    waiting = {ledgerboard._num(str(read.sessions[a].lane[0])) for a in found.seen}
    steps = []
    for tid in targets(records, repo.entries, repo.team):
        record = records.get(tid)
        if ledgerboard._num(tid) in waiting and (record is None or record.get("closed_at")):
            continue
        try:
            f = facts_on(repo, tid, record)
            steps.append(step(store, record, f, reach) if f is not None else Step(tid, read=False))
        except Exception:  # noqa: BLE001 — a failed read is no reading of this entry and never stops the pass
            log.exception("reading the stage entry %s failed", tid)
            steps.append(Step(tid, read=False))
    return TeamPass(tuple(steps), found.seen, tuple(unended))
