"""`ao stage end` from a built-in seat's job session (design §4.9d *How each one runs*, §4.7, TD-2053).

A job's session holds its work order's reference (`board:<8 hex>`, `pr:<n>`), not an entry, and ends its job with
`work-pushed` or `other`, and a pull request's job also with `closed-unmerged` (TD-2165): a reason given and the pull
request the job was given read on the forge as closed and not merged, it closes the record as Reconcile closes one whose
object is gone; from the session the record last named, after Reconcile closed it, it is answered as a repeat, *the
job is closed*. `work-pushed` is checked as a build stage's is — the branch pushed, its pull request open on
this repo at the worktree's head, its precheck green — except that no entry is archived, a job having none; and, for a
board answer, that the pull request closes the decided line (it moves the line's file into the board's archive); for a
pull request nobody holds, that it is the one the job was given. Accepted, the record stands in its team's flow as a
record of the stage that takes `other` entries would: it takes that stage's `work-pushed` destination, counted against
the flow's limits and its cap on moves as an entry's move is. A job goes only to that stage, to a review stage and to
`merge`; any other destination, a limit or the cap reached, and `other` send the job to the person: the home's plain
board line is written first (`line`), its id kept on the record as `person_line`, and the record waits.

A record the flow sent to one of its review stages is ended by that stage's session, which holds the same reference:
its outcomes are the review stage's (`ship`, `changes-wanted`, `other`), checked as an entry's verdict is (`ship` on
the head the session read being the pull request's head now) and posted as the `cadence-review:` comment the gate's
review row reads; its rows carry no `run` and no `findings` (§4.9c *What a run records*). Its move goes where the
review stage sends that outcome, by the same rule: back to the job's stage (a fresh job session, told the review's
reason), to another review stage or to `merge`, counted as any move; anything else goes to the person.

`stage_end.call` routes a job's reference here. A job sent to `merge` is merged by the home (`stage_job_merge`).
The tick offers a review stage's session on a job (`stage_job.choose`, `stage_job_start.review_launch`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from sessionorc import workorders
from shiftlead import flow3, stage_job
from shiftlead.stage_end import (
    CLOSED_UNMERGED,
    NEEDS_NO_REASON,
    PR_JOB_ALONE,
    PullRequest,
    Refused,
    _check_read,
    _review_body,
    destination,
)
from shiftlead.stage_job_start import job_stage, lane_of
from shiftlead.stagerecord import StageStore, _now

OUTCOMES = ("work-pushed", flow3.OTHER)
PR_OUTCOMES = ("work-pushed", CLOSED_UNMERGED, flow3.OTHER)  # a pull request's job's (§4.9d)
CLOSED = "closed"  # where `closed-unmerged` takes a job: its record closed
REVIEW_OUTCOMES = (*flow3.OUTCOMES["review"], flow3.OTHER)
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


def _counted(record: dict[str, Any], doc: Mapping[str, Any], at: str, outcome: str, where: Mapping[str, Any]) -> str:
    """Count a move from `at` to a stage, as an entry's is: the reason it goes to the person instead, or `""`."""
    count, counts = f"{at}:{outcome}", record.setdefault("counts", {})
    limit, cap = where.get("limit"), doc.get("max-moves", flow3.MAX_MOVES)
    if limit is not None and int(counts.get(count, 0)) >= int(limit):
        return f"{outcome} from {at} reached its limit of {limit}"
    if int(record.get("moves") or 0) >= int(cap):
        return f"the job reached the flow's cap of {cap} moves"
    counts[count] = int(counts.get(count, 0)) + 1
    record["moves"] = int(record.get("moves") or 0) + 1
    return ""


def _close_unmerged(
    store: StageStore, record: dict[str, Any], ref: str, caller: str, at: str, said: str, facts: Any
) -> dict[str, Any]:
    """`closed-unmerged`'s fact, read on the forge: the pull request the job was given is closed and not merged. The
    record then closes as Reconcile closes one whose object is gone (`stage_job.closed`), its move in the history."""
    number = int(record.get("pr") or str(record.get("object")))
    pr = facts.pull_request(None, number)
    if pr is None:
        raise Refused(f"pull request #{number} could not be read on the forge: try again")
    if pr.state != "CLOSED":
        state = "merged" if pr.state == "MERGED" else "still open" if pr.state == "OPEN" else pr.state.lower()
        raise Refused(f"pull request #{number} is {state}: {CLOSED_UNMERGED} ends a job whose pull request was closed")
    step = {"from": at, "outcome": CLOSED_UNMERGED, "reason": said, "by": caller, "to": CLOSED, "head": pr.head}
    record["history"] = [*(record.get("history") or []), {**step, "at": _now()}]
    store.put_job(stage_job.closed(record), f"{CLOSED_UNMERGED}: closed")
    return {"entry": ref, "outcome": CLOSED_UNMERGED, "went": CLOSED, "repeat": False}


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
    if outcome == CLOSED_UNMERGED and not ref.startswith(workorders.PR_PREFIX):
        raise Refused(PR_JOB_ALONE)
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
            if outcome == CLOSED_UNMERGED and record.get("closed_at") and record.get("closed_holder") == caller:
                return {"entry": ref, "outcome": outcome, "went": CLOSED, "repeat": True, "said": "the job is closed"}
            raise Refused("the job is closed" if record.get("closed_at") else "this job is not yours")
        here = job_stage(doc)
        stage = _stage(doc, here)
        if here is None or stage is None:
            raise Refused("the team's flow has no stage that takes other entries, so a job has no place in it")
        at = here if record.get("stage") in (None, here) else str(record.get("stage"))
        if at != here:  # a review stage's session on the job's pull request
            stage = _stage(doc, at)
            if stage is None or stage.get("does") != "review":
                raise Refused(f"{ref} stands at stage {at}, which is no review stage of the team's flow")
            if outcome not in REVIEW_OUTCOMES:
                listed = ", ".join(REVIEW_OUTCOMES)
                raise Refused(f"{outcome} is not an outcome of a review stage: its outcomes are {listed}")
        elif outcome not in (taken := PR_OUTCOMES if ref.startswith(workorders.PR_PREFIX) else OUTCOMES):
            raise Refused(f"{outcome} is not an outcome of a job: its outcomes are {', '.join(taken)}")
        if outcome not in NEEDS_NO_REASON and not said:
            raise Refused(f"{outcome} needs --reason")
        if outcome == CLOSED_UNMERGED:
            return _close_unmerged(store, record, ref, caller, at, said, facts)
        head: str | None = None
        went, why = "person", said
        if outcome == "work-pushed":
            pr = _check_pushed(record, facts, board)
            record["branch"], record["pr"], head = pr.branch, pr.number, pr.head
        elif outcome in ("ship", "changes-wanted"):
            pr, head = _check_read(record, facts, ship=outcome == "ship")
            verdict = "SHIP" if outcome == "ship" else "BLOCK"
            facts.post_review(pr.number, _review_body(stage, caller, verdict, head, pr.files, said))
            record.setdefault("verdicts", {})[at] = {"head": head, "stage": at, "outcome": outcome}
        if outcome != flow3.OTHER:
            where = destination(stage, outcome)
            went = _where(doc, here, str(where["to"]))
            if went == "person" and where["to"] != "person":
                why = f"the flow sends {outcome} from {at} to {where['to']}, a stage a job never goes to"
            elif went == "person":
                why = f"the flow sends {outcome} from {at} to the person"
            elif went != "merge":  # a move to merge is no stage's, so never counted, as an entry's is not
                why = _counted(record, doc, at, outcome, where)
                went = "person" if why else went
        record["history"] = [
            *(record.get("history") or []),
            {"from": at, "outcome": outcome, "reason": said, "by": caller, "to": went, "head": head, "at": _now()},
        ]
        record["holder"] = None
        record["stage"] = at if went in ("person", "merge") else went
        record["entered_at"] = _now()
        record["offers"] = 0
        if went == "merge":
            record["waits"] = "merging"
            record["merging"] = {"head": head, "stage": at, "outcome": outcome}
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
