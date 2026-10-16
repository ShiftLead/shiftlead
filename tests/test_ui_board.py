"""Board items in the Inbox (design §4.5 screen 6, §4.4; TD-069 step 3): the due items of each
repo's `docs/user_attention.md`, read by dev-cadence's own reader, as counted **Needs you** rows."""

from __future__ import annotations

import os
import pathlib
import shutil
from datetime import UTC, date, datetime, timedelta

import pytest
from conftest import fake_gh_bin, with_origin
from fastapi.testclient import TestClient
from test_ui_inbox import needs_line

READER = pathlib.Path(__file__).parents[1] / "scripts" / "nudge_user_attention.py"
LEDGERBOARD = READER.with_name("ledgerboard.py")  # the reader imports it from beside itself


def host(tmp_path, monkeypatch, repos=()):
    """A host whose roster lists `repos`; returns the roster file."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    roster = tmp_path / "repos.txt"
    roster.write_text("".join(f"{r}\n" for r in repos))
    (tmp_path / "home" / "hosts.yml").write_text(
        f"local:\n  name: kmaster\n  local: true\n  repos_registry: {roster}\n"
    )
    return roster


def repo(tmp_path, name, board=None, *, reader=True):
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    if board is not None:
        (root / "docs").mkdir()
        (root / "docs" / "user_attention.md").write_text(board)
    if reader:
        (root / "scripts").mkdir()
        shutil.copy(READER, root / "scripts" / "nudge_user_attention.py")
        shutil.copy(LEDGERBOARD, root / "scripts" / "ledgerboard.py")
    return root


def report(root, *items):
    return {
        "today": "2026-09-22",
        "due_only": True,
        "boards": [
            {
                "label": pathlib.Path(root).name,
                "board": f"{root}/docs/user_attention.md",
                "root": str(root),
                "items": list(items),
            }
        ],
    }


def item(line, text, due, tag):
    # `answers` as a current reader gives it (dev-cadence TD-036): one without it is named (TD-278)
    return {"line": line, "text": text, "due": due, "overdue_days": 1, "due_tag": tag, "answers": []}


def reading(*reports, error=None):
    """The host agent's `repos` reading (§4.4 *The boards*, TD-615) carrying each report as one
    checkout's `boards`, keyed by its root; `error` marks every one's last read as failed."""
    out = {}
    for rep in reports:
        root = rep["boards"][0]["root"]
        bds = {**rep, **({"error": error, "failed_at": "2026-09-22T10:00:00+00:00"} if error else {})}
        out[root] = {"name": pathlib.Path(root).name, "root": root, "boards": bds}
    return out


@pytest.mark.unit
def test_the_board_rows_are_the_host_agents_reading_and_what_it_could_not_read_is_said(tmp_path):
    """§4.4 *Each reading has one owner*, *The boards* (TD-615): the page's board rows are the
    `boards` of the host agent's repo readings — every repo's, each row its reading's id — and the
    page runs no reader. What could not be read is said (§4.5 *no silent failure path*): a failed
    read keeps its last items, and says since when."""
    from shiftlead.ui.app import board_reading

    assert board_reading({}) == ([], "") and board_reading(None) == ([], "")
    a, b = repo(tmp_path, "a", "- [ ] x\n"), repo(tmp_path, "b", "- [ ] y\n")
    one = {**item(3, "x. Due: 2026-09-20.", "2026-09-20", "2d overdue"), "key": "board:0123abcd"}
    rows, note = board_reading(reading(report(a, one), report(b, item(4, "y.", "2026-09-21", "1d overdue"))))
    assert [(r["repo"], r["line"], r["key"]) for r in rows] == [("a", 3, "board:0123abcd"), ("b", 4, "")]
    assert note == ""
    rows, note = board_reading(reading(report(a, one), error="the reader exited 2"))
    assert len(rows) == 1 and note == (
        "the board of a could not be read since 2026-09-22T10:00:00+00:00 (the reader exited 2): "
        "its rows are the last reading"
    )
    assert "no row is shown" in board_reading(reading(report(a), error="x"))[1]
    # a reading taken before its first board read: said, not drawn as an empty board
    assert board_reading({str(a): {"name": "a", "root": str(a)}}) == ([], "the board of a has not been read yet")
    bare = repo(tmp_path, "bare", reader=False)  # no board anywhere is not a fault: nothing to say
    assert board_reading({str(bare): {"root": str(bare), "boards": {"boards": []}}, "x": "junk"}) == ([], "")


@pytest.mark.unit
def test_a_board_row_carries_its_repo_due_words_text_and_the_board_at_its_line(tmp_path, monkeypatch):
    """§4.5 screen 6 (TD-722, built by TD-741): the board is the repo's, so a row carries its repo and
    no team — the repo's teams ride along for the rail, never as a badge."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui.app import board_rows

    root = tmp_path / "samscrape"
    of = {"name": "samscrape", "label": "samscrape", "teams": ["sam-grind", "sam-audit"]}
    rows = board_rows(
        report(root, item(7, "Decide X. Due: 2026-09-20.", "2026-09-20", "2d overdue")), {str(root.resolve()): of}
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["row"] == "board" and r["repo"] == "samscrape" and r["repo_name"] == "samscrape" and r["team"] == ""
    assert r["teams"] == ["sam-grind", "sam-audit"]
    assert r["due_tag"] == "2d overdue" and r["at"] == "2026-09-20" and r["line"] == 7
    assert r["id"] == f"board:{root}:7"
    assert r["editor"]["url"].startswith("vscode://file") and "user_attention.md:7" in r["editor"]["url"]
    assert "decide x" in r["find"] and "samscrape" in r["find"]
    # a repo no team works carries no team, named by its checkout; junk is skipped
    bare = board_rows(report(root, item(1, "t", "2026-09-20", "due")), {})[0]
    assert bare["teams"] == [] and bare["repo"] == bare["repo_name"] == "samscrape"
    # a repo in a project of several repos reads *Project · repo*; its pick is still the repo's name
    of = {"name": "samscrape", "label": "ContractMatch · samscrape", "teams": []}
    (cm,) = board_rows(report(root, item(1, "t", "2026-09-20", "due")), {str(root.resolve()): of})
    assert cm["repo"] == "ContractMatch · samscrape" and cm["repo_name"] == "samscrape"
    assert board_rows({"boards": [{"root": str(root), "items": [{"line": 2}, "x"]}, 3]}) == []
    assert board_rows(None) == [] and board_rows({"boards": "x"}) == []


@pytest.mark.unit
def test_a_repo_maps_to_the_first_team_whose_repo_it_is(tmp_path):
    """§4.9 *Teams* (TD-722): a repo has any number of teams; a board row carries one badge, the first
    team whose `repo:` is that checkout, in definition order."""
    from shiftlead import org as orgmod
    from shiftlead.ui.app import repo_teams

    here = tmp_path / "ao"
    org = orgmod.Org(
        checkouts={"shiftlead": {"kmaster": here, "other": tmp_path / "x"}, "cm": {"other": tmp_path / "cm"}},
        teams={
            "ao-grind": orgmod.TeamDef("ao-grind", repo="shiftlead"),
            "ao-audit": orgmod.TeamDef("ao-audit", repo="shiftlead"),
            "cm-grind": orgmod.TeamDef("cm-grind", repo="cm"),
        },
    )
    assert repo_teams(org, "kmaster") == {str(here.resolve()): "ao-grind"}


@pytest.mark.unit
def test_a_board_row_names_its_repo_and_every_team_that_works_it(tmp_path):
    """§4.5 screen 6, §4.5a *the rail* (TD-722, built by TD-741): the board is the repo's — a row of it
    names the repo, *ContractMatch · samscrape* where its project has several repos, else the repo's
    name, and carries every team whose `repo:` it is in definition order; a checkout no team works is
    named all the same."""
    from shiftlead import org as orgmod
    from shiftlead.ui.app import repo_boards

    ao, sam, web, solo = (tmp_path / n for n in ("ao", "samscrape", "web", "solo"))
    org = orgmod.Org(
        projects={
            "cm": orgmod.Project("cm", repos={"samscrape": {}, "web": {}}, title="ContractMatch"),
            "one": orgmod.Project("one", repos={"shiftlead": {}}, title="ShiftLead"),
        },
        checkouts={
            "shiftlead": {"kmaster": ao},
            "samscrape": {"kmaster": sam},
            "web": {"other": web},
            "solo": {"kmaster": solo},
        },
        teams={
            "ao-grind": orgmod.TeamDef("ao-grind", repo="shiftlead"),
            "sam-grind": orgmod.TeamDef("sam-grind", repo="samscrape"),
            "ao-audit": orgmod.TeamDef("ao-audit", repo="shiftlead"),
            "web-grind": orgmod.TeamDef("web-grind", repo="web"),
        },
    )
    assert repo_boards(org, "kmaster") == {
        str(ao.resolve()): {"name": "shiftlead", "label": "shiftlead", "teams": ["ao-grind", "ao-audit"]},
        str(sam.resolve()): {"name": "samscrape", "label": "ContractMatch · samscrape", "teams": ["sam-grind"]},
        str(solo.resolve()): {"name": "solo", "label": "solo", "teams": []},
    }


@pytest.mark.unit
def test_the_rail_narrows_board_rows_by_repo_and_a_team_pick_by_its_repo():
    """§4.5a *Inbox page: the rail* (TD-722, built by TD-741): a **Repos** group, each repo a board row
    on the page carries with its count, picked by the URL's `repo`; a team pick narrows board rows to
    the team's repo, and a team's count takes in its repo's board rows, so the count and the page
    narrowed to it agree — for each of two teams on one repo."""
    from shiftlead.ui.app import rail_counts, rail_picks, rail_rows

    b1 = {"row": "board", "id": "b1", "teams": ["ao-grind", "ao-audit"], "repo": "shiftlead",
          "repo_name": "shiftlead", "find": "one"}  # fmt: skip
    b2 = {"row": "board", "id": "b2", "teams": ["sam-grind"], "repo": "ContractMatch · samscrape",
          "repo_name": "samscrape", "find": "two"}  # fmt: skip
    ask = {"kind": "ask", "id": "m-1", "team": "ao-grind", "text": "q"}
    rows = rail_rows({"needs": [b1, b2, ask]})
    got = rail_counts(rows, rail_picks({}))
    assert got["teams"]["ao-grind"]["all"] == 2 and got["teams"]["ao-audit"]["all"] == 1
    assert got["teams"]["sam-grind"]["all"] == 1 and "none" not in got["teams"]
    assert got["repo_order"] == ["samscrape", "shiftlead"]
    assert got["repo_labels"] == {"samscrape": "ContractMatch · samscrape", "shiftlead": "shiftlead"}
    assert got["repos"]["shiftlead"] == {"shown": 1, "all": 1}
    # ?repo= narrows to its board rows; a row with no repo is not one of them
    picked = rail_counts(rows, rail_picks({"repo": "shiftlead"}))
    assert picked["filtered"] and picked["heads"]["needs"]["shown"] == 1
    assert picked["repos"]["samscrape"]["shown"] == 0 and picked["teams"]["ao-audit"]["shown"] == 1
    # a team pick shows its repo's board rows: the second team on the repo sees the row and no mail
    audit = rail_counts(rows, rail_picks({"team": "ao-audit"}))
    assert audit["heads"]["needs"]["shown"] == audit["teams"]["ao-audit"]["shown"] == 1
    grind = rail_counts(rows, rail_picks({"team": "ao-grind"}))
    assert grind["heads"]["needs"]["shown"] == grind["teams"]["ao-grind"]["shown"] == 2
    # a repo no team works is under *no team*; a picked repo no row carries keeps its line
    lone = rail_rows({"needs": [{**b1, "teams": []}]})
    assert rail_counts(lone, rail_picks({}))["teams"] == {"none": {"shown": 1, "all": 1}}
    gone = rail_counts(rows, rail_picks({"repo": "gone"}))
    assert gone["repo_order"][-1] == "gone" and gone["repos"]["gone"] == {"shown": 0, "all": 0}


@pytest.mark.unit
def test_next_n_draws_n_per_repo_whichever_teams_work_it():
    """§4.5 screen 6 *The board's horizon* (TD-722, built by TD-741): `next:<n>` is each repo's board's
    n soonest open items — a board counted once, though two teams work its repo."""
    from shiftlead.ui.app import board_horizon

    a = [_row(i, f"2026-10-{i:02d}", root="/a", teams=["g", "h"]) for i in range(1, 6)]
    b = [_row(10 + i, f"2026-10-{i:02d}", root="/b", teams=["g"]) for i in range(1, 6)]
    got = board_horizon(a + b, "next:3")
    assert sorted(r["line"] for r in got["ahead"]) == [1, 2, 3, 11, 12, 13]
    assert len(got["hidden"]) == 4


@pytest.mark.unit
def test_due_board_items_are_counted_in_needs_you_oldest_first_among_the_mail(tmp_path, monkeypatch):
    """§4.5 screen 6: *a due board item* is in **Needs you**, and the section is oldest first
    across every kind — so an item a week overdue sits above a question asked this morning."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui.app import board_rows, inbox_sections

    root = tmp_path / "r"
    boards = board_rows(
        report(root, item(3, "old", "2026-09-12", "10d overdue"), item(4, "today", "2026-09-22", "due today"))
    )
    ask = {
        "id": "m-1", "from": "ao-w", "from_name": "w", "kind": "ask", "text": "q", "at": "2026-09-18T10:00:00Z",
        "closed_at": None, "closed_by": None, "expired_at": None, "closed_reason": None, "snoozed_until": None,
    }  # fmt: skip
    s = inbox_sections([ask], now=datetime(2026, 9, 22, 12, tzinfo=UTC), boards=boards)
    assert [r["id"] for r in s["needs"]] == [boards[0]["id"], "m-1", boards[1]["id"]]
    assert s["count"] == 3 and not s["fyi"] and not s["snoozed"]


@pytest.mark.unit
def test_a_board_row_is_text_and_its_two_answers_carry_what_the_reader_gave(tmp_path, monkeypatch):
    """§4.5a *Due strip / Inbox board row*: the item's text, *open board in VS Code* at that line, **Snooze ▾**
    (+1 day · +1 week · a date) and **Done** (confirms). Each control carries the board, the line and
    the text, which the agent re-checks. The text is the board's, escaped: nothing on the page is a
    control made from it (TD-071 item 8) — it rides only as an attribute value."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui.app import board_rows, templates

    root = tmp_path / "samscrape"
    text = '<b>Allow</b> the "rm". Due: 2026-09-20.'
    of = {"name": "samscrape", "label": "samscrape", "teams": ["sam", "sam2"]}
    rows = board_rows(report(root, item(9, text, "2026-09-20", "2d overdue")), {str(root.resolve()): of})
    html = templates.get_template("inbox_rows.html").render(rows=rows, section="needs")
    assert 'data-kind="board"' in html and 'data-teams="sam sam2"' in html and 'class="mailrow boardrow"' in html
    # the board is the repo's (TD-741): its repo on the row, and no team badge
    assert 'data-repo="samscrape"' in html and "badge team" not in html and "data-team=" not in html
    assert "&lt;b&gt;Allow&lt;/b&gt;" in html and "<b>Allow</b>" not in html
    assert ">samscrape<" in html and "2d overdue" in html and ">board<" in html
    assert "Open board" in html and "user_attention.md:9" in html
    acts = html.count('data-act="board"')
    assert acts == 4  # +1 day, +1 week, a date, Done — and Reply (TD-142) the one other act
    assert html.count('data-act="') == acts + 1 and html.count('data-act="board_reply"') == 1
    assert html.count('data-board-act="snooze"') == 3 and html.count('data-board-act="done"') == 1
    assert html.count('data-line="9"') == 5 and html.count(f'data-board="{root}/docs/user_attention.md"') == 5
    # the line's text is written once, on the row, and every press reads it there (TD-738)
    assert html.count('data-text="&lt;b&gt;Allow&lt;/b&gt; the &#34;rm&#34;. Due: 2026-09-20."') == 1
    row = html[html.index('class="mailrow boardrow"') :].split(">")[0]
    assert 'data-text="&lt;b&gt;Allow&lt;/b&gt;' in row
    assert all("data-text=" not in t.split(">")[0] for t in html.split("<button")[1:])
    assert 'data-when="1d"' in html and 'data-when="1w"' in html and 'data-when="pick"' in html
    done = html[html.index('data-board-act="done"') :]
    assert "data-confirm=" in done.split(">")[0]


@pytest.mark.unit
def test_snooze_and_done_go_to_the_host_agents_write_back_and_the_page_reads_no_board(tmp_path, monkeypatch):
    """The route (§4.4, TD-069 step 3) hands the row's board, line and text to `board_edit`,
    caller-less — the person's own act. The host agent re-reads the board before it answers (§4.4
    *The boards*, TD-615), so the press reads nothing itself: the next draw takes the agent's
    reading. What it cannot know is refused before the agent is asked."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui import app as uiapp

    reads, calls, replies = [], [], []

    class Fake:
        def __init__(self, *a, **k):
            self.kw = k

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "repos":
                reads.append(1)
            if method == "board_edit":
                calls.append((self.kw.get("caller"), kw))
                return {"commit": "abc123", "message": "shiftlead: done x (session n/a)"}
            if method == "board_reply":
                replies.append(kw)
                return {"commit": "def456", "sent": [], "note": "written on the board"}
            return {"list": [], "inbox": {"entries": [], "trail": []}}.get(method, {})

    monkeypatch.setattr(uiapp, "LocalClient", Fake)
    board = str(tmp_path / "r/docs/user_attention.md")
    with TestClient(uiapp.create_app()) as c:
        c.get("/api/person/inbox")
        drawn = len(reads)
        assert drawn  # the page drew its board rows from the agent's reading
        r = c.post("/api/person/board", json={"action": "done", "board": board, "line": 4, "text": "x"})
        assert r.status_code == 200 and r.json()["commit"] == "abc123"
        assert len(reads) == drawn  # the agent's re-read is in its reading: the press reads nothing
        r = c.post(
            "/api/person/board",
            json={
                "action": "snooze",
                "board": board,
                "line": "4",
                "text": "x",
                "due": "2026-09-30",
                "key": "board:0a1b2c3d",
            },
        )
        assert r.status_code == 200
        # the row's id rides along (§4.4 *A board line's id*, TD-607); a press without one sends it empty
        assert [k for _, k in calls] == [
            {"board": board, "line": 4, "text": "x", "action": "done", "due": None, "key": ""},
            {"board": board, "line": 4, "text": "x", "action": "snooze", "due": "2026-09-30", "key": "board:0a1b2c3d"},
        ]
        assert all(caller is None for caller, _ in calls)  # a person is not a session
        # TD-142: Reply goes to `board_reply` with the reader's refs
        r = c.post(
            "/api/person/board",
            json={
                "action": "reply", "board": board, "line": 4, "text": "x", "reply": " rebase it ", "refs": ["TD-9"],
                "key": "board:0a1b2c3d",
            },
        )  # fmt: skip
        assert r.status_code == 200 and replies == [
            {"board": board, "line": 4, "text": "x", "reply": "rebase it", "refs": ["TD-9"], "key": "board:0a1b2c3d"}
        ]
        assert len(reads) == drawn
        for bad in ({"reply": ""}, {"line": "four"}, {"board": ""}):
            body = {"action": "reply", "board": board, "line": 4, "text": "x", "reply": "y", **bad}
            assert c.post("/api/person/board", json=body).status_code == 400
        assert len(replies) == 1
        for bad in (
            {"action": "delete", "board": board, "line": 4, "text": "x"},
            {"action": "done", "board": board, "line": "four", "text": "x"},
            {"action": "done", "board": "", "line": 4, "text": "x"},
            {"action": "snooze", "board": board, "line": 4, "text": "x"},
        ):
            assert c.post("/api/person/board", json=bad).status_code == 400
        assert len(calls) == 2


@pytest.mark.unit
def test_the_rows_of_a_real_board_read_by_the_host_agents_reader(tmp_path, monkeypatch):
    """End to end over a real board, the real reader and the host agent's reading of it
    (`workorders.read_boards`, TD-615): an overdue item and one due today are due-now rows, an
    undated one and one due next week are rows not yet due (TD-220); the team comes from the org's
    projects, and each row's id is the reading's."""
    past = (date.today() - timedelta(days=3)).isoformat()
    later = (date.today() + timedelta(days=7)).isoformat()
    board = (
        "# Board\n\n"
        f"- [ ] overdue thing. Due: {past}.\n"
        f"- [ ] due today. Due: {date.today().isoformat()}.\n"
        "- [ ] undated thing.\n"
        f"- [ ] next week. Due: {later}.\n"
        f"- [x] done already. Due: {past}.\n"
    )
    root = repo(tmp_path, "proj", board)
    host(tmp_path, monkeypatch, [root])
    (tmp_path / "home" / "org.yml").write_text(
        f"projects:\n  proj:\n    repos:\n      proj: {{kmaster: {root}}}\n"
        "teams:\n  proj-grind:\n    repo: proj\n    manager: {role: manager}\n"
    )
    from sessionorc import workorders
    from shiftlead.ui import app as uiapp

    got = {str(root): {"name": "proj", "root": str(root), "boards": workorders.read_boards(root, fetch=False)}}
    rows, note = uiapp.board_reading(got, uiapp.repo_boards(uiapp.org_here()[0], uiapp.host_name()))
    assert note == ""
    assert all(r["key"] == workorders.ref(root, r["text"]) and r["key"].startswith("board:") for r in rows)
    # every open item is read (TD-220), the ones due now marked; the closed one is not an item
    assert [(r["text"].split(".")[0], r["due_now"]) for r in rows] == [
        ("overdue thing", True),
        ("due today", True),
        ("undated thing", False),
        ("next week", False),
    ]
    assert [r["ahead"] for r in rows[2:]] == [
        "no due date",
        f"due in 7 d · {date.today() + timedelta(days=7):%b} {(date.today() + timedelta(days=7)).day}",
    ]
    rows = [r for r in rows if r["due_now"]]
    assert (
        rows[0]["line"] == 3
        and rows[0]["repo"] == "proj"
        and rows[0]["teams"] == ["proj-grind"]
        and rows[0]["team"] == ""
    )
    assert "overdue" in rows[0]["due_tag"]


@pytest.mark.unit
def test_the_page_the_top_bar_and_the_poll_carry_the_board_rows_and_the_note(tmp_path, monkeypatch):
    """One count in three places (§4.5a **Inbox page**): the board rows join the page, the poll and
    the Org's top bar through the same `inbox_sections`; the reading's note is drawn and polled. The
    rows are the host agent's reading (§4.4 *The boards*, TD-615): no surface runs a reader — a spy
    on `subprocess.run` sees none."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui import app as uiapp

    root = tmp_path / "proj"
    later = {**item(4, "look next week", "2026-09-30", "due 2026-09-30"), "overdue_days": None}
    rep = report(root, item(3, "decide the thing", "2026-09-20", "2d overdue"), later)
    rows = uiapp.board_rows(rep)
    calls = []
    monkeypatch.setattr("subprocess.run", lambda *a, **k: calls.append(a) or pytest.fail(f"a reader was run: {a}"))

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            return {
                "list": [],
                "inbox": {"entries": [], "trail": []},
                "usage": {},
                "gate": {},
                "host": {"name": "kmaster", "mode": "home"},
                "identity": {},
                "repos": reading(rep, error="a note from the reader"),
            }.get(method, {})

    monkeypatch.setattr(uiapp, "LocalClient", Fake)
    with TestClient(uiapp.create_app()) as c:
        page = c.get("/inbox").text
        assert "decide the thing" in page and needs_line(page) == "1"
        # not yet due: drawn under *Not due yet*, counted nowhere (TD-220 slice 3)
        assert "look next week" in page and "Not due yet" in page and needs_line(page) == "1"
        assert "a note from the reader" in page and 'id="boardnote"' in page
        got = c.get("/api/person/inbox").json()
        assert got["needs"] == 1 and got["sections"]["needs"] == [rows[0]["id"]]
        assert (
            "(a note from the reader): its rows are the last reading" in got["board_note"]
            and "decide the thing" in got["html"]["needs"]
        )
        assert 'id="personneeds">1</span>' in c.get("/").text
    assert calls == []


@pytest.mark.unit
def test_with_the_host_agent_down_no_surface_counts_the_board(tmp_path, monkeypatch):
    """The three surfaces agree while the host agent is down (review of PR #472): the Org's top bar
    and the poll claim nothing, so the Inbox page does not count the board rows alone."""
    host(tmp_path, monkeypatch)
    from sessionorc.client import AgentUnavailable
    from shiftlead.ui import app as uiapp

    root = tmp_path / "proj"
    rows = uiapp.board_rows(report(root, item(3, "decide the thing", "2026-09-20", "2d overdue")))
    monkeypatch.setattr(uiapp, "board_reading", lambda *a, **k: (rows, ""))

    class Down:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            raise AgentUnavailable("down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(uiapp, "LocalClient", Down)
    with TestClient(uiapp.create_app()) as c:
        page = c.get("/inbox").text
        assert "decide the thing" not in page and needs_line(page) == "0"
        assert c.get("/api/person/inbox").json()["needs"] is None


def _row(line, due, team="t", *, due_now=False, **kw):
    return {
        "row": "board",
        "id": f"board:r:{line}",
        "line": line,
        "repo": "r",
        "repo_name": "r",
        "root": "/r",
        "team": "",
        "teams": [team] if team else [],
        "due": due,
        "due_now": due_now,
        "today": "2026-09-28",
        **kw,
    }


@pytest.mark.unit
def test_what_is_due_is_the_readers_due_only_set():
    """§4.5 screen 6 *The board's horizon* (TD-220): due now is what `--due-only` surfaced — due today
    or earlier, decided whatever its date, a date that could not be read — and never an undecided fyi."""
    from shiftlead.ui.app import board_due_now

    assert board_due_now({"overdue_days": 0}) and board_due_now({"overdue_days": 3})
    assert board_due_now({"overdue_days": None, "decided": {"text": "go", "date": "2026-09-27"}})
    assert board_due_now({"overdue_days": None, "due_error": "Due: soonish"})
    assert not board_due_now({"overdue_days": None, "due": "2026-10-04"})
    assert not board_due_now({"overdue_days": None})  # undated
    assert not board_due_now({"overdue_days": 2, "kind": "fyi"})
    assert board_due_now({"overdue_days": None, "kind": "fyi", "decided": {"text": "x", "date": "2026-09-27"}})


@pytest.mark.unit
def test_the_horizon_sorts_the_rows_by_the_mode():
    """§4.5 screen 6 *The board's horizon*, §5 `person.inbox.board_show` (TD-220 slice 2)."""
    from shiftlead.ui.app import board_horizon

    def ids(rows):
        return [r["line"] for r in rows]

    # next:10 — a team with twelve due shows twelve and none ahead; one with two due shows eight ahead
    busy = [_row(i, "2026-09-20", "busy", due_now=True) for i in range(12)] + [_row(99, "2026-09-29", "busy")]
    got = board_horizon(busy, None)
    assert got["mode"] == "next:10" and len(got["due"]) == 12 and got["ahead"] == [] and ids(got["hidden"]) == [99]
    quiet = [_row(i, "2026-09-20", due_now=True) for i in range(2)] + [
        _row(100 + i, f"2026-10-{i + 1:02d}") for i in range(12)
    ]
    got = board_horizon(quiet, "next:10")
    assert ids(got["ahead"]) == [100 + i for i in range(8)] and ids(got["hidden"]) == [108, 109, 110, 111]
    assert got["next_due"] == "2026-10-09"
    # n per repo (TD-741): a team's two repos are two boards, each its own n
    two = [_row(1, "2026-10-01", root="/a"), _row(2, "2026-10-02", root="/b"), _row(3, "2026-10-03", root="/a")]
    assert ids(board_horizon(two, "next:2")["ahead"]) == [1, 2, 3]
    assert ids(board_horizon(two, "next:1")["ahead"]) == [1, 2]
    lone = [_row(1, "2026-10-01", ""), _row(2, "2026-10-02", "", root="/other")]
    assert ids(board_horizon(lone, "next:1")["ahead"]) == [1, 2]
    # a due_error row is a due row and takes no place of the n
    bad = [_row(1, "", due_now=True, due_error=True), _row(2, "2026-10-01")]
    got = board_horizon(bad, "next:1")
    assert ids(got["due"]) == [1] and ids(got["ahead"]) == [2]
    # 7d: six days out is coming up, forty is hidden and counted by the line; undated is hidden
    week = [_row(1, "2026-10-04"), _row(2, "2026-11-07"), _row(3, None), _row(4, "2026-09-27", due_now=True)]
    got = board_horizon(week, "7d")
    assert ids(got["due"]) == [4] and ids(got["ahead"]) == [1] and ids(got["hidden"]) == [2, 3]
    assert got["next_due"] == "2026-11-07"
    # due: nothing ahead; all: everything, the undated last
    got = board_horizon(week, "due")
    assert ids(got["due"]) == [4] and got["ahead"] == [] and ids(got["hidden"]) == [1, 2, 3]
    got = board_horizon(week, "all")
    assert ids(got["ahead"]) == [1, 2, 3] and got["hidden"] == [] and got["next_due"] == ""
    # an undated item takes a place under next: once the dated ones have theirs
    assert ids(board_horizon(week, "next:3")["ahead"]) == [1, 2]
    assert ids(board_horizon(week, "next:4")["ahead"]) == [1, 2, 3]
    # the due rows never move with the mode, and a mode that does not parse is next:10
    for mode in ("next:1", "due", "7d", "all", "soon", None):
        assert ids(board_horizon(week, mode)["due"]) == [4]
    assert board_horizon(week, "soon")["mode"] == "next:10"
    # a past-dated fyi is not due now: it reads the reader's words, and is never the line's next date
    from shiftlead.ui.app import board_rows

    fyi = {
        "line": 5,
        "text": "for your read",
        "due": "2026-09-25",
        "overdue_days": 3,
        "due_tag": "3d overdue",
        "kind": "fyi",
        "decided": None,
    }
    (row,) = board_rows({"today": "2026-09-28", "boards": [{"root": "/r", "board": "/r/b.md", "items": [fyi]}]})
    assert not row["due_now"] and row["ahead"] == "3d overdue"
    got = board_horizon([row, _row(6, "2026-10-12")], "due")
    assert ids(got["hidden"]) == [5, 6] and got["next_due"] == "2026-10-12"
    # a row from before TD-220 carries no due_now: it was the --due-only read's, so it is due
    assert ids(board_horizon([{"line": 7, "due": "2026-10-10"}], "due")["due"]) == [7]


@pytest.mark.unit
def test_the_mode_is_the_persons_setting_as_last_read():
    """§5 `person.inbox.board_show` through the agent's `settings` read (TD-220): unset or bad is next:10."""
    from shiftlead.ui import uiconf

    try:
        uiconf.set_read({"person": {}})
        assert uiconf.board_show() == "next:10"
        uiconf.set_read({"person": {"inbox": {"board_show": "7d"}}})
        assert uiconf.board_show() == "7d"
        uiconf.set_read({"person": {"inbox": {"board_show": "next:0"}}})
        assert uiconf.board_show() == "next:10"
        uiconf.set_read({"person": {"inbox": "all"}})
        assert uiconf.board_show() == "next:10"
    finally:
        uiconf.set_read({"person": {}, "migrate": []})


@pytest.mark.unit
def test_the_line_says_the_mode_and_what_it_hides():
    """§4.5 screen 6 *The board's horizon*: the line that closes the board rows, in each mode's words."""
    from shiftlead.ui.app import board_line

    def line(mode, hidden=0, next_due=""):
        return board_line({"mode": mode, "hidden": [{}] * hidden, "next_due": next_due})

    assert line("next:10", 14, "2026-10-12") == {
        "says": "showing the next 10 board items per repo",
        "rest": "14 not shown, the next due Oct 12",
        "n": 14,
    }
    assert line("next:10")["rest"] == "nothing hidden" and line("next:10")["n"] == 0
    assert line("next:1")["says"] == "showing the next 1 board item per repo"
    assert line("due", 5, "2026-10-04")["says"] == "showing board items that are due"
    assert line("7d", 3)["says"] == "showing board items due this week" and line("7d", 3)["rest"] == "3 not shown"
    assert line("14d")["says"] == "showing board items due within 14 days"
    assert line("all")["says"] == "showing every board item"


@pytest.mark.unit
def test_the_repo_page_cuts_the_inboxs_horizon_to_its_repo():
    """§4.5 screen 11 *Waiting on you*: the Inbox's rows, lists and line filtered to the repo."""
    from shiftlead.ui.app import board_horizon, horizon_of

    rows = [
        _row(1, "2026-09-20", due_now=True, root="/a"),
        _row(2, "2026-10-01", root="/a"),
        _row(3, "2026-10-02", root="/b"),
        _row(4, "2026-10-20", root="/a"),
        _row(5, "2026-10-05", root="/b"),
    ]
    h = board_horizon(rows, "next:2")  # per repo: /a's due row and 2; /b's 3 and 5
    got = horizon_of(h, "/a")
    assert [r["line"] for r in got["due"]] == [1] and [r["line"] for r in got["ahead"]] == [2]
    assert [r["line"] for r in got["hidden"]] == [4] and got["next_due"] == "2026-10-20"
    assert h["next_due"] == "2026-10-20" and got["mode"] == "next:2"
    # the line is the repo's own: its hidden count and next date, not the Inbox's
    got = horizon_of({**h, "line": {"says": "x", "rest": "y", "n": 2}}, "/a")
    assert got["line"]["rest"] == "1 not shown, the next due Oct 20" and got["line"]["n"] == 1
    assert horizon_of(h, "/a").get("line") is None


@pytest.mark.unit
def test_coming_up_the_fold_and_the_line_are_drawn_and_counted_nowhere(tmp_path, monkeypatch):
    """§4.5 screen 6 *The board's horizon* (TD-220 slice 3): under the due board rows, *Board, coming
    up (n)* with its due words, the *not shown* fold closed, and the line with **show** and Settings;
    the counts are the due rows' alone under every mode, and the poll brings the same markup."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui import app as uiapp
    from shiftlead.ui import uiconf

    root = tmp_path / "proj"

    def ahead(line, text, due):
        return {"line": line, "text": text, "due": due, "overdue_days": None, "due_tag": f"due {due}"}

    items = [item(3, "decide the thing", "2026-09-20", "2d overdue")]
    items += [ahead(10 + i, f"later item {i}", f"2026-10-{i + 1:02d}") for i in range(12)]
    rows = uiapp.board_rows({**report(root, *items), "today": "2026-09-28"})
    monkeypatch.setattr(uiapp, "board_reading", lambda *a, **k: (rows, ""))

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            return {"list": [], "inbox": {"entries": [], "trail": []}, "host": {"name": "kmaster"}}.get(method, {})

    monkeypatch.setattr(uiapp, "LocalClient", Fake)
    try:
        with TestClient(uiapp.create_app()) as c:
            page = c.get("/inbox").text
            assert needs_line(page) == "1"
            assert 'Not due yet</span><span class="meta">(9)</span>' in page  # ten places, one due
            # the heading says why these are here: a setting, named and linked (TD-281)
            assert 'shown by your <a href="/settings#sec-you"' in page and ">board items shown</a> setting" in page
            assert "due in 3 d · Oct 1" in page and 'data-section="coming"' in page
            assert "<summary>not shown (3)</summary>" in page and "later item 11" in page
            assert "showing the next 10 board items per repo · 3 not shown, the next due Oct 10" in page
            assert 'class="boardshow"' in page and 'href="/settings#sec-you"' in page
            # the rail's *board items* counts every board row on the page; its *Needs you* the due one
            assert 'data-value="board"' in page
            got = c.get("/api/person/inbox").json()
            assert got["needs"] == 1 and got["sections"]["needs"] == [rows[0]["id"]]
            assert "Not due yet" in got["html"]["horizon"] and "later item 0" not in got["html"]["needs"]
            uiconf.set_read({"person": {"inbox": {"board_show": "due"}}})
            page = c.get("/inbox").text
            assert "Not due yet" not in page and needs_line(page) == "1"
            assert "showing board items that are due · 12 not shown, the next due Oct 1" in page
            uiconf.set_read({"person": {"inbox": {"board_show": "all"}}})
            page = c.get("/inbox").text
            assert "showing every board item · nothing hidden" in page and "not shown (" not in page
            assert "boardshow" not in page and needs_line(page) == "1"
    finally:
        uiconf.set_read({"person": {}, "migrate": []})


@pytest.mark.unit
def test_the_rail_counts_coming_up_as_board_items_and_under_later():
    """§4.5 screen 6: the rail's *board items* counts the rows coming up; *Needs you* does not, and a
    *Later* pick keeps them, as they sit in its section (TD-565)."""
    from shiftlead.ui.app import rail_counts, rail_picks, rail_rows

    due = {"row": "board", "id": "b1", "teams": ["t"], "find": "now"}
    later = {"row": "board", "id": "b2", "teams": ["t"], "find": "later"}
    rows = rail_rows({"needs": [due]}, [later])
    got = rail_counts(rows, rail_picks({}))
    assert got["kinds"]["board"]["all"] == 2 and got["sections"]["needs"]["all"] == 1
    assert got["heads"]["needs"]["all"] == 1 and got["teams"]["t"]["all"] == 1
    assert got["sections"]["later"]["all"] == 1 and got["heads"]["later"]["all"] == 1
    picked = rail_counts(rows, rail_picks({"sec": "needs", "kind": "board"}))
    assert picked["kinds"]["board"]["shown"] == 1 and picked["heads"]["needs"]["shown"] == 1
    picked = rail_counts(rows, rail_picks({"sec": "needs,later", "kind": "board"}))
    assert picked["kinds"]["board"]["shown"] == 2 and picked["heads"]["later"]["shown"] == 1


@pytest.mark.unit
def test_a_row_coming_up_snoozes_from_its_own_date_and_show_draws_forty_days_out(tmp_path, monkeypatch):
    """§4.5 screen 6 *The board's horizon*, §4.5a *Due strip / Inbox board row* **Snooze ▾** (TD-220
    slice 6): a row coming up carries Snooze with its own date, and +1 day / +1 week count from the
    later of today and that date, so a Snooze moves it later, never nearer; under `7d` an item due in
    forty days is in the closed fold, which **show** opens without a request — no setting is written."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui import app as uiapp
    from shiftlead.ui import uiconf

    root = tmp_path / "proj"

    def ahead(line, text, due):
        return {"line": line, "text": text, "due": due, "overdue_days": None, "due_tag": f"due {due}"}

    items = [ahead(10, "next week's item", "2026-10-04"), ahead(11, "forty days out", "2026-11-07")]
    rows = uiapp.board_rows({**report(root, *items), "today": "2026-09-28"})
    monkeypatch.setattr(uiapp, "board_reading", lambda *a, **k: (rows, ""))
    calls = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            calls.append(method)
            return {"list": [], "inbox": {"entries": [], "trail": []}, "host": {"name": "kmaster"}}.get(method, {})

    monkeypatch.setattr(uiapp, "LocalClient", Fake)
    try:
        with TestClient(uiapp.create_app()) as c:
            c.get("/inbox")  # the first request reads the settings; the mode is set after it
            uiconf.set_read({"person": {"inbox": {"board_show": "7d"}}})
            page = c.get("/inbox").text
            coming = page[page.index('id="rows-coming"') : page.index("<summary>not shown (")]
        for when in ("1d", "1w", "pick"):
            assert f'data-board-act="snooze" data-when="{when}" data-due="2026-10-04"' in coming
        fold = page[page.index('<details class="fold boardfold"') :]
        fold = fold[: fold.index("</details>")]
        assert "forty days out" in fold and "next week's item" not in fold
        assert "3 d" not in fold and 'data-due="2026-11-07"' in fold
        assert "1 not shown, the next due Nov 7 — " in page and 'class="boardshow"' in page
        assert "set_settings" not in calls
    finally:
        uiconf.set_read({"person": {}, "migrate": []})
    js = (pathlib.Path(uiapp.__file__).parent / "static" / "app.js").read_text()
    assert "boardDue(b.dataset.when, b.dataset.due)" in js
    body = js[js.index("function boardDue(when, from)") :]
    body = body[: body.index("\n  }\n")]
    assert "if (own > d) d.setTime(own.getTime())" in body  # the later of today and its own date
    show = js[js.index('closest("a.boardshow")') :]
    show = show[: show.index("});")]
    assert "fetch" not in show and "settings" not in show  # show writes nothing


# -- the board read against origin (§4.5 screen 6 *Boards are read against origin*, TD-221) ------


def _git(*args, cwd):
    import subprocess

    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.mark.unit
def test_a_board_line_only_on_origin_is_read_from_origin_on_a_clone_behind(tmp_path, monkeypatch):
    """A clone one commit behind its origin: the host agent's fetching read (§4.4 *The boards*,
    TD-615) shows the line merged on origin, the row says it was read from origin (`source`) and
    keeps the reader's `fetch_note`; the plain read does not see it. Real git, the real reader."""
    due = date.today().isoformat()
    origin, seed, clone = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "proj"
    _git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    _git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        _git("config", k, v, cwd=seed)
    (seed / "docs").mkdir()
    (seed / "docs" / "user_attention.md").write_text(f"# Board\n\n- [ ] the old line. Due: {due}.\n")
    (seed / "scripts").mkdir()
    shutil.copy(READER, seed / "scripts" / "nudge_user_attention.py")
    shutil.copy(LEDGERBOARD, seed / "scripts" / "ledgerboard.py")
    _git("add", "-A", cwd=seed)
    _git("commit", "-q", "-m", "board", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    _git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    with (seed / "docs" / "user_attention.md").open("a") as f:
        f.write(f"- [ ] the line only on origin. Due: {due}.\n")
    _git("commit", "-q", "-am", "a line", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    host(tmp_path, monkeypatch, [clone])
    from sessionorc import workorders
    from shiftlead.ui import app as uiapp

    def read(fetch):
        return uiapp.board_reading(
            {str(clone): {"root": str(clone), "boards": workorders.read_boards(clone, fetch=fetch)}}
        )

    rows, note = read(False)
    assert note == "" and [r["text"].split(".")[0] for r in rows] == ["the old line"]
    assert rows[0]["source"] == "" and rows[0]["fetch_note"] == ""
    rows, note = read(True)
    assert note == "" and [r["text"].split(".")[0] for r in rows] == ["the old line", "the line only on origin"]
    assert all(r["source"] for r in rows) and rows[0]["fetch_note"].startswith("fetched; local clone is behind")


def test_the_origin_note_knows_every_case_the_reading_gives():
    """§4.5 screen 6 (TD-585): the note is chosen by the reading's own `fetch_case`, never by its
    sentence, so a case the host agent's read gains that the Inbox does not map fails here."""
    from sessionorc import workorders
    from shiftlead.ui.inbox import origin_case

    want = {"skipped": "unreached", "none": None, "matches": None, "behind": "behind", "local": "local", "both": "both"}
    assert set(workorders.FETCH_CASES) == set(want)
    for case, drawn in want.items():
        assert origin_case("", case) == drawn, case
    assert origin_case("origin/main", "") == "behind" and origin_case("", "") is None


@pytest.mark.unit
def test_the_origin_note_says_each_case_in_the_designs_words():
    """§4.5a **origin note**: behind, local edits, two-sided (the warning colour), origin not
    reached with its reason; none when the board matches, origin has none, or the read was plain."""
    from shiftlead.ui.inbox import origin_note

    def note(case, source="", why=""):
        return origin_note({"source": source, "fetch_case": case, "fetch_why": why})

    behind = note("behind", "origin/main")
    assert behind == {"text": "read from origin/main: this checkout has not pulled it yet", "warn": False}
    assert note("local") == {"text": "board edits made here are not on origin", "warn": False}
    both = note("both")
    assert both["warn"] and both["text"].startswith("this checkout's board and origin's have both changed")
    assert both["text"].endswith("what origin added is not shown — pull")
    assert note("skipped", why="timeout") == {
        "text": "origin could not be reached (timeout): showing the checkout's board as of its last pull",
        "warn": False,
    }
    assert "(fatal: could not read (x))" in note("skipped", why="fatal: could not read (x)")["text"]
    assert "(no reason given)" in note("skipped")["text"]
    for none in ("matches", "none", ""):
        assert note(none) is None


@pytest.mark.unit
def test_the_behind_note_ends_with_the_pulls_standing(monkeypatch):
    """§4.5 screen 6, §6 *Pull* (TD-263): the *behind* note's tail is the home's last pull reading
    for the repo, from the fixed table; no tail before a pass has reached it, or once it is current."""
    from shiftlead.ui import inbox

    head = "read from origin/main: this checkout has not pulled it yet"
    row = {"source": "origin/main", "fetch_note": "", "root": "/x/shiftlead"}
    for reading, tail in (
        ({"outcome": "waiting", "occupant": "main"}, " — the host agent pulls it once main is idle"),
        ({"outcome": "waiting", "occupant": None, "why": "unreadable"}, " — the host agent pulls it once it is idle"),
        ({"outcome": "refused", "why": "on topic"}, " — it could not be pulled: on topic"),
        ({"outcome": "off"}, " — pulling is off for this repo"),
        ({"outcome": "current"}, ""),
        ({"outcome": "pulled", "commits": 2}, ""),
        (None, ""),
    ):
        monkeypatch.setattr(inbox, "PULLS", {"shiftlead": reading} if reading else {})
        assert inbox.origin_note(row) == {"text": head + tail, "warn": False}
    monkeypatch.setattr(inbox, "PULLS", {"shiftlead": {"outcome": "off"}})
    assert inbox.origin_note({**row, "root": "/x/other"})["text"] == head  # another repo's reading


@pytest.mark.unit
def test_a_board_read_from_origin_has_its_note_once_and_its_rows_are_live(tmp_path, monkeypatch):
    """One note above the repo's first board row in the list, none for a board that matches; on a
    board whose `source` is origin, Snooze, Done and Reply are as live as any (TD-264: the write-back
    works on origin's line) and Open board stays; a two-sided board's note is in the warning colour."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui.app import board_rows, templates

    a, b, c = tmp_path / "behind", tmp_path / "same", tmp_path / "both"
    rep = report(a, item(3, "one. Due: 2026-09-20.", "2026-09-20", "2d overdue"), item(4, "two.", "2026-09-20", "x"))
    rep["boards"][0].update(source="origin/main", fetch_case="behind")
    for root, case in ((b, "matches"), (c, "both")):
        more = report(root, item(7, f"{root.name} line.", "2026-09-20", "2d overdue"))["boards"][0]
        more["fetch_case"] = case
        rep["boards"].append(more)
    rows = board_rows(rep)
    assert [r["source"] for r in rows] == ["origin/main", "origin/main", "", ""]
    html = templates.get_template("inbox_rows.html").render(rows=rows, section="needs")
    assert html.count("read from origin/main: this checkout has not pulled it yet") == 1
    assert html.index("this checkout has not pulled it yet") < html.index("<p>one.</p>")
    assert html.count('class="originnote meta warnish"') == 1 and html.count("originnote") == 2
    behind_html = html[: html.index("same line.")]
    assert "disabled" not in behind_html and "pull to act on it" not in html
    assert behind_html.count('data-board-act="done"') == 2 and behind_html.count('data-act="board_reply"') == 2
    assert behind_html.count("Open board") == 2
    rest = html[html.index("same line.") :]
    assert rest.count('data-board-act="done"') == 2
    # the Repo page and the horizon draw it by the same rule
    part = templates.get_template("board_horizon.html").render(
        hz={"ahead": rows, "hidden": [], "line": {"says": "x", "rest": "y", "n": 0}}, origin=""
    )
    assert part.count("this checkout has not pulled it yet") == 1


@pytest.mark.unit
def test_a_press_on_a_board_read_from_origin_goes_to_the_write_back(tmp_path, monkeypatch):
    """TD-264 (§4.4, §4.5 screen 6): a row read from origin is pressable — the write-back works on
    origin's line, so the press goes to `board_edit` or `board_reply` as any row's does; the re-read
    after it is the host agent's (§4.4 *The boards*, TD-615)."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui import app as uiapp

    board = str(tmp_path / "r/docs/user_attention.md")
    row = {"row": "board", "id": f"board:{board}:3", "board": board, "text": "x", "due_now": True, "at": "2026-09-01"}
    monkeypatch.setattr(uiapp, "board_reading", lambda *a, **k: ([dict(row, line=3, source="origin/main")], ""))
    calls = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method in ("board_edit", "board_reply"):
                calls.append((method, kw.get("action")))
                return {"commit": "abc"}
            return {"list": [], "inbox": {"entries": [], "trail": []}}.get(method, {})

    monkeypatch.setattr(uiapp, "LocalClient", Fake)
    with TestClient(uiapp.create_app()) as c:
        c.get("/api/person/inbox")
        for body in (
            {"action": "done", "board": board, "line": 3, "text": "x"},
            {"action": "snooze", "board": board, "line": 3, "text": "x", "due": "2026-10-01"},
            {"action": "reply", "board": board, "line": 3, "text": "x", "reply": "y"},
        ):
            r = c.post("/api/person/board", json=body)
            assert r.status_code == 200, r.text
        assert calls == [("board_edit", "done"), ("board_edit", "snooze"), ("board_reply", None)]


def _behind_clone(tmp_path):
    """An origin, a seed that pushes to it and a clone one board commit behind."""
    due = date.today().isoformat()
    origin, seed, clone = tmp_path / "origin.git", tmp_path / "seed", tmp_path / "proj"
    _git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    _git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    (seed / "docs").mkdir()
    (seed / "docs" / "user_attention.md").write_text(f"# Board\n\n- [ ] the old line. Due: {due}.\n")
    (seed / "scripts").mkdir()
    shutil.copy(READER, seed / "scripts" / "nudge_user_attention.py")
    shutil.copy(LEDGERBOARD, seed / "scripts" / "ledgerboard.py")
    for d in (seed,):
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            _git("config", k, v, cwd=d)
    _git("add", "-A", cwd=seed)
    _git("commit", "-q", "-m", "board", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    _git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        _git("config", k, v, cwd=clone)
    with (seed / "docs" / "user_attention.md").open("a") as f:
        f.write(f"- [ ] the line only on origin. Due: {due}.\n")
    _git("commit", "-q", "-am", "a line", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    return clone, due


@pytest.mark.unit
def test_after_a_pull_the_row_is_pressable_and_a_two_sided_board_warns(tmp_path, monkeypatch):
    """Real git, the real reader, the host agent's fetching read (TD-221 slice 4, TD-615): behind,
    the row only on origin is drawn under the *behind* note, pressable (TD-264); after a pull no
    note is drawn; a local board edit against a new line on origin shows the checkout's rows under
    the warning note."""
    clone, due = _behind_clone(tmp_path)
    host(tmp_path, monkeypatch, [clone])
    from sessionorc import workorders
    from shiftlead.ui import app as uiapp
    from shiftlead.ui.app import templates

    def page():
        got = workorders.read_boards(clone, fetch=True)
        rows, note = uiapp.board_reading({str(clone): {"root": str(clone), "boards": got}})
        assert note == ""
        return rows, templates.get_template("inbox_rows.html").render(rows=rows, section="needs")

    rows, html = page()
    assert [r["text"].split(".")[0] for r in rows] == ["the old line", "the line only on origin"]
    assert "this checkout has not pulled it yet" in html and html.count('data-board-act="done"') == 2
    _git("pull", "-q", "--ff-only", cwd=clone)
    rows, html = page()
    assert [r["source"] for r in rows] == ["", ""] and rows[0]["fetch_note"].startswith("fetched; board matches")
    assert "originnote" not in html and html.count('data-board-act="done"') == 2
    # two-sided: an edit here, committed, and another line merged on origin
    board = clone / "docs" / "user_attention.md"
    board.write_text(board.read_text() + f"- [ ] a line made here. Due: {due}.\n")
    _git("commit", "-q", "-am", "here", cwd=clone)
    seed = tmp_path / "seed"
    with (seed / "docs" / "user_attention.md").open("a") as f:
        f.write(f"- [ ] a second line on origin. Due: {due}.\n")
    _git("commit", "-q", "-am", "there", cwd=seed)
    _git("push", "-q", "origin", "main", cwd=seed)
    rows, html = page()
    assert "a line made here" in html and "a second line on origin" not in html
    assert 'class="originnote meta warnish"' in html and "what origin added is not shown — pull" in html
    assert html.count('data-board-act="done"') == 3  # the checkout's rows are its own: pressable


# ── §4.5a **answers** / **Go with it** on a board row (§4.4 *Decide*; TD-255 slice 2) ──────────────


def decide_item(line=9, *, decided=None, default="hold"):
    text = "**Ship it?** Pick one. Due: 2026-09-20. Answers: approve | hold (default) | ask <b>Ann</b>."
    if not default:
        text = text.replace(" (default)", "")
    if decided:
        text += f" Decided: {decided} (2026-09-21)."
    return {
        **item(line, text, "2026-09-20", "2d overdue"),
        "answers": ["approve", "hold", "ask <b>Ann</b>"],
        "default": default or None,
        "decided": {"text": decided, "date": "2026-09-21"} if decided else None,
        "kind": "decide",
    }


def rows_html(tmp_path, monkeypatch, it, **board):
    host(tmp_path, monkeypatch)
    from shiftlead.ui.app import board_rows, templates

    rep = report(tmp_path / "samscrape", it)
    rep["boards"][0].update(board)
    rows = board_rows(rep)
    return rows, templates.get_template("inbox_rows.html").render(rows=rows, section="needs")


@pytest.mark.unit
def test_a_board_items_answers_are_buttons_in_the_order_written_and_go_with_it_is_in_the_foot(tmp_path, monkeypatch):
    """Three answers and a default: three answer buttons in the order written, the default's marked,
    each the `decide` act carrying its text and the reader's list; a bare **Go with it** in the
    foot after Reply, its confirm naming the default; the body prints no `Answers:` tail. The
    answers are the reader's field and escaped — a label, never markup."""
    import html as htmllib
    import json
    import re

    rows, html = rows_html(tmp_path, monkeypatch, decide_item())
    assert rows[0]["body"] == "**Ship it?** Pick one. Due: 2026-09-20."
    assert rows[0]["answers"] == ["approve", "hold", "ask <b>Ann</b>"] and rows[0]["default"] == "hold"
    assert '<div class="body md"><p><strong>Ship it?</strong> Pick one.</p></div>' in html
    btns = re.findall(r'<button class="btn sm answer" ([^>]*)>(.*?)</button>', html, re.S)
    assert [htmllib.unescape(re.search(r'data-answer="([^"]*)"', a).group(1)) for a, _ in btns] == rows[0]["answers"]
    assert ["default" in inner for _, inner in btns] == [False, True, False]
    assert "<b>Ann</b>" not in html and "&lt;b&gt;Ann&lt;/b&gt;" in html
    for attrs, _ in btns:
        assert 'data-act="board"' in attrs and 'data-board-act="decide"' in attrs and 'data-line="9"' in attrs
        assert json.loads(re.search(r"data-answers='([^']*)'", attrs).group(1)) == rows[0]["answers"]
        assert "disabled" not in attrs and "data-confirm" not in attrs
    foot = html[html.index('class="row gap wrap mfoot"') :]
    assert foot.index(">Reply<") < foot.index(">Go with it<") < foot.index(">Snooze<") < foot.index(">Done<")
    gwi = foot[: foot.index(">Go with it<")].rsplit("<button", 1)[1]
    assert 'data-board-act="decide"' in gwi and 'data-answer="hold"' in gwi
    assert "Go with it? &ldquo;hold&rdquo; is written on samscrape" in gwi
    assert html.count('data-board-act="decide"') == 4


def look_item(default="", kind="watch", answers=("Works", "Not right: <what>")):
    tail = " | ".join(a + (" (default)" if a == default else "") for a in answers)
    text = f"**One look at the ring** after the promote (TD-9, #12). Due: 2026-09-20. Answers: {tail}."
    return {
        **item(7, text, "2026-09-20", "2d overdue"),
        "answers": list(answers),
        "default": default or None,
        "decided": None,
        "kind": kind,
    }


@pytest.mark.unit
def test_a_live_looks_pair_is_drawn_by_its_words_works_and_not_right(tmp_path, monkeypatch):
    """§4.5a **Works** / **Not right…** (TD-255 slice 3): a `watch` whose answers are the pair draws
    two `.btn.answer` — **Works**, the `decide` with *Works*, and **Not right…**, the composer's
    act carrying the reader's list, the repo's name and the item's head for the hand-off — and no
    quoted answer text. A default on *Works* is that button, *Go with it: Works*, with none in the
    foot. Read from origin both are live (TD-264)."""
    import json
    import re

    rows, html = rows_html(tmp_path, monkeypatch, look_item())
    assert rows[0]["pair"] and rows[0]["head"] == "One look at the ring" and rows[0]["name"] == "samscrape"
    btns = re.findall(r'<button class="btn sm answer" ([^>]*)><span class="alabel">(.*?)</span></button>', html, re.S)
    assert [label for _, label in btns] == ["Works", "Not right…"]
    works, form = btns[0][0], btns[1][0]
    assert 'data-act="board"' in works and 'data-board-act="decide"' in works and 'data-answer="Works"' in works
    assert 'data-act="board_notright"' in form and "data-answer=" not in form and "data-board-act" not in form
    assert 'data-repo="samscrape"' in form and 'data-head="One look at the ring"' in form and 'data-line="7"' in form
    assert json.loads(re.search(r"data-answers='([^']*)'", form).group(1)) == ["Works", "Not right: <what>"]
    drawn = html.split('class="row gap wrap mfoot"')[0].split("its answers")[1]
    assert "&ldquo;" not in drawn and "Go with it" not in html
    assert rows[0]["body"].endswith("Due: 2026-09-20.")

    # the head and the text are a session's words: attributes, escaped, never markup
    bad = look_item()
    bad["text"] = bad["text"].replace("One look at the ring", 'One "look" <b>at</b>')
    rows, html = rows_html(tmp_path, monkeypatch, bad)
    assert rows[0]["head"] == 'One "look" <b>at</b>' and "<b>at</b>" not in html
    assert 'data-head="One &#34;look&#34; &lt;b&gt;at&lt;/b&gt;"' in html

    _, html = rows_html(tmp_path, monkeypatch, look_item(default="Works"))
    assert ">Go with it: Works</span>" in html and ">Go with it<" not in html and ">default<" not in html

    _, html = rows_html(tmp_path, monkeypatch, look_item(), source="origin/main")
    btns = re.findall(r'<button class="btn sm answer" ([^>]*)>', html)
    assert len(btns) == 2 and all("disabled" not in a and "data-act" in a for a in btns)


@pytest.mark.unit
def test_only_a_look_or_watch_with_exactly_the_pair_is_a_live_look(tmp_path, monkeypatch):
    """Else they are ordinary answer buttons: another kind, a third answer, a complete *Not right:
    wrong repo*, or the words in another order."""
    from shiftlead.ui.inbox import board_head, live_look

    for it in (
        look_item(kind="decide"),
        look_item(answers=("Works", "Not right: <what>", "Later")),
        look_item(answers=("Works", "Not right: wrong repo")),
        look_item(answers=("Not right: <what>", "Works")),
        look_item(answers=("works", "Not right: <what>")),
    ):
        assert not live_look(it)
        rows, html = rows_html(tmp_path, monkeypatch, it)
        assert not rows[0]["pair"] and "board_notright" not in html and "&ldquo;" in html
    assert live_look(look_item()) and live_look(look_item(answers=("Works", "Not right:")))
    assert live_look(look_item(kind="look"))  # the kind cadence names for it (TD-292), as a `watch` before it
    rows, html = rows_html(tmp_path, monkeypatch, look_item(kind="look"))
    assert rows[0]["pair"] and "board_notright" in html
    from shiftlead.ui.inbox import board_due_now

    assert board_due_now(look_item(kind="look"))  # with no default, a counted due row under Needs you
    assert board_head("no bold here, just a long line " * 4).endswith("…") and len(board_head("x " * 90)) == 60


@pytest.mark.unit
def test_not_right_opens_the_composer_begun_decides_then_hands_an_entry_on():
    """The page's half, read from its source: the composer opens with *Not right:* begun, one
    `decide` carries the typed text, and only then the second call hands a `debt` entry to the
    techlead, its words the item's head and the answer; a refusal there is toasted and returns."""
    import pathlib

    js = (pathlib.Path(__file__).parent.parent / "src/shiftlead/ui/static/app.js").read_text()
    at = js.index('if (action === "board_notright") {')
    block = js[at : js.index('if (action === "board_add") {', at)]
    assert 'text: "Not right: "' in block and '$("#mailtext").value = o.text || "";' in js
    decide, hand = block.index('action: "decide"'), block.index('fetch("/api/entry/hand"')
    assert decide < hand and 'type: "debt"' in block and "words: `${b.dataset.head} — ${answer}`" in block
    assert "no entry was handed on" in block and 'board_notright: "Not right…"' in js
    assert "!refused);" in block and "/^not right\\s*:?\\s*/i" in block  # a refusal is not a green toast
    assert 'text: ["Go with it", "Go with it: Works"]' in js


@pytest.mark.unit
def test_a_row_with_no_default_has_no_go_with_it_and_one_with_no_answers_no_buttons(tmp_path, monkeypatch):
    _, html = rows_html(tmp_path, monkeypatch, decide_item(default=""))
    assert html.count('class="btn sm answer"') == 3 and "Go with it" not in html and ">default<" not in html
    plain = item(4, "Look at it. Answers: in the prose only. Due: 2026-09-20.", "2026-09-20", "2d overdue")
    rows, html = rows_html(tmp_path, monkeypatch, plain)
    # the reader gave no `answers`: the prose is prose, the body whole, and nothing is a button
    assert rows[0]["body"] == plain["text"] and rows[0]["answers"] == []
    assert "btn sm answer" not in html and "Go with it" not in html and "decide" not in html


@pytest.mark.unit
def test_a_decided_row_reads_decided_in_place_of_the_buttons(tmp_path, monkeypatch):
    """Once decided the row reads *decided: <text> · <date>* from the reader's `decided`, the body
    prints neither tail, no answer and no Go with it is offered — and **Reply** and **Done** stand."""
    rows, html = rows_html(tmp_path, monkeypatch, decide_item(decided="approve"))
    assert rows[0]["decided"] == {"text": "approve", "date": "Sep 21"} and rows[0]["due_now"]
    assert rows[0]["body"] == "**Ship it?** Pick one. Due: 2026-09-20."
    # the *not done: … work order* words went with TD-305: the *waiting on …* line says it
    assert "decided: approve · Sep 21" in html and "work order" not in html
    assert "btn sm answer" not in html and "Go with it" not in html and 'data-board-act="decide"' not in html
    assert 'data-act="board_reply"' in html and 'data-board-act="done"' in html
    # the acts still hand back the whole line, which the agent re-checks word for word
    assert "Decided: approve (2026-09-21)." in html


@pytest.mark.unit
def test_a_row_read_from_origin_draws_its_answers_and_go_with_it_live(tmp_path, monkeypatch):
    """TD-264: the answers and Go with it on a row read from origin press the write-back."""
    _, html = rows_html(tmp_path, monkeypatch, decide_item(), source="origin/main")
    import re

    btns = re.findall(r'<button class="btn sm answer" ([^>]*)>', html)
    assert len(btns) == 3 and all("disabled" not in a and 'data-board-act="decide"' in a for a in btns)
    assert re.search(r'<button[^>]*data-board-act="decide"[^>]*>Go with it</button>', html)


@pytest.mark.unit
def test_a_press_hands_the_answer_and_the_readers_list_to_the_write_back(tmp_path, monkeypatch):
    """The route (§4.4 *Decide*): `board_edit {action: decide, answer, answers}`, caller-less, and
    the host agent's re-read is in its reading before it answers (TD-615); a decide naming no answer or no
    list is refused before the agent is asked, and the other acts carry neither field."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui import app as uiapp

    calls = []

    class Fake:
        def __init__(self, *a, **k):
            self.kw = k

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "board_edit":
                calls.append((self.kw.get("caller"), kw))
                return {"commit": "abc123", "answer": kw.get("answer")}
            return {"list": [], "inbox": {"entries": [], "trail": []}}.get(method, {})

    monkeypatch.setattr(uiapp, "LocalClient", Fake)
    board = str(tmp_path / "r/docs/user_attention.md")
    base = {"action": "decide", "board": board, "line": 4, "text": "x"}
    with TestClient(uiapp.create_app()) as c:
        r = c.post("/api/person/board", json={**base, "answer": " hold ", "answers": ["approve", "hold"]})
        assert r.status_code == 200 and r.json()["answer"] == "hold"
        assert calls == [(None, {**base, "due": None, "key": "", "answer": "hold", "answers": ["approve", "hold"]})]
        for bad in ({"answers": ["approve"]}, {"answer": "hold"}, {"answer": "hold", "answers": "hold"}):
            assert c.post("/api/person/board", json={**base, **bad}).status_code == 400
        assert len(calls) == 1


@pytest.mark.integration
def test_the_page_draws_what_the_reader_reads_and_a_press_is_written_and_read_back(tmp_path, monkeypatch):
    """End to end with dev-cadence's own reader and the real write-back: the reader's `answers` and
    `default` draw the buttons; the answer the page would send is written as `Decided:`; and the
    reader's next read gives `decided`, which the row prints in place of the buttons."""
    import json
    import subprocess
    import sys

    host(tmp_path, monkeypatch)
    from sessionorc import board as board_mod
    from shiftlead.ui.app import board_rows, templates

    today = date.today().isoformat()
    head = f"- [ ] decide {today} (session `w` on kmaster) — **Ship it?** Pick."
    line = f"{head} Due: {today}. Answers: approve | hold (default)."
    root = repo(tmp_path, "r", f"# Board\n\n## Needs the user\n\n{line}\n")

    def git(*a):
        subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)

    shutil.rmtree(root / ".git")
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    git("add", "-A")
    git("commit", "-qm", "board")
    with_origin(root)
    monkeypatch.setenv("PATH", f"{fake_gh_bin(tmp_path / 'fake-bin')}{os.pathsep}{os.environ.get('PATH', '')}")

    def read():
        out = subprocess.run(
            [sys.executable, str(root / "scripts" / "nudge_user_attention.py"), "--report", "--json"]
            + ["--board", str(root / "docs" / "user_attention.md")],
            capture_output=True,
            text=True,
            check=True,
        )
        return board_rows(json.loads(out.stdout))

    (row,) = read()
    assert row["answers"] == ["approve", "hold"] and row["default"] == "hold" and row["decided"] is None
    html = templates.get_template("inbox_rows.html").render(rows=[row], section="needs")
    assert html.count('class="btn sm answer"') == 2 and ">Go with it<" in html
    monkeypatch.setattr(board_mod, "default_branch", lambda r: "main")
    board_mod.write_back(root, row["line"], row["text"], "decide", None, answer=row["default"])
    git("pull", "-q", "--ff-only", "origin", "main")  # the edit is on origin; the checkout catches up
    (row,) = read()
    assert row["decided"]["text"] == "hold" and row["due_now"] and "Answers:" not in row["body"]
    html = templates.get_template("inbox_rows.html").render(rows=[row], section="needs")
    assert "decided: hold · " in html and "btn sm answer" not in html and "Go with it" not in html


@pytest.mark.unit
def test_a_board_row_draws_its_line_as_markdown_folded_after_its_head(tmp_path, monkeypatch):
    """design §4.5a **Inbox board row: text** (TD-279): the line in the closed markdown subset — no
    `**` or backtick printed — drawn up to its bold head and the sentence after it, the rest under
    *details* with each **Part:** head opening a paragraph and the `Context:` last; the `Due:` goes
    and the reader's replies stand under the text, outside the fold."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui.app import board_rows, templates

    root = tmp_path / "shiftlead"
    filler = " ".join(["the card reads its line and its hover lists every window."] * 6)
    text = (
        "watch 2026-09-30 (session `grinder-ao-2` on kmaster) — **One walk of the Org.** The live copy is "
        f"built from #837: look now. Each look's line is closed. **Top bar:** {filler} (TD-122). "
        f"**Cards:** {filler} Context: TD-244 / TD-122 PR #517. Due: 2026-10-01. "
        "— Paul, 2026-10-02: This is a `wall` of text. Answers: Works | Not right: <what>."
    )
    it = item(21, text, "2026-10-01", "1d overdue") | {
        "kind": "watch",
        "answers": ["Works", "Not right: <what>"],
        "replies": [{"by": "Paul", "date": "2026-10-02", "text": "This is a `wall` of text."}],
    }
    (row,) = board_rows(report(root, it), {})
    assert row["lead"].endswith("The live copy is built from #837: look now.")
    assert row["rest"].startswith("Each look's line is closed.\n\n**Top bar:**")
    assert "\n\n**Cards:**" in row["rest"] and row["rest"].endswith("\n\nContext: TD-244 / TD-122 PR #517")
    assert "Due:" not in row["lead"] + row["rest"] and "Paul" not in row["rest"]
    assert row["replies"] == [{"by": "Paul", "date": "Oct 2", "text": "This is a `wall` of text."}]
    html = templates.get_template("inbox_rows.html").render(rows=[row], section="needs")
    body = html[html.index('class="body md"') : html.index('class="row gap wrap sugg"')]
    assert "<strong>One walk of the Org.</strong>" in body and "<code>grinder-ao-2</code>" in body
    assert "**" not in body and "`" not in body
    assert '<details class="fold" data-fold="board:' in body and "<p><strong>Cards:</strong>" in body
    assert "Paul, Oct 2: This is a <code>wall</code> of text." in body
    assert body.index("</details>") < body.index("Paul, Oct 2")  # the reply stands outside the fold


@pytest.mark.unit
def test_a_short_board_line_draws_whole_and_a_reader_without_replies_keeps_them(tmp_path, monkeypatch):
    """A line no longer than `FOLD_CHARS` has no *details* (§4.5a **Inbox board row: text**); a
    `Context:` alone is still under one. A reader that gives no `replies` leaves the tail in the text."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui.app import board_rows

    root = tmp_path / "samscrape"
    (row,) = board_rows(report(root, item(3, "act — **Rotate the key.** Soon. Due: 2026-09-20.", "2026-09-20", "x")))
    assert (row["lead"], row["rest"], row["replies"]) == ("act — **Rotate the key.** Soon.", "", [])
    (row,) = board_rows(report(root, item(3, "act — Rotate it. Context: TD-9. Due: 2026-09-20.", "2026-09-20", "x")))
    assert (row["lead"], row["rest"]) == ("act — Rotate it.", "Context: TD-9")
    text = "act — Rotate it. Due: 2026-09-20. — Paul, 2026-09-21: today please"
    (row,) = board_rows(report(root, item(3, text, "2026-09-20", "x")))
    assert row["lead"] == "act — Rotate it. — Paul, 2026-09-21: today please" and row["replies"] == []


@pytest.mark.unit
def test_fold_head_cuts_after_the_bold_head_and_its_sentence():
    from shiftlead.ui import render

    long = "x " * 200
    assert render.fold_head("short **head.** one.") == ("short **head.** one.", "")
    lead, rest = render.fold_head(f"watch — **Head here.** First one. {long}")
    assert lead == "watch — **Head here.** First one." and rest == long.strip()
    late = "y" * 250 + " **late head.** after. " + long  # a head past the first 200 characters is no head
    assert render.fold_head(late) == render.fold(late)


@pytest.mark.unit
def test_a_board_rows_text_loses_nothing_on_the_odd_line(tmp_path, monkeypatch):
    """The review's cases (TD-279): a reply the reader's `replies` missed keeps every tail in the text
    and draws none twice; a `Context:` after the `Due:` still closes the fold. A mid-sentence
    *Context:* is the field, as ledgerboard reads it (`CONTEXT_RE`, its `refs` too): the Inbox cuts the
    line where ledgerboard finds the field, with no pattern of its own (TD-585)."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui.app import board_rows

    root = tmp_path / "shiftlead"
    text = "act — Rotate it. Due: 2026-10-05. — Paul, 2026-10-02: hi — Paul, 2026-10-03: yo"
    it = item(3, text, "2026-10-05", "x") | {"replies": [{"by": "Paul", "date": "2026-10-02", "text": "hi"}]}
    (row,) = board_rows(report(root, it))
    assert row["replies"] == [] and "hi" in row["lead"] and "yo" in row["lead"]
    (row,) = board_rows(report(root, item(3, "act — Rotate it. Due: 2026-10-05. Context: TD-9.", "2026-10-05", "x")))
    assert (row["lead"], row["rest"]) == ("act — Rotate it.", "Context: TD-9")
    text = "act — See the Context: of this. **Context:** bold. Due: 2026-10-05."
    (row,) = board_rows(report(root, item(3, text, "2026-10-05", "x")))
    assert (row["lead"], row["rest"]) == ("act — See the", "Context: of this. **Context:** bold")


@pytest.mark.unit
def test_put_on_the_board_takes_its_words_in_a_box_of_lines(tmp_path, monkeypatch):
    """TD-281 (2): *what's needed* is a textarea of four rows, not a one-line input."""
    host(tmp_path, monkeypatch)
    from shiftlead.ui.app import templates

    html = templates.get_template("board_add.html").render(board_choices=[{"board": "/b", "label": "b"}])
    assert '<textarea class="input" id="batext" rows="4"' in html and 'id="batext"' in html
    assert '<input class="input" id="batext"' not in html and "Ctrl+Enter" in html


# ── §4.5 screen 6 *A board item the person answered waits on them* (TD-303, built by TD-305) ─────


def answered_item(line, *, decided="", replied="", due="2026-09-20", tag="2d overdue", waiting_on=None, **kw):
    it = {**item(line, f"**Item {line}** words. Due: {due}.", due, tag), **kw}
    if decided:
        it["decided"] = {"text": "approve", "date": decided}
    if replied:
        it["replies"] = [
            {"by": "Paul", "date": "2026-09-01", "text": "first"},
            {"by": "Paul", "date": replied, "text": "go"},
        ]
    if waiting_on is not None:
        it["waiting_on"] = waiting_on
    elif decided:
        it["waiting_on"] = "session"
    if due > "2026-09-22":
        it["overdue_days"] = None
    return it


@pytest.mark.unit
def test_board_rows_stamp_whom_the_item_waits_on_and_when_it_comes_back(tmp_path):
    """`answered` is `decided` from the reader's `waiting_on`, else `replied` from its `replies`;
    the date is the decided date or the last reply's; `stale` from `BOARD_WAIT_DAYS` (3) civil days
    to the reader's `today` (2026-09-22): decided Sep 19 is back, Sep 20 is not."""
    from shiftlead.ui.inbox import BOARD_WAIT_DAYS, board_rows

    assert BOARD_WAIT_DAYS == 3
    root = tmp_path / "r"
    rows = board_rows(
        report(
            root,
            answered_item(1, decided="2026-09-20"),
            answered_item(2, decided="2026-09-19"),
            answered_item(3, replied="2026-09-21"),
            answered_item(4),
            answered_item(5, decided="not a date"),
            # a reader with no `waiting_on` falls back to its `decided`
            {k: v for k, v in answered_item(6, decided="2026-09-21").items() if k != "waiting_on"},
            # `waiting_on: person` with replies: the person's word is last — replied
            answered_item(7, replied="2026-09-10", waiting_on="person"),
        )
    )
    got = {r["line"]: (r["answered"], r["answered_at"], r["stale"]) for r in rows}
    assert got == {
        1: ("decided", "2026-09-20", False),
        2: ("decided", "2026-09-19", True),
        3: ("replied", "2026-09-21", False),
        4: ("", "", False),
        5: ("decided", "not a date", False),
        6: ("decided", "2026-09-21", False),
        7: ("replied", "2026-09-10", True),
    }
    lines = {r["line"]: r["stale_line"] for r in rows}
    assert lines[2] == "decided Sep 19 — no session has acted in 3 d"
    assert lines[7] == "replied Sep 10 — no session has acted in 12 d"
    assert lines[1] == lines[4] == lines[5] == ""


@pytest.mark.unit
def test_an_answered_row_waits_on_them_in_no_count_and_a_stale_one_comes_back(tmp_path):
    """Decided and replied rows are under *Waiting on them* — out of `count`, `overdue_n` and the
    horizon — the undecided due one under *Needs you*; a decided row three days back is counted
    again; a replied one that is not due and stale goes back to the horizon, not to *Needs you*."""
    from shiftlead.ui.inbox import board_horizon, board_rows, inbox_sections

    root = tmp_path / "r"
    rows = board_rows(
        report(
            root,
            answered_item(1, decided="2026-09-21"),
            answered_item(2, replied="2026-09-21"),
            answered_item(3),
            answered_item(4, decided="2026-09-19"),
            answered_item(5, replied="2026-09-21", due="2026-09-25", tag=""),
            answered_item(6, replied="2026-09-01", due="2026-09-25", tag=""),
        )
    )
    hz = board_horizon(rows, "all")
    assert [r["line"] for r in hz["waiting"]] == [1, 2, 5]
    assert [r["line"] for r in hz["due"]] == [3, 4] and [r["line"] for r in hz["ahead"]] == [6]
    s = inbox_sections([], now=datetime(2026, 9, 22, 12, tzinfo=UTC), boards=hz["due"] + hz["waiting"])
    assert [e["line"] for e in s["needs"]] == [3, 4]
    assert sorted(e["line"] for e in s["waiting"]) == [1, 2, 5]
    assert s["count"] == 2 and s["overdue_n"] == 2  # 3 and 4, both past Sep 20; 1 and 2 are not counted
    # a caller that hands every due row (the Org's top bar) gets the same placement
    s2 = inbox_sections([], now=datetime(2026, 9, 22, 12, tzinfo=UTC), boards=[r for r in rows if r["due_now"]])
    assert s2["count"] == 2 and sorted(e["line"] for e in s2["waiting"]) == [1, 2]
    # the cache's rows are never written to
    assert all("waiting_on" not in r for r in rows)
    # under `next:1` a waiting row takes no place: the one place goes to the due row's group
    assert [r["line"] for r in board_horizon(rows, "next:3")["ahead"]] == [6]


@pytest.mark.unit
def test_the_waiting_words_say_the_lease_holder_the_named_session_or_the_next_reader():
    from shiftlead.ui.inbox import board_waiting_on

    now = datetime(2026, 9, 22, 12, tzinfo=UTC)
    lease = {"ref": "TD-122", "status": "claimed", "at": (now - timedelta(hours=1)).isoformat()}
    row = {"repo": "shiftlead", "refs": ["TD-122"], "session": "grinder-ao-1"}
    holder = {"id": "ao-x-2", "name": "grinder-ao-2", "state": "working", "progress": [lease]}
    named = {"id": "ao-x-1", "name": "grinder-ao-1", "state": "idle", "progress": []}
    assert board_waiting_on(row, [named, holder], now) == "waiting on grinder-ao-2 — holds TD-122"
    assert board_waiting_on(row, [named], now) == "waiting on grinder-ao-1"
    assert board_waiting_on(row, [{**named, "state": "exited"}], now) == (
        "waiting on the next session to read shiftlead's board"
    )
    # an expired lease holds nothing; a session named by its uuid's first eight is found by adapter_id
    old = {**holder, "progress": [{**lease, "at": (now - timedelta(days=2)).isoformat()}]}
    uuid = {"id": "ao-x-3", "name": "w3", "state": "idle", "adapter_id": "294349ee-7da4"}
    assert board_waiting_on({**row, "session": "294349ee"}, [old, uuid], now) == "waiting on w3"


@pytest.mark.unit
def test_the_waiting_row_offers_reply_done_and_open_board_and_no_answers_or_snooze(tmp_path, monkeypatch):
    host(tmp_path, monkeypatch)
    from shiftlead.ui.app import board_rows, inbox_sections, templates

    it = {**decide_item(decided="approve"), "waiting_on": "session"}
    rows = board_rows(report(tmp_path / "samscrape", it))
    s = inbox_sections([], now=datetime(2026, 9, 22, 12, tzinfo=UTC), boards=rows)
    assert s["count"] == 0 and len(s["waiting"]) == 1
    html = templates.get_template("inbox_rows.html").render(rows=s["waiting"], section="waiting")
    assert "decided: approve · Sep 21" in html
    assert "waiting on the next session to read samscrape&#39;s board" in html
    assert 'data-act="board_reply"' in html and 'data-board-act="done"' in html
    assert "Snooze" not in html and "btn sm answer" not in html and "Go with it" not in html
    # stale, it is a Needs you row again, saying nobody has acted, with the board row's controls
    stale = board_rows({**report(tmp_path / "samscrape", it), "today": "2026-09-24"})
    s = inbox_sections([], now=datetime(2026, 9, 24, 12, tzinfo=UTC), boards=stale)
    assert s["count"] == 1 and not s["waiting"]
    html = templates.get_template("inbox_rows.html").render(rows=s["needs"], section="needs")
    assert "decided Sep 21 — no session has acted in 3 d" in html and "Snooze" in html


# ── §4.5a **Inbox board row: detail block** (TD-304, built by TD-312) ──────────────────────────────

BLOCK = [
    "- **Context:** The backup <script>x</script> stopped.",
    "  - nightly costs 2 GB",
    "  - weekly costs less",
    "- **Question:** Back it up? Answers: Never | Always.",
    "- **Recommended:** Nightly. Decided: Never (2026-09-01).",
]


@pytest.mark.unit
def test_a_board_rows_detail_block_is_drawn_in_its_fold_nested_and_as_text(tmp_path, monkeypatch):
    """A `decide` item with a block draws it under *details*, nested bullets as nested lists, the
    fold open because it has answers to press; `<script>`, `Answers:` and `Decided:` inside it are
    text and change no field; the find box matches its words."""
    rows, html = rows_html(tmp_path, monkeypatch, {**decide_item(), "detail": BLOCK})
    r = rows[0]
    assert r["detail"] == "\n".join(BLOCK)
    assert r["answers"] == ["approve", "hold", "ask <b>Ann</b>"] and r["decided"] is None
    assert "nightly costs 2 gb" in r["find"]
    assert '<details class="fold"' in html and " open><summary>details</summary>" in html
    assert "<ul><li><strong>Context:</strong> The backup &lt;script&gt;x&lt;/script&gt; stopped.<ul><li>nightly" in html
    assert "<script>x" not in html and "Back it up? Answers: Never | Always." in html
    assert html.count('data-board-act="decide"') == 4  # the three answers and Go with it: none from the block


@pytest.mark.unit
def test_a_block_with_nothing_to_press_is_folded_shut_and_no_block_draws_as_before(tmp_path, monkeypatch):
    plain = item(9, "**Short.**", "2026-09-20", "2d overdue")
    rows, html = rows_html(tmp_path, monkeypatch, {**plain, "detail": BLOCK})
    assert '<details class="fold"' in html and "<summary>details</summary>" in html  # the fold, for a short line
    assert " open><summary>" not in html
    # decided: nothing to press, so shut
    _, html = rows_html(tmp_path, monkeypatch, {**decide_item(decided="approve"), "detail": BLOCK})
    assert " open><summary>" not in html and "detailblock" in html
    # no key, an empty list, or not a list of strings: the row as it was
    for d in ({}, {"detail": []}, {"detail": "- **Context:** x"}, {"detail": [1, 2]}):
        rows, html = rows_html(tmp_path, monkeypatch, {**plain, **d})
        assert rows[0]["detail"] == "" and '<details class="fold"' not in html


@pytest.mark.unit
def test_the_standing_says_whom_a_reply_reaches_before_the_press():
    """design §4.5a *Inbox board row: standing* (TD-142): a live lease on one of the item's refs is
    *still on <ref> — <holder> holds it*; else a live record the item's session names is *moved on*;
    else *gone*; an item with no session and no refs draws nothing."""
    from shiftlead.ui.inbox import board_standing

    now = datetime(2026, 9, 22, 12, tzinfo=UTC)
    lease = {"ref": "TD-122", "status": "claimed", "at": (now - timedelta(hours=1)).isoformat()}
    row = {"repo": "shiftlead", "refs": ["TD-9", "TD-122"], "session": "grinder-ao-1"}
    holder = {"id": "ao-x-2", "name": "grinder-ao-2", "state": "working", "progress": [lease]}
    named = {"id": "ao-x-1", "name": "grinder-ao-1", "state": "idle", "progress": []}
    got = board_standing(row, [named, holder], now)
    assert got == {
        "word": "still on",
        "holder": "grinder-ao-2",
        "ref": "TD-122",
        "text": "still on TD-122 — grinder-ao-2 holds it",
    }
    assert board_standing(row, [named], now)["text"] == "moved on"
    assert board_standing(row, [{**named, "state": "exited"}], now)["text"] == "gone"
    # an expired lease, or a closed holder, holds nothing
    old = {**holder, "progress": [{**lease, "at": (now - timedelta(days=2)).isoformat()}]}
    assert board_standing(row, [old], now)["text"] == "gone"
    assert board_standing(row, [{**holder, "state": "closed"}], now)["text"] == "gone"
    assert board_standing({"repo": "shiftlead", "refs": [], "session": ""}, [holder], now) is None


@pytest.mark.unit
def test_the_row_draws_its_standing_and_hands_its_refs_to_reply(tmp_path, monkeypatch):
    host(tmp_path, monkeypatch)
    from shiftlead.ui.app import board_rows, inbox_sections, templates, with_standings
    from shiftlead.ui.inbox import board_horizon

    now = datetime(2026, 9, 22, 12, tzinfo=UTC)
    lease = {"ref": "TD-122", "status": "claimed", "at": (now - timedelta(hours=1)).isoformat()}
    holder = {"id": "ao-x-2", "name": "grinder-ao-2", "state": "working", "progress": [lease]}
    due = {**item(4, "**Rebase it.** Context: TD-122. Due: 2026-09-20.", "2026-09-20", "2d overdue")}
    due.update(session="grinder-ao-1", refs=["TD-122"])
    ahead = {**item(5, "**Later.** Due: 2026-09-25.", "2026-09-25", ""), "session": "grinder-ao-1", "refs": []}
    ahead["overdue_days"] = None
    rows = board_rows(report(tmp_path / "shiftlead", due, ahead))
    s = inbox_sections([], now=now, boards=rows, fleet=[holder])
    html = templates.get_template("inbox_rows.html").render(rows=s["needs"], section="needs")
    assert "grinder-ao-1 · still on TD-122 — grinder-ao-2 holds it" in html
    assert "data-refs='[\"TD-122\"]'" in html and "mailed to grinder-ao-2 (holds TD-122)" in html
    # the horizon's coming-up rows carry theirs too; the cache's rows are never written to
    hz = with_standings(board_horizon(rows, "all"), [holder], now)
    assert [r["standing"]["text"] for r in hz["ahead"]] == ["gone"]
    assert all("standing" not in r for r in rows)


@pytest.mark.unit
def test_a_decided_lines_waiting_words_name_its_work_orders_holder_or_the_teams_that_pick_it(tmp_path):
    """TD-384 slice 2 (§4.5 screen 6): a decided line is a work order, `board:<key>` by the repo's
    own reader — a lease on it is *holds board:<key>*; held by nobody and its session gone, it is
    *pickable by <team>* for each team whose `free-pick` lane takes it, with the team's wound-down
    state when none is live; a `fyi` line and a repo no team services keep the next reader."""
    from sessionorc import workorders
    from shiftlead.ui.inbox import board_waiting_on

    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(
        pathlib.Path(__file__).resolve().parent.parent / "scripts" / "nudge_user_attention.py", root / "scripts"
    )
    shutil.copy2(LEDGERBOARD, root / "scripts")
    text = (
        "decide 2026-10-01 (session gone-1 on kmaster) — **Keep the nightly backup?** Context: TD-777."
        " Due: 2026-10-02. Answers: keep | drop. Decided: keep (2026-10-03)."
    )
    ref = workorders.ref(root, text)
    assert workorders.is_work_order(ref)
    now = datetime(2026, 10, 4, 12, tzinfo=UTC)
    row = {"repo": "repo", "root": str(root), "text": text, "decided": "keep", "session": "gone-1", "refs": ["TD-777"]}
    lease = {"ref": ref, "status": "claimed", "at": (now - timedelta(hours=1)).isoformat()}
    g1 = {"id": "ao-g1", "name": "g1", "state": "working", "team": "grind", "repo": str(root), "lane": ["free-pick"]}
    assert board_waiting_on(row, [{**g1, "progress": [lease]}], now) == f"waiting on g1 — holds {ref}"
    assert board_waiting_on(row, [g1], now) == "pickable by grind"
    down = {**g1, "state": "exited", "out_of_work": {"at": "2026-10-04T10:00:00Z", "why": "nothing pickable"}}
    assert board_waiting_on(row, [down], now) == "pickable by grind · grind wound down — starts on `on_work`"
    assert board_waiting_on(row, [down], now, {"grind"}) == "pickable by grind · the start row is in Needs you"
    # a team that stopped rather than wound down (nobody declared) is never started by rule 8 (TD-781)
    stopped = {**g1, "state": "exited"}
    assert board_waiting_on(row, [stopped], now) == "pickable by grind · grind stopped — Start it"
    # a seat that never declares does not keep its team from *wound down*; a person's session is not its crew
    seat = {**stopped, "id": "ao-t1", "name": "t1", "seat": "techlead"}
    mine = {**stopped, "id": "ao-p1", "name": "p1", "unattended": False}
    assert board_waiting_on(row, [down, seat, mine], now).endswith("grind wound down — starts on `on_work`")
    # a lane that takes no free-pick work, a fyi line, and no team: the next reader
    nobody = "waiting on the next session to read repo's board"
    assert board_waiting_on(row, [{**g1, "lane": ["design-first"]}], now) == nobody
    assert board_waiting_on({**row, "kind": "fyi"}, [g1], now) == nobody
    assert board_waiting_on(row, [], now) == nobody
    # a record whose repo will not resolve is passed over, never the page's error
    assert board_waiting_on(row, [{**g1, "repo": "bad\x00path"}, g1], now) == "pickable by grind"
    # a repo no team services names nobody; the id is ledgerboard's, the same with no script in the repo
    assert board_waiting_on({**row, "root": str(tmp_path)}, [g1], now) == nobody
    assert workorders.ref(tmp_path / "nowhere", text) == ref


def test_a_decided_lines_teams_skip_a_resumed_away_record_and_read_live_from_any_one(tmp_path):
    """TD-393 (`_order_teams`): a record resumed as another (`superseded_by`) names no team, and a
    team with one live and one ended record reads live whichever comes first — never *wound down*."""
    from shiftlead.ui.inbox import board_waiting_on

    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(
        pathlib.Path(__file__).resolve().parent.parent / "scripts" / "nudge_user_attention.py", root / "scripts"
    )
    shutil.copy2(LEDGERBOARD, root / "scripts")
    text = (
        "decide 2026-10-01 (session gone-1 on kmaster) — **Keep the nightly backup?** Context: TD-777."
        " Due: 2026-10-02. Answers: keep | drop. Decided: keep (2026-10-03)."
    )
    now = datetime(2026, 10, 4, 12, tzinfo=UTC)
    row = {"repo": "repo", "root": str(root), "text": text, "decided": "keep", "session": "gone-1", "refs": ["TD-777"]}
    g1 = {"id": "ao-g1", "name": "g1", "state": "working", "team": "grind", "repo": str(root), "lane": ["free-pick"]}
    old = {**g1, "id": "ao-old", "name": "old", "team": "gone", "state": "exited", "superseded_by": "ao-g1"}
    assert board_waiting_on(row, [old, g1], now) == "pickable by grind"
    ended = {**g1, "id": "ao-g0", "name": "g0", "state": "exited"}
    for fleet in ([g1, ended], [ended, g1]):
        assert board_waiting_on(row, fleet, now) == "pickable by grind", [r["id"] for r in fleet]


@pytest.mark.unit
def test_every_board_row_draws_its_id_and_every_press_on_it_carries_it(tmp_path, monkeypatch):
    """§4.5a *board row: id* (§4.4 *A board line's id*, TD-603, TD-607): the row's `key` is the
    host agent's reading's `board:<key>` for its text (TD-615) — the work orders' id — drawn in mono
    before the due words as a control that copies it, and sent as `data-key` by every press on the
    row; an item the reading gave none draws none and sends it empty. The page's script puts it in
    every board body."""
    import re

    from sessionorc import workorders

    repo(tmp_path, "samscrape")  # the reader beside the board, which names the line
    it = decide_item()
    it["key"] = workorders.ref(tmp_path / "samscrape", it["text"])  # as the host agent's reading gives it
    rows, html = rows_html(tmp_path, monkeypatch, it)
    key = rows[0]["key"]
    assert workorders.is_work_order(key) and key == workorders.ref(tmp_path / "samscrape", it["text"])
    chip = re.search(r'<button class="mono boardkey"[^>]*>([^<]*)</button>', html)
    assert chip and chip.group(1) == key
    assert f'data-copy="{key}"' in chip.group(0) and f'data-copied="copied {key}"' in chip.group(0)
    assert "type it in chat or in ao board show" in chip.group(0)
    assert html.index("boardkey") < html.index("data-slot")  # before the due words
    presses = re.findall(r"<button[^>]*data-board=[^>]*>", html)
    assert len(presses) >= 5 and all(
        f'data-key="{key}"' in b for b in presses
    )  # answers, Reply, Go with it, Snooze, Done
    rows, html = rows_html(tmp_path, monkeypatch, {**it, "key": ""})
    assert rows[0]["key"] == "" and "boardkey" not in html and 'data-key=""' in html
    js = (pathlib.Path(__file__).resolve().parent.parent / "src/shiftlead/ui/static/app.js").read_text()
    assert js.count('key: b.dataset.key || ""') == 3  # Snooze/Done/decide, Reply, Not right…
    assert 'AO.toast(b.dataset.copied || "copied", true)' in js
