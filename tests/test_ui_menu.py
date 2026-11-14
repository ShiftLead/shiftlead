"""A *more ▾* / *Snooze* menu escapes the box it sits in (TD-121): the card keeps its one height and
its `overflow: hidden`, so the menu is drawn fixed to the viewport and placed from its summary's rect
when it opens. The placement is JavaScript, run as itself under node."""

import json
import pathlib
import re
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
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const P = window.AO.placeMenu;
const r = (left, top, w, h) => ({ left, top, right: left + w, bottom: top + h });
console.log(JSON.stringify({
  below: P(r(500, 100, 24, 24), 170, 200, 1200, 800),
  above: P(r(500, 700, 24, 24), 170, 200, 1200, 800),
  no_room_either: P(r(500, 150, 24, 24), 170, 700, 1200, 800),
  left_edge: P(r(20, 100, 24, 24), 170, 200, 1200, 800),
  right_edge: P(r(1190, 100, 24, 24), 170, 200, 1200, 800),
}));
"""


@pytest.mark.unit
def test_a_menu_is_placed_under_its_button_and_kept_on_screen():
    """Right-aligned under the summary; above it where the space below is short and above is not;
    below when neither fits; never past either side of the viewport (8px in)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "menu_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["below"] == {"top": 128, "left": 354}
    assert got["above"] == {"top": 496, "left": 354}
    assert got["no_room_either"] == {"top": 178, "left": 354}
    assert got["left_edge"] == {"top": 128, "left": 8}
    assert got["right_edge"] == {"top": 128, "left": 1022}


@pytest.mark.unit
def test_the_menu_is_fixed_and_the_card_still_clips():
    """The card's one height (TD-095) stands — `.sc` keeps `overflow: hidden` — and the menu no
    longer lives inside that box: fixed, placed by the page on `toggle`, re-placed on scroll and resize,
    and reopened on the fresh card when a delta redraws the card it was open on."""
    css = (UI / "static" / "app.css").read_text()
    assert re.search(r"^\.sc \{[^}]*overflow: hidden", css, re.M)
    menu = re.search(r"^details\.more \.menu \{([^}]*)\}", css, re.M).group(1)
    assert "position: fixed" in menu and "position: absolute" not in menu
    js = (UI / "static" / "app.js").read_text()
    assert 'document.addEventListener("toggle"' in js and 'document.addEventListener("scroll", placeOpen, true)' in js
    assert 'menu = !!$("details.more[open]", old)' in js and "if (d) d.open = true;" in js


OUTSIDE_PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
// a page of nodes: each a `details` (a menu: class `more`; a fold: class `fold`) holding a summary and an item
const nodes = [];
const node = (cls, parent) => {
  const n = { cls, parent, open: false, focused: 0, focus() { this.focused++; document.activeElement = this; },
    contains(t) { for (let x = t; x; x = x.parent) if (x === this) return true; return false; },
    querySelector(sel) {
      return sel === "summary" ? nodes.find((k) => k.parent === this && k.cls === "summary") : null;
    } };
  nodes.push(n); return n;
};
const listeners = [];
const document = { documentElement: el(), body: el(), activeElement: null, createElement: el,
  querySelector: () => null,
  querySelectorAll: (sel) => sel === "details.more[open]" ? nodes.filter((n) => n.cls === "more" && n.open) : [],
  addEventListener: (type, fn, capture) => listeners.push({ type, fn, capture: !!capture }) };
document.activeElement = document.body;
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const page = node("page", null), menu = node("more", page), summary = node("summary", menu), item = node("item", menu);
const fold = node("fold", page), inFold = node("item", fold), composer = node("textarea", page);
const out = {};
menu.open = true; fold.open = true;
out.inside = [AO.menuPress(item), menu.open];
out.summary = [AO.menuPress(summary), menu.open];
out.outside = [AO.menuPress(page), menu.open, fold.open];
menu.open = true;
out.in_fold = [AO.menuPress(inFold), menu.open, fold.open];
menu.open = true; document.activeElement = item;
out.esc_in_menu = [AO.menuEsc({ key: "Escape" }), menu.open, document.activeElement === summary];
menu.open = true; document.activeElement = composer;
const ev = { key: "Escape" };
out.esc_in_composer = [AO.menuEsc(ev), menu.open, document.activeElement === composer, ev.aoMenuClosed === true];
menu.open = true; document.activeElement = document.body;
out.other_key = [AO.menuEsc({ key: "x" }), menu.open];
out.esc_on_body = [AO.menuEsc({ key: "Escape" }), menu.open, document.activeElement === summary];
out.esc_none_open = AO.menuEsc({ key: "Escape" });
out.pointerdown_capture = listeners.some((l) => l.type === "pointerdown" && l.capture);
// the wiring itself (TD-1339): an event goes through the page's own capturing listeners, as a browser sends it
// down, each listener's throw kept to itself (a browser reports it and goes on to the next)
const fire = (type, ev) => {
  for (const l of listeners.filter((x) => x.type === type && x.capture)) {
    try { l.fn(ev); } catch (e) { /* not ours */ }
  }
  return ev;
};
const key = (k) => ({ key: k, prevented: false, preventDefault() { this.prevented = true; } });
menu.open = true; fold.open = true;
fire("pointerdown", { target: item });
out.fired_inside = menu.open;
fire("pointerdown", { target: page });
out.fired_outside = [menu.open, fold.open];
menu.open = true; document.activeElement = item;
out.fired_esc_in_menu = [fire("keydown", key("Escape")).prevented, menu.open, document.activeElement === summary];
menu.open = true; document.activeElement = composer;
out.fired_esc_in_composer = [fire("keydown", key("Escape")).prevented, menu.open, document.activeElement === composer];
console.log(JSON.stringify(out));
"""


@pytest.mark.unit
def test_a_press_outside_an_open_menu_or_esc_closes_it_and_a_fold_stays_open():
    """§4.5a *every page: a pop-up menu* (TD-1337): one page-wide `pointerdown`, caught on the way down,
    closes an open `details.more` the press is not inside; a press inside it or on its own summary is the
    menu's; a fold is no menu and stays open. `Esc` closes it wherever focus is, focus back on its button
    only from the menu or no control — a composer keeps focus and the key."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "menu_outside_probe.js"
    probe.write_text(OUTSIDE_PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["inside"] == [False, True]
    assert got["summary"] == [False, True]
    assert got["outside"] == [True, False, True]
    assert got["in_fold"] == [True, False, True]
    assert got["esc_in_menu"] == [True, False, True]
    assert got["esc_in_composer"] == [False, False, True, True]
    assert got["other_key"] == [False, True]
    assert got["esc_on_body"] == [True, False, True]
    assert got["esc_none_open"] is False
    assert got["pointerdown_capture"] is True
    # the listeners themselves, fired (TD-1339): a press inside leaves the menu open, one outside closes it and
    # not the fold; `Esc` closes it and is taken (`preventDefault`) from the menu, and goes on from a composer
    assert got["fired_inside"] is True
    assert got["fired_outside"] == [False, True]
    assert got["fired_esc_in_menu"] == [True, False, True]
    assert got["fired_esc_in_composer"] == [False, False, True]


@pytest.mark.unit
def test_an_esc_that_closed_a_menu_presses_no_page_key():
    """The message page's `Esc` is Back (§4.5a **keys**): an `Esc` that closed a *Snooze* menu there closes the
    menu alone (TD-1337's review) — the keys table returns on the mark `AO.menuEsc` puts on the event."""
    js = (UI / "static" / "app.js").read_text()
    assert "ev.aoMenuClosed = true;" in js
    keys = js[js.index("const page = AO.keyPage(location.pathname);") :]
    assert keys.index("if (ev.aoMenuClosed) return;") < keys.index("const name = AO.keyName(ev);")


ROLLUP_PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const docL = [], boxL = [];
const focusable = (extra) =>
  Object.assign({ focused: 0, focus() { this.focused++; document.activeElement = this; } }, extra);
// one rollup row with its *more* button and the menu after it; the box's and the document's listeners kept
const menu = focusable({ hidden: true, querySelector: () => null, querySelectorAll: () => [],
  contains(t) { return t === this; }, parentElement: { contains: () => false } });
const row = { dataset: { row: "team:t" } };
const btn = focusable({ dataset: { menu: "more" }, isConnected: true, nextElementSibling: menu, attrs: {},
  setAttribute(k, v) { this.attrs[k] = v; }, closest: (s) => (s === "[data-menu]" ? btn : s === "tr" ? row : null) });
const box = { addEventListener: (type, fn) => boxL.push({ type, fn }) };
const document = { documentElement: el(), body: focusable({}), activeElement: null, createElement: el,
  querySelector: () => null, querySelectorAll: () => [],
  addEventListener: (type, fn, capture) => docL.push({ type, fn, capture: !!capture }) };
document.activeElement = document.body;
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const wiredBefore = docL.length;
window.AO.rollupWire(box);
const fire = (list, type, ev) => { for (const l of list.filter((x) => x.type === type)) l.fn(ev); return ev; };
const press = () => fire(boxL, "click", { target: btn, preventDefault: noop });
const key = (k) => ({ key: k, target: document.activeElement, preventDefault: noop, stopPropagation: noop });
const out = { wired: [boxL.map((l) => l.type).sort(), docL.slice(wiredBefore).map((l) => l.type).sort()] };
press();
out.opened = [menu.hidden, btn.attrs["aria-expanded"]];
document.activeElement = document.body; btn.focused = 0;
fire(docL.slice(wiredBefore), "keydown", key("x"));
out.other_key = menu.hidden;
fire(docL.slice(wiredBefore), "keydown", key("Escape"));
out.esc_on_body = [menu.hidden, btn.attrs["aria-expanded"], btn.focused, document.activeElement === btn];
press();
const composer = focusable({});
document.activeElement = composer; btn.focused = 0;
fire(docL.slice(wiredBefore), "keydown", key("Escape"));
out.esc_in_composer = [menu.hidden, btn.attrs["aria-expanded"], btn.focused, document.activeElement === composer];
console.log(JSON.stringify(out));
"""


@pytest.mark.unit
def test_esc_with_focus_outside_the_rollup_menu_closes_it():
    """§4.5a *every page: a pop-up menu* (TD-1337), the Org rollup's own road (TD-1830): with a row's menu
    opened by a press, the document's `keydown` closes it on `Esc` from outside the menu — focus back on its
    button from no control, kept by a composer — and on no other key. The Org page's init wires its box
    through `AO.rollupWire`, which the probe calls with a fake box."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "rollup_esc_probe.js"
    probe.write_text(ROLLUP_PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["wired"] == [["click", "keydown"], ["click", "keydown"]]
    assert got["opened"] == [False, "true"]
    assert got["other_key"] is False
    assert got["esc_on_body"] == [True, "false", 1, True]
    assert got["esc_in_composer"] == [True, "false", 0, True]
    js = (UI / "static" / "app.js").read_text()
    org = js[js.index("AO.org = function () {") :]
    assert "if (rollupBox) AO.rollupWire(rollupBox);" in org[: org.index("\n  };\n")]
