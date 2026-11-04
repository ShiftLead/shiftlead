"""TD-1362, design §4.5 screen 12 *Three verbs*, screen 11 *For you*, screen 6 *Later*: a held entry whose question an
open Decide or Do board line of its repo asks (its `Context:` names the entry) is not drawn beside that line with its
own **Lift the hold** / **Answer…** — on the Inbox's *Later* the entry's row is left out, the line drawn where it
stands, and on the Repo page's *For you* the line is drawn in the row's place, a line not yet due among them."""

from __future__ import annotations

from datetime import timedelta

import pytest
from test_queue import NOW

from shiftlead.ui.queue import asked_entries, split_later

TODAY = NOW.date().isoformat()


def _line(text: str, *, repo: str = "r", kind: str = "decide", decided=None, due_now: bool = True) -> dict:
    """A board row as `board_rows` hands it, cut to what the split reads."""
    return {"row": "board", "id": f"board:/{repo}:3", "repo_name": repo, "text": text, "kind": kind,
            "decided": decided, "due_now": due_now}  # fmt: skip


def _lf(*ids: str, name: str = "r") -> dict:
    rows = [{"row": "ledger", "id": i, "name": name, "why": "decision"} for i in ids]
    return {"n": len(rows), "groups": [{"repo": name, "rows": rows}]}


def _kept(lf) -> list[str]:
    return [r["id"] for g in lf["groups"] for r in g["rows"]]


@pytest.mark.unit
def test_an_open_decide_or_do_line_naming_the_entry_asks_its_question():
    say = "Say Go or Hold. Context: TD-60 / PR #74. Due: 2026-11-04."
    assert asked_entries([_line(say)]) == {"r#TD-060"}, "a bare TD-n is the line's own repo's, `/ PR #n` after it"
    assert asked_entries([_line(say, kind="act")]) == {"r#TD-060"}, "a Do line asks it too"
    assert asked_entries([_line("x. Context: other#TD-60.")]) == {"other#TD-060"}, "a qualified ref is its own"
    assert not asked_entries([_line(say, kind="watch")]), "a watch line is for reading, no question"
    assert not asked_entries([_line(say, decided={"text": "Go", "date": "Nov 4"})]), "a decided line is answered"
    assert not asked_entries([_line("Say Go. Due: 2026-11-04.")]), "no Context: names nothing"
    assert not asked_entries([{"row": "ledger", "text": say}]), "only a board line"


@pytest.mark.unit
def test_later_leaves_out_the_entry_a_drawn_line_asks_about_and_keeps_the_rest():
    say = _line("Say Go or Hold. Context: TD-60 / PR #74.")
    lf, ahead, moved, _ = split_later(_lf("TD-060", "TD-061"), [], {}, [], [say])
    assert _kept(lf) == ["TD-061"] and lf["n"] == 1 and not moved, "the due line is drawn in the entry's place"
    lf, ahead, _, _ = split_later(_lf("TD-060"), [{**say, "due_now": False}], {}, [], [])
    assert _kept(lf) == [] and len(ahead) == 1, "a line not yet due the horizon draws asks it too, and stays drawn"
    assert _kept(split_later(_lf("TD-060"), [], {}, [say], [])[0]) == ["TD-060"], "a line the mode hides does not"
    other = _line("Say Go. Context: TD-60.", repo="s")
    assert _kept(split_later(_lf("TD-060"), [], {}, [], [other])[0]) == ["TD-060"], "another repo's TD-60 is not r's"
    watch = _line("Read it. Context: TD-60.", kind="watch")
    assert _kept(split_later(_lf("TD-060"), [], {}, [], [watch])[0]) == ["TD-060"], "a watch line asks nothing"


# ---- the routes: the Inbox's Later and the Repo page's For you over a fake home ----


def _client(tmp_path, monkeypatch, *, due: bool):
    """A UI over a fake home: repo `r` holding TD-060 on `decision (paul)` with its own answers, and its board one
    open `decide` line whose `Context:` names it, due now (`due`) or a week out."""
    from test_ui_queue import client

    root = tmp_path / "r"
    (root / "docs").mkdir(parents=True)
    board = root / "docs" / "user_attention.md"
    board.write_text("# board\n")
    entry = {"for_page": "for-you", "priority": "medium", "id": "TD-060", "title": "held entry",
             "blocked_by": ["decision (paul)"], "answers": ["Lift", "Keep"], "default": 0}  # fmt: skip
    when = NOW.date() if due else NOW.date() + timedelta(days=7)
    text = f"decide 2026-11-01 — **Say Go or Hold on TD-060.** Context: TD-060 / PR #74. Due: {when.isoformat()}."
    item = {"line": 3, "text": text, "kind": "decide", "decided": None, "due": when.isoformat(),
            "answers": ["Go", "Hold"], "default": "Go", "refs": ["TD-060", "PR #74"], "key": "board:abc12345",
            **({"overdue_days": 0, "due_tag": "due today"} if due else {"due_tag": "due in 7d"})}  # fmt: skip
    repos = {
        str(root): {
            "name": "r",
            "root": str(root),
            "ledger": {"path": "docs/technical_debt.md", "entries": [entry]},
            "boards": {"today": TODAY, "boards": [{"root": str(root), "board": str(board), "items": [item]}]},
        }
    }

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "inbox":
                return {"entries": []}
            return {"repos": repos, "list": [], "host": {"name": "kmaster"}}.get(method, {})

    monkeypatch.setenv("SHIFTLEAD_INBOX_BOARD_SHOW", "all")
    return client(monkeypatch, tmp_path, Fake)


@pytest.mark.parametrize("due", [True, False])
def test_the_inbox_draws_the_line_and_not_the_held_entrys_row(tmp_path, monkeypatch, due):
    c = _client(tmp_path, monkeypatch, due=due)
    html = c.get("/inbox").text
    assert "Say Go or Hold on TD-060" in html, "the line is drawn"
    later = c.get("/api/person/inbox").json()["html"]["ledger"]
    assert "held entry" not in later and ">Keep<" not in later, "the entry's own row is not drawn beside it"


@pytest.mark.parametrize("due", [True, False])
def test_the_repo_pages_for_you_draws_the_line_in_the_entrys_place(tmp_path, monkeypatch, due):
    html = _client(tmp_path, monkeypatch, due=due).get("/repo/r").text
    at, wait = html.index('class="brow"'), html.index(">Waiting on you</a>")
    key = html.index('data-copy="board:abc12345"')
    assert at < key < wait, "the line is drawn in For you's row"
    assert html.count('data-copy="board:abc12345"') == 1, "and is not drawn again under Waiting on you or Not due yet"
    assert "Not due yet" not in html and ">Keep<" not in html, "the entry's own answers are not drawn beside it"
