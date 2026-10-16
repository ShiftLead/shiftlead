"""TD-103 slice (3), design §6 *Keeping a team running* rule 3: the seats. The tick computes
`seat_due` from a seat's trigger — a question waiting, n PRs merged since it came, or a time since
it came — fills an ended seat that is due with its mail kept, caps the fills at six an hour over the
seats sharing a controller, and closes a seat that has run and sits idle with nothing due."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import reports
from sessionorc.agent import FILL_CEILING, SEAT_IDLE_GRACE, SEAT_PR_WAIT
from sessionorc.client import LocalClient
from sessionorc.models import PR_CLOSED, MailEntry, ProgressEntry, Session

pytestmark = pytest.mark.integration


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


@pytest.fixture(autouse=True)
def _no_gh(monkeypatch):
    """No test here asks GitHub: a `prs:` count is what the test says it is."""
    monkeypatch.setattr(reports, "merged_prs", lambda *a, **kw: None)


async def _seat(person, tmp_path, name="audit", trigger="every", after="6h", **kw):
    params = {
        "name": name,
        "dir": str(tmp_path),
        "adapter": "shell",
        "argv": ["bash", "--norc", "--noprofile"],
        "unattended": True,
        "supervised": True,
        "prompt": "the seat's brief",
        "seat": {"trigger": trigger, **({"after": after} if after else {})},
    }
    return (await person.call("create", **{**params, **kw}))["id"]


def _end(agent, sid: str) -> None:
    rec = agent.sessions[sid]
    rec.state, rec.pane, rec.exit_code = "exited", True, 0
    agent.store.save(rec)


def _idle(agent, sid: str, now: datetime, **git) -> None:
    rec = agent.sessions[sid]
    rec.state, rec.confidence, rec.since = "idle", "hook", _iso(now - SEAT_IDLE_GRACE - timedelta(seconds=1))
    rec.git = {"branch": "main", "dirty": 0, "unpushed": 0, **git}


async def test_an_every_seat_comes_due_on_the_clock_and_is_filled_with_its_mail(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _seat(person, tmp_path)
        first = agent.sessions[sid]
        _end(agent, sid)
        now = datetime.now(UTC)
        await agent._keep_running(now + timedelta(hours=5))
        assert agent.sessions[sid] is first and first.seat_due is None, "not yet: six hours since it came"
        await agent._keep_running(now + timedelta(hours=6, minutes=1))
        new = agent.sessions[sid]
        assert new is not first, "filled under its name (§4.1)"
        assert first.seat_due == {"at": first.seat_due["at"], "by": "every"}
        assert new.seat == {"trigger": "every", "after": "6h"} and new.seat_due is None
        assert [r["why"] for r in new.restarts] == ["fill"]
        assert new.supersedes and new.supersedes[0]["mail"] is True, "a fill keeps the seat's mail (§4.9b)"
        await person.call("kill", id=sid)


async def test_an_asks_seat_is_due_while_a_question_waits(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _seat(person, tmp_path, name="tl", trigger="asks", after="")
        rec = agent.sessions[sid]
        _end(agent, sid)
        now = datetime.now(UTC)
        await agent._keep_running(now)
        assert agent.sessions[sid] is rec and rec.seat_due is None, "nothing waiting, nothing due"
        # a question lands and is answered by someone else before the tick: due, then not
        rec.asks_waiting = lambda **kw: 1
        agent._profile_gated = lambda *a: True  # paused: due, but not filled into a pause
        await agent._keep_running(now)
        assert rec.seat_due and rec.seat_due["by"] == "asks" and agent.sessions[sid] is rec
        rec.asks_waiting = lambda **kw: 0
        await agent._keep_running(now)
        assert rec.seat_due is None
        del agent._profile_gated
        rec.asks_waiting = lambda **kw: 2
        await agent._keep_running(now)
        assert agent.sessions[sid] is not rec
        await person.call("kill", id=sid)


async def test_a_prs_seat_counts_merges_since_it_came_and_an_outage_is_not_zero(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _seat(person, tmp_path, trigger="prs", after="3")
        rec = agent.sessions[sid]
        came = datetime.fromisoformat(rec.created.replace("Z", "+00:00"))
        merged = [came - timedelta(hours=1), came + timedelta(minutes=1), came + timedelta(minutes=2)]
        asked: list[str] = []

        def fake(directory, *a, **kw):
            asked.append(str(directory))
            return list(merged)

        monkeypatch.setattr(reports, "merged_prs", fake)
        await agent._count_seats([rec])
        assert rec.seat_count["prs"] == 2 and asked == [str(tmp_path)], "one read, merges before it came left out"
        monkeypatch.setattr(reports, "merged_prs", lambda *a, **kw: None)
        await agent._count_seats([rec])
        assert rec.seat_count["prs"] == 2, "gh could not be asked: the last reading stands"
        _end(agent, sid)
        now = datetime.now(UTC)
        await agent._keep_running(now)
        assert rec.seat_due is None and agent.sessions[sid] is rec
        merged.append(came + timedelta(minutes=3))
        monkeypatch.setattr(reports, "merged_prs", fake)
        await agent._count_seats([rec])
        await agent._keep_running(now)
        assert rec.seat_due and rec.seat_due["by"] == "prs"
        assert agent.sessions[sid] is not rec and agent.sessions[sid].seat_count is None, "the count starts again"
        await person.call("kill", id=sid)


async def test_six_fills_an_hour_over_seats_sharing_a_controller(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        a = await _seat(person, tmp_path, name="a", controllers=["ao-x-mgr"])
        b = await _seat(person, tmp_path, name="b", controllers=["ao-x-mgr"])
        alone = await _seat(person, tmp_path, name="c", controllers=["ao-y-mgr"])
        for sid in (a, b, alone):
            _end(agent, sid)
            agent.sessions[sid].seat_due = {"at": _iso(now), "by": "every"}
        agent.sessions[a].restarts = [{"at": _iso(now - ago), "why": "fill"} for ago in _mins(FILL_CEILING)]
        ra, rb, rc = agent.sessions[a], agent.sessions[b], agent.sessions[alone]
        await agent._keep_running(now)
        tripped = [r for r in (ra, rb) if r.restart_ceiling]
        assert len(tripped) == 1 and tripped[0].restart_ceiling["why"] == "fill", "one seat carries the mark"
        assert agent.sessions[a] is ra and agent.sessions[b] is rb, "its fellow is refused, unmarked"
        assert agent.sessions[alone] is not rc, "a seat under another controller is not held by the ceiling"
        for sid in (a, b, alone):
            await person.call("kill", id=sid)


async def test_a_fellows_lost_brief_ceiling_does_not_trip_the_fill_ceiling(agent, tmp_path):
    """Only a `why: fill` ceiling says a fellow's fill tripped it (§6 rule 3, TD-720): a seat whose brief
    was lost twice beside it leaves the seat whose fill reaches `FILL_CEILING` to carry the mark."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        a = await _seat(person, tmp_path, name="a", controllers=["ao-x-mgr"])
        b = await _seat(person, tmp_path, name="b", controllers=["ao-x-mgr"])
        for sid in (a, b):
            _end(agent, sid)
        agent.sessions[a].seat_due = {"at": _iso(now), "by": "every"}
        agent.sessions[a].restarts = [{"at": _iso(now - ago), "why": "fill"} for ago in _mins(FILL_CEILING)]
        agent.sessions[b].restart_ceiling = {"at": _iso(now), "count": 1, "why": "lost-brief"}
        ra = agent.sessions[a]
        await agent._keep_running(now)
        assert agent.sessions[a] is ra, "not filled past the ceiling"
        assert ra.restart_ceiling and ra.restart_ceiling["why"] == "fill", "the mark is its own"
        for sid in (a, b):
            await person.call("kill", id=sid)


def _mins(n: int) -> list[timedelta]:
    return [timedelta(minutes=5 * (i + 1)) for i in range(n)]


async def test_an_idle_seat_with_nothing_due_and_nothing_left_is_closed(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        done = await _seat(person, tmp_path, name="done")
        dirty = await _seat(person, tmp_path, name="dirty")
        due = await _seat(person, tmp_path, name="due")
        fresh = await _seat(person, tmp_path, name="fresh")
        _idle(agent, done, now)
        _idle(agent, dirty, now, dirty=2)
        _idle(agent, due, now)
        agent.sessions[due].seat_due = {"at": _iso(now), "by": "every"}
        _idle(agent, fresh, now)
        agent.sessions[fresh].since = _iso(now)
        await agent._keep_running(now)
        assert agent.sessions[done].state == "closed"
        assert agent.sessions[due].state == "closed", "an `every` due met while it ran is the next fill's (TD-700)"
        for sid in (dirty, fresh):
            assert agent.sessions[sid].state == "idle", sid
            await person.call("kill", id=sid)
        await person.call("kill", id=due)


async def test_a_prs_seat_that_came_due_mid_run_is_closed_once_idle_and_pushed_then_filled(agent, tmp_path):
    """TD-700: a `prs` seat whose `seat_due` was met while it ran sat idle forever — `_seat_done`
    read the due as work left for that run, so the tick never closed it and so never filled it."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _seat(person, tmp_path, name="audit", trigger="prs", after="10")
        unpushed = await _seat(person, tmp_path, name="left", trigger="prs", after="10")
        rec, left = agent.sessions[sid], agent.sessions[unpushed]
        for r in (rec, left):
            r.seat_count = {"prs": 10, "at": _iso(now)}
        await agent._keep_running(now)
        assert rec.seat_due and rec.seat_due["by"] == "prs" and rec.state != "closed", "due while it runs"
        assert left.seat_due and left.seat_due["by"] == "prs"
        _idle(agent, sid, now)
        _idle(agent, unpushed, now, unpushed=1)
        assert agent._seat_done(rec), "the due is the next run's, not this one's"
        await agent._keep_running(now)
        assert rec.state == "closed" and rec.seat_due, "closed with its due standing"
        assert agent.sessions[unpushed] is left and left.state == "idle", "a seat that left work is the board's"
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert new is not rec and [r["why"] for r in new.restarts] == ["fill"], "filled on the next tick"
        assert new.seat_due is None and new.seat_count is None, "the count starts again at the fill"
        for s in (sid, unpushed):
            await person.call("kill", id=s)


async def test_an_idle_seat_waiting_on_its_own_pr_is_left_open_until_a_reader_holds_it_or_the_wait_runs_out(
    agent, tmp_path
):
    """TD-366: an audit seat opened its PR, launched its fact-check in the background and ended its
    turn — rule 3 closed it, killing the fact-check and leaving the PR with nobody. A PR of its own
    keeps an idle seat open: on its branch in the repo reading, on a claim, or a claim derived from
    its branch before any reading has the PR. Handed to a reader, or past `SEAT_PR_WAIT`, it closes.
    TD-369: a claim carrying `pr` alone, not handed, keeps it open; so does an ask carrying its PR from
    a session of the same id on another host, which is not this seat's hand."""
    await park_ticks(agent)
    now = datetime.now(UTC)
    root = str(tmp_path)
    agent._repos[root] = {"root": root, "prs": {"open": [{"number": 1197, "branch": "td363-gaps", "state": "open"}]}}
    async with LocalClient() as person:
        names = ("onbranch", "claimed", "ownpr", "elsewhere", "fresh", "handed", "closedpr", "late", "reader")
        sids = {n: await _seat(person, tmp_path, name=n) for n in names}
        for sid in sids.values():
            _idle(agent, sid, now)
            agent.sessions[sid].repo = root
        agent.sessions[sids["onbranch"]].git["branch"] = "td363-gaps"
        agent.sessions[sids["claimed"]].progress = [ProgressEntry(ref="TD-365", review_pr=1198)]
        agent.sessions[sids["ownpr"]].progress = [ProgressEntry(ref="TD-367", pr=1201)]
        agent.sessions[sids["elsewhere"]].progress = [ProgressEntry(ref="TD-368", pr=1202)]
        agent.sessions[sids["fresh"]].git["branch"] = "td364-callers"
        agent.sessions[sids["fresh"]].progress = [ProgressEntry(ref="TD-364", source="derived", branch="td364-callers")]
        agent.sessions[sids["handed"]].progress = [ProgressEntry(ref="TD-366", pr=1199, source="derived")]
        agent.sessions[sids["reader"]].inbox.append(
            MailEntry(
                id="m-0000000000aa",
                from_=sids["handed"],
                to=[sids["reader"]],
                at=_iso(now),
                kind="ask",
                text="read #1199",
                pr=1199,
            )
        )
        agent.sessions[sids["reader"]].inbox.append(
            MailEntry(
                id="m-0000000000ab",
                from_=f"{sids['elsewhere']}@laptop",
                to=[sids["reader"]],
                at=_iso(now),
                kind="ask",
                text="read #1202",
                pr=1202,
            )
        )
        agent.sessions[sids["reader"]].git["dirty"] = 1  # not this test's to close
        agent.sessions[sids["closedpr"]].progress = [ProgressEntry(ref="TD-363", pr=1200, why=PR_CLOSED)]
        late = agent.sessions[sids["late"]]
        late.git["branch"] = "td363-gaps"
        late.since = _iso(now - SEAT_PR_WAIT - timedelta(seconds=1))
        await agent._keep_running(now)
        for n in ("onbranch", "claimed", "ownpr", "elsewhere", "fresh", "reader"):
            assert agent.sessions[sids[n]].state == "idle", n
        for n in ("handed", "closedpr", "late"):
            assert agent.sessions[sids[n]].state == "closed", n
        assert agent._seat_prs(agent.sessions[sids["onbranch"]], list(agent.sessions.values())) == ["#1197"]
        for n in ("onbranch", "claimed", "ownpr", "elsewhere", "fresh", "reader"):
            await person.call("kill", id=sids[n])


async def test_rule_three_leaves_an_unsupervised_or_attended_seat_alone(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        plain = await _seat(person, tmp_path, name="plain", supervised=False)
        attended = await _seat(person, tmp_path, name="att")
        agent.sessions[attended].unattended = False
        for sid in (plain, attended):
            _end(agent, sid)
        recs = {sid: agent.sessions[sid] for sid in (plain, attended)}
        await agent._keep_running(now + timedelta(days=1))
        for sid, rec in recs.items():
            assert agent.sessions[sid] is rec and rec.seat_due is None, sid
            await person.call("kill", id=sid)


# -- the tagging seat (§4.4 *An entry names its team*, TD-730, TD-763) ------------------------------


async def _tl(person, tmp_path, team: str, seat=None):
    """A techlead seat of `team` as `ao team start` writes it: `{trigger: asks, tags: true}`."""
    return await _seat(
        person,
        tmp_path,
        name=f"tl-{team}",
        team=team,
        repo=str(tmp_path),
        seat=seat or {"trigger": "asks", "tags": True},
    )


async def _crew(person, tmp_path, team: str) -> str:
    """An unattended member carrying `team`'s badge, live: what makes the team live (§4.9)."""
    params = {
        "name": f"g-{team}",
        "dir": str(tmp_path),
        "adapter": "shell",
        "argv": ["bash", "--norc", "--noprofile"],
        "unattended": True,
        "team": team,
        "repo": str(tmp_path),
    }
    return (await person.call("create", **params))["id"]


def _needs(agent, tmp_path, ids: list[str], declared=("db", "compliance")) -> None:
    agent._repos[str(tmp_path)] = {"ledger": {"declared_teams": list(declared), "needs_team": list(ids)}}


async def test_the_first_declared_live_teams_seat_is_filled_once_per_id_set(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        comp, db = await _tl(person, tmp_path, "compliance"), await _tl(person, tmp_path, "db")
        crew = [await _crew(person, tmp_path, "compliance"), await _crew(person, tmp_path, "db")]
        for sid in (comp, db):
            _end(agent, sid)
        _needs(agent, tmp_path, ["TD-801", "TD-802"])
        agent._profile_gated = lambda *a: True
        await agent._keep_running(now)
        first = agent.sessions[db]
        assert first.seat_due == {"at": first.seat_due["at"], "by": "tag", "ids": ["TD-801", "TD-802"]}
        assert agent.sessions[comp].seat_due is None, "db is declared first: compliance's seat is not the one"
        del agent._profile_gated
        await agent._keep_running(now)
        new = agent.sessions[db]
        assert new is not first, "filled for the tag"
        assert [{k: v for k, v in e.items() if k != "at"} for e in new.seat_filled] == [
            {"by": "tag", "ids": ["TD-801", "TD-802"]}
        ]
        _end(agent, db)
        await agent._keep_running(now)
        assert agent.sessions[db] is new and new.seat_due is None, "a set filled once is not filled again"
        # TD-801 tagged, TD-803 joined: a due for TD-803 alone, the fill's entry kept while TD-802 stands
        _needs(agent, tmp_path, ["TD-802", "TD-803"])
        agent._profile_gated = lambda *a: True
        await agent._keep_running(now)
        assert new.seat_due["ids"] == ["TD-803"] and len(new.seat_filled) == 1
        # every id the fill was for gone: its entry drops
        _needs(agent, tmp_path, ["TD-803"])
        await agent._keep_running(now)
        assert new.seat_filled == [] and new.seat_due["ids"] == ["TD-803"]
        del agent._profile_gated
        for sid in (comp, db, *crew):
            await person.call("kill", id=sid)


async def test_a_stopped_teams_seat_is_never_the_tagging_seat(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        comp, db = await _tl(person, tmp_path, "compliance"), await _tl(person, tmp_path, "db")
        crew = await _crew(person, tmp_path, "compliance")
        for sid in (comp, db):
            _end(agent, sid)
        _needs(agent, tmp_path, ["TD-801"])
        agent._profile_gated = lambda *a: True
        await agent._keep_running(now)
        assert agent.sessions[db].seat_due is None, "db has nothing live: stopped"
        assert agent.sessions[comp].seat_due["by"] == "tag"
        del agent._profile_gated
        for sid in (comp, db, crew):
            await person.call("kill", id=sid)


async def test_no_seat_carrying_tags_means_no_tag_due(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _tl(person, tmp_path, "db", seat={"trigger": "asks"})
        crew = await _crew(person, tmp_path, "db")
        _end(agent, sid)
        _needs(agent, tmp_path, ["TD-801"])
        await agent._keep_running(now)
        assert agent.sessions[sid].seat_due is None
        for s in (sid, crew):
            await person.call("kill", id=s)


async def test_a_question_holds_the_tagging_seats_due_as_asks_and_tag_follows(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid, crew = await _tl(person, tmp_path, "db"), await _crew(person, tmp_path, "db")
        rec = agent.sessions[sid]
        _end(agent, sid)
        _needs(agent, tmp_path, ["TD-801"])
        agent._profile_gated = lambda *a: True
        rec.asks_waiting = lambda **kw: 1
        await agent._keep_running(now)
        assert rec.seat_due["by"] == "asks", "a question waits: asks first"
        await agent._keep_running(now + timedelta(minutes=1))
        assert rec.seat_due["by"] == "asks", "a question left standing still holds it"
        rec.asks_waiting = lambda **kw: 0
        await agent._keep_running(now)
        assert rec.seat_due["by"] == "tag" and rec.seat_due["ids"] == ["TD-801"], "then tag"
        rec.asks_waiting = lambda **kw: 1
        await agent._keep_running(now)
        assert rec.seat_due["by"] == "asks" and "ids" not in rec.seat_due, "a standing tag due becomes asks"
        del agent._profile_gated
        for s in (sid, crew):
            await person.call("kill", id=s)


async def test_an_idle_tagging_seat_with_a_tag_due_is_closed_and_filled_an_asks_due_holds_it(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid, crew = await _tl(person, tmp_path, "db"), await _crew(person, tmp_path, "db")
        rec = agent.sessions[sid]
        _needs(agent, tmp_path, [])
        rec.asks_waiting = lambda **kw: 1
        _idle(agent, sid, now)
        await agent._keep_running(now)
        assert rec.seat_due["by"] == "asks" and rec.state == "idle", "an asks due holds an idle seat"
        rec.asks_waiting = lambda **kw: 0
        _needs(agent, tmp_path, ["TD-801"])
        await agent._keep_running(now)
        assert rec.state == "closed" and rec.seat_due["by"] == "tag", "a tag due is the next fill's"
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert new is not rec and [e["ids"] for e in new.seat_filled] == [["TD-801"]]
        for s in (sid, crew):
            await person.call("kill", id=s)


async def test_an_asks_fill_of_a_tagging_seat_writes_no_seat_filled_entry(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid, crew = await _tl(person, tmp_path, "db"), await _crew(person, tmp_path, "db")
        rec = agent.sessions[sid]
        _end(agent, sid)
        _needs(agent, tmp_path, ["TD-801"])
        rec.asks_waiting = lambda **kw: 1
        await agent._keep_running(now)
        new = agent.sessions[sid]
        assert new is not rec and new.seat_filled == [], "an asks fill carries no cause, as today"
        for s in (sid, crew):
            await person.call("kill", id=s)


def _rec(sid: str, root: str, **kw) -> Session:
    """A record of `root` for the tagging-seat helpers, read directly (TD-776): a good tagging seat
    unless `kw` says otherwise."""
    r = Session(id=sid, name=sid, kind="interactive", adapter="shell", dir=root)
    r.repo, r.team, r.state = root, "db", "working"
    r.seat, r.supervised, r.unattended = {"trigger": "asks", "tags": True}, True, True
    for k, v in kw.items():
        setattr(r, k, v)
    return r


async def test_a_repo_with_no_reading_yet_keeps_a_standing_tag_due(agent, tmp_path):
    """*A repo with no reading yet changes nothing* (TD-776): a ledger reading with no `needs_team`
    leaves a seat's `tag` due as it stands."""
    await park_ticks(agent)
    root = str(tmp_path)
    due = {"at": "2026-10-01T00:00:00+00:00", "by": "tag", "ids": ["TD-801"]}
    seat = _rec("tl", root, seat_due=due)
    agent._repos[root] = {"ledger": {"declared_teams": ["db"]}}
    assert agent._tag_cause(seat, [seat]) is due


async def test_the_same_uncovered_ids_keep_the_dues_first_at(agent, tmp_path):
    """Two ticks over the same uncovered ids: the second returns the first's due, `at` and all
    (TD-776), so a standing due is not made new each tick."""
    await park_ticks(agent)
    root = str(tmp_path)
    seat = _rec("tl", root)
    _needs(agent, tmp_path, ["TD-801", "TD-802"], declared=("db",))
    first = agent._tag_cause(seat, [seat])
    assert first["ids"] == ["TD-801", "TD-802"]
    seat.seat_due = {**first, "at": "2026-10-01T00:00:00+00:00"}
    assert agent._tag_cause(seat, [seat]) is seat.seat_due


@pytest.mark.parametrize(
    "bad",
    [
        {"supervised": False},
        {"unattended": False},
        {"superseded_by": "tl-next"},
        {"suspended": {"at": "2026-10-16T00:00:00+00:00", "by": "paul", "why": "identity alarm"}},
    ],
    ids=["unsupervised", "attended", "superseded", "suspended"],
)
async def test_only_a_supervised_unattended_current_unsuspended_seat_is_the_tagging_seat(agent, tmp_path, bad):
    """Each of `_tagging_seat`'s seat filters (TD-776): a candidate that fails one, listed before a
    good one of the same team, is passed over, and gets no `tag` due."""
    await park_ticks(agent)
    root = str(tmp_path)
    worse, good = _rec("tl-bad", root, **bad), _rec("tl-good", root)
    _needs(agent, tmp_path, ["TD-801"], declared=("db",))
    records = [worse, good]
    assert agent._tagging_seat(root, records) is good
    assert agent._tag_cause(worse, records) is None
    assert agent._tag_cause(good, records)["ids"] == ["TD-801"]


def test_filled_for_names_a_tag_causes_ids():
    from sessionorc.agent_tick import filled_for

    assert filled_for({"by": "tag", "ids": ["TD-801", "TD-802"]}) == (
        "[shiftlead] you are filled for: tag — TD-801, TD-802"
    )
