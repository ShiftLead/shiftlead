"""The Sessions rollup's rows (design §4.5a *Sessions: rollup*, *rollup: press and menus*; TD-1203, built by
TD-1204): a row per team and per repo with no team, in the page's order, the strips and *No repo* under them,
each row's cells, its needs-you split and its ⋯ acts — and the rows adding up to the totals."""

from __future__ import annotations

from datetime import timedelta

from test_ui_team_summary import NOW, PERM, _ask, _iso, _s, reading

from shiftlead.ui import app as ui

DEFS = [
    {"name": "grind", "repo": "samscrape", "manager": "person",
     "roles": [{"role": "grinder", "names": ["g1", "g2", "g3"]}]},
    {"name": "review", "repo": "samscrape", "manager": "person", "roles": [{"role": "reviewer", "names": ["r1"]}]},
    {
        "name": "design",
        "repo": "samscrape",
        "manager": "lead",
        "techlead": "tl",
        "roles": [{"role": "manager", "names": ["lead"]}, {"role": "designer", "names": ["d1", "d2"]}],
        "seats": [{"name": "tl", "role": "techlead"}],
        "wound_down": True,
        "wound_down_age": "3h",
    },
]  # fmt: skip


def _repos() -> dict:
    quiet = reading("/r/quiet", name="quiet", ledger={"error": "git: not a repository"})
    return {"/r/samscrape": reading("/r/samscrape"), "/r/quiet": quiet}


def _page(ms: list[dict], needs: list[dict] = ()) -> tuple[list[dict], dict]:
    repos = _repos()
    groups = ui.team_groups(ms, DEFS, repos, {}, needs=needs)
    layout = ui.org_layout(groups, repos, (), ms, NOW)
    return layout, ui.rollup(layout, ms)


def _fleet() -> list[dict]:
    return [
        _s("g1", "working"),
        _s("g2", "needs-you", rank=0, pending=PERM),
        _s("g3", "idle"),
        _s("r1", "waiting", team="review"),
        _s("d1", "exited", team="design"),  # a stopped team's leftover: not counted, no block
        _s("p1", "working", team="design", unattended=False),  # a person's own, in a stopped team
        _s("s1", "idle", team=""),  # samscrape's no-team strip
        _s("n1", "needs-you", team="", repo="/elsewhere", pending=PERM),  # *No repo*
    ]


def test_a_row_per_team_and_repo_in_the_pages_order_with_strips_and_no_repo_last():
    """§4.5a *Sessions: rollup* **Rows**: each team a row, in the page's order; a second team on one repo
    leaves the repo, debt and open cells blank; the repo's no-team strip a sub-row; a registered repo with
    no team a row reading *no team*; *No repo* last. The rows' keys and hashes are the layout's."""
    layout, ro = _page(_fleet())
    rows = ro["rows"]
    assert [r["key"] for r in rows] == [
        "team:grind",
        "team:review",
        "team:design",
        "strip:samscrape",
        "repo:quiet",
        "norepo",
    ]
    assert [r["name"] for r in rows] == [
        "samscrape · grind",
        "samscrape · review",
        "samscrape · design",
        "no team · 1 session",
        "quiet · no team",
        "No repo",
    ]
    assert [r["hash"] for r in rows] == [
        "team=grind",
        "team=review",
        "team=design",
        "strip=samscrape",
        "repo=quiet",
        "norepo",
    ]
    grind, review = rows[0], rows[1]
    assert grind["first"] and grind["repo_url"] == "/repo/samscrape"
    assert [s["key"] for s in grind["segs"]] == ["pickable", "design"] and grind["open"] == 2
    assert not review["first"] and review["segs"] == [] and review["open"] is None
    quiet = rows[4]
    assert quiet["error"] == "git: not a repository" and quiet["open"] is None and quiet["blocks"] == []


def test_a_rows_members_are_its_counted_cards_in_urgency_order_and_a_stopped_team_stubs_its_empty_seats():
    """**Members**: a block per counted card in the grid's urgency order, *w* the working ones; a stopped
    team draws its counted cards (a person's own live session among them), a stub per seat its definition
    names with no counted card — matched by name, never `person` — and its word."""
    _, ro = _page(_fleet())
    grind, _, design = ro["rows"][:3]
    assert [(b["id"], b["cls"]) for b in grind["blocks"]] == [("g2", "needs"), ("g1", "working"), ("g3", "idle")]
    assert grind["working"] == 1 and grind["stubs"] == [] and grind["word"] == ""
    assert [b["id"] for b in design["blocks"]] == ["p1"] and design["working"] == 1
    assert design["stubs"] == ["lead", "d1", "d2", "tl"]
    assert design["word"] == "wound down 3h ago"


def test_the_rows_add_up_to_the_totals():
    """**What is counted**: every count is over `rollup_counted`'s one set, so the rows' blocks add up to
    Agents' total and their needs-you numbers to *n from teams* — a strip's *answer needed* alone, a team's
    *answer needed* and *asked you* added (TD-924's rules)."""
    needs = [_ask("m-1", "g1", minutes=30), _ask("m-2", "g3", minutes=10), _ask("m-3", "g1", minutes=5)]
    _, ro = _page(_fleet(), needs)
    rows = ro["rows"]
    assert sum(len(r["blocks"]) for r in rows) == ro["n_agents"] == 7
    grind = rows[0]
    assert grind["answer"] == 1 and grind["asked"]["n"] == 3 and grind["needs"] == 4
    assert grind["asked"]["by"] == [
        {"member": "g1", "name": "g1", "n": 2, "id": "m-1"},
        {"member": "g3", "name": "g3", "n": 1, "id": "m-2"},
    ]
    norepo = rows[-1]
    assert norepo["needs"] == 1 and norepo["answer_card"] == "n1" and norepo["asked"] is None
    assert ro["n_from_teams"] == sum(r["needs"] for r in rows) == 5


def test_each_kind_of_rows_menu_holds_its_cards_acts():
    """**The ⋯ menu**: a live team Add entry… (only where its repo has a ledger reading), New session in it,
    Wind down, Stop now; a stopped team Start first; a repo with no team whose reading failed no Add entry…
    but New session here (its root from the registry); a strip New session here; *No repo* none."""
    _, ro = _page(_fleet())
    acts = {r["key"]: r["acts"] for r in ro["rows"]}
    assert acts["team:grind"] == ["add-entry", "new-team", "wind-down", "stop-now"]
    assert acts["team:review"] == ["add-entry", "new-team", "wind-down", "stop-now"]
    assert acts["team:design"] == ["start", "add-entry", "new-team"]
    assert acts["repo:quiet"] == ["new-here"]
    assert acts["strip:samscrape"] == ["new-here"] and acts["norepo"] == []
    roots = {r["key"]: r["root"] for r in ro["rows"]}
    assert roots["repo:quiet"] == "/r/quiet" and roots["strip:samscrape"] == "/r/samscrape"


def test_the_last_work_cell_is_the_teams_newest_doing_row():
    """**Last work**: the age and doer of the team's newest kept `ao doing` row, its words for the hover;
    blank on a team with none."""
    repos = _repos()
    ms = _fleet()
    doing = {
        "grind": [
            {"id": "g1", "at": _iso(NOW - timedelta(minutes=50)), "text": "older"},
            {"id": "g3", "at": _iso(NOW - timedelta(minutes=4)), "text": "TD-9: the fix"},
        ]
    }
    groups = ui.team_groups(ms, DEFS, repos, doing)
    rows = ui.rollup(ui.org_layout(groups, repos, (), ms, NOW), ms)["rows"]
    assert rows[0]["last"]["name"] == "g3" and rows[0]["last"]["text"] == "TD-9: the fix"
    assert rows[1]["last"] is None


def test_a_strip_is_drawn_only_with_a_counted_card_and_the_flat_page_has_no_rows():
    """A strip whose sessions all ended draws no row; the flat page (no layout) has no rows, its
    *n from teams* the *answer needed* over its sessions."""
    ms = [m for m in _fleet() if m["id"] != "s1"] + [_s("s2", "exited", team="")]
    _, ro = _page(ms)
    assert "strip:samscrape" not in [r["key"] for r in ro["rows"]]
    vs = [_s("a", "needs-you", team="", pending=PERM), _s("b", "working", team="")]
    flat = ui.rollup(None, vs)
    assert flat["rows"] == [] and flat["n_from_teams"] == 1 == flat["answer_needed"]
