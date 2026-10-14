"""The UI's two listeners and their checks (design §4.5b *The route port*, *Origin and Host*, TD-647 slice 1).

The checks are driven through `listener.Gate` around a small app, as each listener wraps the real one;
the process — both servers on one loop, one SIGTERM, a route port another process holds, a node —
runs `shiftlead-ui` itself on free ports and a temp home.
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient, WebSocketDenialResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from sessionorc import settings
from shiftlead.ui import listener
from shiftlead.ui.common import page_origin

pytestmark = pytest.mark.unit

URL = "https://home.tail1234.ts.net"
LOGIN = "paul@example.com"


async def _echo(request: Request) -> JSONResponse:
    return JSONResponse({"shiftlead": request.scope.get("shiftlead"), "origin": page_origin(request)})


async def _ws(ws: WebSocket) -> None:
    await ws.accept()
    await ws.send_json(ws.scope.get("shiftlead"))
    await ws.close()


inner = Starlette(routes=[Route("/", _echo, methods=["GET", "POST"]), WebSocketRoute("/events", _ws)])


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    return tmp_path


def _reach(**over):
    doc = {"route": "tailscale", "url": URL, "allow": [LOGIN], **over}
    settings.save({"reach": doc})


def _client(which: str, base: str, **kw) -> TestClient:
    return TestClient(listener.Gate(inner, which, reach=listener.Reach(every=0), **kw), base_url=base)


def _route() -> TestClient:
    return _client("route", URL)


def _plain(**kw) -> TestClient:
    return _client("plain", "http://127.0.0.1:8765", **kw)


ID = {"tailscale-user-login": LOGIN}


def _ws_url(c: TestClient, path: str) -> str:
    return str(c.base_url).rstrip("/").replace("http", "ws", 1) + path  # its Host is the base URL's


def _denied(c: TestClient, path: str, headers: dict) -> None:
    with (
        pytest.raises((WebSocketDisconnect, WebSocketDenialResponse)),
        c.websocket_connect(_ws_url(c, path), headers=headers) as ws,
    ):
        ws.receive_json()


# -- the reader --------------------------------------------------------------------------------------


def test_a_hand_written_reach_is_read_and_a_malformed_one_refused(home):
    _reach(allow=["Paul@Example.com"])
    got = settings.reach(settings.load())
    assert got == {"route": "tailscale", "url": URL, "allow": [LOGIN]}
    for bad in (
        {"route": "wireguard", "url": URL, "allow": [LOGIN]},
        {"route": "tailscale", "url": "http://home", "allow": [LOGIN]},
        {"route": "tailscale", "url": URL + "/path", "allow": [LOGIN]},
        {"route": "tailscale", "url": URL, "allow": "paul"},
        {"route": "tailscale", "url": URL},
        {"route": "tailscale", "url": URL, "allow": [LOGIN], "port": 1},
    ):
        with pytest.raises(ValueError):
            settings.parse_reach(bad)
        assert settings.reach({"reach": bad}) is None  # a malformed route lets nobody in
    assert settings.reach({}) is None


def test_reach_is_read_from_the_file_with_no_host_agent(home):
    """The route outlives the agent (§4.5b): the route port reads settings.yml itself — no agent runs here."""
    _reach()
    r = _route().get("/", headers=ID)
    assert r.status_code == 200 and r.json()["shiftlead"] == {"listener": "route", "origin": URL}


# -- the route port ----------------------------------------------------------------------------------


def test_the_route_port_with_no_reach_refuses_everything(home):
    r = _route().get("/", headers=ID)
    assert r.status_code == 403 and "reach:" in r.text
    assert r.headers["x-shiftlead-listener"] == "route"


def test_a_tailscale_login_in_allow_is_served_and_others_refused(home):
    _reach()
    c = _route()
    ok = c.get("/", headers={"tailscale-user-login": "PAUL@example.com"})
    assert ok.status_code == 200 and ok.json()["origin"] == URL  # page_origin is reach.url's
    assert ok.headers["x-shiftlead-listener"] == "route"
    assert c.get("/").status_code == 403  # no login: a tagged device, Funnel
    other = c.get("/", headers={"tailscale-user-login": "eve@example.com"})
    assert other.status_code == 403 and "not in reach.allow" in other.text
    _reach(allow=[])
    assert c.get("/", headers=ID).status_code == 403  # an empty allow lets nobody in


def test_an_encoded_login_is_compared_decoded(home):
    _reach(allow=["jürgen@example.com"])
    enc = "=?utf-8?q?j=C3=BCrgen@example.com?="
    assert listener.decode_login(enc) == "jürgen@example.com"
    assert _route().get("/", headers={"tailscale-user-login": enc}).status_code == 200


def test_a_cloudflare_route_is_refused_naming_its_entry(home):
    _reach(route="cloudflare", team="t", aud="a")
    r = _route().get("/", headers={"cf-access-jwt-assertion": "x.y.z"})
    assert r.status_code == 403 and "TD-656" in r.text


def test_the_route_port_websocket_needs_the_identity_and_the_origin(home):
    _reach()
    c = _route()
    with c.websocket_connect(_ws_url(c, "/events"), headers={**ID, "origin": URL}) as ws:
        assert ws.receive_json() == {"listener": "route", "origin": URL}
    _denied(c, "/events", {"origin": URL})  # no login
    _denied(c, "/events", {"tailscale-user-login": "eve@example.com", "origin": URL})
    _denied(c, "/events", ID)  # no Origin
    _denied(c, "/events", {**ID, "origin": "https://evil.example"})
    _denied(c, "/events", {**ID, "origin": "http://home.tail1234.ts.net"})  # http against an https reach.url


def test_the_route_port_checks_host_and_origin(home):
    _reach()
    c = _route()
    assert c.get("/", headers={**ID, "host": "rebound.example"}).status_code == 421
    assert c.get("/", headers={**ID, "host": "HOME.tail1234.ts.net:443"}).status_code == 200
    assert c.post("/", headers={**ID, "origin": URL}).status_code == 200
    assert c.post("/", headers={**ID, "origin": URL + ":443"}).status_code == 200  # a default port elided
    assert c.post("/", headers=ID).status_code == 403  # a POST with no Origin
    assert c.post("/", headers={**ID, "sec-fetch-site": "same-origin"}).status_code == 200
    foreign = {**ID, "origin": "https://evil.example", "sec-fetch-site": "same-origin"}
    assert c.post("/", headers=foreign).status_code == 403  # a present Origin must match, whatever else


# -- the plain port ----------------------------------------------------------------------------------


def test_the_plain_port_serves_loopback_names_and_allow_hosts(home):
    c = _plain()
    r = c.get("/")
    assert r.status_code == 200 and r.json()["shiftlead"] == {"listener": "plain", "origin": "http://127.0.0.1:8765"}
    assert r.headers["x-shiftlead-listener"] == "plain"
    assert c.get("/", headers={"host": "localhost:9000"}).status_code == 200  # an ssh -L from another port
    assert c.get("/", headers={"host": "[::1]:8765"}).status_code == 200
    rebound = c.get("/", headers={"host": "rebound.example"})
    assert rebound.status_code == 421 and "--allow-host" in rebound.text
    assert _plain(allow_hosts=["Home.lan"]).get("/", headers={"host": "home.lan:8765"}).status_code == 200
    private = _plain(bind="10.0.0.5", allow_hosts=["box.lan"])
    assert private.get("/", headers={"host": "box.lan"}).status_code == 200
    assert private.get("/", headers={"host": "10.0.0.5:8765"}).status_code == 200
    assert private.get("/", headers={"host": "rebound.example"}).status_code == 421


def test_the_plain_port_refuses_each_proxy_header(home):
    c = _plain()
    for h in listener.PROXY_HEADERS:
        r = c.get("/", headers={h: "x"})
        assert r.status_code == 403 and "point the proxy at the route port" in r.text, h
        assert "tailscale serve --https=443 off" in r.text and "127.0.0.1:8766" in r.text


def test_the_interim_serve_gets_the_route_port_page_not_a_421(home):
    """§4.5b *Until the route port exists*: a `tailscale serve` aimed at 8765 sends its identity and a
    `*.ts.net` Host; the proxy refusal is judged first, so the phone reads the steps that move it."""
    r = _plain().get("/", headers={"host": "home.tail1234.ts.net", **ID})
    assert r.status_code == 403 and "route port" in r.text


def test_the_plain_port_refuses_foreign_origins(home):
    c = _plain()
    assert c.post("/", headers={"origin": "http://127.0.0.1:8765"}).status_code == 200
    assert c.post("/", headers={"origin": "http://evil.example"}).status_code == 403
    assert c.post("/").status_code == 403
    with c.websocket_connect(_ws_url(c, "/events"), headers={"origin": "http://127.0.0.1:8765"}) as ws:
        assert ws.receive_json()["listener"] == "plain"
    _denied(c, "/events", {"origin": "http://evil.example"})
    _denied(c, "/events", {})


# -- the log and the count ---------------------------------------------------------------------------


def test_a_refusal_is_logged_without_a_token_and_counted(home, caplog):
    c = _plain()
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        r = c.get("/", headers={"cf-access-jwt-assertion": "SECRET.TOKEN.VALUE"})
    assert r.status_code == 403
    assert r.headers["x-shiftlead-refused"].split()[0] == "1"
    warn = [x for x in caplog.records if x.levelno == logging.WARNING and "refused on the plain port" in x.getMessage()]
    assert warn and "SECRET" not in caplog.text
    ok = c.get("/")
    assert ok.headers["x-shiftlead-refused"].split()[0] == "1"  # every answer carries the count


def test_a_loopback_probe_of_the_route_port_is_logged_at_info_and_not_counted(home, caplog):
    c = _client("route", "http://127.0.0.1:8766")
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        r = c.get("/")
    assert r.status_code == 403 and r.headers["x-shiftlead-refused"].split()[0] == "0"
    rec = [x for x in caplog.records if "refused on the route port" in x.getMessage()]
    assert rec and all(x.levelno == logging.INFO for x in rec)


def test_host_and_origin_parsing():
    assert listener.host_name("Home:80") == "home"
    assert listener.host_name("[::1]:8765") == "::1"
    assert listener.origin_of("https://h") == listener.origin_of("https://H:443") == ("https", "h", 443)
    assert listener.origin_of("null") is None
    assert listener.origin_of("http://u@h") is None and listener.origin_of("http://h/x") is None


# -- the process: both servers on one loop -----------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ui(home: Path, *args: str) -> subprocess.Popen:
    env = {**os.environ, "SHIFTLEAD_HOME": str(home), "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    env.pop("SHIFTLEAD_SESSION", None)
    code = "import sys; from shiftlead.ui.app import main; sys.exit(main(sys.argv[1:]))"
    return subprocess.Popen(
        [sys.executable, "-c", code, *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )


def _get(port: int) -> tuple[int, dict]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/static/app.css", timeout=2) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)


def _upgrade(port: int) -> str:
    """The status line a real server answers a websocket upgrade of `/events` with."""
    req = (
        f"GET /events HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", port), timeout=3) as s:
        s.sendall(req.encode())
        return s.recv(200).decode("latin-1")


def _up(port: int, proc: subprocess.Popen, timeout: float = 20) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end and proc.poll() is None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _stop(proc: subprocess.Popen) -> str:
    if proc.poll() is None:
        proc.terminate()
    try:
        out, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return out


def test_both_listeners_serve_and_one_sigterm_stops_both(home):
    plain, route = _free_port(), _free_port()
    proc = _ui(home, "--port", str(plain), "--route-port", str(route))
    try:
        assert _up(plain, proc) and _up(route, proc)
        status, h = _get(plain)
        assert status == 200 and h["x-shiftlead-listener"] == "plain"
        status, h = _get(route)
        assert status == 403 and h["x-shiftlead-listener"] == "route"  # no reach: set
        assert _upgrade(route).startswith("HTTP/1.1 403")  # a refused websocket is refused at its upgrade
        assert _upgrade(plain).startswith("HTTP/1.1 403")  # no Origin
        proc.terminate()
        proc.wait(timeout=10)
        for port in (plain, route):
            with pytest.raises(OSError), socket.create_connection(("127.0.0.1", port), timeout=0.5):
                pass
    finally:
        _stop(proc)


def test_a_held_route_port_leaves_the_plain_port_serving(home):
    plain = _free_port()
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    route = holder.getsockname()[1]
    proc = _ui(home, "--port", str(plain), "--route-port", str(route))
    try:
        assert _up(plain, proc)
        assert _get(plain)[0] == 200
    finally:
        out = _stop(proc)
        holder.close()
    assert f"route port {route} not bound" in out


def test_route_port_0_and_a_node_run_no_route_listener(home):
    plain = _free_port()
    proc = _ui(home, "--port", str(plain), "--route-port", "0")
    try:
        assert _up(plain, proc) and _get(plain)[0] == 200
    finally:
        out = _stop(proc)
    assert "route port" not in out
    (home / "hosts.yml").write_text("home: elsewhere\n")
    plain, route = _free_port(), _free_port()
    proc = _ui(home, "--port", str(plain), "--route-port", str(route))
    try:
        assert _up(plain, proc)
        with pytest.raises(OSError), socket.create_connection(("127.0.0.1", route), timeout=0.5):
            pass
    finally:
        out = _stop(proc)
    assert "no route listener: not the home" in out
