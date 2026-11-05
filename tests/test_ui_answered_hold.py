"""TD-1331 slice 2 (TD-1316's build), design §4.5 screen 12 *Three wants*, screen 11 *For you*, screen 6 *Later*:
a held entry whose question the person answered is drawn *answered — waiting on <asker>* — on its Queue card in the
grey section beside *with you*, uncounted, with no answers, Answer… or Start session, Lift the hold and Open in its
⋯ — and `ledger_for_you` draws the same on the Repo page's For you and the Inbox's *Later*."""

from __future__ import annotations

from datetime import UTC, timedelta

from markupsafe import Markup
from test_queue import NOW

from shiftlead.ui.queue import attach, branch, item_start, qid, queue_view

ANSWERED = NOW - timedelta(minutes=30)


def _repos(tmp_path, *names: str, answers: bool = True) -> dict:
    """Repo facts with one held `decision (paul)` entry, TD-60, in each repo named."""
    out = {}
    for name in names:
        root = tmp_path / name
        led = {
            "for_page": "for-you",
            "priority": "medium",
            "id": "TD-60",
            "title": "held",
            "blocked_by": ["decision (paul)"],
            "written": (ANSWERED - timedelta(hours=2)).timestamp(),
            **({"answers": ["Yes", "No"], "default": 0} if answers else {}),
        }
        out[str(root)] = {"name": name, "root": str(root), "ledger": {"path": "docs/ledger", "entries": [led]}}
    return out


def _ask(about="TD-60", **kw) -> dict:
    """The person inbox's answered `ask` about the entry, as `person_inbox` hands it (`_owing` applied)."""
    e = {
        "id": "m-1",
        "from": "ao-r-designer@kmaster",
        "to": ["person"],
        "kind": "ask",
        "text": "Lift the hold on TD-60?",
        "about": about,
        "closed_reason": "replied",
        "closed_at": ANSWERED.isoformat().replace("+00:00", "Z"),
        "outcome": None,
        "answer_given": "",
        "answer_how": "you answered",
    }
    return {**e, **kw}


FLEET = [{"id": "ao-r-designer", "name": "designer", "state": "working", "repo": "/x/r"}]


def _rows(repos, inbox, fleet=FLEET, every=None):
    from shiftlead.ui.inbox import ledger_for_you

    got = ledger_for_you(repos, fleet, {}, NOW, inbox, every)
    return [r for g in got["groups"] for r in g["rows"]]


def test_ledger_for_you_carries_answered_while_the_question_owes(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask()])
    a = row["answered"]
    assert a["name"] == "designer" and a["kind"] == "ask" and a["mid"] == "m-1"
    assert a["words"] == "you answered" and a["age"] == "30m" and a["outcome"] is None
    # a pressed suggested answer is named in its words
    (row,) = _rows(_repos(tmp_path, "r"), [_ask(answer_given="Yes")])
    assert row["answered"]["words"] == "you answered “Yes”"
    # no question, or an asker gone with the debt unpaid: the need again
    assert _rows(_repos(tmp_path, "r"), [])[0]["answered"] is None
    assert _rows(_repos(tmp_path, "r"), [_ask()], fleet=[])[0]["answered"] is None


def test_a_bare_id_carried_by_two_repos_links_to_neither(tmp_path):
    repos = _repos(tmp_path, "r", "s")
    assert all(r["answered"] is None for r in _rows(repos, [_ask()]))
    # the Repo page passes one repo, and every repo's facts for the link's index
    one = {k: v for k, v in repos.items() if v["name"] == "r"}
    assert _rows(one, [_ask()], every=repos)[0]["answered"] is None
    assert _rows(one, [_ask()])[0]["answered"] is not None, "one repo alone: the bare id links"
    assert _rows(one, [_ask(about="r#TD-60")], every=repos)[0]["answered"] is not None


def test_a_done_outcome_draws_the_askers_line(tmp_path):
    done = {"state": "done", "text": "#2900 drops the hold", "at": (NOW - timedelta(minutes=5)).isoformat()}
    (row,) = _rows(_repos(tmp_path, "r"), [_ask(outcome=done)])
    assert row["answered"]["outcome"] == {"text": "#2900 drops the hold"}
    html = _render(row)
    assert "designer: #2900 drops the hold" in html and "the hold goes when its PR merges" not in html


def _render(row, mode=None, home=None) -> str:
    from shiftlead.ui.app import templates

    e = {**row, **({"home": home} if home else {})}
    if mode == "card":
        e["want"] = "answered"
        return templates.get_template("queue_mail.html").render(e=e, section="needs")
    return templates.env.get_template("inbox_row.html").module.row(e, "later")


def test_the_inbox_and_repo_row_reads_answered_with_no_answers_and_lift_the_hold_in_its_dots(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask()])
    html = _render(row)
    assert '<span class="st qans">answered — waiting on designer</span>' in html
    assert "you answered · in designer's ask, 30m ago — the hold goes when its PR merges" in html
    assert "its answers" not in html and 'data-index="0"' not in html, "no answers"
    assert ">Reply<" not in html and ">Go with it<" not in html and ">Start session<" not in html
    assert ">Done…<" not in html
    dots = html.split('class="more qdots"')[1]
    assert ">Lift the hold</button>" in dots and 'data-words="go ahead"' in dots and ">Open</a>" in dots
    # the same row unanswered draws its answers and controls as before
    plain = _render({**row, "answered": None})
    assert "qans" not in plain and "its answers" in plain and ">Reply<" in plain and ">Start session<" in plain


def _world(tmp_path, inbox, asks=()):
    """A card whose only member, `r#TD-60`, is held for the person, with its ledger item attached."""
    from shiftlead.ui.app import _with_you

    (row,) = _rows(_repos(tmp_path, "r"), inbox)
    q = qid("r", "TD-60")
    answered = row["answered"]
    word = "answered — waiting on designer" if answered else ""
    top = {"qid": q, "id": "TD-60", "repo": "r", "title": "held", "priority": "Medium", "needs": "decision",
           "state": word, "with_you": None, "answered": answered}  # fmt: skip
    card = {"id": q, "group": "up_next", "status": "" if answered else "needs you", "top": top, "rows": [],
            "order": [q], "start": q}  # fmt: skip
    reading = {"at": NOW.isoformat(), "cards": [card]}
    item = {**row, "home": "queue", "on_card": q, "on_row": q}
    drawn: list[dict] = []
    got = attach(
        {"needs": [item, *asks]},
        lambda e, sec: drawn.append(e) or Markup(f'<div class="mailrow">{e.get("id")}</div>'),
        (),
        lambda c, i: item_start(card, i, FLEET),
        lambda c, i: _with_you(card, i),
    )
    return queue_view(reading, NOW, got, fleet=FLEET), drawn


def test_the_card_draws_the_item_grey_uncounted_with_no_start_session(tmp_path):
    v, drawn = _world(tmp_path, [_ask()])
    (c,) = v["up_next"]
    assert c["wants"]["n"] == {"decide": 0, "do": 0, "read": 0} and len(c["wants"]["answered"]) == 1
    assert v["n"]["needs_you"] == 0 and c["edge"] != "needs"
    assert c["items_start"] is False, "it draws no Start session, so the header may draw its own"
    (e,) = drawn
    assert e["want"] == "answered" and e["start"] == {} and c["wants"]["answered"][0]["kind"] == ""
    from shiftlead.ui.app import templates

    html = templates.env.get_template("queue_card.html").module.card(c)
    head = html.split('<div class="qrows">')[0]
    assert 'class="qsec qwith" data-sec="with_you"' in head and "qwant" not in head
    word = templates.env.get_template("queue_row.html").module.state(c["top"])
    assert word == '<span class="qstate s-with">answered — waiting on designer</span>', "the row's word, grey"
    assert branch(c["top"]) == "open"


def test_the_card_item_draws_no_answers_or_answer_and_lift_the_hold_in_its_dots(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask()])
    html = _render(row, mode="card", home="queue")
    assert "answered — waiting on designer" in html and "you answered · in designer's ask" in html
    assert "Answer…" not in html and 'data-index="0"' not in html and ">Start session<" not in html
    assert 'class="st qneed"' not in html
    dots = html.split('class="more qdots"')[1]
    assert ">Lift the hold</button>" in dots and ">Open</a>" in dots
    assert html.count(">Lift the hold<") == 1, "Lift the hold only in its ⋯"


def test_a_second_open_question_is_its_own_decide_beside_the_word(tmp_path):
    from test_ui_inbox import entry

    ask = {**entry("m-2", "ask", text="and the other?"), "home": "queue", "on_card": "r#TD-060", "on_row": "r#TD-060"}
    v, _ = _world(tmp_path, [_ask()], asks=[ask])
    (c,) = v["up_next"]
    assert c["wants"]["n"]["decide"] == 1 and len(c["wants"]["answered"]) == 1
    assert c["status"] == "needs you"


def test_the_queue_reading_feeds_the_row_and_the_ui_reads_it_aware(tmp_path):
    # the `later` row's age is the answer's, read from a `Z` time
    (row,) = _rows(_repos(tmp_path, "r"), [_ask(closed_at=(NOW - timedelta(hours=2)).astimezone(UTC).isoformat())])
    assert row["answered"]["age"].startswith("2h")


def test_on_a_card_it_is_drawn_whole_its_details_folded_and_with_you_wins(tmp_path):
    (row,) = _rows(_repos(tmp_path, "r"), [_ask()])
    html = _render({**row, "ask": "Lift the hold on TD-60?", "detail": "why"}, mode="card", home="queue")
    assert '<div class="body sentence">Lift the hold on TD-60?</div>' in html, "its Ask: sentence, as a whole item"
    assert '" open>' not in html.split("data-fold=")[1][:80], "its details folded though it has answers"
    # the person's own session holding it: *with you* wins over the answered word, in `put` and in the row
    from shiftlead.ui.app import templates

    item = {**row, "home": "queue", "on_card": "r#TD-060", "on_row": "r#TD-060"}
    drawn: list[dict] = []
    attach({"needs": [item]}, lambda e, sec: drawn.append(e) or Markup(""), (), None, lambda c, i: "p")
    assert drawn[0]["want"] == "with_you"
    html = templates.get_template("queue_mail.html").render(e={**drawn[0], "with_you": "p"}, section="needs")
    assert "with you in p" in html and "answered — waiting on" not in html


# ---- the routes (TD-1335): each hands the person inbox to `ledger_for_you`, so the row reads answered there too ----


def _route_client(tmp_path, monkeypatch, *, inbox_fails=False, queue=None):
    """A UI over a fake home: repo `r` holding TD-60 for the person, its asker live, the person inbox holding its
    answered `ask` (or failing to read, `inbox_fails`), and `queue` as the home's Queue reading."""
    from test_ui_queue import client

    from sessionorc.client import AgentError

    repos = _repos(tmp_path, "r")
    for r in repos.values():
        r["ledger"]["path"] = "docs/technical_debt.md"
    fleet = [{**FLEET[0], "repo": str(tmp_path / "r")}]

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "inbox":
                if inbox_fails:
                    raise AgentError("the inbox could not be read")
                return {"entries": [_ask()] if kw.get("id") in (None, "person") and not kw.get("sent") else []}
            if method == "queue":
                if queue is None:
                    raise AgentError("unknown method: queue")
                return queue
            return {"repos": repos, "list": fleet, "host": {"name": "kmaster"}}.get(method, {})

    return client(monkeypatch, tmp_path, Fake)


WORD = "answered — waiting on designer"


def test_the_inbox_page_and_its_poll_draw_the_answered_row(tmp_path, monkeypatch):
    c = _route_client(tmp_path, monkeypatch)
    assert WORD in c.get("/inbox").text
    assert WORD in c.get("/api/person/inbox").json()["html"]["ledger"]


def test_the_queue_cards_item_reads_answered(tmp_path, monkeypatch):
    q = qid("r", "TD-60")
    top = {"qid": q, "id": "TD-60", "repo": "r", "title": "held", "priority": "Medium", "needs": "decision",
           "state": WORD, "with_you": None, "answered": {"mid": "m-1", "asker": "ao-r-designer"}}  # fmt: skip
    card = {"id": q, "group": "up_next", "status": "", "top": top, "rows": [], "order": [q], "start": q}
    html = _route_client(tmp_path, monkeypatch, queue={"at": NOW.isoformat(), "cards": [card]}).get("/queue").text
    item = html[html.index(f'data-card="{q}"') :]
    assert "you answered · in designer's ask" in item, "the card's item is the answered row, from card_mail"


def test_the_repo_pages_for_you_reads_answered_and_an_unread_inbox_draws_it_as_before(tmp_path, monkeypatch):
    html = _route_client(tmp_path, monkeypatch).get("/repo/r").text
    assert WORD in html and "you answered · in designer's ask" in html
    plain = _route_client(tmp_path, monkeypatch, inbox_fails=True).get("/repo/r")
    assert plain.status_code == 200 and 'href="/repo/r#TD-60"' in plain.text and WORD not in plain.text


def test_ledger_for_you_links_a_question_about_the_origin_path(tmp_path):
    """TD-1371: a question about `<origin path>#TD-n` links to the repo whose `remote` has that path."""
    repos = _repos(tmp_path, "r", "s")
    for r in repos.values():
        r["remote"] = f"git@github.com:O/{r['name']}.git"
    rows = _rows(repos, [_ask("o/r#TD-60")])
    assert [r["answered"] is not None for r in rows] == [True, False], "r's member alone, by its origin path"


# ---- TD-1368 slice 3: a board answer on the Inbox's *Later*, *For you* and the Queue card's item ----

DECIDED = "2026-10-15"  # the day before NOW


def _line(*refs, parts=(), decided=True, kind="decide", line=3) -> dict:
    """An open board item, as the boards reading carries it."""
    got = {"text": "Go", "date": DECIDED} if decided else None
    return {"kind": kind, "key": f"k{line}", "line": line, "refs": list(refs), "parts": list(parts),
            "decided": got, "decided_by": None, "session": ""}  # fmt: skip


def _carried(*refs, why="carried to TD-61", to=("TD-61",), closed=DECIDED) -> dict:
    """A closed decided line, as the boards reading's `carried` holds it."""
    return {"key": "kc", "ref": refs[0], "decided": {"text": "Go", "date": DECIDED}, "decided_by": None,
            "closed": {"date": closed, "why": why}, "to": list(to), "at": 9, "refs": list(refs),
            "parts": []}  # fmt: skip


def _board_repos(tmp_path, items=(), carried=(), extra=()) -> dict:
    repos = _repos(tmp_path, "r")
    (r,) = repos.values()
    r["ledger"]["entries"] += list(extra)
    r["boards"] = {"boards": [{"items": list(items), "carried": list(carried)}]}
    return repos


def _build(id="TD-62", part_of="TD-60", **kw) -> dict:
    """A `decision (paul)` build `Part of` TD-60, for the person."""
    return {"for_page": "for-you", "priority": "medium", "id": id, "title": "a build", "part_of": part_of,
            "blocked_by": ["decision (paul)"], "added": "2026-10-10", **kw}  # fmt: skip


def _ids(repos, inbox=(), fleet=FLEET) -> list[str]:
    return [r["id"] for r in _rows(repos, list(inbox), fleet)]


def test_an_open_decided_line_covering_an_entry_takes_its_row(tmp_path):
    # named, named second, listed in Parts:, or the parent of a held build: no ledger row while the line is open
    assert _ids(_board_repos(tmp_path, [_line("TD-60")], extra=[_build()])) == []
    assert _ids(_board_repos(tmp_path, [_line("TD-1", "TD-62")], extra=[_build()])) == ["TD-60"]
    assert _ids(_board_repos(tmp_path, [_line("TD-1", parts=["TD-62"])], extra=[_build()])) == ["TD-60"]
    # a build not held for the person is not covered by its parent's line
    free = _build(blocked_by=[])
    assert _ids(_board_repos(tmp_path, [_line("TD-60")], extra=[free])) == ["TD-62"]
    # an undecided line, or a decided fyi, leaves the rows (the undecided one is drawn in their place, below)
    assert _ids(_board_repos(tmp_path, [_line("TD-60", decided=False)], extra=[_build()])) == ["TD-60", "TD-62"]
    assert _ids(_board_repos(tmp_path, [_line("TD-60", kind="fyi")])) == ["TD-60"]


def test_a_line_on_another_repos_board_covers_that_repos_entry(tmp_path):
    repos = _repos(tmp_path, "r", "s")
    by = {r["name"]: r for r in repos.values()}
    by["s"]["boards"] = {"boards": [{"items": [_line("r#TD-60")]}]}
    assert [(r["name"], r["id"]) for r in _rows(repos, [])] == [("s", "TD-60")]


def test_a_closed_carried_line_draws_the_row_answered_with_its_foot(tmp_path):
    to = {"id": "TD-61", "title": "the carried work", "for_page": "pickable", "added": DECIDED, "owner": "grinder"}
    (row,) = _rows(_board_repos(tmp_path, carried=[_carried("TD-60")], extra=[to]), [])
    a = row["answered"]
    assert a["kind"] == "board" and a["asker"] == "TD-061" and a["board"]["to"] == ["TD-61"] and a["age"] == "1d"
    html = _render(row)
    assert '<span class="st qans">answered — waiting on TD-061</span>' in html
    assert "you answered “Go” on the board, 1d ago — carried to TD-61" in html
    assert "its answers" not in html and ">Start session<" not in html
    assert ">Lift the hold</button>" in html.split('class="more qdots"')[1]
    # on the card, the same item
    card = _render(row, mode="card", home="queue")
    assert "carried to TD-61" in card and "Answer…" not in card
    # TD-61 archived: no hold, the need again
    (row,) = _rows(_board_repos(tmp_path, carried=[_carried("TD-60")]), [])
    assert row["answered"] is None


def test_a_line_closed_in_other_words_names_its_holder_acting_on_it(tmp_path):
    claim = {"ref": "TD-60", "status": "claimed", "at": (NOW - timedelta(hours=1)).isoformat()}
    fleet = [{**FLEET[0], "repo": str(tmp_path / "r"), "unattended": True, "progress": [claim]}]
    repos = _board_repos(tmp_path, carried=[_carried("TD-60", why="done in #9", to=())])
    (row,) = _rows(repos, [], fleet)
    assert row["answered"]["name"] == "designer"
    assert "you answered “Go” on the board, 1d ago — designer acts on it" in _render(row)
    # nobody holds it: the need again
    assert _rows(repos, [], [{**fleet[0], "progress": []}])[0]["answered"] is None


def test_a_kept_waiting_member_reads_waits_until_its_date(tmp_path):
    repos = _board_repos(tmp_path, carried=[_carried("TD-60", why="kept waiting.", to=())])
    (r,) = repos.values()
    r["ledger"]["entries"][0]["kept_waiting"] = {"decision (paul)": DECIDED}
    (row,) = _rows(repos, [])
    assert row["answered"]["until"] == "2026-11-14"
    html = _render(row)
    assert '<span class="st qans">waits until 2026-11-14</span>' in html and "answered — waiting" not in html
    assert "its answers" not in html


def test_an_undecided_covering_line_stands_in_the_rows_place_on_later_and_the_card(tmp_path):
    from shiftlead.ui.queue import asked_entries, split_later

    (row,) = _rows(_board_repos(tmp_path, extra=[_build()]), [])[1:]  # TD-62, the build
    assert row["parent"] == "r#TD-060"
    line = {"row": "board", "repo_name": "r", "text": "Lift it? Context: TD-1.", "parts": []}
    assert asked_entries([{**line, "text": "Lift it? Context: TD-60."}]) == {"r#TD-060"}
    assert asked_entries([{**line, "parts": ["TD-62"]}]) == {"r#TD-001", "r#TD-062"}
    lf = {"groups": [{"repo": "r", "rows": [row]}]}
    for e in ({**line, "text": "Lift it? Context: TD-60."}, {**line, "parts": ["TD-62"]}):
        kept, *_ = split_later(lf, [e], {})
        assert kept["n"] == 0, e
    kept, *_ = split_later(lf, [line], {})
    assert kept["n"] == 1, "a line naming neither leaves the row"
    # on a card: the line drawn on the card takes the block of the build it covers
    item = {**row, "home": "queue", "on_card": "r#TD-60", "on_row": "r#TD-62", "later_section": "later"}
    board = {**line, "text": "Lift it? Context: TD-60.", "id": "b1", "home": "queue", "on_card": "r#TD-60",
             "on_row": "r#TD-60", "kind": "decide"}  # fmt: skip
    got = attach({"needs": [board]}, lambda e, sec: Markup(""), [item])
    assert [m["id"] for m in got["cards"]["r#TD-60"]["needs"]] == ["b1"], "the build's block gives way"


def test_open_decided_covers_reads_every_board(tmp_path):
    from sessionorc import queue

    opens = {"r#TD-060": {"id": "TD-60", "repo": "r"}, "r#TD-062": {**_build(), "repo": "r"}}
    got = queue.open_decided_covers({"s": [{"items": [_line("r#TD-60")]}]}, opens, queue.open_refs(opens, {}))
    assert got == {"r#TD-060", "r#TD-062"}


def test_a_kept_wait_keeps_its_age(tmp_path):
    repos = _board_repos(tmp_path, carried=[_carried("TD-60", why="kept waiting.", to=())])
    (r,) = repos.values()
    r["ledger"]["entries"][0]["kept_waiting"] = {"decision (paul)": DECIDED}
    (row,) = _rows(repos, [])
    assert row["answered"]["age"] == "1d" and "on the board, 1d ago — it waits until 2026-11-14" in _render(row)
