"""The Focus soft-key row (design §4.5a **Focus pane: soft-key row**, §4.5 *Phone layout*, TD-986, built by
TD-990), reshaped as the key bar (TD-003, built by TD-1300): `esc tab ⇧tab ctrl ◂▴▾▸ ↵ 1–9` under the terminal on a
phone or a coarse pointer, each key's bytes typed through the terminal by `term.input`, ctrl latched or locked, the
drag pad's repeating arrows, the digit page, and the row drawn only where the terminal takes keys."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from conftest import scratch_dir
from test_ui import client  # noqa: F401 — the fixture, by name

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"

PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const names = ["Tab", "Esc", "BackTab", "Up", "Down", "Left", "Right", "Enter", "1", "5", "9", "0", "F1", ""];
// ctrl over a letter: a tap latches it for one key, a hold locks it until it is pressed again
const c = AO.ctrlLatch(), ctrlRun = [];
const step = (what, data) => {
  if (what === "tap") c.tap(); else if (what === "hold") c.hold(); else ctrlRun.push([data, c.apply(data)]);
  ctrlRun.push(c.state());
};
step("tap"); step("data", "c"); step("data", "c");             // latched: one ^C, then a plain c
step("tap"); step("data", "hello");                            // the phone's word: its first character only
step("tap"); step("tap"); step("data", "x");                    // a second tap lets the latch go
step("hold"); step("data", "a"); step("data", "["); step("data", "Z"); step("tap"); step("data", "a");
step("tap"); step("data", "\x1b[I"); step("data", "\t");          // a focus report is no key; the tab clears it
// the drag pad by a scripted pointer, the clock in our hand
let now = 0; const timers = []; const sent = [];
const tm = {
  set: (f, ms) => { const h = { f, at: now + ms }; timers.push(h); return h; },
  clear: (h) => { const i = timers.indexOf(h); if (i >= 0) timers.splice(i, 1); },
};
const advance = (ms) => {
  const end = now + ms;
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    const h = timers[0]; if (!h || h.at > end) break;
    timers.shift(); now = h.at; h.f();
  }
  now = end;
};
const pad = AO.dragPad((d) => sent.push([now, d]), tm);
const padRun = {};
pad.down(100, 100); pad.move(110, 105); advance(500); padRun.press = sent.splice(0);         // under 16 px: nothing
pad.move(100, 84); padRun.first = sent.splice(0);                                          // 16 px up: an arrow at once
advance(310); padRun.slow = sent.splice(0);                                                 // then every 150 ms
pad.move(100, 30); advance(130); padRun.fast = sent.splice(0);                              // 64 px out: every 60 ms
pad.move(200, 90); padRun.turn = sent.splice(0);                                            // a new main direction
pad.move(105, 100); advance(500); padRun.back = sent.splice(0);                             // back within 16 px: stops
pad.move(70, 100); padRun.again = sent.splice(0); pad.up(); advance(500); padRun.lifted = sent.splice(0);
// the digit page: a fake row's classes
const cls = new Set(); const row = { classList: { toggle: (k, on) => (on ? cls.add(k) : cls.delete(k)) } };
AO.softPage(row, "digits"); const pageDigits = cls.has("digits");
AO.softPage(row, "main"); const pageBack = cls.has("digits");
const live = { state: "idle", unattended: false };
console.log(JSON.stringify({
  ctrl: ctrlRun, pad: padRun, page: [pageDigits, pageBack],
  normal: Object.fromEntries(names.map((n) => [n, AO.softKey(n, false)])),
  app: Object.fromEntries(names.map((n) => [n, AO.softKey(n, true)])),
  shown: {
    live: AO.softShown(live, false),
    live_pane_gone: AO.softShown(live, true),
    working: AO.softShown({ state: "working", unattended: false }, false),
    needs_you: AO.softShown({ state: "needs-you", unattended: false }, false),
    unattended: AO.softShown({ state: "idle", unattended: true }, false),
    exited: AO.softShown({ state: "exited", unattended: false }, false),
    closed: AO.softShown({ state: "closed", unattended: false }, false),
    nothing: AO.softShown(null, false),
  },
}));
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the row's rules are JavaScript, and nothing else runs them")
    probe = scratch_dir() / "soft_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_each_key_is_the_bytes_xterm_sends_for_it_in_both_cursor_modes():
    got = _probe()
    same = {"Tab": "\t", "Esc": "\x1b", "Enter": "\r", "BackTab": "\x1b[Z", "1": "1", "5": "5", "9": "9"}
    for mode in ("normal", "app"):
        for name, want in same.items():
            assert got[mode][name] == want, (mode, name)
        # the row has 1–9 and no other key: a name it does not have types nothing
        for name in ("0", "F1", ""):
            assert got[mode][name] is None, (mode, name)
    # the arrows follow the program's application cursor keys (`term.modes.applicationCursorKeysMode`)
    assert [got["normal"][k] for k in ("Up", "Down", "Right", "Left")] == ["\x1b[A", "\x1b[B", "\x1b[C", "\x1b[D"]
    assert [got["app"][k] for k in ("Up", "Down", "Right", "Left")] == ["\x1bOA", "\x1bOB", "\x1bOC", "\x1bOD"]


@pytest.mark.unit
def test_ctrl_latches_for_one_key_and_a_hold_locks_it_over_a_letter():
    s = [x if isinstance(x, str) else tuple(x) for x in _probe()["ctrl"]]
    assert s == [
        "latched", ("c", "\x03"), "off", ("c", "c"), "off",  # latched: one ^C, then a plain c
        "latched", ("hello", "\x08ello"), "off",  # the first character of the keyboard's data, the rest as typed
        "latched", "off", ("x", "x"), "off",  # pressed again, it lets go
        "locked", ("a", "\x01"), "locked", ("[", "\x1b"), "locked", ("Z", "\x1a"), "locked",  # locked: every key
        "off", ("a", "a"), "off",  # a press unlocks it
        "latched", ("\x1b[I", "\x1b[I"), "latched", ("\t", "\t"), "off",  # a focus report is no key; a bar key is
    ]  # fmt: skip


@pytest.mark.unit
def test_the_drag_pad_sends_nothing_on_a_press_then_its_arrow_repeating_until_it_comes_back():
    p = _probe()["pad"]
    assert p["press"] == []  # under 16 px of slide: nothing, however long it is held
    assert p["first"] == [[500, "Up"]]  # 16 px up: the arrow at once
    assert p["slow"] == [[650, "Up"], [800, "Up"]]  # then every 150 ms while held away
    assert [d for _, d in p["fast"]] == ["Up", "Up"] and p["fast"][1][0] - p["fast"][0][0] == 60  # 64 px out: 60 ms
    assert p["turn"] == [[940, "Right"]]  # a new main direction sends its own arrow at once
    assert p["back"] == []  # back within 16 px: it stops
    assert p["again"] == [[1440, "Left"]] and p["lifted"] == []  # the lift stops it too


@pytest.mark.unit
def test_the_digit_page_flips_and_back():
    assert _probe()["page"] == [True, False]
    css = (UI / "static" / "app.css").read_text()
    assert ".softkeys .skd, .softkeys.digits .skm, .softkeys .skblur { display: none; }" in css
    assert ".softkeys.digits .skd { display: block; }" in css
    # ⌄ in 1–9's place while the phone's keyboard is up for the terminal; a coarse tablet's desktop page keeps 1–9
    assert "html.phonefocus .page.focus.kbdup .softkeys:not(.digits) .sk19 { display: none; }" in css
    assert "html.phonefocus .page.focus.kbdup .softkeys:not(.digits) .skblur { display: block; }" in css
    js = (UI / "static" / "app.js").read_text()
    assert "if (k.dataset.page) { AO.softPage(softEl, k.dataset.page); return; }" in js
    assert 'if (blurEl) blurEl.addEventListener("click", () => term.blur());' in js


@pytest.mark.unit
def test_the_row_never_scrolls_and_its_keys_take_no_pan():
    css = (UI / "static" / "app.css").read_text()
    row = css[css.index(".softkeys { display: flex; gap: 5px;") :]
    row = row[: row.index(".softkeys.digits .skd")]
    assert "overflow-x" not in row and "flex: 1 1 0; min-width: 0; height: 44px;" in row
    assert "touch-action: none;" in row and "touch-action: pan-x" not in css
    js = (UI / "static" / "app.js").read_text()
    focus = js[js.index("AO.focus = function") :]
    # the pad keeps its pointer, and the keys' test at pointerup is never the pad's
    assert 'padEl.addEventListener("pointermove", (e) => pad.move(e.clientX, e.clientY));' in focus
    assert "button[data-key], button[data-ctrl], button[data-page], button[data-blur]" in focus
    # ctrl's next key is the bar's own (through `term.input`) or the keyboard's: both reach onData
    assert 'if (ctrl.state() !== "off") { d = ctrl.apply(d); drawCtrl(); }' in focus


@pytest.mark.unit
def test_the_row_is_drawn_exactly_where_the_terminal_takes_keys():
    got = _probe()["shown"]
    assert got["live"] and got["working"] and got["needs_you"]
    # read-only (unattended), ended, or a page whose pane is gone: no keys, so no row
    for case in ("live_pane_gone", "unattended", "exited", "closed", "nothing"):
        assert got[case] is False, case


@pytest.mark.unit
def test_render_and_the_attach_drive_the_row_and_a_press_goes_through_the_terminal():
    js = (UI / "static" / "app.js").read_text()
    focus = js[js.index("AO.focus = function") :]
    render = focus[focus.index("    function render(v) {") :]
    render = render[: render.index("\n    }\n")]
    # one rule on load and each delta: the ending's two sides, the mode's flip, the pane's going
    assert 'softEl.classList.toggle("hidden", !AO.softShown(v, paneGone));' in render
    # the dim is drawMark's, before its markEl guard; the press reads the same two things itself
    mark = focus[focus.index("    const drawMark = () => {") :]
    assert mark.index('softEl.classList.toggle("dim"') < mark.index("if (!markEl) return;")
    assert "if (!live() || readOnly) return;" in focus
    assert "term.input(bytes, true)" in focus and "applicationCursorKeysMode" in focus
    # never a touchstart default (the row's sideways pan), and openTerm() never touches the row
    assert 'softEl.addEventListener("touchstart"' not in focus
    open_term = focus[focus.index("    function openTerm() {") : focus.index("    function reattach() {")]
    assert 'softEl.classList.toggle("hidden"' not in open_term and 'softEl.classList.remove("hidden")' not in open_term


def _start(client, tmp_path, name, **extra):  # noqa: F811
    d = tmp_path / name
    d.mkdir()
    r = client.post("/new", data={"name": name, "dir": str(d), "adapter": "hookstub", **extra}, follow_redirects=False)
    return r.headers["location"].rsplit("/", 1)[-1]


def _row(html: str) -> str:
    m = re.search(r'<div class="softkeys[^"]*" id="softkeys"[^>]*>', html)
    assert m, "the soft-key row is in the page"
    return m.group(0)


def test_the_row_is_seeded_on_a_live_record_and_hidden_on_an_unattended_or_ended_one(client, tmp_path):  # noqa: F811
    sid = _start(client, tmp_path, "sk")
    html = client.get(f"/focus/{sid}").text
    row = _row(html)
    assert "hidden" not in row
    # its hover is the help text's first sentence
    assert 'title="Keys under the terminal — esc, tab, ⇧tab, ctrl, the drag pad ◂▴▾▸, ↵ and 1–9 — that type' in row
    keys = re.findall(r'<button [^>]*data-key="([^"]+)"', html[html.index('id="softkeys"') :])
    assert keys[:4] == ["Esc", "Tab", "BackTab", "Enter"] and keys[4:13] == [*map(str, range(1, 10))]
    bar = html[html.index('id="softkeys"') :]
    bar = bar[: bar.index("</div>")]
    labels = re.findall(r'class="(skm[^"]*)"[^>]*>([^<]+)</button>', bar)
    assert [w for _, w in labels] == ["esc", "tab", "⇧tab", "ctrl", "◂▴▾▸", "↵", "1–9", "⌄"]
    assert re.findall(r'class="skd"[^>]*>([^<]+)</button>', bar) == [*map(str, range(1, 10)), "‹"]
    # unattended: the attach is read-only, so the row is seeded hidden and does not flash before the first frame
    assert client.post(f"/api/sessions/{sid}/mode", json={"unattended": True}).json()["ok"] is True
    assert "hidden" in _row(client.get(f"/focus/{sid}").text)
    assert client.post(f"/api/sessions/{sid}/mode", json={"unattended": False}).json()["ok"] is True
    assert "hidden" not in _row(client.get(f"/focus/{sid}").text)
    assert client.post(f"/api/sessions/{sid}/close").status_code == 200
    assert "hidden" in _row(client.get(f"/focus/{sid}").text)
