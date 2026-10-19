"""`scripts/smoke.py`, this repo's smoke (design §6 *The smoke*, *This repo's smoke*; TD-812): against a stub
server and a stub `ao`, never the live UI."""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from shiftlead import service

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "smoke.py"
PAGE = b"<!doctype html><html><body>ok</body></html>\n"
BIG = b"<!doctype html><html><body>" + b"<p>row</p>" * 20_000 + b"</body></html>\n"  # ~195 KB, ~1 KB gzipped
TIMING = "rpc_list;dur=12, inbox;dur=210.4, render;dur=250.5, total;dur=480"


def _load():
    spec = importlib.util.spec_from_file_location("smoke", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sm = _load()


@pytest.fixture
def stub():
    """A UI that answers every page with `TIMING` as its `Server-Timing`, and `behave[route]` to break one: an
    int is its status, `cut` a body with no `</html>`, `short` a body cut short of its Content-Length, a float
    seconds of delay, `coldslow` 0.25 s of delay on the route's first load alone, `big` a page past the budget's
    150 KB sent plain, `gzip` the same page gzipped to a request that takes it, `badgzip` that gzip with its
    deflate stream broken. `seen` is every route asked."""
    behave: dict[str, object] = {}
    seen: list[str] = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            b = behave.get(self.path)
            if isinstance(b, float):
                time.sleep(b)
            if b == "coldslow" and seen.count(self.path) == 1:
                time.sleep(0.25)
            body = PAGE[:20] if b == "cut" else BIG if b in ("big", "gzip") else PAGE
            zipped = b in ("gzip", "badgzip") and "gzip" in (self.headers.get("Accept-Encoding") or "")
            body = gzip.compress(body) if zipped else body
            body = body[:10] + b"\xff" * 8 + body[18:] if b == "badgzip" else body  # a deflate stream that breaks
            self.send_response(b if isinstance(b, int) else 200)
            self.send_header("Server-Timing", TIMING)
            if zipped:
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body) + (100 if b == "short" else 0)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield srv.server_address[1], behave, seen
    srv.shutdown()
    srv.server_close()


def _unit(tmp_path: Path, port: int, bind: str = "127.0.0.1") -> Path:
    u = tmp_path / "shiftlead-ui.service"
    u.write_text(service.unit_text("shiftlead-ui", bind=bind, port=port))
    return u


def _ao(tmp_path: Path, fail: str | None = None, prose: str | None = None) -> str:
    """A stub `ao` that answers JSON, or exits 2 on the subcommand `fail`, or exits 0 printing prose on the
    subcommand `prose`; it logs every argv."""
    a = tmp_path / "ao"
    a.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> {tmp_path}/ao.log\n'
        f'[ "$1" = "{fail}" ] && {{ echo "boom: $1" >&2; exit 2; }}\n'
        f'[ "$1" = "{prose}" ] && {{ echo "not json"; exit 0; }}\n'
        "echo '{\"ok\": true}'\n"
    )
    a.chmod(0o755)
    return str(a)


def _run(tmp_path, port, capsys, **kw):
    kw.setdefault("unit", _unit(tmp_path, port))
    kw.setdefault("venv", tmp_path / "no-venv")
    if "ao" not in kw:
        kw["ao"] = _ao(tmp_path)
    code = sm.smoke(wait_bound=kw.pop("wait_bound", 3.0), **kw)
    lines = capsys.readouterr().out.strip().splitlines()
    return code, lines


def test_the_page_list_has_no_focus_and_the_reads_no_inbox():
    routes = [r for _, r in sm.PAGES]
    assert routes == ["/", "/inbox", "/queue", "/repo/shiftlead", "/settings"]
    assert not any(r.startswith("/focus") for r in routes)
    assert all(a[0] != "inbox" for a in sm.AO_READS)
    assert sm.PAGE_BOUND == 20.0 and sm.WAIT_BOUND == 90.0


def test_the_address_is_the_units_bind_and_port_and_the_defaults_without_one(tmp_path):
    assert sm.address(_unit(tmp_path, 8799, "100.64.0.5")) == ("100.64.0.5", 8799)
    assert sm.address(_unit(tmp_path, 8799, "0.0.0.0")) == ("127.0.0.1", 8799)
    u = tmp_path / "shiftlead-ui.service"
    u.write_text("[Service]\nExecStart=/v/bin/shiftlead-ui\n")
    assert sm.address(u) == ("127.0.0.1", service.DEFAULT_PORT)
    assert sm.address(tmp_path / "absent.service") == ("127.0.0.1", service.DEFAULT_PORT)
    assert sm.address(_unit(tmp_path, 8799, "::1")) == ("::1", 8799)  # the base brackets it
    assert sm.DEFAULT_PORT == service.DEFAULT_PORT and sm.UNIT == service.UNIT_DIR / "shiftlead-ui.service"


def test_a_healthy_ui_passes_with_a_line_per_load_and_the_browser_half_skipped(tmp_path, stub, capsys):
    port, _, seen = stub
    code, lines = _run(tmp_path, port, capsys)
    assert code == 0 and lines[-1] == f"smoke passed; {sm.SKIPPED}"
    assert sorted(seen) == sorted(r for _, r in sm.PAGES for _ in range(2))  # each page twice: cold, then judged
    inbox = [ln for ln in lines if ln.startswith("Inbox /inbox · ")]
    steps = "rpc_list 12 ms, inbox 210 ms, render 250 ms, total 480 ms"  # the page's `Server-Timing`, in its order
    assert inbox[0].startswith("Inbox /inbox · cold · 200 · first byte ")
    assert inbox[1].startswith("Inbox /inbox · 200 · first byte ")
    assert all(ln.endswith(f"· {len(PAGE)} bytes · {steps}") for ln in inbox) and len(inbox) == 2
    assert (tmp_path / "ao.log").read_text().splitlines() == ["status --json", "repo --json", "promote status --json"]


@pytest.mark.parametrize(
    ("behave", "why"),
    [
        (500, "smoke failed: Queue /queue: status 500"),
        ("cut", "smoke failed: Queue /queue: the body does not end its </html> (20 bytes)"),
        (0.8, "smoke failed: Queue /queue: no answer within 0.5 s"),
        ("short", "smoke failed: Queue /queue: IncompleteRead"),
        ("badgzip", "smoke failed: Queue /queue: its gzipped body does not read: "),
    ],
)
def test_each_page_failure_is_the_last_line(tmp_path, stub, capsys, behave, why):
    port, b, _ = stub
    b["/queue"] = behave
    code, lines = _run(tmp_path, port, capsys, bound=0.5)
    assert code == 1 and lines[-1].startswith(why)


def test_a_page_over_its_budget_is_told_with_its_longest_step_and_fails_nothing(tmp_path, stub, capsys):
    """§4.5 *Page loads*' budget, told on the last line — the promote's note (§6 *This repo's smoke*, TD-881):
    first byte by page, the HTML on the wire, and the judged load alone."""
    port, b, _ = stub
    b.update({"/settings": 0.25, "/inbox": "big", "/queue": "gzip"})
    code, lines = _run(tmp_path, port, capsys)
    assert code == 0 and lines[-1].startswith("smoke passed; Inbox over budget: 195 KB of HTML over 150 KB")
    told = lines[-1].split("; ")
    assert told[1] == "Inbox over budget: 195 KB of HTML over 150 KB — longest step render 250 ms"
    assert told[2].startswith("Settings over budget: first byte 0.2") and told[2].endswith(
        " s over 0.2 s — longest step render 250 ms"
    )
    assert told[3:] == [sm.SKIPPED]  # the Queue, gzipped on the wire, is under; so is every other page
    queue = [ln for ln in lines if ln.startswith("Queue /queue · ")]
    assert all(f"· {len(gzip.compress(BIG))} bytes ·" in ln for ln in queue)  # what the wire carried
    b.clear()
    code, lines = _run(tmp_path, port, capsys)
    assert code == 0 and lines[-1] == f"smoke passed; {sm.SKIPPED}"  # every page under: nothing told


def test_the_budget_judges_the_second_load_not_the_cold_one(tmp_path, stub, capsys):
    """Each page is loaded twice and the second judged (§6 *This repo's smoke*, TD-886): a slow cold load tells
    nothing."""
    port, b, _ = stub
    b["/settings"] = "coldslow"
    code, lines = _run(tmp_path, port, capsys)
    settings = [ln for ln in lines if ln.startswith("Settings /settings · ")]
    assert settings[0].startswith("Settings /settings · cold · 200 · first byte ")
    assert float(settings[0].split("first byte ")[1].split(" s")[0]) >= 0.2  # the cold load was over its budget
    assert code == 0 and lines[-1] == f"smoke passed; {sm.SKIPPED}"


def test_a_failing_page_keeps_its_steps_on_its_line(tmp_path, stub, capsys):
    """A page answering 500 still says where its time went: its `Server-Timing` is read off the error (TD-886)."""
    port, b, _ = stub
    b["/queue"] = 500
    code, lines = _run(tmp_path, port, capsys)
    queue = [ln for ln in lines if ln.startswith("Queue /queue · ")]
    assert code == 1 and queue and queue[0].endswith("rpc_list 12 ms, inbox 210 ms, render 250 ms, total 480 ms")


def test_the_budget_is_the_designs():
    assert sm.BUDGET == {"/": 0.5, "/inbox": 0.5, "/queue": 0.5, "/repo/shiftlead": 0.5, "/settings": 0.2}
    assert set(sm.BUDGET) == {r for _, r in sm.PAGES}
    assert sm.WIRE_BUDGET == 150 * 1024 and sm.DOM_BUDGET == 1.0
    assert sm.steps_of("a;dur=1.5, b;desc=x, c;desc=y;dur=3") == [("a", 1.5), ("c", 3.0)]


def test_a_ui_that_never_answers_fails_and_an_ao_read_that_fails_names_it(tmp_path, stub, capsys):
    port, _, _ = stub
    code, lines = _run(tmp_path, sm_free_port(), capsys, wait_bound=0)
    assert code == 1 and lines[-1].startswith("smoke failed: the UI did not answer on 127.0.0.1:")
    code, lines = _run(tmp_path, port, capsys, ao=_ao(tmp_path, fail="repo"))
    assert code == 1 and lines[-1] == "smoke failed: ao repo --json exited 2: boom: repo"
    # exit 0 is not enough: each read answers JSON (the module's docstring)
    code, lines = _run(tmp_path, port, capsys, ao=_ao(tmp_path, prose="promote"))
    assert code == 1 and lines[-1] == "smoke failed: ao promote status --json: its output is not JSON"


def sm_free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_reach_loads_are_told_and_a_refusal_fails_nothing(tmp_path, stub, capsys):
    port, _, _ = stub
    srv_reach = _Refusing()  # the route the person uses: the Org cut short, the Queue refused
    try:
        code, lines = _run(tmp_path, port, capsys, reach=srv_reach.url)
    finally:
        srv_reach.close()
    assert code == 0
    assert any(ln.startswith("reach Sessions / · 200") for ln in lines)
    assert any(ln.startswith("reach (fails nothing): Sessions /: IncompleteRead") for ln in lines)
    assert "reach (fails nothing): Queue /queue: status 403" in lines
    assert lines[-1].startswith("smoke passed; reach refused /: IncompleteRead")
    assert lines[-1].endswith(f"; reach refused /queue: status 403; {sm.SKIPPED}")


class _Refusing:
    """A reach route that cuts the Org's body short and refuses the Queue."""

    def __init__(self):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                ok = self.path != "/queue"
                self.send_response(200 if ok else 403)
                self.send_header("Content-Length", str(len(PAGE) + (100 if ok else 0)))
                self.end_headers()
                self.wfile.write(PAGE)

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def _venv(tmp_path: Path, rows: list[dict], code: int = 0) -> Path:
    """A stand-in smoke venv whose `python` prints the browser half's JSON lines."""
    v = tmp_path / "venv"
    (v / "bin").mkdir(parents=True)
    py = v / "bin" / "python"
    out = "".join(f"echo '{json.dumps(r)}'\n" for r in rows)
    py.write_text(f'#!/bin/sh\n[ "$2" = "--browser" ] || exit 9\n{out}exit {code}\n')
    py.chmod(0o755)
    return v


def test_the_browser_half_runs_under_the_smoke_venv_and_a_script_error_fails(tmp_path, stub, capsys):
    port, _, _ = stub
    ok = [{"page": p, "route": r, "error": None} for p, r in sm.PAGES]
    code, lines = _run(tmp_path, port, capsys, venv=_venv(tmp_path / "a", ok))
    assert code == 0 and lines[-1] == "smoke passed" and "browser Queue /queue · ok" in lines
    bad = [*ok[:2], {"page": "Queue", "route": "/queue", "error": "script error: TypeError: x is undefined"}]
    code, lines = _run(tmp_path, port, capsys, venv=_venv(tmp_path / "b", bad))
    assert code == 1 and lines[-1] == "smoke failed: Queue /queue: script error: TypeError: x is undefined"
    code, lines = _run(tmp_path, port, capsys, venv=_venv(tmp_path / "c", ok[:1], code=4))
    assert code == 1 and lines[-1].startswith("smoke failed: the browser half exited 4")
    # a venv that cannot start a browser is the venv's fault, not the build's: skipped, failing nothing
    code, lines = _run(tmp_path, port, capsys, venv=_venv(tmp_path / "d", [], code=sm.UNAVAILABLE))
    assert code == 0 and lines[-1] == "smoke passed; browser half skipped: the smoke venv cannot start a browser"
    # each load's line carries the browser half's DOM ready, and the judged one is held to the budget
    dom = [{**r, "dom": [1500, 1200] if r["route"] == "/queue" else [400, 300]} for r in ok]
    code, lines = _run(tmp_path, port, capsys, venv=_venv(tmp_path / "e", dom))
    queue = [ln for ln in lines if ln.startswith("Queue /queue · ")]
    assert "· DOM ready 1.50 s ·" in queue[0] and "· DOM ready 1.20 s ·" in queue[1]
    over = "Queue over budget: DOM ready 1.20 s over 1 s — longest step render 250 ms"
    assert code == 0 and lines[-1] == f"smoke passed; {over}"


def test_the_shiftlead_yml_names_the_smoke():
    import yaml

    block = yaml.safe_load((SCRIPT.parent.parent / ".shiftlead.yml").read_text())["promote"]
    assert "scripts/smoke.py" in block["smoke"] and "shiftlead-venv/bin/python" in block["smoke"]
    with pytest.raises(SystemExit):
        sm.main(["--help"])


def test_setup_makes_the_venv_with_the_headless_shell_and_names_a_failed_step(tmp_path, monkeypatch, capsys):
    ran: list[list[str]] = []
    fail_at: list[int] = []

    def run(cmd, *a, **kw):
        ran.append(cmd)
        return types.SimpleNamespace(returncode=1 if len(ran) in fail_at else 0)

    monkeypatch.setattr(sm.subprocess, "run", run)
    assert sm.main(["--setup"]) == 0  # the CLI's own route, in SMOKE_VENV
    assert [c[1:3] for c in ran] == [["-m", "venv"], ["install", "-q"], ["-m", "playwright"]]
    assert ran[0][3] == str(sm.SMOKE_VENV) and ran[1][0] == str(sm.SMOKE_VENV / "bin" / "pip")
    assert ran[2][-3:] == ["install", "--only-shell", "chromium"]  # the headless shell, never the full browser
    assert capsys.readouterr().out.strip().splitlines()[-1] == f"the smoke's browser half is set up in {sm.SMOKE_VENV}"
    ran.clear()
    fail_at.append(2)
    assert sm.setup(tmp_path / "v") == 1 and len(ran) == 2  # it stops at the failed step
    pip = tmp_path / "v" / "bin" / "pip"
    assert capsys.readouterr().out.strip().splitlines()[-1] == f"setup failed at: {pip} install -q playwright"


def test_the_reach_url_is_read_from_settings_and_handed_to_the_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    settings = tmp_path / "settings.yml"
    assert sm.reach_url() is None  # no file
    settings.write_text("reach: {route: tailscale, url: 'https://home.example.ts.net/', allow: [paul]}\n")
    assert sm.reach_url() == "https://home.example.ts.net"
    got: dict = {}
    monkeypatch.setattr(sm, "smoke", lambda **kw: got.update(kw) or 0)
    assert sm.main([]) == 0 and got == {"reach": "https://home.example.ts.net"}
    settings.write_text("reach: {route: tailscale, url: 'http://home.example.ts.net', allow: [paul]}\n")
    assert sm.reach_url() is None  # a malformed route: no reach loads, failing nothing
    settings.write_text("other: 1\n")
    assert sm.reach_url() is None


class _Page:
    """A fake Playwright page: `script` fires its `pageerror` during the load, `never` raises from `goto`."""

    def __init__(self, behave: dict[str, str], error: type):
        self.behave, self.error, self.handlers, self.loads = behave, error, {}, 0

    def on(self, event, fn):
        self.handlers[event] = fn

    def goto(self, url, wait_until, timeout):
        b = self.behave.get("/" + url.split("://", 1)[1].partition("/")[2])
        assert wait_until == "load" and timeout == 500
        if b == "script":
            self.handlers["pageerror"](RuntimeError("TypeError: x is undefined\n    at app.js:1"))
        if b == "never":
            raise self.error("Timeout 500ms exceeded.\n=== logs ===")
        self.loads += 1

    def evaluate(self, script):
        assert script == sm.DOM_READY
        return 300 if self.loads == 1 else 120  # the second load, its static files cached, is quicker

    def close(self):
        pass


def _playwright(monkeypatch, behave: dict[str, str], launch_error: Exception | None = None) -> list[str]:
    """`playwright.sync_api` faked in `sys.modules`; returns the log of what was closed and stopped."""
    log: list[str] = []

    class Error(Exception):
        pass

    class Browser:
        def new_page(self):
            return _Page(behave, Error)

        def close(self):
            log.append("browser closed")

    class Chromium:
        def launch(self):
            if launch_error:
                raise launch_error
            return Browser()

    class PW:
        chromium = Chromium()

        def stop(self):
            log.append("stopped")

    api = types.ModuleType("playwright.sync_api")
    api.Error = Error
    api.sync_playwright = lambda: types.SimpleNamespace(start=PW)
    pkg = types.ModuleType("playwright")
    pkg.sync_api = api
    monkeypatch.setitem(sys.modules, "playwright", pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    return log


def test_browse_reports_a_script_error_and_a_load_that_never_fired(monkeypatch, capsys):
    log = _playwright(monkeypatch, {"/inbox": "script", "/queue": "never"})
    assert sm.browse("http://ui", bound=0.5) == 0
    rows = {r["route"]: r for r in map(json.loads, capsys.readouterr().out.strip().splitlines())}
    assert list(rows) == [r for _, r in sm.PAGES]
    assert rows["/inbox"]["error"] == "script error: TypeError: x is undefined"
    assert rows["/queue"]["error"] == "load never fired within 0.5 s: Timeout 500ms exceeded."
    assert rows["/"]["error"] is None and rows["/settings"]["error"] is None
    assert rows["/"]["dom"] == [300, 120] and rows["/queue"]["dom"] == []  # each page loaded twice, in one page
    assert log == ["browser closed", "stopped"]


def test_browse_that_cannot_launch_is_unavailable_with_its_first_line(monkeypatch, capsys):
    _playwright(monkeypatch, {}, launch_error=RuntimeError("Executable doesn't exist at /x/chrome\nmore"))
    assert sm.browse("http://ui") == sm.UNAVAILABLE
    out = capsys.readouterr()
    assert out.out == "" and out.err.strip() == "RuntimeError: Executable doesn't exist at /x/chrome"
