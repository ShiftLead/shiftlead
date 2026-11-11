"""The send's choice of record for a scaled seat (design §4.9 *Mail to a scaled seat*, §6 rule 3 *An extra seat*,
§4.10's two scaled-seat rows; td-max, TD-1547): mail to the seat goes to its first free live record in place order;
none free and the own record not live, to the own record, no extra; the own record live and busy and no live
record free, an `ask` fills the lowest-placed held extra at the send and lands there, the send not waiting for the
pane; a thread or a PR a live record holds stays with it; a note stays on the own record; an own record neither
busy nor free keeps the ask and fills nothing; a burst, or two racing sends, fill one extra."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import mail, models, seat_send
from sessionorc.client import LocalClient

AGENT = {"adapter": "agentshell", "argv": ["bash", "--norc", "--noprofile"]}
HOOK = "2026-11-11T08:00:00Z"


async def _mk(person, tmp_path, name, **kw):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    kw.setdefault("unattended", True)
    return (await person.call("create", name=name, dir=str(d), **AGENT, **kw))["id"]


def _set(rec: models.Session, state: str) -> models.Session:
    """A live record as a hook reported it: `working`, `idle`, `needs-you` or `limited`."""
    rec.set_state(state, confidence="hook")
    rec.hook_seen_at = HOOK
    return rec


async def _seat(agent, person, tmp_path, *, own_live: bool, live_extras: int = 0, extras: int = 2):
    """A techlead seat `tl` of team beta (`max: 1 + extras`): its own record (live or held) and its extras `tl-2`…
    in place order, the first `live_extras` of them live, the rest held."""
    seat = {"trigger": "asks"}
    on_call = {} if own_live else {"held": True}
    own = await _mk(person, tmp_path, "tl", team="beta", seat=seat, supervised=True, **on_call)
    made = []
    for k in range(2, extras + 2):
        held = {} if k - 2 < live_extras else {"held": True}
        made.append(
            await _mk(
                person, tmp_path, f"tl-{k}", team="beta", seat=seat, scale={"line": "tl"}, supervised=True, **held
            )
        )
    for sid in (own, *made):
        agent.sessions[sid].git = {"dirty": 0, "unpushed": 0}
    return own, made


async def _askers(person, tmp_path, n=3):
    return [await _mk(person, tmp_path, f"w{k}", team="alpha") for k in range(1, n + 1)]


def _rec(agent, sid):
    return agent.sessions[sid]


@pytest.fixture
def blocked_replay(agent, monkeypatch):
    """`_replay` held on an event: the send's fill is started and never finished until the test lets it go."""
    gate = asyncio.Event()
    calls: list[tuple[str, str, dict]] = []

    async def replay(s, why, **kw):
        calls.append((s.id, why, kw))
        await gate.wait()

    monkeypatch.setattr(agent, "_replay", replay)
    return gate, calls


# -- the host agent's send -------------------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_seat_on_call_with_a_live_idle_extra_sends_the_ask_to_the_extra(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        own, (tl2, tl3) = await _seat(agent, person, tmp_path, own_live=False, live_extras=1)
        _set(_rec(agent, tl2), "idle")
        (w1, *_) = await _askers(person, tmp_path, 1)
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="read #12?", kind="ask")
        assert got["delivered"] == [tl2] and got["seated"] == {own: tl2}
        assert [e.id for e in _rec(agent, tl2).inbox] == [got["entry"]["id"]]
        assert not _rec(agent, own).inbox and not agent._send_filling
        assert got["read_when"][own].startswith("lands on tl-2, an extra of this seat, then lands; nothing is typed")


@pytest.mark.integration
async def test_a_seat_on_call_with_no_live_extra_takes_it_on_its_own_record_and_fills_no_extra(
    agent, tmp_path, blocked_replay
):
    await park_ticks(agent)
    _, calls = blocked_replay
    async with LocalClient() as person:
        own, (tl2, tl3) = await _seat(agent, person, tmp_path, own_live=False)
        (w1, *_) = await _askers(person, tmp_path, 1)
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="read #12?", kind="ask")
        assert got["delivered"] == [own] and got["seated"] == {}
        assert len(_rec(agent, own).inbox) == 1 and not _rec(agent, tl2).inbox
        assert not agent._send_filling and calls == []
        assert got["read_when"][own].startswith("fills this seat: a session starts on the next tick")


@pytest.mark.integration
async def test_a_working_seat_receiving_a_second_ask_fills_its_extra_at_the_send_and_delivers_there(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        own, (tl2, tl3) = await _seat(agent, person, tmp_path, own_live=True)
        w1, w2, _ = await _askers(person, tmp_path)
        async with LocalClient(caller=w1) as a:
            first = await a.call("msg", to=own, text="read #11?", kind="ask")
        assert first["delivered"] == [own], "the own record is free: the first ask is its own"
        _set(_rec(agent, own), "working")  # its turn on the first ask
        async with LocalClient(caller=w2) as b:
            got = await b.call("msg", to=own, text="read #12?", kind="ask")
        assert got["delivered"] == [tl2] and got["seated"] == {own: tl2}
        assert got["read_when"][own].startswith("fills tl-2, an extra of this seat, and lands there: it reads it first")
        await (agent._send_filling.get(tl2) or asyncio.sleep(0))
        new = _rec(agent, tl2)
        assert new.state not in ("exited", "closed"), "the extra is live"
        assert [e.id for e in new.inbox] == [got["entry"]["id"]], "the mail moved with the fill"
        assert new.restarts[-1]["why"] == "fill" and new.restarts[-1]["for"] == "send"
        assert new.scale["line"] == "tl" and new.scale["last"]["did"] == "fill"
        assert _rec(agent, tl3).state == "closed", "one extra, the lowest-placed"
        assert not agent._send_filling


@pytest.mark.integration
async def test_the_send_does_not_wait_for_the_fill(agent, tmp_path, blocked_replay):
    await park_ticks(agent)
    gate, calls = blocked_replay
    async with LocalClient() as person:
        own, (tl2, _) = await _seat(agent, person, tmp_path, own_live=True)
        _set(_rec(agent, own), "working")
        (w1, *_) = await _askers(person, tmp_path, 1)
        async with LocalClient(caller=w1) as a:
            got = await asyncio.wait_for(a.call("msg", to=own, text="read #12?", kind="ask"), 5)
        assert got["delivered"] == [tl2] and calls == [(tl2, "fill", {"keep_mail": True, "mark": {"for": "send"}})]
        assert not agent._send_filling[tl2].done(), "the replay is still held: the send came back before it"
        assert len(_rec(agent, tl2).inbox) == 1, "landed on the held extra's mailbox, for the fill to carry"
        gate.set()
        await agent._send_filling[tl2]


@pytest.mark.integration
async def test_a_follow_up_on_the_first_asks_thread_stays_with_the_record_that_answered(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        own, (tl2, _) = await _seat(agent, person, tmp_path, own_live=True, live_extras=1)
        _set(_rec(agent, own), "working")
        _set(_rec(agent, tl2), "idle")
        w1, w2 = await _askers(person, tmp_path, 2)
        async with LocalClient(caller=w1) as a, LocalClient(caller=tl2) as t, LocalClient(caller=w2) as b:
            first = await a.call("msg", to=own, text="read #12?", kind="ask")
            assert first["delivered"] == [tl2]
            answer = (await t.call("msg", text="pass", kind="reply", reply_to=first["entry"]["id"]))["entry"]
            _set(_rec(agent, own), "idle")  # the own record is free now: a new ask would go there
            _set(_rec(agent, tl2), "working")
            again = await a.call("msg", to=own, text="and the follow-up?", kind="ask", reply_to=answer["id"])
            assert again["delivered"] == [tl2], "the thread holds its context on the record that answered"
            fresh = await b.call("msg", to=own, text="a new question", kind="ask")
        assert fresh["delivered"] == [own]


@pytest.mark.integration
async def test_an_ask_about_a_pr_a_live_record_already_holds_an_ask_about_stays_with_it(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        own, (tl2, _) = await _seat(agent, person, tmp_path, own_live=True, live_extras=1)
        _set(_rec(agent, own), "idle")
        _set(_rec(agent, tl2), "working")
        _rec(agent, tl2).inbox.append(
            models.MailEntry(id="m-old", from_="ao-x", to=[tl2], at=HOOK, kind="ask", text="read #12", pr=12)
        )
        w1 = await _mk(person, tmp_path, "w1", team="beta")  # a reader's `ask` carrying `pr` is a teammate's
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="#12 again, rebased", kind="ask", pr=12)
            other = await a.call("msg", to=own, text="fyi", kind="note")
        assert got["delivered"] == [tl2] and other["delivered"] == [own]


@pytest.mark.integration
async def test_three_asks_in_one_burst_while_the_seat_works_fill_one_extra_and_land_there(
    agent, tmp_path, blocked_replay
):
    await park_ticks(agent)
    gate, calls = blocked_replay
    async with LocalClient() as person:
        own, (tl2, tl3) = await _seat(agent, person, tmp_path, own_live=True)
        _set(_rec(agent, own), "working")
        ws = await _askers(person, tmp_path)
        clients = [LocalClient(caller=w) for w in ws]
        for c in clients:
            await c.__aenter__()
        try:
            sends = (c.call("msg", to=own, text=f"q{i}", kind="ask") for i, c in enumerate(clients))
            got = await asyncio.gather(*sends)
        finally:
            for c in clients:
                await c.__aexit__(None, None, None)
        assert [g["delivered"] for g in got] == [[tl2]] * 3
        assert [c[:2] for c in calls] == [(tl2, "fill")], "one fill for the burst"
        assert all(g["read_when"][own].startswith("fills tl-2") for g in got)
        assert len(_rec(agent, tl2).inbox) == 3 and _rec(agent, tl3).state == "closed"
        gate.set()
        await agent._send_filling[tl2]


@pytest.mark.integration
async def test_two_racing_sends_take_one_extra_and_the_next_once_it_has_reported(agent, tmp_path, blocked_replay):
    """Two sends at once take the lowest-placed held extra once — the second finds it filling, so free (§4.9: a
    record filled and not yet reported on counts as free) — and once that extra works, the next send takes the
    next held extra; no send fills an extra another send is filling."""
    await park_ticks(agent)
    gate, calls = blocked_replay
    async with LocalClient() as person:
        own, (tl2, tl3) = await _seat(agent, person, tmp_path, own_live=True)
        _set(_rec(agent, own), "working")
        w1, w2, w3 = await _askers(person, tmp_path)
        async with LocalClient(caller=w1) as a, LocalClient(caller=w2) as b, LocalClient(caller=w3) as c:
            one, two = await asyncio.gather(
                a.call("msg", to=own, text="q1", kind="ask"), b.call("msg", to=own, text="q2", kind="ask")
            )
            assert one["delivered"] == two["delivered"] == [tl2] and len(calls) == 1
            gate.set()
            await agent._send_filling[tl2]
            # the fill stands (as `_replay` would leave it) and its first hook reports it working
            _set(_rec(agent, tl2), "working")
            three = await c.call("msg", to=own, text="q3", kind="ask")
        assert three["delivered"] == [tl3] and [x[0] for x in calls] == [tl2, tl3]
        gate.set()
        await (agent._send_filling.get(tl3) or asyncio.sleep(0))


@pytest.mark.integration
async def test_a_note_and_a_reply_that_closes_nothing_stay_on_the_own_record(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        own, (tl2, _) = await _seat(agent, person, tmp_path, own_live=True, live_extras=1)
        _set(_rec(agent, own), "working")
        _set(_rec(agent, tl2), "idle")  # free: an ask would go there
        w1 = await _mk(person, tmp_path, "w1", team="beta")  # a note to a seat is a teammate's
        async with LocalClient(caller=w1) as a:
            note = await a.call("msg", to=own, text="fyi: main moved", kind="note")
        assert note["delivered"] == [own] and not _rec(agent, tl2).inbox and not agent._send_filling
        got = await person.call("msg", to=own, text="from the person", kind="note")
        assert got["delivered"] == [own]


@pytest.mark.integration
async def test_a_limited_own_record_keeps_its_ask_and_fills_no_extra(agent, tmp_path, blocked_replay):
    await park_ticks(agent)
    _, calls = blocked_replay
    async with LocalClient() as person:
        own, (tl2, _) = await _seat(agent, person, tmp_path, own_live=True)
        _set(_rec(agent, own), "limited")
        # a reset soon: not routed around (§4.9b), so the own record keeps it
        _rec(agent, own).limited_reset = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
        (w1, w2, _) = await _askers(person, tmp_path)
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="read #12?", kind="ask")
        assert got["delivered"] == [own] and calls == [] and _rec(agent, tl2).state == "closed"
        assert got["read_when"][own].startswith("lands and waits: its account is capped")
        # a free live extra takes it from an own record neither busy nor free
        live = await _mk(person, tmp_path, "tl-4", team="beta", seat={"trigger": "asks"}, scale={"line": "tl"})
        _set(_rec(agent, live), "idle")
        async with LocalClient(caller=w2) as b:
            moved = await b.call("msg", to=own, text="read #13?", kind="ask")
        assert moved["delivered"] == [live] and calls == []


@pytest.mark.integration
async def test_a_working_seat_whose_fill_is_refused_keeps_the_ask_and_says_why(agent, tmp_path, blocked_replay):
    await park_ticks(agent)
    _, calls = blocked_replay
    async with LocalClient() as person:
        own, _ = await _seat(agent, person, tmp_path, own_live=True)
        _set(_rec(agent, own), "working")
        (w1, *_) = await _askers(person, tmp_path, 1)
        agent._profile_gated = lambda profile, now, team="": True
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="read #12?", kind="ask")
        assert got["delivered"] == [own] and calls == []
        assert got["read_when"][own].startswith(
            "waits on tl: its profile is paused — it moves to an extra once one fills"
        )


# -- the pure choice and the sentence ---------------------------------------------------------------------------


def _r(sid: str, name: str, state: str, **kw) -> models.Session:
    s = models.Session(id=sid, name=name, kind="claude", adapter="claude-code", dir=f"/{name}", team="beta")
    s.seat = {"trigger": "asks"}
    s.state, s.confidence, s.hook_seen_at = state, "hook", HOOK
    for k, v in kw.items():
        setattr(s, k, v)
    return s


NOW = datetime(2026, 11, 11, 9, tzinfo=UTC)


@pytest.mark.unit
def test_choose_reads_free_busy_and_the_guard_in_place_order():
    own = _r("ao-tl", "tl", "working")
    e3 = _r("ao-tl-3", "tl-3", "closed", scale={"line": "tl"})
    e2 = _r("ao-tl-2", "tl-2", "closed", scale={"line": "tl"})
    extras = seat_send.extras_in_place(own, [own, e3, e2, _r("ao-fc-2", "fc-2", "idle", scale={"line": "fc"})])
    assert [r.id for r in extras] == ["ao-tl-2", "ao-tl-3"]
    held = [e2, e3]
    got = seat_send.choose(own, extras, kind="ask", now=NOW, held=held)
    assert got.to == "ao-tl-2" and got.fill is e2 and got.words == {"fill": "tl-2"}
    full = seat_send.choose(own, extras, kind="ask", now=NOW, held=held, guard=lambda r: "host full, 4 live")
    assert full.to == "ao-tl" and full.fill is None and full.words == {"waits": "host full, 4 live"}
    assert seat_send.choose(own, extras, kind="ask", now=NOW).words == {"waits": "every extra busy"}
    # the filling extra takes the next ask; one being evicted is never chosen
    burst = seat_send.choose(own, extras, kind="ask", now=NOW, held=held, filling={"ao-tl-2"})
    assert burst.to == "ao-tl-2" and burst.fill is None
    e2.state = "idle"
    assert seat_send.choose(own, extras, kind="ask", now=NOW, held=[e3]).to == "ao-tl-2"
    evicted = seat_send.choose(own, extras, kind="ask", now=NOW, held=[e3], evicting={"ao-tl-2"})
    assert evicted.to == "ao-tl-3" and evicted.fill is e3
    # a steer takes a free record but fills nothing; a `stalled?` own record keeps it
    e2.state = "working"
    assert seat_send.choose(own, extras, kind="steer", now=NOW, held=[e3]).to == "ao-tl"
    own.state = "stalled?"
    assert seat_send.choose(own, extras, kind="ask", now=NOW, held=[e3]) == seat_send.Choice("ao-tl")


@pytest.mark.unit
def test_free_counts_a_record_no_hook_has_reported_and_not_one_wrapping_up():
    r = _r("ao-tl-2", "tl-2", "working")
    assert seat_send.busy(r, NOW) and not seat_send.free(r, NOW)
    r.hook_seen_at, r.confidence = None, "scraped"
    assert seat_send.free(r, NOW) and not seat_send.busy(r, NOW), "filled, not yet reported on: free"
    r.state, r.hook_seen_at, r.confidence = "idle", HOOK, "hook"
    assert seat_send.free(r, NOW)
    r.wrapup_at = HOOK
    assert not seat_send.free(r, NOW) and not seat_send.busy(r, NOW)


@pytest.mark.unit
def test_read_when_says_the_scaled_seat_rows_for_an_ask_alone():
    own = _r("ao-tl", "tl", "working")
    extra = _r("ao-tl-2", "tl-2", "idle")
    fill = mail.read_when(own, "ask", NOW, extras={"fill": "tl-2"})
    assert fill.startswith("fills tl-2, an extra of this seat, and lands there: it reads it first")
    waits = mail.read_when(own, "ask", NOW, extras={"waits": "every extra busy"})
    assert waits.startswith("waits on tl: every extra busy — it moves to an extra once one fills")
    lands = mail.read_when(extra, "ask", NOW, extras={"lands": True})
    assert lands.startswith('lands on tl-2, an extra of this seat, then rung within a tick: the doorbell types "you')
    assert mail.read_when(own, "note", NOW, extras={"fill": "tl-2"}) == mail.read_when(own, "note", NOW)


@pytest.mark.integration
async def test_a_failed_fill_puts_the_ask_back_on_the_own_record(agent, tmp_path, monkeypatch):
    """A send's fill that does not start leaves nothing on the held extra: its unread mail is back on the seat's own
    record, addressed there, where it waits as it would have with no extra to fill (§4.9 *nothing is stranded*)."""
    await park_ticks(agent)

    async def replay(s, why, **kw):  # the create refused: the record stays as it was
        return None

    monkeypatch.setattr(agent, "_replay", replay)
    async with LocalClient() as person:
        own, (tl2, _) = await _seat(agent, person, tmp_path, own_live=True)
        _set(_rec(agent, own), "working")
        (w1, *_) = await _askers(person, tmp_path, 1)
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="read #12?", kind="ask")
        assert got["delivered"] == [tl2]
        await (agent._send_filling.get(tl2) or asyncio.sleep(0))
        mid = got["entry"]["id"]
        assert not _rec(agent, tl2).inbox, "nothing left on a record nothing reads"
        assert [e.id for e in _rec(agent, own).inbox] == [mid]
        assert _rec(agent, own).inbox[0].to == [own]
        assert [e.to for e in _rec(agent, w1).outbox if e.id == mid] == [[own]]
        assert not agent._send_filling


@pytest.mark.integration
async def test_a_send_never_lands_on_the_extra_the_eviction_is_closing(agent, tmp_path, blocked_replay):
    await park_ticks(agent)
    gate, _ = blocked_replay
    async with LocalClient() as person:
        own, (tl2, tl3) = await _seat(agent, person, tmp_path, own_live=True, live_extras=1)
        _set(_rec(agent, own), "working")
        _set(_rec(agent, tl2), "idle")  # free, but the host cap's eviction is closing it
        agent._evicting.add(tl2)
        (w1, *_) = await _askers(person, tmp_path, 1)
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="read #12?", kind="ask")
        assert got["delivered"] == [tl3] and not _rec(agent, tl2).inbox
        gate.set()
        await agent._send_filling[tl3]


@pytest.mark.unit
def test_a_reply_that_closes_nothing_goes_to_the_own_record_on_a_thread_an_extra_answered():
    own = _r("ao-tl", "tl", "working")
    e2 = _r("ao-tl-2", "tl-2", "idle", scale={"line": "tl"})
    e2.outbox = [
        models.MailEntry(id="m-1", from_="ao-tl-2", to=["ao-w1"], at=HOOK, kind="reply", text="pass", root="m-0")
    ]
    got = seat_send.choose(own, [e2], kind="reply", now=NOW, root="m-0", closes_seat_question=False)
    assert got == seat_send.Choice("ao-tl")
    closing = seat_send.choose(own, [e2], kind="reply", now=NOW, root="m-0", closes_seat_question=True)
    assert closing.to == "ao-tl-2", "a reply closing the extra's own question goes to it"


# -- the tick's mover (§4.9 *Mail to a scaled seat*: rule 3's pass reads the state each tick) ----------------------


def _land(agent, on: str, frm: str, mid: str, text: str = "read it?") -> models.MailEntry:
    """An unread ask already on a record of the seat, however it got there."""
    e = models.MailEntry(id=mid, from_=frm, to=[on], at=HOOK, kind="ask", text=text, root=mid)
    agent.sessions[on].inbox.append(e)
    agent.sessions[frm].outbox.append(models.MailEntry.from_dict(e.to_dict()))
    return e


@pytest.mark.integration
async def test_an_ask_waiting_on_a_busy_seat_moves_to_an_extra_the_tick_fills_once_one_can_be(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        own, (tl2, tl3) = await _seat(agent, person, tmp_path, own_live=True)
        _set(_rec(agent, own), "working")
        (w1, *_) = await _askers(person, tmp_path, 1)
        gated = {"on": True}
        agent._profile_gated = lambda profile, now, team="": gated["on"]
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="read #12?", kind="ask")
        assert got["delivered"] == [own]
        await agent._seat_move(datetime.now(UTC))
        assert not agent._send_filling and [e.id for e in _rec(agent, own).inbox] == [got["entry"]["id"]], (
            "still paused"
        )
        gated["on"] = False
        await agent._seat_move(datetime.now(UTC))
        await (agent._send_filling.get(tl2) or asyncio.sleep(0))
        new = _rec(agent, tl2)
        assert new.state not in ("exited", "closed") and [e.id for e in new.inbox] == [got["entry"]["id"]]
        assert not [e for e in _rec(agent, own).inbox if e.id == got["entry"]["id"]], "moved, not copied"
        sent = [e for e in _rec(agent, w1).outbox if e.id == got["entry"]["id"]]
        assert sent and sent[0].to == [tl2], "the sender's copy says where it went"
        assert _rec(agent, tl3).state == "closed", "one extra, the lowest-placed"


@pytest.mark.integration
async def test_mail_left_on_a_held_extra_moves_to_the_first_free_live_record(agent, tmp_path, blocked_replay):
    await park_ticks(agent)
    _, calls = blocked_replay
    async with LocalClient() as person:
        own, (tl2, tl3) = await _seat(agent, person, tmp_path, own_live=True, live_extras=1)
        _set(_rec(agent, own), "working")
        _set(_rec(agent, tl2), "idle")
        (w1, *_) = await _askers(person, tmp_path, 1)
        _land(agent, tl3, w1, "m-left")
        await agent._seat_move(datetime.now(UTC))
        assert [e.id for e in _rec(agent, tl2).inbox] == ["m-left"] and not _rec(agent, tl3).inbox
        assert calls == [], "a free live record takes it: nothing filled"


@pytest.mark.integration
async def test_mail_left_on_a_held_extra_of_a_seat_on_call_lands_on_its_own_record(agent, tmp_path, blocked_replay):
    await park_ticks(agent)
    _, calls = blocked_replay
    async with LocalClient() as person:
        own, (_tl2, tl3) = await _seat(agent, person, tmp_path, own_live=False)
        (w1, *_) = await _askers(person, tmp_path, 1)
        _land(agent, tl3, w1, "m-left")
        await agent._seat_move(datetime.now(UTC))
        assert [e.id for e in _rec(agent, own).inbox] == ["m-left"] and not _rec(agent, tl3).inbox
        assert calls == [], "the own record is filled on its cause, no extra by the mover"


@pytest.mark.integration
async def test_an_ask_on_a_free_own_record_or_a_thread_a_live_record_holds_stays(agent, tmp_path, blocked_replay):
    await park_ticks(agent)
    _, calls = blocked_replay
    async with LocalClient() as person:
        own, (tl2, _tl3) = await _seat(agent, person, tmp_path, own_live=True, live_extras=1)
        _set(_rec(agent, own), "idle")
        _set(_rec(agent, tl2), "idle")
        (w1, *_) = await _askers(person, tmp_path, 1)
        _land(agent, own, w1, "m-own")
        await agent._seat_move(datetime.now(UTC))
        assert [e.id for e in _rec(agent, own).inbox] == ["m-own"], "free: it reads its own"
        _set(_rec(agent, own), "working")
        e = _land(agent, own, w1, "m-thread")
        e.root = "m-t"
        _rec(agent, own).outbox.append(models.MailEntry(id="m-t", from_=own, to=[w1], at=HOOK, kind="ask", text="q"))
        _rec(agent, own).inbox = [x for x in _rec(agent, own).inbox if x.id == "m-thread"]
        await agent._seat_move(datetime.now(UTC))
        assert [x.id for x in _rec(agent, own).inbox] == ["m-thread"], "its thread: it holds the context"
        assert calls == []


@pytest.mark.integration
async def test_the_mover_fills_for_a_pr_ask_once_and_not_again_after_a_failed_fill(agent, tmp_path, monkeypatch):
    """A reader's `pr` ask on the busy own record is not its own reason to stay; a fill that fails puts it back,
    and the mover does not fill that extra again within `MOVE_FILL_BACKOFF`. An `entry` envelope is never moved."""
    await park_ticks(agent)
    calls: list[str] = []

    async def failing(s, why, **kw):
        calls.append(s.id)
        raise RuntimeError("no launch record")

    monkeypatch.setattr(agent, "_replay", failing)
    async with LocalClient() as person:
        own, (tl2, _tl3) = await _seat(agent, person, tmp_path, own_live=True)
        _set(_rec(agent, own), "working")
        (w1, *_) = await _askers(person, tmp_path, 1)
        env = _land(agent, own, w1, "m-env")
        env.entry = {"title": "x"}
        await agent._seat_move(datetime.now(UTC))
        assert calls == [] and not agent._send_filling, "an entry envelope is never moved or filled for"
        e = _land(agent, own, w1, "m-pr")
        e.pr = 12
        await agent._seat_move(datetime.now(UTC))
        await (agent._send_filling.get(tl2) or asyncio.sleep(0))
        assert calls == [tl2], "the pr ask filled the lowest-placed held extra"
        assert {x.id for x in _rec(agent, own).inbox} == {"m-pr", "m-env"}, "the failed fill put it back"
        await agent._seat_move(datetime.now(UTC))
        await asyncio.sleep(0)
        assert calls == [tl2], "not filled again at once"
        assert "m-env" in {x.id for x in _rec(agent, own).inbox}, "an entry envelope stays"


# -- routing around an unable seat reads its extras first (§4.9b *A seat that cannot answer is routed around*) -------


@pytest.mark.unit
def test_routes_to_extras_reads_stalled_exited_and_closed_never_limited_or_gated():
    stalled = _r("ao-tl", "tl", "stalled?")
    assert seat_send.routes_to_extras(stalled, "stalled?")
    assert not seat_send.routes_to_extras(stalled, None), "able: nothing is routed"
    assert seat_send.routes_to_extras(_r("ao-tl", "tl", "closed"), "fill ceiling")
    assert seat_send.routes_to_extras(_r("ao-tl", "tl", "exited"), "restart ceiling")
    for kept in ("suspended", "sat out", "not supervised"):
        assert not seat_send.routes_to_extras(_r("ao-tl", "tl", "closed"), kept), f"{kept}: no extra runs it either"
    assert not seat_send.routes_to_extras(_r("ao-tl", "tl", "exited"), "profile gated"), "its extras share the profile"
    assert not seat_send.routes_to_extras(_r("ao-tl", "tl", "limited"), "limited")
    paused = _r("ao-tl", "tl", "closed", gated={"next": None})
    assert not seat_send.routes_to_extras(paused, "paused by the usage gate")


@pytest.mark.unit
def test_an_unable_own_record_passes_an_ask_to_a_free_extra_else_fills_a_held_one():
    own = _r("ao-tl", "tl", "stalled?")
    e2 = _r("ao-tl-2", "tl-2", "closed", scale={"line": "tl"})
    e3 = _r("ao-tl-3", "tl-3", "closed", scale={"line": "tl"})
    got = seat_send.choose(own, [e2, e3], kind="ask", now=NOW, held=[e2, e3], unable=True)
    assert got.to == "ao-tl-2" and got.fill is e2, "a stalled own record, not busy: the held extra is filled"
    own.state = "closed"
    assert seat_send.choose(own, [e2, e3], kind="ask", now=NOW, held=[e2, e3], unable=True).fill is e2
    assert seat_send.choose(own, [e2, e3], kind="ask", now=NOW, held=[e2, e3]) == seat_send.Choice("ao-tl"), (
        "able, on call: filled on its cause as before"
    )
    e3.state = "idle"
    assert seat_send.choose(own, [e2, e3], kind="ask", now=NOW, held=[e2], unable=True).to == "ao-tl-3"
    e3.state = "closed"
    refused = seat_send.choose(own, [e2, e3], kind="ask", now=NOW, held=[e2], unable=True, guard=lambda r: "host full")
    assert refused == seat_send.Choice("ao-tl", words={"waits": "host full"}), "the road around takes over"
    # a thread or a PR ask the unable own record holds keeps nothing there
    own.state = "stalled?"
    own.outbox = [models.MailEntry(id="m-1", from_="ao-tl", to=["w"], at=HOOK, kind="reply", text="x", root="m-0")]
    own.inbox = [models.MailEntry(id="m-2", from_="w", to=["ao-tl"], at=HOOK, kind="ask", text="x", pr=7)]
    assert seat_send.choose(own, [e2], kind="ask", now=NOW, root="m-0", held=[e2], unable=True).fill is e2
    assert seat_send.choose(own, [e2], kind="ask", now=NOW, pr=7, held=[e2], unable=True).fill is e2
    assert seat_send.choose(own, [e2], kind="note", now=NOW, held=[e2], unable=True).to == "ao-tl", "a note stays"


@pytest.mark.integration
async def test_an_ask_to_a_seat_unable_as_closed_fills_its_extra_and_is_not_routed(agent, tmp_path, blocked_replay):
    await park_ticks(agent)
    _, calls = blocked_replay
    async with LocalClient() as person:
        own, (tl2, tl3) = await _seat(agent, person, tmp_path, own_live=False)
        agent.unfillable = {own: "fill ceiling"}  # rule 3 would not fill it: unable (§4.9b)
        (w1, *_) = await _askers(person, tmp_path, 1)
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="read #12?", kind="ask")
        assert "routed" not in got and got["delivered"] == [tl2] and got["seated"] == {own: tl2}
        assert [c[0] for c in calls] == [tl2] and _rec(agent, tl3).state == "closed"
        view = next(x for x in agent._views() if x["id"] == own)
        assert view["seat_unable"] == "fill ceiling" and view["seat_routed_to"] == "tl-2", "its extras first"
        mate = await _mk(person, tmp_path, "w9", team="beta")  # a reader's `ask` carrying `pr` is a teammate's
        async with LocalClient(caller=mate) as b:
            pr = await b.call("msg", to=own, text="read #13?", kind="ask", pr=13)
        assert "routed" not in pr and pr["delivered"] == [tl2], "a reader's ask may go to an extra, the same reader"


@pytest.mark.integration
async def test_a_limited_seat_passes_its_extras_over_and_is_routed_as_before(agent, tmp_path, blocked_replay):
    await park_ticks(agent)
    _, calls = blocked_replay
    async with LocalClient() as person:
        own, (tl2, _) = await _seat(agent, person, tmp_path, own_live=True)
        _set(_rec(agent, own), "limited")  # no reset known: unable, but the extras share its profile
        (w1, *_) = await _askers(person, tmp_path, 1)
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="read #12?", kind="ask")
        assert got["routed"]["seat"] == own and got["entry"]["to"] == [mail.PERSON]
        assert calls == [] and _rec(agent, tl2).state == "closed"


@pytest.mark.integration
async def test_the_mover_takes_an_ask_off_a_stalled_own_record_to_an_extra(agent, tmp_path, blocked_replay):
    await park_ticks(agent)
    _, calls = blocked_replay
    async with LocalClient() as person:
        own, (tl2, _) = await _seat(agent, person, tmp_path, own_live=True)
        (w1, *_) = await _askers(person, tmp_path, 1)
        e = _land(agent, own, w1, "m-stuck", "read #9?")
        r = _rec(agent, own)
        _set(r, "working")
        r.set_state("stalled?", confidence="scraped")
        r.stalled_ticks = 1
        await agent._seat_move(datetime.now(UTC))
        assert [x.id for x in r.inbox] == ["m-stuck"] and calls == [], "one tick of stall: it keeps the ask"
        r.stalled_ticks = 2
        await agent._seat_move(datetime.now(UTC))
        assert not r.inbox and [x.id for x in _rec(agent, tl2).inbox] == [e.id] and tl2 in agent._send_filling


@pytest.mark.integration
async def test_a_suspended_seat_fills_no_extra_and_is_routed_as_before(agent, tmp_path, blocked_replay):
    await park_ticks(agent)
    _, calls = blocked_replay
    async with LocalClient() as person:
        own, (tl2, _) = await _seat(agent, person, tmp_path, own_live=False)
        agent.unfillable = {own: "suspended"}  # only a person lifts it: no extra runs in its place
        (w1, *_) = await _askers(person, tmp_path, 1)
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="read #12?", kind="ask")
        assert got["routed"]["why"] == "suspended" and got["entry"]["to"] == [mail.PERSON]
        assert calls == [] and _rec(agent, tl2).state == "closed"


@pytest.mark.integration
async def test_an_extra_whose_counts_refuse_the_ask_leaves_it_to_the_road_around(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    async with LocalClient() as person:
        own, (tl2, _) = await _seat(agent, person, tmp_path, own_live=False, live_extras=1)
        _set(_rec(agent, tl2), "idle")
        agent.unfillable = {own: "fill ceiling"}
        real = agent._landing_refusal
        monkeypatch.setattr(
            agent,
            "_landing_refusal",
            lambda rec, frm, to, e: "its mailbox is full" if to == tl2 else real(rec, frm, to, e),
        )
        (w1, *_) = await _askers(person, tmp_path, 1)
        async with LocalClient(caller=w1) as a:
            got = await a.call("msg", to=own, text="read #12?", kind="ask")
        assert got["routed"]["seat"] == own and got["entry"]["to"] == [mail.PERSON], "never refused: routed on"
        assert not _rec(agent, tl2).inbox
