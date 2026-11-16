# ruff: noqa: F811 — `repo` is the imported fixture, named by each test's argument
"""An `ask` that lifts the person's gate (design §4.10 *An `ask` that lifts the person's gate*, TD-1829, built by
TD-1833): `ao msg --lift` names the answers whose press lifts the `about` entry's `decision (paul)`; each send check
refuses in its words; the person's lifting answer lifts the gate through `_press_lift` before the reply is stored,
which carries `lifted` (or `lifted_before`); every other road lifts nothing."""

from __future__ import annotations

import pytest
from test_ledger_lift_press import (
    _entry,
    _home,
    _origin_entry,
    repo,  # noqa: F401 — the `repo` fixture, which each test's argument names
)

from sessionorc import queue as queue_mod
from sessionorc.agent_common import RpcError
from sessionorc.client import AgentError, LocalClient

pytestmark = pytest.mark.integration

ANSWERS = ["Lift it — a session goes on with the work", "Keep it — nobody picks the entry", "Not yet — it waits"]


async def _worker(person, repo, name: str = "w") -> str:
    d = repo.parent / name  # one directory each (§9 invariant 2)
    d.mkdir(exist_ok=True)
    got = await person.call("create", name=name, dir=str(d), adapter="agentshell", argv=["bash", "--norc"],
                            unattended=True)  # fmt: skip
    return got["id"]


async def _ask(c, about: str = "repo#TD-190", subject: str = "lift", **kw) -> str:
    sent = await c.call("msg", to="person", kind="ask", text="May the hold go?", answers=ANSWERS, lift=["Lift it"],
                        about=about, subject=subject, **kw)  # fmt: skip
    return sent["entry"]["id"]


def _person_copy(agent, mid: str):
    return next(e for e in agent.person_inbox if e.id == mid)


def _replies(agent, mid: str) -> list:
    return [e for e in agent.person_inbox if e.reply_to == mid] + [
        e for s in agent.sessions.values() for e in s.inbox if e.reply_to == mid
    ]


async def test_each_send_check_refuses_in_its_words(agent, repo, monkeypatch):
    """Kind, the person directly, the labels, `--about` given and open, the gate the person's, the entry not the
    person's to do, and no board item already asking the gate — each refused, nothing sent."""
    await _home(agent, repo, monkeypatch, [_entry(190), _entry(191, owner="paul"), _entry(192, gated=False)])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        v = await _worker(person, repo, "v")
        async with LocalClient(caller=w) as c:
            base = {"to": "person", "kind": "ask", "text": "May it go?", "answers": ANSWERS, "about": "repo#TD-190"}
            cases = [
                ({"kind": "steer", "default": "Keep it"}, "only an ask lifts the person's gate: a steer"),
                ({"to": v}, "a lifting ask is put to the person directly"),
                ({"to": None, "team": "ao-grind"}, "a lifting ask is put to the person directly"),
                ({"lift": ["Lift it", "Lift it"]}, "'Lift it' is named twice"),
                ({"lift": ["Go"]}, "'Go' is not the label of one of the answers"),
                ({"lift": ["Not yet"]}, "'Not yet' reads as waiting, which never lifts"),
                ({"answers": [*ANSWERS, "Other: <what>"], "lift": ["Other: <what>"]}, "is a form"),
                ({"answers": ["Lift it — I go", "Lift it (default) — you go"]}, "two of them read the same"),
                ({"about": None}, "a lifting ask names the entry it lifts: --about TD-n"),
                ({"about": "nowhere#TD-190"}, "names no entry of a repo this home reads"),
                ({"about": "repo#TD-404"}, "TD-404 is no open entry of repo's ledger"),
                ({"about": "repo#TD-192"}, r"TD-192 carries no decision \(paul\)"),
                ({"about": "repo#TD-191"}, "TD-191 is yours to do: its Done answers it"),
            ]
            for extra, words in cases:
                kw = {**base, "lift": ["Lift it"], **extra}
                with pytest.raises(AgentError, match=words):
                    await c.call("msg", **{k: x for k, x in kw.items() if x is not None})
            monkeypatch.setattr(queue_mod, "lift_case_d_item", lambda *a, **k: "board:0000abcd")
            with pytest.raises(AgentError, match="TD-190's hold is asked on board:0000abcd: answer it there"):
                await c.call("msg", **base, lift=["Lift it"])
            monkeypatch.undo()
    assert not [e for e in agent.person_inbox if e.lift], "nothing was sent"


async def test_a_lifting_answer_lifts_the_gate_and_the_reply_carries_lifted(agent, repo, monkeypatch):
    """The ask keeps `lift` as labels; the person's press on a lifting answer lifts the gate (its Log's answer the
    label) and stores the reply with `lifted` and its closing line, closing the ask `replied`."""
    root = await _home(agent, repo, monkeypatch, [_entry(190)])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            mid = await _ask(c)
        assert _person_copy(agent, mid).lift == ["Lift it"]
        got = await person.call("msg", kind="reply", reply_to=mid, text="Lift it", answer=0)
    assert got["lifted"] == "repo#TD-190" and got["lifted_before"] is None
    assert got["entry"]["lifted"] == "repo#TD-190"
    assert got["entry"]["text"].endswith("\n\n— the hold on TD-190 is lifted")
    assert _person_copy(agent, mid).closed_reason == "replied"
    entry = _origin_entry(repo, 190)
    assert "**Blocked by:**" not in entry and 'gate lifted: decision (paul) — by paul; answer "Lift it"' in entry
    assert root


async def test_the_askers_own_claim_never_refuses_and_another_sessions_does(agent, repo, monkeypatch):
    """Case (b) is read with the asker's own records left out: its claim on the entry is the work that asked."""
    await _home(agent, repo, monkeypatch, [_entry(190)])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        v = await _worker(person, repo, "v")
        holder = {"id": w}

        def claims(records, repos, now):
            ids = {str(r.id) for r in records}
            return {"repo#TD-190": holder["id"]} if holder["id"] in ids else {}

        monkeypatch.setattr(queue_mod, "held_claims", claims)
        async with LocalClient(caller=w) as c:
            other = await _ask(c, subject="other")
            holder["id"] = v
            with pytest.raises(AgentError, match="is being acted on by"):
                await person.call("msg", kind="reply", reply_to=other, text="Lift it", answer=0)
            assert _person_copy(agent, other).open and not _replies(agent, other), "a refused lift stores nothing"
            holder["id"] = w
            got = await person.call("msg", kind="reply", reply_to=other, text="Lift it", answer=0)
    assert got["lifted"] == "repo#TD-190"


async def test_the_roads_that_lift_nothing(agent, repo, monkeypatch):
    """A non-lifting answer, a worded reply, a session's pick on a copy carrying `lift`, and an orphaned ask's answer
    never call the lift."""
    await _home(agent, repo, monkeypatch, [_entry(190)])
    pressed: list[tuple] = []

    async def press(root, id, **kw):
        pressed.append((id, kw))
        return {"repo": root, "id": id, "lifted": True}

    monkeypatch.setattr(agent, "_press_lift", press)
    async with LocalClient() as person:
        w = await _worker(person, repo)
        v = await _worker(person, repo, "v")
        async with LocalClient(caller=w) as c:
            a = await _ask(c, subject="a")
            b = await _ask(c, subject="b")
            got = await person.call("msg", kind="reply", reply_to=a, text="Keep it", answer=1)
            assert got["lifted"] is None and "lifted" not in got["entry"]["text"]
            await person.call("msg", kind="reply", reply_to=b, text="please lift it")
            # a session's reply to a question carrying `lift` (never sent so, written here) lifts nothing
            q = (await person.call("msg", to=v, kind="ask", text="ok?", answers=ANSWERS))["entry"]["id"]
            next(e for e in agent.sessions[v].inbox if e.id == q).lift = ["Lift it"]
            async with LocalClient(caller=v) as vc:
                await vc.call("msg", kind="reply", reply_to=q, text="Lift it", answer=0)
            # an orphaned ask's answer takes the orphan road, which lifts nothing
            o = await _ask(c, subject="o")
            _person_copy(agent, o).orphaned = {"how": "closed", "ref": "repo#TD-190"}
            orphan: list[str] = []

            async def answer_orphan(e, text, reason, picked=None):
                orphan.append(e.id)
                return {"board": True, "note": "written"}

            monkeypatch.setattr(agent, "_answer_orphan", answer_orphan)
            await person.call("msg", kind="reply", reply_to=o, text="Lift it", answer=0)
    assert orphan == [o] and pressed == []


async def test_a_gone_gate_a_refused_lift_and_a_failed_store(agent, repo, monkeypatch):
    """A gate already gone stores the reply with `lifted_before`; a refused lift refuses the reply in its words and
    stores none; an asker gone during the lift refuses as *lifted; the answer was not sent*; an entry made the
    person's to do after the send is refused *yours to do*, no reply stored."""
    await _home(agent, repo, monkeypatch, [_entry(190)])
    state = {"do": "gone"}

    async def press(root, id, **kw):
        if state["do"] == "refuse":
            raise RpcError("TD-190's hold is asked on board:0000abcd: answer it there")
        if state["do"] == "orphan":
            _person_copy(agent, state["mid"]).orphaned = {"how": "closed", "ref": "repo#TD-190"}
            return {"repo": root, "id": id, "lifted": True}
        return {"repo": root, "id": id, "gone": True}

    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            gone, refused, orphaned, owned = [await _ask(c, subject=s) for s in ("g", "r", "o", "y")]
        real = agent._press_lift
        monkeypatch.setattr(agent, "_press_lift", press)
        got = await person.call("msg", kind="reply", reply_to=gone, text="Lift it", answer=0)
        assert got["lifted"] is None and got["lifted_before"] == "repo#TD-190"
        assert got["entry"]["text"].endswith("— TD-190 was no longer held")
        state["do"] = "refuse"
        with pytest.raises(AgentError, match="hold is asked on board:0000abcd"):
            await person.call("msg", kind="reply", reply_to=refused, text="Lift it", answer=0)
        assert _person_copy(agent, refused).open and not _replies(agent, refused)
        state.update(do="orphan", mid=orphaned)
        with pytest.raises(AgentError, match="the hold on TD-190 is lifted; the answer was not sent: .*asker is gone"):
            await person.call("msg", kind="reply", reply_to=orphaned, text="Lift it", answer=0)
        assert not _replies(agent, orphaned)
        monkeypatch.setattr(agent, "_press_lift", real)
        agent._repos[next(iter(agent._repos))]["ledger"]["entries"] = [_entry(190, owner="paul")]
        with pytest.raises(AgentError, match="TD-190 is yours to do: its Done answers it"):
            await person.call("msg", kind="reply", reply_to=owned, text="Lift it", answer=0)
        assert _person_copy(agent, owned).open and not _replies(agent, owned)


async def test_a_failed_store_after_a_gone_gate_refuses_in_its_own_words(agent, repo, monkeypatch):
    """TD-1902: only a store that fails after a landed lift says *the hold is lifted*; where the gate was already
    gone (`lifted_before`) the press lifted nothing, so the store's own error is the refusal, and no reply lands."""
    await _home(agent, repo, monkeypatch, [_entry(190)])
    state: dict[str, str] = {}

    async def press(root, id, **kw):
        _person_copy(agent, state["mid"]).orphaned = {"how": "closed", "ref": "repo#TD-190"}  # the store then fails
        return {"repo": root, "id": id, "gone": True}

    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            state["mid"] = await _ask(c)
        monkeypatch.setattr(agent, "_press_lift", press)
        with pytest.raises(AgentError, match="asker is gone") as err:
            await person.call("msg", kind="reply", reply_to=state["mid"], text="Lift it", answer=0)
        assert "is lifted" not in str(err.value) and "the answer was not sent" not in str(err.value)
        assert not _replies(agent, state["mid"])


async def test_a_withdraw_a_delete_and_a_second_reply_racing_the_lift_are_refused(agent, repo, monkeypatch):
    """The lifting road holds the ask's id: a withdraw, a Delete and a second reply during it are refused with
    *<id> is already being answered*, and the reply lands after."""
    await _home(agent, repo, monkeypatch, [_entry(190)])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            mid = await _ask(c)
            seen: list[str] = []

            async def press(root, id, **kw):
                async with LocalClient() as p2, LocalClient(caller=w) as c2:  # the outer press holds `person`
                    for call, kw2 in (
                        (c2.call, {"method": "msg_withdraw", "id": mid}),
                        (p2.call, {"method": "inbox_delete", "msg": mid}),
                        (p2.call, {"method": "msg", "kind": "reply", "reply_to": mid, "text": "Keep it", "answer": 1}),
                    ):
                        method = kw2.pop("method")
                        with pytest.raises(AgentError, match=f"{mid} is already being answered"):
                            await call(method, **kw2)
                        seen.append(method)
                return {"repo": root, "id": id, "lifted": True}

            monkeypatch.setattr(agent, "_press_lift", press)
            got = await person.call("msg", kind="reply", reply_to=mid, text="Lift it", answer=0)
    assert seen == ["msg_withdraw", "inbox_delete", "msg"] and got["lifted"] == "repo#TD-190"
    assert mid not in agent._board_adding
