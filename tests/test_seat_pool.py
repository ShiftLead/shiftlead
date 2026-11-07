"""A seat as an ordered pool, its definition and its start (design §4.9b *A seat as an ordered pool*, *The
members*, *Where it is refused*; §6 rule 3; TD-1476 build 1, TD-1520): a `seats:` line on `asks` may name
`pool:`, two or more profiles in order; each is a member, a seat record of its own — the first named as the
line, the k-th `<name>-p<k>` — the first started live as a seat is, each later one written held; every
reader that knows a seat by its name knows each member; a review stage held by a pool is unstaffed."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from shiftlead import flowdefs, teamrun, teams
from shiftlead import org as orgmod

HOST = "kmaster"
POOL = {"name": "qa", "role": "fact-checker", "trigger": "asks", "pool": ["gemini-reader", "sonnet", "sonnet"]}


def _org(tmp_path: Path, monkeypatch, team: dict) -> orgmod.Org:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
    (tmp_path / "alpha" / ".git").mkdir(parents=True, exist_ok=True)
    doc = {"projects": {"p": {"repos": {"alpha": {HOST: str(tmp_path / "alpha")}}}}, "teams": {"t": team}}
    (home / "org.yml").write_text(yaml.safe_dump(doc))
    profiles = {p: {"account": p} for p in ("paul", "gemini-reader", "sonnet", "other")}
    (home / "profiles.yml").write_text(yaml.safe_dump({"default": "paul", "profiles": profiles}))
    return orgmod.load()


def _team(*seats: dict, **extra) -> dict:
    return {
        "repo": "alpha",
        "manager": {"role": "manager", "name": "lead"},
        "techlead": {"name": "tl"},
        "members": [{"role": "grinder", "name": "g"}],
        "seats": list(seats),
        **extra,
    }


@pytest.mark.unit
def test_each_refusal_is_refused_at_load_naming_the_line(tmp_path, monkeypatch):
    for seat, extra, why in (
        ({**POOL, "profile": "sonnet"}, {}, r"seats\[0\]: pool: names its members' profiles"),
        ({**POOL, "pool": ["sonnet"]}, {}, r"seats\[0\]\.pool: a pool is two or more profiles"),
        ({**POOL, "pool": "sonnet"}, {}, r"seats\[0\]\.pool must be a list"),
        ({**POOL, "trigger": {"prs": 3}}, {}, r"seats\[0\]\.pool: a pool is an asks seat's"),
        ({**POOL, "trigger": {"every": "6h"}}, {}, r"seats\[0\]\.pool: a pool is an asks seat's"),
        (POOL, {"techlead": {"name": "tl", "pool": ["a", "b"]}}, r"techlead\.pool: pool: is an asks seat's"),
        (
            POOL,
            {"manager": {"role": "manager", "name": "lead", "pool": ["a", "b"]}},
            r"manager\.pool: pool: is an asks seat's",
        ),
        # a member's name another record of the team holds: `qa-p2` is the pool's second member
        (POOL, {"members": [{"role": "grinder", "name": "qa-p2"}]}, r"seats\[0\]\.pool: its member qa-p2"),
    ):
        with pytest.raises(ValueError, match=why):
            _org(tmp_path, monkeypatch, _team(seat, **extra))
    # a second seat line named as a member is refused too, naming the pooled line
    with pytest.raises(ValueError, match=r"seats\[0\]\.pool: its member qa-p3"):
        _org(tmp_path, monkeypatch, _team(POOL, {"name": "qa-p3", "role": "auditor", "trigger": "asks"}))


@pytest.mark.unit
def test_a_pool_is_one_line_and_its_members_are_named_profiled_and_worded_per_place(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch, _team(POOL))
    team = org.teams["t"]
    (line,) = team.seats
    assert line.pool == ["gemini-reader", "sonnet", "sonnet"] and line.profile is None
    got = [(m.name, m.profile, m.pool_name, m.rank, m.pool_size) for m in team.seat_records()]
    assert got == [
        ("qa", "gemini-reader", "qa", 1, 3),
        ("qa-p2", "sonnet", "qa", 2, 3),
        ("qa-p3", "sonnet", "qa", 3, 3),
    ]
    assert [m.when() for m in team.seat_records()] == [
        "comes on the next question",
        "backup 1 of 2 — comes when qa cannot answer",
        "backup 2 of 2 — comes when qa and qa-p2 cannot answer",
    ]
    assert {"qa", "qa-p2", "qa-p3"} <= set(team.started_names())
    # the team listing carries the pool on its one line
    (listed,) = [s for s in teamrun.rows(org, [])[0]["seats"] if s["name"] == "qa"]
    assert listed["pool"] == ["gemini-reader", "sonnet", "sonnet"]


def _fake():
    calls: list[tuple[str, dict]] = []

    def call(method, **params):
        calls.append((method, params))
        if method == "name_check":
            return {"name": params["name"], "verdict": "free"}
        if method == "list":
            return []
        if method == "create":
            return {
                "id": f"ao-alpha-{params['name']}",
                "name": params["name"],
                "state": "closed" if params.get("held") else "working",
            }
        raise AssertionError(method)

    return call, calls


@pytest.mark.unit
def test_a_start_runs_the_first_member_and_writes_the_rest_held_each_a_seat(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch, _team(POOL))
    call, calls = _fake()
    # `--profile` changes no member's profile: a pool names its own
    teamrun.start(call, org, "t", HOST, profile="other")
    made = {p["name"]: p for m, p in calls if m == "create"}
    assert [made[n]["profile"] for n in ("qa", "qa-p2", "qa-p3")] == ["gemini-reader", "sonnet", "sonnet"]
    assert [made[n]["seat"] for n in ("qa", "qa-p2", "qa-p3")] == [
        {"trigger": "asks", "pool": "qa", "rank": k} for k in (1, 2, 3)
    ]
    assert "held" not in made["qa"] and made["qa-p2"]["held"] is True and made["qa-p3"]["held"] is True
    assert all(made[n]["supervised"] is True and made[n]["unattended"] is True for n in ("qa", "qa-p2", "qa-p3"))
    assert all(made[n]["controllers"] == ["ao-alpha-lead"] for n in ("qa", "qa-p2", "qa-p3"))
    # each member is a seat of the team to every reader that knows one by its name
    recs = [{"id": f"ao-alpha-{n}", "name": n, "team": "t", "state": "closed"} for n in ("qa", "qa-p2", "qa-p3")]
    assert teamrun._seat_of(org.teams["t"], recs) == {
        "qa": "comes on the next question",
        "qa-p2": "backup 1 of 2 — comes when qa cannot answer",
        "qa-p3": "backup 2 of 2 — comes when qa and qa-p2 cannot answer",
    }
    assert set(teamrun.seat_ids(org, recs)) == {"ao-alpha-qa", "ao-alpha-qa-p2", "ao-alpha-qa-p3"}
    # `ao team start`'s line for a held member says when it comes
    from shiftlead import cli

    p = teams.plan(org, "t", HOST)
    assert cli._team_line({"id": "ao-alpha-qa-p2", "name": "qa-p2", "state": "closed", "dir": "/d"}, "t", p) == (
        "ao-alpha-qa-p2  seat fact-checker  /d  starts held — pool member 2 of 3, comes when its pool routes to it"
    )


def _live(p: teams.Plan, without: tuple[str, ...] = ()) -> list[dict]:
    rec = {"team": "t", "state": "working"}
    return [
        {**rec, "id": f"ao-alpha-{x.name}", "name": x.name, "lane": x.lane, "review": x.review, "seat": x.seat_params()}
        | ({"profile": x.profile} if x.profile else {})
        for x in p.launches
        if x.name not in without
    ]


@pytest.mark.unit
def test_apply_of_a_pool_grown_at_the_tail_starts_the_new_member_held_and_moves_no_other(tmp_path, monkeypatch):
    org = _org(tmp_path, monkeypatch, _team(POOL))
    before = _live(teams.plan(org, "t", HOST), without=("qa-p3",))  # the run started with two members
    calls: list[tuple[str, dict]] = []

    def call(method, **params):
        calls.append((method, params))
        if method == "list":
            return before
        if method == "name_check":
            return {"name": params["name"], "verdict": "free"}
        if method == "create":
            return {"id": f"ao-alpha-{params['name']}", "name": params["name"]}
        raise AssertionError((method, params))

    got = teamrun.apply(call, org, "t", HOST)
    (made,) = [p for m, p in calls if m == "create"]
    assert made["name"] == "qa-p3" and made["held"] is True
    assert made["seat"] == {"trigger": "asks", "pool": "qa", "rank": 3}
    assert [r["line"] for r in got["applied"]] == [
        "qa-p3: starts held — pool member 3 of 3, comes when its pool routes to it"
    ]
    assert not [m for m, _ in calls if m == "relaunch"], "an earlier member's seat carries no count, so none moved"


@pytest.mark.unit
def test_apply_reads_a_members_changed_profile_and_a_dropped_member(tmp_path, monkeypatch):
    """§4.9b *A pool is compared member by member*: names follow places, so a member whose place now holds
    another profile reads *profile … → …*, and a member the definition no longer names is removed."""
    org = _org(tmp_path, monkeypatch, _team(POOL))
    before = _live(teams.plan(org, "t", HOST))
    org = _org(tmp_path, monkeypatch, _team({**POOL, "pool": ["sonnet", "gemini-reader"]}))
    calls: list[tuple[str, dict]] = []

    def call(method, **params):
        calls.append((method, params))
        if method == "list":
            return before
        if method in ("relaunch", "create"):
            return {"id": params.get("id") or f"ao-alpha-{params['name']}"}
        raise AssertionError((method, params))

    got = teamrun.apply(call, org, "t", HOST)
    assert sorted(r["line"] for r in got["applied"]) == [
        "qa-p2: profile sonnet → gemini-reader (next restart)",
        "qa-p3: removed from the definition",
        "qa: profile gemini-reader → sonnet (next restart)",
    ]
    dropped = [p for m, p in calls if m == "relaunch" and p.get("dropped")]
    assert [p["id"] for p in dropped] == ["ao-alpha-qa-p3"]


@pytest.mark.unit
def test_a_profile_seat_turned_into_a_pool_reads_its_rank_in_the_seat_line():
    x = teams.Launch(name="qa", role="fact-checker", home="alpha", dir=Path("/d"), team="t", project="p")
    x.trigger = {"trigger": "asks", "pool": "qa", "rank": 1}
    assert teamrun._seat_moved({"seat": {"trigger": "asks"}}, x) == ["seat asks → asks · pool 1"]


@pytest.mark.unit
def test_a_review_stage_held_only_by_a_pooled_seat_is_not_followable(tmp_path, monkeypatch):
    flow = flowdefs.Flow(
        name="qa-flow",
        place="repo",
        dir=tmp_path,
        stages=[
            flowdefs.Stage(name="build", role="grinder", lane=["td"]),
            flowdefs.Stage(name="qa", role="fact-checker"),
        ],
    )

    def why(seats):
        return flowdefs.unfollowable(flow, {"grinder"}, techlead=True, held=("src/**",), seats=seats)

    assert why([("fact-checker", "asks", False, "qa")]) == []
    assert why([("fact-checker", "asks")]) == [], "a pair reads unpooled, as the tests that omit it pass"
    assert why([("fact-checker", "asks", True, "qa")]) == ["qa is a pool: a review stage has one reader"]


@pytest.mark.integration
async def test_a_pool_member_with_no_mail_waiting_is_not_filled(agent, tmp_path):
    """§6 rule 3 unchanged: a held member is filled when mail waits on it, and only then."""
    from sessionorc.client import LocalClient

    d = tmp_path / "qa-p2"
    d.mkdir()
    async with LocalClient() as person:
        sid = (
            await person.call(
                "create",
                name="qa-p2",
                dir=str(d),
                adapter="agentshell",
                argv=["bash", "--norc"],
                unattended=True,
                supervised=True,
                seat={"trigger": "asks", "pool": "qa", "rank": 2},
                held=True,
            )
        )["id"]
        rec = agent.sessions[sid]
        assert rec.state == "closed" and rec.seat == {"trigger": "asks", "pool": "qa", "rank": 2}
        assert agent._seat_due(rec, datetime.now(UTC), list(agent.sessions.values())) is None
        # and when a question waits on it, it is due, as any `asks` seat is
        await person.call("msg", to=sid, text="is this figure right?", kind="ask")
        assert agent._seat_due(rec, datetime.now(UTC), list(agent.sessions.values())) is not None
