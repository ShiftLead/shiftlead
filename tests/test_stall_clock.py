"""The liveness cross-check reads *nothing new on the screen* (design §4.2 *Liveness cross-check*, §4.3 *An
adapter names its volatile rows*, TD-1475): the later of the masked screen's last change and the last
work-naming hook event, held while a tool call is open (up to `OPEN_TOOL_CEILING`) or a subagent is live,
checked on every record the tick leaves `working`; `stalled_ticks` counts the ticks it reads `stalled?`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sessionorc import adapters
from sessionorc.agent_common import OPEN_TOOL_CEILING
from sessionorc.models import Session, now_iso
from sessionorc.tmux import PaneInfo

pytestmark = pytest.mark.integration

FIX = Path(__file__).parent / "conformance" / "fixtures"
GEM = (FIX / "gemini" / "panes" / "working-empty.txt").read_text(encoding="utf-8").splitlines()[-15:]
CC = (FIX / "claude-code" / "panes" / "grinder-working.txt").read_text(encoding="utf-8").splitlines()[-15:]
WORKING = "✦  Working… (t1)" + " " * 40


@pytest.fixture(autouse=True)
def _adapters():
    adapters.load_all()


def _gem_repaint(n: int) -> list[str]:
    """The Gemini pane with only its spinner glyph, its *still on it…* timer and its footer moved."""
    glyph = "⠋⠙⠹⠸⠼⠴⠦⠧"[n % 8]
    return [r.replace("⠴", glyph).replace("1m 44s", f"{n}m 0s").replace("/model", f"/m{n}") for r in GEM]


def _cc_repaint(n: int) -> list[str]:
    return [r.replace("4m 50s", f"{n}m 1s").replace("19.3k", f"{n}.0k").replace("1 shell", f"{n} shells") for r in CC]


def _rec(agent, tmp_path, adapter: str, sid: str = "ao-x-s") -> Session:
    s = Session(id=sid, name="s", kind="agent", dir=str(tmp_path), adapter=adapter, state="working")
    s.confidence = "hook"
    s.hook_seen_at = now_iso()
    agent.sessions[s.id] = s
    return s


def _tick(agent, s: Session, tail: list[str], at: datetime, title: str = "") -> Session:
    """One tick at `at`, with no fresh hook (a hook within a tick outranks the screen and the title)."""
    agent._last_hook.pop(s.id, None)
    agent._observe(s, PaneInfo(s.id, 0, "node", 1, dead=False, dead_status=None, title=title), tail, at)
    return s


def _hook(agent, s: Session, **event) -> None:
    agent._apply_event(s.id, {"state": "working", "pending": None, **event})


async def test_a_gemini_pane_moving_only_its_spinner_and_timer_reads_stalled(agent, tmp_path):
    t0 = datetime.now(UTC)
    s = _rec(agent, tmp_path, "gemini")
    _tick(agent, s, _gem_repaint(0), t0, WORKING)
    for k, m in enumerate((5, 10, 15, 19), start=1):
        assert _tick(agent, s, _gem_repaint(k), t0 + timedelta(minutes=m), WORKING).state == "working"
    s = _tick(agent, s, _gem_repaint(9), t0 + timedelta(minutes=21), WORKING)
    assert (s.state, s.confidence, s.stalled_ticks) == ("stalled?", "tick", 1)
    # the title's `✦ Working…` does not end it; the count goes on
    assert _tick(agent, s, _gem_repaint(10), t0 + timedelta(minutes=22), WORKING).stalled_ticks == 2
    assert s.state == "stalled?"
    # a transcript row changes: something new, `working` again, the count back to 0
    moved = [*_gem_repaint(11)[:-6], "✦ a new line of the answer", *_gem_repaint(11)[-5:]]
    s = _tick(agent, s, moved, t0 + timedelta(minutes=23), WORKING)
    assert (s.state, s.stalled_ticks) == ("working", 0)


async def test_changing_transcript_rows_keep_it_working(agent, tmp_path):
    t0 = datetime.now(UTC)
    s = _rec(agent, tmp_path, "gemini")
    for m in range(0, 45, 5):
        tail = [*GEM[:-6], f"✦ answer line {m}", *GEM[-5:]]
        assert _tick(agent, s, tail, t0 + timedelta(minutes=m), WORKING).state == "working"


async def test_a_work_naming_hook_event_keeps_it_working_and_a_notification_does_not(agent, tmp_path):
    t0 = datetime.now(UTC)
    s = _rec(agent, tmp_path, "gemini")
    _tick(agent, s, GEM, t0 - timedelta(minutes=15))
    _hook(agent, s, event="AfterTool:read_file")  # a tool use, now: within the window at +6
    assert _tick(agent, s, GEM, t0 + timedelta(minutes=6), WORKING).state == "working"
    s.work_at = None
    agent._apply_event(s.id, {"state": "needs-you", "pending": {"kind": "question", "text": "?"}})
    assert s.work_at is None  # a notification names no work
    s.set_state("working", confidence="hook")
    assert _tick(agent, s, GEM, t0 + timedelta(minutes=6), WORKING).state == "stalled?"


async def test_a_silent_bash_call_and_a_live_subagent_keep_claude_code_working(agent, tmp_path):
    t0 = datetime.now(UTC)
    s = _rec(agent, tmp_path, "claude-code")
    _tick(agent, s, CC, t0)
    _hook(agent, s, event="PreToolUse:Bash", call="start", tool_use_id="t1", call_sig="sig")
    assert s.tool_open_at is not None
    assert _tick(agent, s, _cc_repaint(25), t0 + timedelta(minutes=25)).state == "working"
    _hook(agent, s, event="PostToolUse:Bash", call="end", tool_use_id="t1")
    assert s.tool_open_at is None
    assert s.work_at is not None  # the post-tool event is work, stamped when it lands
    # a live subagent holds the clocks too
    s2 = _rec(agent, tmp_path, "claude-code", sid="ao-x-t")
    _tick(agent, s2, CC, t0)
    s2.subagents, s2.subagent_at = 1, (t0 + timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
    assert _tick(agent, s2, _cc_repaint(3), t0 + timedelta(minutes=25)).state == "working"


async def test_an_adapter_naming_no_volatile_rows_reads_a_static_pane_as_before(agent, tmp_path, monkeypatch):
    t0 = datetime.now(UTC)
    s = _rec(agent, tmp_path, "claude-code")
    ad = adapters.get("claude-code")
    monkeypatch.setattr(type(ad), "volatile_rows", ())
    monkeypatch.setattr(type(ad), "volatile_after", None)
    _tick(agent, s, CC, t0)
    assert _tick(agent, s, CC, t0 + timedelta(minutes=19)).state == "working"
    assert _tick(agent, s, CC, t0 + timedelta(minutes=21)).state == "stalled?"
    # with nothing masked, a repaint is something new
    s = _rec(agent, tmp_path, "claude-code", sid="ao-x-u")
    _tick(agent, s, CC, t0)
    assert _tick(agent, s, _cc_repaint(7), t0 + timedelta(minutes=21)).state == "working"


async def test_a_screen_verdict_of_limited_wins_over_the_stall_check(agent, tmp_path):
    t0 = datetime.now(UTC)
    s = _rec(agent, tmp_path, "gemini")
    box = (FIX / "gemini" / "captured" / "panes" / "6-a-doorbell.txt").read_text(encoding="utf-8").splitlines()
    _tick(agent, s, box, t0, WORKING)
    s = _tick(agent, s, box, t0 + timedelta(minutes=40), WORKING)
    assert (s.state, s.stalled_ticks) == ("limited", 0)


async def test_an_open_call_holds_until_the_ceiling_and_parallel_calls_each_count(agent, tmp_path):
    t0 = datetime.now(UTC)
    s = _rec(agent, tmp_path, "claude-code")
    _tick(agent, s, CC, t0)
    _hook(agent, s, event="PreToolUse:Bash", call="start", tool_use_id="a", call_sig="x")
    _hook(agent, s, event="PreToolUse:Bash", call="start", tool_use_id="b", call_sig="y")
    _hook(agent, s, event="PostToolUse:Bash", call="end", tool_use_id="a")
    assert s.tool_open_at is not None  # b is still open
    assert _tick(agent, s, CC, t0 + timedelta(minutes=40)).state == "working"
    past = t0 + OPEN_TOOL_CEILING + timedelta(minutes=1)
    assert _tick(agent, s, CC, past).state == "stalled?"  # a hung call, or a lost post-tool hook
    # an interrupted call (no post-tool event, no stop) is cleared by the next prompt
    s = _rec(agent, tmp_path, "claude-code", sid="ao-x-v")
    _hook(agent, s, event="PreToolUse:Bash", call="start", tool_use_id="c", call_sig="z")
    _hook(agent, s, prompt=True)
    assert s.tool_open_at is None and not agent._tool_open.get(s.id)
    # a stop clears them too, and a session start
    _hook(agent, s, event="PreToolUse:Bash", call="start", tool_use_id="d", call_sig="z")
    agent._apply_event(s.id, {"state": "idle", "pending": None})
    assert s.tool_open_at is None
    _hook(agent, s, event="PreToolUse:Bash", call="start", tool_use_id="e", call_sig="z")
    agent._apply_event(s.id, {"state": "idle", "pending": None, "subagents_reset": True})
    assert s.tool_open_at is None


async def test_gemini_opens_no_call_and_reads_from_its_clocks_alone(agent, tmp_path):
    t0 = datetime.now(UTC)
    s = _rec(agent, tmp_path, "gemini")
    _tick(agent, s, GEM, t0)
    _hook(agent, s, event="BeforeTool:run_shell_command")  # Gemini's hooks carry no per-call id
    assert s.tool_open_at is None and not agent._tool_open.get(s.id)
    assert _tick(agent, s, _gem_repaint(4), t0 + timedelta(minutes=10), WORKING).state == "working"
    assert _tick(agent, s, _gem_repaint(5), t0 + timedelta(minutes=25), WORKING).state == "stalled?"


async def test_a_restart_keeps_the_screen_clock_the_open_call_and_the_count(agent, tmp_path):
    """The clocks are on the record: a restart (memory emptied) that finds the same masked text keeps
    `screen_at`; a call open 10 minutes before it still holds at 25; the first post-tool event clears it."""
    t0 = datetime.now(UTC)
    s = _rec(agent, tmp_path, "claude-code")
    _tick(agent, s, CC, t0)
    screen_at = s.screen_at
    s.tool_open_at = (t0 - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    agent._tool_open.clear()  # the restart
    assert _tick(agent, s, _cc_repaint(2), t0 + timedelta(minutes=15)).screen_at == screen_at
    assert _tick(agent, s, CC, t0 + timedelta(minutes=25)).state == "working"  # the call holds
    _hook(agent, s, event="PostToolUse:Bash", call="end", tool_use_id="other")  # the first post-tool event
    assert s.tool_open_at is None
    s.work_at = None
    assert _tick(agent, s, CC, t0 + timedelta(minutes=25)).state == "stalled?"
    assert _tick(agent, s, CC, t0 + timedelta(minutes=26)).stalled_ticks == 2
    agent._tool_open.clear()
    assert _tick(agent, s, CC, t0 + timedelta(minutes=27)).stalled_ticks == 3  # kept on the record
    # a start after the restart keeps the older opening
    s2 = _rec(agent, tmp_path, "claude-code", sid="ao-x-w")
    old = (t0 - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    s2.tool_open_at = old
    _hook(agent, s2, event="PreToolUse:Bash", call="start", tool_use_id="n", call_sig="q")
    assert s2.tool_open_at == old
