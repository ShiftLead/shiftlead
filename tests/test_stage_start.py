"""A session started for one stage of a format-3 flow, and what it is told (design §4.9c, §4.8, TD-2049)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sessionorc import teamstore
from sessionorc.client import AgentError
from shiftlead import flow3, repoconfig, stage_audit_start, stage_start, teams

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


def test_a_session_is_told_the_move_that_brought_it_and_the_persons_words(world):
    work = stage_start.Work("TD-7", came="the merge gate failed on ci (`refused` at `review`)", answer="mend it")
    text = made(world, builtin("build-review"), "build", work).launch.prompt
    assert "a move whose reason was: the merge gate failed on ci" in text
    assert "in their own words: mend it" in text
    plain = made(world, builtin("build-review"), "build").launch.prompt
    assert "a move whose reason was" not in plain and "in their own words" not in plain


CHECK = "**This entry is a live check**"


@pytest.mark.parametrize("own", [False, True])
def test_a_live_checks_session_is_told_the_checks_rules_whatever_brief_the_stage_picks(world, own):
    _, _, root = world
    doc, kw = builtin("build-review"), {}
    if own:
        flow = root / ".shiftlead" / "flows" / "mine"
        (flow / "briefs").mkdir(parents=True)
        (flow / "briefs" / "own.md").write_text("---\nkind: build\n---\nBUILD THE THING\n")
        doc["stages"][0]["brief"] = "own"
        kw = {"place": "repo", "flow_dir": flow}
    text = made(world, doc, "build", stage_start.Work("TD-7", live_check=True), **kw).launch.prompt
    assert CHECK in text and "- `check-waits`: " in text and "never press it" in text
    assert "replaces any building the brief below asks for" in text
    assert "a new branch, its name holding the entry's id and not already on origin" in text
    assert "post its `cadence-review:` comment" in text and "`ao td reserve`" in text
    assert text.index(CHECK) < text.index("## Your brief")
    assert ("BUILD THE THING" in text) is own


def test_a_build_entrys_session_is_told_nothing_of_a_live_check(world):
    text = made(world, builtin("build-review"), "build").launch.prompt
    assert CHECK not in text and "check-waits" not in text


def test_a_review_stage_holding_a_live_check_is_offered_no_check_waits(world):
    text = made(world, builtin("build-review"), "review", stage_start.Work("TD-7", live_check=True)).launch.prompt
    assert CHECK not in text and "check-waits" not in text


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
    assert calls == [(("host",), {})], "only the home's marks are read"


def test_a_start_reads_the_teams_mark_from_the_home_just_before_the_create(world):
    """The mark is the home's `host` read's `team_marks` (§4.9d *Started is a mark the home keeps*, TD-2065): a team
    stopped by the person, or another team started, starts nothing; this team's mark creates the session."""
    org, team, _ = world
    got = made(world, builtin("build"), "build")
    for marks, want in (
        ({team.name: {"stopped": {"at": "t", "by": "person"}}}, None),
        ({"other": {"started": {"since": "t", "by": "person"}}}, None),
        ({team.name: {"started": {"since": "t", "by": "person"}}}, {"id": "new"}),
    ):
        calls: list[str] = []
        answers = {"host": {"team_marks": marks}, "name_check": {"verdict": "free"}}

        def call(method, _calls=calls, _answers=answers, **kw):
            _calls.append(method)
            return _answers.get(method, {"id": "new"})

        assert stage_start.start(call, org, team, got) == want
        assert calls == (["host", "name_check", "team_show", "create"] if want else ["host"])


def test_a_started_team_creates_it_supervised_unless_the_name_is_held(world, monkeypatch):
    org, team, _ = world
    monkeypatch.setattr(stage_start, "team_started", lambda *_a: True)
    got = made(world, builtin("build"), "build")
    calls = []

    def call(method, **kw):
        calls.append((method, kw))
        return {"verdict": "free"} if method == "name_check" else {"id": "new"}

    assert stage_start.start(call, org, team, got) == {"id": "new"}
    assert [m for m, _ in calls] == ["host", "name_check", "team_show", "create"]
    assert calls[3][1]["supervised"] is True and calls[3][1]["lane"] == ["TD-7"]
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
    assert seen == [("host", None), ("name_check", "node"), ("team_show", None), ("create", "node")]


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


def test_the_flows_briefs_are_each_stages_as_its_start_reads_it_in_order(world):
    """§4.9c *The flow's content hash* (TD-2158): an offer hashes each brief a session's start would be given."""
    org, team, _ = world
    doc = builtin("build-review")
    doc["stages"][1]["also"] = "Read the tests first."
    got = stage_start.briefs(org, team, doc, host="h", here="h")
    assert [b["stage"] for b in got] == [flow3.key_of(st["name"]) for st in doc["stages"]]
    for b, st in zip(got, doc["stages"], strict=True):
        assert b["text"] == stage_start.brief_for(st, "package", None)
    assert got[1]["text"].endswith("Read the tests first.")


def test_an_unreadable_brief_on_any_stage_fails_the_flows_briefs(world):
    org, team, root = world
    doc = builtin("build-review")
    doc["stages"][1]["brief"] = "gone"
    with pytest.raises(teams.TeamError, match="brief 'gone' cannot be read"):
        stage_start.briefs(org, team, doc, host="h", here="h", place="repo", flow_dir=root)


def test_a_standard_brief_that_cannot_be_read_fails_the_flows_briefs(world, monkeypatch):
    org, team, _ = world
    monkeypatch.setattr(flow3, "STANDARD_DIR", world[2] / "nowhere")
    with pytest.raises(OSError):
        stage_start.briefs(org, team, builtin("build"), host="h", here="h")


# --- the launch on a login (design §4.9e *The launch on a login*, TD-2068) ---------------------------------------

ORDER = ["claude-code:main", "claude-code:spare", "gemini:g"]


def _rows(**change):
    """`teamstore.pick`'s rows: every login signed in on its own account and offering opus, unless changed."""
    rows = {lk: {"state": "signed_in", "account": f"a-{i}", "models": ["opus", "sonnet"]} for i, lk in enumerate(ORDER)}
    for lk, row in change.items():
        rows[lk.replace("_", ":", 1)] = {**rows[lk.replace("_", ":", 1)], **row}
    return rows


def _shown(rows, *, switched=True, audits=()):
    """The team's `team_show` reading as the home answers it: each stage's and audit's `now` the pick of the list."""
    return {
        "switched": switched,
        "flow": {"stages": [{"key": "build", "now": teamstore.pick(ORDER, "opus", rows)}]},
        "audits": [{"name": n, "now": teamstore.pick(ORDER, m, rows)} for n, m in audits],
        "logins": [{"login": lk} for lk in ORDER],
    }


def _start(world, monkeypatch, shown, got=None):
    org, team, _ = world
    monkeypatch.setattr(stage_start, "team_started", lambda *_a: True)
    got = got or made(world, builtin("build"), "build")
    calls: list[tuple[str, dict]] = []

    def call(method, **kw):
        calls.append((method, kw))
        return {"name_check": {"verdict": "free"}, "team_show": shown}.get(method, {"id": "new"})

    return stage_start.start(call, org, team, got), calls


def test_a_stage_starts_on_the_first_usable_login_of_the_teams_list_with_the_model_and_the_list(world, monkeypatch):
    made_, calls = _start(world, monkeypatch, _shown(_rows()))
    assert made_ == {"id": "new"}
    assert calls[2] == ("team_show", {"team": "t", "entries": False})
    create = calls[3][1]
    assert (create["login"], create["adapter"], create["profile"]) == ("claude-code:main", "claude-code", "")
    assert create["seat_model"] == "opus" and create["login_list"] == ORDER


def test_a_list_whose_first_login_is_at_its_reserve_starts_the_stage_on_the_second(world, monkeypatch):
    _, calls = _start(world, monkeypatch, _shown(_rows(**{"claude-code_main": {"at_reserve": True}})))
    assert calls[-1][0] == "create" and calls[-1][1]["login"] == "claude-code:spare"


def test_a_login_of_another_tool_starts_the_session_on_that_tool(world, monkeypatch):
    rows = _rows(**{"claude-code_main": {"state": "limited"}, "claude-code_spare": {"models": ["sonnet"]}})
    _, calls = _start(world, monkeypatch, _shown(rows))
    assert (calls[-1][1]["login"], calls[-1][1]["adapter"]) == ("gemini:g", "gemini")


def test_no_usable_login_or_none_offering_the_model_starts_nothing(world, monkeypatch):
    """None usable: the usage gate holds the launch; none offering the model: the team *cannot run*. Either way
    nothing is created, and the next pass asks again."""
    waits = _rows(**{lk.replace(":", "_", 1): {"state": "limited"} for lk in ORDER})
    none = _rows(**{lk.replace(":", "_", 1): {"models": ["sonnet"]} for lk in ORDER})
    for rows in (waits, none):
        made_, calls = _start(world, monkeypatch, _shown(rows))
        assert made_ is None and [m for m, _ in calls] == ["host", "name_check", "team_show"]


def test_a_stage_the_reading_does_not_name_starts_nothing(world, monkeypatch):
    shown = {**_shown(_rows()), "flow": {"stages": []}}
    made_, calls = _start(world, monkeypatch, shown)
    assert made_ is None and "create" not in [m for m, _ in calls]


def test_a_launch_with_no_pick_and_a_team_not_switched_launch_as_before(world, monkeypatch):
    no_pick = replace(made(world, builtin("build"), "build"), pick=None)
    for got, shown in ((no_pick, _shown(_rows())), (None, {"switched": False})):
        made_, calls = _start(world, monkeypatch, shown, got)
        assert made_ == {"id": "new"}
        assert "login" not in calls[-1][1] and "seat_model" not in calls[-1][1]
        assert ("team_show" in [m for m, _ in calls]) is (got is None)


def _on_node(world):
    org, team, _ = world
    return stage_start.launch(org, team, builtin("build"), "build", stage_start.Work("TD-7"), host="n", here="h")


def test_a_team_on_a_node_sends_its_list_as_names_and_the_model_and_no_login(world, monkeypatch):
    """§4.9e *A team on a node*: the home does not read a node's logins, so the node's own pick takes the login."""
    made_, calls = _start(world, monkeypatch, _shown(_rows()), _on_node(world))
    create = calls[-1][1]
    assert made_ == {"id": "new"} and calls[-1][0] == "create" and create["host"] == "n"
    assert (create["seat_model"], create["login_list"], create["profile"]) == ("opus", ORDER, "")
    assert "login" not in create


def test_a_team_on_a_node_the_home_marked_cannot_run_or_with_no_list_starts_nothing(world, monkeypatch):
    for shown in (
        {**_shown(_rows()), "cannot_run": "t cannot run f: no login in its list offers opus on n"},
        {**_shown(_rows()), "logins": []},
    ):
        made_, calls = _start(world, monkeypatch, shown, _on_node(world))
        assert made_ is None and "create" not in [m for m, _ in calls]


@pytest.mark.parametrize(
    ("words", "marked"),
    [
        ("n: no login usable on n for opus: claude-code:main: limited (design §4.9e)", False),
        ("n: no login offers opus on n (design §4.9e)", True),
    ],
    ids=["waits", "none-offers"],
)
def test_a_nodes_refusal_for_its_list_starts_nothing_and_none_offering_marks_the_team(
    world, monkeypatch, words, marked
):
    """*No login usable* is a wait, the next pass asking again; *no login offers <model>* marks the team *cannot run* at
    the home, naming the model, with the list and the flow it was read against."""
    org, team, _ = world
    monkeypatch.setattr(stage_start, "team_started", lambda *_a: True)
    shown = {**_shown(_rows()), "flow": {**_shown(_rows())["flow"], "name": "f"}}
    calls: list[tuple[str, dict]] = []

    def call(method, **kw):
        calls.append((method, kw))
        if method == "create":
            raise AgentError(words)
        return {"name_check": {"verdict": "free"}, "team_show": shown}.get(method, {})

    assert stage_start.start(call, org, team, _on_node(world)) is None
    marks = [kw for m, kw in calls if m == "team_node_cannot"]
    assert marks == ([{"team": "t", "model": "opus", "logins": ORDER, "flow": "f"}] if marked else [])


def test_any_other_refusal_of_a_nodes_create_is_raised(world, monkeypatch):
    org, team, _ = world
    monkeypatch.setattr(stage_start, "team_started", lambda *_a: True)

    def call(method, **kw):
        if method == "create":
            raise AgentError("n: bad params: unexpected keyword seat_model")
        return {"name_check": {"verdict": "free"}, "team_show": _shown(_rows())}.get(method, {})

    with pytest.raises(AgentError, match="bad params"):
        stage_start.start(call, org, team, _on_node(world))


def test_an_audits_run_starts_on_the_login_the_reading_picks_for_the_audits_model(world, monkeypatch):
    org, team, root = world
    monkeypatch.setattr(teams, "_person", lambda *_a: ([], False))
    doc = {**builtin("build"), "audits": [{"name": "Docs audit", "does": "docs", "model": "sonnet", "every": "1d"}]}
    got = stage_audit_start.launch(org, team, doc, "Docs audit", host="h", here="h")
    assert got.pick == ("audits", flow3.key_of("Docs audit"))
    rows = _rows(**{"claude-code_main": {"models": ["opus"]}})
    _, calls = _start(world, monkeypatch, _shown(rows, audits=[("Docs audit", "sonnet")]), got)
    assert (calls[-1][1]["login"], calls[-1][1]["seat_model"]) == ("claude-code:spare", "sonnet")


def test_a_stage_whose_name_is_not_its_key_finds_its_pick_by_key(world, monkeypatch):
    """`design-wise`'s *First read* is keyed `first-read`, the key the team's reading draws each stage under."""
    org, team, _ = world
    doc = builtin("design-wise")
    got = stage_start.launch(org, team, doc, "first-read", stage_start.Work("TD-7"), host="h", here="h")
    assert got.pick == ("stages", "first-read")
    rows = _rows(**{"claude-code_main": {"state": "limited"}})
    model = next(s["model"] for s in doc["stages"] if s["name"] == "First read")
    shown = {**_shown(rows), "flow": {"stages": [{"key": "first-read", "now": teamstore.pick(ORDER, model, rows)}]}}
    _, calls = _start(world, monkeypatch, shown, got)
    assert (calls[-1][1]["login"], calls[-1][1]["seat_model"]) == ("claude-code:spare", model)
