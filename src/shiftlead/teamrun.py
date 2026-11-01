"""Running a team definition: the RPC sequence `ao team start|stop|list` performs, in one place so
the CLI and the Sessions page's **Teams** strip cannot drift (design §4.9 "Starting and stopping",
§4.5a Sessions **Teams** strip).

`shiftlead.teams` decides what a start *means* (`plan`, which touches no RPC); this module is the
one that talks to the agent, and it does so through an injected blocking `call(method, **params)`
so neither caller's transport leaks in: `ao team` hands it `cli.call_sync`, and the UI hands it the
same blocking client from a worker thread, so a start or a wrap-up never blocks the event loop.

Every check happens before any create (§4.9: there is never half a team). Nothing here formats for
a terminal or a page — the callers do that from the returned records.
"""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import balance as balance_mod
from sessionorc import hosts, naming
from sessionorc import ledger as ledger_mod
from sessionorc import seams as seams_mod
from sessionorc.agent_common import ORPHAN_AFTER
from sessionorc.client import AgentError
from sessionorc.gitinfo import work_left
from sessionorc.work import (
    closed_finished,
    finished,
    sat_out,
    wound_down,
)  # one reading each for the card and the home (rules 8, 9)
from shiftlead import flowdefs, repoconfig, teams
from shiftlead import org as orgmod

Call = Callable[..., Any]
Waiting = dict[str, list[dict[str, Any]]]  # sender id → its open questions (`work.waiting_of`, TD-274)


def waiting_of_home(call: Call, *, strict: bool = False) -> Waiting:
    """What each live session waits on, from the home's `host` reading (§4.9a *Waiting is read,
    never declared*, TD-274): the person inbox is a person's to read, so a session's `ao team status`
    asks the home for the references and bounds, never the text. `{}` from an agent without it —
    unless `strict`, for a caller about to close sessions, which a failed read must not license."""
    try:
        got = (call("host") or {}).get("waiting")
    except AgentError:  # an agent that answers no `host`: an older one, a stub
        if strict:
            raise
        return {}
    return {str(k): list(v) for k, v in got.items() if isinstance(v, list)} if isinstance(got, dict) else {}


SETTLED = ("idle", "exited", "closed")  # what "wrapped up" looks like from outside (design §4.2)
DEAD = ("exited", "closed")
WRAPUP_POLL = 2.0  # seconds between reads while a stop waits for the members to settle
STOP_TIMEOUT = 300.0  # the default wrap-up window (§4.9)
# a run under this many seconds, first start to last close, says *after 40 s* on the wound-down note
# (§4.5a, TD-262): a start that ended at once is the thing to notice
SHORT_RUN = 600


class NamesHeld(teams.TeamError):
    """§4.1's rule refused a start: one or more names are held by a live session, or by a record a
    person **suspended** over an identity alarm (§4.8a, TD-077 a2 — the same refusal, since the
    answer is the same: that name is not this start's to take). Nothing was created — the whole
    start is off, so there is never half a team."""

    def __init__(self, team: str, holders: list[dict[str, Any]]):
        self.team, self.holders = team, holders
        names = "; ".join(
            f"{v['name']} is suspended as {v['holder']} — a person lifts it"
            if v.get("verdict") == "suspended"
            else f"{v['name']} is {v.get('holder_state', 'running')} as {v['holder']}"
            for v in holders
        )
        # the cure for a name held by a session that is merely there (§4.9, TD-1051): a suspension is a person's
        cure = (
            f": `ao team stop {team} --close` closes a settled member, or Close it on its card"
            if any(v.get("verdict") != "suspended" for v in holders)
            else ""
        )
        super().__init__(f"team {team} was not started — {names}{cure}")


class PartialStart(teams.TeamError):
    """A create failed part-way through a start that had passed every check. The sessions already
    created are named rather than silently left behind."""

    def __init__(self, team: str, created: list[dict[str, Any]], plan: teams.Plan, error: Exception):
        self.team, self.created, self.plan, self.error = team, created, plan, error
        super().__init__(f"team {team}: {error} — {len(created)} session(s) already started")


@dataclass
class Stopping:
    """A stop in progress: what has been sent, and the lead that is still to be stopped."""

    team: str
    now: bool
    acted: list[dict[str, Any]] = field(default_factory=list)
    lead: dict[str, Any] | None = None  # the record, until `stop_lead` acts on it
    # The lead ran the stop itself — the wind-down of §4.9a. It cannot be typed at mid-command, and
    # killing it would kill the command: it is told what is left, and ends itself.
    lead_is_caller: bool = False

    @property
    def member_ids(self) -> list[str]:
        """The members the stop reached: a refused one (its host unreachable, §4.4a) is not waited on."""
        return [e["id"] for e in self.acted if e["role"] == "member" and not e.get("refused")]


def persons(s: dict[str, Any]) -> bool:
    """A person's own session (design §4.9 *A person in the team*): one whose record says
    `unattended: false`. A team's own facts — live, concluded, wound down, what a stop reaches —
    read the others. Every record carries the field; one that lacks it is read as a worker's, which
    is what every badged session was before TD-173."""
    return s.get("unattended") is False


def badged(name: str, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in sessions if s.get("team") == name]


def crew(name: str, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sessions carrying a team's badge that are not a person's (`persons`): what a team's own
    facts and acts read — whether it is live or concluded, whom a stop or a concluded Start closes,
    whether Add member starts the new one now (design §4.9 *A person in the team*)."""
    return [s for s in badged(name, sessions) if not persons(s)]


def live(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in sessions if s["state"] not in DEAD]


def tagging_seat(fleet: list[dict[str, Any]], root: Path, declared: list[str]) -> tuple[str, str]:
    """Who tags the repo's entries that need a team (§4.4 *An untagged or unknown entry is handed to a
    techlead*, TD-730), as the tick picks it: `(name, "")` for the seat it hands them to — among the
    repo's records carrying `seat.tags` whose team is live, the first in `declared`'s order, a team it
    leaves out after, by name — else `("", why)`, why nobody is, in `ao repo`'s words."""
    order = [str(t).casefold() for t in declared]
    mine = [
        s
        for s in fleet
        if not s.get("superseded_by") and s.get("repo") and Path(s["repo"]).resolve() == root and s.get("seat")
    ]
    up = {s.get("team") for s in fleet if s.get("team") and s.get("unattended") and s.get("state") not in DEAD}

    def first(seats: list[dict[str, Any]]) -> dict[str, Any]:
        def key(s: dict[str, Any]) -> tuple[int, int, str]:
            team = str(s.get("team") or "").casefold()
            return (0, order.index(team), "") if team in order else (1, 0, team)

        return min(seats, key=key)

    tags = [s for s in mine if s["seat"].get("tags")]
    live = [s for s in tags if s.get("team") in up and s.get("unattended") and not s.get("suspended")]
    if live:
        return str(first(live).get("name") or first(live)["id"]), ""
    if tags:
        return "", f"{first(tags).get('name') or first(tags)['id']}'s team is stopped"
    techleads = [s for s in mine if s["seat"].get("trigger") == "asks" and s.get("team")]
    if techleads:
        return "", f"no techlead seat carries tags yet — the next Start of {first(techleads)['team']} writes it"
    return "", "no techlead seat to tag them"


def on_call(s: dict[str, Any]) -> bool:
    """A seat with nobody in it (§4.9b, §6 rule 3): a record carrying `seat` that is `exited` or
    `closed`. Its id and its grants survive the close, so whoever fills it is the controller a
    session names now (design §4.5a New session **Controllers**, TD-269)."""
    return bool(s.get("seat")) and s.get("state") in ("exited", "closed")


# A Start's and an Apply's line for a manager on call, written held (§6 rule 3, TD-410): the card's words
ON_CALL_LINE = f"on call — {orgmod.MANAGER_WHEN}"


def on_call_gate(x: teams.Launch) -> dict[str, Any]:
    """`create`'s `held` for a team's lead on call (§6 rule 3 *A Start writes the seat and never
    fills it*, TD-410): the launch carries a seat's trigger only when its manager is on call, and a
    standing one (`on_call: false`) starts live as before. No `held_reason`: nothing holds it. A
    manager the definition asks to be watched (`unattended: false`) starts live too: a held record is
    a seat's, which `create` writes only unattended."""
    return {"held": True} if x.lead and x.trigger and x.unattended else {}


def can_control(sessions: list[dict[str, Any]], sid: str) -> dict[str, Any] | None:
    """The record `sid` when it may stand as a new session's controller — live, or a seat on call
    (TD-269, built by TD-276) — else None."""
    s = next((s for s in sessions if s.get("id") == sid), None)
    return s if s is not None and (s["state"] not in DEAD or on_call(s)) else None


def balance_marks(repos: dict[str, dict[str, Any]], host: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """The teams over their line, `{team: mark}`, from the `repos` reading (design §6 *Balance*,
    TD-239): each checkout's reading carries the marks whose `repo` it is. `host` is the home's `host`
    read, whose `balance` carries every mark — one with no `repo` too, which no checkout's reading
    holds (TD-330); an older home's read has none."""
    out: dict[str, dict[str, Any]] = {}
    for r in repos.values():
        marks = r.get("balance") if isinstance(r, dict) else None
        for team, mark in (marks if isinstance(marks, dict) else {}).items():
            if isinstance(mark, dict):
                out.setdefault(str(team), mark)
    marks = (host or {}).get("balance")
    for team, mark in (marks if isinstance(marks, dict) else {}).items():
        if isinstance(mark, dict):
            out.setdefault(str(team), mark)
    return out


def _clock(iso: Any) -> str:
    """An instant in this host's clock, the weekday before it when it is not today."""
    try:
        at = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ""
    day = "" if at.date() == datetime.now().astimezone().date() else at.strftime("%a ")
    return f"{day}{at:%H:%M}"


def _crossed_words(c: dict[str, Any]) -> str:
    v, lim, dur = c.get("value"), c.get("limit"), balance_mod.duration
    if c.get("line") == "prs":
        return f"{v} open PR{'' if v == 1 else 's'}, line {lim}"
    if c.get("line") == "oldest":
        return f"oldest PR {dur(v)}, line {dur(lim)}"
    if c.get("line") == "review":
        return f"review waiting {dur(v)}, bound {dur(lim)}"
    return f"{c.get('line')} {v}, line {lim}"


def balance_note(mark: dict[str, Any]) -> str:
    """A mark in the team card's words (design §4.5a **over its line** note), which `ao team list`
    and `ao repo` say too: *over its line since 14:02: 9 open PRs, line 8* — each crossed line in
    the mark's own numbers."""
    since = f" since {t}" if (t := _clock(mark.get("since"))) else ""
    lines = ", ".join(_crossed_words(c) for c in mark.get("crossed") or [] if isinstance(c, dict))
    return f"over its line{since}" + (f": {lines}" if lines else "")


def balance_now(
    team: str, sessions: list[dict[str, Any]], repos: dict[str, dict[str, Any]], now: datetime | None = None
) -> dict[str, Any]:
    """The numbers a team's balance lines are read against, as they read now (design §4.7 `ao team
    balance`, §6 *Balance*), gathered as the home's tick gathers them: the registered repos the
    team's live sessions name, the most open pull requests any of them has (`prs`) and the age of
    the oldest in seconds (`oldest`), how long the oldest pull request has waited at the team's
    seats (`review`) and the bound it is read against (`bound`, the shortest `review.bound` a live
    member carries, two hours where none). A number that cannot be told is None: no live member,
    no reading, nothing waiting; `oldest` is 0 where the reading holds no open pull request."""
    now = now or datetime.now(UTC)
    members = [s for s in sessions if s.get("team") == team and s.get("state") not in DEAD]
    members = [s for s in members if not s.get("superseded_by")]
    roots = sorted({str(s["repo"]) for s in members if s.get("repo") and s["repo"] in repos})

    def age(iso: Any) -> int | None:
        try:
            return int((now - datetime.fromisoformat(str(iso).replace("Z", "+00:00"))).total_seconds())
        except (TypeError, ValueError):
            return None

    counts: list[int] = []
    ages: list[int] = []
    for root in roots:
        prs = repos[root].get("prs")
        if not isinstance(prs, dict) or "error" in prs or not isinstance(prs.get("open"), list):
            continue  # could not look, as `balance.crossed` reads a failed reading
        counts.append(len(prs["open"]))
        ages += [a for p in prs["open"] if isinstance(p, dict) and (a := age(p.get("created"))) is not None]
    waits = [
        a
        for s in members
        if s.get("seat") and isinstance(s.get("prs_waiting"), dict)
        if (a := age(s["prs_waiting"].get("oldest"))) is not None
    ]
    bounds = [d for s in members if (d := balance_mod.span((s.get("review") or {}).get("bound")))]
    return {
        "members": len(members),
        "repos": roots,
        "prs": max(counts) if counts else None,
        "oldest": max(ages) if ages else (0 if counts else None),
        "review": max(waits) if waits else None,
        "bound": int((min(bounds) if bounds else balance_mod.REVIEW_BOUND).total_seconds()),
    }


def balance_rows(bal: dict[str, Any], now: dict[str, Any]) -> list[str]:
    """`ao team balance`'s three lines, which the Settings page draws under **balance** (§4.5a): each
    number as it reads now, the line it is read against where one is drawn, and *over* where it is
    crossed."""
    dur = balance_mod.duration

    def row(what: str, value: Any, limit: Any, word: str, nothing: str, show: Callable[[Any], str]) -> str:
        said = nothing if value is None else show(value)
        if limit is None:
            return f"  {what}: {said} (no line)"
        over = " — over" if value is not None and value > limit else ""
        return f"  {what}: {said} ({word} {show(limit)}){over}"

    oldest = balance_mod.span(bal.get("oldest"))
    return [
        row("open PRs", now["prs"], bal.get("prs"), "line", "could not look", str),
        row("oldest PR", now["oldest"], int(oldest.total_seconds()) if oldest else None, "line", "could not look", dur),
        row(
            "reader's queue",
            now["review"],
            now["bound"] if bal.get("review") else None,
            "bound",
            "nothing waiting",
            dur,
        ),
    ]


def split(name: str, sessions: list[dict[str, Any]], org: orgmod.Org) -> tuple[dict | None, list[dict]]:
    """The lead and the members among the sessions carrying a team's badge: the lead is the session
    the definition names (a team with a `person` lead has none), the rest are members in name order."""
    team = org.teams.get(name)
    lead_name = team.manager.name if team and team.manager.role != orgmod.PERSON else None
    lead = next((s for s in sessions if s.get("name") == lead_name), None)
    return lead, sorted((s for s in sessions if s is not lead), key=lambda s: s.get("name") or s["id"])


def concluded(
    sessions: list[dict[str, Any]], seats: Collection[str] = (), waiting: Waiting | None = None
) -> dict[str, Any] | None:
    """When a live team has said everything it has to say (design §4.5a **team groups**, §4.9a
    *A person's Start on a concluded team*, TD-099): the home's reading of *finished* (§6 rule 9,
    `sessionorc.work.finished`, TD-241) where it holds — every live member `idle` and declared,
    `out_of_work` or `restart_wanted`, its seats not there or `idle`, and its manager `idle`,
    declared or not. Then `{at, restart, names}`: the latest declaration's instant (None where only
    seats and the manager are left), whether any of them asks for a restart, and the live sessions
    a Start would close first. Else None — and None for a team with nothing live, which is
    `wound_down`'s.

    *Concluded* is the team's word, not a member's *finished*: it takes either declaration, since
    either says the run is over. The state is part of the test because a declaration is cleared only
    by a later declared claim — a session that declared and then took a turn is `working` with the
    word still on its record, and its team is not concluded while it is. A seat never declares; one
    that is `working` is answering somebody. `seats` are the definition's names for them, beside
    the record's own `seat` field. `waiting` is the home's `host` reading's (`waiting_of` over the
    person inbox, §4.9a *Waiting is read, never declared*, TD-274): a live member with a question
    about a reference out to the person is not concluded, whatever it declared."""
    f = finished(sessions, seats, waiting)
    if f is None or f["why"]:
        return None
    return {"at": f["at"], "restart": f["restart"], "names": f["names"]}


def _seat_whens(team: orgmod.TeamDef) -> dict[str, str]:
    """Every seat the definition names — the techlead, each seat with a trigger (§4.9b, TD-098) and
    a manager on call (§4.9, TD-259) — with what would make it come, in the card's words
    (`SeatDef.when`, `org.MANAGER_WHEN`)."""
    out = {team.techlead.name: "comes on the next question"} if team.techlead is not None else {}
    out.update({s.name: s.when() for s in team.seats})
    if team.manager.on_call and team.manager.name:  # §4.9, §6 rule 3's `team` trigger (TD-259)
        out[team.manager.name] = orgmod.MANAGER_WHEN
    return out


def _seat_of(team: orgmod.TeamDef, sessions: list[dict[str, Any]]) -> dict[str, str]:
    """name → when-words, for the names among `sessions` that are one of the team's seats: the
    definition's name, or that name with the numeric suffix a session takes when a stale tmux
    session held its id (§4.1, the note `ao team start` prints then) — and never a name the
    definition gives one of its members."""
    whens = _seat_whens(team)
    switched = f"sweep-{team.name}"
    for s in sessions:
        # the Settings switch's sweeper (§4.9b *The switch*, TD-1091): a seat by its record's mark, as
        # no definition names it
        mark = s.get("seat")
        if isinstance(mark, dict) and mark.get("by") == "settings" and switched not in whens:
            whens[switched] = orgmod.SeatDef(trigger="swept", after=str(mark.get("after") or "")).when()
    if not whens:
        return {}
    members = {n for m in team.members for n in m.names()}
    # a manager is a seat by its **record**, not by the definition alone: a team keeps the shape it was
    # started with until its next Start (§4.9 `on_call`), so a standing manager started before the
    # definition read *on call* is no seat — nothing would fill it, and it still declares
    lead = team.manager.name if team.manager.on_call else None
    named = {s.name for s in team.seats} | ({team.techlead.name} if team.techlead is not None else set())
    out: dict[str, str] = {}
    for s in sessions:
        n = str(s.get("name") or "")
        if not n or n in members:
            continue
        base = n if n in whens else re.sub(r"-\d+$", "", n)
        if base == lead and base not in named and not isinstance(s.get("seat"), dict):
            continue
        if base in whens:
            out[n] = whens[base]
    return out


def seat_names(team: orgmod.TeamDef, sessions: list[dict[str, Any]]) -> set[str]:
    """The names among `sessions` that are one of the team's seats (`_seat_of`)."""
    return set(_seat_of(team, sessions))


def seat_ids(org: orgmod.Org, sessions: list[dict[str, Any]]) -> dict[str, str]:
    """The ids among `sessions` that are a seat of the team whose badge they carry (`seat_names`,
    design §4.9b), each with what would make it come (*comes on the next question*, *runs after
    10 PRs*) — what the Sessions page draws *on call* while nobody is in one, and its slot (§4.5 *The
    card's anatomy*, TD-097, TD-098). Keyed by the definition and the name, never by a role (§9
    invariant 9)."""
    out: dict[str, str] = {}
    for t in org.teams.values():
        mine = badged(t.name, sessions)
        whens = _seat_of(t, mine)
        out.update({str(s["id"]): whens[s["name"]] for s in mine if s.get("id") and s.get("name") in whens})
    return out


def size_words(size: Mapping[str, Any] | None, team: orgmod.TeamDef | None) -> list[str]:
    """Each line `teams.<team>.size` sets to other than its count, as `ao team list`, the settings line
    and the Members dialog say it — *grinder-ao 2 (file says 1)* (§4.9 *A team's size*). With no
    definition to read, the number alone; a key no line names is `ao org check`'s to say, not here."""
    counts = {m.name: m.count for m in team.members} if team is not None else {}
    out: list[str] = []
    for line, n in (size or {}).items():
        if team is not None and line not in counts:
            continue
        if counts.get(line) != n:
            out.append(f"{line} {n} (file says {counts[line]})" if line in counts else f"{line} {n}")
    return out


def role_holders(t: orgmod.TeamDef) -> list[dict[str, Any]]:
    """The roles a definition names, in its order — the manager, the techlead seat, the seats with a
    trigger, then the members — each once, with the session names that hold it and whether it is a
    seat (an empty seat reads *on call*). A person leading the team is not a role here."""
    out: dict[str, dict[str, Any]] = {}

    def add(role: str, names: list[str], seat: bool) -> None:
        if not role:
            return
        got = out.setdefault(role, {"role": role, "names": [], "seat": seat})
        got["names"] += [n for n in names if n not in got["names"]]

    if t.manager.role != orgmod.PERSON:
        add(t.manager.role, [t.manager.name], False)
    if t.techlead:
        add("techlead", [t.techlead.name], True)
    for seat in t.seats:
        add(seat.role, [seat.name], True)
    for m in t.members:
        add(m.role, m.names(), False)
    return list(out.values())


def _when(iso: Any) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def wound_down_note(t: orgmod.TeamDef, mine: list[dict[str, Any]], names: dict[str, str]) -> dict[str, Any]:
    """**Who, how soon, and why** on a wound-down team's note (design §4.5a *wound down* note, TD-262,
    built by TD-265): `closed_by` from the run's records' closer — the manager's name when it closed
    any member, else the first member's closer (*you*, *the tick*, a session's name) — `run_seconds`
    from the run's first `created` to its last `closed_at`, `after` set only under `SHORT_RUN`, and
    `manager_why`, the first line of the manager's own `out_of_work.why` (none when it closed without
    declaring). The run is the records not superseded by a later start; anything unreadable is left
    out, never guessed."""
    run = [s for s in mine if not s.get("superseded_by")]
    mgr_name = t.manager.name if t.manager.role != orgmod.PERSON else ""
    mgr = next((s for s in run if mgr_name and s.get("name") == mgr_name), None)
    closers = [
        (s, str(c["by"])) for s in run if s is not mgr and isinstance(c := s.get("closer"), dict) and c.get("by")
    ]
    closed_by = ""
    if mgr and any(by == mgr.get("id") for _, by in closers):
        closed_by = mgr_name
    elif closers:
        s, by = closers[0]
        closed_by = {"person": "you", "tick": "the tick"}.get(by) or names.get(by) or by
    starts = [w for s in run if (w := _when(s.get("created")))]
    ends = [w for s in run if (w := _when(s.get("closed_at")))]
    secs = int((max(ends) - min(starts)).total_seconds()) if starts and ends else None
    after = ""
    if secs is not None and 0 <= secs < SHORT_RUN:
        after = f"{secs} s" if secs < 60 else f"{secs // 60} min"
    oow = mgr.get("out_of_work") if mgr else None
    why = str(oow.get("why") or "").strip() if isinstance(oow, dict) else ""
    return {"closed_by": closed_by, "run_seconds": secs, "after": after, "manager_why": why.split("\n", 1)[0]}


def wound_down_words(r: dict[str, Any]) -> str:
    """The note's tail after *wound down <t>*, as the card and `ao team list` both say it:
    * · after 40 s · by manager-dc-1 — nothing pickable*. *by the tick* where rule 9 ended it."""
    by = "the tick" if r.get("by_tick") else r.get("closed_by")
    return (
        (f" · after {r['after']}" if r.get("after") else "")
        + (f" · by {by}" if by else "")
        + (f" — {r['manager_why']}" if r.get("manager_why") else "")
    )


def rows(org: orgmod.Org, sessions: list[dict[str, Any]], waiting: Waiting | None = None) -> list[dict[str, Any]]:
    """One row per definition for `ao team list` and the Sessions page's **Teams** strip (design §4.5a):
    the name, the file it came from, its repo and project, how many sessions it starts, how many carrying
    its badge are live, and — when none are and every one of them said why — when it wound down;
    when some are and every one is idle and declared, when it concluded (TD-099), or else why it
    has not (`not_concluded`, the reading's `why`; TD-241).
    There is no team record — a team that is stopped is only its definition, so both are counted
    across the fleet on every call. `waiting`: the home's (`waiting_of_home`), so a member with a
    question out keeps its team from *concluded* as it keeps it from the tick's wind-down (TD-274)."""
    # a team's own facts read its **unattended** sessions: a person's session in the team keeps
    # nothing live and never winds it down (design §4.9 *A person in the team*, TD-173)
    crew = [s for s in sessions if not persons(s)]
    up = live(crew)
    names = {str(s.get("id")): str(s.get("name") or "") for s in sessions}
    rows_out = []
    for t in org.teams.values():
        mine = badged(t.name, crew)
        n_live = len(badged(t.name, up))
        down = None if n_live else wound_down(mine, seat_names(t, mine))
        # the home's reading (§6 rule 9), asked once: it holds when `why` is empty
        f = finished(mine, seat_names(t, mine), waiting) if n_live else None
        rows_out.append(
            {
                "name": t.name,
                "source": str(t.source) if t.source else None,
                # the org file's own definition, which the card's Members… may edit (TD-172); a repo's is read
                "in_org": bool(t.source and org.path and Path(t.source) == Path(org.path)),
                # the team's one repo and its project's heading (§4.9 *Teams*, TD-722)
                "repo": t.repo,
                "project": org.project_of(t.repo),
                "manager": t.manager.name if t.manager.role != orgmod.PERSON else "person",
                # a seat on call, filled when a member needs a reading, or a standing session (§4.9, TD-247)
                "on_call": t.manager.on_call,
                "techlead": t.techlead.name if t.techlead else None,  # the seat (§4.9b), if any
                # its start writes `seat.tags`: a candidate for the repo's tagging seat (§4.4, TD-730)
                "techlead_tags": t.techlead is not None,
                # the role Add entry's **Open a session** starts, per Type (§4.9, TD-219), each said
                "entries": {k: t.entry_role(k) for k in orgmod.ENTRY_TYPES},
                # seats with a trigger (§4.9b, TD-098): what the manager reads to fill each one
                "seats": [{"name": s.name, "role": s.role, "trigger": s.trigger, "after": s.after} for s in t.seats],
                "members": sum(len(m.names()) for m in t.members),
                # each line its size sets to other than its count (§4.9 *A team's size*, TD-1164)
                "sizes": size_words(t.size, t),
                # the definition's roles in its order, each with the names that hold it — the team's
                # *who for what* lines (design §4.5a ***i*** mark, TD-171)
                "roles": role_holders(t),
                "live": n_live,
                # how many crew records carry its badge: none is *a team with no record* (§6 rule 8, TD-781)
                "records": len(mine),
                # only when nothing is live: a team still running is described by what it is doing
                "wound_down": down,
                # …who closed it, how soon and why (§4.5a *wound down* note, TD-265): only when it did
                **(wound_down_note(t, mine, names) if down else {}),
                # …and whether rule 9 ended it: its manager carries the tick's mark (§6, TD-241)
                "by_tick": not n_live and any(closed_finished(s) and not s.get("superseded_by") for s in mine),
                # …and when something is live but every live session is idle and declared (TD-099)
                "concluded": {k: f[k] for k in ("at", "restart", "names")} if f and not f["why"] else None,
                # …and when it is not, what keeps it from the reading, a clause per session (TD-241)
                "not_concluded": list(f["why"]) if f else [],
            }
        )
    return rows_out


# ── start ─────────────────────────────────────────────────────────────────────────────────────


def files_via(call: Call) -> teams.Files:
    """How a plan reads a checkout on another host that is not a directory here (a machine node):
    the home's `host_files`, confined to the checkout on that host (§4.4a, TD-057 step 4b.3). Any
    refusal — the host unreachable, a path outside the checkout — is the plan's `OSError`, so the
    start stops before anything is created."""

    def files(host: str, directory: str, paths: list[str]) -> dict[str, str | None]:
        try:
            got = call("host_files", host=host, dir=directory, paths=paths)
        except Exception as e:  # noqa: BLE001 — whatever the transport raised, nothing was started
            raise OSError(f"{host}: {e}") from e
        return dict((got or {}).get("files") or {})

    return files


def repos_via(call: Call) -> orgmod.ReposOf:
    """How the aggregate asks another host for its registered checkouts (design §4.9 *Where a
    repo's team lands*, TD-229 slice 3): the home's `host_repos`. Any refusal — the host
    unreachable, a node on a build without the `repos` link method — is `OSError`, which the
    landing reads as *unknown*, never as *holds no repo*."""

    def repos_of(host: str) -> list[str]:
        try:
            got = call("host_repos", host=host)
        except Exception as e:  # noqa: BLE001 — whatever the transport raised, the registry is unknown
            raise OSError(str(e)) from e
        repos = (got or {}).get("repos")
        if not isinstance(repos, list):
            raise OSError(f"{host} answered its registry with no list of checkouts")
        return [str(r) for r in repos]

    return repos_of


NOTHING_TO_PICK = "nothing to pick: every lane is empty, so the team will wind down as soon as it starts"
# the page's kinds in the kind bar's order, each in its word (§4.4 *Repo facts*; `ui.repo.LEDGER_LISTS`,
# written out since the page imports this module): how a lane's count reads by kind before a start
LANE_WORDS = (
    ("pickable", "pickable"),
    ("design", "design"),
    ("for-you", "for you"),
    ("live-check", "live check"),
    ("blocked", "blocked"),
    ("evaluation", "evaluation"),
    ("other", "other"),
)


def _lane_count(role: str, got: dict[str, Any]) -> str:
    """One role's part of the lanes line: *grinder: 1 pickable, 6 live check*."""
    n, by_kind = got["n"], got["by_kind"]
    count = (
        "ledger unreadable"
        if n is None
        else ", ".join(f"{by_kind[k]} {w}" for k, w in LANE_WORDS if by_kind.get(k))
        if n
        else "0"
    )
    return f"{role}: {count}"


def lanes(call: Call, org: orgmod.Org, name: str, host: str) -> dict[str, Any] | None:
    """What every lane the start creates holds before it (design §4.5a team card **Start**, *What the
    lanes hold, before the start*; TD-262, built by TD-265; TD-558, built by TD-563): the manager's where
    its role carries one and each member role's once — the lanes the team's records carry once it runs
    — each read against its checkout's ledger as rules 6 and 8 read it (`ledger.lane_matches` over the
    home's `repos` reading, whatever the entry's page kind) and said by the page's kinds: *grinder: 3
    pickable, 1 live check · designer: 0*. Returns `{line, empty, roles}`, `roles` as `{role: {n,
    by_kind}}` — `n` None for a ledger that cannot be read, which is *unknown*, never empty — and `ids`,
    the distinct ids every lane read matched, each once (a team with no record says *its lanes hold n
    entries* from it, §6 rule 8 *A team with no record*, TD-781). `empty`
    only when every lane was read and none matched; `unserved`, the start's refusal, for a team of an
    unserved repo, whose lanes read empty (§5 *The seams*, TD-1011). None when there is nothing to
    say: no launch has a lane, or the plan itself fails, which the start reports in its own words."""
    try:
        plan = teams.plan(org, name, host, files=files_via(call))
    except (teams.TeamError, ValueError, OSError):
        return None
    holders = [x for x in [plan.lead, *plan.members] if x is not None and x.lane]
    if not holders:
        return None
    try:
        got = call("repos")
        readings = got if isinstance(got, dict) else {}
    except Exception:  # noqa: BLE001 — no reading is every lane unknown, never a refused start
        readings = {}
    roles: dict[str, dict[str, Any]] = {}
    ids: dict[str, None] = {}  # every lane's matches, each id once, in the ledger's order per lane
    for x in holders:
        if x.role in roles:
            continue  # a role once: its members share a lane (§4.9)
        reading = readings.get(str(x.dir)) or {}
        led = reading.get("ledger") or {}
        entries = led.get("entries") if "error" not in led else None
        if isinstance(entries, list) and seams_mod.unserved(reading):
            roles[x.role] = {"n": 0, "by_kind": {}}  # an unserved repo's lanes read empty (§5, TD-1011)
        elif isinstance(entries, list):
            mine = [e for e in entries if isinstance(e, dict) and ledger_mod.lane_matches(x.lane, e, name)]
            by_kind = {k: sum(1 for e in mine if (e.get("for_page") or "other") == k) for k, _ in LANE_WORDS}
            roles[x.role] = {"n": len(mine), "by_kind": by_kind}
            ids.update((str(e.get("id")), None) for e in mine if e.get("id"))
        else:
            roles[x.role] = {"n": None, "by_kind": {}}
    line = " · ".join(_lane_count(role, got) for role, got in roles.items())
    out = {"line": line, "empty": all(r["n"] == 0 for r in roles.values()), "roles": roles, "ids": list(ids)}
    return out | ({"unserved": why} if (why := unserved(call, plan)) else {})


def keep_mail_for(
    call: Call, verdicts: Mapping[str, Mapping[str, Any]], caller: str | None, *, concluded: bool = True
) -> tuple[set[str], list[str]]:
    """The members whose create asks `keep_mail` (§4.10 *The name coming back adopts it*, TD-274):
    each whose name a **closed** record holds — or, with `concluded`, a live one a Start on a
    concluded team closes first — so a lapse note or an answer left there while the name was gone
    is the successor's. Asked only where the host agent grants it, a person or one of that record's
    controllers (§4.9b, §9 invariant 9), so the start stays all or nothing; anyone else's member
    starts empty, as §4.1 has it, and a note names it and why. Returns `(names, notes)`."""
    closed = {
        n: v for n, v in verdicts.items() if v.get("verdict") == "supersede" and v.get("holder_state") == "closed"
    }
    if concluded:
        closed |= {n: v for n, v in verdicts.items() if v.get("verdict") == "live"}
    if not closed or caller is None:
        return set(closed), []
    ctl = {str(s.get("id")): s.get("controllers") or [] for s in call("list")}
    keeps, notes = set(), []
    for n, v in closed.items():
        holder = str(v.get("holder") or "")
        if caller in ctl.get(holder, []):
            keeps.add(n)
        else:
            notes.append(
                f"{n} starts with an empty mailbox: {caller} is not a controller of {holder}, the closed record "
                "whose mail it would keep — a person's start keeps it (design §4.9b)"
            )
    return keeps, notes


def readings_via(call: Call) -> dict[str, Any]:
    """The home's repo readings (the `repos` RPC), or {} where it cannot be asked: what `ao org check`
    reads a ledger's `Team` declaration from (§4.4 *A stale team*, TD-730), as a start does."""
    try:
        got = call("repos")
    except Exception:  # noqa: BLE001 — no reading says nothing, never a failed check
        return {}
    return got if isinstance(got, dict) else {}


def unserved(call: Call, plan: teams.Plan) -> str | None:
    """Why a start is refused for a team of an unserved repo (§5 *The seams*, §4.7 *Teams*, TD-1011),
    naming each lack in §5's words, or None: the home's reading (the `repos` RPC) of each checkout the
    plan launches in. A repo with no reading, or one read by an agent that predates `serve`, passes —
    a repo is never unserved on a guess."""
    roots = list(dict.fromkeys(str(x.dir) for x in plan.launches))
    readings = readings_via(call)
    for root in roots:
        here = Path(root).resolve()
        r = next((v for k, v in readings.items() if isinstance(v, dict) and Path(k).resolve() == here), {})
        if lacks := seams_mod.unserved(r):
            return f"{plan.team}: {r.get('name') or here.name} is {'; '.join(lacks)} (design §5 The seams)"
    return None


def undeclared(call: Call, org: orgmod.Org, plan: teams.Plan, host: str) -> str | None:
    """Why a start is refused for a team its repo's ledger does not declare (§4.4 *The move from one
    team to two*, TD-730), or None: where the definitions of the team's repo hold two or more teams
    and the `declared_teams` of the home's reading (the `repos` RPC, so a start on another host reads
    the home's checkout) leave this one out. A repo with no reading, or a ledger that did not parse,
    passes, and `ao org check` names the lack once a reading exists."""
    roots = list(dict.fromkeys(str(x.dir) for x in plan.launches))
    try:
        got = call("repos")
        readings = got if isinstance(got, dict) else {}
    except Exception:  # noqa: BLE001 — no reading passes, as a ledger that did not parse does
        return None
    for root in roots:
        here = Path(root).resolve()
        r = next((v for k, v in readings.items() if isinstance(v, dict) and Path(k).resolve() == here), {})
        led = r.get("ledger") or {}
        if "declared_teams" not in led or "error" in led:
            continue
        declared = [str(t) for t in led.get("declared_teams") or []]
        defined = [t["team"] for t in teams.entry_teams(org, str(here), plan.host or host)]
        if len(defined) < 2 or plan.team.casefold() in {t.casefold() for t in declared}:
            continue
        names = [*declared, *(t for t in defined if t.casefold() not in {d.casefold() for d in declared})]
        return (
            f"{plan.team}: {r.get('name') or root} has {len(defined)} teams and its ledger's Fields: line does "
            f"not declare {plan.team} — add `Team = {' | '.join(names)}`, and a Team: line on each open entry "
            "a lane takes, by PR (design §4.4 The move from one team to two)"
        )
    return None


def start(
    call: Call, org: orgmod.Org, name: str, host: str, *, profile: str | None = None, caller: str | None = None
) -> tuple[teams.Plan, dict[str, Any]]:
    """`ao team start <name>` and the strip's **Start** (design §4.9): resolve the definition, check
    *everything* — checkouts, roles, profiles, briefs, and every session name under §4.1's rule —
    then create the lead and each member with `controllers: [lead id]`.

    Raises `TeamError` (or `NamesHeld`) before anything is created, and `PartialStart` if a create
    fails after the checks passed. Returns the plan and the result the callers render. `caller` is
    the session running it (`SHIFTLEAD_SESSION`), None for a person: it decides where a closed
    member's mail is kept (`keep_mail_for`).

    A member the definition renamed or dropped (§4.9 *A member renamed or removed in the definition*,
    TD-706) is read as Apply reads it (`renames`), after the checks and a concluded team's closes:
    each removal is marked sat out (`relaunch {sit_out, dropped}`) and each newcomer paired with an
    orphan — or held by one an Apply marked — is created succeeding it (`succeeds`), so no definition
    name is left with two records; `moved` lists them. A person's act, as both calls are: a session's
    start of a team the definition renamed is refused, and so is one whose orphans are still live."""
    # the Settings sweep switch (§4.9b *The switch*, TD-1091): a home not reached, or a refusal, gives the
    # team no sweep seat, and the start says so
    try:
        got = call("sweep_switch")
    except Exception:  # noqa: BLE001 — whatever the transport raised, the answer is the same
        got = None
    switch: dict[str, Any] | None = got if isinstance(got, dict) else None
    plan = teams.plan(org, name, host, profile=profile, files=files_via(call), sweep=switch)
    if switch is None:
        plan.notes.append("sweep: the switch not read — no sweep seat")
    if not plan.launches:
        raise teams.TeamError(f"team {name} starts nothing: a person leads it and it has no members")
    if why := unserved(call, plan) or undeclared(call, org, plan, host):
        raise teams.TeamError(why)
    on = {"host": plan.host} if plan.host else {}
    if plan.host:
        # Design §4.4a "Teams across hosts": *every checkout exists on the record's host*, asked of
        # that host's node through the home — and the whole team refused while it is unreachable.
        for d in dict.fromkeys(str(x.dir) for x in plan.launches):
            try:
                seen = call("host_dir", host=plan.host, dir=d)
            except Exception as e:  # noqa: BLE001 — whatever the transport raised, the answer is the same
                raise teams.TeamError(f"team {name} was not started — {plan.host}: {e}") from e
            if not seen.get("exists"):
                raise teams.TeamError(f"team {name} was not started — {d} does not exist on {plan.host}")
    # §4.1's rule, asked of the agent rather than reimplemented here (`name_check`, the same verdict
    # `create` and the New session form use), for every session before any of them exists.
    verdicts = {x.name: call("name_check", dir=str(x.dir), name=x.name, repo=str(x.dir), **on) for x in plan.launches}
    held = [v for v in verdicts.values() if v.get("verdict") in ("live", "suspended")]
    # Only when a name is held: a concluded team's declared sessions hold its members' names, so a
    # concluded team whose names are all free would be one whose definition renamed every member.
    # who asks a closed member's mail kept, decided before anything is closed or created (TD-274)
    keeps, notes = keep_mail_for(call, verdicts, caller)
    succeeds, removals = _start_moves(plan, call("list"))
    if (succeeds or removals) and caller is not None:
        gone = ", ".join(str(r.get("name")) for r in [*succeeds.values(), *removals])
        raise teams.TeamError(
            f"team {name} was not started — its definition renamed or removed {gone}: a person's Start or Apply "
            "takes those, never a session's (design §4.9 A member renamed or removed in the definition)"
        )
    closed = _close_concluded(call, org, name, held) if held or succeeds or removals else []
    if succeeds or removals:
        succeeds, removals = _start_moves(plan, call("list"))  # read again: the closes ended some
        up = [str(r.get("name")) for r in [*succeeds.values(), *removals] if r.get("state") not in DEAD]
        if up:
            raise teams.TeamError(
                f"team {name} was not started — {', '.join(up)} still running: a live team takes a rename or a "
                "removal by Apply (design §4.9 A member renamed or removed in the definition)"
            )
    moved = [f"{r.get('name')} → {n}" for n, r in succeeds.items()]
    for r in removals:
        try:
            call("relaunch", id=r["id"], sit_out=True, dropped=True)
        except AgentError as e:
            raise teams.TeamError(
                f"team {name} was not started — {r.get('name')} could not be marked removed: {e}"
                + (f" ({', '.join(moved[len(succeeds) :])} marked already)" if len(moved) > len(succeeds) else "")
            ) from e
        moved.append(f"{r.get('name')} removed")

    def params(x: teams.Launch, controllers: list[str]) -> dict[str, Any]:
        # `team_start`: the home keeps the start's usage reading for rule 9's note (§4.9a, TD-468); a
        # newcomer succeeds its orphan, which moves the mail, so it never asks `keep_mail` beside it
        if x.name in succeeds:
            return {**x.create_params(controllers), "team_start": True, "succeeds": str(succeeds[x.name]["id"])}
        return {**x.create_params(controllers), "team_start": True, **({"keep_mail": True} if x.name in keeps else {})}

    created: list[dict[str, Any]] = []
    notes += plan.notes  # said, and the start goes ahead (a seat without its primer, §4.9b)
    lead_id = ""
    try:
        if plan.lead:
            # A manager on call (§6 rule 3 *A Start writes the seat and never fills it*, TD-410): its
            # record written alone, closed with no pane, the launch record beside it — the tick fills
            # it the first time a reading is due, a question in the mail kept here included. Its id
            # is the name's either way, so every member's `controllers` and `{manager}` name it.
            rec = call("create", **params(plan.lead, []), **on_call_gate(plan.lead))
            created.append(rec)
            lead_id = str(rec["id"])
            if plan.manager_id and lead_id != plan.manager_id:
                notes.append(
                    f"the manager started as {lead_id}, but the members' briefs name {plan.manager_id} — "
                    "a stale tmux session holds that id; its members' done lines will not reach it until a restart"
                )
        if plan.techlead:
            # The seat is its manager's member (design §4.9b): the manager is its controller, as
            # for any member. Its id was named in every brief before it existed (`{techlead}`).
            rec = call("create", **params(plan.techlead, [lead_id] if lead_id else []))
            created.append(rec)
            if str(rec["id"]) != plan.techlead_id:
                notes.append(
                    f"the techlead started as {rec['id']}, but the briefs name {plan.techlead_id} — "
                    "a stale tmux session holds that id; tell the team, or restart it once that session is gone"
                )
        for x in plan.seats:
            # A seat with a trigger (§4.9b, TD-098): started with the team, as the techlead is, so it
            # runs once now and is on call after; its manager fills it again when its trigger is met.
            created.append(call("create", **params(x, [lead_id] if lead_id else [])))
        for m in plan.members:
            # A person runs a team start, so no attenuation applies (§4.8 create rule); a
            # lead running it is subject to it as for any create, in the host agent.
            created.append(call("create", **params(m, [lead_id] if lead_id else [])))
    except Exception as e:
        raise PartialStart(name, created, plan, e) from e
    # §9 invariant 5, as TD-041 made it a gate: no session acts on an interactive one, so a member
    # the definition starts interactive carries `controllers: [lead]` that can never fire. The list
    # is set and the start stands — it is a fact about the definition — but it is said out loud.
    out_of_reach = [x.name for x in plan.members if not x.unattended] if lead_id else []
    # TD-042: a brief that names one run cannot start the next. The start stands — the brief is
    # prose and the judgement is the author's — but it is said out loud, like `out_of_reach`.
    return plan, {
        "team": name,
        "closed": closed,  # the concluded sessions closed before the creates (§4.9a, TD-099)
        "moved": moved,  # the definition's renames and removals (§4.9, TD-706): *grind-1 → mill-1*, *hunt removed*
        "manager": lead_id or None,
        "sessions": created,
        "out_of_reach": out_of_reach,
        "unrepeatable": list(plan.warnings),
        "notes": notes,
    }


# ── a switch of flow: the records against the compile, and Apply (design §4.9c *Switching*) ───


@dataclass
class Difference:
    """One member whose record differs from what the team's current flow compiles to (§4.9c): `act`
    is what Apply does — `sit_out` (wind it down by the home's `relaunch {sit_out}`), `start` (create
    it as **Members…**'s add does), `relaunch` (hand the home its new launch) — or `left`, what Apply
    never touches (a person's session the flow sits out). `what` names each field that differs. Two
    acts are the definition's, read on a stopped team too (§4.9 *A member renamed or removed in the
    definition*, TD-703): `rename`, a record the definition no longer names paired with the newcomer
    `launch` that takes its place, and `removed`, one left over with no newcomer (`renames`)."""

    name: str
    act: str
    what: list[str] = field(default_factory=list)
    record: dict[str, Any] | None = None
    launch: teams.Launch | None = None
    seat: bool = False  # a seat the definition names that the run has no record of (§4.9c, TD-399)

    def line(self, flow: str | None) -> str:
        if self.act == "rename" and self.launch is not None:
            return f"{self.name} → {self.launch.name}: renamed"
        if self.act == "removed":
            return f"{self.name}: removed from the definition"
        if self.act == "sit_out":
            return f"{self.name}: sits out under {flow}"
        if self.act == "start":
            return f"{self.name}: starts under {flow}" if flow else f"{self.name}: starts"
        if self.act == "left":
            return f"{self.name}: sits out under {flow} — a person's session, left running: close it yourself"
        if self.definition:  # its profile alone (TD-619): *techlead-ao-1: profile grind-fable → grind (next restart)*
            return f"{self.name}: {'; '.join(self.what)} (next restart)"
        return f"{self.name}: relaunched — {'; '.join(self.what)}"

    @property
    def definition(self) -> bool:
        """A relaunch whose one difference is the profile the definition names (§4.9c *Switching*,
        TD-619): the definition's, which a flow does not compile, so the mark reads **definition
        changed** where nothing else differs. A rename and a removal are the definition's too (TD-703)."""
        if self.act in MOVED:
            return True
        return self.act == "relaunch" and bool(self.what) and all(w.startswith("profile ") for w in self.what)

    def as_dict(self, flow: str | None) -> dict[str, Any]:
        rec = self.record or {}
        return {
            "name": self.name,
            "id": rec.get("id"),
            "act": self.act,
            "what": list(self.what),
            "line": self.line(flow),
            "seat": self.seat,
            "definition": self.definition,
            **({"to": self.launch.name} if self.act == "rename" and self.launch is not None else {}),
        }


# the acts a definition's rename or removal reads as (§4.9 *A member renamed or removed*, TD-703): the
# one difference read on a team with nothing live, since rule 8 replays its ended records
MOVED = ("rename", "removed")


def definition_changed(diffs: list[dict[str, Any]], flow: str | None) -> bool:
    """Whether the team header's mark reads **definition changed — Apply** rather than *flow changed*
    (§4.5a, §4.9c, TD-399): the team runs no flow, or every difference is a seat to start or a member's
    profile alone (TD-619)."""
    return bool(diffs) and (
        not flow or all((d.get("seat") and d.get("act") == "start") or d.get("definition") for d in diffs)
    )


def stage_of(prompt_from: Any) -> str | None:
    """The `{stage}` file a launch's `prompt_from` names, or None where the slot is text (§4.9c)."""
    slots = prompt_from.get("slots") if isinstance(prompt_from, dict) else None
    slot = slots.get(repoconfig.STAGE_PLACEHOLDER) if isinstance(slots, dict) else None
    f = slot.get("file") if isinstance(slot, dict) else None
    return f if isinstance(f, str) else None


def _record_stage(record: dict[str, Any]) -> tuple[bool, str | None]:
    """The stage file a record's `brief` read, as `(known, path)`: a stage brief is a flow's file or a
    template's `<stem>.stage.md`. Unknown where the home recorded no `brief` (a node member's, an
    unreadable file): nothing is claimed about what was not read."""
    sources = (record.get("brief") or {}).get("sources") if isinstance(record.get("brief"), dict) else None
    if not isinstance(sources, list):
        return False, None
    for src in sources:
        path = src.get("path") if isinstance(src, dict) else None
        if isinstance(path, str) and _is_stage(Path(path)):
            return True, path
    return True, None


def _is_stage(path: Path) -> bool:
    """A template's `<stem>.stage.md`, or a brief of a flow: the package's, the org's `~/.shiftlead/flows/`
    or a repo's `.shiftlead/flows/`."""
    if path.name.endswith(repoconfig.STAGE_SUFFIX) or path.is_relative_to(flowdefs.PACKAGE_DIR):
        return True
    if path.is_relative_to(flowdefs.org_dir()):
        return True
    parts = path.parts
    return any(parts[i : i + 2] == flowdefs.REPO_DIR.parts for i in range(len(parts) - 1))


def _short(path: str | None) -> str:
    return "/".join(Path(path).parts[-2:]) if path else "none"


def _reader(review: Any) -> str:
    if isinstance(review, dict) and isinstance(review.get("chain"), list):  # a flow's chain (§4.9c, TD-315)
        return " then ".join(str(x.get("reader") or "?") for x in review["chain"] if isinstance(x, dict)) or "none"
    return str(review.get("reader") or "none") if isinstance(review, dict) else "none"


def _current(name: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The record a member's name stands for: the live one, else the newest not resumed as another."""
    mine = [r for r in records if r.get("name") == name and not r.get("superseded_by")]
    up = [r for r in mine if r.get("state") not in DEAD]
    return (up or mine or [None])[-1]


def _next_run(record: dict[str, Any]) -> dict[str, Any]:
    """The lane and `review` a member runs next: what a person's Apply handed the home, carried on the
    record's `relaunch` mark until the create that runs it (§4.9c *Switching*, TD-355), else the
    record's own. A mark written before it carried them (`{at}` alone) says nothing of them."""
    mark = record.get("relaunch")
    return mark if isinstance(mark, dict) and "lane" in mark and "review" in mark else record


def _next_profile(record: dict[str, Any]) -> str:
    """The profile a member runs next (§4.9c *Switching*, TD-619): its `relaunch` mark's once Apply has
    run, else the record's own — "" the default's. A mark written before it carried one says nothing
    of it."""
    mark = record.get("relaunch")
    if isinstance(mark, dict) and "profile" in mark:
        return str(mark.get("profile") or "")
    return str(record.get("profile") or "")


def _profile_moved(record: dict[str, Any], x: teams.Launch) -> list[str]:
    """The profile line, *profile grind-fable → grind*, where the one the definition resolves for the
    member (`teams.Launch.profile`: its own `profile:`, else its role's, else the team's) is not the
    one it runs next; nothing where they match."""
    was, now = _next_profile(record), x.profile or ""
    return [] if was == now else [f"profile {was or 'default'} → {now or 'default'}"]


def _review_key(review: Any) -> Any:
    """A `review` as the flow means it (§4.9c): its reader, or each chain link's reader in order, each
    with its `held` as a set, and its bound — so a record whose `held` is the compiled set in another
    order is no difference (`teams.flow_redundant` compares so)."""
    if not isinstance(review, dict) or not review:
        return None
    bound = review.get("bound", teams.REVIEW_BOUND)
    if isinstance(review.get("chain"), list):
        links = tuple((x.get("reader"), frozenset(x.get("held") or ())) for x in review["chain"] if isinstance(x, dict))
        return ("chain", links, bound)
    return ("reader", review.get("reader"), frozenset(review.get("held") or ()), bound)


def _pairing(
    plan: teams.Plan, sessions: list[dict[str, Any]]
) -> tuple[list[tuple[dict[str, Any], teams.Launch]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """`renames`, with the newcomers an applied orphan already holds (its `relaunch` mark's `name`), each
    by name with the orphan that holds it."""
    mine = crew(plan.team, sessions)
    names = {x.name for x in plan.launches} | set(plan.sit_out)
    gone = [n for n in dict.fromkeys(str(r.get("name") or "") for r in mine) if n and n not in names]
    orphans = [
        r
        for n in gone
        if (r := _current(n, mine)) is not None
        and not (r.get("sit_out") or sat_out(r) or r.get("superseded_by") or r.get("run_only"))
    ]  # a run-only member, live or exited inside its run, is neither: it ends with the run (§4.9, TD-1166)
    carried = {str(r.get("name")) for r in badged(plan.team, sessions) if not r.get("superseded_by")}
    newcomers = [x for x in plan.launches if x.name not in carried]
    held: dict[str, dict[str, Any]] = {}
    for r in list(orphans):
        mark = r.get("relaunch")
        to = mark.get("name") if isinstance(mark, dict) else None
        if to and any(x.name == to for x in newcomers):
            held[str(to)] = r
            orphans.remove(r)
    newcomers = [x for x in newcomers if x.name not in held]
    orphans.sort(key=lambda r: str(r.get("created") or ""))
    pairs: list[tuple[dict[str, Any], teams.Launch]] = []
    removals: list[dict[str, Any]] = []
    for r in orphans:
        x = next((x for x in newcomers if x.role == str(r.get("role") or "")), None)
        if x is None:
            removals.append(r)
            continue
        newcomers.remove(x)
        pairs.append((r, x))
    return pairs, removals, held


def _start_moves(
    plan: teams.Plan, sessions: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """What Start does with the definition's renames and removals (§4.9, TD-706): each newcomer, by
    name, with the orphan it succeeds — paired, or held by one an Apply marked — and the removals."""
    pairs, removals, held = _pairing(plan, sessions)
    return {**held, **{x.name: r for r, x in pairs}}, removals


def renames(
    plan: teams.Plan, sessions: list[dict[str, Any]]
) -> tuple[list[tuple[dict[str, Any], teams.Launch]], list[dict[str, Any]]]:
    """A team's records the definition renamed or dropped (design §4.9 *A member renamed or removed in
    the definition*, TD-703), as `(renames, removals)`. The **orphans** are the team's crew records
    (`crew`: never a person's session) that are current (not superseded), not sat out and not run-only (§4.9
    *A member started from the form*, TD-1166), whose name the definition no longer holds; the **newcomers**
    the launches whose name no current record of the team carries. Within one role (the record's `role`
    against the launch's) the orphans, by `created`, are paired with the newcomers, in the definition's
    order: each pair `(record, launch)` is a rename, an orphan left over a removal, and a newcomer left over
    the start it already is. An orphan whose `relaunch` mark already carries a newcomer's `name` was
    applied: it is neither, and the newcomer is held by it. The card, `ao team list`, `ao team flow`, Apply
    and Start read this one pairing."""
    pairs, removals, _ = _pairing(plan, sessions)
    return pairs, removals


def differences(plan: teams.Plan, sessions: list[dict[str, Any]]) -> list[Difference]:
    """How a live team's records differ from what its current flow compiles to (design §4.9c
    *Switching*), member by member: lane, `review`, the `{stage}` file's path, and who should be
    running — never `{flow}`'s text, which names no member, and nothing of a person's session but
    that the flow sits it out. A seat the definition names — the techlead, a `seats:`
    entry, a manager on call (§6 rule 3, TD-410) — with no record is a `start` on any live team (§4.9c,
    TD-399), and a team that runs no flow is compared on its seats alone. The profile the definition
    resolves is compared too, on every live unattended member and every seat, running or closed
    between fills (TD-619) — under a flow or none, since it is the definition's: a closed seat's next
    fill replays its record. A record the definition renamed or dropped (`renames`, TD-703) is a
    `rename` or a `removed`, first, and the one difference read with nothing live."""
    mine = badged(plan.team, sessions)
    pairs, removals, held = _pairing(plan, sessions)
    moved = [Difference(str(r.get("name")), "rename", record=r, launch=x) for r, x in pairs]
    moved += [Difference(str(r.get("name")), "removed", record=r) for r in removals]
    if not live(crew(plan.team, sessions)):
        return moved
    taken = set(held) | {x.name for _, x in pairs}  # a paired or held newcomer is no start of its own
    on_call_lead = plan.lead if plan.lead is not None and on_call_gate(plan.lead) else None
    seats = {x.name for x in (plan.techlead, on_call_lead, *plan.seats) if x is not None}
    if plan.flow is None:
        out = list(moved)
        for x in plan.launches:
            if x.name in taken:
                continue
            rec = _current(x.name, mine)
            if rec is None:
                if x.name in seats:
                    out.append(Difference(x.name, "start", launch=x, seat=True))
                continue
            seat = x.name in seats or rec.get("seat") is not None
            if persons(rec) or rec.get("sit_out") or sat_out(rec) or (rec.get("state") in DEAD and not seat):
                continue
            if what := _profile_moved(rec, x):
                out.append(Difference(x.name, "relaunch", what, record=rec, launch=x))
        return out
    out: list[Difference] = list(moved)
    for name in plan.sit_out:
        rec = _current(name, mine)
        if rec is None or rec.get("state") == "closed" or rec.get("sit_out") or sat_out(rec):
            continue
        if rec.get("seat") is not None or rec.get("state") == "scheduled":
            continue  # the home never sits one out (`_sit_out`)
        out.append(Difference(name, "left" if persons(rec) else "sit_out", record=rec))
    for x in plan.launches:
        if x.name in taken:
            continue
        rec = _current(x.name, mine)
        if rec is None or sat_out(rec):
            # a seat the run lacks is Apply's to create (TD-399)
            out.append(Difference(x.name, "start", record=rec, launch=x, seat=rec is None and x.name in seats))
            continue
        if rec.get("sit_out"):
            continue  # still winding down from a sit-out: once the home has closed it, it reads `start`
        if persons(rec):
            continue  # a person's lane, brief and profile are theirs
        if rec.get("state") == "closed":
            # a closed member is the next Start's, but a seat's next fill replays its record (TD-619)
            if (x.name in seats or rec.get("seat") is not None) and (what := _profile_moved(rec, x)):
                out.append(Difference(x.name, "relaunch", what, record=rec, launch=x))
            continue
        what = []
        runs = _next_run(rec)
        if list(runs.get("lane") or []) != list(x.lane):
            what.append(f"lane {', '.join(runs.get('lane') or []) or 'none'} → {', '.join(x.lane) or 'none'}")
        if _review_key(runs.get("review")) != _review_key(x.review):
            what.append(f"reader {_reader(runs.get('review'))} → {_reader(x.review)}")
        known, was = _record_stage(rec)
        now = stage_of(x.prompt_from)
        if known and was != now:
            what.append(f"stage {_short(was)} → {_short(now)}")
        what += _profile_moved(rec, x)
        if what:
            out.append(Difference(x.name, "relaunch", what, record=rec, launch=x))
    return out


def flow_changed(
    call: Call, org: orgmod.Org, name: str, host: str, sessions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """What a client that reads a live team says of its records against its current flow (§4.9c
    *Switching*: the Sessions page, `ao team list`, `ao team flow`), one `Difference.as_dict` per member;
    with nothing live only the definition's renames and removals (TD-703), since a stopped team
    compiles nothing until its next start; a team with no `flows:` is read on its seats alone
    (TD-399). Raises what `teams.plan` raises: the caller says why the records were not compared."""
    t = org.teams.get(name)
    if t is None or not crew(name, sessions):
        return []
    plan = teams.plan(org, name, host, files=files_via(call))
    return [d.as_dict(plan.flow) for d in differences(plan, sessions)]


def flow_view(call: Call, org: orgmod.Org, name: str, here: str, sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """A team's flows as every client that reads a team shows them (design §4.9c *What is shown*,
    *Switching*; `ao team list`, the Sessions page's team header): `flow`, the current one or None for a
    team that lists none; `flows`, `teams.flow_rows`; `flow_note`, `teams.flow_unlisted`; and
    `differences`, a live team's records against its current flow (`flow_changed`) — empty where the
    plan fails, which the flows' own lines say. Reads files: once per page load or listing, never
    per delta."""
    t = org.teams.get(name)
    if t is None:
        return {"flow": None, "flows": [], "flow_note": "", "differences": []}
    if not t.flows:  # no flow: its seats alone, which a live team may lack (§4.9c, TD-399)
        out: dict[str, Any] = {"flow": None, "flows": [], "flow_note": "", "differences": []}
        with contextlib.suppress(teams.TeamError, ValueError, OSError, AgentError):
            out["differences"] = flow_changed(call, org, name, here, sessions)
        return out
    out = {
        "flow": teams.current_flow(t),
        "flows": teams.flow_rows(org, t, t.host or here, here),
        "flow_note": teams.flow_unlisted(t),
        "differences": [],
    }
    with contextlib.suppress(teams.TeamError, ValueError, OSError, AgentError):  # said by the flows' lines
        out["differences"] = flow_changed(call, org, name, here, sessions)
    return out


def check_pick(call: Call, org: orgmod.Org, name: str, here: str, flow: str) -> orgmod.Org:
    """A pick of `flow` checked before it is written (design §4.5a the Settings page's **flow**, where
    the team card's **Flow** pick moved, TD-418; §4.9c *Switching*): refused, in `teams.TeamError`, for a flow the team
    does not list or one it cannot follow — the pick draws those disabled, with the reason. Returns
    the org as if picked."""
    t = teams.find(org, name)
    if flow not in t.flows:
        raise teams.TeamError(f"team {name} lists {', '.join(t.flows) or 'no flows'}, not {flow!r} (design §4.9c)")
    picked = orgmod.with_settings(org, {name: {"flow": flow}})
    rows = teams.flow_rows(picked, picked.teams[name], t.host or here, here, files=files_via(call))
    if cannot := next((r["cannot"] for r in rows if r["name"] == flow), ""):
        raise teams.TeamError(cannot)
    return picked


def pick_flow(call: Call, org: orgmod.Org, name: str, here: str, flow: str) -> dict[str, Any]:
    """The Settings page's **flow** on Save and `ao team flow <team> <flow>` (§4.5a,
    §4.7, §4.9c *Switching*): checked (`check_pick`), written to `teams.<team>.flow` through
    `set_settings` — a person's own — and nothing more: Apply is the one gate that moves the running
    team (TD-356). Returns `{team, flow, differences, feature}` read against the written org — the
    records' differences (`flow_changed`, empty where they cannot be read: the flows' own lines say
    why), and `feature`, the role **Add entry**'s *feature* now opens where the pick moved it (§4.9c
    item 4), else None. What a switch leaves with a reader is Apply's to say (`apply`'s `stays`, §4.9c
    *What a switch leaves alone*), since a pick moves nothing (TD-365)."""
    check_pick(call, org, name, here, flow)
    t = teams.find(org, name)
    host = t.host or here
    was = _feature_role(org, t, host, here, call)
    got = call("set_settings", teams={name: {"flow": flow}})
    written = orgmod.with_settings(org, (got or {}).get("teams"))
    sessions = call("list")
    diffs: list[dict[str, Any]] = []
    with contextlib.suppress(teams.TeamError, ValueError, OSError, AgentError):  # said by the flows' lines
        diffs = flow_changed(call, written, name, here, sessions)
    now = _feature_role(written, written.teams[name], host, here, call)
    return {
        "team": name,
        "flow": flow,
        "differences": diffs,
        "feature": now if now != was else None,
    }


def _feature_role(org: orgmod.Org, team: orgmod.TeamDef, host: str, here: str, call: Call) -> str | None:
    try:
        return teams.entry_role(org, team, "feature", host, here, files=files_via(call))
    except (teams.TeamError, ValueError, OSError, AgentError):
        return None


def work_orders(r: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """A repo reading's work orders — its board's open decided lines, `board:<key>` (§4.4 *Board
    write-back*, TD-384) — as entries; none from an agent that predates them, and none in an unserved
    repo (§5 *The seams*, TD-1011)."""
    if seams_mod.unserved(r):
        return []
    got = ((r or {}).get("work_orders") or {}).get("orders")
    return [e for e in got if isinstance(e, dict) and e.get("id")] if isinstance(got, list) else []


def pr_orders(r: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """A repo reading's red PRs nobody holds, `pr:<n>` (§4.4 *A red PR nobody holds is a work order*,
    TD-613), as entries — owned by no one: every `free-pick` lane takes one (§4.9b *No anchor seat*,
    TD-757); none from an agent that predates them, and none in an unserved repo (§5 *The seams*, TD-1011)."""
    if seams_mod.unserved(r):
        return []
    got = ((r or {}).get("pr_orders") or {}).get("orders")
    return [e for e in got if isinstance(e, dict) and e.get("id")] if isinstance(got, list) else []


def lane_entries(r: Mapping[str, Any] | None) -> list[dict[str, Any]] | None:
    """What a team's lanes read of a repo (§4.4 *In a team's lanes*): the ledger's open entries and
    the work orders beside them — the board's decided lines (TD-384) and the red PRs nobody holds
    (TD-613) — or None where the ledger was not read. A sync PR's order comes before every entry and
    every other order (§4.4 *A sync PR is the team's at once*, TD-684). An unserved repo's lanes read
    empty (§5 *The seams*, TD-1011)."""
    entries = ((r or {}).get("ledger") or {}).get("entries")
    if entries is None:
        return None
    if seams_mod.unserved(r):
        return []
    prs = pr_orders(r)
    return [*(e for e in prs if e.get("sync")), *entries, *work_orders(r), *(e for e in prs if not e.get("sync"))]


WAIT_CLAMP = 40  # the Repo page's *waits: <words>*, clamped; the whole line is its hover (§4.5a **waits** mark)


def wait_words(e: Mapping[str, Any], short: bool = False) -> str:
    """What an entry whose wait stands waits for (design §4.4 *An entry says what it waits for*, §4.7
    `ao repo`, §4.5a *Repo page: waits mark*, TD-716): *waits until 2026-10-16* (`short`: *waits until
    10-16*), else *waits: <the line's words>* (`short`: clamped); '' while it does not wait. Read from
    the home's `waiting` mark, so a date passed says nothing."""
    w = e.get("waiting")
    if not isinstance(w, dict):
        return ""
    if w.get("on") == "until" and (date := str(w.get("until") or "")):
        return f"waits until {date[5:] if short else date}"
    why = str((e.get("waits") or {}).get("why") or "") or ("no date" if w.get("on") == "until" else "an event")
    if short and len(why) > WAIT_CLAMP:
        why = why[: WAIT_CLAMP - 1].rstrip() + "…"
    return f"waits: {why}"


def wait_line(e: Mapping[str, Any]) -> str:
    """The entry's `**Waits:**` line, whole, as the Repo page's waits mark shows it on hover (TD-716)."""
    w = e.get("waits") or {}
    if not isinstance(w, dict) or not w.get("on"):
        return ""
    return " ".join(x for x in ("Waits:", w["on"], w.get("date") or "", f"— {w['why']}" if w.get("why") else "") if x)


def waits_tally(ids: Collection[str], entries: Mapping[str, Mapping[str, Any]]) -> str:
    """How a lane's waiting entries wait (design §4.4 *Counted apart*, TD-716): *2 until a date (the
    first 2026-10-16), 2 on an event*, each part only where it counts one; an id the reading no longer
    carries is counted on an event."""
    dates = []
    events = 0
    for i in ids:
        w = (entries.get(i) or {}).get("waiting") or {}
        if w.get("on") == "until" and w.get("until"):
            dates.append(str(w["until"]))
        else:
            events += 1
    parts = [f"{len(dates)} until a date (the first {min(dates)})"] if dates else []
    if events:
        parts.append(f"{events} on an event")
    return ", ".join(parts)


def lane_kinds(r: Mapping[str, Any] | None) -> dict[str, Any]:
    """The ledger's counts by the page's kind, a work order — a decided line (§4.5a *Repo page:
    decided lines*, TD-384) or a red PR nobody holds (TD-613) — counted *pickable*, as the lanes take
    them; never in the priorities, which are the ledger's alone. An entry the home's settle clock
    withholds (`settling`, §4.4 *What settling withholds*, TD-710), and one whose wait stands
    (`waiting`, §4.4 *An entry says what it waits for*, TD-716), is not counted pickable, as `ao repo`
    counts it; its page kind is unchanged."""
    led = (r or {}).get("ledger") or {}
    kinds = dict(led.get("by_kind") or {})
    withheld = sum(
        1
        for e in led.get("entries") or ()
        if isinstance(e, dict) and e.get("for_page") == "pickable" and (e.get("settling") or e.get("waiting"))
    )
    if n := len(work_orders(r)) + len(pr_orders(r)) - withheld:
        kinds["pickable"] = max(0, int(kinds.get("pickable") or 0) + n)
    return kinds


def repo_lanes(
    entries: list[dict[str, Any]] | None, root: str | Path, sessions: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Each team servicing a repo, and what its lanes take of the repo's open entries (design §4.4
    *In a team's lanes*, TD-361): `ledger_mod.in_lanes` over the team's records in the repo — live or
    ended, never one resumed as another — with what a live record of the repo holds claimed. A team
    whose records carry no lane, and a repo whose ledger was not read, give nothing."""
    if entries is None:
        return {}
    mine = in_repo(sessions, root)
    held = {
        str(p.get("ref"))
        for s in mine
        if s.get("state") not in DEAD
        for p in s.get("progress") or []
        if isinstance(p, dict) and p.get("status") == "claimed"
    }
    out: dict[str, dict[str, Any]] = {}
    for team in sorted({str(s["team"]) for s in mine if s.get("team")}):
        got = ledger_mod.in_lanes(entries, [s for s in mine if s.get("team") == team], held)
        if got is not None:
            out[team] = got
    return out


def in_repo(sessions: Collection[Mapping[str, Any]], root: str | Path) -> list[Mapping[str, Any]]:
    """The records of a repo — `repo` its checkout, never one resumed as another — live or ended."""
    here = Path(root).resolve()
    return [
        s for s in sessions if s.get("repo") and Path(str(s["repo"])).resolve() == here and not s.get("superseded_by")
    ]


def serviced(root: str | Path, sessions: Collection[Mapping[str, Any]]) -> bool:
    """Whether a team services the repo: one of its records here carries a team (§4.4 *In a team's
    lanes*, `repo_lanes`' teams). A repo none does has no lane for a red PR's order, which is then an
    Inbox row (§4.5a *Inbox row: red PR*, TD-613)."""
    return any(s.get("team") for s in in_repo(sessions, root))


DRAFT_WHOSE = "no order while a draft"  # §4.4 *A draft is no work order*, TD-745
FORK_WHOSE = "its author's"  # §4.4 *A fork's PR is no work order*, TD-1285


def ready_to_precheck(p: Mapping[str, Any] | None) -> bool:
    """Whether an open PR row is a fork's PR ready to precheck (design §4.5 screen 11 *Review*, §4.5a *Inbox
    row: fork's PR*, TD-1292): open, a fork's, not a draft, not conflicting, its checks green, no
    `cadence/precheck` status on its head (`prechecked` False, which a GitLab row never carries) and a
    `precheck_line` the reading gave it. A sync PR is never ready. One test, read by the Inbox, the Queue
    and the Repo page."""
    if not isinstance(p, Mapping):
        return False
    return bool(
        p.get("state", "open") == "open"
        and p.get("fork")
        and not p.get("draft")
        and not p.get("conflicting")
        and not p.get("sync")
        and p.get("checks") == "green"
        and p.get("prechecked") is False
        and p.get("precheck_line")
    )


def red_prs(
    r: Mapping[str, Any] | None, sessions: Collection[Mapping[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    """A reading's open PRs that read red or conflicting (§4.4 *A red PR nobody holds is a work order*,
    TD-613), as the facet's *· n red* and the Repo page's tags draw them, oldest red first: `number`,
    `title`, `url`, `author`, `word` (*red*, else *conflicting*), `failing`, `red_since`, and `whose`
    — past `ORPHAN_AFTER`, *nobody's — the grinders' order* for one the reading lists as an order
    (*nobody's* where no team services the repo: its row is the Inbox's), *held by <names>* for one a
    live record of the repo holds, as the reading names them (`pr_orders.held`, TD-652), *no order while
    a draft* for a draft (not a sync PR) nobody holds (TD-745), *its author's* for a fork's PR nobody holds, a draft
    included (TD-1292); before it, ''.
    `sessions` the records, or the pages' views."""
    r = r or {}
    mine = in_repo(sessions, str(r.get("root") or "")) if r.get("root") else []
    orders = {e.get("pr") for e in pr_orders(r)}
    holders = ((r.get("pr_orders") or {}).get("held")) or {}
    nobody = "nobody's — the grinders' order" if any(s.get("team") for s in mine) else "nobody's"
    out = []
    for p in ((r.get("prs") or {}).get("open")) or []:
        if not isinstance(p, dict) or not isinstance(p.get("number"), int) or not p.get("red_since"):
            continue
        try:
            since = datetime.fromisoformat(str(p["red_since"]))
        except ValueError:
            continue
        if since.tzinfo is None:  # a stamp with no offset is UTC, as every stamp in the store is (`_instant`)
            since = since.replace(tzinfo=UTC)
        whose = ""
        if now - since >= ORPHAN_AFTER:
            held = [str(x) for x in holders.get(str(p["number"])) or []]
            whose = nobody if p["number"] in orders else f"held by {', '.join(held)}" if held else ""
            if not whose and p.get("fork"):
                whose = FORK_WHOSE  # a fork's PR is no order: its cure is its author's (TD-1285, TD-1292)
            elif not whose and p.get("draft") and not p.get("sync"):
                whose = DRAFT_WHOSE  # a draft is no order (TD-745); a sync draft waits as any sync PR does
        out.append(
            {
                "number": p["number"],
                "title": str(p.get("title") or ""),
                "url": str(p.get("url") or ""),
                "author": str(p.get("author") or ""),
                "word": "red" if p.get("checks") == "red" else "conflicting",
                "failing": list(p.get("failing") or []),
                "red_since": str(p["red_since"]),
                "whose": whose,
            }
        )
    out.sort(key=lambda x: x["red_since"])
    return out


def stays_with(name: str, sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What a switch leaves with a reader (design §4.9c *What a switch leaves alone*): each open PR
    `ask` at a session of the team, from the reader's `prs_waiting.asks` (§4.9b, TD-333) in the order
    they came — `{from, pr, reader, line}`, the line *grinder-ao-1's PR #1020 stays with
    techlead-ao-1*. The sender is named by its record where this home lists it, else by its address.
    A reader not running now is still the reader: a seat comes back on its next question (§4.9b)."""
    names = {str(s["id"]): str(s.get("name") or s["id"]) for s in sessions if s.get("id")}
    out: list[dict[str, Any]] = []
    for s in badged(name, sessions):
        waiting = s.get("prs_waiting")
        if s.get("superseded_by") or not isinstance(waiting, dict):
            continue
        reader = str(s.get("name") or s.get("id"))
        for a in waiting.get("asks") or []:
            sent = str(a.get("from"))
            # this host's own sender may be addressed `id@home`, which the list names by its bare id
            sender = names.get(sent) or names.get(naming.split_address(sent)[0], sent)
            line = f"{sender}'s PR #{a.get('pr')} stays with {reader}"
            out.append({"from": a.get("from"), "pr": a.get("pr"), "reader": reader, "line": line})
    return out


def relaunch_params(x: teams.Launch) -> dict[str, Any]:
    """The `relaunch` RPC's `launch`: the keys it replaces, an absent one sent as None so the home
    removes it (a switch to `build` takes `review` off) — and `profile`, always handed, "" the
    default's (TD-619), since one not handed keeps the record's."""
    return {
        "prompt": x.prompt,
        "prompt_from": x.prompt_from,
        "lane": list(x.lane),
        "review": x.review,
        "profile": x.profile or "",
    }


def apply(call: Call, org: orgmod.Org, name: str, host: str, *, caller: str | None = None) -> dict[str, Any]:
    """**Apply** and `ao team flow <team> --apply` (design §4.9c *Switching*): compile the team's
    current flow, read its records against it, and per member sit it out, start it or relaunch it —
    a person's own, since the home's `relaunch` is. A member that cannot be reached, or whose call is
    refused, is skipped and said; the others are applied. Returns `{team, flow, applied, skipped}`,
    each entry `{name, act, line}`, and `stays`, the PRs already asked of a reader, which stay its
    (`stays_with`); nothing but the definition's renames and removals applied for a stopped team, whose
    next start compiles the flow. A rename (§4.9 *A member renamed or removed in the definition*,
    TD-706) is a relaunch whose launch carries the newcomer's `name`, taken at the record's next replay;
    a removal is the sit-out form with `dropped` — on a stopped team too, since rule 8 replays its ended
    records."""
    team = teams.find(org, name)
    sessions = call("list")
    stays = stays_with(name, sessions)
    if not crew(name, sessions):  # no records: its next start compiles the flow
        return {"team": name, "flow": teams.current_flow(team), "applied": [], "skipped": [], "stays": stays}
    plan = teams.plan(org, name, host, files=files_via(call))
    diffs = differences(plan, sessions)  # a stopped team's renames and removals alone
    # a manager on call is the controller closed as live (TD-269): the members Apply starts name it
    lead = next(
        (
            s
            for s in badged(name, sessions)
            if (s["state"] not in DEAD or on_call(s)) and plan.manager_id in (s.get("name"), s.get("id"))
        ),
        None,
    )
    lead_id = str(lead["id"]) if lead else ""
    out: dict[str, Any] = {"team": name, "flow": plan.flow, "applied": [], "skipped": [], "stays": stays}
    for d in diffs:
        row = d.as_dict(plan.flow)
        rec = d.record or {}
        if d.act == "left":
            out["skipped"].append(row)
            continue
        if rec.get("state") == "unreachable":
            row["line"] = f"{d.name}: {rec.get('host') or 'its host'} is not answering — applied to the others"
            out["skipped"].append(row)
            continue
        try:
            if d.act == "sit_out":
                call("relaunch", id=rec["id"], sit_out=True)
            elif d.act == "removed":
                call("relaunch", id=rec["id"], sit_out=True, dropped=True)
            elif d.act == "rename":
                call("relaunch", id=rec["id"], launch={**relaunch_params(d.launch), "name": d.launch.name})
            elif d.act == "relaunch":
                call("relaunch", id=rec["id"], launch=relaunch_params(d.launch))
            else:
                x = d.launch
                on = {"host": x.host} if x.host else {}
                verdict = call("name_check", dir=str(x.dir), name=x.name, repo=str(x.dir), **on)
                if verdict.get("verdict") in ("live", "suspended"):
                    raise teams.TeamError(f"held by a live session ({verdict.get('id') or x.name})")
                keeps, said = keep_mail_for(call, {x.name: verdict}, caller, concluded=False)
                keep = {"keep_mail": True} if keeps else {}
                ctl = [lead_id] if lead_id and x is not plan.lead else []
                gate = on_call_gate(x) if x is plan.lead else {}
                got = call("create", **x.create_params(ctl), **keep, **gate)
                row["id"] = got.get("id")
                if gate:
                    row["line"] = f"{x.name}: {ON_CALL_LINE}"
                row["line"] += "".join(f" — {n}" for n in said)
        except (AgentError, teams.TeamError) as e:
            row["line"] = f"{d.name}: not applied — {e}"
            out["skipped"].append(row)
            continue
        out["applied"].append(row)
    return out


def _close_concluded(call: Call, org: orgmod.Org, name: str, held: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A person's Start on a **concluded** team (design §4.9a, §4.5a *team groups*, TD-099): the
    names `held` are refused as on any start unless the team is concluded and every holder is one
    of its concluded sessions. Then each of those sessions is closed — all of them, not only the
    ones holding a name — under the wrap-up's own check, so one with uncommitted or unpushed work
    refuses the whole start by name, and nothing is closed until every one has passed it. Returns
    what was closed; raises `NamesHeld` or `TeamError` before anything is closed or created."""
    team = org.teams.get(name)
    mine = crew(name, call("list"))  # a person's session beside a concluded team neither blocks nor is closed
    # a member waiting on the person's answer is not concluded, so a Start never closes it (TD-274)
    done = concluded(mine, seat_names(team, mine), waiting_of_home(call, strict=True)) if team is not None else None
    up = {str(s["id"]): s for s in live(mine)} if done else {}
    still = [v for v in held if v.get("verdict") != "live" or str(v.get("holder")) not in up]
    if still:
        raise NamesHeld(name, still)
    unsafe = [f"{s.get('name') or i} has {why}" for i, s in up.items() if (why := _unsafe_to_close(s))]
    if unsafe:
        raise teams.TeamError(
            f"team {name} was not started — it is concluded, but a session it would close first is not "
            f"clean and pushed: {'; '.join(unsafe)}"
        )
    out = []
    for i, s in up.items():
        call("close", id=i)
        out.append({**_entry(s, "concluded"), "action": "closed", "state": "closed"})
    return out


# ── stop ──────────────────────────────────────────────────────────────────────────────────────


def stop_members(call: Call, org: orgmod.Org, name: str, *, now: bool = False, caller: str | None = None) -> Stopping:
    """The first half of `ao team stop` (design §4.9): the wrap-up prompt — the one the card's
    **Wrap up** sends — to every member, or a kill with `--now`. The lead is stopped by `stop_lead`
    once the members have settled, which is what makes the order the design's one.

    Split in two so a caller that must not block (the Sessions page) can send this half and let the rest
    run behind it, while `ao team` runs both in a row.

    `caller` is the session running the command, if one is (`SHIFTLEAD_SESSION`). When it is the
    team's own lead this is the wind-down (design §4.9a): the same sequence under a different
    trigger, except that the lead is never typed at or killed by its own command."""
    up = live(badged(name, call("list")))
    # A person's session in the team is left alone and named (design §4.9 *A person in the team*):
    # §9 invariant 5 would refuse it anyway, and a stop must not end on that refusal.
    people = [s for s in up if persons(s)]
    up = [s for s in up if not persons(s)]
    if not up and people:
        stays = "; ".join(stays_line(s) for s in people)
        raise teams.TeamError(f"no live unattended session carries the team {name} badge — nothing to stop ({stays})")
    if not up:
        raise teams.TeamError(f"no live session carries the team {name} badge — nothing to stop")
    lead, members = split(name, up, org)
    st = Stopping(team=name, now=now, lead=lead, lead_is_caller=bool(caller and lead and lead["id"] == caller))
    for s in people:
        st.acted.append({**_entry(s, "person"), "action": stays_line(s), "state": s["state"]})
    for s in members:
        if not now and s.get("out_of_work") and s["state"] in SETTLED:
            # Finished (§4.9a): it declared, and it is not mid-turn. There is nothing to wrap up, and
            # a prompt would only start a turn that `--close` could then land in the middle of. Unread
            # mail says it is not finished for these words: the doorbell rings it (§4.9, TD-1051)
            n = int(s.get("unread") or 0)
            action = (
                f"out of work, {n} unread — left idle for the doorbell" if n else "finished (out of work), nothing sent"
            )
            st.acted.append({**_entry(s, "member"), "action": action, "state": s["state"], "unread": n})
            continue
        st.acted.append(_stop_one(call, s, "member", now=now))
    if now and lead is not None:  # a kill has nothing to wait for: the lead goes with them
        st.acted.append(_own_end(lead) if st.lead_is_caller else _stop_one(call, lead, "manager", now=True))
        st.lead = None
    return st


def stop_lead(call: Call, st: Stopping, *, timeout: float = STOP_TIMEOUT, close: bool = False) -> Stopping:
    """The second half: wait for each member to go idle, exited or closed — or for the wrap-up
    window to pass — and then stop the lead. A no-op when `--now` already killed everything.

    `close` also closes each member that settled with nothing to lose (design §4.9a, 2026-09-17: a
    wrapped-up Claude Code session sits `idle` rather than leaving, and `ao team start` refuses
    while it does). A member still working, or holding uncommitted or unpushed work, is left open
    and named: a stop never strands work to look finished."""
    if st.now and st.lead is None:
        return st
    states = wait_settled(call, st.member_ids, timeout)
    for entry in st.acted:
        entry["state"] = states.get(entry["id"], entry.get("state") or "?")
    if close and not st.now:
        records = {s["id"]: s for s in call("list")}
        for entry in st.acted:
            if entry["role"] == "member":
                _close_settled(call, entry, records.get(entry["id"]))
    if st.lead is not None:
        st.acted.append(_own_end(st.lead) if st.lead_is_caller else _stop_one(call, st.lead, "manager", now=st.now))
        st.lead = None
    return st


def _close_settled(call: Call, entry: dict[str, Any], record: dict[str, Any] | None) -> None:
    if record is None or record["state"] == "closed":
        return
    if record["state"] not in SETTLED:
        entry["left_open"] = f"still {record['state']}"
        return
    unsafe = _unsafe_to_close(record)
    if unsafe:
        entry["left_open"] = unsafe
        return
    call("close", id=entry["id"])
    n = int(record.get("unread") or 0)
    if entry.get("unread") and n:  # an out-of-work member's mail waits for the name's next start (§4.9, TD-1051)
        entry["action"] = f"closed with {n} unread, kept for the name's next start"
    elif entry.get("unread"):  # read while the stop waited: finished after all
        entry["action"] = "finished (out of work), nothing sent, closed"
    else:
        entry["action"] += ", closed"
    entry["state"] = "closed"


def _unsafe_to_close(record: dict[str, Any]) -> str | None:
    """Why this member's checkout is not *clean and pushed*, or None when it is. Unknown is unsafe:
    a record with no `git` yet is left open, as Ready to close leaves it unchecked.

    **One measure** (design §4.2, 2026-09-20, TD-080): `git.unpushed` is computed once by the host
    agent — against the branch's own `origin/<branch>` where it has one, the upstream where it does
    not, and the remote-tracking branches where there is neither — and read here, by the card's
    flag and by Ready to close alike. This function used to run a third test of its own
    (`git branch -r --contains HEAD` for a branch with no upstream), which is now rule 3 of the
    measure and needs no subprocess here."""
    return work_left(record.get("git"))


def _own_end(lead: dict[str, Any]) -> dict[str, Any]:
    """The lead's entry when the lead is the one running the stop: nothing is sent to it."""
    return {
        **_entry(lead, "manager"),
        "action": f"is you — finish your last acts, then `ao close {lead['id']}`",
        "state": lead.get("state") or "?",
    }


def _stop_one(call: Call, s: dict[str, Any], role: str, *, now: bool) -> dict[str, Any]:
    """One member's or the lead's stop. A refusal — its host unreachable (§4.4a), a pending prompt
    — is this entry's outcome, not the stop's: the rest of the team is still wrapped up, and the
    refused one is named with the reason (TD-057 step 4a, the 3b leftover)."""
    try:
        if now or s.get("agent") is False:  # a record with no agent is killed at once, typed nothing (§4.3)
            call("kill", id=s["id"])
        else:
            call("send", id=s["id"], text=teams.WRAPUP_PROMPT, wrapup=True)
    except Exception as e:  # noqa: BLE001 — the transport's error is the reason, whichever it is
        return {**_entry(s, role), "action": f"refused: {e}", "state": s.get("state") or "?", "refused": True}
    killed = now or s.get("agent") is False
    return {**_entry(s, role), "action": "killed" if killed else "wrap-up sent", "state": "killed" if killed else "?"}


def stays_line(s: dict[str, Any]) -> str:
    """The words Wind down's and Stop now's confirm and `ao team stop` use for a person's session in
    the team (design §4.9 *A person in the team*)."""
    return f"your session {s.get('name') or s['id']} stays: a team act never stops an interactive session"


def _entry(s: dict[str, Any], role: str) -> dict[str, Any]:
    return {"id": s["id"], "name": s.get("name") or s["id"], "role": role}


def wait_settled(call: Call, ids: list[str], timeout: float) -> dict[str, str]:
    """Read the records until every id is idle, exited or closed, or the window passes (design §4.9:
    *waits for each to go idle or the wrap-up window to pass*). Returns each id's last state."""
    if not ids:
        return {}
    end = time.monotonic() + max(timeout, 0.0)
    while True:
        states = {s["id"]: s["state"] for s in call("list") if s["id"] in ids}
        if all(st in SETTLED for st in states.values()) or time.monotonic() >= end:
            return states
        time.sleep(min(WRAPUP_POLL, max(end - time.monotonic(), 0.0)) or WRAPUP_POLL)


# ── Members… (design §4.9 *Add or remove a member from the team card*, TD-163, built by TD-172) ──


def members_view(
    org: orgmod.Org, name: str, sessions: list[dict[str, Any]], roles: list[str] | None = None
) -> dict[str, Any]:
    """The Members dialog's listing: the manager, the techlead seat, and each member entry as the
    definition writes it — role · name · lane · count — with the sessions holding it and their
    states. `editable` is whether the page may edit it: a team `org.yml` defines, never one a
    repo's `.shiftlead.yml` does (*edit it in the repo; this card only reads it*). `next` is Add
    member's default name for each of `roles` (and the members' own), `twice` the names the
    definition holds more than once, each entry holding one marked `twice` (TD-268). Each entry carries
    its `size` — the sessions the line runs — with `count` its file's, `words` as the row reads it (*2
    (file says 1)*), `down` the session its **−** winds down on a live team, and `next_start` on a team
    with nothing live whose size is above its count (*· from the next Start*, §4.9 *A team's size*,
    TD-1165): **− / +** are live on every team, a repo's included."""
    team = teams.find(org, name)
    twice = team.twice_named()
    mine = crew(name, sessions)
    by_name = {str(s.get("name") or ""): s for s in mine}
    up = bool(live(mine))

    def kept(n: str) -> bool:  # what −'s step down winds down: never a run-only member (`resize`)
        s = _current(n, mine)
        return s is not None and not s.get("run_only") and not s.get("sit_out") and not sat_out(s)

    def held(n: str) -> dict[str, Any]:
        s = by_name.get(n)
        return {"name": n, "id": s["id"] if s else "", "state": s.get("state") if s else "not live"}

    editable = bool(team.source and org.path and Path(team.source) == Path(org.path))
    repo = Path(team.source).parent.name if team.source else "the repo"
    entries = []
    for i, m in enumerate(team.members):
        names = m.names()
        size = len(names)
        entries.append(
            {
                "index": i,
                "role": m.role,
                "name": m.name,
                "lane": list(m.lane),
                "count": m.count,
                "size": size,
                "words": str(size) + (f" (file says {m.count})" if size != m.count else ""),
                "down": names[-1] if up and names and kept(names[-1]) else "",
                "next_start": not up and size > m.count,
                "sessions": [held(n) for n in names],
                # a name another entry also holds: Remove leaves that session to it, and − / + are off,
                # since the line's name cannot tell the two apart (TD-268, TD-1165); a line sized 0 names none
                "twice": any(n in twice for n in names),
                "shared": [n for n in names if n in twice],
            }
        )
    out: dict[str, Any] = {
        "team": team.name,
        "source": str(team.source) if team.source else None,
        "editable": editable,
        # the reason the card's disabled Members… gives (§4.5a *Members… on a repo-defined team*, TD-229)
        "note": "" if editable else f"defined in {repo}'s .shiftlead.yml — changed by PR",
        "live": up,
        "manager": held(team.manager.name) if team.manager.role != orgmod.PERSON else None,
        "techlead": held(team.techlead.name) if team.techlead else None,
        "members": entries,
        "twice": twice,
        "next": {r: team.next_name(r) for r in [*(roles or []), *(m.role for m in team.members)]},
    }
    return out


def _names(org: orgmod.Org, name: str) -> list[str]:
    team = teams.find(org, name)
    return [n for m in team.members for n in m.names()]


def _commit(call: Call, message: str) -> None:
    """The home commits the org file with the act's words (design §4.9 *What is left at the home has
    a history*): the edit is written already, so a refusal or an older agent costs only the entry."""
    with contextlib.suppress(Exception):
        call("commit_defs", message=message)


def add_member(
    call: Call,
    path: Path,
    name: str,
    host: str,
    *,
    role: str,
    member: str = "",
    lane: list[str] | None = None,
    caller: str | None = None,
) -> dict[str, Any]:
    """**Add member** (design §4.9): the definition edited as text (`orgmod.edit_members`); on a
    live team, the one new member created under the manager as `ao team start` creates one — the
    plan's own launch, the name check first — so its card appears without a restart. On a stopped
    team, the definition only: the next Start brings the new shape."""
    before = _names(orgmod.with_home_settings(orgmod.load(path)), name)  # sized as `new` is (TD-1164)
    did = orgmod.edit_members(path, name, add={"role": role, "name": member, "lane": lane or []})
    _commit(call, f"org: {name} {did}")
    org = orgmod.with_home_settings(orgmod.load(path))  # under the picked flow (§4.9c)
    new = [n for n in _names(org, name) if n not in before]
    up = live(crew(name, call("list")))
    out: dict[str, Any] = {"team": name, "did": did, "created": [], "text": f"org.yml: {did}"}
    if not up or not new:
        out["text"] += " — the team is stopped: its next Start brings the member" if not up else ""
        return out
    plan = teams.plan(org, name, host, files=files_via(call))
    sits = [n for n in new if n in plan.sit_out]
    if sits:
        # §4.9c *Members the flow does not use sit out*: written, not started under the current flow
        out["text"] += f" — {', '.join(sits)} sits out under {plan.flow}: not started"
        new = [n for n in new if n not in sits]
        if not new:
            return out
    lead_id = _lead_id(plan, up)
    for x in [m for m in plan.members if m.name in new]:
        rec, said = _create_member(call, x, lead_id, caller)
        if rec is None:
            raise teams.TeamError(
                f"org.yml: {did}, but {x.name} is held by a live session, so nothing was created — "
                "the definition names it for the next Start"
            )
        out["created"].append(rec)
        out["text"] += "".join(f" — {n}" for n in said)
    out["text"] += (
        f" — started {', '.join(str(r.get('name') or r.get('id')) for r in out['created'])} under {lead_id or 'you'}"
    )
    return out


def _lead_id(plan: teams.Plan, up: list[dict[str, Any]]) -> str:
    """The id of the team's live manager, the one controller a member created into a live team gets."""
    lead = next((s for s in up if s.get("name") == plan.manager_id or s.get("id") == plan.manager_id), None)
    return str(lead["id"]) if lead else ""


def _create_member(
    call: Call, x: teams.Launch, lead_id: str, caller: str | None, run_only: bool = False
) -> tuple[dict[str, Any] | None, list[str]]:
    """One member created into a live team as `ao team start` creates one, the name check first: the
    record and what keeping its mail said, or `(None, [])` where a live session holds the name."""
    verdict = call("name_check", dir=str(x.dir), name=x.name, repo=str(x.dir))
    if verdict.get("verdict") in ("live", "suspended"):
        return None, []
    keeps, said = keep_mail_for(call, {x.name: verdict}, caller, concluded=False)
    keep = {"keep_mail": True} if keeps else {}
    extra = {**keep, **({"run_only": True} if run_only else {})}
    return call("create", **x.create_params([lead_id] if lead_id else []), **extra), said


def _next_size(team: orgmod.TeamDef, line: str, mine: list[dict[str, Any]]) -> tuple[str, int]:
    """A member line's next free name (`TeamDef.next_free`) and the size that names it."""
    m = team.line(line)
    want = team.next_free(line, mine)
    i = len(m.names())
    while m.names(i + 1)[i] != want:
        i += 1
    return want, i + 1


def next_members(
    org: orgmod.Org, name: str, host: str, sessions: list[dict[str, Any]], files: teams.Files | None = None
) -> dict[str, teams.Launch | str]:
    """Each member line's next member as `start_member` would create it, nothing created (§4.9 *A member
    started from the form*, TD-1167): by line, its `Launch` — the next free name, the line's profile, lane
    and brief over the role's, under a flow the current flow's — or why the form cannot start one (the
    line sits out under the current flow). One plan for the team, every line one past its size."""
    team = teams.find(org, name)
    mine = crew(name, sessions)
    wants, size = {}, dict(team.size)
    for m in team.members:
        wants[m.name], size[m.name] = _next_size(team, m.name, mine)
    plan = teams.plan(orgmod.with_settings(org, {name: {"size": size}}), name, host, files=files)
    by_name = {x.name: x for x in plan.members}
    return {
        line: f"{line} sits out under {plan.flow}" if want in plan.sit_out or want not in by_name else by_name[want]
        for line, want in wants.items()
    }


def start_member(
    call: Call,
    org: orgmod.Org,
    name: str,
    line: str,
    host: str,
    *,
    run_only: bool = False,
    caller: str | None = None,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A member line's next member created (§4.9 *One road for every caller*, TD-1164): the line's next free
    name past its size (`TeamDef.next_free`), created as `ao team start` creates a member — under the live
    manager, the current flow's lane, reader and stage brief, the name check first — and, with `run_only`,
    `run_only` on the create's record and its launch record. The dialog's **Add member**, which edits
    `org.yml`, is `add_member`. Refused for a line the definition does not name, one the current flow
    does not use, and a name a live session holds; a team that is not running is its caller's to refuse
    (`ao team add`, TD-1166) — with no live manager, the member is created under no one. `fields` is what
    the New session form's person typed over the line's (TD-1167: `name`, `prompt`, `lane`, `profile`,
    `adapter`), the record's for its run."""
    team = teams.find(org, name)
    mine = crew(name, call("list"))
    try:
        want, n = _next_size(team, line, mine)
    except ValueError as e:
        raise teams.TeamError(str(e)) from None
    sized = orgmod.with_settings(org, {name: {"size": {**team.size, line: n}}})  # the plan names it
    plan = teams.plan(sized, name, host, files=files_via(call))
    if want in plan.sit_out:
        raise teams.TeamError(f"{line} sits out under {plan.flow}: nothing started")
    x = next(x for x in plan.members if x.name == want)
    if fields:
        x = replace(x, **fields)
        want = x.name
    rec, said = _create_member(call, x, _lead_id(plan, live(mine)), caller, run_only=run_only)
    if rec is None:
        raise teams.TeamError(f"{want} is held by a live session, so nothing was created")
    text = "".join(f" — {w}" for w in said)
    return {"team": name, "line": line, "created": rec, "text": f"started {want}" + text}


def not_running(team: orgmod.TeamDef, sessions: list[dict[str, Any]]) -> str:
    """Why a member start on `team` is refused (§4.9 *A member started from the form*, TD-1166), or "": a team
    with nothing live, or whose defined manager is neither live nor a seat on call, is not running — a team a
    person leads (`manager: person`) is running when any of its crew records is live — so a member started
    there would have no manager and no run to end it."""
    mine = crew(team.name, sessions)
    if live(mine):
        if team.manager.role == orgmod.PERSON:
            return ""
        lead = _current(team.manager.name, mine)
        if lead is not None and (lead["state"] not in DEAD or on_call(lead)):
            return ""
    return f"{team.name} is not running: start it first"


def add(
    call: Call,
    org: orgmod.Org,
    name: str,
    line: str,
    host: str,
    *,
    keep: bool = False,
    caller: str | None = None,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`ao team add <team> <line> [--keep]` (§4.7, §4.9 *A member started from the form*, TD-1166): the line's
    next member started for this run alone (`start_member(run_only=True)`), or with `keep` the line's size one
    higher (`resize`), its refusals included — each refused on a team that is not running (`not_running`).
    `fields` is `start_member`'s, for a run-only start alone: a kept member is the line's."""
    team = teams.find(org, name)
    if why := not_running(team, call("list")):
        raise teams.TeamError(why)
    if not keep:
        return start_member(call, org, name, line, host, run_only=True, caller=caller, fields=fields)
    try:
        n = len(team.line(line).names()) + 1
    except ValueError as e:
        raise teams.TeamError(str(e)) from None
    return resize(call, org, name, line, n, host, caller=caller)


def _sit_out_member(call: Call, s: dict[str, Any]) -> str:
    """A member the definition no longer holds, in the sit-out form a removal takes (`relaunch {sit_out,
    dropped}`, §4.9 *A member renamed or removed*): a live one wound down by the home, never killed, an
    ended one marked as it stands. Its words, or an AgentError the caller says."""
    call("relaunch", id=s["id"], sit_out=True, dropped=True)
    if s.get("state") in DEAD:
        return f"{s.get('name')} is marked sat out, so a start by the tick never brings it back"
    return f"{s.get('name')} is wound down by the home (the wrap-up, never a kill); its card stays until Forget"


def resize(
    call: Call, org: orgmod.Org, name: str, line: str, n: int, host: str, caller: str | None = None
) -> dict[str, Any]:
    """A member line's size set to `n` (§4.9 *A team's size*, TD-1164) — `ao team size`, and the Members
    dialog's **− / +**: refused for a line the definition does not name, below 0, below what a listed
    flow's stages need, and where a step up's next name is another line's, nothing written; then
    `teams.<team>.size` written through `set_settings` (a person's own, refused to a session), and on
    a live team the line's sessions created or wound down one at a time to match, walking its sized
    names — a step up creates the first sized name no current record holds (a line the current flow does
    not use is counted, not started), or adopts a live run-only member that holds it through the `keep`
    act, creating nothing; a step down winds the highest-numbered kept member down by the
    sit-out form. A step that fails stops the walk and says what was done; the setting stays written."""
    team = teams.find(org, name)
    try:
        m = team.line(line)
    except ValueError as e:
        raise teams.TeamError(str(e)) from None
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise teams.TeamError(f"{line}: a size is a whole number of sessions, 0 or more, not {n!r}")
    old = len(m.names())
    if m.role and team.flows and n == 0:
        rest = sum(len(x.names()) for x in team.members if x.role == m.role and x is not m)
        here = hosts.local_host().name
        need = teams.flow_needs(org, team, m.role, team.host or host or here, here, files_via(call)) if not rest else ""
        if need:
            raise teams.TeamError(f"{need} needs a {m.role}: drop {need} from flows: first")
    others = {nm for x in team.members if x is not m for nm in x.names()}
    if taken := [nm for nm in m.names(n)[old:] if nm in others]:
        raise teams.TeamError(f"{taken[0]} is another line's: rename one of them in the definition")
    got = call("set_settings", teams={name: {"size": {**team.size, line: n}}})
    org = orgmod.with_settings(org, got.get("teams"))
    team = teams.find(org, name)
    said = f"{line}: {n}" + (f" (file says {m.count})" if n != m.count else "")
    out: dict[str, Any] = {
        "team": name, "line": line, "size": n, "count": m.count, "created": [], "adopted": [], "wound_down": [],
    }  # fmt: skip
    mine = crew(name, call("list"))
    up = live(mine)
    if not up:
        out["text"] = said + (" · from the next Start" if n > old else "")
        return out
    if n < old:  # the highest-numbered kept member first, never a run-only one (§4.9 *A team's size*)
        for gone in reversed(m.names(old)[n:]):
            s = _current(gone, mine)
            if s is None or s.get("run_only") or s.get("sit_out") or sat_out(s):
                continue
            try:
                words = _sit_out_member(call, s)
            except AgentError as e:
                out["text"] = said + f" — stopped at {gone}: {e}" + "".join(f" — {w}" for w in out["wound_down"])
                return out
            out["wound_down"].append(words)
        out["text"] = said + "".join(f" — {w}" for w in out["wound_down"])
        return out
    plan = teams.plan(org, name, host, files=files_via(call))
    lead_id, said_too = _lead_id(plan, up), []
    for want in team.line(line).names()[old:]:
        if want in plan.sit_out:
            out["text"] = said + f" — {line} sits out under {plan.flow}: counted, not started"
            return out
        held = _current(want, mine)
        if held is not None and held.get("run_only") and held.get("state") not in DEAD:
            try:  # adopted, not created: kept from here, on the record and in its launch record
                out["adopted"].append(call("keep", id=held["id"]))
            except AgentError as e:
                made = ", ".join(str(r.get("name")) for r in out["created"] + out["adopted"]) or "nothing"
                out["text"] = said + f" — stopped at {want}: {e}; started or kept {made}"
                return out
            said_too.append(f"{want} is kept, no longer for this run alone")
            continue
        free = team.next_free(line, mine, from_=team.line(line).names().index(want))
        if free != want:
            continue  # a current record holds it already
        x = next((x for x in plan.members if x.name == want), None)
        rec, notes = _create_member(call, x, lead_id, caller) if x is not None else (None, [])
        if rec is None:
            made = ", ".join(str(r.get("name")) for r in out["created"]) or "nothing"
            out["text"] = said + f" — stopped at {want}: a live session holds the name; started {made}"
            return out
        out["created"].append(rec)
        mine.append(rec)
        said_too += notes
    made = ", ".join(str(r.get("name") or r.get("id")) for r in out["created"])
    out["text"] = said + "".join(f" — {w}" for w in said_too)
    out["text"] += f" — started {made} under {lead_id or 'you'}" if made else ""
    return out


def remove_member(call: Call, path: Path, name: str, *, index: int, role: str, host: str = "") -> dict[str, Any]:
    """**Remove** (design §4.9): the entry's whole line deleted, whatever its count or size (*Add member and
    Remove keep the definition's share*, TD-1165), and each session it held takes the sit-out form a removal
    from the definition takes (`relaunch {sit_out, dropped}`, §4.9 *A member renamed or removed in the
    definition*, TD-706): a live one wound down by the home — the wrap-up, never a kill — and an ended one
    marked as it stands, so rule 8 never replays it; its record stays a card until Forget. A name another
    entry still holds runs on (TD-268), and a run-only member ends with its run. Under a team that lists
    flows, the last members of a role a listed flow's stage needs are refused, naming the flow (§4.9c), the
    file untouched; `host` is where the team's checkout is read."""
    org = orgmod.with_home_settings(orgmod.load(path))  # under the picked flow (§4.9c)
    team = teams.find(org, name)
    if not 0 <= index < len(team.members):
        raise teams.TeamError(f"team {name} has no member entry {index + 1} — reload and try again")
    m = team.members[index]
    if m.role and team.flows:
        left = sum(len(x.names()) for x in team.members if x.role == m.role) - len(m.names())
        here = hosts.local_host().name
        need = teams.flow_needs(org, team, m.role, team.host or host or here, here, files_via(call)) if left < 1 else ""
        if need:
            raise teams.TeamError(f"{need} needs a {m.role}: drop {need} from flows: first")
    gone = m.names()  # a line sized 0 holds no session (TD-1164)
    did = orgmod.edit_members(path, name, remove=index, role=role)
    _commit(call, f"org: {name} {did}")
    out: dict[str, Any] = {"team": name, "did": did, "wound_down": [], "text": f"org.yml: {did}"}
    still = set(teams.find(orgmod.with_home_settings(orgmod.load(path)), name).session_names())
    mine = crew(name, call("list")) if gone else []
    for n in gone:
        if n in still:  # a name the definition held twice: another entry still names it (TD-268)
            out["text"] += f" — another entry still names {n}, so it runs on"
            continue
        s = _current(n, mine)
        if s is None or s.get("run_only") or s.get("sit_out") or sat_out(s):
            continue
        ended = s.get("state") in DEAD
        try:
            words = _sit_out_member(call, s)
        except AgentError as e:  # the file is edited either way: what the record could not take is said
            out["wound_down"].append({**_entry(s, "member"), "action": f"refused: {e}", "state": s.get("state") or "?"})
            out["text"] += f" — {n} could not be marked sat out ({e})"
            continue
        out["wound_down"].append({**_entry(s, "member"), "action": "marked" if ended else "wrap-up sent", "state": "?"})
        out["text"] += f" — {words}"
    return out
