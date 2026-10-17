"""The title's verdict in the tick (design §4.2 *A title the tool writes its state into*, §4.3 *Two gaps*,
TD-785 slice 3): read once a hook has reached the record and past one tick since the last hook, compared
with the hook-confirmed state, `✋`'s text written by the state it replaces, equal states no event (the
stall check still runs), never held for its screen; `ao explain` shows the title as its evidence."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta

import pytest
from conftest import wait_for

from sessionorc import adapters, agent_tick
from sessionorc.client import LocalClient
from sessionorc.models import Pending, Session, now_iso
from sessionorc.tmux import PaneInfo
from shiftlead import cli
from shiftlead.adapters.gemini import GeminiAdapter

pytestmark = pytest.mark.integration

PAD = " " * 40
READY, WORKING, QUIET, ACTION = (
    f"{g}  {w} (t1){PAD}" for g, w in (("◇", "Ready"), ("✦", "Working…"), ("⏲", "Working…"), ("✋", "Action Required"))
)


@pytest.fixture
def gem(monkeypatch):
    adapters.load_all()
    ad = GeminiAdapter(binary="gemini")
    monkeypatch.setitem(adapters._REGISTRY, ad.name, ad)
    return ad


def _rec(tmp_path, state="working", confidence="hook", hooked=True, pending=None) -> Session:
    s = Session(id="ao-x-g", name="g", kind="agent", dir=str(tmp_path), adapter="gemini", state=state)
    s.confidence = confidence
    s.pending = pending
    s.hook_seen_at = now_iso() if hooked else None
    return s


def _look(agent, s: Session, title: str, hook_age: float | None = 60.0) -> Session:
    now = datetime.now(UTC)
    if hook_age is None:
        agent._last_hook.pop(s.id, None)
    else:
        agent._last_hook[s.id] = now - timedelta(seconds=hook_age)
    agent._observe(s, PaneInfo(s.id, 0, "node", 1, dead=False, dead_status=None, title=title), [], now)
    return s


def test_the_adapter_explains_its_title_and_not_its_screen():
    ad = GeminiAdapter(binary="gemini")
    m = ad.explain(["◇  Ready"], title=ACTION)
    assert m.state == "needs-you" and m.pending.kind == "question" and m.pending.text == ""
    assert m.rule == "title ✋" and m.evidence == [ACTION.strip()]
    assert ad.explain([], title=QUIET).state == "working" and ad.explain([], title=READY).pending is None
    assert ad.explain(["✦  Working…"], title="kmaster: ~/src") is None and ad.explain([]) is None


async def test_the_title_replaces_a_hook_state_older_than_a_tick(agent, gem, tmp_path):
    s = _rec(tmp_path, hooked=False)
    assert _look(agent, s, READY).state == "working"  # no hook has reached it: the title is its screen
    s.hook_seen_at = now_iso()
    assert _look(agent, s, READY, hook_age=0.0).state == "working"  # a hook within the tick wins
    agent._hook_state[s.id] = ("idle", None, "hook")  # what a screen verdict kept: the title drops it
    assert _look(agent, s, READY).state == "idle"  # a cancelled or failed turn ends
    assert s.confidence == "title" and s.pending is None and s.id not in agent._hook_state
    assert s.told  # the tool's own word: every hook-confirmed rule takes it
    assert _look(agent, s, WORKING).state == "working" and s.confidence == "title"  # a slash command's call
    assert _look(agent, s, READY, hook_age=None).state == "idle"  # no hook since a restart: none to outrank


async def test_action_required_is_written_by_the_state_it_replaces(agent, gem, tmp_path):
    s = _look(agent, _rec(tmp_path, state="working"), ACTION)
    assert s.state == "needs-you" and s.pending.kind == "question" and s.pending.text == agent_tick.TITLE_SHELL_WAITS
    s = _look(agent, _rec(tmp_path, state="idle"), ACTION)
    assert s.pending.text == agent_tick.TITLE_CONFIRMATION
    # under a Notification's permission the `✋` is that confirmation: its pending stands
    perm = Pending(kind="permission", text="Allow execution: rm -rf build")
    s = _look(agent, _rec(tmp_path, state="needs-you", pending=perm), ACTION)
    assert s.pending == perm and s.confidence == "hook"
    # answered in the terminal, no hook says so until AfterTool: the title's `✦` ends it
    s = _look(agent, s, WORKING)
    assert s.state == "working" and s.pending is None and s.confidence == "title"
    # a title's own `working` is hook-confirmed: `✋` over it is the shell waiting
    s = _look(agent, s, ACTION)
    assert s.state == "needs-you" and s.pending.text == agent_tick.TITLE_SHELL_WAITS


async def test_explains_reason_is_the_ticks_own_rule(agent, gem, tmp_path):
    ad = GeminiAdapter(binary="gemini")
    now = datetime.now(UTC)
    agent._last_hook["ao-x-g"] = now - timedelta(seconds=60)

    def why(s, title):
        return agent._title_reading(s, ad.explain([], title=title), now)

    assert why(_rec(tmp_path), "kmaster: ~") == (None, "the title says no state")
    assert "not read yet" in why(_rec(tmp_path, hooked=False), READY)[1]
    assert "stands" in why(_rec(tmp_path, state="exited"), READY)[1]
    assert "no event" in why(_rec(tmp_path), WORKING)[1]
    assert "does not end a stall" in why(_rec(tmp_path, state="stalled?", confidence="tick"), WORKING)[1]
    assert "not compared" in why(_rec(tmp_path, state="idle", confidence="scraped"), WORKING)[1]
    m, reason = why(_rec(tmp_path), READY)
    assert m.state == "idle" and "confidence: title" in reason
    agent._last_hook["ao-x-g"] = now
    assert "within a tick" in why(_rec(tmp_path), READY)[1]


async def test_the_ticks_own_readings_stand_but_a_stall_ends_when_the_tool_moves_on(agent, gem, tmp_path):
    for st in ("exited", "closed"):
        for conf in ("tick", "hook"):  # the tool's own SessionEnd is a hook's `exited`: it stands too
            s = _look(agent, _rec(tmp_path, state=st, confidence=conf), READY)
            assert s.state == st and s.confidence == conf
    s = _rec(tmp_path, state="stalled?", confidence="tick")
    assert _look(agent, s, WORKING).state == "stalled?"  # still working: no event
    assert _look(agent, s, QUIET).state == "stalled?"
    assert _look(agent, s, READY).state == "idle" and s.confidence == "title"
    s = _look(agent, _rec(tmp_path, state="stalled?", confidence="tick"), ACTION)
    assert s.state == "needs-you" and s.pending.text == agent_tick.TITLE_SHELL_WAITS
    # a scraped state is no hook's word: the title is not compared with it
    assert _look(agent, _rec(tmp_path, state="idle", confidence="scraped"), WORKING).state == "idle"


async def test_an_equal_verdict_falls_through_to_the_stall_check(agent, gem, tmp_path):
    s = _rec(tmp_path, state="working")
    log = tmp_path / "run.log"
    log.write_text("x")
    old = time.time() - 3600
    os.utime(log, (old, old))
    s.run_log = str(log)
    assert _look(agent, s, WORKING).state == "stalled?" and s.confidence == "tick"


async def test_a_title_set_in_the_pane_reaches_the_record_and_explain(agent, hookstub, tmp_path, monkeypatch):
    """The whole path: a pane's own title (OSC 2) through the tick's pane list to the record, and `ao
    explain` showing the title as the verdict's evidence."""
    ad = GeminiAdapter(binary="gemini")
    monkeypatch.setattr(type(hookstub), "state_in_title", True, raising=False)
    monkeypatch.setattr(type(hookstub), "explain", lambda self, tail, title="": ad.explain(tail, title=title))
    async with LocalClient() as c:
        s = await c.call("create", name="ttl", dir=str(tmp_path), adapter="hookstub")
        await c.call("hook", session=s["id"], state="idle")
        agent.tmux.send_prompt(s["id"], r"printf '\033]2;✋  Action Required (ttl)\033\\'")

        async def reads(state, confidence):
            x = await c.call("get", id=s["id"])
            return x["state"] == state and x["confidence"] == confidence

        assert await wait_for(lambda: reads("needs-you", "title"))
        x = await c.call("get", id=s["id"])
        assert x["pending"] == {
            "kind": "question",
            "text": agent_tick.TITLE_CONFIRMATION,
            "deadline": None,
            "tool_use_id": None,
        }
        ex = await c.call("explain", id=s["id"])
        assert ex["title"].startswith("✋  Action Required") and ex["match"]["rule"] == "title ✋"
        assert "no event" in ex["reason"]  # the record already reads what the title says
        await c.call("kill", id=s["id"])


def test_explain_file_takes_a_title(gem, tmp_path, capsys):
    screen = tmp_path / "pane.txt"
    screen.write_text(" > Type your message or @path/to/file\n")
    assert cli.main(["--json", "explain", "--file", str(screen), "-a", "gemini", "--title", ACTION]) == 0
    x = json.loads(capsys.readouterr().out)
    assert x["title"] == ACTION and x["match"]["state"] == "needs-you" and x["match"]["rule"] == "title ✋"
    assert cli.main(["explain", "--file", str(screen), "-a", "gemini"]) == 0
    out = capsys.readouterr().out
    assert "title: \n" in out and "no screen rule matched" in out
