"""Stuck work (design §6 rule 13 *Stuck work*, TD-1470, built by TD-1496): whether open work has a live session
able to act on it, read at the home each tick.

The work is of two kinds, each with its **actors**: an open `ask` to a session (its addressees, each walked to
its newest record) and a decided board line waiting on a session (its holders, else its lanes' records). This
module holds the parts that need no host agent: which asks are open (`open_asks`), whether one actor is acting
and, where it is not, its reason and its clock (`judge`), and the work's reading from its actors (`reading`).
The tick's `_stuck_pass` gathers the inputs — the walk, `unanswered.read`'s stamp, rule 3's `unfillable` — and
keeps the result on `host.json` as `stuck`. It rings no session and presses nothing."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sessionorc import agent_common, mail, work, workorders
from sessionorc import ledger as ledger_mod
from sessionorc.models import PERSON, MailEntry, Session, normalize_ref

ENDED = ("exited", "closed")


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def iso(t: datetime) -> str:
    return t.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _latest(*values: Any) -> datetime | None:
    times = [t for v in values if (t := v if isinstance(v, datetime) else _when(v)) is not None]
    return max(times) if times else None


def persons_own(r: Session) -> bool:
    """A person's own live session (§6 rule 13 *Never stuck*): started by hand (`mail.by_person`), not unattended,
    in no team. Beside other actors it is passed over; work whose only actors are such is never stuck. A member
    the person took over is not one: it reads `taken_over`."""
    return r.state not in mail._NOT_LIVE and not r.unattended and not r.team and mail.by_person(r)


def open_asks(records: Mapping[str, Session]) -> list[MailEntry]:
    """Every open `ask` to a session (§6 rule 13 *The work it reads*), once per id, in the order the records hold
    them: an `ask` open in a session's mailbox — a handed entry among them — never one whose `to` includes the
    person, nor one a seat passed up (`passed_up`). A `steer` is never one: it lapses to its default."""
    seen: set[str] = set()
    out: list[MailEntry] = []
    for r in records.values():
        for e in r.inbox:
            if e.id in seen or e.kind != "ask" or not e.open or e.passed_up or PERSON in e.to:
                continue
            seen.add(e.id)
            out.append(e)
    return out


def fillable_seat(r: Session, unfillable: Mapping[str, str]) -> bool | str:
    """For a supervised, unattended seat whose record is not live (§6 rule 13 *Acting*, `seat_unable`'s exited or
    closed branch): True where rule 3 fills it — no `unfillable` word this tick and not held (`stop_held`) —, the
    word where `unfillable` holds one; False for any other record."""
    if not r.seat or not (r.supervised and r.unattended) or r.state not in ENDED:
        return False
    if why := unfillable.get(r.id):
        return str(why)
    return not isinstance(r.stop_held, Mapping)


@dataclass
class Actor:
    """One actor's reading: `acting`, else its `reason` and its clock `since` (floored at the work's open time).
    `own` marks a person's own session, which is passed over."""

    id: str
    host: str
    name: str
    acting: bool = False
    reason: dict[str, Any] | None = None
    since: datetime | None = None
    own: bool = False
    team: bool = False  # a team read whole (a work order's): its reason is the team's, and it names no actor
    until: datetime | None = None  # the instant its reason names its own end at (`comes_back`), where it names one


def comes_back(reason: Mapping[str, Any] | None, r: Session | None = None) -> datetime | None:
    """The instant a not-acting actor's reason names for its own end (§6 rule 13 *A reason that names its own end
    waits*), read from the actor's own reading: `scheduled`'s `start_at`, `limited`'s `limited_reset` on the record,
    `gated`'s `gate.resets`; a team's held `until` (its instant), `early` (its last start plus `WORK_EARLY`) and
    `usage` with a `resets`. None for any other reason, `usage` with no `resets` among them: that is a need."""
    reason = reason or {}
    state = reason.get("state")
    if state == "scheduled":
        return _when(reason.get("start_at"))
    if state == "limited":
        return _when(r.limited_reset) if r is not None else None
    if state == "gated":
        return _when((reason.get("gate") or {}).get("resets"))
    held = reason.get("held") if state == "team" else None
    if not isinstance(held, Mapping):
        return None
    if held.get("why") == "until":
        return _when(held.get("until"))
    if held.get("why") == "early":
        start = _when(held.get("started"))
        return start + agent_common.WORK_EARLY if start is not None else None
    if held.get("why") == "usage":
        return _when(held.get("resets"))
    return None


def judge(
    r: Session | None,
    address: str,
    stamp: Mapping[str, Any],
    *,
    unfillable: Mapping[str, str],
    open_at: datetime,
    idle_clock: datetime | None,
    now: datetime,
) -> Actor:
    """One actor read as rule 13 reads it. `stamp` is `unanswered.read`'s for `r` (the walk's last record, None:
    gone), `idle_clock` what an `idle` actor gives for this work (an ask: its copy's `read_at`; an order: its
    `stuck_open` `at`), `open_at` the work's open time, which floors every figure."""
    if r is None:
        reason = {k: v for k, v in stamp.items() if k != "at"}
        return Actor(address, "", address, reason=reason, since=open_at, until=comes_back(reason))
    a = Actor(address, r.host or "", r.name or address)
    if persons_own(r):
        a.own = True
        return a
    seat = fillable_seat(r, unfillable)
    figure: datetime | None
    if seat is True:
        a.acting = True
        return a
    if isinstance(seat, str):
        # a seat rule 3 would not fill: this rule's own reason, its word drawn as is (never through `words`)
        a.reason, figure = {"state": "unfillable", "why": seat}, agent_common.idle_from(r)
    elif r.state == "stalled?" and r.stalled_ticks >= 2:
        # the instant nothing new began: the later of its work and screen clocks (§4.2 *Liveness cross-check*)
        figure = _latest(r.work_at, r.screen_at)
        a.reason = {"state": "stalled", **({"since": iso(figure)} if figure else {})}
    elif stamp.get("state") == "working":
        a.acting = True
        return a
    elif stamp.get("state") == "idle":
        if agent_common.on_its_own(r, now):
            a.acting = True  # a live subagent or background shell is working (§4.2 *Working on its own*)
            return a
        start = agent_common.idle_from(r)
        a.reason = {"state": "idle", **({"since": iso(start)} if start else {})}
        figure = _latest(idle_clock, r.subagent_at, r.shells_at)
    else:
        # the stamp without its read instant, so a reason that stands is the same reason every tick (no rewrite)
        a.reason, figure = {k: v for k, v in stamp.items() if k != "at"}, agent_common.idle_from(r)
    a.since = max(figure, open_at) if figure is not None else open_at
    a.until = comes_back(a.reason, r)
    return a


def ask_idle_clock(r: Session | None, ask_id: str) -> datetime | None:
    """An `idle` actor's clock for a question (§6 rule 13 *The clock*): the later of its copy's `read_at` in the
    walk's last record's mailbox and that record's `created`, or, unread there, the record's `since` — a turn that
    woke for other mail and ended with it open moved nothing."""
    if r is None:
        return None
    copy = next((e for e in r.inbox if e.id == ask_id), None)
    if copy is not None and copy.read_at:
        return _latest(copy.read_at, r.created)
    return _when(r.since)


def reading(actors: Iterable[Actor], now: datetime, wait: timedelta) -> dict[str, Any] | None:
    """The work's `stuck` entry, `{since, reason, actor}`, or None while it is not stuck (§6 rule 13): an actor
    acting, `since` (the newest figure among the actors) not yet older than `wait`, or its only actors the
    person's own sessions. `reason` and `actor` are the first actor's (in the order given), `more` the rest."""
    others = [a for a in actors if not a.own]
    if not others or any(a.acting for a in others):
        return None
    since = max(a.since for a in others if a.since is not None)
    if now - since <= wait:
        return None
    first = others[0]
    got: dict[str, Any] = {"since": iso(since), "reason": dict(first.reason or {})}
    if not first.team:
        got["actor"] = {"id": first.id, "host": first.host, "name": first.name, "more": len(others) - 1}
    return got


def waiting_until(actors: Iterable[Actor], now: datetime, wait: timedelta) -> datetime | None:
    """Stuck work drawn at *waiting* (§6 rule 13 *A reason that names its own end waits*): where every actor not
    acting (a person's own session passed over) has a reason naming an instant (`Actor.until`), the earliest, while
    it is ahead of now by no more than `wait`; None where one names none, or the earliest is past or further off.
    Recomputed every tick from each actor's own reading, never from the stored `reason`, and never stored."""
    others = [a for a in actors if not a.own and not a.acting]
    if not others or any(a.until is None for a in others):
        return None
    first = min(a.until for a in others if a.until is not None)
    return first if now < first <= now + wait else None


def shape_ok(key: str, value: Any) -> bool:
    """A `stuck` entry as `HostStore.load` keeps it: a key `ask:<id>` or `board:<key>`, a `since` and a `reason`;
    a `board:` entry carries its `repo`."""
    if not isinstance(value, Mapping) or not isinstance(value.get("since"), str):
        return False
    if not isinstance(value.get("reason"), Mapping) or not isinstance(value["reason"].get("state"), str):
        return False
    if key.startswith("board:"):
        return isinstance(value.get("repo"), str) and bool(value["repo"])
    return key.startswith("ask:")


def open_shape_ok(key: str, value: Any) -> bool:
    """A `stuck_open` entry as `HostStore.load` keeps it: `board:<key>` → `{at, repo, holder?, asked?}`."""
    if not key.startswith("board:") or not isinstance(value, Mapping):
        return False
    if not isinstance(value.get("at"), str) or _when(value["at"]) is None:
        return False
    if not isinstance(value.get("repo"), str) or not value["repo"]:
        return False
    with contextlib.suppress(KeyError):
        if not isinstance(value["holder"], bool):
            return False
    with contextlib.suppress(KeyError):
        if not isinstance(value["asked"], bool):
            return False
    return True


# -- a decided board line waiting on a session (§6 rule 13 *The work it reads*, *The clock*) ---------------------


def board_read(reading: Any) -> str:
    """How a repo's board was read this tick (§6 rule 13 *The clock*): `good` — read against origin; `fallback` —
    a board read of the checkout (`fetch_case` *skipped*, or none at all: the board pass's plain read), which may
    only close a line; `unread` — no reading yet, or its board read errored, so its lines stand as stored. A repo
    with no board reads `good`: it has no line."""
    bds = reading.get("boards") if isinstance(reading, Mapping) else None
    if not isinstance(bds, Mapping) or "error" in bds or not isinstance(bds.get("boards"), list):
        return "unread"
    if any(not isinstance(b, Mapping) or b.get("fetch_case") in (None, "skipped") for b in bds["boards"]):
        return "fallback"
    return "good"


def orders(reading: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The work orders of a repo reading's boards (`workorders.orders`: every open decided line that is not
    `fyi`), each `{id, entry}` — `entry` the line as the lanes read it (`workorders.entry`)."""
    return [{"id": o["id"], "entry": workorders.entry(o)} for o in workorders.orders(reading.get("boards") or {})]


def carried(reading: Mapping[str, Any]) -> set[str]:
    """The keys of the closed decided lines a reading's boards carry (`workorders.carried`): what a fallback read
    may close."""
    out: set[str] = set()
    for b in (reading.get("boards") or {}).get("boards") or ():
        for c in (b.get("carried") or ()) if isinstance(b, Mapping) else ():
            if isinstance(c, Mapping) and c.get("key"):
                out.add(str(c["key"]))
    return out


def claim_at(r: Session, ref: str) -> datetime | None:
    """A holder's claim instant on `ref`: its latest declared `claimed` entry's `at`."""
    return _latest(
        *(p.at for p in r.progress if p.ref == ref and p.status == "claimed" and (p.source or "declared") == "declared")
    )


def holders(ref: str, records: Mapping[str, Session], now: datetime) -> list[str]:
    """The addresses of the records `mail.lease_holders` reads holding `ref` (§4.8 *A claim is a lease*), in the
    order given — a seat among them, whatever its kind."""
    rows = [
        {"id": addr, "state": r.state, "progress": [p.to_dict() for p in r.progress]} for addr, r in records.items()
    ]
    return [str(h["id"]) for h in mail.lease_holders(ref, rows, now)]


def opened(
    prev: Mapping[str, Any] | None, repo: str, held_at: datetime | None, now: datetime, asked: bool = False
) -> dict[str, Any]:
    """A line's `stuck_open` entry this tick (§6 rule 13 *The clock*): `at` the first tick it was read decided, and
    from then the latest of the stored `at` (never moving back), its holders' latest claim while one holds it
    (`held_at`; `holder` set), the release — the first tick reading no holder where `holder` was set, the tick's
    own instant, `holder` cleared then — and the answer — the first tick reading no question that counts
    (`asked` False) where `asked` was set, the tick's own instant, `asked` cleared then. A tick that is both moves
    `at` once; a line first read with a question counting is written with `asked` set and `at` that tick."""
    at = _when((prev or {}).get("at")) or now
    out: dict[str, Any] = {"repo": repo}
    if held_at is not None:
        at = max(at, held_at)
        out["holder"] = True
    elif (prev or {}).get("holder"):
        at = max(at, now)  # the release: a drop, a `done`, an exit, a restart or a lapsed lease alike
    if asked:
        out["asked"] = True
    elif (prev or {}).get("asked"):
        at = max(at, now)  # the answer: answered, lapsed, withdrawn, any other close, or snoozed
    return {"at": iso(at), **out}


# -- a line the person is asked about (§6 rule 13 *Never stuck*) -------------------------------------------------

_BARE_TD = re.compile(r"(?i)TD-\d+")


def in_snoozed_fold(e: MailEntry, now: datetime) -> bool:
    """Whether the Inbox draws an open person-inbox entry in its *Snoozed* fold (§4.10 *Snooze*, §4.5a **Send to
    reviewer**), as `shiftlead/ui/inbox.py`'s `inbox_sections` reads it (which `sessionorc` cannot import; a test
    holds the two to one answer): `snoozed_until` ahead of `now` — an unreadable one read as not snoozed — or a
    look with a reviewer (`snoozed_for` set)."""
    if e.snoozed_for:
        return True
    until = _when(e.snoozed_until)
    return until is not None and until > now


def _same_root(a: Any, b: Any) -> bool:
    return bool(a) and bool(b) and str(a).rstrip("/") == str(b).rstrip("/")


def asked_refs(person_inbox: Iterable[MailEntry], root: str, roots: Mapping[str, str], now: datetime) -> set[str]:
    """The entries of the repo at `root` the person is asked about (§6 rule 13 *Never stuck*), each by
    `normalize_ref`: `work.waiting_of` (open `ask`s and `steer`s, a paused steer among them, `about` by
    `reference_of`) over the person inbox's entries filtered first — to those whose envelope `repo` resolves by
    `roots` (`queue.repo_roots` over the tick's readings) to `root` (none, or unresolved, counts for no line),
    and leaving out any open one in the Inbox's *Snoozed* fold (`in_snoozed_fold`). The sender keys are dropped:
    no sender is matched. This filter is rule 13's own; `host.waiting` reads `waiting_of` unfiltered."""
    mine = [e for e in person_inbox if e.repo and _same_root(roots.get(e.repo), root) and not in_snoozed_fold(e, now)]
    return {normalize_ref(q["ref"]) for qs in work.waiting_of(mine).values() for q in qs}


def asked_about(order: Mapping[str, Any], asked: set[str]) -> bool:
    """Whether a work order's line is one the person is asked about: its `Context:` (its `refs`) a bare `TD-n`
    among `asked` — a PR, a repo-qualified ref, more than one ref or no `Context:` has no such question."""
    refs = [str(r) for r in (order.get("entry") or {}).get("refs") or ()]
    return len(refs) == 1 and bool(_BARE_TD.fullmatch(refs[0])) and normalize_ref(refs[0]) in asked


def _has_lane_ids(mark: Any) -> bool:
    members = mark.get("members") if isinstance(mark, Mapping) else None
    return isinstance(members, Mapping) and any(isinstance(ids, list) and ids for ids in members.values())


def team_reason(team: str, records: Iterable[Session], mark: Any, key: str) -> dict[str, Any] | None:
    """A team read whole for a work order (§6 rule 13 *The work it reads*): none of its crew live and the team
    wound down (`work.team_wound_down`) or stopped (`work.team_stopped`, by the person or its stop time) — its
    reason `{state: team, team, held}` from its `work_waiting` (rule 8): `held` as rule 8 writes it; none for a
    mark with no `held` (*waits for your Start*); `{why: wound_down}` where the team wound down with the line in
    its members' `lane_seen`; `{why: stopped}` for no mark otherwise (*is not running*). A held-only mark (no lane
    ids) reads as no mark. None for a team that is not read whole: its members are read each by its own state."""
    mine = [r for r in records if not r.superseded_by]
    if any(r.state not in work.DEAD for r in work.crew(mine)):
        return None
    wound = work.team_wound_down(mine) is not None
    # stopped by the person or its stop time; a crew that ended otherwise (`by: other` — a crash, a restart
    # ceiling) keeps each member's own state as its reason, the cure's name
    if not wound and (work.team_stopped(mine) or {}).get("by") not in ("person", "until"):
        return None
    out: dict[str, Any] = {"state": "team", "team": team}
    if _has_lane_ids(mark):
        if isinstance(mark.get("held"), Mapping):
            out["held"] = dict(mark["held"])
        return out
    seen = any(key in ((r.lane_seen or {}).get("ids") or ()) for r in mine)
    out["held"] = {"why": "wound_down" if wound and seen else "stopped"}
    return out


def lane_records(
    root: str, entry: Mapping[str, Any], records: Mapping[str, Session], teams: Iterable[str] = ()
) -> list[str]:
    """The addresses of the records whose lane takes a work order (§6 rule 13 *The work it reads*), as `ao repo`
    reads the lanes: the repo's records no newer one supersedes, with a lane `ledger.lane_matches` takes it in —
    never a seat (which has no lane) nor a member its flow sat out (`work.sat_out`) — by team in `teams` order
    (a team not in it after, by name), then id."""
    rank = {t: i for i, t in enumerate(teams)}
    out = [
        (rank.get(r.team or "", len(rank)), r.team or "", addr)
        for addr, r in records.items()
        if r.repo == root
        and r.lane
        and r.seat is None
        and not r.superseded_by
        and not work.sat_out(r)
        and ledger_mod.lane_matches(list(r.lane), dict(entry), r.team)
    ]
    return [addr for *_, addr in sorted(out)]


def no_lane(open_at: datetime, now: datetime, wait: timedelta) -> dict[str, Any] | None:
    """A line no lane takes (§6 rule 13): `{since, reason: {state: no_lane}}` once past the wait, else None."""
    return {"since": iso(open_at), "reason": {"state": "no_lane"}} if now - open_at > wait else None
