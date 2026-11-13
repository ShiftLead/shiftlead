"""No line but the brief is typed into the pane of a tool whose start hooks ride the first prompt until that
brief is in (design §4.3 *The repo's start hooks*, *No send until it is in*, TD-1637): a send is refused in
words and leaves no trace, a wrap-up stops the session, `ao keys` is the person's alone, a policy's line and
the pause line wait, and a stop time stops it. A tool with a start context is untouched."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import adapters
from sessionorc.client import AgentError, LocalClient
from sessionorc.agent_common import RpcError
from sessionorc.models import Pending

pytestmark = pytest.mark.integration

REFUSED = r"w's brief is not in yet; send again once it is \(design §4\.3\)\."


@pytest.fixture
def hooks_ride(agent, monkeypatch):
    """`agentshell` as a tool with no start context: core runs the start hooks into its brief."""
    monkeypatch.setattr(adapters.get("agentshell"), "start_context", False, raising=False)
    assert adapters.core_runs_start_hooks("agentshell")


async def _due(agent, person, tmp_path, **kw) -> str:
    d = tmp_path / "w"
    os.makedirs(d, exist_ok=True)
    sid = (
        await person.call(
            "create",
            name="w",
            dir=str(d),
            adapter="agentshell",
            argv=["bash", "--norc", "--noprofile"],
            unattended=True,
            **kw,
        )
    )["id"]
    rec = agent.sessions[sid]
    rec.first_prompt = "the brief"  # due: neither sent nor given up on
    rec.set_state("idle", confidence="hook")
    return sid


async def test_a_send_is_refused_until_the_brief_is_in_and_leaves_no_trace(agent, hooks_ride, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _due(agent, person, tmp_path)
        rec = agent.sessions[sid]
        with pytest.raises(RpcError, match=REFUSED):
            await agent.rpc_send(sid, "hello", caller="ao-lead")  # a manager's send
        with pytest.raises(AgentError, match=REFUSED):
            await person.call("send", id=sid, text="hello")  # the person's own send too
        assert rec.sends == [] and rec.wrapup_at is None
        rec.first_prompt_sent_at = datetime.now(UTC).isoformat()
        await person.call("send", id=sid, text="echo AFTER")
        assert [e.text for e in rec.sends] == ["echo AFTER"]
        rec.first_prompt_sent_at, rec.first_prompt_error = None, "given up"
        await person.call("send", id=sid, text="echo GIVEN-UP")  # a brief given up on lifts the gate
        assert rec.sends[-1].text == "echo GIVEN-UP"
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


async def test_a_tool_with_a_start_context_is_untouched(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _due(agent, person, tmp_path)
        # read after the launch as a tool with a start context of its own (Claude Code, Gemini CLI)
        monkeypatch.setattr(adapters.get("agentshell"), "start_context", True, raising=False)
        assert not adapters.core_runs_start_hooks("agentshell")
        rec = agent.sessions[sid]
        await person.call("send", id=sid, text="echo SENT")
        assert [e.text for e in rec.sends] == ["echo SENT"]
        await agent.rpc_keys(sid, ["Escape"], caller="ao-lead")
        assert [e.text for e in rec.sends] == ["echo SENT", "Escape"]
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


async def test_a_wrapup_while_the_brief_is_due_stops_the_session_even_on_a_dialog(agent, hooks_ride, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _due(agent, person, tmp_path)
        rec = agent.sessions[sid]
        rec.set_state("needs-you", confidence="hook", pending=Pending(kind="permission", text="run it?"))
        await person.call("send", id=sid, text="wrap up", wrapup=True, key="k1")
        assert rec.state == "exited" and rec.ended["how"] == "kill" and rec.ended["by"] == "person"
        assert "why" not in rec.ended and rec.wrapup_at is None and rec.sends == []
        # a keyed repeat of the stopped press finds no entry and is refused *has exited*
        with pytest.raises(AgentError, match="has exited"):
            await person.call("send", id=sid, text="wrap up", wrapup=True, key="k1")
        await person.call("remove", id=sid)


async def test_keys_are_the_persons_alone_while_the_brief_is_due(agent, hooks_ride, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _due(agent, person, tmp_path)
        rec = agent.sessions[sid]
        with pytest.raises(RpcError, match=REFUSED):
            await agent.rpc_keys(sid, ["Enter"], caller="ao-lead")
        assert rec.sends == []
        await person.call("keys", id=sid, keys=["Escape"])  # the person answers a launch dialog
        assert [e.text for e in rec.sends] == ["Escape"]
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


async def test_a_policys_line_and_the_pause_line_wait_for_the_brief(agent, hooks_ride, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _due(agent, person, tmp_path, pause_prompt="echo PAUSE-NOW", resume_prompt="echo RESUME-NOW")
        rec = agent.sessions[sid]
        assert await agent._policy_send(rec, "an idle nudge") is False and rec.sends == []
        agent._usage[""] = {"windows": [{"label": "wk", "pct": 95, "resets": None}], "reason": "ok"}
        await person.call("set_settings", profile="", reserves={"wk": 10})
        typed: list[str] = []

        async def counting(sid_, adapter, text):
            typed.append(text)
            return "idle", 0

        agent._submit = counting
        await agent._enforce_usage_gate(datetime.now(UTC))
        assert rec.gated and rec.gated["sent_at"] is None and typed == [], "marked, not typed"
        rec.first_prompt_sent_at = datetime.now(UTC).isoformat()
        await agent._enforce_usage_gate(datetime.now(UTC))
        assert rec.gated["sent_at"] and typed == ["echo PAUSE-NOW"], "typed once the brief is in"
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


async def test_a_gate_that_ends_before_the_brief_sends_no_line(agent, hooks_ride, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _due(agent, person, tmp_path, pause_prompt="echo PAUSE-NOW", resume_prompt="echo RESUME-NOW")
        rec = agent.sessions[sid]
        agent._usage[""] = {"windows": [{"label": "wk", "pct": 95, "resets": None}], "reason": "ok"}
        await person.call("set_settings", profile="", reserves={"wk": 10})
        typed: list[str] = []

        async def counting(sid_, adapter, text):
            typed.append(text)
            return "idle", 0

        agent._submit = counting
        now = datetime.now(UTC)
        await agent._enforce_usage_gate(now)
        agent._usage[""]["windows"][0]["pct"] = 50
        await agent._enforce_usage_gate(now + timedelta(hours=2))
        assert rec.gated is None and typed == []
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


async def test_a_stop_time_reached_while_the_brief_is_due_stops_the_session(agent, hooks_ride, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _due(agent, person, tmp_path)
        rec = agent.sessions[sid]
        rec.wrapup_prompt = "wrap up now"
        rec.run_until = (datetime.now(UTC) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        typed: list[str] = []

        async def counting(sid_, adapter, text):
            typed.append(text)
            return "idle", 0

        agent._submit = counting
        await agent._enforce_stop_times(datetime.now(UTC))
        assert typed == [] and rec.wrapup_sent_at is None
        assert rec.state == "exited" and rec.ended["by"] == "tick" and rec.ended["why"] == "stop time"
        await person.call("remove", id=sid)
