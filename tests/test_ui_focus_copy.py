"""TD-1267: Copy's notes in the Focus pane (design §4.6 *A selection is one screen, and a copy is its rows*,
§4.5a *Copy / Paste* and *copy on select*) — the drag's edge mark, the edge test, the note's words and the
page-load flag of the first copy of several rows, each a pure function of `app.js` run under node."""

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
global.window = {}; global.document = { documentElement: el(), body: el(), querySelector: () => null,
  querySelectorAll: () => [], addEventListener: noop, createElement: el };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
// the mark over a run of events: each step's mark and what a release fired
const marks = (evs) => {
  let m = null;
  return evs.map((ev) => { const r = AO.edgeMark(m, ev); m = r.mark; return [m, r.fire]; });
};
const down = { type: "down", shift: false }, shift = { type: "down", shift: true };
const move = (edge) => ({ type: "move", edge }), up = (moved) => ({ type: "up", moved });
const rect = { top: 100, bottom: 500 };
// copies through `AO.copyWith`, each a toast's text, `ok` and clock, and the flag after it
const copies = async (runs) => {
  const state = { firstFree: true }, out = [];
  for (const [text, edge, transcript, refuse] of runs) {
    const seen = [];
    await AO.copyWith({ text, edge, transcript, state,
      write: () => (refuse ? Promise.reject(new Error("no")) : Promise.resolve()),
      toast: (t, ok, href, wait, sticky, ms) => seen.push([t, !!ok, ms || null]) });
    out.push([...seen, state.firstFree]);
  }
  return out;
};
(async () => {
  console.log(JSON.stringify({
    pastEdge: [AO.pastEdge(84, rect, 16), AO.pastEdge(40, rect, 16), AO.pastEdge(516, rect, 16),
      AO.pastEdge(600, rect, 16), AO.pastEdge(85, rect, 16), AO.pastEdge(515, rect, 16), AO.pastEdge(300, rect, 16)],
    crossed: marks([down, move("bottom"), move(null), move("top"), up(true), up(true)]),
    reset: marks([down, move("top"), down, up(true)]),
    shifted: marks([down, move("top"), shift, move("bottom"), up(true)]),
    unmoved: marks([down, move("top"), up(false)]),
    noDrag: marks([move("top"), up(true)]),
    notes: {
      edge: AO.copyNote({ edge: "top", multi: true, flagFree: true, transcript: true }),
      edgeShell: AO.copyNote({ edge: "bottom", transcript: false }),
      first: AO.copyNote({ multi: true, flagFree: true, transcript: true }),
      spent: AO.copyNote({ multi: true, flagFree: false, transcript: true }),
      shell: AO.copyNote({ multi: true, flagFree: true, transcript: false }),
      oneRow: AO.copyNote({ multi: false, flagFree: true, transcript: true }),
    },
    // one row; then several rows twice; the first-copy note once
    plain: await copies([["one row", null, true], ["a\\nb", null, true], ["c\\nd", null, true]]),
    // a refused write of several rows draws no note and spends nothing; the next one carries it
    refused: await copies([["a\\nb", null, true, true], ["a\\nb", null, true]]),
    // the edge and several rows: the edge's note, and the first-copy note left for the next copy of several rows
    edgeFirst: await copies([["a\\nb", "top", true], ["a\\nb", null, true]]),
    // the edge's note on a refused write too; no Transcript: the shell's edge note, and no first-copy note
    edgeRefused: await copies([["a\\nb", "bottom", true, true]]),
    shell: await copies([["a\\nb", "top", false], ["a\\nb", null, false], ["a\\nb", null, true]]),
  }));
})().catch((e) => { console.error(e); process.exit(1); });
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the notes are JavaScript, and nothing else runs them")
    probe = scratch_dir() / "copy_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


EDGE = "the selection stops at the screen's edge; Transcript has the whole conversation"
EDGE_SHELL = "the selection stops at the screen's edge: copy a screen at a time"
FIRST = "as the screen's rows; Transcript has wrapped lines whole"
BLOCKED = "clipboard blocked (needs https or localhost)"


@pytest.mark.unit
def test_past_an_edge_is_a_row_or_more_above_the_top_or_below_the_bottom():
    # a row (16 px) or more beyond the top or the bottom; inside one row of either edge, or within the screen, none
    assert _probe()["pastEdge"] == ["top", "top", "bottom", "bottom", None, None, None]


@pytest.mark.unit
def test_the_drags_mark_is_set_by_a_crossing_and_fired_once_by_the_release():
    got = _probe()
    drag = {"drag": True, "edge": None}
    off = {"drag": False, "edge": None}
    # a crossing sets, a return keeps, the other edge replaces; the release fires it once and clears
    assert got["crossed"] == [
        [drag, None],
        [{"drag": True, "edge": "bottom"}, None],
        [{"drag": True, "edge": "bottom"}, None],
        [{"drag": True, "edge": "top"}, None],
        [off, "top"],
        [off, None],
    ]
    # a press resets the mark, so a release it never saw leaves nothing stale
    assert got["reset"][-1] == [off, None]
    # a Shift press clears the mark and starts no drag: nothing a later crossing sets
    assert got["shifted"][2:] == [[off, None], [off, None], [off, None]]
    # a release whose drag moved no selection clears and fires nothing; a crossing with no drag sets nothing
    assert got["unmoved"][-1] == [off, None]
    assert got["noDrag"] == [[off, None], [off, None]]


@pytest.mark.unit
def test_the_note_is_the_edges_first_and_the_first_copy_only_with_a_transcript():
    assert _probe()["notes"] == {
        "edge": EDGE,
        "edgeShell": EDGE_SHELL,
        "first": FIRST,
        "spent": "",
        "shell": "",
        "oneRow": "",
    }


@pytest.mark.unit
def test_a_copy_carries_its_note_for_seven_seconds_and_the_first_copy_note_once():
    got = _probe()
    # a one-row copy toasts *copied* as before; the first of several rows adds its note, green for 7 s; the next none
    assert got["plain"] == [
        [["copied", True, None], True],
        [[f"copied — {FIRST}", True, 7000], False],
        [["copied", True, None], False],
    ]
    # a refused write draws no first-copy note and gives the flag back, so the next copy of several rows carries it
    assert got["refused"] == [[[BLOCKED, False, None], True], [[f"copied — {FIRST}", True, 7000], False]]
    # the edge's note wins and leaves the first-copy note for the next copy of several rows
    assert got["edgeFirst"] == [[[f"copied — {EDGE}", True, 7000], True], [[f"copied — {FIRST}", True, 7000], False]]
    # the edge's note goes on *clipboard blocked* too
    assert got["edgeRefused"] == [[[f"{BLOCKED} — {EDGE}", False, 7000], True]]
    # no Transcript: the edge reads *copy a screen at a time*, and the first-copy note waits for a Transcript
    assert got["shell"] == [
        [[f"copied — {EDGE_SHELL}", True, 7000], True],
        [["copied", True, None], True],
        [[f"copied — {FIRST}", True, 7000], False],
    ]
