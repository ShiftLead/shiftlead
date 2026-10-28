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


def test_the_rows_render_as_the_design_draws_them():
    """§4.5a *Sessions: rollup* and *rollup: press and menus*: a table row each, its first cell the link
    named for what it goes to; a second team's repo, bar and open cells blank; *could not look* dimmed with
    the error its hover; the blocks by state and a stopped team's stubs and word; the needs-you number solid
    while an answer is needed (the row's amber edge), its menu's lines and URLs; each ⋯ item; one legend."""
    needs = [_ask("m-1", "g1", minutes=30), _ask("m-2", "g3", minutes=10)]
    _, ro = _page(_fleet(), needs)
    html = ui.templates.get_template("rollup.html").render(ro=ro, person_needs=0)
    rows = html.split('<tr class="ru-row')[1:]
    assert len(rows) == 6 and html.count('class="legend"') == 1
    grind, review, design, strip, quiet, norepo = rows
    assert ' ru-attn"' in grind.split(">")[0] and ' ru-attn"' not in review.split(">")[0]
    assert 'aria-label="samscrape · grind"' in grind and '<span class="ru-rp">samscrape</span>' in grind
    assert 'aria-label="samscrape · review"' in review and '<span class="ru-rp' not in review
    assert 'class="bar"' not in review and '<td class="ru-open ru-r"></td>' in review
    assert 'href="#team=grind"' in grind and 'href="#strip=samscrape"' in strip and 'href="#norepo"' in norepo
    assert '<span class="meta ru-dim" title="git: not a repository">could not look</span>' in quiet
    assert grind.count('<i class="s-') == 3 and "<b>1</b> of 3" in grind
    assert design.count('class="ru-stub"') == 4 and "wound down 3h ago" in design and " of " not in design
    # the needs-you number and its menu: *answer needed* to the facet, *asked you* to the Inbox, a line a member
    assert '<button type="button" class="ru-c ru-ans"' in grind and ">3</button>" in grind
    assert 'href="#tsum-grind" data-open-team="grind"' in grind
    assert 'href="/inbox?team=grind&amp;sec=needs&amp;kind=questions"' in grind
    assert 'href="/inbox?row=m-1"' in grind and 'href="/inbox?row=m-2"' in grind
    assert 'href="#card-n1" data-open-card="n1"' in norepo and "asked you" not in norepo
    # the ⋯ items: the card's own acts by their buttons, the links, Add entry… by the repo
    assert 'data-addentry="samscrape"' in grind and 'href="/new?team=grind"' in grind
    assert 'data-press="stop" data-team="grind"' in grind and 'data-press="stopnow" data-team="grind"' in grind
    assert design.index('data-press="start"') < design.index("data-addentry") and 'data-press="stop"' not in design
    assert 'href="/new?dir=/r/quiet"' in quiet and "data-addentry" not in quiet
    assert 'data-menu="acts"' not in norepo and 'data-menu="needs"' not in review


def test_a_rows_hash_is_url_encoded_as_the_client_reads_it():
    """The link's `#team=…` / `#repo=…` / `#strip=…` names its item encoded, so the client's `decodeURIComponent`
    reads back the layout's key whatever the name holds (review of #2623)."""
    team = {"kind": "team", "key": "team:a b%c", "team": "a b%c", "repo": "", "members": [], "summary": {}}
    repo = {"kind": "repo", "key": "repo:x y", "repo": "x y", "url": "/repo/x y", "facet": None}
    rows = ui.rollup_rows([team, repo], set())
    assert [r["hash"] for r in rows] == ["team=a%20b%25c", "repo=x%20y"]
