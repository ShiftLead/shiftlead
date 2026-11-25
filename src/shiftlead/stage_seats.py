"""The built-in seats' records the home writes after the cut-over (design §4.9d *How each one runs*, TD-2065).

A seat is a record at a fixed name that holds the seat's mail and is closed while nothing is due; §6 rule 3 fills it
with a fresh session. After the cut-over no first-shape Start is left to write one, so the home's stage pass writes it:
where a switched team is started and no current record carries `builtin: techlead` for it, it writes
`techlead-<team>`, closed (`held`), with `seat: {trigger: asks, tags: true}`, unattended and supervised, and the launch
a fill replays: the `techlead` role with its brief from the package and the repo's supplement, the repo's registered
checkout on the team's host in a worktree of the seat's own name, the role's grants and no `controllers`. A first-shape
record that holds the very name is superseded by it, its mail kept.

Launching a fill on the built-in set's model and login is TD-2068's; the sweeper's and the prompts seat's records, a
record moved to a new host, a held record and Delete's removal are later slices of TD-2065.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from sessionorc.models import Session
from shiftlead import org as orgmod
from shiftlead import repoconfig, stage_start, teams

log = logging.getLogger(__name__)

TECHLEAD = "techlead"  # the seat key, `builtinstore`'s, and the role the seat runs in
TECHLEAD_SEAT = {"trigger": "asks", "tags": True}


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


def techlead_launch(org: orgmod.Org, team: orgmod.TeamDef, *, host: str, here: str) -> teams.Launch:
    """The tech lead's launch, nothing created: the `techlead` role on the repo's checkout on `host`, its brief the
    package's with the repo's supplement, its grants the role's, a seat on `asks` that tags (§4.9d)."""
    name = techlead_name(team.name)
    where = f"team {team.name}: {name}"
    checkout, read = teams._checkout(org, team, team.repo, host, here, None, where)
    try:
        cfg = repoconfig.load(checkout, read=read)
        cfg.venv = teams.node_venv(host, here)
        role = repoconfig.resolve_role(cfg, TECHLEAD, org.roles)
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
        team=team.name,
        project=org.project_of(team.repo),
        prompt=prompt,
        grants=list(role.grants),
        lane=[],
        seat=True,
        trigger={"trigger": TECHLEAD_SEAT["trigger"]},
        tags=True,
        ledger=cfg.ledger,
        host=host if host != here else "",
        context_bound=role.context_bound,
        prompt_from=made,
        unlisted=unlisted,
    )


def create_params(x: teams.Launch, *, keep_mail: bool = False) -> dict[str, Any]:
    """The `create` RPC's arguments for a built-in tech lead's record: the launch's, held (closed, for rule 3 to
    fill), marked `builtin`, with no controllers; with `keep_mail`, the mail of the record it supersedes moves to it."""
    return {**x.create_params([]), "held": True, "builtin": TECHLEAD, **({"keep_mail": True} if keep_mail else {})}


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
        try:
            x = techlead_launch(org, teamdef, host=str(entry.get("host") or local), here=local)
            on = {"host": x.host} if x.host else {}
            check = call("name_check", dir=str(x.dir), name=x.name, repo=str(x.dir), **on) or {}
            if check.get("verdict") in ("live", "suspended"):
                log.warning("team %s: a live session holds %s, so its tech lead's record waits", team, x.name)
                continue
            # a first-shape record of the very name is superseded, its mail kept (§4.9d)
            keep = check.get("verdict") == "supersede" and check.get("holder_state") != "unrecorded"
            got = call("create", **create_params(x, keep_mail=keep))
        except Exception:  # noqa: BLE001 — one team's record failing is a log line, never another's or the pass
            log.exception("team %s: its tech lead's record could not be written", team)
            continue
        if isinstance(got, Mapping) and got.get("id"):
            made.append(str(got["id"]))
    return made
