"""TD-1686 slice 2, design §4.4 *An entry no lane takes is marked*, *The note to the taker* (TD-1573):
`no_lane_noted.json`'s clocks and spent ids (`sessionorc.no_lane.step`), and the home's uncharged `system` note to
the session an id was given to."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sessionorc import agent_ids, hosts, ledger, no_lane
from sessionorc.models import ProgressEntry, Session

T0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
WHY = "Owner techlead: the lanes that take design-first take owner:designer"
KEY = "github.com/o/r"


def _m(tid, case="owner", why=WHY, **kw):
    return {"id": tid, "for_page": "design", "no_lane": {"case": case, "why": why}, **kw}


def _step(store, ents, at, *, root="/r", lanes=True, claimed=()):
    return [e["id"] for e in no_lane.step(store, KEY, root, ents, lanes, set(claimed), at)]


def _first(store, ents=(), root="/r"):
    assert _step(store, list(ents), T0, root=root) == []


@pytest.mark.unit
def test_a_first_pass_clocks_every_mark_spends_the_owner_ones_and_sends_nothing():
    store: dict = {}
    assert _step(store, [_m("TD-1"), _m("TD-2", case="team", why="Team db: no lane of db")], T0) == []
    rec = store[KEY]
    assert rec["roots"]["/r"]["from"] == T0.isoformat()
    assert set(rec["roots"]["/r"]["marked"]) == {"TD-001", "TD-002"}
    assert rec["ids"] == ["TD-001"]  # a team mark writes nothing to ids
    assert _step(store, [_m("TD-1")], T0 + timedelta(hours=2)) == []  # spent at the first pass: never noted


@pytest.mark.unit
def test_a_mark_is_noted_once_after_thirty_minutes():
    store: dict = {}
    _first(store)
    ents = [_m("TD-5")]
    assert _step(store, ents, T0 + timedelta(minutes=1)) == []
    assert _step(store, ents, T0 + timedelta(minutes=30)) == []  # 29 minutes of mark
    assert _step(store, ents, T0 + timedelta(minutes=31)) == ["TD-5"]
    assert store[KEY]["ids"] == ["TD-005"]
    assert _step(store, ents, T0 + timedelta(hours=3)) == []
    # a header change and back never notes it again
    assert _step(store, [_m("TD-5", why="other")], T0 + timedelta(hours=4)) == []
    assert _step(store, ents, T0 + timedelta(hours=5)) == []


@pytest.mark.unit
def test_a_changed_why_restarts_the_clock_and_a_team_mark_is_noted_thirty_minutes_after_it_turns_owner():
    store: dict = {}
    _first(store)
    team = [_m("TD-7", case="team", why="Team db: no lane of db")]
    assert _step(store, team, T0 + timedelta(minutes=1)) == []
    assert _step(store, team, T0 + timedelta(hours=5)) == []  # a team mark is never noted
    assert "TD-007" not in store[KEY]["ids"]
    owner = [_m("TD-7", why="Team db: Owner x: the lanes that take design-first take owner:designer")]
    assert _step(store, owner, T0 + timedelta(hours=5, minutes=10)) == []  # its why changed: a new clock
    assert _step(store, owner, T0 + timedelta(hours=5, minutes=39)) == []
    assert _step(store, owner, T0 + timedelta(hours=5, minutes=41)) == ["TD-7"]


@pytest.mark.unit
def test_a_claimed_mark_waits_for_its_claim_to_end():
    store: dict = {}
    _first(store)
    ents = [_m("TD-9")]
    _step(store, ents, T0 + timedelta(minutes=1))
    assert _step(store, ents, T0 + timedelta(hours=2), claimed={"TD-009"}) == []
    assert "TD-009" not in store[KEY]["ids"]
    assert _step(store, ents, T0 + timedelta(hours=3)) == ["TD-9"]


@pytest.mark.unit
def test_a_first_pass_spends_a_claimed_owner_mark():
    store: dict = {}
    assert _step(store, [_m("TD-3")], T0, claimed={"TD-003"}) == []
    assert store[KEY]["ids"] == ["TD-003"]
    assert _step(store, [_m("TD-3")], T0 + timedelta(hours=2)) == []


@pytest.mark.unit
def test_a_pass_that_reads_no_lane_empties_the_clocks_and_keeps_from():
    store: dict = {}
    _first(store)
    _step(store, [_m("TD-4")], T0 + timedelta(minutes=1))
    assert _step(store, [_m("TD-4")], T0 + timedelta(hours=1), lanes=False) == []
    assert store[KEY]["roots"]["/r"] == {"from": T0.isoformat(), "marked": {}}
    # back with a lane: a fresh clock, not a first pass
    assert _step(store, [_m("TD-4")], T0 + timedelta(hours=1, minutes=1)) == []
    assert _step(store, [_m("TD-4")], T0 + timedelta(hours=1, minutes=32)) == ["TD-4"]


@pytest.mark.unit
def test_two_checkouts_of_one_origin_keep_their_own_clocks_and_share_ids():
    store: dict = {}
    _first(store, root="/a")
    _first(store, root="/b")
    _step(store, [_m("TD-6")], T0 + timedelta(minutes=1), root="/a")
    _step(store, [_m("TD-6")], T0 + timedelta(minutes=20), root="/b")
    assert _step(store, [_m("TD-6")], T0 + timedelta(minutes=40), root="/b") == []  # b's clock: 20 minutes
    assert _step(store, [_m("TD-6")], T0 + timedelta(minutes=41), root="/a") == ["TD-6"]
    assert _step(store, [_m("TD-6")], T0 + timedelta(minutes=60), root="/b") == []  # spent once per origin


@pytest.mark.unit
def test_ids_are_pruned_only_once_no_reading_holds_them_open_and_no_checkout_marks_them():
    store: dict = {}
    _first(store, ents=[_m("TD-1")], root="/a")
    _first(store, root="/b")
    _step(store, [_m("TD-1")], T0 + timedelta(minutes=1), root="/b")
    assert _step(store, [], T0 + timedelta(minutes=2), root="/a") == []
    assert store[KEY]["ids"] == ["TD-001"]  # /b's marked still holds it
    _step(store, [], T0 + timedelta(minutes=3), root="/b")
    assert store[KEY]["ids"] == []
    assert store[KEY]["roots"]["/a"]["from"] == T0.isoformat()


@pytest.mark.unit
def test_since_survives_a_restart_and_a_gone_checkout_loses_its_key(tmp_path):
    store: dict = {}
    _first(store)
    _step(store, [_m("TD-8")], T0 + timedelta(minutes=1))
    no_lane.save(store)
    again = no_lane.load()
    assert _step(again, [_m("TD-8")], T0 + timedelta(minutes=32)) == ["TD-8"]
    assert no_lane.drop_root(again, "/r") and "/r" not in again[KEY]["roots"]
    assert not no_lane.drop_root(again, "/r")


@pytest.mark.unit
def test_the_note_words_and_the_taker():
    head = "TD-058: no lane of ledgerboard's teams takes it — " + WHY + ". Change its header (agent-cadence run "
    head += "ledger.py set TD-058 --owner, --kind or --field Team=…)"
    assert no_lane.note_text("TD-058", "ledgerboard", WHY, False) == head + ", or block it on what it waits for."
    assert no_lane.note_text("TD-058", "ledgerboard", WHY, True) == head + "."
    given = [{"id": "TD-58", "by": "ao-a"}, {"id": "TD-059", "by": "ao-b"}, {"id": "TD-058", "by": "ao-c@n1"}]
    assert no_lane.taker(given, "TD-058") == "ao-c@n1"
    assert no_lane.taker(given, "TD-060") is None
    assert no_lane.norm("board:x") is None and no_lane.norm("TD-7") == "TD-007"


# ── the home's step ──────────────────────────────────────────────────────────────────────────────


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


def _led(*ents):
    got = list(ents)
    return {"entries": got, "by_kind": {k: 0 for k in ledger.KINDS}, "needs_team": []}


def _e(tid, owner="techlead", **kw):
    return {"id": tid, "for_page": "design", "kind": "design-first", "owner": owner, "pickable": "yes",
            "blocked_by": [], **kw}  # fmt: skip


@pytest.mark.unit
async def test_the_home_notes_the_taker_once_uncharged_and_never_the_person_or_an_unknown(agent, tmp_path, monkeypatch):
    from conftest import park_ticks

    await park_ticks(agent)
    root = _registered(tmp_path)
    agent.sessions["ao-d"] = _rec("ao-d", root, ["design-first", "owner:designer"], host=agent.host)
    agent.sessions["ao-t"] = _rec("ao-t", root, None, state="closed", host=agent.host)  # ended is fine
    key = agent_ids.settle_key(root, "")
    agent_ids._record_given(key, ["TD-058"], "ao-t")
    agent_ids._record_given(key, ["TD-059"], "person")
    agent_ids._record_given(key, ["TD-060"], "ao-gone")
    sent = []
    monkeypatch.setattr(agent, "_system_note", lambda to, text, **kw: sent.append((to, text, kw)))
    ents = [_e("TD-058"), _e("TD-059"), _e("TD-060"), _e("TD-061", waiting=True)]
    agent._mark_lanes(root, {"remote": "", "ledger": _led(*ents)})  # a first pass: nothing sent
    assert sent == []
    store = no_lane.load()
    here = str(tmp_path.resolve() / "repo")
    old = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    store[key]["roots"][here]["from"] = old
    store[key]["ids"] = []
    for m in store[key]["roots"][here]["marked"].values():
        m["since"] = old
    no_lane.save(store)
    agent_ids._record_given(key, ["TD-061"], "ao-t")
    agent._mark_lanes(root, {"remote": "", "ledger": _led(*ents)})
    assert [(to, kw) for to, _, kw in sent] == [("ao-t", {"wake": "uncharged", "team": "lb"})] * 2
    assert sent[0][1].startswith(f"TD-058: no lane of repo's teams takes it — {WHY}.")
    assert sent[0][1].endswith("or block it on what it waits for.")
    assert sent[1][1].startswith("TD-061:") and sent[1][1].endswith("Team=…).")  # it already waits
    assert sorted(no_lane.load()[key]["ids"]) == ["TD-058", "TD-059", "TD-060", "TD-061"]  # each spent
    agent._mark_lanes(root, {"remote": "", "ledger": _led(*ents)})
    assert len(sent) == 2


@pytest.mark.unit
async def test_a_live_claim_skips_the_note_and_an_error_reading_leaves_the_clocks(agent, tmp_path, monkeypatch):
    from conftest import park_ticks

    await park_ticks(agent)
    root = _registered(tmp_path)
    agent.sessions["ao-d"] = _rec("ao-d", root, ["design-first", "owner:designer"], host=agent.host)
    agent.sessions["ao-c"] = _rec("ao-c", root, None, host=agent.host, progress=[ProgressEntry(ref="TD-58")])
    agent.sessions["ao-t"] = _rec("ao-t", root, None, state="closed", host=agent.host)
    key = agent_ids.settle_key(root, "")
    agent_ids._record_given(key, ["TD-058"], "ao-t")
    sent = []
    monkeypatch.setattr(agent, "_system_note", lambda to, text, **kw: sent.append(to))
    here = str(tmp_path.resolve() / "repo")
    old = (datetime.now(UTC) - timedelta(minutes=31)).isoformat()
    no_lane.save({key: {"roots": {here: {"from": old, "marked": {"TD-058": {"why": WHY, "since": old}}}}, "ids": []}})
    agent._mark_lanes(root, {"remote": "", "ledger": _led(_e("TD-058"))})
    assert sent == [] and no_lane.load()[key]["ids"] == []
    before = no_lane.load()
    agent._mark_lanes(root, {"remote": "", "ledger": {**_led(_e("TD-058")), "error": "x"}})
    assert no_lane.load() == before
    agent.sessions["ao-c"].state = "exited"
    agent._mark_lanes(root, {"remote": "", "ledger": _led(_e("TD-058"))})
    assert sent == ["ao-t"]


@pytest.mark.unit
async def test_a_checkout_the_registry_drops_loses_its_clocks(agent, tmp_path, monkeypatch):
    from conftest import park_ticks

    await park_ticks(agent)
    root = _registered(tmp_path)
    here = str(tmp_path.resolve() / "repo")
    no_lane.save({KEY: {"roots": {here: {"from": T0.isoformat(), "marked": {}}, "/other": {}}, "ids": []}})
    agent._repos[root] = {"remote": ""}
    hosts.default_repos_registry().write_text("")
    monkeypatch.setattr(agent, "_read_repos", lambda todo, *a, **kw: {})
    agent._repos_read_at = float("-inf")
    await agent._refresh_repos()
    assert no_lane.load()[KEY]["roots"] == {"/other": {}}
