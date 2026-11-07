"""An envelope carries its sender's `repo` (design §4.10, TD-1467, TD-1453's first build): the home stamps the
registry's name for the sender's record's repo at the send beside `team` — a session in a worktree of a registered
repo, a node's record against that node's own registry — and none for the person or a session in no registered
checkout; a copy moved by the re-route (TD-1480, a landing, not a send) keeps `repo` and `team`."""

from datetime import UTC, datetime

import pytest
from conftest import park_ticks

from sessionorc import queue
from sessionorc.agent_common import RpcError
from sessionorc.client import LocalClient
from sessionorc.models import Session

pytestmark = pytest.mark.integration


def _registry(tmp_path, *repos) -> None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text("".join(f"{r}\n" for r in repos))
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")


async def _mk(person, d, name: str, **kw) -> str:
    d.mkdir(parents=True, exist_ok=True)
    kw.setdefault("unattended", True)
    got = await person.call("create", name=name, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw)
    return got["id"]


async def test_the_send_stamps_the_senders_registered_repo_and_none_elsewhere(agent, tmp_path):
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    _registry(tmp_path, alpha)
    async with LocalClient() as person:
        inside = await _mk(person, alpha / ".claude" / "worktrees" / "g", "g", team="t")
        outside = await _mk(person, tmp_path / "loose", "loose")
        async with LocalClient(caller=inside) as c:
            got = (await c.call("msg", to="person", text="TD-221: merge #164?", kind="ask", about="TD-221"))["entry"]
        assert got["repo"] == "alpha" and got["team"] == "t", "a worktree's record names its registered repo"
        async with LocalClient(caller=outside) as c:
            assert (await c.call("msg", to="person", text="from nowhere"))["entry"]["repo"] is None
        assert (await person.call("msg", to=inside, text="from the person"))["entry"]["repo"] is None
        # it survives the sender, and the read side takes it first (`mail_repo`'s order)
        kept = next(e for e in agent.person_inbox if e.id == got["id"])
        assert kept.repo == "alpha" and queue.asker_repos([kept], []) == {got["id"]: "alpha"}
        for sid in (inside, outside):
            await person.call("kill", id=sid)


async def test_a_nodes_record_is_named_against_its_own_hosts_registry(agent, tmp_path):
    calls: list[str] = []

    async def host_repos(host: str):
        calls.append(host)
        if host == "gone":
            raise RpcError("gone did not answer")
        return {"host": host, "repos": ["/srv/beta"]}

    agent.rpc_host_repos = host_repos
    rec = Session(id="g", name="g", kind="agent", adapter="agentshell", dir="/srv/beta/.claude/worktrees/g")
    rec.host, rec.repo = "node1", "/srv/beta"
    assert await agent._record_repo(rec) == "beta"
    assert await agent._record_repo(rec) == "beta" and calls == ["node1"], "the node's roster is kept, not re-asked"
    rec.host = "gone"
    assert await agent._record_repo(rec) is None, "a node that does not answer gives none, and the send stands"
    local = Session(id="h", name="h", kind="agent", adapter="agentshell", dir="/srv/beta/x")
    local.host = agent.host  # the local host's registry lists no /srv/beta: never the node's roster
    assert await agent._record_repo(local) is None
    assert await agent._record_repo(None) is None


async def test_a_rerouted_copy_keeps_its_repo_and_team(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        tl = await _mk(person, tmp_path / "tl", "tl", team="beta", seat={"trigger": "asks", "tags": True})
        rv = await _mk(person, tmp_path / "rv", "rv", team="beta", seat={"trigger": "asks"})
        w = await _mk(person, tmp_path / "w", "w", team="beta")
        async with LocalClient(caller=w) as c:
            first = (await c.call("msg", to=rv, text="which test covers TD-9?", kind="ask", about="TD-9"))["entry"]
        for r in agent.sessions.values():
            for e in r.holds(first["id"]):
                e.repo = "alpha"  # as the send would have stamped a sender in alpha
        agent.sessions[rv].state, agent.sessions[rv].limited_reset = "limited", None
        await agent._reroute_waiting(datetime.now(UTC))
        moved = [e for e in agent.sessions[tl].inbox if e.root == first["root"] and e.id != first["id"]]
        assert len(moved) == 1 and moved[0].repo == "alpha" and moved[0].team == "beta"
        for sid in (tl, rv, w):
            await person.call("kill", id=sid)
