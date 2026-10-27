"""The Repo page's read of its lists (design §4.5 *Page loads*, *Only what is shown*; TD-882, tested by TD-889):
`AO.repo` runs under node against a page of stubs, its fetches held until the probe answers them. A read
asked for other rows while one is out is read after it; a home that answers without the wider window is
not asked for it again on the next apply; *+n more* on a list not yet sent reads that list; and a failed
read lets the button be pressed again."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
from conftest import scratch_dir

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"

PROBE = r"""
const fs = require("fs");
const noop = () => {};
const el = (extra) => Object.assign({ dataset: {}, style: {}, hidden: false, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false }, contains: () => true,
  querySelector: () => null, querySelectorAll: () => [] }, extra);
global.window = {};
global.document = el({ documentElement: el(), body: el(), createElement: el, getElementById: () => null });
global.CSS = { escape: (s) => s };
global.WebSocket = function () { return el({ close: noop, send: noop }); };
global.EventSource = function () { return el({ close: noop }); };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/repo/r", protocol: "http:", host: "x", search: "", hash: "" };
global.fetch = () => Promise.reject(new Error("no calls at load"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const flush = () => new Promise((r) => setImmediate(r));
// One Repo page: `Q` its elements by selector, `QA` its lists; fetches held until answered
function page() {
  const Q = {}, QA = {}, kept = {}, later = [], asked = [], answers = [];
  let clicks = null, hashchange = null;
  const find = { querySelector: (s) => Q[s] || null, querySelectorAll: (s) => QA[s] || [] };
  Object.assign(document, find);
  global.localStorage = { getItem: (k) => (k in kept ? kept[k] : null), setItem: (k, v) => (kept[k] = v) };
  global.setTimeout = (f) => { later.push(f); return later.length; };
  global.window.addEventListener = (k, f) => { if (k === "hashchange") hashchange = f; };
  global.fetch = (url) => {
    asked.push(decodeURIComponent(url));
    return new Promise((ok, no) => answers.push({ ok, no }));
  };
  const listen = (k, f) => { if (k === "click") clicks = f; };
  Q["#repopage"] = el({ ...find, dataset: { repo: "r", root: "/r" }, addEventListener: listen });
  Q["#repolists"] = el({ ...find, innerHTML: "" }); Q["#groups"] = el(find);
  Q["#completed"] = el({ dataset: { loaded: "day" } });
  AO.repo();
  const press = (sel, target) => clicks({ target: { closest: (s) => (s === sel ? target || el() : null) } });
  return {
    Q, QA, asked,
    pick: (win) => { kept["ao.win"] = JSON.stringify(win); press(".tsum .seg[data-pick] button"); },
    anchor: (id) => { location.hash = "#" + id; Q["#board"] = el(); hashchange(); },
    unfold: (key, b) => { Q[`[data-unfold="${key}"]`] = b; press("[data-unfold]", el({ dataset: { unfold: key } })); },
    answer: async (ok) => {
      const a = answers.shift();
      if (!a) return;  // nothing was asked
      if (ok) a.ok({ ok: true, text: async () => "" }); else a.no(new Error("down"));
      await flush(); await flush();
    },
    tick: async () => { while (later.length) later.shift()(); await flush(); },
  };
}
(async () => {
  const out = {};
  // (a) a read for other rows asked while one is out is read after it
  let p = page();
  p.pick("week"); p.anchor("TD-9");
  out.during = p.asked.length;
  await p.answer(true); await p.tick();
  out.again = p.asked;
  // (b) a home that answers without the wider window is not asked again on the next apply
  p = page();
  p.pick("week"); await p.answer(true); p.pick("week"); await p.tick();
  out.short = p.asked;
  // (c), (d) *+n more* on an unsent list reads its rows; a failed read lets it be pressed again
  p = page();
  const more = el({ dataset: { unsent: "" }, disabled: false });
  p.unfold("debt:open", more);
  out.unsent = { asked: p.asked.slice(), disabled: more.disabled };
  p.QA["[data-unsent][disabled]"] = [more];
  await p.answer(false);
  out.failed = { disabled: more.disabled };
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def got() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the Repo page's read is JavaScript, and nothing else runs it")
    probe = scratch_dir() / "repo_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_a_read_for_other_rows_asked_while_one_is_out_is_read_after_it(got):
    assert got["during"] == 1  # one read out at a time
    assert got["again"] == ["/repo/r?part=1&win=week", "/repo/r?part=1&win=week&open=TD-9"]


@pytest.mark.unit
def test_a_home_that_answers_without_the_wider_window_is_not_asked_again(got):
    assert got["short"] == ["/repo/r?part=1&win=week"]


@pytest.mark.unit
def test_more_on_a_list_not_sent_reads_it_and_a_failed_read_lets_it_be_pressed_again(got):
    assert got["unsent"] == {"asked": ["/repo/r?part=1&win=day&open=debt:open"], "disabled": True}
    assert got["failed"] == {"disabled": False}
