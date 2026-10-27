"""TD-746: a page asks the host agent for the `repos` reading without the parts it never draws (the RPC's
`omit`), and what it draws from that reading is what it drew from the whole one."""

from __future__ import annotations

import copy
import dataclasses
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks
from test_ui_entry import client, fake, world

from sessionorc import hosts, reports
from sessionorc.client import LocalClient


def _reading(root: str) -> dict:
    """A reading with every part a page may leave out: the ledger's month, PRs of the month with
    every field, entries with detail blocks, and what completed."""
    now = datetime.now(UTC)
    day = (now - timedelta(days=1)).isoformat()
    pr = {
        "number": 7,
        "title": "TD-001: a fix",
        "url": "https://github.com/o/samscrape/pull/7",
        "state": "merged",
        "branch": "td001-fix",
        "head": "abc",
        "base": "main",
        "author": "someone",
        "draft": False,
        "created": day,
        "closed": day,
    }
    entry = {
        "id": "TD-002",
        "title": "a question for the person",
        "priority": "Medium",
        "owner": "grinder",
        "kind": "build",
        "type": "debt",
        "blocked_by": [],
        "blocked_ids": [],
        "pickable": "yes",
        "sig": "s",
        "for_page": "pickable",
        "added": "2026-10-01",
        "detail": ["**Why:** a long block only the Inbox's ledger row draws"],
    }
    return {
        "name": "samscrape",
        "root": root,
        "remote": "https://github.com/o/samscrape",
        "at": now.isoformat(),
        "ledger": {
            "path": "docs/technical_debt.md",
            "entries": [entry, {**entry, "id": "TD-003", "for_page": "for-you"}],
            "by_priority": {"High": 0, "Medium": 2, "Low": 0},
            "windows": {w: {"opened": 1, "closed": 1} for w in ("day", "week", "month")},
            "recent": [{"id": "TD-001", "title": "a fix", "opened": day, "closed": day, "pr": 7}],
        },
        "prs": {"open": [], "recent": [pr], "windows": {}, "at": now.isoformat()},
        "completed": [
            {"id": "TD-001", "title": "a fix", "closed": day, "pr": 7, "author": "someone", "url": pr["url"]}
        ],
        "boards": {"boards": [], "at": now.isoformat()},
    }


@pytest.mark.unit
def test_omitted_leaves_out_each_path_through_mappings_and_lists_and_never_changes_the_value():
    v = {"a": {"b": [{"x": 1, "y": 2}, {"x": 3}], "c": 4}, "d": 5}
    before = copy.deepcopy(v)
    assert reports.omitted(v, ["a.b.y", "d"]) == {"a": {"b": [{"x": 1}, {"x": 3}], "c": 4}}
    assert reports.omitted(v, ["a", "a.b.x"]) == {"d": 5}  # left out whole, whatever else names it
    assert reports.omitted(v, ["a.b.x", "a"]) == {"d": 5}  # in either order
    assert reports.omitted(v, ["nope", "a.nope.z", "d.z"]) == v  # a path that names nothing
    assert reports.omitted(v, []) == v
    assert v == before


@pytest.mark.unit
def test_a_filtered_reading_is_the_whole_one_without_those_paths(tmp_path):
    from shiftlead.ui import app as ui

    whole = _reading(str(tmp_path))
    got = reports.omitted(whole, ui.REPOS_OMIT_PAGE)
    want = copy.deepcopy(whole)
    del want["ledger"]["recent"]
    for e in want["ledger"]["entries"]:
        del e["detail"]
    want["prs"]["recent"] = [{k: p[k] for k in ("number", "title", "url", "state")} for p in whole["prs"]["recent"]]
    assert got == want
    inbox = reports.omitted(whole, ui.REPOS_OMIT_INBOX)
    assert "completed" not in inbox and inbox["ledger"]["entries"] == whole["ledger"]["entries"]


async def test_the_repos_rpc_serves_each_reading_without_what_omit_names(agent, tmp_path, monkeypatch):
    root = str(tmp_path)
    # the root registered and its read a no-op, so a repos pass keeps the reading the test sets: an
    # unregistered root's reading is dropped by the next pass, which raced the calls below (TD-1067)
    await park_ticks(agent)
    (reg := tmp_path / "repos.txt").write_text(f"{root}\n")
    real = hosts.local_host
    monkeypatch.setattr(hosts, "local_host", lambda: dataclasses.replace(real(), repos_registry=reg))
    monkeypatch.setattr(agent, "_read_repos", lambda *a: {})
    agent._repos[root] = _reading(root)
    whole = copy.deepcopy(agent._repos[root])
    await agent._refresh_repos()  # a pass between the set and the calls keeps it
    async with LocalClient() as c:
        assert await c.call("repos") == {root: whole}  # no omit: whole, as ever
        got = await c.call("repos", omit=["ledger.recent", "prs.recent.head", "completed"])
    assert set(got[root]) == set(whole) - {"completed"}
    assert "recent" not in got[root]["ledger"] and "head" not in got[root]["prs"]["recent"][0]
    assert got[root]["prs"]["recent"][0]["state"] == "merged"
    assert agent._repos[root]["ledger"]["recent"]  # the agent's own reading keeps every part


def member(root: str) -> dict:
    """A live grinder of the team holding TD-001, whose PR #7 the month's PRs hold as merged: its card's
    report line and the team's *TDs in motion* row read the PR's state, title and link."""
    return {
        "id": "ao-samscrape-grinder-1",
        "name": "grinder-1",
        "state": "working",
        "team": "sam-grind",
        "unattended": True,
        "repo": root,
        "dir": root,
        "progress": [{"ref": "TD-001", "status": "claimed", "pr": 7}],
    }


def recording(log: list[dict], whole: dict, honour: bool = True, fleet: list | None = None):
    """A fake host agent that records each `repos` call's params and answers the reading, without
    what `omit` names when `honour` (else whole, as an agent older than TD-746 does)."""

    class Fake(fake(fleet or [])):
        async def call(self, method, **kw):
            if method == "inbox":
                return {"entries": []}
            if method == "repos":
                log.append(kw)
                return reports.omitted(whole, kw.get("omit") or []) if honour else whole
            if method == "seen":  # Focus opens on a record (TD-756), drawn whole
                at = datetime.now(UTC).isoformat()
                rec = {"since": at, "created": at, "confidence": "hook", "kind": "agent", "adapter": "shell"}
                return {**rec, **member(next(iter(whole)))}
            return await super().call(method, **kw)

    return Fake


PAGES = [
    ("/", "REPOS_OMIT_PAGE"),
    ("/repo/samscrape", "REPOS_OMIT_PAGE"),
    ("/api/sessions", "REPOS_OMIT_PAGE"),
    ("/inbox", "REPOS_OMIT_INBOX"),
    ("/api/person/inbox", "REPOS_OMIT_INBOX"),
    ("/focus/ao-samscrape-grinder-1", "REPOS_OMIT_PAGE"),  # TD-756: the report line's PR mark
    ("/inbox/m-1", "REPOS_OMIT_INBOX"),  # TD-756: the message page's row, drawn as the list draws it
]


@pytest.mark.unit
@pytest.mark.parametrize(("path", "omit"), PAGES)
def test_each_page_asks_for_the_reading_without_what_it_never_draws(tmp_path, monkeypatch, path, omit):
    from shiftlead.ui import app as ui

    root = str(world(tmp_path))
    log: list[dict] = []
    c = client(monkeypatch, tmp_path, recording(log, {root: _reading(root)}))
    assert c.get(path).status_code == 200
    assert log == [{"omit": list(getattr(ui, omit))}], (path, log)


@pytest.mark.unit
@pytest.mark.parametrize("path", ["/", "/repo/samscrape", "/inbox", "/api/person/inbox"])
def test_a_page_draws_from_the_omitted_reading_what_it_drew_from_the_whole_one(tmp_path, monkeypatch, path):
    root = str(world(tmp_path))
    whole = {root: _reading(root)}
    pages = []
    for honour in (False, True):
        c = client(monkeypatch, tmp_path, recording([], whole, honour, [member(root)]))
        r = c.get(path)
        assert r.status_code == 200
        pages.append(r.text)
    assert pages[0] == pages[1]
    # the page drew the parts of the reading an omit could have cost it
    drawn = {
        "/": "#7 merged",
        "/repo/samscrape": "a fix",
        "/inbox": "a long block",
        "/api/person/inbox": "a long block",
    }
    assert drawn[path] in pages[1], path


@pytest.mark.unit
def test_the_settings_page_reads_the_numbers_alone(tmp_path, monkeypatch):
    from shiftlead.ui import app as ui

    root = str(world(tmp_path))
    log: list[dict] = []
    c = client(monkeypatch, tmp_path, recording(log, {root: _reading(root)}))
    assert c.get("/settings").status_code == 200
    assert log == [{"omit": [*ui.REPOS_OMIT_PAGE, "completed"]}]


@pytest.mark.unit
def test_the_counts_outside_a_request_read_the_reading_once_without_the_inbox_omit(monkeypatch):
    """The keeper's recount and `ao inbox --counts` hold a memo of their own: one read, omitted."""
    import asyncio

    from shiftlead.ui import app as ui

    log: list[dict] = []

    async def call(method, **kw):
        if method == "repos":
            log.append(kw)
        return {"list": [], "inbox": {"entries": []}}.get(method, {})

    asyncio.run(ui.Readings(call).counts_now(False))
    assert log == [{"omit": list(ui.REPOS_OMIT_INBOX)}]


# -- the events stream (TD-754) ---------------------------------------------------------------------


async def test_a_subscriber_with_an_omit_is_sent_repos_events_without_it_and_one_without_whole(agent, tmp_path):
    """The seed a subscribe is sent and each `repos` event after it: a subscription that names an
    `omit` gets the reading without those paths, one that names none gets it whole, and a dropped
    checkout's `repo: null` reaches both as it is."""
    import asyncio

    root = str(tmp_path)
    await park_ticks(agent)  # no tick re-reads or drops the hand-written root under the test (TD-874)
    agent._repos[root] = _reading(root)
    view = agent._repo_view(root)  # what every event carries, taken once: a later re-read cannot move it
    omit = ["ledger.recent", "ledger.entries.detail", "completed"]
    got: dict[str, list[dict]] = {"some": [], "whole": []}

    async def listen(key: str, o: list[str] | None) -> None:
        async with LocalClient() as sub:
            async for ev in sub.subscribe(o):
                if ev.get("event") == "repos":
                    got[key].append(ev)

    tasks = [asyncio.create_task(listen("some", omit)), asyncio.create_task(listen("whole", None))]
    try:
        for _ in range(50):
            if all(got.values()):
                break
            await asyncio.sleep(0.05)
        await agent._broadcast({"event": "repos", "root": root, "repo": view})
        await agent._broadcast({"event": "repos", "root": "/gone", "repo": None})
        for _ in range(50):
            if all(len(v) == 3 for v in got.values()):
                break
            await asyncio.sleep(0.05)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    agent._repos[root] = {"root": root, "ledger": None}  # as a re-read of the bare root leaves it: unread below
    want = reports.omitted(view, omit)
    assert "completed" not in want and "recent" not in want["ledger"]
    assert [e["repo"] for e in got["some"]] == [want, want, None]
    assert [e["repo"] for e in got["whole"]] == [view, view, None]
    assert not agent._sub_omit  # a subscription gone takes its omit with it


def test_the_pages_one_subscriber_asks_for_its_events_and_its_seed_without_what_the_pages_omit(tmp_path, monkeypatch):
    """The UI's fan-out keeps the reading the Org, the Repo page and a card draw, so its subscription,
    its seed and the Inbox's counts keeper all ask for it with the page's omit (TD-754)."""
    import asyncio

    from test_ui_events_light import received

    from shiftlead.ui import app as ui

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    root = str(tmp_path / "samscrape")
    asked: list[tuple[str, object]] = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "repos":
                asked.append(("repos", kw.get("omit")))
                return {root: _reading(root)}
            return {"entries": []} if method == "inbox" else ([] if method == "list" else {})

        async def subscribe(self, omit=None):
            asked.append(("subscribe", omit))
            await asyncio.sleep(0.3)
            return
            yield

    from fastapi.testclient import TestClient

    monkeypatch.setattr(ui, "LocalClient", Fake)
    received(TestClient(ui.create_app()), "/events")
    subs = [o for m, o in asked if m == "subscribe"]
    assert subs and all(o == list(ui.REPOS_OMIT_PAGE) for o in subs)
    assert ("repos", list(ui.REPOS_OMIT_PAGE)) in asked  # the run's seed
    assert ("repos", None) not in asked  # nothing in the stream reads the reading whole


async def test_a_subscribe_again_on_one_connection_without_an_omit_is_sent_repos_whole(agent, tmp_path):
    """A subscribe again says its omit again (TD-765): one connection that subscribed with an `omit`
    and then subscribes with none is sent the second seed and the next `repos` event whole."""
    import asyncio
    import json

    await park_ticks(agent)  # the tick would drop a root the registry does not list, mid-test
    root = str(tmp_path)
    agent._repos[root] = _reading(root)
    omit = ["ledger.recent", "completed"]

    async def next_repos(reader: asyncio.StreamReader) -> dict:
        while True:
            ev = json.loads(await asyncio.wait_for(reader.readline(), 5))
            if ev.get("event") == "repos":
                return ev

    async with LocalClient() as c:
        r, w = c._reader, c._writer
        assert r and w
        w.write((json.dumps({"id": 1, "method": "subscribe", "params": {"omit": omit}}) + "\n").encode())
        await w.drain()
        first = await next_repos(r)
        assert first["repo"] == reports.omitted(agent._repo_view(root), omit)
        w.write((json.dumps({"id": 2, "method": "subscribe", "params": {}}) + "\n").encode())
        await w.drain()
        seed = await next_repos(r)
        await agent._broadcast({"event": "repos", "root": root, "repo": agent._repo_view(root)})
        after = await next_repos(r)
    whole = agent._repo_view(root)
    assert "completed" in whole and whole["ledger"]["recent"]
    assert seed["repo"] == whole
    assert after["repo"] == whole


async def test_a_send_that_fails_drops_the_subscriber_and_its_omit(agent):
    """A send that fails drops the subscriber, and its omit goes with it (TD-765)."""

    class Broken:
        def write(self, data: bytes) -> None:
            raise ConnectionError("gone")

        async def drain(self) -> None:  # pragma: no cover - write raises first
            pass

    w = Broken()
    agent._subscribers[w] = {}
    agent._sub_omit[w] = ("completed",)
    await agent._broadcast({"event": "repos", "root": "/r", "repo": None})
    assert w not in agent._subscribers
    assert not agent._sub_omit
