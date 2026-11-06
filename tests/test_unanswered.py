"""Why a question taken up from a session was not answered (design §4.9b *Why it did not answer*, TD-1423,
built by TD-1430): the stamp the home reads off the addressee's record at the take-up, its fixed words, the
copies that carry it, `ao inbox` and `ao msg`'s lines, and `ao pr held` reading a closed unanswered ask as
the link's turn."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sessionorc import client as clientmod
from sessionorc import unanswered
from sessionorc.client import LocalClient
from sessionorc.models import MailEntry, Pending, Session
from shiftlead import review as reviewmod

Q = "2026-11-05T10:00:00Z"  # the taken question's time
AT = "2026-11-05T12:00:00Z"  # the read's


def _rec(**kw) -> Session:
    r = Session(id="ao-x-tl", name="tl", kind="interactive", adapter="claude-code", dir="/tmp/x", profile="max")
    r.created = "2026-11-05T09:00:00Z"
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def _read(r: Session | None, **kw) -> dict:
    return unanswered.read(r, "ao-x-tl", question_at=Q, at=AT, **kw)


def _words(stamp: dict) -> str:
    return unanswered.words(stamp, now=datetime(2026, 11, 5, 12, tzinfo=UTC))


def _t(iso: str) -> str:
    return unanswered.clock(iso, datetime(2026, 11, 5, 12, tzinfo=UTC))


# -- the states, one each, the first that holds (§4.9b) --------------------------------------------------


def test_gone_suspended_and_the_ceilings():
    got = _read(None)
    assert got == {"by": "ao-x-tl", "at": AT, "state": "gone"}
    assert _words(got) == "ao-x-tl is no longer a session; nobody holds this question."
    # a suspended seat keeps its fill mark: suspended is read first
    sus = _read(
        _rec(
            seat={"trigger": "asks"},
            suspended={"at": "2026-11-05T09:30:00Z"},
            restart_ceiling={"at": AT, "why": "fill"},
        )
    )
    assert sus["state"] == "suspended" and sus["since"] == "2026-11-05T09:30:00Z"
    assert _words(sus) == (
        f"tl is suspended since {_t('2026-11-05T09:30:00Z')} — "
        "your own resume of that conversation, or Forget, ends it."
    )
    plain = _read(_rec(seat={"trigger": "asks"}, restart_ceiling={"at": "2026-11-05T11:04:00Z", "why": "fill"}))
    assert plain["state"] == "fills_exhausted" and "held" not in plain
    assert _words(plain).endswith("— it fills again after the hour, or Restart on its fills-exhausted row now.")
    held = _read(
        _rec(seat={"trigger": "asks"}, restart_ceiling={"at": "2026-11-05T11:04:00Z", "why": "fill", "held": True})
    )
    assert held["held"] is True
    assert _words(held) == (
        f"tl was not filled: fills exhausted since {_t('2026-11-05T11:04:00Z')}, tripped twice running — "
        "Restart on its fills-exhausted row brings it back."
    )
    # a crash's ceiling on a non-seat: no `why`, the Restart words
    crash = _read(_rec(state="exited", restart_ceiling={"at": AT, "count": 3}))
    assert crash["state"] == "restart_ceiling" and "seat" not in crash
    assert (
        _words(crash) == f"tl stopped at the restart ceiling at {_t(AT)} — "
        "Restart on its restart row brings it back into its team's run."
    )
    # a seat's why-less ceiling (a lost brief's, a failed scheduled start's): the Resume words
    lost = _read(_rec(seat={"trigger": "asks"}, state="exited", restart_ceiling={"at": AT, "count": 1}))
    assert lost["state"] == "restart_ceiling" and lost["seat"] is True
    assert _words(lost) == f"tl stopped at the restart ceiling at {_t(AT)} — Resume on its restart row brings it back."


def test_a_ceiling_on_a_gated_profile_carries_the_gate():
    over = {"resets": "2026-11-05T15:00:00Z"}
    fill = _read(_rec(seat={"trigger": "asks"}, restart_ceiling={"at": AT, "why": "fill"}), over=over)
    assert fill["gate"] == {"profile": "max", "resets": "2026-11-05T15:00:00Z"}
    assert _words(fill).endswith(
        f"— its profile max is paused until {_t('2026-11-05T15:00:00Z')}, and the fill waits for it."
    )
    # a gate reading with no `resets`
    crash = _read(_rec(state="exited", restart_ceiling={"at": AT, "count": 3}), over={})
    assert crash["gate"] == {"profile": "max"}
    assert _words(crash).endswith(
        "— its profile max is paused until its usage reading resets, and Restart refuses until then."
    )
    # a seat's non-fill ceiling carries the gate and no words of its own
    lost = _read(_rec(seat={"trigger": "asks"}, state="exited", restart_ceiling={"at": AT, "count": 1}), over=over)
    assert lost["gate"]["profile"] == "max" and "paused" not in _words(lost)


def test_unreachable_scheduled_gated_and_limited():
    # a node's limited record on a down link: unreachable, read before its stale state
    got = _read(_rec(state="limited", host="node1"), unreachable=True)
    assert got["state"] == "unreachable"
    assert _words(got) == "tl's host is not answering; the question is delivered when it is back."
    sched = _read(_rec(seat={"trigger": "asks"}, state="scheduled", start_at="2026-11-05T20:00:00Z"))
    assert sched == {**sched, "state": "scheduled", "start_at": "2026-11-05T20:00:00Z"}
    assert _words(sched) == f"tl starts at {_t('2026-11-05T20:00:00Z')}."
    gated = _read(_rec(state="idle"), over={"resets": "2026-11-05T15:00:00Z"})
    assert gated["state"] == "gated" and gated["resets"] == "2026-11-05T15:00:00Z"
    assert _words(gated) == f"tl's profile max is paused by the usage gate until {_t('2026-11-05T15:00:00Z')}."
    # a closed non-seat on an over-line profile has nothing waiting: it reads ended
    closed = _read(_rec(state="closed", closed_at="2026-11-05T11:00:00Z"), over={})
    assert closed["state"] == "ended"
    limited = _read(_rec(state="limited", pending=Pending(kind="limit", text="resets 3pm")))
    assert limited["cap"] == "resets 3pm" and "modal" not in limited
    assert _words(limited) == "tl is at its usage cap: resets 3pm — it is rung after."
    modal = _read(_rec(state="limited", pending=Pending(kind="limit", text="")), modal=True)
    assert "cap" not in modal and _words(modal) == "tl is at its usage cap — answered on its pane."


def test_not_filled_ended_and_lapsed():
    nf = _read(_rec(seat={"trigger": "asks"}, state="exited", ended={"at": "2026-11-05T09:50:00Z"}))
    assert nf["state"] == "not_filled" and _words(nf) == "tl was never filled for this question."
    # a fill live at the ask and ended after it
    held = _read(_rec(seat={"trigger": "asks"}, state="exited", ended={"at": "2026-11-05T11:00:00Z"}))
    assert held["state"] == "ended" and held["since"] == Q and held["ended"] == "2026-11-05T11:00:00Z"
    assert (
        _words(held)
        == f"tl held the question from {_t(Q)} and ended at {_t('2026-11-05T11:00:00Z')} without answering."
    )
    # a closed record with no `ended`, by its `closed_at`, created after the question
    later = _read(_rec(state="closed", created="2026-11-05T10:30:00Z", closed_at="2026-11-05T11:30:00Z"))
    assert later["since"] == "2026-11-05T10:30:00Z" and later["ended"] == "2026-11-05T11:30:00Z"
    # a non-seat ended before the ask
    before = _read(_rec(state="exited", ended={"at": "2026-11-05T09:30:00Z"}))
    assert before["state"] == "ended" and "since" not in before
    assert _words(before) == f"tl ended at {_t('2026-11-05T09:30:00Z')}, before the question was sent."
    # a seat refilled after a lapse of its fill ceiling
    lapsed = _read(_rec(seat={"trigger": "asks"}, state="idle", fill_lapsed={"at": "2026-11-05T11:00:00Z"}))
    assert lapsed["lapsed"] == "2026-11-05T11:00:00Z"
    assert _words(lapsed).endswith(f"— it was at its fill ceiling until {_t('2026-11-05T11:00:00Z')}.")
    # a lapse before the question is no part of the wait
    assert "lapsed" not in _read(_rec(state="idle", fill_lapsed={"at": "2026-11-05T09:00:00Z"}))


def test_needs_you_working_and_idle():
    perm = _read(_rec(state="needs-you", pending=Pending(kind="permission", text="Bash")))
    assert perm["kind"] == "permission"
    assert _words(perm) == "tl is waiting on a permission in its pane — its row under Needs you answers it."
    prompt = _read(_rec(state="needs-you", pending=Pending(kind="prompt", text="?")))
    assert _words(prompt) == "tl is waiting on you in its pane — its row under Needs you answers it."
    q = _read(_rec(state="needs-you", pending=Pending(kind="question", text="?")))
    assert "on its own question" in _words(q)
    stalled = _read(_rec(state="stalled?"), waiting=2, tail="rung when its turn ends")
    assert stalled["state"] == "working" and stalled["waiting"] == 2
    assert _words(stalled) == "tl is working and has not answered, 2 questions waiting — rung when its turn ends."
    idle = _read(_rec(state="idle"), waiting=1)
    assert _words(idle) == "tl is idle and has not answered, 1 question waiting."


# -- the send: every copy carries it, written only at the take-up ----------------------------------------


def _mk(person, tmp_path):
    async def mk(n: str, **kw):
        d = tmp_path / n
        d.mkdir(exist_ok=True)
        got = await person.call("create", name=n, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw)
        return got["id"]

    return mk


@pytest.mark.integration
async def test_a_take_up_stamps_every_copy_and_the_reply_prints_it(agent, tmp_path):
    """The person inbox's copy, the sender's outbox copy and the reply carry the stamp; the techlead's
    reply is unchanged; a seat holding only the taken question reads `waiting` 0."""
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        w, tl = [await mk(n, team="ao-grind", unattended=True) for n in ("w", "tl")]
        agent.sessions[tl].seat = {"trigger": "asks"}
        async with LocalClient(caller=w) as wc:
            q = (await wc.call("msg", to=tl, text="rebase or merge?", kind="ask"))["entry"]
            agent.sessions[tl].state = "idle"
            up = await wc.call(
                "msg", to="person", text="rebase or merge? tl did not answer", kind="ask", thread=q["id"]
            )
        stamp = up["entry"]["unanswered"]
        assert stamp["state"] == "idle" and stamp["by"] == tl and stamp["waiting"] == 0 and stamp["name"] == "tl"
        assert up["forwarded"] == {}
        mine = [e for e in agent.person_inbox if e.id == up["entry"]["id"]]
        out = [e for e in agent.sessions[w].outbox if e.id == up["entry"]["id"]]
        assert mine[0].unanswered == stamp and out[0].unanswered == stamp
        assert mine[0].unanswered is not out[0].unanswered  # each copy its own dict
        # the question it took up carries none, and a later `--thread` on the person's question writes none
        assert all(e.unanswered is None for e in agent.sessions[tl].inbox)


@pytest.mark.integration
async def test_a_refilled_seat_is_read_at_its_newest_record_and_counts_none_of_the_taken(agent, tmp_path, monkeypatch):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        w, tl, tl2 = [await mk(n, team="ao-grind", unattended=True) for n in ("w", "tl", "tl2")]
        async with LocalClient(caller=w) as wc:
            q = (await wc.call("msg", to=tl, text="squash?", kind="ask"))["entry"]
            old = agent.sessions[tl]
            old.state, old.superseded_by = "closed", tl2
            agent.sessions[tl2].state, agent.sessions[tl2].profile = "working", "max"
            monkeypatch.setattr(agent, "_profile_over", lambda p, now, team="": {"resets": "2026-11-05T15:00:00Z"})
            gated = await wc.call("msg", to="person", text="squash? tl did not answer", kind="ask", thread=q["id"])
            assert gated["entry"]["unanswered"]["state"] == "gated" and gated["entry"]["unanswered"]["by"] == tl2
            assert gated["forwarded"] == {}  # the walk writes no forward onto the reply
            monkeypatch.setattr(agent, "_profile_over", lambda p, now, team="": None)
            q2 = (await wc.call("msg", to=tl, text="tag?", kind="ask"))["entry"]
            got = (await wc.call("msg", to="person", text="tag? tl did not answer", kind="ask", thread=q2["id"]))[
                "entry"
            ]
        assert got["unanswered"]["state"] == "working" and got["unanswered"]["waiting"] == 0
        assert got["unanswered"]["tail"]  # the read_when sentence, with no bound's clause
        assert "default bound" not in got["unanswered"]["tail"]


@pytest.mark.integration
async def test_a_forgotten_addressee_reads_gone_and_a_landed_copy_carries_it(agent, tmp_path):
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        lead, lead2, w, tl = [await mk(n, unattended=True) for n in ("lead", "lead2", "w", "tl")]
        await person.call("set_controllers", id=w, add=[lead, lead2])
        await person.call("set_controllers", id=tl, add=[lead])
        async with LocalClient(caller=lead) as lc:
            q = (await lc.call("msg", to=tl, text="ship it?", kind="ask"))["entry"]
            del agent.sessions[tl]  # forgotten
            up = await lc.call(
                "msg", to="person", text="ship it? tl did not answer", kind="ask", thread=q["id"], about=w
            )
        assert up["entry"]["unanswered"] == {"by": tl, "at": up["entry"]["unanswered"]["at"], "state": "gone"}
        assert up["copies"] == [lead2]
        landed = [e for e in agent.sessions[lead2].inbox if e.id == up["entry"]["id"]]
        assert landed and landed[0].unanswered == up["entry"]["unanswered"]


@pytest.mark.integration
async def test_no_caller_writes_the_stamp(agent, tmp_path):
    """The send RPC takes no `unanswered`: dispatch drops it and names it in the reply's `ignored`, and an
    ordinary send or a `--thread` on the person's own question stores none."""
    async with LocalClient() as person:
        mk = _mk(person, tmp_path)
        w = await mk("w", unattended=True)
        clientmod.last_ignored.clear()
        async with LocalClient(caller=w) as wc:
            got = await wc.call("msg", to="person", text="which?", kind="ask", unanswered={"state": "gone"})
        assert "unanswered" in clientmod.last_ignored
        stored = [e for e in agent.person_inbox if e.id == got["entry"]["id"]]
        assert stored[0].unanswered is None
        await person.call("msg", reply_to=got["entry"]["id"], kind="reply", text="a")
        async with LocalClient(caller=w) as wc:
            again = await wc.call("msg", to="person", text="and then?", kind="ask", thread=got["entry"]["id"])
        assert again["entry"]["unanswered"] is None


def test_the_entry_round_trips_and_the_cli_line():
    e = MailEntry(id="m-1", from_="w", to=["person"], at=AT, kind="ask", text="?")
    e.unanswered = {"by": "ao-x-tl", "at": AT, "state": "gone"}
    assert MailEntry.from_dict(e.to_dict()).unanswered == e.unanswered
    from shiftlead import cli

    line = cli._unanswered_line({"by": "ao-x-tl", "name": "tl", "at": AT, "state": "not_filled"})
    assert line == f"not answered by tl (as read at {unanswered.clock(AT)}): tl was never filled for this question."


# -- `ao pr held`: a closed ask with no reply is the link's turn ------------------------------------------


def test_a_closed_unanswered_ask_reads_as_the_links_turn():
    links = [
        {"stage": "ui-review", "reader": "ui-reader-ao", "paths": ["a"]},
        {"stage": "review", "reader": "techlead-ao", "paths": ["b"]},
    ]

    def ask(to, *, open_=True, verdict=None, replied=None):
        return {"id": "m", "to": [to], "at": Q, "open": open_, "verdict": verdict, "replied_at": replied}

    def states(asks):
        got = reviewmod.walk(links, asks)
        return [r["state"] for r in got["chain"]], got["turn"], got["merges"]

    # taken to the person (closed, no reply landed): the reader's turn is the author's to ask again
    assert states([ask("ao-x-ui-reader-ao", open_=False)]) == (["next", "later"], "ui-reader-ao", "techlead-ao")
    # a reply with no verdict still reads asked
    assert states([ask("ao-x-ui-reader-ao", open_=False, replied=AT)])[0] == ["asked", "later"]
    # an asked_person ask with a later pass reply reads passed
    passed = ask("ao-x-ui-reader-ao", open_=False, verdict="pass", replied=AT)
    assert states([passed]) == (["passed", "next"], "techlead-ao", "techlead-ao")
    # a lapsed or expired ask on the second link: next, never asked
    assert states([passed, ask("ao-x-techlead-ao", open_=False)]) == (["passed", "next"], "techlead-ao", "techlead-ao")


def test_clock_names_the_day_when_not_today():
    now = datetime(2026, 11, 5, 12, tzinfo=UTC)
    other = (now - timedelta(days=2)).isoformat()
    assert unanswered.clock(other, now)[:3].isalpha()
    assert unanswered.clock("not a time", now) == "not a time"


def test_a_withdrawn_or_declined_ask_reads_as_the_links_turn_too():
    # §4.9b *What `ao pr held` reads meanwhile*: closed with no reply landed, whatever the reason
    links = [{"stage": "review", "reader": "techlead-ao", "paths": ["b"]}]
    for reason in ("withdrawn", "declined", "asker_gone"):
        ask = {"id": "m", "to": ["ao-x-techlead-ao"], "at": Q, "open": False, "verdict": None, "replied_at": None}
        got = reviewmod.walk(links, [{**ask, "closed_reason": reason}])
        assert got["chain"][0]["state"] == "next" and got["turn"] == "techlead-ao"


def test_words_fall_back_to_the_plain_line():
    plain = "tl did not answer."
    for stamp in (
        {"state": "nonsense"},
        {"state": "working", "waiting": "many"},
        {"state": "gated"},
        {"state": "gated", "gate": "max"},
        {"state": "gated", "gate": {"resets": AT}},
        {"state": "suspended"},
        {"state": "fills_exhausted"},
        {"state": "restart_ceiling"},
        {"state": "scheduled"},
        {"state": "ended"},
    ):
        assert _words({"by": "ao-x-tl", "name": "tl", "at": AT, **stamp}) == plain, stamp


def test_ao_inbox_prints_the_line_only_under_a_stamped_entry(monkeypatch, capsys):
    from shiftlead import cli

    def entry(mid, **kw):
        return {"id": mid, "from": "ao-x-w", "from_role": "other", "to": ["person"], "at": AT, "kind": "ask",
                "text": f"text {mid}", "root": mid, **kw}  # fmt: skip

    stamped = entry("m-1", unanswered={"by": "ao-x-tl", "name": "tl", "at": AT, "state": "not_filled"})
    got = {"id": "person", "entries": [stamped, entry("m-2")], "unread": 0}
    monkeypatch.setattr(cli, "call_sync", lambda m, **kw: got)
    assert cli.main(["inbox"]) == 0
    out = capsys.readouterr().out
    line = f"  not answered by tl (as read at {unanswered.clock(AT)}): tl was never filled for this question."
    assert out.count("not answered by") == 1 and line in out
    assert out.index("text m-1") < out.index(line) < out.index("text m-2")
