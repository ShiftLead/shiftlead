"""TD-1624 (TD-1543's design), §4.5 screen 12 *Three verbs: Have a session do it*, §4.4 *Decide*, §4.5a *Due strip /
Inbox board row, Queue card item, Repo page board row: Have a session do it*: an open `act` line offers **Have a
session do it** after its Done where a lane of its repo would take the work; the press is the `decide` write-back
with the fixed text, on the board alone, so the line stays open and is a work order; the agent checks the kind on the
line it finds, and the decided line still covers its entries."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from markupsafe import Markup
from test_board import BOARD_TEXT, GATED_ENTRY, git, on_origin, origin_board, repo  # noqa: F401 — `repo` a fixture
from test_queue_card_verbs import dots
from test_queue_item_shape import card, inbox

from sessionorc import board, workorders
from sessionorc.agent_inbox import InboxMixin
from shiftlead.ui import app as ui
from shiftlead.ui.queue import asked_entries, attach, session_asks, split_later

FIXED = "have a session do it"
ACT = "act 2026-11-05 (session `grinder-ao-2` on kmaster) — **Rotate the token.** Context: TD-190. Due: 2026-11-06."
MARKED = (
    "act 2026-11-05 (session `grinder-ao-2` on kmaster) — **Sign in on the phone.** Only YOU can do this. "
    "Context: TD-190. Due: 2026-11-06."
)
DECIDE = "decide 2026-11-05 (session `w` on kmaster) — **Go?** Context: TD-190. Due: 2026-11-06. Answers: Go | Not yet."


def open_(text: str) -> str:
    return f"- [ ] {text}"


# -- the one test of the mark ------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_the_mark_is_read_from_the_lines_own_words_by_one_helper():
    assert board.marked_for_person(MARKED), "followed by fields, in mixed case"
    assert board.marked_for_person(open_(MARKED)), "the whole `- [ ]` line too"
    assert board.marked_for_person("act 2026-11-05 (session w) — Do it; only you can do this!  Due: 2026-11-06.")
    assert board.marked_for_person("Only you can   do this")  # no lead: read from its start
    assert board.marked_for_person(MARKED + " — paul, 2026-11-07: not today"), "a Reply keeps it marked"
    assert board.marked_for_person(MARKED.replace(" Context: TD-190.", " Doer: shiftlead. Context: TD-190."))
    assert not board.marked_for_person(ACT)
    mid = "act 2026-11-05 (session w) — only you can do this, then tell w. Due: 2026-11-06."
    assert not board.marked_for_person(mid), "the words mid-text"
    assert not board.marked_for_person("act 2026-11-05 (session w) — Do it. Context: only you can do this.")


# -- the agent's check -------------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_the_agent_passes_the_fixed_text_only_where_the_line_offers_no_answers():
    assert InboxMixin._board_answer("decide", FIXED, []) == FIXED
    assert InboxMixin._board_answer("decide", "  have a  session do it ", []) == FIXED
    with pytest.raises(board.Refused, match="word for word"):
        InboxMixin._board_answer("decide", "now", [])
    with pytest.raises(board.Refused, match="word for word"):
        InboxMixin._board_answer("decide", FIXED, ["Go", "Not yet"])


@pytest.mark.unit
def test_the_kind_is_checked_on_the_found_line_whatever_the_page_sent():
    got = board.edit_line(open_(ACT), ACT, "decide", answer=FIXED, today="2026-11-07")
    assert got.startswith("- [ ] ") and "Decided: have a session do it" in got
    cases = {
        # any other answer on an `act` line
        (ACT, "now"): board.WORD_FOR_WORD,
        # the fixed text on a decide line, a kindless line, and an act line carrying Answers:
        (DECIDE, FIXED): board.NOT_ACTS_ANSWER,
        ("2026-11-05 (session w) — **Do it.** Due: 2026-11-06.", FIXED): board.NOT_ACTS_ANSWER,
        (ACT.replace("Due: 2026-11-06.", "Due: 2026-11-06. Answers: Yes | No."), FIXED): board.NOT_ACTS_ANSWER,
        # the fixed text on a marked line
        (MARKED, FIXED): board.MARKED,
        # a decided line, whatever is pressed
        (ACT + " Decided: have a session do it (by paul) (2026-11-07).", FIXED): "already decided",
    }
    for (text, answer), words in cases.items():
        with pytest.raises(board.Refused, match=re.escape(words)):
            board.edit_line(open_(text), text, "decide", answer=answer, today="2026-11-07")
    # an answer the line offers is decided as today, whatever its words or kind
    own = ACT.replace("Due: 2026-11-06.", "Due: 2026-11-06. Answers: Yes | No.")
    assert "Decided: Yes" in board.edit_line(open_(own), own, "decide", answer="Yes", today="2026-11-07")
    assert "Decided: Go" in board.edit_line(open_(DECIDE), DECIDE, "decide", answer="Go", today="2026-11-07")
    pair = ACT.replace("Due: 2026-11-06.", "Due: 2026-11-06. Answers: Works | Not right: <what>.")
    got = board.edit_line(open_(pair), pair, "decide", answer="Not right: too slow", today="2026-11-07")
    assert "Decided: Not right: too slow" in got, "the pair's filled form is the line's own answer"


# -- the write: the board half alone -----------------------------------------------------------------------------------


def _on_board(repo: Path, text: str, ledger: bool = True) -> int:  # noqa: F811 — the fixture's name
    """`text` as an open line on origin's board, with the v2 ledger of a gated TD-190 beside it; its line number."""
    if ledger:
        (repo / "docs" / "ledger").mkdir()
        (repo / "docs" / "ledger" / "README.md").write_text("# Ledger\n\nLedgerboard: 2\n")
        (repo / "docs" / "ledger" / "TD-190.md").write_text(GATED_ENTRY)
    (repo / board.BOARD).write_text(BOARD_TEXT.replace("## Needs", "People: paul\n\n## Needs") + f"- [ ] {text}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "act")
    git(repo, "push", "-q", "origin", "main")
    return origin_board(repo).splitlines().index(f"- [ ] {text}") + 1


@pytest.mark.parametrize(
    "context",
    ["TD-190 decision (paul)", "TD-190", "other#TD-190 decision (paul)"],
    ids=["this repos entry and a gate", "no gate", "another repos entry"],
)
def test_the_press_writes_decided_on_the_board_alone_and_the_line_stays_open(repo, context):  # noqa: F811
    text = ACT.replace("Context: TD-190.", f"Context: {context}.")
    at = _on_board(repo, text)
    got = board.write_back(repo, at, text, "decide", answer=FIXED)
    assert "entries" not in got
    files = on_origin(repo, "show", "--name-only", "--format=", "origin/main").split()
    assert files == ["docs/user_attention.md"], "no lift runs, no ledger file changes"
    line = origin_board(repo).splitlines()[at - 1]
    assert line.startswith("- [ ] ") and "Decided: have a session do it (by " in line
    assert "**Blocked by:** decision (paul)" in on_origin(repo, "show", "origin/main:docs/ledger/TD-190.md")
    # and the line is a work order `board:<key>`: open and decided
    key = workorders.ref(repo, line.removeprefix("- [ ] "))
    assert workorders.is_work_order(key)


def test_the_press_on_a_board_with_no_ledger_writes_the_board_alone(repo):  # noqa: F811
    at = _on_board(repo, ACT, ledger=False)
    board.write_back(repo, at, ACT, "decide", answer=FIXED)
    assert origin_board(repo).splitlines()[at - 1].startswith("- [ ] ")


# -- the free-pick test: one function for the draw and the 409 ---------------------------------------------------------


def _org(tmp_path, members: str):
    from shiftlead import org as orgmod

    f = tmp_path / "org.yml"
    f.write_text(
        f"projects:\n  p:\n    repos: {{r: {{h: {tmp_path}}}}}\n"
        f"teams:\n  t:\n    repo: r\n    manager: {{role: person}}\n    members:\n{members}",
        encoding="utf-8",
    )
    return orgmod.load(f)


@pytest.mark.unit
def test_a_lane_would_take_the_work_where_a_servicing_team_has_free_pick(tmp_path):
    from shiftlead import org as orgmod

    grind = _org(tmp_path, "      - {role: grinder, lane: free-pick}\n")
    design = _org(tmp_path, "      - {role: designer, lane: design-first}\n")
    assert ui.road_refusal(grind, str(tmp_path), "session", "h") == ""
    assert ui.road_refusal(design, str(tmp_path), "session", "h") == (
        "no lane of r takes a work order: nobody would take the work"
    )
    none = orgmod.Org(teams={}, roles={})
    assert ui.road_refusal(none, str(tmp_path), "session", "h") == (
        f"no team services {tmp_path.name}: nobody would read the line"
    )
    # the board rows' flag is the same function's
    assert ui.repo_boards(grind, "h")[str(tmp_path.resolve())]["session_do"] is True
    assert ui.repo_boards(design, "h")[str(tmp_path.resolve())]["session_do"] is False


def _route(tmp_path, monkeypatch, refusal: str):
    from fastapi.testclient import TestClient

    from sessionorc import hosts
    from shiftlead import org as orgmod

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    calls: list[tuple[str, dict]] = []
    seen: list[str] = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            calls.append((method, kw))
            return {"line": 3}

    def refuse(_org, root, road, _host):
        seen.append(f"{root} {road}")
        return refusal

    monkeypatch.setattr(ui, "LocalClient", Fake)
    monkeypatch.setattr(ui, "org_here", lambda: (orgmod.Org(teams={}, roles={}), []))
    monkeypatch.setattr(ui, "road_refusal", refuse)
    monkeypatch.setattr(
        hosts, "local_host", lambda: type("H", (), {"name": "h", "repos": lambda self: ["/c/samscrape"]})()
    )
    return TestClient(ui.create_app()), calls, seen


def test_a_stale_press_where_no_lane_would_take_the_work_is_a_409(tmp_path, monkeypatch):
    press = {"action": "board", "board": "/c/samscrape/docs/user_attention.md", "line": 3, "text": ACT,
             "answer": FIXED, "answers": [], "key": "board:0123abcd"}  # fmt: skip
    no_lane = "no lane of samscrape takes a work order: nobody would take the work"
    c, calls, seen = _route(tmp_path, monkeypatch, no_lane)
    got = c.post("/api/person/board", json={**press, "action": "decide"})
    assert got.status_code == 409 and "nobody would take the work" in got.json()["detail"]
    assert seen == ["/c/samscrape session"] and [m for m, _ in calls if m == "board_edit"] == []
    c, calls, _ = _route(tmp_path, monkeypatch, "")
    got = c.post("/api/person/board", json={**press, "action": "decide"})
    assert got.status_code == 200
    assert calls[-1][0] == "board_edit" and calls[-1][1]["answer"] == FIXED and calls[-1][1]["answers"] == []


# -- the button --------------------------------------------------------------------------------------------------------


def _rows(tmp_path, monkeypatch, *items, session_do: bool = True) -> list[dict]:
    from test_ui_board import host, report

    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    of = {"name": "samscrape", "label": "samscrape", "teams": ["sam"], "session_do": session_do}
    return ui.board_rows(report(root, *items), {str(root.resolve()): of})


def _item(text: str, kind: str = "act", **kw) -> dict:
    return {"line": 9, "text": text, "due": "2026-11-06", "overdue_days": 1, "due_tag": "1d overdue", "answers": [],
            "kind": kind, **kw}  # fmt: skip


BUTTON = "data-answer=\"have a session do it\" data-answers='[]'"


def test_an_open_act_line_draws_have_a_session_do_it_after_done_on_a_card_and_in_the_inbox(tmp_path, monkeypatch):
    (b,) = _rows(tmp_path, monkeypatch, _item(ACT))
    assert b["session_do"] is True
    whole = card(b, "do")
    row = whole[whole.index("qanswers") : whole.index('class="row gap wrap mfoot"')]
    assert row.index('data-board-act="done"') < row.index(BUTTON), "after Done, in the answer row"
    assert ">Have a session do it</button>" in row and 'title="Asks a session to do this step' in row
    assert row.count(BUTTON) == 1 and whole.count(BUTTON) == 1
    page = inbox(b)
    foot = page[page.index('class="row gap wrap mfoot"') :]
    assert foot.index('data-board-act="done"') < foot.index(BUTTON), "after the footer's Done"
    assert page.count(BUTTON) == 1


def test_no_button_where_it_is_not_offered(tmp_path, monkeypatch):
    decided = {"text": FIXED, "date": "2026-11-07"}
    cases = {
        "no free-pick lane": _rows(tmp_path, monkeypatch, _item(ACT), session_do=False),
        "decided": _rows(tmp_path, monkeypatch, _item(ACT, decided=decided)),
        "answers": _rows(tmp_path, monkeypatch, _item(ACT, answers=["Yes", "No"])),
        "marked": _rows(tmp_path, monkeypatch, _item(MARKED)),
        **{k: _rows(tmp_path, monkeypatch, _item(DECIDE, kind=k)) for k in ("decide", "look", "watch", "fyi")},
        "kindless": _rows(tmp_path, monkeypatch, _item(ACT.removeprefix("act "), kind="")),
    }
    for why, (b,) in cases.items():
        assert b["session_do"] is False, why
        for html in (card(b, "do"), card(b, "read", "waiting"), inbox(b), inbox(b, section="waiting")):
            assert BUTTON not in html and "Have a session do it" not in html, why


def test_a_pressed_line_waits_and_back_draws_no_second_button(tmp_path, monkeypatch):
    (b,) = _rows(tmp_path, monkeypatch, _item(ACT, decided={"text": FIXED, "date": "2026-11-07"}))
    waiting = card({**b, "waiting_on": "waiting on the next session to read samscrape's board"}, "read", "waiting")
    assert dots(waiting) == ["Done, Open board"] and BUTTON not in waiting
    back = inbox(b)  # back among the Do items after BOARD_WAIT_DAYS: Reply, Snooze and Done, nothing more
    assert ">Reply</button>" in back and ">Snooze</summary>" in back and ">Done</button>" in back
    assert BUTTON not in back


# -- the decided line still covers its entries -------------------------------------------------------------------------


def _line(**kw) -> dict:
    return {"row": "board", "id": "board:/r:3", "key": "board:k1", "kind": "act", "repo_name": "r",
            "text": "**Rotate it.** Context: TD-050. Due: 2026-11-20.", "parts": [], "decided": None, **kw}  # fmt: skip


def _ledger_row(n: int, **kw) -> dict:
    q = f"r#TD-{n:03d}"
    return {"row": "ledger", "id": f"TD-{n:03d}", "row_id": f"ledger:r:TD-{n:03d}", "name": "r", "why": "decision",
            "later_section": "later", "home": "queue", "on_card": q, "on_row": q, **kw}  # fmt: skip


@pytest.mark.unit
def test_an_act_line_decided_have_a_session_do_it_still_asks_and_a_decided_decide_line_does_not():
    pressed = _line(decided={"text": FIXED, "date": "Nov 7"})
    assert session_asks(pressed) and asked_entries([pressed]) == {"r#TD-050"}
    assert not session_asks(_line(decided={"text": "Go", "date": "Nov 7"}))
    assert asked_entries([_line(kind="decide", decided={"text": "Go", "date": "Nov 7"})]) == set()
    # the Inbox's *Later* leaves out the entry's own row where the waiting line covers it
    lf = {"groups": [{"repo": "r", "rows": [{"row": "ledger", "id": "TD-050", "name": "r", "qid": "r#TD-050"}]}]}
    kept, *_ = split_later(lf, [], None, waiting=[pressed])
    assert kept["n"] == 0
    kept, *_ = split_later(lf, [], None, waiting=[_line(kind="decide", decided={"text": "Go", "date": "Nov 7"})])
    assert kept["n"] == 1


@pytest.mark.unit
def test_the_waiting_line_covers_its_entry_on_its_card():
    pressed = {**_line(decided={"text": FIXED, "date": "Nov 7"}), "home": "queue", "on_card": "r#TD-050",
               "on_row": "r#TD-050", "covers": ["r#TD-050"]}  # fmt: skip

    def drawn(e, sec):
        return Markup(e.get("key") or e.get("row_id"))

    got = attach({"waiting": [pressed]}, drawn, [_ledger_row(50)])
    assert [m["html"] for m in got["cards"]["r#TD-050"].get("needs") or ()] == [], "no block of its own"
    assert [m["html"] for m in got["cards"]["r#TD-050"]["waiting"]] == ["board:k1"]
    other = {**pressed, "decided": {"text": "Go", "date": "Nov 7"}, "kind": "decide"}
    got = attach({"waiting": [other]}, drawn, [_ledger_row(50)])
    assert [m["html"] for m in got["cards"]["r#TD-050"]["needs"]] == ["ledger:r:TD-050"]
