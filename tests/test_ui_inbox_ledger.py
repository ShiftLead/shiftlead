"""The ledger's rows of the Inbox's **Later** section (design §4.5 screen 6 *The ledger's entries that
wait on you*, §4.5a **Inbox: Later section**, **Inbox row: ledger entry**; TD-368, TD-565): the
entries the home's repo facts sort *for you*, grouped by repo, each a mail row — counted under
*Later* alone and in the rail's *ledger entries*, never in a number that means *due now*."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def _e(i, page="for-you", pri="medium", owner="paul", **kw):
    return {"id": i, "title": f"entry {i}", "for_page": page, "priority": pri, "owner": owner, **kw}


DETAIL = ["**Why:** a team started by hand loses the hour.", "**Fix:**", "1. a `schedules:` block"]


def _repos(tmp_path):
    a, b, c = (str(tmp_path / n) for n in ("agentorc", "samscrape", "quiet"))
    return {
        a: {"name": "agentorc", "root": a, "ledger": {"entries": [
            _e("TD-319", pri="low", owner="grinder", blocked_by=["decision (paul)"]),
            _e("TD-156"),
            _e("TD-133", pri="low", owner="grinder", blocked_by=["decision (Paul)"], added="2026-10-07",
               answers=["At the reset", "At a fixed time", "Not now"], default=0, detail=DETAIL),
            _e("TD-010", page="pickable", owner="grinder"),
            _e("TD-002", pri="high"),
        ]}},
        b: {"name": "samscrape", "root": b, "ledger": {"entries": [_e("TD-400")]}},
        c: {"name": "quiet", "root": c, "ledger": {"entries": [_e("TD-1", page="other")]}},
    }  # fmt: skip


def _fleet(tmp_path):
    a, b = str(tmp_path / "agentorc"), str(tmp_path / "samscrape")
    claim = [{"ref": "TD-319", "status": "claimed"}]
    return [
        {"id": "g1", "name": "grinder-ao-1", "team": "ao-grind", "repo": a, "state": "working", "progress": claim},
        {"id": "g0", "name": "grinder-ao-0", "team": "ao-grind", "repo": a, "state": "closed", "progress":
         [{"ref": "TD-156", "status": "claimed"}]},
        {"id": "s1", "name": "sam-1", "team": "sam-grind", "repo": b, "state": "idle"},
    ]  # fmt: skip


def test_the_fold_lists_each_repos_for_you_entries_in_the_repo_pages_order(tmp_path):
    """Grouped by repo in the reading's order, a repo with none left out; within one, priority then
    id; *yours* for `Owner: paul`, *your decision* otherwise; *held by* a live record's claim and not
    an ended one's; the team the definitions give the repo, else its live records', else none; each
    row the Repo page opened on its id; `n` every row."""
    from shiftlead.ui.app import ledger_for_you

    got = ledger_for_you(_repos(tmp_path), _fleet(tmp_path), {str(tmp_path / "samscrape"): "sam-defined"})
    assert got["n"] == 5
    assert [g["repo"] for g in got["groups"]] == ["agentorc", "samscrape"]
    rows = got["groups"][0]["rows"]
    assert [r["id"] for r in rows] == ["TD-002", "TD-156", "TD-133", "TD-319"]
    mine, theirs = "ledger · yours", "ledger · your decision"
    whys = [("H", mine), ("M", mine), ("L", theirs), ("L", theirs)]
    assert [(r["pri"], r["kind"]) for r in rows] == whys
    assert {r["row"] for r in rows} == {"ledger"} and rows[0]["name"] == "agentorc"
    assert rows[0]["row_id"] == "ledger:agentorc:TD-002"
    # the reading's added, answers (the default by its text) and detail (TD-565)
    t133 = rows[2]
    assert t133["at"] == "2026-10-07" and t133["added"].startswith("added Oct 7")
    assert t133["answers"] == ["At the reset", "At a fixed time", "Not now"] and t133["default"] == "At the reset"
    assert t133["detail"] == "\n".join(DETAIL)
    bare = (rows[0]["at"], rows[0]["added"], rows[0]["answers"], rows[0]["default"], rows[0]["detail"])
    assert bare == ("", "", [], "", "")
    assert [r["held"] for r in rows] == ["", "", "", "grinder-ao-1"]  # the closed record holds nothing
    assert {r["team"] for r in rows} == {"ao-grind"} and rows[0]["url"] == "/repo/agentorc#TD-002"
    assert got["groups"][1]["rows"][0]["team"] == "sam-defined"  # the definitions' team first
    assert ledger_for_you(_repos(tmp_path), [], {})["groups"][0]["rows"][0]["team"] == ""  # none: *no team*
    assert ledger_for_you({}, [], {}) == {"n": 0, "groups": []}


def _render(lf, tmp_path, monkeypatch, horizon=None):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    (tmp_path / "hosts.yml").write_text("local:\n  name: kmaster\n  local: true\n")
    from shiftlead.ui.app import inbox_sections, templates

    sections = inbox_sections([])
    return templates.get_template("inbox.html").render(
        sections=sections, person_needs=sections["count"], host="kmaster", active="Inbox",
        agent_down=False, volatile=False, usage={}, ledger=lf, horizon=horizon,
    )  # fmt: skip


def _row(html, rid):
    at = html.index(f'data-msg="{rid}"')
    row = html[html.rindex("<div ", 0, at) :]
    return row[: row.index('<div class="st rowerr"')]


def test_later_sits_after_answered_and_holds_the_ledgers_rows_counted_there_alone(tmp_path, monkeypatch):
    """§4.5a **Inbox: Later section**: after *Answered for you*, before FYI, headed *Later (n)* with
    *not pressing · not counted*; the horizon's box and the ledger's under it, the board's first; the
    rail's *Urgency* lists it with its count and *Kinds* lists *ledger entries*; *Needs you*'s
    number is untouched; nothing drawn at zero."""
    from shiftlead.ui.app import ledger_for_you

    html = _render(ledger_for_you(_repos(tmp_path), _fleet(tmp_path), {}), tmp_path, monkeypatch)
    assert html.index('id="sec-answered"') < html.index('id="sec-later"') < html.index('id="sec-fyi"')
    later = html[html.index('id="sec-later"') : html.index('id="sec-fyi"')]
    assert '<section class="isec" id="sec-later">' in html  # drawn: it has rows
    assert '<span class="h2">Later</span><span class="meta" id="n-later">5</span>' in later
    assert "not pressing · not counted" in later and 'id="info-later"' in later
    assert later.index('id="boardhorizon"') < later.index('id="ledgerforyou"')
    assert 'class="meta mono ledgerrepo">samscrape<' in later
    assert "ledgerrow" not in html[: html.index('id="sec-later"')]
    rail = html[html.index('id="rail"') : html.index("</aside>")]
    assert 'data-value="later"' in rail and 'data-value="ledger"' in rail
    line = rail[rail.index('data-value="later"') :]
    assert '<span class="raillabel">Later</span><span class="railn">5</span>' in line
    kind = rail[rail.index('data-value="ledger"') :]
    assert '<span class="raillabel">ledger entries</span><span class="railn">5</span>' in kind
    assert '<span class="meta" id="n-needs"></span>' in html  # nothing in *Needs you*
    empty = _render({"n": 0, "groups": []}, tmp_path, monkeypatch)
    assert '<section class="isec hidden" id="sec-later">' in empty and "ledgerrow" not in empty


def test_a_ledger_row_is_a_mail_rows_shape(tmp_path, monkeypatch):
    """§4.5a **Inbox row: ledger entry**: the repo as its name, the team badge, the kind, *held by*,
    the age from `Added:` with the letter; the id and title first; *details* the Why and Fix, open on
    a row with answers; **Open** the Repo page on the id; the rail's kind, section, team and find on
    the row."""
    from shiftlead.ui.app import ledger_for_you

    html = _render(ledger_for_you(_repos(tmp_path), _fleet(tmp_path), {}), tmp_path, monkeypatch)
    row = _row(html, "ledger:agentorc:TD-319")
    assert 'class="mailrow ledgerrow"' in row and 'data-rkind="ledger"' in row and 'data-section="later"' in row
    assert 'data-team="ao-grind"' in row and "td-319" in row and "grinder-ao-1" in row
    assert '<span class="ref" title="agentorc' in row and ">ledger · your decision</span>" in row
    assert "held by grinder-ao-1" in row and ">L</span>" in row
    assert '<b class="mono">TD-319</b> entry TD-319' in row and "<details" not in row  # no detail: no fold
    assert '<a class="btn sm ghost" href="/repo/agentorc#TD-319"' in row and ">Open</a>" in row
    t133 = _row(html, "ledger:agentorc:TD-133")
    assert ">added Oct 7" in t133 and '<details class="fold" data-fold="ledger:agentorc:TD-133" open>' in t133
    assert "a team started by hand loses the hour." in t133
    t002 = _row(html, "ledger:agentorc:TD-002")
    assert "No team" not in t002 and ">ledger · yours</span>" in t002 and ">H</span>" in t002


def test_the_rail_counts_later_from_the_horizon_and_the_ledger():
    """`rail_rows` puts the ledger's rows in `later` and the horizon's coming up in `coming`, which
    the rail reads as *Later*: its line, its heading and a section pick; *Needs you* keeps its own."""
    from shiftlead.ui.app import inbox_sections, rail_counts, rail_rows

    ahead = [{"row": "board", "id": "b1", "team": "t", "find": "x"}]
    ledger = [{"row": "ledger", "id": "TD-1", "team": "t", "title": "y"}]
    rows = rail_rows(inbox_sections([]), ahead, ledger)
    c = rail_counts(rows, {"team": [], "sec": [], "kind": [], "find": ""})
    assert c["sections"]["later"] == {"shown": 2, "all": 2} and c["heads"]["later"]["all"] == 2
    assert c["sections"]["needs"]["all"] == 0 and c["kinds"]["ledger"]["all"] == 1 and c["kinds"]["board"]["all"] == 1
    picked = rail_counts(rows, {"team": [], "sec": ["later"], "kind": ["ledger"], "find": ""})
    assert picked["heads"]["later"] == {"shown": 1, "all": 2}


def test_the_page_and_its_poll_draw_the_fold_from_the_home_repo_facts(tmp_path, monkeypatch):
    """The route reads the home's `repos` and the fleet; the poll's `html.ledger` is the same box,
    so the page keeps it current."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    repos, fleet = _repos(tmp_path), _fleet(tmp_path)

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            got = {"repos": repos, "list": fleet, "inbox": {"entries": []}, "host": {"name": "kmaster"}}
            return got.get(method, {})

    monkeypatch.setattr(ui, "LocalClient", Fake)
    monkeypatch.setattr(ui, "read_boards", lambda *a, **k: ([], ""))
    c = TestClient(ui.create_app())
    page = c.get("/inbox").text
    assert 'href="/repo/agentorc#TD-156"' in page
    assert '<span class="raillabel">Later</span><span class="railn">5</span>' in page  # the route's own rail
    got = c.get("/api/person/inbox").json()
    assert 'href="/repo/samscrape#TD-400"' in got["html"]["ledger"]
    assert got["needs"] == 0  # counted in no number that means *due now*


LEDGER_PROBE = """
const fs = require("fs");
const noop = () => {};
const el = (o) => Object.assign({
  dataset: {}, style: {}, hidden: false, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [], contains: () => false,
}, o);
const document = { documentElement: el(), body: el(), activeElement: null,
  querySelector: () => null, querySelectorAll: () => [], addEventListener: noop, createElement: () => el() };
const window = {};
const kept = new Map();
global.window = window; global.document = document;
global.localStorage = { getItem: (k) => (kept.has(k) ? kept.get(k) : null), setItem: (k, v) => kept.set(k, String(v)) };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/inbox", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
// *Later* as `ledger_for_you.html` draws it: two repos' groups, each `.ledgerrow` hidden or not by the rail
const row = (hidden) => el({ hidden });
const a1 = row(false), a2 = row(true), s1 = row(true);
const ga = el({ querySelectorAll: (s) => (s === ".ledgerrow" ? [a1, a2] : []) });
const gs = el({ querySelectorAll: (s) => (s === ".ledgerrow" ? [s1] : []) });
const all = { ".inboxpage .ledgergroup": [ga, gs] };
const root = el({ querySelectorAll: (s) => all[s] || [] });
const out = {};
AO.ledgerFilter(root); out.groups = [!ga.hidden, !gs.hidden];
s1.hidden = false; AO.ledgerFilter(root); out.back = [!ga.hidden, !gs.hidden];
// the poll's swap: new markup is put in and remembered; the same markup again is left alone
const lf = el({ innerHTML: "drawn by the page" });
out.swap_first = AO.ledgerSwap(lf, "<div>v1</div>"); out.html_first = lf.innerHTML;
lf.innerHTML = "the person's open fold";
out.swap_same = AO.ledgerSwap(lf, "<div>v1</div>"); out.html_same = lf.innerHTML;
out.swap_new = AO.ledgerSwap(lf, "<div>v2</div>"); out.html_new = lf.innerHTML;
out.swap_missing = [AO.ledgerSwap(null, "x"), AO.ledgerSwap(lf, undefined)];
// *Later* holds something: a row coming up, a fold, or a ledger row
const sec = (hit) => el({ querySelector: (q) => (hit ? {} : null) });
out.later = [AO.laterHas(sec(true)), AO.laterHas(sec(false))];
console.log(JSON.stringify(out));
"""


def test_a_repos_name_goes_with_its_last_row_and_the_poll_puts_later_back():
    """§4.5 screen 6 *The ledger's entries that wait on you* (TD-374, TD-565): the client side, run
    under node — a repo's group goes with its last row shown; the poll puts new markup back and
    leaves the same markup alone; *Later* is drawn while it holds anything."""
    import json
    import pathlib
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rules are JavaScript, and nothing else runs them")
    probe = pathlib.Path(tempfile.mkdtemp()) / "ledger_probe.js"
    probe.write_text(LEDGER_PROBE)
    app_js = pathlib.Path(__file__).parents[1] / "src" / "shiftlead" / "ui" / "static" / "app.js"
    out = subprocess.run([node, str(probe), str(app_js)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["groups"] == [True, False]  # samscrape's name goes with its last row
    assert got["back"] == [True, True]
    assert got["swap_first"] is True and got["html_first"] == "<div>v1</div>"
    assert got["swap_same"] is False and got["html_same"] == "the person's open fold"
    assert got["swap_new"] is True and got["html_new"] == "<div>v2</div>"
    assert got["swap_missing"] == [False, False]
    assert got["later"] == [True, False]
    # …and the page calls them where the rules apply
    js = app_js.read_text()
    assert "AO.ledgerFilter(document);" in js
    assert "AO.ledgerSwap(lf, got.html.ledger)) AO.reopenFolds(lf);" in js
    assert '!AO.laterHas(lt) && !rail.sec.includes("later")' in js
