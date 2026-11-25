"""A session started for one run of an audit, and what it is told (design §4.9c *Audits start on a clock*, act 6,
TD-2053).

An audit's session is a stage's session in all but its work (`stage_start`): the same mechanics and the same `ao stage
end`, the repo's rules, and the audit's brief with its `also` (`stage_start.brief_for`: `docs`, `tests`, `code`, or one
of the person's own). It runs in the `auditor` role (§4.8) on the audit's own `model`, from the team's checkout on the
team's host, with its lease as its one lane (`audit:<team>/<audit>`, `stage_audit.lease_ref`), and names no
`controllers`. Its outcomes are `findings-filed`, `nothing-found` and `other`. Nothing calls `launch` until an audit's
start is wired into the tick, and `stage_start.start` starts nothing before the team's started mark (TD-2065).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shiftlead import flow3, repoconfig, teams
from shiftlead import org as orgmod
from shiftlead.stage_audit import lease_ref
from shiftlead.stage_start import StageLaunch, brief_for

AUDIT_TEMPLATE = Path(__file__).resolve().parent / "briefs" / "audit.md"
ROLE = "auditor"


def audit_of(doc: Mapping[str, Any], name: str) -> dict[str, Any]:
    """The audit of `doc` named `name`, by its key."""
    for a in doc.get("audits") or []:
        if isinstance(a, Mapping) and flow3.key_of(a.get("name")) == flow3.key_of(name):
            return dict(a)
    raise teams.TeamError(f"this flow has no audit {name!r}")


def name_of(team: str, audit: Mapping[str, Any]) -> str:
    """The session's name, which no stage's or job's takes: `audit-<team>-<audit's key>`."""
    return f"audit-{flow3.key_of(team)}-{flow3.key_of(audit.get('name'))}"


def told(audit: Mapping[str, Any], *, team: str, base: str | None, came: str | None = None) -> str:
    """How the run is taken and ended: the `{flow}` of its session's prompt."""
    lines = [
        f"You hold one run of the audit **{audit['name']}** of team {team}, every {audit['every']}.",
        "You look where your brief says, file each problem you find as an entry of its own (its id from "
        "`ao td reserve`, filed with `ledger.py new` in a pull request of ledger files alone), and fix nothing.",
    ]
    if base:
        lines.append(f"The run counts from `{base[:12]}`, the default branch's head when it started.")
    if came:
        lines.append(f"It came back to you because the run's last session was {came}.")
    lines.append(
        f'A question goes to your team\'s tech lead: `ao msg --kind ask --team {team} "…"`. Nobody controls you.'
    )
    lines.append(
        '\nEnd the run with one command, run in your worktree: **`ao stage end <outcome> [--reason "…"]`**. Until you '
        "run it you are working. The home checks each outcome's fact and refuses one the facts contradict, saying "
        "which, and you carry on. The outcomes, and what each is checked on:"
    )
    lines.append(
        "- `findings-filed`: `--reason` names each entry you filed in this run (`TD-n`, …), at least one, and each "
        "was filed in it."
    )
    lines.append("- `nothing-found`: `--reason` says where you looked.")
    lines.append(
        "- `other`: a reason is given, and the home puts one plain line on the board naming the audit and the run; "
        "the last choice."
    )
    return "\n".join(lines)


def launch(
    org: orgmod.Org,
    team: orgmod.TeamDef,
    doc: dict[str, Any],
    name: str,
    *,
    host: str,
    here: str,
    base: str | None = None,
    came: str | None = None,
    place: str = "package",
    flow_dir: Path | None = None,
    files: teams.Files | None = None,
) -> StageLaunch:
    """The run's session, nothing created: in the auditor role, on the audit's model, its lane the run's lease."""
    audit = audit_of(doc, name)
    lane, session = lease_ref(team.name, flow3.key_of(audit["name"])), name_of(team.name, audit)
    where = f"team {team.name}: {session}"
    checkout, read = teams._checkout(org, team, team.repo, host, here, files, where)
    try:
        cfg = repoconfig.load(checkout, read=read)
        cfg.venv = teams.node_venv(host, here)
        role = repoconfig.resolve_role(cfg, ROLE, org.roles)
    except (KeyError, ValueError, OSError) as e:
        raise teams.TeamError(f"{where}: {str(e).strip(chr(34))}") from None
    line = next((m for m in team.members if m.role == role.name), None)
    person, unlisted = teams._person(org, team.repo, role, here, where)
    under = repoconfig.UnderFlow(
        told(audit, team=team.name, base=base, came=came), brief=brief_for(audit, place, flow_dir, read)
    )
    try:
        prompt, made = role.compose(
            [lane],
            read=read,
            supplement=line.brief if line is not None and line.brief else None,
            flow=under,
            template_file=AUDIT_TEMPLATE,
            person=person,
        )
    except ValueError as e:
        raise teams.TeamError(f"{where}: {e}") from None
    # no member's or role's profile: as a job's, a run starts on the package's default adapter until a login is
    # chosen for it (TD-2068), never a shell
    x = teams.Launch(
        name=session,
        role=role.name,
        home=team.repo,
        dir=checkout,
        team=team.name,
        project=org.project_of(team.repo),
        prompt=prompt,
        grants=list(role.grants),
        lane=[lane],
        ledger=cfg.ledger,
        host=host if host != here else "",
        context_bound=role.context_bound,
        prompt_from=made,
        unlisted=unlisted,
    )
    return StageLaunch(x, str(audit["model"]))
