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
    (old / "launch" / "ao-x.json").write_text(json.dumps({"env": {"AGENTORC_SESSION": "ao-x"}}))
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
    assert json.loads((new / "launch" / "ao-x.json").read_text()) == {"env": {"SHIFTLEAD_SESSION": "ao-x"}}
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
