"""What the home reads of an entry's own text for a stage record (design §4.9c act 2, TD-2051).

`answer_on` reads the entry's Log, in file order and never by date: whether it carries the person's `decision` gate,
the label of the person's answer that last lifted it, and the mark of the question that answer lifted. Only a lift by
an answer counts: an override lifts the gate and answers nothing. A gate standing now means no answer is waiting, since
any lift in the Log was of an earlier gate.

`holder_on` reads what became of a record's holder from its session's record (§4.9c act 4). A holder the person or the
home stopped or holds is neither lost nor silent: one still there is `held`, and one whose end a Stop or a person made
is `stopped`. A claim released by `done` or `drop` is not a lapsed lease, so a live session that released its claim is
judged by the silent rule.

`ledger_on` reads where the entry stands in the ledger and its archive, and whether it is a design with parts.
`renumbered_on` reads the id an entry that left both was renumbered to, from the commit that removed its file.

`forge_on` reads what became of the record's pull request from the repo's rows, and whether the home's own pull request
archiving the entry is open. A pull request the rows do not hold is no reading, never a pull request that is gone.

`flow_on` reads whether a record's stage and flow still match its team's copy of the flow, `team_moved_on` whether the
entry's `Team:` line now names another team, and `carried_on` whether the work a moved entry carried is still live.

`nothing_to_read_on` reads whether an `only-when` stage has nothing to read (act 3). Passing it lets a pull request by
a review, so only a whole reading of its files at its current head that touches no protected file says so.

`pickable_on` reads whether an entry with no record may be offered (§4.9c *Ways in*), and `held_on` which open pull
requests a live session holds, the `held` that `stage_work.entry_work` is given.

`reading_on` puts them together into the one `Reading` of an entry, from what the tick's wiring has fetched, or None
where any part is no reading of it this pass. None of these writes anything.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal, NamedTuple

from sessionorc import board, held, ledger, ledgerboard, work, workorders
from sessionorc.agent_common import OPEN_TOOL_CEILING, _parse, shells_live, subagents_live
from sessionorc.mail import LEASE_TTL
from sessionorc.models import Session
from shiftlead.flow3 import key_of
from shiftlead.stage_acts import Holder, Reading
from shiftlead.stage_work import EntryWork, entry_work

_ASKED = re.compile(r"asked by the stage record: (\S+)")
_ENTRY_FILE = re.compile(r"(TD-\d+)\.md")


class EntryAnswer(NamedTuple):
    gate: bool
    lifted: str | None
    lifted_for: str | None


def answer_on(text: str, person: str) -> EntryAnswer:
    """`Reading.gate`, `.lifted` and `.lifted_for` from the entry's `text`, for the gate `decision (<person>)`.
    Raises `ledgerboard.Refused` on a text that is not one readable entry: the caller has no reading of that entry this
    pass and acts on nothing, because reading it as *no gate, no answer* would ask the person a question again."""
    gate = f"decision ({person})"
    if ledgerboard._carried(text, gate) is not None:
        return EntryAnswer(True, None, None)
    key = ledgerboard._gate_key(gate)
    asked = lifted = lifted_for = None
    for line in ledgerboard.log_lines(text):
        if line.get("kind") == "gate-lifted" and ledgerboard._gate_key(str(line.get("gate"))) == key:
            lifted, lifted_for = (line["label"], asked) if line.get("label") is not None else (None, None)
        elif line.get("kind") == "note" and (mark := _ASKED.fullmatch(str(line.get("text")))):
            asked, lifted, lifted_for = mark.group(1), None, None
    return EntryAnswer(False, lifted, lifted_for)


class EntryLedger(NamedTuple):
    entry: Literal["open", "archived"]
    design: bool = False
    open_parts: int = 0
    had_parts: bool = False
    live_check: bool = False


def _parent(e: dict) -> int | None:
    par = ledgerboard.parse_part_of(e.get("part_of_raw"))[0]
    return ledgerboard._num(par) if par else None


def ledger_on(tid: str, text: str, archive: str | None) -> EntryLedger | None:
    """`Reading.entry`, `.design`, `.open_parts` and `.had_parts` of `tid`, from the ledger's and the archive's text,
    an id matched by its number. None: the entry is in neither, so the caller looks for a renumbering, and with none
    has no reading of it this pass."""
    n = ledgerboard._num(tid)
    live, gone = ledgerboard.entries(text), ledgerboard.entries(archive or "")
    own = next((e for e in live if ledgerboard._num(e["id"]) == n), None)
    if own is None:
        return EntryLedger("archived") if any(ledgerboard._num(e["id"]) == n for e in gone) else None
    open_parts = sum(1 for e in live if e is not own and _parent(e) == n)
    return EntryLedger(
        "open",
        design=ledgerboard.first_word(own["fields"].get("kind")) == "design-first",
        open_parts=open_parts,
        live_check=ledgerboard.first_word(own["fields"].get("kind")) == "live-check",
        had_parts=bool(open_parts) or any(_parent(e) == n for e in gone),
    )


def renumbered_on(root: Path | str, ref: str, rel: str, tid: str) -> str | None:
    """The id `tid` was renumbered to: the entry file the commit that last removed `<rel>/<tid>.md` on `ref` renamed it
    to, in the same directory. None where git cannot say, or where that commit deleted the file outright."""
    old = f"{rel.rstrip('/')}/{tid}.md"
    commit = (ledger._git(root, "log", "-1", "--format=%H", "--diff-filter=D", ref, "--", old) or "").strip()
    if not commit:
        return None
    out = ledger._git(root, "diff-tree", "-r", "-M", "--name-status", "-z", f"{commit}^", commit)
    fields = (out or "").split("\0")
    for at, field in enumerate(fields[:-2]):
        if field.startswith("R") and fields[at + 1] == old:
            new = PurePosixPath(fields[at + 2])
            found = _ENTRY_FILE.fullmatch(new.name)
            return found.group(1) if found and new.parent == PurePosixPath(old).parent else None
    return None


class EntryForge(NamedTuple):
    pr_state: Literal["open", "merged", "closed"] | None = None
    head: str | None = None
    archive_open: bool = False


def forge_on(tid: str, pr: int | None, rows: Iterable[Mapping[str, Any]]) -> EntryForge | None:
    """`Reading.pr_state`, `.head` and `.archive_open` of `tid`, whose record carries pull request `pr`, from the repo's
    rows. None: the rows do not hold `pr`, or hold it in a state this cannot read, so the caller has no reading of the
    entry this pass and acts on nothing. Only an open pull request has a head a move can carry."""
    rows = list(rows)
    subject = board.archive_subject(tid)
    archive_open = any(r.get("state") == "open" and r.get("title") == subject for r in rows)
    if pr is None:
        return EntryForge(archive_open=archive_open)
    row = next((r for r in rows if r.get("number") == pr), None)
    state = row.get("state") if row else None
    if state not in ("open", "merged", "closed"):
        return None
    return EntryForge(state, (row.get("head") or None) if state == "open" else None, archive_open)


def rows_for(
    reads: Iterable[Iterable[Mapping[str, Any]]],
    wanted: Iterable[int],
    read_one: Callable[[int], Mapping[str, Any] | None],
) -> tuple[Mapping[str, Any], ...]:
    """The repo's rows for `forge_on`, one per number. `reads` go latest first, so a stale open row never hides a merge.
    Each of `wanted`, the records' pull requests, that no read holds is read by its number; one that cannot be read
    stays missing, which is no reading of its entry this pass."""
    rows: list[Mapping[str, Any]] = []
    seen: set[Any] = set()
    for read in reads:
        for row in read:
            number = row.get("number")
            if number not in seen:
                seen.add(number)
                rows.append(row)
    for number in sorted(set(wanted) - seen):
        if (row := read_one(number)) is not None:
            rows.append(row)
    return tuple(rows)


class EntryFlow(NamedTuple):
    stage_known: bool
    flow_current: bool


def _kind_of(doc: Mapping[str, Any] | None, key: str) -> str | None:
    """What the stage `key` of `doc` does, or None where `doc` has no such stage."""
    for st in (doc or {}).get("stages") or []:
        if isinstance(st, Mapping) and key_of(st.get("name")) == key:
            return str(st.get("does"))
    return None


def flow_on(record: Mapping[str, Any], doc: Mapping[str, Any], was: Mapping[str, Any] | None = None) -> EntryFlow:
    """`Reading.stage_known` and `.flow_current` of `record` against `doc`, its team's copy of the flow. A record stores
    no stage's kind, so a key both flows have under different kinds is seen only through `was`, the flow the record was
    written under, where the caller still holds it; without it a key the copy has reads as known."""
    key = str(record.get("stage"))
    kind = _kind_of(doc, key)
    before = _kind_of(was, key)
    return EntryFlow(kind is not None and (before is None or before == kind), record.get("flow") == doc.get("name"))


def team_moved_on(team: str | None, named: str | None, teams: Collection[str]) -> bool:
    """`Reading.team_moved`: the entry's `Team:` line, `named`, names another of the repo's `teams` than the record's
    `team`. No line, or a name no team of the repo holds, moves nothing: closing a record for a team that cannot take
    the entry would strand it."""
    if not team or not named:
        return False
    word = named.casefold()
    return word != team.casefold() and any(word == t.casefold() for t in teams)


def carried_on(
    record: Mapping[str, Any], text: str, rows: Iterable[Mapping[str, Any]], branches: Collection[str]
) -> bool:
    """`Reading.carried_open` of a closed `record`: what it carried is still an open pull request, or a branch still
    pushed where the rows do not hold that pull request, and the entry's `text` logs no archive or reopen on or after
    the day the record closed. A Log's dates are days, so one of the same day counts as since the move."""
    carried = record.get("carried") or {}
    closed = str(record.get("closed_at") or "")[:10]
    if not carried or not closed:
        return False
    try:
        lines = ledgerboard.log_lines(text)
    except ledgerboard.Refused:
        return False
    if any(ln.get("kind") in ("archived", "reopened") and str(ln.get("date")) >= closed for ln in lines):
        return False
    row = next((r for r in rows if carried.get("pr") and r.get("number") == carried["pr"]), None)
    if row is not None:
        return row.get("state") == "open"
    return bool(carried.get("branch")) and carried["branch"] in branches


def only_when_protected(record: Mapping[str, Any], doc: Mapping[str, Any]) -> bool:
    """Whether the record's stage in `doc` runs `only-when: protected-files`."""
    key = str(record.get("stage"))
    stage = next(
        (s for s in doc.get("stages") or [] if isinstance(s, Mapping) and key_of(s.get("name")) == key),
        None,
    )
    return stage is not None and stage.get("only-when") == "protected-files"


def nothing_to_read_on(
    record: Mapping[str, Any],
    doc: Mapping[str, Any],
    head: str | None,
    read_at: str | None,
    files: Collection[str] | None,
    protected: Collection[str] | None,
) -> bool:
    """`Reading.nothing_to_read`: the record's stage in `doc` is `only-when: protected-files`, and `files`, the pull
    request's changed files as read at commit `read_at`, touch none of `protected`, the repo's `held:` globs. `head` is
    the pull request's head now, so a push since the read is no reading. `files` None or empty, or `protected` None,
    is no reading either and the stage keeps its review; `protected` empty is a repo read to have no protected files."""
    if not only_when_protected(record, doc):
        return False
    if not head or read_at != head or not files or protected is None:
        return False
    return not held.match(files, protected)


def pickable_on(entry: dict[str, Any], team: str) -> bool:
    """`Reading.pickable` of an entry from the repo's reading, for `team`: what a lane of that team would take by §6
    rule 6's one test, of a kind a flow has a way in for, whose `Owner:` is neither the person nor the anchor. A live
    check whose gates have lifted is taken as a lane takes it, by the stage for `other`; a work order is no entry."""
    kind = str(entry.get("kind") or "")
    if entry.get("work_order") or kind not in ("", "build", "live-check", "design-first"):
        return False
    if str(entry.get("owner") or "").lower() in (ledger.PERSON_OWNER, "person", "anchor"):
        return False
    return ledger.lane_matches(["design-first" if kind == "design-first" else "free-pick"], entry, team)


def held_on(prs: Iterable[dict[str, Any]], records: Iterable[Any]) -> frozenset[int]:
    """The numbers of the open pull requests in `prs` that a live session holds, by the test the red-PR orders use.
    `records` are the sessions of the pull requests' own repo: a number or a branch name means nothing across repos."""
    live = list(records)
    return frozenset(
        pr["number"]
        for pr in prs
        if isinstance(pr.get("number"), int)
        and pr.get("state") == "open"
        and any(workorders.holds_pr(r, pr) for r in live)
    )


def _instant(value: str | None) -> datetime | None:
    try:
        at = _parse(str(value)) if value else None
    except ValueError:
        return None
    return at.replace(tzinfo=UTC) if at is not None and at.tzinfo is None else at


def _lapsed(s: Session, tid: str, now: datetime) -> bool:
    """Whether the session's claim on `tid` ran out unrenewed. A derived claim holds no clock, as `_lease` reads it."""
    claims = [p for p in s.progress if p.ref == tid and p.status == "claimed"]
    if not claims or any(p.source != "declared" for p in claims):
        return False
    return not any((at := _instant(p.at)) is not None and now - at < LEASE_TTL for p in claims)


def _idle_for(s: Session, now: datetime) -> timedelta:
    """How long since the session last took a turn or did work; never negative, since a node's clock may run ahead."""
    seen = [at for v in (s.work_at, s.turn_at, s.created) if (at := _instant(v)) is not None]
    return max(now - max(seen), timedelta(0)) if seen else timedelta(0)


def holder_on(s: Session | None, tid: str, now: datetime, *, open_ask: bool = False) -> Holder:
    """`Reading.holder` for the session `s` holding `tid` (None: its record is gone). `open_ask`: it has an open ask of
    its own, which the caller reads from the mail."""
    if s is None:
        return Holder(ended=True)
    ended = s.state in ("exited", "closed")
    live_hold = bool(s.gated or s.stop_held or s.wind_down or s.wrapup_at) or s.state in ("limited", "unreachable")
    open_prompts = s.pendings or ([s.pending] if s.pending else [])
    permission = any(p.kind == "permission" for p in open_prompts)
    tool_at = _instant(s.tool_open_at)  # a lost tool-end must not hold it from silent for good, as the tick reads it
    busy = (tool_at is not None and now - tool_at <= OPEN_TOOL_CEILING) or subagents_live(s, now) or shells_live(s, now)
    return Holder(
        ended=ended,
        lease_lapsed=_lapsed(s, tid, now),
        held=bool(s.suspended) or (not ended and live_hold),
        stopped=ended and work._how_stopped(s) is not None,
        person=not ended and not s.unattended,
        idle_for=_idle_for(s, now),
        waiting=open_ask or busy or any(p.kind != "permission" for p in open_prompts),
        permission=permission,
    )


@dataclass(frozen=True)
class EntryFacts:
    """What the tick's wiring fetched for one entry.

    `ledger` is `ledger_on`'s answer and `renumbered_to` `renumbered_on`'s. `text` is the entry's own file, `entry` its
    row in the repo's reading, `named` its `Team:` line and `teams` the repo's teams. `doc` is the team's copy of the
    flow and `was` the flow the record was written under. `rows` are the repo's pull requests, `held` is `held_on`'s
    answer and `session` the holder's record. `may_start` and `within_size` are TD-2065's.
    """

    tid: str
    person: str
    team: str
    now: datetime
    doc: Mapping[str, Any]
    ledger: EntryLedger | None = None
    renumbered_to: str | None = None
    text: str | None = None
    entry: dict[str, Any] | None = None
    named: str | None = None
    teams: Collection[str] = ()
    rows: tuple[Mapping[str, Any], ...] = ()
    held: Collection[int] = ()
    branches: Collection[str] = ()
    was: Mapping[str, Any] | None = None
    session: Session | None = None
    open_ask: bool = False
    read_at: str | None = None
    files: Collection[str] | None = None
    protected: Collection[str] | None = None
    merge_running: bool = False
    may_start: bool = False
    within_size: bool = False


def reading_on(record: Mapping[str, Any] | None, f: EntryFacts) -> Reading | None:
    """The `Reading` of `f.tid` for `stage_acts.choose`. None: the entry is in neither file and was not renumbered, its
    text is missing or unreadable, or the rows do not hold the record's pull request, so the caller acts on nothing this
    pass. A closed record is read as no record is: what it once named is not asked of the forge."""
    if f.renumbered_to:
        return Reading(renumbered_to=f.renumbered_to, merge_running=f.merge_running)
    if f.ledger is None:
        return None
    if f.ledger.entry == "archived":
        return Reading(entry="archived", merge_running=f.merge_running)
    if f.text is None:
        return None
    try:
        answer = answer_on(f.text, f.person)
    except ledgerboard.Refused:
        return None
    live = record if record is not None and not record.get("closed_at") else None
    forge = forge_on(f.tid, live.get("pr") if live else None, f.rows)
    if forge is None:
        return None
    common = {
        "design": f.ledger.design,
        "live_check": f.ledger.live_check,
        "open_parts": f.ledger.open_parts,
        "had_parts": f.ledger.had_parts,
        "archive_open": forge.archive_open,
        "merge_running": f.merge_running,
        "gate": answer.gate,
        "lifted": answer.lifted,
        "lifted_for": answer.lifted_for,
        "may_start": f.may_start,
        "within_size": f.within_size,
    }
    if live is None:
        return Reading(
            pickable=f.entry is not None and pickable_on(f.entry, f.team),
            work=entry_work(f.tid, f.rows, held=f.held),
            carried_open=record is not None and carried_on(record, f.text, f.rows, f.branches),
            **common,
        )
    flow = flow_on(live, f.doc, f.was)
    return Reading(
        pr_state=forge.pr_state,
        head=forge.head,
        team_moved=team_moved_on(live.get("team"), f.named, f.teams),
        stage_known=flow.stage_known,
        flow_current=flow.flow_current,
        nothing_to_read=nothing_to_read_on(live, f.doc, forge.head, f.read_at, f.files, f.protected),
        holder=holder_on(f.session, f.tid, f.now, open_ask=f.open_ask) if live.get("holder") else None,
        work=EntryWork("none"),
        **common,
    )
