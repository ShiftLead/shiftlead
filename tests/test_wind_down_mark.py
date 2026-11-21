"""A Wind down's mark (design §4.9a *A wind-down closes its members*, TD-1898): `send(wrapup=True, wind_down=True)`
stamps `wind_down: {at, by, waits}` once its prompt is submitted; a refused or failed send leaves none; a person's
later send moves it, a controller's plain send clears it, a session's send to itself leaves it; and `winding` is the
one reading every pass that holds a stopping record off reads."""

from __future__ import annotations

import pytest
from conftest import park_ticks

from sessionorc.agent_common import RpcError
from sessionorc.models import Pending, Session, winding


class Typist:
    def __init__(self, agent, monkeypatch):
        self.typed: list[str] = []
        self.fail: BaseException | None = None

        async def fake_type(sid, adapter, text, *a, **kw):
            self.typed.append(text)
            if self.fail is not None:
                raise self.fail

        monkeypatch.setattr(agent, "_type", fake_type)


def _rec(agent, sid, **kw) -> Session:
    s = Session(id=sid, name=sid, kind="interactive", adapter="claude-code", dir="/tmp", host=agent.host, state="idle")
    s.unattended = True
    for k, v in kw.items():
        setattr(s, k, v)
    agent.sessions[sid] = s
    return s


def _team(agent):
    mgr = _rec(agent, "ao-mgr", team="t", capabilities=["control"])
    member = _rec(agent, "ao-w", team="t", controllers=["ao-mgr"])
    return mgr, member


async def test_a_wind_down_send_marks_the_member_once_submitted(agent, monkeypatch):
    await park_ticks(agent)
    Typist(agent, monkeypatch)
    _, w = _team(agent)
    await agent.rpc_send(id=w.id, text="wrap up", wrapup=True, wind_down=True)
    assert w.wrapup_at and w.wrapup_by == "person"
    assert w.wind_down["by"] == "person" and w.wind_down["waits"] is True and w.wind_down["at"]
    assert winding(w) and winding(w.view())
    assert agent.store.load(w.id).wind_down == w.wind_down  # saved, and carried in the view
    assert w.view()["wind_down"] == w.wind_down


async def test_a_session_presses_it_and_a_second_session_press_keeps_the_persons_word(agent, monkeypatch):
    await park_ticks(agent)
    Typist(agent, monkeypatch)
    _, w = _team(agent)
    await agent.rpc_send(id=w.id, text="wrap up", wrapup=True, wind_down=True, caller="ao-mgr")
    assert w.wind_down["by"] == "ao-mgr"
    await agent.rpc_send(id=w.id, text="wrap up", wrapup=True, wind_down=True)
    assert w.wind_down["by"] == "person"
    await agent.rpc_send(id=w.id, text="wrap up", wrapup=True, wind_down=True, caller="ao-mgr")
    assert w.wind_down["by"] == "person"


async def test_a_seat_a_plain_send_and_wind_down_without_wrapup_stamp_nothing(agent, monkeypatch):
    await park_ticks(agent)
    t = Typist(agent, monkeypatch)
    seat = _rec(agent, "ao-seat", team="t", seat="techlead")
    await agent.rpc_send(id=seat.id, text="wrap up", wrapup=True, wind_down=True)
    assert t.typed == ["wrap up"] and seat.wrapup_at and seat.wind_down is None  # a plain wrap-up, never raising
    _, w = _team(agent)
    await agent.rpc_send(id=w.id, text="go on", wind_down=True)
    assert w.wind_down is None and not winding(w)


async def test_a_refused_or_failed_send_leaves_no_mark(agent, monkeypatch):
    await park_ticks(agent)
    t = Typist(agent, monkeypatch)
    _, w = _team(agent)
    w.pending = Pending(kind="permission", text="Bash")
    with pytest.raises(RpcError):
        await agent.rpc_send(id=w.id, text="wrap up", wrapup=True, wind_down=True)
    assert w.wind_down is None and not w.wrapup_at
    w.pending = None
    t.fail = RpcError("the paste did not land")
    with pytest.raises(RpcError):
        await agent.rpc_send(id=w.id, text="wrap up", wrapup=True, wind_down=True)
    assert w.wind_down is None
    assert w.wrapup_at and winding(w)  # the stamp before `_submit` stays, as today: held off, never closed by it


async def test_a_persons_send_moves_the_mark_and_takes_the_persons_word(agent, monkeypatch):
    await park_ticks(agent)
    Typist(agent, monkeypatch)
    _, w = _team(agent)
    await agent.rpc_send(id=w.id, text="wrap up", wrapup=True, wind_down=True, caller="ao-mgr")
    w.wind_down = {**w.wind_down, "at": "2026-01-01T00:00:00Z", "waits": False}
    await agent.rpc_send(id=w.id, text="push it")
    assert w.wind_down["by"] == "person" and w.wind_down["waits"] is True
    assert w.wind_down["at"] > "2026-01-01T00:00:00Z"
    assert w.wrapup_at is None and w.wrapup_by is None and winding(w)  # no wrap-up, so cleared; the mark holds


async def test_a_card_wrap_up_on_a_finished_marked_member_sets_waits(agent, monkeypatch):
    await park_ticks(agent)
    Typist(agent, monkeypatch)
    _, w = _team(agent)
    w.wind_down = {"at": "2026-01-01T00:00:00Z", "by": "ao-mgr", "waits": False}
    await agent.rpc_send(id=w.id, text="wrap up", wrapup=True)
    assert w.wind_down["waits"] is True and w.wind_down["by"] == "person"


async def test_the_managers_inert_mark_keeps_its_by_under_the_persons_send(agent, monkeypatch):
    await park_ticks(agent)
    Typist(agent, monkeypatch)
    mgr, _ = _team(agent)
    mgr.wind_down = {"at": "2026-01-01T00:00:00Z", "by": "ao-mgr", "waits": False}
    await agent.rpc_send(id=mgr.id, text="push it")
    assert mgr.wind_down["by"] == "ao-mgr" and mgr.wind_down["waits"] is True


async def test_a_controllers_plain_send_clears_the_mark_and_a_send_to_itself_leaves_it(agent, monkeypatch):
    await park_ticks(agent)
    t = Typist(agent, monkeypatch)
    _, w = _team(agent)
    mark = {"at": "2026-01-01T00:00:00Z", "by": "person", "waits": False}
    w.wind_down = dict(mark)
    await agent.rpc_send(id=w.id, text="note to self", caller=w.id)
    assert w.wind_down == mark
    t.fail = RpcError("the paste did not land")
    with pytest.raises(RpcError):
        await agent.rpc_send(id=w.id, text="also push X", caller="ao-mgr")
    assert w.wind_down == mark  # a failed controller send leaves it
    t.fail = None
    await agent.rpc_send(id=w.id, text="also push X", caller="ao-mgr")
    assert w.wind_down is None and not winding(w)


def test_winding_reads_each_mark_on_a_record_and_on_a_view():
    s = Session(id="x", name="x", kind="interactive", adapter="claude-code", dir="/tmp", host="h", state="idle")
    assert not winding(s) and not winding(s.view())
    for field, value in (
        ("wrapup_at", "2026-01-01T00:00:00Z"),
        ("wrapup_sent_at", "2026-01-01T00:00:00Z"),
        ("wind_down", {"at": "2026-01-01T00:00:00Z", "by": "person", "waits": False}),
    ):
        r = Session(id="x", name="x", kind="interactive", adapter="claude-code", dir="/tmp", host="h", state="idle")
        setattr(r, field, value)
        assert winding(r) and winding(r.view()), field


async def test_the_home_hands_a_nodes_send_its_reading_of_the_manager(agent, monkeypatch):
    """A node holds none of the team's other records, so the home's route sets `manager` on every send, over any
    caller's value; the node reads only that, and a node's member mark takes the person's word from it."""
    await park_ticks(agent)
    mgr = _rec(agent, "ao-mgr", team="t", capabilities=["control"])
    w = Session(id="ao-w", name="ao-w", kind="interactive", adapter="claude-code", dir="/tmp", host="node")
    w.unattended, w.team, w.controllers, w.state = True, "t", [mgr.id], "idle"
    agent.remote = {"node": {"ao-w": w}}
    sent: list[dict] = []

    class Mux:
        async def request(self, name, timeout=None, **kw):
            sent.append(kw["params"])
            return None

    monkeypatch.setattr(agent, "_node_mux", lambda host: Mux())
    await agent._route_act("send", {"id": "ao-w@node", "text": "go", "manager": "ao-w"}, None, "node")
    assert sent[-1]["manager"] == "ao-mgr" and sent[-1]["id"] == "ao-w"
    # at a node: the param alone says which record is the manager
    monkeypatch.setattr(agent, "mode", "node")
    assert agent._is_team_manager(w, "ao-w@node") and not agent._is_team_manager(w, "ao-mgr")
    assert not agent._is_team_manager(w, None)
