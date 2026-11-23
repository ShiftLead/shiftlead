"""The host agent's two stage calls, `stage_end` and `stage_show` (design §4.9c *An outcome is the session's word,
checked*, §4.7, TD-2050). Their body is `shiftlead.stage_end`, reached through the `shiftlead.home_calls` entry point
because `sessionorc` never imports `shiftlead`; this layer holds what is the home's: who is calling, which entry the
session holds, a thread for the blocking work, and the claim released once the move is written.
"""

from __future__ import annotations

import asyncio
import time
from importlib.metadata import entry_points
from typing import Any

from sessionorc.agent_common import ACT_TIMEOUT, RpcError, log
from sessionorc.agent_ids import origin_key
from sessionorc.models import lane_refs

GROUP = "shiftlead.home_calls"
NAME = "stage"
FLOW = "flow"


def home_call(name: str) -> Any:
    """The module the group names `name`, or a refusal naming the install that lacks it."""
    for ep in entry_points(group=GROUP):
        if ep.name != name:
            continue
        try:
            return ep.load()
        except Exception as e:  # noqa: BLE001 — a broken module refuses this call and never takes the agent down
            log.exception("the %s entry point %s failed to load", GROUP, name)
            raise RpcError(f"the {name} code could not be loaded ({type(e).__name__}): reinstall shiftlead") from None
    raise RpcError(f"this install has no {GROUP} entry point {name}: reinstall shiftlead, then try again")


def stage_calls() -> Any:
    """The module holding the stage calls."""
    return home_call(NAME)


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
        tid = self._stage_entry(s)
        calls = stage_calls()
        root, seen = await self._stage_place(s)
        address = self._address(s)  # type: ignore[attr-defined]
        got = await asyncio.to_thread(
            calls.call,
            root=root,
            directory=s.dir,
            team=s.team,
            tid=tid,
            caller=address,
            outcome=outcome,
            reason=reason,
            seen=seen,
        )
        if "refused" in got:
            raise RpcError(str(got["refused"]))
        if any(e.ref == tid and e.status == "claimed" for e in s.progress):
            await self.rpc_progress(address, ref=tid, status="done", caller=caller)  # type: ignore[attr-defined]
        return got

    async def _stage_place(self, s: Any) -> tuple[str, dict[str, Any] | None]:
        """`(the home's checkout of s's repo, s's worktree as its node read it)`; for a session here, its own repo and
        None. A node's paths mean nothing here, so its repo is found by origin among the home's registered checkouts."""
        if s.host == self.host:  # type: ignore[attr-defined]
            return s.repo or s.dir, None
        seen = await self._ask_node(s.host, "stage_worktree", dir=s.dir)  # type: ignore[attr-defined]
        if not isinstance(seen, dict):
            raise RpcError(f"{s.host} answered with no reading of {s.dir}")
        if "refused" in seen:
            raise RpcError(f"{s.host}: {seen['refused']}")
        if not seen.get("origin"):
            raise RpcError(f"{s.dir} on {s.host} has no origin remote: the home cannot find its repo")
        root, _key, _name = await self._ids_repo(  # type: ignore[attr-defined]
            origin_key(str(seen["origin"])), time.monotonic() + ACT_TIMEOUT
        )
        return root, seen

    async def rpc_stage_show(
        self, id: str | None = None, entry: str | None = None, repo: str | None = None
    ) -> dict[str, Any]:
        """`ao stage show [TD-n]`: the entry's record; with no id, the one the session holds. From a person's shell
        there is no session: it names the entry, and `repo` is the registered checkout it was run in (§4.7)."""
        if id:
            s = self._find(id)  # type: ignore[attr-defined]
            tid = entry or self._stage_entry(s)
            root, _seen = await self._stage_place(s)
        else:
            from sessionorc.agent import _registered_checkout  # the agent imports this mixin

            checkout = await asyncio.to_thread(_registered_checkout, repo)
            if not entry or checkout is None:
                raise RpcError("name the entry and a registered repo, or run this inside a stage's session")
            tid, root = entry, str(checkout)
        got = await asyncio.to_thread(stage_calls().show, root=root, tid=tid)
        if "refused" in got:
            raise RpcError(str(got["refused"]))
        return got
