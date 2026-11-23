"""The Settings page's view (design §4.5 screen 8, §4.5a *Settings page* rows; TD-148): the one page
that **writes a setting** — a value a person moves without redefining anything, in the home's
`settings.yml`, written only through `set_settings` — and shows every other configured value with
where it lives.

Everything here is pure: the route in `app.py` hands over what the host agent answered (the
`settings` read, `usage`, `host`) and what the clients read from their own files (`profiles.yml`,
`hosts.yml`, the org's definitions, each registered repo's `.shiftlead.yml`), and gets back the
sections the template draws. Nothing here reads `settings.yml`: on a node the agent's read serves the
replica and the writes forward to the home (§4.4a *Settings, replicated*), which only the agent knows.

A value a file does not set is drawn with its default and marked *default*; every file card carries
the *i* mark's words — the file's path, when it is re-read, who edits it — from `FILES`, which is
`ao settings --where`'s table in the page's words.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from sessionorc import hosts, paths, work
from sessionorc import settings as settings_mod
from sessionorc import spend as spend_mod
from sessionorc.models import tokens_short
from shiftlead import profiles as profiles_mod
from shiftlead import repoconfig, teamrun

from . import uiconf
from .cards import swept_words
from .common import USAGE_UNKNOWN, _age, card_path, usage_clock, usage_read

# The *i* mark of each file card (§4.5a *Settings page: read-only values and the i mark*): when the
# file is re-read and who edits it. A host's name, its `home:` and its identity mode are read once,
# at the agent's start, so the hosts card says *restart the host agent to apply* for those three.
FILES = {
    "settings": ("every tick", "written only through set_settings — this page, ao gate, ao team — never by hand"),
    "hosts": ("name, home: and identity at the host agent's start — restart the host agent to apply; the rest on use",
              "by hand"),
    "profiles": ("on every use", "by hand"),
    "org": ("by the clients on every use; never the host agent", "by hand"),
    "repo": ("by the clients on every use; promote: alone also by the host agent at the home, every five minutes",
             "by PR"),
}  # fmt: skip

# The browser's own keys (§4.5a *Settings page: You*, *this browser*): drawn with what they hold,
# each beside the control that already sets it; **Reset this browser** clears every `ao.*` key.
BROWSER_KEYS = (
    ("theme", "theme", "the ◐ toggle in the top bar"),
    ("inboxfyi", "Inbox: FYI open", "the section's own fold"),
    ("inboxanswered", "Inbox: Answered open", "the section's own fold"),
)


# a price's kind as the metered card's badge says it (§4.5a: *$3 in / $15 out per M*)
PRICE_WORDS = {"input": "in", "output": "out", "cache_read": "cache read", "cache_write": "cache write"}


def _is_num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def reserve_text(r: Any) -> str:
    """A reserve as the field takes it back: `30`, `10/day`, or "" for none (`ao gate`'s forms)."""
    if isinstance(r, dict) and isinstance(r.get("per_day"), int):
        return f"{r['per_day']}/day"
    return "" if r is None else str(r)


def parse_reserve_text(text: Any) -> int | dict[str, int] | str | None:
    """What a reserve field sends: `30`, `10/day`, empty to clear — `ao gate`'s forms, the same
    refusal — or a metered card's amount, `$5` or `20M tok`, which goes as written for the agent to
    check against the profile's billing. Raises ValueError with the words the field shows in place."""
    t = str(text if text is not None else "").strip()
    if not t:
        return None
    if t.startswith("$") or t.endswith("tok"):
        return t
    per_day = t.endswith("/day")
    n = t.removesuffix("/day").strip()
    if not n.isdigit():
        raise ValueError(f"a reserve is a whole percent (30) or a percent per day (10/day), not {t!r}")
    return {"per_day": int(n)} if per_day else int(n)


def _when(iso: Any) -> datetime | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def spend_text(w: Mapping[str, Any] | None, unit: str = "") -> str:
    """A metered window's spend as the chip draws it (§4.5a): *spent $3.20 · 64% · resets 00:00*, in
    tokens where the amount is tokens or nothing was priced; *no reading yet* before one."""
    spent = (w or {}).get("spent")
    if not isinstance(spent, dict):
        return "no reading yet"
    cost = spent.get("cost")
    got = f"{tokens_short(int(spent.get('total') or 0))} tok" if unit == "tok" or cost is None else f"${cost:,.2f}"
    out = f"spent {got}"
    if isinstance(w.get("pct"), int):
        out += f" · {w['pct']}%"
    if resets := _when(w.get("resets")):
        out += f" · resets {resets.astimezone():%H:%M}"
    return out


def line_text(row: Mapping[str, Any] | None, now: datetime | None = None) -> str:
    """The line a reserve makes today, as `ao gate` prints it and the chip will draw it: *→ line
    70%*, *→ line 60% · 4 days left · moves Thu 07:00*, or why there is none; past `usage.max_age`,
    the projection the gate reads, *· projected 96%*, or *· no rate to project by*."""
    if not row:
        return "no line"
    if row.get("unknown") == "reset":
        return "unknown since its reset — pauses nothing until a new reading"
    if row.get("line") is None:
        return "no line — the window reports no reset"
    out = f"→ line {row['line']:g}%"
    if isinstance(row.get("projected"), dict) and _is_num(row.get("pct")):
        # past `usage.max_age` (§6 *A reading the gate can no longer trust*, TD-233): what the gate reads
        out += f" · projected {row['pct']:g}%"
    elif row.get("unknown") == "rate":
        out += " · no rate to project by"
    r = row.get("reserve")
    resets = _when(row.get("resets"))
    if isinstance(r, dict) and resets:
        now = now or datetime.now(UTC)
        left = max(1, math.ceil((resets - now) / timedelta(days=1)))
        out += f" · {left} day{'s' if left != 1 else ''} left"
    nxt = _when(row.get("next"))
    if nxt:
        out += f" · moves {nxt.astimezone():%a %H:%M}"
    return out


def reading_age(w: Mapping[str, Any], read: Mapping[str, Any] | None, now: datetime) -> str:
    """A window's reading as the chip's hover gives it (§4.5a *Settings page: Usage*, *The reading's
    age*; TD-233 slice 1): *week 88% · read 6h ago, asked of the endpoint*; past its reset or past
    `USAGE_UNKNOWN`, *unknown since 22:21 (was 88%)*. Empty for a reading with no time on it."""
    pct = f"{w['pct']:g}%" if _is_num(w.get("pct")) else "?"
    resets = _when(w.get("resets"))
    if resets is not None and resets <= now:
        return f"unknown since its reset at {usage_clock(resets, now)} (was {pct})"
    if read is None:
        return ""
    if read["secs"] > USAGE_UNKNOWN:
        return f"unknown since {read['clock']} (was {pct}), {read['source']}"
    return f"{pct} · read {read['age']} ago, {read['source']}"


def _usage_key(p: profiles_mod.Profile) -> str:
    """The usage key `<adapter>:<account>` a profile's reserve is kept under (§6 *Names*, TD-1581)."""
    return f"{p.adapter}:{p.account or p.name or 'default'}"


def usage_cards(
    profiles: Mapping[str, profiles_mod.Profile],
    accounts: Mapping[str, Any] | None,
    usage: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """**Usage** (§4.5 screen 8, §4.5a *Settings page: Usage*; §6 *A reserve is the account's*, TD-1610): a
    card per account — the home's `profiles.yml`'s, and each the `gate` reply's `accounts` names (a node's once
    it has reported) — its badge listing the profiles on it, a row per window label its reading reports, each
    with the account's reserve as the field takes it, the line it makes today, and what the page's preview
    needs to draw a new line before the press lands (`resets`). An account with no reading yet draws the
    labels it has reserves for, and says the labels are not checked; one with a reading draws a reserve on a
    label the reading lacks as a `stale` row, *not reported*, which holds no field and which the card's Save
    clears (TD-1680); one absent from `usage_gate:` shows
    empty fields. A **metered** account's card (§4.2a) carries the home's three windows, each taking an
    amount (`$5`, `20M tok`), with the account's spend beside it. An account whose profiles disagree on
    billing (`mixed`) takes no reserve and says so."""
    now = now or datetime.now(UTC)
    accounts, usage = accounts or {}, usage or {}
    in_file: dict[str, list[str]] = {}
    for name, p in profiles.items():
        in_file.setdefault(_usage_key(p), []).append(name)
    cards = []
    for key in sorted({*in_file, *(k for k, v in accounts.items() if isinstance(v, dict))}):
        a = accounts.get(key) if isinstance(accounts.get(key), dict) else {}
        names = sorted({*(in_file.get(key) or []), *(str(n) for n in a.get("profiles") or [])})
        mine = [profiles[n] for n in names if n in profiles]
        bills = {p.billing for p in mine}
        billing = str(a.get("billing") or ("mixed" if len(bills) > 1 else next(iter(bills), "subscription")))
        # the account's one reading: the freshest of its profiles' copies
        got = [usage[n] for n in names if isinstance(usage.get(n), dict)]
        reading = max(got, key=lambda u: str(u.get("fetched") or ""), default=None)
        tool = str((reading or {}).get("tool") or key.split(":", 1)[0])
        windows = [w for w in (reading or {}).get("windows") or [] if isinstance(w, dict) and w.get("label")]
        rows_by = {str(r.get("label")): r for r in a.get("windows") or [] if isinstance(r, dict)}
        badge = f"{', '.join(n or '(default)' for n in names) or 'no profile here'} · {tool}"
        card: dict[str, Any] = {"account": key, "profiles": names, "metered": billing == "metered", "rows": []}
        if billing == "mixed":
            each = ", ".join(f"{p or '(default)'} {b}" for p, b in (a.get("billings") or {}).items()) or ", ".join(
                f"{p.name or '(default)'} {p.billing}" for p in mine
            )
            cards.append(card | {"badge": badge, "mixed": each, "unchecked": False})
            continue
        if billing == "metered":
            prices = next((p.prices for p in mine if p.prices), {})
            words = " / ".join(f"${v:g} {PRICE_WORDS.get(k, k)}" for k, v in prices.items())
            badge += f" · metered · {words + ' per M' if words else 'tokens'}"
            amounts = a.get("amounts") or {}
            # the home's three windows, each an amount (§4.5a *Settings page: Usage*): the account's spend
            # beside it, as the chip draws it
            by_label = {str(w["label"]): w for w in windows}
            for label in spend_mod.LABELS:
                value = str(amounts.get(label) or "")
                card["rows"].append(
                    {
                        "label": label,
                        "value": value,
                        "line": spend_text(by_label.get(label), "tok" if value.endswith("tok") else ""),
                        "resets": str((by_label.get(label) or {}).get("resets") or ""),
                        "pct": None,
                    }
                )
            cards.append(card | {"badge": badge, "unchecked": False})
            continue
        reserves = a.get("reserves") or {}
        read = usage_read(reading, now)
        for w in windows:
            label = str(w["label"])
            card["rows"].append(
                {
                    "label": label,
                    "value": reserve_text(reserves.get(label)),
                    "line": line_text(rows_by.get(label), now) if label in reserves else "no line",
                    "resets": str(w.get("resets") or ""),
                    "pct": w.get("pct") if _is_num(w.get("pct")) else None,
                    "age": reading_age(w, read, now),
                }
            )
        reported = [str(w["label"]) for w in windows]
        for label, r in reserves.items():  # a reserve on a label the reading does not show
            if label in reported:
                continue
            row = {"label": label, "value": reserve_text(r), "line": "no reading yet", "resets": "", "pct": None}
            if windows:  # a reading that lacks the window: no field, and the card's Save clears it (TD-1680)
                row |= {"line": f"not reported: {key} reports {', '.join(reported)}", "stale": True}
            card["rows"].append(row)
        cards.append(card | {"badge": badge, "unchecked": not windows})
    return cards


WEIGHT_KINDS = ("input", "output", "cache_read", "cache_write")  # `settings.WEIGHT_KINDS`, in the card's order


def _price(v: Any) -> str:
    """A price as its field shows it, every digit kept so a Save writes it back unchanged: `4`, `0.25`; ""
    for none."""
    if not _is_num(v):
        return ""
    text = repr(float(v))
    return text[:-2] if text.endswith(".0") else text


def weights_card(weights: Mapping[str, Any] | None) -> dict[str, Any]:
    """§4.5a *Settings page: Usage* **weights** (TD-818, built by TD-832): the weights the seat pass reads
    (`settings`' `spend.weights`, the design's default under what the person set), a row per model prefix
    with its four prices, and the *as of* date. `default` marks a row the design ships at its own prices."""
    from sessionorc.seats import WEIGHTS  # the default lives with the ledger that reads it

    got = dict(weights or WEIGHTS)
    rows = []
    for key, w in got.items():
        if key == "as_of" or not isinstance(w, Mapping):
            continue
        shipped = WEIGHTS.get(key)
        rows.append(
            {
                "model": str(key),
                **{k: _price(w.get(k)) for k in WEIGHT_KINDS},
                "default": isinstance(shipped, Mapping)
                and {k: float(v) for k, v in shipped.items()} == {k: float(v) for k, v in w.items()},
                "shipped": isinstance(shipped, Mapping),
            }
        )
    return {"as_of": str(got.get("as_of") or ""), "rows": rows}


def weights_body(rows: Any, as_of: Any = "") -> dict[str, Any]:
    """The card's rows as `set_settings`' `spend` (§5 `spend.weights`): each row that is not the design's own
    at its own prices — a new model, or a shipped one repriced — and `as_of` where it is not the default's;
    `{}` when nothing differs, so the design's default holds. A row removed that the design ships comes back
    at its default, since the person's keys replace the default's one by one and never drop one. An empty
    price is left out (that kind then weighs at the row's input); a row with none, a model named twice or a
    price that is not a number is refused, in words the card shows."""
    from sessionorc.seats import WEIGHTS

    if not isinstance(rows, list):
        raise ValueError("weights: send {rows: [{model, input, output, cache_read, cache_write}], as_of}")
    out: dict[str, Any] = {}
    seen: set[str] = set()
    for r in rows:
        model = str((r or {}).get("model") or "").strip() if isinstance(r, Mapping) else ""
        if not model:
            raise ValueError("a weights row needs its model prefix, claude-opus or claude-opus-5")
        if model in seen:
            raise ValueError(f"{model} is named twice: one row per model prefix")
        seen.add(model)
        prices: dict[str, float] = {}
        for k in WEIGHT_KINDS:
            text = str(r.get(k) if r.get(k) is not None else "").strip().lstrip("$")
            if not text:
                continue
            try:
                v = float(text)
            except ValueError:
                raise ValueError(f"{model} {k.replace('_', ' ')}: $ per million tokens, not {text!r}") from None
            if not math.isfinite(v) or v < 0:
                raise ValueError(f"{model} {k.replace('_', ' ')}: $ per million tokens, at or above 0, not {text}")
            prices[k] = v
        if "input" not in prices:  # a kind left out weighs at the input, so the input is the one a row needs
            raise ValueError(f"{model}: give it at least its input price")
        shipped = WEIGHTS.get(model)
        if isinstance(shipped, Mapping) and {k: float(v) for k, v in shipped.items()} == prices:
            continue
        out[model] = prices
    day = str(as_of or "").strip()
    if day and day != WEIGHTS["as_of"]:
        try:
            out = {"as_of": datetime.fromisoformat(day).date().isoformat(), **out}
        except ValueError:
            raise ValueError(f"as of is a date, 2026-10-17, not {day!r}") from None
    return {"weights": out} if out else {}


def balance_card(
    name: str,
    bal: Any,
    sessions: list[dict[str, Any]] | None,
    repos: Mapping[str, Any] | None,
    host: Mapping[str, Any] | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    """**balance** on a team's card (§4.5a *Settings page: Teams*, §6 *Balance*, TD-239): the switch,
    the three fields as `settings.yml` holds them — a line not drawn is an empty field — and under
    them the repo's numbers as they read now, in `ao team balance`'s lines, so a line is set against
    what it would have done today. `was` is the value as the form would send it, which is how the
    page tells a Save that moved it from one that did not. `mark` is the card's **over its line**
    note while the home's mark stands — from the `repos` reading and the home's `host` read, whose
    `balance` carries a mark with no `repo` too (TD-330). `root` is a switched team's repo (`""`, one with no
    reading): its numbers are that repo's, and it has no reader's-queue line (§4.9d *Holds new work*)."""
    bal = {k: bal[k] for k in settings_mod.BALANCE_KEYS if k in bal} if isinstance(bal, Mapping) else {}
    if not bal.get("review") or root is not None:
        bal.pop("review", None)  # off is no key, as the file reads
    readings = {str(k): v for k, v in (repos or {}).items() if isinstance(v, dict)}
    now = teamrun.balance_now(name, list(sessions or []), readings, root=root)
    mark = teamrun.balance_marks(readings, dict(host or {})).get(name) if bal else None
    rows = [line.strip() for line in teamrun.balance_rows(bal, now)]
    return {
        "on": bool(bal),
        "prs": str(bal.get("prs") or ""),
        "oldest": str(bal.get("oldest") or ""),
        "review": bool(bal.get("review")),
        "was": json.dumps(bal or None, separators=(",", ":")),
        "live": bool(now["members"]),
        "now": rows[:2] if root is not None else rows,
        "mark": teamrun.balance_note(mark) if mark else "",
    }


def team_cards(
    defs: Mapping[str, Any],
    teams: Mapping[str, Any] | None,
    now: datetime | None = None,
    sessions: list[dict[str, Any]] | None = None,
    repos: Mapping[str, Any] | None = None,
    flows: Mapping[str, list[dict[str, Any]]] | None = None,
    host: Mapping[str, Any] | None = None,
    profiles: Mapping[str, Any] | None = None,
    default: str = "",
    labels: Mapping[str, Any] | None = None,
    roots: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """**Teams** (§4.5 screen 8): a card per team the org defines, with the settings a person
    moves — the schedule (`schedule_card`, from `profiles.yml`'s `profiles` and `default` and the
    `settings` read's `labels`), the stop time, the reserve priority,
    **when work appears** (§6 rule 8) and **balance** (`balance_card`, read against `sessions` and
    the `repos` reading) — as `settings.yml` holds them. The stop time is drawn in the
    reader's clock, as `ao team until` takes it; one already past says so. `on_work` is the picker's
    value, `start` while the key is absent (`ON_WORK_DEFAULT`, TD-457), which `on_work_set` tells apart
    (*start the team* is then marked *default*). `flows` is each team's `teams.flow_rows`, for the
    **flow** pick (§4.9c): the current one is `flow`, its strip `flow_strip`. `roots` is each switched team's
    repo root, which its balance numbers are read from (`balance_card`)."""
    now = now or datetime.now(UTC)
    out = []
    for name, d in defs.items():
        t = (teams or {}).get(name) or {}
        until = _when(t.get("until"))
        out.append(
            {
                "name": name,
                "source": str(getattr(d, "source", "") or ""),
                "until": until.astimezone().strftime("%a %d %b %H:%M") if until else "",
                "passed": bool(until and until <= now),
                "reserve": t.get("reserve") if isinstance(t.get("reserve"), int) else 0,
                "schedule": schedule_card(name, t.get("schedule"), profiles or {}, default, labels),
                "on_work": t.get("on_work")
                if t.get("on_work") in settings_mod.ON_WORK
                else settings_mod.ON_WORK_DEFAULT,
                "on_work_set": t.get("on_work") in settings_mod.ON_WORK,
                "balance": balance_card(name, t.get("balance"), sessions, repos, host, (roots or {}).get(name)),
                "flows": (rows := list((flows or {}).get(name) or [])),
                "flow": next((r["name"] for r in rows if r.get("current")), ""),
                "flow_strip": next((r.get("strip") or "" for r in rows if r.get("current")), ""),
            }
        )
    return out


NODE_LOGINS = "a node's logins are not read here"  # why a node's team has no schedule at a reset (§4.9d)
NODE_NOTE = "not checked: a node's logins are not read here"  # `team_show`'s words, read to know a node's team


def team_tabs(defs: Mapping[str, Any], switched: Mapping[str, str] | None = None) -> list[str]:
    """The team page's tabs (§4.9d *The page*): by repo and then by name, both compared case-folded. `switched` is the
    settings' switched teams, `{team: repo}`, whose repo stands over a definition's."""
    held = switched or {}

    def order(n: str) -> tuple[str, str]:
        return str(held.get(n) or getattr(defs.get(n), "repo", "") or "").casefold(), n.casefold()

    return sorted({*defs, *held}, key=order)


def repo_teams(defs: Mapping[str, Any], switched: Mapping[str, str] | None) -> dict[str, list[str]]:
    """`{repo: its teams}`, by name: a definition's and the settings', whose repo stands over a definition's."""
    held = switched or {}
    out: dict[str, list[str]] = {}
    for n in sorted({*defs, *held}, key=str.casefold):
        repo = str(held.get(n) or getattr(defs.get(n), "repo", "") or "")
        if repo:
            out.setdefault(repo, []).append(n)
    return out


def declared_line(names: Iterable[str], declared: Iterable[str]) -> str:
    """What a repo's ledger writes on its `Fields:` line to declare `names` (§4.4 *The move from one team to two*): the
    names it already declares first, in their order."""
    have = [str(d) for d in declared]
    known = {d.casefold() for d in have}
    return "Team = " + " | ".join([*have, *(n for n in names if n.casefold() not in known)])


def undeclared(team: str, repo: str, teams: Mapping[str, list[str]], readings: Mapping[str, Any]) -> str | None:
    """The line a repo's ledger still needs while it has two or more teams and does not declare `team` (§4.9d *New
    team*, TD-2063), or None. A ledger not read marks nothing, as a Start on it passes."""
    names = teams.get(repo) or []
    r = next((v for v in readings.values() if isinstance(v, Mapping) and v.get("name") == repo), None)
    led = (r or {}).get("ledger")
    if len(names) < 2 or not isinstance(led, Mapping) or "error" in led or "declared_teams" not in led:
        return None
    declared = [str(t) for t in led.get("declared_teams") or ()]
    return None if team.casefold() in {d.casefold() for d in declared} else declared_line(names, declared)


def new_team_form(
    org: Any, teams: Mapping[str, list[str]], names: Iterable[str], flows: Iterable[str], here: str
) -> dict[str, Any]:
    """What **+ New team**'s form offers (§4.9d *New team*, TD-2063): the registered checkouts, each repo's hosts (the
    home, then the nodes the org lists it on) and its teams, and the flows with the built-in `build` first."""
    repos = sorted({str(n) for n in names}, key=str.casefold)
    hosts_of = {r: [here, *sorted(h for h in (org.checkouts.get(r) or {}) if h != here)] for r in repos}
    listed = sorted({str(f) for f in flows}, key=lambda f: (f != "build", f.casefold()))
    return {"repos": repos, "hosts": hosts_of, "teams": {r: list(teams.get(r) or ()) for r in repos}, "flows": listed}


def _switched_word(head: Mapping[str, Any]) -> str:
    """The head's state (§4.9d *The page*). *n finishing* and a wound-down team's who wait on the started mark
    (TD-2065)."""
    if head.get("word") == "running":
        n, most = head.get("sessions") or 0, head.get("most")
        return f"Running · {n} of {most} sessions" if most else f"Running · {n} session{'' if n == 1 else 's'}"
    return {"person": "Stopped by you", "until": "Stopped at its stop time"}.get(str(head.get("by") or ""), "Stopped")


def _pill(e: Mapping[str, Any], repo: Any, now: datetime) -> dict[str, Any]:
    """A record on the route map (§4.9d): filled with how long it has been held, or dashed, waiting on the person, with
    how long ago the stage asked. A time the record does not hold is left out, never guessed."""
    waits = e.get("waits")
    if waits == "person":
        ago = _age(e.get("asked_at"), now)
        word = f"asked {ago} ago" if ago else "waits on you"
    else:
        held = {"merging": "merging", "parts": "waits for its parts"}.get(str(waits))
        word = " · ".join(x for x in (held, _age(e.get("since"), now)) if x)
    tid = str(e.get("id") or "")
    return {
        "id": tid,
        "href": card_path(f"{repo}#{tid}"),
        "dashed": waits == "person",
        "word": word,
        "holder": e.get("holder"),
        "stage": e.get("stage"),
    }


def _on_login(model: Any, now: Mapping[str, Any] | None, shown: Mapping[str, str]) -> str:
    """A stop's model and the login a session would start on now (§4.9d): *opus on claude-paul*."""
    got = now or {}
    state, login = got.get("state"), str(got.get("login") or "")
    if state == "usable":
        return f"{model} on {shown.get(login) or login.partition(':')[2] or login}"
    word = {"waits": "waits for a usable login", "none": "no login offers it", "not_read": "not read here"}.get(
        str(state)
    )
    return f"{model} · {word}" if word else str(model or "")


def _route(flow: Mapping[str, Any], stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The map's lines with their stops. A stage on two lines keeps its number and pills at its first stop, so a record
    is drawn once."""
    by_key = {s.get("key"): s for s in stages}
    seen: set[Any] = set()
    out = []
    for line in flow.get("lines") or ():
        stops = []
        for key in line.get("stops") or ():
            if key in by_key:
                stops.append({**by_key[key], "repeat": key in seen})
                seen.add(key)
        back = by_key.get(line.get("back_to")) or {}
        end = {"merged": "merged", "you": "you", "back": f"back to {back.get('name')}"}.get(str(line.get("end")))
        out.append(
            {"head": line.get("head"), "stops": stops, "end": end or ("" if line.get("other") else "no next stop")}
        )
    return out


def _window_labels(account: Mapping[str, Any] | None) -> list[str]:
    """The windows an account's reading reports, for the **Starts** row; none where it has no reading."""
    g = (account or {}).get("gauges")
    if not isinstance(g, Mapping) or g.get("unread"):
        return []
    return [str(w.get("label")) for w in g.get("windows") or () if isinstance(w, Mapping)]


def switched_team(show: Mapping[str, Any], tools: Mapping[str, Any] | None) -> dict[str, Any]:
    """What the team page draws of a switched team (§4.9d *The page*, TD-2060), from `team_show` and the host's `tools`
    read: the head, the login rows with each account's gauge, the logins that can be added, and the numbers."""
    cards = list((tools or {}).get("tools") or ())
    accounts = {str(a.get("key")): a for c in cards for a in c.get("accounts") or ()}
    known = {f"{c.get('adapter')}:{lg.get('name')}": lg for c in cards for lg in c.get("logins") or ()}
    flow = show.get("flow") or {}
    on_node = any(lg.get("state") == "not_read" for lg in show.get("logins") or ()) or show.get("note") == NODE_NOTE
    rows = []
    for lg in show.get("logins") or ():
        account = accounts.get(str(lg.get("account")))
        held = known.get(str(lg.get("login"))) or {}
        rows.append(
            {
                **lg,
                "shown": lg.get("label") or lg.get("name"),
                "metered": (held.get("settings") or {}).get("billing") == "metered",
                "gauge": gauge_view(account.get("gauges"), account.get("billing")) if account else None,
                "windows": _window_labels(account),
            }
        )
    listed = {str(lg.get("login")) for lg in rows}
    at = datetime.now(UTC)
    repo = show.get("repo")
    shown = {str(lg.get("login")): str(lg.get("shown") or "") for lg in rows}
    stages = [
        {
            **s,
            "number": s.get("at_once") or 1,
            "on_login": _on_login(s.get("model"), s.get("now"), shown),
            "pills": [_pill(e, repo, at) for e in s.get("entries") or ()],
        }
        for s in flow.get("stages") or ()
    ]
    most = (show.get("head") or {}).get("most")
    return {
        "team": show.get("team"),
        "title": show.get("label") or show.get("team"),
        "name_beside": show.get("team") if show.get("label") else None,
        "label": show.get("label") or "",
        "repo": show.get("repo"),
        "host": show.get("host"),
        "version": show.get("version"),
        "word": _switched_word(show.get("head") or {}),
        "running": (show.get("head") or {}).get("word") == "running",
        "cannot_run": show.get("cannot_run"),
        "note": show.get("note"),
        "unread": show.get("unread"),
        "flow": flow.get("name"),
        "flow_read": bool(flow.get("read")),
        "on_node": on_node,
        "logins": rows,
        "order": [str(lg.get("login")) for lg in rows],
        "can_add": [
            {"key": k, "shown": f"{lg.get('label') or lg.get('name')} ({k.partition(':')[0]})"}
            for k, lg in known.items()
            if k not in listed
        ],
        "stages": stages,
        "lines": _route(flow, stages),
        "gone": [_pill(e, repo, at) for e in flow.get("gone") or ()],
        "unplaced": [_pill(e, repo, at) for e in flow.get("unplaced") or ()],
        "audits": [{**a, "on_login": _on_login(a.get("model"), a.get("now"), shown)} for a in show.get("audits") or ()],
        "no_such_stage": flow.get("no_such_stage") or {},
        "most": most,
        "sum": sum(s["number"] for s in stages),
        "held_back": [s["name"] for s in stages if most and s["number"] > most],
    }


def team_head(name: str, d: Any, group: Mapping[str, Any] | None, host: str) -> dict[str, Any]:
    """The head of a team that is not switched (§4.9d *Before and after the cut-over*): the state word the Sessions
    card shows for the team, and its counts from the team's live members as that card counts them."""
    g = group or {}
    if g.get("concluded"):
        word = "concluded"
    elif g.get("live"):
        word = "running"
    elif g.get("wound_down"):
        word = "wound down"
    else:
        word = "stopped"
    return {
        "repo": str(getattr(d, "repo", "") or g.get("repo") or ""),
        "on": str(getattr(d, "host", "") or host),
        "word": word,
        "running": word == "running",
        "counts": list(g.get("counts") or []) if g.get("live") else [],
    }


# why the **schedule** field offers no metered profile (§4.5a *Settings page: Teams*, §6 *Schedule*)
SCHEDULE_METERED = (
    "a metered profile has no account reading to fall back on, so with no session running under it"
    " a wound-down team's rule has no reset to wait for"
)


def schedule_card(
    team: str,
    rule: Any,
    profiles: Mapping[str, Any],
    default: str = "",
    labels: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The team card's **schedule** row (§4.5a *Settings page: Teams*, §6 *Schedule*, TD-1346): a switch,
    a **profile** pick of every profile `profiles.yml` defines, a metered one disabled with the reason,
    and a **window** pick of the labels the `settings` read answered for that profile (`labels`: the
    reading the gate judges it by, the windows `set_settings` checks a label against), or a text field
    where it has none. A standing rule is drawn as it stands: a profile no longer defined, or a label its
    reading lacks, as its own option marked *(not reported)*; one on a metered profile keeps that profile
    selected and its label in a fixed option. Off with no rule, the picks hold what turning on starts
    at: the default profile (else, that one metered, the first offered) and its first label. `was` is
    the drawn rule as the page's JSON compares it, `labels` what a profile pick redraws from, and
    `starts` the team card's *starts* words, or *no schedule*."""
    got = labels if isinstance(labels, Mapping) else {}
    metered = {n for n, p in profiles.items() if getattr(p, "billing", "") == "metered"}
    offered = [n for n in profiles if n not in metered]
    readings = {
        n: [str(x) for x in got.get(n) or [] if isinstance(x, str)] for n in offered if isinstance(got.get(n), list)
    }
    standing = rule if isinstance(rule, dict) and rule.get("profile") and "window" in rule else None
    if standing:
        profile, window = str(standing["profile"]), str(standing.get("window") or "")
    else:
        profile = default if default in offered else (offered[0] if offered else "")
        window = (readings.get(profile) or [""])[0]
    options = [
        {"name": n, "disabled": n in metered, "title": SCHEDULE_METERED if n in metered else "", "mark": ""}
        for n in profiles
    ]
    if profile and profile not in profiles:
        options.append({"name": profile, "disabled": False, "title": "", "mark": " (not reported)"})
    windows: list[dict[str, str]] = []
    note, fixed = "", False
    if profile in metered:  # a standing rule's own label, never from `labels` (§4.5a)
        windows, fixed = [{"label": window, "mark": ""}], True
    elif profile in profiles and readings.get(profile):
        windows = [{"label": w, "mark": ""} for w in readings[profile]]
        if window and window not in readings[profile]:
            windows.append({"label": window, "mark": " (not reported)"})
    elif profile in profiles:
        note = f"no reading of {profile} yet — the label is not checked"
    was = (
        json.dumps({"start": "reset", "profile": profile, "window": window}, separators=(",", ":"), ensure_ascii=False)
        if standing
        else "null"
    )
    return {
        "on": bool(standing),
        "can": bool(offered) or bool(standing),
        "why": "" if offered else SCHEDULE_METERED,
        "profile": profile,
        "window": window,
        "options": options,
        "windows": windows,
        "fixed": fixed,
        "note": note,
        "was": was,
        "labels": json.dumps(readings, separators=(",", ":")),
        "starts": (uiconf.team_starts(team) or "starts at the reset · no reading yet") if standing else "no schedule",
    }


def switched_schedule(rule: Any, sw: Mapping[str, Any]) -> dict[str, Any]:
    """A switched team's **Starts** row (§4.9d *When it runs*, TD-2091), in `schedule_card`'s shape, from the team's
    login rows: a pick of its logins, a metered one disabled, and the windows its account reports. A rule whose login
    left the list reads the first, and the row says so; an empty list, or a metered first login, starts nothing and
    the row says why. A team on a node cannot set one, since its logins are not read here."""
    rows = list(sw.get("logins") or ())
    shown = {str(r.get("login")): str(r.get("shown") or r.get("name")) for r in rows}
    metered = {str(r.get("login")) for r in rows if r.get("metered")}
    offered = [k for k in shown if k not in metered]
    readings = {str(r.get("login")): list(r.get("windows") or ()) for r in rows if r.get("windows")}
    standing = rule if isinstance(rule, dict) and "window" in rule else None
    named = str(standing.get("login") or "") if standing else ""
    if standing:
        login = named if named in shown else next(iter(shown), "")
        window = str(standing.get("window") or "")
    else:
        login = offered[0] if offered else ""
        # the week's with no reading yet: the row saves as it is ticked, and a rule needs its window (§4.9d)
        window = (readings.get(login) or ["week"])[0]
    said = ""
    if standing and not login:
        said = "the schedule names no login and starts nothing: the team's login list is empty"
    elif standing and login in metered:
        said = f"{shown[login]} is metered, so the schedule starts nothing"
    elif standing and named and named != login:
        said = f"the schedule now reads {shown[login]}"
    windows = [{"label": w, "mark": ""} for w in readings.get(login) or ()]
    if windows and window and window not in readings[login]:
        windows.append({"label": window, "mark": " (not reported)"})
    why = NODE_LOGINS if sw.get("on_node") else "" if offered else SCHEDULE_METERED
    was = {"start": "reset", "login": login, "window": window}
    return {
        "who": "login",
        "on": bool(standing),
        "can": bool(standing) or (bool(offered) and not sw.get("on_node")),  # a standing rule can always be cleared
        "why": why,
        "profile": login,
        "window": window,
        "options": [
            {
                "name": k,
                "shown": v,
                "disabled": k in metered,
                "title": SCHEDULE_METERED if k in metered else "",
                "mark": "",
            }
            for k, v in shown.items()
        ],
        "windows": windows,
        "fixed": False,
        "note": f"no reading of {shown[login]} yet — the label is not checked" if login and not windows else "",
        "was": json.dumps(was, separators=(",", ":"), ensure_ascii=False) if standing else "null",
        "labels": json.dumps(readings, separators=(",", ":")),
        "starts": said
        or (why if sw.get("on_node") else "")
        or (f"at the reset of {shown[login]}'s {window}" if standing else "no schedule"),
    }


def _row(key: str, value: Any, default: Any = None, *, is_default: bool | None = None) -> dict[str, Any]:
    """One read-only value: its key, its text, and whether the file left it to its default."""
    if is_default is None:
        is_default = value == default
    if isinstance(value, list | tuple):
        text = ", ".join(str(v) for v in value) or "none"
    elif isinstance(value, dict):
        text = ", ".join(f"{k} {v}" for k, v in value.items()) or "none"
    elif value is None or value == "":
        text = "none"
    else:
        text = str(value)
    return {"key": key, "value": text, "default": bool(is_default)}


def pull_reading(reading: Mapping[str, Any] | None, now: datetime | None = None) -> str:
    """The last pull pass's reading beside the Repos card's **pull** switch (§4.5a, §6 *Pull*,
    TD-263): *current*, *last pulled <age> ago · n commits*, *waiting: <name> is mid-turn*,
    *refused: <why>*, *off* — "" before any pass has reached the checkout."""
    r = reading or {}
    outcome = r.get("outcome")
    if outcome == "pulled":
        n = r.get("commits")
        age = _age(r.get("at"), now or datetime.now(UTC))
        count = f" · {n} commit{'' if n == 1 else 's'}" if isinstance(n, int) else ""
        return f"last pulled {age + ' ago' if age else 'just now'}{count}"
    if outcome == "waiting":
        who = r.get("occupant")
        return (
            f"waiting: {who} is mid-turn"
            if who
            else "waiting: a session here cannot be read, so it is taken as mid-turn"
        )
    if outcome == "refused":
        return f"refused: {r.get('why') or 'no reason given'}"
    return str(outcome) if outcome in ("current", "off") else ""


def sync_reading(reading: Mapping[str, Any] | None, on: bool, now: datetime | None = None) -> str:
    """The repo's last sync verdict beside the Repos card's **sync** switch (§4.5a, §6 *Sync*, TD-685),
    from its repo facts (`sync` and `prs`): *merged #<n> <age> ago*, *#<n> refused: <why>*, *#<n> gate:
    <line>*, *#<n> error: <why>*, *no sync PR*, *off* — the newest entry with a verdict by its `at`;
    *no sync PR* only when the PR reading holds none open. "" with no reading, a PR reading that failed,
    or an open sync PR with no verdict yet (waiting on CI, a retry still counted)."""
    if not on:
        return "off"
    if not isinstance(reading, Mapping):
        return ""
    sync = reading.get("sync") if isinstance(reading.get("sync"), Mapping) else {}
    done = [(str(e.get("at") or ""), str(n), e) for n, e in sync.items() if isinstance(e, Mapping)]
    done = [d for d in done if d[2].get("verdict") in ("merged", "refused", "gate", "error")]
    if not done:
        prs = reading.get("prs") if isinstance(reading.get("prs"), Mapping) else {}
        if prs.get("error") or not isinstance(prs.get("open"), list):
            return ""
        return "" if any(isinstance(p, Mapping) and p.get("sync") is True for p in prs["open"]) else "no sync PR"
    _, n, e = max(done, key=lambda d: d[0])
    if e["verdict"] == "merged":
        age = _age(e.get("at"), now or datetime.now(UTC))
        return f"merged #{n} {age} ago" if age else f"merged #{n}"  # an unreadable `at` says no age
    return f"#{n} {e['verdict']}: {e.get('why') or 'no reason given'}"


def repo_cards(
    checkouts: list[str],
    settings_repos: Mapping[str, Any] | None,
    pulls: Mapping[str, Any] | None = None,
    readings: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """**Repos** (§4.5 screen 8): a card per registered checkout with its `.shiftlead.yml` values
    read-only — the keys the clients read — and, where the file carries `promote:`, the one setting,
    **auto**, as `settings.yml` holds it (`false` when absent). A repo with no block says why it has
    no switch; a file that does not parse says so in place of its values. Every card, block or not,
    carries **pull** (§6 *Pull*: on when absent) and the home's last reading of it from `pulls`, and
    **sync** (§6 *Sync*: on when absent) with the repo's last verdict from the repo facts' `sync`
    (`readings`, keyed by the checkout's path; a checkout with no reading says nothing of it)."""
    out = []
    for path in checkouts:
        root = Path(path)
        name = root.name
        card: dict[str, Any] = {"name": name, "path": path, "file": str(paths.repo_file(root)), "rows": []}
        card["pull"] = ((settings_repos or {}).get(name) or {}).get("pull") is not False
        card["pull_reading"] = pull_reading((pulls or {}).get(name))
        sync_on = (((settings_repos or {}).get(name) or {}).get("sync") or {}).get("auto") is not False
        reading = (readings or {}).get(path)
        card["sync"] = sync_on
        card["sync_reading"] = sync_reading(reading, sync_on)
        try:
            cfg = repoconfig.load(root)
        except (ValueError, OSError) as e:
            card["error"] = str(e)
            out.append(card)
            continue
        card["exists"] = cfg.path is not None
        card["rows"] = [
            # the ledger as resolved (§4.4 *Either layout*, TD-1146): a directory says so, unset is the default
            _row(
                "ledger",
                f"{cfg.ledger} (directory)" if (root / cfg.ledger).is_dir() else cfg.ledger,
                is_default=not cfg.ledger_set,
            ),
            _row("roles", sorted(cfg.roles), is_default=not cfg.roles),
            _row("controllers", cfg.controllers, is_default=not cfg.controllers),
            _row("teams", sorted(cfg.teams), is_default=not cfg.teams),
            # wins over the install's **settle** key by key (§4.4, §5 `settle:`, TD-710)
            _row("settle", cfg.settle, is_default=not cfg.settle),
        ]
        if cfg.promote:
            card["rows"] += [
                _row("promote.run", cfg.promote.get("run"), None),
                _row("promote.check", cfg.promote.get("check"), None),
            ]
        auto = (((settings_repos or {}).get(name) or {}).get("promote") or {}).get("auto")
        card["promote"] = bool(cfg.promote)
        card["auto"] = auto is True
        out.append(card)
    return out


def sweep_line(path: str, fleet: list[Mapping[str, Any]], switch: Mapping[str, Any], readings: Any) -> str:
    """What sweeps one registered repo, for its line on the **Sweep** card (§4.5a, §4.9b *The switch*, *A
    repo no team serves*, TD-1091), read on the records as the tick reads them: a live team's own sweeper
    (*the team's own sweep-ao-1 · swept 1 d ago*), else the switch-made seat the tick has not held back
    (*sweep-ao-grind (ao-grind) · swept 3 d ago*), *off*, a live team with no seat yet (*ao-grind running:
    its seat comes at its next start*), or *no team: never swept*."""
    root = str(Path(path).resolve())
    live = {
        r.get("team")
        for r in fleet
        if r.get("team") and r.get("unattended") and not r.get("superseded_by") and r.get("state") not in work.DEAD
    }
    mine = [
        r
        for r in fleet
        if r.get("repo") and str(Path(str(r["repo"])).resolve()) == root and r.get("team") in live
        if not r.get("superseded_by")
    ]
    stamp = swept_words({"repo": path}, readings)
    seats = [r for r in mine if isinstance(r.get("seat"), dict) and r["seat"].get("trigger") == "swept"]
    own = [r for r in seats if r["seat"].get("by") != "settings"]
    if own:
        return f"the team's own {own[0].get('name')}{stamp}"
    if Path(path).name in (switch.get("off") or ()):
        return "off"
    teams = sorted({str(r.get("team")) for r in mine})
    if not teams:  # the switch gives a repo no team serves nothing (§4.9b *A repo no team serves*)
        return "no team: never swept" if stamp == " · never swept" else f"no team{stamp}"
    if not switch.get("on"):
        return f"the switch is off{stamp}"
    made = [r for r in seats if not (r.get("seat_count") or {}).get("swept")]
    if made:
        return f"{made[0].get('name')} ({made[0].get('team')}){stamp}"
    return f"{teams[0]} running: its seat comes at its next start"


def sweep_card(
    switch: Any,
    checkouts: list[str],
    fleet: list[Mapping[str, Any]],
    readings: Any,
    profiles: Mapping[str, Any],
) -> dict[str, Any]:
    """The **Sweep** card (§4.5a, §4.9b *The switch*, §5 `sweep:`, TD-1091): `sweep_switch`'s reading as
    `settings` answers it — **on**, **every** and **profile**, a pick of `profiles.yml`'s — and a line per
    registered checkout with its own **swept** switch (`repos.<repo>.sweep`, on when absent) and what
    sweeps it (`sweep_line`). `read` is false when the host agent gave no `sweep` (an older build)."""
    sw = switch if isinstance(switch, Mapping) else {}
    off = set(sw.get("off") or ())
    lines = [
        {
            "name": Path(p).name,
            "on": Path(p).name not in off,
            "what": sweep_line(p, fleet, {**sw, "off": sorted(off)}, readings),
        }
        for p in checkouts
    ]
    return {
        "read": bool(sw),
        "on": sw.get("on") is True,
        # the default drawn as the field's placeholder, so a Save that leaves it writes no `every`
        "every": "" if sw.get("every") in (None, settings_mod.SWEEP_EVERY) else str(sw["every"]),
        "every_default": settings_mod.SWEEP_EVERY,
        "profile": str(sw.get("profile") or ""),
        "profiles": sorted(profiles),
        "lines": lines,
    }


def local_entry(path: Path) -> dict[str, Any]:
    """`hosts.yml`'s `local:` mapping as written — only to tell a value the file sets from one it
    leaves to its default; the values themselves are `sessionorc.hosts`'s reading."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    local = doc.get("local") if isinstance(doc, dict) else None
    return local if isinstance(local, dict) else {}


def host_card(raw: Mapping[str, Any], local: hosts.Host, home: str, nodes: Mapping[str, Any]) -> dict[str, Any]:
    """**Hosts** (§4.5 screen 8): this host's `local:` entry as `sessionorc.hosts` reads it, each
    value marked *default* where the file leaves it out; the home; the nodes it admits."""
    rows = [
        _row("name", local.name, is_default="name" not in raw),
        _row("vscode_host", local.vscode_host, is_default="vscode_host" not in raw),
        _row("local", local.local, is_default="local" not in raw),
        _row("volatile", local.volatile, is_default="volatile" not in raw),
        _row("repos_registry", str(local.repos_registry), is_default="repos_registry" not in raw),
        _row("runs_keep_days", local.runs_keep_days, is_default="runs_keep_days" not in raw),
        _row("runs_keep_mb", local.runs_keep_mb, is_default="runs_keep_mb" not in raw),  # §4.6, TD-1945
        _row("scratch_root", local.scratch_root, is_default="scratch_root" not in raw),  # §4.6, TD-1944
        _row("scratch_keep_hours", local.scratch_keep_hours, is_default="scratch_keep_hours" not in raw),
        _row("worktree_keep_days", local.worktree_keep_days, is_default="worktree_keep_days" not in raw),
        _row("cache_keep_days", local.cache_keep_days, is_default="cache_keep_days" not in raw),
        _row("identity", local.identity or "enforce", is_default="identity" not in raw),
        _row("person", local.person, is_default="person" not in raw),
        _row("home", home, is_default=home == local.name),
    ]
    if nodes:
        rows.append(
            _row("nodes", [f"{n} ({', '.join(k for k, v in f.items() if v) or 'plain'})" for n, f in nodes.items()])
        )
    return {"name": local.name, "file": str(hosts.hosts_file()), "rows": rows}


_PROFILE_DEFAULTS = {f.name: f.default for f in fields(profiles_mod.Profile) if f.name != "name"}


def profile_cards(profiles: Mapping[str, profiles_mod.Profile], default: str) -> list[dict[str, Any]]:
    """**Profiles** (§4.5 screen 8): every profile as `profiles.yml` declares it, read-only."""
    out = []
    for name, p in profiles.items():
        rows = []
        for key in ("adapter", "account", "model", "config_dir", "permission_wait", "billing", "prices"):
            v = getattr(p, key)
            d = _PROFILE_DEFAULTS.get(key)
            rows.append(_row(key, str(v) if isinstance(v, Path) else v, is_default=(not v and not d) or v == d))
        for key in ("extra_args", "unattended_args"):
            if getattr(p, key):
                rows.append(_row(key, " ".join(getattr(p, key))))
        out.append({"name": name, "default": name == default, "rows": rows})
    return out


def org_cards(defs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """**Org** (§4.5 screen 8): each team the org defines, read-only — its repo, its manager,
    its techlead seat, its members by role and count, the host it lands on."""
    out = []
    for name, d in defs.items():
        members: dict[str, int] = {}
        for m in d.members:
            members[m.role] = members.get(m.role, 0) + (m.count or 1)
        rows = [
            _row("repo", d.repo),
            _row("manager", f"{d.manager.name} · {d.manager.role}"),
            _row("techlead", d.techlead.name if d.techlead else None, is_default=d.techlead is None),
            _row("members", " · ".join(f"{k} ×{n}" for k, n in members.items()) or "none"),
            _row("host", d.host or "where the start runs", is_default=not d.host),
        ]
        if d.seats:
            rows.append(_row("seats", [f"{s.name} ({s.trigger})" for s in d.seats]))
        out.append({"name": name, "source": str(d.source or ""), "rows": rows})
    return out


def you(person: Mapping[str, Any] | None) -> dict[str, Any]:
    """**You**, *yours everywhere* (§4.5 screen 8): `open_in` as the field takes it back and the
    terminal's size and face, the attachment bound, the composer's pick — what `settings.yml` holds, the
    defaults where it holds nothing."""
    person = person or {}
    o = person.get("open_in")
    if isinstance(o, dict):
        mode, label, url, file = (
            "template",
            str(o.get("label") or ""),
            str(o.get("url") or ""),
            str(o.get("file") or ""),
        )
    else:
        mode, label, url, file = (str(o) if o in ("vscode", "none") else "vscode"), "", "", ""
    # **file link** (§4.5a *Settings page: You, file link*, §5 `person.file_link`; TD-536): the defaults where unset
    try:
        fl = settings_mod.parse_file_link(person.get("file_link"), drop=True)
    except ValueError:
        fl = {}
    term = person.get("terminal") if isinstance(person.get("terminal"), dict) else {}
    lo, hi = settings_mod.TERMINAL_SIZE
    attach = person.get("attach") if isinstance(person.get("attach"), dict) else {}
    # **board items shown** (§4.5a, TD-220 slice 4): the pick of four and its two numbers, 10 and 7 until typed
    inbox = person.get("inbox") if isinstance(person.get("inbox"), dict) else {}
    try:
        show = settings_mod.parse_board_show(inbox.get("board_show"))
    except ValueError:
        show = settings_mod.BOARD_SHOW_DEFAULT
    board_next, board_days = 10, 7
    if show.startswith("next:"):
        board_mode, board_next = "next", int(show.split(":", 1)[1])
    elif show.endswith("d"):
        board_mode, board_days = "days", int(show[:-1])
    else:
        board_mode = show
    return {
        "board_mode": board_mode,
        "board_next": board_next,
        "board_days": board_days,
        "board_next_bounds": settings_mod.BOARD_SHOW_NEXT,
        "board_days_bounds": settings_mod.BOARD_SHOW_DAYS,
        "open_in": mode,
        "label": label,
        "url": url,
        "file": file,
        "folder_first": fl.get("folder_first", True),
        "wait": fl.get("wait", 1),
        "wait_bounds": settings_mod.FILE_LINK_WAIT,
        "size": term.get("size") if isinstance(term.get("size"), int) else None,
        "face": str(term.get("face") or ""),
        "copy_on_select": term.get("copy_on_select") is not False,  # on by default (§4.5a, TD-164)
        "size_bounds": (lo, hi),
        # **attachment bound** (§4.5 screen 8, §5 `person.attach.max`, TD-478): as written, the default beside it
        "attach_max": str(attach.get("max") or ""),
        "attach_default": settings_mod.ATTACH_MAX_DEFAULT,
        # **composer** (§4.5a *Focus composer* **the bar**, §5 `person.composer`, TD-500): folded by default
        "composer": "open" if person.get("composer") == "open" else "folded",
    }


# **Telegram**'s two display lines under its fields (§4.5a **You**: **Telegram**, §4.10 *Told on
# Telegram when nobody is looking*): what is told, and when — the design's list, not a setting
TELEGRAM_TOLD = (
    "told: a session waiting on you · a question · a blocked outcome · an identity alarm · "
    "a member not restarted · a team with work"
)
TELEGRAM_WHEN = "after a minute, once, and never while a page is visible · no text a session wrote is sent"


def telegram(
    notify: Mapping[str, Any] | None,
    last: Mapping[str, Any] | None,
    now: datetime | None = None,
    *,
    reach: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """**You**: **Telegram** (§4.5a, §4.10; TD-319 slice 3): `notify.telegram` as the `settings` read
    keeps it — the switch, the Doppler `project/config` (a name, never a value) and the link — and the
    last send from the home's `host` read (`notify: {last_ok, last_error}`), the later of the two:
    *last sent 14:02* or *last send failed 14:02: <reason>*; nothing yet, or a node's read, draws none.
    The link's placeholder is what an empty link sends (§4.5b *The setting*, TD-648): `reach.url` when a
    route is set, else `http://localhost:8765`, the plain port a browser on the home reaches."""
    tg = (notify or {}).get("telegram") if isinstance(notify, Mapping) else None
    tg = tg if isinstance(tg, Mapping) else {}
    now = now or datetime.now(UTC)
    last = last if isinstance(last, Mapping) else {}
    ok = _when(last.get("last_ok"))
    err = last.get("last_error") if isinstance(last.get("last_error"), Mapping) else {}
    bad = _when(err.get("at"))
    said, failed = "", False
    if bad is not None and (ok is None or bad > ok):
        said, failed = f"last send failed {usage_clock(bad, now)}: {err.get('reason') or 'no reason given'}", True
    elif ok is not None:
        said = f"last sent {usage_clock(ok, now)}"
    return {
        "on": tg.get("on") is True,
        "secrets": str(tg.get("secrets") or ""),
        "link": str(tg.get("link") or ""),
        "link_placeholder": str((reach or {}).get("url") or "") if isinstance(reach, Mapping) else "",
        "last": said,
        "last_failed": failed,
        "told": TELEGRAM_TOLD,
        "when": TELEGRAM_WHEN,
    }


PUSH_READING = "reading the key…"


def _push_clock(dt: datetime, now: datetime) -> str:
    """A device's delivery time: *14:02*, with the date in front once it is a day old (§4.5a **Push**)."""
    try:
        local = dt.astimezone()
    except (OverflowError, ValueError, OSError):
        local = dt
    return local.strftime("%b %-d %H:%M") if (now - dt).total_seconds() >= 86400 else local.strftime("%H:%M")


def push_card(
    notify: Mapping[str, Any] | None,
    view: Mapping[str, Any] | None,
    now: datetime | None = None,
    *,
    node: bool = False,
    home: str = "",
    reach: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """**You**: **Push** (§4.5a, §4.10 *Told on the home-screen app too*; TD-1305): `notify.push` as the
    `settings` read keeps it — **on all devices** (on when absent), **with Telegram** (`both` when absent),
    **secrets** (its own; Telegram's drawn greyed as what an empty one sends) — and the `host` read's `push`
    view: the key's reading, the public key the page subscribes with, each device's line and `last_line`.
    `block` is the switch's line the server can tell (the key's, or the secrets'), "" when the key reads
    *key*; the browser's own cases (a secure context, iOS, the permission) are the page's, checked first.
    On a node only `node` and `home` are drawn: the card is the home's."""
    n = notify if isinstance(notify, Mapping) else {}
    p = n.get("push") if isinstance(n.get("push"), Mapping) else {}
    tg = n.get("telegram") if isinstance(n.get("telegram"), Mapping) else {}
    v = view if isinstance(view, Mapping) else {}
    now = now or datetime.now(UTC)
    own, tg_secrets = str(p.get("secrets") or ""), str(tg.get("secrets") or "")
    reading = v.get("key") if isinstance(v.get("key"), str) else None
    devices = []
    for d in v.get("devices") or []:
        if not isinstance(d, Mapping) or not d.get("id"):
            continue
        ok = _when(d.get("last_ok"))
        err = d.get("last_error") if isinstance(d.get("last_error"), Mapping) else {}
        bad = _when(err.get("at"))
        last, failed = "", False
        if bad is not None and (ok is None or bad > ok):
            last, failed = f"last failed {_push_clock(bad, now)}: {err.get('reason') or 'no reason given'}", True
        elif ok is not None:
            last = f"last told {_push_clock(ok, now)}"
        since = _when(d.get("since"))
        devices.append({
            "id": str(d["id"]),
            "label": str(d.get("label") or "a device"),
            "since": since.astimezone().strftime("%b %-d") if since is not None else "",
            "last": last,
            "failed": failed,
        })  # fmt: skip
    block, make = "", False
    if not own and not tg_secrets:
        block = "set secrets first"
    elif reading is None:
        block = PUSH_READING
    elif reading == "no key":
        block, make = "make the key first", True
    elif reading.startswith("unreadable: "):
        block = f"the key could not be read: {reading.removeprefix('unreadable: ')}"
    elif reading != "key":
        block = f"the key could not be read: {reading}"
    paused = f"push is paused: {reading}" if devices and reading not in (None, "key") else ""
    last_line = str(v.get("last_line") or "")
    url = str((reach or {}).get("url") or "") if isinstance(reach, Mapping) else ""
    return {
        "node": node,
        "home": home,
        "on": p.get("on") is not False,
        "telegram": p.get("telegram") if p.get("telegram") in settings_mod.PUSH_TELEGRAM else "both",
        "tg_on": tg.get("on") is True,
        "secrets": own,
        "tg_secrets": tg_secrets,
        "reading": reading or "",
        "public_key": str(v.get("public_key") or "") if reading == "key" else "",
        "block": block,
        "make": make,
        "devices": devices,
        "paused": paused,
        "last_line": "" if last_line == paused else last_line,
        "https": url if url.startswith("https://") else "",
    }


def gauge_view(g: Mapping[str, Any] | None, billing: Any = None) -> dict[str, Any]:
    """An account's gauges as the Tools page draws them (design §4.2b *The gauge*, TD-1975): the `tools` read's
    `gauges` (`sessionorc.usage.gauges`, the one builder) with the words each window shows — the reserve as the field
    takes it back, the line it makes or a metered window's spend, and its reset in local time. An older agent's read,
    whose `gauges` are not filled, draws as an account with no reading, a metered one its home's windows."""
    if not isinstance(g, Mapping):
        g = {"billing": billing or "subscription", "unread": True, "windows": [], "gone": []}
        if g["billing"] == "metered":
            labels = sorted(spend_mod.LABELS, key=lambda x: x != "week")  # the week's first (§4.2b)
            g["windows"] = [{"label": x, "pct": None, "reserve": None} for x in labels]
        else:
            g["windows"] = [{"label": "week", "pct": None, "reserve": None}]
    metered = g.get("billing") == "metered"
    out: dict[str, Any] = {
        "metered": metered,
        "mixed": g.get("billing") == "mixed",
        "unread": bool(g.get("unread")) and not metered,
        "stale": bool(g.get("stale")),
        "age": f"read {ago} ago" if (ago := _age(g.get("read_at"), datetime.now(UTC))) else "",
        "gauges": [],
        "gone": [],
    }
    reported = [str(w.get("label")) for w in g.get("windows") or []]
    for w in g.get("windows") or []:
        pct = w.get("pct") if _is_num(w.get("pct")) else None
        value = reserve_text(w.get("reserve"))
        if metered:
            spent = {"spent": w.get("spent"), "pct": None if pct is None else round(pct), "resets": w.get("resets")}
            line = spend_text(spent, "tok" if value.endswith("tok") else "")
        else:
            line = line_text({"line": w.get("line"), "reserve": w.get("reserve"), "resets": w.get("resets")})
        resets = _when(w.get("resets"))
        out["gauges"].append(
            {
                "label": str(w.get("label")),
                "value": value,
                "used": pct,
                "keep": w.get("keep"),
                "room": w.get("room"),
                "resets": f"{resets.astimezone():%a %H:%M}" if resets else "",
                "line": line,
            }
        )
    for x in g.get("gone") or []:
        out["gone"].append(
            {
                "label": str(x.get("label")),
                "value": reserve_text(x.get("reserve")),
                "line": f"not reported: its reading reports {', '.join(reported)}",
            }
        )
    return out


def tools_accounts(read: Mapping[str, Any] | None) -> set[str] | None:
    """The accounts the Tools page draws on a switched home (design §4.2b *The gauge*, TD-1975): their gauges and
    reserves are its own, so the Settings page's Usage card leaves them and keeps every other — an account seen only
    on a node, or one no signed-in login draws. None before the switch, or where the agent served no read, where the
    card keeps every account."""
    if not isinstance(read, Mapping) or not read.get("switched"):
        return None
    return {str(a.get("key")) for c in read.get("tools") or [] for a in c.get("accounts") or [] if a.get("key")}
