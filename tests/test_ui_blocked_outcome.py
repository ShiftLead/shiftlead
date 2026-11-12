"""TD-1695 (TD-1556's drawing half): a `blocked` outcome draws as Do, never Decide, and a replied one leaves for FYI
(design §4.10 *Outcomes*, §4.4 *A `blocked` outcome keeps the word*, §4.5 screen 12 *Three wants*, §4.5a *Inbox row:
`blocked` outcome*)."""

from datetime import UTC, datetime

import pytest
from markupsafe import Markup
from test_queue_wants import NOW, item, queue
from test_ui_inbox import answered, entry, handed_entry, rows, sections_of

from shiftlead.ui.queue import attach, queue_view, want_of

AT = datetime(2026, 9, 19, 12, tzinfo=UTC)


def steer(mid, **kw):
    """A steer the person answered (`answered` makes an ask)."""
    return {**answered(mid, **kw), "kind": "steer"}


LIVE = [{"id": "ao-w1", "state": "working"}]
BLOCKED = {"state": "blocked", "text": "needs your token", "at": "2026-09-19T11:30:00Z", "by": "m-9"}
REPLIED = {**BLOCKED, "replied": {"at": "2026-09-19T11:45:00Z", "by": "m-10"}}


@pytest.mark.unit
def test_a_blocked_outcome_is_do_before_its_kind_and_read_in_fyi():
    for kind in ("ask", "steer"):
        assert want_of({"kind": kind, "outcome": BLOCKED}, "needs") == "do", kind
        assert want_of({"kind": kind, "outcome": REPLIED}, "fyi") == "read", kind  # READ_LINES first
    assert want_of({"handed_row": True, "kind": "ask", "outcome": BLOCKED}, "needs") == "do"  # a handed entry's
    assert want_of({"kind": "ask", "outcome": {"state": "done"}}, "needs") == "decide"  # only `blocked` moves


@pytest.mark.unit
def test_a_td1529_shaped_row_is_counted_once_and_its_card_reads_do_1_never_decide():
    """A steer answered, its outcome `blocked`, with its reporting note: the question's row is the one need."""
    q = steer("m-1", text="TD-1529: go ahead?", outcome=BLOCKED)
    note = entry("m-9", "note", text="blocked: needs your token")
    got = sections_of([q, note], fleet=LIVE)
    assert [x["id"] for x in got["needs"]] == ["m-1"] and got["count"] == 1 and not got["fyi"]
    v = queue_view(queue(), NOW, attach({"needs": [item("needs", "s#TD-2", **{**q, "id": "m-1"})]},
                                        lambda e, sec: Markup(f"<{e['id']}>")))  # fmt: skip
    assert v["up_next"][1]["wants"]["n"] == {"decide": 0, "do": 1, "read": 0}


@pytest.mark.unit
def test_a_replied_blocked_outcome_is_fyi_uncounted_with_you_replied():
    q = steer("m-1", outcome=REPLIED)
    got = sections_of([q, entry("m-9", "note")], fleet=LIVE, now=AT)
    assert [x["id"] for x in got["fyi"]] == ["m-1"] and got["count"] == 0 and not got["needs"]
    html = rows("fyi", got["fyi"])
    assert "outcome · blocked" in html and "needs your token" in html and "you replied · 15m ago" in html
    # unreplied, the line is not drawn
    got = sections_of([answered("m-2", outcome=BLOCKED)], fleet=LIVE, now=AT)
    assert "you replied" not in rows("needs", got["needs"])


@pytest.mark.unit
def test_an_asked_again_with_was_draws_was_blocked_and_hides_the_replaced_note():
    was = {**REPLIED, "by": "m-9"}
    again = {"state": "asked_again", "text": "", "at": "2026-09-19T11:50:00Z", "by": "m-11", "was": was}
    q = answered("m-1", outcome=again)
    old_note, new_note = entry("m-9", "note", text="blocked: needs your token"), entry("m-11", "note")
    got = sections_of([q, old_note, new_note], fleet=LIVE, now=AT)
    ids = [x["id"] for s in ("needs", "waiting", "fyi", "answered") for x in got[s]]
    assert "m-9" not in ids and "m-11" not in ids  # neither note is a row of its own
    html = rows("fyi", [x for x in got["fyi"] if x["id"] == "m-1"])
    assert "was blocked: needs your token · you replied 15m ago" in html
    # after a newer `done`: the old blocked note is still not an FYI row of its own
    done = {"state": "done", "text": "merged as #9", "at": "2026-09-19T11:55:00Z", "by": "m-12", "was": BLOCKED}
    got = sections_of([answered("m-1", outcome=done), old_note, entry("m-12", "note")], fleet=LIVE, now=AT)
    assert [x["id"] for x in got["fyi"]] == ["m-1"]
    html = rows("fyi", got["fyi"])
    assert "was blocked: needs your token" in html and "you replied" not in html


@pytest.mark.unit
def test_a_handed_entrys_blocked_row_is_do_and_its_own_was_is_drawn():
    from shiftlead.ui.app import handed_rows, inbox_sections

    fleet = {"ao-shiftlead-techlead-ao-1": {"id": "ao-shiftlead-techlead-ao-1", "state": "working"}}
    got = inbox_sections([], now=AT, handed=handed_rows([handed_entry("m-h", outcome=BLOCKED)], fleet, AT))
    (row,) = got["needs"]
    assert want_of(row, "needs") == "do" and got["count"] == 1
    # owing again after a question on its thread took the outcome up: its own `was`, drawn under it
    got = inbox_sections([], now=AT, handed=handed_rows([handed_entry("m-h", was=BLOCKED)], fleet, AT))
    assert "was blocked: needs your token" in rows("waiting", got["waiting"])
