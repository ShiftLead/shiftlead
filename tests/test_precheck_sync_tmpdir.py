"""The precheck's `pdm sync` runs with `TMPDIR` set to the run's own directory (design §4.6, TD-2122).

A sync killed partway leaves its build directories in `TMPDIR`, so a sync outside the run's directory leaves them in
the shared `/tmp`, where nothing ages them.
"""

import os
import re
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest

CADENCE_TOML = Path(__file__).resolve().parent.parent / "docs" / "cadence.toml"
RUN_DIR = re.compile(r"/var/tmp/pc\.[^/\s]+")


def _commands() -> dict[str, str]:
    """Each precheck command by a short name: the full one, and each entry of `[precheck-paths]`."""
    config = tomllib.loads(CADENCE_TOML.read_text())
    return {
        "precheck": config["precheck"],
        **{f"paths[{i}]": c for i, c in enumerate(config["precheck-paths"].values())},
    }


@pytest.mark.parametrize("name", sorted(_commands()))
def test_sync_runs_in_the_runs_own_directory(name: str, tmp_path: Path) -> None:
    command = _commands()[name]
    # From `T=$(mktemp` onward, so the leading `find` over the real /var/tmp never runs.
    tail = command[command.index("T=$(mktemp") :]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "pdm.log"
    stub = bin_dir / "pdm"
    stub.write_text('#!/bin/sh\nprintf \'%s %s\\n\' "$1" "$TMPDIR" >> "$PDM_LOG"\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "PDM_LOG": str(log), "TMPDIR": str(tmp_path)}

    subprocess.run(["/bin/sh", "-c", tail], cwd=tmp_path, env=env, check=True, timeout=30)

    calls = [line.split(" ", 1) for line in log.read_text().splitlines()]
    synced = [seen for sub, seen in calls if sub == "sync"]
    assert len(synced) == 1, calls
    assert RUN_DIR.fullmatch(synced[0]), calls
