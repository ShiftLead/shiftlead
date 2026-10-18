# ruff: noqa: E501 — the fixture rows read as one line each
"""TD-740, design §4.5 screen 11 *The page is the repo's group of the Org, expanded*: the Repo page
draws the repo's line with its Repo facet once, every servicing team's whole card by the Org's own
partial, and its no-team strip; the cards take the Org's deltas; Doing carries a chip per team where
two or more service the repo; and Add entry's **Team** pick hands to that team's techlead seat."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from test_ui_entry import client as entry_client
from test_ui_entry import fake as entry_fake
from test_ui_entry import world
from test_ui_org_plus import PROBE as ORG_PROBE
from test_ui_repo_page import NOW, _iso, client, fake, reading, rec

pytestmark = pytest.mark.unit

APP = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui" / "static" / "app.js"


def top(html: str) -> str:
    """The page's cards: the Org's items of the repo, above the lists."""
    return html[html.index('id="groups"') : html.index('id="repolists"')]


def two_teams(root: str) -> list[dict]:
    return [
        rec("grind-1", root),
        rec("grind-2", root, state="idle"),
        rec("db-1", root, team="db"),
        rec("loose-1", root, team=""),  # a session of the repo in no team: the no-team strip
    ]


def test_a_repo_two_teams_service_draws_both_teams_whole_cards_and_the_repo_facet_once(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    html = client(monkeypatch, tmp_path, fake({root: reading(root)}, two_teams(root))).get("/repo/samscrape").text
    t = top(html)
    assert t.count('class="facet frepo"') == 1 and t.index('data-key="repo:samscrape"') < t.index('data-key="team:')
    for team, ids in (("db", ["db-1"]), ("grind", ["grind-1", "grind-2"])):
        sec = t[t.index(f'data-key="team:{team}"') :]
        sec = sec[: sec.index("</section>")]
        assert 'class="row gap wrap ghead"' in sec and "TDs in motion" in sec  # its header and its facets
        assert re.findall(r'id="card-([\w-]+)"', sec) == ids  # its member cards, by the Org's partial
    strip = t[t.index('data-key="strip:samscrape"') :]
    assert 'id="card-loose-1"' in strip  # the repo's sessions with no team, after the teams
    assert "serviced by" in html and ">db</a>" in html and ">grind</a>" in html


def test_a_repo_no_team_services_draws_its_line_and_facet_alone_with_the_lists(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    html = client(monkeypatch, tmp_path, fake({root: reading(root)}, [])).get("/repo/samscrape").text
    t = top(html)
    assert 'data-key="repo:samscrape"' in t and t.count('class="facet frepo"') == 1
    assert "<section" not in t and 'class="sc' not in t  # no team card, no session
    assert all(f'id="{s}"' in html for s in ("prs", "debt", "completed", "waiting", "doing"))
    assert "no team services this repo" in html
    part = client(monkeypatch, tmp_path, fake({root: reading(root)}, [])).get("/repo/samscrape?part=1").text
    assert 'id="groups"' not in part and 'id="prs"' in part  # the poll re-reads the lists, never the cards


def test_the_doing_chips_carry_a_team_chip_per_team_where_two_serve_and_none_where_one_does(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    t0 = _iso(NOW)
    doing = {
        "grind": [{"id": "grind-1", "text": "pushing", "at": t0}, {"id": "grind-2", "text": "reading", "at": t0}],
        "db": [{"id": "db-1", "text": "migrating", "at": _iso(NOW.replace(year=NOW.year + 1))}],
    }
    html = (
        client(monkeypatch, tmp_path, fake({root: reading(root)}, two_teams(root), doing)).get("/repo/samscrape").text
    )
    sec = html[html.index('id="doing"') :]
    chips = re.findall(r'<button type="button" class="chip" data-(team|who)="([^"]*)"[^>]*>([^<]*)</button>', sec)
    assert chips == [("team", "db", "db (1)"), ("team", "grind", "grind (2)"), ("who", "", "all (3)"),
                     ("who", "db-1", "db-1 (1)"), ("who", "grind-1", "grind-1 (1)"), ("who", "grind-2", "grind-2 (1)")]  # fmt: skip
    rows = re.findall(r'class="rrow drow" data-who="([\w-]+)" data-team="(\w+)"', sec)
    assert rows[0] == ("db-1", "db") and sorted(rows[1:]) == [
        ("grind-1", "grind"),
        ("grind-2", "grind"),
    ]  # newest first
    one = [r for r in two_teams(root) if r["team"] != "db"]
    html = client(monkeypatch, tmp_path, fake({root: reading(root)}, one, doing)).get("/repo/samscrape").text
    sec = html[html.index('id="doing"') :]
    assert 'data-team="grind" aria-pressed' not in sec and 'data-who="" aria-pressed="true">all (2)' in sec


def test_the_waiting_on_you_heading_links_the_inbox_filtered_to_the_repos_board(tmp_path, monkeypatch):
    root = str(tmp_path / "samscrape")
    html = client(monkeypatch, tmp_path, fake({root: reading(root)}, two_teams(root))).get("/repo/samscrape").text
    sec = html[html.index('id="waiting"') :]
    assert (
        '<a class="h2" href="/inbox?repo=samscrape&amp;kind=board"' in sec
        or '<a class="h2" href="/inbox?repo=samscrape&kind=board"' in sec
    )


def two_team_world(tmp_path):
    import yaml

    repo = world(tmp_path)
    doc = yaml.safe_load((tmp_path / "home" / "org.yml").read_text())
    doc["teams"]["sam-db"] = {
        "repo": "samscrape",
        "manager": {"name": "manager-db"},
        "techlead": {"name": "techlead-db"},
        "members": [{"role": "grinder", "name": "db-grinder"}],
    }
    (tmp_path / "home" / "org.yml").write_text(yaml.safe_dump(doc, sort_keys=False))  # definition order kept
    return repo


def test_the_team_pick_hands_to_the_picked_teams_seat_and_blank_to_the_first(tmp_path, monkeypatch):
    two_team_world(tmp_path)
    handed: list[dict] = []
    c = entry_client(monkeypatch, tmp_path, entry_fake([], handed=handed))
    plan = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt"}).json()
    assert [t["team"] for t in plan["teams"]] == ["sam-grind", "sam-db"] and plan["picked"] == ""
    assert plan["hand"]["name"] == "techlead-sam"  # blank: the first with a seat
    picked = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt", "team": "sam-db"}).json()
    assert picked["picked"] == "sam-db" and picked["hand"]["name"] == "techlead-db"  # the form names the seat
    body = {"repo": "samscrape", "type": "debt", "words": "a slow query"}
    assert c.post("/api/entry/hand", json={**body, "team": "sam-db"}).json()["text"].startswith("handed to techlead-db")
    assert c.post("/api/entry/hand", json=body).json()["text"].startswith("handed to techlead-sam")
    assert [kw["teams"][0]["team"] for kw in handed] == ["sam-db", "sam-grind"]
    # a name no team of the repo has is no pick: the first, as blank
    other = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt", "team": "nobody"}).json()
    assert other["picked"] == "" and other["hand"]["name"] == "techlead-sam"


def test_the_form_draws_the_team_pick_hidden_and_sends_it():
    base = (APP.parent.parent / "templates" / "base.html").read_text()
    assert '<label class="row gap" id="entryteamrow" hidden>' in base and 'id="entryteam"' in base
    js = APP.read_text()
    assert "draft: draft(), team: picked() })" in js  # the hand carries the pick
    assert '$("#entryteamrow").hidden = ts.length < 2' in js  # drawn where two or more teams service the repo


# the Repo page's top under node, by the Org's own delta code: a card of the repo is redrawn, a card of
# another repo is never put in, and a team of another repo in the delta's groups is not drawn
REPO_PROBE = (
    ORG_PROBE[: ORG_PROBE.index("// the page: the filter box")]
    + r"""
El.prototype.replaceWith = function (n) {
  const p = this.parentElement; if (n.parentElement) n.remove();
  p.children[p.children.indexOf(this)] = n; n.parentElement = p; this.parentElement = null;
};
const groups = body.appendChild(new El("div", { id: "groups" }));
const tpl = (html) => { const t = document.createElement("template"); t.innerHTML = html; return t.content.firstElementChild; };
groups.appendChild(tpl('<div class="rline" data-key="repo:r" data-repo="r"></div>'));
const sec = groups.appendChild(new El("section", { class: "tgroup", "data-team": "t", "data-key": "team:t", "data-repo": "r" }));
const grid = sec.appendChild(new El("div", { class: "grid" }));
grid.appendChild(tpl('<div id="card-a" class="card sc" data-id="a" data-name="alpha" data-rank="2" data-state="working"></div>'));
const gs = (ids) => [
  { kind: "repo", key: "repo:r", team: "", html: '<div class="rline" data-key="repo:r" data-repo="r"></div>' },
  { kind: "team", key: "team:t", team: "t", repo: "r", manager: "", live: 1, ids, html: "", summary: "", plus: "", lanes: {} },
  { kind: "team", key: "team:u", team: "u", repo: "other", manager: "", live: 1, ids: ["z"], html: "", summary: "", plus: "", lanes: {} },
];
const card = (id, state) => `<div id="card-${id}" class="card sc" data-id="${id}" data-name="${id}" data-rank="1" data-state="${state}"></div>`;
const out = {};
AO.orgGroupsEvent({ event: "session", id: "a", html: card("a", "idle"), groups: gs(["a"]) }, "r");
out.redrawn = groups.querySelector("#card-a").dataset.state;
out.teams = groups.querySelectorAll(".tgroup").map((s) => s.dataset.key);
AO.orgGroupsEvent({ event: "session", id: "z", html: card("z", "working"), groups: gs(["a"]) }, "r");
out.other = !!groups.querySelector("#card-z");
AO.orgGroupsEvent({ event: "session", id: "b", html: card("b", "working"), groups: gs(["a", "b"]) }, "r");
out.added = groups.querySelector(".tgroup .grid").children.map((c) => c.dataset.id);
AO.orgGroupsEvent({ event: "groups", groups: gs(["b"]) }, "r");
out.left = groups.querySelectorAll(".sc").map((c) => c.dataset.id);
AO.orgGroupsEvent({ event: "groups", groups: null }, "r");
out.flat = groups.querySelectorAll(".sc").map((c) => c.dataset.id);
// the repo's line alone, then a first session of the repo with no team: its strip is made and the card put in it
AO.orgGroupsEvent({ event: "groups", groups: gs([]).slice(0, 1) }, "r");
out.line_alone = [groups.querySelectorAll(".tgroup").length, groups.querySelectorAll(".sc").length];
const strip = { kind: "strip", key: "strip:r", team: "", repo: "r", manager: "", live: 1, ids: ["s"], html: "", summary: "", plus: "", lanes: {} };
AO.orgGroupsEvent({ event: "session", id: "s", html: card("s", "idle"), groups: [...gs([]).slice(0, 1), strip] }, "r");
out.strip = groups.querySelectorAll(".tgroup").map((x) => [x.dataset.key, x.querySelector(".grid").children.map((c) => c.dataset.id)]);
console.log(JSON.stringify(out));
"""
)


def test_a_delta_on_a_member_redraws_its_card_on_the_repo_page_as_on_the_org(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = tmp_path / "repo_probe.js"
    probe.write_text(REPO_PROBE)
    run = subprocess.run([node, str(probe), str(APP)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == {
        "redrawn": "idle",  # the member's delta swapped its card
        "teams": ["team:t"],  # the delta's team of another repo is not drawn here
        "other": False,  # …nor its card put in
        "added": ["a", "b"],  # a new member of the repo's team is placed, sorted as on the Org
        "left": ["b"],  # a card no item lists now is another repo's: it leaves
        "flat": ["b"],  # the flat page's `null` names no repo: what was drawn stays
        "line_alone": [0, 0],
        "strip": [["strip:r", ["s"]]],  # with no grid on the page, the new card still lands in its strip
    }


def test_the_re_read_carries_the_title_line_and_the_seams_and_never_the_cards(tmp_path, monkeypatch):
    """Review of TD-740: *serviced by* and the missing seams are re-read with the lists, as before."""
    root = str(tmp_path / "samscrape")
    part = (
        client(monkeypatch, tmp_path, fake({root: reading(root)}, two_teams(root))).get("/repo/samscrape?part=1").text
    )
    assert part.count('id="repohead"') == 1 and "serviced by" in part and 'id="groups"' not in part
    page = client(monkeypatch, tmp_path, fake({root: reading(root)}, two_teams(root))).get("/repo/samscrape").text
    assert page.count('id="repohead"') == 1 and page.index('id="repohead"') < page.index('id="groups"')


# -- TD-764: *needs a team*, the stale-team notes, and the hand's `entry.team` ------------------------


def test_the_debt_heading_says_what_needs_a_team_and_what_is_stale_and_the_row_is_marked(tmp_path, monkeypatch):
    """§4.5 screen 11 *Technical debt*, §4.4 *An entry names its team* (TD-764): under the lanes lines,
    the repo's *needs a team* line as `ao repo` prints it, and a note for a declared name no definition
    holds (with the entries that carry it) and for a defined team the ledger leaves out; the row of an
    entry that needs a team says so after its owner."""
    two_team_world(tmp_path)
    root = str(tmp_path / "samscrape")
    r = reading(root)
    r["ledger"]["declared_teams"] = ["sam-grind", "db-old"]
    r["ledger"]["entries"] += [
        {"id": "TD-320", "title": "untagged", "for_page": "pickable", "priority": "medium", "owner": "grinder", "needs_team": {"why": "untagged"}},
        {"id": "TD-321", "title": "the old team's", "for_page": "pickable", "priority": "low", "owner": "grinder", "team": "db-old", "needs_team": {"why": "unknown"}},
    ]  # fmt: skip
    seat = rec(
        "techlead-sam", root, team="sam-grind", state="idle", role="techlead", seat={"trigger": "asks", "tags": True}
    )
    html = client(monkeypatch, tmp_path, fake({root: r}, [seat])).get("/repo/samscrape?open=pickable").text
    debt = html[html.index('<section class="rsec" id="debt">') : html.index('id="completed"')]
    head = debt[: debt.index('class="rlist"')]
    assert 'needs a team: <a href="#TD-320">TD-320</a>, <a href="#TD-321">TD-321</a> — handed to techlead-sam' in head
    assert 'the ledger declares db-old, which no definition holds: <a href="#TD-321">TD-321</a>' in head
    assert "the ledger leaves out sam-db, which this repo defines" in head
    assert "the ledger leaves out sam-grind" not in head

    def row(tid: str) -> str:
        return re.search(rf'id="{tid}".*?(?=class="rrow|</section>)', debt, re.S).group(0)

    assert row("TD-320").index("· grinder</span>") < row("TD-320").index("· needs a team</span>")
    assert "needs a team</span>" not in row("TD-301")
    # nobody to hand them to: why, in `ao repo`'s words; a ledger that declares no teams has nothing stale
    r["ledger"]["declared_teams"] = []
    html = client(monkeypatch, tmp_path, fake({root: r}, [])).get("/repo/samscrape").text
    head = html[html.index('<section class="rsec" id="debt">') :]
    head = head[: head.index('class="rlist"')]
    assert "— no techlead seat to tag them</div>" in head
    assert "the ledger leaves out sam-db" in head and "the ledger leaves out sam-grind" in head
    # a reading with no `Team` vocabulary read (an older home) draws neither
    del r["ledger"]["declared_teams"]
    html = client(monkeypatch, tmp_path, fake({root: r}, [])).get("/repo/samscrape?open=pickable").text
    assert 'class="meta teamnote' not in html and "· needs a team</span>" in html


def test_the_hand_carries_the_pick_as_entry_team_and_a_blank_one_takes_the_ledgers_order(tmp_path, monkeypatch):
    """§4.10 *An entry handed to a seat* (TD-764): the hand sends the form's Team pick as `team`, empty
    when blank; blank, the first team with a seat in the ledger's `Team` order takes it — here sam-db,
    though sam-grind is defined first."""
    repo = two_team_world(tmp_path)
    handed: list[dict] = []
    Base = entry_fake([], handed=handed)

    class Fake(Base):
        async def call(self, method, **kw):
            if method == "repos":
                return {
                    str(repo): {
                        "name": "samscrape",
                        "root": str(repo),
                        "ledger": {"declared_teams": ["sam-db", "sam-grind"]},
                    }
                }
            return await super().call(method, **kw)

    c = entry_client(monkeypatch, tmp_path, Fake)
    plan = c.get("/api/entry/plan", params={"repo": "samscrape", "type": "debt"}).json()
    assert [t["team"] for t in plan["teams"]] == ["sam-db", "sam-grind"] and plan["hand"]["name"] == "techlead-db"
    body = {"repo": "samscrape", "type": "debt", "words": "a slow query"}
    assert c.post("/api/entry/hand", json=body).json()["text"].startswith("handed to techlead-db")
    assert (
        c.post("/api/entry/hand", json={**body, "team": "sam-grind"})
        .json()["text"]
        .startswith("handed to techlead-sam")
    )
    assert [(kw["teams"][0]["team"], kw["team"]) for kw in handed] == [("sam-db", ""), ("sam-grind", "sam-grind")]
