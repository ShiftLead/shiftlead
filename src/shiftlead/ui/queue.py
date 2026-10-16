"""The **Queue** page (design §4.5 screen 12, §4.5a *Queue page*; TD-748, built by TD-771).

One card per effort, ranked by the person: *where is TD-n*, and *is my org working what I think matters
first*. The cards are the home's `queue` reading (§4.4 *The Queue*, `sessionorc.queue`), drawn by the
partials the Repo page shares (`queue_card.html`, `queue_row.html`, TD-770). This module shapes that
reading for the page — the three groups, furthest through first, the window picker's counts and the
*other work* lines — and adds nothing the reading does not hold.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from .common import _age, _instant

# Recently completed's window picker (§4.5 screen 12, §4.5a *Queue page, Recently completed*): its
# words, in order, and how far back each reaches; *day* is drawn first (26–69 entries close in a day)
WINDOWS: dict[str, timedelta] = {
    "4h": timedelta(hours=4),
    "day": timedelta(days=1),
    "week": timedelta(days=7),
    "month": timedelta(days=30),
}
WINDOW_LABEL = {"4h": "4 h", "day": "Day", "week": "Week", "month": "Month"}
WINDOW_WORD = {
    "4h": "in the last 4 hours",
    "day": "in the last day",
    "week": "in the last week",
    "month": "in the last month",
}
DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _plain(text: Any) -> str:
    """A `Resolved:` line as the card opens to it: the ledger's emphasis and code marks dropped, its
    words kept (no Markdown is rendered on the page)."""
    return re.sub(r"\*\*|`|(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])", "", str(text or ""))


def _when(closed: Any, now: datetime) -> datetime | None:
    """When an entry closed: the closing commit's time, else its `Resolved:` date read as the end of that
    day (no later than now), so an entry resolved today is in *day* whatever the hour."""
    s = str(closed or "")
    if DATE_ONLY.fullmatch(s):
        end = _instant(s + "T23:59:59+00:00")
        return min(end, now) if end else None
    return _instant(s)


def _aged(closed: Any, at: datetime | None, now: datetime) -> str:
    """A close's age as the line draws it: *2h 5m* from a commit's time; a `Resolved:` date alone is no
    time of day, so it reads *today*, else its days (*3d*)."""
    if at is None:
        return ""
    s = str(closed or "")
    if DATE_ONLY.fullmatch(s):
        days = (now.date() - at.date()).days
        return "today" if days <= 0 else f"{days}d"
    return _age(at.isoformat(), now)


def _wins(closed: Any, at: datetime | None, now: datetime) -> list[str]:
    """The windows a close falls in; a `Resolved:` date alone, no time of day, is in none narrower than *day*."""
    dated = DATE_ONLY.fullmatch(str(closed or "")) is not None
    return [w for w, span in WINDOWS.items() if at is not None and now - at <= span and not (dated and w == "4h")]


def _show(q: str, one_repo: bool) -> str:
    """An entry as the page writes it: `TD-n` where the home reads one repo, else `<repo>#TD-n`."""
    return q.rpartition("#")[2] if one_repo else q


def _row(r: Mapping[str, Any], one_repo: bool) -> dict[str, Any]:
    """A card's row (or its top entry) as the partials take it: `show`, `also`, `anchor` (the id a
    `/queue#TD-n` finds, its open rows alone) and no `ext` — the Repo page's extras are not the Queue's."""
    q = str(r.get("qid") or "")
    return {
        **r,
        "priority": str(r.get("priority") or "").lower(),
        "show": _show(q, one_repo),
        "also": [_show(str(a), one_repo) for a in r.get("also_after") or []],
        "anchor": "" if r.get("archived") else _show(q, one_repo),
        "ext": None,
    }


def queue_view(queue: Mapping[str, Any] | None, now: datetime) -> dict[str, Any]:
    """The page's groups from the `queue` reading (§4.5 screen 12 *Groups*):

    - `completed`: `{lines, counts}` — one line per completed card (its age, the top entry's id, Priority
      badge and title, *n entries*, and the entries it opens to, each its `Resolved:` text and PR) and one
      per open card's archived row (*on TD-n's card*), newest first; each line's `wins` are the windows it
      falls in, and `counts` per window the entries the group lists (a completed card all its entries);
    - `in_progress` and `up_next`: the cards in the reading's order, each row shaped for the partials;
    - `other`: the *other work* lines, each hold that names no open entry, with its holder;
    - `upnext`: the whole Up next order, each card's id (a move's neighbours, §4.4 *A move lands*);
    - `n`: the header's counts — cards, in progress, up next, and those whose status is *needs you*."""
    q = queue or {}
    cards = [c for c in q.get("cards") or [] if isinstance(c, Mapping) and c.get("top")]
    repos = {str(r) for c in cards for r in c.get("repos") or ()}
    repos |= {
        str(e.get("qid") or "").partition("#")[0] for c in q.get("completed") or [] for e in c.get("entries") or ()
    }
    one_repo = len(repos - {""}) <= 1

    shaped: list[dict[str, Any]] = []
    for c in cards:
        top = _row(c["top"], one_repo)
        rows = [_row(r, one_repo) for r in c.get("rows") or []]
        shaped.append({**c, "top": top, "rows": rows, "ids": list(c.get("order") or [c["id"]])})
    in_progress = [c for c in shaped if c.get("group") == "in_progress"]
    up_next = [c for c in shaped if c.get("group") == "up_next"]

    lines: list[dict[str, Any]] = []
    for c in q.get("completed") or []:
        if not isinstance(c, Mapping):
            continue
        ents = [e for e in c.get("entries") or [] if isinstance(e, Mapping)]
        at = _when(c.get("at") or c.get("closed"), now)
        top = next((e for e in ents if e.get("qid") == c.get("id")), ents[0] if ents else {})
        lines.append(
            {
                "kind": "card",
                "at": at,
                "age": _aged(c.get("at") or c.get("closed"), at, now),
                "show": _show(str(c.get("id") or ""), one_repo),
                "priority": str(top.get("priority") or "").lower(),
                "title": str(top.get("title") or (c.get("titles") or {}).get(c.get("id")) or ""),
                "n": len(c.get("ids") or ents) or 1,
                # what it opens to: each entry's `Resolved:` and its PR; nothing to say, it does not open
                "entries": [
                    {
                        "show": _show(str(e.get("qid") or ""), one_repo),
                        "title": e.get("title") or "",
                        "pr": e.get("pr"),
                        "resolved": _plain(e.get("resolved")),
                    }
                    for e in ents
                    if e.get("resolved") or len(ents) > 1
                ],
                "wins": _wins(c.get("at") or c.get("closed"), at, now),
            }
        )
    for c in in_progress + up_next:
        for r in c["rows"]:
            if not r.get("archived"):
                continue
            at = _when(r.get("closed"), now)
            if not at or now - at > WINDOWS["month"]:
                continue
            lines.append(
                {
                    "kind": "row",
                    "at": at,
                    "age": _aged(r.get("closed"), at, now),
                    "show": r["show"],
                    "priority": r["priority"],
                    "title": r.get("title") or "",
                    "n": 1,
                    "on": c["top"]["show"],
                    "entries": [
                        {
                            "show": r["show"],
                            "title": r.get("title") or "",
                            "pr": r.get("pr"),
                            "resolved": _plain(r.get("resolved")),
                        }
                    ]
                    if r.get("resolved")
                    else [],
                    "wins": _wins(r.get("closed"), at, now),
                }
            )
    lines = [ln for ln in lines if ln["wins"]]
    lines.sort(key=lambda ln: ln["at"], reverse=True)
    counts = {w: sum(ln["n"] for ln in lines if w in ln["wins"]) for w in WINDOWS}

    other = []
    for o in q.get("other_work") or []:
        if not isinstance(o, Mapping):
            continue
        h = o.get("holder") or {}
        ref = str(o.get("ref") or "")
        other.append({"ref": ref, "pr": o.get("pr"), "holder": h if h.get("id") else None})

    return {
        "completed": {"lines": lines, "counts": counts},
        "in_progress": in_progress,
        "up_next": up_next,
        "other": other,
        "upnext": [str(c["id"]) for c in up_next],
        "n": {
            "cards": len(shaped),
            "in_progress": len(in_progress),
            "up_next": len(up_next),
            "needs_you": sum(1 for c in shaped if c.get("status") == "needs you"),
        },
        "one_repo": one_repo,
        "served": q.get("at") is not None or bool(cards),
    }
