"""Which open pull request is an entry's work (design §4.9e *Work in flight*, TD-2051)."""

from __future__ import annotations

from typing import Any

import pytest

from shiftlead.stage_work import branch_ids, entry_work


def pr(number: int, branch: str, **over: Any) -> dict[str, Any]:
    row = {
        "number": number,
        "branch": branch,
        "state": "open",
        "head": f"sha{number}",
        "filing": False,
        "filing_head": f"sha{number}",
        "draft": False,
        "fork": False,
        "created": f"2026-11-{number:02d}T00:00:00Z",
        "title": "",
    }
    return {**row, **over}


@pytest.mark.parametrize(
    ("branch", "ids"),
    [
        ("td2051-tick-acts", {"TD-2051"}),
        ("TD-2051/acts", {"TD-2051"}),
        ("fix_td-2051", {"TD-2051"}),
        ("td-205-1", {"TD-205"}),
        ("td-205-acts", {"TD-205"}),
        ("xtd2051", set()),
        ("td2051b", set()),
        ("td2051-td2052", {"TD-2051", "TD-2052"}),
        ("td2051-again-TD-2051", {"TD-2051"}),
        ("main", set()),
        (None, set()),
    ],
)
def test_a_branch_holds_an_id_as_a_whole_token(branch, ids):
    assert branch_ids(branch) == ids


def test_no_pull_request_is_offered_afresh():
    assert entry_work("TD-2051", []).state == "none"
    assert entry_work("TD-2051", [pr(1, "td-205-x"), pr(2, "td20510")]).state == "none"


def test_the_title_is_not_read():
    assert entry_work("TD-2051", [pr(1, "cleanup", title="TD-2051: the acts")]).state == "none"


def test_the_match_is_taken_with_its_branch_and_number():
    got = entry_work("TD-2051", [pr(1, "td2051-acts")])
    assert (got.state, got.pr["number"], got.pr["branch"]) == ("take", 1, "td2051-acts")


@pytest.mark.parametrize(
    "row",
    [
        pr(1, "td2051-acts", fork=True),
        pr(1, "td2051-acts", filing=True),
        pr(1, "td2051-td2052"),
        pr(1, "td2051-acts", state="closed"),
        pr(1, "td2051-acts", state="merged"),
    ],
)
def test_what_is_never_an_entrys_work_leaves_it_offered_afresh(row):
    assert entry_work("TD-2051", [row]).state == "none"


def test_the_newest_of_several_is_taken():
    got = entry_work("TD-2051", [pr(3, "td2051-a"), pr(9, "td2051-c"), pr(5, "td2051-b")])
    assert got.pr["number"] == 9


def test_a_fork_or_filing_pull_request_never_counts_as_the_newest():
    rows = [pr(3, "td2051-a"), pr(8, "td2051-fork", fork=True), pr(9, "td2051-file", filing=True)]
    got = entry_work("TD-2051", rows)
    assert (got.state, got.pr["number"]) == ("take", 3)


def test_a_newest_draft_makes_the_entry_wait_though_an_older_one_is_ready():
    got = entry_work("TD-2051", [pr(3, "td2051-a"), pr(9, "td2051-b", draft=True)])
    assert (got.state, got.pr["number"]) == ("wait", 9)
    assert "draft" in got.why


def test_a_pull_request_a_live_session_holds_makes_the_entry_wait():
    got = entry_work("TD-2051", [pr(4, "td2051-a")], held={4})
    assert (got.state, got.pr["number"]) == ("wait", 4)
    assert "held" in got.why


def test_a_session_taken_as_gone_leaves_the_pull_request_to_be_taken():
    assert entry_work("TD-2051", [pr(4, "td2051-a")], held=set()).state == "take"


@pytest.mark.parametrize(
    "over",
    [{"filing_head": "older"}, {"filing_head": None}, {"filing": None}, {"head": ""}],
)
def test_a_pull_request_whose_files_are_unread_at_its_head_decides_nothing(over):
    got = entry_work("TD-2051", [pr(4, "td2051-a", **over)])
    assert (got.state, got.pr["number"]) == ("unread", 4)


def test_a_filing_word_from_an_older_head_is_not_trusted():
    got = entry_work("TD-2051", [pr(4, "td2051-a", filing=True, filing_head="older")])
    assert got.state == "unread"
