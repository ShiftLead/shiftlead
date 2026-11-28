"""TD-2069 slice 2, design §4.9e *A session moves down the list*: the tick of the home's host moves an unattended
session whose login is no longer usable to the next usable login of the list it was launched with that offers its
model, under the same record, told what its stage's session is told followed by the handoff; while its record is
marked `moving` no other rule acts on it, a failed launch leaves it ended, and a mark is never left standing."""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from _stubs import HookFedStub
from conftest import kill_private_server, park_ticks, private_socket_name, wait_for

from sessionorc import adapters, agent_common, hosts, paths, teamstore
from sessionorc.adapters import LaunchSpec
from sessionorc.agent import HostAgent
from sessionorc.client import LocalClient
from sessionorc.models import MailEntry, Session
from sessionorc.store import SessionStore
from sessionorc.tmux import Tmux
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


async def _stage_session(agent, tmp_path, *, unattended: bool = True, extra: str = "") -> str:
    """A stage's session as the stage pass launches it: supervised, on its list's first login, with its model."""
    await park_ticks(agent)
    (paths.home() / "logins.yml").write_text(LOGINS.replace("accounts: {}", extra + "accounts: {}"))
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


CASES = ["usable", "no-later", "interactive", "suspended", "exited", "superseded", "moving", "ceiling", "scheduled"]


@pytest.mark.integration
@pytest.mark.parametrize("case", CASES, ids=lambda c: c)
async def test_what_does_not_move(agent, tmp_path, launched, rows, case):
    """§4.9e *A session moves down the list*: `_movable` passes over each of these; the record stays the host's, in
    the state the case set, on its login (TD-2299: a moved session leaves its old record marked as it was)."""
    sid = await _stage_session(agent, tmp_path, unattended=case != "interactive")
    s = agent.sessions[sid]
    now = datetime.now(UTC)
    mark = None
    if case == "usable":
        rows["hookstub:first"]["state"] = "signed_in"
    elif case == "no-later":
        rows["hookstub:second"]["state"] = "limited"
        rows["hookstub:third"]["at_reserve"] = True
    elif case == "suspended":
        s.suspended = {"at": now.isoformat(), "by": "person", "why": "an identity alarm"}
    elif case == "exited":
        s.state = "exited"
    elif case == "superseded":
        s.superseded_by = "ao-x-later"
    elif case == "moving":
        mark = {"at": now.isoformat(), "from": "hookstub:first", "to": "hookstub:second"}
        s.moving = mark
    elif case == "ceiling":
        s.restart_ceiling = {"at": now.isoformat(), "count": 3}
    elif case == "scheduled":
        s.state = "scheduled"
    state, count = s.state, len(launched)
    await agent._login_moves(now)
    assert agent.sessions.get(sid) is s and s.state == state, "the same record, in the state the case set"
    assert s.login == "hookstub:first" and s.moving == mark
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
    assert agent.sessions[sid] is s and s.state == state, "the host still holds the same record, in the same state"
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
        assert agent.sessions[sid].login == "hookstub:second", "the move happened"
        assert got.read and got.act is None and started == [], "its holder is live: the pass takes no act"
        assert (after["holder"], after["offers"], after["counts"]) == (sid, 1, {"build": 2})
    else:
        assert got.act is not None and got.act.name == "offer-again"
        assert after["holder"] != sid and after["offers"] == 2, "a lost holder is offered again, an offer spent"


async def _owe(agent, sid: str) -> str:
    """`sid` asks the person, the person answers and `sid` reads it: `sid` owes an outcome on it (§4.10)."""
    async with LocalClient(caller=sid) as me:
        q = (await me.call("msg", to="person", text="which way?", kind="ask"))["entry"]
    async with LocalClient() as person:
        await person.call("msg", reply_to=q["id"], kind="reply", text="the left one")
    async with LocalClient(caller=sid) as me:
        await me.call("inbox")
    assert q["id"] in agent.sessions[sid].owed()
    return q["id"]


@pytest.mark.integration
async def test_a_move_keeps_the_sessions_mail_scratch_worktree_and_the_outcome_it_owes(
    agent, tmp_path, launched, rows, monkeypatch
):
    """TD-2300, design §4.9e *A session moves down the list*, §4.6, §4.10 *Outcomes*: the move closes the old run
    without reaping its worktree or settling what it owes, and replays it with its mail and its scratch."""
    sid = await _stage_session(agent, tmp_path)
    qid = await _owe(agent, sid)
    old = agent.sessions[sid]
    old.state = "limited"
    unread = MailEntry(id="m-u1", from_="ao-x-tl", to=[sid], at=datetime.now(UTC).isoformat(), kind="note", text="hi")
    old.inbox.append(unread)
    scratch = old.scratch
    assert scratch, "the stage's session has a scratch to keep"
    closes: list[dict] = []
    close = agent._close

    async def spy(*a, **kw):
        closes.append(kw)
        return await close(*a, **kw)

    monkeypatch.setattr(agent, "_close", spy)
    await agent._login_moves(datetime.now(UTC))
    new = agent.sessions[sid]
    assert new is not old and new.login == "hookstub:second", "the move happened"
    assert "m-u1" in [e.id for e in new.inbox], "its mail is the new record's"
    assert new.scratch == scratch, "its scratch is handed on, not made again"
    assert len(closes) == 1 and closes[0]["reap"] is False, "the close leaves the worktree for the replay"
    assert closes[0]["keep_debt"] is True
    assert qid in new.owed(), "the outcome it owes rides the move"
    assert next(e for e in agent.person_inbox if e.id == qid).owes


class _OtherStub(HookFedStub):
    name = "hookstub2"


@pytest.mark.integration
async def test_a_move_to_another_tools_login_launches_that_tool(agent, tmp_path, launched, rows, monkeypatch):
    """TD-2300: a list may name logins of two tools; the move launches the one `to` is a login of."""
    other = _OtherStub()
    monkeypatch.setitem(adapters._REGISTRY, other.name, other)
    tools: list[str] = []

    def launch(*, profile, resume, prompt, unattended, cwd, name="", **kw):
        tools.append(other.name)
        return LaunchSpec(argv=["bash", "--norc"])

    monkeypatch.setattr(other, "launch", launch)
    rows["hookstub:second"]["state"] = rows["hookstub:third"]["state"] = "limited"
    rows["hookstub2:fourth"] = _row("acct-4", ["opus"])
    sid = await _stage_session(agent, tmp_path, extra="  hookstub2:fourth: {folder: /c/fourth, account: acct-4}\n")
    agent.sessions[sid].login_list = [*ORDER, "hookstub2:fourth"]
    await agent._login_moves(datetime.now(UTC))
    new = agent.sessions[sid]
    assert (new.adapter, new.login) == ("hookstub2", "hookstub2:fourth") and tools == ["hookstub2"]


@pytest.mark.integration
async def test_a_second_move_adds_to_the_list_of_moves(agent, tmp_path, launched, rows):
    """TD-2300: `login_moves` keeps every move, not the last alone."""
    sid = await _stage_session(agent, tmp_path)
    await agent._login_moves(datetime.now(UTC))
    rows["hookstub:second"]["state"] = "limited"
    agent.sessions[sid].state = "limited"
    agent.sessions[sid].restarts[-1]["at"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    await agent._login_moves(datetime.now(UTC))
    moves = [(m["from"], m["to"]) for m in agent.sessions[sid].login_moves]
    assert moves == [("hookstub:first", "hookstub:second"), ("hookstub:second", "hookstub:third")]


@pytest.mark.integration
async def test_the_move_reads_the_projected_accounts_and_its_teams_reserve(
    agent, tmp_path, launched, rows, monkeypatch
):
    """TD-2301, design §4.9e and §6 *Usage gate*: the rows a move reads are the pick's own, handed the gate's accounts
    as projected to now and the extra reserve of the session's team."""
    sid = await _stage_session(agent, tmp_path)
    (paths.home() / "settings.yml").write_text("teams:\n  t: {reserve: 15}\n")
    raw = {"acct-1": {"windows": [{"label": "5h", "pct": 40}]}}
    projected = {"acct-1": {"windows": [{"label": "5h", "pct": 90, "projected": True}]}}
    monkeypatch.setattr(agent, "rpc_gate", AsyncMock(return_value={"accounts": raw}))
    handed: list = []

    def project(accounts, doc, now):
        handed.append(accounts)
        return projected

    def login_rows(read, accounts, extra, now):
        handed.append((accounts, extra))
        return rows

    monkeypatch.setattr(agent, "_projected", project)
    monkeypatch.setattr(teamstore, "login_rows", login_rows)
    await agent._login_moves(datetime.now(UTC))
    assert handed == [raw, (projected, 15)], "the projected accounts and the team's reserve"
    assert agent.sessions[sid].login == "hookstub:second"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("case", "want"), [("stage", "hookstub:second"), ("prompts", "hookstub:third"), ("director", "hookstub:third")]
)
async def test_the_director_and_a_prompts_seat_pass_over_a_login_that_asks(agent, tmp_path, launched, rows, case, want):
    """TD-2301, design §4.9d and §4.9e: a session on the director's record or the prompts seat's is moved past a
    login that asks, to the next that does not; any other session moves to the first usable one, asking or not."""
    rows["hookstub:second"]["asks"] = True
    sid = await _stage_session(agent, tmp_path)
    s = agent.sessions[sid]
    if case == "prompts":
        s.builtin = "prompts"
    elif case == "director":
        s.seat = {"trigger": "prompt"}
    await agent._login_moves(datetime.now(UTC))
    assert agent.sessions[sid].login == want


@pytest.mark.integration
async def test_a_tick_moves_a_session_at_its_line_before_the_usage_gate_pauses_it(
    agent, tmp_path, launched, rows, monkeypatch
):
    """TD-2301, design §6 *Usage gate* and §4.9e: in one tick the move runs before the gate, so a session whose login
    is at its line and has a usable one below is moved, its old record never marked `gated` and nothing typed into
    it; the gate reads the new record's login, which is under its line."""
    sid = await _stage_session(agent, tmp_path)
    old = agent.sessions[sid]
    old.state, old.pause_prompt = "working", "pause now"
    rows["hookstub:first"]["state"] = "signed_in"
    rows["hookstub:first"]["at_reserve"] = True
    monkeypatch.setattr(agent, "_gate_reserves", lambda whole, profile: {"5h": 30})
    over = [{"label": "5h", "pct": 95}]
    monkeypatch.setattr(agent, "_gate_windows", lambda profile, now, whole: over if profile == "first" else [])
    typed: list[tuple[str, str]] = []

    async def submit(sid, adapter, text):
        typed.append((sid, text))
        return ("", 0)

    monkeypatch.setattr(agent, "_submit", submit)
    assert old.profile == "first", "the gate reads the old record's login as over its line"
    await agent.tick()
    new = agent.sessions[sid]
    assert new is not old and new.login == "hookstub:second", "moved in the tick"
    assert old.gated is None and new.gated is None, "never marked by the gate"
    assert "pause now" not in [text for _, text in typed], "no pause line typed"


@pytest.mark.integration
async def test_a_host_agent_that_starts_on_a_stored_mark_clears_it_on_disk(tmp_path, monkeypatch):
    """TD-2302, design §4.9e *A mark is never left standing*: a host agent started on a store holding a record marked
    `moving` (a move its restart cut off) clears the mark and saves the record, so the next start reads none."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    paths.ensure_layout()
    mark = {"at": datetime.now(UTC).isoformat(), "from": "hookstub:first", "to": "hookstub:second"}
    s = Session(id="ao-w-move", name="w", kind="interactive", adapter="hookstub", dir=str(tmp_path), state="closed")
    s.host, s.moving = hosts.local_host().name, mark
    SessionStore().save(s)
    tmux = Tmux(socket_name=private_socket_name())
    a = HostAgent(tmux=tmux)
    assert a.sessions["ao-w-move"].moving == mark, "the record comes back marked"
    task = asyncio.create_task(a.serve(paths.socket_path()))
    try:
        assert await wait_for(lambda: paths.socket_path().exists(), timeout=5.0, step=0.05)
        assert a.sessions["ao-w-move"].moving is None
        assert SessionStore().load("ao-w-move").moving is None, "the cleared mark is saved"
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        kill_private_server(tmux)


@pytest.mark.integration
async def test_a_moves_mark_is_saved_before_the_old_session_is_closed(agent, tmp_path, launched, rows, monkeypatch):
    """TD-2302, design §4.9e: the mark is on disk before the handoff is read and the old session closed, so a restart
    in between finds it (and clears it) rather than a record that reads no move."""
    sid = await _stage_session(agent, tmp_path)
    seen: dict[str, object] = {}

    def handoff(ad, path):
        seen["handoff"] = agent.store.load(sid).moving
        return HANDOFF

    close = agent._close

    async def closing(*a, **kw):
        seen["close"] = agent.store.load(sid).moving
        return await close(*a, **kw)

    monkeypatch.setattr(adapters, "handoff_of", handoff)
    monkeypatch.setattr(agent, "_close", closing)
    await agent._login_moves(datetime.now(UTC))
    want = {"from": "hookstub:first", "to": "hookstub:second"}
    for at in ("handoff", "close"):
        assert isinstance(seen[at], dict) and {k: seen[at][k] for k in want} == want, at
    assert agent.sessions[sid].login == "hookstub:second" and agent.store.load(sid).moving is None


@pytest.mark.unit
def test_a_failed_move_counts_toward_the_ceiling_and_a_launched_one_does_not():
    """TD-2302, design §4.9e and §6 rule 1: a `login-move` entry counts only when its launch failed."""
    now = datetime.now(UTC)
    at = now.isoformat()
    failed = {"why": "login-move", "at": at, "error": "no launch"}
    assert agent_common._counted([failed], now) == [failed]
    assert agent_common._counted([{"why": "login-move", "at": at}], now) == []


class _HomeMux:
    """A node's link to its home, answering `login_move` as the home does (TD-2070): it ends the node's old session
    and launches the new one on `to` here, through the node's own close and create, unless told to fail."""

    def __init__(self, agent, repo, *, fails: Exception | None = None, launch: bool = True):
        self.agent, self.repo, self.fails, self.launch = agent, repo, fails, launch
        self.sent: list[dict] = []
        self.marked: list = []

    async def request(self, method, timeout=None, **params):
        if method != "login_move":
            return {}
        self.sent.append({"method": method, **params})
        self.marked.append(self.agent.sessions[params["id"]].moving)
        if self.fails is not None:
            raise self.fails
        s = self.agent.sessions[params["id"]]
        await self.agent._close(s.id, closer={"by": "tick", "why": "login-move"}, reap=False, keep_debt=True)
        if not self.launch:
            return {"moved": False, "why": "no launch"}
        await self.agent.rpc_create(
            name=s.name,
            dir=str(self.repo),
            adapter="hookstub",
            profile="",
            login=params["to"],
            seat_model="opus",
            login_list=ORDER,
            unattended=True,
            supervised=True,
            prompt=f"the stage's words\n\n{params['handoff']}",
            team="t",
            keep_mail=True,
        )
        return {"moved": True}


@pytest.mark.integration
async def test_a_nodes_tick_asks_the_home_to_move_and_writes_the_move_on_its_new_record(
    agent, tmp_path, launched, rows, monkeypatch
):
    """§4.9e, §4.4a *A login move from a node* (TD-2070): a node's tick reads its own logins, marks the record
    `moving` before it asks, and sends the home `login_move {id, to, handoff}`; once a new session runs on `to` the
    node clears the mark and adds the move to `login_moves`, which are its own fields."""
    sid = await _stage_session(agent, tmp_path)
    monkeypatch.setattr(agent, "mode", "node")
    monkeypatch.setattr(agent, "_switched_before_home", lambda: False)  # a switched node of a home cut over
    agent._home_mux = mux = _HomeMux(agent, tmp_path / "repo")
    try:
        await agent._login_moves(datetime.now(UTC))
    finally:
        agent._home_mux = None
    assert mux.sent == [{"method": "login_move", "id": sid, "to": "hookstub:second", "handoff": HANDOFF}]
    assert mux.marked[0]["from"] == "hookstub:first" and mux.marked[0]["to"] == "hookstub:second"
    new = agent.sessions[sid]
    assert new.login == "hookstub:second" and new.moving is None
    assert [(m["from"], m["to"]) for m in new.login_moves] == [("hookstub:first", "hookstub:second")]
    assert launched[-1]["prompt"].endswith(HANDOFF)


@pytest.mark.integration
@pytest.mark.parametrize("case", ["refused", "no-launch", "no-link"])
async def test_a_nodes_move_the_home_did_not_make_leaves_no_mark(agent, tmp_path, launched, rows, monkeypatch, case):
    """A home that refuses (an older build: *unknown link method*), a launch that failed, or no link: no session runs
    on the next login, so the node clears its mark on the old record and writes no move."""
    from sessionorc import link

    sid = await _stage_session(agent, tmp_path)
    s = agent.sessions[sid]
    monkeypatch.setattr(agent, "mode", "node")
    monkeypatch.setattr(agent, "_switched_before_home", lambda: False)
    fails = link.LinkError("unknown link method 'login_move'") if case == "refused" else None
    mux = _HomeMux(agent, tmp_path / "repo", fails=fails, launch=case != "no-launch")
    agent._home_mux = None if case == "no-link" else mux
    count = len(launched)
    try:
        await agent._login_moves(datetime.now(UTC))
    finally:
        agent._home_mux = None
    assert agent.sessions[sid] is s and s.moving is None and s.login_moves == []
    assert len(launched) == count
    assert len(mux.sent) == (0 if case == "no-link" else 1)
    assert (s.state == "closed") == (case == "no-launch"), "only the home's close ends it"


def _node_record(agent, **kw) -> Session:
    """A stage's session on node `laptop` as the home holds it, with its launch record at the home."""
    import json

    s = Session(id="ao-build", name="build", kind="claude", adapter="hookstub", dir="/w", state="limited")
    s.host, s.supervised, s.unattended, s.team = "laptop", True, True, "t"
    s.login, s.seat_model, s.login_list = "hookstub:first", "opus", list(ORDER)
    for k, v in kw.items():
        setattr(s, k, v)
    agent.remote["laptop"] = {s.id: s}
    paths.launch_dir().mkdir(parents=True, exist_ok=True)
    launch = {"name": "build", "dir": "/w", "adapter": "hookstub", "profile": "", "prompt": "the stage's words"}
    launch |= {"unattended": True, "team": "t", "seat_model": "opus", "login_list": ORDER}
    (paths.launch_dir() / "ao-build@laptop.json").write_text(json.dumps(launch))
    return s


@pytest.mark.integration
async def test_the_home_moves_a_nodes_session_through_act_and_writes_none_of_the_nodes_fields(agent, monkeypatch):
    """The home takes `login_move` (§4.4a, TD-2070): it ends the old session at the node and replays its launch
    record there on `to`, the handoff after its stage's words, under the same record; `moving` and `login_moves`
    are the node's, so the home's answer is `{moved}` and nothing more."""
    await park_ticks(agent)
    s = _node_record(agent)
    acts: list[tuple[str, dict]] = []

    async def route(method, params, caller, host):
        acts.append((method, params))
        assert host == "laptop"
        if method == "close":
            s.state = "closed"
            return s.view()
        new = Session(id="ao-build", name="build", kind="claude", adapter="hookstub", dir="/w", state="working")
        new.host, new.login = "laptop", params["login"]
        agent.remote["laptop"]["ao-build"] = new
        return {"id": "ao-build@laptop"}

    monkeypatch.setattr(agent, "_route_act", route)
    got = await agent._take_login_move("laptop", {"id": "ao-build", "to": "hookstub:third", "handoff": HANDOFF})
    assert got == {"moved": True}
    (m1, close), (m2, create) = acts
    assert (m1, close["id"], close["closer"]["why"], close["reap"]) == ("close", "ao-build", "login-move", False)
    assert (m2, create["login"], create["adapter"], create["profile"]) == ("create", "hookstub:third", "hookstub", "")
    assert create["prompt"] == f"the stage's words\n\n{HANDOFF}" and create["host"] == "laptop"
    new = agent.remote["laptop"]["ao-build"]
    assert new is not s and new.restarts[-1]["why"] == "login-move"
    assert new.moving is None and new.login_moves == [], "the node's fields, written there"
    assert s.closed_for["why"] == "login-move"


@pytest.mark.integration
async def test_a_failed_launch_of_a_nodes_move_is_answered_not_moved(agent, monkeypatch):
    await park_ticks(agent)
    s = _node_record(agent)

    async def route(method, params, caller, host):
        if method == "close":
            s.state = "closed"
            return s.view()
        raise RuntimeError("no launch there")

    monkeypatch.setattr(agent, "_route_act", route)
    got = await agent._take_login_move("laptop", {"id": "ao-build", "to": "hookstub:second", "handoff": ""})
    assert got["moved"] is False and "no launch there" in got["why"]
    assert agent.remote["laptop"]["ao-build"] is s and s.restarts[-1]["error"]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("params", "kw"),
    [
        ({"id": "ao-gone", "to": "hookstub:second"}, {}),
        ({"id": "ao-build@laptop", "to": "hookstub:second"}, {}),
        ({"id": "ao-build"}, {}),
        ({"id": "ao-build", "to": "hookstub:second", "handoff": 3}, {}),
        ({"id": "ao-build", "to": "hookstub:other"}, {}),
        ({"id": "ao-build", "to": "hookstub:first"}, {"login": "hookstub:second"}),
        ({"id": "ao-build", "to": "hookstub:second"}, {"state": "closed"}),
        ({"id": "ao-build", "to": "hookstub:second"}, {"unattended": False}),
        ({"id": "ao-build", "to": "hookstub:second"}, {"superseded_by": "ao-later"}),
        ({"id": "ao-build", "to": "hookstub:second"}, {"login_list": []}),
    ],
    ids=[
        "no-record",
        "address",
        "no-login",
        "handoff-not-text",
        "not-listed",
        "up-the-list",
        "closed",
        "interactive",
        "superseded",
        "no-list",
    ],  # fmt: skip
)
async def test_the_home_refuses_a_login_move_no_move_applies_to(agent, monkeypatch, params, kw):
    from sessionorc import link

    await park_ticks(agent)
    _node_record(agent, **kw)
    routed = AsyncMock()
    monkeypatch.setattr(agent, "_route_act", routed)
    with pytest.raises(link.LinkError):
        await agent._take_login_move("laptop", params)
    routed.assert_not_called()
