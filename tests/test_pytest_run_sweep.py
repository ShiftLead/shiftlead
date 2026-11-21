"""A test run that died leaves its `pytest-N` locked; the next run's start removes it, and keeps a live run's, a
starting run's and its own (TD-2028)."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from conftest import sweep_dead_pytest_runs


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def _run(parent, n, lock: str | None):
    d = parent / f"pytest-{n}"
    (d / "test_x0").mkdir(parents=True)
    (d / "test_x0" / "f").write_text("x")
    if lock is not None:
        (d / ".lock").write_text(lock)
    return d


@pytest.mark.unit
def test_only_a_dead_runs_locked_directory_is_removed(tmp_path):
    parent = tmp_path / "pytest-of-someone"
    dead = _run(parent, 1, str(_dead_pid()))
    live = _run(parent, 2, str(os.getppid()))  # pytest's parent: running, and not this process
    starting = _run(parent, 3, "")  # created, its pid not yet written
    finished = _run(parent, 4, None)  # ended cleanly: pytest's own retention decides
    huge = _run(parent, 6, "9" * 25)  # no pid could have written it: kept, and the sweep goes on
    mine = _run(parent, 7, str(os.getpid()))
    own = _run(parent, 5, str(_dead_pid()))  # this run's, whatever its lock says
    (parent / "pytest-current").symlink_to(own)

    sweep_dead_pytest_runs(own)

    assert not dead.exists()
    assert huge.exists() and mine.exists()
    assert live.exists() and starting.exists() and finished.exists() and own.exists()
    assert (parent / "pytest-current").is_symlink()


@pytest.mark.unit
def test_a_base_temp_of_the_callers_own_is_left_alone(tmp_path):
    other = _run(tmp_path, 1, str(_dead_pid()))
    sweep_dead_pytest_runs(tmp_path / "pytest-9")  # its parent is no pytest-of-<user>
    assert other.exists()


def _seat(root, token):
    return root / token / "pytest-of-someone"


@pytest.mark.unit
def test_a_run_in_a_seat_sweeps_every_seats_dead_runs(tmp_path):
    """TD-2032: an idle seat's dead run is removed by another seat's next suite."""
    root = tmp_path / f"shiftlead-{os.getuid()}"
    mine, other = _seat(root, "aaaa1111"), _seat(root, "bbbb2222")
    own = _run(mine, 3, str(os.getpid()))
    dead_here = _run(mine, 1, str(_dead_pid()))
    dead_there = _run(other, 51, str(_dead_pid()))
    live_there = _run(other, 52, str(os.getppid()))
    starting_there = _run(other, 53, "")
    (other / "pytest-current").symlink_to(live_there)
    other_user = _run(root / "cccc3333" / "pytest-of-another", 1, str(_dead_pid()))  # not this user's runs
    (root / "loose-file").write_text("x")
    elsewhere = tmp_path / "elsewhere"
    linked = _run(_seat(elsewhere, "x"), 1, str(_dead_pid()))
    (root / "dddd4444").symlink_to(elsewhere / "x")  # a seat directory that is a link: never followed

    sweep_dead_pytest_runs(own)

    assert not dead_here.exists() and not dead_there.exists()
    assert own.exists() and live_there.exists() and starting_there.exists()
    assert (other / "pytest-current").is_symlink()
    assert other_user.exists() and linked.exists()


@pytest.mark.unit
def test_a_run_outside_a_seat_sweeps_only_its_own_parent(tmp_path):
    root = tmp_path / "not-a-scratch-root"
    own = _run(_seat(root, "aaaa1111"), 3, str(os.getpid()))
    dead_elsewhere = _run(_seat(root, "bbbb2222"), 1, str(_dead_pid()))
    sweep_dead_pytest_runs(own)
    assert dead_elsewhere.exists()
