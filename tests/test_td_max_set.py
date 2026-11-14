"""`ao team max` and `teamrun.set_max` (design §4.7, §4.9 *Scaling with the work*, td-max; TD-1545 slice 8): the
setting's write — a ceiling, `0` at or below the size, `off` and `on` — and its refusals."""

from __future__ import annotations

import json

import pytest
import yaml
from test_cli_teams import creates, org_doc, started, world  # noqa: F401 — the fixture, by name

from shiftlead import cli
from shiftlead import org as orgmod


@pytest.fixture(autouse=True)
def hunt_builds(request):
    """The fixture's hunter runs an area lane (`ui`), which takes no extra (§4.9 *What scales*): these tests scale
    it as a build line, `free-pick`, and the area lane's refusal is tested on its own."""
    if "world" not in request.fixturenames or "area_lane" in request.node.name:
        return
    tmp_path, _ = request.getfixturevalue("world")
    doc = org_doc(tmp_path)
    doc["teams"]["ao-grind"]["members"][1]["lane"] = "free-pick"
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))


@pytest.fixture
def extras_on(monkeypatch):
    from shiftlead import teams

    monkeypatch.setattr(teams, "_extras", teams.EXTRAS)  # conftest stubs it: put the real one back


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


def test_on_a_team_with_nothing_live_the_setting_is_all(world, extras_on, capsys):  # noqa: F811
    _, state = world
    assert cli.main(["team", "max", "ao-grind", "grind", "4"]) == 0
    assert capsys.readouterr().out.strip() == "grind: up to 4"
    assert not creates(state)


def _removes(state, monkeypatch):
    real = cli.call_sync

    def call(method, **params):
        if method == "relaunch" and params.get("drop_extra"):  # the home's `drop_extra` (TD-1545): the mark
            state["calls"].append((method, params))
            if (why := state.get("refuse", {}).get(params["id"])) is not None:
                raise cli.AgentError(why)
            s = next(s for s in state["sessions"] if s["id"] == params["id"])
            s["scale"] = {**s["scale"], "drop": "now"}
            return s
        if method != "remove":
            return real(method, **params)
        state["calls"].append((method, params))
        state["sessions"][:] = [s for s in state["sessions"] if s["id"] != params["id"]]

    monkeypatch.setattr(cli, "call_sync", call)


def _held(name, line, st="closed"):
    return {"id": f"ao-shiftlead-{name}", "name": name, "state": st, "team": "ao-grind", "scale": {"line": line}}


def test_on_a_live_team_a_raise_writes_the_new_extras_held_at_once(world, extras_on, monkeypatch, capsys):  # noqa: F811
    _, state = world
    _removes(state, monkeypatch)
    assert cli.main(["team", "max", "ao-grind", "off"]) == 0
    started(state)
    capsys.readouterr()
    assert cli.main(["team", "max", "ao-grind", "grind", "4"]) == 0
    assert capsys.readouterr().out.strip() == "grind: up to 4 · grind-3, grind-4: written held"
    got = {p["name"]: p for p in creates(state)}
    assert sorted(got) == ["grind-3", "grind-4"]
    assert got["grind-3"]["held"] is True and got["grind-3"]["scale"] == {"line": "grind"}
    assert got["grind-3"]["controllers"] == ["ao-shiftlead-orc-ao"]  # under the live manager


def test_a_raise_on_a_live_team_names_the_extras_it_wrote_by_id(world, extras_on, monkeypatch, capsys):  # noqa: F811
    """`ao team max --json`'s result carries the records written in `extras`, by id (TD-1616)."""
    _, state = world
    _removes(state, monkeypatch)
    assert cli.main(["team", "max", "ao-grind", "off"]) == 0
    started(state)
    capsys.readouterr()
    assert cli.main(["--json", "team", "max", "ao-grind", "grind", "4"]) == 0
    assert json.loads(capsys.readouterr().out)["extras"] == ["ao-shiftlead-grind-3", "ao-shiftlead-grind-4"]


def test_a_lowered_max_on_a_live_team_drops_held_extras_and_winds_down_live_ones(world, extras_on, monkeypatch, capsys):  # noqa: F811, E501
    _, state = world
    _removes(state, monkeypatch)
    assert cli.main(["team", "max", "ao-grind", "grind", "4"]) == 0
    started(state)
    state["sessions"][:] = [s for s in state["sessions"] if s["name"] in ("orc-ao", "grind-1", "grind-2", "hunt")]
    state["sessions"] += [_held("grind-3", "grind", "idle"), _held("grind-4", "grind"), _held("hunt-2", "hunt")]
    capsys.readouterr()
    assert cli.main(["team", "max", "ao-grind", "off"]) == 0
    out = capsys.readouterr().out
    assert [p["id"] for m, p in state["calls"] if m == "remove"] == ["ao-shiftlead-grind-4", "ao-shiftlead-hunt-2"]
    assert "grind-4: the held extra of grind removed — the max no longer holds it" in out
    assert "grind-3: a live extra of grind the max no longer holds — wound down, dropped once closed" in out
    drops = [p for m, p in state["calls"] if m == "relaunch"]
    assert drops == [{"id": "ao-shiftlead-grind-3", "drop_extra": True}]  # never a sit-out, never a kill
    assert not any(m in ("kill", "send") for m, _ in state["calls"])
    assert not creates(state)
    # said again: an extra already marked is said, never wound down twice
    assert cli.main(["team", "max", "ao-grind", "off"]) == 0
    assert "grind-3: a live extra of grind the max no longer holds — dropped once closed" in capsys.readouterr().out
    assert len([m for m, _ in state["calls"] if m == "relaunch"]) == 1


def test_a_live_extra_whose_wind_down_is_refused_is_said_and_the_setting_stands(world, extras_on, monkeypatch, capsys):  # noqa: F811
    _, state = world
    _removes(state, monkeypatch)
    assert cli.main(["team", "max", "ao-grind", "grind", "3"]) == 0
    started(state)
    state["sessions"] += [_held("grind-3", "grind", "working")]
    state["refuse"] = {"ao-shiftlead-grind-3": "grind-3: the wrap-up could not be sent (pending), so it is not dropped"}
    capsys.readouterr()
    assert cli.main(["team", "max", "ao-grind", "grind", "2"]) == 0
    out = capsys.readouterr().out
    assert "grind-3: a live extra of grind the max no longer holds was not wound down — grind-3: the wrap-up" in out
    assert _max(state) == {"grind": 0}


def test_on_after_off_on_a_live_team_writes_the_default_extras(world, extras_on, monkeypatch, capsys):  # noqa: F811
    _, state = world
    _removes(state, monkeypatch)
    assert cli.main(["team", "max", "ao-grind", "off"]) == 0
    started(state)
    assert cli.main(["team", "max", "ao-grind", "on"]) == 0
    assert sorted(p["name"] for p in creates(state)) == ["grind-3", "grind-4", "hunt-2", "hunt-3"]


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


def test_on_a_live_team_a_lowered_ceiling_removes_the_held_extra_past_it(world, extras_on, monkeypatch, capsys):  # noqa: F811
    _, state = world
    _removes(state, monkeypatch)
    assert cli.main(["team", "max", "ao-grind", "grind", "4"]) == 0
    started(state)
    state["sessions"][:] = [s for s in state["sessions"] if s["name"] in ("orc-ao", "grind-1", "grind-2", "hunt")]
    state["sessions"] += [_held("grind-3", "grind"), _held("grind-4", "grind")]
    assert cli.main(["team", "max", "ao-grind", "grind", "3"]) == 0
    assert [p["id"] for m, p in state["calls"] if m == "remove"] == ["ao-shiftlead-grind-4"]
    assert "grind-3" in {p["name"] for p in creates(state)}  # the one it keeps written again: its launch record now


def test_a_plan_that_cannot_be_read_is_said_and_the_setting_stands(world, extras_on, monkeypatch, capsys):  # noqa: F811
    from shiftlead import teams

    _, state = world
    started(state)
    capsys.readouterr()

    def broken(*a, **k):
        raise teams.TeamError("brief gone")

    monkeypatch.setattr(teams, "plan", broken)
    assert cli.main(["team", "max", "ao-grind", "grind", "4"]) == 0
    assert "the team's plan could not be read: brief gone" in capsys.readouterr().out
    assert _max(state) == {"grind": 4}


def test_with_no_flow_an_area_lane_is_refused_and_nothing_written(world, capsys):  # noqa: F811
    _, state = world
    assert cli.main(["team", "max", "ao-grind", "hunt", "3"]) == 1
    assert "hunt's lane is in no stage: its lane has no queue to read" in capsys.readouterr().err
    assert "teams" not in state


def test_a_member_line_of_two_stores_a_ceiling_at_its_size_as_zero_and_one_past_it_as_written(world, capsys):  # noqa: F811
    """`set_max` sizes a member line by its names (#3296, TD-1591): `grind` has two, so 2 is at its size and stored
    as `0`, and 3 is past it and stored as 3."""
    _, state = world
    assert cli.main(["team", "max", "ao-grind", "grind", "2"]) == 0
    assert capsys.readouterr().out.strip() == "grind: no scaling — 2 is at or below its size 2"
    assert _max(state) == {"grind": 0}
    assert cli.main(["team", "max", "ao-grind", "grind", "3"]) == 0
    assert _max(state) == {"grind": 3}


def test_a_raise_from_off_writes_the_techlead_seat_at_zero(world, tmp_path):  # noqa: F811
    """`scaling_names` starts with the techlead seat (#3296, TD-1592): a raise from `off` writes it at `0` beside
    the other lines, so it does not go back to its default ceiling."""
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())  # as `hunt_builds` left it
    doc["teams"]["ao-grind"]["techlead"] = {"name": "tl-ao"}
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    _, state = world
    assert cli.main(["team", "max", "ao-grind", "off"]) == 0
    assert cli.main(["team", "max", "ao-grind", "hunt", "3"]) == 0
    assert _max(state) == {"tl-ao": 0, "grind": 0, "hunt": 3}


def test_a_pool_seat_is_refused_in_its_words(world, tmp_path, capsys):  # noqa: F811
    """`max_refusal` names a pool (#3296, TD-1593): what `ao team max` and the dialog say."""
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["teams"]["ao-grind"]["seats"] = [
        {"name": "qa", "role": "fact-checker", "trigger": "asks", "pool": ["paul", "org-grind"]}
    ]
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    _, state = world
    assert cli.main(["team", "max", "ao-grind", "qa", "3"]) == 1
    assert "qa is a pool: a pool is a fallback, not capacity" in capsys.readouterr().err
    assert "teams" not in state
