"""TD-836, design §6 rule 5 *A waiting claim is not in progress* and *A replay carries the waiting
claims* (TD-820): a declared claim whose PR is open and whose next move is someone else's — the
member's open `ask` or `steer` about it in the person inbox, or its ask held in a reader's
`prs_waiting` — does not keep rule 5's line or rule 4's nudge away, and every tick replay that keeps
mail copies it onto the new record with the replay's `at`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks, wait_for

from sessionorc import naming, work
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import PR_CLOSED, MailEntry, ProgressEntry

pytestmark = pytest.mark.integration

OVER = {"tokens": 231_203, "at": "2026-09-27T20:00:00Z", "window": 1_000_000}
CLEAN = {"branch": "w", "dirty": 0, "unpushed": 0, "upstream": "origin/w"}


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _steer(sid: str, about: str, mid: str = "m-s1") -> MailEntry:
    return MailEntry(
        id=mid, from_=sid, to=["person"], at=_iso(datetime.now(UTC)), kind="steer", text="go?", about=about,
        default="go", bound=_iso(datetime.now(UTC) + timedelta(hours=1)),
    )  # fmt: skip


def _held_ask(sid: str, seat: str, pr: int) -> MailEntry:
    return MailEntry(id=f"m-a{pr}", from_=sid, to=[seat], at=_iso(datetime.now(UTC)), kind="ask", text="read", pr=pr)


def _crash(agent, sid: str) -> None:
    """What the tick records for a tool that left on its own: `exited`, the pane kept (§4.2, TD-023)."""
    rec = agent.sessions[sid]
    rec.state, rec.pane, rec.exit_code = "exited", True, 1
    agent.store.save(rec)


async def _shell(person, tmp_path, name: str, **kw) -> str:
    (tmp_path / name).mkdir()
    params = {"dir": str(tmp_path / name), "adapter": "shell", "argv": ["bash", "--norc", "--noprofile"]}
    return (await person.call("create", name=name, unattended=True, supervised=True, prompt="b", **params, **kw))["id"]


async def _member(agent, person, tmp_path, name="w", **kw) -> str:
    (tmp_path / name).mkdir()
    params = {
        "name": name, "dir": str(tmp_path / name), "adapter": "composer0", "unattended": True,
        "supervised": True, "prompt": "the brief", "context_bound": 200_000,
    }  # fmt: skip
    sid = (await person.call("create", **{**params, **kw}))["id"]
    assert await wait_for(lambda: _painted(agent, sid), timeout=5), "the composer child never painted its prompt"
    return sid


async def _painted(agent, sid: str) -> bool:
    return any(t.startswith(">>") for t in await agent.rpc_tail(sid, 3))


async def _submitted(agent, sid: str) -> list[str]:
    return [t.rstrip() for t in await agent.rpc_tail(sid, 30) if t.startswith("SUBMITTED ")]


async def test_a_waiting_claim_has_an_open_pr_and_someone_elses_next_move(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _shell(person, tmp_path, "w")
        seat = await _shell(person, tmp_path, "tl", seat={"trigger": "prs"})
        rec = agent.sessions[sid]
        rec.repo = "/r"
        agent._repos["/r"] = {"prs": {"open": [{"number": 13}, {"number": 16}]}}
        rec.progress = [
            ProgressEntry(ref="TD-001", review_pr=11),  # its steer about it waits: waiting
            ProgressEntry(ref="TD-002", review_pr=12),  # CI or its own merge: its own move
            ProgressEntry(ref="TD-003", pr=13),  # a reader holds its ask: waiting
            ProgressEntry(ref="TD-004"),  # a steer, but no PR
            ProgressEntry(ref="TD-005", pr=15),  # a steer, but the reading has the PR closed
            ProgressEntry(ref="TD-006", pr=16, source="derived"),  # the tick's reading, not its word
            ProgressEntry(ref="TD-007", status="done", pr=17),
        ]
        agent.person_inbox[:] = [_steer(sid, r, f"m-{r}") for r in ("TD-001", "TD-004", "TD-005", "TD-006", "TD-007")]
        agent.sessions[seat].inbox.append(_held_ask(sid, seat, 13))
        assert [e.ref for e in agent._waiting_claims(rec)] == ["TD-001", "TD-003"]
        # a closed steer, or one of another member's, makes no wait
        agent.person_inbox[0].closed_reason = "answered"
        agent.person_inbox.append(_steer(seat, "TD-002", "m-other"))
        assert [e.ref for e in agent._waiting_claims(rec)] == ["TD-003"]
        # no repo reading: a claim's PR is not read closed
        agent._repos.pop("/r")
        assert [e.ref for e in agent._waiting_claims(rec)] == ["TD-003", "TD-005"]
        # a claim the tick read closed unmerged is not waiting, though its PR is in the open list (TD-860)
        agent._repos["/r"] = {"prs": {"open": [{"number": 13}, {"number": 15}]}}
        rec.progress[4].why = PR_CLOSED
        assert [e.ref for e in agent._waiting_claims(rec)] == ["TD-003"]
        # another member's held ask for the same PR makes no wait of this member's claim
        rec.progress[2].pr = 14
        agent._repos["/r"]["prs"]["open"].append({"number": 14})
        agent.sessions[seat].inbox.append(_held_ask(seat, seat, 14))
        assert agent._waiting_claims(rec) == []
        for i in (sid, seat):
            await person.call("kill", id=i)


async def test_a_member_whose_only_claims_wait_is_told_at_its_bound_and_the_line_names_them(
    agent, composerstubs, tmp_path
):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        tl = await _member(agent, person, tmp_path, name="tl", seat={"trigger": "prs"})
        rec = agent.sessions[sid]
        await agent.rpc_hook(sid, state="idle")
        rec.context = dict(OVER)
        rec.progress = [ProgressEntry(ref="TD-001", review_pr=2015)]
        await agent._keep_running(now)
        assert await _submitted(agent, sid) == [], "an open PR with nothing waiting is its own to move"
        agent.person_inbox[:] = [_steer(sid, "TD-001")]
        rec.progress.append(ProgressEntry(ref="TD-002", pr=2018))
        await agent._keep_running(now)
        assert await _submitted(agent, sid) == [], "TD-002's PR waits on nobody: a claim in progress"
        agent.sessions[tl].inbox.append(_held_ask(sid, tl, 2018))
        await agent._keep_running(now)
        (line,) = await _submitted(agent, sid)
        assert "over your 200k bound — take nothing new" in line and line.endswith("; #2015, #2018 carry over")
        assert rec.context_sent_at
        # a seat is still never told, whatever it holds
        t = agent.sessions[tl]
        await agent.rpc_hook(tl, state="idle")
        t.context, t.context_bound = dict(OVER), 200_000
        t.progress = [ProgressEntry(ref="TD-003", review_pr=9)]
        agent.person_inbox.append(_steer(tl, "TD-003", "m-tl"))
        await agent._keep_running(now)
        assert await _submitted(agent, tl) == [] and t.context_sent_at is None
        for i in (sid, tl):
            await person.call("kill", id=i)


async def test_two_waiting_claims_on_one_pr_name_it_once(agent, composerstubs, tmp_path):
    """TD-860: a claim's `review_pr` and another's `pr` naming one PR carry it over once."""
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _member(agent, person, tmp_path)
        rec = agent.sessions[sid]
        await agent.rpc_hook(sid, state="idle")
        rec.context = dict(OVER)
        rec.progress = [ProgressEntry(ref="TD-001", review_pr=2015), ProgressEntry(ref="TD-002", pr=2015)]
        agent.person_inbox[:] = [_steer(sid, "TD-001", "m-1"), _steer(sid, "TD-002", "m-2")]
        await agent._keep_running(datetime.now(UTC))
        (line,) = await _submitted(agent, sid)
        assert line.endswith("; #2015 carry over")
        await person.call("kill", id=sid)


async def test_the_idle_nudge_passes_over_a_waiting_claim(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _shell(person, tmp_path, "w")
        rec = agent.sessions[sid]
        rec.progress = [ProgressEntry(ref="TD-001", review_pr=11)]
        agent.person_inbox[:] = [_steer(sid, "TD-001")]
        assert agent._nudge_line(rec) is None, "only a waiting claim: no open work"
        rec.progress.append(ProgressEntry(ref="TD-002"))
        line = agent._nudge_line(rec)
        assert line and "`TD-002` open" in line and "TD-001" not in line
        await person.call("kill", id=sid)


async def test_a_tick_replay_carries_the_waiting_claims_and_a_persons_restart_none(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _shell(person, tmp_path, "w")
        other = await _shell(person, tmp_path, "o")
        old = agent.sessions[sid]
        old.progress = [
            ProgressEntry(ref="TD-001", review_pr=11, at=_iso(now - timedelta(hours=11))),
            ProgressEntry(ref="TD-002", review_pr=12),
        ]
        agent.person_inbox[:] = [_steer(sid, "TD-001")]
        _crash(agent, sid)
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert new is not old
        (entry,) = new.restarts
        assert entry["why"] == "crash" and entry["left"] == ["TD-002"], "`left` names only the claims not waiting"
        (carried,) = new.progress
        assert (carried.ref, carried.status, carried.review_pr, carried.at) == ("TD-001", "claimed", 11, entry["at"])
        # the lease is renewed on the new record: another member's claim on it is refused
        async with LocalClient(caller=other) as o:
            with pytest.raises(AgentError, match="claimed by"):
                await o.call("progress", id=other, ref="TD-001")

        # a person's Restart starts fresh
        _crash(agent, sid)
        new.git = dict(CLEAN)
        await person.call("restart", id=sid)
        assert agent.sessions[sid] is not new and agent.sessions[sid].progress == []
        for i in (sid, other):
            await person.call("kill", id=i)


async def test_a_replay_that_keeps_no_mail_carries_no_claim(agent, tmp_path):
    """TD-860: a scheduled start (`start_of`, no `keep_mail`) moves the mail itself and carries nothing."""
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _shell(person, tmp_path, "w")
        old = agent.sessions[sid]
        old.progress = [ProgressEntry(ref="TD-001", review_pr=11)]
        agent.person_inbox[:] = [_steer(sid, "TD-001")]
        assert [e.ref for e in agent._waiting_claims(old)] == ["TD-001"]
        _crash(agent, sid)
        await agent._replay(old, "crash")
        new = agent.sessions[sid]
        assert new is not old and new.progress == [] and new.restarts[-1]["left"] == ["TD-001"]
        await person.call("kill", id=sid)


async def test_a_renamed_replay_renews_the_carried_claim_once(agent, tmp_path):
    """TD-860: a rename's `_carry` copies the claim onto the new record; the replay renews its lease there
    rather than adding a second copy."""
    await park_ticks(agent)
    then = _iso(datetime.now(UTC) - timedelta(hours=11))
    async with LocalClient() as person:
        sid = await _shell(person, tmp_path, "w")
        old = agent.sessions[sid]
        old.progress = [ProgressEntry(ref="TD-001", review_pr=11, at=then)]
        agent.person_inbox[:] = [_steer(sid, "TD-001")]
        await person.call("relaunch", id=sid, launch={"name": "w2"})
        _crash(agent, sid)  # a record is succeeded once it has ended
        await agent._replay(old, "flow", keep_mail=True)
        assert old.superseded_by
        new = agent.sessions[naming.split_address(old.superseded_by)[0]]
        (carried,) = new.progress
        assert carried.ref == "TD-001" and carried.at == new.restarts[-1]["at"] != then
        for i in (sid, new.id):
            await person.call("kill", id=i)


def test_a_member_that_declared_none_beside_a_waiting_claim_reads_unfinished():
    rec = {
        "id": "w", "name": "w", "state": "idle", "unattended": True,
        "out_of_work": {"at": "2026-10-17T20:00:00Z", "why": "only waiting claims"},
        "progress": [{"ref": "TD-001", "status": "claimed", "review_pr": 11, "source": "declared"}],
    }  # fmt: skip
    asked = work.waiting_of([_steer("w", "TD-001")])
    got = work.finished([rec], waiting=asked)
    assert got and got["why"] == ["w waiting on the person: TD-001, until " + work.bound_words(asked["w"][0]["bound"])]
