"""The UI's two listeners and the checks each one wraps around the app (design §4.5b *The route port*,
*Origin and Host*, TD-647).

The **plain port** (8765) is what a browser on the home and an `ssh -L` reach; it authenticates nobody
(§4.8a), refuses what a proxy sends, and checks `Host` and `Origin`. The **route port** (8766, always
`127.0.0.1`) is the one a route's proxy is pointed at: every request and websocket upgrade on it must
carry the person's identity as the route proves it — for `tailscale`, a `Tailscale-User-Login` in
`reach.allow` — and the same `Host` and `Origin` checks against `reach.url`. Which listener a
connection came in on is known from the `Gate` that wraps it, never from `Host`.

The checks live here, in a layer outside `create_app()`, so the app's own tests are untouched and a
refused websocket is refused at its upgrade. The layer hands the app `scope["shiftlead"]`: the
listener, and the origin its absolute links use (`page_origin`).
"""

from __future__ import annotations

import asyncio
import contextlib
import email.header
import logging
import signal
import socket
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sessionorc import settings as settingsmod
from shiftlead.service import DEFAULT_ROUTE_PORT

log = logging.getLogger("uvicorn.error")  # the logger uvicorn already shows on the console

LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})
# What a proxy adds, refused on the plain port (§4.5b *The plain port refuses what a proxy sends*)
PROXY_HEADERS = (
    "tailscale-user-login",
    "tailscale-user-name",
    "cf-access-jwt-assertion",
    "cf-connecting-ip",
    "x-forwarded-for",
    "x-forwarded-host",
)
REACH_EVERY = 5.0  # seconds: the route port reads `reach:` from the file at most this often
ROUTE_RETRY = 60.0  # seconds between tries of a route port another process holds
SAFE_METHODS = ("GET", "HEAD")
DEFAULT_PORTS = {"http": 80, "https": 443}


def host_name(value: str) -> str:
    """A `Host` value case-folded with its port split off: `[::1]:8765` is `::1`, `Home:80` is `home`."""
    v = value.strip().casefold()
    if v.startswith("["):
        return v[1 : v.find("]")] if "]" in v else v
    return v.rsplit(":", 1)[0] if v.count(":") == 1 else v


def origin_of(url: str) -> tuple[str, str, int] | None:
    """`(scheme, host, port)` of an origin or URL, a default port filled in, so `https://h` and
    `https://h:443` are one; None for what is not one (`null`, a scheme with no host)."""
    try:
        u = urlsplit(url.strip())
        port = u.port
    except ValueError:
        return None
    scheme = u.scheme.casefold()
    if scheme not in DEFAULT_PORTS or not u.hostname:
        return None
    return scheme, u.hostname.casefold(), port or DEFAULT_PORTS[scheme]


def decode_login(raw: str) -> str:
    """A `Tailscale-User-Login` as decoded: Tailscale MIME-encodes a value that is not ASCII
    (`=?utf-8?q?…?=`); a value that does not decode is compared as sent."""
    try:
        parts = email.header.decode_header(raw)
    except Exception:  # noqa: BLE001 — a malformed encoded-word is the client's
        return raw.strip()
    return "".join(p.decode(c or "utf-8", "replace") if isinstance(p, bytes) else p for p, c in parts).strip()


def is_loopback(bind: str) -> bool:
    return bind.casefold() in LOOPBACK_NAMES or bind.startswith("127.")


def plain_names(bind: str, allow_hosts: Iterable[str]) -> frozenset[str]:
    """The names the plain port serves: the loopback names, each `--allow-host` on any bind, and when
    `--bind` is not loopback the bind address and the machine's own names, short and full."""
    names = set(LOOPBACK_NAMES) | {host_name(h) for h in allow_hosts if h.strip()}
    if not is_loopback(bind):
        full = socket.getfqdn()
        names |= {host_name(bind), socket.gethostname().casefold(), full.casefold(), full.split(".")[0].casefold()}
    return frozenset(names)


class Refused:
    """The count of refusals since the UI started, one for both listeners, carried on every answer as
    `X-Shiftlead-Refused: <n> <start>` (what `ao doctor`'s route line reads)."""

    def __init__(self) -> None:
        self.n = 0
        self.start = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def header(self) -> bytes:
        return f"{self.n} {self.start}".encode()


class Reach:
    """`reach:` as the route port reads it — from `settings.yml` itself through the settings reader, never
    the host agent's RPC, so the route outlives the agent — at most every `REACH_EVERY` seconds. None
    (no route, or one that is not valid) refuses everything."""

    def __init__(self, every: float = REACH_EVERY) -> None:
        self.every = every
        self._at = -float("inf")
        self._got: dict[str, Any] | None = None

    def get(self) -> dict[str, Any] | None:
        now = time.monotonic()
        if now - self._at >= self.every:
            self._got = settingsmod.reach(settingsmod.load())
            self._at = now
        return self._got


class Gate:
    """One listener's checks around the app. `listener` is `plain` or `route`; `route_port` is what the
    plain port's proxy refusal names."""

    def __init__(
        self,
        app: Any,
        listener: str,
        *,
        bind: str = "127.0.0.1",
        allow_hosts: Iterable[str] = (),
        route_port: int = DEFAULT_ROUTE_PORT,
        reach: Reach | None = None,
        refused: Refused | None = None,
    ) -> None:
        assert listener in ("plain", "route")
        self.app = app
        self.listener = listener
        self.route_port = route_port
        self.names = plain_names(bind, allow_hosts)
        self.reach = reach or Reach()
        self.refused = refused or Refused()

    # -- the checks ---------------------------------------------------------------------------------

    def judge(self, scope: dict, headers: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
        """`(refusal, origin)`: the first check that fails as `{status, check, why, cure}`, else None and
        the origin the page's links use."""
        if self.listener == "plain":
            if sent := [h for h in PROXY_HEADERS if h in headers]:
                return self._proxied(sent), ""
            host = headers.get("host", "")
            if host_name(host) not in self.names:
                return {
                    "status": 421,
                    "check": "host",
                    "why": f"this port does not serve the name {host_name(host) or '(none)'!r}",
                    "cure": [
                        f"shiftlead-ui --allow-host {host_name(host) or '<name>'}  (or ao ui / ao service install)"
                    ],
                }, ""
            origin = f"http://{host.strip()}"
            return self._origin(scope, headers, origin), origin
        reach = self.reach.get()
        if reach is None:
            return {
                "status": 403,
                "check": "reach",
                "why": "no route is set (`reach:` in settings.yml is absent or not valid)",
                "cure": [
                    "write reach: in settings.yml by hand — route: tailscale, url: https://<home>.<tailnet>.ts.net, "
                    "allow: [<your login>] (ao connect, TD-648, writes it once it is built)"
                ],
            }, ""
        want = urlsplit(reach["url"]).hostname or ""
        host = headers.get("host", "")
        if host_name(host) != want.casefold():
            return {
                "status": 421,
                "check": "host",
                "why": f"this port serves {want!r}, not {host_name(host) or '(none)'!r}",
                "cure": ["point the route at reach.url's name, or fix reach.url in settings.yml"],
            }, ""
        if refusal := self._origin(scope, headers, reach["url"]):
            return refusal, ""
        if reach["route"] == "cloudflare":
            return {
                "status": 403,
                "check": "cloudflare",
                "why": "the cloudflare route's token check is not built (TD-656)",
                "cure": ["use route: tailscale, or ssh -L 8765:127.0.0.1:8765 <home>"],
            }, ""
        login = decode_login(headers.get("tailscale-user-login", ""))
        if not login:
            return {
                "status": 403,
                "check": "identity",
                "why": "the request carries no Tailscale login (a tagged device, Funnel, or not via tailscale serve)",
                "cure": ["open the UI from a device signed in to the tailnet as a login in reach.allow"],
            }, ""
        if login.casefold() not in reach.get("allow", []):
            return {
                "status": 403,
                "check": "allow",
                "why": f"the login {login!r} is not in reach.allow",
                "cure": ["add the login to reach.allow in settings.yml"],
            }, ""
        return None, reach["url"]

    def _proxied(self, sent: list[str]) -> dict[str, Any]:
        p = self.route_port
        return {
            "status": 403,
            "check": "proxy",
            "why": f"this is the plain port; point the proxy at the route port ({p})"
            f" — the request carries {', '.join(sent)}",
            "cure": [
                "tailscale serve --https=443 off",
                f"tailscale serve --bg --https=443 http://127.0.0.1:{p}",
                "and write reach: in settings.yml (route: tailscale, url, allow) — ao connect tailscale "
                "does both once it is built (TD-648)",
            ],
        }

    @staticmethod
    def _origin(scope: dict, headers: dict[str, str], expected: str) -> dict[str, Any] | None:
        origin = headers.get("origin")
        if origin is None:
            if scope["type"] == "websocket":
                why = "a websocket upgrade must carry an Origin"
            elif scope.get("method", "GET") not in SAFE_METHODS and headers.get("sec-fetch-site") != "same-origin":
                why = f"a {scope.get('method')} must carry an Origin or Sec-Fetch-Site: same-origin"
            else:
                return None
        elif origin_of(origin) != origin_of(expected) or origin_of(origin) is None:
            why = f"the Origin {origin!r} is not this page's ({expected})"
        else:
            return None
        return {
            "status": 403,
            "check": "origin",
            "why": why,
            "cure": ["a script calling the UI sends this page's Origin"],
        }

    # -- ASGI ---------------------------------------------------------------------------------------

    def _stamp(self, message: dict) -> dict:
        extra = [(b"x-shiftlead-listener", self.listener.encode()), (b"x-shiftlead-refused", self.refused.header())]
        return {**message, "headers": [*(message.get("headers") or []), *extra]}

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers: dict[str, str] = {}
        for k, v in scope.get("headers") or []:
            headers.setdefault(k.decode("latin-1").casefold(), v.decode("latin-1"))
        refusal, origin = self.judge(scope, headers)
        if refusal is not None:
            self._log(refusal, headers)
            await self._refuse(scope, receive, send, refusal)
            return

        async def stamped(message: dict) -> None:
            if message["type"] in ("http.response.start", "websocket.accept", "websocket.http.response.start"):
                message = self._stamp(message)
            await send(message)

        await self.app({**scope, "shiftlead": {"listener": self.listener, "origin": origin}}, receive, stamped)

    def _log(self, refusal: dict[str, Any], headers: dict[str, str]) -> None:
        local = self.listener == "route" and host_name(headers.get("host", "")) in LOOPBACK_NAMES
        if not local:  # a loopback Host on the route port is a local process (the CLI's probes): not counted
            self.refused.n += 1
        log.log(
            logging.INFO if local else logging.WARNING,
            "refused on the %s port: %s (%s; Host %r, Origin %r, login %r)",
            self.listener,
            refusal["check"],
            refusal["why"],
            headers.get("host"),
            headers.get("origin"),
            decode_login(headers.get("tailscale-user-login", "")) or None,  # never a token
        )

    async def _refuse(self, scope: dict, receive: Any, send: Any, refusal: dict[str, Any]) -> None:
        from shiftlead.ui.common import templates

        body = templates.get_template("refused.html").render(listener=self.listener, **refusal).encode()
        head = self._stamp({"status": refusal["status"], "headers": [(b"content-type", b"text/html; charset=utf-8")]})
        if scope["type"] == "http":
            await send({"type": "http.response.start", **head})
            await send({"type": "http.response.body", "body": body})
            return
        await receive()  # websocket.connect
        if "websocket.http.response" in (scope.get("extensions") or {}):
            await send({"type": "websocket.http.response.start", **head})
            await send({"type": "websocket.http.response.body", "body": body})
        else:
            await send({"type": "websocket.close", "code": 1008})  # the server answers the upgrade 403


# -- running both listeners in one process -----------------------------------------------------------


def bind_route(port: int) -> socket.socket:
    """The route port's socket, bound to `127.0.0.1` whatever `--bind` says."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen(2048)
    except OSError:
        sock.close()
        raise
    sock.set_inheritable(True)
    return sock


async def serve(
    app: Any,
    *,
    bind: str,
    port: int,
    route_port: int,
    allow_hosts: Iterable[str] = (),
    is_node: bool = False,
    retry: float = ROUTE_RETRY,
) -> None:
    """Both listeners on one loop until a signal: the plain port as uvicorn binds it, the route port on a
    socket bound here, so a route port another process holds is logged and tried again each `retry`
    seconds while the plain port serves. One pair of signal handlers stops both."""
    import uvicorn

    class Server(uvicorn.Server):
        @contextlib.contextmanager
        def capture_signals(self):  # type: ignore[override]  # the process installs one pair, for both
            yield

    allow_hosts = list(allow_hosts)
    refused = Refused()
    common = {"log_level": "info", "ws_ping_interval": 20, "lifespan": "off", "proxy_headers": False}

    def gated(listener: str) -> Gate:
        # with no route listener (`--route-port 0`), the proxy refusal names the port a default install runs
        named = route_port or DEFAULT_ROUTE_PORT
        return Gate(app, listener, bind=bind, allow_hosts=allow_hosts, route_port=named, refused=refused)

    servers = [Server(uvicorn.Config(gated("plain"), host=bind, port=port, **common))]  # configures the log
    if route_port and is_node:
        log.info("no route listener: not the home")
        route_port = 0
    if route_port:
        servers.append(Server(uvicorn.Config(gated("route"), host="127.0.0.1", port=route_port, **common)))
    stopping = asyncio.Event()

    def stop() -> None:
        for s in servers:
            if s.should_exit:
                s.force_exit = True
            s.should_exit = True
        stopping.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop)

    async def route() -> None:
        while not stopping.is_set():
            try:
                sock = bind_route(route_port)
            except OSError as e:
                log.warning("route port %d not bound (%s); trying again in %ds", route_port, e, retry)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stopping.wait(), retry)
                continue
            await servers[1].serve(sockets=[sock])
            return

    async def plain() -> None:
        try:
            await servers[0].serve()
        finally:
            stop()  # the plain port ending ends the route port with it

    try:
        await asyncio.gather(plain(), *([route()] if route_port else []))
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
