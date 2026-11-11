"""An extra seat answers for its seat (design §4.9 *A scaled seat holds its review stage*, TD-1547): a record
carrying `seat` whose `scale.line` names a seat is read as that seat wherever a reader is matched by name — the
read of a held PR (`held.read_by`, older form and a chain link's `addressed`), the cadence's `read_by` and
`pr_reads`, which `ao pr held` walks."""

from __future__ import annotations

import pytest
from test_review import _no_gh, _own  # noqa: F401 — the fixture, by name

from sessionorc import cadence, held
from sessionorc.client import LocalClient
from sessionorc.models import PERSON, MailEntry, Session

SEAT, EXTRA = "ao-x-techlead-ao-1", "ao-x-techlead-ao-1-2"


def _seat(sid: str, name: str, scale: dict | None = None) -> Session:
    s = Session(id=sid, name=name, kind="agent", adapter="shell", dir="", seat={"trigger": "asks"})
    s.scale = scale
    return s


GRAPH = [_seat(SEAT, "techlead-ao-1"), _seat(EXTRA, "techlead-ao-1-2", {"line": "techlead-ao-1"})]


def _author(review: dict) -> Session:
    s = Session(id="ao-x-w", name="w", kind="agent", adapter="shell", dir="")
    s.review = review
    return s


def _ask(s: Session, to: str, root: str = "m-1") -> None:
    s.outbox.append(MailEntry(id=root, from_=s.id, to=[to], at="t", kind="ask", text="read it", root=root, pr=845))


def _reply(s: Session, frm: str, root: str = "m-1", verdict: str | None = None) -> None:
    s.inbox.append(
        MailEntry(id="m-r", from_=frm, to=[s.id], at="t", kind="reply", text="read", root=root, verdict=verdict)
    )


@pytest.mark.unit
def test_extras_of_maps_an_extra_seat_to_its_seat_and_nothing_else():
    worker_extra = Session(id="ao-x-grind-3", name="grind-3", kind="agent", adapter="shell", dir="")
    worker_extra.scale = {"line": "grind"}  # a worker line's extra carries no `seat`: rule 14's, no reader
    plain = _seat("ao-x-fc-ao-1", "fc-ao-1")
    assert held.extras_of([*GRAPH, worker_extra, plain]) == {EXTRA: SEAT}
    assert held.as_seat(f"{EXTRA}@laptop", {EXTRA: SEAT}) == SEAT
    assert held.as_seat("ao-x-other", {EXTRA: SEAT}) == "ao-x-other"


@pytest.mark.unit
@pytest.mark.parametrize("asked", [SEAT, EXTRA])
def test_an_extras_reply_is_its_seats_read_in_the_older_form(asked):
    """The ask addressed to the seat (or delivered to the extra): the extra's reply is the read, and without
    the map it is not — so the map is what makes it one."""
    s = _author({"reader": "techlead", "held": ["src/**"], "bound": "2h"})
    _ask(s, asked)
    _reply(s, EXTRA if asked == SEAT else SEAT)
    extras = held.extras_of(GRAPH)
    assert held.read_by(s, 845) is None, "with no map an extra is a stranger to the ask"
    assert held.read_by(s, 845, extras=extras) == (EXTRA if asked == SEAT else SEAT)
    assert cadence.read_by(s, 845) is None
    assert cadence.read_by(s, 845, extras) == (EXTRA if asked == SEAT else SEAT)


@pytest.mark.unit
def test_an_extras_reply_is_its_links_read_in_a_chain():
    chain = {
        "chain": [
            {"stage": "ui", "reader": "ui-reader-ao-1", "held": ["src/shiftlead/ui/**"]},
            {"stage": "review", "reader": "techlead-ao-1", "held": ["src/**"]},
        ],
        "bound": "2h",
    }
    s = _author(chain)
    _ask(s, "ao-x-ui-reader-ao-1", root="m-1")
    _ask(s, SEAT, root="m-2")
    _reply(s, "ao-x-ui-reader-ao-1", root="m-1", verdict="pass")
    _reply(s, EXTRA, root="m-2", verdict="pass")
    files = ["src/shiftlead/ui/app.py", "src/sessionorc/held.py"]
    extras = held.extras_of(GRAPH)
    assert held.read_by(s, 845, files) is None, "unmapped, `techlead-ao-1-2` is no link's reader"
    assert held.read_by(s, 845, files, extras) == EXTRA
    # the extra's `merged` is the last reader's merge, read before any link's reply
    m = _author(chain)
    _ask(m, SEAT, root="m-2")
    _reply(m, EXTRA, root="m-2", verdict="merged")
    assert held.read_by(m, 845, files, extras) == EXTRA
    # rule 10's kept reply, once the mail is pruned, counts for the extra's link
    k = _author(chain)
    k.checks = [{"pr": 845, "read_by": EXTRA}]
    assert held.read_by(k, 845, ["src/sessionorc/held.py"], extras) == EXTRA
    # the person's reply on the thread still makes it the person's
    p = _author(chain)
    _ask(p, EXTRA, root="m-2")
    _reply(p, PERSON, root="m-2")
    assert held.read_by(p, 845, files, extras) == PERSON


@pytest.mark.integration
async def test_pr_reads_names_an_extras_ask_as_its_seats_and_lets_either_read_it(agent, tmp_path):
    """`pr_reads` gives each addressee as its seat, so `ao pr held`'s walk matches an ask an extra holds to the
    seat's link, and the seat's own record and its extra may each read the author's reads."""
    async with LocalClient() as person:

        async def mk(n: str, **kw):
            params = {"name": n, "dir": _own(tmp_path, n), "adapter": "agentshell", "argv": ["bash", "--norc"], **kw}
            return (await person.call("create", **params))["id"]

        w = await mk("w", team="t", unattended=True, review={"reader": "techlead"})
        tl = await mk("tl", team="t", unattended=True)
        extra = await mk("tl-2", team="t", unattended=True, seat={"trigger": "asks"}, scale={"line": "tl"})
        async with LocalClient(caller=w) as wc, LocalClient(caller=tl) as tc, LocalClient(caller=extra) as xc:
            asked = (await wc.call("msg", to=extra, text="#12: the core", kind="ask", pr=12))["entry"]
            await xc.call("msg", reply_to=asked["id"], kind="reply", text="merged #12", verdict="merged")
            got = await wc.call("pr_reads", id=w, pr=12)
            assert [(a["to"], a["verdict"]) for a in got["asks"]] == [([tl], "merged")]
            assert (await tc.call("pr_reads", id=w, pr=12)) == got, "the seat reads its extra's ask"
            assert (await xc.call("pr_reads", id=w, pr=12)) == got
        for sid in (w, tl, extra):
            await person.call("kill", id=sid)
