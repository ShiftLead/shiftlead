"""A pinch on the phone's Focus terminal and a swipe on its strip (design §4.5a *a pinch* and *the strip*, §4.5 *What
the terminal's grid does*; TD-003, built by TD-1301): the kept size is this browser's, on its narrow screen alone,
read before the setting and a Settings broadcast and clamped to 9–16 px; the swipe walks the switcher's order."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
from conftest import scratch_dir

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"

pytestmark = pytest.mark.unit

PROBE = """
const fs = require("fs");
const noop = () => {};
let narrow = false;
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const root = el();
root.classList = { toggle: noop, add: noop, remove: noop, contains: (c) => c === "phonefocus" && narrow };
const document = { documentElement: root, body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
global.window = {}; global.document = document;
const mem = {};
global.localStorage = { getItem: (k) => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); } };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const size = () => AO.TERM_OPTS.fontSize;
const out = {};
// the setting alone: 15 on either layout while nothing is kept
narrow = true; AO.setTermLook({ size: 15 }); out.nothingKept = size();
AO.pinchKeep(12);
out.stored = mem["ao.term.pinch"];
AO.setTermLook({ size: 15 }); out.narrowKept = size();                      // the kept size wins on the phone
if (AO.termChan) AO.termChan.onmessage({ data: { size: 14 } }); else AO.setTermLook({ size: 14 });
out.broadcast = size();                                                     // …and over a Save's broadcast
narrow = false; AO.setTermLook({ size: 15 }); out.desktop = size();         // the desktop page keeps the setting
narrow = true;
mem["ao.term.pinch"] = "30"; AO.setTermLook({ size: 15 }); out.high = size();
mem["ao.term.pinch"] = "3"; AO.setTermLook({ size: 15 }); out.low = size();
mem["ao.term.pinch"] = '"x"'; AO.setTermLook({ size: 15 }); out.junk = size();
AO.pinchKeep(20); out.keptHigh = mem["ao.term.pinch"];
AO.pinchKeep(8.6); out.keptLow = mem["ao.term.pinch"];
out.clamp = [AO.pinchClamp(12.4), AO.pinchClamp(12.6), AO.pinchClamp(100), AO.pinchClamp(-1)];
// no size from what is not a finite number: never NaN on the terminal, nothing kept
out.notANumber = [AO.pinchClamp(NaN), AO.pinchClamp(Infinity), AO.pinchClamp("x"), AO.pinchClamp(undefined)];
mem["ao.term.pinch"] = "12"; AO.pinchKeep(NaN); out.keptAfterNaN = mem["ao.term.pinch"];
// the strip's finger: one alone, found by its identifier at the lift; a gesture a second finger joined is none
const T = (id, x, y) => ({ identifier: id, clientX: x, clientY: y });
const E = (touches, changed) => ({ touches, changedTouches: changed || [] });
const track = (steps) => {
  const k = AO.swipeTrack(); let got;
  for (const [kind, ...a] of steps) got = k[kind](E(...a));
  return got;
};
out.track = {
  one: track([["start", [T(1, 200, 20)]], ["move", [T(1, 150, 22)]], ["end", [], [T(1, 140, 24)]]]),
  second: track([["start", [T(1, 200, 20)]], ["start", [T(1, 200, 20), T(2, 100, 20)]],
    ["end", [T(2, 100, 20)], [T(1, 140, 20)]]]),
  secondThenLift: track([["start", [T(1, 200, 20)]], ["start", [T(1, 200, 20), T(2, 100, 20)]],
    ["end", [T(2, 100, 20)], [T(1, 140, 20)]], ["end", [], [T(2, 30, 20)]]]),
  seenInMove: track([["start", [T(1, 200, 20)]], ["move", [T(1, 180, 20), T(2, 90, 20)]],
    ["end", [], [T(1, 140, 20)]]]),
  otherFinger: track([["start", [T(1, 200, 20)]], ["end", [], [T(7, 100, 20)]]]),
  fresh: (() => {
    const k = AO.swipeTrack();
    k.start(E([T(1, 200, 20)])); k.start(E([T(1, 200, 20), T(2, 100, 20)])); k.end(E([], [T(1, 1, 1), T(2, 1, 1)]));
    k.start(E([T(3, 300, 20)])); return k.end(E([], [T(3, 250, 20)]));
  })(),
};
// the swipe: the switcher's order, the screen's edge, mostly sideways
const rows = [
  { id: "i", name: "idle-one", state: "idle" }, { id: "w", name: "work", state: "working" },
  { id: "n2", name: "needs-b", state: "needs-you" }, { id: "n1", name: "needs-a", state: "needs-you" },
  { id: "c", name: "closed-one", state: "closed" },
];
const sw = (here, dx, dy, x0) => AO.swipeTarget(rows, here, dx, dy, x0 == null ? 180 : x0, 375);
out.swipe = {
  next: sw("n2", -50, 5), prev: sw("n2", 50, 5), fromFirst: sw("n1", 50, 0), last: sw("c", -60, 0),
  walk: [sw("n1", -45, 0), sw("n2", -45, 0), sw("w", -45, 0), sw("i", -45, 0)],
  short: sw("n2", -39, 0), steep: sw("n2", -50, 30), leftEdge: sw("n2", -50, 0, 10), rightEdge: sw("n2", 50, 0, 365),
};
console.log(JSON.stringify(out));
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the pinch's and the swipe's rules are JavaScript")
    probe = scratch_dir() / "pinch_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_kept_size_wins_over_the_setting_and_a_broadcast_on_this_browsers_narrow_screen_only():
    got = _probe()
    assert got["nothingKept"] == 15
    assert got["stored"] == "12"  # this browser's localStorage, never settings.yml
    assert got["narrowKept"] == 12 and got["broadcast"] == 12
    assert got["desktop"] == 15  # the same browser's desktop page keeps the setting


def test_the_kept_size_is_clamped_to_9_to_16_px():
    got = _probe()
    assert got["high"] == 16 and got["low"] == 9 and got["junk"] == 15  # junk is no size: the setting
    assert got["keptHigh"] == "16" and got["keptLow"] == "9"
    assert got["clamp"] == [12, 13, 16, 9]
    assert got["notANumber"] == [None, None, None, None] and got["keptAfterNaN"] == "12"


def test_the_strips_swipe_reads_one_finger_by_its_identifier_and_no_gesture_a_second_finger_joined():
    t = _probe()["track"]
    assert t["one"] == {"dx": -60, "dy": 4, "x0": 200}
    assert t["second"] is None and t["secondThenLift"] is None and t["seenInMove"] is None
    assert t["otherFinger"] is None  # the lift of a finger that is not the one that went down
    assert t["fresh"] == {"dx": -50, "dy": 0, "x0": 300}  # once every finger lifted, the next one swipes again


def test_the_swipe_walks_the_switchers_order_and_never_from_the_edge():
    s = _probe()["swipe"]
    # the switcher's order: needs you (by name), working, idle, then the rest
    assert s["next"] == "w" and s["prev"] == "n1" and s["fromFirst"] is None and s["last"] is None
    assert s["walk"] == ["n2", "w", "i", "c"]
    # under 40 px, mostly up or down, or from the screen's edge (the browser's back and forward): nothing
    assert s["short"] is None and s["steep"] is None and s["leftEdge"] is None and s["rightEdge"] is None


def test_the_pinch_is_the_terminals_on_a_phone_and_sends_one_grid_when_the_fingers_lift():
    css = (UI / "static" / "app.css").read_text()
    assert (
        "html.phonefocus .termbox, html.phonefocus .termbox .xterm, html.phonefocus .termbox .xterm-viewport, "
        "html.phonefocus .termbox .xterm-screen { touch-action: none; }"
    ) in css
    js = (UI / "static" / "app.js").read_text()
    focus = js[js.index("  AO.focus = function") :]
    pinch = focus[focus.index("    let pinch = null;") : focus.index("    let noteTimer = null;")]
    # two fingers, on a phone; their touchmove's default prevented (iOS's page zoom)
    assert "if (!phone.narrow() || e.targetTouches.length !== 2) return;" in pinch
    assert pinch.count("e.preventDefault();") >= 2
    # drawn as they move, the grid untouched until they lift: then kept, fit once, and the note
    assert "AO.pinchKeep(size);" in pinch and "fit.fit();" in pinch
    assert "pinchNote(`${size} px · ${term.cols} columns`);" in pinch
    assert "new ResizeObserver(() => { if (!phone.opened() && !pinch) fit.fit(); })" in focus
    # a crossing of the narrow query draws the size its layout reads
    relaid = focus[focus.index("    phone.relaid(() => {") :]
    relaid = relaid[: relaid.index("\n    });\n")]
    # only this terminal's size, and no grid under a sheet (its close refits)
    assert "AO.TERM_OPTS.fontSize = size; term.options.fontSize = size;" in relaid
    assert "if (!phone.opened()) fit.fit();" in relaid and "AO.setTermLook" not in relaid
    # the pinch's move sets no size it could not read
    assert "if (size != null && size !== pinch.size)" in focus
