"""The Focus soft-key row (design §4.5a **Focus pane: soft-key row**, §4.5 *Phone layout*, TD-986, built by
TD-990): `Tab Esc ↑ ↓ ← → Enter 1–9` under the terminal on a phone or a coarse pointer, each key's bytes typed
through the terminal by `term.input`, the row drawn only where the terminal takes keys."""

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
const names = ["Tab", "Esc", "Up", "Down", "Left", "Right", "Enter", "1", "5", "9", "0", "F1", ""];
const live = { state: "idle", unattended: false };
console.log(JSON.stringify({
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
    same = {"Tab": "\t", "Esc": "\x1b", "Enter": "\r", "1": "1", "5": "5", "9": "9"}
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
    assert 'title="Keys under the terminal — Tab, Esc, the arrows, Enter and 1–9 — that type into the session' in row
    keys = re.findall(r'<button type="button" tabindex="-1" data-key="([^"]+)">', html[html.index('id="softkeys"') :])
    assert keys[:16] == ["Tab", "Esc", "Up", "Down", "Left", "Right", "Enter", *map(str, range(1, 10))]
    # unattended: the attach is read-only, so the row is seeded hidden and does not flash before the first frame
    assert client.post(f"/api/sessions/{sid}/mode", json={"unattended": True}).json()["ok"] is True
    assert "hidden" in _row(client.get(f"/focus/{sid}").text)
    assert client.post(f"/api/sessions/{sid}/mode", json={"unattended": False}).json()["ok"] is True
    assert "hidden" not in _row(client.get(f"/focus/{sid}").text)
    assert client.post(f"/api/sessions/{sid}/close").status_code == 200
    assert "hidden" in _row(client.get(f"/focus/{sid}").text)
