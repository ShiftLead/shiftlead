"""TD-1843 steps 4 and 9 (design §4.5 screen 12 *A press is never left stranded*; §4.5a *Queue card: press line*): the
replied forms of the press line — an *answered — waiting on <asker>* item drawn again after its `blocked` outcome was
replied on (*You answered "…". <asker> could not do it: <text>; you replied <age> ago.*), an exited asker's owed
question the person has replied on since (*You replied <age> ago; <asker> reads it when it is resumed.* then *Reply
again, …*), and a handed entry's `blocked` outcome (*<seat> could not do it: <text>.* then *Start a session, or dismiss
it.*)."""

from __future__ import annotations

from datetime import timedelta

from test_queue import NOW
from test_queue_answer_bar import START, press, slots
from test_queue_could_not_be_done import _owed
from test_queue_could_not_be_done import press_line as needs
from test_queue_item_shape import card
from test_ui_answered_hold import _ask, _render, _repos, _rows
from test_ui_inbox import entry

from shiftlead.ui.inbox import _owing
from shiftlead.ui.queue import HELD_ANSWERED_KEEP

BLOCKED = {"state": "blocked", "text": "the PR is red", "at": (NOW - timedelta(minutes=20)).isoformat()}
REPLIED = {**BLOCKED, "replied": {"at": (NOW - timedelta(minutes=10)).isoformat()}}


def test_a_replied_blocked_hold_carries_its_state_and_reply_age_and_draws_its_own_press_line(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask(answer_given="Yes", outcome=REPLIED, replied_age="10m")])
    o = row["answered"]["outcome"]
    assert o["state"] == "blocked" and o["replied"] is True and o["replied_age"] == "10m"
    html = _render(row, mode="card", home="queue")
    assert press(html) == "qp-idle: You answered “Yes”. designer could not do it: the PR is red; you replied 10m ago."
    # its question row gone from the person inbox's open rows: the age is the outcome's own reply's
    (gone,) = _rows(_repos(tmp_path / "g", "r"), [_ask(answer_given="Yes", outcome=REPLIED)])
    assert gone["answered"]["outcome"]["replied_age"] == "10m"
    # a `done` hold draws its own form, different (step 9's test)
    (done,) = _rows(
        _repos(tmp_path / "d", "r"), [_ask(answer_given="Yes", outcome={**BLOCKED, "state": "done", "text": "#9"})]
    )
    assert done["answered"]["outcome"]["state"] == "done" and not done["answered"]["outcome"]["replied"]
    want = "qp-idle: You answered “Yes” in designer's ask, 30m ago — designer: #9."
    assert press(_render(done, mode="card", home="queue")) == want
    # `ao card`'s words-free cut is left alone: its outcome is not among the keys it keeps
    assert "outcome" not in HELD_ANSWERED_KEEP


def test_an_unreplied_blocked_hold_says_no_reply():
    from shiftlead.ui.app import templates

    o = {"state": "blocked", "text": "red", "replied": False, "replied_age": ""}
    e = {"answered": {"kind": "ask", "mid": "m-1", "asker": "a", "name": "designer", "words": "you answered",
                      "age": "30m", "outcome": o}}  # fmt: skip
    got = templates.env.get_template("inbox_row.html").module.press_line(e, None, e["answered"])
    assert "You answered. designer could not do it: red." in got and "you replied" not in got


def test_owing_stamps_the_persons_reply_age_on_an_owed_question_alone():
    e = entry("m-5", "ask", text="Merge it?", closed_reason="replied")
    e.update(to=["person"], replied_at=(NOW - timedelta(hours=2)).isoformat())
    _owing(e, {"state": "exited"}, NOW)
    assert e["owes"] and e["owed_replied_age"] == "2h 0m"
    fresh = entry("m-6", "ask", text="Merge it?", closed_reason="replied")
    fresh.update(to=["person"], replied_at=None)
    _owing(fresh, {"state": "exited"}, NOW)
    assert fresh["owed_replied_age"] == "", "a freshly owed one reads the unreplied form"
    settled = entry("m-7", "ask", text="?", closed_reason="replied", outcome={"state": "done", "text": "#1"})
    settled.update(to=["person"], replied_at=NOW.isoformat())
    _owing(settled, {"state": "exited"}, NOW)
    assert settled["owed_replied_age"] == ""


def test_an_exited_askers_question_replied_on_says_so_and_keeps_its_answers():
    e = _owed(answer=1, answer_given="no", owes=True, asker_gone_quiet=True, asker_state="exited", from_open=None)
    fresh = card(e, "do")
    assert "exited without reporting" in needs(fresh) and needs(fresh).endswith(
        "Reply, start a session, or dismiss it."
    )
    html = card({**e, "owed_replied_age": "3h 5m"}, "do")
    assert needs(html) == (
        "You answered &ldquo;no&rdquo;. You replied 3h 5m ago; w1 reads it when it is resumed. "
        "Reply again, start a session, or dismiss it."
    )
    # its answers and Answer… stay pressable, each a further plain reply
    assert slots(html)[:3] == ["Yes", "✓ No", "Answer…"]
    assert 'data-says="yes"' in html


def test_a_handed_entrys_blocked_outcome_draws_its_press_line_and_no_outcome_line():
    e = entry("m-7", "note", text="Draft an entry for the cap", start=START)
    e.update(handed_row=True, holder="ao-tl", holder_name="tl", holder_open="ao-tl", entry={"repo": "r"},
             outcome={"state": "blocked", "text": "cannot reach the repo"})  # fmt: skip
    html = card(e, "do")
    assert needs(html) == "tl could not do it: cannot reach the repo. Start a session, or dismiss it."
    assert "k-outcome" not in html and "mfoot" not in html
    # the Inbox's own row keeps its outcome line and foot
    from test_queue_item_shape import inbox

    row = inbox(e)
    assert "qp-needs" not in row and "k-outcome" in row and "mfoot" in row
