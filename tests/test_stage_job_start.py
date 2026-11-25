"""A session started for one job of a built-in seat, and what it is told (design §4.9d *How each one runs*, TD-2053)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from shiftlead import flow3, stage_job, stage_job_start, stage_start, teams

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


BOARD = stage_job.new_job("board-answers", "1a2b3c4d", "t", "2026-11-24")
PR = stage_job.new_job("unheld-pull-requests", 42, "t", "2026-11-24")


def made(world, record, doc=None, **kw):
    org, team, _ = world
    return stage_job_start.launch(org, team, doc or builtin("build-review"), record, "sonnet", host="h", here="h", **kw)


@pytest.mark.parametrize(
    ("record", "lane", "name", "brief"),
    [
        (BOARD, "board:1a2b3c4d", "job-board-1a2b3c4d", "board-answers"),
        (PR, "pr:42", "job-pr-42", "unheld-pull-requests"),
    ],
)
def test_a_job_starts_in_the_build_role_on_the_seats_model_its_lane_the_work_order(world, record, lane, name, brief):
    got = made(world, record)
    x = got.launch
    assert (x.role, x.lane, x.name, x.team, got.model) == ("grinder", [lane], name, "t", "sonnet")
    assert x.create_params([])["controllers"] == [] and x.create_params([])["supervised"] is True
    text = (stage_job_start.JOB_BRIEFS / f"{brief}.md").read_text().strip()
    marks = ["one job of a built-in seat", "## Mechanics", "ao stage end <outcome>", "## This repo's rules", text]
    at = [x.prompt.index(m) for m in marks]
    assert at == sorted(at)
    assert "THE REPO RULES" in x.prompt
    for slot in ("{lane}", "{flow}", "{stage}"):
        assert slot not in x.prompt
    assert f"**{lane}**" in x.prompt


def test_a_job_takes_its_host_grants_project_bound_ledger_venv_and_listing_from_its_role_and_repo(world, monkeypatch):
    """TD-2168: the `Launch` fields a job takes from its role and its repo's config, as an entry stage's launch does."""
    org, team, root = world
    role = "  grinder: {grants: [control], context: {bound: 150k}}\n"
    (root / ".shiftlead.yml").write_text(f"ledger: docs/work\nroles:\n{role}")
    monkeypatch.setattr(teams, "_person", lambda *_a: ([], True))
    monkeypatch.setattr(teams, "node_venv", lambda host, here: None if host == here else f"/venv/{host}")
    venvs: list = []
    resolve = stage_job_start.repoconfig.resolve_role

    def spy(cfg, *a, **k):
        venvs.append(cfg.venv)
        return resolve(cfg, *a, **k)

    monkeypatch.setattr(stage_job_start.repoconfig, "resolve_role", spy)
    x = made(world, BOARD).launch
    assert (x.host, x.grants, x.project, x.ledger, x.unlisted) == ("", ["control"], "r", "docs/work", True)
    assert x.context_bound == 150_000
    far = stage_job_start.launch(org, team, builtin("build-review"), BOARD, "sonnet", host="node", here="h").launch
    assert far.host == "node", "a job on another host names it; on this one, none"
    assert venvs == [None, "/venv/node"], "the brief is composed for the node's own venv"


def test_the_outcomes_are_work_pushed_and_other_with_each_seats_own_check(world):
    board = made(world, BOARD).launch.prompt
    assert "closes the decided line" in board and "no entry is archived" in board
    assert "- `other`:" in board and "`ship`" not in board and "changes-wanted" not in board
    pr = made(world, PR).launch.prompt
    assert "#42, the one you were given" in pr and "Its pull request is #42" in pr


def test_a_question_goes_to_the_teams_tech_lead_by_its_name(world):
    assert "ao msg --kind ask --team t" in made(world, BOARD).launch.prompt


def test_the_independent_review_is_added_where_no_review_stage_reads_the_job(world):
    assert stage_job_start.job_stage(builtin("build")) == "build"
    assert "run the cadence's independent review" in made(world, BOARD, builtin("build")).launch.prompt
    assert "run the cadence's independent review" not in made(world, BOARD, builtin("build-review")).launch.prompt


def test_a_job_sent_back_is_told_why_and_works_on_its_branch(world):
    back = {**BOARD, "branch": "td-x", "pr": 9}
    text = made(world, back, came="the review asked for a test").launch.prompt
    assert "branch `td-x` and pull request #9" in text and "the review asked for a test" in text
    assert "It has no branch yet" in made(world, BOARD).launch.prompt


def test_no_session_name_of_a_job_is_a_stages():
    stages = {stage_start.stage_of(builtin(f), k)["name"] for f, k in (("build", "build"), ("build-review", "review"))}
    assert all(not stage_job_start.name_of(r).startswith(tuple(f"{s}-" for s in stages)) for r in (BOARD, PR))


def test_an_object_that_is_no_seats_is_refused():
    with pytest.raises(ValueError):
        stage_job_start.lane_of({**BOARD, "object": "nothex!!"})
    with pytest.raises(ValueError):
        stage_job_start.brief_of("sweeper")


def test_the_briefs_ship_with_the_package():
    for seat in stage_job.SEATS:
        assert stage_job_start.brief_of(seat)
    assert stage_job_start.JOB_TEMPLATE.is_file()


def test_a_job_takes_no_members_profile_and_runs_an_agent(world):
    _, team, _ = world
    team.members[0].profile = "some-shell"
    x = made(world, BOARD).launch
    assert x.profile == "" and x.adapter == teams.profiles.DEFAULT_ADAPTER != teams.profiles.SHELL_ADAPTER


def test_a_flow_with_no_stage_for_other_entries_adds_no_review(world):
    doc = builtin("build")
    doc["stages"][0]["takes"] = "design-first"
    assert stage_job_start.job_stage(doc) is None
    assert stage_job_start.job_stage({"stages": [{"name": "x", "takes": "any"}]}) == "x"
