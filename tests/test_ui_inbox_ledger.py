"""The ledger's rows of the Inbox's **Later** section (design §4.5 screen 6 *The ledger's entries that
wait on you*, §4.5a **Inbox: Later section**, **Inbox row: ledger entry**; TD-368, TD-565): the
entries the home's repo facts sort *for you*, grouped by repo, each a mail row — counted under
*Later* alone and in the rail's *ledger entries*, never in a number that means *due now*."""

from __future__ import annotations

import pytest
from conftest import scratch_dir
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


def test_a_rows_year_its_default_and_its_detail_read_only_what_they_can(tmp_path):
    """TD-571: a row added in another year says the year after the day; a `default` that is a bool
    is no index, so no answer is recommended; a `detail` line that is not a string is dropped."""
    from shiftlead.ui.app import ledger_for_you

    root = str(tmp_path / "agentorc")
    e = _e("TD-9", added="2001-10-07", answers=["Yes", "No"], default=True, detail=["one", 3, "two"])
    row = ledger_for_you({root: {"name": "agentorc", "root": root, "ledger": {"entries": [e]}}}, [], {})
    row = row["groups"][0]["rows"][0]
    assert row["added"] == "added Oct 7, 2001"
    assert row["answers"] == ["Yes", "No"] and row["default"] == ""
    assert row["detail"] == "one\ntwo"


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
    # a ledger row's subject is its title, its first paragraph already: no line of its own (§4.5a *subject*, TD-574)
    box = later[later.index('id="ledgerforyou"') :]
    assert "ledgerrow" in box and 'class="subj"' not in box
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


def test_a_ledger_rows_answers_go_with_it_and_reply(tmp_path, monkeypatch):
    """§4.5a **Inbox row: ledger entry** (TD-565 slice 2): the entry's answers as one button each,
    sending the index, the default marked; **Go with it** only on a row with a default; **Reply** on
    every row; each names the checkout the home's repo facts key the repo by, and the entry."""
    from shiftlead.ui.app import ledger_for_you

    root = str(tmp_path / "agentorc")
    html = _render(ledger_for_you(_repos(tmp_path), _fleet(tmp_path), {}), tmp_path, monkeypatch)
    t133 = _row(html, "ledger:agentorc:TD-133")
    group = t133[t133.index('aria-label="this entry\'s answers"') :]
    assert group.count('data-act="ledger"') >= 3 and 'data-index="2"' in group
    first = group[group.index('data-index="0"') : group.index('data-index="1"')]
    assert "&ldquo;At the reset&rdquo;" in first and '<span class="st adflt">default</span>' in first
    assert "adflt" not in group[group.index('data-index="1"') : group.index("</div>")]
    assert f'data-repo="{root}"' in t133 and 'data-ref="TD-133"' in t133
    assert 'data-go="1"' in t133 and ">Go with it</button>" in t133
    assert 'data-act="ledger_reply"' in t133 and ">Reply</button>" in t133
    t002 = _row(html, "ledger:agentorc:TD-002")
    assert 'data-act="ledger_reply"' in t002 and "Go with it" not in t002 and "this entry's answers" not in t002


def test_an_entry_an_open_decided_line_names_leaves_later(tmp_path):
    """§4.5 screen 6 (TD-565): once the reading lists an open decided line whose `Context:` names
    the entry — the repo's work orders' `refs`, bare or `<repo>#` — its row leaves *Later*; another
    repo's id of the same number does not take it."""
    from shiftlead.ui.app import ledger_for_you

    repos = _repos(tmp_path)
    a = str(tmp_path / "agentorc")
    repos[a]["work_orders"] = {"orders": [{"id": "board:1", "refs": ["TD-133"]}, {"refs": ["agentorc#TD-002"]},
                                          {"refs": ["samscrape#TD-156"]}]}  # fmt: skip
    rows = ledger_for_you(repos, [], {})["groups"][0]["rows"]
    assert [r["id"] for r in rows] == ["TD-156", "TD-319"]


def test_an_old_held_mark_on_an_entry_a_decided_line_names_draws_no_row(tmp_path):
    """TD-1297: a *for you* entry an open decided line names is that line's row; an old clock's `held`
    mark on it no longer brings it back as a *ledger · held* row."""
    from datetime import UTC, datetime, timedelta

    from shiftlead.ui.app import ledger_for_you

    now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    repos = _repos(tmp_path)
    a = str(tmp_path / "agentorc")
    by = {e["id"]: e for e in repos[a]["ledger"]["entries"]}
    by["TD-133"]["held"] = {"at": (now - timedelta(hours=2)).isoformat()}
    repos[a]["work_orders"] = {"orders": [{"id": "board:1", "refs": ["TD-133"]}]}
    rows = ledger_for_you(repos, [], {}, now)["groups"][0]["rows"]
    assert "TD-133" not in [r["id"] for r in rows]
    assert all(r["kind"] in ("ledger · yours", "ledger · your decision") for r in rows)


def test_the_route_hands_an_answer_go_with_it_or_words_to_ledger_decide(tmp_path, monkeypatch):
    """`POST /api/person/ledger`: the index, `go` or the Reply's words, with the repo and the id, to
    the home's `ledger_decide`; a press missing any of them is refused before the call."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from shiftlead.ui import app as ui

    calls = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            calls.append((method, kw))
            return {"decided": "x", "line": 7}

    monkeypatch.setattr(ui, "LocalClient", Fake)
    c = TestClient(ui.create_app())
    for body, want in (
        ({"repo": "/r", "id": "TD-1", "answer": 1}, {"answer": 1}),
        ({"repo": "/r", "id": "TD-1", "go": True}, {"go": True}),
        ({"repo": "/r", "id": "TD-1", "words": " drop it "}, {"words": "drop it"}),
    ):
        got = c.post("/api/person/ledger", json=body)
        assert got.status_code == 200 and got.json()["decided"] == "x"
        assert calls[-1] == ("ledger_decide", {"repo": "/r", "id": "TD-1", **want})
    n = len(calls)
    for body in ({"id": "TD-1", "go": True}, {"repo": "/r", "go": True}, {"repo": "/r", "id": "TD-1"},
                 {"repo": "/r", "id": "TD-1", "answer": "one"}):  # fmt: skip
        assert c.post("/api/person/ledger", json=body).status_code == 400
    assert len(calls) == n


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
    so the page keeps it current, and its `html.rail_teams` draws the teams the ledger's rows carry."""
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
    c = TestClient(ui.create_app())
    page = c.get("/inbox").text
    assert 'href="/repo/agentorc#TD-156"' in page
    assert '<span class="raillabel">Later</span><span class="railn">5</span>' in page  # the route's own rail
    got = c.get("/api/person/inbox").json()
    assert 'href="/repo/samscrape#TD-400"' in got["html"]["ledger"]
    assert got["needs"] == 0  # counted in no number that means *due now*
    # the poll's *Teams* lines count the ledger's rows as the route's do (TD-570): a team whose only
    # rows are ledger entries keeps its line after the first poll
    for team in ("ao-grind", "sam-grind"):
        assert f'data-value="{team}"' in got["html"]["rail_teams"]
        assert f'<span class="raillabel">{team}</span><span class="railn">0</span>' in got["html"]["rail_teams"]


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

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rules are JavaScript, and nothing else runs them")
    probe = scratch_dir() / "ledger_probe.js"
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
    assert "if (AO.ledgerSwap(lf, got.html.ledger)) {" in js
    # a ringed row holds no swap back, and the ring goes back on it (review of #1537), as a section's
    swap = js[js.index('const lf = $("#ledgerforyou");') :]
    swap = swap[: swap.index("AO.laterHas(lt)")]
    assert "AO.maySwapSection(lf, lring ? null : lon)" in swap and "AO.restoreRowErrs(lf, errs);" in swap
    assert "back.focus({ preventScroll: true })" in swap
    assert '!AO.laterHas(lt) && !rail.sec.includes("later")' in js


# -- **Start session** / **Open session** (§4.5a *Inbox row: ledger entry*, TD-676 designed, TD-678 built) --


def _start_world(
    tmp_path, monkeypatch, *, fleet=(), team=True, entries=None, checks=None, refuse="", host="", queue=None, inbox=None
):
    """`test_ui_entry`'s repo, team and fake host agent, whose repo facts hold TD-9 (*ledger · yours*, a
    debt), TD-12 (*ledger · your decision*, a feature) and TD-20 (pickable: no longer for you); `queue` the
    `queue` reading it serves (TD-912), else none; `inbox` the person inbox's entries it serves (TD-1256), else
    none, so the road's `card_mail` read fails and *waits on me* is the card's ledger entries."""
    import yaml
    from test_ui_entry import client, fake, world

    from sessionorc.client import AgentError

    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = world(tmp_path, team=team, entries=entries)
    if host:
        org = tmp_path / "home" / "org.yml"
        doc = yaml.safe_load(org.read_text())
        doc["teams"]["sam-grind"]["host"] = host
        org.write_text(yaml.safe_dump(doc))
    root = str(repo.resolve())
    reading = {"name": "samscrape", "root": root, "ledger": {"entries": [
        _e("TD-9", type="debt"),
        _e("TD-12", owner="grinder", type="feature", blocked_by=["decision (paul)"]),
        _e("TD-20", page="pickable", owner="grinder"),
    ]}}  # fmt: skip
    created: list[dict] = []

    class Fake(fake(list(fleet), created=created, checks=checks)):
        async def call(self, method, **kw):
            if method == "repos":
                return {root: reading}
            if method == "queue" and queue is not None:
                return queue
            if method == "inbox" and inbox is not None:
                return {"entries": [dict(e) for e in inbox]}
            if method == "create" and refuse:
                raise AgentError(refuse)
            return await super().call(method, **kw)

    return repo, client(monkeypatch, tmp_path, Fake), created


def _form(r):
    from urllib.parse import parse_qs, urlsplit

    got = r.json()
    assert r.status_code == 200 and got["ok"] is False and got["form"].startswith("/new?"), r.text
    return {k: v[0] for k, v in parse_qs(urlsplit(got["form"]).query).items()}, got["why"]


MANAGER = {"id": "ao-samscrape-manager-sam", "name": "manager-sam", "state": "idle", "team": "sam-grind"}


@pytest.mark.parametrize(
    ("ref", "role", "why"),
    [("TD-9", "techlead", "its owner is me"), ("TD-12", "designer", "it is blocked by a decision of mine")],
)
def test_start_session_starts_the_persons_session_in_td_n_with_work_md_sent(tmp_path, monkeypatch, ref, role, why):
    """One press: interactive, on the repo's team with the role `entries:` names for the entry's Type,
    the team's live manager its controller, the entry its lane, in worktree and branch `td-<n>` under
    that name, `work.md` filled as its first prompt — never a start context or the role's brief."""
    from shiftlead import repoconfig

    repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[MANAGER], entries={"feature": "designer"})
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": ref})
    assert r.status_code == 200, r.text
    name = ref.lower()
    assert r.json() == {"ok": True, "id": f"ao-samscrape-{name}", "name": name}
    (kw,) = created
    root = str(repo.resolve())
    assert (kw["name"], kw["worktree"], kw["dir"], kw["repo"]) == (name, name, root, root)
    assert kw["unattended"] is False and kw["role"] == role and kw["team"] == "sam-grind"
    assert kw["project"] == "sam"  # the repo's project, as New session's badge (§4.9, TD-1043)
    assert kw["lane"] == [ref] and kw["controllers"] == ["ao-samscrape-manager-sam"]
    assert "start_context" not in kw and kw["ledger"] == "docs/technical_debt.md"
    # an entry on no card: *waits on me* is the entry, *the rest* none (TD-912)
    qid = f"samscrape#TD-{int(ref[3:]):03d}"
    assert kw["prompt"] == repoconfig.work_text(
        ref, "samscrape", "docs/technical_debt.md", "yours" if role == "techlead" else "decision", mine=[qid]
    )
    assert kw["prompt"] == (
        f"I opened this session from the Inbox to work {ref} of samscrape's ledger (docs/technical_debt.md) myself: "
        f"it waits on me ({why}). Its entries are: waits on me — {qid}; the rest — none. Read the entry, check the "
        "code and the design for what is already built or decided, and tell me in a few lines what it asks of me "
        "and what you would do first. Then wait for me: I drive this one."
    )


@pytest.mark.parametrize(
    "holder",
    [
        {
            "id": "ao-samscrape-g1",
            "name": "grinder-sam-1",
            "state": "working",
            "progress": [{"ref": "TD-9", "status": "claimed"}],
        },
        {"id": "ao-samscrape-td-9", "name": "td-9", "state": "starting"},  # started, its claim not yet derived
    ],
)
def test_a_live_holder_of_the_entry_or_its_name_is_opened_and_nothing_starts(tmp_path, monkeypatch, holder):
    _repo, c, created = _start_world(tmp_path, monkeypatch, fleet=[{**holder, "repo": str(tmp_path / "samscrape")}])
    r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-9"})
    assert r.json() == {"ok": True, "focus": holder["id"]} and created == []


def test_an_entry_no_longer_for_you_is_refused_in_words(tmp_path, monkeypatch):
    _repo, c, created = _start_world(tmp_path, monkeypatch)
    for ref in ("TD-20", "TD-404"):
        r = c.post("/api/ledger/start", json={"repo": "samscrape", "id": ref})
        assert r.status_code == 409 and "no longer waits on you" in r.json()["detail"]
    assert c.post("/api/ledger/start", json={"repo": "nope", "id": "TD-9"}).status_code == 404
    assert created == []


def test_where_it_cannot_be_silent_the_press_lands_on_the_filled_form(tmp_path, monkeypatch):
    """No team, a name an exited session holds, a worktree or a branch `td-<n>`, a team on another host
    and a refused create each answer the New session form filled in as the press would have started,
    with the reason — and the form draws it, its opening prompt in the box."""
    from test_ui_entry import git

    cases = []
    _r, c, created = _start_world(tmp_path / "a", monkeypatch, team=False)
    cases.append((c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-9"}), "no team services samscrape"))
    checks = {"td-9": {"verdict": "supersede", "message": "replaces the exited td-9"}}
    _r, c, created2 = _start_world(tmp_path / "b", monkeypatch, checks=checks)
    cases.append(
        (c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-9"}), "td-9 names an exited session")
    )
    repo, c, created3 = _start_world(tmp_path / "c", monkeypatch)
    (repo / ".claude" / "worktrees" / "td-9").mkdir(parents=True)
    git(repo, "commit", "-q", "--allow-empty", "-m", "root")
    git(repo, "branch", "td-12")
    cases.append(
        (c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-9"}), "a worktree named td-9 exists")
    )
    cases.append(
        (c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-12"}), "a branch named td-12 exists")
    )
    _r, c, created4 = _start_world(tmp_path / "d", monkeypatch, host="node1")
    cases.append((c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-9"}), "sam-grind runs on node1"))
    _r, c, created5 = _start_world(tmp_path / "e", monkeypatch, refuse="host node1 is not connected")
    cases.append((c.post("/api/ledger/start", json={"repo": "samscrape", "id": "TD-9"}), "host node1 is not connected"))
    for r, why in cases:
        q, said = _form(r)
        assert said.startswith(why), said
        assert q["why"] == said and q["press"] == "start" and q["prefilled"] == "1"
        assert q["where"] == "worktree" and q["worktree"] == q["name"] and q["name"] in ("td-9", "td-12")
        assert q["lane"] == q["name"].upper() and "unattended" not in q
        assert q["prompt"].startswith(f"I opened this session from the Inbox to work {q['lane']} of samscrape's")
        assert q.get("team", "") == ("" if why.startswith("no team") else "sam-grind")
        assert q.get("role", "") == ("" if why.startswith("no team") else "techlead")
    assert created == created2 == created3 == created4 == []
    assert len(created5) == 0
    # the form draws what it was handed: the reason in Start session's words, the prompt in its box
    q, said = _form(cases[0][0])
    html = c.get("/new", params=q).text
    assert "⚠ Start session could not be one press: no team services samscrape" in html
    assert "I opened this session from the Inbox to work TD-9 of samscrape&#39;s ledger" in html


def test_the_row_draws_start_session_or_open_session_while_held(tmp_path, monkeypatch):
    """Every ledger row carries the press beside **Open**: **Start session**, or **Open session** while a
    live record holds the entry — the row's `holder` the first live claimer's id, `type` the entry's,
    `why` its kind for `work.md`."""
    from shiftlead.ui.app import ledger_for_you

    lf = ledger_for_you(_repos(tmp_path), _fleet(tmp_path), {})
    rows = {r["id"]: r for r in lf["groups"][0]["rows"]}
    assert (rows["TD-319"]["holder"], rows["TD-319"]["why"]) == ("g1", "decision")
    assert (rows["TD-156"]["holder"], rows["TD-156"]["why"]) == ("", "yours")  # a closed claimer holds nothing
    html = _render(lf, tmp_path, monkeypatch)
    held, free = _row(html, "ledger:agentorc:TD-319"), _row(html, "ledger:agentorc:TD-156")
    assert 'data-act="ledger_start" data-id="person" data-repo="agentorc" data-ref="TD-319"' in held
    assert ">Open session</button>" in held and ">Start session</button>" not in held
    assert (
        'data-act="ledger_start"' in free and ">Start session</button>" in free and "td-156, in a new worktree" in free
    )


def test_an_old_held_mark_adds_no_row_and_no_release(tmp_path, monkeypatch):
    """TD-1297 (§4.5 screen 6): the Inbox's ledger rows are the *for you* entries alone — no *Inbox row:
    held entry*, no *ledger · held* kind, no **Release** — and an old clock's `held` mark changes none of it."""
    from datetime import UTC, datetime, timedelta

    from shiftlead.ui.app import ledger_for_you

    now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    repos = _repos(tmp_path)
    by = {e["id"]: e for e in repos[str(tmp_path / "agentorc")]["ledger"]["entries"]}
    held = {"at": (now - timedelta(hours=2)).isoformat()}
    plain = [r["id"] for r in ledger_for_you(repos, _fleet(tmp_path), {}, now)["groups"][0]["rows"]]
    by["TD-010"].update(held=held, added="2026-10-01", detail=DETAIL)
    by["TD-133"]["held"] = held
    lf = ledger_for_you(repos, _fleet(tmp_path), {}, now)
    rows = lf["groups"][0]["rows"]
    assert [r["id"] for r in rows] == plain and "TD-010" not in plain
    t133 = next(r for r in rows if r["id"] == "TD-133")
    assert (t133["kind"], t133["added"]) == ("ledger · your decision", "added Oct 7")
    assert "release" not in t133 and "claimed" not in t133
    html = _render(lf, tmp_path, monkeypatch)
    row = _row(html, "ledger:agentorc:TD-133")
    assert ">Release</button>" not in row and ">Reply</button>" in row and "its answers" in row
    assert "ledger · held" not in html and "ledger_release" not in html and "held (person)" not in html
