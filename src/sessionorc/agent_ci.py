"""CI that never started is the person's (design §4.4, TD-682, built by TD-687 slice 1): the home's
**spells** — one per GitHub account `workorders.ci_not_run` groups, kept as `ci_spells` on the `host`
record and stepped once per successful repo reading, after the runs a **Re-run** asked for are read —
and `ci_rerun`, the *CI not starting* row's **Re-run** (§4.5a), a person's own act served by the home
alone. The Telegram line is `agent_notify`'s, which reads the spells. A mixin `HostAgent` inherits;
the state it reads is the agent's.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sessionorc import agent_common, reports, workorders
from sessionorc.agent_common import GH_TIMEOUT, RpcError, log
from sessionorc.models import now_iso


async def _read_runs(spells: dict[str, dict[str, Any]], timeout: float) -> dict[str, dict[str, Any]]:
    """Each spell's pending re-run runs read again (`gh api …/actions/runs/<run>`, each bounded, all at
    once): a run read `completed` is no longer pending, and one that cannot be read stays pending."""
    pending = [
        (key, i, r)
        for key, spell in spells.items()
        for i, r in enumerate(((spell.get("rerun") or {}).get("runs") or []) if isinstance(spell, dict) else [])
        if isinstance(r, dict) and r.get("pending")
    ]
    got = await asyncio.gather(
        *(asyncio.to_thread(reports.run_status, str(r.get("root") or ""), int(r.get("run") or 0), timeout)
          for _, _, r in pending)
    )  # fmt: skip
    out = {key: dict(spell) for key, spell in spells.items()}
    for (key, i, r), status in zip(pending, got, strict=True):
        rerun = out[key]["rerun"] = dict(out[key]["rerun"])
        runs = rerun["runs"] = list(rerun["runs"])
        runs[i] = {**r, "pending": status != workorders.RUN_DONE}
    return out


class CiMixin:
    def _ci_spells_view(self) -> dict[str, Any]:
        """`ci_spells` on `host`: `{<owner>: {owner, since, clear, row, rerun?}}`, keyed in lower case."""
        return {k: dict(v) for k, v in sorted((self._host_rec.get("ci_spells") or {}).items())}

    async def _ci_spells_step(self) -> None:
        """One successful repo reading's step of the spells (design §4.4 *Its spell*), at the home: the
        re-run's runs read first, so a spell never ends on a count taken before their outcome, then
        `workorders.ci_spells` over `ci_not_run`. A change is saved to the `host` record, which the page reads."""
        if self.mode != "home":
            return
        try:
            async with self._ci_lock():  # a press and a step never interleave: neither loses the other's write
                await self._ci_spells_step_locked()
        except Exception:  # noqa: BLE001 — one reading's surprise is a log line; the next reading steps again
            log.exception("stepping the CI spells failed")

    def _ci_lock(self) -> asyncio.Lock:
        lock = getattr(self, "_ci_lock_obj", None)
        if lock is None:
            lock = self._ci_lock_obj = asyncio.Lock()
        return lock

    async def _ci_spells_step_locked(self) -> None:
        old = self._host_rec.get("ci_spells") or {}
        read = await _read_runs(old, GH_TIMEOUT)
        grouped = workorders.ci_not_run(self._repos, self._promotes)
        failed = workorders.ci_failed_owners(self._repos)
        new = workorders.ci_spells(read, grouped, failed, now_iso())
        if new == old:
            return
        for key in new.keys() - old.keys():
            log.info("CI not starting in %s: a spell begins", new[key].get("owner") or key)
        for key in old.keys() - new.keys():
            log.info("CI not starting in %s: the spell ends", old[key].get("owner") or key)
        self._ci_spells_save(new)

    def _ci_spells_save(self, spells: dict[str, dict[str, Any]]) -> None:
        if spells:
            self._host_rec["ci_spells"] = spells
        else:
            self._host_rec.pop("ci_spells", None)
        self.host_store.save(self._host_rec)

    async def rpc_ci_rerun(self, owner: str = "", caller: Any = None) -> dict[str, Any]:
        """The *CI not starting* row's **Re-run** (design §4.5a, TD-687): a person's own act, refused to
        every session as `inbox_delete` is, and served by the home alone, which holds the readings it
        names. `gh run rerun <run> --failed` from each repo's root for every run the row's PRs and
        default branches name, each bounded; the runs GitHub took are kept on the spell as pending and
        its clear count goes back to 0, so the row reads *re-run asked <age>* until they are read
        done. Answers `{owner, asked, refused, why}`, `why` GitHub's first refusal."""
        agent_common.person_only(caller, "re-run an account's CI", "§4.5a *Inbox row: CI not starting*", self._graph())
        if self.mode != "home":
            raise RpcError("ci_rerun runs at the home (design §4.4a): this host is a node")
        async with self._ci_lock():  # one press at a time, never inside a step
            return await self._ci_rerun_locked(owner)

    async def _ci_rerun_locked(self, owner: str) -> dict[str, Any]:
        key = str(owner or "").strip().lower()
        spells = self._host_rec.get("ci_spells") or {}
        if key not in spells:
            raise RpcError(f"no *CI not starting* row for {owner!r}: the home reads CI as starting there")
        runs = workorders.ci_rerun_runs(spells[key])
        if not runs:
            raise RpcError(f"the *CI not starting* row for {owner!r} names no run to re-run")
        results = await asyncio.gather(
            *(asyncio.to_thread(reports.run_rerun, root, run, GH_TIMEOUT) for root, run in runs)
        )
        taken = [
            {"root": root, "run": run, "pending": True}
            for (root, run), why in zip(runs, results, strict=True)
            if why is None
        ]
        refused = [why for why in results if why is not None]
        spell = {**spells[key], "clear": 0}
        spell["rerun"] = {"at": now_iso(), "runs": taken, "asked": len(runs), "refused": len(refused)}
        self._ci_spells_save({**spells, key: spell})
        log.info("CI not starting in %s: re-run asked of %d run(s), %d refused", owner, len(runs), len(refused))
        return {"owner": spell.get("owner") or owner, "asked": len(runs), "refused": len(refused),
                "why": refused[0] if refused else None}  # fmt: skip
