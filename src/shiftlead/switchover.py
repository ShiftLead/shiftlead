"""The switch-over's check (design §4.9e *The three commands*, TD-2071): what the move would make, and what stands in
its way, with nothing changed.

This slice reads one host's profiles. A host gains a login for each distinct folder among its profiles, and its
blockers are those to cure beforehand (§4.2b *What the switch-over makes*):
- profiles on one folder that disagree on a launch setting;
- profiles on one folder that give more than one key;
- two keys whose folders read one identity, or one key whose folders read two;
- a name the rules refuse, or two names of one tool with one fold;
- one folder reached both as a `config_dir` and as the tool's default;
- a pinned model the adapter's table cannot map.
`ao switch-over check` prints what `host_logins` returns, and exits non-zero while a blocker to cure beforehand stands.
The teams, the built-in set, the work in flight, the answers file and `--host` are later slices of TD-2071.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sessionorc import adapters, logins, naming
from shiftlead.profiles import Profile

SETTINGS = ("billing", "prices", "extra_args", "unattended_args", "permission_wait")  # what one folder's must share


@dataclass(frozen=True)
class Blocker:
    """One thing that stands in the move's way: where, what, and what cures it. `day` marks one of the day, printed
    under *to do on the day*, which leaves the check's exit at zero (§4.9e *Blockers*)."""

    where: str
    what: str
    cure: str
    day: bool = False


@dataclass
class Login:
    """A login the move would make on a host, from the profiles on one folder (§4.2b *What the switch-over makes*)."""

    tool: str
    folder: Path
    name: str
    profiles: list[str]
    keys: list[str]
    settings: dict[str, Any] = field(default_factory=dict)
    pin: str | None = None

    @property
    def found(self) -> str:
        """The answers file's key for the folder, `<tool>:<folder>`, the folder written from `~`."""
        return f"{self.tool}:{shown(self.folder)}"


def shown(path: Path) -> str:
    """A folder as the person reads it: under their home, from `~`."""
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home)) if path != home else "~"
    except ValueError:
        return str(path)


def key_of(p: Profile) -> str:
    """The account key a profile's launches read today, unchanged by the move: `<adapter>:<account>`, else
    `<adapter>:<profile name>` (§4.2b *An account per key*)."""
    return f"{p.adapter}:{p.account or p.name}"


def _family(adapter: Any, model: str) -> str | None:
    """The model family `model` maps to through the adapter's table, or None where it has none."""
    mapper = getattr(adapter, "model_family", None)
    try:
        return mapper(model) if callable(mapper) else None
    except Exception:  # noqa: BLE001 — a third-party adapter's table that raises maps nothing
        return None


def _identity(adapter: Any, folder: Path, salt: bytes) -> str | None:
    reader = getattr(adapter, "identity", None)
    try:
        got = reader(folder, salt) if callable(reader) else None
    except Exception:  # noqa: BLE001 — a home whose record cannot be read has no identity to compare
        return None
    match = got.get("match") if isinstance(got, dict) else None
    return match if isinstance(match, str) and match else None


def host_logins(
    host: str,
    profiles: Mapping[str, Profile],
    *,
    names: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
    salt: bytes | None = None,
    adapter_of: Callable[[str], Any] | None = None,
) -> tuple[list[Login], list[Blocker]]:
    """The logins the move would make on `host` from its `profiles`, in the order of each folder's first profile,
    and every blocker to cure beforehand. `names` is the answers' `hosts.<host>.logins.<found>.name`; a folder it
    does not name takes its first profile's name. A `shell` profile, and one whose adapter is not registered, makes
    no login."""
    env = os.environ if env is None else env
    salt = salt if salt is not None else os.urandom(32)
    names = names or {}
    where = f"host {host}"
    if adapter_of is None:
        adapters.load_all()
        adapter_of = adapters.get
    blockers: list[Blocker] = []
    folders: dict[tuple[str, Path], list[tuple[Profile, bool]]] = {}
    tools: dict[str, Any] = {}
    for p in profiles.values():
        if p.adapter == "shell":
            continue
        try:
            adapter = tools[p.adapter] if p.adapter in tools else adapter_of(p.adapter)
        except (KeyError, ValueError):
            continue
        tools[p.adapter] = adapter
        default = getattr(adapter, "default_home", None)
        if p.config_dir is not None:
            folder, by_default = Path(p.config_dir).expanduser().resolve(), False
        elif callable(default):
            folder, by_default = Path(default(env)).expanduser().resolve(), True
        else:
            continue
        folders.setdefault((p.adapter, folder), []).append((p, by_default))

    made: list[Login] = []
    for (tool, folder), on in folders.items():
        profs = [p for p, _ in on]
        at = f"{tool}:{shown(folder)}"
        if len({by for _, by in on}) > 1:
            blockers.append(
                Blocker(
                    where,
                    f"{at} is reached both as a config_dir and as the tool's default home",
                    "in profiles.yml give every profile on it a config_dir, or none",
                )
            )
        settings: dict[str, Any] = {}
        for s in SETTINGS:
            values = {repr(getattr(p, s)) for p in profs}
            if len(values) > 1:
                blockers.append(
                    Blocker(
                        where,
                        f"the profiles on {at} disagree on {s} ({', '.join(p.name for p in profs)})",
                        f"in profiles.yml give them one {s}",
                    )
                )
            settings[s] = getattr(profs[0], s)
        keys = list(dict.fromkeys(key_of(p) for p in profs))
        if len(keys) > 1:
            blockers.append(
                Blocker(
                    where,
                    f"the profiles on {at} give more than one key ({', '.join(keys)})",
                    "in profiles.yml give them one account:, and merge their reserves by hand",
                )
            )
        models = {p.model for p in profs}
        pin = None
        if len(models) == 1 and None not in models:
            model = str(next(iter(models)))
            pin = _family(tools[tool], model)
            if pin is None:
                blockers.append(
                    Blocker(
                        where,
                        f"{at} pins {model}, which the {tool} adapter's table cannot map to a family",
                        "in profiles.yml name a model the adapter knows, or none",
                    )
                )
        name = str(names.get(at) or profs[0].name)
        made.append(Login(tool, folder, name, [p.name for p in profs], keys, settings, pin))

    blockers += _name_blockers(where, made)
    blockers += _identity_blockers(where, made, tools, salt)
    return made, blockers


def _name_blockers(where: str, made: Iterable[Login]) -> list[Blocker]:
    out: list[Blocker] = []
    seen: dict[str, Login] = {}
    for login in made:
        if not logins.valid_name(login.name):
            out.append(
                Blocker(
                    where,
                    f"{login.found} would be named {login.name!r}, which is not a login name",
                    "give it a name in the answers file: at most 24 letters, digits, '-' and '_', the first a letter "
                    "or digit",
                )
            )
            continue
        fold = naming.tools_id(login.tool, login.name)
        if fold in seen:
            out.append(
                Blocker(
                    where,
                    f"{login.found} and {seen[fold].found} would be named {login.name!r} and {seen[fold].name!r}, "
                    "one name of one tool",
                    "give one of them another name in the answers file",
                )
            )
        else:
            seen[fold] = login
    return out


def _identity_blockers(where: str, made: Iterable[Login], tools: Mapping[str, Any], salt: bytes) -> list[Blocker]:
    by_key: dict[str, dict[str, list[str]]] = {}
    by_match: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for login in made:
        match = _identity(tools[login.tool], login.folder, salt)
        if match is None or len(login.keys) != 1:
            continue
        k = login.keys[0]
        by_key.setdefault(k, {}).setdefault(match, []).append(login.found)
        by_match.setdefault((login.tool, match), []).append((k, login.found))
    out: list[Blocker] = []
    for k, matches in by_key.items():
        if len(matches) > 1:
            places = ", ".join(f for fs in matches.values() for f in fs)
            out.append(
                Blocker(
                    where,
                    f"the key {k} has folders signed in as {len(matches)} accounts ({places})",
                    "sign each folder in as one account, or give the profiles of each its own account:",
                )
            )
    for (_tool, _m), pairs in by_match.items():
        keys = sorted({k for k, _ in pairs})
        if len(keys) > 1:
            out.append(
                Blocker(
                    where,
                    f"the keys {', '.join(keys)} are signed in as one account ({', '.join(f for _, f in pairs)})",
                    "in profiles.yml give their profiles one account:, and merge their reserves by hand",
                )
            )
    return out


def report(host: str, made: Iterable[Login], blockers: Iterable[Blocker]) -> list[str]:
    """`ao switch-over check`'s lines for one host: its logins, then its blockers, those of the day last."""
    lines = [f"{host}: logins the move would make"]
    made = list(made)
    for login in made:
        pin = f", pinned to {login.pin}" if login.pin else ""
        lines.append(f"  {login.tool}:{login.name}  {shown(login.folder)}  from {', '.join(login.profiles)}{pin}")
    if not made:
        lines.append("  none: no profile here names a registered tool")
    blockers = list(blockers)
    first = [b for b in blockers if not b.day]
    day = [b for b in blockers if b.day]
    if first:
        lines.append("blockers to cure beforehand")
        lines += [f"  {b.where}: {b.what} — {b.cure}" for b in first]
    if day:
        lines.append("to do on the day")
        lines += [f"  {b.where}: {b.what} — {b.cure}" for b in day]
    if not blockers:
        lines.append("no blockers")
    return lines
