"""One repo's pass over its audits, act 6 of the tick (design §4.9c *Audits start on a clock*, TD-2053)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sessionorc.models import ProgressEntry, Session
from shiftlead import stage_audit, stage_audit_pass, stage_tick
from shiftlead.stage_audit_pass import AuditFacts, AuditReach
from shiftlead.stage_fetch import SessionsRead
from shiftlead.stagerecord import StageStore

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
LEASE = "audit:t/docs"


def stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def root(tmp_path: Path) -> Path:
    origin, root = tmp_path / "o.git", tmp_path / "r"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "remote", "add", "origin", str(origin))
    git(root, "commit", "-q", "--allow-empty", "-m", "init")
    git(root, "push", "-q", "origin", "main")
    return root


@pytest.fixture
def store(root: Path) -> StageStore:
    s = StageStore(root)
    s.ensure_branch()
    return s


class World:
    """A reach whose every session started is named `s-<n>`, on a head and a count the test sets."""

    def __init__(self, *, head: str | None = "c0ffee", merged: int | None = 0, refuse: str | None = None) -> None:
        self.started: list[tuple[str, str, str | None, str | None]] = []
        self.claims: list[tuple[str, str]] = []
        self.ended: list[str] = []
        self.head, self.merged, self.refuse = head, merged, refuse
        self.counted: list[str] = []

    def reach(self) -> AuditReach:
        def start(team, key, base, came):
            self.started.append((team, key, base, came))
            return f"s-{len(self.started)}"

        def claim(holder, ref):
            self.claims.append((holder, ref))
            return self.refuse

        def merged_since(base):
            self.counted.append(base)
            return self.merged

        return AuditReach(start, claim, self.ended.append, lambda: self.head, merged_since)


def session(
    sid: str, *, state: str = "working", idle: timedelta = timedelta(minutes=5), claimed: bool = True
) -> Session:
    s = Session(id=sid, name=sid, dir="/r", kind="agent", adapter="claude-code", state=state, unattended=True)
    s.created = s.turn_at = stamp(NOW - idle)
    if claimed:
        s.progress = [ProgressEntry(ref=LEASE, at=stamp(NOW - timedelta(hours=1)))]
    return s


def flow(every: str = "10 merged-pull-requests") -> dict:
    return {"stages": [{"name": "build", "takes": "other"}], "audits": [{"name": "docs", "model": "m", "every": every}]}


def facts(every: str = "10 merged-pull-requests", **kw) -> AuditFacts:
    base = {"now": NOW, "started": ("t",), "docs": {"t": flow(every)}, "may_start": True}
    return AuditFacts(**{**base, **kw})


def one(store: StageStore, f: AuditFacts, w: World) -> stage_audit_pass.AuditStep:
    (got,) = stage_audit_pass.audit_pass(store, f, w.reach())
    return got


# -- a first run -----------------------------------------------------------------------------------------------------


def test_an_audit_with_no_run_starts_at_once_and_its_run_counts_from_the_head(store):
    w = World(head="c0ffee")
    got = one(store, facts(), w)
    assert got.act.name == "start" and got.act.case == "first" and got.made.made
    assert w.started == [("t", "docs", "c0ffee", None)] and w.claims == [("s-1", LEASE)]
    run = store.audit("t", "docs")
    assert (run["holder"], run["base"], run["offers"], run["started_at"]) == ("s-1", "c0ffee", 1, stamp(NOW))
    assert not got.tell


def test_a_team_not_started_or_not_free_to_start_runs_no_audit(store):
    w = World()
    assert stage_audit_pass.audit_pass(store, facts(started=()), w.reach()) == ()
    assert one(store, facts(may_start=False), w).act is None
    assert w.started == [] and store.audit("t", "docs") is None


def test_an_unreadable_head_starts_nothing_and_ends_nothing(store):
    w = World(head=None)
    got = one(store, facts(), w)
    assert got.act.name == "start" and not got.made.made and w.started == [] and w.ended == []


def test_a_refused_claim_ends_the_session_it_started_and_writes_no_run(store):
    w = World(refuse="held by another")
    got = one(store, facts(), w)
    assert not got.made.made and "held by another" in got.made.why
    assert w.ended == ["s-1"] and store.audit("t", "docs") is None


# -- a run that holds its lease --------------------------------------------------------------------------------------


def test_a_live_holder_keeps_the_run_and_no_count_is_read(store):
    store.put_audit("t", "docs", stage_audit.started("s-9", "c0ffee", NOW - timedelta(hours=1)))
    w = World(merged=50)
    got = one(store, facts(sessions={"s-9": session("s-9")}), w)
    assert got.act is None and w.started == [] and w.counted == []


def test_a_holder_on_a_node_not_read_is_no_reading(store):
    store.put_audit("t", "docs", stage_audit.started("s-9@n2", "c0ffee", NOW - timedelta(hours=1)))
    got = one(store, facts(), World())
    assert not got.read and got.act is None


# -- a lost run, offered again once, then rested ---------------------------------------------------------------------


def test_a_lost_run_is_offered_again_on_its_base_and_its_old_holder_is_ended(store):
    store.put_audit("t", "docs", stage_audit.started("s-9", "beef", NOW - timedelta(hours=1)))
    w = World(head="c0ffee")
    got = one(store, facts(), w)  # s-9 has no record: ended, so lost
    assert (got.act.name, got.act.case) == ("offer-again", "lost") and got.made.made
    assert w.started == [("t", "docs", "beef", "lost")] and w.ended == []  # gone: nothing to end
    run = store.audit("t", "docs")
    assert (run["holder"], run["base"], run["offers"]) == ("s-1", "beef", 2)


def test_a_lapsed_lease_whose_session_still_runs_is_ended_before_the_run_is_offered_again(store):
    store.put_audit("t", "docs", stage_audit.started("s-9", "beef", NOW - timedelta(hours=14)))
    s9 = session("s-9")
    s9.progress = [ProgressEntry(ref=LEASE, at=stamp(NOW - timedelta(hours=13)))]
    w = World()
    order = []
    base = w.reach()
    reach = AuditReach(
        lambda *a: order.append("start") or base.start(*a),
        base.claim,
        lambda h: order.append(f"end {h}"),
        base.head,
        base.merged_since,
    )
    (got,) = stage_audit_pass.audit_pass(store, facts(sessions={"s-9": s9}), reach)
    assert (got.act.name, got.act.case) == ("offer-again", "lost") and got.made.made
    assert order == ["end s-9", "start"] and store.audit("t", "docs")["holder"] == "s-1"


def test_a_run_whose_holder_moved_since_it_was_read_is_not_written(store):
    store.put_audit("t", "docs", stage_audit.started("s-9", "beef", NOW - timedelta(hours=1)))
    f, w = facts(), World()
    s = stage_audit_pass.reading_on(
        "t", "docs", store.audit("t", "docs"), stage_audit.clock("10 merged-pull-requests"), f, w.reach()
    )
    act = stage_audit.choose(store.audit("t", "docs"), stage_audit.clock("10 merged-pull-requests"), s, NOW)
    store.put_audit("t", "docs", stage_audit.started("s-8", "beef", NOW - timedelta(hours=1)))
    got = stage_audit_pass.make(
        store, "t", "docs", stage_audit.clock("10 merged-pull-requests"), act, s, f, w.reach(), was="s-9"
    )
    assert not got.made and w.started == [] and store.audit("t", "docs")["holder"] == "s-8"


def test_a_rest_whose_head_is_not_read_ends_nothing(store):
    run = {**stage_audit.started("s-9", "beef", NOW - timedelta(hours=5)), "offers": 2}
    store.put_audit("t", "docs", run)
    w = World(head=None)
    got = one(store, facts(sessions={"s-9": session("s-9", idle=timedelta(hours=3))}), w)
    assert got.act.name == "rest" and not got.made.made and w.ended == []


def test_a_silent_holder_is_ended_before_the_run_is_offered_again(store):
    store.put_audit("t", "docs", stage_audit.started("s-9", "beef", NOW - timedelta(hours=5)))
    w = World()
    got = one(store, facts(sessions={"s-9": session("s-9", idle=timedelta(hours=3))}), w)
    assert (got.act.name, got.act.case) == ("offer-again", "silent") and got.made.made
    assert w.ended == ["s-9"] and w.started == [("t", "docs", "beef", "silent")]


def test_lost_a_second_time_the_run_rests_from_the_head_and_the_person_is_told(store):
    run = {**stage_audit.started("s-9", "beef", NOW - timedelta(hours=1)), "offers": 2}
    store.put_audit("t", "docs", run)
    w = World(head="c0ffee")
    got = one(store, facts(), w)
    assert (got.act.name, got.act.case) == ("rest", "lost") and got.made.made and got.tell
    assert w.started == [] and w.ended == []
    rested = store.audit("t", "docs")
    assert rested["holder"] is None and rested["base"] == "c0ffee" and rested["ended"]["outcome"] == "lost"
    assert rested["started_at"] == stamp(NOW)


# -- the clock -------------------------------------------------------------------------------------------------------


def finished(started_at: datetime) -> dict:
    run = stage_audit.started("s-9", "beef", started_at)
    return stage_audit.finished(run, "nothing-found", "looked at the docs", started_at + timedelta(minutes=30))


def test_a_merged_pull_requests_clock_starts_once_its_count_is_reached(store):
    store.put_audit("t", "docs", finished(NOW - timedelta(days=3)))
    w = World(merged=9, head="c0ffee")
    assert one(store, facts(), w).act is None and w.counted == ["beef"]
    w.merged = 10
    got = one(store, facts(), w)
    assert got.act.name == "start" and got.made.made and w.started == [("t", "docs", "c0ffee", None)]
    assert store.audit("t", "docs")["base"] == "c0ffee"


def test_an_unread_count_starts_nothing(store):
    store.put_audit("t", "docs", finished(NOW - timedelta(days=3)))
    assert one(store, facts(), World(merged=None)).act is None


def test_a_days_clock_runs_from_the_last_start_and_reads_no_count(store):
    store.put_audit("t", "docs", finished(NOW - timedelta(hours=20)))
    w = World()
    assert one(store, facts("1 days"), w).act is None
    store.put_audit("t", "docs", finished(NOW - timedelta(hours=25)))
    assert one(store, facts("1 days"), w).act.name == "start" and w.counted == []


def test_a_clock_the_check_would_refuse_starts_nothing(store):
    got = one(store, facts("every tuesday"), World())
    assert got.act is None and store.audit("t", "docs") is None


# -- the repo's own refs ---------------------------------------------------------------------------------------------


def test_the_count_is_the_first_parent_commits_after_the_base_and_an_unreached_base_is_none(root):
    base = git(root, "rev-parse", "HEAD").strip()
    for n in range(3):
        git(root, "commit", "-q", "--allow-empty", "-m", f"#{n}")
    count = stage_audit_pass.merged_since(root, "HEAD")
    assert count(base) == 3
    assert count("0" * 40) is None
    assert stage_audit_pass.head_of(root, "HEAD")() == git(root, "rev-parse", "HEAD").strip()
    assert stage_audit_pass.head_of(root, "refs/heads/nothing")() is None


# -- the tick --------------------------------------------------------------------------------------------------------


def test_the_tick_runs_no_audit_while_no_team_is_started(store, root, monkeypatch):
    org = type("Org", (), {"teams": {"t": object()}})()
    monkeypatch.setattr(stage_tick, "_docs", lambda *_: pytest.fail("no team started reads no flow"))
    got = stage_tick._audits(
        store, root, "origin/main", {"t": {"flow": "x"}}, {}, None, "here", lambda **_: {}, lambda: org, NOW
    )
    assert got == ()


def test_the_tick_starts_a_started_teams_audit_on_its_host_through_the_launch(store, root, monkeypatch):
    head = git(root, "rev-parse", "HEAD").strip()
    teamdef = object()
    org = type("Org", (), {"teams": {"t": teamdef}})()
    launched, calls = [], []

    class Got:
        launch = type("L", (), {"host": "n2"})()

    def launch(o, team, doc, key, **kw):
        launched.append((o, team, key, kw["host"], kw["base"], kw["came"]))
        return Got()

    def call(method, **kw):
        calls.append((method, kw))
        return {}

    monkeypatch.setattr(stage_tick.stage_start, "team_started", lambda _o, _t: True)
    monkeypatch.setattr(stage_tick, "_docs", lambda _s, _f: {"t": flow()})
    monkeypatch.setattr(stage_tick.stage_audit_start, "launch", launch)
    monkeypatch.setattr(stage_tick.stage_start, "start", lambda _c, _o, _t, _g: {"id": "s-1"})
    read = SessionsRead({}, frozenset(), frozenset())
    got = stage_tick._audits(
        store, root, "HEAD", {"t": {"flow": "x", "host": "n2"}}, {"t": ("", ())}, read, "here", call, lambda: org, NOW
    )
    assert [(s.act.name, s.made.made) for s in got] == [("start", True)]
    assert launched == [(org, teamdef, "docs", "n2", head, None)]
    assert ("progress", {"id": "s-1@n2", "ref": LEASE, "status": "claimed"}) in calls
    assert store.audit("t", "docs")["holder"] == "s-1@n2"


# -- the team limit (TD-2065, §4.9d *Sessions at once*) -------------------------------------------------------------


def held_stage(store: StageStore, tid: str, team: str = "t") -> None:
    store.put_entry({"id": tid, "team": team, "stage": "build", "holder": f"h-{tid}"}, "test")


def two_audits() -> dict:
    doc = flow("6 hours")
    return {**doc, "audits": [*doc["audits"], {"name": "code", "model": "m", "every": "6 hours"}]}


def test_an_audit_waits_while_the_stages_fill_the_team_limit(store):
    held_stage(store, "TD-1")
    w = World()
    got = one(store, facts(limits={"t": stage_audit_pass.Limits({}, 1)}), w)
    assert got.act is None and w.started == []
    assert one(store, facts(limits={"t": stage_audit_pass.Limits({}, 2)}), w).made.made


def test_the_audits_share_what_is_left_under_the_limit_and_another_teams_sessions_do_not_count(store):
    held_stage(store, "TD-1")
    held_stage(store, "TD-2", team="u")
    w = World()
    f = facts(docs={"t": two_audits()}, limits={"t": stage_audit_pass.Limits({}, 2)})
    got = stage_audit_pass.audit_pass(store, f, w.reach())
    assert [(s.audit, s.act.name if s.act else None) for s in got] == [("docs", "start"), ("code", None)]


def test_a_team_with_no_limit_starts_every_audit_whatever_its_stages_hold(store):
    held_stage(store, "TD-1")
    w = World()
    f = facts(docs={"t": two_audits()}, limits={"t": stage_audit_pass.Limits()})
    assert [s.act.name for s in stage_audit_pass.audit_pass(store, f, w.reach())] == ["start", "start"]


def test_stage_records_that_cannot_be_read_start_no_audit_of_a_team_with_numbers(store, monkeypatch):
    def boom():
        raise ValueError("bad json")

    monkeypatch.setattr(store, "entries", boom)
    w = World()
    assert one(store, facts(limits={"t": stage_audit_pass.Limits()}), w).act is None
    assert one(store, facts(), w).made.made


def test_the_tick_hands_the_audits_each_started_teams_numbers(store, root, monkeypatch):
    org = type("Org", (), {"teams": {"t": object(), "u": object()}})()
    seen: list[AuditFacts] = []
    monkeypatch.setattr(stage_tick.stage_start, "team_started", lambda _o, t: t == "t")
    monkeypatch.setattr(stage_tick, "_docs", lambda _s, _f: {"t": flow()})
    monkeypatch.setattr(stage_tick.stage_audit_pass, "audit_pass", lambda _s, f, _r: seen.append(f) or ())
    teams = {"t": {"flow": "x", "most": 3, "at_once": {"build": 2}}, "u": {"flow": "x", "most": 1}}
    read = SessionsRead({}, frozenset(), frozenset())
    stage_tick._audits(store, root, "HEAD", teams, {"t": ("", ()), "u": ("", ())}, read, "here", None, lambda: org, NOW)
    assert [f.limits for f in seen] == [{"t": stage_audit_pass.Limits({"build": 2}, 3)}]
