"""A team's size (design §4.9 *A team's size*, TD-1164): `teams.<team>.size` per member line over its
`count:`, names that never move, read by `teams.plan` and the followable check."""

from __future__ import annotations

import json

import pytest
import yaml
from test_cli_teams import HOST, world  # noqa: F401 — the fixture, by name

from shiftlead import cli, teams
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
    assert settings_mod.teams({"teams": {"t": {"size": {"a": -1, "b": 2}}}}) == {"t": {"size": {"b": 2}}}


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
    assert [m.names() for m in team.members] == [["grind-1", "grind-2", "grind-3"], []]
    assert team.session_names() == ["orc-ao", "grind-1", "grind-2", "grind-3"]
    assert team.staffed() == {"grinder"}
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
