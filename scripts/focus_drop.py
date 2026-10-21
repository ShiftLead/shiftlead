#!/usr/bin/env python3
"""A dropped Focus on demand (design §4.6 *The disconnect card*, TD-923): open a session's Focus in headless
Chromium, hold its terminal socket and its `/events` stream closed for a while, write a screenshot of the
page once the terminal mark's grace has passed — the *reconnecting…* mark and the disconnect card — then
let the terminal back and check that the mark and the card go on its first pane byte.

    "$HOME/.local/share/shiftlead-venv/bin/python" scripts/focus_drop.py <session> [--for 20] [--shot path]
    scripts/focus_drop.py <session> --url http://127.0.0.1:<port>   # a scratch home (scripts/look_home.py)

The browser is the smoke's (`scripts/smoke.py --setup` makes its venv once, at a person's hand); without
it, or under an interpreter that has Playwright, it says why and writes nothing. The UI is the live one,
at the installed unit's address, unless `--url` names another.

Nothing it does is a press. Playwright's `route` does not reach a WebSocket, so an init script stands in
for `window.WebSocket` on `/term/` and `/events` while the hold lasts: the terminal's first socket opens
(the page takes its Spend reading there, as at every reconnect) and closes with 1006 a moment later
without ever reaching the server, and each retry closes with 1006 — so no attach is made while it holds.
The release lets the page's next retry through: one attach, as any browser opening the Focus makes, read
until its first pane byte; `--no-release` leaves before it.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke import SMOKE_VENV, UNAVAILABLE, address  # noqa: E402

GRACE = 3.0  # AO.TERM_GRACE, in seconds: the mark and the card wait it out
BYTE_BOUND = 30.0  # seconds the released terminal may take to paint

# The stand-in socket (see the docstring). `__aoHold` is this page's alone: the reload the events stream
# makes once it is back starts a page with no hold.
SHIM = """
(() => {
  const Real = window.WebSocket;
  window.__aoHold = true; window.__aoBytes = 0; let first = true;
  const held = (u) => u.includes("/term/") || u.includes("/events");
  window.WebSocket = function (url, protocols) {
    const u = String(url);
    if (!window.__aoHold || !held(u)) {
      const ws = protocols === undefined ? new Real(url) : new Real(url, protocols);
      if (u.includes("/term/")) ws.addEventListener("message", (m) => { if (typeof m.data !== "string") window.__aoBytes++; });
      return ws;
    }
    const opens = first && u.includes("/term/");
    if (opens) first = false;
    const fake = { readyState: 0, binaryType: "blob", url: u, send() {}, close() {},
      onopen: null, onmessage: null, onclose: null, onerror: null, addEventListener() {}, removeEventListener() {} };
    setTimeout(() => {
      if (opens) { fake.readyState = 1; if (fake.onopen) fake.onopen(new Event("open")); }
      setTimeout(() => {
        fake.readyState = 3;
        if (!opens && fake.onerror) fake.onerror(new Event("error"));
        if (fake.onclose) fake.onclose({ code: 1006, reason: "", wasClean: false });
      }, opens ? 1500 : 30);
    }, 30);
    return fake;
  };
  window.WebSocket.prototype = Real.prototype;
  for (const k of ["CONNECTING", "OPEN", "CLOSING", "CLOSED"]) window.WebSocket[k] = Real[k];
})();
"""

SHOWN = "() => { const d = document.getElementById('fdrop'); return !!d && !d.classList.contains('hidden'); }"
CLEARED = """() => window.__aoBytes > 0
  && document.getElementById('ftermmark').classList.contains('hidden')
  && document.getElementById('fdrop').classList.contains('hidden')"""


def run(base: str, sid: str, hold: float, shot: Path, scheme: str, release: bool) -> int:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        b = pw.chromium.launch()
    except Exception as e:  # no Playwright, no Chromium: the venv's fault, nothing written
        print(f"focus_drop: cannot start a browser ({type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''})")
        return UNAVAILABLE
    try:
        pg = b.new_page(viewport={"width": 1400, "height": 900}, color_scheme=scheme)
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script(SHIM)
        pg.goto(f"{base}/focus/{urllib.parse.quote(sid, safe='')}", wait_until="load")
        try:
            pg.wait_for_function(SHOWN, timeout=(GRACE + 5) * 1000)
        except PlaywrightTimeout:
            print("focus_drop: the disconnect card did not show within the mark's grace", file=sys.stderr)
            return 1
        mark = pg.text_content("#ftermmark") or ""
        box = pg.locator("#fdrop").bounding_box() or {"y": 0, "height": 0}
        bottom = min(900, box["y"] + box["height"] + 160)  # the card and the terminal's retry lines under it
        shot.parent.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(shot), clip={"x": 0, "y": 0, "width": 1400, "height": bottom})
        print(f"focus_drop: mark {mark!r}; card: {' / '.join(pg.inner_text('#fdrop').splitlines())}")
        print(f"focus_drop: wrote {shot}")
        if not release:
            return 0
        pg.wait_for_timeout(max(0.0, hold - GRACE) * 1000)
        pg.evaluate("window.__aoHold = false")
        try:
            pg.wait_for_function(CLEARED, timeout=BYTE_BOUND * 1000)
        except PlaywrightTimeout:
            print("focus_drop: released, but the mark or the card stayed past the first pane byte", file=sys.stderr)
            return 1
        print("focus_drop: released; the mark and the card went with the first pane byte")
        if errors:
            print(f"focus_drop: script error on the page: {errors[0].splitlines()[0]}", file=sys.stderr)
            return 1
        return 0
    finally:
        try:
            b.close()
        finally:
            pw.stop()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="focus_drop.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("session", help="the session's id, as its Focus URL carries it")
    ap.add_argument("--for", dest="hold", type=float, default=20.0, help="seconds to hold the sockets closed")
    ap.add_argument("--shot", type=Path, default=Path("focus_drop.png"), help="where the screenshot goes")
    ap.add_argument("--url", help="the UI's base URL (default: the installed unit's address)")
    ap.add_argument("--scheme", choices=("dark", "light"), default="dark")
    ap.add_argument("--no-release", action="store_true", help="leave once the screenshot is written")
    args = ap.parse_args(argv)
    try:
        import playwright  # noqa: F401
    except ImportError:
        python = SMOKE_VENV / "bin" / "python"
        if not python.exists() or os.environ.get("AO_FOCUS_DROP_CHILD"):
            print("focus_drop skipped: run scripts/smoke.py --setup")
            return UNAVAILABLE
        os.environ["AO_FOCUS_DROP_CHILD"] = "1"
        os.execv(str(python), [str(python), str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])])
    if args.url:
        base = args.url.rstrip("/")
    else:
        host, port = address()
        base = f"http://{host}:{port}"
    return run(base, args.session, max(args.hold, GRACE), args.shot, args.scheme, not args.no_release)


if __name__ == "__main__":
    sys.exit(main())
