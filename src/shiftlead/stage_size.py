"""How many sessions a switched team may run at once (design §4.9d *Sessions at once*, TD-2065): one number per stage,
1 where its key is absent, and an optional `most` for the team's stage and audit sessions together. The stage pass
offers an entry only while its stage and the team have room, and the audit pass, which runs after it, starts an audit
only while the team has room under `most`, so stages go first. Built-in seats are not counted."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from shiftlead import flow3

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limits:
    """A team's numbers as `settings.yml`'s `teams.<team>` holds them: `at_once` by stage key, and `most` (None: no
    team limit)."""

    at_once: Mapping[str, int] = field(default_factory=dict)
    most: int | None = None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def limits(entry: Mapping[str, Any] | None) -> Limits:
    """The team's `Limits`. A hand-edited number that is no count is read as its default: 1 for a stage, no limit for
    the team."""
    entry = entry or {}
    raw = entry.get("at_once")
    at_once = {str(k): n for k, v in raw.items() if (n := _count(v)) is not None} if isinstance(raw, Mapping) else {}
    return Limits(at_once, _count(entry.get("most")))


@dataclass
class Room:
    """What a pass may still start: `held` the sessions holding the team's open stage records, by stage key, and
    `audits` its audits' runs with a holder. A session the pass starts is taken from it."""

    limits: Limits
    held: Counter[str] = field(default_factory=Counter)
    audits: int = 0

    def total(self) -> int:
        return sum(self.held.values()) + self.audits

    def _team_fits(self) -> bool:
        return self.limits.most is None or self.total() < self.limits.most

    def stage_fits(self, key: str | None) -> bool:
        """Whether one more session of stage `key` fits its number and the team limit. No stage: none fits."""
        return key is not None and self.held[key] < self.limits.at_once.get(key, 1) and self._team_fits()

    def audit_fits(self) -> bool:
        """Whether one more audit session fits: only the team limit holds an audit back."""
        return self._team_fits()

    def take_stage(self, key: str) -> None:
        self.held[key] += 1

    def take_audit(self) -> None:
        self.audits += 1


def stage_held(records: Mapping[str, Mapping[str, Any]], team: str) -> Counter[str]:
    """The sessions holding `team`'s open stage records, by the record's stage."""
    return Counter(
        str(r.get("stage"))
        for r in records.values()
        if isinstance(r, Mapping) and r.get("team") == team and not r.get("closed_at") and r.get("holder")
    )


def audits_held(store: Any, team: str, audits: Iterable[Any]) -> int:
    """How many of the flow's `audits` have a run with a holder. A run record that cannot be read is not counted."""
    n = 0
    for a in audits:
        if not isinstance(a, Mapping) or not a.get("name"):
            continue
        try:
            run = store.audit(team, flow3.key_of(a.get("name")))
        except Exception:  # noqa: BLE001 — an unreadable run is its own audit's no reading, never the count's failure
            log.exception("the run record of audit %s/%s could not be read for its team's room", team, a.get("name"))
            continue
        if isinstance(run, Mapping) and run.get("holder"):
            n += 1
    return n


def room(store: Any, limits: Limits, records: Mapping[str, Mapping[str, Any]], team: str, doc: Any) -> Room:
    """`team`'s `Room` from its open records and the run records of its flow `doc`'s audits."""
    audits = doc.get("audits") if isinstance(doc, Mapping) else None
    return Room(limits, stage_held(records, team), audits_held(store, team, audits if isinstance(audits, list) else ()))
