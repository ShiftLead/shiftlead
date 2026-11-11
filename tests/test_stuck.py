"""Stuck work, open asks (design §6 rule 13 *Stuck work*, TD-1470, built by TD-1496 slice 1): an open `ask` to a
session that no addressee has been able to act on for longer than `STUCK_ASK_AFTER` is kept on `host.json` as
`stuck`, its reason the first actor's and its clock the newest moment anything moved; it drops the tick an
actor acts. A steer, an ask to the person and one a seat passed up are never read; a person's own session is
passed over."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import hosts, mail, models, stuck, workorders
from sessionorc import ledgerboard as lb
from sessionorc.client import LocalClient
from sessionorc.store import HostStore

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
WAIT = mail.STUCK_ASK_AFTER


def _z(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def rec(n: str = "tl", state: str = "idle", **kw) -> models.Session:
    s = models.Session(id=f"ao-{n}", name=n, kind="claude", adapter="claude-code", dir="/w", state=state)
    s.supervised, s.unattended, s.team = True, True, "beta"
    s.since = _z(NOW - timedelta(hours=3))
    s.created = _z(NOW - timedelta(hours=5))
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def ask(mid: str = "m-1", to: tuple[str, ...] = ("ao-tl",), kind: str = "ask", **kw) -> models.MailEntry:
    e = models.MailEntry(id=mid, from_="ao-w", to=list(to), at=_z(NOW - timedelta(hours=2)), kind=kind, text="q")
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def judge(r, stamp, *, unfillable=None, open_at=None, clock=None):
    return stuck.judge(
        r,
        r.id if r is not None else "ao-gone",
        stamp,
        unfillable=unfillable or {},
        open_at=open_at or NOW - timedelta(hours=2),
        idle_clock=clock,
        now=NOW,
    )


@pytest.mark.unit
def test_open_asks_reads_asks_to_sessions_once_and_never_a_steer_a_person_ask_or_a_passed_up_one():
    a, b = rec("a"), rec("b")
    both = ask("m-both", to=("ao-a", "ao-b"))
    a.inbox = [both, ask("m-steer", kind="steer"), ask("m-person", to=(models.PERSON,)), ask("m-up", passed_up="T")]
    b.inbox = [both, ask("m-closed", closed_reason="replied")]
    assert [e.id for e in stuck.open_asks({"ao-a": a, "ao-b": b})] == ["m-both"]


@pytest.mark.unit
def test_a_working_actor_acts_and_an_idle_one_with_a_live_shell_acts():
    assert judge(rec(state="working"), {"state": "working"}).acting
    shell = rec(shells=[{"id": "b1", "since": _z(NOW - timedelta(minutes=5))}])
    assert judge(shell, {"state": "idle"}).acting, "a live background shell is working on its own (§4.2)"


@pytest.mark.unit
def test_an_idle_actor_is_clocked_from_its_read_and_reads_its_own_idle_start():
    r = rec()
    read = NOW - timedelta(minutes=90)
    a = judge(r, {"state": "idle"}, clock=read)
    assert not a.acting and a.since == read
    assert a.reason == {"state": "idle", "since": r.since}, "the words name its own idle start"
    ended = rec(shells_at=_z(NOW - timedelta(minutes=1)))
    assert judge(ended, {"state": "idle"}, clock=read).since == NOW - timedelta(minutes=1), "a shell's grace"


@pytest.mark.unit
def test_a_stall_needs_two_ticks_and_is_clocked_from_when_nothing_new_began():
    assert judge(rec(state="stalled?", stalled_ticks=1), {"state": "working"}).acting
    began = NOW - timedelta(minutes=20)
    a = judge(rec(state="stalled?", stalled_ticks=2, work_at=_z(began), screen_at=_z(began)), {"state": "working"})
    assert not a.acting and a.reason == {"state": "stalled", "since": _z(began)} and a.since == began


@pytest.mark.unit
def test_a_fillable_ended_seat_acts_and_an_unfillable_one_reads_its_word():
    seat = rec(state="exited", seat={"trigger": "asks"})
    assert judge(seat, {"state": "ended"}).acting, "rule 3 fills it for the question"
    a = judge(seat, {"state": "ended"}, unfillable={"ao-tl": "restart ceiling"})
    assert not a.acting and a.reason == {"state": "unfillable", "why": "restart ceiling"}
    held = rec(state="exited", seat={"trigger": "asks"}, stop_held={"at": "T", "team": "beta"})
    assert not judge(held, {"state": "held"}).acting


@pytest.mark.unit
def test_a_reason_is_the_stamp_and_every_figure_is_floored_at_the_open_time():
    r = rec(state="limited", since=_z(NOW - timedelta(hours=9)))
    a = judge(r, {"state": "limited", "by": "ao-tl"})
    assert a.reason["state"] == "limited" and a.since == NOW - timedelta(hours=2)
    gone = judge(None, {"state": "gone", "by": "ao-gone"})
    assert gone.reason["state"] == "gone" and gone.since == NOW - timedelta(hours=2)


@pytest.mark.unit
def test_reading_is_stuck_past_the_wait_with_the_first_actor_and_never_for_the_persons_own_alone():
    lim = judge(rec("a", state="limited"), {"state": "limited"})
    gone = judge(None, {"state": "gone"})
    got = stuck.reading([lim, gone], NOW, WAIT)
    assert got["reason"]["state"] == "limited" and got["actor"]["id"] == "ao-a" and got["actor"]["more"] == 1
    assert got["since"] == _z(NOW - timedelta(hours=2))
    assert stuck.reading([lim], NOW - timedelta(minutes=61), WAIT) is None, "not yet past the wait"
    own = rec("me", team=None, unattended=False, supervised=False, by_person=True)
    assert stuck.reading([judge(own, {"state": "idle"})], NOW, WAIT) is None, "the person is already there"
    got = stuck.reading([judge(own, {"state": "idle"}), lim], NOW, WAIT)
    assert got["actor"]["id"] == "ao-a" and got["actor"]["more"] == 0, "a person's own session is passed over"
    assert stuck.reading([lim, judge(rec("w", state="working"), {"state": "working"})], NOW, WAIT) is None


@pytest.mark.unit
def test_a_fresh_fills_copy_is_clocked_from_its_created_and_an_unread_copy_from_since():
    fill = rec(created=_z(NOW - timedelta(minutes=10)))
    fill.inbox = [ask(read_at=_z(NOW - timedelta(hours=2)))]
    assert stuck.ask_idle_clock(fill, "m-1") == NOW - timedelta(minutes=10)
    unread = rec()
    unread.inbox = [ask()]
    assert stuck.ask_idle_clock(unread, "m-1") == NOW - timedelta(hours=3)


@pytest.mark.unit
def test_host_store_drops_a_malformed_stuck_or_stuck_open_entry(tmp_path):
    store = HostStore(tmp_path / "host.json")
    good = {"since": "2026-11-11T10:00:00Z", "reason": {"state": "limited"}, "actor": {"id": "ao-a"}}
    store.save(
        {
            "teams": {},
            "stuck": {"ask:m-1": good, "ask:m-2": {"since": 3}, "pr:9": good, "board:k": good},
            "stuck_open": {
                "board:k": {"at": "2026-11-11T10:00:00Z", "repo": "shiftlead", "holder": True},
                "board:j": {"at": "nope", "repo": "shiftlead"},
                "board:h": {"at": "2026-11-11T10:00:00Z", "repo": "shiftlead", "asked": "yes"},
            },
        }
    )
    got = store.load()
    assert list(got["stuck"]) == ["ask:m-1"], "a board entry carries its repo; no key but ask: and board:"
    assert list(got["stuck_open"]) == ["board:k"]


async def _seat_and_worker(person, tmp_path):
    async def mk(n: str, **kw):
        d = tmp_path / n
        d.mkdir(exist_ok=True)
        kw.setdefault("unattended", True)
        got = await person.call("create", name=n, dir=str(d), adapter="agentshell", argv=["bash", "--norc"], **kw)
        return got["id"]

    return await mk("rv", team="beta", seat={"trigger": "asks"}), await mk("w", team="beta")


@pytest.mark.integration
async def test_the_pass_keeps_a_stuck_ask_and_drops_it_the_tick_its_seat_acts(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        rv, w = await _seat_and_worker(person, tmp_path)
        async with LocalClient(caller=w) as c:
            got = await c.call("msg", to=rv, text="which test covers this?", kind="ask", about="TD-9")
        mid = got["entry"]["id"]
        seat = agent.sessions[rv]
        seat.state, seat.limited_reset = "limited", None
        later = datetime.now(UTC) + WAIT + timedelta(minutes=1)
        await agent._stuck_pass(datetime.now(UTC))
        assert "stuck" not in agent._host_rec, "not past the wait"
        await agent._stuck_pass(later)
        row = agent._host_rec["stuck"][f"ask:{mid}"]
        assert row["reason"]["state"] == "limited" and row["actor"]["id"] == rv and row["actor"]["more"] == 0
        assert HostStore(agent.host_store.path).load()["stuck"][f"ask:{mid}"]["since"] == row["since"], "on disk"
        assert (await agent.rpc_host())["stuck"][f"ask:{mid}"]["reason"]["state"] == "limited", "served"
        saves = []
        real = agent.host_store.save
        agent.host_store.save = lambda rec: saves.append(rec) or real(rec)
        await agent._stuck_pass(later + timedelta(minutes=5))
        assert not saves, "a reason that stands is not rewritten each tick"
        assert "at" not in agent._host_rec["stuck"][f"ask:{mid}"]["reason"]
        seat.state = "working"
        await agent._stuck_pass(later)
        assert "stuck" not in agent._host_rec, "dropped the tick an actor acts"


@pytest.mark.integration
async def test_the_pass_reads_no_steer_and_keeps_a_board_entry_as_stored(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    monkeypatch.setattr(hosts.Host, "repos", lambda self: ["/repos/shiftlead"])
    agent._repos = {}  # its repo not yet read: its board entry stands as stored
    board = {"since": "2026-11-11T10:00:00Z", "reason": {"state": "no_lane"}, "repo": "shiftlead"}
    agent._host_rec["stuck"] = {"board:abc": board}
    async with LocalClient() as person:
        rv, w = await _seat_and_worker(person, tmp_path)
        async with LocalClient(caller=w) as c:
            await c.call("msg", to=rv, text="dropping it", kind="steer", default="drop it")
        agent.sessions[rv].state = "limited"
        await agent._stuck_pass(datetime.now(UTC) + timedelta(hours=3))
        assert agent._host_rec["stuck"] == {"board:abc": board}


# -- a decided board line waiting on a session (TD-1496 slice 2) -------------------------------------------------

ROOT = "/repos/fx"
LINE = "decide 2026-11-11 (n/a) — **Keep it?** Context: TD-7. Due: 2026-11-11. Decided: keep (2026-11-11)."
KEY = workorders.key(LINE)
OWAIT = mail.STUCK_ORDER_AFTER


def board(*, case: str | None = "current", lines: tuple[str, ...] = (LINE,), carried: tuple[str, ...] = ()) -> dict:
    items = [
        {"key": workorders.key(t), "text": t, "decided": {"text": "keep"}, "kind": "decide", "refs": lb.item_refs(t)}
        for t in lines
    ]
    b = {"fetch_case": case, "items": items, "carried": [{"key": k} for k in carried]}
    return {"name": "fx", "root": ROOT, "boards": {"boards": [b]}}


def member(n: str, state: str = "idle", **kw) -> models.Session:
    s = rec(n, state, repo=ROOT, lane=["free-pick"], **kw)
    return s


def claimed(ref: str, at: datetime) -> models.ProgressEntry:
    return models.ProgressEntry(ref=ref, status="claimed", at=_z(at))


@pytest.fixture
def home(agent, monkeypatch):
    """A parked home with one repo `fx` on the roster and its records in `agent.sessions`."""
    monkeypatch.setattr(hosts.Host, "repos", lambda self: [ROOT, "/repos/other"])
    agent._repos = {ROOT: board()}
    agent._host_rec.pop("stuck", None)
    agent._host_rec.pop("stuck_open", None)
    return agent


def put(agent, *records: models.Session) -> None:
    for r in records:
        r.host = agent.host  # this home's own records, never unreachable
    agent.sessions.clear()
    agent.sessions.update({r.id: r for r in records})


@pytest.mark.unit
def test_board_read_and_opened_follow_the_clock():
    assert stuck.board_read(None) == "unread" and stuck.board_read({"boards": {"error": "x"}}) == "unread"
    assert stuck.board_read(board(case="skipped")) == "fallback" and stuck.board_read(board(case=None)) == "fallback"
    assert stuck.board_read(board(case="behind")) == "good"
    first = stuck.opened(None, "fx", None, NOW)
    assert first == {"at": _z(NOW), "repo": "fx"}, "first read: that tick"
    claim = stuck.opened(first, "fx", NOW + timedelta(minutes=5), NOW + timedelta(minutes=6))
    assert claim["at"] == _z(NOW + timedelta(minutes=5)) and claim["holder"] is True
    back = stuck.opened(claim, "fx", NOW - timedelta(hours=3), NOW + timedelta(minutes=7))
    assert back["at"] == claim["at"], "a later re-claim never moves at back"
    rel = stuck.opened(claim, "fx", None, NOW + timedelta(minutes=30))
    assert rel["at"] == _z(NOW + timedelta(minutes=30)) and "holder" not in rel, "the release, once"
    assert stuck.opened(rel, "fx", None, NOW + timedelta(hours=1)) == rel, "the next tick moves nothing"
    assert stuck.opened({**first, "asked": True}, "fx", None, NOW, asked=True)["asked"] is True


@pytest.mark.unit
def test_team_reason_reads_a_team_none_of_whose_crew_is_live():
    done = {"at": _z(NOW)}
    a = member("a", "exited", out_of_work=done, lane_seen={"ids": [KEY]})
    b = member("b", "exited", out_of_work=done)
    by_person = member("p", "closed", closer={"by": "person", "at": _z(NOW)})
    assert stuck.team_reason("beta", [by_person], None, KEY)["held"] == {"why": "stopped"}, "a person's Stop"
    assert stuck.team_reason("beta", [a, b], None, KEY) == {
        "state": "team",
        "team": "beta",
        "held": {"why": "wound_down"},
    }, "wound down with the line seen and unpicked"
    assert stuck.team_reason("beta", [a, b], None, "board:zz")["held"] == {"why": "stopped"}, "not running"
    mark = {"members": {"a": [KEY]}, "held": {"why": "day", "count": 3}}
    assert stuck.team_reason("beta", [a, b], mark, KEY)["held"] == {"why": "day", "count": 3}
    assert "held" not in stuck.team_reason("beta", [a, b], {"members": {"a": [KEY]}}, KEY), "waits for your Start"
    held_only = {"members": {}, "seats_held": {"ao-rv": 1}}
    assert stuck.team_reason("beta", [a, b], held_only, KEY)["held"] == {"why": "wound_down"}, "a held-only mark"
    crashed = member("c", "exited", ended={"why": "crash"})
    assert stuck.team_reason("beta", [crashed], None, KEY) is None, "crashed out: each member's own state"
    assert stuck.team_reason("beta", [a, member("live")], None, KEY) is None, "a live member: read each"


@pytest.mark.integration
async def test_an_idle_claimant_reads_its_own_idle_start_while_the_clock_keeps_its_claim(home):
    await park_ticks(home)
    claim = NOW - timedelta(minutes=30)
    w = member("w", since=_z(NOW - timedelta(minutes=10)), progress=[claimed(KEY, claim)])
    put(home, w)
    home._host_rec["stuck_open"] = {KEY: {"at": _z(NOW - timedelta(hours=2)), "repo": "fx"}}
    await home._stuck_pass(NOW)
    assert home._host_rec["stuck_open"][KEY] == {"at": _z(claim), "repo": "fx", "holder": True}
    assert "stuck" not in home._host_rec
    later = claim + OWAIT + timedelta(minutes=1)
    await home._stuck_pass(later)
    row = home._host_rec["stuck"][KEY]
    assert row["since"] == _z(claim) and row["repo"] == "fx", "clocked from the claim"
    assert row["reason"] == {"state": "idle", "since": w.since}, "the words name its own idle start"
    assert row["actor"]["id"] == "ao-w"
    w.state = "working"
    await home._stuck_pass(later)
    assert "stuck" not in home._host_rec, "dropped the tick an actor acts"


@pytest.mark.integration
async def test_two_holders_are_both_actors_and_a_seat_holding_the_lease_is_one(home):
    await park_ticks(home)
    claim = NOW - timedelta(minutes=90)
    a = member("a", state="working", progress=[claimed(KEY, claim)])
    rv = rec("rv", state="limited", repo=ROOT, seat={"trigger": "asks"}, progress=[claimed(KEY, claim)])
    put(home, a, rv)
    home._host_rec["stuck_open"] = {KEY: {"at": _z(NOW - timedelta(hours=2)), "repo": "fx"}}
    await home._stuck_pass(NOW)
    assert "stuck" not in home._host_rec, "one of two holders acting: not stuck"
    a.state = "limited"
    await home._stuck_pass(NOW)
    row = home._host_rec["stuck"][KEY]
    assert row["actor"]["more"] == 1 and {row["actor"]["id"]} <= {"ao-a", "ao-rv"}
    a.progress = []
    await home._stuck_pass(NOW)
    assert home._host_rec["stuck_open"][KEY]["holder"] is True, "one of two dropping is no release"
    assert home._host_rec["stuck"][KEY]["actor"]["id"] == "ao-rv", "the seat holding the lease is the actor"


@pytest.mark.integration
async def test_a_released_line_is_clocked_from_the_release_and_goes_back_to_its_lanes(home):
    await park_ticks(home)
    w = member("w", progress=[claimed(KEY, NOW - timedelta(hours=3))])
    other = member("o", state="limited")
    put(home, w, other)
    home._host_rec["stuck_open"] = {KEY: {"at": _z(NOW - timedelta(hours=4)), "repo": "fx"}}
    await home._stuck_pass(NOW)
    assert home._host_rec["stuck"][KEY]["actor"]["id"] == "ao-w", "the holder is the only actor"
    w.progress = [models.ProgressEntry(ref=KEY, status="dropped", at=_z(NOW))]
    rel = NOW + timedelta(minutes=1)
    await home._stuck_pass(rel)
    assert home._host_rec["stuck_open"][KEY] == {"at": _z(rel), "repo": "fx"}, "the release, its tick's instant"
    assert "stuck" not in home._host_rec, "not stuck at once after the release"
    await home._stuck_pass(rel + OWAIT + timedelta(minutes=1))
    assert home._host_rec["stuck_open"][KEY]["at"] == _z(rel), "moved once"
    row = home._host_rec["stuck"][KEY]
    assert row["since"] == _z(rel) and row["actor"]["more"] == 1, "its lanes' records are its actors after"
    w.state = "exited"
    other.progress = [claimed(KEY, NOW - timedelta(hours=20))]
    await home._stuck_pass(rel + OWAIT + timedelta(minutes=2))
    assert "holder" not in home._host_rec["stuck_open"][KEY], "a lease past LEASE_TTL holds nothing"


@pytest.mark.integration
async def test_a_team_held_at_day_reads_that_reason_and_a_line_no_lane_takes_reads_no_lane(home):
    await park_ticks(home)
    done = {"at": _z(NOW - timedelta(hours=4))}
    put(home, member("a", "exited", out_of_work=done), member("b", "exited", out_of_work=done))
    home._host_rec.setdefault("teams", {})["beta"] = {
        "work_waiting": {"members": {"a": [KEY]}, "held": {"why": "day", "count": 3}}
    }
    await home._stuck_pass(NOW)
    await home._stuck_pass(NOW + OWAIT + timedelta(minutes=1))
    row = home._host_rec["stuck"][KEY]
    assert row["reason"] == {"state": "team", "team": "beta", "held": {"why": "day", "count": 3}}
    assert "actor" not in row, "a team's names no actor"
    home._host_rec["teams"].pop("beta")
    put(home, rec("solo", repo="/repos/other", lane=["free-pick"]))
    await home._stuck_pass(NOW + OWAIT + timedelta(minutes=2))
    assert home._host_rec["stuck"][KEY]["reason"] == {"state": "no_lane"}


@pytest.mark.integration
async def test_an_unread_or_fallback_repo_keeps_its_lines_and_a_repo_off_the_roster_drops_them(home):
    await park_ticks(home)
    gone = workorders.key("act 2026-11-11 (n/a) — **Gone.** Due: 2026-11-11.")
    arch = workorders.key("act 2026-11-11 (n/a) — **Archived.** Due: 2026-11-11.")
    stored = {"since": "2026-11-11T09:00:00Z", "reason": {"state": "limited"}, "repo": "fx"}
    opened = {"at": "2026-11-11T08:00:00Z", "repo": "fx", "holder": True}
    other = {**stored, "repo": "other"}
    left = {**stored, "repo": "left"}
    home._host_rec["stuck"] = {KEY: stored, gone: stored, arch: stored, "board:o1": other, "board:x": left}
    home._host_rec["stuck_open"] = {KEY: opened, gone: opened, arch: opened, "board:o1": {**opened, "repo": "other"}}
    put(home, member("w", state="working", progress=[claimed(KEY, NOW)]))
    home._repos = {}  # a restart before the first pass, or a raised one: no reading
    await home._stuck_pass(NOW)
    assert home._host_rec["stuck"][KEY] == stored, "kept exactly as stored though its claimant works"
    assert "board:x" not in home._host_rec["stuck"], "a repo that left the roster drops its entries"
    home._repos = {ROOT: {**board(), "boards": {"error": "unreadable", "boards": []}}}
    await home._stuck_pass(NOW)
    assert home._host_rec["stuck_open"][KEY] == opened, "an errored board keeps the clock"
    home._repos = {ROOT: board(case="skipped", lines=(LINE,), carried=(arch,))}
    await home._stuck_pass(NOW)
    assert gone in home._host_rec["stuck"], "a fallback read never closes a line absent from it"
    assert arch not in home._host_rec["stuck"] and arch not in home._host_rec["stuck_open"], "archived: closed"
    assert home._host_rec["stuck"][KEY] == stored, "nor reads one, nor opens one"
    assert home._host_rec["stuck"]["board:o1"] == other, "the unread repo's entry is kept as stored"
    home._repos = {ROOT: board()}
    await home._stuck_pass(NOW)
    assert KEY not in home._host_rec["stuck"] and gone not in home._host_rec["stuck"], "dropped on a good read"
    assert set(home._host_rec["stuck"]) == {"board:o1"} and set(home._host_rec["stuck_open"]) == {KEY, "board:o1"}
    assert all(k.startswith(("ask:", "board:")) for k in home._host_rec["stuck"])


@pytest.mark.unit
def test_lane_records_go_by_teams_order_then_id_and_a_blank_source_claim_is_clocked():
    a, z = member("a", team="zeta"), member("b", team="alpha")
    seat = rec("rv", repo=ROOT, lane=["free-pick"], seat={"trigger": "asks"})
    out = member("x", closed_for={"why": "sit_out"})
    records = {r.id: r for r in (a, z, seat, out)}
    entry = workorders.entry({"id": KEY, "text": LINE})
    assert stuck.lane_records(ROOT, entry, records, ["zeta", "alpha"]) == ["ao-a", "ao-b"], "the teams' order"
    assert stuck.lane_records(ROOT, entry, records) == ["ao-b", "ao-a"], "by name where no order is known"
    w = member("w", progress=[models.ProgressEntry(ref=KEY, status="claimed", at=_z(NOW), source="")])
    assert stuck.claim_at(w, KEY) == NOW, "a claim lease_holders counts is clocked from its own at"


# -- the person's question mutes a line, and a reason that names its own end waits (TD-1496 slice 3) -------------


def person_ask(mid: str = "m-p", about: str = "TD-7", repo: str | None = "fx", kind: str = "ask", **kw):
    e = models.MailEntry(id=mid, from_="ao-w", to=[models.PERSON], at=_z(NOW), kind=kind, text="q", about=about)
    e.repo = repo
    for k, v in kw.items():
        setattr(e, k, v)
    return e


@pytest.mark.unit
def test_opened_sets_asked_and_moves_at_once_on_the_answer():
    first = stuck.opened(None, "fx", None, NOW, asked=True)
    assert first == {"at": _z(NOW), "repo": "fx", "asked": True}, "first read with a question open: that tick"
    still = stuck.opened(first, "fx", None, NOW + timedelta(hours=2), asked=True)
    assert still == first, "while it counts nothing moves"
    later = NOW + timedelta(hours=3)
    answered = stuck.opened(still, "fx", None, later)
    assert answered == {"at": _z(later), "repo": "fx"}, "the answer: its tick, asked cleared"
    assert stuck.opened(answered, "fx", None, later + timedelta(hours=1)) == answered, "once"
    both = {"at": _z(NOW), "repo": "fx", "holder": True, "asked": True}
    once = stuck.opened(both, "fx", None, later)
    assert once == {"at": _z(later), "repo": "fx"}, "a release and an answer on one tick move at once, clear both"
    assert stuck.open_shape_ok(KEY, both), "a restart keeps both markers"


@pytest.mark.unit
def test_in_snoozed_fold_answers_as_the_inbox_draws_it():
    from shiftlead.ui.inbox import inbox_sections

    cases = {
        "m-ahead": {"snoozed_until": _z(NOW + timedelta(hours=1))},
        "m-past": {"snoozed_until": _z(NOW - timedelta(hours=1))},
        "m-bad": {"snoozed_until": "not a time"},
        "m-look": {"snoozed_for": "m-handed"},
        "m-none": {},
        "m-steer": {"kind": "steer", "snoozed_until": _z(NOW + timedelta(hours=1))},
    }
    entries = [person_ask(mid, **kw) for mid, kw in cases.items()]
    drawn = {e["id"] for e in inbox_sections([e.to_dict() for e in entries], now=NOW)["snoozed"]}
    assert {e.id for e in entries if stuck.in_snoozed_fold(e, NOW)} == drawn == {"m-ahead", "m-look", "m-steer"}


@pytest.mark.unit
def test_asked_refs_filters_by_repo_and_the_snoozed_fold():
    roots = {"fx": ROOT, "other": "/repos/other", "reg-name": "/repos/fx-dir"}
    box = [
        person_ask("m-1", about="td-7"),
        person_ask("m-2", about="TD-8", repo=None),  # no envelope repo: counts for no line
        person_ask("m-3", about="TD-9", repo="other"),
        person_ask("m-4", about="TD-10", snoozed_until=_z(NOW + timedelta(hours=1))),
        person_ask("m-5", about="TD-11", snoozed_for="m-h"),
        person_ask("m-6", about="TD-12", kind="steer", paused_at=_z(NOW)),
        person_ask("m-7", about="TD-13", closed_reason="replied"),
        person_ask("m-8", about="fx#TD-14"),  # a repo-qualified about is no bare TD-n
        person_ask("m-9", about="TD-15", repo="nowhere"),
    ]
    assert stuck.asked_refs(box, ROOT, roots, NOW) == {"TD-007", "TD-012"}
    assert stuck.asked_refs([person_ask(repo="reg-name")], "/repos/fx-dir", roots, NOW) == {"TD-007"}, (
        "a registry name that differs from its directory's"
    )
    order = {"entry": {"refs": ["TD-7"]}}
    assert stuck.asked_about(order, {"TD-007"}), "td-7 and TD-7 are one entry"
    for refs in (["fx#TD-7"], ["PR #7"], []):
        assert not stuck.asked_about({"entry": {"refs": refs}}, {"TD-007"}), refs
    assert not stuck.asked_about(order, {"TD-008"}), "an ask about another entry"


@pytest.mark.unit
def test_waiting_until_is_the_earliest_instant_when_every_actor_names_one():
    def a(until=None, **kw):
        return stuck.Actor("ao-x", "", "x", until=until, **kw)

    soon, later = NOW + timedelta(minutes=10), NOW + timedelta(minutes=40)
    assert stuck.waiting_until([a(later), a(soon)], NOW, WAIT) == soon
    assert stuck.waiting_until([a(soon), a()], NOW, WAIT) is None, "one with no instant is a need"
    assert stuck.waiting_until([a(soon), a(own=True)], NOW, WAIT) == soon, "a person's own session passed over"
    assert stuck.waiting_until([a(NOW + WAIT + timedelta(minutes=1))], NOW, WAIT) is None, "further than the wait"
    assert stuck.waiting_until([a(NOW - timedelta(minutes=1))], NOW, WAIT) is None, "the instant passed"
    lim = rec("lim", "limited", limited_reset=_z(soon))
    assert stuck.comes_back({"state": "limited"}, lim) == soon
    assert stuck.comes_back({"state": "limited"}, rec("l2", "limited")) is None, "no reset known"
    assert stuck.comes_back({"state": "scheduled", "start_at": _z(soon)}) == soon
    assert stuck.comes_back({"state": "gated", "gate": {"profile": "p", "resets": _z(soon)}}) == soon
    started = NOW - timedelta(minutes=20)
    early = {"state": "team", "team": "beta", "held": {"why": "early", "started": _z(started)}}
    assert stuck.comes_back(early) == started + timedelta(minutes=30)
    assert stuck.comes_back({"state": "team", "held": {"why": "usage", "profile": "p"}}) is None, "usage, no resets"
    assert stuck.comes_back({"state": "team", "held": {"why": "until", "until": _z(soon)}}) == soon
    assert stuck.comes_back({"state": "idle"}) is None


@pytest.mark.integration
async def test_a_line_the_person_is_asked_about_is_muted_and_clocked_from_the_answer(home):
    await park_ticks(home)
    w = member("w", state="limited")
    put(home, w)
    home._host_rec["stuck_open"] = {KEY: {"at": _z(NOW - timedelta(hours=3)), "repo": "fx"}}
    await home._stuck_pass(NOW)
    assert KEY in home._host_rec["stuck"], "stuck before the question"
    q = person_ask("m-q", about="TD-7")
    home.person_inbox.append(q)
    await home._stuck_pass(NOW)
    assert "stuck" not in home._host_rec, "the person's question mutes the line"
    assert home._host_rec["stuck_open"][KEY] == {"at": _z(NOW - timedelta(hours=3)), "repo": "fx", "asked": True}
    later = NOW + timedelta(hours=2)
    q.closed_reason = "replied"
    await home._stuck_pass(later)
    assert home._host_rec["stuck_open"][KEY] == {"at": _z(later), "repo": "fx"}, "clocked from the answer"
    assert "stuck" not in home._host_rec, "not stuck at once"
    await home._stuck_pass(later + OWAIT + timedelta(minutes=1))
    assert home._host_rec["stuck"][KEY]["since"] == _z(later), "one wait after the answer"
    home.person_inbox.append(person_ask("m-s", about="TD-7", snoozed_until=_z(later + timedelta(days=1))))
    home.person_inbox.append(person_ask("m-o", about="TD-7", repo="other"))
    await home._stuck_pass(later + OWAIT + timedelta(minutes=2))
    assert KEY in home._host_rec["stuck"], "a snoozed ask, and one from another repo, mute nothing"
    home.person_inbox[:] = [e for e in home.person_inbox if e.id not in ("m-q", "m-s", "m-o")]


@pytest.mark.integration
async def test_waiting_until_is_served_beside_the_stuck_row_and_never_stored(home):
    await park_ticks(home)
    reset = NOW + timedelta(minutes=10)
    put(home, member("w", state="limited", limited_reset=_z(reset)))
    home._host_rec["stuck_open"] = {KEY: {"at": _z(NOW - timedelta(hours=3)), "repo": "fx"}}
    await home._stuck_pass(NOW)
    assert "waiting_until" not in home._host_rec["stuck"][KEY], "never stored"
    assert (await home.rpc_host())["stuck"][KEY]["waiting_until"] == _z(reset), "served with the reading"
    home.sessions["ao-w"].limited_reset = None
    await home._stuck_pass(NOW)
    assert "waiting_until" not in (await home.rpc_host())["stuck"][KEY], "no reset known: a need"
