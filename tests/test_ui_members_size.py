"""The Members dialog's **− / +** (design §4.9 *A team's size*, §4.5a *Members dialog* **− / +** and *Members… on
a repo-defined team*, TD-1165): a line's size, a setting, on every team a repo's included — the dialog opens on
a repo-defined team with Add member and Remove disabled and its − / + live, and no definition byte changes."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import scratch_dir
from test_ui_teams import _flow_org, _head, badged, client, world  # noqa: F401 — the fixtures, by name

from shiftlead.ui import app as uiapp

pytestmark = pytest.mark.unit

UI = Path(uiapp.__file__).parent
LEAD = "ao-shiftlead-orc-ao"  # the manager's id, as the plan names it


def _repo_team(tmp_path) -> Path:
    f = tmp_path / "shiftlead" / ".shiftlead.yml"
    f.write_text(
        yaml.safe_dump(
            {"teams": {"repo-grind": {"manager": {"role": "manager", "name": "rm"}, "members": [{"role": "grinder"}]}}}
        )
    )
    return f


def _size(client, team, line, step):  # noqa: F811
    return client.post(f"/api/teams/{team}/members", json={"action": "size", "line": line, "step": step})


def _set(fleet) -> list[dict]:
    return [p["teams"] for m, p in fleet.calls if m == "set_settings"]


def test_the_dialog_opens_on_a_repo_defined_team_with_add_and_remove_disabled(world, client):  # noqa: F811
    tmp_path, fleet = world
    _repo_team(tmp_path)
    head = _head(client.get("/").text, "repo-grind")
    defline = head[head.index('<div class="defline"><b>Definition</b>') :]
    assert 'data-members="repo-grind"' in defline  # pressable now; its Add member and Remove are not
    assert "defined in shiftlead&#39;s .shiftlead.yml — changed by PR" in defline
    v = client.get("/api/teams/repo-grind/members").json()
    assert not v["editable"] and v["note"] == "defined in shiftlead's .shiftlead.yml — changed by PR"
    assert v["source"].endswith("shiftlead/.shiftlead.yml") and "open_file" in v
    (e,) = v["members"]
    assert (e["size"], e["count"], e["words"], e["next_start"]) == (1, 1, "1", False)
    # Add member and Remove stay refused on a repo's file, whatever reaches the route
    r = client.post("/api/teams/repo-grind/members", json={"action": "add", "role": "grinder", "name": "g2"})
    assert r.status_code == 400 and "changed by PR" in r.json()["detail"]
    # an org-file team has no Open file in the dialog: its Add member and Remove are live
    assert client.get("/api/teams/ao-grind/members").json()["open_file"] is None


def test_plus_on_a_stopped_team_writes_the_setting_and_says_from_the_next_start(world, client):  # noqa: F811
    tmp_path, fleet = world
    defs = {p: p.read_bytes() for p in (tmp_path / "home" / "org.yml", _repo_team(tmp_path))}
    r = _size(client, "ao-grind", "grind", 1)
    assert r.status_code == 200 and r.json()["text"] == "grind: 3 (file says 2) · from the next Start"
    r = _size(client, "repo-grind", "grinder", 1)  # a repo's team: the setting, never its file
    assert r.status_code == 200 and r.json()["text"] == "grinder: 2 (file says 1) · from the next Start"
    assert _set(fleet) == [{"ao-grind": {"size": {"grind": 3}}}, {"repo-grind": {"size": {"grinder": 2}}}]
    assert not [m for m, _ in fleet.calls if m in ("create", "relaunch")]
    assert all(p.read_bytes() == b for p, b in defs.items())  # no definition byte changed
    # what the setting holds is what the row reads: *3 (file says 2)* and *· from the next Start*
    (tmp_path / "home" / "settings.yml").write_text("teams: {ao-grind: {size: {grind: 3}}}\n")
    (e,) = client.get("/api/teams/ao-grind/members").json()["members"]
    assert (e["size"], e["count"], e["words"], e["next_start"], e["down"]) == (3, 2, "3 (file says 2)", True, "")
    assert [s["name"] for s in e["sessions"]] == ["grind-1", "grind-2", "grind-3"]


def _live(fleet, *names):
    fleet.sessions = [
        {**badged(f"ao-shiftlead-{n}", "ao-grind"), "name": n} | {"controllers": [] if n == "orc-ao" else [LEAD]}
        for n in ("orc-ao", *names)
    ]


def test_plus_and_minus_on_a_live_team_create_and_wind_down_one_member(world, client):  # noqa: F811
    tmp_path, fleet = world
    org_yml = (tmp_path / "home" / "org.yml").read_bytes()
    _live(fleet, "grind-1", "grind-2")
    (e,) = client.get("/api/teams/ao-grind/members").json()["members"]
    assert e["down"] == "grind-2" and not e["next_start"]  # −'s confirm names it
    r = _size(client, "ao-grind", "grind", 1)
    assert r.status_code == 200, r.text
    (made,) = [p for m, p in fleet.calls if m == "create"]
    assert made["name"] == "grind-3" and made["controllers"] == [LEAD]
    assert f"started grind-3 under {LEAD}" in r.json()["text"]
    fleet.calls.clear()
    r = _size(client, "ao-grind", "grind", -1)  # no size written yet in this fake: 2 → 1
    assert r.status_code == 200, r.text
    assert [p for m, p in fleet.calls if m == "relaunch"] == [
        {"id": "ao-shiftlead-grind-2", "sit_out": True, "dropped": True}
    ]
    assert "grind-2 is wound down by the home" in r.json()["text"]
    assert _set(fleet) == [{"ao-grind": {"size": {"grind": 1}}}]
    assert (tmp_path / "home" / "org.yml").read_bytes() == org_yml


def test_minus_is_refused_at_zero_and_at_a_listed_flows_need_with_its_words(world, client):  # noqa: F811
    tmp_path, fleet = world
    (tmp_path / "home" / "settings.yml").write_text("teams: {ao-grind: {size: {grind: 0}}}\n")
    (e,) = client.get("/api/teams/ao-grind/members").json()["members"]
    assert (e["size"], e["words"], e["sessions"]) == (0, "0 (file says 2)", [])
    r = _size(client, "ao-grind", "grind", -1)
    assert r.status_code == 400 and "a size is a whole number of sessions, 0 or more, not -1" in r.json()["detail"]
    (tmp_path / "home" / "settings.yml").write_text("teams: {ao-grind: {size: {grind: 1}}}\n")
    _flow_org(tmp_path, ["build-review"])
    r = _size(client, "ao-grind", "grind", -1)
    assert (
        r.status_code == 400
        and r.json()["detail"] == "build-review needs a grinder: drop build-review from flows: first"
    )
    assert _set(fleet) == []  # refused before anything is written
    assert _size(client, "ao-grind", "nope", 1).json()["detail"].startswith("team ao-grind has no member line 'nope'")
    assert _size(client, "ao-grind", "grind", 2).status_code == 400  # one step at a time


PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
global.window = {};
global.document = { documentElement: el(), body: el(), addEventListener: noop, createElement: el,
  querySelector: () => null, querySelectorAll: () => [] };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const c = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
console.log(JSON.stringify(c.map((x) => ({
  size: AO.membersSizeConfirm(x.e, x.team), remove: AO.membersConfirm(x.e, x.team), row: AO.membersRow(x.e, x.v),
}))));
"""


def _node(cases: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the dialog's words are JavaScript, and nothing else runs them")
    d = scratch_dir()
    (d / "probe.js").write_text(PROBE)
    (d / "cases.json").write_text(json.dumps(cases))
    out = subprocess.run(
        [node, str(d / "probe.js"), str(UI / "static" / "app.js"), str(d / "cases.json")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_rows_words_and_minuses_confirm(world, client):  # noqa: F811
    tmp_path, fleet = world
    _live(fleet, "grind-1", "grind-2")
    live = client.get("/api/teams/ao-grind/members").json()
    _repo_team(tmp_path)
    (tmp_path / "home" / "settings.yml").write_text("teams: {repo-grind: {size: {grinder: 2}}}\n")
    repo = client.get("/api/teams/repo-grind/members").json()
    got = _node(
        [
            {"team": "ao-grind", "e": live["members"][0], "v": live},
            {"team": "repo-grind", "e": repo["members"][0], "v": repo},
        ]
    )
    assert got[0]["size"] == (
        "ao-grind: grind 2 → 1? It winds down grind-2 — Wrap up's prompt, never a kill; its card stays until Forget."
    )
    assert got[0]["remove"] == (
        "Remove from ao-grind? It edits org.yml (removes the grind line) and winds down grind-1, grind-2 — Wrap up's"
        " prompt, never a kill; each card stays until Forget."
    )
    assert '<span class="msize">2</span>' in got[0]["row"] and "from the next Start" not in got[0]["row"]
    assert 'data-mremove="0">Remove</button>' in got[0]["row"]  # an org team's Remove is live
    # a stopped repo team: no confirm on −, *2 (file says 1)* and *· from the next Start*, Remove disabled
    assert got[1]["size"] == ""
    assert '<span class="msize">2 (file says 1)</span>' in got[1]["row"]
    assert "· from the next Start" in got[1]["row"]
    assert 'data-mremove="0" disabled title="defined in shiftlead' in got[1]["row"]
