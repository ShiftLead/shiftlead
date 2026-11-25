"""The home's merge of a record marked `merging` (design §4.9c *The merge gate under a flow*, TD-2051).

`run` makes reconcile's `merging` case. The gate and the merge are slow, so neither runs under the store's lock: the
record is read under it, the gate runs, and the record is read again under it before anything is merged or written, so
an `ao stage end` or a person's move that landed meanwhile is never overwritten.

The gate ends one of four ways. It passes, and the home merges; the record then closes by reconcile, once the forge
shows the merge and the ledger reads the entry archived. A cause a session can cure takes the outcome's `refused` move.
A row only a person can cure sends the entry to the person with *Try the merge again*, spending no limit. No reading
leaves the record `merging`, tried again on later passes for an hour, and then goes to the person, spending no limit.

`gate_and_land` makes the two for a repo: the gate's own script on the pull request, then cadence step 5's merge, signed
`Merged-by: shiftlead-home`; the tick's stage pass (`stage_tick`) holds one pair per repo. Every row the gate writes is
sorted as one a session can cure (`SESSION_ROWS`) or one only a person can (`PERSON_ROWS`), and a failed row in neither,
one a later pin adds, is read as the person's, since a limit spent on a cause no session can cure helps nobody.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc import cadence, sync
from shiftlead.stage_acts import Act, Reading, choose
from shiftlead.stage_end import TRY_AGAIN, _answers, _apply, _stage_or_none, destination
from shiftlead.stage_make import Made, _ask, _back
from shiftlead.stagerecord import StageStore

NO_READING_FOR = timedelta(hours=1)
PERSON_ROWS = frozenset({"reach", "person"})  # the gate's rows only a person can cure
# The gate's rows a session can cure: the pull request itself, its review, checks, base, ledger and board, the gates
# and sources rows on the ledger, the branch's worktree and push, and the repo's deploy check on its head.
SESSION_ROWS = frozenset(
    {"pr", "review", "ci", "base", "ledger", "board", "gates", "sources", "worktree", "pushed", "deploy"}
)
MERGING = Act("reconcile", "merging")
MERGED_BY = "shiftlead-home"  # the squash's `Merged-by:` on a flow's merge, with no model since the home runs none
_STAMP = "%Y-%m-%dT%H:%M:%SZ"

Gate = Callable[[int, str], Mapping[str, Any] | None]  # `cadence.check`'s `{verdict, failed}`, or None for no reading
Land = Callable[[int, str], str | None]  # merges that pull request at that head: None, or why it did not


def gate_and_land(root: Path | str) -> tuple[Gate, Land]:
    """The repo's real `Gate` and `Land`. The gate's script runs on the pull request then and there, and what it passed
    is kept for the merge: the head, and the trailers where the pinned tree composes the squash. `land` merges only a
    head the gate passed, at that head, and a composed squash only where it was composed for that head. A pin that
    composes none merges bare, as the sync pass does. A gate that cannot say whether the tree composes raises, which
    `run` reads as no reading."""
    passed: dict[int, tuple[str, str | None]] = {}

    def gate(pr: int, head: str) -> Mapping[str, Any] | None:
        passed.pop(pr, None)
        composes, why = cadence.composes(root)
        if composes is None:
            raise RuntimeError(why or "whether the tree composes the squash could not be read")
        if not composes:
            got = cadence.check(root, pr, sync.GATE_TIMEOUT)
            if got is not None and got.get("verdict") == "pass":
                passed[pr] = (head, None)
            return got
        with tempfile.TemporaryDirectory(prefix="stage-merge-") as d:
            file = Path(d) / "gate"
            got = cadence.check(root, pr, sync.GATE_TIMEOUT, trailers=file)
            if got is not None and got.get("verdict") == "pass":
                passed[pr] = (head, file.read_text(encoding="utf-8"))  # a pass with no trailers raises: no reading
            return got

    def land(pr: int, head: str) -> str | None:
        got = passed.pop(pr, None)
        if got is None or got[0] != head:
            return "the gate has not passed this head"
        if got[1] is None:
            return sync.merge(root, pr, head)
        with tempfile.TemporaryDirectory(prefix="stage-merge-") as d:
            out = Path(d)
            (out / "gate").write_text(got[1], encoding="utf-8")
            if why := sync.compose(root, pr, out, merged_by=MERGED_BY):
                return why
            try:
                sha = (out / "sha").read_text(encoding="utf-8").strip()
                subject = (out / "subject").read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                return f"the composed squash could not be read: {e}"
            if sha != head:
                return f"the squash was composed for {sha[:12]}, not the head the gate passed"
            return sync.merge(root, pr, head, subject=subject, body_file=out / "body")

    return gate, land


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
        if not failed or not SESSION_ROWS.issuperset(failed):  # a person's row, or one no list sorts
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
