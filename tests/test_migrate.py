"""`ao migrate` and the legacy repo file (TD-060 step 2): the clean cut from agentorc's machine names."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sessionorc import paths
from shiftlead import migrate, repoconfig


def _old_home(root: Path) -> Path:
    old = root / ".agentorc"
    (old / "claude-hooks").mkdir(parents=True)
    (old / "claude-hooks" / "grind.json").write_text('{"command": "/v/agentorc-venv/bin/agentorc-hook"}')
    (old / "launch").mkdir()
    (old / "launch" / "ao-x.json").write_text(
        json.dumps({"env": {"AGENTORC_SESSION": "ao-agentorc-agent-1"}, "cmd": "/h/.agentorc/x /r/.agentorc.yml"})
    )
    (old / "nodes" / "cm" / "home").mkdir(parents=True)
    (old / "nodes" / "cm" / "home" / "hosts.yml").write_text("home: /h/.agentorc/x\n")
    (old / "nodes" / "cm" / "venv" / "bin").mkdir(parents=True)
    (old / "nodes" / "cm" / "profiles" / "grind").mkdir(parents=True)
    (old / "org.yml").write_text("# agentorc org\nprojects:\n  agentorc: {repos: {agentorc: {k: ~/agentorc}}}\n")
    (old / "runs").mkdir()
    (old / "runs" / "big.log").write_text("/h/.agentorc untouched\n")
    return old


def _calls():
    seen: list[tuple[str, ...]] = []

    def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    return seen, systemctl


def test_migrate_moves_the_home_rewrites_its_files_and_removes_the_old_units(tmp_path):
    old = _old_home(tmp_path)
    new = tmp_path / ".shiftlead"
    units = tmp_path / "units"
    units.mkdir()
    for u in migrate.OLD_UNITS:
        (units / f"{u}.service").write_text("[Unit]\n")
    seen, systemctl = _calls()
    done = migrate.run(old=old, new=new, unit_dir=units, sessions=lambda: [], systemctl=systemctl)
    assert not old.exists() and new.is_dir()
    assert not list(units.iterdir())
    assert ("disable", "--now", "agentorc-agent.service", "agentorc-ui.service") in seen
    # the home's directory and the variables change; a repo's file and a session id do not
    assert json.loads((new / "launch" / "ao-x.json").read_text()) == {
        "env": {"SHIFTLEAD_SESSION": "ao-agentorc-agent-1"},
        "cmd": "/h/.shiftlead/x /r/.agentorc.yml",
    }
    assert (new / "nodes" / "cm" / "home" / "hosts.yml").read_text() == "home: /h/.shiftlead/x\n"
    # the project and the repo keep their names; only the machine names change
    assert "agentorc: {repos: {agentorc: {k: ~/agentorc}}}" in (new / "org.yml").read_text()
    assert (new / "runs" / "big.log").read_text() == "/h/.agentorc untouched\n"
    assert not list((new / "claude-hooks").iterdir())
    # a node's venv goes (`ao host up` makes it again); its logins stay
    assert not (new / "nodes" / "cm" / "venv").exists() and (new / "nodes" / "cm" / "profiles" / "grind").is_dir()
    assert any(line.startswith("moved ") for line in done)


@pytest.mark.parametrize(
    ("live", "make_new", "make_old", "why"),
    [
        (["ao-agentorc-guards"], False, True, "still run"),
        ([], True, True, "already exists"),
        ([], False, False, "nothing to migrate"),
    ],
)
def test_migrate_is_refused_with_a_session_running_a_new_home_or_no_old_one(tmp_path, live, make_new, make_old, why):
    old = _old_home(tmp_path) if make_old else tmp_path / ".agentorc"
    new = tmp_path / ".shiftlead"
    if make_new:
        new.mkdir()
    seen, systemctl = _calls()
    with pytest.raises(RuntimeError, match=why):
        migrate.run(old=old, new=new, unit_dir=tmp_path, sessions=lambda: live, systemctl=systemctl)
    assert not seen
    assert old.exists() == make_old


def test_a_repo_that_has_not_renamed_its_file_is_read_from_the_legacy_name(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / paths.LEGACY_REPO_FILE).write_text("ledger: docs/ledger.md\n")
    assert paths.repo_file(tmp_path) == tmp_path / ".agentorc.yml"
    cfg = repoconfig.load(tmp_path)
    assert cfg.path == tmp_path / ".agentorc.yml" and cfg.ledger == "docs/ledger.md"
    assert repoconfig.discover(tmp_path).path == tmp_path / ".agentorc.yml"
    # the new name wins once it is there
    (tmp_path / ".shiftlead.yml").write_text("ledger: docs/new.md\n")
    assert paths.repo_file(tmp_path) == tmp_path / ".shiftlead.yml"
    assert repoconfig.load(tmp_path).ledger == "docs/new.md"


def test_migrate_rewrites_the_venv_and_scripts_reloads_after_the_units_go_and_leaves_symlinks(tmp_path):
    old = _old_home(tmp_path)
    (old / "launch" / "ao-y.json").write_text(json.dumps({"cmd": "/h/agentorc-venv/bin/agentorc-hook agentorc-ui"}))
    (old / "nodes" / "cm" / "home" / "profiles.yml").write_text("hook: /h/agentorc-venv/bin/agentorc-watch\n")
    outside = tmp_path / "outside"
    (outside / "venv").mkdir(parents=True)
    (outside / "linked.yml").write_text("venv: /h/agentorc-venv\n")
    (old / "linked.yml").symlink_to(outside / "linked.yml")
    (old / "nodes" / "dm").mkdir()
    (old / "nodes" / "dm" / "venv").symlink_to(outside / "venv")
    new = tmp_path / ".shiftlead"
    units = tmp_path / "units"
    units.mkdir()
    for u in migrate.OLD_UNITS:
        (units / f"{u}.service").write_text("[Unit]\n")
    seen: list[tuple[str, ...]] = []
    left_at_reload: list[list[Path]] = []

    def systemctl(*args: str) -> subprocess.CompletedProcess[str]:
        seen.append(args)
        if args == ("daemon-reload",):
            left_at_reload.append(list(units.iterdir()))
        return subprocess.CompletedProcess(args, 0, "", "")

    migrate.run(old=old, new=new, unit_dir=units, sessions=lambda: [], systemctl=systemctl)
    assert json.loads((new / "launch" / "ao-y.json").read_text()) == {
        "cmd": "/h/shiftlead-venv/bin/shiftlead-hook shiftlead-ui"
    }
    assert (
        new / "nodes" / "cm" / "home" / "profiles.yml"
    ).read_text() == "hook: /h/shiftlead-venv/bin/shiftlead-watch\n"
    # the reload comes after the disable, once the unit files are gone
    assert seen == [("disable", "--now", "agentorc-agent.service", "agentorc-ui.service"), ("daemon-reload",)]
    assert left_at_reload == [[]]
    # a symlink is followed by neither the rewrite nor the venv removal
    assert (outside / "linked.yml").read_text() == "venv: /h/agentorc-venv\n"
    assert (new / "nodes" / "dm" / "venv").is_symlink() and (outside / "venv").is_dir()


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "want"),
    [
        (0, "ao-a\nao-b\n", "", ["ao-a", "ao-b"]),
        (1, "", "no server running on /tmp/tmux-1000/default\n", []),
        (1, "", "error connecting to /tmp/tmux-1000/default (No such file or directory)\n", []),
        (1, "", "no sessions\n", []),
        (1, "", "lost server\n", ["(tmux: lost server)"]),
        (1, "", "", ["(tmux: unreadable)"]),
    ],
)
def test_live_sessions_reads_a_server_that_errors_as_a_session(monkeypatch, returncode, stdout, stderr, want):
    def run(argv, **kw):
        assert argv[:2] == ["tmux", "list-sessions"]
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr(migrate.subprocess, "run", run)
    assert migrate.live_sessions() == want


def test_live_sessions_without_tmux_is_empty(monkeypatch):
    def run(argv, **kw):
        raise FileNotFoundError("tmux")

    monkeypatch.setattr(migrate.subprocess, "run", run)
    assert migrate.live_sessions() == []


def test_environment_warning_names_the_old_variables(monkeypatch):
    for k in [k for k in migrate.os.environ if k.startswith("AGENTORC_")]:
        monkeypatch.delenv(k)
    assert migrate.environment_warning() is None
    monkeypatch.setenv("AGENTORC_SESSION", "ao-x")
    monkeypatch.setenv("AGENTORC_HOME", "/h")
    assert migrate.environment_warning() == "this shell still carries AGENTORC_HOME, AGENTORC_SESSION: open a new one"


def test_next_steps_put_root_first_then_the_user_units():
    from shiftlead import service

    steps = migrate.next_steps()
    assert steps[0] == service.system_line()
    assert steps[1].endswith("ao service install")


def test_cmd_migrate_prints_what_was_done_and_the_steps_and_exits_1_when_refused(monkeypatch, capsys):
    from shiftlead import cli

    monkeypatch.setattr(migrate, "run", lambda: ["moved /h/.agentorc to /h/.shiftlead"])
    monkeypatch.setattr(migrate, "next_steps", lambda: ["sudo root-line", "ao service install"])
    monkeypatch.setattr(
        migrate, "environment_warning", lambda: "this shell still carries AGENTORC_HOME: open a new one"
    )
    assert cli.main(["migrate"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "moved /h/.agentorc to /h/.shiftlead",
        "then:",
        "  sudo root-line",
        "  ao service install",
        "this shell still carries AGENTORC_HOME: open a new one",
    ]
    assert cli.main(["--json", "migrate"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "done": ["moved /h/.agentorc to /h/.shiftlead"],
        "next": ["sudo root-line", "ao service install"],
        "warning": "this shell still carries AGENTORC_HOME: open a new one",
    }

    def refused():
        raise RuntimeError("1 session(s) still run (ao-x): close them first, then migrate")

    monkeypatch.setattr(migrate, "run", refused)
    assert cli.main(["migrate"]) == 1
    assert "1 session(s) still run (ao-x)" in capsys.readouterr().err
