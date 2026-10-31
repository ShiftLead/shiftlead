"""TD-829, design §4.5 screen 12 *Filters* and §4.5a *Queue page: filters, find*: a pick answers in the browser.
Each card, completed line and *other work* line carries what the picks read as `data-` attributes, and
`app.js`'s `AO.qPicks`, `AO.qQuery` and `AO.qPass` read the URL, write it and hide what `ui.queue`'s
`queue_picks`, `picks_query` and `apply_picks` do on the server — run in node against the same reading. A card
sends no `data-find`: `AO.qFindText` builds it from the ids and titles the card draws, by `_find_text`'s rule
(§4.5 *Page loads*: *Nothing the page does not read*, TD-892). A bare `/queue` takes the remembered picks
(`ao.qpicks`) and window (`ao.qwin`) in `base.html`'s head, which drops a key the row no longer has (TD-1287)."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import scratch_dir
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
    off: c.items.map((it) => !AO.qPass(it.rows ? { ...it, find: AO.qFindText(it.rows) } : it, p, c.teams)),
    finds: (c.cards || []).map(AO.qFindText) };
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
    "?team=s",  # a repo chip: a name no team holds is a repo (TD-1287)
    "?team=dbteam,s",
    "?team=nowhere",  # an unknown name: a repo the home does not read, so no card
    "?team=nowhere&filter=needs-you",
    "?team=",  # the chips cleared
    "?team=,&find=TD-21",
    "?find=td-21",
    "?find=TD-021",
    "?find=TD-2",
    "?find=keep%20%20back",
    "?find=db%23TD-5",
    "?find=TD-3",
    "?find=21",
    "?find=Queue%27s",
    "?team=a&team=b,a&find=queue",
    "?filter=needs-you&filter=steering&find=a&find=TD-20",
]


def _items(view: dict) -> list[dict]:
    cards = [
        {"kind": "card", "status": c.get("status") or "", "repos": c.get("repos") or []}
        | {"rows": [{"qid": r["qid"], "title": r["title"]} for r in [c["top"], *c["rows"]]]}  # built in the browser
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
    d = scratch_dir()
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


class _Cards(HTMLParser):
    """What `AO.qCardRows` reads off the drawn page: each card's header and rows, by `data-qid`, each with the
    text of its `.qtitle`."""

    def __init__(self):
        super().__init__()
        self.cards: list[list[dict]] = []
        self.title = 0  # the depth inside a `.qtitle` being read

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if "qcard" in cls:
            self.cards.append([])
        elif ("qhead" in cls or "qrow" in cls) and "data-qid" in a:
            self.cards[-1].append({"qid": a["data-qid"], "title": None})
        elif "qtitle" in cls and self.cards and self.cards[-1] and self.cards[-1][-1]["title"] is None:
            self.cards[-1][-1]["title"], self.title = "", 1
        elif self.title:
            self.title += 1

    def handle_endtag(self, tag):
        self.title = max(self.title - 1, 0)

    def handle_data(self, data):
        if self.title:
            self.cards[-1][-1]["title"] += data


def test_a_cards_find_text_built_in_the_browser_is_the_servers(tmp_path, monkeypatch):
    q = queue(repo2=True)
    q["cards"][1]["rows"][0]["title"] = "Build the Queue's <find> & ÄÖ — TD-7 too"  # escaped, cased, an id in it
    page = client(monkeypatch, tmp_path, fake(q, []))
    parsed = _Cards()
    parsed.feed(page.get("/queue").text)
    view = queue_view(q, NOW)
    cards = [*view["in_progress"], *view["up_next"]]
    assert [[r["qid"] for r in rows] for rows in parsed.cards] == [
        [r["qid"] for r in [c["top"], *c["rows"]]] for c in cards
    ]
    (got,) = _node([{"search": "", "items": [], "teams": {}, "cards": parsed.cards}])
    assert got["finds"] == [c["find"] for c in cards]
    assert "build the queue's <find> & äö — td-7 too" in got["finds"][1]


def test_the_url_after_a_press_is_the_servers_link_for_it_and_loads_the_same_picks():
    presses = [
        ("", {"filter": "needs-you"}),
        ("?filter=needs-you", {"filter": "needs-you"}),  # pressed again: All
        ("?filter=needs-you&team=a,b", {"team": "a"}),
        ("?kind=yours&find=the%20queue", {"team": "s"}),
        ("?repo=s", {"find": "TD-5"}),
        # a list replaces the chips (**All** is `team: []`), keeping the switch and the find
        ("?filter=needs-you&team=a,b&find=the%20queue", {"team": []}),
        ("?team=a", {"team": ["b", "c"]}),
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
    card = 'data-card="s#TD-30" data-ids="s#TD-30" data-up="1" data-status="needs you"'
    assert card + ' data-repos="s"' in html
    # a card sends no find text (TD-892); a completed line keeps its own, its entries' titles being folded
    assert 'data-find="s#td-30' not in html and html.count("data-find=") == html.count('class="qdline')
    assert 'data-n="2" data-repo="s" data-find="' in html and 'class="qother" data-other="1"' in html
    # the empty window's line says the window it is in, as the heading does
    assert '>nothing closed<span class="qwinword" data-wv="4h" hidden> in the last 4 hours</span>' in html
    assert '<span class="qwinword" data-wv="month" hidden> in the last month</span></div>' in html
    row = html[html.index('id="qfilters"') : html.index('id="qcompleted"')]
    assert "data-teams='{}'" in row and 'data-k="all" href="/queue"' in row
    assert 'data-k="kind"' not in row and 'data-v="steering"' not in row and "data-kinds" not in html
    js = c.get("/static/app.js").text
    assert 'history[push ? "pushState" : "replaceState"]' in js and 'store.set("qpicks", "")' in js
    # **All** clears the chips alone and rewrites the memory, the switch kept in it (TD-1287)
    assert 'if (f.dataset.k === "all") { setPicks({ ...picks, team: [] }, true); return remember(); }' in js
    # Space toggles the switch as Enter does
    assert 'if (e.key === " " && e.target.matches && e.target.matches("#qfilters .qswitch"))' in js
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


HEAD_PROBE = """
const fs = require("fs");
const script = fs.readFileSync(process.argv[2], "utf8");
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
console.log(JSON.stringify(cases.map((mem) => {
  const out = { url: null, pend: false };
  const store = { "ao.qpicks": mem === null ? null : JSON.stringify(mem) };
  const ctx = {
    localStorage: { getItem: (k) => (k in store ? store[k] : null) },
    history: { replaceState: (s, t, url) => { out.url = url; } },
    location: { pathname: "/queue", search: "", hash: "" },
    document: { documentElement: { dataset: {} } },
    setTimeout: () => {},
  };
  new Function(...Object.keys(ctx), script)(...Object.values(ctx));
  out.pend = "qpend" in ctx.document.documentElement.dataset;
  return out;
})));
"""


def test_the_head_drops_a_remembered_pick_the_row_no_longer_has(tmp_path, monkeypatch):
    """TD-1287: a memory holding `kind=`, `repo=` or `filter=steering` restores as if it held none of them; a
    memory left empty by that writes no URL and holds nothing back."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the head's restore is JavaScript, and nothing else runs it")
    head = client(monkeypatch, tmp_path, fake(queue(), [])).get("/queue").text.split("</head>", 1)[0]
    at = head.index('<script>(function () { if (location.pathname !== "/queue")')
    script = head[at + len("<script>") : head.index("</script>", at)]
    cases = ["?kind=do", "?filter=steering&repo=x", "?filter=steering&team=a&repo=x,y&kind=do", "?filter=needs-you",
             "?team=a&filter=needs-you", "", None]  # fmt: skip
    (tmp_path / "head.js").write_text(script)
    (tmp_path / "probe.js").write_text(HEAD_PROBE)
    (tmp_path / "cases.json").write_text(json.dumps(cases))
    out = subprocess.run(
        [node, str(tmp_path / "probe.js"), str(tmp_path / "head.js"), str(tmp_path / "cases.json")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [
        {"url": None, "pend": False},
        {"url": None, "pend": False},
        {"url": "/queue?team=a", "pend": True},
        {"url": "/queue?filter=needs-you", "pend": True},
        {"url": "/queue?team=a&filter=needs-you", "pend": True},
        {"url": None, "pend": False},
        {"url": None, "pend": False},
    ]


WINDOW_PROBE = """
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
const W = ["4h", "day", "week", "month"];
console.log(JSON.stringify(W.map((loaded) => W.map((want) => window.AO.qWinFetch(loaded, want)))));
"""


def test_a_wider_window_is_read_once_and_a_narrower_answers_from_what_is_held(tmp_path, monkeypatch):
    """TD-882, §4.5 *Page loads* (*only what is shown*): the windows nest, so the page holding a window's lines
    answers a narrower pick at once and reads a wider one by the lists' `part=1&win=` read, which keeps it."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the Queue's window pick is JavaScript, and nothing else runs it")
    probe = tmp_path / "win.js"
    probe.write_text(WINDOW_PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [
        ["", "day", "week", "month"],  # 4h held
        ["", "", "week", "month"],  # day held: the load's
        ["", "", "", "month"],
        ["", "", "", ""],
    ]
    js = (UI / "static" / "app.js").read_text()
    qjs = js[js.index("AO.queue = function") : js.index("AO.repo = function")]
    # the lists' read asks for the window held, or the wider one picked; the head's hold lifts once it is drawn
    assert 'q.set("win", win)' in qjs
    assert 'const win = AO.qWinFetch(loaded(), store.get("qwin", "day")) || loaded();' in qjs
    # a read that fell short of its window is the poll's to repeat
    assert "if (read && AO.qWinFetch(loaded(), win) === win) short = win;" in qjs
    assert "if (loading()) reread(); else delete document.documentElement.dataset.qpend;" in qjs
    assert "if (read && loading() && loading() !== win) setTimeout(reread, 0);" in qjs
    part = client(monkeypatch, tmp_path, fake(queue())).get("/queue?part=1&win=month").text
    assert 'data-loaded="month"' in part and part.count('class="qdline') == 4
