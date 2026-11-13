"""Told on Telegram when nobody is looking (design §4.10, TD-092's design, TD-319).

The home sends one Telegram message for a row that newly stops a session or a team. This module holds
what such a message says — one line from **structured fields alone** (a name, a team, a kind, a
reference: never a pending text, a question's words or a `doing` line, which a session wrote and which
would leave the machine for a third party's servers and a phone's lock screen) and the row's address
under the person's `link` — and the sender itself, run as a child of its own:

    doppler run --project <p> --config <c> -- <python> -m sessionorc.notify

with the message on stdin. `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` exist in that child's
environment for one request and nowhere else. It exits 0, or 1 with a one-line reason on stderr that
is the HTTP status or the exception's class — never the request's URL, which holds the token.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from typing import Any

HOLD = timedelta(seconds=60)  # NOTIFY_HOLD: a row is told once it has stood this long and is still there
# A row whose hold ended longer ago than this is not told: it was standing before the switch was turned
# on, or while the home was down for longer than a restart takes — *newly* stops (§4.10), never a backlog
LATE = timedelta(minutes=5)
BURST = 6  # NOTIFY_BURST: messages in BURST_WINDOW; the next reads MORE, and then nothing until it clears
BURST_WINDOW = timedelta(minutes=10)
WATCHED = timedelta(minutes=2)  # NOTIFY_WATCHED: a hold ending this soon after a visible page's read is not told
CHILD_SECONDS = 30.0  # the child's whole life, doppler's start included
PREFIX = "shiftlead"
MORE = f"{PREFIX} · and more need you — open the Inbox"
STATE_KINDS = ("permission", "question", "needs")  # the state rows told (§4.10 *What is told*)
API = "https://api.telegram.org/bot{token}/sendMessage"
REQUEST_SECONDS = 20.0
# `--push`'s own bound (TD-1322): the home kills the child at CHILD_SECONDS + REQUEST_SECONDS from its start, doppler's
# start included, so the posts get that less a margin for doppler, counted from `push_main`'s first line. Every pair
# is posted at once (at most PUSH_THREADS), and a post, or a name's resolution, still running at the deadline is
# printed *no answer* and left behind — the child ends inside the home's bound however the push services answer.
PUSH_SECONDS = CHILD_SECONDS + REQUEST_SECONDS - 10.0
PUSH_THREADS = 64


def _who(name: str, team: str) -> str:
    return f"{name} ({team})" if team else name


def state_line(name: str, team: str, kind: str) -> str:
    """A session in `needs-you`: *shiftlead · grinder-ao-1 (ao-grind) needs you: permission*."""
    what = "needs you" if kind == "needs" else f"needs you: {kind}"
    return f"{PREFIX} · {_who(name, team)} {what}"


def ask_line(name: str, team: str, ref: str) -> str:
    """An open `ask` in the person inbox: *shiftlead · grinder-ao-1 (ao-grind) asks you a question · TD-229*."""
    return f"{PREFIX} · {_who(name, team)} asks you a question" + (f" · {ref}" if ref else "")


def blocked_line(name: str, team: str, ref: str) -> str:
    """An outcome reported `blocked`: *shiftlead · grinder-ao-1 (ao-grind) reports blocked · TD-142*."""
    return f"{PREFIX} · {_who(name, team)} reports blocked" + (f" · {ref}" if ref else "")


def restart_line(name: str, team: str) -> str:
    """A record the tick could not restart: *shiftlead · ao-grind: grinder-ao-2 was not restarted*."""
    return f"{PREFIX} · {team + ': ' if team else ''}{name} was not restarted"


def work_line(team: str, n: int, finished: list[str] | None = None, stopped: bool = False) -> str:
    """A wound-down team whose lanes gained work: *shiftlead · cm-grind wound down and has work: 3 entries*;
    for a team that runs on, its finished members (§6 rule 8, TD-466): *… ao-grind's grinder-ao-1 finished
    and has work: 1 entry*; for a stopped team (TD-781): *… dc-grind stopped and has work: 1 entry*."""
    who = " stopped" if stopped else f"'s {', '.join(finished)} finished" if finished else " wound down"
    return f"{PREFIX} · {team}{who} and has work: {n} entr{'y' if n == 1 else 'ies'}"


def held_line(team: str, n: int, seats: list[str]) -> str:
    """The questions waiting on a team's seats held by its stop time (§6 rule 8 *A team that stopped*, TD-1564):
    *shiftlead · ao-grind · stopped at its stop time · 2 questions wait on techlead and fact-check* — *stopped*
    whatever the team reads, since it says who ended the team; `n` the total, the seats joined by *and*."""
    waits = f"{n} question waits" if n == 1 else f"{n} questions wait"
    return f"{PREFIX} · {team} · stopped at its stop time · {waits} on {' and '.join(seats)}"


def ci_line(owner: str, n: int) -> str:
    """An account whose CI never starts (§4.4 *CI that never started is the person's*, TD-687), its owner a
    GitHub login and the count of PRs and default branches waiting: *shiftlead · GitHub Actions does not
    start in ContractMatch · 3 waiting*."""
    return f"{PREFIX} · GitHub Actions does not start in {owner} · {n} waiting"


def test_line(home: str) -> str:
    """**Send a test**: *shiftlead · a test from kmaster*."""
    return f"{PREFIX} · a test from {home}"


def alarm_line(name: str, team: str) -> str:
    """An identity alarm on a record (§4.8a): *shiftlead · identity alarm on grinder-ao-1 (ao-grind)*."""
    return f"{PREFIX} · identity alarm on {_who(name, team)}"


def row_link(link: str, key: str) -> str:
    """The Inbox with that row scrolled to and marked: `<link>/inbox?row=<key>`."""
    return f"{link}{row_path(key)}" if link else ""


def mail_link(link: str, mid: str) -> str:
    """The message page for a question (§4.5 screen 6 *The message page*): `<link>/inbox/<id>`."""
    return f"{link}{mail_path(mid)}" if link else ""


def queue_link(link: str, card: str, row: str, mid: str) -> str:
    """A question drawn on the Queue (§4.10 *What a message says*, §4.5 screen 12 *Addresses*, TD-795): its
    card, `<link>/card/<top id>?row=<TD-n>&item=<entry id>`, its card's page, which rings the item (TD-1762)."""
    return f"{link}{queue_path(card, row, mid)}" if link else ""


def message(line: str, link: str) -> str:
    return f"{line}\n{link}" if link else line


def row_path(key: str) -> str:
    """A row's page path alone, as a push carries it (§4.10 *What a push carries*): `/inbox?row=<key>`."""
    return f"/inbox?row={urllib.parse.quote(key, safe='')}"


def mail_path(mid: str) -> str:
    return f"/inbox/{urllib.parse.quote(mid, safe='')}"


def queue_path(card: str, row: str | None, mid: str) -> str:
    """A Queue item's address, its card's page (§4.5 screen 12 *Addresses*, TD-1558, built by TD-1762):
    `/card/<card id>` with `row=` and `item=`, each percent-encoded — a card's id carries a `#`, a loose card's
    (`loose:<repo>#TD-n`) a `:` too — and no `row=` on a loose card, which has none (TD-1468)."""
    q = {"row": row, "item": mid}
    if card.startswith("loose:") or not row:
        del q["row"]
    return f"/card/{urllib.parse.quote(card, safe='')}?" + urllib.parse.urlencode(q)


def body(line: str) -> str:
    """A push's `body`: the Telegram line after *shiftlead ·*."""
    return line.removeprefix(f"{PREFIX} · ")


def argv(secrets: str, *mode: str) -> list[str]:
    """The child's command: Doppler puts the values in its environment, and nowhere else. `mode` is empty for
    Telegram's send, `--push`, `--public`, or `--key <project/config>`."""
    project, config = secrets.split("/", 1)
    return ["doppler", "run", "--project", project, "--config", config, "--", sys.executable, "-m",
            "sessionorc.notify", *mode]  # fmt: skip


_TOKENISH = re.compile(r"bot[0-9]+:[A-Za-z0-9_-]+")


def reason(text: str) -> str:
    """A failed child's stderr as the one line the home keeps: its last non-empty line, a cap, and
    anything shaped like a bot token taken out — Doppler's own words pass, a token never does."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return _TOKENISH.sub("bot…", lines[-1])[:200] if lines else ""


def send(text: str, token: str, chat: str) -> str | None:
    """One `sendMessage`; None when Telegram took it, else the reason — never the URL."""
    body = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(
        API.format(token=token), data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_SECONDS) as r:  # noqa: S310 — a fixed https address
            return None if 200 <= r.status < 300 else f"telegram answered HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return f"telegram answered HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 — the class alone: its message may carry the URL
        return f"the send failed: {type(e).__name__}"


# -- push (design §4.10 *Told on the home-screen app too*, TD-1302, built by TD-1304) ---------------------

PUSH_SUB = "https://github.com/ShiftLead/shiftlead"  # VAPID `sub` when `reach.url` is not https
PUSH_TTL = 3600  # a row the phone could not be reached for within the hour is not delivered stale
NO_KEY = "no key"
KEY_REFUSED = "the push service refused the key's sender ({})"
_PUSH_MISSING = "pywebpush: not installed"


def _b64(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def private_key(text: str) -> Any:
    """`VAPID_PRIVATE_KEY` as a P-256 private key: `py_vapid`'s base64url raw scalar, or a PEM. ValueError
    with words that never hold the key."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    t = text.strip()
    if t.startswith("-----BEGIN"):
        try:
            key = load_pem_private_key(t.encode(), password=None)
        except (ValueError, TypeError):
            raise ValueError("VAPID_PRIVATE_KEY is a PEM that does not read as a private key") from None
        if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError("VAPID_PRIVATE_KEY is not a P-256 key")
        return key
    import base64
    import binascii

    try:
        raw = base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))
    except (binascii.Error, ValueError):
        raw = b""
    if len(raw) != 32:
        raise ValueError("VAPID_PRIVATE_KEY is neither a base64url P-256 scalar nor a PEM")
    try:
        return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())
    except ValueError:
        raise ValueError("VAPID_PRIVATE_KEY is not a valid P-256 scalar") from None


def public_key(key: Any) -> str:
    """The public half as the page subscribes with it: the uncompressed point, base64url without padding."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    return _b64(key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))


def reading() -> tuple[dict[str, str], Any]:
    """The key's reading from this child's environment, as the line the home keeps, and the key: `{key:
    "key", public_key}`, `{key: "no key"}` or `{key: "unreadable: <why>"}`."""
    text = os.environ.get("VAPID_PRIVATE_KEY", "")
    if not text.strip():
        return {"key": NO_KEY}, None
    try:
        key = private_key(text)
    except ImportError:
        return {"key": f"unreadable: {_PUSH_MISSING}"}, None
    except ValueError as e:
        return {"key": f"unreadable: {e}"}, None
    return {"key": "key", "public_key": public_key(key)}, key


def _global(host: str, port: int) -> str | None:
    """None when every address `host` resolves to is a global one, else why not: the home's check reads the
    name alone, and a name can resolve inward (§4.10 *On and off, per device*). The post resolves the name
    again, so a name that answers differently a moment later (DNS rebinding) is not caught here."""
    import ipaddress
    import socket

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        return f"the push service's name did not resolve: {type(e).__name__}"
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]).split("%", 1)[0])
        except ValueError:  # TD-1322: an address that does not read is not a global one, and ends no other post
            return "the push service's name resolves to an address that does not read"
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            return "the push service's name resolves to a private address"
    return None


def _post(device: dict[str, Any], data: str, key: Any, sub: str) -> int | str:
    """One push to one device: the push service's status, or the words of why there is none — never the
    endpoint, which is a capability."""
    from py_vapid import Vapid02
    from pywebpush import WebPushException, webpush
    from requests import Session

    u = urllib.parse.urlsplit(str(device.get("endpoint") or ""))
    if u.scheme != "https" or not u.hostname:
        return "the endpoint is not an https address"
    why = _global(u.hostname, u.port or 443)
    if why:
        return why
    session = Session()
    session.max_redirects = 0  # a redirect is never followed: the post goes where the home checked, or nowhere
    session.trust_env = False  # no proxy from the environment: the post goes to the address checked above
    try:
        r = webpush(
            {"endpoint": device["endpoint"], "keys": device.get("keys") or {}},
            data=data,
            vapid_private_key=Vapid02(private_key=key),
            vapid_claims={"sub": sub},
            ttl=PUSH_TTL,
            timeout=REQUEST_SECONDS,
            headers={"Urgency": "high"},
            requests_session=session,
        )
        return int(getattr(r, "status_code", 0)) or "no status"
    except WebPushException as e:
        code = getattr(e.response, "status_code", None)
        return int(code) if isinstance(code, int) else type(e).__name__
    except Exception as e:  # noqa: BLE001 — the class alone: its message may carry the endpoint
        return type(e).__name__
    finally:
        session.close()


def _say(obj: dict[str, Any]) -> None:
    print(json.dumps(obj), flush=True)


def push_main(stdin: str) -> int:
    """`--push`: stdin `{sub, payloads: [{body, path, tag}], devices: [{id, endpoint, keys}]}`. The first stdout
    line is the key's reading with the public key it derived; then one line a device and payload, `{device,
    i, status}`, as each answers — so a timeout keeps those already printed. Never the private key, never an
    endpoint. The posts end by `PUSH_SECONDS` (TD-1322)."""
    deadline = time.monotonic() + PUSH_SECONDS
    line, key = reading()
    _say(line)
    if key is None:
        return 0
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        print(_PUSH_MISSING, file=sys.stderr)
        return 1
    try:
        job = json.loads(stdin or "{}")
    except ValueError:
        print("the send's input is not JSON", file=sys.stderr)
        return 1
    payloads = [json.dumps(p) for p in job.get("payloads") or []]
    devices = [d for d in job.get("devices") or [] if isinstance(d, dict) and d.get("id")]
    sub = str(job.get("sub") or PUSH_SUB)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from concurrent.futures import TimeoutError as Late

    from sessionorc.push import NO_ANSWER

    jobs = [(d, i, data) for d in devices for i, data in enumerate(payloads)]
    pool = ThreadPoolExecutor(max_workers=min(PUSH_THREADS, max(1, len(jobs))))
    futures = {pool.submit(_post, d, data, key, sub): (d["id"], i) for d, i, data in jobs}
    told: set[Any] = set()
    try:
        for f in as_completed(futures, timeout=max(0.0, deadline - time.monotonic())):
            dev, i = futures[f]
            _say({"device": dev, "i": i, "status": f.result()})
            told.add(f)
    except (Late, Exception):  # past the deadline, or a post that raised: never wait on the rest
        for f, (dev, i) in futures.items():
            if f not in told:
                _say({"device": dev, "i": i, "status": NO_ANSWER})
        pool.shutdown(wait=False, cancel_futures=True)
        _abandon()  # the posts still running are never joined: the child ends now, its lines printed
        return 0
    pool.shutdown()
    return 0


def _abandon() -> None:
    """End the child at once, without joining the threads still posting (`--push`'s deadline, TD-1322)."""
    sys.stdout.flush()
    os._exit(0)


def key_main(secrets: str) -> int:
    """`--key <project/config>` (**Make key**): read the config's key first and refuse when one is there — its
    reading on stdout, so the home keeps it — else make a P-256 pair, write the private half with `doppler
    secrets set VAPID_PRIVATE_KEY` from stdin into that config alone, and print the public half."""
    line, _ = reading()
    if line["key"] != NO_KEY:
        _say(line)
        print("a key is there: replacing it would end every device's subscription", file=sys.stderr)
        return 2
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError:
        print(_PUSH_MISSING, file=sys.stderr)
        return 1
    import subprocess

    key = ec.generate_private_key(ec.SECP256R1())
    scalar = _b64(key.private_numbers().private_value.to_bytes(32, "big"))
    project, config = secrets.split("/", 1)
    try:
        done = subprocess.run(
            ["doppler", "secrets", "set", "VAPID_PRIVATE_KEY", "--project", project, "--config", config, "--silent"],
            input=scalar.encode(),
            capture_output=True,
            timeout=REQUEST_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"Doppler refused the write: {type(e).__name__}", file=sys.stderr)
        return 1
    if done.returncode != 0:
        why = reason(done.stderr.decode(errors="replace")).replace(scalar, "…") or f"exit {done.returncode}"
        print(f"Doppler refused the write: {why}", file=sys.stderr)
        return 1
    _say({"key": "key", "public_key": public_key(key)})
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["--public"]:
        _say(reading()[0])
        return 0
    if args[:1] == ["--push"]:
        return push_main(sys.stdin.read())
    if args[:1] == ["--key"] and len(args) == 2 and "/" in args[1]:
        return key_main(args[1])
    text = sys.stdin.read().strip()
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set in that Doppler config", file=sys.stderr)
        return 1
    if not text:
        print("nothing to send", file=sys.stderr)
        return 1
    why = send(text, token, chat)
    if why:
        print(why, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
