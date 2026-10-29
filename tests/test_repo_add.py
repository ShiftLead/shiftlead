"""`ao repo add <path>` (design §4.7 **`ao repo add`**, §5 *Repos*, TD-1010): the home's `add_repo` RPC
appends a checkout to its roster — a person's own act, at the home — and the client word calls it."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import park_ticks, served

from sessionorc import hosts
from sessionorc.client import AgentError, LocalClient
from shiftlead import cli


def _repo(root: Path) -> Path:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    return root


def _roster() -> list[str]:
    reg = hosts.default_repos_registry()
    return reg.read_text(encoding="utf-8").splitlines() if reg.exists() else []


async def test_a_checkout_holding_agent_cadence_is_added_once_and_read_whole_on_the_next_tick(agent, tmp_path):
    await park_ticks(agent)
    root = _repo(tmp_path / "samscrape")
    served(root)
    async with LocalClient() as person:
        got = await person.call("add_repo", path=str(root / "docs"))  # any directory of it: its main checkout
        assert got == {"root": str(root.resolve()), "name": "samscrape", "served": True}
        assert _roster() == [str(root.resolve())]
        with pytest.raises(AgentError, match="is in the roster already"):
            await person.call("add_repo", path=str(root))
    await agent._refresh_repos()
    assert agent._repos[str(root.resolve())]["seams"]["serve"]["ok"] is True


async def test_a_worktree_adds_its_main_checkout_and_a_line_lands_after_a_hand_added_one(agent, tmp_path):
    await park_ticks(agent)
    root = _repo(tmp_path / "r")
    served(root)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"])
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", str(wt)], check=True)
    reg = hosts.default_repos_registry()
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text("# mine\n/elsewhere")  # a hand-added line, no newline at its end
    async with LocalClient() as person:
        assert (await person.call("add_repo", path=str(wt)))["root"] == str(root.resolve())
    assert _roster() == ["# mine", "/elsewhere", str(root.resolve())]


async def test_agent_cadences_source_is_added_and_a_checkout_without_agent_cadence_is_refused(agent, tmp_path):
    await park_ticks(agent)
    source = _repo(tmp_path / "agent-cadence")
    (source / "sync.sh").write_text("#!/bin/sh\n")
    (source / "files" / "scripts").mkdir(parents=True)
    (source / "files" / "scripts" / "check_cadence.py").write_text("x = 1\n")  # its gate
    (source / "docs").mkdir()
    (source / "docs" / "technical_debt.md").write_text("# Technical debt\n")
    bare = _repo(tmp_path / "notes")
    async with LocalClient() as person:
        assert (await person.call("add_repo", path=str(source)))["served"] is True
        with pytest.raises(AgentError, match="holds no agent-cadence .*its adoption comes first"):
            await person.call("add_repo", path=str(bare))
        assert _roster() == [str(source.resolve())]
        # its adoption PR open, it is added unserved until that merges (§5 *The seams*)
        assert (await person.call("add_repo", path=str(bare), adopted=True))["served"] is False
        with pytest.raises(AgentError, match="is not in a git checkout"):
            await person.call("add_repo", path=str(tmp_path))
    assert _roster() == [str(source.resolve()), str(bare.resolve())]


async def test_served_is_the_seams_reading_whatever_let_the_checkout_be_added(agent, tmp_path):
    """§4.7: a checkout holding the lock is added, and is served or unserved as the reading finds it."""
    await park_ticks(agent)
    root = _repo(tmp_path / "r")
    served(root)
    (root / "docs" / "technical_debt.md").unlink()  # the lock and the gate, no ledger
    async with LocalClient() as person:
        assert (await person.call("add_repo", path=str(root)))["served"] is False
    assert _roster() == [str(root.resolve())]


async def test_add_repo_is_a_persons_own_and_the_homes(agent, tmp_path):
    await park_ticks(agent)
    root = _repo(tmp_path / "r")
    served(root)
    async with LocalClient(caller="ao-some-worker") as worker:
        with pytest.raises(AgentError, match="a person's own act, refused to every session"):
            await worker.call("add_repo", path=str(root))
    agent.mode = "node"
    try:
        async with LocalClient() as person:
            with pytest.raises(AgentError, match="run ao repo add on the home"):
                await person.call("add_repo", path=str(root))
    finally:
        agent.mode = "home"
    assert _roster() == []


def test_the_word_calls_the_rpc_with_the_resolved_path_and_is_refused_on_a_node(tmp_path, monkeypatch, capsys):
    calls = []

    def call(method, **kw):
        calls.append((method, kw))
        return {"root": kw["path"], "name": Path(kw["path"]).name, "served": True}

    monkeypatch.setattr(cli, "call_sync", call)
    monkeypatch.setattr(hosts, "is_node", lambda: False)
    monkeypatch.chdir(tmp_path)
    served(_repo(tmp_path / "notes"))  # it holds agent-cadence: the RPC's to add
    assert cli.main(["repo", "add", "notes"]) == 0
    assert calls == [("add_repo", {"path": str((tmp_path / "notes").resolve())})]
    assert capsys.readouterr().out.startswith("added notes")
    assert cli.main(["repo", "add"]) != 0
    assert "ao repo add takes a checkout's path" in capsys.readouterr().err
    assert cli.main(["repo", "samscrape", "extra"]) != 0
    monkeypatch.setattr(hosts, "is_node", lambda: True)
    assert cli.main(["repo", "add", "notes"]) != 0
    assert "run ao repo add on the home" in capsys.readouterr().err
    assert len(calls) == 1


def test_ao_repo_help_lists_add(capsys):
    with pytest.raises(SystemExit):
        cli.main(["repo", "--help"])
    assert "or `add`" in capsys.readouterr().out
