"""The Tools page's read (design §4.2b *The page*, *Controls and verbs*, TD-1973): the coding tools on this host.

Data, no tool name: every tool comes from the adapter registry (`adapters.names()`, an agent adapter's optional reads,
named in its `implements`) or the known-tools table (`adapters.known_tools()`). Each read runs on this host and sends
nothing anywhere. The host agent keeps one read, made when it starts and again on **Check again** (`ao tools check`);
a tick reads none of it.

Before the switch-over (`switched`, no `logins.yml`) a tool card carries no accounts and no logins: the reply holds
the tool cards, their versions, the found rows and *Not ready to run here*.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import adapters, hosts, paths

log = logging.getLogger("shiftlead.tools")

LOGINS_FILE = "logins.yml"


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
    return ((home or paths.home()) / LOGINS_FILE).is_file()


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


def _card(name: str, ad: object, env: Mapping[str, str], salt: bytes) -> dict[str, Any]:
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
    if home is not None and _signed_in(ad, home, salt):
        # the tool's default home, signed in and not yet a login; an `own_home` adapter's may never be one (§4.2a)
        card["found"].append(
            {"folder": str(home), "own_home": own is not None and adapters.same_home(home, Path(own).expanduser())}
        )
    return card


def read(salt: bytes, env: Mapping[str, str] | None = None, home: Path | None = None) -> dict[str, Any]:
    """`tools`' reply (design §4.2b *Controls and verbs*): `{host, read_at, switched, tools, not_ready}`. `tools` are
    the supported tools found on this host; `not_ready` the supported tools not found (each with its install command)
    and the known tools with no adapter, found or not — each in a card's shape, `supported` saying which."""
    env = dict(os.environ if env is None else env)
    tools: list[dict[str, Any]] = []
    not_ready: list[dict[str, Any]] = []
    for name in adapters.names():
        if not adapters.has_agent(name):
            continue
        card = _card(name, adapters.get(name), env, salt)
        (tools if card["installed"] else not_ready).append(card)
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
        "switched": switched(home),
        "tools": tools,
        "not_ready": not_ready,
    }
