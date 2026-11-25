"""One repo's pass over its audits, act 6 of the tick (design §4.9c *Audits start on a clock*, TD-2053).

For each started team and each audit its flow lists, `audit_pass` reads the audit's run record (`StageStore.audit`,
keyed by the team and the audit's key), reads its holder as an entry's is (`stage_read.holder_on`, on the run's lease
`audit:<team>/<audit>`) and, for a `merged-pull-requests` clock, the count since the run's base, and takes the one act
`stage_audit.choose` names. `make` writes it under the store's lock after a fresh read still chooses it:

- **start**: a fresh session of the audit (`AuditReach.start`) holds the run, with its claim on the lease, and the
  record is written as the run starts (`stage_audit.started`), its base the default branch's head then;
- **offer-again**: a lost, silent or stopped run is offered once more; a silent holder is ended first, and the run's
  start and base stand (`stage_audit.again`);
- **rest**: lost again, the run ends as `lost` with its clock afresh from now and the head (`stage_audit.rested`); a
  silent holder is ended. The person is told with one note, which is the caller's: a step whose act is `rest` and
  whose write was made says so (`AuditStep.tell`), as `RepoPass.tell` does of a flow.

What reaches the world is an `AuditReach`, so one audit's failure is that audit's. The pull requests merged since a
base are counted as the default branch's first-parent commits after it (`merged_since`): each squash or merge of a
pull request is one, and so is a rare push straight to it. A run's `findings-filed`, `nothing-found` and `other` are
`ao stage end`'s, a later slice. Nothing starts a run yet: `stage_start.team_started` is false until TD-2065.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sessionorc import gitinfo
from sessionorc.models import Session
from shiftlead import flow3, stage_audit
from shiftlead.stage_audit import AuditAct, AuditReading
from shiftlead.stage_make import Made
from shiftlead.stage_read import holder_on
from shiftlead.stagerecord import StageStore, StateError

log = logging.getLogger(__name__)

CAME = {"lost": "lost", "silent": "silent", "stopped": "stopped"}  # how a run's last session went, as told()'s `came`


@dataclass(frozen=True)
class AuditReach:
    """How an audit's act reaches the world. `start(team, audit, base, came)` starts the run's session and returns its
    address, or None; `claim(holder, ref)` writes the holder's claim on the run's lease and returns why it was refused,
    or None; `end(holder)` ends a session; `head()` is the default branch's head (None: not read); `merged_since(base)`
    the pull requests merged since `base` (None: not read)."""

    start: Callable[[str, str, str | None, str | None], str | None]
    claim: Callable[[str, str], str | None]
    end: Callable[[str], None]
    head: Callable[[], str | None]
    merged_since: Callable[[str], int | None]


@dataclass(frozen=True)
class AuditFacts:
    """What the pass read for a repo's audits: the time, the sessions by address of the nodes in `read_nodes` and
    `open_asks` those with an open ask of their own (`stage_pass.addressed`), the repo's started teams and each one's
    flow in force (`docs`), and whether a session may start (`may_start`)."""

    now: datetime
    sessions: Mapping[str, Session] = field(default_factory=dict)
    read_nodes: Collection[str] = ()
    open_asks: Collection[str] = ()
    started: Collection[str] = ()
    docs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    may_start: bool = False


@dataclass(frozen=True)
class AuditStep:
    """What one audit's turn did. `read`: False where the audit had no reading this pass (its holder's node not read).
    `tell`: the run rested at its second loss, for the person to be told once."""

    team: str
    audit: str
    read: bool = True
    act: AuditAct | None = None
    made: Made | None = None
    unended: str | None = None

    @property
    def tell(self) -> bool:
        return self.act is not None and self.act.name == "rest" and self.made is not None and self.made.made


def merged_since(root: Path | str, ref: str, timeout: float = 10.0) -> Callable[[str], int | None]:
    """`AuditReach.merged_since` read from the repo's own refs: the first-parent commits of `ref` after `base`. A base
    `ref` does not reach (rewritten away) is no count."""

    def count(base: str) -> int | None:
        if gitinfo._git(root, "merge-base", "--is-ancestor", base, ref, timeout=timeout) is None:
            return None
        out = gitinfo._git(root, "rev-list", "--count", "--first-parent", f"{base}..{ref}", timeout=timeout)
        return int(out.strip()) if out and out.strip().isdigit() else None

    return count


def head_of(root: Path | str, ref: str, timeout: float = 10.0) -> Callable[[], str | None]:
    """`AuditReach.head`: the commit `ref` names now."""

    def head() -> str | None:
        out = gitinfo._git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", timeout=timeout)
        return out.strip() or None if out else None

    return head


def _session(f: AuditFacts, holder: str) -> tuple[bool, Session | None]:
    """Whether `holder`'s node was read, and its session (None: gone)."""
    _, at, node = holder.partition("@")
    if at and node not in f.read_nodes:
        return False, None
    return True, f.sessions.get(holder)


def reading_on(
    team: str,
    key: str,
    run: Mapping[str, Any] | None,
    every: stage_audit.Clock | None,
    f: AuditFacts,
    reach: AuditReach,
) -> AuditReading | None:
    """The audit's `AuditReading`. None: its holder's node was not read. The count is read only where it can decide a
    start: a `merged-pull-requests` clock, and a run with a base and no holder."""
    may_start = f.may_start and team in f.started
    holder = None
    if run and (h := str(run.get("holder") or "")):
        read, s = _session(f, h)
        if not read:
            return None
        holder = holder_on(s, stage_audit.lease_ref(team, key), f.now, open_ask=h in f.open_asks)
    count = None
    if run and not run.get("holder") and every is not None and every.unit == "merged-pull-requests" and run.get("base"):
        count = reach.merged_since(str(run["base"]))
    return AuditReading(holder=holder, merged_since=count, may_start=may_start)


def _offer(
    store: StageStore, team: str, key: str, run: Mapping[str, Any] | None, act: AuditAct, f: AuditFacts, r: AuditReach
) -> Made:
    """A start or an offer again: a session holds the run, with its claim, and the record says so. A session whose
    claim or record could not be written is named for the caller to end; the next pass offers afresh."""
    if run is None or act.name == "start":
        base = r.head()
        if not base:
            return Made(False, "the default branch's head could not be read")
    else:
        base = str(run.get("base") or "") or None
    try:
        holder = r.start(team, key, base, CAME.get(act.case) if act.name == "offer-again" else None)
    except Exception as e:  # noqa: BLE001 — one audit's failure is that audit's
        return Made(False, f"the session could not be started: {e}")
    if holder is None:
        return Made(False, "no session was started")
    try:
        if refused := r.claim(holder, stage_audit.lease_ref(team, key)):
            return Made(False, f"the claim was refused: {refused}", end=holder)
        record = (
            stage_audit.started(holder, str(base), f.now)
            if run is None or act.name == "start"
            else stage_audit.again(run, holder, act)
        )
        store.put_audit(team, key, record)
    except Exception as e:  # noqa: BLE001 — whatever failed, a started session must not be left unnamed
        return Made(False, f"the run did not start: {e}", end=holder)
    return Made(True)


def make(
    store: StageStore,
    team: str,
    key: str,
    every: stage_audit.Clock,
    act: AuditAct,
    s: AuditReading,
    f: AuditFacts,
    reach: AuditReach,
) -> Made:
    """Write `act` on the audit `key` of `team`, if a fresh read under the lock still chooses it."""
    with store.locked():
        run = store.audit(team, key)
        if stage_audit.choose(run, every, s, f.now) != act:
            return Made(False, "the run record moved since it was read")
        held = str(run.get("holder") or "") if run else ""
        if held and act.case == "silent":
            try:  # a silent holder may still run: it is ended before another takes the run (§4.9c, act 4)
                reach.end(held)
            except Exception as e:  # noqa: BLE001 — nothing is started beside it; the next pass tries again
                return Made(False, f"the silent session could not be ended: {e}")
        if act.name == "rest":
            base = reach.head()
            if not base:
                return Made(False, "the default branch's head could not be read")
            store.put_audit(team, key, stage_audit.rested(run or {}, act, base, f.now))
            got = Made(True)
        elif act.name in ("start", "offer-again"):
            got = _offer(store, team, key, None if act.name == "start" else run, act, f, reach)
        else:
            return Made(False, f"{act.name} is no audit's act")
        if got.made and held and act.case != "silent" and got.end is None:
            return Made(True, got.why, end=held)  # a lapsed lease's session may still run: the act took the run from it
        return got


def step(store: StageStore, team: str, audit: Mapping[str, Any], f: AuditFacts, reach: AuditReach) -> AuditStep:
    """Take the audit's one act this pass, if it has one."""
    key = flow3.key_of(audit.get("name"))
    every = stage_audit.clock(audit.get("every"))
    try:
        run = store.audit(team, key)
    except (StateError, ValueError):
        log.exception("the run record of audit %s/%s could not be read", team, key)
        return AuditStep(team, key, read=False)
    s = reading_on(team, key, run, every, f, reach)
    if s is None or every is None:
        return AuditStep(team, key, read=s is not None)
    act = stage_audit.choose(run, every, s, f.now)
    if act is None:
        return AuditStep(team, key)
    try:
        made = make(store, team, key, every, act, s, f, reach)
    except Exception as e:  # noqa: BLE001 — one audit's failure must not stop the pass over the others
        log.exception("the audit act %s %s on %s/%s failed", act.name, act.case, team, key)
        return AuditStep(team, key, act=act, made=Made(False, f"the act failed: {e}"))
    if not made.end:
        return AuditStep(team, key, act=act, made=made)
    try:
        reach.end(made.end)
    except Exception:  # noqa: BLE001 — the act is written; the session left running is reported, never raised
        log.exception("ending %s after the audit act on %s/%s failed", made.end, team, key)
        return AuditStep(team, key, act=act, made=made, unended=made.end)
    return AuditStep(team, key, act=act, made=made)


def audit_pass(store: StageStore, f: AuditFacts, reach: AuditReach) -> tuple[AuditStep, ...]:
    """One pass over the audits of each started team, by team and then in its flow's order. A team not started runs
    no audit, and its runs' records are left as they stand."""
    steps = []
    for team in sorted(f.started):
        for audit in (f.docs.get(team) or {}).get("audits") or []:
            if isinstance(audit, Mapping) and audit.get("name"):
                steps.append(step(store, team, audit, f, reach))
    return tuple(steps)
