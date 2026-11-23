"""Making the acts that only write a stage record (design §4.9c *The home acts only where no session will*, TD-2051).

`make` takes what `stage_acts.choose` named and writes it, with the store's lock held from the record's read to its
write. The record is read again under that lock and the choice made again, so an `ao stage end` that landed after the
home's reading is never overwritten: the act is simply not made, and the next pass reads afresh.

It makes reconcile's cases that start no session (`close`, `renumbered`, `land-intent`, `wait-for-parts`,
`mark-waiting`, `rewrite-flow`, `re-enter`, `archive-design`) and those that put a question to the person
(`merged-entry-open`, `pr-closed`, `stage-gone`, `gate-again`), the person's answer (an archive answer landing its own
pull request), the
pass, and the record's half of offering again (the
holder cleared, the offer counted, or a second loss sent to the person). `offer` makes act 5: it starts the session,
takes its claim and writes the record.
`sweep_closed` removes a closed record after its thirty days. The `merging` case is `stage_merge.run`'s, whose gate and
merge run outside the lock; *Try the merge again* is this module's answer. Every other case returns `Made(False, …)`
and writes nothing. A write that takes a record from its holder names that session in `Made.end`, for the caller to
end outside the lock. Nothing calls this yet.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sessionorc import board
from shiftlead import flow3
from shiftlead.stage_acts import Act, Reading, choose, closed_expired
from shiftlead.stage_end import ARCHIVE, _apply, _stage_or_none, destination
from shiftlead.stage_start import Work
from shiftlead.stagerecord import StageStore, _now, answer_move, new_record


@dataclass(frozen=True)
class Made:
    made: bool
    why: str = ""
    end: str | None = None  # the session this write took the record from


def _close(store: StageStore, record: dict[str, Any], _s: Reading, _doc: dict[str, Any]) -> Made:
    record.update(closed_at=_now(), holder=None, waits=None, intent=None, asked=None)
    store.put_entry(record, "closed: the entry is archived")
    return Made(True)


def _renumbered(store: StageStore, record: dict[str, Any], s: Reading, _doc: dict[str, Any]) -> Made:
    old, new = str(record["id"]), str(s.renumbered_to)
    if store.entry(new) is not None:
        return Made(False, f"{new} already has a record")
    record["id"] = new
    store.move_entry(record, old, f"renumbered from {old}")
    return Made(True)


def _land_intent(store: StageStore, record: dict[str, Any], _s: Reading, _doc: dict[str, Any]) -> Made:
    store.land_intent(str(record["id"]))
    return Made(True)


def _wait_for_parts(store: StageStore, record: dict[str, Any], _s: Reading, _doc: dict[str, Any]) -> Made:
    record.update(waits="parts", holder=None)
    store.put_entry(record, "merged: waits for its parts")
    return Made(True)


def _mark_waiting(store: StageStore, record: dict[str, Any], _s: Reading, _doc: dict[str, Any]) -> Made:
    record["waits"] = "person"
    store.put_entry(record, "carries the home's gate: waits on the person")
    return Made(True)


def _rewrite_flow(store: StageStore, record: dict[str, Any], _s: Reading, doc: dict[str, Any]) -> Made:
    """The record moves to the team's copy of its flow: its stage and holder stand, and the counts of moves the new
    flow lacks are dropped."""
    name = doc.get("name")
    if not name:
        return Made(False, "the flow has no name")
    kept: dict[str, Any] = {}
    for count, n in (record.get("counts") or {}).items():
        key, _, outcome = str(count).rpartition(":")
        stage = _stage_or_none(doc, key)
        if stage is not None and (outcome in stage or outcome == "refused"):  # a refused merge's count is its own
            kept[count] = n
    record.update(flow=name, counts=kept)
    store.put_entry(record, f"rewritten to flow {name}")
    return Made(True)


def _way_in(doc: dict[str, Any], design: bool) -> str | None:
    """The key of the stage that takes an entry of this kind (§4.9c *Ways in*)."""
    kind = "design-first" if design else "other"
    for st in doc.get("stages") or []:
        if isinstance(st, dict) and st.get("takes") in (kind, "any"):
            return flow3.key_of(st["name"])
    return None


def _re_enter(store: StageStore, record: dict[str, Any], s: Reading, doc: dict[str, Any]) -> Made:
    """A record that has made no move, whose stage its flow lacks: it enters again by the way in for its kind, keeping
    its branch and pull request."""
    to, name = _way_in(doc, s.design), doc.get("name")
    if to is None or not name:
        return Made(False, "the flow has no stage that takes this entry")
    record.setdefault("history", []).append(
        {
            "from": record["stage"],
            "outcome": "re-enter",
            "reason": "its stage left the flow",
            "by": "home",
            "to": to,
            "head": None,
            "at": _now(),
        }
    )
    record.update(flow=name, stage=to, holder=None, offers=0, entered_at=_now())
    store.put_entry(record, f"re-entered at {to}")
    return Made(True)


def _archive_design(store: StageStore, record: dict[str, Any], _s: Reading, _doc: dict[str, Any]) -> Made:
    """A design entry left open after its last part merged: the home archives it in a pull request of its own, and the
    record closes when the ledger reads it archived (§4.9c *Who archives the entry*)."""
    try:
        store.archive(str(record["id"]), "its last part merged")
    except board.Refused as e:  # the record stands, so the next pass tries again
        return Made(False, f"the entry could not be archived: {e}")
    return Made(True)


def _ask(
    store: StageStore, record: dict[str, Any], s: Reading, person: str, ask: str, context: str, answers: dict[str, Any]
) -> Made:
    """A move to the person, as its intent. An entry already carrying the gate is not asked a second time."""
    record.update(holder=None, waits="person" if s.gate else None)
    if s.gate:  # a gate this record did not ask: no earlier question's map or mark applies to its answer
        record.update(answers=None, asked=None)
        store.put_entry(record, "carries the home's gate: waits on the person")
    else:
        store.record_intent(
            str(record["id"]), person, ask, context, answers, blocked=record.get("blocked"), base=record
        )
    return Made(True)


def _to_stages(doc: dict[str, Any]) -> dict[str, Any]:
    """The flow's stages as the answers to a question about where the entry goes."""
    stages = [st for st in doc.get("stages") or [] if isinstance(st, dict)]
    return {f"{st['name']} — a session takes it to this stage": flow3.key_of(st["name"]) for st in stages}


def _merged_open(store: StageStore, record: dict[str, Any], s: Reading, doc: dict[str, Any], person: str) -> Made:
    ask = "Its pull request merged but the entry is still open, what next?"
    context = f"Pull request {record.get('pr')} merged and did not archive this entry."
    return _ask(store, record, s, person, ask, context, {ARCHIVE: {"archive": True}})


def _back(record: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """The answer that starts the record's stage again, or the flow's stages where it has left the flow."""
    key = str(record["stage"])
    stage = _stage_or_none(doc, key)
    return {f"Back to {stage['name']} — a session starts this stage again": key} if stage else _to_stages(doc)


def _pr_closed(store: StageStore, record: dict[str, Any], s: Reading, doc: dict[str, Any], person: str) -> Made:
    ask = "Its pull request was closed without merging, what next?"
    context = f"Pull request {record.get('pr')} was closed unmerged."
    return _ask(store, record, s, person, ask, context, _back(record, doc))


def _stage_gone(store: StageStore, record: dict[str, Any], s: Reading, doc: dict[str, Any], person: str) -> Made:
    ask = "The stage this entry was in has left its flow, which stage next?"
    context = f"The flow no longer has the stage {record['stage']}."
    return _ask(store, record, s, person, ask, context, _to_stages(doc))


def _gate_again(store: StageStore, record: dict[str, Any], _s: Reading, doc: dict[str, Any], person: str) -> Made:
    """The gate and its item are gone with no answer: the same question again, under a new mark."""
    asked = record.get("asked") or {}
    ask = asked.get("ask") or "This entry was waiting on you and its question is gone, what next?"
    context = asked.get("context") or "The entry's decision was removed with no answer recorded."
    answers = asked.get("answers") or _to_stages(doc)
    store.record_intent(str(record["id"]), person, ask, context, answers, blocked=record.get("blocked"), base=record)
    return Made(True)


_ASKS: dict[str, Callable[[StageStore, dict[str, Any], Reading, dict[str, Any], str], Made]] = {
    "merged-entry-open": _merged_open,
    "pr-closed": _pr_closed,
    "stage-gone": _stage_gone,
    "gate-again": _gate_again,
}

_RECONCILE: dict[str, Callable[[StageStore, dict[str, Any], Reading, dict[str, Any]], Made]] = {
    "close": _close,
    "renumbered": _renumbered,
    "land-intent": _land_intent,
    "wait-for-parts": _wait_for_parts,
    "mark-waiting": _mark_waiting,
    "rewrite-flow": _rewrite_flow,
    "re-enter": _re_enter,
    "archive-design": _archive_design,
}


def _merge_again(store: StageStore, record: dict[str, Any], words: str) -> Made:
    """*Try the merge again*: the record is `merging` at the head its verdict read, and the gate runs afresh."""
    merging = record.get("merging") or {}
    if not merging.get("head"):
        return Made(False, "the record holds no merge to try again")
    fresh = {k: v for k, v in merging.items() if k != "unread_since"}
    record.update(waits="merging", merging=fresh, answers=None, asked=None, blocked=None, answer=words)
    store.put_entry(record, "the person's answer: try the merge again")
    return Made(True)


def _answer(store: StageStore, record: dict[str, Any], s: Reading, doc: dict[str, Any], person: str) -> Made:
    """The person's lifted label, mapped to a move by the record's answer map (act 2). An answer at a limit or the cap
    takes the stopped move, in the person's own words too, and only it starts that move's count and the cap's again.
    The move is not counted."""
    label = str(s.lifted)
    move, words = answer_move(record.get("answers") or {}, label)
    if isinstance(move, dict) and move.get("merge"):
        return _merge_again(store, record, words)
    blocked = record.get("blocked") or {}
    stopped = blocked.get("to")
    if move is None and stopped:
        move = {"blocked": True}
    if isinstance(move, dict) and move.get("archive"):
        try:
            store.archive(str(record["id"]), f"the person's answer: {words}")
        except board.Refused as e:  # the record still waits, so the next pass tries again
            return Made(False, f"the entry could not be archived: {e}")
        return Made(True)  # the record closes when the ledger reads the entry archived
    if isinstance(move, dict):
        if not move.get("blocked") or not stopped:
            return Made(False, f"the answer {label!r} is a later slice's move")
        to = str(stopped)
    else:
        to = str(record["stage"]) if move is None else str(move)
    if to in flow3.FIXED:
        return Made(False, f"the answer {label!r} goes to {to}, which is a later slice's move")
    if _stage_or_none(doc, to) is None:
        ask = "The stage that answer names has left the flow, which stage next?"
        return _ask(store, record, s, person, ask, f"The answer {label} goes to {to}.", _to_stages(doc))
    if isinstance(move, dict):
        record.setdefault("counts", {}).pop(blocked.get("count"), None)
        record["moves"] = 0
    record.setdefault("history", []).append(
        {
            "from": record["stage"],
            "outcome": "answer",
            "reason": words,
            "by": person,
            "to": to,
            "head": None,
            "at": _now(),
        }
    )
    record.update(
        stage=to,
        holder=None,
        waits=None,
        answers=None,
        asked=None,
        blocked=None,
        answer=words,
        merging=None,
        offers=0,
        entered_at=_now(),
    )
    if s.pr_state in ("merged", "closed"):  # that pull request is over: the stage starts from a fresh one
        record.update(branch=None, pr=None)
    store.put_entry(record, f"the person's answer: to {to}")
    return Made(True)


def _pass(store: StageStore, record: dict[str, Any], s: Reading, doc: dict[str, Any], person: str) -> Made:
    """An `only-when` stage with nothing to read counts as `ship` at its head: it writes `{head, passed}` and posts
    no review (§4.9c)."""
    key = str(record["stage"])
    stage = _stage_or_none(doc, key)
    if stage is None or not stage.get("only-when"):
        return Made(False, f"{key} is not an only-when stage of the flow")
    where = destination(stage, "ship")
    if where["to"] == "merge" and not s.head:
        return Made(False, "the pull request's head was not read")
    record.setdefault("verdicts", {})[key] = {"head": s.head, "passed": True}
    _apply(
        store, record, doc, stage, key, "ship", "passed: nothing for this stage to read", where, s.head, person, "home"
    )
    return Made(True)


def _offer_again(
    store: StageStore, record: dict[str, Any], act: Act, s: Reading, doc: dict[str, Any], person: str
) -> Made:
    """Act 4's write. A second loss goes to the person; any other clears the holder, and a loss that happened while
    the team ran counts the offer the next pass makes. A holder ended by a Stop or a hold leaves the count as it is."""
    if act.case == "to-person":
        ask = "Two sessions in a row were lost on this entry, what next?"
        context = f"The sessions holding it in the stage {record['stage']} ended or went silent twice."
        return _ask(store, record, s, person, ask, context, _back(record, doc))
    record["holder"] = None
    if act.counted:
        record["offers"] = int(record.get("offers") or 0) + 1
    store.put_entry(record, f"offered again: {act.case}")
    return Made(True)


def make(store: StageStore, tid: str, act: Act, s: Reading, doc: dict[str, Any], person: str) -> Made:
    """Write `act` on `tid`'s record, if a fresh read under the lock still chooses it."""
    with store.locked():
        record = store.entry(tid)
        if record is None:
            return Made(False, f"{tid} has no stage record")
        if choose(record, s) != act:
            return Made(False, "the record moved since it was read")
        held = record.get("holder")
        if act.name == "answer":
            got = _answer(store, record, s, doc, person)
        elif act.name == "pass":
            got = _pass(store, record, s, doc, person)
        elif act.name == "offer-again":
            got = _offer_again(store, record, act, s, doc, person)
        elif act.name == "reconcile" and act.case in _ASKS:
            got = _ASKS[act.case](store, record, s, doc, person)
        elif act.name == "reconcile" and act.case in _RECONCILE:
            got = _RECONCILE[act.case](store, record, s, doc)
        else:
            return Made(False, f"{act.name} {act.case} is a later slice's")
        return replace(got, end=held) if got.made and held and not record.get("holder") else got


def offer(
    store: StageStore,
    tid: str,
    act: Act,
    s: Reading,
    doc: dict[str, Any],
    start: Callable[[str, Work], str | None],
    claim: Callable[[str, str], str | None],
    *,
    team: str,
) -> Made:
    """Act 5: a fresh session of the stage holds the entry, with its claim, and the record says so. `start` returns the
    holder's address or None; `claim` returns why it was refused or None. The lock is held throughout, so an entry is
    never offered twice. A session whose claim or record could not be written is named in `Made.end` for the caller to
    end, and the next pass offers afresh. `team` is the team whose flow `doc` is, written on a new record."""
    with store.locked():
        record = store.entry(tid)
        if act.name != "offer" or choose(record, s) != act:
            return Made(False, "the record moved since it was read")
        name = doc.get("name")
        first = record is None or bool(record.get("closed_at"))
        if record is None or first:  # a reopened entry's closed record carries nothing over (§4.9c)
            key = _way_in(doc, s.design)
            row = act.work.pr if act.work is not None and act.work.state == "take" else None
            branch, pr = (row.get("branch"), row.get("number")) if row else (None, None)
        else:
            key, branch, pr = str(record["stage"]), record.get("branch"), record.get("pr")
        if key is None or not name:
            return Made(False, "the flow has no stage that takes this entry")
        holder = start(key, Work(tid, branch, pr))
        if holder is None:
            return Made(False, "no session was started")
        try:
            if refused := claim(holder, tid):
                return Made(False, f"the claim was refused: {refused}", end=holder)
            if record is None or first:
                record = {**new_record(tid, str(name), key, team=team, holder=holder), "branch": branch, "pr": pr}
            else:  # a count a loss left stands, so the next loss is the second
                record.update(holder=holder, offers=max(int(record.get("offers") or 0), 1))
            store.put_entry(record, f"offered at {key} to {holder}")
        except Exception as e:  # noqa: BLE001 — whatever failed, a started session must not be left unnamed
            return Made(False, f"the offer did not finish: {e}", end=holder)
        return Made(True)


def sweep_closed(store: StageStore, now: datetime | None = None) -> list[str]:
    """Remove the closed records kept their thirty days, in one commit; the branch's history keeps them."""
    with store.locked():
        gone = sorted(tid for tid, r in store.entries().items() if closed_expired(r, now))
        if gone:
            store.drop_entries(gone, f"removed {len(gone)} closed record(s) past thirty days")
    return gone
