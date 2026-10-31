# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-1292, design §4.5 screen 11 *Review*, §4.5a *Repo page, Review* and *Inbox row: fork's PR* (TD-1285): a
fork's PR ready to precheck carries the person's `--fork-ok` line (`cadence.precheck_person`), drawn on its
Repo page row with **Copy** and **diff ↗**, and is a counted row for the person — a Do item on the card whose
entry its title names, else under the Inbox's *Needs you*. No session is ever given the line."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def now() -> datetime:
    return datetime.now(UTC)


def _iso(t: datetime) -> str:
    return t.isoformat()


LINE = "cd /r/samscrape && agent-cadence run precheck.py --pr 901 --fork-ok"


def fork_row(n: int = 901, **kw) -> dict:
    """An open fork's PR ready to precheck, as `_fork_lines` leaves it on a checkout's reading."""
    return {"number": n, "title": "TD-10 slice 2: a stranger's fix", "created": _iso(now() - timedelta(hours=5)), "author": "stranger", "branch": "patch-1", "url": f"https://github.com/eye/samscrape/pull/{n}", "state": "open", "checks": "green", "failing": [], "conflicting": False, "draft": False, "fork": True, "prechecked": False, "precheck_line": LINE.replace("901", str(n)), **kw}  # fmt: skip


def reading(root: str, *rows: dict) -> dict:
    return {
        "name": "samscrape",
        "root": root,
        "remote": "git@github.com:eye/samscrape.git",
        "ledger": {"path": "docs/ledger", "entries": [], "by_priority": {}, "by_kind": {}},
        "prs": {"open": list(rows), "windows": {w: {"opened": 1, "closed": 1} for w in ("day", "week", "month")}},
        "pr_orders": {"orders": [], "told": {}, "held": {}},
        "at": _iso(now()),
    }


def rec(sid: str, root: str, **kw) -> dict:
    return {"id": sid, "name": sid, "state": "working", "kind": "agent", "team": "grind", "repo": root, "dir": root, "unattended": True, **kw}  # fmt: skip


# -- the line (Fix 1) -------------------------------------------------------------------------------------


def pinned_root(tmp_path: Path) -> Path:
    root = tmp_path / "pinned repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "cadence.toml").write_text('[agent-cadence]\nref = "0123456789abcdef0123456789abcdef01234567"\n')
    return root


def test_the_persons_line_in_a_pinned_repo_is_the_console_script_led_by_cd(tmp_path, monkeypatch):
    from sessionorc import cadence

    root = pinned_root(tmp_path)
    monkeypatch.setattr(cadence, "tree", lambda *a, **k: pytest.fail("the line never resolves the tree"))
    assert cadence.pinned(root)
    assert cadence.precheck_person(root, 7) == f"cd '{root}' && agent-cadence run precheck.py --pr 7 --fork-ok"
    # a session's line is unchanged: the home venv's launcher, with no --fork-ok
    assert "--fork-ok" not in cadence.precheck_typed(root, 7)


def test_the_persons_line_unpinned_is_the_layouts_script_or_none(tmp_path):
    from sessionorc import cadence

    root = tmp_path / "plain"
    (root / "scripts").mkdir(parents=True)
    assert cadence.precheck_person(root, 7) is None, "no script on disk, no line"
    (root / "scripts" / "precheck.py").write_text("")
    assert cadence.precheck_person(root, 7) == f"cd {root} && python3 scripts/precheck.py --pr 7 --fork-ok"


# -- the reading (Fix 2) ----------------------------------------------------------------------------------


def test_each_checkout_of_one_remote_gets_its_own_roots_line_and_the_shared_reading_is_untouched(tmp_path):
    from sessionorc.agent_tick import TickMixin

    a, b = pinned_root(tmp_path / "a"), pinned_root(tmp_path / "b")
    plain = {"number": 5, "fork": False, "prechecked": False, "checks": "green"}
    shared = {"open": [{"number": 4, "fork": True, "prechecked": False, "checks": "green"}, plain], "at": "x"}
    got_a, got_b = TickMixin._fork_lines(str(a), shared), TickMixin._fork_lines(str(b), shared)
    assert got_a["open"][0]["precheck_line"].startswith(f"cd '{a}' && ")
    assert got_b["open"][0]["precheck_line"].startswith(f"cd '{b}' && ")
    assert "precheck_line" not in shared["open"][0], "the shared reading is copied, never written"
    assert "precheck_line" not in got_a["open"][1], "a PR that is not a fork's has no line"
    # a GitLab row carries no `prechecked`: no line
    gitlab = {"open": [{"number": 4, "fork": True, "checks": "green"}]}
    assert "precheck_line" not in TickMixin._fork_lines(str(a), gitlab)["open"][0]
    assert TickMixin._fork_lines(str(a), {"error": "gh down"}) == {"error": "gh down"}


# -- ready to precheck, and whose (Fixes 3, 4) ------------------------------------------------------------


def test_ready_to_precheck_is_a_green_unprechecked_fork_with_a_line():
    from shiftlead import teamrun

    assert teamrun.ready_to_precheck(fork_row())
    for kw in (
        {"prechecked": True},
        {"checks": "red"},
        {"checks": "pending"},
        {"checks": "none"},
        {"checks": "not_run"},
        {"draft": True},
        {"conflicting": True},
        {"fork": False},
        {"sync": True},
        {"precheck_line": None},
    ):
        assert not teamrun.ready_to_precheck(fork_row(**kw)), kw
    gitlab = fork_row()
    del gitlab["prechecked"]
    assert not teamrun.ready_to_precheck(gitlab), "a GitLab row cannot say: never ready"


def test_a_red_fork_pr_past_the_bound_is_its_authors_a_draft_too():
    from shiftlead import teamrun

    root = "/r/samscrape"
    red = fork_row(checks="red", failing=["test"], red_since=_iso(now() - timedelta(hours=3)))
    draft = fork_row(902, draft=True, conflicting=True, red_since=_iso(now() - timedelta(hours=3)))
    got = {x["number"]: x["whose"] for x in teamrun.red_prs(reading(root, red, draft), [rec("g1", root)], now())}
    assert got == {901: "its author's", 902: "its author's"} and teamrun.FORK_WHOSE == "its author's"


# -- the Repo page (Fix 5) --------------------------------------------------------------------------------


def test_pr_rows_tag_a_fork_and_give_the_line_while_ready():
    from shiftlead.ui.repo import FORK_TITLE, pr_rows

    root = "/r/samscrape"
    ready, none = fork_row(), fork_row(902, checks="none", precheck_line=LINE)
    rows = {r["number"]: r for r in pr_rows(reading(root, ready, none), [], {}, now(), home="kmaster")}
    assert rows[901]["fork_line"] == {
        "line": LINE,
        "diff": "https://github.com/eye/samscrape/pull/901/files",
        "title": "type it in a terminal on kmaster, where /r/samscrape is",
    }
    assert rows[901]["fork"]["title"] == FORK_TITLE
    assert rows[902]["fork_line"] is None and rows[902]["fork"]["title"].endswith("no CI on this head yet")
    red = pr_rows(reading(root, fork_row(checks="red")), [], {}, now())[0]
    assert red["fork"]["title"].endswith("may be waiting for your approval on the forge")


def fake(repos, fleet, host=None):
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
            return {"repos": repos, "doing_log": {}, "list": fleet, "usage": {}, "host": host or {"name": "kmaster", "home": "kmaster"}}.get(method, {})  # fmt: skip

    return Fake


def client(monkeypatch, tmp_path, Fake):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    return TestClient(ui.create_app())


def test_the_repo_page_draws_the_fork_tag_the_line_copy_and_the_diff(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    c = client(monkeypatch, tmp_path, fake({root: reading(root, fork_row())}, [rec("g1", root)]))
    html = c.get("/repo/samscrape").text
    assert '<span class="tag fork" title="a fork&#39;s PR: its CI runs' in html
    assert "yours, after reading the diff:" in html
    assert f'data-copy="{LINE.replace("&", "&amp;")}">Copy</button>' in html
    assert 'href="https://github.com/eye/samscrape/pull/901/files" target="_blank" rel="noopener">diff ↗</a>' in html
    assert "type it in a terminal on kmaster, where" in html
    gone = client(monkeypatch, tmp_path, fake({root: reading(root, fork_row(prechecked=True))}, []))
    assert "yours, after reading the diff:" not in gone.get("/repo/samscrape").text, "a precheck status takes the line"


# -- the Inbox row (Fix 6) --------------------------------------------------------------------------------


def test_fork_pr_rows_in_a_serviced_and_an_unserviced_repo_one_per_checkout():
    from shiftlead.ui.app import fork_pr_rows

    a, b = "/r/samscrape", "/w/samscrape"
    ra, rb = reading(a, fork_row()), reading(b, fork_row(precheck_line=LINE.replace("/r/", "/w/")))
    rows = fork_pr_rows({a: ra, b: rb}, [rec("g1", a)], "kmaster", now())
    assert [r["line"] for r in rows] == [LINE, LINE.replace("/r/", "/w/")], "each checkout its own root's line"
    row = rows[0]
    assert row["text"] == "samscrape #901 · fork · CI green · stranger"
    assert (row["row"], row["sid"], row["id"]) == ("fork_pr", "fork_pr:samscrape:901", "fork_pr:samscrape:901")
    assert row["url"].endswith("/pull/901/files") and row["at"] == ra["prs"]["open"][0]["created"]
    assert row["line_title"] == "type it in a terminal on kmaster, where /r/samscrape is"
    assert row["subject"] == "fork's PR · samscrape #901"
    assert fork_pr_rows({a: reading(a, fork_row(prechecked=True))}, [], "kmaster", now()) == []


def test_the_inbox_draws_the_fork_row_counted_with_copy_open_and_snooze(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    row = fork_row(title="no entry named here", precheck_line="cd x && agent-cadence run precheck.py --pr 901 --fork-ok")
    c = client(monkeypatch, tmp_path, fake({root: reading(root, row)}, [rec("g1", root)]))
    html = c.get("/inbox").text
    assert "samscrape #901 · fork · CI green · stranger" in html
    assert 'data-copy="cd x &amp;&amp; agent-cadence run precheck.py --pr 901 --fork-ok"' in html
    assert 'data-sid="fork_pr:samscrape:901" data-row="fork_pr" data-when="1w"' in html
    assert 'href="https://github.com/eye/samscrape/pull/901/files" target="_blank" rel="noopener"' in html
    assert ">Start session<" not in html.split("fork_pr:samscrape:901")[1][:3000]
    assert c.get("/api/person/inbox").json()["needs"] == 1


async def test_a_snooze_of_a_fork_pr_row_is_accepted_and_sets_it_aside(agent):
    from conftest import park_ticks

    from sessionorc.client import LocalClient
    from shiftlead.ui.app import fork_pr_rows, inbox_sections

    await park_ticks(agent)
    async with LocalClient() as person:
        got = await person.call("attention_snooze", id="fork_pr:samscrape:901", kind="fork_pr", until="2030-01-01")
    assert got["row"] == "fork_pr:samscrape:901|fork_pr" and agent.attention_snoozed[got["row"]] == "2030-01-01"
    (row,) = fork_pr_rows({"/r/samscrape": reading("/r/samscrape", fork_row())}, [], "kmaster", now())
    s = inbox_sections([], states=[row], attention_snoozed={got["row"]: "2030-01-01T00:00:00+00:00"})
    assert s["needs"] == [] and [e["row"] for e in s["snoozed"]] == ["fork_pr"]


# -- the Queue (Fix 7) ------------------------------------------------------------------------------------


def test_the_queue_places_a_fork_row_by_its_title_as_a_do_item_with_no_ref_and_no_start():
    from shiftlead.ui.queue import attach, item_home, item_ref, want_of

    e = {"row": "fork_pr", "id": "fork_pr:s:901", "title": "TD-10 slice 2: a stranger's fix", "branch": "td-30"}
    idx = {"TD-010": ("s#TD-10", "s#TD-10"), "TD-030": ("s#TD-30", "s#TD-30")}
    got = item_home(e, idx)
    assert (got["home"], got["on_row"]) == ("queue", "s#TD-10"), "its title alone, never a stranger's branch"
    assert want_of(e, "needs") == "do" and item_ref(e) == ""
    secs = {"needs": [{**e, **got}]}
    called = []
    out = attach(secs, lambda x, sec: "", start=lambda card, ref: called.append(ref) or {"x": 1})
    (item,) = out["cards"]["s#TD-10"]["needs"]
    assert item["fork"] and not item["red"] and item["want"] == "do" and called == []
