"""The home's merge of a job marked `merging` (design §4.9d *How each one runs*, §4.9c *The merge gate under a flow*,
TD-2053).

A job whose `work-pushed` the flow sends to `merge` waits `merging` with its pull request's head (`stage_job_end`). Its
merge is an entry's (`stage_merge`): the repo's gate runs on that head outside the store's lock, and the record is read
again under it before anything is merged or written. The gate ends one of four ways:

- it passes, and the home merges; the record stays `merging` until Reconcile reads its object gone (the pull request
  nobody held merged, or a board answer's line archived by its pull request) and closes it;
- a cause a session can cure takes the job stage's `refused` move for `work-pushed`, counted as any move's: back to
  the job's own stage, where the seat's next pass starts a fresh job session told the failing rows, or to a review
  stage; anywhere else, a limit or the cap reached, the job goes to the person;
- a row only a person can cure sends the job to the person, spending no limit: they merge by hand, which ends the job,
  or close the home's line, which starts it afresh;
- no reading leaves the record `merging`, tried again on later passes for an hour, and then sends it to the person.

A job goes to the person as any job does: the home's plain board line (`JobReach.line`) is written first and its id
kept on the record as `person_line`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from shiftlead import flow3, stage_job
from shiftlead.stage_end import destination
from shiftlead.stage_job_end import _stage, _where
from shiftlead.stage_job_start import job_stage
from shiftlead.stage_make import Made
from shiftlead.stage_merge import _STAMP, NO_READING_FOR, SESSION_ROWS, Gate, Land
from shiftlead.stagerecord import StageStore, _now

Line = Callable[[Mapping[str, Any], str], str | None]  # `JobReach.line`: the home's plain board line, its id or None


def merging(store: StageStore) -> list[str]:
    """The keys of the open job records that wait on the home's merge, in key order."""
    return sorted(
        str(k)
        for k, r in store.jobs().items()
        if isinstance(r, Mapping) and not r.get("closed_at") and r.get("waits") == "merging"
    )


def _current(store: StageStore, key: str, head: str | None) -> dict[str, Any] | None:
    """The record, if it still waits on this merge of this head. Call with the lock held."""
    record = store.job(key)
    if record is None or record.get("waits") != "merging" or record.get("closed_at"):
        return None
    return dict(record) if (record.get("merging") or {}).get("head") == head else None


def _to_person(store: StageStore, record: dict[str, Any], reason: str, line: Line) -> Made:
    """The job waits on the person, its merge given up: the home's line first, its id kept as `person_line`."""
    try:
        got = line(record, reason)
    except Exception as e:  # noqa: BLE001 — nothing is written; the next pass tries again
        return Made(False, f"the home's board line could not be written: {e}")
    if not got:
        return Made(False, "the home's board line could not be written")
    merging = record.get("merging") or {}
    step = {
        "from": merging.get("stage") or record.get("stage"),
        "outcome": "refused",
        "reason": reason,
        "by": "home",
        "to": "person",
        "head": merging.get("head"),
        "at": _now(),
    }
    history = [*(record.get("history") or []), step]
    store.put_job(
        stage_job.to_person({**record, "merging": None, "history": history}, got), f"merging: to the person ({reason})"
    )
    return Made(True)


def _no_reading(store: StageStore, key: str, head: str | None, why: str, line: Line, now: datetime) -> Made:
    """The record stays `merging` and the first such pass is stamped; an hour on, the job goes to the person."""
    with store.locked():
        record = _current(store, key, head)
        if record is None:
            return Made(False, "the record moved while the gate ran")
        merging = dict(record["merging"])
        since = merging.get("unread_since")
        if not since:
            merging["unread_since"] = now.strftime(_STAMP)
            store.put_job({**record, "merging": merging}, f"merging: no reading yet ({why})")
            return Made(False, why)
        try:
            began = datetime.strptime(str(since), _STAMP).replace(tzinfo=UTC)
        except ValueError:
            began = now - NO_READING_FOR  # a stamp nobody can read must not keep the record here for good
        if now - began < NO_READING_FOR:
            return Made(False, why)
        return _to_person(store, record, f"the merge gate gave no reading for an hour: {why}", line)


def _refused(store: StageStore, key: str, head: str | None, doc: Mapping[str, Any], why: str, line: Line) -> Made:
    """A cause a session can cure: the job stage's `refused` move for `work-pushed`, its limit and the flow's cap
    counted as any move's. A destination a job never goes to, `merge` among them, is the person's."""
    with store.locked():
        record = _current(store, key, head)
        if record is None:
            return Made(False, "the record moved while the gate ran")
        here = job_stage(doc)
        stage = _stage(doc, here)
        if here is None or stage is None:
            return _to_person(store, record, f"the merge was refused: {why}", line)
        outcome = str((record.get("merging") or {}).get("outcome") or "work-pushed")
        raw = destination(stage, outcome).get("refused", "person")
        where = destination({"refused": raw}, "refused")
        went = _where(doc, here, str(where["to"]))
        if went in ("person", "merge"):
            return _to_person(store, record, f"the merge was refused: {why}", line)
        count, counts = f"{here}:refused", dict(record.get("counts") or {})
        limit, cap = where.get("limit"), doc.get("max-moves", flow3.MAX_MOVES)
        if limit is not None and int(counts.get(count, 0)) >= int(limit):
            return _to_person(store, record, f"the merge was refused ({why}), and refused reached its limit", line)
        if int(record.get("moves") or 0) >= int(cap):
            return _to_person(store, record, f"the merge was refused ({why}), and the job reached the flow's cap", line)
        counts[count] = int(counts.get(count, 0)) + 1
        step = {"from": here, "outcome": "refused", "reason": why, "by": "home", "to": went, "head": head, "at": _now()}
        store.put_job(
            {
                **record,
                "counts": counts,
                "moves": int(record.get("moves") or 0) + 1,
                "history": [*(record.get("history") or []), step],
                "waits": None,
                "merging": None,
                "holder": None,
                "stage": went,
                "entered_at": _now(),
                "offers": 0,
            },
            f"merging: refused, to {went}",
        )
        return Made(True)


def run(
    store: StageStore,
    key: str,
    head_now: str | None,
    doc: Mapping[str, Any],
    gate: Gate,
    land: Land,
    line: Line,
    now: datetime | None = None,
) -> Made:
    """Run the gate on the job's head and take the one way it ended. `head_now` is its pull request's head as the
    pass read it (None: not read), and `doc` the flow of the job's team."""
    at = now or datetime.now(UTC)
    with store.locked():
        record = store.job(key)
        if record is None or record.get("closed_at") or record.get("waits") != "merging":
            return Made(False, "the record moved since it was read")
        pr, head = record.get("pr"), (record.get("merging") or {}).get("head")

    def unread(why: str) -> Made:
        return _no_reading(store, key, head, why, line, at)

    if not pr or not head:
        return unread("the record names no pull request or head to merge")
    if not head_now:
        return unread("the pull request's head was not read")
    if head_now != head:
        return _refused(store, key, head, doc, f"the head is {head_now[:12]}, not the one the job pushed", line)
    try:
        got = gate(int(pr), str(head))
    except Exception as e:  # noqa: BLE001 — a gate that cannot run is no reading, whatever it raised
        return unread(f"the gate could not run: {e}")
    verdict = (got or {}).get("verdict")
    if verdict == "fail":
        failed = [str(row) for row in (got or {}).get("failed") or []]
        rows = ", ".join(failed) or "a row"
        if not failed or not SESSION_ROWS.issuperset(failed):  # a person's row, or one no list sorts
            with store.locked():
                record = _current(store, key, head)
                if record is None:
                    return Made(False, "the record moved while the gate ran")
                return _to_person(store, record, f"the merge gate failed on {rows}, which needs a person", line)
        return _refused(store, key, head, doc, f"the merge gate failed on {rows}", line)
    if verdict != "pass":
        return unread("the merge gate gave no reading")
    with store.locked():
        if _current(store, key, head) is None:
            return Made(False, "the record moved while the gate ran")
    try:
        why = land(int(pr), str(head))
    except Exception as e:  # noqa: BLE001 — a merge that cannot run leaves the record to be tried again
        why = f"the merge could not run: {e}"
    return unread(why) if why else Made(True)
