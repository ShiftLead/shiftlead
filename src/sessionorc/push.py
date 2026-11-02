"""The home-screen app's devices (design §4.10 *Told on the home-screen app too*, TD-1302, built by TD-1304):
`~/.shiftlead/push.json`, the home's state and never `settings.yml` — `key` (the key's reading: *key*, *no key*
or *unreadable: <why>*, absent while there is none), `public_key`, `last_line`, and `devices`, each `{id,
endpoint, keys, label, since, last_ok, last_error}`. Mode 600, the home its one writer, each write a new file
renamed into place, since the watch reads it. The checks a subscription meets before it is listed, and the
`host` read's view (the same less each device's `endpoint` and `keys`)."""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import ipaddress
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sessionorc import paths
from sessionorc.store import _atomic_write

KEY = "key"  # the reading under which push sends
NO_KEY = "no key"
DEVICE_FIELDS = ("id", "endpoint", "keys", "label", "since", "last_ok", "last_error")


def path() -> Path:
    return paths.home() / "push.json"


def load(where: Path | None = None) -> dict[str, Any]:
    """The file as kept, its devices those with an id and an endpoint; an absent or unreadable file is no
    reading and no device."""
    doc: dict[str, Any] = {}
    with contextlib.suppress(OSError, ValueError):
        got = json.loads((where or path()).read_text(encoding="utf-8"))
        if isinstance(got, dict):
            doc = got
    devices = [d for d in doc.get("devices") or () if isinstance(d, dict) and d.get("id") and d.get("endpoint")]
    out: dict[str, Any] = {"devices": devices}
    for k in ("key", "public_key", "last_line"):
        if isinstance(doc.get(k), str) and doc[k]:
            out[k] = doc[k]
    return out


def save(doc: dict[str, Any], where: Path | None = None) -> None:
    """One write, renamed into place, mode 600 (it holds each device's endpoint and keys)."""
    p = where or path()
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(p, json.dumps(doc, indent=1, sort_keys=True) + "\n", mode=0o600)


def device_id(endpoint: str) -> str:
    """The first 16 hex digits of the SHA-256 of the endpoint, as the page and the worker work it out."""
    return hashlib.sha256(endpoint.encode()).hexdigest()[:16]


_B64URL = re.compile(r"[A-Za-z0-9_-]+={0,2}")


def b64url(s: Any) -> bytes:
    """A base64url value, padded or not, as bytes; ValueError when it is not one."""
    if not isinstance(s, str) or not s.strip():
        raise ValueError("empty")
    t = s.strip()
    if not _B64URL.fullmatch(t):
        raise ValueError("not base64url")
    try:
        return base64.b64decode(t + "=" * (-len(t) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(str(e)) from None


def same_key(a: Any, b: Any) -> bool:
    """Two public keys compared as decoded bytes, so padding and its absence agree."""
    try:
        return b64url(a) == b64url(b)
    except ValueError:
        return False


_NUMERIC = re.compile(r"0x[0-9a-f]*|[0-9]+")  # a label a resolver reads as a number: 127.1, 2130706433, 0x7f
_INTERNAL = (".local", ".localhost", ".internal", ".lan", ".home", ".localdomain", ".home.arpa")


def _public_host(host: str) -> bool:
    """A host the home may post to: a global IP literal, or a dotted name whose last label is not a number and
    that is not internal on its face. Non-canonical IPv4 (`127.1`, `0x7f.0.0.1`, `2130706433`), a trailing
    dot, CGNAT and mapped IPv6 are refused here; a name that resolves to a private address is the sender's to
    refuse at the post (slice 2)."""
    h = host.strip("[]").lower().rstrip(".")
    if not h or h == "localhost" or h.endswith(_INTERNAL):
        return False
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return "." in h and not _NUMERIC.fullmatch(h.rsplit(".", 1)[1])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check(endpoint: Any, keys: Any) -> tuple[str, dict[str, str]]:
    """A subscription as the home lists it, or ValueError naming the field: the endpoint `https` to a public
    host (it is where the home's own child will post), `p256dh` 65 bytes and `auth` 16."""
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("endpoint: the push service's https:// address is required")
    ep = endpoint.strip()
    try:
        u = urlsplit(ep)
        host = u.hostname or ""
        _ = u.port  # a port that is not a number is refused here, not at the send
    except ValueError:
        raise ValueError("endpoint: not an address") from None
    if u.scheme != "https":
        raise ValueError("endpoint: must be https://")
    if not _public_host(host):
        raise ValueError(f"endpoint: {host or 'no host'} is a loopback, private, link-local or internal address")
    if not isinstance(keys, dict):
        raise ValueError("keys: {p256dh, auth} is required")
    out: dict[str, str] = {}
    for name, size in (("p256dh", 65), ("auth", 16)):
        try:
            raw = b64url(keys.get(name))
        except ValueError:
            raise ValueError(f"keys.{name}: not a base64url value") from None
        if len(raw) != size:
            raise ValueError(f"keys.{name}: {len(raw)} bytes, not {size}")
        out[name] = str(keys[name]).strip()
    return ep, out


def subscribe(
    doc: dict[str, Any], endpoint: Any, keys: Any, label: Any, key: Any, at: str, replaces: Any = None
) -> str:
    """List a subscription in `doc` and answer its id (§4.10 *On and off, per device*). Refused (ValueError,
    naming the field or the reading) while the key reads anything but *key*, or when `key` — the public key
    the subscription was made with — is not the home's, so a subscription bound to a key the home no longer
    holds is never listed; then the endpoint and keys are checked. `replaces` swaps that device's endpoint
    and keys, keeping its label and `since`, and adds the device when the id is no longer listed. A refused
    `replaces` leaves the old device listed."""
    reading = doc.get("key")
    if reading != KEY:
        raise ValueError(f"key: push is not ready — {reading or 'reading the key'}")
    if not same_key(key, doc.get("public_key")):
        raise ValueError("key: the subscription was made with a key this home does not hold")
    ep, ks = check(endpoint, keys)
    new = device_id(ep)
    devices: list[dict[str, Any]] = list(doc.get("devices") or [])
    old = next((d for d in devices if replaces and d.get("id") == str(replaces)), None)
    same = next((d for d in devices if d.get("id") == new), None)
    if old is not None:
        devices = [d for d in devices if d is not old and d is not same]
        # a new subscription, so its delivery is its own: the old one's last result is not carried onto it
        devices.append({**old, "id": new, "endpoint": ep, "keys": ks, "last_ok": None, "last_error": None})
    elif same is not None:
        same.update(endpoint=ep, keys=ks)
    else:
        name = label.strip() if isinstance(label, str) and label.strip() else "a device"
        devices.append({"id": new, "endpoint": ep, "keys": ks, "label": name[:80], "since": at,
                        "last_ok": None, "last_error": None})  # fmt: skip
    doc["devices"] = devices
    return new


def unsubscribe(doc: dict[str, Any], device: Any) -> bool:
    """Drop one device by its id; whether it was listed."""
    devices = list(doc.get("devices") or [])
    kept = [d for d in devices if d.get("id") != str(device)]
    doc["devices"] = kept
    return len(kept) != len(devices)


def view(doc: dict[str, Any]) -> dict[str, Any]:
    """The `host` read's `push` (§4.10): the file less each device's `endpoint` and `keys`."""
    out: dict[str, Any] = {k: doc[k] for k in ("key", "public_key", "last_line") if doc.get(k)}
    out["devices"] = [
        {k: d.get(k) for k in DEVICE_FIELDS if k not in ("endpoint", "keys")} for d in doc.get("devices") or []
    ]
    return out


# -- the home's reading of a child's answer (§4.10 *The key*, *The key's reading*; TD-1304 slice 2) ---------

PAUSED = "push is paused: {}"
KEY_CHANGED = "the key changed: turn this on again on each device"
ENDED = "a device was removed: its subscription ended {}"
NO_ANSWER = "no answer"


def hhmm(at: str) -> str:
    """An ISO time as the person's clock reads it: *14:02*."""
    from datetime import datetime

    try:
        return datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError:
        return at


def reading_of(line: Any) -> str | None:
    """The reading a child's first line carries — *key*, *no key* or *unreadable: <why>* — or None."""
    got = line.get("key") if isinstance(line, dict) else None
    if got == KEY:
        return KEY if isinstance(line.get("public_key"), str) and line["public_key"] else None
    return got if isinstance(got, str) and (got == NO_KEY or got.startswith("unreadable: ")) else None


def apply_reading(doc: dict[str, Any], line: Any) -> bool:
    """Keep the reading a child answered (`--public`, `--key`'s refusal, or a send's first line): `key`, and on
    *key* the `public_key` it derived. True when that key differs from the kept one — every device dropped,
    `last_line` *the key changed: …*, in this one write — so the send's statuses are discarded. A reading back
    to *key* clears *push is paused*; the public key is kept while paused, so a key put back resumes."""
    got = reading_of(line)
    if got is None:
        return False
    doc["key"] = got
    if got != KEY:
        return False
    if (doc.get("last_line") or "").startswith(PAUSED.format("")):
        doc.pop("last_line", None)
    new, kept = line["public_key"], doc.get("public_key")
    doc["public_key"] = new
    if kept and not same_key(new, kept):
        if doc.get("devices"):
            doc["last_line"] = KEY_CHANGED
        doc["devices"] = []
        return True
    return False


def paused(doc: dict[str, Any]) -> bool:
    """Set `last_line` *push is paused: <reading>* while the key reads *no key* or *unreadable* with devices
    listed; whether it changed."""
    reading = doc.get("key")
    if not doc.get("devices") or reading in (None, KEY):
        return False
    line = PAUSED.format(reading)
    if doc.get("last_line") == line:
        return False
    doc["last_line"] = line
    return True


def words(status: Any) -> str:
    """A failed status as the device's `last_error` reads it."""
    if status in (401, 403):
        return f"the push service refused the key's sender ({status})"
    if isinstance(status, int):
        return f"the push service answered {status}"
    return str(status or NO_ANSWER)


def ok(status: Any) -> bool:
    return isinstance(status, int) and 200 <= status < 300


def apply_statuses(doc: dict[str, Any], statuses: dict[tuple[str, int], Any], at: str) -> set[int]:
    """A send's statuses laid on the devices it was sent to (`statuses` keyed `(device id, payload index)`;
    *no answer* for each the child never printed): a 2xx sets `last_ok` and clears `last_error`, a 404 or 410
    drops the device with `last_line` *a device was removed: …*, anything else is its `last_error` `{at,
    reason}`. Answers the indices some device's push service accepted."""
    taken: set[int] = set()
    by_device: dict[str, list[tuple[int, Any]]] = {}
    for (dev, i), status in statuses.items():
        by_device.setdefault(dev, []).append((i, status))
    kept = []
    for d in doc.get("devices") or []:
        got = sorted(by_device.get(str(d.get("id")), []), key=lambda x: x[0])
        if any(s in (404, 410) for _, s in got):
            doc["last_line"] = ENDED.format(hhmm(at))
            continue
        for i, status in got:
            if ok(status):
                taken.add(i)
                d["last_ok"], d["last_error"] = at, None
        failed = [s for _, s in got if not ok(s)]
        if failed:
            d["last_error"] = {"at": at, "reason": words(failed[-1])}
        kept.append(d)
    doc["devices"] = kept
    return taken
