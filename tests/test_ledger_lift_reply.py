# ruff: noqa: F811 — `repo` is the imported fixture, named by each test's argument
"""The outcome's lift and reply (design §4.4 *The outcome's lift and reply*, TD-1829, built by TD-1879): a `blocked`
outcome's **Lift the hold** is one request, `ledger_lift_reply` — the entry's lift through `_press_lift`, then the
person's plain reply to the question through `_msg`'s internal `lift_first`, its text chosen after the lift."""

from __future__ import annotations

import pytest
from test_ask_lift import _replies, _worker
from test_ledger_lift_press import (
    _entry,
    _home,
    _origin_entry,
    repo,  # noqa: F401 — the `repo` fixture, which each test's argument names
)

from sessionorc.agent_common import RpcError
from sessionorc.client import AgentError, LocalClient

pytestmark = pytest.mark.integration


async def _stopped(person, c, w: str, about: str = "repo#TD-190", subject: str = "stuck") -> str:
    """A question about the entry, answered by the person, then reported `blocked` by its asker: its id."""
    q = (await c.call("msg", to="person", kind="ask", text="May I go on?", about=about, subject=subject))["entry"]["id"]
    await person.call("msg", to=w, kind="reply", reply_to=q, text="go on")
    await c.call("msg", to="person", kind="note", text="waits on the hold", outcome="blocked", for_=q)
    return q


def _copy(agent, mid: str):
    return next(e for e in agent.person_inbox if e.id == mid)


async def test_the_press_lifts_the_gate_then_replies_and_stamps_the_outcome(agent, repo, monkeypatch):
    """The lift lands (its Log's answer *go ahead*), then a plain reply to the asker — *I lifted the hold on TD-n
    myself*, no `lifted` field nor closing line — and the outcome records `replied`; a second press is refused."""
    root = await _home(agent, repo, monkeypatch, [_entry(190)])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            q = await _stopped(person, c, w)
        got = await person.call("ledger_lift_reply", repo=root, id="TD-190", msg=q)
        assert got["lifted"] is True and got["gone"] is False and got["id"] == "TD-190" and "failed" not in got
        sent = got["entry"]
        assert sent["text"] == "I lifted the hold on TD-190 myself" and sent["to"] == [w]
        assert sent["lifted"] is None and sent["answer"] is None and "\n\n" not in sent["text"]
        assert _copy(agent, q).outcome["replied"]["by"] == sent["id"]
        with pytest.raises(AgentError, match=f"{q} has no blocked outcome waiting on your reply"):
            await person.call("ledger_lift_reply", repo=root, id="TD-190", msg=q)
    entry = _origin_entry(repo, 190)
    assert "**Blocked by:**" not in entry and 'gate lifted: decision (paul) — by paul; answer "go ahead"' in entry


async def test_a_gate_already_gone_still_replies(agent, repo, monkeypatch):
    """An open entry no longer carrying the gate: `{gone}`, and the reply *TD-n was no longer held when I pressed
    Lift the hold*, recorded `replied`."""
    root = await _home(agent, repo, monkeypatch, [_entry(190, gated=False)])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            q = await _stopped(person, c, w)
        got = await person.call("ledger_lift_reply", repo=root, id="TD-190", msg=q)
    assert got["gone"] is True and got["lifted"] is False
    assert got["entry"]["text"] == "TD-190 was no longer held when I pressed Lift the hold"
    assert _copy(agent, q).outcome["replied"]


async def test_the_requests_refusals_send_nothing(agent, repo, monkeypatch):
    """A session caller, a question with no `blocked` outcome, a stale `{repo, id}`, an `Owner:` the person entry, a
    refused lift, and a `msg` RPC carrying `lift_first` — each refused, nothing sent, the outcome unreplied."""
    root = await _home(agent, repo, monkeypatch, [_entry(190), _entry(191, owner="paul")])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            q = await _stopped(person, c, w)
            mine = await _stopped(person, c, w, about="repo#TD-191", subject="mine")
            plain = (await c.call("msg", to="person", kind="ask", text="ok?", about="repo#TD-190"))["entry"]["id"]
            with pytest.raises(AgentError, match="a person's own act"):
                await c.call("ledger_lift_reply", repo=root, id="TD-190", msg=q)
            with pytest.raises(AgentError):
                await c.call("msg", kind="reply", reply_to=q, text="x", lift_first={"root": root, "id": "TD-190"})
        with pytest.raises(AgentError, match="lift_first is the outcome's lift and reply's own"):
            await person.call("msg", kind="reply", reply_to=q, text="x", lift_first={"root": root, "id": "TD-190"})
        with pytest.raises(AgentError, match=f"{plain} has no blocked outcome"):
            await person.call("ledger_lift_reply", repo=root, id="TD-190", msg=plain)
        with pytest.raises(AgentError, match="reload the Queue"):
            await person.call("ledger_lift_reply", repo=root, id="TD-191", msg=q)
        with pytest.raises(AgentError, match="TD-191 is yours to do: its Done answers it"):
            await person.call("ledger_lift_reply", repo=root, id="TD-191", msg=mine)
        pressed: list[str] = []

        async def refuse(root, id, **kw):
            pressed.append(kw.get("asker"))
            raise RpcError("TD-190's hold is asked on board:0000abcd: answer it there")

        monkeypatch.setattr(agent, "_press_lift", refuse)
        with pytest.raises(AgentError, match="hold is asked on board:0000abcd") as no:
            await person.call("ledger_lift_reply", repo=root, id="TD-190", msg=q)
        assert "lifted" not in str(no.value)
    assert pressed == [w], "the lift is handed the asker, whose own claims case (b) leaves out"
    for mid in (q, mine):
        assert not _copy(agent, mid).outcome.get("replied") and not _replies(agent, mid)[1:]
    assert "**Blocked by:** decision (paul)" in _origin_entry(repo, 190), "nothing was lifted"


async def test_a_reply_failing_after_the_lift_says_lifted_with_its_reason(agent, repo, monkeypatch):
    """The asker gone during the lift: the hold stands lifted and the request returns `lifted: true` with the bare
    reason, never a refusal; nothing is stored."""
    root = await _home(agent, repo, monkeypatch, [_entry(190)])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            q = await _stopped(person, c, w)
        before = len(_replies(agent, q))

        async def lift(root, id, **kw):
            _copy(agent, q).orphaned = {"how": "closed", "ref": "repo#TD-190"}
            return {"repo": root, "id": id, "lifted": True}

        monkeypatch.setattr(agent, "_press_lift", lift)
        got = await person.call("ledger_lift_reply", repo=root, id="TD-190", msg=q)
    assert got["lifted"] is True and "asker is gone" in got["failed"] and "entry" not in got
    assert len(_replies(agent, q)) == before and not _copy(agent, q).outcome.get("replied")


async def test_the_question_is_held_across_the_lift_and_the_reply(agent, repo, monkeypatch):
    """During the request the question's id is held: a second press, a reply, a Delete, a Dismiss and a Not clear on
    it are refused *<id> is already being answered*; the request lands after and releases it."""
    root = await _home(agent, repo, monkeypatch, [_entry(190)])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            q = await _stopped(person, c, w)
        seen: list[str] = []

        async def lift(root, id, **kw):
            async with LocalClient() as p2:
                for call, kw2 in (
                    (p2.call, {"method": "ledger_lift_reply", "repo": root, "id": "TD-190", "msg": q}),
                    (p2.call, {"method": "msg", "kind": "reply", "reply_to": q, "text": "later"}),
                    (p2.call, {"method": "inbox_delete", "msg": q}),
                    (p2.call, {"method": "inbox_dismiss", "msg": [q]}),
                ):
                    method = kw2.pop("method")
                    with pytest.raises(AgentError, match=f"{q} is already being answered"):
                        await call(method, **kw2)
                    seen.append(method)
                # Not clear tests the key too (TD-1853), behind its own refusal of a question already closed
                with pytest.raises(AgentError, match=f"{q} is already (being answered|closed)"):
                    await p2.call("inbox_not_clear", msg=q)
                seen.append("inbox_not_clear")
            return {"repo": root, "id": id, "lifted": True}

        monkeypatch.setattr(agent, "_press_lift", lift)
        got = await person.call("ledger_lift_reply", repo=root, id="TD-190", msg=q)
    assert seen == ["ledger_lift_reply", "msg", "inbox_delete", "inbox_dismiss", "inbox_not_clear"]
    assert got["lifted"] is True and q not in agent._board_adding
