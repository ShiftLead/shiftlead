"""Told on Telegram when nobody is looking (design §4.10, TD-319 slices 1 and 2): the home's pass over
the rows that newly stop a session or a team — a state row `permission`, `question` or `needs`, an
identity alarm, an open `ask` in the person inbox, an outcome reported `blocked`, a record the tick
could not restart, a wound-down team whose lanes gained work under `on_work: ask`, an account whose CI
never starts (TD-687) — telling each once
it has stood `notify.HOLD`, is still there, is not snoozed and was not on a visible page, bounded by
`notify.BURST`; the send, a detached child under Doppler; and `notify_test`. A mixin `HostAgent`
inherits; the state it reads is the agent's.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sessionorc import agent_common, notify
from sessionorc import push as push_mod
from sessionorc import queue as queue_mod
from sessionorc import settings as settings_mod
from sessionorc import work as work_mod
from sessionorc.agent_common import RpcError, _parse, log
from sessionorc.mail import PERSON
from sessionorc.models import now_iso, reference_of

PUSH_RETRY = timedelta(minutes=10)  # a key that could not be read, or is missing with devices listed, read again


@dataclass(frozen=True)
class _Row:
    began: str
    line: str
    link: str  # the Inbox's row key, or a mail id when `mail`
    snooze: str  # the attention store's snooze key; for `mail`, the mail id
    mail: bool = False
    until: str | None = None  # a mail row's own `snoozed_until`, read where the entry is kept
    # a snooze before its first telling is the person's having seen it: never told in this row's life
    # (the *CI not starting* row's spell, §4.4 *Its spell*, TD-687)
    snooze_is_seen: bool = False
    # a mail row drawn on the Queue: `(card id, row qid)` of the open card its entry is on (TD-795)
    card: tuple[str, str] | None = None


def _restart_at(s: Any) -> str:
    """When the restart row (§4.5a **Inbox row: restart**) began, or "" for none: the page's
    `restart_mark` read from the same fields — a ceiling, a hold by work left, an early wanted."""
    if s.superseded_by:
        return ""
    for mark in (s.restart_ceiling, s.restart_blocked):
        if isinstance(mark, dict):
            return str(mark.get("at") or "")
    wanted = s.restart_wanted
    if isinstance(wanted, dict) and wanted.get("early") and s.state in ("idle", "exited"):
        return str(wanted.get("at") or "")
    return ""


def _card(e: Any, index: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    """The open card a mail row is drawn on, as the Inbox's `item_home` reads it (§4.5 screen 6 *Where a row is
    drawn*, TD-795); None for one set aside with a reviewer (`snoozed_for`), which the Inbox keeps."""
    return None if e.snoozed_for else queue_mod.mail_card(e.about, f"{e.subject or ''} {e.text or ''}", index)


def _work_ids(mark: dict[str, Any]) -> list[str]:
    members = mark.get("members") if isinstance(mark.get("members"), dict) else {}
    ids = [str(i) for v in members.values() if isinstance(v, list) for i in v]
    ids += [str(q.get("ref")) for q in mark.get("questions") or [] if isinstance(q, dict) and q.get("ref")]
    return list(dict.fromkeys(ids))


class NotifyMixin:
    def _notify_rows(self) -> dict[str, _Row]:
        """Every row standing now that is told when it stops someone, by a key of its own; each `line`
        built from structured fields alone (§4.10 *What a message says*)."""
        graph = self._graph()
        rows: dict[str, _Row] = {}
        for key, (kind, began, _text) in self._attention.items():
            sid, slot = key.split("|", 1)
            s = graph.get(sid)
            if s is None:
                continue
            name, team = s.name or sid, s.team or ""
            if slot == "state" and kind in notify.STATE_KINDS:
                k = f"{sid}|{kind}"
                rows[k] = _Row(began, notify.state_line(name, team, kind), k, k)
            elif slot == "alarm" and kind == "alarm":
                k = f"{sid}|alarm"
                rows[k] = _Row(began, notify.alarm_line(name, team), k, k)
        for sid, s in graph.items():
            if at := _restart_at(s):
                k = f"{sid}|restart"
                rows[k] = _Row(at, notify.restart_line(s.name or sid, s.team or ""), k, k)
        index = queue_mod.card_index(self._queue)
        for e in self.person_inbox:
            if e.from_ == PERSON:
                continue
            card = _card(e, index)
            s = graph.get(e.from_)
            name, team = (s.name or e.from_, s.team or "") if s is not None else (e.from_, e.team or "")
            ref = reference_of(e.about) or ""
            if e.kind == "ask" and e.open:
                line = notify.ask_line(name, team, ref)
                rows[e.id] = _Row(e.passed_up or e.at, line, e.id, e.id, mail=True, until=e.snoozed_until, card=card)
            outcome = e.outcome or {}
            if outcome.get("state") == "blocked":
                line = notify.blocked_line(name, team, ref)
                rows[f"blocked:{e.id}"] = _Row(
                    str(outcome.get("at") or ""), line, e.id, e.id, mail=True, until=e.snoozed_until, card=card
                )
        # work the person handed a session (§4.10 *An entry handed to a seat*): its one copy is the
        # holder's, and the Inbox counts it under Needs you once it comes back `blocked`
        for addr, r in graph.items():
            for e in r.inbox:
                outcome = e.outcome or {}
                if e.handed_entry and outcome.get("state") == "blocked":
                    line = notify.blocked_line(r.name or addr, r.team or "", reference_of(e.about) or "")
                    rows[f"blocked:{e.id}"] = _Row(
                        str(outcome.get("at") or ""),
                        line,
                        e.id,
                        e.id,
                        mail=True,
                        until=e.snoozed_until,
                        card=_card(e, index),
                    )
        doc = settings_mod.load()
        on_work = {
            name: (t or {}).get("on_work", settings_mod.ON_WORK_DEFAULT) for name, t in settings_mod.teams(doc).items()
        }
        for team, rec in (self._host_rec.get("teams") or {}).items():
            mark = rec.get("work_waiting") if isinstance(rec, dict) else None
            if not isinstance(mark, dict):
                continue
            stopped = mark.get("stopped") if isinstance(mark.get("stopped"), dict) else None
            if stopped is not None:
                # a stopped team is never started, so its row is told under `ask` and `start` alike — unless the
                # person stopped it, which is a fact kept in view, not a question (§6 rule 8, TD-781)
                if stopped.get("by") == "person":
                    continue
            elif mark.get("held") or on_work.get(team, settings_mod.ON_WORK_DEFAULT) != "ask":
                continue  # under `on_work: start` a held mark is the home's own wait, and nobody's stop
            if ids := _work_ids(mark):
                k = f"work:{team}"
                if stopped is not None:
                    rows[k] = _Row(
                        str(mark.get("at") or ""), notify.work_line(team, len(ids), stopped=True), k, f"{k}|work"
                    )
                    continue
                # a team that runs on names its finished members (TD-466): the home wrote the mark for them alone
                # *runs on* as the home reads it: its crew alone, a person's session in it keeps nothing live
                crew = work_mod.crew(r for r in graph.values() if r.team == team)
                live = any(r.state not in work_mod.DEAD for r in crew)
                finished = [str(m) for m in mark.get("members") or {}] if live else None  # keyed by name
                line = notify.work_line(team, len(ids), finished)
                rows[k] = _Row(str(mark.get("at") or ""), line, k, f"{k}|work")
        # *CI not starting* for an account (§4.4 *Its spell*, TD-687): one row a spell, begun at its `since`, so
        # it is told once per spell — a re-run that reads `not_run` again, or a snooze that runs out, is the same row
        for key, spell in (self._host_rec.get("ci_spells") or {}).items():
            if not isinstance(spell, dict) or not spell.get("since"):
                continue
            k = f"ci_not_run:{key}"
            n = len((spell.get("row") or {}).get("items") or [])
            line = notify.ci_line(str(spell.get("owner") or key), n)
            rows[k] = _Row(str(spell["since"]), line, k, f"{k}|ci_not_run", snooze_is_seen=True)
        return rows

    def _notify_snoozed(self, row: _Row, now: datetime) -> bool:
        until = row.until if row.mail else self.attention_snoozed.get(row.snooze)
        if not until:
            return False
        if until.startswith("dismissed:"):
            # the restart row's **Dismiss** (§4.5a, TD-103): that one mark's row is gone, as the page reads it
            return until == f"dismissed:{row.began}"
        with contextlib.suppress(ValueError, TypeError):
            return _parse(until) > now
        return False

    def _notify_pass(self, now: datetime) -> None:
        """Once a tick, at the home: what to tell, while either channel is on (§4.10 *Told on the home-screen app
        too*). A told row's key is kept in `notified` until its row ends, so it is told once whichever channels
        carry it; a row that ends and begins again is a new row. Nothing is sent with both channels off or on a
        node, and nothing here waits: each send is a detached child."""
        store = self.attention_store
        if self.mode != "home":
            return
        rows = self._notify_rows()
        gone = [k for k in store.notified if k not in rows]
        for k in gone:
            del store.notified[k]
        doc = settings_mod.load()
        tg = settings_mod.telegram(doc)
        pcfg = settings_mod.push(doc)
        pdoc = push_mod.load()
        self._push_keep_reading(pcfg, pdoc, now)
        # push is wanted while it is on and a device is listed; it sends only while the key reads *key* — paused
        # (*no key*, *unreadable*, or no reading yet) no child runs and every row is one no device took
        push_wanted = pcfg["on"] and bool(pdoc["devices"])
        push_sends = push_wanted and pdoc.get("key") == push_mod.KEY
        if push_wanted and push_mod.paused(pdoc):
            push_mod.save(pdoc)
        due: list[tuple[str, _Row]] = []
        due_seen = False
        for key, row in rows.items():
            if row.snooze_is_seen and key not in store.notified and self._notify_snoozed(row, now):
                store.notified[key] = now_iso()  # seen, as if told, either channel on or off: never told in this life
                due_seen = True
        if tg is not None or push_wanted:
            for key, row in sorted(rows.items(), key=lambda kv: kv[1].began):
                if key in store.notified:
                    continue
                try:
                    stood = now - _parse(row.began)
                except (ValueError, TypeError):
                    continue
                if stood < notify.HOLD or stood > notify.HOLD + notify.LATE or self._notify_snoozed(row, now):
                    continue  # not yet; or a backlog, never told (§4.10 *newly*); or the person's *not now*
                due.append((key, row))
        watched = self._notify_watched_at is not None and now - self._notify_watched_at <= notify.WATCHED
        items: list[tuple[str, _Row] | None] = []  # None is *and more need you*
        stamp = now_iso()
        for key, row in due:
            # told, or on a visible page, or held back by the burst, or paused: in each case never told afterwards
            store.notified[key] = stamp
            if watched:
                continue  # it was on a screen, where the top bar's count rose (§4.10 *Looking*)
            self._notify_sent = [t for t in self._notify_sent if now - t < notify.BURST_WINDOW]
            if self._notify_quiet_until is not None and now < self._notify_quiet_until:
                continue
            if len(self._notify_sent) < notify.BURST:
                items.append((key, row))
            else:
                # the seventh is *and more*, and nothing more until ten minutes have passed with nothing sent
                items.append(None)
                self._notify_quiet_until = now + notify.BURST_WINDOW
            self._notify_sent.append(now)
        if gone or due or due_seen:
            store.save(self.trail, self.attention_snoozed)
        if items and (tg is not None or push_sends):
            task = asyncio.create_task(self._notify_deliver(tg, pcfg if push_sends else None, items))
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)

    @staticmethod
    def _notify_text(tg: dict[str, Any], item: tuple[str, _Row] | None) -> str:
        """A row's Telegram message: its line and its address under the person's `link`."""
        if item is None:
            return notify.MORE
        _, row = item
        if row.card is not None:
            link = notify.queue_link(tg["link"], *row.card, row.link)
        elif row.mail:
            link = notify.mail_link(tg["link"], row.link)
        else:
            link = notify.row_link(tg["link"], row.link)
        return notify.message(row.line, link)

    @staticmethod
    def _push_payload(item: tuple[str, _Row] | None) -> dict[str, str]:
        """A row's push (§4.10 *What a push carries*): `{body, path, tag}` — the line after *shiftlead ·*, the
        page's path alone, and the row's key (`more` for *and more need you*)."""
        if item is None:
            return {"body": notify.body(notify.MORE), "path": "/inbox", "tag": "more"}
        key, row = item
        if row.card is not None:
            path = notify.queue_path(*row.card, row.link)
        elif row.mail:
            path = notify.mail_path(row.link)
        else:
            path = notify.row_path(row.link)
        return {"body": notify.body(row.line), "path": path, "tag": key}

    async def _notify_deliver(
        self, tg: dict[str, Any] | None, pcfg: dict[str, Any] | None, items: list[tuple[str, _Row] | None]
    ) -> None:
        """The pass's send task (§4.10 *with Telegram*): push to every device and Telegram side by side under
        `both`; under `fallback` the push child first, then Telegram for each row no push service accepted."""
        texts = [self._notify_text(tg, item) for item in items] if tg is not None else []
        if pcfg is None:
            if tg is not None:
                await self._notify_send(tg["secrets"], texts)
            return
        payloads = [self._push_payload(item) for item in items]
        if tg is None:
            await self._push_safely(pcfg["secrets"], payloads)
        elif pcfg["telegram"] == "fallback":
            taken = await self._push_safely(pcfg["secrets"], payloads)
            await self._notify_send(tg["secrets"], [t for i, t in enumerate(texts) if i not in taken])
        else:
            await asyncio.gather(self._notify_send(tg["secrets"], texts), self._push_safely(pcfg["secrets"], payloads))

    async def _push_safely(self, secrets: str, payloads: list[dict[str, str]]) -> set[int]:
        """`_push_send` for the pass: a failure of the home's own (a write of `push.json`) is logged and reads as
        no device having taken anything, so under `fallback` Telegram still carries every row."""
        try:
            return (await self._push_send(secrets, payloads))[0]
        except Exception:  # noqa: BLE001 — logged; a told row must not be lost to it
            log.exception("push send failed")
            return set()

    def _notify_watching(self, now: datetime) -> None:
        """A person's `inbox` read from a visible page (§4.10 *Looking*): kept in memory only."""
        self._notify_watched_at = now

    async def rpc_notify_test(self, channel: Any = None, device: Any = None, caller: Any = None) -> dict[str, Any]:
        """**Send a test** (§4.5a **You**: **Telegram**, §4.10): one message now with the saved
        secrets and link, whatever `on` says — *shiftlead · a test from <home>* and the Inbox's
        address — answering the send's result in words. `channel: push` with a `device` id is **Send a
        test to this device** (§4.10 *Told on the home-screen app too*). A person's own
        (`mail.PERSON_ONLY`), at the home alone (`modes.HOME_EDITS` forwards it from a node)."""
        agent_common.person_only(caller, "send a test", "§4.10", self._graph())
        if self.mode != "home":
            raise RpcError("notify_test runs at the home (design §4.10): this host is a node")
        if channel == "push":
            return await self._push_test(device)
        if channel not in (None, "", "telegram"):
            raise RpcError(f"notify_test: channel is telegram or push, not {channel!r} (design §4.10)")
        doc = settings_mod.load()
        tg = settings_mod.notify(doc).get("telegram") or {}
        if not tg.get("secrets"):
            raise RpcError(
                "notify.telegram.secrets is not set: save the Doppler project/config that holds "
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first (design §4.10)"
            )
        link = f"{base}/inbox" if (base := settings_mod.telegram_link(doc)) else ""
        why = await self._notify_run(tg["secrets"], notify.message(notify.test_line(self.home or self.host), link))
        at = now_iso()
        if why is None:
            self._notify_last["last_ok"] = at
            return {"sent": True, "at": at, "result": f"sent at {at}"}
        self._notify_last["last_error"] = {"at": at, "reason": why}
        return {"sent": False, "at": at, "result": f"the send failed: {why}"}

    async def _push_test(self, device: Any) -> dict[str, Any]:
        """*shiftlead · a test from <home>* to one device, whatever `notify.push.on` says; refused while the key
        is paused (its reading in words) or not yet read. *delivered to <label> 14:02* on a 2xx; a 404 or 410
        drops the device and says so; any other failure in `last_error`'s words."""
        secrets = settings_mod.push(settings_mod.load())["secrets"]
        if not secrets:
            raise RpcError("notify_test: set notify.push.secrets (or Telegram's) first (design §4.10)")
        pdoc = push_mod.load()
        reading = pdoc.get("key")
        if reading is None:
            raise RpcError("notify_test: reading the key — try again shortly (design §4.10)")
        if reading != push_mod.KEY:
            raise RpcError(f"notify_test: {push_mod.PAUSED.format(reading)} (design §4.10)")
        dev = next((d for d in pdoc["devices"] if isinstance(device, str) and d.get("id") == device), None)
        if dev is None:
            raise RpcError(f"notify_test: no device {device!r} is listed (design §4.10)")
        payload = {"body": notify.body(notify.test_line(self.home or self.host)), "path": "/inbox", "tag": "test"}
        _, statuses, why = await self._push_send(secrets, [payload], only=device)
        at = now_iso()
        status = statuses.get((device, 0), why or push_mod.NO_ANSWER)
        if push_mod.ok(status):
            return {"sent": True, "at": at, "result": f"delivered to {dev.get('label')} {push_mod.hhmm(at)}"}
        if status in (404, 410):
            result = f"the push service answered {status} — this device's subscription ended"
        else:
            result = push_mod.words(status)
        return {"sent": False, "at": at, "result": result}

    async def _notify_send(self, secrets: str, texts: list[str]) -> None:
        """The messages, one child each, in order; the last result kept for the `host` read. A failure
        is not retried, is not a row and is never itself told (§4.10 *A failed send is shown*)."""
        for text in texts:
            why = await self._notify_run(secrets, text)
            at = now_iso()
            if why is None:
                self._notify_last["last_ok"] = at
            else:
                self._notify_last["last_error"] = {"at": at, "reason": why}
                log.warning("telegram send failed: %s", why)

    async def _notify_run(self, secrets: str, text: str) -> str | None:
        """One child under Doppler with `text` on stdin, given `notify.CHILD_SECONDS`: None when it
        exited 0, else its reason in one line. Replaced by a recorder in the tests."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *notify.argv(secrets),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # its own group: a timeout ends Doppler's child, which holds the token, too
            )
        except FileNotFoundError:
            return "doppler: not installed"
        except OSError as e:
            return f"doppler could not be run: {type(e).__name__}"
        try:
            _, err = await asyncio.wait_for(proc.communicate(text.encode()), notify.CHILD_SECONDS)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            return f"no answer in {notify.CHILD_SECONDS:g} s"
        if proc.returncode == 0:
            return None
        return notify.reason(err.decode(errors="replace")) or f"exit {proc.returncode}"

    def _push_view(self) -> dict[str, Any]:
        """`push` for the `host` read (§4.10 *Told on the home-screen app too*): `push.json` less each device's
        endpoint and keys — the seam the Settings page's Push card draws from."""
        return push_mod.view(push_mod.load())

    def _push_home(self, act: str) -> None:
        if self.mode != "home":
            raise RpcError(f"{act} runs at the home (design §4.10 *Only the home sends*): this host is a node")

    async def rpc_push_subscribe(
        self,
        endpoint: Any = None,
        keys: Any = None,
        label: Any = None,
        key: Any = None,
        replaces: Any = None,
        caller: Any = None,
    ) -> dict[str, Any]:
        """**tell me on this device** (§4.5a **You**: **Push**, §4.10 *On and off, per device*): list this
        browser's subscription in `push.json` and answer `{id}`; refused, naming the field, for a key that is
        not the home's, an endpoint that is not `https` to a public host, or keys of the wrong size, and while
        the key reads anything but *key*. A person's own, at the home alone (it is not in `modes.HOME_EDITS`:
        a tap opens the origin the worker was registered on)."""
        agent_common.person_only(caller, "turn push on for a device", "§4.10", self._graph())
        self._push_home("push_subscribe")
        doc = push_mod.load()
        held = {str(d.get("id")) for d in doc.get("devices") or () if isinstance(d, dict)}
        try:
            got = push_mod.subscribe(doc, endpoint, keys, label, key, now_iso(), replaces)
        except ValueError as e:
            raise RpcError(f"push_subscribe: {e} (design §4.10)") from None
        push_mod.save(doc)
        # push on, witnessed (§4.4, TD-1386): an endpoint new to the home whose post names no held device in
        # `replaces` — a renewal the page could not name reads as a new device and is recorded
        if got not in held and not (replaces and str(replaces) in held):
            await self._witness_press_of("push-on", got, None)
        return {"id": got}

    async def rpc_push_unsubscribe(self, id: Any = None, caller: Any = None) -> dict[str, Any]:
        """**tell me on this device** off, or a device's **Remove** (§4.5a **You**: **Push**): drop the device
        `id` from `push.json`. A person's own, at the home alone. `{removed}`: false when it was not listed."""
        agent_common.person_only(caller, "turn push off for a device", "§4.10", self._graph())
        self._push_home("push_unsubscribe")
        if not isinstance(id, str) or not id:
            raise RpcError("push_unsubscribe: id is the device's id (design §4.10)")
        doc = push_mod.load()
        removed = push_mod.unsubscribe(doc, id)
        if removed:
            push_mod.save(doc)
        return {"removed": removed}

    async def rpc_push_key(self, caller: Any = None) -> dict[str, Any]:
        """**Make key** (§4.5a **You**: **Push**, §4.10 *The key's reading*): a child under `notify.push.secrets`
        alone (`--key`) makes a P-256 pair and writes its private half there — refused when that field is unset,
        when a key is there (its reading kept), or as Doppler refused the write, in words. On success the home
        keeps `key` *key* and the public key it answered. A person's own, at the home alone."""
        agent_common.person_only(caller, "make the push key", "§4.10", self._graph())
        self._push_home("push_key")
        own = settings_mod.push(settings_mod.load())["own_secrets"]
        if not own:
            raise RpcError("push_key: set notify.push.secrets — the key is written only there (design §4.10)")
        async with self._push_key_lock:
            lines, why, _ = await self._push_run(own, ("--key", own))
        first = lines[0] if lines else None
        self._push_gen += 1  # a reading or send begun before this answer is of the old key
        pdoc = push_mod.load()
        if push_mod.reading_of(first) is not None:
            push_mod.apply_reading(pdoc, first)
            push_mod.save(pdoc)
        if why is None and push_mod.reading_of(first) == push_mod.KEY:
            return {"public_key": pdoc["public_key"], "result": "the key is made: turn this on on each device"}
        raise RpcError(f"push_key: {why or 'no key was made'} (design §4.10)")

    def _push_secrets_moved(self) -> None:
        """A Save that moved `notify.push.secrets` (or Telegram's, which push reads when its own is unset): the
        kept reading is of another config, so there is none until the next background read answers."""
        if self.mode != "home":
            return
        self._push_gen += 1
        self._push_read_at = None
        pdoc = push_mod.load()
        if pdoc.pop("key", None) is not None:
            push_mod.save(pdoc)

    def _push_keep_reading(self, pcfg: dict[str, Any], pdoc: dict[str, Any], now: datetime) -> None:
        """Start the key's `--public` read in the background (§4.10 *The key's reading*) — never inside a read —
        when a secrets config is set and there is no reading, and every `PUSH_RETRY` while it reads
        *unreadable*, or *no key* with devices listed. With no config set there is no reading to keep."""
        if not pcfg["secrets"] or (self._push_reading is not None and not self._push_reading.done()):
            return
        reading = pdoc.get("key")
        if reading is not None:
            stale = reading.startswith("unreadable") or (reading == push_mod.NO_KEY and pdoc["devices"])
            if not stale or (self._push_read_at is not None and now - self._push_read_at < PUSH_RETRY):
                return
        self._push_read_at = now
        self._push_reading = asyncio.create_task(self._push_read(pcfg["secrets"], self._push_gen))
        self._bg.add(self._push_reading)
        self._push_reading.add_done_callback(self._bg.discard)

    async def _push_read(self, secrets: str, gen: int) -> None:
        lines, why, _ = await self._push_run(secrets, ("--public",))
        if gen != self._push_gen:
            return  # a Save moved `secrets` meanwhile: this is the old config's reading
        first = lines[0] if lines else None
        pdoc = push_mod.load()
        if push_mod.reading_of(first) is not None:
            push_mod.apply_reading(pdoc, first)
        else:
            pdoc["key"] = f"unreadable: {why or 'no answer'}"
        push_mod.save(pdoc)

    async def _push_send(
        self, secrets: str, payloads: list[dict[str, str]], only: str | None = None
    ) -> tuple[set[int], dict[tuple[str, int], Any], str | None]:
        """One push child to every device (or `only` that one): `(taken, statuses, why)` — the payload indices
        some push service accepted, each `(device, index)`'s status, and why no status was applied (a reading
        that is not *key*, or a changed key). The derived-key check runs first; a 404 or 410 drops a device."""
        pdoc = push_mod.load()
        devices = [d for d in pdoc["devices"] if only is None or d.get("id") == only]
        if not devices or not payloads:
            return set(), {}, None
        url = (settings_mod.reach(settings_mod.load()) or {}).get("url") or ""
        job = {
            "sub": url if url.startswith("https://") else notify.PUSH_SUB,
            "payloads": payloads,
            "devices": [{k: d.get(k) for k in ("id", "endpoint", "keys")} for d in devices],
        }
        gen = self._push_gen
        lines, why, timed_out = await self._push_run(secrets, ("--push",), json.dumps(job))
        at = now_iso()
        if gen != self._push_gen:
            return set(), {}, "the key's config changed while the push ran"  # its reading is of the old config
        first = lines[0] if lines else None
        pdoc = push_mod.load()  # afresh: a subscribe may have landed while the child ran
        if push_mod.reading_of(first) is None:
            if timed_out:
                if pdoc.get("key") != push_mod.KEY:
                    return set(), {}, why
                first = {"key": push_mod.KEY, "public_key": pdoc.get("public_key")}  # nothing said: kept reading
            else:
                pdoc["key"] = f"unreadable: {why or 'no answer'}"
                push_mod.paused(pdoc)
                push_mod.save(pdoc)
                log.warning("push send failed: %s", why)
                return set(), {}, pdoc["key"]
        if push_mod.apply_reading(pdoc, first) or pdoc.get("key") != push_mod.KEY:
            push_mod.paused(pdoc)
            push_mod.save(pdoc)
            return set(), {}, pdoc.get("last_line") or str(pdoc.get("key"))
        statuses: dict[tuple[str, int], Any] = {
            (str(d["id"]), i): why or push_mod.NO_ANSWER for d in devices for i in range(len(payloads))
        }
        for ln in lines[1:]:
            with contextlib.suppress(KeyError, TypeError, ValueError):
                k = (str(ln["device"]), int(ln["i"]))
                if k in statuses:
                    statuses[k] = ln["status"]
        taken = push_mod.apply_statuses(pdoc, statuses, at)
        push_mod.save(pdoc)
        if failed := sum(1 for v in statuses.values() if not push_mod.ok(v)):
            log.warning("push: %d of %d sends not accepted", failed, len(statuses))  # never an endpoint
        return taken, statuses, None

    async def _push_run(
        self, secrets: str, mode: tuple[str, ...], stdin: str = ""
    ) -> tuple[list[Any], str | None, bool]:
        """One push child under Doppler (`--push`, `--public`, `--key`), given `CHILD_SECONDS` plus
        `REQUEST_SECONDS`: `(lines, why, timed_out)` — each JSON line it printed, kept on a timeout too; None
        when it exited 0, else its reason in one line. Replaced by a fake in the tests."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *notify.argv(secrets, *mode),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # its own group: a timeout ends Doppler's child, which holds the key, too
            )
        except FileNotFoundError:
            return [], "doppler: not installed", False
        except OSError as e:
            return [], f"doppler could not be run: {type(e).__name__}", False
        lines: list[Any] = []

        async def talk() -> bytes:
            assert proc.stdin and proc.stdout and proc.stderr
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                proc.stdin.write(stdin.encode())
                await proc.stdin.drain()
                proc.stdin.close()
            err = asyncio.ensure_future(proc.stderr.read())
            async for raw in proc.stdout:
                with contextlib.suppress(ValueError):
                    lines.append(json.loads(raw))
            await proc.wait()
            return await err

        bound = notify.CHILD_SECONDS + notify.REQUEST_SECONDS
        try:
            err = await asyncio.wait_for(talk(), bound)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            return lines, f"no answer in {bound:g} s", True
        if proc.returncode == 0:
            return lines, None, False
        return lines, notify.reason(err.decode(errors="replace")) or f"exit {proc.returncode}", False

    def _notify_view(self) -> dict[str, Any]:
        """`notify: {last_ok, last_error}` for the `host` read (§4.10): the last send's result."""
        return dict(self._notify_last)
