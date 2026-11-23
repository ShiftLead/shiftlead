"""The Flows page's read, check and routes (design §4.9c *The Flows page*, §4.5a, TD-2054)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
import yaml

from shiftlead import flow3, flow_save, flowdefs
from shiftlead.ui import app as app_mod

pytestmark = pytest.mark.unit

FLOW = {
    "format": 3,
    "name": "mine",
    "stages": [
        {"name": "Build", "does": "build", "model": "opus", "takes": "any", "work-pushed": "review"},
        {
            "name": "Review",
            "does": "review",
            "model": "sonnet",
            "ship": {"to": "merge", "refused": {"to": "build", "limit": 3}},
            "changes-wanted": {"to": "build", "limit": 3},
        },
    ],
}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    monkeypatch.setattr(flow3, "model_families", lambda: ("opus", "sonnet", "fable"))
    return tmp_path


def test_the_text_the_check_returns_saves_and_passes_the_files_check(home):
    got = flow_save.checked("mine", FLOW)
    assert got["problems"] == []
    assert yaml.safe_load(got["text"]) == FLOW
    assert "ship: {to: merge, refused: {to: build, limit: 3}}" in got["text"]
    flow_save.save("mine", got["text"])
    assert flow3.check_file(home / "flows" / "mine" / "flow.yml").usable


def test_a_flow_that_fails_is_refused_with_the_checks_words(home):
    doc = json.loads(json.dumps(FLOW))
    doc["stages"][1]["changes-wanted"] = "build"
    doc["stages"][0]["work-pushed"] = "review"
    doc["stages"][1]["ship"] = "build"
    got = flow_save.checked("mine", doc)
    assert any("no limit" in p for p in got["problems"])
    with pytest.raises(flow_save.FlowError, match="no limit"):
        flow_save.save("mine", got["text"])


@pytest.mark.parametrize("name", ["build-review", "../out", ""])
def test_a_builtin_or_bad_name_is_a_problem_before_save(home, name):
    assert flow_save.checked(name, {**FLOW, "name": name})["problems"]


def test_a_new_flow_on_a_taken_name_is_a_problem_and_its_own_version_is_not(home):
    got = flow_save.save("mine", flow_save.checked("mine", FLOW)["text"])
    assert any("already exists" in p for p in flow_save.checked("mine", FLOW)["problems"])
    assert flow_save.checked("mine", FLOW, got["version"])["problems"] == []


def test_the_listing_marks_builtins_own_and_a_first_shape_flow_read_only(home):
    flow_save.save("mine", flow_save.checked("mine", FLOW)["text"])
    old = home / "flows" / "older"
    old.mkdir()
    (old / "flow.yml").write_text("stages:\n- name: build\n  role: grinder\n")
    got = flow_save.listing([])
    rows = {r["name"]: r for r in got["flows"]}
    assert [r["name"] for r in got["flows"] if r["place"] == "builtin"] == list(flow3.BUILTIN)
    assert all(rows[n]["doc"] for n in flow3.BUILTIN)
    assert rows["mine"]["place"] == "own" and rows["mine"]["version"] and rows["mine"]["doc"]["name"] == "mine"
    assert rows["older"]["doc"] is None
    assert got["models"] == ["opus", "sonnet", "fable"]
    assert [b["name"] for b in got["briefs"]["audit"]] == ["docs", "tests", "code"]


def test_a_repos_flow_is_listed_as_the_repos(home, tmp_path):
    repo = tmp_path / "repo"
    d = repo / ".shiftlead" / "flows" / "theirs"
    d.mkdir(parents=True)
    (d / "flow.yml").write_text(flow_save.render({**FLOW, "name": "theirs"}))
    row = next(r for r in flow_save.listing([repo])["flows"] if r["name"] == "theirs")
    assert row["place"] == "repo" and row["repo"] == "repo" and "version" not in row


def test_a_saved_format3_flow_cannot_be_run_by_a_team_before_the_cut_over(home):
    flow_save.save("mine", flow_save.checked("mine", FLOW)["text"])
    flow = flowdefs.find("mine")
    assert flow is not None and any("no team runs until the cut-over" in p for p in flow.problems)


def test_the_flows_reads_are_the_homes():
    from sessionorc import modes

    assert {"flows", "flow_check"} <= modes.HOME_READS


def test_the_page_carries_its_read_and_the_rail_marks_it(home, monkeypatch):
    from fastapi.testclient import TestClient

    seen = {}

    async def call(method, **params):
        seen[method] = params
        if method == "flows":
            return flow_save.listing([])
        return {"name": "mine", "version": "v2", "moved": 0} if method == "flow_save" else {}

    monkeypatch.setattr(app_mod, "agent_call", call)
    with TestClient(app_mod.create_app()) as c:
        text = c.get("/flows").text
        c.post("/api/flows/save", json={"name": "mine", "text": "t", "version": "v1", "renames": {"a": "b"}})
    assert '<a href="/flows" class="on"' in text and "/static/flows.js" in text
    data = json.loads(re.search(r'id="flowsdata">(.*?)</script>', text, re.S).group(1))
    assert [r["name"] for r in data["flows"]] == list(flow3.BUILTIN)
    assert seen["flow_save"] == {"name": "mine", "text": "t", "version": "v1", "renames": {"a": "b"}, "delete": False}


def test_the_page_keeps_off_the_session_press_handler():
    """`app.js` posts every `data-act` press on any page to `/api/sessions/<id>/<act>`, so this page's controls carry
    an attribute of their own: a press here must never reach a session's action."""
    js = (app_mod.Path(app_mod.__file__).parent / "static" / "flows.js").read_text(encoding="utf-8")
    assert "data-act" not in js and "data-fl=" in js


# `flows.js` run as itself under node over a small fake DOM, its check answered as the host agent would: what a person
# does across several presses, which no read of the page's server half can reach.
FLOWS_DRIVE = r"""
const fs = require("fs");
const els = {};
const el = (id) => els[id] || (els[id] = { id, innerHTML: "", textContent: "", hidden: false, dataset: {}, on: {},
  addEventListener(t, f) { this.on[t] = f; } });
const row = (name, doc) => ({ name, place: "own", version: "v1", text: `saved ${name}`, problems: [], info: [], doc });
const stage = (name, does, to) => ({ name, does, model: "opus", ...(does === "build" ? { takes: "any", "work-pushed": to } : { ship: to }) });
const mine = () => ({ format: 3, stages: [stage("Build", "build", "review"), stage("Review", "review", "merge")] });
el("flowsdata").textContent = JSON.stringify({ flows: [row("one", { name: "one", ...mine() }), row("two", { name: "two", ...mine() })], models: ["opus"], briefs: {} });
global.document = { getElementById: el };
const posts = [];
let held = null;
global.fetch = async (path, o) => {
  const body = JSON.parse(o.body);
  posts.push([path, body]);
  if (held && path === "/api/flows/check") await held;
  const cap = body.doc && body.doc["max-moves"];
  const reply = path === "/api/flows/check" ? { problems: cap === 1 ? ["the cap is too low"] : [], info: [], text: `text cap ${cap}` } : { version: "v2" };
  return { ok: true, json: async () => reply };
};
eval(fs.readFileSync(process.argv[2], "utf8"));
const page = el("flowspage"), main = el("flmain"), list = el("fllist");
const settle = () => new Promise((r) => setTimeout(r, 260));
const press = (dataset) => page.on.click({ target: { closest: (q) => (q === "[data-fl]" ? { dataset, tagName: "BUTTON" } : null), tagName: "BUTTON" } });
const change = (dataset, value) => page.on.change({ target: { closest: () => ({ dataset, value, tagName: "INPUT" }) } });
const pick = (name) => press({ fl: "pick", id: `own//${name}` });
const saveOff = () => /id="flsave"[^>]* disabled/.test(main.innerHTML);
const out = {};
(async () => {
  await settle();
  // an edit, away and back: Save waits on a check of the edit, and writes what that check returned
  change({ fl: "maxm" }, "9"); await settle();
  pick("two"); await settle();
  let open; held = new Promise((r) => { open = r; });
  pick("one");
  out.save_off_on_return = saveOff();
  await settle();
  out.save_off_while_asked = saveOff();
  open(); held = null; await settle();
  out.save_on_after = !saveOff();
  press({ fl: "save" }); await settle();
  out.saved = posts.filter((p) => p[0] === "/api/flows/save").map((p) => p[1].text);
  // a failing edit, away and back: Save stays off, and the list's dot follows the check
  change({ fl: "maxm" }, "1"); await settle();
  out.dot = list.innerHTML.includes('class="dot"');
  pick("two"); await settle(); pick("one"); await settle();
  out.save_off_failing = saveOff();
  change({ fl: "maxm" }, "9"); await settle();
  out.dot_gone = !list.innerHTML.includes('class="dot"');
  // a rename onto another stage's name changes nothing, and says why
  change({ fl: "sname", si: "0" }, "Review"); await settle();
  out.renamed = main.innerHTML.includes('id="sn-0"') && main.innerHTML.includes('value="Build"');
  out.said = el("flowsaid").textContent;
  press({ fl: "tab", k: "file" });
  press({ fl: "tab", k: "stages" });
  // a walk ends with any edit: its stage may be the one removed
  press({ fl: "tab", k: "walk" });
  press({ fl: "wstart", k: "other" });
  press({ fl: "wout", o: "work-pushed" });
  press({ fl: "tab", k: "stages" });
  press({ fl: "delstage", si: "1" }); await settle();
  press({ fl: "tab", k: "walk" });
  out.walk_fresh = main.innerHTML.includes("Pick a kind of entry");
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""  # noqa: E501


def test_the_page_across_presses_saves_what_it_shows_and_keeps_a_flows_wiring(tmp_path):
    """§4.9c *Save is disabled while the check fails*, *The file is what will be saved*; §4.5a *a stage*, *Walk an
    entry* and the list's dot, each driven through the page's own handlers (review of #4367)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = tmp_path / "drive.js"
    probe.write_text(FLOWS_DRIVE, encoding="utf-8")
    js = app_mod.Path(app_mod.__file__).parent / "static" / "flows.js"
    run = subprocess.run([node, str(probe), str(js)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["save_off_on_return"] and got["save_off_while_asked"] and got["save_on_after"]
    assert got["saved"] == ["text cap 9"]
    assert got["dot"] and got["save_off_failing"] and got["dot_gone"]
    assert got["renamed"] and "another stage or audit has this name" in got["said"]
    assert got["walk_fresh"]
