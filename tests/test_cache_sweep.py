"""The disk sweep's cache rule (design §4.6 *The disk sweep*, *caches*, TD-1945): an agent-cadence tree no
registered repo's `origin` default branch pins goes past `cache_keep_days`, only on the default home, under the
cache's lock; a pinned tree, a young one and every tree where a pin cannot be read are kept."""

from __future__ import annotations

import contextlib
import fcntl
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import park_ticks

from sessionorc import cachesweep, containers, diskbook, paths

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


@pytest.fixture(autouse=True)
def _writable_at_teardown(tmp_path):
    """The trees are read-only, as the launcher makes them: made writable again after each test, so pytest's own
    clean-up of old temp directories can remove them."""
    yield
    for d, dirs, _files in os.walk(tmp_path):
        for n in dirs:
            p = os.path.join(d, n)
            if not os.path.islink(p):
                with contextlib.suppress(OSError):
                    os.chmod(p, 0o755)


def tree(cache: Path, name: str, days: float, extra=None) -> Path:
    """A read-only tree as the launcher makes one, fetched `days` ago; `extra(t)` adds to it before it is aged."""
    t = cache / "trees" / name
    (t / "files" / "scripts").mkdir(parents=True)
    (t / "files" / "scripts" / "s.py").write_text("x")
    if extra is not None:
        extra(t)
    age(t, days)
    return t


def age(t: Path, days: float) -> None:
    """Every entry under `t` written `days` ago and every directory read-only, never through a link."""
    when = time.time() - days * DAY
    for d, dirs, files in os.walk(t, topdown=False):
        for n in files + dirs:
            os.utime(os.path.join(d, n), (when, when), follow_symlinks=False)
        os.chmod(d, 0o555)
        os.utime(d, (when, when))


def test_the_pin_is_read_on_origin_s_default_branch(tmp_path):
    pinned = repo(tmp_path, "p", f'[agent-cadence]\nsource = "/x"\nref = "{PINNED}"\n')
    (pinned / "docs" / "cadence.toml").write_text(f'[agent-cadence]\nsource = "/x"\nref = "{OLD}"\n')  # local only
    assert cachesweep.pin_of(pinned) == (True, PINNED)
    assert cachesweep.pin_of(repo(tmp_path, "n", None)) == (True, None)
    assert cachesweep.pin_of(repo(tmp_path, "u", "[[[ not toml")) == (False, None)
    assert cachesweep.pin_of(tmp_path / "nowhere") == (False, None)
    assert cachesweep.pins([pinned, tmp_path / "n"]) == {PINNED, OLD}  # the checkout's own, as written, too
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


def test_a_checkout_s_own_pin_is_kept_and_a_broken_one_removes_nothing(tmp_path):
    pinned = repo(tmp_path, "p", f'[agent-cadence]\nsource = "/x"\nref = "{PINNED}"\n')
    wt = tmp_path / "wt"
    git(pinned, "worktree", "add", "-q", "-b", "bump", str(wt))
    (wt / "docs" / "cadence.toml").write_text(f'[agent-cadence]\nsource = "/x"\nref = "{YOUNG}"\n')  # a bump
    assert cachesweep.pins([pinned]) == {PINNED, YOUNG}
    (wt / "docs" / "cadence.toml").write_text("[[[ mid-edit")
    assert cachesweep.pins([pinned]) is None


def test_a_half_removed_aside_is_cleared_and_other_names_are_never_the_rule_s(tmp_path):
    cache = tmp_path / "cache"
    stale = tree(cache, ".tmp-sweep-x-1", 0)
    link = cache / "trees" / OLD
    link.symlink_to(tmp_path)  # a link named like a commit is never followed nor removed
    assert cachesweep.sweep_trees(set(), 14, time.time(), cache) == []
    assert not stale.exists() and link.is_symlink() and tmp_path.exists()


def outside(tmp_path: Path, days: float) -> Path:
    """A read-only directory outside the cache, written `days` ago, for a link to point at."""
    t = tmp_path / "outside"
    (t / "sub").mkdir(parents=True)
    (t / "sub" / "f").write_text("x")
    age(t, days)
    return t


def test_an_old_link_named_like_a_commit_or_an_aside_is_never_followed_nor_removed(tmp_path):
    """Only the symlink guards keep these: the link is as old as the directory it names, past `cache_keep_days`."""
    cache = tmp_path / "cache"
    target = outside(tmp_path, 30)
    (cache / "trees").mkdir(parents=True)
    link = cache / "trees" / OLD
    link.symlink_to(target)
    aside = cache / "trees" / ".tmp-sweep-y-1"
    aside.symlink_to(target)
    for p in (link, aside):
        os.utime(p, (time.time() - 30 * DAY,) * 2, follow_symlinks=False)
    assert cachesweep.sweep_trees(set(), 14, time.time(), cache) == []
    assert link.is_symlink() and aside.is_symlink() and (target / "sub" / "f").exists()
    assert sorted(os.listdir(cache / "trees")) == sorted([OLD, aside.name])
    assert target.stat().st_mode & 0o777 == 0o555 and (target / "sub").stat().st_mode & 0o777 == 0o555


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every directory")
def test_a_tree_holding_an_unreadable_directory_counts_as_written_now(tmp_path):
    cache = tmp_path / "cache"
    shut = tree(cache, OLD, 30, extra=lambda t: (t / "files" / "shut").mkdir())
    os.chmod(shut / "files" / "shut", 0o000)
    assert cachesweep._newest_write(shut) > time.time() - 60
    assert cachesweep.sweep_trees(set(), 14, time.time(), cache) == []
    assert shut.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every directory")
def test_a_tree_holding_an_entry_that_cannot_be_stat_ed_counts_as_written_now(tmp_path):
    """A directory that can be listed but not searched: its entries are named, and each `lstat` is refused."""
    cache = tmp_path / "cache"
    blind = tree(cache, OLD, 30)
    os.chmod(blind / "files" / "scripts", 0o444)
    assert cachesweep._newest_write(blind) > time.time() - 60
    assert cachesweep.sweep_trees(set(), 14, time.time(), cache) == []
    assert blind.exists()


def test_a_read_only_directory_a_tree_links_to_is_never_made_writable(tmp_path):
    cache = tmp_path / "cache"
    target = outside(tmp_path, 30)
    old = tree(cache, OLD, 30, extra=lambda t: (t / "files" / "elsewhere").symlink_to(target))
    assert cachesweep.sweep_trees(set(), 14, time.time(), cache) == [str(old)]
    assert not old.exists() and (target / "sub" / "f").exists()
    assert target.stat().st_mode & 0o777 == 0o555


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every file")
def test_a_checkout_s_unreadable_pin_file_removes_nothing(tmp_path):
    pinned = repo(tmp_path, "p", f'[agent-cadence]\nsource = "/x"\nref = "{PINNED}"\n')
    wt = tmp_path / "wt"
    git(pinned, "worktree", "add", "-q", "-b", "bump", str(wt))
    os.chmod(wt / "docs" / "cadence.toml", 0o000)
    assert cachesweep.checkout_pins(pinned) == (False, set())
    assert cachesweep.pins([pinned]) is None


def test_a_pin_file_missing_from_the_object_store_is_no_reading(tmp_path):
    """The commit's tree lists `docs/cadence.toml`, but its blob is gone: a broken store, never *no pin*."""
    pinned = repo(tmp_path, "p", f'[agent-cadence]\nsource = "/x"\nref = "{PINNED}"\n')
    blob = git(pinned, "rev-parse", "origin/main:docs/cadence.toml").strip()
    (pinned / ".git" / "objects" / blob[:2] / blob[2:]).unlink()
    assert cachesweep.pin_of(pinned) == (False, None)
    assert cachesweep.pins([pinned]) is None


def shipped(directory: Path, name: str, days: float) -> Path:
    t = directory / name
    (t / "files").mkdir(parents=True)
    (t / "files" / "s.py").write_text("x")
    age(t, days)
    return t


def node_sweep(directory: Path, pinned, dry: bool = False, keep: int = 14) -> tuple[list[str], diskbook.Tally]:
    tally = diskbook.Tally()
    read = pinned if callable(pinned) else (lambda: pinned)
    return cachesweep.sweep_node_trees(directory, read, keep, time.time(), tally=tally, dry=dry), tally


def test_a_node_s_unpinned_old_tree_goes_and_a_pinned_or_young_one_stays(tmp_path):
    d = tmp_path / "cadence"
    p, o, y = shipped(d, PINNED, 30), shipped(d, OLD, 30), shipped(d, YOUNG, 1)
    removed, t = node_sweep(d, {PINNED})
    assert removed == [str(o)] and p.exists() and y.exists() and not o.exists()
    assert (str(p), "pinned") in t.kept and {str(p), str(y)} <= t.listed
    assert not [n for n in os.listdir(d) if n.startswith(".tmp-sweep-")]


def test_a_node_s_unreadable_pin_removes_none_of_its_trees(tmp_path):
    d = tmp_path / "cadence"
    o = shipped(d, OLD, 30)
    removed, t = node_sweep(d, None)
    assert not removed and o.exists() and str(o) in t.listed


def test_a_node_pin_that_moves_before_the_rename_keeps_its_tree(tmp_path):
    d = tmp_path / "cadence"
    o = shipped(d, OLD, 30)
    reads = iter([{PINNED}, {OLD}])
    removed, t = node_sweep(d, lambda: next(reads))
    assert not removed and o.exists() and (str(o), "pinned") in t.kept


def test_a_node_pin_that_stops_reading_before_the_rename_keeps_its_tree(tmp_path):
    d = tmp_path / "cadence"
    o = shipped(d, OLD, 30)
    reads = iter([{PINNED}, None])
    removed, _t = node_sweep(d, lambda: next(reads))
    assert not removed and o.exists()


def test_a_node_dry_run_counts_and_removes_nothing(tmp_path):
    d = tmp_path / "cadence"
    o = shipped(d, OLD, 30)
    aside = shipped(d, f".tmp-sweep-{OLD}-1", 30)
    removed, t = node_sweep(d, {PINNED}, dry=True)
    assert removed == [str(o)] and o.exists() and aside.exists() and str(o) in t.gone_paths


def test_a_dead_pass_s_aside_goes_and_a_ship_in_progress_is_not_read(tmp_path):
    d = tmp_path / "cadence"
    aside, ship = shipped(d, f".tmp-sweep-{OLD}-1", 30), shipped(d, f".ship-{OLD}-1", 30)
    _removed, t = node_sweep(d, {PINNED})
    assert not aside.exists() and ship.exists() and str(ship) not in t.listed


def test_a_link_named_like_a_commit_in_a_node_s_directory_is_never_followed(tmp_path):
    d, target = tmp_path / "cadence", tmp_path / "precious"
    d.mkdir()
    target.mkdir()
    (target / "f").write_text("x")
    (d / OLD).symlink_to(target)
    removed, _t = node_sweep(d, {PINNED})
    assert not removed and (target / "f").exists() and (d / OLD).is_symlink()


async def test_the_pass_sweeps_each_node_by_the_home_s_and_its_checkout_s_pins(agent, monkeypatch, tmp_path):
    await park_ticks(agent)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(paths, "DEFAULT_HOME", paths.home())
    home_repo = repo(tmp_path, "h", f'[agent-cadence]\nsource = "/x"\nref = "{PINNED}"\n')
    checkout = repo(tmp_path, "n", f'[agent-cadence]\nsource = "/x"\nref = "{YOUNG}"\n')
    node = SimpleNamespace(node_dir=tmp_path / "node", devcontainer=checkout)
    monkeypatch.setattr(containers, "container_nodes", lambda: {"n": node})
    d = node.node_dir / "cadence"
    by_home, by_node, unpinned = shipped(d, PINNED, 30), shipped(d, YOUNG, 30), shipped(d, OLD, 30)
    agent._sweep_roots = [str(home_repo)]
    agent._sweep_caches(datetime.now(UTC))
    assert by_home.exists() and by_node.exists() and not unpinned.exists()
