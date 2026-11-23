"""Which open pull request is an entry's work (design §4.9e *Work in flight*, §4.9c *Ways in*, TD-2051).

The one function the Offer act, the seat for pull requests nobody holds (TD-2053) and the switch-over's check (TD-2071)
all call, so the three can never disagree. It reads the rows `sessionorc.reports` keeps of a repo's pull requests and
changes nothing.

The match is the **branch name** holding the entry's id as a whole token, whatever its case; the title is not read. A
fork's pull request, a filing pull request (the gate sweep's and a sync's among them, which only touch records) and a
branch holding two entries' ids are never an entry's work. Of several matches the newest is taken. Where that one is
a draft or is held by a live session the entry waits, offered to nobody.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from sessionorc import reports

_TOKEN = re.compile(r"(?<![a-z0-9])td-?(\d+)(?![a-z0-9])", re.IGNORECASE)

State = Literal["none", "take", "wait", "unread"]


@dataclass(frozen=True)
class EntryWork:
    """What an entry's open pull requests mean for its offer.

    `none`: no pull request is its work, so it is offered afresh. `take`: `pr` is its work, and its first record carries
    that branch and number. `wait`: `pr` is its work and is a draft or held by a live session, so it is offered to
    nobody while that lasts. `unread`: whether `pr` is a filing pull request is not known at its head yet, so nothing is
    decided on this reading.
    """

    state: State
    pr: Mapping[str, Any] | None = None
    why: str = ""


def branch_ids(branch: object) -> frozenset[str]:
    """The entry ids a branch name holds as whole tokens: `td2051-acts` and `TD-2051/acts` hold TD-2051, `td-205-1`
    holds TD-205 alone, and `xtd2051` and `td2051b` hold none."""
    return frozenset(f"TD-{m.group(1)}" for m in _TOKEN.finditer(branch)) if isinstance(branch, str) else frozenset()


def _filing(row: Mapping[str, Any]) -> bool | None:
    """Whether the row is a filing pull request's, as read at its current head; None where it was not read there."""
    head = row.get("head")
    if not head or row.get("filing_head") != head or not isinstance(row.get("filing"), bool):
        return None
    return row["filing"]


def _newest(row: Mapping[str, Any]) -> tuple[str, int]:
    return str(row.get("created") or ""), int(row["number"])


def entry_work(tid: str, prs: Iterable[Mapping[str, Any]], *, held: Collection[int] = ()) -> EntryWork:
    """What `tid`'s open pull requests mean for its offer. `prs` are the repo's rows and `held` the numbers of those a
    live session holds, which the caller reads with its own view of who is live (the switch-over's check passes the
    view with every session it will have ended taken as gone)."""
    matches = [
        row
        for row in prs
        if isinstance(row.get("number"), int)
        and row.get("state") == "open"
        and not row.get("fork")
        and not row.get("sync")
        and not reports.gate_head(row.get("branch"))  # the sweep's own: its files are never read for `filing`
        and branch_ids(row.get("branch")) == {tid}
        and _filing(row) is not True
    ]
    if not matches:
        return EntryWork("none")
    row = max(matches, key=_newest)
    number = row["number"]
    if _filing(row) is None:
        return EntryWork("unread", row, f"#{number}'s files have not been read at its head")
    if number in held:
        return EntryWork("wait", row, f"#{number} is held by a live session")
    if row.get("draft"):
        return EntryWork("wait", row, f"#{number} is a draft")
    return EntryWork("take", row)
