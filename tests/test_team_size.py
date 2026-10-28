"""A team's size (design §4.9 *A team's size*, TD-1164): `teams.<team>.size` per member line over its
`count:`, names that never move, read by `teams.plan` and the followable check."""

from __future__ import annotations

import json

import pytest
import yaml
from test_cli_teams import HOST, creates, started, world  # noqa: F401 — the fixture, by name

from shiftlead import cli, teamrun, teams
from shiftlead import org as orgmod


def _sized(world, tmp_path, size: dict, **team) -> orgmod.Org:  # noqa: F811
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["teams"]["ao-grind"].update(team)
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    (tmp_path / "home" / "settings.yml").write_text(yaml.safe_dump({"teams": {"ao-grind": {"size": size}}}))
    return orgmod.with_home_settings(orgmod.load())


@pytest.mark.parametrize("count", [1, 3])
def test_a_lines_names_never_move_as_its_size_changes(count):
    m = orgmod.MemberDef(role="grinder", name="grinder-ao", count=count)
    by = {n: m.names(n) for n in range(6)}
    assert by[0] == []
    for n in range(5):
        assert by[n + 1][:n] == by[n]  # no name of the lower size changes at a higher one
        assert len(by[n + 1]) == n + 1
    if count == 1:
        assert by[3] == ["grinder-ao", "grinder-ao-2", "grinder-ao-3"]
    else:
        assert by[2] == ["grinder-ao-1", "grinder-ao-2"]  # fewer than the count keeps the lowest-numbered
        assert by[4] == ["grinder-ao-1", "grinder-ao-2", "grinder-ao-3", "grinder-ao-4"]
    assert m.names() == by[count]  # no size: its count
    assert orgmod.MemberDef(role="grinder", name="grinder-ao", count=count, size=2).names() == by[2]


def test_the_setting_is_a_map_of_whole_numbers_from_zero():
    from sessionorc import settings as settings_mod

    assert settings_mod.parse_team({"size": {"grind": 3, "hunt": 0}}) == {"size": {"grind": 3, "hunt": 0}}
    for bad in (-1, 1.5, "2", True):
        with pytest.raises(ValueError, match=r"size\.grind is a whole number of sessions, 0 or more"):
            settings_mod.parse_team({"size": {"grind": bad}})
    with pytest.raises(ValueError, match="size is a mapping"):
        settings_mod.parse_team({"size": 3})
    # the reader's side drops what does not parse, line by line
    assert settings_mod.teams({"teams": {"t": {"size": {"a": -1, "": 1, "b": 2}}}}) == {"t": {"size": {"b": 2}}}
    with pytest.raises(ValueError, match="a member line's name is needed"):
        settings_mod.parse_team({"size": {"": 1}})


async def test_set_settings_refuses_a_bad_size_and_writes_a_good_one(agent):
    from sessionorc.client import AgentError, LocalClient

    async with LocalClient() as person:
        for bad in (-1, "two"):
            with pytest.raises(AgentError, match=r"teams\.ao-grind: size\.grind is a whole number"):
                await person.call("set_settings", teams={"ao-grind": {"size": {"grind": bad}}})
        got = await person.call("set_settings", teams={"ao-grind": {"size": {"grind": 3}}})
        assert got["teams"] == {"ao-grind": {"size": {"grind": 3}}}


def test_the_size_reaches_the_definition_and_its_names(world, tmp_path):  # noqa: F811
    org = _sized(world, tmp_path, {"grind": 3, "hunt": 0, "nope": 2})
    raw = orgmod.load().teams["ao-grind"]
    team = org.teams["ao-grind"]
    assert [m.size for m in raw.members] == [None, None]  # a copy: the definition never carries it
    assert team.size == {"grind": 3, "hunt": 0, "nope": 2}
    assert orgmod.with_settings(orgmod.load(), {"ao-grind": {"size": {}}}).teams["ao-grind"].members == raw.members
    assert [m.names() for m in team.members] == [["grind-1", "grind-2", "grind-3"], []]
    assert team.session_names() == ["orc-ao", "grind-1", "grind-2", "grind-3"]
    assert team.staffed() == {"grinder"} and raw.staffed() == {"grinder", "hunter"}
    assert team.unsized() == ["nope"]
    assert team.next_name("grinder") == "grind-4"  # past the size, never a name the size gives


def test_plan_starts_each_line_at_its_size(world, tmp_path):  # noqa: F811
    p = teams.plan(_sized(world, tmp_path, {"grind": 3}), "ao-grind", HOST)
    assert [m.name for m in p.members] == ["grind-1", "grind-2", "grind-3", "hunt"]
    p = teams.plan(_sized(world, tmp_path, {"grind": 1, "hunt": 2}), "ao-grind", HOST)
    assert [m.name for m in p.members] == ["grind-1", "hunt", "hunt-2"]


def test_a_size_of_zero_on_a_role_a_listed_flow_needs_is_not_followable(world, tmp_path):  # noqa: F811
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    extra = {"flows": ["build-review"], "techlead": {"name": "techlead-ao"}}
    teams.plan(_sized(world, tmp_path, {"hunt": 0}, **extra), "ao-grind", HOST)  # a role no stage needs
    with pytest.raises(teams.TeamError, match=r"build-review cannot be followed by ao-grind: no grinder"):
        teams.plan(_sized(world, tmp_path, {"grind": 0}, **extra), "ao-grind", HOST)


def test_org_check_names_a_size_key_no_line_holds(world, tmp_path, capsys):  # noqa: F811
    _sized(world, tmp_path, {"grind": 3, "nope": 2})
    assert cli.main(["org", "check"]) == 0
    out = capsys.readouterr().out
    assert "teams.ao-grind.size.nope in settings.yml: no member line of ao-grind is called nope" in out
    assert "size.grind" not in out


def test_team_list_and_the_settings_line_say_a_differing_size(world, tmp_path, capsys):  # noqa: F811
    _sized(world, tmp_path, {"grind": 2, "hunt": 2})
    assert cli.main(["team", "list"]) == 0
    out = capsys.readouterr().out
    assert "members: 4" in out
    assert "size: hunt 2 (file says 1)" in out and "grind 2" not in out  # grind's size is its count
    assert cli.main(["--json", "team", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["teams"][0]["sizes"] == ["hunt 2 (file says 1)"]
    team = orgmod.load().teams["ao-grind"]
    line = cli._team_setting_line("ao-grind", {"size": {"grind": 2, "hunt": 2}}, team)
    assert line.endswith("size hunt 2 (file says 1)")
    assert cli._team_setting_line("ao-grind", {"size": {"hunt": 2}}).endswith("size hunt 2")  # no org read


def test_the_members_view_and_a_live_add_read_the_sized_names(world, tmp_path):  # noqa: F811
    """Review of #2568: a line sized 0 holds no session in the Members view, and a live Add starts only
    the name it adds — the names before it are read sized, as the names after it are."""
    _, state = world
    path = tmp_path / "home" / "org.yml"
    v = teamrun.members_view(_sized(world, tmp_path, {"grind": 3, "hunt": 0}), "ao-grind", [])
    assert [len(e["sessions"]) for e in v["members"]] == [3, 0] and not any(e["twice"] for e in v["members"])
    _sized(world, tmp_path, {"grind": 3})
    started(state)
    got = teamrun.add_member(cli.call_sync, path, "ao-grind", HOST, role="hunter")
    assert [c["name"] for c in creates(state)] == ["hunter"]  # grind-3 is not started again
    assert [r["name"] for r in got["created"]] == ["hunter"]


# ── slice 2: the next free name, a resize, `ao team size` ──────────────────────────────────────────


def _rec(name: str, **kw) -> dict:
    return {"id": f"ao-{name}", "name": name, "team": "ao-grind", "state": "idle", "unattended": True, **kw}


def test_next_free_is_past_the_size_or_from_a_position_and_skips_a_held_name(world, tmp_path):  # noqa: F811
    team = _sized(world, tmp_path, {"grind": 3}).teams["ao-grind"]
    assert team.next_free("grind", []) == "grind-4"  # past the size
    assert team.next_free("grind", [], from_=1) == "grind-2"
    assert team.next_free("grind", [_rec("grind-2")], from_=1) == "grind-3"  # a live record holds grind-2
    assert team.next_free("grind", [_rec("grind-4")]) == "grind-5"
    ended = _rec("grind-4", state="closed", closed_for={"why": "run_ended"})
    assert team.next_free("grind", [ended]) == "grind-4"  # a run_ended record holds none: the create supersedes it
    sat = _rec("grind-4", state="closed", closed_for={"why": "sit_out"})
    assert team.next_free("grind", [sat, _rec("grind-5", superseded_by="x")]) == "grind-4"
    assert team.next_free("hunt", [_rec("hunt")], from_=0) == "hunt-2"  # a count-1 line's extras are -2, -3
    with pytest.raises(ValueError, match="team ao-grind has no member line 'mill' \\(its lines: grind, hunt\\)"):
        team.next_free("mill", [])


def test_ao_team_size_on_a_stopped_team_writes_the_setting_only(world, tmp_path, capsys):  # noqa: F811
    _, state = world
    assert cli.main(["team", "size", "ao-grind", "hunt", "2"]) == 0
    assert capsys.readouterr().out.strip() == "hunt: 2 (file says 1) · from the next Start"
    assert state["teams"] == {"ao-grind": {"size": {"hunt": 2}}}
    assert cli.main(["team", "size", "ao-grind", "grind", "1"]) == 0  # the other line's size kept
    assert state["teams"]["ao-grind"]["size"] == {"hunt": 2, "grind": 1}
    assert not creates(state) and not [c for c in state["calls"] if c[0] == "relaunch"]


@pytest.mark.parametrize(
    ("line", "n", "says"),
    [
        ("mill", "2", "team ao-grind has no member line 'mill' (its lines: grind, hunt, grind-3)"),
        ("grind", "-1", "grind: a size is a whole number of sessions, 0 or more, not -1"),
        ("grind", "0", "build-review needs a grinder: drop build-review from flows: first"),
        ("grind", "3", "grind-3 is another line's: rename one of them in the definition"),
    ],
)
def test_ao_team_size_refuses_and_writes_nothing(world, tmp_path, capsys, line, n, says):  # noqa: F811
    _, state = world
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["teams"]["ao-grind"].update(flows=["build-review"], techlead={"name": "techlead-ao"})
    doc["teams"]["ao-grind"]["members"].append({"role": "hunter", "name": "grind-3"})
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    assert cli.main(["team", "size", "ao-grind", line, n]) == 1
    assert says in capsys.readouterr().err
    assert "teams" not in state


def test_a_resize_on_a_live_team_creates_one_and_winds_one_down(world, tmp_path, capsys):  # noqa: F811
    _, state = world
    started(state)
    capsys.readouterr()
    assert cli.main(["team", "size", "ao-grind", "grind", "3"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("grind: 3 (file says 2)") and "started grind-3 under ao-shiftlead-orc-ao" in out
    made = creates(state)
    assert [p["name"] for p in made] == ["grind-3"] and made[0]["controllers"] == ["ao-shiftlead-orc-ao"]
    state["calls"].clear()
    assert cli.main(["team", "size", "ao-grind", "grind", "1"]) == 0
    out = capsys.readouterr().out
    downs = [p for m, p in state["calls"] if m == "relaunch"]
    assert [p["id"] for p in downs] == ["ao-shiftlead-grind-3", "ao-shiftlead-grind-2"]  # highest first
    assert all(p["sit_out"] and p["dropped"] for p in downs) and not creates(state)
    assert out.startswith("grind: 1 (file says 2) — grind-3 is wound down by the home")
    # a step up skips a name a live record already holds and starts nothing twice
    state["calls"].clear()
    for s in state["sessions"]:
        s.pop("sit_out", None)
    assert cli.main(["team", "size", "ao-grind", "grind", "3"]) == 0
    assert not creates(state)


def test_a_lowered_size_on_a_stopped_team_is_a_removal_start_marks(world, tmp_path, capsys):  # noqa: F811
    _, state = world
    started(state)
    state["host"] = {"host": "local"}
    for s in state["sessions"]:
        s["state"] = "closed"
    (tmp_path / "home" / "settings.yml").write_text(yaml.safe_dump({"teams": {"ao-grind": {"size": {"grind": 1}}}}))
    org = orgmod.with_home_settings(orgmod.load())
    plan = teams.plan(org, "ao-grind", HOST, files=teamrun.files_via(cli.call_sync))
    _, removals = teamrun.renames(plan, state["sessions"])
    assert [r["name"] for r in removals] == ["grind-2"]
    state["calls"].clear()
    assert cli.main(["--json", "team", "start", "ao-grind", "--anyway"]) == 0
    acts = [(m, p) for m, p in state["calls"] if m in ("create", "relaunch")]
    assert acts[0] == ("relaunch", {"id": "ao-shiftlead-grind-2", "sit_out": True, "dropped": True})
    assert "grind-2" not in {p["name"] for m, p in acts if m == "create"}


# ── slice 3: a run-only member, `start_member`, and a step up adopting one ─────────────────────────


def _keeps(state):
    """The fake agent, taught the `keep` act: `run_only` cleared on the record it names."""
    fake = cli.call_sync

    def call(method, **params):
        if method != "keep":
            return fake(method, **params)
        state["calls"].append((method, params))
        s = next(s for s in state["sessions"] if s["id"] == params["id"])
        s["run_only"] = False
        return s

    return call


def test_start_member_creates_the_lines_next_name_past_its_size_run_only(world, tmp_path):  # noqa: F811
    _, state = world
    started(state)
    org = orgmod.with_home_settings(orgmod.load())
    got = teamrun.start_member(cli.call_sync, org, "ao-grind", "grind", HOST, run_only=True)
    made = creates(state)
    assert [p["name"] for p in made] == ["grind-3"] and made[0]["run_only"] is True
    assert made[0]["controllers"] == ["ao-shiftlead-orc-ao"] and made[0]["supervised"] is True
    assert got["text"] == "started grind-3"
    state["calls"].clear()
    teamrun.start_member(cli.call_sync, org, "ao-grind", "hunt", HOST)  # a kept one sends no `run_only`
    assert [(p["name"], "run_only" in p) for p in creates(state)] == [("hunt-2", False)]
    with pytest.raises(teams.TeamError, match="no member line 'mill'"):
        teamrun.start_member(cli.call_sync, org, "ao-grind", "mill", HOST)


def test_a_step_up_adopts_a_live_run_only_member_that_holds_the_next_name(world, tmp_path, capsys):  # noqa: F811
    _, state = world
    started(state)
    org = orgmod.with_home_settings(orgmod.load())
    teamrun.start_member(cli.call_sync, org, "ao-grind", "grind", HOST, run_only=True)
    state["sessions"][-1]["run_only"] = True  # as the home writes it on the create's record
    state["calls"].clear()
    call = _keeps(state)
    got = teamrun.resize(call, org, "ao-grind", "grind", 3, HOST)
    assert ("keep", {"id": "ao-shiftlead-grind-3"}) in state["calls"] and not creates(state)  # nothing created
    assert [r["name"] for r in got["adopted"]] == ["grind-3"] and not got["created"]
    assert "grind-3 is kept, no longer for this run alone" in got["text"]
    # a resize of more than one passes it: grind-4 adopted, grind-5 created
    teamrun.start_member(cli.call_sync, org, "ao-grind", "grind", HOST, run_only=True)
    state["sessions"][-1]["run_only"] = True
    state["calls"].clear()
    org = orgmod.with_home_settings(orgmod.load())
    got = teamrun.resize(call, org, "ao-grind", "grind", 5, HOST)
    assert [p["id"] for m, p in state["calls"] if m == "keep"] == ["ao-shiftlead-grind-4"]
    assert [p["name"] for p in creates(state)] == ["grind-5"] and "run_only" not in creates(state)[0]


# ── TD-1179: each of `resize`'s branches, set by a test ────────────────────────────────────────────


def _flows(tmp_path, *members):
    """`ao-grind` under listed flows (`build-review` current, `td` beside it), with `members` appended."""
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["teams"]["ao-grind"].update(flows=["build-review", "td"], techlead={"name": "techlead-ao"})
    doc["teams"]["ao-grind"]["members"].extend(members)
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))


def test_a_step_up_on_a_line_the_flow_does_not_use_is_counted_not_started(world, tmp_path):  # noqa: F811
    _, state = world
    _flows(tmp_path, {"role": "designer", "name": "designer-ao"})
    started(state)
    got = teamrun.resize(cli.call_sync, orgmod.with_home_settings(orgmod.load()), "ao-grind", "designer-ao", 2, HOST)
    assert got["text"] == "designer-ao: 2 (file says 1) — designer-ao sits out under build-review: counted, not started"
    assert not creates(state) and state["teams"]["ao-grind"]["size"] == {"designer-ao": 2}


def test_a_step_down_passes_over_a_run_only_and_a_sat_out_member(world, tmp_path):  # noqa: F811
    _, state = world
    started(state)
    by = {s["name"]: s for s in state["sessions"]}
    by["grind-2"]["run_only"] = True
    by["grind-1"]["sit_out"] = {"at": "now"}  # a counted line's names: grind-1, grind-2
    got = teamrun.resize(cli.call_sync, orgmod.with_home_settings(orgmod.load()), "ao-grind", "grind", 0, HOST)
    assert not [c for c in state["calls"] if c[0] == "relaunch"] and got["wound_down"] == []
    assert got["text"] == "grind: 0 (file says 2)"


def test_a_failed_wind_down_stops_the_walk_and_says_what_was_done(world, tmp_path):  # noqa: F811
    _, state = world
    started(state)
    state["refuse"] = {"ao-shiftlead-grind-1": "the link is down"}
    got = teamrun.resize(cli.call_sync, orgmod.with_home_settings(orgmod.load()), "ao-grind", "grind", 0, HOST)
    assert [p["id"] for m, p in state["calls"] if m == "relaunch"] == ["ao-shiftlead-grind-2", "ao-shiftlead-grind-1"]
    assert got["text"].startswith(
        "grind: 0 (file says 2) — stopped at grind-1: the link is down — grind-2 is wound down"
    )
    assert state["teams"]["ao-grind"]["size"] == {"grind": 0}, "the setting stays written"


def test_a_step_up_stops_where_a_live_session_holds_the_name(world, tmp_path):  # noqa: F811
    _, state = world
    started(state)
    state["verdicts"]["grind-4"] = {"name": "grind-4", "verdict": "live"}
    got = teamrun.resize(cli.call_sync, orgmod.with_home_settings(orgmod.load()), "ao-grind", "grind", 4, HOST)
    assert [p["name"] for p in creates(state)] == ["grind-3"]
    assert got["text"] == "grind: 4 (file says 2) — stopped at grind-4: a live session holds the name; started grind-3"
    assert state["teams"]["ao-grind"]["size"] == {"grind": 4}, "the setting stays written"


def test_a_size_of_zero_passes_where_another_line_holds_the_role(world, tmp_path):  # noqa: F811
    _, state = world
    _flows(tmp_path, {"role": "grinder", "name": "mill"})
    got = teamrun.resize(cli.call_sync, orgmod.with_home_settings(orgmod.load()), "ao-grind", "grind", 0, HOST)
    assert got["size"] == 0 and state["teams"]["ao-grind"]["size"] == {"grind": 0}


@pytest.mark.parametrize("n", [True, 2.0, "2"])
def test_a_size_that_is_not_a_whole_number_is_refused(world, tmp_path, n):  # noqa: F811
    _, state = world
    with pytest.raises(teams.TeamError, match="grind: a size is a whole number of sessions, 0 or more, not "):
        teamrun.resize(cli.call_sync, orgmod.with_home_settings(orgmod.load()), "ao-grind", "grind", n, HOST)
    assert "teams" not in state
