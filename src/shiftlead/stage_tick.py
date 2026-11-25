"""One repo's stage pass as the tick calls it (design §4.9c *The home acts only where no session will*, TD-2051).

`run` is the shiftlead half of the tick's wiring, reached through the `shiftlead.home_calls` entry point `stage_tick`
because `sessionorc` never imports `shiftlead`. The home passes what only it holds (its graph of sessions, the nodes
whose snapshot has arrived, every node's checkouts of the repo, the repo's pull request reading and ledger rows, its
`host` record's teams) and the switched teams of the repo from `settings.yml`; `run` reads the rest once from the repo
itself (the ledger at origin's default branch, the protected files, each team's flow and its check, the person) and
takes `stage_pass.repo_pass`. What one repo's passes keep between them (`Kept`) is the caller's to hold.

Given the repo reading's work orders, pull request orders and boards, `run` then takes the two built-in seats' passes
over their jobs (`stage_job_tick`, TD-2053); the home hands them over in a later slice. Last, it takes act 6 over the
started teams' audits (`stage_audit_pass`, TD-2053), a rested run's note to the person being the caller's.

A session starts only for a started team (`stage_start.team_started`, the home's started mark in the `host` record's
teams, TD-2065), and a team is read only after the cut-over, when the caller passes it.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import gitinfo, ledger, paths, reports
from sessionorc.models import Session
from shiftlead import (
    flow3,
    stage_audit_pass,
    stage_audit_start,
    stage_end,
    stage_job_tick,
    stage_merge,
    stage_pass,
    stage_seats,
    stage_size,
    stage_start,
)
from shiftlead import org as orgmod
from shiftlead.stage_fetch import (
    TeamFlow,
    carries_branch,
    flow_doc_of,
    ledger_read,
    protected_at,
    pushed_branches,
    rows_of,
    sessions_read,
    team_flow,
)
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
    doc: Mapping[str, Any],
) -> Reach:
    """`team`'s `Reach`: the repo's one gate and land, kept between passes, and the session half through the host
    agent's `call`, launching from `doc`, the flow the pass runs — the last good copy while the team's flow fails its
    check (§4.9c). A stage's own brief is read from the flow's directory as found now; with no flow file found, only
    a standard brief can be read, so a stage naming its own fails its start. A team the org does not define can start
    nothing (the launch on a login is TD-2068's); its holders are still claimed and ended through the home. `org`
    reads the org once per pass, at the first team that asks."""
    if kept.gate_land is None:
        kept.gate_land = stage_merge.gate_and_land(root)
    gate, land = kept.gate_land
    read = org()
    teamdef = read.teams.get(team) if read is not None else None
    if teamdef is None:
        return Reach(
            gate=gate,
            land=land,
            start=lambda _key, _work: None,
            claim=lambda holder, tid: stage_start.claim(call, holder, tid),
            end=lambda holder: stage_start.end(call, holder),
        )
    host = str(entry.get("host") or local)
    at = flow_file(root, str(entry.get("flow") or ""))
    place, flow_dir = (at[1], at[0].parent) if at is not None else ("package", None)
    return stage_pass.reach_for(
        call, read, teamdef, dict(doc), gate, land, host=host, here=local, place=place, flow_dir=flow_dir
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
    orders: Collection[Mapping[str, Any]] | None = None,
    pr_orders: Collection[Mapping[str, Any]] | None = None,
    boards: Mapping[str, Any] | None = None,
) -> RepoPass | None:
    """One pass over the switched `teams` of the repo at `root` (`settings.yml`'s `teams.<team>` whose `repo` is it).
    None: the repo's ledger or its person could not be read, so no record of it is read this pass. A gate the pass
    runs takes as long as the cadence check does, so the caller runs this in a thread of its own. With `orders` and
    `pr_orders` (`teamrun.work_orders` and `pr_orders` of the repo reading) and its `boards`, the built-in seats' jobs
    are passed over after the teams (`jobs`); without them, they are not."""
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

    pushed: list[frozenset[str] | None] = []  # origin's branches, read once a pass and only when a record needs them
    by_name: dict[str, Mapping[str, Any] | None] = {}  # a switched record's old flow, read once a pass by its name

    def named(name: str) -> Mapping[str, Any] | None:
        if name not in by_name:
            by_name[name] = flow_doc_of(flow_now(root, name)[0])
        return by_name[name]

    def facts(team: str, flow: TeamFlow, records: Mapping[str, Any]) -> Any:
        branches: frozenset[str] | None = frozenset()
        if carries_branch(records):
            if not pushed:
                pushed.append(pushed_branches(root))
            branches = pushed[0]
            if branches is None:  # a moved entry whose branch cannot be seen is not offered afresh in its place
                log.warning("the stage pass of %s: origin's branches could not be read", root)
                return None
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
            branches=branches,
            started=stage_start.team_started(host_teams, team),
            named=named,
            limits=stage_size.limits(teams.get(team)),
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

    def reach(team: str, doc: Mapping[str, Any]) -> Reach:
        return _reach(call, root, teams.get(team) or {}, local, kept, team, org, doc)

    store = StageStore(root)
    got = stage_pass.repo_pass(store, kept.state, flows, facts, sessions, reach, local=local, now=now)
    try:
        got = dataclasses.replace(
            got, audits=_audits(store, root, ref, teams, flows, sessions, local, call, org, now, host_teams)
        )
    except Exception:  # noqa: BLE001 — the audits' pass failing is a log line and never the teams' pass
        log.exception("the audit pass of %s failed", root)
    try:  # a started team's built-in tech lead, written where none stands (§4.9d *How each one runs*)
        if wrote := stage_seats.write_techleads(call, org(), teams, graph, host_teams, local):
            log.info("the stage pass of %s wrote the built-in seat records %s", root, ", ".join(wrote))
    except Exception:  # noqa: BLE001 — the seats' records failing is a log line and never the teams' pass
        log.exception("the seat records of %s could not be written", root)
    try:  # the repo's built-in sweeper, written where none stands while the sweep switch is on (§4.9d)
        switch = call("sweep_switch") if any(stage_start.team_started(host_teams, t) for t in teams) else None
        if wrote := stage_seats.write_sweepers(call, org(), teams, graph, host_teams, local, switch):
            log.info("the stage pass of %s wrote the built-in seat records %s", root, ", ".join(wrote))
    except Exception:  # noqa: BLE001 — the sweeper's record failing is a log line and never the teams' pass
        log.exception("the sweeper record of %s could not be written", root)
    if orders is None or pr_orders is None:
        return got
    try:
        if kept.gate_land is None:  # the repo's one gate and land, the teams' pass's own where it made them
            kept.gate_land = stage_merge.gate_and_land(root)
        jobs = _jobs(
            store,
            root,
            teams,
            flows,
            orders,
            pr_orders,
            boards,
            prs,
            entries,
            sessions,
            checkouts,
            local,
            call,
            org,
            now,
            gate_land=kept.gate_land,
            host_teams=host_teams,
        )
        return dataclasses.replace(got, jobs=jobs)
    except Exception:  # noqa: BLE001 — the jobs' pass failing is a log line and never the teams' pass
        log.exception("the job pass of %s failed", root)
        return got


def _jobs(
    store: StageStore,
    root: Path,
    teams: Mapping[str, Mapping[str, Any]],
    flows: Mapping[str, tuple[str | None, tuple[str, ...]]],
    orders: Collection[Mapping[str, Any]],
    pr_orders: Collection[Mapping[str, Any]],
    boards: Mapping[str, Any] | None,
    prs: Mapping[str, Any] | None,
    entries: Collection[Mapping[str, Any]],
    sessions: Any,
    checkouts: Mapping[str, Collection[str]],
    local: str,
    call: Callable[..., Any],
    org: Callable[[], orgmod.Org | None],
    now: datetime,
    *,
    gate_land: tuple[stage_merge.Gate, stage_merge.Land],
    host_teams: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The jobs' pass, once the teams' pass is done: each team's flow as its records read it, the last good copy
    while it fails (`team_flow`), and the rows, with each open board answer's own pull request read by its number.
    The repo's name, which picks its built-in set, is its teams' `repo`. A pull request reading that cannot be read
    passes over no job. A job waiting `merging` is merged through `gate_land`, the repo's one gate and land."""
    docs = _docs(store, flows)
    wanted = sorted({r["pr"] for r in store.jobs().values() if isinstance(r.get("pr"), int) and not r.get("closed_at")})
    rows = rows_of(prs, wanted, lambda n: reports.pr_state_row(root, n))
    if rows is None:
        return {}
    read = org()
    started = sorted(
        t for t in teams if read is not None and t in read.teams and stage_start.team_started(host_teams, t)
    )
    repo = next((str(e["repo"]) for e in teams.values() if e.get("repo")), root.name)
    hosts = {t: str(e.get("host") or "") for t, e in teams.items()}
    flows_at: dict[str, tuple[str, Path | None]] = {}
    for t, e in teams.items():
        at = flow_file(root, str(e.get("flow") or ""))
        flows_at[t] = (at[1], at[0].parent) if at is not None else ("package", None)
    reach = stage_job_tick.reach_for(call, org, root, repo, local=local, hosts=hosts, docs=docs, flows_at=flows_at)
    return stage_job_tick.run(
        store,
        reach,
        now=now,
        orders=orders,
        pr_orders=pr_orders,
        boards=boards,
        rows=rows,
        entries=entries,
        sessions=sessions,
        checkouts=checkouts,
        local=local,
        started=started,
        docs=docs,
        may_start=bool(started),
        gate_land=gate_land,
    )


def _docs(store: StageStore, flows: Mapping[str, tuple[str | None, tuple[str, ...]]]) -> dict[str, Mapping[str, Any]]:
    """Each team's flow as its records read it: the last good copy while it fails its check (`team_flow`)."""
    docs: dict[str, Mapping[str, Any]] = {}
    for team, (current, problems) in flows.items():
        flow = team_flow(current, problems, store.flow(team))
        if flow is not None:
            docs[team] = flow.doc
    return docs


def _audits(
    store: StageStore,
    root: Path,
    ref: str,
    teams: Mapping[str, Mapping[str, Any]],
    flows: Mapping[str, tuple[str | None, tuple[str, ...]]],
    sessions: Any,
    local: str,
    call: Callable[..., Any],
    org: Callable[[], orgmod.Org | None],
    now: datetime,
    host_teams: Mapping[str, Any] | None = None,
) -> tuple[stage_audit_pass.AuditStep, ...]:
    """Act 6 over the started teams' audits. A run's session launches on its team's host from the flow in force, its
    own brief read from the flow's directory as `_reach` reads a stage's; the head and the count are read at `ref`. No
    team started reads nothing, not even a team's flow."""
    read = org()
    started = sorted(
        t for t in teams if read is not None and t in read.teams and stage_start.team_started(host_teams, t)
    )
    if not started:
        return ()
    docs = _docs(store, {t: flows[t] for t in started if t in flows})

    def start(team: str, key: str, base: str | None, came: str | None) -> str | None:
        got_org = org()
        teamdef = got_org.teams.get(team) if got_org is not None else None
        doc = docs.get(team)
        if got_org is None or teamdef is None or doc is None:
            return None
        entry = teams.get(team) or {}
        at = flow_file(root, str(entry.get("flow") or ""))
        place, flow_dir = (at[1], at[0].parent) if at is not None else ("package", None)
        got = stage_audit_start.launch(
            got_org,
            teamdef,
            dict(doc),
            key,
            host=str(entry.get("host") or local),
            here=local,
            base=base,
            came=came,
            place=place,
            flow_dir=flow_dir,
        )
        made = stage_start.start(call, got_org, teamdef, got)
        return stage_start.holder_of(got, made) if made else None

    reach = stage_audit_pass.AuditReach(
        start=start,
        claim=lambda holder, lease: stage_start.claim(call, holder, lease),
        end=lambda holder: stage_start.end(call, holder, "its audit's run record no longer names it"),
        head=stage_audit_pass.head_of(root, ref),
        merged_since=stage_audit_pass.merged_since(root, ref),
    )
    seen = stage_pass.addressed(sessions, local)  # a holder may be written in the home's `id@<local>` form
    f = stage_audit_pass.AuditFacts(
        now=now,
        sessions=seen.sessions,
        read_nodes=seen.read_nodes,
        open_asks=seen.open_asks,
        started=tuple(started),
        docs=docs,
        may_start=True,
        limits={t: stage_size.limits(teams.get(t)) for t in started},
    )
    return stage_audit_pass.audit_pass(store, f, reach)


def call(**kwargs: Any) -> RepoPass | None:
    """The `shiftlead.home_calls` entry point's call, as every home call module has one: `run`."""
    return run(**kwargs)
