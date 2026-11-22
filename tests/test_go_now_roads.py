# ruff: noqa: F811 — `repo` is the imported fixture, named by each test's argument
"""TD-2027 slice 2, from slice 1's review: the host-side roads of **Go now** (design §4.4 *Go now lifts the design and
its builds*, §4.10 *An `ask` that lifts the person's gate*) over the RPC — a `blocked` outcome's Lift whose `builds`
differ from the set (409, nothing written), `builds` on a reply that does not lift (refused), a lifting answer to an
`ask --lift` sent before its entry became a held build (refused whole, nothing stored), and a lifting answer by `ao
msg` with no `builds` (the set as read is lifted). The held set is the reading's, `queue.held_map` stubbed to one
design and its build; the write is `board.lift_on_press`, recorded and never run (its own tests are
`tests/test_board_lift.py`'s)."""

from __future__ import annotations

import pytest
from test_ask_lift import _ask, _person_copy, _replies, _worker
from test_ledger_lift_press import (
    _entry,
    _home,
    _origin_entry,
    repo,  # noqa: F401 — the `repo` fixture, which each test's argument names
)
from test_ledger_lift_reply import _stopped

from sessionorc import board as board_mod
from sessionorc import queue as queue_mod
from sessionorc.client import AgentError, LocalClient

pytestmark = pytest.mark.integration


def _held(monkeypatch, held: dict[str, str]) -> None:
    """The reading's `{build: design}`, as `held_map` would read it from a design's end-of-rounds line."""
    monkeypatch.setattr(queue_mod, "held_map", lambda *a, **kw: dict(held))


@pytest.fixture
def lifts(monkeypatch) -> list[tuple]:
    """`board.lift_on_press` recorded, never run: `(id, answer, builds)` per call."""
    got: list[tuple] = []

    def fake(root, id, answer="go ahead", held=None, entry_holder=None, builds=()):
        got.append((id, answer, list(builds)))
        return {"lifted": True, "message": "m"}

    monkeypatch.setattr(board_mod, "lift_on_press", fake)
    return got


@pytest.mark.parametrize("sent", [[], ["TD-191", "TD-192"]])
async def test_a_blocked_outcomes_lift_with_differing_builds_is_a_409_and_writes_nothing(
    agent, repo, monkeypatch, lifts, sent
):
    """An empty or grown `builds` through `ledger_lift_reply`: *TD-190's builds changed*, `conflict` (the UI's 409),
    nothing handed to the write, no reply sent and the outcome still unreplied."""
    root = await _home(agent, repo, monkeypatch, [_entry(190), _entry(191)])
    _held(monkeypatch, {"repo#TD-191": "repo#TD-190"})
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            q = await _stopped(person, c, w)
        before = len(_replies(agent, q))
        with pytest.raises(AgentError, match="TD-190's builds changed: read the card again") as err:
            await person.call("ledger_lift_reply", repo=root, id="TD-190", msg=q, builds=sent)
    assert err.value.data.get("conflict") is True
    assert lifts == [] and len(_replies(agent, q)) == before
    assert not _person_copy(agent, q).outcome.get("replied")
    assert "**Blocked by:** decision (paul)" in _origin_entry(repo, 190), "nothing was lifted"


async def test_a_blocked_outcomes_lift_with_matching_builds_lifts_the_set(agent, repo, monkeypatch, lifts):
    """The same road with the page's `builds` matching the set: the write is handed the design and its build."""
    root = await _home(agent, repo, monkeypatch, [_entry(190), _entry(191)])
    _held(monkeypatch, {"repo#TD-191": "repo#TD-190"})
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            q = await _stopped(person, c, w)
        got = await person.call("ledger_lift_reply", repo=root, id="TD-190", msg=q, builds=["TD-191"])
    assert got["lifted"] is True and lifts == [("TD-190", "go ahead", ["TD-191"])]


async def test_builds_on_a_reply_that_does_not_lift_is_refused(agent, repo, monkeypatch, lifts):
    """A plain reply, and a non-lifting answer of a lifting ask, carrying `builds`: refused, nothing stored."""
    await _home(agent, repo, monkeypatch, [_entry(190)])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            plain = (await c.call("msg", to="person", kind="ask", text="ok?", about="repo#TD-190"))["entry"]["id"]
            lifting = await _ask(c)
        with pytest.raises(AgentError, match="builds rides only on an answer that lifts the hold"):
            await person.call("msg", kind="reply", reply_to=plain, text="yes", builds=[])
        with pytest.raises(AgentError, match="builds rides only on an answer that lifts the hold"):
            await person.call("msg", kind="reply", reply_to=lifting, text="Keep it", answer=1, builds=["TD-191"])
    assert lifts == [] and not _replies(agent, plain) and not _replies(agent, lifting)
    assert _person_copy(agent, plain).open and _person_copy(agent, lifting).open


async def test_a_lifting_answer_to_an_ask_sent_before_its_entry_was_held_is_refused_whole(
    agent, repo, monkeypatch, lifts
):
    """The ask about TD-190 passed its send check; TD-190 then became a held build of TD-189's question, so the
    person's lifting answer is refused *TD-190 waits on TD-189's question: answer it there*, its reply not
    recorded and the ask still open."""
    await _home(agent, repo, monkeypatch, [_entry(189), _entry(190)])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            mid = await _ask(c)
        _held(monkeypatch, {"repo#TD-190": "repo#TD-189"})
        with pytest.raises(AgentError, match="TD-190 waits on TD-189's question: answer it there") as err:
            await person.call("msg", kind="reply", reply_to=mid, text="Lift it", answer=0)
    assert err.value.data.get("conflict") is True
    assert lifts == [] and not _replies(agent, mid) and _person_copy(agent, mid).open


async def test_a_lifting_answer_by_ao_msg_with_no_builds_lifts_the_set_as_read(agent, repo, monkeypatch, lifts):
    """`ao msg`'s reply sends no `builds`: the design with a question is lifted with its held builds as the home
    reads them at the answer, the reply carrying `lifted` for the design alone."""
    await _home(agent, repo, monkeypatch, [_entry(190), _entry(191), _entry(192)])
    async with LocalClient() as person:
        w = await _worker(person, repo)
        async with LocalClient(caller=w) as c:
            mid = await _ask(c)
        _held(monkeypatch, {"repo#TD-191": "repo#TD-190", "repo#TD-192": "repo#TD-190"})
        got = await person.call("msg", kind="reply", reply_to=mid, text="Lift it", answer=0)
    assert lifts == [("TD-190", "Lift it", ["TD-191", "TD-192"])]
    assert got["lifted"] == "repo#TD-190" and _person_copy(agent, mid).closed_reason == "replied"
