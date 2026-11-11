"""TD-1574 slice 2, design §6 rule 3 *A stopped team's seats are held* and §4.10 *A team or a repo as the address*
(TD-1564): a held seat is still its team's address — `ao msg --team` and `ao td add --repo` land there, never routed
around — and its reply line says it waits for the team's Start; a held seat is no target across teams: a blank Team
pick and the tick's move take the first team whose techlead is able and not held."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import park_ticks

from sessionorc import mail
from sessionorc.client import LocalClient
from sessionorc.models import Session

NOW = datetime(2026, 11, 11, 6, 0, tzinfo=UTC)


def _z(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _seat_rec(**kw) -> Session:
    base = dict(id="ao-tl", name="tl", kind="interactive", adapter="shell", dir="/tmp/x", state="closed",
                team="g", unattended=True, supervised=True, seat={"trigger": "asks"})  # fmt: skip
    return Session(**{**base, **kw})


# -- the sentence ----------------------------------------------------------------------------------------------


def test_the_held_row_names_the_team_whose_word_and_the_start_and_carries_the_bound():
    held = {"by": "person", "team": "ao-grind", "wound": False}
    s = _seat_rec()
    line = mail.read_when(s, "ask", NOW, person=False, held=held)
    assert line.startswith(
        "waits in the seat's mailbox: its team ao-grind is stopped (by you), and the seat is filled at its next Start"
        " — `ao msg person` if it cannot wait"
    )
    assert "an ask takes the default bound" in line, "with the bound's tail the other on-call rows carry"
    mine = mail.read_when(s, "note", NOW, person=True, held={**held, "by": "until", "wound": True})
    assert mine == (
        "waits in the seat's mailbox: its team ao-grind is wound down (at its stop time), and the seat is filled at"
        " its next Start — Start the team to have it read"
    )
    assert mail.read_when(s, "ask", NOW, unreachable=True, held=held).startswith("lands at the home; its host"), (
        "unreachable still wins"
    )
    assert mail.read_when(s, "ask", NOW).startswith("fills this seat"), "no held word: the on-call row"


# -- the address, the reply line and the blank pick -------------------------------------------------------------


def _registry(tmp_path, *repos):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text("".join(f"{r}\n" for r in repos))
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")


async def _seat(person, d, name: str, team: str, **kw) -> str:
    d.mkdir(exist_ok=True)
    return (
        await person.call(
            "create",
            name=name,
            dir=str(d),
            adapter="agentshell",
            argv=["bash", "--norc", "--noprofile"],
            unattended=True,
            supervised=True,
            prompt="the seat's brief",
            seat={"trigger": "asks", "tags": True},
            team=team,
            **kw,
        )  # fmt: skip
    )["id"]


def _person_closed(agent, sid: str) -> None:
    """The person's Close of a team's last live record: a Stop (§6 rule 3)."""
    r = agent.sessions[sid]
    r.state, r.closer = "closed", {"by": "person", "at": _z(datetime.now(UTC))}


@pytest.mark.integration
async def test_an_ask_by_team_lands_on_the_held_seat_and_its_reply_line_says_so_before_any_pass(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        seat = await _seat(person, tmp_path / "s", "tl-beta", "beta", project="B")
        (tmp_path / "a").mkdir()
        asker = (
            await person.call(
                "create", name="asker", dir=str(tmp_path / "a"), adapter="agentshell", argv=["bash", "--norc"],
                unattended=True, team="alpha", project="A",
            )
        )["id"]  # fmt: skip
        _person_closed(agent, seat)
        assert agent.sessions[seat].stop_held is None, "no pass yet: the send reads the helper, never the mark"
        async with LocalClient(caller=asker) as a:
            got = await a.call("msg", team="beta", text="may samscrape take an entry?")
        assert got["delivered"] == [seat], "not routed around: its questions land and wait"
        line = got["read_when"][seat]
        assert (
            line.startswith("waits in the seat's mailbox: its team beta is stopped (by you)") and "msg person" in line
        )
        await agent._keep_running(datetime.now(UTC))
        assert agent.sessions[seat].stop_held and not agent.sessions[seat].superseded_by, "held, not filled"
        # the composer sentence the home's view gives the seat's card
        view = agent._view(agent.sessions[seat])
        assert (
            view["read_when"]["ask"].startswith("waits in the seat's mailbox")
            and "Start the team to have it read — an ask takes" in view["read_when"]["ask"]
        )
        # a suspended seat of a stopped team reads its own row, not the held one
        agent.sessions[seat].suspended = {"at": _z(datetime.now(UTC)), "by": "person"}
        assert "is stopped" not in agent._view(agent.sessions[seat])["read_when"]["ask"]
        agent.sessions[seat].suspended = None
        # a person's Restart of a record of the team lifts the hold for the next send
        agent.sessions[seat].state = "idle"
        assert agent._held_words(agent.sessions[seat]) is None
        await person.call("kill", id=seat)
        await person.call("kill", id=asker)


@pytest.mark.integration
async def test_a_blank_pick_passes_a_held_seat_and_the_tick_moves_one_off_it(agent, tmp_path):
    repo = tmp_path / "shiftlead"
    repo.mkdir()
    _registry(tmp_path, repo)
    await park_ticks(agent)
    async with LocalClient() as person:
        a = await _seat(person, tmp_path / "a", "tl-a", "team-a")
        b = await _seat(person, tmp_path / "b", "tl-b", "team-b")
        teams = [{"team": "team-a", "seat": a}, {"team": "team-b", "seat": b}]
        _person_closed(agent, a)
        got = await person.call("entry_add", repo="shiftlead", type="debt", text="blank", teams=teams)
        assert (got["to"], got["team"]) == (b, "team-b"), "a held seat is no target across teams"
        # the person's own pick still lands on the held seat, and its reply line is the held sentence
        mine = await person.call("entry_add", repo="shiftlead", type="debt", text="mine", teams=teams, team="team-a")
        assert mine["to"] == a and mine["read_when"].startswith("waits in the seat's mailbox: its team team-a")
        # both held: the first team's seat takes it and waits, saying so
        _person_closed(agent, b)
        waits = await person.call("entry_add", repo="shiftlead", type="debt", text="waits", teams=teams)
        assert waits["to"] == a and "is stopped (by you)" in waits["read_when"]
        # team B's techlead live again: the tick moves the blank pick off held A, `routed.why` saying why
        agent.sessions[b].state, agent.sessions[b].closer = "idle", None
        await agent._reroute_waiting(datetime.now(UTC))
        held = {e.id: e for e in agent.sessions[a].inbox}
        assert held[waits["id"]].closed_reason == "rerouted"
        moved = next(e for e in agent.sessions[b].inbox if e.root == waits["id"])
        assert moved.routed["why"] == "its team is stopped" and moved.entry["team"] == "team-b"
        assert held[mine["id"]].open, "the person's pick waits on the held seat"
        for sid in (a, b):
            await person.call("kill", id=sid)
