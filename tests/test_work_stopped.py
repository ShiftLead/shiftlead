"""TD-782 slice 1, design §6 rule 8 *A team that stopped* (TD-781): a team with nobody live that is not wound
down is *stopped* — read as a wound-down team is, its mark carrying `stopped: {by, at}`, never started; `by` read
from the team's ending alone (`work.stopped_by`), `wrapup_by` saying whose wrap-up it left after; a record never
read for news gets a baseline from the ledger at its end; Telegram tells `until` and `other`, never `person`."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import settings as settings_mod
from sessionorc import work
from sessionorc.agent_common import FINISHED_SETTLE, WORK_SETTLE
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import Session

T0 = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _e(id: str) -> dict:
    return {"id": id, "title": id, "priority": "medium", "owner": "grinder", "kind": "build", "pickable": "yes"}


def _rec(name: str, team: str = "g", **kw) -> Session:
    base = dict(
        id=f"ao-t-{name}", name=name, kind="interactive", adapter="shell", dir="/tmp/x", state="exited",
        team=team, unattended=True, supervised=True, pane=False, lane=["free-pick"],
    )  # fmt: skip
    return Session(**{**base, **kw})


def _killed(by: str, at: datetime, why: str | None = None) -> dict:
    return {"how": "kill", "at": _iso(at), "by": by, **({"why": why} if why else {})}


# -- the reading --------------------------------------------------------------------------------------------


def test_a_team_with_nobody_live_and_not_wound_down_is_stopped_and_by_whom():
    person = [_rec("m", ended=_killed("person", T0)), _rec("g1", ended=_killed("person", T0))]
    assert work.team_stopped(person) == {"by": "person", "at": T0.isoformat()}
    crash = [_rec("m", ended={"how": "pane", "at": _iso(T0), "code": 1}), _rec("g1", ended=_killed("ao-t-m", T0))]
    assert work.team_stopped(crash)["by"] == "other"
    clock = [_rec("m", ended=_killed("tick", T0, "stop time")), _rec("g1", ended=_killed("tick", T0, "stop time"))]
    assert work.team_stopped(clock)["by"] == "until"
    # a member that exited on its own after the stop time's wrap-up names nobody: the stop time's
    left = _rec("g1", ended={"how": "tool", "at": _iso(T0)}, wrapup_sent_at=_iso(T0 - timedelta(minutes=5)))
    assert work.team_stopped([left])["by"] == "until"
    # a live member, a wound-down team, or no record: not stopped
    assert work.team_stopped([*person, _rec("g2", state="idle")]) is None
    out = {"at": _iso(T0), "why": "nothing pickable"}
    assert work.team_stopped([_rec("g1", out_of_work=out, ended=_killed("person", T0))]) is None
    assert work.team_stopped([]) is None


def test_by_is_read_from_the_teams_ending_alone():
    # the person closed a member a day before the stop time stopped the rest: `until`
    early = _rec("g1", state="closed", closer={"by": "person", "why": None, "at": _iso(T0 - timedelta(days=1))})
    clock = _rec("g2", ended=_killed("tick", T0, "stop time"))
    assert work.stopped_by([early, clock]) == {"by": "until", "at": T0.isoformat()}
    # within FINISHED_SETTLE of the last end, the person's word wins
    near = _rec("g1", state="closed", closer={"by": "person", "why": None, "at": _iso(T0 - FINISHED_SETTLE)})
    assert work.stopped_by([near, clock])["by"] == "person"
    # a superseded record the person closed is not the team's current crew
    old = _rec("g3", state="closed", closer={"by": "person", "at": _iso(T0)}, superseded_by="ao-t-g3b")
    assert work.stopped_by([old, clock])["by"] == "until"
    # a killed record Closed later keeps its kill's end: the Close's person does not override the stop time
    tidied = _rec(
        "g1",
        state="closed",
        ended=_killed("tick", T0, "stop time"),
        closer={"by": "person", "at": _iso(T0 + timedelta(hours=3))},
    )
    assert work.record_end(tidied) == _iso(T0)
    assert work.stopped_by([tidied]) == {"by": "until", "at": T0.isoformat()}


def test_a_wind_down_the_person_sent_reads_person_and_a_managers_does_not():
    gone = {"how": "tool", "at": _iso(T0)}
    mine = _rec("g1", ended=gone, wrapup_at=_iso(T0 - timedelta(minutes=3)), wrapup_by="person")
    assert work.stopped_by([mine])["by"] == "person"
    lead = _rec("g1", ended=gone, wrapup_at=_iso(T0 - timedelta(minutes=3)), wrapup_by="ao-t-manager")
    assert work.stopped_by([lead])["by"] == "other"
    # both a person's wrap-up and the stop time's: the later decides
    both = dict(ended=gone, wrapup_by="person")
    later = _rec(
        "g1", wrapup_at=_iso(T0 - timedelta(minutes=1)), wrapup_sent_at=_iso(T0 - timedelta(minutes=9)), **both
    )
    assert work.stopped_by([later])["by"] == "person"
    earlier = _rec(
        "g1", wrapup_at=_iso(T0 - timedelta(minutes=9)), wrapup_sent_at=_iso(T0 - timedelta(minutes=1)), **both
    )
    assert work.stopped_by([earlier])["by"] == "until"


async def test_a_wrap_up_stamps_who_sent_it_and_a_plain_send_clears_it(agent, monkeypatch):
    await park_ticks(agent)

    async def submit(*a, **k):
        return None, None

    monkeypatch.setattr(agent, "_submit", submit)
    agent.sessions["ao-t-w"] = s = _rec("w", adapter="claude-code", state="idle", pane=True)
    agent.sessions["ao-t-lead"] = _rec("lead", adapter="claude-code", state="idle", pane=True)
    await agent.rpc_send("ao-t-w", "wrap up", wrapup=True)
    assert s.wrapup_at and s.wrapup_by == "person"
    await agent.rpc_send("ao-t-w", "carry on")
    assert s.wrapup_at is None and s.wrapup_by is None
    await agent.rpc_send("ao-t-w", "wrap up", wrapup=True, caller="ao-t-lead")
    assert s.wrapup_by == "ao-t-lead"


# -- the tick -----------------------------------------------------------------------------------------------


def _team(agent, repo: str, *recs: Session) -> list[Session]:
    for r in recs:
        r.repo = repo
        agent.sessions[r.id] = r
    return list(recs)


def _mark(agent) -> dict | None:
    return ((agent._host_rec.get("teams") or {}).get("g") or {}).get("work_waiting")


async def _settled(agent, now: datetime) -> None:
    await agent._work_marks(now)
    await agent._work_marks(now + WORK_SETTLE)


@pytest.mark.parametrize("on_work", ["ask", "start"])
async def test_a_team_the_person_stopped_is_marked_never_started_and_untold(agent, tmp_path, monkeypatch, on_work):
    await park_ticks(agent)
    replays: list = []

    async def replay(*a, **k):
        replays.append(a)

    monkeypatch.setattr(agent, "_replay", replay)
    settings_mod.save({"teams": {"g": {"on_work": on_work}}})
    repo = str(tmp_path)
    agent._repos[repo] = {"name": "r", "root": repo, "ledger": {"entries": [_e("TD-001"), _e("TD-002")]}}
    _team(agent, repo, _rec("g1", ended=_killed("person", T0), lane_seen={"at": "x", "ids": ["TD-001"]}))
    now = datetime.now(UTC)
    await _settled(agent, now)
    mark = _mark(agent)
    assert mark["members"] == {"g1": ["TD-002"]} and mark["stopped"]["by"] == "person" and "held" not in mark
    assert replays == []
    assert "work:g" not in agent._notify_rows(), "the person's own stop is never told"
    with pytest.raises(AgentError, match="never starts a stopped team"):
        async with LocalClient() as person:
            await person.call("work_start", team="g")
    assert replays == []


async def test_a_crash_stopped_team_is_told_with_the_stopped_words(agent, tmp_path):
    await park_ticks(agent)
    settings_mod.save({"teams": {"g": {"on_work": "start"}}})
    repo = str(tmp_path)
    agent._repos[repo] = {"name": "r", "root": repo, "ledger": {"entries": [_e("TD-001"), _e("TD-002")]}}
    _team(agent, repo, _rec("g1", ended={"how": "pane", "at": _iso(T0), "code": 1}, lane_seen={"at": "x", "ids": []}))
    await _settled(agent, datetime.now(UTC))
    assert _mark(agent)["stopped"]["by"] == "other"
    row = agent._notify_rows()["work:g"]
    assert row.line == "shiftlead · g stopped and has work: 2 entries"
    # a crew session live again removes it
    agent.sessions["ao-t-g2"] = _rec("g2", state="working", repo=repo)
    await agent._work_marks(datetime.now(UTC) + 2 * WORK_SETTLE)
    assert _mark(agent) is None


def _git(root, *args: str, when: str | None = None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"}
    env["GIT_COMMITTER_EMAIL"] = "t@t"
    if when:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = when
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True, env=env).stdout


def _commit(root, ids: list[str], when: str) -> None:
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "technical_debt.md").write_text("".join(f"## {i}: {i}\n\n**Kind:** build\n\n" for i in ids))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "ledger", when=when)
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")


async def test_the_baseline_is_the_ledger_at_the_records_end(agent, tmp_path):
    """A member never read for news (stopped before it declared) gets `lane_seen` from the ledger as origin held
    it before its end: an entry there is not news, one filed after the stop is, even with the home down between;
    one only on a branch checked out here is not; a red PR standing at the read is not news."""
    await park_ticks(agent)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, ["TD-001"], "2026-10-16T05:00:00Z")
    _commit(repo, ["TD-001", "TD-002"], "2026-10-16T07:00:00Z")  # filed an hour after the stop
    led = {"path": "docs/technical_debt.md", "entries": [_e("TD-001"), _e("TD-002"), _e("TD-009")]}
    red = {
        "id": "pr:77",
        "pr": 77,
        "title": "red",
        "priority": "High",
        "pr_order": True,
        "work_order": True,
        "pickable": "yes",
    }
    agent._repos[str(repo)] = {"name": "repo", "root": str(repo), "ledger": led, "pr_orders": {"orders": [red]}}
    (r,) = _team(agent, str(repo), _rec("g1", ended=_killed("person", T0)))
    now = datetime.now(UTC)
    await agent._work_marks(now)
    assert r.lane_seen["base"] is True
    assert r.lane_seen["ids"] == ["TD-001", "pr:77", "TD-009"]  # the ledger then, the orders now, the checkout's own
    assert _mark(agent) is None, "no news on the tick that wrote the baseline"
    await agent._work_marks(now + timedelta(seconds=1))
    await agent._work_marks(now + WORK_SETTLE + timedelta(seconds=1))
    assert _mark(agent)["members"] == {"g1": ["TD-002"]}
    # a baseline a supersede carried onto a run that ended undeclared is written again
    r.lane_seen = {"at": "2026-10-15T00:00:00Z", "ids": [], "base": True}
    r.created = "2026-10-16T00:00:00Z"
    await agent._work_marks(now + 2 * WORK_SETTLE)
    assert "TD-001" in r.lane_seen["ids"] and r.lane_seen["at"] > r.created
    # a ledger that cannot be read at that commit writes nothing
    r.lane_seen, r.ended = None, _killed("person", datetime(2026, 1, 1, tzinfo=UTC))
    await agent._work_marks(now + 3 * WORK_SETTLE)
    assert r.lane_seen is None


async def test_lanes_is_a_row_kind_snooze_takes(agent):
    await park_ticks(agent)
    async with LocalClient() as person:
        await person.call("attention_snooze", id="dc-grind", kind="lanes", until="2026-10-17T00:00:00Z")
        with pytest.raises(AgentError, match="unknown row kind.*lanes"):
            await person.call("attention_snooze", id="dc-grind", kind="lanez", until="2026-10-17T00:00:00Z")
