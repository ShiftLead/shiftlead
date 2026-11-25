"""The switch-over's check (design §4.9e *The three commands*, TD-2071): what the move would make, and what stands in
its way, with nothing changed.

A host gains a login for each distinct folder among its profiles, and its blockers are those to cure beforehand
(§4.2b *What the switch-over makes*):
- profiles on one folder that disagree on a launch setting;
- profiles on one folder that give more than one key;
- two keys whose folders read one identity, or one key whose folders read two;
- a name the rules refuse, or two names of one tool with one fold;
- one folder reached both as a `config_dir` and as the tool's default;
- a pinned model the adapter's table cannot map.
Each login is named by the answers file (`~/.shiftlead/switch-over/answers.yml`), which `read_answers` reads, and a
folder it names nothing for is a blocker (`unnamed`). `teams` gives each team of the org the flow, logins and counts the
answers give it, with §4.9e *Blockers*' team cases: no flow, a flow the team's host cannot follow, an empty list, a
login its host would not have, a model no login in its list offers.
`ao switch-over check` prints them, and exits non-zero while a blocker to cure beforehand stands.
The built-in set, the director, the work in flight, a container node's logins, writing the answers file (`--answers`)
and `--host` are later slices of TD-2071.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sessionorc import adapters, logins, naming, paths, yamltext
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
    match: str | None = None  # who the folder is signed in as, salted (§4.2b), None where it cannot be read
    models: list[str] = field(default_factory=list)  # the families its account offers, before the pin narrows them

    @property
    def key(self) -> str:
        """The login's key, `<tool>:<name>`, as a team's list names it (§4.9d *The logins, in order*)."""
        return f"{self.tool}:{self.name}"

    @property
    def found(self) -> str:
        """The answers file's key for the folder, `<tool>:<folder>`, the folder written from `~`."""
        return f"{self.tool}:{shown(self.folder)}"


def shown(path: Path) -> str:
    """A folder as the person reads it: under their home, from `~`."""
    for home in dict.fromkeys((Path.home(), Path.home().resolve())):
        if path == home:
            return "~"
        if path.is_relative_to(home):
            return "~/" + str(path.relative_to(home))
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


def _identity(adapter: Any, folder: Path, salt: bytes) -> dict[str, Any]:
    """What the folder's record says of its account: `match` and `plan`, {} where it cannot be read."""
    reader = getattr(adapter, "identity", None)
    try:
        got = reader(folder, salt) if callable(reader) else None
    except Exception:  # noqa: BLE001 — a home whose record cannot be read has no identity to compare
        return {}
    return got if isinstance(got, dict) else {}


def _offer(adapter: Any, folder: Path, plan: Any) -> list[str]:
    """The model families the folder's account offers by the adapter's table (§4.2b `models(home, plan)`)."""
    reader = getattr(adapter, "models", None)
    try:
        got = reader(folder, plan if isinstance(plan, str) else None) if callable(reader) else None
    except Exception:  # noqa: BLE001 — an adapter whose table raises offers nothing
        return []
    families = got.get("families") if isinstance(got, dict) else None
    return [str(f) for f in families] if isinstance(families, list) else []


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
    does not name takes its first profile's name. A `shell` profile, one whose adapter is not registered, and one
    whose folder cannot be read makes no login. The tool's default home is read with no environment of the caller's
    (`env` empty unless given), so the check does not change with the shell it is run from."""
    env = {} if env is None else env
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
        try:
            if p.config_dir is not None:
                folder, by_default = Path(p.config_dir).expanduser().resolve(), False
            elif callable(default):
                folder, by_default = Path(default(env)).expanduser().resolve(), True
            else:
                continue
        except Exception:  # noqa: BLE001, S112 — a home that cannot be read (an adapter that raises) makes no login
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
        ident = _identity(tools[tool], folder, salt)
        match = ident.get("match")
        made.append(
            Login(
                tool,
                folder,
                name,
                [p.name for p in profs],
                keys,
                settings,
                pin,
                match if isinstance(match, str) and match else None,
                _offer(tools[tool], folder, ident.get("plan")),
            )
        )

    blockers += _name_blockers(where, made)
    blockers += _identity_blockers(where, made)
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


def _identity_blockers(where: str, made: Iterable[Login]) -> list[Blocker]:
    by_key: dict[str, dict[str, list[str]]] = {}
    by_match: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for login in made:
        match = login.match
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


ANSWERS = "the answers"  # a blocker's `where` for the file itself


def answers_file() -> Path:
    """The answers file (§4.9e *The three commands*): what the person decides, read before anything runs."""
    return paths.home() / "switch-over" / "answers.yml"


def read_answers(path: Path | None = None) -> tuple[dict[str, Any] | None, list[Blocker]]:
    """The answers file as a mapping, or None with the blocker that says why: there is none, it does not parse, or a
    top-level key holds something other than a mapping. Its values are judged where they are read."""
    path = path or answers_file()
    at = shown(path)
    if not path.is_file():
        return None, [
            Blocker(
                ANSWERS,
                f"there is no answers file at {at}",
                "write it, naming each login and each team's flow (design §4.9e The three commands)",
            )
        ]
    try:
        doc = yamltext.load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as e:
        return None, [Blocker(ANSWERS, f"{at} cannot be read: {e}", "mend the file")]
    doc = {} if doc is None else doc
    if not isinstance(doc, dict):
        return None, [Blocker(ANSWERS, f"{at} is not a mapping", "write hosts:, teams:, builtins: at its top level")]
    bad = [
        k for k in ("hosts", "teams", "builtins", "director") if doc.get(k) is not None and not isinstance(doc[k], dict)
    ]
    if bad:
        return None, [Blocker(ANSWERS, f"{at}: {', '.join(bad)} must each be a mapping", "mend the file")]
    return doc, []


def _under(doc: Any, *keys: str) -> Mapping[str, Any]:
    """`doc[k1][k2]…` where each is a mapping, else {}."""
    for k in keys:
        doc = doc.get(k) if isinstance(doc, Mapping) else None
    return doc if isinstance(doc, Mapping) else {}


def _name(row: Any) -> str | None:
    got = row.get("name") if isinstance(row, Mapping) else None
    return got.strip() if isinstance(got, str) and got.strip() else None


def names_of(answers: Mapping[str, Any] | None, host: str) -> dict[str, str]:
    """The names the answers give `host`'s folders, by `<tool>:<folder>`: `hosts.<host>.logins.<found>.name`."""
    return {
        str(found): name
        for found, row in _under(answers, "hosts", host, "logins").items()
        if (name := _name(row)) is not None
    }


def unnamed(host: str, made: Iterable[Login], answers: Mapping[str, Any] | None) -> list[Blocker]:
    """A blocker for each folder the answers give no name (§4.9e *Blockers*). With no answers file there is one
    blocker for the file, and none here."""
    if answers is None:
        return []
    named = names_of(answers, host)
    return [
        Blocker(
            f"host {host}",
            f"{login.found} has no name in the answers",
            f'give it hosts.{host}.logins."{login.found}".name in the answers file',
        )
        for login in made
        if login.found not in named
    ]


@dataclass
class TeamPlan:
    """A team as the answers would make it (§4.9d *What the cut-over's move must produce*): its repo and host as
    today's definition lands it, and the flow, logins and counts the answers give it. `note` says what is not
    checked here."""

    name: str
    repo: str
    host: str
    flow: str | None = None
    logins: list[str] = field(default_factory=list)
    at_once: dict[str, int] = field(default_factory=dict)
    most: int | None = None
    label: str | None = None
    note: str | None = None


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def teams(
    org: Any,
    answers: Mapping[str, Any] | None,
    here: str,
    made: Iterable[Login],
    roots: Iterable[str | Path],
    *,
    nodes: Mapping[str, Mapping[str, Any]] | None = None,
    offered: Callable[[str], list[Mapping[str, Any]]] | None = None,
) -> tuple[list[TeamPlan], list[Blocker]]:
    """Each team of `org` (`shiftlead.org.Org`, as `ao org` aggregates it) with what the answers give it, and §4.9e
    *Blockers*' team cases. `made` is the home's logins; a team on the home is checked against them, its flow's
    models too. A team on a node has its list checked for emptiness and its flow for reaching the node, and its
    logins not here: an ssh node's are its own (§4.9d *A team on a node*), and a container node's profiles are not
    read yet. `nodes` is `hosts.nodes()`; `offered` gives a repo's flows (`team_show.offered`). With no answers file
    no team has a pick, and the file's own blocker says so."""
    from shiftlead import team_show

    if nodes is None:
        from sessionorc import hosts

        nodes = hosts.nodes()
    where_roots = list(roots)
    offered = offered or (lambda repo: team_show.offered(repo, where_roots))
    rows = {lg.key: {"models": lg.models, "pin": lg.pin} for lg in made}
    picks = _under(answers, "teams")
    plans: list[TeamPlan] = []
    out: list[Blocker] = []
    for name in sorted(org.teams):
        team = org.teams[name]
        host = team.host or here
        at = f"team {name}"
        plan = TeamPlan(name, team.repo, host)
        plans.append(plan)
        if name in org.unlanded:
            out.append(Blocker(at, org.unlanded[name], "land it in the old shape, or take its definition out"))
            continue
        if host != here and host not in nodes:
            out.append(
                Blocker(
                    at, f"runs on {host}, which is not a node of this home", "take its definition out in the old shape"
                )
            )
            continue
        if answers is None:
            continue
        pick = picks.get(name)
        pick = pick if isinstance(pick, Mapping) else {}
        out += _team_blockers(plan, pick, at)
        if plan.flow is None:
            continue
        on_node = host != here
        if on_node:
            kind = "a container" if isinstance(nodes.get(host), Mapping) and nodes[host].get("container") else "an ssh"
            plan.note = f"not checked: the logins of {host}, {kind} node, are not read here"
        else:
            out += [
                Blocker(at, f"lists {lk}, a login {here} would not have", f"take it out of teams.{name}.logins")
                for lk in plan.logins
                if lk not in rows
            ]
        row = next((r for r in offered(team.repo) if r["name"] == plan.flow), None)
        if row is None:
            out.append(
                Blocker(
                    at,
                    f"its flow {plan.flow} is no format-3 flow it could be given",
                    f"give teams.{name}.flow a built-in, one of yours or one of {team.repo}'s",
                )
            )
            continue
        # a login the home lacks is its own blocker above, so the models are read of the logins it would have
        known = plan.logins if on_node else [lk for lk in plan.logins if lk in rows]
        why = team_show.cannot_pick(name, row, {"host": host, "logins": known}, rows, here)
        if why == team_show.NODE_REPO_FLOW:
            plan.note = f"not checked: {host}'s checkout of {team.repo} is not read here"
        elif why and not (known == [] and why.endswith("its login list is empty")):
            out.append(
                Blocker(at, f"its flow {plan.flow}: {why}", f"pick another flow, or mend {plan.flow} or its list")
            )
    known = set(org.teams)
    out += [
        Blocker(ANSWERS, f"teams.{name} names no team of the org", "take it out of the answers file")
        for name in picks
        if name not in known
    ]
    return plans, out


def _team_blockers(plan: TeamPlan, pick: Mapping[str, Any], at: str) -> list[Blocker]:
    """The answers' own shape for one team, written onto `plan`: a flow, a list of logins, whole numbers."""
    out: list[Blocker] = []
    flow = pick.get("flow")
    if isinstance(flow, str) and flow.strip():
        plan.flow = flow.strip()
    else:
        out.append(
            Blocker(at, "has no flow in the answers", f"give teams.{plan.name}.flow: design-wise takes td's place")
        )
    listed = pick.get("logins")
    if isinstance(listed, list) and all(isinstance(x, str) and all(logins.split(x)) for x in listed):
        plan.logins = list(listed)
    elif listed is not None:
        out.append(Blocker(at, "its logins are not a list of <tool>:<name>", f"mend teams.{plan.name}.logins"))
    if not plan.logins:
        out.append(Blocker(at, "its login list is empty", f"list a login in teams.{plan.name}.logins"))
    at_once = pick.get("at_once")
    if isinstance(at_once, Mapping) and all(_count(v) for v in at_once.values()):
        plan.at_once = {str(k): int(v) for k, v in at_once.items()}
    elif at_once is not None:
        out.append(
            Blocker(at, "its at_once is not whole numbers of 1 or more by stage", f"mend teams.{plan.name}.at_once")
        )
    most = pick.get("most")
    if _count(most):
        plan.most = int(most)
    elif most is not None:
        out.append(Blocker(at, "its most is not a whole number of 1 or more", f"mend teams.{plan.name}.most"))
    label = pick.get("label")
    plan.label = label.strip() if isinstance(label, str) and label.strip() else None
    return out


def team_lines(plans: Iterable[TeamPlan]) -> list[str]:
    """`ao switch-over check`'s lines for the teams: each with what the answers give it."""
    plans = list(plans)
    lines = ["teams the answers give"]
    for p in plans:
        label = f' (shown as "{p.label}")' if p.label else ""
        if p.flow is None:
            lines.append(f"  {p.name}{label}: {p.repo} on {p.host}, no flow picked")
        else:
            counts = ", ".join(f"{k} {v}" for k, v in p.at_once.items()) or "1 a stage"
            most = f", at most {p.most} in all" if p.most is not None else ""
            listed = ", ".join(p.logins) or "no logins"
            lines.append(
                f"  {p.name}{label}: {p.repo} on {p.host}, flow {p.flow}; logins {listed}; at once {counts}{most}"
            )
        if p.note:
            lines.append(f"    {p.note}")
    if not plans:
        lines.append("  none: the org defines no team")
    return lines


def report(
    host: str, made: Iterable[Login], blockers: Iterable[Blocker], plans: Iterable[TeamPlan] | None = None
) -> list[str]:
    """`ao switch-over check`'s lines: the host's logins, the teams where `plans` is given, then every blocker, those
    of the day last."""
    lines = [f"{host}: logins the move would make"]
    made = list(made)
    for login in made:
        pin = f", pinned to {login.pin}" if login.pin else ""
        lines.append(f"  {login.tool}:{login.name}  {shown(login.folder)}  from {', '.join(login.profiles)}{pin}")
    if not made:
        lines.append("  none: no profile here names a registered tool")
    if plans is not None:
        lines += team_lines(plans)
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
