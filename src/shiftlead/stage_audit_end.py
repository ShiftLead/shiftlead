"""`ao stage end` from an audit's session (design §4.9c *Audits start on a clock*, the outcome table; §4.7; TD-2053).

An audit run's session holds the run's lease, `audit:<team>/<audit>` (`stage_audit.lease_ref`), not an entry, and ends
the run with `findings-filed`, `nothing-found` or `other`. Each is checked as §4.9c's table says (`stage_audit.
end_refusal`): `findings-filed` names at least one entry, and each entry it names was **filed in this run** — its id
was handed out by the home (`ao td reserve`, the `given` records of `ids.json`) to the run's holder at or after the
run started; `nothing-found` and `other` give a reason. Accepted, the run record is written as finished
(`stage_audit.finished`): no holder, its start and base standing, so its next clock runs from them. An `other` first
adds the home's one plain board line naming the audit and the run (`line_text`, a `Due:` and no detail block); it
offers no answers, and closing it does nothing more. A call repeated by the session that ended the run is answered with
where it went.

`stage_end.call` routes an audit's reference here, and the host agent's `stage_end` takes an audit run's lease as a
session's lane and releases its claim once the end is written (`sessionorc.agent_stage`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from shiftlead import stage_audit
from shiftlead.stage_audit import LEASE_PREFIX
from shiftlead.stage_end import Refused
from shiftlead.stagerecord import StageStore

TID = re.compile(r"\bTD-[1-9]\d*\b")
DONE = "done"  # where `findings-filed` and `nothing-found` take the run (§4.9c: both finish it, as `done`)
PERSON = "person"  # where `other` takes it: the home's board line


def is_ref(ref: str) -> bool:
    """Whether `ref` is an audit run's lease, the one its session holds."""
    return split_ref(ref) is not None


def split_ref(ref: str) -> tuple[str, str] | None:
    """`(team, audit's key)` of an audit run's lease `audit:<team>/<audit>`, or None."""
    if not (ref or "").startswith(LEASE_PREFIX):
        return None
    team, slash, key = ref[len(LEASE_PREFIX) :].partition("/")
    return (team, key) if slash and team and key and "/" not in key else None


def named(reason: str) -> list[str]:
    """The entries a `findings-filed` reason names, in order, each once."""
    return list(dict.fromkeys(TID.findall(reason or "")))


def _at(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _bare(address: str) -> str:
    """A session's id with no `@<host>`: the id service records its caller as the call reached the home, which may
    name a node's session bare where its holder is written `<id>@<node>`."""
    return address.partition("@")[0]


def filed_in_run(given: Iterable[Mapping[str, Any]], holder: str, started_at: Any) -> set[str]:
    """The ids the home handed out to `holder` (by its bare id) at or after `started_at`: the entries the run could
    have filed."""
    start = _at(started_at)
    if start is None:
        return set()
    out, bare = set(), _bare(holder)
    for g in given:
        at = _at(g.get("at"))
        if _bare(str(g.get("by") or "")) == bare and at is not None and at >= start and g.get("id"):
            out.add(str(g["id"]))
    return out


def line_text(team: str, audit: str, run: Mapping[str, Any], reason: str) -> str:
    """The home's plain board line for an audit's `other`: the audit, the run (by its start) and the reason."""
    started = str(run.get("started_at") or "").replace("T", " ").removesuffix("Z")
    when = f" started {started} UTC" if started else ""
    return f"The audit {audit} of team {team} stopped in its run{when}: {reason}. Its next run comes on its clock."


def end_audit(
    store: StageStore,
    ref: str,
    caller: str,
    outcome: str,
    reason: str,
    *,
    team: str | None,
    given: Callable[[], Iterable[Mapping[str, Any]]],
    line: Callable[[str], str | None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Check an audit session's `outcome` and write the run's end: `{entry, outcome, went, repeat}`, `entry` the run's
    lease, or `Refused` with nothing written. `team` is the calling session's; `given()` the home's handed-out ids of
    the repo (`ids.json`'s `given`); `line(text)` writes the home's plain board line and returns its id. The line is
    written before the record, so a record that then fails to be written leaves a line the retry writes again."""
    parts = split_ref(ref)
    if parts is None:
        raise Refused(f"{ref} is no audit run's reference")
    owner, key = parts
    if team is not None and owner != team:
        raise Refused(f"{ref} is an audit of team {owner}, not of {team}")
    said = " ".join((reason or "").split())
    with store.locked():
        run = store.audit(owner, key)
        if run is None:
            raise Refused(f"{ref} has no run record")
        ended = run.get("ended") or {}
        if run.get("holder") != caller:
            if not run.get("holder") and ended.get("by") == caller and ended.get("outcome") == outcome:
                went = PERSON if outcome == "other" else DONE
                return {"entry": ref, "outcome": outcome, "went": went, "repeat": True}
            raise Refused("this run is not yours" if run.get("holder") else "the run is over")
        filed = named(said) if outcome == "findings-filed" else []
        if refused := stage_audit.end_refusal(outcome, said, filed):
            raise Refused(refused)
        if filed:
            mine = filed_in_run(given(), caller, run.get("started_at"))
            if stray := [t for t in filed if t not in mine]:
                raise Refused(
                    f"{', '.join(stray)} {'was' if len(stray) == 1 else 'were'} not filed in this run: name only the "
                    "entries whose ids `ao td reserve` gave you since the run started"
                )
        got = None
        if outcome == "other":
            try:
                got = line(line_text(owner, key, run, said))
            except Exception as e:  # noqa: BLE001 — nothing is written, and the session tries again
                raise Refused(f"the home's board line could not be written ({e}): try again") from None
            if not got:
                raise Refused("the home's board line could not be written: try again")
        store.put_audit(owner, key, stage_audit.finished(run, outcome, said, now(), by=caller, line=got))
    return {"entry": ref, "outcome": outcome, "went": PERSON if outcome == "other" else DONE, "repeat": False}
