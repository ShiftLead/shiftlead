"""TD-746: a page asks the host agent for the `repos` reading without the parts it never draws (the RPC's
`omit`), and what it draws from that reading is what it drew from the whole one."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest
from test_ui_entry import client, fake, world

from sessionorc import reports
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


async def test_the_repos_rpc_serves_each_reading_without_what_omit_names(agent, tmp_path):
    root = str(tmp_path)
    agent._repos[root] = _reading(root)
    async with LocalClient() as c:
        assert await c.call("repos") == {root: agent._repos[root]}  # no omit: whole, as ever
        got = await c.call("repos", omit=["ledger.recent", "prs.recent.head", "completed"])
    assert set(got[root]) == set(agent._repos[root]) - {"completed"}
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
            return await super().call(method, **kw)

    return Fake


PAGES = [
    ("/", "REPOS_OMIT_PAGE"),
    ("/repo/samscrape", "REPOS_OMIT_PAGE"),
    ("/api/sessions", "REPOS_OMIT_PAGE"),
    ("/inbox", "REPOS_OMIT_INBOX"),
    ("/api/person/inbox", "REPOS_OMIT_INBOX"),
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
