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
        "nobody's — the grinders' order",
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
    # where no team services the repo the order is the Inbox's, not the grinders'
    assert {x["number"]: x["whose"] for x in teamrun.red_prs(reading(root), [], now())}[802] == "nobody's"


def test_the_facet_counts_the_red_prs_with_a_hover_of_each():
    from shiftlead.ui.app import repo_facet

    root = "/r/samscrape"
    f = repo_facet(reading(root), now(), fleet=[rec("g1", root, git={"branch": "td9"})])["prs"]
    assert [x["number"] for x in f["red"]] == [802, 803, 804]
    assert f["red_title"].splitlines() == [
        "#802 · red 3h 0m · nobody's — the grinders' order",
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


def test_a_sync_prs_row_says_sync_and_its_reason_green_or_red():
    """TD-684, §4.5a *Inbox row: red PR*: a sync PR the home did not merge has the row at once, its
    reason in place of the failing checks."""
    from shiftlead.ui.app import red_pr_rows

    root = "/r/samscrape"
    sync = order(1728, checks="green", failing=[], red_since=None, sync=True, sync_since=_iso(now()), reason="green: review and merge it")  # fmt: skip
    (row,) = red_pr_rows({root: reading(root, orders=[sync])}, [], now())
    assert row["text"] == "samscrape #1728 · sync · green: review and merge it · eye"
    assert row["sid"] == "red_pr:samscrape:1728" and row["at"] == sync["sync_since"]
    assert red_pr_rows({root: reading(root, orders=[sync])}, [rec("g1", root)], now()) == []  # serviced: a lane's


def test_after_the_cut_over_a_forks_sync_draws_the_row_in_a_serviced_repo():
    """TD-2165, §4.5a *Inbox row: red PR*, §4.9c *Two of the five are not seats today*: after the cut-over no job
    takes a fork's sync, so it has the row in a serviced repo too; a sync row with no `fork` is read as a fork's,
    and every other order of a serviced repo still draws none."""
    from shiftlead.ui.app import red_pr_rows

    root = "/r/samscrape"
    since = _iso(now())
    fork = order(1801, checks="green", failing=[], red_since=None, sync=True, sync_since=since, reason="a fork's head", fork=True)  # fmt: skip
    bare = order(1802, checks="green", failing=[], red_since=None, sync=True, sync_since=since, reason="no fork key")  # fmt: skip
    ours = order(1803, checks="green", failing=[], red_since=None, sync=True, sync_since=since, reason="ours", fork=False)  # fmt: skip
    red = order(1804)
    r = {root: reading(root, orders=[fork, bare, ours, red])}
    lane = [rec("g1", root)]
    got = red_pr_rows(r, lane, now(), cut_over=True)
    assert [x["pr"] for x in got] == [1801, 1802]  # a non-fork sync and a red PR are a job's
    assert got[0]["text"] == "samscrape #1801 · sync · a fork's head · eye" and got[0]["sid"] == "red_pr:samscrape:1801"
    assert red_pr_rows(r, lane, now()) == []  # before the cut-over a serviced repo's orders are a lane's, a fork's too
    # a repo nothing services keeps today's rows, every order, cut over or not
    assert [x["pr"] for x in red_pr_rows(r, [], now(), cut_over=True)] == [1801, 1802, 1803, 1804]


@pytest.mark.parametrize("checks", ["green", "pending"])
def test_a_lift_prs_row_says_lift_its_gate_and_its_age(checks):
    """TD-1578, §4.5a *Inbox row: red PR*: a live check's lift PR is an order whatever its checks (§4.4 *A PR the
    gate sweep opens is the team's at once*); its row says *lift*, its age since `lift_since` and the gate it
    lifts, never *conflicting* — the order as `workorders.pr_order` makes it from the reading."""
    from sessionorc import workorders
    from shiftlead.ui.app import red_pr_rows

    root = "/r/samscrape"
    since = _iso(now() - timedelta(hours=2))
    pr = {"number": 1900, "title": "TD-77: lift event (live)", "branch": "lift/TD-77/live", "url": "https://x/1900", "author": "eye", "checks": checks, "failing": [], "conflicting": False, "lift": True, "lift_since": since}  # fmt: skip
    lift = workorders.pr_order(pr)
    assert lift["lift"] and lift["red_since"] is None
    (row,) = red_pr_rows({root: reading(root, orders=[lift])}, [], now())
    assert row["at"] == since and row["age"].startswith("2h")
    assert row["text"] == f"samscrape #1900 · lift {row['age']} · lifts TD-77 event (live) · eye"
    assert red_pr_rows({root: reading(root, orders=[lift])}, [rec("g1", root)], now()) == []  # serviced: a lane's


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
    assert ">red 3h 0m · nobody&#39;s — the grinders&#39; order</span>" in html
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


def test_after_the_cut_over_the_inbox_draws_a_forks_sync_in_a_serviced_repo(tmp_path, monkeypatch):
    """TD-2165: the Inbox page and its count read the cut-over, so a fork's sync in a serviced repo is the person's."""
    from sessionorc import teamstore

    root = str(tmp_path / "samscrape")
    fork = order(1801, checks="green", failing=[], red_since=None, sync=True, sync_since=_iso(now()), reason="a fork's head", fork=True)  # fmt: skip
    c = client(monkeypatch, tmp_path, fake({root: reading(root, orders=[fork, order(802)])}, [rec("g1", root)]))
    assert "samscrape #1801" not in c.get("/inbox").text  # before the cut-over: a lane's
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: True)
    html = c.get("/inbox").text
    assert "samscrape #1801 · sync · a fork&#39;s head · eye" in html and "samscrape #802" not in html
    assert 'data-sid="red_pr:samscrape:1801" data-row="red_pr"' in html
    assert c.get("/api/person/inbox").json()["needs"] == 1  # the count reads the same rows


def test_after_the_cut_over_the_org_page_counts_a_forks_sync_in_a_serviced_repo(tmp_path, monkeypatch):
    """TD-2214: the Org page's top bar reads the cut-over as the Inbox does, so its number counts a fork's sync in a
    serviced repo only after the cut-over, and nothing while the host agent is down."""
    import re

    from fastapi import HTTPException

    from sessionorc import teamstore

    def needs(html: str) -> str:
        return re.search(r'id="personneeds">([^<]*)</span>', html).group(1)

    root = str(tmp_path / "samscrape")
    fork = order(1801, checks="green", failing=[], red_since=None, sync=True, sync_since=_iso(now()), reason="a fork's head", fork=True)  # fmt: skip
    Fake = fake({root: reading(root, orders=[fork, order(802)])}, [rec("g1", root)])
    c = client(monkeypatch, tmp_path, Fake)
    assert needs(c.get("/").text) == ""  # before the cut-over: a lane's, and #802 is serviced
    monkeypatch.setattr(teamstore, "first_shape_off", lambda: True)
    assert needs(c.get("/").text) == "1" == str(c.get("/api/person/inbox").json()["needs"])

    class Down(Fake):
        async def call(self, method, **kw):
            raise HTTPException(503, "the host agent is down")

    down = client(monkeypatch, tmp_path, Down)
    assert needs(down.get("/").text) == ""


# -- a draft is no work order (design §4.4, TD-745) -------------------------------------------------------


def drafted(root: str, **kw) -> dict:
    """The reading with #802 a draft: the home lists no order for it (`workorders.red_prs`)."""
    r = reading(root, orders=[], **kw)
    r["prs"]["open"][1]["draft"] = True
    return r


def test_an_unheld_draft_past_the_bound_says_no_order_while_a_draft_and_a_held_one_its_holder():
    from shiftlead import teamrun

    root = "/r/samscrape"
    got = {x["number"]: x["whose"] for x in teamrun.red_prs(drafted(root), [], now())}
    assert got[802] == "no order while a draft" == teamrun.DRAFT_WHOSE
    held = {x["number"]: x["whose"] for x in teamrun.red_prs(drafted(root, held={"802": ["g1"]}), [], now())}
    assert held[802] == "held by g1"
    young = drafted(root)
    young["prs"]["open"][1]["red_since"] = _iso(now() - timedelta(minutes=20))
    assert {x["number"]: x["whose"] for x in teamrun.red_prs(young, [], now())}[802] == ""
    sync = drafted(root)  # a pending sync draft waits as any sync PR does: no draft's word either
    sync["prs"]["open"][1].update(sync=True, checks="pending")
    assert {x["number"]: x["whose"] for x in teamrun.red_prs(sync, [], now())}[802] == ""


def test_a_draft_is_tagged_on_the_repo_page_counted_red_and_no_inbox_row(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    c = client(monkeypatch, tmp_path, fake({root: drafted(root)}, [rec("g1", root, git={"branch": "td9"})]))
    assert ">red 3h 0m · no order while a draft</span>" in c.get("/repo/samscrape").text
    org = c.get("/").text
    assert ">· 3 red</span>" in org, "the facet still counts it"
    assert "#802 · red 3h 0m · no order while a draft" in org, "and its hover says why"
    assert "samscrape #802" not in c.get("/inbox").text
    assert c.get("/api/person/inbox").json()["needs"] == 0


def test_ao_repo_lists_no_order_for_a_draft_and_says_why_on_its_line(tmp_path, monkeypatch, capsys):
    import subprocess

    from shiftlead import cli

    root = tmp_path / "samscrape"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True)
    r = drafted(str(root))
    r["prs"]["open"][3]["draft"] = True  # #804, red 20m: before the bound, a draft as today
    monkeypatch.setattr(cli, "call_sync", lambda rpc, **kw: {"repos": {str(root): r}, "list": [], "doing_log": {}, "queue": {}, "inbox": {}}[rpc])  # fmt: skip
    monkeypatch.chdir(root)
    assert cli.main(["repo"]) == 0
    out = capsys.readouterr().out
    since = r["prs"]["open"][1]["red_since"]
    assert f"red, nobody's (draft · red since {since}: no order while a draft)" in out
    assert "red, young (draft)" in out
    assert "pr:802" not in out and "red PR" not in out.splitlines()[0]


# -- every PR the gate sweep opens (design §4.4 *A PR the gate sweep opens is the team's at once*, TD-1854) ------


def _gate_prs(since: str) -> list[dict]:
    """A dated lift and a sweep PR as the reading stamps them, both red: an order whatever its checks."""
    return [
        {"number": 1950, "title": "TD-77: lift until 2026-11-20", "branch": "lift/TD-77/until-2026-11-20", "url": "https://x/1950", "author": "eye", "checks": "red", "failing": ["test"], "conflicting": False, "red_since": since, "lift": True, "lift_since": since},
        {"number": 1951, "title": "Gate sweep 2026-11-15 (TD-1376)", "branch": "sweep/2026-11-15", "url": "https://x/1951", "author": "eye", "checks": "green", "failing": [], "conflicting": True, "red_since": since, "sweep": "sweep", "sweep_since": since},
    ]  # fmt: skip


def test_a_dated_lift_and_a_sweep_prs_rows_say_their_word_in_a_repo_no_team_services():
    from sessionorc import workorders
    from shiftlead.ui.app import red_pr_rows

    root = "/r/samscrape"
    since = _iso(now() - timedelta(hours=2))
    orders = [workorders.pr_order(p) for p in _gate_prs(since)]
    lift, sweep = red_pr_rows({root: reading(root, orders=orders)}, [], now())
    assert lift["text"] == f"samscrape #1950 · lift {lift['age']} · lifts TD-77 until 2026-11-20 · eye"
    assert sweep["text"] == f"samscrape #1951 · sweep {sweep['age']} · the gate sweep's board items · eye"
    assert sweep["at"] == since and sweep["sweep"] and "sweep" not in lift
    assert "conflicting" not in sweep["text"]
    assert red_pr_rows({root: reading(root, orders=orders)}, [rec("g1", root)], now()) == []  # serviced: a lane's


def test_an_unserved_repos_rows_are_its_person_orders_whoever_services_it():
    from sessionorc import workorders
    from shiftlead.ui.app import red_pr_rows

    root = "/r/samscrape"
    since = _iso(now() - timedelta(hours=2))
    r = reading(root, orders=[])
    r["seams"] = {"serve": {"ok": False, "lacks": [{"key": "gate", "words": "unserved: no gate"}]}}
    r["pr_orders"]["person"] = [workorders.pr_order(p) for p in _gate_prs(since)]
    # a red order the reading might still hold is never drawn there: only the person's
    r["pr_orders"]["orders"] = [order(802)]
    got = red_pr_rows({root: r}, [rec("g1", root)], now())
    assert [x["pr"] for x in got] == [1950, 1951]


def test_the_gate_sweeps_prs_are_lift_and_sweep_rows_out_of_the_red_count():
    from sessionorc import workorders
    from shiftlead import teamrun
    from shiftlead.ui.app import repo_facet

    root = "/r/samscrape"
    since = _iso(now() - timedelta(hours=2))
    r = reading(root, orders=[])
    live = {"number": 1952, "title": "TD-78: lift live", "branch": "lift/TD-78/live", "url": "https://x/1952", "author": "eye", "checks": "green", "failing": [], "conflicting": False, "red_since": since, "lift": True, "lift_since": since}  # fmt: skip
    r["prs"]["open"] += [*_gate_prs(since), live]
    r["pr_orders"]["gate"] = [1950, 1951, 1952]
    r["pr_orders"]["orders"] = [workorders.pr_order(r["prs"]["open"][4])]  # the lift unheld, the sweep held
    r["pr_orders"]["held"] = {"1951": ["g2"]}
    got = {x["number"]: x for x in teamrun.red_prs(r, [rec("g1", root)], now())}
    assert (got[1950]["word"], got[1950]["since"], got[1950]["whose"]) == (
        "lift",
        since,
        "nobody's — the grinders' order",
    )
    assert got[1950]["what"] == "lifts TD-77 until 2026-11-20" and not got[1950]["live"]
    assert got[1952]["word"] == "lift" and got[1952]["live"]  # a live check's lift (TD-1888)
    assert (got[1951]["word"], got[1951]["whose"], got[1951]["what"]) == (
        "sweep",
        "held by g2",
        "the gate sweep's board items",
    )
    f = repo_facet(r, now(), fleet=[rec("g1", root)])["prs"]
    assert [x["number"] for x in f["red"]] == [802, 803, 804]  # the facet's red count leaves them out
    # a PR not in `pr_orders.gate` (its read open, say) reads as its checks say
    r["pr_orders"]["gate"] = [1950]
    assert {x["number"]: x["word"] for x in teamrun.red_prs(r, [], now())}[1951] == "conflicting"
    # an unserved repo's are the person's
    r["pr_orders"]["gate"] = [1950, 1951]
    r["pr_orders"]["person"] = [workorders.pr_order(p) for p in _gate_prs(since)]
    r["seams"] = {"serve": {"ok": False, "lacks": [{"key": "gate", "words": "unserved: no gate"}]}}
    got = {x["number"]: x["whose"] for x in teamrun.red_prs(r, [rec("g1", root)], now())}
    assert got[1950] == got[1951] == "the person's"


def test_the_repo_page_tags_a_lift_and_a_sweep_pr(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    since = _iso(now() - timedelta(hours=2))
    r = reading(root)
    r["prs"]["open"] += _gate_prs(since)
    r["pr_orders"]["gate"] = [1950, 1951]
    c = client(monkeypatch, tmp_path, fake({root: r}, [rec("g1", root, git={"branch": "td9"})]))
    html = c.get("/repo/samscrape").text
    assert 'class="tag gate" title="lifts TD-77 until 2026-11-20, open since' in html
    assert ">lift 2h 0m · held by" not in html and ">lift 2h 0m</span>" in html
    assert "the gate sweep&#39;s board items, open since" in html and ">sweep 2h 0m</span>" in html
    assert ">· 3 red</span>" in c.get("/").text


def test_a_record_prs_row_and_red_pr_say_its_own_words():
    """§4.4 *The same pass records a design's Go* (TD-2225): the sweep's record PR is a sweep order in words of its
    own, picked by the mark's value, its key words (`sweep`, `sweep_since`) the sweep's."""
    from sessionorc import workorders
    from shiftlead import teamrun
    from shiftlead.ui.app import red_pr_rows

    root = "/r/samscrape"
    since = _iso(now() - timedelta(hours=2))
    pr = {"number": 1960, "title": "reviews: record pass 2026-11-16 — 2 records", "branch": "record/2026-11-16", "url": "https://x/1960", "author": "eye", "checks": "green", "failing": [], "conflicting": False, "red_since": since, "sweep": "record", "sweep_since": since}  # fmt: skip
    (row,) = red_pr_rows({root: reading(root, orders=[workorders.pr_order(pr)])}, [], now())
    assert row["text"] == f"samscrape #1960 · record {row['age']} · the gate sweep's record of designs' Go · eye"
    assert row["sweep"] == "record", "the mark's value is copied on, never True"
    r = reading(root, orders=[])
    r["prs"]["open"] += [pr]
    r["pr_orders"]["gate"] = [1960]
    got = {x["number"]: x for x in teamrun.red_prs(r, [rec("g1", root)], now())}[1960]
    assert (got["word"], got["what"], got["sweep_since"]) == ("sweep", "the gate sweep's record of designs' Go", since)
