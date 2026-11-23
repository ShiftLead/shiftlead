"""TD-2082, design §4.6 *Temporary space is a pool of its own*: a host's `seat_root` holds unattended runs' scratch,
apart from `scratch_root`; a restart keeps the path it was given under either; the sweep walks each distinct root;
a missing mount stops no host agent and is never made; `ao disk` and the Settings page show it."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sessionorc import agent as agent_mod
from sessionorc import diskbook, hosts, scratch
from sessionorc.agent import HostAgent, RpcError
from sessionorc.models import Session
from shiftlead import cli
from shiftlead.ui import settings_page

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


@pytest.fixture
def short(_scratch_root):
    """A root of this test's own, short enough for the 48 bytes `tmp_path` is past."""
    with tempfile.TemporaryDirectory(dir=_scratch_root) as d:
        yield Path(d)


@pytest.fixture
def roots(short, tmp_path, monkeypatch):
    """A home whose `hosts.yml` sets both roots; `seat` is left unmade, as a fresh mount's content is."""
    root, seat = short / "r", short / "s"
    seat.mkdir()
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    (tmp_path / "hosts.yml").write_text(f"local:\n  scratch_root: {root}\n  seat_root: {seat}\n")
    return root, seat


def _holder(rid: str = "ao-x") -> Session:
    s = Session.__new__(Session)
    s.id = rid
    return s


def _run(given, unattended, rid="ao-x"):
    return HostAgent._run_scratch(HostAgent.__new__(HostAgent), given, _holder(rid), unattended)


@pytest.mark.unit
def test_seat_root_unset_reads_empty_and_every_run_stays_under_scratch_root(short, tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    (tmp_path / "hosts.yml").write_text(f"local:\n  scratch_root: {short / 'r'}\n  seat_root: '  '\n")
    assert hosts.local_host().seat_root == ""
    assert Path(_run(None, True)).parent == scratch.parent(short / "r")
    assert Path(_run(None, False)).parent == scratch.parent(short / "r")


@pytest.mark.unit
def test_an_unattended_run_goes_under_seat_root_and_an_interactive_one_does_not(roots):
    root, seat = roots
    assert Path(_run(None, True)).parent == scratch.parent(seat)
    assert Path(_run(None, False)).parent == scratch.parent(root)


@pytest.mark.unit
def test_a_restart_keeps_its_path_under_either_root_whatever_the_mode_is_now(roots):
    root, seat = roots
    in_seat, in_root = _run(None, True), _run(None, False)
    assert _run(in_seat, False) == in_seat  # a seat a person took over stays in the pool
    assert _run(in_root, True) == in_root  # a session turned unattended stays out of it
    other = scratch.make(seat, "ao-other", hosts.paths.home())
    assert _run(other, True) != other  # another record's directory is never taken


@pytest.mark.unit
def test_a_missing_mount_fails_only_a_run_that_belongs_in_it(roots):
    root, seat = roots
    carried = _run(None, True)
    scratch._remove(scratch.parent(seat))
    seat.chmod(0o500)  # as `/aot` is with its mount gone: root's, and nothing can be made in it
    try:
        with pytest.raises(RpcError, match="no scratch directory"):
            _run(None, True)
        with pytest.raises(RpcError, match="no scratch directory"):
            _run(carried, True)
        assert Path(_run(carried, False)).parent == scratch.parent(root)  # a person's Resume still starts
        assert Path(_run(None, False)).parent == scratch.parent(root)
    finally:
        seat.chmod(0o700)


@pytest.mark.unit
def test_the_start_check_refuses_a_bad_seat_root_and_never_makes_it(short):
    root = short / "r"
    transcripts = short / "t"
    with pytest.raises(scratch.ScratchError, match="seat_root .* longer"):
        scratch.check_seat_root("/tmp/" + "x" * 44, root, [])
    for bad in (root / "in", short):
        with pytest.raises(scratch.ScratchError, match="overlaps scratch_root"):
            scratch.check_seat_root(bad, root, [])
    with pytest.raises(scratch.ScratchError, match="seat_root .* transcripts"):
        scratch.check_seat_root(transcripts / "s", root, [transcripts])
    scratch.check_seat_root(root, root, [])  # equal is allowed
    missing = short / "nowhere"
    agent_mod._check_scratch_root(str(root), str(missing))  # a missing mount stops no start
    assert not missing.exists() and scratch.parent(root).is_dir()


@pytest.mark.unit
def test_the_sweep_walks_each_distinct_root_once_and_skips_one_not_mounted(roots, tmp_path):
    root, seat = roots
    agent = HostAgent.__new__(HostAgent)
    assert agent._scratch_pools() == [str(root)]  # `seat` holds no parent and is no mount: never made
    assert not scratch.parent(seat).exists()
    scratch.ensure_parent(seat)
    assert agent._scratch_pools() == [str(root), str(seat)]
    (tmp_path / "hosts.yml").write_text(f"local:\n  scratch_root: {root}\n  seat_root: {root}\n")
    assert agent._scratch_pools() == [str(root)]
    assert agent._seat_free() is None  # the same disk: `ao disk` draws it once


@pytest.mark.unit
def test_keep_alive_and_the_removal_reach_a_directory_under_seat_root(roots):
    _root, seat = roots
    home = hosts.paths.home()
    live = scratch.make(seat, "ao-live", home)
    (Path(live) / "owner.json").unlink()
    assert scratch.keep_alive(seat, {"ao-live": live}, home, 0) == []
    assert scratch.owner(live)["id"] == "ao-live"
    gone = scratch.make(seat, "ao-gone", home)
    old = 1_000_000.0
    os.utime(Path(gone) / "owner.json", (old, old))
    os.utime(gone, (old, old))
    scratch.sweep(seat, home, {live: ("ao-live", None)}, 24, old + 7200, lambda _p: False, [])
    assert not Path(gone).exists() and Path(live).exists()


@pytest.mark.unit
def test_ao_disk_prints_the_seat_pool_its_warning_and_not_mounted(tmp_path):
    free = {"path": "/tmp", "bytes_free": 50, "bytes_total": 100, "inodes_free": 50, "inodes_total": 100}
    low = {"path": "/aot", "bytes_free": 5, "bytes_total": 100, "inodes_free": 50, "inodes_total": 100}
    diskbook.write(tmp_path, "h", {}, free, "s", NOW, seat_free=low)
    got = diskbook.read(tmp_path, "h", "s", NOW, free, seat_free=low)
    assert got["seat_warnings"] == ["under a tenth of its bytes free"]
    text = "\n".join(cli.disk_lines({"h": got}))
    assert "free under /aot (seats): 5 B of 100 B, 50 of 100 inodes" in text
    assert "⚠ /aot: under a tenth of its bytes free" in text
    gone = diskbook.read(tmp_path, "h", "s", NOW, free, seat_free={"path": "/aot", "not_mounted": True})
    assert gone["seat_warnings"] == []
    assert "free under /aot (seats): not mounted" in "\n".join(cli.disk_lines({"h": gone}))
    assert "seat_free" not in diskbook.read(tmp_path, "h", "s", NOW, free)  # unset: nothing is drawn


@pytest.mark.unit
def test_the_hosts_card_shows_seat_root(roots):
    _root, seat = roots
    local = hosts.local_host()
    rows = {r["key"]: r for r in settings_page.host_card({"seat_root": str(seat)}, local, local.name, {})["rows"]}
    assert rows["seat_root"]["value"] == str(seat) and not rows["seat_root"]["default"]
    local.seat_root = ""
    rows = {r["key"]: r for r in settings_page.host_card({}, local, local.name, {})["rows"]}
    assert rows["seat_root"]["value"] == "unset" and rows["seat_root"]["default"]
