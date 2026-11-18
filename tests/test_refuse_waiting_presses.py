"""TD-1955: the three presses that refuse a member whose question waits on open work (design §4.4 *The card's
status*, *A `decision (paul)` member that still waits on open work is no need*, TD-1926), each sent through its own
RPC — `board_edit`'s decide on a line covering the member, `ledger_decide`'s answer and `ledger_decide`'s **Lift the
hold** (`_press_lift`) — refused *TD-n waits on TD-m: it is asked once that closes* before anything is written.
`test_queue_then_yours` calls the refusal's helpers directly; these go through the home's calls."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import park_ticks
from test_queue import _entry, _repo
from test_queue_board_hold import HELD, _open

from sessionorc import workorders
from sessionorc.client import AgentError, LocalClient

PART = {"Priority": "High", "Part_of": "TD-001"}
REFUSED = "TD-001 waits on TD-002: it is asked once that closes"


async def _home(agent, tmp_path, monkeypatch) -> tuple[str, Path, dict]:
    """A repo whose held design TD-001 has an open round part TD-002, its board an undecided decide line on TD-001,
    registered for this host and read by the home as this test hands it (the tick reads nothing over it)."""
    root, r = _repo(tmp_path, "r", [_entry(1, "the design", **HELD), _entry(2, "the round", **PART)])
    board = Path(root) / workorders.BOARD
    board.write_text("\n".join(["# Board", "", "People: paul", "", _open("TD-001", decided=None), ""]), "utf-8")
    r["boards"] = workorders.read_boards(root, fetch=False)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "repos.txt").write_text(f"{root}\n")
    (home / "hosts.yml").write_text(f"local:\n  repos_registry: {home / 'repos.txt'}\n")

    async def held() -> None:
        return None

    monkeypatch.setattr(agent, "_refresh_repos", held)
    monkeypatch.setattr(agent, "_read_ledger", lambda root, old_led, *a, **kw: (dict(old_led), []))
    await park_ticks(agent)
    agent._repos = {root: r}
    return root, board, r


async def test_a_decide_on_a_board_line_covering_a_waiting_member_is_refused_unwritten(agent, tmp_path, monkeypatch):
    root, board, r = await _home(agent, tmp_path, monkeypatch)
    item = r["boards"]["boards"][0]["items"][0]
    before = board.read_text("utf-8")
    async with LocalClient() as me:
        with pytest.raises(AgentError, match=REFUSED):
            await me.call("board_edit", board=str(board), key=str(item["key"]), action="decide", answer="Go",
                          answers=["Go", "Not yet"])  # fmt: skip
    assert board.read_text("utf-8") == before


async def test_an_answer_on_a_waiting_member_is_refused_unwritten(agent, tmp_path, monkeypatch):
    root, board, r = await _home(agent, tmp_path, monkeypatch)
    e = next(x for x in r["ledger"]["entries"] if x["id"] == "TD-001")
    assert e["for_page"] == "for-you", "it still sorts for you: only the waiting refusal stops the answer"
    before = board.read_text("utf-8")
    async with LocalClient() as me:
        for kw in ({"words": "Go"}, {"go": True}):
            with pytest.raises(AgentError, match=REFUSED):
                await me.call("ledger_decide", repo=root, id="TD-001", **kw)
    assert board.read_text("utf-8") == before


async def test_lift_the_hold_on_a_waiting_member_is_refused_unwritten(agent, tmp_path, monkeypatch):
    root, board, r = await _home(agent, tmp_path, monkeypatch)
    entry = Path(root) / "docs" / "technical_debt.md"
    before = entry.read_text("utf-8")
    async with LocalClient() as me:
        with pytest.raises(AgentError, match=REFUSED):
            await me.call("ledger_decide", repo=root, id="TD-001", lift=True)
    assert entry.read_text("utf-8") == before
    assert not agent._board_adding, "the press's key is let go"
