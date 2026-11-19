"""The Tools page's read (design §4.2b *The page*, *Controls and verbs*, TD-1973): the coding tools on this host.

Data, no tool name: every tool comes from the adapter registry (`adapters.names()`, an agent adapter's optional reads,
named in its `implements`) or the known-tools table (`adapters.known_tools()`). Each read runs on this host and sends
nothing anywhere. The host agent keeps one read, made when it starts and again on **Check again** (`ao tools check`);
a tick reads none of it.

Before the switch-over (`switched`, no `logins.yml`) a tool card carries no accounts and no logins: the reply holds
the tool cards, their versions, the found rows and *Not ready to run here*. From it, each card carries its logins and
the accounts they are signed into (TD-1974): each login's identity and credentials read, the pass settled
(`logins.settle`), and a login that joined an account written to `logins.yml` before the reply.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import adapters, hosts, logins

log = logging.getLogger("shiftlead.tools")

LOGINS_FILE = logins.LOGINS_FILE
# whether the host agent makes the Tools page's read when it starts (design §4.2b, TD-2002): a test knob, never a
# setting — the suite starts hundreds of host agents, and each one's read runs every tool's real `--version` on this
# machine; conftest turns it off, and a test of the start's read turns it on
READ_AT_START = True


_VERSION = re.compile(r"\d+(?:\.\d+)+")


def short_version(version: str | None) -> str | None:
    """A version as the page heads a card with it: the first dotted number of `--version`'s line (`2.1.327` of
    `2.1.327 (Claude Code)`), else the line itself."""
    if not version:
        return version
    m = _VERSION.search(version)
    return m.group(0) if m else version


def switched(home: Path | None = None) -> bool:
    """Whether this host is switched over to logins (design §4.2b *The page*): it has a `logins.yml`. The one test every
    Tools build calls; who writes the file at the window is the cut-over's design (TD-1976)."""
    return logins.switched(home)


def _ask(ad: object, method: str, fallback: Any, *args: Any) -> Any:
    """One optional read of an adapter, where its `implements` names it; `fallback` where it does not, or where it
    raised (one tool's failure never takes the read down, and its words never reach the reply: an exception may hold
    what the read must not send)."""
    if method not in adapters.implements(ad):
        return fallback
    try:
        return getattr(ad, method)(*args)
    except Exception:  # noqa: BLE001
        log.warning("tools read: %s.%s failed", getattr(ad, "name", "?"), method)
        return fallback


def _signed_in(ad: object, home: Path, salt: bytes) -> bool:
    """Whether `home` is signed in (design §4.2b *A login's state*): an identity the tool records, or credentials that
    stand (an API key with no identity)."""
    if _ask(ad, "identity", None, home, salt) is not None:
        return True
    return _ask(ad, "credentials_ok", None, home) is True


def _version(ad: object, env: Mapping[str, str]) -> str | None:
    fn: Callable[..., str | None] | None = getattr(ad, "tool_version", None)
    if fn is None:
        return None
    try:
        return fn(env)
    except Exception:  # noqa: BLE001
        return None


def _card(name: str, ad: object, env: Mapping[str, str], salt: bytes, folders: list[Path] = ()) -> dict[str, Any]:
    """One supported tool (design §4.2b *The read*): an agent adapter, found or not."""
    found = _ask(ad, "find", None)
    card: dict[str, Any] = {
        "adapter": name,
        "label": str(getattr(ad, "label", name)),
        "binary": found,
        "version": _version(ad, env) if found else None,
        "installed": bool(found),
        "supported": True,
        "install_command": _ask(ad, "install_command", None),
        "accounts": [],
        "logins": [],
        "found": [],
    }
    if not found:
        return card
    default = getattr(ad, "default_home", None)
    try:
        home = Path(default(env)) if default is not None else None
    except Exception:  # noqa: BLE001
        home = None
    own = getattr(ad, "own_home", None)
    if home is not None and not any(adapters.same_home(home, f) for f in folders) and _signed_in(ad, home, salt):
        # the tool's default home, signed in and not yet a login; an `own_home` adapter's may never be one (§4.2a)
        card["found"].append(
            {"folder": str(home), "own_home": own is not None and adapters.same_home(home, Path(own).expanduser())}
        )
    return card


def read(
    salt: bytes, env: Mapping[str, str] | None = None, home: Path | None = None, memory: logins.Memory | None = None
) -> dict[str, Any]:
    """`tools`' reply (design §4.2b *Controls and verbs*): `{host, read_at, switched, tools, not_ready}`. `tools` are
    the supported tools found on this host; `not_ready` the supported tools not found (each with its install command)
    and the known tools with no adapter, found or not — each in a card's shape, `supported` saying which. On a
    switched host each found tool's card carries its `accounts` and `logins`, `memory` the run's matches."""
    env = dict(os.environ if env is None else env)
    data = logins.load(home)
    tools: list[dict[str, Any]] = []
    not_ready: list[dict[str, Any]] = []
    for name in adapters.names():
        if not adapters.has_agent(name):
            continue
        ad = adapters.get(name)
        mine = [
            Path(e.get("folder", "")).expanduser()
            for lk, e in (data or {}).get("logins", {}).items()
            if logins.split(lk)[0] == name
        ]
        card = _card(name, ad, env, salt, mine)
        (tools if card["installed"] else not_ready).append(card)
    if data is not None:
        _login_tree(tools, data, salt, memory if memory is not None else logins.Memory(), home)
    try:
        known = adapters.known_tools()
    except Exception:  # noqa: BLE001 — a bad table row costs the known tools, never the supported tools' cards
        log.warning("tools read: the known-tools table failed")
        known = []
    for row in known:
        if not isinstance(row, dict) or "name" not in row:
            continue
        path = row.get("path")
        not_ready.append(
            {
                "adapter": row["name"],
                "label": row.get("label") or row["name"],
                "binary": path,
                "version": adapters.read_version(path, env) if path else None,
                "installed": bool(path),
                "supported": False,
                "install_command": None,
                "accounts": [],
                "logins": [],
                "found": [],
            }
        )
    return {
        "host": hosts.local_host().name,
        "read_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "switched": data is not None,
        "tools": tools,
        "not_ready": not_ready,
    }


def _login_tree(
    cards: list[dict[str, Any]], data: dict[str, Any], salt: bytes, memory: logins.Memory, home: Path | None
) -> None:
    """Each found tool's logins and accounts (design §4.2b *The page*, *A login's state*, *Matching across a
    restart*): every login's identity and credentials read, the whole pass settled once its reads are in, a login
    that joined an account written, and the cards filled. A login whose tool is not found draws on no card."""
    by_tool = {c["adapter"]: c for c in cards}
    reads: dict[str, tuple[dict[str, Any] | None, bool | None]] = {}
    for n, e in data["logins"].items():
        card = by_tool.get(logins.split(n)[0])
        if card is None:
            continue
        ad = adapters.get(card["adapter"])
        folder = Path(str(e.get("folder", ""))).expanduser()
        ident = _ask(ad, "identity", None, folder, salt)
        reads[n] = (
            ident if isinstance(ident, dict) and ident.get("match") else None,
            _ask(ad, "credentials_ok", None, folder),
        )
    # a match is compared within its tool alone: two tools' keys are never one account
    matches = {n: f"{logins.split(n)[0]}\0{i['match']}" if i else None for n, (i, _) in reads.items()}
    stored = {n: data["logins"][n].get("account") for n in reads}
    settled = logins.settle(stored, matches, memory)
    if settled.moves:
        _write_moves(settled.moves, stored, home)
    accounts: dict[str, dict[str, Any]] = {}
    stored_billing: dict[str, str] = {}  # an account's billing is its logins' `billing`, the person's, where one says
    for n, (ident, creds) in sorted(reads.items()):
        e = data["logins"][n]
        card = by_tool[logins.split(n)[0]]
        ad = adapters.get(card["adapter"])
        st = logins.state(ident, creds)
        key = settled.account.get(n)
        if n in settled.name_account:
            st, key = "name_account", None
        elif key is None and st == "signed_in":
            key = n  # its own key, `<adapter>:<login name>`: an API key with no identity: an account of its own
        warnings = []
        if ident and ident.get("billing") and e.get("billing") and ident["billing"] != e["billing"]:
            warnings.append("billing_mismatch")
        card["logins"].append(
            {
                "name": logins.split(n)[1],
                "label": e.get("label"),
                "folder": str(e.get("folder", "")),
                "account": key,
                "state": st,
                "mismatch": n in settled.mismatch,
                "warnings": warnings,
                "note": e.get("note"),
                "pin": e.get("pin"),
                "version": logins.version(e),
            }
        )
        if key is None or st == "not_signed_in":
            continue
        acct = accounts.get(key)
        if acct is not None and e.get("billing") and not stored_billing.get(key):
            acct["billing"] = stored_billing[key] = e["billing"]  # the person's word over the tool's record
        if acct is None:
            plan = ident.get("plan") if ident else None
            offer = _ask(ad, "models", None, Path(str(e.get("folder", ""))).expanduser(), plan)
            acct = accounts[key] = {
                "key": key,
                "label": (data["accounts"].get(key) or {}).get("label"),
                "plan": plan,
                "billing": e.get("billing") or (ident.get("billing") if ident else None),
                "models": offer if isinstance(offer, dict) else {"families": [], "default": None, "unconfirmed": True},
                "gauges": [],
                "version": logins.version(data["accounts"].get(key)),
            }
            card["accounts"].append(acct)
            if e.get("billing"):
                stored_billing[key] = e["billing"]


def _write_moves(moves: Mapping[str, str], read: Mapping[str, str | None], home: Path | None) -> None:
    """Write the logins that joined an account (§4.2b *A login changes account*), on the file as it stands now: a
    login the person changed or forgot since this pass read the file is left as they left it. A failed write is
    logged and the read stands; the next pass settles again."""

    def change(data: dict[str, Any]) -> str | None:
        done = []
        for n, key in sorted(moves.items()):
            e = data["logins"].get(n)
            if e is not None and e.get("account") == read.get(n):
                e["account"] = key
                done.append(f"{n} joined {key}")
        return ", ".join(done) or None

    try:
        logins.update(change, home)
    except (OSError, logins.LoginError) as e:
        log.warning("tools read: writing the logins that joined an account failed: %s", type(e).__name__)
