"""The Repo facet on each team card (design §4.5a *team card: Repo facet*, *Sessions: repo line*, TD-1189,
built by TD-1194): drawn first on every Sessions card that draws a summary, with the team's lanes, no name
row; the repo's line keeps it only while no card of the repo shows one; the Repo page's cards draw none."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from conftest import scratch_dir
from test_ui_keys import PROBE, UI
from test_ui_org_layout import layout, page, row, sess

pytestmark = pytest.mark.unit

LINE_PROBE = (
    PROBE[: PROBE.index("console.log(")]
    + """
const c = (o) => Object.assign({ hidden: false, folded: false, filtering: false, facet: true }, o);
console.log(JSON.stringify([
  AO.lineFacetShown([]),                                                   // a repo with no team
  AO.lineFacetShown([c({})]),                                              // a card shows it
  AO.lineFacetShown([c({ folded: true })]),                                // its only card folded
  AO.lineFacetShown([c({ folded: true }), c({})]),                         // one of two folded
  AO.lineFacetShown([c({ folded: true }), c({ hidden: true })]),           // folded, and hidden by the filter
  AO.lineFacetShown([c({ folded: true, filtering: true })]),               // a filter shows a folded card's summary
  AO.lineFacetShown([c({ facet: false })]),                                // a card drawing no Repo facet
]));
"""
)


def test_the_lines_facet_shows_only_while_no_card_of_the_repo_shows_one():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "line_facet_probe.js"
    probe.write_text(LINE_PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [True, False, True, False, True, False, True]
    js = (UI / "static" / "app.js").read_text()
    # re-checked where the team cards sync (a fold, a swap) and where the filter runs
    assert js.count("syncLineFacets();") == 2 and '$(".tsum > .frepo", s)' in js


def test_the_card_draws_it_first_and_the_line_renders_it_for_the_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    items = layout([sess("t1", team="t", repo="/r/main", state="working")], [row("t", "main")], ["main"])
    (card,) = [it for it in items if it["kind"] == "team"]
    assert card["summary"]["drawn"] == ["repo", "motion", "face"]
    html = page(items)
    line = html[html.index('class="rline') : html.index('<section class="tgroup"')]
    assert 'class="tsum rsum" data-team="repo:main"' in line and 'class="facet frepo"' in line  # its key kept
    sec = html[html.index('<section class="tgroup"') :]
    tsum = sec[sec.index('class="tsum"') : sec.index("</section>")]
    assert tsum.index("frepo") < tsum.index("fmotion") < tsum.index("fface")
    # **Add entry…** on the card's facet opens the form with the card's repo
    assert '<button class="btn sm ghost" type="button" data-addentry="main"' in tsum


def test_a_stopped_team_with_a_repo_reading_draws_its_repo_facet(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.org import drawn_facets

    items = layout([sess("t1", team="t", repo="/r/main", state="exited", rank=1)], [row("t", "main")], ["main"])
    (card,) = [it for it in items if it["kind"] == "team"]
    assert not card["live"] and card["summary"]["drawn"] == drawn_facets(card["summary"]) == ["repo"]


def test_the_repo_pages_cards_draw_none():
    from shiftlead.ui.app import team_groups

    views = [
        sess("t1", team="t", repo="/r/main", state="working"),
        sess("t2", team="t", repo="/r/main", state="exited"),
    ]
    readings = {"/r/main": {"name": "main", "root": "/r/main", "ledger": {"entries": []}, "prs": {"open": []}}}
    for repo_page, drawn in ((False, ["repo", "motion", "face"]), (True, ["motion", "face"])):
        (g,) = team_groups(views, [row("t", "main")], readings, {}, repo_page=repo_page)
        assert g["summary"]["drawn"] == drawn and g["summary"]["repo"]
    app = (UI / "app.py").read_text()
    assert app.count("repo_page=True") == 1  # the Repo page's own call
