# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-1811, design §4.4 *A filing PR nobody holds is a work order* (TD-1804's order half, on TD-1810's
`filing` stamp): the one test `workorders.is_filing_order`, the order and the note in `workorders.red_prs`,
the holders in `red_holders`, the tick's `pr_orders.filing`, and what the pages and `ao repo` read of it."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sessionorc import workorders
from sessionorc.agent_common import FILING_AFTER, ORPHAN_AFTER
from sessionorc.models import ProgressEntry, Session

T0 = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
KEY = ["src/sessionorc/**"]


def _filing(n=3700, created=T0, **kw):
    """A filing PR's row as the reading stamps it (TD-1810): `filing` read at its head, `held` read empty at it."""
    row = {
        "number": n, "title": f"TD-{n} filed: a gap", "url": f"https://github.com/o/r/pull/{n}", "branch": f"td{n}",
        "author": "a", "head": f"sha{n}", "created": created.isoformat() if isinstance(created, datetime) else created, "checks": "green", "failing": [],
        "conflicting": False, "filing": True, "filing_head": f"sha{n}", "held": [], "held_head": f"sha{n}",
        "held_key": list(KEY),
    }  # fmt: skip
    return {**row, **kw}


def _rec(sid="ao-g1", state="idle", **kw):
    return Session(id=sid, name=sid, kind="interactive", adapter="shell", dir="/tmp", state=state, **kw)


def _order(prs, records=(), now=T0 + DAY, told=None, *, key=KEY, reads=None, filing_after=FILING_AFTER):
    return workorders.red_prs(
        prs, list(records), now, told or {}, ORPHAN_AFTER, filing_after=filing_after, key=key, reads=reads
    )


# -- the one test --------------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("checks", ["green", "pending", "none"])
def test_a_filing_pr_green_pending_or_with_no_checks_passes_once_open_a_day(checks):
    pr = _filing(checks=checks)
    assert workorders.is_filing_order(pr, T0 + DAY, FILING_AFTER, KEY, {})
    assert not workorders.is_filing_order(pr, T0 + DAY - timedelta(seconds=1), FILING_AFTER, KEY, {})


@pytest.mark.unit
@pytest.mark.parametrize(
    "change",
    [
        {"checks": "red", "red_since": T0.isoformat()},  # the red rule's alone
        {"checks": "not_run"},  # CI that never started is the person's
        {"conflicting": True, "red_since": T0.isoformat()},
        {"draft": True},
        {"fork": True},
        {"sync": True, "sync_since": T0.isoformat()},
        {"branch": "lift/TD-9/live", "lift": True, "lift_since": T0.isoformat()},
        {"filing": False},
        {"filing_head": "older"},  # `filing` read at another head: not yet read at this one
        {"held_head": "older"},  # `held` unread at this head
        {"held_key": ["docs/briefs/**"]},  # `held` read at another key
        {"held": ["src/sessionorc/x.py"]},  # touches a held path: the reader's
        {"created": None},
        {"created": "not a stamp"},
    ],
)
def test_a_row_the_rule_does_not_take_is_no_filing_order(change):
    assert not workorders.is_filing_order(_filing(**change), T0 + 2 * DAY, FILING_AFTER, KEY, {})


@pytest.mark.unit
def test_with_no_key_a_fresh_held_is_not_needed_but_a_kept_non_empty_held_is_never_one():
    unread = _filing(held_head=None, held_key=None)
    unread.pop("held")
    assert workorders.is_filing_order(unread, T0 + DAY, FILING_AFTER, [], {})
    assert not workorders.is_filing_order(unread, T0 + DAY, FILING_AFTER, KEY, {})  # under a key it waits
    kept = _filing(held=["src/sessionorc/x.py"], held_head="older")
    assert not workorders.is_filing_order(kept, T0 + DAY, FILING_AFTER, [], {})


@pytest.mark.unit
def test_an_open_read_of_the_pr_any_addressees_keeps_it_off_and_a_closed_one_does_not():
    for to in ("ao-shiftlead-techlead-ao-1", "person"):
        reads = {"3700": [{"id": "m-1", "to": to, "state": "open", "verdict": ""}]}
        assert not workorders.is_filing_order(_filing(), T0 + DAY, FILING_AFTER, KEY, reads)
    closed = {"3700": [{"id": "m-1", "to": "person", "state": "answered", "verdict": "pass"}]}
    assert workorders.is_filing_order(_filing(), T0 + DAY, FILING_AFTER, KEY, closed)
    assert workorders.is_filing_order(_filing(), T0 + DAY, FILING_AFTER, KEY, {"9": [{"state": "open"}]})


# -- the order and the note ------------------------------------------------------------------------------


@pytest.mark.unit
def test_an_unheld_filing_pr_is_a_medium_order_after_the_red_ones_once_open_a_day():
    red = {"number": 9, "title": "red", "branch": "b9", "checks": "red", "failing": ["t"], "red_since": T0.isoformat()}
    assert _order([_filing()], now=T0 + DAY - timedelta(seconds=1)) == ([], {}, [])
    orders, told, notes = _order([_filing(), red])
    assert [o["id"] for o in orders] == ["pr:9", "pr:3700"]
    o = orders[1]
    assert (o["priority"], o["filing"], o["filing_since"], o["pickable"], o["pr_order"]) == (
        "Medium",
        True,
        T0.isoformat(),
        "yes",
        True,
    )
    assert o["context"] == (
        "https://github.com/o/r/pull/3700 · filing, open since 2026-11-13, nobody holds it:"
        " review and merge it, or close it if superseded"
    )
    assert (told, notes) == ({}, [])
    assert not orders[0].get("filing") and orders[0]["priority"] == "High"


@pytest.mark.unit
def test_no_filing_after_no_filing_order_so_the_existing_callers_stand():
    assert workorders.red_prs([_filing()], [], T0 + 2 * DAY, {}, ORPHAN_AFTER) == ([], {}, [])
    assert workorders.red_holders([_filing()], [_rec(git={"branch": "td3700"})], T0 + 2 * DAY, ORPHAN_AFTER) == {}


@pytest.mark.unit
def test_a_red_filing_pr_is_one_red_order_not_two():
    red = _filing(checks="red", failing=["test"], red_since=(T0 + DAY).isoformat())
    (o,) = _order([red], now=T0 + DAY + ORPHAN_AFTER)[0]
    assert not o.get("filing") and o["priority"] == "High" and o["context"].endswith(" · test")


@pytest.mark.unit
def test_a_held_filing_pr_is_no_order_while_its_holder_works():
    for r in (
        _rec(state="working", git={"branch": "td3700"}),
        _rec(state="working", progress=[ProgressEntry(ref="pr:3700")]),
        _rec(state="working", progress=[ProgressEntry(ref="TD-1", review_pr=3700)]),
    ):
        assert _order([_filing()], [r], now=T0 + 3 * DAY) == ([], {}, [])


@pytest.mark.unit
def test_an_idle_holder_is_told_once_and_orphan_after_later_it_is_an_order():
    holder = _rec(git={"branch": "td3700"})
    orders, told, notes = _order([_filing()], [holder])
    assert orders == [] and [(sid, p["number"]) for sid, p in notes] == [("ao-g1", 3700)]
    assert told == {"3700": {"red_since": T0.isoformat(), "at": (T0 + DAY).isoformat()}}
    note = workorders.pr_note(notes[0][1])
    assert note == f"filing PR #3700 has been open since {T0.isoformat()}: merge it or say why"
    assert _order([_filing()], [holder], now=T0 + DAY + ORPHAN_AFTER - timedelta(seconds=1), told=told) == (
        [],
        told,
        [],
    )
    orders, kept, notes = _order([_filing()], [holder], now=T0 + DAY + ORPHAN_AFTER, told=told)
    assert [o["id"] for o in orders] == ["pr:3700"] and kept == told and notes == []


@pytest.mark.unit
def test_the_memory_stays_while_the_row_is_a_filing_row_and_goes_when_it_is_not():
    holder = _rec(git={"branch": "td3700"})
    told = _order([_filing()], [holder])[1]
    moved = _filing(head="new")  # a new head, not yet read again: no order, no note, the memory kept
    assert _order([moved], [holder], now=T0 + 2 * DAY, told=told) == ([], told, [])
    # turned red: the red rule's spell, another stamp, so the filing memory goes
    red = _filing(checks="red", red_since=(T0 + 2 * DAY).isoformat())
    assert _order([red], [holder], now=T0 + 2 * DAY, told=told)[1] == {}


@pytest.mark.unit
def test_the_holders_of_a_filing_pr_are_named_once_the_test_passes():
    on_head = _rec("ao-h", state="working", git={"branch": "td3700"})
    kw = {"filing_after": FILING_AFTER, "key": KEY, "reads": {}}
    assert workorders.red_holders([_filing()], [on_head], T0 + DAY, ORPHAN_AFTER, **kw) == {"3700": ["ao-h"]}
    assert workorders.red_holders([_filing()], [on_head], T0 + DAY - timedelta(seconds=1), ORPHAN_AFTER, **kw) == {}


# -- the tick ----------------------------------------------------------------------------------------------


async def test_the_tick_orders_an_unheld_filing_pr_and_lists_its_number(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    root = str(tmp_path / "repo")
    agent._repos[root] = {"name": "repo", "root": root, "prs": {"open": [_filing(held_key=[])]}}
    await agent._red_prs(T0 + DAY - timedelta(seconds=1))
    po = agent._repos[root].get("pr_orders") or {}
    assert not po.get("orders") and not po.get("filing")
    await agent._red_prs(T0 + DAY)
    po = agent._repos[root]["pr_orders"]
    assert [o["id"] for o in po["orders"]] == ["pr:3700"] and po["filing"] == [3700]


async def test_a_change_to_the_filing_list_alone_is_saved(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    root = str(tmp_path / "repo")
    worker = _rec("ao-w", state="working", git={"branch": "td3700"}, repo=root, host=agent.host)
    agent.sessions[worker.id] = worker
    agent._repos[root] = {"name": "repo", "root": root, "prs": {"open": [_filing(held_key=[])]}}
    agent._repos[root]["pr_orders"] = {"orders": [], "told": {}, "held": {"3700": ["ao-w"]}}
    await agent._red_prs(T0 + DAY)
    po = agent._repos[root]["pr_orders"]
    assert po["orders"] == [] and po["filing"] == [3700] and po["held"] == {"3700": ["ao-w"]}


async def test_an_unserved_repo_has_no_filing_order_and_an_empty_filing_list(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    root = str(tmp_path / "repo")
    holder = _rec("ao-holder", git={"branch": "td3700"}, repo=root, host=agent.host)
    agent.sessions[holder.id] = holder
    lacks = [{"key": "gate", "words": "unserved: no gate (no scripts/check_cadence.py) — cure"}]
    agent._repos[root] = {
        "name": "repo", "root": root, "prs": {"open": [_filing(held_key=[])]},
        "seams": {"serve": {"ok": False, "lacks": lacks}},
    }  # fmt: skip
    await agent._red_prs(T0 + 2 * DAY)
    po = agent._repos[root].get("pr_orders") or {}
    assert not po.get("orders") and not po.get("filing") and not po.get("held")
    assert not [e for e in agent.sessions["ao-holder"].inbox if e.from_ == "system"]


# -- the pages and `ao repo` ----------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _reading(root: str, *, orders: list | None = None, held: dict | None = None) -> dict:
    created = (_now() - timedelta(days=3)).isoformat()
    pr = {**_filing(created=_now() - timedelta(days=3)), "url": "https://x/3700"}
    red = {"number": 802, "title": "red one", "created": created, "author": "eye", "branch": "r", "url": "https://x/802", "checks": "red", "failing": ["test"], "conflicting": False, "red_since": (_now() - timedelta(hours=3)).isoformat()}  # fmt: skip
    order = workorders.pr_order(pr)
    return {
        "name": "samscrape", "root": root, "remote": "git@github.com:eye/samscrape.git",
        "ledger": {"path": "docs/ledger", "entries": [], "by_priority": {}, "by_kind": {}},
        "prs": {"open": [pr, red], "windows": {w: {"opened": 1, "closed": 1} for w in ("day", "week", "month")}},
        "pr_orders": {"orders": [order] if orders is None else orders, "told": {}, "held": held or {}, "filing": [3700]},
        "at": _now().isoformat(),
    }  # fmt: skip


def _member(sid: str, root: str, **kw) -> dict:
    return {"id": sid, "name": sid, "state": "working", "kind": "agent", "team": "grind", "repo": root, "dir": root, "unattended": True, **kw}  # fmt: skip


@pytest.mark.unit
def test_the_pages_row_says_filing_and_whose_it_is():
    from shiftlead import teamrun

    root = "/r/samscrape"
    r = _reading(root)
    got = {x["number"]: x for x in teamrun.red_prs(r, [_member("g1", root)], _now())}
    assert sorted(got) == [802, 3700]
    f = got[3700]
    assert (f["word"], f["whose"]) == ("filing", "nobody's — the grinders' order")
    assert f["since"] == f["filing_since"] == r["prs"]["open"][0]["created"]
    assert got[802]["since"] == got[802]["red_since"]
    held = teamrun.red_prs(_reading(root, orders=[], held={"3700": ["g1"]}), [_member("g1", root)], _now())
    assert {x["number"]: x["whose"] for x in held}[3700] == "held by g1"
    # the pages list exactly the reading's numbers (TD-652): a row not in `pr_orders.filing` is none
    r = _reading(root)
    r["pr_orders"]["filing"] = []
    assert [x["number"] for x in teamrun.red_prs(r, [], _now())] == [802]


@pytest.mark.unit
def test_the_facet_leaves_a_filing_pr_out_of_its_red_count_and_no_inbox_row_is_drawn():
    from shiftlead.ui.app import red_pr_rows, repo_facet

    root = "/r/samscrape"
    f = repo_facet(_reading(root), _now(), fleet=[_member("g1", root)])["prs"]
    assert [x["number"] for x in f["red"]] == [802] and "3700" not in f["red_title"]
    assert red_pr_rows({root: _reading(root)}, [], _now()) == []  # a repo no team services: still no row


def _fake(repos, fleet):
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "inbox":
                return {"id": "person", "entries": [], "threads": {}, "sends": [], "unread": 0}
            return {"repos": repos, "doing_log": {}, "list": fleet, "usage": {}, "host": {"name": "kmaster"}}.get(
                method, {}
            )

    return Fake


@pytest.mark.unit
def test_the_repo_pages_review_row_draws_a_filing_tag_not_red_styled(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    root = str(tmp_path / "samscrape")
    monkeypatch.setattr(ui, "LocalClient", _fake({root: _reading(root)}, [_member("g1", root)]))
    html = TestClient(ui.create_app()).get("/repo/samscrape").text
    since = _reading(root)["prs"]["open"][0]["created"][:10]
    tag = f'<span class="tag filing" title="ledger and board files only, open since {since}">filing 3d'
    assert tag in html and "· nobody&#39;s — the grinders&#39; order</span>" in html.split(tag)[1][:80]
    assert 'class="tag red" title="test">red 3h' in html


@pytest.mark.unit
def test_ao_repo_prints_a_filing_order_on_its_own_line_and_counts_it_apart(tmp_path, monkeypatch, capsys):
    from shiftlead import cli

    root = tmp_path / "samscrape"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True)
    red = workorders.pr_order({"number": 802, "title": "red one", "checks": "red", "failing": ["test"], "red_since": "2026-11-13T09:00:00+00:00"})  # fmt: skip
    r = _reading(str(root))
    r["pr_orders"]["orders"] = [red, *r["pr_orders"]["orders"]]
    reading = {str(root): r}
    monkeypatch.setattr(cli, "call_sync", lambda rpc, **kw: {"repos": reading, "list": [], "doing_log": {}, "queue": {}, "inbox": {}}[rpc])  # fmt: skip
    monkeypatch.chdir(root)
    assert cli.main(["repo"]) == 0
    out = capsys.readouterr().out
    assert "1 red PR nobody holds, 1 filing PR nobody holds" in out.splitlines()[0]
    since = r["prs"]["open"][0]["created"][:10]
    line = (
        f"pickable     pr:3700  Medium  grinders     TD-3700 filed: a gap · filing, open since {since}: nobody holds it"
    )
    assert line in out and out.index("pr:802") < out.index("pr:3700")
    assert cli.main(["--json", "repo"]) == 0
    (got,) = json.loads(capsys.readouterr().out)
    (o,) = [x for x in got["pr_orders"]["orders"] if x["id"] == "pr:3700"]
    assert o["filing"] is True and o["filing_since"] == r["prs"]["open"][0]["created"]
    (row,) = [p for p in got["prs"]["open"] if p["number"] == 3700]
    assert row["filing"] is True and row["filing_head"] == "sha3700"


# -- the briefs -------------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_the_grinder_brief_carries_the_filing_takers_path():
    from pathlib import Path

    text = (Path(__file__).parents[1] / "src/shiftlead/briefs/grinder.md").read_text()
    start = text.index("**A filing PR** (a `pr:<n>` order marked *filing*")
    path = text[start : text.index("**Out of work**", start)]
    for step in ("`cadence-stack:`", "`ao td reserve`", "`board_edit.py replay`", "fact-check it always at the head",
                 "`ao pr held <n>`", "never a drop that leaves the PR open", "`ao progress done pr:<n> --pr <n>`"):  # fmt: skip
        assert step in path, step


@pytest.mark.unit
def test_every_brief_of_a_session_that_files_by_pr_says_a_filing_pr_left_open_is_a_draft():
    from pathlib import Path

    root = Path(__file__).parents[1]
    said = "A filing PR you mean to leave open past a day is a draft, or a lane takes it"
    briefs = [f"src/shiftlead/briefs/{b}.md" for b in ("grinder", "designer", "entry", "hunter", "sweeper", "auditor")]
    briefs += [f"docs/briefs/{b}.md" for b in ("docs-audit", "test-audit", "designer-ao-1")]
    for b in briefs:
        assert said in (root / b).read_text(), b
    assert "files you mean to leave open past a day is a draft, or a lane takes it" in (root / "AGENTS.md").read_text()
