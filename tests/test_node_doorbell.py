"""The doorbell rings a node's session through its node (design §4.4a, §4.10 *The doorbell*, TD-1051, built
by TD-1079): the home decides for every record whose link is up, keyed by its address and its stretch by
`since`; the node types the home's line under its own checks and answers `typed`, `busy` or `failed`; the
node stamps `ring_seen` at the ring's turn and Stop, and the home judges the ring once from that report."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import adapters, agent_common, link, mail
from sessionorc.agent_common import _Wait
from sessionorc.models import MailEntry, Session, now_iso

pytestmark = pytest.mark.integration

HOST = "laptop"
RID = "ao-w"
ADDR = f"{RID}@{HOST}"


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds").replace("+00:00", "Z")


class Node:
    """A fake link to `laptop`: each `ring` act answered by the next verdict queued (or raised)."""

    def __init__(self, rec: Session):
        self.rec, self.rings, self.verdicts = rec, [], []

    async def request(self, method, timeout=None, **params):
        if method != "act" or params.get("rpc") != "ring":
            return {}
        self.rings.append(params["params"])
        verdict = self.verdicts.pop(0) if self.verdicts else "typed"
        if isinstance(verdict, BaseException):
            raise verdict
        if verdict == "typed":
            self.rec.ring_seen = {"token": params["params"]["token"], "at": _iso(datetime.now(UTC))}
        if verdict == "failed" and params["params"]["retry"]:
            self.rec.doorbell_failed = {"at": _iso(datetime.now(UTC)), "error": "prompt-stuck: still there"}
        return {"result": verdict, "record": self.rec.to_dict()}

    async def notify(self, method, **params):
        pass

    def close(self, why="closed"):
        pass


async def _ring(agent) -> None:
    agent._ring_doorbells()
    await asyncio.gather(*list(agent._ringing.values()))


def _mail(agent, n: int = 1, read_at: str | None = None) -> None:
    box = agent.remote[HOST][RID].inbox
    for _ in range(n):
        at = _iso(datetime.now(UTC))
        box.append(MailEntry(id=f"m-{len(box):04x}", from_="ao-lead", to=[ADDR], at=at, kind="note", text="x"))
        box[-1].read_at = read_at


def _report(agent, node: Node) -> None:
    agent._take_records(HOST, [node.rec.to_dict()], whole=False)


@contextlib.asynccontextmanager
async def _linked(agent):
    """A hook-confirmed idle claude-code record on `laptop`, its link up, and the tick parked."""
    await park_ticks(agent)
    since = _iso(datetime.now(UTC) - timedelta(minutes=1))
    rec = Session(id=RID, name="w", kind="interactive", adapter="claude-code", dir="/x/w", host=HOST, unattended=True)
    rec.state, rec.confidence, rec.since = "idle", "hook", since
    node = Node(rec)
    agent._link_muxes[HOST] = node
    agent.links[HOST] = {"up": True, "since": "t", "why": "linked"}
    _report(agent, node)
    try:
        yield node
    finally:
        agent._link_muxes.pop(HOST, None)


async def test_a_node_record_is_rung_once_per_idle_stretch_with_the_homes_line(agent):
    async with _linked(agent) as node:
        _mail(agent)
        await _ring(agent)
        assert len(node.rings) == 1
        act = node.rings[0]
        assert (act["id"], act["retry"], act["since"]) == (RID, False, node.rec.since)
        assert act["line"] == mail.unread_line(1) and act["token"]
        home = agent.remote[HOST][RID]
        assert [(w["cause"], w["charged"], w["via"]) for w in home.wakes] == [("mail", True, "doorbell")]
        # the same stretch: more mail rings nothing
        _mail(agent)
        await _ring(agent)
        assert len(node.rings) == 1
        # a report changing only `ring_seen` or `doorbell_failed` keeps the stretch
        node.rec.doorbell_failed = {"at": _iso(datetime.now(UTC)), "error": "x"}
        _report(agent, node)
        await _ring(agent)
        assert len(node.rings) == 1
        # a node state change is a new stretch: rung again, the count all the unread mail
        node.rec.since = _iso(datetime.now(UTC) + timedelta(seconds=5))
        node.rec.doorbell_failed = None
        _report(agent, node)
        await _ring(agent)
        assert len(node.rings) == 2 and node.rings[1]["line"] == mail.unread_line(2)
        assert node.rings[1]["token"] != node.rings[0]["token"]


async def test_busy_charges_nothing_and_is_looked_at_again(agent):
    async with _linked(agent) as node:
        _mail(agent)
        node.verdicts = ["busy"]
        await _ring(agent)
        assert len(node.rings) == 1 and agent.remote[HOST][RID].wakes == []
        assert ADDR not in agent._bells
        await _ring(agent)
        assert len(node.rings) == 2 and node.rings[1]["retry"] is False
        assert len(agent.remote[HOST][RID].wakes) == 1


async def test_a_failed_ring_is_retried_once_then_the_nodes_doorbell_failed_says_so(agent):
    async with _linked(agent) as node:
        _mail(agent)
        node.verdicts = ["failed", "failed"]
        await _ring(agent)
        await _ring(agent)
        await _ring(agent)
        assert [r["retry"] for r in node.rings] == [False, True]
        home = agent.remote[HOST][RID]
        assert home.wakes == []  # a node's failed ring is not charged
        assert home.doorbell_failed and home.doorbell_failed["error"].startswith("prompt-stuck")
        _report(agent, node)  # the node's report of its `doorbell_failed` rings nothing more in the stretch
        await _ring(agent)
        assert len(node.rings) == 2
        said = mail.read_when(home, "note", datetime.now(UTC))
        assert said.startswith("lands; its doorbell failed at") and "rung" not in said
        # an older stretch's failure does not stand in this one's
        home.since = _iso(datetime.now(UTC) + timedelta(minutes=1))
        assert mail.read_when(home, "note", datetime.now(UTC)).startswith("rung within a tick")


async def test_no_verdict_charges_and_writes_nothing_and_rings_again_once_the_link_is_up(agent):
    async with _linked(agent) as node:
        _mail(agent)
        node.verdicts = [link.LinkClosed("dropped")]
        await _ring(agent)
        home = agent.remote[HOST][RID]
        assert len(node.rings) == 1 and home.wakes == [] and ADDR not in agent._bells
        assert home.doorbell_failed is None
        del agent._link_muxes[HOST]  # the link down: nothing is rung, and the sentence is *unreachable*
        await _ring(agent)
        assert len(node.rings) == 1
        assert mail.read_when(home, "note", datetime.now(UTC), unreachable=True).startswith("lands at the home")
        agent._link_muxes[HOST] = node
        await _ring(agent)
        assert len(node.rings) == 2 and node.rings[1]["retry"] is False and len(home.wakes) == 1


async def test_a_record_blocked_in_a_forwarded_wait_is_not_rung(agent):
    async with _linked(agent) as node:
        _mail(agent)
        bare = _Wait(RID)  # a home session of the same bare id: not this record
        agent._waits.add(bare)
        forwarded = _Wait(ADDR)
        agent._waits.add(forwarded)
        try:
            await _ring(agent)
            assert node.rings == []
            agent._waits.discard(forwarded)
            await _ring(agent)
            assert len(node.rings) == 1
        finally:
            agent._waits.discard(bare)
            agent._waits.discard(forwarded)


async def test_a_lapsed_cache_on_a_node_is_rung_never_restarted(agent, monkeypatch):
    monkeypatch.setattr(agent_common, "cache_restarts", lambda s, now: True)

    async def never(*a, **kw):
        raise AssertionError("a node's record is never cache-restarted")

    monkeypatch.setattr(agent, "_cache_restart", never)
    async with _linked(agent) as node:
        _mail(agent)
        await _ring(agent)
        assert len(node.rings) == 1


async def test_a_typed_ring_is_judged_once_from_the_report_bringing_its_stop(agent):
    async with _linked(agent) as node:
        before = _iso(datetime.now(UTC) - timedelta(seconds=30))
        _mail(agent, read_at=before)  # read before the ring's dispatch: never ends the run
        _mail(agent)
        await _ring(agent)
        assert ADDR in agent._rang
        node.rec.ring_seen = {**node.rec.ring_seen, "turned": _iso(datetime.now(UTC))}
        _report(agent, node)
        assert ADDR in agent._rang and ADDR not in agent._unread_rings  # its turn alone waits
        node.rec.ring_seen = {**node.rec.ring_seen, "stopped": _iso(datetime.now(UTC))}
        _report(agent, node)
        _report(agent, node)  # the same report twice counts once
        assert agent._unread_rings[ADDR] == 1 and ADDR not in agent._rang
        # two more rings with nothing read hold the bell, written on the home's copy
        for _ in range(2):
            node.rec.since = _iso(datetime.now(UTC) + timedelta(seconds=len(node.rings) * 5))
            _report(agent, node)
            _mail(agent)
            await _ring(agent)
            node.rec.ring_seen = {**node.rec.ring_seen, "turned": "t", "stopped": "t"}
            _report(agent, node)
        assert agent._unread_rings[ADDR] == 3 and agent.remote[HOST][RID].doorbell_held


async def test_a_read_after_the_ring_ends_the_run_and_a_newer_token_drops_the_judgement(agent):
    async with _linked(agent) as node:
        _mail(agent)
        await _ring(agent)
        agent._unread_rings[ADDR] = 2
        agent.remote[HOST][RID].inbox[0].read_at = now_iso()  # read at the home, just before the Stop
        node.rec.ring_seen = {**node.rec.ring_seen, "turned": "t", "stopped": "t"}
        _report(agent, node)
        assert ADDR not in agent._unread_rings and not agent.remote[HOST][RID].doorbell_held
        # a ring_seen of another token (a newer ring, or lost to a node restart): dropped, uncounted
        node.rec.since = _iso(datetime.now(UTC) + timedelta(seconds=5))
        _report(agent, node)
        _mail(agent)
        await _ring(agent)
        node.rec.ring_seen = None
        _report(agent, node)
        assert ADDR not in agent._rang and ADDR not in agent._unread_rings


# -- the node's half: `_ring_here` and the stamps ------------------------------------------------


class _Composer:
    def __init__(self):
        self.left = ""

    def composer(self, tail):
        return self.left


@pytest.fixture
async def here(agent, monkeypatch):
    """A node-mode agent holding `ao-w`, its pane's composer and its typing faked."""
    await park_ticks(agent)
    agent.mode, agent.home = "node", "kmaster"
    fake = _Composer()
    real = adapters.get
    monkeypatch.setattr(adapters, "get", lambda name: fake if name == "fake" else real(name))
    monkeypatch.setattr(agent.tmux, "capture_tail", lambda *a, **kw: ["> "])
    typed: list[str] = []

    async def _type(sid, adapter, text, **kw):
        if fake.left == "stuck":
            raise agent_common.RpcError("prompt-stuck: still there")
        typed.append(text)

    monkeypatch.setattr(agent, "_type", _type)
    s = Session(id=RID, name="w", kind="interactive", adapter="fake", dir="/x/w", host=agent.host, unattended=True)
    s.state, s.confidence, s.since = "idle", "hook", "2026-10-26T10:00:00Z"
    agent.sessions[RID] = s
    try:
        yield agent, s, fake, typed
    finally:
        agent.sessions.pop(RID, None)
        agent.mode, agent.home = "home", agent.host


def _act(**kw):
    base = {"id": RID, "retry": False, "since": "2026-10-26T10:00:00Z", "line": mail.unread_line(2), "token": "t1"}
    return {**base, **kw}


async def test_the_node_types_the_homes_line_and_stamps_ring_seen(here):
    agent, s, fake, typed = here
    got = await agent._ring_here(_act())
    assert got["result"] == "typed" and typed == [mail.unread_line(2)]
    assert got["record"]["ring_seen"]["token"] == "t1"
    with pytest.raises(agent_common.RpcError):
        await agent._ring_here(_act(line="rm -rf / 2"))
    # its hooks stamp the turn and the Stop after it
    agent._bell_answered(s, {"state": "idle"})
    assert "turned" not in s.ring_seen
    agent._bell_answered(s, {"prompt": "x"})
    agent._bell_answered(s, {"state": "idle"})
    assert s.ring_seen["turned"] and s.ring_seen["stopped"]


async def test_the_node_answers_busy_and_failed_by_its_own_checks(here):
    agent, s, fake, typed = here
    assert (await agent._ring_here(_act(since="2026-10-26T09:00:00Z")))["result"] == "busy"  # the state moved
    fake.left = "half-typed"
    assert (await agent._ring_here(_act()))["result"] == "busy"  # someone's words
    assert s.doorbell_failed is None
    # a retry finding a line in the composer is the first try's: failed, and the node writes it
    assert (await agent._ring_here(_act(retry=True)))["result"] == "failed"
    assert s.doorbell_failed["error"].startswith("prompt-stuck")
    # a first try whose paste does not submit fails without writing
    s.doorbell_failed = None
    fake.left = ""
    real = fake.composer
    fake.composer = lambda tail: ""
    fake.left = "stuck"
    assert (await agent._ring_here(_act()))["result"] == "failed" and s.doorbell_failed is None
    fake.composer = real
    assert typed == []
    async with agent._typing[RID]:
        fake.left = ""
        assert (await agent._ring_here(_act()))["result"] == "busy"  # a send is typing
