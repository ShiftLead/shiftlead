"""TD-2047, design §4.9c *A flow is usable only when it flows*: the format-3 reader and check, its built-ins and
standard briefs, `ao flow check` and `ao flow list`, and that nothing a running team reads changes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from shiftlead import cli, flow3, flowdefs, repoconfig


def flow(**top) -> dict:
    """A small good flow: Build (takes any) → Review → merge."""
    return {
        "format": 3,
        "name": "f",
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
        **top,
    }


def problems(doc, **kw) -> str:
    return "\n".join(flow3.check(doc, **kw).problems)


def edit(stage: int, **keys) -> dict:
    doc = flow()
    doc["stages"][stage].update(keys)
    return doc


def test_a_good_flow_passes_and_says_what_goes_to_the_person():
    got = flow3.check(flow())
    assert got.usable, got.problems
    assert any("Build: goes to the person on" in i for i in got.info)
    assert any("after 25 moves" in i for i in got.info)


@pytest.mark.parametrize("name", flow3.BUILTIN)
def test_each_format3_builtin_passes(name):
    assert flow3.check_file(flow3.PACKAGE_DIR / name / flow3.FILE).usable


@pytest.mark.parametrize(
    "doc, words",
    [
        (
            edit(0, **{"work-pushed": "nowhere"}),
            "Build: `work-pushed` goes to `nowhere`, which is not a stage (rule 1)",
        ),
        (edit(0, other="merge"), "Build: `other`: only `work-pushed` or `ship` can go to merge (rule 1)"),
        (
            flow(audits=[{"name": "Sweep", "model": "sonnet", "every": "1 days", "brief": "docs"}])
            | {"stages": edit(0, **{"work-pushed": "sweep"})["stages"]},
            "Build: `work-pushed` goes to the audit `sweep`",
        ),
        (edit(0, ship="review"), "Build: `ship` is not an outcome of a build stage"),
        (edit(0, **{"closed-unmerged": "review"}), "Build: unknown key `closed-unmerged`"),  # a job's outcome alone
        (edit(1, **{"closed-unmerged": "merge"}), "Review: unknown key `closed-unmerged`"),
        (edit(1, **{"changes-wanted": "build"}, ship="build"), "a loop through it has no limit"),
        (edit(0, **{"work-pushed": "build", "other": "build"}), "(rule 3)"),
        (edit(0, **{"work-pushed": "done"}), "Build: `work-pushed: done` is not a destination"),
        (edit(0, takes=None), "new `design-first` entries need exactly one stage"),
        (edit(1, takes="other"), "a review stage cannot take new entries"),
        (edit(1, name="Build"), "the name is already used"),
        (edit(1, name="Merge"), "a reserved word"),
        (edit(0, model="gpt"), "Build: model must be one of"),
        (edit(0, does="merge"), "merge is a destination, not a stage"),
        (edit(0, does=["build", "review"]), "a stage does one kind of work"),
        (flow(**{"max-moves": 1}), "`max-moves` is a whole number, 2 or more (rule 9)"),
        (flow(audits=[{"name": "A", "model": "sonnet", "every": "often", "brief": "docs"}]), "`every` is written like"),
        (flow(audits=[{"name": "A", "model": "sonnet", "every": "1 days"}]), "an audit needs a `brief:`"),
        (flow(audits=[{"model": "sonnet"}]), "audit 1 has no name"),
        (edit(0, brief="review"), "the standard review brief, not a build one"),
        (edit(0, brief="nobody"), "`brief: nobody` is no standard brief"),
    ],
)
def test_each_rule_refuses_naming_the_stage_and_outcome(doc, words):
    assert words in problems(doc)


@pytest.mark.parametrize(
    "doc, words",
    [
        (edit(1, ship={"to": "merge", "refused": "build"}, **{"changes-wanted": "person"}), "(rule 3)"),
        (edit(1, ship={"to": "merge", "refused": "done"}), "`ship.refused: done` is not a destination"),
        (edit(1, ship={"to": "merge", "limit": 2}), "put it on `refused`"),
        (edit(1, ship={"to": "person", "limit": 2}), "a limit sits on a move to a stage"),
        (edit(0, name=3), "stage 1 has no name"),
        (flow(audits=[{"name": "A", "model": "sonnet", "every": "1 hours\n", "brief": "docs"}]), "`every` is written"),
    ],
)
def test_a_refused_move_a_misplaced_limit_and_a_name_that_is_not_text_are_refused(doc, words):
    assert words in problems(doc)


def test_two_stages_taking_one_kind_of_entry_are_refused():
    doc = flow()
    doc["stages"].append({"name": "Other", "does": "build", "model": "opus", "takes": "other", "work-pushed": "review"})
    assert "new `other` entries need exactly one stage that takes them; found 2 (rule 6)" in problems(doc)


def test_the_builtins_are_the_paths_the_design_names():
    def path(name):
        doc = yaml.safe_load((flow3.PACKAGE_DIR / name / flow3.FILE).read_text())
        return [(s["name"], s["does"], s.get("takes"), s.get("only-when")) for s in doc["stages"]], doc.get(
            "audits", []
        )

    wise, audits = path("design-wise")
    assert wise == [
        ("Design", "design", "design-first", None),
        ("First read", "review", None, None),
        ("Second read", "review", None, None),
        ("Fact-check", "review", None, None),
        ("Build", "build", "other", None),
        ("Review", "review", None, None),
        ("Protected read", "review", None, "protected-files"),
    ]
    assert [(a["brief"], a["every"]) for a in audits] == [("docs", "10 merged-pull-requests"), ("tests", "6 hours")]
    assert path("build-review")[0] == [("Build", "build", "any", None), ("Review", "review", None, None)]
    assert path("build")[0] == [("Build", "build", "any", None)]


def test_a_pull_request_with_no_way_out_is_refused():
    """Rule 4: a build whose every move goes round, with limits, never reaches a merge or the person."""
    doc = {
        "format": 3,
        "stages": [
            {
                "name": "Build",
                "does": "build",
                "model": "opus",
                "takes": "any",
                "work-pushed": {"to": "again", "limit": 2},
            },
            {"name": "Again", "does": "build", "model": "opus", "work-pushed": {"to": "build", "limit": 2}},
        ],
    }
    assert "Build: its pull request can never reach a merge or the person (rule 4)" in problems(doc)


def test_a_stage_nothing_reaches_is_refused():
    doc = flow()
    doc["stages"].append({"name": "Lost", "does": "review", "model": "sonnet", "ship": "person"})
    assert "Lost: nothing can reach this stage (rule 8)" in problems(doc)


@pytest.mark.parametrize("key, value", [("support", {"tech-lead": "opus"}), ("flows", [])])
def test_a_stray_top_key_is_refused_by_name(key, value):
    assert f"unknown key at the top: `{key}`" in problems(flow(**{key: value}))


def test_rule_11_says_which_stages_carry_the_independent_review():
    said = flow3.check_file(flow3.PACKAGE_DIR / "build" / flow3.FILE).info
    assert any(i.startswith("Build: merge can be reached with no review") for i in said)
    assert not any("merge can be reached" in i for i in flow3.check(flow()).info)
    only = flow()
    only["stages"][1]["only-when"] = "protected-files"
    assert any("Build: merge can be reached" in i for i in flow3.check(only).info), "a passed only-when is no review"


def test_a_review_on_its_writers_model_warns_and_is_not_refused():
    got = flow3.check(edit(1, model="opus"))
    assert got.usable and any(i.startswith("warning: Review reviews on opus") for i in got.info)


def test_a_merge_destination_needs_the_repos_gate(tmp_path):
    bare = tmp_path / "plain"
    bare.mkdir()
    assert "no pinned agent-cadence" in problems(flow(), repo_root=bare)
    pinned = tmp_path / "pinned"
    (pinned / "docs").mkdir(parents=True)
    (pinned / "docs" / "cadence.toml").write_text(
        '[agent-cadence]\nsource = "https://github.com/ShiftLead/agent-cadence"\nref = "' + "a" * 40 + '"\n'
    )
    assert problems(flow(), repo_root=pinned) == ""
    ask = edit(1, ship="person")
    assert problems(ask, repo_root=bare) == "", "with no merge destination the gate is not needed"


def _own(d: Path, name: str, kind: str | None) -> None:
    (d / "briefs").mkdir(parents=True, exist_ok=True)
    head = f"---\nkind: {kind}\n---\n" if kind else ""
    (d / "briefs" / f"{name}.md").write_text(head + "Do it.\n")


def test_a_briefs_kind_and_where_it_lives(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    d = tmp_path / "repo" / ".shiftlead" / "flows" / "mine"
    _own(d, "sec", "review")
    _own(d, "bare", None)
    assert problems(edit(1, brief="sec"), place="repo", flow_dir=d) == ""
    assert "a review brief, not a build one" in problems(edit(0, brief="sec"), place="repo", flow_dir=d)
    assert "writes no `kind:`" in problems(edit(1, brief="bare"), place="repo", flow_dir=d)
    _own(tmp_path / "home", "orgs", "review")
    assert "one of the org's" in problems(edit(1, brief="orgs"), place="repo", flow_dir=d)
    assert problems(edit(1, brief="orgs"), place="org", flow_dir=tmp_path / "home" / "flows" / "x") == ""


def test_the_standard_briefs_ship_one_per_kind_and_three_for_audits():
    assert sorted(flow3.STANDARD) == ["build", "code", "design", "docs", "review", "tests"]
    for name in flow3.STANDARD:
        assert (flow3.STANDARD_DIR / f"{name}.md").read_text().strip()


def test_a_directory_may_not_take_a_builtins_name(tmp_path):
    d = tmp_path / ".shiftlead" / "flows" / "design-wise"
    d.mkdir(parents=True)
    (d / "flow.yml").write_text(yaml.safe_dump(flow()))
    got = flow3.check_text((d / "flow.yml").read_text(), place="repo", flow_dir=d)
    assert any("a built-in flow's name" in p for p in got.problems)


def test_a_node_team_follows_a_repo_flow_its_checkout_holds(tmp_path):
    d = tmp_path / ".shiftlead" / "flows" / "mine"
    doc = edit(1, brief="sec")
    held = {d / "flow.yml": "x", d / "briefs" / "sec.md": "y"}
    assert flow3.node_reasons(doc, "repo", d, "cm", "node1", held.get) == ([], True)
    held.pop(d / "briefs" / "sec.md")
    why, known = flow3.node_reasons(doc, "repo", d, "cm", "node1", held.get)
    assert known and "briefs/sec.md is not in node1's checkout" in why[0]

    def down(_p):
        raise OSError("no link")

    assert flow3.node_reasons(doc, "repo", d, "cm", "node1", down) == (["node1 did not answer"], False)
    assert "an org flow" in flow3.node_reasons(doc, "org", d, "cm", "node1", held.get)[0][0]
    assert flow3.node_reasons(doc, "package", d, "cm", "node1", held.get) == ([], True)


def test_a_first_shape_flow_is_read_as_before_and_a_teams_name_resolves_to_it():
    for name in flowdefs.BUILTIN:
        got = flowdefs.find(name)
        assert got.dir == flowdefs.PACKAGE_DIR / name and got.stages, "the first shape's built-in, still in use"
        assert got.problems == []
    assert flowdefs.find("design-wise") is None, "a format-3 built-in is reachable by check and list alone"


def test_a_format3_file_is_no_flow_a_team_can_run(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    d = tmp_path / "repo" / ".shiftlead" / "flows" / "mine"
    d.mkdir(parents=True)
    (d / "flow.yml").write_text(yaml.safe_dump(flow()))
    cfg = repoconfig.load(tmp_path / "repo")
    got = flowdefs.load("mine", cfg)
    assert not got.usable and "no team runs until the cut-over" in got.problems[0]
    (row,) = [r for r in flowdefs.visible([tmp_path / "repo"]) if r["name"] == "mine"]
    assert row["format"] == 3 and row["in_use"] is False
    assert not row["usable"] and "no pinned agent-cadence" in row["problems"][0], "judged by its own check"


def test_ao_flow_check_prints_problems_and_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.yml"
    good.write_text(yaml.safe_dump(flow()))
    assert cli.main(["flow", "check", str(good)]) == 0
    assert capsys.readouterr().out.rstrip().endswith("OK")
    bad = tmp_path / "bad.yml"
    bad.write_text(yaml.safe_dump(edit(0, **{"work-pushed": "nowhere"})))
    assert cli.main(["flow", "check", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "PROBLEM: Build: `work-pushed` goes to `nowhere`" in out and "3 problem(s)" in out
    assert cli.main(["flow", "check", str(good), "--repo", str(tmp_path)]) == 1
    assert "no pinned agent-cadence" in capsys.readouterr().out
    assert cli.main(["--json", "flow", "check", str(bad)]) == 1
    assert json.loads(capsys.readouterr().out)["usable"] is False


def test_ao_flow_list_marks_the_format3_builtins_not_yet_in_use(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    assert cli.main(["flow", "list"]) == 0
    lines = capsys.readouterr().out.splitlines()
    wise = [ln for ln in lines if ln.startswith("flow design-wise")]
    assert len(wise) == 1 and "usable  format 3, not yet in use" in wise[0]
    assert any(ln.startswith("flow td") and "format 3" not in ln for ln in lines), "the first shape's stay in use"


def test_a_flow_nested_past_the_parsers_depth_is_one_problem():
    """TD-2135: a file nested past the YAML parser's depth reads as text that is no YAML, never a RecursionError."""
    deep = "format: 3\nstages: " + "[" * 5000
    got = flow3.check_text(deep)
    assert len(got.problems) == 1 and got.problems[0].startswith("the file is not valid YAML")
    assert flow3.is_format3(deep) is False
