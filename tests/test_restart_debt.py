"""TD-1516 (design §4.9a *The third declaration*, §4.10 *Outcomes*, TD-1485): the later of `none` and
`restart` stands, and an owed outcome rides a restart the tick replays — through the close made for the
replay, to the next run's `mail.owed` — while a person's Close, a forget and a create that does not carry
the mail settle it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks, wait_for

from sessionorc.agent import RpcError
from sessionorc.client import LocalClient

pytestmark = pytest.mark.integration

CLEAN = {"branch": "w", "dirty": 0, "unpushed": 0, "upstream": "origin/w"}


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


async def _painted(agent, sid: str) -> bool:
    return any(t.startswith(">>") for t in await agent.rpc_tail(sid, 3))


async def _member(agent, person, tmp_path, name="w", **kw) -> str:
    (tmp_path / name).mkdir(exist_ok=True)
    params = {
        "name": name,
        "dir": str(tmp_path / name),
        "adapter": "composer0",
        "unattended": True,
        "supervised": True,
        "prompt": "the brief",
    }
    sid = (await person.call("create", **{**params, **kw}))["id"]
    assert await wait_for(lambda: _painted(agent, sid), timeout=5), "the composer child never painted its prompt"
    return sid


async def _owe(agent, person, sid: str) -> str:
    """`sid` asks the person, the person answers: `sid` owes an outcome on it (§4.10)."""
    async with LocalClient(caller=sid) as me:
        q = (await me.call("msg", to="person", text="which way?", kind="ask"))["entry"]
    await person.call("msg", reply_to=q["id"], kind="reply", text="the left one")
    async with LocalClient(caller=sid) as me:
        await me.call("inbox")  # read: an unread reply refuses either declaration
    assert q["id"] in agent.sessions[sid].owed()
    return q["id"]


def _person_copy(agent, qid: str):
    return next(e for e in agent.person_inbox if e.id == qid)


async def _declare(agent, sid: str, status: str, why: str = "x"):
    return await agent.rpc_progress(id=sid, status=status, why=why, caller=sid)


async def test_the_later_declaration_stands(agent, composerstubs, tmp_path, monkeypatch):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        rec = agent.sessions[sid]
        await _declare(agent, sid, "none", "nothing left")
        rec.lane_seen = {"at": _iso(datetime.now(UTC)), "ids": []}
        await _declare(agent, sid, "restart", "context bound")
        assert rec.out_of_work is None and rec.lane_seen is None and rec.restart_wanted["why"] == "context bound"

        rec.restart_blocked, rec.restart_blocked_sent_at = {"dirty": 1}, _iso(datetime.now(UTC))
        rec.restart_ceiling = {"at": _iso(datetime.now(UTC)), "count": 3}
        await _declare(agent, sid, "none", "nothing after all")
        assert rec.restart_wanted is None and rec.restart_blocked is None and rec.restart_blocked_sent_at is None
        assert rec.restart_ceiling is not None, "the ceiling counts runs, not words"
        assert rec.out_of_work["why"] == "nothing after all"

        # a `none` the balance check refuses clears nothing
        await _declare(agent, sid, "restart", "context bound")
        monkeypatch.setattr(agent, "_balance_refusal", lambda s, ref, caller: "over its line")
        with pytest.raises(RpcError, match="over its line"):
            await _declare(agent, sid, "none")
        assert rec.restart_wanted["why"] == "context bound" and rec.out_of_work is None
        await person.call("kill", id=sid)


async def test_a_restart_with_an_owed_outcome_is_taken_only_where_the_tick_replays_it(agent, composerstubs, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        qid = await _owe(agent, person, sid)
        with pytest.raises(RpcError, match="owes 1 outcome.*none is the run with no successor"):
            await _declare(agent, sid, "none")
        await _declare(agent, sid, "restart", "context bound")
        assert agent.sessions[sid].restart_wanted

        loose = await _member(agent, person, tmp_path, name="loose", supervised=False)
        await _owe(agent, person, loose)
        with pytest.raises(RpcError, match="not a member the tick replays"):
            await _declare(agent, loose, "restart")
        seat = await _member(agent, person, tmp_path, name="seat", seat={"trigger": "asks"})
        await _owe(agent, person, seat)
        with pytest.raises(RpcError, match="not a member the tick replays"):
            await _declare(agent, seat, "restart")
        assert _person_copy(agent, qid).owes
        for r in (sid, loose, seat):
            await person.call("kill", id=r)


async def test_rule_2_replay_carries_the_debt_to_the_next_run(agent, composerstubs, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        qid = await _owe(agent, person, sid)
        rec = agent.sessions[sid]
        await agent.rpc_hook(sid, state="idle")
        rec.since = _iso(now - timedelta(minutes=1))
        rec.restart_wanted = {"at": _iso(now), "why": "context bound"}
        rec.git = dict(CLEAN)
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert new is not rec and [r["why"] for r in new.restarts] == ["wanted"]
        assert qid in new.owed(), "the replay keeps the mail, and the debt with it"
        assert _person_copy(agent, qid).owes
        with pytest.raises(RpcError, match="owes 1 outcome"):
            await _declare(agent, sid, "none")
        async with LocalClient(caller=sid) as me:
            await me.call("msg", to="person", text="took the left, PR 1", outcome="done", for_=qid)
        assert new.owed() == []
        await person.call("kill", id=sid)


@pytest.mark.parametrize("keep", [True, False])
async def test_a_replays_close_leaves_the_debt_and_any_other_close_settles_it(agent, composerstubs, tmp_path, keep):
    """The tick's closes before a replay with the mail (rule 2's `wanted`, rule 7's `brief`/`flow`/`cache`,
    rule 1's lost brief) and a person's Restart's all pass `keep_debt` to `_close`; `rpc_close` never can."""
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        qid = await _owe(agent, person, sid)
        await agent.rpc_hook(sid, state="idle")
        if keep:
            await agent._close(sid, closer={"by": "tick", "why": "wanted"}, reap=False, keep_debt=True)
        else:
            await person.call("close", id=sid)
        assert agent.sessions[sid].state == "closed"
        assert _person_copy(agent, qid).owes is keep
        if keep:  # a forget of the record never replayed settles it
            await person.call("remove", id=sid)
            assert not _person_copy(agent, qid).owes


async def test_rpc_close_takes_no_keep_debt(agent):
    import inspect

    assert "keep_debt" not in inspect.signature(agent.rpc_close).parameters
    assert "keep_debt" in inspect.signature(agent._close).parameters


async def test_the_ticks_replay_closes_all_keep_the_debt():
    """Each of the tick's closes before a replay with the mail goes through `_close(… keep_debt=True)`."""
    import inspect

    from sessionorc import agent_tick

    for fn in ("_lost_brief", "_wanted_restart", "_brief_restart", "_cache_restart"):
        body = inspect.getsource(getattr(agent_tick.TickMixin, fn))
        assert "self._close(" in body and "keep_debt=True" in body, fn
        assert "self.rpc_close(" not in body, fn


async def test_a_persons_restart_carries_the_debt(agent, composerstubs, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        qid = await _owe(agent, person, sid)
        rec = agent.sessions[sid]
        await agent.rpc_hook(sid, state="idle")
        rec.git = dict(CLEAN)
        await person.call("restart", id=sid)
        new = agent.sessions[sid]
        assert new is not rec and qid in new.owed() and _person_copy(agent, qid).owes
        await person.call("kill", id=sid)


async def test_a_create_without_the_mail_settles_the_debt_once_it_stands(agent, composerstubs, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        qid = await _owe(agent, person, sid)
        await person.call("kill", id=sid)
        assert _person_copy(agent, qid).owes, "an exited asker still owes"

        # a launch that fails leaves it
        with pytest.raises(Exception):  # noqa: B017 — whatever the create raises, it did not stand
            await person.call("create", name="w", dir=str(tmp_path / "w"), adapter="no-such-adapter", unattended=True)
        assert _person_copy(agent, qid).owes

        # with keep_mail the next run carries it
        await _member(agent, person, tmp_path, keep_mail=True)
        assert qid in agent.sessions[sid].owed() and _person_copy(agent, qid).owes
        await person.call("kill", id=sid)

        # without it the create replaces the mail in place: settled
        await _member(agent, person, tmp_path)
        assert not _person_copy(agent, qid).owes
        assert _person_copy(agent, qid).outcome["state"] == "asker_gone"
        await person.call("kill", id=sid)


async def test_scheduling_a_start_under_the_name_settles_the_debt(agent, composerstubs, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        qid = await _owe(agent, person, sid)
        await person.call("kill", id=sid)
        later = _iso(datetime.now(UTC) + timedelta(hours=2))
        (tmp_path / "w").mkdir(exist_ok=True)
        await person.call(
            "create",
            name="w",
            dir=str(tmp_path / "w"),
            adapter="composer0",
            unattended=True,
            supervised=True,
            prompt="the brief",
            start_at=later,
            keep_mail=True,
        )
        assert agent.sessions[sid].state == "scheduled"
        assert not _person_copy(agent, qid).owes
        await person.call("close", id=sid)


async def test_a_held_seat_with_keep_mail_settles_nothing(agent, composerstubs, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path, seat={"trigger": "asks"})
        qid = await _owe(agent, person, sid)
        await person.call("kill", id=sid)
        await person.call(
            "create",
            name="w",
            dir=str(tmp_path / "w"),
            adapter="composer0",
            unattended=True,
            supervised=True,
            prompt="the brief",
            seat={"trigger": "asks"},
            held=True,
            keep_mail=True,
        )
        assert agent.sessions[sid].state == "closed" and qid in agent.sessions[sid].owed()
        assert _person_copy(agent, qid).owes
