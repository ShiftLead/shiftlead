"""TD-1843 step 5 (design §4.5 screen 12 *A press is never left stranded*, case *could not be done*; §4.4 *Where Lift
the hold is drawn*, *The outcome's lift and reply*): a `blocked` outcome joined by its question's id to the entry row
TD-1879 stamped `answered.lift` on draws that entry's **Lift the hold** first, its press `ledger_lift_reply`, and its
press line's tail names it; and while that outcome is unreplied the entry's *answered — waiting on <asker>* item is not
drawn (*One press, one item*), out of every count and the header's walk, whether or not the outcome draws a Lift."""

from __future__ import annotations

import pathlib
import re
from datetime import timedelta

from test_queue import NOW
from test_queue_answer_bar import START, slots
from test_queue_could_not_be_done import _owed, press_line
from test_queue_item_shape import card
from test_ui_answered_hold import FLEET, _ask, _world

from shiftlead.ui.queue import items_n, walk_mine

APP_JS = (pathlib.Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui" / "static" / "app.js").read_text()
BLOCKED = {"state": "blocked", "text": "the PR is red", "at": (NOW - timedelta(minutes=5)).isoformat()}
Q = "r#TD-060"


def _outcome(**kw):
    """The same question as the person inbox's `blocked` outcome row, attached to the entry's card."""
    return {**_ask(**{"outcome": BLOCKED, **kw}), "home": "queue", "on_card": Q, "on_row": Q}


def test_an_unreplied_blocked_outcome_draws_its_entrys_lift_and_hides_the_answered_item(tmp_path):
    v, drawn = _world(tmp_path, [_ask(outcome=BLOCKED)], asks=[_outcome()])
    (c,) = v["up_next"]
    # the answered item gives way: only the outcome is drawn, carrying the entry's stamp as its Lift
    assert [e.get("row") for e in drawn] == [None]
    (o,) = drawn
    assert o["lift_reply"] == {"root": str(tmp_path / "r"), "id": "TD-60"}
    assert c["wants"]["answered"] == [] and c["wants"]["hidden"] == [Q]
    # out of every count and the walk, and its entry out of the walk's own entries
    assert all(m.get("item") != Q for w in ("decide", "do", "with_you", "answered") for m in c["wants"][w])
    assert walk_mine([Q], c["wants"]) == []


def test_a_replied_outcome_draws_the_answered_item_again_and_no_lift(tmp_path):
    replied = {**BLOCKED, "replied": {"at": NOW.isoformat()}}
    v, drawn = _world(tmp_path, [_ask(outcome=replied)], asks=[_outcome(outcome=replied)])
    (c,) = v["up_next"]
    assert sorted(str(e.get("row")) for e in drawn) == ["None", "ledger"]
    assert all("lift_reply" not in e for e in drawn)
    assert len(c["wants"]["answered"]) == 1 and c["wants"]["hidden"] == []


def test_an_outcome_on_another_question_draws_no_lift_and_hides_nothing(tmp_path):
    # the join is by the question's id alone: an outcome on another question (m-2) draws no Lift and hides nothing
    v, drawn = _world(tmp_path, [_ask(outcome=BLOCKED)], asks=[_outcome(id="m-2")])
    assert [e.get("id") for e in drawn if not e.get("row")] == ["m-2"]
    assert "lift_reply" not in next(e for e in drawn if not e.get("row")), "joined by the question's id alone"
    # m-1's outcome is not on the page: its answered item stays
    assert any(e.get("row") == "ledger" for e in drawn)


def test_the_hidden_item_counts_nowhere_whatever_it_would_draw(tmp_path):
    v, _ = _world(tmp_path, [_ask(outcome=BLOCKED)], asks=[_outcome()])
    (c,) = v["up_next"]
    # the outcome is a Do item; the hidden answered item, which would draw its Start session, adds nothing
    assert items_n(c["wants"]) == 1 and c["wants"]["n"]["do"] == 1
    held = [{**FLEET[0], "unattended": True, "progress": [{"ref": "TD-60", "status": "claimed"}]}]
    v, _ = _world(tmp_path, [_ask(outcome=BLOCKED)], asks=[_outcome()], fleet=held)
    (c,) = v["up_next"]
    assert c["wants"]["hidden"] == [Q] and walk_mine([Q], c["wants"]) == []


def _lifted(**kw):
    e = _owed(answer=0, answer_given="yes", outcome={"state": "blocked", "text": "the PR is red"}, **kw)
    e["lift_reply"] = {"root": "/x/r", "id": "TD-9"}
    return e


def test_the_card_draws_lift_the_hold_first_and_its_tail_names_it():
    html = card(_lifted(), "do")
    tail = "w1 could not do it: the PR is red. Lift the hold, reply, start a session, or dismiss it."
    assert press_line(html).endswith(tail)
    assert slots(html)[:3] == ["Lift the hold", "✓ Yes", "No"]
    lift = re.search(r"<button[^>]*>Lift the hold</button>", html).group(0)
    for attr in ('data-act="ledger"', 'data-repo="/x/r"', 'data-ref="TD-9"', 'data-lift="1"', 'data-lift-reply="m-5"'):
        assert attr in lift, attr
    confirm = "Lift the hold on TD-9? Its decision (paul) is lifted now, and the entry can be picked."
    assert f'data-confirm="{confirm}"' in lift
    # unstamped: no Lift, the plain tail
    plain = card(_owed(answer=0, answer_given="yes", outcome={"state": "blocked", "text": "red"}, start=START), "do")
    assert "data-lift-reply" not in plain and press_line(plain).endswith("Reply, start a session, or dismiss it.")
    assert "Lift the hold" not in press_line(plain)


def test_the_press_sends_lift_reply_and_a_failed_reply_after_the_lift_is_its_own_words():
    assert "want.lift_reply = at.liftReply;" in APP_JS
    assert 'The hold on ${at.ref} is lifted; telling ${at.name || "its asker"} failed: ${res.failed}' in APP_JS
    # stored as sent, so the line never says Nothing was sent
    assert "AO.pressErrs[msgOf] = AO.pressErr(words, true, atSig)" in APP_JS


def test_an_unstamped_outcome_draws_no_lift_and_its_answered_item_still_gives_way():
    """*Whether or not the outcome draws a Lift* (§4.5 *One press, one item*): an entry with no `answered.lift` (its
    `lift_item` unset) still hides its *answered* item behind the unreplied outcome."""
    from markupsafe import Markup

    from shiftlead.ui.queue import HIDDEN, attach

    led = {"row": "ledger", "id": "TD-1", "name": "r", "home": "queue", "on_card": "c", "on_row": "c",
           "answered": {"mid": "m-1", "asker": "a", "kind": "ask", "lift": None}}  # fmt: skip
    mail = {"id": "m-1", "kind": "ask", "outcome": {"state": "blocked", "text": "no"}, "home": "queue",
            "on_card": "c", "on_row": "c"}  # fmt: skip
    drawn: list[dict] = []
    got = attach({"needs": [led, mail]}, lambda e, sec: drawn.append(e) or Markup(""))
    assert [e["id"] for e in drawn] == ["m-1"] and "lift_reply" not in drawn[0]
    assert got["cards"]["c"][HIDDEN] == ["r#TD-001"]
    # a handed entry's outcome is no question: it hides nothing
    drawn.clear()
    attach({"needs": [led, {**mail, "handed": True}]}, lambda e, sec: drawn.append(e) or Markup(""))
    assert sorted(e["id"] for e in drawn) == ["TD-1", "m-1"]


def test_an_outcome_in_the_inbox_alone_or_on_another_card_hides_nothing():
    from markupsafe import Markup

    from shiftlead.ui.queue import HIDDEN, attach

    led = {"row": "ledger", "id": "TD-1", "name": "r", "home": "queue", "on_card": "c", "on_row": "c",
           "answered": {"mid": "m-1", "asker": "a", "kind": "ask", "lift": {"root": "/x/r", "id": "TD-1"}}}  # fmt: skip
    mail = {"id": "m-1", "kind": "ask", "outcome": {"state": "blocked", "text": "no"}}
    # TD-1907: an outcome the Inbox draws that still names the card (its home moved there, its `on_card` kept) hides
    # nothing either: the home is read, not the card alone
    inbox_on_c = {**mail, "home": "inbox", "on_card": "c", "on_row": "c"}
    for other in ({**mail, "home": "inbox"}, inbox_on_c, {**mail, "home": "queue", "on_card": "d", "on_row": "d"}):
        got = attach({"needs": [led, other]}, lambda e, sec: Markup(""))
        assert HIDDEN not in got["cards"].get("c", {}) and got["cards"]["c"]["needs"][0]["item"] == "r#TD-001"


def test_a_failed_reply_after_the_lift_ends_the_cards_hold_as_a_refusal():
    branch = APP_JS.split("if (lifting && at.liftReply) {")[1].split("if (lifting) {")[0]
    assert "AO.qcardBack(msgOf)" in branch and "refusedOn = true;" in branch
