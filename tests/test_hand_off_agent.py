"""TD-1660 (TD-1543's design), the host agent's half of **Have a session do it**'s hand-off to a line's `Doer:` seat
(§4.5 screen 12 *Three verbs: Have a session do it*, §4.4 *Board write-back*, §4.10 *An entry handed to a seat*):
`board_find` re-reads the act line on origin's head and refuses what may not be handed; `board_edit`'s Done takes a
`why`; `entry_add` stores the hand-off's `refs`, `key`, `doer` and `handed_at` on the send, finds a handed ask by its
key (`find_only`) and sends once per key; `LocalClient.ignored` is the last call's dropped parameters."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from _v3board import item, ref_of, write_board
from conftest import park_ticks
from test_board import BOARD_TEXT, git, origin_item, repo  # noqa: F401 — `repo` a fixture
from test_handed_entry import _registry, _seat_session

from sessionorc import board, mail
from sessionorc.agent_inbox import HAND_OFF_ONLY
from sessionorc.client import AgentError, AgentStuck, LocalClient

ACT = (
    "act 2026-11-05 (session `grinder-ao-2` on kmaster) — **Bump the pin.** Context: TD-190, PR #12, "
    "agent-cadence#TD-7. Doer: agent-cadence. Due: 2026-11-20."
)
DETAIL = "  - **Context:** agent-cadence vendors v2.8 first.\n"


def _put(repo: Path, text: str, detail: str = "") -> str:  # noqa: F811 — the fixture's name
    """`text` (a v2 line) as an open item on origin's v3 board, `detail` its detail block; its reference."""
    write_board(repo, BOARD_TEXT + f"- [ ] {text}\n{detail}")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "act")
    git(repo, "push", "-q", "origin", "main")
    return ref_of(text)


# -- own_text and the Done's why ---------------------------------------------------------------------------------------


@pytest.mark.unit
def test_own_text_is_the_lines_words_bold_kept_and_marked_for_person_reads_it():
    assert board.own_text(ACT) == "**Bump the pin.**"
    assert board.own_text(f"- [ ] {ACT} — paul, 2026-11-06: soon") == "**Bump the pin.**"
    assert board.marked_for_person(ACT.replace("pin.**", "pin.** Only you can do this."))


@pytest.mark.unit
def test_a_done_writes_its_why_and_any_other_edit_refuses_one(tmp_path):
    write_board(tmp_path, BOARD_TEXT + f"- [ ] {ACT}\n")
    it = item(tmp_path, ref_of(ACT))
    got = board.edit_item(it, "done", today="2026-11-14", why="handed to agent-cadence: m-1")
    assert "**Closed:** 2026-11-14 — handed to agent-cadence: m-1\n" in got
    with pytest.raises(board.Refused, match="a why is a Done's alone"):
        board.edit_item(it, "snooze", "2026-11-30", why="x")
    with pytest.raises(board.Refused, match="a why is a Done's alone"):
        board.write_back(Path("/nowhere"), 1, ACT, "decide", answer="have a session do it", why="x")


# -- board_find --------------------------------------------------------------------------------------------------------


def test_board_find_reads_the_act_line_on_origin(repo):  # noqa: F811
    key = _put(repo, ACT, DETAIL)
    got = board.find_line(repo, None, key)
    assert got.pop("id").endswith(key[-8:])
    assert got == {
        "doer": "agent-cadence",
        "text": "**Bump the pin.**",
        "context": "agent-cadence vendors v2.8 first.",
        "session": "grinder-ao-2",
        "due": "2026-11-20",
        "context_refs": ["TD-190", "PR #12", "agent-cadence#TD-7"],
        "refs": ["TD-190", "agent-cadence#TD-7"],
        "key": key,
    }
    assert board.find_line(repo, 99, key)["doer"] == "agent-cadence", "a line number is read no more, the key decides"


@pytest.mark.parametrize(
    ("text", "words"),
    [
        (ACT + " Answers: Go | Not yet. Decided: Go (by paul) (2026-11-07).", "already decided"),
        (ACT.replace("act 2026", "decide 2026"), "act line's answer"),
        (ACT + " Answers: Go | Not yet.", "act line's answer"),
        (ACT.replace("pin.**", "pin.** Only you can do this."), "only you can do this"),
        (ACT.replace(" Doer: agent-cadence.", ""), "names no Doer"),
    ],
)
def test_board_find_refuses_what_may_not_be_handed_as_found_on_origin(repo, text, words):  # noqa: F811
    with pytest.raises(board.Refused, match=words):
        board.find_line(repo, None, _put(repo, text))


def test_board_find_refuses_a_closed_line_and_a_key_that_is_none(repo):  # noqa: F811
    key = _put(repo, ACT)
    board.write_back(repo, None, ACT, "done", key=key, why="handed to agent-cadence: m-1")
    assert origin_item(repo, key).closed[1] == "handed to agent-cadence: m-1"
    with pytest.raises(board.Refused, match=f"{key} was closed"):  # a closed item is said closed (TD-1881)
        board.find_line(repo, None, key)
    with pytest.raises(board.Refused, match="reworded or closed"):
        board.find_line(repo, None, "board:00000000")
    with pytest.raises(board.Refused, match="not a board line's id"):
        board.find_line(repo, None, "TD-1")


@pytest.mark.unit
def test_board_find_is_the_persons_own():
    assert "board_find" in mail.PERSON_ONLY


# -- entry_add's hand-off fields ---------------------------------------------------------------------------------------

RELAY = (
    "Relayed from shiftlead's board (board:0a1b2c3d): session w wrote it and the person pressed Have a session do "
    "it; due 2026-11-20\n**Bump the pin.**\n\nagent-cadence vendors v2.8 first."
)
KEY = "shiftlead:board:0a1b2c3d"


async def _hand(person, sid, **kw):
    teams = [{"team": "ao-grind", "seat": sid}]
    args = {"repo": "shiftlead", "type": "debt", "text": RELAY, "teams": teams, "refs": ["shiftlead#TD-190"]}
    return await person.call("entry_add", **{**args, "key": KEY, "doer": "agent-cadence", **kw})


@pytest.mark.integration
async def test_a_keyed_hand_off_stores_its_fields_on_the_send_and_is_found_by_its_key(agent, tmp_path):
    repo_dir = tmp_path / "shiftlead"
    repo_dir.mkdir()
    _registry(tmp_path, repo_dir)
    await park_ticks(agent)
    async with LocalClient() as person:
        assert await person.call("entry_add", key=KEY, find_only=True) == {"existing": False}
        sid = await _seat_session(person, tmp_path)
        got = await _hand(person, sid)
        e = next(e for e in agent.sessions[sid].inbox if e.id == got["id"])
        assert e.handed_entry and e.bound is None
        assert e.entry["refs"] == ["shiftlead#TD-190"] and e.entry["key"] == KEY and e.entry["doer"] == "agent-cadence"
        assert e.entry["handed_at"]
        assert e.subject == mail.clip_subject("**Bump the pin.**"), "the line's own text, never the relay line"
        want = {"id": got["id"], "to": sid, "team": "ao-grind", "doer": "agent-cadence", "existing": True}
        assert await person.call("entry_add", key=KEY, find_only=True) == want
        again = await _hand(person, sid)
        assert again == want, "a second press sends nothing"
        assert sum(1 for x in agent.sessions[sid].inbox if (x.entry or {}).get("key") == KEY) == 1
        # settled by an outcome, it is still found: a press on the line still open sends nothing
        agent._mark(got["id"], outcome={"state": "done", "text": "TD-7", "at": "t", "by": "m-x"})
        assert (await person.call("entry_add", key=KEY, find_only=True))["id"] == got["id"]
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_two_concurrent_keyed_calls_send_one_ask_and_a_rerouted_copy_is_skipped(agent, tmp_path):
    repo_dir = tmp_path / "shiftlead"
    repo_dir.mkdir()
    _registry(tmp_path, repo_dir)
    await park_ticks(agent)
    async with LocalClient() as a, LocalClient() as b:
        sid = await _seat_session(a, tmp_path)
        one, two = await asyncio.gather(_hand(a, sid), _hand(b, sid))
        assert one["id"] == two["id"]
        assert sum(1 for x in agent.sessions[sid].inbox if (x.entry or {}).get("key") == KEY) == 1
        e = next(x for x in agent.sessions[sid].inbox if x.id == one["id"])
        e.closed_reason = "rerouted"
        assert await a.call("entry_add", key=KEY, find_only=True) == {"existing": False}
        await a.call("kill", id=sid)


@pytest.mark.integration
async def test_a_sessions_entry_add_carrying_a_hand_off_field_is_refused(agent, tmp_path):
    repo_dir = tmp_path / "shiftlead"
    repo_dir.mkdir()
    _registry(tmp_path, repo_dir)
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _seat_session(person, tmp_path)
        for extra in ({"key": KEY}, {"refs": ["x#TD-1"]}, {"doer": "x"}, {"find_only": True}):
            async with LocalClient(caller=sid) as s:
                with pytest.raises(AgentError, match=HAND_OFF_ONLY):
                    await s.call("entry_add", repo="other", type="debt", text="t", **extra)
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_board_edit_refuses_a_why_on_any_action_but_done(agent):
    async with LocalClient() as person:
        with pytest.raises(AgentError, match="a why is a Done's alone"):
            await person.call("board_edit", board="/nowhere", line=1, text="t", action="snooze", why="x")


# -- LocalClient.ignored -----------------------------------------------------------------------------------------------


@pytest.mark.integration
async def test_ignored_is_the_last_calls_list_a_refusals_too_and_a_timeout_leaves_it_empty(agent):
    async with LocalClient() as c:
        assert c.ignored == []
        await c.call("ping", bogus=1)
        assert c.ignored == ["bogus"]
        await c.call("ping")
        assert c.ignored == [], "reset per call"
        with pytest.raises(AgentError):
            await c.call("entry_add", repo="", type="debt", text="t", zzz=1, caller_hint="x")
        assert sorted(c.ignored) == ["caller_hint", "zzz"], "a refusal carries its list too"
    async with LocalClient() as c:
        await c.call("ping", bogus=1)
        with pytest.raises(AgentStuck):
            await c.call("ping", _timeout=0)
        assert c.ignored == [], "a call that never answered leaves []"
