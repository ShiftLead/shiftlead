"""TD-2132, design §4.6 *A live seat's rebuildable copies*, part 4: a seat's `copies/` is released by the hourly pass
after a quiet day and under pressure after two quiet hours, kept while a process, git work or an unreadable `/proc`
holds it."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from sessionorc import diskbook, scratch

DAY = 86_400


@pytest.fixture
def seat(short, tmp_path) -> tuple[Path, Path, Path]:
    p = scratch.ensure_parent(short) / "aaaaaaaa"
    p.mkdir(mode=0o700)
    scratch.write_owner(p, "ao-x", tmp_path)
    (p / scratch.COPIES_DIR).mkdir(mode=0o700)
    return short, tmp_path, p


@pytest.fixture
def no_holds(monkeypatch):
    monkeypatch.setattr(scratch, "held_paths", lambda proc="/proc": set())


def _copy(s: Path, name: str, at: float | None = None) -> Path:
    """A copy made as `cp -a` makes one: old modification times, while its directories' change times are now."""
    src = s.parent / f"src-{name}"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "a.py").write_text("x")
    old = time.time() - 3 * DAY
    for p in (src / "pkg" / "a.py", src / "pkg", src):
        os.utime(p, (old, old))
    dest = s / scratch.COPIES_DIR / name
    subprocess.run(["cp", "-a", str(src), str(dest)], check=True)
    shutil.rmtree(src)
    return dest


def _release(root, home, now: float, **kw) -> list[tuple[str, str]]:
    return scratch.release_copies(root, home, kw.pop("troots", []), now, kw.pop("tally", None), **kw)


def _reclaim(root, home, now: float):
    """A reclaim at `now`, the seat named by a live record, so rule 2 leaves the seat itself alone."""
    named = {str(p): ("ao-x", None) for p in scratch._seats(root, home)}
    return scratch.reclaim(root, home, named, lambda _p: True, [], lambda: 0.1, now, threading.Lock())


@pytest.mark.unit
def test_a_cp_a_copy_reads_as_written_by_its_change_time_and_goes_after_a_day(seat, no_holds):
    root, home, s = seat
    c = _copy(s, "review")
    _release(root, home, time.time())
    assert c.exists(), "cp -a set old modification times, but its directories' change times are now"
    _release(root, home, time.time() + DAY + 60)
    assert not c.exists()
    assert not list((s / scratch.COPIES_DIR).iterdir()), "no .gone-* is left behind"


@pytest.mark.unit
def test_under_pressure_a_copy_goes_after_two_quiet_hours(seat, no_holds):
    root, home, s = seat
    c = _copy(s, "review")
    _reclaim(root, home, time.time() + 3600)
    assert c.exists()
    _reclaim(root, home, time.time() + 2 * 3600 + 60)
    assert not c.exists()


@pytest.mark.unit
def test_a_process_in_a_copy_keeps_it(seat):
    root, home, s = seat
    c = _copy(s, "review")
    p = subprocess.Popen(["sleep", "30"], cwd=c)
    try:
        kept = _release(root, home, time.time() + DAY + 60)
        assert c.exists() and (str(c), scratch.IN_USE) in kept
        _reclaim(root, home, time.time() + DAY + 60)
        assert c.exists()
    finally:
        p.kill()
        p.wait()


@pytest.mark.unit
def test_an_open_file_in_a_copy_keeps_it(seat):
    root, home, s = seat
    c = _copy(s, "review")
    with open(c / "pkg" / "a.py"):
        kept = _release(root, home, time.time() + DAY + 60)
    assert c.exists() and (str(c), scratch.IN_USE) in kept


@pytest.mark.unit
def test_an_unreadable_proc_keeps_every_copy(seat, monkeypatch):
    root, home, s = seat
    monkeypatch.setattr(scratch, "held_paths", lambda proc="/proc": None)
    c = _copy(s, "review")
    kept = _release(root, home, time.time() + DAY + 60)
    assert c.exists() and (str(c), scratch.PROC_UNREAD) in kept
    _reclaim(root, home, time.time() + DAY + 60)
    assert c.exists()


@pytest.mark.unit
def test_held_paths_reads_this_process_and_refuses_an_unlistable_proc(tmp_path):
    got = scratch.held_paths()
    assert got is not None and os.getcwd() in got
    assert scratch.held_paths(str(tmp_path / "none")) is None


@pytest.mark.unit
def test_git_work_keeps_a_copy(seat, no_holds):
    root, home, s = seat
    c = _copy(s, "review")
    subprocess.run(["git", "init", "-q", str(c)], check=True)
    (c / "new.txt").write_text("unsaved")
    kept = _release(root, home, time.time() + DAY + 60)
    assert c.exists() and (str(c), scratch.GIT_WORK) in kept


@pytest.mark.unit
def test_a_walk_cut_short_keeps_the_copy_with_why(seat, no_holds, monkeypatch):
    root, home, s = seat
    c = _copy(s, "review")
    monkeypatch.setattr(scratch, "RELEASE_WALK_S", -1.0)
    kept = _release(root, home, time.time() + DAY + 60)
    assert c.exists() and (str(c), scratch.WALK_CUT) in kept


@pytest.mark.unit
def test_a_leftover_gone_is_finished_and_never_blocks_a_later_copy(seat, no_holds):
    root, home, s = seat
    copies = s / scratch.COPIES_DIR
    left = copies / f"{scratch.GONE}review"
    (left / "x").mkdir(parents=True)
    _release(root, home, time.time())
    assert not left.exists(), "a .gone-* is finished with no age test"
    (left / "x").mkdir(parents=True)
    c = _copy(s, "review")
    assert scratch._gone_to(copies, "review") == copies / f"{scratch.GONE}review-1"
    _reclaim(root, home, time.time() + DAY)
    assert not c.exists() and not left.exists()


@pytest.mark.unit
def test_symlinks_plain_files_and_a_dry_run_remove_nothing(seat, no_holds, tmp_path):
    root, home, s = seat
    outside = tmp_path / "outside"
    (outside / "d").mkdir(parents=True)
    old = time.time() - 3 * DAY
    for p in (outside / "d", outside):
        os.utime(p, (old, old))
    copies = s / scratch.COPIES_DIR
    (copies / "link").symlink_to(outside)
    (copies / "file").write_text("x")
    c = _copy(s, "review")
    tally = diskbook.Tally()
    _release(root, home, time.time() + DAY + 60, tally=tally, dry=True)
    assert c.exists() and outside.exists() and (copies / "file").exists()
    assert str(c) in tally.gone_paths
    _release(root, home, time.time() + DAY + 60)
    assert not c.exists() and outside.exists() and (copies / "link").is_symlink() and (copies / "file").exists()


@pytest.mark.unit
def test_a_symlinked_copies_is_not_read(seat, no_holds, tmp_path):
    root, home, s = seat
    (s / scratch.COPIES_DIR).rmdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (s / scratch.COPIES_DIR).symlink_to(elsewhere)
    (elsewhere / "review").mkdir()
    old = time.time() - 3 * DAY
    os.utime(elsewhere / "review", (old, old))
    _release(root, home, time.time() + 3 * DAY)
    _reclaim(root, home, time.time() + 3 * DAY)
    assert (elsewhere / "review").exists()


@pytest.mark.unit
def test_nothing_outside_copies_is_taken_by_the_rule(seat, no_holds):
    root, home, s = seat
    other = s / "clone"
    other.mkdir()
    old = time.time() - 3 * DAY
    os.utime(other, (old, old))
    _release(root, home, time.time() + 3 * DAY)
    assert other.exists()


@pytest.mark.unit
def test_a_transcript_store_is_skipped(seat, no_holds):
    root, home, s = seat
    c = _copy(s, "review")
    _release(root, home, time.time() + DAY + 60, troots=[c / "pkg"])
    assert c.exists()


@pytest.mark.unit
def test_a_process_the_kernel_refuses_to_show_is_not_seen_and_any_other_failure_keeps_every_copy(tmp_path):
    proc = tmp_path / "proc"
    refused, broken, gone = proc / "101", proc / "102", proc / "103"
    for d in (refused, broken, gone):
        d.mkdir(parents=True)
    (refused / "maps").write_text("")
    (refused / "maps").chmod(0)
    (broken / "maps").mkdir()  # reading it fails, and not as a refusal
    (broken / "fd").mkdir()
    try:
        assert scratch.held_paths(str(proc)) is None
        shutil.rmtree(broken)
        assert scratch.held_paths(str(proc)) == set()
    finally:
        (refused / "maps").chmod(0o600)
