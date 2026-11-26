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
    text = stage_job_start.brief_of(brief)
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


# -- a review stage's session on a job -------------------------------------------------------------------------------


def reviewed(world, record, doc=None, **kw):
    org, team, _ = world
    return stage_job_start.review_launch(org, team, doc or builtin("build-review"), record, host="h", here="h", **kw)


def test_a_review_stages_session_on_a_job_is_that_stages_on_its_model_holding_the_work_order(world):
    record = {**PR, "stage": "review", "branch": "td-x", "pr": 42}
    got = reviewed(world, record, came="pushed for review")
    x = got.launch
    assert (x.role, x.lane, x.name, x.team, got.model) == ("reviewer", ["pr:42"], "review-job-pr-42", "t", "sonnet")
    assert "**pr:42**" in x.prompt and "stage **Review**" in x.prompt and "pull request #42" in x.prompt
    assert "- `ship`:" in x.prompt and "- `changes-wanted`:" in x.prompt and "pushed for review" in x.prompt
    assert "work-pushed" not in x.prompt.split("The outcomes")[-1].split("\n\n")[0]


def test_a_review_session_on_a_job_is_told_the_jobs_branch_or_that_it_has_none(world):
    told = reviewed(world, {**PR, "stage": "review", "branch": "td-x", "pr": 42}).launch.prompt
    assert "Its record already carries branch `td-x` and pull request #42:" in told
    bare = reviewed(world, {**PR, "stage": "review", "pr": 42}).launch.prompt
    assert "Its record already carries pull request #42:" in bare and "branch `" not in bare
    none = reviewed(world, {**BOARD, "stage": "review"}).launch.prompt
    assert "already carries" not in none and "no branch yet" not in none, "a reviewer is never told to branch off"


def test_a_review_sessions_name_is_neither_an_entrys_stage_session_nor_a_job_session():
    record = {**BOARD, "stage": "review"}
    name = stage_job_start.review_name(record)
    assert name == "review-job-board-1a2b3c4d" and name != stage_job_start.name_of(record)
    assert not name.startswith("review-td-")


def test_a_record_at_no_review_stage_is_refused_a_review_session(world):
    for stage in ("build", "qa", None):
        with pytest.raises(teams.TeamError):
            reviewed(world, {**BOARD, "stage": stage})


def test_only_a_pull_request_jobs_session_is_told_closed_unmerged():
    pr = stage_job_start.told(PR, team="t", adds_review=False)
    assert "- `closed-unmerged`: a reason is given, and the pull request is closed and not merged" in pr
    board = stage_job_start.told(BOARD, team="t", adds_review=False)
    assert "closed-unmerged" not in board


@pytest.mark.parametrize(
    ("kind", "words"),
    [
        ("red", "**A red pull request**"),
        ("filing", "**A filing pull request**"),
        ("sync", "**A sync pull request**"),
        ("lift", "**A lift pull request**"),
        ("sweep", "**A sweep pull request**"),
        ("record", "**A record pull request**"),
    ],
)
def test_a_pull_request_jobs_brief_is_its_orders_words_by_its_kind(world, kind, words):
    prompt = made(world, {**PR, "kind": kind, **({"reason": "src/x.py is not in the lock"} if kind == "sync" else {})})
    text = prompt.launch.prompt
    assert words in text
    others = [
        w
        for k, w in (
            ("red", "**A red"),
            ("filing", "**A filing"),
            ("sync", "**A sync"),
            ("lift", "**A lift"),
            ("sweep", "**A sweep"),
            ("record", "**A record"),
        )
        if k != kind
    ]
    assert not any(w in text for w in others), "only the order's own kind's words"
    assert "<!-- kind -->" not in text and "Work on the pull request you were given" in text
    assert f"Its pull request is #42, a **{kind}** one: work on its own branch." in text
    assert ("Its order's reason, as the first offer read it: src/x.py is not in the lock" in text) == (kind == "sync")


def test_a_pull_request_job_with_no_kind_is_told_the_red_and_filing_words(world):
    text = stage_job_start.brief_of("unheld-pull-requests")
    assert "**A red pull request**" in text and "**A filing pull request**" in text
    assert "**A sync pull request**" not in text and "<!-- kind -->" not in text
    assert "Its pull request is #42: work on its own branch." in stage_job_start.told(PR, team="t", adds_review=False)
    with pytest.raises(ValueError):
        stage_job_start.brief_of("unheld-pull-requests", "fork")

    with pytest.raises(teams.TeamError, match="kind is one of"):
        made(world, {**PR, "kind": "fork"})
    board = made(world, {**BOARD, "kind": "red"}).launch.prompt
    assert "**A red pull request**" not in board, "a board answer's job takes no pull request's kind"


def test_the_closing_words_each_kind_ends_on_are_its_outcomes():
    for kind in stage_job_start.PR_KINDS:
        text = stage_job_start.brief_of("unheld-pull-requests", kind)
        assert "`work-pushed`" in text and "`closed-unmerged`" in text, kind
    lift = stage_job_start.brief_of("unheld-pull-requests", "lift")
    assert "a fresh gate <new> in place of <old>" in lift and "never by `ledger.py lift`" in lift
    assert "end `other` with what you read" in lift
    assert "`gh pr ready <n>`" in stage_job_start.brief_of("unheld-pull-requests", "sync")


# --- the launch on the set's login (design §4.9d *The login a seat starts on*, TD-2068) -----------------------------

SET_ORDER = ["claude-code:main", "gemini:g"]


def _set_shown(state="usable", login="claude-code:main", *, cut_over="2026-12-01", seat="board-answers"):
    """The home's `builtins_show` reading of a set: each seat's `now` the pick of its list."""
    now = {"login": login if state == "usable" else None, "state": state, "why": None}
    return {"cut_over": cut_over, "seats": [{"key": seat, "now": now}], "order": SET_ORDER}


def _start_job(world, monkeypatch, shown, got):
    org, team, _ = world
    monkeypatch.setattr(stage_start, "team_started", lambda *_a: True)
    calls: list[tuple[str, dict]] = []

    def call(method, **kw):
        calls.append((method, kw))
        return {"name_check": {"verdict": "free"}, "builtins_show": shown}.get(method, {"id": "new"})

    return stage_start.start(call, org, team, got), calls


def test_a_job_with_its_set_named_picks_its_seat_from_that_sets_reading(world):
    assert made(world, BOARD, on_set="cheap").pick == ("builtins", "board-answers")
    assert made(world, PR, on_set="cheap").on_set == "cheap"
    assert made(world, BOARD).pick is None, "no set named: a launch as before"


def test_after_the_cut_over_a_job_starts_on_its_sets_login_with_the_seats_model_and_the_list(world, monkeypatch):
    made_, calls = _start_job(world, monkeypatch, _set_shown(login="gemini:g"), made(world, BOARD, on_set="cheap"))
    assert made_ == {"id": "new"}
    assert ("builtins_show", {"set": "cheap"}) in calls and "team_show" not in [m for m, _ in calls]
    create = calls[-1][1]
    assert (create["login"], create["adapter"], create["profile"]) == ("gemini:g", "gemini", "")
    assert create["seat_model"] == "sonnet" and create["login_list"] == SET_ORDER


@pytest.mark.parametrize("state", ["waits", "none"])
def test_a_job_whose_set_has_no_usable_login_starts_nothing(world, monkeypatch, state):
    made_, calls = _start_job(world, monkeypatch, _set_shown(state), made(world, BOARD, on_set="cheap"))
    assert made_ is None and "create" not in [m for m, _ in calls]


def test_a_job_before_the_cut_over_launches_as_before(world, monkeypatch):
    before, calls = _start_job(world, monkeypatch, _set_shown(cut_over=None), made(world, BOARD, on_set="cheap"))
    assert before == {"id": "new"} and "seat_model" not in calls[-1][1]


def _job_on_node(world):
    org, team, _ = world
    return stage_job_start.launch(org, team, builtin("build-review"), BOARD, "sonnet", host="n", here="h", on_set="c")


def test_a_job_on_a_node_sends_its_sets_list_as_names_and_the_seats_model_and_no_login(world, monkeypatch):
    """§4.9d *Where a seat's session launches*, §4.9e *A team on a node*: the home does not read a node's logins, so the
    node's own pick takes the login from the set's list."""
    made_, calls = _start_job(world, monkeypatch, _set_shown(state="none", login=None), _job_on_node(world))
    assert made_ == {"id": "new"} and ("builtins_show", {"set": "c"}) in calls
    create = calls[-1][1]
    assert create["host"] == "n" and (create["seat_model"], create["login_list"], create["profile"]) == (
        "sonnet",
        SET_ORDER,
        "",
    )
    assert "login" not in create, "the home's own reading of its logins is not the node's"


def test_a_job_on_a_node_the_home_marked_or_with_no_list_starts_nothing(world, monkeypatch):
    marked = _set_shown()
    marked["seats"][0]["node_cannot_run"] = {"n": "c cannot run the board answers: no login in its list offers sonnet"}
    elsewhere = _set_shown()
    elsewhere["seats"][0]["node_cannot_run"] = {"m": "on another node"}
    unnamed = _set_shown(seat="sweeper")  # TD-2277: the set's reading names no row for the job's seat
    for shown, starts in ((marked, False), ({**_set_shown(), "order": []}, False), (unnamed, False), (elsewhere, True)):
        made_, calls = _start_job(world, monkeypatch, shown, _job_on_node(world))
        assert (made_ == {"id": "new"}) is starts and ("create" in [m for m, _ in calls]) is starts


def test_a_job_before_the_cut_over_on_a_node_launches_as_before(world, monkeypatch):
    made_, calls = _start_job(world, monkeypatch, _set_shown(cut_over=None), _job_on_node(world))
    assert made_ == {"id": "new"} and "seat_model" not in calls[-1][1] and "login" not in calls[-1][1]


@pytest.mark.parametrize(
    ("words", "marked"),
    [
        ("n: no login usable on n for sonnet: claude-code:main: limited (design §4.9e)", False),
        ("n: no login offers sonnet on n (design §4.9e)", True),
    ],
    ids=["waits", "none-offers"],
)
def test_a_nodes_refusal_of_a_job_starts_nothing_and_none_offering_marks_the_sets_seat(
    world, monkeypatch, words, marked
):
    """*No login usable* is a wait; *no login offers <model>* marks the set *cannot run* the seat on that node, with the
    list it was read against (§4.9e *A team on a node*: a built-in seat launched on a node is the same)."""
    org, team, _ = world
    monkeypatch.setattr(stage_start, "team_started", lambda *_a: True)
    calls: list[tuple[str, dict]] = []

    def call(method, **kw):
        calls.append((method, kw))
        if method == "create":
            raise stage_start.AgentError(words)
        return {"name_check": {"verdict": "free"}, "builtins_show": _set_shown()}.get(method, {})

    assert stage_start.start(call, org, team, _job_on_node(world)) is None
    got = [kw for m, kw in calls if m == "builtins_node_cannot"]
    want = [{"set": "c", "seat": "board-answers", "host": "n", "model": "sonnet", "logins": SET_ORDER}]
    assert got == (want if marked else []) and not [m for m, _ in calls if m == "team_node_cannot"]


def test_a_seat_the_sets_reading_does_not_name_starts_nothing(world, monkeypatch):
    made_, calls = _start_job(world, monkeypatch, _set_shown(seat="sweeper"), made(world, PR, on_set="cheap"))
    assert made_ is None and "create" not in [m for m, _ in calls]
