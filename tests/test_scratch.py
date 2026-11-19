"""TD-1944, design §4.6 *A session's scratch*: every run of a record has one `0700` scratch directory,
`<scratch_root>/shiftlead-<uid>/<token>/`, holding `owner.json`, named in the record's `scratch` and in its env as
`SHIFTLEAD_SCRATCH`, `TMPDIR` and the adapter's `scratch_env`; a restart and a Resume keep it, a fresh start gets a
new one; the host agent refuses a `scratch_root` past 48 bytes and a `shiftlead-<uid>/` that is a symlink."""

from __future__ import annotations

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
