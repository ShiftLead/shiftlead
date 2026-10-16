"""TD-739: a page reads the host agent's `repos` reading once per request, not once per part that uses it."""

from __future__ import annotations

import asyncio

import pytest
from test_ui_entry import client, fake, world


def counting(log: list[str], repos: dict):
    class Fake(fake([])):
        async def call(self, method, **kw):
            log.append(method)
            if method == "inbox":
                return {"entries": []}
            if method == "repos":
                return repos
            return await super().call(method, **kw)

    return Fake


@pytest.mark.unit
@pytest.mark.parametrize("path", ["/", "/inbox", "/repo/samscrape"])
def test_a_page_reads_repos_once_per_request(tmp_path, monkeypatch, path):
    root = str(world(tmp_path))
    reading = {"name": "samscrape", "root": root, "ledger": {"path": "docs/technical_debt.md", "entries": []}}
    log: list[str] = []
    c = client(monkeypatch, tmp_path, counting(log, {root: reading}))
    for _ in range(2):  # each request reads it afresh, once
        log.clear()
        assert c.get(path).status_code == 200
        assert log.count("repos") == 1, (path, log)


@pytest.mark.unit
def test_a_reader_with_no_request_reads_repos_each_time(monkeypatch):
    """`ao inbox --counts` makes its own `Readings`, outside any request: nothing is memoised."""
    from shiftlead.ui import app as ui

    log: list[str] = []

    async def call(method, **kw):
        log.append(method)
        return {}

    rd = ui.Readings(call)
    asyncio.run(rd.repos())
    asyncio.run(rd.repos())
    assert log == ["repos", "repos"]


@pytest.mark.unit
def test_a_memo_older_than_its_ttl_is_read_again(monkeypatch):
    """A long-lived request (the events stream) never holds a reading past `REPOS_MEMO_TTL`."""
    from shiftlead.ui import app as ui

    log: list[str] = []
    clock = [100.0]

    async def call(method, **kw):
        log.append(method)
        return {"n": len(log)}

    monkeypatch.setattr(ui.time, "monotonic", lambda: clock[0])
    rd = ui.Readings(call)

    async def go():
        ui._REPOS_MEMO.set({})
        a, b = await rd.repos(), await rd.repos()
        clock[0] += ui.REPOS_MEMO_TTL + 0.1
        return a, b, await rd.repos()

    assert asyncio.run(go()) == ({"n": 1}, {"n": 1}, {"n": 2})
