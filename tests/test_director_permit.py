"""The director seat's `permit` grant (design §4.8, §4.9b *The director seat answers permission prompts for the
person*, TD-642 slice 1): `decide` on any unattended record's pending prompt without being among its controllers,
with a reason the person is told in *Answered for you*; refused on an interactive record, on itself, without a
reason, on an *allow* of a prompt that always reaches the person (a deny stands), and for every other act."""

import asyncio

import pytest
from conftest import wait_state
from test_permission_rules import _hook, rulestub  # noqa: F401 — the fixture

from sessionorc import mail
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import ALL_GRANTS, GRANTS, Session


def _rec(sid: str, *, grants=(), unattended=True, kind="agent", controllers=None) -> Session:
    s = Session(id=sid, name=sid, dir="/x", adapter="shell", kind=kind, unattended=unattended)
    s.capabilities = list(grants)
    if controllers is not None:
        s.controllers = list(controllers)
    return s


def test_permit_is_a_grant_and_passes_decide_alone():
    # the seat's, never the person's to tick or `ao grant` (§4.5a *New session: Grants*)
    assert "permit" in ALL_GRANTS and "permit" not in GRANTS
    recs = {
        "d": _rec("d", grants=["permit"]),
        "w": _rec("w", controllers=["m"]),
        "i": _rec("i", kind="interactive", unattended=False),
        "m": _rec("m", grants=["control"]),
    }
    gate = mail.act_gate
    assert gate(recs, "d", "decide", {"id": "w"}) is None
    assert mail.by_permit(recs, "d", {"id": "w"}) is True
    # a controller holding control answers as before, not by permit
    assert mail.by_permit(recs, "m", {"id": "w"}) is False
    assert mail.by_permit(recs, None, {"id": "w"}) is False  # the person
    assert "invariant 5" in gate(recs, "d", "decide", {"id": "i"})
    assert "itself" in gate(recs, "d", "decide", {"id": "d"})
    for method in ("send", "keys", "kill", "close"):
        assert "control grant" in gate(recs, "d", method, {"id": "w"}), method


@pytest.mark.integration
async def test_the_director_decides_an_unattended_prompt_with_a_reason_and_tells_the_person(
    agent,
    rulestub,  # noqa: F811 — the fixture, imported above
    tmp_path,
):
    for d in ("w", "d", "i"):
        (tmp_path / d).mkdir()
    async with LocalClient() as c:
        w = (
            await c.call(
                "create", name="w", dir=str(tmp_path / "w"), adapter="rulestub", unattended=True, role="grinder"
            )
        )["id"]
        d = (
            await c.call(
                "create", name="director", dir=str(tmp_path / "d"), adapter="rulestub", unattended=True,
                capabilities=["permit"],
            )
        )["id"]  # fmt: skip
        i = (await c.call("create", name="i", dir=str(tmp_path / "i"), adapter="rulestub"))["id"]
        async with LocalClient(caller=d) as dc:
            task = asyncio.create_task(_hook(w, "Bash", "pdm run test", "t1"))
            await wait_state(c, w, "needs-you")
            with pytest.raises(AgentError, match="without a reason"):
                await dc.call("decide", id=w, tool_use_id="t1", behavior="allow")
            await dc.call("decide", id=w, tool_use_id="t1", behavior="allow", reason="the member's own test run")
            assert await task == {"behavior": "allow", "reason": "the member's own test run"}
            fyi = [e for e in agent.person_inbox if e.answered]
            assert len(fyi) == 1 and fyi[0].answered == {
                "question": "Bash: pdm run test",
                "asker": w,
                "answerer": d,
                "source": "the member's own test run",
            }
            assert fyi[0].text.startswith("allowed by director:")
            # an allow of a prompt kept for the person is refused, and a deny of it stands
            task = asyncio.create_task(_hook(w, "Bash", "cat ~/.shiftlead/settings.yml", "t2"))
            await wait_state(c, w, "needs-you")
            with pytest.raises(AgentError, match="always reaches the person"):
                await dc.call("decide", id=w, tool_use_id="t2", behavior="allow", reason="looks fine")
            await dc.call("decide", id=w, tool_use_id="t2", behavior="deny", reason="the home's settings")
            assert (await task)["behavior"] == "deny"
            assert len([e for e in agent.person_inbox if e.answered]) == 2
            # an interactive record's prompt is out of reach, and so is any other act
            task = asyncio.create_task(_hook(i, "Bash", "ls", "t3"))
            await wait_state(c, i, "needs-you")
            with pytest.raises(AgentError, match="invariant 5"):
                await dc.call("decide", id=i, tool_use_id="t3", behavior="deny", reason="no")
            await c.call("decide", id=i, tool_use_id="t3", behavior="allow")
            await task
            with pytest.raises(AgentError, match="control grant"):
                await dc.call("send", id=w, text="hi")
        # a person's own decide is no director's: nothing more is told
        task = asyncio.create_task(_hook(w, "Bash", "ls", "t4"))
        await wait_state(c, w, "needs-you")
        await c.call("decide", id=w, tool_use_id="t4", behavior="allow")
        await task
        assert len([e for e in agent.person_inbox if e.answered]) == 2
