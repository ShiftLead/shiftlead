"""One entry's turn in the tick's pass over the stage records (design §4.9c *The home acts only where no session will*,
TD-2051).

`step` reads the entry, chooses its one act and makes it, by the module that makes that act, then ends the session the
act took the record from. What it is given to reach the world (`gate`, `land`, `start`, `claim`, `end`) is the tick's
wiring, so one entry's failure is that entry's: it is returned as a `Step` and the pass goes on to the next.
`team_pass` is one team's whole pass: it ends the sessions a crash stranded, stores the team's flow copy once the
records are read, and takes a step on each open record and each entry the team's lane may take. `repo_facts` makes a
team's `RepoFacts` from the pass's reads, and `repo_pass` is one repo's pass over its teams, keeping between passes what
the next one needs. Nothing calls this yet.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc import ledgerboard
from shiftlead import org as orgmod
from shiftlead import stage_make, stage_merge, stage_size, stage_start
from shiftlead.stage_acts import Act, Reading, choose
from shiftlead.stage_fetch import (
    TD_ID,
    LedgerRead,
    RepoFacts,
    SessionsRead,
    TeamFlow,
    facts_on,
    held_read,
    over_line,
    rows_of,
    stranded,
    team_flow,
    teams_on,
)
from shiftlead.stage_make import Made
from shiftlead.stage_read import EntryFacts, pickable_on, reading_on
from shiftlead.stage_start import Work
from shiftlead.stagerecord import StageStore, StateError, flow_version, session_fields

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reach:
    """How an act reaches the world: the merge gate and the merge, a session's start and claim, and a session's end."""

    gate: stage_merge.Gate
    land: stage_merge.Land
    start: Callable[[str, Work], str | None]
    claim: Callable[[str, str], str | None]
    end: Callable[[str], None]
    spent: Callable[[str], Any] | None = None  # a session id's `models` sums, for the offer's `spent_before` (§4.9c)
    briefs: Callable[[Mapping[str, Any]], list[dict[str, str]]] | None = None  # each stage's resolved brief, to hash


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
        spent=lambda sid: call("seats", record=sid)["models"],
        briefs=lambda flow: stage_start.briefs(org, team, flow, **where),
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
        version = _version(f, doc, reach)
        return stage_make.offer(
            store, f.tid, act, s, doc, reach.start, reach.claim, team=f.team, spent=reach.spent, version=version
        )
    session = session_fields(f.session) if f.session is not None else None
    return stage_make.make(store, f.tid, act, s, doc, f.person, session=session, spent=reach.spent)


def _version(f: EntryFacts, doc: Mapping[str, Any], reach: Reach) -> tuple[str, str] | None:
    """The flow's canonical text and hash for an offer (§4.9c *The flow's content hash*): the text the team's turn chose
    and each stage's brief as a start reads it now. None, the offer made as without it, where the reach reads no
    briefs, the pass has no text, or a brief cannot be read (logged)."""
    if reach.briefs is None or f.flow_text is None:
        return None
    try:
        return flow_version(f.flow_text, reach.briefs(doc))
    except Exception:  # noqa: BLE001 — the checkout's, a brief's, a decode's or an encode's error: offered unhashed
        log.warning("%s: the flow's briefs could not be read for its hash; flow_hash is null", f.tid, exc_info=True)
        return None


def offer_stage(record: Mapping[str, Any] | None, s: Reading, doc: Mapping[str, Any]) -> str | None:
    """The stage an offer of the entry would start a session in: an open record's own, else the way in for its kind."""
    if record is not None and not record.get("closed_at"):
        return str(record["stage"]) if record.get("stage") else None
    return stage_make._way_in(dict(doc), s.design)


def step(
    store: StageStore,
    record: Mapping[str, Any] | None,
    f: EntryFacts,
    reach: Reach,
    room: stage_size.Room | None = None,
) -> Step:
    """Take `f.tid`'s one act this pass, if it has one. With `room`, whether an offer is within the team's size is read
    from it for the stage the offer would start in, and an offer made is taken from it (§4.9d *Sessions at once*)."""
    s = reading_on(record, f)
    if s is None:
        return Step(f.tid, read=False)
    at = None
    if room is not None:
        at = offer_stage(record, s, f.doc)
        s = replace(s, within_size=room.stage_fits(at))
    act = choose(record, s)
    if act is None:
        return Step(f.tid)
    try:
        made = _make(store, act, s, f, reach)
    except Exception as e:  # noqa: BLE001 — one entry's failure must not stop the pass over the others
        log.exception("the stage act %s %s on %s failed", act.name, act.case, f.tid)
        return Step(f.tid, act=act, made=Made(False, f"the act failed: {e}"))
    if room is not None and at is not None and act.name == "offer" and made.made:
        room.take_stage(at)
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
    so no entry was stepped, since a session's `ao stage end` reads that copy. `read` False: the records could not be
    read or the copy stored, so no entry had a reading this pass."""

    steps: tuple[Step, ...] = ()
    seen: tuple[str, ...] = ()
    unended: tuple[str, ...] = ()
    flow_unstored: bool = False
    read: bool = True


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
    record's acts go on beside it. With `repo.limits`, the team's room is counted from the records and its audits' runs
    as read here, and each offer the pass makes is taken from it."""
    try:
        with store.locked():
            records = {k: r for k, r in store.entries().items() if isinstance(r, dict)}
            found = stranded(read, records, repo.team, repo.doc, local=local, before=before)
    except (StateError, ValueError):
        log.exception("the stage records of team %s could not be read", repo.team)
        return TeamPass(seen=tuple(before), read=False)
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
            return TeamPass(seen=found.seen, unended=tuple(unended), flow_unstored=True, read=False)
    waiting = {ledgerboard._num(str(read.sessions[a].lane[0])) for a in found.seen}
    room = stage_size.room(store, repo.limits, records, repo.team, repo.doc) if repo.limits is not None else None
    steps = []
    for tid in targets(records, repo.entries, repo.team):
        record = records.get(tid)
        if ledgerboard._num(tid) in waiting and (record is None or record.get("closed_at")):
            continue
        try:
            f = facts_on(repo, tid, record)
            steps.append(step(store, record, f, reach, room) if f is not None else Step(tid, read=False))
        except Exception:  # noqa: BLE001 — a failed read is no reading of this entry and never stops the pass
            log.exception("reading the stage entry %s failed", tid)
            steps.append(Step(tid, read=False))
    return TeamPass(tuple(steps), found.seen, tuple(unended))


def addressed(read: SessionsRead, local: str) -> SessionsRead:
    """`read` as an entry's facts look a holder up. The home's graph keys a session here by its bare id, but a holder
    may be written `id@<local>`, the home's address form, which would read as a session on a node nobody read. So each
    session here is also found by that form, and `local` is among the nodes read. Only an entry's facts read this: the
    stranded test keeps one address per session, so it never ends one twice."""
    here = {a: s for a, s in read.sessions.items() if "@" not in a}
    return SessionsRead(
        {**read.sessions, **{f"{a}@{local}": s for a, s in here.items() if f"{a}@{local}" not in read.sessions}},
        read.read_nodes | {local},
        read.open_asks | {f"{a}@{local}" for a in read.open_asks if "@" not in a},
    )


def repo_facts(
    root: Path | str,
    ref: str,
    read: LedgerRead,
    *,
    person: str,
    team: str,
    now: datetime,
    flow: TeamFlow,
    entries: Iterable[dict[str, Any]],
    prs: Mapping[str, Any] | None,
    read_one: Callable[[int], Mapping[str, Any] | None],
    records: Mapping[str, Any],
    sessions: SessionsRead,
    checkouts: Mapping[str, Collection[str]],
    local: str,
    host_teams: Mapping[str, Any] | None,
    protected: Collection[str] | None,
    branches: Collection[str] = (),
    merging: Collection[str] = (),
    started: bool = False,
    within_size: bool = False,
    named: Callable[[str], Mapping[str, Any] | None] | None = None,
    limits: stage_size.Limits | None = None,
) -> RepoFacts | None:
    """`team`'s `RepoFacts` from what the pass read once. `prs` is the repo's pull request reading and `read_one` reads
    one by its number, asked for each open record's pull request the reading lacks; `records` are only for which those
    are. `sessions` must name as read only the nodes whose link has delivered its snapshot since it came up, and
    `checkouts` every node's checkouts of the repo, since a node left out is read as holding nothing. A team over its
    line on open pull requests is offered no new entry (`holds_new`); its entries already in a stage carry on. None:
    the pull requests could not be read, so no entry of the team can be told from one whose work is in flight.
    `limits` are the team's numbers, from which each offer's room is counted; without them `within_size` is taken as
    given."""
    wanted = sorted(
        {
            r["pr"]
            for r in records.values()
            if isinstance(r, Mapping) and isinstance(r.get("pr"), int) and not r.get("closed_at")
        }
    )
    rows = rows_of(prs, wanted, read_one)
    if rows is None:
        return None
    seen = addressed(sessions, local)
    return RepoFacts(
        root=root,
        ref=ref,
        read=read,
        person=person,
        team=team,
        now=now,
        doc=flow.doc,
        flow_text=flow.text,
        entries=tuple(entries),
        teams=teams_on(read),
        rows=rows,
        held=held_read(rows, sessions, checkouts, local=local),
        branches=branches,
        protected=protected,
        sessions=seen.sessions,
        read_nodes=seen.read_nodes,
        open_asks=seen.open_asks,
        merging=merging,
        was=flow.was,
        named=named,
        may_start=started,
        holds_new=over_line(host_teams, team),
        within_size=within_size,
        limits=limits,
    )


@dataclass
class RepoState:
    """What one repo's passes keep from one to the next: each team's stranded sightings, the next pass's `before`, and
    the flow problems the person was last told of, so a flow failing the same way is told once."""

    seen: dict[str, tuple[str, ...]] = field(default_factory=dict)
    told: dict[str, tuple[str, ...]] = field(default_factory=dict)
    spells: dict[tuple[str, str], Spell] = field(default_factory=dict)  # by (team, entry): an act refused alike


STANDING_PASSES = 3  # a refusal the same on this many passes running, over at least STANDING_SPAN, is standing
STANDING_SPAN = timedelta(minutes=10)


@dataclass
class Spell:
    """One entry's run of passes whose act was refused with the same reason: since when, how many, and whether the
    person has been told of it."""

    team: str
    act: str
    why: str
    since: datetime
    passes: int = 1
    told: bool = False


@dataclass(frozen=True)
class Refusal:
    """A refusal newly standing, for the person to be told once (§4.9c *A refusal that stands*)."""

    tid: str
    team: str
    act: str
    why: str
    since: datetime


def note_refusals(state: RepoState, team: str, steps: Iterable[Step], now: datetime) -> list[Refusal]:
    """Each refused act among `team`'s `steps` counted into its entry's spell, and the spells newly standing. A made
    act, no act, or a refusal for another act or reason ends the spell (the last starting one of its own); a step with
    no reading leaves it as it was; an entry the pass did not turn to has its spell dropped."""
    out: list[Refusal] = []
    stepped: set[str] = set()
    for s in steps:
        stepped.add(s.tid)
        if not s.read:
            continue
        refused = s.act is not None and s.made is not None and not s.made.made
        if not refused:
            state.spells.pop((team, s.tid), None)
            continue
        act = f"{s.act.name} ({s.act.case})" if s.act.case else str(s.act.name)  # type: ignore[union-attr]
        why = s.made.why or "no reason given"  # type: ignore[union-attr]
        spell = state.spells.get((team, s.tid))
        if spell is None or (spell.act, spell.why) != (act, why):
            state.spells[(team, s.tid)] = Spell(team, act, why, now)
            continue
        spell.passes += 1
        if not spell.told and spell.passes >= STANDING_PASSES and now - spell.since >= STANDING_SPAN:
            spell.told = True
            out.append(Refusal(s.tid, team, act, why, spell.since))
    for key in [k for k in state.spells if k[0] == team and k[1] not in stepped]:
        del state.spells[key]
    return out


@dataclass(frozen=True)
class RepoPass:
    """What one repo's pass did. `unread`: the teams with no reading this pass. `tell`: the teams whose flow has newly
    stopped passing its check, with its problems, for the person to be told once. `swept`: closed records moved to their
    closed copies. `refused`: the entries whose act's refusal has newly come to stand, for the person to be told once
    each. `jobs`: the built-in seats' steps, where the caller read them (`stage_tick.run`); `audits` its audits' steps,
    a rested one for the person to be told once (`AuditStep.tell`)."""

    teams: Mapping[str, TeamPass] = field(default_factory=dict)
    unread: tuple[str, ...] = ()
    tell: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    swept: tuple[str, ...] = ()
    refused: tuple[Refusal, ...] = ()
    jobs: Mapping[str, Any] = field(default_factory=dict)  # by seat: its job steps (`stage_job_tick.run`), or None
    audits: tuple[Any, ...] = ()  # each audit's step (`stage_audit_pass.audit_pass`), where the caller read them


FactsFor = Callable[[str, TeamFlow, Mapping[str, Any]], RepoFacts | None]


def repo_pass(
    store: StageStore,
    state: RepoState,
    flows: Mapping[str, tuple[str | None, Collection[str]]],
    facts: FactsFor,
    read: SessionsRead,
    reach: Callable[[str, Mapping[str, Any]], Reach],
    *,
    local: str,
    now: datetime | None = None,
) -> RepoPass:
    """One pass over a repo's teams. `flows` holds each team's flow as read now (None: unreadable) and its check's
    problems; `facts` makes a team's `RepoFacts` from the flow it runs and the records (`repo_facts`, its reads bound);
    `reach` gives a team its `Reach` from the flow it runs, the last good copy while its flow fails. A team's flow copy
    is read before its pass, so the flow its records were written under is known before the copy is replaced. The
    person is told of a failing flow once, until it passes again, and the closed records are swept once for the repo,
    after its teams."""
    for gone in set(state.seen) - set(flows):
        del state.seen[gone]
    for gone in set(state.told) - set(flows):
        del state.told[gone]
    for key in [k for k in state.spells if k[0] not in flows]:
        del state.spells[key]
    at = now or datetime.now(UTC)
    refused: list[Refusal] = []
    try:
        records = {k: r for k, r in store.entries().items() if isinstance(r, Mapping)}
    except Exception:  # noqa: BLE001 — no records read is only no pull requests read by number
        log.exception("the stage records could not be read for their pull requests")
        records = {}
    done: dict[str, TeamPass] = {}
    unread: list[str] = []
    tell: dict[str, tuple[str, ...]] = {}
    for team, (current, problems) in flows.items():
        try:
            got = _repo_team(store, state, team, current, problems, facts, records, read, reach, tell, local=local)
        except Exception:  # noqa: BLE001 — one team's failure is that team's and never stops the others' passes
            log.exception("the stage pass of team %s failed", team)
            got = None
        if got is None:
            unread.append(team)
        else:
            done[team] = got
            if got.read:  # a team pass with no reading neither counts nor ends a run
                refused += note_refusals(state, team, got.steps, at)
    try:
        swept = tuple(stage_make.sweep_closed(store, now))
    except Exception:  # noqa: BLE001 — a failed sweep is tried again next pass and never fails this one
        log.exception("the closed stage records could not be swept")
        swept = ()
    return RepoPass(done, tuple(unread), tell, swept, tuple(refused))


def _repo_team(
    store: StageStore,
    state: RepoState,
    team: str,
    current: str | None,
    problems: Collection[str],
    facts: FactsFor,
    records: Mapping[str, Any],
    read: SessionsRead,
    reach: Callable[[str, Mapping[str, Any]], Reach],
    tell: dict[str, tuple[str, ...]],
    *,
    local: str,
) -> TeamPass | None:
    """One team's turn in `repo_pass`: its flow chosen and told, then its pass. None: no reading of the team."""
    try:
        kept = store.flow(team)
    except (StateError, ValueError):
        log.exception("the flow copy of team %s could not be read", team)
        return None
    flow = team_flow(current, problems, kept)
    failing = flow.problems if flow is not None else tuple(problems) or ("the flow could not be read",)
    if failing:
        if state.told.get(team) != failing:
            tell[team] = state.told[team] = failing
    else:
        state.told.pop(team, None)
    repo = facts(team, flow, records) if flow is not None else None
    if flow is None or repo is None:
        return None
    got = team_pass(
        store, repo, read, reach(team, flow.doc), local=local, before=state.seen.get(team, ()), put=flow.put
    )
    state.seen[team] = got.seen
    return got
