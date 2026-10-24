"""A close reaps the worktree its start made (design §4.1 *A close reaps the worktree it made*, TD-979): the
host agent's half — which closes reap, *idle* over the records, the locks, the stamp's recovery, the Cancel."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import park_ticks

from sessionorc import adapters
from sessionorc.agent_common import RpcError
from sessionorc.client import LocalClient

pytestmark = pytest.mark.usefixtures("hookstub")


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    """A main checkout cloned from a bare origin, `origin/HEAD` set, its caches ignored."""
    origin, r = tmp_path / "origin.git", tmp_path / "r"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(r))
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    (r / ".gitignore").write_text(".claude/\n__pycache__/\n")
    git(r, "add", ".gitignore")
    git(r, "commit", "-q", "-m", "one")
    git(r, "push", "-q", "-u", "origin", "main")
    git(r, "remote", "set-head", "origin", "-a")
    return r


def branches(r) -> set[str]:
    return set(git(r, "for-each-ref", "--format=%(refname:short)", "refs/heads").split())


AGENT = {"adapter": "hookstub"}
SHELL = {"adapter": "shell", "argv": ["bash", "--norc"]}


async def test_a_close_reaps_the_clean_worktree_it_made_and_its_launch_branch(agent, repo):
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        assert s["worktree_made"] is True
        got = await c.call("close", id=s["id"])
    assert not Path(s["dir"]).exists() and got["worktree_reaped_at"] and got["worktree_kept"] is None
    assert got["branches_deleted"] == ["w"] and got["branch_kept"] == {} and got["worktree_reaping"] is None
    assert "w" not in branches(repo) and git(repo, "ls-remote", "origin", "w") == ""  # origin untouched


async def test_an_unpushed_commit_keeps_the_branch_never_the_worktree(agent, repo):
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        (Path(s["dir"]) / "f").write_text("x")
        git(s["dir"], "add", "f")
        git(s["dir"], "commit", "-q", "-m", "mine")
        got = await c.call("close", id=s["id"])
    assert not Path(s["dir"]).exists() and got["branch_kept"] == {"w": "1 commit never on origin"}
    assert "w" in branches(repo)


async def test_a_restarts_close_keeps_the_worktree_and_says_nothing(agent, repo):
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        got = await c.call("close", id=s["id"], reap=False)
    assert Path(s["dir"]).is_dir() and got["worktree_kept"] is None and got["worktree_reaped_at"] is None


async def test_a_dirty_tree_and_a_found_worktree_are_kept_with_their_whys(agent, repo):
    found = repo / ".claude" / "worktrees" / "found"
    git(repo, "worktree", "add", "-q", "-b", "found", str(found))
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        (Path(s["dir"]) / "scratch").write_text("x")
        assert (await c.call("close", id=s["id"]))["worktree_kept"] == "1 uncommitted"
        f = await c.call("create", name="f", dir=str(repo), worktree="found", **AGENT)
        assert (await c.call("close", id=f["id"]))["worktree_kept"] == "not made here"
        plain = await c.call("create", name="p", dir=str(repo.parent), **AGENT)
        assert (await c.call("close", id=plain["id"]))["worktree_kept"] is None  # no worktree, nothing said
    assert Path(s["dir"]).is_dir() and found.is_dir()


async def test_a_live_shell_inside_keeps_it_an_exited_one_does_not(agent, repo):
    await park_ticks(agent)
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        sh = await c.call("create", name="sh", dir=str(Path(s["dir"])), **SHELL)
        assert (await c.call("close", id=s["id"]))["worktree_kept"] == f"in use by {sh['id']}"
        agent.sessions[sh["id"]].set_state("exited", confidence="tick")
        again = await c.call("close", id=s["id"])  # `ao close` on the closed record: the reap again
    assert again["worktree_reaped_at"] and not Path(s["dir"]).exists()


async def test_a_blind_external_adapter_keeps_it(agent, repo, monkeypatch):
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        monkeypatch.setattr(adapters, "external_sessions", lambda: {"items": [], "blind": ["claude-code"]})
        got = await c.call("close", id=s["id"])
    assert got["worktree_kept"] == "claude-code sessions could not be read" and Path(s["dir"]).is_dir()


def test_a_broken_registry_is_named_blind(monkeypatch):
    class Broken:
        name = "broken"

        def external_sessions(self):
            raise OSError("unreadable")

    adapters.load_all()
    monkeypatch.setitem(adapters._REGISTRY, "broken", Broken())
    assert "broken" in adapters.external_sessions()["blind"]


async def test_a_session_callers_string_reap_is_refused(agent, repo):
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
    with pytest.raises(RpcError, match="the home's word"):
        await agent.rpc_close(s["id"], caller="ao-someone", reap="in use by x")
    got = await agent.rpc_close(s["id"], reap="in use by ao-x-sh@box")  # the home's, with no session caller
    assert got["worktree_kept"] == "in use by ao-x-sh@box" and Path(s["dir"]).is_dir()


async def test_a_lock_still_held_at_the_deadline_keeps_as_busy(agent, repo, monkeypatch):
    monkeypatch.setattr("sessionorc.agent.REAP_WITHIN", 0.5)
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        lock = agent._dir_locks[str(Path(s["dir"]))]
        await lock.acquire()
        try:
            got = await c.call("close", id=s["id"])
        finally:
            lock.release()
    assert got["worktree_kept"] == "busy: a start is using it" and Path(s["dir"]).is_dir()
    assert not any(lk.locked() for lk in agent._dir_locks.values())  # the reap let go of what it took


async def test_a_cancelled_close_holds_both_locks_until_the_thread_returns(agent, repo, monkeypatch):
    import threading

    from sessionorc import gitinfo

    gate, entered = threading.Event(), threading.Event()
    real = gitinfo.reap_worktree

    def slow(*a, **kw):
        entered.set()
        gate.wait(10)
        return real(*a, **kw)

    monkeypatch.setattr("sessionorc.agent.reap_worktree", slow)
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
    close = asyncio.create_task(agent.rpc_close(s["id"]))
    assert await asyncio.to_thread(entered.wait, 10)
    close.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close
    held = [k for k, lk in agent._dir_locks.items() if lk.locked()]
    assert str(Path(s["dir"])) in held and any(k.startswith("worktree:") and k.endswith(":w") for k in held)
    gate.set()
    for _ in range(200):
        if not any(lk.locked() for lk in agent._dir_locks.values()):
            break
        await asyncio.sleep(0.05)
    assert not any(lk.locked() for lk in agent._dir_locks.values()) and not Path(s["dir"]).exists()


async def test_a_reap_cut_off_is_recovered_at_the_next_start(agent, repo):
    async with LocalClient() as c:
        a = await c.call("create", name="a", dir=str(repo), worktree="a", **AGENT)
        b = await c.call("create", name="b", dir=str(repo), worktree="b", **AGENT)
        for x in (a, b):
            await c.call("close", id=x["id"], reap=False)
    ra, rb = agent.sessions[a["id"]], agent.sessions[b["id"]]
    ra.worktree_reaping = {"at": "t", "branch": "a"}  # cut off after `--dehydrate`: the tree is still there
    git(repo, "worktree", "remove", rb.dir)  # cut off after the remove
    rb.worktree_reaping = {"at": "t", "branch": "b"}
    agent._recover_reaps()
    assert ra.worktree_kept == "interrupted" and ra.worktree_reaping is None and Path(ra.dir).is_dir()
    assert rb.worktree_reaped_at and rb.branches_deleted == ["b"] and rb.worktree_reaping is None
    assert "b" not in branches(repo) and "a" in branches(repo)


async def test_a_cancel_reaps_what_its_scheduling_made_and_says_a_kept_one(agent, repo):
    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", start_at=later, unattended=True, **AGENT)
        assert s["state"] == "scheduled" and s["worktree_made"] is True
        got = await c.call("close", id=s["id"])
        assert got["cancelled"] is True and got["worktree_reaped_at"] and not Path(s["dir"]).exists()
        k = await c.call("create", name="k", dir=str(repo), worktree="k", start_at=later, unattended=True, **AGENT)
        (Path(k["dir"]) / "scratch").write_text("x")
        kept = await c.call("close", id=k["id"])
    assert kept["cancelled"] is True and kept["worktree_kept"] == "1 uncommitted" and Path(k["dir"]).is_dir()


async def test_a_create_waits_for_a_reap_of_the_same_name(agent, repo, monkeypatch):
    """The reap holds the per-name worktree lock, so a create of the same name made while it runs waits, and
    then makes the worktree again rather than starting in a tree being removed."""
    import threading

    from sessionorc import gitinfo

    gate, entered = threading.Event(), threading.Event()
    real = gitinfo.reap_worktree

    def slow(*a, **kw):
        entered.set()
        gate.wait(10)
        return real(*a, **kw)

    monkeypatch.setattr("sessionorc.agent.reap_worktree", slow)
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
    close = asyncio.create_task(agent.rpc_close(s["id"]))
    assert await asyncio.to_thread(entered.wait, 10)
    create = asyncio.create_task(agent.rpc_create(name="w", dir=str(repo), worktree="w", **AGENT))
    await asyncio.sleep(0.3)
    assert not create.done()  # waiting on the worktree's lock
    gate.set()
    await close
    new = await create
    assert Path(new["dir"]).is_dir() and new["worktree_made"] is True


async def test_an_agentless_record_reaps_nothing(agent, repo):
    async with LocalClient() as c:
        sh = await c.call("create", name="sh", dir=str(repo), worktree="sh", **SHELL)
        got = await c.call("close", id=sh["id"])
    assert Path(sh["dir"]).is_dir() and got["worktree_kept"] is None and got["worktree_reaped_at"] is None


def test_the_tick_restarts_close_with_reap_false():
    """The lost-brief, wanted, brief and cache restarts keep the worktree (§6 rules 1, 2 and 7)."""
    src = (Path(__file__).resolve().parent.parent / "src" / "sessionorc" / "agent_tick.py").read_text()
    for why in ('"lost-brief"', '"wanted"'):
        i = src.index(f'closer = {{"by": "tick", "why": {why}}}')
        near = src[i : i + 400]
        assert near.count("reap=False") == 1 and near.count('"reap": False') == 1
    assert 'closer={"by": "tick", "why": why}, reap=False' in src
    assert 'closer={"by": "tick", "why": "cache"}, reap=False' in src


async def test_a_node_close_carries_reap_over_the_link_a_missing_one_reaping(agent, repo):
    """The node's `act` hands `reap` to its own `rpc_close`: a restart's `False` keeps, and a close from an
    older home, which sends none, reaps."""
    async with LocalClient() as c:
        a = await c.call("create", name="a", dir=str(repo), worktree="a", **AGENT)
        b = await c.call("create", name="b", dir=str(repo), worktree="b", **AGENT)
    await agent._act({"rpc": "close", "params": {"id": a["id"], "reap": False}, "caller": None})
    await agent._act({"rpc": "close", "params": {"id": b["id"]}, "caller": None})
    assert Path(a["dir"]).is_dir() and agent.sessions[a["id"]].worktree_reaped_at is None
    assert not Path(b["dir"]).exists() and agent.sessions[b["id"]].worktree_reaped_at


async def test_the_home_names_its_own_record_inside_a_sharing_hosts_worktree(agent, repo):
    await park_ticks(agent)
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        sh = await c.call("create", name="sh", dir=s["dir"], **SHELL)
    assert agent._shared_inside("box", s["id"], s["dir"]) == f"{sh['id']}@{agent.host}"
    assert agent._shared_inside("box", "ao-x-w", str(repo.parent / "elsewhere")) is None


async def test_a_sharing_node_whose_link_is_down_is_unreachable(agent, repo, monkeypatch):
    from sessionorc import containers

    monkeypatch.setattr(containers, "container_nodes", lambda: {"box": object(), "other": object()})
    agent.links.pop("other", None)
    assert agent._shared_inside("box", "ao-x-w", str(repo)) == "other unreachable"


async def test_a_string_reap_on_a_record_with_no_worktree_says_nothing(agent, repo):
    async with LocalClient() as c:
        s = await c.call("create", name="p", dir=str(repo.parent), **AGENT)
    got = await agent.rpc_close(s["id"], reap="in use by ao-x@box")
    assert got["worktree_kept"] is None


async def test_a_routed_close_takes_the_homes_why_whatever_session_closed(agent, repo):
    """A manager's close of a container node's member: the home sends its why as `reap` and the session as the
    caller; the node closes it and writes the why, never refusing the close (§4.1, #2312's review)."""
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
    got = await agent._act(
        {"rpc": "close", "params": {"id": s["id"], "reap": "in use by ao-x-sh@kmaster"}, "caller": "ao-mgr"}
    )
    rec = agent.sessions[s["id"]]
    assert rec.state == "closed" and rec.worktree_kept == "in use by ao-x-sh@kmaster" and Path(s["dir"]).is_dir()
    assert got["result"]["closer"]["by"] == "ao-mgr"


# -- `ao close` on a closed record (§4.1 *the record*): the reap again, or the branches weighed again ----------


async def test_a_retry_reaps_a_kept_record_and_its_close_stamps_stand(agent, repo):
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        (Path(s["dir"]) / "scratch").write_text("x")
        first = await c.call("close", id=s["id"])
        assert first["worktree_kept"] == "1 uncommitted"
        (Path(s["dir"]) / "scratch").unlink()
        assert (await c.call("close", id=s["id"], reap=False)) == first  # a restart's: nothing touched
        again = await c.call("close", id=s["id"])
    assert again["worktree_reaped_at"] and again["worktree_kept"] is None and not Path(s["dir"]).exists()
    assert (again["closed_at"], again["closer"]) == (first["closed_at"], first["closer"])


async def test_a_retry_weighs_the_kept_branches_again(agent, repo):
    """*no origin/HEAD* cured by `set-head`: the launch branch, with nothing of its own, goes to
    `branches_deleted`; the checked-out branch keeps with its fresh why, then goes once pushed."""
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        git(repo, "remote", "set-head", "origin", "-d")
        git(s["dir"], "checkout", "-q", "-b", "x")
        (Path(s["dir"]) / "f").write_text("x")
        git(s["dir"], "add", "f")
        git(s["dir"], "commit", "-q", "-m", "mine")
        first = await c.call("close", id=s["id"])
        assert first["branch_kept"] == {"x": "no origin/HEAD", "w": "no origin/HEAD"} and first["worktree_reaped_at"]
        git(repo, "remote", "set-head", "origin", "-a")
        again = await c.call("close", id=s["id"])
        assert again["branches_deleted"] == ["w"] and again["branch_kept"] == {"x": "1 commit never on origin"}
        assert again["worktree_reaped_at"] == first["worktree_reaped_at"]
        git(repo, "push", "-q", "origin", "x")
        last = await c.call("close", id=s["id"])
    assert last["branches_deleted"] == ["w", "x"] and last["branch_kept"] == {} and not {"w", "x"} & branches(repo)


async def test_a_retry_after_the_directory_was_removed_by_hand(agent, repo):
    """No `worktree_reaped_at`: the stale registration names the checked-out branch, `prune` frees it and the
    path, both branches are weighed, and a later start of the name makes the worktree again."""
    import shutil

    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        git(s["dir"], "checkout", "-q", "-b", "x")
        (Path(s["dir"]) / "scratch").write_text("x")
        assert (await c.call("close", id=s["id"]))["worktree_kept"] == "1 uncommitted"
        shutil.rmtree(s["dir"])
        await agent._clear_gone_kept()  # the tick's check: the directory is gone, so it no longer says kept
        assert agent.sessions[s["id"]].worktree_kept is None
        got = await c.call("close", id=s["id"])
        assert got["worktree_reaped_at"] and sorted(got["branches_deleted"]) == ["w", "x"] and got["branch_kept"] == {}
        assert str(Path(s["dir"])) not in git(repo, "worktree", "list", "--porcelain")
        new = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
    assert new["dir"] == s["dir"] and Path(new["dir"]).is_dir() and new["worktree_made"] is True


async def test_a_retry_racing_a_create_of_the_name_answers_busy(agent, repo, monkeypatch):
    import shutil

    monkeypatch.setattr("sessionorc.agent.REAP_WITHIN", 0.5)
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        git(repo, "remote", "set-head", "origin", "-d")
        assert (await c.call("close", id=s["id"]))["branch_kept"] == {"w": "no origin/HEAD"}
        shutil.rmtree(s["dir"], ignore_errors=True)
        held = [lk for k, lk in agent._dir_locks.items() if k.startswith("worktree:") and k.endswith(":w")]
        assert len(held) == 1
        await held[0].acquire()
        try:
            got = await c.call("close", id=s["id"])
        finally:
            held[0].release()
    assert got["worktree_kept"] == "busy: a start is using it" and got["branch_kept"] == {"w": "no origin/HEAD"}


async def test_a_retry_with_nothing_kept_and_a_record_not_made_here_write_nothing(agent, repo):
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        first = await c.call("close", id=s["id"])
        assert first["worktree_reaped_at"] and first["branch_kept"] == {}
        assert (await c.call("close", id=s["id"])) == first
    rec = agent.sessions[s["id"]]
    rec.worktree_made, rec.worktree_reaped_at, rec.branch_kept = False, None, {"w": "no origin"}
    assert (await agent.rpc_close(s["id"]))["branch_kept"] == {"w": "no origin"}  # not this start's to weigh


async def test_the_ticks_check_passes_over_a_reap_still_running_and_a_tree_still_there(agent, repo):
    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        (Path(s["dir"]) / "scratch").write_text("x")
        await c.call("close", id=s["id"])
    rec = agent.sessions[s["id"]]
    await agent._clear_gone_kept()
    assert rec.worktree_kept == "1 uncommitted"  # still there
    rec.dir = str(repo / "gone")
    rec.worktree_reaping = {"at": "t", "branch": "w"}
    await agent._clear_gone_kept()
    assert rec.worktree_kept == "1 uncommitted"  # the reap's own to write


async def test_a_retry_over_a_detached_stale_entry_weighs_the_launch_branch_alone(agent, repo):
    import shutil

    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        git(repo, "branch", "-q", "y")  # a branch the detached tree never names
        git(s["dir"], "checkout", "-q", "--detach")
        (Path(s["dir"]) / "scratch").write_text("x")
        assert (await c.call("close", id=s["id"]))["worktree_kept"] == "1 uncommitted"
        shutil.rmtree(s["dir"])
        got = await c.call("close", id=s["id"])
    assert got["branches_deleted"] == ["w"] and got["branch_kept"] == {} and "y" in branches(repo)


async def test_a_registration_not_read_stamps_nothing_and_a_retry_never_raises(agent, repo, monkeypatch):
    import shutil

    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        (Path(s["dir"]) / "scratch").write_text("x")
        await c.call("close", id=s["id"])
        shutil.rmtree(s["dir"])
        monkeypatch.setattr("sessionorc.agent.reweigh_gone", lambda *a: None)
        assert (await c.call("close", id=s["id"]))["worktree_reaped_at"] is None

        def broken(*a):
            raise RuntimeError("boom")

        monkeypatch.setattr("sessionorc.agent.reweigh_gone", broken)
        got = await c.call("close", id=s["id"])
    assert got["state"] == "closed" and got["worktree_reaped_at"] is None
    assert not any(lk.locked() for lk in agent._dir_locks.values())


async def test_a_cancelled_retry_holds_the_lock_until_the_thread_returns(agent, repo, monkeypatch):
    import shutil
    import threading

    from sessionorc import gitinfo

    gate, entered = threading.Event(), threading.Event()
    real = gitinfo.reweigh_gone

    def slow(*a):
        entered.set()
        gate.wait(10)
        return real(*a)

    async with LocalClient() as c:
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        (Path(s["dir"]) / "scratch").write_text("x")
        await c.call("close", id=s["id"])
    shutil.rmtree(s["dir"])
    monkeypatch.setattr("sessionorc.agent.reweigh_gone", slow)
    retry = asyncio.create_task(agent.rpc_close(s["id"]))
    assert await asyncio.to_thread(entered.wait, 10)
    retry.cancel()
    with pytest.raises(asyncio.CancelledError):
        await retry
    assert any(k.startswith("worktree:") and lk.locked() for k, lk in agent._dir_locks.items())
    gate.set()
    for _ in range(200):
        if not any(lk.locked() for lk in agent._dir_locks.values()):
            break
        await asyncio.sleep(0.05)
    rec = agent.sessions[s["id"]]
    assert not any(lk.locked() for lk in agent._dir_locks.values()) and rec.worktree_reaped_at
    assert rec.branches_deleted == ["w"]  # written by the shielded task, though its close was cancelled


async def test_a_retry_passes_over_a_record_not_made_here_and_a_reap_still_stamped(agent, repo):
    found = repo / ".claude" / "worktrees" / "found"
    git(repo, "worktree", "add", "-q", "-b", "found", str(found))
    async with LocalClient() as c:
        f = await c.call("create", name="f", dir=str(repo), worktree="found", **AGENT)
        first = await c.call("close", id=f["id"])
        assert first["worktree_kept"] == "not made here"
        assert (await c.call("close", id=f["id"])) == first
        s = await c.call("create", name="w", dir=str(repo), worktree="w", **AGENT)
        await c.call("close", id=s["id"], reap=False)
        agent.sessions[s["id"]].worktree_reaping = {"at": "t", "branch": "w"}
        got = await c.call("close", id=s["id"])
    assert got["worktree_reaped_at"] is None and Path(s["dir"]).is_dir()  # the start's recovery's to finish
