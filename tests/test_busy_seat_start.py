"""TD-1672 (TD-1569's build), design §4.9a *A busy seat is left alone* and *A refused start says why*: a person's
Start leaves each busy seat running — its name neither checked nor created, the start's result saying so — while
the rest of the team is started or closed as before; a refused start names each holder's clause and offers that
one session's cure, never a team stop. One reading (`teamrun.busy_reading`) serves `rows`, the start and
`_close_concluded`."""

from __future__ import annotations

import pytest
import yaml
from test_cli_teams import creates, org_doc, world  # noqa: F401 — `world` is a fixture

from sessionorc import work
from shiftlead import cli, teamrun
from shiftlead import org as orgmod

pytestmark = pytest.mark.unit

CLEAN = {"dirty": 0, "unpushed": 0, "upstream": "origin/x"}
OUT = {"at": "2026-11-12T08:00:00Z", "why": "nothing pickable"}


def _seated(tmp_path, *, on_call: bool = False) -> None:
    doc = org_doc(tmp_path)
    doc["teams"]["ao-grind"]["techlead"] = {"name": "techlead-ao"}
    if on_call:
        doc["teams"]["ao-grind"]["manager"]["on_call"] = True
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc))


def _rec(name: str, state: str = "exited", **kw) -> dict:
    return {
        "id": f"ao-shiftlead-{name}", "name": name, "team": "ao-grind", "state": state, "git": dict(CLEAN),
        "unattended": True, **kw,
    }  # fmt: skip


def _team(state, *, members: str = "exited", seat: dict | None = None, manager: dict | None = None) -> None:
    """The ao-grind crew: members in `members` (declared, clean), the techlead seat as `seat` says."""
    state["sessions"][:] = [
        _rec("orc-ao", **(manager or {"state": "exited"})),
        *(_rec(n, members, out_of_work=OUT) for n in ("grind-1", "grind-2", "hunt")),
        _rec("techlead-ao", **({"state": "working", "seat": {"trigger": "asks"}} | (seat or {}))),
    ]
    state["verdicts"].clear()
    for s in state["sessions"]:
        if s["state"] not in ("exited", "closed"):
            state["verdicts"][s["name"]] = {
                "name": s["name"], "verdict": "live", "holder": s["id"], "holder_state": s["state"],
            }  # fmt: skip


@pytest.mark.parametrize(
    "seat, words",
    [
        ({"state": "working"}, "working"),
        ({"state": "needs-you"}, "needs-you"),
        ({"state": "idle", "shells_live": 1}, "idle, shell live"),
        ({"state": "idle", "git": {"dirty": 0, "unpushed": 2, "upstream": "o"}}, "idle, unpushed work"),
    ],
)
def test_exited_members_start_and_a_busy_seat_is_left_running(world, capsys, seat, words):  # noqa: F811
    tmp_path, state = world
    state["host"] = {"host": "local"}
    _seated(tmp_path)
    _team(state, seat=seat)
    before = dict(state["sessions"][-1])
    assert cli.main(["team", "start", "ao-grind"]) == 0
    assert [p["name"] for p in creates(state)] == ["orc-ao", "grind-1", "grind-2", "hunt"]
    assert not any(m == "name_check" and p["name"] == "techlead-ao" for m, p in state["calls"])
    assert state["sessions"][4] == before, "the seat's record is untouched"
    assert f"techlead-ao left running ({words})" in capsys.readouterr().out


def test_left_running_is_in_the_result_and_rows_agree_with_the_start(world):  # noqa: F811
    tmp_path, state = world
    state["host"] = {"host": "local"}
    _seated(tmp_path)
    _team(state, members="idle")
    org = cli._org_here()
    (row,) = [r for r in teamrun.rows(org, state["sessions"], {}) if r["name"] == "ao-grind"]
    assert row["busy"] == [{"name": "techlead-ao", "state": "working"}]
    assert row["startable"] == {"closes": ["grind-1", "grind-2", "hunt"], "leaves": row["busy"]}
    _, result = teamrun.start(cli.call_sync, org, "ao-grind", "kmaster")
    assert result["left_running"] == row["startable"]["leaves"]
    assert sorted(c["name"] for c in result["closed"]) == row["startable"]["closes"]
    assert state["sessions"][4]["state"] == "working", "the seat is left, the rest closed"


def test_a_busy_on_call_manager_is_every_members_lead(world):  # noqa: F811
    tmp_path, state = world
    state["host"] = {"host": "local"}
    _seated(tmp_path, on_call=True)
    _team(state, manager={"state": "working", "seat": {"trigger": "team"}}, seat={"state": "exited"})
    _, result = teamrun.start(cli.call_sync, cli._org_here(), "ao-grind", "kmaster")
    made = {p["name"]: p for p in creates(state)}
    assert "orc-ao" not in made
    assert all(made[n]["controllers"] == ["ao-shiftlead-orc-ao"] for n in ("techlead-ao", "grind-1", "hunt"))
    assert result["manager"] == "ao-shiftlead-orc-ao"
    assert result["left_running"] == [{"name": "orc-ao", "state": "working"}]


def test_a_busy_filled_extra_is_only_skipped(world):  # noqa: F811
    tmp_path, state = world
    state["host"] = {"host": "local"}
    _seated(tmp_path)
    _team(state, seat={"state": "exited"})
    state["sessions"].append(_rec("techlead-ao-2", "working", seat={"trigger": "asks"}, scale={"line": "techlead-ao"}))
    _, result = teamrun.start(cli.call_sync, cli._org_here(), "ao-grind", "kmaster")
    assert "techlead-ao" in [p["name"] for p in creates(state)]
    assert result["left_running"] == [{"name": "techlead-ao-2", "state": "working"}]


def test_a_suffixed_live_seat_without_scale_refuses(world):  # noqa: F811
    tmp_path, state = world
    state["host"] = {"host": "local"}
    _seated(tmp_path)
    _team(state, seat={"state": "exited"})
    state["sessions"].append(_rec("techlead-ao-2", "working", seat={"trigger": "asks"}))
    state["verdicts"]["techlead-ao"] = {
        "name": "techlead-ao", "verdict": "live", "holder": "ao-shiftlead-techlead-ao-2", "holder_state": "working",
    }  # fmt: skip
    # no busy seat (a suffix without `scale`): the plan reads it as removed, refused in Apply's words (accepted)
    with pytest.raises(teamrun.teams.TeamError, match="techlead-ao-2 still running"):
        teamrun.start(cli.call_sync, cli._org_here(), "ao-grind", "kmaster")
    assert not creates(state)


def test_a_sessions_start_skips_nothing(world):  # noqa: F811
    tmp_path, state = world
    state["host"] = {"host": "local"}
    _seated(tmp_path)
    _team(state)
    with pytest.raises(teamrun.NamesHeld, match="techlead-ao working"):
        teamrun.start(cli.call_sync, cli._org_here(), "ao-grind", "kmaster", caller="ao-shiftlead-orc-ao")
    assert not creates(state)


def test_a_member_waiting_on_the_busy_seat_refuses_with_its_clause(world):  # noqa: F811
    tmp_path, state = world
    state["host"] = {"host": "local"}
    _seated(tmp_path)
    _team(state, members="idle")
    g1 = state["sessions"][1]
    g1["progress"] = [{"ref": "TD-9", "status": "claimed", "source": "declared", "pr": 77}]
    state["sessions"][4]["prs_waiting"] = {"asks": [{"from": g1["id"], "pr": 77}]}
    with pytest.raises(teamrun.NamesHeld) as e:
        teamrun.start(cli.call_sync, cli._org_here(), "ao-grind", "kmaster")
    assert "grind-1 waiting on techlead-ao: #77 — it waits on techlead-ao: #77" in str(e.value)
    assert not [m for m, _ in state["calls"] if m in ("close", "create")]


def test_a_seat_that_turns_busy_after_the_read_refuses_with_its_clause(world):  # noqa: F811
    tmp_path, state = world
    state["host"] = {"host": "local"}
    _seated(tmp_path)
    _team(state, members="idle", seat={"state": "idle"})  # idle, clean: closed with the team
    lists = 0
    real = cli.call_sync

    def call(method, **params):
        nonlocal lists
        if method == "list":
            lists += 1
            if lists == 2:  # `_close_concluded`'s own read: the seat was rung meanwhile
                state["sessions"][4]["state"] = "working"
        return real(method, **params)

    with pytest.raises(teamrun.NamesHeld) as e:
        teamrun.start(call, cli._org_here(), "ao-grind", "kmaster")
    assert "techlead-ao working — let it finish, or Kill that one session" in str(e.value)
    assert not [m for m, _ in state["calls"] if m in ("close", "create")]


def test_a_renamed_record_still_at_work_refuses_before_anything_is_closed(world):  # noqa: F811
    tmp_path, state = world
    state["host"] = {"host": "local"}
    _seated(tmp_path)
    _team(state, members="idle", seat={"state": "exited"})
    state["sessions"].append(_rec("dig", "working", role="hunter"))  # a member the definition dropped
    with pytest.raises(teamrun.teams.TeamError, match="dig still running: a live team takes a rename"):
        teamrun.start(cli.call_sync, cli._org_here(), "ao-grind", "kmaster")
    assert not [m for m, _ in state["calls"] if m in ("close", "create")]


# ---- the reading ----


def _def(tmp_path) -> orgmod.TeamDef:
    _seated(tmp_path)
    return cli._org_here().teams["ao-grind"]


def test_the_reading_names_busy_orphans_closes_and_why(world):  # noqa: F811
    tmp_path, state = world
    team = _def(tmp_path)
    _team(state, members="idle")
    rows = state["sessions"] + [_rec("oldseat", "working", seat={"trigger": "asks"})]  # renamed away
    got = teamrun.busy_reading(team, rows, {})
    assert got["busy"] == [{"id": "ao-shiftlead-techlead-ao", "name": "techlead-ao", "state": "working"}]
    assert [o["name"] for o in got["orphans"]] == ["oldseat"]
    assert got["closes"] == [] and got["why"] == ["oldseat working"], "an orphan is no busy seat"
    got = teamrun.busy_reading(team, state["sessions"], {})
    assert got["closes"] == ["grind-1", "grind-2", "hunt"] and got["why"] == []
    # a given skip replaces the computed busy
    got = teamrun.busy_reading(team, state["sessions"], {}, skip=[])
    assert got["closes"] == [] and got["why"] == ["techlead-ao working"]


def test_a_sweep_seat_is_neither_busy_nor_an_orphan(world):  # noqa: F811
    tmp_path, state = world
    team = _def(tmp_path)
    _team(state, seat={"state": "exited"})
    state["sessions"].append(_rec("sweep-ao-grind", "working", seat={"trigger": "swept", "by": "settings"}))
    got = teamrun.busy_reading(team, state["sessions"], {})
    assert got["busy"] == [] and got["orphans"] == []
    assert got["why"] == ["sweep-ao-grind working"]


def test_a_live_sweep_seat_refuses_with_its_clause_and_an_idle_clean_one_is_closed(world):  # noqa: F811
    tmp_path, state = world
    state["host"] = {"host": "local"}
    state["sweep"] = {"on": True, "every": "7d", "off": []}
    _seated(tmp_path)
    _team(state, members="idle", seat={"state": "exited"})
    sweep = _rec("sweep-ao-grind", "working", seat={"trigger": "swept", "by": "settings"})
    state["sessions"].append(sweep)
    state["verdicts"]["sweep-ao-grind"] = {
        "name": "sweep-ao-grind", "verdict": "live", "holder": sweep["id"], "holder_state": "working",
    }  # fmt: skip
    with pytest.raises(teamrun.NamesHeld, match="sweep-ao-grind working — let it finish"):
        teamrun.start(cli.call_sync, cli._org_here(), "ao-grind", "kmaster")
    sweep["state"], state["verdicts"]["sweep-ao-grind"]["holder_state"] = "idle", "idle"
    _, result = teamrun.start(cli.call_sync, cli._org_here(), "ao-grind", "kmaster")
    assert "sweep-ao-grind" in [c["name"] for c in result["closed"]]


def test_startable_is_none_for_an_orphan_and_with_no_waiting_reading(world):  # noqa: F811
    tmp_path, state = world
    _seated(tmp_path)
    org = cli._org_here()
    _team(state)
    (row,) = [r for r in teamrun.rows(org, state["sessions"]) if r["name"] == "ao-grind"]
    assert row["busy"] and row["startable"] is None, "no waiting reading"
    state["sessions"].append(_rec("oldseat", "working", seat={"trigger": "asks"}))
    (row,) = [r for r in teamrun.rows(org, state["sessions"], {}) if r["name"] == "ao-grind"]
    assert row["startable"] is None, "an orphan"


def test_finished_skip_leaves_a_record_out_and_still_reads_it_for_others():
    def r(name, state="idle", **kw):
        return {"id": name, "name": name, "state": state, "unattended": True, **kw}

    seat = r("tl", "working", seat={"trigger": "asks"})
    assert work.finished([seat], skip=["tl"]) is None, "only skipped records live: None"
    m = r("g1", out_of_work=OUT, progress=[{"status": "claimed", "source": "declared", "pr": 5}])
    seat["prs_waiting"] = {"asks": [{"from": "g1", "pr": 5}]}
    got = work.finished([m, seat], skip=["tl"])
    assert got["names"] == ["g1"] and got["why"] == ["g1 waiting on tl: #5"]


# ---- the clause and the cure ----


@pytest.mark.parametrize(
    "rec, why, clause, cure",
    [
        (
            _rec("hunt", "idle"),
            ["hunt idle, not declared"],
            "hunt idle, not declared",
            "Close it (`ao close ao-shiftlead-hunt`",
        ),
        (
            _rec("hunt", "idle", git={"dirty": 3, "unpushed": 0, "upstream": "o"}),
            ["hunt idle, not declared"],
            "hunt idle, not declared",
            "settle what it holds (3 uncommitted) before its Close",
        ),
        (
            _rec("hunt", "idle", out_of_work=OUT),
            ["grind-1 working"],
            "hunt finished — the team is not concluded: grind-1 working",
            "Close it (`ao close ao-shiftlead-hunt`",
        ),
        (
            _rec("hunt", "working"),
            ["hunt working"],
            "hunt working",
            "let it finish, or Kill that one session (`ao kill",
        ),
        (
            _rec("hunt", "idle", out_of_work=OUT),
            ["hunt waiting on the person: TD-2"],
            "hunt waiting on the person: TD-2",
            "it waits on the person: TD-2",
        ),
        (_rec("hunt", "idle", unattended=False), [], "your session hunt", "close it yourself"),
        (
            _rec("hunt", "working", sit_out={"at": "x"}),
            ["grind-1 working"],
            "hunt sat out by its flow, still working",
            "let it wrap up, or Close it once idle",
        ),
        (None, [], "hunt working", "let it finish, or Kill that one session"),
    ],
)
def test_each_holders_clause_and_cure(rec, why, clause, cure):
    v = {"name": "hunt", "verdict": "live", "holder": "ao-shiftlead-hunt", "holder_state": "working"}
    got = teamrun._holder_words("ao-grind", v, rec, {"why": why})
    assert got[0] == clause and got[1].startswith(cure), got
    assert "ao team stop" not in got[1] and ("Kill" not in got[1] or rec is None or rec["state"] == "working")


def test_a_suspended_holder_keeps_its_words():
    v = {"name": "hunt", "verdict": "suspended", "holder": "ao-shiftlead-hunt"}
    assert teamrun._holder_words("ao-grind", v, None, None) == (
        "hunt is suspended as ao-shiftlead-hunt",
        "a person lifts it",
    )


def test_a_suffixed_holders_clause_is_matched_to_its_own_record():
    v = {"name": "techlead-ao", "verdict": "live", "holder": "ao-shiftlead-techlead-ao-2", "holder_state": "working"}
    rec = _rec("techlead-ao-2", "working")
    got = teamrun._holder_words("ao-grind", v, rec, {"why": ["techlead-ao working", "techlead-ao-2 working"]})
    assert got[0] == "techlead-ao-2 working"
