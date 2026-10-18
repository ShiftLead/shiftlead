"""The **Spend** page (design §4.5 screen 13, §4.5a *Spend page*; TD-818, built by TD-832).

*Which teams and which sessions spent the quota, over time, and what a finished entry cost*: the home's
`seats` reading (§4.4 *Spend per seat*, `sessionorc.seats.reading`) over one window, one period and one
team. This module reads the page's picks from the URL and shapes that reading for the template — the
head's words, the chart's bars, By team, Top sessions, By seat and Finished entries — and adds nothing
the reading does not hold beyond the names the page links to (a record's Focus, an entry's title).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

WINDOWS = ("day", "week", "month")
WINDOW_LABEL = {"day": "Day", "week": "Week", "month": "Month"}
INTERACTIVE = "interactive"  # sessionorc.seats' team for the records in no team: the person's own
OUTSIDE = "outside"  # and its one row for the turns no record owns
OTHER = "other"
TOKEN_KINDS = ("input", "output", "cache_read", "cache_write")  # sessionorc.spend's KINDS, a seat's `tokens`
TEAM_WORD = {INTERACTIVE: "interactive sessions", OUTSIDE: "outside shiftlead"}
TOP = 8  # Top sessions' rows until *all →*
SPEND_TTL = 60.0  # seconds a team card's **spend** figure keeps its reading (§4.5a *team card: spend*)
# a colour per team in By team's order, and per role on a team (§4.5 screen 13 *Over time*); the
# interactive sessions grey and *outside shiftlead* hatched, as the legend says
TEAM_COLOURS = ("#2563eb", "#0d9488", "#d97706", "#7c3aed", "#db2777", "#65a30d", "#0891b2", "#b45309")
ROLE_COLOURS = {"grinder": "#2563eb", "designer": "#db2777", "techlead": "#0d9488", "manager": "#d97706"}
GREY = "#9ca3af"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # fixed words, never the locale's
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")  # fmt: skip


def spend_picks(params: Mapping[str, str]) -> dict[str, Any]:
    """The page's picks from its URL (§4.5a *Spend page: Day · Week · Month, the team chips, ‹ ›*,
    *Spend · Shape*): `view` (*spend* by default, or `shape`), `window` (*day* by default), `at` (the
    period's first day, absent for the current), `team` (absent for All; `interactive` and `outside`,
    which `ao spend` reads, open All) and `top=all`. On Shape `at` and `top` drop, since it reads the
    current period, and `window=month` reads as `week`."""
    view = "shape" if params.get("view") == "shape" else "spend"
    window = str(params.get("window") or "day")
    window = window if window in WINDOWS else "day"
    team = str(params.get("team") or "")
    team = "" if team in (INTERACTIVE, OUTSIDE) else team
    if view == "shape":
        return {"view": view, "window": "week" if window == "month" else window, "at": "", "team": team, "top": False}
    return {
        "view": view,
        "window": window,
        "at": str(params.get("at") or ""),
        "team": team,
        "top": params.get("top") == "all",
    }


def spend_query(picks: Mapping[str, Any], **change: Any) -> str:
    """`/spend?…` with `change` over `picks`, the defaults left out so a link stays short."""
    p = {**picks, **change}
    q = {
        k: v
        for k, v in (
            ("view", "shape" if p.get("view") == "shape" else ""),
            ("team", p.get("team")),
            ("window", "" if p.get("window") == "day" else p.get("window")),
            ("at", p.get("at")),
            ("top", "all" if p.get("top") else ""),
        )
        if v
    }
    return "/spend" + (f"?{urlencode(q)}" if q else "")


def money(value: Any, unit: str = "≈$") -> str:
    """A figure as the page prints it: `≈$1,498` from a hundred up, `≈$92.40` below (§4.5 screen 13)."""
    v = float(value or 0.0)
    return f"{unit}{v:,.0f}" if abs(v) >= 100 else f"{unit}{v:,.2f}"


def tokens(n: Any) -> str:
    """A token count in the chip's short shape: *4.1M tok*, *812k tok*."""
    v = int(n or 0)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M tok"
    return f"{v / 1000:.0f}k tok" if v >= 1000 else f"{v} tok"


def figure(acc: Mapping[str, Any], unit: str | None = None) -> str:
    """A figure with its *unweighed* part named beside it, never in it (§4.4 *Spend per seat*):
    *unweighed · 4.1M tok* where nothing was weighed, else the figure and *+ 4.1M tok unweighed*."""
    u = unit or str(acc.get("unit") or "≈$")
    unweighed = int(acc.get("unweighed_tokens") or 0)
    if unweighed and not float(acc.get("figure") or 0.0):
        return f"unweighed · {tokens(unweighed)}"
    return money(acc.get("figure"), u) + (f" + {tokens(unweighed)} unweighed" if unweighed else "")


def team_figure(team: str, row: Mapping[str, Any] | None) -> dict[str, str] | None:
    """A team card's **spend** figure (§4.5 screen 1, §4.5a *team card: spend*; TD-832): today's figure from
    the team's `seats` row, a link to this page on the team, the week's figure and the seat that spent most
    today in its hover; `None` while the team spent nothing today."""
    if not row or not (int(row.get("turns") or 0) or float(row.get("figure") or 0.0)):
        return None
    unit = str(row.get("unit") or "≈$")
    title = f"{money(row.get('week'), unit)} this week"
    most = row.get("most") or {}
    if most.get("seat"):
        title += f" · {most['seat']} spent most today, {pct(most.get('share'))}"
    return {
        "text": f"{figure(row)} today",
        "href": spend_query({"team": team}),
        "title": title + " — the team's Spend page (API-equivalent where it is ≈$)",
    }


def pct(share: Any) -> str:
    return f"{round(float(share or 0.0) * 100)}%"


def _day(s: str) -> date:
    return date.fromisoformat(s[:10])


def _first(window: str, d: date) -> date:
    if window == "week":
        return d - timedelta(days=d.weekday())
    return d.replace(day=1) if window == "month" else d


def _step(window: str, first: date, n: int) -> date:
    if window == "month":
        m = first.year * 12 + first.month - 1 + n
        return date(m // 12, m % 12 + 1, 1)
    return first + timedelta(days=n * (7 if window == "week" else 1))


def period_label(window: str, first: date, today: date | None = None) -> str:
    """*Fri 16 Oct*, *week of 12 Oct*, *October* (§4.5a *Spend page*), the year where it is not this one."""
    year = f" {first.year}" if first.year != (today or date.today()).year else ""
    if window == "month":
        return f"{MONTHS[first.month - 1]}{year}"
    short = f"{first.day} {MONTHS[first.month - 1][:3]}{year}"
    return f"week of {short}" if window == "week" else f"{DAYS[first.weekday()]} {short}"


def bar_label(window: str, first: date) -> str:
    """A chart bar's label: *16*, *12 Oct*, *Oct*."""
    if window == "day":  # thirty bars: the day's number, its weekday on the hover
        return str(first.day)
    return f"{first.day} {MONTHS[first.month - 1][:3]}" if window == "week" else MONTHS[first.month - 1][:3]


def _team_word(t: str) -> str:
    return TEAM_WORD.get(t, t)


def _colours(names: list[str], by_role: bool) -> dict[str, str]:
    out: dict[str, str] = {}
    spare = iter(TEAM_COLOURS)
    for n in names:
        if n in (INTERACTIVE, OTHER):
            out[n] = GREY
        elif n == OUTSIDE:
            out[n] = "hatch"
        elif by_role and n in ROLE_COLOURS:
            out[n] = ROLE_COLOURS[n]
        else:
            out[n] = next(spare, GREY)
    return out


def _seat_link(seat: Mapping[str, Any], records: Mapping[str, Mapping[str, Any]]) -> str:
    """A seat's name links to its newest record's Focus, or its Transcript once it has ended (§4.5a
    *Spend page: seat name, entry id*); "" for a seat none of whose records the fleet holds."""
    known = [records[r] for r in seat.get("records") or [] if r in records]
    if not known:
        return ""
    newest = max(known, key=lambda r: str(r.get("created") or ""))
    rid = str(newest.get("id"))
    return f"/transcript/{rid}" if newest.get("state") in ("exited", "closed") else f"/focus/{rid}"


def _seat_name(seat: Mapping[str, Any]) -> str:
    """A seat as the page names it: an interactive one by name within its repo, *ao-paul · shiftlead*."""
    name = str(seat.get("seat") or "")
    if seat.get("team") == INTERACTIVE and seat.get("repo"):
        return f"{name} · {seat['repo']}"
    return name


def _unknown(seat: Mapping[str, Any], records: Mapping[str, Mapping[str, Any]], unknown: Mapping[str, Any]) -> str:
    """The reason a seat's profile's spend could not be read, or ""."""
    for r in seat.get("records") or []:
        prof = str((records.get(r) or {}).get("profile") or "")
        if prof and prof in unknown:
            return str(unknown[prof])
    return ""


def titles_of(reading: Any) -> dict[str, str]:
    """Each `TD-n`'s title as the Queue reading carries it (a card's top, its rows, a completed card),
    so a finished entry's row names what it was. Best-effort: an entry no card holds is its id alone."""
    out: dict[str, str] = {}

    def walk(v: Any) -> None:
        if isinstance(v, Mapping):
            q, t = str(v.get("qid") or v.get("ref") or ""), v.get("title")
            if q and isinstance(t, str) and t:
                out.setdefault(q.rpartition("#")[2], t)
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(reading)
    return out


def _held(e: Mapping[str, Any]) -> str:
    """How long an entry was held, first claim to done: *5h40m*, *50m*, *2d3h*."""
    try:
        a = datetime.fromisoformat(str(e.get("first_claimed")).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(e.get("done_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):  # a missing stamp, or a naive one beside an aware one
        return ""
    m = max(0, int((b - a).total_seconds() // 60))
    if m >= 1440:
        return f"{m // 1440}d{m % 1440 // 60}h"
    return f"{m // 60}h{m % 60:02d}m" if m >= 60 else f"{m}m"


def _chart(got: Mapping[str, Any], picks: Mapping[str, Any], team: str, today: date) -> dict[str, Any]:
    """The Over time chart (§4.5 screen 13): the window's bars, each stacked by team on All or by role on a
    team, its total above it, the picked one outlined, the ones before the ledger began a dashed baseline."""
    window = picks["window"]
    series = list(got.get("series") or [])
    begins = str(got.get("begins") or "")
    order: list[str] = []
    totals: dict[str, float] = {}
    for b in series:
        for k, v in (b.get("by") or {}).items():
            totals[k] = totals.get(k, 0.0) + float(v.get("figure") or 0.0)
    for k in sorted(totals, key=lambda k: (k in (INTERACTIVE, OUTSIDE, OTHER), k == OUTSIDE, -totals[k], k)):
        order.append(k)
    colours = _colours(order, bool(team))
    top = max([float(b.get("figure") or 0.0) for b in series] or [0.0]) or 1.0
    bars = []
    for b in series:
        at = str(b.get("at") or "")
        first = _day(at)
        last = _step(window, first, 1) - timedelta(days=1)
        before = not begins or last.isoformat() < begins
        whole = float(b.get("figure") or 0.0)
        segs = [
            {"key": k, "colour": colours.get(k, GREY), "h": round(float(v.get("figure") or 0.0) / whole * 100, 2)}
            for k in order
            if (v := (b.get("by") or {}).get(k)) and float(v.get("figure") or 0.0) > 0
        ]
        lines = [f"{period_label(window, first, today)}: {figure(b)}"]
        lines += [f"{_team_word(k) if not team else k}: {figure(v)}" for k, v in (b.get("by") or {}).items()]
        if b.get("partial"):
            lines.append(f"partial: the ledger begins {begins}")
        bars.append(
            {
                "at": at,
                "label": bar_label(window, first),
                "name": period_label(window, first, today),
                "h": round(whole / top * 88, 2),  # the tallest bar leaves room for its total above it
                "total": figure(b) if float(b.get("figure") or 0.0) or b.get("unweighed_tokens") else "",
                "segs": list(reversed(segs)),  # the first series at the bottom
                "picked": at == got.get("at"),
                "before": before,
                "title": "\n".join(lines),
                "href": spend_query(picks, at="" if first == _first(window, today) else at),
            }
        )
    legend = [{"key": k, "word": _team_word(k) if not team else k, "colour": colours[k]} for k in order]
    return {"bars": bars, "legend": legend, "colours": colours, "empty": not any(totals.values())}


def spend_view(
    got: Mapping[str, Any] | None,
    picks: Mapping[str, Any],
    *,
    fleet: list[Mapping[str, Any]] | None = None,
    all_teams: list[str] | None = None,
    titles: Mapping[str, str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """The `seats` reading shaped for `spend.html`: the head, the picks' links, the chart, and on All
    By team and Top sessions, on a team its line, By seat and Finished entries. `all_teams` are the
    chips' teams (By team's, which a team view's own reading does not list); `fleet` the records the
    seats' links and *spend unknown* are read from."""
    if not got or not got.get("at"):
        return {"served": False}
    today = today or date.today()
    window, team = picks["window"], picks["team"]
    records = {str(r.get("id")): r for r in fleet or []}
    unknown = got.get("unknown") or {}
    start = _day(str(got.get("at")))
    current = bool(got.get("current"))
    begins = str(got.get("begins") or "")
    unit = str(got.get("unit") or "≈$")
    prev, nxt = _step(window, start, -1), _step(window, start, 1)
    can_back = bool(begins) and prev >= _first(window, _day(begins))
    out: dict[str, Any] = {
        "served": True,
        "period": period_label(window, start, today),
        "metered": unit == "$",
        "as_of": got.get("as_of") or "",
        "begins": begins,
        "back": spend_query(picks, at=prev.isoformat()) if can_back else "",
        "forward": "" if current else spend_query(picks, at="" if _first(window, today) == nxt else nxt),
        "views": view_links(picks),
        "windows": [(w, WINDOW_LABEL[w], spend_query(picks, window=w, at="")) for w in WINDOWS],
        "chips": [("", "All", spend_query(picks, team=""))]
        + [(t, t, spend_query(picks, team=t)) for t in sorted({*(all_teams or []), *([team] if team else [])})],
        "chart": _chart(got, picks, team, today),
        "word": {"day": "day", "week": "week", "month": "month"}[window],
        "unit": unit,
    }
    whole = got.get("whole") or {}
    if not team:
        colours = out["chart"]["colours"]
        rows = []
        for t in got.get("teams") or []:
            name = str(t.get("team"))
            p = t.get("previous") or {}
            change = ""
            if "to_date" in p:
                was, now = float(p.get("to_date") or 0.0), float(t.get("figure") or 0.0)
                change = "—" if not was else ("▲ " if now >= was else "▼ ") + f"{round(abs(now - was) / was * 100)}%"
            most = t.get("most") or {}
            rows.append(
                {
                    "name": _team_word(name),
                    "href": "" if name in (INTERACTIVE, OUTSIDE) else spend_query(picks, team=name),
                    "colour": colours.get(name, GREY),
                    "figure": figure(t),
                    "share": float(t.get("share") or 0.0),
                    "pct": pct(t.get("share")),
                    "change": change,
                    "up": change.startswith("▲"),
                    "turns": int(t.get("turns") or 0),
                    "week": money(t.get("week"), str(t.get("unit") or unit)),
                    "month": money(t.get("month"), str(t.get("unit") or unit)),
                    "most": f"{most['seat']} · {pct(most.get('share'))}" if most.get("seat") else "—",
                }
            )
        top = list(got.get("top") or [])
        out |= {
            "whole": figure(whole),
            "by_team": rows,
            "top": [
                {
                    "name": _seat_name(s),
                    "href": _seat_link(s, records),
                    "team": "interactive" if s.get("team") == INTERACTIVE else str(s.get("team")),
                    "colour": colours.get(str(s.get("team")), GREY),
                    "role": str(s.get("role") or OTHER),
                    "figure": figure(s),
                    "unknown": _unknown(s, records, unknown),
                    "share": float(s.get("share") or 0.0),
                    "pct": pct(s.get("share")),
                    "turns": int(s.get("turns") or 0),
                    "past_300k": pct(s.get("past_300k_share")),
                    "title": _weights_title(s, got),
                }
                for s in (top if picks["top"] else top[:TOP])
            ],
            "top_n": len(top),
            "top_all": spend_query(picks, top=True),
            "top_fold": spend_query(picks, top=False),
        }
        return out
    mine = next((t for t in got.get("teams") or [] if t.get("team") == team), {})
    out |= {"team": team, "line": _team_line(mine, window, start, current, unit, today), "seats": [], "entries": []}
    seats = [s for s in got.get("seats") or [] if s.get("team") == team]
    total = sum(float(s.get("figure") or 0.0) for s in seats)
    out["total"] = money(total, unit)
    out["turns"] = sum(int(s.get("turns") or 0) for s in seats)
    finished = got.get("finished") or {}
    entries = sorted(got.get("entries") or [], key=lambda e: -float(e.get("figure") or 0.0))
    by_role: dict[str, list[Mapping[str, Any]]] = {}
    for s in seats:
        by_role.setdefault(str(s.get("role") or OTHER), []).append(s)
    for role, group in by_role.items():
        per = finished.get(role) or {}
        listed = [
            str(e.get("ref")) for e in entries if e.get("by_role") and max(e["by_role"], key=e["by_role"].get) == role
        ]
        per_word = f"{per['entries']} · median {money(per.get('median'), unit)}" if per.get("entries") else "—"
        for s in group:
            own = s.get("finished") or {}
            out["seats"].append(
                {
                    "name": _seat_name(s),
                    "href": _seat_link(s, records),
                    "role": role,
                    "figure": figure(s),
                    "unknown": _unknown(s, records, unknown),
                    "share": float(s.get("share") or 0.0),
                    "pct": pct(s.get("share")),
                    "turns": int(s.get("turns") or 0),
                    # the seat's own spend on each finished entry it spent on; its role's count, by the
                    # role that spent most on each entry, is the subtotal's
                    "per": f"{own['entries']} · median {money(own.get('median'), unit)}" if own.get("entries") else "—",
                    "per_title": ", ".join(str(r) for r in own.get("refs") or []),
                    "between": money(s.get("between"), unit),
                    "past_200k": pct(s.get("past_200k_share")),
                    "past_300k": pct(s.get("past_300k_share")),
                    "title": _weights_title(s, got),
                }
            )
        if len(group) > 1:
            fig = sum(float(s.get("figure") or 0.0) for s in group)

            def part(k: str, group: list[Mapping[str, Any]] = group, fig: float = fig) -> str:
                return pct(sum(float(s.get(k) or 0.0) for s in group) / fig) if fig else "0%"

            out["seats"].append(
                {
                    "subtotal": True,
                    "name": f"{role}s",
                    "figure": money(fig, unit),
                    "share": fig / total if total else 0.0,
                    "pct": pct(fig / total if total else 0.0),
                    "turns": sum(int(s.get("turns") or 0) for s in group),
                    "per": per_word,
                    "per_title": ", ".join(listed),
                    "between": money(sum(float(s.get("between") or 0.0) for s in group), unit),
                    "past_200k": part("past_200k"),
                    "past_300k": part("past_300k"),
                }
            )
    for e in entries:
        ref = str(e.get("ref"))
        out["entries"].append(
            {
                "ref": ref,
                "href": f"/queue#{ref}" if ref.startswith("TD-") else "",
                "title": (titles or {}).get(ref, ""),
                "roles": [
                    f"{r} {money(v, unit)}" for r, v in sorted((e.get("by_role") or {}).items(), key=lambda kv: -kv[1])
                ],
                "figure": money(e.get("figure"), unit),
                "turns": int(e.get("turns") or 0),
                "held": _held(e),
                "partial": bool(e.get("partial")),
            }
        )
    return out


def _weights_title(s: Mapping[str, Any], got: Mapping[str, Any]) -> str:
    """A seat's hover (§4.5a *Spend page: seat name, entry id*): what its figure holds and the weights
    it was weighed at: its tokens by kind, turns and context marks."""
    got_tokens = s.get("tokens") or {}
    bits = [
        " · ".join(f"{k.replace('_', ' ')} {tokens(got_tokens.get(k))}" for k in TOKEN_KINDS) if got_tokens else "",
        f"{int(s.get('turns') or 0):,} turns",
        f"past 200k {pct(s.get('past_200k_share'))}",
    ]
    bits = [b for b in bits if b]
    bits.append(f"past 300k {pct(s.get('past_300k_share'))}")
    if s.get("unweighed"):
        bits.append(f"{int(s['unweighed'])} turns unweighed ({tokens(s.get('unweighed_tokens'))})")
    if got.get("as_of"):
        bits.append(f"weighed at your weights as of {got['as_of']}")
    return "\n".join(bits)


def _team_line(t: Mapping[str, Any], window: str, start: date, current: bool, unit: str, today: date) -> str:
    """The head's line on one team (§4.5 screen 13 *On one team*): the period's figure (*so far* on the
    current one), the previous period's whole figure, then this week's and this month's so far where the
    period is not that one — *≈$1,498 this week (so far) · last week ≈$1,583 · October ≈$3,496*."""
    if not t:
        return f"nothing spent in the {window}"
    now_word = {"day": "today", "week": "this week", "month": MONTHS[start.month - 1]}[window]
    prev_word = {"day": "yesterday", "week": "last week", "month": MONTHS[_step("month", start, -1).month - 1]}[window]
    if not current:
        now_word, prev_word = period_label(window, start, today), period_label(window, _step(window, start, -1), today)
    u = str(t.get("unit") or unit)
    parts = [f"{figure(t, u)} {now_word}" + (" (so far)" if current else "")]
    parts.append(f"{prev_word} {money((t.get('previous') or {}).get('figure'), u)}")
    if not (window == "week" and current) and window != "month":
        parts.append(f"this week {money(t.get('week'), u)}")
    if not (window == "month" and current):
        parts.append(f"{MONTHS[today.month - 1]} {money(t.get('month'), u)}")
    return " · ".join(parts)


# -- Shape (§4.5 screen 13 *Shape*, TD-819, built by TD-835) ------------------------------------------

SHAPE_WINDOWS = ("day", "week")
# a role's bar, in the mockup's order, each class's word and colour; limited and paused hatched at its end
SHAPE_CLASSES = (
    ("working", "working", "#16a34a"),
    ("on_claim", "on its claim", "#86efac"),
    ("waiting:person", "waiting on you", "#d97706"),
    ("waiting:review", "waiting on review", "#7c3aed"),
    ("idle_with_work", "idle with work", "#2563eb"),
    ("starved", "starved", GREY),
    ("free", "free", "#ffffff"),
)
HELD = ("limited", "paused")  # one hatched segment: *limited / paused*


def view_links(picks: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """The head's **Spend · Shape** pick (§4.5a *Spend page: Spend · Shape*): Shape reads the current
    period, so its link drops `at` and `top`, and a *Month* picked on Spend opens it on *Week*."""
    window = "week" if picks.get("window") == "month" else picks.get("window")
    return [
        ("spend", "Spend", spend_query(picks, view="spend")),
        ("shape", "Shape", spend_query(picks, view="shape", at="", top=False, window=window)),
    ]


def hours(h: Any) -> str:
    """An age in hours as the Queues table draws it: *14h*, *1h10m*, *25m*; *—* for none."""
    m = round(float(h or 0) * 60)
    if not m:
        return "—"
    if m < 60:
        return f"{m}m"
    return f"{m // 60}h" + (f"{m % 60:02d}m" if m % 60 and m < 600 else "")


def _role_bar(r: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """A role's bar of hours by class and the percents under it, in `SHAPE_CLASSES`' order, limited and
    paused one hatched segment at its end."""
    shares = r.get("shares") or {}
    segs, words = [], []
    for c, word, colour in SHAPE_CLASSES:
        if share := float(shares.get(c) or 0.0):
            segs.append({"w": round(share * 100, 1), "colour": colour, "word": word})
            words.append(f"{word} {pct(share)}")
    if held := sum(float(shares.get(c) or 0.0) for c in HELD):
        segs.append({"w": round(held * 100, 1), "colour": "hatch", "word": "limited / paused"})
        words.append(f"limited / paused {pct(held)}")
    return segs, " · ".join(words)


def _role_title(r: Mapping[str, Any]) -> str:
    """A role's bar's hover: its seats and their hours by class."""
    word = {c: w for c, w, _ in SHAPE_CLASSES} | {c: c for c in HELD}
    lines = []
    for s in r.get("seats") or []:
        h = s.get("hours") or {}
        parts = [f"{word.get(c, c)} {h[c]:.1f} h" for c in (*(c for c, _, _ in SHAPE_CLASSES), *HELD) if h.get(c)]
        lines.append(f"{s.get('name')}: " + (" · ".join(parts) or "no hours"))
    return "\n".join(lines)


def _queue_row(q: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "stage": f"{q.get('stage')} ({q.get('role')})" if q.get("role") else str(q.get("stage")),
        "mean": f"{float(q.get('mean_depth') or 0):.1f}",
        "max": int(q.get("max_depth") or 0),
        "oldest": hours(q.get("oldest_hours")),
        "nonempty": pct(q.get("nonempty")),
        "backed_up": pct(q.get("backed_up")),
        "unstaffed": pct(q.get("unstaffed")),
        "past_bound": pct(q.get("past_bound")) if q.get("kind") == "review" else "",
    }


def shape_block(got: Mapping[str, Any], min_hours: float) -> dict[str, Any]:
    """One team's `shape` reading for the Shape view: its suggestions (or *nothing to suggest*, or *too
    little to read yet*), a row per role, a row per queue."""
    unit = str(got.get("unit") or "≈$")
    roles = []
    for r in got.get("roles") or []:
        segs, words = _role_bar(r)
        n = len(r.get("seats") or [])
        f = r.get("finished") or {}
        entries = int(f.get("entries") or 0)
        roles.append(
            {
                "role": r.get("role"),
                "seats": f"{n} seat" + ("" if n == 1 else "s"),
                "hours": f"{float(r.get('live_hours') or 0):.1f} h",
                "segs": segs,
                "words": words,
                "title": _role_title(r),
                "finished": f"{entries} · median {money(f.get('median'), unit)}" if entries else "—",
            }
        )
    live = float(got.get("live_hours") or 0)
    return {
        "team": got.get("team"),
        "suggestions": [str(x.get("text") or "") for x in got.get("suggestions") or []],
        "too_little": f"too little to read yet: {live:.1f} live hours of the {min_hours:g} a reading needs"
        if got.get("too_little")
        else "",
        "roles": roles,
        "queues": [_queue_row(q) for q in got.get("queues") or []],
    }


def shape_view(
    readings: list[Mapping[str, Any]], picks: Mapping[str, Any], all_teams: list[str], min_hours: float
) -> dict[str, Any]:
    """The `shape` readings shaped for `shape_part.html` (§4.5 screen 13 *Shape*): the head's picks — the
    view, **Day · Week** over the current period, the team chips — and a block per team read."""
    team = picks["team"]
    return {
        "served": True,
        "period": {"day": "today", "week": "this week"}[picks["window"]],
        "views": view_links(picks),
        "windows": [(w, WINDOW_LABEL[w], spend_query(picks, window=w)) for w in SHAPE_WINDOWS],
        "chips": [("", "All", spend_query(picks, team=""))]
        + [(t, t, spend_query(picks, team=t)) for t in sorted({*all_teams, *([team] if team else [])})],
        "classes": [(w, c) for _, w, c in SHAPE_CLASSES] + [("limited / paused", "hatch")],
        "teams": [shape_block(g, min_hours) for g in readings],
    }
