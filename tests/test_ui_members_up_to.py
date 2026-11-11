"""The Members dialog's **up to** (design §4.5a *Members dialog* **up to**, §4.9 *Scaling with the work*, td-max,
TD-1545): a number field on each member line and each seat that may scale — the line's ceiling, the default's where
none is written, blank on a team at `off`, `0` on one stored at `0` — drawn disabled with its reason where it may
not scale; a number writes `teams.<team>.max.<line>` through `teamrun.set_max`, and a lowered one's confirm names
each live extra it winds down."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
import yaml
from conftest import scratch_dir
from test_ui_members_size import LEAD, UI, _node, _set
from test_ui_teams import badged, client, org_doc, world  # noqa: F401 — the fixtures, by name

pytestmark = pytest.mark.unit


def _seated(tmp_path):
    doc = org_doc(tmp_path)
    doc["teams"]["ao-grind"].update(
        techlead={"name": "tl-ao"},
        seats=[
            {"role": "fact-checker", "name": "fc-ao", "trigger": "asks"},
            {"role": "sweeper", "name": "sw-ao", "trigger": {"swept": "7d"}},
        ],
    )
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))


def _max(client, line, n):  # noqa: F811
    return client.post("/api/teams/ao-grind/members", json={"action": "max", "line": line, "n": n})


def test_each_line_and_seat_reads_its_ceiling_and_why_it_may_not_scale(world, client):  # noqa: F811
    tmp_path, fleet = world
    _seated(tmp_path)
    v = client.get("/api/teams/ao-grind/members").json()
    (e,) = v["members"]
    # no max key: the default ceilings, a line's size + 2 and a seat's 3
    assert (e["up_to"]["value"], e["up_to"]["default"], e["up_to"]["why"]) == (4, True, "")
    assert [x["name"] for x in e["up_to"]["extras"]] == ["grind-3", "grind-4"]
    assert (v["techlead"]["up_to"]["value"], v["techlead"]["up_to"]["default"]) == (3, True)
    assert v["manager"]["up_to"]["why"] == "one lead per team" and v["manager"]["up_to"]["value"] is None
    fc, sw = v["seats"]
    assert (fc["name"], fc["trigger"], fc["up_to"]["value"]) == ("fc-ao", "asks", 3)
    assert [x["name"] for x in fc["up_to"]["extras"]] == ["fc-ao-2", "fc-ao-3"]
    assert (sw["up_to"]["why"], sw["up_to"]["value"], sw["up_to"]["extras"]) == ("one pass covers the repo", None, [])
    # a written ceiling, one stored at 0, and the team at off (blank, no extras)
    (tmp_path / "home" / "settings.yml").write_text("teams: {ao-grind: {max: {grind: 5, tl-ao: 0}}}\n")
    v = client.get("/api/teams/ao-grind/members").json()
    assert (v["members"][0]["up_to"]["value"], v["members"][0]["up_to"]["default"]) == (5, False)
    assert (v["techlead"]["up_to"]["value"], v["techlead"]["up_to"]["extras"]) == (0, [])
    assert v["seats"][0]["up_to"]["value"] == 3  # a seat with no key of its own keeps its default
    (tmp_path / "home" / "settings.yml").write_text("teams: {ao-grind: {max: off}}\n")
    v = client.get("/api/teams/ao-grind/members").json()
    assert v["members"][0]["up_to"]["value"] is None and v["members"][0]["up_to"]["extras"] == []


def test_a_number_writes_the_setting_and_a_refused_one_says_why(world, client):  # noqa: F811
    tmp_path, fleet = world
    _seated(tmp_path)
    defs = (tmp_path / "home" / "org.yml").read_bytes()
    r = _max(client, "grind", 5)
    assert r.status_code == 200 and r.json()["text"] == "grind: up to 5", r.text
    r = _max(client, "fc-ao", 1)  # at or below the seat's size: stored as 0
    assert r.status_code == 200 and r.json()["text"] == "fc-ao: no scaling — 1 is at or below its size 1"
    assert _set(fleet) == [{"ao-grind": {"max": {"grind": 5}}}, {"ao-grind": {"max": {"fc-ao": 0}}}]
    fleet.calls.clear()
    assert _max(client, "orc-ao", 3).json()["detail"] == "orc-ao is the manager: one lead per team"
    assert _max(client, "sw-ao", 3).json()["detail"] == "sw-ao is on swept: one pass covers the repo"
    for bad in ("4", 2.5, True, None):
        assert _max(client, "grind", bad).status_code == 400
    assert _max(client, "grind", -1).status_code == 400
    assert _set(fleet) == []  # refused before anything is written
    assert (tmp_path / "home" / "org.yml").read_bytes() == defs  # writes no definition


def test_the_field_and_a_lowered_ones_confirm_name_the_live_extras(world, client):  # noqa: F811
    tmp_path, fleet = world
    _seated(tmp_path)
    fleet.sessions = [
        {**badged(f"ao-shiftlead-{n}", "ao-grind"), "name": n} | {"controllers": [] if n == "orc-ao" else [LEAD]}
        for n in ("orc-ao", "grind-1", "grind-2", "grind-3")
    ] + [{**badged("ao-shiftlead-grind-4", "ao-grind", state="closed"), "name": "grind-4", "scale": {"line": "grind"}}]
    fleet.sessions[3]["scale"] = {"line": "grind"}
    v = client.get("/api/teams/ao-grind/members").json()
    e = v["members"][0]
    got = _node([{"team": "ao-grind", "e": e, "v": v}])[0]
    assert 'data-mupto="grind" value="4"' in got["row"] and "the default ceiling, its size + 2" in got["row"]
    # the manager's and the swept seat's fields are disabled with their reason, through the same helper
    probe = """
const fs = require("fs"); const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
global.window = {}; global.document = { documentElement: el(), body: el(), addEventListener: noop, createElement: el,
  querySelector: () => null, querySelectorAll: () => [] };
global.localStorage = { getItem: () => null, setItem: noop }; global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" }; global.fetch = () => Promise.reject(new Error("x"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO; const v = JSON.parse(fs.readFileSync(process.argv[3], "utf8")); const u = v.members[0].up_to;
console.log(JSON.stringify({
  manager: AO.membersUpTo(v.manager.name, v.manager.up_to), swept: AO.membersUpTo(v.seats[1].name, v.seats[1].up_to),
  down3: AO.membersMaxConfirm("grind", u, 3, "ao-grind", v.live),
  down2: AO.membersMaxConfirm("grind", u, 2, "ao-grind", v.live),
  up: AO.membersMaxConfirm("grind", u, 6, "ao-grind", v.live),
  stopped: AO.membersMaxConfirm("grind", u, 2, "ao-grind", false),
}));
"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    d = scratch_dir()
    (d / "probe.js").write_text(probe)
    (d / "v.json").write_text(json.dumps(v))
    out = subprocess.run(
        [node, str(d / "probe.js"), str(UI / "static" / "app.js"), str(d / "v.json")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    w = json.loads(out.stdout)
    assert 'disabled title="one lead per team"' in w["manager"] and 'value=""' in w["manager"]
    assert 'disabled title="one pass covers the repo"' in w["swept"]
    # grind-3 is the live extra, grind-4 held: 3 keeps grind-3; 2 (at the size, stored 0) winds it down
    assert w["down3"] == ""
    assert w["down2"] == (
        "ao-grind: grind up to 2? It winds down grind-3 — Wrap up's prompt, never a kill; its record is dropped"
        " once it closes."
    )
    assert w["up"] == "" and w["stopped"] == ""
