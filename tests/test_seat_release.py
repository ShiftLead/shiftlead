"""TD-2131, design §4.6 *A live seat's rebuildable copies*, parts 2 and 3: a hand-run suite is marked and listed, and
an ended one is released from a live seat, by the hourly pass after two quiet hours and under pressure after ten
minutes."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import conftest
import pytest

from sessionorc import diskbook, scratch

HERE = Path(__file__).parent


@pytest.fixture
def dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


@pytest.fixture
def seat(short, tmp_path) -> tuple[Path, Path, Path]:
    p = scratch.ensure_parent(short) / "aaaaaaaa"
    p.mkdir(mode=0o700)
    scratch.write_owner(p, "ao-x", tmp_path)
    return short, tmp_path, p


def _age(path: Path, seconds: float) -> None:
    at = time.time() - seconds
    for d, subdirs, files in os.walk(path, topdown=False):
        for name in files + subdirs:
            os.utime(os.path.join(d, name), (at, at), follow_symlinks=False)
    os.utime(path, (at, at), follow_symlinks=False)


def _listed(s: Path, base: Path, pid: int, mark: int | None = None, age: float = 3 * 3600) -> Path:
    """A base temp at `base` marked with `mark` (default `pid`), and its list file naming `pid`."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "data").write_text("x")
    (base / scratch.TEST_RUN_MARK).write_text(str(pid if mark is None else mark))
    _age(base, age)
    d = s / scratch.TEST_RUNS_DIR
    d.mkdir(mode=0o700, exist_ok=True)
    f = d / f"{pid}-{time.time_ns()}"
    f.write_text(str(base))
    return f


def _release(root, home, **kw) -> list[tuple[str, str]]:
    return scratch.release(root, home, kw.pop("troots", []), time.time(), kw.pop("tally", None), **kw)


def _reclaim(root, home):
    return scratch.reclaim(root, home, {}, lambda _p: False, [], lambda: 0.1, time.time(), threading.Lock())


@pytest.mark.unit
def test_a_dead_listed_run_at_any_depth_goes_after_two_quiet_hours(seat, dead_pid):
    root, home, s = seat
    old, young = s / "work" / "deep" / "run", s / "work" / "young"
    _listed(s, old, dead_pid)
    _listed(s, young, dead_pid, age=3600)
    _release(root, home)
    assert not old.exists() and young.exists()


@pytest.mark.unit
def test_under_pressure_a_dead_listed_run_goes_after_ten_minutes(seat, dead_pid):
    root, home, s = seat
    run, recent = s / "a" / "run", s / "a" / "recent"
    _listed(s, run, dead_pid, age=700)
    _listed(s, recent, dead_pid, age=60)
    _reclaim(root, home)
    assert not run.exists() and recent.exists()


@pytest.mark.unit
def test_a_live_run_is_not_touched(seat):
    root, home, s = seat
    run = s / "a" / "live"
    f = _listed(s, run, os.getpid())
    _release(root, home)
    _reclaim(root, home)
    assert run.exists() and f.exists()


@pytest.mark.unit
def test_a_path_through_a_symlink_or_outside_the_seat_is_not_touched(seat, dead_pid, tmp_path):
    root, home, s = seat
    outside = tmp_path / "outside"
    f_out = _listed(s, outside, dead_pid)
    real = s / "real"
    real.mkdir()
    (s / "link").symlink_to(real)
    inner = real / "run"
    f_link = _listed(s, inner, dead_pid)
    f_link.write_text(str(s.resolve() / "link" / "run"))
    _release(root, home)
    _reclaim(root, home)
    assert outside.exists() and inner.exists() and f_out.exists() and f_link.exists()


@pytest.mark.unit
def test_a_list_directory_that_is_a_symlink_is_not_read(seat, dead_pid, tmp_path):
    root, home, s = seat
    run = s / "a" / "run"
    run.mkdir(parents=True)
    (run / scratch.TEST_RUN_MARK).write_text(str(dead_pid))
    _age(run, 3 * 3600)
    elsewhere = tmp_path / "lists"
    elsewhere.mkdir()
    (elsewhere / f"{dead_pid}-1").write_text(str(run))
    (s / scratch.TEST_RUNS_DIR).symlink_to(elsewhere)
    _release(root, home)
    assert run.exists()


@pytest.mark.unit
def test_an_oversized_list_file_is_not_touched(seat, dead_pid):
    root, home, s = seat
    run = s / "a" / "run"
    f = _listed(s, run, dead_pid)
    f.write_text(str(run) + "\n" * scratch.RUN_LIST_MAX)
    _release(root, home)
    assert run.exists() and f.exists()


@pytest.mark.unit
def test_a_file_whose_path_is_gone_or_reused_by_another_pid_is_removed(seat, dead_pid):
    root, home, s = seat
    gone = _listed(s, s / "a" / "gone", dead_pid)
    (s / "a" / "gone" / "data").unlink()
    (s / "a" / "gone" / scratch.TEST_RUN_MARK).unlink()
    (s / "a" / "gone").rmdir()
    reused = s / "a" / "reused"
    stale = _listed(s, reused, dead_pid, mark=os.getpid())
    assert scratch._listed_runs(s, dry=True) == [] and gone.exists() and stale.exists()
    _release(root, home)
    assert not gone.exists() and not stale.exists() and reused.exists()


@pytest.mark.unit
def test_the_hourly_pass_takes_pytest_current_target_and_its_link(seat):
    root, home, s = seat
    parent = s / "pytest-of-me"
    run = parent / "pytest-1"
    run.mkdir(parents=True)
    (run / "data").write_text("x")
    _age(run, 3 * 3600)
    link = parent / "pytest-current"
    link.symlink_to(run)
    _reclaim(root, home)
    assert run.exists()  # the pressure pass leaves the target
    _release(root, home)
    assert not run.exists() and not link.is_symlink()


@pytest.mark.unit
def test_a_link_naming_a_newer_run_stays(seat):
    root, home, s = seat
    parent = s / "pytest-of-me"
    old, new = parent / "pytest-1", parent / "pytest-2"
    for r in (old, new):
        r.mkdir(parents=True)
    (new / ".lock").write_text(str(os.getpid()))
    _age(old, 3 * 3600)
    link = parent / "pytest-current"
    link.symlink_to(new)
    _release(root, home)
    assert not old.exists() and new.exists() and link.is_symlink()


@pytest.mark.unit
def test_a_dry_run_counts_and_removes_nothing(seat, dead_pid):
    root, home, s = seat
    run = s / "a" / "run"
    f = _listed(s, run, dead_pid)
    tally = diskbook.Tally()
    _release(root, home, tally=tally, dry=True)
    assert run.exists() and f.exists() and str(run.resolve()) in tally.gone_paths


@pytest.mark.unit
def test_a_transcript_store_is_skipped(seat, dead_pid):
    root, home, s = seat
    run = s / "a" / "run"
    _listed(s, run, dead_pid)
    _release(root, home, troots=[run / "store"])
    assert run.exists()


@pytest.mark.unit
def test_a_walk_cut_short_keeps_the_run_with_why(seat, dead_pid, monkeypatch):
    root, home, s = seat
    run = s / "a" / "run"
    _listed(s, run, dead_pid)
    monkeypatch.setattr(scratch, "RELEASE_WALK_S", -1.0)
    tally = diskbook.Tally()
    kept = _release(root, home, tally=tally)
    assert run.exists() and kept == [(str(run.resolve()), scratch.WALK_CUT)] and tally.kept == kept


@pytest.mark.unit
def test_past_the_deadline_the_pass_stops_partial(seat, dead_pid):
    root, home, s = seat
    run = s / "a" / "run"
    _listed(s, run, dead_pid)
    tally = diskbook.Tally()
    _release(root, home, tally=tally, deadline=time.monotonic() - 1)
    assert run.exists() and tally.unlisted


def _config(basetemp) -> SimpleNamespace:
    return SimpleNamespace(option=SimpleNamespace(basetemp=basetemp))


@pytest.mark.unit
def test_the_mark_and_list_are_written_only_for_a_given_basetemp_under_the_seat(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    s = (tmp_path / "seat").resolve()
    base = s / "x" / "run"
    base.mkdir(parents=True)
    monkeypatch.setenv("SHIFTLEAD_SCRATCH", str(s))
    config = _config(str(base))
    conftest._mark_run(config, base)
    assert (base / conftest.TEST_RUN_MARK).read_text() == str(os.getpid())
    assert config._run_list_file.read_text() == str(base)
    for given, where in ((None, s / "y"), ("o", tmp_path / "outside")):
        where.mkdir()
        other = _config(given)
        conftest._mark_run(other, where)
        assert (where / conftest.TEST_RUN_MARK).exists() and not hasattr(other, "_run_list_file")


@pytest.mark.unit
def test_a_suite_run_inside_a_test_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "x")
    monkeypatch.setenv("SHIFTLEAD_SCRATCH", str(tmp_path))
    base = tmp_path / "run"
    base.mkdir()
    conftest._mark_run(_config(str(base)), base)
    assert list(base.iterdir()) == [] and not (tmp_path / conftest.RUN_LIST).exists()


@pytest.mark.unit
def test_a_failed_write_never_fails_the_run(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    s = tmp_path.resolve()
    monkeypatch.setenv("SHIFTLEAD_SCRATCH", str(s))
    base = s / "run"
    base.mkdir()
    (s / conftest.RUN_LIST).write_text("a file where the directory goes")
    config = _config(str(base))
    conftest._mark_run(config, base)  # the list cannot be written
    assert not hasattr(config, "_run_list_file")
    conftest._mark_run(_config(str(base)), s / "no-such-directory")  # nor the mark


def test_a_list_file_whose_write_fails_is_not_left_behind(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    s = tmp_path.resolve()
    monkeypatch.setenv("SHIFTLEAD_SCRATCH", str(s))
    base = s / "run"
    base.mkdir()

    def no_space(fd, *_args):
        os.close(fd)
        raise OSError("no space left on device")

    monkeypatch.setattr(conftest.os, "fdopen", no_space)
    config = _config(str(base))
    conftest._mark_run(config, base)
    assert not hasattr(config, "_run_list_file") and not list((s / conftest.RUN_LIST).iterdir())


def test_a_scratch_path_that_cannot_be_resolved_never_fails_the_run(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("SHIFTLEAD_SCRATCH", str(tmp_path))
    base = tmp_path / "run"
    base.mkdir()

    def loop(_self, *_args, **_kwargs):
        raise RuntimeError("symlink loop")

    monkeypatch.setattr(conftest.Path, "resolve", loop)
    config = _config(str(base))
    conftest._mark_run(config, base)
    assert not hasattr(config, "_run_list_file")


@pytest.mark.parametrize("body, stays", [("pass", False), ("assert False", True)])
def test_a_real_suite_leaves_a_list_file_only_when_it_fails(tmp_path, body: str, stays: bool):
    s = tmp_path.resolve() / "seat"
    base = s / "deep" / "run"
    base.parent.mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    (work / "test_one.py").write_text(f"def test_one():\n    {body}\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "PYTHONPATH"))}
    env.update(SHIFTLEAD_SCRATCH=str(s), PYTHONPATH=f"{HERE}{os.pathsep}{HERE.parent / 'src'}")
    got = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider", "-q", f"--basetemp={base}", "."],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert got.returncode == (1 if stays else 0), got.stdout + got.stderr
    assert base.exists() is stays
    assert len(list((s / conftest.RUN_LIST).iterdir())) == (1 if stays else 0)
