"""TD-1944, design §4.6 *A session's scratch*: every run of a record has one `0700` scratch directory,
`<scratch_root>/shiftlead-<uid>/<token>/`, holding `owner.json`, named in the record's `scratch` and in its env as
`SHIFTLEAD_SCRATCH`, `TMPDIR` and the adapter's `scratch_env`; a restart and a Resume keep it, a fresh start gets a
new one; the host agent refuses a `scratch_root` past 48 bytes and a `shiftlead-<uid>/` that is a symlink."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
from pathlib import Path

import pytest
from conftest import park_ticks, wait_for

from sessionorc import hosts, paths, scratch
from sessionorc.agent import HostAgent, RpcError
from sessionorc.client import LocalClient
from sessionorc.tmux import Tmux
from shiftlead.adapters import claude_code, gemini, grok
from shiftlead.ui import settings_page

CLEAN = {"branch": "w", "dirty": 0, "unpushed": 0, "upstream": "origin/w"}


@pytest.fixture
def short(_scratch_root):
    """A root of this test's own under the run's short one: `tmp_path` is past the 48 bytes a root may hold."""
    import tempfile

    with tempfile.TemporaryDirectory(dir=_scratch_root) as d:
        yield Path(d)


def _owner(path: str) -> dict:
    return json.loads((Path(path) / "owner.json").read_text())


@pytest.mark.unit
def test_a_run_s_directory_is_its_own_0700_token_under_the_uid_s_parent(short):
    root = short / "r"
    d = Path(scratch.make(root, "ao-x", "/h"))
    assert d.parent == root / f"shiftlead-{os.getuid()}" and len(d.name) == 8 and int(d.name, 16) >= 0
    assert stat.S_IMODE(d.stat().st_mode) == 0o700 and stat.S_IMODE(d.parent.stat().st_mode) == 0o700
    assert _owner(str(d)) == {"id": "ao-x", "home": "/h"}
    assert Path(scratch.make(root, "ao-x", "/h")) != d  # a fresh start's is a new one


@pytest.mark.unit
def test_the_parent_is_refused_when_a_symlink_and_the_root_past_48_bytes(tmp_path, short):
    root = short / "r"
    root.mkdir()
    (root / f"shiftlead-{os.getuid()}").symlink_to(tmp_path)
    with pytest.raises(scratch.ScratchError, match="symlink"):
        scratch.ensure_parent(root)
    with pytest.raises(scratch.ScratchError, match="48 bytes"):
        scratch.ensure_parent("/tmp/" + "x" * 44)  # 49 bytes
    scratch.check_root("/tmp/" + "x" * 43)  # 48 bytes: taken


@pytest.mark.unit
def test_a_48_byte_root_with_a_ten_digit_uid_binds_a_scratch_home_s_socket(tmp_path):
    """§4.6: 48 + `/shiftlead-` + ten digits + `/<token>/home/agent.sock` is 94 bytes, inside the 107 a socket
    path may hold — bound here at that length, in a root of the test's own padded to 48 bytes."""
    base = Path("/tmp") / f"aosock-{os.getpid()}"
    root = Path(str(base) + "x" * (48 - len(str(base))))
    assert len(os.fsencode(str(root))) == 48
    home = root / "shiftlead-1234567890" / "0123abcd" / "home"
    home.mkdir(parents=True)
    try:
        sock = home / "agent.sock"
        assert len(os.fsencode(str(sock))) == 94
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(sock))
        s.close()
    finally:
        import shutil

        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.unit
def test_a_handed_scratch_is_kept_only_where_it_is_this_record_s_under_this_host(tmp_path, short):
    root = short / "r"
    d = scratch.make(root, "ao-x", "/h")
    assert scratch.kept(root, d, "ao-x", "/h") == d
    assert scratch.kept(root, d, "ao-y", "/h") is None  # another record's
    assert scratch.kept(root, d, "ao-x", "/other") is None  # another home's
    assert scratch.kept(root, str(tmp_path / "elsewhere" / "0123abcd"), "ao-x", "/h") is None  # not under the parent
    assert scratch.kept(root, None, "ao-x", "/h") is None
    gone = Path(d)
    (gone / "f").write_text("x")
    for f in gone.iterdir():
        f.unlink()
    gone.rmdir()
    assert scratch.kept(root, d, "ao-x", "/h") == d  # gone: made again, 0700, owner.json, empty
    assert sorted(p.name for p in gone.iterdir()) == ["owner.json"] and stat.S_IMODE(gone.stat().st_mode) == 0o700


@pytest.mark.unit
def test_the_env_names_it_three_ways_and_each_adapter_s_temp_variable():
    assert scratch.env("/s", None) == {"SHIFTLEAD_SCRATCH": "/s", "TMPDIR": "/s"}
    assert scratch.env("/s", "CLAUDE_CODE_TMPDIR")["CLAUDE_CODE_TMPDIR"] == "/s"
    assert claude_code.ClaudeCodeAdapter.scratch_env == "CLAUDE_CODE_TMPDIR"
    assert gemini.GeminiAdapter.scratch_env is None and grok.GrokAdapter.scratch_env is None


@pytest.mark.unit
def test_scratch_root_is_read_from_hosts_yml_and_shown_on_the_hosts_card(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    assert hosts.local_host().scratch_root == hosts.DEFAULT_SCRATCH_ROOT
    (tmp_path / "hosts.yml").write_text("local:\n  scratch_root: ~/scr\n")
    local = hosts.local_host()
    assert local.scratch_root == os.path.expanduser("~/scr")
    (tmp_path / "hosts.yml").write_text("local:\n  scratch_root: rel\n")
    assert os.path.isabs(hosts.local_host().scratch_root)  # never a relative TMPDIR
    (tmp_path / "hosts.yml").write_text("local:\n  scratch_root: ~/scr\n")
    local = hosts.local_host()
    rows = {r["key"]: r for r in settings_page.host_card({"scratch_root": "~/scr"}, local, local.name, {})["rows"]}
    assert rows["scratch_root"]["value"] == local.scratch_root and not rows["scratch_root"]["default"]


@pytest.mark.integration
async def test_the_host_agent_refuses_to_start_on_a_long_root_or_a_symlinked_parent(tmp_path, short, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "hosts.yml").write_text("local:\n  scratch_root: /tmp/" + "x" * 44 + "\n")
    a = HostAgent(tmux=Tmux(socket_name="ao-test-never-started"))
    with pytest.raises(scratch.ScratchError, match="48 bytes"):
        await a.serve(tmp_path / "s.sock")
    root = short / "r"
    root.mkdir()
    (root / f"shiftlead-{os.getuid()}").symlink_to(tmp_path)
    (tmp_path / "home" / "hosts.yml").write_text(f"local:\n  scratch_root: {root}\n")
    with pytest.raises(scratch.ScratchError, match="symlink"):
        await a.serve(tmp_path / "s.sock")
    assert not (tmp_path / "s.sock").exists()


@pytest.mark.integration
async def test_a_session_cannot_hand_a_scratch_and_a_foreign_one_gets_a_new_directory(agent, tmp_path):
    await park_ticks(agent)
    other = scratch.make(hosts.local_host().scratch_root, "ao-someone-else", paths.home())
    with pytest.raises(RpcError, match="a session cannot give it"):
        await agent.rpc_create(name="x", dir=str(tmp_path), adapter="shell", scratch=other, caller="ao-a-session")
    view = await agent.rpc_create(name="x", dir=str(tmp_path), adapter="shell", scratch=other)
    got = agent.sessions[view["id"]].scratch
    assert got and got != other and _owner(got)["id"] == view["id"]
    await agent.rpc_kill(view["id"])


async def _painted(agent, sid: str) -> bool:
    return any(t.startswith(">>") for t in await agent.rpc_tail(sid, 3))


@pytest.mark.integration
async def test_a_restart_keeps_the_run_s_scratch_and_makes_it_again_where_it_is_gone(agent, composerstubs, tmp_path):
    await park_ticks(agent)
    (tmp_path / "w").mkdir()
    async with LocalClient() as person:
        params = {"name": "w", "dir": str(tmp_path / "w"), "adapter": "composer0", "unattended": True}
        sid = (await person.call("create", **params, supervised=True, prompt="the brief"))["id"]
        assert await wait_for(lambda: _painted(agent, sid), timeout=5)
        old = agent.sessions[sid]
        kept = old.scratch
        assert kept and (Path(kept) / "owner.json").exists()
        (Path(kept) / "work.txt").write_text("what the run wrote")
        old.git = dict(CLEAN)
        await agent.rpc_hook(sid, state="idle")
        await person.call("restart", id=sid)
        new = agent.sessions[sid]
        assert new is not old and new.scratch == kept and (Path(kept) / "work.txt").exists()
        assert _owner(kept) == {"id": sid, "home": str(paths.home())}
        # the sweep took it (a Resume past `scratch_keep_hours`): the restart makes it again, empty
        for f in Path(kept).iterdir():
            f.unlink()
        Path(kept).rmdir()
        assert await wait_for(lambda: _painted(agent, sid), timeout=5)
        new.git = dict(CLEAN)
        await agent.rpc_hook(sid, state="idle")
        await person.call("restart", id=sid)
        again = agent.sessions[sid]
        assert again.scratch == kept and sorted(p.name for p in Path(kept).iterdir()) == ["owner.json"]
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_a_resume_keeps_the_conversation_s_scratch_and_makes_it_again_where_it_is_gone(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        old = await c.call("create", name="conv", dir=str(tmp_path), adapter="hookstub")
        kept = agent.sessions[old["id"]].scratch
        (Path(kept) / "notes.txt").write_text("read again by the same conversation")
        await c.call("hook", session=old["id"], adapter_id="cc-123")
        await c.call("kill", id=old["id"])
        new = await c.call("create", name="conv", dir=str(tmp_path), adapter="hookstub", resume="cc-123")
        assert agent.sessions[new["id"]].scratch == kept and (Path(kept) / "notes.txt").exists()
        await c.call("hook", session=new["id"], adapter_id="cc-123")
        await c.call("kill", id=new["id"])
        # the sweep took it: the Resume makes it again, `0700`, with `owner.json`, empty
        for f in Path(kept).iterdir():
            f.unlink()
        Path(kept).rmdir()
        again = await c.call("create", name="conv", dir=str(tmp_path), adapter="hookstub", resume="cc-123")
        assert agent.sessions[again["id"]].scratch == kept
        assert sorted(p.name for p in Path(kept).iterdir()) == ["owner.json"]
        assert stat.S_IMODE(Path(kept).stat().st_mode) == 0o700
        # a fresh start of the same name, no Resume, gets a new one
        await c.call("kill", id=again["id"])
        fresh = await c.call("create", name="conv", dir=str(tmp_path), adapter="hookstub")
        assert agent.sessions[fresh["id"]].scratch not in (None, kept)
        await c.call("kill", id=fresh["id"])


DAY_NS = 86_400 * 10**9


def _aged(f: Path, now_ns: int, days: int = 11) -> tuple[int, int]:
    """Date `f` `days` back, both times; returns them."""
    t = now_ns - days * DAY_NS
    os.utime(f, ns=(t, t))
    return t, t


@pytest.mark.unit
def test_the_sweep_touches_stale_access_times_alone_and_never_through_a_symlink(tmp_path, short):
    import time

    root, now = short / "r", time.time_ns()
    d = Path(scratch.make(root, "ao-x", "/h"))
    old = d / "old.txt"
    old.write_text("a")
    git = d / "clone" / ".git" / "objects"
    git.mkdir(parents=True)
    obj = git / "ab"
    obj.write_text("b")
    outside = tmp_path / "outside.txt"
    outside.write_text("c")
    (d / "link").symlink_to(outside)
    _, m_old = _aged(old, now)
    _, m_obj = _aged(obj, now)
    a_out, m_out = _aged(outside, now)
    young = d / "young.txt"
    young.write_text("d")
    young_t = now - 3600 * 10**9
    os.utime(young, ns=(young_t, young_t))
    assert scratch.keep_alive(root, {"ao-x": str(d)}, "/h", now) == []
    for f, m in ((old, m_old), (obj, m_obj)):
        st = f.stat()
        assert st.st_atime_ns == now and st.st_mtime_ns == m
    st = outside.stat()
    assert (st.st_atime_ns, st.st_mtime_ns) == (a_out, m_out)
    assert young.stat().st_atime_ns == young_t  # accessed within the day: left


@pytest.mark.unit
def test_the_sweep_makes_a_live_record_s_directory_again_and_leaves_another_s(short):
    import time

    root = short / "r"
    d = Path(scratch.make(root, "ao-x", "/h"))
    (d / "owner.json").unlink()
    d.rmdir()
    other = Path(scratch.make(root, "ao-y", "/h"))
    stray = other / "s.txt"
    stray.write_text("e")
    t = time.time_ns() - 11 * DAY_NS
    os.utime(stray, ns=(t, t))
    nowhere = short / "elsewhere"
    scratch.keep_alive(root, {"ao-x": str(d), "ao-z": str(other), "ao-w": str(nowhere)}, "/h", time.time_ns())
    assert _owner(str(d)) == {"id": "ao-x", "home": "/h"} and stat.S_IMODE(d.stat().st_mode) == 0o700
    assert stray.stat().st_atime_ns == t  # its owner.json names ao-y: not ao-z's to touch
    assert not nowhere.exists()  # not under this host's parent: never made
    (d / "owner.json").unlink()  # a directory missing its owner.json gains it
    scratch.keep_alive(root, {"ao-x": str(d)}, "/h", time.time_ns())
    assert _owner(str(d)) == {"id": "ao-x", "home": "/h"}


@pytest.mark.unit
def test_a_record_past_sweep_touch_files_is_large_scratch(short, monkeypatch):
    import time

    monkeypatch.setattr(scratch, "SWEEP_TOUCH_FILES", 2)
    root, now = short / "r", time.time_ns()
    d = Path(scratch.make(root, "ao-x", "/h"))
    files = [d / f"f{i}" for i in range(3)]
    for f in files:
        f.write_text("x")
        _aged(f, now)
    assert scratch.keep_alive(root, {"ao-x": str(d)}, "/h", now) == ["ao-x"]
    assert sum(f.stat().st_atime_ns == now for f in files) == 2


@pytest.mark.integration
async def test_the_hourly_sweep_brings_back_a_live_record_s_scratch(agent, tmp_path, caplog, monkeypatch):
    from datetime import UTC, datetime

    await park_ticks(agent)
    view = await agent.rpc_create(name="x", dir=str(tmp_path), adapter="shell")
    d = Path(agent.sessions[view["id"]].scratch)
    for f in d.iterdir():
        f.unlink()
    d.rmdir()
    agent._pruned_at = datetime.min.replace(tzinfo=UTC)
    await agent.tick()
    await agent._prune_task
    assert _owner(str(d)) == {"id": view["id"], "home": str(paths.home())}
    monkeypatch.setattr(scratch, "SWEEP_TOUCH_FILES", 0)
    import time

    f = d / "stale"
    f.write_text("x")
    _aged(f, time.time_ns())
    await asyncio.to_thread(agent._prune_runs, datetime.now(UTC), set(), set(), {view["id"]: str(d)})
    assert "large scratch" in caplog.text
    await agent.rpc_kill(view["id"])


@pytest.mark.integration
async def test_a_node_keeps_a_scratch_the_home_hands_its_create_and_makes_a_foreign_one_anew(agent, tmp_path):
    """A node's restart (§4.6): the home closes the record and routes a create carrying its `scratch` over the
    link, as every create param goes. The node keeps it only where it is its own record's under its own parent,
    and a session's create through the home cannot hand one."""
    await park_ticks(agent)
    agent.mode, agent.home = "node", "kmaster"
    first = (await agent._act({"rpc": "create", "params": {"name": "w", "dir": str(tmp_path), "adapter": "shell"}}))[
        "result"
    ]
    kept = agent.sessions[first["id"]].scratch
    (Path(kept) / "work.txt").write_text("x")
    await agent.rpc_kill(first["id"])
    params = {"name": "w", "dir": str(tmp_path), "adapter": "shell", "scratch": kept}
    again = (await agent._act({"rpc": "create", "params": params, "caller": None}))["result"]
    assert agent.sessions[again["id"]].scratch == kept and (Path(kept) / "work.txt").exists()
    await agent.rpc_kill(again["id"])
    other = scratch.make(hosts.local_host().scratch_root, "ao-someone-else", paths.home())
    params = {"name": "v", "dir": str(tmp_path), "adapter": "shell", "scratch": other}
    fresh = (await agent._act({"rpc": "create", "params": params, "caller": None}))["result"]
    assert agent.sessions[fresh["id"]].scratch not in (None, other)
    await agent.rpc_kill(fresh["id"])
    from sessionorc import link

    with pytest.raises(link.LinkError, match="a session cannot give it"):
        await agent._act({"rpc": "create", "params": {**params, "name": "u"}, "caller": "ao-lead@kmaster"})


@pytest.mark.unit
def test_each_adapter_names_its_transcript_roots_from_the_profile_file(tmp_path, monkeypatch):
    """TD-1945, design §4.3 `transcript_roots`, §9 invariant 16: Claude Code `projects` under `~/.claude`, its
    `CLAUDE_CONFIG_DIR` and each profile's `config_dir`; Gemini CLI the whole `<home>/.gemini/tmp`; Grok Build each
    profile's `<config_dir>/sessions` (a Grok profile with none is refused at load); the core gathers them all."""
    from sessionorc import adapters

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cc"))
    monkeypatch.delenv("GEMINI_CLI_HOME", raising=False)
    (home / "profiles.yml").write_text(
        "profiles:\n"
        "  default: {adapter: claude-code}\n"
        f"  other: {{adapter: claude-code, config_dir: {tmp_path / 'cc2'}}}\n"
        f"  gem: {{adapter: gemini, config_dir: {tmp_path / 'g'}}}\n"
        f"  grok: {{adapter: grok, config_dir: {tmp_path / 'x'}}}\n"
    )
    mine = Path.home()
    assert claude_code.ClaudeCodeAdapter().transcript_roots() == sorted(
        [mine / ".claude" / "projects", tmp_path / "cc" / "projects", tmp_path / "cc2" / "projects"]
    )
    assert gemini.GeminiAdapter().transcript_roots() == sorted(
        [mine / ".gemini" / "tmp", tmp_path / "g" / ".gemini" / "tmp"]
    )
    assert grok.GrokAdapter().transcript_roots() == [tmp_path / "x" / "sessions"]
    roots, blind = adapters.transcript_roots()
    assert not blind and {tmp_path / "cc2" / "projects", tmp_path / "x" / "sessions"} <= set(roots)


@pytest.mark.unit
def test_a_scratch_root_inside_or_holding_a_transcript_root_is_refused(tmp_path):
    """§4.6, §9 invariant 16 (TD-1945): inside, holding, the same, or reached through a symlink."""
    t = tmp_path / "cfg" / "projects"
    t.mkdir(parents=True)
    for bad in (tmp_path, tmp_path / "cfg", t, t / "deeper"):
        with pytest.raises(scratch.ScratchError, match="transcripts"):
            scratch.check_transcripts(bad, [t])
    (tmp_path / "link").symlink_to(t)
    with pytest.raises(scratch.ScratchError, match="transcripts"):
        scratch.check_transcripts(tmp_path / "link" / "s", [t])
    scratch.check_transcripts(tmp_path / "elsewhere", [t])
    scratch.check_transcripts(tmp_path / "cfg" / "projectsX", [t])  # a sibling by name is not inside


@pytest.mark.integration
async def test_the_host_agent_refuses_to_start_on_a_root_holding_or_inside_a_transcript_store(
    tmp_path, short, monkeypatch
):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    root = short / "r"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root / "claude"))  # its `projects` under the root: held by it
    (tmp_path / "home" / "hosts.yml").write_text(f"local:\n  scratch_root: {root}\n")
    a = HostAgent(tmux=Tmux(socket_name="ao-test-never-started"))
    with pytest.raises(scratch.ScratchError, match="transcripts"):
        await a.serve(tmp_path / "s.sock")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(short / "c"))
    (tmp_path / "home" / "hosts.yml").write_text(f"local:\n  scratch_root: {short / 'c' / 'projects' / 's'}\n")
    with pytest.raises(scratch.ScratchError, match="transcripts"):
        await a.serve(tmp_path / "s.sock")
    assert not (tmp_path / "s.sock").exists() and not (root / f"shiftlead-{os.getuid()}").exists()


@pytest.mark.unit
def test_an_unreadable_profile_file_still_names_the_tools_own_transcript_roots(tmp_path, monkeypatch):
    """TD-1945 review: a broken `profiles.yml` loses the profiles' roots, never the tools' own `projects` or `tmp`."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cc"))
    monkeypatch.delenv("GEMINI_CLI_HOME", raising=False)
    (tmp_path / "profiles.yml").write_text("profiles: [unclosed\n")
    assert Path.home() / ".claude" / "projects" in claude_code.ClaudeCodeAdapter().transcript_roots()
    assert gemini.GeminiAdapter().transcript_roots() == [Path.home() / ".gemini" / "tmp"]
