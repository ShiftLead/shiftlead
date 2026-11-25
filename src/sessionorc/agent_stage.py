"""The host agent's two stage calls, `stage_end` and `stage_show` (design §4.9c *An outcome is the session's word,
checked*, §4.7, TD-2050). Their body is `shiftlead.stage_end`, reached through the `shiftlead.home_calls` entry point
because `sessionorc` never imports `shiftlead`; this layer holds what is the home's: who is calling, which entry the
session holds, a thread for the blocking work, and the claim released once the move is written.
"""

from __future__ import annotations

import asyncio
import copy
import re
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import entry_points
from pathlib import PurePath
from typing import Any

from sessionorc import hosts, naming, teamstore, workorders
from sessionorc import settings as settings_mod
from sessionorc.agent_common import ACT_TIMEOUT, RpcError, log
from sessionorc.agent_ids import origin_key
from sessionorc.client import AgentError, AgentUnavailable
from sessionorc.mail import PERSON
from sessionorc.models import Session, lane_refs

GROUP = "shiftlead.home_calls"
NAME = "stage"
FLOW = "flow"
TEAM = "team"
TICK = "stage_tick"
STAGE_EVERY = 60.0  # seconds between two stage passes at the home (§4.9c *The home acts only where no session will*)
STAGE_CALL_WAIT = ACT_TIMEOUT * 4  # a pass's call on the home's loop: a create waits on its pane
# a job's work order (`workorders.PREFIX`, `PR_PREFIX`) or an audit run's lease, as its session holds it
HELD = re.compile(
    rf"{re.escape(workorders.PREFIX)}[0-9a-f]{{8}}|{re.escape(workorders.PR_PREFIX)}[1-9]\d{{0,6}}|audit:[^/\s]+/[^/\s]+"
)
STAGE_POOL = 4  # the pass's own threads, apart from `to_thread`'s pool, which the RPCs it waits on use


def switching(host_teams: Mapping[str, Any] | None, team: str) -> str | None:
    """The flow a team's switch is under way to, from the home's `host` record (§4.9d *The flow pick and a switch*), or
    None."""
    rec = (host_teams or {}).get(team)
    value = rec.get("switching") if isinstance(rec, Mapping) else None
    return str(value) if value else None


def stage_teams(
    doc: Mapping[str, Any], host_teams: Mapping[str, Any] | None = None
) -> dict[str, dict[str, dict[str, Any]]]:
    """The switched teams of `settings.yml` by the registered checkout's name their `repo` holds (§4.9d *Before and
    after the cut-over*): `{repo: {team: its entry}}`, each entry a copy for the pass's thread. A team whose switch is
    under way is left out until it is made, so no pass writes the old flow's copy back over the new."""
    teams = doc.get("teams")
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for team, entry in teams.items() if isinstance(teams, Mapping) else ():
        if isinstance(team, str) and teamstore.switched(doc, team) and not switching(host_teams, team):
            out.setdefault(str(entry["repo"]).strip(), {})[team] = copy.deepcopy(dict(entry))
    return out


def _named(path: Any, name: str) -> bool:
    """Whether a checkout's path is the registered repo `name`, by its last component as the readings name a repo
    (`queue.record_repo`); a node's path is never resolved here."""
    return bool(path) and PurePath(str(path)).name == name


def told(team: str, problems: Any) -> str:
    """The note to the person once a team's flow stops passing its check (§4.9c *A flow that stops passing its check
    keeps its last good version in use*)."""
    lines = [str(p) for p in problems or ()] or ["its check gave no reason"]
    return f"Team {team}'s flow stopped passing its check, so the team keeps running its last good copy.\n" + "\n".join(
        f"- {p}" for p in lines
    )


def refused_words(r: Any) -> str:
    """The note to the person once an entry's act has been refused the same way pass after pass (§4.9c *A refusal that
    stands*)."""
    since = r.since.strftime("%Y-%m-%d %H:%M UTC") if hasattr(r.since, "strftime") else str(r.since)
    return (
        f"The home cannot move {r.tid} (team {r.team}): its {r.act} step was refused on every pass since {since}.\n"
        f"- {r.why}\n"
        "The home keeps trying each pass, and tells you again only if the refusal changes, or comes back after the "
        "step goes through."
    )


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


def held_ref(ref: str, *, jobs: bool = False) -> bool:
    """Whether `ref` is what a stage's session holds: an entry; with `jobs`, also a built-in seat's job's work order
    (`board:<8 hex>`, `pr:<n>`, §4.9d *How each one runs*) or an audit run's lease (`audit:<team>/<audit>`, §4.9c
    *Audits start on a clock*), whose outcomes the body takes too (TD-2053)."""
    if ref.startswith("TD-"):
        return True
    return jobs and bool(HELD.fullmatch(ref))


class StageMixin:
    def _stage_entry(self, s: Any, *, jobs: bool = False) -> str:
        """The one entry a stage's session holds: its lane is that entry (§4.8). With `jobs`, a job's work order or an
        audit run's lease is held as well: `ao stage end` takes their outcomes, and `ao stage show` an entry's alone."""
        refs = [r for r in lane_refs(s.lane or []) if held_ref(r, jobs=jobs)]
        if len(refs) != 1:
            raise RpcError("this session holds no stage: `ao stage end` is run by a stage's own session")
        return refs[0]

    @staticmethod
    def _holds_stage(s: Any) -> bool:
        """Whether `s` is a stage's session: a team's, no seat, its lane one entry (§4.8)."""
        refs = [r for r in lane_refs(s.lane or []) if r.startswith("TD-")]
        return bool(s.team) and s.seat is None and not s.builtin and len(refs) == 1

    async def rpc_stage_end(self, id: str, outcome: str, reason: str = "", caller: Any = None) -> dict[str, Any]:
        """`ao stage end <outcome> [--reason]`: only the session itself may end its stage, and the entry is the one
        it holds. The body checks the outcome's fact and writes the move; a refusal changes nothing."""
        s = self._find(id)  # type: ignore[attr-defined]
        if not self._is_self(s, caller):  # type: ignore[attr-defined]
            raise RpcError("this entry is not yours: a stage is ended by the session that holds it")
        tid = self._stage_entry(s, jobs=True)
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

    # the stage pass (§4.9c *The home acts only where no session will*, TD-2051): one detached pass at the home after
    # the cut-over, at most once a minute, a thread for each repo with switched teams, and never two passes at once
    _stage_task: asyncio.Task[None] | None = None
    _stage_at = float("-inf")

    def _stage_due(self) -> None:
        """The tick's start of the stage pass: the home's, after the cut-over, once `STAGE_EVERY` has passed since the
        last began and that one has ended, so no repo is ever in two passes at once."""
        if self.mode != "home" or not self._first_shape_off:  # type: ignore[attr-defined]
            return
        if self._stage_task is not None and not self._stage_task.done():
            return
        if time.monotonic() - self._stage_at < STAGE_EVERY:
            return
        self._stage_at = time.monotonic()
        self._stage_task = asyncio.create_task(self._stage_pass())

    async def _stage_pass(self) -> None:
        """One pass over every repo with switched teams, each in a thread of its own (`shiftlead.stage_tick.run`, whose
        gate can take as long as the cadence check). What only the home holds is read here, on the loop, and handed
        over as copies: the repo facts of `_refresh_repos`' last reading (a repo not read yet waits for it), the graph,
        the nodes whose snapshot has arrived, every node's checkouts of the repo and the `host` record's teams."""
        try:
            doc = await asyncio.to_thread(settings_mod.read)
            host_teams = copy.deepcopy(self._host_rec.get("teams") or {})  # type: ignore[attr-defined]
            by_repo = stage_teams(doc, host_teams) if doc is not None else {}
            if not by_repo:
                return
            calls = home_call(TICK)
            roots = await asyncio.to_thread(lambda: hosts.local_host().repos())
            graph = copy.deepcopy(self._graph())  # type: ignore[attr-defined]
            snapshotted = frozenset(self._intent_sent)  # type: ignore[attr-defined]
            kept: dict[str, Any] = self.__dict__.setdefault("_stage_kept", {})
            call = self._stage_call(asyncio.get_running_loop())
            jobs = []
            for name, teams in sorted(by_repo.items()):
                local = [r for r in roots if _named(r, name)]
                if not local:
                    log.warning("the stage pass: no registered checkout is %s, named by %s", name, ", ".join(teams))
                    continue
                root = local[0]
                reading = self._repos.get(root)  # type: ignore[attr-defined]
                if not reading:
                    continue
                checkouts = {self.host: local, **await self._stage_nodes(name, graph)}  # type: ignore[attr-defined]
                args = {
                    "root": root,
                    "teams": teams,
                    "entries": copy.deepcopy((reading.get("ledger") or {}).get("entries") or []),
                    "prs": copy.deepcopy(reading.get("prs")),
                    "graph": graph,
                    "snapshotted": snapshotted,
                    "checkouts": checkouts,
                    "host_teams": host_teams,
                    "local": self.host,  # type: ignore[attr-defined]
                    "call": call,
                    "kept": kept.setdefault(root, calls.Kept()),
                }
                jobs.append(self._stage_repo(calls, root, args))
            await asyncio.gather(*jobs)
        except Exception:  # noqa: BLE001 — a pass that fails is a log line and the next minute's retry
            log.exception("the stage pass failed")

    async def _stage_nodes(self, name: str, graph: Mapping[str, Session]) -> dict[str, list[str]]:
        """Each node's checkouts of the repo `name`: its roster's, and the repos its sessions work in, so a roster
        that did not answer still names where they are. A node with none of either is left out, but for one whose
        roster gave nothing at all, which is named with what its sessions show, so its holders read as unknown while
        its snapshot has not arrived."""
        nodes = set(hosts.nodes()) | set(self.remote)  # type: ignore[attr-defined]
        nodes.discard(self.host)  # type: ignore[attr-defined]
        out: dict[str, list[str]] = {}
        for node in sorted(nodes):
            roster = await self._host_roster(node)  # type: ignore[attr-defined]
            paths = [str(r) for r in roster if _named(r, name)]
            for address, s in graph.items():
                at = naming.split_address(address)[1]
                if at == node and _named(s.repo, name) and str(s.repo) not in paths:
                    paths.append(str(s.repo))
            if paths or not roster:
                out[node] = paths
        return out

    async def _stage_repo(self, calls: Any, root: str, args: dict[str, Any]) -> None:
        """One repo's pass in a thread, then the person told once of each team whose flow newly fails its check, and of
        each entry whose act's refusal has newly come to stand."""
        try:
            pool = self.__dict__.get("_stage_pool")
            if pool is None:
                pool = self.__dict__["_stage_pool"] = ThreadPoolExecutor(STAGE_POOL, thread_name_prefix="stage-pass")
            got = await asyncio.get_running_loop().run_in_executor(pool, lambda: calls.call(**args))
        except Exception:  # noqa: BLE001 — one repo's failure never stops another's pass
            log.exception("the stage pass of %s failed", root)
            return
        for team, problems in sorted((getattr(got, "tell", None) or {}).items()):
            try:
                self._system_note(PERSON, told(team, problems), team=team)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 — a note that cannot be written is a log line, never the pass
                log.exception("the stage pass could not tell the person of %s's flow", team)
        for r in getattr(got, "refused", None) or ():
            try:
                self._system_note(PERSON, refused_words(r), team=r.team)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 — as above
                log.exception("the stage pass could not tell the person of %s's refusal", r.tid)

    def _stage_call(self, loop: asyncio.AbstractEventLoop) -> Callable[..., Any]:
        """The host agent's call as the pass's thread makes it: the RPC dispatched on the loop with no session caller,
        so a close keeps the tick as its closer (slice 31). A refusal raises `AgentError` as the client's does, and a
        loop that does not answer in `STAGE_CALL_WAIT`, or stops, raises `AgentUnavailable`. A call that times out is
        never cancelled, since a create cancelled after its pane came up would leave a session no record names; it
        finishes on the loop and the next pass reads what it made."""

        def call(method: str, **params: Any) -> Any:
            req = {"id": f"stage-{method}", "method": method, "params": params}
            fut = asyncio.run_coroutine_threadsafe(self._dispatch_inner(req), loop)  # type: ignore[attr-defined]
            end = time.monotonic() + STAGE_CALL_WAIT
            while True:
                try:
                    resp = fut.result(timeout=1.0)
                    break
                except TimeoutError:
                    if not loop.is_running():
                        raise AgentUnavailable(f"the home stopped while {method} was asked") from None
                    if time.monotonic() >= end:
                        raise AgentUnavailable(
                            f"the home did not answer {method} within {STAGE_CALL_WAIT:.0f}s"
                        ) from None
            if "error" in resp:
                raise AgentError(str(resp["error"]), resp.get("error_data"))
            return resp.get("result")

        return call
