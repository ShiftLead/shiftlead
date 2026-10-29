"""The home merges a mechanical sync PR (design §6 *Sync*, TD-681, built by TD-685 slice 2): the pass,
in the promote's pass and on its full cadence, over every checkout in the registry — declining what is
not the home's, `sync.judge` (the check, the SHIP comment, the gate) off the loop, then the holders and
the head read again and the merge pinned to the head. Its outcome is the repo reading's `sync`, which
`_red_prs` reads through `sync.mark`. A mixin `HostAgent` inherits; the state it reads is the agent's.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc import cadence, hosts, workorders
from sessionorc import promote as promote_mod
from sessionorc import seams as seams_mod
from sessionorc import settings as settings_mod
from sessionorc import sync as sync_mod
from sessionorc.agent_common import log
from sessionorc.mail import PERSON
from sessionorc.models import now_iso

# How long a pass's cover holds a green sync PR back from the order (§6 *Sync*): three full readings. A home
# whose pass stopped covering a repo (no `gh` login, a read failing, a surprise) leaves it the team's.
SYNC_COVER = timedelta(seconds=3 * 300)


class SyncMixin:
    @staticmethod
    def _sync_on() -> dict[str, bool]:
        """`repos.<repo>.sync.auto` from `settings.yml`; a repo absent is on (§6 *Sync*, as `pull` is)."""
        repos = settings_mod.repos(settings_mod.load())
        return {name: bool((v.get("sync") or {}).get("auto", True)) for name, v in repos.items()}

    def _sync_covers(self, root: str, on: bool, now: datetime) -> bool:
        """Whether the home holds this repo's green unjudged sync PRs back from the order: the switch on and a
        pass that covered the repo whole inside `SYNC_COVER`."""
        ran = self._sync_ran.get(root)
        return on and ran is not None and now - ran <= SYNC_COVER

    def _sync_held_by(self, root: str, pr: dict[str, Any]) -> bool:
        """Whether a live record of the repo holds the PR (§4.4's test), read now."""
        return any(workorders.holds_pr(r, pr) for r in self._graph().values() if r.repo == root)

    async def _sync_pass(self) -> None:
        """One pass at the home: each registered checkout's open sync PRs. One repo's surprise is a log line."""
        if self.mode != "home":
            return
        clones = hosts.local_host().repos()
        on = await asyncio.to_thread(self._sync_on)
        for root in list(self._repos):
            try:
                await self._sync_repo(root, on.get(Path(root).name, True), clones)
            except Exception:  # noqa: BLE001 — the next pass tries again
                log.exception("sync: the pass over %s failed", root)

    async def _sync_repo(self, root: str, auto: bool, clones: list[Any]) -> None:
        reading = self._repos.get(root) or {}
        prs_r = reading.get("prs") or {}
        if prs_r.get("error"):
            return  # an outage is never zero PRs: nothing is pruned or judged on it
        prs = [p for p in prs_r.get("open") or [] if isinstance(p, dict)]
        old = reading.get("sync") or {}
        sync = sync_mod.prune(old, prs)
        if await asyncio.to_thread(cadence.gate, root) is None or seams_mod.unserved(
            reading, but=("age", "ledger_age")
        ):
            # unserved by any lack but an older tree (or one too old for a v2 ledger), which the sync cures: its
            # PRs are the person's — not read, nothing written (§6 *Sync*, TD-1018)
            pass
        elif not auto:
            for pr in prs:
                n, head = str(pr.get("number")), str(pr.get("head") or "")
                e = sync.get(n) or {}
                if e.get("verdict") == "off" and e.get("head") == head:
                    continue  # already *off* at this head: nothing rewritten, nothing pushed
                if pr.get("sync") is True and head and not sync_mod.settled(sync.get(n), head):
                    sync[n] = {"head": head, "verdict": "off", "why": "sync is off", "tries": 0,
                               "at": now_iso()}  # fmt: skip
        else:
            covered, repo = True, Path(root).name
            # where the repo sets `precheck`, a PR reading *none* is prechecked before its gate (§6 step 4, TD-1039)
            want = f"origin/{await asyncio.to_thread(workorders.default_branch, Path(root))}"
            command, unread = await asyncio.to_thread(cadence.precheck_command, root, want)
            prechecks, counted = bool(command), None
            if unread:  # no reading of `precheck`: nothing starts; a PR waiting on its precheck keeps its clock, and
                # the pass covers nothing, so it is the team's again rather than held without end (§6 *Sync*)
                covered = not any(
                    sync_mod.waiting(sync.get(str(p.get("number"))), str(p.get("head") or "")) for p in prs
                )
            elif not prechecks:  # `precheck` unset since: nothing waits on a precheck the pass will not start
                sync = {n: {k: v for k, v in e.items() if k != "waiting_since"} for n, e in sync.items()}
            else:
                async with self._promote_lock:
                    counted = await asyncio.to_thread(sync_mod.tend_precheck, root, repo, prs, sync, now_iso())
            for pr in sync_mod.candidates(prs, sync, lambda p: self._sync_held_by(root, p), prechecks):
                n, head = str(pr["number"]), str(pr["head"])
                if not self._sync_login:
                    self._sync_login = await asyncio.to_thread(sync_mod.gh_login)
                    if not self._sync_login:
                        log.warning("sync: the home's gh login could not be read; nothing judged this pass")
                        covered = False
                        break  # no reading: no verdict on anyone
                if why := sync_mod.decline(pr, self._sync_login):
                    sync[n] = {"head": head, "verdict": "refused", "why": why, "tries": 0,
                               "at": now_iso()}  # fmt: skip
                    continue
                if prechecks and sync_mod.unprechecked(pr):
                    e = await self._sync_precheck(root, pr, sync.get(n), clones, n == counted)
                    if e is not None:
                        sync[n] = e
                    continue  # a wait holds no task: the pass goes on
                e = await asyncio.to_thread(sync_mod.judge, root, pr, sync.get(n), clones, now_iso())
                if e is None:
                    continue  # the head moved: the next pass checks the new one
                if e.pop("ready", False):
                    e = await self._sync_merge(root, pr, e)
                if e is not None:
                    sync[n] = e
            if covered:
                self._sync_ran[root] = datetime.now(UTC)
        if sync != old and (cur := self._repos.get(root)) is not None:
            self._repos[root] = {**cur, "sync": sync}  # never the snapshot: a re-read may have landed
            self.repos_store.save(self._repos)
            await self._broadcast({"event": "repos", "root": root, "repo": self._repo_view(root)})

    async def _sync_precheck(
        self, root: str, pr: dict[str, Any], entry: dict[str, Any] | None, clones: list[Any], counted: bool
    ) -> dict[str, Any] | None:
        """Step 4's precheck on a PR reading *none* (§6 *Sync*, TD-1039): a run going, or a checkout that cannot
        run it, waits uncounted without the check; else steps 1 to 3, and a mechanical PR's `precheck.py --pr`
        is started detached under the promote lock, the blockers read again there. A wait past
        `SYNC_PRECHECK_WAIT` at the head is *refused*. None for a head that moved."""
        repo, head, at = Path(root).name, str(pr["head"]), now_iso()
        if counted:  # its run ended this pass with nothing recorded: a later pass may start another
            return sync_mod.wait_entry(entry, head, (entry or {}).get("why") or "", at)
        if why := await asyncio.to_thread(sync_mod.precheck_blocked, root, repo):
            return sync_mod.wait_entry(entry, head, why, at)
        e = await asyncio.to_thread(sync_mod.judge, root, pr, entry, clones, at, precheck=True)
        if e is None or not e.pop("prestart", False):
            return e  # moved, refused, or no reading (counted, as any check's)
        async with self._promote_lock:
            why = await asyncio.to_thread(sync_mod.precheck_blocked, root, repo)
            if not why:
                try:
                    started, why = await asyncio.to_thread(
                        promote_mod.start_precheck_pr, root, repo, int(pr["number"]), head
                    )
                except OSError as err:
                    started, why = None, f"precheck.py could not be started: {err}"
                if started is not None:
                    why = f"prechecking {head[:7]}"
                    log.info("sync: %s #%s: prechecking %s", repo, pr["number"], head[:7])
        return sync_mod.wait_entry(e, head, why or "", at)

    async def _sync_merge(self, root: str, pr: dict[str, Any], e: dict[str, Any]) -> dict[str, Any] | None:
        """Step 5: the holders and the head read again just before the merge. A new holder drops the merge
        with no verdict; a moved head drops it unwritten; the merge pinned with `--match-head-commit`."""
        n, head = int(pr["number"]), str(pr["head"])
        if not (await asyncio.to_thread(self._sync_on)).get(Path(root).name, True):
            return e  # turned off while the pass ran: nothing merged
        if self._sync_held_by(root, pr):
            return e  # no verdict: back on the list once the claim ends
        now = await asyncio.to_thread(cadence.head, root, n)
        if now is None:
            return sync_mod._no_reading(e, "the PR's head could not be read before the merge", now_iso())
        if now != (head, "open"):
            return None
        if why := await asyncio.to_thread(sync_mod.merge, root, n, head):
            if await asyncio.to_thread(cadence.head, root, n) not in (None, (head, "open")):
                return None  # the head moved under the merge: the forge's match refused it, and nothing is written
            return sync_mod._no_reading(e, f"the merge was refused: {why}", now_iso())
        repo = Path(root).name
        text = f"merged {repo} #{n} — bump of the dev-cadence pin to {(e.get('commit') or '?')[:7]}"
        self._system_note(PERSON, text)
        log.info("sync: %s", text)
        return {**e, "verdict": "merged", "why": "", "at": now_iso()}
