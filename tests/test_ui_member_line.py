"""New session's **member line** fill + **keep as a team member** (design §4.5a, §4.9 *A member started from the
form*, TD-1167): under a Team pick, a Role one of the team's member lines names fills the form from that line as
`ao team start` creates its next member and starts a run-only member through `ao team add`'s road; ticked, the
line's size one higher; *run it under me instead* the person's own session in the team, as before."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from test_ui_teams import badged, client, world  # noqa: F401 — the fixtures, by name

from shiftlead import org as orgmod
from shiftlead import teamrun
from shiftlead.ui import app as uiapp

pytestmark = pytest.mark.unit

UI = Path(uiapp.__file__).parent
LEAD = "ao-shiftlead-dc-manager"  # the manager's id, as the plan names it
NOT_RUNNING = "dc-grind is not running: start it first"


def _dc_team(tmp_path, manager: dict | None = None) -> None:
    """dev-cadence's `dc-grinder` shape, defined in the repo's `.shiftlead.yml`: two lines of one role."""
    repo = tmp_path / "shiftlead"
    (repo / "docs" / "briefs").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "briefs" / "grinder-dc-1.md").write_text("You are a dc grinder; your manager is {manager}.\n")
    members = [
        {"role": "grinder", "name": "dc-grinder", "brief": "docs/briefs/grinder-dc-1.md", "profile": "paul",
         "lane": ["TD-7", "TD-9"]},
        {"role": "grinder", "name": "dc-hunter"},
    ]  # fmt: skip
    team = {"manager": manager or {"role": "manager", "name": "dc-manager"}, "members": members}
    (repo / ".shiftlead.yml").write_text(yaml.safe_dump({"teams": {"dc-grind": team}}))


def _running(fleet, *crew: str) -> None:
    fleet.sessions += [{**badged(LEAD, "dc-grind", "shiftlead", state="idle"), "name": "dc-manager"}]
    fleet.sessions += [{**badged(n, "dc-grind", "shiftlead", state="idle"), "id": f"ao-shiftlead-{n}"} for n in crew]


def _post(client, tmp_path, **over):  # noqa: F811
    data = {"name": "dc-grinder-2", "dir": str(tmp_path / "shiftlead"), "team": "dc-grind", "role": "grinder",
            "line": "dc-grinder", "unattended": "on", **over}  # fmt: skip
    return client.post("/new", data=data, follow_redirects=False)


def _option(html: str) -> str:
    return html.split('<option value="dc-grind"')[1].split(">")[0]


def test_the_team_pick_carries_its_member_lines_and_whether_it_runs(world, client):  # noqa: F811
    tmp_path, fleet = world
    _dc_team(tmp_path)
    opt = _option(client.get("/new").text)
    lines = json.loads(opt.split("data-lines='")[1].split("'")[0])
    assert lines == [{"line": "dc-grinder", "role": "grinder"}, {"line": "dc-hunter", "role": "grinder"}]
    assert f'data-notrunning="{NOT_RUNNING}"' in opt
    _running(fleet, "dc-grinder")
    assert 'data-notrunning=""' in _option(client.get("/new").text)
    # the template draws the line pick, the hidden `line` and the tick under Role
    html = client.get("/new").text
    assert '<input type="hidden" name="line" value="">' in html and 'id="linepick"' in html
    assert '<input type="checkbox" name="keep" id="keep"> keep as a team member' in html


def test_a_member_line_fills_the_form_as_its_next_member(world, client):  # noqa: F811
    tmp_path, fleet = world
    _dc_team(tmp_path)
    _running(fleet, "dc-grinder")
    got = client.get("/api/team_line", params={"team": "dc-grind", "line": "dc-grinder"}).json()
    assert (got["name"], got["profile"], got["lane"], got["why"], got["not_running"]) == (
        "dc-grinder-2", "paul", ["TD-7", "TD-9"], "", ""
    )  # fmt: skip
    assert f"You are a dc grinder; your manager is {LEAD}." in got["prompt"]
    # each line by its name: the other line of the role fills from itself
    other = client.get("/api/team_line", params={"team": "dc-grind", "line": "dc-hunter"}).json()
    assert other["name"] == "dc-hunter-2" and other["why"] == ""
    bad = client.get("/api/team_line", params={"team": "dc-grind", "line": "mill"}).json()
    assert "no member line 'mill'" in bad["why"]


def test_start_makes_a_run_only_member_from_the_line(world, client):  # noqa: F811
    tmp_path, fleet = world
    _dc_team(tmp_path)
    _running(fleet, "dc-grinder")
    got = client.get("/api/team_line", params={"team": "dc-grind", "line": "dc-grinder"}).json()
    r = _post(client, tmp_path, prompt=got["prompt"], lane="TD-7, TD-9", profile="paul")  # the fill, posted unedited
    assert r.status_code == 303 and r.headers["location"] == "/focus/ao-dc-grinder-2"
    (made,) = fleet.creates()
    assert made["name"] == "dc-grinder-2" and made["run_only"] is True
    assert (made["profile"], made["lane"], made["controllers"]) == ("paul", ["TD-7", "TD-9"], [LEAD])
    assert made["unattended"] is True and made["supervised"] is True and made["team"] == "dc-grind"
    assert made["prompt"] == got["prompt"] and made["prompt_from"], "the line's brief, its source kept"
    assert not [m for m, _ in fleet.calls if m == "set_settings"], "a run-only start writes no setting"


def test_what_the_person_typed_over_the_line_is_the_records_for_its_run(world, client):  # noqa: F811
    tmp_path, fleet = world
    _dc_team(tmp_path)
    _running(fleet, "dc-grinder")
    assert _post(client, tmp_path, name="dc-extra", prompt="just TD-9", lane="TD-9").status_code == 303
    (made,) = fleet.creates()
    assert (made["name"], made["prompt"], made["lane"], made["run_only"]) == ("dc-extra", "just TD-9", ["TD-9"], True)
    assert "prompt_from" not in made and made["worktree"] == "dc-extra"


def test_a_member_start_on_a_team_not_running_is_refused(world, client):  # noqa: F811
    tmp_path, fleet = world
    _dc_team(tmp_path)
    got = client.get("/api/team_line", params={"team": "dc-grind", "line": "dc-grinder"}).json()
    assert got["not_running"] == NOT_RUNNING and got["name"] == "dc-grinder-2", "filled, and Start refused"
    for keep in ("", "on"):
        r = _post(client, tmp_path, keep=keep)
        assert r.status_code == 400 and r.json()["detail"] == NOT_RUNNING
    assert not fleet.creates() and not [m for m, _ in fleet.calls if m == "set_settings"]
    # the page offers the team's Start in its place, and the kept start's locked note is the design's
    js = (UI / "static" / "app.js").read_text()
    assert 'id="memberteamstart">Start ${esc(team)}</button>' in js
    assert '"a kept member is the line\'s: change the line in the definition"' in js


def test_keep_as_a_team_member_is_the_lines_plus(world, client):  # noqa: F811
    tmp_path, fleet = world
    _dc_team(tmp_path)
    _running(fleet, "dc-grinder")
    assert _post(client, tmp_path, keep="on", name="ignored", prompt="ignored").status_code == 303
    assert [p["teams"] for m, p in fleet.calls if m == "set_settings"] == [{"dc-grind": {"size": {"dc-grinder": 2}}}]
    (made,) = fleet.creates()
    assert made["name"] == "dc-grinder-2" and "run_only" not in made, "a kept member, named from the line alone"
    assert "You are a dc grinder" in made["prompt"]


def test_a_team_a_person_leads_runs_while_any_crew_record_is_live(world, client):  # noqa: F811
    tmp_path, fleet = world
    _dc_team(tmp_path, manager={"role": orgmod.PERSON})
    got = client.get("/api/team_line", params={"team": "dc-grind", "line": "dc-hunter"}).json()
    assert got["not_running"] == NOT_RUNNING
    fleet.sessions.append({**badged("dc-grinder", "dc-grind", "shiftlead", state="idle"), "id": "ao-x"})
    got = client.get("/api/team_line", params={"team": "dc-grind", "line": "dc-hunter"}).json()
    assert got["not_running"] == "" and got["name"] == "dc-hunter-2"
    assert _post(client, tmp_path, line="dc-hunter", name="dc-hunter-2").status_code == 303
    (made,) = fleet.creates()
    assert made["controllers"] == [] and made["run_only"] is True, "no manager to tick"


def test_run_it_under_me_instead_is_the_persons_own_session_in_the_team(world, client):  # noqa: F811
    """No `unattended`: the form's *run it under me instead* — the person's session, `ao new --team`'s,
    which needs no running team; the line's brief and lane, as the fill left them, kept."""
    tmp_path, fleet = world
    _dc_team(tmp_path)
    r = _post(client, tmp_path, unattended="", prompt="the line's brief", lane="TD-7")
    assert r.status_code == 303
    (made,) = fleet.creates()
    assert made["unattended"] is False and "run_only" not in made and made["team"] == "dc-grind"
    assert (made["prompt"], made["lane"]) == ("the line's brief", ["TD-7"])


def test_next_members_reads_every_line_in_one_plan(world):  # noqa: F811
    tmp_path, fleet = world
    _dc_team(tmp_path)
    org, _ = uiapp.org_here()
    held = [{**badged("dc-hunter-2", "dc-grind"), "state": "idle"}]  # a live record holds the line's next name
    got = teamrun.next_members(org, "dc-grind", "kmaster", held)
    assert {k: v.name for k, v in got.items()} == {"dc-grinder": "dc-grinder-2", "dc-hunter": "dc-hunter-3"}
