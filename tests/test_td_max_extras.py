"""td-max's held extras written by a Start and by Apply's starts (design §4.9 *Scaling with the work*, TD-1545):
`ao team start` writes `max − size` extras per line and seat that may scale, each `create(held=True)` with the
launch record its line's next kept member gets and `scale: {line}`; a seat's extra carries `seat: {trigger: asks}`
alone. A name an extra already holds is left as it is, a live holder of the name is said, and a held extra is
never read as a member the definition dropped, nor counted on call by the rollup. The RPC is mocked as
`test_cli_teams.py` mocks it."""

from __future__ import annotations

import pytest
import yaml
from test_cli_teams import creates, org_doc, world  # noqa: F401 — the fixture, by name

from shiftlead import cli, teamrun, teams
from shiftlead.ui import org as ui_org

pytestmark = pytest.mark.unit


@pytest.fixture
def extras_on(monkeypatch):
    monkeypatch.setattr(teams, "_extras", teams.EXTRAS)  # conftest stubs it: put the real one back


def held(state):
    """The extras a start wrote: each create that asked `held` with a `scale`."""
    return {p["name"]: p for p in creates(state) if p.get("scale")}


def settings(tmp_path, teams_doc):
    (tmp_path / "home" / "settings.yml").write_text(yaml.safe_dump({"teams": teams_doc}))


def test_a_start_on_the_default_ceilings_writes_two_held_extras_per_line(world, extras_on, capsys):  # noqa: F811
    tmp_path, state = world
    assert cli.main(["team", "start", "ao-grind"]) == 0
    got = held(state)
    assert sorted(got) == ["grind-3", "grind-4", "hunt-2", "hunt-3"]
    grind = next(p for p in creates(state) if p["name"] == "grind-1")
    for name, p in got.items():
        line = "grind" if name.startswith("grind") else "hunt"
        assert p["held"] is True and p["scale"] == {"line": line}
        assert p["unattended"] is True and p["supervised"] is True and p["worktree"] == name
        assert p["controllers"] == ["ao-shiftlead-orc-ao"]  # the line's next kept member's
        assert "seat" not in p  # a worker line's extra is no seat
    # the launch record the line's kept member runs: its profile, lane and brief
    g3 = got["grind-3"]
    assert (g3["profile"], g3["lane"], g3["prompt"]) == (grind["profile"], grind["lane"], grind["prompt"])
    # the team's sessions come first, the extras after them
    names = [p["name"] for p in creates(state)]
    assert names.index("hunt") < names.index("grind-3")
    assert "grind-3, grind-4, hunt-2, hunt-3: written held as extras" in capsys.readouterr().out


def test_a_written_max_and_off_and_a_zero_set_the_extras(world, extras_on):  # noqa: F811
    tmp_path, state = world
    settings(tmp_path, {"ao-grind": {"max": {"grind": 3, "hunt": 0}}})
    assert cli.main(["team", "start", "ao-grind"]) == 0
    assert sorted(held(state)) == ["grind-3"]
    state["calls"].clear()
    state["sessions"].clear()
    settings(tmp_path, {"ao-grind": {"max": "off"}})
    assert cli.main(["team", "start", "ao-grind"]) == 0
    assert held(state) == {} and len(creates(state)) == 4  # the team alone


def test_a_seats_extra_carries_its_trigger_alone(world, extras_on):  # noqa: F811
    tmp_path, state = world
    doc = org_doc(tmp_path)
    doc["teams"]["ao-grind"]["techlead"] = {"name": "techlead-ao"}
    doc["teams"]["ao-grind"]["seats"] = [
        {"role": "fact-checker", "name": "ask-ao", "trigger": "asks"},
        {"role": "auditor", "name": "prs-ao", "trigger": {"prs": 3}},
    ]
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    settings(tmp_path, {"ao-grind": {"max": {"grind": 0, "hunt": 0}}})
    assert cli.main(["team", "start", "ao-grind"]) == 0
    got = held(state)
    # the techlead seat and the `asks` seat scale; a seat on `prs` is one pass over the repo
    assert sorted(got) == ["ask-ao-2", "ask-ao-3", "techlead-ao-2", "techlead-ao-3"]
    for p in got.values():
        assert p["seat"] == {"trigger": "asks"}  # no tags, no pool, no after
    seat = next(p for p in creates(state) if p["name"] == "techlead-ao")
    assert seat["seat"].get("tags") is True  # the seat itself stays the tagging candidate
    assert got["techlead-ao-2"]["prompt"] == seat["prompt"] and got["techlead-ao-2"]["role"] == "techlead"


def test_a_filled_extra_is_left_a_held_one_rewritten_and_a_live_holder_is_said(world, extras_on, capsys):  # noqa: F811
    tmp_path, state = world
    state["sessions"].append(
        {
            "id": "ao-shiftlead-grind-3",
            "name": "grind-3",
            "state": "idle",
            "team": "ao-grind",
            "scale": {"line": "grind"},
        }
    )
    state["sessions"].append(
        {
            "id": "ao-shiftlead-hunt-3",
            "name": "hunt-3",
            "state": "closed",
            "team": "ao-grind",
            "scale": {"line": "hunt"},
        }
    )
    state["verdicts"]["grind-4"] = {"name": "grind-4", "verdict": "live", "holder": "ao-shiftlead-grind-4"}
    for n in ("hunt-2", "hunt-3"):
        state["verdicts"][n] = {
            "name": n,
            "verdict": "supersede",
            "holder": f"ao-shiftlead-{n}",
            "holder_state": "closed",
        }
    assert cli.main(["team", "start", "ao-grind"]) == 0
    got = held(state)
    # grind-3 is filled and runs on; grind-4 is another's; the held hunt-3 is written again, so its launch record
    # is the line's now; a closed record's mail is the extra's, as a member's is
    assert sorted(got) == ["hunt-2", "hunt-3"]
    assert got["hunt-2"].get("keep_mail") is True and got["hunt-3"].get("keep_mail") is True
    assert "grind-4: not written as an extra of grind — ao-shiftlead-grind-4 holds the name" in capsys.readouterr().err


@pytest.fixture
def removes(world, monkeypatch):  # noqa: F811
    """`remove` on the mocked home: the record forgotten, as `rpc_remove` forgets a closed one."""
    tmp_path, state = world
    real = cli.call_sync

    def call(method, **params):
        if method != "remove":
            return real(method, **params)
        state["calls"].append((method, params))
        if (why := state.get("refuse", {}).get(params["id"])) is not None:
            raise cli.AgentError(why)
        state["sessions"][:] = [s for s in state["sessions"] if s["id"] != params["id"]]
        return None

    monkeypatch.setattr(cli, "call_sync", call)


def removed(state):
    return [p["id"] for m, p in state["calls"] if m == "remove"]


def extra(name, line, st="closed"):
    return {"id": f"ao-shiftlead-{name}", "name": name, "state": st, "team": "ao-grind", "scale": {"line": line}}


def test_a_start_removes_the_held_extras_a_lowered_max_or_a_removed_line_leaves(world, extras_on, removes, capsys):  # noqa: F811
    tmp_path, state = world
    settings(tmp_path, {"ao-grind": {"max": {"grind": 3, "hunt": 0}}})
    state["sessions"] += [extra("grind-3", "grind"), extra("grind-4", "grind"), extra("hunt-2", "hunt")]
    state["sessions"] += [extra("dig-2", "dig"), extra("hunt-3", "hunt", "idle")]
    assert cli.main(["team", "start", "ao-grind"]) == 0
    # past the lowered max, and the extra of a line the definition no longer has; the live one runs on
    assert removed(state) == ["ao-shiftlead-grind-4", "ao-shiftlead-hunt-2", "ao-shiftlead-dig-2"]
    assert sorted(held(state)) == ["grind-3"]
    err = capsys.readouterr().err
    assert "grind-4: the held extra of grind removed — the max no longer holds it" in err
    assert "hunt-3: a live extra of hunt the max no longer holds — left to its run" in err


def test_max_off_removes_every_held_extra_and_a_refused_removal_is_said(world, extras_on, removes, capsys):  # noqa: F811
    tmp_path, state = world
    settings(tmp_path, {"ao-grind": {"max": "off"}})
    state["sessions"] += [extra("grind-3", "grind"), extra("hunt-2", "hunt")]
    state["refuse"] = {"ao-shiftlead-hunt-2": "suspended"}
    assert cli.main(["team", "start", "ao-grind"]) == 0
    assert removed(state) == ["ao-shiftlead-grind-3", "ao-shiftlead-hunt-2"] and held(state) == {}
    assert "hunt-2: the held extra of hunt was not removed — suspended" in capsys.readouterr().err


def test_a_size_lowered_while_down_makes_the_record_past_it_an_extra(world, extras_on, removes):  # noqa: F811
    """A kept member's closed record past a size lowered while the team was down is no member the definition
    dropped: the Start supersedes it as the line's extra, its mail kept, and marks nothing sat out."""
    tmp_path, state = world
    assert cli.main(["team", "start", "ao-grind"]) == 0
    for s in state["sessions"]:
        s["state"] = "closed"
    kept = {"id": "ao-shiftlead-grind-3", "name": "grind-3", "state": "closed", "team": "ao-grind", "role": "grinder"}
    team = ("orc-ao", "grind-1", "grind-2", "hunt")  # the team's own records; the extras it wrote forgotten
    state["sessions"] = [s for s in state["sessions"] if s["name"] in team] + [kept]
    state["calls"].clear()
    state["verdicts"]["grind-3"] = {
        "name": "grind-3", "verdict": "supersede", "holder": "ao-shiftlead-grind-3", "holder_state": "closed"
    }  # fmt: skip
    doc = org_doc(tmp_path)
    assert doc["teams"]["ao-grind"]["members"][0]["count"] == 2  # the size the record was kept under: 3 → 2
    plan = teams.plan(orgmod_with_settings(tmp_path), "ao-grind", "kmaster")
    assert teamrun.renames(plan, state["sessions"]) == ([], [])  # no removal: the line scales
    assert cli.main(["team", "start", "ao-grind"]) == 0
    assert not [p for m, p in state["calls"] if m == "relaunch"]  # nothing sat out
    got = held(state)
    assert got["grind-3"]["scale"] == {"line": "grind"} and got["grind-3"].get("keep_mail") is True
    assert removed(state) == []


def test_a_refused_extra_is_said_and_the_start_stands(world, extras_on, monkeypatch, capsys):  # noqa: F811
    tmp_path, state = world
    real = cli.call_sync

    def refusing(method, **params):
        if method == "create" and params.get("scale"):
            raise cli.AgentError("no room")
        return real(method, **params)

    monkeypatch.setattr(cli, "call_sync", refusing)
    assert cli.main(["team", "start", "ao-grind"]) == 0
    assert "grind-3: the extra of grind was not written — no room" in capsys.readouterr().err


def test_a_held_extra_is_no_member_the_definition_dropped(world, extras_on):  # noqa: F811
    """`renames` reads a record the definition does not name as a rename or a removal: an extra is named by no
    definition line, so a Start or Apply would mark it sat out — it is passed over."""
    tmp_path, state = world
    assert cli.main(["team", "start", "ao-grind"]) == 0
    for s in state["sessions"]:
        if s["name"].startswith(("grind-3", "grind-4", "hunt-")):
            s["state"], s["scale"] = "closed", {"line": s["name"].rsplit("-", 1)[0]}
    org = orgmod_with_settings(tmp_path)
    plan = teams.plan(org, "ao-grind", "kmaster")
    assert teamrun.renames(plan, state["sessions"]) == ([], [])


def orgmod_with_settings(tmp_path):
    from shiftlead import org as orgmod

    return orgmod.with_home_settings(orgmod.load(tmp_path / "home" / "org.yml"))


def test_apply_starting_a_seat_writes_the_missing_extras(world, extras_on):  # noqa: F811
    tmp_path, state = world
    doc = org_doc(tmp_path)
    doc["teams"]["ao-grind"]["techlead"] = {"name": "techlead-ao"}
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    settings(tmp_path, {"ao-grind": {"max": "off"}})
    assert cli.main(["team", "start", "ao-grind"]) == 0
    assert held(state) == {}
    # the seat's record gone: Apply starts it (TD-399), and with it the extras the team now reads
    state["sessions"][:] = [s for s in state["sessions"] if s["name"] != "techlead-ao"]
    state["calls"].clear()
    settings(tmp_path, {"ao-grind": {"max": {"grind": 3, "hunt": 0, "techlead-ao": 0}}})
    out = teamrun.apply(cli.call_sync, orgmod_with_settings(tmp_path), "ao-grind", "kmaster")
    assert [r["act"] for r in out["applied"]] == ["start"]
    assert sorted(held(state)) == ["grind-3"] and out["extras"] == ["ao-shiftlead-grind-3"]


def test_the_rollup_never_counts_a_held_extra_on_call():
    seat = {"id": "a", "state": "closed", "seat": {"trigger": "asks"}}
    extra = {"id": "b", "state": "closed", "seat": {"trigger": "asks"}, "scale": {"line": "techlead-ao"}}
    live_extra = {"id": "c", "state": "idle", "seat": {"trigger": "asks"}, "scale": {"line": "techlead-ao"}}
    groups = [{"team": "ao-grind", "live": True, "members": [seat, extra, live_extra]}]
    assert [m["id"] for _, m in ui_org.rollup_counted(groups)] == ["a", "c"]


def test_an_attended_line_writes_no_extra_and_a_failed_read_is_said(world, extras_on, monkeypatch, capsys):  # noqa: F811
    tmp_path, state = world
    doc = org_doc(tmp_path)
    doc["teams"]["ao-grind"]["members"][1]["unattended"] = False
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    assert cli.main(["team", "start", "ao-grind"]) == 0
    assert sorted(held(state)) == ["grind-3", "grind-4"]  # a line a person watches is no tick's to fill
    state["calls"].clear()
    state["sessions"].clear()
    real = cli.call_sync

    def failing(method, **params):
        if method == "name_check" and params["name"] == "grind-3":
            raise cli.AgentError("home gone")
        return real(method, **params)

    monkeypatch.setattr(cli, "call_sync", failing)
    assert cli.main(["team", "start", "ao-grind"]) == 0  # the team started: the extras are said, never a failure
    assert held(state) == {}
    assert "no extras written — the home could not be read: home gone" in capsys.readouterr().err


def test_a_held_seat_extra_is_never_on_call():
    assert teamrun.on_call({"seat": {"trigger": "asks"}, "state": "closed"})
    assert not teamrun.on_call({"seat": {"trigger": "asks"}, "state": "closed", "scale": {"line": "tl"}})
