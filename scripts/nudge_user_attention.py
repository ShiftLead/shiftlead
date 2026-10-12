#!/usr/bin/env python3
# SYNCED FILE — canonical copy: ShiftLead/dev-cadence files/scripts/nudge_user_attention.py
# Edit it there and re-run sync.sh; an edit made in a consumer repo is overwritten (sync.sh --verify detects one).
"""Due-date nudges for docs/user_attention.md items, delivered to any channel.

Reads the user-attention board, finds unchecked items whose optional
``Due: YYYY-MM-DD`` marker is today or past, and pushes ONE message listing
them. On Mondays it additionally appends a full-board summary (including
items with no due date). Silent exit when
there is nothing to say. Snoozing an item = editing its Due date on the board.

Delivery channel (first match wins — most repos have no Telegram, so the
generic hook comes first):
  1. NUDGE_COMMAND env var — a shell command; the message is piped to its
     stdin. Works with anything: ``mail -s 'board' you@example.com``,
     ``ntfy publish mytopic``, a curl to a Slack/Discord webhook, etc.
  2. TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID env vars — built-in Telegram
     sender (the channel this script was born with in samscrape).
  3. Neither set: the message prints to stdout (cron's default mail catches
     it if configured) and the run exits nonzero so the misconfiguration
     is visible.

When a message is going out anyway (due items, or the Monday summary), a
best-effort staleness line rides along if the board repo's
``docs/cadence-sync.lock`` commit no longer matches the dev-cadence upstream
HEAD (anonymous-https ``git ls-remote``, 5 s timeout, silent on any failure) —
so a consumer repo can't quietly fall behind for weeks. Staleness alone never
triggers a send. The check targets the BOARD's repo; keep the checkout this
script *runs from* current via whatever schedule updates it.

Point ``--board`` (or USER_ATTENTION_BOARD) at the LIVE working-tree copy of
the board, not a deploy-pinned checkout: the board is an operator to-do list,
not production code, and a hand-edited Due date (snooze) must take effect the
same day — not after a merge + deploy sync. Falls back to the copy next to
this script.

Secrets (NUDGE_COMMAND contents, Telegram tokens) come from the environment —
inject them in the cron line via your secrets manager (e.g. `doppler run -- ...`).

Report mode (``--report``, plan 2026-08-10 P2): print a machine-wide attention
report to stdout and exit — no delivery channel is ever invoked, regardless of
NUDGE_COMMAND/TELEGRAM_* being set. Boards come from repeated ``--board`` flags,
or (with none) from every entry in this machine's roster
(``repos.txt`` in ``$DEV_CADENCE_REG_DIR``, else ``${XDG_CONFIG_HOME:-~/.config}/dev-cadence`` — written by dev-cadence
sync.sh; path-resolution spec: cadence.md §Machine scope), falling back to the
usual single-board resolution when no roster exists. Offline and fast by
default; ``--fetch`` (opt-in) additionally fetches each repo's origin serially —
hang-proofed (GIT_TERMINAL_PROMPT=0, BatchMode ssh, 30 s per repo, failures
degrade to a per-repo "fetch skipped" note) — and compares the local board
with the origin default branch's copy, plus the per-repo cadence staleness
line. When the local clone is merely BEHIND (local board untouched since the
merge-base, origin's has moved — the service-account append case, TD-030) the
row reads origin's board and says so; local-only or two-sided differences keep
reading the local file and are flagged. ``--due-only --fetch`` is the same
under a hard aggregate budget (``ATTENTION_DUE_FETCH_BUDGET``, default 8 s)
so a SessionStart hook can opt in without ever waiting long on the network.
Nudge (delivery) mode is unchanged and takes at most one ``--board``.

``--report --json`` prints the same rows as one JSON object instead of text
(boards, items with their 1-based board line numbers and parsed due dates, the
per-row notes, the sweep and sync-staleness lines, and with --fetch the repo-settings
drift line as `settings`, never under --due-only) so another tool can consume
the machine-wide view without parsing the human report; ``--due-only`` filters
the items the same way it filters the text. Items come in board order (the text
report sorts overdue-first) and there is no header tally — derive counts from
``items``. The text report stays the human surface and is unchanged.

Answers and decisions (TD-036): an item may end with ``Answers: a | b.`` (the
session's proposed answers) and ``Decided: <text> (YYYY-MM-DD).`` (written by
``board_edit.py decide`` on a person's action). A decided item stays on the
board and stays due, but it waits on a session, not the person: the reports
mark it so and list it first, ``--due-only`` shows it whether or not it is due,
the nudge never pushes it as due, and ``--json`` carries ``answers``,
``default``, ``decided`` and ``waiting_on`` per item. One answer may end in
`` (default)`` — the one the session recommends (TD-066): stripped from the answer's
text, carried as ``default``, and shown in the reports' tag.

For a tool that draws the board (TD-075) — so that it parses neither a board line nor a
sentence of this report: each ``--json`` item carries ``session`` and ``host`` (from its
``(session <name> on <host>)`` head; null when the head is not that shape) and ``refs`` (what
``Context:`` names, in order: ``TD-NNN`` or ``<repo>#TD-NNN``, ``PR #N``, ``branch <name>`` —
the branch best-effort, see ``item_refs``; empty when there is none); each board carries ``fetch_case`` — one of ``skipped | none |
matches | behind | local | both | unrelated`` (``FETCH_CASES``), null when no fetch was asked —
and ``fetch_why`` for a skip, beside ``fetch_note``, whose sentence is for people. The
SessionStart line clips an item at ``MAX_ITEM_CHARS`` but prints a reply tail
(`` — <name>, YYYY-MM-DD: …``, after the item's ``Due:``, written by ``board_edit.py reply``)
whole after it, and each ``--json`` item carries them as ``replies`` (``by``, ``date``,
``text``, in order; empty when there is none).

Usage:
    nudge_user_attention.py [--board PATH] [--dry-run] [--force-weekly]
    nudge_user_attention.py --report [--board PATH ...] [--fetch] [--due-only] [--json]
"""

import argparse
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledgerboard import (  # noqa: E402,F401  # sibling SYNC file: the board format, defined once (ShiftLead/ledgerboard); re-exported
    ANSWER_SPLIT_RE,
    ANSWERS_RE,
    ARCHIVE_AT,
    CLOSED_ITEM_RE,
    CLOSED_RE,
    CONTEXT_RE,
    DECIDED_RE,
    DEFAULT_MARK_RE,
    DUE_ATTEMPT_RE,
    DUE_RE,
    HEAD_HOST_RE,
    HEAD_RE,
    ITEM_RE,
    KIND_RE,
    KINDS,
    LIVE_LOOK_ANSWERS,
    REF_BRANCH_RE,
    REF_FILE_RE,
    REF_PR_RE,
    REF_TD_RE,
    REPLY_TAIL_RE,
    BoardItem,
    _raw_answers,
    _trailer,
    closed_items,
    detail_block,
    due_tag,
    item_head,
    item_key,
    item_record,
    item_refs,
    parse_answers,
    parse_board,
    parse_decided,
    parse_default,
    parse_replies,
    reply_span,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nudge_user_attention")

def _default_boards() -> list[Path]:
    boards = []
    env = os.environ.get("USER_ATTENTION_BOARD")
    if env:
        boards.append(Path(env))
    boards.append(Path(__file__).resolve().parent.parent / "docs" / "user_attention.md")
    return boards

MAX_ITEM_CHARS = 200
# TD-084: the reports print an item's detail block under it, each line clipped like the head
# and at most this many lines — a board read from origin is text anyone who can push wrote.
MAX_DETAIL_LINES = 20
# TD-039: a board past this many open items is warned about (report and SessionStart line).
BOARD_SIZE_WARN = 15
# TD-039: an item overdue this long is ledger material, not board material — the report
# says "ledger it" and /stranded-work proposes the move. The other trigger, an item
# snoozed twice, needs the board's git history, so the sweep checks that one (docs/procedures/stranded-work.md).
ESCALATE_OVERDUE_DAYS = 14
# TD-039: the SessionStart line lists at most this many items, then says how many more.
DUE_ONLY_LIST_CAP = 12



def escalation(item: BoardItem, today: date) -> str | None:
    """Why this item belongs in the ledger rather than on the board (TD-039), or None.
    Not for fyi (it has no date to miss) or a decided item (a session's work order)."""
    if item.kind == "fyi" or item.decided is not None:
        return None
    days = item.overdue_days(today)
    if days is not None and days >= ESCALATE_OVERDUE_DAYS:
        return f"overdue {days}d"
    return None


def archive_note(content: str) -> str | None:
    """TD-062: the prompt to archive closed items, once ARCHIVE_AT or more are on the board."""
    n = len(closed_items(content))
    if n < ARCHIVE_AT:
        return None
    return (f"⚠ {n} closed item(s) on the board — move them to docs/user_attention_archive.md "
            "in a PR of its own (cadence.md §3)")


def twin_note(content: str) -> str | None:
    """TD-062: open items that appear twice (item_key equal) — a merge kept both copies of
    an in-place edit (a snooze, a Decided:), which only a reader of the two can settle."""
    seen: dict[str, int] = {}
    for ln in content.splitlines():
        if ITEM_RE.match(ln):
            k = item_key(ln)
            seen[k] = seen.get(k, 0) + 1
    n = sum(1 for c in seen.values() if c > 1)
    if not n:
        return None
    return (f"⚠ {n} open item(s) appear twice — a merge kept both copies of a snooze or "
            "Decided:; keep the right one, drop the other (cadence.md §3)")



def size_note(items: list[BoardItem]) -> str | None:
    """TD-039: the warning for a board past BOARD_SIZE_WARN open items."""
    if len(items) <= BOARD_SIZE_WARN:
        return None
    return (f"⚠ {len(items)} open items on this board (over {BOARD_SIZE_WARN}) — triage or ledger "
            "them: the board is only \"a human must act\" (cadence.md §3)")


def kind_counts(items: list[BoardItem]) -> str:
    """'decide 2, act 1, unmarked 3' — the kinds present, in KINDS order (TD-039)."""
    n = {k: sum(1 for i in items if i.kind == k) for k in (*KINDS, None)}
    return ", ".join(f"{k or 'unmarked'} {c}" for k, c in n.items() if c)


def _clip(text: str) -> str:
    return text if len(text) <= MAX_ITEM_CHARS else text[: MAX_ITEM_CHARS - 1] + "…"


def _detail_lines(item: BoardItem) -> list[str]:
    """TD-084: the item's detail block as the reports print it — indented under the item,
    each line clipped, at most MAX_DETAIL_LINES, then how many more (--json has them all)."""
    out = [f"      {_clip(d)}" for d in item.detail[:MAX_DETAIL_LINES]]
    if len(item.detail) > MAX_DETAIL_LINES:
        out.append(f"      … {len(item.detail) - MAX_DETAIL_LINES} more line(s) — --json has them all")
    return out



def _clip_keep_replies(text: str) -> str:
    """The SessionStart line's clip (TD-075): the item is cut at MAX_ITEM_CHARS as ever, but a
    reply tail — what the person said back on the line — is printed whole after it. A reply
    lost to the clip is an answer the session it was written for never reads."""
    span = reply_span(text)
    if span is None or len(text) <= MAX_ITEM_CHARS:
        return _clip(text)
    return _clip(text[: span[0]]) + text[span[0]:]



def item_tag(item: BoardItem, today: date) -> str:
    """due_tag (with the recommended answer, TD-066), or — for a decided item (TD-036) —
    who it now waits on and since when."""
    if item.decided is None:
        if item.bad_due is not None:
            return f"⚠ unparseable due date {_clip(item.bad_due)} — write Due: YYYY-MM-DD"
        rec = f" · default: {_clip(item.default)}" if item.default else ""
        if item.kind == "fyi":
            base = "fyi" + (" · ⚠ an fyi carries no Due: — drop it" if item.fyi_due else "")
        elif item.kind == "watch":
            days = item.overdue_days(today)
            base = "watch · " + ("no check-by date" if item.due is None
                                 else f"check by {item.due.isoformat()}" if days is None
                                 else "check today" if days == 0 else f"check {days}d overdue")
        else:
            base = due_tag(item, today)
        esc = escalation(item, today)
        esc_tag = f" · ⚠ {esc} — ledger it and close it here" if esc else ""
        return base + rec + esc_tag
    text, on = item.decided
    age = (today - on).days
    since = f", {age}d ago" if age > 0 else ""
    return f"decided: {_clip(text)} on {on.isoformat()}{since} — waiting on a session"


def _report_sort_key(item: BoardItem, today: date) -> tuple[int, int]:
    """Decided first (oldest decision leading — a session's work order, TD-036), then
    overdue (most overdue leading), then dated soonest-first, then undated; then the
    watch items the same way, then fyi (TD-039: reported apart from the to-dos)."""
    if item.decided is not None:
        return (-1, item.decided[1].toordinal())
    if item.kind == "fyi":
        return (7, 0)
    if item.kind == "watch":
        days = item.overdue_days(today)
        return (4, -days) if days is not None else (5, item.due.toordinal()) if item.due else (6, 0)
    days = item.overdue_days(today)
    if days is not None:
        return (0, -days)
    if item.due is not None:
        return (1, item.due.toordinal())
    return (2, 0)


def surfaces_at_start(item: BoardItem, today: date) -> bool:
    """What the SessionStart line (--due-only) shows: every decided item, due or not,
    because it is a session's work order; an item whose Due: cannot be read (it might be
    due — TD-053); otherwise only due and overdue items — never an fyi (TD-039)."""
    if item.kind == "fyi" and item.decided is None:
        return False
    return item.decided is not None or item.bad_due is not None or item.overdue_days(today) is not None


def build_message(items: list[BoardItem], today: date, weekly: bool) -> str | None:
    """The single Telegram message for this run, or None if nothing to send."""
    # A decided item is a session's work order, not the person's (TD-036): not pushed as due.
    due_items = [(i, i.overdue_days(today)) for i in items if i.decided is None]
    due_items = [(i, d) for i, d in due_items if d is not None]

    lines: list[str] = []
    if due_items:
        lines.append(f"📌 user_attention.md — {len(due_items)} item(s) due:")
        for item, days in sorted(due_items, key=lambda p: -p[1]):
            lines.append(f"• ({due_tag(item, today)}) {_clip(item.text)}")

    if weekly and items:
        lines.append("")
        lines.append(f"🗓 Weekly board review — {len(items)} open item(s):")
        for item in items:
            marker = f" [due {item.due.isoformat()}]" if item.due else " [no due date]"
            lines.append(f"• {_clip(item.text)}{marker}")
        # (The old "run /stranded-work" Monday reminder is retired — TD-7/TD-12:
        # the Swept:/Swept-deep: staleness warnings are its pull-side successor.)

    if not lines:
        return None
    lines.append("")
    lines.append("Snooze: edit the item's Due date in docs/user_attention.md.")
    return "\n".join(lines)


def send_command(cmd: str, text: str) -> bool:
    """Pipe the message to an arbitrary shell command's stdin (NUDGE_COMMAND)."""
    try:
        r = subprocess.run(cmd, shell=True, input=text.encode(), timeout=120, check=False)
        if r.returncode != 0:
            logger.error("NUDGE_COMMAND exited %d", r.returncode)
        return r.returncode == 0
    except Exception:
        logger.exception("NUDGE_COMMAND failed")
        return False


def send_telegram(text: str, token: str, chat_id: str) -> bool:
    """Best-effort Telegram push; mirrors cluster_health_check.send_telegram_alert."""
    try:
        payload = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
        ).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=payload)
        with urllib.request.urlopen(req, timeout=30) as resp:
            ok = resp.status == 200
        if not ok:
            logger.error("Telegram send failed: HTTP %s", resp.status)
        return ok
    except Exception:
        logger.exception("Telegram send failed")
        return False


def _normalize_source_url(source: str) -> str | None:
    """Anonymous-https form of the lock's source (legacy slug, https, or ssh).

    Always anonymous https regardless of the URL's own auth form: an ssh or
    credentialed URL would hang or fail in a cron with no agent/TTY, and the
    check must never use (or expose) credentials. A bare ``owner/repo`` slug
    becomes a github.com URL only because that is what the old locks that wrote
    one meant — it is not a guess about any other remote (TD-098).
    """
    source = source.strip()
    if not source:
        return None
    if re.fullmatch(r"[\w.-]+/[\w.-]+", source):  # legacy slug owner/repo
        return f"https://github.com/{source}"
    m = re.fullmatch(r"(?:ssh://)?git@([\w.-]+)(?::\d+)?[:/](.+?)(?:\.git)?/?", source)
    if m:  # ssh port (if any) dropped — the https host serves the web UI/API
        return f"https://{m.group(1)}/{m.group(2)}"
    m = re.fullmatch(r"https?://(?:[^@/]+@)?([\w.-]+(?::\d+)?)/(.+?)(?:\.git)?/?", source)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    return None


def origin_forge(root: Path) -> tuple[str, str | None]:
    """Classify a repo's origin once (TD-098): ("github", "owner/repo") for github.com;
    ("other", host) for a forge the cadence cannot read yet (GitLab, Gitea, a GitHub
    Enterprise host — TD-097); ("none", None) for no origin, or one that names no host (a
    local path, a bare file:// clone: what every test fixture uses) — there the caller
    behaves as before. A detector told "other" says it could not look, never stays quiet:
    an empty answer must mean nothing there (cadence.md §7)."""
    try:
        r = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                           check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "none", None
    raw = r.stdout.strip() if r.returncode == 0 else ""
    # The host is read from the URL's own shape, not through _normalize_source_url, so any
    # scheme (ssh://, git://, HTTPS://) and any user (deploy@host:a/b) names its forge.
    m = re.fullmatch(r"([A-Za-z][A-Za-z0-9+.-]*)://(?:[^@/]*@)?([^/:]*)(?::\d*)?(/.*)?", raw)
    if m:
        if m.group(1).lower() == "file":
            return "none", None
        host, path = m.group(2).lower(), m.group(3) or ""
    else:
        # scp-like user@host:path; a bare owner/repo (a legacy *lock* form) or a local path
        # has no host — it would read as github.com through the lock normalizer, so never here
        m = re.fullmatch(r"[^/@:]+@([^/:]+):(.*)", raw)
        if not m:
            return "none", None
        host, path = m.group(1).lower(), m.group(2)
    if not host:
        return "none", None
    if host == "github.com":
        slug = re.sub(r"\.git$", "", path.strip("/")).lower()
        return ("github", slug) if re.fullmatch(r"[^/]+/[^/]+", slug) else ("none", None)
    return "other", host


def forge_unread_line(host: str) -> str:
    """The one wording every detector uses for an origin it cannot read (TD-098)."""
    return f"PRs not checked: origin is {host}, which the cadence cannot read yet (TD-097)"


def _upstream_files_commit(url: str) -> str | None:
    """The last commit touching files/ or sync.sh on origin/<default> of a dev-cadence clone
    on this machine's roster whose origin is `url` (TD-035); None when there is none — or
    when that clone's origin/<default> is not the remote's tip right now (a live ls-remote,
    the same call the fallback makes): a clone nobody re-fetched must never answer "in
    step" for a consumer that is behind."""
    for root in read_registry() or []:
        if not ((root / "sync.sh").is_file() and (root / "files").is_dir()):
            continue
        r = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                           check=False, capture_output=True, timeout=5)
        if r.returncode != 0 or _normalize_source_url(r.stdout.decode(errors="replace")) != url:
            continue
        branch = default_branch(root)
        ref = f"origin/{branch}"
        local = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "-q", ref],
                               check=False, capture_output=True, timeout=5)
        live = subprocess.run(["git", "ls-remote", url, f"refs/heads/{branch}"], check=False,
                              capture_output=True, timeout=5, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        tip = live.stdout.split()[0].decode("ascii", errors="replace") if live.returncode == 0 and live.stdout else ""
        if not tip or local.stdout.decode(errors="replace").strip() != tip:
            return None          # stale or unverifiable: the caller falls back to the uncertain line
        r = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%H", ref, "--", "files/", "sync.sh"],
                           check=False, capture_output=True, timeout=5)
        out = r.stdout.decode(errors="replace").strip()
        if r.returncode == 0 and out:
            return out
    return None


def staleness_line(board: Path | None) -> str | None:
    """One extra report line if the board repo's cadence sync lags upstream.

    `board` is `Path | None` because a roster repo may have no board at all, and two of the
    three call sites pass the roster row's value straight through. Until 2026-09-18 the
    annotation said `Path`, `None.parent` raised, and the blanket `except Exception` below
    turned it into `return None` — so the check was *structurally unreachable* for exactly
    those repos and nothing said so. The None case is handled here, explicitly: no board
    means no `cadence-sync.lock` beside it, which is not a staleness answer but the absence
    of a question.

    Reads docs/cadence-sync.lock next to the board (so the check targets the
    BOARD's repo even when this script runs from another repo's checkout).

    TD-035: an upstream commit that changes no synced file (a ledger edit, CLAUDE.md)
    must not read as "behind". The lock's ``files_commit:`` is the last upstream commit
    touching ``files/`` or ``sync.sh`` when it synced; when this machine's roster has a
    clone of that upstream, its ``origin/<default>`` answers the same question now, and
    the line fires only if they differ. Without a clone (or an older lock) the fallback
    is the remote HEAD via anonymous ``ls-remote`` — which cannot tell a synced change
    from any other, so its line says so. Best-effort
    by design (plan P2 / TD-2): any parse, git, or network failure returns None
    — the nudge's core job must never be blocked by this check. Rides along
    only when a message is already being sent (incl. Mondays), so staleness
    alone never triggers a send.
    """
    if board is None:
        return None
    try:
        lock = board.parent / "cadence-sync.lock"
        if not lock.is_file():
            return None
        source = commit = files_commit = None
        for line in lock.read_text(encoding="utf-8").splitlines():
            if line.startswith("source:"):
                source = line.split(":", 1)[1].strip()
            elif line.startswith("commit:"):
                commit = line.split(":", 1)[1].strip().removesuffix("+dirty")
            elif line.startswith("files_commit:"):
                # a +dirty sync shipped content no commit holds: the field cannot vouch for it
                v = line.split(":", 1)[1].strip()
                files_commit = v if len(v) >= 7 and not v.endswith("+dirty") else None
        if not source or not commit:
            return None
        url = _normalize_source_url(source)
        if url is None:
            return None
        if files_commit:
            upstream = _upstream_files_commit(url)
            if upstream is not None:
                if upstream.startswith(files_commit):   # full sha since TD-035; a 7+ prefix from older locks
                    return None
                return (
                    f"🔄 cadence sync behind (synced files at {files_commit[:8]} → upstream {upstream[:8]}): "
                    f"pull the dev-cadence clone and re-run sync.sh against this repo."
                )
        r = subprocess.run(
            ["git", "ls-remote", url, "HEAD"],
            check=False,
            capture_output=True,
            timeout=5,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if r.returncode != 0 or not r.stdout:
            return None
        head = r.stdout.split()[0].decode("ascii", errors="replace")
        if head.startswith(commit):
            return None
        return (
            f"🔄 cadence upstream moved (lock {commit[:8]} → upstream {head[:8]}) — possibly only files "
            f"sync does not ship; `sync.sh --verify` against this repo says for certain."
        )
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, ValueError):
        # The best-effort family the docstring means: the lock unreadable, git missing or
        # timing out, a remote that will not answer. Nothing to say, nothing to see.
        logger.debug("Staleness check skipped", exc_info=True)
        return None
    except Exception:
        # Anything else is a defect in this function, and the nudge still must not die of
        # it — but it must not be invisible either. DEBUG in a cron is invisible; this is
        # the level at which a five-month-unreachable check would have been noticed.
        logger.warning("Staleness check failed unexpectedly (bug, not environment)", exc_info=True)
        return None


def deliver(text: str) -> bool:
    """Send via the first configured channel (see module docstring)."""
    cmd = os.environ.get("NUDGE_COMMAND")
    if cmd:
        return send_command(cmd, text)
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return send_telegram(text, token, chat_id)
    logger.error(
        "No delivery channel configured — set NUDGE_COMMAND (message piped to its "
        "stdin) or TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID. Printing to stdout instead."
    )
    print(text)
    return False


def resolve_board(explicit: str | None) -> Path | None:
    candidates = [Path(explicit)] if explicit else []
    candidates += _default_boards()
    for path in candidates:
        if path.is_file():
            return path
    logger.error("No user_attention.md found (tried: %s)", ", ".join(str(p) for p in candidates))
    return None


# --- report mode (plan 2026-08-10 P2) ----------------------------------------


# TD-12 sweep staleness: /stranded-work stamps `Swept: YYYY-MM-DD (host, quick|deep)`
# on the board as its final step; deep runs also stamp `Swept-deep: YYYY-MM-DD`
# (TD-13), which quick runs never touch — so the last transcript-scan date
# survives later quick sweeps instead of being overwritten out of existence.
# The report warns past SWEEP_STALE_DAYS (or when the header is absent) and,
# separately, when no deep sweep is on record or the last one is past
# SWEEP_DEEP_STALE_DAYS (a `Swept:` stamp whose own mode is deep counts as deep
# recency, so pre-TD-13 stamps never false-warn "never"). "Weekly-ish quick,
# warned past 10 days; monthly-ish deep, warned past 30" — documented with a
# parity note in cadence.md §3; change writer, reader, and doc together.
SWEEP_STALE_DAYS = 10
SWEEP_DEEP_STALE_DAYS = 30
SWEEP_RE = re.compile(r"^Swept:\s*(?P<date>\d{4}-\d{2}-\d{2})\s*(?:\((?P<meta>[^)]*)\))?", re.MULTILINE)
# `^Swept:` cannot match a `Swept-deep:` line (the colon is anchored), so the
# two headers never shadow each other.
# On duplicate `Swept-deep:` lines (a hand-edit or merge leftover — the procedure
# replaces in place, so normal use never makes one) the FIRST match binds:
# fail-safe, it can only over-warn relative to a fresher line below it.
SWEEP_DEEP_RE = re.compile(r"^Swept-deep:\s*(?P<date>\d{4}-\d{2}-\d{2})\s*(?:\((?P<meta>[^)]*)\))?", re.MULTILINE)
# The mode marker the stranded-work procedure calls load-bearing. Matched as its own comma-separated
# token in the parenthesised meta — its format is `(<host>, quick|deep)` —
# so `(kmaster, deep)` and bare `(deep)` both read. In a multi-token meta the first
# token is the host and is never read as a mode, so `(deep-box)` and even a host
# literally named `deep` in `(deep, <mode>)` can't satisfy the check by accident.
SWEEP_MODES = ("quick", "deep")


def sweep_mode(meta: str | None) -> str | None:
    """'quick' | 'deep' from a stamp's meta, or None when it claims neither."""
    if not meta:
        return None
    tokens = [tok.strip().lower() for tok in meta.split(",")]
    # the mode is a standalone token; the first token is the host and is never a mode
    for tok in tokens[1:] if len(tokens) > 1 else tokens:
        if tok in SWEEP_MODES:
            return tok
    return None


def sweep_note(content: str, today: date) -> str | None:
    """Staleness warning for the board's Swept: stamp, or None when fresh."""
    m = SWEEP_RE.search(content)
    if m is None:
        return "⚠ never swept (no Swept: header) — run /stranded-work in this repo (cadence.md §3)"
    try:
        swept_on = datetime.strptime(m.group("date"), "%Y-%m-%d").date()  # noqa: DTZ007  # local civil dates by design (TD-15)
    except ValueError:
        return "⚠ unparseable Swept: header — fix the date or re-run /stranded-work"
    age = (today - swept_on).days
    if age < -1:
        # future-dated stamp (typo'd year, badly wrong clock) would otherwise read
        # as fresh forever — the exact silent-health illusion the stamp exists to
        # kill. One day of tolerance: a host in a timezone ahead of the reader can
        # legitimately stamp "tomorrow" for up to ~21 hours (TD-15).
        return f"⚠ Swept: date is in the future ({m.group('date')}) — fix the stamp"
    if age > SWEEP_STALE_DAYS:
        meta = f", {m.group('meta')}" if m.group("meta") else ""
        return f"⚠ last sweep {age}d ago ({m.group('date')}{meta}) — run /stranded-work in this repo"
    # Checked AFTER staleness on purpose: a stale stamp's fix (re-run the sweep)
    # also fixes a missing marker, so the more urgent line is the one to show.
    # A date alone is not a coverage claim — without this, `Swept: <today>` with no
    # mode read as full health, which is the illusion TD-12 exists to remove.
    if sweep_mode(m.group("meta")) is None:
        return (f"⚠ Swept: {m.group('date')} claims no quick|deep mode — re-run "
                "/stranded-work so the stamp records the coverage it actually had")
    # TD-13: deep coverage has its own slot and threshold. One `Swept:` slot let
    # a quick sweep overwrite the record of the last deep one, so a
    # permanently-quick repo read as fully healthy while the transcript scan —
    # the thing that recovers closed-session work — was deferred forever with
    # no signal. Checked only after the main stamp reads healthy: the more
    # urgent warning wins, and re-running the sweep refreshes both.
    deep_on = None
    dm = SWEEP_DEEP_RE.search(content)
    if dm is not None:
        try:
            deep_on = datetime.strptime(dm.group("date"), "%Y-%m-%d").date()  # noqa: DTZ007  # local civil dates by design (TD-15)
        except ValueError:
            return "⚠ unparseable Swept-deep: header — fix the date or re-run /stranded-work deep"
        deep_age = (today - deep_on).days
        if deep_age < -1:
            return f"⚠ Swept-deep: date is in the future ({dm.group('date')}) — fix the stamp"
    # A Swept: stamp whose own mode is deep is a deep sweep on record — the
    # second header only exists to PRESERVE that recency, so its absence next
    # to a fresh deep-mode stamp (a pre-TD-13 writer) must not warn "never".
    if sweep_mode(m.group("meta")) == "deep" and (deep_on is None or swept_on > deep_on):
        deep_on = swept_on
    if deep_on is None:
        return (f"{NO_DEEP_SWEEP} (quick sweeps only) — the transcript scan that "
                "recovers closed-session work has not run; run /stranded-work deep (cadence.md §3)")
    if (today - deep_on).days > SWEEP_DEEP_STALE_DAYS:
        return (f"⚠ last deep sweep {(today - deep_on).days}d ago — quick sweeps since keep the "
                "board fresh but do not scan transcripts; run /stranded-work deep")
    return None


NO_DEEP_SWEEP = "⚠ no deep sweep on record"


def never_hosted(root: Path) -> bool:
    """TD-28: no session transcript for this repo — its own dir, its worktrees, or any
    subdirectory a session started in — exists on this machine, so a deep sweep would have
    nothing of its own to scan. Asked of the session adapter (agent_sessions.ever_ran,
    TD-100), which is deliberately broad: a sibling repo sharing the path's prefix counts as
    "ran", the safe direction for a line that hides a warning. False whenever it cannot
    tell — a tool the repo lists that cannot be looked at keeps the warning."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import agent_sessions
        return agent_sessions.ever_ran(root) is False
    except Exception:  # noqa: BLE001 — cannot tell: keep the warning
        return False


def sweep_note_for(content: str, today: date, root: Path | None) -> str | None:
    """sweep_note, except that "no deep sweep on record" for a repo where no session has
    ever run on this machine says so instead of warning (TD-28): an unswept repo with a
    history of sessions is a gap; one with none is nothing to do here."""
    note = sweep_note(content, today)
    if note and note.startswith(NO_DEEP_SWEEP) and root is not None and never_hosted(root):
        return ("ℹ no deep sweep on record — and no session has run in this repo on this "
                "machine, so it has no transcripts to scan (work done on it from other repos' sessions "
                "is read by /stranded-work deep via list_sessions --roster --mentioning)")
    return note


def machine_dir() -> Path:
    """The machine-scope directory (cadence.md §9): DEV_CADENCE_REG_DIR when set — it
    isolates only the roster, leaving gh's credentials under XDG_CONFIG_HOME alone
    (TD-029) — else ${XDG_CONFIG_HOME:-~/.config}/dev-cadence."""
    if os.environ.get("DEV_CADENCE_REG_DIR"):
        return Path(os.environ["DEV_CADENCE_REG_DIR"])
    return Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")) / "dev-cadence"


def registry_path() -> Path:
    return machine_dir() / "repos.txt"


def read_registry() -> list[Path] | None:
    """Canonicalized, deduped roster entries; None when no registry file exists.

    Read-time canonicalization + dedupe is the defense-in-depth half of the
    registry contract (writers canonicalize too) — spec: cadence.md §Machine
    scope. Entries are returned even if the path is gone; callers degrade
    per-entry with a note rather than dropping rows silently.
    """
    reg = registry_path()
    if not reg.is_file():
        return None
    entries: list[Path] = []
    seen: set[str] = set()
    for raw in reg.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        p = Path(line).resolve()
        if str(p) not in seen:
            seen.add(str(p))
            entries.append(p)
    return entries


FETCH_TIMEOUT = 30.0  # s per repo fetch (plan P2.5 hang-proofing)
# --due-only --fetch (TD-030): the SessionStart runner (cadence_hooks.sh) bounds each
# child at 25 s (CADENCE_HOOK_CHILD_TIMEOUT), so the aggregate fetch budget sits well
# under it with room for python startup, the per-repo git show/merge-base calls and
# TD-052's one gh call. Exhaustion degrades to "fetch skipped" per remaining repo, never to a
# hung session start. Env override exists for the test suite.
DUE_FETCH_BUDGET = float(os.environ.get("ATTENTION_DUE_FETCH_BUDGET", "8"))
# TD-044: a fetch past its time is stopped with SIGTERM first — git's signal handlers
# remove the .lock files it holds (refs, packed-refs, FETCH_HEAD) — and SIGKILLed only
# if it is still running after this grace. A bare SIGKILL mid-write left a lock that
# failed the person's next `git pull` in some OTHER repo, reading as unrelated.
FETCH_TERM_GRACE = 1.0


def run_graceful(cmd: list[str], timeout: float, env: dict | None = None) -> subprocess.CompletedProcess:
    """subprocess.run(capture_output=True) whose timeout sends SIGTERM, waits
    FETCH_TERM_GRACE, then SIGKILLs; raises TimeoutExpired either way. The command runs
    in its own process group and the signal goes to the GROUP: git's children (ssh, a
    remote helper) hold the output pipes open, so signalling git alone and draining the
    pipes would wait on them for as long as they live."""
    with subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env, start_new_session=True) as p:
        try:
            out, err = p.communicate(timeout=max(timeout, 0))
        except subprocess.TimeoutExpired:
            _signal_group(p, signal.SIGTERM)
            try:
                p.wait(timeout=FETCH_TERM_GRACE)
            except subprocess.TimeoutExpired:
                _signal_group(p, signal.SIGKILL)
                p.wait()
            raise subprocess.TimeoutExpired(cmd, timeout) from None
        return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def _signal_group(p: subprocess.Popen, sig: int) -> None:
    try:
        os.killpg(p.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def current_repo() -> Path | None:
    """The main-checkout root of the repo this process runs in (cadence.md §9 path spec), or None."""
    try:
        r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                           check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(r.stdout.strip()).parent.resolve() if r.returncode == 0 and r.stdout.strip() else None


@dataclass
class FetchResult:
    """Outcome of one repo's origin comparison (TD-030).

    note     — the human line for the full report.
    content  — when set, the board text to READ instead of the local file:
               origin's copy, used only when the local board carries nothing
               origin lacks (see _fetch_board). None = read the local file.
    source   — the ref the content came from (e.g. "origin/main"), for labels.
    """
    note: str
    content: str | None = None
    source: str | None = None
    # TD-075: which case the comparison found, as a word a tool can key on — the note's
    # sentence is for people and may be reworded. One of FETCH_CASES; `why` is set for a skip.
    case: str = "skipped"
    why: str | None = None


# skipped: no comparison was made (why says why) · none: origin has no board · matches ·
# behind: only origin moved (its copy is shown) · local: only this clone moved (unpushed) ·
# both: both moved · unrelated: no common history to tell
FETCH_CASES = ("skipped", "none", "matches", "behind", "local", "both", "unrelated")


def default_branch(root: Path, run=None) -> str:
    """The repo's default branch NAME — cadence.md §9 "Default-branch rule": the first of
    origin/HEAD's target, init.defaultBranch, main, master that exists on origin (an
    unset or dangling origin/HEAD falls through); else main. Parity: the shell default_branch() copies and the other Python scripts
    follow the same rule; tests/test_default_branch.sh runs every copy. ``run`` (args ->
    CompletedProcess) lets --fetch keep these calls under its aggregate deadline."""
    def git(*args: str) -> str | None:
        if run is not None:
            r = run(list(args))
            return r.stdout.decode() if r.returncode == 0 else None
        try:
            r = subprocess.run(["git", "-C", str(root), *args], check=False, capture_output=True,
                               text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout if r.returncode == 0 else None

    head = git("symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    cfg = git("config", "init.defaultBranch")
    for b in ((head or "").strip().removeprefix("origin/"), (cfg or "").strip(), "main", "master"):
        if b and git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{b}") is not None:
            return b
    return "main"


def _fetch_board(root: Path, board: Path, deadline: float | None = None) -> FetchResult:
    """Opt-in origin comparison for one repo; NEVER hangs, never raises.

    Mandatory hang-proofing (plan P2.5): GIT_TERMINAL_PROMPT=0 + BatchMode ssh
    with a 5 s connect timeout, FETCH_TIMEOUT subprocess cap on the fetch and
    10 s on each local call — ALL of them further clipped to the remaining
    aggregate ``deadline`` when one is given — and every failure path degrades
    to a 'fetch skipped' note. A board that is missing locally is fine: it
    reads as "" and the compare decides whether origin's copy is the answer.

    Three-way compare (TD-030): local working-tree board vs the board blob at
    origin/<default> vs the blob at their merge-base. Branch-independent —
    whatever branch or detached state the repo is on.
      local == origin            → matches
      local == base, origin ≠    → origin moved and local is untouched: read
                                   ORIGIN's board (content set), say so. This is
                                   the service-account append case — the line
                                   exists only on origin until someone pulls.
      origin == base, local ≠    → local edits not pushed: read local, say so.
      all three differ           → diverged: read local, flag it (no safe
                                   automatic answer).
    Reading origin's blob never mutates the clone beyond the fetch itself — a
    report must not fast-forward repos it is only inspecting.
    """
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=5",
    }

    def git(args: list[str], cap: float) -> subprocess.CompletedProcess:
        # Every call — the network fetch AND the local show/merge-base calls —
        # is clipped to the remaining aggregate deadline, so a wedged .git
        # cannot push --due-only past its budget any more than a dead remote can.
        timeout = cap
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic())
            if timeout <= 0.05:
                raise subprocess.TimeoutExpired(args, 0)
        return subprocess.run(["git", "-C", str(root), *args],
                              check=False, capture_output=True, timeout=timeout, env=env)

    def blob(ref: str, rel: str) -> str | None:
        r = git(["show", f"{ref}:{rel}"], 10)
        return r.stdout.decode("utf-8", errors="replace") if r.returncode == 0 else None

    try:
        # TD-044: only the default branch, and never --prune — this is a reader; it must
        # not delete remote-tracking refs as a side effect. A clone with no ref for the
        # default yet gets a plain fetch (still unpruned) so it can learn one.
        branch = default_branch(root, run=lambda a: git(a, 10))
        have = git(["rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}"], 10).returncode == 0
        timeout = FETCH_TIMEOUT
        if deadline is not None:  # the SIGTERM grace comes out of the budget, not on top of it
            timeout = min(timeout, deadline - time.monotonic() - FETCH_TERM_GRACE)
            if timeout <= 0.05:
                raise subprocess.TimeoutExpired("git fetch", 0)
        # an explicit refspec: `fetch origin <branch>` updates only FETCH_HEAD where
        # remote.origin.fetch is narrowed, and the compare would read a stale ref as current
        r = run_graceful(["git", "-C", str(root), "fetch", "-q", "--no-prune", "origin",
                          *([f"+refs/heads/{branch}:refs/remotes/origin/{branch}"] if have else [])],
                         timeout, env)
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", errors="replace").strip().splitlines()
            why = err[-1] if err else "git fetch failed"
            return FetchResult(f"fetch skipped ({why})", why=why)
        ref = f"origin/{branch}"
        rel = (board.relative_to(root) if board.is_relative_to(root) else Path("docs/user_attention.md")).as_posix()
        origin = blob(ref, rel)
        if origin is None:
            return FetchResult(f"fetched; no board at {ref}", case="none")
        local = board.read_text(encoding="utf-8", errors="replace") if board.is_file() else ""
        if origin == local:
            return FetchResult(f"fetched; board matches {ref}", case="matches")
        mb = git(["merge-base", "HEAD", ref], 10)
        if mb.returncode != 0:
            return FetchResult(f"fetched; board DIFFERS from {ref} (no common history to compare) — pull/push; showing local",
                               case="unrelated")
        base = blob(mb.stdout.decode().strip(), rel) or ""
        if local == base:
            return FetchResult(
                f"fetched; local clone is behind — showing {ref}'s board (pull to catch up)",
                content=origin, source=ref, case="behind")
        if origin == base:
            return FetchResult(f"fetched; board DIFFERS from {ref} (local edits not pushed) — push for the cross-machine view",
                               case="local")
        return FetchResult(f"fetched; board DIFFERS from {ref} (both sides changed) — pull/push; showing local",
                           case="both")
    except subprocess.TimeoutExpired:
        if deadline is not None and time.monotonic() >= deadline - FETCH_TERM_GRACE - 0.05:
            return FetchResult("fetch skipped (budget exhausted)", why="budget exhausted")
        return FetchResult("fetch skipped (timeout)", why="timeout")
    except Exception as e:  # noqa: BLE001 — a dead report row beats a dead report
        return FetchResult(f"fetch skipped ({e})", why=str(e))


# --- Remote board tier (TD-6, plan 2026-08-13) -------------------------------
# Budget convention mirrors TD-10's GIT_TIMEOUT/GIT_BUDGET in
# check_claude_memory.sh: a per-call cap and an aggregate per-run cap, both
# named constants. Unlike the SessionStart hook (where exhaustion degrades to
# silence), --remote is a user-invoked report, so exhaustion prints an
# incomplete-note — never a stuck report, never a fake all-clear. The env
# overrides exist for the test suite only.
GH_TIMEOUT = float(os.environ.get("ATTENTION_GH_TIMEOUT", "10"))    # s per gh call
GH_BUDGET = float(os.environ.get("ATTENTION_GH_BUDGET", "60"))     # s aggregate
GH_LIST_LIMIT = int(os.environ.get("ATTENTION_GH_LIST_LIMIT", "500"))


def _remote_filter_path() -> Path:
    return machine_dir() / "remote_repos.txt"


def _read_remote_filter() -> tuple[list[str], list[str]]:
    """(owners, owner/repo entries) from the optional machine-local filter.

    Missing file OR a file with no entries both mean "no filter" (D1 as
    amended 2026-08-13): full discovery, user + orgs. Same comment/blank
    conventions as repos.txt.
    """
    f = _remote_filter_path()
    if not f.is_file():
        return [], []
    owners: list[str] = []
    repos: list[str] = []
    for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        (repos if "/" in line else owners).append(line)
    return owners, repos


def _gh(args: list[str], spent: dict) -> tuple[int, str, str]:
    """One budgeted gh call. Returns (rc, stdout, stderr); rc -1 = timeout,
    rc -2 = budget already exhausted (call not attempted), rc -3 = gh missing.
    Books elapsed time into spent["t"] in a finally so timeouts count too."""
    remaining = GH_BUDGET - spent["t"]
    if remaining <= 0:
        spent["hit"] = True
        return -2, "", "remote-tier budget exhausted"
    cap = min(GH_TIMEOUT, remaining)   # the budget may truncate below GH_TIMEOUT
    t0 = time.monotonic()
    try:
        r = subprocess.run(["gh", *args], check=False, capture_output=True,
                           text=True, timeout=cap)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return -3, "", "gh not installed"
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {cap:g}s"
    finally:
        spent["t"] += time.monotonic() - t0


PR_STALE_DAYS = 2  # an open PR older than this is named at SessionStart (TD-052)


def open_pr_lines(root: Path, deadline: float | None) -> list[str]:
    """TD-052: the SessionStart line's other half — this repo's open PRs older than
    PR_STALE_DAYS, a reviewed-but-unmerged one marked as such (the highest-value case:
    PR #89 sat seven days reviewed FIXED and nothing said so). One gh call, clipped to
    what is left of the fetch budget; offline, no gh, or any failure is silence — but an
    origin that is not GitHub is said, once, never silence (TD-098)."""
    kind, host = origin_forge(root)
    if kind == "other":
        return [f"⚠ {forge_unread_line(host)}"]
    timeout = 5.0 if deadline is None else min(5.0, deadline - time.monotonic())
    if timeout < 0.5:
        return []
    try:
        # oldest first, so the limit can never drop the stalest PR — the one this is for
        r = subprocess.run(["gh", "pr", "list", "--state", "open", "--limit", "30",
                            "--search", "sort:created-asc",
                            "--json", "number,title,createdAt,isDraft,comments"],
                           cwd=root, check=False, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "GH_PROMPT_DISABLED": "1"})
        if r.returncode != 0:
            return []
        prs = json.loads(r.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    now = datetime.now(timezone.utc)
    old = []
    for pr in prs:
        if pr.get("isDraft"):
            continue            # a draft is work in progress, not parked work
        try:
            created = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
        except (KeyError, ValueError, AttributeError):
            continue
        age = (now - created).days
        if age < PR_STALE_DAYS:
            continue
        # This text lands in every session's context (TD-051), and titles and comments come
        # from anyone who can open a PR: a title is one line of plain words, clipped, and a
        # `cadence-review:` counts only from someone with a say in the repo.
        # Its verdict may sit on any line, the last one counting (TD-087).
        verdicts = []
        for c in pr.get("comments") or []:
            if c.get("authorAssociation") not in ("OWNER", "MEMBER", "COLLABORATOR"):
                continue
            hits = re.findall(r"^[ \t]*cadence-review:[ \t]*(SHIP|FIXED|BLOCK)\b",
                              c.get("body") or "", re.I | re.M)
            if hits:
                verdicts.append(hits[-1].upper())
        mark = f", reviewed {verdicts[-1]} — unmerged" if verdicts else ""
        title = " ".join("".join(ch if ch.isprintable() else " " for ch in str(pr.get("title") or "")).split())
        num = pr.get("number") if isinstance(pr.get("number"), int) else "?"
        old.append((age, f"  • #{num} {title[:100]} ({age}d open{mark})"))
    if not old:
        return []
    old.sort(key=lambda p: -p[0])
    return [f"⚠ {len(old)} open PR(s) in {root.name} older than {PR_STALE_DAYS} days — merge, close, "
            "or say on the board why they wait (cadence.md §3):"] + [ln for _, ln in old]


def _local_origin(root: Path) -> str | None:
    """Normalized (anonymous-https, lowercased) origin URL of a local repo."""
    try:
        r = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                           check=False, capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001 — a missing origin just means no dedup match
        return None
    if r.returncode != 0:
        return None
    url = _normalize_source_url(r.stdout.strip())
    return url.lower() if url else None


# TD-034 tier 2: the merge settings cadence.md §4 assumes. adopt_repo_settings.sh checks and
# applies them one repo at a time; this only REPORTS, in the --fetch report, so drift is seen
# without anyone remembering to run it. Same values as that script's WANT (a parity pair).
CADENCE_SETTINGS = {"allow_squash_merge": True, "allow_merge_commit": False,
                    "allow_rebase_merge": False, "delete_branch_on_merge": True}


def _no_auto_delete() -> set[str]:
    """owner/repo names (lowercased) listed in the machine-scope no_auto_delete.txt: repos
    that keep "Automatically delete head branches" off on purpose (they stack PRs, §4), so
    the settings line never nags about it. Same format as remote_repos.txt."""
    try:
        lines = (machine_dir() / "no_auto_delete.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {ln.split("#", 1)[0].strip().lower() for ln in lines if ln.split("#", 1)[0].strip()}


def settings_line(root: Path, spent: dict) -> str | None:
    """One "⚙ repo settings" line when the repo's GitHub merge settings disagree with the
    cadence; None when they agree, there is no origin, or gh cannot answer (offline,
    unauthenticated, a non-admin sees null) — never a guess, never a write. An origin that
    is not GitHub gets a "not checked" line instead, so the row never reads clean (TD-098)."""
    kind, slug = origin_forge(root)
    if kind == "other":
        return f"⚙ repo settings not checked: origin is {slug}, which the cadence cannot read yet (TD-097)"
    if kind != "github" or slug is None:
        return None
    want = dict(CADENCE_SETTINGS)
    if slug.lower() in _no_auto_delete():
        want.pop("delete_branch_on_merge")   # a repo that stacks PRs, by choice (§4)
    rc, out, _err = _gh(["api", f"repos/{slug}"], spent)
    if rc != 0:
        return None
    try:
        got = json.loads(out)
    except ValueError:
        return None
    off = []
    for name, value in want.items():
        have = got.get(name)
        if have is None:
            return None     # not readable here (a non-admin): cannot say, so say nothing
        if have != value:
            off.append(f"{name} {'on' if have else 'off'}")
    if not off:
        return None
    return (f"⚙ repo settings differ from cadence.md §4: {', '.join(off)} — "
            "`scripts/adopt_repo_settings.sh --check` for the detail (never applied from here)")


def remote_tier(local_roots: list[Path], today: date, spent: dict | None = None) -> list[str]:
    """Render the remote-only tier (TD-6): discover boards on GitHub that no
    local row covers. Returns printable lines; every failure mode degrades to
    a ⚠ note — a per-repo failure must never ride the same silent path as a
    genuine 404, and discovery failure must never render as "no remote boards".
    """
    lines: list[str] = ["-- Remote tier (GitHub, pushed state only) --"]
    spent = spent if spent is not None else {"t": 0.0, "hit": False}

    owners, direct = _read_remote_filter()
    if not owners and not direct:
        rc, out, err = _gh(["api", "user", "--jq", ".login"], spent)
        if rc != 0:
            reason = "gh not installed" if rc == -3 else (err.strip().splitlines() or ["gh api user failed"])[-1]
            lines.append(f"⚠ remote tier unavailable ({reason})")
            return lines
        owners = [out.strip()]
        rc, out, err = _gh(["api", "user/orgs", "--jq", ".[].login"], spent)
        if rc == 0:
            owners += [o for o in out.split() if o]
        else:
            reason = (err.strip().splitlines() or ["org listing failed"])[-1]
            lines.append(f"⚠ org discovery failed ({reason}) — org repos not covered")

    candidates: list[str] = list(direct)
    for owner in owners:
        rc, out, err = _gh(["repo", "list", owner, "--json", "nameWithOwner,isArchived",
                            "--limit", str(GH_LIST_LIMIT)], spent)
        if rc != 0:
            reason = "budget exhausted" if rc == -2 else (err.strip().splitlines() or ["repo list failed"])[-1]
            lines.append(f"⚠ repo list failed for {owner} ({reason}) — that owner not covered")
            continue
        try:
            listed = json.loads(out)
        except ValueError:
            lines.append(f"⚠ repo list unparseable for {owner} — that owner not covered")
            continue
        if len(listed) >= GH_LIST_LIMIT:
            lines.append(f"⚠ repo list truncated at {GH_LIST_LIMIT} for {owner} — remote coverage incomplete")
        candidates += [r["nameWithOwner"] for r in listed if not r.get("isArchived")]

    local = {u for u in (_local_origin(r) for r in local_roots) if u}
    seen: set[str] = set()
    probes = [c for c in candidates
              if not (c in seen or seen.add(c))                      # order-preserving dedup
              and f"https://github.com/{c}".lower() not in local]    # local rows win (fresher)

    boards: list[tuple[str, str]] = []
    unprobeable: list[tuple[str, str]] = []
    probed = 0
    for name in sorted(probes):
        rc, out, err = _gh(["api", f"repos/{name}/contents/docs/user_attention.md",
                            "-H", "Accept: application/vnd.github.raw"], spent)
        if rc == -2:
            break
        probed += 1
        if rc == 0:
            boards.append((name, out))
        elif "HTTP 404" in err:
            continue                                # no board — silent by design
        else:
            reason = "gh not installed" if rc == -3 else (err.strip().splitlines() or ["probe failed"])[-1]
            unprobeable.append((name, reason))

    if spent["hit"]:
        lines.append(f"⚠ remote tier incomplete (budget exhausted after {probed} of {len(probes)} repos)")
    if unprobeable:
        n, (first, why) = len(unprobeable), unprobeable[0]
        lines.append(f"⚠ {n} repo(s) unprobeable (first: {first}: {why})")

    lines[0] = (f"-- Remote tier (GitHub, pushed state only) — {len(boards)} remote-only "
                f"board(s) across {probed} repo(s) probed --")
    for name, content in boards:
        lines.append("")
        lines.append(f"== {name} (remote-only, pushed state)")
        items = parse_board(content, warn=False)
        if items:
            for item in sorted(items, key=lambda i: _report_sort_key(i, today)):
                lines.append(f"  • ({due_tag(item, today)}) {_clip(item.text)}")
                lines.extend(_detail_lines(item))  # TD-084
        else:
            lines.append("  (no open items)")
    return lines


def _item_json(item: BoardItem, today: date) -> dict:
    """ledgerboard's item record (the board's API, TD-075/TD-084), plus this report's escalation (TD-039)."""
    return {**item_record(item, today), "escalate": escalation(item, today)}


def report(boards_cli: list[str], fetch: bool, due_only: bool = False, remote: bool = False,
           as_json: bool = False) -> int:
    """Machine-wide attention report to stdout. Report mode never delivers:
    deliver()/send_*() are unreachable from here regardless of environment.

    due_only (TD-7): the SessionStart wake-up line — only due/overdue items,
    plus every decided item (a session's work order, TD-036, listed first),
    one compact line each, and NOTHING when nothing is due, so a clean roster
    adds zero context noise. Row-level problems (missing boards, bad roster
    paths) are deliberately silent here; the full report is where they show."""
    today = date.today()  # noqa: DTZ011  # local civil dates by design (TD-15: one-day skew tolerated at the sweep comparisons)
    # (label, board_path or None, repo_root or None, note)
    rows: list[tuple[str, Path | None, Path | None, str | None]] = []
    # Board paths that are absent on disk, by row index — still fetchable
    # (TD-030): a clone that predates the board's first commit, or a locally
    # deleted board, has origin's copy as the only readable one.
    missing: dict[int, Path] = {}
    if boards_cli:
        for b in boards_cli:
            board = Path(b).resolve()
            root = board.parent.parent if board.parent.name == "docs" else board.parent
            if not board.is_file():
                missing[len(rows)] = board
            rows.append((root.name, board if board.is_file() else None, root,
                         None if board.is_file() else f"missing board file ({board})"))
    else:
        entries = read_registry()
        if entries is None:
            if due_only and not any(p.is_file() for p in _default_boards()):
                # SessionStart hook path (TD-7): a repo with no board yet has
                # nothing due — exit 0 with NO output and no ERROR log, per the
                # hooks-never-break-a-session rule (cadence.md §1). The JSON
                # twin still owes its consumer a parseable object (review
                # finding on #82): empty, never empty stdout.
                if as_json:
                    print(json.dumps({"today": today.isoformat(), "due_only": True, "boards": []}))
                return 0
            board = resolve_board(None)
            if board is None:
                return 1
            root = board.resolve().parent.parent
            rows.append((root.name, board, root, "no machine roster — showing this checkout's board only"))
        else:
            for root in entries:
                if not root.is_dir():
                    rows.append((root.name, None, None, f"roster path missing ({root})"))
                    continue
                if not (root / ".git").exists():
                    rows.append((root.name, None, None, f"roster path is not a git repo ({root})"))
                    continue
                board = root / "docs" / "user_attention.md"
                if not board.is_file():
                    missing[len(rows)] = board
                rows.append((root.name, board if board.is_file() else None, root,
                             None if board.is_file() else "no board (docs/user_attention.md not found)"))

    # TD-030: with --fetch, each row's board may be read from origin/<default>
    # when the local clone is merely behind. Full report: no aggregate budget
    # (serial, FETCH_TIMEOUT per repo, as before). --due-only: hard aggregate
    # budget so the SessionStart hook never waits on the network for long.
    here = current_repo() if fetch else None  # resolved before the budget's clock starts
    deadline = time.monotonic() + DUE_FETCH_BUDGET if (fetch and due_only) else None
    fetched: dict[int, FetchResult] = {}
    if fetch:
        # TD-044: the repo this session runs in is fetched FIRST — the changes hook that
        # runs next reads its origin/<default>, and a slow remote earlier on the roster
        # must not starve it. The rest follow in roster order; rows print in roster order.
        order = sorted(range(len(rows)),
                       key=lambda i: 0 if rows[i][2] is not None and here is not None
                       and rows[i][2].resolve() == here else 1)
        starved: list[str] = []
        for i in order:
            label, board, root, note = rows[i]
            bpath = board if board is not None else missing.get(i)
            if bpath is None or root is None:
                continue
            fr = _fetch_board(root, bpath, deadline)
            fetched[i] = fr
            if fr.case == "skipped" and fr.why == "budget exhausted":
                starved.append(label)
            if board is None and fr.content is not None:
                # Missing locally, present on origin: origin's copy IS the row.
                rows[i] = (label, bpath, root, None)
        if starved and due_only:
            # --due-only is silent about rows by design; a budget that ran out is the one
            # thing it must not hide, or "nothing due" reads as "checked everything".
            print(f"attention: fetch budget ({DUE_FETCH_BUDGET:g}s) ran out — {len(starved)} repo(s) "
                  f"read from their last fetch: {', '.join(starved)}", file=sys.stderr)

    def read_board(i: int, board: Path) -> str:
        fr = fetched.get(i)
        if fr is not None and fr.content is not None:
            return fr.content
        return board.read_text(encoding="utf-8", errors="replace")

    if as_json:
        json_gh_spent = {"t": 0.0, "hit": False}
        # One object, every row, no delivery — the tool-facing twin of the text
        # report. Items come back in board order with their line numbers so a
        # consumer can edit the board (snooze = Due: edit, done = tick) by line.
        out_rows: list[dict] = []
        for i, (label, board, root, note) in enumerate(rows):
            fr = fetched.get(i)
            row: dict = {"label": label, "board": str(board) if board else None,
                         "root": str(root) if root else None,
                         "source": fr.source if fr is not None and fr.source else None,
                         "note": note, "fetch_note": fr.note if fr is not None else None,
                         # TD-075: the same outcome as a word (FETCH_CASES); null when no fetch was asked
                         "fetch_case": fr.case if fr is not None else None,
                         "fetch_why": fr.why if fr is not None else None,
                         # stale: same gate as the text report — only a fetched row
                         # pays for the best-effort ls-remote (None = current/unknown)
                         "stale": staleness_line(board) if fr is not None else None,
                         # TD-034: the merge-settings drift line — fetched rows of the full
                         # report only, never --due-only (a session start pays no gh call)
                         "settings": (settings_line(root, json_gh_spent)
                                      if fr is not None and root is not None and not due_only else None),
                         "sweep": None, "archive": None, "size": None, "items": []}
            if board is not None:
                try:
                    content = read_board(i, board)
                except OSError as e:
                    row["note"] = f"unreadable board: {e}"
                    content = None
                if content is not None:
                    row["sweep"] = sweep_note_for(content, today, root)
                    row["archive"] = " ".join(n for n in (archive_note(content), twin_note(content)) if n) or None
                    all_items = parse_board(content, warn=False)
                    row["size"] = size_note(all_items)  # TD-039
                    row["items"] = [_item_json(it, today) for it in all_items
                                    if not due_only or surfaces_at_start(it, today)]
            out_rows.append(row)
        print(json.dumps({"today": today.isoformat(), "due_only": due_only, "boards": out_rows}, indent=2))
        return 0

    if due_only:
        due_lines: list[str] = []
        due_items: list[BoardItem] = []
        decided_lines: list[str] = []
        bad_lines: list[str] = []
        watch_lines: list[str] = []
        oversized: list[str] = []
        n_escalate = 0
        for i, (label, board, _root, _note) in enumerate(rows):
            if board is None:
                continue
            try:
                content = read_board(i, board)
            except OSError:
                continue
            fr = fetched.get(i)
            tag = f" [{fr.source} — local clone behind, pull]" if fr is not None and fr.source else ""
            items = parse_board(content, warn=False)
            if len(items) > BOARD_SIZE_WARN:
                oversized.append(f"{label} {len(items)}")
            for item in sorted(items, key=lambda it: _report_sort_key(it, today)):
                if not surfaces_at_start(item, today):
                    continue
                n_escalate += escalation(item, today) is not None
                ln = f"  • {label}{tag}: ({item_tag(item, today)}) {_clip_keep_replies(item.text)}"
                if item.decided is not None:
                    decided_lines.append(ln)
                elif item.bad_due is not None:
                    bad_lines.append(ln)
                elif item.kind == "watch":
                    watch_lines.append(ln)
                else:
                    due_lines.append(ln)
                    due_items.append(item)
        if due_lines or decided_lines or bad_lines or watch_lines:
            parts = []
            if due_lines:
                kinds = kind_counts(due_items)
                parts.append(f"{len(due_lines)} attention item(s) due"
                             + (f" ({kinds})" if any(it.kind for it in due_items) else ""))
            if decided_lines:
                parts.append(f"{len(decided_lines)} decided item(s) waiting on a session")
            if bad_lines:
                parts.append(f"{len(bad_lines)} with a due date that cannot be read")
            if watch_lines:
                parts.append(f"{len(watch_lines)} watch item(s) to check")
            print(f"⚠ {' and '.join(parts)} across this machine's repos — "
                  "run /attention for the full report (cadence.md §3):")
            listed = decided_lines + due_lines + bad_lines + watch_lines
            for ln in listed[:DUE_ONLY_LIST_CAP]:
                print(ln)
            if len(listed) > DUE_ONLY_LIST_CAP:
                print(f"  … and {len(listed) - DUE_ONLY_LIST_CAP} more — run /attention")
            if n_escalate:
                # Counts every surfacing item, listed or past the cap — so never "of them".
                print(f"⚠ {n_escalate} item(s) overdue {ESCALATE_OVERDUE_DAYS}d or more across these boards — "
                      "ledger each as a TD and close it on the board (cadence.md §3)")
        if oversized:
            print(f"⚠ board(s) over {BOARD_SIZE_WARN} open items — triage or ledger them: {', '.join(oversized)}")
        if fetch and here is not None:
            for ln in open_pr_lines(here, deadline):
                print(ln)
        return 0

    sections: list[str] = []
    gh_spent = {"t": 0.0, "hit": False}  # one gh budget for the settings lines and the remote tier
    total_items = 0
    total_due = 0
    total_decided = 0
    total_watch = 0
    all_items: list[BoardItem] = []
    n_boards = 0
    for i, (label, board, root, note) in enumerate(rows):
        fr = fetched.get(i)
        head = f"== {label}" + (f" ({board})" if board else "")
        if fr is not None and fr.source:
            head += f" — showing {fr.source}"
        body: list[str] = []
        if board is not None:
            try:
                # errors="replace": one mis-encoded board must degrade to mojibake in
                # its own row, never crash the whole multi-repo report (review finding)
                content = read_board(i, board)
            except OSError as e:
                body.append(f"  ⚠ unreadable board: {e}")
                content = None
            if content is not None:
                n_boards += 1
                items = parse_board(content, warn=False)
                total_items += len(items)
                all_items += items
                total_due += sum(1 for i in items if i.decided is None and i.todo and i.overdue_days(today) is not None)
                total_watch += sum(1 for i in items if i.decided is None and i.kind == "watch"
                                   and i.overdue_days(today) is not None)
                total_decided += sum(1 for i in items if i.decided is not None)
                if items:
                    for item in sorted(items, key=lambda i: _report_sort_key(i, today)):
                        body.append(f"  • ({item_tag(item, today)}) {_clip(item.text)}")
                        body.extend(_detail_lines(item))  # TD-084
                else:
                    body.append("  (no open items)")
                # Deliberately OUTSIDE the open-items gate (TD-14, decided
                # 2026-08-12): the sweep covers PRs, worktrees, unpushed
                # commits, and memories — an empty board proves nothing about
                # those, so staleness warns unconditionally.
                sweep = sweep_note_for(content, today, root)
                if sweep:
                    body.append(f"  {sweep}")
                for extra in (size_note(items), archive_note(content), twin_note(content)):
                    if extra:
                        body.append(f"  {extra}")
        if note:
            body.append(f"  note: {note}")
        if fr is not None:
            body.append(f"  {fr.note}")
            stale = staleness_line(board)
            if stale:
                body.append(f"  {stale}")
            if root is not None:
                drift = settings_line(root, gh_spent)
                if drift:
                    body.append(f"  {drift}")
        sections.append("\n".join([head, *body]))

    decided_note = f", {total_decided} decided (waiting on a session)" if total_decided else ""
    decided_note += f", {total_watch} watch item(s) to check" if total_watch else ""
    kinds_note = f" ({kind_counts(all_items)})" if any(i.kind for i in all_items) else ""
    print(f"Attention report — {n_boards} board(s), {total_items} open item(s){kinds_note}, "
          f"{total_due} due/overdue{decided_note}")
    for s in sections:
        print()
        print(s)
    if remote:
        # Dedup compares against the rows actually rendered above, however
        # they were sourced (registry or explicit --board) — plan D-amendment.
        print()
        for ln in remote_tier([r for _, _, r, _ in rows if r is not None], today, gh_spent):
            print(ln)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", action="append",
                    help="Path to user_attention.md (default: $USER_ATTENTION_BOARD, then this checkout). "
                         "Repeatable in --report mode; nudge mode takes at most one.")
    ap.add_argument("--dry-run", action="store_true", help="Print the message instead of sending")
    ap.add_argument("--force-weekly", action="store_true", help="Include the weekly summary regardless of weekday")
    ap.add_argument("--report", action="store_true",
                    help="Print a machine-wide attention report to stdout (no delivery) and exit. "
                         "--dry-run/--force-weekly are nudge-mode flags and are ignored here (a report "
                         "is already a dry run and always shows the full board).")
    ap.add_argument("--fetch", action="store_true",
                    help="With --report: also fetch each repo's origin (serial, hang-proofed) and compare boards; "
                         "a clone that is merely behind has its board read from origin/<default> (TD-030). "
                         "With --due-only: bounded by ATTENTION_DUE_FETCH_BUDGET (default 8 s) in aggregate.")
    ap.add_argument("--remote", action="store_true",
                    help="With --report: additionally discover boards on GitHub (gh CLI) that no "
                         "local row covers — the cross-machine tier (TD-6). Implies --fetch so the "
                         "freshness story stays coherent. Pushed state only.")
    ap.add_argument("--due-only", action="store_true",
                    help="With --report: print only due/overdue items, compactly; SILENT when none "
                         "are due (TD-7: the SessionStart wake-up line — offline, no delivery)")
    ap.add_argument("--json", action="store_true",
                    help="With --report: print the rows as one JSON object (boards, items with board "
                         "line numbers and parsed due dates) for other tools; --due-only filters "
                         "items the same way. --remote is text-only and is refused with --json.")
    args = ap.parse_args()

    if args.fetch and not args.report:
        ap.error("--fetch requires --report")
    if args.remote and not args.report:
        ap.error("--remote requires --report")
    if args.due_only and not args.report:
        ap.error("--due-only requires --report")
    if args.json and not args.report:
        ap.error("--json requires --report")
    if args.json and args.remote:
        ap.error("--json does not cover --remote (the remote tier is text-only)")
    if args.report:
        return report(args.board or [], args.fetch or args.remote, args.due_only, args.remote, args.json)
    if args.board and len(args.board) > 1:
        ap.error("nudge mode takes at most one --board (use --report for a multi-board view)")

    board = resolve_board(args.board[0] if args.board else None)
    if board is None:
        return 1
    today = date.today()  # noqa: DTZ011  # local civil dates by design (TD-15: one-day skew tolerated at the sweep comparisons)
    weekly = args.force_weekly or today.weekday() == 0  # Monday
    items = parse_board(board.read_text(encoding="utf-8"))
    message = build_message(items, today, weekly)

    if message is None:
        logger.info("Board clean (%d open item(s), none due, not weekly) — no nudge.", len(items))
        return 0
    stale = staleness_line(board)
    if stale:
        message += "\n\n" + stale
    if args.dry_run:
        print(message)
        return 0
    sent = deliver(message)
    logger.info("Nudge %s (%d open item(s), board: %s)", "sent" if sent else "NOT sent", len(items), board)
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
