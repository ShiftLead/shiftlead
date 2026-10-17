"""A team's shape at the home (design §4.4 *Team shape*, TD-819; built by TD-834): once a minute each
running team's sampled members are classed and its stages' queues measured, from what the home already
reads — the records, the repo readings through `ledger.in_lanes` (as the balance marks read them), the
person inbox's `waiting_of` and the seats' `prs_waiting` — and added to `shape.json`; the `shape` RPC
reads it. The pure half is `sessionorc.shape`. A mixin `HostAgent` inherits.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Any

from sessionorc import balance as balance_mod
from sessionorc import ledger as ledger_mod
from sessionorc import naming
from sessionorc import shape as shape_mod
from sessionorc import work as work_mod
from sessionorc.agent_common import RpcError, log
from sessionorc.agent_tick import _orders
from sessionorc.models import Session

DEAD = work_mod.DEAD


class ShapeMixin:
    def _shape_init(self) -> None:
        self.shape_store = shape_mod.ShapeStore()
        self._shape: dict[str, Any] = self.shape_store.load()
        self._shape_at = 0.0  # monotonic: when the last sample was taken
        self._shape_pruned = ""

    async def _shape_tick(self, now: datetime) -> None:
        """Once a minute (`SHAPE_EVERY`), not every tick: a shape is read over hours. A surprise is a log
        line; the next minute samples again."""
        if time.monotonic() - self._shape_at < shape_mod.SHAPE_EVERY:
            return
        self._shape_at = time.monotonic()
        try:
            sampled = self._shape_pass(now)
        except Exception:  # noqa: BLE001 — the shape is a reading: a minute missed, never a tick
            log.exception("sampling the teams' shape failed")
            return
        if not sampled:
            return  # a quiet minute writes nothing
        snapshot = json.loads(json.dumps(self._shape))
        try:
            await asyncio.to_thread(self.shape_store.save, snapshot)
        except OSError:
            log.exception("writing shape.json failed")

    def _shape_pass(self, now: datetime) -> bool:
        """One minute's sample of every running team — a team with a live crew record (§4.9 *A person in
        the team*: a person's session keeps nothing running). True when a team was sampled."""
        graph = list(self._graph().values())
        teams: dict[str, list[Session]] = {}
        for r in graph:
            if r.team and r.unattended and not r.superseded_by and not work_mod.sat_out(r):
                teams.setdefault(r.team, []).append(r)
        # by record id: the inbox names a node's sender `id@host`, as the readers' asks do
        person = {naming.split_address(k)[0] for k in work_mod.waiting_of(self.person_inbox)}
        review: set[str] = set()
        for r in graph:
            for a in (r.prs_waiting(home=self.host) or {}).get("asks") or ():
                if isinstance(a, dict) and a.get("from"):
                    review.add(naming.split_address(str(a["from"]))[0])
        sampled = False
        for team, crew in sorted(teams.items()):
            try:
                sampled |= self._shape_team(team, crew, graph, person, review, now)
            except Exception:  # noqa: BLE001 — one team's surprise is a log line, never another's minute
                log.exception("sampling %s's shape failed", team)
        day = now.astimezone().date()
        if sampled and self._shape_pruned != day.isoformat():
            self._shape_pruned = day.isoformat()
            shape_mod.prune(self._shape, day)
        return sampled

    def _shape_team(
        self, team: str, crew: list[Session], graph: list[Session], person: set[str], review: set[str], now: datetime
    ) -> bool:
        live = [r for r in crew if r.state not in DEAD]
        if not any(r.adapter != "shell" for r in live):
            return False  # not running: a shell opened from a member keeps nothing running (TD-821)
        manager = work_mod.manager_of(crew)
        stages = shape_mod.stages(crew, manager)
        if not stages:
            return False
        counts: dict[str, int] = {}
        ids: dict[str, list[str]] = {}
        # the team's repos are the ones its live members name that the home reads, as `_balance_mark` takes
        # them (§6 *Balance*): a path the registry does not list is not the team's repo; none read is a
        # minute that could not look, not one with *no work*
        roots = sorted({r.repo for r in live if r.repo and r.adapter != "shell" and r.repo in self._repos})
        if not roots:
            return False
        for root in roots:
            facts = self._repos.get(root) or {}
            led = facts.get("ledger") or {}
            if "error" in led or not isinstance(led.get("entries"), list):
                return False  # could not look is not *no work*: the minute is not sampled
            held = {
                p.ref
                for r in graph
                if r.repo == root and r.state not in DEAD and not r.superseded_by
                for p in r.progress
                if p.status == "claimed"
            }
            views = [
                {"id": r.id, "name": r.name, "lane": list(r.lane), "team": r.team, "state": r.state}
                | {"out_of_work": r.out_of_work}
                for r in crew
                if r.repo == root
            ]
            got = ledger_mod.in_lanes([*led["entries"], *_orders(facts)], views, held)
            if got is None:
                continue
            for m in got["members"]:
                counts[str(m["id"])] = counts.get(str(m["id"]), 0) + len(m["ids"])
            for kind in set(shape_mod.LANE_KIND.values()):
                ids.setdefault(kind, []).extend(f"{root}:{i}" for i in got.get(kind) or () if i not in held)
        members = []
        for r in live:
            st = None if r is manager else shape_mod.stage_of(r, stages)
            if st is None or r.state not in shape_mod.SAMPLED_STATES:
                continue  # unreachable or scheduled: nothing the record could be doing is known
            seat = r.seat is not None
            members.append(
                {
                    "id": self._address(r),
                    "name": r.name,
                    "role": r.role or r.name,
                    "stage": st["name"],
                    "class": shape_mod.classify(
                        r,
                        seat=seat,
                        in_review=r.id in review,
                        waiting_person=r.id in person,
                        lane_count=counts.get(r.id, 0),
                        prs_waiting=bool(seat and r.prs_waiting(home=self.host)),
                    ),
                }
            )
        queues = []
        for n, st in enumerate(stages):
            q = {"name": st["name"], "role": st["role"], "kind": st["kind"], "order": n}
            if st["kind"] == "lane":
                q["ids"] = ids.get(st["lane"], [])
            else:
                held_by = [r for r in crew if r.seat is not None and r.name == st["reader"]]
                held_by.sort(key=lambda r: (r.state not in DEAD, str(r.created or "")))
                w = held_by[-1].prs_waiting(home=self.host) if held_by else None
                q.update({"n": w["n"] if w else 0, "oldest": w["oldest"] if w else None})
            queues.append(q)
        bounds = [d for r in live if (d := balance_mod.span((r.review or {}).get("bound")))]
        bound: timedelta = min(bounds) if bounds else balance_mod.REVIEW_BOUND
        shape_mod.take(self._shape, team, now, members, queues, bound)
        return True

    async def rpc_shape(self, team: str, window: str = "day") -> dict[str, Any]:
        """A team's shape over `day` or `week` (design §4.4 *Team shape*, TD-834): per role its live hours
        and class shares, per queue its depth, oldest age and shares, and the suggestions — read from
        `shape.json`, never acting. The home's; a node forwards it (§4.4a)."""
        if window not in ("day", "week"):
            raise RpcError(f"a shape window is day or week, not {window!r} (design §4.4 *Team shape*)")
        return shape_mod.reading(self._shape, str(team), window, datetime.now().astimezone())
