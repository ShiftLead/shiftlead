"""`ao team max` and `teamrun.set_max` (design §4.7, §4.9 *Scaling with the work*, td-max; TD-1545 slice 8): the
setting's write — a ceiling, `0` at or below the size, `off` and `on` — and its refusals."""

from __future__ import annotations

import pytest
from test_cli_teams import creates, started, world  # noqa: F401 — the fixture, by name

from shiftlead import cli
from shiftlead import org as orgmod


def _max(state):
    return state["teams"]["ao-grind"].get("max")


def test_a_ceiling_is_written_and_one_at_or_below_the_size_is_stored_as_zero(world, capsys):  # noqa: F811
    _, state = world
    assert cli.main(["team", "max", "ao-grind", "grind", "5"]) == 0
    assert capsys.readouterr().out.strip() == "grind: up to 5"
    assert _max(state) == {"grind": 5}
    assert cli.main(["team", "max", "ao-grind", "hunt", "1"]) == 0  # hunt's size is 1: no scaling at any size
    assert capsys.readouterr().out.strip() == "hunt: no scaling — 1 is at or below its size 1"
    assert _max(state) == {"grind": 5, "hunt": 0}  # the other line's ceiling kept
    assert orgmod.with_home_settings(orgmod.load()).teams["ao-grind"].extra_names("hunt") == []
    assert not creates(state)


def test_off_replaces_the_ceilings_a_raise_from_off_turns_on_one_line_and_on_removes_the_key(world, capsys):  # noqa: F811
    _, state = world
    assert cli.main(["team", "max", "ao-grind", "grind", "5"]) == 0
    assert cli.main(["team", "max", "ao-grind", "off"]) == 0
    assert _max(state) == "off"
    assert cli.main(["team", "max", "ao-grind", "hunt", "3"]) == 0
    assert _max(state) == {"grind": 0, "hunt": 3}  # every other line that may scale at 0
    team = orgmod.with_home_settings(orgmod.load()).teams["ao-grind"]
    assert team.extra_names("grind") == [] and team.extra_names("hunt") == ["hunt-2", "hunt-3"]
    assert cli.main(["team", "max", "ao-grind", "on"]) == 0
    assert "on — each line and seat on its default ceiling" in capsys.readouterr().out
    team = orgmod.with_home_settings(orgmod.load()).teams["ao-grind"]
    assert team.max is None and team.extra_names("grind") == ["grind-3", "grind-4"]


@pytest.mark.parametrize(
    ("args", "says"),
    [
        (["orc-ao", "3"], "orc-ao is the manager: one lead per team"),
        (["mill", "3"], "team ao-grind has no member line or seat 'mill'"),
        (["grind", "-1"], "grind: an up to is a whole number of sessions, 0 or more, not -1"),
        (["grind"], "ao team max <team> <name> <n>, or ao team max <team> off|on"),
    ],
)
def test_what_may_not_scale_is_refused_and_nothing_written(world, capsys, args, says):  # noqa: F811
    _, state = world
    assert cli.main(["team", "max", "ao-grind", *args]) in (1, 2)
    assert says in capsys.readouterr().err
    assert "teams" not in state


def test_a_seat_on_another_trigger_is_refused_in_its_words(world, tmp_path, capsys):  # noqa: F811
    import yaml

    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["teams"]["ao-grind"]["seats"] = [{"name": "sweeper", "role": "auditor", "trigger": {"prs": 10}}]
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    assert cli.main(["team", "max", "ao-grind", "sweeper", "3"]) == 1
    assert "sweeper is on prs: one pass covers the repo" in capsys.readouterr().err


def test_a_session_is_refused(world, monkeypatch, capsys):  # noqa: F811
    _, state = world
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-shiftlead-orc-ao")
    assert cli.main(["team", "max", "ao-grind", "off"]) == 1
    assert "refused to a session" in capsys.readouterr().err and "teams" not in state


def test_on_a_live_team_the_extras_follow_at_the_next_start(world, capsys):  # noqa: F811
    _, state = world
    started(state)
    capsys.readouterr()
    assert cli.main(["team", "max", "ao-grind", "grind", "4"]) == 0
    assert capsys.readouterr().out.strip() == "grind: up to 4 · the extras follow at the next Start"


def test_a_seat_scales_from_a_size_of_one(world, tmp_path, capsys):  # noqa: F811
    """#3296's review: the techlead seat and an `asks` seat are sized 1 — 3 writes two extras, 1 none."""
    import yaml

    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["teams"]["ao-grind"]["techlead"] = {"name": "tl-ao"}
    doc["teams"]["ao-grind"]["seats"] = [{"name": "fc-ao", "role": "auditor", "trigger": "asks"}]
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    _, state = world
    assert cli.main(["team", "max", "ao-grind", "tl-ao", "3"]) == 0
    assert cli.main(["team", "max", "ao-grind", "fc-ao", "1"]) == 0
    assert _max(state) == {"tl-ao": 3, "fc-ao": 0}
    team = orgmod.with_home_settings(orgmod.load()).teams["ao-grind"]
    assert team.extra_names("tl-ao") == ["tl-ao-2", "tl-ao-3"] and team.extra_names("fc-ao") == []
