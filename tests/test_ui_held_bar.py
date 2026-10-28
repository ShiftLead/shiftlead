"""The top bar is held (design §4.5 *Browser mechanics* *The top bar is held*, TD-1187, built by TD-1192): sticky on
a wide screen; on a phone away while the page scrolls down and back on a scroll up, by `AO.barAway`'s four rules;
`--barh` for the scroll padding and every rail's `top`. The page's rules run as themselves under node."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
from conftest import scratch_dir

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"

PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const cls = () => { const set = new Set(); return { set, contains: (c) => set.has(c), add: (c) => set.add(c),
  remove: (c) => set.delete(c), toggle: (c, on) => (on ? set.add(c) : set.delete(c)) }; };
// the bar, + New ▾ and the page: what `holdBar` reads
let focusVisible = false;
const on = {}, barOn = {}, mqOn = {};
const bar = { offsetHeight: 107, classList: cls(), addEventListener: (k, f) => { barOn[k] = f; },
  querySelector: (s) => (s === ":focus-visible" && focusVisible ? {} : null) };
const newmenu = { open: false };
const props = {};
const root = { dataset: {}, scrollHeight: 3000, style: { setProperty: (k, v) => { props[k] = v; } } };
const document = { documentElement: root, body: el(), addEventListener: noop, createElement: el,
  querySelectorAll: () => [], querySelector: (s) => (s === ".topbar" ? bar : s === "#newmenu" ? newmenu : null) };
const mq = { matches: true, addEventListener: (k, f) => { mqOn[k] = f; } };
let observed = null;
global.window = { scrollY: 0, innerHeight: 844, matchMedia: () => mq, addEventListener: (k, f) => { on[k] = f; },
  ResizeObserver: class { constructor(f) { this.f = f; } observe(t) { observed = t; this.f(); } } };
global.document = document; global.Event = class { constructor(t) { this.type = t; } };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
let frames = [];
global.requestAnimationFrame = (f) => frames.push(f);
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const out = {};
const B = AO.barAway;
out.rules = {
  held: B(200, 900, 107, true, true), top: B(100, 111, 107, false, false), top_edge: B(100, 112, 107, false, false),
  down: B(300, 305, 107, false, false), down_4: B(300, 304, 107, false, false),
  shown_up: B(300, 250, 107, false, false),
  up: B(800, 795, 107, true, false), up_4: B(800, 796, 107, true, false), away_down: B(800, 900, 107, true, false),
};
// wired: the page's own listeners, as a phone scrolls
const away = () => bar.classList.contains("away");
const scroll = (y) => { window.scrollY = y; on.scroll(); return away(); };
out.wired = { barh: props["--barh"], observed: observed === bar, passive: typeof on.scroll };
const run = [];
for (let y = 0; y <= 130; y += 2) run.push(scroll(y));  // a slow touch scroll down, 2 px a step
out.slow = { first_away: 2 * run.indexOf(true), at_130: away() };
const back = [];
for (let y = 130; y >= 120; y -= 2) back.push(scroll(y));  // the reversal: 4 px up keeps it away, 6 px brings it back
out.reversal = back;
scroll(1000); scroll(1010);  // away again, mid-page
const ceiling = root.scrollHeight - window.innerHeight;  // 2156
scroll(ceiling);  // iOS's bounce at the foot
out.bounce = [scroll(ceiling + 60), scroll(ceiling + 10), scroll(ceiling)];
newmenu.open = true; out.menu_open = scroll(ceiling - 300); newmenu.open = false;
out.menu_shut_down = [scroll(ceiling - 296), scroll(ceiling - 290)];
focusVisible = true; barOn.focusin(); out.tab_in = away();
focusVisible = false; barOn.focusout(); out.focusout_now = away(); frames.forEach((f) => f()); frames = [];
out.after_tab = [scroll(ceiling - 288), scroll(ceiling - 285)];
mqOn.change(); out.crossed = away();
mq.matches = false; out.wide = [scroll(1500), scroll(2000)];
console.log(JSON.stringify(out));
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the held bar is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "held_bar_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_bar_away_rules_a_to_d_first_match_wins_and_every_threshold_strict():
    r = _probe()["rules"]
    assert r["held"] == {"away": False, "anchorY": 900}, "(a) held: shown, whatever the scroll"
    assert r["top"] == {"away": False, "anchorY": 111}, "(b) within the bar's height + 4 of the top: shown, before (c)"
    assert r["top_edge"] == {"away": True, "anchorY": 112}, "(b) is strict: at 112 > 107 + 4, (c) sends it away"
    assert r["down"] == {"away": True, "anchorY": 305}, "(c) shown, more than 4 px down: away"
    assert r["down_4"] == {"away": False, "anchorY": 300}, "(c) 4 px is not more than 4"
    assert r["shown_up"] == {"away": False, "anchorY": 250}, "(c) shown, the anchor follows the lowest point"
    assert r["up"] == {"away": False, "anchorY": 795}, "(d) away, more than 4 px up: back"
    assert r["up_4"] == {"away": True, "anchorY": 800}, "(d) 4 px is not more than 4"
    assert r["away_down"] == {"away": True, "anchorY": 900}, "(d) away, the anchor follows the highest point"


@pytest.mark.unit
def test_a_phone_scroll_sends_the_bar_away_and_brings_it_back_by_the_clamped_distance():
    got = _probe()
    assert got["wired"] == {"barh": "107px", "observed": True, "passive": "function"}, "--barh is the bar's height"
    # a slow run of 2 px steps adds up: (b) holds the anchor at 110, and 116 is the first step more than 4 px past it
    assert got["slow"] == {"first_away": 116, "at_130": True}
    assert got["reversal"] == [True, True, True, False, False, False], "4 px up keeps it away; 6 px brings it back"
    assert got["bounce"] == [True, True, True], "the clamp's ceiling: a bounce past the foot moves nothing"
    assert got["menu_open"] is False, "+ New ▾ open holds the bar"
    assert got["menu_shut_down"] == [False, True], "once shut, the next scroll down of more than 4 px lets it go"
    assert got["tab_in"] is False, "a Tab into a bar that is away brings it back"
    assert got["focusout_now"] is False, "read a frame after the focus leaves, never during focusout"
    assert got["after_tab"] == [False, True], "a Tab out lets it go on the next scroll down of more than 4 px"
    assert got["crossed"] is False, "a window that crosses 720 px shows the bar"
    assert got["wide"] == [False, False], "a wide screen: decide returns at once, the bar stays"


@pytest.mark.unit
def test_the_stylesheet_holds_the_bar_and_the_rails_ride_under_it():
    css = (UI / "static" / "app.css").read_text()
    assert "--barh: 48px;" in css.split(":root {", 1)[1].split("}", 1)[0]
    topbar = css.split("\n.topbar {", 1)[1].split("}", 1)[0]
    assert "position: sticky; top: 0; z-index: 30;" in topbar
    assert "html { scroll-padding-top: calc(var(--barh) + 8px); }" in css
    assert "html:has(.topbar.away) { scroll-padding-top: 8px; }" in css
    assert "html:has(body.popped) { --barh: 0px; }" in css
    assert ".rail { position: sticky; top: calc(var(--barh) + 12px);" in css
    phone = css.split("@media (max-width: 720px) {", 1)[1].split("\n}\n", 1)[0]
    assert ".topbar.away { transform: translateY(-100%); transition: transform .15s ease-out; }" in phone
    assert "@media (prefers-reduced-motion: reduce) { .topbar.away { transition: none; } }" in css
    js = (UI / "static" / "app.js").read_text()
    toggle = js.split('document.addEventListener("toggle", (ev) => {', 1)[1]
    assert toggle.lstrip().startswith("AO.barDecide();"), "the toggle reads the bar before any menu is placed"
    assert "fitUsage();\n  AO.holdBar();" in js
