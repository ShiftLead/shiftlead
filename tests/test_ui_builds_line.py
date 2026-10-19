"""TD-697, design §4.5 screen 11 *Technical debt* (*Its builds*), §4.5a *Repo page: its builds line*:
a design entry's row carries its builds and each one's state, a build's row says *builds TD-n*, and
the ledger reading carries what that is read from — `blocked_ids` and `archived`."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_ui_repo_page import client, fake, rec

from sessionorc import ledger
from shiftlead.ui.repo import design_builds, ledger_lists

pytestmark = pytest.mark.unit

LEDGER = """# Technical Debt

## TD-100: the design

**Priority:** Medium
**Owner:** designer
**Kind:** design-first
**Blocked by:** TD-42, TD-101, TD-102, TD-103, TD-104, other#TD-5

## TD-101: build one

**Priority:** Medium
**Owner:** grinder
**Kind:** build

## TD-102: build two

**Priority:** Medium
**Owner:** grinder
**Kind:** build

## TD-103: build three

**Priority:** Medium
**Owner:** grinder
**Kind:** build
**Blocked by:** TD-102, decision (paul)

## TD-104: build four

**Priority:** Low
**Owner:** grinder
**Kind:** build

## TD-105: not a design

**Priority:** Low
**Owner:** grinder
**Blocked by:** TD-101

## TD-106: a design with no builds

**Priority:** Low
**Owner:** designer
**Kind:** design-first

## TD-107: a design every build of which is archived

**Priority:** Low
**Owner:** designer
**Kind:** design-first
**Blocked by:** TD-42, TD-43
"""

ARCHIVE = """# Archive

## TD-042: an archived build

**Resolved:** 2026-10-01

## TD-043: another archived build

**Resolved:** 2026-10-02

## TD-077: archived, and named by nothing

**Resolved:** 2026-10-03
"""

MOTION = [
    {"ref": "TD-101", "members": [{"name": "g1"}], "pr": None},
    {"ref": "TD-102", "members": [{"name": "g2"}], "pr": 815, "pr_url": "https://x/815"},
]


def _repo(root: Path) -> Path:
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "technical_debt.md").write_text(LEDGER)
    (root / "docs" / "technical_debt_archive.md").write_text(ARCHIVE)
    return root


def _reading(root: Path) -> dict:
    return ledger.reading(_repo(root), datetime.now(UTC), with_history=False)


def test_the_reading_carries_every_blocked_id_and_only_the_archived_ones_named(tmp_path):
    got = _reading(tmp_path / "r")
    by = {e["id"]: e for e in got["entries"]}
    # `TD-42` is the archive's `TD-042`; another repo's item and the decision are not ids of this ledger
    assert by["TD-100"]["blocked_ids"] == ["TD-042", "TD-101", "TD-102", "TD-103", "TD-104"]
    assert by["TD-100"]["blocked_by"] == ["TD-101", "TD-102", "TD-103", "TD-104", "other#TD-5"]
    assert by["TD-103"]["blocked_ids"] == ["TD-102"] and by["TD-101"]["blocked_ids"] == []
    assert got["archived"] == ["TD-042", "TD-043"], "TD-077 is named by nothing, so it does not ride the reading"


def test_the_line_lists_each_build_in_order_with_its_state(tmp_path):
    r = {"ledger": _reading(tmp_path / "r")}
    lists = {x["key"]: x for x in ledger_lists(r, MOTION)}
    rows = {e["id"]: e for x in lists.values() for e in x["rows"]}
    line = rows["TD-100"]["builds"]
    assert [(b["id"], b["state"]) for b in line["builds"]] == [
        ("TD-042", "archived"),
        ("TD-101", "held"),
        ("TD-102", "review"),
        ("TD-103", "open"),
        ("TD-104", "open"),
    ]
    b = {x["id"]: x for x in line["builds"]}
    assert b["TD-042"]["row"] == "" and b["TD-101"]["row"] == "TD-101", "an archived id is plain text"
    assert b["TD-101"]["held"] == "g1" and (b["TD-102"]["pr"], b["TD-102"]["url"]) == (815, "https://x/815")
    # what still blocks, and only the design's own builds: the decision is not one
    assert b["TD-103"]["blocked_by"] == ["TD-102"] and b["TD-104"]["blocked_by"] == []
    assert line["done"] is False
    # the back-link, from the same pass; not on an entry that is no design's build
    assert rows["TD-101"]["builds_of"] == ["TD-100"] and rows["TD-105"]["builds_of"] == []
    # no line where `Blocked by:` names no build, or the entry is no design
    assert rows["TD-106"]["builds"] is None and rows["TD-105"]["builds"] is None


def test_a_design_whose_builds_are_all_archived_still_lists_them(tmp_path):
    r = {"ledger": _reading(tmp_path / "r")}
    rows = {e["id"]: e for x in ledger_lists(r, []) for e in x["rows"]}
    line = rows["TD-107"]["builds"]
    assert [(b["id"], b["state"]) for b in line["builds"]] == [("TD-042", "archived"), ("TD-043", "archived")]
    assert line["done"] is True


def test_ids_written_either_way_are_one_entry():
    entries = [
        {"id": "TD-042", "kind": "design-first", "blocked_ids": ["TD-043", "TD-044"]},
        {"id": "TD-43", "kind": "build", "blocked_by": ["TD-44", "decision (paul)", "x#TD-1"]},
        {"id": "TD-044", "kind": "build", "blocked_by": []},
    ]
    lines, back = design_builds(entries, ["TD-0099"], {"TD-44": "g"}, {})
    got = {b["id"]: b for b in lines["TD-042"]["builds"]}
    assert got["TD-43"]["blocked_by"] == ["TD-044"] and got["TD-044"]["state"] == "held"
    assert back == {"TD-43": ["TD-042"], "TD-044": ["TD-042"]}


def test_the_page_draws_the_line_and_the_back_link(tmp_path, monkeypatch):
    root = tmp_path / "samscrape"
    r = {"name": "samscrape", "root": str(root), "ledger": _reading(root), "prs": {"open": []}}
    fleet = [
        rec("g1", str(root), progress=[{"ref": "TD-101", "status": "claimed"}]),
        rec("g2", str(root), progress=[{"ref": "TD-102", "status": "claimed", "pr": 815}]),
    ]
    c = client(monkeypatch, tmp_path, fake({str(root): r}, fleet))
    html = c.get("/repo/samscrape?open=TD-103,TD-100").text  # both blocked: their folds sent (TD-903)
    assert 'class="qbuilds"' in html
    line = html[html.index("qbuilds", html.index('id="TD-100"')) :]
    line = line[: line.index("</div>")]
    assert "builds: TD-042 <span" in line, "an archived id is plain text"
    assert '<a href="#TD-101">TD-101</a> <span class="bstate">held by g1</span>' in line
    assert '<a href="#TD-102">TD-102</a> <span class="bstate">in review ' in line and "#815" in line
    assert '<a href="#TD-103">TD-103</a> <span class="bstate">open, blocked by TD-102</span>' in line
    assert "every build archived — archive this entry" in html  # TD-107
    # a build's row says *builds TD-n* after its owner (TD-103 waits on the person: For you's Inbox row, TD-903)
    back = '· grinder</span><span class="meta">· builds <a href="#TD-100">TD-100</a></span>'
    assert back in html


def test_an_id_named_twice_is_listed_once():
    # `TD-5` and `TD-005` are one id: the design's line lists the build once, where it is first written
    assert ledger.blocked_ids("TD-5, TD-101, TD-005, TD-101") == ["TD-005", "TD-101"]


def test_a_build_in_review_links_its_pr(tmp_path, monkeypatch):
    root = tmp_path / "samscrape"
    r = {
        "name": "samscrape",
        "root": str(root),
        "remote": "git@github.com:o/samscrape.git",
        "ledger": _reading(root),
        "prs": {"open": []},
    }
    fleet = [rec("g2", str(root), progress=[{"ref": "TD-102", "status": "claimed", "pr": 815}])]
    c = client(monkeypatch, tmp_path, fake({str(root): r}, fleet))
    html = c.get("/repo/samscrape?open=TD-100").text  # a design its builds block: folded until opened (TD-903)
    line = html[html.index("qbuilds", html.index('id="TD-100"')) :]
    line = line[: line.index("</div>")]
    want = '<span class="bstate">in review <a href="https://github.com/o/samscrape/pull/815" target="_blank"'
    assert want in line and ">#815</a>" in line
