"""The rank's moves and their flush at the home (design §4.4 *The Queue*: *A move lands*, §4.7 `ao rank`,
TD-769): `rank_move` keeps a move as an intent in `ranks.json`, the `queue` reading serves the order with
the intents applied, and each tick flushes what is due — the moves `RANK_FLUSH` after the last one, the
joins and prunes `RANK_FLUSH` after they were found — one PR per repo per kind, by the board's road. The
pure half is `sessionorc.rank`. A mixin `HostAgent` inherits.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from sessionorc import board as board_mod
from sessionorc import ledger as ledger_mod
from sessionorc import ledgerboard as lb
from sessionorc import mail
from sessionorc import rank as rank_mod
from sessionorc.agent_common import RpcError, log
from sessionorc.models import now_iso

KINDS = ("rank", "join", "prune")  # a flush's PRs, each kind its own (§4.4 *The rank file*)
# A landed move's key stands in for its card's until the home's reading shows it (the checkout pulled), or this long
LANDED_KEEP = 3600.0


class RankMixin:
    def _rank_init(self) -> None:
        self.rank_store = rank_mod.RankStore()
        self._rank_task: asyncio.Task[None] | None = None

    def _rank_caller(self, caller: Any) -> str:
        """A move is the person's and an interactive session's (§4.4 *A move lands*): the person, the
        person's own shell and a session whose record is not `unattended` pass; an unattended one, and a
        caller the graph does not hold, are refused, since the rank is the person's."""
        if mail.is_person(caller):
            return "person"
        r = self._graph().get(caller) if isinstance(caller, str) else None
        if r is None:
            raise RpcError(
                f"a move on the rank is the person's and an interactive session's: {caller} is not a session this "
                "home holds (design §4.4 *A move lands*)"
            )
        if r.unattended:
            raise RpcError(
                f"a move on the rank is the person's and an interactive session's: {caller} is unattended, and the "
                "rank is the person's (design §4.4 *A move lands*)"
            )
        return str(caller)

    def _pending_keys(self, cards: list[dict[str, Any]], state: Mapping[str, Any]) -> dict[str, str]:
        """Card id → the key a landed move gave it that the reading does not show yet, then the key its
        intents give it, re-derived now, in the order they were made."""
        keys = _landed(cards, state)
        for it in state["intents"]:
            try:
                rank_mod.derive(it, cards, keys)
            except rank_mod.Refused:
                continue
        return keys

    async def rpc_rank_move(
        self,
        ids: list[str] | None = None,
        prev: str | None = None,
        next: str | None = None,
        scope: str | None = None,
        caller: Any = None,
    ) -> dict[str, Any]:
        """`ao rank` and the Queue's move (design §4.4 *A move lands*, §4.7, §4.5a *Queue page, Up next*): the
        card holding `ids` (`<repo>#TD-n` each) goes between the Up next cards holding `prev` (none: the top)
        and `next` (none: the end), kept as an intent and landed by the flush `RANK_FLUSH` after the last move.
        A move from a Repo page carries `scope`, the repo: its neighbours are adjacent among that repo's Up
        next cards, not the whole order's (`rank.intent`, TD-901). Refused to an unattended session; refused
        for an id no open card holds, a card In progress, or a neighbour not in Up next. Returns `{moved, card,
        entries, place, prev, next, flush}` — `moved` false for a move that leaves the card where it is, which
        lands nothing."""
        by = self._rank_caller(caller)
        # the order as the page draws it, the moves not yet landed applied: the neighbours are that order's
        shown = list(self._queue_ranked(self._queue or {}).get("cards") or [])
        cards = list((self._queue or {}).get("cards") or [])
        want = [str(q) for q in ids or () if q]
        with self.rank_store.lock:
            state = self.rank_store.load()
            try:
                it = rank_mod.intent(shown, want, prev or None, next or None, by, now_iso(), scope=scope or None)
            except rank_mod.Refused as e:
                raise RpcError(str(e)) from None
            card = rank_mod.card_of(cards, want[0]) or {}
            if it is not None:
                state["intents"].append(it)
                state["moved_at"] = time.time()
                self.rank_store.save(state)
        keys = self._pending_keys(cards, state)
        if it is not None and self._queue:  # applied on the page at once (§4.4 *A move lands*)
            await self._broadcast({"event": "queue", "queue": self._queue_ranked(self._queue)})
        log.info(
            "rank_move by %s: %s between %s and %s%s%s",
            by, want, prev, next, f" in {scope}" if scope else "", "" if it else " (where it is)",
        )  # fmt: skip
        return {
            "moved": it is not None,
            "card": card.get("id"),
            "entries": len(card.get("order") or ()),
            "place": rank_mod.place(cards, str(card.get("id")), keys),
            "prev": prev or None,
            "next": next or None,
            "flush": rank_mod.RANK_FLUSH,
        }

    def _queue_ranked(self, got: dict[str, Any]) -> dict[str, Any]:
        """The `queue` reading with the intents not yet landed applied (§4.4 *A move lands*: applied on the
        page at once): each moved card at its new key and marked `pending`, the order and the Up next places
        (`rank.number`) again, and `not_landed` on a card whose rank PR failed after its retry."""
        cards = got.get("cards") or []
        if not cards:
            return got
        state = self.rank_store.load()
        if not state["intents"] and not state["not_landed"] and not state["landed"]:
            return got
        keys = self._pending_keys(cards, state)
        landed = _landed(cards, state)
        out = []
        for c in cards:
            c = dict(c)
            if c["id"] in keys:
                c["key"] = keys[c["id"]]
                if landed.get(c["id"]) != c["key"]:  # an intent's, not yet landed; a landed key only stands in
                    c["pending"] = True
            if c["id"] in state["not_landed"]:
                c["not_landed"] = state["not_landed"][c["id"]]
            out.append(c)
        out = [c for c in rank_mod.order(out) if c.get("group") != "up_next"] + [
            c for c in rank_mod.order(out) if c.get("group") == "up_next"
        ]
        rank_mod.number(out)
        return {**got, "cards": out}

    def _rank_repos(self) -> dict[str, tuple[str, str, Mapping[str, Any]]]:
        """Repo name (as the Queue names it) → (checkout root, the rank file's path in it, its ledger reading),
        taken on the event loop so the flush's thread never reads `self._repos` while a tick replaces it."""
        out: dict[str, tuple[str, str, Mapping[str, Any]]] = {}
        for root, v in self._repos.items():
            led = (v or {}).get("ledger") if isinstance(v, Mapping) else None
            if not isinstance(led, Mapping) or not led.get("path"):
                continue
            name = str(v.get("name") or Path(root).name)
            out.setdefault(name, (str(v.get("root") or root), lb.rank_path(str(led["path"])), led))
        return out

    def _rank_found(self, cards: list[dict[str, Any]], repos: Mapping[str, tuple[str, str, Any]]) -> dict[str, Any]:
        """The joins and prunes the rank files and the cards call for now (`{qid: key or None}`)."""
        return {**rank_mod.joins(cards), **rank_mod.prunes(cards, self._rank_lined(repos))}

    async def _rank_pass(self, now: datetime) -> None:
        """Each tick at the home: start a flush when one is due (§4.4 *A move lands*) — the moves
        `RANK_FLUSH` after the last one, a join or a prune `RANK_FLUSH` after it was first found. One flush
        at a time, detached as the promote's refresh is; a surprise is a log line, and the next tick tries."""
        if self._rank_task is not None and not self._rank_task.done():
            return
        cards = list((self._queue or {}).get("cards") or [])
        if not cards:
            return
        try:
            repos = self._rank_repos()
            found = self._rank_found(cards, repos)
            if _signature(found) == self.rank_store.load()["flushed"]:
                found = {}  # what the last flush wrote, or found already said: the checkout has not caught up yet
            t = time.time()
            with self.rank_store.lock:
                state = self.rank_store.load()
                shown = {c["id"]: c.get("key") for c in cards}
                kept = {
                    cid: v
                    for cid, v in state["landed"].items()
                    if cid in shown and shown[cid] != v.get("key") and t - float(v.get("at") or 0) < LANDED_KEEP
                }
                if kept != state["landed"]:  # the reading shows it now, or the card is gone, or it is too old
                    state["landed"] = kept
                    self.rank_store.save(state)
                if found and state["found_at"] is None:
                    state["found_at"] = t
                    self.rank_store.save(state)
                elif not found and state["found_at"] is not None:
                    state["found_at"] = None
                    self.rank_store.save(state)
            due = (state["intents"] and t - float(state["moved_at"] or 0) >= rank_mod.RANK_FLUSH) or (
                found and t - float(state["found_at"] or t) >= rank_mod.RANK_FLUSH
            )
        except Exception:  # noqa: BLE001 — the rank is a convenience: the next tick looks again
            log.exception("looking for a rank flush failed")
            return
        if due:
            self._rank_task = asyncio.create_task(self._rank_run(cards, repos))

    async def _rank_run(self, cards: list[dict[str, Any]], repos: Mapping[str, tuple[str, str, Any]]) -> None:
        """The flush off the event loop, then the page told what it changed (`pending` gone, `not_landed`)."""
        try:
            await asyncio.to_thread(self._rank_flush, cards, repos)
        except Exception:  # noqa: BLE001 — the intents stay for the next flush
            log.exception("the rank flush failed")
        if self._queue:
            await self._broadcast({"event": "queue", "queue": self._queue_ranked(self._queue)})

    def _rank_flush(self, cards: list[dict[str, Any]], repos: Mapping[str, tuple[str, str, Any]]) -> None:
        """One flush (§4.4 *A move lands*): every intent re-derived against `cards` in the order made, its
        lines landed as one `queue: rank` PR per repo; then the joins and the prunes, each kind a PR per
        repo. A repo whose rank PR fails after its retry keeps every intent that touches it, retried at the
        next flush, and its cards read *not landed*; an intent that no longer derives is dropped."""
        with self.rank_store.lock:
            state = self.rank_store.load()
        # the moves only once `RANK_FLUSH` has passed since the last one, so a run of drags lands as one PR
        # even when a join or a prune comes due in the middle of it
        due = state["intents"] and time.time() - float(state["moved_at"] or 0) >= rank_mod.RANK_FLUSH
        taken = list(state["intents"]) if due else []
        keys = _landed(cards, state)  # a move derives against the keys landed moves gave, not the stale reading
        lines: dict[str, str | None] = {}
        made: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for it in taken:
            try:
                got = rank_mod.derive(it, cards, keys)
            except rank_mod.Refused as e:
                log.warning("a rank move by %s is dropped: %s", it.get("by"), e)
                continue
            if got is None:
                continue  # every member archived since the move
            card, key = got
            lines.update({q: key for q in card.get("order") or ()})
            made.append((it, card))
        failed: dict[str, str] = {}
        missed = False  # a join or a prune that did not land: found again at the next tick
        batches = (
            ("rank", lines),
            ("join", rank_mod.joins(cards, keys)),
            ("prune", rank_mod.prunes(cards, self._rank_lined(repos))),
        )
        for kind, want in batches:
            for repo, ls in rank_mod.by_repo(want).items():
                if repo not in repos:
                    continue  # a repo the home no longer reads: nothing to write
                root, rel, _ = repos[repo]
                try:
                    got = board_mod.land_rank(root, rel, ls, lb.queue_subject(rank_mod.TOOL, kind, list(ls)))
                except Exception as e:  # noqa: BLE001 — a refusal, or gh or git failing under it: kept, retried
                    log.warning("the %s flush of %s did not land: %s", kind, repo, e)
                    if kind == "rank":
                        failed[repo] = str(e)
                    missed = missed or kind != "rank"
                    continue
                if got:
                    log.info("rank flush %s %s: PR #%s", kind, repo, got.get("pr"))
        keep = [it for it, card in made if set(card.get("repos") or ()) & failed.keys()]
        t = time.time()
        with self.rank_store.lock:
            state = self.rank_store.load()
            later = [i for i in state["intents"] if i not in taken]  # moves made while this flush ran
            state["intents"] = keep + later
            state["not_landed"] = {
                str(card["id"]): "; ".join(failed[r] for r in card.get("repos") or () if r in failed)
                for it, card in made
                if it in keep
            }
            for it, card in made:
                if it not in keep:  # landed: its key stands in until the reading shows it
                    state["landed"][str(card["id"])] = {"key": keys[card["id"]], "at": t}
            state["found_at"] = None
            state["flushed"] = [] if missed else _signature(self._rank_found(cards, repos))
            if keep and not later:
                state["moved_at"] = t  # retried at the next flush, `RANK_FLUSH` on, never every tick
            elif not state["intents"]:
                state["moved_at"] = None
            self.rank_store.save(state)

    def _rank_lined(self, repos: Mapping[str, tuple[str, str, Any]]) -> dict[str, list[str]]:
        """Repo name → the ids its checkout's rank file gives a line that are open or archived — what a prune
        may weigh. A repo whose ledger reading failed or holds no entry, or whose archive cannot be read, is
        left out: a reading that is missing must never read as every line's card archived."""
        out: dict[str, list[str]] = {}
        for name, (root, rel, led) in repos.items():
            if led.get("error") or not led.get("entries"):
                continue
            try:
                lined = rank_mod.lined_ids((Path(root) / rel).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            archive = ledger_mod.read_pair(str(led["path"]), ledger_mod.fs_io(root))[2]  # either layout
            if archive is None:
                continue
            known = ledger_mod.ids_in(archive) | {str(e.get("id")) for e in led["entries"]}
            out[name] = [t for t in lined if t in known]
        return out


def _signature(found: Mapping[str, str | None]) -> list[list[Any]]:
    """The joins and prunes found, as `ranks.json` keeps them."""
    return [[q, k] for q, k in sorted(found.items())]


def _landed(cards: list[dict[str, Any]], state: Mapping[str, Any]) -> dict[str, str]:
    """Card id → the key a landed move gave it, for a card the reading still shows at another key."""
    shown = {c["id"]: c.get("key") for c in cards}
    return {
        cid: str(v["key"])
        for cid, v in (state.get("landed") or {}).items()
        if cid in shown and isinstance(v, dict) and v.get("key") and shown[cid] != v["key"]
    }
