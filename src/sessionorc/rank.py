"""The rank's moves and their flush (design §4.4 *The Queue*: *The rank file*, *A move lands*, TD-769).

A move is the person's: `rank_move {ids, prev, next}` (`ao rank`, a drag on the Queue) stores an
**intent** in `ranks.json` beside `repos.json`, and `RANK_FLUSH` after the last move the home
re-derives every intent against the cards as they are then and writes the lines — one key per open
member of the moved card, the one new key between the keys of the two cards it now sits between —
on each repo's rank file, one `queue: rank` PR per repo, landed by the board's road. The same flush
writes a `queue: join` for an open member of a lined card whose line is not the card's key, and a
`queue: prune` for the lines of a card wholly archived, each a PR of its own kind. This module holds
the pure half — the intent, its re-derivation, what a join or a prune is — and the store; the landing
is `board.land_rank`, and the agent's half is `agent_rank`.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sessionorc import ledgerboard as lb
from sessionorc import paths
from sessionorc.store import _atomic_write

# A flush runs this long after the last move (§4.4 *A move lands*), and this long after a join or a
# prune is first found, so a run of drags lands as one PR per repo
RANK_FLUSH = 60.0
TOOL = "shiftlead"  # the `(<tool>)` of every rank PR's subject (ledgerboard's `queue_subject`)
NEIGHBOURS_KEPT = 5  # the cards beyond each neighbour an intent remembers, for a neighbour that is gone


class Refused(Exception):
    """A move the rank refuses, in words the caller is shown."""


def split(q: str) -> tuple[str, str]:
    """`shiftlead#TD-769` → (`shiftlead`, `TD-769`)."""
    repo, _, tid = q.partition("#")
    return repo, tid


def _sort(c: Mapping[str, Any]) -> tuple[tuple[int, ...], int, str]:
    repo, tid = split(str(c["id"]))
    return lb.key_order(str(c.get("key") or "")), int(tid[3:]), repo


def order(cards: list[dict[str, Any]], keys: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Every open card in rank order — In progress and Up next alike, every card having a key — with
    `keys` (card id → key) standing in for a card's own key."""
    keys = keys or {}
    return sorted(cards, key=lambda c: _sort({**c, "key": keys.get(c["id"], c.get("key") or "")}))


def card_of(cards: list[dict[str, Any]], q: str) -> dict[str, Any] | None:
    """The open card one of whose open members is `q`."""
    return next((c for c in cards if q in (c.get("order") or ())), None)


def up_next(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The Up next cards in rank order (§4.4 *A move lands*)."""
    return [c for c in order(cards) if c.get("group") == "up_next"]


def intent(
    cards: list[dict[str, Any]], ids: list[str], prev: str | None, next_: str | None, by: str, at: str
) -> dict[str, Any] | None:
    """The intent of a move of the card holding `ids` to between the cards holding `prev` and `next_`
    (None: that end of the order), or None for a move that leaves it where it is. Refused: an id no open
    card holds, ids of two cards, a card In progress, a neighbour not in Up next or the card itself, and
    neighbours not adjacent in the Up next order the card leaves."""
    if not ids:
        raise Refused("a move names the card's ids")
    card = card_of(cards, ids[0])
    if card is None:
        raise Refused(f"{ids[0]} is not on an open card")
    if any(card_of(cards, q) is not card for q in ids):
        raise Refused(f"{', '.join(ids)} are not one card's")
    if card.get("group") != "up_next":
        raise Refused(f"{card['id']}'s card is In progress, which does not move")
    ups = up_next(cards)
    rest = [c for c in ups if c is not card]
    ends: list[dict[str, Any] | None] = []
    for q in (prev, next_):
        if q is None:
            ends.append(None)
            continue
        c = card_of(cards, q)
        if c is None:
            raise Refused(f"{q} is not on an open card")
        if c is card:
            raise Refused(f"{q} is on the moved card itself")
        if c.get("group") != "up_next":
            raise Refused(f"{q}'s card is not in Up next: a card moves only among Up next cards")
        ends.append(c)
    p, n = ends
    at_p = rest.index(p) if p is not None else -1
    at_n = rest.index(n) if n is not None else len(rest)
    if at_n != at_p + 1:
        raise Refused("the neighbours are not adjacent in the Up next order")
    i = ups.index(card)
    now_p = ups[i - 1] if i > 0 else None
    now_n = ups[i + 1] if i + 1 < len(ups) else None
    if now_p is p and now_n is n:
        return None  # where it is: accepted, and nothing lands
    return {
        "ids": list(card.get("order") or ids),
        "prev": prev,
        "next": next_,
        # the cards beyond each neighbour, nearest first: a neighbour archived or out of the order by the
        # flush is replaced by the nearest of these that survives (§4.4 *A move lands*)
        "prevs": [c["id"] for c in reversed(rest[max(0, at_p - NEIGHBOURS_KEPT) : max(0, at_p)])],
        "nexts": [c["id"] for c in rest[at_n + 1 : at_n + 1 + NEIGHBOURS_KEPT]],
        "by": by,
        "at": at,
    }


def place(cards: list[dict[str, Any]], card_id: str, keys: Mapping[str, str]) -> int | None:
    """The card's place in Up next (from 1) with `keys` standing in, or None when it is not in Up next."""
    ups = [c for c in order(cards, keys) if c.get("group") == "up_next"]
    return next((i for i, c in enumerate(ups, 1) if c["id"] == card_id), None)


def derive(it: Mapping[str, Any], cards: list[dict[str, Any]], keys: dict[str, str]) -> tuple[dict, str] | None:
    """An intent re-derived against the cards as they are now (§4.4 *A move lands*): the moved card (its
    current open members) and its new key, between the keys of the cards it sits between in the whole
    order — `keys` standing in for the keys of cards an earlier intent of the same flush moved. A
    neighbour gone is replaced by the nearest surviving card the intent remembers beyond it. None when
    no member is open any more. Refused when no key fits between the two (two cards of one key)."""
    card = next((c for q in it.get("ids") or () if (c := card_of(cards, q)) is not None), None)
    if card is None:
        return None
    whole = [c for c in order(cards, keys) if c is not card]

    def key(c: Mapping[str, Any] | None) -> str | None:
        return None if c is None else keys.get(c["id"], str(c.get("key") or ""))

    def first(qs: list[Any]) -> dict[str, Any] | None:
        for q in qs:
            if q and (c := card_of(whole, str(q))) is not None:
                return c
        return None

    p = first([it.get("prev"), *(it.get("prevs") or ())])
    n = first([it.get("next"), *(it.get("nexts") or ())])
    if p is not None:  # just after the card ranked before it, whatever now follows that one
        i = whole.index(p)
        lo, hi = key(p), key(whole[i + 1]) if i + 1 < len(whole) else None
    elif n is not None:  # just before the card after it, whatever now precedes that one
        i = whole.index(n)
        lo, hi = key(whole[i - 1]) if i > 0 else None, key(n)
    elif it.get("prev") is None:  # the top, its next gone
        lo, hi = None, key(whole[0]) if whole else None
    else:  # every neighbour gone: the end of the order
        lo, hi = key(whole[-1]) if whole else None, None
    try:
        new = lb.midpoint(lo, hi)
    except lb.Refused as e:
        raise Refused(f"no key fits between the neighbours of {card['id']}'s card: {e}") from None
    keys[card["id"]] = new
    return card, new


def _members(c: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [r for r in [c.get("top") or {}, *(c.get("rows") or ())] if r and not r.get("archived")]


def joins(cards: list[dict[str, Any]], keys: Mapping[str, str] | None = None) -> dict[str, str]:
    """`{qid: key}` for every open member of a lined card whose line is not the card's key — a build filed
    later, two lined cards merged (§4.4 *The rank file*), the moved cards of `keys` left out."""
    keys = keys or {}
    out: dict[str, str] = {}
    for c in cards:
        if not c.get("lined") or c["id"] in keys:
            continue
        for r in _members(c):
            if not r.get("lined") or r.get("key") != c.get("key"):
                out[str(r["qid"])] = str(c["key"])
    return out


def prunes(cards: list[dict[str, Any]], lined: Mapping[str, list[str]]) -> dict[str, None]:
    """`{qid: None}` for every line of a repo's rank file (`lined`: repo → its ids with a line) whose card
    is wholly archived: neither an open member nor an archived row of an open card (§4.4 *The rank
    file*: a lined entry archived while its card is open keeps its line)."""
    alive = {str(r["qid"]) for c in cards for r in [c.get("top") or {}, *(c.get("rows") or ())] if r.get("qid")}
    return {q: None for repo, ids in lined.items() for t in ids if (q := f"{repo}#{t}") not in alive}


def by_repo(lines: Mapping[str, str | None]) -> dict[str, dict[str, str | None]]:
    """`{qid: key}` → `{repo: {TD-n: key}}`."""
    out: dict[str, dict[str, str | None]] = {}
    for q, k in lines.items():
        repo, tid = split(q)
        out.setdefault(repo, {})[tid] = k
    return out


def changed(text: str, lines: Mapping[str, str | None]) -> dict[str, str | None]:
    """The lines of `lines` the rank file's `text` does not already say."""
    have = lb.rank(text)[0]
    return {t: k for t, k in lines.items() if have.get(t) != k and not (k is None and t not in have)}


def lined_ids(text: str) -> list[str]:
    """The ids a rank file gives a line."""
    return list(lb.rank(text)[0])


class RankStore:
    """`ranks.json`: the intents not yet landed, when the last move was made, the cards whose rank PR
    failed after its retry (`not_landed`, card id → why), when a join or a prune was first found, and what
    the last flush found (`flushed`), so a checkout that has not caught up is not flushed again. Written
    whole; a missing or unreadable file is no intents (an intent not landed is lost on a machine change,
    accepted — §4.4)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.home() / "ranks.json"
        self.lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        raw = raw if isinstance(raw, dict) else {}
        return {
            "intents": [i for i in raw.get("intents") or () if isinstance(i, dict)],
            "moved_at": raw.get("moved_at"),
            "found_at": raw.get("found_at"),
            "not_landed": {str(k): str(v) for k, v in (raw.get("not_landed") or {}).items()},
            "flushed": [list(x) for x in raw.get("flushed") or () if isinstance(x, list)],
        }

    def save(self, state: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.path, json.dumps(state, indent=1))
