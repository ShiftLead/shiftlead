"""One repo's stage pass as the tick calls it (design §4.9c *The home acts only where no session will*, TD-2051).

`run` is the shiftlead half of the tick's wiring, reached through the `shiftlead.home_calls` entry point `stage_tick`
because `sessionorc` never imports `shiftlead`. The home passes what only it holds (its graph of sessions, the nodes
whose snapshot has arrived, every node's checkouts of the repo, the repo's pull request reading and ledger rows, its
`host` record's teams) and the switched teams of the repo from `settings.yml`; `run` reads the rest once from the repo
itself (the ledger at origin's default branch, the protected files, each team's flow and its check, the person) and
takes `stage_pass.repo_pass`. What one repo's passes keep between them (`Kept`) is the caller's to hold.

Nothing starts a session yet: `stage_start.team_started` is false until TD-2065, so no offer is made, and a team is
read only after the cut-over, when the caller passes it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from sessionorc import gitinfo, ledger, paths, reports
from sessionorc.models import Session
from shiftlead import flow3, repoconfig, stage_end, stage_merge, stage_pass, stage_start
from shiftlead import org as orgmod
from shiftlead.stage_fetch import TeamFlow, ledger_read, protected_at, sessions_read
from shiftlead.stage_pass import Reach, RepoPass, RepoState
from shiftlead.stagerecord import StageStore

log = logging.getLogger(__name__)


@dataclass
class Kept:
    """What one repo's passes keep from one to the next: `repo_pass`'s own state, and the gate and land, whose gate
    keeps what it passed for the merge that follows it."""

    state: RepoState = field(default_factory=RepoState)
    gate_land: tuple[stage_merge.Gate, stage_merge.Land] | None = None


def flow_file(root: Path | str, name: str) -> tuple[Path, str, Path | None] | None:
    """Where the format-3 flow `name` is: `(its file, its place, the repo root for a repo's)`. A built-in's name is
    resolved in the package (§4.9e *After the cut-over a built-in flow's name is resolved in `shiftlead/flows3/`*),
    then the org's over the repo's (§4.9c *Where flows and roles live*): the first that holds the file is the flow,
    whatever its format, which `flow_now` then refuses where it is not format 3. A name that could leave the flows'
    directory (empty, holding `/`, or starting `.`) is no flow, as `flowdefs.find` reads it. None: not found."""
    if name in flow3.BUILTIN:
        return flow3.PACKAGE_DIR / name / flow3.FILE, "package", None
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    for d, place, repo in (
        (paths.home() / "flows" / name, "org", None),
        (Path(root) / flow3.REPO_DIR / name, "repo", Path(root)),
    ):
        if (d / flow3.FILE).is_file():
            return d / flow3.FILE, place, repo
    return None


def flow_now(root: Path | str, name: Any) -> tuple[str | None, tuple[str, ...]]:
    """`repo_pass`'s `flows` value for a team whose flow is `name`: its text as read now and its check's problems.
    A flow not found, or unreadable, is `(None, why)`, so the team runs its last good copy."""
    if not isinstance(name, str) or not name.strip():
        return None, ("the team names no flow",)
    got = flow_file(root, name)
    if got is None:
        return None, (f"flow {name} is not found",)
    file, place, repo = got
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return None, (f"flow {name} could not be read ({type(e).__name__})",)
    if not flow3.is_format3(text):
        return None, (f"flow {name} ({file.parent}) is not a format-3 flow",)
    checked = flow3.check_text(text, place=place, flow_dir=file.parent, repo_root=repo)
    return text, tuple(checked.problems)


def _reach(
    call: Callable[..., Any],
    root: Path,
    entry: Mapping[str, Any],
    local: str,
    kept: Kept,
    team: str,
    org: Callable[[], orgmod.Org | None],
) -> Reach:
    """`team`'s `Reach`: the repo's one gate and land, kept between passes, and the session half through the host
    agent's `call`. A team the org does not define can start nothing (the launch on a login is TD-2068's); its holders
    are still claimed and ended through the home. `org` reads the org once per pass, at the first team that asks."""
    if kept.gate_land is None:
        kept.gate_land = stage_merge.gate_and_land(root)
    gate, land = kept.gate_land
    read = org()
    teamdef = read.teams.get(team) if read is not None else None
    at = flow_file(root, str(entry.get("flow") or ""))
    doc = None
    if teamdef is not None and at is not None:
        try:
            got = repoconfig.parse_yaml(at[0].read_text(encoding="utf-8"))
            doc = dict(got) if isinstance(got, Mapping) else None
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
            doc = None
    if teamdef is None or at is None or doc is None:
        return Reach(
            gate=gate,
            land=land,
            start=lambda _key, _work: None,
            claim=lambda holder, tid: stage_start.claim(call, holder, tid),
            end=lambda holder: stage_start.end(call, holder),
        )
    host = str(entry.get("host") or local)
    return stage_pass.reach_for(
        call, read, teamdef, doc, gate, land, host=host, here=local, place=at[1], flow_dir=at[0].parent
    )


def run(
    *,
    root: Path | str,
    teams: Mapping[str, Mapping[str, Any]],
    entries: Collection[Mapping[str, Any]],
    prs: Mapping[str, Any] | None,
    graph: Mapping[str, Session],
    snapshotted: Collection[str],
    checkouts: Mapping[str, Collection[str]],
    host_teams: Mapping[str, Any] | None,
    local: str,
    call: Callable[..., Any],
    kept: Kept,
    now: datetime | None = None,
) -> RepoPass | None:
    """One pass over the switched `teams` of the repo at `root` (`settings.yml`'s `teams.<team>` whose `repo` is it).
    None: the repo's ledger or its person could not be read, so no record of it is read this pass. A gate the pass
    runs takes as long as the cadence check does, so the caller runs this in a thread of its own."""
    root = Path(root)
    now = now or datetime.now(UTC)
    try:
        ref = f"origin/{gitinfo.default_branch(root)}"
        read = ledger_read(root, ledger.ledger_path(root), ref)
        if read is None:
            log.warning("the stage pass of %s: its ledger could not be read at %s", root, ref)
            return None
        person = stage_end._person_of(root)
        protected = protected_at(root, ref)
    except stage_end.Refused as e:
        log.warning("the stage pass of %s: %s", root, e)
        return None
    except Exception:  # noqa: BLE001 — a repo that cannot be read this pass is read again on the next
        log.exception("the stage pass of %s could not read the repo", root)
        return None
    sessions = sessions_read(graph, snapshotted)
    flows = {team: flow_now(root, entry.get("flow")) for team, entry in teams.items()}

    def facts(team: str, flow: TeamFlow, records: Mapping[str, Any]) -> Any:
        return stage_pass.repo_facts(
            root,
            ref,
            read,
            person=person,
            team=team,
            now=now,
            flow=flow,
            entries=[dict(e) for e in entries],
            prs=prs,
            read_one=lambda n: reports.pr_state_row(root, n),
            records=records,
            sessions=sessions,
            checkouts=checkouts,
            local=local,
            host_teams=host_teams,
            protected=protected,
            started=False,  # stage_start.team_started, false until TD-2065 writes the started mark
        )

    held: list[orgmod.Org | None] = []

    def org() -> orgmod.Org | None:
        if not held:
            try:
                held.append(orgmod.load())
            except Exception:  # noqa: BLE001 — an unreadable org starts nothing; holders are still claimed and ended
                log.exception("the org could not be read for the stage pass of %s", root)
                held.append(None)
        return held[0]

    def reach(team: str) -> Reach:
        return _reach(call, root, teams.get(team) or {}, local, kept, team, org)

    return stage_pass.repo_pass(StageStore(root), kept.state, flows, facts, sessions, reach, local=local, now=now)
