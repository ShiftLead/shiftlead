# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-618 slice 4, design §4.4 *A red PR nobody holds is a work order* (TD-613) on the pages: the
facet's *· n red* and its hover, the Repo page's Open PRs tags, a claimed `pr:<n>`'s title in TDs in
motion, and the Inbox's *red PR* row for a repo no team services (§4.5a *Inbox row: red PR*)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def now() -> datetime:
    """The clock read at each use: a module-level instant goes stale across a long suite run and the
    pages' ages, read on their own clock, then drift from it."""
    return datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.isoformat()


def order(n: int, **kw) -> dict:
    return {"id": f"pr:{n}", "pr": n, "title": f"PR {n}", "priority": "High", "pr_order": True, "work_order": True, "url": f"https://x/{n}", "author": "eye", "checks": "red", "failing": ["test"], "red_since": _iso(now() - timedelta(hours=3)), **kw}  # fmt: skip


def reading(root: str, orders: list[dict] | None = None, held: dict | None = None) -> dict:
    return {
        "name": "samscrape",
        "root": root,
        "remote": "git@github.com:eye/samscrape.git",
        "ledger": {"path": "docs/technical_debt.md", "entries": [], "by_priority": {}, "by_kind": {}},
        "prs": {
            "open": [
                {"number": 801, "title": "green one", "created": _iso(now() - timedelta(days=3)), "author": "eye", "branch": "g", "url": "https://x/801", "checks": "green", "failing": [], "conflicting": False},
                {"number": 802, "title": "red, nobody's", "created": _iso(now() - timedelta(days=2)), "author": "eye", "branch": "r", "url": "https://x/802", "checks": "red", "failing": ["test", "lint"], "conflicting": False, "red_since": _iso(now() - timedelta(hours=3))},
                {"number": 803, "title": "conflicting, held", "created": _iso(now() - timedelta(days=1)), "author": "eye", "branch": "td9", "url": "https://x/803", "checks": "green", "failing": [], "conflicting": True, "red_since": _iso(now() - timedelta(hours=2))},
                {"number": 804, "title": "red, young", "created": _iso(now() - timedelta(hours=1)), "author": "eye", "branch": "y", "url": "https://x/804", "checks": "red", "failing": ["test"], "conflicting": False, "red_since": _iso(now() - timedelta(minutes=20))},
            ],
            "windows": {w: {"opened": 1, "closed": 1} for w in ("day", "week", "month")},
        },
        "pr_orders": {"orders": orders if orders is not None else [order(802)], "told": {}, "held": {"803": ["g1"]} if held is None else held},
        "at": _iso(now()),
    }  # fmt: skip


def rec(sid: str, root: str, **kw) -> dict:
    return {"id": sid, "name": sid, "state": "working", "kind": "agent", "team": "grind", "repo": root, "dir": root, "unattended": True, **kw}  # fmt: skip


def test_the_red_prs_say_their_word_and_past_the_bound_whose_they_are():
    from shiftlead import teamrun

    root = "/r/samscrape"
    holder = rec("g1", root, git={"branch": "td9"})
    got = {x["number"]: x for x in teamrun.red_prs(reading(root), [holder], now())}
    assert sorted(got) == [802, 803, 804]  # a green PR is never one
    assert (got[802]["word"], got[802]["whose"], got[802]["failing"]) == (
        "red",
        "nobody's — the anchor's order",
        ["test", "lint"],
    )
    assert (got[803]["word"], got[803]["whose"]) == ("conflicting", "held by g1")
    assert got[804]["whose"] == ""  # before ORPHAN_AFTER nobody's order and nobody's to name
    # the holders are the reading's (`pr_orders.held`, TD-652): the page re-derives nothing from the records
    assert {x["number"]: x["whose"] for x in teamrun.red_prs(reading(root, held={}), [holder], now())}[803] == ""
    two = reading(root, held={"803": ["g3", "g4"]})
    assert {x["number"]: x["whose"] for x in teamrun.red_prs(two, [], now())}[803] == "held by g3, g4"
    # a stamp with no offset is read as UTC, never a page's TypeError (review of #1668)
    naive = reading(root)
    naive["prs"]["open"][1]["red_since"] = (now() - timedelta(hours=3)).replace(tzinfo=None).isoformat()
    assert {x["number"]: x["whose"] for x in teamrun.red_prs(naive, [holder], now())}[802].startswith("nobody's")
    # where no team services the repo the order is the Inbox's, not the anchor's
    assert {x["number"]: x["whose"] for x in teamrun.red_prs(reading(root), [], now())}[802] == "nobody's"


def test_the_facet_counts_the_red_prs_with_a_hover_of_each():
    from shiftlead.ui.app import repo_facet

    root = "/r/samscrape"
    f = repo_facet(reading(root), now(), fleet=[rec("g1", root, git={"branch": "td9"})])["prs"]
    assert [x["number"] for x in f["red"]] == [802, 803, 804]
    assert f["red_title"].splitlines() == [
        "#802 · red 3h 0m · nobody's — the anchor's order",
        "#803 · conflicting 2h 0m · held by g1",
        "#804 · red 20m",
    ]
    assert repo_facet({**reading(root), "prs": {"open": []}}, now())["prs"]["red"] == []


def test_a_claimed_red_pr_is_in_motion_with_the_prs_title():
    from shiftlead.ui.app import motion_rows

    root = "/r/samscrape"
    m = rec("g1", root, progress=[{"ref": "pr:803", "status": "claimed"}])
    (row,) = motion_rows([m], reading(root, orders=[]))
    assert (row["ref"], row["title"]) == ("pr:803", "conflicting, held")
    m2 = rec("g2", root, progress=[{"ref": "pr:802", "status": "claimed"}])
    assert motion_rows([m2], reading(root))[0]["title"] == "PR 802"  # the order's own title while listed


def test_red_pr_rows_are_for_a_repo_no_team_services_alone():
    from shiftlead.ui.app import inbox_sections, red_pr_rows

    root = "/r/samscrape"
    (row,) = red_pr_rows({root: reading(root)}, [], now())
    assert row["row"] == "red_pr" and row["sid"] == "red_pr:samscrape:802" and row["url"] == "https://x/802"
    assert row["text"] == "samscrape #802 · red 3h 0m · test · eye" and row["subject"] == "red PR · samscrape #802"
    assert red_pr_rows({root: reading(root)}, [rec("g1", root, state="exited")], now()) == []  # a team services it
    assert red_pr_rows({root: reading(root, orders=[])}, [], now()) == []
    s = inbox_sections([], states=[row])
    assert [e["row"] for e in s["needs"]] == ["red_pr"]
    until = (now() + timedelta(days=1)).isoformat()
    s = inbox_sections([], states=[row], attention_snoozed={"red_pr:samscrape:802|red_pr": until})
    assert s["needs"] == [] and [e["row"] for e in s["snoozed"]] == ["red_pr"]
    # a snooze stored with no offset is UTC, never a TypeError for the whole Inbox (the UI check of #1668)
    s = inbox_sections([], states=[row], attention_snoozed={"red_pr:samscrape:802|red_pr": "2099-01-01"})
    assert s["needs"] == [] and [e["row"] for e in s["snoozed"]] == ["red_pr"]


def fake(repos, fleet):
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


def client(monkeypatch, tmp_path, Fake):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    return TestClient(ui.create_app())


def test_the_repo_page_tags_the_red_prs_and_the_card_marks_them(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    fleet = [rec("g1", root, git={"branch": "td9"})]
    c = client(monkeypatch, tmp_path, fake({root: reading(root)}, fleet))
    html = c.get("/repo/samscrape").text
    assert ">red 3h 0m · nobody&#39;s — the anchor&#39;s order</span>" in html
    assert ">conflicting 2h 0m · held by g1</span>" in html and ">red 20m</span>" in html
    assert 'title="test, lint"' in html
    assert ">· 3 red</span>" in c.get("/").text


def test_the_inbox_draws_the_row_with_open_and_snooze_and_counts_it(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    c = client(monkeypatch, tmp_path, fake({root: reading(root)}, []))
    html = c.get("/inbox").text
    assert "samscrape #802 · red 3h 0m · test · eye" in html
    assert 'data-sid="red_pr:samscrape:802" data-row="red_pr" data-when="1w"' in html
    assert 'href="https://x/802" target="_blank" rel="noopener" title="the pull request, on its forge">Open</a>' in html
    assert c.get("/api/person/inbox").json()["needs"] == 1
