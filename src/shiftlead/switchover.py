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
`builtin_set` reads the answers' `builtins.default`, every seat's model with the package's where it is left out, and
§4.9e *Blockers*' set cases: an empty list on a home with a team, a login the home would not have, a seat's model no
login in the list offers.
Where the org has a director, `director` reads the answers' `director:`, suggests its model and login (the set's
prompts model, and the login made from the profile it launches on today), and blocks on §4.9e *Blockers*' director
cases: no entry, an empty list, a login the home would not have, a model no login in its list offers.
It blocks too on a director list whose every login leaves its prompts on: its `unattended_args` lack the adapter's
`skip_args` (§4.9d *How each one runs*).
`suggest` and `write_answers` are `--answers`: the answers file written where there is none, with what §4.9e *The
answers file* says the home can suggest, with the seats each team runs today that its suggested flow lacks (`lacking`)
in the file's head; the check lists those of the flow the answers pick beside each team. A container node's logins and
`--host` are later slices of TD-2071. `in_flight` lists the work in flight from the home's last repo reading, by the
Offer act's own function, each session the window ends taken as gone, and `first_shape_asks` each open ask to a member
or seat of the first shape (§4.9e *Work in flight*: nothing answers it after the window).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sessionorc import adapters, builtinstore, logins, mail, naming, paths, teamstore, yamltext
from sessionorc.models import Session
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
    asks: bool | None = None  # its `unattended_args` leave its prompts on; None where the adapter names no skip_args

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


def _asks(adapter: Any, args: Any) -> bool | None:
    """Whether an unattended launch on `args` (a login's `unattended_args`) leaves its prompts on: they are given
    and lack one of the adapter's `skip_args` (§4.3). None where the adapter names none, unread."""
    skip = getattr(adapter, "skip_args", None)
    if not isinstance(skip, (list, tuple)) or not skip:
        return None
    args = list(args or [])
    return bool(args) and not all(a in args for a in skip)


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
                _asks(tools[tool], settings.get("unattended_args")),
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
    lacks: list[str] = field(default_factory=list)  # the seats it runs today that its flow lacks (`lacking`)


# The role of a `seats:` line whose work a built-in seat takes after the window (§4.9d *The built-in seats and their
# page*): a sweeper is the set's sweeper. The techlead seat is the set's tech-lead, and is no `seats:` line.
SET_ROLES = ("sweeper",)


def lacking(team: Any, doc: Any) -> list[str]:
    """The seats `team` runs today that the format-3 flow `doc` lacks (§4.9e *The answers file*, §4.9d *What the
    cut-over's move must produce*), each as `<name> (<role>)`, which go at the window. Only its `seats:` lines are
    read: the techlead seat (`techlead:`) is the set's tech-lead, and a sweeper the set's sweeper, never lacking. An
    auditor is had where the flow has an audit whose brief begins with, or is begun by, the first word of its own
    brief's file name, else of its name (`docs-audit.md` and an audit's `docs`; `test-audit-ao-1` and `tests`). Every
    other seat — a fact-checker, an asks seat of any other role — has no place in a format-3 flow, whose stages each
    run on the flow's own model (ao-grind's fact-check seats, Paul, 2026-11-22). A pool is its one line."""
    audits = doc.get("audits") if isinstance(doc, Mapping) else None
    briefs = [str(a["brief"]) for a in audits or () if isinstance(a, Mapping) and isinstance(a.get("brief"), str)]
    out: list[str] = []
    for seat in getattr(team, "seats", None) or ():
        role = str(getattr(seat, "role", "") or "")
        if role in SET_ROLES:
            continue
        name = str(getattr(seat, "name", "") or role)
        if role == "auditor":
            brief = getattr(seat, "brief", None)
            word = (Path(str(brief)).stem if brief else name).split("-")[0].lower()
            if word and any(b.lower().startswith(word) or word.startswith(b.lower()) for b in briefs if b):
                continue
        out.append(f"{name} ({role})")
    return out


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
        if row is not None:
            plan.lacks = lacking(team, row.get("doc"))
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


@dataclass
class SetPlan:
    """The built-in set the answers give (§4.9e *The answers file*, `builtins.default`): every seat's model, the
    package's where the answers leave the seat out, and the ordered list. `director` marks an org with a director,
    whose prompts seat is not written. `note` says what is not checked here."""

    models: dict[str, str]
    logins: list[str] = field(default_factory=list)
    director: bool = False
    note: str | None = None


SET = "the built-in set"  # a set blocker's `where`


def builtin_set(
    answers: Mapping[str, Any] | None,
    made: Iterable[Login],
    plans: Iterable[TeamPlan],
    here: str,
    *,
    director: bool = False,
    nodes: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[SetPlan | None, list[Blocker]]:
    """The answers' `builtins.default` and §4.9e *Blockers*' set cases: an empty list on a home that has a team; a
    login in the list the home would not have, unless a team runs on an ssh node, the list then being taken as names
    there (§4.9d *A team on a node*); a seat's model that no login in the list the home has offers, the prompts seat's
    not read where the org has a director. A seat the answers name that is no built-in seat is refused, named (a
    `manager` key among them: there is no manager after the move). With no answers file, None and nothing."""
    if answers is None:
        return None, []
    if nodes is None:
        from sessionorc import hosts

        nodes = hosts.nodes()
    plans = list(plans)
    row = _under(answers, "builtins", "default")
    out: list[Blocker] = []
    held: dict[str, str] = {}
    raw = row.get("models")
    if raw is not None and not isinstance(raw, Mapping):
        out.append(Blocker(SET, "builtins.default.models is not a mapping of seat to model", "mend it"))
    for key, model in (raw if isinstance(raw, Mapping) else {}).items():
        if key not in builtinstore.SEAT_KEYS:
            gone = ": there is no manager after the move (design §4.9d)" if key == "manager" else ""
            out.append(
                Blocker(
                    SET,
                    f"builtins.default.models names {key!r}, which is not a built-in seat{gone}",
                    f"take it out; the seats are {', '.join(builtinstore.SEAT_KEYS)}",
                )
            )
        elif not isinstance(model, str) or not builtinstore._MODEL.fullmatch(model):
            out.append(Blocker(SET, f"builtins.default.models.{key} is not a model", "name a model family, or none"))
        else:
            held[str(key)] = model
    plan = SetPlan({k: builtinstore.model({"models": held}, k) for k in builtinstore.SEAT_KEYS}, director=director)
    listed = row.get("logins")
    if isinstance(listed, list) and all(isinstance(x, str) and all(logins.split(x)) for x in listed):
        plan.logins = list(dict.fromkeys(listed))
    elif listed is not None:
        out.append(Blocker(SET, "builtins.default.logins is not a list of <tool>:<name>", "mend it"))
    if not plan.logins:
        if plans and (listed is None or listed == []):  # a list that is not one is its own blocker
            out.append(Blocker(SET, "its login list is empty", "list a login in builtins.default.logins"))
        return plan, out
    rows = {lg.key: {"models": lg.models, "pin": lg.pin} for lg in made}
    ssh = sorted(
        {
            p.host
            for p in plans
            if p.host != here and not (isinstance(nodes.get(p.host), Mapping) and nodes[p.host].get("container"))
        }
    )
    elsewhere = [lk for lk in plan.logins if lk not in rows]
    if ssh and elsewhere:
        plan.note = f"not checked: {', '.join(elsewhere)}, taken as names on {', '.join(ssh)}, nor the seats' models"
        return plan, out  # what an unread login offers is not known here, so no seat's model is judged
    else:
        out += [
            Blocker(SET, f"lists {lk}, a login {here} would not have", "take it out of builtins.default.logins")
            for lk in elsewhere
        ]
    known = [lk for lk in plan.logins if lk in rows]
    for key, _shown, words, _does, _for in builtinstore.SEATS:
        if director and key == builtinstore.PROMPTS:
            continue
        model = plan.models[key]
        if known and not any(teamstore.offers(rows[lk], model) for lk in known):
            out.append(
                Blocker(
                    SET,
                    f"no login in its list offers {model}, the model of {words}",
                    f"list a login that offers {model}, or give builtins.default.models.{key} another model",
                )
            )
    return plan, out


def set_lines(plan: SetPlan) -> list[str]:
    """`ao switch-over check`'s lines for the built-in set."""
    seats = ", ".join(
        f"{key} {plan.models[key]}"
        for key in builtinstore.SEAT_KEYS
        if not (plan.director and key == builtinstore.PROMPTS)
    )
    lines = ["the built-in set the answers give", f"  default: {seats}; logins {', '.join(plan.logins) or 'none'}"]
    if plan.director:
        lines.append("    the director answers prompts: no prompts seat is written")
    if plan.note:
        lines.append(f"    {plan.note}")
    return lines


@dataclass
class DirectorPlan:
    """The director the answers give (§4.9e *The answers file*, `director:`), beside what `--answers` would suggest:
    the set's prompts model, the seat that stands in for it, and the login made from the profile the director
    launches on today (`profile`; its role's precedence, the profiles file's default, where `org.yml` names none).
    `given` is False where the answers have no `director:`."""

    suggest_model: str
    suggest_login: str | None
    profile: str | None
    given: bool = False
    model: str | None = None
    logins: list[str] = field(default_factory=list)


DIRECTOR = "the director"  # a director blocker's `where`


def director(
    answers: Mapping[str, Any] | None,
    made: Iterable[Login],
    builtins: SetPlan | None,
    profile: str | None,
) -> tuple[DirectorPlan | None, list[Blocker]]:
    """The answers' `director:` for an org that has a director, and §4.9e *Blockers*' director cases: no entry, a
    model that is none, an empty list, a login the home would not have, a model no login in its list offers, a list
    whose every login leaves its prompts on (§4.9d *How each one runs*: nothing above it would answer them). The
    director runs on the home, so its list is read against the home's logins alone. With no answers file, None and
    nothing: the file's own blocker says so."""
    if answers is None:
        return None, []
    made = list(made)
    model = (builtins.models if builtins is not None else {}).get(builtinstore.PROMPTS) or builtinstore.model(
        {}, builtinstore.PROMPTS
    )
    login = next((lg.key for lg in made if profile is not None and profile in lg.profiles), None)
    plan = DirectorPlan(model, login, profile)
    shape = f"director: {{model: {model}, logins: [{login or '<tool>:<name>'}]}}"
    row = answers.get("director")
    if row is None:
        return plan, [Blocker(DIRECTOR, "the org has a director and the answers give it none", f"write {shape}")]
    plan.given = True
    if not isinstance(row, Mapping):  # `read_answers` refuses it; a caller with its own mapping meets it here
        return plan, [Blocker(DIRECTOR, "director is not a mapping", f"write {shape}")]
    out: list[Blocker] = []
    given = row.get("model")
    if isinstance(given, str) and builtinstore._MODEL.fullmatch(given):
        plan.model = given
    else:
        what = "has no model" if given is None else "director.model is not a model"
        out.append(Blocker(DIRECTOR, what, f"give director.model a model family: {model} stands in for it today"))
    listed = row.get("logins")
    if isinstance(listed, list) and all(isinstance(x, str) and all(logins.split(x)) for x in listed):
        plan.logins = list(dict.fromkeys(listed))
    elif listed is not None:
        out.append(Blocker(DIRECTOR, "director.logins is not a list of <tool>:<name>", "mend it"))
        return plan, out
    if not plan.logins:
        out.append(Blocker(DIRECTOR, "its login list is empty", f"list a login in director.logins: {shape}"))
        return plan, out
    rows = {lg.key: {"models": lg.models, "pin": lg.pin} for lg in made}
    out += [
        Blocker(DIRECTOR, f"lists {lk}, a login the home would not have", "take it out of director.logins")
        for lk in plan.logins
        if lk not in rows
    ]
    known = [lk for lk in plan.logins if lk in rows]
    if plan.model and known and not any(teamstore.offers(rows[lk], plan.model) for lk in known):
        out.append(
            Blocker(
                DIRECTOR,
                f"no login in its list offers {plan.model}, its model",
                "list a login that offers it, or give director.model another model",
            )
        )
    asks = {lk: next(lg.asks for lg in made if lg.key == lk) for lk in known}
    if known and all(asks.values()):
        out.append(
            Blocker(
                DIRECTOR,
                f"every login in its list leaves its prompts on ({', '.join(known)})",
                "list a login whose unattended_args skip them, or give its profiles unattended_args that do",
            )
        )
    return plan, out


def director_lines(plan: DirectorPlan) -> list[str]:
    """`ao switch-over check`'s lines for the director: what the answers give, and what `--answers` suggests."""
    on = f" (from profile {plan.profile})" if plan.profile else ""
    suggest = f"suggested: model {plan.suggest_model}, login {plan.suggest_login or 'none the home would make'}{on}"
    if not plan.given:
        return ["the director the answers give", f"  none; {suggest}"]
    listed = ", ".join(plan.logins) or "none"
    return ["the director the answers give", f"  model {plan.model or 'none'}; logins {listed}", f"    {suggest}"]


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
        if p.lacks:
            lines.append(f"    seats it runs today that {p.flow} lacks, which go: {', '.join(p.lacks)}")
        if p.note:
            lines.append(f"    {p.note}")
    if not plans:
        lines.append("  none: the org defines no team")
    return lines


def report(
    host: str,
    made: Iterable[Login],
    blockers: Iterable[Blocker],
    plans: Iterable[TeamPlan] | None = None,
    builtins: SetPlan | None = None,
    director: DirectorPlan | None = None,
    flights: Iterable[Flight] | None = None,
    asks: Iterable[FirstShapeAsk] | None = None,
) -> list[str]:
    """`ao switch-over check`'s lines: the host's logins, the teams where `plans` is given, the built-in set where
    `builtins` is, the director where `director` is, then every blocker, those of the day last."""
    lines = [f"{host}: logins the move would make"]
    made = list(made)
    for login in made:
        pin = f", pinned to {login.pin}" if login.pin else ""
        lines.append(f"  {login.tool}:{login.name}  {shown(login.folder)}  from {', '.join(login.profiles)}{pin}")
    if not made:
        lines.append("  none: no profile here names a registered tool")
    if plans is not None:
        lines += team_lines(plans)
    if builtins is not None:
        lines += set_lines(builtins)
    if director is not None:
        lines += director_lines(director)
    if flights is not None:
        lines += flight_lines(flights)
    if asks is not None:
        lines += ask_lines(asks)
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


# What `--answers` suggests (§4.9e *The answers file*): `td` becomes `design-wise` (TD-2075); every other flow keeps
# its name, where a format-3 flow of that name is offered.
RENAMED = {"td": "design-wise"}


def _profiles_ran_on(org: Any, team: Any, here: str, default: str | None) -> list[str]:
    """The profiles `team`'s members and seats run on today, the members' first: the start's own reading
    (`teams.plan`, the role's precedence), else, where the start cannot be read here (a checkout this host lacks),
    an approximation: each line's own `profile`, then the profiles file's default, a role's `profile:` not read."""
    from shiftlead import teams as teamsmod

    try:
        p = teamsmod.plan(org, team.name, here)
    except Exception:  # noqa: BLE001 — a team the start would refuse is still suggested from its own lines
        lines = [*team.members, *([team.techlead] if team.techlead is not None else []), *team.seats]
        got = [x.profile or default for x in lines]
    else:
        seats = [*([p.techlead] if p.techlead is not None else []), *p.seats]
        got = [x.profile or default for x in (*p.members, *seats)]
    return list(dict.fromkeys(g for g in got if g))


def _build_role(team: Any) -> str:
    """The role of the stage that builds in the flow the team runs today (the stage named `build`), else `grinder`.
    A flow of the repo's own is not read here (no checkout is), so it too gives `grinder`."""
    from shiftlead import flowdefs
    from shiftlead import teams as teamsmod

    name = teamsmod.current_flow(team)
    try:
        flow = flowdefs.find(name) if name else None
    except Exception:  # noqa: BLE001 — a flow that cannot be read names no build stage
        flow = None
    stage = next((s for s in (flow.stages if flow is not None else ()) if s.name.lower() == "build"), None)
    return stage.role if stage is not None else "grinder"


def suggest(
    org: Any,
    here: str,
    made: Iterable[Login],
    roots: Iterable[str | Path],
    *,
    default: str | None,
    schedules: Mapping[str, Mapping[str, Any]] | None = None,
    offered: Callable[[str], list[Mapping[str, Any]]] | None = None,
    ran_on: Callable[[Any], list[str]] | None = None,
    lacks: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """The answers file `--answers` writes where there is none (§4.9e *The answers file*): each folder named for its
    first profile; each team the format-3 flow of the name its flow has today (`design-wise` for `td`), the logins
    made from the profiles its members and seats run on, the members' first, `at_once` for the stage that takes
    ready-to-build entries the sum of today's builder lines' sizes, and a `schedule_login` where its schedule names a
    profile; the set the package's models and the first home team's logins; the director, where `org` has one, the
    package's prompts model and the login made from its profile. A team on a node is given no logins: its host's are
    not read here. `schedules` is `settings.teams`' reading; `offered` and `ran_on` stand in for the home's readings.
    `lacks`, where given, gains each team the seats it runs today that its suggested flow lacks (`lacking`)."""
    from shiftlead import flow3, team_show
    from shiftlead import teams as teamsmod

    made = list(made)
    where_roots = list(roots)
    offered = offered or (lambda repo: team_show.offered(repo, where_roots))
    schedules = schedules or {}

    def login_of(profile: str | None) -> str | None:
        return next((lg.key for lg in made if profile is not None and profile in lg.profiles), None)

    doc: dict[str, Any] = {"hosts": {here: {"logins": {lg.found: {"name": lg.name} for lg in made}}}, "teams": {}}
    first: list[str] | None = None
    for name, team in org.teams.items():
        if name in getattr(org, "unlanded", {}):
            continue
        pick: dict[str, Any] = {}
        today = teamsmod.current_flow(team)
        want = RENAMED.get(today or "", today)
        row = next((r for r in offered(team.repo) if want and r["name"] == want), None)
        if row is not None:
            pick["flow"] = want
            if lacks is not None and (gone := lacking(team, row.get("doc"))):
                lacks[name] = gone
        on_home = not team.host or team.host == here
        listed: list[str] = []
        if on_home:
            profs = ran_on(team) if ran_on is not None else _profiles_ran_on(org, team, here, default)
            listed = list(dict.fromkeys(lk for p in profs if (lk := login_of(p)) is not None))
            if first is None:
                first = listed
        pick["logins"] = listed
        builds = _build_role(team)
        builders = sum(m.size if m.size is not None else m.count for m in team.members if m.role == builds)
        stages = row["doc"].get("stages") if row is not None and isinstance(row.get("doc"), Mapping) else None
        # the stage that takes ready-to-build entries: `takes: other`, else `any` (§4.9d)
        staged = [s for s in stages or () if isinstance(s, Mapping)]
        takes = next((s for want_ in ("other", "any") for s in staged if s.get("takes") == want_), None)
        if takes is not None and builders >= 1:
            pick["at_once"] = {flow3.key_of(takes.get("name")): builders}
        profile = _under(schedules, name, "schedule").get("profile")
        if isinstance(profile, str) and (lk := login_of(profile)) is not None:
            pick["schedule_login"] = lk
        doc["teams"][name] = pick
    seats = [k for k in builtinstore.SEAT_KEYS if not (org.director is not None and k == builtinstore.PROMPTS)]
    doc["builtins"] = {
        "default": {"models": {k: builtinstore.model({}, k) for k in seats}, "logins": list(first or [])}
    }
    if org.director is not None:
        lk = login_of(org.director.profile or default)
        doc["director"] = {"model": builtinstore.model({}, builtinstore.PROMPTS), "logins": [lk] if lk else []}
    return doc


def write_answers(
    doc: Mapping[str, Any], path: Path | None = None, lacks: Mapping[str, Iterable[str]] | None = None
) -> bool:
    """Write `doc` as the answers file where there is none; False, and nothing written, where there is one (a
    dangling link included). The file is linked into place, so one written meanwhile is never replaced. `lacks`
    (`suggest`'s) is written in the head, a comment line a team: the seats it runs today that its flow lacks."""
    path = path or answers_file()
    if path.exists() or path.is_symlink():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    head = "# written by ao switch-over check --answers (design §4.9e The answers file): read it, change it, check\n"
    rows = [(t, list(seats)) for t, seats in (lacks or {}).items()]
    if any(seats for _t, seats in rows):
        head += "# seats each team runs today that its suggested flow lacks, which go (their logins are still made):\n"
        head += "".join(f"#   {t}: {', '.join(seats)}\n" for t, seats in rows if seats)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(head + yaml.safe_dump(dict(doc), sort_keys=False, allow_unicode=True), encoding="utf-8")
        os.link(tmp, path)
    except FileExistsError:
        return False
    finally:
        tmp.unlink(missing_ok=True)
    return True


@dataclass
class Flight:
    """One repo's work in flight as the home will take it up after the window (§4.9e *Work in flight*): the entries
    taken up with their pull requests, those that wait, those whose pull request is not read at its head yet, and the
    branches nothing will read. `unread` says why the repo's pull requests were not read; the repo is then no
    blocker, and nothing else is listed."""

    repo: str
    taken: list[tuple[str, int, str]] = field(default_factory=list)  # (entry, pull request, branch)
    waits: list[tuple[str, str]] = field(default_factory=list)  # (entry, why)
    unknown: list[tuple[str, str]] = field(default_factory=list)  # (entry, why): its PR's files not read at its head
    nobodys: list[tuple[str, str]] = field(default_factory=list)  # (branch, why)
    unread: str | None = None
    branches_unread: bool = False  # origin's branches could not be read, so no pushed branch is named
    at: str | None = None  # when the home read the repo's pull requests


def in_flight(
    readings: Mapping[str, Mapping[str, Any]],
    org: Any,
    *,
    branches_of: Callable[[str], frozenset[str] | None] | None = None,
) -> list[Flight]:
    """Each repo of `org`'s teams, from the home's last repo reading (`readings`, `repos.json` by checkout), with what
    `stage_work.entry_work` — the Offer act's own function — gives each entry a team's lane may pick, every session
    the window ends taken as gone (no pull request is held). A branch of a pull request that may be work
    (`stage_work.may_be_work`) holding two entries' ids is nobody's work, and a pushed branch holding the id of an
    entry of the reading, with no open pull request of the repo's own, is read by nothing (`branches_of`, origin's
    branches by `git ls-remote`; None, not read). A person's own session's hold is not read here."""
    from shiftlead import stage_fetch, stage_read, stage_work

    branches_of = branches_of or stage_fetch.pushed_branches
    by_repo: dict[str, list[str]] = {}
    for name in sorted(org.teams):
        if name not in getattr(org, "unlanded", {}):
            by_repo.setdefault(str(org.teams[name].repo), []).append(name)
    out: list[Flight] = []
    for repo, names in sorted(by_repo.items()):
        flight = Flight(repo)
        out.append(flight)
        root, reading = next(((k, v) for k, v in readings.items() if isinstance(v, Mapping) and v.get("name") == repo),
                             (None, None))  # fmt: skip
        prs = reading.get("prs") if reading is not None else None
        if not isinstance(prs, Mapping) or "error" in prs or not isinstance(prs.get("open"), list):
            error = prs.get("error") if isinstance(prs, Mapping) else None
            flight.unread = (
                "the home has not read its pull requests"
                if reading is None or prs is None
                else f"its pull requests could not be read: {error}"
                if error
                else "its pull request reading holds no open list"
            )
            continue
        flight.at = str(prs["at"]) if prs.get("at") else None
        rows = [r for r in prs["open"] if isinstance(r, Mapping)]
        entries = (reading.get("ledger") or {}).get("entries") or []
        for e in entries:
            tid = str(e.get("id") or "")
            if not tid or not any(stage_read.pickable_on(dict(e), team) for team in names):
                continue
            work = stage_work.entry_work(tid, rows)
            if work.state == "take" and work.pr is not None:
                flight.taken.append((tid, int(work.pr["number"]), str(work.pr.get("branch") or "")))
            elif work.state == "wait":
                flight.waits.append((tid, work.why))
            elif work.state == "unread":
                flight.unknown.append((tid, work.why))
        for r in rows:
            ids = stage_work.branch_ids(r.get("branch"))
            if len(ids) > 1 and stage_work.may_be_work(r):
                flight.nobodys.append((str(r["branch"]), f"#{r.get('number')} holds {', '.join(sorted(ids))}"))
        pushed = branches_of(root) if root is not None and Path(root).is_dir() else None
        if pushed is None:
            flight.branches_unread = True
            continue
        known = {str(e.get("id")) for e in entries if e.get("id")}
        with_pr = {str(r.get("branch")) for r in rows if not r.get("fork")}
        for b in sorted(pushed - with_pr):
            ids = stage_work.branch_ids(b) & known
            if ids:
                flight.nobodys.append((b, f"holds {', '.join(sorted(ids))} and has no open pull request"))
    return out


def flight_lines(flights: Iterable[Flight]) -> list[str]:
    """`ao switch-over check`'s lines for the work in flight (§4.9e *Work in flight*)."""
    lines = ["work in flight, as the home will take it up after the window"]
    flights = list(flights)
    for f in flights:
        if f.unread is not None:
            lines.append(f"  {f.repo}: not read — {f.unread}")
            continue
        lines.append(f"  {f.repo}:{f' (its pull requests read {f.at})' if f.at else ''}")
        lines += [f"    taken up with its pull request: {tid} #{n} ({b})" for tid, n, b in f.taken]
        lines += [f"    waits, offered to nobody: {tid} — {why}" for tid, why in f.waits]
        lines += [f"    not yet known: {tid} — {why}" for tid, why in f.unknown]
        lines += [f"    nothing will read: {b} — {why}" for b, why in f.nobodys]
        if f.branches_unread:
            lines.append("    origin's branches could not be read, so no pushed branch is named")
        if not (f.taken or f.waits or f.unknown or f.nobodys or f.branches_unread):
            lines.append("    nothing in flight: every pickable entry is offered afresh")
    if not flights:
        lines.append("  none: the org defines no team")
    return lines


# -- open asks to the first shape (§4.9e *Work in flight*) ------------------------------------------------------------


@dataclass(frozen=True)
class FirstShapeAsk:
    """An open ask in the mailbox of a member or seat of the first shape, which nothing answers after the window."""

    id: str
    to: str
    sender: str
    subject: str
    at: str


def stored_records(root: Path | None = None) -> dict[str, Session]:
    """The home's stored session records, read and never written (no directory is made where there is none)."""
    root = root or paths.sessions_dir()
    out: dict[str, Session] = {}
    for p in sorted(root.glob("*.json")) if root.is_dir() else ():
        try:
            s = Session.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue  # a half-written or foreign file is passed over, as the store passes it
        out[s.id] = s
    return out


def first_shape(r: Session) -> bool:
    """A member or seat of the first shape (§4.9e *What decides which shape runs*, rule 13): a record with a `team`,
    no `builtin`, and not the person's own (`mail.by_person`). Every stored record was made before the cut-over."""
    return bool(r.team) and not r.builtin and not mail.by_person(r)


def first_shape_asks(records: Mapping[str, Session]) -> list[FirstShapeAsk]:
    """Each open ask to a member or seat of the first shape, in the order the records hold them (§4.9e *Work in
    flight*: for the person to answer or close before the window), the person's own and one passed up to the person
    left out, as `stuck.open_asks` leaves them out, and once per id (a handed entry may sit in two mailboxes)."""
    seen: set[str] = set()
    out: list[FirstShapeAsk] = []
    for key, r in records.items():
        if not first_shape(r):
            continue
        for e in r.inbox:
            if e.id in seen or e.kind != "ask" or not e.open or e.passed_to == mail.PERSON or mail.PERSON in e.to:
                continue
            seen.add(e.id)
            out.append(FirstShapeAsk(e.id, r.id or key, e.from_, mail.heading(e), e.at))
    return out


def ask_lines(asks: Iterable[FirstShapeAsk]) -> list[str]:
    """`ao switch-over check`'s lines for the open asks to the first shape."""
    asks = list(asks)
    lines = ["open asks to a member or seat of the first shape, to answer or close before the window"]
    lines += [f"  {a.id} to {a.to} from {a.sender} ({a.at}): {a.subject}" for a in asks]
    if not asks:
        lines.append("  none")
    return lines
