"""One entry's turn in the tick's pass over the stage records (design §4.9c *The home acts only where no session will*,
TD-2051).

`step` reads the entry, chooses its one act and makes it, by the module that makes that act, then ends the session the
act took the record from. What it is given to reach the world (`gate`, `land`, `start`, `claim`, `end`) is the tick's
wiring, so one entry's failure is that entry's: it is returned as a `Step` and the pass goes on to the next.
Nothing calls this yet.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from shiftlead import org as orgmod
from shiftlead import stage_make, stage_merge, stage_start
from shiftlead.stage_acts import Act, Reading, choose
from shiftlead.stage_make import Made
from shiftlead.stage_read import EntryFacts, reading_on
from shiftlead.stage_start import Work
from shiftlead.stagerecord import StageStore

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
