"""TD-661, design §4.9b *Passing up keeps the thread and the asker* and *The director answers what is passed up
to it*: where the org has a director seat that can be filled, a techlead's pass lands in the director's inbox and
makes it due by `asks`; the director's pass reaches the person showing both recommendations; `passes` holds one
pass per passer; with no director, or one suspended or at its fill ceiling, the pass goes to the person as before;
the person's reply goes to the asker, is copied to every passer and closes every copy."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import park_ticks

from sessionorc import reports
from sessionorc.client import AgentError, LocalClient

pytestmark = pytest.mark.integration

SHELL = {"adapter": "agentshell", "argv": ["bash", "--norc", "--noprofile"], "unattended": True, "supervised": True}
Q = "Should the flag be renamed?"


@pytest.fixture(autouse=True)
def _no_gh(monkeypatch):
    monkeypatch.setattr(reports, "merged_prs", lambda *a, **kw: None)


async def _make(person, tmp_path, name: str, **kw) -> str:
    (tmp_path / name).mkdir(exist_ok=True)
    return (await person.call("create", **{**SHELL, "name": name, "dir": str(tmp_path / name), **kw}))["id"]


async def _org(person, tmp_path, director: bool = True) -> tuple[str, str, str | None]:
    w = await _make(person, tmp_path, "w", team="ao-grind")
    tl = await _make(person, tmp_path, "tl", team="ao-grind")
    d = await _make(person, tmp_path, "director", prompt="brief", seat={"trigger": "prompt"}) if director else None
    return w, tl, d


def _copies(agent, mid: str) -> list:
    return [e for r in agent.sessions.values() for e in r.holds(mid)] + [e for e in agent.person_inbox if e.id == mid]


async def test_a_pass_goes_to_the_director_then_to_the_person_with_both_recommendations(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        w, tl, d = await _org(person, tmp_path)
        async with LocalClient(caller=w) as wc, LocalClient(caller=tl) as tc, LocalClient(caller=d) as dc:
            q = (await wc.call("msg", to=tl, text="rename the flag?", kind="ask"))["entry"]
            # a seat reads the asker's own text: no --question on a pass to the director
            with pytest.raises(AgentError, match="without --question"):
                await tc.call("pass_up", id=q["id"], recommend="keep it", question=Q)
            got = await tc.call("pass_up", id=q["id"], recommend="keep it", answers=["rename it"])
            assert got["id"] == d and got["answers"] == ["keep it", "rename it"]
            assert not any(e.id == q["id"] for e in agent.person_inbox), "the person is not asked yet"
            held = [e for e in agent.sessions[d].inbox if e.id == q["id"]]
            assert len(held) == 1 and held[0].from_ == w and held[0].text == "rename the flag?"
            assert held[0].answers == ["keep it", "rename it"] and held[0].passed_to == d
            # the director is due by `asks`, the techlead no longer
            assert (await person.call("get", id=d))["asks_waiting"] == 1
            assert (await person.call("get", id=tl))["asks_waiting"] == 0
            rd = agent.sessions[d]
            due = agent._seat_due(rd, datetime.now(UTC), [rd])
            assert due["by"] == "asks" and due["ask"] == q["id"]
            # once per passer: the techlead may not pass it again
            with pytest.raises(AgentError, match="once"):
                await tc.call("pass_up", id=q["id"], recommend="again")
            # the director passes it on to the person, with the person's question
            with pytest.raises(AgentError, match="--question"):
                await dc.call("pass_up", id=q["id"], recommend="keep it, the docs name it")
            up = await dc.call("pass_up", id=q["id"], recommend="keep it, the docs name it", question=Q)
            assert up["id"] == "person"
            mine = [e for e in agent.person_inbox if e.id == q["id"]]
            assert len(mine) == 1 and mine[0].recommend["by"] == d
            assert [(p["by"], p["to"], p["recommend"]["text"]) for p in mine[0].passes] == [
                (tl, d, "keep it"),
                (d, "person", "keep it, the docs name it"),
            ]
            assert (await person.call("get", id=d))["asks_waiting"] == 0
            with pytest.raises(AgentError, match="once"):
                await dc.call("pass_up", id=q["id"], recommend="again", question=Q)
            # the person's reply: to the asker, copied to both passers, closing every copy
            r = await person.call("msg", reply_to=q["id"], kind="reply", text="keep it, the docs name it", answer=0)
            assert r["delivered"] == [w] and sorted(r["copies"]) == sorted([tl, d]) and r["closed"] == q["id"]
            assert all(not e.open for e in _copies(agent, q["id"]))
            assert q["id"] in agent.sessions[w].owed() and q["id"] not in agent.sessions[d].owed()
        for sid in (w, tl, d):
            await person.call("kill", id=sid)


async def test_the_director_answers_a_pass_and_the_asker_has_it(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        w, tl, d = await _org(person, tmp_path)
        async with LocalClient(caller=w) as wc, LocalClient(caller=tl) as tc, LocalClient(caller=d) as dc:
            q = (await wc.call("msg", to=tl, text="squash or merge?", kind="ask"))["entry"]
            await tc.call("pass_up", id=q["id"], recommend="squash")
            got = await dc.call("msg", reply_to=q["id"], kind="reply", text="squash", source="cadence §4 squash merge")
            assert w in got["delivered"] and got["closed"] == q["id"]
            assert all(not e.open for e in _copies(agent, q["id"]))
            assert (await person.call("get", id=d))["asks_waiting"] == 0
            # the person answered nothing: the asker owes the person no outcome on it (review of #4275)
            assert q["id"] not in agent.sessions[w].owed()
            # a question the director itself asked is never passed up to it: it goes to the person
            assert agent._director_to_pass_to(tl, d) is None and agent._director_to_pass_to(tl, w) == d
        for sid in (w, tl, d):
            await person.call("kill", id=sid)


@pytest.mark.parametrize("how", ["none", "suspended", "unfillable"])
async def test_with_no_director_that_can_be_filled_the_pass_goes_to_the_person(agent, tmp_path, how):
    await park_ticks(agent)
    async with LocalClient() as person:
        w, tl, d = await _org(person, tmp_path, director=how != "none")
        if how == "suspended":
            agent.sessions[d].suspended = {"at": "2026-11-20T00:00:00Z", "by": "person", "why": "test"}
        elif how == "unfillable":
            agent.unfillable[d] = "at its fill ceiling"
        async with LocalClient(caller=w) as wc, LocalClient(caller=tl) as tc:
            q = (await wc.call("msg", to=tl, text="rename the flag?", kind="ask"))["entry"]
            with pytest.raises(AgentError, match="--question"):
                await tc.call("pass_up", id=q["id"], recommend="keep it")
            got = await tc.call("pass_up", id=q["id"], recommend="keep it", question=Q)
            assert got["id"] == "person"
            mine = [e for e in agent.person_inbox if e.id == q["id"]]
            assert len(mine) == 1 and [p["to"] for p in mine[0].passes] == ["person"]
            if d:
                assert not any(e.id == q["id"] for e in agent.sessions[d].inbox)
        for sid in (w, tl, d):
            if sid:
                await person.call("kill", id=sid)


async def test_not_clear_on_the_directors_pass_gives_it_back_to_the_director(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        w, tl, d = await _org(person, tmp_path)
        async with LocalClient(caller=w) as wc, LocalClient(caller=tl) as tc, LocalClient(caller=d) as dc:
            q = (await wc.call("msg", to=tl, text="rename the flag?", kind="ask"))["entry"]
            await tc.call("pass_up", id=q["id"], recommend="keep it")
            await dc.call("pass_up", id=q["id"], recommend="keep it", question=Q)
            await person.call("inbox_not_clear", msg=q["id"])
            assert not any(e.id == q["id"] for e in agent.person_inbox)
            held = [e for e in agent.sessions[d].inbox if e.id == q["id"]][0]
            assert held.open and held.passed_to == d and [p["by"] for p in held.passes] == [tl]
            assert held.recommend["by"] == tl
            assert (await person.call("get", id=d))["asks_waiting"] == 1
            assert (await person.call("get", id=tl))["asks_waiting"] == 0
        for sid in (w, tl, d):
            await person.call("kill", id=sid)
