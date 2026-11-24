"""TD-2150: a repo's YAML file nested past the parser's depth is a bad file to every sessionorc reader of it, never a
RecursionError out of the read."""

from __future__ import annotations

import pytest
import yaml

from sessionorc import briefs, gitinfo, held, ledger, promote, settle, sync, workorders, yamltext
from shiftlead import stage_end

DEEP = "promote: " + "[" * 5000 + "\n"


def test_the_reader_raises_a_yaml_error_for_a_text_nested_too_deeply():
    with pytest.raises(yaml.YAMLError, match="nested too deeply"):
        yamltext.load(DEEP)
    assert yamltext.load("a: [1]\n") == {"a": [1]}
    assert yamltext.load("") is None


def test_the_promote_read_reports_a_file_nested_too_deeply_as_unreadable(tmp_path):
    (tmp_path / ".shiftlead.yml").write_text(DEEP)
    with pytest.raises(ValueError, match="cannot be read: YAMLError"):
        promote.block(tmp_path)


def test_every_other_repo_file_reader_reads_a_file_nested_too_deeply_as_no_reading(tmp_path):
    (tmp_path / ".shiftlead.yml").write_text(DEEP)
    assert sync.held_globs(tmp_path) is None
    assert settle.repo_settle(tmp_path) == {}
    assert ledger.ledger_set(tmp_path) is None
    assert held.repo_key(tmp_path, []) == []
    assert gitinfo.worktree_setup(tmp_path) == ("absent", None)
    assert workorders.board_path(tmp_path) == ("absent", None)


def test_an_org_flow_nested_too_deeply_is_named_unreadable(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    d = tmp_path / "flows" / "deep"
    d.mkdir(parents=True)
    (d / briefs.FLOW_FILE).write_text("format: 3\nstages: " + "[" * 5000)
    assert briefs.flows_naming("builder") == ["deep (unreadable)"]


def test_a_stored_flow_nested_too_deeply_is_a_refusal_of_the_stage_end_call(monkeypatch):
    class Store:
        def __init__(self, root):
            pass

        def flow(self, team):
            return "format: 3\nstages: " + "[" * 5000

    monkeypatch.setattr(stage_end, "StageStore", Store)
    got = stage_end.call(
        root="/nowhere", directory="/nowhere", team="t", tid="TD-1", caller="s", outcome="done", reason=""
    )
    assert got == {"refused": "team t's flow on the state branch cannot be read"}


def test_every_home_file_reader_reads_a_file_nested_too_deeply_as_a_bad_file(tmp_path, monkeypatch):
    """TD-2154: the home's own YAML files, which only the person writes, were still read by a bare `yaml.safe_load`,
    so one nested past the parser's depth crashed its reader where a bad file is reported."""
    from sessionorc import agent_doctor, containers, defs, hosts, logins
    from sessionorc import settings as settings_mod
    from shiftlead import org, profiles
    from shiftlead.ui import settings_page

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    for name in ("settings.yml", "hosts.yml", "logins.yml", "profiles.yml", "org.yml"):
        (tmp_path / name).write_text(DEEP)
    settings = tmp_path / "settings.yml"
    assert agent_doctor._parse_error(settings) == "nested too deeply to read"  # `ao doctor` names it invalid
    assert settings_mod.load(settings) == {} and settings_mod.read(settings) is None
    assert hosts.home_name() == hosts.local_host().name and hosts.nodes() == {}
    assert settings_page.local_entry(tmp_path / "hosts.yml") == {}
    assert containers.remove_node_entry(tmp_path / "hosts.yml", "desk") is False
    assert defs._parses(settings) is False
    with pytest.raises(logins.LoginError, match="YAMLError"):
        logins.load(tmp_path)
    with pytest.raises(yaml.YAMLError):
        profiles.load(tmp_path / "profiles.yml")
    with pytest.raises(yaml.YAMLError):
        org.load(tmp_path / "org.yml")
