"""TD-2100, design §4.6: a precheck removes its user's `pc.*` directories over a day old before it makes its own.

The commands are read from `docs/cadence.toml` and run with `/var/tmp` pointed at a temp directory.
"""

import os
import subprocess
import time
import tomllib
from pathlib import Path

import pytest

TOML = Path(__file__).resolve().parents[1] / "docs" / "cadence.toml"
DAY_AND_A_BIT = 25 * 3600


def _commands() -> list[str]:
    conf = tomllib.loads(TOML.read_text())
    return [conf["precheck"], *conf["precheck-paths"].values()]


def _removal(command: str, root: Path) -> str:
    """The part of `command` before it makes its own directory, aimed at `root`, then a marker."""
    head, sep, _ = command.partition("T=$(mktemp")
    assert sep and head.strip()
    return head.replace("/var/tmp", str(root)) + "echo ran"


def _aged(path: Path, seconds: int) -> Path:
    then = time.time() - seconds
    os.utime(path, (then, then), follow_symlinks=False)
    return path


@pytest.mark.parametrize("index", range(len(_commands())))
def test_removes_only_a_directory_over_a_day_old(tmp_path, index):
    root = tmp_path / "vartmp"
    root.mkdir()
    old = root / "pc.old"
    (old / "p" / "deep").mkdir(parents=True)
    _aged(old, DAY_AND_A_BIT)
    recent = root / "pc.recent"
    recent.mkdir()
    _aged(recent, 3600)
    concurrent = root / "pc.running"
    concurrent.mkdir()
    other = root / "other"
    other.mkdir()
    _aged(other, DAY_AND_A_BIT)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "kept").write_text("x")
    link = root / "pc.link"
    link.symlink_to(outside)
    _aged(link, DAY_AND_A_BIT)

    out = subprocess.run(["bash", "-c", _removal(_commands()[index], root)], capture_output=True, text=True)

    assert out.returncode == 0 and out.stdout.strip() == "ran"
    assert not old.exists()
    assert recent.is_dir() and concurrent.is_dir() and other.is_dir()
    assert link.is_symlink() and (outside / "kept").read_text() == "x"


@pytest.mark.parametrize("index", range(len(_commands())))
def test_removes_a_directory_holding_a_read_only_tree(tmp_path, index):
    root = tmp_path / "vartmp"
    root.mkdir()
    old = root / "pc.readonly"
    tree = old / "p" / "cache" / "files"
    tree.mkdir(parents=True)
    (tree / "f").write_text("x")
    tree.chmod(0o555)
    tree.parent.chmod(0o555)
    _aged(old, DAY_AND_A_BIT)

    out = subprocess.run(["bash", "-c", _removal(_commands()[index], root)], capture_output=True, text=True)

    assert out.returncode == 0 and out.stdout.strip() == "ran"
    assert not old.exists()


@pytest.mark.parametrize("index", range(len(_commands())))
def test_a_failed_removal_does_not_stop_the_precheck(tmp_path, index):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "find"
    fake.write_text("#!/bin/sh\necho broken >&2\nexit 1\n")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    out = subprocess.run(
        ["bash", "-c", _removal(_commands()[index], tmp_path)], capture_output=True, text=True, env=env
    )

    assert out.returncode == 0 and out.stdout.strip() == "ran" and out.stderr == ""
