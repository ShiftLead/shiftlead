"""The disk sweep's worktree rule (design §4.6 *The disk sweep*, *worktrees*, TD-1945): on scratch repos cloned from
a bare origin, the pass removes a landed, clean, idle, unlocked worktree past its keep and keeps every other, each
with its why; it deletes no branch; and the pinned `reap_worktrees.sh` reads the same worktrees the same way."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from sessionorc import gitinfo, worktreesweep

DAY = 86400


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(cwd, name="f", text="x", msg="c") -> str:
    (Path(cwd) / name).write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", msg)
    return git(cwd, "rev-parse", "HEAD")


def age(wt: Path, days: float = 10) -> None:
    """Every write the rule reads — `HEAD`, the index, each tracked file — put `days` back."""
    t = time.time() - days * DAY
    names = [git(wt, "rev-parse", "--path-format=absolute", "--git-path", n) for n in ("HEAD", "index")]
    names += [str(wt / f) for f in git(wt, "ls-files").splitlines()]
    for n in names:
        if os.path.exists(n):
            os.utime(n, (t, t))


@pytest.fixture
def repo(tmp_path) -> Path:
    """A main checkout cloned from a bare origin with one commit on `main` and `origin/HEAD` set."""
    seed, origin, r = tmp_path / "seed", tmp_path / "origin.git", tmp_path / "r"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(seed))
    git(seed, "config", "user.email", "t@t")
    git(seed, "config", "user.name", "t")
    (seed / ".gitignore").write_text(".claude/\nwt/\n")
    git(seed, "add", ".gitignore")
    commit(seed, msg="one")
    git(seed, "push", "-q", str(origin), "main")
    git(tmp_path, "clone", "-q", str(origin), str(r))
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    return r


def wt_of(repo: Path, name: str, root: str = ".claude/worktrees") -> Path:
    wt = repo / root / name
    git(repo, "worktree", "add", "-q", "-b", name, str(wt), "origin/main")
    return wt


def squash_merge(repo: Path, wt: Path, name: str, *, push_branch: bool = True, drop_remote: bool = True) -> None:
    """`name`'s work squash-merged into origin's main from the main checkout, its remote branch deleted."""
    if push_branch:
        git(wt, "push", "-q", "-u", "origin", name)
    git(repo, "fetch", "-q", "origin")
    git(repo, "merge", "-q", "--squash", name)
    git(repo, "commit", "-q", "-m", f"{name} (#1)")
    git(repo, "push", "-q", "origin", "main")
    if push_branch and drop_remote:
        git(repo, "push", "-q", "origin", "--delete", name)
    git(repo, "fetch", "-q", "--prune", "origin")


def run(repo, **kw):
    kw.setdefault("cursor", "")
    kw.setdefault("keep_days", 7)
    return worktreesweep.sweep([repo], **kw)


def test_a_landed_clean_old_worktree_goes_and_its_branch_stays_while_the_rest_are_kept_with_why(repo):
    landed = wt_of(repo, "landed")
    commit(landed, "a", msg="landed work")
    squash_merge(repo, landed, "landed")  # its remote branch gone: commits on no remote, yet landed
    unpushed = wt_of(repo, "unpushed")
    commit(unpushed, "b", msg="only here")
    untracked = wt_of(repo, "untracked")
    commit(untracked, "c", msg="landed too")
    squash_merge(repo, untracked, "untracked")
    (untracked / "notes.txt").write_text("scratch")
    young = wt_of(repo, "young")
    commit(young, "d", msg="young")
    squash_merge(repo, young, "young")
    detached = repo / ".claude/worktrees/detached"
    git(repo, "worktree", "add", "-q", "--detach", str(detached), "origin/main")
    locked = wt_of(repo, "locked")
    commit(locked, "e", msg="locked")
    squash_merge(repo, locked, "locked")
    git(repo, "worktree", "lock", str(locked))
    for w in (landed, unpushed, untracked, detached, locked):
        age(w)
    got = run(repo)
    assert got.removed == [str(detached), str(landed)] and not landed.exists() and not detached.exists()
    kept = dict(got.kept)
    assert kept[str(unpushed)] == "1 commit only on this machine"
    assert kept[str(untracked)].endswith("uncommitted")
    assert kept[str(young)] == "written within 7 days"
    assert kept[str(locked)] == "locked"
    assert str(repo) not in kept  # the main checkout is never weighed
    assert "landed" in git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").split()  # no branch deleted


def test_a_branch_landed_before_main_edited_its_files_reads_since_and_one_main_reverted_is_kept(repo, tmp_path):
    since = wt_of(repo, "since")
    commit(since, "s", text="one", msg="s")
    squash_merge(repo, since, "since")
    git(repo, "checkout", "-q", "main")
    git(repo, "pull", "-q", "--ff-only")
    commit(repo, "s", text="main edits it since", msg="main edits s")
    git(repo, "push", "-q", "origin", "main")
    reverted = wt_of(repo, "reverted")
    commit(reverted, "v", text="v", msg="v")
    squash_merge(repo, reverted, "reverted", drop_remote=False)  # its commits on origin: why is the landing
    git(repo, "pull", "-q", "--ff-only")
    git(repo, "rm", "-q", "v")
    git(repo, "commit", "-q", "-m", "revert v")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    for w in (since, reverted):
        age(w)
    assert gitinfo.landed_of(since, "since", root=repo) == "since"
    got = run(repo)
    assert got.removed == [str(since)]
    assert dict(got.kept)[str(reverted)] == "not landed" and reverted.exists()


def test_an_unparsable_pin_and_a_missing_default_ref_keep_as_not_landed(repo):
    w = wt_of(repo, "w")
    commit(w, "a", msg="a")
    squash_merge(repo, w, "w", drop_remote=False)
    age(w)
    (repo / "docs").mkdir()
    (repo / "docs/cadence.toml").write_text("this is [not toml")
    assert dict(run(repo).kept)[str(w)] == "not landed (unreadable)"
    (repo / "docs/cadence.toml").unlink()
    git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    assert dict(run(repo).kept)[str(w)].startswith("not landed")
    assert w.exists()


def test_a_repos_own_worktree_root_is_where_it_looks(repo):
    (repo / "docs").mkdir()
    (repo / "docs/cadence.toml").write_text('worktree-root = "wt"\n')
    there = wt_of(repo, "there", root="wt")
    elsewhere = wt_of(repo, "elsewhere")  # under .claude/worktrees, which this repo does not name
    for w, n in ((there, "there"), (elsewhere, "elsewhere")):
        commit(w, n, msg=n)
        squash_merge(repo, w, n)
        age(w)
    got = run(repo)
    assert got.removed == [str(there)] and elsewhere.exists() and not got.kept


def test_idle_busy_and_transcripts_keep(repo, tmp_path):
    names = ("busy", "inuse", "holds")
    wts = {}
    for n in names:
        wts[n] = wt_of(repo, n)
        commit(wts[n], n, msg=n)
        squash_merge(repo, wts[n], n)
        age(wts[n])
    store = wts["holds"] / ".claude" / "projects"  # a profile's config dir inside a removable worktree
    store.mkdir(parents=True)
    (store / "t.jsonl").write_text("{}\n")
    asked = []

    def hold(wt, main):
        asked.append(wt.name)
        return None if wt.name == "busy" else (lambda: None)

    got = run(
        repo,
        idle=lambda wt: "in use by ao-x" if wt.name == "inuse" else None,
        hold=hold,
        transcript_roots=[store],
    )
    kept = dict(got.kept)
    assert kept == {
        str(wts["busy"]): "busy: a start is using it",
        str(wts["inuse"]): "in use by ao-x",
        str(wts["holds"]): "transcripts",
    }
    assert asked == ["busy"] and (store / "t.jsonl").exists()


def test_successive_passes_weigh_each_worktree_in_turn_from_the_cursor(repo, monkeypatch):
    for n in ("a", "b", "c"):
        wt_of(repo, n)  # each kept: young
    clock = [0.0]
    monkeypatch.setattr(worktreesweep.time, "monotonic", lambda: clock[0])
    real = worktreesweep.weigh

    def weigh(*a, **kw):
        clock[0] += worktreesweep.SWEEP_WORKTREE_S  # each weigh spends a whole pass
        return real(*a, **kw)

    monkeypatch.setattr(worktreesweep, "weigh", weigh)
    cursor, seen = "", []
    for _ in range(4):
        got = run(repo, cursor=cursor)
        seen += [Path(p).name for p, _ in got.kept]
        cursor = got.cursor
    assert seen == ["a", "b", "c", "a"]  # a kept worktree never starves the next; past the end it wraps


def test_the_pinned_script_reads_the_same_worktrees_the_same_way_but_for_empty_and_detached(repo):
    """§4.6: the sweep holds `reap_worktrees.sh`'s five tests. Run without `--reap` over the same worktrees, the
    script's REAPABLE are what the sweep removes, but for an *empty* branch, which the sweep takes past its keep, and
    a landed *detached* worktree, which the script never reaps and the sweep weighs by its own tests (TD-2103)."""
    from conftest import pinned_script

    made = {}
    for n in ("landed", "since", "untracked", "locked", "unpushed", "reverted"):
        made[n] = wt_of(repo, n)
        commit(made[n], f"{n}.txt", text=n, msg=n)
    for n in ("landed", "since", "untracked", "locked"):
        squash_merge(repo, made[n], n)
    squash_merge(repo, made["reverted"], "reverted", drop_remote=False)
    git(repo, "pull", "-q", "--ff-only")
    commit(repo, "since.txt", text="main edits it since", msg="main edits since")
    git(repo, "rm", "-q", "reverted.txt")
    git(repo, "commit", "-q", "-m", "revert reverted")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    made["empty"] = wt_of(repo, "empty")
    made["detached"] = repo / ".claude/worktrees/detached"
    git(repo, "worktree", "add", "-q", "--detach", str(made["detached"]), "origin/main")
    (made["untracked"] / "notes.txt").write_text("scratch")
    git(repo, "worktree", "lock", str(made["locked"]))
    for w in made.values():
        age(w)
    cp = subprocess.run(["bash", str(pinned_script("reap_worktrees.sh"))], cwd=repo, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    rows = {ln.split()[0]: ln.split() for ln in cp.stdout.splitlines() if " landed=" in ln}
    assert set(rows) == set(made), cp.stdout
    script = {n for n, row in rows.items() if row[-1] == "REAPABLE"}
    assert script == {"landed", "since"}, cp.stdout
    assert rows["empty"][2] == "landed=empty" and rows["empty"][-1] == "keep"
    for w in made.values():
        age(w)  # the script's own `git status` refreshed each index, a write; the sweep's reads write none
    got = run(repo, idle=lambda wt: None)
    assert {Path(p).name for p in got.removed} == script | {"empty", "detached"}, got.kept
    assert {Path(p).name for p, _ in got.kept} == set(made) - script - {"empty", "detached"}


def test_the_tick_reads_every_registered_root_even_two_of_one_name():
    from sessionorc.agent_tick import sweep_roots

    repos = {"/a/shiftlead": {"name": "shiftlead"}, "/b/x": {"name": "shiftlead", "root": "/b/shiftlead"}, "k": None}
    assert sweep_roots(repos) == ["/a/shiftlead", "/b/shiftlead"]


@pytest.mark.integration
async def test_the_host_agent_keeps_a_live_records_worktree_and_one_a_create_holds(agent, repo):
    import asyncio
    from datetime import UTC, datetime

    from conftest import park_ticks

    from sessionorc.models import Session

    await park_ticks(agent)
    made = {}
    for n in ("gone", "live", "busy"):
        made[n] = wt_of(repo, n)
        commit(made[n], f"{n}.txt", msg=n)
        squash_merge(repo, made[n], n)
        age(made[n])
    agent.sessions["ao-live"] = Session(
        id="ao-live", name="live", kind="interactive", adapter="shell", dir=str(made["live"])
    )
    agent._worktree_scope, agent._sweep_roots = True, [str(repo)]
    agent._sweep_loop = asyncio.get_running_loop()
    lock = agent._dir_locks[str(made["busy"])]
    await lock.acquire()  # a create into it, before its record exists
    try:
        await asyncio.to_thread(agent._sweep_worktrees, datetime.now(UTC))
    finally:
        lock.release()
    assert not made["gone"].exists() and made["live"].exists() and made["busy"].exists()
    assert agent._worktree_cursor == str(made["live"])  # the last path weighed, in path order
    assert not agent._dir_locks[str(made["gone"])].locked()  # the create's locks the removal held are let go
    agent._worktree_scope = False  # a scratch home's own scope: weighs nothing
    del agent.sessions["ao-live"]
    await asyncio.to_thread(agent._sweep_worktrees, datetime.now(UTC))
    assert made["live"].exists()


def test_an_odd_worktree_root_reads_the_default(repo, tmp_path):
    (repo / "docs").mkdir()
    for value in (".", "./", "../elsewhere", "/abs"):
        (repo / "docs/cadence.toml").write_text(f"worktree-root = {value!r}\n")
        assert worktreesweep.worktree_root(repo) == repo / ".claude/worktrees", value
    (tmp_path / "out").mkdir()
    (repo / "link").symlink_to(tmp_path / "out")  # inside by name, outside in fact
    (repo / "docs/cadence.toml").write_text('worktree-root = "link"\n')
    assert worktreesweep.worktree_root(repo) == repo / ".claude/worktrees"


def test_one_worktree_that_cannot_be_weighed_never_starves_the_rest_and_two_roots_of_one_repo_weigh_it_once(
    repo, tmp_path
):
    for n in ("a", "b"):
        w = wt_of(repo, n)
        commit(w, f"{n}.txt", msg=n)
        squash_merge(repo, w, n)
        age(w)
    (tmp_path / "alias").symlink_to(repo)

    def idle(wt):
        if wt.name == "a":
            raise OSError("cannot read")
        return None

    got = worktreesweep.sweep([repo, tmp_path / "alias"], cursor="", keep_days=7, idle=idle)
    assert [Path(p).name for p in got.removed] == ["b"]
    assert [(Path(p).name, why) for p, why in got.kept] == [("a", gitinfo.NOT_WEIGHED)]
    assert got.cursor.endswith("/b")


@pytest.mark.integration
async def test_a_loop_too_slow_to_answer_keeps_the_worktree_and_holds_no_lock_late(agent, monkeypatch, tmp_path):
    import asyncio
    import threading

    from conftest import park_ticks

    await park_ticks(agent)
    monkeypatch.setattr(gitinfo, "REAP_STEP", 0.1)
    agent._sweep_loop = asyncio.get_running_loop()
    wt, got = tmp_path / "w", []
    t = threading.Thread(target=lambda: got.append(agent._hold_create_locks(wt, tmp_path)))
    t.start()
    time.sleep(0.5)  # the loop stalls past the sweep's wait
    t.join()
    for _ in range(3):
        await asyncio.sleep(0.05)  # the late take runs, then gives back what it took
    assert got == [None]
    assert not any(lock.locked() for lock in agent._dir_locks.values())


def landed_old(repo: Path, name: str) -> Path:
    """A worktree the rule would remove: its work squash-merged, clean, past its keep."""
    w = wt_of(repo, name)
    commit(w, f"{name}.txt", msg=name)
    squash_merge(repo, w, name)
    age(w)
    return w


def test_idle_is_asked_again_under_the_locks_just_before_the_removal(repo):
    """A session that starts in the worktree between its weigh and its removal keeps it: the second ask, under the
    create's locks, answers with the reason, and the locks are given back."""
    w = landed_old(repo, "late")
    asks, released = [], []

    def idle(wt):
        asks.append(wt.name)
        return None if len(asks) == 1 else "in use by ao-late"

    got = run(repo, idle=idle, hold=lambda wt, main: lambda: released.append(wt.name))
    assert got.removed == [] and dict(got.kept) == {str(w): "in use by ao-late"} and w.exists()
    assert asks == ["late", "late"] and released == ["late"]


def test_a_refused_removal_is_kept_with_the_refusal_and_never_reported_removed(repo, monkeypatch):
    w = landed_old(repo, "stuck")
    monkeypatch.setattr(worktreesweep, "remove", lambda wt, main, timeout=worktreesweep.STEP: False)
    got = run(repo)
    assert got.removed == [] and dict(got.kept) == {str(w): "git worktree remove refused"} and w.exists()


def test_a_worktree_path_that_is_a_symlink_is_kept_as_not_a_directory(repo):
    """git lists the worktree at its own path, which is now a link to the directory moved beside it, inside the root:
    the rule never weighs, nor removes, through a link."""
    w = landed_old(repo, "linked")
    moved = w.parent / "linked-moved"
    w.rename(moved)
    w.symlink_to(moved)
    got = run(repo)
    assert got.removed == [] and dict(got.kept) == {str(w): "not a directory"}
    assert w.is_symlink() and moved.is_dir()


def detached_at(repo: Path, name: str, ref: str = "origin/main") -> Path:
    w = repo / ".claude/worktrees" / name
    git(repo, "worktree", "add", "-q", "--detach", str(w), ref)
    git(w, "config", "user.email", "t@t")
    git(w, "config", "user.name", "t")
    return w


def test_a_detached_worktree_with_a_commit_not_on_origin_is_kept_and_counted(repo):
    w = detached_at(repo, "ahead")
    commit(w, "a", msg="one")
    commit(w, "b", msg="two")
    git(repo, "branch", "holds-it", git(w, "rev-parse", "HEAD"))  # a ref reaches them: the reflog test passes
    age(w)
    assert gitinfo.detached_landed(w, root=repo) == "no"
    got = run(repo)
    assert dict(got.kept) == {str(w): "detached: 2 commits not on origin/main"} and w.exists()


def test_a_detached_worktree_with_a_commit_only_in_its_reflog_is_kept(repo):
    w = detached_at(repo, "reflog")
    commit(w, "a", msg="made here")
    git(w, "checkout", "-q", "--detach", "origin/main")  # HEAD is landed; the commit survives only in the reflog
    age(w)
    assert dict(run(repo).kept) == {str(w): "detached: 1 commit only in its reflog"} and w.exists()


def test_a_detached_worktree_whose_reflog_cannot_be_read_is_kept(repo, monkeypatch):
    w = detached_at(repo, "noreflog")
    age(w)
    real = gitinfo._git

    def fails(directory, *args, **kw):
        return None if args[:2] == ("log", "-g") else real(directory, *args, **kw)

    monkeypatch.setattr(gitinfo, "_git", fails)
    assert dict(run(repo).kept) == {str(w): gitinfo.UNKNOWN} and w.exists()


@pytest.mark.parametrize("name", worktreesweep.OPERATIONS)
def test_a_detached_worktree_with_an_operation_in_progress_is_kept(repo, name):
    w = detached_at(repo, "op")
    marker = Path(git(w, "rev-parse", "--path-format=absolute", "--git-path", name))
    if name.startswith("rebase"):
        marker.mkdir()
    else:
        marker.write_text("")
    age(w)
    assert dict(run(repo).kept) == {str(w): "detached: operation in progress"} and w.exists()


def test_a_detached_worktree_whose_landing_cannot_be_read_is_kept(repo):
    w = detached_at(repo, "pin")
    age(w)
    (repo / "docs").mkdir()
    (repo / "docs/cadence.toml").write_text("this is [not toml")
    assert gitinfo.detached_landed(w, root=repo) == "unreadable"
    assert dict(run(repo).kept) == {str(w): "detached: not landed (unreadable)"} and w.exists()


def test_a_detached_worktree_with_changes_or_a_recent_write_is_kept(repo):
    dirty = detached_at(repo, "dirty")
    (dirty / "notes.txt").write_text("scratch")
    age(dirty)
    young = detached_at(repo, "young")
    kept = dict(run(repo).kept)
    assert kept[str(dirty)].endswith("uncommitted") and kept[str(young)] == "written within 7 days"


def test_a_recorded_home_keeps_a_detached_worktree_and_is_asked_before_the_age_and_again_before_removal(repo):
    home, late = detached_at(repo, "home"), detached_at(repo, "late")
    age(home)
    age(late)
    asks = []

    def record(wt):
        asks.append(wt.name)
        if wt.name == "home":
            return "record: ao-seat"
        return "record: ao-late" if asks.count("late") == 2 else None

    got = run(repo, record=record)
    assert dict(got.kept) == {str(home): "record: ao-seat", str(late): "record: ao-late"}
    assert home.exists() and late.exists() and asks.count("home") == 1 and asks.count("late") == 2


def test_a_branch_worktree_never_asks_the_recorded_home(repo):
    w = landed_old(repo, "branchy")
    got = run(repo, record=lambda wt: pytest.fail("a branch's worktree has no recorded-home test"))
    assert got.removed == [str(w)]


def test_a_head_that_moves_between_the_weigh_and_the_removal_keeps_the_worktree(repo):
    w = detached_at(repo, "moved")
    age(w)

    def hold(wt, main):
        commit(wt, "late", msg="made during the pass")
        return lambda: None

    assert dict(run(repo, hold=hold).kept) == {str(w): "detached: HEAD moved"} and w.exists()


def test_a_dry_run_names_a_detached_worktrees_why_and_reads_no_head(repo, monkeypatch):
    home, gone = detached_at(repo, "home"), detached_at(repo, "gone")
    age(home)
    age(gone)
    monkeypatch.setattr(worktreesweep, "_head", lambda *a: pytest.fail("a dry run reads HEAD neither time"))
    got = run(repo, dry=True, record=lambda wt: "record: ao-x" if wt.name == "home" else None)
    assert got.removed == [str(gone)] and dict(got.kept) == {str(home): "record: ao-x"}
    assert home.exists() and gone.exists()


@pytest.mark.integration
async def test_the_record_guard_reads_any_state_a_node_and_whole_path_components(agent, tmp_path, monkeypatch):
    from conftest import park_ticks

    from sessionorc import containers
    from sessionorc.models import Session

    await park_ticks(agent)
    wt = tmp_path / "grinder-ao-1"
    (wt / "sub").mkdir(parents=True)
    (tmp_path / "grinder-ao-10").mkdir()

    def rec(rid, d, state):
        s = Session(id=rid, name=rid, kind="interactive", adapter="shell", dir=d)
        s.state = state
        return s

    agent.sessions.clear()
    agent.sessions["ao-empty"] = rec("ao-empty", "", "exited")  # an empty dir is skipped, never resolved to the cwd
    monkeypatch.chdir(wt)
    agent.sessions["ao-sibling"] = rec("ao-sibling", str(tmp_path / "grinder-ao-10"), "idle")
    assert agent._record_home(wt) is None
    for state in ("exited", "closed", "idle"):
        agent.sessions["ao-seat"] = rec("ao-seat", str(wt / "sub"), state)
        assert agent._record_home(wt) == "record: ao-seat"
    del agent.sessions["ao-seat"]
    monkeypatch.setattr(agent, "mode", "home")
    monkeypatch.setattr(containers, "container_nodes", lambda: ["node1"])
    monkeypatch.setitem(agent.remote, "node1", {"ao-n": rec("ao-n", str(wt), "closed")})
    monkeypatch.setitem(agent.links, "node1", {"up": True})
    assert agent._record_home(wt) == "record: ao-n@node1"
    monkeypatch.setitem(agent.links, "node1", {"up": False})
    assert agent._record_home(wt) == "node1 unreachable"
