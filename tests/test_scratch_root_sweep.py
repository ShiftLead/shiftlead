"""The test run's own `aoscr-*` scratch roots: a run that has ended has its root swept by the next, a live run's is
kept (TD-2015)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid

import pytest
from conftest import OWNERS, sweep_stale_scratch_roots


def _root(base, owner_pid=None, age=0.0):
    root = base / f"aoscr-{uuid.uuid4().hex[:8]}"
    (root / "shiftlead-1000" / "ro").mkdir(parents=True)
    (root / "shiftlead-1000" / "ro" / "f").write_text("x")
    os.chmod(root / "shiftlead-1000" / "ro", 0o555)  # a read-only directory a test left behind
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
