"""A record with no agent (design §4.3 *A record with no agent*, TD-665, built by TD-666 slice 1): a
`shell` or a `command` run says `agent: False`, the view carries it, and the host agent types nothing
of its own into one, refuses mail and the wrap-up to it, keeps it interactive, kills it at its stop
time and derives no claim for it."""

from datetime import UTC, datetime

import pytest

from sessionorc import adapters, reports
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import Session
from shiftlead import teamrun

PAST = "2026-09-13T06:00:00Z"


@pytest.mark.unit
def test_the_adapter_says_whether_it_runs_an_agent():
    """`shell` and `command` set `agent` False; an adapter that leaves it unset runs one, and so does
    one this host does not know (a node's adapter installed there alone)."""
    assert adapters.has_agent("shell") is False
    assert adapters.has_agent("command") is False
    assert adapters.has_agent("agentshell") is True  # the test stub: a shell standing in for an agent
    assert adapters.has_agent("no-such-tool") is True


@pytest.mark.unit
def test_a_shell_in_a_workers_worktree_takes_no_claim_from_it(tmp_path):
    """§4.3: a shell opened in a worker's worktree shares the worker's branch, and that branch's
    claim is the worker's — the newer shell never holds the directory."""

    def rec(sid, adapter, created):
        return Session(
            id=sid, name=sid, kind="interactive", adapter=adapter, dir=str(tmp_path), state="idle", created=created
        )

    worker = rec("ao-w", "agentshell", "2026-10-13T00:00:00Z")
    shell = rec("ao-s", "shell", "2026-10-13T01:00:00Z")
    run = rec("ao-c", "command", "2026-10-13T02:00:00Z")
    assert reports.holds_directory([worker, shell, run]) == {"ao-w"}
    assert reports.holds_directory([shell]) == set()


@pytest.mark.unit
def test_team_stop_kills_a_record_with_no_agent_at_once():
    """§4.3 and §6 *Stop time*: `ao team stop` types no wrap-up into a shell — it is killed at once."""
    calls = []

    def call(method, **kw):
        calls.append((method, kw))
        return None

    out = teamrun._stop_one(call, {"id": "ao-s", "name": "s", "agent": False, "state": "idle"}, "member", now=False)
    assert calls == [("kill", {"id": "ao-s"})] and out["action"] == "killed"
    calls.clear()
    out = teamrun._stop_one(call, {"id": "ao-w", "name": "w", "agent": True, "state": "idle"}, "member", now=False)
    assert calls[0][0] == "send" and calls[0][1]["wrapup"] is True and out["action"] == "wrap-up sent"


@pytest.mark.integration
async def test_the_view_carries_agent_and_the_host_types_nothing_into_a_shell(agent, tmp_path):
    """The view's `agent` is derived from the adapter; on a shell the wrap-up is refused in §4.3's
    words, `set_mode` to unattended is refused, mail to it is refused from the person and from a
    session, and neither the doorbell nor a policy's line is typed into it."""
    for d in "abc":
        (tmp_path / d).mkdir()
    async with LocalClient() as person:
        shell = await person.call(
            "create", name="sh", dir=str(tmp_path / "a"), adapter="shell", argv=["bash", "--norc"]
        )
        run = await person.call(
            "create", name="cmd", dir=str(tmp_path / "b"), adapter="command", kind="command", argv=["sleep", "30"]
        )
        lead = await person.call(
            "create", name="lead", dir=str(tmp_path / "c"), adapter="agentshell", argv=["bash", "--norc"]
        )
        views = {v["id"]: v for v in await person.call("list")}
        assert views[shell["id"]]["agent"] is False and views[run["id"]]["agent"] is False
        assert views[lead["id"]]["agent"] is True
        assert (await person.call("get", id=shell["id"]))["agent"] is False

        with pytest.raises(AgentError, match="a shell runs no turns: there is nothing to wrap up — Close it"):
            await person.call("send", id=shell["id"], text="wrap up", wrapup=True)
        assert agent.sessions[shell["id"]].wrapup_at is None
        await person.call("send", id=shell["id"], text="true")  # what a person types still goes in

        with pytest.raises(AgentError, match="runs no agent"):
            await person.call("set_mode", id=shell["id"], unattended=True)
        assert agent.sessions[shell["id"]].unattended is False

        await person.call("set_controllers", id=shell["id"], add=[lead["id"]])
        with pytest.raises(AgentError, match="nothing reads sh's inbox — it runs no agent"):
            await person.call("msg", to=[shell["id"]], text="hello")
        with pytest.raises(AgentError, match="nothing reads sh's inbox — it runs no agent"):
            await person.call("msg", to=[shell["id"]], text="hello", caller=lead["id"])
        with pytest.raises(AgentError, match="nothing reads cmd's inbox"):
            await person.call("msg", to=[run["id"]], text="hello")
        assert not agent.sessions[shell["id"]].inbox

        rec = agent.sessions[shell["id"]]
        rec.set_state("idle", confidence="hook")
        assert agent._bell_blocked(rec, datetime.now(UTC)) == "no agent"
        assert await agent._policy_send(rec, "an idle nudge") is False


@pytest.mark.integration
async def test_a_shells_stop_time_kills_it_with_nothing_typed(agent, tmp_path):
    """§6 *Stop time*: a record with no agent is killed at once — no wrap-up, no grace — and the usage
    gate never marks one."""
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create", name="sh", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc", "--noprofile"],
                unattended=True, run_until=PAST, wrapup_prompt="wrap up and exit",
            )
        )["id"]  # fmt: skip
        rec = agent.sessions[sid]
        rec.set_state("working", confidence="scraped")
        await agent._enforce_stop_times(datetime.now(UTC))
        assert rec.state == "exited" and rec.wrapup_sent_at is None
        await person.call("remove", id=sid)
