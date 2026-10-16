"""A reconnect reloads once, never in a loop (design §4.5 *Browser mechanics*, TD-692, TD-694).

On 2026-10-14 three open tabs reloaded every second or two for two hours, and the UI logged nothing: a
stream that failed at each open sent `error`, which the page took as *up*, so its second socket reloaded
it every time. The page now takes `error` as not up, bounds its reloads on a stream's return to three a
minute, and the UI warns of a page opening `/events` in a loop and logs its own handler's failure."""

from __future__ import annotations

import json
import logging
import pathlib
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from shiftlead.ui import fanout
from shiftlead.ui.common import static_url
from shiftlead.ui.fanout import OPENS_LIMIT, Every, OpenRate

APP = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui" / "static" / "app.js"
BASE = APP.parent.parent / "templates" / "base.html"

# Under node, with a fake clock, a fake socket and a fake `sessionStorage` that outlive a page's load:
# `load(path)` evaluates app.js afresh, as a reload does, and `location.reload()` only counts — the
# scenario makes the next load itself.
PROBE = r"""
const fs = require("fs");
const SRC = fs.readFileSync(process.argv[2], "utf8");
const noop = () => {};
let now = 1e9, timers = [];
Date.now = () => now;
const advance = (ms) => {
  const end = now + ms;
  for (;;) {
    timers.sort((a, b) => a.at - b.at);
    const t = timers[0];
    if (!t || t.at > end) break;
    timers.shift(); now = t.at; t.f();
  }
  now = end;
};
global.setTimeout = (f, ms) => { const t = { f, at: now + (ms || 0) }; timers.push(t); return t; };
global.clearTimeout = (t) => { timers = timers.filter((x) => x !== t); };
global.setInterval = noop;
let store = {}, throws = false;
global.sessionStorage = {
  getItem: (k) => { if (throws) throw new Error("denied"); return k in store ? store[k] : null; },
  setItem: (k, v) => { if (throws) throw new Error("denied"); store[k] = String(v); },
  removeItem: (k) => { if (throws) throw new Error("denied"); delete store[k]; },
};
let sockets = [];
global.WebSocket = class {
  constructor(url) { this.url = url; this.readyState = 0; this.at = now; sockets.push(this); }
  send() {}
  close() { if (this.closed) return; this.closed = true; this.readyState = 3; if (this.onclose) this.onclose(); }
};
const cls = () => {
  const s = new Set();
  return { toggle: (c, on) => (on ? s.add(c) : s.delete(c)), add: (c) => s.add(c), remove: (c) => s.delete(c),
    contains: (c) => s.has(c) };
};
const el = () => {
  const on = {};
  return { dataset: {}, style: {}, classList: cls(), appendChild: noop, querySelector: () => null,
    querySelectorAll: () => [], contains: () => false,
    addEventListener: (t, f) => { on[t] = f; }, fire: (t) => on[t] && on[t]() };
};
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
let reloads = 0, reloaded = false, toasts = [], shown = 0, banner, btn, AO;
function load(path) {
  timers = []; sockets = []; reloaded = false;
  banner = el(); btn = el();
  let hidden = true;
  Object.defineProperty(banner, "hidden", {
    get: () => hidden, set: (v) => { if (hidden && !v) shown++; hidden = v; } });
  global.window = { addEventListener: noop };
  global.document = { documentElement: el(), body: el(), addEventListener: noop, createElement: () => el(),
    querySelectorAll: () => [], visibilityState: "visible", currentScript: { src: "/static/app.js?v=abc123" },
    querySelector: (s) => (s === "#reloadloop" ? banner : s === "#reloadloopbtn" ? btn : null) };
  global.location = { pathname: path, protocol: "http:", host: "x", href: "http://x" + path,
    reload: () => { reloads++; reloaded = true; } };
  eval(SRC);
  AO = window.AO;
  AO.toast = (t) => toasts.push(t);
}
const sock = () => sockets[sockets.length - 1];
const say = (ev) => { const s = sock(); s.readyState = 1; s.onmessage({ data: JSON.stringify(ev) }); };
const ERROR = { event: "error", text: "events stream failed; reconnecting" };
const REAL = { event: "session", session: { id: "s1" } };
const reset = () => { store = {}; throws = false; reloads = 0; toasts = []; shown = 0; };
const out = {};

// 1. a stream that sends only `error` and closes: no reload, one toast, the page's handler never called,
// the backoff growing to its cap — on each page's stream (the Org's, the repo page's, Focus's light one)
out.error_only = {};
for (const [path, query] of [["/", ""], ["/repo/r", ""], ["/focus/s1", "light=1&focus=s1"]]) {
  reset(); load(path);
  let handled = 0;
  AO.connectEvents(() => handled++, query);
  for (let i = 0; i < 9; i++) { say(ERROR); sock().close(); advance(10000); }
  out.error_only[path] = { reloads, toasts: toasts.length, handled, url: sockets[0].url };
}
// 2. the backoff: each reopen waits from the close — 500 ms, then doubling to 10 s, never put back by `error`
reset(); load("/");
AO.connectEvents(noop, "");
out.backoff = [];
for (let i = 0; i < 8; i++) {
  say(ERROR); const closed = now; sock().close(); advance(20000); out.backoff.push(sock().at - closed);
}

// 3. `error`, a close, then a real message: one reload — and the messages that still arrive before the
// page goes are the same reload, counted once
reset(); load("/repo/r");
AO.connectEvents(noop, "");
say(ERROR); sock().close(); advance(1000); say(REAL); say(REAL); say(REAL);
out.error_then_real = { reloads, stored: JSON.parse(store["ao.reloads:/repo/r"]).length };

// 4. a stream that comes up, then closes, each time: three reloads in a minute, then the fourth is held
reset();
let handled = [];
const page = () => {
  load("/focus/s1"); handled = []; AO.connectEvents((ev) => handled.push(ev.event), "light=1&focus=s1");
};
page();
for (let i = 0; i < 6 && !(shown); i++) {
  say(REAL); sock().close(); advance(600); say(REAL);
  if (reloaded) { advance(1000); page(); }
}
out.loop = { reloads, shown, handled: handled.length, stored: JSON.parse(store["ao.reloads:/focus/s1"]).length };
// 5. later messages patch the page, and a second return draws no second banner
say({ event: "session", session: { id: "s2" } });
sock().close(); advance(1000); say(REAL);
out.after = { reloads, shown, handled: handled.length };
// 5b. a message past the window, on the same stream, patches too: the page took the stream as its own (TD-699)
advance(61000); say(REAL);
out.later = { reloads, shown, handled: handled.length };
// 6. **Reload** clears the count
btn.fire("click");
out.reload_button = { reloads, stored: store["ao.reloads:/focus/s1"] === undefined,
  mark: store["ao.reloading:/focus/s1"] === undefined };
// 7. a load the page did not make clears the count; one it made keeps it
store["ao.reloads:/x"] = JSON.stringify([now, now, now]);
load("/x");
out.own_load_clears = store["ao.reloads:/x"] === undefined;
store["ao.reloads:/x"] = JSON.stringify([now]); store["ao.reloading:/x"] = "1";
load("/x");
out.its_reload_keeps = store["ao.reloads:/x"] !== undefined && store["ao.reloading:/x"] === undefined;
// 8. storage that throws counts nothing: the page reloads as before, every time
reset(); throws = true;
page();
for (let i = 0; i < 6; i++) { say(REAL); sock().close(); advance(600); say(REAL); advance(1000); page(); }
out.throws = { reloads, shown };
// 9. a minute later the count has aged out
reset(); store["ao.reloads:/y"] = JSON.stringify([now - 61000, now - 61000, now - 61000]);
store["ao.reloading:/y"] = "1";
load("/y"); AO.connectEvents(noop, ""); say(REAL); sock().close(); advance(600); say(REAL);
out.aged = { reloads, shown };
console.log(JSON.stringify(out));
"""


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    return node


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    node = _node()
    path = tmp_path_factory.mktemp("reload") / "reload_probe.js"
    path.write_text(PROBE)
    run = subprocess.run([node, str(path), str(APP)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.unit
def test_a_stream_that_sends_only_error_never_reloads_and_toasts_once_on_every_page(probe):
    for path in ("/", "/repo/r", "/focus/s1"):
        assert probe["error_only"][path] == {
            "reloads": 0, "toasts": 1, "handled": 0, "url": probe["error_only"][path]["url"],
        }, path  # fmt: skip
    # the stream says the page's script hash and its path, beside the page's own query
    assert probe["error_only"]["/focus/s1"]["url"] == "ws://x/events?light=1&focus=s1&page=abc123&at=%2Ffocus%2Fs1"
    assert probe["error_only"]["/"]["url"] == "ws://x/events?page=abc123&at=%2F"


@pytest.mark.unit
def test_a_stream_that_sends_only_error_reconnects_with_growing_delays(probe):
    assert probe["backoff"] == [500, 1000, 2000, 4000, 8000, 10000, 10000, 10000]


@pytest.mark.unit
def test_error_a_close_then_a_real_message_reloads_once(probe):
    assert probe["error_then_real"] == {"reloads": 1, "stored": 1}


@pytest.mark.unit
def test_three_reloads_in_a_minute_hold_back_the_fourth_and_draw_the_banner(probe):
    # the load's first message and the held-back one, which is the page's own: its handler patched from both
    assert probe["loop"] == {"reloads": 3, "shown": 1, "handled": 2, "stored": 3}


@pytest.mark.unit
def test_after_a_held_back_reload_later_messages_patch_and_no_second_banner(probe):
    assert probe["after"] == {"reloads": 3, "shown": 1, "handled": 4}


@pytest.mark.unit
def test_a_held_back_page_keeps_the_stream_past_the_window(probe):
    """TD-699: the held-back page clears its *reconnected* mark, so a message more than a minute on,
    when the recorded reloads have aged out, patches the page rather than reloading it."""
    assert probe["later"] == {"reloads": 3, "shown": 1, "handled": 5}


@pytest.mark.unit
def test_reload_clears_the_count_and_so_does_a_load_the_page_did_not_make(probe):
    assert probe["reload_button"] == {"reloads": 4, "stored": True, "mark": True}
    assert probe["own_load_clears"] is True
    assert probe["its_reload_keeps"] is True
    assert probe["aged"] == {"reloads": 1, "shown": 0}


@pytest.mark.unit
def test_storage_that_throws_reloads_as_before(probe):
    assert probe["throws"] == {"reloads": 6, "shown": 0}


@pytest.mark.unit
def test_the_banner_is_on_every_page_and_no_page_handles_error_itself():
    """One banner, in the base template every page extends, with §4.5a's words; `connectEvents` handles
    `error` before any page's handler, so no handler has an `error` branch of its own."""
    base = BASE.read_text()
    assert 'id="reloadloop" hidden>This page reloaded 3 times in a minute when its stream came back, so it' in base
    assert 'stopped; what it shows may be behind. <span class="grow"></span><button' in base
    assert ">Reload</button></div>" in base
    src = APP.read_text()
    assert src.count('ev.event === "error"') == 1


# -- the UI's two log lines ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_open_rate_warns_past_the_limit_once_in_ten_minutes():
    rate = OpenRate()
    assert [rate.opened("a", "/x", t) for t in range(OPENS_LIMIT)] == [None] * OPENS_LIMIT
    assert rate.opened("a", "/x", 20.5) == OPENS_LIMIT + 1
    assert [rate.opened("a", "/x", 21 + t / 10) for t in range(30)] == [None] * 30  # told once
    # ten minutes on, a loop still running is told again
    assert [rate.opened("a", "/x", 700 + t / 10) for t in range(OPENS_LIMIT)] == [None] * OPENS_LIMIT
    assert rate.opened("a", "/x", 703) == OPENS_LIMIT + 1


@pytest.mark.unit
def test_twenty_opens_over_two_paths_or_two_minutes_write_nothing():
    rate = OpenRate()
    assert all(rate.opened("a", f"/{t % 2}", t) is None for t in range(OPENS_LIMIT * 2))
    rate = OpenRate()
    assert all(rate.opened("a", "/x", t * 3.0) is None for t in range(OPENS_LIMIT * 3))  # 20 a minute at most
    assert rate._opens.keys() == {("a", "/x")} and len(rate._opens[("a", "/x")]) == 20  # the table stays small


@pytest.mark.unit
def test_every_is_due_once_a_minute():
    every = Every(60.0)
    assert [every.due(t) for t in (0, 1, 59.9, 60, 61, 125)] == [True, False, False, True, False, True]


def _failing_client(monkeypatch, tmp_path):
    """A UI whose host agent answers everything empty, and whose every stream fails at its start."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            return {"entries": []} if method == "inbox" else {}

        async def subscribe(self, omit=None):
            if False:
                yield {}

    def join(self, st):
        raise RuntimeError("the stream fails at its start")

    from shiftlead.ui import app as ui

    monkeypatch.setattr(ui, "LocalClient", Fake)
    monkeypatch.setattr(fanout.Fanout, "join", join)
    return TestClient(ui.create_app())


def _open(c, query: str) -> dict:
    with c.websocket_connect(f"/events?{query}") as ws:
        while True:
            try:
                ev = json.loads(ws.receive_text())
            except WebSocketDisconnect:
                return {}
            if ev.get("event") == "error":
                return ev


@pytest.mark.unit
def test_a_page_in_a_loop_is_one_warning_and_a_failing_stream_one_traceback(monkeypatch, tmp_path, caplog):
    c = _failing_client(monkeypatch, tmp_path)
    caplog.set_level(logging.WARNING, logger="uvicorn.error")
    for _ in range(OPENS_LIMIT + 5):
        assert _open(c, "page=old123&at=/repo/r")["text"] == fanout.FAILED
    for _ in range(5):
        _open(c, "page=old123&at=/focus/s1")
    warnings = [r.getMessage() for r in caplog.records if r.getMessage().startswith("events: ")]
    v = static_url("app.js").partition("?v=")[2]  # *this UI serves*: the UI's own link to its script
    assert warnings == [
        f"events: testclient opened /events {OPENS_LIMIT + 1} times in 60s from '/repo/r'"
        f" (page 'old123', this UI serves {v})"
    ]
    failed = [r for r in caplog.records if r.getMessage() == "the events handler failed"]
    assert len(failed) == 1 and failed[0].exc_info and "fails at its start" in str(failed[0].exc_info[1])


@pytest.mark.unit
def test_what_the_client_says_is_cut_and_kept_on_its_stream(monkeypatch, tmp_path, caplog):
    c = _failing_client(monkeypatch, tmp_path)
    caplog.set_level(logging.WARNING, logger="uvicorn.error")
    seen: list[tuple[str, str]] = []
    real = fanout.Stream.__init__

    def init(self, *a, **k):
        real(self, *a, **k)
        seen.append((self.page, self.at))

    monkeypatch.setattr(fanout.Stream, "__init__", init)
    long = "p" * 300
    for _ in range(OPENS_LIMIT + 1):
        _open(c, f"page={long}&at=/{long}")
    assert seen[0] == ("p" * 100, "/" + "p" * 99)
    (w,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("events: ")]
    assert f"from '/{'p' * 99}' (page '{'p' * 100}'" in w
