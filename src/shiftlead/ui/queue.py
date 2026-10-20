"""The **Queue** page (design §4.5 screen 12, §4.5a *Queue page*; TD-748, built by TD-771).

One card per effort, ranked by the person: *where is TD-n*, and *is my org working what I think matters
first*. The cards are the home's `queue` reading (§4.4 *The Queue*, `sessionorc.queue`), drawn by the
partials the Repo page shares (`queue_card.html`, `queue_row.html`, TD-770). This module shapes that
reading for the page — the three groups, furthest through first, the window picker's counts and the
*other work* lines — and adds nothing the reading does not hold.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sessionorc.queue import TD_REF, card_index  # noqa: F401 — the page's names for the home's
from sessionorc.queue import refs as _refs

from .common import _age, _instant, close_state, promote_reading

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
CONTEXT = re.compile(r"\bContext:\s*(.*?)(?=\s+(?:Due|Answers|Decided|Closed):|$)", re.S)
# the filter row (§4.5 screen 12 *Filters*, §4.5a *Queue page: filters, find*): the status toggles, and the
# kind pick's words in its order — the kinds of what needs the person on a card
FILTERS = {"needs-you": "Needs you", "steering": "Steering"}
# the kind pick (§4.5a *Queue page: filters, find*, TD-911): the two wants that need the person, and a card the
# person holds
KINDS = {
    "decide": "Decide",
    "do": "Do",
    "held-person": "held (person)",
}


def item_home(e: Mapping[str, Any], index: Mapping[str, tuple[str, str]] | None) -> dict[str, Any]:
    """Where an Inbox item is drawn (§4.5 screen 6 *Where a row is drawn*, screen 12 *What is attached to a
    card*): `{home, on_card, on_row, mentions}` — `queue` with the card and row its entry is on, for a question,
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
    lf: Mapping[str, Any] | None, ahead: Any, index: Mapping[str, tuple[str, str]] | None, hidden: Any = ()
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """*Later*'s rows split by where each is drawn (§4.5 screen 6 *Where a row is drawn*, TD-771; screen 12 *What
    is attached to a card*, TD-828): the ledger's rows (`lf`, `ledger_for_you`'s groups) and the board's lines
    not yet due — those the horizon draws (`ahead`) and those its mode folds (`hidden`), since the mode orders
    the Inbox, not a card — whose entry an open card holds leave the Inbox for their card. Answers the Inbox's
    `lf`, `ahead`, the rows the Queue draws and the `hidden` lines no card holds (which the Inbox's *not shown*
    fold draws and counts). Each row the Queue draws is tagged `home: queue` with its card and row and the
    renderer's section it is drawn with — `later` a ledger row, `coming` a board line with its due date — and
    lands in its card's *Needs you*, counted there and never in the top bar's number."""
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
    rest, unshown = [], []
    for lines, keep in ((ahead, rest), (hidden, unshown)):
        for e in lines or ():
            home = item_home(e, index)
            if home["home"] == "queue":
                moved.append({**e, **home, "later_section": "coming"})
            else:
                keep.append(e)
    return {"n": sum(len(g["rows"]) for g in groups), "groups": groups}, rest, moved, unshown


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


def _row(r: Mapping[str, Any], one_repo: bool, mentioned: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A card's row (or its top entry) as the partials take it: `show`, `also`, `anchor` (the id a
    `/queue#TD-n` finds, its open rows alone), no `ext` — the Repo page's extras are not the Queue's — and
    `mentioned`, the first words of each item that names it beside another row, one per item (`attach`). What is
    attached to it is the card's, in the card's wants, never the row's (§4.5 screen 12 *Three wants*)."""
    q = str(r.get("qid") or "")
    return {
        "mentioned": list(((mentioned or {}).get(q) or {}).values()),
        **r,
        "priority": str(r.get("priority") or "").lower(),
        "show": _show(q, one_repo),
        "also": [_show(str(a), one_repo) for a in r.get("also_after") or []],
        "anchor": "" if r.get("archived") else _show(q, one_repo),
        "ext": None,
    }


# the Inbox's sections a card gathers its items from, in the Inbox's order (§4.5 screen 12 *Three wants*)
CARD_SECTIONS = ("needs", "steering", "waiting", "answered", "fyi")
# a card's three wants (§4.5 screen 12 *Three wants*, TD-909, built by TD-911): Decide and Do drawn in the header,
# open and counted on the pill; Read under the rows, folded, its lines the Inbox's three it gathers
WANTS = {"decide": "Decide", "do": "Do"}
READ_LINES = {"answered": "answered for you", "waiting": "waiting on them", "fyi": "fyi"}


def want_of(e: Mapping[str, Any], sec: str) -> str:
    """An attached item's want (§4.5 screen 12 *Three wants*): `decide` — an `ask`, a `steer` running or
    paused, a board line but a `watch` or `fyi` one, a `decision (paul)` entry; `do` — an `Owner: paul` entry,
    a red PR nobody holds, and what else needs the person (a blocked outcome); `read` — what is answered,
    waits on others or is for reading; `held` — an entry the person holds, which is no want while held."""
    if sec in READ_LINES:
        return "read"
    row = e.get("row")
    if row == "ledger":
        return "held" if e.get("release") else ("do" if e.get("why") == "yours" else "decide")
    if row == "red_pr":
        return "do"
    if row == "board":
        return "read" if str(e.get("kind") or "").lower() in ("watch", "fyi") else "decide"
    if sec == "steering" or e.get("kind") in ("ask", "steer"):
        return "decide"
    return "do"


def attach(sections: Mapping[str, Any], drawn: Any, later: Any = ()) -> dict[str, Any]:
    """The Inbox's rows the Queue draws (`home: queue`, §4.5 screen 6 *Where a row is drawn*), by the card each
    is attached to and the card's section it is in (§4.5 screen 12 *What is attached to a card*, TD-828):
    `cards`, each card's `{section: [item]}`, every item `{section, id, html, kind, on_row}` with the row drawn
    by the Inbox's own renderer (`drawn(e, section)`), in the Inbox's order; and `mentioned`, on each row an item
    names beside its own, `{item id: its first words}` — one per item however often it is drawn, so the row's
    one phrase counts items (*mentioned in n items*, TD-915). The snoozed list is the Inbox's alone: no Snooze on the
    Queue. `later` is `split_later`'s rows, all under *Needs you* whatever their `Due:`: a ledger row the
    person's, drawn first, and a board line not yet due after the questions, drawn with its due date."""
    cards: dict[str, dict[str, list[Any]]] = {}
    mentioned: dict[str, dict[str, str]] = {}

    def put(e: Mapping[str, Any], sec: str, drawn_as: str, mid: Any, kind: str) -> None:
        want = want_of(e, sec)
        if want == "held":  # the held row, never the for-you row (§4.5a *Inbox row: held entry*)
            e = {**e, "kind": "ledger · held", "claimed": True, "answers": [], "default": ""}
        cards.setdefault(str(e.get("on_card") or ""), {}).setdefault(sec, []).append(
            {
                "section": sec,
                "id": str(mid or ""),
                "html": drawn({**e, "want": want}, drawn_as),  # its renderer's `card` mode reads the want
                "kind": kind,
                "want": want,
                "red": e.get("row") == "red_pr",
                "running": sec == "steering",
                "on_row": e["on_row"],
            }
        )

    for e in later or ():
        if e.get("later_section") == "later":
            put(e, "needs", "later", e.get("row_id"), _item_kind(e, "needs"))
    for sec in CARD_SECTIONS:
        for e in sections.get(sec) or ():
            if e.get("home") != "queue":
                continue
            put(e, sec, sec, e.get("id"), _item_kind(e, sec))
            words = " ".join(str(e.get("subject") or e.get("text") or "").split()[:8])
            for m in e.get("mentions") or ():
                mentioned.setdefault(m, {}).setdefault(str(e.get("id") or words), words)
        if sec == "needs":
            for e in later or ():
                if e.get("later_section") == "coming":
                    put(e, "needs", "coming", e.get("id"), _item_kind(e, "needs"))
    return {"cards": cards, "mentioned": mentioned}


def card_wants(got: Mapping[str, list[Any]] | None, top: str, one_repo: bool) -> dict[str, Any]:
    """A card's attached items as its three wants draw them (§4.5 screen 12 *Three wants*): `decide` and `do`,
    each item in the Inbox's order; `read`, `{line: [item]}` for each of `READ_LINES` with any; `held`, the
    entries the person holds, no want; and `n`, the counts — `decide`, `do` (the pill's, a red PR in it) and
    `read`. Each item carries `on` — the row it is about, written as the page writes ids, where that is not the
    top entry (*on TD-n*, a link to the row)."""
    out: dict[str, Any] = {"decide": [], "do": [], "read": {}, "held": []}
    for sec in CARD_SECTIONS:
        for m in (got or {}).get(sec) or ():
            m = {**m, "on": "" if m.get("on_row") == top else _show(str(m.get("on_row") or ""), one_repo)}
            want = m.get("want") or want_of({}, sec)
            if want == "read":  # a `watch` or `fyi` board line the Inbox counts is fyi on a card
                out["read"].setdefault(sec if sec in READ_LINES else "fyi", []).append(m)
            else:
                out[want].append(m)
    out["n"] = {
        "decide": len(out["decide"]),
        "do": len(out["do"]),
        "read": sum(len(v) for v in out["read"].values()),
    }
    return out


def _item_kind(e: Mapping[str, Any], sec: str) -> str:
    """The kind pick's word for an attached item (`KINDS`): its want where that is Decide or Do; '' for what
    waits on nobody (Read, a held entry)."""
    want = want_of(e, sec)
    return want if want in WANTS else ""


def _card_kinds(rows: list[Mapping[str, Any]], secs: Mapping[str, Any] | None = None) -> list[str]:
    """The kinds of what needs the person on a card (the kind pick, §4.5a *Queue page: filters, find*): its
    rows' own needs — *yours to do* a Do, *held until* a Decide, *held (person)* — and its attached items' wants."""
    got: set[str] = set()
    for r in rows:
        if r.get("archived"):
            continue
        if r.get("needs") == "owner":
            got.add("do")
        elif r.get("needs") == "decision":
            got.add("decide")
        if str(r.get("state") or "") == "held (person)":
            got.add("held-person")
    got |= {w for w in WANTS if (secs or {}).get(w)}
    # a running `steer` is Decide, and `steering` besides: what the Steering filter reads (§4.5 screen 12 *Filters*)
    steering = any(m.get("running") for m in (secs or {}).get("decide") or ())
    return [k for k in KINDS if k in got] + (["steering"] if steering else [])


def _find_text(rows: list[Mapping[str, Any]]) -> str:
    """What the find box matches on a card or a completed line: each id, written whole and bare, and each
    title, lower-cased."""
    bits: list[str] = []
    for r in rows:
        q = str(r.get("qid") or r.get("show") or "")
        bits += [q, *(x for ref in _refs(q) for x in (ref, ref.rpartition("#")[2])), str(r.get("title") or "")]
    return " ".join(bits).lower()


def _finds(w: str, text: str) -> bool:
    """A find word in a card's or line's find text: an id whole — `TD-7` never finds TD-70 or TD-77 — and a
    title's words as written, anywhere."""
    if re.fullmatch(r"(?:[\w.-]+#)?td-\d+", w):
        return any(t == w or t.endswith("#" + w) for t in text.split())
    return w in text


def _find_word(w: str) -> str:
    """A find word as `_find_text` writes it: lower-cased, an id with its number as the ledger writes it."""
    w = re.sub(r"(?i)\btd-(?=\d)", "TD-", w)
    refs = _refs(w) if TD_REF.fullmatch(w) else []
    return (refs[0] if refs else w).lower()


def same_td(a: Any, b: Any) -> bool:
    """Two ids one entry, by number where both are `TD-n` (`TD-9` and a card's `TD-009`), else as written."""
    a, b = str(a or ""), str(b or "")
    if re.fullmatch(r"TD-\d+", a, re.I) and re.fullmatch(r"TD-\d+", b, re.I):
        return int(a[3:]) == int(b[3:])
    return a == b


def card_session(card: Mapping[str, Any], fleet: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """Who a card's **Start session** meets (§4.5a *Queue card: Start session / Open session*, TD-912), one answer
    the button and `/api/ledger/start` both read: `start`, the reading's entry to start on; `own`, the person's
    own session (`unattended: false`) holding any of the card's open entries — the one holding `start`, else the
    first by id — whose Focus the press opens; `other`, the name of any other live session holding `start` while
    none of the person's does, when the button is absent and a press is refused. A session holds an entry by its
    claim, or by the name `td-<n>` in the entry's repo before the tick derives the claim (TD-678)."""
    start = str(card.get("start") or "")
    rows = [r for r in [card.get("top"), *(card.get("rows") or [])] if isinstance(r, Mapping) and not r.get("archived")]
    live = [s for s in fleet or () if s.get("state") not in ("exited", "closed") and s.get("repo")]

    def holders(q: str) -> list[Mapping[str, Any]]:
        repo, _, ref = q.partition("#")
        return [
            s
            for s in live
            if Path(str(s["repo"])).name == repo
            and (
                same_td(str(s.get("name") or "").upper(), ref)
                or any(
                    isinstance(p, Mapping) and same_td(p.get("ref"), ref) and p.get("status") == "claimed"
                    for p in s.get("progress") or ()
                )
            )
        ]

    def mine(ss: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        return sorted((s for s in ss if not s.get("unattended")), key=lambda s: str(s.get("id")))

    on_start = holders(start) if start else []
    own = mine(on_start) or mine(s for r in rows for s in holders(str(r.get("qid") or "")))
    other = on_start[0] if on_start and not own else {}
    return {
        "start": start,
        "own": str(own[0]["id"]) if own else "",
        "other": str(other.get("name") or other.get("id") or ""),
    }


def _mail_status(status: str, wants: Mapping[str, Any]) -> str:
    """The mail's part of a card's status (§4.4 *The card's status*: *needs you* > *steer* > the ledger's): a
    Decide or Do item — a question, a paused `steer`, a board line due or not, the person's ledger row, a red PR —
    but a running `steer`, which is Decide and leaves the status *steer* (§4.5 screen 12 *Three wants*); a held
    entry is no need."""
    items = [*(wants.get("decide") or ()), *(wants.get("do") or ())]
    if status == "needs you" or any(not m.get("running") for m in items):
        return "needs you"
    return "steer" if any(m.get("running") for m in items) else status


def card_edge(group: str, status: str, wants: Mapping[str, Any]) -> str:
    """A card's 4 px left edge (§4.5 screen 12 *A card*, TD-915), in this order: `needs` (amber) for any Decide or
    Do item — or a *needs you* status, the same need read from the ledger — else `waiting` (teal) on a Waiting
    card, else `working` (green) In progress, else `ended` (grey)."""
    n = wants.get("n") or {}
    if n.get("decide") or n.get("do") or status == "needs you":
        return "needs"
    return {"waiting": "waiting", "in_progress": "working"}.get(group, "ended")


def branch(r: Mapping[str, Any]) -> str:
    """A row's colour in the card's tree (§4.5 screen 12 *A card*, TD-915): `done` (green) an archived row,
    `needs` (amber) the person's — *yours to do*, *your decision*, *held (person)* — `waiting` (teal) one that
    waits — *waits until*, *waits on an event*, *after TD-n*, *settling* — else `open` (grey)."""
    state = str(r.get("state") or "")
    if r.get("archived"):
        return "done"
    if r.get("needs") or state == "held (person)":
        return "needs"
    if state.startswith(("waits ", "after ")) or state == "settling":
        return "waiting"
    return "open"


def _tree(rows: list[dict[str, Any]], top: str) -> list[dict[str, Any]]:
    """The rows as the tree draws them (TD-915): depth first from the top entry, each row's children under it
    in the reading's order (which is breadth first), so a row sits under its own parent; a row whose parent is
    not on the card keeps its place at the end. Each row gains `rails`, one colour per level down to its own —
    its ancestors' branches, then its own — so the 2 px rule down a level's left edge runs unbroken past the
    deeper rows under it."""
    kids: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        kids.setdefault(str(r.get("parent") or ""), []).append(r)
    out: list[dict[str, Any]] = []
    seen: set[int] = set()

    def walk(q: str, up: list[str]) -> None:
        for r in kids.get(q) or ():
            if id(r) in seen:
                continue
            seen.add(id(r))
            depth = max(int(r.get("depth") or 1), 1)
            r["rails"] = [*(up + ["open"] * depth)[: depth - 1], branch(r)]
            out.append(r)
            walk(str(r.get("qid") or ""), r["rails"])

    walk(top, [])
    for r in rows:
        if id(r) not in seen:
            seen.add(id(r))
            depth = max(int(r.get("depth") or 1), 1)
            r["rails"] = [*["open"] * (depth - 1), branch(r)]
            out.append(r)
            walk(str(r.get("qid") or ""), r["rails"])
    return out


def queue_view(
    queue: Mapping[str, Any] | None,
    now: datetime,
    mail: Mapping[str, Any] | None = None,
    promotes: Any = None,
    fleet: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """The page's groups from the `queue` reading (§4.5 screen 12 *Groups*):

    - `completed`: `{lines, counts}` — one line per completed card (its age, the top entry's id, Priority
      badge and title, *n entries*, and the entries it opens to, each its `Resolved:` text and PR) and one
      per open card's archived row (*on TD-n's card*), newest first; each line's `wins` are the windows it
      falls in, and `counts` per window the entries the group lists (a completed card all its entries);
    - `in_progress`, `waiting` and `up_next`: the cards in the reading's order, each row shaped for the
      partials, and `chips` on each where the home reads more than one repo: its `places` (a Waiting card's
      `would_be`, TD-918) are drawn each with its repo;
    - `other`: the *other work* lines, each hold that names no open entry, with its holder;
    - `upnext`: the whole Up next order, each card's id (a move's neighbours, §4.4 *A move lands*);
    - `n`: the header's counts — cards, in progress, waiting, up next, and those whose status is *needs you*.

    `mail` is what is attached to each card (`attach`), gathered into its `wants` (`card_wants`): Decide and Do
    drawn in the header, Read in the body, raising the card's status to *needs you* or *steer*. `promotes` is the `host`
    reading's: each completed line's `live` is its close's promote state, *not yet live* or *live* by the
    newest close it holds, "" where its repo promotes nothing or live is unknown (§4.5 screen 12, TD-904). `fleet`
    is the live records: each open card's `session` (`card_session`) is what its **Start session** reads (TD-912)."""
    fleet = list(fleet or ())
    q = queue or {}
    cards = [c for c in q.get("cards") or [] if isinstance(c, Mapping) and c.get("top")]
    repos = {str(r) for c in cards for r in c.get("repos") or ()}
    repos |= {
        str(e.get("qid") or "").partition("#")[0] for c in q.get("completed") or [] for e in c.get("entries") or ()
    }
    one_repo = len(repos - {""}) <= 1

    mentioned = (mail or {}).get("mentioned") or {}
    shaped: list[dict[str, Any]] = []
    for c in cards:
        top = _row(c["top"], one_repo, mentioned)
        rows = _tree([_row(r, one_repo, mentioned) for r in c.get("rows") or []], str(top.get("qid") or ""))
        wants = card_wants(((mail or {}).get("cards") or {}).get(str(c["id"])), str(top.get("qid") or ""), one_repo)
        status = _mail_status(str(c.get("status") or ""), wants)
        shaped.append(
            {
                **c,
                "status": status,
                "edge": card_edge(str(c.get("group") or ""), status, wants),
                "top": top,
                "rows": rows,
                "wants": wants,
                "ids": list(c.get("order") or [c["id"]]),
                # the number per repo, each with its chip, where the home reads more than one (TD-901)
                "chips": not one_repo,
                "kinds": _card_kinds([top, *rows], wants),
                "find": _find_text([top, *rows]),
                "session": card_session(c, fleet),
            }
        )
    in_progress = [c for c in shaped if c.get("group") == "in_progress"]
    waiting = [c for c in shaped if c.get("group") == "waiting"]
    up_next = [c for c in shaped if c.get("group") == "up_next"]

    readings: dict[str, Any] = {}

    def live(repo: str, sha: Any) -> str:
        if repo not in readings:
            readings[repo] = promote_reading(promotes, name=repo)
        return close_state(readings[repo], sha)

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
                "repo": str(c.get("id") or "").partition("#")[0],
                "find": _find_text([*ents, {"qid": c.get("id"), "title": top.get("title")}]),
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
                "live": live(str(c.get("id") or "").partition("#")[0], (ents[0] if ents else {}).get("sha")),
            }
        )
    for c in in_progress + waiting + up_next:
        for r in c["rows"]:
            if not r.get("archived"):
                continue
            at = _when(r.get("closed"), now)
            if not at or now - at > WINDOWS["month"]:
                continue
            lines.append(
                {
                    "kind": "row",
                    "repo": str(r.get("repo") or str(r.get("qid") or "").partition("#")[0]),
                    "find": _find_text([r]),
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
                    "live": live(str(r.get("repo") or str(r.get("qid") or "").partition("#")[0]), r.get("sha")),
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
        "waiting": waiting,
        "up_next": up_next,
        "other": other,
        "upnext": [str(c["id"]) for c in up_next],
        "n": {
            "cards": len(shaped),
            "in_progress": len(in_progress),
            "waiting": len(waiting),
            "up_next": len(up_next),
            "needs_you": sum(1 for c in shaped if c.get("status") == "needs you"),
            # the page header's *Decide n · Do n*: items, not cards, display only — in no top-bar or rail
            # number; a red PR is counted on its card's pill alone (§4.5 screen 12 *Three wants*)
            "decide": sum(c["wants"]["n"]["decide"] for c in shaped),
            "do": sum(sum(1 for m in c["wants"]["do"] if not m.get("red")) for c in shaped),
        },
        "one_repo": one_repo,
        "repos": sorted(repos - {""}),
        "served": q.get("at") is not None or bool(cards),
    }


def queue_window(params: Any) -> str:
    """The window whose completed lines the page sends (§4.5 *Page loads*: *only what is shown*, TD-882):
    the URL's `win`, else *day*; an unknown one reads as *day*."""
    w = str(params.get("win") or "")
    return w if w in WINDOWS else "day"


def send_window(view: dict[str, Any], win: str) -> dict[str, Any]:
    """Recently completed's lines trimmed to those in `win` (`completed.sent`), and the window named
    (`completed.loaded`), for the page to draw; `lines`, its counts and its shares stay whole, so every
    window's button keeps its count. The windows nest, so the lines of a wider window hold a narrower's,
    and the browser asks for a wider one by `part=1&win=` once (TD-882)."""
    done = view.setdefault("completed", {"lines": [], "counts": {}})
    done["sent"] = [ln for ln in done.get("lines") or () if win in ln["wins"]]
    done["loaded"] = win
    return view


def queue_picks(params: Any) -> dict[str, Any]:
    """The filter row's picks from the URL (§4.5a *Queue page: filters, find*): `filter` (*All* when absent,
    `needs-you`, `steering`), `team`, `repo` and `kind` each a list, comma-separated or repeated, and
    `find`. An unknown filter or kind is dropped, so a stale link reads as *All*."""

    def many(key: str) -> list[str]:
        raw = params.getlist(key) if hasattr(params, "getlist") else [params.get(key) or ""]
        out: list[str] = []
        for v in raw:
            out += [w.strip() for w in str(v or "").split(",") if w.strip() and w.strip() not in out]
        return out

    f = str(params.get("filter") or "")
    return {
        "filter": f if f in FILTERS else "",
        "team": many("team"),
        "repo": many("repo"),
        "kind": [k for k in many("kind") if k in KINDS],
        "find": " ".join(str(params.get("find") or "").split()),
    }


def picks_query(picks: Mapping[str, Any], **change: Any) -> str:
    """The page's address with `change` applied to `picks` — a toggle's link: a list value is toggled in its
    list, `filter` replaced (its own value again is *All*, as is `filter=""`), `find` set."""
    p = {k: (list(v) if isinstance(v, list) else v) for k, v in picks.items()}
    for k, v in change.items():
        if k in ("team", "repo", "kind"):
            p[k] = [x for x in p.get(k) or [] if x != v] if v in (p.get(k) or []) else [*(p.get(k) or []), v]
        elif k == "filter":
            p[k] = "" if p.get(k) == v else v
        else:
            p[k] = v
    parts = [f"filter={p['filter']}"] if p.get("filter") else []
    parts += [f"{k}={quote(','.join(p[k]))}" for k in ("team", "repo", "kind") if p.get(k)]
    if p.get("find"):
        parts.append(f"find={quote(p['find'])}")
    return "/queue" + ("?" + "&".join(parts) if parts else "")


def apply_picks(view: dict[str, Any], picks: Mapping[str, Any], teams: Mapping[str, str]) -> dict[str, Any]:
    """Mark what the picks hide (`off`), never drop it: a move's neighbours are the whole Up next order,
    whatever a filter hides (§4.4 *A move lands*). A card passes when its status fits `filter` (*needs you*;
    *steer*, or a steering item on it), one of its repos is a picked team's (`teams`: name → repo) or a
    picked repo, one of its kinds is picked, and every word of `find` is in its ids and titles. A completed
    line passes by the repo and find picks, and by none while a status or kind is picked: nothing on it
    needs the person. `find_miss` is an id the find names that no open card holds, with the Repo page's
    address for it in the archive (one per repo where the id names none)."""
    repos: set[str] = set()
    if picks.get("team"):
        repos = {teams.get(t, "") for t in picks["team"]} - {""} or {"\0"}  # a team with no repo holds no card
    if picks.get("repo"):
        repos = (repos & set(picks["repo"])) if picks.get("team") else set(picks["repo"])
        repos = repos or {"\0"}
    words = [_find_word(w) for w in str(picks.get("find") or "").split()]
    kinds = set(picks.get("kind") or ())

    def by_repo_find(card_repos: Any, text: str) -> bool:
        if repos and not repos & set(card_repos or ()):
            return False
        return all(_finds(w, text) for w in words)

    cards = [*(view.get("in_progress") or ()), *(view.get("waiting") or ()), *(view.get("up_next") or ())]
    for c in cards:
        ok = by_repo_find(c.get("repos"), str(c.get("find") or ""))
        if picks.get("filter") == "needs-you":
            ok = ok and c.get("status") == "needs you"
        elif picks.get("filter") == "steering":
            ok = ok and (c.get("status") == "steer" or "steering" in (c.get("kinds") or ()))
        if kinds:
            ok = ok and bool(kinds & set(c.get("kinds") or ()))
        c["off"] = not ok
    status_pick = bool(picks.get("filter") or kinds)
    for ln in (view.get("completed") or {}).get("lines") or ():
        ln["off"] = status_pick or not by_repo_find([ln.get("repo")], str(ln.get("find") or ""))
    for o in view.get("other") or ():
        o["off"] = status_pick or bool(repos) or bool(words)
    view["find_miss"] = None
    ref = next(iter(_refs(re.sub(r"(?i)\btd-(?=\d)", "TD-", str(picks.get("find") or "")))), "")
    if ref:
        held = {x for c in cards for r in [c.get("top") or {}, *(c.get("rows") or ())] if not r.get("archived")
                for q in _refs(r.get("qid")) for x in (q, q.rpartition("#")[2])}  # fmt: skip
        repo, _, tid = ref.rpartition("#")
        if ref not in held:
            where = [repo] if repo else list(view.get("repos") or ())
            view["find_miss"] = {"id": tid, "repos": [{"name": r, "url": f"/repo/{quote(r)}#{tid}"} for r in where]}
    view["picks"] = dict(picks)
    view["shown"] = sum(1 for c in cards if not c["off"])
    # each group's share while a pick or a find is on (§4.5 screen 12 *Groups*: *Up next (4 of 28)*)
    done = (view.get("completed") or {}).get("lines") or ()
    view["shown_in"] = {
        "in_progress": sum(1 for c in view.get("in_progress") or () if not c["off"]),
        "waiting": sum(1 for c in view.get("waiting") or () if not c["off"]),
        "up_next": sum(1 for c in view.get("up_next") or () if not c["off"]),
        "completed": {w: sum(ln["n"] for ln in done if w in ln["wins"] and not ln["off"]) for w in WINDOWS},
    }
    view["filtered"] = bool(picks.get("filter") or picks.get("team") or picks.get("repo") or kinds or words)
    return view
