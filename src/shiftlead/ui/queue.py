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

from sessionorc.queue import TD_REF, card_entries, card_index, qid  # noqa: F401 — the page's names for the home's
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
# the filter row's one status pick (§4.5 screen 12 *Filters*, §4.5a *Queue page: filters, find*): the
# **Needs you** switch, beside the team chips and the find box (TD-1287)
FILTERS = {"needs-you": "Needs you"}


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
    """A card's row (or its top entry) as the partials take it: `show`, `afters` (its `after`, TD-1130),
    `anchor` (the id a `/queue#TD-n` finds, its open rows alone), no `ext` — the Repo page's extras are not the
    Queue's — and `mentioned`, the first words of each item that names it beside another row, one per item
    (`attach`). What is attached to it is the card's, in the card's wants, never the row's (§4.5 screen 12
    *Three wants*)."""
    q = str(r.get("qid") or "")
    return {
        "mentioned": list(((mentioned or {}).get(q) or {}).values()),
        **r,
        "priority": str(r.get("priority") or "").lower(),
        "show": _show(q, one_repo),
        "afters": [_show(str(a), one_repo) for a in r.get("after") or []],
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
    paused, a `decide` or `look` board line, a `decision (paul)` entry; `do` — an `act` board line (TD-1066: Done
    its answer), an `Owner: paul` entry, a red PR nobody holds, and what else needs the person (a blocked
    outcome); `read` — what is answered,
    waits on others or is for reading; `held` — an entry the person holds, which is no want while held. A fifth,
    `with_you` — the person's entry their own session holds, no want either (TD-1281) — is `attach`'s, read from
    the card, never from the row."""
    if sec in READ_LINES:
        return "read"
    row = e.get("row")
    if row == "ledger":
        return "held" if e.get("release") else ("do" if e.get("why") == "yours" else "decide")
    if row == "red_pr":
        return "do"
    if row == "board":
        kind = str(e.get("kind") or "").lower()
        return "read" if kind in ("watch", "fyi") else ("do" if kind == "act" else "decide")
    if sec == "steering" or e.get("kind") in ("ask", "steer"):
        return "decide"
    return "do"


def item_ref(e: Mapping[str, Any]) -> str:
    """An attached item's id as **Start session** names it (§4.5 screen 12 *Started from an item*, TD-1246): a board
    line `board:<key>`, a mail item its `m-…`, a ledger row `<repo>#TD-n`, a red PR `<repo>#<n>`; '' for any other
    row, which no button starts from and the id list does not name."""
    row = e.get("row")
    if row == "board":
        return str(e.get("key") or "")
    if row == "ledger":
        tid = str(e.get("id") or "")
        return qid(str(e.get("name") or ""), tid) if TD_REF.fullmatch(tid) else ""
    if row == "red_pr":
        return f"{e.get('repo')}#{e.get('pr')}"
    mid = str(e.get("id") or "")
    return mid if not row and mid.startswith("m-") else ""


def waits_on_me(mine: Iterable[str], wants: Mapping[str, Any]) -> list[str]:
    """*waits on me* in **Start session**'s id list (§4.5 screen 12 *Started from an item*, TD-1246): the card's
    Decide and Do ledger entries in key order (`card_entries`), then every other Decide and Do item — a board
    line, a mail item, a red PR — by its id, in the card's order."""
    out = list(mine)
    for w in WANTS:
        for m in wants.get(w) or ():
            ref = str(m.get("item") or "")
            if ref and not TD_REF.fullmatch(ref) and ref not in out:
                out.append(ref)
    return out


def attach(
    sections: Mapping[str, Any], drawn: Any, later: Any = (), start: Any = None, with_of: Any = None
) -> dict[str, Any]:
    """The Inbox's rows the Queue draws (`home: queue`, §4.5 screen 6 *Where a row is drawn*), by the card each
    is attached to and the card's section it is in (§4.5 screen 12 *What is attached to a card*, TD-828):
    `cards`, each card's `{section: [item]}`, every item `{section, id, item, html, kind, on_row}` with the row
    drawn by the Inbox's own renderer (`drawn(e, section)`) and `item` its id (`item_ref`), in the Inbox's order;
    and `mentioned`, on each row an item names beside its own, `{item id: its first words}` — one per item however
    often it is drawn, so the row's one phrase counts items (*mentioned in n items*, TD-915). The snoozed list is
    the Inbox's alone: no Snooze on the Queue. `later` is `split_later`'s rows, all under *Needs you* whatever their
    `Due:`: a ledger row the person's, drawn first, and a board line not yet due after the questions, drawn with
    its due date. `start(card id, item id)` is a Decide or Do item's `item_start`, which its renderer draws as the
    item's own **Start session** (TD-1246); without it no item draws one. `with_of(card id, ref)` names the person's
    own session holding a ledger item's entry on its card, where one does: the item's want is then `with_you`, no
    kind, drawn *with you in <name>* with its Open session (§4.5 screen 12 *Three wants*, TD-1281)."""
    cards: dict[str, dict[str, list[Any]]] = {}
    mentioned: dict[str, dict[str, str]] = {}

    def put(e: Mapping[str, Any], sec: str, drawn_as: str, mid: Any, kind: str) -> None:
        want = want_of(e, sec)
        if want == "held":  # the held row, never the for-you row (§4.5a *Inbox row: held entry*)
            e = {**e, "kind": "ledger · held", "claimed": True, "answers": [], "default": ""}
        card, ref = str(e.get("on_card") or ""), item_ref(e)
        mine = with_of(card, ref) if with_of is not None and e.get("row") == "ledger" and want in WANTS else None
        if mine:
            want, kind = "with_you", ""
        go = start(card, ref) if start is not None and want in (*WANTS, "with_you") and e.get("row") != "red_pr" else {}
        cards.setdefault(card, {}).setdefault(sec, []).append(
            {
                "section": sec,
                "id": str(mid or ""),
                "item": ref,
                # its renderer's `card` mode reads the want, and draws the item's Start session from `start`
                "html": drawn({**e, "want": want, "start": go, **({"with_you": mine} if mine else {})}, drawn_as),
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
    entries the person holds, no want; `with_you`, the person's entries their own session holds, no want and in no
    count (TD-1281); and `n`, the counts — `decide`, `do` (the pill's, a red PR in it) and `read`. Each item
    carries `on` — the row it is about, written as the page writes ids, where that is not the top entry (*on
    TD-n*, a link to the row)."""
    out: dict[str, Any] = {"decide": [], "do": [], "read": {}, "held": [], "with_you": []}
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
    """An attached item's kind: its want where that is Decide or Do; '' for what waits on nobody (Read, a held
    entry)."""
    want = want_of(e, sec)
    return want if want in WANTS else ""


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


def card_session(card: Mapping[str, Any], fleet: Iterable[Mapping[str, Any]] | None, on: str = "") -> dict[str, Any]:
    """Who a card's **Start session** meets (§4.5a *Queue card: Start session / Open session*, TD-912), one answer
    the button and `/api/ledger/start` both read: `start`, the reading's entry to start on; `own`, the person's
    own session (`unattended: false`) holding any of the card's open entries — the one holding `start`, else the
    first by id — whose Focus the press opens; `other`, the name of any other live session holding `start` while
    none of the person's does, when the button is absent and a press is refused. A session holds an entry by its
    claim, or by the name `td-<n>` in the entry's repo before the tick derives the claim (TD-678). `on` is the entry
    an item's press starts on where that is not `start` (§4.5 screen 12 *Started from an item*, TD-1246): the
    holder rules read it in `start`'s place, so `other` is its holder and `own` the one holding it first."""
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

    on = on or start
    on_start = holders(on) if on else []
    own = mine(on_start) or mine(s for r in rows for s in holders(str(r.get("qid") or "")))
    other = on_start[0] if on_start and not own else {}
    return {
        "start": start,
        "own": str(own[0]["id"]) if own else "",
        "other": str(other.get("name") or other.get("id") or ""),
    }


def item_start(card: Mapping[str, Any], item: str, fleet: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """What an item's **Start session** / **Open session** on a card sends and reads (§4.5 screen 12 *Started from
    an item*, TD-1246): `{item, repo, ref, card, own}` — the entry it starts on (a ledger item's own where it is one
    of the card's Decide or Do entries, any other item the card's `start`) and the person's own session the press
    opens — or `{}` where it draws no button: a red PR, a ledger item the road would refuse, a card with no
    `start`, or another session holding the entry it starts on while none of the person's is on the card."""
    if not item or not card.get("start"):
        return {}
    on = str(card["start"])
    if TD_REF.fullmatch(item):
        if item not in card_entries(card)[0] and item != on:
            return {}
        on = item
    elif re.fullmatch(r"[\w.-]+#\d+", item):  # a red PR draws none
        return {}
    met = card_session(card, fleet, on=on)
    if met["other"]:
        return {}
    repo, _, ref = on.partition("#")
    return {"item": item, "repo": repo, "ref": ref, "card": str(card.get("id") or ""), "own": met["own"]}


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
    waits — *waits until*, *waits on an event*, *waiting* (TD-1130), *settling* — else `open` (grey), *with you in
    <name>* among them (TD-1281)."""
    state = str(r.get("state") or "")
    if r.get("archived"):
        return "done"
    if (r.get("needs") and not r.get("with_you")) or state == "held (person)":
        return "needs"
    if state.startswith("waits ") or state in ("waiting", "settling"):
        return "waiting"
    return "open"


def _seg(r: Mapping[str, Any]) -> dict[str, str]:
    """A part's segment in its parent's meter: `branch()`'s colour, and its id and state word in its title, so
    *in review* keeps its word in a grey segment (§4.5 screen 12 *A card*, TD-1131)."""
    word = (
        ""
        if r.get("with_you")
        else {"owner": "yours to do", "decision": "your decision"}.get(str(r.get("needs") or ""), "")
    )
    return {"b": branch(r), "title": f"{r.get('show') or r.get('qid')}: {word or r.get('state') or 'open'}"}


def meter(parts: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    """A parent's parts meter (§4.5 screen 12 *A card*, TD-1131): one segment per part and *d/n*, `d` the
    archived; a parent with no part on the card has none."""
    if not parts:
        return None
    return {"segs": [_seg(p) for p in parts], "d": sum(1 for p in parts if p.get("archived")), "n": len(parts)}


def _tree(rows: list[dict[str, Any]], top: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows as the card draws them (§4.4 *Rows*, §4.5 screen 12 *A card*; TD-1131): indented by *part of*
    alone, each row under its `parent` in the reading's order, which is the drawn order. A part hangs on its
    parent's **spine**: `rails`, one entry per level down to its own — an ancestor's branch where that ancestor is
    a part, "" where it is a loose row (no rule) — so the 2 px rule down a level runs unbroken past the deeper
    rows under it, and a loose row draws none. **Finished parts fold** — an archived part whose own parts are all
    archived — to one `fold` line first on the parent's spine, *✓ n done*; a parent never folds while a part of it
    is open (it is a done group head); finished loose rows fold to one line at the card's end. Each parent, and
    `top` when it is one, gains its `meter`. Returns the lines: `{"row": r}` or `{"fold": [rows], "n", "depth",
    "rails", "loose"}`; a folded row keeps its `rails` for when the fold opens."""
    on = {str(r.get("qid") or "") for r in rows} | {str(top.get("qid") or "")}
    kids: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        p = str(r.get("parent") or "")
        kids.setdefault(p if p in on else "", []).append(r)  # a parent not on the card: a loose row
    top["meter"] = meter(kids.get(str(top.get("qid") or "")) or [])

    def finished(r: Mapping[str, Any], up: frozenset[int] = frozenset()) -> bool:
        """Archived, and every part of it too; a `parent` cycle reads as not finished, so it is drawn, never lost."""
        if id(r) in up or not r.get("archived"):
            return False
        return all(finished(k, up | {id(r)}) for k in kids.get(str(r.get("qid") or "")) or ())

    out: list[dict[str, Any]] = []
    seen: set[int] = set()

    def place(r: dict[str, Any], up: list[str], spine: bool, into: list[dict[str, Any]], depth: int) -> None:
        """`r` and its parts, into `into`: the row, then its finished parts' fold, then its open parts."""
        seen.add(id(r))
        r["depth"] = depth
        r["rails"] = [*up, branch(r)] if spine else [*up, ""]
        r["meter"] = meter(kids.get(str(r.get("qid") or "")) or [])
        into.append({"row": r})
        if r.get("qid"):  # `kids[""]` is the loose rows, never a row's parts
            hang(str(r["qid"]), r["rails"], into, depth + 1)

    def hang(q: str, up: list[str], into: list[dict[str, Any]], depth: int) -> None:
        ks = [k for k in kids.get(q) or () if id(k) not in seen]
        done = [k for k in ks if finished(k)]
        if done:
            folded: list[dict[str, Any]] = []
            for k in done:
                place(k, up, True, folded, depth)
            rs = [r for ln in folded for r in (ln["fold"] if "fold" in ln else [ln["row"]])]  # all of it is done
            into.append({"fold": rs, "n": len(rs), "depth": depth, "rails": [*up, "done"], "loose": False})
        for k in ks:
            if id(k) not in seen:
                place(k, up, True, into, depth)

    hang(str(top.get("qid") or ""), [], out, 1)
    loose = [r for r in kids.get("") or () if id(r) not in seen]
    ends: list[dict[str, Any]] = []
    for r in loose:
        if id(r) not in seen:
            place(r, [], False, ends if finished(r) else out, 1)
    for r in rows:  # a cycle of `parent` lines no walk reached: loose, never lost
        if id(r) not in seen:
            place(r, [], False, out, 1)
    if ends:
        rs = [r for ln in ends for r in (ln["fold"] if "fold" in ln else [ln["row"]])]
        out.append({"fold": rs, "n": len(rs), "depth": 1, "rails": [], "loose": True})
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
        drawn = _tree([_row(r, one_repo, mentioned) for r in c.get("rows") or []], top)
        rows = [r for ln in drawn for r in (ln["fold"] if "fold" in ln else [ln["row"]])]
        wants = card_wants(((mail or {}).get("cards") or {}).get(str(c["id"])), str(top.get("qid") or ""), one_repo)
        status = _mail_status(str(c.get("status") or ""), wants)
        shaped.append(
            {
                **c,
                "status": status,
                "edge": card_edge(str(c.get("group") or ""), status, wants),
                "top": top,
                "rows": rows,
                "lines": drawn,
                "wants": wants,
                "ids": list(c.get("order") or [c["id"]]),
                # the number per repo, each with its chip, where the home reads more than one (TD-901)
                "chips": not one_repo,
                "find": _find_text([top, *rows]),
                "session": card_session(c, fleet),
                # a Decide or Do item but a red PR draws its own Start session, the header then none (TD-1246);
                # so does an item *with you in <name>*, with its Open session (TD-1281)
                "items_start": any(not m.get("red") for w in WANTS for m in wants.get(w) or ())
                or bool(wants.get("with_you")),
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
    """The filter row's picks from the URL (§4.5a *Queue page: filters, find*): `filter` (off when absent, or
    `needs-you`, the switch), `team` a list, comma-separated or repeated, and `find`. An unknown filter is
    dropped, and so are the old `repo` and `kind` picks and `filter=steering` (TD-1287), so a stale link reads
    as not picked, never an error."""

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
        "find": " ".join(str(params.get("find") or "").split()),
    }


def picks_query(picks: Mapping[str, Any], **change: Any) -> str:
    """The page's address with `change` applied to `picks` — a toggle's link: a `team` string is toggled in its
    list and a `team` list replaces it (`team=[]` is **All**: the chips cleared, the rest kept), `filter`
    replaced (its own value again is off, as is `filter=""`), `find` set."""
    p = {k: (list(v) if isinstance(v, list) else v) for k, v in picks.items()}
    for k, v in change.items():
        if k == "team" and isinstance(v, list):
            p[k] = list(v)
        elif k == "team":
            p[k] = [x for x in p.get(k) or [] if x != v] if v in (p.get(k) or []) else [*(p.get(k) or []), v]
        elif k == "filter":
            p[k] = "" if p.get(k) == v else v
        else:
            p[k] = v
    parts = [f"filter={p['filter']}"] if p.get("filter") else []
    if p.get("team"):
        parts.append(f"team={quote(','.join(p['team']))}")
    if p.get("find"):
        parts.append(f"find={quote(p['find'])}")
    return "/queue" + ("?" + "&".join(parts) if parts else "")


def filter_chips(teams: Mapping[str, str], repos: Any, picked: Any) -> dict[str, list[str]]:
    """The filter row's chips (§4.5 screen 12 *Filters*, TD-1287): `team` — each team whose repo the Queue
    reads, or that is picked, by name; `repo` — each repo it reads that no team's repo names and no team with
    a repo (`teams`: name → repo) is named like, and each picked name no team holds, so it can be pressed off,
    by name. A repo chip's pick is a `team` name that names no team, which `apply_picks` reads as the repo."""
    read, picked = set(repos or ()), list(picked or ())
    named = set(teams.values()) | set(teams)
    return {
        "team": sorted(n for n, r in teams.items() if r in read or n in picked),
        "repo": sorted((read - named) | {t for t in picked if t not in teams}),
    }


def apply_picks(view: dict[str, Any], picks: Mapping[str, Any], teams: Mapping[str, str]) -> dict[str, Any]:
    """Mark what the picks hide (`off`), never drop it: a move's neighbours are the whole Up next order,
    whatever a filter hides (§4.4 *A move lands*). A card passes when its status fits `filter` (*needs you*,
    the switch), one of its repos is a picked chip's — a team's repo (`teams`: name → repo), and a name no
    team holds is a repo, which is what a repo chip is (TD-1287) — and every word of `find` is in its ids and
    titles. A completed line passes by the chips and the find, and by none while the switch is on: nothing on
    it needs the person. `find_miss` is an id the find names that no open card holds, with the Repo page's
    address for it in the archive (one per repo where the id names none)."""
    repos: set[str] = set()
    if picks.get("team"):
        repos = {teams.get(t, t) for t in picks["team"]} - {""} or {"\0"}
    words = [_find_word(w) for w in str(picks.get("find") or "").split()]

    def by_repo_find(card_repos: Any, text: str) -> bool:
        if repos and not repos & set(card_repos or ()):
            return False
        return all(_finds(w, text) for w in words)

    cards = [*(view.get("in_progress") or ()), *(view.get("waiting") or ()), *(view.get("up_next") or ())]
    for c in cards:
        ok = by_repo_find(c.get("repos"), str(c.get("find") or ""))
        if picks.get("filter") == "needs-you":
            ok = ok and c.get("status") == "needs you"
        c["off"] = not ok
    status_pick = bool(picks.get("filter"))
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
    view["filtered"] = bool(picks.get("filter") or picks.get("team") or words)
    return view
