"""The built-in tech lead's and sweeper's records the home writes after the cut-over (design §4.9d *How each one runs*,
TD-2065)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sessionorc.models import Session
from shiftlead import stage_seats, teamrun, teams

pytestmark = pytest.mark.unit

STARTED = {"t": {"started": {"since": "2026-11-25T00:00:00Z", "by": "person"}}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(teams, "_person", lambda *_a: ([], False))
    (tmp_path / "rules.md").write_text("THE REPO RULES\n")
    (tmp_path / ".shiftlead.yml").write_text("roles: {techlead: {brief: rules.md}, sweeper: {brief: rules.md}}\n")
    team = SimpleNamespace(name="t", repo="r", members=[])
    org = SimpleNamespace(
        checkout=lambda _repo, _host: str(tmp_path),
        roles={},
        project_of=lambda repo: repo,
        checkouts={"r": str(tmp_path)},
        teams={"t": team},
    )
    return org, team, tmp_path


class Home:
    """The home's calls as the pass makes them: `name_check` answers `verdict`, `create` records its arguments."""

    def __init__(self, verdict: str = "free", holder_state: str | None = None) -> None:
        self.verdict, self.holder_state, self.created = verdict, holder_state, []

    def __call__(self, method: str, **params):
        if method == "name_check":
            return {"verdict": self.verdict, **({"holder_state": self.holder_state} if self.holder_state else {})}
        assert method == "create"
        self.created.append(params)
        return {"id": f"ao-r-{params['name']}"}


def record(**kw) -> Session:
    base = {
        "id": "ao-r-techlead-t",
        "name": "techlead-t",
        "kind": "interactive",
        "adapter": "claude-code",
        "dir": "/r",
        "team": "t",
    }
    return Session(**{**base, **kw})


def test_the_launch_is_the_techlead_role_on_the_repos_checkout_with_the_package_brief_and_the_repos_part(world):
    org, team, root = world
    x = stage_seats.techlead_launch(org, team, host="h", here="h")
    assert (x.name, x.role, x.team, x.dir, x.lane, x.host) == ("techlead-t", "techlead", "t", root, [], "")
    assert "You are a **techlead**" in x.prompt and "THE REPO RULES" in x.prompt
    p = stage_seats.create_params(x)
    assert p["worktree"] == "techlead-t", "the seat runs in a worktree of its own name (§9 invariant 2)"
    assert p["seat"] == {"trigger": "asks", "tags": True}
    assert (p["held"], p["builtin"], p["controllers"]) == (True, "techlead", [])
    assert (p["unattended"], p["supervised"]) == (True, True)
    assert "keep_mail" not in p


def test_a_started_team_with_no_tech_lead_record_gets_one_and_a_second_pass_writes_none(world):
    org, _team, _ = world
    home = Home()
    assert stage_seats.write_techleads(home, org, {"t": {}}, {}, STARTED, "h") == ["ao-r-techlead-t"]
    assert [c["name"] for c in home.created] == ["techlead-t"]
    graph = {"ao-r-techlead-t": record(builtin="techlead", state="closed")}
    assert stage_seats.write_techleads(home, org, {"t": {}}, graph, STARTED, "h") == []
    assert len(home.created) == 1, "the record stands, so the next pass writes no second"


@pytest.mark.parametrize(
    "marks", [{}, {"t": {"stopped": {"at": "2026-11-25T00:00:00Z", "by": "person"}}}], ids=["never", "stopped"]
)
def test_a_team_that_is_not_started_gets_no_record(world, marks):
    org, _team, _ = world
    home = Home()
    assert stage_seats.write_techleads(home, org, {"t": {}}, {}, marks, "h") == []
    assert home.created == []


def test_a_first_shape_seat_of_the_name_is_superseded_its_mail_kept(world):
    org, _team, _ = world
    home = Home(verdict="supersede", holder_state="closed")
    graph = {"ao-r-techlead-t": record(seat={"trigger": "asks", "tags": True}, state="closed")}
    assert stage_seats.write_techleads(home, org, {"t": {}}, graph, STARTED, "h") == ["ao-r-techlead-t"]
    assert home.created[0]["keep_mail"] is True and home.created[0]["builtin"] == "techlead"


def test_a_superseded_built_in_record_is_not_the_current_one(world):
    org, _team, _ = world
    home = Home(verdict="supersede", holder_state="exited")
    graph = {"old": record(id="old", builtin="techlead", superseded_by="gone")}
    assert stage_seats.write_techleads(home, org, {"t": {}}, graph, STARTED, "h") == ["ao-r-techlead-t"]


def test_a_tmux_session_with_no_record_is_superseded_with_no_mail_to_keep(world):
    org, _team, _ = world
    home = Home(verdict="supersede", holder_state="unrecorded")
    stage_seats.write_techleads(home, org, {"t": {}}, {}, STARTED, "h")
    assert "keep_mail" not in home.created[0]


@pytest.mark.parametrize("verdict", ["live", "suspended"])
def test_a_live_session_holding_the_name_writes_nothing_this_pass(world, verdict):
    org, _team, _ = world
    home = Home(verdict=verdict)
    assert stage_seats.write_techleads(home, org, {"t": {}}, {}, STARTED, "h") == []
    assert home.created == []


def test_a_team_the_org_does_not_hold_or_no_org_writes_nothing(world):
    org, _team, _ = world
    home = Home()
    assert stage_seats.write_techleads(home, org, {"u": {}}, {}, {"u": STARTED["t"]}, "h") == []
    assert stage_seats.write_techleads(home, None, {"t": {}}, {}, STARTED, "h") == []
    assert home.created == []


def test_a_refused_create_is_a_log_line_and_the_next_team_still_gets_its_record(world, caplog):
    org, team, root = world
    org.teams["u"] = SimpleNamespace(name="u", repo="r", members=[])
    marks = {**STARTED, "u": STARTED["t"]}

    def home(method, **params):
        if method == "name_check":
            return {"verdict": "free"}
        if params["name"] == "techlead-t":
            raise RuntimeError("refused")
        return {"id": f"ao-r-{params['name']}"}

    assert stage_seats.write_techleads(home, org, {"t": {}, "u": {}}, {}, marks, "h") == ["ao-r-techlead-u"]
    assert "could not be written" in caplog.text


def test_the_record_lands_on_the_teams_host(world):
    org, _team, _ = world
    home = Home()
    stage_seats.write_techleads(home, org, {"t": {"host": "node"}}, {}, STARTED, "h")
    assert home.created[0]["host"] == "node"


ON = {"on": True, "every": "7d", "off": []}


def test_the_sweepers_launch_is_the_repos_record_on_swept_made_by_the_switch(world):
    org, team, root = world
    x = stage_seats.sweeper_launch(org, team, "7d", host="h", here="h")
    assert (x.name, x.role, x.team, x.dir, x.lane) == ("sweeper-r", "sweeper", "", root, [])
    assert "THE REPO RULES" in x.prompt
    p = stage_seats.create_params(x, builtin="sweeper")
    assert p["seat"] == {"trigger": "swept", "after": "7d", "by": "settings"}
    assert (p["held"], p["builtin"], p["team"], p["worktree"]) == (True, "sweeper", "", "sweeper-r")


def test_a_repo_with_a_started_team_gets_one_sweeper_record_while_the_switch_is_on(world):
    org, _team, _ = world
    org.teams["u"] = SimpleNamespace(name="u", repo="r", members=[])
    marks = {**STARTED, "u": STARTED["t"]}
    home = Home()
    got = stage_seats.write_sweepers(home, org, {"t": {"host": "node"}, "u": {}}, {}, marks, "h", ON)
    assert got == ["ao-r-sweeper-r"] and len(home.created) == 1, "one record for the repo, never one per team"
    assert home.created[0]["host"] == "node", "on the host of the first of the repo's started teams by name"
    graph = {"ao-r-sweeper-r": record(id="ao-r-sweeper-r", name="sweeper-r", team="", builtin="sweeper")}
    assert stage_seats.write_sweepers(home, org, {"t": {}, "u": {}}, graph, marks, "h", ON) == []
    assert len(home.created) == 1, "the record stands, so the next pass writes no second"


@pytest.mark.parametrize(
    "switch",
    [None, {"on": False, "every": "7d", "off": []}, {"on": True, "every": "7d", "off": ["r"]}],
    ids=["unread", "off", "repo-off"],
)
def test_no_sweeper_record_while_either_switch_is_off(world, switch):
    org, _team, _ = world
    home = Home()
    assert stage_seats.write_sweepers(home, org, {"t": {}}, {}, STARTED, "h", switch) == []
    assert home.created == []


def test_no_sweeper_record_while_no_team_of_the_repo_is_started(world):
    org, _team, _ = world
    home = Home()
    assert stage_seats.write_sweepers(home, org, {"t": {}}, {}, {}, "h", ON) == []
    assert home.created == []


def test_a_first_shape_sweep_seat_is_not_the_repos_sweeper(world):
    org, _team, _ = world
    home = Home()
    graph = {"sw": record(id="sw", name="sweep-t", seat={"trigger": "swept", "after": "7d", "by": "settings"})}
    assert stage_seats.write_sweepers(home, org, {"t": {}}, graph, STARTED, "h", ON) == ["ao-r-sweeper-r"]


def test_the_prompts_seats_launch_is_the_repos_record_in_the_directors_role_naming_its_repo(world):
    org, team, root = world
    x = stage_seats.prompts_launch(org, team, host="h", here="h")
    assert (x.name, x.role, x.team, x.dir, x.lane, x.grants) == ("prompts-r", "director", "", root, [], ["permit"])
    assert "**director seat**" in x.prompt, "the director seat's brief"
    assert "r's prompts seat" in x.prompt and str(root) in x.prompt and "{org}" not in x.prompt
    assert "The org's checkouts" not in x.prompt, "its repo stands where the director's Org block goes"
    p = stage_seats.create_params(x, builtin="prompts")
    assert p["seat"] == {"trigger": "prompt"}
    assert (p["held"], p["builtin"], p["team"], p["worktree"], p["controllers"]) == (
        True,
        "prompts",
        "",
        "prompts-r",
        [],
    )
    assert (p["unattended"], p["supervised"]) == (True, True)


def test_a_repo_with_a_started_team_gets_one_prompts_record_while_the_org_has_no_director(world):
    org, _team, _ = world
    org.director = None
    org.teams["u"] = SimpleNamespace(name="u", repo="r", members=[])
    marks = {**STARTED, "u": STARTED["t"]}
    home = Home()
    got = stage_seats.write_prompts(home, org, {"t": {"host": "node"}, "u": {}}, {}, marks, "h")
    assert got == ["ao-r-prompts-r"] and len(home.created) == 1, "one record for the repo, never one per team"
    assert home.created[0]["host"] == "node" and home.created[0]["builtin"] == "prompts"
    graph = {"ao-r-prompts-r": record(id="ao-r-prompts-r", name="prompts-r", team="", builtin="prompts")}
    assert stage_seats.write_prompts(home, org, {"t": {}, "u": {}}, graph, marks, "h") == []
    assert len(home.created) == 1, "the record stands, so the next pass writes no second"


def test_no_prompts_record_where_the_org_has_a_director_or_no_team_is_started(world):
    org, _team, _ = world
    home = Home()
    org.director = None
    assert stage_seats.write_prompts(home, org, {"t": {}}, {}, {}, "h") == []
    org.director = SimpleNamespace(name="director")
    assert stage_seats.write_prompts(home, org, {"t": {}}, {}, STARTED, "h") == []
    assert stage_seats.write_prompts(home, None, {"t": {}}, {}, STARTED, "h") == []
    assert home.created == []


def test_the_directors_record_is_never_the_repos_prompts_seat(world):
    org, _team, _ = world
    org.director = None
    graph = {"d": record(id="d", name="prompts-r", team="", seat={"trigger": "prompt"})}
    assert stage_seats.prompts_of(graph, "r") is None
    assert stage_seats.write_prompts(Home(), org, {"t": {}}, graph, STARTED, "h") == ["ao-r-prompts-r"]


@pytest.mark.integration
async def test_the_home_takes_the_record_held_built_in_and_due_on_a_question(agent, world):
    """The `create` the pass sends: a closed record marked `builtin: techlead` that tags, filled when an ask waits."""
    import subprocess
    from datetime import UTC, datetime

    from sessionorc.client import LocalClient

    org, team, root = world
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    x = stage_seats.techlead_launch(org, team, host="h", here="h")
    async with LocalClient() as person:
        sid = (await person.call("create", **stage_seats.create_params(x)))["id"]
        rec = agent.sessions[sid]
        assert (rec.state, rec.builtin, rec.seat, rec.team) == (
            "closed",
            "techlead",
            {"trigger": "asks", "tags": True},
            "t",
        )
        assert rec.unattended and rec.supervised and rec.controllers == []
        assert stage_seats.techlead_of(agent.sessions, "t") is rec
        assert agent._seat_due(rec, datetime.now(UTC), list(agent.sessions.values())) is None
        await person.call("msg", to=sid, text="is this figure right?", kind="ask")
        assert agent._seat_due(rec, datetime.now(UTC), list(agent.sessions.values())) is not None


@pytest.mark.integration
async def test_the_home_takes_the_sweeper_record_held_built_in_and_of_the_repo(agent, world):
    """The `create` the pass sends for a sweeper: a closed record marked `builtin: sweeper`, of no team, its seat the
    switch's `swept` mark."""
    import subprocess

    from sessionorc.client import LocalClient

    org, team, root = world
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    x = stage_seats.sweeper_launch(org, team, "7d", host="h", here="h")
    async with LocalClient() as person:
        sid = (await person.call("create", **stage_seats.create_params(x, builtin="sweeper")))["id"]
        rec = agent.sessions[sid]
        assert (rec.state, rec.builtin, rec.seat, rec.team or "") == (
            "closed",
            "sweeper",
            {"trigger": "swept", "after": "7d", "by": "settings"},
            "",
        )
        assert rec.unattended and rec.supervised and rec.controllers == []
        assert stage_seats.sweeper_of(agent.sessions, "r") is rec


class Records:
    """The home's `list`, `create` and `remove`, on records it holds as dicts, so a second pass reads the first's."""

    def __init__(self, *records) -> None:
        self.records, self.removed, self.refuse = [dict(r) for r in records], [], set()

    def __call__(self, method: str, **params):
        if method == "list":
            return [dict(r) for r in self.records]
        if method == "create":
            self.records.append({"id": f"ao-{params['name']}", "state": "closed", **params})
            return {"id": f"ao-{params['name']}"}
        assert method == "remove"
        if params["id"] in self.refuse:
            raise RuntimeError("refused")
        self.removed.append(params["id"])
        self.records = [r for r in self.records if r["id"] != params["id"]]
        return None


def _director_params(tmp_path):
    return {"name": "director", "dir": str(tmp_path / "director"), "seat": {"trigger": "prompt"}, "held": True}


def test_the_director_record_is_written_once_where_the_org_has_a_director(world, monkeypatch):
    org, _team, tmp_path = world
    org.director = SimpleNamespace(name="director")
    monkeypatch.setattr(teams, "director_create", lambda _org: _director_params(tmp_path))
    home = Records()
    assert stage_seats.write_director(home, org) == [f"director: {teamrun.DIRECTOR_LINE}"]
    assert stage_seats.write_director(home, org) == [], "the record stands, so a second pass writes none"
    assert [r["name"] for r in home.records] == ["director"] and (tmp_path / "director").is_dir()
    prompts = {"id": "p", "name": "prompts-r", "seat": {"trigger": "prompt"}, "builtin": "prompts", "state": "closed"}
    home = Records(prompts)
    assert stage_seats.write_director(home, org) == [f"director: {teamrun.DIRECTOR_LINE}"], "a prompts seat is not it"
    assert stage_seats.write_director(Records(), None) == []


def test_the_director_record_is_removed_once_the_key_is_gone_and_no_session_of_it_is_live(world):
    org, _team, _ = world
    org.director = None
    seat = {"seat": {"trigger": "prompt"}}
    home = Records(
        {"id": "d1", "name": "director", "state": "closed", **seat},
        {"id": "d2", "name": "director-old", "state": "working", **seat},
        {"id": "p", "name": "prompts-r", "state": "closed", "builtin": "prompts", **seat},
        {"id": "x", "name": "techlead-t", "state": "closed", "seat": {"trigger": "asks"}},
    )
    assert stage_seats.write_director(home, org) == ["director: removed, the org has no director"]
    assert home.removed == ["d1"], "a live director, a prompts seat and another seat are kept"
    home.records[0]["state"] = "exited"
    home.refuse.add("d2")
    assert stage_seats.write_director(home, org) == [] and home.removed == ["d1"], "a refused remove is retried later"


def test_the_pass_asks_the_home_nothing_where_its_snapshot_reads_as_the_key_wants(world):
    org, _team, _ = world
    home = Records()
    org.director = None
    assert stage_seats.write_director(home, org, {"x": record(id="x")}) == []
    org.director = SimpleNamespace(name="director")
    graph = {"d": record(id="d", name="director", team="", seat={"trigger": "prompt"})}
    assert stage_seats.write_director(home, org, graph) == []
    assert home.records == [] and home.removed == []


# ── a record moved host (§4.9d *How each one runs*: where that host changes, the home makes the record there) ──


class Mover(Home):
    """The home's calls with `seat_moved` recorded too."""

    def __init__(self, verdict: str = "free") -> None:
        super().__init__(verdict)
        self.moved: list[dict] = []

    def __call__(self, method: str, **params):
        if method == "seat_moved":
            self.moved.append(params)
            return {"old": params["old"], "new": params["new"]}
        return super().__call__(method, **params)


def test_an_ended_tech_lead_record_whose_host_changed_is_written_there_and_the_old_one_moved(world):
    org, _team, _ = world
    home = Mover("supersede")  # the new host's name rule would keep the mail: the move's own `keep=False` refuses it
    graph = {"ao-r-techlead-t": record(builtin="techlead", state="closed", host="h")}
    assert stage_seats.write_techleads(home, org, {"t": {"host": "node"}}, graph, STARTED, "h") == ["ao-r-techlead-t"]
    assert home.created[0]["host"] == "node"
    assert "keep_mail" not in home.created[0], "the mail comes by seat_moved, never by the new host's name rule"
    assert home.moved == [{"old": "ao-r-techlead-t", "new": "ao-r-techlead-t@node"}]


def test_a_record_on_a_node_moved_home_is_addressed_by_its_node(world):
    org, _team, _ = world
    home = Mover()
    graph = {"ao-r-techlead-t@node": record(builtin="techlead", state="exited", host="node")}
    stage_seats.write_techleads(home, org, {"t": {}}, graph, STARTED, "h")
    assert "host" not in home.created[0] or not home.created[0]["host"]
    assert home.moved == [{"old": "ao-r-techlead-t@node", "new": "ao-r-techlead-t"}]


@pytest.mark.parametrize(
    "over", [{"state": "idle"}, {"state": "working"}, {"state": "closed", "suspended": {"at": "x"}}]
)
def test_a_live_or_suspended_record_stays_where_it_is(world, over):
    org, _team, _ = world
    home = Mover()
    graph = {"ao-r-techlead-t": record(builtin="techlead", host="h", **over)}
    assert stage_seats.write_techleads(home, org, {"t": {"host": "node"}}, graph, STARTED, "h") == []
    assert home.created == [] and home.moved == []


def test_a_repo_seat_moves_with_its_first_started_team(world):
    org, _team, _ = world
    home = Mover()
    rec = record(id="ao-r-sweeper-r", name="sweeper-r", team="", builtin="sweeper", state="closed", host="h")
    assert stage_seats.write_sweepers(home, org, {"t": {"host": "node"}}, {rec.id: rec}, STARTED, "h", ON)
    assert home.moved == [{"old": "ao-r-sweeper-r", "new": "ao-r-sweeper-r@node"}]


def test_a_prompts_seat_moves_with_its_repo_s_first_started_team(world):
    org, _team, _ = world
    org.director = None
    home = Mover()
    rec = record(id="ao-r-prompts-r", name="prompts-r", team="", builtin="prompts", state="exited", host="h")
    assert stage_seats.write_prompts(home, org, {"t": {"host": "node"}}, {rec.id: rec}, STARTED, "h") == [rec.id]
    assert home.created[0]["host"] == "node" and home.created[0]["builtin"] == "prompts"
    assert home.moved == [{"old": "ao-r-prompts-r", "new": "ao-r-prompts-r@node"}]


def test_a_refused_move_is_a_log_line(world, caplog):
    org, _team, _ = world

    class Refuses(Mover):
        def __call__(self, method, **params):
            if method == "seat_moved":
                raise RuntimeError("refused")
            return super().__call__(method, **params)

    graph = {"ao-r-techlead-t": record(builtin="techlead", state="closed", host="h")}
    assert stage_seats.write_techleads(Refuses(), org, {"t": {"host": "node"}}, graph, STARTED, "h")
    assert "was not marked superseded" in caplog.text


def test_a_half_made_move_asks_seat_moved_again_and_writes_nothing(world):
    """A move whose `seat_moved` failed leaves two current records; whichever the graph lists first, the next pass asks
    only `seat_moved` again, old to new (#4617's review)."""
    org, _team, _ = world
    old = record(builtin="techlead", state="closed", host="h")
    new = record(builtin="techlead", state="closed", host="node")
    for graph in ({"ao-r-techlead-t@node": new, "ao-r-techlead-t": old}, {"ao-r-techlead-t": old, "x@node": new}):
        home = Mover()
        assert stage_seats.write_techleads(home, org, {"t": {"host": "node"}}, graph, STARTED, "h") == []
        assert home.created == []
        assert home.moved == [{"old": "ao-r-techlead-t", "new": "ao-r-techlead-t@node"}]


@pytest.mark.integration
async def test_the_home_marks_the_old_record_superseded_and_moves_its_mail(agent):
    from sessionorc.agent import RpcError
    from sessionorc.models import PERSON, MailEntry

    old = record(builtin="techlead", state="closed", host=agent.host, unattended=True, seat={"trigger": "asks"})
    old.inbox = [MailEntry(id="m-1", from_=PERSON, to=[old.id], at="2026-11-25T10:00:00Z", kind="ask", text="?")]
    agent.sessions[old.id] = old
    new = record(builtin="techlead", state="closed", host="node", unattended=True, seat={"trigger": "asks"})
    agent.remote["node"] = {new.id: new}
    with pytest.raises(RpcError, match="never a session's"):
        await agent.rpc_seat_moved(old=old.id, new=f"{new.id}@node", caller="ao-r-worker")
    with pytest.raises(RpcError, match="not one built-in seat's record on two hosts"):
        await agent.rpc_seat_moved(old=old.id, new=old.id)
    old.state = "idle"
    with pytest.raises(RpcError, match="finishes where it runs"):
        await agent.rpc_seat_moved(old=old.id, new=f"{new.id}@node")
    old.state = "closed"
    got = await agent.rpc_seat_moved(old=old.id, new=f"{new.id}@node")
    assert got == {"old": old.id, "new": f"{new.id}@node"}
    assert old.superseded_by == f"{new.id}@node"
    assert [e.id for e in new.inbox] == ["m-1"] and old.inbox == []
    assert new.supersedes[-1]["id"] == old.id
    with pytest.raises(RpcError, match="superseded already"):
        await agent.rpc_seat_moved(old=old.id, new=f"{new.id}@node")


@pytest.mark.integration
async def test_a_seat_s_host_move_closes_an_exited_record_and_drops_its_launch_and_refuses_a_node_and_a_suspended(
    agent, monkeypatch
):
    """`rpc_seat_moved`'s other clauses (design §4.9d *How each one runs*, TD-2209): an exited old record on the home's
    host is closed and its pane killed, its launch record is dropped so no fill replays it, a suspended record on either
    side is never moved, a node never takes the call, and a node's forward of it is refused (`modes.HOME_ONLY`)."""
    from pathlib import Path

    from sessionorc import modes, paths
    from sessionorc.agent import RpcError

    old = record(builtin="techlead", state="exited", host=agent.host, unattended=True, seat={"trigger": "asks"})
    agent.sessions[old.id] = old
    new = record(builtin="techlead", state="closed", host="node", unattended=True, seat={"trigger": "asks"})
    agent.remote["node"] = {new.id: new}
    killed = []
    monkeypatch.setattr(agent.tmux, "kill_session", killed.append)
    for side in (old, new):
        side.suspended = {"at": "2026-11-25T10:00:00Z", "by": "person", "why": "alarm"}
        with pytest.raises(RpcError, match="suspended"):
            await agent.rpc_seat_moved(old=old.id, new=f"{new.id}@node")
        side.suspended = None
    with monkeypatch.context() as m:  # scoped: the fixtures' own patches (the scratch home among them) stay
        m.setattr(agent, "mode", "node")
        with pytest.raises(RpcError, match="is a node of"):
            await agent.rpc_seat_moved(old=old.id, new=f"{new.id}@node")
    assert agent.mode == "home"
    assert killed == [] and old.state == "exited", "a refused move changes nothing"
    launch = paths.launch_dir() / f"{old.id}.json"
    assert paths.home() != Path.home() / ".shiftlead", "the test writes on its scratch home alone"
    launch.parent.mkdir(parents=True, exist_ok=True)
    launch.write_text("{}")
    await agent.rpc_seat_moved(old=old.id, new=f"{new.id}@node")
    assert killed == [old.id]
    assert old.state == "closed" and old.closed_at
    assert not launch.exists(), "a fill would replay the old record's launch"
    assert "seat_moved" in modes.HOME_ONLY, "refused when forwarded from a node"
