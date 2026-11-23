"""The home's merge of a record marked `merging` (design §4.9c *The merge gate under a flow*, TD-2051).

`run` makes reconcile's `merging` case. The gate and the merge are slow, so neither runs under the store's lock: the
record is read under it, the gate runs, and the record is read again under it before anything is merged or written, so
an `ao stage end` or a person's move that landed meanwhile is never overwritten.

The gate ends one of four ways. It passes, and the home merges; the record then closes by reconcile, once the forge
shows the merge and the ledger reads the entry archived. A cause a session can cure takes the outcome's `refused` move.
A row only a person can cure sends the entry to the person with *Try the merge again*, spending no limit. No reading
leaves the record `merging`, tried again on later passes for an hour, and then goes to the person, spending no limit.

`gate` and `land` are given by the caller; nothing calls this yet.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from shiftlead.stage_acts import Act, Reading, choose
from shiftlead.stage_end import TRY_AGAIN, _answers, _apply, _stage_or_none, destination
from shiftlead.stage_make import Made, _ask, _back
from shiftlead.stagerecord import StageStore

NO_READING_FOR = timedelta(hours=1)
PERSON_ROWS = frozenset({"reach", "person"})  # the gate's rows only a person can cure
MERGING = Act("reconcile", "merging")
_STAMP = "%Y-%m-%dT%H:%M:%SZ"

Gate = Callable[[int, str], Mapping[str, Any] | None]  # `cadence.check`'s `{verdict, failed}`, or None for no reading
Land = Callable[[int, str], str | None]  # merges that pull request at that head: None, or why it did not


def _current(store: StageStore, tid: str, head: str | None) -> dict[str, Any] | None:
    """The record, if it still waits on this merge of this head. Call with the lock held."""
    record = store.entry(tid)
    if record is None or record.get("waits") != "merging" or record.get("closed_at"):
        return None
    return record if (record.get("merging") or {}).get("head") == head else None


def _to_person(
    store: StageStore, record: dict[str, Any], s: Reading, doc: dict[str, Any], person: str, context: str
) -> Made:
    ask = "The merge of this entry needs you, what next?"
    return _ask(store, record, s, person, ask, context, {TRY_AGAIN: {"merge": True}, **_back(record, doc)})


def _no_reading(
    store: StageStore,
    tid: str,
    head: str | None,
    s: Reading,
    doc: dict[str, Any],
    person: str,
    why: str,
    now: datetime,
) -> Made:
    """The record stays `merging` and the first such pass is stamped; an hour on, the entry goes to the person."""
    with store.locked():
        record = _current(store, tid, head)
        if record is None:
            return Made(False, "the record moved while the gate ran")
        merging = record["merging"]
        since = merging.get("unread_since")
        if not since:
            merging["unread_since"] = now.strftime(_STAMP)
            store.put_entry(record, f"merging: no reading yet ({why})")
            return Made(False, why)
        try:
            began = datetime.strptime(str(since), _STAMP).replace(tzinfo=UTC)
        except ValueError:
            began = now - NO_READING_FOR  # a stamp nobody can read must not keep the record here for good
        if now - began < NO_READING_FOR:
            return Made(False, why)
        return _to_person(store, record, s, doc, person, f"The merge gate gave no reading for an hour: {why}.")


def _refused(
    store: StageStore,
    tid: str,
    head: str | None,
    s: Reading,
    doc: dict[str, Any],
    person: str,
    why: str,
) -> Made:
    """A cause a session can cure: the outcome's `refused` move, with a limit counted as any move's."""
    with store.locked():
        record = _current(store, tid, head)
        if record is None:
            return Made(False, "the record moved while the gate ran")
        merging = record["merging"]
        key, outcome = str(merging.get("stage") or record["stage"]), str(merging.get("outcome") or "")
        stage = _stage_or_none(doc, key)
        if stage is None:
            return _to_person(store, record, s, doc, person, f"The merge was refused: {why}.")
        raw = destination(stage, outcome).get("refused", "person")
        where = destination({"refused": raw}, "refused")
        if where["to"] == "person":
            context = f"The merge was refused: {why}."
            ask = "The merge of this entry was refused, what next?"
            return _ask(store, record, s, person, ask, context, _answers(stage, key, "refused", where, False))
        record.update(waits=None, merging=None)
        _apply(store, record, doc, stage, key, "refused", why, where, head, person, "home")
        return Made(True)


def run(
    store: StageStore,
    tid: str,
    act: Act,
    s: Reading,
    doc: dict[str, Any],
    person: str,
    gate: Gate,
    land: Land,
    now: datetime | None = None,
) -> Made:
    """Run the gate on the record's head and take the one way it ended."""
    at = now or datetime.now(UTC)
    with store.locked():
        record = store.entry(tid)
        if act != MERGING or record is None or choose(record, s) != act:
            return Made(False, "the record moved since it was read")
        pr, head = record.get("pr"), (record.get("merging") or {}).get("head")

    def unread(why: str) -> Made:
        return _no_reading(store, tid, head, s, doc, person, why, at)

    if not pr or not head:
        return unread("the record names no pull request or head to merge")
    if not s.head:
        return unread("the pull request's head was not read")
    if s.head != head:
        return _refused(store, tid, head, s, doc, person, f"the head is {s.head[:12]}, not the one the verdict read")
    try:
        got = gate(int(pr), str(head))
    except Exception as e:  # noqa: BLE001 — a gate that cannot run is no reading, whatever it raised
        return unread(f"the gate could not run: {e}")
    verdict = (got or {}).get("verdict")
    if verdict == "fail":
        failed = [str(row) for row in (got or {}).get("failed") or []]
        rows = ", ".join(failed) or "a row"
        if PERSON_ROWS.intersection(failed):
            with store.locked():
                record = _current(store, tid, head)
                if record is None:
                    return Made(False, "the record moved while the gate ran")
                return _to_person(store, record, s, doc, person, f"The merge gate's {rows} row needs a person.")
        return _refused(store, tid, head, s, doc, person, f"the merge gate failed on {rows}")
    if verdict != "pass":
        return unread("the merge gate gave no reading")
    with store.locked():
        if _current(store, tid, head) is None:
            return Made(False, "the record moved while the gate ran")
    try:
        why = land(int(pr), str(head))
    except Exception as e:  # noqa: BLE001 — a merge that cannot run leaves the record to be tried again
        why = f"the merge could not run: {e}"
    return unread(why) if why else Made(True)
