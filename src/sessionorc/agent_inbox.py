"""The person's own bookkeeping on their inbox (TD-108 step 1): design §4.10 and TD-069 step 0 — snooze,
dismiss, pause, resume, go with it, the attention store — as a mixin `HostAgent` inherits (delete is mail's,
`agent_mail.py`), and the person's Dismiss on the Inbox's work-waiting and mark rows (`rpc_clear_work`,
`rpc_clear_mark`, from `agent_wake.py` in TD-317 slice 2). Moved as written; the state it reads is the agent's.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import (
    adapters,
    agent_common,
    hosts,
    ledgerboard,
    mail,
    workorders,
)
from sessionorc import board as board_mod
from sessionorc import cadence as cadence_mod
from sessionorc import held as held_mod
from sessionorc import ledger as ledger_mod
from sessionorc import seams as seams_mod
from sessionorc import settings as settings_mod
from sessionorc.agent_common import (
    ENTRY_PRIORITIES,
    ENTRY_TYPES,
    LEASE_TTL,
    RpcError,
    _older,
    _parse,
    _prune_tallies,
    log,
)
from sessionorc.models import (
    ATTENTION_KINDS,
    PERSON,
    MailEntry,
    Session,
    normalize_ref,
    now_iso,
)

# A board reply's note quotes the item's head, clipped where the SessionStart line clips an item (§4.4).
BOARD_HEAD_CHARS = 200
# a ledger row's two roads and the fixed words each writes before the person's (§4.5 screen 12 *any open row*, TD-905)
LEDGER_ROADS = {"done": "done", "design": "back to design"}


def reply_note(sent: list[dict[str, str]], refused: list[str]) -> str:
    """A board Reply's result in words (§4.5a *Inbox board row → Reply*), which the trail says too."""
    note = "written on the board"
    if sent:
        note += " · sent to " + ", ".join(f"{x['session']} (holds {x['ref']})" for x in sent)
    if refused:
        note += " · not sent to " + "; ".join(refused)
    return note


def board_refs(refs: list[str] | None) -> list[str]:
    """The board reader's `refs` as a lease names them (§4.8): `TD-122` canonical, and the reader's
    `PR #1020` the `#1020` a claim on a PR number is. In order, each once; an unreadable one dropped."""
    out: list[str] = []
    for raw in refs or ():
        r = " ".join(str(raw).split())
        if r.upper().startswith("PR ") or r.upper().startswith("PR#"):
            r = r[2:].strip()
        try:
            r = normalize_ref(r)
        except ValueError:
            continue
        if r not in out:
            out.append(r)
    return out


# What a session may not do with `entry_add` but for another repo (design §4.9, §4.7 *Entries*): its own
# ledger's entry is written on its branch, and reported with `ao finding`
ENTRY_ACT = (
    "add an entry to the ledger this way — a session writes one on its branch (cadence §2), or files `ao finding`"
)


class InboxMixin:
    # -- the person's own bookkeeping on their inbox (design §4.10, TD-069 step 0) ----------------
    # Each is refused to every session exactly as `inbox_delete` is, and each acts on the org's
    # person inbox: a snooze, a pause and a *Go with it* are the person's, and no session has them.

    def _inbox_changed(self, rev: int) -> None:
        """The person inbox was written (design §4.4 *Each reading has one owner*, TD-616): push
        `{event: "inbox", rev}` to every subscriber, so the UI recounts the Inbox once per change
        instead of polling it. Called by the store's every save, sync or not; with no loop running
        (a test's direct call) there is nobody subscribed to tell."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        task = asyncio.ensure_future(self._broadcast({"event": "inbox", "rev": rev}))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def _person_entry(self, msg: str, caller: Any, what: str) -> MailEntry:
        agent_common.person_only(caller, f"{what} mail", "§4.10", self._graph())
        held = [e for e in self.person_inbox if e.id == msg]
        if not held:
            raise RpcError(f"the person inbox holds no entry {msg}")
        return held[0]

    async def rpc_inbox_snooze(self, msg: str, until: str | None = None, caller: Any = None) -> dict[str, Any]:
        """**Snooze** (design §4.10, TD-069): `snoozed_until` on a person-inbox entry, set by this
        RPC and cleared by it with no `until`. A snooze is the person's own bookkeeping, as editing
        a `Due:` date is, and the sender is not told. It persists with the person inbox and affects
        **the Inbox page only** — the entry leaves its section and the page's count until that time
        — and nothing else: it is still unread if it was, it still occupies the depths, and a
        snoozed `ask` stays open. A `steer` has **Pause** instead, so it is refused one: snooze
        hides a row while its clock runs, pause stops the clock, and both on one row invite the
        wrong press."""
        e = self._person_entry(msg, caller, "snooze")
        if e.kind == "steer":
            raise RpcError(f"{msg} is a steer: it has Pause, which stops its clock, and no Snooze (design §4.10)")
        # **Unsnooze** brings a look handed to a reviewer back sooner (§4.5a **Send to reviewer**): the
        # handed `ask` stays with the seat and owes its outcome, which is still written on the look
        self._mark(msg, snoozed_until=str(until) if until else None, **({} if until else {"snoozed_for": None}))
        return {"id": PERSON, "msg": msg, "snoozed_until": e.snoozed_until}

    async def rpc_inbox_hand(self, msg: str, seat: str = "", caller: Any = None) -> dict[str, Any]:
        """**Send to reviewer** (design §4.5a, §4.10 *A look*, TD-292 slice 4): a look that is an
        open `ask`, handed to its sender's team's techlead seat as an `ask` from the person marked
        `handed`, carrying the look's text, `about`, `shots` and id (`look`), with **no bound** — it
        ends by its outcome or the person's Dismiss, as a handed entry does — and the look snoozed
        **until that debt closes** (`snoozed_for`, the handed entry's id). The person's alone,
        refused to every session as `inbox_snooze` is. The host agent does not read `org.yml`, so the
        caller names the seat (`seat`, the id the sender's team's techlead takes; empty where the
        team defines none). Refused in words: not a look, not an open `ask`, already with a reviewer,
        no techlead seat. Returns `{id, msg, to, read_when}`."""
        e = self._person_entry(msg, caller, "hand")
        if not e.shots:
            raise RpcError(f"{msg} is not a look: it names no screenshots (design §4.10 *A look*)")
        if e.kind != "ask":
            raise RpcError(
                f"{msg} is a {e.kind}: only an `ask` look is sent to a reviewer — a steer has Go with it "
                "and lapses to its default (design §4.5a)"
            )
        if not e.open:
            raise RpcError(f"{msg} is already answered: there is nothing left to send to a reviewer (design §4.5a)")
        if busy := next((h.id for r in self._graph().values() for h in r.inbox if h.look == e.id and h.owes), None):
            raise RpcError(f"{msg} is already with a reviewer ({busy}): its outcome brings it back")
        to = str(seat or "").strip()
        if not to:
            raise RpcError(
                f"{e.team or 'its sender'} has no techlead seat: there is nobody to send the look to (design §4.9b)"
            )
        # held from the check to the snooze: two presses (two tabs, a double click) send one ask
        handing: set[str] = self.__dict__.setdefault("_looks_handing", set())
        if e.id in handing:
            raise RpcError(f"{msg} is already with a reviewer: it is being sent now")
        handing.add(e.id)
        try:
            sent = await self._msg(PERSON, e.text, [to], "ask", e.about, None, None, None)
        finally:
            handing.discard(e.id)
        mid = (sent.get("entry") or {}).get("id")
        if not mid:
            raise RpcError(f"the look was not delivered to {to}")
        to = next(iter(sent.get("delivered") or ()), to)  # a seat started again under its name (review of #764)
        # the debt, the look's screenshots and its id, and no bound: it ends by its outcome (§4.10). The
        # shots are written here, not sent: `--shot` rides only toward the person, and this is the
        # person's own look going the other way
        self._mark(mid, handed=True, shots=list(e.shots), look=e.id, bound=None)
        self._mark(e.id, snoozed_for=mid, looked_by=None)  # an earlier reading is not this one's
        await self._push_changes()
        log.info("inbox_hand: look %s handed to %s as %s", e.id, to, mid)
        return {"id": PERSON, "msg": e.id, "handed": mid, "to": to, "read_when": self._entry_read_when(to)}

    async def rpc_inbox_dismiss(self, msg: list[str] | str, caller: Any = None) -> dict[str, Any]:
        """**Dismiss** and **Dismiss all** (design §4.10 *The Inbox is a queue*, TD-079): the one
        way a `note` or a trail entry leaves the person's Inbox — *reading never removes a row; an
        answer does, and dismissing is an answer.*

        Takes a **list of ids**, mail (`m-`) and trail (`t-`) alike, because *Dismiss all*
        dismisses **the entries this browser has on screen**, never *everything FYI holds now*:
        mail that arrived after the page was drawn is exactly what must not go unseen. An id that
        is already gone is skipped — two browsers may press it at once — and an **open question is
        refused**, naming it: a question is answered, declined or snoozed, never swept away.

        **A person's only**, refused to every session exactly as `inbox_delete` is and, like it, no
        never-gated read (§4.8a): a session that could dismiss the person's rows could bury its own
        question."""
        agent_common.person_only(caller, "dismiss the person's rows", "§4.10 *The Inbox is a queue*", self._graph())
        ids = [str(x) for x in ([msg] if isinstance(msg, str) else list(msg or [])) if str(x).strip()]
        if not ids:
            raise RpcError("dismiss names the entries to dismiss, by id (design §4.10)")
        held = {e.id: e for e in self.person_inbox}
        if still_open := [i for i in ids if i in held and held[i].open]:
            raise RpcError(
                f"{', '.join(still_open)} is still open: a question is answered, declined or snoozed, never "
                "dismissed with the rest (design §4.10 *The Inbox is a queue*)",
                open=still_open,
            )
        wanted = set(ids)
        # *The debt ends when the person **Dismisses** the row — I do not need to hear back — and
        # the asker is told by a `system` note, as for every other act of the person's on its mail*
        # (design §4.10 *Outcomes*). Only now that both halves of step 1 are in one tree.
        at = now_iso()
        for e in [x for x in self.person_inbox if x.id in wanted and x.owes]:
            self._mark(e.id, outcome={"state": "dismissed", "text": "", "at": at, "by": ""})
            self._system_note(e.from_, f"the person dismissed {e.id}: no outcome is owed on it")
        # work the person handed a session lives in that session's inbox, not the person's: its row
        # under *Waiting on them* is dismissed the same way — the debt ends, the holder is told
        # (§4.10 *An entry handed to a seat*, TD-218 slice 3)
        handed: list[str] = []
        for addr, r in list(self._graph().items()):
            for e in r.inbox:
                if (
                    e.id in wanted
                    and e.id not in handed
                    and e.handed
                    and (e.owes or (e.outcome or {}).get("state") == "blocked")  # a blocked row is dismissed too
                ):
                    self._mark(e.id, outcome={"state": "dismissed", "text": "", "at": at, "by": ""})
                    self._system_note(addr, f"the person dismissed {e.id}: no outcome is owed on it")
                    handed.append(e.id)
        dismissed = [e.id for e in self.person_inbox if e.id in wanted]
        if dismissed:
            self.person_inbox = [e for e in self.person_inbox if e.id not in wanted]
            self.person_store.save(self.person_inbox)
        dropped = [e["id"] for e in self.trail if e.get("id") in wanted]
        if dropped:
            self.trail = [e for e in self.trail if e.get("id") not in wanted]
            self.attention_store.save(self.trail, self.attention_snoozed)
        return {
            "id": PERSON,
            "dismissed": [*dismissed, *handed, *dropped],
            "skipped": [i for i in ids if i not in (*dismissed, *handed, *dropped)],
            "unread": sum(1 for e in self.person_inbox if not e.read_at),
        }

    async def rpc_attention_snooze(
        self, id: str, kind: str, until: str | None = None, caller: Any = None
    ) -> dict[str, Any]:
        """A **state row's** Snooze (design §4.10 *The Inbox is a queue*; TD-069's open gap): a
        state lives on the record and has no mail entry to carry a `snoozed_until`, so the person's
        *not now* is kept in the home's own attention store, per record **and row kind** — a
        session's permission and its stalled row are two rows, and snoozing one is not snoozing the
        other. No `until` clears it. A person's only, as every act on the person's Inbox is."""
        agent_common.person_only(caller, "snooze the person's rows", "§4.10", self._graph())
        # `promote` (§4.5a *Inbox row: promote*, TD-132): keyed `promote:<repo>`, a repo and not a
        # record, so Snooze is by time alone and a later merge does not wake the row; `work`
        # (§4.5a *Inbox row: team start*, §6 rule 8) the same way, keyed `work:<team>`, and `lanes` — a defined
        # team with no record (§6 rule 8 *A team with no record*, TD-781) — keyed `lanes:<team>`
        # `idle_open` (§4.5a *Inbox row: idle · open work*, TD-259): a record's row, keyed as `stalled` is
        # `cadence:<pr>` (§4.5a *Inbox row: cadence check failed*, TD-258): a record's row and one a
        # PR, so the key carries the PR's number
        # `red_pr` (§4.5a *Inbox row: red PR*, TD-613): keyed `red_pr:<repo>:<n>`, a PR and not a record
        # `fork_pr` (§4.5a *Inbox row: fork's PR*, TD-1292): keyed `fork_pr:<repo>:<n>`, the same way
        cadence = (
            kind.startswith("cadence:") and kind[8:].isascii() and kind[8:].isdigit() and kind[8:] == str(int(kind[8:]))
        )
        # `ci_not_run` (§4.5a *Inbox row: CI not starting*, TD-687): keyed `ci_not_run:<owner>`, by time alone
        rows = (
            *ATTENTION_KINDS,
            "alarm",
            "restart",
            "idle_open",
            "promote",
            "work",
            "lanes",
            "red_pr",
            "fork_pr",
            "ci_not_run",
        )
        if not cadence and kind not in rows:
            raise RpcError(
                f"unknown row kind {kind!r}; the state rows are: "
                f"{', '.join(ATTENTION_KINDS)}, alarm, restart, idle_open, cadence:<pr>, promote, work, "
                "lanes, red_pr, fork_pr, ci_not_run"
            )
        key = f"{self._addr(id)}|{kind}"
        if until:
            self.attention_snoozed[key] = str(until)
        else:
            self.attention_snoozed.pop(key, None)
        self.attention_store.save(self.trail, self.attention_snoozed)
        return {"id": PERSON, "row": key, "snoozed_until": self.attention_snoozed.get(key)}

    async def rpc_board_edit(
        self,
        board: str,
        line: int | None = None,
        text: str = "",
        action: str = "",
        due: str | None = None,
        entry: str | None = None,
        answer: str = "",
        answers: list[str] | None = None,
        key: str = "",
        caller: Any = None,
    ) -> dict[str, Any]:
        """**Snooze**, **Done** or **Decide** on a board item (design §4.4 *Board write-back*, TD-069 step 3):
        the one line edited on origin's head in the host agent's own tree, committed with the fixed
        message and landed by its own PR (`board.write_back`); the checkout is never written.
        `board` must be the board of a checkout this host's repos registry names;
        `line` and `text` are what agent-cadence's reader gave the Inbox, and the edit is refused
        unless the line still holds that text. `key` is the line's id (`board:<key>`, §4.4 *A board
        line's id*, TD-603): the open line whose id it is is found first, wherever it now sits and
        whatever a snooze or a reply has added to it, and refused in its own words when none is.
        A person's only, as every act on the Inbox is.

        `action: add` is **Put on the board** (§4.5a, TD-140): `entry` an FYI row of the person's
        Inbox — a `note`, a closed question, a trail row, never an open `ask` or `steer` — and
        `text` and `due` the form's; one new line at the top of the board's open items naming the
        entry's sender and its `about`, committed, and only then the entry dismissed as Dismiss
        does, so a refused or failed commit leaves the row where it was.

        `action: decide` is the fourth edit (§4.4 *Decide*, TD-255): `answer` written as the
        line's `Decided:` field. `answers` is the item's own list as the reader gave it to the
        page, handed as a Reply's `refs` are, and the answer is one of them word for word — or,
        where the live look's pair is among them, `Not right:` and the person's words. Anything
        else typed is a Reply."""
        agent_common.person_only(caller, "edit the board", "§4.4", self._graph())
        root, want = self._board_root(board)
        self._board_served(root)
        if action == "reply":
            raise RpcError("a reply on a board line is board_reply, which says where it went (design §4.4)")
        if action == "add":
            return await self._board_add(root, want, text, due, entry, caller)
        if line is None and not key:
            raise RpcError(f"a board {action or 'edit'} names the item's line or its id (design §4.4)")
        try:
            said = self._board_answer(action, answer, answers)
            done = await asyncio.to_thread(
                board_mod.write_back, root, line, text, action, due, answer=said, key=str(key or "")
            )
        except board_mod.Refused as e:
            raise RpcError(str(e)) from None
        log.info("board %s: %s", root, done["message"])
        await self._reread_board(root)
        return {
            "board": str(want),
            "line": done.get("line", line),
            "action": action,
            "due": due,
            **({"answer": said} if said else {}),
            **done,
        }

    @staticmethod
    def _board_answer(action: str, answer: Any, answers: Any) -> str:
        """The answer a `decide` writes, or "" for every other edit: one of the item's `answers`
        word for word, or `Not right: <what>` where the pair's second answer is among them
        (design §4.4 *Decide*) — refused otherwise, since any other typed answer is a Reply."""
        if action != "decide":
            return ""
        offered = [" ".join(str(a).split()) for a in answers] if isinstance(answers, list) else []
        said = " ".join(str(answer or "").split())
        # an offered answer word for word comes first, so an item's own complete *Not right: wrong
        # repo* is an answer like any other; the pair's second answer is a form, `Not right: <what>`,
        # whose slot is the person's words, and pressed as written — or filled with a slot — it says
        # nothing (ledgerboard's reading of the form, TD-585)
        if said and said in offered and not ledgerboard.is_not_right_form(said):
            return said
        try:
            filled = ledgerboard.fill_not_right(said, offered)
        except ledgerboard.Refused as e:
            raise board_mod.Refused(str(e)) from None
        if filled:
            return filled
        raise board_mod.Refused(
            "a decide records one of the item's own answers, word for word: anything else is a Reply (design §4.4)"
        )

    @staticmethod
    def _board_root(board: str) -> tuple[Path, Path]:
        """The checkout whose board `board` is, among those this host's repos registry names, and
        the board's resolved path; refused for any other file."""
        want = Path(board).resolve()
        roots = [Path(r) for r in hosts.local_host().repos()]
        root = next((r for r in roots if (r / workorders.board_rel(r)).resolve() == want), None)
        if root is None:
            raise RpcError(f"{board} is not the board of a repo this host knows (its repos registry)")
        return root, want

    def _board_served(self, root: Path) -> None:
        """Refuse a write-back to an unserved repo's board (§5 *The seams*, TD-1011), naming its lack."""
        if lacks := seams_mod.unserved(self._repos.get(str(root))):
            raise RpcError(f"{root.name} is {lacks[0]}; the home writes nothing to its board until it is cured")

    async def rpc_entry_add(
        self,
        repo: str = "",
        type: str = "",
        text: str = "",
        teams: list[dict[str, str]] | None = None,
        draft: str = "",
        team: str = "",
        priority: str = "",
        caller: Any = None,
    ) -> dict[str, Any]:
        """**Hand to the techlead** and `ao td add` (design §4.10 *An entry handed to a seat*, §4.9
        *Add an entry to the ledger*; TD-218 slice 2): the person's words as an `ask` from the
        person to a techlead seat of the repo, carrying `entry: {repo, type, team, priority}` and marked
        `handed`, with **no bound**: it never lapses, and ends by its outcome or the person's
        Dismiss alone. A person's own, refused to every session as `board_edit` is, and served at
        the home. The host agent does not read `org.yml`, so the caller hands it the teams that
        service the repo, in the order a blank pick takes them (the ledger's `Team` vocabulary,
        else definition order), each `{team, seat}` — `seat` the id the team's techlead takes, or
        empty where the team defines none — as `board_reply`'s `refs` come from the reader. `team`,
        the form's **Team** pick or `--team` (TD-730, TD-764), hands to that team's seat and is
        `entry.team`; blank, the first team with a seat takes it and `entry.team` is empty. `priority`,
        the form's **Priority** pick or `--priority` (TD-851), is `entry.priority`, `medium` when absent.
        Refused in words: no such repo, no team services it, a picked team that does not, no techlead
        seat to hand to, an unknown type or priority, empty text. Returns
        `{id, to, team, repo, type, priority, read_when}`, `team` the team handed to.
        `draft`, where the form attached files (§4.4 *The Add entry form's draft*, TD-630): refused
        before the send unless it is this host's and unclaimed, then claimed for the ask
        (`claimed.json` `{by: hand:<its id>, at}`) and carried in the envelope beside `entry`.
        A session's call, for another repo only, is its own `ask` to that repo's question seat
        (`_entry_request`, TD-995)."""
        me = self._entry_session(caller, repo, draft)
        if me is not None:
            return await self._entry_request(me, repo, type, text, team, priority)
        want = str(repo or "").strip()
        roots = hosts.local_host().repos()
        found = [r for r in roots if want and (want in (Path(r).name, r) or Path(r).resolve() == Path(want).resolve())]
        if not found:
            raise RpcError(f"no registered repo is {want!r} (the home's repos registry lists {len(roots)})")
        name = Path(found[0]).name
        kind = str(type or "").strip().lower()
        if kind not in ENTRY_TYPES:
            raise RpcError(f"an entry is {' or '.join(ENTRY_TYPES)}, not {type!r} (cadence §2.11)")
        rank = str(priority or "").strip().lower() or "medium"
        if rank not in ENTRY_PRIORITIES:
            raise RpcError(f"an entry's priority is {', '.join(ENTRY_PRIORITIES)}, not {priority!r} (design §4.10)")
        words = str(text or "").strip()
        if not words:
            raise RpcError("the entry has no words: say what it is — a title is enough")
        servicing = [t for t in teams or () if isinstance(t, dict) and str(t.get("team") or "").strip()]
        if not servicing:
            raise RpcError(f"no team services {name}: there is no techlead seat to hand it to (design §4.10)")
        pick = str(team or "").strip()
        if pick:
            to = next((t for t in servicing if str(t["team"]).strip().casefold() == pick.casefold()), None)
            if to is None:
                names = ", ".join(str(t["team"]).strip() for t in servicing)
                raise RpcError(f"{pick} does not service {name}: its teams are {names} (design §4.10)")
            pick = str(to["team"]).strip()
        else:  # a blank pick: the first team with a techlead seat, in the order the caller gives them
            to = next((t for t in servicing if str(t.get("seat") or "").strip()), servicing[0])
        team = str(to["team"]).strip()
        seat = str(to.get("seat") or "").strip()
        if not seat:
            raise RpcError(f"{team} has no techlead seat: there is nobody to hand the entry to (design §4.9b)")
        folder = await asyncio.to_thread(agent_common.draft_folder, draft, "entry_add") if draft else None
        sent = await self._msg(PERSON, words, [seat], "ask", None, None, None, None)
        mid = (sent.get("entry") or {}).get("id")
        if not mid:
            raise RpcError(f"the entry was not delivered to {seat}")
        # a seat closed and started again under its name is followed to the record that took it (review of #764)
        seat = next(iter(sent.get("delivered") or ()), seat)
        # the debt, the envelope's fields and no bound: an entry never lapses (§4.10)
        entry = {"repo": name, "type": kind, "team": pick, "priority": rank}
        self._mark(mid, handed=True, entry=entry, bound=None, draft=draft or None)
        if folder is not None:  # the form's files are the ask's, kept `runs_keep_days` from now (§4.4, TD-630)
            try:
                await asyncio.to_thread(agent_common.claim_draft, folder, f"hand:{mid}", datetime.now(UTC))
            except (OSError, RpcError) as e:  # the ask is sent: it stands, the draft unclaimed
                log.warning("entry_add %s: could not claim %s: %s", mid, folder.name, e)
        await self._push_changes()
        log.info("entry_add: %s handed to %s (%s, %s)", mid, seat, name, kind)
        return {
            "id": mid,
            "to": seat,
            "team": team,
            "repo": name,
            "type": kind,
            "priority": rank,
            "read_when": self._entry_read_when(seat),
        }

    def _entry_session(self, caller: Any, repo: Any, draft: Any) -> Session | None:
        """Who calls `entry_add` (design §4.10 *An entry handed to a seat*, §4.7 *Entries*): None for
        the person, the person's own shell included — the handed entry; the caller's record for a
        session naming a repo, which `_entry_request` serves only for another repo than its own. Any
        other session is refused as a person's own act, and a session's call carrying a draft in words."""
        graph = self._graph()
        if mail.as_person(caller, graph):
            return None
        me = graph.get(str(caller))  # as `msg` reads its sender: a forwarded caller is `id@host` already
        if me is None or not str(repo or "").strip():
            agent_common.person_only(caller, ENTRY_ACT, "§4.9 *Add an entry to the ledger*", graph)
        if draft:
            raise RpcError(
                f"{caller} cannot attach a draft: a draft folder is the person's form's (design §4.7 *Entries*)"
            )
        return me

    async def _entry_request(
        self, me: Session, repo: str, type: str, text: str, team: str, priority: str
    ) -> dict[str, Any]:
        """A session's ledger request for another repo (design §4.7 *Entries*, §4.10 *An entry handed
        to a seat*; TD-995, TD-1000 slice 3): its own `ask` to the repo's question seat, resolved from
        the records as `ao msg --repo` is (`team` choosing), through the same gate as `msg` — so the
        open-question limit and every depth bound hold — carrying `entry` and **not** `handed`, with
        no bound: the seat replies once its PR is merged, and the open `ask` holds it on call. The
        caller's own repo — the seat record's `repo` is the caller's, on the same host — is refused
        as the person's own act is: a session writes its own entry on its branch."""
        kind = str(type or "").strip().lower()
        if kind not in ENTRY_TYPES:
            raise RpcError(f"an entry is {' or '.join(ENTRY_TYPES)}, not {type!r} (cadence §2.11)")
        rank = str(priority or "").strip().lower() or "medium"
        if rank not in ENTRY_PRIORITIES:
            raise RpcError(f"an entry's priority is {', '.join(ENTRY_PRIORITIES)}, not {priority!r} (design §4.10)")
        words = str(text or "").strip()
        if not words:
            raise RpcError("the entry has no words: say what it is — a title is enough")
        own = me.repo and os.path.normpath(me.repo)
        try:
            seat = await self._question_seat(team=team, repo=repo)
        except RpcError:
            # a repo of its own name that resolves to no one seat is its own first: the branch is the answer
            if own and Path(own).name == str(repo).strip():
                agent_common.person_only(me.id, ENTRY_ACT, "§4.9 *Add an entry to the ledger*", {})
            raise
        if own and os.path.normpath(seat.repo or "") == own and (seat.host or self.host) == (me.host or self.host):
            agent_common.person_only(me.id, ENTRY_ACT, "§4.9 *Add an entry to the ledger*", {})
        sender = self._address(me)
        sent = await self._msg(sender, words, [self._address(seat)], "ask", None, None, None, None)
        mid = (sent.get("entry") or {}).get("id")
        if not mid:
            raise RpcError(f"the entry request was not delivered to {self._address(seat)}")
        to = next(iter(sent.get("delivered") or ()), self._address(seat))
        name = Path(str(seat.repo)).name
        self._mark(
            mid, entry={"repo": name, "type": kind, "team": str(team or "").strip(), "priority": rank}, bound=None
        )
        await self._push_changes()
        log.info("entry_add: %s asked %s for an entry in %s (%s)", sender, to, name, kind)
        return {
            "id": mid,
            "to": to,
            "team": seat.team,
            "repo": name,
            "type": kind,
            "priority": rank,
            "read_when": self._entry_read_when(to),
        }

    def _entry_read_when(self, seat: str) -> str:
        """*When it is read* for a handed entry (§4.10): an `ask`'s sentence without a bound."""
        s = self._graph().get(self._addr(seat))
        down = s is not None and s.host != self.host and not (self.links.get(s.host) or {}).get("up")
        rings = s is not None and getattr(adapters.get(s.adapter), "composer", None) is not None
        # a modal limit has no reset to name (§4.3, TD-944): read off a record of this host alone
        modal = s is not None and s.host == self.host and agent_common.limit_is_modal(s, adapters.get(s.adapter))
        return mail.read_when(
            s, "ask", datetime.now(UTC), seat=s is None, unreachable=down, rings=rings, lapses=False, modal_limit=modal
        )

    async def rpc_board_reply(
        self,
        board: str,
        line: int | None = None,
        text: str = "",
        reply: str = "",
        refs: list[str] | None = None,
        key: str = "",
        caller: Any = None,
    ) -> dict[str, Any]:
        """**Reply** on a board row (design §4.4 *Board write-back*, §4.5a *Due strip / Inbox board
        row → Reply*; TD-142 slice 1): the person's words appended to the item's own line as
        ` — <name>, <date>: <reply>` and committed as ledgerboard's
        `shiftlead: reply <head> (session <name>)`,
        refused as `board_edit` refuses, and found by `key` as it finds one. The line stays open and
        counted: a reply is not Done.

        Then the mail half (TD-142 slice 2): each live record holding an unexpired declared lease
        on one of the line's `refs` (the reader's, handed in by the page) gets one `note` from the
        person, `about` that reference and marked `handed`, so it owes an outcome (§4.10 *A board
        reply owes an outcome too*). Nobody holding one is mailed nothing. The file half is
        written first; a refused send is said in `note` and `mail_refused`, never raised, since
        the line is committed and a second press would write it twice. `sent` is `[{session, id,
        ref}]`, `session` the holder's name."""
        agent_common.person_only(caller, "reply on the board", "§4.4", self._graph())
        root, want = self._board_root(board)
        self._board_served(root)
        if line is None and not key:
            raise RpcError("a board reply names the item's line or its id (design §4.4)")
        try:
            try:
                at: int | None = int(line) if line is not None else None
            except (TypeError, ValueError):
                if not key:
                    raise
                at = None  # a line it cannot read, and the line's id: found by the id
            done = await asyncio.to_thread(
                board_mod.write_back, root, at, text, "reply", None, reply=reply, key=str(key or "")
            )
        except (TypeError, ValueError):
            raise RpcError("a board reply names the item's line (design §4.4)") from None
        except board_mod.Refused as e:
            raise RpcError(str(e)) from None
        log.info("board %s: %s", root, done["message"])
        await self._reread_board(root)
        text = str(done.get("text") or text)  # the line found, by its id where the press named one
        head = ledgerboard.bold_head(text) or " ".join(text.split())
        by = await asyncio.to_thread(board_mod.author, root)
        # the mail half and the trail line are the home's, served there with the same words
        sent, refused = await self._board_reply_mail(head, by, reply, refs, root.name)
        note = reply_note(sent, refused)
        return {
            "board": str(want),
            "line": done.get("line", at),
            "action": "reply",
            **done,
            "sent": sent,
            "note": note,
            **({"mail_refused": refused} if refused else {}),
        }

    async def _board_reply_mail(
        self, head: str, by: str, reply: str, refs: list[str] | None, repo: str
    ) -> tuple[list[dict[str, str]], list[str]]:
        """The mail half where it is served (§4.4a): the mailbox, the lease records, the `handed`
        mark and the trail are the home's, so a node that wrote the board hands this half to the
        home as `board_reply_hand` — with no refs too, for the trail line (§4.5a) — and mails
        nobody while the link is down, saying so when there was someone to mail. The file half
        stays where the repos registry holds the repo (§4.4)."""
        if self.mode == "home":
            got = await self.rpc_board_reply_hand(head=head, by=by, reply=reply, refs=refs, repo=repo)
            return got["sent"], got["refused"]
        if not self.home_reachable():
            if not board_refs(refs):
                return [], []
            return [], [f"mail is the home's: {self.home} (home) is unreachable from {self.host}"]
        params = {"head": head, "by": by, "reply": reply, "refs": refs, "repo": repo}
        out = await self._forward(0, "board_reply_hand", params, None)
        if "error" in out:
            if not board_refs(refs):  # nobody to mail: only the trail line was lost (review of #1043)
                log.info("board reply: the trail line was not written at %s: %s", self.home, out["error"])
                return [], []
            return [], [f"mail is the home's: {out['error']}"]
        got = out.get("result") or {}
        return list(got.get("sent") or ()), list(got.get("refused") or ())

    async def rpc_board_reply_hand(
        self,
        head: str = "",
        by: str = "",
        reply: str = "",
        refs: list[str] | None = None,
        repo: str = "",
        caller: Any = None,
    ) -> dict[str, Any]:
        """A board reply's mail half (§4.5a *Inbox board row → Reply*, TD-142 slice 2), served at
        the home (`modes.HOME_EDITS`): one `note` from the person, `about` the ref and marked
        `handed`, to each live lease holder on the line's `refs` — a holder of two refs mailed
        once, about the first. The person's alone, as `board_reply` is; `board_reply` calls it
        after its commit, a node's over the link. Returns `{sent: [{session, id, ref}], refused:
        ["<name> (holds <ref>): <why>"]}`, a refused send said, never raised. With `repo` (the
        board's checkout's name) it also writes the trail line, in the result's words (`reply_note`)."""
        agent_common.person_only(caller, "reply on the board", "§4.4", self._graph())
        head = " ".join(str(head or "").split())
        if len(head) > BOARD_HEAD_CHARS:
            head = head[: BOARD_HEAD_CHARS - 1].rstrip() + "…"
        words = " ".join(str(reply or "").split())
        body = f"board: {head}\n\n{by}: {words}"
        if len(body.encode()) > mail.TEXT_CAP:
            body = body.encode()[: mail.TEXT_CAP - 3].decode(errors="ignore") + "…"
        sent: list[dict[str, str]] = []
        refused: list[str] = []
        seen: set[str] = set()
        for ref in board_refs(refs):
            for addr in self._lease_holders(ref):
                if addr in seen:
                    continue
                seen.add(addr)
                r = self._graph().get(addr)
                name = (r.name if r is not None else "") or addr
                try:
                    got = await self._msg(PERSON, body, [addr], "note", ref, None, None, None)
                except RpcError as e:
                    refused.append(f"{name} (holds {ref}): {e}")
                    continue
                if mid := (got.get("entry") or {}).get("id"):
                    self._mark(mid, handed=True)  # work the person handed on: it owes an outcome (§4.10)
                # a seat started again under its name is followed to the record that took it (review of #764)
                to = next(iter(got.get("delivered") or ()), addr)
                r = self._graph().get(to)
                sent.append({"session": (r.name if r is not None else "") or name, "id": to, "ref": ref})
        if sent:
            await self._push_changes()
        if repo:
            self._trail_reply(repo, head, by, words, reply_note(sent, refused))
        return {"sent": sent, "refused": refused}

    async def _board_add(
        self, root: Path, board: Path, text: str, due: str | None, entry: str | None, caller: Any
    ) -> dict[str, Any]:
        """`board_edit` with `action: add` (above): the entry checked, the line written and
        committed, then the entry dismissed. The sender named on the line is the entry's session
        by name and host, `n/a` for the person or a `system` note."""
        if not entry:
            raise RpcError("Put on the board names the Inbox entry it comes from (design §4.5a)")
        # One press per entry at a time: a retried request must not write the line twice. Taken
        # before the first await, so the check and the mark are one step on the loop.
        if entry in self._board_adding:
            raise RpcError(f"{entry} is already being put on the board")
        self._board_adding.add(entry)
        try:
            return await self._board_add_one(root, board, text, due, entry, caller)
        finally:
            self._board_adding.discard(entry)

    async def _board_add_one(
        self, root: Path, board: Path, text: str, due: str | None, entry: str, caller: Any
    ) -> dict[str, Any]:
        mail_entry = next((e for e in self.person_inbox if e.id == entry), None)
        trail_row = next((t for t in self.trail if t.get("id") == entry), None)
        if mail_entry is None and trail_row is None:
            raise RpcError(f"the person inbox holds no entry {entry}")
        if mail_entry is not None and mail_entry.open:
            raise RpcError(
                f"{entry} is an open {mail_entry.kind}: a question waiting on you is answered, declined or "
                "snoozed — Put on the board is for FYI rows (design §4.5a)"
            )
        sid = mail_entry.from_ if mail_entry is not None else str(trail_row.get("sid") or "")
        rec = self._graph().get(sid) if sid else None
        name = rec.name if rec else (str(trail_row.get("name") or "") if trail_row else "") or None
        if mail_entry is not None and mail_entry.from_ in (PERSON, mail.SYSTEM):
            name = None
        host = (rec.host if rec else "") or self.host
        context = mail_entry.about if mail_entry is not None else None
        try:
            done = await asyncio.to_thread(
                board_mod.add, root, text, str(due or ""), session=name, host=host, context=context
            )
        except board_mod.Refused as e:
            raise RpcError(str(e)) from None
        log.info("board %s: %s", root, done["message"])
        await self._reread_board(root)
        out: dict[str, Any] = {"board": str(board), "action": "add", "due": due, **done}
        try:
            out["dismissed"] = (await self.rpc_inbox_dismiss(msg=[entry], caller=caller))["dismissed"]
        except RpcError as e:
            # The line is committed, so the press succeeded; the row staying is said, not raised, so
            # a second press is not taken for a first (review of PR #578).
            out["dismissed"], out["dismiss_refused"] = [], str(e)
        await self._push_changes()
        return out

    def _lease_holders(self, ref: str) -> list[str]:
        """Every live record with an unexpired declared lease on `ref` (design §4.8, `LEASE_TTL`),
        by graph address — who still holds the work a question is about."""
        now = datetime.now(UTC)
        out = []
        for addr, r in self._graph().items():
            if r.state in ("exited", "closed", "scheduled"):
                continue
            for p in r.progress:
                if p.ref == ref and p.status == "claimed" and p.source == "declared":
                    try:
                        fresh = now - _parse(p.at) < LEASE_TTL
                    except ValueError:
                        fresh = False
                    if fresh and addr not in out:
                        out.append(addr)
        return out

    async def _answer_orphan(self, e: MailEntry, answer: str, reason: str, picked: int | None = None) -> dict[str, Any]:
        """The person's answer to an **orphaned** question (design §4.10 *A question about a
        reference outlives its asker*, TD-216): Reply, a suggested answer or *Go with it*. Two
        things, in order. **The board**: one line at the top of the open items of the asker's
        repo's board — the question's first paragraph and the answer — by the write-back's second
        add (§4.4); a refused write refuses the press and touches nothing. **The holders**: a
        `note` from the person, `about` the reference and marked `handed`, to every live record
        with a lease on it, which owes an outcome as a handed board reply does — and to **the closed
        asker's own record** (TD-271), where it waits for the record the name's next create puts
        there, which keeps the mail; with neither (the asker forgotten, nobody holding), nothing is
        mailed and nothing is owed. Then the entry closes `replied` or `go_with_it`. One press per
        entry at a time, as *Put on the board*."""
        if not e.open:
            raise RpcError(f"{e.id} is already closed ({e.closed_reason})")
        if e.id in self._board_adding:
            raise RpcError(f"{e.id} is already being answered")
        self._board_adding.add(e.id)
        try:
            return await self._answer_orphan_one(e, answer, reason, picked)
        finally:
            self._board_adding.discard(e.id)

    async def _answer_orphan_one(self, e: MailEntry, answer: str, reason: str, picked: int | None) -> dict[str, Any]:
        o = dict(e.orphaned or {})
        repo, ref = str(o.get("repo") or ""), str(o.get("ref") or e.about or "")
        if not repo:
            raise RpcError(
                f"{e.id}'s asker had no repo, so there is no board to write your answer on: Delete declines it "
                "(design §4.10)"
            )
        root, board = self._board_root(str(Path(repo) / workorders.board_rel(repo)))
        first = " ".join(e.text.strip().split("\n\n", 1)[0].split())
        today = datetime.now().date().isoformat()
        try:
            done = await asyncio.to_thread(
                board_mod.add,
                root,
                first,
                today,
                session=str(o.get("name") or "") or None,
                host=str(o.get("host") or "") or self.host,
                context=e.about,
                answer=answer,
            )
        except board_mod.Refused as err:
            raise RpcError(str(err)) from None
        log.info("board %s: %s", root, done["message"])
        holders = self._lease_holders(ref) if ref else []
        # the asker's own name is a holder too (TD-271): its closed record keeps the note for the
        # next create under the name. A forgotten one is gone, one a holder already is gets one, and
        # a superseded one was never orphaned (its questions moved with the conversation)
        r = self._graph().get(e.from_)
        asker = e.from_ if r is not None and not r.superseded_by and e.from_ not in holders else ""
        how = str(o.get("how") or "closed")
        text = (
            f"{answer}\n\nThe person's answer to {e.id}, which {o.get('name') or e.from_} asked about {ref} "
            f'before its session was {how}: "{first[:600]}". It is on {root.name}\'s board too — close that line '
            "when you have carried it out."
        )
        if len(text.encode()) > mail.TEXT_CAP:  # the answer alone is within the cap; the quote is not counted
            text = text.encode()[: mail.TEXT_CAP - 3].decode(errors="ignore") + "…"

        async def hand(to: list[str]) -> tuple[list[str], str]:
            """One `handed` note; a refusal is said beside the press, never raised: the line is
            committed, so a second press would write it twice (as `_board_add_one`)."""
            try:
                got = await self._msg(PERSON, text, to, "note", ref, None, None, None)
            except RpcError as err:
                return [], str(err)
            if mid := (got.get("entry") or {}).get("id"):
                self._mark(mid, handed=True)  # it owes an outcome, as a handed board reply does (§4.10)
            return list(got.get("delivered") or to), ""

        # two sends, so the asker's mailbox filled to depth never keeps the note from the holders
        sent, mail_refused = await hand(holders) if holders else ([], "")
        left, asker_refused = await hand([asker]) if asker else ([], "")
        at = now_iso()
        self._close_entry(e.id, reason, at)
        self._question_end(e, "answered")  # work for the asker's team, if it wound down (§6 rule 8)
        # Nobody is left to report what became of it: the entry's own debt is settled here, and the
        # handed note carries it on to whoever holds the work (§4.10 *Outcomes*).
        settled = "answered on the board" + (f", sent to {', '.join(sent)}" if sent else "")
        toast = "written on the board" + (f" · sent to {', '.join(sent)} (holds {ref})" if sent else "")
        if mail_refused:
            settled += f"; not sent to {', '.join(holders)}: {mail_refused}"
            toast += f" · not sent to {', '.join(holders)} (holds {ref}): {mail_refused}"
        name = o.get("name") or asker
        if left:
            settled += f", left in {name}'s mailbox"
            toast += f" · left in {name}'s mailbox for its next run"
        elif asker_refused:
            settled += f"; not left in {name}'s mailbox: {asker_refused}"
            toast += f" · not left in {name}'s mailbox: {asker_refused}"
        self._mark(e.id, outcome={"state": "asker_gone", "text": settled, "at": at, "by": ""}, answer=picked)
        await self._push_changes()
        return {
            "id": PERSON,
            "msg": e.id,
            "closed": e.id,
            "closed_reason": reason,
            "board": str(board),
            **done,
            "sent": sent,
            "delivered": sent,
            **({"asker": asker} if left else {}),
            "note": toast,
            **({"mail_refused": mail_refused} if mail_refused else {}),
            **({"asker_refused": asker_refused} if asker_refused else {}),
        }

    async def rpc_ledger_decide(
        self,
        repo: str,
        id: str,
        words: str = "",
        answer: int | None = None,
        go: bool = False,
        road: str = "",
        caller: Any = None,
    ) -> dict[str, Any]:
        """The person's answer to a ledger entry that waits on them (design §4.5 screen 6 *The ledger's
        entries that wait on you*, §4.5a *Inbox row: ledger entry*, TD-565): one of its answers by
        index (`answer`), its default (`go`, **Go with it**) or the Reply's `words`, written as one
        decided line at the top of the repo's open board items by the second add's road (§4.4 *Board
        write-back*) — `Context:` the id, committed as `shiftlead: append <title> (session n/a)` — so it
        is a work order at once. `repo` is the checkout the home's repo facts key it by; the entry is
        read from that reading, and refused when it no longer sorts *for you* or an open decided line
        already names it. The ledger itself is never written. The repo's work orders are read again
        once the line lands, so the row leaves on the next poll. `road` is **Done…** (`done`) or **Back to
        design…** (`design`) on any open row (`_ledger_road`, TD-905). A person's session passes for a road
        alone (`mail.PERSON_SESSION`, §4.8 *A person's session passes two of them*, TD-1117): the answer with
        no road was put to the person, and stays theirs."""
        agent_common.person_only(
            caller, "answer a ledger entry", "§4.5", self._graph(), session_ok=bool(str(road or ""))
        )
        road = str(road or "")
        root = next((r for r in self._repos if r == repo or str(Path(r).resolve()) == str(Path(repo).resolve())), None)
        if root is None:
            raise RpcError(f"{repo} is not a repo this home reads (its repos registry)")
        view = self._repos.get(root) or {}
        name = str(view.get("name") or Path(root).name)
        if road:
            return await self._ledger_road(root, name, view, str(id or "").strip().upper(), road, words, caller)
        e = next(
            (
                x
                for x in ((view.get("ledger") or {}).get("entries") or [])
                if isinstance(x, dict) and x.get("id") == id and x.get("for_page") == "for-you"
            ),
            None,
        )
        if e is None:
            raise RpcError(f"{id} no longer waits on you in {name}'s ledger: reload the Inbox")
        if any(
            id in (o.get("refs") or []) or f"{name}#{id}" in (o.get("refs") or [])
            for o in ((view.get("work_orders") or {}).get("orders") or [])
            if isinstance(o, dict)
        ):
            raise RpcError(f"{id} is already decided on {name}'s board: its session acts on it")
        answers = [str(a) for a in e.get("answers") or () if str(a).strip()]
        d = e.get("default")
        default = d if isinstance(d, int) and not isinstance(d, bool) and 0 <= d < len(answers) else None
        if go:
            if default is None:
                raise RpcError(f"{id} marks no answer (default): pick one of its answers, or Reply")
            said = answers[default]
        elif answer is not None:
            if isinstance(answer, bool) or not isinstance(answer, int) or not 0 <= answer < len(answers):
                raise RpcError(f"{id} has no answer {answer!r}: reload the Inbox")
            said = answers[answer]
        else:
            said = str(words or "")
        key = f"ledger:{root}:{id}"
        if key in self._board_adding:
            raise RpcError(f"{id} is already being decided")
        self._board_adding.add(key)
        try:
            today = datetime.now().date().isoformat()
            try:
                line = board_mod.decided_line(str(e.get("title") or ""), id, answers, default, said, today)
                done = await asyncio.to_thread(board_mod.add_decided, root, line)
            except board_mod.Refused as err:
                raise RpcError(str(err)) from None
            log.info("board %s: %s", root, done["message"])
            # held through the re-read: a second press in between would pass the decided check on
            # the reading from before the line (review of #1542)
            await self._reread_board(root)
        finally:
            self._board_adding.discard(key)
        return {"repo": root, "id": id, "decided": " ".join(said.split()), **done}

    async def _ledger_road(
        self, root: str, name: str, view: dict[str, Any], id: str, road: str, words: str, caller: Any
    ) -> dict[str, Any]:
        """**Done…** and **Back to design…** on any open ledger row (design §4.5 screen 12 *any open row*,
        §4.4 *Hold*, TD-905): the Reply road with the fixed words *done — <words>* or *back to design —
        <words>* — one decided board line, `Context:` the id, the session's work order. First the entry's
        unattended holders and its PR's reader are told (`td_hold`'s drop notice), and the whole press is
        refused where one could not be; then a person's hold on it is cleared; then the line is written.
        Done is refused on *yours to do* (that row's own **Done** sends *done*), Back to design on a row that
        is not *pickable*, *live check* or blocked by an open id. Where the repo has no servicing team, or no
        stage's lane takes `design-first`, the page refuses before it calls (the home reads no `org.yml`)."""
        if road not in LEDGER_ROADS:
            raise RpcError(f"a ledger row's road is {' or '.join(LEDGER_ROADS)}, not {road!r}")
        listed = [x for x in ((view.get("ledger") or {}).get("entries") or []) if isinstance(x, dict)]
        e = next((x for x in listed if x.get("id") == id), None)
        open_ids = {str(x.get("id")) for x in listed}
        if e is None:
            raise RpcError(f"{id} is not an open entry of {name}'s ledger as the home last read it: reload the page")
        page = str(e.get("for_page") or "")
        if road == "done" and str(e.get("owner") or "").lower() == ledger_mod.PERSON_OWNER:
            raise RpcError(f"{id} is yours to do: its own Done says what was done")
        graph = self._graph()
        mine = mail.as_person(caller, graph)
        if road == "done" and not mine and ledger_mod.decided_by(e, ledger_mod.PERSON_OWNER):
            # Done here would close the person's question unanswered (§4.8 *A person's session passes two of them*)
            raise RpcError(f"{id} waits on the person's decision: they answer it on the Inbox or the Queue")
        if road == "design" and not (
            page in ("pickable", "live-check")
            # blocked by an id still open, or with an open part: the page's `blocked_open`, asked again here
            # (review of #2162, TD-1130)
            or (
                page == "blocked"
                and (any(str(b) in open_ids for b in e.get("blocked_by") or ()) or e.get("parts_open"))
            )
        ):
            raise RpcError(f"{id} is {page or 'of no page kind'}: Back to design is on a pickable, live check or "
                           "id-blocked entry (design §4.5 screen 12)")  # fmt: skip
        if any(
            id in (o.get("refs") or []) or f"{name}#{id}" in (o.get("refs") or [])
            for o in ((view.get("work_orders") or {}).get("orders") or [])
            if isinstance(o, dict)
        ):
            raise RpcError(f"{id} is already decided on {name}'s board: its session acts on it")
        said = LEDGER_ROADS[road] + (f" — {w}" if (w := " ".join(str(words or "").split())) else "")
        key = f"ledger:{root}:{id}"
        if key in self._board_adding:
            raise RpcError(f"{id} is already being decided")
        today = datetime.now().date().isoformat()
        try:  # the line is made before anyone is told, so words the board refuses refuse the press whole
            line = board_mod.decided_line(str(e.get("title") or ""), id, [], None, said, today)
        except board_mod.Refused as err:
            raise RpcError(str(err)) from None
        if not str(view.get("remote") or ""):
            raise RpcError(f"{name}'s origin is not read yet: its clock is keyed by it, so ask again in a minute")
        rec = None if mine else graph.get(str(caller))
        session = "" if mine else rec.name if rec is not None else str(caller)  # the commit's: *n/a* for the person
        who = "the person" if mine else self._presser_words(str(caller))
        self._board_adding.add(key)
        try:
            tell = (f"is closed by {who}" if road == "done" else "goes back to design") + (f" — {w}" if w else "")
            told, readers, untold = await self._hold_notice(id, tell)
            if untold:
                raise RpcError(
                    f"nothing was written: {'; '.join(untold)} — a worker would run on against "
                    f"{id} (design §4.4 *Hold*)"
                )
            await self._clear_hold(root, e, "person")  # any hold, whatever the reading says: the press decides it
            try:
                done = await asyncio.to_thread(board_mod.add_decided, root, line, session=session)
            except board_mod.Refused as err:
                raise RpcError(str(err)) from None
            log.info("board %s: %s", root, done["message"])
            await self._reread_board(root)
        finally:
            self._board_adding.discard(key)
        return {"repo": root, "id": id, "decided": said, "told": told, "readers": readers, **done}

    async def _reread_board(self, root: str | Path) -> None:
        """The repo's board read again at once after a write-back the host agent made (§4.4 *Each
        reading has one owner*, *The boards*, TD-615), so a Snooze, a Done, a Decide, a Reply or an
        add is in the next `repos` push and not a minute later, and a ledger entry answered on the
        board leaves *Later* with it. It reads the write-back's own tree — origin's head, the press
        landed — as the checkout's board read from origin, and fetches where there is no tree. A
        failed read changes nothing: the next reading lists the line. The press is marked, so a
        tick's read that began before it does not put the old board back."""
        root = str(root)
        self._boards_pressed[root] = time.monotonic()
        old = self._repos.get(root)
        if old is None:
            return
        tree = board_mod.tree_dir(Path(root)) / workorders.board_rel(root)
        here = tree if tree.is_file() else None
        try:
            bds, wos = await asyncio.to_thread(self._read_boards, root, old, here is None, False, now_iso(), tree=here)
        except Exception:  # noqa: BLE001 — the line is landed; the reading catches up on its own
            log.exception("re-reading the board of %s failed", root)
            return
        if "error" in bds or root not in self._repos:
            return
        self._repos[root] = {**self._repos[root], "boards": bds, "work_orders": wos}
        # marked again as it lands: a tick's pass that began while this read ran is older too (review of TD-615)
        self._boards_pressed[root] = time.monotonic()
        self.repos_store.save(self._repos)
        await self._broadcast({"event": "repos", "root": root, "repo": self._repo_view(root)})

    async def rpc_inbox_pause(self, msg: str, caller: Any = None) -> dict[str, Any]:
        """**Pause** (design §4.10, TD-069): on a `steer` in the person inbox — *I want to answer
        this; do not go on without me*. `paused_at` stops the bound running (the sweep skips the
        entry outright, whatever `bound` reads), the sender is told by a `system` note that wakes it
        as a person's reply does, so it turns to other work instead of waiting out a clock that has
        stopped, and the entry is counted while paused: a preference has become something a session
        is held on. Only a `steer` can be paused — an `ask` to the person has no clock — and a
        `steer` addressed to a session cannot be: the pause is the person's."""
        e = self._person_entry(msg, caller, "pause")
        if e.kind != "steer":
            raise RpcError(f"only a steer can be paused: {msg} is a {e.kind}, and has no clock to stop (design §4.10)")
        if not e.open:
            raise RpcError(f"{msg} is closed ({e.closed_reason}): there is no clock left to stop (design §4.10)")
        if e.paused_at:
            raise RpcError(f"{msg} is already paused")
        if e.orphaned:  # a pause tells a session to hold, and there is none (§4.5a *orphaned question*: no Pause)
            raise RpcError(f"{msg} is orphaned: its asker is gone, so there is no session to hold (design §4.10)")
        self._mark(msg, paused_at=now_iso())
        self._system_note(e.from_, f"steer {msg} paused by the person: do not take your default yet", wake="person")
        await self._push_changes()
        return {"id": PERSON, "msg": msg, "paused_at": e.paused_at, "bound": e.bound}

    async def rpc_inbox_resume(self, msg: str, caller: Any = None) -> dict[str, Any]:
        """**Resume** (design §4.10, TD-069): moves `bound` later by the time it was held and then
        clears `paused_at`, **in one step**, so the sweep never sees a resumed entry with its old
        bound — what was left is what is left — and the sender is told again. That note is an
        ordinary one: it only says the clock runs again and what is left, so it wakes within the
        wake budget like any `note`."""
        e = self._person_entry(msg, caller, "resume")
        if not e.paused_at:
            raise RpcError(f"{msg} is not paused")
        held = datetime.now(UTC) - _parse(e.paused_at)
        bound = (_parse(e.bound) + held).replace(microsecond=0).isoformat().replace("+00:00", "Z") if e.bound else None
        self._mark(msg, bound=bound, paused_at=None)
        self._system_note(e.from_, f"steer {msg} resumed by the person: the clock runs again, until {bound}")
        await self._push_changes()
        return {"id": PERSON, "msg": msg, "paused_at": None, "bound": bound}

    async def rpc_inbox_go_with_it(self, msg: str, caller: Any = None) -> dict[str, Any]:
        """**Go with it** (design §4.5a **Inbox**, §4.10): closes a `steer` now —
        `closed_reason: go_with_it`, a fixed outcome and not text for the sender to weigh — so the
        sender need not wait out the bound; doing nothing would let it lapse to the same end. The
        sender is told by a `system` note that wakes it as a person's reply does. It closes a
        paused `steer` as it closes a running one."""
        e = self._person_entry(msg, caller, "answer")
        if e.kind != "steer":
            raise RpcError(f"Go with it answers a steer, which carries the default: {msg} is a {e.kind} (§4.10)")
        if not e.open:
            raise RpcError(f"{msg} is already closed ({e.closed_reason})")
        if e.orphaned:  # nobody is left to take the default: it is written down for whoever holds the work
            return await self._answer_orphan(e, f"go with the default: {e.default}", "go_with_it")
        self._close_entry(msg, "go_with_it", now_iso())
        self._system_note(e.from_, f"steer {msg} — the person says: go with your default", wake="person", ends=e)
        await self._push_changes()
        return {"id": PERSON, "msg": msg, "closed_reason": "go_with_it"}

    async def _sweep_mail(self, now: datetime) -> None:
        """Once a tick: an `ask` past its bound expires on every copy and a `steer` past its bound
        **lapses**; an addressee that exited leaves the `ask`s addressed to it pending, a closed one
        expires them — but for a **seat**, which is closed whenever it is empty and keeps them
        pending for its fill (design §4.10 lifecycle, §6 rule 3); read entries past retention are pruned, open asks
        exempt. Two things a `steer` does differently (§4.10 *What a person is asked*): its bound
        runs whatever becomes of the addressee — an exit leaves it no `pending` and a close expires
        nothing, it lapses on time — and while the person has **paused** it the sweep skips it
        outright, whatever `bound` reads. An `ask` to the person carries no bound at all, so nothing
        here ever reaches it."""
        stamp = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self._adopt_orphans()  # before the bounds: an adopted `steer` lapses to its successor on time
        for r in list(self._graph().values()):
            for e in list(r.inbox):
                if not e.open or e.paused_at:
                    continue
                if e.bound and _parse(e.bound) <= now:
                    self._lapse_or_expire(e, stamp)
                elif e.kind == "steer":
                    continue  # the sender goes on: nothing the addressee does closes it early
                elif r.state == "closed" and r.seat is None:
                    self._close_entry(e.id, "expired", stamp)
                elif r.state in ("exited", "closed") and r.id not in e.pending:
                    # a closed seat is an empty one (§6 rule 3): its question waits for the fill as
                    # an exited record's does, however long a ceiling, a gate or a down link holds it
                    self._mark(e.id, pending=r.id)
            for e in list(r.outbox):
                if e.open and not e.paused_at and e.bound and _parse(e.bound) <= now:
                    self._lapse_or_expire(e, stamp)
        for e in list(self.person_inbox):  # a `steer` to the person lapses on its bound; an `ask` has none
            if e.open and not e.paused_at and e.bound and _parse(e.bound) <= now:
                self._lapse_or_expire(e, stamp)
        if self._question_ended:  # rule 8's mark, written by a lapse (§6, TD-274)
            self._question_ended = False
            await self._push_changes()
        if mail.MAIL_RETENTION is None:
            return
        # the trail is kept like read mail: each entry for the retention window from when it ended
        # (design §4.10 *The Inbox is a queue*), so FYI does not grow without bound
        trail = [e for e in self.trail if not _older(e.get("last") or e.get("resolved_at"), now)]
        if len(trail) != len(self.trail):
            self.trail = trail
            self.attention_store.save(self.trail, self.attention_snoozed)
        kept = [e for e in self.person_inbox if self._keep(e, now, inbox=True, person=True)]
        if len(kept) != len(self.person_inbox):
            self.person_inbox = kept
            self.person_store.save(kept)
        for r in self._graph().values():
            dead_since = r.since if r.state in ("exited", "closed") else None
            inbox = [e for e in r.inbox if self._keep(e, now, inbox=True, dead_since=dead_since)]
            outbox = [e for e in r.outbox if self._keep(e, now, inbox=False)]
            if len(inbox) != len(r.inbox) or len(outbox) != len(r.outbox):
                r.inbox, r.outbox = inbox, outbox
                _prune_tallies(r)
                self._save(r)

    def _lapse_or_expire(self, e: MailEntry, stamp: str) -> None:
        """A bound that ran out (design §4.10): a `steer` **lapses** — `closed_reason: lapsed`,
        never `expired_at`, because nothing failed — and the sender is told by a `system` note that
        wakes it **uncharged**, so a spent budget cannot hold it past the bound it set itself. An
        `ask` expires, as it always has.

        **An orphaned `steer` lapses to its default too** (§4.10 *An orphaned `steer` lapses to its
        default*, TD-271): the bound is the person's answer whoever is left to hear it, so the entry
        closes `lapsed` and the note is written into the **closed asker's mailbox**, where the
        record the name's next create puts there finds it. One **adopted** by a successor lapses as
        any does; neither wrote what the note reads, so both name the default. (From TD-213 until
        then the bound was cleared instead; an entry that happened to stays a question with no
        clock, which this sweep never reaches.)"""
        if e.kind == "steer":
            self._close_entry(e.id, "lapsed", stamp)
            text = f"steer {e.id} lapsed: go with your default"
            if e.adopted_at or e.orphaned:
                text = f'steer {e.id} about {e.about} lapsed: the default was "{e.default}"'
            self._system_note(e.from_, text, wake="uncharged", ends=e)
            if e.orphaned:  # nobody is left to act on the default: work for the asker's team (§6 rule 8)
                self._question_end(e, "lapsed")
        else:
            self._close_entry(e.id, "expired", stamp)

    @staticmethod
    def _keep(e: MailEntry, now: datetime, *, inbox: bool, person: bool = False, dead_since: str | None = None) -> bool:
        """Lifecycle stage 3 (design §4.10): a read entry is kept for the retention window from
        `read_at` — or, for an `ask`, from when it closed or expired — and an open `ask` is never
        pruned. The sender's copy runs from `at`, and a sent reply carrying a `source` is kept
        `SOURCED_RETENTION` whatever else is pruned. `person`: the copy is the person inbox's,
        where a question the person answered is listed as owed.

        An unread inbox entry never ages out **while the record lives**. `dead_since` is when its
        record became `exited` or `closed`: the run it was addressed to is over, and an unread
        `note` or `reply` ages out on the same window from then (TD-072, TD-141) — the window, not
        the exit itself, because a resume carries mail forward and a worker resumed inside it still
        gets the note. One written **after** the record ended — a lapse's note or an orphan's answer
        left in a closed asker's mailbox (§4.10, TD-271) — runs from its own arrival instead, or a
        team wound down a day before the bound would lose it at the next sweep. An open `ask`
        or `steer` is untouched (`e.open`, above)."""
        if e.open or e.owes_for(session_inbox=inbox and not person) or mail.MAIL_RETENTION is None:
            # `owes`: a question that was answered and not reported back is kept until it is
            # (design §4.10 *Outcomes*) — the follow-up `--thread` names it, and the person's
            # Inbox lists it under *Waiting on them*, so pruning it would strand both.
            return True
        if not inbox and e.source and _parse(e.at) + mail.SOURCED_RETENTION > now:
            return True  # a sourced reply, in its sender's outbox (§4.9b): what `inbox --sent` reads
        since = e.expired_at or e.closed_at or (e.read_at if inbox else e.at)
        if since is None and inbox and dead_since:
            # from the later of the death and the arrival: a note written to a closed record — a
            # lapse, an orphan's answer (TD-271) — waits its window for the name's next create
            since = max(dead_since, e.at, key=_parse) if e.at else dead_since
        if since is None:
            return True
        return _parse(since) + mail.MAIL_RETENTION > now

    async def rpc_clear_work(self, team: str = "", caller: Any = None) -> dict[str, Any]:
        """Dismiss's half of the **Inbox row: team start** (design §6 rule 8, §4.5a, TD-227): the ids
        of the team's `work_waiting` are added to each named member's `lane_seen`, so those entries
        do not ask again and a later one does, and the mark is removed. A person's own, refused to a
        session as `set_settings` is, and the home's alone (`modes.HOME_EDITS`). `{team, cleared,
        ids}`: `cleared` false when no work was waiting."""
        agent_common.person_only(caller, "clear a team's waiting work", "§6 rule 8", self._graph())
        if self.mode != "home":
            raise RpcError("clear_work runs at the home (design §6 rule 8): this host is a node")
        team = str(team or "").strip()
        if not team:
            raise RpcError("clear_work needs the team whose work to dismiss")
        teams = self._host_rec.get("teams") or {}
        rec = teams.get(team) or {}
        mark = rec.get("work_waiting")
        if not isinstance(mark, dict):
            return {"team": team, "cleared": False, "ids": []}
        named = mark.get("members") if isinstance(mark.get("members"), dict) else {}
        # a question ends once (§6 rule 8 *A question's end is work*, TD-274): its reference is not
        # lane news, and is not written to `lane_seen`
        asked = {(str(q.get("name")), str(q.get("ref"))) for q in mark.get("questions") or [] if isinstance(q, dict)}
        for r in self._graph().values():
            ids = named.get(r.name)
            if r.team != team or r.superseded_by or r.lane_seen is None or not isinstance(ids, list):
                continue
            held = list(r.lane_seen.get("ids") or [])
            if add := [str(i) for i in ids if str(i) not in held and (r.name, str(i)) not in asked]:
                r.lane_seen = {**r.lane_seen, "at": now_iso(), "ids": [*held, *add]}
                self._save(r)
        rec.pop("work_waiting", None)
        if not rec:
            teams.pop(team, None)
        try:
            self.host_store.save(self._host_rec)
        except OSError:
            log.exception("writing the home's host record failed")
        await self._push_changes()
        ids = sorted({str(i) for v in named.values() if isinstance(v, list) for i in v})
        log.info("rule 8: %s's work waiting dismissed by the person: %s", team, ", ".join(ids))
        return {"team": team, "cleared": True, "ids": ids}

    async def rpc_work_start(self, team: str = "", caller: Any = None) -> dict[str, Any]:
        """Start's half of the **Inbox row: team start** for a team that runs on (design §6 rule 8 *A
        member that finished while its team runs on*, §4.5a, TD-466): the members the team's
        `work_waiting` names are replayed, each alone, under the five bounds — rule 8's own start
        (`_work_start`), which reads at the start whether the team is wound down and replays it whole
        if it is. A person's own, and the home's alone (`modes.HOME_EDITS`). `{team, started, ids,
        held}`: `started` false and `held` the mark's `{why, …}` when a bound holds the start back,
        which the page says in the row's words; false with no `held` when no work was waiting. Under
        `on_work: off` the tick writes no mark, so there is nothing for it to start."""
        agent_common.person_only(caller, "start a team's waiting members", "§6 rule 8", self._graph())
        if self.mode != "home":
            raise RpcError("work_start runs at the home (design §6 rule 8): this host is a node")
        team = str(team or "").strip()
        if not team:
            raise RpcError("work_start needs the team whose members to start")
        teams = self._host_rec.setdefault("teams", {})
        rec = teams.get(team) or {}
        mark = rec.get("work_waiting")
        if not isinstance(mark, dict):
            return {"team": team, "started": False, "ids": [], "held": None}
        if mark.get("stopped"):
            raise RpcError(
                f"{team} stopped: rule 8 never starts a stopped team — Start it from its card (design §6 rule 8 "
                "*A team that stopped*)"
            )
        ids = sorted({str(i) for v in (mark.get("members") or {}).values() if isinstance(v, list) for i in v})
        records = [r for r in self._graph().values() if r.team == team]
        conf = settings_mod.teams(settings_mod.load()).get(team) or {}
        new = await self._work_start(team, mark, rec, records, conf, datetime.now(UTC))
        if new is None:
            rec.pop("work_waiting", None)
        else:
            rec["work_waiting"] = new
        teams[team] = rec
        try:
            self.host_store.save(self._host_rec)
        except OSError:
            log.exception("writing the home's host record failed")
        await self._push_changes()
        held = (new or {}).get("held")
        log.info(
            "rule 8: %s's waiting members started by the person: %s%s", team, ", ".join(ids), " (held)" if held else ""
        )
        return {"team": team, "started": new is None, "ids": ids, "held": held}

    async def rpc_clear_mark(
        self, id: str, kind: str = "", pr: int | None = None, caller: Any = None
    ) -> dict[str, Any]:
        """Dismiss's half of the two rows the tick's reads raise (design §4.5a, §6 rules 10 and 11,
        TD-258). `kind: cadence` with `pr` takes `row` off that PR's `checks` entry — the entry
        stays as the record of the read, and a fail read later, at a new head or after a new `done`, is the row again —
        and the row's snooze with it; `kind: held` marks every standing `held_missed` entry
        `dismissed`, kept so that its PR is never read as a crossing again. A person's own,
        refused to a session as `clear_work` is, and the home's alone (`modes.HOME_EDITS`): both
        fields are home-owned, a node's member's too. `{id, kind, cleared}`: `cleared` the PRs
        whose mark went, empty when none stood."""
        agent_common.person_only(caller, "dismiss a mark", "§4.5a", self._graph())
        if self.mode != "home":
            raise RpcError("clear_mark runs at the home (design §6 rules 10 and 11): this host is a node")
        s = self._find(self._addr(id))
        addr = self._address(s)
        if kind == "cadence":
            if isinstance(pr, bool) or not isinstance(pr, int):
                raise RpcError("clear_mark cadence needs the PR whose row to dismiss")
            s.checks, stood = cadence_mod.dismiss(s.checks, pr)
            cleared = [pr] if stood else []
            if self.attention_snoozed.pop(f"{addr}|cadence:{pr}", None) is not None:
                self.attention_store.save(self.trail, self.attention_snoozed)
        elif kind == "held":
            s.held_missed, cleared = held_mod.dismiss(s.held_missed, now_iso())
        else:
            raise RpcError(f"unknown mark {kind!r}; the marks a person dismisses are: cadence, held")
        if cleared:
            self._save(s)
            await self._push_changes()
            log.info("%s: %s row dismissed by the person: %s", addr, kind, ", ".join(f"#{n}" for n in cleared))
        return {"id": addr, "kind": kind, "cleared": cleared}
