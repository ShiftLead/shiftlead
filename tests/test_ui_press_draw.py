"""TD-1333, design §4.5 screen 6 rule 4 (TD-1316, built by TD-1321): a press that writes origin draws its result on
the press, a refusal puts the row back as it was, and a re-read draws a press still out again, once. The source-grep
tests in `test_ui_inbox.py`, `test_ui_keys.py` and `test_ui_queue.py` pin the wiring; this one runs the draw functions
of `app.js` (`AO.drawDecided`, `drawReply`, `unDraw`, `redraw`, `drawQState`, `unDrawQState`) under node, on rows
built in a small DOM of its own, and reads what they drew."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

APP_JS = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui" / "static" / "app.js"

PROBE = r"""
const fs = require("fs");
const noop = () => {};
// ---- a small DOM: elements, classes, data-* and other attributes, and the selectors the draw functions use ----
const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
class El {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.parentElement = null; this.dataset = {}; this.attrs = {};
    this.hidden = false; this.disabled = false; this.open = false; this.textContent = ""; this.style = {};
    this._cls = new Set();
    const self = this;
    this.classList = {
      contains: (c) => self._cls.has(c), add: (...c) => c.forEach((x) => self._cls.add(x)),
      remove: (...c) => c.forEach((x) => self._cls.delete(x)),
      toggle: (c, on) => { if (on === undefined ? !self._cls.has(c) : on) self._cls.add(c); else self._cls.delete(c); },
    };
  }
  get className() { return [...this._cls].join(" "); }
  set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get tabIndex() { return this.attrs.tabindex === undefined ? 0 : Number(this.attrs.tabindex); }
  set tabIndex(v) { this.attrs.tabindex = String(v); }
  getAttribute(a) { return a.startsWith("data-") ? this.dataset[camel(a.slice(5))] ?? null : this.attrs[a] ?? null; }
  setAttribute(a, v) {
    if (a.startsWith("data-")) this.dataset[camel(a.slice(5))] = String(v); else this.attrs[a] = String(v);
  }
  removeAttribute(a) { if (a.startsWith("data-")) delete this.dataset[camel(a.slice(5))]; else delete this.attrs[a]; }
  addEventListener() {}
  appendChild(c) { c.remove(); c.parentElement = this; this.children.push(c); return c; }
  remove() {
    const p = this.parentElement;
    if (p) { p.children.splice(p.children.indexOf(this), 1); this.parentElement = null; }
  }
  insert(n, at) {
    const p = this.parentElement;
    n.remove(); n.parentElement = p; p.children.splice(p.children.indexOf(this) + at, 0, n);
  }
  before(n) { this.insert(n, 0); }
  after(n) { this.insert(n, 1); }
  descendants() { return this.children.flatMap((c) => [c, ...c.descendants()]); }
  matches(sel) { return groups(sel).some((g) => matchChain(this, g)); }
  closest(sel) { for (let e = this; e; e = e.parentElement) if (e.matches(sel)) return e; return null; }
  querySelectorAll(sel) { return this.descendants().filter((e) => e.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
// a selector: comma groups, each a descendant chain of compounds — tag, .class, [attr], [attr="v"], :not(compound)
const groups = (sel) => sel.split(",").map((g) => g.trim().split(/\s+(?![^\[]*\])/).map(compound));
function compound(s) {
  const c = { tag: null, cls: [], attrs: [], not: [] };
  const re = /^([a-z]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]|:not\(([^)]*)\)/g;
  let m;
  while ((m = re.exec(s))) {
    if (m[1]) c.tag = m[1].toUpperCase(); else if (m[2]) c.cls.push(m[2]);
    else if (m[3]) c.attrs.push([m[3], m[4]]); else if (m[5]) c.not.push(compound(m[5]));
  }
  return c;
}
const matchOne = (e, c) =>
  (!c.tag || e.tagName === c.tag) && c.cls.every((x) => e.classList.contains(x)) &&
  c.attrs.every(([a, v]) => (v === undefined ? e.getAttribute(a) !== null : e.getAttribute(a) === v)) &&
  c.not.every((n) => !matchOne(e, n));
function matchChain(e, chain) {
  if (!matchOne(e, chain[chain.length - 1])) return false;
  let i = chain.length - 2;
  for (let a = e.parentElement; a && i >= 0; a = a.parentElement) if (matchOne(a, chain[i])) i--;
  return i < 0;
}
const h = (tag, cls, opts, kids) => {
  const e = new El(tag); e.className = cls || "";
  Object.entries(opts || {}).forEach(([k, v]) => (k === "text" ? (e.textContent = v) : e.setAttribute(k, v)));
  (kids || []).forEach((k) => e.appendChild(k));
  return e;
};
// the row as a string — tag, classes, attributes, data, hidden, disabled, text — to compare a row with itself
const snap = (e) => [e.tagName, e.className, JSON.stringify(e.attrs), JSON.stringify(e.dataset), e.hidden, e.disabled,
  e.textContent, `(${e.children.map(snap).join(",")})`].join("|");
// ---- the page app.js loads into, its load-time hooks inert ----
const document = { documentElement: new El("html"), body: new El("body"), querySelector: () => null,
  querySelectorAll: () => [], addEventListener: noop, createElement: (t) => new El(t), activeElement: null };
global.window = {}; global.document = document; global.Event = class { constructor(t) { this.type = t; } };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
// ---- fixtures: a board row (one reply, its answers, Go with it, its foot) and a Queue card's row ----
const boardRow = (opts) => {
  const o = opts || {};
  return h("div", "mailrow", {}, [
    h("div", "st boardreply", { text: "Paul, 2026-11-02: first" }),
    ...(o.replies2 ? [h("div", "st boardreply", { text: "Paul, 2026-11-03: second" })] : []),
    ...(o.decided ? [h("div", "st decided", { text: "decided: Yes (2026-11-03)" })] : []),
    h("div", "sugg", {}, [h("button", "", { text: "Yes" }), h("button", "", { text: "No" })]),
    h("a", "btn boardgo", { text: "Go with it" }),
    h("div", "mfoot", {}, [h("button", "", { text: "Snooze" }), h("button", "", { text: "Done" })]),
    h("div", "rowerr", { text: "" }),
  ]);
};
const kids = (row) => row.children.map((c) => c.className);
const drawn = (row) => row.querySelectorAll("[data-drawn]").map((x) => [x.className, x.textContent]);
const hiddenNow = (row) => row.querySelectorAll(".sugg, .boardgo").map((x) => x.hidden);
const offNow = (row) => row.querySelectorAll("button, .btn").filter((x) => x.disabled).map((x) => x.textContent);
const out = {};

// a decide: the drawn line before the answers, the answers and Go with it hidden; a second draw rewrites it
let row = boardRow(), was = snap(row);
AO.drawDecided(row, "decided: Yes — landing on the board…");
AO.drawDecided(row, "decided: Yes — written on the board");
AO.drawOff(row);
out.decided = { kids: kids(row), drawn: drawn(row), hidden: hiddenNow(row), off: offNow(row) };
AO.unDraw(row);
out.decided_undone = snap(row) === was;

// a reply: the drawn line after the row's last reply line
row = boardRow({ replies2: true }); was = snap(row);
AO.drawReply(row, "Paul, 2026-11-03: third — landing on the board…");
out.reply = { kids: kids(row), drawn: drawn(row), hidden: hiddenNow(row) };
AO.unDraw(row);
out.reply_undone = snap(row) === was;

// a re-read: a fresh row is drawn again, once; a row the board already draws the result on is left alone
const fd = { kind: "decided", text: "decided: Yes — landing on the board…", out: true };
row = boardRow();
out.redraw_fresh = [AO.redraw(row, fd), AO.redraw(row, fd)];
out.redraw_fresh_drawn = drawn(row); out.redraw_fresh_off = offNow(row);
row = boardRow({ decided: true }); was = snap(row);
out.redraw_board_has_it = AO.redraw(row, fd); out.redraw_board_untouched = snap(row) === was;
const fr = { kind: "reply", text: "Paul, 2026-11-03: second — landing on the board…", replies: 1, out: false };
row = boardRow();
out.redraw_reply = AO.redraw(row, fr); out.redraw_reply_drawn = drawn(row); out.redraw_reply_off = offNow(row);
row = boardRow({ replies2: true }); was = snap(row);
out.redraw_reply_landed = AO.redraw(row, fr); out.redraw_reply_untouched = snap(row) === was;
out.redraw_other = AO.redraw(boardRow(), { kind: "qrow" });

// a Queue card's row: its state cell rewritten (the page's word kept for a refusal), its own ⋯ off — not the ⋯ of
// an item drawn inside it (a `.mailrow`), which comes first in the row
const dots = () => h("details", "qdots", {}, [h("summary", "qdotsbtn", { text: "⋯" }),
  h("div", "menu", {}, [h("button", "", { role: "menuitem", text: "Done…" }),
    h("a", "", { role: "menuitem", text: "Open" })])]);
const qrow = (state) => h("div", "qrow", { "data-qid": "TD-7" }, [
  h("div", "mailrow", {}, [dots()]),
  h("div", "qtail", {}, [...(state ? [h("span", "qstate s-waiting", { text: "waiting on review" })] : []), dots()]),
]);
const ownDots = (t) => t.children[1].querySelector("details.qdots");
const dotsState = (d) => ({ open: d.open, mark: d.querySelector("summary").getAttribute("aria-disabled"),
  tab: d.querySelector("summary").getAttribute("tabindex"),
  items: d.querySelectorAll('.menu [role="menuitem"]').map((x) => [x.getAttribute("aria-disabled"), x.disabled]) });
let t = qrow(true); was = snap(t);
ownDots(t).open = true;
AO.drawQState(t, "done — landing on the board…", true);
const cell = (t) =>
  t.children[1].children.filter((x) => x.classList.contains("qstate")).map((x) => [x.className, x.textContent]);
out.q = { cell: cell(t), own: dotsState(ownDots(t)), item: dotsState(t.children[0].querySelector("details.qdots")) };
AO.unDrawQState(t);
out.q_undone = snap(t) === was;
t = qrow(false); was = snap(t);
AO.drawQState(t, "back to design — landing on the board…", true);
out.q_new = { cell: cell(t), drawn: t.children[1].children[0].dataset.drawn === "1" };
AO.drawQState(t, "back to design — written on the board", false);
out.q_answered = { cell: cell(t), own: dotsState(ownDots(t)) };
AO.unDrawQState(t);
out.q_new_undone = snap(t) === was;
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def drew(tmp_path_factory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    probe = tmp_path_factory.mktemp("press_draw") / "press_draw_probe.js"
    probe.write_text(PROBE)
    got = subprocess.run(["node", str(probe), str(APP_JS)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(got.stdout.strip().splitlines()[-1])


ROW = ["st boardreply", "sugg", "btn boardgo", "mfoot", "rowerr"]


def test_a_decide_draws_its_answer_once_before_the_answers_and_hides_them(drew):
    assert drew["decided"] == {
        "kids": ["st boardreply", "st decided", *ROW[1:]],
        "drawn": [["st decided", "decided: Yes — written on the board"]],
        "hidden": [True, True],
        "off": ["Snooze", "Done"],  # the hidden answers and Go with it are not turned off, only hidden
    }


def test_a_refused_decide_puts_the_row_back_as_it_was(drew):
    assert drew["decided_undone"] is True


def test_a_reply_draws_its_words_after_the_rows_last_reply_line(drew):
    assert drew["reply"] == {
        "kids": ["st boardreply", "st boardreply", "st boardreply", *ROW[1:]],
        "drawn": [["st boardreply", "Paul, 2026-11-03: third — landing on the board…"]],
        "hidden": [False, False],
    }
    assert drew["reply_undone"] is True


def test_a_reread_draws_a_press_still_out_again_once_and_leaves_a_landed_one(drew):
    assert drew["redraw_fresh"] == [True, True]
    assert drew["redraw_fresh_drawn"] == [["st decided", "decided: Yes — landing on the board…"]]
    assert drew["redraw_fresh_off"] == ["Snooze", "Done"]
    assert drew["redraw_board_has_it"] is False and drew["redraw_board_untouched"] is True
    assert drew["redraw_reply"] is True
    assert drew["redraw_reply_drawn"] == [["st boardreply", "Paul, 2026-11-03: second — landing on the board…"]]
    assert drew["redraw_reply_off"] == []  # an answered press: drawn, its controls on
    assert drew["redraw_reply_landed"] is False and drew["redraw_reply_untouched"] is True
    assert drew["redraw_other"] is True


def test_a_queue_rows_dots_press_writes_its_state_cell_and_turns_its_own_dots_off(drew):
    assert drew["q"] == {
        "cell": [["qstate s-pressed", "done — landing on the board…"]],
        "own": {"open": False, "mark": "true", "tab": "-1", "items": [["true", True], ["true", False]]},
        "item": {"open": False, "mark": None, "tab": None, "items": [[None, False], [None, False]]},
    }
    assert drew["q_undone"] is True  # the page's state word and its ⋯ back


def test_a_queue_row_with_no_state_cell_gains_one_and_loses_it_on_a_refusal(drew):
    assert drew["q_new"] == {"cell": [["qstate s-pressed", "back to design — landing on the board…"]], "drawn": True}
    assert drew["q_answered"] == {
        "cell": [["qstate s-pressed", "back to design — written on the board"]],
        "own": {"open": False, "mark": None, "tab": None, "items": [[None, False], [None, False]]},
    }
    assert drew["q_new_undone"] is True
