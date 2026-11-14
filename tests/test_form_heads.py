"""TD-1698 slice 4 (TD-1557's design), §4.5a **<head>…**: every reader hands the page `heads`, a list parallel to
`answers` holding each form's head as offered ('' for a complete answer), and each board item `reply_decides`, so the
page draws **Hold…** and the reply box's foot without matching the shape itself; no reader hands a default where the
marked answer is a form."""

from __future__ import annotations

from test_ui_board import host, item, report
from test_ui_board import reading as boards_reading

from sessionorc import mail as mail_mod
from shiftlead.ui import common
from shiftlead.ui.app import board_rows, ledger_for_you

DECIDE = "decide 2026-11-14 (session `g` on kmaster) — **Go or hold?** Context: TD-1. Due: 2026-11-15."


def _board(tmp_path, monkeypatch, kind, answers, default="", decided=None):
    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    it = {**item(9, DECIDE, "2026-11-15", "due"), "kind": kind, "answers": answers, "default": default}
    if decided:
        it["decided"] = decided
    (row,) = board_rows(report(root, it), {str(root.resolve()): {"name": "samscrape", "label": "samscrape"}})
    return row


def test_a_board_item_hands_heads_and_whether_a_reply_decides(tmp_path, monkeypatch):
    row = _board(tmp_path, monkeypatch, "decide", ["Go", "Hold: <note>"])
    assert row["answers"] == ["Go", "Hold: <note>"] and row["heads"] == ["", "Hold"]
    assert row["reply_decides"] is True
    # a form marked the default is no default: the reader clears what the parse gave
    assert _board(tmp_path, monkeypatch, "decide", ["Go", "Hold: <note>"], default="Hold: <note>")["default"] == ""
    assert _board(tmp_path, monkeypatch, "decide", ["Go", "Hold: <note>"], default="Go")["default"] == "Go"
    # a decided line, a line with no form, an `act` line, a `watch` with another form: no Reply decides
    assert not _board(tmp_path, monkeypatch, "decide", ["Go", "Hold: <note>"], decided="Go")["reply_decides"]
    plain = _board(tmp_path, monkeypatch, "decide", ["Go", "Stop"])
    assert plain["heads"] == ["", ""] and not plain["reply_decides"]
    assert not _board(tmp_path, monkeypatch, "act", ["Go", "Hold: <note>"])["reply_decides"]
    assert not _board(tmp_path, monkeypatch, "watch", ["Works", "Hold: <note>"])["reply_decides"]
    # a look offering another form is no live look, and a Reply on it still decides
    look = _board(tmp_path, monkeypatch, "look", ["Works", "Hold: <note>"])
    assert look["pair"] is False and look["reply_decides"] is True and look["heads"] == ["", "Hold"]
    pair = _board(tmp_path, monkeypatch, "watch", ["Works", "Not right: <what>"])
    assert pair["pair"] is True and pair["reply_decides"] is True and pair["heads"] == ["", "Not right"]


def test_a_ledger_rows_heads_stay_in_step_when_blanks_drop(tmp_path, monkeypatch):
    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    rs = boards_reading(report(root))
    led = {
        "for_page": "for-you",
        "priority": "medium",
        "owner": "paul",
        "id": "TD-60",
        "title": "yours",
        "answers": ["Go", " ", "Hold: <note>"],
        "consequences": ["it ships", "", "it waits"],
        "default": 2,
    }
    rs[str(root)]["ledger"] = {"path": "docs/ledger", "entries": [led]}
    row = next(r for g in ledger_for_you(rs, [], {})["groups"] for r in g["rows"])
    assert row["answers"] == ["Go", "Hold: <note>"] and row["heads"] == ["", "Hold"]
    assert row["consequences"] == ["it ships", "it waits"]
    assert row["default"] == ""  # its marked answer is a form: no Go with it
    led["default"] = 0
    row = next(r for g in ledger_for_you(rs, [], {})["groups"] for r in g["rows"])
    assert row["default"] == "Go"


def test_a_mail_entry_hands_heads_filtered_and_clipped_with_its_answers():
    read = mail_mod.read_answers({"kind": "ask", "answers": ["Go — it ships", "Hold: <note> (default) — it waits"]})
    assert read["answers"] == ["Go", "Hold: <note>"] and read["heads"] == ["", "Hold"]
    assert read["recommended"] is None
    e = {"kind": "ask", "answers": ["Go", "", 3, "Hold: <note>"], "heads": ["", "", "", "Hold"]}
    assert common.suggested_answers(e) == ["Go", "Hold: <note>"]
    assert common.suggested_heads(e) == ["", "Hold"]
    # a `heads` out of step with the answers reads as no forms; no answers, no heads
    assert common.suggested_heads({"answers": ["Go", "Hold: <note>"], "heads": ["Hold"]}) == ["", ""]
    assert common.suggested_heads({"answers": None}) == []
    many = {"answers": [f"a{i}" for i in range(9)] + ["Hold: <note>"], "heads": [""] * 9 + ["Hold"]}
    assert len(common.suggested_heads(many)) == len(common.suggested_answers(many)) == mail_mod.ANSWERS_MAX
    assert mail_mod.form_heads(["Go", "not right :", "Hold: x"]) == ["", "not right", ""]
