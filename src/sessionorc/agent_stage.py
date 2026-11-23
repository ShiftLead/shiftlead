"""The host agent's two stage calls, `stage_end` and `stage_show` (design §4.9c *An outcome is the session's word,
checked*, §4.7, TD-2050). Their body is `shiftlead.stage_end`, reached through the `shiftlead.home_calls` entry point
because `sessionorc` never imports `shiftlead`; this layer holds what is the home's: who is calling, which entry the
session holds, a thread for the blocking work, and the claim released once the move is written.
"""

from __future__ import annotations

import asyncio
from importlib.metadata import entry_points
from typing import Any

from sessionorc.agent_common import RpcError, log
from sessionorc.models import lane_refs

GROUP = "shiftlead.home_calls"
NAME = "stage"


def stage_calls() -> Any:
    """The module holding the stage calls, or a refusal naming the install that lacks it."""
    for ep in entry_points(group=GROUP):
        if ep.name != NAME:
            continue
        try:
            return ep.load()
        except Exception as e:  # noqa: BLE001 — a broken stage module refuses this call and never takes the agent down
            log.exception("the %s entry point %s failed to load", GROUP, NAME)
            raise RpcError(f"the stage code could not be loaded ({type(e).__name__}): reinstall shiftlead") from None
    raise RpcError(f"this install has no {GROUP} entry point: reinstall shiftlead, then try again")


class StageMixin:
    def _stage_entry(self, s: Any) -> str:
        """The one entry a stage's session holds: its lane is that entry (§4.8)."""
        refs = [r for r in lane_refs(s.lane or []) if r.startswith("TD-")]
        if len(refs) != 1:
            raise RpcError("this session holds no stage: `ao stage end` is run by a stage's own session")
        return refs[0]

    async def rpc_stage_end(self, id: str, outcome: str, reason: str = "", caller: Any = None) -> dict[str, Any]:
        """`ao stage end <outcome> [--reason]`: only the session itself may end its stage, and the entry is the one
        it holds. The body checks the outcome's fact and writes the move; a refusal changes nothing."""
        s = self._find(id)  # type: ignore[attr-defined]
        if not self._is_self(s, caller):  # type: ignore[attr-defined]
            raise RpcError("this entry is not yours: a stage is ended by the session that holds it")
        if s.host != self.host:  # type: ignore[attr-defined]
            raise RpcError(f"{s.id} runs on {s.host}: the home cannot read that worktree yet, so its stage cannot end")
        tid = self._stage_entry(s)
        calls = stage_calls()
        got = await asyncio.to_thread(
            calls.call,
            root=s.repo or s.dir,
            directory=s.dir,
            team=s.team,
            tid=tid,
            caller=s.id,
            outcome=outcome,
            reason=reason,
        )
        if "refused" in got:
            raise RpcError(str(got["refused"]))
        if any(e.ref == tid and e.status == "claimed" for e in s.progress):
            await self.rpc_progress(s.id, ref=tid, status="done", caller=caller)  # type: ignore[attr-defined]
        return got

    async def rpc_stage_show(self, id: str, entry: str | None = None) -> dict[str, Any]:
        """`ao stage show [TD-n]`: the entry's record; with no id, the one the session holds."""
        s = self._find(id)  # type: ignore[attr-defined]
        tid = entry or self._stage_entry(s)
        got = await asyncio.to_thread(stage_calls().show, root=s.repo or s.dir, tid=tid)
        if "refused" in got:
            raise RpcError(str(got["refused"]))
        return got
