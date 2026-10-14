"""`ao connect` and `ao doctor`'s **route** line (design §4.7, §4.5b, TD-648): the person's route to the
UI's route port — checked step by step, a step it cannot take named as a *lacking:* line in
`ao doctor`'s words, and `reach:` written through `set_reach` only when the route works.

It runs the provider's own commands as the person and never `sudo`; it creates no account and holds
no key. Every outside call — a command, a port asked, the probe's fetch, the agent — comes in as a
callable, so each check is tested against a faked provider.
"""

from __future__ import annotations

import http.client
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from shiftlead import doctor
from shiftlead.service import DEFAULT_PORT, DEFAULT_ROUTE_PORT

INSTALL_PAGE = "https://tailscale.com/download"
DNS_PAGE = "https://login.tailscale.com/admin/dns"
PROBE_AFTER = 10.0  # seconds the UI's read of `reach:` is given before the probe (§4.7)
ASK_WAIT = 3.0
PROBE_WAIT = 15.0
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}

Run = Callable[[list[str]], tuple[int, str, str]]
Ask = Callable[[int], dict[str, Any]]


class Lacking(Exception):
    """A step `ao connect` cannot take: its text is the *lacking: route — …* line, naming the cure."""


def run(argv: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    """A provider command as the person: `(returncode, stdout, stderr)`; a missing binary or a hang
    is a failed command, never an exception."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", f"{type(e).__name__}: {e}"
    return p.returncode, p.stdout, p.stderr


def _answer(url: str, timeout: float, host: str | None = None) -> dict[str, Any]:
    """One GET: `{status, listener, refused}` from any answer, a refusal's included; `{status: None}`
    when nothing answered, with `why`."""
    req = urllib.request.Request(url, headers={"Host": host} if host else {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # never an http_proxy's answer
    try:
        with opener.open(req, timeout=timeout) as r:
            status, headers = r.status, r.headers
    except urllib.error.HTTPError as e:
        status, headers = e.code, e.headers
    except http.client.HTTPException as e:  # something answered, not in HTTP: another process
        return {"status": 0, "listener": None, "refused": None, "why": f"{type(e).__name__}: not an HTTP answer"}
    except (OSError, ValueError) as e:
        return {"status": None, "listener": None, "refused": None, "why": str(getattr(e, "reason", e))}
    return {
        "status": status,
        "listener": headers.get("X-Shiftlead-Listener"),
        "refused": headers.get("X-Shiftlead-Refused"),
    }


def ask_port(port: int, timeout: float = ASK_WAIT) -> dict[str, Any]:
    """A port's state by asking it (§4.5b *The ports*): `down` when nothing answers, `ui` when the
    answer carries `X-Shiftlead-Listener` (the UI's own, `listener` saying which), `other` otherwise."""
    got = _answer(f"http://127.0.0.1:{port}/", timeout, host=f"127.0.0.1:{port}")
    state = "down" if got["status"] is None else "ui" if got["listener"] else "other"
    return {"port": port, "state": state, **got}


def holder(port: int, run: Run = run) -> str:
    """Who holds a port, from `ss -lptn`: *pid 4121 (python3)*, or *another process* unread."""
    _, out, _ = run(["ss", "-lptnH", f"sport = :{port}"])
    m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', out)
    return f"pid {m.group(2)} ({m.group(1)})" if m else "another process"


def ports(plain: int, route: int, ask: Ask = ask_port, run: Run = run) -> dict[str, Any]:
    """Both ports asked: the UI running, and the route port its own. A lack stops `ao connect`."""
    p = ask(plain)
    if p["state"] == "down":
        raise Lacking("the UI is not running (`ao service install`)")
    if p["state"] == "other":
        raise Lacking(f"port {plain} is not the UI's: held by {holder(plain, run)}")
    r = ask(route)
    if r["state"] == "down":
        raise Lacking(f"port {route} not bound: the UI runs no route listener there (`ao service install`)")
    if r["state"] == "other" or r.get("listener") != "route":
        raise Lacking(f"port {route} not bound: held by {holder(route, run)}")
    return {"plain": p, "route": r}


def _json(run: Run, argv: list[str]) -> tuple[dict[str, Any] | None, str]:
    rc, out, err = run(argv)
    if rc != 0:
        return None, (err or out).strip()
    try:
        got = json.loads(out or "{}")
    except ValueError:
        return None, f"{' '.join(argv)} printed no JSON"
    return (got if isinstance(got, dict) else {}), ""


def _target_port(target: str) -> tuple[bool, int | None]:
    """A serve handler's proxy target as `(loopback, port)`: `http://127.0.0.1:8766` is `(True, 8766)`."""
    u = urlsplit(target if "://" in target else f"http://{target}")
    try:
        port = u.port
    except ValueError:
        port = None
    return (u.hostname or "") in _LOOPBACK, port


def handler(serve: dict[str, Any], dns: str) -> tuple[str | None, bool]:
    """`(target, any)` of the tailnet's HTTPS 443 in `tailscale serve status --json`: the proxy the
    root path is served by, and whether 443 is served at all (a TCP forward has no target)."""
    web = (serve.get("Web") or {}).get(f"{dns}:443") or {}
    target = ((web.get("Handlers") or {}).get("/") or {}).get("Proxy")
    served = bool(web) or "443" in (serve.get("TCP") or {})
    return (str(target) if target else None), served


def ours(target: str | None, route: int) -> bool:
    """`ao connect`'s own handler (§4.7 *Its own handler*): a 443 handler aimed at the route port."""
    if not target:
        return False
    loop, port = _target_port(target)
    return loop and port == route


def tailscale(
    allow: list[str],
    route: int,
    plain: int,
    run: Run = run,
    linux: bool = sys.platform.startswith("linux"),
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """The checks of `ao connect tailscale`, in §4.7's order, before anything is written: installed,
    logged in, `serve` allowed without root, HTTPS on, a login to allow, 443 free or already this
    route's, Funnel off. Answers `{url, allow, ours}`; the first step it cannot take is a `Lacking`."""
    if which("tailscale") is None:
        raise Lacking(f"tailscale is not installed: install it from {INSTALL_PAGE}")
    st, why = _json(run, ["tailscale", "status", "--json"])
    if st is None or st.get("BackendState") != "Running":
        raise Lacking("tailscale is not logged in: run `tailscale up` and open the link it prints")
    serve, why = _json(run, ["tailscale", "serve", "status", "--json"])
    if serve is None:
        if linux and re.search(r"access denied|permission|operator|root", why, re.I):
            raise Lacking("tailscale serve needs root here: run `sudo tailscale set --operator=$USER`")
        raise Lacking(f"tailscale serve status failed: {why or 'no reason given'}")
    if not st.get("CertDomains"):
        raise Lacking(f"HTTPS is off for the tailnet: turn on MagicDNS and HTTPS Certificates at {DNS_PAGE}")
    me = st.get("Self") or {}
    dns = str(me.get("DNSName") or "").rstrip(".")
    if not dns:
        raise Lacking(f"tailscale names no DNS name for this node: turn on MagicDNS at {DNS_PAGE}")
    if me.get("Tags") and not allow:
        raise Lacking("this node is tagged: name your login with `--allow`")
    owner = ((st.get("User") or {}).get(str(me.get("UserID"))) or {}).get("LoginName")
    logins = allow or ([owner] if owner else [])
    if not logins:
        raise Lacking("no login to allow: tailscale names no owner for this node — name yours with `--allow`")
    target, served = handler(serve, dns)
    if served and not ours(target, route):
        loop, port = _target_port(target) if target else (False, None)
        if loop and port == plain:
            raise Lacking(
                f"HTTPS 443 serves the plain port {plain} (the interim, §4.5b): run "
                "`tailscale serve --https=443 off` first, then `ao connect tailscale`"
            )
        raise Lacking(
            f"HTTPS 443 is already served ({target or 'another handler'}): ao connect never replaces another serve"
        )
    if (serve.get("AllowFunnel") or {}).get(f"{dns}:443"):
        raise Lacking(
            "Funnel is on for 443: Funnel would put the UI on the internet — `tailscale funnel --https=443 off`"
        )
    return {"url": f"https://{dns}", "allow": logins, "ours": ours(target, route)}


def probe(url: str, fetch: Callable[[str], dict[str, Any]] | None = None) -> str | None:
    """The route's URL fetched over the tailnet (§4.7 *The probe*): None when an answer marked `route`
    came back that is not a `421`; else what it got, in words."""
    got = (fetch or (lambda u: _answer(u, PROBE_WAIT)))(url)
    if got.get("status") is None:
        return f"{url} did not answer ({got.get('why') or 'no reason given'})"
    if got.get("listener") == "route" and got["status"] != 421:
        return None
    if got["status"] == 421:
        return f"{url} answered 421: the proxy rewrote Host"
    if got.get("listener") == "plain":
        return f"{url} reached the plain port, not the route port"
    return f"{url} answered {got['status']} from something not the UI"


def connect_tailscale(
    allow: list[str],
    route: int,
    plain: int,
    set_reach: Callable[[dict[str, Any] | None], dict[str, Any]],
    *,
    run: Run = run,
    ask: Ask = ask_port,
    fetch: Callable[[str], dict[str, Any]] | None = None,
    sleep: Callable[[float], None] | None = None,
    say: Callable[[str], None] = print,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """`ao connect tailscale` (§4.7): the ports asked, the checks, then in this order — `reach:`
    written, `tailscale serve --bg --https=443 http://127.0.0.1:<route>` unless it is already this
    route's, the probe once the UI has had `PROBE_AFTER` to read the setting. A probe that fails
    restores the `reach:` there before and turns off the handler if this run added it."""
    import time

    ports(plain, route, ask, run)
    got = tailscale(allow, route, plain, run, which=which)
    reach = {"route": "tailscale", "url": got["url"], "allow": got["allow"]}
    before = set_reach(reach).get("before")
    added = False

    def undo() -> str:
        """The handler this run added turned off first, then the setting there before restored: a
        restore that fails (a hand-written `reach:` the RPC refuses) still leaves no handler up."""
        said = []
        if added:
            rc, out, err = run(["tailscale", "serve", "--https=443", "off"])
            said.append(
                "the handler it added turned off"
                if rc == 0
                else f"`tailscale serve --https=443 off` failed: {(err or out).strip()}"
            )
        try:
            set_reach(before)
            said.insert(0, "the setting restored")
        except Exception as e:  # noqa: BLE001 — named, never raised over the failure being undone
            said.insert(0, f"the setting there before could not be restored ({e}): fix settings.yml's reach: by hand")
        return " and ".join(said)

    try:
        if not got["ours"]:
            rc, out, err = run(["tailscale", "serve", "--bg", "--https=443", f"http://127.0.0.1:{route}"])
            if rc != 0:
                why = (err or out).strip() or "no reason given"
                if re.search(r"access denied|permission|operator|root", why, re.I):
                    why += " — run `sudo tailscale set --operator=$USER`"
                raise Lacking(f"tailscale serve failed: {why} — {undo()}")
            added = True
        say(f"checking {got['url']} in {PROBE_AFTER:.0f}s, once the UI has read the route…")
        (sleep or time.sleep)(PROBE_AFTER)
        why = probe(got["url"], fetch)
    except Lacking:
        raise
    except BaseException:  # an interrupt or a failure mid-way: undone before it goes on up
        undo()
        raise
    if why:
        raise Lacking(f"the probe failed: {why} — {undo()}")
    return {**reach, "added": added}


def off(
    reach: dict[str, Any] | None,
    route: int,
    set_reach: Callable[[dict[str, Any] | None], dict[str, Any]],
    *,
    run: Run = run,
) -> list[str]:
    """`ao connect off` (§4.7): `reach:` removed, and for `tailscale` only its own handler turned off —
    never `serve reset`; for `cloudflare` the tunnel and the Access application stay the person's.
    Answers what it did, a line each."""
    done: list[str] = []
    set_reach(None)
    done.append("reach: removed from settings.yml" if reach else "no reach: was set")
    if (reach or {}).get("route", "tailscale") == "tailscale":
        st, _ = _json(run, ["tailscale", "status", "--json"])
        serve, _ = _json(run, ["tailscale", "serve", "status", "--json"])
        dns = str(((st or {}).get("Self") or {}).get("DNSName") or "").rstrip(".")
        target, _ = handler(serve or {}, dns) if dns else (None, False)
        if ours(target, route):
            rc, out, err = run(["tailscale", "serve", "--https=443", "off"])
            done.append(
                f"tailscale serve on 443 turned off (it pointed at 127.0.0.1:{route})"
                if rc == 0
                else f"tailscale serve --https=443 off failed: {(err or out).strip()}"
            )
    else:
        done.append("the tunnel and its Access application are yours, left as they are")
    return done


def _refused(answer: dict[str, Any] | None) -> str:
    """` · 3 refused since 09:12` from a port's `X-Shiftlead-Refused: <n> <start>`; nothing at none."""
    raw = str((answer or {}).get("refused") or "").split()
    if not raw or not raw[0].isdigit() or raw[0] == "0":
        return ""
    return f" · {raw[0]} refused since {_clock(raw[1] if len(raw) > 1 else '')}"


def _clock(iso: str) -> str:
    """The UI's start (`2026-10-14T09:12:00Z`) as local *09:12*; *the UI's start* unread."""
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError:
        return "the UI's start"


def route_line(
    reach: dict[str, Any] | None,
    plain: int = DEFAULT_PORT,
    route: int = DEFAULT_ROUTE_PORT,
    *,
    node: bool = False,
    ask: Ask = ask_port,
    run: Run = run,
) -> list[dict[str, Any]]:
    """`ao doctor`'s **route** line (§4.7): the route as `ao connect` with no argument reads it, each
    port asked. No route is a warning (`ssh -L` may be meant); a UI not running, a route port held by
    another process, or a serve no longer aimed at the route port is lacking. Ends with the refusals
    the UI counted since it started, which say nothing about health."""
    if node:
        return [doctor._row("route", doctor.HOME, "route — the home's")]
    p = ask(plain)
    if p["state"] == "down":
        return [doctor._row("route", doctor.LACKING, "route — the UI is not running (`ao service install`)")]
    r = ask(route)
    tail = _refused(r if r["state"] == "ui" else p)
    if r["state"] != "ui" or r.get("listener") != "route":
        held = "not bound" if r["state"] == "down" else f"not bound: held by {holder(route, run)}"
        return [doctor._row("route", doctor.LACKING, f"route — port {route} {held}{tail}")]
    if not reach:
        text = "route — none set; the UI is reached over `ssh -L` (`ao connect tailscale`)"
        return [doctor._row("route", doctor.WARNING, text + tail)]
    if reach.get("route") == "tailscale":
        st, _ = _json(run, ["tailscale", "status", "--json"])
        serve, _ = _json(run, ["tailscale", "serve", "status", "--json"])
        dns = str(((st or {}).get("Self") or {}).get("DNSName") or "").rstrip(".")
        target, _ = handler(serve or {}, dns) if dns else (None, False)
        if not ours(target, route):
            text = "route — tailscale serve no longer points at the route port (`ao connect tailscale`)"
            return [doctor._row("route", doctor.LACKING, text + tail, reach=reach)]
    allows = ", ".join(reach.get("allow") or [])
    text = f"route — {reach.get('route')}, {reach.get('url')}, allows {allows}"
    return [doctor._row("route", doctor.OK, text + tail, reach=reach)]
