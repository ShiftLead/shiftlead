"""TD-133 slice 1, design §6 *Schedule*: a team start at a window's reset. The person's standing press
is `teams.<team>.schedule: {start: reset, profile, window}`; at the window's `resets` in the profile's
reading the home replays the team as rule 8's start does, `why: schedule`, once per reset."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import paths
from sessionorc import settings as settings_mod
from sessionorc.agent_common import SCHEDULE_LATE
from sessionorc.agent_tick import NOT_RESTARTS
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import Session

DECLARED = {"at": "2026-09-28T06:56:00Z", "why": "nothing pickable"}
RULE = {"start": "reset", "profile": "grind", "window": "week"}


def _iso(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rec(name: str, **kw) -> Session:
    base = dict(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="agentshell", dir="/tmp/x", state="closed",
        team="g", unattended=True, supervised=True, out_of_work=DECLARED, lane=["free-pick"], profile="grind",
    )  # fmt: skip
    return Session(**{**base, **kw})


class _Replays:
    """`_replay` stood in for: what the pass would start, in order, with its arguments."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict]] = []

    async def __call__(self, s, why, *, mark=None, **extra):
        self.calls.append((s.name, why, mark or {}, extra))


def _team(agent, *recs: Session) -> None:
    for r in recs:
        r.host = agent.host
        agent.sessions[r.id] = r
        paths.launch_dir().mkdir(parents=True, exist_ok=True)
        (paths.launch_dir() / f"{r.id}.json").write_text(json.dumps({"name": r.id}), encoding="utf-8")


def _reading(agent, resets: datetime | None) -> None:
    w = {"label": "week", "pct": 12}
    if resets is not None:
        w["resets"] = _iso(resets)
    agent._usage["grind"] = {"windows": [w]}


def _rec_of(agent) -> dict:
    return (agent._host_rec.get("teams") or {}).get("g") or {}


async def _setup(agent, monkeypatch, *recs: Session) -> _Replays:
    await park_ticks(agent)
    settings_mod.save({"teams": {"g": {"schedule": RULE, "on_work": "off"}}})
    replays = _Replays()
    monkeypatch.setattr(agent, "_replay", replays)
    _team(agent, *recs)
    return replays


async def test_the_reset_replays_a_wound_down_team_once(agent, monkeypatch):
    replays = await _setup(
        agent, monkeypatch,
        _rec("grinder-ao-1", controllers=["ao-t-manager-ao"]),
        _rec("manager-ao", lane=["TD-900"]),
        _rec("techlead-ao", seat={"trigger": "asks"}, out_of_work=None, controllers=["ao-t-manager-ao"]),
    )  # fmt: skip
    now = datetime.now(UTC)
    reset = now + timedelta(hours=1)
    _reading(agent, reset)
    await agent._schedules(now)
    assert replays.calls == [], "not before the reset"
    assert _rec_of(agent)["schedule_next"] == {**{k: RULE[k] for k in ("profile", "window")}, "at": _iso(reset)}

    # past the reset the reading has already rolled to next week: the remembered instant still fires
    _reading(agent, reset + timedelta(days=7))
    agent._host_rec["teams"]["g"]["work_waiting"] = {"at": "x", "members": {}}
    later = reset + timedelta(minutes=1)
    await agent._schedules(later)
    names = [c[0] for c in replays.calls]
    assert names[0] == "manager-ao" and sorted(names[1:]) == ["grinder-ao-1", "techlead-ao"], "the lead first"
    assert {c[1] for c in replays.calls} == {"schedule"}
    about = replays.calls[0][2]
    assert set(about) == {"start", "of"} and about["of"] == 3 and all(c[2] == about for c in replays.calls)
    assert all(c[3]["keep_mail"] is True for c in replays.calls)
    assert {c[0]: c[3]["held"] for c in replays.calls} == {
        "manager-ao": False,
        "grinder-ao-1": False,
        "techlead-ao": True,
    }
    rec = _rec_of(agent)
    assert rec["schedule_fired"] == _iso(reset) and "work_waiting" not in rec, "a schedule's start clears rule 8's mark"
    assert rec["schedule_next"]["at"] == _iso(reset + timedelta(days=7))
    assert agent.host_store.load()["teams"]["g"]["schedule_fired"] == _iso(reset), "saved, so a restart fires no twice"

    replays.calls.clear()
    await agent._schedules(later + timedelta(minutes=1))
    assert replays.calls == [], "once per reset"


async def test_a_reading_not_rolled_past_its_reset_fires_it(agent, monkeypatch):
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    now = datetime.now(UTC)
    _reading(agent, now - timedelta(minutes=5))
    await agent._schedules(now)
    assert [c[0] for c in replays.calls] == ["grinder-ao-1"]
    assert _rec_of(agent)["schedule_fired"] == _iso(now - timedelta(minutes=5))


async def test_no_reading_no_fire(agent, monkeypatch):
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    now = datetime.now(UTC)
    _reading(agent, None)
    await agent._schedules(now)
    agent._usage.pop("grind")
    await agent._schedules(now)
    assert replays.calls == [] and "schedule_fired" not in _rec_of(agent)


async def test_a_live_or_stopped_team_is_left_alone_and_the_reset_counted(agent, monkeypatch):
    now = datetime.now(UTC)
    past = now - timedelta(minutes=1)
    # anything live at the reset: left alone
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"), _rec("grinder-ao-2", state="working"))
    _reading(agent, past)
    await agent._schedules(now)
    assert replays.calls == [] and _rec_of(agent)["schedule_fired"] == _iso(past)


async def test_a_team_a_person_stopped_is_never_started_by_its_schedule(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1", out_of_work=None))  # closed with nothing declared
    _reading(agent, now - timedelta(minutes=1))
    agent._host_rec.setdefault("teams", {})["g"] = {"work_waiting": {"at": "x", "members": {}, "stopped": True}}
    await agent._schedules(now)
    assert replays.calls == [] and "schedule_fired" in _rec_of(agent), "the reset counts as fired"
    assert "work_waiting" in _rec_of(agent), "nothing started: rule 8's mark (the card's Start row) stands"


async def test_no_launch_record_starts_nothing(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    (paths.launch_dir() / "ao-t-grinder-ao-1.json").unlink()
    _reading(agent, now - timedelta(minutes=1))
    await agent._schedules(now)
    assert replays.calls == [] and "schedule_fired" in _rec_of(agent), "a schedule never invents a team"


async def test_a_cleared_schedule_forgets_its_upcoming_reset(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    _reading(agent, now + timedelta(hours=1))
    await agent._schedules(now)
    assert "schedule_next" in _rec_of(agent)
    settings_mod.save({"teams": {"g": {"on_work": "off"}}})
    await agent._schedules(now + timedelta(hours=2))
    assert replays.calls == [] and "schedule_next" not in _rec_of(agent)


def test_a_schedules_start_is_no_restart_of_rule_9():
    assert "schedule" in NOT_RESTARTS


async def test_a_reset_found_late_is_counted_and_starts_nothing(agent, monkeypatch):
    # a stale reading when the schedule is set, or an agent down across the reset: never an arbitrary hour
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    old = now - SCHEDULE_LATE - timedelta(minutes=5)
    _reading(agent, old)
    await agent._schedules(now)
    assert replays.calls == [] and _rec_of(agent)["schedule_fired"] == _iso(old)


async def test_a_stored_reset_fires_with_the_reading_gone_and_after_a_reload(agent, monkeypatch):
    # the profile's reading is dropped once no session runs under it: the reset read while it ran still fires,
    # from the host record as saved (an agent restart between the read and the reset)
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    reset = now + timedelta(minutes=30)
    _reading(agent, reset)
    await agent._schedules(now)
    agent._usage.pop("grind")
    agent._host_rec = agent.host_store.load()
    await agent._schedules(reset + timedelta(minutes=2))
    assert [c[0] for c in replays.calls] == ["grinder-ao-1"]


async def test_one_reset_spelled_two_ways_fires_once(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    past = (now - timedelta(minutes=3)).replace(microsecond=0)
    agent._usage["grind"] = {"windows": [{"label": "week", "pct": 1, "resets": _iso(past)}]}
    await agent._schedules(now)
    agent._usage["grind"] = {"windows": [{"label": "week", "pct": 1, "resets": past.isoformat()[:19] + ".400+00:00"}]}
    await agent._schedules(now + timedelta(minutes=1))
    assert len(replays.calls) == 1


async def test_a_changed_window_forgets_the_old_ones_reset(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    _reading(agent, now + timedelta(minutes=10))
    await agent._schedules(now)
    settings_mod.save({"teams": {"g": {"schedule": {**RULE, "window": "5h"}, "on_work": "off"}}})
    agent._usage.pop("grind")
    await agent._schedules(now + timedelta(minutes=20))
    assert replays.calls == [], "the stored reset was read for the week, not for 5h"


async def test_a_member_behind_a_down_link_holds_the_reset_to_the_next_tick(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    far = agent.sessions["ao-t-grinder-ao-1"]
    far.host = "far"
    (paths.launch_dir() / f"{agent._address(far)}.json").write_text(json.dumps({"name": far.id}), encoding="utf-8")
    past = now - timedelta(minutes=2)
    _reading(agent, past + timedelta(days=7))  # the reading already rolled
    agent._host_rec.setdefault("teams", {})["g"] = {
        "schedule_next": {"profile": "grind", "window": "week", "at": _iso(past)}
    }
    await agent._schedules(now)
    assert replays.calls == [] and "schedule_fired" not in _rec_of(agent)
    assert _rec_of(agent)["schedule_next"]["at"] == _iso(past), "the same reset, tried again"
    await agent._schedules(now + SCHEDULE_LATE + timedelta(minutes=5))
    assert replays.calls == [] and "schedule_fired" not in _rec_of(agent), "a held reset is never counted late"
    agent._link_muxes["far"] = object()
    await agent._schedules(now + SCHEDULE_LATE + timedelta(minutes=6))
    assert [c[0] for c in replays.calls] == ["grinder-ao-1"] and _rec_of(agent)["schedule_fired"] == _iso(past)


async def test_a_surprise_mid_pass_loses_no_reset(agent, monkeypatch):
    now = datetime.now(UTC)
    replays = await _setup(agent, monkeypatch, _rec("grinder-ao-1"))
    past = now - timedelta(minutes=2)
    _reading(agent, past + timedelta(days=7))
    agent._host_rec.setdefault("teams", {})["g"] = {
        "schedule_next": {"profile": "grind", "window": "week", "at": _iso(past)}
    }

    def boom(*a, **k):
        raise RuntimeError("surprise")

    real = agent._work_replays
    monkeypatch.setattr(agent, "_work_replays", boom)
    await agent._schedules(now)
    assert _rec_of(agent)["schedule_next"]["at"] == _iso(past) and "schedule_fired" not in _rec_of(agent)
    monkeypatch.setattr(agent, "_work_replays", real)
    await agent._schedules(now + timedelta(minutes=1))
    assert [c[0] for c in replays.calls] == ["grinder-ao-1"]


async def test_set_settings_checks_a_schedules_window_and_the_read_says_when_it_starts(agent):
    """TD-133 slice 2 (§4.7 `ao schedule`): the window is checked against the profile's reading as
    `ao gate`'s labels are — refused naming the reported ones, `unchecked` with no reading — and the
    `settings` read gives each scheduled team `starts`: the tick's `schedule_next`, else the reading's reset."""
    await park_ticks(agent)
    async with LocalClient() as person:
        got = await person.call("set_settings", teams={"g": {"schedule": RULE}})
        assert got["unchecked"] is True and got["teams"]["g"]["schedule"] == RULE
        assert (await person.call("settings"))["teams"]["g"]["starts"] == {"at": None}
        reset = datetime.now(UTC) + timedelta(days=2)
        _reading(agent, reset)
        with pytest.raises(AgentError, match="profile grind reports no window 5h: its windows are week"):
            await person.call("set_settings", teams={"g": {"schedule": {**RULE, "window": "5h"}}})
        assert settings_mod.teams(settings_mod.load())["g"]["schedule"] == RULE  # refused before the write
        got = await person.call("set_settings", teams={"g": {"schedule": RULE}})
        assert "unchecked" not in got and got["teams"]["g"]["starts"] == {"at": _iso(reset)}  # the reply says it too
        assert (await person.call("settings"))["teams"]["g"]["starts"] == {"at": _iso(reset)}
        held = _iso(datetime.now(UTC) - timedelta(minutes=5))
        agent._host_rec["teams"] = {"g": {"schedule_next": {**RULE, "at": held, "held": True}}}
        assert (await person.call("settings"))["teams"]["g"]["starts"] == {"at": held, "held": True}
        agent._host_rec["teams"] = {"g": {"schedule_next": {"profile": "grind", "window": "5h", "at": held}}}
        assert (await person.call("settings"))["teams"]["g"]["starts"] == {"at": _iso(reset)}  # another rule's
        _reading(agent, datetime.now(UTC) - timedelta(hours=1))  # a reset passed and not yet rolled
        agent._host_rec["teams"] = {}
        assert (await person.call("settings"))["teams"]["g"]["starts"] == {"at": None}
        agent._usage["grind"] = {"windows": [{"label": "week", "resets": "2099-01-01T07:00:00"}]}  # no offset
        agent._host_rec["teams"] = "x"  # a malformed host record: the read still answers
        assert (await person.call("settings"))["teams"]["g"]["starts"] == {"at": None}
        agent._usage["grind"] = {"windows": [{"label": "week", "resets": "2099-01-01T08:00:00+01:00"}]}
        assert (await person.call("settings"))["teams"]["g"]["starts"] == {"at": "2099-01-01T07:00:00Z"}
        agent._host_rec["teams"] = {}


async def test_the_settings_read_answers_each_named_profiles_window_labels(agent):
    """TD-1346 (§4.5a *Settings page: Teams*): the page passes the profile names it read from `profiles.yml`
    and the `settings` read answers `labels`, each to the labels of the reading the gate judges it by, in
    the reading's order; a profile with none answers `[]`; no `profiles`, or not a list of names, no key."""
    await park_ticks(agent)
    agent._usage.clear()
    agent._usage["grind"] = {"windows": [{"label": "5h", "pct": 3}, {"label": "week", "pct": 12}, "junk"]}
    async with LocalClient() as person:
        got = await person.call("settings", profiles=["grind", "fresh"])
        assert got["labels"] == {"grind": ["5h", "week"], "fresh": []}
        assert "labels" not in await person.call("settings")
        assert "labels" not in await person.call("settings", profiles="grind")
        assert "labels" not in await person.call("settings", profiles=["grind", 3])


LOGIN_RULE = {"start": "reset", "login": "claude-code:a", "window": "week"}


def test_a_login_rule_is_a_switched_teams_alone():
    """§4.9d *When it runs* (TD-2091): a team that is not switched still needs its profile."""
    assert settings_mod.parse_team({"schedule": LOGIN_RULE}, switched=True) == {"schedule": LOGIN_RULE}
    no_login = {"start": "reset", "window": "week"}
    assert settings_mod.parse_team({"schedule": no_login}, switched=True) == {"schedule": no_login}
    blank = {**no_login, "login": ""}  # what the page sends for a rule on an empty login list
    assert settings_mod.parse_team({"schedule": blank}, switched=True) == {"schedule": no_login}
    for bad in (LOGIN_RULE, no_login):
        with pytest.raises(ValueError):
            settings_mod.parse_team({"schedule": bad})
    with pytest.raises(ValueError):
        settings_mod.parse_team({"schedule": RULE}, switched=True)
    doc = {"teams": {"sw": {"repo": "r", "schedule": LOGIN_RULE}, "old": {"schedule": LOGIN_RULE, "reserve": 3}}}
    assert settings_mod.teams(doc) == {"sw": {"schedule": LOGIN_RULE}, "old": {"reserve": 3}}


async def test_a_login_is_checked_when_saved_and_a_stale_one_stands(agent, monkeypatch):
    """Saved: in the list, not metered, a reported window. Read after the list moved: kept (TD-2091's ruling)."""
    await park_ticks(agent)
    here = agent.host
    entry = {"repo": "r", "host": here, "logins": ["claude-code:a", "claude-code:m"]}
    settings_mod.save({"teams": {"sw": {**entry}}})
    held = {"claude-code:a": {"account": "claude-code:acct"}, "claude-code:m": {"billing": "metered"}}
    monkeypatch.setattr("sessionorc.logins.load", lambda *_a: {"logins": held, "forgotten": {}})
    agent._usage_acct["claude-code:acct"] = {"windows": [{"label": "week", "pct": 1}]}
    async with LocalClient(paths.socket_path(), caller=None) as person:
        got = await person.call("set_settings", teams={"sw": {"schedule": LOGIN_RULE}})
        assert got["teams"]["sw"]["schedule"] == LOGIN_RULE and not got.get("unchecked")
        for rule, word in (
            ({**LOGIN_RULE, "login": "claude-code:z"}, "not in sw's logins"),
            ({**LOGIN_RULE, "login": "claude-code:m"}, "metered"),
            ({**LOGIN_RULE, "window": "5h"}, "reports no window"),
            (RULE, "names a login"),
        ):
            with pytest.raises(AgentError, match=word):
                await person.call("set_settings", teams={"sw": {"schedule": rule}})
    doc = settings_mod.load()
    doc["teams"]["sw"]["logins"] = ["claude-code:m"]
    settings_mod.save(doc)
    assert settings_mod.teams(settings_mod.load())["sw"]["schedule"] == LOGIN_RULE


async def test_a_nodes_team_cannot_save_a_schedule(agent):
    await park_ticks(agent)
    settings_mod.save({"teams": {"sw": {"repo": "r", "host": "elsewhere", "logins": ["claude-code:a"]}}})
    async with LocalClient(paths.socket_path(), caller=None) as person:
        with pytest.raises(AgentError, match="node's logins are not read here"):
            await person.call("set_settings", teams={"sw": {"schedule": LOGIN_RULE}})


async def test_a_login_rule_fires_nothing_before_the_cut_over(agent, monkeypatch):
    replays = await _setup(agent, monkeypatch, _rec("w"))
    settings_mod.save({"teams": {"g": {"repo": "r", "schedule": LOGIN_RULE}}})
    _reading(agent, datetime.now(UTC) - timedelta(minutes=1))
    await agent._schedules(datetime.now(UTC))
    assert replays.calls == [] and "schedule_next" not in _rec_of(agent)


SW_HELD = {
    "claude-code:a": {"account": "claude-code:acct"},
    "claude-code:b": {},
    "claude-code:m": {"billing": "metered"},
}


async def _switched(agent, monkeypatch, logins_=("claude-code:a", "claude-code:b"), rule=LOGIN_RULE) -> _Replays:
    """A switched team `g` after the cut-over, its schedule on a login (§6 *Schedule*, *After the cut-over*)."""
    replays = await _setup(agent, monkeypatch, _rec("w"))
    entry = {"repo": "r", "host": agent.host, "logins": list(logins_), "schedule": rule}
    settings_mod.save({"cut_over": "2026-12-01", "teams": {"g": entry}})
    agent._read_cut_over()
    monkeypatch.setattr("sessionorc.logins.load", lambda *_a: {"logins": SW_HELD, "forgotten": {}})
    return replays


def _acct(agent, key: str, resets: datetime) -> None:
    agent._usage_acct[key] = {"windows": [{"label": "week", "pct": 3, "resets": _iso(resets)}]}


async def test_a_switched_teams_reset_sets_its_started_mark_once_and_replays_nothing(agent, monkeypatch):
    """TD-2065: at its login's account's reset the schedule starts a team never started (no `stopped`) by its mark."""
    replays = await _switched(agent, monkeypatch)
    now = datetime.now(UTC)
    _acct(agent, "claude-code:acct", now + timedelta(hours=1))
    await agent._schedules(now)
    rec = _rec_of(agent)
    assert "started" not in rec and rec["schedule_next"]["login"] == "claude-code:a"
    assert agent._schedule_starts("g", LOGIN_RULE, now) == {"at": rec["schedule_next"]["at"]}
    later = now + timedelta(hours=1, minutes=2)
    await agent._schedules(later)
    rec = _rec_of(agent)
    assert rec["started"]["by"] == "schedule" and rec["schedule_fired"] == _iso(now + timedelta(hours=1))
    assert replays.calls == [], "a switched team is started by its mark, never by a replay"
    assert json.loads(paths.host_file().read_text())["teams"]["g"]["started"]["by"] == "schedule"
    agent._host_rec["teams"]["g"].pop("started")
    await agent._schedules(later)
    assert "started" not in _rec_of(agent), "once per reset"


@pytest.mark.parametrize(("stopped", "starts"), [({"by": "until"}, True), ({"by": "person"}, False)])
async def test_the_reset_starts_a_team_its_stop_time_stopped_and_never_one_the_person_wound_down(
    agent, monkeypatch, stopped, starts
):
    await _switched(agent, monkeypatch)
    now = datetime.now(UTC)
    agent._host_rec.setdefault("teams", {})["g"] = {"stopped": {"at": _iso(now - timedelta(days=1)), **stopped}}
    _acct(agent, "claude-code:acct", now - timedelta(minutes=1))
    await agent._schedules(now)
    rec = _rec_of(agent)
    assert ("started" in rec) is starts and ("stopped" in rec) is not starts
    assert rec["schedule_fired"] == _iso(now - timedelta(minutes=1)), "either way the reset counts as fired"


async def test_a_rule_whose_login_left_the_list_reads_the_first_and_a_metered_or_empty_list_starts_nothing(
    agent, monkeypatch
):
    now, gone = datetime.now(UTC), {**LOGIN_RULE, "login": "x:gone"}
    await _switched(agent, monkeypatch, logins_=("claude-code:b", "claude-code:a"), rule=gone)
    _acct(agent, "claude-code:b", now - timedelta(minutes=1))
    await agent._schedules(now)
    assert _rec_of(agent)["started"]["by"] == "schedule"
    for order in (("claude-code:m", "claude-code:a"), ()):
        agent._host_rec.get("teams", {}).pop("g", None)
        await _switched(agent, monkeypatch, logins_=order, rule=gone)  # the first is read: metered, or none
        _acct(agent, "claude-code:acct", now - timedelta(minutes=1))
        agent._usage_acct["claude-code:m"] = agent._usage_acct["claude-code:acct"]
        await agent._schedules(now)
        assert "started" not in _rec_of(agent) and "schedule_fired" not in _rec_of(agent), order
        assert agent._schedule_starts("g", gone, now) == {"at": None}


async def test_the_rules_own_login_is_read_where_it_is_in_the_list_and_a_started_team_is_left(agent, monkeypatch):
    """The named login, not the first, while it is in the list; a reset on a started team leaves its mark as it was."""
    await _switched(agent, monkeypatch, logins_=("claude-code:b", "claude-code:a"))
    now = datetime.now(UTC)
    _acct(agent, "claude-code:acct", now - timedelta(minutes=1))  # `a`'s account alone has a reading
    since = {"since": _iso(now - timedelta(days=2)), "by": "person"}
    agent._host_rec.setdefault("teams", {})["g"] = {"started": dict(since)}
    await agent._schedules(now)
    rec = _rec_of(agent)
    assert rec["started"] == since and rec["schedule_fired"] == _iso(now - timedelta(minutes=1))


async def test_a_login_rule_answers_no_next_reset_before_the_cut_over(agent, monkeypatch):
    await _switched(agent, monkeypatch)
    _acct(agent, "claude-code:acct", datetime.now(UTC) + timedelta(hours=1))
    assert agent._schedule_starts("g", LOGIN_RULE, datetime.now(UTC))["at"]
    doc = settings_mod.load()
    doc.pop("cut_over")
    settings_mod.save(doc)
    assert agent._schedule_starts("g", LOGIN_RULE, datetime.now(UTC)) == {"at": None}
