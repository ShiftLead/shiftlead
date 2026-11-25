"""`ao stage end` from a built-in seat's job session (design §4.9d *How each one runs*, §4.7, TD-2053).

A job's session holds its work order's reference (`board:<8 hex>`, `pr:<n>`), not an entry, and ends its job with
`work-pushed` or `other`. `work-pushed` is checked as a build stage's is — the branch pushed, its pull request open on
this repo at the worktree's head, its precheck green — except that no entry is archived, a job having none; and, for a
board answer, that the pull request closes the decided line (it moves the line's file into the board's archive); for a
pull request nobody holds, that it is the one the job was given. Accepted, the record stands in its team's flow as a
record of the stage that takes `other` entries would: it takes that stage's `work-pushed` destination, counted against
the flow's limits and its cap on moves as an entry's move is. A job goes only to that stage, to a review stage and to
`merge`; any other destination, a limit or the cap reached, and `other` send the job to the person: the home's plain
board line is written first (`line`), its id kept on the record as `person_line`, and the record waits.

`stage_end.call` routes a job's reference here. A job sent to `merge` is merged by the home (`stage_job_merge`). A
review stage's verdict on a job's pull request and `closed-unmerged` (TD-2165) are later work.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from sessionorc import workorders
from shiftlead import flow3, stage_job
from shiftlead.stage_end import PullRequest, Refused, destination
from shiftlead.stage_job_start import job_stage, lane_of
from shiftlead.stagerecord import StageStore, _now

OUTCOMES = ("work-pushed", flow3.OTHER)
BOARD_DIR = "docs/user_attention"
REF = re.compile(rf"(?:{re.escape(workorders.PREFIX)}[0-9a-f]{{8}}|{re.escape(workorders.PR_PREFIX)}[1-9]\d{{0,6}})")


def is_ref(ref: str) -> bool:
    """Whether `ref` is a job's work order reference, the one a job's session holds."""
    return bool(REF.fullmatch(ref or ""))


def key_of_ref(ref: str) -> str:
    """The job's key from its session's reference: `board:1a2b3c4d` → `board-1a2b3c4d`, `pr:12` → `pr-12`."""
    if not is_ref(ref):
        raise Refused(f"{ref} is no job's reference")
    if ref.startswith(workorders.PREFIX):
        return stage_job.key_of("board-answers", ref[len(workorders.PREFIX) :])
    return stage_job.key_of("unheld-pull-requests", ref[len(workorders.PR_PREFIX) :])


def closes_line(files: tuple[str, ...], item: str, board: str = BOARD_DIR) -> bool:
    """Whether a pull request's files close the board item `item` (its eight hex digits): its file, named
    `<date>-<id>.md`, lands under `archive/` of the board's directory `board` (a v3 board's, its stub's name less
    `.md`)."""
    under = PurePosixPath(board.rstrip("/")) / "archive"
    for f in files:
        p = PurePosixPath(f)
        if p.name.endswith(f"-{item}.md") and p.is_relative_to(under):
            return True
    return False


def board_dir(root: str | Path) -> str:
    """The board's directory in the repo at `root`, as `closes_line` reads it (`workorders.board_rel`)."""
    rel = PurePosixPath(workorders.board_rel(root).as_posix())
    return str(rel.with_suffix("") if rel.suffix == ".md" else rel)


def _stage(doc: Mapping[str, Any], key: str | None) -> dict[str, Any] | None:
    for st in doc.get("stages") or []:
        if isinstance(st, Mapping) and flow3.key_of(st.get("name")) == key:
            return dict(st)
    return None


def _check_pushed(record: Mapping[str, Any], facts: Any, board: str) -> PullRequest:
    """`work-pushed`'s fact for a job: a build stage's, no entry archived, and the job's own pull request."""
    seat, obj = str(record.get("seat")), str(record.get("object"))
    given = int(obj) if seat == "unheld-pull-requests" else None
    branch = record.get("branch") or facts.branch()
    if not branch and given is None:
        raise Refused("this worktree is on no branch: work on the job's branch and push it")
    pr = facts.pull_request(branch, record.get("pr") or given)
    if pr is None:
        raise Refused(f"the branch {branch} has no open pull request of this repo: open it, then end the job")
    if pr.fork or pr.state != "OPEN":
        raise Refused(f"pull request #{pr.number} is not open on this repo")
    if given is not None and pr.number != given:
        raise Refused(f"pull request #{pr.number} is not #{given}, the one this job was given")
    if facts.worktree_head() != pr.head:
        raise Refused(f"this worktree's head is not pull request #{pr.number}'s head: push your work")
    if not pr.precheck:
        raise Refused(f"pull request #{pr.number}'s precheck is not green at its head")
    if seat == "board-answers" and not closes_line(pr.files, obj, board):
        raise Refused(f"pull request #{pr.number} does not close the board line {obj}: close it on the branch")
    return pr


def _where(doc: Mapping[str, Any], here: str, to: str) -> str:
    """Where a job's move lands: `merge`, a review stage or the job's own stage; anything else is the person's."""
    if to == "merge" or to == here:
        return to
    after = _stage(doc, to)
    return to if after is not None and after.get("does") == "review" else "person"


def end_job(
    store: StageStore,
    ref: str,
    caller: str,
    outcome: str,
    reason: str,
    doc: Mapping[str, Any],
    facts: Any,
    line: Callable[[Mapping[str, Any], str], str | None],
    *,
    board: str = BOARD_DIR,
) -> dict[str, Any]:
    """Check a job session's `outcome` and write its move: `{entry, outcome, went, repeat}`, `entry` the job's
    reference, or `Refused` with nothing written. `line(record, reason)` writes the home's plain board line for a job
    sent to the person and returns its id; `board` is the board's directory (`board_dir`). The line is written before
    the record, so a record that then fails to be written leaves a line the retry writes again."""
    key = key_of_ref(ref)
    said = " ".join((reason or "").split())
    with store.locked():
        found = store.job(key)
        if found is None:
            raise Refused(f"{ref} has no job record")
        record = dict(found)
        last = (record.get("history") or [None])[-1]
        if record.get("holder") != caller or record.get("closed_at"):
            if last and last.get("by") == caller and last.get("outcome") == outcome:
                return {"entry": ref, "outcome": outcome, "went": last.get("to"), "repeat": True}
            raise Refused("the job is closed" if record.get("closed_at") else "this job is not yours")
        if outcome not in OUTCOMES:
            raise Refused(f"{outcome} is not an outcome of a job: its outcomes are {', '.join(OUTCOMES)}")
        here = job_stage(doc)
        stage = _stage(doc, here)
        if here is None or stage is None:
            raise Refused("the team's flow has no stage that takes other entries, so a job has no place in it")
        if record.get("stage") not in (None, here):
            raise Refused(
                f"{ref} stands at stage {record.get('stage')}, not the job's own: its session is not ended so"
            )
        if outcome != "work-pushed" and not said:
            raise Refused(f"{outcome} needs --reason")
        head: str | None = None
        went, why = "person", said
        if outcome == "work-pushed":
            pr = _check_pushed(record, facts, board)
            record["branch"], record["pr"], head = pr.branch, pr.number, pr.head
            where = destination(stage, outcome)
            went = _where(doc, here, str(where["to"]))
            if went == "person" and where["to"] != "person":
                why = f"the flow sends work-pushed from {here} to {where['to']}, a stage a job never goes to"
            elif went == "person":
                why = f"the flow sends work-pushed from {here} to the person"
            elif went != "merge":  # a move to merge is no stage's, so never counted, as an entry's is not
                count, counts = f"{here}:{outcome}", record.setdefault("counts", {})
                limit, cap = where.get("limit"), doc.get("max-moves", flow3.MAX_MOVES)
                if limit is not None and int(counts.get(count, 0)) >= int(limit):
                    went, why = "person", f"work-pushed from {here} reached its limit of {limit}"
                elif int(record.get("moves") or 0) >= int(cap):
                    went, why = "person", f"the job reached the flow's cap of {cap} moves"
                else:
                    counts[count] = int(counts.get(count, 0)) + 1
                    record["moves"] = int(record.get("moves") or 0) + 1
        record["history"] = [
            *(record.get("history") or []),
            {"from": here, "outcome": outcome, "reason": said, "by": caller, "to": went, "head": head, "at": _now()},
        ]
        record["holder"] = None
        record["stage"] = here if went in ("person", "merge") else went
        record["entered_at"] = _now()
        record["offers"] = 0
        if went == "merge":
            record["waits"] = "merging"
            record["merging"] = {"head": head, "stage": here, "outcome": outcome}
            store.put_job(record, f"{outcome}: merging")
        elif went == "person":
            try:
                got = line(record, why)
            except Exception as e:  # noqa: BLE001 — nothing is written, and the session tries again
                raise Refused(f"the home's board line could not be written ({e}): try again") from None
            if not got:
                raise Refused("the home's board line could not be written: try again")
            store.put_job(stage_job.to_person(record, got), f"{outcome}: to the person")
        else:
            store.put_job(record, f"{outcome}: to {went}")
    return {"entry": lane_of(record), "outcome": outcome, "went": went, "repeat": False}
