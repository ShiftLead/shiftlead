"""The disk sweep's pass result (design §4.6 *The sweep's reading*, TD-1945): per kind the bytes held, each item's
size as last measured and kept in memory, *partial* until every item is measured (after a restart too); the bytes a
pass removed; and each item it kept with why — *another home*, *no owner*, *large scratch*, *pinned* and a
worktree's own words among them."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import park_ticks
from test_cache_sweep import OLD, PINNED, tree
from test_scratch_sweep import age as age_scratch
from test_scratch_sweep import made
from test_worktree_sweep import repo, run, wt_of  # noqa: F401 — `repo` is a fixture

from sessionorc import cachesweep, diskbook, hosts, paths, scratch, worktreesweep

HOUR = 3600


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "scr"
    r.mkdir()
    return r


@pytest.mark.unit
def test_a_size_counts_each_entry_once_and_a_symlink_as_the_link(tmp_path):
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "f").write_bytes(b"x" * 1000)
    big = tmp_path / "big"
    big.write_bytes(b"y" * 100_000)
    (d / "link").symlink_to(big)
    got = diskbook.size_of(d)
    assert 1000 < got < 100_000  # the link's own bytes, never its target's
    assert diskbook.size_of(tmp_path / "nowhere") is None
    assert diskbook.size_of(d, deadline=time.monotonic() - 1) is None


@pytest.mark.unit
def test_the_book_holds_what_it_measured_and_reads_partial_until_every_item_is():
    book = diskbook.Book()
    t = book.tallies()
    t["worktrees"].measure("/a", 10)
    t["worktrees"].list("/b")  # listed, never measured: past the pass's budget
    got = book.close(t)
    assert got["worktrees"] == {"held": 10, "partial": True, "removed": 0, "kept": []}
    t = book.tallies()
    t["worktrees"].list("/a")  # sized last pass: held as last measured
    t["worktrees"].measure("/b", 5)
    t["worktrees"].gone("/a")
    got = book.close(t)
    assert got["worktrees"] == {"held": 5, "partial": False, "removed": 10, "kept": []}
    t = book.tallies()
    t["worktrees"].unlisted = True  # the rule could not list: the last reading stands, *partial*
    assert book.close(t)["worktrees"]["held"] == 5 and book.sizes["worktrees"] == {"/b": 5}
    t = diskbook.Book().tallies()  # a host-agent restart: nothing measured yet
    t["worktrees"].list("/b")
    assert diskbook.Book().close(t)["worktrees"]["partial"] is True
    assert set(got) == set(diskbook.KINDS)


@pytest.mark.unit
def test_the_scratch_rule_counts_what_it_removes_and_keeps_another_home_s_and_an_unowned_one(root, tmp_path):
    home, other = tmp_path / "home", tmp_path / "other"
    home.mkdir()
    other.mkdir()
    theirs, gone, unowned = made(root, str(other)), made(root, str(tmp_path / "gone")), made(root, str(home))
    fresh = made(root, str(home))
    (unowned / "owner.json").unlink()
    (gone / "data").write_bytes(b"x" * 5000)
    (unowned / "data").write_bytes(b"x" * 3000)
    for d in (theirs, gone, unowned):
        age_scratch(d, 2 * HOUR)
    book = diskbook.Book()
    t = book.tallies()
    size_gone = diskbook.size_of(gone)
    scratch.sweep(root, str(home), {}, 24, time.time(), lambda _p: False, [], t["scratch"])
    got = book.close(t)["scratch"]
    assert not gone.exists() and got["removed"] == size_gone
    assert sorted((k["path"], k["why"]) for k in got["kept"]) == sorted(
        [(str(unowned), "no owner"), (str(theirs), "another home")]
    )
    # held: the unowned one and the fresh one (sized once, on first sight); another home's bytes are its own
    assert got["held"] == diskbook.size_of(unowned) + diskbook.size_of(fresh) and not got["partial"]


@pytest.mark.integration
async def test_the_hourly_pass_sizes_a_live_scratch_by_its_walk_and_names_a_large_one(agent, monkeypatch):
    await park_ticks(agent)
    root = hosts.DEFAULT_SCRATCH_ROOT
    live, large = made(root, str(paths.home()), "ao-l-1"), made(root, str(paths.home()), "ao-g-2")
    (live / "f").write_bytes(b"x" * 4000)
    stale = large / "old"
    stale.write_bytes(b"x")
    t = time.time() - 2 * 86400
    os.utime(stale, (t, t))
    monkeypatch.setattr(scratch, "SWEEP_TOUCH_FILES", 0)  # the first stale file is past the cap
    try:
        got = agent._prune_runs(datetime.now(UTC), set(), set(), {"ao-l-1": str(live), "ao-g-2": str(large)})
        s = got["scratch"]
        assert {"path": str(large), "why": "large scratch"} in s["kept"]
        assert s["held"] == diskbook.size_of(live) and s["partial"]  # the large one's walk stopped short
    finally:
        for d in (live, large):
            scratch._remove(d)


@pytest.mark.unit
def test_worktrees_read_partial_until_each_is_weighed_and_after_a_restart(repo, monkeypatch):  # noqa: F811
    a, b = wt_of(repo, "a"), wt_of(repo, "b")  # each kept: young
    clock = [0.0]
    monkeypatch.setattr(worktreesweep.time, "monotonic", lambda: clock[0])
    real = worktreesweep.weigh

    def weigh(*args, **kw):
        clock[0] += worktreesweep.SWEEP_WORKTREE_S  # each weigh spends a whole pass
        return real(*args, **kw)

    monkeypatch.setattr(worktreesweep, "weigh", weigh)
    book = diskbook.Book()
    t = book.tallies()
    first = run(repo, tally=t["worktrees"])
    got = book.close(t)["worktrees"]
    assert got["partial"] and got["held"] == diskbook.size_of(a)
    assert got["kept"] == [{"path": str(a), "why": first.kept[0][1]}]
    t = book.tallies()
    run(repo, cursor=first.cursor, tally=t["worktrees"])
    got = book.close(t)["worktrees"]
    assert not got["partial"] and got["held"] == diskbook.size_of(a) + diskbook.size_of(b)
    t = diskbook.Book().tallies()  # a restart: the memory is empty again
    run(repo, tally=t["worktrees"])
    assert diskbook.Book().close(t)["worktrees"]["partial"]


@pytest.mark.unit
def test_the_cache_rule_counts_a_removed_tree_and_keeps_an_old_pinned_one(tmp_path):
    cache = tmp_path / "cache"
    p, o = tree(cache, PINNED, 30), tree(cache, OLD, 30)
    size_o, size_p = diskbook.size_of(o), diskbook.size_of(p)
    book = diskbook.Book()
    t = book.tallies()
    try:
        cachesweep.sweep_trees({PINNED}, 14, time.time(), cache, tally=t["caches"])
        got = book.close(t)["caches"]
        assert not o.exists() and got["removed"] == size_o
        assert got["held"] == size_p and got["kept"] == [{"path": str(p), "why": "pinned"}]
    finally:
        cachesweep._writable(cache)


@pytest.mark.unit
def test_every_adapter_s_transcripts_outlive_a_sweep_through_its_roots_and_symlinks(repo, root, tmp_path, monkeypatch):  # noqa: F811
    """The Done when's walk (§4.6 *The disk sweep*, §9 invariant 16): a transcript under every adapter's
    `transcript_roots()` and a symlink to each inside a scratch directory and a worktree the sweep removes; a profile
    `config_dir` holding transcripts inside a removable worktree. Every transcript is intact, that worktree kept."""
    from test_worktree_sweep import age as age_wt
    from test_worktree_sweep import commit, squash_merge

    from sessionorc import adapters

    fake = tmp_path / "fakehome"  # the tools' own stores under `~` are this test's, never the person's
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    home = tmp_path / "sl"
    home.mkdir()
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("GEMINI_CLI_HOME", raising=False)
    holds, gone = wt_of(repo, "holds"), wt_of(repo, "gone")
    for wt in (holds, gone):
        commit(wt, wt.name, msg=wt.name)
        squash_merge(repo, wt, wt.name)
    (home / "profiles.yml").write_text(
        "profiles:\n"
        "  default: {adapter: claude-code}\n"
        f"  inside: {{adapter: claude-code, config_dir: {holds / 'cfg'}}}\n"
        f"  gem: {{adapter: gemini, config_dir: {tmp_path / 'g'}}}\n"
        f"  grok: {{adapter: grok, config_dir: {tmp_path / 'x'}}}\n"
    )
    troots, blind = adapters.transcript_roots()
    assert not blind and holds / "cfg" / "projects" in troots
    assert {fake / ".claude" / "projects", fake / ".gemini" / "tmp", tmp_path / "x" / "sessions"} <= set(troots)
    planted = []
    for i, t in enumerate(troots):
        t.mkdir(parents=True, exist_ok=True)
        (t / f"t{i}.jsonl").write_text("{}\n")
        planted.append(t / f"t{i}.jsonl")
    ended = made(root, str(home), "ao-e-1")
    for i, f in enumerate(planted):
        (ended / f"l{i}").symlink_to(f)
        (gone / f"l{i}").symlink_to(f)
        (gone / f"d{i}").symlink_to(f.parent)
    git_exclude = Path(repo) / ".git" / "info" / "exclude"
    git_exclude.write_text("l*\nd*\n")  # the links are no untracked work that would keep the worktree
    age_scratch(ended, 48 * HOUR)
    for wt in (holds, gone):
        age_wt(wt)
    kept = scratch.sweep(root, str(home), {str(ended): ("ao-e-1", time.time() - 48 * HOUR)}, 24, time.time(),
                         lambda _p: False, troots)  # fmt: skip
    got = run(repo, transcript_roots=troots)
    assert not ended.exists() and kept == []
    assert str(gone) in got.removed and dict(got.kept)[str(holds)] == "transcripts"
    assert all(f.read_text() == "{}\n" for f in planted)
