"""The seat ledger: who spent the quota (design §4.4 *Spend per seat*, TD-818, built by TD-830).

The account ledger (`sessionorc.spend`, `spend.json`) answers *how much has this key spent* and gates
on it; this one answers *who spent it*, for every profile, a subscription's included, and nothing
gates on it. Each turn the adapter reports (§4.3 *Spend per turn*) is

- **weighed**: its `cost`, else the metered profile's prices, else the person's weights (§5
  `spend.weights`) by the turn's `model`'s longest prefix, else *unweighed* and kept in tokens;
- **owned**: by the record whose `adapter_id` is the turn's conversation or whose `transcript` is its
  source, else by the record whose `dir` is the turn's `cwd` or above it (the deepest) inside the
  `cwd`'s git worktree, else by *outside shiftlead* — the owner found once per transcript and kept on
  its cursor;
- **charged** to the owner's current reference: the claimed reference its live `doing` names as a
  whole token (the longest), else its newest claim, else `between`.

`seat_spend.json` beside `spend.json`: `{began, days: {YYYY-MM-DD: {<record id>: {name, role, team,
repo, metered, models: {<model>: {input, output, cache_read, cache_write, turns, figure, past_200k,
past_300k, unweighed, subagent}}, refs: {<ref>: {figure, turns}}}}}, refs: {"<repo> <ref>":
{first_claimed, done_at, partial?}}, hosts: {<host>: {cursors: {<source>: {offset, seen, at, id,
response, tokens, owner, root}}, seeded: [<profile>]}}}`. *Outside shiftlead* is the record id
`outside`. A turn is counted once by the account ledger's rules (`spend._fresh`), and a cursor moves
only after its row is written. Tool-agnostic: nothing here knows a tool or a price list by heart, but
the default weights the design ships (§5)."""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc import paths
from sessionorc import spend as spend_mod
from sessionorc.store import _atomic_write

KINDS = spend_mod.KINDS
OUTSIDE = "outside"  # the record id of a turn no record owns
BETWEEN = "between"  # the reference of a turn whose record held no claim
BACKFILL = timedelta(days=14)  # the first pass reads the fortnight before it (§4.4 *First read*)
PAST = (200_000, 300_000)  # the context marks a row's figure is kept past (TD-460's reading)
ROOT_GONE = ""  # a cursor's `root` when the `cwd`'s worktree could not be read: no record by `cwd`

# §5 `spend.weights`' default: the API's list prices of `as_of`, $ per million tokens per kind, by
# model prefix (the longest wins). A newer price is the person's settings change, not an edit here.
WEIGHTS: dict[str, Any] = {
    "as_of": "2026-10-17",
    "claude-fable": {"input": 10, "output": 50, "cache_read": 0.25, "cache_write": 20},
    "claude-opus": {"input": 4, "output": 20, "cache_read": 0.2, "cache_write": 8},
    "claude-sonnet": {"input": 2, "output": 10, "cache_read": 0.2, "cache_write": 4},
    "claude-haiku": {"input": 0.1, "output": 0.5, "cache_read": 0.01, "cache_write": 0.2},
    "claude-opus-5": {"input": 5, "output": 25, "cache_read": 0.5, "cache_write": 10},
    "claude-opus-5-5": {"input": 4, "output": 20, "cache_read": 0.2, "cache_write": 8},
    "claude-opus-4": {"input": 5, "output": 25, "cache_read": 0.5, "cache_write": 10},
    "claude-sonnet-4": {"input": 3, "output": 15, "cache_read": 0.3, "cache_write": 6},
    "claude-haiku-4": {"input": 1, "output": 5, "cache_read": 0.1, "cache_write": 2},
}


def seat_file() -> Path:
    return paths.home() / "seat_spend.json"


class SeatStore:
    """`seat_spend.json`. A missing or unreadable file is an empty ledger, never a crash — the next
    pass backfills again."""

    def __init__(self, path: Path | None = None):
        self.path = path or seat_file()

    def load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def save(self, ledger: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.path, json.dumps(ledger, indent=1, sort_keys=True))


# -- weighing ------------------------------------------------------------------------------------


def weight_for(model: str, weights: dict[str, Any]) -> dict[str, float] | None:
    """The weights of the longest key `model` starts with, or None when none matches (unweighed)."""
    keys = [k for k, v in weights.items() if k != "as_of" and isinstance(v, dict) and model.startswith(k)]
    return weights[max(keys, key=len)] if model and keys else None


def figure_of(
    turn: dict[str, Any], tokens: dict[str, int], prices: dict[str, float] | None, weights: dict[str, Any]
) -> tuple[float | None, bool]:
    """A turn's worth and whether it is a bill: its own `cost`, else the metered profile's prices,
    both bills; else its tokens at the weights — a kind with no weight at `input`, as `prices:` does
    (§4.2a) — API-equivalent; else `(None, False)`: unweighed."""
    billed = spend_mod.cost_of(tokens, turn.get("cost"), prices or None)
    if billed is not None:
        return billed, True
    w = weight_for(str(turn.get("model") or ""), weights)
    if not w:
        return None, False
    return spend_mod.cost_of(tokens, None, {k: float(v) for k, v in w.items()}), False


# -- owning --------------------------------------------------------------------------------------


def worktree_root(cwd: str) -> str:
    """The git worktree `cwd` lies in — the nearest directory at or above it holding `.git`, a file in a
    linked worktree — or `/` for an existing directory in none; `ROOT_GONE` when `cwd` is not a
    directory any more (a removed worktree), which matches no record by `cwd`."""
    p = Path(cwd) if cwd else None
    if p is None or not p.is_absolute() or not p.is_dir():
        return ROOT_GONE
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return str(d)
    return "/"


def _within(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def owner_of(turn: dict[str, Any], records: list[Any], root: str | None) -> str | None:
    """The id of the record a transcript's turn belongs to, or None (outside shiftlead): by the
    conversation, then the transcript, then the deepest `dir` at or above the turn's `cwd` within
    `root` (its worktree). Among several records of one conversation the live one wins, then the one
    not superseded."""
    conv, source = str(turn.get("conversation") or ""), str(turn.get("source") or "")

    def best(rs: list[Any]) -> Any:
        return sorted(rs, key=lambda r: (r.state in ("exited", "closed"), bool(r.superseded_by)))[0]

    if conv and (by := [r for r in records if r.adapter_id == conv]):
        return best(by).id
    if source and (by := [r for r in records if r.transcript == source]):
        return best(by).id
    cwd = str(turn.get("cwd") or "")
    if not cwd or not root:
        return None
    by = [r for r in records if r.dir and _within(cwd, r.dir) and _within(r.dir, root)]
    if not by:
        return None
    deepest = max(len(r.dir) for r in by)
    return best([r for r in by if len(r.dir) == deepest]).id


def current_ref(record: Any) -> str:
    """What a record's turns are charged to now: among its claimed references, the one its `doing`
    names as a whole token (case-insensitive, the longest), `doing` read only while it is live; else
    the claim with the newest `at`; else `between`."""
    claims = [e for e in record.progress if e.status == "claimed"]
    if not claims:
        return BETWEEN
    text = (record.doing or {}).get("text") if record.state not in ("exited", "closed") else None
    if text:
        named = [
            e.ref for e in claims if re.search(rf"(?<![\w-]){re.escape(e.ref)}(?![\w-])", str(text), re.IGNORECASE)
        ]
        if named:
            return max(named, key=len)
    return max(claims, key=lambda e: e.at).ref


def ref_key(repo: str | None, ref: str) -> str:
    """A reference's key in `refs`: two repos' ledgers both hold a `TD-12`."""
    return f"{repo or ''} {ref}"


# -- the pass ------------------------------------------------------------------------------------


def take(
    ledger: dict[str, Any],
    host: str,
    result: dict[str, Any],
    records: list[Any],
    prices: dict[str, float] | None,
    weights: dict[str, Any],
    now: datetime,
    backfill: bool = False,
    root_of: Callable[[str], str] = worktree_root,
) -> bool:
    """One profile's `spend` read into `ledger` (mutated) for `host`'s cursors; whether anything was
    charged or a cursor moved. `prices` is the profile's when it is metered, else None. A backfill
    charges every turn of a transcript it holds no cursor for to `between`; any transcript with no
    cursor drops its turns older than `BACKFILL`. `root_of` gives a `cwd`'s worktree: the home reads
    its own disk, and a node's turns carry the roots the node read (`seat_spend`, TD-833)."""
    cursors = ledger.setdefault("hosts", {}).setdefault(host, {}).setdefault("cursors", {})
    by_id = {r.id: r for r in records}
    by_source: dict[str, list[dict[str, Any]]] = {}
    for t in result.get("turns") or ():
        if (
            isinstance(t, dict)
            and isinstance(t.get("source"), str)
            and isinstance(t.get("offset"), int)
            and str(t.get("model") or "") != "<synthetic>"
        ):
            by_source.setdefault(t["source"], []).append(t)
    oldest = now - BACKFILL
    moved = False
    stamp = now.date().isoformat()
    refs_now: dict[str, str] = {}
    for source, offset in (result.get("cursors") or {}).items():
        if not isinstance(offset, int):
            continue
        cur = cursors.get(source) if isinstance(cursors.get(source), dict) else {}
        turns = sorted(by_source.pop(source, []), key=lambda t: t["offset"])
        keep = spend_mod._fresh(cur, turns)
        back = backfill and not cur  # a transcript another profile's read already holds reads on as live
        if not cur:  # new to this host: never more than the fortnight, a backfill's or a copied-in file's
            keep = [(t, k) for t, k in keep if (w := spend_mod._when(t.get("at"))) is not None and w >= oldest]
        owner = cur.get("owner")
        root = cur.get("root")
        if keep and (owner is None or owner == OUTSIDE):
            cwd = str(next((t.get("cwd") for t, _ in keep if t.get("cwd")), "") or "")
            if root is None:
                root = root_of(cwd)
            owner = owner_of(keep[0][0] | {"cwd": cwd}, records, root) or OUTSIDE
        if owner != OUTSIDE and owner not in by_id:
            owner = OUTSIDE  # its record was forgotten since: outside shiftlead, as the backfill reads it
        for t, tokens in keep:
            record = by_id.get(owner) if owner != OUTSIDE else None
            ref = BETWEEN if record is None or back else refs_now.setdefault(record.id, current_ref(record))
            _charge(ledger, owner or OUTSIDE, record, ref, t, tokens, prices, weights, now)
            moved = True
        new = {"offset": offset, "seen": stamp, "owner": owner, "root": root}
        last = turns[-1] if turns else None
        if last is not None:
            new |= {
                "at": last.get("at"),
                "id": str(last.get("id") or ""),
                "response": str(last.get("response") or ""),
                "tokens": spend_mod._tokens(last),
            }
        else:
            new |= {k: cur[k] for k in ("at", "id", "response", "tokens") if k in cur}
        new = {k: v for k, v in new.items() if v is not None}
        if new != cur:
            cursors[source] = new  # moved after the row is written: the one write holds both
            moved = True
    return moved


def _charge(
    ledger: dict[str, Any],
    rid: str,
    record: Any,
    ref: str,
    turn: dict[str, Any],
    tokens: dict[str, int],
    prices: dict[str, float] | None,
    weights: dict[str, Any],
    now: datetime,
) -> None:
    """One turn into its day's row (the day its `at` carries in the home's zone) for record `rid`."""
    when = spend_mod._when(turn.get("at"))
    day = (when.astimezone(now.tzinfo) if when else now).date().isoformat()
    row = ledger.setdefault("days", {}).setdefault(day, {}).get(rid)
    if row is None:
        row = {"models": {}, "refs": {}, "metered": True}
        if record is not None:
            row |= {"name": record.name, "role": record.role, "team": record.team or "", "repo": record.repo or ""}
        else:
            row |= {"name": OUTSIDE, "role": "", "team": "", "repo": ""}
        ledger["days"][day][rid] = row
    model = str(turn.get("model") or "") or "?"
    m = row["models"].setdefault(
        model, {k: 0 for k in KINDS} | {"turns": 0, "figure": 0.0, "past_200k": 0.0, "past_300k": 0.0}
    )
    for k in KINDS:
        m[k] = int(m.get(k) or 0) + tokens[k]
    m["turns"] = int(m.get("turns") or 0) + 1
    fig, billed = figure_of(turn, tokens, prices, weights)
    row["metered"] = bool(row.get("metered")) and billed  # every turn of the row a bill: drawn `$`
    if fig is None:
        m["unweighed"] = int(m.get("unweighed") or 0) + 1
        fig = 0.0
    m["figure"] = round(float(m.get("figure") or 0.0) + fig, 6)
    context = tokens["input"] + tokens["cache_read"] + tokens["cache_write"]
    for mark in PAST:
        if context > mark:
            key = f"past_{mark // 1000}k"
            m[key] = round(float(m.get(key) or 0.0) + fig, 6)
    if turn.get("subagent"):
        m["subagent"] = int(m.get("subagent") or 0) + 1
    r = row["refs"].setdefault(ref, {"figure": 0.0, "turns": 0})
    r["figure"] = round(float(r.get("figure") or 0.0) + fig, 6)
    r["turns"] = int(r.get("turns") or 0) + 1


def see_claims(ledger: dict[str, Any], records: list[Any], at: str, first: bool = False) -> bool:
    """Each claimed reference's `first_claimed`, the first time a pass sees it on any record; whether
    one was written. On the pass that began the ledger (`first`) each is marked `partial`: it was
    claimed before the ledger could see its spend."""
    refs = ledger.setdefault("refs", {})
    wrote = False
    for r in records:
        for e in r.progress:
            if e.status != "claimed":
                continue
            entry = refs.setdefault(ref_key(r.repo, e.ref), {})
            if "first_claimed" not in entry:
                entry["first_claimed"] = at
                entry |= {"partial": True} if first else {}
                wrote = True
    return wrote


def done(ledger: dict[str, Any], repo: str | None, ref: str, claimed_at: str | None, at: str) -> None:
    """A plain `ao progress done` landed: the reference's `done_at`, and its `first_claimed` from the
    claim's own `at` when no pass saw it (claimed and done inside a minute)."""
    entry = ledger.setdefault("refs", {}).setdefault(ref_key(repo, ref), {})
    entry["done_at"] = at
    if "first_claimed" not in entry:
        entry["first_claimed"] = claimed_at or at


def prune(ledger: dict[str, Any], today: date) -> None:
    """The rows and the cursors older than the account ledger's thirteen months (`spend.KEEP`)."""
    oldest = (today - spend_mod.KEEP).isoformat()
    days = ledger.get("days") or {}
    for d in [d for d in days if d < oldest]:
        del days[d]
    for h in (ledger.get("hosts") or {}).values():
        cursors = h.get("cursors") or {}
        for s in [s for s, c in cursors.items() if str((c or {}).get("seen") or "") < oldest]:
            del cursors[s]


# -- the readings --------------------------------------------------------------------------------


def _blank() -> dict[str, Any]:
    return {"figure": 0.0, "turns": 0, "between": 0.0, "past_200k": 0.0, "past_300k": 0.0, "unweighed": 0}


def _add_row(acc: dict[str, Any], row: dict[str, Any]) -> None:
    for m in (row.get("models") or {}).values():
        acc["figure"] += float(m.get("figure") or 0.0)
        acc["turns"] += int(m.get("turns") or 0)
        acc["past_200k"] += float(m.get("past_200k") or 0.0)
        acc["past_300k"] += float(m.get("past_300k") or 0.0)
        acc["unweighed"] += int(m.get("unweighed") or 0)
    acc["between"] += float(((row.get("refs") or {}).get(BETWEEN) or {}).get("figure") or 0.0)


def _rounded(acc: dict[str, Any], whole: float | None = None) -> dict[str, Any]:
    out = {k: round(v, 4) if isinstance(v, float) else v for k, v in acc.items()}
    fig = acc["figure"]
    for k in ("past_200k", "past_300k"):
        out[f"{k}_share"] = round(acc[k] / fig, 4) if fig else 0.0
    if whole is not None:
        out["share"] = round(fig / whole, 4) if whole else 0.0
    return out


def reading(
    ledger: dict[str, Any],
    window: str,
    now: datetime,
    team: str | None = None,
    by: str | None = None,
    weights: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The `seats` reading over `window` (`day` or `week`, the home's clock): per seat — the records of
    one name within a team, or per record under `by: record` — with its share of its team's figure;
    per role, team and repo; per finished entry (its `done_at` in the window: every row charged to it
    from its `first_claimed`, by role, `partial` when claimed before the ledger began); and the
    entries' count, sum and median per role. *Outside shiftlead* is one row."""
    if window not in ("day", "week"):
        raise ValueError(f"a seats window is day or week, not {window!r}")
    start, resets = spend_mod.bounds(now)[window]
    first, last = start.isoformat(), now.date().isoformat()
    days = {d: rows for d, rows in (ledger.get("days") or {}).items() if isinstance(rows, dict)}
    seats: dict[str, dict[str, Any]] = {}
    groups: dict[str, dict[str, dict[str, Any]]] = {"roles": {}, "teams": {}, "repos": {}}
    outside = _blank()
    metered = True
    seen_any = False
    for d, rows in days.items():
        if d < first or d > last:
            continue
        for rid, row in rows.items():
            if not isinstance(row, dict):
                continue
            if rid == OUTSIDE:
                _add_row(outside, row)
                continue
            if team and row.get("team") != team:
                continue
            seen_any = True
            metered = metered and bool(row.get("metered"))
            key = rid if by == "record" else f"{row.get('team') or ''}\0{row.get('name') or rid}"
            s = seats.setdefault(
                key,
                {"seat": row.get("name") or rid, "team": row.get("team") or "", "role": row.get("role") or "",
                 "repo": row.get("repo") or "", "records": []} | _blank(),
            )  # fmt: skip
            if rid not in s["records"]:
                s["records"].append(rid)
            _add_row(s, row)
            for group, field in (("roles", "role"), ("teams", "team"), ("repos", "repo")):
                _add_row(groups[group].setdefault(str(row.get(field) or ""), _blank()), row)
    team_whole: dict[str, float] = {}
    for s in seats.values():
        team_whole[s["team"]] = team_whole.get(s["team"], 0.0) + s["figure"]
    out_seats = [
        {**{k: s[k] for k in ("seat", "team", "role", "repo", "records")},
         **_rounded({k: s[k] for k in _blank()}, team_whole[s["team"]])}
        for s in sorted(seats.values(), key=lambda s: (-s["figure"], s["team"], s["seat"]))
    ]  # fmt: skip
    entries, roles = _entries(ledger, days, first, last, resets, team)
    return {
        "window": window,
        "begins": spend_mod._begins(start, resets).isoformat(),
        "resets": resets.isoformat(),
        "unit": "$" if metered and seen_any else "≈$",
        "as_of": (weights or WEIGHTS).get("as_of"),
        "began": ledger.get("began"),
        "seats": out_seats,
        **{g: {k: _rounded(v) for k, v in sorted(rows.items())} for g, rows in groups.items()},
        "entries": entries,
        "finished": roles,
        "outside": _rounded(outside),
    }


def _entries(
    ledger: dict[str, Any], days: dict[str, Any], first: str, last: str, resets: datetime, team: str | None
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """The entries finished in the window, each its whole figure from its `first_claimed`, and per
    role (the role that spent most on it) the count, sum and median."""
    began = str(ledger.get("began") or "")
    out = []
    for key, meta in (ledger.get("refs") or {}).items():
        done_at = str((meta or {}).get("done_at") or "")
        done_day = _local_day(done_at, resets)
        if not done_day or done_day < first or done_day > last:
            continue
        repo, _, ref = key.partition(" ")
        since = _local_day(str(meta.get("first_claimed") or ""), resets) or first
        figure, turns, by_role, teams = 0.0, 0, {}, set()
        for d, rows in days.items():
            if d < since:
                continue
            for rid, row in rows.items():
                if rid == OUTSIDE or not isinstance(row, dict) or (row.get("repo") or "") != repo:
                    continue
                got = (row.get("refs") or {}).get(ref)
                if not got:
                    continue
                fig = float(got.get("figure") or 0.0)
                figure += fig
                turns += int(got.get("turns") or 0)
                role = str(row.get("role") or "")
                by_role[role] = by_role.get(role, 0.0) + fig
                teams.add(str(row.get("team") or ""))
        if team and team not in teams:
            continue
        out.append(
            {
                "ref": ref,
                "repo": repo,
                "first_claimed": meta.get("first_claimed"),
                "done_at": done_at,
                "figure": round(figure, 4),
                "turns": turns,
                "by_role": {k: round(v, 4) for k, v in sorted(by_role.items())},
                "partial": bool(meta.get("partial")) or (bool(began) and str(meta.get("first_claimed") or "") < began),
            }
        )
    out.sort(key=lambda e: e["done_at"])
    per_role: dict[str, list[float]] = {}
    for e in out:
        role = max(e["by_role"], key=e["by_role"].get) if e["by_role"] else ""
        per_role.setdefault(role, []).append(e["figure"])
    roles = {
        r: {"entries": len(v), "sum": round(sum(v), 4), "median": round(statistics.median(v), 4)}
        for r, v in sorted(per_role.items())
    }
    return out, roles


def _local_day(stamp: str, resets: datetime) -> str:
    """An instant's day in the zone the window's reset is in (the home's), `""` for no instant."""
    w = spend_mod._when(stamp)
    return w.astimezone(resets.tzinfo).date().isoformat() if w else ""
