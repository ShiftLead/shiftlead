"""TD-1843 step 4 (design §4.5 screen 12 *A press is never left stranded*, case *could not be done*): the person's
`inbox` read stamps `replied_at` on each `ask` or `steer` it answered (`replied` or `go_with_it`) that carries no
outcome — the `at` of the person's newest reply in the asker's inbox on that question, not counting the answer that
closed it — so an exited asker's owed question can say *You replied <age> ago*."""

from __future__ import annotations

import pytest
from conftest import park_ticks
from test_answer_waiting import _make_seat

from sessionorc.client import LocalClient
from sessionorc.models import PERSON


def _row(entries, mid):
    return next(e for e in entries if e["id"] == mid)


def _age(agent, sid, mid):
    """Put an earlier reply back in its asker's inbox: `at` is kept to the second, so two replies sent in one
    second would tie and could not tell the newest from the first."""
    (x,) = [x for x in agent._find(sid).inbox if x.id == mid]
    x.at = "2000-01-01T00:00:00Z"


@pytest.mark.integration
async def test_the_persons_read_stamps_their_newest_reply_after_the_answer(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _make_seat(person, tmp_path)
        async with LocalClient(caller=sid) as tl:
            q = (await tl.call("msg", to=PERSON, kind="ask", text="A or B?"))["entry"]
        assert "replied_at" not in _row((await person.call("inbox"))["entries"], q["id"]), "an open one: no key"
        await person.call("msg", to=sid, kind="reply", reply_to=q["id"], text="B")
        row = _row((await person.call("inbox"))["entries"], q["id"])
        assert row["closed_reason"] == "replied" and row["replied_at"] is None, "the answer that closed it is not one"
        again = (await person.call("msg", to=sid, kind="reply", reply_to=q["id"], text="B, as I said"))["entry"]
        assert _row((await person.call("inbox"))["entries"], q["id"])["replied_at"] == again["at"]
        # TD-1906: two replies after the answer — the newest is stamped, not the first
        latest = (await person.call("msg", to=sid, kind="reply", reply_to=q["id"], text="B, still"))["entry"]
        _age(agent, sid, again["id"])
        assert _row((await person.call("inbox"))["entries"], q["id"])["replied_at"] == latest["at"]
        # an outcome settles it: the key is not written
        agent.person_inbox[[e.id for e in agent.person_inbox].index(q["id"])].outcome = {"state": "done", "text": "#1"}
        assert "replied_at" not in _row((await person.call("inbox"))["entries"], q["id"])


@pytest.mark.integration
async def test_a_steer_let_go_with_its_default_counts_its_first_reply(agent, tmp_path):
    await park_ticks(agent)
    async with LocalClient() as person:
        sid = await _make_seat(person, tmp_path)
        async with LocalClient(caller=sid) as tl:
            q = (await tl.call("msg", to=PERSON, kind="steer", default="A", text="A or B?"))["entry"]
        e = next(e for e in agent.person_inbox if e.id == q["id"])
        e.closed_reason, e.closed_at = "go_with_it", e.at  # a go_with_it close has no closed_by
        assert _row((await person.call("inbox"))["entries"], q["id"])["replied_at"] is None
        r = (await person.call("msg", to=sid, kind="reply", reply_to=q["id"], text="and B too"))["entry"]
        assert _row((await person.call("inbox"))["entries"], q["id"])["replied_at"] == r["at"]
        # TD-1906: a second reply is the one stamped, the first counting only while it is the newest
        r2 = (await person.call("msg", to=sid, kind="reply", reply_to=q["id"], text="and C"))["entry"]
        _age(agent, sid, r["id"])
        assert _row((await person.call("inbox"))["entries"], q["id"])["replied_at"] == r2["at"]
