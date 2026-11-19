"""The disk sweep's reading (design §4.6 *The sweep's reading*, §4.7 `ao disk`, TD-1946): each pass writes
`disk.json` with a dated line kept 30 days; `disk` reads it with the free space under `scratch_root`, at the home
asking itself and every node at once, one host's failure that host's entry; with `host` that host's route alone."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import diskbook, hosts, link, modes, paths
from sessionorc.agent_common import DIGEST_TIMEOUT, RpcError
from sessionorc.client import AgentError, LocalClient
from shiftlead import cli

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
FREE = {"path": "/s", "bytes_free": 50, "bytes_total": 100, "inodes_free": 50, "inodes_total": 100}


def result(removed: int = 0) -> dict:
    return {k: {"held": 7, "partial": False, "removed": removed, "kept": []} for k in diskbook.KINDS}


@pytest.mark.unit
def test_a_pass_line_older_than_thirty_days_leaves_the_totals_and_the_file(tmp_path):
    diskbook.write(tmp_path, "h", result(5), FREE, "s1", NOW - timedelta(days=32))
    diskbook.write(tmp_path, "h", result(3), FREE, "s1", NOW - timedelta(days=2))
    diskbook.write(tmp_path, "h", result(2), FREE, "s1", NOW - timedelta(days=1))
    got = diskbook.read(tmp_path, "h", "s1", NOW, FREE)
    assert got["at"] == "2026-11-18T12:00:00Z" and got["host"] == "h"
    for k in diskbook.KINDS:
        assert got["kinds"][k] == {"held": 7, "partial": False, "removed": 2, "removed_30d": 5, "kept": []}
    stored = json.loads((tmp_path / diskbook.FILE).read_text())
    assert [line["at"] for line in stored["passes"]] == ["2026-11-17T12:00:00Z", "2026-11-18T12:00:00Z"]
    # read 30 days on, the older of the two is outside the window too
    assert (
        diskbook.read(tmp_path, "h", "s1", NOW + timedelta(days=28, hours=1), FREE)["kinds"]["runs"]["removed_30d"] == 2
    )


@pytest.mark.unit
def test_a_reading_by_a_later_run_or_before_any_pass_is_partial(tmp_path):
    diskbook.write(tmp_path, "h", result(), FREE, "run-1", NOW)
    assert all(k["partial"] for k in diskbook.read(tmp_path, "h", "run-2", NOW, FREE)["kinds"].values())
    empty = diskbook.read(tmp_path / "nowhere", "h", "run-2", NOW, FREE)
    assert empty["at"] is None and all(k["partial"] and k["held"] == 0 for k in empty["kinds"].values())


@pytest.mark.unit
def test_under_a_tenth_free_of_bytes_or_inodes_is_a_warning_and_no_inode_count_draws_none():
    assert diskbook.warnings(FREE) == []
    assert diskbook.warnings({**FREE, "bytes_free": 9}) == ["under a tenth of its bytes free"]
    assert diskbook.warnings({**FREE, "inodes_free": 9}) == ["under a tenth of its inodes free"]
    assert diskbook.warnings({**FREE, "inodes_free": 0, "inodes_total": 0}) == []
    got = diskbook.free_space("/")
    assert got["bytes_total"] > 0 and got["bytes_free"] >= 0 and "inodes_total" in got
    assert diskbook.free_space("/nowhere/at/all")["bytes_total"] == got["bytes_total"]  # read at its parent


@pytest.mark.unit
def test_the_prose_names_each_kind_what_was_kept_and_a_warning():
    reading = diskbook.read("/nowhere", "h", "s", NOW, {**FREE, "inodes_free": 1})
    reading["kinds"]["worktrees"]["kept"] = [{"path": "/w/a", "why": "git work"}]
    lines = cli.disk_lines({"h": reading, "laptop": {"error": "runs on laptop: unreachable since t — down"}})
    text = "\n".join(lines)
    assert "h: no pass yet" in text and "kept /w/a — git work" in text
    assert "⚠ /s: under a tenth of its inodes free" in text
    assert "laptop: runs on laptop: unreachable since t — down" in text
    refused = cli.disk_lines({"desk": {"error": "desk: a pass runs; ask again in a minute"}})
    assert refused == ["desk: desk: a pass runs; ask again in a minute"]  # the host's own refusal, never *unreachable*
    silent = cli.disk_lines({"desk": {"error": "desk did not answer disk within 300 s: its verdict is unknown"}})
    assert silent[0].startswith("desk: unreachable — ")
    uncounted = diskbook.read("/nowhere", "h", "s", NOW, {**FREE, "inodes_free": 0, "inodes_total": 0})
    assert "inodes" not in "\n".join(cli.disk_lines({"h": uncounted}))


@pytest.mark.unit
def test_the_cli_keys_a_bare_reading_by_its_host(monkeypatch, capsys):
    bare = diskbook.read("/nowhere", "laptop", "s", NOW, FREE)
    seen = {}

    def call(method, **params):
        seen.update(method=method, **params)
        return bare

    monkeypatch.setattr(cli, "call_sync", call)
    cli.cmd_disk(argparse.Namespace(host="laptop", json=True))
    assert json.loads(capsys.readouterr().out) == {"laptop": bare}
    assert seen["method"] == "disk" and seen["host"] == "laptop" and seen["_timeout"] > DIGEST_TIMEOUT


@pytest.mark.unit
def test_a_sessions_disk_on_a_node_is_never_refused_offline():
    assert modes.offline_refusal("disk", "ao-x-1", {}, host="laptop", home="kmaster") is None
    assert modes.offline_refusal("disk", "ao-x-1", {"host": "desk"}, host="laptop", home="kmaster") is None


@pytest.mark.integration
async def test_a_pass_writes_the_reading_and_disk_answers_by_host(agent):
    await park_ticks(agent)
    agent._prune_runs(datetime.now(UTC), set(), set())
    stored = json.loads((paths.home() / diskbook.FILE).read_text())
    assert stored["host"] == agent.host and stored["started"] == agent.started_at and stored["passes"]
    assert stored["free"]["path"] == agent._scratch_root()
    async with LocalClient() as person:
        everywhere = await person.call("disk")
        assert list(everywhere) == [agent.host]
        here = everywhere[agent.host]
        assert here["at"] == stored["at"] and set(here["kinds"]) == set(diskbook.KINDS)
        assert not here["kinds"]["runs"]["partial"]  # this run wrote it
        bare = await person.call("disk", host=agent.host)
        assert bare["host"] == agent.host and "kinds" in bare
    async with LocalClient(caller="ao-stranger") as stranger:  # a read under no grant
        assert agent.host in await stranger.call("disk")


class Node:
    """A node's link end for `disk`: its reading after `delay` seconds, or its refusal."""

    closed_why = None

    def __init__(self, host: str, delay: float = 0.0, refuse: str = "") -> None:
        self.host, self.delay, self.refuse, self.sent = host, delay, refuse, []

    async def request(self, method, timeout=None, **params):
        self.sent.append((method, timeout, params))
        await asyncio.sleep(self.delay)
        if self.refuse:
            raise link.LinkError(self.refuse)
        return {"result": {**diskbook.read("/nowhere", self.host, "s", NOW, FREE)}, "record": None}

    def close(self, why="closed"):
        self.closed_why = why


@pytest.mark.integration
async def test_the_home_asks_every_node_at_once_and_one_hosts_failure_is_its_entry(agent, monkeypatch):
    await park_ticks(agent)
    monkeypatch.setattr(hosts, "nodes", lambda: {"laptop": {}, "desk": {}, "attic": {}})
    laptop, desk = Node("laptop", delay=0.4), Node("desk", delay=0.4)
    agent._link_muxes.update(laptop=laptop, desk=desk)  # attic has no link: unreachable
    agent.links["attic"] = {"up": False, "since": "t", "why": "stopped"}
    async with LocalClient() as person:
        t0 = time.monotonic()
        got = await person.call("disk")
        assert time.monotonic() - t0 < 0.8  # at once, never in turn
    assert set(got) == {agent.host, "laptop", "desk", "attic"}
    assert got["laptop"]["host"] == "laptop" and "kinds" in got["desk"]
    assert "unreachable" in got["attic"]["error"]
    method, timeout, params = laptop.sent[0]
    assert method == "act" and params["rpc"] == "disk" and params["params"] == {"host": "laptop"}
    assert timeout == DIGEST_TIMEOUT  # by the method's name, past ACT_TIMEOUT
    agent._link_muxes["desk"] = Node("desk", refuse="a pass runs; ask again in a minute")
    async with LocalClient() as person:
        got = await person.call("disk")
        assert got["desk"] == {"error": "desk: a pass runs; ask again in a minute"} and "kinds" in got[agent.host]
        alone = await person.call("disk", host="laptop")  # that host's route alone: its bare reading
        assert alone["host"] == "laptop" and "kinds" in alone


@pytest.mark.integration
async def test_a_node_reads_its_own_host_and_refuses_another(agent, monkeypatch):
    await park_ticks(agent)
    agent.mode, agent.home = "node", "kmaster-home"
    own = await agent.rpc_disk()
    assert own["host"] == agent.host and "kinds" in own
    with pytest.raises(RpcError, match="is a node of kmaster-home: it acts on its own sessions only, ask the home"):
        await agent._route_act("disk", {"host": "desk"}, None, "desk")
    # over the link the home's `host` param is popped before the handler runs
    got = await agent._act({"rpc": "disk", "params": {"host": agent.host}, "caller": None})
    assert got["result"]["host"] == agent.host and got["record"] is None
    with pytest.raises(link.LinkError, match="not my host"):
        await agent._act({"rpc": "disk", "params": {"host": "desk"}, "caller": None})


@pytest.mark.integration
async def test_through_the_socket_a_node_answers_its_own_and_refuses_another_host(agent):
    await park_ticks(agent)
    agent.mode, agent.home = "node", "kmaster-home"
    async with LocalClient(caller="ao-x-1") as session:
        own = await session.call("disk")
        assert own["host"] == agent.host and "kinds" in own
        with pytest.raises(AgentError, match="ask the home"):
            await session.call("disk", host="desk")
