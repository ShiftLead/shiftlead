"""A host's logins (design §4.2b *Where it lives*, *Matching across a restart*, TD-1974): `~/.shiftlead/logins.yml`,
its reader and writer, the name rules, an entry's version, retired keys, and the settling of one pass of identity
reads into accounts.

Data, no tool name: a login is `{folder, label, note, account, billing, prices, extra_args, unattended_args,
permission_wait, pin}` under `<tool>:<name>` (a name is unique per tool on a host, §4.2b *Terms used below*);
`accounts:` holds each account's label by key; `forgotten:` each forgotten
login's folder and account by `<tool>:<name>`. The file holds no secret and no identity: which login is which account
is each login's `account`, and an identity's `match` is compared only in the host agent's memory (`Memory`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sessionorc import defs, naming, paths

LOGINS_FILE = "logins.yml"

# a login's name and an account's name: at most 24 of letters, digits, `-` and `_`, the first a letter or digit, so a
# key (`<adapter>:<name>`), a commit line and a path never break (§4.2b *Terms used below*)
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,23}")
# what a login's Settings may set (§4.2b *A login's Settings*), `ao login set`'s keys
SETTINGS = ("billing", "prices", "extra_args", "unattended_args", "permission_wait", "pin")
ENTRY_KEYS = ("folder", "label", "note", "account", *SETTINGS)


class LoginError(ValueError):
    """A login write refused, its words the person's to read."""


def path(home: Path | None = None) -> Path:
    return (home or paths.home()) / LOGINS_FILE


def switched(home: Path | None = None) -> bool:
    """Whether this host is switched over to logins (design §4.2b *The page*): it has a `logins.yml`."""
    return path(home).is_file()


def valid_name(name: object) -> bool:
    return isinstance(name, str) and _NAME.fullmatch(name) is not None


def name_of(text: str) -> str:
    """A display name folded to a name's characters (`Paul K` → `paul-k`), for a suggestion (§4.2b *How a login is
    found and made*); empty where nothing of it is left."""
    out = re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-_")
    return out[:24].rstrip("-_")


def key(tool: str, name: str) -> str:
    """A login's key in `logins:` and `forgotten:`, `<tool>:<name>`; it is also the key of the account of its own a
    login with no identity is (`<adapter>:<login name>`), never written to its `account` (§4.2b *Matching across a
    restart*)."""
    return f"{tool}:{name}"


derived_key = key


def split(lk: str) -> tuple[str, str]:
    """A login's key as `(tool, name)`."""
    tool, _, name = lk.rpartition(":")
    return tool, name


def empty() -> dict[str, Any]:
    return {"logins": {}, "accounts": {}, "forgotten": {}}


def load(home: Path | None = None) -> dict[str, Any] | None:
    """The host's logins, or None where it is not switched. A file that does not parse raises `LoginError`: a write
    over it would lose what the person wrote."""
    p = path(home)
    if not p.is_file():
        return None
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise LoginError(f"{p} could not be read: {type(e).__name__}") from None
    if not isinstance(raw, dict):
        raise LoginError(f"{p} is not a mapping")
    data = empty()
    for part in data:
        got = raw.get(part) or {}
        if not isinstance(got, dict):
            raise LoginError(f"{p}: `{part}:` is not a mapping")
        data[part] = {str(k): dict(v) if isinstance(v, dict) else {} for k, v in got.items()}
    return data


def save(data: Mapping[str, Any], change: str, home: Path | None = None) -> bool:
    """Write the host's logins as one replace, then commit it as `logins: <change>` (§4.2b *Where it lives*), so it is
    never committed later as *edited by hand*. True when a commit was made: none on a node, whose file is untracked, nor
    before the switch-over puts it among `defs.TRACKED` in `profiles.yml`'s place (§4.9, the cut-over's, TD-1976)."""
    p = path(home)
    out = {part: {k: _clean(v) for k, v in sorted(data.get(part, {}).items())} for part in empty()}
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".logins-", suffix=".yml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(out, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    if LOGINS_FILE not in defs.TRACKED:  # it takes `profiles.yml`'s place there at the switch-over (TD-1976)
        return False
    return defs.commit(f"logins: {change}"[:200], home=home, files=(LOGINS_FILE,))


def _clean(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if v is not None}


def version(entry: Mapping[str, Any] | None) -> str:
    """An entry's version (§4.2b *The read*): a hash of the entry as it stands, nothing stored. A write sends back the
    one it read, and is refused over a newer one."""
    blob = json.dumps(_clean(entry or {}), sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def check_version(entry: Mapping[str, Any] | None, sent: str | None, name: str) -> None:
    if sent is not None and sent != version(entry):
        raise LoginError(f"{name} changed since this page read it — reload")


def resolve(data: Mapping[str, Any], ref: str) -> tuple[str, dict[str, Any]]:
    """A login by `<tool>:<name>`, or by its bare name where one login of this host has it — two refused, naming both
    forms (§4.2b *Controls and verbs*); a label is never taken as a name. Returns the login's key and entry."""
    logins = data["logins"]
    if ":" in ref:
        if ref in logins:
            return ref, logins[ref]
    else:
        hits = sorted(lk for lk in logins if split(lk)[1] == ref)
        if len(hits) == 1:
            return hits[0], logins[hits[0]]
        if hits:
            raise LoginError(f"{ref} names more than one login here: say which, {' or '.join(hits)}")
    raise LoginError(f"no login {ref} on this host")


def account_of(lk: str, entry: Mapping[str, Any]) -> str:
    """The key a login's launches read: its stored `account`, else its derived key (its own key)."""
    return str(entry.get("account") or lk)


def live_keys(data: Mapping[str, Any]) -> set[str]:
    return {account_of(n, e) for n, e in data["logins"].items()}


def retired(data: Mapping[str, Any], reserve_keys: Iterable[str] = ()) -> set[str]:
    """Retired keys (§4.2b *Matching across a restart*): named by no live login's `account` or derived key, and
    named by a forgotten login or holding a reserve in `settings.yml`. A bare name composing to one is refused
    everywhere; the full key given to `ao login account` rejoins it deliberately."""
    named = {str(f.get("account")) for f in data["forgotten"].values() if f.get("account")}
    return (named | set(reserve_keys)) - live_keys(data)


def name_taken(data: Mapping[str, Any], tool: str, name: str, tools: Iterable[str] = ()) -> str | None:
    """Why `name` cannot be a new login of `tool` here, or None (§4.2b *Terms used below*, *The tools shell*): a name
    is unique per tool, and the login's tools shell id may not be one another login's shell or an install shell of
    `tools` (the registered adapters) already has — one fold, or a hyphenated adapter name meeting another's."""
    if not valid_name(name):
        return f"{name!r} is not a login name: at most 24 letters, digits, '-' and '_', the first a letter or digit"
    lk = key(tool, name)
    if lk in data["logins"]:
        return f"{lk} is a login on this host already"
    sid = naming.tools_id(tool, name)
    for other in data["logins"]:
        if naming.tools_id(*split(other)) == sid:
            return f"{lk}'s tools shell would be {other}'s"
    for t in tools:
        if naming.tools_install_id(t) == sid:
            return f"{lk}'s tools shell would be {t}'s install shell"
    return None


def suggest(base: str, taken: Iterable[str]) -> str:
    """`base`, or with a suffix (`-2`, `-3`, …) where it is taken (§4.2b *How a login is found and made*)."""
    have = set(taken)
    if base not in have:
        return base
    n = 2
    while f"{base[: 24 - len(str(n)) - 1]}-{n}" in have:
        n += 1
    return f"{base[: 24 - len(str(n)) - 1]}-{n}"


# ---- the settling of one pass of reads (§4.2b *Matching across a restart*) ----


@dataclass
class Memory:
    """What one run of the host agent knows of matches: never written anywhere. `last` is each login's last match this
    run (none is not a match); `owner` the account a match settled to first this run."""

    last: dict[str, str] = field(default_factory=dict)
    owner: dict[str, str] = field(default_factory=dict)


@dataclass
class Settled:
    account: dict[str, str | None]  # each login's account this pass: a key, or None (no account, no match)
    moves: dict[str, str]  # logins whose stored `account` this pass writes: login key → account key
    name_account: set[str]  # signed in as an account none has: launches nothing until the person names it
    mismatch: set[str]  # *these logins read different accounts*: launches nothing


def settle(stored: Mapping[str, str | None], matches: Mapping[str, str | None], memory: Memory) -> Settled:
    """Settle one pass of reads, once all of them are in (§4.2b *Matching across a restart*). `stored` is each login's
    stored `account`; `matches` its identity's match this pass, or None. `memory` is updated in place.

    1. A login whose match differs from its own last match this run moves to the account whose logins read that
       match, or draws *name its account* where none does.
    2. A login's first match this run joins its stored account, unless that match is another account's logins'
       (marking that login alone), or its stored account's other logins read another (marking all of them).
    3. A login with no stored account and a match no account has draws *name its account*; one some account has
       joins it."""
    changed = {n for n, m in matches.items() if m and memory.last.get(n) not in (None, m)}
    steady = {n: m for n, m in matches.items() if m and n not in changed and stored.get(n)}
    # who owns a match: what earlier passes settled, then a match only one stored account's logins read now
    readers: dict[str, set[str]] = {}
    for n, m in steady.items():
        readers.setdefault(m, set()).add(str(stored[n]))
    for m, accts in readers.items():
        if m not in memory.owner and len(accts) == 1:
            memory.owner[m] = next(iter(accts))
    mismatch: set[str] = set()
    for n, m in steady.items():  # rule 2's first case: the incoming login alone; a match no one owns, every reader
        if memory.owner.get(m) != stored[n]:
            mismatch.add(n)
    by_account: dict[str, set[str]] = {}
    for n, m in steady.items():
        if n not in mismatch:
            by_account.setdefault(str(stored[n]), set()).add(m)
    for acct, ms in by_account.items():  # rule 2's second case: the stored account's logins disagree
        if len(ms) > 1:
            mismatch |= {n for n in steady if stored[n] == acct}
    account: dict[str, str | None] = {n: stored.get(n) for n in matches}
    moves: dict[str, str] = {}
    name_account: set[str] = set()
    for n, m in matches.items():
        if not m or (n in steady):
            continue
        target = memory.owner.get(m)
        if target is not None:
            if target != stored.get(n):
                moves[n] = target
            account[n] = target
        else:
            name_account.add(n)
    for n, m in matches.items():
        if m:
            memory.last[n] = m
    return Settled(account=account, moves=moves, name_account=name_account, mismatch=mismatch)


def state(identity: Mapping[str, Any] | None, creds: bool | None) -> str:
    """A login's state from its identity and `credentials_ok(home)` (§4.2b *A login's state*), before the settle's
    marks and the account's cap."""
    if identity is not None:
        return "sign_in_again" if creds is False else "signed_in"
    return "signed_in" if creds is True else "not_signed_in"
