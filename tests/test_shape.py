"""TD-834, design §4.4 *Team shape*: the home samples each running team once a minute — each member's
class and each stage's queue — keeps the minutes per day in `shape.json`, and the `shape` RPC reads
them with the rules that suggest a change of members."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from conftest import park_ticks

from sessionorc import identity, modes, paths
from sessionorc import shape as shape_mod
from sessionorc.client import LocalClient
from sessionorc.models import MailEntry, ProgressEntry, Session

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)  # a Wednesday: a week window holds Monday on


def _rec(name, role="grinder", **kw) -> Session:
    s = Session(id=f"ao-x-{name}", name=name, kind="interactive", adapter="claude-code", dir=f"/w/{name}")
    s.team, s.role, s.unattended, s.state = "grind", role, True, "idle"
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _cls(r, *, seat=False, in_review=False, waiting_person=False, lane_count=0, prs_waiting=False):
    return shape_mod.classify(
        r, seat=seat, in_review=in_review, waiting_person=waiting_person, lane_count=lane_count, prs_waiting=prs_waiting
    )


# -- the classes ------------------------------------------------------------------------------------


def test_each_class_is_read_in_its_order():
    claim = [ProgressEntry(ref="TD-1")]
    assert _cls(_rec("a", state="limited", gated={"x": 1})) == "limited"
    assert _cls(_rec("a", state="working", gated={"x": 1})) == "paused"
    assert _cls(_rec("a", state="working"), in_review=True) == "working"
    assert _cls(_rec("a", state="stalled?")) == "working"
    # a held PR's ask that is also about a reference reads review, whatever `waiting_of` says
    assert _cls(_rec("a"), in_review=True, waiting_person=True) == "waiting:review"
    assert _cls(_rec("a", state="needs-you")) == "waiting:person"
    assert _cls(_rec("a"), waiting_person=True, lane_count=3) == "waiting:person"
    assert _cls(_rec("a", progress=claim), lane_count=0) == "on_claim"
    assert _cls(_rec("a"), lane_count=2) == "idle_with_work"
    assert _cls(_rec("a"), lane_count=0) == "starved"
    assert _cls(_rec("a", out_of_work={"at": "x", "why": "y"}), lane_count=0) == "starved"
    # a seat: free with nothing waiting, idle with work when PRs wait
    seat = _rec("t", role="techlead", seat={})
    assert _cls(seat, seat=True) == "free"
    assert _cls(seat, seat=True, prs_waiting=True) == "idle_with_work"
    assert _cls(_rec("t", role="techlead", seat={}, state="working"), seat=True) == "working"


# -- who is sampled ---------------------------------------------------------------------------------


def test_stages_come_from_lanes_and_review_links_and_skip_the_manager_and_a_shell():
    designer = _rec("d1", role="designer", lane=["design-first", "owner:designer"])
    grinder = _rec("g1", lane=["free-pick", "owner:grinder"], review={"reader": "techlead-1", "held": ["**"]})
    seat = _rec("techlead-1", role="techlead", seat={})
    manager = _rec("m1", role="manager", seat={}, lane=["free-pick"])
    shell = _rec("g1-shell", role="", adapter="shell", lane=["free-pick"])
    hunter = _rec("h1", role="hunter", lane=["area:ui"])
    auditor = _rec("a1", role="auditor", seat={})
    got = shape_mod.stages([designer, grinder, seat, manager, shell, hunter, auditor], manager)
    assert [(s["name"], s["role"], s["kind"]) for s in got] == [
        ("design", "designer", "lane"),
        ("build", "grinder", "lane"),
        ("review", "techlead", "review"),
    ]
    assert shape_mod.stage_of(seat, got)["name"] == "review"
    assert shape_mod.stage_of(grinder, got)["name"] == "build"
    for r in (shell, hunter, auditor):
        assert shape_mod.stage_of(r, got) is None


def test_a_chain_gives_one_review_stage_per_link_in_order():
    g = _rec(
        "g1",
        lane=["free-pick"],
        review={"chain": [{"stage": "security", "reader": "sec-1"}, {"stage": "review", "reader": "tl-1"}]},
    )
    got = shape_mod.stages([g, _rec("tl-1", role="techlead", seat={}), _rec("sec-1", role="auditor", seat={})])
    want = [("build", "grinder"), ("security", "auditor"), ("review", "techlead")]
    assert [(s["name"], s["role"]) for s in got] == want


# -- the queues -------------------------------------------------------------------------------------


def _member(name, stage, cls, role="grinder"):
    return {"id": f"ao-x-{name}", "name": name, "role": role, "stage": stage, "class": cls}


def _q(name, kind="lane", role="grinder", order=1, **kw):
    return {"name": name, "role": role, "kind": kind, "order": order, **kw}


BOUND = timedelta(hours=2)


def test_backed_up_unstaffed_and_past_bound_and_first_seen():
    doc = shape_mod.blank()
    members = [_member("g1", "build", "working"), _member("g2", "build", "on_claim")]
    queues = [_q("build", ids=["r:TD-1", "r:TD-2"]), _q("review", kind="review", role="techlead", order=2, n=1)]
    queues[1]["oldest"] = (NOW - timedelta(hours=3)).isoformat()
    shape_mod.take(doc, "grind", NOW, members, queues, BOUND)
    later = NOW + timedelta(minutes=1)
    shape_mod.take(doc, "grind", later, members, [_q("build", ids=["r:TD-2", "r:TD-3"]), queues[1]], BOUND)
    day = doc["days"][NOW.astimezone().date().isoformat()]["grind"]
    b, r = day["queues"]["build"], day["queues"]["review"]
    assert day["minutes"] == 2 and b["minutes"] == 2 and b["depth_sum"] == 4 and b["depth_max"] == 2
    assert b["backed_up"] == 2 and b["unstaffed"] == 0  # every builder busy
    assert b["oldest_max"] == 60  # TD-2 kept its first sight across the minute
    seen = doc["first_seen"]["grind"]["build"]
    assert set(seen) == {"r:TD-2", "r:TD-3"} and seen["r:TD-2"] == NOW.isoformat()  # TD-1 left: dropped
    # no techlead was sampled: unstaffed, never backed up; past its two-hour bound both minutes
    assert r["unstaffed"] == 2 and r["backed_up"] == 0 and r["past_bound"] == 2
    assert day["records"]["ao-x-g1"]["minutes"] == {"working": 2}


def test_an_idle_member_with_work_keeps_a_queue_from_backing_up_and_an_empty_one_counts_nothing():
    doc = shape_mod.blank()
    members = [_member("g1", "build", "working"), _member("g2", "build", "idle_with_work")]
    shape_mod.take(doc, "grind", NOW, members, [_q("build", ids=["r:TD-1"])], BOUND)
    shape_mod.take(doc, "grind", NOW, [_member("g1", "build", "starved")], [_q("build", ids=[])], BOUND)
    b = doc["days"][NOW.astimezone().date().isoformat()]["grind"]["queues"]["build"]
    assert b["backed_up"] == 0 and b["nonempty"] == 1 and b["unstaffed"] == 0


def test_limited_minutes_are_the_teams_and_old_days_are_pruned():
    doc = shape_mod.blank()
    shape_mod.take(doc, "grind", NOW, [_member("g1", "build", "paused"), _member("g2", "build", "working")], [], BOUND)
    assert doc["days"][NOW.astimezone().date().isoformat()]["grind"]["limited"] == 1
    old = NOW - shape_mod.spend_mod.KEEP - timedelta(days=1)
    shape_mod.take(doc, "grind", old, [_member("g1", "build", "working")], [], BOUND)
    shape_mod.prune(doc, NOW.astimezone().date())
    assert list(doc["days"]) == [NOW.astimezone().date().isoformat()]


# -- the reading and its rules ----------------------------------------------------------------------


def _day(doc, team="grind", minutes=600, limited=0, records=None, queues=None, at=NOW):
    doc["days"][at.astimezone().date().isoformat()] = {
        team: {"minutes": minutes, "limited": limited, "records": records or {}, "queues": queues or {}}
    }
    return doc


def _row(name, role, stage, **minutes):
    return {name: {"name": name, "role": role, "stage": stage, "minutes": dict(minutes)}}


def _queue(role, kind, order, minutes=600, backed_up=0, unstaffed=0, past_bound=0, oldest_h=0, nonempty=None):
    return {
        "role": role,
        "kind": kind,
        "order": order,
        "minutes": minutes,
        "depth_sum": minutes,
        "depth_max": 3,
        "oldest_max": oldest_h * 3600,
        "nonempty": minutes if nonempty is None else nonempty,
        "backed_up": backed_up,
        "unstaffed": unstaffed,
        "past_bound": past_bound,
    }


def _rules(doc, window="day"):
    got = shape_mod.reading(doc, "grind", window, NOW)
    return got, [(s["rule"], s["text"]) for s in got["suggestions"]]


def test_too_little_to_read_suggests_nothing():
    doc = _day(shape_mod.blank(), records=_row("g1", "grinder", "build", starved=400))
    got, rules = _rules(doc)
    assert got["too_little"] is True and rules == [] and got["live_hours"] == 6.7


def test_starved_reads_one_fewer_and_not_below_its_threshold():
    recs = _row("g1", "grinder", "build", starved=240, working=360)  # 40%
    got, rules = _rules(_day(shape_mod.blank(), records=recs, queues={"build": _queue("grinder", "lane", 1)}))
    assert rules == [("starved", "grinders starved 40%: one grinder fewer")]
    assert got["roles"][0]["shares"] == {"working": 0.6, "starved": 0.4} and got["roles"][0]["live_hours"] == 10.0
    recs = _row("g1", "grinder", "build", starved=230, working=370)
    assert _rules(_day(shape_mod.blank(), records=recs))[1] == []


def test_starved_names_the_upstream_role_when_the_stage_before_was_backed_up():
    recs = {
        **_row("g1", "grinder", "build", starved=300, working=300),
        **_row("d1", "designer", "design", working=600),
    }
    queues = {"design": _queue("designer", "lane", 0, backed_up=246), "build": _queue("grinder", "lane", 1)}
    _, rules = _rules(_day(shape_mod.blank(), records=recs, queues=queues))
    assert rules == [("starved", "grinders starved 50% while design was backed up 41%: one more designer")]


def test_backed_up_needs_its_share_and_its_oldest():
    recs = _row("g1", "grinder", "build", working=600)
    q = {"build": _queue("grinder", "lane", 1, backed_up=228, oldest_h=9)}
    _, rules = _rules(_day(shape_mod.blank(), records=recs, queues=q))
    assert rules == [("backed_up", "builds backed up 38%, oldest 9h: one more grinder")]
    q = {"build": _queue("grinder", "lane", 1, backed_up=228, oldest_h=5)}
    assert _rules(_day(shape_mod.blank(), records=recs, queues=q))[1] == []
    q = {"build": _queue("grinder", "lane", 1, backed_up=170, oldest_h=9)}
    assert _rules(_day(shape_mod.blank(), records=recs, queues=q))[1] == []


def test_a_seat_gets_no_fewer_or_more_line():
    recs = _row("tl", "techlead", "review", free=600)
    q = {"review": _queue("techlead", "review", 2, backed_up=400, oldest_h=9)}
    got, rules = _rules(_day(shape_mod.blank(), records=recs, queues=q))
    assert got["roles"][0]["kind"] == "seat" and rules == []


def test_starved_and_backed_up_for_one_role_are_one_bursts_line_in_either_wording():
    recs = {
        **_row("g1", "grinder", "build", starved=300, working=300),
        **_row("d1", "designer", "design", working=600),
    }
    queues = {
        "design": _queue("designer", "lane", 0, backed_up=246),
        "build": _queue("grinder", "lane", 1, backed_up=200, oldest_h=7),
    }
    _, rules = _rules(_day(shape_mod.blank(), records=recs, queues=queues))
    assert rules == [
        (
            "bursts",
            "grinders starved 50% and builds backed up 33%: the work arrives in bursts — a steadier intake, "
            "not the shape",
        )
    ]


def test_two_rules_naming_the_same_change_are_one_line():
    recs = {
        **_row("g1", "grinder", "build", starved=300, working=300),
        **_row("d1", "designer", "design", working=600),
    }
    queues = {"design": _queue("designer", "lane", 0, backed_up=246, oldest_h=8), "build": _queue("grinder", "lane", 1)}
    _, rules = _rules(_day(shape_mod.blank(), records=recs, queues=queues))
    assert rules == [
        (
            "backed_up+starved",
            "design backed up 41%, oldest 8h; grinders starved 50% while design was backed up 41%: one more designer",
        )
    ]


def test_past_bound_unstaffed_idle_waiting_and_limited():
    recs = {
        **_row("g1", "grinder", "build", idle_with_work=120, working=300, **{"waiting:person": 180}),
        **_row("tl", "techlead", "review", working=600),
    }
    queues = {
        "build": _queue("grinder", "lane", 1, unstaffed=60),
        "review": _queue("techlead", "review", 2, past_bound=90),
    }
    got, rules = _rules(_day(shape_mod.blank(), records=recs, queues=queues, limited=120))
    assert rules == [
        ("unstaffed", "builds waited 1h with no grinder live: its members ended while work remained"),
        ("past_bound", "review waited 2h past its bound — the reader, not the shape"),
        ("idle_with_work", "grinder idle 20% with work in its lane — not the shape: read its picks"),
        ("waiting_person", "grinder waiting on you 30% — answers, not members"),
        ("limited", "the quota, not the shape: 2h limited or paused"),
    ]
    review = next(q for q in got["queues"] if q["stage"] == "review")
    assert review["past_bound"] == 0.15 and "past_bound" not in got["queues"][0]
    # one below each threshold: nothing
    recs = {
        **_row("g1", "grinder", "build", idle_with_work=110, working=320, **{"waiting:person": 170}),
        **_row("tl", "techlead", "review", working=600),
    }
    queues = {
        "build": _queue("grinder", "lane", 1, unstaffed=59),
        "review": _queue("techlead", "review", 2, past_bound=59),
    }
    assert _rules(_day(shape_mod.blank(), records=recs, queues=queues, limited=119))[1] == []


def test_a_role_merges_its_records_and_lists_its_seats_and_a_week_reads_back_to_monday():
    doc = shape_mod.blank()
    _day(doc, records={**_row("g1", "grinder", "build", working=60), **_row("g2", "grinder", "build", starved=60)})
    monday = NOW - timedelta(days=2)
    doc["days"][monday.astimezone().date().isoformat()] = {
        "grind": {"minutes": 60, "limited": 0, "records": _row("g1", "grinder", "build", working=60), "queues": {}}
    }
    doc["days"][(NOW - timedelta(days=3)).astimezone().date().isoformat()] = doc["days"][
        monday.astimezone().date().isoformat()
    ]  # last Sunday: outside the week
    day = shape_mod.reading(doc, "grind", "day", NOW)
    week = shape_mod.reading(doc, "grind", "week", NOW)
    assert [r["role"] for r in day["roles"]] == ["grinder"] and day["live_hours"] == 2.0
    assert [s["name"] for s in day["roles"][0]["seats"]] == ["g1", "g2"]
    assert week["live_hours"] == 3.0 and week["minutes"] == 660
    assert shape_mod.reading(doc, "other", "week", NOW)["roles"] == []


def test_a_role_reads_its_spend_per_finished_entry_when_given_the_seat_ledgers():
    doc = _day(
        shape_mod.blank(),
        records={**_row("g1", "grinder", "build", working=60), **_row("tl", "techlead", "review", free=60)},
    )
    finished = {"grinder": {"entries": 3, "sum": 6.0, "median": 1.5}}
    got = {r["role"]: r for r in shape_mod.reading(doc, "grind", "day", NOW, finished)["roles"]}
    assert got["grinder"]["finished"] == {"entries": 3, "median": 1.5}
    assert got["techlead"]["finished"] == {"entries": 0, "median": None}  # none finished is a count, not a gap
    assert all("finished" not in r for r in shape_mod.reading(doc, "grind", "day", NOW)["roles"])


# -- at the home ------------------------------------------------------------------------------------


def _entry(i, **kw):
    return {"id": i, "for_page": "pickable", "pickable": "yes", "kind": "build", "owner": "grinder", **kw}


async def test_the_home_samples_a_running_team_and_serves_its_shape(agent, tmp_path):
    await park_ticks(agent)
    root = str(tmp_path / "repo")
    agent._repos[root] = {"name": "repo", "ledger": {"entries": [_entry("TD-1"), _entry("TD-2")]}}
    mgr = _rec("mgr", role="manager", seat={}, repo=root, capabilities=["control"])
    g1 = _rec("g1", lane=["free-pick"], repo=root, controllers=[mgr.id], review={"reader": "tl", "held": ["**"]})
    g2 = _rec("g2", lane=["free-pick"], repo=root, controllers=[mgr.id], progress=[ProgressEntry(ref="TD-2")])
    g3 = _rec("g3", lane=["free-pick"], repo=root, controllers=[mgr.id], state="needs-you")
    tl = _rec("tl", role="techlead", seat={}, repo=root, controllers=[mgr.id])
    shell = _rec("g1-sh", role="", adapter="shell", lane=[], repo=root)
    person = _rec("paul", role="", unattended=False, repo=root)  # a person's session keeps nothing running
    ask = MailEntry(id="m-1", from_=g3.id, to=[tl.id], at="2026-10-14T09:00:00Z", kind="ask", text="read #9")
    ask.pr = 9
    tl.inbox.append(ask)
    for r in (mgr, g1, g2, g3, tl, shell, person):
        r.host = agent.host
        agent.sessions[r.id] = r
    assert agent._shape_pass(NOW) is True
    day = agent._shape["days"][NOW.astimezone().date().isoformat()]["grind"]
    classes = {k: next(iter(v["minutes"])) for k, v in day["records"].items()}
    assert classes == {
        g1.id: "idle_with_work",  # TD-1 is in its lane, unheld
        g2.id: "on_claim",
        g3.id: "waiting:review",  # its PR's ask waits at the seat, though it is needs-you too
        tl.id: "idle_with_work",  # a PR waits for it
    }
    assert day["queues"]["build"]["depth_sum"] == 1  # TD-2 is held
    assert day["queues"]["review"]["depth_sum"] == 1 and day["queues"]["review"]["role"] == "techlead"

    # the minute's sample is written; a minute with no running team writes nothing
    agent._shape_at = 0.0
    await agent._shape_tick(NOW)
    assert json.loads(paths.shape_file().read_text())["days"]
    for r in (mgr, g1, g2, g3, tl):
        r.state = "closed"
    assert agent._shape_pass(NOW + timedelta(minutes=1)) is False

    async with LocalClient() as person_client:
        got = await person_client.call("shape", team="grind", window="week")
    assert got["team"] == "grind" and {r["role"] for r in got["roles"]} == {"grinder", "techlead"}
    assert got["too_little"] is True and got["suggestions"] == []


async def test_the_shape_rpc_reads_each_roles_spend_per_finished_entry_from_the_seat_ledger(agent):
    await park_ticks(agent)
    now = datetime.now().astimezone()
    today, at = now.date().isoformat(), now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _day(agent._shape, records=_row("ao-x-g1", "grinder", "build", working=60), at=now)

    def row(team, figure, ref):
        spent = {"figure": figure, "turns": 1}
        return {"name": "g1", "role": "grinder", "team": team, "repo": "r", "metered": False,
                "models": {"m": spent}, "refs": {ref: spent}}  # fmt: skip

    agent._seats["days"] = {today: {"ao-x-g1": row("grind", 2.0, "TD-1"), "ao-y-g1": row("other", 9.0, "TD-2")}}
    agent._seats["refs"] = {
        "r TD-1": {"first_claimed": at, "done_at": at},
        "r TD-2": {"first_claimed": at, "done_at": at},
    }
    async with LocalClient() as person_client:
        got = await person_client.call("shape", team="grind", window="day")
    assert got["roles"][0]["finished"] == {"entries": 1, "median": 2.0}  # the other team's TD-2 is not grind's
    assert got["unit"] == "≈$"


async def test_a_team_whose_ledger_cannot_be_read_is_not_sampled(agent, tmp_path):
    await park_ticks(agent)
    root = str(tmp_path / "repo")
    agent._repos[root] = {"name": "repo", "ledger": {"error": "gone"}}
    g1 = _rec("g1", lane=["free-pick"], repo=root, host=agent.host)
    agent.sessions[g1.id] = g1
    assert agent._shape_pass(NOW) is False and agent._shape["days"] == {}


def test_shape_is_a_read_open_to_a_session_and_the_homes():
    assert "shape" in identity.READS and "shape" in modes.HOME_READS


async def test_a_repo_not_read_yet_and_a_member_whose_state_says_nothing_are_not_sampled(agent, tmp_path):
    await park_ticks(agent)
    root = str(tmp_path / "repo")
    g1 = _rec("g1", lane=["free-pick"], repo=root, host=agent.host)
    g2 = _rec("g2", lane=["free-pick"], repo=root, host=agent.host, state="unreachable")
    agent.sessions[g1.id] = g1
    agent.sessions[g2.id] = g2
    assert agent._shape_pass(NOW) is False  # after a restart, before the repo's first reading: not *no work*
    agent._repos[root] = {"name": "repo", "ledger": {"entries": []}}
    gone = _rec("g0", lane=["free-pick"], repo=str(tmp_path / "scratch"), host=agent.host, state="closed")
    agent.sessions[gone.id] = gone  # an ended member in a path the registry does not list holds nothing back
    assert agent._shape_pass(NOW) is True
    day = agent._shape["days"][NOW.astimezone().date().isoformat()]["grind"]
    assert set(day["records"]) == {g1.id}  # a node down is not starved
