"""td-max as the person sees it (design §4.9 *What the person sees*, §4.5a team card **td-max**; TD-1548): the
header's mark, each scaling line or seat as its range, extras and newest fill or stop on the card's members
line, the Members dialog and `ao team list`, and a live extra's *extra k of n* badge."""

from __future__ import annotations

from datetime import datetime

import pytest

from shiftlead import org as orgmod
from shiftlead import teamrun

pytestmark = pytest.mark.unit

TODAY = datetime.now().astimezone().replace(hour=14, minute=2, second=0, microsecond=0)


def _team(**kw) -> orgmod.TeamDef:
    return orgmod.TeamDef(
        name="ao-grind",
        manager=orgmod.ManagerDef(role="manager", name="manager-ao-1"),
        members=[orgmod.MemberDef(role="grinder", name="grinder-ao", count=3)],
        techlead=orgmod.TechleadDef(name="techlead-ao-1"),
        seats=[orgmod.SeatDef(name="audit-ao-1", role="auditor", trigger="prs", after="10")],
        **kw,
    )


def _rec(name: str, state: str = "working", line: str = "", last: dict | None = None, **kw) -> dict:
    scale = {"line": line, **({"last": last} if last else {})} if line else None
    return {"id": f"ao-{name}", "name": name, "team": "ao-grind", "state": state, "scale": scale, **kw}


def _fleet() -> list[dict]:
    fill = {"at": TODAY.isoformat(), "did": "fill", "why": "4 pickable, every grinder claimed"}
    return [
        *(_rec(f"grinder-ao-{k}") for k in (1, 2, 3)),
        _rec("grinder-ao-4", line="grinder-ao", last=fill),
        _rec("grinder-ao-5", "closed", line="grinder-ao"),  # held: counted in n, never live
        _rec("grinder-ao-6", "closed", line="grinder-ao"),
        _rec("techlead-ao-1"),
        _rec("techlead-ao-1-2", "idle", line="techlead-ao-1"),
        _rec("techlead-ao-1-3", "idle", line="techlead-ao-1"),
    ]


def test_each_scaling_line_reads_its_range_extras_and_newest_fill():
    lines = {x["name"]: x for x in teamrun.scale_lines(_team(max={"grinder-ao": 6}), _fleet())}
    assert list(lines) == ["techlead-ao-1", "grinder-ao"]  # the definition's order; the prs seat may not scale
    assert lines["grinder-ao"]["range"] == "grinder-ao 3–6 +1"
    assert lines["grinder-ao"]["last"] == "+1 at 14:02: 4 pickable, every grinder claimed"
    assert lines["techlead-ao-1"]["range"] == "techlead-ao-1 1–3 +2 idle"  # a seat's open idle extras said idle
    assert lines["techlead-ao-1"]["last"] == ""


def test_a_stop_reads_plus_zero_and_the_newest_fill_or_stop_wins():
    old = {"at": "2026-01-01T09:00:00Z", "did": "fill", "why": "old"}
    stop = {"at": TODAY.isoformat(), "did": "stopped", "why": "host full, 30 live"}
    hold = {"at": TODAY.replace(hour=15).isoformat(), "did": "hold", "why": "back to held: out of work"}
    fleet = [
        _rec("grinder-ao-4", "closed", line="grinder-ao", last=old),
        _rec("grinder-ao-5", "closed", line="grinder-ao", last=stop),
    ]
    fleet.append(_rec("grinder-ao-6", "closed", line="grinder-ao", last=hold))  # a hold is not drawn
    (g,) = [x for x in teamrun.scale_lines(_team(max={"grinder-ao": 6}), fleet) if x["name"] == "grinder-ao"]
    assert g["range"] == "grinder-ao 3–6" and g["last"] == "+0: host full, 30 live"
    assert teamrun.scale_last_words({"did": "unstuck", "why": "x"}) == ""


def test_a_line_stored_at_zero_is_plain_and_off_carries_no_mark():
    team = _team(max={"grinder-ao": 0, "techlead-ao-1": 0})
    assert teamrun.scale_lines(team, _fleet()) == [] and not teamrun.td_max_on(team)
    assert not teamrun.td_max_on(_team(max="off"))
    assert teamrun.td_max_on(_team()) and teamrun.td_max_on(_team(max={"grinder-ao": 6, "techlead-ao-1": 0}))


def test_a_live_extra_badge_reads_its_place_among_the_lines_extras():
    fleet = _fleet()
    assert teamrun.extra_badge(fleet[3], fleet) == "extra 1 of 3"
    assert teamrun.extra_badge(fleet[8], fleet) == "extra 2 of 2"
    assert teamrun.extra_badge(fleet[0], fleet) == ""  # a member the size keeps


def test_the_card_badge_rows_and_header_draw_it():
    from shiftlead.ui.app import team_groups, templates
    from shiftlead.ui.cards import view

    fleet = [{**r, "unattended": True, "role": "grinder"} for r in _fleet()]
    card = view(fleet[3], fleet)
    assert card["role_label"].endswith("· extra 1 of 3")
    assert "extra" not in view(fleet[4], fleet)["role_label"]  # a held extra draws no badge (and no card)
    org = orgmod.Org(teams={"ao-grind": _team(max={"grinder-ao": 6})})
    (row,) = teamrun.rows(org, fleet)
    assert row["td_max"] and [x["range"] for x in row["scaling"]] == ["techlead-ao-1 1–3 +2 idle", "grinder-ao 3–6 +1"]

    def v(r):
        return {**view(r, fleet), "controllers": [], "capabilities": []}

    groups = team_groups([v(r) for r in fleet if r["state"] != "closed"], [row])
    (g,) = [x for x in groups if x["team"] == "ao-grind"]
    head = templates.get_template("group_head.html").render(g=g, help_title=lambda k: k)
    assert ">td-max</span>" in head
    assert "grinder-ao 3–6 +1 · +1 at 14:02: 4 pickable, every grinder claimed</div>" in head
    assert "techlead-ao-1 1–3 +2 idle</div>" in head


def test_the_members_dialog_reads_the_range_beside_up_to():
    org = orgmod.Org(teams={"ao-grind": _team(max={"grinder-ao": 6})})
    v = teamrun.members_view(org, "ao-grind", _fleet())
    (m,) = v["members"]
    assert m["up_to"]["range"] == "grinder-ao 3–6 +1" and m["up_to"]["last"].startswith("+1 at 14:02")
    assert v["techlead"]["up_to"]["range"] == "techlead-ao-1 1–3 +2 idle"
    assert "range" not in v["seats"][0]["up_to"]  # may not scale: no range


def test_ao_team_list_says_each_scaling_line_on_a_live_team(monkeypatch, capsys):
    from shiftlead import cli

    fleet = [{**r, "unattended": True} for r in _fleet()]
    org = orgmod.Org(teams={"ao-grind": _team(max={"grinder-ao": 6})})
    monkeypatch.setattr(cli, "_org_here", lambda: org)
    monkeypatch.setattr(cli, "call_sync", lambda m, **kw: fleet if m == "list" else {})
    monkeypatch.setattr(teamrun, "waiting_of_home", lambda call: {})
    monkeypatch.setattr(teamrun, "flow_view", lambda *a, **kw: {})
    assert cli.main(["team", "list"]) == 0
    out = capsys.readouterr().out
    said = "td-max: techlead-ao-1 1–3 +2 idle; grinder-ao 3–6 +1 (+1 at 14:02: 4 pickable, every grinder claimed)"
    assert said in out
