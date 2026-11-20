"""The Focus pane measures character widths by Unicode 15 with grapheme clusters (design §2 goal 12, TD-1912,
TD-1918): xterm.js's unicode-graphemes addon, vendored at the release paired with the vendored xterm, is loaded
where the terminal is built and made the active version, so an emoji, a wide symbol, a ZWJ sequence or an emoji
presentation selector takes the cells tmux gives it."""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess

import pytest
from conftest import scratch_dir

pytestmark = pytest.mark.unit

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
VENDOR = UI / "static" / "vendor"

# `AO.termUnicode` from app.js, run on the vendored xterm with the vendored addon as the page's global: the cursor
# column after each string is the cells the terminal gave it
PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
global.window = {}; global.document = document; global.self = global;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
const timers = { setInterval, setTimeout, clearTimeout };
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
Object.assign(global, timers);  // app.js is loaded: xterm's writes need the real ones
const { Terminal } = require(process.argv[3]);
// under node the addon decodes its tables with `Buffer.from`, whose pooled bytes it misreads; a browser has no
// `Buffer` and takes `atob`, so the probe hides it while the addon loads
const B = global.Buffer; global.Buffer = undefined;
global.UnicodeGraphemesAddon = require(process.argv[4]);
global.Buffer = B;
const cases = JSON.parse(process.argv[5]);
const got = { cells: {} }; const keys = Object.keys(cases); let i = 0;
const next = () => {
  if (i >= keys.length) return console.log(JSON.stringify(got));
  const k = keys[i++];
  const term = new Terminal({ allowProposedApi: true, cols: 80, rows: 5 });
  got.before = term.unicode.activeVersion;
  AO.termUnicode(term);
  got.active = term.unicode.activeVersion;
  term.write(cases[k], () => { got.cells[k] = term.buffer.active.cursorX; term.dispose(); next(); });
};
next();
"""


def test_the_addon_is_vendored_at_its_release_with_its_licence():
    # the files @xterm/xterm 6.0.0 and @xterm/addon-unicode-graphemes 0.4.0 publish (jsdelivr and unpkg, 2026-11-17)
    published = {
        "addon-unicode-graphemes.js": "8e7f926f4def5733a190b80cff5cbaa550404e143b0750962f7d756138203cb8",
        "xterm.js": "14903579ff54664cd72f8e8699e6961a6272c21863ec1c3b118cdc8af5d4a972",
        "xterm.css": "854a7c0fb70e8b1a083c16797ab827299fb18744f5ad34f227b48337e33293c6",
    }
    for name, digest in published.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == digest, name
    licence = (VENDOR / "LICENSE-addon-unicode-graphemes.txt").read_text()
    assert "Permission is hereby granted, free of charge" in licence
    readme = (VENDOR / "README.md").read_text()
    assert "| `addon-unicode-graphemes.js` | `@xterm/addon-unicode-graphemes` | 0.4.0" in readme
    assert "| `xterm.js`, `xterm.css` | `@xterm/xterm` | 6.0.0" in readme
    assert not (VENDOR / "addon-unicode11.js").exists()


def test_focus_loads_the_addon_where_the_terminal_is_built():
    html = (UI / "templates" / "focus.html").read_text()
    assert html.index("vendor/xterm.js") < html.index("vendor/addon-unicode-graphemes.js") < html.index("AO.focus(")
    js = (UI / "static" / "app.js").read_text()
    focus = js[js.index("AO.focus = function") :]
    built = focus.index("const term = new Terminal(")
    # the `unicode` API is proposed in xterm 6: without the option, setting the version throws
    assert "allowProposedApi: true" in focus[built : focus.index("\n", built)]
    # once, right after the terminal is made, before it opens (a popped-out window is the same page)
    assert focus.count("AO.termUnicode(term)") == 1
    assert built < focus.index("AO.termUnicode(term)") < focus.index("term.open(boxEl)")
    assert js.count("new Terminal(") == 1  # no other terminal to miss


# each string and the cells tmux 3.5a gives it (`#{cursor_x}` after it on an 80-column pane, 2026-11-17)
TMUX_CELLS = {
    "emoji": ("a\U0001f600b", 4),
    "check": ("\u2705x", 3),
    "cjk": ("\u4e2d\u6587x", 5),
    "symbols": ("\u26a0 \u2713 \u2717 \u2460 x", 9),
    "vs16": ("\u26a0\ufe0fx", 3),
    "zwj": ("\U0001f468\u200d\U0001f469\u200d\U0001f467x", 3),
}


def test_the_addon_is_active_and_counts_the_cells_tmux_gives():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the load is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "unicode_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run(
        [
            node,
            str(probe),
            str(UI / "static" / "app.js"),
            str(VENDOR / "xterm.js"),
            str(VENDOR / "addon-unicode-graphemes.js"),
            json.dumps({k: v for k, (v, _) in TMUX_CELLS.items()}),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["before"] == "6" and got["active"] == "15-graphemes"
    assert got["cells"] == {k: n for k, (_, n) in TMUX_CELLS.items()}
