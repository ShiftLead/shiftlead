"""TD-1131, design §4.4 *Rows*, §4.5 screen 12 *A card*, §4.5a *Queue page: card*; ADR 2026-10-27 §3: a Queue
card draws its parts on a spine — indented by *part of* alone, a 2 px rule for parts and none for a loose row —
each open blocker *after TD-n*, a link that rings its row, finished parts folded to *✓ n done* first on the
parent's spine, finished loose rows to one line at the card's end, and the parts meter on every parent row and on
the header."""

import re
from datetime import UTC, datetime
from pathlib import Path

from shiftlead.ui.queue import meter, queue_view

NOW = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)
JS = Path(__file__).resolve().parents[1] / "src/shiftlead/ui/static/app.js"


def row(n: int, parent: int | None = None, **kw) -> dict:
    return {
        "qid": f"s#TD-{n}",
        "id": f"TD-{n}",
        "repo": "s",
        "title": f"entry {n}",
        "priority": "Medium",
        "parent": f"s#TD-{parent}" if parent else None,
        "after": [],
        **kw,
    }


def done(n: int, parent: int | None = None, pr: int = 0) -> dict:
    return row(n, parent, archived=True, state=f"done #{pr or n}")


def td748() -> dict:
    """TD-748's card as the reading draws it: its parts (three done, TD-772 waiting); TD-909, a loose parent with
    a done part of a part (TD-911 under TD-915), an amber part, one in review and two after TD-772; an archived
    parent TD-800 with an open part; TD-122 loose after TD-772; TD-121 a finished loose row."""
    rows = [
        done(769, 748),
        done(770, 748),
        done(771, 748),
        row(772, 748, state="waits until 2026-10-30"),
        row(909, state="waiting"),
        done(915, 909),
        done(911, 915),
        row(916, 909, state="waiting", after=["s#TD-772"]),
        row(917, 909, needs="owner"),
        row(918, 909, state="in review #2178", pr=2178),
        done(800),
        row(801, 800, state="ready"),
        row(122, state="waiting", after=["s#TD-772"]),
        done(121, pr=288),
    ]
    order = ["s#TD-748", *(r["qid"] for r in rows if not r.get("archived"))]
    card = {"id": "s#TD-748", "group": "waiting", "status": "waiting", "top": row(748, state="waiting"),
            "rows": rows, "order": order}  # fmt: skip
    return {"at": NOW.isoformat(), "cards": [card]}


def lines(c: dict) -> list[tuple]:
    """The card's lines as (id or `fold n`, depth, rails)."""
    return [
        (f"fold {ln['n']}" + (" loose" if ln["loose"] else ""), ln["depth"], ln["rails"])
        if "fold" in ln
        else (ln["row"]["id"], ln["row"]["depth"], ln["row"]["rails"])
        for ln in c["lines"]
    ]


def test_parts_hang_on_the_spine_finished_parts_fold_first_and_loose_rows_draw_no_rule():
    c = queue_view(td748(), NOW)["waiting"][0]
    assert lines(c) == [
        ("fold 3", 1, ["done"]),  # TD-748's finished parts, first, directly under the header
        ("TD-772", 1, ["waiting"]),
        ("TD-909", 1, [""]),  # a loose parent: at the left edge, no rule
        ("fold 2", 2, ["", "done"]),  # a done part of a part folds with its parent's line
        ("TD-916", 2, ["", "waiting"]),
        ("TD-917", 2, ["", "needs"]),
        ("TD-918", 2, ["", "open"]),
        ("TD-800", 1, [""]),  # an archived parent with an open part: a done group head, never folded
        ("TD-801", 2, ["", "open"]),
        ("TD-122", 1, [""]),
        ("fold 1 loose", 1, []),  # finished loose rows: one line at the card's end, unindented
    ]
    fold = c["lines"][3]["fold"]
    assert [(r["id"], r["depth"], r["rails"]) for r in fold] == [
        ("TD-915", 2, ["", "done"]),
        ("TD-911", 3, ["", "done", "done"]),
    ]
    assert [r["id"] for r in c["lines"][0]["fold"]] == ["TD-769", "TD-770", "TD-771"]
    # every row stays in `rows`, the fold's too, for the counts, kinds and find text
    assert len(c["rows"]) == 14 and c["find"].count("entry 121")


def test_the_parts_meter_is_on_every_parent_and_the_header():
    c = queue_view(td748(), NOW)["waiting"][0]
    assert c["top"]["meter"] == {
        "segs": [
            {"b": "done", "title": "TD-769: done #769"},
            {"b": "done", "title": "TD-770: done #770"},
            {"b": "done", "title": "TD-771: done #771"},
            {"b": "waiting", "title": "TD-772: waits until 2026-10-30"},
        ],
        "d": 3,
        "n": 4,
    }
    by = {r["id"]: r for r in c["rows"]}
    m = by["TD-909"]["meter"]
    # amber for the person's part alone; *in review* is grey and keeps its word in the title
    assert [s["b"] for s in m["segs"]] == ["done", "waiting", "needs", "open"] and (m["d"], m["n"]) == (1, 4)
    assert m["segs"][2]["title"] == "TD-917: yours to do" and m["segs"][3]["title"] == "TD-918: in review #2178"
    assert by["TD-915"]["meter"]["n"] == 1 and by["TD-800"]["meter"] == {
        "segs": [{"b": "open", "title": "TD-801: ready"}],
        "d": 0,
        "n": 1,
    }
    assert by["TD-772"]["meter"] is None and by["TD-122"]["meter"] is None and meter([]) is None


def test_a_card_with_no_parent_draws_no_meter_and_no_spine():
    q = {"at": NOW.isoformat(), "cards": [{"id": "s#TD-1", "group": "up_next", "status": "blocked", "top": row(1),
         "rows": [row(2, after=["s#TD-1"], state="waiting"), done(3)], "order": ["s#TD-1", "s#TD-2"]}]}  # fmt: skip
    c = queue_view(q, NOW)["up_next"][0]
    assert c["top"]["meter"] is None
    assert lines(c) == [("TD-2", 1, [""]), ("fold 1 loose", 1, [])]


def test_the_card_draws_the_spine_the_fold_the_meter_and_after_links():
    from shiftlead.ui.app import templates

    c = queue_view(td748(), NOW)["waiting"][0]
    html = str(templates.env.get_template("queue_card.html").module.card(c))
    head = html[: html.index('class="qrows"')]
    assert '<span class="qmeter" role="img" aria-label="3 of 4 parts done">' in head and ">3/4</span>" in head
    body = html[html.index('class="qrows"') :]
    # the fold is first on the spine, before TD-772, and holds its rows
    assert body.index('<details class="qfold">') < body.index('data-qid="s#TD-769"') < body.index('data-qid="s#TD-772"')
    assert re.search(r'<span class="qtick" aria-hidden="true">✓</span> 3 done</summary>', body)
    assert body.count('<details class="qfold loose">') == 1
    assert body.rindex('<details class="qfold loose">') > body.index('data-qid="s#TD-122"')
    # a loose row draws no rule; a part its own and its ancestors'
    td909 = body[body.index('data-qid="s#TD-909"') :]
    assert "qrail" not in td909[: td909.index("</div>")]
    td916 = body[body.index('data-qid="s#TD-916"') :]
    assert re.findall(r'class="qrail b-(\w+)" style="--ql: (\d)"', td916[: td916.index("</div>")]) == [("waiting", "2")]
    # *after TD-772*: a link that scrolls to and rings the row (the page's `a.qon` press)
    assert 'after <a class="qon" href="#TD-772" data-on="TD-772"' in td916[: td916.index("</div>")]
    assert "also after" not in html
    assert 'aria-label="1 of 4 parts done"' in td909[: td909.index("</div>")]


def test_after_lights_the_row_it_names_on_hover_or_focus():
    js = JS.read_text()
    assert ".qafter a.qon[data-on]" in js and '"focusin", lit(true)' in js and '"mouseover", lit(true)' in js


def test_a_cycle_of_archived_parts_is_drawn_once_never_lost():
    q = {"at": NOW.isoformat(), "cards": [{"id": "s#TD-1", "group": "up_next", "status": "ready", "top": row(1),
         "rows": [done(2, 3), done(3, 2), row(4, state="ready")], "order": ["s#TD-1", "s#TD-4"]}]}  # fmt: skip
    c = queue_view(q, NOW)["up_next"][0]
    assert sorted(r["id"] for r in c["rows"]) == ["TD-2", "TD-3", "TD-4"]
