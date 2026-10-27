"""The Focus terminal tells tmux its grid once per gesture (TD-794, design §4.6 *Attach behaviour with
another client present*): a drag or a put away fires the box's observer once a frame, and each resize
makes the tool repaint over lines tmux keeps. `AO.resizeSender` sends the last grid once the box has been
still, and nothing when tmux already has it. The page's rule runs as itself under node."""

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
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
global.window = {}; global.document = document; global.Event = class { constructor(t) { this.type = t; } };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
// a clock the probe moves: `tick(ms)` runs what is due
let now = 0, seq = 0; const due = new Map();
const timers = { set: (f, ms) => { due.set(++seq, { f, at: now + ms }); return seq; }, clear: (id) => due.delete(id) };
const tick = (ms) => { now += ms; for (const [id, t] of [...due]) if (t.at <= now) { due.delete(id); t.f(); } };
let open = true; const sent = [];
const send = AO.resizeSender((grid) => open && (sent.push(grid.join("x")), true), 150, timers);
const out = {};
// a drag: a grid a frame for half a second, then still
for (let c = 120; c > 90; c--) { send(c, 40); tick(16); }
out.during = sent.slice(); tick(150); out.drag = sent.slice();
// the same grid again (a refit that changed nothing): nothing sent
send(91, 40); tick(200); out.same = sent.slice();
// a closed socket sends nothing, and the grid is tried again on the next change
open = false; send(100, 40); tick(200); open = true; send(100, 40); tick(200); out.closed = sent.slice();
// a grid sent at attach (`mark`) is not sent again, and a pending one is dropped
send(80, 30); send.mark(110, 40); tick(200); send(110, 40); tick(200); out.marked = sent.slice();
// the default timers call `setTimeout` as a browser needs, never as a method of another object
const later = [];
const bound = (self) => { if (self !== undefined) throw new TypeError("Illegal invocation"); };
global.setTimeout = function (f) { "use strict"; bound(this); later.push(f); return later.length; };
global.clearTimeout = function () { "use strict"; bound(this); };
const plain = []; const dflt = AO.resizeSender((grid) => (plain.push(grid.join("x")), true));
dflt(70, 20); later.forEach((f) => f()); out.defaults = plain;
console.log(JSON.stringify(out));
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the terminal's resize is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "resize_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_a_gesture_sends_one_resize_with_its_last_grid_and_an_unchanged_grid_none():
    got = _probe()
    assert got["during"] == []  # nothing while the box still moves
    assert got["drag"] == ["91x40"]  # 30 frames, one send, the final grid
    assert got["same"] == ["91x40"]
    assert got["closed"] == ["91x40", "100x40"]  # not counted as sent while the socket was closed
    assert got["marked"] == ["91x40", "100x40"]  # the attach's grid is tmux's already; the pending one dropped
    assert got["defaults"] == ["70x20"]  # a browser's setTimeout, called unbound


@pytest.mark.unit
def test_the_focus_terminal_sends_its_grid_through_the_sender():
    js = (UI / "static" / "app.js").read_text()
    assert "term.onResize(({ cols, rows }) => sendGrid(cols, rows));" in js
    assert "sendGrid.mark(...grid);" in js  # the grid sent at attach
    assert js.count("JSON.stringify({ resize:") == 2  # the attach's and the sender's, nothing else
