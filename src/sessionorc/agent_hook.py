"""The hook's entry and the permission it waits on (TD-317 slice 2, TD-108's design): `rpc_hook`, which an
adapter's hook script calls, `_await_permission`, the blocking wait on a permission event, and `rpc_decide`,
which answers it — design §4.3 and §4.8. A mixin `HostAgent` inherits; moved from `agent_wake.py` as written,
and the state it reads is the agent's.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sessionorc import (
    adapters,
    agent_common,
    link,
    mail,
    permits,
)
from sessionorc import settings as settings_mod
from sessionorc.agent_common import (
    RpcError,
)
from sessionorc.models import (
    PERSON,
    SYSTEM,
    MailEntry,
    Pending,
    now_iso,
)

log = logging.getLogger(__name__)


class HookMixin:
    async def rpc_hook(self, session: str, **event: Any) -> dict[str, Any] | None:
        """Called by an adapter's hook script. A `permission` event blocks until answered or timed out."""
        if event.get("kind") == "permission":
            return await self._await_permission(session, event)
        self._apply_event(session, event)
        await self._push_changes()
        return None

    async def _await_permission(self, session: str, event: dict[str, Any]) -> dict[str, Any] | None:
        s = self.sessions.get(session)
        if s is None:
            return None
        self._last_hook[session] = datetime.now(UTC)
        self._live_hook_at[session] = time.time()
        if (ruled := await self._by_rule(s, event)) is not None:
            await self._push_changes()
            return ruled
        wait = float(event.get("wait_seconds") or 600)
        deadline = (datetime.now(UTC) + timedelta(seconds=wait)).replace(microsecond=0)
        tool_use_id = event.get("tool_use_id") or f"{session}:{now_iso()}"
        pending = Pending(
            kind="permission",
            text=event.get("text", ""),
            deadline=deadline.isoformat().replace("+00:00", "Z"),
            tool_use_id=tool_use_id,
        )
        s.set_state("needs-you", confidence="hook", pending=pending)
        self.store.save(s)
        # Register the waiter BEFORE the first await: a client reacting to the push must find it.
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        key = (session, tool_use_id)
        self._waiters[key] = fut
        await self._push_changes()
        try:
            decision = await asyncio.wait_for(fut, timeout=wait)
        except TimeoutError:
            # Fell through to the terminal dialog: the decision now lives there (design §4.2) — but
            # only while the record still waits on this one. A later event already moved it on.
            s = self.sessions.get(session)
            if s is None or s.pending is None or s.pending.tool_use_id != tool_use_id:
                return None
            s.set_state("needs-you", confidence="hook", pending=Pending(kind="question", text=pending.text))
            self.store.save(s)
            await self._push_changes()
            return None
        else:
            # answered in the terminal (`_end_waiters`): the hook prints nothing, the tool has moved on
            return None if decision.get("terminal") else decision
        finally:
            self._waiters.pop(key, None)

    async def _by_rule(self, s: Any, event: dict[str, Any]) -> dict[str, Any] | None:
        """The person's written rules, the first line in front of them (design §4.9b *The director seat
        answers permission prompts for the person*, TD-641): for an **unattended** record only, its
        role's `deny` and then its `allow` in `settings.yml`'s `permissions:`, matched by the record's
        adapter against the prompt's tool and input. A deny answers; an allow answers unless the
        prompt is one that always reaches the person (`permits.always_the_person`), which goes on to
        the person as today. Every answer is filed to the person as *Answered for you*. None: no rule
        answered, and the prompt waits as before. An interactive record's prompt, and a question
        (which carries no tool), are never matched. **On a node** the hook is the node's and the rules
        its replica of the home's `settings.yml`, but the FYI is mail, whose one writer is the home
        (§9 invariant 15): a rule answers only while the link is up, and only once the home has filed
        the FYI over it (`answered_by_rule`); a link that is down, or a filing that fails, leaves the
        prompt waiting for the person, never answered untold."""
        tool, tool_input = event.get("tool"), event.get("input")
        if self.mode not in ("home", "node") or not s.unattended or not isinstance(tool, str) or not tool:
            return None
        if self.mode == "node" and (self._home_mux is None or not self._snapshot_sent):
            return None
        rules = settings_mod.permissions(settings_mod.load())[0].get(s.role or "")
        if not rules:
            return None
        try:
            adapter = adapters.get(s.adapter)
        except KeyError:
            return None
        matches = getattr(adapter, "rule_matches", None)
        if matches is None:
            return None
        cwd = Path(s.dir)
        try:
            hit = next((r for r in rules.get("deny", []) if matches(r, tool, tool_input, cwd=cwd, deny=True)), None)
            behavior = "deny"
            if hit is None:
                hit = next((r for r in rules.get("allow", []) if matches(r, tool, tool_input, cwd=cwd)), None)
                behavior = "allow"
                if hit is None:
                    return None
                strings = getattr(adapter, "prompt_strings", lambda *_: None)(tool, tool_input)
                touched = permits.all_strings(tool_input) if strings is None else strings
                if why := permits.always_the_person(touched, s.dir, s.repo):
                    log.info("%s: rule %s would allow %s, but %s: the person answers it", s.id, hit, tool, why)
                    return None
        except Exception:  # noqa: BLE001 — a rule that cannot be read answers nothing: the person does
            log.exception("%s: the permissions: rules could not be matched; the prompt waits", s.id)
            return None
        reason = f"rule: {hit}"
        prompt = event.get("text") or tool
        if self.mode == "node":
            try:
                await self._home_mux.request(
                    "answered_by_rule",
                    timeout=agent_common.REPORT_WRITE,
                    id=s.id,
                    prompt=prompt,
                    behavior=behavior,
                    rule=hit,
                )
            except (link.LinkError, link.LinkClosed, TimeoutError, OSError) as e:
                log.warning("%s: rule %s matched, but the home filed no FYI (%s): the person answers", s.id, hit, e)
                return None
        else:
            self._answered_by_rule(s, prompt, behavior, hit)
        return {"behavior": behavior, "reason": reason}

    def _answered_by_rule(self, s: Any, prompt: str, behavior: str, rule: str, asker: str | None = None) -> None:
        """The *Answered for you* FYI for a prompt a rule answered (§4.9b, §4.5a): the `answered` shape a
        sourced reply's FYI has — the prompt as the question, the member as the asker, *rules* as the
        answerer, the rule as the source. Written by the home, so it is no one's to reply to."""
        verdict = "allowed" if behavior == "allow" else "denied"
        role = s.role or ""
        source = f"settings.yml permissions: {role} {behavior} {rule}"[: mail.SOURCE_CAP]
        note = MailEntry(
            id="m-" + secrets.token_hex(6),
            from_=SYSTEM,
            to=[PERSON],
            at=now_iso(),
            kind="note",
            text=f"{verdict} by your rule {rule} — change it in settings.yml's permissions:",
        )
        note.team = getattr(s, "team", "") or None
        note.subject = mail.subject_of(f"{verdict}: {prompt}")
        note.answered = {"question": prompt, "asker": asker or s.id, "answerer": mail.RULES, "source": source}
        self.person_inbox.append(note)
        self.person_store.save(self.person_inbox)

    async def rpc_decide(
        self, id: str, tool_use_id: str, behavior: str, reason: str | None = None, caller: Any = None
    ) -> None:
        """Answer a pending permission through the hook (design §4.2). An act, gated like `send`
        (§4.8, TD-116): a session answers another's only as one of its controllers holding `control`."""
        s = self._get(id)
        fut = self._waiters.get((id, tool_use_id))
        if fut is None or fut.done():
            raise RpcError("no pending permission with that id (answered, timed out, or in the terminal)")
        if behavior not in ("allow", "deny"):
            raise RpcError("behavior must be allow or deny")
        fut.set_result({"behavior": behavior, "reason": reason})
        # the row ends here and the home knows how (design §4.10 *The Inbox is a queue*): the trail
        # says who answered — *you* for a person, the controller's name for a session — and a
        # person's answer is never too quick to record
        self._attention_ended(s.id, self._answered_by(behavior, caller))
        s.set_state("working", confidence="hook")
        if mail.is_person(caller):
            self._refill(s)  # a person's answer to its permission; a controller's refills nothing (§4.10)
        self.store.save(s)
        await self._push_changes()

    def _answered_by(self, behavior: str, caller: Any) -> str:
        """The trail's word for a decided permission: *allowed by you* when a person pressed it,
        *allowed by <name>* when a controller did (TD-116) — which is not *by you*, so a policy's
        200 ms answer stays under the trail's floor."""
        who = "you"
        if not mail.is_person(caller):
            # the one graph, so a controller on another host is named too, not shown as `id@host`
            rec = self._graph().get(self._addr(caller))
            who = rec.name if rec is not None else str(caller)
        return f"{'allowed' if behavior == 'allow' else 'denied'} by {who}"
