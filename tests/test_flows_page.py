"""The Flows page's read, check and routes (design §4.9c *The Flows page*, §4.5a, TD-2054)."""

from __future__ import annotations

import json
import re

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
