"""TD-1825 (design §4.5 screen 6 *One place for each thing that needs the person*, *Where a row is drawn*,
*Every item that needs the person draws on a card*): a board line that names no entry (`Context: none`) is the
Inbox's, counted in its tab; one whose `Context:` names an entry no open card holds, and that needs the person,
draws on that entry's kept card, else a loose card, counted in the Queue's. Neither is dropped."""

from __future__ import annotations

import pytest
from test_queue_kept_loose import view

pytestmark = pytest.mark.unit


def line(lid: str, context: str, kind: str = "act") -> dict:
    text = f"Sign in, so TD-20 can run — only you can do this. Context: {context}. Due: 2026-10-16"
    return {"row": "board", "id": lid, "kind": kind, "repo_name": "s", "due": "2026-10-16", "text": text}


def homes(secs: dict) -> dict:
    return {e["id"]: (k, e["home"], e["on_card"]) for k in ("needs", "waiting", "fyi") for e in secs[k]}


def test_a_line_naming_no_entry_is_the_inboxs_counted_in_its_tab():
    secs, v = view([], [line("b1", "none")])
    # the TD-20 its text names is no Context ref: the line is the person's to-do, not TD-20's card's
    assert homes(secs) == {"b1": ("needs", "inbox", "")}
    assert secs["count"] == 1 and secs["queue_n"] == 0
    assert v["loose"] == [] and v["kept"] == []


def test_a_line_naming_an_entry_no_open_card_holds_draws_on_its_kept_card_else_a_loose_one():
    secs, v = view([], [line("b2", "TD-3"), line("b3", "TD-077")])  # TD-3 on a completed card; TD-077 on none
    assert homes(secs) == {"b2": ("needs", "queue", "s#TD-3"), "b3": ("needs", "queue", "loose:s#TD-077")}
    assert secs["count"] == 2 and secs["queue_n"] == 2
    assert [c["id"] for c in v["kept"]] == ["s#TD-3"] and [c["id"] for c in v["loose"]] == ["loose:s#TD-077"]
