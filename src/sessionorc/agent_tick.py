"""Reconcile and the tick's policies (TD-108 step 1): what the host agent does every tick — observe the
panes, the stop times, the usage gate, keeping a team running (design §6), git and model reads, the reports
— as a mixin `HostAgent` inherits. Moved as written; the state it reads is the agent's.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import os
import re
import shutil
import time
from collections.abc import Collection, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc import (
    adapters,
    agent_common,
    hosts,
    mail,
    naming,
    paths,
    reports,
    workorders,
)
from sessionorc import balance as balance_mod
from sessionorc import brief as brief_mod
from sessionorc import cadence as cadence_mod
from sessionorc import conventions as conventions_mod
from sessionorc import held as held_mod
from sessionorc import ledger as ledger_mod
from sessionorc import promote as promote_mod
from sessionorc import queue as queue_mod
from sessionorc import seams as seams_mod
from sessionorc import settings as settings_mod
from sessionorc import settle as settle_mod
from sessionorc import sync as sync_mod
from sessionorc import usage as usage_mod
from sessionorc import work as work_mod
from sessionorc.agent_common import (
    BOARD_EVERY,
    BRIEF_SETTLE,
    COMPOSER_LINES,
    CONTEXT_AGAIN,
    DERIVE_EVERY,
    FILL_CEILING,
    FILL_WINDOW,
    GIT_EVERY,
    IDLE_NUDGE,
    LANE_NEWS_NAMED,
    LAUNCH_KEYS,
    LEASE_TTL,
    MODEL_EVERY,
    ORPHAN_AFTER,
    OWED_NAMED,
    PRUNE_EVERY,
    REMOVED_GUARD_SECONDS,
    REPOS_EVERY,
    RESTART_CEILING,
    RESTART_WINDOW,
    RESUME_MIN,
    SEAT_IDLE_GRACE,
    SEAT_PR_WAIT,
    SETTLED,
    STALL_AFTER,
    TAIL_LINES,
    RpcError,
    _cap,
    _clean,
    _cool_left,
    _duration,
    _is_branch_claim,
    _pane_title,
    _parse,
    _recent,
    _usage_checked_at,
    _usage_key,
    backup_store,
    log,
)
from sessionorc.agent_ids import settle_key
from sessionorc.agent_spend import SEAT_EVERY, _metered_of
from sessionorc.gitinfo import UNKNOWN as GIT_UNKNOWN
from sessionorc.gitinfo import changed_files, git_info, work_left
from sessionorc.models import (
    PERSON,
    PR_CLOSED,
    RECENT_FILES,
    RECENT_LINKS,
    RECENT_PROMPTS,
    SYSTEM,
    Pending,
    ProgressEntry,
    Session,
    context_over_text,
    lane_refs,
    now_iso,
)
from sessionorc.tmux import PaneInfo


def _stamped(mark: dict[str, Any], stopped: dict[str, str] | None) -> dict[str, Any]:
    """A `work_waiting` mark with `stopped` as the team reads now (§6 rule 8 *A team that stopped*, TD-781): set
    for a stopped team, dropped for one that reads wound down or runs on, every other field kept."""
    bare = {k: v for k, v in mark.items() if k != "stopped"}
    return {**bare, "stopped": stopped} if stopped else bare


def _asked(questions: list[Any], members: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """A `work_waiting` mark's members with each question's reference under the name that asked it
    (§6 rule 8 *A question's end is work*, TD-274): `members` (a lane's new ids) copied, or none."""
    out = {m: list(ids) for m, ids in (members or {}).items()}
    for q in questions:
        got = out.setdefault(str(q.get("name")), [])
        if str(q.get("ref")) not in got:
            got.append(str(q.get("ref")))
    return out


FILLED_FOR = "[shiftlead] you are filled for: "
# `restarts` entries that are not the tick's restarts, left out of rule 9's note (§4.9a, TD-468): a
# person's Restart, and a team's start by a schedule or by rule 8
NOT_RESTARTS = ("person", "start", "work")


def filled_for(cause: dict[str, Any] | None) -> str | None:
    """The closing line of a manager on call's fill prompt (§6 rule 3 *A fill says why it came*,
    TD-410), in fixed words from its `seat_due`: *[shiftlead] you are filled for: <by> — <member>*, the
    question's id for `asks`, and for a tagging seat's `tag` the ids it tags, *tag — TD-801, TD-802*
    (§4.4 *An entry names its team*, TD-730). None for any other fill, which says nothing more — a
    sweep seat's `swept` among them, whose brief says what brought it (§4.9b *The sweep*, TD-1090)."""
    if not cause or not cause.get("by") or cause["by"] == "swept":
        return None
    if cause["by"] == "asks":
        what = cause.get("ask")
    elif cause["by"] == "tag":
        what = ", ".join(str(i) for i in cause.get("ids") or [])
    else:
        what = cause.get("member")
    return f"{FILLED_FOR}{cause['by']}" + (f" — {what}" if what else "")


def _carry_live(reading: dict[str, Any], old: dict[str, Any]) -> None:
    """A live check in `reading` takes the `live` the same id held in `old`, the checkout's last
    reading, when the live commit is unknown (`_read_repos`, TD-516); one `old` does not hold keeps
    the `no` it was read with."""
    was = {
        str(e.get("id")): e["live"]
        for e in (old.get("ledger") or {}).get("entries") or []
        if isinstance(e, dict) and e.get("kind") == "live-check" and e.get("live") in ("yes", "no")
    }
    for e in (reading.get("ledger") or {}).get("entries") or []:
        if isinstance(e, dict) and e.get("kind") == "live-check" and str(e.get("id")) in was:
            e["live"] = was[str(e.get("id"))]


# how often a record whose only change is `shells_at` is written to disk (§4.2 *A background shell task*,
# TD-766): it moves every tick in memory, and a minute's lag on disk only matters across a restart
SHELLS_SAVE_EVERY = timedelta(minutes=1)
# How long after a `kill` an `exited` hook on a record a new run has taken is the killed run's own
# `SessionEnd` (TD-822): the walk saw it land within a second or two; fifteen is the walk's own wait.
KILLED_END_GRACE = 15.0
# A thread's open calls (design §4.2 *A waiter is keyed by its call*, TD-950): the last eight per thread, at
# most sixteen threads per session; a call that never ends (the tool's own id, every subagent capture) ages out.
OPEN_CALLS = 8
OPEN_THREADS = 16
# `_permission_waiting`'s thread when any thread's waiter counts
ANY_THREAD = object()
# A title's `needs-you` (§4.3 *Two gaps*), written by the state it replaces: over a turn, the tool's
# embedded shell gone quiet waiting for input; over `idle`, a confirmation shown with no turn.
TITLE_SHELL_WAITS = "the tool's shell waits for input"
TITLE_CONFIRMATION = "the tool waits for a confirmation"


def _orders(r: dict[str, Any] | None) -> list[Any]:
    """A repo reading's work orders: the board's decided lines (TD-384), then its red PRs nobody holds
    (`pr_orders`, TD-613)."""
    r = r or {}
    return [*((r.get("work_orders") or {}).get("orders") or []), *((r.get("pr_orders") or {}).get("orders") or [])]


NODE_CHANGES = "agent-cadence path cadence-changes.md"  # rule 12's command on a node: `ao host up`'s link (TD-1046)
SETUP_EVERY = 3600.0  # seconds between the setup notes' reads with `profiles.yml` unchanged (TD-875)


class TickMixin:
    # -- reconcile -------------------------------------------------------------------------------
    #
    # Concurrency model: every mutation of `self.sessions` and of Session objects happens on the
    # event loop, never in a thread. Only the tmux subprocess calls run in threads, and they
    # return plain data. So a tick's reconcile step and an RPC handler can never interleave
    # inside a check-then-act sequence — the loop runs them one at a time.

    async def _setup_notes(self) -> None:
        """What a machine needs a person for before an adapter's sessions can run (design §4.3 *The person
        meets the step at setup*, TD-875): on the first tick, whenever `profiles.yml` changes, and hourly
        (what the note is about lives outside the home, so its undoing is seen without a restart), each
        adapter's `setup_note` (§4.3's optional method) is read, and a note it gives goes to the person
        **once per key** — kept in `setup_notes.json`, so a restart does not repeat it; a key of None
        (all is as wanted) forgets the adapter's, so a step undone later is said again."""
        p = paths.home() / "profiles.yml"
        try:
            seen: object = p.stat().st_mtime_ns
        except OSError:
            seen = "none"
        if seen == self._setup_seen and time.monotonic() - self._setup_read_at < SETUP_EVERY:
            return
        self._setup_seen, self._setup_read_at = seen, time.monotonic()

        def read() -> list[tuple[str, dict[str, Any]]]:
            out = []
            for name in adapters.names():
                fn = getattr(adapters.get(name), "setup_note", None)
                if fn is None:
                    continue
                try:
                    got = fn()
                except Exception:  # noqa: BLE001 — one adapter's reading never holds up the tick
                    log.exception("adapter %s: setup note failed", name)
                    continue
                if got is not None:
                    out.append((name, got))
            return out

        notes = await asyncio.to_thread(read)
        store = paths.home() / "setup_notes.json"
        try:
            sent: dict[str, str] = json.loads(store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            sent = {}
        before = dict(sent)
        for name, got in notes:
            key = got.get("key")
            if key is None:
                sent.pop(name, None)
            elif sent.get(name) != key and got.get("text"):
                self._system_note(PERSON, str(got["text"]))
                sent[name] = str(key)
        if sent != before:
            store.write_text(json.dumps(sent, indent=1), encoding="utf-8")

    async def tick(self) -> None:
        snapshot_at = datetime.now(UTC)
        panes = await asyncio.to_thread(self.tmux.main_panes, naming.PREFIX)
        self._id_note_panes(panes)
        self._id_flush()
        await self._id_recheck_detached()
        tails = await asyncio.to_thread(lambda: {sid: self.tmux.capture_tail(sid, TAIL_LINES) for sid in panes})
        self._reconcile(panes, tails, snapshot_at)
        self._note_tick(snapshot_at)
        self._note_attention(snapshot_at)
        try:
            self._notify_pass(snapshot_at)
        except Exception:  # noqa: BLE001 — telling the person is never worth a tick
            log.exception("the Telegram pass failed")
        await self._clear_gone_kept()
        await self._refresh_git(snapshot_at)
        await self._refresh_model(snapshot_at)
        await self._refresh_context(snapshot_at)
        await self._refresh_shells(snapshot_at, panes)
        await self._refresh_links(snapshot_at)
        await self._refresh_prompts(snapshot_at)
        if self._derive_task is None or self._derive_task.done():
            # detached for the same reason the usage refresh is: `gh` talks to the network, and the
            # tick and its push must not wait on it (review 2026-09-11)
            self._derive_task = asyncio.create_task(self._derive_reports(snapshot_at))
        if snapshot_at - self._pruned_at > PRUNE_EVERY:
            self._pruned_at = snapshot_at
            # the live set is read here, on the loop (the class's one-writer rule); only the file
            # work goes to the thread
            ended = ("exited", "closed")
            live = {s.run_log for s in self.sessions.values() if s.run_log and s.state not in ended}
            # a round log goes with the last record of its name (§4.6, TD-191): kept while one is live
            live |= {str(self._rounds_log(s)) for s in self.sessions.values() if s.state not in ended}
            # an attachment's folder is kept whole while any record of its session is live (§4.4, TD-469)
            live_ids = {s.id for s in self.sessions.values() if s.state not in ended}
            await asyncio.to_thread(self._prune_runs, snapshot_at, live, live_ids)
        if self.mode == "home":
            self._supervise_containers()
            day = datetime.now().astimezone().date().isoformat()
            if day != self._backed_up and (self._backup_task is None or self._backup_task.done()):
                self._backed_up = day  # tried once a day: a failure is a log line and tomorrow's retry
                self._backup_task = asyncio.create_task(self._backup(day))
        if self.mode == "home" and (self._repos_task is None or self._repos_task.done()):
            # detached as the usage refresh is: `gh` talks to the network (§4.4 *Repo facts*)
            self._repos_task = asyncio.create_task(self._refresh_repos())
        if self.mode == "home":
            await self._balance_marks(snapshot_at)
            await self._red_prs(snapshot_at)
            await self._queue_pass(snapshot_at)
            await self._rank_pass(snapshot_at)
            await self._shape_tick(snapshot_at)
        if self.mode == "home" and (self._promote_task is None or self._promote_task.done()):
            # detached as the repo facts are: a fetch, `gh` and a repo's own `check` (§6 *Promote*)
            self._promote_task = asyncio.create_task(self._refresh_promotes())
        if self._usage_task is None or self._usage_task.done():
            # detached: a slow usage endpoint (10 s timeout) must not hold up the tick or its push
            self._usage_task = asyncio.create_task(self._refresh_usage())
        if self._spend_task is None or self._spend_task.done():
            # detached as the usage poll is: it reads transcripts (§4.4 *Usage*, TD-151); a node's
            # pass sends its turns home over the link (slice 4)
            self._spend_task = asyncio.create_task(self._refresh_spend())
        if (self._seats_task is None or self._seats_task.done()) and time.monotonic() - self._seats_at >= SEAT_EVERY:
            # once a minute, not every tick: nothing waits on the seat ledger (§4.4 *Spend per seat*); a
            # node's pass sends its turns home (TD-833)
            self._seats_at = time.monotonic()
            self._seats_task = asyncio.create_task(self._refresh_seats())
        await self._setup_notes()
        await self._team_stop_times(snapshot_at)
        await self._carry_controllers()
        await self._enforce_stop_times(snapshot_at)
        await self._enforce_usage_gate(snapshot_at)
        await self._subagent_flips(snapshot_at)
        await self._retire_anchors()
        await self._keep_running(snapshot_at)
        await self._finished_pass(snapshot_at)
        await self._work_marks(snapshot_at)
        await self._sweep_mail(snapshot_at)
        self._poke_waits()  # the wake decision is re-taken every tick for a session blocked in `wait`
        self._send_first_prompts()  # before the doorbell, which a brief not yet typed holds off
        self._ring_doorbells()

    async def _team_stop_times(self, now: datetime) -> None:
        """Design §6 *Team stop time* (TD-146): each live, unattended session carrying a team's badge
        — members and seats, this host's and every node's — whose `run_until` is unset or later than
        its team's `teams.<team>.until` takes the team's instant, exactly as `set_stop` gives one. A
        session's own earlier stop time is kept. A record created after the instant had passed is not
        given it: a team started again after its stop time is the person's word, not a stop.
        **At the home**, whose file it is; a node's record takes it through `set_stop` over the link,
        and waits for the link when it is down."""
        if self.mode != "home":
            return
        untils = {t: v["until"] for t, v in settings_mod.teams(settings_mod.load()).items() if v.get("until")}
        if not untils:
            return
        changed = False
        for s in [*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values())]:
            inst = untils.get(s.team) if s.team else None
            if not inst or not s.unattended or s.state in ("exited", "closed") or s.superseded_by:
                continue
            if s.run_until and _parse(s.run_until) <= _parse(inst):
                continue  # its own earlier stop time, or the team's already
            with contextlib.suppress(TypeError, ValueError):
                if _parse(s.created) >= _parse(inst):
                    continue
            if s.host == self.host:
                self._take_stop(s, inst)
                changed = True
            elif s.host in self._link_muxes:
                try:
                    await self._route_act("set_stop", {"id": self._address(s), "run_until": inst}, None, s.host)
                except Exception as e:  # noqa: BLE001 — tried again on the next tick
                    log.warning("%s: the team's stop time did not reach %s: %s", s.id, s.host, e)
        if changed:
            await self._push_changes()

    async def _carry_controllers(self) -> None:
        """The node half of a rename's carry (design §4.9 *A member renamed or removed in the definition*,
        TD-712): a node member's own record whose `controllers` still name a lead the rename succeeded,
        where `_carry` already rewrote its launch record to the new address, takes the rewrite at its
        node — `set_controllers` routed as a person's edit is (`_route_act`), since `controllers` is the
        node's field and a rewrite of the home's copy would be lost to its next report. **At the home**;
        a node whose link is down is passed over and tried again on the next tick, and a refused or lost
        act is said in the log and ends that node's pass, so a stuck link holds the tick once. The launch
        record is what makes it the carry's: a resume under another id rewrites none, so it moves no
        controller."""
        if self.mode != "home":
            return
        graph = self._graph()
        for host, recs in list(self.remote.items()):
            if host not in self._link_muxes:
                continue
            for rid, r in list(recs.items()):
                if r.state == "closed" or r.superseded_by:
                    continue
                try:
                    launch = json.loads((paths.launch_dir() / f"{rid}@{host}.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                named = launch.get("controllers") if isinstance(launch, dict) else None
                if not isinstance(named, list):
                    continue
                add: list[str] = []
                remove: list[str] = []
                for c in r.controllers:
                    if c in named:
                        continue
                    was, now, seen = self._from_host(c, host), None, 0
                    t = graph.get(was)
                    while t is not None and t.superseded_by and seen < 16:  # a lead renamed twice, too
                        now, seen = t.superseded_by, seen + 1
                        t = graph.get(now)
                    if now and self._to_host(now, host) in named:
                        add.append(now)
                        remove.append(was)
                if not add:
                    continue
                try:
                    await self._route_act(
                        "set_controllers", {"id": f"{rid}@{host}", "add": add, "remove": remove}, None, host
                    )
                    log.info("%s@%s: controllers carried across the rename: %s", rid, host, ", ".join(add))
                except Exception as e:  # noqa: BLE001 — tried again on the next tick
                    log.warning("%s@%s: the rename's controllers did not reach %s: %s", rid, host, host, e)
                    break  # the rest of this node's wait for the next tick: one stuck act, not one each

    def _team_stamp(self, team: str, unattended: bool, run_until: str | None) -> str | None:
        """What a create's `run_until` is under its team's stop time (§6 *Team stop time*): the
        earlier of the two while the team's is still ahead; its own, or none, otherwise — a start
        after the instant has passed is not stopped by it."""
        if not (team and unattended):
            return run_until
        inst = (settings_mod.teams(settings_mod.load()).get(team) or {}).get("until")
        if not inst or _parse(inst) <= datetime.now(UTC):
            return run_until
        return inst if not run_until or _parse(inst) < _parse(run_until) else run_until

    def _take_stop(self, s: Session, when: str | None) -> None:
        """A stop time given by a policy as `set_stop` gives one: a new time is a new run, so a wrap-up
        already asked is spent."""
        if when != s.run_until:
            s.wrapup_sent_at = None
        s.run_until = when
        self._save(s)

    async def _restamp_team(self, team: str, old: str | None, new: str | None) -> None:
        """A team's stop time moved or was cleared (TD-146): the live members that carry the old
        instant took it from the team, so they follow — to the new one, or to none on **Clear**. A
        member's own earlier stop time is another instant and is not touched."""
        if not old or old == new:
            return
        changed = False
        for s in [*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values())]:
            if s.team != team or s.run_until != old or s.state in ("exited", "closed") or s.superseded_by:
                continue
            if new and not s.unattended:
                # a person took it over: a move is a policy's, and policies leave it alone (§4.2); a Clear clears
                continue
            if s.host == self.host:
                self._take_stop(s, new)
                changed = True
            elif s.host in self._link_muxes:
                try:
                    await self._route_act("set_stop", {"id": self._address(s), "run_until": new}, None, s.host)
                except Exception as e:  # noqa: BLE001 — the tick's pass gives a new instant again; a clear waits
                    log.warning("%s: the team's changed stop time did not reach %s: %s", s.id, s.host, e)
        if changed:
            await self._push_changes()

    async def _enforce_stop_times(self, now: datetime) -> None:
        """Stop the unattended sessions whose time is up (design §6, TD-026 gap 1).

        A session started by hand with `--unattended` used to have no stopper at all: nothing wrapped
        it up at 06:00, at a usage cap or when its token lapsed, so "start it now so I can watch it"
        meant "remember to close it yourself". A `run_until` is the general form, and the weekly run
        window (phase 3) becomes one way of setting it rather than a second mechanism.

        Two steps, in the order a person would use: at the time, the session is asked to wrap up —
        once, with the words the client gave at create, because this package must not know what a
        brief is. Then it is killed when it settles (its work is done, or it is waiting on a person
        who is not there) or when `WRAPUP_GRACE` runs out, whichever comes first. Interactive
        sessions are never touched: a stop time is a policy, and policies apply to unattended
        sessions alone (§4.2).
        """
        for s in list(self.sessions.values()):
            if not (s.unattended and s.run_until) or s.state in ("exited", "closed", "scheduled"):
                continue  # a scheduled record has nothing running to stop yet (§6 *Start time*)
            if now < _parse(s.run_until):
                continue
            if not adapters.has_agent(s.adapter):
                # a shell or a command run is typed nothing: killed at once, no wrap-up, no grace (§4.3)
                log.info("%s reached its run_until and runs no agent; stopping it", s.id)
                await self.rpc_kill(s.id, killer={"by": "tick", "why": "stop time"})
                continue
            if not s.wrapup_sent_at:
                if s.pending and s.pending.kind in ("permission", "question"):
                    # A session stopped on a dialog cannot wrap up, and typing at it would answer
                    # the dialog rather than reach the composer (`send` refuses for this reason,
                    # §4.2). Nobody is coming to answer it either — that is what unattended means —
                    # so it is stopped now rather than asked something it cannot hear.
                    log.info("%s reached its run_until on a pending %s; stopping it", s.id, s.pending.kind)
                    await self.rpc_kill(s.id, killer={"by": "tick", "why": "stop time"})
                    continue
                if not s.wrapup_prompt:
                    # Nothing to say, so say nothing and stop it: a stop time with no wrap-up text is
                    # still a stop time, and silently running past it is the failure this fixes.
                    log.info("%s reached its run_until with no wrap-up prompt; stopping it", s.id)
                    await self.rpc_kill(s.id, killer={"by": "tick", "why": "stop time"})
                    continue
                log.info("%s reached its run_until (%s); asking it to wrap up", s.id, s.run_until)
                try:
                    await self._submit(s.id, adapters.get(s.adapter), s.wrapup_prompt)
                except Exception:  # noqa: BLE001 — a pane that will not take a prompt is killed below
                    log.warning("%s would not take the wrap-up prompt; it will be stopped anyway", s.id)
                s.wrapup_sent_at = now_iso()
                self.store.save(s)
                await self._push_changes()
                continue
            settled = s.state in SETTLED
            if settled or now - _parse(s.wrapup_sent_at) >= agent_common.WRAPUP_GRACE:
                log.info("%s stopped after its wrap-up (%s)", s.id, "settled" if settled else "grace ran out")
                await self.rpc_kill(s.id, killer={"by": "tick", "why": "stop time"})

    async def _enforce_usage_gate(self, now: datetime) -> None:
        """Pause the unattended sessions of a profile whose usage crossed a line, and resume them
        when every window is back under (design §6 *Usage gate*, TD-100).

        The lines come from the person's reserves in `settings.yml`, read here on every tick, and
        the windows from the profile's last good usage reading — a failed poll keeps the last one,
        and a profile with no reading at all neither pauses nor resumes anything. A pause is a
        **send, not a kill**: the mark `gated` is written the tick the line is crossed, the record's
        `pause_prompt` is typed once and retried every tick until it lands (`sent_at`), and a session
        sitting on a permission or a question is not typed at — waiting on a dialog, it is consuming
        nothing, so the mark stands and the send lands after the dialog clears. The resume is the
        `resume_prompt`, typed when every window is under its line and no sooner than `RESUME_MIN`
        after the pause; the mark goes with it. Interactive sessions are never gated: a session a
        person took over loses its mark on the next tick, with nothing typed.

        A session carrying a team's badge whose team has a **reserve priority** (`teams.<team>.
        reserve`, TD-146) pauses at its profile's line lowered by that much, on every window with a
        reserve, and its mark carries `team_extra: {team, n}` so the card can say which line it was."""
        whole = settings_mod.load()
        changed = False
        for s in list(self.sessions.values()):
            if not s.unattended or s.state in ("exited", "closed", "scheduled") or not adapters.has_agent(s.adapter):
                if s.gated:
                    s.gated = None  # the gate's reach is unattended, live agents alone (§9 invariant 5, §4.3)
                    self.store.save(s)
                    changed = True
                continue
            by_label = self._gate_reserves(whole, s.profile)
            windows = self._gate_windows(s.profile, now, whole)
            if windows is None and by_label:
                continue  # no reading: the last word stands, whatever it was (§6: a failure never gates)
            extra = settings_mod.team_extra(whole, s.team)
            rows = settings_mod.lines(by_label or {}, windows, now, extra)
            over = settings_mod.crossed(rows)
            if over is not None:
                mark = {
                    "profile": s.profile,
                    "label": over["label"],
                    "pct": over["pct"],
                    "line": over["line"],
                    "since": (s.gated or {}).get("since") or now_iso(),
                    "next": over["next"],
                    "resets": over["resets"],  # so a card can say *resets* when `next` is the reset
                    "sent_at": (s.gated or {}).get("sent_at"),
                    **({"team_extra": {"team": s.team, "n": extra}} if extra else {}),
                    **({"projected": over["projected"]} if over.get("projected") else {}),
                }
                was = s.gated or {}
                if (
                    was.get("projected")
                    and mark.get("projected")
                    and (was.get("label"), was.get("line")) == (mark["label"], mark["line"])
                    and abs(float(was.get("pct") or 0) - float(mark["pct"] or 0)) < 1
                ):
                    mark = was  # a projection grows by the second: rewrite the mark only as it moves a point
                if mark != s.gated:
                    if not s.gated:
                        log.info("%s paused by the usage gate: %s %s %s%% >= %s%%", s.id, s.profile,
                                 over["label"], over["pct"], over["line"])  # fmt: skip
                    s.gated = mark
                    self.store.save(s)
                    changed = True
                if not s.gated.get("sent_at") and s.pause_prompt and not self._on_a_dialog(s):
                    try:
                        await self._submit(s.id, adapters.get(s.adapter), s.pause_prompt)
                    except Exception:  # noqa: BLE001 — retried on the next tick (§6)
                        log.warning("%s would not take the pause prompt; retrying next tick", s.id)
                    else:
                        s.gated = {**s.gated, "sent_at": now_iso()}
                        self.store.save(s)
                        changed = True
                continue
            if not s.gated:
                continue
            if now - _parse(s.gated["since"]) < RESUME_MIN:
                continue
            if any(row["label"] == s.gated.get("label") and row.get("unknown") == "rate" for row in rows):
                continue  # §6: a pause ends on a reading, never on an old one that has no rate to project by
            if s.gated.get("sent_at") and s.resume_prompt:
                if self._on_a_dialog(s):
                    continue
                try:
                    await self._submit(s.id, adapters.get(s.adapter), s.resume_prompt)
                except Exception:  # noqa: BLE001 — the mark stands and the resume is tried again
                    log.warning("%s would not take the resume prompt; retrying next tick", s.id)
                    continue
            log.info("%s resumed by the usage gate", s.id)
            s.gated = None
            self.store.save(s)
            changed = True
        self._projection_notes(whole, now)
        if changed:
            await self._push_changes()

    def _gate_windows(self, profile: str, now: datetime, whole: dict[str, Any]) -> list[dict[str, Any]] | None:
        """The gate's **one reader** (§6 *A reading the gate can no longer trust*, TD-233 slice 4):
        the profile's windows as the gate reads them — the reading, or past `usage.max_age` its
        projection (`usage.project`) — which the gate's pass, `_profile_gated` and `gate` all ask, so
        a profile paused on a projection is not restarted or filled the next tick. A metered
        profile's windows are its spend, which does not age, and are never projected."""
        reading = self._gate_reading(profile)
        windows = reading.get("windows")
        if windows is None or self._is_metered(profile):
            return windows
        return usage_mod.project(windows, now, settings_mod.max_age(whole), reading.get("fetched"))

    def _gate_reading(self, profile: str) -> dict[str, Any]:
        """The reading the gate judges `profile` by: its own copy, else its **account's** (TD-456).
        A copy is kept only under a profile a live session runs under (the chip's rule, TD-073), so a
        team wound down while a person's session keeps the account read would start under its own
        profile with *no reading*, which is no gate. A metered profile's reading is its own spend."""
        own = self._usage.get(profile)
        if own is not None or self._is_metered(profile):
            return own or {}
        # the profile's own tool first — the adapter of a record under it — so another tool's
        # account of the same name is never read for it; every polling adapter only for a profile no
        # record names
        mine = list(dict.fromkeys(s.adapter for s in self.sessions.values() if s.profile == profile))
        for name in mine or adapters.names():
            if name not in adapters.names():
                continue
            ad = adapters.get(name)
            if not getattr(ad, "usage_for", None):
                continue
            key, account = _usage_key(ad, name, profile)
            if (acct := self._usage_acct.get(key)) is not None:
                return {**acct, "account": account, "tool": str(getattr(ad, "label", "") or name)}
        return {}

    def _projection_notes(self, whole: dict[str, Any], now: datetime) -> None:
        """The person's two FYI notes on an old reading (§6 *A reading the gate can no longer
        trust*): *pausing on a projection*, once per account while a pause on a projection stands,
        and *usage unknown*, once per account per day, for a window with a reserve that is unknown
        (no rate to project by, or past its reset for longer than `max_age`) while its unattended
        sessions work. Neither under `max_age: off`."""
        limit = settings_mod.max_age(whole)
        if limit is None:
            self._projection_noted.clear()
            return
        paused: dict[str, dict[str, Any]] = {}
        unknown: dict[str, tuple[dict[str, Any], int]] = {}
        for s in self.sessions.values():
            if not s.unattended or s.state in ("exited", "closed", "scheduled"):
                continue
            name = self._usage_name(s.profile)
            if (s.gated or {}).get("projected"):
                paused.setdefault(name, s.gated)
            if s.state != "working":
                continue
            by_label = self._gate_reserves(whole, s.profile) or {}
            for row in settings_mod.lines(by_label, self._gate_windows(s.profile, now, whole), now):
                gone = self._unknown_for(row, now)
                if gone is not None and gone >= limit:
                    got = unknown.get(name)
                    unknown[name] = ({**row, "for": gone}, (got[1] if got else 0) + 1)
                    break
        for name in [n for n in self._projection_noted if n not in paused]:
            self._projection_noted.discard(name)
        for name, mark in paused.items():
            if name in self._projection_noted:
                continue
            self._projection_noted.add(name)
            pr = mark["projected"]
            self._system_note(
                PERSON,
                f"pausing on a projection: no reading of {name} for {_span(pr['age'])} — projected "
                f"{mark['label']} {mark['pct']:g}% ≥ {mark['line']}%, from {pr['from']}% at {pr['rate']:g} a hour. "
                "The pause ends on a reading under the line, at the window's reset, or when max_age or a "
                "reserve is moved (design §6 Usage gate).",
            )
        today = now.date().isoformat()
        for name, (row, n) in unknown.items():
            if self._unknown_noted.get(name) == today:
                continue
            self._unknown_noted[name] = today
            self._system_note(
                PERSON,
                f"usage unknown for {_span(row['for'])}: {name} {row['label']} (was {row['pct']}%), "
                f"{n} unattended session{'s' if n != 1 else ''} working — the gate cannot see this window, "
                "so it pauses nothing on it (design §6 Usage gate).",
            )

    @staticmethod
    def _unknown_for(row: dict[str, Any], now: datetime) -> float | None:
        """How long, in seconds, a gate row has been unknown: its reading's age for `rate`, the
        time since its reset for `reset`; None for a row the gate can read."""
        if row.get("unknown") == "rate":
            return float(row.get("age") or 0)
        if row.get("unknown") == "reset" and (t := usage_mod._instant(row.get("resets"))) is not None:
            return (now - t).total_seconds()
        return None

    def _usage_name(self, profile: str) -> str:
        """The account's name as the chip prints it, *Claude · paul*, else the profile's own."""
        reading = self._usage.get(profile) or {}
        tool, account = reading.get("tool"), reading.get("account")
        return f"{tool} · {account}" if tool and account else str(account or profile)

    async def _subagent_flips(self, now: datetime) -> None:
        """A live subagent goes stale at `STALL_AFTER` with no event to say so (design §4.2 *Working
        on its own*, TD-734): each record's last `subagents_live` is kept, and a record whose reading
        flipped since the last tick is pushed, so the card leaves *working* without waiting for a change.
        A background shell's reading is one with it (`on_its_own`, TD-766): it goes stale at `SHELL_WAIT`."""
        records = [*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values())]
        flipped = False
        seen: dict[str, bool] = {}
        for r in records:
            key = self._address(r)
            seen[key] = live = agent_common.on_its_own(r, now)
            flipped = flipped or self._subagents_were.get(key, live) != live
        self._subagents_were = seen
        if flipped:
            await self._push_changes()

    async def _keep_running(self, now: datetime) -> None:
        """Design §6 *Keeping a team running* (TD-103): rule 1, the crash restart; rule 2, the wanted
        restart; rule 3, the seats; rule 4, the idle nudge; rule 5, the context bound (TD-190);
        rule 6, new work in a lane (TD-195).
        **The restarts run at the home** (§4.4a: policies that start run at the home), over this
        host's records and every node's — a member on a host whose link is down is left as it is and
        looked at again on the next tick, refused rather than queued. **Each record's pass is
        isolated**: one's exception is logged and the tick goes on to the next."""
        if self.mode != "home":
            return
        records = [*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values())]
        for s in records:
            try:
                await self._scheduled_start(s, now)
                await self._crash_restart(s, now)
                if await self._lost_brief(s, now):
                    continue  # replayed: the record is the closed run's, and no other rule acts on it now
                await self._wanted_restart(s, now)
                await self._seat_pass(s, now, records)
                await self._sit_out_close(s)
                await self._brief_restart(s, now)  # first: a member it restarts is typed nothing else
                await self._idle_nudge(s, now)
                await self._idle_open(s, now)
                await self._context_line(s, now)
                await self._cadence_line(s, now)
                await self._held_line(s, now)
                await self._lane_news(s, now)
            except Exception:  # noqa: BLE001 — one record's failure is never the tick's (§6)
                log.exception("%s: the keep-running pass failed", self._address(s))
        if (
            self._seat_count_task is None or self._seat_count_task.done()
        ) and now - self._seat_counted_at > DERIVE_EVERY:
            # detached, as the reports are: `gh` talks to the network, and the tick must not wait on it
            self._seat_counted_at = now
            self._seat_count_task = asyncio.create_task(self._count_seats(records))
        if (self._cadence_task is None or self._cadence_task.done()) and now - self._cadence_read_at > DERIVE_EVERY:
            self._cadence_read_at = now  # rule 10: the script talks to GitHub, so detached as well
            self._cadence_task = asyncio.create_task(self._cadence_pass(records))
        if (
            self._conventions_task is None or self._conventions_task.done()
        ) and now - self._conventions_read_at > DERIVE_EVERY:
            self._conventions_read_at = now  # rule 12: the script runs git, so detached as well
            self._conventions_task = asyncio.create_task(self._conventions_pass(records))
        if (self._held_task is None or self._held_task.done()) and now - self._held_read_at > DERIVE_EVERY:
            self._held_read_at = now  # rule 11: one `gh pr view` a merged PR, so detached as well
            self._held_task = asyncio.create_task(self._held_pass(records, now))
        if (self._brief_task is None or self._brief_task.done()) and now - self._brief_read_at > DERIVE_EVERY:
            self._brief_read_at = now
            self._brief_task = asyncio.create_task(self._brief_pass(now))
        if (
            self.mode == "home" and (self._defs_task is None or self._defs_task.done())
        ) and now - self._defs_read_at > DERIVE_EVERY:
            # a hand edit of the three files is committed on the reports' cadence (§4.9), detached
            self._defs_read_at = now
            self._defs_task = asyncio.create_task(self._commit_defs("edited by hand"))

    async def _brief_pass(self, now: datetime) -> None:
        """Rule 7's mark (design §6 *Keeping a team running*, TD-217 slice 3): each live record of
        this host with a `brief` has its sources read again as merged, in a thread; a difference
        that has stood `BRIEF_SETTLE` with the same blob ids writes `brief_changed: {at, paths}`,
        and files that read as recorded again take it away. A node's member is not read: its files
        are that host's (as the replay, slice 2)."""
        live = [
            s for s in self.sessions.values() if s.brief and s.state not in ("exited", "closed") and not s.superseded_by
        ]
        try:
            read = await asyncio.to_thread(lambda: {s.id: brief_mod.changed(s.brief) for s in live})
        except Exception:  # noqa: BLE001 — a failed read is no mark, never the tick's
            log.exception("the brief pass failed")
            return
        for sid in [k for k in self._brief_differs if k not in read]:
            del self._brief_differs[sid]
        dirty = False
        for s in live:
            if self.sessions.get(s.id) is not s or s.state in ("exited", "closed") or s.superseded_by:
                continue  # forgotten, replaced or ended while the files were read: never saved back
            paths, shas, whole = read[s.id]
            if not whole:
                continue  # a source not read this time says nothing: the mark and the settle stand
            if not paths:
                self._brief_differs.pop(s.id, None)
                if s.brief_changed is not None:
                    s.brief_changed, dirty = None, True
                    self._save(s)
                continue
            was = self._brief_differs.get(s.id)
            if was is None or was[0] != shas:  # a new difference, or another merge: the settle restarts
                self._brief_differs[s.id] = was = (shas, now)
            if now - was[1] >= BRIEF_SETTLE and (s.brief_changed or {}).get("paths") != paths:
                s.brief_changed, dirty = {"at": was[1].isoformat().replace("+00:00", "Z"), "paths": paths}, True
                self._save(s)
        if dirty:
            await self._push_changes()

    def _crashed(self, s: Session, now: datetime) -> bool:
        """Rule 1's test: a supervised, unattended member that is not a seat, `exited` by a
        **natural exit** — `pane` true, the tool left on its own; a kill takes the pane and is a
        person's or a controller's act, never undone — with no declaration, no wrap-up asked, no
        stop time passed, not gated, not suspended, and not already at its ceiling or superseded."""
        return bool(
            s.supervised
            and s.unattended
            and s.seat is None
            and s.state == "exited"
            and s.pane
            and not s.out_of_work
            and not s.restart_wanted
            and not s.wrapup_at
            and not s.wrapup_sent_at
            and not (s.run_until and now >= _parse(s.run_until))
            and not s.gated
            and not s.suspended
            and not s.restart_ceiling
            and not s.superseded_by
            and not s.sit_out
            and not work_mod.sat_out(s)
            and not self._profile_gated(s.profile, now, s.team)
            and not self._just_restarted(s, now)
        )

    @staticmethod
    def _just_restarted(s: Session, now: datetime) -> bool:
        """Whether the tick's last restart of `s` succeeded less than `RESTART_SETTLE` ago (TD-186):
        the record is the new run, whatever the ending run it replaced reports meanwhile."""
        last = s.restarts[-1] if s.restarts and isinstance(s.restarts[-1], dict) else None
        return bool(last and not last.get("error") and _recent(last.get("at"), now, agent_common.RESTART_SETTLE))

    def _profile_gated(self, profile: str, now: datetime, team: str = "") -> bool:
        """Whether `profile` is over a usage line now (`_profile_over`'s reading, as a yes or no)."""
        return self._profile_over(profile, now, team) is not None

    def _profile_over(self, profile: str, now: datetime, team: str = "") -> dict[str, Any] | None:
        """The window `profile` is over its usage line in now, or None (§6 *Usage gate*): the gate's own
        reading — the row `settings.crossed` names, with its `resets` — for a record the gate no longer
        marks (it clears `gated` on an exited one), so a policy does not restart or fill into a pause.
        No reading is no gate, as at the gate (a failure never gates).
        `team` is the record's: its reserve priority lowers the line exactly as it does at the gate
        (TD-146), or a teamed member would be restarted at 65% and paused on the next tick."""
        whole = settings_mod.load()
        windows = self._gate_windows(profile, now, whole)
        if windows is None:
            return None
        by_label = self._gate_reserves(whole, profile) or {}
        extra = settings_mod.team_extra(whole, team)
        return settings_mod.crossed(settings_mod.lines(by_label, windows, now, extra))

    async def _crash_restart(self, s: Session, now: datetime) -> None:
        """Rule 1 (design §6 *Keeping a team running*): restart a member that crashed by replaying
        its launch record — `create` again with what the last supervised create was handed, never
        the definition re-read — which supersedes the record in place under its name (§4.1). Each
        attempt is appended to `restarts` and the list is carried onto the new record, so the count
        survives the restart it counts; a replay that fails keeps its entry with `error` and counts
        all the same, so an unrepairable record reaches the ceiling within three ticks. At
        `RESTART_CEILING` inside `RESTART_WINDOW` the tick writes `restart_ceiling` and stops: the
        session is a person's."""
        if not self._crashed(s, now):
            return
        if s.host != self.host and s.host not in self._link_muxes:
            return  # its link is down: left as it is, looked at again next tick (§4.4a)
        recent = agent_common._counted(s.restarts, now)
        if len(recent) >= RESTART_CEILING:
            s.restart_ceiling = {"at": now_iso(), "count": len(recent)}
            log.warning("%s: %d restarts in %s — the ceiling; it is a person's now", s.id, len(recent), RESTART_WINDOW)
            self._save(s)
            await self._push_changes()
            return
        log.info("%s exited on its own with nothing declared: restarting it (%d in the window)", s.id, len(recent) + 1)
        await self._replay(s, "crash", keep_mail=True)

    async def _lost_brief(self, s: Session, now: datetime) -> bool:
        """A lost brief (design §4.1 *A launch whose hook never comes is recovered*, §6 rule 1, TD-717,
        built by TD-720 slice 2): a supervised, unattended record — a member or a seat — marked *no hook
        since launch* never started its run, so the tick closes it (closer `{by: tick, why: lost-brief}`)
        and replays it once as rule 1 does, `create` with `keep_mail`, `why: lost-brief`, counted in
        `RESTART_CEILING` and never in the fill ceiling; nothing is dirty, so no `restart_blocked` is read.
        A seat's replay repeats its fill's context: the fill's *why it came* line and `seat_filled`. Each
        sender of an `ask` or `steer` still open in the moved inbox is told by a system note. A record
        that came from a `lost-brief` replay and is marked again is not replayed: it is written
        `restart_ceiling: {at, count, why: lost-brief}` and is the person's (*brief lost twice*). A replay
        that failed after its close is retried on the next tick (`_closed_by_tick`). True when the tick
        closed the record, so the rest of the pass leaves the closed run alone (a seat is never filled
        twice)."""
        retry = self._closed_by_tick(s, "lost-brief")
        if not (s.supervised and s.unattended) or s.superseded_by or s.suspended or s.sit_out:
            return False
        if not retry and (s.first_prompt_error != agent_common.FIRST_PROMPT_NO_HOOK or s.state in ("exited", "closed")):
            return False
        if s.restart_ceiling or (s.run_until and now >= _parse(s.run_until)) or s.wrapup_at or s.wrapup_sent_at:
            return False
        if s.gated or self._profile_gated(s.profile, now, s.team):
            return False
        if s.host != self.host and s.host not in self._link_muxes:
            return False  # its link is down: left as it is, looked at again next tick (§4.4a)
        last = s.restarts[-1] if s.restarts and isinstance(s.restarts[-1], dict) else {}
        recent = agent_common._counted(s.restarts, now)
        # a record a lost-brief replay made, marked again; a failed close's entry, with its `error`, is retried
        again = not retry and last.get("why") == "lost-brief" and not last.get("error")
        if again or len(recent) >= RESTART_CEILING:
            count = sum(1 for r in s.restarts if isinstance(r, dict) and r.get("why") == "lost-brief")
            s.restart_ceiling = {"at": now_iso(), "count": count if again else len(recent)}
            if again:
                s.restart_ceiling["why"] = "lost-brief"
            how = "again" if again else "at the ceiling"
            log.warning("%s: its brief was lost %s — it is a person's now", s.id, how)
            self._save(s)
            await self._push_changes()
            return False
        if not retry:
            log.info("%s: no hook reached it since its launch and its brief was not sent: relaunching it", s.id)
            try:
                closer = {"by": "tick", "why": "lost-brief"}
                if s.host == self.host:  # a restart keeps the worktree (§4.1, TD-979)
                    await self.rpc_close(s.id, closer=closer, reap=False)
                else:
                    await self._route_act("close", {"id": s.id, "closer": closer, "reap": False}, None, s.host)
                self._mark_closed(s, "lost-brief")
            except Exception as e:  # noqa: BLE001 — a close that failed is a restart that failed, and counts
                if s.state == "closed":  # a close that failed before it marked the record leaves no mark
                    self._mark_closed(s, "lost-brief")
                s.restarts = [*s.restarts, {"at": now_iso(), "why": "lost-brief", "error": f"close: {e}"}]
                log.warning("%s: the close before a lost-brief replay failed: %s", s.id, e)
                self._save(s)
                await self._push_changes()
                return s.state == "closed"
        closing = None
        if s.seat:
            # the fill's *why it came* line, as rule 3's fill wrote it into the launch record (TD-410)
            with contextlib.suppress(Exception):
                stored = str(self._read_launch(self._address(s)).get("prompt") or "")
                if f"\n\n{FILLED_FOR}" in stored:
                    closing = FILLED_FOR + stored.split(f"\n\n{FILLED_FOR}", 1)[1]
        await self._replay(s, "lost-brief", closing=closing, keep_mail=True)
        new = self.sessions.get(s.id) if s.host == self.host else self.remote.get(s.host, {}).get(s.id)
        if new is None or new is s:
            return True  # the replay failed: its entry says so, and the next tick retries it
        if s.seat:
            new.seat_filled = list(s.seat_filled)
            self._save(new)
        at = datetime.now().astimezone().strftime("%H:%M")
        told: set[str] = set()
        for e in new.inbox:
            if not (e.open and e.kind in ("ask", "steer")) or e.from_ in (PERSON, SYSTEM) or e.from_ in told:
                continue
            told.add(e.from_)
            self._system_note(
                e.from_,
                f"the brief of {s.name} was lost at its launch; it was relaunched at {at} and reads your {e.kind} now",
            )
        if told:
            await self._push_changes()
        return True

    async def _scheduled_start(self, s: Session, now: datetime) -> None:
        """Design §6 *Start time* (TD-152): a `scheduled` record whose instant has passed is created
        from its launch record — `restarts: [{why: start}]`, the record superseded in place with its
        mail — here or at its node; a node whose link is down waits and is looked at next tick. A
        failed start counts, as a failed replay does, and at `RESTART_CEILING` inside the window the
        tick stops trying and says so: the record is a person's."""
        if s.state != "scheduled" or not s.start_at or s.restart_ceiling:
            return
        try:
            due = _parse(s.start_at) <= now
        except ValueError:
            due = False
        if not due:
            return
        if s.host != self.host and s.host not in self._link_muxes:
            return  # its link is down: left as it is, looked at again next tick (§4.4a)
        tries = [
            r
            for r in s.restarts
            if isinstance(r, dict) and r.get("why") == "start" and _recent(r.get("at"), now, RESTART_WINDOW)
        ]
        if len(tries) >= RESTART_CEILING:
            s.restart_ceiling = {"at": now_iso(), "count": len(tries)}
            log.warning("%s: its scheduled start failed %d times — the ceiling; it is a person's now", s.id, len(tries))
            self._save(s)
            await self._push_changes()
            return
        log.info("%s: its start time %s has come — starting it", s.id, s.start_at)
        await self._replay(s, "start", start_of=s.id)

    async def _wanted_restart(self, s: Session, now: datetime) -> None:
        """Rule 2 (design §6, §4.9a): a supervised member that declared `restart_wanted` and is `idle`,
        or `exited` on its own — a kill or a Close is never undone — is closed if it is still there and
        restarted as rule 1 does, under the same ceiling, **only when its git fields are known and show
        nothing uncommitted and nothing unpushed**. With work left it is sent one fixed line naming the
        counts, and `IDLE_NUDGE` later carries `restart_blocked`; the moment the work reads pushed the
        restart runs. An `early` one is left to the person (§4.9a), and so is an unknown git state."""
        rw = s.restart_wanted
        if not (rw and s.supervised and s.unattended) or s.seat is not None or rw.get("early"):
            return
        if s.superseded_by or s.suspended or s.gated or s.sit_out or work_mod.sat_out(s):
            return  # a member its flow sits out is never started again by the tick (§4.9c)
        # A ceiling guards against a crash loop, not a member that has worked since (TD-186): a clean
        # declaration is acted on once the window holds fewer than the ceiling's restarts; the new
        # record carries no mark. Inside the window the mark stands, as it does for rule 1.
        if s.restart_ceiling and self._window_full(s, now):
            return
        closed_by_tick = self._closed_by_tick(s, "wanted")
        if not (s.state == "idle" or (s.state == "exited" and s.pane) or closed_by_tick):
            return
        if (s.run_until and now >= _parse(s.run_until)) or self._profile_gated(s.profile, now, s.team):
            return
        if s.host != self.host and s.host not in self._link_muxes:
            return  # its link is down: left as it is, looked at again next tick (§4.4a)
        left = work_left(s.git)  # the one test a person's Restart and a team's stop make too (TD-250)
        if left == GIT_UNKNOWN:
            return  # an unknown git state is left alone (§6 rule 2)
        if left:
            await self._restart_held(s, now, s.git["dirty"], s.git["unpushed"])
            return
        recent = agent_common._counted(s.restarts, now)
        if len(recent) >= RESTART_CEILING:
            s.restart_ceiling = {"at": now_iso(), "count": len(recent)}
            log.warning("%s: %d restarts in %s — the ceiling; it is a person's now", s.id, len(recent), RESTART_WINDOW)
            self._save(s)
            await self._push_changes()
            return
        log.info("%s wants another run and its work is pushed: restarting it", s.id)
        # the member's own why (*context bound*) kept on the entry, for rule 9's note (§4.9a, TD-468)
        said = {"said": str(rw["why"])} if rw.get("why") else {}
        if s.state == "idle":
            try:
                closer = {"by": "tick", "why": "wanted"}
                if s.host == self.host:  # a restart keeps the worktree (§4.1, TD-979)
                    await self.rpc_close(s.id, closer=closer, reap=False)
                else:
                    await self._route_act("close", {"id": s.id, "closer": closer, "reap": False}, None, s.host)
                self._mark_closed(s, "wanted")
            except Exception as e:  # noqa: BLE001 — a close that failed is a restart that failed, and counts
                # `rpc_close` marks the record closed before its own tail runs, so a failure there
                # leaves it `closed` with nothing replayed: the entry and `closed_for` are what let the
                # next tick retry it (`closed_by_tick`) rather than strand it (review of PR #461)
                if s.state == "closed":  # a close that failed before it marked the record leaves no mark
                    self._mark_closed(s, "wanted")
                s.restarts = [*s.restarts, {"at": now_iso(), "why": "wanted", **said, "error": f"close: {e}"}]
                log.warning("%s: the close before a wanted restart failed: %s", s.id, e)
                self._save(s)
                await self._push_changes()
                return
        await self._replay(s, "wanted", mark=said, keep_mail=True)

    async def _retire_anchors(self) -> None:
        """The retired seats' records (design §4.9 *A definition written before TD-722*, §4.9b *No anchor
        seat*, TD-757): each record whose role is `anchor`, this host's and every node's, is retired at the
        home before rule 3 or rule 8 can resolve a role the presets no longer hold — a closed one, or an
        exited one with nothing uncommitted or unpushed, is forgotten, and a scheduled one's start
        cancelled (a node's removed); a live one is closed first, under
        rule 9's close (`_finished_close`), and forgotten on a later tick. One with work left, or a node's
        whose link is down, is left as it stands and looked at again next tick. A suspended one is the
        person's (§4.8a) and never forgotten here."""
        if self.mode != "home":
            return
        records = [*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values())]
        gone = False
        for s in [r for r in records if r.role == "anchor" and not r.suspended]:
            try:
                git = s.git or {}
                clean = all(isinstance(git.get(k), int) and git[k] == 0 for k in ("dirty", "unpushed"))
                if s.state == "exited" and not clean:
                    continue  # its work is the *exited with unpushed work* row's, and the person's
                if s.state == "scheduled" and s.host == self.host:
                    await self._cancel_start(s)  # a start not yet made would be a seat in a checkout
                    gone = True
                    continue
                if s.state not in ("exited", "closed", "scheduled"):
                    if not await self._finished_close(s, "retired"):
                        continue
                    log.info("%s: the anchor seat is retired — closed", self._address(s))
                if s.host == self.host:
                    pane = (await asyncio.to_thread(self.tmux.main_panes, naming.PREFIX)).get(s.id)
                    if pane is not None:
                        await asyncio.to_thread(self.tmux.kill_session, s.id)
                    self._forget(s.id)
                elif s.host in self._link_muxes:
                    await self._route_act("remove", {"id": s.id}, None, s.host)
                else:
                    continue  # its link is down: looked at again next tick (§4.4a)
                log.info("%s: the anchor seat is retired — its record forgotten", self._address(s))
                gone = True
            except Exception:  # noqa: BLE001 — one record's failure is never the tick's (§6)
                log.exception("%s: retiring the anchor record failed", self._address(s))
        if gone:
            await self._push_changes()

    async def _sit_out_close(self, s: Session) -> None:
        """A sit-out's end (design §4.9c *Switching*, TD-309 slice 5b): a record carrying `sit_out` — a
        person's Apply sent it the wrap-up — is closed by the tick with rule 9's close once it is
        settled (idle, its work known and pushed), and marked `closed_for: {why: sit_out, closed_at}`;
        one that exited, or that a person closed, in the meantime is marked as it stands, `closed_at`
        the close's or, for an exit, the time it exited. A working member finishes what it holds first,
        and one left with work stays open until it reads pushed: waiting tick after tick for it to
        settle is not a retry — no `restarts` entry is written and no replay follows. Never an
        interactive record (§9 invariant 5)."""
        if not s.sit_out or not s.unattended or s.superseded_by or work_mod.sat_out(s):
            return
        if s.state == "exited":
            s.closed_for = {"why": "sit_out", "closed_at": s.closed_at or s.since}
        elif s.state == "closed" or await self._finished_close(s, "sit_out"):
            self._mark_closed(s, "sit_out")
        else:
            return
        log.info("%s: sat out by its team's flow — %s", self._address(s), s.state)
        self._save(s)
        await self._push_changes()

    async def _brief_restart(self, s: Session, now: datetime) -> None:
        """Rule 7's second telling (design §6, TD-217 slice 4): a member whose record carries
        `brief_changed` and that is hook-confirmed `idle`, holds no claim in progress, has declared
        nothing, and has its git fields known and showing nothing uncommitted or unpushed is closed
        and replayed by the tick itself, `why: brief`, under the ceiling as every replay is. Never a
        seat, an interactive session, one past its stop time, into a wrap-up, a gate pause or a
        suspension, and not on a node yet. A working member is told on its `ao` replies instead.

        Its second trigger (§4.9c *Switching*, TD-309 slice 5): a record a person's Apply relaunched
        carries `relaunch`, and is restarted the same way under `why: flow` — the replay reads the
        launch record the relaunch wrote — whether or not the member declared out of work, since the run
        that declared is the one the Apply replaces (TD-358).

        Its third (§4.10 *A lapsed cache is started again, not rung*, TD-467) is the doorbell's, which
        closes and replays the member itself (`_cache_restart`); what reaches here is a `cache` restart
        whose replay failed, retried as the other two are, with the hours and tokens its first try read."""
        cache = self._closed_by_tick(s, "cache")
        why = "brief" if s.brief_changed else "flow" if s.relaunch else "cache" if cache else ""
        if not (why and s.supervised and s.unattended) or s.seat is not None or s.sit_out or work_mod.sat_out(s):
            return
        if s.superseded_by or s.suspended or s.gated or s.host != self.host:
            return
        if s.restart_wanted or (s.out_of_work and not s.relaunch):
            # it declared: rule 2 or the team's next start is what starts it — except that a person's
            # Apply is the person's word, and the old run's `none` does not stand against it (TD-358)
            return
        # either trigger's failed restart is retried under the one that stands now: a person's Apply on a
        # record a `brief` restart left closed clears `brief_changed`, and the mark it left is `brief` (TD-334)
        closed_by_tick = self._closed_by_tick(s, "brief") or self._closed_by_tick(s, "flow") or cache
        if not closed_by_tick:
            if s.state != "idle" or not s.told or s.pending:
                return
            if any(e.status == "claimed" and e.source == "declared" for e in s.progress):
                return  # a claim in progress: the clause on its `ao` replies says it
        if s.wrapup_at or s.wrapup_sent_at or (s.run_until and now >= _parse(s.run_until)):
            return
        if self._profile_gated(s.profile, now, s.team) or self._just_restarted(s, now):
            return
        git = s.git or {}
        clean = (
            git.get("dirty") == 0
            and git.get("unpushed") == 0
            and all(isinstance(git.get(k), int) for k in ("dirty", "unpushed"))
        )
        if not (closed_by_tick or clean):
            return  # work left, or not known: its replies keep saying it, and it declares when it can
        if self._window_full(s, now):
            if not s.restart_ceiling:
                recent = agent_common._counted(s.restarts, now)
                s.restart_ceiling = {"at": now_iso(), "count": len(recent)}
                log.warning("%s: the %s changed at its restart ceiling — it is a person's now", s.id, why)
                self._save(s)
                await self._push_changes()
            return
        log.info("%s: its %s changed and it is idle with its work pushed: restarting it", s.id, why)
        if s.state == "idle":
            try:
                await self.rpc_close(s.id, closer={"by": "tick", "why": why}, reap=False)  # a restart keeps it
                self._mark_closed(s, why)
            except Exception as e:  # noqa: BLE001 — a close that failed is a restart that failed, and counts
                if s.state == "closed":  # a close that failed before it marked the record leaves no mark
                    self._mark_closed(s, why)
                s.restarts = [*s.restarts, {"at": now_iso(), "why": why, "error": f"close: {e}"}]
                log.warning("%s: the close before a %s restart failed: %s", s.id, why, e)
                self._save(s)
                await self._push_changes()
                return
        elif not self._closed_by_tick(s, why):
            # a retry taken from the other trigger's mark: the mark follows the trigger it is replayed under,
            # just before the replay, so a replay that fails again is taken again next tick (TD-334)
            self._mark_closed(s, why)
        last = s.restarts[-1] if why == "cache" else {}
        await self._replay(s, why, mark={k: last[k] for k in ("idle", "context") if k in last}, keep_mail=True)

    async def _cache_restart(self, s: Session, now: datetime) -> bool:
        """§4.10 *A lapsed cache is started again, not rung* (TD-459, built by TD-467): the doorbell has
        decided and charged a ring for `s`; a member idle past `CACHE_LIFETIME` with a context over
        `CACHE_FLOOR` that meets rule 7's precondition is closed and replayed on its brief instead, `why:
        cache` with its `idle` hours and `context` tokens, under the ceiling as every replay is, its mail
        kept. True when the restart took the ring — the close was made, so a replay that fails is the
        tick's to retry (`_brief_restart`); False rings as today: the precondition fails, the window is
        full, a node's member (rule 7 reaches no node yet), or the close failed (its entry counts)."""
        lapsed = agent_common.cache_lapsed(s, now)
        if lapsed is None or s.host != self.host or not agent_common.tick_ready(s, now):
            return False
        if self._profile_gated(s.profile, now, s.team) or self._just_restarted(s, now) or self._window_full(s, now):
            return False
        log.info("%s: idle %sh with %d tokens: restarting it on its brief rather than ringing", s.id, *lapsed.values())
        try:
            await self.rpc_close(s.id, closer={"by": "tick", "why": "cache"}, reap=False)  # a restart keeps it
        except Exception as e:  # noqa: BLE001 — a close that failed is a restart that failed, and counts
            if s.state != "closed":
                s.restarts = [*s.restarts, {"at": now_iso(), "why": "cache", **lapsed, "error": f"close: {e}"}]
                log.warning("%s: the close before a cache restart failed, ringing instead: %s", s.id, e)
                self._save(s)
                return False
        self._mark_closed(s, "cache")
        await self._replay(s, "cache", mark=lapsed, keep_mail=True)
        return True

    @staticmethod
    def _mark_closed(s: Session, why: str) -> None:
        """The tick's mark after its own close for a restart: the rule and the `closed_at` that close
        wrote — the node's own stamp for a node's member, applied from the close's reply — so a later
        Close, which writes its own `closed_at`, no longer matches, even one made at the node that the
        home never hears of as an act (TD-238)."""
        s.closed_for = {"why": why, "closed_at": s.closed_at}

    @staticmethod
    def _closed_by_tick(s: Session, why: str) -> bool:
        """A `closed` record the tick itself closed and failed to replay (`why` rule 2's `wanted` or rule
        7's `brief` or `flow`): it carries the tick's mark for that rule and the close the mark names is still the
        record's (`closed_at` unchanged), and the last `restarts` entry is that rule's and carries
        `error` — both failure paths, the close's and the replay's, write one. Any other close clears the
        mark or writes a new `closed_at`, so a person's Close is never undone (design §6 rule 2; TD-235
        to TD-238)."""
        last = s.restarts[-1] if s.restarts and isinstance(s.restarts[-1], dict) else {}
        mark = s.closed_for if isinstance(s.closed_for, dict) else {}
        return (
            s.state == "closed"
            and mark.get("why") == why
            and bool(s.closed_at)
            and mark.get("closed_at") == s.closed_at
            and last.get("why") == why
            and bool(last.get("error"))
        )

    @staticmethod
    def _window_full(s: Session, now: datetime) -> bool:
        recent = agent_common._counted(s.restarts, now)
        return len(recent) >= RESTART_CEILING

    async def _restart_held(self, s: Session, now: datetime, dirty: int, unpushed: int) -> None:
        """Rule 2 with work left: one fixed send, once, naming the counts from the record and never a
        session's words; `IDLE_NUDGE` after it (after the declaration, where nothing could be typed)
        the record carries `restart_blocked` and the Inbox lists it."""
        if not s.restart_blocked_sent_at and s.state == "idle" and s.host == self.host:
            line = (
                f"[shiftlead] your restart is held: {dirty} uncommitted and {unpushed} unpushed in your checkout "
                "— commit and push them, and the host agent restarts you"
            )
            if await self._policy_send(s, line):
                s.restart_blocked_sent_at = now_iso()
                self._save(s)
        start = s.restart_blocked_sent_at or (s.restart_wanted or {}).get("at")
        if not s.restart_blocked and start and now - _parse(str(start)) >= IDLE_NUDGE:
            s.restart_blocked = {"at": now_iso(), "dirty": dirty, "unpushed": unpushed}
            log.info("%s: its restart is held by work left — the person's now", s.id)
            self._save(s)
            await self._push_changes()

    async def _idle_nudge(self, s: Session, now: datetime) -> None:
        """Rule 4 (design §6): a supervised member hook-confirmed `idle` for `IDLE_NUDGE` with open work
        — a lane reference not done or dropped, a declared claim not done or dropped, for a seat a
        question waiting, or an outcome owed to the person (TD-258) — and nothing declared, is sent
        one fixed line naming it, once per idle
        stretch (`nudged_at`; a stretch ends when the state changes). It spends no wake budget. The
        send needs the pane here: a node's member is not nudged yet (TD-103)."""
        if not (s.supervised and s.unattended) or s.superseded_by or s.suspended or s.host != self.host:
            return
        if s.state != "idle" or not s.told or s.pending or s.out_of_work or s.restart_wanted:
            return
        if agent_common.on_its_own(s, now):
            return  # its own work runs — a subagent or a shell — and its card says *working* (§4.2, TD-766)
        idle = agent_common.idle_from(s)
        if idle is None or now - idle < IDLE_NUDGE:
            return  # counted from the later of `since`, `subagent_at` and `shells_at` (TD-734, TD-766)
        if s.nudged_at and _parse(s.nudged_at) >= _parse(s.since):
            return  # this stretch was nudged already: never a second before the first is answered
        if s.wrapup_at or s.wrapup_sent_at or (s.run_until and now >= _parse(s.run_until)):
            return
        if s.gated or self._profile_gated(s.profile, now, s.team):
            return
        if s.balance_refused and self._balance_of(s):
            return  # refused a claim over its team's line (§6 *Balance*): idling is what it was told to do
        line = self._nudge_line(s)
        if line and await self._policy_send(s, line):
            s.nudged_at = now_iso()
            log.info("%s: idle %s with work open — nudged", s.id, IDLE_NUDGE)
            self._save(s)
            await self._push_changes()

    @staticmethod
    def _open_ref(s: Session, skip: Collection[str] = ()) -> str | None:
        """A member's first open reference (rule 4): a lane reference, then a declared claim not in
        `skip` (the waiting claims, TD-820), with no `done` or `dropped` entry."""
        ended = {e.ref for e in s.progress if e.status in ("done", "dropped")}
        claimed = [e.ref for e in s.progress if e.source == "declared" and e.status == "claimed" and e.ref not in skip]
        return next((r for r in [*lane_refs(s.lane), *claimed] if r not in ended), None)

    def _waiting_claims(self, s: Session) -> list[ProgressEntry]:
        """Rule 5's *waiting claims* (design §6, §4.2 *Waiting*, TD-820): `s`'s declared claims whose
        PR is open — the claim's `pr`, not read closed, or its `review_pr` — **and** whose next move is
        someone else's: the person inbox holds an open `ask` or `steer` of `s`'s about the reference
        (`work.waiting_of`), or a record's `prs_waiting.asks` holds `s`'s ask for that PR. Read for
        rules 4 and 5 and the replay's carry alone; rule 9 reads the held-ask half itself
        (`work.held_asks`, TD-854), and rule 3, the flow's restart and §4.10 still read every claim as
        in progress."""
        claims = [
            e
            for e in s.progress
            if e.source == "declared" and e.status == "claimed" and (e.pr or e.review_pr) and e.why != PR_CLOSED
        ]
        if not claims:
            return []
        me = (s.id, s.host or self.host)

        def mine(address: Any) -> bool:
            sid, host = naming.split_address(str(address or ""))
            return (sid, host or self.host) == me

        asked = {q["ref"] for k, qs in work_mod.waiting_of(self.person_inbox).items() if mine(k) for q in qs}
        handed: set[int] = set()
        for r in self._graph().values():
            for a in (r.prs_waiting(home=self.host) or {}).get("asks") or ():
                if isinstance(a, dict) and mine(a.get("from")) and isinstance(a.get("pr"), int):
                    handed.add(a["pr"])
        opened = ((self._repos.get(s.repo or "") or {}).get("prs") or {}).get("open")
        numbers = {p.get("number") for p in opened if isinstance(p, dict)} if isinstance(opened, list) else None

        def open_pr(e: ProgressEntry) -> int | None:
            if e.review_pr:
                return e.review_pr  # held only while that PR is open (TD-150)
            return e.pr if numbers is None or e.pr in numbers else None

        return [e for e in claims if (n := open_pr(e)) and (e.ref in asked or n in handed)]

    async def _idle_open(self, s: Session, now: datetime) -> None:
        """*idle · open work* (design §6 rule 3, TD-259): `idle_open: {at, ref}` on a supervised
        member, not a seat, that rule 4 nudged in this idle stretch and that is still hook-confirmed
        idle `IDLE_NUDGE` after the nudge with work open and nothing declared. It stands while the
        stretch does — the reference it names is the one open when it was written, None where the
        work is an outcome owed alone — and is cleared
        when the state changes, the work closes or the member declares."""
        try:
            stretch = bool(
                s.state == "idle" and s.nudged_at and s.since and _parse(s.nudged_at) >= _parse(s.since)
            ) and not (s.out_of_work or s.restart_wanted or s.superseded_by)
        except ValueError:
            stretch = False
        ref = self._open_ref(s) if stretch and s.seat is None else None
        # an outcome owed is open work too, as rule 4's nudge counts it (TD-258): the mark names no reference then
        still = ref is not None or bool(stretch and s.seat is None and s.owed())
        if s.idle_open:
            if not still:
                s.idle_open = None
                self._save(s)
                await self._push_changes()
            return
        if not still or not (s.supervised and s.unattended) or s.suspended:
            return
        if not s.told or s.pending or now - _parse(str(s.nudged_at)) < IDLE_NUDGE:
            return
        if agent_common.on_its_own(s, now):
            return  # not marked while its own work runs (§6 rule 4, TD-734, TD-766)
        s.idle_open = {"at": now_iso(), "ref": ref}
        log.info("%s: still idle %s after the nudge with %s open — idle · open work", s.id, IDLE_NUDGE, ref or "a debt")
        self._save(s)
        await self._push_changes()

    async def _context_line(self, s: Session, now: datetime) -> None:
        """Rule 5 (design §6, TD-190): a supervised member whose context reading is past its role's
        bound is told so by one fixed line once it is hook-confirmed `idle` and holds no claim in
        progress — between entries, never mid-turn — and again after `CONTEXT_AGAIN` while it is
        still idle and over (`context_sent_at`). A wrap-up under way or a gate pause beats it, as it
        beats the doorbell; a member that declared already (out of work, a restart wanted) is not
        told. The send needs the pane here: a node's member is not told yet, as rule 4's is not."""
        if not (s.supervised and s.unattended) or s.superseded_by or s.suspended or s.host != self.host:
            return
        if s.seat is not None or s.out_of_work or s.restart_wanted:
            return
        over = context_over_text({"context": s.context, "context_bound": s.context_bound})
        if not over:
            return
        if s.state != "idle" or not s.told or s.pending:
            return
        waiting = self._waiting_claims(s)
        if any(e.status == "claimed" and e.source == "declared" and e not in waiting for e in s.progress):
            return  # a claim in progress: the clause on its `ao` replies says it, and it declares after
        if s.context_sent_at and now - _parse(s.context_sent_at) < CONTEXT_AGAIN:
            return
        if s.wrapup_at or s.wrapup_sent_at or (s.run_until and now >= _parse(s.run_until)):
            return
        if s.gated or self._profile_gated(s.profile, now, s.team):
            return
        line = f"[shiftlead] {over.replace(' over the ', ', over your ', 1)} — take nothing new: push, ledger, then "
        line += '`ao progress restart --why "context bound"`'
        if waiting:
            line += "; " + ", ".join(dict.fromkeys(f"#{e.review_pr or e.pr}" for e in waiting)) + " carry over"
        if await self._policy_send(s, line):
            s.context_sent_at = now_iso()
            log.info("%s: %s — told", s.id, over)
            self._save(s)
            await self._push_changes()

    @staticmethod
    def _cadence_member(s: Session) -> bool:
        """Rule 10's subject: a supervised member, not a seat, on the record that is its run now."""
        return bool(s.supervised and s.seat is None and not s.superseded_by)

    def _is_record(self, s: Session) -> bool:
        """Whether `s` is still the record under its address — not forgotten, replaced by a
        restart, or a node's replica read anew — so a read made off the loop is saved to it."""
        held = self.sessions if s.host == self.host else self.remote.get(s.host, {})
        return held.get(s.id) is s

    async def _cadence_pass(self, records: list[Session]) -> None:
        """Rule 10's read (design §6, TD-258), detached on the reports' cadence: for each supervised
        member, not a seat, each `progress` entry `done` with a `pr` — declared or derived — whose
        `checks` entry is missing, `unknown`, older than the `done`, or read at another head, the
        repo's gate (§5 *The seams*, TD-1011: agent-cadence's script) is run in the registry root the
        record's `repo` names, **one PR per run**, the one longest unread first. A root with no gate is
        unserved: nothing is run there and nothing written. A root the home holds no reading of, a head
        `gh` cannot give and a run with no reading write nothing."""
        try:
            due: list[tuple[str, Session, int, str]] = []
            for s in records:
                if not self._cadence_member(s) or s.repo not in self._repos:
                    continue
                dones: dict[int, str] = {}
                for e in s.progress:
                    if e.status == "done" and isinstance(e.pr, int):
                        # a derived entry is written anew at every derivation, so only the
                        # member's own word dates a new report
                        dones[e.pr] = max(dones.get(e.pr, ""), e.at if e.source == "declared" else "")
                for pr, done_at in dones.items():
                    old = cadence_mod.entry_of(s.checks, pr)
                    if cadence_mod.settled(old) and not cadence_mod.stale(old, done_at):
                        continue  # a merged or closed PR's head no longer moves: the read stands
                    due.append((str((old or {}).get("at") or ""), s, pr, done_at))
            due.sort(key=lambda d: (d[0], d[2]))
            gates: dict[str, str | None] = {}
            for _, s, pr, done_at in due:
                root = str(s.repo)
                if root not in gates:
                    gates[root] = await asyncio.to_thread(cadence_mod.gate, root)
                if gates[root] is None:
                    continue  # unserved (§5): no gate run, nothing written
                # the repo reading's head first (TD-332): `gh` is asked only for a PR that reading lacks
                head = cadence_mod.head_from((self._repos.get(root) or {}).get("prs"), pr)
                if head is None:
                    head = await asyncio.to_thread(cadence_mod.head, root, pr)
                if head is None:
                    continue
                sha, state = head
                merged, closed = state == "merged", state == "closed"
                old = cadence_mod.entry_of(s.checks, pr)
                if old and not cadence_mod.stale(old, done_at) and old.get("sha") == sha:
                    if bool(old.get("merged")) == merged and bool(old.get("closed")) == closed:
                        continue
                    if closed and not old.get("merged"):
                        # closed unmerged at the head it was read at: the read stands, settled — written
                        # only to the record still under its address, as a read is
                        if self._is_record(s) and self._cadence_member(s):
                            old["closed"] = True
                            self._save(s)
                        continue
                got = await asyncio.to_thread(cadence_mod.check, root, pr)
                if got is None or not self._is_record(s) or not self._cadence_member(s):
                    continue
                old = cadence_mod.entry_of(s.checks, pr)
                new = cadence_mod.record(old, pr, sha, merged, got, now_iso(), closed=closed)
                s.checks = [*(c for c in s.checks if c.get("pr") != pr), new]
                for e in s.progress:  # its read at the head clears a `done`'s `ci: pending` (TD-637)
                    if e.status == "done" and e.pr == pr and e.ci == "pending":
                        e.ci = None
                log.info("%s: PR #%s read by the cadence check: %s", self._address(s), pr, cadence_mod.said(new))
                self._save(s)
                break  # one PR per run
        except Exception:  # noqa: BLE001 — a detached task: log it, and the next pass tries again
            log.exception("the cadence check's pass failed")
        finally:
            await self._push_changes()

    async def _cadence_line(self, s: Session, now: datetime) -> None:
        """Rule 10's telling (design §6, TD-258), rule 5's two ways. A first fail of an open PR is
        one fixed line typed into the composer of an unattended member of this host that is
        hook-confirmed `idle` — never at a dialog, a wrap-up or a gate pause — and for a member
        that is working, on a node or attended it is the clause every `ao` reply carries
        (`cadence.clause`, read at the home); either way `told` marks it. `read_by` is written the
        first time a reader's reply on the PR's `ask` is seen in the record's mail, and kept."""
        if not self._cadence_member(s) or not s.checks:
            return
        dirty = False
        for pr in [int(c["pr"]) for c in s.checks]:
            c = cadence_mod.entry_of(s.checks, pr)
            if c is None:
                continue
            if not c.get("read_by") and (who := cadence_mod.read_by(s, pr)):
                c["read_by"], dirty = who, True
            if not cadence_mod.untold(c):
                continue
            typed = s.host == self.host and s.unattended and not s.suspended
            if typed and s.state == "idle":
                if not s.told or s.pending or s.wrapup_at or s.wrapup_sent_at:
                    continue
                if s.gated or self._profile_gated(s.profile, now, s.team):
                    continue
                ref = next((e.ref for e in reversed(s.progress) if e.status == "done" and e.pr == pr), "")
                if not await self._policy_send(s, cadence_mod.line(c, ref)):
                    continue  # not typed: the next tick looks again
                # the detached read may have replaced the list while the line was typed
                c = cadence_mod.entry_of(s.checks, pr)
                if c is None:
                    continue
            elif typed and s.state != "working":
                continue  # exited, closed or at a dialog: nobody reads a reply now
            c["told"], dirty = now_iso(), True
        if dirty:
            self._save(s)
            await self._push_changes()

    @staticmethod
    def _conventions_member(s: Session) -> bool:
        """Rule 12's subject: a supervised member, not a seat (every fill starts cold, and the hook
        tells it), not finished (never sent to; its next start is told at its start), on the record
        that is its run now — one not running (`scheduled`, `exited`, `closed`) starts again as a
        new record, which the hook tells."""
        if s.state in ("scheduled", "exited", "closed"):
            return False
        return bool(s.supervised and s.seat is None and not s.out_of_work and not s.superseded_by)

    async def _conventions_pass(self, records: list[Session]) -> None:
        """Rule 12 (design §6, TD-258), detached on the reports' cadence: `scripts/cadence_changes.py
        --json` is run once in each registry root that carries it and holds a member to tell, and
        each such member's `conventions_seen` is written from the reading — at the first one after
        its create, the headings landed at or before `created`; later, a heading it does not hold
        that landed after `created` is one `note` from `system` and joins it. The doorbell does
        the waking; nothing is typed here. A root with no script, or a run with no reading,
        writes nothing. In a pinned repo the note carries each entry's body and names the file by the
        resolver's command (TD-1046); a root's empty reading, and a pinned root whose tree cannot be
        made, are logged at info once while they last (`_conventions_quiet`)."""
        try:
            by_root: dict[str, list[Session]] = {}
            for s in records:
                if self._conventions_member(s) and s.repo and s.repo in self._repos:
                    by_root.setdefault(str(s.repo), []).append(s)
            for root, members in by_root.items():
                pinned = await asyncio.to_thread(cadence_mod.pinned, root)
                if not await asyncio.to_thread(conventions_mod.has_script, root):  # a pinned tree may fetch
                    if pinned:
                        payload, why = await asyncio.to_thread(cadence_mod.tree, root)  # cached
                        if payload is not None:
                            why = f"no scripts/{conventions_mod.PINNED_SCRIPT} in the tree"
                        self._conventions_once(root, f"pinned, no tree: {why}")
                    continue
                self._conventions_ended(root, "pinned, no tree: ")
                got, why = await asyncio.to_thread(conventions_mod.read, root)
                if got is None:
                    log.info("%s: %s gave no reading — %s", root, conventions_mod.PINNED_SCRIPT, why)
                    continue
                if not got["entries"]:
                    self._conventions_once(
                        root,
                        "no entries — the checkout's pin may predate agent-cadence's change"
                        if pinned
                        else "no entries — the checkout may predate the migration, "
                        "or still hold docs/cadence-sync.lock beside its pin",
                    )
                else:
                    self._conventions_ended(root, "no entries — ")
                for s in members:
                    if not self._is_record(s) or not self._conventions_member(s):
                        continue  # replaced, or declared out of work, while the script ran
                    first = s.conventions_seen is None
                    sorted_ = conventions_mod.sort(
                        got["entries"], (s.conventions_seen or {}).get("headings"), s.created
                    )
                    if sorted_ is None:
                        continue
                    seen, told = sorted_
                    if not first and seen == (s.conventions_seen or {}).get("headings"):
                        continue
                    s.conventions_seen = {"at": now_iso(), "headings": seen}
                    if told:
                        path = None
                        if pinned:  # a node's container has neither the home's Python nor its launcher
                            on_home = s.host == self.host
                            path = cadence_mod.typed("path", "cadence-changes.md") if on_home else NODE_CHANGES
                        self._system_note(self._address(s), conventions_mod.note(told, got["ref"], path))
                        where = "agent-cadence's changes" if pinned else "docs/cadence-changes.md"
                        log.info("%s: told of %d new in %s", self._address(s), len(told), where)
                    self._save(s)
        except Exception:  # noqa: BLE001 — a detached task: log it, and the next pass tries again
            log.exception("the conventions pass failed")
        finally:
            await self._push_changes()

    def _conventions_once(self, root: str, line: str) -> None:
        """Rule 12's info line for `root`, logged once while it lasts (TD-1046)."""
        if (root, line) not in self._conventions_quiet:
            self._conventions_quiet.add((root, line))
            log.info("%s: %s", root, line)

    def _conventions_ended(self, root: str, prefix: str) -> None:
        """The condition of `root`'s lines starting `prefix` has ended: the next time it holds, it is logged."""
        self._conventions_quiet -= {
            (r, line) for r, line in self._conventions_quiet if r == root and line.startswith(prefix)
        }

    @staticmethod
    def _held_member(s: Session) -> bool:
        """Rule 11's subject: a supervised member whose record carries `review`, on the record that
        is its run now."""
        return bool(s.supervised and s.review and not s.superseded_by)

    async def _held_pass(self, records: list[Session], now: datetime) -> None:
        """Rule 11's read (design §6, TD-258), detached on the reports' cadence: for each supervised
        member whose record carries `review`, each `progress` entry `done` with a `pr` is read once
        it has merged — its files against the record's `held:` globs, in the registry root the
        record's `repo` names, `held.READS` PRs a run, the longest unread first. A PR touching no
        held path, one merged before the record was created, and one its reader replied on (`held.
        read_by`) are settled, in memory: a restarted home reads each once more, and since mail
        is pruned, a PR merged longer ago than half `mail.MAIL_RETENTION` is settled unjudged. A
        held PR with no reply `held.GRACE` after its merge is a **crossing**: an entry on `held_missed` and one
        `system` note to the person. A PR not merged yet, a failed read and a root the home holds
        no reading of write nothing and are read again."""
        try:
            due: list[tuple[float, Session, int]] = []
            for s in records:
                if not self._held_member(s) or s.repo not in self._repos:
                    continue
                addr = self._address(s)
                crossed = {c.get("pr") for c in s.held_missed}
                for pr in {e.pr for e in s.progress if e.status == "done" and isinstance(e.pr, int)}:
                    if pr not in crossed and (addr, s.created, pr) not in self._held_settled:
                        due.append((self._held_tried.get((addr, pr), 0.0), s, pr))
            due.sort(key=lambda d: (d[0], d[2]))
            for _, s, pr in due[: held_mod.READS]:
                addr = self._address(s)
                self._held_tried[(addr, pr)] = time.monotonic()
                try:
                    files, merged = await asyncio.to_thread(held_mod.pr_read, pr, str(s.repo))
                except RuntimeError:
                    continue  # no reading: never a crossing by default
                if merged is None or not self._is_record(s) or not self._held_member(s):
                    continue
                paths = held_mod.held_paths(files, s.review)
                # mail is pruned: past half its retention the reply that would clear a PR may be
                # gone (a restarted home, a first promote), and that is no reading, never a crossing
                old = mail.MAIL_RETENTION is not None and now - merged > mail.MAIL_RETENTION / 2
                if not paths or merged <= _parse(s.created) or held_mod.read_by(s, pr, files) or old:
                    self._held_settled.add((addr, s.created, pr))
                    self._held_tried.pop((addr, pr), None)
                    continue
                if now - merged < held_mod.GRACE or any(c.get("pr") == pr for c in s.held_missed):
                    continue  # the reader merges, then replies: looked at again
                self._held_settled.add((addr, s.created, pr))  # told once, whatever clears the entry
                self._held_tried.pop((addr, pr), None)
                entry = held_mod.crossing(pr, paths, now_iso())
                s.held_missed = [*s.held_missed, entry]
                reader = str((s.review or {}).get("reader") or "")
                self._system_note(PERSON, held_mod.note(entry, reader, addr))
                log.info("%s: %s", addr, held_mod.said(entry, reader))
                self._save(s)
        except Exception:  # noqa: BLE001 — a detached task: log it, and the next pass tries again
            log.exception("the held-path pass failed")
        finally:
            await self._push_changes()

    async def _held_line(self, s: Session, now: datetime) -> None:
        """Rule 11's telling (design §6, TD-258), rule 5's two ways. A crossing the member has not
        been told of is one fixed line typed into the composer of an unattended member of this host
        that is hook-confirmed `idle` — never at a dialog, a wrap-up or a gate pause; a member that
        is working, on a node or attended reads it as the clause on its next `ao` reply
        (`held.clause`, which the reply marks told). `told` marks it either way."""
        if not self._held_member(s) or not held_mod.untold(s.held_missed):
            return
        if not (s.host == self.host and s.unattended and not s.suspended and s.state == "idle"):
            return
        if not s.told or s.pending or s.wrapup_at or s.wrapup_sent_at:
            return
        if s.gated or self._profile_gated(s.profile, now, s.team):
            return
        reader = str((s.review or {}).get("reader") or "")
        for pr in [c.get("pr") for c in held_mod.untold(s.held_missed)]:
            c = next((c for c in held_mod.untold(s.held_missed) if c.get("pr") == pr), None)
            if c is None or not await self._policy_send(s, held_mod.line(c, reader)):
                return  # not typed: the next tick looks again
            # the detached read may have replaced the list while the line was typed
            for c in s.held_missed:
                if c.get("pr") == pr:
                    c["told"] = now_iso()
            self._save(s)
            await self._push_changes()
            return  # one line a tick: the composer holds the one just typed

    async def _lane_news(self, s: Session, now: datetime) -> None:
        """Rule 6 (design §6, TD-195): a supervised member, not a seat, that declared out of work is
        told when its lane gains entries. The first tick that sees the declaration writes
        `lane_seen` — the ids in its repo's ledger reading that match its lane; a later reading
        holding a matching id not in it, while the member is live, not winding down, not gated and
        not suspended, becomes one `note` from `system` naming the new ids, which are then added,
        so each is told once. The doorbell does the waking; nothing is typed here. No reading —
        the repo not in this home's registry, or its file unreadable — writes nothing.

        **The first write is the ledger at the declaration** (TD-227): the file as the last commit of
        `origin/<default>` before `out_of_work.at` held it, so an entry merged between the
        declaration and a first tick that comes late (a promote, a home down) is new and is told;
        where the history cannot be read, the reading at this tick, the log saying which."""
        if not (s.supervised and s.out_of_work) or s.seat is not None or s.superseded_by:
            return
        facts = self._repos.get(s.repo or "") or {}
        led = facts.get("ledger") or {}
        if "error" in led or not isinstance(led.get("entries"), list) or seams_mod.unserved(facts):
            return  # an unserved repo's lane reads empty (§5 *The seams*, TD-1011)

        def matching(got: list[Any]) -> list[str]:
            return [
                str(e["id"])
                for e in got
                if isinstance(e, dict) and e.get("id") and ledger_mod.lane_matches(s.lane, e, s.team)
            ]

        ledger_ids = matching(led["entries"])
        # the board's decided lines are work in the lane too (§6 rule 6, TD-384): never in the first
        # `lane_seen`, so one that sat unclaimed while its member declared is told on the next tick
        order_ids = [i for i in matching(_orders(self._repos.get(s.repo or ""))) if i not in ledger_ids]
        ids = ledger_ids + order_ids
        if s.lane_seen is None:
            seen, read = list(ledger_ids), "the reading at this tick"
            root, rel = (self._repos.get(s.repo or "") or {}).get("root") or s.repo, s.ledger or led.get("path")
            try:
                at = _parse(str((s.out_of_work or {}).get("at")))
            except (ValueError, TypeError):
                at = None
            if root and rel and at is not None:
                decl = dict(s.out_of_work or {})
                then, why, tip = await asyncio.to_thread(self._ledger_then, s, str(root), str(rel), at)
                if s.out_of_work != decl or s.lane_seen is not None:
                    return  # the declaration moved while git was read: the next tick looks afresh
                if then is not None and tip is not None:
                    # an entry the checkout holds and origin's tip does not (a branch checked out here)
                    # is seen, untold, or every tick after this one, which reads the checkout, would
                    # tell it as new — and again after each `none`
                    seen = matching(then)
                    on_tip = set(matching(tip))
                    seen += [i for i in ledger_ids if i not in on_tip and i not in seen]
                    read = f"the ledger at the declaration ({why}), the checkout's own entries seen"
                else:
                    read = f"the reading at this tick ({why})"
            s.lane_seen = {"at": now_iso(), "ids": seen}
            self._save(s)
            log.info("%s: lane_seen from %s", self._address(s), read)
            # and on: an entry merged since the declaration is told on this tick
        # the lane's memory, never the ledger's (§6 rule 6, TD-407): an id the lane no longer takes
        # leaves it, written for a gone member as for a live one, so an entry that comes back is news
        pruned, new = work_mod.reread(s, [*led["entries"], *_orders(self._repos.get(s.repo or ""))])
        if pruned is not s.lane_seen:
            s.lane_seen = pruned
            self._save(s)
        seen = set(s.lane_seen.get("ids") or [])
        drops = self._lane_drops(s, [i for i in ids if i in seen])
        if not (new or drops) or s.state in ("exited", "closed") or s.suspended:
            return
        if s.wrapup_at or s.wrapup_sent_at or (s.run_until and now >= _parse(s.run_until)):
            return
        if s.gated or self._profile_gated(s.profile, now, s.team):
            return
        if s.balance_refused and self._balance_of(s):
            return  # its claims are refused while its team is over its line (§6 *Balance*): told once it clears
        # a new id a live sibling already holds is its holder's (TD-899): seen untold, so only its
        # release is news, as a dropped lease — else every `none` beside a held decided line is told it
        leased = self._leased(s, new)
        s.lane_seen = {**s.lane_seen, "at": now_iso(), "ids": [*s.lane_seen.get("ids", []), *new]}
        new = [i for i in new if i not in leased]
        if not (new or drops):
            self._save(s)
            return
        if drops:
            s.lane_seen["dropped"] = {**(s.lane_seen.get("dropped") or {}), **{i: at for i, _, at in drops}}
        told = [*new, *(f"{i} (dropped by {who})" for i, who, _ in drops)]
        named = ", ".join(told[:LANE_NEWS_NAMED]) + (
            f" and {len(told) - LANE_NEWS_NAMED} more" if len(told) > LANE_NEWS_NAMED else ""
        )
        count = f"{len(told)} entr{'y' if len(told) == 1 else 'ies'}"
        self._system_note(
            self._address(s),
            f"your lane gained {count} since you declared out of work: {named} — read the "
            f"{'ledger and the board' if any(i in order_ids for i in new) else 'ledger'} on "
            "`origin/main`, then claim one or declare again",
        )
        self._save(s)
        log.info("%s: told of %s new in its lane", self._address(s), count)

    def _ledger_then(self, s: Session, root: str, rel: str, at: datetime) -> tuple[Any, str, Any]:
        """The ledger's entries as `origin/<default>` held them before `at`, what was read, and its tip read as
        the checkout's reading is (`(None, why, None)` where the history cannot be read) — rule 6's first write
        at a declaration (TD-227) and rule 8's baseline at a record's end (TD-781). Blocking: git is read."""
        name = Path(root).name
        commit = self._live_commits().get(name)
        resolve = ledger_mod.Registry(hosts.local_host().repos())
        # a live check stood in the lane at `at` when its build was live then (§4.9b, §6 rule 6): known when
        # the promote that made today's live commit live concluded before it, so the ledger then is read
        # against that commit; unknown, it is read without, and a check live now is told once as new
        was = promote_mod.last(name) or {}
        try:
            before = bool(commit) and was.get("sha") == commit and _parse(str(was.get("at"))) <= at
        except (ValueError, TypeError):
            before = False
        live = ledger_mod.LiveReader(root, commit)
        then, why = ledger_mod.entries_before(root, rel, at, resolve=resolve, live=live if before else None)
        if then is None:
            return then, why, None
        # the tip read as the checkout's reading is, with its live checks' `live`, or a live one would read
        # as the checkout's own and be seen untold
        tip = ledger_mod.entries_before(root, rel, None, resolve=resolve, live=live)[0]
        # both marked by the settle clock as it stands, so an entry still settling is not seen now and is told
        # once it settles (§4.4, TD-710); `then` as the clock stood at `at`, so one settling then is told when
        # it settles
        facts = self._repos.get(s.repo or "") or {}
        remote = str(facts.get("remote") or "")
        for got, when in ((then, at), (tip, datetime.now(UTC))):
            if got is not None and not seams_mod.unserved(facts):  # no settle in an unserved repo (TD-1011)
                TickMixin._settle(root, remote, got, when, fresh=False)
        return then, why, tip

    def _lane_drops(self, s: Session, held: list[str]) -> list[tuple[str, str, str]]:
        """Rule 6's dropped lease (design §6, TD-258): of the ids `s` has seen and its lane still
        matches, each one a record of the same repo let go — a `dropped` entry in its `progress`
        later than `s`'s declaration and than the drop `lane_seen` holds for the id — and that no
        live record holds a lease on now, as `(id, the dropper's name, the drop's instant)`, the
        latest drop of each. An instant that cannot be read is no drop."""
        if not held:
            return []
        told = s.lane_seen.get("dropped") if isinstance((s.lane_seen or {}).get("dropped"), dict) else {}

        def instant(v: Any) -> datetime | None:
            try:
                at = _parse(str(v))
            except ValueError:
                return None
            return at if at.tzinfo else at.replace(tzinfo=UTC)

        declared = instant((s.out_of_work or {}).get("at"))
        if declared is None:
            return []
        # a kept instant that cannot be read is no memory of that id's drop, and the others stand
        since = {i: max(declared, instant(told.get(i)) or declared) for i in held}
        last: dict[str, tuple[datetime, str, str]] = {}
        leased = self._leased(s, held)  # taken again since: the lease's holder is who it is news to
        for r in self._repo_peers(s):
            for e in r.progress:
                if e.ref not in since or e.status != "dropped":
                    continue
                at = instant(e.at)
                if at is not None and at > since[e.ref] and (e.ref not in last or at > last[e.ref][0]):
                    last[e.ref] = (at, r.name, e.at)
        return [(i, last[i][1], last[i][2]) for i in held if i in last and i not in leased]

    def _repo_peers(self, s: Session) -> list[Session]:
        """Every other record of `s`'s repo, here and on the nodes."""
        every = (*self.sessions.values(), *(r for recs in self.remote.values() for r in recs.values()))
        return [r for r in every if r is not s and r.repo and r.repo == s.repo]

    def _leased(self, s: Session, ids: Collection[str]) -> set[str]:
        """The `ids` another live record of `s`'s repo holds an unexpired declared lease on (design §4.8
        *A claim is a lease*, `LEASE_TTL`). An instant that cannot be read holds nothing."""
        if not ids:
            return set()
        now = datetime.now(UTC)
        out: set[str] = set()
        for r in self._repo_peers(s):
            if r.state in ("exited", "closed", "scheduled"):
                continue
            for e in r.progress:
                if e.ref not in ids or e.status != "claimed" or e.source != "declared":
                    continue
                try:
                    at = _parse(str(e.at))
                except ValueError:
                    continue
                if now - (at if at.tzinfo else at.replace(tzinfo=UTC)) < LEASE_TTL:
                    out.add(e.ref)
        return out

    async def _work_marks(self, now: datetime) -> None:
        """Rule 8 (design §6 *Work for a team that wound down*, TD-227): on every tick at the home,
        each team read as **wound down** from its records (`work.team_wound_down`, the card's own
        reading) whose members' lanes hold ids their `lane_seen` does not gets `work_waiting: {at,
        repo, members: {<name>: [ids]}}` on the home's `host` record under its name, once
        `WORK_SETTLE` has passed since the home first read the newest of them (a time kept in
        memory, so a restart settles again). It is removed when the team is no longer wound down —
        a crew session live again, or a member that never declared — when no id is new, and under
        `on_work: off`. `lane_seen` itself is rule 6's, written for a member that is gone as for a
        live one and pruned by it on the same tick, before this pass (`work.reread`, TD-407), which
        `work.gained` reads the same way. One team's surprise is a log line, never another's."""
        if self.mode != "home":
            return
        teams = self._host_rec.setdefault("teams", {})
        try:
            settings = settings_mod.teams(settings_mod.load())
        except Exception:  # noqa: BLE001 — a policy's surprise is a log line; the next tick reads again
            log.exception("reading the teams' settings for rule 8 failed")
            return
        by_team: dict[str, list[Session]] = {}
        for r in self._graph().values():
            if r.team:
                by_team.setdefault(r.team, []).append(r)
        firsts: dict[tuple[str, str], datetime] = {}
        dirty = False
        for team in sorted(set(by_team) | {t for t, rec in teams.items() if "work_waiting" in rec}):
            try:
                rec = teams.get(team) or {}
                old = rec.get("work_waiting")
                await self._run_ended_marks(by_team.get(team) or [])
                on_work = (settings.get(team) or {}).get("on_work", settings_mod.ON_WORK_DEFAULT)
                # a record never read for news gets its baseline first, and has none on this tick (TD-781)
                fresh = await self._work_baselines(by_team.get(team) or []) if on_work != "off" else set()
                new = self._work_mark(team, old, by_team.get(team) or [], on_work, now, firsts, fresh)
                starts = rec.get("work_started")
                if new is not None and on_work == "start" and not new.get("stopped"):  # a stopped team: never
                    new = await self._work_start(team, new, rec, by_team.get(team) or [], settings.get(team) or {}, now)
                elif isinstance(new, dict) and "held" in new:
                    new = {k: v for k, v in new.items() if k != "held"}  # `ask` again: no start to hold back
                if new == old and rec.get("work_started") == starts:
                    continue
                dirty = True
                if new is None:
                    rec.pop("work_waiting", None)
                    log.info("rule 8: %s has no work waiting", team)
                else:
                    rec["work_waiting"] = new
                    how = "stopped" if new.get("stopped") else "wound down"
                    log.info("rule 8: %s %s with work waiting: %s", team, how, new["members"])
                if rec:
                    teams[team] = rec
                else:
                    teams.pop(team, None)
            except Exception:  # noqa: BLE001 — one team's surprise is a log line, never the others'
                log.exception("reading %s's work for rule 8 failed", team)
        self._work_first = firsts  # an id no longer new starts its settle again if it comes back
        if dirty:
            try:
                self.host_store.save(self._host_rec)
            except OSError:
                log.exception("writing the home's host record failed")
            await self._push_changes()

    def _work_mark(
        self,
        team: str,
        old: Any,
        records: list[Session],
        on_work: str,
        now: datetime,
        firsts: dict[tuple[str, str], datetime],
        fresh: set[str] | frozenset[str] = frozenset(),
    ) -> dict[str, Any] | None:
        """One team's `work_waiting` as it reads now (`_work_marks`), or None. Its repo is the ledger's
        — a registry root, since two repos may hold one id — and a team whose members' news is in two
        repos is written for the first registry root in order; the other's waits for the next
        wind-down. A crew member's ledger that cannot be read keeps what stands: *could not look*
        is not *no id new* (the techlead's read of #788). A **stopped** team (§6 rule 8 *A team that
        stopped*, TD-781) is read as a wound-down one, its mark carrying `stopped: {by, at}`, which no
        start follows; `fresh` are the records whose baseline this tick wrote, which have no news on it."""
        if on_work == "off":
            return None
        wound = work_mod.team_wound_down(records) is not None
        stopped = None if wound else work_mod.team_stopped(records)
        # a team that runs on: only its members that finished alone are read (§6 rule 8 *A member that
        # finished while its team runs on*, TD-457); none, and there is nothing for this rule
        alone = None if wound or stopped else {r.id for r in work_mod.finished_alone(records)}
        if alone is not None and not alone:
            return None
        # a question's end (§6 rule 8 *A question's end is work*, TD-274) is written once, at the
        # lapse or the answer, and stands with the mark until a start, Dismiss or a live team clears it
        questions = list(old.get("questions") or []) if isinstance(old, dict) and wound else []
        news: dict[str, dict[str, list[str]]] = {}  # repo → member → ids
        for r in sorted(work_mod.crew(records), key=lambda r: (r.name, r.id)):
            if r.seat is not None or r.superseded_by or work_mod.sat_out(r):
                continue  # a member its flow sat out has no lane that is the team's work (§4.9c)
            if alone is not None and r.id not in alone:
                continue  # live, or not finished: rule 6's, or nobody's
            if r.id in fresh:
                continue  # its baseline was written on this tick: news from the next one (TD-781)
            if seams_mod.unserved(self._repos.get(r.repo or "")):
                continue  # an unserved repo's lane reads empty: nothing in it starts its team (§5, TD-1011)
            led = (self._repos.get(r.repo or "") or {}).get("ledger") or {}
            if "error" in led or not isinstance(led.get("entries"), list):
                if isinstance(old, dict):
                    # the settle's memory kept too, so the ids read back later need no second settle
                    firsts.update({k: t for k, t in self._work_first.items() if k[0] == team})
                    return _stamped(old, stopped)
                continue
            ids = news.setdefault(str(r.repo), {}).setdefault(r.name, [])
            # the repo's work orders count as entries do (§6 rule 8, TD-384): a decided line starts its team
            orders = _orders(self._repos.get(r.repo or ""))
            ids.extend(i for i in work_mod.gained(r, [*led["entries"], *orders]) if i not in ids)
        news = {repo: {m: ids for m, ids in ms.items() if ids} for repo, ms in news.items()}
        news = {repo: ms for repo, ms in news.items() if ms}
        if not news:
            if questions:  # nothing new in the lanes: the questions' references alone, under their names
                at = old.get("at") or now_iso()
                return {"at": at, "repo": old.get("repo"), "members": _asked(questions), "questions": questions}
            return None
        repo = min(news)
        members = news[repo]
        newest = max(
            firsts.setdefault((team, i), self._work_first.get((team, i), now)) for ids in members.values() for i in ids
        )
        if now - newest < agent_common.WORK_SETTLE:
            return _stamped(old, stopped) if isinstance(old, dict) else None  # still settling: what stands, stands
        at = old.get("at") if isinstance(old, dict) and old.get("at") else now_iso()
        if questions:  # the questions' references and repo are the mark's own, the lanes' news beside them
            members = _asked(questions, members)
            return {"at": at, "repo": old.get("repo") or repo, "members": members, "questions": questions}
        return _stamped({"at": at, "repo": repo, "members": members}, stopped)

    async def _run_ended_marks(self, records: list[Session], concluded: bool = False) -> None:
        """A run-only member's run ends with its team's (design §4.9 *A member started from the form*, §6
        rules 8 and 9, TD-1166): when the team has nobody live — wound down or stopped — or rule 9 concludes
        it (`concluded`), every dead, current run-only crew record that carries no mark is marked
        `closed_for: {why: run_ended}`, `closed_at` its close's or, for an exit, the time it exited, as a
        sit-out's exit is. A Close marks its own (`agent_common.run_ended`); this reaches the exited one no
        Close did. A record carrying the tick's restart mark is mid-restart, never its run's end."""
        mine = work_mod.crew(records)
        if not concluded and (not mine or any(r.state not in work_mod.DEAD for r in mine)):
            return
        ended = [
            r for r in mine if r.run_only and r.state in work_mod.DEAD and not r.superseded_by and r.closed_for is None
        ]
        for r in ended:
            r.closed_for = {"why": "run_ended", "closed_at": r.closed_at or r.since}
            log.info("%s: run-only, its team's run ended — never replayed", self._address(r))
            self._save(r)
        if ended:
            await self._push_changes()

    async def _work_baselines(self, records: list[Session]) -> set[str]:
        """Rule 8's baseline (§6 rule 8 *How the lanes are read*, TD-781): each record `_work_mark` reads whose
        `lane_seen` is None — never read for news, as rule 6 writes the memory only at a supervised member's
        declaration — or holds a `base` older than the record's `created` (one a supersede carried onto a run
        that ended undeclared) gets `{at, ids, base: true}`: the ledger's entries matching its lane as
        `origin/<default>` held them before the record's end (`work.record_end`), the work orders matching now,
        and the matching entries the checkout's reading holds and the ref's tip does not, pruned as `reread`
        prunes. A read that fails writes nothing, and the next tick tries again. The ids written to."""
        wound = work_mod.team_wound_down(records) is not None
        stopped = not wound and work_mod.team_stopped(records) is not None
        alone = None if wound or stopped else {r.id for r in work_mod.finished_alone(records)}
        done: set[str] = set()
        for r in work_mod.crew(records):
            if r.seat is not None or r.superseded_by or work_mod.sat_out(r):
                continue
            if alone is not None and r.id not in alone:
                continue
            seen = r.lane_seen
            if seen is not None and not (seen.get("base") and str(seen.get("at") or "") < r.created):
                continue
            facts = self._repos.get(r.repo or "") or {}
            led = facts.get("ledger") or {}
            if "error" in led or not isinstance(led.get("entries"), list):
                continue
            root, rel = facts.get("root") or r.repo, r.ledger or led.get("path")
            try:
                end = _parse(str(work_mod.record_end(r)))
            except (ValueError, TypeError):
                continue
            if not (root and rel):
                continue
            then, why, tip = await asyncio.to_thread(self._ledger_then, r, str(root), str(rel), end)
            if then is None or tip is None or r.lane_seen is not seen:
                continue  # could not read it, or rule 6 wrote it while git was read: the next tick looks again

            def matching(got: list[Any], r: Session = r) -> list[str]:
                return [
                    str(e["id"])
                    for e in got
                    if isinstance(e, dict) and e.get("id") and ledger_mod.lane_matches(r.lane, e, r.team)
                ]

            orders = _orders(facts)
            ids = matching(then)
            ids += [i for i in matching(orders) if i not in ids]  # orders keep no history: those standing now
            # an entry the checkout holds and origin's tip does not (a branch checked out here) is seen, untold
            on_tip = set(matching(tip))
            ids += [i for i in matching(led["entries"]) if i not in on_tip and i not in ids]
            r.lane_seen = {"at": now_iso(), "ids": ids, "base": True}
            r.lane_seen = work_mod.reread(r, [*led["entries"], *orders])[0]
            self._save(r)
            done.add(r.id)
            log.info("%s: rule 8's baseline from the ledger at its end (%s)", self._address(r), why)
        return done

    def _question_end(self, e: Any, how: str) -> None:
        """§6 rule 8 *A question's end is work* (TD-271, TD-274 slice 4): an orphaned question that lapsed (`how:
        lapsed`) or was answered (`answered`) while its asker's team is **wound down** writes `work_waiting` for the
        team as a lane's new id does — `members[<name>]` gaining the reference, `questions` gaining `{id, ref, name,
        how, kind}` (the Inbox row says *steer* or *ask*) — with no settle, a standing mark gaining the question and
        keeping its `at`. Under `on_work: off`, or for a team stopped rather than wound down, or one live again, nothing
        is written: a live member is waiting (§4.9a), and a stopped team's note waits in the mailbox for the person's
        Start, while that team's lanes are read (*A team that stopped*, TD-781). The next tick's `_work_marks` does
        what the team's `on_work` says. Never on a node."""
        o = e.orphaned if isinstance(e.orphaned, dict) else {}
        team, name, ref = str(o.get("team") or ""), str(o.get("name") or ""), str(o.get("ref") or "")
        if self.mode != "home" or not (team and name and ref):
            return
        try:
            on_work = (settings_mod.teams(settings_mod.load()).get(team) or {}).get(
                "on_work", settings_mod.ON_WORK_DEFAULT
            )
        except Exception:  # noqa: BLE001 — a policy's surprise is a log line, never the answer's failure
            log.exception("reading %s's settings for rule 8's question failed", team)
            return
        records = [r for r in self._graph().values() if r.team == team]
        if on_work == "off" or work_mod.team_wound_down(records) is None:
            return
        teams = self._host_rec.setdefault("teams", {})
        rec = teams.setdefault(team, {})
        old = rec.get("work_waiting") if isinstance(rec.get("work_waiting"), dict) else {}
        if any(isinstance(q, dict) and q.get("id") == e.id for q in old.get("questions") or []):
            return  # a question ends once
        members = {m: list(ids) for m, ids in (old.get("members") or {}).items()}
        if ref not in members.setdefault(name, []):
            members[name].append(ref)
        questions = [*(old.get("questions") or []), {"id": e.id, "ref": ref, "name": name, "how": how, "kind": e.kind}]
        rec["work_waiting"] = {
            **old,
            "at": old.get("at") or now_iso(),
            "repo": old.get("repo") or str(o.get("repo") or ""),
            "members": members,
            "questions": questions,
        }
        log.info("rule 8: %s's %s about %s %s; %s has work waiting", name, e.kind, ref, how, team)
        self._question_ended = True  # the sweep pushes it: the next tick reads the mark unchanged
        try:
            self.host_store.save(self._host_rec)
        except OSError:
            log.exception("writing the home's host record failed")

    async def _work_start(
        self,
        team: str,
        mark: dict[str, Any],
        rec: dict[str, Any],
        records: list[Session],
        conf: dict[str, Any],
        now: datetime,
    ) -> dict[str, Any] | None:
        """Rule 8 under `on_work: start` (design §6, TD-227 slice 4): the person's standing press. The
        five bounds are read before the first replay, and one that holds the start back leaves the
        mark standing with `held: {why, …}`, which is what draws the row under `start`; otherwise the
        team's records are replayed (`_work_replays`, the lead first), each `restarts` entry
        `why: work` with the ids it was started for, the instant appended to `work_started` on the
        home's record once however many records it replayed, and None is returned: the mark goes.
        Every entry of one start carries the same `start` instant and `of`, the number of records it
        set out to replay, so a client counts *n of m* from the records when some replays failed
        (the techlead's read of #792). An unattended seat is replayed held — `closed`, no pane, its
        entry `held: true` — and the first tick fills it only for a cause (rule 3, TD-660); a member
        and a standing manager replay live. A member on a node whose link is down holds the whole
        start as `held: {why: link, host, hosts}` — every down host, `host` the first — looked at
        again on the next tick."""
        if mark.get("stopped"):
            # a stopped team is never started by this rule (§6 rule 8 *A team that stopped*, TD-781): its
            # Start is the card's
            return {k: v for k, v in mark.items() if k != "held"}
        started = [t for t in rec.get("work_started") or [] if _recent(t, now, agent_common.WORK_DAY)]
        if started != (rec.get("work_started") or []):
            rec["work_started"] = started  # a start older than the day counts for nothing
        if not started:
            rec.pop("work_started", None)
        replays = self._work_replays(records, now)
        if work_mod.team_wound_down(records) is None:
            # what a start replays is read at the start (TD-457): a team that runs on has only the
            # members the mark names replayed, each alone; one left by `_work_replays` holds as `nothing`
            named = set(mark.get("members") or {})
            replays = [r for r in replays if r.name in named]
        standing = (rec.get("work_waiting") or {}).get("held")
        held = self._work_held(replays, started, conf, now, team, records, standing)
        bare = {k: v for k, v in mark.items() if k != "held"}
        if held is None:
            down = list(
                dict.fromkeys(r.host for r in replays if r.host != self.host and r.host not in self._link_muxes)
            )
            if down:  # the whole team waits for them, looked at again next tick (§4.4a); `host` for an older page
                held = {"why": "link", "host": down[0], "hosts": down}
        if held is not None:
            return {**bare, "held": held}
        ids = list(dict.fromkeys(i for got in (mark.get("members") or {}).values() for i in got))
        at = now_iso()
        rec["work_started"] = [*started, at]
        about = {"ids": ids, "start": at, "of": len(replays)}
        log.info("rule 8: starting %s again for %s (%d records)", team, ids, len(replays))
        for r in replays:
            try:
                # every record's mail kept, as a fill's and a Restart's is: a lapse note or an answer
                # written to the closed record waits there for this successor (§4.10, TD-271)
                # a seat is written held, on call again with no pane, and the first tick fills it only
                # for a cause (rule 3, TD-660); `create` takes `held` from an unattended seat alone
                await self._replay(r, "work", mark=dict(about), keep_mail=True, held=bool(r.seat and r.unattended))
            except Exception:  # noqa: BLE001 — one record's failure is never the team's start
                log.exception("%s: rule 8's replay failed", self._address(r))
        return None

    def _work_replays(self, records: list[Session], now: datetime) -> list[Session]:
        """What a start by rule 8 replays: the team's crew records that ended — the wound-down reading
        has every one that is not a seat declared — seats included, none superseded, suspended, at
        its ceiling, sat out by the team's flow (§4.9c: not started until a flow that uses it returns)
        or without a launch record (no launch record, no start: the rule never invents a
        team). A seat's `fill` entries are not counted toward `RESTART_CEILING`, as rule 3 never counts
        them (the techlead's read of #792). The records other ones name as a controller come first, so
        the lead is up before its members, as a person's start makes it."""
        out = []
        for r in work_mod.crew(records):
            if r.state not in work_mod.DEAD or r.superseded_by or r.suspended or r.restart_ceiling:
                continue
            if work_mod.sat_out(r) or r.run_only:
                # it did not end by the team's own ending: its flow sat it out (§4.9c); a run-only member is
                # never replayed, an exited one included, which no Close marks (§4.9, TD-1166)
                continue
            recent = agent_common._counted(r.restarts, now, fills=False)
            if len(recent) >= RESTART_CEILING:
                continue
            if not (paths.launch_dir() / f"{self._address(r)}.json").is_file():
                continue
            out.append(r)
        leads = {c for r in out for c in self._ctl(r)}
        return sorted(out, key=lambda r: (self._address(r) not in leads, r.name, r.id))

    def _work_held(
        self,
        replays: list[Session],
        started: list[str],
        conf: dict[str, Any],
        now: datetime,
        team: str,
        records: list[Session] | None = None,
        standing: Any = None,
    ) -> dict[str, Any] | None:
        """The bound that holds rule 8's start back, in the design's order, or None (§6 rule 8): a
        member's profile over its usage line; the team's stop time passed and not cleared;
        `WORK_STARTS_DAY` starts in the day; a start inside `WORK_EARLY`; its repo over the team's
        balance line (`_work_balance`). Nothing to replay holds it too: the row of `ask` is the
        person's way to start a team the rule cannot. A standing balance hold that an earlier bound
        displaces is kept beside it as `balance`, so a failed reading when that bound lifts does not
        start a team that was over its line (TD-330)."""
        prior = _balance_hold(standing)
        kept = {"balance": prior} if prior is not None else {}
        if not replays:
            return {"why": "nothing", **kept}
        for profile in dict.fromkeys(r.profile for r in replays):
            if (over := self._profile_over(profile, now, team)) is not None:
                # the window's reset, when the reading has one, so the row can say when the hold lifts
                resets = {"resets": over["resets"]} if over.get("resets") else {}
                return {"why": "usage", "profile": profile, **resets, **kept}
        until = conf.get("until")
        with contextlib.suppress(TypeError, ValueError):
            if until and _parse(str(until)) <= now:
                return {"why": "until", "until": str(until), **kept}
        if len(started) >= agent_common.WORK_STARTS_DAY:
            return {"why": "day", "count": len(started), **kept}
        if started and _recent(started[-1], now, agent_common.WORK_EARLY):
            return {"why": "early", "started": started[-1], **kept}
        return self._work_balance(conf.get("balance"), records or replays, now, prior)

    def _work_balance(
        self, bal: dict[str, Any] | None, records: list[Session], now: datetime, standing: Any = None
    ) -> dict[str, Any] | None:
        """Rule 8's fifth bound (§6 *Balance*): the team's lines read by the rule itself, since the mark
        went with the team's last live member — against every registry root its records name, either
        crossing counts, as `_balance_mark` reads a live team, and for `review` the queue at its seats,
        which keep their inbox when they end, against the shortest bound its records carry.
        `{why: balance, repo, crossed}` when a line is crossed. A reading that cannot be told writes no
        new hold and lifts none (a failed reading crosses nothing and clears nothing); a standing hold
        whose repo, lines and limits are unchanged is kept as it stands, so an age's `value` is the
        crossing's and the tick writes nothing while it holds (the techlead's read of #799)."""
        if not bal:
            return None
        records = [r for r in records if not r.superseded_by]  # a resumed record's successor holds its inbox
        roots = sorted({r.repo for r in records if r.repo and r.repo in self._repos})
        waiting = [str(w["oldest"]) for r in records if r.seat is not None and (w := r.prs_waiting(home=self.host))]
        bounds = [d for r in records if (d := balance_mod.span((r.review or {}).get("bound")))]
        got = balance_mod.crossed(
            bal, roots, self._repos, min(waiting) if waiting else None,
            min(bounds) if bounds else balance_mod.REVIEW_BOUND, now,
        )  # fmt: skip
        kept = _balance_hold(standing)
        if got is None:
            return kept
        if not got[0]:
            return None
        if kept is not None and kept.get("repo") == got[1] and _lines(kept.get("crossed")) == _lines(got[0]):
            return kept
        return {"why": "balance", "repo": got[1], "crossed": got[0]}

    async def _finished_pass(self, now: datetime) -> None:
        """Rule 9 (design §6 *Finished is the home's reading*, TD-241): on every tick at the home,
        each team whose records read **finished** (`work.finished`, the card's own *concluded*) with
        no restart wanted, for `FINISHED_SETTLE`, is wound down by the home itself — its finished
        members closed under the wrap-up's safety check, its manager told once and closed after
        `WRAPUP_GRACE`, and the person told what the manager did not say. When the reading first held
        is kept in memory per team and dropped the tick it stops holding. One team's surprise is a
        log line, never another's."""
        if self.mode != "home":
            return
        by_team: dict[str, list[Session]] = {}
        for r in self._graph().values():
            if r.team:
                by_team.setdefault(r.team, []).append(r)
        firsts: dict[str, datetime] = {}
        for team in sorted(by_team):
            try:
                first = await self._finished_team(team, by_team[team], now)
            except Exception:  # noqa: BLE001 — one team's surprise is a log line, never the others'
                log.exception("reading whether %s has finished failed", team)
                first = self._finished_first.get(team)  # a surprise is not the reading no longer holding
            if first is not None:
                firsts[team] = first
        self._finished_first = firsts
        for team in [t for t in self._finished_owed if t not in by_team]:
            del self._finished_owed[team]  # its records are forgotten: nothing left to announce

    def _finished_view(self, r: Session, now: datetime) -> dict[str, Any]:
        """What `work.finished` reads of a record, as this host addresses it: a node's member names
        its controllers in its own host's form (§4.4a), and the manager is found by address; a live
        subagent is read at the tick's `now`, as the view reads it at its own (§4.2, TD-734); its held
        asks and its declared claims, as the page's view carries them, for the reader's wait (TD-854)."""
        return {
            "id": self._address(r),
            "name": r.name,
            "state": r.state,
            "pane": r.pane,
            "unattended": r.unattended,
            "superseded_by": r.superseded_by,
            "seat": r.seat,
            "capabilities": r.capabilities,
            "controllers": self._ctl(r),
            "out_of_work": r.out_of_work,
            "restart_wanted": r.restart_wanted,
            "subagents_live": agent_common.subagents_live(r, now),
            "shells_live": agent_common.shells_live(r, now),
            "prs_waiting": r.prs_waiting(home=self.host),
            "progress": [
                {"ref": e.ref, "status": e.status, "source": e.source, "pr": e.pr, "review_pr": e.review_pr}
                for e in r.progress
                if e.status == "claimed" and e.source == "declared"
            ],
        }

    async def _finished_team(self, team: str, records: list[Session], now: datetime) -> datetime | None:
        """One team's pass of rule 9: when its reading first held, to keep for the next tick, or None
        when it does not hold or the wind-down is over."""
        by_address = {self._address(r): r for r in records}
        views = [self._finished_view(r, now) for r in records]
        mine = [v for v in views if v["unattended"] is not False and not v["superseded_by"]]
        top = work_mod.manager_of(mine)
        manager = by_address[top["id"]] if top is not None else None
        members = [
            by_address[v["id"]] for v in mine if v["seat"] is None and v is not top and v["state"] not in work_mod.DEAD
        ]
        first = self._finished_first.get(team)
        led = manager is not None and manager.state not in work_mod.DEAD
        if (
            team in self._finished_owed
            and not members
            and not led
            and not (manager is not None and manager.finished_sent_at)
        ):
            # the member left open with work is gone by another hand — a person's Close, a kill —
            # and nobody live announced the team: the note is written now, whoever ended it
            since = self._finished_owed.pop(team)
            if not work_mod.closed_finished(manager):
                self._finished_tell(team, records, manager, since)
                await self._push_changes()
            return None
        if manager is not None and manager.finished_sent_at:
            # the manager's half: from the send on the reading is no longer asked of it — its last
            # acts are work — and only a member live and not finished takes the wind-down back
            since = first or _parse(manager.finished_sent_at) - agent_common.FINISHED_SETTLE
            asked = work_mod.waiting_of(self.person_inbox)
            held = work_mod.held_asks(views, home=self.host)  # a reader's wait takes it back too (TD-854)
            if any(
                m.state != "idle"
                or m.restart_wanted
                or not m.out_of_work
                or asked.get(self._address(m))
                or held.get(self._address(m))
                for m in members
            ):
                manager.finished_sent_at = None
                self._save(manager)
                log.info("rule 9: %s has a member at work again — the wind-down is off", team)
                await self._push_changes()
                return None
            for m in members:
                # one left open with work is closed once it is pushed, the manager live or gone
                await self._finished_close(m)
            if manager.state in work_mod.DEAD:
                if manager.state == "closed" and not work_mod.closed_finished(manager):
                    # it closed itself, as the line asked: the mark is what lets the team read
                    # *wound down* without its declaration, and what says the person was told. One
                    # that `exited` — a crash, a kill — is rule 1's or a person's, and is left
                    self._mark_closed(manager, "finished")
                    self._save(manager)
                    self._finished_tell(team, records, manager, since)
                    await self._push_changes()
                return None
            grace = now - _parse(manager.finished_sent_at) >= agent_common.WRAPUP_GRACE
            if grace and await self._finished_close(manager):
                self._mark_closed(manager, "finished")
                self._save(manager)
                self._finished_tell(team, records, manager, since)
                await self._push_changes()
                return None
            return since
        reading = work_mod.finished(views, waiting=work_mod.waiting_of(self.person_inbox), home=self.host)
        if reading is None or reading["why"] or reading["restart"]:
            self._finished_owed.pop(team, None)  # at work again, or started again: nothing is owed
            return None  # not finished, or one that wants another run: rule 2's
        first = first or now
        if now - first < agent_common.FINISHED_SETTLE:
            return first
        closed = [m for m in members if await self._finished_close(m)]
        left = [m for m in members if m not in closed]
        if closed:
            log.info("rule 9: %s finished — closed %s", team, ", ".join(m.name for m in closed))
        await self._run_ended_marks(records, concluded=True)  # its closes marked theirs; an exited one too
        if manager is None or manager.state in work_mod.DEAD:
            if left:
                # one left open with work: the note waits for the tick that finds the last one gone,
                # kept in memory as the settle is, so a close by a person is announced too (TD-256)
                self._finished_owed.setdefault(team, first)
                return first
            self._finished_owed.pop(team, None)
            if closed and not work_mod.closed_finished(manager):
                # nobody live to tell; one rule 9 closed was announced then, and is never told twice
                self._finished_tell(team, records, manager, first)
                await self._push_changes()
            return None
        if manager.suspended:
            return first
        if manager.host != self.host:
            # a node's manager gets no line and the close alone, routed as rule 2 routes one
            if await self._finished_close(manager):
                self._mark_closed(manager, "finished")
                self._save(manager)
                self._finished_tell(team, records, manager, first)
                await self._push_changes()
                return None
            return first
        line = (
            "[shiftlead] your team is finished: every member has declared. Make your last acts — "
            "`ao progress none`, the note to the person — then `ao close` yourself"
        )
        if manager.state == "idle" and await self._policy_send(manager, line):
            manager.finished_sent_at = now_iso()
            log.info("rule 9: %s finished — its manager %s told", team, manager.name)
            self._save(manager)
            await self._push_changes()
        return first

    async def _finished_close(self, s: Session, why: str = "finished") -> bool:
        """Rule 9's close, under the wrap-up's own safety check in the tick's form (rule 2's): only an
        `idle` record whose git fields are known and show nothing uncommitted and nothing unpushed,
        never a suspended one, and a node's only while its link is up. True when it was closed. A
        sit-out's close is the same close (§4.9c), under `why: sit_out`."""
        if s.state != "idle" or s.suspended or not s.unattended:
            return False
        git = s.git or {}
        if not all(isinstance(git.get(k), int) and git[k] == 0 for k in ("dirty", "unpushed")):
            return False  # work left, or not known: left open, and the Inbox row it is after any wrap-up
        if s.host != self.host and s.host not in self._link_muxes:
            return False  # its link is down: looked at again next tick (§4.4a)
        try:
            closer = {"by": "tick", "why": why}
            if s.host == self.host:
                await self.rpc_close(s.id, closer=closer)
            else:
                await self._route_act("close", {"id": s.id, "closer": closer}, None, s.host)
        except Exception as e:  # noqa: BLE001 — a close that failed is tried again on the next tick
            log.warning("%s: the %s close failed: %s", self._address(s), why, e)
            return False
        return s.state == "closed"

    def _finished_tell(self, team: str, records: list[Session], manager: Session | None, since: datetime) -> None:
        """The announcement the manager did not make (design §6 rule 9, §4.9a): one `system` note to
        the person — the pull requests the members reported `done` since the team's start, the
        earliest `created` among its records that are not superseded, and each member's
        `out_of_work.why` — written only when no `note` from the manager reached the person inbox
        since the reading first held, so a team that dissolves is never quiet and never told twice."""
        if manager is not None:
            sender = self._address(manager)
            for e in self.person_inbox:
                try:
                    if e.from_ == sender and e.kind == "note" and _parse(e.at) >= since:
                        return
                except (ValueError, TypeError):
                    continue
        mine = [r for r in records if r.unattended and not r.superseded_by]
        start = min((r.created for r in mine if r.created), default="")
        members = [r for r in mine if r.seat is None and r is not manager]
        prs = sorted(
            {
                e.pr
                for r in members
                for e in r.progress
                if e.status == "done" and e.pr and (not start or str(e.at) >= start)
            }
        )
        said = "; its manager did not announce it" if manager is not None else ""
        lines = [
            f"{team} finished and the host agent wound it down: every member declared out of work{said}. "
            "Nothing is asked of you.",
            "",
            ("Pull requests reported done since the team started: " + ", ".join(f"#{n}" for n in prs) + ".")
            if prs
            else "No pull request was reported done since the team started.",
        ]
        for r in sorted(members, key=lambda r: (r.name, r.id)):
            why = (r.out_of_work or {}).get("why") if isinstance(r.out_of_work, dict) else None
            if why:
                lines.append(f"{r.name}: {why}")
        if more := self._finished_more(team, mine, members, start):
            lines += ["", *more]
        self._system_note(PERSON, "\n".join(lines), team=team)
        log.info("rule 9: %s wound down by the tick — the person told", team)

    def _finished_more(self, team: str, mine: list[Session], members: list[Session], start: str) -> list[str]:
        """What rule 9's note adds under its first lines (§4.9a *The home's note says more*, TD-468),
        each line only when it has something to say: the members' claims left standing and their
        drops since `start`, with each one's why; their restarts since `start` by `why`, and any at
        the restart ceiling (a `wanted` one under the member's own why; a person's Restart and a start
        are not the tick's restarts); the identity alarms standing on the team's records; each open
        `ask` or `steer` a member put to the person about a reference, with its bound; and each profile the
        records name, its window readings now beside `teams.<team>.usage_at_start`."""
        out: list[str] = []
        for r in sorted(members, key=lambda r: (r.name, r.id)):
            left = [f"{e.ref} left claimed" for e in r.progress if e.status == "claimed"]
            left += [
                f"{e.ref} dropped" + (f" — {e.why}" if e.why else "")
                for e in r.progress
                if e.status == "dropped" and (not start or str(e.at) >= start)
            ]
            if left:
                out.append(f"Claims left — {r.name}: {'; '.join(left)}")
        whys: dict[str, int] = {}
        for r in members:
            for e in r.restarts:
                if not isinstance(e, dict) or e.get("why") in NOT_RESTARTS:
                    continue
                if not start or str(e.get("at") or "") >= start:
                    word = str(e.get("said") or e.get("why") or "restarted")
                    word = "cache lapsed" if word == "cache" else word
                    whys[word] = whys.get(word, 0) + 1
        ceiling = sorted(r.name for r in members if r.restart_ceiling)
        if whys or ceiling:
            n = sum(whys.values())
            said = f"{n} restart{'' if n == 1 else 's'}: " + ", ".join(
                f"{c} {w}" for w, c in sorted(whys.items(), key=lambda x: (-x[1], x[0]))
            )
            if ceiling:
                said = (said + "; " if whys else "") + "at the restart ceiling: " + ", ".join(ceiling)
            out.append(f"Restarts — {said}")
        alarms = [r for r in mine if r.identity_alarms]
        if alarms:
            n = sum(len(r.identity_alarms) for r in alarms)
            names = ", ".join(sorted(r.name for r in alarms))
            out.append(f"Alarms — {n} identity alarm{'' if n == 1 else 's'} standing on {names} (§4.8a)")
        asked = work_mod.waiting_of(self.person_inbox)
        for r in sorted(members, key=lambda r: (r.name, r.id)):
            qs = asked.get(self._address(r)) or []
            if qs:
                each = [
                    f"{q['ref']} ({q['id']}"
                    + (
                        f", until {work_mod.bound_words(q.get('bound'))})"
                        if work_mod.bound_words(q.get("bound"))
                        else ")"
                    )
                    for q in qs
                ]
                out.append(f"Open to you — {r.name}: {'; '.join(each)}")
        at_start = ((self._host_rec.get("teams") or {}).get(team) or {}).get("usage_at_start") or {}
        for prof in sorted({r.profile for r in mine if r.profile}):
            now = [
                w for w in (self._usage.get(prof) or {}).get("windows") or [] if isinstance(w, dict) and w.get("label")
            ]
            was = at_start.get(prof) if isinstance(at_start.get(prof), dict) else {}
            each = []
            for w in now:
                if not isinstance(w.get("pct"), int | float):
                    continue
                then = was.get(str(w["label"]))
                from_ = f", from {round(then)}%" if isinstance(then, int | float) else ""
                each.append(f"{w['label']} {round(w['pct'])}%{from_}")
            if each:
                out.append(f"Usage — {prof}: {'; '.join(each)}")
        return out

    @staticmethod
    def _owed_part(ids: list[str]) -> str | None:
        """Rule 4's owed clause (design §6, TD-258): the outcomes a record owes the person, named
        apart from its open work — the ids from the record's own `owed()` reading, three at most."""
        if not ids:
            return None
        named = ", ".join(ids[:OWED_NAMED]) + (f" and {len(ids) - OWED_NAMED} more" if len(ids) > OWED_NAMED else "")
        return (
            f"you owe {len(ids)} outcome{'' if len(ids) == 1 else 's'} on {named} — "
            f'`ao msg person --outcome done|blocked|dropped "…" --for {ids[0] if len(ids) == 1 else "<id>"}`'
        )

    def _nudge_line(self, s: Session) -> str | None:
        if s.seat is not None:
            n = s.asks_waiting(home=self.host) if s.seat_due else 0
            # an entry the person handed the seat owes its outcome, read or not: named apart from the questions (TD-218)
            h = s.asks_waiting(home=self.host, handed_only=True) if n else 0
            parts = [f"you have {n - h} questions waiting — run `ao inbox`"] if n > h else []
            if h:
                parts.append(
                    f"{h} {'entry' if h == 1 else 'entries'} the person handed you "
                    f"{'owes its' if h == 1 else 'owe their'} outcome — "
                    '`ao msg person --outcome done|blocked|dropped "…" --for <id>`'
                )
            # the seat's own questions the person answered (TD-258): a handed entry is the part above
            owed = self._owed_part([e.id for e in s.outbox if e.owes_for(session_inbox=False)])
            parts += [owed] if owed else []
            return "[shiftlead] " + "; ".join(parts) if parts else None
        ref = self._open_ref(s, {e.ref for e in self._waiting_claims(s)})  # a waiting claim is not open work (TD-820)
        owed = self._owed_part(s.owed())
        minutes = int(IDLE_NUDGE.total_seconds() // 60)
        if ref is None:
            return f"[shiftlead] you have been idle {minutes} minutes: {owed}" if owed else None
        return (
            f"[shiftlead] you have been idle {minutes} minutes with `{ref}` open "
            f"— end the run with one of `ao progress done {ref} --pr N`, `ao progress drop {ref} --why`, "
            "`ao progress none --why` or `ao progress restart --why`" + (f"; {owed}" if owed else "")
        )

    async def _policy_send(self, s: Session, text: str) -> bool:
        """A policy's fixed line, typed through `send`'s path under the doorbell's rules (§6, §4.10):
        one typist per pane, never at a dialog, only into an empty composer — someone's half-typed
        words would be submitted with it. Recorded on `sends` as the home's own (`system`). False
        when it was not typed: the tick looks again next time."""
        adapter = adapters.get(s.adapter)
        if not adapters.has_agent(s.adapter):
            return False  # a policy's line typed into a shell runs as a command line (§4.3)
        if getattr(adapter, "composer", None) is None or self._on_a_dialog(s):
            return False
        typing = self._typing[s.id]
        if typing.locked():
            return False
        async with typing:
            tail = await asyncio.to_thread(self.tmux.capture_tail, s.id, COMPOSER_LINES, raw=True)
            if adapter.composer(tail) != "":
                return False
            entry = self._record_send(s, SYSTEM, text)
            try:
                await self._type(s.id, adapter, text)
            except Exception as e:  # noqa: BLE001 — a failed send is not a sent one; next tick looks again
                entry.verdict = str(e) or type(e).__name__
                self.store.save(s)
                return False
        return True

    def _mark_team_start(self, team: str, but: Session | None = None) -> None:
        """A start of `team` (§4.9a *The home's note says more*, TD-468): `ao team start`'s creates, a
        schedule's start and rule 8's — each counts only when no unattended record of the team runs
        but `but`, the one being started. The home's usage readings now (the `usage` RPC's windows)
        are kept as `teams.<team>.usage_at_start: {profile: {window: pct}}` on the host record,
        replacing the last start's; with no reading the key goes. At the home only."""
        if self.mode != "home" or not team:
            return
        for r in self._graph().values():
            if r is but or r.team != team or not r.unattended or r.superseded_by:
                continue
            if r.state not in ("exited", "closed", "scheduled"):
                return
        readings: dict[str, dict[str, float]] = {}
        for prof, reading in self._usage.items():
            windows = {
                str(w["label"]): w["pct"]
                for w in (reading or {}).get("windows") or []
                if isinstance(w, dict) and w.get("label") and isinstance(w.get("pct"), int | float)
            }
            if windows:
                readings[prof] = windows
        teams = self._host_rec.setdefault("teams", {})
        rec = teams.get(team) if isinstance(teams.get(team), dict) else {}
        if readings:
            rec["usage_at_start"] = readings
        else:
            rec.pop("usage_at_start", None)
        if rec:
            teams[team] = rec
        else:
            teams.pop(team, None)
        try:
            self.host_store.save(self._host_rec)
        except OSError:
            log.exception("writing the home's host record failed")

    async def _replay(
        self,
        s: Session,
        why: str,
        *,
        mark: dict[str, Any] | None = None,
        closing: str | None = None,
        held: bool = False,
        **extra: Any,
    ) -> None:
        """One restart by the tick (§6): the record's launch record handed to `create` again — here,
        or at its node — the attempt appended to `restarts` and the list carried onto the new record,
        so the count survives the restart it counts. A replay that fails keeps its entry with `error`
        and counts all the same. `mark` adds to the entry (rule 8's `ids`, what a start was for).
        `closing` is a line the prompt ends with, after it is filled again or stored (a manager on
        call's cause, `filled_for`, TD-410); no other replay adds one.
        `held` writes the record alone, `closed` with no pane (`create` with `held`), for rule 3 to
        fill once something is due, and the entry carries `held: true` (rule 8's start of a seat, TD-660).
        Every caller but a scheduled start (whose `start_of` moves the mail itself) passes `keep_mail`:
        the closed run's mail is the new record's, so a reply to its `ask` still has a thread (TD-352).
        Every entry, a failed one's too, carries `done` and `left` — what the run it replaces reported
        (`agent_common._reported`) — since the new record keeps none of the old one's `progress` (§4.9a, TD-245)."""
        if why in ("start", "work"):  # a schedule's start and rule 8's: the team's, if none of it runs
            self._mark_team_start(s.team, but=s)
        now = datetime.now(UTC)
        entry: dict[str, Any] = {
            "at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "why": why,
            **agent_common._reported(s, now),
            **(mark or {}),
            **({"held": True} if held else {}),
        }
        # a replay that keeps mail carries the waiting claims (§6 rule 5, TD-820): `left` is the rest
        carried = [copy.deepcopy(e) for e in self._waiting_claims(s)] if extra.get("keep_mail") else []
        if carried:
            entry["left"] = [r for r in entry.get("left") or [] if r not in {e.ref for e in carried}]
        history = [*s.restarts, entry]
        address = self._address(s)
        read: dict[str, Any] | None = None
        renamed: str | None = None
        try:
            params = {**self._read_launch(address), **extra, "supervised": True}
            if held:
                params["held"] = True
            mark_name = s.relaunch.get("name") if isinstance(s.relaunch, dict) else None
            if mark_name and params.get("name") == mark_name and mark_name != s.name:
                # a rename (§4.9, TD-706): the create under the new name succeeds this record, and a
                # name it never held has no mail to keep under it
                params.pop("keep_mail", None)
                params["succeeds"] = s.id
                renamed = mark_name
            read = await self._refill_prompt(s, params, entry)
            if params.get("prompt"):
                # the launch record keeps the prompt as this create hands it, so a stored prompt carries
                # the last fill's line: it goes, whatever replays now, and a fill's own is added
                params["prompt"] = params["prompt"].split(f"\n\n{FILLED_FOR}", 1)[0]
                if closing:
                    params["prompt"] = f"{params['prompt']}\n\n{closing}"
            if s.host == self.host:
                view = await self.rpc_create(**params)
            else:
                view = await self._route_act("create", {**params, "host": s.host}, None, s.host)
        except Exception as e:  # noqa: BLE001 — a failed replay is a restart that failed, and counts (§6)
            entry["error"] = str(e) or type(e).__name__
            log.warning("%s: the %s restart failed: %s", s.id, why, entry["error"])
            s.restarts = history
            self._save(s)
            await self._push_changes()
            return
        rid, _h = naming.split_address(str((view or {}).get("id") or ""))
        new = self.sessions.get(rid) if s.host == self.host else self.remote.get(s.host, {}).get(rid)
        if new is not None and renamed and s.host != self.host:
            self._carry(s, new)  # a node's create moved what it holds; the rest is the home's (§4.9)
            self._drop_launch(self._address(s))  # `_route_act` wrote the new id's
            self._save(s)
        if new is not None and renamed:
            await self._carry_controllers()  # a node member's own record takes the new lead now (TD-712)
        if new is not None:
            new.restarts = history
            held = {e.ref: e for e in new.progress if e.source == "declared" and e.status == "claimed"}
            for e in carried:
                e.at = entry["at"]  # a renewal of the lease (§4.8 *A claim is a lease*)
                if e.ref in held:
                    held[e.ref].at = e.at  # a rename's `_carry` copied it already
                elif new is not s:
                    new.progress.append(e)
            # the files as this replay read them, not as the create's check did; a replay of the stored
            # prompt carries none, since the create's working-tree read is not what the prompt was made
            # from, and the mark must not compare it (the techlead's read of #745)
            new.brief = read
            self._save(new)
            await self._push_changes()

    async def _refill_prompt(self, s: Session, params: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any] | None:
        """Rule 7's first half (design §6, TD-217 slice 2): a replay fills the brief again from what
        it was made from (`prompt_from`), with its files as merged, and hands `create` that prompt
        in place of the stored one; returns the record's `brief` as read. A launch record with no
        `prompt_from` (a prompt typed whole, a record written before it), a file that cannot be read,
        or a member on a node (its files are that host's, not the home's) replays the stored prompt,
        and the `restarts` entry says `prompt: stored`."""
        made = params.get("prompt_from")
        if not params.get("prompt"):
            return None  # nothing was typed at its start, and nothing is now
        if not isinstance(made, dict) or s.host != self.host:
            entry["prompt"] = "stored"
            return None
        try:
            text, sources = await asyncio.to_thread(brief_mod.fill, made, True)
        except brief_mod.Unreadable as e:
            log.info("%s: replaying the stored prompt: %s", s.id, e)
            entry["prompt"] = "stored"
            return None
        params["prompt"] = text
        return {"at": now_iso(), "sources": sources}

    def _read_launch(self, address: str) -> dict[str, Any]:
        """A launch record as `create`'s arguments (design §6): what `_write_launch` kept, less its own
        bookkeeping. Raises when there is none — a supervised record written before its launch record
        existed has nothing to replay, and that is a failed restart, said as one."""
        path = paths.launch_dir() / f"{address}.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise RpcError(f"no launch record for {address}: nothing to replay (design §6)") from None
        if not isinstance(record, dict):
            raise RpcError(f"the launch record of {address} is not a record")
        params = {k: record[k] for k in LAUNCH_KEYS if k in record}
        if isinstance(record.get("controllers"), list):
            params["controllers"] = list(record["controllers"])
        return params

    async def _seat_pass(self, s: Session, now: datetime, records: list[Session]) -> None:
        """Rule 3 (design §6 *Keeping a team running*, §4.9b): a supervised seat's `seat_due` from its
        trigger, the fill of an ended seat that is due — `create` with `keep_mail`, so a question that
        was waiting is still there — under `FILL_CEILING`, and the close of a seat that has run and
        sits idle with nothing due — or a due that is the next fill's (`_seat_done`) — and nothing
        left unpushed."""
        if not (s.seat and s.supervised and s.unattended) or s.superseded_by or s.suspended:
            return
        if s.sit_out or work_mod.sat_out(s):
            return  # a seat the definition dropped (TD-706): `_sit_out_close` ends it, and nothing fills it
        filled, seen, count = s.seat_filled, s.lane_seen, s.seat_count
        due = self._seat_due(s, now, records)
        if due != s.seat_due or s.seat_filled != filled or s.lane_seen != seen or s.seat_count != count:
            s.seat_due = due
            self._save(s)
            await self._push_changes()
        if s.host != self.host and s.host not in self._link_muxes:
            return  # its link is down: left as it is, looked at again next tick (§4.4a)
        if s.state in ("exited", "closed") and s.seat_due:
            await self._fill(s, now, records)
        elif s.state == "idle" and self._seat_done(s) and self._seat_has_run(s, now):
            waits = self._seat_prs(s, records)
            if waits and now - _parse(s.since) < SEAT_PR_WAIT:
                return  # it ended its turn to wait on its own PR's fact-check or CI (TD-366)
            if waits:
                log.info(
                    "%s: a seat idle %s on its own PR %s, which no reader holds — closing it (§6 rule 3)",
                    s.id,
                    SEAT_PR_WAIT,
                    ", ".join(waits),
                )
            else:
                log.info("%s: a seat with nothing due, idle and pushed — closing it (§6 rule 3)", s.id)
            closer = {"by": "tick", "why": "seat"}
            if s.host == self.host:
                await self.rpc_close(s.id, closer=closer)
            else:
                await self._route_act("close", {"id": s.id, "closer": closer}, None, s.host)

    @staticmethod
    def _seat_done(s: Session) -> bool:
        """Whether an idle seat has nothing left that this run of it will take: nothing due — or a
        due that is the next fill's: a `prs` or `every` one met while it ran
        (TD-700), and for a manager on call a reading of a member that came due after its fill,
        since a fill starts cold on the one reading its `seat_due` names (§6 rule 3, TD-259). A question
        waiting is the idle seat's own to read, as the techlead's is."""
        if not s.seat_due:
            return True
        if s.seat_due.get("by") == "tag":
            return True  # a tagging seat's `tag` due is the next fill's (§4.4 *An entry names its team*, TD-730)
        # a `prs`, `every` or `swept` due met while the seat ran is the next run's cause (TD-700, TD-1090)
        if (s.seat or {}).get("trigger") in ("prs", "every", "swept"):
            return True
        return (s.seat or {}).get("trigger") == "team" and s.seat_due.get("by") != "asks"

    def _team_causes(self, s: Session, records: list[Session]) -> list[dict[str, Any]]:
        """What a manager on call is filled for (§6 rule 3, TD-259), each a reading of the records
        and never of a screen, in this order: `asks` — each open `ask` or `steer` addressed to it,
        by id; then, of its members (the supervised records listing it in `controllers`), `pending`
        — hook-confirmed `needs-you` on a permission (a question or a menu is a person's);
        `stalled` — `stalled?`; `open` — carrying `idle_open`."""
        causes: list[dict[str, Any]] = [{"by": "asks", "ask": i} for i in s.asks_ids(home=self.host)]
        now = datetime.now(UTC)
        me = self._address(s)
        members = [
            r
            for r in records
            if r is not s and r.supervised and not r.superseded_by and not r.suspended and me in self._ctl(r)
        ]
        for by in ("pending", "stalled", "open"):
            for r in members:
                if by == "pending":
                    met = (
                        r.state == "needs-you"
                        and r.told
                        and r.pending is not None
                        and r.pending.kind == "permission"
                        # a permission only the terminal answers is never a seat's (§4.3, §6 rule 3, TD-785)
                        and adapters.permission_channel(r.adapter)
                    )
                elif by == "stalled":
                    met = r.state == "stalled?"
                else:
                    # a standing mark is no cause while a subagent or a shell of the member's runs (§6 rule 4)
                    met = r.state == "idle" and bool(r.idle_open) and not agent_common.on_its_own(r, now)
                if met:
                    causes.append({"by": by, "member": self._address(r)})
        return causes

    def _seat_due(self, s: Session, now: datetime, records: list[Session]) -> dict[str, Any] | None:
        """`seat_due: {at, by}` (§6 rule 3): set once the trigger is met and kept until the fill — but
        `asks` is a question waiting now, so it clears again if none is. `prs` reads `seat_count`,
        which `_count_seats` keeps; `every` is the time since this record was created; `swept` reads
        the repo's board's stamp (`_swept_met`). `team` is a
        manager on call's (TD-259): `{at, by, member}` — `ask` in `member`'s place for `asks` — the
        first cause standing that no fill was made for; `seat_filled` loses each entry whose cause
        has gone, here, and a due whose cause went before the fill is cleared as `asks` is."""
        seat = s.seat or {}
        trigger = seat.get("trigger")
        if trigger == "team":
            causes = self._team_causes(s, records)

            def same(a: dict[str, Any], b: dict[str, Any]) -> bool:
                return all(a.get(k) == b.get(k) for k in ("by", "member", "ask"))

            kept = [e for e in s.seat_filled if isinstance(e, dict) and any(same(e, c) for c in causes)]
            if kept != s.seat_filled:
                s.seat_filled = kept
            fresh = [c for c in causes if not any(same(e, c) for e in kept)]
            if s.seat_due and any(same(s.seat_due, c) for c in fresh):
                return s.seat_due
            return {"at": now_iso(), **fresh[0]} if fresh else None
        if seat.get("tags"):
            # a tagging seat (§4.4 *An entry names its team*, TD-730): `asks` while a question waits —
            # a standing `tag` due handed back would hide it — else `tag` while uncovered ids stand
            return self._asks_cause(s) or self._tag_cause(s, records)
        if trigger == "asks":
            return self._asks_cause(s)
        if trigger == "swept":
            # read again each tick, as `asks` is: a stamp written by hand, or a board unreadable, before
            # the fill clears the due — an unreadable board fills nothing (§4.9b *The sweep*, TD-1090)
            idle = self._sweep_idle(s, records)
            # why a switch-made seat is not the repo's, for its card (§4.9b *What a sweep seat's card says*)
            if (s.seat_count or {}).get("swept") != (idle or None):
                s.seat_count = {"swept": idle} if idle else None
            if idle or not self._swept_met(s, now):
                return None
            return s.seat_due if (s.seat_due or {}).get("by") == "swept" else {"at": now_iso(), "by": "swept"}
        if s.seat_due:
            return s.seat_due
        met = False
        if trigger == "prs":
            count = (s.seat_count or {}).get("prs")
            after = str(seat.get("after") or "")
            met = after.isdigit() and isinstance(count, int) and count >= int(after)
        elif trigger == "every":
            every = _duration(str(seat.get("after") or ""))
            met = every is not None and now - _parse(s.created) >= every
        return {"at": now_iso(), "by": trigger} if met else None

    def _swept_met(self, s: Session, now: datetime) -> bool:
        """A sweep seat's `swept: <d>` cause (design §4.9b *The sweep*, §6 rule 3, TD-1090): the boards
        reading of the seat's repo carries `swept` for its board (read from origin), and its `at` is
        null — never swept — or `d` old; **and** `d` has passed since the seat's last fill for it (its
        `seat_filled` entry `by: swept`), so a run that ended without stamping is not refilled in a loop.
        An `error` reading, no reading, no board, or a null `swept` (no board on origin) is no cause."""
        mark = s.seat or {}
        # a switch-made seat's `d` is the switch's `every` now, not the mark's from its start (TD-1091)
        after = settings_mod.sweep(settings_mod.load())["every"] if mark.get("by") == "settings" else mark.get("after")
        every = _duration(str(after or ""))
        reading = (self._repos.get(s.repo or "") or {}).get("boards")
        if every is None or not isinstance(reading, dict) or "error" in reading:
            return False
        board = next(
            (b for b in reading.get("boards") or () if isinstance(b, dict) and str(b.get("root")) == str(s.repo)),
            None,
        )
        stamp = (board or {}).get("swept")
        if not isinstance(stamp, dict):
            return False
        at = stamp.get("at")
        # the stamp is a civil date, the board's local day (cadence §3.10): its age from that day's start
        if at and now - datetime.fromisoformat(str(at)).astimezone() < every:
            return False
        fills = [
            _parse(e["at"])
            for e in s.seat_filled
            if isinstance(e, dict) and e.get("by") == "swept" and isinstance(e.get("at"), str)
        ]
        return not fills or now - max(fills) >= every

    def _asks_cause(self, s: Session) -> dict[str, Any] | None:
        """A seat's `asks` due while a question waits (§6 rule 3): `{at, by: asks, ask}`, `ask` the id of
        the first question `asks_ids` counts — an answer waiting by its question's (§4.9b, TD-1051) — the
        standing due kept while its question still counts, so its `at` is the first tick's."""
        ids = s.asks_ids(home=self.host)
        if not ids:
            return None
        due = s.seat_due or {}
        if due.get("by") == "asks" and due.get("ask") in ids:
            return s.seat_due
        return {"at": now_iso(), "by": "asks", "ask": ids[0]}

    def _tagging_seat(self, root: str, records: list[Session]) -> Session | None:
        """The repo's tagging seat (§4.4 *An entry names its team*, TD-730): among the repo's records
        carrying `seat.tags` whose team is live — an unattended session carrying its badge is live
        (§4.9 *Starting and stopping*), so a stopped team's seat is never filled for this — the one
        whose team comes first in the ledger's `declared_teams`, a team it leaves out after, by name."""
        return self._first_seat(root, records, lambda mark: bool(mark.get("tags")))

    def _sweep_idle(self, s: Session, records: list[Session]) -> str:
        """Why a sweep seat's `swept` cause may not be computed (design §4.9b *The switch*, §6 rule 3,
        TD-1091), "" where it may. A definition's sweeper always may; a switch-made one (`by: settings`)
        only while `sweep.on` and its repo not `off` (else `off`), no live team's record of the repo
        carrying a `swept` mark that is not `by: settings` (a team's own sweeper wins), and it is the
        repo's first such seat by team, as the tagging seat is chosen — one filled per repo (else
        `other`). Tested before a standing due is kept."""
        if (s.seat or {}).get("by") != "settings":
            return ""
        switch = settings_mod.sweep(settings_mod.load())
        root = str(s.repo or "")
        name = str((self._repos.get(root) or {}).get("name") or Path(root).name)
        if not switch["on"] or name in switch["off"]:
            return "off"
        live = self._live_teams(records)
        if any(
            r.repo == root
            and r.team in live
            and not r.superseded_by
            and (r.seat or {}).get("trigger") == "swept"
            and (r.seat or {}).get("by") != "settings"
            for r in records
        ):
            return "other"
        first = self._first_seat(root, records, lambda m: m.get("trigger") == "swept" and m.get("by") == "settings")
        return "" if first is s else "other"

    @staticmethod
    def _live_teams(records: list[Session]) -> set[str]:
        """The teams with an unattended session live (§4.9 *Starting and stopping*)."""
        return {
            r.team for r in records if r.team and r.unattended and not r.superseded_by and r.state not in work_mod.DEAD
        }

    def _first_seat(self, root: str, records: list[Session], marked: Any) -> Session | None:
        """Among the repo's seats whose mark `marked` takes and whose team is live — supervised,
        unattended, unsuspended — the one whose team comes first in the ledger's `declared_teams`, a
        team it leaves out after, by name (§4.4 *An entry names its team*)."""
        led = (self._repos.get(root) or {}).get("ledger") or {}
        declared = [str(t).casefold() for t in led.get("declared_teams") or []]
        live = self._live_teams(records)
        seats = [
            r
            for r in records
            if r.repo == root
            and marked(r.seat or {})
            and r.team in live
            and r.supervised
            and r.unattended
            and not r.superseded_by
            and not r.suspended
        ]

        def order(r: Session) -> tuple[int, int, str]:
            team = str(r.team).casefold()
            return (0, declared.index(team), "") if team in declared else (1, 0, team)

        return min(seats, key=order, default=None)

    def _tag_cause(self, s: Session, records: list[Session]) -> dict[str, Any] | None:
        """A tagging seat's `tag` cause (§4.4 *An entry names its team*, §6 rule 3, TD-730):
        `{at, by: tag, ids}`, `ids` the repo's `needs_team` that no `seat_filled` tag entry covers —
        coverage by set, so {A, B} filled, A tagged and C joined is a due for {C} alone — and only on
        the repo's tagging seat. A tag entry of `seat_filled` is kept while any of its ids is in
        `needs_team`. A repo with no reading yet changes nothing."""
        led = (self._repos.get(s.repo or "") or {}).get("ledger") or {}
        if "needs_team" not in led:
            return s.seat_due if (s.seat_due or {}).get("by") == "tag" else None
        need = [str(i) for i in led.get("needs_team") or []]

        def tag(e: Any) -> bool:
            return isinstance(e, dict) and e.get("by") == "tag"

        kept = [e for e in s.seat_filled if not tag(e) or set(map(str, e.get("ids") or [])) & set(need)]
        if kept != s.seat_filled:
            s.seat_filled = kept
        if self._tagging_seat(str(s.repo or ""), records) is not s:
            return None
        covered = {str(i) for e in kept if tag(e) for i in e.get("ids") or []}
        ids = [i for i in need if i not in covered]
        if not ids:
            return None
        if (s.seat_due or {}).get("by") == "tag" and s.seat_due.get("ids") == ids:
            return s.seat_due
        return {"at": now_iso(), "by": "tag", "ids": ids}

    async def _fill(self, s: Session, now: datetime, records: list[Session]) -> None:
        """A due seat, ended, is filled — unless its profile is paused, or it or its fellows are at
        the fill ceiling: six fills an hour over all seats sharing a controller (the graph, never the
        team badge). The seat whose fill tripped it gets `restart_ceiling` and the Inbox row; its
        fellows are merely refused until the hour rolls. Fills never count toward `RESTART_CEILING`."""
        if s.restart_ceiling or self._profile_gated(s.profile, now, s.team):
            return
        mine = set(self._ctl(s))
        fellows = [
            r for r in records if r.seat and not r.superseded_by and (r is s or (mine and mine & set(self._ctl(r))))
        ]
        fills = [
            e
            for r in fellows
            for e in r.restarts
            if isinstance(e, dict) and e.get("why") == "fill" and _recent(e.get("at"), now, FILL_WINDOW)
        ]
        if len(fills) >= FILL_CEILING:
            tripped = any(
                r is not s
                and isinstance(r.restart_ceiling, dict)
                and r.restart_ceiling.get("why") == "fill"  # a lost brief's ceiling is no fill's (TD-720)
                and _recent(r.restart_ceiling.get("at"), now, FILL_WINDOW)
                for r in fellows
            )
            if not tripped:
                s.restart_ceiling = {"at": now_iso(), "count": len(fills), "why": "fill"}
                log.warning(
                    "%s: %d seat fills in %s — the ceiling; it is a person's now", s.id, len(fills), FILL_WINDOW
                )
                self._save(s)
                await self._push_changes()
            return
        log.info("%s: the seat is due (%s) — filling it", s.id, (s.seat_due or {}).get("by"))
        seat = s.seat or {}
        tagged = bool(seat.get("tags")) and (s.seat_due or {}).get("by") == "tag"
        # a manager on call's cause, a tagging seat's `tag` (TD-730), or a sweep seat's `swept`, which is
        # remembered so it fills once (TD-1090) but says nothing (`filled_for`); a techlead's `asks` fill has none
        cause = s.seat_due if seat.get("trigger") in ("team", "swept") or tagged else None
        # a manager on call says why it came (§6 rule 3 *A fill says why it came*, TD-410): its first
        # act is the reading `seat_due` names, read back from the record, never `ao status` first
        said = filled_for(cause)
        if cause and any(e.id == cause.get("ask") and e.handed_entry for e in s.inbox):
            cause = None  # an entry the person handed it fills the seat while it owes, as any seat's (TD-218)
        await self._replay(s, "fill", mark={"for": "seat_due"} if said else None, closing=said, keep_mail=True)
        new = self.sessions.get(s.id) if s.host == self.host else self.remote.get(s.host, {}).get(s.id)
        if cause and new is not None and new is not s:
            # the fill was made: the cause is remembered on the record that took the seat
            new.seat_filled = [*s.seat_filled, {**{k: v for k, v in cause.items() if k != "at"}, "at": now_iso()}]
            self._save(new)

    def _seat_prs(self, s: Session, records: list[Session]) -> list[str]:
        """What of its own an idle seat may be waiting on (§6 rule 3, TD-366): an open PR on the branch
        it has checked out, as the repo reading has it; a claim on its record carrying a PR not read
        merged or closed; and a claim derived from that branch whose PR no reading has yet — what a
        seat that opened its PR a minute ago holds. A PR it handed to a reader (an `ask` carrying it,
        still open in any record's inbox) is the reader's, and nothing it waits on."""
        branch = str((s.git or {}).get("branch") or "")
        found: list[str] = []
        opened = ((self._repos.get(s.repo or "") or {}).get("prs") or {}).get("open") or []
        for p in opened:
            if branch and isinstance(p, dict) and p.get("branch") == branch and isinstance(p.get("number"), int):
                found.append(f"#{p['number']}")
        for e in s.progress:
            if e.status != "claimed" or e.why == PR_CLOSED:
                continue
            number = e.pr or e.review_pr
            if number:
                found.append(f"#{number}")
            elif e.source == "derived" and branch and e.branch == branch:
                found.append(branch)
        handed: set[str] = set()
        for r in records:
            for a in (r.prs_waiting(home=self.host) or {}).get("asks", []):
                sid, host = naming.split_address(str(a.get("from") or ""))
                if (sid, host or self.host) == (s.id, s.host or self.host):
                    handed.add(f"#{a['pr']}")
        return sorted({w for w in found if w not in handed})

    def _seat_has_run(self, s: Session, now: datetime) -> bool:
        """A seat to close (§6 rule 3): hook-confirmed idle for `SEAT_IDLE_GRACE` — counted from the later
        of `since` and `subagent_at`, with no live subagent (TD-734: a seat that ended its turn on a
        reviewer subagent is working) — with its git known and nothing uncommitted or unpushed — a seat
        that left work is the board's, as today."""
        git = s.git or {}
        idle = agent_common.idle_from(s)  # from the later of `since`, `subagent_at` and `shells_at` (TD-734, TD-766)
        return bool(
            s.state == "idle"
            and s.told
            and idle is not None
            and now - idle >= SEAT_IDLE_GRACE
            and not agent_common.on_its_own(s, now)
            and git
            and not git.get("dirty")
            and not git.get("unpushed")
            and not s.pending
        )

    def _turned_unserved(self, root: str, old: Any, new: dict[str, Any]) -> None:
        """A served repo that turns unserved (§5 *The seams*, TD-1011): the person gets one `system` note
        for each team running there, naming the first lack — the reading before said `ok`, so a repo read
        unserved from the first is told nothing, and the next turn is told once more."""
        was = ((old or {}).get("seams") or {}).get("serve") if isinstance(old, dict) else None
        lacks = seams_mod.unserved(new)
        if not (lacks and isinstance(was, dict) and was.get("ok") is True):
            return
        live = {s.team for s in self._graph().values() if s.team and s.repo == root and s.state not in work_mod.DEAD}
        for team in sorted(live):
            text = f"{Path(root).name} is {lacks[0]} — team {team} has no lane until it is cured"
            log.info("%s", text)
            self._system_note(PERSON, text)

    async def _refresh_repos(self) -> None:
        """The repo facts (design §4.4 *Repo facts*, TD-176): for every checkout the repos registry
        lists, the PRs and the ledger with its history every `REPOS_EVERY`, and the ledger alone on
        any tick its file's mtime moved, and the board on its own clock, `BOARD_EVERY` (§4.4 *The
        boards*, TD-615). The PRs are read once per remote, so two checkouts of one
        repo are one `gh` read. A read that failed keeps the last reading with `error` and
        `failed_at` beside it — an outage is never zero PRs. A changed reading is saved and pushed
        as a `repos` event; a checkout the registry no longer lists is dropped with `repo: null`."""
        try:
            due = time.monotonic() - self._repos_read_at >= REPOS_EVERY or self._repos_fresh
            if due:  # cleared before the read: a `pr_wait --fresh` asked while it runs gets the next pass (TD-940)
                self._repos_fresh = False
            boards = due or time.monotonic() - self._boards_read_at >= BOARD_EVERY
            roots = hosts.local_host().repos()
            mtimes = await asyncio.to_thread(self._ledger_mtimes, roots)
            ledgers = {r for r in roots if due or mtimes.get(r) != self._ledger_mtime.get(r) or r not in self._repos}
            todo = [r for r in roots if boards or r in ledgers]
            gone = [r for r in self._repos if r not in roots]
            if not (todo or gone):
                return
            prev = {r: self._repos.get(r) or {} for r in todo}
            began = time.monotonic()
            # a checkout read for the first time gets the whole reading at once, not in five minutes
            full = {r for r in todo if due or r not in self._repos}
            live = self._live_commits() if self._promotes_read else None  # None: unknown (TD-516)
            read, keys = self._read_repos, self._held_keys(roots)
            got = await asyncio.to_thread(read, todo, prev, full, roots, live, ledgers, boards, keys) if todo else {}
            if due:
                self._repos_read_at = time.monotonic()  # after the read: a read that raised is retried next tick
            if boards:
                self._boards_read_at = time.monotonic()
            for root in todo:
                self._ledger_mtime[root] = mtimes.get(root)
            for r, v in got.items():
                # the red PRs' orders and memory are the tick's (`_red_prs`), never the read's: carried
                if (po := (self._repos.get(r) or {}).get("pr_orders")) is not None:
                    v.setdefault("pr_orders", po)
                # and the sync pass's outcomes are the pass's (§6 *Sync*, TD-685)
                if (so := (self._repos.get(r) or {}).get("sync")) is not None:
                    v.setdefault("sync", so)
                # a write-back re-read this board while the pass ran: its reading is the newer (`_reread_board`)
                if self._boards_pressed.get(r, float("-inf")) >= began and r in self._repos:
                    v.update({k: self._repos[r][k] for k in ("boards", "work_orders") if k in self._repos[r]})
            changed = {r: v for r, v in got.items() if v != self._repos.get(r)}
            for r, v in changed.items():
                self._turned_unserved(r, self._repos.get(r), v)
            for r in gone:
                self._repos.pop(r, None)
                self._ledger_mtime.pop(r, None)
            self._repos.update(changed)
            if changed or gone:
                self.repos_store.save(self._repos)
            for r in changed:
                await self._broadcast({"event": "repos", "root": r, "repo": self._repo_view(r)})
            for r in gone:
                await self._broadcast({"event": "repos", "root": r, "repo": None})
            if due:  # one reading of the PRs, a step of the *CI not starting* spells (§4.4 *Its spell*, TD-687)
                await self._ci_spells_step()
        except Exception:  # noqa: BLE001 — a detached task: log it, and the next tick tries again
            log.exception("reading the repo facts failed")

    async def _red_prs(self, now: datetime) -> None:
        """Design §4.4 *A red PR nobody holds is a work order* (TD-613): on every tick at the home, each
        repo's open PRs that have read red or conflicting for `ORPHAN_AFTER` are read against the live
        records of that repo — an unheld one is a `pr:<n>` order under the reading's `pr_orders`, an
        idle holder is told once per red spell (a `system` note, outside the wake budget), and `after`
        that, still idle, no longer holds it. A sync PR is an order from the first reading that sees
        it, first in the list (§4.4 *A sync PR is the team's at once*, TD-684). It keeps the first ask
        of each open PR the mail holds, `asked`, and lists the held PRs nobody asked, `unasked` (§4.4 *A
        held PR nobody asked is marked, never ordered*, TD-789). A change is saved and pushed as a
        `repos` event."""
        graph = self._graph()
        records = [r for r in graph.values() if r.repo]
        found = held_mod.asks(graph, self.person_inbox, self._repos)
        sync_on, at = self._sync_on(), datetime.now(UTC)
        for root, r in list(self._repos.items()):
            try:
                prs = (r.get("prs") or {}).get("open") or []
                # a sync PR the home holds is no order; one it judged takes its `why` (§6 *Sync*, TD-685)
                prs = sync_mod.mark(
                    prs, r.get("sync") or {}, self._sync_covers(root, sync_on.get(Path(root).name, True), at)
                )
                old = r.get("pr_orders") or {}
                mine = [x for x in records if x.repo == root]
                if seams_mod.unserved(r):  # no order in an unserved repo (§5 *The seams*, TD-1011)
                    orders, told, notes = [], old.get("told") or {}, []
                else:
                    orders, told, notes = workorders.red_prs(prs, mine, now, old.get("told") or {}, ORPHAN_AFTER)
                by_id = {x.id: x for x in mine}
                for sid, pr in notes:
                    rec = by_id[sid]  # addressed as mail is: a node's record as `<id>@<host>`
                    self._system_note(self._address(rec), workorders.pr_note(pr), wake="uncharged", team=rec.team)
                    log.info("%s: told PR #%s is red with it idle", sid, pr["number"])
                held = workorders.red_holders(prs, mine, now, ORPHAN_AFTER)  # the pages' *held by* (TD-652)
                # the first ask is kept past the mail's prune, and dropped once its PR closes
                asked = {**(found.get(root) or {}), **(old.get("asked") or {})}
                if "open" in (r.get("prs") or {}):
                    numbers = {str(p.get("number")) for p in prs if isinstance(p, dict)}
                    asked = {n: a for n, a in asked.items() if n in numbers}
                unasked = held_mod.unasked(prs, asked, held_mod.has_reader(root, graph, self._repos))
                new = {"orders": orders, "told": told, "held": held, "asked": asked, "unasked": unasked}
                if new == {
                    "orders": old.get("orders") or [],
                    "told": old.get("told") or {},
                    "held": old.get("held") or {},
                    "asked": old.get("asked") or {},
                    "unasked": old.get("unasked") or [],
                }:
                    continue
                if (cur := self._repos.get(root)) is None:
                    continue  # dropped from the registry while this pass ran
                self._repos[root] = {**cur, "pr_orders": new}  # never the snapshot: a re-read may have landed
                self.repos_store.save(self._repos)
                await self._broadcast({"event": "repos", "root": root, "repo": self._repo_view(root)})
            except Exception:  # noqa: BLE001 — one repo's surprise is a log line; the next tick reads again
                log.exception("reading the red PRs of %s failed", root)

    async def _queue_pass(self, now: datetime) -> None:
        """The Queue's reading (§4.4 *The Queue*, TD-769), at the home on every tick: derived from the
        repo readings, the live graph's claims, who waits on a question (the person's, or a reader
        holding a PR's ask) and the doing log, and pushed as a `queue` event when it changed — its `at`
        aside. A surprise is a log line, and the last reading stands."""
        try:
            graph = list(self._graph().values())
            # by record id: an inbox names a node's sender `id@host`, as the readers' asks do
            waiting = {naming.split_address(k)[0] for k in work_mod.waiting_of(self.person_inbox)}
            for r in graph:
                for a in (r.prs_waiting(home=self.host) or {}).get("asks") or ():
                    if isinstance(a, dict) and a.get("from"):
                        waiting.add(naming.split_address(str(a["from"]))[0])
            doing = {t: list(r) for t, r in self.doing_log.rings.items()}
            got = queue_mod.reading(self._repos, graph, now, waiting=waiting, doing=doing, pressers=self._presser_words)
        except Exception:  # noqa: BLE001 — the Queue is a reading: the last one stands, the next tick tries again
            log.exception("reading the queue failed")
            return
        old = self._queue or {}
        self._queue = got
        if {k: v for k, v in got.items() if k != "at"} != {k: v for k, v in old.items() if k != "at"}:
            await self._broadcast({"event": "queue", "queue": self._queue_ranked(got)})

    def _repo_view(self, root: str) -> dict[str, Any] | None:
        """A checkout's reading as the `repos` RPC and event serve it: the reading, and under
        `balance` the marks of the teams over their line in this repo (§6 *Balance*), by team."""
        v = self._repos.get(root)
        if v is None:
            return None
        v = self._held_words(v)
        marks = {
            team: rec["balance"]
            for team, rec in (self._host_rec.get("teams") or {}).items()
            if isinstance(rec.get("balance"), dict) and rec["balance"].get("repo") == root
        }
        return {**v, "balance": marks} if marks else dict(v)

    def _held_words(self, v: dict[str, Any]) -> dict[str, Any]:
        """A reading whose held entries carry their presser in words beside `held.by` (`held.words`,
        `mail.presser_words` over the graph now, §4.8 *The record names who pressed*, TD-1127), for the
        *held (person)* mark's `title`; the stored reading is left as it is."""
        led = v.get("ledger") or {}
        entries = led.get("entries")
        if not isinstance(entries, list) or not any(
            isinstance(e, dict) and isinstance(e.get("held"), dict) for e in entries
        ):
            return v
        out = [
            {**e, "held": {**e["held"], "words": self._presser_words(str(e["held"].get("by") or ""))}}
            if isinstance(e, dict) and isinstance(e.get("held"), dict)
            else e
            for e in entries
        ]
        return {**v, "ledger": {**led, "entries": out}}

    async def _balance_marks(self, now: datetime) -> None:
        """Design §6 *Balance* (TD-239): on every tick at the home, each team whose `teams.<team>.balance`
        is set is read against the repo facts of the registered repos its live members name (`repo`)
        and the reader's queue on its seats, and its mark — `balance: {since, repo, crossed}` on the
        home's `host` record under the team's name — is written, kept (its `since` with it) or removed.
        A reading that cannot be told leaves the mark as it stands; a team with no key, or with no live
        member, has none. A change is saved, and pushed as a `repos` event for each repo it touches;
        one team's surprise costs that team's reading this tick, never another's or the save."""
        teams = self._host_rec.setdefault("teams", {})
        try:
            settings = settings_mod.teams(settings_mod.load())
        except Exception:  # noqa: BLE001 — a policy's surprise is a log line; the next tick reads again
            log.exception("reading the teams' settings for the balance failed")
            return
        if not teams and not any(v.get("balance") for v in settings.values()):
            return
        live: dict[str, list[Session]] = {}
        for r in self._graph().values():
            if r.team and r.state not in ("exited", "closed") and not r.superseded_by:
                live.setdefault(r.team, []).append(r)
        touched: set[str] = set()
        dirty = False
        for team in sorted(set(teams) | set(settings)):
            try:
                rec = teams.get(team) or {}
                old = rec.get("balance")
                members = live.get(team) or []
                new = self._balance_mark(old, (settings.get(team) or {}).get("balance"), members, now)
                if new is ...:
                    continue  # could not look: the mark stands as it was, or stays absent
                if new is None:
                    self._balance_ring(team)
                told = self._balance_tell(team, rec, new, members, now)
                if new == old and not told:
                    continue
                dirty = True
                touched |= {m["repo"] for m in (old, new) if isinstance(m, dict) and m.get("repo")}
                if new is None:
                    rec.pop("balance", None)
                else:
                    rec["balance"] = new
                if rec:
                    teams[team] = rec
                else:
                    teams.pop(team, None)
            except Exception:  # noqa: BLE001 — one team's surprise is a log line, never the others'
                log.exception("reading %s's balance failed", team)
        if not dirty:
            return
        try:
            self.host_store.save(self._host_rec)
        except OSError:
            log.exception("writing the home's host record failed")
        for root in sorted(touched):
            await self._broadcast({"event": "repos", "root": root, "repo": self._repo_view(root)})

    def _balance_tell(
        self, team: str, rec: dict[str, Any], mark: dict[str, Any] | None, members: list[Session], now: datetime
    ) -> bool:
        """Design §6 *Balance*, *Who is told*: one `system` note to the team's manager and one to the
        person on a crossing, and the same pair when it clears. What was last told is kept on the team's
        `host` record (`balance_told: {state, at, since}`, `at` the last note of either kind), so a restart
        tells nothing twice; a crossing inside `FLAP` of the last note waits until it is that far from
        it, so a mark that comes and goes tells one pair. A team that wound down loses its mark with
        nobody to tell, and its memory with it. True when `rec` changed."""
        told = rec.get("balance_told") if isinstance(rec.get("balance_told"), dict) else {}
        if not members:
            return rec.pop("balance_told", None) is not None
        at = _parse(told["at"]) if told.get("at") else None  # when the last note was sent, either kind
        sent = now.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")  # the tick's clock
        if mark is not None:
            if told.get("state") == "over" or (at is not None and now - at < balance_mod.FLAP):
                return False
            text, told = (
                balance_mod.crossing(team, mark),
                {"state": "over", "at": sent, "since": mark.get("since")},
            )
        elif told.get("state") == "over":
            text, told = balance_mod.clearing(team, told), {**told, "state": "clear", "at": sent}
        elif told and (at is None or now - at >= balance_mod.FLAP):
            return rec.pop("balance_told", None) is not None  # the flap window is over: nothing left to hold
        else:
            return False
        for lead in self._balance_leads(members):
            self._system_note(lead, text)
        self._system_note(PERSON, text)
        rec["balance_told"] = told  # after the notes: one that raised is sent again next tick
        log.info("balance: %s", text)
        return True

    def _balance_leads(self, members: list[Session]) -> list[str]:
        """The controllers the team's members share — its manager (§6 *Balance*) — read from the members
        the rule refuses (unattended, no seat) that control no teammate; none when a person leads."""
        leads = {c for m in members for c in self._ctl(m)}  # in the home's form: a node's member is `id@host`
        sets = [set(self._ctl(m)) for m in members if self._address(m) not in leads and m.unattended and m.seat is None]
        return sorted(set.intersection(*sets)) if sets else []

    def _balance_ring(self, team: str) -> None:
        """The mark went: each live member refused while it stood is rung, once, within its wake budget
        (§6 *Balance*), and the field that held it back from the nudge and the lane news goes. A node's
        member is refused at the home, so its record here carries the field and the note lands in the
        home's copy of it, which the doorbell rings through its node (§4.4a, TD-1079)."""
        for s in self._graph().values():
            if s.team != team or not s.balance_refused:
                continue
            s.balance_refused = None
            if s.state in ("exited", "closed"):
                self._save(s)
                continue
            self._system_note(self._address(s), balance_mod.CLEAR)  # saves the record

    def _balance_mark(
        self, old: Any, bal: dict[str, Any] | None, members: list[Session], now: datetime
    ) -> dict[str, Any] | None | Any:
        """One team's mark as it reads now (`_balance_marks`): None when it has none, `...` when it
        cannot be told. The team's repos are the ones its live members name **that the home reads**
        — a registry root (§6 *Balance*); a path the registry does not list is not the team's repo."""
        if not bal or not members:
            return None
        roots = sorted({m.repo for m in members if m.repo and m.repo in self._repos})
        waiting = [str(w["oldest"]) for m in members if m.seat and (w := m.prs_waiting(home=self.host))]
        bounds = [d for m in members if (d := balance_mod.span((m.review or {}).get("bound")))]
        got = balance_mod.crossed(
            bal, roots, self._repos, min(waiting) if waiting else None,
            min(bounds) if bounds else balance_mod.REVIEW_BOUND, now,
        )  # fmt: skip
        if got is None:
            return ...
        crossed, repo = got
        if not crossed:
            return None
        since = old["since"] if isinstance(old, dict) and old.get("since") else now_iso()
        return {"since": since, "repo": repo, "crossed": crossed}

    @staticmethod
    def _ledger_mtimes(roots: list[str]) -> dict[str, tuple[str, float] | None]:
        """Each root's `ledger.stamp`: the resolved path and its newest mtime, either layout (§4.4)."""
        return {root: ledger_mod.stamp(root) for root in roots}

    def _live_commits(self) -> dict[str, str]:
        """Each repo's live commit as the promote reading holds it (§6 *Promote*), by the repo's
        name, for a live check's `live` (§4.9b, TD-323): a reading that carries `live_why` — the live
        commit could not be read — names none, and unknown is never live."""
        return {name: str(r["live"]) for name, r in self._promotes.items() if r.get("live") and not r.get("live_why")}

    def _held_keys(self, roots: list[str]) -> dict[str, list[str]]:
        """Each root's held key for the PR read (§4.4 *A held PR nobody asked is marked*, TD-789):
        `held.repo_key` from the graph, and the union over the roots of one remote (`by_remote` reads
        it once for them all, at the first root's key on a pass where no `remote` is read yet)."""
        records = list(self._graph().values())
        own = {r: held_mod.repo_key(r, records) for r in roots}
        union: dict[str, set[str]] = {}
        for r in roots:
            remote = str((self._repos.get(r) or {}).get("remote") or "") or r
            union.setdefault(remote, set()).update(own[r])
        return {r: sorted(union[str((self._repos.get(r) or {}).get("remote") or "") or r]) for r in roots}

    @staticmethod
    def _read_repos(
        roots: list[str],
        prev: dict[str, dict[str, Any]],
        full: set[str],
        registry: list[str] | None = None,
        live: dict[str, str] | None = None,
        ledgers: set[str] | None = None,
        boards: bool = False,
        keys: dict[str, list[str]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Each checkout's reading, in a thread: `{name, root, remote, ledger, prs, at}`. A root in
        `full` has its PRs and the ledger's history read; the others their ledger's entries alone,
        the rest carried from `prev`. One checkout's read that raises keeps its last reading with
        the error beside it and never costs the others theirs. `ledgers`, where given, are the roots
        whose ledger is read — the others keep their last ledger, read again for the board alone —
        and `boards` is the board's own clock, `BOARD_EVERY` (`_read_repo`). `live` is `_live_commits`: a live
        check's build is read against its repo's (§4.9b). `None` — no promote reading since the
        host agent started — is unknown, not *not live*: each live check keeps the `live` its last
        reading gave it (§6 rule 6, TD-516), so a restart never takes one out of a lane and brings
        it back as new. A promote pass that keeps failing keeps it unknown, and nothing goes live
        while it does. `keys` is each root's held key (`_held_keys`): the thread has no records."""
        now = datetime.now(UTC)
        stamp = now.isoformat()
        by_remote: dict[str, dict[str, Any]] = {}
        out: dict[str, dict[str, Any]] = {}
        # `<repo>#TD-NNN` blockers resolve among every checkout the registry lists, not only the ones
        # re-read this pass (the techlead's read of #793); each repo read once per pass (TD-228)
        resolve = ledger_mod.Registry(registry if registry is not None else roots)
        for root in roots:
            old = prev.get(root) or {}
            try:
                reader = ledger_mod.LiveReader(root, (live or {}).get(Path(root).name))
                led = ledgers is None or root in ledgers or "ledger" not in old
                out[root] = TickMixin._read_repo(
                    root, old, root in full, now, by_remote, resolve, reader, ledger=led, boards=boards,
                    held=(keys or {}).get(root), roster=registry if registry is not None else roots,
                )  # fmt: skip
                if live is None:  # no promote reading yet since the start: unknown is not *not live* (TD-516)
                    _carry_live(out[root], old)
            except Exception as e:  # noqa: BLE001 — one checkout's surprise is its reading's error, not the batch's
                log.exception("reading the repo facts of %s failed", root)
                why = f"the read failed: {type(e).__name__}"
                out[root] = {
                    "name": Path(root).name,
                    "root": root,
                    "remote": str(old.get("remote") or ""),
                    "ledger": {**(old.get("ledger") or {}), "error": why, "failed_at": stamp},
                    "prs": {**(old.get("prs") or {}), "error": why, "failed_at": stamp},
                    **({"seams": old["seams"]} if old.get("seams") is not None else {}),
                    "at": str(old.get("at") or stamp),
                }
        return out

    @staticmethod
    def _fork_lines(root: str, prs: Any) -> Any:
        """The PR reading as `root`'s checkout gives it (design §4.5 screen 11 *Review*, TD-1292): each
        fork's PR row carries `precheck_line`, the person's `--fork-ok` line led by `cd <root>`
        (`cadence.precheck_person`), for this checkout's own root. The reading is shared by every checkout
        of one remote (`by_remote`), so the rows are copied, never written in place; a GitLab reading's
        rows, which carry no `prechecked`, get none."""
        rows = prs.get("open") if isinstance(prs, dict) else None
        if not isinstance(rows, list):
            return prs
        out: list[Any] = []
        for p in rows:
            if isinstance(p, dict) and (p.get("fork") or "precheck_line" in p):
                p = {k: v for k, v in p.items() if k != "precheck_line"}
                line = cadence_mod.precheck_person(root, p["number"]) if p.get("fork") and "prechecked" in p else None
                if line:
                    p["precheck_line"] = line
            out.append(p)
        return {**prs, "open": out}

    @staticmethod
    def _read_repo(
        root: str,
        old: dict[str, Any],
        due: bool,
        now: datetime,
        by_remote: dict[str, dict[str, Any]],
        resolve: ledger_mod.Resolve | None = None,
        live: ledger_mod.Live | None = None,
        *,
        ledger: bool = True,
        boards: bool = False,
        held: list[str] | None = None,
        roster: list[str] | None = None,
    ) -> dict[str, Any]:
        """One checkout's reading (`_read_repos`): `by_remote` holds the PR readings taken in this
        pass, so two checkouts of one remote are one `gh` read. `ledger` False keeps the last
        ledger as it stands (a pass for the board alone); `boards` is the board's clock (`_read_boards`);
        `roster` the registry's checkouts, where the seams find agent-cadence's (§5 *Which agent-cadence*)."""
        stamp = now.isoformat()
        remote = reports._git(root, "remote", "get-url", "origin") if due else None
        remote = (remote or "").strip() if due else str(old.get("remote") or "")
        old_led = old.get("ledger") or {}
        led = ledger_mod.reading(root, now, with_history=due, resolve=resolve, live=live) if ledger else old_led
        if not ledger:
            led = dict(old_led)  # a pass for the board alone
        elif "error" in led:
            led = {**old_led, "error": led["error"], "failed_at": stamp}
        elif not due:
            led.update({k: old_led[k] for k in ("windows", "recent", "history_error") if k in old_led})
        elif "history_error" in led:
            led.update({k: old_led[k] for k in ("windows", "recent") if k in old_led})
        prs = old.get("prs")
        if due:
            if remote and remote in by_remote:
                prs = by_remote[remote]
            else:
                fresh = reports.pr_reading(root, now, old=prs, held=held, remote=remote)
                prs = {**(prs or {}), "error": fresh["error"], "failed_at": stamp} if "error" in fresh else fresh
                if remote:
                    by_remote[remote] = prs
            prs = TickMixin._fork_lines(root, prs)  # this checkout's own copy (§4.5 screen 11, TD-1292)
        seams = old.get("seams")
        if due or seams is None:  # §4.4 *The seams*: on the repo reading's own cadence
            try:
                seams = seams_mod.reading(root, roster or [root], seams)
            except Exception:  # noqa: BLE001 — a seam that cannot be read keeps the last reading
                log.exception("reading the seams of %s failed", root)
            seams = seams_mod.with_adoption(seams, root, prs)  # *adoption PR #n open* (§5 *The seams*, TD-1010)
        if isinstance(led.get("entries"), list) and not seams_mod.unserved({"seams": seams}):
            # the settle clock (§4.4 *A new entry settles before it is pickable*, TD-710): a fresh reading is
            # recorded and marked, a carried one marked again, so a window ends when its time does; an
            # unserved repo has none (§5 *The seams*, TD-1011)
            TickMixin._settle(root, remote, led["entries"], now, fresh=ledger and "error" not in led)
        bds, wos = TickMixin._read_boards(root, old, due, boards, stamp)
        return {
            "name": Path(root).name,
            "root": root,
            "remote": remote,
            "ledger": led,
            "prs": prs,
            "boards": bds,
            "work_orders": wos,
            "seams": seams,
            # what closed, and by which PR (§4.4 *Repo facts*, TD-604): the history's and the PRs' join
            "completed": ledger_mod.completed(led.get("recent"), (prs or {}).get("recent")),
            "at": stamp if due else str(old.get("at") or stamp),
        }

    @staticmethod
    def _settle(root: str, remote: str, entries: list[Any], now: datetime, *, fresh: bool) -> None:
        """Mark a ledger reading's entries `settling` or `held` from the home's clock, and `waiting` from
        their `Waits:` lines (`sessionorc.settle`, §4.4, TD-710, TD-716), keyed by the checkout's origin
        (its path where it has none); `fresh` records the reading first — never while the checkout's
        origin is not yet known, since the clock is keyed by it and a first reading under another key
        would settle everything at the epoch. The durations are the repo's `settle:` over the install's
        over the built-in. A clock that cannot be written marks no settling, and says so in the log:
        entries go at once; their waits are marked all the same."""
        if not remote:
            fresh = False
        key = settle_key(root, remote)
        spans = settle_mod.spans(root)
        got = [e for e in entries if isinstance(e, dict)]
        try:
            (settle_mod.observe if fresh else settle_mod.mark)(got, key, spans, now)
        except OSError as e:
            log.warning("the settle clock of %s could not be kept: %s", root, e)
            settle_mod.mark_waits(got, now)  # a wait needs no clock (TD-716)

    @staticmethod
    def _read_boards(
        root: str, old: dict[str, Any], due: bool, clock: bool, stamp: str, *, tree: Path | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """The checkout's board and the work orders derived from it (§4.4 *Each reading has one owner*,
        *The boards*, TD-615): `boards` — `workorders.read_boards`' reading, with `file` the checkout's
        board as last read (its mtime and size), `today` the reading's day and `at` — and the lanes'
        `work_orders`, its decided open lines (TD-384), never a second read.

        `due` (the `REPOS_EVERY` pass) reads against origin (`workorders._against_origin`); `clock`
        (`BOARD_EVERY`) reads the checkout plainly, and only when its board's file or the day moved
        since the last reading, so a board read from origin stays so until the checkout pulls; `tree`
        reads that file — the write-back's tree — as the checkout's board read from origin. A failed
        read keeps the last boards and orders with `error` and `failed_at` beside them. A board read of
        the checkout alone (the clock's, or a due pass whose fetch was skipped) carries the last `swept`
        of the same board (`root` and `label`) forward: only a read against origin writes it (§4.9b
        *The sweep*, TD-1090)."""
        bds, wos = old.get("boards"), old.get("work_orders")
        try:
            st = (Path(root) / workorders.board_rel(root)).stat()
            file: list[int] | None = [st.st_mtime_ns, st.st_size]
        except OSError:
            file = None
        today = datetime.now().date().isoformat()  # the reading's own day, local
        new_day = bds is not None and bds.get("today") != today
        moved = bds is None or "error" in bds or bds.get("file") != file or new_day
        if not (due or tree is not None or (clock and moved)):
            return bds or {"boards": []}, wos or {"orders": []}
        # a new day re-reads a board last read from origin against origin: the checkout's would bring
        # back a press it has not pulled (review of TD-615)
        from_origin = new_day and any(isinstance(b, dict) and b.get("source") for b in bds.get("boards") or ())
        got = workorders.read_boards(root, fetch=due or from_origin, board=tree)
        if "error" in got:
            # the same error again is the same reading: no save and no push every `BOARD_EVERY`
            same = bds is not None and bds.get("error") == got["error"] and bds.get("failed_at")
            at = str(same) if same else stamp
            bds = {**(bds or {"boards": []}), "error": got["error"], "failed_at": at}
            wos = {**(wos or {"orders": []}), "error": got["error"], "failed_at": at}
            return bds, wos
        was = {
            (b.get("root"), b.get("label")): b["swept"]
            for b in (bds or {}).get("boards") or ()
            if isinstance(b, dict) and "swept" in b
        }
        for b in got["boards"]:
            if isinstance(b, dict) and "swept" not in b and (b.get("root"), b.get("label")) in was:
                b["swept"] = was[(b.get("root"), b.get("label"))]
        bds = {"boards": got["boards"], "today": got.get("today") or today, "file": file, "at": stamp}
        return bds, {"orders": [workorders.entry(o) for o in workorders.orders(bds)], "at": stamp}

    async def _count_seats(self, records: list[Session]) -> None:
        """`seat_count` for every supervised `prs:` seat (§6 rule 3): the PRs merged to the seat's repo
        since its record was created, one `gh` read per repo, run at the home in the seat's checkout
        — a node's is at the same absolute path (§4.4a); a path that is not a directory here gives no
        reading. A read that failed leaves the last reading: an outage is never zero merges."""
        try:
            seats = [
                r
                for r in records
                if (r.seat or {}).get("trigger") == "prs" and r.supervised and r.unattended and not r.superseded_by
            ]
            where = {r.id: r.repo or r.dir for r in seats}
            dirs = sorted(set(where.values()))
            found = await asyncio.gather(*(asyncio.to_thread(reports.merged_prs, d) for d in dirs))
            merged = dict(zip(dirs, found, strict=True))
            for r in seats:
                got = merged.get(where[r.id])
                if got is None or r.superseded_by:
                    continue  # no reading; or a fill or restart replaced it while `gh` was out
                since = _parse(r.created)
                count = {"prs": sum(1 for at in got if at > since), "at": now_iso()}
                if (r.seat_count or {}).get("prs") != count["prs"]:
                    r.seat_count = count
                    self._save(r)
        except Exception:  # noqa: BLE001 — a detached task: log it, and the next pass tries again
            log.exception("counting the seats' PRs failed")
        finally:
            await self._push_changes()

    @staticmethod
    def _on_a_dialog(s: Session) -> bool:
        """Typing at a session on a permission or a question would answer the dialog rather than
        reach the composer (§4.2) — the rule `send` refuses by."""
        return bool(s.pending and s.pending.kind in ("permission", "question"))

    async def _backup(self, day: str) -> None:
        """The nightly tarball (§4.4a "When the home is lost"): off the loop, and never an error
        anyone but the log hears of."""
        try:
            made = await asyncio.to_thread(backup_store, day)
            if made:
                log.info("backed up the store to %s", made)
        except Exception:  # noqa: BLE001 — a detached task: log, and try again tomorrow
            log.exception("the nightly backup of the store failed")

    def _prune_runs(self, now: datetime, live: set[str], live_ids: set[str] | None = None) -> None:
        """Run-log retention (design §4.6): a log older than `runs_keep_days` goes unless it is in
        `live`, the logs of sessions still running (never truncate a live log: invariant 3). Logs
        of forgotten sessions are the common case — Forget keeps the file until this sweep. `0`
        keeps everything. A session's attachments (`attachments/<session>/`, §4.4 *An attachment's
        life*, TD-469) go by the same bound unless its id is in `live_ids` — any record of it neither
        exited nor closed; a forgotten one has none — each folder removed once empty; `None` sweeps no
        attachment. An attachment's `.part` nothing has written to for an hour goes whatever
        the bound (§4.4 *Attachment drop*, TD-478): a browser closed mid-upload leaves nothing.
        The Add entry form's draft folders go by their claim (`_prune_drafts`, TD-630), before the
        early returns. Runs in a thread: touches files, never `self.sessions`."""
        idle = now.timestamp() - paths.ATTACH_PART_IDLE_S
        for f in paths.attachments_dir().glob("*/*.part"):
            try:
                # an upload's `.part` alone (`<name>.<16 hex>.part`): a finished file a person named
                # `notes.part` is an attachment, kept as any other is
                if paths.UPLOAD_PART.fullmatch(f.name) and f.stat().st_mtime < idle:
                    f.unlink()
                    log.info("pruned attachment upload %s (nothing written for an hour)", f)
            except OSError:
                continue
        keep = hosts.local_host().runs_keep_days
        _prune_drafts(now, keep, live_ids)
        if keep <= 0:
            return
        cutoff = (now - timedelta(days=keep)).timestamp()
        for f in paths.runs_dir().glob("*.log"):
            try:
                if str(f) not in live and f.stat().st_mtime < cutoff:
                    f.unlink()
                    log.info("pruned run log %s (older than %d days)", f.name, keep)
            except OSError:
                continue
        # a promote's log goes with the run logs (§6 *Promote*), unless its run is still in flight
        inflight = {str(r["inflight"].get("log")) for r in self._promotes.values() if r.get("inflight")}
        for f in (paths.home() / "promotes").glob("*/*.log"):
            try:
                if str(f) not in inflight and f.stat().st_mtime < cutoff:
                    f.unlink()
                    log.info("pruned promote log %s (older than %d days)", f, keep)
            except OSError:
                continue
        if live_ids is None:
            return
        for folder in paths.attachments_dir().glob("*"):
            if folder.name in live_ids or folder.is_symlink() or not folder.is_dir():
                continue
            if paths.DRAFT.fullmatch(folder.name):
                continue  # a draft goes by its claim (`_prune_drafts`)
            try:
                files = [f for f in folder.iterdir() if f.is_file() and not f.is_symlink()]
            except OSError:  # gone meanwhile
                continue
            for f in files:
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                        log.info("pruned attachment %s (older than %d days)", f, keep)
                except OSError as e:
                    log.warning("could not prune attachment %s: %s", f, e)
            with contextlib.suppress(OSError):  # not empty: a younger file keeps it
                folder.rmdir()

    async def _clear_gone_kept(self) -> None:
        """A closed record still saying its worktree is kept stops saying so once the directory is gone, such as
        one the person removed by hand (§4.1 *the record*, TD-979): the check asks only `Path.is_dir()`, no git,
        and passes over a reap still running. `_refresh_git` skips closed records and is left so."""
        held = [
            s
            for s in self.sessions.values()
            if s.state == "closed" and s.worktree_kept and not s.worktree_reaping and s.dir
        ]
        if not held:
            return
        gone = await asyncio.to_thread(lambda: {s.id for s in held if not Path(s.dir).is_dir()})  # off the loop
        for s in held:
            if s.id in gone and s.worktree_kept and not s.worktree_reaping:
                s.worktree_kept = None
                self.store.save(s)

    async def _refresh_git(self, now: datetime) -> None:
        due = [
            s
            for s in self.sessions.values()
            if s.dir
            and s.state not in ("closed",)
            and now - self._git_checked.get(s.id, datetime.min.replace(tzinfo=UTC)) > GIT_EVERY
        ]
        if not due:
            return
        results = await asyncio.gather(*(asyncio.to_thread(git_info, s.dir) for s in due), return_exceptions=True)
        infos = {s.id: (r if not isinstance(r, BaseException) else None) for s, r in zip(due, results, strict=True)}
        # the recent files (§4.2 *The record's `files`*, TD-538): read again only when the status's
        # `oid` or its porcelain moved since the last read, or none was read for this record yet
        keys = {sid: (i.oid, i.dirty, tuple(i.files)) for sid, i in infos.items() if i is not None}
        stale = [s for s in due if s.id in keys and keys[s.id] != self._files_read.get(s.id)]
        read = await asyncio.gather(*(asyncio.to_thread(_recent_files, s.dir) for s in stale), return_exceptions=True)
        files = {s.id: r for s, r in zip(stale, read, strict=True) if isinstance(r, list)}
        for s in due:
            live = self.sessions.get(s.id)
            if live is None:
                continue  # forgotten while git ran: no side-table key outlives it (TD-463)
            self._git_checked[s.id] = now
            info = infos.get(s.id)
            new = info.to_dict() if info else None
            changed = new != live.git
            live.git = new
            if s.id in files:  # a read that failed keeps the list it had, and is taken again next time
                self._files_read[s.id] = keys[s.id]
                changed = changed or files[s.id] != live.files
                live.files = files[s.id]
            if changed:
                self.store.save(live)

    async def _derive_reports(self, now: datetime) -> None:
        """A detached task: log a failure, never let it vanish silently, and announce what changed
        (the tick's own push has been and gone by the time this finishes)."""
        try:
            await self._derive_reports_inner(now)
        except Exception:  # noqa: BLE001
            log.exception("deriving reports failed")
        finally:
            await self._push_changes()

    async def _derive_reports_inner(self, now: datetime) -> None:
        """Fill in the report channels the session did not declare (design §4.8, §9 invariant 10):
        its branch, the PRs from it, and the ledger rows those PRs put on main. Every entry is
        marked `derived`, so a declaration stands whatever this finds — the record refuses the
        write, which is why a refusal is not an error. Runs off the branch `_refresh_git` already
        read, on its own slow cadence, and never blocks the tick on a failure.

        What is checked out in a directory is derived only for the record that *holds* that
        directory now (TD-034, `reports.holds_directory`) — a worktree is reused run after run, and
        an exited predecessor sharing the `dir` would otherwise be credited with its successor's
        branch and PRs. Every record keeps the `pending`-by-PR re-check, which is attributed by a PR
        the record itself claimed, so a merge still lands on a worker that has since exited
        (TD-032).

        A branch-only claim the session has moved off is looked up one last time by the branch it
        came from and then *retired* if that branch never grew a PR (TD-045): nothing else could
        ever remove one — the re-check above works by PR number, the upsert has no delete branch,
        and invariant 10 only replaces a derived entry when the session declares the same reference
        — and a permanent false `claimed` is exactly what the idle-with-open-work send fires on."""
        if self.mode == "node" and not self.home_reachable():
            # `progress` and `findings` are the home's (§4.4a, step 4b.2): a claim written to the
            # replica is overwritten on reconnect and was never checked against the siblings' leases.
            return
        holders = reports.holds_directory(self.sessions.values())
        due: list[tuple[Session, str | None, list[tuple[str, int]], list[tuple[str, str | None]]]] = []
        for s in self.sessions.values():
            if not s.dir or s.state == "closed" or not adapters.has_agent(s.adapter):
                continue  # no claim is derived for a record with no agent (§4.3, §4.4 *Repo facts*)
            if now - self._derived_at.get(s.id, datetime.min.replace(tzinfo=UTC)) <= DERIVE_EVERY:
                continue
            branch = (s.git or {}).get("branch") if s.id in holders else None
            pending = [e for e in s.progress if e.source != "declared" and e.status == "claimed" and e.pr]
            # …and a declared claim's `review_pr` (TD-150), re-checked by number, so a merge or a close
            # clears it after the session has moved to its next branch
            reviews = [
                (e.ref, e.review_pr)
                for e in s.progress
                if e.source == "declared" and e.status == "claimed" and e.review_pr and not e.pr
            ]
            # Branch-only claims from a branch this record is no longer on (TD-045). Only for a
            # record that still holds its directory: what is checked out elsewhere says nothing
            # about this one, and an exited worker's claims are its history, not a live question.
            left = (
                [(e.ref, e.branch) for e in s.progress if _is_branch_claim(e) and e.branch != branch]
                if s.id in holders
                else []
            )
            if not branch and not pending and not left and not reviews:
                continue
            due.append((s, branch, [(e.ref, e.pr) for e in pending if e.pr], left, reviews))
        if not due:
            return
        results = await asyncio.gather(
            *(
                # the ledger path the client read from the repo's config at create (design §5
                # `ledger:`), else the default — the record's own, never a re-read of `.shiftlead.yml`
                asyncio.to_thread(
                    reports.derive, s.dir, branch, pend, s.ledger or reports.LEDGER_DEFAULT, left, reviews
                )
                for s, branch, pend, left, reviews in due
            ),
            return_exceptions=True,
        )
        for (s, _branch, _pending, _left, _reviews), result in zip(due, results, strict=True):
            self._derived_at[s.id] = now
            live = self.sessions.get(s.id)
            if live is None:
                continue
            if isinstance(result, BaseException):
                log.warning("deriving reports for %s failed: %s", s.id, result)
                continue
            progress, findings, retire = result
            if self.mode == "node":
                # sent to the home as the derived reports they are; the home's push brings them back
                await self._send_derived(live, progress, findings, retire)
                continue
            # Lists, not generators: these upserts are the write, and `any()` over a generator
            # would stop at the first change and silently drop every later entry (review 2026-09-11).
            applied = [live.report_progress(e) for e in progress] + [live.report_finding(e) for e in findings]
            # a refused derived entry still leaves its PR beside a declared claim (TD-150)
            applied += [live.note_review(e) for e in progress]
            changed = any(applied) | live.retire_branch_claims(retire)
            if changed:
                self.store.save(live)

    async def _refresh_model(self, now: datetime) -> None:
        """The model each live agent session is running (TD-031, design §4.2a). The hook reports it
        at SessionStart and on a `/model` switch; this is the cross-check and the fallback for a
        session that started before the hook carried one — a read of the transcript's tail, in a
        thread, on its own cadence. An adapter that cannot tell leaves the field alone."""
        due = []
        for s in self.sessions.values():
            if not (s.adapter_id and s.dir) or s.state == "closed":
                continue
            if now - self._model_checked.get(s.id, datetime.min.replace(tzinfo=UTC)) <= MODEL_EVERY:
                continue
            try:
                fn = getattr(adapters.get(s.adapter), "model_in_use", None)
            except KeyError:
                fn = None
            if fn:
                due.append((s, fn))
        if not due:
            return
        results = await asyncio.gather(
            *(asyncio.to_thread(fn, str(s.adapter_id), Path(s.dir), s.profile) for s, fn in due),
            return_exceptions=True,
        )
        for (s, _), result in zip(due, results, strict=True):
            self._model_checked[s.id] = now
            live = self.sessions.get(s.id)
            if live is None or isinstance(result, BaseException) or not result:
                continue
            if live.model != result:
                live.model = str(result)
                agent_common.write_model_file(live)  # the commit hook's trailer follows it (§4.2, TD-638)
                self.store.save(live)

    async def _refresh_context(self, now: datetime) -> None:
        """Each unattended record's context reading (design §4.3 `context`, §6 rule 5, TD-190): the
        adapter's read of the transcript's tail, in a thread, once per CONTEXT_EVERY. An attended
        session is a person's, and they can see their own context; an adapter that cannot tell
        leaves the field as it was."""
        every = agent_common.CONTEXT_EVERY
        due = []
        for s in self.sessions.values():
            if not (s.unattended and s.adapter_id and s.dir) or s.state == "closed":
                continue
            if now - self._context_checked.get(s.id, datetime.min.replace(tzinfo=UTC)) <= every:
                continue
            try:
                fn = getattr(adapters.get(s.adapter), "context", None)
            except KeyError:
                fn = None
            if fn:
                due.append((s, fn))
        if not due:
            return
        results = await asyncio.gather(
            *(asyncio.to_thread(fn, str(s.adapter_id), Path(s.dir), s.profile) for s, fn in due),
            return_exceptions=True,
        )
        for (s, _), result in zip(due, results, strict=True):
            self._context_checked[s.id] = now
            live = self.sessions.get(s.id)
            if live is None or not isinstance(result, dict) or not result.get("tokens"):
                continue
            reading = {"tokens": int(result["tokens"]), "at": result.get("at"), "window": result.get("window")}
            if live.context != reading:
                live.context = reading
                self.store.save(live)

    async def _refresh_shells(self, now: datetime, panes: Mapping[str, Any]) -> None:
        """Each idle record's background shell tasks (design §4.2 *A background shell task*, §4.3
        `background`, TD-766): every tick, for each record of this host that is `idle`, attended or
        not, with no live subagent and a pane in `panes` (the tick's list, keyed by the record's id),
        whose adapter has `background` — read off the loop with the pane's pid. `shells` is written
        with `since` kept for a task (`pid`, `start`) seen before, and `shells_at` moves to `now` while
        one is within `SHELL_WAIT`, never back. Any other record, and a read that cannot tell (None),
        keeps its last reading. The record is pushed when its list changes, and saved then, or once a
        `SHELLS_SAVE_EVERY` while only `shells_at` moves."""
        due = []
        for s in self.sessions.values():
            pane = panes.get(s.id)
            if s.state != "idle" or s.host != self.host or pane is None or agent_common.subagents_live(s, now):
                continue
            try:
                fn = getattr(adapters.get(s.adapter), "background", None)
            except KeyError:
                fn = None
            if fn and getattr(pane, "pane_pid", 0) > 1:
                due.append((s, fn, int(pane.pane_pid)))
        if not due:
            return
        results = await asyncio.gather(
            *(asyncio.to_thread(fn, pid, self.proc) for _, fn, pid in due), return_exceptions=True
        )
        changed = False
        at = now.isoformat()
        for (s, _, _), result in zip(due, results, strict=True):
            if isinstance(result, BaseException):
                log.warning("%s: the background-shell read failed: %r", s.id, result)
                continue
            live = self.sessions.get(s.id)
            # read again after the thread: a turn, or a subagent's foreground call, may have begun under it
            if live is None or live.state != "idle" or agent_common.subagents_live(live, now):
                continue
            if not isinstance(result, list):
                continue
            was = {(sh.get("pid"), sh.get("start")): sh.get("since") for sh in live.shells if isinstance(sh, dict)}
            shells = [
                {
                    "pid": t.get("pid"),
                    "start": t.get("start"),
                    "cmd": str(t.get("cmd") or ""),
                    "since": was.get((t.get("pid"), t.get("start"))) or at,
                }
                for t in result
                if isinstance(t, dict)
            ]
            moved = shells != live.shells
            live.shells = shells
            if agent_common.shells_live(live, now) and (not live.shells_at or _parse(live.shells_at) < now):
                live.shells_at, moved_at = at, True
            else:
                moved_at = False
            # `shells_at` moves every tick in memory; on disk once a `SHELLS_SAVE_EVERY` unless the list moved
            last = self._shells_saved.get(s.id)
            if moved or (moved_at and (last is None or now - last >= SHELLS_SAVE_EVERY)):
                self.store.save(live)
                self._shells_saved[s.id] = now
            changed = changed or moved
        if changed:
            await self._push_changes()

    async def _refresh_links(self, now: datetime) -> None:
        """Each live record's printed URLs (design §4.2 *The record's `links`*, §4.3 `links`, TD-543): the
        adapter's read of the transcript from the record's cursor, in a thread, once per LINKS_EVERY,
        attended records too. A URL is kept once at its newest time, newest first, `RECENT_LINKS` of
        them; the cursor starts again at 0 for a new tool session. An adapter without the read, or a
        read that fails, leaves the field as it was."""
        every = agent_common.LINKS_EVERY
        due = []
        for s in self.sessions.values():
            if not (s.adapter_id and s.dir) or s.state == "closed":
                continue
            if now - self._links_checked.get(s.id, datetime.min.replace(tzinfo=UTC)) <= every:
                continue
            try:
                fn = getattr(adapters.get(s.adapter), "links", None)
            except KeyError:
                fn = None
            if fn:
                tool, cursor = self._links_cursor.get(s.id, ("", 0))
                due.append((s, fn, str(s.adapter_id), cursor if tool == s.adapter_id else 0))
        if not due:
            return
        results = await asyncio.gather(
            *(asyncio.to_thread(fn, tool, Path(s.dir), s.profile, cursor=cursor) for s, fn, tool, cursor in due),
            return_exceptions=True,
        )
        for (s, _, tool, _), result in zip(due, results, strict=True):
            self._links_checked[s.id] = now
            live = self.sessions.get(s.id)
            if live is None or not isinstance(result, tuple) or len(result) != 2:
                continue
            found, cursor = result
            self._links_cursor[s.id] = (tool, int(cursor))
            newest: dict[str, str] = {}
            for x in [*live.links, *({"url": k.url, "at": k.at or ""} for k in found)]:
                url, at = str(x.get("url") or ""), str(x.get("at") or "")
                if url and (url not in newest or at > newest[url]):
                    newest[url] = at
            merged = [
                {"url": u, "at": a or None} for u, a in sorted(newest.items(), key=lambda kv: kv[1], reverse=True)
            ][:RECENT_LINKS]
            if merged != live.links:
                live.links = merged
                self.store.save(live)

    async def _refresh_prompts(self, now: datetime) -> None:
        """Each live record's prompts (design §4.2 *The record's `prompts`*, §4.3 `prompts`, TD-976): the
        adapter's read of the transcript from the record's own cursor, in a thread, once per LINKS_EVERY as
        `links` is, attended records too, and on the tick after a hook reported a prompt or the main
        thread's turn end. The merge is `merge_prompts`; a new tool session starts the list and the cursor
        again. An adapter without the read, or a read that fails, leaves the field as it was."""
        every = agent_common.LINKS_EVERY
        due = []
        for s in self.sessions.values():
            if not (s.adapter_id and s.dir) or s.state == "closed":
                continue
            checked = self._prompts_checked.get(s.id, datetime.min.replace(tzinfo=UTC))
            if s.id not in self._prompts_due and now - checked <= every:
                continue
            try:
                fn = getattr(adapters.get(s.adapter), "prompts", None)
            except KeyError:
                fn = None
            if fn:
                tool, cursor = self._prompts_cursor.get(s.id, ("", 0))
                due.append((s, fn, str(s.adapter_id), tool, cursor if tool == s.adapter_id else 0))
        if not due:
            return
        for s, *_ in due:
            self._prompts_due.discard(s.id)
        results = await asyncio.gather(
            *(asyncio.to_thread(fn, aid, Path(s.dir), s.profile, cursor=cursor) for s, fn, aid, _, cursor in due),
            return_exceptions=True,
        )
        for (s, _, aid, tool, cursor), result in zip(due, results, strict=True):
            self._prompts_checked[s.id] = now
            live = self.sessions.get(s.id)
            if live is None or not isinstance(result, tuple) or len(result) != 3:
                continue
            found, leading, after = result
            self._prompts_cursor[s.id] = (aid, int(after))
            held = [] if tool and tool != aid else live.prompts  # a new tool session starts the list again
            # a cursor past the file's end was read from 0: its leading text is no reply to what the record holds
            merged = merge_prompts(held, found, leading, live.sends, from_start=cursor == 0 or after < cursor)
            if merged != live.prompts:
                live.prompts = merged
                self.store.save(live)

    async def _refresh_usage(self) -> None:
        """Ask each account a live agent session's profile names for its usage, once per account
        (§4.2a, TD-122), in a thread, and only on demand (§4.4 *Usage*, TD-233 slice 3): when its
        reading is older than `USAGE_FRESH`, at most once per `USAGE_FRESH`, and not for
        `USAGE_COOL` after a 429. A fetch failure keeps the last answer and never gates anything
        (design §6).
        Then the `limited` rule: an interactive session on a profile at 100% of a window shows
        `limited` with the reset time, and goes back to what it was once the window resets."""
        try:
            await self._refresh_usage_inner()
        except Exception:  # noqa: BLE001 — a detached task: log, never let it vanish silently
            log.exception("usage refresh failed")
        finally:
            await self._push_changes()

    def _usage_live(self) -> list[Session]:
        """The records whose profile has a reading: this host's live tool sessions. The quota poll and
        the spend pass read the same list, or one would drop what the other writes."""
        return [
            s
            for s in self.sessions.values()
            if s.kind == "interactive" and adapters.has_agent(s.adapter) and s.state not in ("exited", "closed")
        ]

    def _usage_remote_live(self) -> list[Session]:
        """The nodes' live tool sessions, as this home holds them: shown on the chip by what they
        report (§4.4 *A node's sessions report to their node*, TD-233 slice 2), never asked for
        here, since the credentials are the node's, and never marked `limited` here, a node-owned
        field."""
        return [
            s
            for recs in self.remote.values()
            for s in recs.values()
            if s.kind == "interactive" and adapters.has_agent(s.adapter) and s.state not in ("exited", "closed")
        ]

    def _usage_theirs(self, here: set[str]) -> list[tuple[Session, str]]:
        """The nodes' live sessions this home shows, each with the account key its node reported it
        under, for the poll and the spread alike. A reading is per profile and the chip per account,
        so one profile carries one account's: a profile a session here runs under (`here`) is this
        host's own, and one two nodes key to two accounts goes to the first by host, never to both,
        or the reading would flip between them on every pass."""
        claimed: dict[str, str] = {}
        out: list[tuple[Session, str]] = []
        for s in sorted(self._usage_remote_live(), key=lambda r: (r.host, r.id)):
            key = self._usage_remote_keys.get((s.host, s.profile))
            if s.profile in here or key is None or claimed.setdefault(s.profile, key) != key:
                continue
            out.append((s, key))
        return out

    async def _refresh_usage_inner(self) -> None:
        live = self._usage_live()
        # A metered profile is never polled (§4.2a): its reading is the spend pass's sum, and the cap
        # rule below skips it by its billing, read before the windows (TD-151)
        metered = {p for _, p in await asyncio.to_thread(_metered_of, {(s.adapter, s.profile) for s in live})}
        mono = time.monotonic()
        # One poll per account, never per profile (§4.2a, TD-122): four profiles split by role on
        # one login asked four times, and the endpoint answered `rate_limited` to all of them.
        groups: dict[str, list[str]] = {}  # account key → the live profiles sharing it
        meta: dict[str, dict[str, str]] = {}  # account key → what the chip names it by
        ask: dict[str, tuple[Any, str]] = {}  # account key → (usage_for, the profile asked through)
        for s in live:
            ad = adapters.get(s.adapter)
            fn = getattr(ad, "usage_for", None)
            if not fn or s.profile in metered:
                continue
            key, account = _usage_key(ad, s.adapter, s.profile)
            profs = groups.setdefault(key, [])
            if s.profile not in profs:
                profs.append(s.profile)
            meta.setdefault(key, {"account": account, "tool": str(getattr(ad, "label", "") or s.adapter)})
            ask.setdefault(key, (fn, s.profile))
        # a node's session is kept and shown while its node reports it, and never asked for here;
        # the key of a node's profile no live session of that node runs under any more is forgotten
        remote_live = {(s.host, s.profile) for s in self._usage_remote_live()}
        for pair in [p for p in self._usage_remote_keys if p not in remote_live]:
            del self._usage_remote_keys[pair]
        for s, key in self._usage_theirs({s.profile for s in live}):
            ad = adapters.get(s.adapter)
            account = key.split(":", 1)[1]
            profs = groups.setdefault(key, [])
            if s.profile not in profs:
                profs.append(s.profile)
            meta.setdefault(key, {"account": account, "tool": str(getattr(ad, "label", "") or s.adapter)})
        for key, profs in groups.items():
            self._usage_seed(key, profs)
        due: dict[str, tuple[Any, str]] = {}
        whole: dict[str, Any] | None = None  # the settings, read once and only for a young reading
        for key, profs in groups.items():
            if key not in ask:
                continue
            wait = self._usage_wait.get(key, agent_common.USAGE_FRESH)
            if mono - self._usage_checked.get(key, -wait) < wait:
                continue
            if not self._usage_young(key):
                due[key] = ask[key]
            elif mono - self._usage_only_at.get(key, float("-inf")) >= agent_common.USAGE_ONLY_EVERY:
                # once an hour for a window only the endpoint gives, by this clock and not the
                # window's `at`, which never moves if the endpoint stops naming it
                whole = settings_mod.load() if whole is None else whole
                if self._usage_only_due(key, profs, whole):
                    self._usage_only_at[key] = mono
                    due[key] = ask[key]
        changed = False
        if due:
            results = await asyncio.gather(
                *(asyncio.to_thread(fn, prof) for fn, prof in due.values()), return_exceptions=True
            )
            for key, r in zip(due, results, strict=True):
                self._usage_checked[key] = mono
                if (merged := self._usage_reading(key, r)) is not None:
                    self._usage_acct[key] = merged
        # every profile sharing an account carries its reading — windows, `fetched`, `reason` alike
        for key, profs in groups.items():
            if (acct := self._usage_acct.get(key)) is None:
                continue
            reading = {**acct, **meta[key]}
            for prof in profs:
                if self._usage.get(prof) != reading:
                    self._usage[prof] = reading
                    changed = True
                    await self._broadcast({"event": "usage", "profile": prof, "usage": reading})
        if changed:
            self.usage_store.save(self._usage)  # once for the batch: the file is whole either way
        # Only profiles a live session is running under are shown (TD-073, Paul 2026-09-19): one
        # account in use is one chip, and last night's profile does not sit in the top bar all day.
        # a node's account is kept while its session lives, shown or not (a profile a session here
        # runs under, or one a second node keys to another account), since the home sends it back
        keyed = {k for (h, p), k in self._usage_remote_keys.items()}
        for key in [k for k in self._usage_acct if k not in groups and k not in keyed]:
            self._usage_acct.pop(key, None)
            self._usage_checked.pop(key, None)
            self._usage_wait.pop(key, None)
            self._usage_only_at.pop(key, None)
        # …and a node's profile, restored from `usage.json` at the start and not keyed since, keeps
        # what it held while a live session of a node runs under it: its first report is merged onto
        # it (`_usage_seed`). Only until then — a profile keyed or dropped once is shown by the rule.
        self._usage_restored -= {p for _, p in self._usage_remote_keys}
        waiting = {s.profile for s in self._usage_remote_live()} & self._usage_restored
        shown = {p for profs in groups.values() for p in profs} | metered | waiting
        if dropped := [p for p in self._usage if p not in shown]:
            for prof in dropped:
                self._usage.pop(prof, None)
                self._usage_restored.discard(prof)
                await self._broadcast({"event": "usage", "profile": prof, "usage": None})
            self.usage_store.save(self._usage)
        self._usage_limits(live, metered)
        await self._push_usage_readings()

    def _usage_limits(self, live: list[Session], metered: set[str]) -> None:
        """The `limited` rule over the readings `_usage` holds (§4.2), for the poll and for a report
        between polls alike (TD-233 slice 2): a session's cap is marked when it is read, not on the
        next poll. A `limited` a modal screen rule set is never lifted: only its screen ends it (§4.3)."""
        for s in live:
            cap = None if s.profile in metered else _cap(self._usage.get(s.profile))
            if cap and s.state not in ("limited", "needs-you"):
                # the tool's own endpoint, not the screen: reported, so `hook` (design §9 invariant 4)
                self._pre_limited[s.id] = s.state
                s.set_state("limited", confidence="hook", pending=Pending(kind="limit", text=cap))
                self.store.save(s)
            elif not cap and s.state == "limited" and s.pending and s.pending.kind == "limit":
                if agent_common.limit_is_modal(s, adapters.get(s.adapter)):
                    continue  # the record's own tail is the authority: a restart forgets nothing
                if s.confidence == "scraped":
                    # a screen rule's `limited` goes back to what the verdict replaced, as `_screen_gone` does
                    saved = self._hook_state.pop(s.id, None)
                    if saved is None or saved[0] != "limited":
                        self._pre_limited.pop(s.id, None)  # no poll's mark comes back with it: spent
                    if saved is None or (saved[2] == "hook" and s.id not in self._last_hook):
                        s.set_state("idle", confidence="scraped")
                    else:
                        s.set_state(saved[0], confidence=saved[2], pending=saved[1])
                else:
                    # back to what it was (idle stays idle: no hook will come to correct a wrong `working`)
                    s.set_state(self._pre_limited.pop(s.id, "working"), confidence="hook")
                self.store.save(s)

    def _usage_only_due(self, key: str, profs: list[str], whole: dict[str, Any]) -> bool:
        """Whether a young reading still wants the endpoint, for a window only it gives (§4.4
        *Usage*, TD-233 slice 2): once per `USAGE_ONLY_EVERY` while the account reports and a
        reserve of a profile on it names the window, or the window stood within ten points of
        its cap."""
        watched = {str(label) for p in profs for label in self._gate_reserves(whole, p) or {}}
        return usage_mod.asked_only_due(
            self._usage_acct.get(key), datetime.now(UTC), agent_common.USAGE_ONLY_EVERY, watched
        )

    async def _usage_spread(self, key: str) -> None:
        """The account's reading copied under every live profile sharing it, pushed and written
        when it moved (the refresh's own step, for a reading a report changed between polls)."""
        acct = self._usage_acct.get(key)
        if acct is None:
            return
        changed = False
        mine = [
            (s, _usage_key(ad, s.adapter, s.profile))
            for s in self._usage_live()
            if getattr(ad := adapters.get(s.adapter), "usage_for", None)
        ]
        theirs = [(s, (k, k.split(":", 1)[1])) for s, k in self._usage_theirs({s.profile for s in self._usage_live()})]
        for s, (k, account) in [*mine, *theirs]:
            if k != key:
                continue
            ad = adapters.get(s.adapter)
            reading = {**acct, "account": account, "tool": str(getattr(ad, "label", "") or s.adapter)}
            if self._usage.get(s.profile) != reading:
                self._usage[s.profile] = reading
                changed = True
                await self._broadcast({"event": "usage", "profile": s.profile, "usage": reading})
        if changed:
            self.usage_store.save(self._usage)

    def _usage_young(self, key: str) -> bool:
        """Whether the account's reading is younger than `USAGE_FRESH` by its own time (§4.4
        *Usage*, TD-233 slice 3): an account whose reading is fresh is not asked, whatever put
        it there. A reading with no readable time is not young, nor is one stamped ahead of the
        clock: a clock that stepped back must not hold the poll off for as long as it is behind
        (`_usage_checked`, seeded at now for such a reading, still waits one period)."""
        try:
            age = (datetime.now(UTC) - _parse(str((self._usage_acct.get(key) or {}).get("fetched")))).total_seconds()
        except (ValueError, TypeError):
            return False
        return 0 <= age < agent_common.USAGE_FRESH

    def _usage_seed(self, key: str, profs: list[str], strict: bool = False) -> None:
        """An account the poll has not met since the agent started takes its reading, and its
        poll's allowance, from the newest reading its profiles hold (TD-087, TD-122): a restart
        keeps the chip and does not ask sooner than `fetched + USAGE_FRESH`. A reading with no
        readable time is polled at once. `strict`, for a node's account: a held reading that
        names no account is not taken, since the profile's name here may be another login's."""
        # only a reading of this account: a node's profile can change hands between two accounts
        account = key.split(":", 1)[-1]
        held = [
            r
            for p in profs
            if isinstance(r := self._usage.get(p), dict)
            and str(r.get("account") or ("" if strict else account)) == account
        ]
        if key not in self._usage_acct and held:
            newest = max(held, key=lambda r: str(r.get("fetched") or ""))
            self._usage_acct[key] = {k: v for k, v in newest.items() if k not in ("account", "tool")}
        first = key not in self._usage_checked
        if first and (seen := [m for r in held if (m := _usage_checked_at(r)) is not None]):
            self._usage_checked[key] = max(seen)
        # …and so does a cool-off (TD-233 slice 3): a promote inside the hour after a 429 does not
        # ask at once because the held reading's `fetched` is old
        if first and key not in self._usage_wait:
            left = [s for r in held if (s := _cool_left(r)) is not None]
            if left and max(left) > 0:
                self._usage_checked[key] = time.monotonic()
                self._usage_wait[key] = max(left)

    def _usage_reading(self, key: str, r: Any) -> dict[str, Any] | None:
        """One poll's answer folded into what this account already had (TD-087, TD-122: `key` is
        the account's, so a backoff holds every profile on it), or None when nothing changed and
        nothing need be said.

        An adapter now answers with a **reason** rather than a silence: `ok` with the windows,
        or `rate_limited` / `no_credentials` / `no_profile` / `error` with none. A reading is
        replaced only by a newer reading — a failure **keeps the last one**, with the reason
        beside it, because *the chip went out* and *the allowance is spent* are different things
        to a person and a five-hour window does not change while we are refused. The backoff is
        set here too: a 429 waits `USAGE_COOL`, or the endpoint's own `Retry-After` when that is
        longer (TD-233 slice 3; the doubling it replaced could not learn a window the endpoint
        never names, TD-231); any other answer, good or bad, goes back to the ordinary cadence,
        since only a 429 is the endpoint telling us to ask less often."""
        if isinstance(r, BaseException) or not isinstance(r, dict):
            r = {"reason": "error"}
        reason = str(r.get("reason") or ("ok" if r.get("windows") is not None else "error"))
        if reason == "rate_limited":
            after = r.get("retry_after")
            # a fixed hour, and the endpoint's own word only where it is longer: it answered with
            # `Retry-After` 0 or none while refusing for six hours (TD-231), so a shorter word is
            # not believed, and a longer one is kept, never capped
            cool = agent_common.USAGE_COOL
            self._usage_wait[key] = max(float(after), cool) if isinstance(after, int | float) else cool
            until = datetime.now(UTC) + timedelta(seconds=self._usage_wait[key])
        else:
            self._usage_wait.pop(key, None)
        was = self._usage_acct.get(key) or {}
        if was.get("reason") != reason:
            # once per change of reason, never per poll: a 429 every five minutes is one line
            log.info("usage for account %s: %s (was %s)", key, reason, was.get("reason") or "no reading yet")
        if reason == "ok":
            # merged with what the account's sessions reported, by the same rule (TD-233 slice 2)
            windows = usage_mod.clean_windows(r.get("windows"))
            fetched = r.get("fetched")
            at = fetched if isinstance(fetched, str) and fetched else now_iso()
            out = usage_mod.merge(was, windows, at=at, source="asked", fresh=True)
            out = {k: v for k, v in out.items() if k not in ("retry_after", "cool_until")} | {"reason": "ok"}
        else:
            out = {**{k: v for k, v in was.items() if k in ("windows", "fetched", "source", "by")}, "reason": reason}
            if isinstance(r.get("retry_after"), int | float):
                out["retry_after"] = r["retry_after"]
            if reason == "rate_limited":
                # when the cool-off ends, held in `usage.json` so a restart keeps it (`_usage_seed`)
                out["cool_until"] = until.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return out if out != was else None

    def _reconcile(self, panes: dict[str, PaneInfo], tails: dict[str, list[str]], snapshot_at: datetime) -> None:
        for sid, event in self.events.drain():
            self._apply_event(sid, event, queued=True)
        now = datetime.now(UTC)
        mono = time.monotonic()
        self._removed = {k: v for k, v in self._removed.items() if mono - v[1] < REMOVED_GUARD_SECONDS}
        for sid, s in list(self.sessions.items()):
            if s.state == "closed":
                if s.closed_at and _parse(s.closed_at) + agent_common.CLOSED_KEEP < now:
                    self._forget(sid)
                continue
            if s.state == "scheduled":
                continue  # no pane yet, by design (§6 *Start time*): the tick's start pass is its judge
            killed = self._killed_at.get(sid)
            if killed is not None and killed < snapshot_at:
                del self._killed_at[sid]  # this snapshot is newer than the kill: the guard is spent
                killed = None
            pane = panes.get(sid)
            if pane is not None and killed is not None:
                # The pane list was taken before the kill that ended this record, so it still lists
                # a tmux session that is gone. Observing it would set `pane` back to True and read a
                # state off the last screen — an `exited` record flipped back to `idle`, which then
                # refuses its own `remove` ("kill it first"). The window is the two `to_thread` hops
                # between the snapshot and here, and an RPC runs on the loop inside them (TD-063,
                # seen on a 3.12 CI runner 2026-09-17).
                continue
            if pane is None:
                # A session created after the pane snapshot was taken is not judged by it.
                if _parse(s.created) + agent_common.CREATE_GRACE < snapshot_at and (s.state != "exited" or s.pane):
                    if s.state != "exited" or s.ended is None:
                        s.ended = self._gone_ending(now)
                    s.set_state("exited", confidence="tick")
                    s.pane = False  # gone for good: killed, or the tmux server restarted (TD-023)
                    self.store.save(s)
                continue
            self._observe(s, pane, tails.get(sid, []), now)
        # tmux sessions with our prefix that we have no record of (created by hand, or the
        # store was lost): adopt them minimally as shells so they appear in the Org. A pane whose
        # create is still starting it is that create's, not a stranger's (TD-952).
        for name, pane in panes.items():
            if name not in self.sessions and name not in self._starting and not self._is_removed_pane(name, pane):
                s = Session(
                    id=name,
                    name=name[len(naming.PREFIX) :],
                    kind="interactive",
                    adapter="shell",
                    dir="",
                    host=self.host,
                )
                s.created = datetime.fromtimestamp(pane.created, UTC).isoformat().replace("+00:00", "Z")
                self.sessions[name] = s
                self._observe(s, pane, tails.get(name, []), now)

    def _gone_ending(self, now: datetime) -> dict[str, Any]:
        """The record's `ended` for a tmux session the tick found gone (§4.2, §4.5 row 5 (b), TD-490):
        when it was found, and — on the agent's first tick after a start, the previous run's last
        tick in `host.json` older than the create grace — since when nobody was looking."""
        found = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        ended: dict[str, Any] = {"how": "gone", "at": found, "found": found}
        prev = self._prev_last_tick
        if not self._ticked and isinstance(prev, str):
            with contextlib.suppress(ValueError):
                if now - _parse(prev) > agent_common.CREATE_GRACE:
                    ended["down_since"] = prev
        return ended

    def _note_tick(self, at: datetime) -> None:
        """`last_tick` in `host.json`, written each tick: the next run's measure of how long nobody
        was looking (§4.5 row 5 (b), TD-490). A failed write is a weaker ending, never a failed tick."""
        self._ticked = True
        self._host_rec["last_tick"] = at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        try:
            self.host_store.save(self._host_rec)
        except OSError:
            log.warning("could not write last_tick to %s", self.host_store.path)

    def _is_removed_pane(self, name: str, pane: PaneInfo) -> bool:
        """Is this the pane a recent `remove` killed (as a stale snapshot would still list it)? A
        pane born after the removed one is a new session and adopts normally (TD-021)."""
        rem = self._removed.get(name)
        if rem is None:
            return False
        created, _ = rem
        # `created` is tmux's `session_created`, whole seconds. Equal means "could be the same
        # pane", so it is skipped: a pane that was created, exited, observed, removed *and* had
        # its name reused inside one second is the only case this delays (until the guard
        # expires), and `None` (the pane was already gone at remove) is treated the same way.
        return created is None or pane.created <= created

    def _observe(self, s: Session, pane: PaneInfo, tail: list[str], now: datetime) -> None:
        adapter = adapters.get(s.adapter)
        s.tail = [_clean(t) for t in tail]
        s.title = _pane_title(adapter, pane.title)
        s.pane = True
        if s.run_log:
            with contextlib.suppress(OSError):
                mtime = datetime.fromtimestamp(Path(s.run_log).stat().st_mtime, UTC)
                s.last_output = mtime.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if pane.dead:
            s.exit_code = pane.dead_status
            if s.state != "exited" or s.ended is None:
                # the tool's own end, when its hook landed first, keeps its words (§4.2, TD-490)
                s.ended = {"how": "pane", "at": now_iso(), "code": pane.dead_status}
            elif s.ended.get("how") == "pane":
                s.ended["code"] = pane.dead_status  # tmux's status lags its dead flag, as `exit_code` does
            if s.state != "exited":
                s.set_state("exited", confidence="tick")
        elif adapter.state_source == "scraped":
            st = adapter.classify(pane, tail)
            if st and st != s.state:
                s.set_state(st, confidence="scraped")
        elif s.id in self._recheck and not s.pendings:
            # a screen rule's `needs-you` the emptied stack restored (§4.2 *Open prompts are a stack*, TD-950):
            # the rules are asked once, whatever the hook's freshness — the stack's own hook just made one fresh
            self._recheck.discard(s.id)
            explain = getattr(adapter, "explain", None)
            if s.state == "needs-you" and s.confidence == "scraped" and explain is not None and explain(s.tail) is None:
                s.set_state("idle", confidence="tick")
        elif (m := self._screen_verdict(s, adapter, now)) is not None:
            # Hook-fed adapter, screen rule fired, no fresher hook state: the labelled fallback
            if s.state == m.state == "limited" and s.confidence == "hook":
                pass  # the poll's `limited` keeps its reset, pending and confidence (§4.3, TD-944)
            elif m.state != s.state or (m.pending and m.pending != s.pending):
                if not self._screen_held(s):  # what the verdict replaces, unless it is a verdict itself
                    self._hook_state[s.id] = (s.state, s.pending, s.confidence)
                s.set_state(m.state, confidence="scraped", pending=m.pending)
        elif self._screen_gone(s, adapter, now):
            # The screen that set this state is gone and no hook has spoken since (TD-306): back to
            # what the last hook said, or `idle` when no hook has reported — not the scraped verdict
            # until the tool's next hook, which on a quiet session may be the next turn
            saved = self._hook_state.pop(s.id, None)
            if saved is None or (saved[2] == "hook" and s.id not in self._last_hook):
                s.set_state("idle", confidence="scraped")  # the launch's assumption is no hook's word
            else:
                s.set_state(saved[0], confidence=saved[2], pending=saved[1])
        elif self._title_verdict(s, adapter, pane, now):
            pass  # the tool's own title replaced the record's state (§4.2 *A title the tool writes its state into*)
        elif s.state == "working" and s.last_output and now - _parse(s.last_output) > STALL_AFTER:
            # Hook-fed adapters: the liveness cross-check applies to `working` alone — a
            # `needs-you` or `idle` session is silent by design.
            s.set_state("stalled?", confidence="tick")
        self.store.save(s)

    def _hook_fresh(self, sid: str, now: datetime) -> bool:
        last = self._last_hook.get(sid)
        return last is not None and now - last <= STALL_AFTER

    def _hook_within(self, s: Session, adapter: Any, now: datetime) -> bool:
        """Whether a hook is fresh enough that the screen yields to it: the stall window, or for a title
        adapter one tick, as `_title_reading` reads it — a working Gemini fires hooks, so the stall
        window would hold its screen rule's verdict off, and a cleared box's, for minutes (§4.3, TD-944)."""
        if not getattr(adapter, "state_in_title", False):
            return self._hook_fresh(s.id, now)
        last = self._last_hook.get(s.id)
        return last is not None and now - last <= timedelta(seconds=agent_common.TICK_SECONDS)

    def _screen_verdict(self, s: Session, adapter: Any, now: datetime) -> Any:
        """The adapter's screen-rule match for the session's tail, or None when there is no rule
        set, nothing matched, or a hook state is fresher (design §4.2: scraped never outranks it).
        A title adapter is asked without its title, so its manifest alone answers (§4.3). Nothing while
        the record's stack is open: it is the one writer of `pending` (§4.2, TD-950)."""
        explain = getattr(adapter, "explain", None)
        if explain is None or s.pendings or self._hook_within(s, adapter, now):
            return None
        return explain(s.tail)

    def _title_verdict(self, s: Session, adapter: Any, pane: PaneInfo, now: datetime) -> bool:
        """Whether the title of a tool that writes its state there replaced the record's state (design
        §4.2 *A title the tool writes its state into*, §4.3 *Two gaps*, TD-785), by `_title_reading`.
        It is not held for its screen: what it replaced is dropped, as a hook's report drops it."""
        if not getattr(adapter, "state_in_title", False) or s.pendings:
            return False  # no title, or the record's stack is open: it alone writes `pending` (§4.2, TD-950)
        m = adapter.explain(s.tail, title=pane.title)
        if m is not None and not m.title:
            return False  # the adapter's manifest matched: a screen rule's verdict, not the title's (§4.3)
        m, _why = self._title_reading(s, m, now)
        if m is None:
            return False
        pending = m.pending
        if m.state == "needs-you":
            # the glyph cannot say which: the tool's shell waits once a turn ran, a confirmation without one
            text = TITLE_SHELL_WAITS if s.state in ("working", "stalled?") else TITLE_CONFIRMATION
            pending = Pending(kind=pending.kind if pending else "question", text=text)
        self._hook_state.pop(s.id, None)
        log.info("%s: title %r: %s -> %s", s.id, pane.title.strip()[:40], s.state, m.state)
        s.set_state(m.state, confidence="title", pending=pending)
        return True

    def _title_reading(self, s: Session, m: Any, now: datetime) -> tuple[Any, str]:
        """The title's verdict `m` if it replaces the record's state, else None, and why (`ao explain`'s
        reason): read once a hook has reached the record and only past one tick since the last hook;
        compared with the record's hook-confirmed state, never `exited` or `closed`, and with
        `stalled?` only by a verdict other than `working`; a verdict equal to the record's state is no
        event, so its `pending` stands and the stall check still runs."""
        if m is None:
            return None, "the title says no state"
        if not s.hook_seen_at:
            return None, f"title {m.state}, but no hook has reached the record — the title is not read yet"
        last = self._last_hook.get(s.id)
        if last is not None and now - last <= timedelta(seconds=agent_common.TICK_SECONDS):
            return None, f"title {m.state}, but a hook reported within a tick — the hook state wins"
        if s.state in ("exited", "closed"):
            return None, f"title {m.state}, but {s.state} stands"
        # a scraped record the title reaches holds no rule's verdict: `explain` asks the manifest first,
        # so its screen is gone and nothing was saved to restore (§4.3, TD-944) — compared as told
        fallback = s.confidence == "scraped" and getattr(m, "title", False)
        if m.state == s.state:
            if fallback:  # the same state, now the tool's own word: `since` and `rev` stand
                return m, f"title {m.state}, as the record reads — taken as the tool's own word (confidence: title)"
            return None, f"title {m.state}, as the record reads — no event"
        if s.state == "stalled?":
            if m.state == "working":
                return None, "title working, which does not end a stall"
        elif not s.told and not fallback:
            return None, f"title {m.state}, but the record's {s.state} is no hook's word — not compared"
        return m, f"title {m.state}, read as the tool's own word (confidence: title)"

    @staticmethod
    def _screen_held(s: Session) -> bool:
        """Whether a hook-fed record's state is a screen rule's verdict: scraped, and not one the
        tick reads without a rule (`exited`, `closed`, `stalled?`)."""
        return s.confidence == "scraped" and s.state not in ("exited", "closed", "stalled?")

    def _screen_gone(self, s: Session, adapter: Any, now: datetime) -> bool:
        """Whether a hook-fed record holds a screen rule's verdict that its screen no longer shows:
        no hook is fresher and no rule matches the tail. An `idle` with nothing saved has nothing to
        restore, so it is not gone: the title (a title adapter's) overrules it instead (§4.3, TD-944)."""
        explain = getattr(adapter, "explain", None)
        if explain is None or s.pendings or not self._screen_held(s) or self._hook_within(s, adapter, now):
            return False
        if s.id not in self._hook_state and s.state == "idle":
            return False
        return explain(s.tail) is None

    def _apply_event(self, sid: str, event: dict[str, Any], queued: bool = False) -> None:
        """A hook-fed state transition (design §4.2 table). Adapters map hook names to these.

        A **queued** event (the hook's call failed and it wrote `events/<session>.jsonl`, drained
        at the tick) carries `at`, when it happened. One stamped before an event that reached the
        record live is older than the state that event set, so its state is skipped; its adapter
        id, model and subagent count still apply (TD-169)."""
        s = self.sessions.get(sid)
        if s is None:
            return
        at = event.get("at") if queued else None  # a queue written before the stamp is applied as it was
        stale = isinstance(at, int | float) and at < self._live_hook_at.get(sid, 0.0)
        aid = event.get("adapter_id")
        if aid and s.adapter_id and aid != s.adapter_id and event.get("state") in ("exited", "closed"):
            # The end of a run this record no longer holds (TD-186): a restart closed the old run and
            # created this one under the same id, and the old run's SessionEnd landed after it. It is
            # not this run's exit, and its tool id is not this run's — applied, it marked a live run
            # `exited` and made its own tool session read as *outside shiftlead* to the anchor rule.
            log.info("%s: ignored the end of a previous run (%s; this run is %s)", sid, aid, s.adapter_id)
            return
        killed_run = self._killed_run_at.get(sid)
        taken = s.state not in ("exited", "closed")  # a new run holds the id
        if killed_run is not None and (
            time.monotonic() - killed_run >= KILLED_END_GRACE or (not taken and event.get("state") == "exited")
        ):
            self._killed_run_at.pop(sid, None)  # past the grace, or the killed run's end came before any resume
            killed_run = None
        if killed_run is not None and taken and not queued and event.get("state") == "exited":
            # The end of the run a `kill` ended, landing after a resume took the id (TD-822): Claude
            # Code runs its SessionEnd on the kill's hangup, and a resume keeps the tool's session id,
            # so the check above cannot tell the runs apart. Dropped once; a new run that really
            # ends inside the grace is still read `exited` by the tick, from its pane.
            self._killed_run_at.pop(sid, None)
            log.info("%s: ignored the killed run's own end, after a new run took the id", sid)
            return
        if s.state == "closed":
            # Closed is final (§4.2 *Close*: the card kept a day, then forgotten). `ao close` kills
            # the pane, and the tool's own SessionEnd for the run it killed lands after it: applied,
            # it read `exited`, offered Forget, and the reconcile's day-long keep — which reads only
            # `closed` — never forgot the record (TD-200 (3)). Whatever a closed run still says is
            # the dying run's.
            log.info("%s: ignored %s on a closed record", sid, event.get("event") or event.get("state") or "a hook")
            return
        if not queued:
            self._live_hook_at[sid] = time.time()
        self._last_hook[sid] = datetime.now(UTC)  # apply time, also for events drained from the offline queue
        s.hook_seen_at = s.hook_seen_at or now_iso()  # the first hook, kept across restarts (§4.1, TD-720)
        if aid:
            s.adapter_id = aid
        if (path := event.get("transcript")) and isinstance(path, str):
            s.transcript = path  # the tool's file for this run, pushed with the id (§4.2, TD-578)
        if (model := event.get("model")) and str(model) != s.model:
            s.model = str(model)  # SessionStart's `model`, or a `/model` switch (TD-031)
            agent_common.write_model_file(s)  # the commit hook's trailer follows it (§4.2, TD-638)
        running = s.subagents
        self._apply_subagents(s, event, at)
        if (stopped := event.get("subagent_stopped")) and isinstance(stopped, str):
            # a `TaskStop` of a subagent (TD-1277): its waiter and entries end, listed or not — an agent
            # counted with no id may still wait under its own — before the `queued` gate and whatever the
            # event's age, and before the zero branch below, so this end is the session's last sure one
            self._end_waiters(sid, None, stopped, None)
            self._end_entries(s, lambda p: p.subagent == stopped, sure=True)
        if not queued:
            self._track_call(sid, event)  # a replayed event touches no list: no waiter outlived the outage
        if event.get("prompt") or (event.get("state") == "idle" and not event.get("subagent")):
            self._prompts_due.add(sid)  # the prompts read on the next tick, not a minute later (§4.2, TD-976)
        if event.get("prompt") and not stale and (s.first_prompt or s.first_prompt_error):
            # a prompt went in (the tool's UserPromptSubmit, §4.1 *No prose in the argv*): the brief
            # typed by the tick, or a person's or a manager's send that cures *brief not sent*
            s.first_prompt_sent_at = s.first_prompt_sent_at or now_iso()
            s.first_prompt, s.first_prompt_error = None, None
        if not stale:
            self._bell_answered(s, event)  # a ring's turn, judged at its Stop (§4.10, TD-347)
        state = None if stale else event.get("state")
        thread = event.get("subagent") or None
        starting = thread is not None and (event.get("subagent_delta") or 0) > 0  # a `SubagentStart` ends nothing
        if thread is None and state and state not in ("needs-you", "exited", "closed") and s.pendings:
            # the main thread's own state goes beneath the open prompts, before any of them ends (§4.2
            # *Open prompts are a stack*): the emptied stack restores it, and a `Stop` is not lost
            self._keep_beneath(s, state)
        if state in ("exited", "closed"):
            self._end_waiters(sid, every=True)  # the session's end ends every thread's waiter
        elif event.get("subagents_reset") or (running and not s.subagents):
            self._end_waiters(sid, every=True, subagents=True)  # no subagent is left to ask
            self._end_entries(s, lambda p: p.subagent is not None, sure=False)  # nor to answer in the pane
        pending_kind = (event.get("pending") or {}).get("kind")
        if stale or event.get("notice") or starting:
            pass  # a notice announces the dialog its waiter is for: the notice rule below weighs it (§4.2)
        elif thread is not None or (state and state != "needs-you") or pending_kind == "question":
            self._end_waiters(
                sid, event.get("tool_use_id"), thread, event.get("call"), question=pending_kind == "question"
            )
        # a question in the pane (a fall-through, a question) has no waiter: any event of its thread means it
        # was answered — the main thread's only once no waiter of its own is live (§4.2)
        if (
            not stale
            and not starting
            and (thread is not None or (state and state != "needs-you" and not self._permission_waiting(sid, None)))
        ):
            tid = event.get("tool_use_id")
            # a tool with no permission channel answers its permission in the terminal: no waiter ends it,
            # so it leaves as a question does (§4.3 *Permissions: no channel*, TD-786)
            terminal = not adapters.permission_channel(s.adapter)
            self._end_entries(
                s,
                lambda p: p.subagent == thread and (p.kind != "permission" or terminal),
                sure=not tid or None,
                tool_use_id=tid,
            )
        if state == "needs-you":
            pending = Pending.from_dict(event["pending"]) if event.get("pending") else Pending("question", "")
            if thread is not None:
                pending.subagent = thread
            if not (event.get("notice") and self._notice_dropped(s)):
                self._push_prompt(s, pending)
        elif state:
            pending = Pending.from_dict(event["pending"]) if event.get("pending") else None
            if s.pendings and state not in ("exited", "closed"):
                pass  # written into `kept` above: the stack is the one writer of `pending` while it is open
            else:
                if state == "working" and s.state == "idle" and s.told and event.get("event"):
                    # An event that is not a turn's start woke a session its Stop left idle: the
                    # capture TD-201 asks for, since the one that did it once is not yet named.
                    log.info("%s: %s turned a hook-confirmed idle session working", sid, event["event"])
                if state == "exited" and s.state != "exited":
                    # the tool's own end (§4.2 the `SessionEnd` row, TD-490): its `reason`, and its
                    # code when the event carries one
                    s.ended = {"how": "tool", "at": now_iso()}
                    for k in ("reason", "code"):
                        if event.get(k) not in (None, ""):
                            s.ended[k] = event[k]
                s.set_state(state, confidence="hook", pending=pending)
                self._hook_state.pop(sid, None)  # a hook's word: no screen's verdict to go back from
        self.store.save(s)

    def _push_prompt(self, s: Session, entry: Pending) -> None:
        """An open prompt goes on top of the record's stack (design §4.2 *Open prompts are a stack*, TD-950).
        The first one keeps what the record read as `kept` — a screen or title road's `needs-you` too —
        and takes over the screen road's saved state, so nothing restores an older state later. A
        main-thread question replaces an older main-thread question, as it replaced the one pending."""
        if not s.pendings:
            s.kept = {
                "state": s.state,
                "pending": s.pending.to_dict() if s.pending else None,
                "confidence": s.confidence,
                "since": s.since,
            }
            self._hook_state.pop(s.id, None)
            self._recheck.discard(s.id)
        elif entry.subagent is None and entry.kind != "permission":
            s.pendings = [p for p in s.pendings if p.subagent is not None or p.kind == "permission"]
        s.pendings.append(entry)
        s.set_state("needs-you", confidence="hook", pending=entry)

    def _end_entries(self, s: Session, which: Any, *, sure: Any = None, tool_use_id: Any = None) -> bool:
        """The open prompts `which` picks leave the stack, wherever they sit, and the record shows what is
        left: the newest entry, or once none is, `kept` with its own confidence and `since` (§4.2). `sure`
        sets the session's last sure end (True) or clears it (False) — None: sure when an entry ended is the
        call `tool_use_id` names, cleared otherwise. True when an entry ended."""
        ended = [p for p in s.pendings if which(p)]
        if not ended:
            return False
        if sure is None:
            sure = any(p.tool_use_id == tool_use_id for p in ended)
        if sure:
            self._sure_end[s.id] = time.monotonic()
        else:
            self._sure_end.pop(s.id, None)
        s.pendings = [p for p in s.pendings if not which(p)]
        self._show_top(s)
        return True

    def _show_top(self, s: Session) -> None:
        """The record reads the newest open prompt, or with none left goes back to `kept`. A `kept` screen
        rule's `needs-you` comes back `scraped` and is rechecked by the next tick (§4.2)."""
        if s.pendings:
            s.set_state("needs-you", confidence="hook", pending=s.pendings[-1])
            return
        kept = s.kept or {"state": "idle", "pending": None, "confidence": "tick", "since": None}
        s.kept = None
        pending = Pending.from_dict(kept["pending"]) if kept.get("pending") else None
        s.set_state(kept["state"], confidence=kept["confidence"], pending=pending, since=kept.get("since"))
        if kept["state"] == "needs-you" and kept["confidence"] == "scraped":
            self._recheck.add(s.id)

    @staticmethod
    def _keep_beneath(s: Session, state: Any, confidence: Any = "hook") -> None:
        """The main thread's own state written beneath the open prompts: a fresh `since` where it changed,
        `kept`'s own where it did not (§4.2 *Open prompts are a stack*)."""
        kept = s.kept or {}
        since = kept.get("since") if kept.get("state") == state and kept.get("since") else now_iso()
        s.kept = {"state": state, "pending": None, "confidence": confidence, "since": since}

    @staticmethod
    def _sweep_prompts(s: Session) -> bool:
        """At the host agent's start (design §4.2 *A waiter does not outlive the host agent*, TD-950): a hook
        `pending` saved with no `pendings` (an older version's) moves into the stack, over `kept` `idle` at
        `tick` with its own `since`; then every permission entry, its waiter gone with the last run, takes
        the question form — the hook's call failed, so the tool drew its dialog. True when it changed."""
        if s.state in ("exited", "closed"):
            return False
        changed = False
        if not s.pendings and s.pending is not None and s.state == "needs-you" and s.confidence == "hook":
            s.pendings = [s.pending]
            s.kept = {"state": "idle", "pending": None, "confidence": "tick", "since": s.since}
            changed = True
        for i, p in enumerate(s.pendings):
            if p.kind == "permission":
                s.pendings[i] = Pending(
                    kind="question",
                    text=p.text,
                    tool_use_id=p.tool_use_id,
                    subagent=p.subagent,
                    subagent_name=p.subagent_name,
                )
                changed = True
        if changed and s.pendings:
            s.set_state("needs-you", confidence="hook", pending=s.pendings[-1])
        return changed

    def _notice_dropped(self, s: Session) -> bool:
        """Whether the tool's `permission_prompt` notice announces a prompt the stack already holds: one
        is open (a permission, or a question that fell through from one), or one had a sure end within
        `NOTICE_LAG` — the notice lands about six seconds after the dialog (§4.2)."""
        if any(p.kind == "permission" or (p.kind == "question" and p.tool_use_id) for p in s.pendings):
            return True
        at = self._sure_end.get(s.id)
        return at is not None and time.monotonic() - at < agent_common.NOTICE_LAG

    @staticmethod
    def _apply_subagents(s: Session, event: dict[str, Any], at: Any) -> None:
        """The subagent count and its time (design §4.2 *Working on its own*, TD-734). An event the
        adapter marked `subagent_seen` sets `subagent_at` to the later of the record's and its own
        time — a queued event's `at`, else now — so a drained event never moves it back; a
        `subagents_reset` older than the record's `subagent_at` is a stale start, and is not applied. A
        `SubagentStop` for an id no `SubagentStart` announced — the tool's own, about thirty seconds into
        a subagent's permission — moves no count, so it never reads as the last subagent's end (TD-960). A
        `subagent_stopped` (a `TaskStop` of it, TD-1277) counts down only an id the record lists."""
        when = datetime.fromtimestamp(at, UTC) if isinstance(at, int | float) else datetime.now(UTC)
        try:
            last = _parse(s.subagent_at) if s.subagent_at else None
        except ValueError:
            last = None
        if event.get("subagents_reset") and (last is None or when >= last):
            s.subagents, s.subagent_at, last = 0, None, None
            s.subagent_ids = []
        if delta := event.get("subagent_delta"):
            sub = event.get("subagent")
            if not isinstance(sub, str) or not sub:
                s.subagents = max(0, s.subagents + int(delta))  # an adapter with no per-subagent id
            elif int(delta) > 0:
                if sub not in s.subagent_ids:
                    s.subagent_ids.append(sub)
                    s.subagents += 1
            elif sub in s.subagent_ids:
                s.subagent_ids.remove(sub)
                s.subagents = max(0, s.subagents - 1)
            elif s.subagents > len(s.subagent_ids):
                s.subagents -= 1  # a start with no id, or counted by an older build
        if (stopped := event.get("subagent_stopped")) and isinstance(stopped, str) and stopped in s.subagent_ids:
            s.subagent_ids.remove(stopped)
            s.subagents = max(0, s.subagents - 1)
        if event.get("subagent_seen") and (last is None or when > last):
            s.subagent_at = when.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _permission_waiting(self, sid: str, thread: Any = ANY_THREAD) -> bool:
        """Whether a waiter of the session is live: of any thread, or of the one named (a subagent's
        id, or None for the main thread)."""
        return any(
            k[0] == sid and not f.done() and (thread is ANY_THREAD or t == thread)
            for k, (f, t) in self._waiters.items()
        )

    def _end_waiters(
        self,
        sid: str,
        tool_use_id: Any = None,
        subagent: str | None = None,
        call: Any = None,
        *,
        question: bool = False,
        every: bool = False,
        subagents: bool = False,
    ) -> None:
        """A later hook event of a session whose permission is still waiting was answered in the
        terminal (design §4.2, TD-629, TD-950): the tool has moved past the dialog, and the waiter left
        live timed out ten minutes later into a false *needs you*. **The thread scopes it**: a waiter
        is ended only by an event of its own thread — a subagent's by an event carrying the same
        `subagent`, a main thread's by one carrying none. Within it, a tool event names its call, so
        it ends that call's waiter and not another's — a parallel call's event says nothing about
        this one; an event with no call (a turn's end, a prompt, a `SubagentStop`) ends every waiter
        of the thread, and so does any event for a waiter whose permission matched no call
        (`_await_permission` keyed it `<session>:<time>`). A main-thread waiter keyed by its call is
        also ended by any main-thread `call: start` or question: its dialog is drawn, and a pane Deny
        gives the asked call no end, so the turn's next call is the first sign. `every` ends the
        session's waiters whatever the event (its end), or with `subagents` every subagent's.

        An ended waiter's entry leaves the record's stack here, before the hook call returns (§4.2 *Open
        prompts are a stack*): an end by the asked call's own event or by one naming no call is sure."""
        ended: dict[str, bool] = {}
        for (k_sid, k_tid), (fut, k_thread) in list(self._waiters.items()):
            if k_sid != sid or fut.done():
                continue
            if every:
                if not subagents or k_thread is not None:
                    fut.set_result({"terminal": True})
                    ended[k_tid] = True
                continue
            if k_thread != subagent:
                continue
            if (
                tool_use_id is None
                or k_tid == tool_use_id
                or k_tid.startswith(f"{sid}:")
                or (subagent is None and (call == "start" or question))
            ):
                fut.set_result({"terminal": True})
                ended[k_tid] = tool_use_id is None or k_tid == tool_use_id
        if ended and (s := self.sessions.get(sid)) is not None:
            self._end_entries(s, lambda p: p.kind == "permission" and p.tool_use_id in ended, sure=any(ended.values()))

    def _track_call(self, sid: str, event: dict[str, Any]) -> None:
        """Each thread's open calls, what `_await_permission` matches a permission to (design §4.2 *A
        waiter is keyed by its call*, TD-950): a `call: start` with its `call_sig` joins its thread's
        list, its own `call: end` leaves it. A thread's list goes at its `SubagentStop` or a `TaskStop` of
        it (TD-1277), every subagent's at a `subagents_reset`, and the session's at its end."""
        threads = self._open_calls.get(sid)
        if event.get("state") in ("exited", "closed"):
            self._open_calls.pop(sid, None)
            return
        thread = event.get("subagent") or None
        if threads is not None:
            if event.get("subagents_reset"):
                for k in [k for k in threads if k is not None]:
                    del threads[k]
            if thread is not None and (event.get("subagent_delta") or 0) < 0:
                threads.pop(thread, None)
            if (stopped := event.get("subagent_stopped")) and isinstance(stopped, str):
                threads.pop(stopped, None)
        tid, edge = event.get("tool_use_id"), event.get("call")
        if not isinstance(tid, str) or not tid:
            return
        if edge == "start" and (sig := event.get("call_sig")):
            threads = self._open_calls.setdefault(sid, {})
            calls = threads.pop(thread, [])  # re-inserted: the thread heard from last is the newest
            calls = [c for c in calls if c[0] != tid] + [(tid, str(sig))]
            threads[thread] = calls[-OPEN_CALLS:]
            while len(threads) > OPEN_THREADS:
                del threads[next(iter(threads))]
        elif edge == "end" and threads is not None and (calls := threads.get(thread)):
            threads[thread] = [c for c in calls if c[0] != tid]

    def _take_call(self, sid: str, subagent: str | None, sig: Any) -> str | None:
        """The oldest open call of the thread with the permission's `call_sig`, consumed: its
        `tool_use_id` keys the waiter, and two parallel calls of one signature are matched in order."""
        calls = (self._open_calls.get(sid) or {}).get(subagent)
        if not sig or not calls:
            return None
        for i, (tid, s) in enumerate(calls):
            if s == sig:
                del calls[i]
                return tid
        return None

    def _scrub(self, sid: str) -> None:
        """No cadence or hook key outlives the session it was about — whether the record is
        forgotten or replaced in place by a new session of the same name (§4.1)."""
        for side in (
            self._git_checked,
            self._files_read,
            self._derived_at,
            self._model_checked,
            self._context_checked,
            self._links_checked,
            self._links_cursor,
            self._prompts_checked,
            self._prompts_cursor,
            self._pre_limited,
            self._last_hook,
            self._hook_state,
            self._live_hook_at,
            self._open_calls,
            self._sure_end,
            self._killed_at,
            self._mail_hints,
            self._asks_hints,
            self._bells,
            self._rang,  # a ring's count and the run of unread rings (TD-347): a reused id starts at none
            self._unread_rings,
        ):
            side.pop(sid, None)
        self._lead_typed.discard(sid)  # a reused id never starts with the old run's line in the composer (TD-347)
        self._recheck.discard(sid)
        self._prompts_due.discard(sid)
        if not (lock := self._typing.get(sid)) or not lock.locked():
            self._typing.pop(sid, None)  # a held one stays: its typist is mid-paste, the name reused or not
        for key in [k for k in self._attention_how if k.split("|", 1)[0] == sid]:
            del self._attention_how[key]
        for key in [k for k in self._attention if k.split("|", 1)[0] == sid]:
            del self._attention[key]  # belt and braces: `_attention_gone` wrote these out already

    def _write_launch(self, address: str, s: Session, params: dict[str, Any]) -> None:
        """The launch record of a supervised create (design §6 *Keeping a team running*): what the
        create was handed — adapter, profile, the prompt as handed, lane, name, directory, worktree,
        role, badges — with the record's own `controllers` (the creator added), written at the home
        as `launch/<address>.json`, which a restart replays rather than re-reading any definition.
        Written at every such create, so a resume with changes leaves the person's latest choices;
        owner-only, since it holds the brief. A failure to write is logged, never the create's."""
        record = {**params, "controllers": list(s.controllers), "supervised": True, "id": address, "at": now_iso()}
        path = paths.launch_dir() / f"{address}.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.parent.chmod(0o700)  # as the launch scripts beside it have it (tmux.py)
            tmp = path.with_suffix(".json.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # owner-only from the start
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=1)
            tmp.replace(path)
        except OSError as e:
            log.warning("%s: could not write its launch record: %s", address, e)

    @staticmethod
    def _drop_launch(address: str) -> None:
        with contextlib.suppress(OSError):
            (paths.launch_dir() / f"{address}.json").unlink(missing_ok=True)

    def _drop_context(self, conversation: str | None, gone: Session) -> None:
        """A conversation's start-context file, once no record but `gone` holds it (§4.1 *No prose in
        the argv*, TD-339): on Forget, and when a create replaces a record in place with another
        conversation. A record still holding it would hand it again on a Resume."""
        if not conversation or any(r.adapter_id == conversation for r in self.sessions.values() if r is not gone):
            return
        with contextlib.suppress(OSError, ValueError):
            paths.context_file(conversation).unlink(missing_ok=True)

    def _forget(self, sid: str) -> None:
        gone = self.sessions.get(sid)
        if gone is None:
            return  # already forgotten (two removes of one id in flight): nothing more to announce
        self._drop_launch(sid)  # the launch record goes with the record on Forget (§6)
        self._drop_context(gone.adapter_id, gone)
        # Its open `ask`s expire with it (design §4.10 lifecycle): the record and its inbox go, and
        # every other holder of those asks — the askers — is told so. Done while it is still in the
        # map so `_mark` reaches it, harmlessly, along with the rest. A `steer` is the exception:
        # its bound runs whatever becomes of the addressee, so the sender's copy lapses on time.
        for e in [e for e in gone.inbox if e.open and e.kind != "steer"]:
            self._close_entry(e.id, "expired", now_iso())
        self._asker_gone(gone, self._address(gone), how="forgotten")
        self._attention_gone(gone, "forgotten")
        self.sessions.pop(sid, None)
        self.store.delete(sid)
        # Scrub the id from every subscriber's map and queue the one `gone`: whichever
        # `_push_changes` runs next (the caller's or a tick's) announces it exactly once.
        for last in self._subscribers.values():
            last.pop(sid, None)
        self._scrub(sid)
        self._killed_run_at.pop(sid, None)  # kept past `_scrub` for a resume (TD-822), not past a forget
        self._gone.append(sid)


# The home's doorbell (design §4.10): typed with no `sends` entry, it would read as the person's prompt.
_DOORBELL = re.compile(re.escape(mail.unread_line(0)).replace("0", r"\d+") + r"\Z")
BRIEF_SEND = "(the brief)"  # the `system` entry the brief's send leaves in `sends` (agent_wake)
BRIEF_NEAR = timedelta(minutes=1)  # how near a brief sent without its lead line names its prompt


def _first(text: str) -> str:
    return next((x.strip() for x in text[:300].splitlines() if x.strip()), "")


def _when(iso: Any) -> datetime | None:
    try:
        return _parse(str(iso)) if iso else None
    except ValueError:
        return None


def merge_prompts(
    held: list[dict[str, Any]], found: list[Any], leading: str | None, sends: list[Any], *, from_start: bool
) -> list[dict[str, Any]]:
    """A record's `prompts` after one read (design §4.2 *The record's `prompts`*, TD-976): `held` newest
    first, `found` the read's `Prompt`s oldest first, `leading` the read's first reply before any prompt.

    An entry already held is matched by `at` and `text`: it keeps its `from` and takes a reply while it has
    none, so a reread from 0 changes nothing; the leading reply fills the newest entry only on a read from a
    cursor past 0. A new entry's `from` comes from `sends`, each matched to one prompt at most — the held
    entries are matched again first, oldest first, so a send is never given twice: a prompt opening with
    the brief's lead line is the brief, consuming the *(the brief)* entry; an unconsumed *(the brief)* entry
    names the earliest prompt within a minute of it; else the oldest unconsumed send made before it with the
    same first line; else the person. The doorbell is left out, and the newest `RECENT_PROMPTS` kept."""
    out = [dict(x) for x in held]
    if leading and not from_start and out and not out[0].get("reply"):
        out[0]["reply"] = leading
    keys = {(x.get("at"), x.get("text")): x for x in out}
    briefs = [e for e in sends if e.from_ == SYSTEM and e.text == BRIEF_SEND]
    others = [e for e in sends if not (e.from_ == SYSTEM and e.text == BRIEF_SEND)]
    used: set[str] = set()
    if len(out) >= RECENT_PROMPTS and (floor := _when(out[-1].get("at"))):
        used |= {e.id for e in sends if (_when(e.at) or floor) < floor}  # their prompts left the list

    def take(sender: str, first: str, at: datetime | None) -> str | None:
        for e in others:
            if e.id in used or (sender and e.from_ != sender) or _first(e.text) != first:
                continue
            if at is not None and (made := _when(e.at)) is not None and made > at:
                continue
            used.add(e.id)
            return e.from_
        return None

    def take_brief(at: datetime | None, lead: bool) -> bool:
        for e in briefs:
            near = at is not None and (made := _when(e.at)) is not None and abs(made - at) <= BRIEF_NEAR
            if e.id not in used and (lead or near):
                used.add(e.id)
                return True
        return False

    for x in reversed(out):  # the held entries consume their sends again, oldest first
        at = _when(x.get("at"))
        if x.get("from") == "brief":
            take_brief(at, lead=str(x.get("text") or "").startswith(mail.BRIEF_LINE))
        elif x.get("from") not in (PERSON, None):
            take(str(x["from"]), _first(str(x.get("text") or "")), at)
    for p in found:
        first = _first(p.text)
        if _DOORBELL.match(first):
            continue
        same = keys.get((p.at, p.text))
        if same is not None:
            if p.reply and not same.get("reply"):
                same["reply"] = p.reply
            continue
        at = _when(p.at)
        if p.text.startswith(mail.BRIEF_LINE):
            take_brief(at, lead=True)
            sender = "brief"
        elif take_brief(at, lead=False):
            sender = "brief"
        else:
            sender = take("", first, at) or PERSON
        entry = {"at": p.at, "text": p.text, "drawn": p.drawn, "whole": p.whole, "reply": p.reply, "from": sender}
        keys[(p.at, p.text)] = entry
        out.insert(0, entry)
    out.sort(key=lambda x: _when(x.get("at")) or datetime.min.replace(tzinfo=UTC), reverse=True)
    return out[:RECENT_PROMPTS]


def _prune_drafts(now: datetime, keep: int, live_ids: set[str] | None) -> None:
    """The Add entry form's draft folders (design §4.6 *Run-log retention*, §4.4 *The Add entry form's
    draft*, TD-630), by their `claimed.json`: one with none is removed once nothing in it was written
    for `ATTACH_PART_IDLE_S`, whatever `keep`; one claimed by a hand (`by: hand:<ask id>`) is removed
    `keep` days after its `at`, and kept under `0`; one claimed by a session lives as that session's
    own folder does — kept while its id is in `live_ids` (`None`: nothing is known, so kept), its
    files then going by age and the folder, claim and all, once nothing else is left. A claim that
    cannot be read is kept: the person's files are the safe direction."""
    idle = now.timestamp() - paths.ATTACH_PART_IDLE_S
    cutoff = (now - timedelta(days=keep)).timestamp()
    for folder in paths.attachments_dir().glob("draft-*"):
        if not paths.DRAFT.fullmatch(folder.name) or folder.is_symlink() or not folder.is_dir():
            continue
        try:
            claim = agent_common.read_draft_claim(folder)
            if claim is None:
                last = max([folder.lstat().st_mtime, *(f.lstat().st_mtime for f in folder.iterdir())])
                if last < idle:
                    shutil.rmtree(folder)
                    log.info("pruned draft %s (unclaimed, nothing written for an hour)", folder.name)
                continue
            by = str(claim.get("by") or "")
            if by.startswith("hand:"):
                try:
                    at = datetime.fromisoformat(str(claim.get("at"))).timestamp()
                except ValueError:
                    continue
                if keep > 0 and at < cutoff:
                    shutil.rmtree(folder)
                    log.info("pruned draft %s (handed as %s, older than %d days)", folder.name, by[5:], keep)
                continue
            if not by or live_ids is None or by in live_ids or keep <= 0:
                continue
            files = [f for f in folder.iterdir() if f.name != paths.DRAFT_CLAIM]
            for f in files:
                if f.is_file() and not f.is_symlink() and f.lstat().st_mtime < cutoff:
                    f.unlink()
                    log.info("pruned attachment %s (older than %d days)", f, keep)
            if not any(f.name != paths.DRAFT_CLAIM for f in folder.iterdir()):
                (folder / paths.DRAFT_CLAIM).unlink(missing_ok=True)
                folder.rmdir()
        except OSError as e:  # gone meanwhile, or not ours to remove: the next sweep tries again
            log.warning("could not prune draft %s: %s", folder, e)


def _recent_files(directory: str) -> list[dict[str, Any]] | None:
    """A record's recent files (§4.2 *The record's `files`*, TD-538): what the work in `directory` changed
    against `merge-base HEAD origin/<default>` by the cadence's default-branch rule — the tree alone with
    no origin — or None when a read failed. Blocking: a thread's."""
    return changed_files(directory, ledger_mod.default_ref(directory, timeout=5.0), RECENT_FILES)


def _span(seconds: float) -> str:
    """An age as a person reads it: *40m*, *6h*, *2d*."""
    m = int(seconds // 60)
    if m < 120:
        return f"{m}m"
    return f"{m // 60}h" if m < 48 * 60 else f"{m // 1440}d"


def _lines(crossed: Any) -> list[tuple[Any, Any]]:
    """A balance crossing's lines and limits, without the numbers that move with the clock."""
    return [(c.get("line"), c.get("limit")) for c in crossed or [] if isinstance(c, dict)]


def _balance_hold(held: Any) -> dict[str, Any] | None:
    """The balance hold a standing `held` carries (§6 rule 8's fifth bound): the hold itself, or the one
    kept beside another bound that displaced it (`_work_held`); None when it carries none."""
    if not isinstance(held, dict):
        return None
    if held.get("why") == "balance":
        return held
    inner = held.get("balance")
    return inner if isinstance(inner, dict) and inner.get("why") == "balance" else None
