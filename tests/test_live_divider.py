# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-904, design §4.5 screen 11 *Merged* and screen 12 *Recently completed*, §4.5a *Repo page, Merged:
live divider* and *Queue page, Recently completed: live mark*, §6 *Promote*: the promote reading's
`promoted` and whole `pending`, a close's commit tested against `live..main`, the Repo page's one line
and the Queue's mark — live, not yet live, held, unknown, no `promote:` block, live older than the window."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import test_ui_queue as tq
from test_promote import _git, _merge, checkout  # noqa: F401 — the fixture
from test_ui_repo_completed import closed, section
from test_ui_repo_page import client, fake, reading

from sessionorc import build, ledger, promote
from shiftlead.ui.common import LIVE, NOT_LIVE, close_state, live_divider
from shiftlead.ui.queue import queue_view

pytestmark = pytest.mark.unit

NOW = datetime.now(UTC)
LIVE_SHA = "a1b2c3d" + "0" * 33


def promo(root: str, pending=("c2",), **kw) -> dict:
    """A promote reading: live at `LIVE_SHA` (#2146, promoted 2h ago by auto), `pending` the shas past it."""
    return {
        "root": root,
        "live": LIVE_SHA,
        "live_why": None,
        "main": "f" * 40,
        "pending": [{"sha": s, "subject": f"pending {s}"} for s in pending],
        "pending_more": 0,
        "promoted": {
            "sha": LIVE_SHA,
            "subject": "the fix (#2146)",
            "at": (NOW - timedelta(hours=2)).isoformat(),
            "by": "auto",
        },
        "held": None,
        **kw,
    }


# ── the rule ───────────────────────────────────────────────────────────────────────────────────


def test_a_close_is_not_yet_live_while_its_commit_is_in_live_dot_dot_main():
    p = promo("/r", pending=("c2", "c3"))
    assert close_state(p, "c2") == NOT_LIVE and close_state(p, "c1") == LIVE
    assert close_state(None, "c2") == ""  # no `promote:` block: merged is as far as it goes
    assert close_state(p, None) == ""  # a close whose commit is not known
    assert close_state(promo("/r", live_why="check exited 1"), "c1") == ""  # live unknown, a last good one kept
    unknown = promo("/r")
    del unknown["pending"]  # live and main could not be compared
    assert close_state(unknown, "c1") == ""
    assert close_state(promo("/r", pending_more=1), "c1") == ""  # past the cap the list is not whole


def test_the_divider_puts_what_is_not_yet_live_above_one_line():
    rows = [{"id": "TD-3", "sha": "c3"}, {"id": "TD-2", "sha": "c2"}, {"id": "TD-1", "sha": "c1"}]
    d = live_divider(promo("/r", pending=("c3", "c2")), rows, "r", NOW)
    assert [r["id"] for r in rows] == ["TD-3", "TD-2", "TD-1"] and d["n"] == 2
    assert [r["live"] for r in rows] == [NOT_LIVE, NOT_LIVE, LIVE]
    clock = (NOW - timedelta(hours=2)).astimezone().strftime("%H:%M")
    assert d["text"] in (
        f"live a1b2c3d · #2146 · promoted {clock} by auto · 2h 0m",
        f"live a1b2c3d · #2146 · promoted {(NOW - timedelta(hours=2)).astimezone().strftime('%m-%d %H:%M')} by auto · 2h 0m",
    )
    assert d["held"] == "" and d["repo"] == "r"
    # live at main's head: the line at the top, no *not yet live*
    assert live_divider(promo("/r", pending=()), [{"sha": "c1"}], "r", NOW)["n"] == 0
    # live older than every row: the line at the foot
    rows = [{"sha": "c2"}, {"sha": "c3"}]
    assert live_divider(promo("/r", pending=("c3", "c2", "c1")), rows, "r", NOW)["n"] == len(rows)
    # a copy installed by hand: no promoter words
    bare = promo("/r", promoted={"sha": LIVE_SHA, "subject": "the fix (#2146)", "at": None, "by": None})
    assert live_divider(bare, [], "r", NOW)["text"] == "live a1b2c3d · #2146"
    # held, unknown, no block
    held = live_divider(promo("/r", held={"sha": "b" * 40, "from": "c" * 40}), [], "r", NOW)
    assert held["held"] == "rolled back to bbbbbbb"
    assert live_divider(promo("/r", live_why="check exited 1"), [], "r", NOW) == {"unknown": "check exited 1"}
    assert live_divider(None, [], "r", NOW) == {}


# ── the reading ────────────────────────────────────────────────────────────────────────────────


def test_the_reading_names_the_promote_that_made_live_from_last_json(checkout):  # noqa: F811
    live = _git(checkout, "rev-parse", "HEAD")
    tip = _merge(checkout, "b")
    got = promote.read_since(checkout, live, tip, "repo")
    assert got["pending"] == [{"sha": tip, "subject": "b"}]
    assert got["promoted"] == {"sha": live, "subject": "a", "at": None, "by": None}  # installed by hand
    d = promote.repo_dir("repo")
    d.mkdir(parents=True, exist_ok=True)
    for written, by in (
        ({"by": "auto", "kind": "promote"}, "auto"),
        ({"by": "person", "kind": "promote"}, "you"),
        ({"by": "paul-shell", "kind": "promote"}, "you"),
        ({"by": "person", "kind": "rollback"}, "rollback"),
        ({"by": "smoke"}, "rollback"),  # a `last.json` from before `kind`: a failed smoke's rollback
    ):
        (d / "last.json").write_text(
            json.dumps({"sha": live, "from": None, "at": "2026-10-18T15:10:00+00:00", **written})
        )
        assert promote.read_since(checkout, live, tip, "repo")["promoted"]["by"] == by
    (d / "last.json").write_text(json.dumps({"sha": tip, "at": "2026-10-18T15:10:00+00:00", "by": "auto"}))
    assert promote.read_since(checkout, live, tip, "repo")["promoted"]["by"] is None  # names another commit


def test_a_concluded_run_keeps_its_kind(checkout):  # noqa: F811
    promote._concluded("repo", {"sha": "s" * 40, "from": "f" * 40, "by": "person", "kind": "rollback"}, None, NOW)
    assert promote.last("repo")["kind"] == "rollback"
    promote._concluded("repo", {"sha": "s" * 40, "from": "f" * 40, "by": "auto"}, None, NOW)
    assert promote.last("repo")["kind"] == "promote"


def test_the_chip_lists_ten_of_the_whole_pending_list():
    rows = [{"sha": f"{i:040d}", "subject": f"m{i}"} for i in range(13)]
    chip = build.chip({"commit": "a" * 40}, "", {"ref": build.REF, "ahead": 13}, pending=rows, pending_more=0)
    assert "m9" in chip["title"] and "m10" not in chip["title"] and "… and 3 more" in chip["title"]


def test_the_ledger_history_keeps_each_closes_commit():
    log = "\x00C c1 2026-10-18T10:00:00+00:00 add (#1)\n+## TD-1: one\n+## TD-2: two\n\x00C c2 2026-10-18T11:00:00+00:00 close (#2)\n-## TD-1: one\n"
    life = ledger._parse_log(log, set())
    assert (life["TD-1"].sha, life["TD-1"].pr) == ("c2", 2) and life["TD-2"].sha is None
    got = ledger.completed(
        [{"id": "TD-1", "title": "one", "closed": "2026-10-18T11:00:00+00:00", "pr": 2, "sha": "c2"}], []
    )
    assert got[0]["sha"] == "c2"


# ── the pages ──────────────────────────────────────────────────────────────────────────────────


def with_host(Fake, promotes):
    class Host(Fake):
        async def call(self, method, **kw):
            if method == "host":
                return {"name": "kmaster", "promotes": promotes}
            return await super().call(method, **kw)

    return Host


def page(tmp_path, monkeypatch, promotes, rows):
    root = str(tmp_path / "samscrape")
    r = reading(root)
    r["completed"] = rows
    got = promotes(root) if callable(promotes) else promotes
    return section(
        client(monkeypatch, tmp_path, with_host(fake({root: r}, []), got)).get("/repo/samscrape?win=week").text, "week"
    )


ROWS = [closed(3, 1, 903, sha="c3"), closed(2, 2, 902, sha="c2"), closed(1, 30, 901, sha="c1")]


def test_the_repo_page_draws_the_line_between_what_is_live_and_what_is_not(tmp_path, monkeypatch):
    week = page(tmp_path, monkeypatch, lambda root: {"samscrape": promo(root, pending=("c3",))}, list(ROWS))
    assert "not yet live (1)" in week
    line = week.index('class="rrow livediv"')
    assert week.index("TD-3") < line < week.index("TD-2") < week.index("TD-1")
    assert "live a1b2c3d · #2146 · promoted" in week and "by auto" in week
    assert "Dismiss" not in week


def test_live_at_main_draws_the_line_at_the_top_and_live_older_at_the_foot(tmp_path, monkeypatch):
    top = page(tmp_path, monkeypatch, lambda root: {"samscrape": promo(root, pending=())}, list(ROWS))
    assert "livewords" not in top and top.index('class="rrow livediv"') < top.index("TD-3")
    foot = page(
        tmp_path, monkeypatch, lambda root: {"samscrape": promo(root, pending=("c3", "c2", "c1", "c0"))}, list(ROWS)
    )
    assert "not yet live (3)" in foot and foot.index("TD-1") < foot.index('class="rrow livediv"')


def test_a_hold_says_so_and_offers_the_inbox_rows_dismiss(tmp_path, monkeypatch):
    held = {"sha": "b" * 40, "from": "c" * 40, "at": NOW.isoformat()}
    week = page(tmp_path, monkeypatch, lambda root: {"samscrape": promo(root, held=held)}, list(ROWS))
    assert "held: rolled back to bbbbbbb" in week
    assert 'data-act="clear_promote" data-id="person" data-repo="samscrape" data-held="1"' in week


def test_an_unknown_live_or_no_block_draws_no_line(tmp_path, monkeypatch):
    week = page(tmp_path, monkeypatch, lambda root: {"samscrape": promo(root, live_why="check exited 1")}, list(ROWS))
    assert "live unknown — check exited 1" in week and "livediv" not in week and "livewords" not in week
    week = page(tmp_path, monkeypatch, {}, list(ROWS))
    assert "livediv" not in week and "live unknown" not in week


def test_the_queue_marks_each_completed_line_by_its_newest_close():
    q = tq.queue()
    q["completed"][0]["entries"][0]["sha"] = "c2"  # s#TD-1's card: its newest close, TD-2, is pending
    q["completed"][1]["entries"][0]["sha"] = "c3"  # s#TD-3: live
    q["cards"][0]["rows"][0]["sha"] = "c9"  # TD-10's archived row: pending
    v = queue_view(q, tq.NOW, None, {"s": promo("/s", pending=("c2", "c9"))})
    marks = {ln["show"]: ln["live"] for ln in v["completed"]["lines"]}
    assert marks["TD-1"] == NOT_LIVE and marks["TD-3"] == LIVE and marks["TD-9"] == NOT_LIVE
    assert marks["TD-4"] == ""  # no closing commit known
    assert all(not ln["live"] for ln in queue_view(q, tq.NOW, None, {})["completed"]["lines"])  # no block


def test_the_queue_page_draws_the_mark(tmp_path, monkeypatch):
    q = tq.queue()
    q["completed"][0]["entries"][0]["sha"] = "c2"
    q["cards"][0]["rows"][0]["sha"] = "c1"  # TD-9, closed 2h ago: in the day the page sends
    html = (
        tq.client(monkeypatch, tmp_path, with_host(tq.fake(q), {"s": promo("/s", pending=("c2",))})).get("/queue").text
    )
    assert '<span class="qlive notlive"' in html and ">not yet live</span>" in html
    assert '<span class="qlive"' in html and ">live</span>" in html
