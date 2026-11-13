"""The tick's screen road over a hook-fed adapter, beside a usage poll (design §4.2, §4.3 *The limit dialog
is read off the screen*, TD-944 slice 2): what TD-944 changed for every adapter, read on Claude Code's
rules, which have no title and no modal rule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sessionorc import adapters, agent_common
from sessionorc.models import Pending, Session
from sessionorc.tmux import PaneInfo

pytestmark = pytest.mark.integration

SCREENS = Path(__file__).parent / "fixtures" / "screens"
CAP = Pending(kind="limit", text="5-hour limit — resets 14:00")


def screen(name: str) -> list[str]:
    return (SCREENS / f"{name}.txt").read_text().splitlines()


def _rec(tmp_path, state="working", confidence="hook", pending=None) -> Session:
    s = Session(id="ao-x-c", name="c", kind="agent", dir=str(tmp_path), adapter="claude-code", state=state)
    s.confidence, s.pending = confidence, pending
    return s


def _tick(agent, s: Session, tail: list[str], hook_age: float = 60.0) -> Session:
    now = datetime.now(UTC)
    agent._last_hook[s.id] = now - timedelta(seconds=hook_age)
    agent._observe(s, PaneInfo(s.id, 0, "node", 1, dead=False, dead_status=None, title=""), tail, now)
    return s


@pytest.fixture
def stale():
    """A hook older than the stall window: Claude Code's rules apply only past it."""
    adapters.load_all()
    return agent_common.STALL_AFTER.total_seconds() + 60


async def test_claude_codes_scraped_limit_takes_a_changed_pending(agent, stale, tmp_path):
    s = _tick(agent, _rec(tmp_path), screen("usage-limit-reached"), stale)
    first = s.pending
    assert (s.state, s.confidence) == ("limited", "scraped") and first.kind == "limit"
    s = _tick(agent, s, screen("usage-limit-hit"), stale)
    assert s.state == "limited" and s.pending != first


async def test_a_scraped_idle_with_nothing_saved_stays_so(agent, stale, tmp_path):
    s = _rec(tmp_path, state="idle", confidence="scraped")
    since, rev = s.since, s.rev
    for _ in range(3):
        _tick(agent, s, ["$ "], stale)
    assert (s.state, s.confidence, s.since, s.rev) == ("idle", "scraped", since, rev)


async def test_a_limit_message_over_the_polls_limited_keeps_the_polls_pending(agent, stale, tmp_path):
    s = _tick(agent, _rec(tmp_path, state="limited", pending=CAP), screen("usage-limit-reached"), stale)
    assert (s.state, s.confidence, s.pending) == ("limited", "hook", CAP) and s.id not in agent._hook_state


async def test_another_rule_over_the_polls_limited_saves_it_and_gives_it_back(agent, stale, tmp_path):
    s = _tick(agent, _rec(tmp_path, state="limited", pending=CAP), screen("held-peer-message"), stale)
    assert (s.state, s.confidence) == ("needs-you", "scraped")
    assert agent._hook_state[s.id] == ("limited", CAP, "hook")
    s = _tick(agent, s, ["$ "], stale)
    assert (s.state, s.confidence, s.pending) == ("limited", "hook", CAP)


async def test_the_polls_lift_of_a_scraped_limit_goes_back_to_what_it_replaced(agent, stale, tmp_path):
    """Claude Code's limit message is not modal: a poll that reads no cap lifts it, to the state the
    verdict replaced rather than `_pre_limited`'s `working`."""
    s = _tick(agent, _rec(tmp_path, state="idle"), screen("usage-limit-reached"), stale)
    assert s.state == "limited" and not agent_common.limit_is_modal(s, adapters.get("claude-code"))
    agent._usage_limits([s], set())
    assert (s.state, s.confidence) == ("idle", "hook") and s.id not in agent._hook_state


async def test_a_scraped_lift_spends_a_polls_mark_the_verdict_replaced(agent, stale, tmp_path):
    s = _tick(agent, _rec(tmp_path, state="limited", pending=CAP), screen("held-peer-message"), stale)
    agent._pre_limited[s.id] = "working"  # the poll had marked it from `working`
    s = _tick(agent, s, screen("usage-limit-reached"), stale)  # the limit message replaces the question
    assert (s.state, s.confidence) == ("limited", "scraped")
    agent._usage_limits([s], set())  # back to the poll's own `limited`, its mark kept for its next lift
    assert (s.state, s.confidence, s.pending) == ("limited", "hook", CAP) and agent._pre_limited[s.id] == "working"
    agent._usage_limits([s], set())
    assert (s.state, s.confidence) == ("working", "hook") and s.id not in agent._pre_limited
    s = _tick(agent, _rec(tmp_path, state="idle"), screen("usage-limit-reached"), stale)
    agent._pre_limited[s.id] = "idle"  # a stale mark from an earlier cap
    agent._usage_limits([s], set())
    assert s.state == "idle" and s.id not in agent._pre_limited


@pytest.mark.parametrize(("before", "restart", "after"), [("idle", True, "idle"), ("working", False, "working")])
async def test_the_polls_lift_goes_back_to_the_state_before_its_mark_or_idle_after_a_restart(
    agent, tmp_path, before, restart, after
):
    """TD-1798, design §4.2: what a session was before the poll's `limited` is the host agent's memory alone;
    a restart inside the spell drops it, and the lift then reads `idle`, never a `working` the tick would read
    as `stalled?`. With the memory kept, the lift goes back to what it was, a working session included."""
    adapters.load_all()
    s = _rec(tmp_path, state=before)
    resets = (datetime.now(UTC) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    agent._usage[s.profile] = {"windows": [{"label": "week", "pct": 100, "resets": resets}]}
    agent._usage_limits([s], set())
    assert (s.state, s.confidence) == ("limited", "hook") and s.pending is not None and s.pending.kind == "limit"
    assert agent._pre_limited[s.id] == before
    if restart:
        agent._pre_limited.clear()  # what a host-agent restart forgets
    agent._usage[s.profile] = {"windows": [{"label": "week", "pct": 2, "resets": resets}]}
    agent._usage_limits([s], set())
    assert (s.state, s.confidence, s.pending) == (after, "hook", None) and s.id not in agent._pre_limited
