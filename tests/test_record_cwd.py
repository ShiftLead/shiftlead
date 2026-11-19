"""The record's `cwd` and `cwd_root`, and the status read's `git.top` and `git.worktree` (design §4.2 *The record's
`cwd`*, §4.3; TD-1988 slice 1): written from the main thread's live hook events, cleared at `dir`, and the root
written by the status read only where `cwd` held still while it ran."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sessionorc import gitinfo, models
from sessionorc.models import Session
from shiftlead.adapters.claude_code import hook as cc_hook
from shiftlead.adapters.gemini import hook as gemini_hook


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "first")
    return r


def test_cwd_and_cwd_root_are_the_hosts_alone():
    for f in ("cwd", "cwd_root"):
        assert f in models.NODE_OWNED and f not in models.HOME_OWNED and f not in models.IDENTITY


def test_both_adapters_put_the_payloads_cwd_on_every_event_they_translate():
    base = {"session_id": "a", "cwd": "/w/x"}
    assert cc_hook.translate({**base, "hook_event_name": "UserPromptSubmit", "prompt": "hi"})["cwd"] == "/w/x"
    assert cc_hook.translate({**base, "hook_event_name": "Stop"})["cwd"] == "/w/x"
    assert gemini_hook.translate({**base, "hook_event_name": "SessionStart"})["cwd"] == "/w/x"
    assert "cwd" not in (cc_hook.translate({"session_id": "a", "hook_event_name": "Stop"}) or {})


def _record(agent, d: Path, sid: str = "ao-cwd-1") -> Session:
    s = Session(id=sid, name="w", kind="interactive", adapter="claude-code", dir=str(d), state="working")
    agent.sessions[sid] = s
    return s


async def test_a_main_thread_event_sets_cwd_as_its_real_path_and_one_at_dir_clears_it(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    d, other = tmp_path / "d", tmp_path / "other"
    d.mkdir()
    other.mkdir()
    (tmp_path / "link").symlink_to(other)
    s = _record(agent, d)
    agent._git_checked[s.id] = datetime.now(UTC)
    s.cwd_root = "/old/root"
    await agent.rpc_hook(s.id, cwd=str(tmp_path / "link"))
    assert s.cwd == str(other.resolve()) and s.cwd_root is None  # its root cleared until the next status read
    assert s.id not in agent._git_checked  # and the read made due
    await agent.rpc_hook(s.id, cwd=str(other), subagent="sub-1")  # a subagent's: written by none
    await agent.rpc_hook(s.id, cwd=str(d), subagent="sub-1")
    assert s.cwd == str(other.resolve())
    agent._apply_event(s.id, {"cwd": str(d), "cwd_real": None}, queued=True)  # a queued one writes none
    assert s.cwd == str(other.resolve())
    await agent.rpc_hook(s.id, cwd=str(d))  # back at `dir`: absent
    assert s.cwd is None
    await agent.rpc_hook(s.id, cwd_real="/forged")  # the resolved value is the host agent's own word
    assert s.cwd is None


async def test_a_launch_drops_the_last_raw_cwd_and_a_forget_scrubs_it(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    s = _record(agent, tmp_path)
    await agent.rpc_hook(s.id, cwd="/")
    assert agent._cwd_raw[s.id] == "/" and s.cwd == "/"
    agent._scrub(s.id)
    assert s.id not in agent._cwd_raw


def test_git_top_and_worktree_name_a_linked_worktree_and_not_a_main_checkout(repo, tmp_path):
    wt = tmp_path / "wt" / "td-1153"
    _git(repo, "worktree", "add", "-q", "-b", "td-1953-tools", str(wt))
    main = gitinfo.git_info(repo).to_dict()
    assert main["top"] == str(repo.resolve()) and "worktree" not in main
    linked = gitinfo.git_info(wt).to_dict()
    assert linked["top"] == str(wt.resolve()) and linked["worktree"] == "td-1153"
    (repo / "sub").mkdir()
    assert gitinfo.git_info(repo / "sub").to_dict()["top"] == str(repo.resolve())


def test_a_submodule_is_not_a_linked_worktree(repo, tmp_path):
    inner = tmp_path / "inner"
    inner.mkdir()
    _git(inner, "init", "-q", "-b", "main")
    _git(inner, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x")
    _git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(inner), "mod")
    assert "worktree" not in gitinfo.git_info(repo / "mod").to_dict()


def test_cwd_root_names_another_worktree_none_in_its_own_and_cwd_outside_any_repo(repo, tmp_path):
    wt = tmp_path / "wt" / "b"
    _git(repo, "worktree", "add", "-q", "-b", "b", str(wt))
    (wt / "src").mkdir()
    assert gitinfo.cwd_root(repo, str(wt / "src")) == str(wt.resolve())  # another worktree: its top level
    (repo / "docs").mkdir()
    assert gitinfo.cwd_root(repo, str(repo / "docs")) is None  # a subdirectory of its own: none
    bare = tmp_path / "plain"
    bare.mkdir()
    assert gitinfo.cwd_root(repo, str(bare)) == str(bare.resolve())  # in no repository: `cwd` itself
    assert gitinfo.cwd_root(repo, str(tmp_path / "gone")) is None  # a deleted folder: none
    # `dir` in no repository: `cwd`'s top level where it has one, else `cwd` outside `dir`, none inside it
    (bare / "in").mkdir()
    assert gitinfo.cwd_root(bare, str(wt)) == str(wt.resolve())
    assert gitinfo.cwd_root(bare, str(bare / "in")) is None
    assert gitinfo.cwd_root(bare / "in", str(bare)) == str(bare.resolve())


async def test_the_status_read_writes_cwd_root_and_none_where_cwd_moved_while_it_ran(
    agent, repo, tmp_path, monkeypatch
):
    from conftest import park_ticks

    await park_ticks(agent)
    wt = tmp_path / "wt" / "b"
    _git(repo, "worktree", "add", "-q", "-b", "b", str(wt))
    s = _record(agent, repo)
    s.cwd = str(wt.resolve())
    await agent._refresh_git(datetime.now(UTC))
    assert s.cwd_root == str(wt.resolve()) and s.git["top"] == str(repo.resolve())
    assert s.id in agent._git_checked
    real = gitinfo.cwd_root

    def moved(directory, cwd, timeout=5.0):  # a hook event lands mid-read
        s.cwd = "/elsewhere"
        return real(directory, cwd, timeout)

    monkeypatch.setattr(gitinfo, "cwd_root", moved)
    agent._git_checked.pop(s.id)
    s.cwd_root = None
    await agent._refresh_git(datetime.now(UTC))
    assert s.cwd_root is None and s.id not in agent._git_checked  # nothing written, the record still due
    assert s.git is not None  # its `git` written as ever


def test_a_nodes_clearing_of_cwd_reaches_the_homes_copy_through_the_overlay():
    home = Session(id="ao-n-1", name="w", kind="interactive", adapter="claude-code", dir="/w", host="laptop",
                   cwd="/w2", cwd_root="/w2")  # fmt: skip
    report = {**home.to_dict(), "cwd": None, "cwd_root": None}
    models.apply_node(home, report)
    assert home.cwd is None and home.cwd_root is None
    models.apply_home(home, {**home.to_dict(), "cwd": "/home-says"})  # the home's copy never writes them
    assert home.cwd is None
