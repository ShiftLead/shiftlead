"""The test run's own `aoscr-*` scratch roots: a run that has ended has its root swept by the next, a live run's is
kept (TD-2015)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from conftest import OWNERS, TEST_RUN_MARK, _scratch_parent, sweep_stale_scratch_roots


def _root(base, owner_pid=None, age=0.0):
    root = base / f"aoscr-{uuid.uuid4().hex[:8]}"
    (root / "shiftlead-1000" / "ro").mkdir(parents=True)
    (root / "shiftlead-1000" / "ro" / "f").write_text("x")
    os.chmod(root / "shiftlead-1000" / "ro", 0o000)  # a directory a test left unreadable and unwritable
    if owner_pid is not None:
        OWNERS.mkdir(exist_ok=True)
        (OWNERS / root.name).write_text(str(owner_pid))
    if age:
        when = time.time() - age
        os.utime(root, (when, when))
    return root


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


@pytest.mark.unit
def test_a_dead_runs_root_is_swept_and_a_live_runs_is_kept(tmp_path):
    dead = _root(tmp_path, owner_pid=_dead_pid())
    live = _root(tmp_path, owner_pid=os.getppid())  # pytest's parent: running, and not this process
    try:
        sweep_stale_scratch_roots(str(tmp_path))
        assert not dead.exists() and not (OWNERS / dead.name).exists()
        assert live.exists() and (OWNERS / live.name).exists()
    finally:
        (OWNERS / live.name).unlink(missing_ok=True)
        os.chmod(live / "shiftlead-1000" / "ro", 0o755)


@pytest.mark.unit
def test_a_root_no_owner_file_names_is_never_swept(tmp_path):
    unowned = _root(tmp_path, age=30 * 86400)  # made before TD-2015: whose it is cannot be read
    sweep_stale_scratch_roots(str(tmp_path))
    assert unowned.exists()
    os.chmod(unowned / "shiftlead-1000" / "ro", 0o755)


def _seat_root(holder, seat, mark):
    root = holder / f"shiftlead-{os.getuid()}" / seat / f"aoscr-{uuid.uuid4().hex[:8]}"
    (root / "shiftlead-1000").mkdir(parents=True)
    if mark is not None:
        (root / TEST_RUN_MARK).write_text(mark)
    return root


@pytest.mark.unit
def test_a_killed_runs_root_in_another_seats_directory_is_swept(tmp_path):
    dead = _seat_root(tmp_path, "seat-a", str(_dead_pid()))
    live = _seat_root(tmp_path, "seat-b", str(os.getppid()))
    starting = _seat_root(tmp_path, "seat-b", "")  # the mark's file made, its pid not yet written
    unmarked = _seat_root(tmp_path, "seat-c", None)
    sweep_stale_scratch_roots(str(tmp_path))
    assert not dead.exists()
    assert live.exists() and starting.exists() and unmarked.exists()


@pytest.mark.unit
def test_a_seats_tmpdir_in_another_pool_has_that_pools_seats_swept(tmp_path):
    pool = tmp_path / "pool"
    dead = _seat_root(pool, "seat-a", str(_dead_pid()))
    own = pool / f"shiftlead-{os.getuid()}" / "seat-b"
    own.mkdir()
    sweep_stale_scratch_roots(str(tmp_path / "top"), tmpdir=str(own))
    assert not dead.exists()


@pytest.mark.unit
def test_the_root_goes_under_tmpdir_only_where_it_fits(tmp_path, monkeypatch):
    short = tmp_path / "s"
    short.mkdir()
    monkeypatch.setattr("sessionorc.scratch.MAX_ROOT", len(str(short)) + len("/aoscr-12345678/s/r"))
    assert _scratch_parent(str(short)) == str(short)
    monkeypatch.setattr("sessionorc.scratch.MAX_ROOT", len(str(short)) + len("/aoscr-12345678/s/r") - 1)
    assert _scratch_parent(str(short)) == "/tmp"
    monkeypatch.setattr("sessionorc.scratch.MAX_ROOT", 4096)
    assert _scratch_parent(str(tmp_path / "missing")) == "/tmp"
    assert _scratch_parent("relative") == "/tmp"
    assert _scratch_parent(None) == "/tmp"


@pytest.mark.unit
def test_this_runs_root_carries_its_pid(_scratch_root):
    assert (Path(_scratch_root) / TEST_RUN_MARK).read_text() == str(os.getpid())
