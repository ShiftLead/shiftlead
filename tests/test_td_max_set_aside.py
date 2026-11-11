"""A `teams.<team>.max` key already in `settings.yml` that names what may not scale (design §4.9 *Scaling with the
work*, *What does not*; td-max, TD-1545): set aside, and said by `ao org check` and the team's settings line."""

from __future__ import annotations

import pytest
import yaml
from test_cli_teams import HOST, world  # noqa: F401 — the fixture, by name

from shiftlead import cli, orgcheck, teamrun, teams
from shiftlead import org as orgmod

REFUSED = {"orc-ao": 3, "mill": 2, "sweeper": 2, "hunt": 3}
SAYS = {
    "orc-ao": "orc-ao is the manager: one lead per team",
    "mill": "team ao-grind has no member line or seat 'mill'",
    "sweeper": "sweeper is on prs: one pass covers the repo",
    "hunt": "hunt's lane is in no stage: its lane has no queue to read",  # the fixture's hunter runs an area lane
}


def _file(tmp_path, ceilings) -> None:
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["teams"]["ao-grind"]["seats"] = [{"name": "sweeper", "role": "auditor", "trigger": {"prs": 10}}]
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    (tmp_path / "home" / "settings.yml").write_text(yaml.safe_dump({"teams": {"ao-grind": {"max": ceilings}}}))


def test_org_check_sets_aside_each_key_that_may_not_scale_and_says_why(world, capsys):  # noqa: F811
    tmp_path, _ = world
    _file(tmp_path, {"grind": 4, **REFUSED})
    assert cli.main(["org", "check"]) == 0  # a warning, as an ignored size key is: nothing lacks
    out = capsys.readouterr().out
    for key, why in SAYS.items():
        assert f"warning: teams.ao-grind.max.{key} in settings.yml: {why} — set aside, no extra runs for it" in out
    assert "max.grind" not in out  # a line that may scale is no warning
    org = orgmod.with_home_settings(orgmod.load())
    assert [org.teams["ao-grind"].extra_names(k) for k in ("orc-ao", "mill", "sweeper")] == [[], [], []]


def test_an_area_lanes_key_plans_no_extra(world, monkeypatch):  # noqa: F811
    """Review of slice 12: the lane case is set aside by the plan, not by `ceiling` — no extra launch for it."""
    tmp_path, _ = world
    monkeypatch.setattr(teams, "_extras", teams.EXTRAS)  # conftest stubs it: put the real one back
    _file(tmp_path, {"grind": 4, "hunt": 3})
    plan = teams.plan(orgmod.with_home_settings(orgmod.load()), "ao-grind", HOST)
    held = [x.name for x in plan.extras]
    assert not any(n.startswith("hunt") for n in held)
    assert any(n.startswith("grind") for n in held)


def test_a_value_that_is_no_whole_number_is_read_as_with_settings_reads_it(world):  # noqa: F811
    team = orgmod.load().teams["ao-grind"]
    assert "set aside" not in cli._team_setting_line("ao-grind", {"max": {"mill": "two"}}, team)


def test_the_settings_line_says_each_key_set_aside(world, capsys):  # noqa: F811
    tmp_path, state = world
    _file(tmp_path, {"grind": 4, **REFUSED})
    state["teams"] = {"ao-grind": {"max": {"grind": 4, **REFUSED}}}
    assert cli.main(["team", "on-work", "ao-grind", "start"]) == 0
    line = capsys.readouterr().out.strip()
    assert line.startswith("ao-grind: ") and "when work appears: start the team" in line
    for key, why in SAYS.items():
        assert f"max.{key} set aside: {why}" in line
    assert "max.grind" not in line
    # without the definition (no org read), nothing is said: the number alone is `size_words`' rule too
    assert "set aside" not in cli._team_setting_line("ao-grind", {"max": REFUSED})


def test_a_team_at_off_or_on_its_defaults_sets_nothing_aside(world):  # noqa: F811
    team = orgmod.load().teams["ao-grind"]
    assert teamrun.set_aside_max(team) == []
    assert (
        teamrun.set_aside_max(orgmod.with_settings(orgmod.load(), {"ao-grind": {"max": "off"}}).teams["ao-grind"]) == []
    )
    # with no plan, the lane case is the next Start's to say; the names' own refusals are read from the definition
    got = teamrun.set_aside_max(
        orgmod.with_settings(orgmod.load(), {"ao-grind": {"max": {"hunt": 3, "x": 2}}}).teams["ao-grind"]
    )
    assert got == [("x", "team ao-grind has no member line or seat 'x'")]


def test_the_dialogs_lane_refusals_name_an_area_lane_alone(world, monkeypatch):  # noqa: F811
    """The Members dialog's **up to** (§4.5a, TD-1545 slice 15): `lane_refusals` reads one plan and names the member
    line whose lane is in no stage — the fixture's hunter — and no other; `members_view` draws it disabled."""
    monkeypatch.setattr(teamrun, "files_via", lambda call: None)  # the plan reads this host's checkout
    org = orgmod.with_home_settings(orgmod.load())
    got = teamrun.lane_refusals(lambda *a, **k: None, org, "ao-grind", HOST)
    assert got == {"hunt": "hunt's lane is in no stage: its lane has no queue to read"}
    v = teamrun.members_view(org, "ao-grind", [], None, got)
    ups = {e["name"]: e["up_to"] for e in v["members"]}
    assert (ups["hunt"]["why"], ups["hunt"]["value"]) == ("its lane has no queue to read", None)
    assert ups["grind"]["why"] == "" and ups["grind"]["value"] is not None


def _org_with_mill(tmp_path) -> orgmod.Org:
    _file(tmp_path, {"grind": 4, "mill": 2})
    return orgmod.with_home_settings(orgmod.load())


MILL = (
    "teams.ao-grind.max.mill in settings.yml: team ao-grind has no member line or seat 'mill' — set aside, "
    "no extra runs for it"
)


def test_org_check_says_a_key_set_aside_on_an_unlanded_team(world, monkeypatch):  # noqa: F811
    """TD-1621: an unlanded team skips its plan, and its set-aside keys are still said (#3349)."""
    tmp_path, _ = world
    org = _org_with_mill(tmp_path)
    monkeypatch.setattr(teams, "plan", lambda *a, **k: pytest.fail("an unlanded team is planned"))
    org.unlanded["ao-grind"] = "place.ao-grind: the node could not be asked"
    assert MILL in orgcheck.check(org, [], HOST, [], [])["warnings"]


def test_org_check_says_a_key_set_aside_on_a_team_whose_plan_fails(world, monkeypatch):  # noqa: F811
    """TD-1621: a team whose start would be refused is a lack, and its set-aside keys are still said (#3349)."""
    tmp_path, _ = world
    org = _org_with_mill(tmp_path)

    def refused(*a, **k):
        raise teams.TeamError("brief gone")

    monkeypatch.setattr(teams, "plan", refused)
    got = orgcheck.check(org, [], HOST, [], [])
    assert "brief gone" in got["lacks"]
    assert MILL in got["warnings"]
