"""A metered account's reading at the home (design §4.4 *Usage*, §4.2a, §6 *Usage gate*; TD-151
slice 3): on every tick the adapter's `spend` for each metered profile a live session runs under,
added to the daily ledger per account (`sessionorc.spend`, `spend.json`), summed into the three
windows and served under every profile of the account as a polled reading is — `_usage`, the
`usage` event, `usage.json` — with `pct` from that profile's amount. A mixin `HostAgent` inherits.

A node runs the same pass over its own sessions, and its turns reach the home over the link as
`spend {account, profile, prices, turns, cursors}` (slice 4): the ledger and its cursors are the
home's, and the account's sums come back to the node in the reply and as `usage {account, sums}`.

Beside it, once a minute, the **seat pass** (§4.4 *Spend per seat*, TD-830): every profile a live
session runs under, a subscription's included, read with cursors of its own into `seat_spend.json`
(`sessionorc.seats`), each turn weighed and charged to a record and a reference; the `seats` RPC
reads it. Nothing gates on it. A node's seat pass sends its turns home as `seat_spend {profile,
prices, turns, cursors, roots}` (TD-833), of `spend`'s shape, and the home charges them against the
node's records it holds.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import datetime
from typing import Any

from sessionorc import adapters, agent_common, link, seats
from sessionorc import settings as settings_mod
from sessionorc import spend as spend_mod
from sessionorc.agent_common import RpcError, _usage_key, log
from sessionorc.models import PERSON, now_iso

BILLING_KEEP = 60.0  # seconds a profile's billing, read for the gate, is kept before it is read again
SEAT_EVERY = 60.0  # seconds between seat passes (§4.4 *Spend per seat*): nothing waits on it


def _offsets(held: dict[str, Any]) -> dict[str, int]:
    """`{source: offset}` from a ledger host's cursors, or a reply's plain ones."""
    out = {}
    for src, c in (held.get("cursors") or {}).items():
        v = c.get("offset") if isinstance(c, dict) else c
        if isinstance(v, int) and not isinstance(v, bool):
            out[str(src)] = v
    return out


def _amount(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v >= 0


def _metered_of(pairs: set[tuple[str, str]]) -> dict[tuple[str, str], dict[str, float]]:
    """`{(adapter, profile): prices}` for each pair whose adapter says the profile is billed
    `metered` (`billing_for`, §4.3); a pair whose adapter has no such method, or cannot say, is a
    subscription — never guessed (§4.2a)."""
    out = {}
    for name, prof in pairs:
        try:
            fn = getattr(adapters.get(name), "billing_for", None)
            b = fn(prof) if fn else None
        except Exception:  # noqa: BLE001 — an adapter's lookup never stops the tick
            b = None
        if isinstance(b, dict) and b.get("billing") == "metered":
            prices = b.get("prices")
            out[(name, prof)] = dict(prices) if isinstance(prices, dict) else {}
    return out


class SpendMixin:
    async def _refresh_spend(self) -> None:
        """One pass, detached from the tick as the usage poll is (it reads transcripts)."""
        try:
            await self._refresh_spend_inner()
        except Exception:  # noqa: BLE001 — a detached task: log it, and the next tick tries again
            log.exception("the spend pass failed")

    async def _refresh_spend_inner(self) -> None:
        # one definition of live with the quota poll (`_usage_live`), or one pass would write a reading
        # the other drops, tick after tick (the techlead's read of #681)
        live = {(s.adapter, s.profile) for s in self._usage_live()}
        metered = await asyncio.to_thread(_metered_of, live)
        self._metered = {prof for _, prof in metered}
        self._billing_seen = {p: (time.monotonic(), p in self._metered) for _, p in live}
        groups: dict[str, dict[str, Any]] = {}  # account key → {account, tool, adapter, profiles: {prof: prices}}
        for (name, prof), prices in metered.items():
            ad = adapters.get(name)
            key, account = _usage_key(ad, name, prof)
            g = groups.setdefault(
                key, {"account": account, "tool": str(getattr(ad, "label", "") or name), "ad": ad, "profiles": {}}
            )
            g["profiles"][prof] = prices
        now = datetime.now().astimezone()  # the home's own clock: its midnight, Monday and first (§4.2a)
        if self.mode == "node":
            node_sums = await self._spend_to_home(groups, now)
        else:
            node_sums = {}
            await self._spend_at_home(groups, now)
        if self.mode == "home" and now.date().isoformat() != self._spend_pruned:
            self._spend_pruned = now.date().isoformat()
            for acct in self._spend.values():
                spend_mod.prune(acct, now.date())
        whole = settings_mod.load()
        amounts = settings_mod.amounts(whole)
        changed = False
        for key, g in groups.items():
            acct = self._spend.get(key) or {}
            window_sums = node_sums[key] if self.mode == "node" else spend_mod.sums(acct, now)
            for prof in g["profiles"]:
                reading = spend_mod.reading(window_sums, amounts.get(prof) or {}, now_iso(), now)
                reading |= {"account": g["account"], "tool": g["tool"]}
                if why := self._spend_reason.get(prof):
                    reading["reason"] = why  # the chip's *spend unknown* (§4.3); the sum so far still stands
                if self.mode == "home":
                    # the person inbox is the home's: a node's accounts are noted in `_push_spend_usage`
                    self._spend_notes(acct, prof, reading)
                was = self._usage.get(prof) or {}
                if _settled(was) != _settled(reading):
                    self._usage[prof] = reading
                    changed = True
                    await self._broadcast({"event": "usage", "profile": prof, "usage": reading})
                elif prof in self._usage:
                    self._usage[prof] = (
                        reading  # the pace drifts with the clock alone: kept current, pushed with the next move
                    )
        # a metered profile no live session runs under any more leaves the top bar, as a polled one does
        shown = {p for g in groups.values() for p in g["profiles"]}
        for prof in [p for p in self._metered_shown if p not in shown and p in self._usage]:
            self._usage.pop(prof, None)
            changed = True
            await self._broadcast({"event": "usage", "profile": prof, "usage": None})
        self._metered_shown = shown
        if changed:
            self.usage_store.save(self._usage)
        if self.mode == "home":
            await self._save_spend()
            await self._push_spend_usage(now)

    async def _save_spend(self) -> None:
        """`spend.json` written when the ledger changed. The tick's pass and a node's `spend` call
        both save (TD-643): one lock makes them one writer, so the compare, the write and
        `_spend_saved` move together and the file ends as the last ledger; the thread writes a
        snapshot, never the dict the loop goes on changing."""
        async with self._spend_lock:
            text = json.dumps(self._spend, sort_keys=True)
            if text != self._spend_saved:
                await asyncio.to_thread(self.spend_store.save, json.loads(text))
                self._spend_saved = text

    async def _spend_at_home(self, groups: dict[str, dict[str, Any]], now: datetime) -> None:
        """The home reads its own transcripts into the ledger, one profile after another."""
        for key, g in groups.items():
            acct = self._spend.setdefault(key, {})
            for prof, prices in sorted(g["profiles"].items()):
                # read one profile after another, in a fixed order: two profiles sharing a directory
                # read it once, and the first by name prices its turns
                host = (acct.get("hosts") or {}).get(self.host) or {}
                r = await self._read_spend(g["ad"], prof, _offsets(host))
                if r is not None:
                    spend_mod.ingest(acct, self.host, prof, r, prices, now.date(), now.tzinfo)

    async def _read_spend(self, ad: Any, prof: str, cursors: dict[str, int]) -> dict[str, Any] | None:
        """The adapter's `spend` from `cursors`, or None with the reason kept for the chip's *spend
        unknown* (§4.3) and logged once per change."""
        try:
            r = await asyncio.to_thread(ad.spend, prof, cursors)
        except Exception as e:  # noqa: BLE001 — the adapter's failure is a reason, never the pass's
            r = {"reason": f"error: {type(e).__name__}"}
        if not isinstance(r, dict) or r.get("reason") != "ok":
            why = str((r or {}).get("reason") or "error") if isinstance(r, dict) else "error"
            if self._spend_reason.get(prof) != why:
                log.info("spend for %s: %s", prof, why)  # once per change
            self._spend_reason[prof] = why
            return None
        self._spend_reason.pop(prof, None)
        return r

    # -- a node's turns (§4.4 *Usage*, §4.4a; TD-151 slice 4) --------------------------------------

    async def _spend_to_home(self, groups: dict[str, dict[str, Any]], now: datetime) -> dict[str, Any]:
        """A node's pass: the ledger and its cursors are the home's, so each metered profile's turns
        go home as `spend {account, profile, prices, turns, cursors}` and the reply's cursors are the
        ones read from next. The first call on each link is a read (no turns, no cursors): the
        cursors the home holds for this host, whether the profile is seeded there, and the account's
        sums. While a profile is not seeded, only the cursors travel — the home takes them as the
        ends — plus the turns of transcripts it already holds a cursor for (a shared directory's
        known transcript keeps counting); a long batch goes in pieces (`spend.pieces`). Offline, or
        when a send fails, the account's figure is the home's last sums plus this node's own turns
        past its last acknowledged cursors (`spend.figure`), written nowhere. Returns each account's
        window sums, which the caller makes each profile's reading from with this node's replica of
        the amounts, as the home does."""
        mux = self._home_mux if self._snapshot_sent else None
        out: dict[str, Any] = {}
        for key, g in groups.items():
            extra: list[dict[str, Any]] = []
            for prof, prices in sorted(g["profiles"].items()):
                if mux is not None and await self._spend_send(mux, key, g, prof, prices):
                    continue
                acked = self._spend_acked.get(prof)
                if acked is None:
                    continue  # never acknowledged here: nothing to read a figure from
                r = await self._read_spend(g["ad"], prof, acked)
                if r is not None:
                    for t in r.get("turns") or ():
                        if isinstance(t, dict) and t.get("source") in acked:
                            extra.append(t | {"cost": spend_mod.cost_of(spend_mod._tokens(t), t.get("cost"), prices)})
            out[key] = spend_mod.figure(self._spend_held.get(key), extra, None, now)
        return out

    async def _spend_send(self, mux: Any, key: str, g: dict[str, Any], prof: str, prices: dict[str, float]) -> bool:
        """One profile's read and send over `mux`; False when the link failed under it, and the
        figure is then this node's to make."""
        head = {"account": key, "label": g["account"], "tool": g["tool"], "profile": prof, "prices": prices}

        async def call(turns: list[dict[str, Any]], cursors: dict[str, int]) -> dict[str, Any]:
            reply = await mux.request("spend", timeout=link.LINK_SILENCE, **head, turns=turns, cursors=cursors)
            if not isinstance(reply, dict) or not isinstance(reply.get("cursors"), dict):
                raise link.LinkError(f"a spend reply without cursors: {reply!r}")
            state = {"cursors": _offsets(reply), "seeded": bool(reply.get("seeded"))}
            self._spend_link[prof] = state
            self._spend_acked[prof] = dict(state["cursors"])
            if isinstance(reply.get("sums"), dict):
                self._spend_held[key] = reply["sums"]
            return state

        try:
            state = self._spend_link.get(prof) or await call([], {})
            r = await self._read_spend(g["ad"], prof, state["cursors"])
            if r is None:
                return True  # the adapter's reason, not the link's: the held sums stand
            turns = [t for t in r.get("turns") or () if isinstance(t, dict)]
            if not state["seeded"]:
                turns = [t for t in turns if t.get("source") in state["cursors"]]
            cursors = {s: o for s, o in (r.get("cursors") or {}).items() if isinstance(o, int)}
            if not turns and state["seeded"] and cursors == state["cursors"]:
                return True  # nothing new: the home pushes the sums when another host moves them
            for piece in spend_mod.pieces({"turns": turns, "cursors": cursors}):
                await call(piece["turns"], piece["cursors"])
        except (link.LinkError, link.LinkClosed, TimeoutError) as e:
            # nothing moved that the home did not answer for: the next pass sends it again, and the
            # home drops what it already ledgered turn by turn (§4.4)
            log.warning("spend for %s did not reach %s: %s", prof, self.home, e)
            self._spend_link.pop(prof, None)
            return False
        return True

    def _take_usage(self, params: dict[str, Any]) -> None:
        """`usage {account, sums}` from the home (§4.4a): the account's window sums, from which the
        next pass makes each profile's reading with this node's replica of the amounts."""
        if self.mode == "node" and isinstance(params.get("sums"), dict) and params.get("account"):
            self._spend_held[str(params["account"])] = params["sums"]

    async def _take_spend(self, host: str, params: dict[str, Any]) -> dict[str, Any]:
        """A node's `spend` (§4.4 *Usage*): its turns into the account's ledger at the home, under that
        host's cursors — each turn at or before the cursor held for its transcript dropped, so a
        resent batch is never counted twice — and the reply the cursors, whether the profile is
        seeded, and the account's sums. With no turns and no cursors it is a read. The home learns
        the node's accounts here, and pushes their sums to it as they move (`_push_spend_usage`)."""
        key, prof = str(params.get("account") or ""), str(params.get("profile") or "")
        turns, cursors = params.get("turns") or [], params.get("cursors") or {}
        if not key or not prof or not isinstance(turns, list) or not isinstance(cursors, dict):
            raise link.LinkError("a spend names an account and a profile, with turns and cursors")
        prices = params.get("prices") if isinstance(params.get("prices"), dict) else {}
        prices = {k: float(v) for k, v in prices.items() if _amount(v)}
        # a figure the node sent is kept only when it is one: a negative or non-finite cost or price
        # would poison the account's ledger for every host sharing it
        turns = [t | {"cost": t.get("cost") if _amount(t.get("cost")) else None} for t in turns if isinstance(t, dict)]
        now = datetime.now().astimezone()
        acct = self._spend.setdefault(key, {})
        if turns or cursors:
            spend_mod.ingest(acct, host, prof, {"turns": turns, "cursors": cursors}, prices, now.date(), now.tzinfo)
            await self._save_spend()
        named = self._spend_named.setdefault(host, {}).setdefault(key, set())
        named.add(prof)
        self._spend_node_prices[prof] = prices  # a profile only a node defines is still metered here
        window_sums = spend_mod.sums(acct, now)
        self._spend_told[(host, key)] = self._spend_mark(window_sums, named)
        h = (acct.get("hosts") or {}).get(host) or {}
        return {"cursors": _offsets(h), "seeded": prof in (h.get("seeded") or []), "sums": window_sums}

    def _spend_mark(self, window_sums: dict[str, Any], profiles: set[str]) -> str:
        """What a node's readings of an account would show: each named profile's `pct` per window
        from the amounts (the node's replica is this file) and each window's reset. A push goes when
        it changes — a whole point, or a roll (§4.4a)."""
        amounts = settings_mod.amounts(settings_mod.load())
        marks = {p: spend_mod.reading(window_sums, amounts.get(p) or {}, "")["windows"] for p in sorted(profiles)}
        return json.dumps({p: [(w["pct"], w["resets"]) for w in ws] for p, ws in marks.items()}, sort_keys=True)

    async def _push_spend_usage(self, now: datetime) -> None:
        """Each linked node's accounts, `usage {account, sums}`, where its readings moved since it was
        last told — by the home's own turns or another node's. A notification, refused not queued:
        a node whose link is down reads the sums in the reply to its first `spend` on the next dial.
        The eight-tenths note for a node's profiles is filed here, at the home, once per window."""
        amounts = settings_mod.amounts(settings_mod.load())
        noted: dict[str, set[str]] = {}
        for accounts in self._spend_named.values():
            for key, profiles in accounts.items():
                noted.setdefault(key, set()).update(profiles)
        for key, profiles in noted.items():
            if key in self._spend:
                window_sums = spend_mod.sums(self._spend[key], now)
                for prof in sorted(profiles):
                    self._spend_notes(
                        self._spend[key], prof, spend_mod.reading(window_sums, amounts.get(prof) or {}, "")
                    )
        for host, accounts in list(self._spend_named.items()):
            mux = self._link_muxes.get(host)
            if mux is None:
                continue
            for key, profiles in list(accounts.items()):
                acct = self._spend.get(key) or {}
                window_sums = spend_mod.sums(acct, now)
                mark = self._spend_mark(window_sums, profiles)
                if self._spend_told.get((host, key)) == mark:
                    continue
                try:
                    async with asyncio.timeout(agent_common.REPORT_WRITE):
                        await mux.notify("usage", account=key, sums=window_sums)
                except link.LinkClosed:
                    break
                except (link.LinkError, TimeoutError) as e:
                    log.warning("the spend sums did not reach %s: %s", host, e)
                    break
                self._spend_told[(host, key)] = mark

    def _spend_notes(self, acct: dict[str, Any], prof: str, reading: dict[str, Any]) -> None:
        """At eight tenths of an amount, one `system` note to the person inbox — *grind-api · day
        $4.10 of $5* — an FYI, uncounted, once per window (§6 *Usage gate*); the window is known by
        its `resets`, so the next day's crossing files the next note."""
        noted = acct.setdefault("noted", {})
        for w in reading["windows"]:
            pct, amount = w.get("pct"), w.get("amount")
            if not amount or not isinstance(pct, int) or pct < spend_mod.NOTE_AT:
                continue
            k = f"{prof} {w['label']}"
            if noted.get(k) == w["resets"]:
                continue
            noted[k] = w["resets"]
            got = spend_mod.spent_of(amount, {"total": w["spent"]["total"], "cost": w["spent"]["cost"]}) or 0.0
            text = f"{prof} · {w['label']} {spend_mod.say(amount, got)} of {spend_mod.say(amount, amount['value'])}"
            log.info("spend: %s", text)
            self._system_note(PERSON, text)

    # -- the seat ledger (§4.4 *Spend per seat*, TD-830) ------------------------------------------

    async def _refresh_seats(self) -> None:
        """One seat pass, detached from the tick as the spend pass is (it reads transcripts)."""
        try:
            await self._refresh_seats_inner()
        except Exception:  # noqa: BLE001 — a detached task: log it, and the next pass tries again
            log.exception("the seat pass failed")

    async def _refresh_seats_inner(self) -> None:
        """`spend(profile, seat cursors)` for every profile this host's live sessions run under, each
        turn weighed and charged (`seats.take`); a profile's first read on this host (not yet in the
        host's `seeded`) is its backfill — the fortnight before it, to `between`. `seat_spend.json` is
        written only when a turn was charged, a cursor moved or a claim was first seen. A pair whose last
        live session ended since the pass before is read once more, so that session's last minute is
        charged though nothing else runs on its profile (TD-965). A node's pass sends its turns home
        instead (`_seats_to_home`)."""
        now_live = {(s.adapter, s.profile) for s in self._usage_live()}
        live = now_live | self._seat_live
        self._seat_live = now_live
        metered = await asyncio.to_thread(_metered_of, live)
        if self.mode == "node":
            await self._seats_to_home(live, metered)
            return
        weights = settings_mod.weights(settings_mod.load())
        now = datetime.now().astimezone()  # the home's own clock, as the account ledger's days
        ledger = self._seats
        records = list(self.sessions.values())
        mine = (ledger.get("hosts") or {}).get(self.host) or {}
        held = mine.get("cursors") or {}
        seeded = set(mine.get("seeded") or ())
        first = bool(live) and "began" not in ledger
        if first:
            ledger["began"] = now_iso()
        # a claim seen by the pass that began the ledger was made before it: its entry reads partial; a
        # node's claims are seen here too, since its turns are charged here (`_take_seat_spend`)
        claimants = [*records, *(r for recs in self.remote.values() for r in recs.values())]
        moved = seats.see_claims(ledger, claimants, now_iso(), first) if live else False
        for name, prof in sorted(live):
            cursors = {
                str(src): int(c["offset"]) for src, c in held.items() if isinstance((c or {}).get("offset"), int)
            }
            r = await self._read_seats(name, prof, cursors)
            if r is None:
                continue
            backfill = prof not in seeded  # a profile's first read is its backfill, whenever it first runs
            moved = (
                seats.take(ledger, self.host, r, records, metered.get((name, prof)), weights, now, backfill) or moved
            )
            held = ledger["hosts"][self.host]["cursors"]  # a second profile on one directory reads on from here
            if backfill:
                seeded.add(prof)
                ledger["hosts"][self.host]["seeded"] = sorted(seeded)
                moved = True
        if now.date().isoformat() != self._seats_pruned:
            self._seats_pruned = now.date().isoformat()
            seats.prune(ledger, now.date())
        if moved:
            await self._save_seats()

    async def _read_seats(self, name: str, prof: str, cursors: dict[str, int]) -> dict[str, Any] | None:
        """The adapter's `spend` for `prof` from `cursors`, or None with its reason logged once per change."""
        ad = adapters.get(name)
        if not callable(getattr(ad, "spend", None)):
            return None
        try:
            r = await asyncio.to_thread(ad.spend, prof, cursors)
        except Exception as e:  # noqa: BLE001 — the adapter's failure is a reason, never the pass's
            r = {"reason": f"error: {type(e).__name__}"}
        if not isinstance(r, dict) or r.get("reason") != "ok":
            why = str(r.get("reason") or "error") if isinstance(r, dict) else "error"
            if self._seat_reason.get(prof) != why:
                log.info("seat spend for %s: %s", prof, why)  # once per change
            self._seat_reason[prof] = why
            return None
        self._seat_reason.pop(prof, None)
        return r

    # -- a node's seat turns (§4.4 *Spend per seat*, *A node's turns*; TD-833) ----------------------

    async def _seats_to_home(self, live: set[tuple[str, str]], metered: dict[tuple[str, str], Any]) -> None:
        """A node's seat pass: the seat ledger and its cursors are the home's, which holds this node's
        records, so each profile's turns go home as `seat_spend {profile, prices, turns, cursors,
        roots}` and the reply's cursors are the ones read from next — `spend`'s road (§4.4a). The first
        call on each link is a read; while the profile is not seeded on this host only the cursors
        travel (the transcripts' ends), with the turns of a transcript the home already holds; a long
        batch goes in pieces. `roots` is each turn's `cwd`'s worktree, read on this node's disk, where
        the record's `dir` is. Offline nothing is read: the turns wait in the transcripts, from the
        home's cursors, for the next dial."""
        mux = self._home_mux if self._snapshot_sent else None
        if mux is None:
            return
        for name, prof in sorted(live):
            prices = metered.get((name, prof))

            async def call(turns: list[dict[str, Any]], cursors: dict[str, int], prof: str = prof, prices=prices):
                roots = {c: seats.worktree_root(c) for c in sorted({str(t.get("cwd") or "") for t in turns}) if c}
                reply = await mux.request(
                    "seat_spend", timeout=link.LINK_SILENCE, profile=prof, prices=prices, turns=turns, cursors=cursors,
                    roots=roots,
                )  # fmt: skip
                if not isinstance(reply, dict) or not isinstance(reply.get("cursors"), dict):
                    raise link.LinkError(f"a seat_spend reply without cursors: {reply!r}")
                state = {"cursors": _offsets(reply), "seeded": bool(reply.get("seeded"))}
                self._seat_link[prof] = state
                return state

            try:
                state = self._seat_link.get(prof) or await call([], {})
                r = await self._read_seats(name, prof, state["cursors"])
                if r is None:
                    continue
                turns = [t for t in r.get("turns") or () if isinstance(t, dict)]
                if not state["seeded"]:
                    turns = [t for t in turns if t.get("source") in state["cursors"]]
                cursors = {s: o for s, o in (r.get("cursors") or {}).items() if isinstance(o, int)}
                if not turns and state["seeded"] and cursors == state["cursors"]:
                    continue
                for piece in spend_mod.pieces({"turns": turns, "cursors": cursors}):
                    await call(piece["turns"], piece["cursors"])
            except (link.LinkError, link.LinkClosed, TimeoutError) as e:
                # the home drops what it already charged turn by turn: the next pass sends it again
                log.warning("seat spend for %s did not reach %s: %s", prof, self.home, e)
                self._seat_link.pop(prof, None)

    async def _take_seat_spend(self, host: str, params: dict[str, Any]) -> dict[str, Any]:
        """A node's `seat_spend` (TD-833): its turns into the seat ledger under that host's cursors,
        each owned among the node's records the home holds and charged as the home's own are — a turn
        at or before its transcript's cursor dropped, so a resent batch is never charged twice. While
        the profile is not seeded on that host, a transcript the home holds no cursor for takes its end
        and charges nothing (the seeding sends cursors alone), and the call seeds it. With no turns and
        no cursors it is a read; the reply is the cursors and whether the profile is seeded."""
        prof = str(params.get("profile") or "")
        turns, cursors = params.get("turns") or [], params.get("cursors") or {}
        roots = params.get("roots") if isinstance(params.get("roots"), dict) else {}
        if not prof or not isinstance(turns, list) or not isinstance(cursors, dict):
            raise link.LinkError("a seat_spend names a profile, with turns and cursors")
        raw = params.get("prices")
        prices = {k: float(v) for k, v in raw.items() if _amount(v)} if isinstance(raw, dict) else None
        turns = [t | {"cost": t.get("cost") if _amount(t.get("cost")) else None} for t in turns if isinstance(t, dict)]
        ledger = self._seats
        h = ledger.setdefault("hosts", {}).setdefault(host, {})
        seeded = set(h.get("seeded") or ())
        if turns or cursors:
            if prof not in seeded:
                held = h.get("cursors") or {}
                turns = [t for t in turns if t.get("source") in held]  # a known transcript keeps counting
            if "began" not in ledger:
                ledger["began"] = now_iso()
            records = list((self.remote.get(host) or {}).values())
            seats.see_claims(ledger, records, now_iso())
            seats.take(
                ledger, host, {"turns": turns, "cursors": cursors}, records, prices,
                settings_mod.weights(settings_mod.load()), datetime.now().astimezone(),
                root_of=lambda cwd: str(roots.get(cwd) or seats.ROOT_GONE),
            )  # fmt: skip
            h = ledger["hosts"][host]
            h["seeded"] = sorted(seeded | {prof})
            await self._save_seats()
        return {"cursors": _offsets(h), "seeded": prof in (h.get("seeded") or [])}

    async def _save_seats(self) -> None:
        """`seat_spend.json` written when it changed: one writer (the pass, and a `done` that lands),
        a snapshot written off the loop."""
        async with self._seats_lock:
            text = json.dumps(self._seats, sort_keys=True)
            if text != self._seats_saved:
                await asyncio.to_thread(self.seat_store.save, json.loads(text))
                self._seats_saved = text

    async def _seat_spend_done(self, s: Any, ref: str, claimed_at: str | None) -> None:
        """A plain `ao progress done` landed (§4.4 *Spend per seat*): the reference's `done_at`, and its
        `first_claimed` from the claim when no pass saw it."""
        seats.done(self._seats, s.repo, ref, claimed_at, now_iso())
        await self._save_seats()

    async def rpc_seats(
        self, window: str = "day", team: str | None = None, by: str | None = None, at: str | None = None
    ) -> dict[str, Any]:
        """The seat ledger's reading (design §4.4 *Spend per seat*, §4.7 `ao spend`; TD-830, TD-859): over a
        `day`, `week` or `month`, `at` its first day, per seat (per record under `by: record`), per role,
        team and repo, per finished entry, and *outside shiftlead*; the window's `series`, the `teams`
        against the previous period and the `top` seats; `unknown` the profiles whose spend could not be
        read, whose seats read *spend unknown*. Read-only, and open to a session."""
        if by not in (None, "", "seat", "record"):
            raise RpcError(f"seats by seat or record, not {by!r}")
        now = datetime.now().astimezone()
        try:
            out = seats.reading(
                self._seats,
                window,
                now,
                team or None,
                by or None,
                settings_mod.weights(settings_mod.load()),
                at=at or None,
            )
        except ValueError as e:
            raise RpcError(str(e)) from None
        return out | {"unknown": dict(sorted(self._seat_reason.items()))}

    def _is_metered(self, profile: str) -> bool:
        """Whether `profile` is billed `metered`, known **before** the gate judges (§4.4: keyed on the
        billing, read before the windows): from the spend pass when it has run, else asked of the
        adapter of any record running under it and kept for `BILLING_KEEP`. After a restart the gate
        runs before the detached pass has, and a profile read as a subscription would lose its
        amounts and lift every pause made at them (the techlead's read of #681)."""
        seen = self._billing_seen.get(profile)
        if seen is not None and time.monotonic() - seen[0] < BILLING_KEEP:
            return seen[1]
        records = [*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values())]
        pairs = {(r.adapter, r.profile) for r in records if r.profile == profile and adapters.has_agent(r.adapter)}
        metered = bool(_metered_of(pairs))
        self._billing_seen[profile] = (time.monotonic(), metered)
        return metered

    def _gate_reserves(self, whole: dict[str, Any], profile: str) -> dict[str, Any] | None:
        """The reserves the gate reads for `profile`: a subscription profile's percents, or — for a
        metered one — a line at the amount itself on each window that has one (§6 *Usage gate*:
        the amount is the window's 100, and a team's priority lowers it), since its `pct` is
        already the spend over the amount. Keyed on the profile's billing, never on the reading."""
        if self._is_metered(profile):
            by_label = settings_mod.amounts(whole).get(profile)
            return {label: 0 for label in by_label} if by_label else None
        return settings_mod.reserves(whole).get(profile)

    def _billing_of(self, profile: str) -> dict[str, Any] | None:
        """`{billing, prices}` when `profile` is billed `metered`, else None — asked of the adapter of
        any record running under it, and with none of every adapter this host knows, so a person can
        set an amount before the profile's first session (`set_settings`, §6 *Usage gate*). A profile
        no adapter here resolves but a node's `spend` has named is metered, at the prices the node
        declared: the home's `profiles.yml` need not define a node's profile, and one it does define
        keeps the billing it gives it. The gate is unchanged: a node's sessions are judged at the node,
        whose own adapters know the profile."""
        records = [*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values())]
        names = sorted({r.adapter for r in records if r.profile == profile and adapters.has_agent(r.adapter)})
        known = False  # an adapter here resolved the profile: its word stands over any node's
        for name in names or adapters.names():
            try:
                fn = getattr(adapters.get(name), "billing_for", None)
                b = fn(profile) if fn else None
            except Exception as e:  # noqa: BLE001 — an adapter's lookup never stops the write
                log.warning("billing_for %s on %s failed: %s — read as a subscription", profile, name, e)
                b = None
            if isinstance(b, dict) and b.get("billing") == "metered":
                return {"billing": "metered", "prices": dict(b.get("prices") or {})}
            known = known or isinstance(b, dict)
        if not known and profile in self._spend_node_prices:
            return {"billing": "metered", "prices": dict(self._spend_node_prices[profile])}
        return None


def _settled(reading: dict[str, Any]) -> dict[str, Any]:
    """A metered reading less what moves with the clock alone — `fetched` and each window's `pace`
    (TD-151) — so a usage event goes when the spend, a percent or a reset moves, not on every tick."""
    out = {k: v for k, v in reading.items() if k not in ("fetched", "windows")}
    out["windows"] = [
        {k: v for k, v in w.items() if k != "pace"} if isinstance(w, dict) else w for w in reading.get("windows") or []
    ]
    return out
