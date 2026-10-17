"""TD-829, design §4.5 screen 12 *Filters* and §4.5a *Queue page: filters, find*: a pick answers in the browser.
Each card, completed line and *other work* line carries what the picks read as `data-` attributes, and
`app.js`'s `AO.qPicks`, `AO.qQuery` and `AO.qPass` read the URL, write it and hide what `ui.queue`'s
`queue_picks`, `picks_query` and `apply_picks` do on the server — run in node against the same reading. A bare
`/queue` takes the remembered picks (`ao.qpicks`) and window (`ao.qwin`) in `base.html`'s head."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.datastructures import QueryParams
from test_ui_queue import NOW, client, fake, queue

from shiftlead.ui.queue import apply_picks, picks_query, queue_picks, queue_view

pytestmark = pytest.mark.unit

UI = pathlib.Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui"

PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
global.window = {};
global.document = { documentElement: el(), body: el(), addEventListener: noop, createElement: el,
  querySelector: () => null, querySelectorAll: () => [] };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
console.log(JSON.stringify(cases.map((c) => {
  const p = AO.qPicks(c.search);
  return { picks: p, query: AO.qQuery(p, c.change || {}), filtered: AO.qFiltered(p),
    off: c.items.map((it) => !AO.qPass(it, p, c.teams)) };
})));
"""

TEAMS = {"sgrind": "s", "dbteam": "db", "ghost": ""}
SEARCHES = [
    "",
    "?filter=needs-you",
    "?filter=steering",
    "?filter=bogus",
    "?team=dbteam",
    "?team=ghost",
    "?team=sgrind&repo=db",
    "?repo=s",
    "?repo=s,db&kind=held-person",
    "?kind=questions,nonsense",
    "?find=td-21",
    "?find=TD-021",
    "?find=TD-2",
    "?find=keep%20%20back",
    "?find=db%23TD-5",
    "?find=TD-3",
    "?team=a&team=b,a&find=queue",
]


def _items(view: dict) -> list[dict]:
    cards = [
        {"kind": "card", "status": c.get("status") or "", "kinds": c.get("kinds") or [], "repos": c.get("repos") or []}
        | {"find": c.get("find") or ""}
        for c in [*view["in_progress"], *view["up_next"]]
    ]
    lines = [{"kind": "line", "repos": [ln["repo"]], "find": ln["find"]} for ln in view["completed"]["lines"]]
    return [*cards, *lines, *({"kind": "other"} for _ in view["other"])]


def _offs(view: dict) -> list[bool]:
    return [c["off"] for c in [*view["in_progress"], *view["up_next"], *view["completed"]["lines"], *view["other"]]]


def _node(cases: list[dict]) -> list[dict]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the Queue's in-browser picks are JavaScript, and nothing else runs them")
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "probe.js").write_text(PROBE)
    (d / "cases.json").write_text(json.dumps(cases))
    out = subprocess.run(
        [node, str(d / "probe.js"), str(UI / "static" / "app.js"), str(d / "cases.json")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_pick_in_the_browser_hides_what_the_servers_apply_picks_hides():
    view = queue_view(queue(repo2=True), NOW)
    got = _node([{"search": s, "items": _items(view), "teams": TEAMS} for s in SEARCHES])
    for s, js in zip(SEARCHES, got, strict=True):
        picks = queue_picks(QueryParams(s.lstrip("?")))
        server = apply_picks(queue_view(queue(repo2=True), NOW), picks, TEAMS)
        assert js["picks"] == picks, s
        assert js["off"] == _offs(server), s
        assert js["filtered"] == server["filtered"], s
    # the fixture's picks are not all-or-nothing: some hide a part
    assert any(0 < sum(js["off"]) < len(js["off"]) for js in got)


def test_the_url_after_a_press_is_the_servers_link_for_it_and_loads_the_same_picks():
    presses = [
        ("", {"filter": "needs-you"}),
        ("?filter=needs-you", {"filter": "needs-you"}),  # pressed again: All
        ("?filter=needs-you&team=a,b", {"team": "a"}),
        ("?kind=yours&find=the%20queue", {"kind": "board"}),
        ("?repo=s", {"repo": "db"}),
        ("?repo=s", {"find": "TD-5"}),
    ]
    got = _node([{"search": s, "change": ch, "items": [], "teams": {}} for s, ch in presses])
    for (s, ch), js in zip(presses, got, strict=True):
        picks = queue_picks(QueryParams(s.lstrip("?")))
        assert js["query"] == picks_query(picks, **ch), (s, ch)
        # the address loads the picks it was made from
        assert queue_picks(QueryParams(urlsplit(js["query"]).query)) == queue_picks(
            QueryParams(urlsplit(picks_query(picks, **ch)).query)
        )
    assert parse_qs(urlsplit(got[2]["query"]).query) == {"filter": ["needs-you"], "team": ["b"]}


def test_each_card_and_line_carries_what_the_picks_read(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(queue(), []))
    html = c.get("/queue").text
    card = 'data-card="s#TD-30" data-ids="s#TD-30" data-up="1" data-status="needs you" data-kinds="held-person"'
    assert card + ' data-repos="s"' in html
    assert 'data-find="s#td-30 s#td-030 td-030 keep this one back"' in html
    assert 'data-n="2" data-repo="s" data-find="' in html and 'class="qother" data-other="1"' in html
    # the empty window's line says the window it is in, as the heading does
    assert '>nothing closed<span class="qwinword" data-wv="4h" hidden> in the last 4 hours</span>' in html
    assert '<span class="qwinword" data-wv="month" hidden> in the last month</span></div>' in html
    row = html[html.index('id="qfilters"') : html.index('id="qcompleted"')]
    assert "data-teams='{}'" in row and 'data-k="all" href="/queue"' in row
    assert row.count('data-k="kind"') == 6 and 'data-k="filter" data-v="steering"' in row
    js = c.get("/static/app.js").text
    assert 'history[push ? "pushState" : "replaceState"]' in js and 'store.set("qpicks", "")' in js
    assert "setTimeout(() => { typing = null; setPicks(typed(), false); }, 150)" in js


def test_a_bare_queue_restores_the_remembered_picks_and_window_before_the_first_paint(tmp_path, monkeypatch):
    c = client(monkeypatch, tmp_path, fake(queue(), []))
    head = c.get("/queue").text.split("</head>", 1)[0]
    script = head[head.index('if (location.pathname !== "/queue") return;') :]
    assert 'localStorage.getItem("ao.qwin")' in script and 'localStorage.getItem("ao.qpicks")' in script
    assert 'if (!location.search && typeof p === "string"' in script and "history.replaceState" in script
    assert head.index("ao.qpicks") < head.index("app.css")  # before the stylesheet, as the theme's read is
    css = c.get("/static/app.css").text
    assert "html[data-qpend] #queuelists, html[data-qpend] #qfilters { visibility: hidden; }" in css
