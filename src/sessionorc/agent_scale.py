"""Rule 14's up half at the home (design §6 rule 14 *Scale with the work*, §4.9 *Scaling with the work*; td-max,
TD-1546 slice 1): a worker line with a held extra is read **short** — its lane holding a pickable entry nobody
holds while every live member of the line holds a lease — at the events that change the answer, never on a timer,
and filled by its lowest-placed held extra. A mixin `HostAgent` inherits; the tick calls `_scale_pass`.

The down half (an out-of-work extra closed back to held), the shape's sampling of an extra and the wound-down
readings are later slices.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sessionorc import ledger as ledger_mod
from sessionorc import seams as seams_mod
from sessionorc import settings as settings_mod
from sessionorc import work as work_mod
from sessionorc.agent_common import FILL_CEILING, FILL_WINDOW, LEASE_TTL, SCALE_STEP, _parse, _recent, log
from sessionorc.agent_tick import _orders
from sessionorc.models import ProgressEntry, Session, now_iso

DEAD = work_mod.DEAD


def _scale_line(r: Session) -> str:
    """The worker line a record is an extra of, or '' — a seat's extra (it carries `seat`) is rule 3's."""
    if not isinstance(r.scale, dict) or r.seat is not None:
        return ""
    return str(r.scale.get("line") or "")


def _of_line(r: Session, line: str) -> bool:
    """Whether `r` runs on the worker line `line`: its extra, or a member under one of the line's names (the bare
    prefix of a `count: 1` line, else `<line>-<k>`; §4.9 *Names, the size and the ceiling*), never a seat."""
    if r.seat is not None:
        return False
    if isinstance(r.scale, dict):
        return _scale_line(r) == line
    return r.name == line or re.fullmatch(rf"{re.escape(line)}-\d+", r.name or "") is not None


def _place(r: Session, line: str) -> tuple[int, str]:
    """An extra's place among its line's extras (§4.9 *An extra*): the number its name carries, read, never stored."""
    k = r.name[len(line) + 1 :] if r.name.startswith(f"{line}-") else ""
    return (int(k) if k.isdigit() else 1 if r.name == line else 1 << 30, r.name)


def _last(r: Session) -> dict[str, Any]:
    last = r.scale.get("last") if isinstance(r.scale, dict) else None
    return last if isinstance(last, dict) else {}


def _claimed(r: Session) -> bool:
    """Whether a record's `progress` holds a claim (rule 14's guard): one claimed, or one claimed and since done."""
    return any(e.status in ("claimed", "done") for e in r.progress)


def _lease(e: ProgressEntry, now: datetime) -> bool:
    """Whether a progress entry holds a lease (§6 rule 14, §4.8 *A claim is a lease*): a claim not `done` or
    `dropped`, declared — younger than `LEASE_TTL`, as `ao progress claim`'s test reads it — or derived."""
    if e.status != "claimed":
        return False
    if e.source != "declared":
        return True
    try:
        at = _parse(str(e.at))
    except (TypeError, ValueError):
        return False
    return now - at < LEASE_TTL


class ScaleMixin:
    def _scale_init(self) -> None:
        # (team, line) → the line's pickable entries nobody holds at the last reading (rule 14's own memory, beside
        # rule 8's and rule 6's `lane_seen`, never in it); in memory, so the first reading after a start is a baseline
        self._scale_seen: dict[tuple[str, str], set[str]] = {}
        # (team, line) whose last reading was short with its fill held back: read again each tick until it fills
        # or is no longer short
        self._scale_held: set[tuple[str, str]] = set()
        # the addresses that declared a claim since the last pass (`ao progress claim`, rule 14's second event)
        self._scale_claims: set[str] = set()

    def _scale_claimed(self, s: Session) -> None:
        """A declared claim's event (rule 14): the line it runs on is read at the next tick."""
        if self.mode != "node" and s.team:
            self._scale_claims.add(self._address(s))

    async def _scale_pass(self, now: datetime) -> None:
        """Rule 14 up, at the home: each running team's worker lines that carry an extra, read at an event — an
        entry becoming pickable in the line's lane, a member of the line claiming, or a fill held back at the last
        reading — and filled where short. One team's surprise is a log line, never another's or the tick's."""
        if self.mode != "home":
            return
        claims, self._scale_claims = self._scale_claims, set()
        records = [*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values())]
        teams: dict[str, list[Session]] = {}
        for r in records:
            if r.team and not r.superseded_by:
                teams.setdefault(r.team, []).append(r)
        keep: set[tuple[str, str]] = set()
        for team, crew in sorted(teams.items()):
            for line in sorted({ln for r in crew if (ln := _scale_line(r))}):
                keep.add((team, line))
                try:
                    await self._scale_line_pass(team, line, crew, records, claims, now)
                except Exception:  # noqa: BLE001 — one line's surprise is a log line, never the tick's
                    log.exception("rule 14: reading %s's line %s failed", team, line)
        for key in [k for k in self._scale_seen if k not in keep]:
            del self._scale_seen[key]  # a line with no extra any more: its memory goes with it
        self._scale_held &= keep

    def _scale_pickable(self, line: list[Session], graph: Iterable[Session], now: datetime) -> set[str] | None:
        """The line's lane's pickable entries nobody holds (§6 rule 14): `ledger.in_lanes` on the home's readings of
        the line's repos, as the shape reads them, less every reference a live record of the repo holds a lease on.
        None where a repo could not be read — *could not look* is not *no work*."""
        roots = sorted({r.repo for r in line if r.repo and r.repo in self._repos})
        out: set[str] = set()
        graph = list(graph)
        for root in roots:
            facts = self._repos.get(root) or {}
            led = facts.get("ledger") or {}
            if "error" in led or not isinstance(led.get("entries"), list):
                return None
            if seams_mod.unserved(facts):
                continue  # an unserved repo's lane reads empty (§5 *The seams*)
            held = {
                p.ref
                for r in graph
                if r.repo == root and r.state not in DEAD and not r.superseded_by
                for p in r.progress
                if _lease(p, now)
            }
            views = [
                {"id": r.id, "name": r.name, "lane": list(r.lane), "team": r.team, "state": r.state}
                for r in line
                if r.repo == root
            ]
            got = ledger_mod.in_lanes([*led["entries"], *_orders(facts)], views, held)
            if got is None:
                continue
            for kind in ledger_mod.LANE_KINDS:
                out |= {str(i) for i in got.get(kind.replace("-", "_")) or () if i not in held}
        return out

    def _scale_short(self, members: list[Session], now: datetime) -> bool:
        """Every live member of the line busy, or unable to pick (§6 rule 14): a member holding a lease is busy; one
        `limited`, paused by the usage gate, or an extra whose start stuck (`unstuck`) with none is neither free nor
        busy; any other live member is free, and so is a kept member rule 1 is restarting — the line is not short."""
        for m in members:
            if m.state in DEAD:
                if not m.scale and self._crashed(m, now):
                    return False  # it picks on its return: a crash never reads as a short line
                continue
            if any(_lease(e, now) for e in m.progress):
                continue
            if m.state == "limited" or m.gated:
                continue
            if m.scale and _last(m).get("did") == "unstuck":
                continue
            return False
        return True

    async def _scale_line_pass(
        self,
        team: str,
        line: str,
        crew: list[Session],
        graph: list[Session],
        claims: set[str],
        now: datetime,
    ) -> None:
        key = (team, line)
        members = [r for r in crew if _of_line(r, line)]
        extras = [r for r in members if r.scale]
        await self._scale_unstick(extras, now)
        pick = self._scale_pickable(members, graph, now)
        if pick is None:
            return  # nothing read: the memory and what was held back stand for the next reading
        was = self._scale_seen.get(key)
        self._scale_seen[key] = pick
        gained = sorted(pick - was) if was is not None else []
        claimed = any(self._address(m) in claims for m in members)
        newest = max(extras, key=lambda r: str(_last(r).get("at") or ""), default=None)
        stopped = newest is not None and _last(newest).get("did") == "stopped"
        if not (gained or claimed or stopped or key in self._scale_held):
            return
        self._scale_held.discard(key)
        if not pick or not self._scale_short(members, now):
            return
        # held: closed, or exited and no crash rule 1 restarts; never one a lowered max is dropping
        held = sorted(
            (
                r
                for r in extras
                if work_mod.held_extra(r)
                and not r.scale.get("drop")
                and (r.state == "closed" or not self._crashed(r, now))
            ),
            key=lambda r: _place(r, line),
        )
        why = await self._scale_guard(team, line, crew, members, extras, held, now)
        if why is not None:
            self._scale_held.add(key)
            log.info("rule 14: %s's %s is short (%d pickable) — no fill: %s", team, line, len(pick), why)
            return
        await self._scale_fill(held[0], line, len(pick), now)

    async def _scale_unstick(self, extras: list[Session], now: datetime) -> None:
        """The guard's ten minutes (§6 rule 14): a live extra filled `SCALE_STEP` ago that has not claimed is a start
        that stuck — its `scale.last` says so (`did: unstuck`), and it holds the line's guard no more."""
        for r in extras:
            last = _last(r)
            if r.state in DEAD or last.get("did") != "fill" or _claimed(r) or _recent(last.get("at"), now, SCALE_STEP):
                continue
            log.info("%s: filled %s and not claimed in %s — the line's guard lifts", r.id, last.get("at"), SCALE_STEP)
            r.scale = {**r.scale, "last": {"at": now_iso(), "did": "unstuck", "why": "not claimed in 10 min"}}
            self._save(r)
            await self._push_changes()

    async def _scale_guard(
        self,
        team: str,
        line: str,
        crew: list[Session],
        members: list[Session],
        extras: list[Session],
        held: list[Session],
        now: datetime,
    ) -> str | None:
        """What holds a short line's fill back (§6 rule 14), in words, or None: the line's own fill ceiling, the
        team's balance mark, a gated profile, an unstaffed line, a wind-down, the one guard, no held extra to fill,
        and the host at `scale.live` with no extra seat to close for the room — that one written on the line's
        lowest-placed held extra as `did: stopped`."""
        fills = [
            e
            for r in extras
            for e in r.restarts
            if isinstance(e, dict) and e.get("why") == "fill" and _recent(e.get("at"), now, FILL_WINDOW)
        ]
        if len(fills) >= FILL_CEILING:
            return f"fill ceiling ({len(fills)} in {FILL_WINDOW})"
        mark = ((self._host_rec.get("teams") or {}).get(team) or {}).get("balance")
        if isinstance(mark, dict) and mark.get("crossed"):
            return "balance mark"
        live = [m for m in members if m.state not in DEAD]
        if not live:
            return "unstaffed"
        if team in self._finished_first or any(
            r.wrapup_at for r in crew if r.state not in DEAD and r.seat is None and not r.scale
        ):
            return "the team winds down"
        if any(r.state not in DEAD and _last(r).get("did") == "fill" and not _claimed(r) for r in extras):
            return "the last extra filled has not claimed"
        if not held:
            return "no held extra"
        extra = held[0]
        if self._profile_gated(extra.profile, now, team):
            return f"profile {extra.profile} gated"
        n = self._scale_full(extra, line, now)
        if n is not None:
            why = f"host full, {n} live"
            if _last(extra).get("did") != "stopped" or _last(extra).get("why") != why:
                extra.scale = {**extra.scale, "last": {"at": now_iso(), "did": "stopped", "why": why}}
                self._save(extra)
                await self._push_changes()
            return why
        return None

    def _scale_full(self, extra: Session, line: str, now: datetime) -> int | None:
        """The extra's host's live count where it is at `scale.live` and no clean idle extra seat can be closed for
        the room (§4.9 *The host cap*; `create`'s eviction makes the room itself where one can), else None."""
        try:
            doc = settings_mod.load()
        except Exception:  # noqa: BLE001 — an unreadable settings file caps nothing, as at the eviction
            return None
        host = extra.host or self.host
        if host == self.host:
            cap = settings_mod.live_cap(doc, host, self._machine_cap)
            live = [*self._live_here(), *(h for h in self._room_held if h)]
            pool = self._live_here()
        else:
            cap = settings_mod.live_cap(doc, host, None)
            pool = [r for r in self.remote.get(host, {}).values() if r.state not in DEAD]
            live = list(pool)
        if not cap or len(live) < cap:
            return None
        if any(self._evictable(r, now, line) for r in pool):
            return None
        return len(live)

    async def _scale_fill(self, extra: Session, line: str, pickable: int, now: datetime) -> None:
        """The fill (§6 rule 14): the held extra created from its launch record with `keep_mail`, as rule 3 fills a
        seat — a `fill` in its `restarts`, counted toward the line's extras' own `FILL_CEILING` — the record keeping
        `scale` and its `last` saying why."""
        log.info("rule 14: %s's line %s is short (%d pickable) — filling %s", extra.team, line, pickable, extra.name)
        await self._replay(extra, "fill", keep_mail=True)
        new = self.sessions.get(extra.id) if extra.host == self.host else self.remote.get(extra.host, {}).get(extra.id)
        if new is None or new is extra or not isinstance(new.scale, dict):
            return  # the replay failed, and its `restarts` entry says so: the next event reads the line again
        why = f"filled: {pickable} pickable, every {line} claimed"
        new.scale = {**new.scale, "last": {"at": now_iso(), "did": "fill", "why": why}}
        self._save(new)
        await self._push_changes()
