"""TD-2027 slice 1, design §4.4 *Go now lifts the design and its builds* (TD-2021): every lifting road lifts a design
with a question together with its held builds — `_press_lift` reads the set from `_open_work`'s one `held_map`,
refuses a page's `builds` that differ from it and a lift on a held build alone (each `conflict`, the UI's 409), runs
the press's refusals over every entry of the set, and hands the set to `board.lift_on_press`; `ask --lift` about a
held build is refused at its send. The write itself is `tests/test_board_lift.py`'s."""

from __future__ import annotations

from typing import Any

import pytest
from test_queue import _entry
from test_queue_board_hold import HELD, _open
from test_queue_lift_here import _setup

from sessionorc import board as board_mod
from sessionorc.agent_common import RpcError
from sessionorc.agent_inbox import InboxMixin
from sessionorc.agent_mail import MailMixin

PART = {"Priority": "High", "Part_of": "TD-001", "Blocked_by": "decision (paul)"}
ASK = "TD-001 decision (paul)"


def _rounds(parts: str) -> str:
    """The design's end-of-rounds line, decided *One more round* and open: its `Parts:` the held builds, and
    nothing undecided asks, so the press is drawn (case (b) on the write)."""
    return _open(ASK, decided="One more round (2026-10-15)", parts=parts)


class _Home(InboxMixin, MailMixin):
    """The press's own state alone: the reading, the in-flight keys, the applying marks, no records."""

    def __init__(self, repos: dict[str, Any]) -> None:
        self._repos = repos
        self._board_adding: set[str] = set()
        self._applying: dict[str, Any] = {}
        self._applying_seq = 0
        self.person_inbox: list[Any] = []
        self.marked: list[str] = []
        self.host = "h"

    def _graph(self) -> dict[str, Any]:
        return {}

    async def _applying_push(self, root: str) -> None:
        self.marked.extend(k for k in (self._applying.get(root) or {}) if k not in self.marked)

    async def _reread_board(self, root: str) -> None:
        return None


@pytest.fixture
def lifts(monkeypatch) -> list[tuple]:
    """`board.lift_on_press` recorded, never run: `(id, answer, entry_holder, builds)` per call."""
    got: list[tuple] = []

    def fake(root, id, answer="go ahead", held=None, entry_holder=None, builds=()):
        got.append((id, answer, entry_holder, list(builds)))
        return {"lifted": True, "message": "m"}

    monkeypatch.setattr(board_mod, "lift_on_press", fake)
    return got


def _home(tmp_path, entries=None, *lines) -> tuple[_Home, str]:
    entries = entries or [_entry(1, "the design", **HELD), _entry(2, "build a", **PART), _entry(3, "build b", **PART)]
    root, r = _setup(tmp_path, entries, *(lines or (_rounds("TD-002, TD-003"),)))
    return _Home({root: r}), root


@pytest.mark.unit
async def test_a_lift_of_a_design_with_a_question_lifts_its_held_builds(tmp_path, lifts):
    """With the page's `builds` matching, and with none (the CLI, `ao msg`'s answer), the press lifts the set:
    `lift_on_press` handed the builds in key order, the applying mark over every entry."""
    home, root = _home(tmp_path)
    got = await home._press_lift(root, "TD-001", builds=["TD-002", "TD-003"])
    assert got == {"repo": root, "id": "TD-001", "lifted": True, "builds": ["TD-002", "TD-003"]}
    assert lifts[-1] == ("TD-001", "go ahead", None, ["TD-002", "TD-003"])
    assert home.marked == ["ledger:r#TD-001", "ledger:r#TD-002", "ledger:r#TD-003"]
    assert home._board_adding == set()  # every in-flight key released
    await home._press_lift(root, "TD-001")
    assert lifts[-1][3] == ["TD-002", "TD-003"]


@pytest.mark.unit
@pytest.mark.parametrize("sent", [[], ["TD-002"], ["TD-002", "TD-003", "TD-004"], ["TD-003", "TD-002"]])
async def test_builds_that_differ_from_the_set_are_a_conflict_and_write_nothing(tmp_path, lifts, sent):
    """An empty, short, grown or reordered `builds` is *TD-<design>'s builds changed: read the card again*, carrying
    `conflict` (the UI's 409), nothing handed to the write."""
    home, root = _home(tmp_path)
    with pytest.raises(RpcError, match="TD-001's builds changed: read the card again") as err:
        await home._press_lift(root, "TD-001", builds=sent)
    assert err.value.data == {"conflict": True} and lifts == []
    assert home._board_adding == set()


@pytest.mark.unit
async def test_a_plain_lift_with_no_held_builds_sends_an_empty_list(tmp_path, lifts):
    """A design with no question (no `Parts:` line) lifts alone; the page's empty `builds` matches it."""
    home, root = _home(tmp_path, [_entry(1, "the design", **HELD)], _open(ASK))
    got = await home._press_lift(root, "TD-001", builds=[])
    assert got == {"repo": root, "id": "TD-001", "lifted": True} and lifts[-1][3] == []


@pytest.mark.unit
async def test_a_lift_on_a_held_build_alone_is_refused_after_its_gone_check(tmp_path, lifts):
    home, root = _home(tmp_path)
    with pytest.raises(RpcError, match="TD-002 waits on TD-001's question: answer it there") as err:
        await home._press_lift(root, "TD-002")
    assert err.value.data == {"conflict": True} and lifts == []
    assert await home._press_lift(root, "TD-404") == {"repo": root, "id": "TD-404", "gone": True}


@pytest.mark.unit
async def test_a_build_with_an_open_part_refuses_the_whole_set(tmp_path, lifts):
    """TD-1926's refusal read over the set: the design takes in its build's counted work, and its build's open part
    gives it the fact (TD-2172), so the press is refused whole, naming the work."""
    entries = [
        _entry(1, "the design", **HELD),
        _entry(2, "build a", Priority="High", Part_of="TD-001", Blocked_by="TD-004, decision (paul)"),
        _entry(4, "the build's blocker", Priority="High"),
        _entry(5, "build a's round", Priority="High", Part_of="TD-002"),
    ]
    home, root = _home(tmp_path, entries, _rounds("TD-002"))
    with pytest.raises(RpcError, match="waits on TD-004: it is asked once that closes"):
        await home._press_lift(root, "TD-001", builds=["TD-002"])
    assert lifts == []


@pytest.mark.unit
async def test_a_build_already_being_decided_refuses_the_press(tmp_path, lifts):
    home, root = _home(tmp_path)
    home._board_adding.add(f"ledger:{root}:TD-003")
    with pytest.raises(RpcError, match="TD-003 is already being decided"):
        await home._press_lift(root, "TD-001")
    assert lifts == [] and home._board_adding == {f"ledger:{root}:TD-003"}


@pytest.mark.unit
async def test_the_writes_builds_changed_is_a_conflict(tmp_path, monkeypatch):
    """A build archived or ungated at origin's head (`board.BuildsChanged`) reaches the page as the same 409."""

    def changed(*a, **kw):
        raise board_mod.BuildsChanged(board_mod.builds_changed("TD-001"))

    monkeypatch.setattr(board_mod, "lift_on_press", changed)
    home, root = _home(tmp_path)
    with pytest.raises(RpcError, match="TD-001's builds changed: read the card again") as err:
        await home._press_lift(root, "TD-001", builds=["TD-002", "TD-003"])
    assert err.value.data == {"conflict": True}


@pytest.mark.unit
async def test_ledger_decide_carries_builds_to_the_lift_alone(tmp_path, lifts, monkeypatch):
    from sessionorc import agent_common

    monkeypatch.setattr(agent_common, "person_only", lambda *a, **kw: None)
    home, root = _home(tmp_path)
    await home.rpc_ledger_decide(root, "TD-001", lift=True, builds=["TD-002", "TD-003"])
    assert lifts[-1][3] == ["TD-002", "TD-003"]
    with pytest.raises(RpcError, match="builds is Go now's, a lift's: it takes lift"):
        await home.rpc_ledger_decide(root, "TD-001", answer=0, builds=[])
    with pytest.raises(RpcError, match="builds is a list of entry ids"):
        await home.rpc_ledger_decide(root, "TD-001", lift=True, builds="TD-002")


@pytest.mark.unit
def test_an_ask_lift_about_a_held_build_is_refused_at_its_send(tmp_path):
    home, root = _home(tmp_path)
    with pytest.raises(RpcError, match="TD-002 waits on TD-001's question: answer it there"):
        home._lift_send(["Go"], "ask", ["person"], ["Go", "Not yet"], "TD-002", "r")
