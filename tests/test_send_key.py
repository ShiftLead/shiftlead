"""A send lands once (design §4.10 *A send lands once*, TD-806, TD-813): a `send` carrying a `key` that
an entry of `sends` from the same caller holds, within `SEND_KEY_SECONDS`, answers as that send did —
its verdict, or its outcome once it ends — and types nothing, stamps nothing, refills nothing."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import mail
from sessionorc.agent_common import RpcError
from sessionorc.models import Pending, SendEntry, Session, apply_node


class Typist:
    """The paste, counted: each call records its text, then waits on `gate` and raises `fail` if set."""

    def __init__(self, agent, monkeypatch):
        self.typed: list[str] = []
        self.gate: asyncio.Event | None = None
        self.fail: BaseException | None = None

        async def fake_type(sid, adapter, text, *a, **kw):
            self.typed.append(text)
            if self.gate is not None:
                await self.gate.wait()
            if self.fail is not None:
                raise self.fail

        monkeypatch.setattr(agent, "_type", fake_type)


def _rec(agent, sid="ao-w", **kw) -> Session:
    s = Session(id=sid, name=sid, kind="interactive", adapter="claude-code", dir="/tmp", host=agent.host, state="idle")
    for k, v in kw.items():
        setattr(s, k, v)
    agent.sessions[sid] = s
    return s


async def _until(pred, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        if pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("never")


async def test_a_keyed_repeat_after_a_delivered_send_types_nothing_and_answers_ok(agent, monkeypatch):
    await park_ticks(agent)
    t = Typist(agent, monkeypatch)
    s = _rec(agent)
    assert await agent.rpc_send(id=s.id, text="go", key="k1", wrapup=True) is None
    assert t.typed == ["go"] and s.sends[-1].key == "k1" and s.wrapup_at
    # the record as the first send left it, then moved on: a repeat stamps, refills and refuses nothing
    s.wrapup_at = s.wrapup_by = s.wake_refilled_at = None
    s.pending = Pending(kind="permission", text="Bash")
    assert await agent.rpc_send(id=s.id, text="go", key="k1", wrapup=True, wait=True) is None
    assert t.typed == ["go"] and len(s.sends) == 1
    assert s.wrapup_at is None and s.wake_refilled_at is None
    s.pending, s.state = None, "exited"  # a session that has since exited still answers as delivered
    assert await agent.rpc_send(id=s.id, text="go", key="k1") is None
    with pytest.raises(RpcError, match="has exited"):  # a new key is a new send
        await agent.rpc_send(id=s.id, text="go", key="k2")
    assert t.typed == ["go"]


async def test_a_repeat_while_the_first_is_typing_awaits_it_with_one_paste(agent, monkeypatch):
    await park_ticks(agent)
    t = Typist(agent, monkeypatch)
    t.gate = asyncio.Event()
    s = _rec(agent)
    first = asyncio.create_task(agent.rpc_send(id=s.id, text="go", key="k"))
    await _until(lambda: t.typed)
    again = asyncio.create_task(agent.rpc_send(id=s.id, text="go", key="k"))
    await asyncio.sleep(0.05)
    assert not again.done()
    t.gate.set()
    assert await first is None and await again is None
    assert t.typed == ["go"] and not agent._keyed_sends


async def test_a_paste_that_fails_unworded_still_answers_the_waiting_repeat(agent, monkeypatch):
    await park_ticks(agent)
    t = Typist(agent, monkeypatch)
    t.gate, t.fail = asyncio.Event(), RuntimeError("tmux: no server")
    s = _rec(agent)
    first = asyncio.create_task(agent.rpc_send(id=s.id, text="go", key="k"))
    await _until(lambda: t.typed)
    again = asyncio.create_task(agent.rpc_send(id=s.id, text="go", key="k"))
    await asyncio.sleep(0.05)
    t.gate.set()
    for task in (first, again):
        with pytest.raises(RuntimeError, match="no server"):
            await task
    assert t.typed == ["go"] and s.sends[-1].verdict == "submitted"  # as a restart leaves it


async def test_after_a_prompt_stuck_the_repeat_raises_the_same_verdict(agent, monkeypatch):
    await park_ticks(agent)
    t = Typist(agent, monkeypatch)
    t.fail = RpcError("prompt-stuck: the composer did not empty")
    s = _rec(agent)
    for _ in range(2):
        with pytest.raises(RpcError, match="^prompt-stuck: the composer did not empty$"):
            await agent.rpc_send(id=s.id, text="go", key="k")
    assert t.typed == ["go"]


async def test_another_caller_an_old_key_a_pruned_key_and_no_key_are_typed(agent, monkeypatch):
    await park_ticks(agent)
    t = Typist(agent, monkeypatch)
    s = _rec(agent)
    _rec(agent, "ao-lead")
    await agent.rpc_send(id=s.id, text="a", key="k")
    await agent.rpc_send(id=s.id, text="b", key="k", caller="ao-lead")  # another caller's key is its own
    assert t.typed == ["a", "b"]
    await agent.rpc_send(id=s.id, text="c")
    await agent.rpc_send(id=s.id, text="c")  # no key: as before
    assert t.typed == ["a", "b", "c", "c"]
    old = datetime.now(UTC) - timedelta(seconds=mail.SEND_KEY_SECONDS + 5)
    s.sends.append(SendEntry(id="s-old", from_="person", at=old.isoformat().replace("+00:00", "Z"), text="o", key="ko"))
    await agent.rpc_send(id=s.id, text="o", key="ko")  # past the window
    await agent.rpc_send(id=s.id, text="p", key="kp")
    for i in range(mail.SENDS_KEEP):
        await agent.rpc_send(id=s.id, text=f"x{i}")
    await agent.rpc_send(id=s.id, text="p", key="kp")  # pushed out of `sends`
    assert t.typed.count("o") == 1 and t.typed.count("p") == 2


async def test_a_repeat_after_a_resume_answers_at_the_new_id_and_is_refused_as_closed_at_the_old(agent, monkeypatch):
    await park_ticks(agent)
    t = Typist(agent, monkeypatch)
    old = _rec(agent, "ao-old")
    await agent.rpc_send(id=old.id, text="go", key="k")
    new = _rec(agent, "ao-new")
    agent._move_mail(old, new)
    old.state, old.superseded_by = "closed", new.id
    assert await agent.rpc_send(id=new.id, text="go", key="k") is None
    with pytest.raises(RpcError, match="is closed; it was resumed as ao-new"):
        await agent.rpc_send(id=old.id, text="go", key="k")
    assert t.typed == ["go"]


@pytest.mark.unit
def test_the_key_survives_the_record_and_the_nodes_merge():
    e = SendEntry(id="s-1", from_="person", at="2026-10-16T00:00:00Z", text="go", key="k")
    assert SendEntry.from_dict(e.to_dict()).key == "k"
    assert SendEntry.from_dict({k: v for k, v in e.to_dict().items() if k != "key"}).key is None  # an older copy
    home = Session(id="ao-w", name="w", kind="interactive", adapter="claude-code", dir="/tmp", host="laptop")
    report = Session(**{**{f: getattr(home, f) for f in ("id", "name", "kind", "adapter", "dir", "host")}})
    report.sends = [e]
    merged = apply_node(home, report.to_dict())
    assert [x.key for x in merged.sends] == ["k"]


async def test_the_key_crosses_the_link_in_the_sends_arguments(agent):
    """The match is made where the pane is (§4.10 *Where it is matched*): `_route_act` forwards the key."""
    from test_person_shell_link import Node, _linked, _record

    await park_ticks(agent)
    agent._take_records("laptop", [_record("ao-x-w", adapter="claude-code")], whole=True)
    node = Node()
    _linked(agent, node)
    try:
        got = await agent._dispatch(
            {"id": 1, "method": "send", "params": {"id": "ao-x-w@laptop", "text": "go", "key": "k"}, "caller": None}
        )
        assert "error" not in got, got
        assert node.acts[-1]["rpc"] == "send" and node.acts[-1]["params"]["key"] == "k"
    finally:
        del agent._link_muxes["laptop"]
