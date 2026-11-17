"""The Focus pane measures character widths by Unicode 11 (design §2 goal 12, TD-1912): xterm.js's unicode11
addon, vendored at the release paired with the vendored xterm, is loaded where the terminal is built and made
the active version, so an emoji or a wide symbol takes the cells tmux gives it."""

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

# `AO.termUnicode` from app.js, run on a stand-in terminal with the vendored addon as the page's global
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
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const providers = {};
let active = "6";
const term = { loadAddon: (a) => a.activate(term),
  unicode: { register: (p) => { providers[p.version] = p; },
    get activeVersion() { return active; }, set activeVersion(v) { active = v; } } };
const before = { active };
global.Unicode11Addon = require(process.argv[3]);
AO.termUnicode(term);
const p = providers["11"];
console.log(JSON.stringify({ before, active,
  widths: { grin: p.wcwidth(0x1F600), check: p.wcwidth(0x2705), letter: p.wcwidth(0x61), cjk: p.wcwidth(0x4E2D) } }));
"""


def test_the_addon_is_vendored_at_its_release_with_its_licence():
    data = (VENDOR / "addon-unicode11.js").read_bytes()
    # the file @xterm/addon-unicode11 0.8.0 publishes (jsdelivr and unpkg, 2026-11-17)
    assert hashlib.sha256(data).hexdigest() == "b0c3be540a9984713aea996966c24ed1a639d11f60d44986b22661e3a8a148d0"
    assert "Permission is hereby granted, free of charge" in (VENDOR / "LICENSE-addon-unicode11.txt").read_text()
    readme = (VENDOR / "README.md").read_text()
    assert "| `addon-unicode11.js` | `@xterm/addon-unicode11` | 0.8.0" in readme


def test_focus_loads_the_addon_where_the_terminal_is_built():
    html = (UI / "templates" / "focus.html").read_text()
    assert html.index("vendor/xterm.js") < html.index("vendor/addon-unicode11.js") < html.index("AO.focus(")
    js = (UI / "static" / "app.js").read_text()
    focus = js[js.index("AO.focus = function") :]
    built = focus.index("const term = new Terminal(")
    # the `unicode` API is proposed in xterm 5.5: without the option, setting the version throws
    assert "allowProposedApi: true" in focus[built : focus.index("\n", built)]
    # once, beside the fit addon, before the terminal opens (a popped-out window is the same page)
    assert focus.count("AO.termUnicode(term)") == 1
    assert built < focus.index("new FitAddon.FitAddon()") < focus.index("AO.termUnicode(term)")
    assert focus.index("AO.termUnicode(term)") < focus.index('term.open($("#term"))')
    assert js.count("new Terminal(") == 1  # no other terminal to miss


def test_the_addon_is_active_and_measures_emoji_wide():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the load is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "unicode_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run(
        [node, str(probe), str(UI / "static" / "app.js"), str(VENDOR / "addon-unicode11.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["before"] == {"active": "6"} and got["active"] == "11"
    # two cells for an emoji and a CJK ideograph, one for a letter: what tmux gives them
    assert got["widths"] == {"grin": 2, "check": 2, "letter": 1, "cjk": 2}
