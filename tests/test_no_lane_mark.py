"""TD-1686, design §4.4 *An entry no lane takes is marked* (TD-1573): `ledger.lane_gap`, the home's mark step on
every reading it stores (`_refresh_repos`, `_reread_board`), the withheld counts, and the Queue's reads."""

from __future__ import annotations

import copy

import pytest

from sessionorc import hosts, ledger, queue
from sessionorc.models import Session
from shiftlead import teamrun

DESIGNER = ["design-first", "owner:designer"]
GRINDER = ["free-pick", "owner:grinder"]
TD_058_WHY = "Owner techlead: the lanes that take design-first take owner:designer"


def _e(tid, page="design", kind="design-first", owner="techlead", **kw):
    return {
        "id": tid,
        "for_page": page,
        "kind": kind,
        "owner": owner,
        "pickable": "yes",
        "blocked_by": [],
        "priority": "Medium",
        **kw,
    }


def _led(*ents):
    got = list(ents)
    return {
        "path": "docs/ledger",
        "entries": got,
        "by_kind": {k: sum(1 for e in got if e["for_page"] == k) for k in ledger.KINDS},
        "needs_team": [],
    }


# ── lane_gap ─────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ledgerboard_td_058_is_marked_by_its_owner():
    lanes = [(DESIGNER, "lb"), (GRINDER, "lb")]
    assert ledger.lane_gap(_e("TD-058"), lanes) == ("owner", TD_058_WHY)


@pytest.mark.unit
def test_what_is_never_marked():
    lanes = [(DESIGNER, "lb"), (GRINDER, "lb")]
    # a pickable build of the person's, untagged, and any untagged pickable (its miss is the rest's)
    assert ledger.lane_gap(_e("TD-1", page="pickable", kind="build", owner="paul"), lanes) is None
    assert ledger.lane_gap(_e("TD-2", page="pickable", kind="build", owner="techlead"), lanes) is None
    # a design-first entry of the person's
    assert ledger.lane_gap(_e("TD-3", owner="Paul"), lanes) is None
    # held by a decision, an open id or an open part
    assert ledger.lane_gap(_e("TD-4", pickable="no", blocked_by=["decision (paul)"]), lanes) is None
    assert ledger.lane_gap(_e("TD-5", pickable="no", blocked_by=["TD-9"]), lanes) is None
    # a live check blocked by a decision
    check = _e("TD-6", page="live-check", kind="live-check", pickable="no", blocked_by=["decision (paul)"])
    assert ledger.lane_gap(check, lanes) is None
    # one marked needs_team
    assert ledger.lane_gap(_e("TD-7", needs_team={"why": "x"}), lanes) is None
    # one a lane takes
    assert ledger.lane_gap(_e("TD-8", owner="designer"), lanes) is None


@pytest.mark.unit
def test_settling_and_waiting_entries_a_lane_would_not_take_once_settled_are_marked_and_one_it_would_is_not():
    lanes = [(DESIGNER, "")]
    settling = _e("TD-1", settling={"until": "x"})
    waiting = _e("TD-2", pickable="no", blocked_by=["until 2099-01-01"], gates=["until 2099-01-01"], waiting={})
    assert ledger.lane_gap(settling, lanes)[0] == "owner"
    assert ledger.lane_gap(waiting, lanes)[0] == "owner"
    assert ledger.lane_gap({**settling, "owner": "designer"}, lanes) is None
    assert ledger.lane_gap({**waiting, "owner": "designer"}, lanes) is None


@pytest.mark.unit
def test_the_team_and_kind_cases_give_their_own_words():
    lanes = [(DESIGNER, "lb"), (["free-pick"], "")]
    assert ledger.lane_gap(_e("TD-1", team="db"), lanes) == ("team", "Team db: no lane of db")
    # a pickable entry tagged with a team no record carries is tested, and marked
    tagged = _e("TD-2", page="pickable", kind="build", owner="grinder", team="DB")
    assert ledger.lane_gap(tagged, lanes) == ("team", "Team DB: no lane of DB")
    # a tagged entry's team matched case-folded, and the teamless lanes are its team's too
    assert ledger.lane_gap(_e("TD-3", team="LB"), lanes) == ("owner", f"Team LB: {TD_058_WHY}")
    # no lane takes the kind word
    assert ledger.lane_gap(_e("TD-4"), [(GRINDER, "lb")]) == ("kind", "no lane takes design-first")
    check = _e("TD-5", page="live-check", kind="live-check")
    assert ledger.lane_gap(check, [(DESIGNER, "")]) == ("kind", "no lane takes free-pick")


@pytest.mark.unit
def test_a_tagged_entry_is_read_against_its_own_teams_lanes_alone():
    # another team's lane would take it; its own team's lanes take no design-first (TD-1736)
    lanes = [(DESIGNER, "db"), (GRINDER, "lb")]
    assert ledger.lane_gap(_e("TD-1", owner="designer", team="lb"), lanes) == (
        "kind",
        "Team lb: no lane takes design-first",
    )


@pytest.mark.unit
def test_owner_words_are_sorted_and_said_once():
    lanes = [(["design-first", "owner:zed", "owner:designer"], ""), (DESIGNER, ""), (GRINDER, "")]
    why = ledger.lane_gap(_e("TD-1"), lanes)[1]
    assert why == "Owner techlead: the lanes that take design-first take owner:designer or owner:zed"


# ── mark_no_lane ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_the_mark_counts_under_no_lane_and_never_changes_the_reading_given():
    led = _led(_e("TD-058"), _e("TD-2", owner="designer"), _e("TD-3", page="pickable", kind="build", owner="x"))
    was = copy.deepcopy(led)
    got = ledger.mark_no_lane(led, [(DESIGNER, "lb"), (GRINDER, "lb")])
    assert led == was  # copies: a carried reading shares its entries with the stored one
    assert got["entries"][0]["no_lane"] == {"case": "owner", "why": TD_058_WHY}
    assert "no_lane" not in got["entries"][1]
    assert got["by_kind"]["design"] == 1 and got["by_kind"]["no-lane"] == 1 and got["by_kind"]["pickable"] == 1
    assert got["no_lane"] == [{"id": "TD-058", "why": TD_058_WHY}]
    # an old mark is dropped once a lane takes it, its count back under its kind
    again = ledger.mark_no_lane(got, [(["design-first"], "lb")])
    assert "no_lane" not in again["entries"][0]
    assert again["by_kind"]["design"] == 2 and again["by_kind"]["no-lane"] == 0 and again["no_lane"] == []


@pytest.mark.unit
def test_no_lanes_marks_nothing_but_still_rebuilds_and_an_error_reading_is_left():
    led = _led(_e("TD-058"))
    got = ledger.mark_no_lane(ledger.mark_no_lane(led, [(GRINDER, "")]), [])
    assert "no_lane" not in got["entries"][0] and got["by_kind"]["no-lane"] == 0 and got["by_kind"]["design"] == 1
    failed = {"path": "docs/ledger", "error": "cannot be read", "entries": [{**_e("TD-1"), "no_lane": {}}]}
    assert ledger.mark_no_lane(failed, [(GRINDER, "")]) is failed


# ── the withheld counts ──────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_lane_kinds_subtracts_a_settling_marked_entry_once():
    tagged = _e("TD-1", page="pickable", kind="build", owner="grinder", team="db", settling={"until": "x"})
    plain = _e("TD-2", page="pickable", kind="build", owner="grinder", settling={"until": "x"})
    led = ledger.mark_no_lane(_led(tagged, plain), [(GRINDER, "lb")])
    assert led["by_kind"]["pickable"] == 1 and led["by_kind"]["no-lane"] == 1
    assert teamrun.lane_kinds({"ledger": led})["pickable"] == 0  # the plain settling one alone, subtracted once


@pytest.mark.unit
def test_lane_kinds_leaves_a_marked_settling_entry_out_of_the_withheld_count():
    # one pickable entry beside a settling one the mark moved to no-lane: it stays counted (TD-1736)
    tagged = _e("TD-1", page="pickable", kind="build", owner="grinder", team="db", settling={"until": "x"})
    plain = _e("TD-2", page="pickable", kind="build", owner="grinder")
    led = ledger.mark_no_lane(_led(tagged, plain), [(GRINDER, "lb")])
    assert led["by_kind"]["pickable"] == 1 and led["by_kind"]["no-lane"] == 1
    assert teamrun.lane_kinds({"ledger": led})["pickable"] == 1


# ── the Queue ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_the_queue_reads_a_marked_member_as_no_lane_takes_it():
    marked = {**_e("TD-1"), "no_lane": {"case": "owner", "why": TD_058_WHY}}
    assert queue._status([], [marked]) == "blocked"
    assert queue._status([], [marked, _e("TD-2", owner="designer")]) == "ready"
    w = queue._wait(["shiftlead#TD-1"], {"shiftlead#TD-1": marked}, {"shiftlead#TD-1": set()},
                    {"shiftlead#TD-1": set()}, {"shiftlead#TD-1": "a"}, "shiftlead#TD-1")  # fmt: skip
    assert w == {"column": "blocked", "phrase": "blocked: no lane takes it", "id": "shiftlead#TD-1"}


# ── the mark step on the home ────────────────────────────────────────────────────────────────────


def _rec(sid, repo, lane, team="lb", state="idle", **kw):
    return Session(
        id=sid, name=sid, kind="interactive", adapter="shell", dir="/tmp", state=state, repo=repo, lane=lane,
        team=team, **kw,
    )  # fmt: skip


def _registered(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    reg = hosts.default_repos_registry()
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(f"{root}\n")
    return str(root)


@pytest.mark.unit
async def test_the_tick_marks_before_it_compares_and_a_record_starting_drops_the_mark(agent, tmp_path, monkeypatch):
    from conftest import park_ticks

    await park_ticks(agent)
    root = _registered(tmp_path)
    agent.sessions["ao-g"] = _rec("ao-g", root, GRINDER, host=agent.host)
    agent.sessions["ao-old"] = _rec("ao-old", root, ["design-first"], superseded_by="ao-g", host=agent.host)
    reads = []

    def read(todo, prev, *a, **kw):
        reads.append(1)
        return {r: {"remote": "", "ledger": _led(_e("TD-058"))} for r in todo}

    monkeypatch.setattr(agent, "_read_repos", read)
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()
    stored = agent._repos[root]["ledger"]
    assert stored["entries"][0]["no_lane"] == {"case": "kind", "why": "no lane takes design-first"}
    assert stored["by_kind"]["no-lane"] == 1 and stored["by_kind"]["design"] == 0
    before = copy.deepcopy(stored)
    saved = []
    monkeypatch.setattr(agent.repos_store, "save", lambda v: saved.append(1))
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()
    assert saved == []  # an unchanged mark changes nothing
    agent.sessions["ao-d"] = _rec("ao-d", root, DESIGNER, host=agent.host, state="closed")  # ended records count
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()
    now = agent._repos[root]["ledger"]
    assert now["entries"][0]["no_lane"] == {"case": "owner", "why": TD_058_WHY} and saved == [1]
    assert stored == before  # the stored reading was replaced, never edited in place
    agent.sessions["ao-d"].lane = ["design-first"]
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()
    now = agent._repos[root]["ledger"]
    assert "no_lane" not in now["entries"][0] and now["by_kind"]["design"] == 1 and now["by_kind"]["no-lane"] == 0


@pytest.mark.unit
async def test_an_unserved_repo_marks_nothing(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    root = _registered(tmp_path)
    agent.sessions["ao-g"] = _rec("ao-g", root, GRINDER, host=agent.host)
    reading = {"ledger": _led(_e("TD-058")), "seams": {"serve": {"ok": False, "lacks": [{"key": "x"}]}}}
    agent._mark_lanes(root, reading)
    assert "no_lane" not in reading["ledger"]["entries"][0] and reading["ledger"]["by_kind"]["no-lane"] == 0
    served = {"ledger": _led(_e("TD-058"))}
    agent._mark_lanes(root, served)
    assert served["ledger"]["no_lane"] == [{"id": "TD-058", "why": "no lane takes design-first"}]


@pytest.mark.unit
async def test_a_press_re_read_marks_before_its_compare(agent, tmp_path, monkeypatch):
    from conftest import park_ticks

    await park_ticks(agent)
    root = _registered(tmp_path)
    agent.sessions["ao-d"] = _rec("ao-d", root, DESIGNER, host=agent.host)
    marked = ledger.mark_no_lane(_led(_e("TD-058")), agent._repo_lanes(root))
    assert marked["no_lane"]
    agent._repos[root] = {"remote": "", "ledger": marked}
    saved = []
    monkeypatch.setattr(agent.repos_store, "save", lambda v: saved.append(1))
    monkeypatch.setattr(agent, "_reread_repo", lambda *a: ({"error": "x"}, {}, _led(_e("TD-058")), []))
    assert await agent._reread_board(root) is False and saved == []  # the same mark: nothing pushed
    agent.sessions["ao-d"].lane = ["design-first"]
    assert await agent._reread_board(root) is True
    assert "no_lane" not in agent._repos[root]["ledger"]["entries"][0]
