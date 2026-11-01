"""The Repo page's **board** (design §4.5 screen 11 *the board*, §4.5a *Repo page: Technical debt cards*; TD-900,
built by TD-903): one repo by stage — **For you**, one column per worker stage of the servicing teams' flows,
**Review**, **Merged**. An entry is placed by its page kind against the stages' lane words, never by a stage's
name (§9 invariant 9); a column's rows are its claimed entries, then its queued ones in the Queue's order with
the rows of one card together, then its blocked ones folded. This module shapes the columns from the readings
the page already holds; it reads no file and calls nothing.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

from sessionorc.models import owner_word
from shiftlead import flowdefs, repoconfig
from shiftlead import org as orgmod
from shiftlead import teams as teams_mod

SHOWN = 7  # a column's queued rows, and For you's, sent on a load (§4.5 screen 11 *Only what is shown*)
DESIGN, PICK = "design-first", "free-pick"
# no team, or no usable flow: the five fixed columns, placing by the page kinds alone (§4.5 screen 11)
FIXED = (("design", "Design", [DESIGN]), ("build", "Build", [PICK]))
NO_DESIGN = "no design stage"


def team_stages(org: orgmod.Org, names: Collection[str], root: str) -> list[tuple[str, list[flowdefs.Stage] | None]]:
    """Each servicing team's current flow's stages, in `names`' order, read against the repo's checkout
    `root` — None for a team with no flow, or one whose flow is not there or not usable (§4.9c). Reads
    files: once per page load, off the loop."""
    out: list[tuple[str, list[flowdefs.Stage] | None]] = []
    for n in names:
        t = org.teams.get(n)
        flow = None
        name = teams_mod.current_flow(t) if t is not None else None
        if name:
            try:
                flow = flowdefs.load(name, repoconfig.load(Path(root)), org.roles)
            except (OSError, ValueError):
                flow = None
        out.append((n, list(flow.stages) if flow is not None and flow.usable else None))
    return out


def columns(flows: list[tuple[str, list[flowdefs.Stage] | None]]) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """The worker columns (§4.5 screen 11 *The columns*): the worker stages of the teams' flows in flow order,
    joined — a stage whose lane words equal an earlier one's is drawn once, under the first team's stage
    name, its role added to that column's people; one that differs is a column of its own, headed *<name> ·
    <owner word>* where its name is already taken. Each `{key, name, lane, kinds, owners, roles}`, `roles`
    the `(team, role)` pairs staffing it. Where no team has a usable flow, the fixed *Design* and *Build*.
    Also returns Review's `(team, role)` pairs, the flows' review stages."""
    cols: list[dict[str, Any]] = []
    review: list[tuple[str, str]] = []
    for team, stages in flows:
        for s in stages or ():
            if s.review:
                if (team, s.role) not in review:
                    review.append((team, s.role))
                continue
            lane = [str(w) for w in s.lane]
            same = next((c for c in cols if c["lane"] == lane), None)
            if same is not None:
                if (team, s.role) not in same["roles"]:
                    same["roles"].append((team, s.role))
                continue
            owners = [o for w in lane if (o := owner_word(w))]
            name = s.name[:1].upper() + s.name[1:]
            if any(c["name"] == name for c in cols):
                name = f"{name} · {owners[0] if owners else team}"
            cols.append(
                {
                    "key": f"s{len(cols) + 1}",
                    "name": name,
                    "lane": lane,
                    "kinds": [w for w in lane if w in (DESIGN, PICK)],
                    "owners": owners,
                    "roles": [(team, s.role)],
                }
            )
    if not cols:
        cols = [
            {"key": k, "name": n, "lane": ln, "kinds": ln, "owners": [], "roles": [], "fixed": True}
            for k, n, ln in FIXED
        ]
    return cols, review


def place(e: Mapping[str, Any], cols: list[dict[str, Any]]) -> tuple[str, str]:
    """`(column key, '')` for an entry, by its page kind against the columns' lane words (§4.5 screen 11):
    *design* to the column taking `design-first`; *pickable* and *live check* to one taking `free-pick` — the
    first whose owner words take the entry's `Owner:`, else the first; a *blocked* entry where it will go once
    it is not (a `design-first` one to Design, the rest to the pick). `('', words)` for one no lane takes —
    *evaluation*, *other*, a flagged entry, a design entry with no design stage — its flag's words."""
    kind = str(e.get("for_page") or "")
    if e.get("flag"):
        return "", str(e["flag"])

    def taking(word: str) -> list[dict[str, Any]]:
        return [c for c in cols if word in c["kinds"]]

    if kind == "blocked":
        kind = "design" if str(e.get("kind") or "") == DESIGN else "pickable"
        if kind == "design" and not taking(DESIGN):
            kind = "pickable"
    if kind == "design":
        got = taking(DESIGN)
        return (got[0]["key"], "") if got else ("", NO_DESIGN)
    if kind in ("pickable", "live-check"):
        got = taking(PICK)
        if not got:
            return "", "no lane takes it"
        owner = str(e.get("owner") or "").strip().lower()
        return next((c for c in got if owner and owner in c["owners"]), got[0])["key"], ""
    return "", str(e.get("flag") or kind or "no lane takes it")


def _waits_on_you(e: Mapping[str, Any]) -> bool:
    """For you's rule (§4.4 *The card's status*): `Owner: paul` or `decision (paul)`."""
    return e.get("for_page") == "for-you"


def _people(roles: list[tuple[str, str]], members: Collection[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Who is on a stage, per team (§4.5 screen 11 *A column's heading*): the members whose role the stage names,
    grouped by their lane's word — *grinder-ao-1 · grinder-ao-2 · out of work* — and *no <role> running*,
    `none`, where no live member holds it."""
    out = []
    for team, role in roles:
        held = [m for m in members if m.get("team") == team and str(m.get("role") or "") == role]
        live = [m for m in held if m.get("state") not in ("exited", "closed")]
        if not live:
            out.append({"team": team, "text": f"no {role} running", "none": True})
            continue
        words: dict[str, list[str]] = {}
        for m in live:
            w = "out of work" if m.get("out_of_work") else str(m.get("state_label") or m.get("state") or "")
            words.setdefault(w, []).append(str(m.get("name") or m.get("id")))
        out.append(
            {"team": team, "text": ", ".join(" · ".join([*names, w]) for w, names in words.items()), "none": False}
        )
    return out


def _kind_word(e: Mapping[str, Any]) -> str:
    """A row's word in its column's heading kinds (*build · live check*; *decide · yours*)."""
    k = str(e.get("for_page") or "")
    if k == "for-you":
        return "decide" if str(e.get("kind") or "") == "decision" else "yours"
    if k == "live-check":
        return "live check"
    if k == "design":
        return DESIGN
    return str(e.get("kind") or "build") if k == "pickable" else k


def board(
    cards: Mapping[str, Any] | None,
    lists: list[dict[str, Any]],
    flows: list[tuple[str, list[flowdefs.Stage] | None]],
    members: Collection[Mapping[str, Any]],
    name: str,
    opened: Collection[str] = (),
    doing: Mapping[str, str] | None = None,
    orders: Collection[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The board's ledger columns (§4.5 screen 11): `{foryou, stages, fold, review_people, upnext, numbered}`.

    `cards` is `repo.debt_cards`' (the repo's Queue cards, whole, in the reading's order) or None where the home
    serves no Queue reading — a node, a home before its first tick — and the rows are then the ledger's, in
    `lists`' order, with no number and no grip. Each column `{key, name, people, kinds, claimed, groups, more,
    blocked, n_blocked, n}`: `claimed` its rows a member claims, each with `holders` and `doing`, the first
    holder's newest `ao doing` line; `groups` its queued rows by card, `{card, ids, up, place, wait, would_be,
    rows}`, in the
    Queue's order, cut after `SHOWN` rows (`more` the rest) unless `opened` names `<key>:queued` or an id in
    them; `blocked` its blocked rows, sent only when `opened` names `<key>:blocked` or an id in them,
    `n_blocked` always. `up` is a card Up next with its first row here (the grip and ⤒ ↑ ↓), `place` its
    number in this repo; `wait` a Waiting card's `{column, phrase, id}` and `would_be` its place here once the
    wait ends, drawn in the gutter with no grip (TD-918). The work orders `orders` (open decided board lines)
    lead the pick's queued rows.
    `fold` is *no lane takes these*: `(row, words)` pairs. `numbered` is whether the home served the cards."""
    opened = set(opened)
    doing = doing or {}
    cols, review = columns(flows)
    by_key: dict[str, dict[str, Any]] = {
        c["key"]: {
            **c,
            "people": _people(c["roles"], members),
            "claimed": [],
            "groups": {},
            "blocked": [],
            "orders": [],
        }
        for c in cols
    }
    foryou: dict[str, Any] = {
        "key": "foryou",
        "name": "For you",
        "claimed": [],
        "groups": {},
        "blocked": [],
        "orders": [],
    }
    fold: list[tuple[dict[str, Any], str]] = []
    pick = next((c["key"] for c in cols if PICK in c["kinds"]), "")
    if pick:
        by_key[pick]["orders"] = list(orders)
    else:  # no stage takes free-pick: a decided line is in no lane, so it waits in For you's fold
        fold.extend(({**o, "anchor": "", "ext": {}, "work_order": True}, "no lane takes it") for o in orders)

    if cards is not None:
        seq = []
        for c in cards.get("cards") or ():
            for r in (c["top"], *(c.get("rows") or ())):
                if r.get("anchor") and r.get("ext"):
                    seq.append((c, r))
    else:  # no Queue reading: the ledger's own rows, one card each, unnumbered
        seq = []
        for lst in lists:
            for e in lst["rows"]:
                if e.get("work_order"):
                    continue
                r = {
                    "qid": f"{name}#{e['id']}",
                    "repo": name,
                    "id": e["id"],
                    "show": e["id"],
                    "title": e.get("title") or "",
                    "priority": str(e.get("priority") or "").lower(),
                    "state": f"held by {e['held']}" if e.get("held") else "",
                    "holder": None,
                    "archived": False,
                    "afters": [],
                    "anchor": e["id"],
                    "ext": {**e, "kind_label": lst["label"]},
                }
                seq.append(({"id": r["qid"], "ids": [r["qid"]], "group": "", "places": []}, r))

    for card, r in seq:
        e = r["ext"]
        col = foryou if _waits_on_you(e) else None
        words = ""
        if col is None:
            key, words = place(e, cols)
            col = by_key.get(key)
        if col is None:
            fold.append((r, words))
            continue
        if e.get("held"):  # a member's claim (§4.4 *TDs in motion*): first, with its holder and doing line
            holders = [h.strip() for h in str(e["held"]).split(",") if h.strip()]
            col["claimed"].append(
                {**r, "holders": holders, "doing": next((doing[h] for h in holders if h in doing), "")}
            )
        elif e.get("for_page") == "blocked":
            col["blocked"].append(r)
        else:
            g = col["groups"].get(card["id"])
            if g is None:
                up = cards is not None and card.get("group") == "up_next"
                mine = next((p["n"] for p in card.get("places") or () if p.get("repo") == name), None)
                # a Waiting card's gutter draws its wait column and no grip (§4.5 screen 11 *For you*, TD-918)
                waits = cards is not None and card.get("group") == "waiting" and card.get("wait")
                g = col["groups"][card["id"]] = {
                    "card": card["id"],
                    "ids": card.get("ids") or [card["id"]],
                    "up": up,
                    "place": mine if up else None,
                    "wait": card["wait"] if waits else None,
                    "would_be": next((w["n"] for w in card.get("would_be") or () if w.get("repo") == name), None),
                    "rows": [],
                }
            g["rows"].append(r)

    def finish(col: dict[str, Any]) -> dict[str, Any]:
        groups = list(col["groups"].values())
        rows = [r for g in groups for r in g["rows"]]
        whole = f"{col['key']}:queued" in opened or any(r["id"] in opened for r in rows)
        left, kept = SHOWN - len(col["orders"]), []
        for g in groups:
            if whole:
                kept.append(g)
            elif left > 0:
                kept.append({**g, "rows": g["rows"][:left]})
                left -= len(kept[-1]["rows"])
        n_sent = sum(len(g["rows"]) for g in kept)
        blocked = col["blocked"]
        bwhole = f"{col['key']}:blocked" in opened or any(r["id"] in opened for r in blocked)
        every = [*col["claimed"], *rows, *blocked]
        kinds = list(dict.fromkeys([*(["decided"] if col["orders"] else []), *(_kind_word(r["ext"]) for r in every)]))
        return {
            **col,
            "groups": kept,
            "more": len(rows) - n_sent,
            "blocked": blocked if bwhole else [],
            "n_blocked": len(blocked),
            "n": len(every) + len(col["orders"]),
            "kinds": kinds,
        }

    return {
        "foryou": finish(foryou),
        "stages": [finish(by_key[c["key"]]) for c in cols],
        "fixed": bool(cols and cols[0].get("fixed")),
        "fold": fold,
        "review_people": _people(review, members),
        "upnext": list((cards or {}).get("upnext") or []),
        "numbered": cards is not None,
    }
