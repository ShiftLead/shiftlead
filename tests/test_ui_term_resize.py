"""The Focus terminal draws at the pane's grid, not at its box's (design §4.6 *Attach behaviour with another client
present*, TD-1919): a box shorter than the grid shows a run of its rows — the box-height run ending at the lower of the
cursor's row and the last row with text (`AO.viewStart`) — and the view's keep (`AO.viewKeep`) holds the rows it had
from its own move, a scroll or a jump until a key, a box change, a `grid` frame or a settled change of the cursor's row.
The wheel, a drag and a page move the view within the grid first and send only the rest. The page's rules run as
themselves under node."""

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
const out = {};
// the run shown, with no keep: a fresh shell's prompt at its top, a full screen, the cursor above the last text, a box
// as tall as the grid
out.start = [AO.viewStart(3, 3, 10, 40), AO.viewStart(39, 39, 10, 40), AO.viewStart(10, 39, 10, 40),
  AO.viewStart(5, 30, 10, 40), AO.viewStart(39, 39, 40, 40), AO.viewStart(39, 39, 50, 40)];
out.rows = [AO.boxRows(200, 0, 17), AO.boxRows(10, 0, 17), AO.boxRows(212, 12, 20)];
// the scroll offset of a run: the top row shows the gap; a run below it starts at its row past the terminal's border
out.scroll = [AO.viewScroll(0, 20, 6), AO.viewScroll(30, 20, 6), AO.viewScroll(30, 20, 0), AO.viewScroll(7, 17.5, 4)];
out.page = [AO.pageRows(10, 40), AO.pageRows(1, 40), AO.pageRows(40, 40)];
out.axis = [AO.touchAxis(3, 9), AO.touchAxis(12, 4), AO.touchAxis(4, -12), AO.touchAxis(-10, 10)];
out.grid = [AO.gridOf({ width: 812, height: 412 }, { x: 12, y: 12 }, { width: 8, height: 20 }),
  AO.gridOf({ width: 0, height: 0 }, { x: 12, y: 12 }, { width: 8, height: 20 }),
  AO.gridOf({ width: 812, height: 412 }, { x: 0, y: 0 }, null)];
out.fits = [AO.gridFits([20, 5]), AO.gridFits([500, 200]), AO.gridFits([19, 40]), AO.gridFits([100, 201])];
// a short shell paged up: nothing above the top row to move through, so the page goes to tmux and the keep holds the
// rows, its history passing through them (the cursor kept on its row by copy mode)
let k = AO.viewKeep();
k.frame(3, true, 0, 30);
out.short = { sent: k.move(-9, 0), keeping: k.keeping(), tops: [k.frame(3, true, 0, 30), k.frame(3, false, 0, 30)] };
// a full screen, the box ten rows: a scroll first moves the view up through the grid, then goes to tmux; at tmux's
// history top the grid's top rows show
k = AO.viewKeep(); k.frame(39, true, 30, 30);
out.full = { first: k.move(-9, 30), top1: k.frame(39, true, 30, 30) };
out.full.second = k.move(-30, 30); out.full.top2 = k.frame(39, true, 30, 30);
out.full.down = k.move(5, 30); out.full.top3 = k.frame(39, false, 30, 30);
out.full.past = k.move(40, 30); out.full.top4 = k.frame(39, false, 30, 30);
// …then cleared from the composer: the cursor's row, read the same on two frames, releases the keep
out.cleared = [k.frame(0, true, 0, 30), k.keeping(), k.frame(0, true, 0, 30), k.keeping()];
// a keep while the pane streams: a row that moves between two socket messages of one redraw releases nothing, and a
// change is measured against the row settled when the keep started
k = AO.viewKeep(); k.frame(39, true, 30, 30); k.move(-5, 30); k.frame(39, true, 30, 30); k.frame(39, true, 30, 30);
const stream = [];
for (const r of [38, 39, 37, 39, 38, 39]) stream.push(k.frame(r, true, 30, 30));
out.stream = { tops: stream, keeping: k.keeping(), unsettled: k.unsettled(39) };
k.frame(20, true, 30, 30); out.stream.moved_once = k.keeping();
k.frame(20, true, 30, 30); out.stream.moved = k.keeping();
// a downward move while no keep stands sends its lines and starts none
k = AO.viewKeep(); k.frame(39, true, 30, 30);
out.down = { sent: k.move(4, 30), keeping: k.keeping() };
// a jump in a ten-row box on a forty-row grid: a history row lands at the top (row 0); one on the live screen above the
// clamp is the top row shown; one inside the grid's last rows as near the top as they allow; a keep anew, its row the
// answer's cursor
k = AO.viewKeep();
out.jump = [k.land(0, 39, 30), k.land(12, 39, 30), k.land(35, 39, 30)];
out.jump_keeps = [k.frame(39, true, 30, 30), k.frame(39, false, 30, 30), k.keeping()];
// a jump within a standing keep keeps the landed row; a miss (`release`) ends it
k.move(-3, 30); out.jump_again = k.land(7, 39, 30); out.jump_again_top = k.frame(39, true, 30, 30);
k.release(); out.miss = [k.keeping(), k.frame(39, true, 30, 30)];
// a jump's settled row is the answer's: the cursor reading another row on two frames releases it
k.land(5, 20, 30); k.frame(21, true, 30, 30); out.jump_moved = [k.keeping(), (k.frame(21, true, 30, 30), k.keeping())];
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
def test_the_run_shown_the_rows_the_page_and_the_box_grid():
    got = _probe()
    assert got["start"] == [0, 30, 10, 5, 0, 0]  # the cursor's row never above the run
    assert got["rows"] == [11, 1, 10]
    assert got["page"] == [9, 1, None]
    assert got["scroll"] == [0, 606, 600, 127]  # never a part of the row above the run (TD-1947)
    assert got["axis"] == [None, "x", "y", "y"]
    assert got["grid"] == [[100, 20], None, None]
    assert got["fits"] == [True, True, False, False]


@pytest.mark.unit
def test_a_short_shell_paged_up_shows_its_history_through_the_rows_it_had():
    got = _probe()
    assert got["short"] == {"sent": {"dir": "up", "lines": 9}, "keeping": True, "tops": [0, 0]}


@pytest.mark.unit
def test_a_scroll_moves_the_view_through_the_grid_first_and_a_clear_releases_the_keep():
    full = _probe()["full"]
    assert full["first"] is None and full["top1"] == 21  # within the grid: nothing sent
    assert full["second"] == {"dir": "up", "lines": 9} and full["top2"] == 0  # the rest to tmux; the top rows show
    assert full["down"] is None and full["top3"] == 5  # back down within the grid
    assert full["past"] == {"dir": "down", "lines": 15} and full["top4"] == 30  # past the run it would show: sent
    assert _probe()["cleared"] == [30, True, 0, False]  # one frame's reading releases nothing; two do


@pytest.mark.unit
def test_a_keep_holds_while_the_pane_streams_against_its_settled_row():
    stream = _probe()["stream"]
    assert stream["tops"] == [25] * 6 and stream["keeping"] is True
    assert stream["moved_once"] is True and stream["moved"] is False


@pytest.mark.unit
def test_a_downward_move_with_no_keep_sends_its_lines_and_starts_none():
    assert _probe()["down"] == {"sent": {"dir": "down", "lines": 4}, "keeping": False}


@pytest.mark.unit
def test_a_jump_lands_on_the_top_row_shown_and_keeps_it():
    got = _probe()
    assert got["jump"] == [0, 12, 30]
    assert got["jump_keeps"] == [30, 30, True]
    assert got["jump_again"] == 7 and got["jump_again_top"] == 7
    assert got["miss"] == [False, 30]
    assert got["jump_moved"] == [True, False]
