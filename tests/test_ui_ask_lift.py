"""An `ask --lift`'s lifting answer on the page (design §4.5a *Inbox row: suggested answers*, §4.10 *An `ask` that
lifts the person's gate*, TD-1833): drawn as **Lift the hold** is — its title and its confirm — on an ask that is not
orphaned; any other answer, and an orphaned ask's, are drawn as before."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

import shiftlead.ui.app  # noqa: E402, F401 — registers every template global the row reads
from shiftlead.ui.common import lifts_hold, templates  # noqa: E402

pytestmark = pytest.mark.unit

ASK = {
    "id": "m-1", "kind": "ask", "from": "ao-w", "from_name": "w", "about": "repo#TD-190", "text": "May it go?",
    "answers": ["Lift it — a session goes on", "Keep it — nobody picks it"], "lift": ["Lift it"],
}  # fmt: skip


def test_lifts_hold_reads_the_label_and_never_an_orphaned_ask():
    assert lifts_hold(ASK, "Lift it — a session goes on") == "TD-190"
    assert lifts_hold(ASK, "Lift it") == "TD-190"
    assert lifts_hold(ASK, "Keep it — nobody picks it") == ""
    assert lifts_hold({**ASK, "orphaned": {"how": "closed"}}, "Lift it") == ""
    assert lifts_hold({**ASK, "kind": "steer"}, "Lift it") == ""
    assert lifts_hold({**ASK, "lift": None}, "Lift it") == ""


def test_the_inbox_rows_lifting_answer_carries_lift_the_holds_title_and_confirm():
    t = templates.env.from_string('{% from "inbox_row.html" import answers %}{{ answers(e) }}')
    html = t.render(e=ASK)
    assert html.count('title="lifts the hold on TD-190"') == 1
    assert html.count("Lift the hold on TD-190? Its decision (paul) is lifted now, and the entry can be picked.") == 1
    orphaned = t.render(e={**ASK, "orphaned": {"how": "closed"}})
    assert "lifts the hold" not in orphaned and "data-lift" not in orphaned
