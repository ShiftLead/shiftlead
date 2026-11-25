"""After the cut-over a built-in seat is filled only where design §4.9d *When they run* allows it (TD-2065): a tech
lead's while its team is started and on while that team's sessions finish, a repo's seat while any of the repo's teams
is started, and the tagging seat is the tech lead of the repo's first started team."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from conftest import park_ticks

from sessionorc import paths
from sessionorc.models import Session

SETTINGS = """cut_over: 2026-12-01
teams:
  a: {repo: repo, host: home, flow: build, logins: []}
  b: {repo: repo, host: home, flow: build, logins: []}
  c: {repo: other, host: home, flow: build, logins: []}
"""
STARTED = {"started": {"since": "2026-12-01T09:00:00Z", "by": "person"}}


def _stopped(by: str = "person", at: str = "2026-12-01T10:00:00Z") -> dict:
    return {"stopped": {"at": at, "by": by}}


async def _cut(agent, **marks) -> None:
    await park_ticks(agent)
    paths.home().mkdir(parents=True, exist_ok=True)
    (paths.home() / "settings.yml").write_text(SETTINGS)
    agent._read_cut_over()
    assert agent._first_shape_off
    agent._host_rec["teams"] = marks


def _seat(agent, name: str, builtin: str | None, team: str = "", trigger: dict | None = None, **kw) -> Session:
    s = Session(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="shell", dir="/tmp/x", state="closed", team=team,
        repo="/tmp/repo", supervised=True, unattended=True, builtin=builtin,
        seat=trigger or {"trigger": "asks", "tags": True}, **kw,
    )  # fmt: skip
    agent.sessions[s.id] = s
    return s


def _member(agent, name: str, team: str, state: str = "working") -> Session:
    s = Session(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="shell", dir="/tmp/x", state=state, team=team,
        repo="/tmp/repo", supervised=True, unattended=True,
    )  # fmt: skip
    agent.sessions[s.id] = s
    return s


async def test_a_tech_lead_runs_while_its_team_is_started(agent):
    await _cut(agent, a=STARTED)
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    assert agent._builtin_hold(lead, [lead]) is None


async def test_a_wound_down_team_s_tech_lead_answers_while_a_session_finishes(agent):
    await _cut(agent, a=_stopped())
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    finishing = _member(agent, "w", "a")
    assert agent._builtin_hold(lead, [lead, finishing]) is None
    finishing.state = "closed"
    assert agent._builtin_hold(lead, [lead, finishing]) == {"at": "2026-12-01T10:00:00Z", "by": "person", "team": "a"}


def _decoy(agent, case: str) -> Session:
    """A live record of team a that is no finishing session of it: each case fails one clause of the reading."""
    s = _member(agent, f"decoy-{case}", "a")
    if case == "superseded":
        s.superseded_by = "ao-t-elsewhere"
    elif case == "attended":
        s.unattended = False
    elif case == "first-shape seat":
        s.seat = {"trigger": "asks"}
    elif case == "built-in record":
        s.builtin = "sweeper"
    return s


@pytest.mark.parametrize("case", ["superseded", "attended", "first-shape seat", "built-in record"])
async def test_no_seat_superseded_or_attended_record_keeps_a_wound_down_tech_lead_on(agent, case):
    await _cut(agent, a=_stopped())
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    lead.state = "working"  # a live lead is never its own team's finishing session
    assert agent._builtin_hold(lead, [lead]) == {"at": "2026-12-01T10:00:00Z", "by": "person", "team": "a"}
    decoy = _decoy(agent, case)
    assert agent._builtin_hold(lead, [lead, decoy]) == {"at": "2026-12-01T10:00:00Z", "by": "person", "team": "a"}


async def test_another_team_s_session_keeps_no_tech_lead_running(agent):
    await _cut(agent, a=_stopped("until"), b=STARTED)
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    other = _member(agent, "w", "b")
    assert agent._builtin_hold(lead, [lead, other])["by"] == "until"


@pytest.mark.parametrize("key", ["sweeper", "prompts"])
async def test_a_repo_s_seat_runs_while_any_of_its_teams_is_started(agent, key):
    await _cut(agent, a=_stopped(), b=STARTED, c=STARTED)
    seat = _seat(agent, f"{key}-repo", key, trigger={"trigger": "prompt"})
    assert agent._builtin_hold(seat, [seat]) is None
    agent._host_rec["teams"]["b"] = _stopped(at="2026-12-01T11:00:00Z")  # c is another repo's, never this one's
    assert agent._builtin_hold(seat, [seat]) == {"at": "2026-12-01T11:00:00Z", "by": "person", "team": ""}


@pytest.mark.parametrize(("key", "held"), [("prompts", False), ("sweeper", True)])
async def test_only_the_prompts_seat_runs_on_while_a_repo_s_session_finishes(agent, key, held):
    await _cut(agent, a=_stopped(), b=_stopped())
    seat = _seat(agent, f"{key}-repo", key, trigger={"trigger": "prompt"})
    finishing = _member(agent, "w", "b")
    assert (agent._builtin_hold(seat, [seat, finishing]) is not None) is held


async def test_a_held_built_in_seat_is_not_filled_and_carries_its_hold(agent, monkeypatch):
    await _cut(agent, a=_stopped())
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    lead.host = agent.host
    lead.seat_due = {"at": "2026-12-01T10:30:00Z", "by": "asks", "ask": "m-1"}
    monkeypatch.setattr(agent, "_seat_due", lambda s, now, records: s.seat_due)
    fill = AsyncMock()
    monkeypatch.setattr(agent, "_fill", fill)
    await agent._seat_pass(lead, datetime.now(UTC), [lead])
    fill.assert_not_awaited()
    assert lead.stop_held == {"at": "2026-12-01T10:00:00Z", "by": "person", "team": "a"}
    agent._host_rec["teams"]["a"] = STARTED
    await agent._seat_pass(lead, datetime.now(UTC), [lead])
    fill.assert_awaited_once()
    assert lead.stop_held is None


async def test_the_tagging_seat_is_the_first_started_team_s_tech_lead(agent):
    await _cut(agent, a=STARTED, b=STARTED)
    a = _seat(agent, "techlead-a", "techlead", team="a")
    b = _seat(agent, "techlead-b", "techlead", team="b")
    assert a.seat["tags"] and b.seat["tags"]
    assert agent._tagging_seat("/tmp/repo", [a, b]) is a
    agent._host_rec["teams"]["a"] = _stopped()
    assert agent._tagging_seat("/tmp/repo", [a, b]) is b
    agent._host_rec["teams"]["b"] = _stopped()
    assert agent._tagging_seat("/tmp/repo", [a, b]) is None


async def test_a_repo_s_sweeper_record_is_the_repo_s_while_a_team_is_started(agent, monkeypatch):
    from sessionorc import agent_tick

    monkeypatch.setattr(agent_tick.settings_mod, "sweep", lambda _doc: {"on": True, "off": [], "every": "1d"})
    await _cut(agent, b=STARTED)
    sweeper = _seat(agent, "sweeper-repo", "sweeper", trigger={"trigger": "swept", "after": "1d", "by": "settings"})
    assert agent._sweep_idle(sweeper, [sweeper]) == ""
    agent._host_rec["teams"]["b"] = _stopped()
    assert agent._sweep_idle(sweeper, [sweeper]) == "other"


async def test_an_odd_team_mark_holds_without_a_crash(agent):
    await _cut(agent, a="started", b=_stopped(at="2026-12-01T08:00:00Z"))
    seat = _seat(agent, "sweeper-repo", "sweeper", trigger={"trigger": "swept"})
    assert agent._builtin_hold(seat, [seat]) == {"at": "2026-12-01T08:00:00Z", "by": "person", "team": ""}


async def test_a_prompts_seat_is_held_once_the_org_has_a_director(agent):
    await _cut(agent, a=STARTED)
    seat = _seat(agent, "prompts-repo", "prompts", trigger={"trigger": "prompt"})
    assert agent._builtin_hold(seat, [seat]) is None
    director = _seat(agent, "director", None, trigger={"trigger": "prompt"})
    assert agent._builtin_hold(seat, [seat, director]) == {"at": "", "by": "director", "team": ""}


async def test_a_held_built_in_seat_s_reply_line_reads_when_they_run(agent):
    """§4.10's reply line for a held seat (TD-2065): after the cut-over a built-in seat's `held` is its §4.9d hold, so a
    tech lead whose team is started reads no hold however its first-shape crew reads, and one wound down says so."""
    from sessionorc import mail

    await _cut(agent, a=STARTED)
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    assert agent._held_words(lead, [lead]) is None and not agent._seat_held(lead, [lead])
    agent._host_rec["teams"]["a"] = _stopped()
    held = agent._held_words(lead, [lead])
    assert held == {"by": "person", "team": "a", "wound": True, "repo": False} and agent._seat_held(lead, [lead])
    line = mail.read_when(lead, "ask", datetime.now(UTC), held=held)
    assert line.startswith("waits in the seat's mailbox: its team a is wound down (by you)")
    agent._host_rec["teams"]["a"] = _stopped("until")
    assert "its team a is stopped (at its stop time)" in mail.read_when(
        lead, "ask", datetime.now(UTC), held=agent._held_words(lead, [lead])
    )
    lead.suspended = {"at": "2026-12-01T10:00:00Z"}
    assert agent._held_words(lead, [lead]) is None, "a seat rule 3 would not fill is never held"


async def test_a_repo_s_seat_and_a_prompts_seat_under_a_director_read_their_own_reply_lines(agent):
    from sessionorc import mail

    await _cut(agent, a=_stopped(), b=_stopped())
    sweeper = _seat(agent, "sweeper-repo", "sweeper", trigger={"trigger": "swept"})
    held = agent._held_words(sweeper, [sweeper])
    assert held["repo"] is True
    line = mail.read_when(sweeper, "ask", datetime.now(UTC), held=held, person=True)
    assert line.startswith("waits in the seat's mailbox: every team of its repo is stopped")
    assert "Start a team of the repo to have it read" in line
    line = mail.read_when(sweeper, "ask", datetime.now(UTC), held=held, person=False)  # a session: no Start for it
    assert "`ao msg person` if it cannot wait" in line
    assert "Start a team" not in line
    agent._host_rec["teams"]["a"] = STARTED
    prompts = _seat(agent, "prompts-repo", "prompts", trigger={"trigger": "prompt"})
    director = _seat(agent, "director", None, trigger={"trigger": "prompt"})
    held = agent._held_words(prompts, [prompts, director])
    assert held["by"] == "director"
    line = mail.read_when(prompts, "ask", datetime.now(UTC), held=held)
    assert line.startswith("waits in the seat's mailbox: the org's director answers in its place")


async def test_before_the_cut_over_a_built_in_mark_reads_the_first_shape_hold(agent, monkeypatch):
    await park_ticks(agent)
    assert not agent._first_shape_off
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    calls = []
    monkeypatch.setattr(agent, "_builtin_hold", lambda *a: calls.append(a) or {"by": "person"})
    agent._held_words(lead, [lead])
    agent._seat_held(lead, [lead])
    assert calls == []


async def test_a_held_built_in_tech_lead_takes_no_blank_pick_and_one_started_does(agent):
    """A blank Team pick's target is able and not held (§4.10 *A team or a repo as the address*, TD-1564): after the
    cut-over a built-in tech lead's hold is §4.9d's, a wound-down team's lead refuses it, a started one takes it."""
    await _cut(agent, a=_stopped(), b=STARTED)
    held = _seat(agent, "techlead-a", "techlead", team="a")
    started = _seat(agent, "techlead-b", "techlead", team="b")
    assert not agent._seat_id_takes(held.id)
    assert agent._seat_id_takes(started.id)


def _blank_pick(to: str, teams: list[tuple[str, str]]):
    from sessionorc.mail import PERSON
    from sessionorc.models import MailEntry

    e = MailEntry(id="m-blank0000001", from_=PERSON, to=[to], at="2026-12-01T10:05:00Z", kind="ask", text="blank")
    e.handed = True
    e.entry = {"repo": "repo", "type": "debt", "teams": [{"team": t, "seat": s} for t, s in teams]}
    return e


async def test_a_blank_pick_moves_off_a_built_in_tech_lead_only_while_its_team_is_held(agent):
    """The tick moves a blank pick off a held seat to the next team's (§4.9b *A question already waiting*, TD-1564),
    reading a built-in seat's hold by §4.9d after the cut-over: a started team's lead keeps it, however few of its
    first-shape crew run, and a wound-down team's lead hands it on."""
    await _cut(agent, a=STARTED, b=STARTED)
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    other = _seat(agent, "techlead-b", "techlead", team="b")
    e = _blank_pick(lead.id, [("a", lead.id), ("b", other.id)])
    lead.inbox.append(e)
    await agent._reroute_waiting(datetime.now(UTC))
    assert e.open and not other.inbox, "a started team's lead is not held: the pick stays"
    agent._host_rec["teams"]["a"] = _stopped()
    await agent._reroute_waiting(datetime.now(UTC))
    assert e.closed_reason == "rerouted"
    (moved,) = other.inbox
    assert moved.root == e.id and moved.routed["why"] == "its team is stopped"


async def test_a_built_in_seat_that_sat_out_reads_no_hold(agent):
    await _cut(agent, a=_stopped())
    lead = _seat(agent, "techlead-a", "techlead", team="a")
    assert agent._seat_held(lead, [lead])
    lead.sit_out = {"at": "2026-12-01T10:00:00Z"}
    assert not agent._seat_held(lead, [lead]) and agent._held_words(lead, [lead]) is None
