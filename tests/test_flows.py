"""Flows (design §4.9c, TD-309 slice 1): a flow found and read — the package's built-ins and a repo's
`.shiftlead/flows/<name>/` — judged usable when whole, a role's `kind`, the repo's top-level `held:`,
and a team's `flows:` refused at its start when a flow is unknown, not usable or cannot be followed."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from test_cli_teams import HOST, world  # noqa: F401 — the fixture, by name

from shiftlead import flowdefs, repoconfig, teams
from shiftlead import org as orgmod

pytestmark = pytest.mark.unit


def cfg_with(tmp_path: Path, text: str = "") -> repoconfig.RepoConfig:
    return repoconfig.load_text(text or None, tmp_path)


def repo_flow(root: Path, name: str, stages: list[dict], briefs: dict[str, str] | None = None, extra: str = "") -> Path:
    d = root / ".shiftlead" / "flows" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "flow.yml").write_text(yaml.safe_dump({"stages": stages}) + extra)
    for f, text in (briefs or {}).items():
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_text(text)
    return d


# ── kind and held ────────────────────────────────────────────────────────────────────────────────


def test_every_preset_has_a_kind_and_an_overlay_may_not_write_one(tmp_path):
    kinds = {n: repoconfig.resolve_role(cfg_with(tmp_path), n).kind for n in repoconfig.PRESETS}
    assert kinds == {
        "designer": "worker",
        "grinder": "worker",
        "hunter": "worker",
        "manager": "manager",
        "techlead": "seat",
        "auditor": "seat",
        "anchor": "seat",
        "plain": "plain",
    }
    with pytest.raises(ValueError, match=r"grinder.kind: a role's kind is its definition's"):
        cfg_with(tmp_path, "roles:\n  grinder: {kind: seat}\n")
    # a key-only role defines nothing (§4.9c, TD-313): refused when the file is read, and never resolved
    (tmp_path / ".shiftlead.yml").write_text("roles:\n  scout: {brief: d.md}\n")
    with pytest.raises(ValueError, match="`roles`.scout: unknown role 'scout'"):
        repoconfig.load(tmp_path)
    with pytest.raises(KeyError, match="unknown role 'scout'"):
        repoconfig.resolve_role(cfg_with(tmp_path, "roles:\n  scout: {brief: d.md}\n"), "scout")


def test_held_is_a_top_level_list_of_paths(tmp_path):
    assert cfg_with(tmp_path).held is None
    assert cfg_with(tmp_path, "held: [src/sessionorc/**, docs/briefs/**]\n").held == [
        "src/sessionorc/**",
        "docs/briefs/**",
    ]
    with pytest.raises(ValueError, match="names no path"):
        cfg_with(tmp_path, "held: []\n")


# ── the built-ins ────────────────────────────────────────────────────────────────────────────────


def test_the_built_in_flows_read_as_the_design_writes_them(tmp_path):
    """`td`, `build-review` and `build` (§4.9c): their stages, lanes and briefs; `build-review`'s
    review brief is `td`'s, by `../td/review.md`. Each brief is a file."""
    got = {n: flowdefs.find(n) for n in flowdefs.BUILTIN}
    shape = {n: [(s.name, s.role, s.lane) for s in f.stages] for n, f in got.items()}
    build = ("build", "grinder", ["free-pick", "owner:grinder"])
    assert shape == {
        "td": [("design", "designer", ["design-first", "owner:designer"]), build, ("review", "techlead", [])],
        "build-review": [build, ("review", "techlead", [])],
        "build": [build],
    }
    assert got["build-review"].stages[1].path == flowdefs.PACKAGE_DIR / "td" / "review.md"
    assert all(s.path is not None and s.path.is_file() for f in got.values() for s in f.stages)
    # all three are usable anywhere: `designer` is a preset (slice 2)
    plain = cfg_with(tmp_path)
    assert all(flowdefs.load(n, plain).usable for n in flowdefs.BUILTIN)


# ── a repo's flow ────────────────────────────────────────────────────────────────────────────────


def test_a_repo_flow_is_found_by_its_directory_and_reaches_package_and_sibling_briefs(tmp_path):
    repo_flow(
        tmp_path, "base", [{"name": "build", "role": "grinder", "lane": ["free-pick"], "brief": "b.md"}], {"b.md": "x"}
    )
    repo_flow(
        tmp_path,
        "mine",
        [
            {"name": "build", "role": "grinder", "lane": ["free-pick"], "brief": "../base/b.md"},
            {"name": "review", "role": "techlead", "brief": "package:td/review.md"},
        ],
    )
    f = flowdefs.load("mine", cfg_with(tmp_path))
    assert f.place == "repo" and f.usable, f.problems
    assert f.stages[0].path == tmp_path / ".shiftlead" / "flows" / "base" / "b.md"
    assert f.stages[1].path == flowdefs.PACKAGE_DIR / "td" / "review.md"
    assert flowdefs.load("nothing", cfg_with(tmp_path)) is None
    # a repo directory taking a built-in's name is never read: the built-in is the flow
    repo_flow(tmp_path, "build", [{"name": "x", "role": "grinder", "lane": ["free-pick"], "brief": "nope.md"}])
    assert flowdefs.load("build", cfg_with(tmp_path)).place == "package"


@pytest.mark.parametrize(
    ("stages", "extra", "says"),
    [
        ([{"name": "b", "role": "grinder", "lane": ["free-pick"], "brief": "gone.md"}], "", "is not a file"),
        ([{"name": "b", "role": "grinder", "lane": ["free-pick"], "brief": "b.md", "when": 1}], "", "not a stage key"),
        ([{"name": "b", "role": "grinder", "lane": ["free-pick"], "brief": "b.md"}], "owner: x\n", "not a flow key"),
        ([{"name": "b", "role": "grinder", "lane": ["free-pick"]}], "", "brief is required"),
        ([{"name": "b", "role": "techlead", "lane": ["free-pick"], "brief": "b.md"}], "", "names a worker"),
        ([{"name": "r", "role": "grinder", "brief": "b.md"}], "", "a review stage names a seat"),
        ([{"name": "b", "role": "grinder", "lane": ["free-pick"], "brief": "b.md", "held": "ui"}], "", "alone"),
        ([{"name": "r", "role": "techlead", "brief": "b.md", "held": "UI sets"}], "", "names one path set"),
        ([{"name": "b", "role": "nobody", "lane": ["free-pick"], "brief": "b.md"}], "", "unknown role 'nobody'"),
        ([{"name": "b", "role": "grinder", "lane": ["whatever"], "brief": "b.md"}], "", "lane word 'whatever'"),
        ([{"name": "b", "role": "grinder", "lane": ["free-pick"], "brief": "../../x.md"}], "", "nothing further"),
        ([{"name": "b", "role": "grinder", "lane": ["free-pick"], "brief": "/etc/passwd"}], "", "never absolute"),
        (
            [
                {"name": "a", "role": "grinder", "lane": ["free-pick"], "brief": "b.md"},
                {"name": "b", "role": "grinder", "lane": ["TD-001"], "brief": "b.md"},
            ],
            "",
            "two stages name the role 'grinder'",
        ),
        ([], "", "non-empty list"),
        ([{"name": "b", "role": "grinder", "lane": ["free-pick"], "brief": "."}], "", "name a file"),
        ([{"name": "b", "role": "grinder", "lane": ["free-pick"], "brief": "sub"}], "", "is not a file"),
    ],
)
def test_a_flow_that_is_not_whole_is_not_usable_and_says_why(tmp_path, stages, extra, says):
    repo_flow(tmp_path, "f", stages, {"b.md": "brief", "sub/x.md": "a directory's file"}, extra)
    f = flowdefs.load("f", cfg_with(tmp_path))
    assert not f.usable and any(says in p for p in f.problems), f.problems


def test_lane_words_are_rule_6s_a_named_items_or_a_hunters_area(tmp_path):
    ok = [
        {"name": "b", "role": "grinder", "lane": ["free-pick", "owner:grinder", "TD-042", "#17"], "brief": "b.md"},
        {"name": "h", "role": "hunter", "lane": ["ui"], "brief": "b.md"},
    ]
    repo_flow(tmp_path, "f", ok, {"b.md": "x"})
    assert flowdefs.load("f", cfg_with(tmp_path)).usable


# ── a team's flows: ──────────────────────────────────────────────────────────────────────────────


def test_flows_on_a_team_is_a_list_of_names_each_once(tmp_path):
    t = orgmod._team("t", {"projects": ["p"], "flows": ["td", "build"]}, "teams.t", source=tmp_path)
    assert t.flows == ["td", "build"]
    assert orgmod._team("t", {"projects": ["p"]}, "teams.t", source=tmp_path).flows == []
    with pytest.raises(ValueError, match="listed twice"):
        orgmod._team("t", {"projects": ["p"], "flows": ["td", "td"]}, "teams.t", source=tmp_path)
    with pytest.raises(ValueError, match="list of flow names"):
        orgmod._team("t", {"projects": ["p"], "flows": "td"}, "teams.t", source=tmp_path)


@pytest.mark.unit
def test_an_org_flow_is_found_over_a_repos_and_never_over_a_built_in(tmp_path, monkeypatch):
    # §4.9c *Where flows and roles live* (TD-313): the org's `~/.shiftlead/flows/<name>/` over a
    # repo's, whole; a directory taking a built-in's name is never read, in either place
    home = tmp_path / "home"
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    hunt = [{"name": "find", "role": "hunter", "lane": ["free"], "brief": "find.md"}]
    repo_flow(tmp_path / "r", "hunt", hunt, {"find.md": "the repo's find words\n"})
    assert flowdefs.find("hunt", tmp_path / "r").place == "repo"
    org_flow = flowdefs.org_dir() / "hunt"
    assert org_flow == home / "flows" / "hunt"
    org_flow.mkdir(parents=True)
    (org_flow / "flow.yml").write_text(yaml.safe_dump({"stages": hunt}))
    (org_flow / "find.md").write_text("the org's find words\n")
    got = flowdefs.load("hunt", cfg_with(tmp_path / "r"))
    assert got.place == "org" and got.dir == org_flow and got.usable, got.problems
    assert got.stages[0].path == org_flow / "find.md"
    # without a repo too: an org flow is every team's
    assert flowdefs.find("hunt").place == "org"
    (flowdefs.org_dir() / "td").mkdir()
    (flowdefs.org_dir() / "td" / "flow.yml").write_text("stages: []\n")
    assert flowdefs.find("td").place == "package"
    rows = {(r["name"], r["source"]): r for r in flowdefs.visible([tmp_path / "r"])}
    assert rows[("hunt", str(org_flow))]["usable"]
    assert "the org's flow hunt" in rows[("hunt", str(tmp_path / "r" / ".shiftlead" / "flows" / "hunt"))]["shadowed"]
    assert "built-in's name" in rows[("td", str(flowdefs.org_dir() / "td"))]["shadowed"]
    (flowdefs.org_dir() / ".hidden").mkdir()
    (flowdefs.org_dir() / ".hidden" / "flow.yml").write_text("stages: []\n")
    assert ".hidden" not in {r["name"] for r in flowdefs.visible([])}  # never found, so never listed


@pytest.mark.unit
def test_an_org_flow_cannot_be_followed_by_a_team_on_a_node(tmp_path, monkeypatch):
    # §4.9c: a node team's briefs are read on the node, and the org's directories are the home's
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    d = flowdefs.org_dir() / "hunt"
    d.mkdir(parents=True)
    (d / "flow.yml").write_text("stages:\n  - {name: find, role: hunter, lane: [free], brief: find.md}\n")
    (d / "find.md").write_text("find\n")
    hunt = flowdefs.load("hunt", cfg_with(tmp_path))
    assert flowdefs.unfollowable(hunt, {"hunter"}, techlead=False, held=(), team="cm-grind") == []
    why = flowdefs.unfollowable(hunt, {"hunter"}, techlead=False, held=(), team="cm-grind", node="contractmatch")
    # and a member started under it reads its stage brief as a flow's, so no *flow changed* is raised
    from shiftlead import teamrun

    assert teamrun._is_stage(d / "find.md")
    assert flowdefs.cannot_follow("hunt", "cm-grind", why) == (
        "hunt cannot be followed by cm-grind: an org flow, and cm-grind runs on contractmatch — define it in "
        "the repo, or drop hunt from flows:"
    )


def _with(tmp_path: Path, **team) -> orgmod.Org:
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["teams"]["ao-grind"].update(team)
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    return orgmod.load()


def test_a_team_listing_a_flow_it_can_follow_plans_and_one_it_cannot_is_refused(world, tmp_path):  # noqa: F811
    root = tmp_path / "shiftlead"
    techlead = {"name": "techlead-ao", "home": "shiftlead"}
    # nothing held: the review stage would hold every path
    org = _with(tmp_path, flows=["build-review"], techlead=techlead)
    with pytest.raises(
        teams.TeamError, match=r"build-review cannot be followed by ao-grind: nothing held — write held:"
    ):
        teams.plan(org, "ao-grind", HOST)
    (root / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    teams.plan(org, "ao-grind", HOST)  # followable now
    # no techlead seat
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    del doc["teams"]["ao-grind"]["techlead"]
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    with pytest.raises(teams.TeamError, match="no techlead seat"):
        teams.plan(orgmod.load(), "ao-grind", HOST)
    # `build` needs no seat and holds nothing
    teams.plan(_with(tmp_path, flows=["build"]), "ao-grind", HOST)
    # td: a designer resolves (a preset), but the team starts no member of it — not followable
    with pytest.raises(teams.TeamError, match=r"td cannot be followed by ao-grind: no designer — add one to members:"):
        teams.plan(_with(tmp_path, flows=["td"], techlead=techlead), "ao-grind", HOST)
    # an unknown flow
    with pytest.raises(teams.TeamError, match=r"flows: no flow 'hunt'"):
        teams.plan(_with(tmp_path, flows=["hunt"]), "ao-grind", HOST)


def test_a_team_with_no_flows_plans_as_before_and_its_slots_take_their_kind(world, tmp_path):  # noqa: F811
    teams.plan(orgmod.load(), "ao-grind", HOST)  # the fixture's team: no flows, unchanged
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["teams"]["ao-grind"]["members"].append({"role": "techlead", "name": "tl", "home": "shiftlead"})
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    with pytest.raises(teams.TeamError, match="a member takes a worker role, and 'techlead' is a seat"):
        teams.plan(orgmod.load(), "ao-grind", HOST)
    doc["teams"]["ao-grind"]["members"].pop()
    doc["teams"]["ao-grind"]["manager"]["role"] = "grinder"
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    with pytest.raises(teams.TeamError, match="manager: takes a manager role, and 'grinder' is a worker"):
        teams.plan(orgmod.load(), "ao-grind", HOST)
    doc["teams"]["ao-grind"]["manager"]["role"] = "manager"
    doc["teams"]["ao-grind"]["entries"] = {"feature": "manager"}
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    with pytest.raises(teams.TeamError, match="entries.feature takes a worker or a seat, and 'manager' is a manager"):
        teams.plan(orgmod.load(), "ao-grind", HOST)


@pytest.mark.unit
def test_every_template_carries_the_path_slots_and_the_path_words_moved_beside_it():
    # §4.9c *A brief has three layers*: every role template gains `{flow}` and `{stage}`; the path
    # words a team with no flow is told ship as `<role>.stage.md` and fill its `{stage}`
    for name, preset in repoconfig.PRESETS.items():
        if preset.get("brief"):
            text = (Path(repoconfig.__file__).parent / "briefs" / preset["brief"]).read_text()
            assert "{flow}" in text and "{stage}" in text, name
    cfg = repoconfig.RepoConfig()
    text, made = repoconfig.resolve_role(cfg, "grinder").compose(techlead="ao-r-techlead-1")
    assert "**This team's flow:** none" in text
    assert "Never merge a held PR yourself" in text and "ask --pr <n> ao-r-techlead-1" in text
    assert "a PR you have asked a reader about is the reader's to merge" in text  # stays in the template
    assert made["slots"]["{stage}"] == {"file": str(Path(repoconfig.__file__).parent / "briefs" / "grinder.stage.md")}
    assert list(made["slots"])[:3] == ["{repo}", "{flow}", "{stage}"]  # before the slots a stage brief may use
    text, _ = repoconfig.resolve_role(cfg, "techlead").compose()
    assert "### A held PR" in text
    text, made = repoconfig.resolve_role(cfg, "hunter").compose()  # the package ships no hunter.stage.md
    assert made["slots"]["{stage}"] == {"text": "none"} and "{stage}" not in text


@pytest.mark.unit
def test_under_a_flow_a_member_reads_its_path_line_and_its_stage_brief():
    td = flowdefs.find("td")
    held = ["src/sessionorc/**", "docs/briefs/**"]
    line = flowdefs.path_line(td, "grinder", techlead="ao-r-techlead-1", held=held)
    assert line == (
        "td: design (designer) → **build** (grinder) → review (ao-r-techlead-1, on src/sessionorc/**, "
        "docs/briefs/**) → you, through ao-r-techlead-1."
    )
    assert flowdefs.path_line(td, "manager").endswith("→ you, directly. You stand outside it.")
    links = {"review": ("techlead-ao-1", ["src/sessionorc/**"])}
    assert "review (techlead-ao-1, on src/sessionorc/**)" in flowdefs.path_line(td, "grinder", links=links)
    cfg = repoconfig.RepoConfig()
    text, made = repoconfig.resolve_role(cfg, "grinder").compose(
        techlead="ao-r-techlead-1", flow=flowdefs.under(td, "grinder", techlead="ao-r-techlead-1", held=held)
    )
    assert f"**This team's flow:** {line}" in text
    assert "A `design-first` entry is the design stage's" in text
    # §4.9c *The words* (TD-315): the build brief asks the reader `ao pr held` names, not the techlead by id
    assert "ask the reader it names" in text and "A PR with a reader still to read is never yours to merge" in text
    assert made["slots"]["{stage}"] == {"file": str(flowdefs.PACKAGE_DIR / "td" / "build.md")}
    assert made["slots"]["{flow}"] == {"text": line}
    # the techlead reads the review stage's brief; under `build` it reads none
    _, made = repoconfig.resolve_role(cfg, "techlead").compose(flow=flowdefs.under(td, "techlead"))
    assert made["slots"]["{stage}"] == {"file": str(flowdefs.PACKAGE_DIR / "td" / "review.md")}
    text, made = repoconfig.resolve_role(cfg, "techlead").compose(
        flow=flowdefs.under(flowdefs.find("build"), "techlead")
    )
    assert made["slots"]["{stage}"] == {"text": "none"} and "### A held PR" not in text


@pytest.mark.unit
def test_the_designer_is_a_preset_whose_template_wraps_it_flow_or_none(tmp_path):
    # §4.9c *The designer gets a template* (TD-310): the template wraps a designer as it wraps every
    # preset — the repo's brief is the `{repo}` supplement, flow or none, and with no repo brief the
    # template alone composes (the carve-out that read the repo's brief whole outside a flow is gone)
    designer = repoconfig.PRESETS["designer"]
    assert designer["kind"] == "worker" and designer["lane"] == ["design-first", "owner:designer"]
    assert "icon" not in designer and "label" not in designer
    (tmp_path / "d.md").write_text("the repo's designer brief, {techlead}\n")
    cfg = repoconfig.load_text("roles: {designer: {brief: d.md}}\n", tmp_path)
    role = repoconfig.resolve_role(cfg, "designer")
    text, made = role.compose(techlead="T")
    assert made["base"].endswith("briefs/designer.md") and "the repo's designer brief, T" in text
    assert made["slots"]["{stage}"] == {"text": "none"} and "This team's flow:** none" in text
    text, made = role.compose(techlead="T", flow=flowdefs.under(flowdefs.find("td"), "designer", techlead="T"))
    assert made["base"].endswith("briefs/designer.md") and "the repo's designer brief, T" in text
    assert made["slots"]["{stage}"] == {"file": str(flowdefs.PACKAGE_DIR / "td" / "design.md")}
    text, made = repoconfig.resolve_role(repoconfig.RepoConfig(), "designer").compose(techlead="T")
    assert made["base"].endswith("briefs/designer.md") and repoconfig.NO_REPO in text


def test_a_session_started_into_a_team_reads_its_current_flow(world, tmp_path):  # noqa: F811
    # §4.9c item 5, TD-309 slice 2a: `ao new --team` and the form's Team pick (`teams.brief_ids` with
    # the role and its repo) fill `{flow}` and `{stage}` from the team's current flow
    root = tmp_path / "shiftlead"
    (root / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    cfg = repoconfig.load(root)
    org = _with(tmp_path, flows=["build-review", "build"], techlead={"name": "techlead-ao", "home": "shiftlead"})
    ids = teams.brief_ids(org, "ao-grind", HOST, "grinder", cfg)
    seat = ids["techlead"]
    assert seat and ids["flow"].text == (
        f"build-review: **build** (grinder) → review ({seat}, on src/sessionorc/**) → you, through {seat}."
    )
    text, made = repoconfig.resolve_role(cfg, "grinder").compose(**ids)
    assert made["slots"]["{stage}"] == {"file": str(flowdefs.PACKAGE_DIR / "build-review" / "build.md")}
    assert "ask the reader it names" in text  # `ao pr held` names the reader (§4.9c *The words*, TD-315)
    # without the role and repo, or for a team with no flows, nothing of a flow: `{flow}` reads none
    assert "flow" not in teams.brief_ids(org, "ao-grind", HOST)
    assert "flow" not in teams.brief_ids(_with(tmp_path, flows=[]), "ao-grind", HOST, "grinder", cfg)


@pytest.mark.unit
def test_a_node_members_repo_stage_brief_is_read_on_its_checkout(tmp_path):
    # TD-309 (2): a repo flow's stage brief for a node member is read across the link with the rest of
    # its compose, never from this host's disk; a `package:` brief is this host's own, as `check` reads
    node = tmp_path / "on-node"  # the node's checkout: nothing of it is on this disk
    there = {
        node / ".shiftlead" / "flows" / "mine" / "flow.yml": (
            "stages:\n  - {name: build, role: grinder, lane: [free-pick], brief: build.md}\n"
            "  - {name: review, role: techlead, brief: 'package:td/review.md'}\n"
        ),
        node / ".shiftlead" / "flows" / "mine" / "build.md": "the node's own build words\n",
    }

    def read(path: Path) -> str | None:
        if not Path(path).is_relative_to(node):
            raise OSError(f"{path} is outside the checkout")
        return there.get(Path(path))

    cfg = repoconfig.load_text("held: [src/**]\n", node)
    mine = flowdefs.load("mine", cfg, read=read)
    assert mine is not None and mine.usable, mine.problems
    text, made = repoconfig.resolve_role(cfg, "grinder").compose(read=read, flow=flowdefs.under(mine, "grinder"))
    assert "the node's own build words" in text
    assert made["slots"]["{stage}"] == {"file": str(node / ".shiftlead" / "flows" / "mine" / "build.md")}
    _, made = repoconfig.resolve_role(cfg, "techlead").compose(read=read, flow=flowdefs.under(mine, "techlead"))
    assert made["slots"]["{stage}"] == {"file": str(flowdefs.PACKAGE_DIR / "td" / "review.md")}
    # a node that stops answering between the check and the compose refuses the member, by its file
    del there[node / ".shiftlead" / "flows" / "mine" / "build.md"]
    with pytest.raises(ValueError, match="stage brief .*build.md cannot be read"):
        repoconfig.resolve_role(cfg, "grinder").compose(read=read, flow=flowdefs.under(mine, "grinder"))


@pytest.mark.unit
def test_an_edit_to_a_stage_brief_is_brief_changed(tmp_path):
    # TD-309's *Done when*: `{stage}` is a file slot, so rule 7 reads an edit to it as it reads one to
    # the repo's brief (design §6 rule 7, §4.9c *Briefs*)
    from sessionorc import brief

    flow_dir = tmp_path / ".shiftlead" / "flows" / "mine"
    flow_dir.mkdir(parents=True)
    stage = "{name: build, role: grinder, lane: [free-pick], brief: build.md}"
    (flow_dir / "flow.yml").write_text(f"stages:\n  - {stage}\n")
    (flow_dir / "build.md").write_text("build words\n")
    cfg = repoconfig.load(tmp_path)
    mine = flowdefs.load("mine", cfg)
    assert mine is not None and mine.usable, mine.problems
    _, made = repoconfig.resolve_role(cfg, "grinder").compose(flow=flowdefs.under(mine, "grinder"))
    was = brief.record(made)
    assert was is not None and brief.changed(was)[0] == []
    (flow_dir / "build.md").write_text("other build words\n")
    assert brief.changed(was)[0] == [str(flow_dir / "build.md")]
    assert "other build words" in brief.fill(made)[0]


def test_a_session_started_into_a_node_team_under_an_org_flow_composes_as_with_no_flow(world, tmp_path):  # noqa: F811
    # review of TD-313 slice 1: `ao new --team` and the form reach a node's checkout through `read`;
    # an org flow is not followable there, so `{flow}` reads none rather than a brief from the wrong host
    d = flowdefs.org_dir() / "hunt"
    d.mkdir(parents=True)
    (d / "flow.yml").write_text("stages:\n  - {name: find, role: hunter, lane: [free], brief: find.md}\n")
    (d / "find.md").write_text("find\n")
    org = _with(tmp_path, flows=["hunt"])
    team, cfg = org.teams["ao-grind"], repoconfig.load(tmp_path / "shiftlead")
    assert teams.flow_for(org, team, cfg, "hunter").stage == d / "find.md"
    assert teams.flow_for(org, team, cfg, "hunter", read=lambda p: None) is None


def test_a_flow_that_cannot_be_read_on_its_host_composes_as_no_flow(world, tmp_path):  # noqa: F811
    # review of TD-309 slice 2a: a node's checkout that does not answer is never a 500 past the form
    root = tmp_path / "shiftlead"
    cfg = repoconfig.load(root)
    org = _with(tmp_path, flows=["mine"])

    def down(path: Path) -> str | None:
        raise OSError("contractmatch is not answering")

    team = org.teams["ao-grind"]
    assert teams.flow_for(org, team, cfg, "grinder", read=down) is None


# ── the compile at start (TD-309 slice 3a) ──────────────────────────────────────────────────────────


def _team_doc(tmp_path: Path) -> dict:
    return yaml.safe_load((tmp_path / "home" / "org.yml").read_text())


def _write(tmp_path: Path, doc: dict) -> orgmod.Org:
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    return orgmod.load()


def test_a_start_under_a_flow_compiles_lanes_the_reader_and_the_path(world, tmp_path):  # noqa: F811
    """§4.9c *What a flow compiles to*: a member's lane is its own, else its stage's; a member stage's
    role takes the techlead on the repos' `held:`, its own `review:` set aside and said once; a
    seat, the manager and a member outside the flows take none; each brief carries the path."""
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**, docs/briefs/**]\n")
    doc = _team_doc(tmp_path)
    t = doc["teams"]["ao-grind"]
    t.update(flows=["build-review"], techlead={"name": "techlead-ao", "home": "shiftlead"})
    del t["members"][0]["lane"]  # the grinders take the stage's lane
    doc["roles"]["grinder"]["review"] = {"reader": "techlead", "held": ["src/shiftlead/**"]}
    p = teams.plan(_write(tmp_path, doc), "ao-grind", HOST)
    assert p.flow == "build-review" and not p.sit_out
    grinders = [x for x in p.members if x.role == "grinder"]
    assert [x.lane for x in grinders] == [["free-pick", "owner:grinder"]] * 2
    reader = {"reader": "techlead", "held": ["docs/briefs/**", "src/sessionorc/**"], "bound": teams.REVIEW_BOUND}
    assert all(x.review == reader for x in grinders)
    hunter = next(x for x in p.members if x.role == "hunter")
    assert hunter.lane == ["ui"] and hunter.review is None  # outside the flows: its own lane, no reader
    assert p.techlead.review is None and p.lead.review is None
    assert "grinder's review: set aside — the flow says what waits" in p.notes
    seat = p.techlead_id
    assert f"build-review: **build** (grinder) → review ({seat}, on src/sessionorc/**, docs/briefs/**)" in (
        grinders[0].prompt
    )
    assert p.techlead.prompt_from["slots"]["{stage}"] == {"file": str(flowdefs.PACKAGE_DIR / "td" / "review.md")}
    assert "You stand outside it." in hunter.prompt and "You stand outside it." in p.lead.prompt
    # `build` has no review stage: nobody gets a reader
    t["flows"] = ["build"]
    p = teams.plan(_write(tmp_path, doc), "ao-grind", HOST)
    assert p.flow == "build" and all(x.review is None for x in p.launches)
    # no flows: today's start, the role's own `review:` kept and the written lane
    t["flows"] = []
    t["members"][0]["lane"] = "free-pick"
    p = teams.plan(_write(tmp_path, doc), "ao-grind", HOST)
    assert p.flow is None and not any("set aside" in n for n in p.notes)
    assert next(x for x in p.members if x.role == "grinder").review["held"] == ["src/shiftlead/**"]


def test_a_member_the_current_flow_does_not_use_sits_out(world, tmp_path):  # noqa: F811
    """§4.9c *Members the flow does not use sit out*: a designer, a stage of `td` and of no stage of
    `build-review`, is not started while `build-review` is current, and is under `td`."""
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    doc = _team_doc(tmp_path)
    t = doc["teams"]["ao-grind"]
    t.update(flows=["build-review", "td"], techlead={"name": "techlead-ao", "home": "shiftlead"})
    t["members"].append({"role": "designer", "name": "designer-ao", "home": "shiftlead"})
    p = teams.plan(_write(tmp_path, doc), "ao-grind", HOST)
    assert p.sit_out == ["designer-ao"] and "designer-ao" not in [x.name for x in p.launches]
    assert "designer-ao: sits out under build-review" in p.notes
    assert "hunt" in [x.name for x in p.members]  # outside every flow: runs
    t["flows"] = ["td", "build-review"]
    p = teams.plan(_write(tmp_path, doc), "ao-grind", HOST)
    designer = next(x for x in p.members if x.name == "designer-ao")
    assert not p.sit_out and designer.review == {
        "reader": "techlead",
        "held": ["src/sessionorc/**"],
        "bound": teams.REVIEW_BOUND,
    }


def test_a_session_started_into_a_team_takes_the_flows_reader(world, tmp_path):  # noqa: F811
    """§4.9c items 2 and 3 outside a start: a person's session and a member stage's role take the
    flow's reader; a role with no member stage takes none; a team with no flow keeps today's rule."""
    root = tmp_path / "shiftlead"
    (root / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    cfg = repoconfig.load(root)
    org = _with(tmp_path, flows=["build-review"], techlead={"name": "techlead-ao", "home": "shiftlead"})
    team = org.teams["ao-grind"]
    reader = {"reader": "techlead", "held": ["src/sessionorc/**"], "bound": teams.REVIEW_BOUND}
    assert teams.flow_review(org, team, cfg) == (True, reader)
    assert teams.flow_review(org, team, cfg, "grinder") == (True, reader)
    assert teams.flow_review(org, team, cfg, "hunter") == (True, None)
    bare = _with(tmp_path, flows=[])
    assert teams.flow_review(bare, bare.teams["ao-grind"], cfg) == (False, None)


# ── Members… and Add entry under flows (TD-309 slice 3b) ─────────────────────────────────────────


def test_remove_refuses_the_last_member_of_a_role_a_listed_flow_needs(world, tmp_path):  # noqa: F811
    """§4.9c *Every listed flow must be followable*: **Remove** refuses the last designer while `td`
    is listed, naming the flow, and leaves the file as it was; a grinder of two goes."""
    from test_cli_teams import org_doc

    from shiftlead import cli, teamrun

    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    doc = org_doc(tmp_path)
    t = doc["teams"]["ao-grind"]
    t.update(flows=["build-review", "td"], techlead={"name": "techlead-ao", "home": "shiftlead"})
    t["members"].append({"role": "designer", "name": "designer-ao", "home": "shiftlead"})
    path = tmp_path / "home" / "org.yml"
    path.write_text(yaml.safe_dump(doc, default_flow_style=None))
    before = path.read_text()
    with pytest.raises(teams.TeamError, match=r"^td needs a designer: drop td from flows: first$"):
        teamrun.remove_member(cli.call_sync, path, "ao-grind", index=2, role="designer", host=HOST)
    assert path.read_text() == before
    got = teamrun.remove_member(cli.call_sync, path, "ao-grind", index=0, role="grinder", host=HOST)
    assert got["did"] == "grind count: 2 → 1"
    with pytest.raises(teams.TeamError, match=r"^build-review needs a grinder"):
        teamrun.remove_member(cli.call_sync, path, "ao-grind", index=0, role="grinder", host=HOST)
    # a role no listed flow stages goes, as before
    assert teamrun.remove_member(cli.call_sync, path, "ao-grind", index=1, role="hunter", host=HOST)["did"] == (
        "removed hunt"
    )


def test_a_feature_entry_opens_the_flows_design_stage(world, tmp_path):  # noqa: F811
    """§4.9c item 4: `entries.feature` defaults to the role of the current flow's stage whose lane
    holds `design-first`; a debt stays the techlead's; the team's own `entries:` wins."""
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    org = _with(tmp_path, flows=["td"], techlead={"name": "techlead-ao", "home": "shiftlead"})
    team = org.teams["ao-grind"]
    assert teams.entry_role(org, team, "feature", HOST, HOST) == "designer"
    assert teams.entry_role(org, team, "debt", HOST, HOST) == "techlead"
    org = _with(tmp_path, flows=["build-review"])
    assert teams.entry_role(org, org.teams["ao-grind"], "feature", HOST, HOST) == "techlead"  # no design stage
    org = _with(tmp_path, flows=["td"], entries={"feature": "grinder"})
    assert teams.entry_role(org, org.teams["ao-grind"], "feature", HOST, HOST) == "grinder"


# ── the setting: which listed flow runs (TD-309 slice 4) ──────────────────────────────────────────


def test_the_flow_setting_is_a_name_the_agent_takes_without_a_definition():
    from sessionorc import settings as settings_mod

    assert settings_mod.parse_team({"flow": "build-review"}) == {"flow": "build-review"}
    for bad in ("", "  ", "td review", 3):
        with pytest.raises(ValueError, match="flow is the name of a flow"):
            settings_mod.parse_team({"flow": bad})


def test_the_person_picks_a_listed_flow_and_an_unlisted_pick_reads_as_the_first(world, tmp_path):  # noqa: F811
    """§4.9c *A team lists its flows, and the person picks one*: `teams.<team>.flow` turns the team
    to a flow it lists; absent, the first; a value it no longer lists reads as the first, said."""
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    doc = _team_doc(tmp_path)
    t = doc["teams"]["ao-grind"]
    t.update(flows=["td", "build-review"], techlead={"name": "techlead-ao", "home": "shiftlead"})
    t["members"].append({"role": "designer", "name": "designer-ao", "home": "shiftlead"})
    org = _write(tmp_path, doc)
    assert teams.current_flow(org.teams["ao-grind"]) == "td"
    picked = orgmod.with_settings(org, {"ao-grind": {"flow": "build-review"}, "other": {"flow": "td"}})
    assert picked is not org and org.teams["ao-grind"].flow == ""  # a copy: the definition never carries it
    team = picked.teams["ao-grind"]
    assert teams.current_flow(team) == "build-review" and teams.flow_unlisted(team) == ""
    p = teams.plan(picked, "ao-grind", HOST)  # the start compiles the pick
    assert p.flow == "build-review" and p.sit_out == ["designer-ao"]
    gone = orgmod.with_settings(org, {"ao-grind": {"flow": "build"}}).teams["ao-grind"]
    assert teams.current_flow(gone) == "td"
    assert teams.flow_unlisted(gone) == "teams.ao-grind.flow is build, which ao-grind does not list — it runs td"
    assert orgmod.with_settings(org, {"ao-grind": {"on_work": "ask"}}) is org  # no pick: the org as read


def test_ao_team_flow_lists_the_flows_and_writes_the_pick(world, tmp_path, capsys, monkeypatch):  # noqa: F811
    """`ao team flow <team> [<flow>]` (design §4.7): the flows, the current marked, each strip and why
    one cannot be followed; a pick of a listed flow is written through `set_settings`, any other refused."""
    from shiftlead import cli

    _, state = world
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    doc = _team_doc(tmp_path)
    doc["teams"]["ao-grind"].update(
        flows=["build", "td", "build-review"], techlead={"name": "techlead-ao", "home": "shiftlead"}
    )
    _write(tmp_path, doc)
    assert cli.main(["team", "flow", "ao-grind"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "* build         build → you, through ao-shiftlead-techlead-ao",
        "  td            design → build → review → you, through ao-shiftlead-techlead-ao",
        "                td cannot be followed by ao-grind: no designer — add one to members:, or drop td from flows:",
        "  build-review  build → review → you, through ao-shiftlead-techlead-ao",
    ]
    assert cli.main(["team", "flow", "ao-grind", "hunt"]) != 0
    assert "lists build, td, build-review, not 'hunt'" in capsys.readouterr().err
    assert cli.main(["--json", "team", "flow", "ao-grind", "build-review"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert state["teams"]["ao-grind"] == {"flow": "build-review"}
    assert got["flow"] == "build-review" and [r["current"] for r in got["flows"]] == [False, False, True]
    assert cli.main(["team", "flow", "ao-grind"]) == 0  # read back from the home's setting
    assert capsys.readouterr().out.splitlines()[-1].startswith("* build-review ")
    # a session's `ao` reads the pick as the person's does: the file, not the person-only `settings` read
    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-shiftlead-grinder-ao-1")
    assert teams.current_flow(cli._org_here().teams["ao-grind"]) == "build-review"
    monkeypatch.delenv("SHIFTLEAD_SESSION")
    del doc["teams"]["ao-grind"]["flows"]
    _write(tmp_path, doc)
    # no flows: a flow named is refused; the bare read and Apply read its seats alone (§4.9c, TD-399)
    assert cli.main(["team", "flow", "ao-grind", "td"]) != 0
    assert "lists no flows:" in capsys.readouterr().err
    assert cli.main(["team", "flow", "ao-grind"]) == 0
    assert "ao-grind lists no flows:" in capsys.readouterr().out


# ── the listings (TD-309 slice 6) ────────────────────────────────────────────────────────────────


def test_ao_team_list_carries_the_flows_and_the_feature_role(world, tmp_path, capsys):  # noqa: F811
    """§4.9c *What is shown*: `ao team list` and its `--json` carry `flows`, `flow` and why a flow
    cannot be followed; `entries.feature` reads as the current flow fills it."""
    from shiftlead import cli

    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    doc = _team_doc(tmp_path)
    t = doc["teams"]["ao-grind"]
    t.update(flows=["td", "build-review"], techlead={"name": "techlead-ao", "home": "shiftlead"})
    t["members"].append({"role": "designer", "name": "designer-ao", "home": "shiftlead"})
    _write(tmp_path, doc)
    assert cli.main(["--json", "team", "list"]) == 0
    row = next(r for r in json.loads(capsys.readouterr().out)["teams"] if r["name"] == "ao-grind")
    assert row["flow"] == "td" and [f["name"] for f in row["flows"]] == ["td", "build-review"]
    assert row["entries"]["feature"] == "designer" and row["flow_note"] == ""
    assert cli.main(["team", "list"]) == 0
    assert (
        "  flow: td — design → build → review → you, through ao-shiftlead-techlead-ao  (also lists build-review)"
        in (capsys.readouterr().out)
    )
    t["members"].pop()  # no designer: td cannot be followed, said under the team
    _write(tmp_path, doc)
    assert cli.main(["team", "list"]) == 0
    assert "td cannot be followed by ao-grind: no designer" in capsys.readouterr().out
    assert cli.main(["--json", "team", "list"]) == 0
    other = [r for r in json.loads(capsys.readouterr().out)["teams"] if r["name"] != "ao-grind"]
    assert all(r["flow"] is None and r["flows"] == [] for r in other)  # a team with no flows: none


def test_ao_org_lists_every_flow_and_check_fails_on_one_not_usable(world, tmp_path, capsys):  # noqa: F811
    """§4.7: `ao org` lists the built-ins and each registered repo's flows with source and whether
    usable; `ao org check` fails on a flow that is not usable, and a repo flow taking a built-in's
    name is listed as not read."""
    from shiftlead import cli

    root = tmp_path / "shiftlead"
    repo_flow(
        root, "hunt", [{"name": "find", "role": "hunter", "lane": ["free"], "brief": "find.md"}], {"find.md": "x"}
    )
    repo_flow(root, "td", [{"name": "x", "role": "grinder", "lane": ["free-pick"], "brief": "x.md"}])
    assert cli.main(["--json", "org"]) == 0
    flows = {(f["name"], f["source"]): f for f in json.loads(capsys.readouterr().out)["flows"]}
    assert all(flows[(n, "package")]["usable"] for n in flowdefs.BUILTIN)
    hunt = flows[("hunt", str(root / ".shiftlead" / "flows" / "hunt"))]
    assert hunt["usable"], hunt["problems"]
    assert flows[("td", str(root / ".shiftlead" / "flows" / "td"))]["shadowed"].startswith("not read: td is a built-in")
    assert cli.main(["org"]) == 0
    assert f"flow hunt          usable  [{root / '.shiftlead' / 'flows' / 'hunt'}]" in capsys.readouterr().out
    assert cli.main(["org", "check"]) == 0
    capsys.readouterr()
    repo_flow(root, "broken", [{"name": "b", "role": "grinder", "lane": ["free-pick"], "brief": "gone.md"}])
    assert cli.main(["org", "check"]) == 1
    assert "lacking: flow broken (" in capsys.readouterr().out


def test_a_flow_file_that_cannot_be_read_is_a_problem_of_the_flow_not_a_crash(tmp_path):
    """Review of #1068: `ao org` and its check list every flow, so one bad file is that flow's problem."""
    d = repo_flow(tmp_path, "bad", [{"name": "b", "role": "grinder", "lane": ["free-pick"], "brief": "b.md"}])
    (d / "flow.yml").write_bytes(b"stages: \xff\xfe\n")
    (tmp_path / ".shiftlead" / "flows" / "stray.txt").write_text("not a flow\n")
    rows = {f["name"]: f for f in flowdefs.visible([tmp_path])}
    assert not rows["bad"]["usable"] and "could not be read" in rows["bad"]["problems"][0]
    assert "stray.txt" not in rows and all(rows[n]["usable"] for n in flowdefs.BUILTIN)


def test_ao_org_check_warns_of_each_key_the_flow_fills_the_same(world, tmp_path, capsys):  # noqa: F811
    """§4.9c *What is shown*: `ao org check` warns, per team, of each key it writes that its current
    flow would fill with the same value — a lane in its written order, `entries.feature`, a stage
    role's `review:` in the repo's `roles:` with `held` as a set — and fails on none of them."""
    from shiftlead import cli

    held = "held: [src/sessionorc/**, docs/briefs/**]\n"
    review = "roles:\n  grinder:\n    review: {reader: techlead, held: [docs/briefs/**, src/sessionorc/**]}\n"
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text(held + review)
    doc = _team_doc(tmp_path)
    t = doc["teams"]["ao-grind"]
    t.update(flows=["td"], techlead={"name": "techlead-ao", "home": "shiftlead"}, entries={"feature": "designer"})
    t["members"][0]["lane"] = ["free-pick", "owner:grinder"]
    t["members"].append({"role": "designer", "name": "design", "lane": ["owner:designer", "design-first"]})
    org = _write(tmp_path, doc)
    teams.plan(org, "ao-grind", HOST)
    got = teams.flow_redundant(org, org.teams["ao-grind"], HOST, HOST)
    assert got == [
        "team ao-grind: grind's lane: free-pick, owner:grinder is what flow td fills — org.yml may drop it",
        "team ao-grind: entries.feature: designer is what flow td fills — org.yml may drop it",
        "team ao-grind: grinder's review: in .shiftlead.yml is the reader flow td gives — the repo may drop it "
        "(a session outside a flow still reads it)",
    ]  # the designer's lane is in another order, its pick order: not the same; the hunter is outside the flow
    assert cli.main(["org", "check"]) == 0
    out = capsys.readouterr().out
    assert "warning: team ao-grind: grind's lane: free-pick, owner:grinder is what flow td fills" in out
    # a held set that differs, and no flow at all: nothing to say
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text(held + review.replace("docs/briefs/**, ", ""))
    t["members"][0]["lane"] = "free-pick"
    t.pop("entries")
    org = _write(tmp_path, doc)
    assert teams.flow_redundant(org, org.teams["ao-grind"], HOST, HOST) == []
    t["flows"] = []
    t["members"][0]["lane"] = ["free-pick", "owner:grinder"]
    org = _write(tmp_path, doc)
    assert teams.flow_redundant(org, org.teams["ao-grind"], HOST, HOST) == []


# ── the switch: the records against the compile, and Apply (TD-309 slice 5c) ─────────────────────


def _switching(world, tmp_path, monkeypatch, flows):  # noqa: F811
    """A live ao-grind under `flows[0]`, its records as the start created them, each carrying the
    `brief` the home records (the stage file among its sources); `relaunch` calls answered and kept."""
    from shiftlead import cli, teamrun

    _, state = world
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**]\n")
    doc = _team_doc(tmp_path)
    t = doc["teams"]["ao-grind"]
    t.update(flows=flows, techlead={"name": "techlead-ao", "home": "shiftlead"})
    del t["members"][0]["lane"]
    t["members"].append({"role": "designer", "name": "designer-ao", "home": "shiftlead"})
    org = _write(tmp_path, doc)
    plan, _ = teamrun.start(cli.call_sync, org, "ao-grind", HOST)
    for x, rec in zip(plan.launches, state["sessions"], strict=True):
        stage = teamrun.stage_of(x.prompt_from)
        rec.update(brief={"sources": [{"path": stage}] if stage else []}, seat=(x.trigger if x.seat else None))
    fake = cli.call_sync

    def call(method, **params):
        if method == "relaunch":
            state["calls"].append((method, params))
            return next(s for s in state["sessions"] if s["id"] == params["id"])
        return fake(method, **params)

    monkeypatch.setattr(cli, "call_sync", call)
    state["calls"].clear()
    return state, doc


def test_a_team_running_its_flow_reads_no_difference(world, tmp_path, capsys, monkeypatch):  # noqa: F811
    from shiftlead import cli

    _switching(world, tmp_path, monkeypatch, ["td", "build-review"])
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []
    assert cli.main(["team", "flow", "ao-grind"]) == 0
    assert "flow changed" not in capsys.readouterr().out


def test_a_live_add_under_the_flow_raises_no_flow_changed(world, tmp_path, capsys, monkeypatch):  # noqa: F811
    # TD-309's *Done when*: **Members…** Add starts the member with the current flow's compiled lane,
    # reader and stage brief (§4.5a *Members dialog*), so the team still reads as running its flow
    from shiftlead import cli, teamrun

    state, _ = _switching(world, tmp_path, monkeypatch, ["td", "build-review"])
    got = teamrun.add_member(cli.call_sync, tmp_path / "home" / "org.yml", "ao-grind", HOST, role="grinder")
    (made,) = got["created"]
    (create,) = [p for m, p in state["calls"] if m == "create"]
    assert teamrun.stage_of(create["prompt_from"]).endswith("flows/td/build.md")
    rec = next(s for s in state["sessions"] if s["id"] == made["id"])
    rec.update(brief={"sources": [{"path": teamrun.stage_of(create["prompt_from"])}]})
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []


def test_a_switch_sits_the_designer_out_and_relaunches_whose_stage_or_reader_moved(
    world,  # noqa: F811
    tmp_path,
    capsys,
    monkeypatch,  # noqa: F811
):
    """§4.9c *Switching*: `ao team flow <team> <flow>` writes the pick and applies it — the designer
    `build-review` gives no stage sits out by the home's `relaunch {sit_out}`, a grinder whose stage
    brief moved is handed its new launch, and the seat whose review brief is the same is untouched;
    then `build` takes the grinders' reader off and the seat's stage brief away."""
    from shiftlead import cli

    state, _ = _switching(world, tmp_path, monkeypatch, ["td", "build-review", "build"])
    assert cli.main(["team", "flow", "ao-grind", "build-review", "--apply"]) == 0
    out = capsys.readouterr().out
    assert state["teams"]["ao-grind"] == {"flow": "build-review"}
    calls = [(m, p) for m, p in state["calls"] if m == "relaunch"]
    sat = [p for _, p in calls if p.get("sit_out")]
    assert [p["id"] for p in sat] == ["ao-shiftlead-designer-ao"]
    handed = {p["id"]: p["launch"] for _, p in calls if "launch" in p}
    assert sorted(handed) == ["ao-shiftlead-grind-1", "ao-shiftlead-grind-2"]
    launch = handed["ao-shiftlead-grind-1"]
    assert sorted(launch) == ["lane", "profile", "prompt", "prompt_from", "review"]  # profile always (TD-620)
    assert launch["prompt_from"]["slots"]["{stage}"]["file"].endswith("build-review/build.md")
    assert "designer-ao: sits out under build-review" in out
    assert "grind-1: relaunched — stage td/build.md → build-review/build.md" in out
    # the home took them (the fake does not): the records now read as the new launch
    for s in state["sessions"]:
        if s["id"] in handed:
            s["brief"] = {"sources": [{"path": handed[s["id"]]["prompt_from"]["slots"]["{stage}"]["file"]}]}
        if s["id"] == "ao-shiftlead-designer-ao":
            s.update(state="closed", closed_for={"why": "sit_out"})
    state["calls"].clear()
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []
    # `build`: no review stage — the reader comes off (sent as None, so the home removes it)
    assert cli.main(["--json", "team", "flow", "ao-grind", "build", "--apply"]) == 0
    got = json.loads(capsys.readouterr().out)["apply"]
    handed = {p["id"]: p["launch"] for m, p in state["calls"] if m == "relaunch"}
    assert handed["ao-shiftlead-grind-1"]["review"] is None
    assert handed["ao-shiftlead-techlead-ao"]["prompt_from"]["slots"]["{stage}"].get("file") is None
    lines = [d["line"] for d in got["applied"]]
    assert any(x.startswith("grind-1: relaunched — reader techlead → none") for x in lines)


def test_an_apply_clears_flow_changed_before_the_member_restarts(world, tmp_path, capsys, monkeypatch):  # noqa: F811
    """TD-355: the home's `relaunch` replaces the launch record and marks the record `relaunch: {at,
    lane, review}`; the record's own lane and `review` stay the old run's until the member restarts,
    so the mark — what it runs next — is what the flow is read against, and Apply is not offered
    again. A record's `held` in another order is no difference; another set is."""
    from shiftlead import cli

    state, _ = _switching(world, tmp_path, monkeypatch, ["td", "build"])
    (tmp_path / "shiftlead" / ".shiftlead.yml").write_text("held: [src/sessionorc/**, docs/briefs/**]\n")
    read = [s for s in state["sessions"] if s.get("review")]
    assert {s["name"] for s in read} >= {"grind-1", "grind-2"}
    assert all(s["review"]["held"] == ["src/sessionorc/**"] for s in read)
    for s in read:  # started before the repo held docs/briefs/** too: in the repo's order, not sorted
        s["review"] = {**s["review"], "held": ["src/sessionorc/**", "docs/briefs/**"]}
    grind = next(s for s in read if s["name"] == "grind-1")
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []  # the compiled set, sorted: the same
    grind["review"] = {**grind["review"], "held": ["src/sessionorc/**"]}
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    (d,) = json.loads(capsys.readouterr().out)["differences"]
    assert d["name"] == "grind-1" and d["what"] == ["reader techlead → techlead"]  # another set still differs
    grind["review"] = {**grind["review"], "held": ["docs/briefs/**", "src/sessionorc/**"]}
    assert cli.main(["--json", "team", "flow", "ao-grind", "build", "--apply"]) == 0
    assert "grind-1" in [d["name"] for d in json.loads(capsys.readouterr().out)["apply"]["applied"]]
    handed = {p["id"]: p["launch"] for m, p in state["calls"] if m == "relaunch" and "launch" in p}
    assert handed["ao-shiftlead-grind-1"]["review"] is None
    old = dict(grind["review"])
    for s in state["sessions"]:  # the home took them: brief re-recorded, the mark set, lane and review the old run's
        if s["id"] in handed:
            launch = handed[s["id"]]
            s["brief"] = {"sources": [{"path": stage}] if (stage := teamrun_stage(launch)) else []}
            s["relaunch"] = {"at": "2026-10-06T20:58:00Z", "lane": launch["lane"], "review": launch["review"]}
        if s["name"] == "designer-ao":
            s.update(state="closed", closed_for={"why": "sit_out"})
    assert grind["review"] == old
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []
    grind["relaunch"] = {"at": "2026-10-06T20:58:00Z"}  # a mark from before it carried them says nothing
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    assert [d["name"] for d in json.loads(capsys.readouterr().out)["differences"]] == ["grind-1"]


def teamrun_stage(launch: dict) -> str | None:
    from shiftlead import teamrun

    return teamrun.stage_of(launch["prompt_from"])


def test_a_chain_is_compared_link_by_link_each_held_as_a_set():
    from shiftlead import teamrun

    chain = {
        "chain": [
            {"stage": "ui", "reader": "ui-reader", "held": ["src/shiftlead/ui/**", "docs/mockups/**"]},
            {"stage": "review", "reader": "techlead", "held": ["src/sessionorc/**"]},
        ],
        "bound": teams.REVIEW_BOUND,
    }
    key = teamrun._review_key
    reordered = {
        **chain,
        "chain": [{**chain["chain"][0], "held": ["docs/mockups/**", "src/shiftlead/ui/**"]}, chain["chain"][1]],
    }
    assert key(reordered) == key(chain)
    assert key({**chain, "chain": chain["chain"][::-1]}) != key(chain)  # the links' order is the flow's
    assert key({**chain, "chain": [chain["chain"][0], {**chain["chain"][1], "reader": "other"}]}) != key(chain)
    assert key({**chain, "bound": "4h"}) != key(chain)
    assert key({"reader": "techlead", "held": ["b", "a"]}) == key(
        {"reader": "techlead", "held": ["a", "b"], "bound": teams.REVIEW_BOUND}
    )
    assert key(None) is None and key({}) is None


def test_a_switch_back_starts_the_member_that_sat_out(world, tmp_path, capsys, monkeypatch):  # noqa: F811
    from shiftlead import cli

    state, _ = _switching(world, tmp_path, monkeypatch, ["build-review", "td"])
    assert "ao-shiftlead-designer-ao" not in [s["id"] for s in state["sessions"]]  # sat out at the start
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []
    assert cli.main(["team", "flow", "ao-grind", "td", "--apply"]) == 0
    assert "designer-ao: starts under td" in capsys.readouterr().out
    made = [p for m, p in state["calls"] if m == "create"]
    assert [p["name"] for p in made] == ["designer-ao"] and made[0]["controllers"] == ["ao-shiftlead-orc-ao"]
    assert made[0]["lane"] == ["design-first", "owner:designer"]


def test_apply_leaves_a_persons_session_and_an_unreachable_member_and_says_so(
    world,  # noqa: F811
    tmp_path,
    capsys,
    monkeypatch,  # noqa: F811
):
    from shiftlead import cli

    state, _ = _switching(world, tmp_path, monkeypatch, ["td", "build-review"])
    for s in state["sessions"]:
        if s["name"] == "designer-ao":
            s["unattended"] = False  # a person's own session in the team (§4.9 *A person in the team*)
        if s["name"] == "grind-2":
            s.update(state="unreachable", host="devenv")
    assert cli.main(["--json", "team", "flow", "ao-grind", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["apply"]["applied"] == []  # td is current: nothing differs
    assert cli.main(["--json", "team", "flow", "ao-grind", "build-review", "--apply"]) == 0
    got = json.loads(capsys.readouterr().out)["apply"]
    assert [d["name"] for d in got["applied"]] == ["grind-1"]
    skipped = {d["name"]: d["line"] for d in got["skipped"]}
    assert skipped == {
        "designer-ao": "designer-ao: sits out under build-review — a person's session, left running: close it yourself",
        "grind-2": "grind-2: devenv is not answering — applied to the others",
    }
    assert not [p for m, p in state["calls"] if m == "relaunch" and p["id"] != "ao-shiftlead-grind-1"]


def test_a_flow_named_is_written_and_nothing_more(world, tmp_path, capsys, monkeypatch):  # noqa: F811
    """§4.7, §4.9c *A switch takes one gate, Apply* (TD-356, TD-359): `ao team flow <team> <flow>`
    writes the setting, relaunches nothing, and prints the differences as the bare form does, ending
    with the hint; picking the old flow back reads nothing changed."""
    from shiftlead import cli

    state, _ = _switching(world, tmp_path, monkeypatch, ["td", "build-review"])
    assert cli.main(["team", "flow", "ao-grind", "build-review"]) == 0
    out = capsys.readouterr().out
    assert state["teams"]["ao-grind"] == {"flow": "build-review"}
    assert not [m for m, _ in state["calls"] if m in ("relaunch", "create")]
    assert "ao-grind: flow set to build-review" in out
    assert "flow changed — Apply (ao team flow ao-grind --apply):" in out
    assert "  designer-ao: sits out under build-review" in out
    assert cli.main(["--json", "team", "flow", "ao-grind", "td"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["flow"] == "td" and got["differences"] == [] and "apply" not in got
    assert cli.main(["team", "flow", "ao-grind", "td"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "nothing running differs"
    assert not [m for m, _ in state["calls"] if m in ("relaunch", "create")]


def test_a_pick_says_what_add_entrys_feature_now_opens(world, tmp_path, monkeypatch):  # noqa: F811
    """§4.5a team card **Flow** pick, §4.9c item 4: a pick to a flow with no design stage says
    *feature* now opens a techlead; a pick back to `td`, the designer; a pick that leaves it, nothing."""
    from shiftlead import cli, teamrun

    _switching(world, tmp_path, monkeypatch, ["td", "build-review", "build"])
    org = cli._org_here()
    got = teamrun.pick_flow(cli.call_sync, org, "ao-grind", HOST, "build-review")
    assert got["flow"] == "build-review" and got["feature"] == "techlead" and got["differences"]
    assert "stays" not in got  # what stays with a reader is Apply's to say: a pick moves nothing (TD-365)
    org = cli._org_here()
    assert teamrun.pick_flow(cli.call_sync, org, "ao-grind", HOST, "build")["feature"] is None
    assert teamrun.pick_flow(cli.call_sync, cli._org_here(), "ao-grind", HOST, "td")["feature"] == "designer"


def test_a_switch_says_which_prs_stay_with_their_reader(world, tmp_path, capsys, monkeypatch):  # noqa: F811
    """§4.9c *What a switch leaves alone*: a PR already asked of the techlead stays its, and the
    apply says so from the seat's `prs_waiting.asks` (TD-333) — the sender by its name, an address
    this home does not list as given."""
    from shiftlead import cli

    state, _ = _switching(world, tmp_path, monkeypatch, ["td", "build"])
    tl = next(s for s in state["sessions"] if s["name"] == "techlead-ao")
    tl["prs_waiting"] = {
        "n": 3,
        "oldest": "2026-10-05T09:00:00Z",
        "asks": [
            {"from": "ao-shiftlead-grind-1", "pr": 1020},
            {"from": "ao-x-w@devenv", "pr": 1021},
            {"from": f"ao-shiftlead-grind-2@{HOST}", "pr": 1022},
        ],
    }
    assert cli.main(["team", "flow", "ao-grind", "build", "--apply"]) == 0
    out = capsys.readouterr().out
    assert "  grind-1's PR #1020 stays with techlead-ao" in out
    assert "  ao-x-w@devenv's PR #1021 stays with techlead-ao" in out
    assert "  grind-2's PR #1022 stays with techlead-ao" in out
    assert cli.main(["--json", "team", "flow", "ao-grind", "--apply"]) == 0
    got = json.loads(capsys.readouterr().out)["apply"]
    assert got["stays"][0] == {
        "from": "ao-shiftlead-grind-1",
        "pr": 1020,
        "reader": "techlead-ao",
        "line": "grind-1's PR #1020 stays with techlead-ao",
    }
    # a team with no ask waiting says nothing of it
    tl["prs_waiting"] = None
    assert cli.main(["team", "flow", "ao-grind", "--apply"]) == 0
    assert "stays with" not in capsys.readouterr().out


def test_ao_team_list_says_flow_changed_while_the_records_differ(world, tmp_path, capsys, monkeypatch):  # noqa: F811
    """§4.9c *Switching*: a client reading a live team compares it with its current flow — a pick
    written and not yet applied (the page's, before slice 4b applies at once) reads *flow changed*."""
    from shiftlead import cli

    _switching(world, tmp_path, monkeypatch, ["td", "build-review"])
    assert cli.main(["--json", "team", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["teams"][0]["differences"] == []
    cli.call_sync("set_settings", teams={"ao-grind": {"flow": "build-review"}})  # written, not applied
    assert cli.main(["--json", "team", "list"]) == 0
    row = next(r for r in json.loads(capsys.readouterr().out)["teams"] if r["name"] == "ao-grind")
    assert {(d["name"], d["act"]) for d in row["differences"]} == {
        ("designer-ao", "sit_out"),
        ("grind-1", "relaunch"),
        ("grind-2", "relaunch"),
    }
    assert cli.main(["team", "list"]) == 0
    out = capsys.readouterr().out
    assert "flow changed — Apply (ao team flow ao-grind --apply):" in out
    assert "designer-ao: sits out under build-review" in out


# ── role directories (TD-313 slice 2) ───────────────────────────────────────────────────────────────


def define_role(base: Path, name: str, yml: str = "kind: worker\n", template: str | None = "# {lane}\n") -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "role.yml").write_text(yml)
    if template is not None:
        (d / "template.md").write_text(template)
    return d


@pytest.mark.unit
def test_a_role_directory_defines_a_role_the_orgs_over_a_repos_whole(tmp_path, monkeypatch):
    # §4.9c *Where flows and roles live*: `role.yml` (the role keys and `kind`) and `template.md`, the
    # org's `~/.shiftlead/roles/<name>/` over a repo's `.shiftlead/roles/<name>/`, never merged by key
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    root = tmp_path / "r"
    repo_role = define_role(root / ".shiftlead" / "roles", "security", "kind: seat\nicon: eye\nlane: [a]\n")
    cfg = repoconfig.load(root)
    sec = repoconfig.resolve_role(cfg, "security")
    assert (sec.kind, sec.icon, sec.lane, sec.source, sec.defined) == ("seat", "eye", ["a"], "repo role", repo_role)
    assert "security" in repoconfig.role_names(cfg)
    org_role = define_role(
        repoconfig.org_roles_dir(),
        "security",
        "icon: shield\nlabel: security\nprofile: grind\n",
        "sec: {lane}\n{repo}\n",
    )
    sec = repoconfig.resolve_role(cfg, "security")
    assert (sec.kind, sec.icon, sec.lane, sec.display, sec.profile) == ("worker", "shield", [], "security", "grind")
    assert sec.source == "org role" and sec.defined == org_role  # whole: the repo's `kind` and `lane` gone
    # its template is the brief, the repo's slots filled as a preset's; an overlay still lays over it per key
    text, made = sec.compose(["TD-1"])
    assert text == "sec: TD-1\nnone\n" and made["base"] == str(org_role / "template.md")
    (root / "s.md").write_text("the repo's security words\n")
    (root / ".shiftlead.yml").write_text("roles:\n  security: {brief: s.md, lane: [b]}\n")
    sec = repoconfig.resolve_role(repoconfig.load(root), "security", {"security": {"profile": "fable"}})
    assert sec.source == "org role + org + repo" and sec.profile == "fable"
    assert sec.brief_text() == "sec: b\nthe repo's security words\n"
    rows = {(r["name"], r["source"]): r for r in repoconfig.visible([root])}
    assert rows[("security", str(org_role))]["usable"]
    assert "the org's role security" in rows[("security", str(repo_role))]["shadowed"]


@pytest.mark.unit
def test_a_role_directory_that_is_not_whole_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    base = repoconfig.org_roles_dir()
    cfg = cfg_with(tmp_path)
    for yml, template, why in (
        ("brief: x.md\n", "t\n", "`brief:` is not a defined role's"),
        ("kind: boss\n", "t\n", "kind 'boss' is not a kind"),
        ("icon: rocket\n", "t\n", "icon: unknown icon 'rocket'"),
        ("- a\n", "t\n", "the top level must be a mapping"),
        ("kind: worker\n", None, "no template.md"),
    ):
        d = define_role(base, "odd", yml, template)
        with pytest.raises(ValueError, match=why):
            repoconfig.resolve_role(cfg, "odd")
        assert not {r["name"]: r for r in repoconfig.visible()}["odd"]["usable"]
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
    # a directory taking a preset's name is never read, and is listed as refused
    define_role(base, "grinder", "kind: seat\n")
    assert repoconfig.resolve_role(cfg, "grinder").kind == "worker"
    assert "a preset's name" in repoconfig.visible()[0]["problems"][0]
    # a manager on call takes `template_on_call.md`; without one it is a standing manager only
    d = define_role(base, "boss", "kind: manager\n", "standing\n")
    boss = repoconfig.resolve_role(cfg, "boss")
    assert boss.brief_text() == "standing\n"
    with pytest.raises(ValueError, match="standing manager only"):
        boss.compose(on_call=True)
    (d / "template_on_call.md").write_text("on call\n")
    assert boss.compose(on_call=True)[0] == "on call\n"


@pytest.mark.unit
def test_an_org_flow_uses_an_org_role_and_a_node_team_cannot(tmp_path, monkeypatch):
    # TD-313's *Done when*, its first half: a role directory under `~/.shiftlead/roles/` is used by an
    # org flow with no other file changed — and, on a node, the role is the home's (*security is an org role*)
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    d = flowdefs.org_dir() / "sweep"
    d.mkdir(parents=True)
    (d / "flow.yml").write_text("stages:\n  - {name: look, role: security, lane: [free], brief: look.md}\n")
    (d / "look.md").write_text("look\n")
    assert "unknown role 'security'" in flowdefs.load("sweep", cfg_with(tmp_path)).problems[0]
    define_role(repoconfig.org_roles_dir(), "security", "kind: worker\nlane: [free]\n", "sec {lane}\n{stage}\n")
    sweep = flowdefs.load("sweep", cfg_with(tmp_path))
    assert sweep.usable, sweep.problems
    text, _ = repoconfig.resolve_role(cfg_with(tmp_path), "security").compose(flow=flowdefs.under(sweep, "security"))
    assert text == "sec free\nlook\n"
    assert flowdefs.unfollowable(sweep, {"security"}, techlead=False, held=()) == []
    why = flowdefs.unfollowable(sweep, {"security"}, techlead=False, held=(), team="cm-grind", node="contractmatch")
    assert "security is an org role" in why
    # a seat where a stage gives a lane is not usable, as for a preset
    define_role(repoconfig.org_roles_dir(), "security", "kind: seat\n", "sec\n")
    assert "names a worker, and 'security' is a seat" in " ".join(flowdefs.load("sweep", cfg_with(tmp_path)).problems)


def test_a_node_team_member_naming_an_org_role_is_refused_at_its_start(world, tmp_path):  # noqa: F811
    # §4.9c *An org flow or role is not usable by a team on a node*: a member's role, not only a flow's
    # stage — its brief would be the home's `~/.shiftlead/roles/`, which the node never reads
    define_role(repoconfig.org_roles_dir(), "security", "kind: worker\n", "sec {lane}\n")
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["projects"]["ao"]["repos"]["shiftlead"]["contractmatch"] = "/srv/cm/shiftlead"
    doc["teams"]["ao-grind"]["members"].append({"role": "security", "name": "sec", "home": "shiftlead"})
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    org = orgmod.load()
    teams.plan(org, "ao-grind", HOST)  # on the home, the org's role is the team's to use
    org = _with(tmp_path, host="contractmatch")
    asked: list[list[str]] = []

    def files(host: str, directory: str, paths: list[str]) -> dict[str, str | None]:
        asked.append(paths)
        return dict.fromkeys(paths)

    with pytest.raises(teams.TeamError, match="sec: security is an org role, and ao-grind runs on contractmatch"):
        teams.plan(org, "ao-grind", HOST, files=files)
    assert asked  # the members before it were read on the node; the refusal is the org role's alone


def test_a_hunt_flow_in_the_orgs_directory_starts_its_members_from_it(world, tmp_path):  # noqa: F811
    # TD-313's *Done when*, its second half: a `hunt` flow in the org's directory starts a hunter and
    # a grinder with their lanes and briefs from it, and an org role directory's member beside them
    d = flowdefs.org_dir() / "hunt"
    d.mkdir(parents=True)
    stages = [
        {"name": "find", "role": "hunter", "lane": ["free"], "brief": "find.md"},
        {"name": "build", "role": "grinder", "lane": ["free-pick"], "brief": "build.md"},
        {"name": "look", "role": "security", "lane": ["free"], "brief": "look.md"},
    ]
    (d / "flow.yml").write_text(yaml.safe_dump({"stages": stages}))
    for f in ("find", "build", "look"):
        (d / f"{f}.md").write_text(f"the org's {f} words\n")
    define_role(repoconfig.org_roles_dir(), "security", "kind: worker\nlane: [free]\n", "security: {lane}\n{stage}\n")
    doc = _team_doc(tmp_path)
    t = doc["teams"]["ao-grind"]
    t["flows"] = ["hunt"]
    for m in t["members"]:
        m.pop("lane", None)
    t["members"].append({"role": "security", "name": "security-ao", "home": "shiftlead"})
    p = teams.plan(_write(tmp_path, doc), "ao-grind", HOST)
    assert p.flow == "hunt"
    by = {x.role: x for x in p.members}
    assert by["grinder"].lane == ["free-pick"] and "the org's build words" in by["grinder"].prompt
    assert by["hunter"].lane == ["free"] and "the org's find words" in by["hunter"].prompt
    assert by["security"].prompt == "security: free\nthe org's look words\n"


def test_ao_org_lists_every_role_directory_and_check_fails_on_one_not_whole(world, tmp_path, capsys):  # noqa: F811
    """§4.9c: `ao org` says a repo's role directory the org's shadows, as a shadowed team; `ao org
    check` fails on one that is not whole or takes a preset's name."""
    from shiftlead import cli

    root = tmp_path / "shiftlead"
    define_role(root / ".shiftlead" / "roles", "security")
    define_role(repoconfig.org_roles_dir(), "security")
    assert cli.main(["org"]) == 0
    out = capsys.readouterr().out
    assert f"role security  usable  [{repoconfig.org_roles_dir() / 'security'}]" in out
    assert "role security  not read: the org's role security" in out
    assert cli.main(["org", "check"]) == 0
    capsys.readouterr()
    define_role(root / ".shiftlead" / "roles", "hunter")
    assert cli.main(["org", "check"]) == 1
    assert "lacking: role hunter (" in capsys.readouterr().out
    shutil.rmtree(root / ".shiftlead" / "roles" / "hunter")
    # a directory with no role.yml is not whole, and a broken one leaves every other role listed
    (root / ".shiftlead" / "roles" / "stray").mkdir()
    (repoconfig.org_roles_dir() / "security" / "template.md").unlink()
    assert cli.main(["org", "check"]) == 1
    out = capsys.readouterr().out
    assert "lacking: role stray (" in out and "no role.yml" in out and "lacking: role security (" in out
    names = [r.name for r in repoconfig.roles(repoconfig.load(root))]
    assert "security" not in names and "grinder" in names
    assert cli.main(["roles"]) == 0
    capsys.readouterr()
    # org.yml's `roles:` key naming no definition is named, since the org file cannot see the repos
    (repoconfig.org_roles_dir() / "security" / "template.md").write_text("x\n")
    shutil.rmtree(root / ".shiftlead" / "roles" / "stray")
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc.setdefault("roles", {})["grnder"] = {"lane": ["free-pick"]}
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))
    assert cli.main(["org", "check"]) == 1
    assert "roles.grnder — unknown role" in capsys.readouterr().out


# ── review stages for any seat: path sets, the staffing, the chain (TD-315 slice 3) ──────────────────


@pytest.mark.unit
def test_held_may_be_a_mapping_of_named_path_sets(tmp_path):
    # §4.9c *A repo names its path sets*: a list as before, or named sets — `held` then their union
    cfg = cfg_with(tmp_path, "held:\n  core: [src/sessionorc/**, docs/briefs/**]\n  ui: src/shiftlead/ui/**\n")
    assert cfg.held_sets == {"core": ["src/sessionorc/**", "docs/briefs/**"], "ui": ["src/shiftlead/ui/**"]}
    assert cfg.held == ["src/sessionorc/**", "docs/briefs/**", "src/shiftlead/ui/**"]
    assert repoconfig.held_for(cfg, "ui") == ["src/shiftlead/ui/**"] and repoconfig.held_for(cfg) == cfg.held
    assert repoconfig.held_for(cfg, "docs") is None
    assert cfg_with(tmp_path, "held: [a/**]\n").held_sets is None
    for text, why in (
        ("held: {UI: [a]}\n", "a word of lower-case letters"),
        ("held: {ui: []}\n", "names no path"),
        ("held: {}\n", "names no path set"),
    ):
        with pytest.raises(ValueError, match=why):
            cfg_with(tmp_path, text)


@pytest.mark.unit
def test_a_review_stage_of_any_seat_is_staffed_by_one_seat_on_asks(tmp_path):
    # §4.9c *A review stage names any seat role*: the techlead seat for `techlead`, else exactly one
    # `seats:` entry of the role on `asks`; a stage's `held:` names a set its repo defines
    stages = [
        {"name": "build", "role": "grinder", "lane": ["free-pick"], "brief": "b.md"},
        {"name": "ui-review", "role": "auditor", "brief": "b.md", "held": "ui"},
        {"name": "review", "role": "techlead", "brief": "b.md", "held": "core"},
    ]
    repo_flow(tmp_path, "td-ui", stages, {"b.md": "x\n"})
    cfg = cfg_with(tmp_path, "held: {core: [src/sessionorc/**], ui: [src/shiftlead/ui/**]}\n")
    flow = flowdefs.load("td-ui", cfg)
    assert flow.usable, flow.problems
    assert [s.held for s in flow.review_stages] == ["ui", "core"]

    def why(**kw):
        args = {"techlead": True, "held": cfg.held, "seats": [("auditor", "asks")], "held_sets": cfg.held_sets}
        return flowdefs.unfollowable(flow, {"grinder"}, repo="shiftlead", **(args | kw))

    assert why() == []
    assert why(seats=[]) == ["no seat of role auditor — add one under seats: with trigger: asks"]
    assert why(seats=[("auditor", "prs")]) == [
        "the seat of role auditor is on trigger prs — a review seat's trigger is asks"
    ]
    assert why(seats=[("auditor", "asks")] * 2) == ["2 seats of role auditor on asks — a review stage has one reader"]
    assert why(techlead=False) == ["no techlead seat — add `techlead:` to the team"]
    assert why(held_sets={"core": ["x"]}) == ["nothing held: no path set ui in shiftlead"]


def test_the_compile_writes_the_chain_in_the_flows_order(world, tmp_path):  # noqa: F811
    # §4.9c *The record carries the chain*: one link per review stage, its seat's name and its set's
    # paths; a flow whose review is the techlead on every held path keeps the older shape
    root = tmp_path / "shiftlead"
    (root / ".shiftlead.yml").write_text("held: {core: [src/sessionorc/**], ui: [src/shiftlead/ui/**]}\n")
    stages = [
        {"name": "build", "role": "grinder", "lane": ["free-pick"], "brief": "b.md"},
        {"name": "ui-review", "role": "auditor", "brief": "b.md", "held": "ui"},
        {"name": "review", "role": "techlead", "brief": "b.md", "held": "core"},
    ]
    repo_flow(root, "td-ui", stages, {"b.md": "x\n"})
    doc = _team_doc(tmp_path)
    t = doc["teams"]["ao-grind"]
    t.update(flows=["td-ui"], techlead={"name": "techlead-ao", "home": "shiftlead"})
    t["seats"] = [{"name": "ui-reader-ao", "role": "auditor", "trigger": "asks", "home": "shiftlead"}]
    for m in t["members"]:
        m.pop("lane", None)
    p = teams.plan(_write(tmp_path, doc), "ao-grind", HOST)
    chain = {
        "chain": [
            {"stage": "ui-review", "reader": "ui-reader-ao", "held": ["src/shiftlead/ui/**"]},
            {"stage": "review", "reader": "techlead-ao", "held": ["src/sessionorc/**"]},
        ],
        "bound": teams.REVIEW_BOUND,
    }
    grinder = next(x for x in p.members if x.role == "grinder")
    assert grinder.review == chain
    from sessionorc.models import normalize_review

    assert normalize_review(chain) == chain  # the host agent takes it as the compile writes it
    assert teams.chain_line(chain) == "ui-reader-ao on src/shiftlead/ui/**, then techlead-ao on src/sessionorc/**"
    # §4.9c *The words* (TD-315 slice 5): `{flow}` draws every review stage with its seat and its paths
    assert grinder.prompt_from["slots"]["{flow}"]["text"] == (
        f"td-ui: **build** (grinder) → ui-review (ui-reader-ao, on src/shiftlead/ui/**) → review "
        f"({p.techlead_id}, on src/sessionorc/**) → you, through {p.techlead_id}."
    )
    # the same seat edited out: not followable, in the shared words
    t["seats"] = []
    with pytest.raises(teams.TeamError, match="td-ui cannot be followed by ao-grind: no seat of role auditor"):
        teams.plan(_write(tmp_path, doc), "ao-grind", HOST)


def test_a_roles_profile_changed_reads_a_difference_and_apply_relaunches_with_it(
    world,  # noqa: F811
    tmp_path,
    capsys,
    monkeypatch,  # noqa: F811
):
    """TD-619 (§4.9c *Switching*): a role's `profile:` edited in `org.yml` is a difference on every live
    member it resolves for — the team reads **definition changed** where nothing else differs, and
    `ao team flow` prints *profile <old> → <new> (next restart)*; Apply hands the new profile, and the
    home's `relaunch` mark, carrying it, is what the member runs next, so Apply is not offered again."""
    from shiftlead import cli, teamrun

    state, doc = _switching(world, tmp_path, monkeypatch, ["td", "build-review"])
    doc["roles"]["grinder"]["profile"] = "repo-grind"
    _write(tmp_path, doc)
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    diffs = json.loads(capsys.readouterr().out)["differences"]
    assert {d["name"]: d["what"] for d in diffs} == {
        n: ["profile org-grind → repo-grind"] for n in ("grind-1", "grind-2")
    }
    assert all(d["act"] == "relaunch" and d["definition"] for d in diffs)
    assert teamrun.definition_changed(diffs, "td")
    assert cli.main(["team", "flow", "ao-grind"]) == 0
    out = capsys.readouterr().out
    assert "definition changed — Apply (ao team flow ao-grind --apply):" in out
    assert "  grind-1: profile org-grind → repo-grind (next restart)" in out
    assert cli.main(["--json", "team", "flow", "ao-grind", "--apply"]) == 0
    applied = json.loads(capsys.readouterr().out)["apply"]["applied"]
    assert [d["line"] for d in applied][0] == "grind-1: profile org-grind → repo-grind (next restart)"
    handed = {p["id"]: p["launch"] for m, p in state["calls"] if m == "relaunch"}
    assert {k: v["profile"] for k, v in handed.items()} == dict.fromkeys(
        ("ao-shiftlead-grind-1", "ao-shiftlead-grind-2"), "repo-grind"
    )
    # the home marks the record with what it runs next; its own `profile` stays the running one
    for s in state["sessions"]:
        if s["id"] in handed:
            s["relaunch"] = {
                "at": "2026-10-13T00:00:00Z",
                "lane": s["lane"],
                "review": s["review"],
                "profile": "repo-grind",
            }
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []


def test_a_profile_beside_another_difference_reads_flow_changed_and_a_members_own_profile_wins(
    world,  # noqa: F811
    tmp_path,
    capsys,
    monkeypatch,  # noqa: F811
):
    """A profile difference beside a lane's is one relaunch line under **flow changed**; a member whose
    own `profile:` still matches its record is no difference, whatever its role's now says; an
    interactive member is compared on nothing (§4.9c *Switching*, TD-619)."""
    from shiftlead import cli, teamrun

    state, doc = _switching(world, tmp_path, monkeypatch, ["td", "build-review"])
    doc["roles"]["grinder"]["profile"] = "repo-grind"
    doc["roles"]["hunter"] = {"profile": "member-grind"}
    grind = next(m for m in doc["teams"]["ao-grind"]["members"] if m["role"] == "grinder")
    grind["profile"] = "org-grind"  # the members' own: what their records run
    _write(tmp_path, doc)
    hunt = next(s for s in state["sessions"] if s["name"] == "hunt")
    hunt["lane"] = ["other"]
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    diffs = json.loads(capsys.readouterr().out)["differences"]
    (d,) = diffs
    assert d["name"] == "hunt" and d["what"] == ["lane other → ui", "profile default → member-grind"]
    assert d["line"] == "hunt: relaunched — lane other → ui; profile default → member-grind"
    assert not d["definition"] and not teamrun.definition_changed(diffs, "td")
    hunt["unattended"] = False  # a person's session: its lane, brief and profile are theirs
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []


def test_a_closed_seat_whose_roles_profile_changed_reads_a_difference_and_apply_relaunches_it(
    world,  # noqa: F811
    tmp_path,
    capsys,
    monkeypatch,  # noqa: F811
):
    """A seat is compared on its profile closed between fills (§4.9c *Switching*, TD-619): its next fill
    replays its record, so the techlead's role's new profile is offered there and Apply relaunches the
    closed record; a closed member that is not a seat is still the next Start's, compared on nothing."""
    from shiftlead import cli

    state, doc = _switching(world, tmp_path, monkeypatch, ["td", "build-review"])
    doc["roles"]["techlead"] = {"profile": "repo-grind"}
    doc["roles"]["grinder"]["profile"] = "repo-grind"
    _write(tmp_path, doc)
    for s in state["sessions"]:
        if s["name"] in ("techlead-ao", "grind-2"):
            s["state"] = "closed"
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    diffs = json.loads(capsys.readouterr().out)["differences"]
    assert {d["name"]: d["what"] for d in diffs} == {
        "techlead-ao": ["profile default → repo-grind"],
        "grind-1": ["profile org-grind → repo-grind"],
    }
    assert cli.main(["--json", "team", "flow", "ao-grind", "--apply"]) == 0
    handed = {p["id"]: p["launch"] for m, p in state["calls"] if m == "relaunch"}
    assert handed["ao-shiftlead-techlead-ao"]["profile"] == "repo-grind"
    assert "ao-shiftlead-grind-2" not in handed


def test_a_team_with_no_flows_is_compared_on_its_profiles_too(world, tmp_path, capsys, monkeypatch):  # noqa: F811
    """A team that runs no flow is compared on its seats and on every live member's profile (§4.9c
    *Switching*, TD-619: the profile is the definition's, not a flow's), and reads **definition changed**."""
    from shiftlead import cli, teamrun

    _, state = world
    org = orgmod.load()
    teamrun.start(cli.call_sync, org, "ao-grind", HOST)
    doc = _team_doc(tmp_path)
    doc["roles"]["grinder"]["profile"] = "repo-grind"
    _write(tmp_path, doc)
    fake = cli.call_sync

    def call(method, **params):
        if method == "relaunch":
            state["calls"].append((method, params))
            return next(s for s in state["sessions"] if s["id"] == params["id"])
        return fake(method, **params)

    monkeypatch.setattr(cli, "call_sync", call)
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    diffs = json.loads(capsys.readouterr().out)["differences"]
    assert sorted(d["name"] for d in diffs) == ["grind-1", "grind-2"]
    assert teamrun.definition_changed(diffs, None)
    assert cli.main(["--json", "team", "flow", "ao-grind", "--apply"]) == 0
    handed = [p["launch"]["profile"] for m, p in state["calls"] if m == "relaunch"]
    assert handed == ["repo-grind", "repo-grind"]


# ── a member renamed or removed in the definition (§4.9, TD-703, built by TD-706 slice 1) ─────────


def _renamed(world, tmp_path, monkeypatch):  # noqa: F811
    """ao-grind started with no flows, its records carrying the `role` and `created` the home writes;
    then its grinders renamed (`grind` → `mill`) and its hunter dropped from the definition."""
    from shiftlead import cli, teamrun

    _, state = world
    plan, _ = teamrun.start(cli.call_sync, orgmod.load(), "ao-grind", HOST)
    for i, (x, rec) in enumerate(zip(plan.launches, state["sessions"], strict=True)):
        rec.update(role=x.role, created=f"2026-10-14T00:00:0{i}Z")
    doc = _team_doc(tmp_path)
    t = doc["teams"]["ao-grind"]
    t["members"] = [dict(t["members"][0], name="mill")]
    _write(tmp_path, doc)
    fake = cli.call_sync

    def call(method, **params):
        if method == "relaunch":
            state["calls"].append((method, params))
            return next(s for s in state["sessions"] if s["id"] == params["id"])
        return fake(method, **params)

    monkeypatch.setattr(cli, "call_sync", call)
    state["calls"].clear()
    return state


def test_a_renamed_member_reads_renamed_and_a_dropped_one_removed_and_apply_creates_neither(
    world,  # noqa: F811
    tmp_path,
    capsys,
    monkeypatch,  # noqa: F811
):
    """§4.9 *A member renamed or removed in the definition*: the records the definition no longer names
    are paired with the names no record carries, within a role, in order — each pair *renamed*, an
    orphan left over *removed from the definition* — the team reads **definition changed**, and the
    newcomer is no `start` of its own, so Apply never creates it beside the old record (until the
    home's half lands it says so and touches nothing)."""
    from shiftlead import cli, teamrun

    state = _renamed(world, tmp_path, monkeypatch)
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    diffs = json.loads(capsys.readouterr().out)["differences"]
    assert [d["line"] for d in diffs] == [
        "grind-1 → mill-1: renamed",
        "grind-2 → mill-2: renamed",
        "hunt: removed from the definition",
    ]
    assert [d.get("to") for d in diffs] == ["mill-1", "mill-2", None]
    assert all(d["definition"] for d in diffs) and teamrun.definition_changed(diffs, None)
    assert cli.main(["team", "list"]) == 0
    out = capsys.readouterr().out
    assert "definition changed — Apply (ao team flow ao-grind --apply):" in out
    assert "    grind-1 → mill-1: renamed" in out and "    hunt: removed from the definition" in out
    assert cli.main(["--json", "team", "flow", "ao-grind", "--apply"]) == 0
    applied = json.loads(capsys.readouterr().out)["apply"]
    assert applied["applied"] == [] and len(applied["skipped"]) == 3
    assert applied["skipped"][0]["line"].startswith("grind-1 → mill-1: renamed — not applied yet")
    assert not [m for m, _ in state["calls"] if m in ("create", "relaunch")]


def test_a_stopped_team_reads_its_renames_and_an_applied_orphan_is_no_difference(
    world,  # noqa: F811
    tmp_path,
    capsys,
    monkeypatch,  # noqa: F811
):
    """A stopped team is read for renames and removals alone (rule 8 replays its ended records); an
    orphan whose `relaunch` mark already carries a newcomer's `name` is that newcomer's — neither is a
    difference; a superseded record and a sat-out one are never orphans."""
    from shiftlead import cli

    state = _renamed(world, tmp_path, monkeypatch)
    for s in state["sessions"]:
        s["state"] = "closed"
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    lines = [d["line"] for d in json.loads(capsys.readouterr().out)["differences"]]
    assert lines == ["grind-1 → mill-1: renamed", "grind-2 → mill-2: renamed", "hunt: removed from the definition"]
    by = {s["name"]: s for s in state["sessions"]}
    by["grind-1"]["relaunch"] = {"at": "x", "name": "mill-1"}  # applied: held until its replay runs
    by["grind-2"]["superseded_by"] = "ao-shiftlead-other"
    by["hunt"]["closed_for"] = {"why": "sit_out"}
    assert cli.main(["--json", "team", "flow", "ao-grind"]) == 0
    assert json.loads(capsys.readouterr().out)["differences"] == []
    assert cli.main(["--json", "team", "flow", "ao-grind", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["apply"]["skipped"] == []


def test_orphans_pair_by_created_within_a_role_and_a_persons_session_is_never_one(world, tmp_path):  # noqa: F811
    """`teamrun.renames`: the orphans by `created`, the newcomers in the definition's order, paired within
    one role; an orphan of a role with no newcomer is a removal, and a newcomer no orphan matches (the
    designer) is left to the start it already is; a person's session is never an orphan, whatever its name."""
    from shiftlead import cli, teamrun

    _, state = world
    doc = _team_doc(tmp_path)
    doc["teams"]["ao-grind"]["members"] = [
        {"role": "grinder", "count": 2, "name": "mill", "home": "shiftlead"},
        {"role": "designer", "name": "design", "home": "shiftlead"},
    ]
    org = _write(tmp_path, doc)
    plan = teams.plan(org, "ao-grind", HOST, files=teamrun.files_via(cli.call_sync))
    rec = lambda name, role, created, **kw: {  # noqa: E731
        "id": f"ao-{name}", "name": name, "role": role, "created": created, "state": "closed",
        "team": "ao-grind", "unattended": True, **kw,
    }  # fmt: skip
    sessions = [
        rec("orc-ao", "manager", "2026-10-14T00:00:00Z"),
        rec("grind-b", "grinder", "2026-10-14T00:00:01Z"),
        rec("grind-a", "grinder", "2026-10-14T00:00:02Z"),
        rec("hunt", "hunter", "2026-10-14T00:00:03Z"),
        rec("paul-ao", "", "2026-10-14T00:00:04Z", unattended=False),
    ]
    pairs, removals = teamrun.renames(plan, sessions)
    assert [(r["name"], x.name) for r, x in pairs] == [("grind-b", "mill-1"), ("grind-a", "mill-2")]
    assert [r["name"] for r in removals] == ["hunt"]
    lines = [d.line(None) for d in teamrun.differences(plan, sessions)]
    assert lines == ["grind-b → mill-1: renamed", "grind-a → mill-2: renamed", "hunt: removed from the definition"]
