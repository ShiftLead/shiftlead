"""The built-in seats' records the home writes after the cut-over (design §4.9d *How each one runs*, TD-2065).

A seat is a record at a fixed name that holds the seat's mail and is closed while nothing is due; §6 rule 3 fills it
with a fresh session. After the cut-over no first-shape Start is left to write one, so the home's stage pass writes it:
where a switched team is started and no current record carries `builtin: techlead` for it, it writes
`techlead-<team>`, closed (`held`), with `seat: {trigger: asks, tags: true}`, unattended and supervised, and the launch
a fill replays: the `techlead` role with its brief from the package and the repo's supplement, the repo's registered
checkout on the team's host in a worktree of the seat's own name, the role's grants and no `controllers`. A first-shape
record that holds the very name is superseded by it, its mail kept.

The sweeper's record is the repo's, not a team's: `sweeper-<repo>`, written where a team of the repo is started, the
Settings sweep switch is on and the repo's own switch is not off, with `seat: {trigger: swept, after: <sweep.every>,
by: settings}` and no `team`, on the host of the first, by name, of the repo's started teams (*Where a seat's session
launches*).

The prompts seat's record is the repo's too: `prompts-<repo>`, written where a team of the repo is started and the org
has no director, with `seat: {trigger: prompt}`, no `team` and the director seat's `permit`, on the same host. Its brief
is the package's director brief with the Org block's place naming the repo instead: it answers that repo's prompts.

Launching a fill on the built-in set's model and login is TD-2068's; a record moved to a new host is a later slice of
TD-2065.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import Any

from sessionorc import brief as brief_mod
from sessionorc.models import Session
from shiftlead import org as orgmod
from shiftlead import repoconfig, stage_start, teams

log = logging.getLogger(__name__)

TECHLEAD = "techlead"  # the seat key, `builtinstore`'s, and the role the seat runs in
TECHLEAD_SEAT = {"trigger": "asks", "tags": True}
SWEEPER = teams.SWEEPER  # the sweeper's seat key and role
PROMPTS = "prompts"  # the prompts seat's key, `builtinstore`'s; it runs in the director seat's role


def techlead_name(team: str) -> str:
    """The tech lead's record name: `techlead-<team>`."""
    return f"{TECHLEAD}-{team}"


def techlead_of(graph: Mapping[str, Session], team: str) -> Session | None:
    """The team's current built-in tech lead record, or None: one marked `builtin: techlead` for `team` and superseded
    by none. A first-shape seat, whatever its name, is never one (§4.9d)."""
    for s in graph.values():
        if s.builtin == TECHLEAD and s.team == team and not s.superseded_by:
            return s
    return None


def sweeper_name(repo: str) -> str:
    """The sweeper's record name: `sweeper-<repo>`."""
    return f"{SWEEPER}-{repo}"


def sweeper_of(graph: Mapping[str, Session], repo: str) -> Session | None:
    """The repo's current built-in sweeper record, or None: `sweeper-<repo>` marked `builtin: sweeper` and superseded
    by none. A first-shape `sweep-<team>` is never one (§4.9d)."""
    name = sweeper_name(repo)
    for s in graph.values():
        if s.builtin == SWEEPER and s.name == name and not s.superseded_by:
            return s
    return None


def prompts_name(repo: str) -> str:
    """The prompts seat's record name: `prompts-<repo>`."""
    return f"{PROMPTS}-{repo}"


def prompts_of(graph: Mapping[str, Session], repo: str) -> Session | None:
    """The repo's current built-in prompts seat record, or None: `prompts-<repo>` marked `builtin: prompts` and
    superseded by none. The director's record carries no `builtin` and is never one (§4.9d)."""
    name = prompts_name(repo)
    for s in graph.values():
        if s.builtin == PROMPTS and s.name == name and not s.superseded_by:
            return s
    return None


def prompts_paragraph(repo: str, checkout: str) -> str:
    """What stands in the director brief's Org block for a repo's prompts seat: the one repo it answers for."""
    return (
        "## Your repo\n\n"
        f"You are **{repo}'s prompts seat** (`{prompts_name(repo)}`), not the org's director: the org has no director, "
        f"so you answer the permission prompts of {repo}'s unattended sessions alone — its teams' and its built-in "
        f"seats' — whose checkout is `{checkout}`. Where this brief says the org or any unattended session, read "
        f"{repo}'s: the home refuses your `ao allow` or `ao deny` on a session of another repo."
    )


def prompts_launch(org: orgmod.Org, team: orgmod.TeamDef, *, host: str, here: str) -> teams.Launch:
    """The repo's prompts seat's launch, nothing created: the director seat's role on the checkout of `team`'s repo on
    `host` (the first of its started teams by name), the repo's record and no team's, a seat on `prompt` holding the
    director's `permit`, its brief the package's director brief with the Org block's place naming the repo (§4.9d)."""
    name = prompts_name(team.repo)
    where = f"team {team.name}: {name}"
    checkout, _read = teams._checkout(org, team, team.repo, host, here, None, where)
    base = Path(orgmod.__file__).parent / "briefs" / "director.md"
    prompt_from = {"base": str(base), "slots": {"{org}": {"text": prompts_paragraph(team.repo, str(checkout))}}}
    try:
        prompt = brief_mod.fill(prompt_from, merged=False)[0]
    except brief_mod.Unreadable as e:
        raise teams.TeamError(f"{where}: its brief cannot be read ({e})") from None
    return teams.Launch(
        name=name,
        role=teams.DIRECTOR_ROLE,
        home=team.repo,
        dir=checkout,
        team="",
        project=org.project_of(team.repo),
        prompt=prompt,
        grants=[orgmod.DIRECTOR_GRANT],
        lane=[],
        seat=True,
        trigger={"trigger": orgmod.DIRECTOR_TRIGGER},
        host=host if host != here else "",
        prompt_from=prompt_from,
    )


def techlead_launch(org: orgmod.Org, team: orgmod.TeamDef, *, host: str, here: str) -> teams.Launch:
    """The tech lead's launch, nothing created: the `techlead` role on the repo's checkout on `host`, its brief the
    package's with the repo's supplement, its grants the role's, a seat on `asks` that tags (§4.9d)."""
    return _launch(
        org,
        team,
        techlead_name(team.name),
        TECHLEAD,
        {"trigger": TECHLEAD_SEAT["trigger"]},
        True,
        team.name,
        host,
        here,
    )


def sweeper_launch(org: orgmod.Org, team: orgmod.TeamDef, every: str, *, host: str, here: str) -> teams.Launch:
    """The repo's sweeper's launch, nothing created: the `sweeper` role on the checkout of `team`'s repo on `host` (the
    first of its started teams by name), the repo's record and no team's, a seat on `swept: <every>` made by the
    Settings switch (§4.9d)."""
    trigger = {"trigger": "swept", "after": every, "by": "settings"}
    return _launch(org, team, sweeper_name(team.repo), SWEEPER, trigger, False, "", host, here)


def _launch(
    org: orgmod.Org,
    team: orgmod.TeamDef,
    name: str,
    key: str,
    trigger: dict[str, Any],
    tags: bool,
    of_team: str,
    host: str,
    here: str,
) -> teams.Launch:
    """A built-in seat's launch: role `key` on the checkout of `team`'s repo on `host`, its brief the package's with the
    repo's supplement, its grants the role's, no lane; `of_team` the record's team, "" for a repo's seat."""
    where = f"team {team.name}: {name}"
    checkout, read = teams._checkout(org, team, team.repo, host, here, None, where)
    try:
        cfg = repoconfig.load(checkout, read=read)
        cfg.venv = teams.node_venv(host, here)
        role = repoconfig.resolve_role(cfg, key, org.roles)
    except (KeyError, ValueError, OSError) as e:
        raise teams.TeamError(f"{where}: {str(e).strip(chr(34))}") from None
    person, unlisted = teams._person(org, team.repo, role, here, where)
    try:
        prompt, made = role.compose([], read=read, person=person)
    except ValueError as e:
        raise teams.TeamError(f"{where}: {e}") from None
    return teams.Launch(
        name=name,
        role=role.name,
        home=team.repo,
        dir=checkout,
        team=of_team,
        project=org.project_of(team.repo),
        prompt=prompt,
        grants=list(role.grants),
        lane=[],
        seat=True,
        trigger=trigger,
        tags=tags,
        ledger=cfg.ledger,
        host=host if host != here else "",
        context_bound=role.context_bound,
        prompt_from=made,
        unlisted=unlisted,
    )


def create_params(x: teams.Launch, *, keep_mail: bool = False, builtin: str = TECHLEAD) -> dict[str, Any]:
    """The `create` RPC's arguments for a built-in seat's record: the launch's, held (closed, for rule 3 to fill),
    marked `builtin` with its seat key, with no controllers; with `keep_mail`, the mail of the record it supersedes
    moves to it."""
    return {**x.create_params([]), "held": True, "builtin": builtin, **({"keep_mail": True} if keep_mail else {})}


def write_techleads(
    call: Callable[..., Any],
    org: orgmod.Org | None,
    teams_cfg: Mapping[str, Mapping[str, Any]],
    graph: Mapping[str, Session],
    host_teams: Mapping[str, Any] | None,
    local: str,
) -> list[str]:
    """Write the record of each started team in `teams_cfg` that has no current built-in tech lead (`techlead_of`),
    and return the ids written. A team the org does not hold, a launch that cannot be made, a name a live session
    holds, or a refused create writes nothing this pass and is a log line; the next pass tries again."""
    if org is None:
        return []
    made: list[str] = []
    for team in sorted(teams_cfg):
        teamdef = org.teams.get(team)
        if teamdef is None or not stage_start.team_started(host_teams, team) or techlead_of(graph, team) is not None:
            continue
        entry = teams_cfg.get(team) or {}
        host = str(entry.get("host") or local)
        if got := _write(call, partial(techlead_launch, org, teamdef, host=host, here=local), TECHLEAD, f"team {team}"):
            made.append(got)
    return made


def write_sweepers(
    call: Callable[..., Any],
    org: orgmod.Org | None,
    teams_cfg: Mapping[str, Mapping[str, Any]],
    graph: Mapping[str, Session],
    host_teams: Mapping[str, Any] | None,
    local: str,
    switch: Mapping[str, Any] | None,
) -> list[str]:
    """Write the record of each repo of a started team in `teams_cfg` that has no current built-in sweeper
    (`sweeper_of`), while the sweep switch (`sweep_switch`'s answer) is on and the repo is not among its `off`, and
    return the ids written. The record is made from, and on the host of, the first of the repo's started teams by name
    (§4.9d *Where a seat's session launches*). As for a tech lead, what cannot be written this pass is a log line."""
    if org is None or not switch or switch.get("on") is not True:
        return []
    first = _first_started(org, teams_cfg, host_teams)
    every = str(switch.get("every") or "")
    made: list[str] = []
    for repo, team in sorted(first.items()):
        if repo in (switch.get("off") or ()) or sweeper_of(graph, repo) is not None:
            continue
        teamdef, host = org.teams[team], str((teams_cfg.get(team) or {}).get("host") or local)
        if got := _write(
            call, partial(sweeper_launch, org, teamdef, every, host=host, here=local), SWEEPER, f"repo {repo}"
        ):
            made.append(got)
    return made


def write_prompts(
    call: Callable[..., Any],
    org: orgmod.Org | None,
    teams_cfg: Mapping[str, Mapping[str, Any]],
    graph: Mapping[str, Session],
    host_teams: Mapping[str, Any] | None,
    local: str,
) -> list[str]:
    """Write the record of each repo of a started team in `teams_cfg` that has no current built-in prompts seat
    (`prompts_of`), only where the org has no director (`org.yml`'s `director:`), and return the ids written. The
    record is made from, and on the host of, the first of the repo's started teams by name, as the sweeper's is."""
    if org is None or getattr(org, "director", None) is not None:
        return []
    made: list[str] = []
    for repo, team in sorted(_first_started(org, teams_cfg, host_teams).items()):
        if prompts_of(graph, repo) is not None:
            continue
        teamdef, host = org.teams[team], str((teams_cfg.get(team) or {}).get("host") or local)
        if got := _write(call, partial(prompts_launch, org, teamdef, host=host, here=local), PROMPTS, f"repo {repo}"):
            made.append(got)
    return made


def _first_started(
    org: orgmod.Org, teams_cfg: Mapping[str, Mapping[str, Any]], host_teams: Mapping[str, Any] | None
) -> dict[str, str]:
    """Each repo of a started team in `teams_cfg` → the first, by name, of its started teams."""
    first: dict[str, str] = {}
    for team in sorted(teams_cfg):
        teamdef = org.teams.get(team)
        if teamdef is not None and stage_start.team_started(host_teams, team):
            first.setdefault(teamdef.repo, team)
    return first


def _write(call: Callable[..., Any], launch: Callable[[], teams.Launch], key: str, of: str) -> str:
    """Create one built-in seat's record from `launch()` and return its id, "" where nothing was written: a name a
    live session holds waits for the next pass, a first-shape record of the very name is superseded with its mail kept
    (§4.9d), and a launch that cannot be made or a refused create is a log line."""
    try:
        x = launch()
        on = {"host": x.host} if x.host else {}
        check = call("name_check", dir=str(x.dir), name=x.name, repo=str(x.dir), **on) or {}
        if check.get("verdict") in ("live", "suspended"):
            log.warning("%s: a live session holds %s, so its %s record waits", of, x.name, key)
            return ""
        keep = check.get("verdict") == "supersede" and check.get("holder_state") != "unrecorded"
        got = call("create", **create_params(x, keep_mail=keep, builtin=key))
    except Exception:  # noqa: BLE001 — one record failing is a log line, never another's or the pass
        log.exception("%s: its %s record could not be written", of, key)
        return ""
    return str(got["id"]) if isinstance(got, Mapping) and got.get("id") else ""
