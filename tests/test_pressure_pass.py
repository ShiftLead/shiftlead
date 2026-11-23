"""TD-2081, design §4.6 *The pressure pass*: a low share free starts a reclaim without the hourly sweep. It takes test
runs, ended runs' directories and build leftovers, in that order, stops over `PRESSURE_CLEAR`, and backs off after a
pass that freed under a point. The free-space reading is stubbed: this machine allows no unprivileged mount."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sessionorc import diskbook, hosts, scratch
from sessionorc.agent import HostAgent
from shiftlead import cli

NOW = time.time()


@pytest.fixture
def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


@pytest.fixture
def pool(short, tmp_path):
    return short, tmp_path


def _seat(root: Path, home: Path, token: str = "aaaaaaaa", rid: str = "ao-x") -> Path:
    p = scratch.ensure_parent(root) / token
    p.mkdir(mode=0o700)
    scratch.write_owner(p, rid, home)
    return p


def _age(path: Path, seconds: float) -> None:
    at = NOW - seconds
    for d, subdirs, files in os.walk(path, topdown=False):
        for name in files + subdirs:
            os.utime(os.path.join(d, name), (at, at), follow_symlinks=False)
    os.utime(path, (at, at), follow_symlinks=False)


def _run(seat: Path, n: int, lock: str | None = None, age: float = 3600) -> Path:
    r = seat / "pytest-of-me" / f"pytest-{n}"
    r.mkdir(parents=True)
    (r / "data").write_text("x")
    if lock is not None:
        (r / ".lock").write_text(lock)
    _age(r, age)
    return r


def _reclaim(root, home, *, named=None, share=lambda: 0.1, troots=(), lock=None, live=lambda _p: False):
    return scratch.reclaim(root, home, named or {}, live, list(troots), share, time.time(), lock or threading.Lock())


@pytest.mark.unit
def test_rule_one_takes_finished_and_dead_runs_and_keeps_the_rest(pool, dead_pid):
    root, home = pool
    seat = _seat(root, home)
    finished, dead = _run(seat, 1), _run(seat, 2, str(dead_pid))
    recent = _run(seat, 3, age=60)
    empty = _run(seat, 4, "")
    live = _run(seat, 5, str(os.getpid()))
    current = _run(seat, 6)
    (seat / "pytest-of-me" / "pytest-current").symlink_to(current)
    marked = seat / "aoscr-dead"
    marked.mkdir()
    (marked / scratch.TEST_RUN_MARK).write_text(str(dead_pid))
    _age(marked, 3600)
    clone = seat / "clone" / "pytest-of-me" / "pytest-9"
    clone.mkdir(parents=True)
    _age(seat / "clone", 3600)
    _reclaim(root, home)
    assert not finished.exists() and not dead.exists() and not marked.exists()
    assert recent.exists() and empty.exists() and live.exists() and current.exists() and clone.exists()


@pytest.mark.unit
def test_rule_two_takes_an_ended_run_past_the_short_keep_unless_a_hold_keeps_it(pool):
    root, home = pool
    gone = _seat(root, home, "bbbbbbbb", "ao-a")
    fixture = gone / "pytest-of-me" / "pytest-1" / "repo"
    fixture.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(fixture)], check=True)
    (fixture / "untracked").write_text("x")
    young = _seat(root, home, "cccccccc", "ao-b")
    held = _seat(root, home, "dddddddd", "ao-c")
    subprocess.run(["git", "init", "-q", str(held / "work")], check=True)
    (held / "work" / "file").write_text("x")
    now = time.time()
    named = {str(gone): ("ao-a", now - 7200), str(young): ("ao-b", now - 60), str(held): ("ao-c", now - 7200)}
    _reclaim(root, home, named=named)
    assert not gone.exists() and young.exists() and held.exists()


@pytest.mark.unit
def test_rule_two_is_skipped_while_the_sweep_holds_its_lock(pool):
    root, home = pool
    seat = _seat(root, home, "bbbbbbbb", "ao-a")
    lock = threading.Lock()
    lock.acquire()
    got = _reclaim(root, home, named={str(seat): ("ao-a", time.time() - 7200)}, lock=lock)
    assert got["skipped"] and seat.exists()


@pytest.mark.unit
def test_rule_three_takes_a_build_leftover_unwritten_for_a_day(pool):
    root, home = pool
    seat = _seat(root, home)
    old, fresh = seat / "pdm-build-old", seat / "pdm-wheel-cache-new"
    old.mkdir()
    fresh.mkdir()
    (old / "f").write_text("x")
    _age(old, 90_000)
    deep = seat / "clone" / "pdm-build-deep"
    deep.mkdir(parents=True)
    _age(seat / "clone", 90_000)
    _reclaim(root, home)
    assert not old.exists() and fresh.exists() and deep.exists()


@pytest.mark.unit
def test_it_stops_once_over_clear(pool, dead_pid):
    root, home = pool
    seat = _seat(root, home)
    first, second = _run(seat, 1), _run(seat, 2)
    readings = iter([0.1, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4])
    _reclaim(root, home, share=lambda: next(readings))
    assert first.exists() != second.exists()


@pytest.mark.unit
def test_another_homes_directory_is_left_to_that_home(pool):
    root, home = pool
    other = home / "other"
    other.mkdir()
    seat = _seat(root, other)
    run = _run(seat, 1)
    _reclaim(root, home)
    assert run.exists()


@pytest.mark.unit
def test_backoff_after_a_weak_pass_and_a_fall_of_five_points_ends_it():
    b = scratch.Backoff()
    assert b.due(0.2, 100) and not b.due(0.3, 100) and not b.due(None, 100)
    assert b.after(0.2, 0.205, False, 100)
    assert (
        not b.due(0.2, 200) and b.due(0.15, 200) and not b.due(0.16, 200) and b.due(0.2, 100 + scratch.PRESSURE_BACKOFF)
    )
    assert not b.after(0.15, 0.3, False, 200)
    assert b.due(0.2, 201)


@pytest.mark.unit
def test_a_pass_that_skipped_rule_two_starts_no_backoff():
    b = scratch.Backoff()
    assert b.after(0.2, 0.2, True, 100)
    assert b.due(0.2, 101)


@pytest.mark.unit
def test_weak_passes_fold_into_one_line_and_count_under_scratch(tmp_path):
    at = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    diskbook.note_pressure(tmp_path, "h", 10, True, at)
    diskbook.note_pressure(tmp_path, "h", 5, True, at)
    diskbook.note_pressure(tmp_path, "h", 7, False, at)
    lines = json.loads((tmp_path / diskbook.FILE).read_text())["passes"]
    assert [ln["removed"]["scratch"] for ln in lines] == [15, 7]
    assert lines[0]["pressure"] == {"weak": True, "count": 2}
    got = diskbook.read(tmp_path, "h", "s", at, {"path": "/"})
    assert got["kinds"]["scratch"]["removed_30d"] == 22


@pytest.mark.unit
def test_share_free_by_file_system_type(tmp_path, monkeypatch):
    table = tmp_path / "mountinfo"
    table.write_text(f"1 0 8:1 / / rw - ext4 /dev/sda rw\n2 1 0:1 / {tmp_path} rw shared:1 - tmpfs tmpfs rw\n")
    read = {"path": "x", "bytes_free": 10, "bytes_total": 100, "inodes_free": 50, "inodes_total": 100}
    monkeypatch.setattr(diskbook, "free_space", lambda _p: dict(read))
    assert diskbook.fs_type(tmp_path, str(table)) == "tmpfs" and diskbook.fs_type("/usr", str(table)) == "ext4"
    assert diskbook.share_free(tmp_path, str(table)) == 0.1  # a tmpfs: the lower of the two
    assert diskbook.share_free("/usr", str(table)) == 0.5  # elsewhere: inodes alone
    read["inodes_total"] = 0
    assert diskbook.share_free("/usr", str(table)) is None  # btrfs's shape: no reading
    assert diskbook.share_free(tmp_path, str(table)) == 0.1


@pytest.mark.unit
def test_a_seat_root_with_no_reading_is_skipped_without_being_made(pool, monkeypatch):
    root, home = pool
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    seat = root / "u"
    (home / "hosts.yml").write_text(f"local:\n  scratch_root: {root}\n  seat_root: {seat}\n")
    assert hosts.local_host().seat_root == str(seat)
    assert HostAgent._pressure_read(HostAgent.__new__(HostAgent)) == (None, None)
    assert not seat.exists()


@pytest.mark.unit
@pytest.mark.parametrize("share, taken", [(0.1, True), (0.3, False)])
def test_the_tick_pass_reclaims_on_a_low_reading_alone(pool, monkeypatch, share, taken):
    root, home = pool
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    (home / "hosts.yml").write_text(f"local:\n  scratch_root: {root}\n")
    run = _run(_seat(root, home), 1)
    monkeypatch.setattr(diskbook, "share_free", lambda _p, *_a: share)
    a = HostAgent.__new__(HostAgent)
    a.sessions, a.host = {}, "h"
    a._pressure_lock, a._sweep_lock = threading.Lock(), threading.Lock()
    a._pressure_backoff = scratch.Backoff()
    asyncio.run(a._pressure_pass(datetime.now(UTC)))
    assert run.exists() is not taken
    assert (home / diskbook.FILE).exists() is taken


@pytest.mark.unit
def test_ao_disk_says_no_pressure_reading():
    lines = cli.disk_lines({"h": {"at": None, "kinds": {}, "free": {}, "no_pressure": "/data"}})
    assert "  /data: no pressure reading" in lines
