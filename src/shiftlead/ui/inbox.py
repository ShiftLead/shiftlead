"""The Inbox page (design §4.5 screen 6, §4.5a **Inbox page**, §4.10): its sections, the state rows,
the board rows from the host agent's reading, the promote rows, what is owed, and the rail and Find.
Moved out of `shiftlead.ui.app` unchanged (TD-196) and re-exported from it, so a route, a template or
a test reads each name from the app as before. `repo_teams` stays in the app, and `board_reading` is
read through it: the suite patches both there.
"""

from __future__ import annotations

import functools
import re
import subprocess
import time
from collections.abc import Callable, Collection, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sessionorc import balance as balance_mod
from sessionorc import board as board_mod
from sessionorc import cadence as cadence_mod
from sessionorc import held as held_mod
from sessionorc import hosts, ledgerboard
from sessionorc import ledger as ledger_mod
from sessionorc import ledgerboard as lb
from sessionorc import mail as mail_mod
from sessionorc import promote as promote_mod
from sessionorc import settings as settings_mod
from sessionorc import settle as settle_mod
from sessionorc import shots as shots_mod
from sessionorc import workorders as workorders_mod
from sessionorc.agent_common import WRAPUP_GRACE
from sessionorc.client import call_sync
from sessionorc.models import (
    normalize_ref,
)
from sessionorc.work import manager_of, wound_down
from shiftlead import review as review_mod
from shiftlead import teamrun

from . import render as rendermod
from . import uiconf
from .cards import _clock, _first_line, alarm_note, alarm_to_view, subagent_held
from .common import _age, _countdown, _instant, _iso, _left, editor_file_link, host_name, templates
from .queue import item_home

# -- the Inbox page (design §4.5 screen 6, §4.5a **Inbox page**, §4.10; TD-069 step 1) -------------

PERSON_ASK_KINDS = ("ask",)  # what reads as a question to the person; `steer` has its own rules
# design §4.5 screen 6 / §4.10 *Outcomes* (TD-079 step 2): **Waiting on them** is the fourth
# section, under *Steering* and in neither number — it waits on a session, not on the person.
# §4.9b (TD-075 step 2): **Answered for you** follows it, uncounted too — what a teammate answered
# for the person from the record, each with **Overrule**.
INBOX_SECTIONS = ("needs", "steering", "waiting", "answered", "later", "fyi", "snoozed")


def _entry_open(e: dict[str, Any]) -> bool:
    """Design §4.10 *One way of being closed*, mirrored for the dicts the RPC hands the page: an
    entry is open exactly when it is an `ask` or a `steer` with no `closed_reason` —
    and, for entries written before 2026-09-19, one with no `closed_by` and no `expired_at`."""
    if e.get("kind") not in (*PERSON_ASK_KINDS, "steer"):
        return False
    if e.get("closed_reason"):
        return False
    return not (e.get("closed_by") or e.get("expired_at"))


def _find_text(*parts: Any) -> str:
    """What the page's free-text filter matches on, lowercased once here rather than in the
    browser: the same `data-find` the mail rows carry."""
    return " ".join(str(p).strip() for p in parts if str(p or "").strip()).lower()


def kind_subject(kind: str, what: Any = "") -> str:
    """A row the home builds, as its subject (§4.10 *A subject on every entry*, TD-566): *<kind> ·
    <what>*, the reference in it — *permission · Bash*, *stalled? · grinder-ao-1* — clipped as mail's."""
    what = " ".join(str(what or "").split())
    return mail_mod.clip_subject(f"{kind} · {what}" if what else kind)


def restart_subject(words: str, name: str) -> str:
    """The restart row's subject: *restarts exhausted · <name>*, its kind the one its words open with."""
    return kind_subject(next((k for k in RESTART_SUBJECTS if words.startswith(k)), "restart"), name)


def row_subject(e: Mapping[str, Any]) -> str:
    """The subject a row draws first (§4.10 *A subject on every entry*, §4.5a **subject**): the one its
    builder set; else mail's — the envelope's, or, on an entry written before the field (or by a
    build that did not set it), derived from its text as `ao msg` derives one; a trail row its *how*."""
    if e.get("subject"):
        return str(e["subject"])
    if e.get("row") == "trail":
        return mail_mod.clip_subject(str(e.get("how") or ""))
    if e.get("row") == "ledger":  # §4.5 screen 6 *Later*: a ledger entry's title (TD-565)
        return mail_mod.clip_subject(str(e.get("title") or ""))
    if e.get("row"):
        return ""
    return _subject_of(str(e.get("text") or ""))


# a mail entry's text never changes, and the page asks for its subject twice a row on every request
# (the row's subject line and its find text), so each text's is derived once (TD-747)
_subject_of = functools.lru_cache(maxsize=4096)(mail_mod.subject_of)


# design §4.5a **Inbox row: state**: the row kinds that are a *needs you* session, and so exactly
# what the Org's needs-you count counts. Kept beside `state_kind` because the two are one rule.
NEEDS_YOU_ROWS = ("permission", "question", "needs")
# §4.10 *A subject on every entry* (TD-566): each state row's kind as its subject says it, before the
# session's name — *stalled? · grinder-ao-1* — in §4.5a's words for the row
STATE_SUBJECTS = {
    "needs": "needs you",
    "stalled": "stalled?",
    "unpushed": "exited with unpushed work",
    "idle_open": "idle · open work",
    "unclosed": "manager did not close",
    "alarm": "identity alarm",
}
# …and the restart row's, by which of its marks raised it: what `restart_mark`'s words open with
RESTART_SUBJECTS = ("brief lost twice", "fills exhausted", "restarts exhausted", "restart held", "restart wanted")


def state_kind(v: dict[str, Any]) -> str:
    """Which state row this session is, or "" for one that needs nobody (design §4.5a **Inbox row:
    state**). **The one predicate the Inbox and the Org's needs-you count both read**, so every
    session the Sessions page counts as `needs-you` has exactly one row on the Inbox and the page's hover
    text — *the session states the Sessions page counts too* — is true (review of PR #251).

    A `needs-you` record whose `pending` is empty, is not a dict, or names a kind this build does
    not know is still a session stopped for a person: it becomes a plain **needs** row with
    **Open** and no Allow / Deny, because nothing structured came with it and a control built from
    what is not there is the thing §4.2 and TD-071 item 8 forbid."""
    state = v.get("state")
    pend = v.get("pending")
    pend = pend if isinstance(pend, dict) else {}
    if state == "needs-you":
        # a permission only the terminal answers (§4.3 `permission_channel`, TD-785) is a question row
        if pend.get("kind") == "permission" and pend.get("tool_use_id") and v.get("permission_channel") is not False:
            return "permission"
        return "question" if pend.get("text") or pend.get("kind") else "needs"
    if state == "stalled?":
        return "stalled"
    if state == "limited":
        return "limited"
    if state == "exited" and v.get("flag") and [name for name, ok in (v.get("ready") or []) if not ok]:
        # "exited with unpushed work" (§4.5a, TD-069): what Ready to close says, in its own words —
        # the row goes when the work is pushed or the session is forgotten.
        return "unpushed"
    return ""


def restart_mark(v: dict[str, Any]) -> tuple[str, str] | None:
    """Design §4.5a **Inbox row: restart** (§6 *Keeping a team running*, TD-103 slice 5): `(the
    mark's own time, the row's words)` for a record the tick could not restart — at a ceiling,
    held by work left, or an `early` `restart_wanted` that neither a controller nor the tick acts
    on (§4.9a) — else None. The words are fixed, from the record's fields: an early one says what
    decided it (`restart_wanted.decided`, the host agent's reading — *early: nothing reported done
    this run*, *repeats TD-229: reported done by an earlier run too*; TD-249 slice 6), and its `why`
    is the session's own sentence, shown as such and never acted on."""
    if v.get("superseded_by"):
        return None
    ceiling, held, wanted = v.get("restart_ceiling"), v.get("restart_blocked"), v.get("restart_wanted")
    if isinstance(ceiling, dict):
        n = ceiling.get("count")
        n = n if isinstance(n, int) else "?"
        if ceiling.get("why") == "lost-brief":
            # a second lost brief (§4.1 *A launch whose hook never comes is recovered*, TD-720): no count
            return str(ceiling.get("at") or ""), (
                "brief lost twice — no hook reached it at its launch, nor after the host agent relaunched it once"
            )
        if ceiling.get("why") == "fill":
            return str(ceiling.get("at") or ""), (
                f"fills exhausted · {n} in 1 h — the seats beside it were filled as often as the host agent will"
            )
        return str(ceiling.get("at") or ""), (
            f"restarts exhausted · {n} in 2 h — it exited on its own each time and the host agent restarted it "
            "up to its ceiling"
        )
    if isinstance(held, dict):
        return str(held.get("at") or ""), (
            f"restart held: {held.get('dirty')} uncommitted and {held.get('unpushed')} unpushed in its checkout "
            "— it is restarted by itself the moment they are pushed"
        )
    if isinstance(wanted, dict) and wanted.get("early") and v.get("state") in ("idle", "exited"):
        why = _first_line(wanted.get("why") or "") or "no reason given"
        decided = _first_line(wanted.get("decided") or "") or "early"  # a mark older than the field
        return str(wanted.get("at") or ""), f"restart wanted · {decided} — {why}"
    return None


def unclosed_mark(v: dict[str, Any], now: datetime) -> tuple[str, str] | None:
    """Design §4.5a **Inbox row: manager did not close** (§6 rule 9, TD-241): `(when it was told,
    the row's words)` for a live manager the tick told its team had finished (`finished_sent_at`)
    and could not close `WRAPUP_GRACE` later — never idle, `needs-you`, `limited`, or holding work
    — else None. Read from the record each time: nothing more is stored, and the row leaves when
    the manager is closed or a member at work takes the wind-down back."""
    sent = _instant(v.get("finished_sent_at"))
    if sent is None or v.get("superseded_by") or v.get("state") in ("exited", "closed"):
        return None
    if now - sent < WRAPUP_GRACE:
        return None
    return str(v["finished_sent_at"]), (
        "manager did not close — its team finished and the host agent told it so, and it has not closed; "
        "the host agent closes it only once it is idle with nothing uncommitted or unpushed"
    )


def idle_open_mark(v: dict[str, Any], views: Collection[dict[str, Any]], now: datetime) -> tuple[str, str] | None:
    """Design §4.5a **Inbox row: idle · open work** (§6 rule 3 `idle_open`, TD-259): `(the mark's
    time, the row's words)` for a supervised member of a team with **no manager** that the tick
    reads as idle with its work open — `idle_open: {at, ref}` on its record — else None. A team
    with a manager draws no row: the reading fills a manager on call, or is a standing manager's
    round. The manager is read from the team's records whatever their state (`work.manager_of`), so
    a manager on call whose seat is empty — its record closed between fills — still manages.
    The words are the record's fields and nothing off its screen: *idle 40m with TD-070 open, nudged
    14:02*."""
    mark = v.get("idle_open")
    if not isinstance(mark, dict) or v.get("state") != "idle" or not v.get("supervised") or not v.get("team"):
        return None
    if manager_of([o for o in views if o.get("team") == v["team"]]) is not None:
        return None
    idle = _age(v.get("since"), now)
    ref = str(mark.get("ref") or "").strip()
    nudged = _clock(v.get("nudged_at"))
    words = f"idle {idle}".strip() + (f" with {ref} open" if ref else " with its work open")
    return str(mark.get("at") or ""), words + (f", nudged {nudged}" if nudged else "")


def _pr_parts(prs: Collection[int], directory: Any, tail: str) -> list[dict[str, str]]:
    """A row's words as the page draws them: *PR #845 and #851 <tail>*, each `#n` a link to the pull
    request where the checkout's origin says where it is (`review.pr_url`), bare where it does not."""
    parts: list[dict[str, str]] = [{"text": "PR "}]
    for i, pr in enumerate(prs):
        if i:
            parts.append({"text": " and " if i == len(prs) - 1 else ", "})
        parts.append({"text": f"#{pr}", "url": review_mod.pr_url(str(directory) if directory else None, pr)})
    return [*parts, {"text": f" {tail}"}]


def _parts_text(parts: Collection[Mapping[str, str]]) -> str:
    return "".join(p["text"] for p in parts)


def cadence_marks(v: dict[str, Any], names: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Design §4.5a **Inbox row: cadence check failed** (§6 rule 10, TD-258): one `{pr, at, parts}`
    for each `checks` entry of the record carrying `row` — a PR that failed the cadence check twice,
    or failed already merged. The words are fixed and the record's: the failed rows by the script's
    `rule` names, never its `detail`; beside *review*, *read by <seat>* when the home saw the
    reader's reply on the PR's `ask` and *recorded* when it did not; and when it was read. `names`
    gives the reader's record its name, where the page holds that record; its id is said otherwise."""
    if v.get("superseded_by") or not isinstance(v.get("checks"), list):
        return []
    out = []
    for c in cadence_mod.rows([c for c in v["checks"] if isinstance(c, dict) and isinstance(c.get("pr"), int)]):
        by = str(c.get("read_by") or "")
        note = f"read by {(names or {}).get(by) or by}" if by else "recorded"
        failed = [
            f"{r} ({note})" if r == "review" else str(r)
            for r in (c.get("failed") if isinstance(c.get("failed"), list) else [])
        ]
        tail = f"fails the cadence check: {', '.join(failed) or 'no row named'}"
        if read := _clock(c.get("at")):
            tail += f" · read {read}"
        parts = _pr_parts([c["pr"]], v.get("repo") or v.get("dir"), tail)
        out.append({"pr": c["pr"], "at": str(c.get("row") or c.get("at") or ""), "parts": parts})
    return out


def held_mark(v: dict[str, Any]) -> dict[str, Any] | None:
    """Design §4.5a **Inbox row: merged without its read** (§6 rule 11, TD-258): `{at, parts}` for a
    record whose `held_missed` holds two crossings the person has not dismissed (`held.row`), else
    None — the first is a note and the member's line. The PRs and the held paths are the entries'."""
    if v.get("superseded_by") or not isinstance(v.get("held_missed"), list):
        return None
    left = held_mod.row([c for c in v["held_missed"] if isinstance(c, dict) and isinstance(c.get("pr"), int)])
    if not left:
        return None
    reader = str((v.get("review") or {}).get("reader") or "") if isinstance(v.get("review"), dict) else ""
    chained = isinstance(v.get("review"), dict) and "chain" in v["review"]  # a flow's chain (§4.9c, TD-315)
    whose = "the person's" if reader == "person" else "its readers'" if chained else "the techlead's"
    paths = list(
        dict.fromkeys(str(p) for c in left for p in (c.get("paths") if isinstance(c.get("paths"), list) else []))
    )
    more = f" and {len(paths) - held_mod.NAMED} more" if len(paths) > held_mod.NAMED else ""
    tail = f"touched held paths and merged without {whose} read"
    if paths:
        tail += f" · {', '.join(paths[: held_mod.NAMED])}{more}"
    parts = _pr_parts([c["pr"] for c in left], v.get("repo") or v.get("dir"), tail)
    return {"at": max(str(c.get("at") or "") for c in left), "parts": parts}


def state_rows(
    views: Collection[dict[str, Any]],
    *,
    host_alarms: Collection[dict[str, Any]] = (),
    host: str = "",
    identity_mode: str = "",
) -> list[dict[str, Any]]:
    """Design §4.5 screen 6 / §4.5a **Inbox row: state** (TD-069 step 2): a session's state as a
    row of the Inbox, one per thing that needs a person. Built from the card views the Org is
    rendered from — the same `view()`, so a row's pill, `doing` line, `title`, team and role are
    the card's own and cannot drift from it — and never from anything parsed off a screen
    (TD-071 item 8).

    The kinds, in §4.5a's words: a pending **permission** (what is asked, the time left, Allow /
    Deny through the hook channel); a pending **question** and **stalled?** (the text or the host's
    note, **Open**); **limited** (the reset time); an **exited** session with unpushed work (what
    Ready to close says, **Open**). To them TD-077 step 2 adds the **identity alarm** rows: one per
    record that has alarms, and one for the host's own list — *it is either a bug of ours or a
    session misbehaving and a person should know which* (§4.8a).

    A row has no `snoozed_until` and no Snooze: a state lives on the record, and there is nowhere
    to keep a person's *not now* (the gap is written up in TD-069 step 2's entry). It leaves the
    list the moment the state does, which is the next poll."""
    rows: list[dict[str, Any]] = []
    now = datetime.now(UTC)  # one instant for the whole list, as `inbox_sections` takes one

    def base(v: dict[str, Any], row: str, text: str, *, extra: str = "", subject: str = "") -> dict[str, Any]:
        doing = v.get("doing") or {}
        name = v.get("name") or v["id"]
        subject = subject or kind_subject(STATE_SUBJECTS.get(row, row), name)
        return {
            "row": row,
            "id": f"{v['id']}:{row}",  # the row's own key on the page; a record may raise two
            "sid": v["id"],
            "name": name,
            "subject": subject,
            "team": v.get("team") or "",
            "role": v.get("role") or "",
            "role_icon": v.get("role_icon") or "",
            "role_label": v.get("role_label") or "",
            "title": v.get("title") or "",
            "doing": v.get("doing"),
            "state": v.get("state") or "",
            "state_class": v.get("state_class") or "",
            "state_label": v.get("state_label") or "",
            "scraped": bool(v.get("scraped")),
            "pill_title": v.get("pill_title") or "",  # §4.5a **state pill hover**: the card's one text (TD-490)
            # §4.5a *card: unseen mark* (TD-1228): the chip after the pill, the record's as the card's
            "unseen": bool(v.get("unseen")),
            "unseen_age": v.get("unseen_age") or "",
            "suspended_note": v.get("suspended_note") or "",  # §4.8a: the mark rides with the record
            "host": v.get("host") or "",
            "text": text,
            "deadline": v.get("deadline") or "" if row == "permission" else "",
            # a subagent's prompt names its asker and, while held, says the pane shows nothing (TD-950)
            "held": subagent_held(v.get("pending")) if row in ("permission", "question") else None,
            # the entry the row's Allow / Deny answer, so a newer one pushed meanwhile is never answered unseen
            "call": str((v.get("pending") or {}).get("tool_use_id") or "") if row == "permission" else "",
            # §4.5 screen 6 *Layout* (TD-082): the countdown is rendered in words here, not left as
            # `…` for the client's first tick. The words are `fmtLeft`'s, so nothing jumps.
            "left": _countdown(v.get("deadline") if row == "permission" else None, now),
            "at": v.get("since") or "",
            "age": v.get("age") or "",
            "find": _find_text(v.get("name"), v.get("title"), doing.get("text"), text, extra),
        }

    names = {str(v.get("id")): str(v.get("name") or v.get("id")) for v in views}
    for v in sorted(views, key=lambda v: (str(v.get("since") or ""), str(v.get("id") or ""))):
        pend = v.get("pending")
        pend = pend if isinstance(pend, dict) else {}
        text = str(pend.get("text") or "")
        kind = state_kind(v)
        if kind == "permission":
            # the tool's name is what the adapter's text opens with, *Bash: git push* (§4.2)
            tool = text.split(":", 1)[0] if ":" in text else ""
            rows.append(base(v, kind, text, subject=kind_subject("permission", tool or v.get("name") or v["id"])))
        elif kind == "question":
            rows.append(base(v, kind, f"{pend.get('kind')}: {text}" if pend.get("kind") else text))
        elif kind == "needs":
            rows.append(base(v, kind, "it is waiting on a person, and nothing came with it saying what for"))
        elif kind == "stalled":
            rows.append(base(v, kind, text or v.get("host_note") or "no output for a while, and no note"))
        elif kind == "limited":
            rows.append(base(v, kind, text or "the profile is at its cap"))
        elif kind == "unpushed":
            unmet = [name for name, ok in (v.get("ready") or []) if not ok]
            rows.append(base(v, kind, f"{v['flag']} — {', '.join(unmet)}", extra=v.get("where") or ""))
        if mark := restart_mark(v):
            # its own row beside any state row, as an alarm is: a crashed record at its ceiling can
            # also be exited with unpushed work, and the two are answered differently
            rows.append(
                {
                    **base(v, "restart", mark[1], subject=restart_subject(mark[1], v.get("name") or v["id"])),
                    "at": mark[0] or v.get("since") or "",
                    "age": "",
                    "restartable": bool(v.get("restartable")),  # never a seat: *fills exhausted* has no Restart
                }
            )
        if mark := idle_open_mark(v, views, now):
            rows.append({**base(v, "idle_open", mark[1]), "at": mark[0] or v.get("since") or "", "age": ""})
        if mark := unclosed_mark(v, now):
            rows.append({**base(v, "unclosed", mark[1]), "at": mark[0], "age": ""})
        for c in cadence_marks(v, names):
            # one row a PR, and the PR in the row's kind: it is the snooze's key (`cadence:<pr>`)
            row = base(
                v,
                f"cadence:{c['pr']}",
                _parts_text(c["parts"]),
                subject=kind_subject("cadence check failed", f"#{c['pr']}"),
            )
            rows.append({**row, **c, "at": c["at"] or row["at"], "age": "", "mark": "cadence"})
        if held := held_mark(v):
            prs = ", ".join(f"#{p['text'][1:]}" for p in held["parts"] if p.get("text", "").startswith("#"))
            row = base(v, "held", _parts_text(held["parts"]), subject=kind_subject("merged without its read", prs))
            rows.append({**row, "at": held["at"] or row["at"], "age": "", "mark": "held", "parts": held["parts"]})
        if alarms := v.get("alarms"):
            row = base(v, "alarm", alarm_note(alarms))
            # an alarm row is as old as its newest alarm, not as its session: what the order is
            # about is when the thing that needs a person happened
            rows.append(
                {
                    **row,
                    "at": max((a["last"] or a["at"]) for a in alarms) or row["at"],
                    "age": "",
                    "alarms": alarms,
                    # §4.8a *An alarm's answers* (TD-077 b): who **Log TD** would hand these to — the
                    # home's own answer (`alarm_to`, the record's first live controller from the
                    # control graph), never worked out here, so drawn-or-not and the RPC's
                    # refused-or-not cannot disagree.
                    "alarm_to": alarm_to_view(v.get("alarm_to")),
                    "mode": identity_mode,
                    "find": _find_text(row["find"], *(a["words"] for a in alarms)),
                }
            )
    if host_alarms:
        rows.append(
            {
                "row": "alarm_host",
                "id": "host:alarm",
                "sid": "",
                "name": host or host_name(),
                "subject": kind_subject("identity alarm", host or host_name()),
                "team": "",
                "role": "",
                "role_icon": "",
                "role_label": "",
                "title": "",
                "doing": None,
                "state": "",
                "state_class": "",
                "state_label": "",
                "scraped": False,
                "host": host,
                "text": alarm_note(list(host_alarms)),
                "deadline": "",
                "at": max((a["last"] or a["at"]) for a in host_alarms),
                "age": "",
                "find": _find_text(host, "identity alarm", *(a["words"] for a in host_alarms)),
                "alarms": list(host_alarms),
                "mode": identity_mode,
            }
        )
    return rows


# design §4.5 screen 6 / §4.4 (TD-069 step 3): **board items** in the Inbox. The board is each
# repo's `board:` (§5 *The seams*, default `docs/user_attention.md`), in ledgerboard's format, read
# in-process through ledgerboard (TD-585) — never a second parser here — and the reading is the host
# agent's (§4.4 *Each reading has one owner*, *The boards*, TD-615): every open item, on the repo
# reading as `boards`, which the page reads from the `repos` RPC and runs no reader of its own.
# §4.5a's answers to a board row, the `board_edit` RPC's actions: Snooze, Done, and **Decide** — one
# of the item's own `Answers:`, or *Go with it* for the one marked default (§4.4 *Decide*, TD-255)
BOARD_ACTS = ("snooze", "done", "decide")
# the kinds a live look is written as: `look` since dev-cadence TD-082, `watch` before it (TD-292)
LOOK_KINDS = ("look", "watch")
WORKS = "Works"  # a live look's first answer, cadence §3.5's word (the second is the `Not right: <what>` form)

# the home's pull readings by repo name (`host`'s `pulls`, §6 *Pull*), kept fresh by the app as
# `work_marks` keeps its marks: what the *behind* note's tail says
PULLS: dict[str, Any] = {}


def pull_tail(reading: Mapping[str, Any] | None) -> str:
    """The *behind* origin note's tail (§4.5 screen 6, TD-263): the pull's standing for the repo, in
    the design's words — "" when no pass has reached it, or its last pass left it current or pulled
    (the board read is then older than the checkout, and the next read says so)."""
    r = reading or {}
    outcome = r.get("outcome")
    if outcome == "waiting":
        who = str(r.get("occupant") or "")
        return f" — the host agent pulls it once {who} is idle" if who else " — the host agent pulls it once it is idle"
    if outcome == "refused":
        return f" — it could not be pulled: {r.get('why') or 'no reason given'}"
    if outcome == "off":
        return " — pulling is off for this repo"
    return ""


def origin_case(source: str, fetch_case: str) -> str | None:
    """The case of one board's read against origin (§4.5 screen 6): `behind`, `local`, `both`,
    `unreached`, or None — matches origin, no board there, or a plain read. The reading's own
    `fetch_case` (`workorders.FETCH_CASES`, TD-585) decides, never its sentence; `source` is non-empty
    only when the board was read from origin, which is *behind*."""
    if source:
        return "behind"
    return {"skipped": "unreached", "behind": "behind", "local": "local", "both": "both"}.get(fetch_case)


def origin_note(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """§4.5a **origin note**: the line above a repo's first board row, in the design's words, as
    `{text, warn}` — `warn` the warning colour, for the one case where rows are hidden — or None.
    The reader's sentence is never drawn but for a skipped fetch's reason, which carries no count."""
    source = str(row.get("source") or "")
    case = origin_case(source, str(row.get("fetch_case") or ""))
    if case == "behind":
        tail = pull_tail(PULLS.get(Path(str(row.get("root") or "")).name)) if row.get("root") else ""
        return {"text": f"read from {source or 'origin'}: this checkout has not pulled it yet{tail}", "warn": False}
    if case == "local":
        return {"text": "board edits made here are not on origin", "warn": False}
    if case == "both":
        return {
            "text": "this checkout's board and origin's have both changed: showing the checkout's, "
            "and what origin added is not shown — pull",
            "warn": True,
        }
    if case == "unreached":
        why = str(row.get("fetch_why") or "")
        return {
            "text": f"origin could not be reached ({why.strip() or 'no reason given'}): "
            "showing the checkout's board as of its last pull",
            "warn": False,
        }
    return None


def origin_firsts(rows: Collection[Mapping[str, Any]]) -> set[str]:
    """The ids of the rows that carry their repo's **origin note** in one list as drawn: the first
    board row of each board whose read has a note (§4.5a: *one line above a repo's first board row*)."""
    seen: set[str] = set()
    out: set[str] = set()
    for r in rows:
        if r.get("row") != "board" or not r.get("board") or r["board"] in seen:
            continue
        seen.add(r["board"])
        if origin_note(r):
            out.add(str(r.get("id")))
    return out


templates.env.globals.update(origin_note=origin_note, origin_firsts=origin_firsts)


def board_reading(
    repos: Mapping[str, Any] | None, repos_of: Mapping[str, Mapping[str, Any]] | None = None
) -> tuple[list[dict[str, Any]], str]:
    """The Inbox's board rows (`board_rows`) from the host agent's repo readings — the `repos` RPC,
    each checkout's `boards` (§4.4 *Each reading has one owner*, *The boards*, TD-615) — and a note
    saying what could not be read, never drawn as an empty board (§4.5 *no silent failure path*): a
    reading the host agent could not take again keeps its last items and says since when."""
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for root, r in sorted((repos or {}).items()):
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or Path(str(root)).name)
        got = r.get("boards")
        if not isinstance(got, dict):
            if workorders_mod.board_path(str(root))[0] != "absent":  # a reading from before its first board read
                notes.append(f"the board of {name} has not been read yet")
            continue
        own = board_rows(got, repos_of)
        if got.get("error"):
            since = f" since {got['failed_at']}" if got.get("failed_at") else ""
            shown = "its rows are the last reading" if own else "no row is shown"
            notes.append(f"the board of {name} could not be read{since} ({got['error']}): {shown}")
        rows += own
    return rows, "; ".join(notes)


def _same_ref(a: Any, b: Any) -> bool:
    """One reference, as the host agent stores it (`normalize_ref`: `td-27` is `TD-027`)."""
    try:
        return normalize_ref(str(a or "")) == normalize_ref(str(b or ""))
    except ValueError:  # an empty reference names nothing
        return False


def review_pr(progress: Collection[dict[str, Any]], ref: str) -> int | None:
    """The PR a claim on `ref` is in review as (design §4.5a *Focus side panel → Reports*, TD-150),
    or None: a declared `claimed` entry's own `pr`, else the `review_pr` its record carries for its
    branch — the rule `AO.reportGroups` draws the panel by, so the panel and the refusal agree. No
    derived entry shares a declared one's reference (§9 invariant 10), so there is no third."""
    for p in progress:
        if not isinstance(p, dict) or not _same_ref(p.get("ref"), ref) or p.get("status") != "claimed":
            continue
        if (p.get("source") or "declared") != "declared":
            continue
        got = p.get("review_pr") or p.get("pr")
        if isinstance(got, int) or str(got or "").isdigit():
            return int(got)
    return None


def board_choices(roots: Collection[str | Path] | None = None) -> list[dict[str, str]]:
    """The boards *Put on the board* may write to (design §4.5a *Inbox row: FYI*, TD-140): each
    checkout this host's repos registry names that carries a board, as `{label, root, board}` with
    both paths resolved — the paths `board_edit` resolves against the same registry. On a node the
    org is the home's (§4.4a), so a node offers none."""
    if roots is None:
        if hosts.is_node():
            return []
        roots = hosts.local_host().repos()
    out: list[dict[str, str]] = []
    for r in roots:
        root = Path(r).expanduser().resolve()
        rel = workorders_mod.board_path(root)[1]
        if rel is not None and (root / rel).is_file():
            out.append({"label": root.name, "root": str(root), "board": str((root / rel).resolve())})
    return out


def promote_rows(promotes: Mapping[str, Any] | None, now: datetime | None = None) -> list[dict[str, Any]]:
    """design §4.5a **Inbox row: promote** (§6 *Promote*, TD-132 slice 3): one row per repo in the
    home's `promotes` reading, drawn only while live is not main's head or a promote failed — and
    every part from that structured reading, never text a session wrote. Under `auto: false` a repo
    main is ahead of is *Needs you*, counted (the press is what stands between merged and live); a
    run **in flight** is FYI (`fyi`), uncounted, its Promote disabled; a **failure** is *Needs you*
    whatever `auto` says. **Under `auto: true`** (TD-581) a repo main is ahead of, nothing in flight
    and no failure or hold, is FYI too (`auto_row`), uncounted and snoozable, saying when the home
    will act — *· auto on ·* and the reading's `acts` in its words — with **Promote now**; a
    failure or a hold is drawn under *Needs you* in its place, and a run in flight under `auto`
    draws nothing: the note says when it is live.
    Aged from when main moved (`moved`, its head's committer time). Keyed `promote:<repo>` in the
    attention store, so Snooze is by time alone and more merges do not wake a snoozed row.

    **After a rollback** (§6 *A rollback*, TD-226 slice 3) the row is drawn while the home's `held`
    stands, whatever `auto` says, under *Needs you*: *live `<sha7>`, rolled back from `<sha7>` <t>
    ago · main … · auto on · held* — *rolled back*, never *behind*, since a person put live there;
    its Dismiss ends the hold when no failure stands. A hold a failed smoke wrote (`by: smoke`, §6 *The
    smoke*, TD-811) reads *rolled back by the smoke from `<sha7>` <t> ago — <why>*; a run in flight
    whose `check` read its commit (`phase: smoke`) reads *checking `<sha7>` live* on the row.

    **The precheck on main** (§6, TD-1038): while the home's own run goes on main's head the `auto` row
    reads *· prechecking `<sha7>` — promotes when green* (`acts`); a precheck that failed on main's head
    (`precheck_failed`) is drawn under *Needs you*, counted, whatever `auto` says, *checks failed on
    `<sha7>`* with the log's last lines, until main's head moves."""
    at = now or datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for repo, r in sorted((promotes or {}).items()):
        if not isinstance(r, dict):
            continue
        failed = r.get("failed") if isinstance(r.get("failed"), dict) else None
        flight = r.get("inflight") if isinstance(r.get("inflight"), dict) else None
        held = r.get("held") if isinstance(r.get("held"), dict) else None
        pre = r.get("precheck_failed") if isinstance(r.get("precheck_failed"), dict) else None
        pre = pre if pre and pre.get("sha") == r.get("main") else None  # until main's head moves
        behind = bool(r.get("main")) and r.get("live") != r.get("main")
        auto_row = bool(r.get("auto")) and behind and not (failed or held or flight or pre)
        if not failed and not held and not pre and not auto_row and (r.get("auto") or not (flight or behind)):
            continue
        live = str(r.get("live") or "")[:7]
        main = str(r.get("main") or "")[:7]
        ahead = r.get("ahead")
        checks = str(r.get("checks") or "unknown")
        text = f"{repo} · live {live or 'unknown'}"
        if held:
            frm, since = str(held.get("from") or "")[:7], _age(held.get("at"), at)
            by = " by the smoke" if held.get("by") == "smoke" else ""  # §6 *The smoke*: a failed smoke put it back
            text += f", rolled back{by} from {frm or 'unknown'}" + (f" {since} ago" if since else "")
            if by and held.get("why"):
                text += f" — {held['why']}"
        text += f" · main {main or 'unknown'}"
        if isinstance(ahead, int) and ahead:
            text += f", {ahead} commit{'' if ahead == 1 else 's'} ahead"
        text += f" · checks failed on {str(pre['sha'])[:7]}" if pre else f" · checks {checks}"
        if held:
            text += f" · auto {'on' if r.get('auto') else 'off'} · held"
        elif auto_row:
            text += " · auto on" + (f" · {w}" if (w := promote_mod.acts_words(r.get("acts"))) else "")
        when = str(
            (failed or {}).get("at") or (flight or {}).get("at") or (held or {}).get("at") or r.get("moved") or ""
        )
        out.append(
            {
                "row": "promote",
                "sid": f"promote:{repo}",
                "id": f"promote:{repo}",
                "name": repo,
                "repo": repo,
                "subject": kind_subject("promote", repo),
                "team": "",
                "at": when,
                "age": _age(when, at),
                "text": text,
                "live_why": r.get("live_why") if not live else None,
                "checks_why": r.get("checks_why"),
                # under `auto` the checks are the row's own words (*checks pending — promotes when green*)
                "unmet": None if auto_row and (r.get("unmet") or {}).get("name") == "checks" else r.get("unmet"),
                "auto_row": auto_row,
                "failed": failed,
                "held": held,
                "precheck_failed": pre,
                "inflight": flight,
                "fyi": (bool(flight) and not failed and not pre) or auto_row,
                "find": " ".join(x for x in (repo, "promote", text, (failed or {}).get("why") or "") if x),
            }
        )
    return out


def red_pr_rows(
    repos: Mapping[str, Any] | None, records: Collection[Mapping[str, Any]], now: datetime | None = None
) -> list[dict[str, Any]]:
    """design §4.5a **Inbox row: red PR** (§4.4 *A red PR nobody holds is a work order*, TD-613): one
    row per `pr:<n>` order of a repo **no team services** (`teamrun.serviced`) — a serviced repo's
    order is a lane's, never the person's — under *Needs you*, counted: *`<repo>` #<n> · red 3h 5m ·
    <the failing checks> · <author>*. **Open** is the PR on its forge; **Snooze ▾** by time alone,
    keyed `red_pr:<repo>:<n>` in the attention store. Every part from the home's reading; it leaves
    when the order does — green, closed, or held by a live record. A sync PR's order (TD-684) has the
    row green or red, *`<repo>` #<n> · sync · <its reason> · <author>*, and leaves when it merges,
    closes or is held."""
    at = now or datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for root, r in sorted((repos or {}).items()):
        if not isinstance(r, dict) or teamrun.serviced(str(r.get("root") or root), records):
            continue
        repo = str(r.get("name") or Path(str(root)).name)
        for e in teamrun.pr_orders(r):
            n = e.get("pr")
            if not isinstance(n, int):
                continue
            if e.get("sync"):
                # a sync PR the home did not merge, green or red, its reason in place of the checks (TD-684)
                since = str(e.get("sync_since") or "")
                parts = [f"{repo} #{n}", "sync", str(e.get("reason") or ""), str(e.get("author") or "")]
            else:
                since = str(e.get("red_since") or "")
                word = "red" if e.get("checks") == "red" else "conflicting"
                failing = ", ".join(e.get("failing") or [])
                parts = [f"{repo} #{n}", f"{word} {_age(since, at)}".strip(), failing, str(e.get("author") or "")]
            text = " · ".join(x for x in parts if x)
            out.append(
                {
                    "row": "red_pr",
                    "sid": f"red_pr:{repo}:{n}",
                    "id": f"red_pr:{repo}:{n}",
                    "name": repo,
                    "repo": repo,
                    "pr": n,
                    "url": str(e.get("url") or ""),
                    "title": str(e.get("title") or ""),
                    "subject": kind_subject("red PR", f"{repo} #{n}"),
                    "team": "",
                    "at": since,
                    "age": _age(since, at),
                    "text": text,
                    "find": " ".join(x for x in (repo, f"#{n}", "red PR", str(e.get("title") or ""), text) if x),
                }
            )
    return out


def fork_pr_rows(
    repos: Mapping[str, Any] | None,
    records: Collection[Mapping[str, Any]],
    home: str = "",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """design §4.5a **Inbox row: fork's PR** (§4.4 *A fork's PR is no work order*, TD-1285, built by TD-1292):
    one row per fork's PR ready to precheck (`teamrun.ready_to_precheck`) in every repo, serviced or not, since
    no session may run its line — one per checkout, as `red_pr_rows` gives, each with its own root's line —
    under *Needs you*, counted: *`<repo>` #<n> · fork · CI green · <author>*, its age the PR's own, then the
    reading's `precheck_line`, titled *type it in a terminal on <home>, where <root> is* (`home` the home's host
    name). **Open** is the PR's diff, **Snooze ▾** by time alone, keyed `fork_pr:<repo>:<n>`. It leaves when the
    PR is no longer ready. `records` is unread: a fork's PR is no lane's, so who services the repo does not
    matter; it is taken for the callers' symmetry with `red_pr_rows`."""
    del records
    at = now or datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for root, r in sorted((repos or {}).items()):
        if not isinstance(r, dict):
            continue
        repo = str(r.get("name") or Path(str(root)).name)
        where = str(r.get("root") or root)
        for p in ((r.get("prs") or {}).get("open")) or []:
            if not teamrun.ready_to_precheck(p):
                continue
            n = p["number"]
            since = str(p.get("created") or "")
            text = " · ".join(x for x in (f"{repo} #{n}", "fork", "CI green", str(p.get("author") or "")) if x)
            out.append(
                {
                    "row": "fork_pr",
                    "sid": f"fork_pr:{repo}:{n}",
                    "id": f"fork_pr:{repo}:{n}",
                    "name": repo,
                    "repo": repo,
                    "pr": n,
                    "url": f"{str(p.get('url') or '').rstrip('/')}/files",
                    "title": str(p.get("title") or ""),
                    "subject": kind_subject("fork's PR", f"{repo} #{n}"),
                    "team": "",
                    "at": since,
                    "age": _age(since, at),
                    "text": text,
                    "line": str(p["precheck_line"]),
                    "line_title": f"type it in a terminal on {home or 'the home'}, where {where} is",
                    "find": " ".join(x for x in (repo, f"#{n}", "fork's PR", str(p.get("title") or ""), text) if x),
                }
            )
    return out


CI_BILLING_REASON = "billing or spending limit"  # §4.5a *Inbox row: CI not starting*: a `billing` kind's words
ORG_BILLING = "https://github.com/organizations/{owner}/settings/billing"
USER_BILLING = "https://github.com/settings/billing"
GH_USER_TTL = 600.0  # an account that could not be read is asked again after this long, not on every poll
GH_USER_WAIT = 10.0
_gh_user_type: dict[str, tuple[float, str]] = {}  # owner (lower) → (when read, `Organization` | `User` | "")


def _gh_user_type_read(owner: str) -> str:
    """`gh api users/<owner> --jq .type`, bounded: *Organization*, *User*, or "" when it cannot be read."""
    try:
        cp = subprocess.run(
            ["gh", "api", f"users/{owner}", "--jq", ".type"],
            capture_output=True,
            text=True,
            timeout=GH_USER_WAIT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return cp.stdout.strip() if cp.returncode == 0 else ""


def billing_url(owner: str) -> str:
    """**Open** on the *CI not starting* row (§4.5a): the owner's billing page — the org's for an
    organisation, the person's own for a user — told apart once with `gh api users/<owner>`'s `type`
    and kept for the process's life. An account that cannot be read is asked again after
    `GH_USER_TTL`, and meanwhile is the person's own billing page: a page that always opens, where
    GitHub's settings switch to the org, rather than an org page that is a 404 for a user. Blocking:
    the page reads it off the loop (`ci_not_run_kinds`)."""
    key, now = owner.lower(), time.monotonic()
    at, kind = _gh_user_type.get(key, (0.0, ""))
    if not kind and (key not in _gh_user_type or now - at > GH_USER_TTL):
        kind = _gh_user_type_read(owner)
        _gh_user_type[key] = (now, kind)
    return ORG_BILLING.format(owner=owner) if kind == "Organization" else USER_BILLING


def ci_not_run_rows(spells: Mapping[str, Any] | None, now: datetime | None = None) -> list[dict[str, Any]]:
    """design §4.5a **Inbox row: CI not starting** (§4.4 *CI that never started is the person's*, TD-687):
    one row per spell the home keeps (`ci_spells` on `host`), under *Needs you*, counted: *GitHub
    Actions does not start in <owner>: billing or spending limit · samscrape #1097, #1099, samscrape
    main*, each PR a link, the reason GitHub's when it is not billing. The row stands for the spell's
    life, its items empty while the spell clears; it reads *re-run asked <age>* while a **Re-run**'s
    runs are pending. Keyed `ci_not_run:<owner in lower case>` — the attention store's snooze key and
    the Telegram line's `?row=`. **Open** is `billing_url`, filled by the page (`url`)."""
    at = now or datetime.now(UTC)
    out: list[dict[str, Any]] = []
    if not isinstance(spells, Mapping):  # a host record a hand or another build left odd costs the rows, not the page
        return out
    for key, spell in sorted(spells.items()):
        if not isinstance(spell, Mapping):
            continue
        owner = str(spell.get("owner") or key)
        row = spell.get("row") if isinstance(spell.get("row"), Mapping) else {}
        reason = CI_BILLING_REASON if row.get("kind") == "billing" else str(row.get("reason") or "")
        items = []
        for it in row.get("items") or []:
            if not isinstance(it, Mapping):
                continue
            repo = str(it.get("repo") or "")
            if isinstance(it.get("pr"), int):
                url = str(it.get("url") or "")  # GitHub's `html_url`; anything but https is drawn as text
                url = url if url.startswith("https://") else ""
                items.append({"repo": repo, "label": f"{repo} #{it['pr']}", "url": url})
            else:
                items.append({"repo": repo, "label": f"{repo} main", "url": ""})
        rerun = spell.get("rerun") if isinstance(spell.get("rerun"), Mapping) else {}
        pending = workorders_mod.ci_rerun_pending(dict(spell))
        head = f"GitHub Actions does not start in {owner}" + (f": {reason}" if reason else "")
        text = " · ".join(x for x in (head, ", ".join(i["label"] for i in items)) if x)
        since = str(spell.get("since") or "")
        sid = f"ci_not_run:{key.lower()}"
        out.append(
            {
                "row": "ci_not_run",
                "sid": sid,
                "id": sid,
                "name": owner,
                "owner": owner,
                "head": head,
                "parts": items,  # not `items`: the template would read the dict's method
                "url": "",
                "rerun_pending": pending,
                "rerun_at": str(rerun.get("at") or "") if pending else "",
                "rerun_age": _age(str(rerun.get("at") or ""), at) if pending else "",
                "subject": kind_subject("CI not starting", owner),
                "team": "",
                "at": since,
                "age": _age(since, at),
                "text": text,
                "find": " ".join(x for x in (owner, "CI not starting", text) if x),
            }
        )
    return out


def ci_not_run_kinds(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows with **Open**'s `url`, each owner's billing page (`billing_url`). Blocking on a first read."""
    return [{**r, "url": billing_url(str(r.get("owner") or ""))} for r in rows]


WORK_IDS = 5  # §4.5a *Inbox row: team start*: five ids at most, then *and n more*
# §4.5a *Inbox row: team start*, a stopped team's: the words after *stopped*, by `stopped.by` (TD-781)
STOPPED_BY = {"person": " by you", "until": " at its stop time"}


def work_ids(mark: Mapping[str, Any]) -> list[str]:
    """The ids of one `work_waiting` mark, each once, in its members' order (§6 rule 8)."""
    members = mark.get("members") if isinstance(mark.get("members"), Mapping) else {}
    return list(dict.fromkeys(str(i) for ids in members.values() if isinstance(ids, list) for i in ids))


def work_questions(mark: Mapping[str, Any]) -> list[dict[str, str]]:
    """A mark's question ends (§6 rule 8 *A question's end is work*, TD-274), each `{name, kind, ref,
    how, words}`: *designer-ao-1's steer about TD-222 lapsed to its default*, *… ask about TD-222 was
    answered*. Only a `steer` lapses, so a mark that names no kind reads a lapse as one and an
    answer as a *question*. Every part is the home's reading, never text a session wrote."""
    got = mark.get("questions") if isinstance(mark.get("questions"), list) else []
    out = []
    for q in got:
        if not isinstance(q, Mapping) or not q.get("ref"):
            continue
        how = str(q.get("how") or "")
        kind = str(q.get("kind") or ("steer" if how == "lapsed" else "question"))
        end = "lapsed to its default" if how == "lapsed" else "was answered"
        name, ref = str(q.get("name") or "a member"), str(q["ref"])
        out.append({"name": name, "kind": kind, "ref": ref, "how": how, "words": f"{name}'s {kind} about {ref} {end}"})
    return out


def work_held(held: Any, now: datetime) -> str:
    """Why rule 8's start was held back, in the row's words (§4.5a *Inbox row: team start*), from the
    mark's `held: {why, …}` — or "" for no hold, which is `on_work: ask`'s row."""
    if not isinstance(held, Mapping):
        return ""
    why = held.get("why")
    if why == "usage":
        left = _left(str(held.get("resets") or ""), now)  # "" with no reset on the hold, or one already past
        return f"{held.get('profile') or 'its profile'} is over its line" + (f", resets in {left}" if left else "")
    if why == "until":
        return "its stop time has passed"
    if why == "day":
        n = held.get("count")
        return f"started {n} time{'' if n == 1 else 's'} today"
    if why == "early":
        ago = _age(held.get("started"), now)
        return f"started {ago + ' ago' if ago else 'just now'} and wound down again"
    if why == "link":
        got = held.get("hosts")  # every down host; an older home names one, as `host`
        down = [str(h) for h in got if h] if isinstance(got, list) else []
        if len(down) > 1:
            return f"{', '.join(down[:-1])} and {down[-1]} are unreachable"
        return f"{(down[0] if down else held.get('host')) or 'a host'} is unreachable"
    if why == "nothing":
        return "no record to start"
    if why == "balance":
        lines = balance_mod.crossed_words(dict(held))
        return "its repo is over its line" + (f": {lines}" if lines else "")
    return str(why or "held")


def work_rows(
    work: Mapping[str, Any] | None,
    wound: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    records: Iterable[Mapping[str, Any]] = (),
    on_work: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """design §4.5a **Inbox row: team start** (§6 rule 8, TD-227 slice 3): one row per wound-down
    team whose lanes gained work, from the home's `work_waiting` (`work` on the `host` read) —
    *`<team>` · wound down <t> · its lanes gained n entries: TD-213, TD-214, TD-223*, five ids at
    most and *and n more*, each a link to the Repo page's entry made with the mark's `repo`. Every
    part is a structured reading, never text a session wrote. `wound` is `{team: instant}`, the
    card's own *wound down* reading; a team it does not name is drawn without the time. Under
    *Needs you*, counted, aged from the mark's `at`; under `on_work: start` the home keeps the mark
    only while a bound holds the start back, and the row says which (`held`). Keyed `work:<team>`
    in the attention store, so Snooze is by time alone.

    **A team that runs on** (§6 rule 8 *A member that finished while its team runs on*, TD-466): a
    team `wound` does not name, whose mark names members, reads *`<team>` · grinder-ao-1 finished <t>
    · its lane gained …* — each named member by its record's name and the instant it closed, from
    `records` (the page's own list) — and is `running`, so its **Start** posts `work_start`.

    **A team that stopped** (§6 rule 8 *A team that stopped*, TD-781: the mark carries `stopped: {by,
    at}`) is never read as one that runs on: *`<team>` · stopped by you <t> · its lanes gained …*, *by
    you* for `person`, *at its stop time* for `until`, nothing for `other`, `<t>` its `stopped.at`
    (`wound_down`, as the wound-down row's), and under `on_work: start` (`on_work`, the team's setting
    as `uiconf` last read it) *· not started: a stopped team is started by Start*. Its **Start** is the
    card's. `stopped` is its `by`; one the person stopped is `later`, which **Needs you** never takes."""
    at = now or datetime.now(UTC)
    on_work = on_work or uiconf.team_on_work
    out: list[dict[str, Any]] = []
    for team, mark in sorted((work or {}).items()):
        if not isinstance(mark, Mapping):
            continue
        # a question's end is its own clause, before the ids where both stand (TD-274)
        asked = work_questions(mark)
        refs = {q["ref"] for q in asked}
        ids = [i for i in work_ids(mark) if i not in refs]
        if not ids and not asked:
            continue
        stopped = mark.get("stopped") if isinstance(mark.get("stopped"), Mapping) else None
        by = str(stopped.get("by") or "other") if stopped else ""
        # a stopped team's instant is its stop's, never the card's *wound down* (TD-781)
        down = (str(stopped.get("at") or "") or None) if stopped else (wound or {}).get(team)
        repo = Path(str(mark.get("repo") or "")).name
        held = work_held(mark.get("held"), at)
        if stopped and not held and on_work(str(team)) == "start":
            held = "a stopped team is started by Start"  # rule 8 never starts it (§6, TD-781)
        n = len(ids)
        finished = work_finished(str(team), mark, records) if wound is not None and not down and not stopped else []
        lanes = ("its lane" if len(finished) == 1 else "their lanes") if finished else "its lanes"
        said = f"{lanes} gained {n} entr{'y' if n == 1 else 'ies'}: {', '.join(ids[:WORK_IDS])}" if ids else ""
        if n > WORK_IDS:
            said += f" and {n - WORK_IDS} more"
        said = "; ".join([*(q["words"] for q in asked), *([said] if said else [])])
        who = ", ".join(f"{f['name']} finished" + (f" {f['at']}" if f["at"] else "") for f in finished) or (
            "stopped" + STOPPED_BY.get(by, "") if stopped else "wound down"
        )
        out.append(
            {
                "row": "work",
                "sid": f"work:{team}",
                "id": f"work:{team}",
                "name": str(team),
                "team": str(team),
                # §4.10 *A subject on every entry*: *lanes gained 3 entries · ao-grind*; a row of
                # questions alone has no count to give, so its kind is the row's own, *team start*
                "subject": kind_subject(
                    f"lanes gained {n} entr{'y' if n == 1 else 'ies'}" if n else "team start", team
                ),
                "at": str(mark.get("at") or ""),
                "age": _age(mark.get("at"), at),
                "wound_down": str(down) if down else "",
                "repo": repo,
                "ids": ids[:WORK_IDS],
                "more": max(0, n - WORK_IDS),
                "n": n,
                "questions": asked,
                "held": held,
                "running": bool(finished),
                "finished": finished,
                "stopped": by,
                "stopped_words": STOPPED_BY.get(by, ""),
                "later": by == "person",  # under Later, uncounted and never told (§6 rule 8, TD-781)
                "lanes": lanes,
                "text": f"{team} · {who} · {said}" + (f" · not started: {held}" if held else ""),
                "find": " ".join(x for x in (str(team), "team start", who, said, held) if x),
            }
        )
    return out


def lanes_hold(got: Mapping[str, Any] | None) -> list[str] | None:
    """The distinct ids a `teamrun.lanes` reading matched (§6 rule 8 *A team with no record*, TD-781), or
    None where it says nothing: no reading, or a lane whose ledger could not be read — *unknown*, never empty."""
    if not got or any(r.get("n") is None for r in (got.get("roles") or {}).values()):
        return None
    return [str(i) for i in got.get("ids") or []]


def lanes_rows(
    teams: Iterable[Mapping[str, Any]],
    readings: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]] = (),
    on_work: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """design §4.5a **Inbox row: team start**, a defined team with **no record** (§6 rule 8 *A team with
    no record*, TD-781): the client's own row, under *Later*, uncounted and never told — *`<team>` ·
    stopped · its lanes hold n entries: TD-119*, five ids at most and *and n more*, from `readings`, the
    `teamrun.lanes` reading by team. `teams` is the definitions' rows (`teamrun.rows`). A team is drawn
    when no **unattended** record in `records` carries its badge (a person's own session in the team does
    not take the row away), its `on_work` is `ask` or `start`, and its lanes were read and hold an entry.
    **Start** is the card's and **Snooze ▾** is kept under `lanes:<team>`; nothing is stored, so no Dismiss."""
    on_work = on_work or uiconf.team_on_work
    manned = {str(r.get("team") or "") for r in records if r.get("unattended") and r.get("team")}
    out: list[dict[str, Any]] = []
    for row in teams:
        team = str(row.get("name") or "")
        if not team or team in manned or on_work(team) not in ("ask", "start"):
            continue
        ids = lanes_hold(readings.get(team))
        if not ids:
            continue
        n = len(ids)
        said = f"its lanes hold {n} entr{'y' if n == 1 else 'ies'}: {', '.join(ids[:WORK_IDS])}"
        if n > WORK_IDS:
            said += f" and {n - WORK_IDS} more"
        out.append(
            {
                "row": "lanes",
                "sid": f"lanes:{team}",
                "id": f"lanes:{team}",
                "name": team,
                "team": team,
                "subject": kind_subject(f"lanes hold {n} entr{'y' if n == 1 else 'ies'}", team),
                "at": "",
                "repo": Path(str(row.get("repo") or "")).name,
                "ids": ids[:WORK_IDS],
                "more": max(0, n - WORK_IDS),
                "n": n,
                "questions": [],
                "later": True,  # under Later, uncounted and never told (§6 rule 8, TD-781)
                "text": f"{team} · stopped · {said}",
                "find": " ".join((team, "team start", "stopped", said)),
            }
        )
    return out


def work_finished(team: str, mark: Mapping[str, Any], records: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    """The members a running team's mark names (§6 rule 8 *A member that finished while its team runs
    on*, TD-466), each `{name, at}` in the mark's order: the mark keys them by name, and the instant is
    the latest `closed_at` among the team's records under that name (a superseded record and its
    successor share one); a member the page holds no closed record of is drawn with no time."""
    members = mark.get("members") if isinstance(mark.get("members"), Mapping) else {}
    closed: dict[str, str] = {}
    for r in records:
        if isinstance(r, Mapping) and r.get("team") == team and r.get("closed_at"):
            name, at = str(r.get("name") or ""), str(r["closed_at"])
            closed[name] = max(closed.get(name, ""), at)
    return [{"name": str(m), "at": closed.get(str(m), "")} for m in members]


def work_note(mark: Any, now: datetime | None = None) -> dict[str, Any] | None:
    """design §4.5a team card **work waiting** note (§6 rule 8): *n entries waiting since <t>* beside
    *wound down <t>*, its tooltip the ids by member — `{n, at, age, title}`, or None for no mark."""
    if not isinstance(mark, Mapping) or not (ids := work_ids(mark)):
        return None
    members = mark.get("members") if isinstance(mark.get("members"), Mapping) else {}
    by = "; ".join(f"{m}: {', '.join(str(i) for i in got)}" for m, got in members.items() if isinstance(got, list))
    # a question's end is counted as one of the n and named in the tooltip (TD-271, TD-274)
    by = "; ".join([by, *(q["words"] for q in work_questions(mark))]) if by else by
    return {
        "n": len(ids),
        "at": str(mark.get("at") or ""),
        "age": _age(mark.get("at"), now or datetime.now(UTC)),
        "title": by,
    }


def work_started(members: Collection[Mapping[str, Any]], now: datetime | None = None) -> dict[str, Any] | None:
    """design §4.5a team card **work waiting** note on a live team: *started <t> for TD-213 and 2
    more*, from the newest `restarts` entry `why: work` on the team's live records (rule 8's start
    writes one on every record it replays) — `{at, age, first, more}`, or None. A start whose
    replays partly failed adds `n`, `of` and `failed`: every entry of one start carries its `start`
    instant and `of`, the records it set out to replay, and a failed replay leaves its entry, with
    `error`, on the ended record — *· 2 of 3 records started — manager-ao-1 did not*."""
    marks = [
        e
        for m in members
        if m.get("state") not in ("exited", "closed")
        for e in (m.get("restarts") or [])
        if isinstance(e, Mapping) and e.get("why") == "work" and e.get("at") and not e.get("error")
    ]
    if not marks:
        return None
    last = max(marks, key=lambda e: str(e["at"]))
    ids = [str(i) for i in last.get("ids") or []]
    out: dict[str, Any] = {
        "at": str(last["at"]),
        "age": _age(last["at"], now or datetime.now(UTC)),
        "first": ids[0] if ids else "",
        "more": max(0, len(ids) - 1),
    }
    start, of = last.get("start"), last.get("of")
    if start and isinstance(of, int):  # a home before the count writes neither, and the note says nothing of it
        same = [
            (m, e)
            for m in members
            for e in (m.get("restarts") or [])
            if isinstance(e, Mapping) and e.get("why") == "work" and e.get("start") == start
        ]
        # a failed replay's entry goes with the record's history onto whatever starts it later (a
        # crash restart, a person's Start), so a name that is live now did come up, whatever it carries
        up = {str(m.get("name") or m.get("id") or "") for m in members if m.get("state") not in ("exited", "closed")}
        names = (str(m.get("name") or m.get("id") or "") for m, e in same if e.get("error"))
        failed = [n for n in dict.fromkeys(names) if n not in up]
        if failed:
            out.update(n=of - len(failed), of=of, failed=failed)
    return out


def board_due_now(it: Mapping[str, Any]) -> bool:
    """Whether a reader's item is **due now** (§4.5 screen 6 *The board's horizon*): what the
    `--due-only` read surfaced, and so a counted *Needs you* row under every mode — a decided item
    whatever its date, one whose date could not be read (`due_error`), one due today or earlier; an
    undecided `fyi` item never (the reader's own `surfaces_at_start`, read here from its fields)."""
    if it.get("kind") == "fyi" and not it.get("decided"):
        return False
    return bool(it.get("decided")) or bool(it.get("due_error")) or it.get("overdue_days") is not None


def board_body(text: str, it: Mapping[str, Any]) -> str:
    """A board row's body (§4.5a *answers*, TD-255): the item's text without its `Answers:` and
    `Decided:` tails where the reader read them as fields — those are drawn as the row's buttons and
    its *decided* line, so the body does not print them twice. The reader's fields decide, never the
    prose: an item the reader gave no `answers` and no `decided` keeps its whole text."""
    fields = (it.get("answers") and lb.ANSWERS_RE, it.get("decided") and lb.DECIDED_RE)
    due = lb.DUE_RE.search(text)
    off = due.end() if due else 0  # the reader looks for the fields after the item's `Due:`
    starts = [m.start() for m in (f.search(text[off:]) for f in fields if f) if m]
    return text[: off + min(starts)].rstrip() if starts else text


# a board line's fields — its `Context:`, `Due:` and reply tails — are ledgerboard's to find (TD-585): the
# text drawn here is cut where ledgerboard's own patterns find them, never by a second pattern of ours


def _board_split(body: str, it: Mapping[str, Any]) -> tuple[str, str, list[dict[str, str]]]:
    """A board line's `(text, context, replies)`: its words with the `Due:` and the `Context:` cut out, what
    the `Context:` says, and the person's replies from the reader's field — a reader that gives none, or a
    tail after the `Due:` that is more than those replies, leaves them in the text."""
    replies = [
        {"by": str(r.get("by") or ""), "date": str(r.get("date") or ""), "text": str(r.get("text") or "")}
        for r in it.get("replies") or ()
        if isinstance(r, dict) and str(r.get("text") or "").strip()
    ]
    text, tail = body, ""
    due = lb.DUE_RE.search(body)
    if due:
        text, tail = body[: due.start()].rstrip(), body[due.end() :].lstrip(" .")
        if replies and tail.startswith("—") and len(lb.REPLY_TAIL_RE.findall(f" {tail}")) == len(replies):
            tail = ""  # the reader's replies, drawn from its field — every one of them, or none
        elif tail:
            replies = []  # what follows the `Due:` is not just the reader's replies: the text keeps it all, once
    if tail:
        text = f"{text} {tail}"
    ctx = lb.CONTEXT_RE.search(text)
    context = ctx.group("ctx").rstrip(" .") if ctx else ""
    if ctx:
        text = (text[: ctx.start()] + text[ctx.end() :]).rstrip()
    return text, context, replies


def board_text(body: str, it: Mapping[str, Any]) -> dict[str, Any]:
    """A board row's text as the row draws it (§4.5a *Inbox board row: text*, TD-279), from its
    `board_body`: `lead`, up to the end of its bold head and the sentence after it (`fold_head`),
    and `rest`, under *details*, ending with the line's `Context:` as a paragraph of its own; the
    `Due:` is the row's due words and goes, and the person's replies are `replies`, drawn under the
    text — from the reader's field, so a reader that gives none leaves them in the text. Display
    only: nothing here is a control."""
    text, context, replies = _board_split(body, it)
    lead, rest = rendermod.fold_head(text)
    rest = rendermod.part_heads(rest)  # a walk's **Part:** heads each open a paragraph
    if context:
        rest = f"{rest}\n\nContext: {context}" if rest else f"Context: {context}"
    for r in replies:
        d = _civil(r["date"])
        r["date"] = f"{d:%b} {d.day}" if d else r["date"]
    return {"lead": lead, "rest": rest, "replies": replies}


# a `Context:` reference into a named repo — `<repo>#TD-n` or `<repo>#n` — read for a card's *in <repo>*
_REPO_REF = re.compile(r"(?<![\w/.#-])(?P<repo>[A-Za-z0-9][\w.-]*)#(?:TD-\d+|\d+)\b")


def board_card(body: str, it: Mapping[str, Any], repo: str) -> dict[str, str]:
    """A board item as a Queue card draws it whole (§4.5 screen 12 *An item's shape*, *A board item says where
    its task is*; TD-1066, built by TD-1245): `sentence`, its bold head (`head_split`; a line with none, the
    line before its `Context:`); `leads`, the line's next sentence after the head where the item has no
    `Answers:`; `context`, under *context* — the prefix (kind, date, *(session … on <host>)*), the rest of the
    line and its `Context:`; and `in_repo`, the first repo other than `repo` the `Context:` names
    (`<repo>#TD-n`, `<repo>#n`), else "". Display only: nothing here is a control."""
    text, context, _ = _board_split(body, it)
    prefix, head, leads, after = rendermod.head_split(text)
    if it.get("answers"):
        leads, after = "", f"{leads} {after}".strip()
    here = repo.lower()
    in_repo = next((m.group("repo") for m in _REPO_REF.finditer(context) if m.group("repo").lower() != here), "")
    parts = [prefix, rendermod.part_heads(after), f"Context: {context}" if context else ""]
    return {
        "sentence": head,
        "leads": leads,
        "context": "\n\n".join(p for p in parts if p),
        "in_repo": in_repo,
    }


def live_look(it: Mapping[str, Any]) -> bool:
    """Whether a board item's answers are cadence's fixed pair for a live look (§3.5, design §4.5a
    **Works** / **Not right…**): a `look` (cadence §3.3's kind for it, dev-cadence TD-082) or a
    `watch` written before that kind (TD-292), whose two answers are *Works* and the form *Not
    right: <what>*. Anything else — a third answer, another kind, a complete *Not right: wrong
    repo* — is ordinary answer buttons."""
    answers = [" ".join(str(a).split()) for a in it.get("answers") or ()]
    return (
        str(it.get("kind") or "") in LOOK_KINDS
        and len(answers) == 2
        and answers[0] == WORKS
        and ledgerboard.is_not_right_form(answers[1])
    )


# §4.5a **Inbox row: a look** (§4.10 *A look*, TD-292 slice 3): the one directory a look's screenshots
# are served from, as origin's default branch holds it, and the names that may be asked of it —
# the shape and the count the host agent checks a look's `shots` against (`mail`, TD-292 slice 2).
# The reading itself is `sessionorc.shots`, the one the host agent makes for another host (TD-300).
SHOT_DIR = shots_mod.SHOT_DIR
SHOT_NAME = mail_mod.SHOT_NAME
SHOTS_MAX = mail_mod.SHOTS_MAX
SHOT_TTL = 60.0  # seconds a screenshot's presence on origin is kept: a row is redrawn on every poll
_shot_seen: dict[tuple[str, str], tuple[float, bool]] = {}
SHOT_WAIT = 2.0  # seconds a row waits for another host's answer: a hung node holds the Inbox no longer
_shot_host_down: dict[str, float] = {}  # a host that did not answer, by when: not asked again for `SHOT_TTL`
shot_root = shots_mod.root_of
shot_bytes = shots_mod.read


def _shot_on_origin(root: Path, name: str) -> bool:
    key, now = (str(root), name), time.monotonic()
    at, seen = _shot_seen.get(key, (0.0, False))
    if now - at > SHOT_TTL:
        seen = shots_mod.exists(root, name)
        _shot_seen[key] = (now, seen)
    return seen


def _shot_on_host(host: str, repo: str, name: str) -> bool:
    """The same test for a repo another host registers (TD-300): `host_shot` with `head`, asked
    through the home and kept `SHOT_TTL` as this host's is, waiting `SHOT_WAIT` and no longer. A host
    that cannot be asked, or does not answer in time, reads as not holding it — the row draws the
    name alone — and is not asked again, for any name, for `SHOT_TTL`."""
    key, now = (f"{host}:{repo}", name), time.monotonic()
    at, seen = _shot_seen.get(key, (0.0, False))
    if now - at > SHOT_TTL:
        if now - _shot_host_down.get(host, -SHOT_TTL - 1.0) <= SHOT_TTL:
            return False
        try:
            got = call_sync("host_shot", host=host, repo=repo, name=name, head=True, _timeout=SHOT_WAIT)
            seen = bool((got or {}).get("exists"))
        except Exception:  # noqa: BLE001 — whatever the transport raised, the image is not drawn
            _shot_host_down[host] = now
            seen = False
        _shot_seen[key] = (now, seen)
    return seen


def look_shots(shots: Any, repo: str, host: str = "") -> list[dict[str, str]]:
    """A look's screenshots as its row draws them (§4.5a **Inbox row: a look**): each of the
    envelope's `shots`, in the order sent, at most four — `name`, the file's name, and `url`, the
    image's address on this page when origin holds the file in the sender's repo (`repo`, a
    registered checkout's name), else "" and the row draws the name alone. The repo is read where
    the sender runs: this host's registry, or — `host`, the sender's record's, when it is another —
    that host's through the home (TD-300). A path outside `docs/mockups/reviews/` has no address,
    whatever its name."""
    if not isinstance(shots, list):
        return []
    there = host if host and host != host_name() else ""
    root = None if there else shot_root(repo)
    out: list[dict[str, str]] = []
    for raw in shots[:SHOTS_MAX]:
        if not isinstance(raw, str) or not raw.strip():
            continue
        p = Path(raw.strip().removeprefix("./"))
        url = ""
        if repo and p.parent == SHOT_DIR and SHOT_NAME.fullmatch(p.name):
            if there and _shot_on_host(there, repo, p.name):
                url = f"/repo/{quote(repo)}/shot/{quote(p.name)}?host={quote(there)}"
            elif root is not None and _shot_on_origin(root, p.name):
                url = f"/repo/{quote(repo)}/shot/{quote(p.name)}"
        out.append({"name": p.name, "url": url})
    return out


def look_pair(e: Mapping[str, Any]) -> bool:
    """Whether a mail row draws its answers as a live look's pair, **Works** / **Not right…**
    (§4.5a **Inbox row: a look**): an `ask` whose envelope carries `shots` and whose suggested
    answers are exactly *Works* and the form *Not right: <what>*. A look is known by its `shots`,
    never by its words; a `steer` look keeps its kind's row, and any other answers are ordinary."""
    shots = e.get("shots")
    answers = [" ".join(str(a).split()) for a in e.get("answers") or ()]
    return (
        e.get("kind") == "ask"
        and isinstance(shots, list)
        and any(isinstance(s, str) and s.strip() for s in shots)
        and len(answers) == 2
        and answers[0] == WORKS
        and ledgerboard.is_not_right_form(answers[1])
    )


def look_review(e: dict[str, Any], seat: str, seat_name: str, handed: Mapping[str, Mapping[str, Any]]) -> None:
    """§4.5a **Send to reviewer** (§4.10 *A look*, TD-292 slice 4b), on a look that is an open `ask`
    (it carries `shots`): with a reviewer already — `snoozed_for` names the `handed` `ask` that
    carries it — the row reads *with <seat> since <time>* from that entry in `handed` (by id, the
    holder's own copy the person's read lists), *a reviewer* where the read no longer lists it;
    otherwise the button is drawn when the sender's team has a techlead seat, `seat` being the id it
    takes as the page reads it from `org.yml` (the host agent reads none) and `seat_name` its name.
    Any other entry is left as it is."""
    if not e.get("shots") or e.get("kind") != "ask" or not _entry_open(e):
        return
    hid = str(e.get("snoozed_for") or "")
    if hid:
        h = handed.get(hid) or {}
        e["with_seat"] = str(h.get("holder_name") or h.get("holder") or "a reviewer")
        e["with_at"] = str(h.get("at") or "")
        e["with_since"] = _clock(h.get("at"))
        return
    if seat:
        e["review_seat"] = seat
        e["review_name"] = seat_name or seat


def board_head(text: str) -> str:
    """A board item's head, as the write-back's commit message names it: its first bold run, else
    the line, clipped."""
    words = ledgerboard.bold_head(text) or " ".join(text.split())
    return words if len(words) <= board_mod.HEAD_MAX else words[: board_mod.HEAD_MAX - 1].rstrip() + "…"


def _decided(it: Mapping[str, Any]) -> dict[str, str] | None:
    """The reader's `decided` as the row prints it — *decided: <text> · <date>* — or None."""
    got = it.get("decided")
    if not isinstance(got, dict) or not got.get("text"):
        return None
    d = _civil(got.get("date"))
    return {"text": str(got["text"]), "date": f"{d:%b} {d.day}" if d else str(got.get("date") or "")}


def _ahead_words(due: str, today: str, tag: str = "") -> str:
    """A not-yet-due item's due words, *due in 6 d · Oct 4*; an undated one's, *no due date*. An item
    that is not due now yet dated today or earlier — an undecided `fyi`, which the reader never
    surfaces as due — takes the reader's own words for it (*3d overdue*), never *due in -3 d*."""
    d, t = _civil(due), _civil(today)
    if d is None:
        return "no due date"
    if t is None:
        return f"due {d:%b} {d.day}"
    if d <= t:
        return tag or f"due {d:%b} {d.day}"
    return f"due in {(d - t).days} d · {d:%b} {d.day}"


def _civil(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v or ""))
    except ValueError:
        return None


# §4.5 screen 6 *A board item the person answered waits on them* (TD-303, built by TD-305): an
# answered row waits under *Waiting on them* until this many civil days from the answer's date, and
# then comes back to where it would be drawn unanswered, saying nobody has acted
BOARD_WAIT_DAYS = 3


def board_answered(it: Mapping[str, Any], today: str) -> dict[str, Any]:
    """Whom a reader's item waits on (§4.5 screen 6 *A board item the person answered waits on
    them*), from the reader's fields and never the prose: `answered` is `decided` when the reader
    says `waiting_on: session` (a reader that gives no `waiting_on`: its `decided`), else `replied`
    when an undecided item carries `replies`, else empty; `answered_at` the answer's date — the
    `decided` date, the last reply's — and `stale` whether `BOARD_WAIT_DAYS` or more civil days lie
    between it and the reader's `today`, with `stale_line` the words the row then says. A date that
    does not parse reads as not stale."""
    decided = it.get("waiting_on") == "session" if "waiting_on" in it else bool(it.get("decided"))
    replies = [r for r in it.get("replies") or () if isinstance(r, dict) and str(r.get("text") or "").strip()]
    if decided:
        got = it.get("decided")
        how, at = "decided", str(got.get("date") or "") if isinstance(got, dict) else ""
    elif replies:
        how, at = "replied", str(replies[-1].get("date") or "")
    else:
        return {"answered": "", "answered_at": "", "stale": False, "stale_line": ""}
    d, t = _civil(at), _civil(today)
    days = (t - d).days if d and t else None
    stale = days is not None and days >= BOARD_WAIT_DAYS
    line = f"{how} {d:%b} {d.day} — no session has acted in {days} d" if stale and d else ""
    return {"answered": how, "answered_at": at, "stale": stale, "stale_line": line}


def board_waiting_on(
    r: Mapping[str, Any], records: Collection[Mapping[str, Any]], now: datetime, starting: Collection[str] = ()
) -> str:
    """The *waiting on …* words of an answered board row (§4.5 screen 6, the standing of §4.5a as
    words): a live record with an unexpired declared lease on one of the item's `refs` or on the
    line's own work order (*waiting on grinder-ao-2 — holds TD-122*, *… — holds board:1a2b3c4d*),
    else a live record the item's `session` names, else — a decided line being a work order in the
    repo's lanes (§4.4 *Board write-back*, TD-384) — *pickable by <team>* naming the teams whose
    `free-pick` lanes take it, with each one's wound-down state when none of them is live (*· the
    start row is in Needs you* for a team in `starting`, the teams a *team start* row names, else
    *· <team> wound down — starts on `on_work`*, or *· <team> stopped — Start it* for a team that
    stopped rather than wound down, which rule 8 never starts, §6 *A team that stopped*, TD-781), else
    the next session to read the repo's board. Read from the fleet the page already holds, as
    `orphan_standing` reads it for mail; display only."""
    order = _board_order(r)
    holder, ref = _board_holder(r, records, now, order)
    if holder:
        return f"waiting on {holder} — holds {ref}"
    named = _board_named(r, records)
    if named:
        return f"waiting on {named}"
    if order:
        teams = _order_teams(r, order, records)
        if teams:
            words = f"pickable by {', '.join(teams)}"
            if not any(teams.values()):
                for t in teams:
                    if t in starting:
                        words += " · the start row is in Needs you"
                    elif _team_wound(t, records):
                        words += f" · {t} wound down — starts on `on_work`"
                    else:
                        words += f" · {t} stopped — Start it"
            return words
    return f"waiting on the next session to read {r.get('repo') or 'its repo'}'s board"


def _board_order(r: Mapping[str, Any]) -> str:
    """A board row's work order, `board:<key>` by its repo's own reader (TD-384), or empty: only a
    decided line that is not `fyi` is one."""
    if not r.get("decided") or r.get("kind") == "fyi" or not r.get("root"):
        return ""
    return str(r.get("key") or "") or workorders_mod.ref(str(r["root"]), str(r.get("text") or ""))


def _team_wound(team: str, records: Collection[Mapping[str, Any]]) -> bool:
    """Whether a team with nothing live reads *wound down* (`work.wound_down` over its crew's records, its
    seats left out), as the card reads it — else it *stopped* (§6 rule 8 *A team that stopped*, TD-781)."""
    mine = [dict(r) for r in records if isinstance(r, Mapping) and r.get("team") == team and not teamrun.persons(r)]
    return wound_down(mine, {str(r.get("name") or "") for r in mine if r.get("seat")}) is not None


def _order_teams(r: Mapping[str, Any], order: str, records: Collection[Mapping[str, Any]]) -> dict[str, bool]:
    """The teams whose `free-pick` lanes take a work order (§6 rule 6, `lane_matches`), from their
    records in the board's repo, live or ended, never one resumed as another — each `{team: live}`."""
    here = _resolved(str(r.get("root") or ""))
    if not here:
        return {}
    entry = {"id": order, "work_order": True, "pickable": "yes"}
    out: dict[str, bool] = {}
    for rec in records:
        if not isinstance(rec, Mapping) or not rec.get("team") or not rec.get("repo") or rec.get("superseded_by"):
            continue
        if _resolved(str(rec["repo"])) != here or not ledger_mod.lane_matches(list(rec.get("lane") or ()), entry):
            continue
        team = str(rec["team"])
        out[team] = out.get(team, False) or rec.get("state") not in mail_mod._NOT_LIVE
    return dict(sorted(out.items()))


@functools.lru_cache(maxsize=256)
def _resolved(path: str) -> str:
    """A path resolved once per process — a decided row asks it of every record on each poll — or
    empty for one that will not resolve (a NUL, a loop)."""
    try:
        return str(Path(path).resolve()) if path else ""
    except (OSError, ValueError, RuntimeError):
        return ""


def _board_holder(
    r: Mapping[str, Any], records: Collection[Mapping[str, Any]], now: datetime, order: str = ""
) -> tuple[str, str]:
    """The first live record with an unexpired declared lease on one of a board row's `refs`, or on
    its work order `order`, as `(name, ref)` — the session `board_reply` hands its note to — or
    `("", "")`."""
    for ref in [*(r.get("refs") or ()), *([order] if order else [])]:
        held = mail_mod.lease_holders(str(ref), records, now)
        if held:
            return str(held[0].get("name") or held[0].get("id") or ""), str(ref)
    return "", ""


def _board_named(r: Mapping[str, Any], records: Collection[Mapping[str, Any]]) -> str:
    """The name of a live record the board row's `session` names (its name, its id, or its tool's
    session id by the board's eight-character prefix), or empty."""
    sess = str(r.get("session") or "")
    if not sess:
        return ""
    for rec in records:
        if not isinstance(rec, Mapping) or rec.get("state") in mail_mod._NOT_LIVE:
            continue
        if sess in (rec.get("name"), rec.get("id")) or (
            len(sess) >= 8 and str(rec.get("adapter_id") or "").startswith(sess)
        ):
            return str(rec.get("name") or rec.get("id") or "")
    return ""


def board_standing(
    r: Mapping[str, Any], records: Collection[Mapping[str, Any]], now: datetime
) -> dict[str, str] | None:
    """A board row's **standing** (design §4.5a *Inbox board row: standing*, TD-142): where a Reply
    will go, said before the press — *still on TD-122 — grinder-ao-2 holds it* while a live record
    holds an unexpired declared lease on one of the item's `refs` (Reply mails it), else *moved on*
    while a live record carries the item's `session` name, else *gone*. `word` is `still on`,
    `moved on` or `gone`; `holder` and `ref` name the lease. None for an item the reader gave no
    `session` and no `refs`: nothing is known, so nothing is drawn. Read from the records the page
    already holds; display only — the home reads the leases again at the press."""
    if not r.get("session") and not r.get("refs"):
        return None
    holder, ref = _board_holder(r, records, now)
    if holder:
        return {"word": "still on", "holder": holder, "ref": ref, "text": f"still on {ref} — {holder} holds it"}
    word = "moved on" if _board_named(r, records) else "gone"
    return {"word": word, "holder": "", "ref": "", "text": word}


def board_standings(
    rows: Collection[dict[str, Any]], records: Collection[Mapping[str, Any]], now: datetime | None = None
) -> list[dict[str, Any]]:
    """`rows` as copies carrying their `standing` (`board_standing`) — copies, because the board
    rows are the page's cache, read again by the next request."""
    at = now or datetime.now(UTC)
    return [{**r, "standing": board_standing(r, records, at)} if r.get("row") == "board" else r for r in rows]


def with_standings(
    hz: Mapping[str, Any], records: Collection[Mapping[str, Any]], now: datetime | None = None
) -> dict[str, Any]:
    """A board horizon (`board_horizon`, `horizon_of`) whose drawn rows — due, coming up and the
    *not shown* fold — carry their `standing`; the answered rows under *Waiting on them* say
    *waiting on …* instead and are left as they are."""
    at = now or datetime.now(UTC)
    return {**hz, **{k: board_standings(hz.get(k) or (), records, at) for k in ("due", "ahead", "hidden")}}


def board_detail(it: Mapping[str, Any]) -> str:
    """An item's **detail block** (§4.5a *Inbox board row: detail block*, TD-312): the reader's
    `detail` lines joined as one text, drawn through the closed subset under the row's *details* —
    only when the key is a non-empty list of strings; anything else draws the row as it was. Data,
    never a field: nothing in it is read here."""
    got = it.get("detail")
    if not isinstance(got, list) or not got or not all(isinstance(x, str) for x in got):
        return ""
    return "\n".join(got).strip("\n")


def board_subject_text(text: str) -> str:
    """A board line's text before its `Due:` and without its `Context:` — what a head-less line's
    subject is cut from, so a headline never carries the due date or the answers after it."""
    due = lb.DUE_RE.search(text)
    return lb.CONTEXT_RE.sub("", text[: due.start()] if due else text).strip() or text


def board_rows(report: Any, repos_of: Mapping[str, Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """design §4.5a **Due strip / Inbox board row** rows, as the Inbox draws them (TD-069 step 3): one
    per open item of the report — its repo, its due words, the whole text, and the board at that
    line in the editor — with no team: the board is the repo's (TD-722, built by TD-741), so `repo`
    is the repo's words (`repo_boards`' `label`, *ContractMatch · samscrape* where its project has
    several repos), `repo_name` the rail's `repo` pick and `teams` every team whose repo it is; with
    `due_now` saying which are due (`board_due_now`) and `ahead` the due words of one that is not
    (TD-220). `at` is the due date, so *oldest first* in **Needs you**
    puts the longest overdue first among the states and the mail. The text is the board's, shown as
    text: nothing here is a control built from it (TD-071 item 8)."""
    rows: list[dict[str, Any]] = []
    today = str(report.get("today") or "") if isinstance(report, dict) else ""
    boards = report.get("boards") if isinstance(report, dict) else None
    for b in boards if isinstance(boards, list) else ():
        if not isinstance(b, dict):
            continue
        root = str(b.get("root") or "")
        board = str(b.get("board") or "")
        of = (repos_of or {}).get(str(Path(root).resolve()), {}) if root else {}
        repo_name = str(of.get("name") or (Path(root).name if root else ""))
        label = str(of.get("label") or b.get("label") or Path(root).name)
        teams = [str(t) for t in of.get("teams") or () if t]
        for it in b.get("items") or ():
            if not isinstance(it, dict) or not it.get("text"):
                continue
            line, text, tag = it.get("line"), str(it["text"]), str(it.get("due_tag") or "")
            detail = board_detail(it)
            # **Open board** is a file link at the item's line, the checkout first (§4.6, TD-689)
            url = editor_file_link(board, line=line if isinstance(line, int) else 1) if board else None
            rows.append(
                {
                    "row": "board",
                    "id": f"board:{root}:{line}",
                    # §4.4 *A board line's id* (TD-603): `board:<key>`, the host agent's reading's own
                    # (TD-615), drawn on the row and sent as `key` with every press; empty where none
                    "key": str(it.get("key") or ""),
                    "repo": label,
                    "repo_name": repo_name,
                    "root": root,
                    "board": board,
                    "line": line,
                    "team": "",
                    "teams": teams,
                    "text": text,
                    # §4.5a **answers** / **Go with it** (§4.4 *Decide*, TD-255): the reader's own
                    # fields, never read out of the prose here — the item's answers in the order
                    # written, the one marked default, what was decided, and the body without them
                    "body": board_body(text, it),
                    # §4.5a *Inbox board row: text* (TD-279): the body folded after its head, the
                    # `Context:` under *details*, the replies from the reader's field
                    **board_text(board_body(text, it), it),
                    # §4.5 screen 12 *An item's shape* (TD-1066): the same text as a card draws it whole
                    "card": board_card(board_body(text, it), it, repo_name),
                    "detail": detail,  # §4.5a *Inbox board row: detail block* (TD-312)
                    "answers": [str(a) for a in it.get("answers") or () if str(a).strip()],
                    "default": str(it.get("default") or ""),
                    "decided": _decided(it),
                    "kind": str(it.get("kind") or ""),
                    # §4.5a **Works** / **Not right…** (TD-255 slice 3): a live look's pair, known
                    # by its words; `head` and `name` are what the *Not right* hand-off sends
                    "pair": live_look(it),
                    "head": board_head(text),
                    # §4.10 *A subject on every entry*: the head line's *what's needed*, already its
                    # headline (cadence §3.3) — before the `Context:`, which is under *details*
                    "subject": mail_mod.clip_subject(board_head(board_subject_text(text))),
                    "name": Path(root).name if root else "",
                    "due": str(it.get("due") or ""),
                    "due_tag": tag,
                    "at": str(it.get("due") or ""),
                    "due_now": board_due_now(it),
                    "today": today,  # the reader's, which `board_horizon` measures days from
                    # §4.5 screen 6 *A board item the person answered waits on them* (TD-305): whom
                    # it waits on, and the reader's `session` and `refs` for the *waiting on* words
                    **board_answered(it, today),
                    "session": str(it.get("session") or ""),
                    "refs": [str(x) for x in it.get("refs") or () if str(x).strip()],
                    "due_error": bool(it.get("due_error")),
                    "ahead": "" if board_due_now(it) else _ahead_words(str(it.get("due") or ""), today, tag),
                    "editor": url,
                    # §4.5 screen 6 *Boards are read against origin* (TD-221): whether the board was
                    # read from origin (the reader's `source`, non-null only then) and the reader's
                    # sentence for what its fetch found, kept for the note above the repo's rows
                    "source": str(b.get("source") or ""),
                    "fetch_note": str(b.get("fetch_note") or ""),
                    # the case the read found and a skip's why, which the note is drawn from (TD-585)
                    "fetch_case": str(b.get("fetch_case") or ""),
                    "fetch_why": str(b.get("fetch_why") or ""),
                    "find": _find_text(label, text, tag, "board", detail),
                }
            )
    return rows


def board_horizon(rows: Collection[dict[str, Any]], mode: str | None = None, today: str = "") -> dict[str, Any]:
    """The board's horizon (design §4.5 screen 6, §5 `person.inbox.board_show`; TD-220): the board rows
    sorted into `due` — due now, a counted *Needs you* row under every mode — `ahead`, what the mode
    draws before it is due (*Board, coming up*), and `hidden`, what it does not (the *not shown*
    fold); soonest first, an undated item after the dated ones. `mode` is the setting as read,
    `next:10` when it is unset or does not parse; `today` is the reader's (each row carries it),
    for the days a `<n>d` reaches. A row with no `due_now` is due: a row from before TD-220 was the `--due-only` read's.
    An answered row that is not stale (`board_waits`, TD-305) is in none of the three but `waiting`,
    drawn under *Waiting on them* and taking no place.

    - `next:<n>`: per repo, the n soonest open items of its board, the due ones among them, so
      what is due takes places first; a due row whose date could not be read takes none. A board is
      the repo's and is counted once, whichever teams work the repo (TD-722, built by TD-741).
    - `due`: nothing ahead. `<n>d`: what falls due within n days of `today`; an undated item is
      hidden. `all`: every open item.

    `next_due` is the soonest date among the hidden, for the line (*the next due Oct 12*)."""
    try:
        mode = settings_mod.parse_board_show(mode)
    except ValueError:
        mode = settings_mod.BOARD_SHOW_DEFAULT
    waiting = [r for r in rows if board_waits(r)]
    rows = [r for r in rows if not board_waits(r)]
    due = [r for r in rows if r.get("due_now", True)]
    rest = sorted(
        (r for r in rows if not r.get("due_now", True)),
        key=lambda r: (not r.get("due"), str(r.get("due") or ""), str(r.get("repo") or ""), r.get("line") or 0),
    )
    ahead: list[dict[str, Any]] = []
    if mode == "all":
        ahead = rest
    elif mode.endswith("d"):
        t = _civil(today or next((r.get("today") for r in rows if r.get("today")), "")) or date.today()
        until = (t + timedelta(days=int(mode[:-1]))).isoformat()
        ahead = [r for r in rest if r.get("due") and str(r["due"]) <= until]
    elif mode.startswith("next:"):
        n = int(mode.split(":", 1)[1])

        def group(r: Mapping[str, Any]) -> str:
            return str(r.get("root") or r.get("repo") or "")

        places: dict[str, int] = {}
        for r in due:
            if not r.get("due_error"):
                places[group(r)] = places.get(group(r), 0) + 1
        for r in rest:
            g = group(r)
            if places.get(g, 0) < n:
                ahead.append(r)
                places[g] = places.get(g, 0) + 1
    shown = {id(r) for r in ahead}
    hidden = [r for r in rest if id(r) not in shown]
    now = str(today or next((r.get("today") for r in rows if r.get("today")), "")) or date.today().isoformat()
    return {
        "mode": mode,
        "due": due,
        "ahead": ahead,
        "hidden": hidden,
        "waiting": waiting,
        "next_due": _next_due(hidden, now),
        "today": now,
    }


def board_waits(r: Mapping[str, Any]) -> bool:
    """Whether a board row is drawn under *Waiting on them* (§4.5 screen 6, TD-305): answered, and
    not yet `BOARD_WAIT_DAYS` from the answer — in no count and out of the board's horizon."""
    return bool(r.get("answered")) and not r.get("stale")


def _next_due(hidden: Collection[Mapping[str, Any]], today: str) -> str:
    """The line's *the next due*: the soonest date among the hidden that is ahead of today — a hidden
    past-dated `fyi` is not what comes next."""
    dated = [str(r["due"]) for r in hidden if r.get("due") and str(r["due"]) > today]
    return min(dated) if dated else ""


def horizon_of(h: Mapping[str, Any], root: str | Path) -> dict[str, Any]:
    """The Repo page's *Waiting on you* (§4.5 screen 11): the Inbox's horizon filtered to one repo —
    the same rows the Inbox draws, each list cut to this checkout, and the line's next date from what
    is left hidden. The mode's places are the Inbox's, so a row is coming up here exactly when it is
    there."""
    want = str(Path(root).resolve())

    def mine(rs: Collection[Mapping[str, Any]]) -> list[Any]:
        return [r for r in rs if r.get("root") and str(Path(str(r["root"])).resolve()) == want]

    hidden = mine(h.get("hidden") or ())
    out = {**h, "due": mine(h.get("due") or ()), "ahead": mine(h.get("ahead") or ()), "hidden": hidden,
           "waiting": mine(h.get("waiting") or ()),
           "next_due": _next_due(hidden, str(h.get("today") or ""))}  # fmt: skip
    if h.get("line") is not None:  # the line says this repo's hidden count and next date, not the Inbox's
        out["line"] = board_line(out)
    return out


def horizon_left(h: Mapping[str, Any], ahead: Collection[Any], hidden: Collection[Any]) -> dict[str, Any]:
    """The Inbox's horizon once the lines a Queue card draws have left it (§4.5 screen 12 *What is attached to a
    card*, TD-828; `queue.split_later`): coming up and the *not shown* fold cut to what is left, and the line's
    count and next date read again from that fold, so a line drawn on a card is counted in neither."""
    hidden = list(hidden)
    out = {**h, "ahead": list(ahead), "hidden": hidden, "next_due": _next_due(hidden, str(h.get("today") or ""))}
    if h.get("line") is not None:
        out["line"] = board_line(out)
    return out


def board_line(h: Mapping[str, Any]) -> dict[str, Any]:
    """The line that closes the board rows (§4.5 screen 6 *The board's horizon*, §4.5a): the page
    saying its mode — *showing the next 10 board items per repo* — then what it hides, *14 not shown,
    the next due Oct 12*, or *nothing hidden*. `n` is the count hidden: with none there is no fold
    and no **show**."""
    mode = str(h.get("mode") or settings_mod.BOARD_SHOW_DEFAULT)
    if mode == "all":
        says = "showing every board item"
    elif mode == "due":
        says = "showing board items that are due"
    elif mode == "7d":
        says = "showing board items due this week"
    elif mode.endswith("d"):
        says = f"showing board items due within {mode[:-1]} days"
    else:
        n = int(mode.split(":", 1)[1]) if mode.startswith("next:") else 10
        says = f"showing the next {n} board item{'' if n == 1 else 's'} per repo"
    hidden = len(h.get("hidden") or ())
    nd = _civil(h.get("next_due"))
    if not hidden:
        rest = "nothing hidden"
    else:
        rest = f"{hidden} not shown" + (f", the next due {nd:%b} {nd.day}" if nd else "")
    return {"says": says, "rest": rest, "n": hidden}


def _needs_key(item: dict[str, Any]) -> tuple[int, str]:
    """The **Needs you** order (design §4.5 screen 6): *what is on the tool's clock first (a
    permission's countdown), then oldest first* — across states and mail together, which is why one
    key reads both."""
    if item.get("row") == "permission" and item.get("deadline"):
        return (0, str(item["deadline"]))
    return (1, str(item.get("at") or ""))


# design §4.10 *Outcomes*: the same predicate as `MailEntry.owes`, over the dict the RPC hands the
# page. It is duplicated rather than imported because the page reads entries, not models — and it
# is the *one* rule that decides which section a settled question is in, so it says so out loud.
OWING_CLOSES = ("replied", "go_with_it")
# …and **every** kind that can be one, which is not `PERSON_ASK_KINDS`: that pair is about which
# *open* entry is a question in *Needs you*, where a `steer` has its own branch. A debt is the
# model's `ASK_KINDS`, `steer` included — *a `go_with_it` close owes one too* (§4.10 *Outcomes*),
# and `go_with_it` is a `steer`'s own close reason. The agent enforces the debt on that set, so a
# narrower one here would leave a `steer`'s debt sitting in FYI, uncounted, while `ao progress
# none` was still refusing its sender (review of PR #287).
OWING_KINDS = ("ask", "steer")


def _owing(e: dict[str, Any], record: dict[str, Any] | None, now: datetime) -> None:
    """Stamp a question the person answered with what *Waiting on them* and *Needs you* need
    (§4.10 *Outcomes*, §4.5a): whether it still owes an outcome, how long it has owed it, what the
    person answered as far as the inbox still holds it, and whether its asker has **exited without
    reporting** — which is what moves the row into the counted section, because then only a person
    or the asker's manager can find out what happened.

    An asker whose record is **gone** is not this row: the home settles that as `asker_gone` and
    the question stops owing. `exited` is the live record that will not report by itself."""
    outcome = _outcome_of(e)
    e["owes"] = bool(
        "person" in (e.get("to") or [])
        and e.get("kind") in OWING_KINDS
        and e.get("closed_reason") in OWING_CLOSES
        and not outcome
    )
    e["owed_age"] = _age(e.get("closed_at"), now) if e["owes"] else ""
    # what the person answered, as far as the person inbox still holds it: a pressed suggested
    # answer is in the entry itself (§4.10 *Suggested answers*), and a typed reply is not — the
    # reply went to the asker's inbox, not to this one — so the row says which of the two it was
    # rather than inventing words the person did not write
    answers = e.get("answers") if isinstance(e.get("answers"), list) else []
    idx = e.get("answer")
    e["answer_given"] = str(answers[idx]) if isinstance(idx, int) and 0 <= idx < len(answers) else ""
    e["answer_how"] = "you let it go with its default" if e.get("closed_reason") == "go_with_it" else "you answered"
    e["asker_state"] = str((record or {}).get("state") or "")
    # the record here is the raw one off `list`, not a `view()` — so its `doing` is `{text, at}`
    # and the row wants `{text, age}`, as the card and the Focus header draw it (§4.8, TD-074)
    doing = (record or {}).get("doing")
    doing = doing if isinstance(doing, dict) else {}
    e["asker_doing"] = (
        {"text": str(doing.get("text") or ""), "age": _age(doing.get("at"), now)} if doing.get("text") else None
    )
    e["asker_gone_quiet"] = bool(e["owes"] and e["asker_state"] in ("exited", "closed"))
    if outcome:
        e["outcome_age"] = _age(outcome.get("at"), now)


def handed_rows(
    handed: Collection[dict[str, Any]], records: Mapping[str, dict[str, Any]], now: datetime
) -> list[dict[str, Any]]:
    """The entries the person handed a seat (§4.10 *An entry handed to a seat*, TD-219): the
    `inbox` read lists them as `handed` beside the person inbox, each the holder's own copy with
    `holder`, `holder_name` and `holder_state`, while it owes its outcome or came back `blocked`.
    Each becomes a row keyed `handed_row`, never `row` — it is mail, so its page (`/inbox/<id>`) and
    **Dismiss** reach it by its id as any entry's do. It waits on the seat, not on the holder: a seat
    that exited half way is filled again, so an exited holder is not the counted *asker gone quiet*
    of an answered question; only `blocked` is counted (`inbox_sections`)."""
    out = []
    for e in handed:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        holder = str(e.get("holder") or "")
        rec = records.get(holder) or {}
        doing = rec.get("doing") if isinstance(rec.get("doing"), dict) else {}
        entry = e.get("entry") if isinstance(e.get("entry"), dict) else {}
        out.append(
            {
                **e,
                "handed_row": True,
                "entry": entry,
                "team": e.get("team") or rec.get("team") or "",
                "from_name": "you",
                "holder_name": str(e.get("holder_name") or rec.get("name") or holder),
                "holder_state": str(e.get("holder_state") or rec.get("state") or ""),
                "holder_open": holder if holder in records else "",
                "holder_doing": (
                    {"text": str(doing.get("text") or ""), "age": _age(doing.get("at"), now)}
                    if doing.get("text")
                    else None
                ),
                "age": _age(e.get("at"), now),
                "outcome_age": _age(_outcome_of(e).get("at"), now) if _outcome_of(e) else "",
            }
        )
    return out


def _outcome_of(e: dict[str, Any]) -> dict[str, Any]:
    """An entry's `outcome` (§4.10 *Outcomes*) as a dict, or `{}` — read as a shape, never trusted:
    an entry from another build may carry anything there and it must cost a row a line, not the
    page (the `_age` rule)."""
    o = e.get("outcome")
    return o if isinstance(o, dict) else {}


def _answered_of(e: dict[str, Any]) -> dict[str, Any]:
    """An entry's `answered` (§4.9b, TD-075 step 2) as a dict, or `{}` — the structured field the
    home writes on an *answered for you* FYI, `{question, asker, answerer, source}`. The row and its
    **Overrule** key on it and on nothing else: never on who sent the entry, never on a role (§9
    invariant 9). Read as a shape, as `_outcome_of` is."""
    a = e.get("answered")
    return a if isinstance(a, dict) and a else {}


def _trail_rows(trail: Collection[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """The trail as FYI rows (§4.10 *The Inbox is a queue*, TD-079): what a state row's **ending**
    left behind, so a row that resolved by some other road does not simply vanish. The home writes
    these, and they are not mail — the page gives them `at` and `age` so they sort and read beside
    the entries, and a `row` of `trail` so one renderer draws them."""
    out = []
    for t in trail:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        at = str(t.get("last") or t.get("resolved_at") or "")
        # *up for* is how long the row **stood**, which is its ending minus its start — not its
        # age now, which is a different number and the one a reader would misread it as
        ended = _instant(at) or now
        out.append({**t, "row": "trail", "at": at, "age": _age(at, now), "for_words": _age(t.get("since"), ended)})
    return out


def _orphan_held(e: dict[str, Any]) -> bool:
    """An orphaned `steer` whose bound the home cleared (design §4.10 *An orphaned `steer` does not
    lapse*): nobody is left to take its default, so from its bound it waits on the person — under
    *Needs you* and counted, as a paused one is. With its clock still running it is *Steering*."""
    return e.get("kind") == "steer" and bool(e.get("orphaned")) and not e.get("bound")


def inbox_sections(
    entries: Collection[dict[str, Any]],
    *,
    now: datetime | None = None,
    states: Collection[dict[str, Any]] = (),
    trail: Collection[dict[str, Any]] = (),
    attention_snoozed: dict[str, Any] | None = None,
    boards: Collection[dict[str, Any]] = (),
    handed: Collection[dict[str, Any]] = (),
    fleet: Collection[Mapping[str, Any]] = (),
    cards: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Design §4.5 screen 6: the person inbox split into the page's three sections, plus what is
    snoozed — and, from TD-069 step 2, the **session states** (`states`, from `state_rows`) joined
    into **Needs you** here rather than anywhere else. From step 3 the due **board items**
    (`boards`, from `board_rows`) join it the same way, counted: a due board item is waiting on a
    person by definition. They carry no snooze of the Inbox's own: a board row's Snooze is §4.4's
    write-back, which moves its `Due:` date on the board itself.

    - **Needs you** — the state rows, open `ask`s to the person and **paused** `steer`s; oldest first.
    - **Steering** — open `steer`s whose clock is running; soonest bound first, and a `steer`
      that somehow carries no bound last.
    - **FYI** — everything else: `note`s, `system` notes, replies, and every closed entry until
      retention prunes it (`MAIL_RETENTION`, 12 h); newest first, because the useful end of a list
      nobody must act on is the recent end.
    - **Snoozed** — an entry whose `snoozed_until` is still ahead is in none of the three and in
      no count (§4.10 *Snooze*); soonest first, so the page can draw the **Snoozed (n)** fold and a
      snooze is never a way to lose mail.

    `count` is the **Needs you** section's length, which is the top bar's number (§4.5a): what is
    waiting on a person, never unread mail. One computation, used by the page and by the poll.
    An unreadable `snoozed_until` reads as *not snoozed*: mail is never hidden by a bad field.

    - **Waiting on them** (§4.10 *Outcomes*, TD-079 step 2) — answered questions that owe an
      outcome and whose asker is still live: it waits on a session, not on the person, so it is in
      neither number. A debt whose asker **exited without reporting** is in *Needs you* instead,
      counted — only a person, or the asker's manager, can find out what happened — and so is a
      **`blocked`** outcome, which is not a dead end but work stopped on something only a person
      can move. A `done` or `dropped` outcome is FYI, shown under the question it closes.
      **An entry the person handed a seat** (`handed`, from `handed_rows`; §4.10 *An entry handed
      to a seat*, TD-219) waits here from the press until its outcome, whatever its holder's state
      — a seat that exited is filled again — and is in *Needs you*, counted, once it came back
      `blocked`. A `done` or `dropped` one is no longer listed by the read, so it is in neither.
      **A board item the person answered** (§4.5 screen 6, TD-305) — decided, or replied to — waits
      here, uncounted, whatever its `Due:`, until `BOARD_WAIT_DAYS` from the answer (`board_waits`);
      then it is where it would be unanswered, saying so. Its *waiting on …* words are read from
      `fleet`, the records the request already holds.

    **A state row's snooze** (§4.10 *The Inbox is a queue*, TD-079 step 1b) lives in the home's own
    attention store, per record and row kind, because a state has no mail entry to carry one:
    `attention_snoozed` is that store as the RPC hands it over, and a row whose time is still
    ahead is in no section and no count, exactly as a snoozed entry is.

    The **trail** (§4.10) is FYI too: what a state row's ending left behind, so a row that resolved
    by some other road — the session was resumed, the permission was answered in the terminal —
    does not simply vanish.

    - **Answered for you** (§4.9b, TD-075 step 2) — the FYI the home files when a teammate answers
      a question from the record (a reply carrying `source`): it carries `answered`, and is here
      instead of in FYI, uncounted, newest first, so what was decided in the person's name is
      never mixed in with the notes.

    - **Later** (§6 rule 8 *A team that stopped*, *A team with no record*; TD-781, built by TD-782) — a
      state row carrying `later`: the *team start* row of a team the person stopped, and a defined
      team with no record's (`lanes_rows`). Uncounted, snoozed as any state row is.

    **Where a row is drawn** (§4.5 screen 6, TD-748, built by TD-771): with `cards`, the open Queue
    cards' entries (`ui.queue.card_index`), every row is tagged `home: inbox|queue` with the `on_card` and
    `on_row` it is drawn on and its `mentions` (`ui.queue.item_home`); a view rule, so the sections and the
    counts are what they were, and `queue_n` is how many counted rows the Queue draws. Without `cards`
    every row is `home: inbox`."""
    at = now or datetime.now(UTC)
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in INBOX_SECTIONS}
    snoozed_rows = attention_snoozed or {}
    for r in states:
        raw = snoozed_rows.get(f"{r.get('sid') or ''}|{r.get('row') or ''}")
        if r.get("fyi") and not (r.get("auto_row") and _iso(raw) and _iso(raw) > at):
            # a promote in flight, or one `auto` will make (§4.5a *Inbox row: promote*): FYI, uncounted;
            # the `auto` row has Snooze ▾, so a snoozed one is set aside as any row is
            out["fyi"].append(r)
            continue
        if isinstance(raw, str) and raw.startswith("dismissed:"):
            # the restart row's **Dismiss** (§4.5a, TD-103): that one mark's row is gone from every
            # section; a new mark carries a new `at` and raises a new row
            if raw == f"dismissed:{r.get('at') or ''}":
                continue
            raw = None
        until = _iso(raw)
        if until and until > at:
            out["snoozed"].append({**r, "snoozed_until": str(raw), "until_words": _left(str(raw), at)})
        elif r.get("later"):
            # a stopped team's row the person stopped, and a team with no record's (§6 rule 8, TD-781):
            # *Later*'s, never counted
            out["later"].append(r)
        else:
            out["needs"].append(r)
    # The outcome `note` that settles a question is an ordinary entry in its own right, and is
    # **listed under its question** rather than beside it (§4.10 *Outcomes*) — so it is taken out
    # of the FYI list here and hung on the question's own row by `id`.
    settles = {str(_outcome_of(e)["by"]): e["id"] for e in entries if _outcome_of(e).get("by")}
    for e in entries:
        snoozed = _iso(e.get("snoozed_until"))
        outcome = _outcome_of(e)
        question = e.get("kind") in (*PERSON_ASK_KINDS, "steer")
        if (snoozed and snoozed > at and (_entry_open(e) or not question)) or (e.get("snoozed_for") and _entry_open(e)):
            # a look with a reviewer (`snoozed_for`, §4.5a **Send to reviewer**) is set aside until
            # that debt closes, which clears the field: listed with the snoozed, in no count. A
            # question closed while snoozed is not: a press that answers or closes it ends the
            # snooze with it, and it is listed by its close (§4.10 *Snooze*, TD-373)
            out["snoozed"].append(e)
        elif _entry_open(e) and (e.get("kind") in PERSON_ASK_KINDS or e.get("paused_at") or _orphan_held(e)):
            out["needs"].append(e)
        elif _entry_open(e) and e.get("kind") == "steer":
            out["steering"].append(e)
        elif outcome and outcome.get("state") == "blocked":
            out["needs"].append(e)  # counted: work stopped on something only a person can move
        elif e.get("owes"):
            # the asker exited without reporting: only a person or its manager can find out what
            # happened, so that one is counted; the rest wait on a live session and are not
            (out["needs"] if e.get("asker_gone_quiet") else out["waiting"]).append(e)
        elif _answered_of(e):
            out["answered"].append(e)  # §4.9b: uncounted, and apart from FYI's notes
        elif e["id"] in settles:
            continue  # the reporting note: drawn under the question it closes, not beside it
        else:
            out["fyi"].append(e)
    for e in handed:
        out["needs" if _outcome_of(e).get("state") == "blocked" else "waiting"].append(e)
    out["fyi"].extend(_trail_rows(trail or (), at))
    # the teams a *team start* row names (§6 rule 8): a decided line pickable by one says so (TD-384)
    starting = {str(x.get("team") or "") for x in states if x.get("row") == "work"}
    for r in boards:
        if board_waits(r):
            # a copy: the board rows are the page's cache, read again by the next request
            out["waiting"].append({**r, "waiting_on": board_waiting_on(r, fleet, at, starting)})
        else:
            out["needs"].append({**r, "standing": board_standing(r, fleet, at)})
    out["needs"].sort(key=_needs_key)
    out["steering"].sort(key=lambda e: (not e.get("bound"), str(e.get("bound") or "")))
    out["waiting"].sort(key=lambda e: str(e.get("closed_at") or e.get("answered_at") or e.get("at") or ""))
    out["answered"].sort(key=lambda e: str(e.get("at") or ""), reverse=True)
    out["fyi"].sort(key=lambda e: str(e.get("at") or ""), reverse=True)
    out["snoozed"].sort(key=lambda e: str(e.get("snoozed_until") or ""))
    # the Org rollup's *m overdue* beside *in the Inbox* (§4.5 screen 1, §4.5a *Sessions: rollup*, TD-178):
    # the Needs you board items past their `Due:` date — a civil date, so read in this host's calendar
    today = at.astimezone().date().isoformat()
    overdue = sum(1 for e in out["needs"] if e.get("row") == "board" and e.get("due") and str(e["due"]) < today)
    for k, rows in out.items():
        # a snoozed row stays the Inbox's: the Queue has no Snooze (§4.5 screen 12)
        out[k] = [{**e, **item_home(e, cards if k != "snoozed" else None)} for e in rows]
    queue_n = sum(1 for e in out["needs"] if e["home"] == "queue")
    return {**out, "count": len(out["needs"]), "fyi_n": len(out["fyi"]), "overdue_n": overdue, "queue_n": queue_n}


# -- the rail (design §4.5 screen 6 *The rail* and *Find*, §4.5a **Inbox page: the rail**; TD-129,
# built by TD-135) ----------------------------------------------------------------------------------

# *Urgency*: the page's own sections in the page's order. The snoozed list is not one of them: it
# is in no section and no count (§4.10 *Snooze*).
# *Later* (TD-565) is the board's rows coming up, the fold's once opened, and the ledger's *for you*
# rows, its own boxes the poll puts back, and the team start rows a stopped team's own Stop or a team
# with no record draws (§6 rule 8, TD-781), which are `INBOX_SECTIONS`' `later`.
RAIL_SECTIONS = ("needs", "steering", "waiting", "answered", "later", "fyi")
RAIL_SECTION_NAMES = {
    "needs": "Needs you",
    "steering": "Steering",
    "waiting": "Waiting on them",
    "answered": "Answered for you",
    "later": "Later",
    "fyi": "FYI",
}
# *Kinds*: a row's coarse kind, one per line (§4.5 screen 6 *The rail*)
RAIL_KINDS = ("questions", "steering", "states", "board", "ledger", "notes", "trail")
RAIL_KIND_NAMES = {
    "questions": "questions",
    "steering": "steering",
    "states": "session states",
    "board": "board items",
    "ledger": "ledger entries",
    "notes": "notes",
    "trail": "trail",
}
# the board's rows coming up and the fold's (TD-220) are drawn under *Later* (TD-565) and counted
# and picked with it: a section pick, a section line and a heading read them as *Later*
RAIL_UNDER = {"coming": "later", "unshown": "later"}
RAIL_NO_TEAM = "none"  # a row that carries no team, in the URL and on the rail's *no team* line
_FIND_EDGE = ",.;:!?()[]{}\"'“”‘’<>"


def rail_kind(e: Mapping[str, Any]) -> str:
    """A row's coarse kind (§4.5 screen 6 *The rail*): *questions* (an `ask`, a passed-up
    question), *steering* (a `steer`), *session states* (every state row, alarms
    included), *board items*, *notes* (a `note`, a `system` note, a reply, answered-for-you, an
    outcome), *trail*."""
    row = e.get("row")
    if row == "board":
        return "board"
    if row == "trail":
        return "trail"
    if row == "ledger":
        return "ledger"
    if row:
        return "states"
    if e.get("kind") in PERSON_ASK_KINDS or e.get("passed_up"):
        return "questions"
    if e.get("kind") == "steer":
        return "steering"
    return "notes"


def row_find(e: Mapping[str, Any], section: str = "") -> str:
    """The row's whole visible text, lowercased once, which the find matches every word against
    (§4.5 screen 6 *Find*): a mail row's sender, team, kind, `about`, PR, text and subject; the rows
    the home builds carry their own (`find` on a state, alarm or board row) and their subject; a
    trail row its name, kind, `how` and text. `data-find` on every row kind is this."""
    row = e.get("row")
    if row == "trail":
        return _find_text(e.get("name"), e.get("team"), e.get("kind"), "trail", e.get("how"), e.get("text"))
    if row == "ledger":
        return _find_text(e.get("id"), e.get("title"), e.get("name"), e.get("team"), e.get("kind"), e.get("held"))
    if row:  # the home's own text for the row, its subject, and its team and pill, which the row draws too
        return _with_subject(_find_text(e.get("find"), e.get("team"), e.get("state_label")), e)
    answered = e.get("answered") if section == "answered" and isinstance(e.get("answered"), dict) else {}
    pr = e.get("pr")
    found = _find_text(
        e.get("from_name") or e.get("from"),
        e.get("team"),
        e.get("kind"),
        e.get("about"),
        f"#{pr}" if isinstance(pr, int) and not isinstance(pr, bool) else "",
        e.get("text"),
        e.get("asker_name") if answered else "",
        answered.get("question") if answered else "",
        answered.get("source") if answered else "",
        # a prompt the person's rules answered names them as who answered (§4.5a, TD-641), so finds by it
        "your permissions: rules" if answered.get("answerer") == mail_mod.RULES else "",
    )
    return _with_subject(found, e)


def _with_subject(found: str, e: Mapping[str, Any]) -> str:
    """A row's find text and its subject, the subject added once and only where the text does not
    already hold it — a subject derived from the text is its first sentence."""
    subject = row_subject(e).lower()
    return f"{found} {subject}".strip() if subject and subject not in found else found


templates.env.globals["rail_kind"] = rail_kind
templates.env.globals["row_find"] = row_find
templates.env.globals["row_subject"] = row_subject
templates.env.globals["rail_sections"] = RAIL_SECTIONS
templates.env.globals["rail_section_names"] = RAIL_SECTION_NAMES
templates.env.globals["rail_kinds"] = RAIL_KINDS
templates.env.globals["rail_kind_names"] = RAIL_KIND_NAMES


def find_words(find: str) -> list[str]:
    """The find's words (§4.5 screen 6 *Find*): lowercased, and a word's edge punctuation dropped,
    so *517,* finds what *517* does; a `#` is kept, and a bare number finds *#517* as a substring
    of it anyway."""
    return [w for w in (x.strip(_FIND_EDGE) for x in str(find or "").lower().split()) if w]


def find_matches(text: str, words: Collection[str]) -> bool:
    """Every word must match, in any order, as a substring of the row's text."""
    return all(w in text for w in words)


def rail_picks(query: Mapping[str, Any]) -> dict[str, Any]:
    """The picks a page's URL carries (§4.5 screen 6 *The rail*): `team`, `repo`, `sec` and `kind` as
    comma lists — `none` is *no team* — and `find`. An unknown section or kind is dropped, never an error:
    a link survives a renamed line by showing a little more."""

    def lst(key: str) -> list[str]:
        return [x.strip() for x in str(query.get(key) or "").split(",") if x.strip()]

    return {
        "team": lst("team"),
        "repo": lst("repo"),
        "sec": [x for x in lst("sec") if x in RAIL_SECTIONS],
        "kind": [x for x in lst("kind") if x in RAIL_KINDS],
        "find": str(query.get("find") or "").strip(),
    }


def rail_rows(
    sections: Mapping[str, Any],
    ahead: Collection[Mapping[str, Any]] = (),
    ledger: Collection[Mapping[str, Any]] = (),
) -> list[dict[str, str]]:
    """Every row on the page that the rail counts, as the things a pick reads: its section, its teams
    (`none` for no team), its repo, coarse kind and find text. A board row carries its repo (`repo`,
    the pick's value, and `repo_label`, its words) and, as its teams, every team whose repo it is —
    `none` where no team works it — so a team pick narrows board rows to the team's repo (TD-722,
    built by TD-741); every other row carries its one team and no repo. The snoozed list is in no count, and
    a row the Queue draws (`home: queue`) is on no line here. `ahead` is
    the board's rows coming up (TD-220), in section `coming`, and `ledger` the ledger's *for you*
    rows (`ledger_rows`), in section `later`: both counted under *Later* (TD-565); the fold's rows
    (`unshown`) join only once it is opened, in the browser."""
    return [
        {
            "section": sec,
            "teams": _rail_teams(e),
            "repo": str(e.get("repo_name") or "") if e.get("row") == "board" else "",
            "repo_label": str(e.get("repo") or e.get("repo_name") or "") if e.get("row") == "board" else "",
            "kind": rail_kind(e),
            "find": row_find(e, sec),
        }
        for sec, rows in [*((s, sections.get(s) or ()) for s in RAIL_SECTIONS), ("coming", ahead), ("later", ledger)]
        for e in rows
        if e.get("home") != "queue"  # drawn on its Queue card, not on this page (§4.5 screen 6 *Where a row is drawn*)
    ]


def _rail_teams(e: Mapping[str, Any]) -> list[str]:
    """The teams a row is counted under and picked by: a board row's are its repo's (TD-741)."""
    if e.get("row") == "board":
        return [str(t) for t in e.get("teams") or () if t] or [RAIL_NO_TEAM]
    return [str(e.get("team") or "") or RAIL_NO_TEAM]


def rail_counts(rows: Collection[Mapping[str, Any]], picks: Mapping[str, Any]) -> dict[str, Any]:
    """The rail's counts and the section headings' (§4.5 screen 6 *The rail*): **every count is a
    count of rows on the page now**. Within a group the picks are OR'd, across groups AND'd, and a
    group with nothing picked means all of it; the find is a fourth group. For a line: a picked line
    reads its share of the page; an unpicked line in a group with a pick reads 0; an unpicked line
    in a group without one reads its share under the other groups' picks. `all` is the line's count
    with no filter at all. A **team** line counts that team's *Needs you* rows — *which team needs
    me* (TD-135's steer to the techlead, 2026-09-25) — a board row among them under each team whose
    repo it is, so a team's count and the page narrowed to it agree; a **repo** line counts that
    repo's *Needs you* rows the same way (TD-741). `app.js`'s `AO.railCounts` is this function
    again, over the rows in the DOM, and a test holds the two to one answer."""
    words = find_words(picks.get("find") or "")
    pick = {g: set(picks.get(g) or ()) for g in ("team", "repo", "sec", "kind")}

    def vals(r: Mapping[str, Any], group: str) -> list[str]:
        if group == "team":
            return list(r["teams"])
        if group == "repo":
            return [r["repo"]] if r["repo"] else []
        return [RAIL_UNDER.get(r["section"], r["section"])] if group == "sec" else [r["kind"]]

    def passes(r: Mapping[str, Any], skip: str = "") -> bool:
        for g, want in pick.items():
            if g != skip and want and not want.intersection(vals(r, g)):
                return False
        return find_matches(r["find"], words)

    teams = sorted({t for r in rows for t in r["teams"] if t != RAIL_NO_TEAM})
    if any(RAIL_NO_TEAM in r["teams"] for r in rows):
        teams.append(RAIL_NO_TEAM)
    # a picked team no row carries still gets its line, so the pick can be undone
    teams += [t for t in picks.get("team") or () if t not in teams]
    labels: dict[str, str] = {}
    for r in rows:
        if r["repo"]:
            labels.setdefault(r["repo"], r["repo_label"] or r["repo"])
    repos = sorted(labels)
    repos += [x for x in picks.get("repo") or () if x not in repos]

    def line(group: str, value: str, among: Collection[Mapping[str, Any]]) -> dict[str, int]:
        mine = [r for r in among if value in vals(r, group)]
        shown = 0 if pick[group] and value not in pick[group] else sum(1 for r in mine if passes(r, group))
        return {"shown": shown, "all": len(mine)}

    needs = [r for r in rows if r["section"] == "needs"]
    return {
        "filtered": bool(pick["team"] or pick["repo"] or pick["sec"] or pick["kind"] or words),
        "sections": {s: line("sec", s, rows) for s in RAIL_SECTIONS},
        "teams": {t: line("team", t, needs) for t in teams},
        "team_order": teams,
        "repos": {x: line("repo", x, needs) for x in repos},
        "repo_order": repos,
        "repo_labels": {x: labels.get(x, x) for x in repos},
        "kinds": {k: line("kind", k, rows) for k in RAIL_KINDS},
        "heads": {
            s: {
                "shown": sum(1 for r in rows if vals(r, "sec") == [s] and passes(r)),
                "all": sum(1 for r in rows if vals(r, "sec") == [s]),
            }
            for s in RAIL_SECTIONS
        },
    }


# the page computes its rail from its sections when a caller did not (a test rendering the template
# directly, as the rows are shaped by `shaped` and `suggested_answers` whoever renders them)
templates.env.globals["rail_picks"] = rail_picks
templates.env.globals["look_pair"] = look_pair
templates.env.globals["rail_rows"] = rail_rows
templates.env.globals["rail_counts"] = rail_counts


def _added_words(day: str) -> str:
    """A ledger row's age words from its `Added:` date (§4.5a **Inbox row: ledger entry**):
    *added Oct 7*, the year after it when it is not this year's; nothing for a date it cannot read."""
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return ""
    words = f"added {d.strftime('%b')} {d.day}"
    return words if d.year == date.today().year else f"{words}, {d.year}"


def ledger_rows(lf: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """`ledger_for_you`'s rows, every group's, in its order: what the rail counts under *Later*."""
    return [r for g in (lf or {}).get("groups") or () for r in g.get("rows") or ()]


def ledger_for_you(
    repos: Mapping[str, Any],
    fleet: Collection[dict[str, Any]],
    named: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The ledger's rows of the Inbox's **Later** section (design §4.5 screen 6 *The ledger's entries
    that wait on you*, §4.5a **Inbox row: ledger entry**, TD-368, TD-565): the entries §4.4 *Repo
    facts* sorts *for you* in the home's repo facts (`repos`, keyed by checkout, in the registry's
    order), one group per repo with any, each in the Repo page's order (priority, then id). A row is
    a mail row's shape — `row: "ledger"`, its `kind` (*ledger · yours* for `Owner: paul`, *ledger ·
    your decision* for a `decision (paul)` item), `name` the repo, `team`, `at` its `Added:` date and
    `added` its words, `pri`, `held`, `title`, `detail`, `answers`, `default` (the default's text),
    `root` and `url`, and for **Start session** (TD-678) the entry's `type`, `why` (`yours` or
    `decision`) and `holder`, the id of the first live record claiming it — with `held` the names of
    the live records of that repo claiming it; an entry an
    open decided line's `Context:` names (the repo's work orders' `refs`) is left out; the team the
    rail's *Teams* picks filter by — the definitions' team for the repo (`named`, by resolved
    checkout), else the team most of its live records carry, else none; the link the Repo page
    opened on the id. `n` is every row, counted under *Later* alone.
    A held entry (its reading carries `held`, §4.5a **Inbox row: held entry**, TD-736) is a row too, in
    the same order: `release` set, for **Release**; one not *for you* is of the kind *ledger · held*, its
    `at` and `added` the hold's (*held 2h*), no answers — and `claimed` set, so its `held` reads
    *claimed by*, since on this row *held by* would name the wrong hold."""
    from .repo import PRIORITY_RANK  # repo imports this module: read at call time

    now = now or datetime.now(UTC)

    live = [s for s in fleet if s.get("state") not in ("exited", "closed") and s.get("repo")]
    groups: list[dict[str, Any]] = []
    for root, r in (repos or {}).items():
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or Path(str(r.get("root") or root)).name)
        # an entry an open decided line names has been answered: that line is its row now, a
        # *Waiting on them* row while it waits on its session (TD-565)
        decided = {
            str(ref).rsplit("#", 1)[-1]
            for o in ((r.get("work_orders") or {}).get("orders") or [])
            if isinstance(o, dict)
            for ref in o.get("refs") or ()
            if "#" not in str(ref) or str(ref).rsplit("#", 1)[0] == name
        }
        entries = [
            e
            for e in ((r.get("ledger") or {}).get("entries") or [])
            if isinstance(e, dict)
            and ((e.get("for_page") == "for-you" and e.get("id") not in decided) or isinstance(e.get("held"), dict))
        ]
        if not entries:
            continue
        every = [e for e in ((r.get("ledger") or {}).get("entries") or []) if isinstance(e, dict)]
        opened = {str(e.get("id")) for e in every}
        here = Path(str(r.get("root") or root)).resolve()
        mine = [s for s in live if Path(str(s["repo"])).resolve() == here]
        tally: dict[str, int] = {}
        for s in mine:
            if s.get("team"):
                tally[str(s["team"])] = tally.get(str(s["team"]), 0) + 1
        team = (named or {}).get(str(here)) or (max(sorted(tally), key=lambda t: tally[t]) if tally else "")
        rows = []
        for e in sorted(entries, key=lambda e: (PRIORITY_RANK.get(e.get("priority") or "", 9), e["id"])):
            holders = [
                s
                for s in mine
                if any(
                    isinstance(p, dict) and p.get("ref") == e["id"] and p.get("status") == "claimed"
                    for p in s.get("progress") or []
                )
            ]
            held = [str(s.get("name") or s.get("id")) for s in holders]
            owner = str(e.get("owner") or "").lower() == "paul"
            for_you = e.get("for_page") == "for-you" and e.get("id") not in decided  # else here for its hold
            hold = e.get("held") if isinstance(e.get("held"), dict) else None
            # the labels and, beside each, what it leads to (§4.10 *The answers' split*, TD-913): a card draws both
            got = e.get("consequences") if isinstance(e.get("consequences"), list) else []
            pairs = [(str(a), str(got[i]) if i < len(got) else "") for i, a in enumerate(e.get("answers") or ())]
            pairs = [(a, c) for a, c in pairs if a.strip()] if for_you else []
            answers = [a for a, _ in pairs]
            d = e.get("default")
            ok = isinstance(d, int) and not isinstance(d, bool) and 0 <= d < len(answers)
            added = str(e.get("added") or "") if for_you else str((hold or {}).get("at") or "")
            rows.append(
                {
                    "row": "ledger",
                    "id": e["id"],
                    "row_id": f"ledger:{name}:{e['id']}",  # the row's `data-msg` and fold key: an id is per repo
                    "kind": ("ledger · yours" if owner else "ledger · your decision") if for_you else "ledger · held",
                    "name": name,
                    "title": e.get("title") or "",
                    "subject": mail_mod.clip_subject(str(e.get("title") or "")),  # §4.10 *A subject on every entry*
                    "pri": (str(e.get("priority") or "")[:1] or "?").upper(),
                    "held": ", ".join(held),
                    "claimed": not for_you,  # a held row's claim reads *claimed by*
                    "release": hold is not None,  # **Release** (§4.5a *Inbox row: held entry*)
                    "holder": str(holders[0].get("id") or "") if holders else "",  # **Open session** (TD-678)
                    "type": str(e.get("type") or ""),  # the role **Start session** takes, by `entries:`
                    "why": "yours" if owner else "decision",  # `repoconfig.WORK_OPENING`'s key
                    "until": str(e.get("until") or "") if for_you else "",  # *held until <it>* (TD-795)
                    "team": team,
                    "at": added,
                    "added": _added_words(added) if for_you else settle_mod.words({"held": hold}, now),
                    "detail": "\n".join(str(x) for x in e.get("detail") or () if isinstance(x, str)).strip("\n"),
                    "answers": answers,
                    "consequences": [c for _, c in pairs],
                    "ask": str(e.get("ask") or "") if for_you else "",  # its one sentence on a card (§4.10)
                    "default": answers[d] if ok else "",
                    "root": str(r.get("root") or root),  # the checkout `ledger_decide` names the repo by
                    # what the row's controls read, as a Queue row carries them (§4.5 screen 12 *any open row*, TD-905)
                    "page": str(e.get("for_page") or ""),
                    "blocked_open": any(str(b) in opened for b in e.get("blocked_by") or ())
                    or bool(e.get("parts_open")),  # an open part counts as an open blocker (TD-1130)
                    "builds_open": ledger_mod.builds_open(e),
                    "hold_why": str((hold or {}).get("why") or ""),
                    "hold_by": str((hold or {}).get("words") or ""),  # the mark's `title` (TD-1127)
                    "url": f"/repo/{quote(name)}#{quote(e['id'])}",
                }
            )
        groups.append({"repo": name, "rows": rows})
    return {"n": sum(len(g["rows"]) for g in groups), "groups": groups}


templates.env.globals["ledger_rows"] = ledger_rows
