"""Profiles: (adapter, account, model), declared once per host in `~/.shiftlead/profiles.yml` (design §4.2a).

```yaml
default: paul
profiles:
  paul:  {adapter: claude-code, account: paul,  model: opus,   config_dir: ~/.claude}
  grind: {adapter: claude-code, account: grind, model: sonnet, config_dir: ~/.claude-grind,
          permission_wait: 600, unattended_args: [--dangerously-skip-permissions]}
  api:   {adapter: claude-code, account: api-key, config_dir: ~/.claude-api,
          billing: metered,             # an API key: spend per turn, never a quota poll (design §4.2a)
          # per million tokens, one per kind; a cache kind left out is charged at `input`, the safe
          # side — most of a coding agent's input is cache reads at a tenth of the input rate
          prices: {input: 3, output: 15, cache_read: 0.3, cache_write: 3.75}}
```

`billing` (design §4.2a *How a profile is billed*, TD-151): `subscription` — the default, bound by the
account's quota windows — or `metered`, bound by an amount on its spend; `prices` only on a metered
profile, and none at all for a self-hosted model, whose reading is tokens.

With no file, one implicit profile named `default` uses the tool's own default config directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from sessionorc import paths

DEFAULT_ADAPTER = "claude-code"  # a profile that names none, and a team member with no profile (teams.create_params)
SHELL_ADAPTER = "shell"  # no agent: a profile may name it, a team session may not (teams.plan, TD-329)
DEFAULT_PERMISSION_WAIT = 600  # seconds; long enough to reach a phone (design §4.2)
PERMISSION_PROMPTS = ("skip", "ask", "all")  # §4.2a, TD-641, TD-823: the first is the default
BILLINGS = ("subscription", "metered")
PRICE_KINDS = ("input", "output", "cache_read", "cache_write")


@dataclass
class Profile:
    name: str
    adapter: str = DEFAULT_ADAPTER
    account: str = ""
    model: str | None = None
    config_dir: Path | None = None  # the tool's per-account config directory
    permission_wait: int = DEFAULT_PERMISSION_WAIT
    extra_args: list[str] = field(default_factory=list)
    unattended_args: list[str] = field(default_factory=list)
    permission_prompts: str = "skip"  # §4.2a: `ask` and `all` launch unattended without the adapter's skip flag
    billing: str = "subscription"  # §4.2a: or `metered` — never guessed from the directory or the environment
    prices: dict[str, float] = field(default_factory=dict)  # per million tokens, by kind; a metered profile's

    @property
    def metered(self) -> bool:
        return self.billing == "metered"

    @property
    def label(self) -> str:
        parts = [self.adapter, self.account or self.name]
        if self.model:
            parts.append(self.model)
        if self.metered:
            parts.append("metered")
        return " · ".join(parts)


def _billing(name: str, raw: dict) -> tuple[str, dict[str, float]]:
    """A profile's `billing` and `prices` (design §4.2a), checked: an unknown billing, prices on a
    subscription, an unknown token kind or a price that is not a number at or above zero is the
    file's error, named, never a guess — a wrong one pauses nothing or everything."""
    billing = str(raw.pop("billing", "subscription") or "subscription")
    if billing not in BILLINGS:
        raise ValueError(f"profiles.yml: {name}.billing is {' or '.join(BILLINGS)}, not {billing!r}")
    prices = raw.pop("prices", None)
    if prices is None:
        return billing, {}
    if billing != "metered":
        raise ValueError(f"profiles.yml: {name}.prices belongs to a metered profile (billing: metered)")
    if not isinstance(prices, dict):
        raise ValueError(f"profiles.yml: {name}.prices is a mapping of {', '.join(PRICE_KINDS)} to a price per million")
    out: dict[str, float] = {}
    for kind, v in prices.items():
        if kind not in PRICE_KINDS:
            raise ValueError(f"profiles.yml: {name}.prices.{kind} is not a token kind ({', '.join(PRICE_KINDS)})")
        if isinstance(v, bool) or not isinstance(v, int | float) or v < 0:
            raise ValueError(f"profiles.yml: {name}.prices.{kind} is a price per million tokens, not {v!r}")
        out[str(kind)] = float(v)
    return billing, out


def _permission_prompts(name: str, raw: dict) -> str:
    """`permission_prompts: skip | ask | all` (§4.2a, TD-641, TD-823), `skip` when absent; anything else is the file's
    error, named — a guess either way launches a member with or without its prompts."""
    word = raw.pop("permission_prompts", None)
    if word is None:
        return PERMISSION_PROMPTS[0]
    if word not in PERMISSION_PROMPTS:
        raise ValueError(f"profiles.yml: {name}.permission_prompts is skip, ask or all, not {word!r}")
    return str(word)


def _metered_dirs(profiles: dict[str, Profile]) -> None:
    """A metered profile's spend is read from every transcript under its config directory (§4.3), so
    the directory must be its account's alone: one with no `config_dir` would read the tool's
    default, and one sharing a directory with another account's profile would bill that account's
    turns to this one. Both are the file's error, named (TD-151)."""
    for p in profiles.values():
        if not p.metered:
            continue
        if p.config_dir is None:
            raise ValueError(
                f"profiles.yml: {p.name} is metered and names no config_dir — its spend is read from its own "
                "transcripts, so it needs a directory of its own (design §4.2a)"
            )
        for q in profiles.values():
            if q is not p and q.config_dir == p.config_dir and (q.account or q.name) != (p.account or p.name):
                raise ValueError(
                    f"profiles.yml: {p.name} is metered and shares config_dir {p.config_dir} with {q.name}, another "
                    "account — its spend would count that account's turns (design §4.2a)"
                )


def _adapter_rules(profiles: dict[str, Profile]) -> None:
    """The two rules of the load that read a profile's adapter (design §4.2a, §4.3, TD-1550), naming no tool: a
    profile of an adapter that writes into its tool home (`own_home`) names a `config_dir` of its own — set, not
    that home, and shared only with profiles of the same account — and a metered profile of an adapter that
    reports no `spend` is refused, since its amount would bind nothing. The adapter is resolved here, lazily,
    since the adapters import this module; a profile whose adapter is not registered is checked by neither."""
    from sessionorc import adapters

    for p in profiles.values():
        try:
            ad = adapters.get(p.adapter)
        except KeyError:
            continue
        own = getattr(ad, "own_home", None)
        if own is not None:
            mine = p.config_dir.resolve() if p.config_dir is not None else None
            shared = any(
                q is not p
                and q.config_dir is not None
                and q.config_dir.resolve() == mine
                and (q.account or q.name) != (p.account or p.name)
                for q in profiles.values()
            )
            if mine is None or mine == Path(own).expanduser().resolve() or shared:
                raise ValueError(f"profiles.yml: {p.name} needs a config_dir of its own ({p.adapter} writes into it)")
        if p.metered and not callable(getattr(ad, "spend", None)):
            raise ValueError(f"profiles.yml: {p.name} is metered, but {p.adapter} reports no spend")


def profiles_file() -> Path:
    return paths.home() / "profiles.yml"


def load(path: Path | None = None) -> tuple[dict[str, Profile], str]:
    """Return (profiles by name, default profile name)."""
    path = path or profiles_file()
    if not path.is_file():
        return {"default": Profile(name="default")}, "default"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, Profile] = {}
    for name, raw in (data.get("profiles") or {}).items():
        raw = dict(raw or {})
        cfg = raw.pop("config_dir", None)
        billing, prices = _billing(name, raw)
        out[name] = Profile(
            name=name,
            adapter=raw.pop("adapter", DEFAULT_ADAPTER),
            account=str(raw.pop("account", "") or ""),
            model=raw.pop("model", None),
            config_dir=Path(cfg).expanduser() if cfg else None,
            permission_wait=int(raw.pop("permission_wait", DEFAULT_PERMISSION_WAIT)),
            extra_args=list(raw.pop("extra_args", []) or []),
            unattended_args=list(raw.pop("unattended_args", []) or []),
            permission_prompts=_permission_prompts(name, raw),
            billing=billing,
            prices=prices,
        )
    _metered_dirs(out)
    _adapter_rules(out)
    if not out:
        out["default"] = Profile(name="default")
    default = data.get("default") or next(iter(out))
    if default not in out:
        raise ValueError(f"profiles.yml: default {default!r} is not a declared profile ({sorted(out)})")
    return out, default


def account_of(name: str | None, adapter: str, path: Path | None = None) -> str | None:
    """The account the profile `name` runs under (§4.2a, TD-122) — its `account`, else its name — asked
    of `adapter`, which answers only for a profile naming it (§6 *A reserve is the account's*, TD-1581):
    None for a profile of another adapter, an unknown one, or an unreadable file. `""` or None is the
    default profile."""
    try:
        prof = get(name or None, path)
    except (KeyError, ValueError, OSError, yaml.YAMLError):
        return None
    return (prof.account or prof.name) if prof.adapter == adapter else None


def for_adapter(adapter: str, path: Path | None = None) -> list[dict[str, str]]:
    """The profiles naming `adapter`, each `{name, account, billing}` (§4.3 `profiles()`, TD-1581): how
    the core, which reads no profile list, knows an account's profiles. An unreadable file lists none."""
    try:
        profiles, _ = load(path)
    except (ValueError, OSError, yaml.YAMLError):
        return []
    return [
        {"name": p.name, "account": p.account or p.name, "billing": p.billing}
        for p in profiles.values()
        if p.adapter == adapter
    ]


def get(name: str | None, path: Path | None = None) -> Profile:
    profiles, default = load(path)
    key = name or default
    try:
        return profiles[key]
    except KeyError:
        raise KeyError(f"unknown profile {key!r}; known: {sorted(profiles)}") from None
