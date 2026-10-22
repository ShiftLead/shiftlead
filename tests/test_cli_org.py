"""`ao org` and `ao org check` (design §4.7, §4.9 *The org is an aggregate*; TD-229 slice 6): the
org as the clients aggregate it, and the same reading as a verdict. The RPC is mocked as
`test_cli_teams.py` mocks it; the checkouts are real git repos, since the warnings are git's."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from sessionorc import defs
from shiftlead import cli

pytestmark = pytest.mark.unit

HOST = "kmaster"
TEAM = {"manager": {"role": "person"}, "members": [{"role": "hunter"}]}


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


def repo(root: Path, teams: dict | None = None) -> Path:
    """A checkout on `main` with one commit, `origin/HEAD` naming `main`, and its `.shiftlead.yml`."""
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    (root / ".gitignore").write_text(".worktrees/\n")
    if teams is not None:
        (root / ".shiftlead.yml").write_text(yaml.safe_dump({"teams": teams}))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return root


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A temp home with `org.yml` and `profiles.yml`, a registry of two checkouts (`alpha` defines
    a team, `beta` none), one linked node `devenv` whose registry is empty, and an agent that
    answers nothing else — a check needs nothing else."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    registry = home / "repos.txt"
    registry.write_text(f"{tmp_path / 'alpha'}\n{tmp_path / 'beta'}\n")
    monkeypatch.setattr(
        cli.hosts,
        "local_host",
        lambda: cli.hosts.Host(name=HOST, vscode_host=HOST, local=True, repos_registry=registry),
    )
    monkeypatch.setattr(cli.hosts, "is_node", lambda: False)
    monkeypatch.setattr(cli.hosts, "nodes", lambda: {"devenv": {}})
    repo(tmp_path / "alpha", {"alpha-grind": TEAM})
    repo(tmp_path / "beta")
    (home / "profiles.yml").write_text(yaml.safe_dump({"default": "paul", "profiles": {"paul": {"account": "paul"}}}))
    org = {
        "projects": {"both": {"repos": {"alpha": {HOST: str(tmp_path / "alpha")}}}},
        "teams": {
            "span": {
                "repo": "alpha",
                "manager": {"role": "person"},
                "members": [{"role": "hunter", "name": "span-hunt"}],
            }
        },
    }
    (home / "org.yml").write_text(yaml.safe_dump(org))

    def no_agent(method, **params):
        if method == "host_repos" and params.get("host") == "devenv":
            return {"repos": []}  # the linked node holds nothing the home does not (TD-318)
        raise cli.AgentError(f"unknown method: {method}")

    monkeypatch.setattr(cli, "call_sync", no_agent)
    monkeypatch.chdir(home)
    return tmp_path, home, org


def check(capsys) -> tuple[int, dict]:
    code = cli.main(["--json", "org", "check"])
    return code, json.loads(capsys.readouterr().out)


def test_ao_org_prints_each_team_its_file_its_repo_and_where_it_lands(world, capsys):
    tmp_path, home, _ = world
    assert cli.main(["--json", "org"]) == 0
    got = json.loads(capsys.readouterr().out)
    rows = {r["name"]: r for r in got["teams"]}
    assert rows["alpha-grind"] == {
        "name": "alpha-grind",
        "source": str(tmp_path / "alpha" / ".shiftlead.yml"),
        "repo": "alpha",
        "project": "both",
        "host": HOST,
        "why": "registered here",
    }
    # the org file's own team has no landing rule: its `host:`, or where it is started
    assert rows["span"]["source"] == str(home / "org.yml") and rows["span"]["host"] == HOST
    assert rows["span"]["why"].startswith("no host:")
    # the remainder: the three files, none with a history until the home is a work tree
    rem = got["remainder"]
    assert rem["tree"] is False and [f["name"] for f in rem["files"]] == list(defs.TRACKED)
    assert {f["name"]: f["exists"] for f in rem["files"]} == {
        "org.yml": True,
        "profiles.yml": True,
        "settings.yml": False,
    }
    assert cli.main(["org"]) == 0
    out = capsys.readouterr().out
    src = tmp_path / "alpha" / ".shiftlead.yml"
    assert f"alpha-grind  repo: alpha  project: both  on {HOST} (registered here)  [{src}]" in out
    assert "no history yet" in out and "settings.yml  not there" in out


def test_ao_org_says_a_placed_a_shadowed_and_a_twice_named_team_and_each_files_last_commit(world, capsys):
    tmp_path, home, org = world
    (tmp_path / "alpha" / ".shiftlead.yml").write_text(
        yaml.safe_dump({"teams": {"alpha-grind": TEAM, "twice": TEAM, "span": TEAM}})
    )
    (tmp_path / "beta" / ".shiftlead.yml").write_text(yaml.safe_dump({"teams": {"twice": TEAM}}))
    org["projects"]["both"] = {"repos": {"alpha": {HOST: str(tmp_path / "alpha"), "devenv": "/work/alpha"}}}
    assert defs.init(home)
    (home / "org.yml").write_text(yaml.safe_dump({**org, "place": {"alpha-grind": "devenv"}}))
    assert defs.commit("org: placed alpha-grind", home=home)
    assert cli.main(["org"]) == 0
    out = capsys.readouterr().out
    assert "alpha-grind  repo: alpha  project: both  on devenv (place)" in out
    assert f"span         shadowed by org.yml  [{tmp_path / 'alpha' / '.shiftlead.yml'}]" in out
    assert "twice        refused: team 'twice' is defined twice" in out and out.count("defined twice") == 1
    # each file's last commit, the one never written said so
    assert "org: placed alpha-grind" in out and "no history yet" not in out
    assert "the home's definitions, first tracked" in out and "settings.yml  not there" in out


def test_a_whole_org_checks_ok_and_exits_0(world, capsys):
    code, got = check(capsys)
    assert (code, got) == (0, {"ok": True, "lacks": [], "warnings": []})
    assert cli.main(["org", "check"]) == 0
    assert capsys.readouterr().out.strip() == "ok: 2 teams"


def test_a_registered_checkout_that_is_not_there_is_lacking(world, capsys):
    tmp_path, home, _ = world
    (home / "repos.txt").write_text(f"{tmp_path / 'alpha'}\n{tmp_path / 'beta'}\n{tmp_path / 'gone'}\n")
    code, got = check(capsys)
    assert code == 1 and got["ok"] is False
    assert [x for x in got["lacks"] if "a registered checkout that is not there" in x] == [got["lacks"][0]]
    assert str(tmp_path / "gone") in got["lacks"][0]
    assert cli.main(["org", "check"]) == 1
    out = capsys.readouterr().out
    assert f"lacking: {tmp_path / 'gone'}" in out and out.strip().endswith("1 lacking")


def test_a_checkout_holding_only_the_old_agentorc_file_is_lacking_naming_the_rename(world, capsys):
    tmp_path, home, _ = world
    old = tmp_path / "old"
    old.mkdir()
    (old / ".agentorc.yml").write_text("ledger: docs/ledger.md\n")
    (home / "repos.txt").write_text(f"{tmp_path / 'alpha'}\n{tmp_path / 'beta'}\n{old}\n")
    code, got = check(capsys)
    assert code == 1
    assert [x for x in got["lacks"] if ".agentorc.yml" in x] == [
        f"{old}: its .agentorc.yml is read by nothing — rename it .shiftlead.yml (TD-553)"
    ]
    (old / ".shiftlead.yml").write_text("ledger: docs/ledger.md\n")  # renamed: the stale file beside it says nothing
    code, got = check(capsys)
    assert not [x for x in got["lacks"] if ".agentorc.yml" in x]


def test_a_settings_team_no_definition_names_is_lacking(world, capsys):
    _, home, _ = world
    kept = {"alpha-grind": {"reserve": 5}, "old": {"reserve": 5}}
    (home / "settings.yml").write_text(yaml.safe_dump({"teams": kept}))
    code, got = check(capsys)
    assert code == 1 and len(got["lacks"]) == 1
    assert got["lacks"][0].startswith("settings.yml: teams.old — no definition names a team 'old'")


def test_a_profile_not_held_a_missing_brief_and_a_place_on_no_linked_host_are_each_lacking(world, capsys):
    tmp_path, home, org = world
    teams_ = {
        "alpha-grind": {**TEAM, "members": [{"role": "hunter", "profile": "nope"}]},
        "alpha-brief": {**TEAM, "members": [{"role": "hunter", "name": "hunt-b", "brief": "docs/briefs/absent.md"}]},
        "alpha-far": {**TEAM, "members": [{"role": "hunter", "name": "hunt-far"}]},
    }
    (tmp_path / "alpha" / ".shiftlead.yml").write_text(yaml.safe_dump({"teams": teams_}))
    git(tmp_path / "alpha", "commit", "-qam", "teams")
    org["projects"]["both"] = {"repos": {"alpha": {HOST: str(tmp_path / "alpha"), "mars": "/work/alpha"}}}
    (home / "org.yml").write_text(yaml.safe_dump({**org, "place": {"alpha-far": "mars"}}))
    code, got = check(capsys)
    assert code == 1
    lacks = "\n".join(got["lacks"])
    assert "unknown profile 'nope'" in lacks
    assert "absent.md" in lacks
    assert "place.alpha-far: mars is no linked host of kmaster (devenv)" in lacks
    assert len([x for x in got["lacks"] if x.startswith("team alpha-grind:")]) == 1  # one line per lack


def test_a_name_defined_twice_is_lacking_once(world, capsys):
    tmp_path, _, _ = world
    (tmp_path / "beta" / ".shiftlead.yml").write_text(yaml.safe_dump({"teams": {"alpha-grind": TEAM}}))
    git(tmp_path / "beta", "add", "-A")
    git(tmp_path / "beta", "commit", "-qm", "a team")
    code, got = check(capsys)
    assert code == 1 and len(got["lacks"]) == 1 and "defined twice" in got["lacks"][0]


def test_a_team_naming_one_session_twice_is_lacking(world, capsys):
    """TD-268: Add member once wrote a member's name a second time; the check says a definition that holds one."""
    tmp_path, home, org = world
    org["teams"]["span"]["members"] = [{"role": "hunter"}, {"role": "grinder", "name": "hunter"}]
    (home / "org.yml").write_text(yaml.safe_dump(org))
    code, got = check(capsys)
    assert code == 1
    assert [x for x in got["lacks"] if "twice" in x] == [
        "team span names hunter twice — take one of its lines out of org.yml (Members… → Remove keeps the session)"
    ]
    # a repo's team is changed by PR: no Members… hint
    org["teams"]["span"]["members"] = [{"role": "hunter", "name": "span-hunt"}]
    (home / "org.yml").write_text(yaml.safe_dump(org))
    (tmp_path / "alpha" / ".shiftlead.yml").write_text(
        yaml.safe_dump({"teams": {"alpha-grind": {**TEAM, "members": [{"role": "hunter"}, {"role": "hunter"}]}}})
    )
    git(tmp_path / "alpha", "commit", "-qam", "twice")
    _, got = check(capsys)
    assert "team alpha-grind names hunter twice — take one of its lines out of .shiftlead.yml" in got["lacks"]


def test_a_name_two_teams_on_one_repo_give_is_lacking_naming_both(world, capsys):
    """§4.9 *Names are the org's*: an agent's name is its repo's, so the org file's `span` and alpha's
    own `alpha-grind`, both on alpha, cannot both start a `hunter`; the check names the two and the name."""
    tmp_path, home, org = world
    org["teams"]["span"]["members"] = [{"role": "hunter"}]
    (home / "org.yml").write_text(yaml.safe_dump(org))
    code, got = check(capsys)
    assert code == 1
    assert any(
        "teams span and alpha-grind both start a session called 'hunter' on alpha — an agent's name is its repo's" in x
        for x in got["lacks"]
    ), got["lacks"]


def test_a_checkout_off_its_default_branch_or_holding_changes_warns_and_does_not_fail(world, capsys):
    tmp_path, home, org = world
    git(tmp_path / "beta", "checkout", "-q", "-b", "topic")
    (tmp_path / "alpha" / "scratch.txt").write_text("x")
    # a `place:` naming a team no registered repo defines is the aggregate's note, and a warning here
    (home / "org.yml").write_text(yaml.safe_dump({**org, "place": {"alpha-grnd": "devenv"}}))
    code, got = check(capsys)
    assert code == 0 and got["ok"] is True and got["lacks"] == []
    warned = "\n".join(got["warnings"])
    assert f"{tmp_path / 'beta'}: on topic, not its default branch main" in warned
    assert f"{tmp_path / 'alpha'}: holds 1 change " in warned
    assert "place.alpha-grnd: no registered repo defines a team 'alpha-grnd'" in warned
    assert cli.main(["org", "check"]) == 0
    assert capsys.readouterr().out.strip().endswith("ok: 2 teams, 3 warnings")


def test_on_a_node_both_refuse_and_name_the_home(world, capsys, monkeypatch):
    monkeypatch.setattr(cli.hosts, "is_node", lambda: True)
    monkeypatch.setattr(cli.hosts, "home_name", lambda: "homebox")
    assert cli.main(["org"]) == 1
    assert "the org lives on homebox (home): run `ao org` there" in capsys.readouterr().err
    assert cli.main(["org", "check"]) == 1
    assert "run `ao org check` there" in capsys.readouterr().err


def test_an_org_file_that_cannot_be_read_fails_the_check_in_its_own_words(world, capsys):
    _, home, _ = world
    (home / "org.yml").write_text(yaml.safe_dump({"teams": {"x": {"lead": "y"}}}))
    assert cli.main(["org", "check"]) == 1
    assert "org.yml: teams.x" in capsys.readouterr().err


def test_neither_writes_a_file_or_calls_anything_that_changes_a_record(world, capsys, monkeypatch):
    tmp_path, home, _ = world
    calls: list[str] = []

    def recording(method, **params):
        calls.append(method)
        raise cli.AgentError(f"unknown method: {method}")

    monkeypatch.setattr(cli, "call_sync", recording)
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert cli.main(["org"]) == 0 and cli.main(["org", "check"]) == 0
    capsys.readouterr()
    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert after == before
    assert set(calls) <= {"host_repos", "host_files", "host_dir", "repos"}  # reads, when anything is asked at all


def test_a_place_on_a_host_whose_registry_cannot_be_asked_is_one_lack_not_two(world, capsys):
    """The review of #833: the landing's own note already says the host could not be read."""
    _, home, org = world
    (home / "org.yml").write_text(yaml.safe_dump({**org, "place": {"alpha-grind": "mars"}}))
    code, got = check(capsys)
    assert code == 1 and len(got["lacks"]) == 1
    assert "`place:` puts it on mars, whose registry could not be read" in got["lacks"][0]


def test_a_repo_held_only_on_a_node_is_listed_and_warned_of_and_an_unread_registry_said(world, capsys, monkeypatch):
    """§4.9 *A definition is read at the home, and only there* (TD-318): a repo a linked node's
    registry holds that the home's does not is listed by `ao org` and warned of by its check, which
    still exits 0; a node whose registry cannot be read is said so, never read as holding nothing."""
    tmp_path, _, _ = world
    regs = {"devenv": ["/workspaces/sam", "/workspaces/alpha", "/w/sam"]}

    def agent(method, **params):
        if method == "host_repos" and params.get("host") in regs:
            return {"repos": regs[params["host"]]}
        raise cli.AgentError(f"unknown method: {method}")

    monkeypatch.setattr(cli, "call_sync", agent)
    line = f"sam — held only on devenv: its .shiftlead.yml is not read; register a checkout at {HOST}"
    code, got = check(capsys)
    assert (code, got["warnings"]) == (0, [line])  # alpha is held here too; sam is said once
    assert cli.main(["--json", "org"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["held_elsewhere"] == [{"host": "devenv", "repo": "sam", "path": "/workspaces/sam"}]
    assert got["unread"] == []
    assert cli.main(["org"]) == 0
    assert line in capsys.readouterr().out
    # the node does not answer: one note, and nothing read as held nowhere
    regs.clear()
    code, got = check(capsys)
    assert code == 0 and len(got["warnings"]) == 1
    assert got["warnings"][0].startswith("devenv: its registry could not be read (")
    assert cli.main(["org"]) == 0
    out = capsys.readouterr().out
    assert "note: devenv: its registry could not be read (" in out and "held only on" not in out


def _reading(world, monkeypatch, led: dict) -> None:
    """The home's `repos` reading of `alpha`, which `ao org check` reads the ledger's Team from (TD-763)."""
    tmp_path = world[0]
    base = cli.call_sync

    def agent(method, **params):
        if method == "repos":
            return {str(tmp_path / "alpha"): {"name": "alpha", "ledger": led}}
        return base(method, **params)

    monkeypatch.setattr(cli, "call_sync", agent)


def test_a_declared_name_no_definition_holds_is_lacking_and_names_its_entries(world, monkeypatch, capsys):
    """§4.4 *A stale team*: alpha holds alpha-grind and span; `gone` is declared and defined nowhere."""
    entries = [{"id": "TD-001", "team": "gone"}, {"id": "TD-002", "team": "span"}]
    _reading(world, monkeypatch, {"declared_teams": ["alpha-grind", "span", "gone"], "entries": entries})
    code, got = check(capsys)
    assert code == 1 and len(got["lacks"]) == 1
    assert got["lacks"][0].startswith(
        "alpha: its ledger declares team gone, which no definition of the repo holds (TD-001 carry it)"
    )


@pytest.mark.parametrize("declared", [[], ["span"]])
def test_a_team_of_a_two_team_repo_its_ledger_does_not_declare_is_lacking(world, monkeypatch, capsys, declared):
    """§4.4 *The move from one team to two* (TD-791): the remedy names the declared teams and every left-out one,
    so following it declares what was missing."""
    _reading(world, monkeypatch, {"declared_teams": declared, "entries": []})
    code, got = check(capsys)
    assert code == 1 and len(got["lacks"]) == 2 - len(declared)
    assert any(
        x.startswith("alpha: has 2 teams and its ledger's Fields: line does not declare alpha-grind")
        for x in got["lacks"]
    )
    assert all("add `Team = span | alpha-grind`, and a Team: line" in x for x in got["lacks"])


def test_a_declared_name_differing_from_its_definition_by_case_is_no_lack(world, monkeypatch, capsys):
    """§4.4 *A stale team* (TD-777): a declared name is held by a definition case-folded — `ALPHA-GRIND`
    and `Span` against alpha-grind and span are both declared and both held."""
    _reading(world, monkeypatch, {"declared_teams": ["ALPHA-GRIND", "Span"], "entries": []})
    code, got = check(capsys)
    assert (code, got["lacks"]) == (0, [])


def test_a_ledger_that_did_not_parse_says_no_lack(world, monkeypatch, capsys):
    """§4.4 (TD-777): a reading whose ledger carries `error` says nothing, though what it holds would lack."""
    _reading(world, monkeypatch, {"declared_teams": ["gone"], "entries": [], "error": "no Fields: line"})
    code, got = check(capsys)
    assert (code, got["lacks"]) == (0, [])


def test_entries_that_need_a_team_where_no_team_has_a_techlead_seat_are_lacking(world, monkeypatch, capsys):
    led = {"declared_teams": ["alpha-grind", "span"], "entries": [], "needs_team": ["TD-003"]}
    _reading(world, monkeypatch, led)
    code, got = check(capsys)
    assert code == 1 and got["lacks"] == [
        "alpha: TD-003 need a team, and no team of the repo has a techlead seat to tag them — tag them by PR, "
        "or give a team a techlead (design §4.4 An entry names its team)"
    ]


# ── `ao org check --root <dir>` (design §4.7, TD-942) ───────────────────────────────────────────


def branch(world, teams: dict | None = None, name: str = "topic") -> Path:
    """A worktree of `alpha` on a branch of its own, outside the checkout and named unlike it, its
    `.shiftlead.yml` holding `teams` (as committed on the branch, never merged)."""
    tmp_path = world[0]
    wt = tmp_path / f"wt-{name}"
    git(tmp_path / "alpha", "worktree", "add", "-q", "-b", name, str(wt))
    if teams is not None:
        (wt / ".shiftlead.yml").write_text(yaml.safe_dump({"teams": teams}))
        git(wt, "commit", "-qam", "teams on the branch")
    return wt


def check_at(capsys, wt: Path | str) -> tuple[int, dict]:
    code = cli.main(["--json", "org", "check", "--root", str(wt)])
    return code, json.loads(capsys.readouterr().out)


def test_a_branch_naming_a_profile_not_held_lacks_it_before_it_merges(world, capsys):
    """Done when: the profile `profiles.yml` lacks is named from the branch, the same file unmerged;
    the first line and `--json`'s `root` name the repo (the checkout's name, not the worktree's) and `<dir>`."""
    wt = branch(world, {"alpha-grind": {**TEAM, "members": [{"role": "hunter", "profile": "nope"}]}})
    assert check(capsys) == (0, {"ok": True, "lacks": [], "warnings": []})  # main does not have it
    code, got = check_at(capsys, wt)
    assert code == 1 and got["root"] == {"repo": "alpha", "dir": str(wt.resolve())}
    assert len(got["lacks"]) == 1 and "unknown profile 'nope'" in got["lacks"][0]
    assert got["warnings"] == []  # no off-branch warning for `<dir>`, and nothing the plain run does not give
    assert cli.main(["org", "check", "--root", str(wt)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"checking alpha at {wt.resolve()}" and out[-1] == "1 lacking"


def test_without_root_the_json_carries_no_root_key(world, capsys):
    _, got = check(capsys)
    assert "root" not in got


def test_a_brief_only_the_branch_holds_is_read_at_dir_over_the_org_files_path(world, capsys):
    """The org file's heading gives alpha's path on this host; `--root` reads the branch's briefs all the same."""
    teams_ = {"alpha-grind": {**TEAM, "members": [{"role": "hunter", "brief": "docs/briefs/new.md"}]}}
    wt = branch(world)
    (wt / ".shiftlead.yml").write_text(yaml.safe_dump({"teams": teams_}))
    (wt / "docs" / "briefs").mkdir(parents=True)
    (wt / "docs" / "briefs" / "new.md").write_text("the brief\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "a brief")
    (world[0] / "alpha" / ".shiftlead.yml").write_text(yaml.safe_dump({"teams": teams_}))  # main lacks the brief
    git(world[0] / "alpha", "commit", "-qam", "names the brief")
    code, got = check(capsys)
    assert code == 1 and any("new.md" in x for x in got["lacks"])
    code, got = check_at(capsys, wt)
    assert (code, got["lacks"]) == (0, []), got


def test_the_ledger_as_merged_is_paired_with_the_branchs_teams(world, monkeypatch, capsys):
    """A `Team` declaration on main naming a team only the branch defines reads clean with `--root`, a
    lack without it; a branch that drops a team the ledger still declares reads that lack."""
    _reading(world, monkeypatch, {"declared_teams": ["alpha-grind", "span", "fresh"], "entries": []})
    wt = branch(world, {"alpha-grind": TEAM, "fresh": {**TEAM, "members": [{"role": "hunter", "name": "fresh-h"}]}})
    code, got = check(capsys)
    assert code == 1 and any("declares team fresh" in x for x in got["lacks"])
    code, got = check_at(capsys, wt)
    assert (code, got["lacks"]) == (0, []), got
    dropped = branch(world, {"fresh": {**TEAM, "members": [{"role": "hunter", "name": "fresh-h"}]}}, "drop")
    code, got = check_at(capsys, dropped)
    assert code == 1 and [x for x in got["lacks"] if "declares team" in x] == [
        "alpha: its ledger declares team alpha-grind, which no definition of the repo holds — drop it from the "
        "Fields: line's Team, or add it back, by PR (design §4.4 A stale team)"
    ]


def test_a_branch_renaming_the_old_repo_file_reads_no_td553_lack(world, capsys):
    tmp_path, _, _ = world
    alpha = tmp_path / "alpha"
    git(alpha, "mv", ".shiftlead.yml", ".agentorc.yml")
    git(alpha, "commit", "-qm", "the old name")
    wt = branch(world)
    git(wt, "mv", ".agentorc.yml", ".shiftlead.yml")
    git(wt, "commit", "-qm", "renamed")
    _, got = check(capsys)
    assert any(".agentorc.yml is read by nothing" in x for x in got["lacks"])
    code, got = check_at(capsys, wt)
    assert not [x for x in got["lacks"] if ".agentorc.yml" in x], got


def test_root_at_the_registered_checkout_reads_as_without_it_but_for_the_header_and_its_state(world, capsys):
    tmp_path, _, _ = world
    alpha = tmp_path / "alpha"
    (alpha / "scratch.txt").write_text("x")
    git(tmp_path / "beta", "checkout", "-q", "-b", "elsewhere")
    code, plain = check(capsys)
    code_at, got = check_at(capsys, alpha)
    assert code == code_at == 0 and got["root"] == {"repo": "alpha", "dir": str(alpha.resolve())}
    assert got["lacks"] == plain["lacks"]
    # alpha's change is not warned of with `--root`; beta, read as without it, still is
    assert [w for w in plain["warnings"] if str(alpha) not in w] == got["warnings"] and len(got["warnings"]) == 1


@pytest.mark.parametrize("where", ["sub", "dotgit", "outside", "plain"])
def test_a_dir_that_is_no_checkout_of_a_registered_repo_is_refused_exit_2(world, capsys, where):
    tmp_path, _, _ = world
    if where == "sub":
        d = branch(world) / "docs"
        d.mkdir()
    elif where == "dotgit":
        d = tmp_path / "alpha" / ".git"
    elif where == "outside":
        d = repo(tmp_path / "stranger")
    else:
        d = tmp_path / "nogit"
        d.mkdir()
    assert cli.main(["--json", "org", "check", "--root", str(d)]) == 2
    assert json.loads(capsys.readouterr().out) == {"error": f"{d} is not a checkout of a registered repo"}


def test_only_check_takes_root(world, capsys):
    assert cli.main(["org", "--root", str(world[0] / "alpha")]) == 2
    assert "only `ao org check` takes --root" in capsys.readouterr().err


def test_a_team_placed_on_another_host_warns_its_briefs_are_read_there(world, capsys, monkeypatch):
    tmp_path, home, org = world
    org["projects"]["both"] = {"repos": {"alpha": {HOST: str(tmp_path / "alpha"), "devenv": "/work/alpha"}}}
    (home / "org.yml").write_text(yaml.safe_dump({**org, "place": {"alpha-grind": "devenv"}}))
    monkeypatch.setattr(cli.teamrun, "files_via", lambda call: lambda host, d, paths: dict.fromkeys(paths, "x"))
    wt = branch(world)
    _, plain = check(capsys)
    assert not [w for w in plain["warnings"] if "briefs read on" in w]
    _, got = check_at(capsys, wt)
    assert f"alpha-grind: briefs read on devenv's checkout, not at {wt.resolve()}" in got["warnings"]


def test_a_role_directory_only_the_branch_holds_is_read_at_dir(world, capsys):
    """The role directories are read at `<dir>`: one the branch adds that is not whole is named with `--root` alone."""
    wt = branch(world)
    (wt / ".shiftlead" / "roles" / "scout").mkdir(parents=True)
    (wt / ".shiftlead" / "roles" / "scout" / "role.yml").write_text("kind: worker\n")
    _, plain = check(capsys)
    assert not [x for x in plain["lacks"] if "role scout" in x]
    code, got = check_at(capsys, wt)
    assert code == 1 and [x for x in got["lacks"] if x.startswith("role scout (")], got
