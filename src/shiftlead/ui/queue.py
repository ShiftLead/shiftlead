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
# an entry named in a mail item, a board line's `Context:` or a PR's title: `TD-n`, or `<repo>#TD-n`
TD_REF = re.compile(r"(?<![\w-])(?:([\w.-]+)#)?TD-(\d+)\b")
CONTEXT = re.compile(r"\bContext:\s*(.*?)(?=\s+(?:Due|Answers|Decided|Closed):|$)", re.S)


def card_index(queue: Mapping[str, Any] | None) -> dict[str, tuple[str, str]]:
    """The open cards' entries (§4.5 screen 6 *Where a row is drawn*): each `<repo>#TD-n` a card holds —
    its top entry and every row, an open card's archived rows among them — to `(card id, row qid)`, and
    the bare `TD-n` too where one repo alone holds it. An entry on a completed card, or on none, is in
    no card: the item that names it stays in the Inbox."""
    out: dict[str, tuple[str, str]] = {}
    bare: dict[str, set[str]] = {}
    for c in (queue or {}).get("cards") or []:
        if not isinstance(c, Mapping) or not c.get("top"):
            continue
        for r in [c["top"], *(c.get("rows") or [])]:
            q = str(r.get("qid") or "")
            refs = _refs(q)
            if "#" not in q or not refs:
                continue
            out.setdefault(refs[0], (str(c["id"]), q))
            bare.setdefault(refs[0].partition("#")[2], set()).add(refs[0])
    for tid, qs in bare.items():
        if len(qs) == 1:
            out[tid] = out[next(iter(qs))]
    return out


def _refs(text: Any) -> list[str]:
    """The entries a text names, in order, each once: `TD-n` with its number as the ledger writes it."""
    seen: list[str] = []
    for repo, n in TD_REF.findall(str(text or "")):
        ref = f"{repo}#TD-{int(n):03d}" if repo else f"TD-{int(n):03d}"
        if ref not in seen:
            seen.append(ref)
    return seen


def item_home(e: Mapping[str, Any], index: Mapping[str, tuple[str, str]] | None) -> dict[str, Any]:
    """Where an Inbox item is drawn (§4.5 screen 6 *Where a row is drawn*, screen 12 *What is attached to a
    row*): `{home, on_card, on_row, mentions}` — `queue` with the card and row its entry is on, for a question,
    steer or note whose `about` names an entry an open card holds (else the first `TD-n` of its subject
    and text, the others its mentions), a board line whose `Context:` names one, and a red PR whose title
    or branch names one; `inbox` for the rest — a state row, a promote or team-start row, mail about no
    entry, an entry on a completed card or found nowhere."""
    inbox = {"home": "inbox", "on_card": "", "on_row": "", "mentions": []}
    if not index:
        return inbox
    kind = e.get("row")
    if kind == "board":
        m = CONTEXT.search(str(e.get("text") or ""))
        refs = _refs(m.group(1)) if m else []
    elif kind == "red_pr":
        refs = _refs(f"{e.get('branch') or ''} {e.get('title') or ''}")
    elif kind and not e.get("handed_row"):
        return inbox  # a state row, an alarm, a promote, a team start, the trail: no entry's
    else:
        about = _refs(e.get("about"))
        refs = about or _refs(f"{e.get('subject') or ''} {e.get('text') or ''}")
        if about:
            refs += [r for r in _refs(f"{e.get('subject') or ''} {e.get('text') or ''}") if r not in about]
    if not refs or refs[0] not in index:
        return inbox
    card, row = index[refs[0]]
    mentions = [index[r][1] for r in refs[1:] if r in index and index[r][1] != row]
    return {"home": "queue", "on_card": card, "on_row": row, "mentions": list(dict.fromkeys(mentions))}


def ledger_home(e: Mapping[str, Any], index: Mapping[str, tuple[str, str]] | None) -> dict[str, Any]:
    """Where a ledger row of the Inbox's (`ledger_for_you`'s, §4.5 screen 6 *The ledger's entries that wait on
    you*) is drawn: on the card that holds its entry, `<repo>#TD-n`, as its block of what needs the person
    (screen 12, TD-771); in *Later* where no open card holds it — a home that serves no Queue, an entry found
    nowhere — so nothing is lost."""
    refs = _refs(f"{e.get('name') or ''}#{e.get('id') or ''}")
    if not index or not refs or refs[0] not in index:
        return {"home": "inbox", "on_card": "", "on_row": "", "mentions": []}
    card, row = index[refs[0]]
    return {"home": "queue", "on_card": card, "on_row": row, "mentions": []}


def split_later(
    lf: Mapping[str, Any] | None, ahead: Any, index: Mapping[str, tuple[str, str]] | None
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """*Later*'s rows split by where each is drawn (§4.5 screen 6 *Where a row is drawn*, TD-771): the ledger's
    rows (`lf`, `ledger_for_you`'s groups) and the board's lines not yet due (`ahead`) whose entry an open card
    holds leave the Inbox for their card. Answers the Inbox's `lf` and `ahead` and the rows the Queue draws,
    each tagged `home: queue` with its card and row and its section — `later` a ledger row, `coming` a board
    line, which is drawn with its due date and counted nowhere, as the board's horizon says."""
    groups, moved = [], []
    for g in (lf or {}).get("groups") or []:
        keep = []
        for e in g.get("rows") or []:
            home = ledger_home(e, index)
            if home["home"] == "queue":
                moved.append({**e, **home, "later_section": "later"})
            else:
                keep.append(e)
        if keep:
            groups.append({**g, "rows": keep})
    rest = []
    for e in ahead or ():
        home = item_home(e, index)
        if home["home"] == "queue":
            moved.append({**e, **home, "later_section": "coming"})
        else:
            rest.append(e)
    return {"n": sum(len(g["rows"]) for g in groups), "groups": groups}, rest, moved


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


def _row(r: Mapping[str, Any], one_repo: bool, mail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A card's row (or its top entry) as the partials take it: `show`, `also`, `anchor` (the id a
    `/queue#TD-n` finds, its open rows alone), no `ext` — the Repo page's extras are not the Queue's — and
    what is attached to it (`attach`): `mail`, the Inbox items drawn under it, and `mentioned`, the first
    words of each item that names it beside another row."""
    q = str(r.get("qid") or "")
    got = (mail or {}).get(q) or {}
    return {
        "mail": list(got.get("items") or ()),
        "mentioned": list(got.get("mentioned") or ()),
        **r,
        "priority": str(r.get("priority") or "").lower(),
        "show": _show(q, one_repo),
        "also": [_show(str(a), one_repo) for a in r.get("also_after") or []],
        "anchor": "" if r.get("archived") else _show(q, one_repo),
        "ext": None,
    }


def attach(sections: Mapping[str, Any], drawn: Any, later: Any = ()) -> dict[str, dict[str, list[Any]]]:
    """The Inbox's rows the Queue draws (`home: queue`, §4.5 screen 6 *Where a row is drawn*), by the row
    each is attached to (§4.5 screen 12 *What is attached to a row*): `items`, each `{section, id, html}`
    with the row drawn by the Inbox's own renderer (`drawn(e, section)`), in the Inbox's order — what
    needs the person first — and `mentioned`, a quiet line's words on each row an item names beside its own.
    The snoozed list is the Inbox's alone: no Snooze on the Queue. `later` is `split_later`'s rows: a ledger
    row is the row's own block of what needs the person and is drawn first; a board line not yet due after
    the questions."""
    out: dict[str, dict[str, list[Any]]] = {}
    for e in later or ():
        if e.get("later_section") == "later":
            out.setdefault(e["on_row"], {"items": [], "mentioned": []})["items"].append(
                {"section": "later", "id": str(e.get("row_id") or ""), "html": drawn(e, "later")}
            )
    for sec in ("needs", "steering", "coming", "waiting", "answered", "fyi"):
        if sec == "coming":
            for e in later or ():
                if e.get("later_section") == "coming":
                    out.setdefault(e["on_row"], {"items": [], "mentioned": []})["items"].append(
                        {"section": "coming", "id": str(e.get("id") or ""), "html": drawn(e, "coming")}
                    )
            continue
        for e in sections.get(sec) or ():
            if e.get("home") != "queue":
                continue
            out.setdefault(e["on_row"], {"items": [], "mentioned": []})["items"].append(
                {"section": sec, "id": str(e.get("id") or ""), "html": drawn(e, sec)}
            )
            words = " ".join(str(e.get("subject") or e.get("text") or "").split()[:8])
            for m in e.get("mentions") or ():
                out.setdefault(m, {"items": [], "mentioned": []})["mentioned"].append(words)
    return out


def _mail_status(status: str, rows: list[Mapping[str, Any]]) -> str:
    """The mail's part of a card's status (§4.4 *The card's status*: *needs you* > *steer* > the ledger's):
    an attached item that needs the person, else an attached running `steer`."""
    secs = {m["section"] for r in rows for m in r.get("mail") or ()}
    if status == "needs you" or "needs" in secs:
        return "needs you"
    return "steer" if "steering" in secs else status


def queue_view(queue: Mapping[str, Any] | None, now: datetime, mail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The page's groups from the `queue` reading (§4.5 screen 12 *Groups*):

    - `completed`: `{lines, counts}` — one line per completed card (its age, the top entry's id, Priority
      badge and title, *n entries*, and the entries it opens to, each its `Resolved:` text and PR) and one
      per open card's archived row (*on TD-n's card*), newest first; each line's `wins` are the windows it
      falls in, and `counts` per window the entries the group lists (a completed card all its entries);
    - `in_progress` and `up_next`: the cards in the reading's order, each row shaped for the partials;
    - `other`: the *other work* lines, each hold that names no open entry, with its holder;
    - `upnext`: the whole Up next order, each card's id (a move's neighbours, §4.4 *A move lands*);
    - `n`: the header's counts — cards, in progress, up next, and those whose status is *needs you*.

    `mail` is what is attached to each row (`attach`): drawn under it, the top entry's in the header, and
    raising the card's status to *needs you* or *steer*."""
    q = queue or {}
    cards = [c for c in q.get("cards") or [] if isinstance(c, Mapping) and c.get("top")]
    repos = {str(r) for c in cards for r in c.get("repos") or ()}
    repos |= {
        str(e.get("qid") or "").partition("#")[0] for c in q.get("completed") or [] for e in c.get("entries") or ()
    }
    one_repo = len(repos - {""}) <= 1

    shaped: list[dict[str, Any]] = []
    for c in cards:
        top = _row(c["top"], one_repo, mail)
        rows = [_row(r, one_repo, mail) for r in c.get("rows") or []]
        status = _mail_status(str(c.get("status") or ""), [top, *rows])
        shaped.append({**c, "status": status, "top": top, "rows": rows, "ids": list(c.get("order") or [c["id"]])})
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
