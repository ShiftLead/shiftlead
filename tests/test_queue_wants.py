"""TD-911, design §4.5 screen 12 *Three wants*, *A card*; §4.5a *Queue page: card*, *Queue card: Read n*: what
is attached to a card is gathered into Decide and Do — in the header, amber, counted on the pill — and Read, under
the rows, folded with its count; a held entry is no want; the page header counts Decide and Do in items."""

from datetime import UTC, datetime

from markupsafe import Markup

from shiftlead.ui.queue import attach, card_wants, queue_view, want_of

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)


def queue() -> dict:
    """Two Up next cards in one repo: TD-1 alone, and TD-2 with its row TD-3."""

    def row(n: int, **kw) -> dict:
        return {"qid": f"s#TD-{n}", "id": f"TD-{n}", "repo": "s", "title": f"entry {n}", "priority": "Medium", **kw}

    return {
        "at": NOW.isoformat(),
        "cards": [
            {"id": "s#TD-1", "group": "up_next", "status": "ready", "top": row(1), "rows": [], "order": ["s#TD-1"]},
            {"id": "s#TD-2", "group": "up_next", "status": "ready", "top": row(2), "rows": [row(3, depth=1)],
             "order": ["s#TD-2", "s#TD-3"]},
        ],
    }  # fmt: skip


def item(sec: str, on_row: str, **e) -> dict:
    return {"id": e.pop("id", "x"), "home": "queue", "on_card": e.pop("card", "s#TD-2"), "on_row": on_row, **e}


def test_each_kind_lands_in_its_want():
    assert want_of({"kind": "ask"}, "needs") == "decide"
    assert want_of({"kind": "steer"}, "needs") == "decide"  # a paused steer
    assert want_of({"kind": "steer"}, "steering") == "decide"  # a running one
    for kind in ("decide", "look", ""):
        assert want_of({"row": "board", "kind": kind}, "needs") == "decide"
    assert want_of({"row": "board", "kind": "act"}, "needs") == "do"  # TD-1066: Done its answer
    assert want_of({"row": "board", "kind": "watch"}, "needs") == "read"
    assert want_of({"row": "ledger", "why": "decision"}, "needs") == "decide"  # held until
    assert want_of({"row": "ledger", "why": "yours"}, "needs") == "do"  # yours to do
    assert want_of({"row": "ledger", "why": "yours", "release": True}, "needs") == "held"  # no want while held
    assert want_of({"row": "red_pr"}, "needs") == "do"
    for sec in ("answered", "waiting", "fyi"):
        assert want_of({"kind": "ask"}, sec) == "read"


def test_the_counts_are_items_and_a_running_steer_leaves_the_status_steer():
    secs = {
        "needs": [item("needs", "s#TD-3", id="a1", kind="ask"), item("needs", "s#TD-2", id="r1", row="red_pr")],
        "steering": [item("steering", "s#TD-1", id="s1", kind="steer", card="s#TD-1")],
        "answered": [item("answered", "s#TD-2", id="n1"), item("answered", "s#TD-2", id="n2")],
        "fyi": [item("fyi", "s#TD-3", id="f1")],
    }
    # a `watch` line due: Read, on fyi's line, though the Inbox draws it under Needs you
    secs["needs"].append(item("needs", "s#TD-2", id="b1", row="board", kind="watch"))
    got = attach(secs, lambda e, sec: Markup(f"<{e['id']}>"))
    v = queue_view(queue(), NOW, got)
    one, two = v["up_next"]
    assert one["status"] == "steer" and one["wants"]["n"] == {"decide": 1, "do": 0, "read": 0}
    assert two["status"] == "needs you" and two["wants"]["n"] == {"decide": 1, "do": 1, "read": 4}
    assert sorted(two["wants"]["read"]) == ["answered", "fyi"] and two["wants"]["read"]["fyi"][1]["on"] == "TD-3"
    assert [m["id"] for m in two["wants"]["read"]["fyi"]] == ["b1", "f1"]
    # the page header: items, not cards; a red PR on its card's pill alone; the needs-you number unchanged
    assert (v["n"]["decide"], v["n"]["do"], v["n"]["needs_you"]) == (2, 0, 1)


def test_the_page_headers_decide_counts_items_on_a_card_with_two():
    """TD-920: a card with a question and a paused steer, and one with a running steer alone, read Decide 3 — the
    cards with any Decide item would read 2."""
    secs = {
        "needs": [item("needs", "s#TD-3", id="a1", kind="ask"), item("needs", "s#TD-2", id="p1", kind="steer")],
        "steering": [item("steering", "s#TD-1", id="s1", kind="steer", card="s#TD-1")],
    }
    v = queue_view(queue(), NOW, attach(secs, lambda e, sec: Markup(f"<{e['id']}>")))
    one, two = v["up_next"]
    assert one["wants"]["n"]["decide"] == 1 and two["wants"]["n"]["decide"] == 2
    assert v["n"]["decide"] == 3


def test_a_held_entry_is_no_want_and_draws_the_held_row():
    later = [
        {"row": "ledger", "id": "TD-3", "row_id": "ledger:s:TD-3", "why": "yours", "release": True,
         "kind": "ledger · yours", "answers": ["a"], "home": "queue", "on_card": "s#TD-2", "on_row": "s#TD-3",
         "later_section": "later"},
    ]  # fmt: skip
    drawn = []
    got = attach({}, lambda e, sec: drawn.append(e) or Markup("<held>"), later)
    v = queue_view(queue(), NOW, got)
    two = v["up_next"][1]
    assert two["status"] == "ready" and two["wants"]["n"] == {"decide": 0, "do": 0, "read": 0}
    assert len(two["wants"]["held"]) == 1
    assert drawn[0]["kind"] == "ledger · held" and drawn[0]["claimed"] and drawn[0]["answers"] == []


def test_a_card_draws_decide_and_do_in_its_header_and_read_folded_under_its_rows():
    from shiftlead.ui.app import templates

    secs = {
        "needs": [item("needs", "s#TD-2", id="a1", kind="ask"),
                  item("needs", "s#TD-2", id="y1", row="ledger", why="yours", row_id="y1")],
        "waiting": [item("waiting", "s#TD-2", id="w1")],
        "fyi": [item("fyi", "s#TD-2", id="f1")],
    }  # fmt: skip
    v = queue_view(queue(), NOW, attach(secs, lambda e, sec: Markup(f'<div class="mailrow">{e["id"]}</div>')))
    html = templates.env.get_template("queue_card.html").module.card(v["up_next"][1])
    head, body = html.split('<div class="qrows">')
    assert "Decide (1)" in head and "Do (1)" in head and ">Decide 1 · Do 1</span>" in head
    assert ">Read 2</span>" in head  # *Read n*, which the page shows on a folded card alone
    assert "waiting on them (1)" in body and "fyi (1)" in body and "answered for you" not in body
    # Dismiss all on fyi's line alone; waiting on them has none
    assert body.count(">Dismiss all</button>") == 1
    assert body.index('data-sec="fyi"') < body.index(">Dismiss all</button>")
    assert 'class="qcard edge-needs g-up_next st-needs-you wants hasrows"' in html


def test_a_card_with_nothing_attached_draws_no_want():
    v = queue_view(queue(), NOW, {"cards": {}, "mentioned": {}})
    assert all(c["wants"] == card_wants(None, c["top"]["qid"], True) for c in v["up_next"])
    assert v["n"]["decide"] == v["n"]["do"] == 0
