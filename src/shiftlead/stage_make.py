"""Making the acts that only write a stage record (design §4.9c *The home acts only where no session will*, TD-2051).

`make` takes what `stage_acts.choose` named and writes it, with the store's lock held from the record's read to its
write. The record is read again under that lock and the choice made again, so an `ao stage end` that landed after the
home's reading is never overwritten: the act is simply not made, and the next pass reads afresh.

This slice makes reconcile's cases that need no session and no new question (`close`, `renumbered`, `land-intent`,
`wait-for-parts`, `mark-waiting`, `rewrite-flow`), the person's answer, and the pass; `sweep_closed` removes a closed
record after its thirty days. Every other case returns `Made(False, …)` and writes nothing. Nothing calls this yet.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shiftlead import flow3
from shiftlead.stage_acts import Act, Reading, choose, closed_expired
from shiftlead.stage_end import _apply, _stage_or_none, destination
from shiftlead.stagerecord import StageStore, _now, answer_move


@dataclass(frozen=True)
class Made:
    made: bool
    why: str = ""


def _close(store: StageStore, record: dict[str, Any], _s: Reading, _doc: dict[str, Any]) -> Made:
    record.update(closed_at=_now(), holder=None, waits=None, intent=None)
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
        if stage is not None and outcome in stage:
            kept[count] = n
    record.update(flow=name, counts=kept)
    store.put_entry(record, f"rewritten to flow {name}")
    return Made(True)


_RECONCILE: dict[str, Callable[[StageStore, dict[str, Any], Reading, dict[str, Any]], Made]] = {
    "close": _close,
    "renumbered": _renumbered,
    "land-intent": _land_intent,
    "wait-for-parts": _wait_for_parts,
    "mark-waiting": _mark_waiting,
    "rewrite-flow": _rewrite_flow,
}


def _answer(store: StageStore, record: dict[str, Any], s: Reading, doc: dict[str, Any], person: str) -> Made:
    """The person's lifted label, mapped to a move by the record's answer map (act 2). An answer at a limit or the cap
    takes the stopped move, in the person's own words too, and only it starts that move's count and the cap's again.
    The move is not counted."""
    label = str(s.lifted)
    move, words = answer_move(record.get("answers") or {}, label)
    blocked = record.get("blocked") or {}
    stopped = blocked.get("to")
    if move is None and stopped:
        move = {"blocked": True}
    if isinstance(move, dict):
        if not move.get("blocked") or not stopped:
            return Made(False, f"the answer {label!r} is a later slice's move")
        to = str(stopped)
    else:
        to = str(record["stage"]) if move is None else str(move)
    if to in flow3.FIXED or _stage_or_none(doc, to) is None:
        return Made(False, f"the answer {label!r} goes to {to}, which is not a stage of the flow")
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
        stage=to, holder=None, waits=None, answers=None, blocked=None, answer=words, offers=0, entered_at=_now()
    )
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


def make(store: StageStore, tid: str, act: Act, s: Reading, doc: dict[str, Any], person: str) -> Made:
    """Write `act` on `tid`'s record, if a fresh read under the lock still chooses it."""
    with store.locked():
        record = store.entry(tid)
        if record is None:
            return Made(False, f"{tid} has no stage record")
        if choose(record, s) != act:
            return Made(False, "the record moved since it was read")
        if act.name == "answer":
            return _answer(store, record, s, doc, person)
        if act.name == "pass":
            return _pass(store, record, s, doc, person)
        maker = _RECONCILE.get(act.case) if act.name == "reconcile" else None
        if maker is None:
            return Made(False, f"{act.name} {act.case} is a later slice's")
        return maker(store, record, s, doc)


def sweep_closed(store: StageStore, now: datetime | None = None) -> list[str]:
    """Remove the closed records kept their thirty days, in one commit; the branch's history keeps them."""
    with store.locked():
        gone = sorted(tid for tid, r in store.entries().items() if closed_expired(r, now))
        if gone:
            store.drop_entries(gone, f"removed {len(gone)} closed record(s) past thirty days")
    return gone
