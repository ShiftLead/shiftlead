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
import math
import os
import re
import tempfile
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sessionorc import defs, naming, paths, yamltext

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
        raw = yamltext.load(p.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise LoginError(f"{p} could not be read: {type(e).__name__}") from None
    if not isinstance(raw, dict):
        raise LoginError(f"{p} is not a mapping")
    data = empty()
    for part in data:
        got = raw.get(part) or {}
        if not isinstance(got, dict):
            raise LoginError(f"{p}: `{part}:` is not a mapping")
        for k, v in got.items():
            if not isinstance(v, dict):  # a write over it would erase what the person wrote there
                raise LoginError(f"{p}: `{part}:` {k} is not a mapping")
            data[part][str(k)] = dict(v)
    return data


def save(data: Mapping[str, Any], change: str, home: Path | None = None) -> bool:
    """Write the host's logins as one replace, then commit it as `logins: <change>` (§4.2b *Where it lives*), so it is
    never committed later as *edited by hand*. True when a commit was made, at the home, where it is among
    `defs.TRACKED` (beside `profiles.yml` until the switch-over takes that out, TD-1976); none on a node, whose home is
    no tree and whose file is untracked."""
    p = path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = {part: {k: _clean(v) for k, v in sorted(data.get(part, {}).items())} for part in empty()}
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".logins-", suffix=".yml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(out, f, sort_keys=False, allow_unicode=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return defs.commit(f"logins: {change}"[:200], home=home, files=(LOGINS_FILE,))


_LOCK = threading.Lock()


def update(change: Callable[[dict[str, Any]], str | None], home: Path | None = None) -> str | None:
    """One read-modify-write of the host's logins under the host agent's one lock, so two writers never lose each
    other's change: `change` edits the file as it stands now and returns the change's words, or None to write
    nothing. Returns those words. Not switched: `LoginError`."""
    with _LOCK:
        data = load(home)
        if data is None:
            raise LoginError("this host has no logins until the switch-over (design §4.2b)")
        words = change(data)
        if words:
            save(data, words, home)
        return words


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
    run (none is not a match); `unnamed` each login drawn *name its account*, with the match and stored account it was
    drawn on — it stays so until either changes (the person names it, or it is signed in again)."""

    last: dict[str, str] = field(default_factory=dict)
    unnamed: dict[str, tuple[str, str | None]] = field(default_factory=dict)


@dataclass
class Settled:
    account: dict[str, str | None]  # each login's account this pass: a key, or None (no account, no match)
    moves: dict[str, str]  # logins whose stored `account` this pass writes: login key → account key
    name_account: set[str]  # signed in as an account none has: launches nothing until the person names it
    mismatch: set[str]  # *these logins read different accounts*: launches nothing


def settle(stored: Mapping[str, str | None], matches: Mapping[str, str | None], memory: Memory) -> Settled:
    """Settle one pass of reads, once all of them are in (§4.2b *Matching across a restart*). `stored` is each login's
    stored `account`; `matches` its identity's match this pass, or None. `memory` is updated in place. Which account
    has a match is read from this pass: the stored accounts of the logins that read it now.

    1. A login whose match differs from its own last match this run moves to the account whose logins read that
       match, or draws *name its account* where none does.
    2. A login's first match this run joins its stored account, unless that match is read by a login of another
       account that read it before (marking the incoming login alone; at the run's first pass, where none read it
       before, every reader), or its stored account's other logins read another (marking all of them).
    3. A login with no stored account and a match no account has draws *name its account*; one exactly one account
       has joins it. Two accounts reading the match mark the login."""
    for n, (m, acct) in list(memory.unnamed.items()):
        if matches.get(n) != m or stored.get(n) != acct:
            del memory.unnamed[n]  # named by the person, or signed in again: settled afresh below
    unnamed = set(memory.unnamed)
    changed = {n for n, m in matches.items() if m and n not in unnamed and memory.last.get(n) not in (None, m)}
    placed = {n: m for n, m in matches.items() if m and n not in changed and n not in unnamed and stored.get(n)}
    seen = {n for n, m in placed.items() if memory.last.get(n) == m}  # read this match before: established
    readers: dict[str, set[str]] = {}  # a match → the accounts whose logins read it now
    for n, m in placed.items():
        readers.setdefault(m, set()).add(str(stored[n]))
    mismatch: set[str] = set()
    for m, accts in readers.items():
        if len(accts) < 2:
            continue
        on = [n for n, got in placed.items() if got == m]
        established = {str(stored[n]) for n in on if n in seen}
        if len(established) == 1:  # rule 2's first case: the incoming logins alone
            mismatch |= {n for n in on if stored[n] not in established}
        else:  # no account had it before (the run's first pass), or two did: every reader
            mismatch |= set(on)
    by_account: dict[str, set[str]] = {}
    for n, m in placed.items():
        if n not in mismatch:
            by_account.setdefault(str(stored[n]), set()).add(m)
    for acct, ms in by_account.items():  # rule 2's second case: the stored account's logins disagree
        if len(ms) > 1:
            mismatch |= {n for n in placed if stored[n] == acct}
    account: dict[str, str | None] = {n: stored.get(n) for n in matches}
    moves: dict[str, str] = {}
    name_account: set[str] = set(unnamed)
    for n in unnamed:
        account[n] = None
    for n, m in matches.items():
        if not m or n in placed or n in unnamed:
            continue
        has = readers.get(m, set())
        if len(has) == 1:
            target = next(iter(has))
            if target != stored.get(n):
                moves[n] = target
            account[n] = target
        elif has:
            mismatch.add(n)
        else:
            name_account.add(n)
            memory.unnamed[n] = (m, stored.get(n))
            account[n] = None
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


# ---- the verbs' edits (§4.2b *Controls and verbs*): each edits the file as it stands, inside `update`, and returns
# its change's words, or raises `LoginError` in the person's words ----

LABEL_MAX = 40
NOTE_MAX = 300
BILLINGS = ("subscription", "metered")
PRICE_KINDS = ("input", "output", "cache_read", "cache_write")


def _one_line(text: object, what: str, most: int) -> str | None:
    """A label's or a note's text: one line of at most `most`; empty or None clears it."""
    if text is None:
        return None
    if not isinstance(text, str):
        raise LoginError(f"a {what} is text, not {type(text).__name__}")
    text = text.strip()
    if "\n" in text or "\r" in text:
        raise LoginError(f"a {what} is one line")
    if len(text) > most:
        raise LoginError(f"a {what} is at most {most} characters")
    return text or None


def _put(entry: dict[str, Any], k: str, v: Any) -> None:
    if v is None:
        entry.pop(k, None)
    else:
        entry[k] = v


def label_login(data: dict[str, Any], ref: str, label: object, sent: str | None = None) -> str:
    """`ao login label <login> [<label>]`: a label only, the name fixed; none clears it."""
    lk, e = resolve(data, ref)
    check_version(e, sent, lk)
    text = _one_line(label, "label", LABEL_MAX)
    _put(e, "label", text)
    return f"{lk} labelled {text!r}" if text else f"{lk}'s label cleared"


def label_account(data: dict[str, Any], key: str, label: object, sent: str | None = None) -> str:
    """`ao account label <key> [<label>]`: an account named by its key, one a login of this host is under."""
    if key not in live_keys(data):
        raise LoginError(f"no account {key} on this host: an account is named by its key, <tool>:<name>")
    entry = data["accounts"].get(key)
    check_version(entry, sent, key)
    text = _one_line(label, "label", LABEL_MAX)
    entry = dict(entry or {})
    _put(entry, "label", text)
    if entry:
        data["accounts"][key] = entry
    else:
        data["accounts"].pop(key, None)
    return f"account {key} labelled {text!r}" if text else f"account {key}'s label cleared"


def note_login(data: dict[str, Any], ref: str, text: object, sent: str | None = None) -> str:
    """`ao login note <login> <text>`: the note drawn in italics under the login; empty clears it."""
    lk, e = resolve(data, ref)
    check_version(e, sent, lk)
    got = _one_line(text, "note", NOTE_MAX)
    _put(e, "note", got)
    return f"{lk}'s note set" if got else f"{lk}'s note cleared"


def _arg_list(v: object, k: str) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(a, str) for a in v):
        raise LoginError(f"{k} is a list of arguments, not {v!r}")
    return list(v)


def _sharing(data: Mapping[str, Any], lk: str) -> list[tuple[str, Mapping[str, Any]]]:
    """The other logins whose folder is `lk`'s, in key order: the logins §4.2a's metered-folder rule compares."""
    folder = str(data["logins"][lk].get("folder") or "")
    if not folder:
        return []
    mine = Path(folder).expanduser().resolve()
    return [
        (other, oe)
        for other, oe in sorted(data["logins"].items())
        if other != lk and oe.get("folder") and Path(str(oe["folder"])).expanduser().resolve() == mine
    ]


def setting_value(
    data: Mapping[str, Any],
    lk: str,
    k: str,
    v: object,
    *,
    default_home: bool,
    spends: bool,
    families: Iterable[str] | None,
) -> Any:
    """A login's Settings value checked by §4.2a's rules (§4.2b *A login's Settings*), or None to clear it.
    `default_home`: the login's folder is its tool's default home; `spends`: its adapter reports spend; `families`: the
    model families its account offers, None where no read has them."""
    e = data["logins"][lk]
    if k not in SETTINGS:
        raise LoginError(f"{k!r} is not a login's setting ({', '.join(SETTINGS)})")
    if v is None or v == "":
        if k == "billing" and e.get("prices"):
            raise LoginError(f"{lk} has prices: clear them before its billing")
        return None
    if k == "billing":
        if v not in BILLINGS:
            raise LoginError(f"billing is {' or '.join(BILLINGS)}, not {v!r}")
        if v == "metered":
            if default_home:
                raise LoginError(
                    f"{lk} is on its tool's default home: a metered login's spend is read from its own folder's "
                    "transcripts, so it needs a folder of its own (design §4.2a)"
                )
            if not spends:
                raise LoginError(f"{lk} cannot be metered: its tool reports no spend, so an amount would bind nothing")
            mine = account_of(lk, e)
            for other, oe in _sharing(data, lk):
                if account_of(other, oe) != mine:
                    raise LoginError(
                        f"{lk} shares its folder with {other}, another account: a metered login's spend would count "
                        "that account's turns (design §4.2a)"
                    )
        elif e.get("prices"):
            raise LoginError(f"{lk} has prices, a metered login's: clear them before making it a subscription")
        return v
    if k == "prices":
        if e.get("billing") != "metered":
            raise LoginError(f"prices belong to a metered login: set {lk}'s billing to metered first")
        if not isinstance(v, dict):
            raise LoginError(f"prices is a mapping of {', '.join(PRICE_KINDS)} to a price per million tokens")
        out: dict[str, float] = {}
        for kind, p in v.items():
            if kind not in PRICE_KINDS:
                raise LoginError(f"prices.{kind} is not a token kind ({', '.join(PRICE_KINDS)})")
            if isinstance(p, bool) or not isinstance(p, int | float) or not math.isfinite(p) or p < 0:
                raise LoginError(f"prices.{kind} is a price per million tokens, not {p!r}")
            out[str(kind)] = float(p)
        return out
    if k in ("extra_args", "unattended_args"):
        return _arg_list(v, k)
    if k == "permission_wait":
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise LoginError(f"permission_wait is a number of seconds, not {v!r}")
        return v
    if k == "pin":
        if not isinstance(v, str):
            raise LoginError(f"a pin is a model family's name, not {v!r}")
        offered = list(families or [])
        if not offered:
            raise LoginError(f"{lk}'s account has no model families read yet: Check again, then pin")
        if v not in offered:
            raise LoginError(f"{v!r} is not a family {lk}'s account offers ({', '.join(offered)})")
        return v
    raise LoginError(f"{k!r} is not a login's setting ({', '.join(SETTINGS)})")


def set_setting(data: dict[str, Any], ref: str, k: str, v: object, sent: str | None = None, **rules: Any) -> str:
    """`ao login set <login> <key> <value>`, the key one of `SETTINGS` (§4.2b *A login's Settings*)."""
    lk, e = resolve(data, ref)
    check_version(e, sent, lk)
    got = setting_value(data, lk, k, v, **rules)
    _put(e, k, got)
    return f"{lk} {k} set" if got is not None else f"{lk} {k} cleared"


def join(
    data: dict[str, Any],
    ref: str,
    target: str,
    sent: str | None = None,
    *,
    reserve_keys: Iterable[str] = (),
    matches: Mapping[str, str] | None = None,
    families: Callable[[str], Iterable[str] | None] = lambda acct: None,
) -> str:
    """`ao login account <login> <key or new name>` (§4.2b *Matching across a restart*): an account's key, or its
    name (the key `<tool>:<name>`), a name no account has making a new key. A bare name composing to a retired key is
    refused; its full key rejoins it deliberately. Refused where the result would leave a mismatch: a match another
    account's logins read, or an account whose logins read another. `matches` is this run's last match of each
    login (`Memory.last`); a login with none is compared with nothing. `families` gives the model families an account
    offers, None where no read has them: a pin is a family the login's account offers (§4.2b *A login's Settings*), so
    a pin the joined account does not offer, or one no read can check, is cleared."""
    lk, e = resolve(data, ref)
    check_version(e, sent, lk)
    acct = account_key(data, split(lk)[0], target, reserve_keys, who=lk)
    if acct == account_of(lk, e):
        raise LoginError(f"{lk} is under {acct} already")
    mine = (matches or {}).get(lk)
    for other, oe in sorted(data["logins"].items()):
        theirs = (matches or {}).get(other)
        if other == lk or not mine or not theirs:
            continue
        under = account_of(other, oe)
        if theirs == mine and under != acct:
            raise LoginError(f"{other} reads the same account as {lk} and is under {under}: name that one instead")
        if under == acct and theirs != mine:
            raise LoginError(f"{other} is under {acct} and reads another account than {lk}")
    for other, oe in _sharing(data, lk):  # §4.2a: a metered login's folder is its account's alone, a join too
        metered = lk if e.get("billing") == "metered" else other if oe.get("billing") == "metered" else None
        if metered and account_of(other, oe) != acct:
            raise LoginError(
                f"{lk} shares its folder with {other}, and {metered} is metered: under {acct} its spend would count "
                "another account's turns (design §4.2a)"
            )
    left, new = account_of(lk, e), acct not in live_keys(data)
    _put(e, "account", None if acct == lk else acct)
    if left not in live_keys(data):  # its last login gone, the account's entry leaves `accounts:`, as forget's does
        data["accounts"].pop(left, None)
    pin = e.get("pin")
    if not pin:
        return f"{lk} joined {acct}"
    offered = families(acct)
    if offered is not None and pin in set(offered):
        return f"{lk} joined {acct}"
    del e["pin"]
    if offered is not None:
        why = f"{acct} offers no {pin}"
    elif new:
        why = f"{acct} is a new account no read has yet: pin it once it is signed in"
    else:
        why = f"{acct}'s families are not read yet: Check again, then pin"
    return f"{lk} joined {acct}; its pin {pin} cleared, as {why}"


def account_key(
    data: Mapping[str, Any], tool: str, target: str, reserve_keys: Iterable[str] = (), who: str = "the login"
) -> str:
    """The account a name or a key names for a login of `tool` (§4.2b *Matching across a restart*): a key as given,
    its tool `tool`'s; a bare name `<tool>:<name>`, refused where that is a retired key, whose full key rejoins it."""
    target = str(target or "").strip()
    if ":" in target:
        a, n = split(target)
        if a != tool:
            raise LoginError(f"{target} is an account of {a}, and {who} is a {tool} login")
        if not valid_name(n):
            raise LoginError(f"{target} is not an account's key: <tool>:<name>, the name at most 24 letters and digits")
        return target
    if not valid_name(target):
        raise LoginError(f"{target!r} is not an account name: at most 24 letters, digits, '-' and '_'")
    acct = key(tool, target)
    if acct in retired(data, reserve_keys):
        raise LoginError(
            f"{acct} is a forgotten account's key: give the full key, {acct}, to rejoin it and its reserve, "
            "or another name"
        )
    return acct


def add(
    data: dict[str, Any],
    tool: str,
    folder: Path,
    name: str | None,
    account: str | None = None,
    *,
    tools: Iterable[str] = (),
    reserve_keys: Iterable[str] = (),
    same: Callable[[Path, Path], bool] = lambda a, b: a == b,
    suggested: str | None = None,
) -> tuple[str, str]:
    """`ao login add <tool> [--path] [--name] [--account]` (§4.2b *Controls and verbs*, *Where it lives*): `folder` a
    login of `tool`, named `name`. A folder already a login's is refused; a forgotten login's folder takes back its old
    name and account, and a different `name` is refused; a forgotten login's name is refused any other folder, so a
    record never resolves to another folder. `account` names the login's account up front (`account_key`); `same`
    compares two folders; `suggested` is the base of a name to suggest where none is given (`<tool>-<display>`), a
    suffix added where it is taken. Returns the new login's key and the change's words."""
    folder = Path(folder)
    for lk, e in sorted(data["logins"].items()):
        if split(lk)[0] == tool and same(Path(str(e.get("folder") or "")).expanduser(), folder):
            raise LoginError(f"{folder} is {lk}'s folder already")
    back = sorted(
        lk
        for lk, f in data["forgotten"].items()
        if split(lk)[0] == tool and same(Path(str((f or {}).get("folder") or "")).expanduser(), folder)
    )
    if back:
        old = split(back[0])[1]
        if name and name != old:
            raise LoginError(f"{folder} was the login {back[0]}: it takes back its name, {old}, and no other")
        name = old
    if not name and suggested:
        taken = {split(k)[1] for k in (*data["logins"], *data["forgotten"]) if split(k)[0] == tool}
        name = suggest(suggested, taken)
    if not name:
        raise LoginError("name the new login (--name): its tool records no display name to suggest one from")
    lk = key(tool, name)
    if not back and lk in data["forgotten"]:
        raise LoginError(f"{lk} is a forgotten login's name, kept for its own folder: give another name")
    why = name_taken(data, tool, name, tools)
    if why:
        raise LoginError(why)
    entry: dict[str, Any] = {"folder": str(folder)}
    if back:
        was = data["forgotten"].pop(lk)
        if was.get("account") and was["account"] != lk:
            entry["account"] = was["account"]
    if account:
        acct = account_key(data, tool, account, reserve_keys)
        if acct != lk:
            entry["account"] = acct
        else:  # its own account, named over a forgotten login's old one
            entry.pop("account", None)
    data["logins"][lk] = entry
    under = f" under {entry['account']}" if entry.get("account") else ""
    return lk, f"{lk} added{' back' if back else ''}{under}"


def forget(data: dict[str, Any], ref: str, sent: str | None = None, *, in_use: Iterable[str] = ()) -> str:
    """`ao login forget <login>` (§4.2b *⋯ on a login*): moved to `forgotten:` with its folder and account, the folder
    left on disk. Refused, naming them, while `in_use` names anything that runs on it or names it. An account whose last
    login this was leaves `accounts:`; its key is then retired."""
    lk, e = resolve(data, ref)
    check_version(e, sent, lk)
    users = sorted(set(in_use))
    if users:
        raise LoginError(f"{lk} cannot be forgotten while {', '.join(users)} use it")
    acct = account_of(lk, e)
    data["forgotten"][lk] = {"folder": e.get("folder"), "account": acct}
    del data["logins"][lk]
    if acct not in live_keys(data):
        data["accounts"].pop(acct, None)
    return f"{lk} forgotten"
