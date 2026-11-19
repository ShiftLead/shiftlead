"""The disk sweep (design §4.6 *The disk sweep*, §5, TD-1921, TD-1945): the host keys that bound it, shown on the
Settings page's Hosts card; run logs and attachment folders of ended runs past `runs_keep_mb`, oldest first, a live
run's never; and the hourly pass as a detached task the tick never waits on, one at a time under its lock."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import hosts, paths
from shiftlead.ui import settings_page

MB = 1024 * 1024


@pytest.mark.unit
def test_the_sweep_s_host_keys_parse_with_their_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    local = hosts.local_host()
    assert (local.runs_keep_mb, local.scratch_keep_hours, local.worktree_keep_days, local.cache_keep_days) == (
        2000,
        24,
        7,
        14,
    )
    (tmp_path / "hosts.yml").write_text(
        "local:\n  runs_keep_mb: 0\n  scratch_keep_hours: 2\n  worktree_keep_days: 30\n  cache_keep_days: '3'\n"
    )
    local = hosts.local_host()
    assert (local.runs_keep_mb, local.scratch_keep_hours, local.worktree_keep_days) == (0, 2, 30)
    assert local.cache_keep_days == 14  # a string is no number of days: the default
    (tmp_path / "hosts.yml").write_text("local:\n  runs_keep_mb: -1\n  worktree_keep_days: 1.5\n")
    local = hosts.local_host()
    assert local.runs_keep_mb == 2000 and local.worktree_keep_days == 7


@pytest.mark.unit
def test_the_four_keys_show_on_the_hosts_card(monkeypatch, tmp_path):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    (tmp_path / "hosts.yml").write_text("local:\n  runs_keep_mb: 500\n")
    local = hosts.local_host()
    rows = {r["key"]: r for r in settings_page.host_card({"runs_keep_mb": 500}, local, local.name, {})["rows"]}
    assert rows["runs_keep_mb"]["value"] == "500" and not rows["runs_keep_mb"]["default"]
    for key, value in (("scratch_keep_hours", "24"), ("worktree_keep_days", "7"), ("cache_keep_days", "14")):
        assert rows[key]["value"] == value and rows[key]["default"], key


def _put(p, mb: float, days: float) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * int(mb * MB))
    t = (datetime.now(UTC) - timedelta(days=days)).timestamp()
    os.utime(p, (t, t))


@pytest.mark.integration
async def test_ended_runs_go_oldest_first_past_runs_keep_mb_and_a_live_run_never(agent):
    await park_ticks(agent)
    (paths.home() / "hosts.yml").write_text("local:\n  runs_keep_days: 0\n  runs_keep_mb: 3\n")
    runs = paths.runs_dir()
    live = runs / "ao-live-1-20261101T000000Z.log"
    earlier = runs / "ao-live-1-20261001T000000Z.log"  # a live record's earlier run: it counts
    old, young = runs / "ao-old-2-20261002T000000Z.log", runs / "ao-young-3-20261103T000000Z.log"
    rounds = runs / "ao-x.rounds.log"
    _put(live, 2, 40)  # the oldest of all, and live: never counted, never taken
    _put(earlier, 1, 30)
    _put(old, 1, 20)
    _put(young, 1, 1)
    _put(rounds, 2, 50)  # a base id's rounds log keeps its own rule
    gone = paths.attachments_dir() / "ao-gone-4"
    _put(gone / "a.png", 1, 25)
    _put(paths.attachments_dir() / "ao-live-1" / "b.png", 2, 45)  # a live record's folder
    _put(paths.attachments_dir() / "draft-0123abcd" / "c.png", 2, 45)  # a draft goes by its claim
    agent._prune_runs(datetime.now(UTC), {str(live)}, {"ao-live-1"})
    # 4 MB of ended runs against a 3 MB bound: the oldest, `earlier`, goes and the rest fit
    assert not earlier.exists() and old.exists() and young.exists() and gone.exists()
    (paths.home() / "hosts.yml").write_text("local:\n  runs_keep_days: 0\n  runs_keep_mb: 1\n")
    agent._prune_runs(datetime.now(UTC), {str(live)}, {"ao-live-1"})
    assert not old.exists() and not gone.exists() and young.exists()
    assert live.exists() and rounds.exists() and (paths.attachments_dir() / "draft-0123abcd" / "c.png").exists()
    assert (paths.attachments_dir() / "ao-live-1" / "b.png").exists()
    (paths.home() / "hosts.yml").write_text("local:\n  runs_keep_mb: 0\n")
    _put(old, 5, 2)
    agent._prune_runs(datetime.now(UTC), {str(live)}, {"ao-live-1"})
    assert old.exists() and young.exists()  # `0` is no bound


@pytest.mark.integration
async def test_a_tick_is_not_delayed_by_a_slow_pass_and_starts_no_second(agent, monkeypatch):
    await park_ticks(agent)
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow(*_a, **_kw):
        calls.append(1)
        started.set()
        release.wait(30)  # a pass stubbed to take up to 30 s

    monkeypatch.setattr(agent, "_prune_runs", slow)
    agent._pruned_at = datetime.min.replace(tzinfo=UTC)
    t0 = time.monotonic()
    await agent.tick()
    assert time.monotonic() - t0 < 10, "the tick waited on its sweep"
    assert await asyncio.to_thread(started.wait, 5)
    first = agent._prune_task
    agent._pruned_at = before = datetime.min.replace(tzinfo=UTC)
    await agent.tick()  # the last pass still runs: none started, `_pruned_at` left where it was
    assert agent._prune_task is first and agent._pruned_at == before and len(calls) == 1
    release.set()
    await first
    # a dry run holding the lock: none started either
    with agent._sweep_lock:
        await agent.tick()
        assert agent._prune_task is first and agent._pruned_at == before
    await agent.tick()
    await agent._prune_task
    assert len(calls) == 2 and agent._pruned_at != before
