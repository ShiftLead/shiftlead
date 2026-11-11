"""*One open question per sender per seat* is counted over the seat's records (design §4.9 *Mail to a scaled
seat*, TD-1547): an open ask from the sender on the seat's own record or on any extra of it refuses a second ask
to either, while each record's mailbox depth stays its own; an extra of another seat, or of another team or
repo, is not the same seat — and a moved ask lands through `_landing_refusal` on those terms."""

from __future__ import annotations

import pytest

from sessionorc import mail, models
from sessionorc.models import MailEntry


def _rec(sid: str, name: str, team: str = "beta", project: str = "B", **kw) -> models.Session:
    s = models.Session(id=sid, name=name, kind="claude", adapter="claude-code", dir=f"/{name}", team=team)
    s.project, s.repo = project, "/r"
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _graph() -> dict[str, models.Session]:
    recs = [
        _rec("ao-tl", "tl", seat={"trigger": "asks"}),
        _rec("ao-tl-2", "tl-2", seat={"trigger": "asks"}, scale={"line": "tl"}),
        _rec("ao-tl-3", "tl-3", seat={"trigger": "asks"}, scale={"line": "tl"}),
        _rec("ao-fc-2", "fc-2", seat={"trigger": "asks"}, scale={"line": "fc"}),  # another seat's extra
        _rec("ao-tl-x", "tl", team="gamma", seat={"trigger": "asks"}),  # a seat of the same name, another team
        _rec("ao-tl-o", "tl-4", seat={"trigger": "asks"}, scale={"line": "tl"}, repo="/o"),  # same seat, another repo
        _rec("ao-a", "a", team="alpha", project="A"),
    ]
    return {r.id: r for r in recs}


def _open_ask(g, on: str, mid: str = "m-1") -> None:
    g[on].inbox.append(MailEntry(id=mid, from_="ao-a", to=[on], at="2026-11-11T00:00:00Z", kind="ask", text="q"))


@pytest.mark.unit
def test_seat_records_are_the_seat_and_its_extras_of_its_team():
    g = _graph()
    assert mail.seat_records(g, "ao-tl") == ["ao-tl", "ao-tl-2", "ao-tl-3"]
    assert sorted(mail.seat_records(g, "ao-tl-2")) == ["ao-tl", "ao-tl-2", "ao-tl-3"]
    assert mail.seat_records(g, "ao-a") == ["ao-a"], "no seat: itself alone"


@pytest.mark.unit
@pytest.mark.parametrize("on, to", [("ao-tl-2", "ao-tl"), ("ao-tl", "ao-tl-3"), ("ao-tl-2", "ao-tl-2")])
def test_an_open_ask_on_any_record_of_the_seat_refuses_a_second(on, to):
    g = _graph()
    assert mail.message_gate(g, "ao-a", to, kind="ask") is None
    _open_ask(g, on)
    refused = mail.message_gate(g, "ao-a", to, kind="ask")
    assert refused and "m-1 is still open" in refused


@pytest.mark.unit
def test_another_seats_extra_and_a_same_named_seat_of_another_team_are_not_the_seat():
    g = _graph()
    _open_ask(g, "ao-fc-2")
    _open_ask(g, "ao-tl-x", mid="m-2")
    _open_ask(g, "ao-tl-o", mid="m-3")
    assert "ao-tl-o" not in mail.seat_records(g, "ao-tl"), "an extra of the same team and line in another repo"
    assert mail.message_gate(g, "ao-a", "ao-tl", kind="ask") is None


@pytest.mark.unit
def test_a_moved_ask_does_not_block_itself_and_another_open_ask_still_does():
    """The moved copy has an id of its own and its original's root; the original stays open until the copy lands."""
    g = _graph()
    _open_ask(g, "ao-tl")
    g["ao-tl"].inbox[0].root = "m-1"
    assert mail.open_question(g, {"ao-a"}, "ao-tl-2", thread="m-1") is None
    assert mail.open_question(g, {"ao-a"}, "ao-tl-2").id == "m-1"
    _open_ask(g, "ao-tl-3", mid="m-9")
    g["ao-tl-3"].inbox[0].root = "m-9"
    assert mail.open_question(g, {"ao-a"}, "ao-tl-2", thread="m-1").id == "m-9"


@pytest.mark.integration
def test_a_moved_ask_lands_on_an_extra_and_another_open_ask_on_the_seat_refuses_it(agent):
    """The landing check (`_landing_refusal`, §4.9b *The move is a landing, not a send*) counts over the seat's
    records and passes the moved ask's root, so the copy of an ask still open on the seat lands on an extra,
    while a distinct ask open on another record of the seat refuses it (TD-1657)."""
    g = _graph()
    _open_ask(g, "ao-tl")
    g["ao-tl"].inbox[0].root = "m-1"
    moved = MailEntry(id="m-mv", from_="ao-a", to=["ao-tl-2"], at="2026-11-11T00:01:00Z", kind="ask", text="q")
    moved.root = "m-1"
    assert agent._landing_refusal(g, "ao-a", "ao-tl-2", moved) is None, "its own original does not block it"
    _open_ask(g, "ao-tl-3", mid="m-9")
    g["ao-tl-3"].inbox[0].root = "m-9"
    refused = agent._landing_refusal(g, "ao-a", "ao-tl-2", moved)
    assert refused == "your question m-9 to it is still open", "an open ask on another record of the seat"
