"""The Focus terminal's mark (design §4.6 *Reconnect contract*; §4.5a **terminal mark**; TD-474, TD-480): a frozen
terminal has causes the person could not tell apart — the socket reconnecting, a working session whose pane draws
nothing — and the page names the one that holds. *Resized by another client* is gone (TD-1919): the window is pinned,
so no client sizes it."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import uuid

import pytest

from shiftlead.ui.pty_bridge import grid_argv, grid_read

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
APP = UI / "static" / "app.js"

PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [], contains: () => false });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: () => el() };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const base = { retryAt: null, open: true, state: "working", lastByte: 0 };
const mark = (o, now) => { const m = AO.termMark({ ...base, ...o }, now); return m && m.text; };
console.log(JSON.stringify({
  quiet: mark({}, 1000),
  retry_in_grace: mark({ retryAt: 0, open: false }, 2999),
  retry_past_grace: mark({ retryAt: 0, open: false }, 3000),
  retry_cleared: mark({ retryAt: null, open: false }, 60000),
  resized_gone: mark({ clients: 2, window: [80, 24], grid: [120, 32] }, 1000),
  silent_before: mark({}, 29999),
  silent: mark({}, 30000),
  silent_counts: mark({}, 45900),
  silent_idle: mark({ state: "idle" }, 90000),
  silent_closed: mark({ open: false }, 90000),
  silent_no_byte: mark({ lastByte: null }, 90000),
  precedence_retry: mark({ retryAt: 0 }, 40000),
  titles: ["reconnecting", "silent"].map((k) => {
    const o = { reconnecting: { retryAt: 0 }, silent: {} }[k];
    const m = AO.termMark({ ...base, ...o }, 40000); return [m.kind, m.title];
  }),
  grace: [AO.TERM_GRACE, AO.TERM_SILENT],
}));
"""


@pytest.mark.unit
def test_the_mark_is_one_in_order_each_after_its_grace(tmp_path):
    """Under node: *reconnecting…* only three seconds after a retry was scheduled and until a pane byte
    clears it; *no output for Ns* after thirty seconds of silence on an open socket of a working
    session, counting up — never on idle, closed, or before any byte; no *resized* mark whatever the
    state says of other clients. One mark, in that order; each hover in §4.5a's words."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = tmp_path / "mark_probe.js"
    probe.write_text(PROBE)
    run = subprocess.run([node, str(probe), str(APP)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got.pop("titles") == [
        ["reconnecting", "the terminal socket dropped and retries on its own — reload if it stays"],
        ["silent", "the session reads working and the pane has drawn nothing"
                   " — Transcript or `ao tail` say whether it is thinking or stuck"],
    ]  # fmt: skip
    assert got == {
        "quiet": None, "retry_in_grace": None, "retry_past_grace": "reconnecting…", "retry_cleared": None,
        "resized_gone": None,
        "silent_before": None, "silent": "no output for 30s", "silent_counts": "no output for 45s",
        "silent_idle": None, "silent_closed": None, "silent_no_byte": None,
        "precedence_retry": "reconnecting…",
        "grace": [3000, 30000],
    }  # fmt: skip


@pytest.mark.unit
def test_the_focus_wires_the_mark_to_the_socket_and_the_feed():
    """The wiring around `AO.termMark`: the bridge's `{grid}` frame is read beside the
    `read_only` one, before the backoff reset (the attach's own word, not pane output); a pane byte
    clears a pending reconnect and restarts the silence; a retry stamps `retryAt` once; the feed's
    state reaches the mark; each event goes to the console as `[shiftlead] terminal …`; the page
    carries the slot, hidden."""
    js = APP.read_text()
    body = js[js.index("ws.onmessage = (m) => {\n") :]
    body = body[: body.index("\n      };\n")]
    assert body.index("if (c && Array.isArray(c.grid))") < body.index("delay = 500;")
    assert '"clients" in c' not in js and "resized by another client" not in js
    assert body.index("mk.lastByte = t;") < body.index("delay = 500;")
    assert "if (mk.retryAt != null) { mk.retryAt = null; drawMark(); }" in body
    assert "if (mk.retryAt == null) mk.retryAt = Date.now();" in js
    assert "mk.state = ev.session.state; drawMark();" in js
    # a session that turns working counts its silence from then, not from the quiet idle before it
    assert 'if (ev.session.state === "working" && mk.lastByte != null) mk.lastByte = Date.now();' in js
    assert 'console.info("[shiftlead] terminal", ...a, new Date().toISOString())' in js
    for event in ('tlog("open")', 'tlog("closed", e.code, e.reason || "")', 'tlog("grid"', "tlog(`output after"):
        assert event in js, event
    html = (UI / "templates" / "focus.html").read_text()
    assert '<span class="badge termmark hidden" id="ftermmark"></span>' in html


@pytest.mark.integration
def test_the_grid_reading_is_what_tmux_says_for_the_window():
    """Against a private tmux server: the bridge's reading of a detached session's window, its status bar's line
    counted as a client's grid counts it."""
    if not shutil.which("tmux"):
        pytest.skip("tmux is not installed")
    sock = f"ao-mark-{uuid.uuid4().hex[:8]}"
    try:
        new = ["new", "-d", "-s", "m", "-x", "90", "-y", "20"]
        subprocess.run(["tmux", "-L", sock, "-f", "/dev/null", *new], check=True, timeout=10)
        out = subprocess.run(grid_argv("m", socket_name=sock), capture_output=True, text=True, timeout=10)
        assert out.returncode == 0, out.stderr
        assert grid_read(out.stdout) == (90, 21)
    finally:
        subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True, timeout=10)
