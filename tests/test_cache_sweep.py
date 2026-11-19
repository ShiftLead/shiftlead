"""The disk sweep's cache rule (design §4.6 *The disk sweep*, *caches*, TD-1945): an agent-cadence tree no
registered repo's `origin` default branch pins goes past `cache_keep_days`, only on the default home, under the
cache's lock; a pinned tree, a young one and every tree where a pin cannot be read are kept."""

from __future__ import annotations

import fcntl
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import park_ticks

from sessionorc import cachesweep, paths

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}
DAY = 86400
PINNED, OLD, YOUNG = "a" * 40, "b" * 40, "c" * 40


def git(d, *args) -> str:
    return subprocess.run(["git", "-C", str(d), *args], env=ENV, check=True, capture_output=True, text=True).stdout


def repo(tmp_path: Path, name: str, toml: str | None) -> Path:
    """A clone whose `origin/main` carries `toml` as its `docs/cadence.toml` (None: no such file)."""
    bare, c = tmp_path / f"{name}.git", tmp_path / name
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(tmp_path, "clone", "-q", str(bare), str(c))
    git(c, "checkout", "-q", "-b", "main")
    (c / "x").write_text("x")
    if toml is not None:
        (c / "docs").mkdir()
        (c / "docs" / "cadence.toml").write_text(toml)
    git(c, "add", "-A")
    git(c, "commit", "-qm", "c")
    git(c, "push", "-q", "-u", "origin", "main")
    return c


def tree(cache: Path, name: str, days: float) -> Path:
    """A read-only tree as the launcher makes one, fetched `days` ago."""
    t = cache / "trees" / name
    (t / "files" / "scripts").mkdir(parents=True)
    (t / "files" / "scripts" / "s.py").write_text("x")
    when = time.time() - days * DAY
    for d, dirs, files in os.walk(t, topdown=False):
        for n in files + dirs:
            os.utime(os.path.join(d, n), (when, when))
        os.chmod(d, 0o555)
        os.utime(d, (when, when))
    return t


def test_the_pin_is_read_on_origin_s_default_branch(tmp_path):
    pinned = repo(tmp_path, "p", f'[agent-cadence]\nsource = "/x"\nref = "{PINNED}"\n')
    (pinned / "docs" / "cadence.toml").write_text(f'[agent-cadence]\nsource = "/x"\nref = "{OLD}"\n')  # local only
    assert cachesweep.pin_of(pinned) == (True, PINNED)
    assert cachesweep.pin_of(repo(tmp_path, "n", None)) == (True, None)
    assert cachesweep.pin_of(repo(tmp_path, "u", "[[[ not toml")) == (False, None)
    assert cachesweep.pin_of(tmp_path / "nowhere") == (False, None)
    assert cachesweep.pins([pinned, tmp_path / "n"]) == {PINNED}
    assert cachesweep.pins([pinned, tmp_path / "u"]) is None


def test_an_unpinned_old_tree_goes_and_a_pinned_or_young_one_stays(tmp_path):
    cache = tmp_path / "cache"
    p, o, y = tree(cache, PINNED, 30), tree(cache, OLD, 30), tree(cache, YOUNG, 2)
    other = cache / "trees" / ".tmp-index-x"  # not a commit's name: never the rule's
    other.mkdir()
    removed = cachesweep.sweep_trees({PINNED}, 14, time.time(), cache)
    assert removed == [str(o)]
    assert p.exists() and not o.exists() and y.exists() and other.exists()
    assert not [n for n in os.listdir(cache / "trees") if n.startswith(".tmp-sweep-")]


def test_a_held_cache_lock_removes_nothing(tmp_path):
    cache = tmp_path / "cache"
    o = tree(cache, OLD, 30)
    with open(cache / "lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert cachesweep.sweep_trees(set(), 14, time.time(), cache) == []
    assert o.exists()


@pytest.mark.integration
async def test_only_the_default_home_with_a_roster_takes_a_tree(agent, monkeypatch, tmp_path):
    """A scratch home's sweep removes no tree, nor does a default home that registers no repo; a default home with
    a registered repo removes the trees it does not pin."""
    await park_ticks(agent)
    cache = tmp_path / "xdg" / "agent-cadence"
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    pinned = repo(tmp_path, "p", f'[agent-cadence]\nsource = "/x"\nref = "{PINNED}"\n')
    p, o = tree(cache, PINNED, 30), tree(cache, OLD, 30)
    now = datetime.now(UTC)
    agent._sweep_roots = [str(pinned)]
    agent._sweep_caches(now)  # the test's home is not the default one
    assert o.exists()
    monkeypatch.setattr(paths, "DEFAULT_HOME", paths.home())
    agent._sweep_roots = []
    agent._sweep_caches(now)  # the default home, no repo registered
    assert o.exists()
    agent._sweep_roots = [str(pinned)]
    agent._sweep_caches(now)
    assert p.exists() and not o.exists()
