"""TD-2069 slice 2, design §4.9e *A session moves down the list*: the tick of the home's host moves an unattended
session whose login is no longer usable to the next usable login of the list it was launched with that offers its
model, under the same record, told what its stage's session is told followed by the handoff; while its record is
marked `moving` no other rule acts on it, a failed launch leaves it ended, and a mark is never left standing."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from conftest import park_ticks

from sessionorc import adapters, agent_common, paths, teamstore
from sessionorc.adapters import LaunchSpec
from sessionorc.client import LocalClient
from shiftlead import stage_pass
from shiftlead.stage_read import EntryFacts, EntryLedger, holder_on
from shiftlead.stagerecord import StageStore, new_record

LOGINS = """logins:
  hookstub:first: {folder: /c/first, account: acct-1}
  hookstub:second: {folder: /c/second, account: acct-2}
  hookstub:third: {folder: /c/third, account: acct-3}
accounts: {}
forgotten: {}
"""
ORDER = ["hookstub:first", "hookstub:second", "hookstub:third"]
HANDOFF = f"{adapters.HANDOFF_HEADING}\n\nfixing the race"


def _row(account: str, models: list[str], **kw) -> dict:
    return {"state": "signed_in", "account": account, "pin": None, "models": models, "at_reserve": False, **kw}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("states", "current", "want"),
    [
        ({}, "hookstub:first", None),
        ({"hookstub:first": {"state": "limited"}}, "hookstub:first", "hookstub:second"),
        (
            {"hookstub:first": {"at_reserve": True}, "hookstub:second": {"state": "limited"}},
            "hookstub:first",
            "hookstub:third",
        ),
        (
            {"hookstub:first": {"state": "limited"}, "hookstub:second": {"account": "acct-1"}},
            "hookstub:first",
            "hookstub:third",
        ),
        ({"hookstub:second": {"state": "limited"}}, "hookstub:second", "hookstub:third"),
        ({"hookstub:third": {"state": "limited"}}, "hookstub:third", None),
        (
            {"hookstub:first": {"state": "limited"}, "hookstub:second": {"models": ["haiku"]}},
            "hookstub:first",
            "hookstub:third",
        ),
        ({"hookstub:first": {"state": "limited"}}, "hookstub:other", None),
    ],
    ids=[
        "usable",
        "limited",
        "reserve-then-limited",
        "shared-account",
        "never-up",
        "last",
        "not-offered",
        "not-listed",
    ],
)
def test_next_login_is_the_first_usable_one_below_that_offers_the_model(states, current, want):
    rows = {lk: _row(f"acct-{i}", ["opus"]) for i, lk in enumerate(ORDER, 1)}
    for lk, kw in states.items():
        rows[lk] = {**rows[lk], **kw}
    assert teamstore.next_login(ORDER, current, "opus", rows) == want


@pytest.fixture
def launched(hookstub, monkeypatch):
    """The stub adapter's launch, recording the profile and prompt each was handed."""
    seen: list[dict] = []

    def launch(*, profile, resume, prompt, unattended, cwd, name="", **kw):
        seen.append({"profile": profile, "prompt": prompt, **kw})
        return LaunchSpec(argv=["bash", "--norc"])

    monkeypatch.setattr(hookstub, "launch", launch)
    return seen


@pytest.fixture
def rows(agent, monkeypatch):
    """The login rows the move reads, as the test sets them: first limited, second and third usable."""
    held = {lk: _row(f"acct-{i}", ["opus"]) for i, lk in enumerate(ORDER, 1)}
    held["hookstub:first"]["state"] = "limited"
    monkeypatch.setattr(agent, "rpc_tools", AsyncMock(return_value={"tools": []}))
    monkeypatch.setattr(agent, "rpc_gate", AsyncMock(return_value={"accounts": {}}))
    monkeypatch.setattr(teamstore, "login_rows", lambda *a, **kw: held)
    monkeypatch.setattr(adapters, "handoff_of", lambda ad, path: HANDOFF)
    return held


async def _stage_session(agent, tmp_path, *, unattended: bool = True) -> str:
    """A stage's session as the stage pass launches it: supervised, on its list's first login, with its model."""
    await park_ticks(agent)
    (paths.home() / "logins.yml").write_text(LOGINS)
    (tmp_path / "repo").mkdir(exist_ok=True)
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create",
                name="build-td-1",
                dir=str(tmp_path / "repo"),
                adapter="hookstub",
                profile="",
                login="hookstub:first",
                seat_model="opus",
                login_list=ORDER,
                unattended=True,
                supervised=True,
                prompt="the stage's words",
                team="t",
            )
        )["id"]
    s = agent.sessions[sid]
    s.state = "limited"
    s.unattended = unattended
    return sid


@pytest.mark.integration
async def test_a_session_on_an_unusable_login_moves_to_the_next_under_the_same_record(agent, tmp_path, launched, rows):
    sid = await _stage_session(agent, tmp_path)
    old = agent.sessions[sid]
    await agent._login_moves(datetime.now(UTC))
    new = agent.sessions[sid]
    assert new is not old, "the session was launched again"
    assert new.id == sid and new.name == "build-td-1", "under the same record, so its stage record's holder stands"
    assert (new.login, new.account, new.seat_model, new.login_list) == ("hookstub:second", "acct-2", "opus", ORDER)
    assert new.moving is None and old.closed_for["why"] == "login-move"
    assert [(m["from"], m["to"]) for m in new.login_moves] == [("hookstub:first", "hookstub:second")]
    assert launched[-1]["profile"] == "second" and launched[-1]["model"] == "opus"
    told = launched[-1]["prompt"]
    assert told.startswith("the stage's words") and told.endswith(HANDOFF), "its stage's words, then the handoff"
    assert new.restarts[-1]["why"] == "login-move"
    assert agent_common._counted(new.restarts, datetime.now(UTC)) == [], "a move counts toward no ceiling"


@pytest.mark.integration
async def test_an_adapter_without_handoff_moves_with_its_stages_words_alone(
    agent, tmp_path, launched, rows, monkeypatch
):
    monkeypatch.setattr(adapters, "handoff_of", lambda ad, path: "")
    sid = await _stage_session(agent, tmp_path)
    await agent._login_moves(datetime.now(UTC))
    assert agent.sessions[sid].login == "hookstub:second"
    assert launched[-1]["prompt"] == "the stage's words"


@pytest.mark.integration
@pytest.mark.parametrize("case", ["usable", "no-later", "interactive", "suspended", "exited"], ids=lambda c: c)
async def test_what_does_not_move(agent, tmp_path, launched, rows, case):
    sid = await _stage_session(agent, tmp_path, unattended=case != "interactive")
    s = agent.sessions[sid]
    if case == "usable":
        rows["hookstub:first"]["state"] = "signed_in"
    elif case == "no-later":
        rows["hookstub:second"]["state"] = "limited"
        rows["hookstub:third"]["at_reserve"] = True
    elif case == "suspended":
        s.suspended = True
    elif case == "exited":
        s.state = "exited"
    count = len(launched)
    await agent._login_moves(datetime.now(UTC))
    assert agent.sessions[sid] is s and s.login == "hookstub:first" and s.moving is None
    assert len(launched) == count and s.login_moves == [], "it waits where it is"


@pytest.mark.integration
async def test_a_launch_that_fails_leaves_the_session_ended_unmarked_and_its_holder_lost(
    agent, tmp_path, launched, rows, monkeypatch
):
    sid = await _stage_session(agent, tmp_path)
    s = agent.sessions[sid]
    monkeypatch.setattr(agent, "rpc_create", AsyncMock(side_effect=RuntimeError("no launch")))
    await agent._login_moves(datetime.now(UTC))
    assert agent.sessions[sid] is s and s.state == "closed" and s.moving is None
    assert s.restarts[-1]["why"] == "login-move" and "no launch" in s.restarts[-1]["error"]
    assert not agent._crashed(s, datetime.now(UTC)), "no crash restart: the tick closed it"
    assert holder_on(s, "TD-1", datetime.now(UTC)).lost


@pytest.mark.integration
async def test_a_moving_record_is_neither_lost_nor_silent_and_gets_no_crash_restart(agent, tmp_path, launched, rows):
    sid = await _stage_session(agent, tmp_path)
    s = agent.sessions[sid]
    s.moving = {"at": datetime.now(UTC).isoformat(), "from": "hookstub:first", "to": "hookstub:second"}
    s.state, s.pane = "exited", True
    now = datetime.now(UTC)
    held = holder_on(s, "TD-1", now)
    assert not held.lost and not held.silent
    assert not agent._crashed(s, now)
    count = len(launched)
    await agent._login_moves(now)
    assert len(launched) == count and s.moving is not None, "a fresh mark stands and nothing moves it again"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("minutes", "state", "cleared"), [(11, "closed", True), (5, "closed", False), (11, "limited", False)]
)
async def test_a_mark_with_no_live_session_ten_minutes_on_is_cleared(
    agent, tmp_path, launched, rows, minutes, state, cleared
):
    sid = await _stage_session(agent, tmp_path)
    s = agent.sessions[sid]
    at = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
    s.moving, s.state = {"at": at, "from": "hookstub:first", "to": "hookstub:second"}, state
    await agent._login_moves(datetime.now(UTC))
    assert (s.moving is None) == cleared


@pytest.mark.integration
async def test_a_host_agent_that_starts_clears_every_mark(agent, tmp_path, launched, rows):
    sid = await _stage_session(agent, tmp_path)
    s = agent.sessions[sid]
    s.moving, s.state = {"at": datetime.now(UTC).isoformat(), "from": "hookstub:first", "to": "x"}, "closed"
    agent._clear_moving()
    assert s.moving is None and holder_on(s, "TD-1", datetime.now(UTC)).lost


@pytest.mark.unit
def test_an_unasked_move_passes_over_a_login_that_asks():
    rows = {lk: _row(f"acct-{i}", ["opus"]) for i, lk in enumerate(ORDER, 1)}
    rows["hookstub:first"]["state"] = "limited"
    rows["hookstub:second"]["asks"] = True
    assert teamstore.next_login(ORDER, "hookstub:first", "opus", rows) == "hookstub:second"
    assert teamstore.next_login(ORDER, "hookstub:first", "opus", rows, unasked=True) == "hookstub:third"


@pytest.mark.integration
async def test_an_unsupervised_session_is_never_moved(agent, tmp_path, launched, rows):
    sid = await _stage_session(agent, tmp_path)
    s = agent.sessions[sid]
    s.supervised = False
    await agent._login_moves(datetime.now(UTC))
    assert agent.sessions[sid] is s and s.state == "limited" and s.login == "hookstub:first"


@pytest.mark.integration
async def test_a_second_move_hands_over_its_own_handoff_alone(agent, tmp_path, launched, rows, monkeypatch):
    sid = await _stage_session(agent, tmp_path)
    await agent._login_moves(datetime.now(UTC))
    rows["hookstub:second"]["state"] = "limited"
    monkeypatch.setattr(adapters, "handoff_of", lambda ad, path: f"{adapters.HANDOFF_HEADING}\n\nlater")
    agent.sessions[sid].state = "limited"
    agent.sessions[sid].restarts[-1]["at"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    await agent._login_moves(datetime.now(UTC))
    assert agent.sessions[sid].login == "hookstub:third"
    told = launched[-1]["prompt"]
    assert "fixing the race" not in told and told.endswith("later") and told.count("before you stopped") == 1


@pytest.mark.integration
async def test_a_close_that_fails_after_it_closed_marks_the_record(agent, tmp_path, launched, rows, monkeypatch):
    sid = await _stage_session(agent, tmp_path)
    s = agent.sessions[sid]

    async def close(*a, **kw):
        s.state = "closed"
        raise RuntimeError("push failed")

    monkeypatch.setattr(agent, "_close", close)
    await agent._login_moves(datetime.now(UTC))
    assert s.moving is None and s.closed_for["why"] == "login-move"


def _state_store(tmp_path) -> StageStore:
    """A `shiftlead/state` branch in a scratch repo and its bare origin, as the stage pass writes its records."""
    origin, root = tmp_path / "state.git", tmp_path / "state"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    for args in (
        ("config", "user.email", "t@example.com"),
        ("config", "user.name", "t"),
        ("remote", "add", "origin", str(origin)),
        ("commit", "-q", "--allow-empty", "-m", "init"),
        ("push", "-q", "origin", "main"),
    ):
        subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
    store = StageStore(root)
    store.ensure_branch()
    return store


FLOW = {
    "format": 3,
    "name": "f",
    "stages": [
        {"name": "build", "does": "build", "model": "opus", "takes": "any", "work-pushed": "review"},
        {"name": "review", "does": "review", "model": "opus", "ship": "merge"},
    ],
}
ENTRY = "## TD-1: An entry\n\n**Priority:** Low\n**Status:** Open\n\n**Why:** It matters.\n"


@pytest.mark.integration
@pytest.mark.parametrize("launch", ["moved", "failed"])
async def test_a_move_leaves_its_stage_records_holder_offers_and_counts_as_they_were(
    agent, tmp_path, launched, rows, monkeypatch, launch
):
    """TD-2296, design §4.9e *A session moves down the list*: "A move spends no offer, no limit and nothing of the
    total cap". The stage pass that next reads the record finds its holder live under the same id and takes no act;
    a move whose launch failed is the control, its holder lost and offered again, so the reading is one that bites."""
    store = _state_store(tmp_path)
    sid = await _stage_session(agent, tmp_path)
    store.put_entry({**new_record("TD-1", "f", "build", team="t", holder=sid), "counts": {"build": 2}}, "test")
    if launch == "failed":
        monkeypatch.setattr(agent, "rpc_create", AsyncMock(side_effect=RuntimeError("no launch")))
    await agent._login_moves(datetime.now(UTC))
    started: list[str] = []
    reach = stage_pass.Reach(
        gate=lambda pr, head: {"verdict": "pass", "failed": []},
        land=lambda pr, head: None,
        start=lambda key, work: started.append(key) or "s2",
        claim=lambda holder, tid: None,
        end=lambda sid: None,
    )
    f = EntryFacts(
        tid="TD-1",
        person="paul",
        team="t",
        now=datetime.now(UTC),
        doc=FLOW,
        ledger=EntryLedger("open"),
        text=ENTRY,
        session=agent.sessions[sid],
        may_start=True,
        within_size=True,
    )
    got = stage_pass.step(store, store.entry("TD-1"), f, reach)
    after = store.entry("TD-1")
    if launch == "moved":
        assert got.read and got.act is None and started == [], "its holder is live: the pass takes no act"
        assert (after["holder"], after["offers"], after["counts"]) == (sid, 1, {"build": 2})
    else:
        assert got.act is not None and got.act.name == "offer-again"
        assert after["holder"] != sid and after["offers"] == 2, "a lost holder is offered again, an offer spent"
