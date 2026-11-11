"""A `teams.<team>.max` key already in `settings.yml` that names what may not scale (design §4.9 *Scaling with the
work*, *What does not*; td-max, TD-1545): set aside, and said by `ao org check` and the team's settings line."""

from __future__ import annotations

import yaml
from test_cli_teams import world  # noqa: F401 — the fixture, by name

from shiftlead import cli, teamrun
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
    team = orgmod.with_home_settings(orgmod.load()).teams["ao-grind"]
    assert [team.extra_names(k) for k in ("orc-ao", "mill", "sweeper")] == [[], [], []]  # set aside: no extra


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
