"""A terminal size saved on Settings reaches an open Focus (`AO.setTermLook`, TD-288) and changes how many of the
pane's columns the box shows, never the grid (design §4.6, TD-1919): the terminal draws at the pane's grid, which only
the bridge's `grid` frame sets, so the look's change lays the terminal out again and sends nothing. The look's change
is JavaScript, run as itself under node; that the page sends no grid is read from the source."""

import json
import pathlib
import shutil
import subprocess

import pytest
from conftest import scratch_dir

JS = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui" / "static" / "app.js"

PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el, fonts: { check: () => true } };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
// an open terminal: its grid is the pane's, and its `relayout` is what follows a new cell
const laid = [];
const term = { options: { fontSize: 13, fontFamily: "" }, cols: 100, rows: 22 };
AO.terms.push({ term, relayout: () => laid.push(term.options.fontSize) });
AO.setTermLook({ size: 17 });
const after = { size: term.options.fontSize, grid: [term.cols, term.rows] };
AO.setTermLook({ size: 99 });  // out of range: the default
console.log(JSON.stringify({ after, fallback: term.options.fontSize, laid }));
"""


@pytest.mark.unit
def test_a_saved_size_reaches_an_open_terminal_and_keeps_its_grid():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "look_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(JS)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["after"] == {"size": 17, "grid": [100, 22]}  # the pane's grid, whatever the cell
    assert got["laid"] == [17, 13]  # laid out again at each new cell
    assert got["fallback"] == 13


@pytest.mark.unit
def test_focus_sends_no_grid_and_sizes_the_terminal_by_the_bridges_frame():
    js = JS.read_text()
    start = js.index("const term = new Terminal(")
    body = js[start : js.index("\n  };\n", start)]  # to the end of `AO.focus`, which grows (TD-989, TD-990)
    # no resize message, no `onResize` wiring, no fit addon, no grid on the socket's address
    for gone in ("resize:", "term.onResize(", "FitAddon", "fit.fit(", "?cols="):
        assert gone not in body, gone
    # the terminal is resized by the `grid` frame alone, and only by one that differs from its own
    assert "if (gc !== term.cols || gr !== term.rows) term.resize(gc, gr);" in body
    assert body.count("term.resize(") == 1
    # …and the box's observer sets the view, never a grid
    obs = body[body.index("new ResizeObserver(() => { keeper") :]
    assert "ws.send" not in obs[: obs.index(".observe(")]
