"""TD-915, design §4.5 screen 12 *A card*, *Three wants*; §4.5a *Queue page: card*: each Queue card its own box
with a 4 px left edge in the card's colour — amber for a Decide or Do item, else teal Waiting, else green In
progress, else grey — its rows' tree drawn, a 2 px rule per level in its branch's colour, and a row's mentions one
phrase, *mentioned in n items*, counted by item."""

import re
from datetime import UTC, datetime
from pathlib import Path

from markupsafe import Markup

from shiftlead.ui.queue import attach, branch, card_edge, queue_view

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
CSS = Path(__file__).resolve().parents[1] / "src/shiftlead/ui/static/app.css"


def row(n: int, **kw) -> dict:
    return {"qid": f"s#TD-{n}", "id": f"TD-{n}", "repo": "s", "title": f"entry {n}", "priority": "Medium", **kw}


def queue(group: str = "up_next") -> dict:
    """One card, TD-1, its tree: TD-2 (done) over TD-4 (waits), TD-3 (open) over TD-5 (the person's)."""
    rows = [
        row(2, parent="s#TD-1", depth=1, archived=True, state="done #9"),
        row(4, parent="s#TD-2", depth=2, state="waits until 2026-10-30"),
        row(3, parent="s#TD-1", depth=1, state="ready"),
        row(5, parent="s#TD-3", depth=2, needs="owner"),
    ]
    order = ["s#TD-1", *(r["qid"] for r in rows)]
    card = {"id": "s#TD-1", "group": group, "status": "ready", "top": row(1), "rows": rows, "order": order}
    return {"at": NOW.isoformat(), "cards": [card]}


def item(id: str, sec: str = "fyi", **e) -> dict:
    return {"id": id, "home": "queue", "on_card": "s#TD-1", "on_row": "s#TD-1", **e}


def test_the_edge_is_amber_for_a_want_then_teal_waiting_then_green_in_progress_then_grey():
    want = {"n": {"decide": 1, "do": 0}}
    do = {"n": {"decide": 0, "do": 2}}
    none = {"n": {"decide": 0, "do": 0, "read": 3}}  # Read never colours the card
    for group in ("waiting", "in_progress", "up_next"):
        assert card_edge(group, "ready", want) == card_edge(group, "ready", do) == "needs"
    assert card_edge("waiting", "waiting", none) == "waiting"
    assert card_edge("in_progress", "ready", none) == "working"
    assert card_edge("up_next", "ready", none) == card_edge("up_next", "blocked", {}) == "ended"
    assert card_edge("up_next", "needs you", {}) == "needs"  # the ledger's own need
    # the view carries it, from the mail's wants
    secs = {"needs": [item("a1", kind="ask")]}
    v = queue_view(queue("waiting"), NOW, attach(secs, lambda e, sec: Markup("")))
    assert v["waiting"][0]["edge"] == "needs"
    assert queue_view(queue("waiting"), NOW, {"cards": {}, "mentioned": {}})["waiting"][0]["edge"] == "waiting"


def test_each_row_carries_its_ancestors_branches_then_its_own():
    assert branch({"archived": True, "needs": "owner"}) == "done"
    assert branch({"needs": "owner"}) == branch({"needs": "decision"}) == "needs"
    for state in ("waits until 2026-10-30", "waits on an event", "waiting", "settling"):
        assert branch({"state": state}) == "waiting"
    for state in ("ready", "in review #4", "held by w", ""):
        assert branch({"state": state}) == "open"
    rows = queue_view(queue(), NOW)["up_next"][0]["rows"]
    assert [(r["id"], r["rails"]) for r in rows] == [
        ("TD-2", ["done"]),
        ("TD-4", ["done", "waiting"]),
        ("TD-3", ["open"]),
        ("TD-5", ["open", "needs"]),
    ]


def test_the_rows_are_drawn_depth_first_each_under_its_own_parent():
    # the reading's rows are breadth first: both level-1 rows, then both level-2 rows
    q = queue()
    rows = q["cards"][0]["rows"]
    q["cards"][0]["rows"] = [rows[0], rows[2], rows[1], rows[3]]
    got = queue_view(q, NOW)["up_next"][0]["rows"]
    assert [r["id"] for r in got] == ["TD-2", "TD-4", "TD-3", "TD-5"]
    # a row whose parent is not on the card is a loose row after the top entry's parts: no rule (TD-1131)
    q["cards"][0]["rows"] = [row(9, parent="s#TD-99", depth=2, state="ready"), *rows]
    got = queue_view(q, NOW)["up_next"][0]["rows"]
    assert [r["id"] for r in got] == ["TD-2", "TD-4", "TD-3", "TD-5", "TD-9"] and got[-1]["rails"] == [""]
    assert (got[-1]["depth"], got[-1]["meter"]) == (1, None)


def test_the_card_draws_its_edge_and_its_rails():
    from shiftlead.ui.app import templates

    c = queue_view(queue("in_progress"), NOW)["in_progress"][0]
    html = str(templates.env.get_template("queue_card.html").module.card(c))
    assert 'class="qcard edge-working g-in_progress' in html
    td4 = html[html.index('data-qid="s#TD-4"') :]
    rails = re.findall(r'class="qrail b-(\w+)" style="--ql: (\d)"', td4[: td4.index("</div>")])
    assert rails == [("done", "1"), ("waiting", "2")]


def test_one_item_mentioning_a_row_twice_counts_once():
    from shiftlead.ui.app import templates

    # one item drawn under two sections and naming TD-3 twice, another naming it once: two items
    secs = {
        "needs": [item("m1", subject="first <one>", mentions=["s#TD-3", "s#TD-3"])],
        "fyi": [
            item("m1", subject="first <one>", mentions=["s#TD-3"]),
            item("m2", subject="second", mentions=["s#TD-3"]),
        ],
    }
    got = attach(secs, lambda e, sec: Markup(""))
    assert got["mentioned"] == {"s#TD-3": {"m1": "first <one>", "m2": "second"}}
    c = queue_view(queue(), NOW, got)["up_next"][0]
    html = str(templates.env.get_template("queue_card.html").module.card(c))
    assert html.count("qmention") == 1
    assert '<div class="qnote qmention" title="first &lt;one&gt;\nsecond">mentioned in 2 items</div>' in html
    assert "also mentioned" not in html


def test_the_colours_are_tokens_in_both_themes():
    css = CSS.read_text()
    rules = [line for line in css.splitlines() if re.match(r"\s*\.(qrail|qcard\.edge-)", line)]
    rules += [line for line in css.splitlines() if ".qcards:not(.bcards) >" in line]
    assert len(rules) >= 5
    for line in rules:
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", line), line  # no literal colour: a token, so each theme's
    used = set(re.findall(r"var\(--(needs|waiting|working|ended|done)\)", "\n".join(rules)))
    assert used == {"needs", "waiting", "working", "ended", "done"}
    # the box is the Queue page's alone, and outranks the older `.qcard` border rules; the Repo page's board keeps
    # its one-column box (`bcards`)
    box = next(line for line in css.splitlines() if line.startswith(".qcards:not(.bcards) > .qcard"))
    assert "border-left: 4px solid var(--qedge" in box and "border-radius: 6px" in box
    repo = (CSS.parents[1] / "templates/repo_part.html").read_text()
    assert 'class="qcards bcards"' in repo
    root = css[css.index(":root {") : css.index("}", css.index(":root {"))]
    for token in used:
        assert f"--{token}:" in root


def test_a_card_not_landed_carries_the_flushs_refusal_on_its_note():
    """TD-1242, design §4.4 *A move lands*: the *not landed — retrying* note's hover is the flush's refusal,
    escaped."""
    from shiftlead.ui.app import templates

    q = queue()
    q["cards"][0]["not_landed"] = 'origin refused the push (GH007: <a> & "b"): the edit was not made'
    c = queue_view(q, NOW)["up_next"][0]
    html = str(templates.env.get_template("queue_card.html").module.card(c))
    note = 'title="origin refused the push (GH007: &lt;a&gt; &amp; &#34;b&#34;): the edit was not made">'
    assert f'<div class="qnote" {note}not landed — retrying</div>' in html
