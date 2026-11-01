# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-770, design §4.5 screen 11 item 2 and screen 12 *A card*, §4.5a *Repo page: Technical debt cards*
and *Queue page, Up next: grip / ⤒ ↑ ↓*: the Repo page draws the repo's Queue cards in rank order, by
the Queue's own partials, a move posts `rank_move` with the two neighbours of the whole Up next order,
and a row keeps what the ledger row carried — its owner, *needs a team*, its settle mark."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
from datetime import UTC, datetime

import pytest
from conftest import scratch_dir
from fastapi.testclient import TestClient

from sessionorc.client import AgentError

pytestmark = pytest.mark.unit

NOW = datetime.now(UTC)
JS = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui" / "static" / "app.js"


def reading(name: str, root: str, entries: list[dict]) -> dict:
    return {"name": name, "root": root, "ledger": {"path": "docs/technical_debt.md", "entries": entries}, "prs": {"open": []}, "at": NOW.isoformat()}  # fmt: skip


def row(repo: str, tid: str, title: str, **kw) -> dict:
    return {"qid": f"{repo}#{tid}", "repo": repo, "id": tid, "title": title, "priority": "Medium", "state": "ready",
            "needs": None, "pr": None, "holder": None, "key": "", "lined": False, "archived": False, **kw}  # fmt: skip


def card(top: dict, rows=(), group="up_next", place=None, status="ready", **kw) -> dict:
    members = [top["qid"], *(r["qid"] for r in rows if not r["archived"])]
    done = sum(1 for r in rows if r["archived"])
    return {"id": top["qid"], "key": "0i", "lined": True, "top": {**top, "parent": None, "depth": 0, "after": []},
            "rows": list(rows), "done": done, "of": len(members) + done, "status": status, "group": group, "place": place,
            "order": members, "repos": sorted({top["repo"], *(r["repo"] for r in rows)}), "passed_over": [], **kw}  # fmt: skip


def queue() -> dict:
    """In progress: TD-10, held by grinder-1. Up next: TD-20 with its build TD-21 (and TD-19 archived),
    a card the person holds (TD-30), a card of another repo (db#TD-5), and a card spanning both repos
    (db#TD-7 with samscrape's TD-40)."""
    return {
        "cards": [
            card(row("samscrape", "TD-10", "recover stuck notices", state="held by grinder-1", holder={"id": "g1", "name": "grinder-1", "state": "working"}), group="in_progress"),
            card(
                row("samscrape", "TD-20", "the queue's design", priority="High"),
                [row("samscrape", "TD-21", "build the queue", depth=1, parent="samscrape#TD-20", after=["samscrape#TD-30"]),
                 row("samscrape", "TD-19", "an old step", state="done #77", pr=77, archived=True, depth=1, parent="samscrape#TD-20")],
                place=1,
            ),
            card(row("samscrape", "TD-30", "keep this one back", state="", needs="decision"), place=2, status="needs you"),
            card(row("db", "TD-5", "a db entry"), place=3),
            card(row("db", "TD-7", "the cross-repo top"), [row("samscrape", "TD-40", "samscrape's half", state="after db#TD-7", depth=1, parent="db#TD-7")], place=4),
        ],
        "completed": [],
        "other_work": [],
        "at": NOW.isoformat(),
    }  # fmt: skip


def entries() -> list[dict]:
    e = {"for_page": "pickable", "priority": "medium", "owner": "grinder"}
    return [
        {**e, "id": "TD-10", "title": "recover stuck notices"},
        {**e, "id": "TD-20", "title": "the queue's design", "for_page": "design", "owner": "designer"},
        {**e, "id": "TD-21", "title": "build the queue", "needs_team": True},
        {**e, "id": "TD-30", "title": "keep this one back", "for_page": "for-you", "blocked_by": ["decision (paul)"]},
        {**e, "id": "TD-40", "title": "samscrape's half", "for_page": "blocked"},
        {**e, "id": "TD-50", "title": "filed since the reading"},
    ]


def fake(repos: dict, q: dict | None, moves: list | None = None, refuse: str = ""):
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "queue":
                assert kw.get("omit") == ["completed"]  # the Repo page draws no completed card
                if q is None:
                    raise AgentError("unknown method: queue")
                return q
            if method == "rank_move":
                if refuse:
                    raise AgentError(refuse)
                (moves if moves is not None else []).append(kw)
                return {"moved": True, "card": kw["ids"][0], "flush": 60}
            return {"repos": repos, "doing_log": {}, "list": [], "usage": {}, "host": {"name": "kmaster"}}.get(
                method, {}
            )

    return Fake


def client(monkeypatch, tmp_path, Fake):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    return TestClient(ui.create_app())


def repos(tmp_path) -> dict:
    s, d = str(tmp_path / "samscrape"), str(tmp_path / "db")
    return {s: reading("samscrape", s, entries()), d: reading("db", d, [{"id": "TD-5", "title": "a db entry", "for_page": "pickable", "priority": "medium", "owner": "grinder"}, {"id": "TD-7", "title": "the cross-repo top", "for_page": "pickable", "priority": "medium", "owner": "grinder"}])}  # fmt: skip


def column(html: str, key: str) -> str:
    """One column of the board (§4.5 screen 11, TD-903), its markup to the next column's."""
    at = html.index(f'data-col="{key}"')
    return html[at : html.index('class="bcol"', at)]


def cards_of(html: str, key: str = "build") -> dict[str, str]:
    """Each card group drawn in a column of the board, by its card's id, in page order."""
    parts = re.split(r'(?=<div class="qcard bcard)', column(html, key))[1:]
    return {re.search(r'data-card="([^"]+)"', p).group(1): p for p in parts}


def test_the_board_draws_a_columns_rows_by_card_in_rank_order(tmp_path, monkeypatch):
    """§4.5 screen 11 *A row* (TD-903): each column's queued rows in the Queue's order, the rows of one card
    together; a card whose entries are in two columns is in both, each with its own rows."""
    c = client(monkeypatch, tmp_path, fake(repos(tmp_path), queue()))
    html = c.get("/repo/samscrape").text
    # Build: the In progress card first, the design's build, then an entry filed since the reading; db's own
    # card is not drawn here, and samscrape's half of the spanning card is blocked, folded at the foot
    assert list(cards_of(html)) == ["samscrape#TD-10", "samscrape#TD-20", "samscrape#TD-50"]
    assert 'data-unfold="build:blocked" data-unsent>1 blocked' in column(html, "build")
    assert list(cards_of(html, "design")) == ["samscrape#TD-20"]
    assert list(cards_of(html, "foryou")) == ["samscrape#TD-30"]  # held by its decision (paul): waits on them
    assert 'id="debt-pickable"' not in html  # the kind lists are gone; the count line stays
    # the whole Up next order rides on each column, every repo's, for a move's neighbours
    up = re.search(r"data-upnext='([^']*)'", html).group(1)
    assert json.loads(up) == ["samscrape#TD-20", "samscrape#TD-30", "db#TD-5", "db#TD-7"]


def test_a_card_in_two_columns_draws_its_rows_with_the_queue_cards_row(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(repos(tmp_path), queue()))
    html = c.get("/repo/samscrape").text
    design, build = cards_of(html, "design")["samscrape#TD-20"], cards_of(html)["samscrape#TD-20"]
    # the row is the Queue card's row partial: its id (the `#TD-20` link's target), badge, title (TD-903)
    assert '<div class="qrow" style="--qd: 1" id="TD-20"' in design and "qpri qp-high" in design
    assert "the queue&#39;s design" in design and 'id="TD-21"' not in design
    assert (
        'id="TD-21"' in build
        and 'after <a class="qon" href="#TD-30" data-on="TD-30"' in build
        and 'id="TD-20"' not in build
    )
    assert 'id="TD-19"' not in html  # an archived member is the Queue's, not the board's


def test_only_an_up_next_cards_first_row_in_a_column_moves(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(repos(tmp_path), queue()))
    html = c.get("/repo/samscrape").text
    d = cards_of(html)
    working = d["samscrape#TD-10"]  # In progress: no number and no grip
    assert "draggable" not in working and "data-move" not in working and "data-up" not in working
    assert "grinder-1" in working  # the holder's pill
    held = cards_of(html, "foryou")["samscrape#TD-30"]  # a card on the person's decision is in Up next, and moves
    assert 'draggable="true"' in held and held.count("data-move=") == 3 and "moves TD-30's card" in held
    assert "data-move" not in d["samscrape#TD-50"]  # not on the Queue yet: nothing to move
    # one card's grip in each column it has a row in
    assert cards_of(html, "design")["samscrape#TD-20"].count("data-move=") == 3
    assert d["samscrape#TD-20"].count("data-move=") == 3


def test_a_row_keeps_what_the_ledger_row_carried(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(repos(tmp_path), queue()))
    html = c.get("/repo/samscrape").text
    build = cards_of(html)["samscrape#TD-20"]
    assert "· grinder" in build and "needs a team" in build and "data-tdhold" not in build  # no Hold (TD-1297)
    assert "· designer" in cards_of(html, "design")["samscrape#TD-20"]  # the design entry's owner
    # For you's row is the Inbox's ledger row: a decision's answers, never a Release
    held = cards_of(html, "foryou")["samscrape#TD-30"]
    assert 'data-act="ledger" data-id="person"' in held and "ledger_release" not in held and "Release" not in held


def test_a_card_spanning_two_repos_is_drawn_on_both_pages(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(repos(tmp_path), queue()))
    db = cards_of(c.get("/repo/db").text)
    assert list(db) == ["db#TD-5", "db#TD-7"]
    assert (
        'id="TD-7"' in db["db#TD-7"] and ">samscrape#TD-40<" not in db["db#TD-7"]
    )  # each page draws its own repo's rows


def test_no_queue_reading_draws_the_columns_with_no_number_and_no_grip(tmp_path, monkeypatch):
    """§4.5 screen 11: where the home serves no Queue reading (a node, a home before its first tick) the
    columns are the same, in the ledger's order, with no number and no grip."""
    c = client(monkeypatch, tmp_path, fake(repos(tmp_path), None))
    html = c.get("/repo/samscrape").text
    assert 'id="board"' in html and "data-move" not in html and "qgrip" not in html and "bgut" not in html
    assert 'id="TD-21"' in column(html, "build") and 'id="TD-20"' in column(html, "design")


def test_a_move_posts_rank_move_with_its_neighbours(tmp_path, monkeypatch):
    moves: list = []
    c = client(monkeypatch, tmp_path, fake(repos(tmp_path), queue(), moves))
    got = c.post("/api/rank/move", json={"ids": ["samscrape#TD-30"], "prev": None, "next": "samscrape#TD-20"})
    assert got.status_code == 200 and got.json()["moved"] is True
    assert moves == [{"ids": ["samscrape#TD-30"], "prev": None, "next": "samscrape#TD-20"}]
    assert c.post("/api/rank/move", json={}).status_code == 400


def test_a_refused_move_is_a_400_in_the_homes_words(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(repos(tmp_path), queue(), refuse="TD-10 is In progress: it does not move"))
    got = c.post("/api/rank/move", json={"ids": ["samscrape#TD-10"], "prev": None, "next": None})
    assert got.status_code == 400 and "In progress" in got.json()["detail"]


def test_the_page_puts_a_refused_card_back_and_says_why():
    js = JS.read_text()
    body = js[js.index("async function moveCard(") :]
    body = body[: body.index("\n    }\n")]
    # moved at once, then back to the order before, the reason under the heading
    assert body.index("placeCards(m.order)") < body.index('fetch("/api/rank/move"') < body.index("placeCards(before)")
    # every column of the board takes the order, so a card drawn in two columns moves in both (TD-903)
    assert '$$(".qcards", box).forEach((q) => {' in js
    assert "why.textContent" in body and "why.hidden = false" in body
    # a link to an entry opens the card that holds it before it scrolls there
    show = js[js.index("function reveal(") :]
    show = show[: show.index("\n    }\n")]
    assert show.index("toggleFold(card)") < show.index("el.scrollIntoView(")
    assert "reveal(el, false)" in js[js.index("function showHash()") :][:200]


PROBE = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const s = src.indexOf("AO.rankMove = function"), e = src.indexOf("\\n  };\\n", s);
const AO = {}; eval(src.slice(s, e + 5));
const o = ["a", "b", "c", "d"];
console.log(JSON.stringify([
  AO.rankMove(o, "c", "top"), AO.rankMove(o, "a", "top"), AO.rankMove(o, "c", "up"), AO.rankMove(o, "d", "down"),
  AO.rankMove(o, "b", "down"), AO.rankMove(o, "a", {after: "c"}), AO.rankMove(o, "d", {before: "b"}), AO.rankMove(o, "x", "up"),
]));
"""


def test_a_moves_neighbours_are_the_whole_orders():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "rank_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(JS)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    top, top_first, up, last_down, down, after, before, unknown = json.loads(out.stdout)
    assert top == {"prev": None, "next": "a", "order": ["c", "a", "b", "d"]}
    assert top_first is None and last_down is None and unknown is None  # a move that moves nothing lands nothing
    assert up == {"prev": "a", "next": "b", "order": ["a", "c", "b", "d"]}
    assert down == {"prev": "c", "next": "d", "order": ["a", "c", "b", "d"]}
    assert after == {"prev": "c", "next": "d", "order": ["b", "c", "a", "d"]}
    assert before == {"prev": "a", "next": "b", "order": ["a", "d", "b", "c"]}


# -- TD-890 (TD-888's design, §4.5 *Page loads* *Nothing the page does not read*, screen 12 *the Queue has
# no Snooze*): a Queue card's mail rows send no `data-find` and no Snooze; the Inbox's keep both --------

TEMPLATES = JS.parent.parent / "templates"


def _lean_rows(tmp_path, monkeypatch):
    from test_ui_board import host, item, report
    from test_ui_inbox import entry

    from shiftlead.ui.app import board_rows, templates

    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    of = {"name": "samscrape", "label": "samscrape", "teams": ["sam"]}
    board = board_rows(
        report(root, item(9, "pick a name. Due: 2026-09-20.", "2026-09-20", "2d overdue")), {str(root.resolve()): of}
    )
    es = [entry("m-1", "ask", text="merge PR 9?", subject="merge PR 9?", answers=["merge it", "hold it"]), *board]
    queue = "".join(templates.get_template("queue_mail.html").render(e=e, section="needs") for e in es)
    inbox = templates.get_template("inbox_rows.html").render(rows=es, section="needs")
    return queue, inbox


def test_a_queue_cards_mail_rows_send_no_find_text_and_no_snooze(tmp_path, monkeypatch):
    queue, inbox = _lean_rows(tmp_path, monkeypatch)
    assert queue.count('class="mailrow') == inbox.count('class="mailrow') == 2
    assert "data-find=" not in queue and inbox.count("data-find=") == 2
    assert ">Snooze" not in queue and 'data-act="snooze"' not in queue and 'data-board-act="snooze"' not in queue
    assert 'data-act="snooze"' in inbox and inbox.count('data-board-act="snooze"') == 3
    # a card's board item has no *on the board —* footer (TD-1066); the Inbox's says Snooze moves its `Due:` date
    assert "Snooze moves its" not in queue and "on the board —" not in queue
    assert "Reply writes" not in queue  # no Reply word on a card (TD-914)
    assert "Snooze moves its <code>Due:</code> date" in inbox


def test_no_subject_or_answer_draws_a_title_repeating_its_text(tmp_path, monkeypatch):
    """A `title` equal to its element's text is not drawn (TD-888): the subject line and an answer's label
    are whole on hover by the script, which sets the title on a line that is in fact clipped (run under node by
    `test_ui_whole_on_hover.py`, TD-894)."""
    queue, inbox = _lean_rows(tmp_path, monkeypatch)
    for html in (queue, inbox):
        assert '<div class="subj">merge PR 9?</div>' in html
        assert 'title="merge PR 9?"' not in html and 'title="merge it"' not in html
    assert 'class="h1 msgsubj">' in (TEMPLATES / "inbox_entry.html").read_text()


def test_every_snooze_in_the_row_renderer_is_the_inboxs_alone():
    """Each of the row renderer's Snooze menus (an ask, a state row, a board line, a promote, a red PR, a fork's
    PR, CI not run, work waiting) is drawn only off the Queue, so a kind added later is caught here too."""
    src = (TEMPLATES / "inbox_row.html").read_text()
    menus = [m.start() for m in re.finditer(r"<summary[^>]*>Snooze", src)]
    assert len(menus) == 8
    for at in menus:
        assert src[:at].rstrip().rsplit("\n", 2)[-2].strip() == "{%- if not drawn_on_queue %}", src[at - 200 : at]
    assert "{% set drawn_on_queue = true %}" in (TEMPLATES / "queue_mail.html").read_text()


def test_the_inbox_pages_own_queue_count_leaves_its_rows_whole(tmp_path, monkeypatch):
    """The Inbox page's context carries `on_queue`, its rail's *+ n on the Queue* count: the renderer's
    flag is a name no page defines, so an Inbox with entries on the Queue keeps its rows' find text and
    Snooze (#2136's review)."""
    from test_ui_inbox import entry

    from shiftlead.ui.app import templates

    host_rows = [entry("m-1", "ask", text="merge PR 9?")]
    html = templates.get_template("inbox_rows.html").render(rows=host_rows, section="needs", on_queue=3)
    assert "data-find=" in html and 'data-act="snooze"' in html


# -- TD-891 (TD-888's design, §4.5 *Page loads* *A row's folded details on a Queue card*): a fold a Queue card
# draws closed is sent empty and read on its first open, `GET /api/fold?key=`, the Inbox's own fold body -----


def _fold_body(html: str, key: str) -> str:
    """What a fold of `key` holds after its summary, as the Inbox draws it."""
    m = re.search(
        rf'<details class="fold" data-fold="{re.escape(key)}"[^>]*><summary>details</summary>(.*?)</details>',
        html,
        re.S,
    )
    assert m, key
    return m.group(1)


def _fold_world(tmp_path, monkeypatch):
    from test_ui_board import host, item, report
    from test_ui_board import reading as boards_reading
    from test_ui_inbox import entry

    host(tmp_path, monkeypatch)
    root = tmp_path / "samscrape"
    line = {
        **item(9, "pick a name. Due: 2026-09-20.\n\nthe rest of the line, *in* markdown.", "2026-09-20", "2d overdue"),
        "detail": ["a detail block", "of two lines"],
    }
    rs = boards_reading(report(root, line))
    led = {
        "for_page": "for-you",
        "priority": "medium",
        "owner": "paul",
        "id": "TD-60",
        "title": "yours",
        "detail": ["why it is yours", "", "and what to do"],
    }
    rs[str(root)]["ledger"] = {"path": "docs/technical_debt.md", "entries": [led]}
    mail = entry("m-7", "note", text="the first paragraph.\n\nthe *rest*, folded.")
    return rs, mail


def _fold_fake(rs, mail, seen):
    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            seen.append(method)
            if method == "inbox":
                return {"entries": [mail], "handed": [{"id": "m-h1", "text": "handed.\n\nwhat the seat reads."}]}
            return {"repos": rs, "list": [], "host": {"name": "kmaster"}}.get(method, {})

    return Fake


def test_the_fold_route_answers_each_kind_with_the_inboxs_own_fold_body(tmp_path, monkeypatch):
    from shiftlead.ui import app as ui
    from shiftlead.ui.app import board_reading, ledger_for_you, templates

    rs, mail = _fold_world(tmp_path, monkeypatch)
    seen: list[str] = []
    monkeypatch.setattr(ui, "LocalClient", _fold_fake(rs, mail, seen))
    c = TestClient(ui.create_app())
    board = board_reading(rs)[0]
    ledger = [r for g in ledger_for_you(rs, [], {})["groups"] for r in g["rows"]]
    assert len(board) == 1 and len(ledger) == 1
    inbox = templates.get_template("inbox_rows.html").render(rows=[mail, *board, *ledger], section="needs")
    for key in (mail["id"], board[0]["id"], ledger[0]["row_id"]):
        r = c.get("/api/fold", params={"key": key})
        assert r.status_code == 200, (key, r.text)
        assert r.text.strip() == _fold_body(inbox, key).strip() != ""
        assert "total" in r.headers["server-timing"]
    # a row handed to a seat is read from `handed`, where the person's inbox carries it (#2139's review)
    handed = c.get("/api/fold", params={"key": "m-h1"})
    assert handed.status_code == 200 and "what the seat reads." in handed.text
    gone = c.get("/api/fold", params={"key": "m-nothing"})
    assert gone.status_code == 404 and "gone — reload" in gone.text


def test_a_queue_card_sends_a_closed_fold_empty_and_an_open_one_whole(tmp_path, monkeypatch):
    from shiftlead.ui.app import board_reading, ledger_for_you, templates

    rs, mail = _fold_world(tmp_path, monkeypatch)
    board = board_reading(rs)[0]
    ledger = [r for g in ledger_for_you(rs, [], {})["groups"] for r in g["rows"]]
    one = templates.get_template("queue_mail.html")
    for e, key in ((mail, mail["id"]), (board[0], board[0]["id"])):
        html = one.render(e=e, section="needs")
        assert f'data-fold="{key}" data-lazy="1"><summary>details</summary></details>' in html
    # drawn open — an entry with answers to press — it is sent whole, as it is shown
    held = {**ledger[0], "answers": ["yes", "no"]}
    html = one.render(e=held, section="needs")
    assert "data-lazy" not in html and "why it is yours" in html
    # the Inbox sends every fold whole
    inbox = templates.get_template("inbox_rows.html").render(rows=[mail, *board, *ledger], section="needs")
    assert "data-lazy" not in inbox and "the <em>rest</em>, folded." in inbox


def test_a_reread_queue_reopens_its_folds_and_fills_each_open_one():
    # `AO.fillFold` itself runs under node in test_ui_fill_fold.py (TD-898); this is its wiring
    js = JS.read_text()
    reopen = js[js.index("AO.reopenFolds = function") : js.index("AO.fillFold = async function")]
    assert "AO.fillFold(d)" in reopen
    q = js[js.index("AO.queue = function") :]
    assert "AO.reopenFolds(lists);" in q[: q.index("wire();")]


def _placed() -> dict:
    """`queue()` with each Up next card's `places` (TD-901): samscrape's cards 1, 2, db's 1, and the card
    spanning both db's 2 and samscrape's 3."""
    q = queue()
    places = {"samscrape#TD-20": [("samscrape", 1)], "samscrape#TD-30": [("samscrape", 2)], "db#TD-5": [("db", 1)],
              "db#TD-7": [("db", 2), ("samscrape", 3)]}  # fmt: skip
    for c in q["cards"]:
        c["places"] = [{"repo": r, "n": n} for r, n in places.get(c["id"], [])]
    return q


def test_the_repo_page_numbers_a_card_by_its_place_in_the_repo_and_sends_the_scope(tmp_path, monkeypatch):
    """§4.5 screen 11 *Numbers, grips and moves are the card's*, §4.4 *A move lands* (TD-901, TD-903): the board
    draws a card's place among the repo's own Up next cards, and its moves carry the repo as `scope`."""
    moves: list = []
    c = client(monkeypatch, tmp_path, fake(repos(tmp_path), _placed(), moves))
    html = c.get("/repo/samscrape").text
    held = cards_of(html, "foryou")["samscrape#TD-30"]
    assert '<span class="qplace" title="' in held and '">2</span>' in held  # samscrape's 2
    assert re.search(r'class="qcards bcards" data-upnext=\'[^\']*\' data-scope="samscrape"', html)
    got = c.post(
        "/api/rank/move",
        json={"ids": ["db#TD-7"], "prev": "samscrape#TD-20", "next": "samscrape#TD-30", "scope": "samscrape"},
    )
    assert got.status_code == 200
    assert moves == [{"ids": ["db#TD-7"], "prev": "samscrape#TD-20", "next": "samscrape#TD-30", "scope": "samscrape"}]
    js = JS.read_text()
    body = js[js.index("async function moveCard(") :]
    body = body[: body.index("\n    }\n")]
    assert "AO.rankMoveScoped(before, own, card.dataset.card, how)" in body and "...(scope ? { scope } : {})" in body


def test_the_repo_page_draws_no_held_row_for_an_old_clock_mark(tmp_path, monkeypatch):
    """TD-1297: an old clock's `held` mark on an entry draws no *held in <repo>'s ledger* row."""
    rs = repos(tmp_path)
    held = {"at": NOW.isoformat(), "by": "s-1", "words": "the person's session paul-1"}
    next(e for r in rs.values() for e in r["ledger"]["entries"] if e["id"] == "TD-10")["held"] = held
    html = client(monkeypatch, tmp_path, fake(rs, queue())).get("/repo/samscrape").text
    assert "held in samscrape's ledger" not in html and "the person&#39;s session paul-1" not in html
