"""A line clipped with an ellipsis is whole on hover (TD-888, TD-894): the page sends no `title` repeating a
subject's or an answer's text, and `AO.wholeOnHover` sets it on the first hover, only on a line that is in
fact clipped and has none. The page's rule runs as itself under node, as `test_ui_term_resize.py` runs its
resize."""

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
const heard = {};  // the document's listeners, by event, so a hover can be dispatched to them
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: (type, f) => (heard[type] = heard[type] || []).push(f), createElement: el };
global.window = {}; global.document = document; global.Event = class { constructor(t) { this.type = t; } };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const line = (text, scrollWidth, clientWidth, title = "") => ({ textContent: text, scrollWidth, clientWidth, title });
const out = {};
const clipped = line("  merge PR 9?  ", 300, 120); AO.wholeOnHover(clipped); out.clipped = clipped.title;
const fits = line("merge it", 80, 120); AO.wholeOnHover(fits); out.fits = fits.title;
const even = line("merge it", 120, 120); AO.wholeOnHover(even); out.even = even.title;
const titled = line("merge PR 9?", 300, 120, "the page's own"); AO.wholeOnHover(titled); out.titled = titled.title;
try { AO.wholeOnHover(null); out.none = "nothing"; } catch (e) { out.none = String(e); }
// a hover reaches the rule through the document's listener, for the three lines it names and no other
const hover = (target) => (heard.mouseover || []).forEach((f) => f({ target }));
const asked = [];
const over = line("a subject", 300, 120);
hover({ closest: (sel) => (asked.push(sel), over) }); out.hovered = over.title; out.selector = asked;
hover({}); out.no_closest = "nothing";  // a text node or the document: no `closest`, nothing done
console.log(JSON.stringify(out));
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the hover is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "hover_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_a_clipped_line_gets_its_whole_text_and_no_other_line_a_title():
    got = _probe()
    assert got["clipped"] == "merge PR 9?"  # its text, trimmed
    assert got["fits"] == "" and got["even"] == ""  # a line that fits draws no title
    assert got["titled"] == "the page's own"  # a title already there is kept
    assert got["none"] == "nothing"  # a hover off the three lines does nothing


@pytest.mark.unit
def test_a_hover_reaches_the_rule_for_the_subject_and_answer_lines():
    got = _probe()
    # the rule's selector among the document's hovers (an Inbox row's paths have one of their own, TD-1115)
    assert ".mailrow .subj, .msgsubj, .btn.answer .alabel" in got["selector"]
    assert got["hovered"] == "a subject" and got["no_closest"] == "nothing"
