"""Open prompts are a stack; the main thread's state is kept beneath it (design §4.2, TD-950 slice 3b): every
hook-road `needs-you` entry in the record's `pendings`, `kept` set at the first push and restored once the last
ends, each end removing its own entry wherever it sits, the tool's `permission_prompt` notice weighed against
what is open, the screen and title roads silent while the stack is open, and the startup sweep."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_claude_adapter import _captured, _feed

from sessionorc import adapters, agent_common
from sessionorc.client import LocalClient
from sessionorc.models import Pending, Session
from sessionorc.tmux import PaneInfo

pytestmark = pytest.mark.integration

SCREENS = Path(__file__).parent / "fixtures" / "screens"
NOTICE = {
    "state": "needs-you",
    "pending": {"kind": "question", "text": "Claude needs your permission"},
    "notice": "permission_prompt",
}
STOP = {"state": "idle", "pending": None}


def pre(tid: str, sig: str, sub: str | None = None) -> dict:
    """A call's `PreToolUse`, on the main thread (with its state) or a subagent's (with none)."""
    ev = {"call": "start", "tool_use_id": tid, "call_sig": sig}
    return {**ev, "subagent": sub, "subagent_seen": True} if sub else {**ev, "state": "working", "pending": None}


def post(tid: str, sub: str | None = None) -> dict:
    ev = {"call": "end", "tool_use_id": tid}
    return {**ev, "subagent": sub, "subagent_seen": True} if sub else {**ev, "state": "working", "pending": None}


def perm(sig: str, sub: str | None = None, text: str = "Bash: x") -> dict:
    ev = {"kind": "permission", "text": text, "call_sig": sig, "tool": "Bash", "input": {}}
    return {**ev, "subagent": sub, "subagent_name": "general-purpose"} if sub else ev


def question(text: str, sub: str | None = None) -> dict:
    ev = {"state": "needs-you", "pending": {"kind": "question", "text": text}}
    return {**ev, "subagent": sub} if sub else ev


async def _ask(agent, c, sid, sig, sub=None, wait=10, text="Bash: x"):
    """A thread's call and its permission, the waiter live: its task and its call's id."""
    tid = f"tu-{sig}"
    task = await _feed(agent, c, sid, [pre(tid, sig, sub), perm(sig, sub, text)], wait=wait)
    return task, tid


async def _rec(c, sid) -> dict:
    return await c.call("get", id=sid)


def _ago(agent, sid, seconds):
    """The session's last sure end moved `seconds` into the past."""
    agent._sure_end[sid] = time.monotonic() - seconds


# -- the captures ----------------------------------------------------------------------------------


async def test_the_background_capture_holds_then_falls_through_keeping_its_asker(agent, hookstub, tmp_path):
    """Design §4.2, the `background/` capture: through the hook's wait the record reads `needs-you` with the
    held line's fields and one entry, the dialog's notice dropped; at the timeout the entry turns into the
    question in place, keeping `subagent` and `subagent_name`; the notice after it keeps the text."""
    events = _captured("background")
    i = next(n for n, e in enumerate(events) if e.get("kind") == "permission")
    asked = events[i]
    async with LocalClient() as c:
        sid = (await c.call("create", name="b", dir=str(tmp_path), adapter=hookstub.name))["id"]
        task = await _feed(agent, c, sid, events[: i + 1], wait=1)
        rest = events[i + 1 :]
        assert [e["raw"]["hook_event_name"] for e in rest] == ["PreToolUse", "Notification"]
        await _feed(agent, c, sid, rest)
        rec = await _rec(c, sid)
        assert rec["state"] == "needs-you" and len(rec["pendings"]) == 1 and rec["pending"]["pane_held"] is True
        assert rec["kept"]["state"] == "idle"  # the main thread's Stop came before the request
        assert await task is None
        rec = await _rec(c, sid)
        p = rec["pending"]
        assert p["kind"] == "question" and p["text"] == asked["text"] and p["subagent"] == asked["subagent"]
        assert p["subagent_name"] == "general-purpose" and p["pane_held"] is False
        await _feed(agent, c, sid, [rest[-1]])  # the notice, six seconds after the drawn dialog
        rec = await _rec(c, sid)
        assert len(rec["pendings"]) == 1 and rec["pending"]["text"] == asked["text"]


async def test_the_answered_capture_ends_the_question_at_the_subagents_own_end(agent, hookstub, tmp_path):
    """The `answered/` capture after the same fall-through: the subagent's `PostToolUse` ends the question,
    and the record goes back to `kept` — the `Stop`'s `idle`, `hook`, with the `Stop`'s own `since`."""
    events = _captured("answered")
    i = next(n for n, e in enumerate(events) if e.get("kind") == "permission")
    async with LocalClient() as c:
        sid = (await c.call("create", name="a", dir=str(tmp_path), adapter=hookstub.name))["id"]
        task = await _feed(agent, c, sid, events[: i - 1])  # through the main thread's Stop
        stop = await _rec(c, sid)
        assert stop["state"] == "idle"
        stopped = stop["since"]
        # the fall-through's second (wait=1) puts the restore in a later second than the Stop, so a restore
        # that wrote a fresh `since` fails below every run, not only when the two straddle one (TD-958)
        task = await _feed(agent, c, sid, events[i - 1 : i + 1], wait=1)
        assert await task is None
        rest = events[i + 1 :]
        assert [e["raw"]["hook_event_name"] for e in rest][:4] == [
            "PreToolUse",
            "Notification",
            "PostToolUse",
            "SubagentStop",
        ]
        assert rest[3]["subagent"] == events[i]["subagent"]
        await _feed(agent, c, sid, rest[:3])
        rec = await _rec(c, sid)
        assert (rec["state"], rec["confidence"], rec["since"]) == ("idle", "hook", stopped)
        assert rec["pendings"] == [] and rec["kept"] is None


async def test_the_foreground_capture_keeps_the_main_threads_stop_beneath(agent, hookstub, tmp_path):
    """The `foreground/` capture: the main thread's `Stop` a second after the request leaves the record
    `needs-you` with its buttons, and goes into `kept`; the subagent's **Allow** restores that `idle`
    (`hook`, its own `since`), not `working`. Again, ended by the asked call's own event instead."""
    events = _captured("foreground")
    i = next(n for n, e in enumerate(events) if e.get("kind") == "permission")
    asked = events[i]
    tid = next(e for e in events[:i] if e.get("call") == "start" and e.get("subagent") == asked["subagent"])[
        "tool_use_id"
    ]
    async with LocalClient() as c:
        sid = (await c.call("create", name="f", dir=str(tmp_path), adapter=hookstub.name))["id"]
        task = await _feed(agent, c, sid, events)
        rec = await _rec(c, sid)
        assert rec["state"] == "needs-you" and rec["pending"]["kind"] == "permission"
        assert rec["kept"]["state"] == "idle"
        kept_since = rec["kept"]["since"]
        await c.call("decide", id=sid, tool_use_id=tid, behavior="allow")
        await task
        rec = await _rec(c, sid)
        assert (rec["state"], rec["confidence"], rec["since"]) == ("idle", "hook", kept_since)
        # again, the asked call's own event in place of the Allow
        task, tid = await _ask(agent, c, sid, "again", asked["subagent"])
        await _feed(agent, c, sid, [post("tu-other", asked["subagent"])])
        assert not task.done()
        await _feed(agent, c, sid, [post(tid, asked["subagent"])])
        assert await task is None
        rec = await _rec(c, sid)
        assert (rec["state"], rec["confidence"]) == ("idle", "hook") and rec["pendings"] == []


# -- the stack ---------------------------------------------------------------------------------------


async def test_two_subagents_ask_at_once(agent, hookstub, tmp_path):
    """Both are in `pendings`, each **Allow** ends its own, and `kept` comes back only after the second."""
    async with LocalClient() as c:
        sid = (await c.call("create", name="t", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await _feed(agent, c, sid, [STOP])
        t1, id1 = await _ask(agent, c, sid, "one", "s1")
        t2, id2 = await _ask(agent, c, sid, "two", "s2")
        rec = await _rec(c, sid)
        assert [p["tool_use_id"] for p in rec["pendings"]] == [id1, id2] and rec["pending"]["tool_use_id"] == id2
        await c.call("decide", id=sid, tool_use_id=id2, behavior="allow")
        await t2
        rec = await _rec(c, sid)
        assert rec["state"] == "needs-you" and rec["pending"]["tool_use_id"] == id1
        await c.call("decide", id=sid, tool_use_id=id1, behavior="deny", reason="no")
        await t1
        rec = await _rec(c, sid)
        assert rec["state"] == "idle" and rec["pendings"] == [] and rec["kept"] is None


async def test_a_main_thread_question_goes_on_top_and_the_held_prompt_comes_back(agent, hookstub, tmp_path):
    """A main-thread `AskUserQuestion` over a subagent's prompt is drawn; a second replaces it; once the main
    thread moves on, the subagent's prompt is drawn again."""
    async with LocalClient() as c:
        sid = (await c.call("create", name="q", dir=str(tmp_path), adapter=hookstub.name))["id"]
        task, tid = await _ask(agent, c, sid, "one", "s1")
        await _feed(agent, c, sid, [question("Which?")])
        assert (await _rec(c, sid))["pending"]["text"] == "Which?"
        await _feed(agent, c, sid, [question("Which, then?")])
        rec = await _rec(c, sid)
        assert [p["text"] for p in rec["pendings"]] == ["Bash: x", "Which, then?"]
        await _feed(agent, c, sid, [STOP])
        rec = await _rec(c, sid)
        assert rec["pending"]["tool_use_id"] == tid and rec["pending"]["pane_held"] is True
        assert rec["kept"]["state"] == "idle" and not task.done()
        await c.call("decide", id=sid, tool_use_id=tid, behavior="allow")
        await task


async def test_the_older_prompt_falls_through_under_the_newer(agent, hookstub, tmp_path):
    """The older of two prompts falls through in place: its entry becomes the question, the newer on top.
    After it, the subagent's call for another tool (a pane **Deny**) ends the question."""
    async with LocalClient() as c:
        sid = (await c.call("create", name="o", dir=str(tmp_path), adapter=hookstub.name))["id"]
        t1, id1 = await _ask(agent, c, sid, "one", "s1", wait=1)
        t2, id2 = await _ask(agent, c, sid, "two", "s2")
        assert await t1 is None
        rec = await _rec(c, sid)
        assert [p["kind"] for p in rec["pendings"]] == ["question", "permission"]
        assert rec["pending"]["tool_use_id"] == id2
        await _feed(agent, c, sid, [pre("tu-next", "next", "s1")])
        rec = await _rec(c, sid)
        assert [p["tool_use_id"] for p in rec["pendings"]] == [id2]
        await c.call("decide", id=sid, tool_use_id=id2, behavior="allow")
        await t2


async def test_the_records_end_drops_the_stack(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="e", dir=str(tmp_path), adapter=hookstub.name))["id"]
        task, _ = await _ask(agent, c, sid, "one", "s1")
        await _feed(agent, c, sid, [{"state": "exited", "pending": None}])
        assert await task is None
        rec = await _rec(c, sid)
        assert rec["state"] == "exited" and rec["pendings"] == [] and rec["kept"] is None


async def test_a_main_thread_waiter_keyed_by_its_call_beside_a_subagents(agent, hookstub, tmp_path):
    """A parallel call's `PostToolUse` (open before the permission) ends nothing; another call's `PreToolUse`
    ends it as answered in the terminal, and the subagent's entry and buttons stay. A main-thread Allow with
    a subagent's entry left writes `working` into `kept`, and the record reads the subagent's entry."""
    async with LocalClient() as c:
        sid = (await c.call("create", name="k", dir=str(tmp_path), adapter=hookstub.name))["id"]
        sub, sub_id = await _ask(agent, c, sid, "sub", "s1")
        await _feed(agent, c, sid, [pre("tu-par", "par")])
        main, main_id = await _ask(agent, c, sid, "main")
        await _feed(agent, c, sid, [post("tu-par")])
        assert not main.done() and (await _rec(c, sid))["pending"]["tool_use_id"] == main_id
        await _feed(agent, c, sid, [pre("tu-next", "next")])
        assert await main is None
        rec = await _rec(c, sid)
        assert rec["pending"]["tool_use_id"] == sub_id and rec["pending"]["kind"] == "permission"
        # the main thread asks again, and its Allow leaves the subagent's on top
        main, main_id = await _ask(agent, c, sid, "main2")
        await c.call("decide", id=sid, tool_use_id=main_id, behavior="allow")
        await main
        rec = await _rec(c, sid)
        assert rec["pending"]["tool_use_id"] == sub_id and rec["kept"]["state"] == "working"
        await c.call("decide", id=sid, tool_use_id=sub_id, behavior="allow")
        await sub
        assert (await _rec(c, sid))["state"] == "working"


async def test_a_main_thread_question_ends_its_threads_call_keyed_waiter(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="m", dir=str(tmp_path), adapter=hookstub.name))["id"]
        task, _ = await _ask(agent, c, sid, "main")
        await _feed(agent, c, sid, [question("Which?")])
        assert await task is None
        rec = await _rec(c, sid)
        assert [p["text"] for p in rec["pendings"]] == ["Which?"] and rec["pending"]["kind"] == "question"


async def test_a_dialog_answer_then_the_stop_leaves_the_threads_own_idle(agent, hookstub, tmp_path):
    """A main-thread permission answered in the dialog, then the turn's `Stop`: `idle`, not `kept`'s
    earlier `working`. With nothing open, a `Stop` sets `idle` and `kept` stays None."""
    async with LocalClient() as c:
        sid = (await c.call("create", name="d", dir=str(tmp_path), adapter=hookstub.name))["id"]
        await _feed(agent, c, sid, [{"state": "working", "pending": None, "prompt": True}])
        task, tid = await _ask(agent, c, sid, "main")
        assert (await _rec(c, sid))["kept"]["state"] == "working"
        await _feed(agent, c, sid, [post(tid)])
        assert await task is None
        await _feed(agent, c, sid, [STOP])
        rec = await _rec(c, sid)
        assert (rec["state"], rec["confidence"], rec["kept"]) == ("idle", "hook", None)


async def test_a_kept_stall_comes_back_with_tick_confidence(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="s", dir=str(tmp_path), adapter=hookstub.name))["id"]
        agent.sessions[sid].set_state("stalled?", confidence="tick")
        task, tid = await _ask(agent, c, sid, "one", "s1")
        await c.call("decide", id=sid, tool_use_id=tid, behavior="allow")
        await task
        rec = await _rec(c, sid)
        assert (rec["state"], rec["confidence"]) == ("stalled?", "tick")


# -- the notice --------------------------------------------------------------------------------------


async def test_the_notice_is_weighed_against_the_last_sure_end(agent, hookstub, tmp_path):
    """Dropped within `NOTICE_LAG` of a sure end — an Allow, a Deny, the asked call's own event, a `Stop`
    ending a main-thread waiter, a fall-through question's `SubagentStop` — and pushed past it; with
    nothing open and no recent end, pushed as a question. An unsure end (another call's start) clears it."""
    async with LocalClient() as c:
        sid = (await c.call("create", name="n", dir=str(tmp_path), adapter=hookstub.name))["id"]

        async def notice_after(seconds):
            _ago(agent, sid, seconds)
            await _feed(agent, c, sid, [NOTICE])
            rec = await _rec(c, sid)
            pushed = rec["state"] == "needs-you"
            if pushed:
                await _feed(agent, c, sid, [STOP])  # the main thread moves on: the question goes
            return pushed

        for end in ("allow", "deny", "own"):
            task, tid = await _ask(agent, c, sid, f"x{end}")
            if end == "own":
                await _feed(agent, c, sid, [post(tid)])
            else:
                await c.call("decide", id=sid, tool_use_id=tid, behavior=end)
            await task
            await _feed(agent, c, sid, [STOP])
            assert not await notice_after(6), end
            assert await notice_after(11), end
        task, _ = await _ask(agent, c, sid, "stop")
        await _feed(agent, c, sid, [STOP])
        await task
        assert not await notice_after(6)
        task, _ = await _ask(agent, c, sid, "fall", "s1", wait=1)
        await task
        await _feed(agent, c, sid, [{"subagent": "s1", "subagent_delta": -1, "subagent_seen": True}])
        assert (await _rec(c, sid))["state"] == "idle"
        assert not await notice_after(6)
        # another call's start ends a main-thread waiter unsurely: the notice that follows is pushed
        task, _ = await _ask(agent, c, sid, "unsure")
        await _feed(agent, c, sid, [pre("tu-next", "next")])
        await task
        assert sid not in agent._sure_end
        await _feed(agent, c, sid, [NOTICE])
        assert (await _rec(c, sid))["pending"]["text"] == "Claude needs your permission"


async def test_the_notice_pushes_nothing_over_an_open_permission(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="p", dir=str(tmp_path), adapter=hookstub.name))["id"]
        task, tid = await _ask(agent, c, sid, "one", "s1")
        await _feed(agent, c, sid, [NOTICE])
        rec = await _rec(c, sid)
        assert len(rec["pendings"]) == 1 and rec["pending"]["tool_use_id"] == tid
        await c.call("decide", id=sid, tool_use_id=tid, behavior="allow")
        await task


# -- the screen road and the restart --------------------------------------------------------------------


def _tick(agent, s: Session, tail: list[str], hook_age: float) -> None:
    now = datetime.now(UTC)
    agent._last_hook[s.id] = now - timedelta(seconds=hook_age)
    agent._observe(s, PaneInfo(s.id, 0, "node", 1, dead=False, dead_status=None, title=""), tail, now)


async def test_a_screen_verdict_beneath_the_stack_is_kept_and_rechecked(agent, tmp_path):
    """A first push over a screen rule's `needs-you` keeps it and pops `_hook_state`; while the stack is open
    a matching screen writes nothing; the emptied stack restores it `scraped`, and the next tick keeps it
    while its rule matches the tail and sets `idle` (`tick`) once it does not — a fresh hook or not."""
    adapters.load_all()
    stale = agent_common.STALL_AFTER.total_seconds() + 60
    trust = (SCREENS / "trust-dialog.txt").read_text().splitlines()
    s = Session(id="ao-x-c", name="c", kind="agent", dir=str(tmp_path), adapter="claude-code", state="working")
    s.confidence = "hook"
    agent.sessions[s.id] = s
    _tick(agent, s, trust, stale)
    assert (s.state, s.confidence) == ("needs-you", "scraped") and s.id in agent._hook_state
    verdict = s.pending
    agent._push_prompt(s, Pending("permission", "Bash: x", tool_use_id="tu-1", subagent="s1"))
    assert s.kept["confidence"] == "scraped" and s.id not in agent._hook_state
    _tick(agent, s, trust, stale)
    assert s.pending.tool_use_id == "tu-1"
    agent._end_entries(s, lambda p: p.tool_use_id == "tu-1", sure=True)
    assert (s.state, s.confidence, s.pending) == ("needs-you", "scraped", verdict)
    _tick(agent, s, trust, 0)  # the rule still matches: kept
    assert (s.state, s.confidence) == ("needs-you", "scraped")
    agent._push_prompt(s, Pending("permission", "Bash: y", tool_use_id="tu-2"))
    agent._end_entries(s, lambda p: p.tool_use_id == "tu-2", sure=True)
    _tick(agent, s, ["$ "], 0)  # gone from the pane, though a hook is fresh
    assert (s.state, s.confidence) == ("idle", "tick")


def test_the_startup_sweep_moves_a_saved_hook_pending_into_the_stack(agent, tmp_path):
    """A record saved with a `hook` pending and no `pendings` reads one question entry over `kept` `idle`
    (`tick`) with its own `since`; a permission with no waiter takes the question form; a screen road's
    pending is left as it was."""
    s = Session(id="ao-x-a", name="a", kind="agent", dir=str(tmp_path), adapter="claude-code", state="working")
    s.set_state("needs-you", confidence="hook", pending=Pending("permission", "Bash: x", tool_use_id="tu-1"))
    since = s.since
    assert agent._sweep_prompts(s)
    assert [(p.kind, p.tool_use_id) for p in s.pendings] == [("question", "tu-1")]
    assert s.kept == {"state": "idle", "pending": None, "confidence": "tick", "since": since}
    assert s.pending.kind == "question" and s.state == "needs-you"
    held = Session(id="ao-x-b", name="b", kind="agent", dir=str(tmp_path), adapter="claude-code", state="working")
    p = Pending("permission", "Bash: y", tool_use_id="tu-2", subagent="s1", subagent_name="g", pane_held=True)
    held.pendings, held.kept = [p], {"state": "idle", "pending": None, "confidence": "hook", "since": since}
    held.set_state("needs-you", confidence="hook", pending=p)
    assert agent._sweep_prompts(held)
    assert held.pending.kind == "question" and held.pending.subagent == "s1" and held.pending.pane_held is False
    scraped = Session(id="ao-x-c", name="c", kind="agent", dir=str(tmp_path), adapter="claude-code", state="working")
    scraped.set_state("needs-you", confidence="scraped", pending=Pending("question", "trust?"))
    assert not agent._sweep_prompts(scraped) and scraped.pendings == []
