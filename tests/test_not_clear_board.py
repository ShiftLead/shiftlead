"""**Not clear** on a board line (design §4.10 *Text a person reads is checked at its writer*, rule 6, *a board line*;
TD-1853): the fixed answer `board.NOT_CLEAR` is taken on a `decide` and an `act` line whatever answers it offers,
checked against the line found, never a kind the page sent, and written to the board alone — no gate in its
`Context:` lifted or logged — so the decided line is a work order."""

from __future__ import annotations

import re

import pytest
from test_board import git, on_origin, origin_item, repo  # noqa: F401 — `repo` a fixture
from test_have_a_session_do_it import ACT, DECIDE, _decided, _it, _on_board

from sessionorc import board, workorders
from sessionorc.agent_inbox import InboxMixin

FIXED = board.NOT_CLEAR
LOOK = "look 2026-11-05 (session w) — **Does it draw?** Due: 2026-11-06. Answers: Works | Not right: <what>."


@pytest.mark.unit
def test_the_agent_takes_the_fixed_text_whatever_answers_the_line_offers():
    assert InboxMixin._board_answer("decide", FIXED, []) == FIXED
    assert InboxMixin._board_answer("decide", FIXED, ["Go", "Not yet"]) == FIXED
    assert InboxMixin._board_answer("decide", f"  {FIXED} ", ["Go"]) == " ".join(FIXED.split())
    assert board.not_clear(DECIDE, FIXED) and board.not_clear(ACT, FIXED)
    assert not board.not_clear(DECIDE, "Go") and not board.session_do(DECIDE, FIXED)


def test_a_decide_and_an_act_line_take_it_and_any_other_kind_is_refused(tmp_path):
    for text in (DECIDE, ACT, ACT.replace("Due: 2026-11-06.", "Due: 2026-11-06. Answers: Yes | No.")):
        got = board.edit_item(_it(tmp_path, text), "decide", answer=FIXED, today="2026-11-07")
        assert _decided(got) == (None, FIXED)
    for text in (LOOK, "2026-11-05 (session w) — **Do it.** Due: 2026-11-06."):
        with pytest.raises(board.Refused, match=re.escape("Not clear answers a decide or an act line")):
            board.edit_item(_it(tmp_path, text), "decide", answer=FIXED, today="2026-11-07")
    with pytest.raises(board.Refused, match="already decided"):
        board.edit_item(_it(tmp_path, DECIDE + " Decided: Go (by paul) (2026-11-07)."), "decide", answer=FIXED)


@pytest.mark.parametrize("kind", ["decide", "act"])
def test_a_gated_line_so_decided_is_written_on_the_board_alone_and_its_gate_stands(repo, kind):  # noqa: F811
    text = (DECIDE if kind == "decide" else ACT).replace("Context: TD-190.", "Context: TD-190 decision (paul).")
    ref = _on_board(repo, text)
    got = board.write_back(repo, None, "", "decide", answer=FIXED, key=ref)
    assert "entries" not in got
    files = on_origin(repo, "show", "--name-only", "--format=", "origin/main").split()
    assert files == [f"docs/user_attention/{got['id']}.md"], "no lift runs, no ledger file changes"
    it = origin_item(repo, ref)
    assert it.closed is None and it.decided[0] == FIXED
    entry = on_origin(repo, "show", "origin/main:docs/ledger/TD-190.md")
    assert "**Blocked by:** decision (paul)" in entry and "gate lifted" not in entry and "kept waiting" not in entry
    assert workorders.is_work_order(got["key"]) and got["key"] == ref


# -- the person route: each road, then the count -----------------------------------------------------------------------


def _route(tmp_path, monkeypatch, reply):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from fastapi.testclient import TestClient

    from shiftlead.ui import app as ui

    calls = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "settings":  # the app's own read as it starts
                return {}
            calls.append((method, kw))
            return {"recorded": "w-1"} if method == "witness_press" else dict(reply)

    monkeypatch.setattr(ui, "LocalClient", Fake)
    return TestClient(ui.create_app()), calls, ui


@pytest.mark.unit
def test_the_route_sends_mail_back_and_records_one_press_from_its_reply(tmp_path, monkeypatch):
    c, calls, _ui = _route(tmp_path, monkeypatch, {"writer": "tl", "kind": "steer", "repo": "-"})
    got = c.post("/api/person/notclear", json={"msg": "m-abc"})
    assert got.status_code == 200 and got.json()["writer"] == "tl"
    assert calls == [
        ("inbox_not_clear", {"msg": "m-abc"}),
        ("witness_press", {"word": "not-clear", "target": "steer -:m-abc tl", "dir": ""}),
    ]


@pytest.mark.unit
def test_the_route_decides_a_board_line_with_the_fixed_answer_and_records_it(tmp_path, monkeypatch):
    c, calls, ui = _route(tmp_path, monkeypatch, {"key": "board:0a1b2c3d", "id": "x"})
    body = {"action": "decide", "not_clear": True, "board": "/r/b.md", "text": "Go?", "kind": "act",
            "answers": ["Go", "Not yet"], "key": "board:0a1b2c3d"}  # fmt: skip
    assert c.post("/api/person/board", json=body).status_code == 200
    (method, kw), press = calls
    assert method == "board_edit" and kw["action"] == "decide"
    assert kw["answer"] == board.NOT_CLEAR and kw["answers"] == ["Go", "Not yet"]
    assert press == ("witness_press", {"word": "not-clear", "target": "act -:board:0a1b2c3d -", "dir": ""})


@pytest.mark.unit
def test_the_route_decides_a_ledger_entry_with_the_fixed_words_and_records_it(tmp_path, monkeypatch):
    c, calls, ui = _route(tmp_path, monkeypatch, {"decided": "x"})
    assert (
        c.post("/api/person/ledger", json={"repo": "/s/shiftlead", "id": "TD-7", "not_clear": True}).status_code == 200
    )
    assert calls == [
        ("ledger_decide", {"repo": "/s/shiftlead", "id": "TD-7", "words": ui.LEDGER_NOT_CLEAR}),
        ("witness_press", {"word": "not-clear", "target": "entry shiftlead:TD-7 -", "dir": ""}),
    ]
    assert ui.LEDGER_NOT_CLEAR == "Not clear: rewrite it — the person could not follow it."
