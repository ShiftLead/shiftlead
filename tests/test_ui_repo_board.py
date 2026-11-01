# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-903, design §4.5 screen 11 *the board*: the Repo page by stage — For you, one column per worker stage of
the servicing teams' flows, Review, Merged — each entry placed by its page kind against the stages' lane
words, never by a stage's name; claimed rows first, queued by card, blocked folded; bounded."""

from __future__ import annotations

import pathlib

import pytest

from shiftlead.flowdefs import Stage
from shiftlead.ui import repo_board as rb

pytestmark = pytest.mark.unit

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
TD = [  # the `td` flow: design → build → review
    Stage("design", "designer", ["design-first", "owner:designer"]),
    Stage("build", "grinder", ["free-pick", "owner:grinder"]),
    Stage("review", "techlead"),
]
BUILD_REVIEW = [Stage("build", "grinder", ["free-pick", "owner:grinder"]), Stage("review", "techlead")]


def entry(tid: str, page: str = "pickable", owner: str = "grinder", **kw) -> dict:
    return {"id": tid, "title": f"entry {tid}", "for_page": page, "priority": "medium", "owner": owner, **kw}


def lists(*entries: dict) -> list[dict]:
    """`ledger_lists`' shape, one list per page kind, the rows in the order given."""
    keys = ("pickable", "design", "for-you", "live-check", "blocked", "evaluation", "other")
    return [{"key": k, "label": k, "rows": [e for e in entries if e["for_page"] == k]} for k in keys]


def ids(col: dict) -> list[str]:
    return [r["id"] for g in col["groups"] for r in g["rows"]]


def test_the_td_flow_draws_design_then_build_and_places_by_lane_words():
    cols, review = rb.columns([("grind", TD)])
    assert [c["name"] for c in cols] == ["Design", "Build"] and review == [("grind", "techlead")]
    assert rb.place(entry("TD-1", "design", "designer"), cols) == ("s1", "")
    assert rb.place(entry("TD-2"), cols) == ("s2", "")
    assert rb.place(entry("TD-3", "live-check"), cols) == ("s2", "")
    # placed by kind, never by a stage's name or the owner alone: a design entry owned by a grinder is Design's
    assert rb.place(entry("TD-4", "design", "grinder"), cols) == ("s1", "")
    # a blocked build waits at Build; a blocked design-first entry at Design
    assert rb.place(entry("TD-5", "blocked"), cols) == ("s2", "")
    assert rb.place(entry("TD-6", "blocked", kind="design-first"), cols) == ("s1", "")
    # no lane takes an evaluation or a flagged entry: For you's fold, with its flag's words
    assert rb.place(entry("TD-7", "evaluation", flag="in no lane"), cols) == ("", "in no lane")
    assert rb.place(entry("TD-8", "other", flag="fits no page kind"), cols) == ("", "fits no page kind")


def test_a_flow_with_one_worker_stage_has_no_design_column():
    cols, _ = rb.columns([("grind", BUILD_REVIEW)])
    assert [c["name"] for c in cols] == ["Build"]
    assert rb.place(entry("TD-1", "design", "designer"), cols) == ("", rb.NO_DESIGN)
    assert rb.place(entry("TD-2", "blocked", kind="design-first"), cols) == ("s1", "")  # waits where it can go


def test_two_teams_stages_join_equal_lanes_once_and_split_differing_ones():
    other = [Stage("build", "builder", ["free-pick", "owner:db"]), Stage("review", "techlead")]
    cols, review = rb.columns([("grind", TD), ("db", BUILD_REVIEW), ("dbgrind", other)])
    # grind's and db's build stages take the same lane words: one column, both teams' roles on it
    assert [c["name"] for c in cols] == ["Design", "Build", "Build · db"]
    assert cols[1]["roles"] == [("grind", "grinder"), ("db", "grinder")]
    assert review == [("grind", "techlead"), ("db", "techlead"), ("dbgrind", "techlead")]
    # among the stages taking free-pick, the first whose owner words take the entry's Owner, else the first
    assert rb.place(entry("TD-1", owner="db"), cols) == ("s3", "")
    assert rb.place(entry("TD-2", owner="anchor"), cols) == ("s2", "")


def test_no_team_or_no_usable_flow_draws_the_fixed_columns():
    for flows in ([], [("grind", None)]):
        cols, review = rb.columns(flows)
        assert [c["name"] for c in cols] == ["Design", "Build"] and cols[0]["fixed"] and review == []
    b = rb.board(None, lists(entry("TD-1")), [], [], "r")
    assert b["fixed"] and all(not c["people"] for c in b["stages"]) and b["review_people"] == []


def test_a_heading_names_who_is_on_the_stage_per_team_and_says_nobody_running():
    members = [
        {"id": "g1", "name": "grinder-ao-1", "team": "grind", "role": "grinder", "state": "idle", "out_of_work": {"why": "x"}},
        {"id": "g2", "name": "grinder-ao-2", "team": "grind", "role": "grinder", "state": "idle", "out_of_work": {"why": "y"}},
        {"id": "d1", "name": "designer-ao-1", "team": "grind", "role": "designer", "state": "working", "state_label": "working"},
        {"id": "t1", "name": "techlead-ao-1", "team": "grind", "role": "techlead", "state": "exited"},
    ]  # fmt: skip
    b = rb.board(None, lists(), [("grind", TD)], members, "r")
    design, build = b["stages"]
    assert design["people"] == [{"team": "grind", "text": "designer-ao-1 · working", "none": False}]
    assert build["people"] == [{"team": "grind", "text": "grinder-ao-1 · grinder-ao-2 · out of work", "none": False}]
    assert b["review_people"] == [{"team": "grind", "text": "no techlead running", "none": True}]


def card(cid: str, rows: list[dict], group: str = "up_next", places=()) -> dict:
    def row(e: dict) -> dict:
        return {"qid": f"r#{e['id']}", "id": e["id"], "show": e["id"], "anchor": e["id"], "ext": e, "title": e["title"]}

    return {"id": cid, "top": row(rows[0]), "rows": [row(e) for e in rows[1:]], "group": group,
            "ids": [f"r#{e['id']}" for e in rows], "places": [{"repo": r, "n": n} for r, n in places]}  # fmt: skip


def test_claimed_rows_first_then_queued_by_card_then_blocked_folded():
    held = entry("TD-9", held="grinder-ao-1")
    design, build = entry("TD-1", "design", "designer"), entry("TD-2")
    cards = {
        "cards": [
            card("r#TD-9", [held], group="in_progress"),
            card("r#TD-1", [design, build], places=[("r", 1)]),
            card("r#TD-3", [entry("TD-3"), entry("TD-4", "blocked")], places=[("r", 2)]),
            card("r#TD-5", [entry("TD-5", owner="paul", **{"for_page": "for-you"})], places=[("r", 3)]),
            card(
                "r#TD-6",
                [entry("TD-6", owner="paul", **{"for_page": "for-you", "kind": "decision"})],
                places=[("r", 4)],
            ),
        ],
        "upnext": ["r#TD-1", "r#TD-3", "r#TD-5", "r#TD-6"],
    }
    b = rb.board(cards, [], [("grind", TD)], [], "r", doing={"grinder-ao-1": "TD-9: reading the fetcher"})
    d, bu = b["stages"]
    assert [r["id"] for r in bu["claimed"]] == ["TD-9"] and bu["claimed"][0]["holders"] == ["grinder-ao-1"]
    assert bu["claimed"][0]["doing"] == "TD-9: reading the fetcher"
    # one card in two columns: its design row in Design and its build in Build, each group numbered 1
    assert ids(d) == ["TD-1"] and ids(bu) == ["TD-2", "TD-3"]
    assert [(g["card"], g["up"], g["place"]) for g in bu["groups"]] == [("r#TD-1", True, 1), ("r#TD-3", True, 2)]
    # blocked: counted, not sent until its fold is opened (or an anchor names a row in it)
    assert bu["n_blocked"] == 1 and bu["blocked"] == [] and bu["n"] == 4
    opened = rb.board(cards, [], [("grind", TD)], [], "r", ["TD-4"])
    assert [r["id"] for r in opened["stages"][1]["blocked"]] == ["TD-4"]
    # For you: what waits on the person — Owner: paul or decision (paul) — numbered and moved as a card
    assert ids(b["foryou"]) == ["TD-5", "TD-6"] and b["foryou"]["kinds"] == ["yours", "decide"]


def test_an_in_progress_cards_rows_carry_no_number_and_no_grip():
    cards = {"cards": [card("r#TD-1", [entry("TD-1", held="g1"), entry("TD-2")], group="in_progress")], "upnext": []}
    g = rb.board(cards, [], [("grind", TD)], [], "r")["stages"][1]["groups"][0]
    assert g["rows"][0]["id"] == "TD-2" and g["up"] is False and g["place"] is None


def test_a_column_sends_seven_queued_rows_and_the_rest_by_its_read():
    rows = [entry(f"TD-{n}") for n in range(1, 11)]
    cards = {"cards": [card(f"r#TD-{n}", [e]) for n, e in enumerate(rows, 1)], "upnext": []}
    col = rb.board(cards, [], [("grind", TD)], [], "r")["stages"][1]
    assert len(ids(col)) == rb.SHOWN == 7 and col["more"] == 3 and col["n"] == 10
    whole = rb.board(cards, [], [("grind", TD)], [], "r", ["s2:queued"])["stages"][1]
    assert len(ids(whole)) == 10 and whole["more"] == 0
    # a decided board line leads the pick's queued rows and takes one of the seven
    led = rb.board(cards, [], [("grind", TD)], [], "r", orders=[{"id": "board:ab12", "work_order": True}])["stages"][1]
    assert [o["id"] for o in led["orders"]] == ["board:ab12"] and len(ids(led)) == 6 and led["more"] == 4


def test_no_queue_reading_draws_the_ledgers_rows_unnumbered():
    b = rb.board(None, lists(entry("TD-2"), entry("TD-1", "design", "designer")), [("grind", TD)], [], "r")
    assert not b["numbered"] and ids(b["stages"][0]) == ["TD-1"] and ids(b["stages"][1]) == ["TD-2"]
    assert all(not g["up"] and g["place"] is None for c in b["stages"] for g in c["groups"])


def test_the_boards_row_and_the_queue_cards_row_are_one_partial():
    """§4.5 screen 11 *A row*: the board draws a ledger row by the Queue card's row partial, never a copy."""
    part = (UI / "templates" / "repo_part.html").read_text()
    card = (UI / "templates" / "queue_card.html").read_text()
    assert '{% from "queue_row.html" import row as qrow %}' in part
    assert '{% from "queue_row.html" import row,' in card
    assert 'class="qrow' not in part  # no row markup of its own
    assert "{{ qrow(r, name) }}" in part


def test_a_decided_line_with_no_pick_stage_waits_in_for_yous_fold():
    design_only = [Stage("design", "designer", ["design-first", "owner:designer"]), Stage("review", "techlead")]
    b = rb.board(None, lists(), [("grind", design_only)], [], "r", orders=[{"id": "board:ab12", "work_order": True}])
    assert [(r["id"], w) for r, w in b["fold"]] == [("board:ab12", "no lane takes it")]
