"""The switch-over's check: the logins a host's profiles make, named by the answers file, each team with what the
answers give it, and the blockers to cure beforehand (design §4.9e *The three commands*, *Blockers*, §4.2b *What the
switch-over makes*, TD-2071)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from shiftlead import cli, switchover
from shiftlead.adapters import claude_code, gemini, grok
from shiftlead.profiles import Profile

SALT = b"s" * 32


class Fake:
    """An adapter's switch-over reads: its default home, its model table, and who each folder is signed in as."""

    def __init__(self, default: Path, signed: dict[Path, str] | None = None, table: dict[str, str] | None = None):
        self.default, self.signed, self.table = default, signed or {}, table or {"opus-4": "opus"}

    def default_home(self, _env: Any) -> Path:
        return self.default

    def model_family(self, model: str) -> str | None:
        return self.table.get(model)

    def identity(self, home: Path, _salt: bytes) -> dict | None:
        m = self.signed.get(Path(home).resolve())
        return {"match": m} if m else None


def run(tmp_path: Path, profs: list[Profile], **kw: Any) -> tuple[list[switchover.Login], list[switchover.Blocker]]:
    fakes = kw.pop("fakes", None) or {"claude-code": Fake(tmp_path / "default-claude")}

    def adapter_of(name: str) -> Any:
        return fakes[name]

    return switchover.host_logins("h", {p.name: p for p in profs}, env={}, salt=SALT, adapter_of=adapter_of, **kw)


def P(name: str, folder: Path | None = None, **kw: Any) -> Profile:  # noqa: N802 — a fixture's constructor
    return Profile(name=name, config_dir=folder, **kw)


def test_one_login_per_folder_named_for_its_first_profile(tmp_path):
    a = tmp_path / "a"
    made, blockers = run(tmp_path, [P("paul", a), P("grind", a, account="paul"), P("other", tmp_path / "b")])
    assert blockers == []
    assert [(m.name, m.profiles) for m in made] == [("paul", ["paul", "grind"]), ("other", ["other"])]


def test_a_shell_profile_and_an_unregistered_adapter_make_no_login(tmp_path):
    profs = [P("sh", adapter="shell"), P("x", tmp_path / "x", adapter="nope"), P("c", tmp_path / "c")]

    def adapter_of(name: str) -> Any:
        if name == "nope":
            raise KeyError(name)
        return Fake(tmp_path / "d")

    made, _ = switchover.host_logins("h", {p.name: p for p in profs}, env={}, salt=SALT, adapter_of=adapter_of)
    assert [m.name for m in made] == ["c"]


def test_the_default_home_is_the_folder_of_a_profile_with_no_config_dir(tmp_path):
    made, blockers = run(tmp_path, [P("paul")])
    assert made[0].folder == (tmp_path / "default-claude").resolve() and not blockers


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("billing", "metered"),
        ("extra_args", ["--x"]),
        ("unattended_args", ["--y"]),
        ("permission_wait", 9),
        ("prices", {"input": 1.0}),
    ],
)
def test_profiles_on_one_folder_that_disagree_on_a_setting_block(tmp_path, setting, value):
    a = tmp_path / "a"
    _, blockers = run(tmp_path, [P("paul", a), P("grind", a, account="paul", **{setting: value})])
    assert [b for b in blockers if setting in b.what and not b.day]


def test_permission_prompts_alone_is_no_disagreement(tmp_path):
    a = tmp_path / "a"
    _, blockers = run(tmp_path, [P("paul", a), P("ask", a, account="paul", permission_prompts="ask")])
    assert blockers == []


def test_two_keys_on_one_folder_block(tmp_path):
    a = tmp_path / "a"
    _, blockers = run(tmp_path, [P("paul", a), P("grind", a)])
    assert any("more than one key" in b.what and "account:" in b.cure for b in blockers)


def test_one_folder_reached_as_a_config_dir_and_as_the_default_blocks(tmp_path):
    d = tmp_path / "default-claude"
    _, blockers = run(tmp_path, [P("paul"), P("grind", d, account="paul")])
    assert any("both as a config_dir" in b.what for b in blockers)


def test_a_pin_only_where_every_profile_names_one_model(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    made, blockers = run(
        tmp_path,
        [
            P("p1", a, model="opus-4"),
            P("p2", a, account="p1", model="opus-4"),
            P("q1", b, model="opus-4"),
            P("q2", b, account="q1"),
        ],
    )
    assert [m.pin for m in made] == ["opus", None] and not blockers


def test_a_pin_the_table_cannot_map_blocks(tmp_path):
    _, blockers = run(tmp_path, [P("p", tmp_path / "a", model="mystery-9")])
    assert any("cannot map" in b.what and "mystery-9" in b.what for b in blockers)


def test_a_bad_name_and_two_names_of_one_fold_block(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    names = {f"claude-code:{switchover.shown(a.resolve())}": "bad name!"}
    _, blockers = run(tmp_path, [P("p", a), P("q", b)], names=names)
    assert any("not a login name" in x.what for x in blockers)
    names = {f"claude-code:{switchover.shown(b.resolve())}": "P"}
    _, blockers = run(tmp_path, [P("p", a), P("q", b)], names=names)
    assert any("one name of one tool" in x.what for x in blockers)


def test_two_keys_signed_in_as_one_account_block(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    fakes = {"claude-code": Fake(tmp_path / "d", signed={a.resolve(): "m1", b.resolve(): "m1"})}
    _, blockers = run(tmp_path, [P("p", a), P("q", b)], fakes=fakes)
    assert any("signed in as one account" in x.what for x in blockers)


def test_one_key_whose_folders_read_two_accounts_blocks(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    fakes = {"claude-code": Fake(tmp_path / "d", signed={a.resolve(): "m1", b.resolve(): "m2"})}
    _, blockers = run(tmp_path, [P("p", a), P("q", b, account="p")], fakes=fakes)
    assert any("signed in as 2 accounts" in x.what for x in blockers)


def test_one_account_on_two_tools_is_no_blocker(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    fakes = {
        "claude-code": Fake(tmp_path / "d", signed={a.resolve(): "m1"}),
        "gemini": Fake(tmp_path / "e", signed={b.resolve(): "m1"}),
    }
    _, blockers = run(tmp_path, [P("p", a), P("q", b, adapter="gemini")], fakes=fakes)
    assert blockers == []


def test_each_adapter_maps_a_model_through_its_own_table():
    assert claude_code.ClaudeCodeAdapter().model_family("claude-opus-4-1") == claude_code.model_family(
        "claude-opus-4-1"
    )
    assert gemini.GeminiAdapter().model_family("gemini-3.5-flash-lite") == "flash-lite"
    assert grok.GrokAdapter().model_family("nothing-known") is None


def test_the_report_lists_logins_then_blockers(tmp_path):
    made, blockers = run(tmp_path, [P("p", tmp_path / "a", model="mystery-9")])
    lines = switchover.report("h", made, blockers)
    assert lines[0] == "h: logins the move would make" and lines[1].startswith("  claude-code:p  ")
    assert lines[2] == "blockers to cure beforehand" and "mystery-9" in lines[3]
    assert switchover.report("h", [], [])[-1] == "no blockers"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A home of its own (the worker's is read by every later test on it), on a host `h` with no node and no
    registered checkout."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    registry = home / "repos.txt"
    registry.write_text("")
    monkeypatch.setattr(
        cli.hosts, "local_host", lambda: cli.hosts.Host(name="h", vscode_host="h", repos_registry=registry)
    )
    monkeypatch.setattr(cli.hosts, "is_node", lambda: False)
    monkeypatch.setattr(cli.hosts, "nodes", lambda: {})
    return home


def answers(home: Path, doc: dict) -> None:
    (home / "switch-over").mkdir(exist_ok=True)
    (home / "switch-over" / "answers.yml").write_text(yaml.safe_dump(doc))


def test_check_exits_nonzero_while_a_blocker_to_cure_beforehand_stands(home, tmp_path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    (home / "profiles.yml").write_text(f"profiles:\n  p: {{config_dir: {a}}}\n  q: {{config_dir: {a}}}\n")
    assert cli.main(["switch-over", "check"]) == 1
    assert "more than one key" in capsys.readouterr().out
    (home / "profiles.yml").write_text(f"profiles:\n  p: {{config_dir: {a}}}\n  q: {{config_dir: {b}}}\n")
    assert cli.main(["switch-over", "check"]) == 1  # no answers file
    assert "there is no answers file" in capsys.readouterr().out
    answers(home, {"hosts": {"h": {"logins": {f"claude-code:{a}": {"name": "p"}, f"claude-code:{b}": {"name": "q"}}}}})
    assert cli.main(["switch-over", "check"]) == 0
    out = capsys.readouterr().out
    assert "no blockers" in out and "none: the org defines no team" in out


def test_the_check_names_each_team_with_what_the_answers_give_it(home, tmp_path, capsys):
    a = tmp_path / "a"
    (home / "profiles.yml").write_text(f"profiles:\n  p: {{config_dir: {a}}}\n")
    team = {"repo": "r", "manager": {"role": "person"}, "members": [{"role": "grinder"}]}
    (home / "org.yml").write_text(yaml.safe_dump({"teams": {"grind": team}}))
    found = {f"claude-code:{a}": {"name": "paul"}}
    pick = {"flow": "design-wise", "logins": ["claude-code:paul"], "at_once": {"build": 2}, "most": 4}
    sets = {"default": {"logins": ["claude-code:paul"]}}
    answers(home, {"hosts": {"h": {"logins": found}}, "teams": {"grind": pick}})
    assert cli.main(["switch-over", "check"]) == 1, "a home with a team and no set's list"
    assert "the built-in set: its login list is empty" in capsys.readouterr().out
    answers(home, {"hosts": {"h": {"logins": found}}, "teams": {"grind": pick}, "builtins": sets})
    before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    assert cli.main(["switch-over", "check"]) == 0
    out = capsys.readouterr().out
    assert "  grind: r on h, flow design-wise; logins claude-code:paul; at once build 2, at most 4 in all" in out
    assert "claude-code:paul" in out.splitlines()[1]
    assert {p: p.read_bytes() for p in home.rglob("*") if p.is_file()} == before  # changes nothing
    assert "  default: tech-lead opus, prompts sonnet" in out and "logins claude-code:paul" in out.split("built-in")[1]
    gone = {"grind": {**pick, "logins": ["claude-code:gone"]}}
    answers(home, {"hosts": {"h": {"logins": found}}, "teams": gone, "builtins": sets})
    assert cli.main(["switch-over", "check"]) == 1
    out = capsys.readouterr().out
    assert "lists claude-code:gone, a login h would not have" in out


def test_no_answers_file_a_bad_one_and_one_not_a_mapping_each_block(tmp_path):
    got, blockers = switchover.read_answers(tmp_path / "none.yml")
    assert got is None and "there is no answers file" in blockers[0].what and not blockers[0].day
    (tmp_path / "bad.yml").write_text("hosts: [unclosed\n")
    assert "cannot be read" in switchover.read_answers(tmp_path / "bad.yml")[1][0].what
    (tmp_path / "list.yml").write_text("- a\n")
    assert "not a mapping" in switchover.read_answers(tmp_path / "list.yml")[1][0].what
    (tmp_path / "teams.yml").write_text("teams: [a]\n")
    assert "teams" in switchover.read_answers(tmp_path / "teams.yml")[1][0].what
    (tmp_path / "director.yml").write_text("director: [a]\n")
    assert "director must each be a mapping" in switchover.read_answers(tmp_path / "director.yml")[1][0].what
    (tmp_path / "ok.yml").write_text("")
    assert switchover.read_answers(tmp_path / "ok.yml") == ({}, [])


def test_a_folder_the_answers_name_takes_that_name_and_one_they_do_not_blocks(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    doc = {"hosts": {"h": {"logins": {f"claude-code:{a.resolve()}": {"name": "paul"}}}}}
    made, _ = run(tmp_path, [P("p", a), P("q", b)], names=switchover.names_of(doc, "h"))
    assert [m.name for m in made] == ["paul", "q"]
    got = switchover.unnamed("h", made, doc)
    assert len(got) == 1 and f"claude-code:{b.resolve()} has no name" in got[0].what
    assert switchover.unnamed("h", made, None) == []  # the file's own blocker stands for every name


# -- the teams (§4.9e *Blockers*: a team's cases) ----------------------------------------------------------------------


def Team(repo: str = "r", host: str = "") -> SimpleNamespace:  # noqa: N802 — a fixture's constructor
    return SimpleNamespace(repo=repo, host=host)


def Org(unlanded: dict | None = None, **teams: SimpleNamespace) -> SimpleNamespace:  # noqa: N802
    return SimpleNamespace(teams=teams, unlanded=unlanded or {})


FLOW = {"stages": [{"name": "Build", "model": "opus"}], "audits": [{"name": "Docs", "model": "sonnet"}]}


def flows(*rows: dict) -> Any:
    got = [{"name": "design-wise", "place": "builtin", "doc": FLOW, "problems": []}, *rows]
    return lambda _repo: got


def plan(org: Any, doc: dict | None, *, made: list | None = None, nodes: dict | None = None, offered: Any = None):
    made = (
        made
        if made is not None
        else [switchover.Login("claude-code", Path("/a"), "paul", ["p"], ["k"], models=["opus", "sonnet"])]
    )
    return switchover.teams(org, doc, "h", made, [], nodes=nodes or {}, offered=offered or flows())


def pick(**kw: Any) -> dict:
    return {"teams": {"grind": {"flow": "design-wise", "logins": ["claude-code:paul"], **kw}}}


def test_a_team_the_answers_fill_has_no_blocker_and_carries_its_counts():
    plans, blockers = plan(Org(grind=Team()), pick(at_once={"build": 2}, most=4, label="Builders"))
    assert blockers == []
    p = plans[0]
    assert (p.flow, p.logins, p.at_once, p.most, p.label, p.host) == (
        "design-wise",
        ["claude-code:paul"],
        {"build": 2},
        4,
        "Builders",
        "h",
    )


def test_with_no_answers_file_a_team_is_listed_and_blocks_nothing_of_its_own():
    plans, blockers = plan(Org(grind=Team()), None)
    assert [p.flow for p in plans] == [None] and blockers == []


@pytest.mark.parametrize(
    ("doc", "words"),
    [
        ({"teams": {}}, "has no flow in the answers"),
        (pick(logins=[]), "its login list is empty"),
        (pick(logins="claude-code:paul"), "not a list of <tool>:<name>"),
        (pick(logins=["claude-code"]), "not a list of <tool>:<name>"),
        (pick(logins=["claude-code:gone"]), "lists claude-code:gone, a login h would not have"),
        (pick(flow="nope"), "its flow nope is no format-3 flow it could be given"),
        (pick(at_once={"build": 0}), "at_once is not whole numbers"),
        (pick(most=True), "its most is not a whole number"),
        ({"teams": {**pick()["teams"], "ghost": {}}}, "teams.ghost names no team of the org"),
    ],
)
def test_each_team_case_blocks_by_name(doc, words):
    _, blockers = plan(Org(grind=Team()), doc)
    assert [b for b in blockers if words in b.what and not b.day], blockers


def test_an_empty_list_is_one_blocker_not_two():
    _, blockers = plan(Org(grind=Team()), pick(logins=[]))
    assert len(blockers) == 1


def test_a_login_the_home_lacks_is_one_blocker_not_two():
    _, blockers = plan(Org(grind=Team()), pick(logins=["claude-code:gone"]))
    assert [b.what for b in blockers] == ["lists claude-code:gone, a login h would not have"]
    _, blockers = plan(Org(grind=Team()), pick(logins=["claude-code:gone", "claude-code:paul"]))
    assert len(blockers) == 1


def test_a_model_its_flow_names_that_no_login_in_its_list_offers_blocks():
    made = [switchover.Login("claude-code", Path("/a"), "paul", ["p"], ["k"], models=["opus"])]
    _, blockers = plan(Org(grind=Team()), pick(), made=made)
    assert any("no login in its list offers sonnet" in b.what for b in blockers)
    pinned = [switchover.Login("claude-code", Path("/a"), "paul", ["p"], ["k"], pin="opus", models=["opus", "sonnet"])]
    _, blockers = plan(Org(grind=Team()), pick(), made=pinned)
    assert any("offers sonnet" in b.what for b in blockers)  # a pin narrows what the login offers


def test_a_flow_with_problems_blocks():
    bad = {"name": "mine", "place": "own", "doc": FLOW, "problems": ["stage Build names no brief"]}
    _, blockers = plan(Org(grind=Team()), pick(flow="mine"), offered=flows(bad))
    assert any("names no brief" in b.what for b in blockers)


def test_a_node_team_is_not_checked_for_its_logins_and_an_org_flow_does_not_reach_it():
    own = {"name": "mine", "place": "own", "doc": FLOW, "problems": []}
    nodes = {"far": {}, "box": {"container": {"devcontainer": "~/x"}}}
    org = Org(grind=Team(host="far"), boxed=Team(host="box"))
    doc = {
        "teams": {"grind": {"flow": "mine", "logins": ["grok:x"]}, "boxed": {"flow": "design-wise", "logins": ["a:b"]}}
    }
    plans, blockers = plan(org, doc, nodes=nodes, offered=flows(own))
    assert [b.what for b in blockers] == [
        "its flow mine: not followable: an org flow, and grind runs on far — define it in the repo"
    ]
    notes = {p.name: p.note for p in plans}
    assert "far, an ssh node" in notes["grind"] and "box, a container node" in notes["boxed"]


def test_a_repo_flow_on_a_node_is_said_not_checked():
    mine = {"name": "ours", "place": "repo", "repo": "r", "doc": FLOW, "problems": []}
    plans, blockers = plan(Org(grind=Team(host="far")), pick(flow="ours"), nodes={"far": {}}, offered=flows(mine))
    assert blockers == [] and "checkout of r is not read here" in plans[0].note


def test_a_team_on_a_host_that_is_no_node_and_one_unlanded_block():
    org = Org({"lost": "team lost: its registry could not be read"}, gone=Team(host="mars"), lost=Team())
    _, blockers = plan(org, pick())
    whats = [b.what for b in blockers]
    assert "runs on mars, which is not a node of this home" in whats
    assert "team lost: its registry could not be read" in whats


def test_the_report_lists_the_teams_between_the_logins_and_the_blockers():
    plans, blockers = plan(Org(grind=Team()), {"teams": {}})
    lines = switchover.report("h", [], blockers, plans)
    assert lines.index("teams the answers give") < lines.index("blockers to cure beforehand")
    assert "  grind: r on h, no flow picked" in lines


def test_a_profiles_file_that_does_not_parse_is_reported_not_raised(tmp_path, capsys, monkeypatch):
    from sessionorc import paths

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))  # never the suite's shared unit home: a later test reads it
    (paths.home() / "profiles.yml").write_text("profiles: [unclosed\n")
    assert cli.main(["switch-over", "check"]) == 1
    assert "cannot be read" in capsys.readouterr().err


def test_an_adapter_whose_home_raises_makes_no_login(tmp_path):
    class Broken(Fake):
        def default_home(self, _env: Any) -> Path:
            raise RuntimeError("no home")

    made, _ = run(tmp_path, [P("p"), P("q", tmp_path / "q")], fakes={"claude-code": Broken(tmp_path)})
    assert [m.name for m in made] == ["q"]


def test_a_folder_under_a_symlinked_home_is_shown_from_tilde(tmp_path, monkeypatch):
    real = tmp_path / "real"
    (real / ".claude").mkdir(parents=True)
    (tmp_path / "link").symlink_to(real)
    monkeypatch.setenv("HOME", str(tmp_path / "link"))
    assert switchover.shown((tmp_path / "link" / ".claude").resolve()) == "~/.claude"


# -- the built-in set (§4.9e *Blockers*: the set's cases) --------------------------------------------------------------

HOME = [switchover.Login("claude-code", Path("/a"), "paul", ["p"], ["k"], models=["opus", "sonnet"])]


def builtins(models: Any = None, logins: Any = ("claude-code:paul",), *, plans: Any = ("grind",), **kw: Any) -> Any:
    row: dict[str, Any] = {"logins": list(logins) if isinstance(logins, tuple) else logins}
    if models is not None:
        row["models"] = models
    teams = [p if isinstance(p, switchover.TeamPlan) else switchover.TeamPlan(p, "r", "h") for p in plans]
    return switchover.builtin_set({"builtins": {"default": row}}, HOME, teams, "h", nodes=kw.pop("nodes", {}), **kw)


def test_the_set_takes_the_packages_model_for_a_seat_left_out_and_reads_the_rest():
    got, blockers = builtins({"tech-lead": "sonnet", "sweeper": "sonnet"})
    assert blockers == [] and got.logins == ["claude-code:paul"]
    assert got.models == {
        "tech-lead": "sonnet",
        "prompts": "sonnet",
        "board-answers": "sonnet",
        "unheld-pull-requests": "sonnet",
        "sweeper": "sonnet",
    }
    assert switchover.builtin_set(None, HOME, [], "h", nodes={}) == (None, []), "the file's own blocker stands"


def test_a_seat_no_login_offers_blocks_by_name_and_the_package_haiku_is_one():
    _, blockers = builtins()
    assert [b.what for b in blockers] == ["no login in its list offers haiku, the model of the sweeper"]
    assert "builtins.default.models.sweeper" in blockers[0].cure and blockers[0].where == switchover.SET


def test_where_the_org_has_a_director_the_prompts_seat_is_not_read():
    models = {"prompts": "fable", "sweeper": "sonnet"}
    assert [b.what for b in builtins(models)[1]] == ["no login in its list offers fable, the model of the prompts seat"]
    got, blockers = builtins(models, director=True)
    assert blockers == [] and "prompts" not in switchover.set_lines(got)[1]
    assert "the director answers prompts" in switchover.set_lines(got)[2]


def test_an_empty_list_blocks_only_on_a_home_with_a_team():
    assert [b.what for b in builtins(logins=[])[1]] == ["its login list is empty"]
    assert builtins(logins=[], plans=())[1] == []
    assert [b.what for b in builtins(logins="claude-code:paul")[1]] == [
        "builtins.default.logins is not a list of <tool>:<name>"
    ], "one blocker, not two"


def test_a_login_the_home_lacks_blocks_unless_a_team_runs_on_an_ssh_node():
    lacks = ("claude-code:paul", "claude-code:far")
    models = {"sweeper": "sonnet"}
    assert [b.what for b in builtins(models, lacks)[1]] == ["lists claude-code:far, a login h would not have"]
    far = switchover.TeamPlan("away", "r", "far")
    got, blockers = builtins(models, lacks, plans=("grind", far), nodes={"far": {}})
    assert blockers == [] and got.note == "not checked: claude-code:far, taken as names on far, nor the seats' models"
    _, blockers = builtins(None, lacks, plans=("grind", far), nodes={"far": {}})
    assert blockers == [], "the sweeper's haiku may be offered by the unread login"
    _, blockers = builtins(models, lacks, plans=("grind", far), nodes={"far": {"container": True}})
    assert [b.what for b in blockers] == ["lists claude-code:far, a login h would not have"], "a container's is"


def test_a_seat_that_is_none_and_a_manager_key_are_refused_by_name():
    _, blockers = builtins({"manager": "opus", "fact-check": "sonnet", "sweeper": 4})
    whats = [b.what for b in blockers]
    assert whats[0] == (
        "builtins.default.models names 'manager', which is not a built-in seat: there is no manager after the move"
        " (design §4.9d)"
    )
    assert whats[1] == "builtins.default.models names 'fact-check', which is not a built-in seat"
    assert whats[2] == "builtins.default.models.sweeper is not a model"
    assert "haiku" in whats[3], "a seat refused reads the package's model"


# -- the director (§4.9e *The answers file*, *Blockers*: the director's cases) -----------------------------------------


def director(row: Any = None, *, profile: str | None = "p", prompts: str | None = None) -> Any:
    doc = {} if row is None else {"director": row}
    sets = switchover.SetPlan({"prompts": prompts}) if prompts else None
    return switchover.director(doc, HOME, sets, profile)


def test_the_director_is_suggested_the_prompts_model_and_the_login_its_profile_becomes():
    got, blockers = director()
    assert (got.suggest_model, got.suggest_login, got.given) == ("sonnet", "claude-code:paul", False)
    assert [b.what for b in blockers] == ["the org has a director and the answers give it none"]
    assert blockers[0].cure == "write director: {model: sonnet, logins: [claude-code:paul]}"
    assert blockers[0].where == switchover.DIRECTOR and not blockers[0].day
    got, _ = director(prompts="opus", profile="elsewhere")
    assert (got.suggest_model, got.suggest_login) == ("opus", None), "the set's prompts model; no login the home makes"
    assert switchover.director_lines(got)[1] == "  none; suggested: model opus, login none the home would make " + (
        "(from profile elsewhere)"
    )
    assert switchover.director(None, HOME, None, "p") == (None, []), "the file's own blocker stands"


def test_a_director_the_answers_fill_has_no_blocker():
    got, blockers = director({"model": "opus", "logins": ["claude-code:paul", "claude-code:paul"]})
    assert blockers == [] and (got.model, got.logins) == ("opus", ["claude-code:paul"])
    assert switchover.director_lines(got) == [
        "the director the answers give",
        "  model opus; logins claude-code:paul",
        "    suggested: model sonnet, login claude-code:paul (from profile p)",
    ]


@pytest.mark.parametrize(
    ("row", "whats"),
    [
        ({"logins": ["claude-code:paul"]}, ["has no model"]),
        ({"model": 4, "logins": ["claude-code:paul"]}, ["director.model is not a model"]),
        ({"model": "opus"}, ["its login list is empty"]),
        ({"model": "opus", "logins": []}, ["its login list is empty"]),
        ({"model": "opus", "logins": "claude-code:paul"}, ["director.logins is not a list of <tool>:<name>"]),
        (
            {"model": "opus", "logins": ["claude-code:paul", "claude-code:far"]},
            ["lists claude-code:far, a login the home would not have"],
        ),
        ({"model": "fable", "logins": ["claude-code:paul"]}, ["no login in its list offers fable, its model"]),
        ({"model": "fable", "logins": ["claude-code:far"]}, ["lists claude-code:far, a login the home would not have"]),
    ],
)
def test_each_director_case_blocks_by_name(row, whats):
    assert [b.what for b in director([])[1]] == ["director is not a mapping"]
    assert [b.what for b in director(row)[1]] == whats


def test_the_check_reads_the_director_where_the_org_has_one(home, tmp_path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    (home / "profiles.yml").write_text(f"default: q\nprofiles:\n  p: {{config_dir: {a}}}\n  q: {{config_dir: {b}}}\n")
    found = {f"claude-code:{a}": {"name": "paul"}, f"claude-code:{b}": {"name": "grind"}}
    answers(home, {"hosts": {"h": {"logins": found}}})
    assert cli.main(["switch-over", "check"]) == 0
    assert "director" not in capsys.readouterr().out, "no director in the org, none read"
    (home / "org.yml").write_text(yaml.safe_dump({"director": {}}))
    assert cli.main(["switch-over", "check"]) == 1
    out = capsys.readouterr().out
    assert "  none; suggested: model sonnet, login claude-code:grind (from profile q)" in out, "the default profile's"
    assert "the director: the org has a director and the answers give it none" in out
    (home / "org.yml").write_text(yaml.safe_dump({"director": {"profile": "p"}}))
    answers(home, {"hosts": {"h": {"logins": found}}, "director": {"model": "sonnet", "logins": ["claude-code:far"]}})
    assert cli.main(["switch-over", "check"]) == 1
    out = capsys.readouterr().out
    assert "suggested: model sonnet, login claude-code:paul (from profile p)" in out
    assert "the director: lists claude-code:far, a login the home would not have" in out
    answers(home, {"hosts": {"h": {"logins": found}}, "director": {"model": "sonnet", "logins": ["claude-code:paul"]}})
    assert cli.main(["switch-over", "check"]) == 0, capsys.readouterr().out


def test_a_director_list_whose_every_login_leaves_its_prompts_on_blocks():
    on = switchover.Login("claude-code", Path("/b"), "asks", ["q"], ["k2"], models=["opus", "sonnet"], asks=True)
    unread = switchover.Login("x", Path("/c"), "unread", ["r"], ["k3"], models=["opus", "sonnet"], asks=None)
    made = [*HOME, on, unread]
    row = {"model": "sonnet", "logins": ["claude-code:asks"]}
    _, blockers = switchover.director({"director": row}, made, None, "p")
    assert [b.what for b in blockers] == ["every login in its list leaves its prompts on (claude-code:asks)"]
    for listed in (["claude-code:asks", "claude-code:paul"], ["x:unread"]):
        assert switchover.director({"director": {**row, "logins": listed}}, made, None, "p")[1] == [], listed


def test_a_login_leaves_its_prompts_on_where_its_unattended_args_lack_the_skip_args(tmp_path):
    fake = Fake(tmp_path / "d")
    fake.skip_args = ["--skip"]
    profs = [
        P("bare", tmp_path / "a"),
        P("skips", tmp_path / "b", unattended_args=["--skip", "--x"]),
        P("asks", tmp_path / "c", unattended_args=["--x"]),
    ]
    made, _ = run(tmp_path, profs, fakes={"claude-code": fake})
    assert [(m.name, m.asks) for m in made] == [("bare", False), ("skips", False), ("asks", True)]
    made, _ = run(tmp_path, profs)
    assert {m.asks for m in made} == {None}, "an adapter naming no skip_args is not read"


@pytest.mark.parametrize("adapter", [claude_code.ClaudeCodeAdapter(), gemini.GeminiAdapter(), grok.GrokAdapter()])
def test_each_adapter_names_skip_args_and_a_login_lacking_them_asks(adapter):
    assert adapter.skip_args and switchover._asks(adapter, []) is False
    assert switchover._asks(adapter, list(adapter.skip_args)) is False
    assert switchover._asks(adapter, ["--other"]) is True


# -- the answers file `--answers` writes (§4.9e *The answers file*) ----------------------------------------------------


def Line(role: str = "grinder", count: int = 1, size: int | None = None) -> SimpleNamespace:  # noqa: N802
    return SimpleNamespace(role=role, count=count, size=size, profile=None)


def Def(host: str = "", flows: tuple = ("td",), members: tuple = (), repo: str = "r") -> SimpleNamespace:  # noqa: N802
    return SimpleNamespace(
        repo=repo, host=host, flows=list(flows), flow="", members=list(members), techlead=None, seats=[]
    )


FLOW3 = {"stages": [{"name": "Design", "takes": "design-first"}, {"name": "Build", "takes": "other"}]}


def suggest(org: Any, *, ran_on: Any = None, **kw: Any) -> dict:
    made = [
        switchover.Login("claude-code", Path("/a"), "paul", ["p"], ["k"]),
        switchover.Login("gemini", Path("/g"), "reader", ["fc"], ["k2"]),
    ]
    offered = lambda _repo: [{"name": "design-wise", "doc": FLOW3}, {"name": "build", "doc": {"stages": []}}]  # noqa: E731
    return switchover.suggest(
        org, "h", made, [], default="p", offered=offered, ran_on=ran_on or (lambda _t: ["p", "fc"]), **kw
    )


def test_answers_name_each_folder_and_give_a_team_its_renamed_flow_logins_and_builders():
    org = SimpleNamespace(
        teams={"grind": Def(members=(Line("designer"), Line(count=2), Line(size=3)))}, unlanded={}, director=None
    )
    got = suggest(org, schedules={"grind": {"schedule": {"profile": "p"}}})
    assert got["hosts"] == {"h": {"logins": {"claude-code:/a": {"name": "paul"}, "gemini:/g": {"name": "reader"}}}}
    assert got["teams"]["grind"] == {
        "flow": "design-wise",
        "logins": ["claude-code:paul", "gemini:reader"],
        "at_once": {"build": 5},
        "schedule_login": "claude-code:paul",
    }, "td becomes design-wise; the builders' sizes summed, a size over a count; the schedule's profile's login"
    assert got["builtins"]["default"]["logins"] == ["claude-code:paul", "gemini:reader"]
    assert got["builtins"]["default"]["models"]["prompts"] == "sonnet" and "director" not in got


def test_answers_suggest_no_flow_offered_none_and_no_logins_for_a_node_team():
    org = SimpleNamespace(
        teams={"far": Def(host="node", flows=("mine",)), "near": Def(flows=("build",), members=(Line(),))},
        unlanded={"gone": "why"},
        director=None,
    )
    got = suggest(org)
    assert got["teams"]["far"] == {"logins": []}, "no format-3 flow of its name, and its node's logins not read"
    assert got["teams"]["near"]["flow"] == "build" and "at_once" not in got["teams"]["near"], "a flow with no build"
    assert got["builtins"]["default"]["logins"] == ["claude-code:paul", "gemini:reader"], "the first home team's"


def test_answers_give_the_director_the_prompts_model_and_its_profiles_login_and_drop_the_prompts_seat():
    org = SimpleNamespace(teams={}, unlanded={}, director=SimpleNamespace(profile="fc"))
    got = suggest(org)
    assert got["director"] == {"model": "sonnet", "logins": ["gemini:reader"]}
    assert "prompts" not in got["builtins"]["default"]["models"] and got["builtins"]["default"]["logins"] == []
    org.director.profile = None
    assert suggest(org)["director"]["logins"] == ["claude-code:paul"], "the profiles file's default"


def test_check_answers_writes_a_file_the_check_accepts_and_leaves_one_that_is_there(home, tmp_path, capsys):
    a = tmp_path / "a"
    (home / "profiles.yml").write_text(f"default: p\nprofiles:\n  p: {{config_dir: {a}}}\n")
    team = {"repo": "r", "manager": {"role": "person"}, "members": [{"role": "grinder", "count": 2}], "flows": ["td"]}
    (home / "org.yml").write_text(yaml.safe_dump({"teams": {"grind": team}}))
    assert cli.main(["switch-over", "check", "--answers"]) == 0
    captured = capsys.readouterr()
    assert "wrote " in captured.err and "answers.yml" in captured.err
    path = home / "switch-over" / "answers.yml"
    doc = yaml.safe_load(path.read_text())
    assert doc["teams"]["grind"] == {"flow": "design-wise", "logins": ["claude-code:p"], "at_once": {"build": 2}}
    assert "no blockers" in captured.out
    path.write_text("teams: {}\n")
    assert cli.main(["switch-over", "check", "--answers"]) == 1
    captured = capsys.readouterr()
    assert "left as it is" in captured.err and path.read_text() == "teams: {}\n"


def test_answers_give_at_once_to_a_stage_that_takes_any_where_none_takes_other():
    org = SimpleNamespace(teams={"grind": Def(flows=("build",), members=(Line(size=3),))}, unlanded={}, director=None)
    any_flow = {"stages": [{"name": "Build", "takes": "any"}, {"name": "Review"}]}
    got = switchover.suggest(
        org, "h", [], [], default=None, offered=lambda _r: [{"name": "build", "doc": any_flow}], ran_on=lambda _t: []
    )
    assert got["teams"]["grind"]["at_once"] == {"build": 3}


def test_answers_fall_back_to_each_lines_profile_where_the_start_cannot_be_read(monkeypatch):
    from shiftlead import teams as teamsmod

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise teamsmod.TeamError("no checkout")

    monkeypatch.setattr(teamsmod, "plan", refuse)
    seat = SimpleNamespace(profile="fc")
    team = SimpleNamespace(members=[SimpleNamespace(profile=None)], techlead=seat, seats=[SimpleNamespace(profile="p")])
    team.name = "grind"
    assert switchover._profiles_ran_on(SimpleNamespace(), team, "h", "p") == ["p", "fc"], "members first, once each"


def test_write_answers_leaves_a_file_or_a_dangling_link_that_is_there_and_no_temporary(tmp_path):
    path = tmp_path / "so" / "answers.yml"
    assert switchover.write_answers({"teams": {}}, path) is True
    assert yaml.safe_load(path.read_text()) == {"teams": {}}
    assert switchover.write_answers({"hosts": {}}, path) is False and "teams" in path.read_text()
    link = tmp_path / "so" / "other.yml"
    link.symlink_to(tmp_path / "nowhere")
    assert switchover.write_answers({}, link) is False and not (tmp_path / "nowhere").exists()
    assert sorted(p.name for p in path.parent.iterdir()) == ["answers.yml", "other.yml"]


def test_check_answers_writes_nothing_where_the_org_cannot_be_read(home, tmp_path, capsys):
    (home / "profiles.yml").write_text(f"profiles:\n  p: {{config_dir: {tmp_path / 'a'}}}\n")
    (home / "org.yml").write_text("teams: [not, a, mapping\n")
    assert cli.main(["switch-over", "check", "--answers"]) == 1
    assert "no answers written" in capsys.readouterr().err
    assert not (home / "switch-over" / "answers.yml").exists()


def test_check_answers_for_an_org_with_a_director_writes_one_the_check_accepts(home, tmp_path, capsys):
    a = tmp_path / "a"
    (home / "profiles.yml").write_text(f"default: p\nprofiles:\n  p: {{config_dir: {a}}}\n")
    team = {"repo": "r", "manager": {"role": "person"}, "members": [{"role": "grinder"}], "flows": ["td"]}
    (home / "org.yml").write_text(yaml.safe_dump({"director": {}, "teams": {"grind": team}}))
    assert cli.main(["switch-over", "check", "--answers"]) == 0, capsys.readouterr().out
    doc = yaml.safe_load((home / "switch-over" / "answers.yml").read_text())
    assert doc["director"] == {"model": "sonnet", "logins": ["claude-code:p"]}
    assert "prompts" not in doc["builtins"]["default"]["models"]
    assert "no blockers" in capsys.readouterr().out


# -- the work in flight (§4.9e *Work in flight*) ---------------------------------------------------------------------


def Entry(tid: str, **kw: Any) -> dict:  # noqa: N802
    return {"id": tid, "kind": "build", "owner": "grinder", "pickable": "yes", "for_page": "pickable", **kw}


def Pr(n: int, branch: str, *, filing: bool | None = False, **kw: Any) -> dict:  # noqa: N802
    head = f"h{n}"
    row = {"number": n, "branch": branch, "state": "open", "head": head, "created": f"2026-11-{n:02d}"}
    if filing is not None:
        row |= {"filing": filing, "filing_head": head}
    return row | kw


def test_in_flight_lists_the_entries_taken_up_those_that_wait_and_branches_nothing_reads(tmp_path):
    blocked = Entry("TD-5", pickable="no", for_page="blocked")
    entries = [Entry("TD-1"), Entry("TD-2"), Entry("TD-3"), Entry("TD-4", owner="paul"), blocked, Entry("TD-6")]
    prs = [
        Pr(10, "td1-x"),
        Pr(11, "td2-y", draft=True),
        Pr(12, "td3-z", filing=None),
        Pr(13, "td1-td2-both"),
        Pr(14, "td4-mine"),
        Pr(15, "td6-filing", filing=True),
    ]
    readings = {str(tmp_path): {"name": "r", "ledger": {"entries": entries}, "prs": {"open": prs}}}
    org = SimpleNamespace(teams={"grind": SimpleNamespace(repo="r")}, unlanded={})
    seen: list[str] = []

    def branches(root: str) -> frozenset[str]:
        seen.append(root)
        return frozenset({"main", "td1-x", "td5-lost", "notes"})

    (f,) = switchover.in_flight(readings, org, branches_of=branches)
    assert seen == [str(tmp_path)]
    assert f.taken == [("TD-1", 10, "td1-x")], "the newest single-id match; TD-4 is the person's; a filing PR is none"
    assert f.waits == [("TD-2", "#11 is a draft")] and f.unknown == [
        ("TD-3", "#12's files have not been read at its head")
    ]
    assert f.nobodys == [
        ("td1-td2-both", "#13 holds TD-1, TD-2"),
        ("td5-lost", "holds TD-5 and has no open pull request"),
    ]
    lines = switchover.flight_lines([f])
    assert "    taken up with its pull request: TD-1 #10 (td1-x)" in lines
    assert "    nothing will read: td5-lost — holds TD-5 and has no open pull request" in lines


def test_in_flight_says_a_repo_not_read_and_reads_no_branch_of_a_checkout_that_is_not_here(tmp_path):
    org = SimpleNamespace(teams={"a": SimpleNamespace(repo="r"), "b": SimpleNamespace(repo="s")}, unlanded={})
    readings = {
        str(tmp_path / "gone"): {"name": "s", "ledger": {"entries": []}, "prs": {"open": []}},
        "/x": {"name": "q", "prs": {"error": "gh failed", "open": []}},
    }
    r, s = switchover.in_flight(readings, org, branches_of=lambda _root: pytest.fail("not read"))
    assert r.unread == "the home has not read its pull requests"
    assert s.branches_unread and s.nobodys == []
    readings["/y"] = {"name": "r", "prs": {"at": "t"}}
    assert switchover.in_flight(readings, org, branches_of=lambda _r: None)[0].unread == (
        "its pull request reading holds no open list"
    )
    readings["/y"] = {"name": "r", "prs": {"error": "gh failed"}}
    r, _ = switchover.in_flight(readings, org, branches_of=lambda _root: frozenset())
    assert r.unread == "its pull requests could not be read: gh failed"
    assert switchover.flight_lines([r])[1] == "  r: not read — its pull requests could not be read: gh failed"


def test_the_check_prints_the_work_in_flight_from_the_homes_repo_reading(home, tmp_path, capsys):
    (home / "profiles.yml").write_text(f"profiles:\n  p: {{config_dir: {tmp_path / 'a'}}}\n")
    team = {"repo": "r", "manager": {"role": "person"}, "members": [{"role": "grinder"}]}
    (home / "org.yml").write_text(yaml.safe_dump({"teams": {"grind": team}}))
    reading = {"name": "r", "ledger": {"entries": [Entry("TD-1")]}, "prs": {"open": [Pr(10, "td1-x")]}}
    (home / "repos.json").write_text(json.dumps({"/nowhere/r": reading}))
    cli.main(["switch-over", "check"])
    out = capsys.readouterr().out
    assert "work in flight, as the home will take it up after the window" in out
    assert "    taken up with its pull request: TD-1 #10 (td1-x)" in out


def test_in_flight_names_no_filing_fork_sync_or_sweep_branch_and_no_branch_of_an_entry_not_in_the_reading(tmp_path):
    entries = [Entry("TD-1"), Entry("TD-2"), Entry("TD-7")]
    prs = [
        Pr(20, "td1-td2-filing", filing=True),
        Pr(21, "td1-td2-fork", fork=True),
        Pr(22, "td1-td2-sync", sync=True),
        Pr(23, "lift/TD-1/until-2026-12-01"),
        Pr(24, "td7-fork-named", fork=True),
        Pr(25, "td1-old"),
        Pr(26, "td1-new"),
    ]
    readings = {str(tmp_path): {"name": "r", "ledger": {"entries": entries}, "prs": {"open": prs, "at": "t0"}}}
    org = SimpleNamespace(teams={"grind": SimpleNamespace(repo="r")}, unlanded={})
    pushed = frozenset({"td7-fork-named", "td999-archived", "td1-old", "td1-new"})
    (f,) = switchover.in_flight(readings, org, branches_of=lambda _r: pushed)
    assert f.taken == [("TD-1", 26, "td1-new")], "the newest of two matches"
    assert f.nobodys == [("td7-fork-named", "holds TD-7 and has no open pull request")], (
        "a fork's branch hides no origin branch; an id no entry of the reading has is not named"
    )
    assert switchover.flight_lines([f])[1] == "  r: (its pull requests read t0)"


# -- the seats a picked flow lacks, and the open asks to the first shape (§4.9e) --------------------------------------


def Seat(role: str, name: str = "", brief: str | None = None) -> SimpleNamespace:  # noqa: N802
    return SimpleNamespace(role=role, name=name or f"grind-{role}", brief=brief)


AUDITED = {"stages": [], "audits": [{"name": "Docs audit", "brief": "docs"}, {"name": "Tests audit", "brief": "tests"}]}


def test_a_flow_lacks_a_fact_checker_and_an_unmatched_auditor_but_never_the_sets_seats():
    team = SimpleNamespace(
        techlead=SimpleNamespace(profile=None),
        seats=[
            Seat("fact-checker", "fc-gemini"),
            Seat("auditor", "docs-audit-ao-1", "docs/briefs/docs-audit.md"),
            Seat("auditor", "test-audit-ao-1"),
            Seat("auditor", "security-audit"),
            Seat("sweeper"),
        ],
    )
    assert switchover.lacking(team, AUDITED) == ["fc-gemini (fact-checker)", "security-audit (auditor)"]
    assert switchover.lacking(team, {"stages": []})[1:] == [
        "docs-audit-ao-1 (auditor)",
        "test-audit-ao-1 (auditor)",
        "security-audit (auditor)",
    ], "a flow with no audits has no auditor's place"
    assert switchover.lacking(SimpleNamespace(), AUDITED) == [], "a team with no seats lacks nothing"


def test_an_auditors_brief_file_decides_its_match_and_a_longer_word_matches_a_shorter_brief():
    team = SimpleNamespace(
        seats=[
            Seat("auditor", "grind-checker", "docs/briefs/tests-audit.md"),  # its name matches no audit; its brief does
            Seat("auditor", "docs-audit", "docs/briefs/security-audit.md"),  # its name matches; its brief does not
            Seat("auditor", "testsuite-audit"),  # `testsuite` is begun by the audit's brief `tests`
        ]
    )
    assert switchover.lacking(team, AUDITED) == ["docs-audit (auditor)"]


def test_the_check_lists_beside_a_team_the_seats_its_picked_flow_lacks():
    team = SimpleNamespace(repo="r", host="", seats=[Seat("fact-checker", "fc-grok")])
    plans, blockers = plan(Org(grind=team), pick())
    assert plans[0].lacks == ["fc-grok (fact-checker)"] and blockers == [], "a lacking seat is no blocker"
    lines = switchover.team_lines(plans)
    assert "    seats it runs today that design-wise lacks, which go: fc-grok (fact-checker)" in lines


def test_answers_write_the_seats_each_suggested_flow_lacks_in_the_files_head(tmp_path):
    org = SimpleNamespace(teams={"grind": Def(members=(Line(),))}, unlanded={}, director=None)
    org.teams["grind"].seats = [Seat("fact-checker", "fc-gemini")]
    lacks: dict[str, list[str]] = {}
    doc = suggest(org, lacks=lacks)
    assert lacks == {"grind": ["fc-gemini (fact-checker)"]} and "lacks" not in doc["teams"]["grind"]
    path = tmp_path / "answers.yml"
    assert switchover.write_answers(doc, path, lacks=lacks)
    text = path.read_text()
    assert "#   grind: fc-gemini (fact-checker)\n" in text and yaml.safe_load(text) == doc
    other = tmp_path / "other.yml"
    assert switchover.write_answers(doc, other, lacks={}) and "lacks" not in other.read_text()


def Rec(n: str, *, team: str = "grind", **kw: Any) -> Any:  # noqa: N802
    from sessionorc import models

    kw.setdefault("unattended", True)
    return models.Session(id=f"ao-{n}", name=n, kind="claude", adapter="claude-code", dir="/w", team=team, **kw)


def Ask(mid: str, to: str, *, kind: str = "ask", **kw: Any) -> Any:  # noqa: N802
    from sessionorc.models import MailEntry

    return MailEntry(id=mid, from_="ao-x", to=[to], at="2026-11-24T10:00:00Z", kind=kind, text="which way? more", **kw)


def test_first_shape_asks_are_open_asks_to_a_teams_member_or_seat_alone():
    from sessionorc.models import PERSON

    member = Rec("m")
    member.inbox = [Ask("m-1", "ao-m"), Ask("m-2", "ao-m", kind="note"), Ask("m-3", "ao-m", closed_reason="answered")]
    member.inbox.append(Ask("m-4", PERSON))
    seat = Rec("s", builtin="techlead")
    seat.inbox = [Ask("m-5", "ao-s")]
    loose = Rec("l", team="")
    loose.inbox = [Ask("m-6", "ao-l")]
    own = Rec("o", unattended=False, by_person=True)
    own.inbox = [Ask("m-7", "ao-o")]
    twin = Rec("t")
    twin.inbox = [Ask("m-1", "ao-m"), Ask("m-8", "ao-t", passed_up=True, passes=[{"to": "ao-director"}])]
    twin.inbox.append(Ask("m-9", "ao-t", passed_up=True, passes=[{"to": PERSON}]))  # the person's to answer now
    got = switchover.first_shape_asks({r.id: r for r in (member, seat, loose, own, twin)})
    assert [(a.id, a.to) for a in got] == [("m-1", "ao-m"), ("m-8", "ao-t")], "once per id; the director's counts"
    got = got[:1]
    assert [(a.id, a.to, a.sender, a.subject) for a in got] == [("m-1", "ao-m", "ao-x", "which way?")]
    assert switchover.ask_lines(got)[1] == "  m-1 to ao-m from ao-x (2026-11-24T10:00:00Z): which way?"
    assert switchover.ask_lines([])[1:] == ["  none"]
    assert [a.to for a in switchover.first_shape_asks({"a key": member})] == ["ao-m"], "named by its record's id"


def test_the_check_prints_the_open_asks_to_the_first_shape_and_makes_no_sessions_directory(home, tmp_path, capsys):
    (home / "profiles.yml").write_text(f"profiles:\n  p: {{config_dir: {tmp_path / 'a'}}}\n")
    team = {"repo": "r", "manager": {"role": "person"}, "members": [{"role": "grinder"}]}
    (home / "org.yml").write_text(yaml.safe_dump({"teams": {"grind": team}}))
    cli.main(["switch-over", "check"])
    assert "open asks to a member or seat of the first shape" in capsys.readouterr().out
    assert not (home / "sessions").exists(), "read, never made"
    member = Rec("m")
    member.inbox = [Ask("m-1", "ao-m")]
    (home / "sessions").mkdir()
    (home / "sessions" / "ao-m.json").write_text(json.dumps(member.to_dict()))
    (home / "sessions" / "bad.json").write_text("{")
    cli.main(["switch-over", "check"])
    assert "  m-1 to ao-m from ao-x (2026-11-24T10:00:00Z): which way?" in capsys.readouterr().out


# -- a container node's logins (§4.9e *The window* step 2, *Blockers*) ------------------------------------------------


def Node(root: Path, profiles: str | None) -> SimpleNamespace:  # noqa: N802
    if profiles is not None:
        (root / "home").mkdir(parents=True, exist_ok=True)
        (root / "home" / "profiles.yml").write_text(profiles)
    return SimpleNamespace(node_dir=root)


def test_a_container_nodes_logins_come_from_its_own_profiles_read_at_its_directory_on_the_home(tmp_path):
    root = tmp_path / "nodes" / "cm"
    signed = {(root / "profiles" / "p").resolve(): "who"}
    text = "profiles:\n  p: {config_dir: /shiftlead/profiles/p}\n  bare: {}\n  out: {config_dir: /elsewhere/x}\n"
    nodes = {"cm": Node(root, text + "  up: {config_dir: /shiftlead/../x}\n")}
    seen: list[Path] = []

    class Spy(Fake):
        def identity(self, home: Path, salt: bytes) -> dict | None:
            seen.append(Path(home))
            return super().identity(home, salt)

    made, blockers = switchover.node_logins(
        None, nodes=nodes, salt=SALT, adapter_of=lambda _n: Spy(tmp_path / "d", signed)
    )
    assert [(m.name, m.folder, m.match) for m in made["cm"]] == [("p", Path("/shiftlead/profiles/p"), "who")]
    assert seen == [root / "profiles" / "p"], (
        "read where the folder is on the home; a bare profile, one elsewhere or one climbing out makes none"
    )
    assert made["cm"][0].found == "claude-code:/shiftlead/profiles/p" and blockers == []
    named, blockers = switchover.node_logins({"hosts": {}}, nodes=nodes, salt=SALT, adapter_of=lambda _n: Spy(tmp_path))
    assert [b.what for b in blockers] == ["claude-code:/shiftlead/profiles/p has no name in the answers"]
    doc = {"hosts": {"cm": {"logins": {"claude-code:/shiftlead/profiles/p": {"name": "paul"}}}}}
    named, blockers = switchover.node_logins(doc, nodes=nodes, salt=SALT, adapter_of=lambda _n: Spy(tmp_path))
    assert [m.key for m in named["cm"]] == ["claude-code:paul"] and blockers == []


def test_a_node_with_no_profiles_makes_no_login_and_one_that_does_not_parse_blocks(tmp_path):
    nodes = {"a": Node(tmp_path / "a", None), "b": Node(tmp_path / "b", "profiles: [")}
    made, blockers = switchover.node_logins(None, nodes=nodes, salt=SALT, adapter_of=lambda _n: Fake(tmp_path))
    assert made == {"a": []} and [b.where for b in blockers] == ["host b"]
    assert "profiles.yml cannot be read" in blockers[0].what


def test_a_team_on_a_container_node_is_checked_against_the_nodes_logins():
    nodes = {"cm": {"container": {"devcontainer": "/x"}}}
    node = [switchover.Login("claude-code", Path("/shiftlead/profiles/p"), "paul", ["p"], ["k"])]
    team = Team(host="cm")
    plans, blockers = plan(Org(grind=team), pick(), nodes=nodes, made=[])
    assert plans[0].note and "not read here" in plans[0].note, "unread, as before"
    plans, blockers = switchover.teams(
        Org(grind=team), pick(), "h", [], [], nodes=nodes, offered=flows(), node_made={"cm": node}
    )
    assert plans[0].note is None and blockers == []
    _, blockers = switchover.teams(
        Org(grind=team), pick(logins=["claude-code:gone"]), "h", [], [], nodes=nodes, offered=flows(),
        node_made={"cm": node},
    )  # fmt: skip
    assert [b.what for b in blockers] == ["lists claude-code:gone, a login cm would not have"]


def test_answers_name_a_container_nodes_folders_and_give_its_team_the_nodes_logins():
    org = SimpleNamespace(teams={"far": Def(host="cm", members=(Line(),))}, unlanded={}, director=None)
    node = [switchover.Login("claude-code", Path("/shiftlead/profiles/p"), "p", ["p"], ["k"])]
    got = suggest(org, node_made={"cm": node}, ran_on=lambda _t: ["p"])
    assert got["hosts"]["cm"] == {"logins": {"claude-code:/shiftlead/profiles/p": {"name": "p"}}}
    assert got["teams"]["far"]["logins"] == ["claude-code:p"]
    assert got["builtins"]["default"]["logins"] == [], "the set takes the first home team's, and none is on the home"


def test_the_report_prints_each_container_nodes_logins_after_the_homes():
    node = [switchover.Login("claude-code", Path("/shiftlead/profiles/p"), "p", ["p"], ["k"])]
    lines = switchover.report("h", [], [], node_made={"cm": node, "empty": []})
    assert lines[:5] == [
        "h: logins the move would make",
        "  none: no profile here names a registered tool",
        "cm: logins the move would make, a container node",
        "  claude-code:p  /shiftlead/profiles/p  from p",
        "empty: logins the move would make, a container node",
    ]


def test_the_check_and_its_answers_read_a_container_nodes_logins(home, tmp_path, capsys, monkeypatch):
    from sessionorc import containers

    (home / "profiles.yml").write_text(f"profiles:\n  p: {{config_dir: {tmp_path / 'a'}}}\n")
    team = {"repo": "r", "host": "cm", "manager": {"role": "person"}, "members": [{"role": "grinder", "profile": "q"}]}
    (home / "org.yml").write_text(yaml.safe_dump({"teams": {"grind": team}}))
    node = Node(home / "nodes" / "cm", "profiles:\n  q: {config_dir: /shiftlead/profiles/q}\n")
    monkeypatch.setattr(containers, "container_nodes", lambda: {"cm": node})
    monkeypatch.setattr(cli.hosts, "nodes", lambda: {"cm": {"container": {"devcontainer": "/x"}}})
    cli.main(["switch-over", "check", "--answers"])
    out = capsys.readouterr().out
    assert "cm: logins the move would make, a container node\n  claude-code:q  /shiftlead/profiles/q  from q" in out
    doc = yaml.safe_load((home / "switch-over" / "answers.yml").read_text())
    assert doc["hosts"]["cm"] == {"logins": {"claude-code:/shiftlead/profiles/q": {"name": "q"}}}
    assert doc["teams"]["grind"]["logins"] == ["claude-code:q"]
    assert "a login cm would not have" not in out and "has no name in the answers" not in out


# -- `--host`: one ssh node's own part (§4.9e *The window* step 2) ----------------------------------------------------


def test_check_host_answers_writes_this_hosts_part_alone_and_the_check_accepts_it(home, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.hosts, "is_node", lambda: True)
    (home / "profiles.yml").write_text(f"profiles:\n  p: {{config_dir: {tmp_path / 'a'}}}\n")
    (home / "org.yml").write_text("teams: [")  # a node reads no org: the check never asks for it
    before = {f: f.read_bytes() for f in home.rglob("*") if f.is_file()}
    assert cli.main(["switch-over", "check", "--host"]) == 1, "no answers file yet"
    assert {f: f.read_bytes() for f in home.rglob("*") if f.is_file()} == before, "the home's files are untouched"
    assert cli.main(["switch-over", "check", "--host", "--answers"]) == 0
    out = capsys.readouterr().out
    doc = yaml.safe_load((home / "switch-over" / "answers.yml").read_text())
    assert doc == {
        "hosts": {"h": {"logins": {f"claude-code:{switchover.shown((tmp_path / 'a').resolve())}": {"name": "p"}}}}
    }
    assert "teams the answers give" not in out and "work in flight" not in out and "the org" not in out
    assert out.rstrip().endswith("no blockers")
    answers(home, {"hosts": {"h": {"logins": {}}}})
    assert cli.main(["switch-over", "check", "--host"]) == 1
    assert "has no name in the answers" in capsys.readouterr().out


# -- the Done when: a home shaped like today's ------------------------------------------------------------------


def test_a_home_shaped_like_todays_is_checked_whole_and_its_files_left_as_they_are(home, tmp_path, capsys, monkeypatch):
    from sessionorc import containers

    on = {
        "a": ["paul", "grind", "design"],
        "b": ["fable"],
        "c": ["sonnet", "audit"],
        "d": ["cm"],
        "e": ["spare", "later"],
    }
    lines = [f"  {p}: {{config_dir: {tmp_path / f}, account: {ps[0]}}}" for f, ps in on.items() for p in ps]
    lines.append(f"  reader: {{config_dir: {tmp_path / 'g'}, account: reader}}")
    (home / "profiles.yml").write_text("default: paul\nprofiles:\n" + "\n".join(lines) + "\n")

    def team(repo: str, profile: str, host: str = "") -> dict:
        got = {"repo": repo, "manager": {"role": "person"}, "flows": ["td"]}
        got["members"] = [{"role": "grinder", "count": 2, "profile": profile}]
        return {**got, "host": host} if host else got

    teams = {f"t{i}": team(f"r{i}", p) for i, p in enumerate(("paul", "grind", "fable", "sonnet", "audit"), 1)}
    teams["far"] = team("rcm", "q", "cm")
    (home / "org.yml").write_text(yaml.safe_dump({"teams": teams}))
    node = Node(home / "nodes" / "cm", "profiles:\n  q: {config_dir: /shiftlead/profiles/q}\n")
    monkeypatch.setattr(containers, "container_nodes", lambda: {"cm": node})
    monkeypatch.setattr(cli.hosts, "nodes", lambda: {"cm": {"container": {"devcontainer": "/x"}}})
    prs = [Pr(10, "td1-x"), Pr(11, "td2-y", draft=True), Pr(13, "td1-td2-both")]
    reading = {"name": "r1", "ledger": {"entries": [Entry("TD-1"), Entry("TD-2")]}, "prs": {"open": prs}}
    (home / "repos.json").write_text(json.dumps({"/nowhere/r1": reading}))
    before = {f: f.read_bytes() for f in home.rglob("*") if f.is_file()}
    assert cli.main(["switch-over", "check"]) == 1, "no answers file: a blocker to cure beforehand"
    assert {f: f.read_bytes() for f in home.rglob("*") if f.is_file()} == before, "the check changes nothing"
    capsys.readouterr()
    assert cli.main(["switch-over", "check", "--answers"]) == 0
    out = capsys.readouterr().out
    home_logins = out.split("h: logins the move would make\n")[1].split("cm: logins")[0].splitlines()
    assert [ln.split()[0] for ln in home_logins] == [
        "claude-code:paul", "claude-code:fable", "claude-code:sonnet", "claude-code:cm", "claude-code:spare",
        "claude-code:reader",
    ], "ten profiles on six folders make six logins, each named for its folder's first profile"  # fmt: skip
    assert "cm: logins the move would make, a container node\n  claude-code:q  /shiftlead/profiles/q  from q" in out
    team_part = out.split("teams the answers give\n")[1].split("the built-in set")[0]
    assert [ln.split(":")[0].strip() for ln in team_part.splitlines() if not ln.startswith("    ")] == [
        "far", "t1", "t2", "t3", "t4", "t5",
    ], "six teams"  # fmt: skip
    for name in ("t1", "t2", "t3", "t4", "t5", "far"):
        assert f"  {name}: " in out and "flow design-wise" in out.split(f"  {name}: ")[1].splitlines()[0]
    assert "    taken up with its pull request: TD-1 #10 (td1-x)" in out
    assert "    waits, offered to nobody: TD-2 — #11 is a draft" in out
    assert "    nothing will read: td1-td2-both — #13 holds TD-1, TD-2" in out
    assert "no blockers" in out
    answers_file = home / "switch-over" / "answers.yml"
    assert cli.main(["switch-over", "check"]) == 0
    after = {f: f.read_bytes() for f in home.rglob("*") if f.is_file() and f != answers_file}
    assert after == before, "only the answers file is new"


def test_check_host_answers_on_a_home_writes_nothing(home, tmp_path, capsys):
    (home / "profiles.yml").write_text(f"profiles:\n  p: {{config_dir: {tmp_path / 'a'}}}\n")
    assert cli.main(["switch-over", "check", "--host", "--answers"]) == 1
    assert "an ssh node's" in capsys.readouterr().err
    assert not (home / "switch-over").exists(), "the home's answers file is the whole one, written by --answers alone"
