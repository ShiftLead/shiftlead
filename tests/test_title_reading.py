"""A title reading is the tool's own word (design §4.2 *A title the tool writes its state into*, TD-785
slice 1, TD-839): every rule that acts only on a hook-confirmed state acts on `confidence: title` as it
does on `hook`, and on neither for `scraped`. One case per family of `Session.told` sites — the read-when
sentence, the cache restart, the doorbell, the first prompt's road and its seeding at load, the tick's
rules 3, 4, 5, 7, 10 and 11, and the title's own comparison — so a site going
back to `confidence == "hook"` fails its case."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import park_ticks

from sessionorc import agent_common, held, mail
from sessionorc.agent import IDLE_NUDGE, SEAT_IDLE_GRACE, HostAgent
from sessionorc.client import LocalClient
from sessionorc.models import Pending, Session

SHELL = {"adapter": "agentshell", "argv": ["bash", "--norc", "--noprofile"], "unattended": True, "supervised": True}
TOLD = [("hook", True), ("title", True), ("scraped", False)]
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _rec(confidence: str, **kw) -> Session:
    s = Session(id="ao-w", name="w", kind="interactive", adapter="claude-code", dir="/w", state="idle", **kw)
    s.set_state("idle", confidence=confidence)
    return s


@pytest.mark.unit
@pytest.mark.parametrize(("confidence", "told"), TOLD)
def test_the_read_when_sentence_rings_a_title_idle(confidence, told):
    """`mail.read_when`'s two idle rows: rung, or for a tool with no composer *nothing is typed*."""
    s = _rec(confidence, unattended=True)
    rung, untyped = mail.read_when(s, "note", NOW), mail.read_when(s, "note", NOW, rings=False)
    assert rung.startswith("rung within a tick") is told
    assert untyped.startswith("lands; nothing is typed into this tool's pane") is told
    if not told:
        assert rung.startswith("lands; its idle is a guess from the screen") and untyped == rung


@pytest.mark.unit
@pytest.mark.parametrize(("confidence", "told"), TOLD)
def test_a_lapsed_cache_and_rule_7s_precondition_read_a_title_idle(confidence, told):
    """`agent_common.cache_lapsed` and `tick_ready` (§4.10 *A lapsed cache is started again*, §6 rule 7)."""
    s = _rec(confidence, unattended=True, supervised=True)
    s.since = _iso(NOW - agent_common.CACHE_LIFETIME - timedelta(minutes=5))
    s.context = {"tokens": agent_common.CACHE_FLOOR + 1, "at": _iso(NOW)}
    s.git = {"dirty": 0, "unpushed": 0}
    assert (agent_common.cache_lapsed(s, NOW) is not None) is told
    assert agent_common.tick_ready(s, NOW) is told


async def _member(agent, person, tmp_path, name: str, confidence: str, **kw) -> Session:
    (tmp_path / name).mkdir(exist_ok=True)
    params = {"name": name, "dir": str(tmp_path / name), **SHELL, **kw}
    s = agent.sessions[(await person.call("create", **params))["id"]]
    s.set_state("idle", confidence=confidence)
    s.since = _iso(datetime.now(UTC) - timedelta(hours=2))
    s.git = {"branch": "main", "dirty": 0, "unpushed": 0}
    s.first_prompt, s.first_prompt_sent_at = None, _iso(datetime.now(UTC) - timedelta(hours=3))
    return s


@pytest.fixture
def sent(agent, monkeypatch) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []

    async def policy_send(s, text):
        lines.append((s.id, text))
        return True

    monkeypatch.setattr(agent, "_policy_send", policy_send)
    return lines


@pytest.mark.integration
@pytest.mark.parametrize(("confidence", "told"), TOLD)
async def test_the_doorbell_and_the_first_prompts_road_take_a_title_idle(agent, tmp_path, confidence, told):
    """`_bell_blocked`'s first test, and `_first_prompt_road` for a record fed this run (agent_wake)."""
    await park_ticks(agent)
    async with LocalClient() as person:
        s = await _member(agent, person, tmp_path, "w", confidence)
        now = datetime.now(UTC)
        assert (agent._bell_blocked(s, now) != "not hook-confirmed idle") is told
        agent._last_hook[s.id] = now
        assert (agent._first_prompt_road(s, now) == "hook") is told


@pytest.mark.integration
@pytest.mark.parametrize(("confidence", "told"), TOLD)
async def test_an_agent_started_now_seeds_a_title_record_as_fed(agent, tmp_path, confidence, told):
    """At load a record a hook (or a title) reached is seeded as fed (agent.py's `_last_hook`, TD-720)."""
    await park_ticks(agent)
    async with LocalClient() as person:
        s = await _member(agent, person, tmp_path, "w", confidence)
        s.hook_seen_at = _iso(datetime.now(UTC))
        agent._save(s)
        assert (s.id in HostAgent(tmux=agent.tmux)._last_hook) is told


@pytest.mark.integration
@pytest.mark.parametrize(("confidence", "told"), TOLD)
async def test_the_tick_nudges_marks_and_tells_a_title_idle_member(agent, tmp_path, sent, confidence, told):
    """Rule 4's nudge and rule 3's *idle · open work*, rule 5's context line, rule 10's cadence line
    and rule 11's held line, each typed into a member idle by a title as by a hook."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        w = await _member(agent, person, tmp_path, "w", confidence, lane=["TD-001"])
        w.since = _iso(now - IDLE_NUDGE - timedelta(minutes=5))
        await agent._idle_nudge(w, now)
        assert bool(w.nudged_at) is told
        w.nudged_at = _iso(now - IDLE_NUDGE - timedelta(minutes=1))  # rule 3 reads the nudge's stretch
        await agent._idle_open(w, now)
        assert bool(w.idle_open) is told

        c = await _member(agent, person, tmp_path, "c", confidence)
        c.context, c.context_bound = {"tokens": 250_000, "at": _iso(now)}, 200_000
        await agent._context_line(c, now)
        assert bool(c.context_sent_at) is told

        k = await _member(agent, person, tmp_path, "k", confidence)
        k.checks = [{"pr": 842, "at": "t", "sha": "aaa", "verdict": "fail", "failed": ["review"]}]
        await agent._cadence_line(k, now)
        assert bool(k.checks[0].get("told")) is told

        h = await _member(agent, person, tmp_path, "h", confidence, review={"reader": "techlead"})
        h.held_missed = [held.crossing(845, ["src/sessionorc/agent_tick.py"], "t")]
        await agent._held_line(h, now)
        assert bool(h.held_missed[0].get("told")) is told
        assert {sid for sid, _ in sent} == ({w.id, c.id, k.id, h.id} if told else set())


@pytest.mark.integration
@pytest.mark.parametrize(("confidence", "told"), TOLD)
async def test_a_brief_restart_and_a_seats_close_read_a_title_idle(agent, tmp_path, monkeypatch, confidence, told):
    """Rule 7's brief restart reaches its ceiling check (`_brief_restart`) and rule 3 closes a seat
    that has run (`_seat_has_run`) on a title idle as on a hook idle."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    monkeypatch.setattr(agent, "_window_full", lambda s, now: True)  # stop at the ceiling: no replay here
    async with LocalClient() as person:
        b = await _member(agent, person, tmp_path, "b", confidence)
        b.brief_changed = True
        await agent._brief_restart(b, now)
        assert bool(b.restart_ceiling) is told

        seat = await _member(agent, person, tmp_path, "audit", confidence, seat={"trigger": "every", "after": "6h"})
        seat.since = _iso(now - SEAT_IDLE_GRACE - timedelta(minutes=10))
        assert agent._seat_has_run(seat, now) is told


@pytest.mark.integration
@pytest.mark.parametrize(("confidence", "told"), TOLD)
async def test_a_title_permission_is_a_managers_cause(agent, tmp_path, confidence, told):
    """Rule 3's `pending` cause (`_team_causes`): a member at a permission the title reported."""
    await park_ticks(agent)
    async with LocalClient() as person:
        mgr = await _member(agent, person, tmp_path, "mgr", "hook", seat={"trigger": "team"})
        m = await _member(agent, person, tmp_path, "m", confidence, controllers=[mgr.id])
        m.set_state("needs-you", confidence=confidence)
        m.pending = Pending.from_dict({"kind": "permission", "text": "Shell: ls", "tool_use_id": "tu-1"})
        causes = agent._team_causes(mgr, list(agent.sessions.values()))
        assert ([c["by"] for c in causes] == ["pending"]) is told


@pytest.mark.integration
@pytest.mark.parametrize(("confidence", "told"), TOLD)
async def test_a_working_event_on_a_title_idle_is_logged(agent, tmp_path, caplog, confidence, told):
    """`_apply_event`'s capture (TD-201): an event that is not a turn's start woke a session its Stop left idle."""
    await park_ticks(agent)
    async with LocalClient() as person:
        s = await _member(agent, person, tmp_path, "w", confidence)
        with caplog.at_level(logging.INFO, logger="shiftlead.agent"):
            await agent.rpc_hook(s.id, state="working", event="PostToolUse")
        assert ("turned a hook-confirmed idle session working" in caplog.text) is told


@pytest.mark.integration
@pytest.mark.parametrize(("confidence", "told"), TOLD)
async def test_a_title_verdict_is_compared_with_a_title_state(agent, tmp_path, confidence, told):
    """`_title_reading` (TD-785 slice 3): a record whose state the title set is the tool's word, so the
    next verdict is compared with it; a scraped state is not compared."""
    await park_ticks(agent)
    async with LocalClient() as person:
        s = await _member(agent, person, tmp_path, "w", confidence)
        s.set_state("working", confidence=confidence)
        s.hook_seen_at = _iso(datetime.now(UTC) - timedelta(hours=1))
        agent._last_hook.pop(s.id, None)
        got, why = agent._title_reading(s, SimpleNamespace(state="idle"), datetime.now(UTC))
        assert (got is not None) is told, why
