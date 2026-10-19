"""The Sessions page grouped **project → repo → team** (design §4.9 *The Sessions page*, §4.5a *team groups*,
*team card: Repo facet*, TD-725): headings in the org file's order, a repo's line carrying the Repo
facet once, its teams' cards in order, a no-team strip per repo, and *No repo* last."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from shiftlead import org as orgmod

APP = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui" / "static" / "app.js"


def reading(name: str) -> dict:
    """A repo's reading as the home gives it, the few keys the Repo facet reads."""
    return {
        "name": name,
        "root": f"/r/{name}",
        "remote": f"git@github.com:eye/{name}.git",
        "ledger": {"entries": [], "by_priority": {"high": 1}, "by_kind": {"pickable": 1}},
        "prs": {"open": []},
        "at": "2026-10-16T10:00:00Z",
    }


def sess(sid: str, *, team: str = "", repo: str = "", state: str = "idle", **kw) -> dict:
    """A session view, only the keys grouping and the card read."""
    return {
        "id": sid,
        "name": sid,
        "team": team or None,
        "repo": repo,
        "state": state,
        "state_class": state,
        "state_label": state,
        "pill_word": state,
        "scraped": False,
        "rank": 5,
        "controllers": [],
        "capabilities": [],
        "unattended": True,
        "host": "kmaster",
        "place": f"kmaster / {Path(repo).name}" if repo else "kmaster / x",
        "slot": {},
        **kw,
    }


def row(name: str, repo: str) -> dict:
    """A definition's row as `teamrun.rows` gives it: the keys `team_groups` reads."""
    return {"name": name, "repo": repo, "project": repo, "manager": "person", "members": 1, "roles": []}


def project(name: str, *repos: str, title: str = "") -> orgmod.Project:
    return orgmod.Project(name, {r: {} for r in repos}, title=title)


def layout(views, rows=(), repos=(), projects=()):
    from shiftlead.ui.app import org_layout, team_groups

    readings = {f"/r/{n}": reading(n) for n in repos}
    return org_layout(team_groups(list(views), list(rows), readings, {}), readings, list(projects), list(views))


def shape(items) -> list[str]:
    """The page's order as words: `head:` a project heading, `repo:` a repo's line (`*` where it is the
    heading), `team:` a team card, `strip:` a repo's no-team strip, `norepo` *No repo*."""
    out = []
    for it in items:
        if it["kind"] == "repo":
            out.append(it["key"] + ("*" if it["heading"] else ""))
        else:
            out.append(it["key"])
    return out


def page(items) -> str:
    from shiftlead.ui.app import templates

    sessions = [m for it in items for m in it.get("members") or []]
    return templates.get_template("org.html").render(
        sessions=sessions,
        groups=items,
        counts=dict.fromkeys(("needs-you", "limited", "stalled?"), 0),
        strip={"teams": [], "source": "", "notes": []},
        host="kmaster",
        active="Sessions",
        agent_down=False,
        volatile=False,
        usage={},
    )


def test_two_teams_on_one_repo_are_two_cards_under_one_line_and_the_repo_facet_is_drawn_once(tmp_path, monkeypatch):
    """§4.9: two teams on one repo are two whole cards under one repo line, and the Repo facet is the
    line's — drawn once, never on a team card; its lanes *i* is one line per team."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    views = [
        sess("a1", team="alpha", repo="/r/shiftlead", state="working"),
        sess("b1", team="beta", repo="/r/shiftlead", state="working"),
    ]
    items = layout(views, [row("alpha", "shiftlead"), row("beta", "shiftlead")], ["shiftlead"])
    assert shape(items) == ["repo:shiftlead*", "team:alpha", "team:beta"]
    html = page(items)
    assert html.count('class="facet frepo"') == 1
    line = html[html.index('class="rline') : html.index('<section class="tgroup" data-team="alpha"')]
    assert 'class="facet frepo"' in line and 'href="/repo/shiftlead"' in line
    for team in ("alpha", "beta"):
        sec = html[html.index(f'<section class="tgroup" data-team="{team}"') :]
        assert "frepo" not in sec[: sec.index("</section>")]


def test_a_project_of_two_repos_is_one_heading_with_its_title_and_one_of_one_repo_is_the_repos_line(
    tmp_path, monkeypatch
):
    """§4.9: a project heading carries its `title` over its repos in its list's order; a project of one
    repo draws one heading, the repo's line."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    views = [sess("w1", team="web", repo="/r/web"), sess("a1", team="api", repo="/r/api")]
    projects = [project("guardians", "web", "api", title="Guardians"), project("solo", "tools")]
    rows = [row("api", "api"), row("web", "web"), row("t", "tools")]
    items = layout(views, rows, ["api", "web", "tools"], projects)
    assert shape(items) == ["head:guardians", "repo:web", "team:web", "repo:api", "team:api", "repo:tools*", "team:t"]
    head = items[0]
    assert head["label"] == "Guardians" and head["repos"] == ["web", "api"]
    html = page(items)
    assert '<span class="h1">Guardians</span>' in html and html.count('class="phead"') == 1
    assert ">solo<" not in html  # one repo: no heading of the project's own


def test_headings_follow_the_org_files_order_and_a_live_team_precedes_a_stopped_one(tmp_path, monkeypatch):
    """§4.9: the headings in the org file's order, then the repos no project lists in the registry's
    order; within a repo the live and concluded first, then those with nothing live, each in
    definition order."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    views = [
        sess("s1", team="first", repo="/r/zeta", state="exited"),  # defined first, nothing live
        sess("l1", team="second", repo="/r/zeta", state="working"),
        sess("l2", team="third", repo="/r/zeta", state="working"),
    ]
    rows = [row("first", "zeta"), row("second", "zeta"), row("third", "zeta")]
    items = layout(views, rows, ["loose", "alpha", "zeta"], [project("p", "zeta", "alpha")])
    assert shape(items) == [
        "head:p",
        "repo:zeta",
        "team:second",
        "team:third",
        "team:first",
        "repo:alpha",
        "repo:loose*",  # in no project: its own heading, after the projects, in the registry's order
    ]
    assert items[-1]["project"] == ""  # no project's key, so a project named `loose` could not claim its line


def test_a_registered_repo_with_no_team_draws_its_line_and_facet(tmp_path, monkeypatch):
    """§4.9: a registered repo with no team is drawn, its line and its Repo facet alone."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    items = layout([sess("t1", team="t", repo="/r/main")], [row("t", "main")], ["main", "quiet"])
    assert shape(items) == ["repo:main*", "team:t", "repo:quiet*"]
    assert items[-1]["facet"] and items[-1]["facet"]["name"] == "quiet"
    html = page(items)
    assert html.count('class="facet frepo"') == 2


def test_a_session_with_no_team_sits_in_its_repos_strip_or_under_no_repo(tmp_path, monkeypatch):
    """§4.9: a repo's sessions with no team badge are its no-team strip, headed *n sessions, no team*
    and nothing else; a session in no registered repo is under *No repo*, last."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    views = [
        sess("t1", team="t", repo="/r/main"),
        sess("mine", repo="/r/main", unattended=False),
        sess("mine2", repo="/r/main", unattended=False),
        sess("scratch", repo=""),
    ]
    items = layout(views, [row("t", "main")], ["main"])
    assert shape(items) == ["repo:main*", "team:t", "strip:main", "norepo"]
    strip, none = items[-2], items[-1]
    assert strip["label"] == "2 sessions, no team" and strip["ids"] == ["mine", "mine2"]
    assert none["label"] == "No repo" and none["ids"] == ["scratch"]
    html = page(items)
    sec = html[html.index('data-key="strip:main"') :]
    head = sec[: sec.index('<div class="grid">')]
    assert '<span class="meta">2 sessions, no team</span>' in head and 'class="h2"' not in head
    assert '<section class="tgroup" data-team="" data-key="norepo"' in html  # a section: `g` then a digit counts it
    assert html.index('data-key="strip:main"') < html.index('data-key="norepo"')


def test_an_undefined_badges_group_sits_under_the_repo_its_records_are_in(tmp_path, monkeypatch):
    """§4.9: a team's repo is its definition's `repo:`, never where its members sit; a badge no
    definition holds is drawn under the repo its records sit in."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    views = [
        sess("d1", team="defined", repo="/r/other"),  # its members elsewhere: the definition says `main`
        sess("o1", team="orphan", repo="/r/other"),
    ]
    items = layout(views, [row("defined", "main")], ["main", "other"])
    assert shape(items) == ["repo:main*", "team:defined", "repo:other*", "team:orphan"]


def test_the_ring_runs_repo_line_then_team_cards_then_the_strip(tmp_path, monkeypatch):
    """§4.5a *Sessions: keys*: under a repo the ring runs its line, the team cards, the no-team strip's
    cards — the page's own order, the line a stop of its own."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    views = [sess("t1", team="t", repo="/r/main"), sess("mine", repo="/r/main", unattended=False)]
    html = page(layout(views, [row("t", "main")], ["main"]))
    line = re.search(r'<div class="rline[^"]*"[^>]*>', html).group(0)
    assert 'tabindex="0"' in line
    assert html.index('class="rline') < html.index('id="card-t1"') < html.index('id="card-mine"')
    assert '"#groups .rline, #groups .sc,' in APP.read_text()  # the ring's selector: the line a stop


def test_the_flat_page_and_the_delta_carry_the_layout(tmp_path, monkeypatch):
    """No badge and no definition: the flat page, no headings. A delta carries each heading and line
    whole, with its key, and each section with its key, repo and project."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import org_layout, render_heads, team_groups

    assert org_layout(team_groups([sess("x", repo="/r/main")]), {}, ()) is None
    views = [sess("t1", team="t", repo="/r/main"), sess("mine", repo="/r/main")]
    heads = render_heads(layout(views, [row("t", "main")], ["main"]))
    assert [(h["kind"], h["key"]) for h in heads] == [
        ("repo", "repo:main"),
        ("team", "team:t"),
        ("strip", "strip:main"),
    ]
    assert 'data-key="repo:main"' in heads[0]["html"] and heads[0]["team"] == ""
    assert heads[1]["repo"] == "main" and heads[1]["team"] == "t" and heads[2]["ids"] == ["mine"]


# The Org functions under node over the fake DOM of test_ui_org_plus.py: a delta places a heading
# and a repo line in the server's order, and the filter hides a line and its heading when nothing
# under them shows, and shows them again with the first match.
PROBE_TAIL = r"""
const filter = body.appendChild(new El("input", { id: "filter" })); filter.value = "";
["count", "empty", "badges"].forEach((id) => body.appendChild(new El("div", { id })));
const groups = body.appendChild(new El("div", { id: "groups" }));
const card = (id, team) => Object.assign(new El("div", { id: `card-${id}`, class: "card sc", "data-id": id,
  "data-name": id, "data-rank": 5, "data-state": "idle", "data-team": team }), { textContent: id });
const mk = (team, key) => {
  const s = groups.appendChild(new El("section", { class: "tgroup", "data-team": team, "data-key": key }));
  s.appendChild(new El("div", { class: "grid" })); return s;
};
mk("a", "team:a").querySelector(".grid").appendChild(card("a1", "a"));
mk("b", "team:b").querySelector(".grid").appendChild(card("b1", "b"));
const H = '<div class="phead" data-key="head:p" data-project="p"><span class="h1">P</span></div>';
const L = (r) => `<div class="rline" data-key="repo:${r}" data-repo="${r}" data-project="p" tabindex="0">`
  + '<div class="row"></div></div>';
AO.orgSyncGroups([
  { kind: "heading", key: "head:p", team: "", html: H },
  { kind: "repo", key: "repo:one", team: "", html: L("one") },
  { kind: "team", key: "team:a", team: "a", repo: "one", project: "p", manager: "", ids: ["a1"], html: "" },
  { kind: "repo", key: "repo:two", team: "", html: L("two") },
  { kind: "team", key: "team:b", team: "b", repo: "two", project: "p", manager: "", ids: ["b1"], html: "" },
]);
const order = () => groups.children.map((e) => e.dataset.key);
const hidden = () => groups.children.filter((e) => e.hidden).map((e) => e.dataset.key);
const out = { order: order() };
filter.value = "a1"; AO.orgLayout(); out.a1 = hidden();
filter.value = "nothing"; AO.orgLayout(); out.none = hidden();
filter.value = ""; AO.orgLayout(); out.cleared = hidden();
// a second delta: repo two goes, its team with it; nothing is left behind
AO.orgSyncGroups([
  { kind: "heading", key: "head:p", team: "", html: H },
  { kind: "repo", key: "repo:one", team: "", html: L("one") },
  { kind: "team", key: "team:a", team: "a", repo: "one", project: "p", manager: "", ids: ["a1"], html: "" },
]);
out.after = order();
console.log(JSON.stringify(out));
"""


@pytest.mark.unit
def test_the_client_places_headings_and_lines_and_hides_them_under_a_filter(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    import importlib.util

    spec = importlib.util.spec_from_file_location("plus_probe", pathlib.Path(__file__).with_name("test_ui_org_plus.py"))
    plus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plus)
    PROBE = plus.PROBE  # noqa: N806 — the fake DOM, shared
    head = PROBE[: PROBE.index("// the page: the filter box")]
    probe = tmp_path / "layout_probe.js"
    probe.write_text(head + PROBE_TAIL)
    run = subprocess.run([node, str(probe), str(APP)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["order"] == ["head:p", "repo:one", "team:a", "repo:two", "team:b"]
    assert got["a1"] == ["repo:two", "team:b"]  # repo two's line hides with its only team; the heading stays
    assert got["none"] == ["head:p", "repo:one", "team:a", "repo:two", "team:b"]
    assert got["cleared"] == []
    assert got["after"] == ["head:p", "repo:one", "team:a"]
