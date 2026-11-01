"""The gates, written as functions over a record map (design §4.4a, TD-057 step 1).

Both gates read several records at once — the caller's grant, the target's `controllers`, a
shared controlled target — and the process that holds every record is the home host agent
(§4.4a). Writing them over a plain mapping rather than as methods reaching into the agent is what
lets a node forward a request and the home answer it from one graph. Nothing here mutates a record
or touches the store: each function returns a reason, or None when the call passes. Every gate
takes `controllers`, how a record's `controllers` read from the caller's host (§4.4a "Every address
crosses in the reader's form", step 5): the home passes a function that re-addresses another host's
record's list into its own form, and the records themselves are never copied.

Every number the mail rules need was `None` — unlimited — until TD-052 step 5 measured a team and
step 6 set it from the evidence (2026-09-18, design §4.10 "The numbers"). What was measured: eight
hours of a four-session team, a lead over three free-pick grinders, on 2026-09-17.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from sessionorc import adapters
from sessionorc.models import GRANTS, PERSON, SYSTEM, MailEntry, Session, has_control, start_note

# -- bounds (design §4.10 "The bounds are part of the design"); numbers are TD-052 step 6's --------
RECIPIENT_CAP = 5  # addressees the *sender* names; automatic copies are exempt
TEXT_CAP = 4096  # bytes of `text`; an `ask` to two cites `sends` by id rather than quoting them
THREAD_BOUND: int | None = 40  # entries per thread before a send is refused; measured: no thread past 2
PAIR_BOUND: int | None = 300  # reply-less entries between one pair inside PAIR_WINDOW; measured: 48 in 8 h
PAIR_WINDOW = timedelta(hours=24)  # the rolling window a reply-less pair is counted in
MAILBOX_DEPTH: int | None = 100  # unread entries an inbox holds before a send to it is refused; measured: 19
# The person inbox's depths are two counts from 2026-10-04 (TD-324), each with its own figures.
# **Questions** — the open `ask`s and `steer`s (`MailEntry.open`) — refuse a question to
# the person, and a pass-up, so one worker cannot fill the Inbox with questions that never lapse.
PERSON_INBOX_DEPTH: int | None = 200  # open questions the person inbox holds before one more is refused
# …and of those, how many one sender may hold there: 100 since 2026-09-28 (Paul), 20 before, when a
# techlead seat's replies to the person were refused for a day with every one of its 20 slots held
PERSON_SENDER_DEPTH: int | None = 100
# **FYIs** — every other entry still in the person inbox: notes, replies, the answered-FYI, a closed
# question — refuse any other send to the person. A person's read marks nothing, so a note counts
# until a Dismiss takes it (a closed question ages out with retention); until 2026-10-04 they
# counted against the questions' figures, and a seat's 100 notes stopped its verdicts and
# escalations reaching the person (Paul).
PERSON_FYI_DEPTH: int | None = 1000  # Paul's figure
PERSON_FYI_SENDER_DEPTH: int | None = 500  # so one looping sender leaves the others room
ASK_BOUND = timedelta(hours=24)  # an `ask`'s default bound, wall-clock on the home's clock
DEFAULT_CAP = 200  # characters of a `steer`'s `default`, cleaned and capped as a `doing` line is (§4.8)
RULES = "rules"  # the answerer of an *Answered for you* FYI the person's `permissions:` rules filed (§4.9b, TD-641)
SOURCE_CAP = 200  # characters of a reply's `source` (§4.9b): one line, where the answer is written down
# A subject on every entry (§4.10 *A subject on every entry*, TD-561): the headline a person browses the
# Inbox by, apart from the text, at most this many characters.
SUBJECT_CHARS = 80
# The subject rule's sentence: to the first full stop, question or exclamation mark followed by a space or the
# end. Public, since `shiftlead.ui.render.one_sentence` matches a first paragraph by it (§4.10 *An item leads
# with one sentence*, TD-913) and `sessionorc` never imports `shiftlead`.
SENTENCE = re.compile(r"(.+?[.?!])(?:\s|$)")
# Suggested answers (§4.10 *Suggested answers*, 2026-09-20, TD-070): how many an `ask` or a `steer`
# may carry, and how long each may be. They are a field of their own and do not
# count toward `TEXT_CAP`. Each is cleaned **more strictly than displayed text is** (the tail's
# cleaning and also every Unicode format character), because an answer becomes the label of
# something a person presses.
ANSWERS_MAX = 4
ANSWER_CAP = 80  # a label, read after the split (§4.10 *The answers' split*, TD-913)
ANSWER_LINE_CAP = 200  # a stored answer, consequence and all: `<label> (default) — <consequence>`
CONSEQUENCE_SEP = " — "  # the split, on its first occurrence (cadence §3.5's answer form)
_DEFAULT_MARK = re.compile(r"\s*\(default\)$", re.IGNORECASE)
# A look's screenshots (§4.10 *A look*, TD-290, TD-292): up to four repo-relative paths, each a `.png`
# directly under `docs/mockups/reviews/`, matched whole — the page serves that one directory and
# nothing else, so a path of any other shape is refused rather than cleaned into one.
SHOTS_MAX = 4
SHOT_NAME = re.compile(r"[A-Za-z0-9._-]+\.png")  # a screenshot's file name, as the page serves it
SHOT_RE = re.compile(r"docs/mockups/reviews/" + SHOT_NAME.pattern)
OPEN_ASK_ADVICE = 3  # open `ask`s to the person at which `ao msg` advises asking whether this one is a steer
# Outcomes owed to the person before an `ask` or a `steer` to it is refused (design §4.10
# *Outcomes*, TD-079). Ten, because the remedy is one line each and a worker with a long night of
# answered questions must be able to keep asking — the debt bounds the *unreported*, never the
# mailbox: an owing question does not hold its sender's slot in the person-inbox depths.
OUTCOMES_OWED_MAX: int | None = 10
OUTCOME_STATES = ("done", "blocked", "dropped")  # what an asker may report; the home writes two more
MAIL_RETENTION: timedelta | None = timedelta(hours=12)  # how long a read entry is kept; an open `ask` is exempt
# A reply that carries a `source` (§4.9b) is kept in its sender's outbox this long from when it was
# sent, whatever else is pruned: `ao inbox --sent` is how a techlead started cold answers two
# questions in one night alike, and a seat filled by `--keep-mail` carries the outbox with it.
SOURCED_RETENTION = timedelta(days=7)
SENDS_KEEP = 20  # `sends` entries a record keeps
# how long a send's `key` answers a repeat as the first send (§4.10 *A send lands once*, TD-806)
SEND_KEY_SECONDS = 600
NONCES_KEEP = 256  # verdicts remembered per host agent for a client's same-nonce retry
WAKE_BUDGET: int | None = 30  # mail-caused wakes a session may take per WAKE_WINDOW; measured: a lead took 4 an hour
WAKE_WINDOW = timedelta(hours=1)  # the rolling window the wake budget counts charged wakes in
WAKES_KEEP = 50  # wake decisions a record keeps (`wakes`): what step 5 measures
# How long a declared claim holds its reference against another live session's claim (design §4.8
# "A claim is a lease", TD-056). Renewed by claiming again; released sooner by done/dropped or the
# holder's record ending. Long enough for one medium TD without a renewal, short enough that a
# stood-down worker does not hold a reference into the next day. The standing of an orphaned
# question (below) reads it as the claim's refusal does.
LEASE_TTL = timedelta(hours=12)

# RPCs that act on a session (design §4.8): a caller that is a session needs the `control`
# grant to run one of these on a session other than itself (§9 invariant 11). `create` targets a
# session that is by definition not the caller; `set_grants` is gated so a session cannot grant
# itself. `decide` answers another session's permission prompt, the same class of act as typing
# at it (TD-116). Reads are never listed here, and neither is `msg`: messaging is not acting (§4.10).
ACTING_RPCS = frozenset(
    {
        "send",
        "keys",
        "kill",
        "close",
        "set_mode",
        "keep",
        "remove",
        "create",
        "decide",
        "set_grants",
        "set_controllers",
        "set_stop",
        "set_start",
    }
)


# A person's own acts (design §4.8 *A person's own act is a named RPC, and the gate is one list*,
# TD-317): RPCs no session may call, whatever grant or membership it holds. Each begins with
# `agent_common.person_only`, in the RPC and never in the dispatcher, since the link's `act` calls
# an RPC directly; `tests/test_person_only.py` holds this list and those checks to each other.
PERSON_ONLY = frozenset(
    {
        "inbox_delete",
        "inbox_snooze",
        "inbox_hand",
        "inbox_dismiss",
        "attention_snooze",
        "inbox_pause",
        "inbox_resume",
        "inbox_go_with_it",
        "thread",
        "identity_ack",
        "identity_log",
        "suspend",
        "board_edit",
        "board_reply",
        "board_reply_hand",
        "ledger_decide",
        "entry_add",
        "settings",
        "set_settings",
        "set_reach",
        "commit_defs",
        "promote",
        "clear_promote",
        "clear_work",
        "work_start",
        "clear_mark",
        "restart",
        "relaunch",
        "notify_test",
        "forget_host",
        "attach",
        "ci_rerun",
        "add_repo",
    }
)

# The one of them a person's session passes too (design §4.8 *A person's session passes one of them*,
# TD-1117, TD-1297): `ledger_decide`'s roads, passing `session_ok` to `agent_common.person_only`;
# `tests/test_person_only.py` holds the subset to that call.
PERSON_SESSION = frozenset({"ledger_decide"})


# every control character read as a space, in one C pass rather than a generator per character (TD-739);
# a pattern, since `str.translate` with a mapping looks each character up in Python's dict (TD-747)
_CONTROLS = re.compile(r"[\x00-\x1f]")


def clip_subject(line: str) -> str:
    """A subject as one line of at most `SUBJECT_CHARS` (§4.10 *A subject on every entry*): whitespace
    and control characters folded to single spaces, and a longer one clipped at a word with an
    ellipsis."""
    flat = " ".join(_CONTROLS.sub(" ", str(line)).split())
    if len(flat) <= SUBJECT_CHARS:
        return flat
    cut = flat[: SUBJECT_CHARS - 1]
    if flat[SUBJECT_CHARS - 1] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]  # never half a word
    return cut.rstrip(" ,;:-—") + "…"


def subject_of(text: str) -> str:
    """The subject a text with none stands under (§4.10 *A subject on every entry*, TD-561): its first
    sentence — to the first full stop, question or exclamation mark followed by a space or the end —
    else the text itself, either one clipped as `clip_subject` clips. Only a prefix is folded: a clipped
    subject reads no further than `SUBJECT_CHARS + 1` folded characters, and a prefix's fold is a prefix
    of the whole text's, so the first prefix whose fold is longer than that draws the same (TD-747)."""
    text, n = str(text), 4 * SUBJECT_CHARS
    while True:
        flat = " ".join(_CONTROLS.sub(" ", text[:n]).split())
        if n >= len(text) or len(flat) > SUBJECT_CHARS + 1:
            break
        n *= 4
    m = SENTENCE.match(flat)
    return clip_subject(m.group(1) if m else flat)


def split_answer(line: str) -> tuple[str, str]:
    """One answer as its reader reads it (§4.10 *The answers' split*, TD-913): `(label, consequence)`, split
    on the first ` — `, the label capped at `ANSWER_CAP`; a line with no dash is all label, consequence ''.
    The `(default)` mark stays on the label: `answer_mark` reads it."""
    label, sep, rest = str(line).partition(CONSEQUENCE_SEP)
    if not sep:
        label, rest = str(line), ""
    return label.strip()[:ANSWER_CAP], rest.strip()


def answer_mark(label: str) -> tuple[str, bool]:
    """A label with its ` (default)` mark taken off, and whether it carried one (§4.10 *The answers' split*)."""
    bare = _DEFAULT_MARK.sub("", label).strip()
    return (bare, True) if bare != label.strip() and bare else (label, False)


def picks_answer(text: str, line: str) -> bool:
    """Whether a press's `text` is the stored answer `line` word for word: the whole line, as before the
    split, or the label its reader drew from it, mark and all (§4.10 *The answers' split*, TD-913)."""
    label = split_answer(line)[0]
    return text in (line, label, answer_mark(label)[0])


def read_answers(entry: dict[str, Any]) -> dict[str, Any]:
    """A mail entry's reading with its `answers` split (§4.10 *The answers' split*, TD-913): `answers` the
    labels, a parallel `consequences`, and `recommended` — the index of a `steer`'s `default` (matched on
    the label or the whole line, word for word) or of the one `ask` label ending in ` (default)`, else None.
    What is stored is unchanged; a reading without answers is returned as it is."""
    lines = [str(a) for a in entry.get("answers") or ()]
    if not lines:
        return entry
    labels, consequences, marked = [], [], []
    for i, line in enumerate(lines):
        label, consequence = split_answer(line)
        bare, mark = answer_mark(label)
        labels.append(bare)
        consequences.append(consequence)
        if mark:
            marked.append(i)
    d = entry.get("default")
    if entry.get("kind") == "steer" and d:
        rec = next((i for i, line in enumerate(lines) if d in (line, split_answer(line)[0], labels[i])), None)
    else:
        rec = marked[0] if len(marked) == 1 else None
    return {**entry, "answers": labels, "consequences": consequences, "recommended": rec}


def is_person(caller: Any) -> bool:
    """`caller is None` — the field absent from the envelope — is the only thing that reads as a
    person. Anything else present is a session, however odd its type: `not caller` would have
    let `"caller": 0` (or `""`, `[]`, `{}`) past both halves of the gate, since the socket
    takes raw JSON from any local process and only `LocalClient` bothers to send a real id
    (review 2026-09-13)."""
    return caller is None


def person_shell(record: Session | None) -> bool:
    """The person's own shell (design §4.8 *The person's own shell is the person*, TD-580): a `shell`
    session, interactive, with no role and no controller — what **Open shell here**, **+ New ▾ Shell**
    and `ao shell` make, and what no session can make, since a session's shell lists its creator as a
    controller from birth. A team badge does not end it (TD-821): **Open shell here** on a team member
    gives the shell the member's `team` and `project`, so its card is drawn on that team, and a badge
    grants nothing (§9 invariant 9). Read from the record at each request, never kept: `ao mode`, `ao
    control … add` or a role ends it on the next call. The one exception to `PERSON_ONLY`, and it passes
    the acting gate and every other act a person passes (`as_person`, TD-801)."""
    return (
        record is not None
        and record.adapter == "shell"
        and not record.unattended
        and not record.role
        and not record.controllers
    )


def as_person(caller: Any, records: Mapping[str, Session]) -> bool:
    """Whether a request passes where a person passes an act (design §4.8 *The person's own shell is
    the person*, TD-801): no caller (`is_person`), or a caller whose record in `records` — the one
    graph, so a node's shell under `id@host` is read from the home's copy — is the person's own shell
    (`person_shell`). A caller that is not a string, or one `records` does not hold, is a session.
    `is_person` stays where the absent caller itself is meant: who sent, who closed, the identity."""
    if is_person(caller):
        return True
    return isinstance(caller, str) and person_shell(records.get(caller))


def by_person(record: Session) -> bool:
    """Whether the person started this record by hand (design §4.10 *between the person's own
    sessions*, TD-1069): its `by_person`, written once by the create; a record written before the
    field reads it from being interactive, not `supervised` and with no `controllers`, since a
    session's start names its starter from birth (§4.8). What the gate and the pushed view read."""
    if record.by_person is not None:
        return record.by_person
    return record.kind == "interactive" and not record.unattended and not record.supervised and not record.controllers


def own_end(record: Session) -> bool:
    """An end of the edge between the person's own sessions (§4.10, TD-1069): started by hand
    (`by_person`), interactive as invariant 5 reads one, and holding no `seat` of any trigger — so a
    session of theirs later put in `ao mode unattended` is no end, and an `ask` to a seat keeps the
    question-seat edge."""
    return by_person(record) and record.kind == "interactive" and not record.unattended and not record.seat


Controllers = Callable[[Session], list[str]]


def _own(s: Session) -> list[str]:
    return s.controllers


def person_session(record: Session | None, controllers: Controllers = _own) -> bool:
    """A person's session (design §4.8 *A person's session passes one of them*, §4.10 *between the
    person's own sessions*, TD-1116, TD-1117): an own end (`own_end`) with no `controllers` — started by
    hand, interactive, holding no seat, carrying no lead's word. Read from the record at each request, so
    a flip to `unattended`, a controller added or a seat end it on the next call. What `from_role` reads
    as `person-session` and `agent_common.person_only` passes for `PERSON_SESSION`."""
    return record is not None and own_end(record) and not controllers(record)


def presser_words(by: str, records: Mapping[str, Session]) -> str:
    """Who pressed a ledger road (`ledger_decide`'s caller), as the tell's notes say it (§4.4 *The tell*,
    TD-1117), read from `records` (the one graph) now: *the person* for
    `person`, none, or the person's shell (`as_person`); *the person's session <name>* for a person's
    session; the record's name for any other; the id for one gone."""
    if not by or by == PERSON or as_person(by, records):
        return "the person"
    r = records.get(by)
    if r is None:
        return by
    return f"the person's session {r.name}" if person_session(r) else r.name


# A record's `superseded_by` as the reader addresses it (§4.4a): its key in the records and the record,
# to the next key or None. The home re-addresses a node record's bare id as `id@host` (`_from_host`).
Successor = Callable[[str, Session], "str | None"]


def _raw_successor(_key: str, s: Session) -> str | None:
    return s.superseded_by or None


def chain(records: Mapping[str, Session], start: str, successor: Successor = _raw_successor) -> list[str]:
    """`start` and every record its `superseded_by` chain reaches, in order: a resumed session is the
    same conversation (design §4.10 *to a question seat*). A loop ends the walk."""
    out, sid = [start], start
    while (r := records.get(sid)) is not None and (nxt := successor(sid, r)) and nxt not in out:
        out.append(nxt)
        sid = nxt
    return out


def asks_seat(s: Session | None) -> bool:
    """Does `s` hold a seat whose trigger is `asks` — the techlead seat, or any `seats:` entry given
    that trigger (§4.9b)? Read from the record's `seat`, which a start writes."""
    return s is not None and isinstance(s.seat, dict) and s.seat.get("trigger") == "asks"


def self_decide_refusal(caller: Any) -> str:
    """TD-119, design §4.8: whatever it holds, a session never answers its own permission prompt."""
    return f"{caller} cannot decide itself: a session does not answer its own permission prompt (design §4.8)"


def act_gate(
    records: Mapping[str, Session],
    caller: Any,
    method: str,
    params: Mapping[str, Any],
    *,
    controllers: Controllers = _own,
) -> str | None:
    """Design §4.8, §9 invariant 11: an acting RPC from a session onto a *different* session
    needs the `control` grant on the caller's record **and** the caller in the target's
    `controllers` (TD-036). Both halves are read from the records here, on every call, so a
    revoke or a membership edit takes effect on the session's next call and neither is cached.
    No caller (a person's terminal, the UI) passes; a session acting on itself passes, except
    for the two RPCs that edit authority — a session may no more hand itself a grant than
    remove the controller watching it — and `decide`, which is refused outright on oneself: a
    permission prompt exists so that someone other than the session approves the call (TD-119).
    A caller this agent does not know is a session (the id came from `SHIFTLEAD_SESSION`) and
    holds no grant. Reads are never gated; this is a guard against a confused worker, not a
    security boundary.

    Third, §9 invariant 5 (TD-041): a target that is a person's session (`kind: interactive`
    and not `unattended`) is refused to every session, grant and membership notwithstanding.

    The person's own shell (`as_person`, TD-801) passes as no caller does — grant, membership,
    invariant 5 and the self-act branches alike: the shell is the person.

    Returns the refusal, or None when the call passes."""
    if as_person(caller, records) or method not in ACTING_RPCS:
        return None
    if method == "decide" and params.get("id") == caller:
        return self_decide_refusal(caller)
    if method not in ("create", "set_grants", "set_controllers") and params.get("id") == caller:
        return None
    me = records.get(str(caller))
    if me is None or not has_control(me.capabilities):
        target = "a new session" if method == "create" else params.get("id", "?")
        # a person's session with an agent in it (§4.8a *A tool's shell escape is the session's*, TD-1051):
        # what the person typed through the tool's `!` runs as the session, so the refusal names the way out
        typed = me is not None and not me.unattended and adapters.has_agent(me.adapter)
        hint = " — typed with the tool's `!`? It runs as this session; run it from your own shell or the page"
        return f"{caller} cannot {method} {target}: needs the control grant (design §4.8)" + (hint if typed else "")
    if method == "create":
        # No target to be a member of yet. What create is gated on instead is attenuation: the
        # child's grants must be a subset of the creator's (design §4.8, capability attenuation).
        excess = [
            g for g in dict.fromkeys(params.get("capabilities") or []) if g in GRANTS and g not in me.capabilities
        ]
        if excess:
            return (
                f"{caller} cannot create a session holding {', '.join(excess)}: "
                f"a session it creates gets no grant it does not hold itself (design §4.8)"
            )
        return None
    target_id = str(params.get("id", ""))
    target = records.get(target_id)
    # An id this agent has no record of falls through to the method, which answers "no session
    # <id>" — a membership refusal here would say more about the org than the caller may read.
    # A missing `id` lands here as `None` too and is refused by the method rather than by this
    # gate: it is a required argument on every acting RPC and so fails as bad params (pinned by a
    # test; an acting RPC that ever gave `id` a default would need its own membership check here).
    if target is not None and target.kind == "interactive" and not target.unattended:
        # §9 invariant 5 (TD-041): a person's session — `kind: interactive` says conversation,
        # `unattended: false` says not a worker — is out of every session's reach, whatever the
        # grant and whatever `controllers` says, `set_controllers` included. Checked before
        # membership because no edit to the list changes the answer; read from the record on
        # every call, so `ao mode <id> interactive` takes effect on the controller's next call
        # and its list entry merely goes inert. A person (no caller) never reaches this line.
        return (
            f"{caller} cannot {method} {target_id}: it is interactive, and no session acts on an "
            f"interactive session — only a person does (design §9 invariant 5)"
        )
    if target is not None and str(caller) not in (ctl := controllers(target)):
        how = "nobody may act on it" if not ctl else "it is controlled by " + ", ".join(ctl)
        return f"{caller} cannot {method} {target_id}: not in its controllers — {how} (design §4.8)"
    return None


def message_edge(
    records: Mapping[str, Session],
    sender: str,
    target: str,
    *,
    controllers: Controllers = _own,
    kind: str = "",
    carries: bool = False,
    replied: MailEntry | None = None,
    successor: Successor = _raw_successor,
) -> str | None:
    """The edge that lets `sender` message `target` (design §4.10 "The message gate is weaker than
    `control`"), or None when there is none. No new list, no new grant: the graph is read on every
    call, so a membership edit changes who may talk on the next call.

    - **upward**: the target is in the sender's own `controllers`;
    - **downward**: the sender is in the target's `controllers` (its `members:`);
    - **team**: both carry the same non-empty `team` badge;
    - **project**: both carry the same non-empty `project` badge, whatever their teams (TD-582) —
      with `team`, §9 invariant 9's named exception, for mail alone;
    - **shared target**: some record names both in its `controllers` (two leads over one worker);
    - **own**: from a record the person started by hand (`own_end`, TD-1069) with no `controllers`
      to any record, whatever its team, project, role or state — and from one that names a controller
      to another own end alone (TD-1116) — in any kind but an `ask` carrying `pr` or `cites` or put
      to a question seat (that one takes the seat's edge); and back along it, a `reply` from any
      record on an entry in its own inbox (`replied`) whose sender is such an own end with no
      `controllers`, to that sender or a record its `superseded_by` chain reaches;
    - **question seat**: tried last (TD-995) — an `ask` carrying no `pr` or `cites` (`carries`) to a
      record whose seat's trigger is `asks`, from anywhere in the org; and that seat's `reply` to an
      `ask` it holds (`replied`, from the sender's own inbox), to its asker or a record the asker's
      `superseded_by` chain reaches.
    """
    me, it = records.get(sender), records.get(target)
    if me is None or it is None:
        return None
    if target in controllers(me):
        return "upward"
    if sender in controllers(it):
        return "downward"
    if me.team and me.team == it.team:
        return "team"
    if me.project and me.project == it.project:
        return "project"
    if any(sender in (c := controllers(r)) and target in c for r in records.values()):
        return "shared target"
    if own_end(me) and (own_end(it) or not controllers(me)) and not (kind == "ask" and (carries or asks_seat(it))):
        return "own"
    if (
        kind == "reply"
        and replied is not None
        and (asker := records.get(replied.from_)) is not None
        and own_end(asker)
        and not controllers(asker)
        and target in chain(records, replied.from_, successor)
    ):
        return "own"
    if kind == "ask" and not carries and asks_seat(it):
        return "question seat"
    if (
        kind == "reply"
        and replied is not None
        and replied.kind == "ask"
        and asks_seat(me)
        and target in chain(records, replied.from_, successor)
    ):
        return "question seat"
    return None


def message_gate(
    records: Mapping[str, Session],
    sender: str,
    target: str,
    *,
    controllers: Controllers = _own,
    kind: str = "",
    carries: bool = False,
    replied: MailEntry | None = None,
    successor: Successor = _raw_successor,
    agentless: bool = False,
) -> str | None:
    """Design §4.10: may `sender` message `target`? A person (`sender == PERSON`) always may — they
    are not a session and may message anyone (§4.8) — and any session may message the person
    inbox (`target == PERSON`). Otherwise a session may message along one of
    `message_edge`'s seven edges and nothing else, refused by naming §4.10's graph rather than
    invariant 11: messaging is not acting. An `ask` passing the question-seat edge alone is one open
    question per sender per seat: the sender counted along its `superseded_by` chain, the count read
    in the target's inbox, since a seat's mail moves with its fills (TD-995). A sender with no agent
    (`agentless`, the person's own shell) sends a `note` alone on the own edge: its target could not
    reply into it (TD-1116). Returns the refusal, or None when the message may land."""
    if sender == PERSON or target == PERSON:
        return None  # the person inbox is ungated (§4.10 "A session reaches a person")
    if sender == target:
        return f"{sender} cannot message itself: a note to yourself is a ledger entry (design §4.10)"
    if sender not in records:
        return f"{sender} cannot message {target}: this host agent has no record of the sender (design §4.10)"
    edge = message_edge(
        records,
        sender,
        target,
        controllers=controllers,
        kind=kind,
        carries=carries,
        replied=replied,
        successor=successor,
    )
    if edge is None:
        return (
            f"{sender} cannot message {target}: not one of its controllers, its members, its team, "
            f"its project, or a controller of a session it controls — nor an ask to a question seat, "
            f"or that seat's reply to an ask it holds, nor from a session the person started by hand, "
            f"or a reply to one (design §4.10)"
        )
    if edge == "own" and kind in ("ask", "steer") and agentless:
        return (
            f"{sender} cannot {kind} {target}: a question needs an inbox to answer into: send it from a session, "
            f"or `ao msg person` (design §4.10 *between the person's own sessions*)"
        )
    if edge == "question seat" and kind == "ask":
        mine = {k for k in records if sender in chain(records, k, successor)}
        first = next((e for e in records[target].inbox if e.kind == "ask" and e.open and e.from_ in mine), None)
        if first is not None:
            return (
                f"{sender} cannot ask {target} again: its question {first.id} is still open — a reply, "
                f"its lapse or the person's close frees it (design §4.10 *to a question seat*)"
            )
    return None


def from_role(records: Mapping[str, Session], holder: str, sender: str, *, controllers: Controllers = _own) -> str:
    """What `ao inbox` says beside every entry (design §4.10 "Surface"): whether its sender is one
    of the holder's controllers, a person, or neither — read at the moment the text is weighed,
    because instructions come from controllers and people, and mail from anyone else is
    information. `system` is the fourth value (design §4.10, 2026-09-19): the home reporting what
    became of the reader's own message, and never an instruction. `person-session` (TD-1116): a
    sender the person started by hand, with no `controllers`, as it is now — what it says to do or
    avoid binds as the person's; a sender since put unattended or under a lead reads `other`."""
    if sender == SYSTEM:
        return "system"
    if sender == PERSON:
        return "person"
    me = records.get(holder)
    if me is not None and sender in controllers(me):
        return "controller"
    if person_session(records.get(sender), controllers):
        return "person-session"
    return "other"


# -- the wake decision (design §4.10 "The host agent decides each wake") -------------------------


def undecided_mail(s: Session) -> list[MailEntry]:
    """The unread entries in `s`'s inbox that no wake has covered: those after the `mail_decided`
    watermark. The inbox is in arrival order, so the watermark's id is where the covered part
    ends. If that entry has since left the inbox (a person deleted it, retention pruned it), its
    `at` stands in — compared with `>=`, since `at` is whole seconds: a sibling from the same
    second may be decided twice, a redundant wake, never a missed one."""
    mark = s.mail_decided
    if not mark:
        return [e for e in s.inbox if not e.read_at]
    ids = [e.id for e in s.inbox]
    if mark.get("id") in ids:
        return [e for e in s.inbox[ids.index(mark["id"]) + 1 :] if not e.read_at]
    return [e for e in s.inbox if not e.read_at and e.at >= str(mark.get("at") or "")]


def charged_wakes(s: Session, now: datetime) -> int:
    """Mail-caused wakes inside the rolling window and since the last refill (a person's act
    restores the budget in full; time restores it as the window rolls)."""
    since = (now - WAKE_WINDOW).isoformat(timespec="microseconds")
    if s.wake_refilled_at and s.wake_refilled_at > since:
        since = s.wake_refilled_at
    return sum(1 for w in s.wakes if w.get("charged") and str(w.get("at", "")) > since)


def wake_budget_spent(s: Session, now: datetime) -> bool:
    return WAKE_BUDGET is not None and charged_wakes(s, now) >= WAKE_BUDGET


def mail_wakes(s: Session) -> bool:
    """A person's session is never woken by mail (§9 invariant 5, §4.10 *Done when*): it gets the
    unread line and the chip, and nothing returns or rings for it."""
    return not (s.kind == "interactive" and not s.unattended)


# Rings in a row, each answered by a turn that read none of its mail, before the bell stops (design
# §4.10 *A ring is answered by a read, or the bell stops*, TD-347).
DOORBELL_HELD = 3


# The two fixed texts around a brief (design §4.1 *The brief is the person's word, and the tool is told
# so*, TD-343): text no sender chose, the line in the person's voice whoever started the session. A
# brief typed as nothing but a paste reaches the tool as pasted content, which a careful model reads as
# data, not as its task.
BRIEF_LINE = "My brief for this session is pasted below; read it and act on it."
BRIEF_PREFACE = (
    "This session was started by a person through shiftlead, which runs it in a terminal on their behalf. "
    "When the session has a brief, it arrives as the first prompt: one line in the person's voice, typed, then "
    "the brief, pasted, both by shiftlead's host agent on that person's behalf. Act on the brief as the person's own "
    "instruction. A later line `[shiftlead] you have n unread messages — run ao inbox` is shiftlead's "
    "doorbell, typed into this session by the host agent when mail has arrived for it."
)


def start_context_file_text(start_context: str | None) -> str:
    """What the start-context file holds (§4.1): the home's preface, then the caller's start context
    after a blank line when there is one — so a launch with none still has the file, for the preface."""
    return f"{BRIEF_PREFACE}\n\n{start_context}" if start_context else BRIEF_PREFACE


def unread_line(n: int) -> str:
    """The one line a session is told it has mail with (design §4.10): the doorbell typed into an
    idle pane and the line on every `ao` reply are this text. A count and nothing a sender wrote —
    no `from`, no `kind`, no `about`, no body — which is what keeps a ring a message and not a
    laundered `send`: whatever is pasted and followed by Enter is the recipient's next prompt."""
    return f"[shiftlead] you have {int(n)} unread messages — run ao inbox"


def _at_or_after(a: str, b: str | None) -> bool:
    """Whether the instant `a` is no earlier than `b` (an unreadable one: no)."""
    try:
        return not b or datetime.fromisoformat(a.replace("Z", "+00:00")) >= datetime.fromisoformat(
            b.replace("Z", "+00:00")
        )
    except ValueError:
        return False


def _hours(d: timedelta) -> str:
    h = d.total_seconds() / 3600
    return f"{h:g} h" if h >= 1 else f"{int(d.total_seconds() // 60)} min"


# design §4.10 *A question about a reference outlives its asker*, §4.5a *Inbox row: orphaned
# question* (TD-216 slice 2): how an orphaned question's asker went, in the row's words
ORPHAN_HOW = {"closed": "was closed", "forgotten": "was forgotten", "cancelled": "was cancelled"}
_NOT_LIVE = ("exited", "closed", "scheduled")  # a record that holds no lease on anything (§4.8)


def lease_holders(ref: str, records: Iterable[Mapping[str, Any]], now: datetime) -> list[Mapping[str, Any]]:
    """Every live record, as the `list` RPC hands it over, with an unexpired declared lease on
    `ref` (design §4.8, `LEASE_TTL`) — the reading `_lease_holders` makes at the home when the
    person's answer is mailed, made again here from the records a page or `ao inbox` already holds."""
    out: list[Mapping[str, Any]] = []
    for r in records:
        if not isinstance(r, Mapping) or r.get("state") in _NOT_LIVE:
            continue
        for p in r.get("progress") or ():
            if not isinstance(p, Mapping) or p.get("ref") != ref or p.get("status") != "claimed":
                continue
            if (p.get("source") or "declared") != "declared":
                continue
            try:
                at = datetime.fromisoformat(str(p.get("at") or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            if at.tzinfo is not None and now - at < LEASE_TTL and r not in out:
                out.append(r)
    return out


def orphan_standing(e: Mapping[str, Any], records: Iterable[Mapping[str, Any]], now: datetime) -> dict[str, Any] | None:
    """The **standing** of an orphaned question (design §4.5a *Inbox row: orphaned question*), or
    None for an entry that carries no `orphaned`: where the person's answer will go, said before
    the press, in the board row's words — *its session was closed — grinder-ao-2 holds TD-149:
    your answer reaches it, and shiftlead's board*, or *… — nobody holds TD-180: your answer is
    written on shiftlead's board*. Display only: the home reads the leases again at the press.
    `holders` is `[{id, name}]`, `text` the line."""
    o = e.get("orphaned")
    if not isinstance(o, Mapping):
        return None
    ref = str(o.get("ref") or e.get("about") or "")
    repo = str(o.get("repo") or "")
    board = f"{repo.rstrip('/').rsplit('/', 1)[-1]}'s board" if repo else ""
    held = lease_holders(ref, records, now) if ref else []
    holders = [{"id": str(r.get("id") or ""), "name": str(r.get("name") or r.get("id") or "")} for r in held]
    went = f"its session {ORPHAN_HOW.get(str(o.get('how') or ''), 'is gone')}"
    names = ", ".join(h["name"] for h in holders)
    if holders and board:
        verb, whom = ("holds", "it") if len(holders) == 1 else ("hold", "them")
        text = f"{went} — {names} {verb} {ref}: your answer reaches {whom}, and {board}"
    elif board:
        text = f"{went} — nobody holds {ref}: your answer is written on {board}"
    else:  # the home refuses the press in these words' sense (TD-216 slice 1): no repo, no board
        text = f"{went} and named no repo: there is no board for your answer — Delete declines it"
    return {"ref": ref, "repo": repo, "board": board, "holders": holders, "text": text}


def _held_by_subagents(s: Session) -> bool:
    """Whether only subagents' prompts are open over an idle main thread (§4.10 *When it is read*'s
    `needs-you` row, TD-950): every entry of `pendings` a subagent's, and `kept` an `idle`."""
    pends = getattr(s, "pendings", None) or []
    kept = getattr(s, "kept", None)
    return bool(pends) and all(p.subagent for p in pends) and isinstance(kept, dict) and kept.get("state") == "idle"


def read_when(
    s: Session | None,
    kind: str,
    now: datetime,
    *,
    person: bool = True,
    seat: bool = False,
    bound: timedelta | None = None,
    unreachable: bool = False,
    rings: bool = True,
    refills: bool = False,
    lapses: bool = True,
    cache: bool = False,
    modal_limit: bool = False,
) -> str:
    """**When it is read** (design §4.10 *When it is read: the sentence the sender sees*, TD-158,
    built by TD-168): one sentence saying when a message of `kind` to `s` will be read — the first
    case of the design's table that applies, in the doorbell's own order (`_bell_blocked`, then the
    budget), so it never promises a ring the doorbell would not give. A pure function of the record
    and the kind, never stored. `s` None with `seat` is a seat nobody fills (the placeholder card);
    `person` is whether the sender is a person, whose message refills the budget (*Time and a
    person restore it*), so only a session's reads *budget spent*; `unreachable` is the home's word
    that the record's host link is down (§4.4a), which the record's own state may not say yet;
    `rings` is whether its adapter has a composer the doorbell can type into (`_bell_blocked`).
    `refills` is a `reply` — the person's or a session's — that closes a question the seat itself
    sent (§4.9b *An answer waiting counts too*, TD-1051; TD-218 on a handed entry's thread): to a seat
    on call it counts toward the seat until a fill reads it, so it fills it as an `ask` does. `lapses`
    False is an `ask` that carries no bound — a handed entry, which never lapses (§4.10 *An entry
    handed to a seat*) — so the sentence names none. `cache` is the home's word that a ring would be
    a restart instead (§4.10 *A lapsed cache is started again, not rung*, TD-467:
    `agent_common.cache_restarts` on a record of its own host). `modal_limit` is the home's word that a
    `limited` record's cap is a modal rule's, a dialog with no reset (§4.3 *The limit dialog is read off
    the screen*: `agent_common.limit_is_modal` on a record of its own host). Advice, never a refusal."""
    ask = kind == "ask"
    tail = f" — an ask takes the default bound of {_hours(bound or ASK_BOUND)}" if ask and lapses else ""
    if s is not None and not mail_wakes(s):
        return (
            "lands in its inbox and wakes nothing: a person's session is never rung (invariant 5)"
            " — the card's unread chip shows it" + tail
        )
    state = s.state if s is not None else "exited"
    if state == "unreachable" or unreachable:
        # before the seat and exited rows: a down host's record reads *unreachable* on its card
        # whatever its last state, so the sentence under that card must too (techlead, PR #583)
        return "lands at the home; its host cannot be reached, so it is delivered when the link is back" + tail
    on_call = (seat or (s is not None and bool(s.seat))) and state in ("exited", "closed")
    if on_call:
        if ask or refills:
            return "fills this seat: a session starts on the next tick and reads it first" + tail
        return (
            "waits in the seat's mailbox: a note fills no seat, and is read at the next fill, which a question causes"
        )
    if s is None or state in ("exited", "closed"):
        return "read when this session is resumed, or started again under this name" + tail
    if state == "scheduled":
        # §6 *Start time* (TD-152): its mail moves to the session it becomes, which reads it first
        at = start_note({"state": state, "start_at": s.start_at}).removeprefix("starts ") or "its start time"
        return f"read when it starts, at {at}" + tail
    stop = s.wrapup_sent_at or s.wrapup_at
    if not stop and s.run_until:
        try:
            stop = datetime.fromisoformat(s.run_until.replace("Z", "+00:00")) <= now
        except ValueError:
            stop = False
    if stop or s.gated:
        why = "it is wrapping up" if stop else "it is paused for usage"
        return f"lands and waits: {why}, and mail never pushes a session past a stop" + tail
    if state == "limited" and modal_limit:
        return "lands and waits: the tool's usage-limit dialog is up; it is read once that is answered" + tail
    if state == "limited":
        cap = s.pending.text if s.pending and s.pending.text else "a usage cap"
        return f"lands and waits: its account is capped ({cap}), and it is rung after" + tail
    if state == "needs-you" and _held_by_subagents(s):
        # only a subagent's prompt holds an idle main thread (§4.2 *A subagent's dialog is held back*,
        # TD-950): the stack's restore brings back the `idle` beneath it, which the doorbell rings
        return "rung on the restore to idle, once the subagent's prompt ends" + tail
    if state == "needs-you":
        what = "question" if s.pending and s.pending.kind == "question" else "permission"
        return f"read once its {what} is answered and its turn ends" + tail
    if state in ("working", "stalled?"):
        return "read when its turn ends: it is rung on the tick after its Stop" + tail
    if s.told and not rings:
        return "lands; nothing is typed into this tool's pane — read on its next look or its next `ao` reply" + tail
    if s.told:
        # the budget gates the ring alone: a busy session reads its mail at its Stop regardless
        # (review of PR #583)
        if not person and wake_budget_spent(s, now):
            return "lands without waking it: its wake budget is spent, read on its next look" + tail
        if cache:
            return "started again on its brief within a tick, and reads it first" + tail
        failed = s.doorbell_failed or {}
        if failed.get("at") and _at_or_after(failed["at"], s.since):
            # this idle stretch's ring did not land (§4.10 *The doorbell*, TD-1079): never *rung*
            return (
                f"lands; its doorbell failed at {failed['at']} ({failed.get('error') or 'unknown'}), so nothing"
                " was typed — read on its next look or its next `ao` reply" + tail
            )
        return 'rung within a tick: the doorbell types "you have n unread" into its pane' + tail
    return (
        "lands; its idle is a guess from the screen, so nothing is typed into it"
        " — read on its next look or its next `ao` reply" + tail
    )
