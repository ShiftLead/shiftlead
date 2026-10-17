"""**Open shell here** reopens the session's live shell (design §4.5a *Focus: Open shell here*, **One
shell per session, reopened**, TD-810, built by TD-817): the route checks the name the create would take
with `name_check`, with what the create sends, and opens the person's own live shell holding it instead
of creating one; a live holder that is not one is refused with its reason; an exited one is superseded
by the create; a second press racing the first lands on the same shell; a node session's shell is made
on its node."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sessionorc.client import AgentError

SESSION = {"id": "ao-shiftlead-w", "name": "w", "dir": "/repo/wt", "host": None}
OWN = {
    "id": "ao-wt-w-shell",
    "adapter": "shell",
    "unattended": False,
    "role": None,
    "team": None,
    "controllers": [],
    "dir": "/repo/wt",
}


class Agent:
    """The host agent the route asks: `name_check`'s verdict, the records, and what `create` does."""

    def __init__(self, verdict: dict | None = None, holder: dict | None = None):
        self.verdict = verdict or {"verdict": "free", "holder": None}
        self.records = {SESSION["id"]: dict(SESSION), **({holder["id"]: holder} if holder else {})}
        self.calls: list[tuple[str, dict]] = []
        self.create_refused: str | None = None
        self.on_create = None  # what a racing press did before this create landed

    async def call(self, method, **kw):
        self.calls.append((method, kw))
        if method == "get":
            return self.records[kw["id"]]
        if method == "name_check":
            return dict(self.verdict)
        if method == "create":
            if self.on_create:
                self.on_create(self)
            if self.create_refused:
                raise AgentError(self.create_refused)
            return {"id": "ao-wt-w-shell"}
        return {}

    def made(self) -> list[dict]:
        return [kw for m, kw in self.calls if m == "create"]

    def checked(self) -> list[dict]:
        return [kw for m, kw in self.calls if m == "name_check"]


@pytest.fixture
def press(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui import app as uiapp

    holder = {}

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            return await holder["agent"].call(method, **kw)

    monkeypatch.setattr(uiapp, "LocalClient", Client)

    def go(agent: Agent):
        holder["agent"] = agent
        with TestClient(uiapp.create_app()) as c:
            return c.post(f"/api/sessions/{SESSION['id']}/shell-here")

    return go


def live(holder: dict) -> dict:
    return {"verdict": "live", "holder": holder["id"], "holder_state": "idle", "message": "w-shell is running"}


@pytest.mark.unit
def test_a_press_with_the_sessions_shell_still_open_opens_it_and_creates_nothing(press):
    agent = Agent(live(OWN), OWN)
    r = press(agent)
    assert r.status_code == 200 and r.json() == {"ok": True, "id": OWN["id"], "reused": True}
    assert agent.made() == []
    assert ("seen", {"id": SESSION["id"]}) in agent.calls  # still marks the session seen


@pytest.mark.unit
def test_a_press_after_exit_creates_a_fresh_shell_that_supersedes_it(press):
    gone = {**OWN, "state": "exited"}
    agent = Agent({"verdict": "supersede", "holder": gone["id"], "holder_state": "exited"}, gone)
    r = press(agent)
    assert r.status_code == 200 and r.json() == {"ok": True, "id": "ao-wt-w-shell"}
    assert agent.made() == [{"name": "w-shell", "dir": "/repo/wt", "adapter": "shell"}]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("holder", "words"),
    [
        ({**OWN, "adapter": "claude-code"}, "which is not a shell"),
        ({**OWN, "controllers": ["ao-shiftlead-lead"]}, "a shell with controllers ao-shiftlead-lead — not your own"),
        ({**OWN, "role": "grinder"}, "a shell with a role — not your own"),
        ({**OWN, "unattended": True}, "a shell run unattended — not your own"),
        ({**OWN, "dir": "/elsewhere"}, "is held by a shell in /elsewhere"),
    ],
)
def test_a_live_holder_that_is_not_the_persons_own_shell_is_refused_with_its_reason(press, holder, words):
    agent = Agent(live(holder), holder)
    r = press(agent)
    assert r.status_code == 409 and words in r.json()["detail"], r.json()
    assert agent.made() == []


@pytest.mark.unit
def test_a_live_holder_with_no_record_is_refused_in_name_checks_words(press):
    msg = "w-shell is running outside shiftlead — its card appears within a tick"
    agent = Agent({"verdict": "live", "holder": "ao-wt-w-shell", "holder_state": "unrecorded", "message": msg})
    r = press(agent)
    assert r.status_code == 409 and r.json()["detail"] == msg and agent.made() == []


@pytest.mark.unit
def test_the_lookup_is_by_the_directory_the_create_names_not_the_sessions_repo(press):
    """TD-810's own case: the shell's id comes from its directory's basename, so the check is sent
    exactly what the create sends — the directory, no repo — and reads the agent's answer."""
    agent = Agent(live(OWN), OWN)
    press(agent)
    assert agent.checked() == [{"dir": "/repo/wt", "name": "w-shell"}]


@pytest.mark.unit
def test_two_presses_land_on_one_shell(press):
    """The second press's create is refused because the first took the name between its check and its
    create: the lookup runs once more and answers with the first's shell."""
    agent = Agent()
    agent.create_refused = "w-shell is running — switch to it, or pick another name"

    def raced(a: Agent):
        a.records[OWN["id"]] = OWN
        a.verdict = live(OWN)

    agent.on_create = raced
    r = press(agent)
    assert r.status_code == 200 and r.json() == {"ok": True, "id": OWN["id"], "reused": True}
    assert len(agent.checked()) == 2


@pytest.mark.unit
def test_a_refused_create_with_no_shell_behind_it_is_the_creates_own_refusal(press):
    agent = Agent()
    agent.create_refused = "no such directory: /repo/wt"
    r = press(agent)
    assert r.status_code == 400 and r.json()["detail"] == "no such directory: /repo/wt"


@pytest.mark.unit
def test_a_node_sessions_press_checks_and_creates_on_its_node(press):
    agent = Agent()
    agent.records[SESSION["id"]] = {**SESSION, "id": SESSION["id"], "host": "node-b"}
    r = press(agent)
    assert r.status_code == 200
    assert agent.checked() == [{"dir": "/repo/wt", "name": "w-shell", "host": "node-b"}]
    assert agent.made() == [{"name": "w-shell", "dir": "/repo/wt", "adapter": "shell", "host": "node-b"}]


# ── a team member's shell (design §4.8 *The person's own shell is the person*, §4.9, TD-821, TD-827) ──


@pytest.mark.unit
def test_a_press_on_a_team_member_creates_a_shell_with_its_badge_alone(press):
    agent = Agent()
    member = {**SESSION, "team": "ao-grind", "project": "shiftlead", "role": "grinder", "controllers": ["ao-lead"],
              "review": {"reader": "techlead"}, "unattended": True}  # fmt: skip
    agent.records[SESSION["id"]] = member
    r = press(agent)
    assert r.status_code == 200 and r.json() == {"ok": True, "id": "ao-wt-w-shell"}
    made = {"name": "w-shell", "dir": "/repo/wt", "adapter": "shell", "team": "ao-grind", "project": "shiftlead"}
    assert agent.made() == [made]


@pytest.mark.unit
def test_a_press_on_a_session_with_no_badge_creates_a_shell_with_none(press):
    agent = Agent()
    press(agent)
    assert agent.made() == [{"name": "w-shell", "dir": "/repo/wt", "adapter": "shell"}]


@pytest.mark.unit
def test_a_team_reads_the_teamed_shell_as_a_persons_session():
    """`teamrun.persons` keys on `unattended: false`: a team with only that shell live is not live, and
    neither a stop nor a concluded Start reaches it (`crew`)."""
    from shiftlead import teamrun

    shell = {"id": "ao-w-shell", "team": "t", "adapter": "shell", "unattended": False, "state": "idle"}
    member = {"id": "ao-w", "team": "t", "unattended": True, "state": "exited"}
    assert teamrun.persons(shell) and teamrun.crew("t", [shell, member]) == [member]
    assert not teamrun.live(teamrun.crew("t", [shell, member]))


@pytest.mark.unit
def test_a_teamed_shell_left_open_is_reopened(press):
    teamed = {**OWN, "team": "ao-grind", "project": "shiftlead"}
    agent = Agent(live(teamed), teamed)
    agent.records[SESSION["id"]] = {**SESSION, "team": "ao-grind", "project": "shiftlead"}
    r = press(agent)
    assert r.status_code == 200 and r.json() == {"ok": True, "id": OWN["id"], "reused": True}
    assert agent.made() == []


@pytest.mark.unit
def test_the_teamed_shell_draws_in_its_teams_group_not_the_no_team_strip():
    from shiftlead.ui.app import team_groups

    def v(sid, **kw):
        return {"id": sid, "name": sid, "state": "idle", "state_class": "idle", "state_label": "idle",
                "scraped": False, "rank": 5, "controllers": [], "capabilities": [], **kw}  # fmt: skip

    groups = team_groups([v("w", team="t", unattended=True), v("w-shell", team="t", adapter="shell", unattended=False)])
    (team,) = [g for g in groups if g["team"] == "t"]
    assert {m["id"] for m in team["members"]} == {"w", "w-shell"}
    assert all("w-shell" not in {m["id"] for m in g["members"]} for g in groups if g["team"] != "t")
