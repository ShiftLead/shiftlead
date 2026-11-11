"""The attention trail (TD-108 step 1): design §4.10 *The Inbox is a queue* and TD-079 — how each row ended,
and who ended it — as a mixin `HostAgent` inherits. Moved as written; the state it reads is the agent's.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from datetime import UTC, datetime
from typing import Any

from sessionorc import (
    agent_common,
    hosts,
    mail,
    naming,
)
from sessionorc import queue as queue_mod
from sessionorc.agent_common import (
    TRAIL_FLOOR,
    _alarm_since,
    _alarm_words,
    _clean,
    _ended_by,
    _parse,
)
from sessionorc.models import (
    PERSON,
    Session,
    attention_kind,
    now_iso,
    reference_of,
)


class AttentionMixin:
    # -- the attention trail (design §4.10 *The Inbox is a queue*, TD-079) -------------------------

    def _note_attention(self, now: datetime) -> None:
        """Once a tick: every record's state row, compared with the one it was showing. A row that
        **ended** leaves a trail entry; a row that began is remembered. Nothing here decides what a
        person sees — that is the page's — it only records what went away, because a state row is
        derived and leaves no entry of its own to find afterwards."""
        graph = self._graph()
        for sid, s in list(graph.items()):
            # two slots per record, because the page draws two rows: its state, and its identity
            # alarms (§4.5a **Inbox row: state** / **identity alarm**). One ends without the other.
            for slot, kind, began, what in (
                ("state", attention_kind(s), s.since, (s.pending.text if s.pending else "") or ""),
                ("alarm", "alarm" if s.identity_alarms else "", _alarm_since(s) or s.since, _alarm_words(s)),
            ):
                key = f"{sid}|{slot}"
                was, since, text = self._attention.get(key, ("", "", ""))
                if kind == was:
                    continue
                if was:
                    # what the row *said*, remembered from when it began: by the time it ends the
                    # pending is cleared, and a trail entry with no words is no use to a person
                    self._trail_append(s, was, since, now, text=text, ended=_ended_by(s, slot, was))
                if kind:
                    # `began`, never the old row's: `kind != was` here (the `continue` above), so
                    # this is always a row starting — one that inherited the previous row's start
                    # would misreport how long *it* had been up (review of PR #269)
                    self._attention[key] = (kind, began, what)
                else:
                    self._attention.pop(key, None)
        for key in [x for x in self._attention if x.split("|", 1)[0] not in graph]:
            del self._attention[key]  # a record that is gone left through `_forget`, not here

    def _trail_append(
        self,
        s: Session,
        kind: str,
        since: str,
        now: datetime,
        how: str = "",
        text: str = "",
        ended: str = "",
    ) -> None:
        """One ending, coalesced. A repeat of the same `{sid, kind, how}` inside the retention
        window is one entry carrying a `count` and its first and last time, so a session flapping
        in and out of `stalled?` cannot push the rest of the trail out (the identity alarms' rule,
        §4.8a). A row that lasted under `TRAIL_FLOOR` leaves nothing **unless a person ended it**:
        a permission a policy answered in 200 ms is not news."""
        slot = "alarm" if kind == "alarm" else "state"
        # the address, not the bare id: a node's record is keyed `id@host` everywhere the graph and
        # the attention bookkeeping touch it, and the word the home wrote for it was keyed that way
        who = self._address(s)
        how = how or self._attention_how.pop(f"{who}|{slot}", "") or self._attention_how.get(f"{who}|*", "")
        # A resumed record says so on its own face, so the word is right for a **node's** session
        # too, where the resume ran at the node and this home never saw the act (review of PR #269).
        # `ended` is what the record's own state says ended the row (`_ended_by`): below every word
        # an act wrote, since a resume or a forget also leaves the record closed or exited (TD-088).
        how = how or ("resumed" if s.superseded_by else "") or ended or "resolved"
        stamp = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if not how.endswith("by you") and since:
            with contextlib.suppress(ValueError, TypeError):
                if now - _parse(since) < TRAIL_FLOOR:
                    return
        for e in self.trail:
            if (e.get("sid"), e.get("kind"), e.get("how")) == (who, kind, how):
                e["count"] = int(e.get("count") or 1) + 1
                e["last"] = stamp
                self.attention_store.save(self.trail, self.attention_snoozed)
                return
        doing = text or (s.doing or {}).get("text") or ""
        self.trail.insert(
            0,
            {
                # the entry's own id, which `inbox_dismiss` takes, as mail's is `m-`
                "id": "t-" + secrets.token_hex(6),
                "sid": who,
                "name": s.name,
                "team": s.team or "",
                "kind": kind,
                "text": _clean(str(doing))[: mail.DEFAULT_CAP],
                "since": since,
                "resolved_at": stamp,
                "how": how,
                "count": 1,
                "first": stamp,
                "last": stamp,
            },
        )
        del self.trail[agent_common.TRAIL_KEEP :]
        self.attention_store.save(self.trail, self.attention_snoozed)

    def _trail_reply(self, repo: str, head: str, by: str, reply: str, how: str) -> None:
        """A board **Reply** (§4.5a *Inbox board row → Reply*, TD-142): the trail's one entry that is
        not a record's ending — no `sid`, `kind` *board reply*, `how` the press's own result
        (*written on the board · sent to …*), never coalesced, since each reply is its own words."""
        stamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.trail.insert(
            0,
            {
                "id": "t-" + secrets.token_hex(6),
                "sid": "",
                "name": repo,
                "team": "",
                "kind": "board reply",
                "text": _clean(f"{head} — {by}: {reply}")[: mail.DEFAULT_CAP],
                "since": stamp,
                "resolved_at": stamp,
                "how": how,
                "count": 1,
                "first": stamp,
                "last": stamp,
            },
        )
        del self.trail[agent_common.TRAIL_KEEP :]
        self.attention_store.save(self.trail, self.attention_snoozed)

    def _attention_gone(self, s: Session, how: str) -> None:
        """A record **leaving the graph** — forgotten, or replaced in place by a new session that
        took its name (`_take_name`) — writes its live rows' endings here rather than on the next
        tick's comparison: nothing would be left to compare, and an id handed straight back would
        give the new record the old one's words, `kind` and start time (review of PR #269). A word
        the act that ended the row already left wins over `how`, which is the default. **The
        record's snoozes go with it**: they were that row's *not now*, and a reused id must not
        arrive pre-silenced."""
        who = self._address(s)
        now = datetime.now(UTC)
        for key in [k for k in self._attention if k.split("|", 1)[0] == who]:  # keyed by address (the graph's)
            was, since, text = self._attention.pop(key)
            slot = key.split("|", 1)[1]
            word = self._attention_how.get(f"{who}|{slot}") or self._attention_how.get(f"{who}|*") or how
            self._trail_append(s, was, since, now, how=word, text=text)
        gone = [k for k in self.attention_snoozed if k.split("|", 1)[0] in (s.id, who)]
        for key in gone:
            del self.attention_snoozed[key]
        if gone:
            self.attention_store.save(self.trail, self.attention_snoozed)

    def _attention_ended(self, sid: str, how: str, slot: str = "state") -> None:
        """What ended a row, said by the act that ended it (`decide`, `identity_ack`, a resume, a
        forget): the next tick's comparison uses it instead of a plain *resolved*. `slot` is which
        of the record's two rows it is about — `"*"` for an act that ends both, a resume or a
        forget — and a slot's own word is spent once, while `*` stands until the record goes."""
        self._attention_how[f"{sid}|{slot}"] = how

    def _asker_gone(self, s: Session, *ids: str, how: str = "closed", keep_debt: bool = False) -> None:
        """Design §4.10 *What a person is asked*: an `ask` to the person cannot expire, so the
        other half of its lifecycle is the **asker's** — closing or forgetting a record closes the
        open `ask`s and `steer`s it put to the person, `closed_reason: asker_gone`, or a forgotten
        worker's questions would stand forever. An asker that merely **exited** leaves them open: a
        resume may still want the answer. Nothing is told — there is no one left to tell.

        **A record a resume superseded is not a gone asker** (review of PR #245): the conversation
        continues under the new id, `_move_mail` moved its questions' `from` there with it, and this
        record is closed only as the bookkeeping of that move — forgetting it a day later must not
        close a question the resumed session is still waiting on. The id rewrite is what makes this
        so; this is the second line, for a superseded record whose person-inbox copy was pruned and
        written again, or a rewrite a future path misses.

        **A question about a reference outlives its asker** (§4.10, TD-213): an open question whose
        `about` names a ledger id or a PR number is **orphaned** instead — it stays open, stamped
        `orphaned` from the record as it is now (`how`: `closed`, `forgotten` or `cancelled`), and
        a pause on it is cleared, there being no session left to hold. `repo` is the record's, or
        its directory when it names none (a session in a main checkout), which is where its board
        is. One already orphaned (a close, then the forget a day later) keeps its first stamp.

        **`keep_debt`** (§4.9a *The third declaration*, TD-1485): the close made for a replay that keeps
        the mail — the tick's before rule 2's, rule 7's, rule 1's lost-brief replay, and a person's
        Restart's — leaves the owed outcomes standing, since the next run under the name carries them;
        its open questions are handled as at any close. Only `_close` passes it, never `rpc_close`."""
        if s.superseded_by:
            return
        at = now_iso()
        for e in [e for e in self.person_inbox if e.from_ in (s.id, *ids) and e.open]:
            if e.orphaned:
                continue
            ref = reference_of(e.about)
            if ref is None:
                self._close_entry(e.id, "asker_gone", at)
                continue
            stamp = {"at": at, "how": how, "ref": ref, "name": s.name, "repo": s.repo or s.dir, "host": s.host or ""}
            self._mark(e.id, orphaned={**stamp, "team": s.team or ""}, paused_at=None)
        # And the debt goes with the asker (design §4.10 *Outcomes*): a question the person
        # answered whose asker was **closed or forgotten** is settled `asker_gone` — nobody is left
        # to report it, and the row must not wait in the Inbox for a session that cannot come back.
        # An asker that merely **exited** still owes: that row waits until the person opens the
        # session or dismisses it, which is why this runs from close and forget and not from exit.
        if not keep_debt:
            self._settle_owed(s.id, *ids, at=at)

    def _settle_owed(self, *addresses: str, at: str | None = None) -> None:
        """Each owed person-inbox entry asked from one of `addresses`, settled `asker_gone` (§4.10
        *Outcomes*): `_asker_gone`'s debt half, and a create that does not carry the old run's mail
        (§4.9a *The third declaration*, TD-1485), which replaces that mail in place. Touches no open
        question."""
        at = at or now_iso()
        for e in [e for e in self.person_inbox if e.from_ in addresses and e.owes]:
            self._mark(e.id, outcome={"state": "asker_gone", "text": "", "at": at, "by": ""})

    def _adopt_orphans(self, address: str | None = None) -> None:
        """**The name coming back adopts it** (§4.10 *A question about a reference outlives its
        asker*): a record under the id an orphaned question's `from` names — any the create left
        there, which is neither closed nor still scheduled — clears `orphaned`,
        whether or not its create resumed the conversation — the successor holds the name and the
        lane. `adopted_at` keeps that it ever was, which is what a later lapse's note reads.
        `address`: the record a create just made, at that create; with none, every orphaned entry
        is checked against the graph — the sweep's pass, which is how a node's create reaches here."""
        graph = self._graph()
        for e in [e for e in self.person_inbox if e.orphaned and e.open]:
            if address is not None and e.from_ != address:
                continue
            r = graph.get(e.from_)
            if r is None or r.state in ("closed", "scheduled") or r.superseded_by:
                continue
            self._mark(e.id, orphaned=None, adopted_at=now_iso())

    async def _settle_by_work(self) -> None:
        """**A question the work settled closes itself** (§4.10, TD-1469): once a tick, every open `ask` or `steer`
        in the person inbox, orphaned or not — never one the person sent — closes `merged` when the PR it carries
        merged in its repo, else `settled` when the entry its `about` names was archived after it was asked
        (`mail.work_settles`), `settled_by` the closing PR. Its repo is its stamp, else its orphan stamp's path,
        else its sender's live record found by its graph address, else its `team`'s one repo, each named through
        TD-1467's helper (`queue.mail_repo`'s order, TD-1541) against the record's own host's registered checkouts,
        by `(host, root)`; none of them, and it settles nothing. The close sets
        `closed_at` alone and tells nobody: a `steer` so closed applies no default and writes no lapse note."""
        todo = [e for e in self.person_inbox if e.open and e.from_ != PERSON]
        if not todo or not self._repos:
            return
        roots = queue_mod.repo_roots(self._repos)
        keys = {
            name: next((k for k, r in self._repos.items() if (r or {}).get("root", k) == root), root)
            for name, root in roots.items()
        }  # a name to its reading's key in `_repos`
        graph = self._graph()

        def home(h: Any) -> str:  # the home's host written one way, empty, in `live` and `names` alike (TD-1541)
            return "" if not h or str(h) == self.host else str(h)

        names: dict[tuple[str, str], str] = {}  # (host, path or record root) to its registry name
        live: dict[str, tuple[str, str]] = {}  # a live record's graph address to its (host, root), for `mail_repo`
        keyed: dict[str, tuple[str, str, str]] = {}  # the live records named, with their team, for `team_repos`
        wanted: set[str] = set()  # the senders' addresses, whole and (bare or home-host ones) bare
        teams = set()  # the teams of open items that carry no repo
        for e in todo:
            if e.repo:
                continue
            o = e.orphaned if isinstance(e.orphaned, dict) else None
            if o and o.get("repo") and (key := (home(o.get("host")), str(o["repo"]))) not in names:
                host_roots = await self._roots_of(o.get("host"))
                names[key] = queue_mod.record_repo(o["repo"], None, host_roots, roots) or ""
            bare, host = naming.split_address(e.from_)
            wanted.add(e.from_)
            if host is None or host == self.host:
                wanted.add(bare)
            if e.team:
                teams.add(e.team)
        for addr, r in graph.items():
            if r.state in ("closed", "scheduled") or r.superseded_by:
                continue
            if addr not in wanted and not (r.team and r.team in teams):
                continue
            pair = (naming.split_address(addr)[1] or "", str(r.repo or r.dir or ""))
            live[addr] = pair
            keyed[addr] = (*pair, str(r.team or ""))
            if pair[1] and pair not in names:
                names[pair] = await self._record_repo(r) or ""

        def name_of(h: str, root: Any) -> str:
            return names.get((h or "", str(root or "")), "")

        by_team = queue_mod.team_repos(keyed, name_of)
        at = now_iso()
        for e in todo:
            name = queue_mod.mail_repo(e, live, name_of, by_team, self.host)
            root = keys.get(name or "")
            if root is None:
                continue
            try:
                got = mail.work_settles(e, self._repos.get(root), self._archived.get(root))
            except (TypeError, ValueError):  # one malformed row or stamp: this question waits, the rest settle
                continue
            if got is None:
                continue
            reason, pr = got
            if reason == "settled":
                self._mark(e.id, settled_by=pr)
            self._close_entry(e.id, reason, at)

    async def _roots_of(self, host: Any) -> list[str]:
        """The checkouts the home registers for `host` (§4.10, TD-1467): this host's registry, or a node's roster."""
        host = str(host or "") or self.host
        try:
            if host == self.host:
                return list(await asyncio.to_thread(lambda: hosts.local_host().repos()))
            return await self._host_roster(host)
        except Exception:  # noqa: BLE001 — a registry unreadable: the question settles nothing this tick
            return []
