"""TD-918, design §4.4 *Waiting*, *The card's status*, *A move lands*; §4.5 screen 12 *Waiting*, *Up next*;
§4.5a *Queue page, Waiting: the wait column*; §4.7 `ao rank --list`: a card nobody can pick now and the person
is not holding up is Waiting — unnumbered, unmoved, saying what it waits for from a leaf and where it would be
in Up next."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_queue import NOW, _by_id, _cards, _entry, _repo

from sessionorc import rank, settle


def _read(tmp: Path, entries: list[str], **marks: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The cards of one repo `r`, its `Waits:` lines marked as the home marks them, `marks` per id set on top."""
    root, r = _repo(tmp, "r", entries)
    settle.mark_waits(r["ledger"]["entries"], NOW)
    for e in r["ledger"]["entries"]:
        e.update(marks.get(e["id"].replace("-", "_"), {}))
    return _by_id(_cards({root: r}))


HELD = {"held": {"at": NOW.isoformat()}}


def test_blocked_only_by_the_persons_entry_is_up_next_and_beside_an_open_id_it_waits_on_that_id(tmp_path):
    cards = _read(tmp_path, [
        _entry(1, "the person's", Priority="High", Owner="paul"),
        _entry(2, "after it alone", Priority="High", Blocked_by="TD-001"),
        _entry(11, "the person's too", Priority="Medium", Owner="paul"),
        _entry(12, "an event", Priority="Medium", Waits="event — the next promote"),
        _entry(13, "after both", Priority="Medium", Blocked_by="TD-011, TD-012"),
    ])  # fmt: skip
    one, two = cards["r#TD-001"], cards["r#TD-011"]
    assert one["group"] == "up_next" and one["wait"] is None and one["place"] == 1, "its unblock is the person's"
    assert two["group"] == "waiting" and two["place"] is None and two["places"] == []
    assert two["wait"] == {"column": "event", "phrase": "waits on the next promote", "id": "r#TD-012"}
    assert two["status"] == "needs you", "the status word is unchanged by `waits`"


def test_the_wait_columns_order_top_entry_then_earliest_date_then_event_then_the_reasons(tmp_path):
    cards = _read(tmp_path, [
        # the top entry's own Waits: line comes first, though a row's date is earlier
        _entry(10, "top waits", Priority="High", Waits="until 2026-10-30 — the trial"),
        _entry(11, "row waits sooner", Priority="High", Waits="until 2026-10-20", Blocked_by="TD-010"),
        # a top entry with none: the earliest date of the rows
        _entry(20, "a live check", Priority="High", Kind="live-check #5"),
        _entry(21, "later", Priority="High", Waits="until 2026-10-25", Blocked_by="TD-020"),
        _entry(22, "sooner", Priority="High", Waits="until 2026-10-22", Blocked_by="TD-020"),
        _entry(23, "an event", Priority="High", Waits="event — x", Blocked_by="TD-020"),
        # no date: an event before settling and a build not yet live
        _entry(30, "a live check", Priority="High", Kind="live-check #6"),
        _entry(31, "an event", Priority="High", Waits="event — the reset", Blocked_by="TD-030"),
        _entry(32, "settling", Priority="High", Blocked_by="TD-030"),
        # settling before not live
        _entry(40, "a live check", Priority="High", Kind="live-check #7"),
        _entry(41, "settling", Priority="High", Blocked_by="TD-040"),
        _entry(50, "a live check alone", Priority="High", Kind="live-check #8 #9"),
        _entry(60, "another's decision", Priority="High", Blocked_by="decision (techlead)"),
        _entry(70, "a typo'd id", Priority="High", Blocked_by="TD-999"),
        _entry(71, "another repo's", Priority="High", Blocked_by="nowhere#TD-1"),
    ], TD_032={"settling": True}, TD_041={"settling": True})  # fmt: skip
    wait = {k: c["wait"] for k, c in cards.items()}
    assert wait["r#TD-010"] == {"column": "Oct 30", "phrase": "waits until Oct 30", "id": "r#TD-010"}
    assert wait["r#TD-020"] == {"column": "Oct 22", "phrase": "waits until Oct 22", "id": "r#TD-022"}
    assert wait["r#TD-030"] == {"column": "event", "phrase": "waits on the reset", "id": "r#TD-031"}
    assert wait["r#TD-040"] == {"column": "settling", "phrase": "settling", "id": "r#TD-041"}
    assert wait["r#TD-050"] == {"column": "not live", "phrase": "not live #8 #9", "id": "r#TD-050"}
    assert wait["r#TD-060"] == {"column": "blocked", "phrase": "blocked: decision (techlead)", "id": "r#TD-060"}
    assert wait["r#TD-070"] == {"column": "blocked", "phrase": "blocked: TD-999 unresolved", "id": "r#TD-070"}
    assert wait["r#TD-071"]["phrase"] == "blocked: nowhere#TD-1 unresolved"
    assert {c["group"] for c in cards.values()} == {"waiting"}
    assert all(c["place"] is None for c in cards.values())


def test_a_date_that_has_begun_reads_as_unwritten(tmp_path):
    cards = _read(tmp_path, [_entry(1, "past", Priority="High", Waits="until 2026-10-16")])
    assert cards["r#TD-001"]["group"] == "up_next" and cards["r#TD-001"]["wait"] is None


def test_a_cycle_of_open_ids_reads_as_past_reach(tmp_path):
    cards = _read(tmp_path, [
        _entry(80, "one", Priority="High", Blocked_by="TD-081"),
        _entry(81, "two", Priority="High", Blocked_by="TD-082"),
        _entry(82, "three", Priority="High", Blocked_by="TD-080"),
        _entry(90, "a", Priority="High", Blocked_by="TD-091"),
        _entry(91, "b", Priority="High", Blocked_by="TD-090"),
    ])  # fmt: skip
    (three,) = [c for c in cards.values() if "r#TD-080" in c["order"]]
    (two,) = [c for c in cards.values() if "r#TD-090" in c["order"]]
    assert two["group"] == "waiting"
    said = "blocked: TD-090 and TD-091 block each other"
    assert two["wait"] == {"column": "blocked", "phrase": said, "id": "r#TD-090"}
    assert three["wait"]["phrase"] == "blocked: TD-080, TD-081 and TD-082 block each other"


def test_in_progress_is_in_progress_whatever_waits_says(tmp_path):
    from test_queue import _rec

    root, r = _repo(tmp_path, "r", [_entry(1, "an event", Priority="High", Waits="event — x")])
    settle.mark_waits(r["ledger"]["entries"], NOW)
    (c,) = _cards({root: r}, [_rec("w", root, "TD-001")])["cards"]
    assert c["group"] == "in_progress" and c["wait"] is None


def test_up_next_is_numbered_without_gaps_and_a_waiting_card_would_be_its_place(tmp_path):
    cards = _read(tmp_path, [
        _entry(1, "high", Priority="High"),
        _entry(2, "high, waits", Priority="High", Waits="until 2026-11-01"),
        _entry(3, "medium", Priority="Medium"),
        _entry(4, "low, waits", Priority="Low", Waits="event — y"),
    ])  # fmt: skip
    assert [(k, c["group"], c["place"]) for k, c in cards.items()] == [
        ("r#TD-001", "up_next", 1), ("r#TD-002", "waiting", None), ("r#TD-003", "up_next", 2),
        ("r#TD-004", "waiting", None)]  # fmt: skip
    assert cards["r#TD-002"]["would_be"] == [{"repo": "r", "n": 2}]
    assert cards["r#TD-004"]["would_be"] == [{"repo": "r", "n": 3}]
    assert cards["r#TD-001"]["would_be"] == []


def test_a_waiting_card_refuses_a_move_and_is_no_neighbour(tmp_path):
    cards = list(_read(tmp_path, [
        _entry(1, "high", Priority="High"),
        _entry(2, "waits", Priority="High", Waits="event — z"),
        _entry(3, "medium", Priority="Medium"),
    ]).values())  # fmt: skip
    with pytest.raises(rank.Refused, match="r#TD-002's card is Waiting, which does not move"):
        rank.intent(cards, ["r#TD-002"], None, "r#TD-001", "person", NOW.isoformat())
    with pytest.raises(rank.Refused, match="r#TD-002's card is Waiting, not in Up next"):
        rank.intent(cards, ["r#TD-003"], "r#TD-002", None, "person", NOW.isoformat())
    # moving past it in the whole Up next order: TD-001 and TD-003 are adjacent there
    assert rank.intent(cards, ["r#TD-003"], None, "r#TD-001", "person", NOW.isoformat()) is not None


def test_an_old_clock_held_mark_is_no_status_and_no_need(tmp_path):
    """TD-1297: the clock keeps no hold, so a `held` mark left on an entry is read as nothing — a card reads
    by its members as they are; an entry held out of the lanes is a `decision (<person>)` row."""
    cards = _read(tmp_path, [
        _entry(1, "marked, waits", Priority="High", Waits="event — a"),
        _entry(2, "waits", Priority="High", Waits="event — b", Blocked_by="TD-001"),
        _entry(11, "marked", Priority="Medium", Blocked_by="TD-012"),
        _entry(12, "ready", Priority="Medium"),
    ], TD_001=HELD, TD_011=HELD)  # fmt: skip
    assert (cards["r#TD-001"]["status"], cards["r#TD-001"]["group"]) == ("waiting", "waiting")
    assert (cards["r#TD-012"]["status"], cards["r#TD-012"]["group"]) == ("ready", "up_next")
    assert all(r["state"] != "held (person)" for c in cards.values() for r in [c["top"], *c["rows"]])


def test_the_page_draws_waiting_between_in_progress_and_up_next_with_its_wait_column(tmp_path, monkeypatch):
    """§4.5 screen 12 *Waiting*, §4.5a *Queue page, Waiting: the wait column* and *group heading*."""
    import test_ui_queue as tq

    q = tq.queue()
    wait = {"column": "Oct 30", "phrase": "waits until Oct 30", "id": "s#TD-40"}
    q["cards"].insert(1, tq.card(tq.row("s", "TD-40", "read the trial back"), group="waiting", status="waiting",
                                 wait=wait, would_be=[{"repo": "s", "n": 2}], places=[]))  # fmt: skip
    html = tq.client(monkeypatch, tmp_path, tq.fake(q)).get("/queue").text
    assert html.index('id="qinprogress"') < html.index('id="qwaiting"') < html.index('id="qupnext"')
    waits = html[html.index('id="qwaiting"') : html.index('id="qupnext"')]
    assert 'Waiting <span class="qshare" data-of="1">(1)</span>' in waits
    assert 'data-card="s#TD-40"' in waits and "g-waiting" in waits
    assert '<span class="qn">Oct 30</span>' in waits and "would be 2 in s" in waits
    assert '<span class="qstatus s-waits"' in waits and ">waits until Oct 30</span>" in waits
    assert "qmove" not in waits and "draggable" not in waits, "no grip and no ⤒ ↑ ↓"
    assert 'data-card="s#TD-40"' not in html[html.index('id="qupnext"') :]
    assert "4 cards: 1 in progress, 1 waiting, 2 up next." in html


def test_the_repo_boards_gutter_draws_a_waiting_cards_wait_column_and_no_grip():
    """§4.5 screen 11 *For you*: a Waiting card's gutter draws the wait column and no grip (TD-918)."""
    import test_ui_repo_board as tb

    w = tb.card("r#TD-1", [tb.entry("TD-1")], group="waiting")
    w.update(wait={"column": "event", "phrase": "waits on x", "id": "r#TD-1"}, would_be=[{"repo": "r", "n": 3}])
    g = tb.rb.board({"cards": [w], "upnext": []}, [], [("grind", tb.TD)], [], "r")["stages"][1]["groups"][0]
    assert (g["up"], g["place"], g["wait"]["column"], g["would_be"]) == (False, None, "event", 3)


def test_ao_rank_list_prints_waiting_unnumbered_after_in_progress_with_its_phrase(tmp_path, monkeypatch, capsys):
    """§4.7 `ao rank --list` (TD-918), and `ao rank` refuses a Waiting card in `rank.intent`'s words."""
    from test_queue import _rec

    from shiftlead import cli

    root, r = _repo(tmp_path, "r", [
        _entry(1, "high", Priority="High"),
        _entry(2, "waits", Priority="High", Waits="until 2026-10-30"),
        _entry(3, "held", Priority="Low"),
    ])  # fmt: skip
    settle.mark_waits(r["ledger"]["entries"], NOW)
    cards = _cards({root: r}, [_rec("w", root, "TD-003")])["cards"]
    monkeypatch.setattr(cli, "call_sync", lambda rpc, **kw: {"cards": cards})
    assert cli.main(["rank", "--list"]) == 0
    out = [ln.split() for ln in capsys.readouterr().out.splitlines()]
    assert [(ln[0], ln[1]) for ln in out] == [("·", "r#TD-003"), ("·", "r#TD-002"), ("1", "r#TD-001")]
    assert " ".join(out[1]).endswith("waits until Oct 30")
    monkeypatch.setattr(cli, "_td_repo", lambda repo: (str(root), str(root)))
    assert cli.main(["rank", "TD-002", "--top"]) != 0
    assert "TD-002's card is Waiting, which does not move" in capsys.readouterr().err
