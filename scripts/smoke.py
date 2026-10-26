#!/usr/bin/env python3
"""This repo's smoke (design §6 *The smoke*, *This repo's smoke*; TD-812): once a promote's `check` reads
the new commit live, load every page and read `ao` against the live copy, so a build that breaks on the
person's real state is put back within minutes. `.shiftlead.yml`'s `smoke:` runs it in the tree, under
the live venv's interpreter.

It presses nothing and changes nothing: GETs and reads only. It loads no Focus — opening one is the
person's *seen* (§4.2) and its attach sizes the pane (§4.6) — and never runs `ao inbox`, which marks
entries read (§4.10).

- It waits up to `WAIT_BOUND` for the UI's plain port, read from the installed unit's `ExecStart`
  (`--bind`, `--port`): loopback when `--bind` is absent or `0.0.0.0`, `DEFAULT_PORT` when the unit is
  absent or names no port.
- A page fails on a status other than 200, a body that does not end its `</html>`, a load past
  `PAGE_BOUND`, and in the browser half an uncaught script error or a `load` that never fires.
- Where `settings.yml` has `reach:`, the Sessions page and the Queue load once more through `reach.url`: told in the
  log, failing nothing.
- `ao status --json`, `ao repo --json`, `ao promote status --json` and `ao service status --json` must each exit 0
  with JSON, and the last's `build.built_from.commit` must be the full `SHIFTLEAD_PROMOTE_SHA` (TD-1041): a run that
  installed and then failed its restart leaves the old units serving. Skipped, with a line, when it is unset.
- Each page is loaded twice, the first printed *cold* and the second judged against §4.5 *Page loads*'
  budget (`BUDGET`, `WIRE_BUDGET`, `DOM_BUDGET`, TD-805): a page over it is told on the last line, naming
  the page and its longest `Server-Timing` step, and fails nothing (TD-881).

One log line per load (page, route, status, first byte, total, bytes on the wire, the browser half's DOM
ready, the page's `Server-Timing` steps). Exit 0 when all pass, else 1 with the first failure as the last
line; a pass's last line is *smoke passed*, then each thing told, `; `-separated.

The browser half needs Playwright and its Chromium headless shell, in a venv of their own that
`scripts/smoke.py --setup` makes once, at a person's hand, in `SMOKE_VENV` — never inside the live venv.
The script re-runs itself under that venv's python for the browser half (`--browser`); without it, the
HTTP half alone judges.

    "$HOME/.local/share/shiftlead-venv/bin/python" scripts/smoke.py
    "$HOME/.local/share/shiftlead-venv/bin/python" scripts/smoke.py --setup
"""

from __future__ import annotations

import argparse
import gzip
import http.client
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any

PAGES = (("Sessions", "/"), ("Inbox", "/inbox"), ("Queue", "/queue"), ("Repo", "/repo/shiftlead"), ("Settings", "/settings"))
REACH_PAGES = (("Sessions", "/"), ("Queue", "/queue"))  # the route the person uses: told, failing nothing
AO_READS = (
    ("status", "--json"),
    ("repo", "--json"),
    ("promote", "status", "--json"),
    ("service", "status", "--json"),  # the running build (TD-1041)
)  # never `ao inbox`
PAGE_BOUND = 20.0  # seconds a load may take: the smoke's own, not a page budget (those are TD-805's)
WAIT_BOUND = 90.0  # seconds for the UI's port to answer: the run restarts the UI after the agent
AO_BOUND = 60.0
SMOKE_VENV = Path("~/.local/share/shiftlead-smoke").expanduser()
UNIT = Path("~/.config/systemd/user/shiftlead-ui.service").expanduser()  # service.UNIT_DIR's
DEFAULT_PORT = 8765  # service.DEFAULT_PORT
SKIPPED = "browser half skipped: run scripts/smoke.py --setup"
UNAVAILABLE = 3  # `--browser`'s exit when Playwright or Chromium cannot start: the venv's fault, not the build's
# §4.5 *Page loads*' budget for a page's second load (TD-805), told and never failed: first byte by route,
# the HTML on the wire, and DOM ready, in seconds and bytes
BUDGET = {"/": 0.5, "/inbox": 0.5, "/queue": 0.5, "/repo/shiftlead": 0.5, "/settings": 0.2}
WIRE_BUDGET = 150 * 1024
DOM_BUDGET = 1.0
DOM_READY = "() => (performance.getEntriesByType('navigation')[0] || {}).domContentLoadedEventEnd ?? null"


class Failed(Exception):
    """The first failure: the smoke's last line."""


def address(unit: Path = UNIT) -> tuple[str, int]:
    """The UI's plain address from the installed unit's `ExecStart`: `--bind` (loopback when absent or
    `0.0.0.0`) and `--port` (`DEFAULT_PORT` when the unit is absent or names none)."""
    try:
        text = unit.read_text(encoding="utf-8")
    except OSError:
        text = ""
    line = next((ln.split("=", 1)[1] for ln in text.splitlines() if ln.startswith("ExecStart=")), "")
    try:
        argv = shlex.split(line)
    except ValueError:
        argv = line.split()

    def opt(name: str) -> str | None:
        for i, a in enumerate(argv):
            if a == name and i + 1 < len(argv):
                return argv[i + 1]
            if a.startswith(name + "="):
                return a.split("=", 1)[1]
        return None

    bind = opt("--bind")
    host = "127.0.0.1" if bind in (None, "", "0.0.0.0", "::") else bind
    port = opt("--port")
    return host, int(port) if port and port.isdigit() else DEFAULT_PORT


def wait_for(host: str, port: int, bound: float = WAIT_BOUND) -> None:
    """Until the port takes a connection, up to `bound` seconds."""
    end = time.monotonic() + bound
    while True:
        try:
            with socket.create_connection((host, port), timeout=2):
                return
        except OSError as e:
            if time.monotonic() >= end:
                raise Failed(f"the UI did not answer on {host}:{port} within {bound:g} s: {e}") from None
            time.sleep(1)


def load(base: str, page: str, route: str, bound: float = PAGE_BOUND) -> tuple[str, str | None]:
    """One GET: `(the log line, why it failed or None)`."""
    got = fetch(base, page, route, bound)
    return line_of(got), got["why"]


def fetch(base: str, page: str, route: str, bound: float = PAGE_BOUND) -> dict[str, Any]:
    """One GET taking gzip, as a browser does: its page, route, status, first byte and total (seconds), its
    bytes on the wire, its `Server-Timing` and why it failed (None when it did not)."""
    t0 = time.monotonic()
    first, body, status, why, timing, zipped = None, b"", None, None, "", False
    req = urllib.request.Request(base + route, headers={"Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=bound) as r:
            first, status, timing = time.monotonic() - t0, r.status, r.headers.get("Server-Timing") or ""
            body = r.read()
            zipped = (r.headers.get("Content-Encoding") or "").lower() == "gzip"
    except urllib.error.HTTPError as e:
        first, status, timing = time.monotonic() - t0, e.code, e.headers.get("Server-Timing") or ""
        body = e.read() or b""
    except (OSError, ValueError, http.client.HTTPException) as e:  # a body cut short is an IncompleteRead
        reason = getattr(e, "reason", None) or e
        if isinstance(reason, TimeoutError):  # the socket's own bound, which is the page's
            why = f"{page} {route}: no answer within {bound:g} s"
        else:
            why = f"{page} {route}: {reason}"
    total, wire = time.monotonic() - t0, len(body)
    if why is None and zipped:
        try:
            body = gzip.decompress(body)
        except (OSError, EOFError, zlib.error) as e:
            why = f"{page} {route}: its gzipped body does not read: {e}"
    if why is None and status != 200:
        why = f"{page} {route}: status {status}"
    elif why is None and not body.rstrip().lower().endswith(b"</html>"):
        why = f"{page} {route}: the body does not end its </html> ({len(body)} bytes)"
    elif why is None and total > bound:
        why = f"{page} {route}: took {total:.1f} s, past {bound:g} s"
    got = {"page": page, "route": route, "status": status, "first": first, "total": total, "bytes": wire}
    return got | {"timing": timing, "why": why}


def steps_of(header: str) -> list[tuple[str, float]]:
    """A `Server-Timing` value's steps, `(name, ms)`, in its order; one with no `dur` is left out."""
    out = []
    for part in header.split(","):
        name, _, params = part.strip().partition(";")
        dur = re.search(r"(?:^|;)\s*dur=([0-9.]+)", params)
        if name and dur:
            out.append((name.strip(), float(dur.group(1))))
    return out


def line_of(got: dict[str, Any], dom: float | None = None, cold: bool = False) -> str:
    """One load's log line: the HTTP half's numbers, the browser half's DOM ready (seconds) when it ran,
    and the page's `Server-Timing` steps."""
    first = f"{got['first']:.2f} s" if got["first"] is not None else "-"
    line = f"{got['page']} {got['route']}{' · cold' if cold else ''} · {got['status'] or '-'} · first byte {first}"
    line += f" · total {got['total']:.2f} s · {got['bytes']} bytes"
    if dom is not None:
        line += f" · DOM ready {dom:.2f} s"
    steps = steps_of(got["timing"])
    return line + (" · " + ", ".join(f"{n} {ms:.0f} ms" for n, ms in steps) if steps else "")


def over_budget(got: dict[str, Any], dom: float | None = None) -> str | None:
    """What a judged load is over §4.5 *Page loads*' budget by, with its longest `Server-Timing` step —
    the line told on the promote's note — or None when it is under."""
    over = []
    fb = BUDGET.get(got["route"])
    if fb is not None and got["first"] is not None and got["first"] > fb:
        over.append(f"first byte {got['first']:.2f} s over {fb:g} s")
    if got["bytes"] > WIRE_BUDGET:
        over.append(f"{got['bytes'] // 1024} KB of HTML over {WIRE_BUDGET // 1024} KB")
    if dom is not None and dom > DOM_BUDGET:
        over.append(f"DOM ready {dom:.2f} s over {DOM_BUDGET:g} s")
    if not over:
        return None
    steps = [s for s in steps_of(got["timing"]) if s[0] != "total"]
    longest = max(steps, key=lambda s: s[1], default=None)
    return f"{got['page']} over budget: {', '.join(over)}" + (
        f" — longest step {longest[0]} {longest[1]:.0f} ms" if longest else ""
    )


def reach_url(settings: Path | None = None) -> str | None:
    """`reach.url` from `settings.yml`, or None: absent, malformed, or the file unreadable."""
    try:
        from sessionorc import settings as settings_mod

        reach = settings_mod.reach(settings_mod.load(settings))
    except Exception:  # the reach loads fail nothing, and so does not reading them
        return None
    return (reach or {}).get("url") or None


def ao_reads(ao: str) -> tuple[list[str], dict[str, Any]]:
    """Each read must exit 0 with JSON; raises Failed on the first that does not. Returns its log lines and
    each read's JSON by its command."""
    out, got = [], {}
    for args in AO_READS:
        cmd = f"ao {' '.join(args)}"
        try:
            p = subprocess.run([ao, *args], capture_output=True, text=True, timeout=AO_BOUND, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise Failed(f"{cmd}: {e}") from None
        if p.returncode != 0:
            last = next((ln for ln in reversed((p.stderr or p.stdout).splitlines()) if ln.strip()), "")
            raise Failed(f"{cmd} exited {p.returncode}: {last}")
        try:
            got[cmd] = json.loads(p.stdout)
        except ValueError:
            raise Failed(f"{cmd}: its output is not JSON") from None
        out.append(f"{cmd} · exit 0 · {len(p.stdout)} bytes of JSON")
    return out, got


def build_check(sha: str | None, read: Any) -> str:
    """The running host agent's build — `ao service status --json`'s `build.built_from.commit` — against
    the promoted commit (design §6 *The smoke*, TD-1041): `check` reads the installed copy, so a run that
    installed and then failed its restart reads its commit with the old units serving. Returns the log
    line; raises Failed on another build, or on none. Skipped with no `sha` (a smoke run by hand)."""
    if not sha:
        return "build check skipped: no SHIFTLEAD_PROMOTE_SHA (a smoke run by hand)"
    b = read.get("build") if isinstance(read, dict) else None
    frm = b.get("built_from") if isinstance(b, dict) else None
    commit = frm.get("commit") if isinstance(frm, dict) else None
    if not isinstance(commit, str) or not commit:
        raise Failed("running build unknown")
    if commit != sha:
        raise Failed(f"running build {commit[:7]} is not the promoted {sha[:7]}")
    return f"running build {commit[:7]} is the promoted one"


def browser(
    python: Path, base: str, bound: float = PAGE_BOUND
) -> tuple[list[str], str | None, dict[str, list[float | None]]]:
    """The browser half, run as this script under `python` (`--browser`): `(log lines, why or None, each
    route's DOM ready in seconds, cold load then judged)`."""
    try:
        p = subprocess.run(
            [str(python), str(Path(__file__).resolve()), "--browser", base],
            capture_output=True, text=True, timeout=bound * 2 * len(PAGES) + 60, stdin=subprocess.DEVNULL,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], f"the browser half did not finish: {e}", {}
    lines, why, dom = [], None, {}
    if p.returncode == UNAVAILABLE:  # told, failing nothing: the build is not what broke
        last = (p.stderr.strip().splitlines() or ["no output"])[-1]
        return [
            f"browser half skipped: the smoke venv cannot start a browser ({last}); run scripts/smoke.py --setup"
        ], None, {}  # fmt: skip
    for ln in p.stdout.splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        lines.append(f"browser {r.get('page')} {r.get('route')} · {'ok' if not r.get('error') else r['error']}")
        if r.get("error") and why is None:
            why = f"{r.get('page')} {r.get('route')}: {r['error']}"
        if isinstance(r.get("dom"), list):
            dom[str(r.get("route"))] = [d / 1000 if isinstance(d, int | float) else None for d in r["dom"]]
    if why is None and p.returncode != 0:
        why = f"the browser half exited {p.returncode}: " + (p.stderr.strip().splitlines() or ["no output"])[-1]
    return lines, why, dom


def browse(base: str, bound: float = PAGE_BOUND) -> int:
    """`--browser`, under the smoke venv: each page loaded twice in headless Chromium, the second with the
    first's cache; one JSON line per page, its `error` an uncaught script error or a `load` that never
    fired, its `dom` each load's DOM ready in milliseconds (None when it was not read)."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        b = pw.chromium.launch()
    except Exception as e:  # no Playwright, no Chromium: `UNAVAILABLE`, never a failed page
        print(f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else ''}", file=sys.stderr, flush=True)
        return UNAVAILABLE
    try:
        for page, route in PAGES:
            pg = b.new_page()
            errors: list[str] = []
            pg.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            error, dom = None, []
            for _ in range(2):  # cold, then judged
                try:
                    pg.goto(base + route, wait_until="load", timeout=bound * 1000)
                    dom.append(pg.evaluate(DOM_READY))
                except PlaywrightError as e:
                    error = f"load never fired within {bound:g} s: {str(e).splitlines()[0]}"
                    break
            if errors and error is None:
                error = f"script error: {errors[0].splitlines()[0]}"
            print(json.dumps({"page": page, "route": route, "error": error, "dom": dom}), flush=True)
            pg.close()
    finally:
        try:
            b.close()
        finally:
            pw.stop()
    return 0


def setup(venv: Path = SMOKE_VENV) -> int:
    """`--setup`, at a person's hand: the smoke venv from the live venv's base interpreter, with Playwright
    and its Chromium headless shell."""
    base = getattr(sys, "_base_executable", None) or sys.executable
    steps = [
        [base, "-m", "venv", str(venv)],
        [str(venv / "bin" / "pip"), "install", "-q", "playwright"],
        [str(venv / "bin" / "python"), "-m", "playwright", "install", "--only-shell", "chromium"],
    ]
    for cmd in steps:
        print("+", " ".join(cmd), flush=True)
        if subprocess.run(cmd).returncode != 0:
            print(f"setup failed at: {' '.join(cmd)}", flush=True)
            return 1
    print(f"the smoke's browser half is set up in {venv}", flush=True)
    return 0


def smoke(
    *,
    unit: Path = UNIT,
    venv: Path = SMOKE_VENV,
    ao: str | None = None,
    reach: str | None = None,
    sha: str | None = None,
    wait_bound: float = WAIT_BOUND,
    bound: float = PAGE_BOUND,
) -> int:
    """The smoke: prints its log lines, and its verdict as the last line. 0 when everything passed. `sha` is
    the promoted commit the running build must be, None to skip that check."""
    ao = ao or str(Path(sys.executable).with_name("ao"))
    told: list[str] = []
    loads: list[dict[str, Any]] = []  # each page's two loads, printed once the browser half's DOM ready is in
    dom: dict[str, list[float | None]] = {}

    def dom_at(route: str, i: int) -> float | None:  # the browser half's DOM ready of a page's load i
        d = dom.get(route) or []
        return d[i] if i < len(d) else None

    def loads_out() -> None:
        for i, got in enumerate(loads):
            print(line_of(got, dom_at(got["route"], i % 2), cold=i % 2 == 0), flush=True)
        loads.clear()

    try:
        host, port = address(unit)
        base = f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"
        wait_for(host, port, wait_bound)
        print(f"the UI answers on {host}:{port}", flush=True)
        for page, route in PAGES:
            for _ in range(2):  # cold, then judged (§4.5 *Page loads*)
                loads.append(fetch(base, page, route, bound))
                if loads[-1]["why"]:
                    raise Failed(loads[-1]["why"])
        for page, route in REACH_PAGES if reach else ():
            line, why = load(reach.rstrip("/"), page, route, bound)
            print(f"reach {line}", flush=True)
            if why:
                told.append(f"reach refused {route}: {why.split(': ', 1)[-1]}")
                print(f"reach (fails nothing): {why}", flush=True)
        lines, got = ao_reads(ao)
        for line in lines:
            print(line, flush=True)
        print(build_check(sha, got.get("ao service status --json")), flush=True)
        python = venv / "bin" / "python"
        if python.exists():
            lines, why, dom = browser(python, base, bound)
            for line in lines:
                print(line, flush=True)
            told += [ln.split(" (", 1)[0] for ln in lines if ln.startswith("browser half skipped")]
            if why:
                raise Failed(why)
        else:
            told.append(SKIPPED)
            print(SKIPPED, flush=True)
        over = [o for got in loads[1::2] if (o := over_budget(got, dom_at(got["route"], 1)))]
        loads_out()
        told[:0] = over  # a page over its budget is told first, and fails nothing
    except Failed as e:
        loads_out()
        print(f"smoke failed: {e}", flush=True)
        return 1
    print("smoke passed" + "".join(f"; {t}" for t in told), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="smoke.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--setup", action="store_true", help=f"make the browser half's venv in {SMOKE_VENV}")
    ap.add_argument("--browser", metavar="URL", help=argparse.SUPPRESS)  # the child's own mode
    args = ap.parse_args(argv)
    if args.setup:
        return setup()
    if args.browser:
        return browse(args.browser)
    return smoke(reach=reach_url(), sha=os.environ.get("SHIFTLEAD_PROMOTE_SHA") or None)


if __name__ == "__main__":
    sys.exit(main())
