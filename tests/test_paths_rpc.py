"""The `paths` read (design §4.6 *A path in the pane is a link*, TD-501, TD-688): which runs a pane
named are regular files the record's host can read, its real path judged and `PATHS_PRIVATE` kept as
text, answered by the record's host."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sessionorc.agent import _path_private
from sessionorc.agent_common import NODE_READS, PATHS_RUN_CHARS, PATHS_RUNS_MAX
from sessionorc.client import AgentError, LocalClient


def checkout(tmp_path: Path) -> Path:
    """A repo with a worktree beside its files: `dir` is the worktree, `repo` the main checkout."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "x.py").write_text("x\n")
    (repo / "top.md").write_text("top\n")
    wt = repo / ".claude" / "worktrees" / "w"
    (wt / "src" / "sub").mkdir(parents=True)
    (wt / "src" / "a.py").write_text("a\n")
    (wt / "out.txt").symlink_to("/etc/passwd")
    (wt / "in.txt").symlink_to(wt / "src" / "a.py")
    (tmp_path / "outside.txt").write_text("no\n")
    (tmp_path / "repo-evil").mkdir()  # a sibling whose name starts with the repo's
    (tmp_path / "repo-evil" / "f.txt").write_text("no\n")
    return wt


@pytest.mark.integration
async def test_a_run_answers_as_any_readable_regular_file_on_the_host(agent, tmp_path, monkeypatch):
    assert "paths" in NODE_READS  # a node's record answers through `read`, as a transcript does
    wt = checkout(tmp_path)
    repo = wt.parent.parent.parent
    home = tmp_path / "userhome"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / "h.txt").write_text("h\n")
    async with LocalClient() as person:
        sid = (await person.call("create", name="sh", dir=str(wt), adapter="shell", argv=["bash", "--norc"]))["id"]
        agent.sessions[sid].repo = str(repo)  # a worktree's record carries its main checkout
        runs = [
            "src/a.py",  # relative to `dir`
            "./src/a.py",
            "src/a.py:12",  # the page strips `:line` before it asks: a run with one is not a file
            "src/sub",  # a directory is the header button's
            "src/missing.py",
            "out.txt",  # a symlink out of the checkout answers its target (TD-688)
            "in.txt",  # a symlink inside it answers as its target
            "../../../src/x.py",  # up out of the worktree, into the repo
            "../../../../outside.txt",  # and up out of both: any readable file on the host
            f"{repo}/top.md",  # absolute, inside the repo
        ]
        got = {}
        for i in range(0, len(runs), PATHS_RUNS_MAX):  # one row asks about eight at most
            got |= (await person.call("paths", id=sid, runs=runs[i : i + PATHS_RUNS_MAX]))["paths"]
        assert got == {
            "src/a.py": str(wt / "src" / "a.py"),
            "./src/a.py": str(wt / "src" / "a.py"),
            "src/a.py:12": None,
            "src/sub": None,
            "src/missing.py": None,
            "out.txt": os.path.realpath("/etc/passwd"),
            "in.txt": str(wt / "src" / "a.py"),
            "../../../src/x.py": str(repo / "src" / "x.py"),
            "../../../../outside.txt": str(tmp_path / "outside.txt"),
            f"{repo}/top.md": str(repo / "top.md"),
        }
        odd = ["src/a\x00.py", "~nosuchuser-td501/x"]
        assert (await person.call("paths", id=sid, runs=odd))["paths"] == dict.fromkeys(odd)
        with pytest.raises(AgentError, match="runs, a list of strings"):
            await person.call("paths", id=sid, runs=["src/a.py", 3])
        assert (await person.call("paths", id=sid, runs=["~/h.txt", f"{repo}-evil/f.txt"]))["paths"] == {
            "~/h.txt": str(home / "h.txt"),  # home expanded: a `~/.bashrc` is a link (TD-688)
            f"{repo}-evil/f.txt": str(tmp_path / "repo-evil" / "f.txt"),
        }
        # the bounds, refused naming them
        with pytest.raises(AgentError, match=f"past the {PATHS_RUNS_MAX} one row may ask about"):
            await person.call("paths", id=sid, runs=["a/b"] * (PATHS_RUNS_MAX + 1))
        with pytest.raises(AgentError, match=f"past the {PATHS_RUN_CHARS} one may be"):
            await person.call("paths", id=sid, runs=["a/" * PATHS_RUN_CHARS])
        with pytest.raises(AgentError, match="runs, a list of strings"):
            await person.call("paths", id=sid, runs="src/a.py")
        with pytest.raises(AgentError, match="no session ao-nope"):
            await person.call("paths", id="ao-nope", runs=[])
        async with LocalClient(caller=sid) as other:
            assert (await other.call("paths", id=sid, runs=["src/a.py"]))["paths"]["src/a.py"]  # a read: ungated
        # a `~/` run inside the checkout answers: the home is the checkout's parent here
        monkeypatch.setenv("HOME", str(repo))
        assert (await person.call("paths", id=sid, runs=["~/top.md"]))["paths"] == {"~/top.md": str(repo / "top.md")}
        # a node serves it to the home through `read`
        old_mode = agent.mode, agent.home
        agent.mode, agent.home = "node", "kmaster"
        reply = await agent._from_home("read", {"rpc": "paths", "params": {"id": sid, "runs": ["src/a.py"]}})
        assert reply == {"paths": {"src/a.py": str(wt / "src" / "a.py")}}
        agent.mode, agent.home = old_mode
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


@pytest.mark.integration
async def test_an_unreadable_file_and_a_record_with_no_repo(agent, tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    (d / "f.txt").write_text("f\n")
    locked = d / "locked"
    locked.mkdir()
    (locked / "g.txt").write_text("g\n")
    (d / "shut.txt").write_text("s\n")
    async with LocalClient() as person:
        sid = (await person.call("create", name="sh", dir=str(d), adapter="shell", argv=["bash", "--norc"]))["id"]
        assert agent.sessions[sid].repo is None
        os.chmod(locked, 0)
        os.chmod(d / "shut.txt", 0)
        try:
            got = (await person.call("paths", id=sid, runs=["f.txt", "locked/g.txt", "shut.txt"]))["paths"]
        finally:
            os.chmod(locked, 0o755)
            os.chmod(d / "shut.txt", 0o644)
        assert got["f.txt"] == str(d / "f.txt")
        assert got["locked/g.txt"] is None or os.geteuid() == 0  # root stats through a mode of 0
        assert got["shut.txt"] is None or os.geteuid() == 0  # a regular file this user cannot read
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


@pytest.mark.integration
async def test_a_checkout_reached_through_a_symlink_answers_its_files(agent, tmp_path):
    """A `dir` reached through a link (TD-517) — a home or a worktree path that is one — resolves a
    relative run against it and answers the real path."""
    wt = checkout(tmp_path)
    repo = wt.parent.parent.parent
    (tmp_path / "linked").symlink_to(repo)
    async with LocalClient() as person:
        sid = (await person.call("create", name="sh", dir=str(wt), adapter="shell", argv=["bash", "--norc"]))["id"]
        s = agent.sessions[sid]
        s.dir = str(tmp_path / "linked" / ".claude" / "worktrees" / "w")  # as the record may hold it
        s.repo = str(tmp_path / "linked")
        got = (await person.call("paths", id=sid, runs=["src/a.py", "../../../top.md", "out.txt"]))["paths"]
        assert got == {
            "src/a.py": str(wt / "src" / "a.py"),
            "../../../top.md": str(repo / "top.md"),
            "out.txt": os.path.realpath("/etc/passwd"),
        }
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


@pytest.mark.integration
async def test_paths_is_served_under_enforce_from_a_channel_nobody_can_place(agent, tmp_path, monkeypatch):
    """`paths` is a read (§4.4a, TD-519): under `enforce` a request whose channel cannot be placed
    is refused unless its method is in `identity.READS`, and the Focus page's hover is one."""
    wt = checkout(tmp_path)

    async def boom(*_a, **_k):
        raise RuntimeError("the classification fell over")

    async with LocalClient() as person:
        sid = (await person.call("create", name="sh", dir=str(wt), adapter="shell", argv=["bash", "--norc"]))["id"]
    monkeypatch.setattr(agent, "_id_channel", boom)
    agent.identity_mode = "enforce"
    async with LocalClient() as person:
        assert (await person.call("paths", id=sid, runs=["src/a.py"]))["paths"] == {
            "src/a.py": str(wt / "src" / "a.py")
        }
        with pytest.raises(AgentError, match="identity check failed"):
            await person.call("doing", id=sid, text="nope")  # the gate is on: a write is refused
    agent.identity_mode = "off"
    async with LocalClient() as person:
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


@pytest.mark.integration
async def test_a_credential_file_stays_text_whatever_the_stat_says(agent, tmp_path, monkeypatch):
    """`PATHS_PRIVATE` (§4.6, TD-688): a credential file is nothing though it is readable, matched on
    the real path, so a symlink to one is nothing too; the run limits stand beside it."""
    home = tmp_path / "userhome"
    for f in (".bashrc", ".ssh/config", ".ssh/id_x", ".config/gh/hosts.yml", ".config/other.yml", ".netrc"):
        (home / f).parent.mkdir(parents=True, exist_ok=True)
        (home / f).write_text("x\n")
    other = tmp_path / "otheruser" / ".ssh"  # a `.ssh/` in another user's home
    other.mkdir(parents=True)
    (other / "known_hosts").write_text("x\n")
    d = tmp_path / "repo"
    (d / "deploy" / ".ssh").mkdir(parents=True)  # and in a repo
    (d / "deploy" / ".ssh" / "k").write_text("x\n")
    for f in (".env", ".env.local", "env.txt", "server.pem", "tls.key", "notes.keys", ".docker/config.json"):
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_text("x\n")
    (d / "docker").mkdir()
    (d / "docker" / "config.json").write_text("x\n")  # not `.docker/`: a file like any other
    (d / "id_link").symlink_to(home / ".ssh" / "id_x")
    monkeypatch.setenv("HOME", str(home))
    async with LocalClient() as person:
        sid = (await person.call("create", name="sh", dir=str(d), adapter="shell", argv=["bash", "--norc"]))["id"]
        runs = [
            "~/.bashrc",
            "~/.ssh/config",
            f"{other}/known_hosts",
            "deploy/.ssh/k",
            "id_link",  # a symlink to `~/.ssh/id_x`
            "~/.config/gh/hosts.yml",
            "~/.config/other.yml",
            "~/.netrc",
        ]
        got = (await person.call("paths", id=sid, runs=runs))["paths"]
        assert got == {
            "~/.bashrc": str(home / ".bashrc"),
            "~/.ssh/config": None,
            f"{other}/known_hosts": None,
            "deploy/.ssh/k": None,
            "id_link": None,
            "~/.config/gh/hosts.yml": None,
            "~/.config/other.yml": str(home / ".config" / "other.yml"),
            "~/.netrc": None,
        }
        runs = [".env", ".env.local", "./env.txt", "./server.pem", "./tls.key", "./notes.keys"]
        runs += ["./.docker/config.json", "docker/config.json", "/proc/self/environ", "./deploy"]
        got = (await person.call("paths", id=sid, runs=runs[:PATHS_RUNS_MAX]))["paths"]
        got |= (await person.call("paths", id=sid, runs=runs[PATHS_RUNS_MAX:]))["paths"]
        assert got == {
            ".env": None,
            ".env.local": None,
            "./env.txt": str(d / "env.txt"),
            "./server.pem": None,
            "./tls.key": None,
            "./notes.keys": str(d / "notes.keys"),
            "./.docker/config.json": None,
            "docker/config.json": str(d / "docker" / "config.json"),
            "/proc/self/environ": None,  # a process's environment holds the secrets Doppler injected
            "./deploy": None,  # a directory is the header button's
        }
        with pytest.raises(AgentError, match=f"past the {PATHS_RUNS_MAX} one row may ask about"):
            await person.call("paths", id=sid, runs=runs)
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


def test_private_matches_whole_components_only():
    assert _path_private("/proc") and _path_private("/dev/null") and _path_private("/sys/kernel/x")
    assert not _path_private("/process/x") and not _path_private("/devices.txt")
    assert _path_private("/home/u/.aws/credentials") and _path_private("/r/.password-store/a.gpg")
    assert not _path_private("/home/u/my.ssh/x") and not _path_private("/home/u/.ssh.md")
    assert _path_private("/home/u/.config/doppler/cli.yaml") and not _path_private("/home/u/doppler/x")
    assert not _path_private("/home/u/.config/ghost/x") and not _path_private("/home/u/.docker/other.json")
    assert _path_private("/home/u/.claude.json") and _path_private("/home/u/.claude/.credentials.json")
    assert not _path_private("/home/u/.claude/settings.json") and not _path_private("/r/.envrc")
