"""A session started for one stage of a format-3 flow, and what it is told (design §4.9c, §4.8, TD-2049)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sessionorc.client import AgentError
from shiftlead import flow3, repoconfig, stage_start, teams

pytestmark = pytest.mark.unit


def builtin(name: str) -> dict:
    return yaml.safe_load((flow3.PACKAGE_DIR / name / flow3.FILE).read_text(encoding="utf-8"))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(teams, "_person", lambda *_a: ([], False))
    (tmp_path / ".shiftlead.yml").write_text("{}\n")
    org = SimpleNamespace(
        checkout=lambda _repo, _host: str(tmp_path),
        roles={},
        project_of=lambda repo: repo,
        checkouts={"r": str(tmp_path)},
    )
    line = SimpleNamespace(role="grinder", brief="rules.md", profile=None)
    (tmp_path / "rules.md").write_text("THE REPO RULES\n")
    return org, SimpleNamespace(name="t", repo="r", members=[line]), tmp_path


def made(world, doc, key, work=None, **kw):
    org, team, _ = world
    return stage_start.launch(org, team, doc, key, work or stage_start.Work("TD-7"), host="h", here="h", **kw)


@pytest.mark.parametrize(
    ("flow", "key", "role"),
    [
        ("design-wise", "design", "designer"),
        ("build-review", "build", "grinder"),
        ("build-review", "review", "reviewer"),
    ],
)
def test_each_kind_starts_in_its_role_on_its_stages_model_with_the_four_parts_in_order(world, flow, key, role):
    doc = builtin(flow)
    got = made(world, doc, key)
    x = got.launch
    assert (x.role, x.lane, x.name) == (role, ["TD-7"], f"{key}-td-7")
    assert got.model == stage_start.stage_of(doc, key)["model"]
    standard = (flow3.STANDARD_DIR / f"{stage_start.stage_of(doc, key)['does']}.md").read_text().strip()
    marks = ["## Mechanics", "ao stage end <outcome>", "## This repo's rules", "## Your brief", standard]
    at = [x.prompt.index(m) for m in marks]
    assert at == sorted(at)
    assert "{" + "flow}" not in x.prompt and "{" + "stage}" not in x.prompt and "{" + "lane}" not in x.prompt


def test_the_repos_supplement_reaches_a_build_stage(world):
    assert "THE REPO RULES" in made(world, builtin("build"), "build").launch.prompt


def test_rule_11_adds_the_independent_review_whatever_brief_the_stage_picks(world):
    _, _, root = world
    flow = root / ".shiftlead" / "flows" / "mine"
    (flow / "briefs").mkdir(parents=True)
    (flow / "briefs" / "own.md").write_text("---\nkind: build\n---\nMY OWN BRIEF\n")
    doc = builtin("build")
    doc["stages"][0]["brief"] = "own"
    text = made(world, doc, "build", place="repo", flow_dir=flow).launch.prompt
    assert "run the cadence's independent review" in text and "MY OWN BRIEF" in text and "kind: build" not in text
    assert flow3.independent_review(builtin("build")) == {"build"}
    reviewed = builtin("build-review")
    assert flow3.independent_review(reviewed) == frozenset()
    assert "run the cadence's independent review" not in made(world, reviewed, "build").launch.prompt


def test_a_stage_passed_only_when_protected_is_no_review_that_runs_every_time():
    doc = builtin("build-review")
    review = stage_start.stage_of(doc, "review")
    review["only-when"] = "protected-files"
    assert flow3.independent_review(doc) == {"build"}


def test_also_is_appended_to_the_picked_brief(world):
    doc = builtin("build")
    doc["stages"][0]["also"] = "AND THIS TOO"
    text = made(world, doc, "build").launch.prompt
    standard = (flow3.STANDARD_DIR / "build.md").read_text().strip()
    assert text.index(standard) < text.index("AND THIS TOO")


def test_a_later_stage_is_told_the_branch_and_pull_request_on_its_record(world):
    work = stage_start.Work("TD-7", branch="td7-x", pr=12)
    text = made(world, builtin("build-review"), "build", work).launch.prompt
    assert "branch `td7-x` and pull request #12" in text and "It has no branch yet" not in text
    assert "It has no branch yet" in made(world, builtin("build-review"), "build").launch.prompt


def test_a_brief_a_stage_names_that_cannot_be_read_stops_the_launch(world):
    doc = builtin("build")
    doc["stages"][0]["brief"] = "gone"
    with pytest.raises(teams.TeamError, match="brief 'gone' cannot be read"):
        made(world, doc, "build", place="repo", flow_dir=world[2])


def test_nothing_starts_while_the_team_is_not_started(world):
    org, team, _ = world
    calls = []
    got = made(world, builtin("build"), "build")
    assert stage_start.start(lambda *a, **k: calls.append((a, k)) or {}, org, team, got) is None
    assert calls == []


def test_a_started_team_creates_it_supervised_unless_the_name_is_held(world, monkeypatch):
    org, team, _ = world
    monkeypatch.setattr(stage_start, "team_started", lambda *_a: True)
    got = made(world, builtin("build"), "build")
    calls = []

    def call(method, **kw):
        calls.append((method, kw))
        return {"verdict": "free"} if method == "name_check" else {"id": "new"}

    assert stage_start.start(call, org, team, got) == {"id": "new"}
    assert calls[1][1]["supervised"] is True and calls[1][1]["lane"] == ["TD-7"]
    assert stage_start.start(lambda *_a, **_k: {"verdict": "live"}, org, team, got) is None


def test_the_grinder_name_is_unchanged_and_reviewer_is_a_preset():
    assert "grinder" in repoconfig.PRESETS and "builder" not in repoconfig.PRESETS
    assert repoconfig.PRESETS["reviewer"]["brief"] == "reviewer.md"
    assert Path(repoconfig.__file__).with_name("briefs").joinpath("stage.md").is_file()


def test_the_name_is_checked_on_the_node_the_session_lands_on(world, monkeypatch):
    org, team, _ = world
    monkeypatch.setattr(stage_start, "team_started", lambda *_a: True)
    got = stage_start.launch(org, team, builtin("build"), "build", stage_start.Work("TD-7"), host="node", here="h")
    seen = []

    def call(method, **kw):
        seen.append((method, kw.get("host")))
        return {"verdict": "free"}

    stage_start.start(call, org, team, got)
    assert seen == [("name_check", "node"), ("create", "node")]


@pytest.mark.parametrize("head", ["---\r\nkind: build\r\n---\r\n", "--- \nkind: build\n---\n"])
def test_front_matter_the_check_accepts_is_left_out_of_the_prompt(world, head):
    _, _, root = world
    flow = root / ".shiftlead" / "flows" / "mine"
    (flow / "briefs").mkdir(parents=True)
    (flow / "briefs" / "own.md").write_bytes((head + "MY OWN BRIEF\n").encode())
    assert flow3.brief_kind((flow / "briefs" / "own.md").read_bytes().decode()) == "build"
    text = stage_start.brief_for({"name": "B", "does": "build", "brief": "own"}, "repo", flow)
    assert text == "MY OWN BRIEF"


def test_a_brief_a_node_cannot_read_is_a_refusal_not_a_crash(world):
    def read(_path):
        raise OSError("no link")

    with pytest.raises(teams.TeamError, match="cannot be read"):
        stage_start.brief_for({"name": "B", "does": "build", "brief": "own"}, "repo", world[2], read)


def test_an_unknown_or_shell_profile_is_refused(world, monkeypatch):
    org, team, _ = world
    team.members[0].profile = "nope"
    monkeypatch.setattr(teams.profiles, "get", lambda _n: (_ for _ in ()).throw(KeyError("no profile nope")))
    with pytest.raises(teams.TeamError, match="no profile nope"):
        made(world, builtin("build"), "build")
    monkeypatch.setattr(teams.profiles, "get", lambda _n: SimpleNamespace(adapter=teams.profiles.SHELL_ADAPTER))
    with pytest.raises(teams.TeamError, match="runs a shell"):
        made(world, builtin("build"), "build")


def test_a_holder_on_a_node_is_written_in_the_homes_form(world):
    got = made(world, builtin("build"), "build")
    node = replace(got, launch=replace(got.launch, host="n1"))
    assert stage_start.holder_of(got, {"id": "s1"}) == "s1"
    assert stage_start.holder_of(node, {"id": "s1"}) == "s1@n1"
    assert stage_start.holder_of(node, {"id": "s1@n1"}) == "s1@n1"


def test_the_claim_is_the_holders_and_a_refusal_is_returned():
    calls = []
    assert stage_start.claim(lambda m, **k: calls.append((m, k)), "s1", "TD-7") is None
    assert calls == [("progress", {"id": "s1", "ref": "TD-7", "status": "claimed"})]

    def refuse(*_a, **_k):
        raise AgentError("held")

    assert stage_start.claim(refuse, "s1", "TD-7") == "held"
