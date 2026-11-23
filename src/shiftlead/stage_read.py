"""What the home reads of an entry's own text for a stage record (design §4.9c act 2, TD-2051).

`answer_on` reads the entry's Log, in file order and never by date: whether it carries the person's `decision` gate,
the label of the person's answer that last lifted it, and the mark of the question that answer lifted. Only a lift by
an answer counts: an override lifts the gate and answers nothing. A gate standing now means no answer is waiting, since
any lift in the Log was of an earlier gate. It reads and writes nothing else; the tick's wiring calls it.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from sessionorc import ledgerboard

_ASKED = re.compile(r"asked by the stage record: (\S+)")


class EntryAnswer(NamedTuple):
    gate: bool
    lifted: str | None
    lifted_for: str | None


def answer_on(text: str, person: str) -> EntryAnswer:
    """`Reading.gate`, `.lifted` and `.lifted_for` from the entry's `text`, for the gate `decision (<person>)`."""
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
