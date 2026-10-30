"""The repo line's compact facet (design §4.9 *The Sessions page*, §4.5a *Sessions: repo line*, TD-1240, built
by TD-1248): two rows, Technical debt and Pull requests, with **Add entry…**, drawn by the Sessions page while
no team card of the repo shows the Repo facet; the line keeps the whole facet for the Repo page alone."""

from __future__ import annotations

import re

import pytest
from test_ui_org_layout import APP, page, reading, row, sess

pytestmark = pytest.mark.unit

CSS = APP.parent / "app.css"


def line_html(r: dict, tmp_path, monkeypatch) -> str:
    """The page from `r`'s line on, `r` a registered repo with no team beside a team's repo (a page with no
    team at all is the flat one, which draws no repo lines)."""
    from shiftlead.ui.app import org_layout, team_groups

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    readings = {"/r/main": reading("main"), r["root"]: r}
    views = [sess("t1", team="t", repo="/r/main")]
    items = org_layout(team_groups(views, [row("t", "main")], readings, {}), readings, [], views)
    html = page(items)
    return html[html.index(f'data-repo="{r["name"]}"') :]


def compact(html: str) -> str:
    return html[html.index('class="rcompact"') : html.index("</div>\n  </div>", html.index('class="rcompact"'))]


def test_the_compact_form_draws_two_rows_of_figures_and_add_entry(tmp_path, monkeypatch):
    r = reading("quiet")
    r["ledger"] = {"entries": [{}] * 4, "by_priority": {"high": 1, "low": 3}, "by_kind": {"pickable": 1}}
    r["prs"] = {
        "open": [
            {"number": 7, "created": "2026-10-16T08:00:00Z", "checks": "not_run", "not_run": {"reason": "no runner"}}
        ]
    }
    c = compact(line_html(r, tmp_path, monkeypatch))
    assert c.index("Technical debt") < c.index("Pull requests")
    assert "<b>4</b> open" in c and "1 high" in c and "3 low" in c and "medium" not in c  # a priority at 0 not drawn
    assert 'class="csw p-high"' in c and 'class="csw p-low"' in c
    assert '<button class="btn sm ghost" type="button" data-addentry="quiet"' in c
    assert "<b>1</b> open" in c and "1 CI never ran" in c and "#7 · no runner" in c and "oldest" in c and "read " in c
    assert 'href="/repo/quiet#debt"' in c and 'href="/repo/quiet#prs"' in c  # each figure a link to the Repo page
    # no bars, no legend, no selector, no window picker, no key of its own
    for gone in ('class="bar"', 'class="legend"', "data-pick", "data-team", 'class="seg"', "facet frepo"):
        assert gone not in c, gone


def test_a_failed_reading_reads_could_not_look_dimmed_with_its_error(tmp_path, monkeypatch):
    r = reading("broken")
    r["ledger"] = {"error": "no ledger here"}
    r["prs"] = {"error": "gh: not logged in"}
    c = compact(line_html(r, tmp_path, monkeypatch))
    assert c.count("could not look") == 2
    assert 'class="meta dim" title="no ledger here"' in c and 'class="meta dim" title="gh: not logged in"' in c


def test_the_line_keeps_the_whole_facet_beside_the_compact_one(tmp_path, monkeypatch):
    html = line_html(reading("quiet"), tmp_path, monkeypatch)
    line = html[: html.index("</div>\n</div>") + 12]
    assert 'class="tsum rsum" data-team="repo:quiet"' in line and 'class="facet frepo"' in line
    assert line.index('class="tsum rsum"') < line.index('class="rcompact"')


def test_each_page_shows_one_form_and_the_client_toggles_the_compact():
    css = CSS.read_text()
    assert re.search(r"#groups > \.rline \.tsum\.rsum \{[^}]*display: none;", css)  # hidden by default
    assert ".repopage #groups > .rline .tsum.rsum:not([hidden]) { display: flex; }" in css
    assert "#groups > .rline .rcompact[hidden], .repopage #groups > .rline .rcompact { display: none; }" in css
    js = APP.read_text()
    sync = js[js.index("function syncLineFacets()") :]
    sync = sync[: sync.index("\n  }\n")]
    assert '$(".rcompact", line)' in sync and ".rsum" not in sync.split("//")[0]


def test_the_compact_form_carries_the_repos_lanes_i_one_line_per_team(tmp_path, monkeypatch):
    from test_ui_org_layout import layout

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    lane = ["free-pick", "owner:grinder"]
    views = [
        sess("a1", team="alpha", repo="/r/shiftlead", state="working", lane=lane),
        sess("b1", team="beta", repo="/r/shiftlead", state="working", lane=lane),
    ]
    html = page(layout(views, [row("alpha", "shiftlead"), row("beta", "shiftlead")], ["shiftlead"]))
    c = compact(html[html.index('class="rline') :])
    tip = c[c.index('class="tipmark"') :]
    assert "in alpha&#39;s lanes" in tip.split(">")[0] and "in beta&#39;s lanes" in tip.split(">")[0]
    assert c.index('class="tipmark"') < c.index("data-addentry")  # the lanes *i*, then Add entry…
