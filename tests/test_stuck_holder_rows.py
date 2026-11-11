"""TD-1497 slice 3 (design §6 rule 13 *What the person sees*, §4.5 screen 6, §4.5a *Queue card / Inbox: stuck row*):
one counted item for one cause. A `needs_you` actor's stuck words are a line under its own pending row, never a row.
Where a stopped holder's state row names the stuck work's actor on the same surface (one card, or both in the Inbox),
the stuck words are a line under it alone and the work's own row stays where it was, in no number; on two surfaces
each row is drawn, the stuck words ending *— its holder row is on <TD-n>* or *— its holder row is in the Inbox*."""

from __future__ import annotations

import pytest
from test_stuck_board_rows import line
from test_stuck_board_rows import stuck as board_stuck
from test_stuck_rows import reading
from test_ui_queue import NOW, queue

from shiftlead import cli
from shiftlead.ui.inbox import inbox_sections, stuck_rows
from shiftlead.ui.queue import attach, card_index, card_view, queue_view


def drawn(e, sec):
    return f'<div class="mailrow" data-msg="{e.get("id")}">{e.get("text")}</div>'


def state(row="limited", sid="g7", name="techlead-1", text="the profile is at its cap"):
    """A session's state row as `state_rows` builds it, the fields this rule reads."""
    return {"row": row, "id": f"{sid}:{row}", "sid": sid, "name": name, "subject": f"{row} · {name}", "text": text,
            "team": "", "at": "", "age": ""}  # fmt: skip


def sections(stuck, states=(), boards=(), held_on=None):
    """`held_on`: the card row the actor's claim draws its holder row on (`holder:<sid>`), else the Inbox."""
    q = queue()
    index = card_index(q)
    if held_on:
        index = {**index, "holder:g7": index[held_on], "holder:g1": index[held_on]}
    rows = [*states, *stuck_rows(stuck, now=NOW)]
    secs = inbox_sections([], now=NOW, states=rows, boards=list(boards), cards=index)
    return q, secs


def every(secs):
    return [r for k in ("needs", "steering", "waiting", "answered", "later", "fyi", "snoozed") for r in secs[k]]


@pytest.mark.unit
def test_a_needs_you_actors_stuck_words_are_a_line_under_its_pending_row_never_a_row():
    _, secs = sections(reading(reason={"state": "needs_you", "name": "techlead-1"}), states=[state("question")])
    (r,) = every(secs)
    assert r["row"] == "question" and secs["count"] == 1, "the pending row alone, counted once"
    (ln,) = r["stuck_lines"]
    assert ln["id"] == "ask:m-9" and ln["text"].startswith("stuck 1h 30m: grinder-2's ask to techlead-1 — ")
    # with no pending row on the page (the record gone since the reading), it is drawn nowhere
    _, secs = sections(reading(reason={"state": "needs_you", "name": "techlead-1"}))
    assert not every(secs) and secs["count"] == 0


@pytest.mark.unit
def test_a_needs_you_actors_decided_line_stays_under_waiting_on_them_its_words_under_the_pending_row():
    st = board_stuck(reason={"state": "needs_you", "name": "grinder-1"})
    _, secs = sections(st, states=[state("permission", sid="g1", name="grinder-1")], boards=[line()])
    (w,) = secs["waiting"]
    assert w["key"] == "board:k1" and not w.get("stuck"), "never moved: its words are the pending row's line"
    (p,) = secs["needs"]
    assert p["row"] == "permission" and p["stuck_lines"][0]["text"].startswith("stuck 1h 30m: the Go on TD-21")


@pytest.mark.unit
def test_a_stopped_holder_in_the_inbox_takes_the_line_of_a_stuck_ask_homed_there_one_counted_item():
    _, secs = sections(reading(about="", repo="db"), states=[state()])
    (r,) = every(secs)
    assert r["row"] == "limited" and r["home"] == "inbox" and secs["count"] == 1
    assert r["stuck_lines"][0]["text"].startswith("stuck 1h 30m: grinder-2's ask to techlead-1 — techlead-1 is at")


@pytest.mark.unit
def test_a_stopped_holder_on_the_same_card_takes_the_line_alone_and_the_card_draws_no_stuck_item():
    q, secs = sections(reading(about="TD-21"), states=[state()], held_on="s#TD-020")
    (r,) = every(secs)
    assert (r["row"], r["home"], r["on_card"]) == ("limited", "queue", "s#TD-20") and secs["count"] == 1
    assert len(r["stuck_lines"]) == 1
    got = attach(secs, drawn, raw=True)
    v = card_view(q, got, "TD-21", NOW, [], words=False)
    assert not any(m.get("kind") == "stuck" for want in ("do", "decide") for m in v["wants"][want])
    text = "\n".join(cli._card_text(v))
    assert "    stuck 1h 30m: grinder-2's ask to techlead-1 — techlead-1 is at its usage cap" in text


@pytest.mark.unit
def test_on_two_surfaces_each_row_is_drawn_the_stuck_words_saying_where_the_holder_row_is():
    # the holder's row on TD-10's card, the work on TD-20's
    _, secs = sections(reading(about="TD-21"), states=[state()], held_on="s#TD-010")
    stuck = next(r for r in secs["needs"] if r["row"] == "stuck")
    holder = next(r for r in secs["needs"] if r["row"] == "limited")
    assert stuck["on_card"] == "s#TD-20" and holder["on_card"] == "s#TD-10" and secs["count"] == 2
    assert stuck["text"].endswith("— its holder row is on s#TD-10") and not holder.get("stuck_lines")
    # the holder's row in the Inbox, the work on a card
    _, secs = sections(reading(about="TD-21"), states=[state()])
    stuck = next(r for r in secs["needs"] if r["row"] == "stuck")
    assert stuck["home"] == "queue" and stuck["text"].endswith("— its holder row is in the Inbox")


@pytest.mark.unit
def test_a_moved_decided_line_goes_back_under_waiting_on_them_where_its_holder_row_takes_the_line():
    st = board_stuck()  # grinder-1 (g1), limited
    _, secs = sections(st, states=[state(sid="g1", name="grinder-1")], boards=[line(refs=())])
    (w,) = secs["waiting"]
    assert w["key"] == "board:k1" and not w.get("stuck") and not w.get("standing") and w.get("waiting_on")
    (h,) = secs["needs"]
    assert h["row"] == "limited" and secs["count"] == 1
    assert h["stuck_lines"][0]["text"].startswith("stuck 1h 30m: the Go on s's board — grinder-1 is at")


@pytest.mark.unit
def test_two_stuck_works_under_one_holder_row_read_once_the_second_as_on_the_first():
    two = {**reading(mid="m-1", about="", repo="db"), **reading(mid="m-2", about="", repo="db")}
    _, secs = sections(two, states=[state()])
    (r,) = every(secs)
    a, b = r["stuck_lines"]
    assert a["text"].startswith("stuck 1h 30m: grinder-2's ask to techlead-1 — techlead-1 is at its usage cap")
    assert b["text"] == "stuck 1h 30m: grinder-2's ask to techlead-1 — techlead-1, as on grinder-2's ask to techlead-1"


@pytest.mark.unit
def test_the_holder_row_draws_its_stuck_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    q, secs = sections(reading(about="TD-21"), states=[state()], held_on="s#TD-020")
    v = queue_view(q, NOW, attach(secs, drawn))
    assert v  # the page builds
    (r,) = every(secs)
    html = ui.templates.get_template("queue_mail.html").render(e={**r, "want": "do"}, section="needs", origin="")
    assert "stuckline" in html and "stuck 1h 30m: grinder-2&#39;s ask to techlead-1" in html
