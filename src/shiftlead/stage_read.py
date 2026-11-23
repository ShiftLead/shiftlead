"""What the home reads of an entry's own text for a stage record (design §4.9c act 2, TD-2051).

`answer_on` reads the entry's Log, in file order and never by date: whether it carries the person's `decision` gate,
the label of the person's answer that last lifted it, and the mark of the question that answer lifted. Only a lift by
an answer counts: an override lifts the gate and answers nothing. A gate standing now means no answer is waiting, since
any lift in the Log was of an earlier gate.

`holder_on` reads what became of a record's holder from its session's record (§4.9c act 4). A holder the person or the
home stopped or holds is neither lost nor silent: one still there is `held`, and one whose end a Stop or a person made
is `stopped`. A claim released by `done` or `drop` is not a lapsed lease, so a live session that released its claim is
judged by the silent rule. The tick's wiring calls both; neither writes anything.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import NamedTuple

from sessionorc import ledgerboard, work
from sessionorc.agent_common import _parse, shells_live, subagents_live
from sessionorc.mail import LEASE_TTL
from sessionorc.models import Session
from shiftlead.stage_acts import Holder

_ASKED = re.compile(r"asked by the stage record: (\S+)")


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


def _instant(value: str | None) -> datetime | None:
    try:
        return _parse(str(value)) if value else None
    except ValueError:
        return None


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
    busy = bool(s.tool_open_at) or subagents_live(s, now) or shells_live(s, now)
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
