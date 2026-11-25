"""The switch-over's check: the logins a host's profiles make, named by the answers file, each team with what the
answers give it, and the blockers to cure beforehand (design §4.9e *The three commands*, *Blockers*, §4.2b *What the
switch-over makes*, TD-2071)."""

from __future__ import annotations

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
def test_each_adapter_skips_with_the_args_its_launch_adds(adapter):
    assert adapter.skip_args and switchover._asks(adapter, []) is False
    assert switchover._asks(adapter, list(adapter.skip_args)) is False
    assert switchover._asks(adapter, ["--other"]) is True
