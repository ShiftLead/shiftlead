"""The Focus's disconnect card (design §4.6 *The disconnect card*, §4.5a **disconnect card**; TD-923):
while the terminal reconnects, the spend the page last held — this session, its team and all teams,
today and this week, money by unit and tokens on every row, the account's windows and when the figures
were read — drawn from what the page kept, never fetched while the link is down."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

import pytest

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
APP = UI / "static" / "app.js"

PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [], contains: () => false });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: () => el() };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const tok = (i, o, r, w) => ({ input: i, output: o, cache_read: r, cache_write: w });
const seat = (records, unit, figure, tokens, unweighed) =>
  ({ records, unit, figure, tokens, unweighed_tokens: unweighed || 0 });
const day = { seats: [
  seat(["me"], "≈$", 6.93, tok(1000, 2000, 7000000, 397000)),
  seat(["peer"], "$", 1.2, tok(500, 500, 0, 0)),
  seat(["peer2"], "≈$", 150.4, tok(0, 0, 0, 0), 4100000),
] };
const week = { seats: [seat(["me", "me-old"], "≈$", 38.02, tok(0, 0, 39900000, 0))] };
const held = { team: { day, week }, all: { day, week: { seats: [] } }, at: Date.UTC(2026, 9, 20, 14, 2),
  usage: { paul: { windows: [{ label: "week", pct: 98, resets: "2026-10-20T17:59:00Z" },
    { label: "5h", pct: 11, resets: "2026-10-20T12:29:00Z" }, { label: "bad", pct: 3, resets: "never" }] } } };
const now = Date.UTC(2026, 9, 20, 14, 30);
const two = { ...held, usage: { a: { windows: [{ label: "week", pct: 5 }] },
  b: { windows: [{ label: "5h", pct: 7 }] } } };
console.log(JSON.stringify({
  card: AO.dropCard(held, "me", "ao-grind", now),
  teamless: AO.dropCard({ all: { day } }, "me", "", now).rows.map((r) => [r.label, r.day && r.day.money, r.week]),
  nothing: AO.dropCard(null, "me", "ao-grind", now),
  two: AO.dropCard(two, "me", "", now).windows,
  only_unweighed: AO.dropSays(AO.dropSum({ seats: [seat(["x"], "≈$", 0, tok(0, 0, 0, 0), 2500)] })).money,
  metered_zero: AO.dropSays(AO.dropSum({ seats: [seat(["x"], "$", 0, tok(0, 0, 0, 0))] })).money,
  mixed_zero: AO.dropSays(AO.dropSum({ seats: [seat(["x"], "$", 0, tok(0, 0, 0, 0)),
    seat(["y"], "≈$", 0, tok(0, 0, 0, 0))] })).money,
}));
"""

READ_PROBE = (
    PROBE.split("const AO = window.AO;")[0].replace(
        'global.fetch = () => Promise.reject(new Error("the probe makes no calls"));', ""
    )
    + """
const AO = window.AO;
const store = {};
global.sessionStorage = { getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); } };
const asked = [];
let fail = new Set();
global.fetch = (u) => {
  asked.push(u);
  if ([...fail].some((f) => u.includes(f))) return Promise.resolve({ ok: false, status: 503, json: () => ({}) });
  const w = u.includes("window=week") ? "week" : "day", t = u.includes("team=") ? "t" : "all";
  const one = { records: ["me"], unit: "≈$", figure: w === "day" ? 1 : 7, tokens: { input: 1 },
    unweighed_tokens: 0, series: [1, 2], seat: `${t}-${w}` };
  return Promise.resolve({ ok: true, json: () => Promise.resolve({ seats: [null, one] }) });
};
(async () => {
  const out = {};
  await AO.dropRead("me", "ao grind", 1000);
  out.asked = asked.slice();
  out.first = AO.dropHeld("me");
  asked.length = 0;
  await AO.dropRead("me", "ao grind", 1000 + AO.DROP_FRESH - 1);
  out.fresh_asked = asked.length;
  fail = new Set(["window=week"]);
  await AO.dropRead("me", "ao grind", 1000 + AO.DROP_FRESH);
  out.partial = AO.dropHeld("me");
  fail = new Set(["/api/spend"]);
  await AO.dropRead("me", "ao grind", 1000 + 3 * AO.DROP_FRESH);
  out.none_at = AO.dropHeld("me").at;
  console.log(JSON.stringify(out));
})();
"""
)


def probe(tmp_path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    f = tmp_path / "drop_probe.js"
    f.write_text(PROBE)
    run = subprocess.run(
        [node, str(f), str(APP)], capture_output=True, text=True, timeout=30, env={**os.environ, "TZ": "UTC"}
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.unit
def test_each_row_sums_its_seats_by_unit_with_tokens_on_every_row(tmp_path):
    """Three rows — this session (its seats by record id), its team, all teams — each today and this week:
    `≈$` and `$` two figures, never one sum; *unweighed* tokens beside, as the Spend page draws them; the
    tokens of every kind summed in the chip's short shape, the kinds on the hover."""
    card = probe(tmp_path)["card"]
    me, team, every = card["rows"]
    assert [me["label"], team["label"], every["label"]] == ["this session", "team ao-grind", "all teams"]
    assert me["day"] == {
        "money": "≈$6.93",
        "tok": "7.4M tok",
        "kinds": "input 1,000 · output 2,000 · cache read 7,000,000 · cache write 397,000",
    }
    assert me["week"]["money"] == "≈$38.02" and me["week"]["tok"] == "39.9M tok"
    # a hundred and up drops the cents, as the Spend page's `money`; the bill is a figure of its own
    assert team["day"]["money"] == "≈$157 · $1.20 + 4.1M tok unweighed"
    assert team["day"]["tok"] == "7.4M tok"
    # a reading with no seats is a zero, not *no reading*
    assert every["week"]["money"] == "≈$0.00" and every["week"]["tok"] == "0 tok"


@pytest.mark.unit
def test_the_windows_and_the_time_and_what_was_never_read(tmp_path):
    """The account's windows as the chip's hover reads them, label, percentage and reset (an unreadable
    reset left off), the account named only when there are two; *as of* the reading's time; a reading the
    page never got is *no reading* (null), and a session with no team has no team row."""
    got = probe(tmp_path)
    assert got["card"]["windows"] == ["week 98% · resets Tue 17:59", "5h 11% · resets Tue 12:29", "bad 3%"]
    assert got["card"]["asof"] == "14:02"
    assert got["two"] == ["a · week 5%", "b · 5h 7%"]
    assert got["teamless"] == [
        ["this session", "≈$6.93", None],
        ["all teams", "≈$157 · $1.20 + 4.1M tok unweighed", None],
    ]
    nothing = got["nothing"]
    assert nothing["asof"] is None and nothing["windows"] == []
    assert all(r["day"] is None and r["week"] is None for r in nothing["rows"])
    assert got["metered_zero"] == "$0.00" and got["mixed_zero"] == "≈$0.00"  # nothing spent, in its own unit
    assert got["only_unweighed"] == "unweighed · 2k tok"  # nothing weighed, the Spend page's shape


@pytest.mark.unit
def test_the_focus_reads_at_each_open_and_draws_the_card_with_the_mark():
    """The wiring: the reading is taken in the socket's `onopen` (the load's first and each reconnect's),
    never in `onclose`; the card is drawn with the mark while it reads *reconnecting…* and goes with it;
    the four reads ask `top=all`; the slot sits before the terminal's wrap, hidden, with §4.5a's hover."""
    js = APP.read_text()
    opened = js[js.index("      ws.onopen = () => {\n") :]
    opened = opened[: opened.index("\n      };\n")]
    assert 'AO.dropRead(id, s.team || "");' in opened
    closed = js[js.index("      ws.onclose = (e) => {\n") :]
    assert "dropRead" not in closed[: closed.index("\n      };\n")]
    assert 'drawDrop(!!(m && m.kind === "reconnecting"))' in js
    assert "/api/spend?window=${w}&top=all" in js
    assert "if (AO.focusUsage) AO.focusUsage();" in js
    html = (UI / "templates" / "focus.html").read_text()
    slot = (
        '<div class="card dropcard hidden" id="fdrop" title="the terminal dropped and retries on its own — these are'
        ' the last figures the page held; the Spend page has the live ones"></div>'
    )
    assert slot in html and html.index(slot) < html.index('id="termwrap"')


@pytest.mark.unit
def test_the_reading_is_kept_and_a_failed_read_keeps_what_was_held(tmp_path):
    """`AO.dropRead`: the team's and All's day and week (the team URL-quoted), each seat kept slim, a null
    seat passed over; a reading under `DROP_FRESH` old is not taken again; a read that fails keeps the
    scope as it was held and the others move; `at` moves only when a read came back."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    f = tmp_path / "read_probe.js"
    f.write_text(READ_PROBE)
    run = subprocess.run([node, str(f), str(APP)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["asked"] == [
        "/api/spend?window=day&top=all&team=ao%20grind",
        "/api/spend?window=day&top=all",
        "/api/spend?window=week&top=all&team=ao%20grind",
        "/api/spend?window=week&top=all",
    ]
    first = got["first"]
    assert first["at"] == 1000 and set(first) == {"at", "team", "all", "usage"}
    assert first["team"]["week"]["seats"] == [
        {"records": ["me"], "unit": "≈$", "figure": 7, "unweighed_tokens": 0, "tokens": {"input": 1}}
    ]
    assert got["fresh_asked"] == 0
    partial = got["partial"]
    assert partial["at"] == 1000 + 30000 and partial["team"]["week"] == first["team"]["week"]
    assert got["none_at"] == partial["at"]
