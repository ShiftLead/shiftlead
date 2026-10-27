"""A Queue card's lazy fold is read on its first open (TD-891, TD-898): `AO.fillFold` reads `/api/fold?key=`
once per open fold, keeps the body by key while the page lives, refills a re-read fold from it before the
read returns, says *gone — reload* for a key that names nothing and forgets its body, and on a failed read
lets the next open read again. The page's script runs as itself under node, as `test_ui_whole_on_hover.py`
runs its hover."""

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
const heard = {};  // the document's listeners, by event, so a toggle can be dispatched to them
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: (type, f) => (heard[type] = heard[type] || []).push(f), createElement: el };
global.window = {}; global.document = document; global.Event = class { constructor(t) { this.type = t; } };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
// each read takes the next scripted answer: {status, text}, or {throws}; `held` keeps it until released
const reads = [], answers = [];
let held = null;
global.fetch = (url) => {
  reads.push(url);
  const a = answers.shift() || { status: 200, text: "<p>body</p>" };
  const answer = () => {
    if (a.throws) throw new Error(a.throws);
    return { status: a.status, ok: a.status >= 200 && a.status < 300, text: async () => a.text };
  };
  if (a.hold) {
    return new Promise((resolve, reject) => { held = () => { try { resolve(answer()); } catch (e) { reject(e); } }; });
  }
  return Promise.resolve().then(answer);
};
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
// a fold: its summary, and whatever `put` appends after it
const fold = (key) => {
  const d = { dataset: { lazy: "1", fold: key }, children: [] };
  const child = (tagName, html) => ({ tagName, html, remove() { d.children = d.children.filter((c) => c !== this); } });
  d.children.push(child("SUMMARY", "the summary"));
  d.insertAdjacentHTML = (where, html) => d.children.push(child("DIV", html));
  d.matches = (sel) => sel === "details.fold[data-lazy][open]" && d.open === true;
  return d;
};
const shown = (d) => d.children.map((c) => c.html);
(async () => {
  const out = {};
  // two opens of one fold: one read
  const a = fold("k1");
  await AO.fillFold(a); await AO.fillFold(a);
  out.once = { reads: reads.length, shown: shown(a), filled: a.dataset.filled || "" };
  // a re-read swaps in a new element: filled from the kept body before its read returns, then the read's
  answers.push({ status: 200, text: "<p>fresh</p>", hold: true });
  const b = fold("k1");
  const going = AO.fillFold(b);
  out.before = shown(b);
  held(); await going;
  out.after = shown(b);
  // a key that names nothing: *gone — reload*, and the body kept for it is forgotten
  answers.push({ status: 404 });
  const c = fold("k1");
  await AO.fillFold(c);
  out.gone = shown(c);
  answers.push({ status: 200, text: "<p>again</p>", hold: true });
  const c2 = fold("k1");
  const again = AO.fillFold(c2);
  out.forgotten = shown(c2);
  held(); await again;
  // a read that throws, nothing kept: the retry line, and the next open reads again
  answers.push({ throws: "offline" });
  const d = fold("k2");
  await AO.fillFold(d);
  out.failed = { shown: shown(d), filled: d.dataset.filled || "" };
  let n = reads.length;
  await AO.fillFold(d);
  out.retried = { reads: reads.length - n, shown: shown(d) };
  // a read that is not ok, a body kept: the kept body stands, and the next open reads again
  answers.push({ status: 500 });
  const e = fold("k2");
  await AO.fillFold(e);
  out.not_ok = { shown: shown(e), filled: e.dataset.filled || "" };
  // the toggle of an open lazy fold fills it; a closed one is left alone
  n = reads.length;
  const f = fold("k3"); f.open = true;
  const g = fold("k4"); g.open = false;
  (heard.toggle || []).forEach((h) => { h({ target: f }); h({ target: g }); });
  await new Promise((r) => setImmediate(r));
  out.toggled = { reads: reads.slice(n), f: shown(f), g: shown(g) };
  out.url = reads[0];
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def got() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the fold's read is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "fill_fold_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_a_fold_opened_twice_is_read_once_and_keeps_its_summary(got):
    assert got["url"] == "/api/fold?key=k1"
    assert got["once"] == {"reads": 1, "shown": ["the summary", "<p>body</p>"], "filled": "1"}


@pytest.mark.unit
def test_a_reread_fold_is_filled_from_the_kept_body_before_its_read_returns(got):
    assert got["before"] == ["the summary", "<p>body</p>"]
    assert got["after"] == ["the summary", "<p>fresh</p>"]


@pytest.mark.unit
def test_a_key_that_names_nothing_says_gone_and_forgets_its_body(got):
    assert got["gone"] == ["the summary", '<div class="st">gone — reload</div>']
    assert got["forgotten"] == ["the summary"], "nothing kept to fill it from"


@pytest.mark.unit
def test_a_failed_read_says_so_when_nothing_is_kept_and_the_next_open_reads_again(got):
    assert got["failed"] == {
        "shown": ["the summary", '<div class="st">could not be read — open it again</div>'],
        "filled": "",
    }
    assert got["retried"] == {"reads": 1, "shown": ["the summary", "<p>body</p>"]}
    assert got["not_ok"] == {"shown": ["the summary", "<p>body</p>"], "filled": ""}


@pytest.mark.unit
def test_the_toggle_of_an_open_lazy_fold_fills_it(got):
    assert got["toggled"] == {
        "reads": ["/api/fold?key=k3"],
        "f": ["the summary", "<p>body</p>"],
        "g": ["the summary"],
    }
