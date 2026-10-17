"""A team's shape: what each member was doing and how much work waited for each stage, sampled once a
minute at the home, kept per day, and read with the rules that suggest a change of members (design §4.4
*Team shape*, TD-819; built by TD-834).

The home reads no flow (§4.9c *What a flow compiles to*), so a team's stages are read from what its
records carry: a worker stage is a lane that takes design-first entries (`design`, the lane kind
`design`) or builds (`build`, the kind `pickable`); a review stage is a link of a member's `review` —
its chain, or the one-link form — held by the seat its `reader` names. The stages run design, build,
then the review links in the chain's order, which is every built-in flow's order. A record is sampled
when it is the team's crew (unattended), live, not a shell, not its manager, and a member of one of
those stages: a hunter's area lane, an auditor seat no link names, and the manager are not.

`shape.json`, beside `seat_spend.json`: `{days: {YYYY-MM-DD: {team: {minutes, limited, records: {id:
{name, role, stage, minutes: {class: n}}}, queues: {stage: {role, kind, order, minutes, depth_sum,
depth_max, oldest_max, nonempty, backed_up, unstaffed, past_bound}}}}}, first_seen: {team: {stage:
{key: at}}}}` — `minutes` the team's sampled minutes, `limited` the minutes a sampled member was limited
or paused, `oldest_max` in seconds. Kept for `spend.KEEP`; written only on a minute that sampled a team.
Pure: the home's mixin (`agent_shape`) gathers and saves."""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc import paths
from sessionorc import spend as spend_mod
from sessionorc.store import _atomic_write

# the classes, in the order they are taken (§4.4 *The member's class*): the first that holds
CLASSES = (
    "limited",
    "paused",
    "working",
    "waiting:review",
    "waiting:person",
    "on_claim",
    "idle_with_work",
    "starved",
    "free",
)
WORKING_STATES = ("working", "stalled?")  # *working on its own* is a working record's (§4.2)
# the states a sample reads; `unreachable` (a node down) and `scheduled` (not started) say nothing of the work
SAMPLED_STATES = ("working", "stalled?", "idle", "needs-you", "limited")
DESIGN, BUILD = "design", "build"  # the worker stages' words, and the lane kinds they read
LANE_KIND = {DESIGN: "design", BUILD: "pickable"}

# The rules (§4.4 *What it suggests*): fixed in the code, never settings, so two readings of one week agree
SHAPE_EVERY = 60.0  # seconds between samples
SHAPE_MIN_HOURS = 8.0  # under this many live hours on the team: too little to read
SHAPE_STARVED = 0.40  # a worker role starved this share of its live hours
SHAPE_UPSTREAM = 0.30  # … while the stage before it was backed up this share of the window
SHAPE_BACKED = 0.30  # a worker stage backed up this share of the window
SHAPE_BACKED_OLDEST = timedelta(hours=6)  # … with its oldest at least this old
SHAPE_PAST_BOUND = 0.10  # a review stage's oldest past its bound this share of the window
SHAPE_UNSTAFFED = 0.10  # a queue with work and nobody of its stage live this share of the window
SHAPE_IDLE_WITH_WORK = 0.20  # a worker role idle with work in its lane this share of its live hours
SHAPE_WAITING_PERSON = 0.30  # a role waiting on the person this share of its live hours
SHAPE_LIMITED = 0.20  # the team limited or paused this share of its sampled minutes


def shape_file() -> Path:
    return paths.shape_file()


class ShapeStore:
    """`shape.json`. A missing or unreadable file is an empty record, never a crash."""

    def __init__(self, path: Path | None = None):
        self.path = path or shape_file()

    def load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return blank()
        if not isinstance(raw, dict):
            return blank()
        return {"days": dict(raw.get("days") or {}), "first_seen": dict(raw.get("first_seen") or {})}

    def save(self, doc: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.path, json.dumps(doc, indent=1, sort_keys=True))


def blank() -> dict[str, Any]:
    return {"days": {}, "first_seen": {}}


def _f(r: Any, key: str) -> Any:
    return r.get(key) if isinstance(r, Mapping) else getattr(r, key, None)


def lane_stage(lane: Iterable[str]) -> str | None:
    """The worker stage a lane gives: `design` for design-first entries, `build` for builds, None for an
    area lane (a hunter's), which no flow stage gives."""
    words = list(lane or ())
    if "design-first" in words:
        return DESIGN
    if "free-pick" in words:
        return BUILD
    return None


def review_links(review: Any) -> list[dict[str, str]]:
    """A record's review stages, `[{stage, reader}]` in the chain's order: its `chain`, or the one-link
    form `{reader}` as a stage called `review` (§4.9c *The record carries the chain*)."""
    if not isinstance(review, Mapping):
        return []
    chain = review.get("chain")
    if isinstance(chain, list):
        return [
            {"stage": str(x.get("stage") or "review"), "reader": str(x["reader"])}
            for x in chain
            if isinstance(x, Mapping) and x.get("reader")
        ]
    return [{"stage": "review", "reader": str(review["reader"])}] if review.get("reader") else []


def stages(records: Collection[Any], manager: Any = None) -> list[dict[str, Any]]:
    """A team's stages read from its records (live or ended): `[{name, role, kind: lane|review, lane?,
    reader?}]`, design, build, then the review links in their order. `records` are the team's crew,
    no successor-replaced record nor one its flow sat out; `manager` is never a stage's member."""
    lane: dict[str, str] = {}
    review: list[dict[str, str]] = []
    for r in sorted(records, key=lambda r: (str(_f(r, "name")), str(_f(r, "id")))):
        if r is manager or _f(r, "adapter") == "shell":
            continue
        if _f(r, "seat") is None and (st := lane_stage(_f(r, "lane") or ())) is not None:
            lane.setdefault(st, str(_f(r, "role") or _f(r, "name")))
        for link in review_links(_f(r, "review")):
            if all(x["stage"] != link["stage"] for x in review):
                review.append(link)
    seats = {str(_f(r, "name")): r for r in records if _f(r, "seat") is not None and r is not manager}
    out = [{"name": s, "role": lane[s], "kind": "lane", "lane": LANE_KIND[s]} for s in (DESIGN, BUILD) if s in lane]
    for link in review:
        seat = seats.get(link["reader"])
        role = str(_f(seat, "role") or link["reader"]) if seat is not None else link["reader"]
        out.append({"name": link["stage"], "role": role, "kind": "review", "reader": link["reader"]})
    return out


def stage_of(record: Any, team_stages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The stage a record is a member of: a worker by its lane, a seat by the reader name a link gives."""
    if _f(record, "adapter") == "shell":
        return None
    if _f(record, "seat") is not None:
        return next((s for s in team_stages if s["kind"] == "review" and s["reader"] == _f(record, "name")), None)
    st = lane_stage(_f(record, "lane") or ())
    return next((s for s in team_stages if s["kind"] == "lane" and s["name"] == st), None)


def classify(
    record: Any, *, seat: bool, in_review: bool, waiting_person: bool, lane_count: int, prs_waiting: bool
) -> str:
    """One sample's class (§4.4 *The member's class*), the first that holds: limited, paused, working,
    waiting on a reader (whatever `waiting_of` says too), waiting on the person, on its claim; then a
    seat is free or idle with work by its `prs_waiting`, and a worker idle with work or starved by its
    own lane count."""
    state = _f(record, "state")
    if state == "limited":
        return "limited"
    if _f(record, "gated"):
        return "paused"
    if state in WORKING_STATES:
        return "working"
    if in_review:
        return "waiting:review"
    if state == "needs-you" or waiting_person:
        return "waiting:person"
    if any(_f(p, "status") == "claimed" for p in _f(record, "progress") or ()):
        return "on_claim"
    if seat:
        return "idle_with_work" if prs_waiting else "free"
    return "idle_with_work" if lane_count > 0 else "starved"


QUEUE_COUNTS = ("minutes", "depth_sum", "depth_max", "oldest_max", "nonempty", "backed_up", "unstaffed", "past_bound")
BUSY = ("working", "waiting:review", "waiting:person", "on_claim")  # what keeps a member from a backed-up queue


def take(
    doc: dict[str, Any],
    team: str,
    now: datetime,
    members: list[dict[str, Any]],
    queues: list[dict[str, Any]],
    bound: timedelta,
) -> None:
    """Add one minute of a running team to `doc`. `members` are `{id, name, role, stage, class}`, one
    per sampled record; `queues` one per stage, `{name, role, kind, order, ids?: [key], n?, oldest?}` —
    a lane stage's unheld ids, a review stage's `prs_waiting` depth and oldest instant. A lane stage's
    oldest age is read from `first_seen`, kept per id while it stays."""
    since = {}  # a review queue's oldest, parsed before the minute is added, so a bad one adds nothing
    for q in queues:
        if q["kind"] == "review" and q.get("oldest"):
            since[q["name"]] = datetime.fromisoformat(str(q["oldest"]).replace("Z", "+00:00"))
    day = now.astimezone().date().isoformat()
    t = doc["days"].setdefault(day, {}).setdefault(team, {"minutes": 0, "limited": 0, "records": {}, "queues": {}})
    t["minutes"] += 1
    if any(m["class"] in ("limited", "paused") for m in members):
        t["limited"] += 1
    for m in members:
        row = t["records"].setdefault(m["id"], {"name": m["name"], "role": m["role"], "stage": m["stage"]})
        row.setdefault("minutes", {})
        row["minutes"][m["class"]] = row["minutes"].get(m["class"], 0) + 1
    seen = doc["first_seen"].setdefault(team, {})
    for q in queues:
        staff = [m for m in members if m["stage"] == q["name"]]
        if q["kind"] == "lane":
            mine = seen.get(q["name"]) or {}
            stamp = now.isoformat()
            mine = {k: mine.get(k, stamp) for k in q.get("ids") or ()}  # an id that left is dropped
            seen[q["name"]] = mine
            depth = len(mine)
            oldest = max((now - datetime.fromisoformat(v)).total_seconds() for v in mine.values()) if mine else 0.0
        else:
            depth = int(q.get("n") or 0)
            oldest = max(0.0, (now - since.get(q["name"], now)).total_seconds())
        row = t["queues"].setdefault(q["name"], {})
        row.update({"role": q["role"], "kind": q["kind"], "order": q["order"]})
        for k in QUEUE_COUNTS:
            row.setdefault(k, 0)
        row["minutes"] += 1
        row["depth_sum"] += depth
        row["depth_max"] = max(row["depth_max"], depth)
        row["oldest_max"] = max(row["oldest_max"], round(oldest))
        if depth:
            row["nonempty"] += 1
            if staff and all(m["class"] in BUSY for m in staff):
                row["backed_up"] += 1
            if not staff:
                row["unstaffed"] += 1
            if q["kind"] == "review" and oldest > bound.total_seconds():
                row["past_bound"] += 1
    for name in [n for n in seen if all(q["name"] != n for q in queues)]:
        del seen[name]  # a stage the team no longer has keeps no clock


def prune(doc: dict[str, Any], today: date) -> None:
    oldest = (today - spend_mod.KEEP).isoformat()
    for d in [d for d in doc["days"] if d < oldest]:
        del doc["days"][d]


def _share(part: float, whole: float) -> float:
    return round(part / whole, 3) if whole else 0.0


def _pct(x: float) -> int:
    return round(x * 100)


def _hours(minutes: float) -> float:
    return round(minutes / 60, 1)


def reading(doc: dict[str, Any], team: str, window: str, now: datetime) -> dict[str, Any]:
    """The `shape` reading of one team over `day` or `week` (the home's clock): per role its live hours
    and the share of them in each class, its seats under it; per queue its mean and largest depth, its
    oldest age, and the shares of the team's sampled minutes it was non-empty, backed up, unstaffed and
    — a review stage — past its bound; the suggestions, none under `SHAPE_MIN_HOURS` live hours."""
    if window not in ("day", "week"):
        raise ValueError(f"a shape window is day or week, not {window!r}")
    local = now.astimezone()
    start, _ = spend_mod.bounds(local)[window]
    days = sorted(d for d in doc.get("days") or {} if start.isoformat() <= d <= local.date().isoformat())
    minutes = limited = 0
    recs: dict[str, dict[str, Any]] = {}
    queues: dict[str, dict[str, Any]] = {}
    for d in days:
        t = (doc["days"][d] or {}).get(team)
        if not t:
            continue
        minutes += t.get("minutes", 0)
        limited += t.get("limited", 0)
        for rid, row in (t.get("records") or {}).items():
            acc = recs.setdefault(rid, {"minutes": {}})
            acc.update({k: row.get(k) for k in ("name", "role", "stage")})  # the newest day's names stand
            for c, n in (row.get("minutes") or {}).items():
                acc["minutes"][c] = acc["minutes"].get(c, 0) + n
        for name, row in (t.get("queues") or {}).items():
            acc = queues.setdefault(name, {"stage": name})
            acc.update({k: row.get(k) for k in ("role", "kind", "order")})
            for k in ("minutes", "depth_sum", "nonempty", "backed_up", "unstaffed", "past_bound"):
                acc[k] = acc.get(k, 0) + row.get(k, 0)
            for k in ("depth_max", "oldest_max"):
                acc[k] = max(acc.get(k, 0), row.get(k, 0))
    roles: dict[str, dict[str, Any]] = {}
    for rid, acc in sorted(recs.items(), key=lambda kv: (str(kv[1].get("name")), kv[0])):
        role = roles.setdefault(
            str(acc.get("role")), {"role": acc.get("role"), "stage": acc.get("stage"), "minutes": {}, "seats": {}}
        )
        seat = role["seats"].setdefault(str(acc.get("name")), {"name": acc.get("name"), "ids": [], "minutes": {}})
        seat["ids"].append(rid)
        for c, n in acc["minutes"].items():
            role["minutes"][c] = role["minutes"].get(c, 0) + n
            seat["minutes"][c] = seat["minutes"].get(c, 0) + n
    kinds = {q["stage"]: q.get("kind") for q in queues.values()}
    out_roles = []
    for r in roles.values():
        total = sum(r["minutes"].values())
        out_roles.append(
            {
                "role": r["role"],
                "stage": r["stage"],
                "kind": "seat" if kinds.get(r["stage"]) == "review" else "worker",
                "live_hours": _hours(total),
                "shares": {c: _share(r["minutes"].get(c, 0), total) for c in CLASSES if r["minutes"].get(c)},
                "seats": [
                    {"name": s["name"], "ids": s["ids"], "hours": {c: _hours(n) for c, n in s["minutes"].items()}}
                    for s in r["seats"].values()
                ],
            }
        )
    out_queues = []
    for q in sorted(queues.values(), key=lambda q: (q.get("order") or 0, q["stage"])):
        row = {
            "stage": q["stage"],
            "role": q.get("role"),
            "kind": q.get("kind"),
            "mean_depth": round(q["depth_sum"] / q["minutes"], 2) if q.get("minutes") else 0.0,
            "max_depth": q.get("depth_max", 0),
            "oldest_hours": _hours(q.get("oldest_max", 0) / 60),
            "nonempty": _share(q["nonempty"], minutes),
            "backed_up": _share(q["backed_up"], minutes),
            "unstaffed": _share(q["unstaffed"], minutes),
            "unstaffed_hours": _hours(q["unstaffed"]),
        }
        if q.get("kind") == "review":
            row["past_bound"] = _share(q["past_bound"], minutes)
            row["past_bound_hours"] = _hours(q["past_bound"])
        out_queues.append(row)
    live = round(sum(r["live_hours"] for r in out_roles), 1)
    too_little = live < SHAPE_MIN_HOURS
    got = {
        "team": team,
        "window": window,
        "from": start.isoformat(),
        "minutes": minutes,
        "live_hours": live,
        "limited_hours": _hours(limited),
        "limited": _share(limited, minutes),
        "roles": out_roles,
        "queues": out_queues,
        "too_little": too_little,
    }
    got["suggestions"] = [] if too_little else suggestions(got)
    return got


def _label(stage: str) -> str:
    return "builds" if stage == BUILD else stage


def suggestions(got: dict[str, Any]) -> list[dict[str, Any]]:
    """§4.4 *What it suggests*: each rule that holds over the window is one line with its numbers in it;
    starved and backed up for one role are one *bursts* line in place of both; two lines that name the
    same change of members are one. Starved and backed up read worker roles only."""
    queues = [q for q in got["queues"]]
    by_stage = {q["stage"]: q for q in queues}
    lines: list[dict[str, Any]] = []
    changes: dict[tuple[str, str], dict[str, Any]] = {}

    def change(key: tuple[str, str], rule: str, reason: str, numbers: dict[str, Any], role: str) -> None:
        if key in changes:
            line = changes[key]
            line["rule"] = f"{line['rule']}+{rule}"
            line["reasons"].append(reason)
            line["numbers"].update(numbers)
            return
        line = {"rule": rule, "role": role, "reasons": [reason], "numbers": dict(numbers), "change": key}
        changes[key] = line
        lines.append(line)

    for r in got["roles"]:
        if r["kind"] != "worker":
            continue
        role, stage = str(r["role"]), str(r["stage"])
        starved = r["shares"].get("starved", 0.0)
        own = by_stage.get(stage)
        backed = bool(
            own
            and own["backed_up"] >= SHAPE_BACKED
            and own["oldest_hours"] >= SHAPE_BACKED_OLDEST.total_seconds() / 3600
        )
        if starved >= SHAPE_STARVED and backed:
            lines.append(
                {
                    "rule": "bursts",
                    "role": role,
                    "text": f"{role}s starved {_pct(starved)}% and {_label(stage)} backed up "
                    f"{_pct(own['backed_up'])}%: the work arrives in bursts — a steadier intake, not the shape",
                    "numbers": {"starved": starved, "backed_up": own["backed_up"]},
                }
            )
            continue
        if starved >= SHAPE_STARVED:
            lane = [q for q in queues if q["kind"] == "lane"]
            i = next((n for n, q in enumerate(lane) if q["stage"] == stage), 0)
            up = lane[i - 1] if i > 0 else None
            if up is not None and up["backed_up"] >= SHAPE_UPSTREAM:
                change(
                    ("more", str(up["role"])),
                    "starved",
                    f"{role}s starved {_pct(starved)}% while {_label(up['stage'])} was backed up "
                    f"{_pct(up['backed_up'])}%",
                    {"starved": starved, "upstream_backed_up": up["backed_up"]},
                    str(up["role"]),
                )
            else:
                change(("fewer", role), "starved", f"{role}s starved {_pct(starved)}%", {"starved": starved}, role)
        if backed:
            change(
                ("more", role),
                "backed_up",
                f"{_label(stage)} backed up {_pct(own['backed_up'])}%, oldest {round(own['oldest_hours'])}h",
                {"backed_up": own["backed_up"], "oldest_hours": own["oldest_hours"]},
                role,
            )
    for q in queues:
        if q["kind"] == "review" and q.get("past_bound", 0) >= SHAPE_PAST_BOUND:
            h = round(q["past_bound_hours"])
            lines.append(
                {
                    "rule": "past_bound",
                    "queue": q["stage"],
                    "text": f"{q['stage']} waited {h}h past its bound — the reader, not the shape",
                    "numbers": {"past_bound": q["past_bound"], "hours": q["past_bound_hours"]},
                }
            )
        if q["unstaffed"] >= SHAPE_UNSTAFFED:
            lines.append(
                {
                    "rule": "unstaffed",
                    "queue": q["stage"],
                    "text": f"{_label(q['stage'])} waited {round(q['unstaffed_hours'])}h with no {q['role']} live: "
                    "its members ended while work remained",
                    "numbers": {"unstaffed": q["unstaffed"], "hours": q["unstaffed_hours"]},
                }
            )
    for r in got["roles"]:
        idle = r["shares"].get("idle_with_work", 0.0)
        if r["kind"] == "worker" and idle >= SHAPE_IDLE_WITH_WORK:
            lines.append(
                {
                    "rule": "idle_with_work",
                    "role": r["role"],
                    "text": f"{r['role']} idle {_pct(idle)}% with work in its lane — not the shape: read its picks",
                    "numbers": {"idle_with_work": idle},
                }
            )
        waiting = r["shares"].get("waiting:person", 0.0)
        if waiting >= SHAPE_WAITING_PERSON:
            lines.append(
                {
                    "rule": "waiting_person",
                    "role": r["role"],
                    "text": f"{r['role']} waiting on you {_pct(waiting)}% — answers, not members",
                    "numbers": {"waiting_person": waiting},
                }
            )
    if got["limited"] >= SHAPE_LIMITED:
        lines.append(
            {
                "rule": "limited",
                "text": f"the quota, not the shape: {round(got['limited_hours'])}h limited or paused",
                "numbers": {"limited": got["limited"], "hours": got["limited_hours"]},
            }
        )
    out = []
    for line in lines:
        if "change" in line:
            how, who = line.pop("change")
            reasons = line.pop("reasons")
            line["text"] = "; ".join(reasons) + (f": one more {who}" if how == "more" else f": one {who} fewer")
        out.append(line)
    return out
