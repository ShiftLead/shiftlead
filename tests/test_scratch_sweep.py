"""The disk sweep's scratch rule and its *landed* test (design §4.6 *The disk sweep*, TD-1945): an ended record's
scratch goes past `scratch_keep_hours`, one no record names an hour after its newest write, and none holding git
work, another existing home's, one with no `owner.json` or a live record's; `gitinfo.landed_of` answers as
agent-cadence's `landed_of` and `landed_since_edited` do."""

from __future__ import annotations

import os
import secrets
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import park_ticks

from sessionorc import gitinfo, hosts, paths, scratch
from sessionorc.models import Session

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}
HOUR = 3600


def git(d, *args) -> str:
    return subprocess.run(["git", "-C", str(d), *args], env=ENV, check=True, capture_output=True, text=True).stdout


def commit(d, name: str, text: str, msg: str = "c") -> None:
    p = Path(d) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    git(d, "add", "-A")
    git(d, "commit", "-qm", msg)


@pytest.fixture
def origin(tmp_path):
    """A bare origin whose `main` carries a `docs/cadence.toml`, and a seed checkout that pushes to it."""
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(bare), str(seed))
    git(seed, "checkout", "-q", "-b", "main")
    commit(seed, "docs/cadence.toml", "# pin\n")
    commit(seed, "a.txt", "a\n")
    git(seed, "push", "-q", "origin", "main")
    return bare, seed


@pytest.fixture
def root(tmp_path):
    """A root of this test's own, never the run's shared one, which every child agent's sweep reads: the sweep
    needs no short root, only the create does."""
    r = tmp_path / "scr"
    r.mkdir()
    return r


def age(path: Path, seconds: float) -> None:
    t = time.time() - seconds
    for dirpath, dirs, files in os.walk(path):
        for n in dirs + files:
            os.utime(os.path.join(dirpath, n), (t, t), follow_symlinks=False)
    os.utime(path, (t, t))


def made(root: Path, home: str, rid: str = "ao-x-1") -> Path:
    p = scratch.parent(root)
    p.mkdir(mode=0o700, exist_ok=True)
    d = p / secrets.token_hex(4)
    d.mkdir(mode=0o700)
    scratch.write_owner(d, rid, home)
    return d


def sweep(root, home, named=None, live=(), transcripts=(), keep_hours=24):
    return scratch.sweep(
        root, home, named or {}, keep_hours, time.time(), lambda p: p in live, [Path(t) for t in transcripts]
    )


def test_an_ended_record_s_scratch_goes_past_its_keep_and_a_live_one_s_never(root, tmp_path):
    home = str(tmp_path / "home")
    ended, young, live = made(root, home, "ao-e-1"), made(root, home, "ao-y-2"), made(root, home, "ao-l-3")
    for d in (ended, young, live):
        age(d, 48 * HOUR)
    now = time.time()
    named = {str(ended): ("ao-e-1", now - 25 * HOUR), str(young): ("ao-y-2", now - HOUR), str(live): ("ao-l-3", None)}
    assert sweep(root, home, named) == []
    assert not ended.exists() and young.exists() and live.exists()


def test_one_no_record_names_goes_an_hour_after_its_newest_write(root, tmp_path):
    home = str(tmp_path / "home")
    old, fresh = made(root, home, "ao-o-1"), made(root, home, "ao-f-2")
    age(old, 2 * HOUR)
    age(fresh, 2 * HOUR)
    (fresh / "new.txt").write_text("x")  # a write inside it in the last hour
    sweep(root, home)
    assert not old.exists() and fresh.exists()


def test_another_home_s_and_an_unowned_one_are_left_and_a_gone_home_s_goes(root, tmp_path):
    home, other = tmp_path / "home", tmp_path / "other"
    home.mkdir()
    other.mkdir()
    theirs, gone, unowned = made(root, str(other)), made(root, str(tmp_path / "gone")), made(root, str(home))
    (unowned / "owner.json").unlink()
    for d in (theirs, gone, unowned):
        age(d, 2 * HOUR)
    kept = sweep(root, str(home))
    assert theirs.exists() and not gone.exists() and unowned.exists()
    assert sorted(kept) == sorted([(str(unowned), "no owner"), (str(theirs), "another home")])
    # the second home's sweep over the same root removes none of the first's
    mine = made(root, str(home), "ao-m-1")
    age(mine, 2 * HOUR)
    sweep(root, str(other))
    assert mine.exists()


def test_a_record_resumed_since_the_snapshot_keeps_its_scratch(root, tmp_path):
    home = str(tmp_path / "home")
    d = made(root, home)
    age(d, 48 * HOUR)
    kept = sweep(root, home, {str(d): ("ao-x-1", time.time() - 30 * HOUR)}, live={str(d)})
    assert d.exists() and kept == [(str(d), "live record")]


def test_a_transcript_store_inside_keeps_it(root, tmp_path):
    home = str(tmp_path / "home")
    d = made(root, home)
    (d / "cfg" / "projects").mkdir(parents=True)
    (d / "cfg" / "projects" / "t.jsonl").write_text("{}")
    age(d, 2 * HOUR)
    assert sweep(root, home, transcripts=[d / "cfg" / "projects"]) == [(str(d), "transcripts")]
    assert (d / "cfg" / "projects" / "t.jsonl").exists()


def _clone(origin, d: Path) -> Path:
    bare, _ = origin
    c = d / "repo"
    git(d, "clone", "-q", str(bare), str(c))
    return c


@pytest.mark.parametrize(
    "case",
    ["unpushed-other-branch", "upstream-gone", "stash", "unreadable", "tracks-main", "untracked", "detached"],
)
def test_git_work_is_kept(case, origin, root, tmp_path):
    home = str(tmp_path / "home")
    d = made(root, home)
    c = _clone(origin, d)
    if case == "unpushed-other-branch":  # a branch it has not checked out, with a commit only here
        git(c, "checkout", "-q", "-b", "side")
        commit(c, "s.txt", "s\n")
        git(c, "checkout", "-q", "main")
    elif case == "upstream-gone":  # pushed once, its remote branch deleted, then a later local commit
        git(c, "checkout", "-q", "-b", "gone")
        commit(c, "g.txt", "g\n")
        git(c, "push", "-q", "-u", "origin", "gone")
        git(c, "push", "-q", "origin", "--delete", "gone")
        commit(c, "g2.txt", "g2\n")
    elif case == "stash":
        (c / "a.txt").write_text("changed\n")
        git(c, "stash", "-q")
    elif case == "unreadable":
        (c / ".git" / "HEAD").write_text("garbage\n")
    elif case == "tracks-main":  # a branch tracking origin/main with a local commit and no origin/<branch>
        git(c, "checkout", "-q", "-b", "work", "--track", "origin/main")
        commit(c, "w.txt", "w\n")
    elif case == "untracked":
        (c / "new.txt").write_text("n\n")
    elif case == "detached":
        git(c, "checkout", "-q", "--detach")
        commit(c, "d.txt", "d\n")
    age(d, 2 * HOUR)
    assert sweep(root, home) == [(str(d), scratch.GIT_WORK)]
    assert d.exists() and scratch.git_work(d)  # weighed after: a weigh can write objects, a newer write


def test_a_clone_whose_work_is_all_pushed_goes(origin, root, tmp_path):
    home = str(tmp_path / "home")
    d = made(root, home)
    c = _clone(origin, d)
    git(c, "checkout", "-q", "-b", "pushed")
    commit(c, "p.txt", "p\n")
    git(c, "push", "-q", "-u", "origin", "pushed")
    age(d, 2 * HOUR)
    assert not scratch.git_work(d)
    sweep(root, home)
    assert not d.exists()


def test_a_worktree_goes_when_its_own_branch_is_landed_and_clean(origin, root, tmp_path):
    """A worktree of a repo with unlanded branches is weighed over its own branch alone; once gone, its repo's
    `git worktree list` no longer names it."""
    bare, seed = origin
    home = str(tmp_path / "home")
    repo = tmp_path / "main"
    git(tmp_path, "clone", "-q", str(bare), str(repo))
    git(repo, "branch", "unlanded")
    git(repo, "checkout", "-q", "unlanded")
    commit(repo, "u.txt", "u\n")  # a branch only here, in the repo, not the worktree's
    git(repo, "checkout", "-q", "main")
    d = made(root, home)
    wt = d / "wt"
    git(repo, "worktree", "add", "-q", "-b", "done", str(wt), "origin/main")
    commit(wt, "x.txt", "x\n")
    # its content squash-merged onto origin/main, its remote branch never pushed
    commit(seed, "x.txt", "x\n", "squash of done")
    git(seed, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    assert gitinfo.landed_of(wt, "refs/heads/done", root=repo, need_pin=True) == "yes"
    age(d, 2 * HOUR)
    assert sweep(root, home) == []
    assert not d.exists()
    assert str(wt) not in git(repo, "worktree", "list")


def test_a_detached_worktree_with_a_commit_on_no_remote_is_git_work(origin, root, tmp_path):
    bare, _ = origin
    home = str(tmp_path / "home")
    repo = tmp_path / "main"
    git(tmp_path, "clone", "-q", str(bare), str(repo))
    d = made(root, home)
    wt = d / "wt"
    git(repo, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    commit(wt, "x.txt", "x\n")
    age(d, 2 * HOUR)
    assert sweep(root, home) == [(str(d), scratch.GIT_WORK)]


def test_landed_of_answers_as_the_script_does(origin, tmp_path):
    bare, seed = origin
    c = tmp_path / "c"
    git(tmp_path, "clone", "-q", str(bare), str(c))
    git(c, "checkout", "-q", "-b", "fresh", "origin/main")
    assert gitinfo.landed_of(c, "fresh", root=c) == "empty"
    git(c, "checkout", "-q", "-b", "open", "origin/main")
    commit(c, "o.txt", "o\n")
    assert gitinfo.landed_of(c, "open", root=c) == "no"
    # squash-merged, then main edits the file again: *since*
    git(c, "checkout", "-q", "-b", "since", "origin/main")
    commit(c, "s.txt", "s\n")
    commit(seed, "s.txt", "s\n", "squash of since")
    commit(seed, "s.txt", "s, edited later\n", "edit")
    # squash-merged, then reverted on main: *reverted*
    git(c, "checkout", "-q", "-b", "rev", "origin/main")
    commit(c, "r.txt", "r\n")
    commit(seed, "r.txt", "r\n", "squash of rev")
    git(seed, "rm", "-q", "r.txt")
    git(seed, "commit", "-qm", "revert rev")
    git(seed, "push", "-q", "origin", "main")
    git(c, "fetch", "-q", "origin")
    assert gitinfo.landed_of(c, "since", root=c) == "since"
    assert gitinfo.landed_of(c, "rev", root=c) == "reverted"
    # a pin that cannot be parsed, a missing one where needed, or no origin/<default>: *unreadable*
    (c / "docs" / "cadence.toml").write_text("[[[ not toml")
    assert gitinfo.landed_of(c, "since", root=c) == "unreadable"
    assert gitinfo.landed_of(c, "since", root=tmp_path / "nowhere") == "since"
    assert gitinfo.landed_of(c, "since", root=tmp_path / "nowhere", need_pin=True) == "unreadable"
    git(c, "update-ref", "-d", "refs/remotes/origin/main")
    git(c, "remote", "set-head", "origin", "-d")
    assert gitinfo.landed_of(c, "since", root=tmp_path / "nowhere") == "unreadable"


@pytest.mark.integration
async def test_the_hourly_pass_takes_an_ended_record_s_scratch(agent):
    """Through the host agent: the tick's snapshot names each record's scratch with when it ended, and the pass
    reads the records again just before each removal."""
    await park_ticks(agent)
    root = hosts.DEFAULT_SCRATCH_ROOT
    ended, back = made(root, str(paths.home()), "ao-e-1"), made(root, str(paths.home()), "ao-b-2")
    for d in (ended, back):
        age(d, 48 * HOUR)
    long_ago = (datetime.now(UTC) - timedelta(hours=30)).isoformat()
    for rid, d in (("ao-e-1", ended), ("ao-b-2", back)):
        agent.sessions[rid] = Session(
            id=rid, name=rid, kind="interactive", adapter="shell", dir="/", state="exited", scratch=str(d),
            host=agent.host, ended={"how": "tool", "at": long_ago},
        )  # fmt: skip
    from sessionorc.agent_tick import _scratch_named

    named = _scratch_named(agent.sessions.values(), agent.host, datetime.now(UTC))
    assert named[str(ended)][0] == "ao-e-1" and named[str(ended)][1] is not None
    agent.sessions["ao-b-2"].state = "idle"  # resumed after the snapshot
    agent._prune_runs(datetime.now(UTC), set(), set(), None, named)
    assert not ended.exists() and back.exists()
    scratch._remove(back)
    for rid in ("ao-e-1", "ao-b-2"):
        del agent.sessions[rid]


def test_a_symlink_inside_is_removed_as_a_link_and_its_target_kept(root, tmp_path):
    home = str(tmp_path / "home")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("k")
    d = made(root, home)
    (d / "link").symlink_to(outside)
    (d / "flink").symlink_to(outside / "keep.txt")
    age(d, 2 * HOUR)
    sweep(root, home)
    assert not d.exists() and (outside / "keep.txt").read_text() == "k"


@pytest.mark.parametrize("where", ["nested", "top"])
def test_a_bare_repo_with_work_on_no_remote_is_git_work(where, origin, root, tmp_path):
    home = str(tmp_path / "home")
    d = made(root, home)
    work = tmp_path / "w"
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    commit(work, "x.txt", "x\n")
    bare = d / "b.git" if where == "nested" else d
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(work, "push", "-q", str(bare), "main")
    age(d, 2 * HOUR)
    assert sweep(root, home) == [(str(d), scratch.GIT_WORK)]


def test_the_snapshot_names_each_scratch_with_its_latest_end_and_a_live_record_wins():
    from sessionorc.agent_tick import _scratch_named

    now = datetime.now(UTC)

    def rec(rid, state, path, ended=None, since="2026-11-01T00:00:00+00:00", host="h"):
        return Session(
            id=rid, name=rid, kind="interactive", adapter="shell", dir="/", state=state, scratch=path,
            host=host, ended=ended, since=since,
        )  # fmt: skip

    records = [
        rec("a", "exited", "/s/1", {"at": "2026-11-02T00:00:00+00:00"}),
        rec("b", "closed", "/s/1", {"at": "2026-11-03T00:00:00+00:00"}),
        rec("c", "exited", "/s/2", {"at": "2026-11-03T00:00:00+00:00"}),
        rec("d", "idle", "/s/2"),
        rec("e", "closed", "/s/3", None, since="garbage"),
        rec("f", "exited", "/s/4", None),
        rec("g", "idle", "/s/5", host="other"),
    ]
    got = _scratch_named(records, "h", now)
    assert got["/s/1"] == ("b", datetime(2026, 11, 3, tzinfo=UTC).timestamp())
    assert got["/s/2"] == ("d", None)
    assert got["/s/3"] == ("e", now.timestamp())  # no readable end: kept a full keep from now
    assert got["/s/4"] == ("f", datetime(2026, 11, 1, tzinfo=UTC).timestamp())  # `since` once exited
    assert "/s/5" not in got


@pytest.mark.integration
async def test_an_adapter_that_names_no_transcript_roots_stops_the_scratch_rule(agent, monkeypatch):
    from sessionorc import adapters

    await park_ticks(agent)
    d = made(hosts.DEFAULT_SCRATCH_ROOT, str(paths.home()), "ao-o-1")
    age(d, 48 * HOUR)
    monkeypatch.setattr(adapters, "transcript_roots", lambda: ([], ["broken"]))
    agent._prune_runs(datetime.now(UTC), set(), set(), None, {})
    assert d.exists()
    monkeypatch.setattr(adapters, "transcript_roots", lambda: ([], []))
    agent._prune_runs(datetime.now(UTC), set(), set(), None, {})
    assert not d.exists()
