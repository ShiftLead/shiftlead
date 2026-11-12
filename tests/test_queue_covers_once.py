"""TD-1380 (TD-1378's design), §4.5 screen 12 *Three verbs* (*One line is one item, however many entries it
covers*), screen 11 *For you*, §4.5a *Queue card: what needs the person*: a board `decide` line that covers several
entries — its `Context:` refs, its `Parts:` ids, and its `decision (paul)` members `Part of` a `Context:` entry — is one
item on the page, on the card of the first it covers that an open card holds, with one *holds* line naming the rest;
none of the entries it covers draws its own Decide or Do block anywhere on the page, and the Repo page's For you draws
the line once and the other covered rows as plain rows."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from markupsafe import Markup
from test_queue import NOW
from test_queue_item_shape import card, inbox

from shiftlead.ui.queue import CONTEXT, asked_entries, attach, covered, item_home, split_later

TODAY = NOW.date().isoformat()
DESIGN = "**One more round?** Context: TD-050 decision (paul). Parts: TD-052, TD-051. Due: 2026-11-20."


def line(text: str = DESIGN, parts=("TD-052", "TD-051"), **kw) -> dict:
    """A board row as `board_rows` hands it, cut to what these reads read: `parts` the record's, never the text's."""
    return {"row": "board", "id": "board:/r:3", "key": "board:k1", "kind": "decide", "repo_name": "r", "text": text,
            "parts": list(parts), "decided": None, **kw}  # fmt: skip


def entry(n: int, part_of: str = "", held: bool = True) -> tuple[str, dict]:
    """An open entry as `ledger_for_you`'s `entries` carries it."""
    return f"r#TD-{n:03d}", {"repo": "r", "part_of": part_of or None, "part_of_raw": part_of or None,
                             "blocked_by": ["decision (paul)"] if held else []}  # fmt: skip


# TD-050 the design; TD-051, TD-052 its parts in `Parts:`; TD-053, TD-054 held members by `Part of` alone; TD-055 a
# part with no hold of its own; TD-056 another design's held part
ENTRIES = dict([entry(50), entry(51, "TD-050"), entry(52, "TD-050"), entry(54, "TD-050"), entry(53, "TD-050"),
                entry(55, "TD-050", held=False), entry(56, "TD-099")])  # fmt: skip


def index(*cards: tuple[str, list[int]]) -> dict:
    """`card_index`'s shape: each `r#TD-n` a card holds to `(card id, row qid)`."""
    return {f"r#TD-{n:03d}": (cid, f"r#TD-{n:03d}") for cid, ns in cards for n in ns}


def ledger_row(n: int, on_card: str = "", **kw) -> dict:
    """A `later` row of `split_later`'s (a `ledger_for_you` row homed on a card)."""
    q = f"r#TD-{n:03d}"
    return {"row": "ledger", "id": f"TD-{n:03d}", "row_id": f"ledger:r:TD-{n:03d}", "name": "r", "why": "decision",
            "later_section": "later", "home": "queue", "on_card": on_card or q, "on_row": q, **kw}  # fmt: skip


def drawn(e, sec):
    return Markup(e.get("key") or e.get("row_id"))


@pytest.mark.unit
def test_what_a_line_covers_is_its_context_then_its_parts_then_its_held_members_by_number():
    assert covered(line(), ENTRIES) == ["r#TD-050", "r#TD-052", "r#TD-051", "r#TD-053", "r#TD-054"]
    assert covered(line(), None) == ["r#TD-050", "r#TD-052", "r#TD-051"], "no entries read: no members"
    # `Parts:` is read from the record, never as a `Context:` ref out of the text (ledgerboard's stop list)
    assert CONTEXT.search(DESIGN).group(1) == "TD-050 decision (paul)."
    assert covered(line(parts=()), None) == ["r#TD-050"]
    for stop in ("Hide until: 2026-11-20.", "Lifts: Go.", "Answers: Go | Not yet."):
        assert covered(line(f"x. Context: TD-050. {stop}", parts=()), None) == ["r#TD-050"], stop
    # each once; a qualified ref is its own repo's; a member of an entry the line only lists in `Parts:` is not
    assert covered(line("x. Context: TD-050, TD-051.", parts=("TD-051",)), ENTRIES)[:2] == ["r#TD-050", "r#TD-051"]
    assert covered(line("x. Context: s#TD-001.", parts=()), ENTRIES) == ["s#TD-001"]
    assert covered(line("x. Context: TD-099.", parts=()), ENTRIES) == ["r#TD-099", "r#TD-056"]
    assert asked_entries([line()], ENTRIES) == set(covered(line(), ENTRIES))


@pytest.mark.unit
def test_the_line_is_one_item_on_the_parents_card_holding_the_rest_in_order():
    idx = index(("r#TD-050", [50, 51, 52, 53, 54]))
    got = item_home(line(), idx, entries=ENTRIES)
    assert (got["home"], got["on_card"], got["on_row"]) == ("queue", "r#TD-050", "r#TD-050")
    assert [h["show"] for h in got["holds"]] == ["TD-052", "TD-051", "TD-053", "TD-054"]
    assert got["mentions"] == [], "the line's own card names its parts in *holds*, never as a mention"
    one = got["holds"][0]
    assert one == {"id": "r#TD-052", "show": "TD-052", "href": "#r#TD-052", "repo_href": "/repo/r#TD-052",
                   "drawn": True}  # fmt: skip
    # the same line with no `Parts:` covers the parent's `decision (paul)` members by `Part of` the same way
    bare = item_home(line(parts=()), idx, entries=ENTRIES)
    assert [h["show"] for h in bare["holds"]] == ["TD-051", "TD-052", "TD-053", "TD-054"]


@pytest.mark.unit
def test_a_line_whose_parent_is_on_no_open_card_is_drawn_on_its_first_parts_card():
    idx = index(("r#TD-051", [51, 52]))
    got = item_home(line(), idx, entries=ENTRIES)
    assert got["on_card"] == "r#TD-051" and got["on_row"] == "r#TD-052", "the first it covers that a card holds"
    assert [h["show"] for h in got["holds"]] == ["TD-050", "TD-051", "TD-053", "TD-054"]
    assert [h["drawn"] for h in got["holds"]] == [False, True, False, False]
    assert got["holds"][0]["href"] == "/repo/r#TD-050", "a row the page does not draw links the Repo page"


@pytest.mark.unit
def test_a_covered_entry_on_another_card_is_a_mention_and_draws_no_block():
    idx = index(("r#TD-050", [50, 51, 52]), ("r#TD-099", [53, 99]))
    home = item_home(line(), idx, entries=ENTRIES)
    assert home["mentions"] == ["r#TD-053"] and "r#TD-053" in [h["id"] for h in home["holds"]]
    placed = {**line(), **home}
    later = [ledger_row(n, "r#TD-050") for n in (50, 51, 52)] + [ledger_row(53, "r#TD-099"), ledger_row(99, "r#TD-099")]
    got = attach({"needs": [placed]}, drawn, later)
    assert [m["html"] for m in got["cards"]["r#TD-050"]["needs"]] == ["board:k1"], "one item, no covered block"
    assert [m["html"] for m in got["cards"]["r#TD-099"]["needs"]] == ["ledger:r:TD-099"], "stripped on the other card"
    words = "**One more round?** Context: TD-050 decision (paul). Parts:"
    assert list(got["mentioned"]["r#TD-053"].values()) == [words]
    # a line not yet due names its covered rows on other cards as a due one does
    coming = attach({}, drawn, [*later, {**placed, "later_section": "coming"}])
    assert "r#TD-053" in coming["mentioned"]
    assert [m["html"] for m in coming["cards"]["r#TD-099"]["needs"]] == ["ledger:r:TD-099"]
    assert [m["html"] for m in coming["cards"]["r#TD-050"]["needs"]] == ["board:k1"]


@pytest.mark.unit
def test_with_you_and_answered_items_stand_and_an_entrys_own_line_is_a_second_item():
    idx = index(("r#TD-050", [50, 51, 52]))
    placed = {**line(), **item_home(line(), idx, entries=ENTRIES)}
    later = [ledger_row(51, "r#TD-050"), ledger_row(52, "r#TD-050", answered={"asker": "g"})]
    with_you = lambda c, item: {"name": "ao-paul"} if "051" in item else None  # noqa: E731
    mine = attach({"needs": [placed]}, drawn, later, None, with_you)
    got = mine["cards"]["r#TD-050"]["needs"]
    assert [(m["html"], m["want"]) for m in got] == [
        ("ledger:r:TD-051", "with_you"),
        ("ledger:r:TD-052", "answered"),
        ("board:k1", "decide"),
    ]
    # an entry another open undecided line names in its own right keeps that line as its own item, and is still held
    own = line("**Go or not yet?** Context: TD-051 decision (paul).", parts=(), id="board:/r:4", key="board:k2")
    own_home = item_home(own, idx, entries=ENTRIES)
    two = attach({"needs": [placed, {**own, **own_home}]}, drawn, [ledger_row(51, "r#TD-050")])
    assert [m["html"] for m in two["cards"]["r#TD-050"]["needs"]] == ["board:k1", "board:k2"]
    assert "r#TD-051" in [h["id"] for h in placed["holds"]]


@pytest.mark.unit
def test_later_leaves_out_a_covered_member_and_the_inboxs_own_row_draws_its_holds_line():
    lf = {"n": 3, "groups": [{"repo": "r", "rows": [ledger_row(n) for n in (53, 55, 56)]}]}
    lf, ahead, moved, _ = split_later(lf, [], {}, [], [line()], ENTRIES)
    assert [r["id"] for g in lf["groups"] for r in g["rows"]] == ["TD-055", "TD-056"], "TD-053 is a held member"
    lf2 = {"n": 0, "groups": []}
    _, ahead, _, _ = split_later(lf2, [line(due_now=False)], {}, [], [], ENTRIES)
    assert [h["show"] for h in ahead[0]["holds"]] == ["TD-050", "TD-052", "TD-051", "TD-053", "TD-054"]
    assert "holds" not in item_home(line(), None, entries=ENTRIES), "a snoozed line draws none"
    assert [h["id"] for h in item_home(line(), {}, entries=ENTRIES)["holds"]][:1] == ["r#TD-050"], "no Queue: all"


@pytest.mark.unit
def test_the_holds_line_is_drawn_after_the_body_and_links_each_row():
    idx = index(("r#TD-050", [50, 51]))
    e = {**line(), **item_home(line(), idx, entries=ENTRIES), "card": {"sentence": "One more round?", "leads": ""}}
    html = card(e, "decide")
    holds = re.search(r'<div class="st holds"[^>]*>(.*?)</div>', html, re.S).group(1)
    assert re.findall(r'href="([^"]+)" data-repo-href="([^"]+)">([^<]+)<', holds) == [
        ("/repo/r#TD-052", "/repo/r#TD-052", "TD-052"),
        ("#r#TD-051", "/repo/r#TD-051", "TD-051"),
        ("/repo/r#TD-053", "/repo/r#TD-053", "TD-053"),
        ("/repo/r#TD-054", "/repo/r#TD-054", "TD-054"),
    ]
    assert html.index("One more round?") < html.index('class="st holds"')
    # the Inbox's own row of a line no card holds: each id the Repo page's
    row = {**line(), **item_home(line(), {}, entries=ENTRIES), "lead": "One more round?", "due_tag": "", "replies": []}
    page = inbox(row)
    assert 'href="/repo/r#TD-050" data-repo-href="/repo/r#TD-050">TD-050</a>' in page
    assert 'class="st holds"' not in inbox({**row, "holds": []}), "a line that holds nothing else draws none"


def test_a_holds_press_whose_card_a_pick_hides_goes_to_the_repo_page():
    js = (Path(__file__).parents[1] / "src/shiftlead/ui/static/app.js").read_text()
    at = js.index('closest("a.holdsref[data-repo-href]")')
    near = js[at : at + 400]
    assert 'closest(".qoff")' in near and "location.href = hl.dataset.repoHref" in near


# ---- the Repo page's For you over a fake home ----


def _client(tmp_path, monkeypatch, *, due: bool = True):
    """Repo `r`: design TD-050 and its parts TD-051, TD-052 and TD-053 each held on `decision (paul)`, and one
    open `decide` line whose `Context:` names TD-050 and whose `Parts:` lists TD-051 and TD-052."""
    from test_ui_queue import client

    root = tmp_path / "r"
    (root / "docs").mkdir(parents=True)
    board = root / "docs" / "user_attention.md"
    board.write_text("# board\n")

    def held(n: int, title: str, part_of: str = "") -> dict:
        return {"for_page": "for-you", "priority": "medium", "id": f"TD-{n:03d}", "title": title,
                "blocked_by": ["decision (paul)"], "answers": ["Lift", "Keep"], "default": 0,
                **({"part_of": part_of} if part_of else {})}  # fmt: skip

    entries = [held(50, "the design"), held(51, "build one", "TD-050"), held(52, "build two", "TD-050"),
               held(53, "build three", "TD-050")]  # fmt: skip
    when = NOW.date() if due else NOW.date() + timedelta(days=7)
    text = (f"decide 2026-11-01 — **One more round on TD-050?** Context: TD-050 decision (paul). "
            f"Parts: TD-051, TD-052. Due: {when.isoformat()}.")  # fmt: skip
    item = {"line": 3, "text": text, "kind": "decide", "decided": None, "due": when.isoformat(),
            "answers": ["Go", "Not yet"], "default": "Go", "refs": ["TD-050"], "parts": ["TD-051", "TD-052"],
            "key": "board:abc12345",
            **({"overdue_days": 0, "due_tag": "due today"} if due else {"due_tag": "due in 7d"})}  # fmt: skip
    repos = {
        str(root): {
            "name": "r",
            "root": str(root),
            "ledger": {"path": "docs/technical_debt.md", "entries": entries},
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
def test_the_repo_pages_for_you_draws_the_line_once_and_the_covered_rows_plain(tmp_path, monkeypatch, due):
    html = _client(tmp_path, monkeypatch, due=due).get("/repo/r").text
    assert html.count('data-copy="board:abc12345"') == 1, "the line is drawn once"
    holds = re.search(r'<div class="st holds"[^>]*>(.*?)</div>', html, re.S).group(1)
    assert re.findall(r">(TD-\d+)</a>", holds) == ["TD-051", "TD-052", "TD-053"]
    assert html.count('class="brow"') == 1, "the line's row alone draws more than the column's plain row"
    assert 'data-answer="Keep"' not in html, "no covered row draws its own answers"
    assert "Lift the hold" not in html, "nor its Lift the hold: each is the column's plain row"
    for title in ("build one", "build two", "build three"):
        assert title in html, f"{title} stays in For you as its plain row"
