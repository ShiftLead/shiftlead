"""*One open question per sender per seat* is counted over the seat's records (design §4.9 *Mail to a scaled
seat*, TD-1547): an open ask from the sender on the seat's own record or on any extra of it refuses a second ask
to either, while each record's mailbox depth stays its own; an extra of another seat, or of another team or
repo, is not the same seat — and a moved ask lands through `_landing_refusal` on those terms."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sessionorc import mail, models
from sessionorc.agent_common import RpcError
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


# ---- the pair bound over a scaled seat's records (§4.9 *A scaled seat's bounds*, TD-1728) ----

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
AT = "2026-11-12T11:00:00Z"


def _tally(r: models.Session, other: str, n: int) -> None:
    """`n` reply-less entries `r` keeps with `other` inside the window, as `_pair`'s write leaves them."""
    t = r.threads.setdefault(f"pair:{other}", models.Tally())
    t.at += [AT] * n
    t.count = len(t.at)


@pytest.fixture
def bounds(agent, monkeypatch):
    """`_check_bounds` over a graph of its own, a pair bound of 5, and the records it saved."""
    g = _graph()
    saved: list[str] = []
    monkeypatch.setattr(mail, "PAIR_BOUND", 5)
    monkeypatch.setattr(agent, "_graph", lambda: g)
    monkeypatch.setattr(agent, "_save", lambda r: saved.append(r.id))

    def check(sender: str, named: list[str]) -> None:
        agent._check_bounds(sender, named, "", NOW)

    return g, check, saved


def _both(g, a: str, b: str, n: int) -> None:
    """`n` sends between `a` and `b`, tallied on both records as a landing leaves them."""
    _tally(g[a], b, n)
    _tally(g[b], a, n)


@pytest.mark.integration
def test_asks_spread_over_a_seats_records_are_refused_once_their_sum_is_at_the_bound(bounds):
    g, check, _ = bounds
    _both(g, "ao-a", "ao-tl", 3)
    _both(g, "ao-a", "ao-tl-2", 1)
    check("ao-a", ["ao-tl-3"])  # 4 of 5: lands
    _both(g, "ao-a", "ao-tl-3", 1)
    for to in ("ao-tl", "ao-tl-2", "ao-tl-3"):
        with pytest.raises(RpcError, match="ao-a and tl have exchanged 5 messages replying to nothing"):
            check("ao-a", [to])
    assert all(g[k].threads["pair:ao-a"].count < 5 for k in ("ao-tl", "ao-tl-2", "ao-tl-3"))


@pytest.mark.integration
def test_an_extra_writing_to_the_sender_counts_in_the_same_budget(bounds):
    g, check, _ = bounds
    _both(g, "ao-a", "ao-tl", 3)
    _both(g, "ao-tl-2", "ao-a", 2)  # the seat's extra wrote to ao-a
    with pytest.raises(RpcError, match="ao-a and tl have"):
        check("ao-a", ["ao-tl"])
    with pytest.raises(RpcError, match="tl and ao-a have"):
        check("ao-tl-3", ["ao-a"])  # the seat's end named first when it sends


@pytest.mark.integration
def test_bound_hit_lands_on_each_read_tally_with_a_count_and_no_key_is_made(bounds):
    g, check, saved = bounds
    _both(g, "ao-a", "ao-tl", 5)
    with pytest.raises(RpcError):
        check("ao-a", ["ao-tl-2"])
    assert g["ao-a"].threads["pair:ao-tl"].bound_hit and g["ao-tl"].threads["pair:ao-a"].bound_hit
    assert "pair:ao-tl-2" not in g["ao-a"].threads and "pair:ao-a" not in g["ao-tl-2"].threads
    assert "pair:ao-a" not in g["ao-tl-3"].threads
    assert sorted(saved) == ["ao-a", "ao-tl"], "a record holding no tally with a count is not marked"


@pytest.mark.integration
def test_a_check_that_lands_creates_no_tally(bounds):
    g, check, saved = bounds
    check("ao-a", ["ao-tl"])
    assert not any(k.startswith("pair:") for r in g.values() for k in r.threads)
    assert saved == []


@pytest.mark.integration
def test_mail_within_one_seat_counts_on_its_two_records_alone_and_names_them_by_id(bounds):
    g, check, _ = bounds
    _both(g, "ao-tl-2", "ao-tl", 4)
    _both(g, "ao-tl-3", "ao-tl", 4)  # another pair of the seat: not summed in
    check("ao-tl-2", ["ao-tl"])
    _both(g, "ao-tl-2", "ao-tl", 1)
    with pytest.raises(RpcError, match="ao-tl-2 and ao-tl have exchanged 5"):
        check("ao-tl-2", ["ao-tl"])
    assert not g["ao-tl-3"].threads["pair:ao-tl"].bound_hit


@pytest.mark.integration
def test_two_scaled_seats_sum_over_every_record_pair(bounds):
    g, check, _ = bounds
    g["ao-fc"] = _rec("ao-fc", "fc", seat={"trigger": "asks"})
    _both(g, "ao-fc", "ao-tl", 2)
    _both(g, "ao-fc-2", "ao-tl-2", 2)
    check("ao-fc", ["ao-tl-3"])
    _both(g, "ao-fc-2", "ao-tl-3", 1)
    with pytest.raises(RpcError, match="fc and tl have exchanged 5"):
        check("ao-fc", ["ao-tl-3"])


@pytest.mark.integration
def test_a_send_to_two_addressees_marks_the_second_alone(bounds):
    g, check, _ = bounds
    g["ao-b"] = _rec("ao-b", "b", team="alpha", project="A")
    _both(g, "ao-a", "ao-b", 2)
    _both(g, "ao-a", "ao-tl", 5)
    with pytest.raises(RpcError, match="ao-a and tl have"):
        check("ao-a", ["ao-b", "ao-tl"])
    assert not g["ao-a"].threads["pair:ao-b"].bound_hit and not g["ao-b"].threads["pair:ao-a"].bound_hit
    assert g["ao-a"].threads["pair:ao-tl"].bound_hit


@pytest.mark.integration
def test_a_resumed_extra_and_a_resumed_sender_keep_their_count(bounds):
    """A resume moved the tallies to the successor and renamed `pair:<old>` to `pair:<new>`: the keys as they stand."""
    g, check, _ = bounds
    g["ao-tl-2b"] = _rec("ao-tl-2b", "tl-2", seat={"trigger": "asks"}, scale={"line": "tl"})  # resumed ao-tl-2
    g["ao-a2"] = _rec("ao-a2", "a", team="alpha", project="A")  # resumed ao-a
    _both(g, "ao-a2", "ao-tl-2b", 3)
    _both(g, "ao-a2", "ao-tl", 2)
    with pytest.raises(RpcError, match="ao-a2 and tl have"):
        check("ao-a2", ["ao-tl-3"])


@pytest.mark.integration
def test_a_forgotten_seat_records_tallies_leave_the_count(bounds):
    """A forgotten extra leaves the graph, so neither its own tallies nor the other side's `pair:<it>` are read
    (the Fix's sums over `seat_records`' keys; steered to the techlead)."""
    g, check, _ = bounds
    _both(g, "ao-a", "ao-tl", 3)
    _both(g, "ao-a", "ao-tl-2", 3)
    with pytest.raises(RpcError):
        check("ao-a", ["ao-tl"])
    for t in (*g["ao-a"].threads.values(), *g["ao-tl"].threads.values()):
        t.bound_hit = False
    del g["ao-tl-2"]  # forgotten
    check("ao-a", ["ao-tl"])


@pytest.mark.integration
def test_records_that_are_no_seat_are_refused_at_todays_count_by_id(bounds):
    g, check, _ = bounds
    g["ao-b"] = _rec("ao-b", "b", team="alpha", project="A")
    _both(g, "ao-a", "ao-b", 4)
    check("ao-a", ["ao-b"])
    _tally(g["ao-a"], "ao-b", 1)  # one side alone at the bound refuses, as today
    with pytest.raises(RpcError, match="ao-a and ao-b have exchanged 5"):
        check("ao-a", ["ao-b"])


@pytest.mark.integration
def test_the_addressees_sum_alone_at_the_bound_refuses(bounds):
    g, check, _ = bounds
    _tally(g["ao-tl"], "ao-a", 3)  # the seat's records hold the tally; the sender's side holds none
    _tally(g["ao-tl-2"], "ao-a", 2)
    assert "pair:ao-tl" not in g["ao-a"].threads and "pair:ao-tl-2" not in g["ao-a"].threads
    with pytest.raises(RpcError, match="ao-a and tl have exchanged 5"):
        check("ao-a", ["ao-tl"])


@pytest.mark.integration
def test_an_unscaled_seat_is_named_by_its_seat_name(bounds):
    g, check, _ = bounds
    g["ao-qs"] = _rec("ao-qs", "question", team="alpha", seat={"trigger": "asks"})
    _both(g, "ao-a", "ao-qs", 5)
    with pytest.raises(RpcError, match="ao-a and question have"):
        check("ao-a", ["ao-qs"])


@pytest.mark.unit
def test_seat_name_is_an_extras_line_else_its_name():
    g = _graph()
    assert mail.seat_name(g["ao-tl-2"]) == "tl" and mail.seat_name(g["ao-tl"]) == "tl"
