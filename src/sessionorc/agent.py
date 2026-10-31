"""The host agent: one process per host, the only writer to `ao-*` tmux sessions (design §4.4, §9).

JSON-lines RPC over a Unix socket: `{"id": n, "method": "...", "params": {...}}` →
`{"id": n, "result": ...}` or `{"id": n, "error": "..."}`. `subscribe` turns the connection into
a stream of `{"event": "session", "session": {...}}` / `{"event": "gone", "id": ...}` lines; a
`wait` holds its connection until it returns and is dropped when that connection closes. A response
to a session with unread mail carries `"mail": {"unread": N, "wake_budget_spent": bool}` beside
its result or error (design §4.10 "a line on every `ao` reply").
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import contextlib
import copy
import fnmatch
import json
import logging
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from collections import OrderedDict, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import (
    adapters,
    agent_common,
    brief,
    build,
    containers,
    hosts,
    identity,
    link,
    mail,
    naming,
    paths,
    reports,
    work,
)
from sessionorc import balance as balance_mod
from sessionorc import cadence as cadence_mod
from sessionorc import ledger as ledger_mod
from sessionorc import seats as seats_mod
from sessionorc import settings as settings_mod
from sessionorc import settle as settle_mod
from sessionorc import spend as spend_mod
from sessionorc import work as work_mod
from sessionorc.agent_attention import AttentionMixin
from sessionorc.agent_ci import CiMixin
from sessionorc.agent_common import (  # re-exported: callers and tests read these from the agent
    _CSI,  # noqa: F401
    _ESC_OTHER,  # noqa: F401
    _LINE_BREAKS,  # noqa: F401
    _OSC,  # noqa: F401
    ACT_TIMEOUT,  # noqa: F401
    BACKUP_KEEP,  # noqa: F401
    BACKUP_MEMBERS,  # noqa: F401
    BOARD_EVERY,  # noqa: F401
    BRIEF_CLAUSE,  # noqa: F401
    BRIEF_SETTLE,  # noqa: F401
    CACHE_FLOOR,  # noqa: F401
    CACHE_LIFETIME,  # noqa: F401
    CLOSED_KEEP,  # noqa: F401
    COMPOSER_LINES,  # noqa: F401
    CONTEXT_AGAIN,  # noqa: F401
    CONTEXT_EVERY,  # noqa: F401
    CREATE_GRACE,  # noqa: F401
    DERIVE_EVERY,  # noqa: F401
    DOORBELL_TRIES,  # noqa: F401
    ENTRY_PRIORITIES,  # noqa: F401
    ENTRY_TYPES,  # noqa: F401
    FILE_CAP,  # noqa: F401
    FILES_MAX,  # noqa: F401
    FILL_CEILING,  # noqa: F401
    FILL_WINDOW,  # noqa: F401
    FINISHED_SETTLE,  # noqa: F401
    FIRST_PROMPT_BOUND,  # noqa: F401
    FIRST_PROMPT_HOOK_WAIT,  # noqa: F401
    FIRST_PROMPT_NO_HOOK,  # noqa: F401
    FIRST_PROMPT_TRIES,  # noqa: F401
    FLOW_CLAUSE,  # noqa: F401
    GH_TIMEOUT,
    GIT_EVERY,  # noqa: F401
    HOME_EDITS,  # noqa: F401
    ID_RECHECK,  # noqa: F401
    IDLE_NUDGE,  # noqa: F401
    INTENT_FIELDS,  # noqa: F401
    LANE_NEWS_NAMED,  # noqa: F401
    LAUNCH_KEYS,  # noqa: F401
    LEASE_TTL,  # noqa: F401
    LINKS_EVERY,  # noqa: F401
    MODEL_EVERY,  # noqa: F401
    MODEL_FILE,  # noqa: F401
    NODE_ACTS,  # noqa: F401
    NODE_READS,  # noqa: F401
    NOTICE_LAG,  # noqa: F401
    ORPHAN_AFTER,  # noqa: F401
    OWED_NAMED,  # noqa: F401
    PASTE_SHOW_SECONDS,  # noqa: F401
    PATHS_PRIVATE,
    PATHS_RUN_CHARS,
    PATHS_RUNS_MAX,
    PEER_UNREADABLE,  # noqa: F401
    PRUNE_EVERY,  # noqa: F401
    PUSH_OPEN,  # noqa: F401
    RELAUNCH_KEPT,
    RELAUNCH_KEYS,
    REMOVED_GUARD_SECONDS,  # noqa: F401
    REPORT_EVERY,  # noqa: F401
    REPORT_WRITE,  # noqa: F401
    REPOS_EVERY,  # noqa: F401
    RESTART_CEILING,  # noqa: F401
    RESTART_EARLY,  # noqa: F401
    RESTART_SETTLE,  # noqa: F401
    RESTART_WINDOW,  # noqa: F401
    RESUME_MIN,  # noqa: F401
    ROUND_LINE_CAP,  # noqa: F401
    SEAT_IDLE_GRACE,  # noqa: F401
    SEAT_PR_WAIT,  # noqa: F401
    SEND_STALL_SECONDS,  # noqa: F401
    SETTLED,  # noqa: F401
    SHELL_WAIT,  # noqa: F401
    STALL_AFTER,  # noqa: F401
    SUBMIT_SECONDS,  # noqa: F401
    TAIL_LINES,  # noqa: F401
    TICK_SECONDS,  # noqa: F401
    TITLE_CAP,  # noqa: F401
    TRAIL_FLOOR,  # noqa: F401
    TRAIL_KEEP,  # noqa: F401
    TRANSCRIPT_TURNS_MAX,
    USAGE_COOL,  # noqa: F401
    USAGE_FRESH,  # noqa: F401
    USAGE_ONLY_EVERY,  # noqa: F401
    WORK_DAY,  # noqa: F401
    WORK_EARLY,  # noqa: F401
    WORK_SETTLE,  # noqa: F401
    WORK_STARTS_DAY,  # noqa: F401
    WRAPUP_GRACE,  # noqa: F401
    LeadTyped,
    RpcError,  # noqa: F401
    _alarm_report,  # noqa: F401
    _alarm_since,  # noqa: F401
    _alarm_words,  # noqa: F401
    _cap,  # noqa: F401
    _clean,  # noqa: F401
    _clean_answer,  # noqa: F401
    _context_bound,  # noqa: F401
    _controllers,  # noqa: F401
    _cool_left,  # noqa: F401
    _counted,  # noqa: F401
    _drop_unknown,  # noqa: F401
    _duration,  # noqa: F401
    _ended_by,  # noqa: F401
    _falsy,  # noqa: F401
    _grants,  # noqa: F401
    _is_branch_claim,  # noqa: F401
    _lane,  # noqa: F401
    _new_done,  # noqa: F401
    _older,  # noqa: F401
    _oldest_first,  # noqa: F401
    _pane_title,  # noqa: F401
    _parse,  # noqa: F401
    _peer_args,  # noqa: F401
    _peer_pid,  # noqa: F401
    _pr,  # noqa: F401
    _prune_tallies,  # noqa: F401
    _read_capped,  # noqa: F401
    _recent,  # noqa: F401
    _ref,  # noqa: F401
    _reply_line,  # noqa: F401
    _reported,  # noqa: F401
    _restart_reading,  # noqa: F401
    _review,  # noqa: F401
    _slices,  # noqa: F401
    _source,  # noqa: F401
    _start_time,  # noqa: F401
    _stop_time,  # noqa: F401
    _urgent,  # noqa: F401
    _usage_checked_at,  # noqa: F401
    _usage_key,  # noqa: F401
    _Wait,  # noqa: F401
    backup_store,  # noqa: F401
    cache_lapsed,  # noqa: F401
    cache_restarts,  # noqa: F401
    claim_draft,  # noqa: F401
    closer_of,
    draft_folder,  # noqa: F401
    idle_from,  # noqa: F401
    launch_params,  # noqa: F401
    limit_is_modal,  # noqa: F401
    log,  # noqa: F401
    model_env,  # noqa: F401
    on_its_own,  # noqa: F401
    person_only,  # noqa: F401
    read_checkout,  # noqa: F401
    read_draft_claim,  # noqa: F401
    run_ended,
    shells_live,  # noqa: F401
    stat_dir,  # noqa: F401
    subagents_live,  # noqa: F401
    tick_ready,  # noqa: F401
    write_model_file,  # noqa: F401
)
from sessionorc.agent_doctor import DoctorMixin
from sessionorc.agent_hook import HookMixin
from sessionorc.agent_identity import IdentityMixin
from sessionorc.agent_ids import IdsMixin
from sessionorc.agent_inbox import InboxMixin
from sessionorc.agent_link import LinkMixin
from sessionorc.agent_mail import MailMixin
from sessionorc.agent_notify import NotifyMixin
from sessionorc.agent_promote import PromoteMixin
from sessionorc.agent_rank import RankMixin
from sessionorc.agent_remote import RemoteMixin
from sessionorc.agent_serve import ServeMixin
from sessionorc.agent_settings import SettingsMixin
from sessionorc.agent_shape import ShapeMixin
from sessionorc.agent_spend import SpendMixin
from sessionorc.agent_sync import SyncMixin
from sessionorc.agent_tick import TickMixin
from sessionorc.agent_wake import WakeMixin
from sessionorc.gitinfo import (
    REAP_STEP,
    REAP_WITHIN,
    TIMED_OUT,
    GitPickError,
    WorktreeError,
    ensure_worktree,
    git_info,
    main_checkout,
    pick_files,
    reap_worktree,
    rehydrate,
    reweigh_gone,
    weigh_branches,
    work_left,
)
from sessionorc.mail import ACTING_RPCS  # noqa: F401 — re-exported: callers read it from the agent
from sessionorc.models import (
    GRANTS,
    PERSON,
    PROGRESS_STATUSES,
    WRAPUP_PROMPT,
    FindingEntry,
    MailEntry,
    ProgressEntry,
    SendEntry,
    Session,
    State,
    now_iso,
    turn_stamp,
)
from sessionorc.store import (
    AttentionStore,
    DoingLogStore,
    EventQueue,
    HostStore,
    IdentityAlarmStore,
    PersonInboxStore,
    RepoStore,
    SessionStore,
    UsageStore,
)
from sessionorc.tmux import ARG_LIMIT, DuplicateSession, Tmux


def _inherits_made(new: Session, old: Any) -> bool:
    """Whether `new`, superseding `old`, inherits its `worktree_made`: `old` had it and the start reused its
    worktree at the same `dir` — a restart, Resume, scheduled start, team Start, refill or New session under a
    closed holder's name (design §4.1 *A close reaps the worktree it made*, TD-979)."""
    return isinstance(old, Session) and bool(old.worktree_made) and old.dir == new.dir


def _migrate_made(s: Session, host: str) -> bool:
    """The one-time mark of a record from before TD-979 (design §4.1): a team member's worktree is ShiftLead's by
    construction, so an absent `worktree_made` on this host's record holding a `worktree`, a `team` and
    `unattended` becomes true. Idempotent, and never touches a `False`. Answers whether it marked."""
    if s.worktree_made is None and s.host == host and s.worktree and s.team and s.unattended:
        s.worktree_made = True
        return True
    return False


def _place_attachment(where: Path, name: str, place: Any) -> Path:
    """The first free name in `where` for `name` — `paths.attachment_name(name)`, or with `-2`,
    `-3`… before its extension where that is taken — taken by `place(path)`, which raises
    `FileExistsError` when the name is someone's: never over an earlier attachment, whose path a
    sent prompt may still name."""
    base = paths.attachment_name(name)
    stem, dot, ext = base.rpartition(".")
    if not stem:
        stem, dot, ext = base, "", ""
    for n in range(1, 1000):
        path = where / (base if n == 1 else f"{stem}-{n}{dot}{ext}")
        try:
            place(path)
        except FileExistsError:
            continue
        return path
    raise RpcError(f"attach: {base} is taken a thousand times over in {where}")


def _path_private(real: str) -> bool:
    """Whether a real path is one `PATHS_PRIVATE` keeps as text (§4.6, TD-688): under one of its
    trees, through one of its directories, or one of its file names. A name with a `/` in it is
    matched as the path's last components."""
    trees, dirs, names = PATHS_PRIVATE
    if any(real == t or real.startswith(t + "/") for t in trees):
        return True
    parts = real.split("/")
    for d in dirs:
        want = d.split("/")
        if any(parts[k : k + len(want)] == want for k in range(len(parts) - len(want) + 1)):
            return True
    for n in names:
        want = n.split("/")
        if len(parts) >= len(want) and all(
            fnmatch.fnmatchcase(a, b) for a, b in zip(parts[-len(want) :], want, strict=True)
        ):
            return True
    return False


def _resolve_paths(runs: list[str], cwd: Path) -> dict[str, str | None]:
    """`rpc_paths`' disk half: each run to its real path when that is a regular file this process
    can read and `PATHS_PRIVATE` does not hold, else `None`. Any `OSError` on the way is `None` too."""
    out: dict[str, str | None] = {}
    for run in runs:
        try:
            real = os.path.realpath(cwd / Path(run).expanduser())
            ok = os.path.isfile(real) and os.access(real, os.R_OK) and not _path_private(real)
            out[run] = real if ok else None
        except (OSError, ValueError, RuntimeError):
            out[run] = None
    return out


def _registered_checkout(repo: Any) -> Path | None:
    """`rpc_paths`' `repo`: its real path (`~` expanded) when that is one of `hosts.local_host().repos()`'
    real paths, by equality — a directory inside a checkout is none — else `None`, an empty, non-string
    or unreadable one among them (`realpath("")` would be the process's working directory)."""
    if not isinstance(repo, str) or not repo:
        return None
    try:
        real = os.path.realpath(os.path.expanduser(repo))
        roots = {os.path.realpath(os.path.expanduser(r)) for r in hosts.local_host().repos()}
    except (OSError, ValueError, RuntimeError):
        return None
    return Path(real) if real in roots else None


def _write_attachment(where: Path, name: str, raw: bytes) -> Path:
    """`raw` as a new `0600` file in `where` (made `0700`), named by `_place_attachment`."""
    where.mkdir(mode=0o700, parents=True, exist_ok=True)

    def write(path: Path) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)

    return _place_attachment(where, name, write)


def _mint_draft() -> str:
    """A new draft token (§4.4 *The Add entry form's draft*, TD-630): `draft-<8 hex>` whose folder
    does not exist yet; the folder itself is made by the first file's write."""
    while True:
        token = f"draft-{secrets.token_hex(4)}"
        if not (paths.attachments_dir() / token).exists():
            return token


def _start_part(part: Path, raw: bytes) -> None:
    """An upload's first piece as its new `0600` `.part` (§4.4 *Attachment drop*, TD-478)."""
    part.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)


def _append_part(part: Path, offset: int, raw: bytes, total: int) -> tuple[int, str]:
    """One later piece of an upload appended to its `.part`: `(written, why)`, `why` empty when it
    went on, else the refusal — the `.part` deleted with it, since an upload out of order is no
    longer the file. A missing `.part` was cancelled or swept, and is never made again here: it is
    opened without `O_CREAT`, so a cancel between two pieces cannot leave a new one behind."""
    try:
        fd = os.open(part, os.O_WRONLY | os.O_APPEND)
    except FileNotFoundError:
        return 0, "is gone (cancelled, or nothing written to it for an hour)"
    with os.fdopen(fd, "ab") as f:
        have = os.fstat(fd).st_size
        if offset != have:
            part.unlink(missing_ok=True)
            return have, f"sent a piece at {offset} bytes, but {have} are written: the upload is dropped"
        if have + len(raw) > total:
            part.unlink(missing_ok=True)
            return have, f"sent {have + len(raw)} bytes of a {total}-byte file: the upload is dropped"
        f.write(raw)
    return have + len(raw), ""


def _finish_part(part: Path, name: str) -> Path:
    """A whole `.part` linked into its final name — the `-2`, `-3`… rule applied now, `os.link`
    never over a file — and unlinked, so no prompt can name a file that is not whole."""
    try:
        path = _place_attachment(part.parent, name, lambda p: os.link(part, p))
    except BaseException:
        part.unlink(missing_ok=True)  # the upload is spent either way: nothing names this `.part`
        raise
    part.unlink(missing_ok=True)
    return path


def _mib(n: int) -> str:
    """A size as the attach refusal says it: whole MiB, rounded up, or GiB from a GiB on."""
    if n >= 1 << 30 and n % (1 << 30) == 0:
        return f"{n >> 30} GiB"
    return f"{-(-n // (1 << 20))} MiB"


def _clock_words(iso: str | None) -> str:
    """A stored instant in this host's clock, *14:05*, for a refusal's words; the instant itself where
    it does not parse, and *its deadline* with none."""
    if not iso:
        return "its deadline"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError:
        return iso


def _bound(path: Path) -> socket.socket:
    """A unix socket bound at `path` and **born `0600`** (TD-260): made and bound by hand under a
    umask of `0177`, with no `await` inside, and handed to `start_unix_server(sock=…)`. Binding
    through `path=` and then `chmod` left the file at the umask's mode for a moment — and a umask
    held across an awaited bind would leak into whatever else the loop creates meanwhile."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        s.bind(str(path))
    except BaseException:
        s.close()
        raise
    finally:
        os.umask(old)
    return s


class HostAgent(
    ServeMixin,
    TickMixin,
    PromoteMixin,
    SyncMixin,
    SpendMixin,
    ShapeMixin,
    IdsMixin,
    RankMixin,
    AttentionMixin,
    NotifyMixin,
    CiMixin,
    WakeMixin,
    HookMixin,
    SettingsMixin,
    InboxMixin,
    MailMixin,
    IdentityMixin,
    DoctorMixin,
    RemoteMixin,
    LinkMixin,
):
    def __init__(
        self,
        *,
        tmux: Tmux | None = None,
        store: SessionStore | None = None,
        events: EventQueue | None = None,
        identity_mode: str | None = None,
        proc: identity.ProcReader | None = None,
    ):
        paths.ensure_layout()
        # What `host` reports about this process (design §4.4 *Version skew is survivable*, TD-062):
        # when it started, and the commit its install was built from, read once — a promote replaces
        # the files under a running agent, and what is running is what was read at start.
        self.started_at = now_iso()
        self.build = build.info()
        # Who is calling (design §4.8a, TD-077): `off | observe | enforce` from `local: {identity: …}`,
        # the panes the last list saw, the home's own alarms (about no record), and a tally of
        # connections by class and deciding signal since start — what `ao identity` prints, and what
        # turning a host from `observe` to `enforce` is decided on.
        self.identity_mode = identity.mode_of(identity_mode or hosts.local_host().identity)
        self.proc: identity.ProcReader = proc or identity.LinuxProc()
        self._id_panes: list[identity.Pane] = []
        # A record's pane that left the list, and when (monotonic): a hook of its ending process may
        # still arrive (TD-115, `identity.PANE_GONE_GRACE`).
        self._id_gone: dict[str, tuple[identity.Pane, float]] = {}
        self._id_scopes: dict[int, str] = {}  # pane pid → its own cgroup, or "" (TD-360)
        self._id_own_cg: str | None = None  # the host agent's own cgroup, never a pane's scope
        self._id_other_scopes: set[str] = set()  # own scopes of the server's panes no record holds (TD-362)
        self._id_conns: dict[Any, identity.Channel] = {}  # a connection's classification, for its life
        self._id_dirty: set[str] = set()  # records whose alarm counts moved since their last write
        self._id_listed_at = 0.0
        self._id_list_lock = asyncio.Lock()
        self._id_detached: str | None = None
        self._id_tmux: tuple[int, int] | None = None  # (pid, start time): the server the answer is about
        # the first server read, kept: `ao doctor` reads a server replaced under the agent against it (§4.7, TD-465)
        self._id_tmux_first: tuple[int, int] | None = None
        self.cgroup_root = "/sys/fs/cgroup"  # where a pane's own cgroup is made (§4.8a, TD-495); tests point it away
        self._id_rechecked = 0.0  # monotonic; the check is re-read on a cadence, not per connection
        # The home's own alarms **persist** (TD-077 step 2): a forgery aimed at no record — a claim
        # from outside every pane — is evidence, and evidence that dies with the process is a page
        # that says *no alarms* about the night the agent was restarted. The tally does not: it
        # says *since the agent started*, and §4.8a means that literally.
        self.identity_store = IdentityAlarmStore()
        # The attention trail and the state rows' snoozes (design §4.10 *The Inbox is a queue*,
        # TD-079). A state row is a view of a record: when its need goes away by some road that is
        # not the person's — the session was resumed, the permission was answered in the terminal,
        # the work was pushed — the row used to vanish with no trace, which is what *it disappeared
        # when I read it* was. The home records the ending instead.
        self.attention_store = AttentionStore()
        self._ticker: asyncio.Task | None = None  # the tick loop, once `serve` is running
        self.trail, self.attention_snoozed = self.attention_store.load()
        # `<sid>|state` / `<sid>|alarm` → (the row kind it is showing, when that row began, what it
        # said). Empty on load **on purpose**: the first tick after a restart reads every live row
        # as one that has just begun, so a row that was already up leaves no trail when it ends —
        # one ending lost per restart, which is better than inventing one the agent never saw, and
        # the record itself is still there to be read.
        self._attention: dict[str, tuple[str, str, str]] = {}
        # sid → how its current row will have ended, when the home knows better than *resolved*:
        # written by the act that ended it (`decide`, `identity_ack`, a resume, a forget).
        self._attention_how: dict[str, str] = {}
        # Told on Telegram (§4.10, TD-319): when each recent message went, for the burst's window, and
        # the last send's result for the `host` read — in memory: a restart forgets both, and `notified`
        # (on the attention store) is what keeps a standing row from being told twice
        self._notify_sent: list[datetime] = []
        self._notify_last: dict[str, Any] = {}
        self._notify_quiet_until: datetime | None = None  # after the burst's *and more*, nothing until then
        self._notify_watched_at: datetime | None = None  # the last person's read from a visible page
        self.identity_alarms: list[dict[str, Any]] = self.identity_store.load()
        self._id_host_dirty = False  # counts moved since the last write; the tick writes them
        self.identity_tally: dict[str, int] = defaultdict(int)
        self.tmux = tmux or Tmux()
        self.store = store or SessionStore()
        self.events = events or EventQueue()
        # This host's name (design §4.4a): what `host` on every record holds, and what an address
        # is qualified against — `ao-x@<this host>` is stored bare (`naming.qualify`).
        self.host = hosts.local_host().name
        # Home or node (design §4.4a, TD-057 step 2). With no `home:` in hosts.yml, or one naming
        # this host, this agent is the home and nothing below differs from phase 1. A node keeps
        # everything that touches its machine and its own host's records on disk — the replica.
        self.home = hosts.home_name()
        self.mode = "node" if self.home != self.host else "home"
        # The link (§4.4a "The link's protocol", TD-057 step 3a). At the home: one entry per node
        # that has ever connected — `{up, since, why}` — and the live `Mux` while it is up. At a
        # node: the same shape for its one link to the home.
        self.links: dict[str, dict[str, Any]] = {}
        self._link_muxes: dict[str, link.Mux] = {}
        # The container supervisor (§4.4a "The home supervises it", step 3c.3): per container node,
        # what the tick is doing about a down link — `{doing, since, attempts, next}` — and the one
        # action in flight. `container_runner` is the seam the suite replaces.
        self.supervision: dict[str, dict[str, Any]] = {}
        self._supervising: dict[str, tuple[asyncio.Task[None], containers.Runner]] = {}
        self.container_runner: Callable[[], containers.Runner] = lambda: containers.Runner(log=log.info)
        self.home_link: dict[str, Any] = {"up": False, "since": now_iso(), "why": "not dialed yet"}
        self._home_mux: link.Mux | None = None
        # A node's calls in flight here, by the node's token (step 5): a `wait` the node cancels
        self._forwarded_calls: dict[str, asyncio.Task[Any]] = {}
        # Other hosts' records, at the home (§4.4a "A node's records at the home", step 3b): held
        # apart from `self.sessions` — host → id → record — so nothing that reads this host's panes
        # ever meets one. Loaded from `remote/<host>/`, so a restarted home still shows them,
        # unreachable, until their node dials in.
        self.remote: dict[str, dict[str, Session]] = {}
        self._remote_stores: dict[str, SessionStore] = {}
        if self.mode == "home" and paths.home().joinpath("remote").is_dir():
            for d in sorted(paths.home().joinpath("remote").iterdir()):
                if d.is_dir():
                    self.remote[d.name] = self._remote_store(d.name).load_all()
        # What the home last pushed each linked node about each of its records (`intent`, step
        # 4b.2): host → id → payload. Present from that link's snapshot until the link goes, so a
        # new link is pushed everything once and then what changes.
        self._intent_sent: dict[str, dict[str, str]] = {}
        # A node's side of the same: what it last told the home about each record, and when.
        self._reported: dict[str, tuple[str, str, float]] = {}
        # A node's hint of each record's mail, as the home last pushed it: `(unread, budget spent)`.
        # Never an inbox — the mailbox is the home's — only what a reply's mail line needs.
        self._mail_hints: dict[str, tuple[int, bool, list[str]]] = {}
        # …and the home's `asks_waiting` for each (§4.9b): a node holds no inbox to count, so its own
        # view of a record shows the number the home last pushed, as fresh as the link.
        self._asks_hints: dict[str, int] = {}
        self._snapshot_sent = False
        self._bg: set[asyncio.Task[None]] = set()  # fire-and-forget tasks, held so they are not collected
        if self.mode == "node":
            log.warning(
                "node of %s: this host's sessions only while the link is down — mail, reports, home-owned edits "
                "and sessions' acts on others are then refused, and forwarded to the home while it is up. "
                "This host calls itself %s: if this machine IS %s, set `local: {name: %s}` in hosts.yml — without "
                "it the name is the machine's hostname, and a home that does not recognise its own name is a node.",
                self.home,
                self.host,
                self.home,
                self.home,
            )
        self.sessions: dict[str, Session] = self.store.load_all()
        # The org's person inbox (design §4.10): held here, on no session record, in its own file.
        self.person_store = PersonInboxStore()
        self.person_inbox: list[MailEntry] = self.person_store.load()
        self.person_store.on_save = self._inbox_changed
        for s in self.sessions.values():
            # `prompt` pendings (Claude's idle_prompt) stopped being an alert on 2026-09-06; a record
            # written before that would otherwise show needs-you until the next hook event.
            if s.pending and s.pending.kind == "prompt":
                s.set_state("idle", confidence="hook")
                self.store.save(s)
            if self._sweep_prompts(s):  # no waiter outlives the host agent (§4.2, TD-950)
                self.store.save(s)
            if not s.host:  # a record written before TD-057 step 1: it ran here, so it is this host's
                s.host = self.host
                self.store.save(s)
            if _migrate_made(s, self.host):
                self.store.save(s)
        # (sender, client nonce) → the verdict its first send got (design §4.4a "Delivery and
        # time"): a retry after a reconnect never lands twice and is not an identical repeat —
        # it returns the original verdict. Bounded, oldest out, in memory only.
        self._nonces: OrderedDict[tuple[str, str], tuple[dict[str, Any] | None, RpcError | None]] = OrderedDict()
        self._dir_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # subscriber → what it was last sent, per session (TD-009: a new tab gets its own snapshot
        # without every other tab being re-sent everything)
        self._subscribers: dict[asyncio.StreamWriter, dict[str, str]] = {}
        # subscriber → the dotted paths its `repos` events are sent without (the subscribe's `omit`,
        # TD-754): a page's stream is not sent the parts of a reading its pages never draw
        self._sub_omit: dict[asyncio.StreamWriter, tuple[str, ...]] = {}
        self._gone: list[str] = []  # forgotten ids not yet announced (`_forget` → `_push_changes`)
        self._waits: set[_Wait] = set()  # every `wait` blocked right now, each on its own connection
        # The doorbell (design §4.10, TD-052 step 7): per session, the idle stretch it last rang in —
        # `{rev, rung, failures}`, `rev` being the record's state counter, so a new stretch is a new
        # entry — and the rings in flight, one per session.
        self._bells: dict[str, dict[str, Any]] = {}
        self._ringing: dict[str, asyncio.Task[None]] = {}
        # A ring's answer (§4.10 *A ring is answered by a read, or the bell stops*, TD-347): per session,
        # the unread count the last ring rang with and whether its turn has started (`{count, turned}`),
        # judged at that turn's `Stop`; and the run of rings so answered with nothing read.
        self._rang: dict[str, dict[str, Any]] = {}
        self._unread_rings: dict[str, int] = {}
        # a brief whose line went in and whose paste did not (TD-347): its next try pastes the brief alone
        self._lead_typed: set[str] = set()
        self._prompting: dict[str, asyncio.Task[None]] = {}  # a brief being typed (§4.1, TD-339), one per session
        # One typist per pane (TD-094): `_submit` holds its session's lock from paste to confirmed
        # submit, and a ring holds it from reading the composer to its own submit — so a ring never
        # pastes into the middle of a `send`, where the two lines would be submitted as one.
        self._typing: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # (session id, key) → a keyed send still typing: its repeat awaits its outcome (§4.10, TD-806)
        self._keyed_sends: dict[tuple[str, str], asyncio.Future[None]] = {}
        # every open client connection: a stop closes them, or `Server.wait_closed()` waits on the
        # UI's subscription and each blocked `wait` forever (TD-058)
        self._conns: set[asyncio.StreamWriter] = set()
        # (session id, tool_use_id) → the hook's pending decision and the thread that asked it: a
        # subagent's id, or None for the main thread (design §4.2 *A waiter is keyed by its call*, TD-950)
        self._waiters: dict[tuple[str, str], tuple[asyncio.Future[dict[str, Any]], str | None]] = {}
        # session id → thread (a subagent's id, or None) → its open calls, `(tool_use_id, call_sig)` oldest
        # first: what a permission, which names no call, is matched to (§4.2, TD-950). In memory only.
        self._open_calls: dict[str, dict[str | None, list[tuple[str, str]]]] = {}
        # session id → when its last open prompt had a sure end (`time.monotonic()`): a decision, the asked
        # call's own event, or an event naming no call; the tool's notice inside `NOTICE_LAG` of it is that
        # prompt's (§4.2 *Open prompts are a stack*, TD-950). In memory only: a restart lets one notice through.
        self._sure_end: dict[str, float] = {}
        # records whose emptied stack restored a screen rule's `needs-you`: the next tick asks the rules once,
        # whatever the hook's freshness (§4.2, TD-950)
        self._recheck: set[str] = set()
        self._git_checked: dict[str, datetime] = {}
        # the status each record's recent files were last read at (§4.2, TD-538): `(oid, dirty, porcelain)`
        self._files_read: dict[str, tuple[Any, ...]] = {}
        self._derived_at: dict[str, datetime] = {}
        self._model_checked: dict[str, datetime] = {}
        self._context_checked: dict[str, datetime] = {}  # the context reading's cadence (TD-190)
        self._shells_saved: dict[str, datetime] = {}  # when a record's `shells_at` was last saved (TD-766)
        self._links_checked: dict[str, datetime] = {}  # the links read's cadence (TD-543)
        # the links read's byte cursor per record, with the tool session it is into (TD-543): in memory,
        # so a restart reads the transcript again from 0 and the merge drops what the record holds
        self._links_cursor: dict[str, tuple[str, int]] = {}
        # the prompts read's cadence and cursor, as the links read's (TD-976), and the records a hook made due
        self._prompts_checked: dict[str, datetime] = {}
        self._prompts_cursor: dict[str, tuple[str, int]] = {}
        self._prompts_due: set[str] = set()
        # When a `kill` or a `close` destroyed a pane, so a tick holding a pane list taken before
        # it does not observe a session that is already gone (TD-063). Dropped as soon as a
        # snapshot newer than the kill arrives, so it holds at most one tick's worth of ids.
        self._killed_at: dict[str, datetime] = {}
        # When a `kill` ended each id's run (TD-822), kept past `_scrub`: a resume that takes the id at once
        # must still know that the killed run's own `SessionEnd`, landing late, is not the new run's end.
        self._killed_run_at: dict[str, float] = {}
        self._derive_task: asyncio.Task[None] | None = None
        self._seat_count_task: asyncio.Task[None] | None = None  # §6 rule 3's `gh` read, detached
        self._seat_counted_at = datetime.min.replace(tzinfo=UTC)
        # rule 7's mark (TD-217 slice 3): the detached read of every brief's sources, when it last
        # ran, and per record the blob ids that first read otherwise and since when
        self._brief_task: asyncio.Task[None] | None = None
        # rule 10 (TD-258): the detached run of the cadence check, one PR a run, and when it last ran
        self._cadence_task: asyncio.Task[None] | None = None
        self._cadence_read_at = datetime.min.replace(tzinfo=UTC)
        # rule 12 (TD-258): the detached read of each root's docs/cadence-changes.md, and when it last ran
        self._conventions_task: asyncio.Task[None] | None = None
        self._conventions_read_at = datetime.min.replace(tzinfo=UTC)
        # and the `(root, line)` info lines it logged while their condition lasts, each logged once (TD-1046)
        self._conventions_quiet: set[tuple[str, str]] = set()
        # rule 11 (TD-258): the detached read of merged PRs against `held:`, when it last ran, what
        # was settled (address, the record's `created`, PR) and when each PR was last tried
        self._held_task: asyncio.Task[None] | None = None
        self._held_read_at = datetime.min.replace(tzinfo=UTC)
        self._held_settled: set[tuple[str, str, int]] = set()
        self._held_tried: dict[tuple[str, int], float] = {}
        # §4.9 *What is left at the home has a history*: one committer, so one git at a time
        self._defs_lock = asyncio.Lock()
        self._defs_task: asyncio.Task[None] | None = None
        self._defs_read_at = datetime.min.replace(tzinfo=UTC)
        self._brief_read_at = datetime.min.replace(tzinfo=UTC)
        self._brief_differs: dict[str, tuple[tuple[str, ...], datetime]] = {}
        # §6 *A reading the gate can no longer trust* (TD-233 slice 4): the accounts told of a pause
        # on a projection while it stands, and the day each was last told its usage is unknown
        self._projection_noted: set[str] = set()
        self._unknown_noted: dict[str, str] = {}
        # when a hook last reported on a session: a screen-rule verdict never outranks a hook
        # state fresher than STALL_AFTER (design §4.2); a session no hook has reported on yet — the
        # trust dialog case — takes the classifier's verdict at once (TD-015)
        # Seeded on load: a hook-confirmed record was fed by a live hook stream until the agent
        # stopped, and `since` is a transition time, not a hook time — so count it fresh as of now.
        # A restart must never let the screen outrank a state a hook just reported. A new launch is
        # `confidence: hook` from its create, so only a record a hook reached (`hook_seen_at`), or one
        # whose brief is no longer due — every record from before the field — is seeded: a launch whose
        # first hook was lost keeps its scraped send and its mark across the restart (§4.1, TD-720).
        self._last_hook: dict[str, datetime] = {
            sid: datetime.now(UTC)
            for sid, s in self.sessions.items()
            if s.told and (s.hook_seen_at or not self._first_prompt_due(s))
        }
        # sid → the state, pending and confidence a screen rule's verdict replaced (TD-306): what
        # the record goes back to when that screen is gone and no hook has spoken since; dropped
        # when a hook sets the state. Not kept across a restart: the record then goes to `idle`.
        self._hook_state: dict[str, tuple[str, Any, str]] = {}
        # When a hook event last reached a record **live**, in epoch seconds (TD-169): a queued
        # event stamped before it is older than the state it would set, so its state is skipped.
        self._live_hook_at: dict[str, float] = {}
        # entries whose *Put on the board* is under way (TD-140): one press per entry at a time
        self._board_adding: set[str] = set()
        # profile → last usage dict from its adapter (`usage_for`), and when it was last asked
        # The last good reading per profile, kept across a restart (TD-087) — with, beside the
        # windows, why the *last poll* failed, which the page draws as a stale chip rather than
        # as nothing at all. `_usage_wait` is the cool-off a 429 sets and a success clears.
        # **The reading is the account's** (§4.2a, TD-122): `_usage_acct` holds one reading per
        # `(adapter, account)` key and the poll, its clock and its backoff are keyed on that;
        # `_usage` is the same reading copied under every live profile sharing the account, with
        # the account and the tool's display name beside it, which is what the gate, `limited`,
        # the `usage` RPC and the chip read.
        self.usage_store = UsageStore()
        self._usage: dict[str, dict[str, Any]] = self.usage_store.load()
        # the profiles restored above: a node's keeps its reading until the node's first report
        self._usage_restored: set[str] = set(self._usage)
        self._usage_acct: dict[str, dict[str, Any]] = {}
        # (node, profile) → the account key that node keys the profile by (§4.4 *A node's sessions
        # report to their node*, TD-233 slice 2): its credentials decide, not a profile of that name here
        self._usage_remote_keys: dict[tuple[str, str], str] = {}
        # (node, account key) → (the link, what it was last sent): the home's reading goes to a node
        # when it moves, and again on a new link
        self._usage_told: dict[tuple[str, str], tuple[Any, str]] = {}
        # …and the **allowance** survives with it (anchor's read of PR #307): a held reading is as
        # good as a poll made at its `fetched`, so the first poll after a promote waits until
        # `fetched + USAGE_FRESH`, never sooner. A reading with no readable time is polled at once.
        # Seeded per account on the first refresh, from its profiles' held readings.
        self._usage_checked: dict[str, float] = {}
        self._usage_wait: dict[str, float] = {}
        self._usage_only_at: dict[str, float] = {}  # when an endpoint-only window was last asked for (TD-233)
        self._usage_task: asyncio.Task[None] | None = None
        # A metered account's ledger (§4.4 *Usage*, TD-151): `spend.json`, the rows and the cursors
        # that make its reading a sum, written only when it changed. `_metered` is the profiles the
        # last pass found billed `metered` — what the gate reads amounts for — and `_metered_shown`
        # those whose reading is in `_usage`, so one no live session runs under leaves the top bar.
        self.spend_store = spend_mod.SpendStore()
        self._spend: dict[str, dict[str, Any]] = self.spend_store.load()
        self._spend_saved = json.dumps(self._spend, sort_keys=True)
        self._spend_lock = asyncio.Lock()  # one writer of `spend.json` (TD-643)
        self._spend_pruned = ""
        self._spend_reason: dict[str, str] = {}
        self._metered: set[str] = set()
        self._billing_seen: dict[str, tuple[float, bool]] = {}  # profile → (monotonic, metered), for the gate
        self._metered_shown: set[str] = set()
        self._spend_task: asyncio.Task[None] | None = None
        # The seat ledger (§4.4 *Spend per seat*, TD-830): `seat_spend.json`, every profile's turns
        # charged to a record and a reference, read by `seats`; its pass runs once a minute at the home.
        self.seat_store = seats_mod.SeatStore()
        self._seats: dict[str, Any] = self.seat_store.load()
        self._seats_saved = json.dumps(self._seats, sort_keys=True)
        self._seats_lock = asyncio.Lock()
        self._seats_task: asyncio.Task[None] | None = None
        self._seats_at = 0.0  # monotonic: when the last pass started
        self._seats_pruned = ""
        self._seat_reason: dict[str, str] = {}
        self._seat_live: set[tuple[str, str]] = set()  # the (adapter, profile) pairs live at the last seat pass
        self._seat_ended: set[tuple[str, str]] = set()  # pairs whose last live session ended, not yet read since
        self._seat_link: dict[str, dict[str, Any]] = {}  # a node's: per profile, the home's seat cursors on this link
        # A node's side of the road (§4.4a, TD-151 slice 4): per profile, the cursors and seeding the
        # home answered on this link (cleared on each dial) and the last cursors it acknowledged (kept
        # for the offline figure); per account, the sums the home last sent. The home's side: the
        # accounts each node named in a `spend`, and what each was last told.
        self._spend_link: dict[str, dict[str, Any]] = {}
        self._spend_acked: dict[str, dict[str, int]] = {}
        self._spend_held: dict[str, dict[str, Any]] = {}
        self._spend_named: dict[str, dict[str, set[str]]] = {}
        self._spend_node_prices: dict[str, dict[str, float]] = {}  # profile → prices, as a node's `spend` declared
        self._spend_told: dict[tuple[str, str], str] = {}
        # The repo facts per registered checkout (design §4.4 *Repo facts*, TD-176), kept across a
        # restart in `repos.json`; the home's alone — a node reads none of this (§4.4a).
        self.repos_store = RepoStore()
        self._repos: dict[str, dict[str, Any]] = self.repos_store.load()
        self._repos_read_at = float("-inf")  # monotonic: the first tick reads
        self._repos_fresh = False  # `pr_wait --fresh` asked for the next tick's PR pass (TD-940)
        self._boards_read_at = float("-inf")  # monotonic: the boards' own clock, `BOARD_EVERY`
        # monotonic, by root: when a write-back last re-read that board (`_reread_board`), so a tick's
        # read that began before it does not put the board from before the press back
        self._boards_pressed: dict[str, float] = {}
        self._ledger_mtime: dict[str, tuple[str, float] | None] = {}  # `ledger.stamp` as last read
        self._repos_task: asyncio.Task[None] | None = None
        # the Queue's reading (§4.4 *The Queue*, TD-769): derived each tick at the home from the repo
        # readings, the claims and the archive (`_queue_pass`), served by `queue`, pushed when it changes
        self._queue: dict[str, Any] | None = None
        self._rank_init()  # the rank's intents and their flush (§4.4 *A move lands*, TD-769)
        self._shape_init()  # the teams' shape, sampled once a minute (§4.4 *Team shape*, TD-834)
        # The home's own `host` record (§6 *Balance*, TD-239): a team's balance mark, kept in `host.json`.
        self.host_store = HostStore()
        self._host_rec: dict[str, Any] = self.host_store.load()
        # the previous run's last tick, read before this run's first tick overwrites it: a pane found
        # gone on that first tick ended while nobody was looking (§4.5 row 5 (b), TD-490)
        self._prev_last_tick: str | None = self._host_rec.get("last_tick")
        self._ticked = False
        # rule 8 (§6, TD-227): (team, id) → when the home first read that id as new in a wound-down
        # team's lane; in memory, so a restart of the home starts the settle again
        self._work_first: dict[tuple[str, str], datetime] = {}
        self._question_ended = False  # rule 8: a lapse wrote a question's mark the sweep must push (TD-274)
        # rule 9 (§6, TD-241): team → when the home's reading of *finished* first held; in memory, and
        # dropped the tick it stops holding, so a restart of the home starts the settle again
        self._finished_first: dict[str, datetime] = {}
        # record address → whether it worked on its own at the last tick — a live subagent or a live
        # background shell (§4.2 *Working on its own*, TD-734, TD-766): a flip with no event behind it is
        # pushed by the tick
        self._subagents_were: dict[str, bool] = {}
        # team → that reading's first tick, where no manager is live to carry `finished_sent_at` and a
        # member was left open with work: the note to the person is owed until the last one is gone
        self._finished_owed: dict[str, datetime] = {}
        # The promote's readings per repo (design §6 *Promote*, TD-132): in memory, re-read at start —
        # what must survive a restart (a run in flight, a failure) is in its intent files.
        self._promotes: dict[str, dict[str, Any]] = {}
        # Until the first pass lands, a live check's `live` is unknown, not *not live* (TD-516).
        self._promotes_read = False
        self._sync_login: str | None = None  # the home's `gh` login, read once (§6 *Sync*, TD-685)
        self._sync_task: asyncio.Task[None] | None = None  # the sync pass, detached from the promote's
        self._sync_ran: dict[str, datetime] = {}  # root → the last pass that covered it whole
        self._ids_locks: dict[str, asyncio.Lock] = {}  # origin → the lock `td_next` gives its ids under (TD-696)
        # An attachment's upload in pieces (§4.4 *Attachment drop*, TD-478): its id → the session,
        # the `.part`, the name and the file's `total`. In memory: a restart drops it, and the hour's
        # sweep the `.part` it leaves.
        self._uploads: dict[str, dict[str, Any]] = {}
        self._promote_read_at = float("-inf")  # monotonic: the first tick reads
        self._promote_watch_at = float("-inf")
        self._promote_bad: dict[str, str] = {}
        self._promote_task: asyncio.Task[None] | None = None
        self._promote_lock = asyncio.Lock()
        self._setup_seen: object = None  # `profiles.yml`'s mtime the setup notes last read (§4.3, TD-875)
        self._setup_read_at = float("-inf")  # monotonic: the setup notes' last read
        self._pulls: dict[str, dict[str, Any]] = {}  # the pull's readings by repo (design §6 *Pull*)
        # per team, the last fifty `ao doing` calls and each doer's newest five (design §4.8 *the doing log*)
        self.doing_log = DoingLogStore()
        self._pre_limited: dict[str, State] = {}  # what a `limited` session was before the cap
        # Sessions removed recently: name → (the removed pane's tmux creation time, a monotonic
        # stamp for expiry). A pane snapshot taken before the remove must not re-adopt the pane it
        # still lists (the tick snapshots in a thread; remove runs between). Keyed by the pane's
        # own creation time, not by clocks compared across a thread hop, so a clock step cannot
        # re-adopt a dead pane and a hand-made session that reuses the name is adopted at once
        # (TD-020, TD-021). `None` for the creation time: the pane was already gone at remove.
        self._removed: dict[str, tuple[int | None, float]] = {}
        # Ids whose create is starting their tmux session in a thread: the pane exists before the
        # record does, and a tick between the two must not adopt it as a nameless shell — on a node
        # that adoption reaches the home first, which then refuses the real record as another
        # session (TD-952). The create's own record goes in on the loop, before its next await.
        self._starting: set[str] = set()
        self._pruned_at = datetime.min.replace(tzinfo=UTC)  # first tick sweeps
        self._oversize: set[str] = set()  # ids whose view is past the line limit, logged once each
        self._backed_up = ""  # the local date of the last nightly tarball tried (a home only)
        self._backup_task: asyncio.Task[None] | None = None

    # -- lifecycle ------------------------------------------------------------------------------

    async def serve(self, sock: Path | None = None) -> None:
        sock = sock or paths.socket_path()
        sock.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(FileNotFoundError):
            sock.unlink()
        self.tmux.ensure_server()
        await asyncio.to_thread(self._recover_reaps)  # a reap a promote cut off (§4.1, TD-979)
        # `limit`: a link's frame is one line, and a node's snapshot outgrows asyncio's 64 KiB default
        server = await asyncio.start_unix_server(self._handle_conn, sock=_bound(sock), limit=link.FRAME_LIMIT)
        log.info("listening on %s", sock)
        link_servers = await self._bind_links() if self.mode == "home" else []
        # Kept on the agent as well as locally: a test that must own the clock cancels it rather
        # than racing it with a sleep, which is the shape TD-078 and TD-088 keep catching. The
        # `finally` below cancels it either way — cancelling a cancelled task is a no-op.
        ticker = self._ticker = asyncio.create_task(self._tick_loop())
        dialer = asyncio.create_task(self._dial_home()) if self.mode == "node" else None
        try:
            async with server:
                # `start_unix_server` is already serving. Not `serve_forever()`: cancelled, it awaits
                # `wait_closed()` itself, which since Python 3.12 waits for every client connection
                # to end — and a subscriber or a blocked `wait` never does on its own, so a stop hung
                # until systemd's SIGKILL. Close them first, then let `async with` wait: a `wait`
                # sees the close, is cancelled and writes its cursor on the way out (TD-058).
                try:
                    await asyncio.get_running_loop().create_future()
                finally:
                    server.close()
                    for _, srv in link_servers:
                        srv.close()
                    for w in list(self._conns):
                        w.close()
        finally:
            ticker.cancel()
            if dialer is not None:
                dialer.cancel()
            for m in list(self._link_muxes.values()):
                m.close("the home is stopping")
            for name in list(self._supervising):
                self._stop_supervising(name)  # a build in flight is killed, not left to finish alone
            with contextlib.suppress(FileNotFoundError):
                sock.unlink()
            for lsock, _ in link_servers:
                with contextlib.suppress(FileNotFoundError):
                    lsock.unlink()

    async def _bind_links(self) -> list[tuple[Path, asyncio.AbstractServer]]:
        """The home's per-node link sockets (design §4.4a "A container node", TD-057 step 3c): one
        listener per `nodes:` entry at `links/<name>/link.sock`, speaking only the link protocol. A
        connection on it *is* that node — the name is the home's configuration, never the node's
        argv — so it enters `_serve_link` as sshd's forced command would, with no bridge between.
        Read once, here: a new node is a restart. The directory is `0700` and the socket `0600`,
        and a container node is handed the directory, which outlives the socket file (re-bound on
        every start of the home)."""
        out: list[tuple[Path, asyncio.AbstractServer]] = []
        for name in hosts.nodes():
            lsock = paths.link_socket(name)
            lsock.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(lsock.parent, 0o700)
            with contextlib.suppress(FileNotFoundError):
                lsock.unlink()

            async def take(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, name: str = name) -> None:
                self._conns.add(writer)
                try:
                    await self._serve_link({"host": name}, reader, writer)
                except (ConnectionError, asyncio.IncompleteReadError):
                    pass
                finally:
                    self._conns.discard(writer)
                    writer.close()

            srv = await asyncio.start_unix_server(take, sock=_bound(lsock), limit=link.FRAME_LIMIT)
            log.info("link socket for %s at %s", name, lsock)
            out.append((lsock, srv))
        return out

    async def _tick_loop(self) -> None:
        while True:
            try:
                await self.tick()
                await self._push_changes()
            except Exception:  # noqa: BLE001
                log.exception("tick failed")
            await asyncio.sleep(agent_common.TICK_SECONDS)

    # -- RPC methods -----------------------------------------------------------------------------

    async def rpc_list(self) -> list[dict[str, Any]]:
        return self._views()

    async def rpc_recent_dirs(self) -> list[str]:
        p = paths.recent_dirs_file()
        return p.read_text().splitlines() if p.is_file() else []

    async def rpc_repos(self, omit: list[str] | None = None) -> dict[str, dict[str, Any]]:
        """The repo facts per registered checkout (design §4.4 *Repo facts*, TD-176), keyed by the
        checkout's path: what the team card's Repo facet, the rollup and the Repo page draw, with
        `balance` beside a reading whose repo a team is over its line in (§6 *Balance*). `omit` is
        dotted paths each reading is served without (`reports.omitted`, TD-746): a page leaves out
        what it never draws. The home's; a node forwards it (§4.4a)."""
        views = {root: v for root in self._repos if (v := self._repo_view(root)) is not None}
        return {root: reports.omitted(v, omit) for root, v in views.items()} if omit else views

    PR_WAIT_STEP = 2.0  # seconds between looks at the reading: it lives in memory, so a look is free

    async def rpc_pr_wait(
        self, root: str, pr: int, timeout: float = 1800.0, fresh: bool = False, head: str | None = None
    ) -> dict[str, Any]:
        """`ao pr wait <n>` (design §4.7, TD-940): block until the home's reading of PR `pr` in the
        checkout `root` leaves *pending*, and return `{pr, word, checks, conflicting, failing, head,
        read_at, url}` — `word` one of `reports.PR_WAIT_EXIT`'s. The wake is the reading's refresh,
        so the latency is the tick's `REPOS_EVERY`; `fresh` makes the next tick's pass due and counts
        only a reading taken after the call. A number the reading does not hold is *gone* once a
        reading taken after the call still lacks it (a PR opened a minute ago is not yet in the one
        before), and at `timeout` the word is *timeout* with the last row; `read_error` is the last
        read's failure, if it failed. `head` (`want_head` in the reply; a sha or a prefix of one, TD-953)
        counts only a row of that commit: one of another head is *pending* whatever it says, so a reading
        of the commit before a push never answers for it. A read: it decides nothing on its caller, and
        the client names the root (`ao` sends its record's repo). Its connection
        is held as a `wait`'s is (`_serve_wait`), so a Ctrl-C ends it here too. The home's."""
        want = str(Path(root).resolve())
        key = next((r for r in self._repos if str(Path(r).resolve()) == want), None)
        if key is None:
            raise RpcError(f"the home holds no reading of {root}: it is not a checkout the repos registry lists")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(float(timeout), 0.0)
        began = datetime.now(UTC)
        want_head = str(head or "").strip().lower()
        if fresh:
            self._repos_fresh = True  # the next tick reads every repo's PRs, this one's among them
        line = (await asyncio.to_thread(self._precheck_line, key, int(pr)))[0]
        row: dict[str, Any] | None = None
        at = ""
        while True:
            prs = (self._repos.get(key) or {}).get("prs") or {}
            at = str(prs.get("at") or "")
            taken = reports._when(at)
            after = taken is not None and taken >= began
            got = next((p for p in prs.get("open") or [] if isinstance(p, dict) and p.get("number") == int(pr)), None)
            if got is not None:
                row = got
            other = reports.forge_of(str((self._repos.get(key) or {}).get("remote") or ""))[0] == "other"
            if prs.get("error") and not at and other:  # a forge with no reading, never read: nothing to wait on
                word = "gone"
                break
            if after or not fresh:
                if got is None and after:
                    word, row = "gone", None  # an earlier reading's row is not this one's
                    break
                ours = got is not None and str(got.get("head") or "").lower().startswith(want_head)
                if ours and (word := reports.pr_wait_word(got)) != "pending":
                    if word == "green" and line and got.get("prechecked") is False and not got.get("fork"):
                        word = "none"  # nothing else will check it (§4.7, TD-1036)
                    break
            if loop.time() >= deadline:
                word = "timeout"
                break
            await asyncio.sleep(min(self.PR_WAIT_STEP, max(deadline - loop.time(), 0.0)))
        row = row or {}
        fork = bool(row.get("fork"))
        return {
            "pr": int(pr),
            "word": word,
            "checks": row.get("checks"),
            "conflicting": bool(row.get("conflicting")),
            "failing": list(row.get("failing") or []),
            "head": row.get("head"),
            "want_head": want_head or None,  # the commit asked for, beside the one the reading is of
            "url": row.get("url"),
            "read_at": at or None,
            # the last read failed (`gh` offline, a lapsed token): the reading is the one before it
            "read_error": str(prs.get("error") or "") or None,
            # the line to run where the repo sets `precheck` and the head carries none (TD-1036)
            # never for a fork's PR, judged on the forge's CI alone: its precheck is the person's (TD-1285)
            "precheck": line if word == "none" and row.get("prechecked") is not True and not fork else None,
        }

    async def rpc_queue(self, omit: list[str] | None = None) -> dict[str, Any]:
        """The Queue's reading (design §4.4 *The Queue: cards, and the rank that orders them*, TD-769):
        the cards in rank order, In progress first, the completed cards and the other work, as
        `sessionorc.queue.reading` derives them, with the moves not yet landed applied (`_queue_ranked`);
        `omit` as the `repos` RPC takes it. The home's: a
        node, or a home before its first tick, serves an empty reading."""
        got = self._queue_ranked(self._queue or {"cards": [], "completed": [], "other_work": [], "at": None})
        return reports.omitted(got, omit) if omit else got

    async def rpc_doing_log(self, team: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """The doing log (design §4.8 *the doing log*, TD-176 slice 2): per team, its last fifty
        `ao doing` calls and each doer's newest five (TD-702), oldest first — `{team, id, text, at}`
        each; one team's with `team`. The home's; a node forwards it (§4.4a). A read, and not the
        `doing` RPC, which writes the line."""
        rings = self.doing_log.rings
        if team is not None:
            return {team: list(rings.get(team, []))}
        return {t: list(r) for t, r in rings.items()}

    async def rpc_adapters(self) -> list[str]:
        return adapters.names()

    async def rpc_ping(self) -> str:
        return "pong"

    async def rpc_host(self) -> dict[str, Any]:
        """Who this host agent is in the org (design §4.4a): its host, its home, its mode, and
        whether the home can be reached — which a client on a node needs before it labels what it
        shows *offline*; which build it runs and since when (§4.4, TD-062); and, at the home, the
        promote's readings per repo (`promotes`, §6 *Promote*, with `promotes_read` false until its
        first pass since start has read them), the pull's (`pulls`, §6 *Pull*) and
        each wound-down team's `work_waiting` as the `host` record holds it (`work: {<team>: mark}`,
        §6 rule 8), which is what draws the Inbox's team start row and the card's note; each team's
        balance mark (`balance: {<team>: mark}`, §6 *Balance*), every one, a mark with no `repo` included,
        which no checkout's `repos` reading carries (TD-330); and what
        each live session waits on (`waiting: {<sender>: [{id, ref, bound}]}`, `work.waiting_of`
        over the person inbox, §4.9a *Waiting is read, never declared*, TD-274) — references and
        bounds, never the questions' text — which a session's `ao team status` cannot read for
        itself, since nobody reads the person inbox but a person."""
        out = {"host": self.host, "home": self.home, "mode": self.mode, "home_reachable": self.home_reachable()}
        out["built_from"], out["started_at"] = dict(self.build), self.started_at
        if self.mode == "home":
            out["links"] = {h: dict(v) for h, v in sorted(self.links.items())}
            out["promotes"] = self._promotes_view()
            out["promotes_read"] = self._promotes_read  # False until the first pass reads the repos (TD-1032)
            out["pulls"] = self._pulls_view()
            out["waiting"] = work.waiting_of(self.person_inbox)
            out["notify"] = self._notify_view()
            out["ci_spells"] = self._ci_spells_view()  # the *CI not starting* rows' spells (§4.4, TD-687)
            out["work"] = {
                team: dict(rec["work_waiting"])
                for team, rec in sorted((self._host_rec.get("teams") or {}).items())
                if isinstance(rec, dict) and isinstance(rec.get("work_waiting"), dict)
            }
            out["balance"] = {
                team: dict(rec["balance"])
                for team, rec in sorted((self._host_rec.get("teams") or {}).items())
                if isinstance(rec, dict) and isinstance(rec.get("balance"), dict)
            }
        else:
            out["link"] = dict(self.home_link)
        return out

    async def rpc_get(self, id: str) -> dict[str, Any]:
        return self._view(self._find(id), bookkeeping=True)  # one record: its tallies and wakes ride along

    async def rpc_create(
        self,
        *,
        name: str,
        dir: str,
        adapter: str = "shell",
        profile: str = "",
        kind: str = "interactive",
        repo: str | None = None,
        worktree: str | None = None,
        argv: list[str] | None = None,
        unattended: bool = False,
        resume: str | None = None,
        prompt: str | None = None,
        prompt_from: dict[str, Any] | None = None,  # kept in the launch record only (§6 rule 7, TD-217)
        start_context: str | None = None,
        capabilities: list[str] | None = None,
        lane: list[str] | None = None,
        controllers: list[str] | None = None,
        role: str = "",
        ledger: str | None = None,
        team: str = "",
        project: str = "",
        run_until: str | None = None,
        wrapup_prompt: str | None = None,
        pause_prompt: str | None = None,
        resume_prompt: str | None = None,
        host: str | None = None,
        caller: str | None = None,
        keep_mail: bool = False,
        supervised: bool = False,
        run_only: bool | None = None,  # None, not False: a launch record keeps it only where it was set
        seat: dict[str, Any] | None = None,
        review: dict[str, Any] | None = None,
        context_bound: int | None = None,
        start_at: str | None = None,
        start_of: str | None = None,
        held: bool = False,
        team_start: bool = False,
        draft: str = "",
        succeeds: str | None = None,
    ) -> dict[str, Any]:
        """`draft` (design §4.4 *The Add entry form's draft*, TD-630): the Add entry form's draft
        folder, which **Open a session** hands to the create — claimed for the new session once it
        exists (`claimed.json` `{by: <its id>, at}`), so the folder then lives as that session's own
        attachments do. A person's own, as `attach` is; refused beside `start_at` or `held`, and
        before anything is made where the draft is not this host's, unclaimed.

        `team_start` marks a create that is part of `ao team start`: the dispatcher reads it at
        the home, before any routing, to keep the start's usage reading (`_mark_team_start`, §4.9a
        *The home's note says more*, TD-468); the create itself does nothing more with it.

        `succeeds` (design §4.9 *A member renamed or removed in the definition*, TD-706): a fresh start
        under a new name that **succeeds** the ended record `succeeds` names, across names — the replay
        of a renamed member, or a person's Start pairing a newcomer with its orphan. As a resume under
        another id does (§4.4a), the old record's mail moves to the new one and the old one records
        `superseded_by`; at the home its claims in progress and its `lane_seen` are copied over, every
        record's and every launch record's `controllers` naming the old address name the new one, and
        its launch record goes (`_carry`). Admitted as `keep_mail` is — the person, the home's own
        replay, or a controller of the old record — and refused beside `resume`, `keep_mail` or
        `start_of`, or when the old record is live, superseded, or holds this name already.

        `held` (design §6 rule 3 *A Start writes the seat and never fills it*, TD-410): a seat's record
        written alone, `closed` with no pane, so rule 3 fills it only for a cause — a manager on call at
        every Start, and a seat replayed by rule 8. Refused without `seat` and `unattended`, and beside
        `start_at` or a resume; with `keep_mail` the held record takes the mail as a fill does.

        `start_at` (design §6 *Start time*, TD-152): an instant ahead; the create makes the
        **record** now — the name taken, the worktree made, the launch record written, the slot held
        — in the state `scheduled`, with no pane, and the home's tick creates the session at the
        instant. Refused without `unattended`, in the past, and with a `run_until` not after it.
        `start_of` is that start: the tick's replay names the scheduled record it starts, which is
        then superseded in place, its mail kept, rather than refused as the live holder it is.

        `start_context` (design §4.3, TD-283): text the session holds from its start that is no
        prompt, handed to the adapter's `launch` — refused for an adapter that cannot carry one,
        never folded into the prompt — and kept on the record and the launch record. A resume that
        gives none carries the conversation's own, so every launch of it holds the same text.

        `review` (design §4.9b *The reader*, TD-093): the role preset's `{reader, held, bound}`,
        checked and kept on the record, read afterwards by the author's own `ao`. `context_bound`
        (design §4.8 *A role has a context bound*, TD-190): the preset's `context: {bound}` in tokens,
        kept on the record the same way.

        `supervised` (design §6 *Keeping a team running*, TD-103 slice 1): kept on the record,
        and a resume of a supervised record stays supervised whether or not it says so — the field
        is cleared by nothing but Forget. With it, the create writes the session's launch record
        (`_write_launch`), here unless this is a node, whose home writes it when it routes the create.
        `run_only` (§4.9 *A member started from the form*, TD-1164): kept on the record and in the launch
        record, so a replay of it is run-only too; `keep` clears both.

        `keep_mail` (design §4.9b, TD-075 step 4): a fresh start under a name moves the mail of
        the record it supersedes — inbox, outbox, tallies, wake decisions — as a resume does, and
        resumes nothing of its conversation. It is how a techlead seat is filled without forgetting
        the questions that caused the fill. Handing a record's mailbox to a successor is an act on
        that record, so it is open to a person and to the record's own controllers alone: a team's
        start under a closed member's name asks it (§4.10 *The name coming back adopts it*, TD-274)."""
        if host and host != self.host:
            # Routed before the method runs (`_act_host`) when this is the home; a node asked for
            # another host's create got here through the link, and the link is one host's.
            raise RpcError(f"{host} is not this host ({self.host}): a create lands on the host it names")
        directory = Path(dir).expanduser().resolve()
        if not directory.is_dir():
            raise RpcError(f"not a directory: {directory}")
        grants, references = _grants(capabilities or []), _lane(lane or [])  # validate before anything starts
        reading, bound = _review(review), _context_bound(context_bound)
        starts = _start_time(start_at, unattended, run_until)
        if held and (not (seat and unattended) or starts or resume):
            raise RpcError(
                "held writes a seat's record alone, closed, for rule 3 to fill: it takes a seat and unattended, "
                "and no start_at or resume (design §6 rule 3)"
            )
        # the scheduled record this create starts (the tick's replay, §6 *Start time*), if it is one
        starting = self.sessions.get(str(start_of)) if start_of else None
        if start_of and (starting is None or starting.state != "scheduled"):
            raise RpcError(f"{start_of} is not a scheduled record: nothing to start (design §6 Start time)")
        if (
            starting is not None
            and not mail.as_person(caller, self._graph())
            and self._addr(str(caller)) not in self._ctl(starting)
        ):
            # starting a scheduled record supersedes it and takes its mailbox: an act on that record,
            # open to a person and to its own controllers, as keep_mail's is (§4.9b, §9 invariant 11);
            # the tick's own start calls with no caller (techlead's read of #669)
            raise RpcError(
                f"{caller} is not a controller of {starting.id}: starting a scheduled record early is an act on it, "
                "open to a person and to its own controllers (design §6 Start time, §9 invariant 11)"
            )
        if seat is not None and not (
            isinstance(seat, dict) and isinstance(seat.get("trigger"), str) and seat["trigger"]
        ):
            raise RpcError("seat is {trigger, after?}: the trigger its team definition gives it (design §4.9b)")
        draft_dir: Path | None = None
        if draft:
            agent_common.person_only(caller, "claim a draft", "§4.4 *The Add entry form's draft*", self._graph())
            if starts or held:
                raise RpcError("a draft is claimed by a session started now: not beside start_at or held (design §4.4)")
            draft_dir = await asyncio.to_thread(agent_common.draft_folder, draft, "create")
        # Create adds the creator (design §4.8): a session that starts another may act on what it
        # started, without a second call and without a person in the loop. `caller` is the request
        # envelope's, injected by the dispatcher — a person's create has none, and then the new
        # session begins with only whatever `--controller` asked for (often nothing, which means
        # nobody may act on it: the explicit default). The person's own shell creates as the person
        # does (§4.8 *The person's own shell is the person*, TD-801): no creator in the child's list.
        members = [self._addr(c) for c in _controllers(controllers or [])]
        if caller and not mail.as_person(caller, self._graph()) and caller not in members:
            members.insert(0, str(caller))
        try:
            ad = adapters.get(adapter)
        except KeyError as e:
            raise RpcError(str(e).strip('"')) from None
        # A prompt no path can deliver is refused **here**, before anything is created (TD-068): an
        # adapter hands it to the tool as one argument, and the kernel refuses one past `ARG_LIMIT`.
        # `_fit` says the same thing at the tmux layer, but by then `create` has made a worktree
        # that no record points at — which is exactly what happened on 2026-09-18.
        # `+ 1` for the argument's NUL, exactly as `_fit` counts it: a prompt of *exactly*
        # `ARG_LIMIT` bytes passes a bare `>` here and is still refused there — after the worktree
        # (review of PR #272).
        if prompt and (size := len(str(prompt).encode("utf-8", "surrogateescape")) + 1) > ARG_LIMIT:
            raise RpcError(
                f"the prompt is {size - 1:,} bytes — past what a process can be started with ({ARG_LIMIT:,}): "
                "put a brief that long in a file and tell the session to read it (design §4.9, TD-068)"
            )
        start_context = (str(start_context).strip() or None) if start_context else None
        if start_context:
            if not getattr(ad, "start_context", False):
                raise RpcError(
                    f"the {adapter} adapter cannot carry a start context: give the text as a prompt, or start "
                    "a tool that holds one (design §4.3, TD-283)"
                )
            # one argument of its own, counted as the prompt is (TD-068)
            if (size := len(start_context.encode("utf-8", "surrogateescape")) + 1) > ARG_LIMIT:
                raise RpcError(
                    f"the start context is {size - 1:,} bytes — past what a process can be started with "
                    f"({ARG_LIMIT:,}): put text that long in a file and tell the session to read it "
                    "(design §4.3, TD-068)"
                )
        made = False  # whether this start created its worktree: the record's `worktree_made` (TD-979)
        if worktree:
            # Design §4.5 New session "new worktree": the checkout is the repo, the session runs in
            # `<repo>/.claude/worktrees/<name>` on branch <name>, created here if missing.
            repo_root = Path(repo).expanduser().resolve() if repo else directory
            # two creates of one name: the second reuses. Keyed by the main checkout as `worktree_path`
            # resolves it, as a close's reap keys it (§4.1 *A close reaps the worktree it made*, TD-979)
            try:
                main = await asyncio.to_thread(main_checkout, repo_root)
            except WorktreeError as e:
                raise RpcError(str(e)) from None
            wt_lock = self._dir_locks[f"worktree:{main}:{worktree}"]
            await wt_lock.acquire()
            try:
                directory, made = await asyncio.to_thread(ensure_worktree, repo_root, worktree, resume=bool(resume))
            except WorktreeError as e:
                wt_lock.release()
                raise RpcError(str(e)) from None
            except BaseException:
                wt_lock.release()
                raise
            repo = str(directory.parent.parent.parent)  # <repo>/.claude/worktrees/<name> → the main checkout
        else:
            wt_lock = None
        async with contextlib.AsyncExitStack() as locks:
            try:
                # the directory's lock is taken before the worktree's is let go, so a reap — which takes them
                # in the same order — never runs between `ensure_worktree` and the pane (TD-979)
                await locks.enter_async_context(self._dir_locks[str(directory)])
            finally:
                if wt_lock is not None:
                    wt_lock.release()
            # A name identifies one session per *scope* (§4.1), and a scope spans a repo's
            # worktrees — so the name check needs a lock on the scope, not just on this directory,
            # or two concurrent creates of one name from two worktrees would both pass it (review).
            await locks.enter_async_context(self._dir_locks[f"scope:{naming.scope_slug(directory, repo)}"])
            if resume:
                # one create per conversation at a time, whatever the directory: two concurrent
                # resumes of one id would otherwise both pass the holder check below (TD-012)
                await locks.enter_async_context(self._dir_locks[f"conversation:{resume}"])
            if kind == "interactive" and adapters.has_agent(adapter) and not held:
                for who in await asyncio.to_thread(self.occupants, directory):
                    if starting is not None and who.split(" ", 1)[0] == starting.id:
                        continue  # the scheduled record holds the slot for exactly this start
                    raise RpcError(f"{directory} already has agent session {who}; anchor rule (use a worktree)")
            # Design §4.1 / §9 invariant 12: a name identifies one session per scope. An unnamed
            # session is named here, not by its caller, so two of them never collide (TD-030).
            if not name.strip():
                name = await asyncio.to_thread(self._auto_name, directory, repo, adapter)
            # Refuse here; *take* the name below, once the launch has succeeded. Taking it kills a
            # pane, and a launch that then failed would have killed it for nothing (review).
            base_of = naming.base_id(directory, repo, name)
            if starting is not None and (starting.dir != str(directory) or not starting.id.startswith(base_of)):
                # the start is of that record, under its name and in its directory — never a way to
                # supersede some other scheduled record from elsewhere (§6 *Start time*)
                raise RpcError(f"{start_of} is scheduled as {starting.name} in {starting.dir}: start_of must name it")
            holder = starting if starting is not None else await self._name_holder(directory, repo, name)
            if isinstance(holder, Session):
                self._refuse_suspended(holder, caller, "a create under that name")
            succeeding = self._check_succeeds(succeeds, name, caller, resume, keep_mail, starting) if succeeds else None
            if keep_mail:
                self._check_keep_mail(holder, caller, resume)
            if resume:
                for gone in [r for r in self.sessions.values() if r.adapter_id == resume and r.suspended]:
                    self._refuse_suspended(gone, caller, "a resume of that conversation")
                    # a person got past that line, which **is** the lift (§4.8a) — and it lifts
                    # here rather than only in `_take_name`, because a resume under another name
                    # leaves this record standing, and a mark nothing can clear would hold its
                    # old name for ever (review of PR #301)
                    gone.suspended = None
                    self._save(gone)
                for who in await asyncio.to_thread(self.conversation_holders, resume):
                    raise RpcError(f"conversation {resume} is still live in {who}; kill it first, or Switch to it")
                if start_context is None:
                    # the conversation's own, whoever presses Resume (§4.3): the tool keeps it in no file
                    start_context = self._start_context_of(resume, holder)
            if starts:
                return await self._schedule(locals(), holder, directory, repo, name, starts)
            if held:
                if isinstance(holder, Session) and holder.state not in ("exited", "closed"):
                    # the name's record is running (or scheduled): the seat is there already, and a
                    # record written over it would take its name and kill its pane (review of TD-386)
                    raise RpcError(f"{holder.id} is {holder.state}: the seat is already there, nothing to write")
                return await self._schedule(locals(), holder, directory, repo, name, None, state="closed")
            try:
                spec = ad.launch(
                    profile=profile,
                    resume=resume,
                    prompt=prompt,
                    unattended=unattended,
                    cwd=directory,
                    name=name,
                    # the home's preface heads it, so every launch of such a tool has the file (§4.1, TD-347)
                    **(
                        {"start_context": mail.start_context_file_text(start_context)}
                        if getattr(ad, "start_context", False)
                        else {}
                    ),
                )
            except (KeyError, ValueError, OSError) as e:  # OSError: the start context's file (TD-339)
                raise RpcError(str(e).strip('"')) from None
            if argv:
                spec.argv = argv
            if isinstance(holder, Session) and resume and holder.adapter_id == resume:
                # its row ended because the person opened it, which is the word the trail wants —
                # `_take_name` would otherwise write the ending of a record merely replaced (§4.10)
                self._attention_ended(holder.id, "resumed", "*")
            previous_run, freed = await self._take_name(holder)
            model_env = await asyncio.to_thread(agent_common.model_env, adapter, spec.model, directory)
            # read after the supersede, so the id it freed is not `taken` and gets reused
            live = await asyncio.to_thread(lambda: [p.session for p in self.tmux.list_panes()])
            # Records can no longer hold the base id: `_claim_name` refused or superseded the one
            # session of this name in scope. What is left is a tmux session nobody has a record of
            # — and then the suffix is part of the name the Org shows (TD-030 step 2).
            taken = (set(self.sessions) | set(live)) - ({freed} if freed else set())
            base = naming.base_id(directory, repo, name)
            for _attempt in range(5):
                sid = naming.session_id(directory, repo, name, taken)
                # Ours win, whatever an adapter sets. SHIFTLEAD_HOME is explicit because the tmux
                # server may predate this agent and carry a different environment; a hook script
                # inside the session must find *this* agent's socket (found the hard way, 2026-09-06).
                # AGENT_NAME is the name the Org shows, for whatever in the session signs its work —
                # agent-cadence's commit hook writes it as a co-author (TD-185). Tool-neutral: every
                # adapter's session gets it, and a blank name was given its automatic one above.
                # CADENCE_ATTENTION_SCOPE tells agent-cadence's start hook whose board to nudge from —
                # its own for an unattended session, the machine's for one a person drives — so the
                # synced script never asks `ao status` (design §4.3, §8, TD-425). AGENT_MODEL and
                # AGENT_MODEL_FILE name the model for its `Agent-Model:` trailer (§4.2, TD-638).
                shown = name if sid == base else name + sid[len(base) :]  # a shown suffix, never a hidden one
                env = {
                    **spec.env,
                    "SHIFTLEAD_SESSION": sid,
                    "SHIFTLEAD_HOME": str(paths.home()),
                    "AGENT_NAME": shown,
                    "CADENCE_ATTENTION_SCOPE": "own" if unattended else "machine",
                    **model_env,
                }
                run_log = paths.runs_dir() / f"{sid}-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.log"
                self._starting.add(sid)
                try:
                    await asyncio.to_thread(self._start, sid, directory, spec.argv, env, run_log)
                    break
                except DuplicateSession:
                    taken.add(sid)  # design §4.1: handle tmux's own verdict, not just our check
                finally:
                    self._starting.discard(sid)  # nothing awaits between here and `self.sessions[sid] = s`
            else:
                raise RpcError(f"could not find a free session name for {name!r} in {directory}")
            s = Session(
                id=sid,
                name=shown,
                kind=kind,  # type: ignore[arg-type]
                adapter=adapter,
                dir=str(directory),
                profile=profile,
                repo=repo,
                worktree=worktree,
                unattended=unattended,
                confidence=ad.state_source,
                run_log=str(run_log),
                adapter_id=spec.adapter_id,
                capabilities=grants,
                controllers=members,
                lane=references,
                role=str(role or ""),
                ledger=(str(ledger).strip() or None) if ledger else None,
                team=str(team or ""),  # badges (§4.9): stored as given, never validated here
                project=str(project or ""),
                run_until=self._team_stamp(str(team or ""), bool(unattended), _stop_time(run_until)),
                wrapup_prompt=(str(wrapup_prompt).strip() or None) if wrapup_prompt else None,
                pause_prompt=(str(pause_prompt).strip() or None) if pause_prompt else None,
                resume_prompt=(str(resume_prompt).strip() or None) if resume_prompt else None,
                previous_run=previous_run,
                host=self.host,
                # a resume carries it — of the name's record or the conversation's (§6: Forget alone clears it)
                supervised=bool(supervised)
                or bool(resume and isinstance(holder, Session) and holder.adapter_id == resume and holder.supervised)
                or any(r.supervised for r in self.sessions.values() if resume and r.adapter_id == resume),
                run_only=bool(run_only),
                seat=dict(seat) if seat else None,
                review=reading,
                context_bound=bound,
                start_context=start_context,
                first_prompt=spec.first_prompt or None,
                model_file=model_env.get("AGENT_MODEL_FILE"),
            )
            if self.mode != "node":
                # started by hand (§4.10 *between the person's own sessions*, TD-1069): derived here and
                # never passed — `supervised` and `seat` as the record is written, the caller as every
                # caller is read. A node's is the home's, set on its copy from this create's reply.
                s.by_person = mail.as_person(caller, self._graph()) and not s.supervised and not s.seat
            if isinstance(holder, Session):
                # the record of this name it replaced, for the home, which holds the mail (§4.4a)
                kept = bool(keep_mail or starting is not None or (resume and holder.adapter_id == resume))
                s.supersedes = [{"id": holder.id, "mail": kept, "at": s.created}]
            s.worktree_made = made or _inherits_made(s, holder)
            self.sessions[sid] = s
            self.store.save(s)
            if draft_dir is not None:  # the form's files are the new session's from here (§4.4, TD-630)
                try:
                    await asyncio.to_thread(agent_common.claim_draft, draft_dir, s.id, datetime.now(UTC))
                except (OSError, RpcError) as e:  # the session exists: its create stands, the draft unclaimed
                    log.warning("create %s: could not claim %s: %s", s.id, draft_dir.name, e)
            if isinstance(holder, Session) and holder.adapter_id != s.adapter_id:
                self._drop_context(holder.adapter_id, holder)  # replaced in place, never forgotten
            self._remember_dir(directory)
            if resume:
                await self._supersede(resume, sid, replaced=holder if isinstance(holder, Session) else None)
            elif (keep_mail or starting is not None) and isinstance(holder, Session):
                # the seat's mail, to the seat's next holder (§4.9b); a scheduled record's, to the
                # session it becomes (§6 *Start time*): mail sent to it before the instant is its own
                self._move_mail(holder, s)
                self.store.save(s)
            if succeeding is not None:
                self._succeed(succeeding, s)
            self._adopt_orphans(self._address(s))  # its name's orphaned questions are its own again (§4.10)
            if self.mode != "node":
                if prompt_from:  # what the prompt was made from, as this create's client read it (§6 rule 7)
                    s.brief = await asyncio.to_thread(brief.record, prompt_from, False)
                    self.store.save(s)
                if s.supervised:
                    self._write_launch(s.id, s, launch_params(locals()))
                else:
                    self._drop_launch(s.id)  # a fresh start that took a supervised record's id is not it
                if succeeding is not None:  # the launch record moves to the new id: dropped once that is written
                    self._drop_launch(self._address(succeeding))
        return s.view()

    async def _schedule(
        self,
        given: dict[str, Any],
        holder: Session | str | None,
        directory: Path,
        repo: str | None,
        name: str,
        starts: str | None,
        state: str = "scheduled",
    ) -> dict[str, Any]:
        """A create with `start_at` (design §6 *Start time*, TD-152): the record now, in the state
        `scheduled` — the name taken under §4.1's rule, the worktree already made, the launch record
        written (the one the tick replays at the instant), the directory's slot held by being a
        record that is neither exited nor closed — and no pane, no run log, no conversation yet.
        Called from `create` under its locks, with `given` its own arguments as they stand. With
        `state="closed"` it is a `held` seat's record (§6 rule 3, TD-410): the same record, holding no
        slot, whose `lane_seen` is empty so everything in its lane is the first fill's."""
        if given.get("resume"):
            raise RpcError("start_at is a fresh start: a resume runs now or not at all (design §6 Start time)")
        previous_run, freed = await self._take_name(holder)
        live = await asyncio.to_thread(lambda: [p.session for p in self.tmux.list_panes()])
        taken = (set(self.sessions) | set(live)) - ({freed} if freed else set())
        base = naming.base_id(directory, repo, name)
        sid = naming.session_id(directory, repo, name, taken)
        team = str(given.get("team") or "")
        s = Session(
            id=sid,
            name=name if sid == base else name + sid[len(base) :],
            kind=given["kind"],
            adapter=given["adapter"],
            dir=str(directory),
            profile=given["profile"],
            repo=repo,
            worktree=given["worktree"],
            unattended=True,
            capabilities=given["grants"],
            controllers=given["members"],
            lane=given["references"],
            role=str(given.get("role") or ""),
            ledger=(str(given["ledger"]).strip() or None) if given.get("ledger") else None,
            team=team,
            project=str(given.get("project") or ""),
            run_until=self._team_stamp(team, True, _stop_time(given.get("run_until"))),
            wrapup_prompt=(str(given["wrapup_prompt"]).strip() or None) if given.get("wrapup_prompt") else None,
            pause_prompt=(str(given["pause_prompt"]).strip() or None) if given.get("pause_prompt") else None,
            resume_prompt=(str(given["resume_prompt"]).strip() or None) if given.get("resume_prompt") else None,
            previous_run=previous_run,
            host=self.host,
            supervised=True,  # it is started by the tick's replay, as any supervised record is restarted
            by_person=None if self.mode == "node" else False,  # supervised: a team's (§4.10, TD-1069)
            seat=dict(given["seat"]) if given.get("seat") else None,
            review=given["reading"],
            context_bound=given["bound"],
            start_context=given.get("start_context"),
            start_at=starts,
        )
        s.set_state(state, confidence="hook")  # type: ignore[arg-type]
        if state == "closed":
            s.closed_at = s.created
            s.closer = {"by": "start", "why": "held"}
            s.lane_seen = {"at": s.created, "ids": []}
        # a held seat's record keeps the mail as its fill would (§6 rule 3, TD-410): a question to the
        # last run's manager is in its inbox, so the first tick reads it as due and fills the seat
        kept = state == "closed" and bool(given.get("keep_mail")) and isinstance(holder, Session)
        if isinstance(holder, Session):
            s.supersedes = [{"id": holder.id, "mail": kept, "at": s.created}]
        s.worktree_made = bool(given.get("made")) or _inherits_made(s, holder)
        self.sessions[sid] = s
        if kept:
            self._move_mail(holder, s)
        if given.get("succeeding") is not None:  # a held seat renamed: the record rule 3 fills is the new name's
            self._succeed(given["succeeding"], s)
        self.store.save(s)
        self._remember_dir(directory)
        if self.mode != "node":
            self._write_launch(s.id, s, launch_params(given))
            if given.get("succeeding") is not None:
                self._drop_launch(self._address(given["succeeding"]))
        if starts:
            log.info("%s scheduled to start at %s", sid, starts)
        else:
            log.info("%s written %s with no pane: rule 3 fills it", sid, state)
        return s.view()

    def _start_context_of(self, resume: str, holder: Session | str | None) -> str | None:
        """The start context a resume of conversation `resume` carries when its create gave none
        (design §4.3, TD-283): the record of this name's, when it holds that conversation, else the
        newest record that does — a Resume under another name is still the same conversation."""
        if isinstance(holder, Session) and holder.adapter_id == resume and holder.start_context:
            return holder.start_context
        held = [r for r in self.sessions.values() if r.adapter_id == resume and r.start_context]
        return max(held, key=lambda r: r.created).start_context if held else None

    def _check_keep_mail(self, holder: Session | str | None, caller: Any, resume: str | None) -> None:
        """`create(keep_mail=true)` is refused, naming the rule, unless it has a record to keep the
        mail of and the caller may hand that record's mailbox on (design §4.9b)."""
        if resume:
            raise RpcError("a resume carries its mail already: --keep-mail is for a fresh start (design §4.9b)")
        if not isinstance(holder, Session):
            raise RpcError(
                "--keep-mail keeps the mail of the record this name held, and no record holds it (design §4.9b)"
            )
        if not mail.as_person(caller, self._graph()) and self._addr(str(caller)) not in self._ctl(holder):
            raise RpcError(
                f"{caller} is not a controller of {holder.id}: handing a record's mailbox to a successor is an act "
                "on that record, open to a person and to its own controllers (design §4.9b, §9 invariant 11)"
            )

    def _check_succeeds(
        self, succeeds: str, name: str, caller: Any, resume: str | None, keep_mail: bool, starting: Session | None
    ) -> Session:
        """`create(succeeds=<old id>)`'s refusals, each naming the rule (design §4.9 *A member renamed or
        removed in the definition*, TD-706), and the record it succeeds when none applies."""
        rule = "(design §4.9 A member renamed or removed in the definition)"
        if resume or keep_mail or starting is not None:
            raise RpcError(
                f"succeeds is a fresh start under a new name: not beside resume, keep_mail or start_of {rule}"
            )
        old = self.sessions.get(str(succeeds))
        if old is None:
            raise RpcError(f"no record {succeeds} on {self.host} to succeed {rule}")
        if old.superseded_by:
            raise RpcError(f"{old.name} was succeeded already, by {old.superseded_by} {rule}")
        if old.state not in ("exited", "closed"):
            raise RpcError(f"{old.name} is {old.state}: a record is succeeded once it has ended {rule}")
        if old.name == name:
            raise RpcError(
                f"{old.name} holds this name already: keep_mail is how a start under it keeps the mail {rule}"
            )
        self._refuse_suspended(old, caller, "a create that succeeds it")
        if not mail.as_person(caller, self._graph()) and self._addr(str(caller)) not in self._ctl(old):
            raise RpcError(
                f"{caller} is not a controller of {old.id}: succeeding a record takes its mailbox, an act on that "
                "record, open to a person and to its own controllers (design §4.9b, §9 invariant 11)"
            )
        return old

    def _succeed(self, old: Session, new: Session) -> None:
        """A create under a new name succeeding `old` (design §4.9, TD-706): the old record's mail moves
        to the new one and the old one records `superseded_by`, as a resume under another id does
        (§4.4a) — an exited one is closed, its dead pane dropped — and, at the home, the rest of the
        carry (`_carry`). A node keeps the move on its own records; the home moves the mail it holds
        when the node reports the supersession (`_take_supersession`) and carries the rest at its replay."""
        if old.state == "exited":
            with contextlib.suppress(Exception):
                self.tmux.kill_session(old.id)
            old.set_state("closed", confidence=old.confidence)
            old.closed_at = now_iso()
        new.supersedes = [*new.supersedes, {"id": old.id, "mail": True, "at": new.created}]
        new.worktree_made = bool(new.worktree_made) or _inherits_made(new, old)
        self._move_mail(old, new)
        old.superseded_by = self._address(new)
        if self.mode != "node":
            self._carry(old, new)
        self._save(old)
        self._save(new)
        log.info("%s succeeds %s across names", self._address(new), self._address(old))

    def _carry(self, old: Session, new: Session) -> None:
        """The home's half of a succession across names (design §4.9, TD-706): `old`'s claims in progress
        and its `lane_seen` copied onto `new`, so the lease and rule 6's memory hold across the name;
        every record of this host and every launch record whose `controllers` name the old address name
        the new one, so a renamed lead is still each member's controller (a node's own records take
        theirs at their node, routed by `_carry_controllers` from the rewritten launch record, TD-712).
        `old`'s launch record is the caller's to drop, once `new`'s is written (`_drop_launch`). Saves
        what it touched but `old` and `new`, which the caller saves."""
        a, b = self._address(old), self._address(new)
        old.superseded_by = b
        held = {e.ref for e in new.progress}
        new.progress = [
            *new.progress,
            *(copy.deepcopy(e) for e in old.progress if e.status == "claimed" and e.ref not in held),
        ]
        if old.lane_seen is not None:
            new.lane_seen = copy.deepcopy(old.lane_seen)
        for r in self.sessions.values():
            if r is not old and a in r.controllers:
                r.controllers = list(dict.fromkeys(b if c == a else c for c in r.controllers))
                if r is not new:
                    self._save(r)
        for path in sorted(paths.launch_dir().glob("*.json")):
            with contextlib.suppress(OSError, ValueError):
                record = json.loads(path.read_text(encoding="utf-8"))
                rid, host = naming.split_address(path.stem)
                ctl = record.get("controllers") if isinstance(record, dict) else None
                was, now = (a, b) if not host or host == self.host else (self._to_host(a, host), self._to_host(b, host))
                if not isinstance(ctl, list) or was not in ctl:
                    continue
                record["controllers"] = list(dict.fromkeys(now if c == was else c for c in ctl))
                tmp = path.with_suffix(".json.tmp")
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(record, f, indent=1)
                tmp.replace(path)

    async def rpc_name_check(
        self, dir: str, name: str, repo: str | None = None, host: str | None = None
    ) -> dict[str, Any]:
        """What §4.1's name rule would do to this name, without doing it: the New session form's
        check as you type, and the note `ao new` prints (design §4.5a, TD-030 step 4)."""
        if host and host != self.host:
            raise RpcError(f"{host} is not this host ({self.host}): a name is checked on the host it would run on")
        verdict, _ = await self._name_verdict(Path(dir).expanduser(), repo, name)
        return verdict

    async def _name_verdict(
        self, directory: Path, repo: str | None, name: str
    ) -> tuple[dict[str, Any], Session | str | None]:
        """The one place §4.1's rule is decided, so the form, the CLI and `create` never drift:
        `(what it would do, what it would have to supersede)`. `verdict` is `free`, `live` (a
        holder that is running) or `supersede`, with the text both surfaces show."""
        base = naming.base_id(directory, repo, name)
        out: dict[str, Any] = {"id": base, "name": name, "verdict": "free", "holder": None, "message": ""}
        if not name.strip():
            return out, None
        holder = self.sessions.get(base)
        if holder is None:
            # No record, but tmux may still hold the id (a hand-made session the tick has not
            # adopted yet, or a pane whose record was lost). Decide on tmux's own answer rather
            # than on when the next tick runs, or the same `ao new` would refuse or suffix
            # depending on the second it landed in (design §4.1).
            pane = (await asyncio.to_thread(self.tmux.main_panes, naming.PREFIX)).get(base)
            if pane is None:
                return out, None
            if not pane.dead:
                out |= {
                    "verdict": "live",
                    "holder": base,
                    "holder_state": "unrecorded",
                    "message": f"{name} is running outside shiftlead — its card appears within a tick",
                    "hint": f"switch to it with: ao focus {base}",
                }
                return out, None
            out |= {"verdict": "supersede", "holder": base, "holder_state": "unrecorded"}
            out["message"] = f"replaces a leftover tmux pane called {name} — it has no record and no log"
            return out, base  # a dead pane nobody has a record of: nothing to keep from it
        if holder.state not in ("exited", "closed"):
            out |= {
                "verdict": "live",
                "holder": holder.id,
                "holder_state": holder.state,
                "message": f"{name} is running — switch to it, or pick another name",
                "hint": f"switch to it with: ao focus {holder.id}",
            }
            return out, None
        if holder.suspended:
            # §4.8a *An alarm's answers*, TD-077 a2: **the one exception to §4.1's rule that an
            # exited holder is superseded**. A verdict of its own rather than `supersede`, so the
            # form, `ao new` and `ao team start` all refuse without each knowing the rule — which
            # is what this function exists for. A person still may: `create` reads the caller, and
            # their own resume is one of the two things that lift it (the other is Forget).
            out |= {
                "verdict": "suspended",
                "holder": holder.id,
                "holder_state": holder.state,
                "message": (
                    f"{name} was suspended by a person at {holder.suspended.get('at')} over an identity alarm "
                    f"({holder.suspended.get('why') or 'no reason recorded'}) — no session may take that name; "
                    "a person lifts it by resuming it themselves or forgetting it"
                ),
                "hint": f"look at it first: ao tail {holder.id}",
            }
            # the holder is returned all the same: a **person** may take this name, and `create`
            # is where the caller is known — `_refuse_suspended` refuses a session there, and a
            # person's create supersedes the record in place, which is what lifts the mark
            return out, holder
        out |= {
            "verdict": "supersede",
            "holder": holder.id,
            "holder_state": holder.state,
            "message": f"replaces the {holder.state} {name} — run log kept",
        }
        return out, holder

    def _refuse_suspended(self, s: Session, caller: Any, road: str) -> None:
        """A suspended record is not brought back by a session (design §4.8a *An alarm's answers*,
        TD-077 a2). Both roads are closed — `create` under its name, and `create --resume` of its
        conversation — which is **the one exception to §4.1's rule that an exited holder is
        superseded**, and §4.1 says so. A **person** walks either road freely: their own resume is
        one of the two things that lift a suspension, the other being Forget."""
        if not s.suspended or mail.as_person(caller, self._graph()):
            return
        mark = s.suspended
        raise RpcError(
            f"{s.name} was suspended by a person at {mark.get('at')} over an identity alarm "
            f"({mark.get('why') or 'no reason recorded'}): {road} is refused to every session, and only a "
            f"person lifts it — by resuming it themselves or forgetting it (design §4.8a)"
        )

    async def _name_holder(self, directory: Path, repo: str | None, name: str) -> Session | str | None:
        """Raises for a **live** holder; otherwise returns what a new session would supersede — the
        exited or closed record, or the id of a dead pane nobody has a record of — or None when the
        name is free. Nothing is destroyed here: `_take_name` does that once the launch has
        succeeded (TD-030)."""
        verdict, holder = await self._name_verdict(directory, repo, name)
        if verdict["verdict"] == "live":
            raise RpcError(
                verdict["message"],
                holder=verdict["holder"],
                holder_state=verdict["holder_state"],
                hint=verdict["hint"],
            )
        return holder

    async def _take_name(self, holder: Session | str | None) -> tuple[str | None, str | None]:
        """Supersede what `_name_holder` found, returning `(previous_run, the id it freed)`. The
        dead pane is killed and the record's run log handed on; the record itself is **replaced in
        place** by the new one under the same id — not forgotten — so the Org's card becomes the
        new session rather than going and coming back, and a launch that fails after this point
        leaves the old record standing instead of losing it (review 2026-09-11)."""
        if holder is None:
            return None, None
        if isinstance(holder, str):
            await asyncio.to_thread(self.tmux.kill_session, holder)
            return None, holder
        await asyncio.to_thread(self.tmux.kill_session, holder.id)  # a dead pane, if it still has one
        self._id_pane_replaced(holder.id)  # the new run's first hook waits for a fresh list (TD-341)
        # The replaced record's rows end here, with the record: it is gone from the graph, and the
        # new session under its id must not inherit what it was showing (review of PR #269).
        self._attention_gone(holder, "forgotten")
        self._scrub(holder.id)  # the side tables are about the old session, not the new one
        log.info("%s superseded the %s session of the same name", holder.name, holder.state)
        return holder.run_log, holder.id

    def _auto_name(self, directory: Path, repo: str | None, adapter: str) -> str:
        """`shell`, `shell-2`, … for a session started without a name (TD-030 step 3): the agent
        picks it, so the name it is shown under is the name it holds. Runs in a thread: tmux."""
        stem = "shell" if adapter == "shell" else adapter
        live = {p.session for p in self.tmux.list_panes()}
        for n in range(1, 100):
            candidate = stem if n == 1 else f"{stem}-{n}"
            if naming.base_id(directory, repo, candidate) not in (set(self.sessions) | live):
                return candidate
        return f"{stem}-{now_iso()}"

    async def _supersede(self, adapter_id: str, new_sid: str, replaced: Session | None = None) -> None:
        """A resumed conversation continues in the new session: the exited record it came from is
        closed (kept a day, sorted last) and its dead pane dropped, so the Org shows one card.

        **Resume carries mail forward** (design §4.10 lifecycle): every entry still inside the
        retention window, read or unread, the exchange tallies and `sends` move to the new record,
        because the conversation they were addressed to is the one continuing — a worker that read
        an `ask`, crashed and was resumed must not lose the thread it was answering. Ids follow the
        move: the old id is rewritten to the new one in the moved entries' `to`, and in every other
        record's pair tallies and pending-`ask` addressees; an `ask` left pending by the exit is
        open again. The old record remembers its successor, so a message addressed to it is
        forwarded there (`rpc_msg`) while an act on it is refused, as on any closed record.

        **A resume under the same name** has no such old record to find: §4.1's name rule replaced
        it **in place, at the same id** (`_take_name`), so the loop below — which looks for a
        *different*, `exited` record — finds nothing and the conversation's mail would be dropped
        by the very path that exists to carry it. `replaced` is what the name rule superseded, and
        when it is the record this resume continues (the same conversation, at the id the new
        session now holds) its mail moves from it (TD-081). Nothing is closed or forwarded in that
        case: there is one record and one id, and the successor *is* the record."""
        new = self.sessions.get(new_sid)
        for other in list(self.sessions.values()):
            if other.id != new_sid and other.adapter_id == adapter_id and other.state == "exited":
                await asyncio.to_thread(self.tmux.kill_session, other.id)
                other.set_state("closed", confidence=other.confidence)
                other.closed_at = now_iso()
                other.superseded_by = new_sid
                if new is not None:
                    self._move_mail(other, new)
                    new.supersedes.append({"id": other.id, "mail": True, "at": new.created})
                    new.worktree_made = bool(new.worktree_made) or _inherits_made(new, other)
                self.store.save(other)
        if replaced is not None and new is not None and replaced.id == new_sid and replaced.adapter_id == adapter_id:
            self._move_mail(replaced, new)
        if new is not None:
            self.store.save(new)

    def _move_mail(self, old: Session, new: Session) -> None:
        # The row the old record was showing ends here, and the trail says *resumed* — which is
        # what Paul saw vanish: opening a row's session resumed it (design §4.10, TD-079). **Only
        # when there are two ids**: under the same name the ending was marked in `rpc_create`,
        # before the name was taken, and marking it again here would leave the word on the id the
        # **live** record now holds — where `*` stands until the record goes, so its next, unrelated
        # ending would wear *resumed* with nothing resumed (review of PR #282).
        #
        # Ids are **addresses** here (`_address`): the same thing on this host's records, and
        # `id@host` on a node's records at the home, which moves their mail when a node reports
        # the supersession (`_take_supersession`, TD-057).
        a, b = self._address(old), self._address(new)
        if a != b:
            self._attention_ended(a, "resumed", "*")
        now = datetime.now(UTC)
        new.inbox = self._rename([self._copy(e) for e in old.inbox if self._keep(e, now, inbox=True)], a, b)
        new.outbox = self._rename([self._copy(e) for e in old.outbox if self._keep(e, now, inbox=False)], a, b)
        new.threads = {k.replace(f"pair:{a}", f"pair:{b}"): t for k, t in old.threads.items()}
        new.sends = list(old.sends)
        # the wake decisions follow the conversation too, so moved mail a wake already covered is
        # not decided (and charged) a second time, and a spent budget is not reset by a resume
        new.mail_decided, new.wakes, new.wake_refilled_at = old.mail_decided, list(old.wakes), old.wake_refilled_at
        old.inbox, old.outbox, old.threads, old.sends = [], [], {}, []
        # **The person inbox's copies follow the move too** (§4.10 "Ids follow the move"; review of
        # PR #245). An `ask` to the person does not expire, so a question the old id put there can
        # outlive the record that sent it — and its `from` is load-bearing in four places: the
        # per-sender depth, the advice line, where a `system` note about it is delivered, and where
        # the person's Reply is addressed. Left naming the old id, the question would be closed
        # `asker_gone` when the superseded record is forgotten a day later, although the
        # conversation it belongs to is still running.
        moved = [e for e in self.person_inbox if e.from_ == a]
        for e in moved:
            e.from_ = b
        if moved:
            self.person_store.save(self.person_inbox)
        for r in self._graph().values():
            if r is old or r is new:
                continue
            # the mailbox is addressed as this host reads it, on every record (`_msg` lands entries
            # by graph address) — only `controllers` are kept in a node's own form
            touched = False
            if f"pair:{a}" in r.threads:
                r.threads[f"pair:{b}"] = r.threads.pop(f"pair:{a}")
                touched = True
            pending = [e for e in (*r.inbox, *r.outbox) if a in e.pending]
            if pending:  # the addressee that exited is back: its ask is open again, addressed to it
                self._rename(pending, a, b)
                touched = True
            if touched:
                self._save(r)

    @staticmethod
    def _rename(entries: list[MailEntry], old: str, new: str) -> list[MailEntry]:
        """The old id rewritten to the new one in entries the resume carries. `from_` too, on the
        copies this record owns — its **outbox**, where `from_` is this conversation and the home
        reads it to deliver a `system` note about the entry (review of PR #245). A delivered copy
        in someone else's inbox is never passed here and keeps `from` as it was (§4.10)."""
        for e in entries:
            e.to = [new if x == old else x for x in e.to]
            e.copies = [new if x == old else x for x in e.copies]
            e.pending = [x for x in e.pending if x != old]
            if e.from_ == old:
                e.from_ = new
        return entries

    def occupants(self, directory: Path) -> list[str]:
        """Who holds the agent slot for `directory` (design §9 invariant 2): shiftlead's own live
        agent sessions, plus live sessions the adapters can see that shiftlead did not start
        (a VS Code terminal running `claude` in the checkout, say). Shells never count."""
        directory = Path(directory).resolve()
        # Runs in a thread while the loop goes on writing these maps in place: iterate copies, taken
        # in one step, never the live dicts (review of PR #215).
        mine = list(self.sessions.values())
        ours = {s.adapter_id for s in mine if s.adapter_id}

        def holds(s: Session) -> bool:
            return (
                s.kind == "interactive"
                and adapters.has_agent(s.adapter)
                and s.state not in ("exited", "closed")
                and Path(s.dir).resolve() == directory
            )

        out = [f"{s.id} ({s.state})" for s in mine if holds(s)]
        # A container node on this machine has the checkout mounted at the same path (design §4.4a
        # "A container node", 3c.4): a record of its over this directory holds the slot too — read
        # from what the node reports, derived from the `container:` entry, never configured — while
        # its link is up. Down, the container is a blip away from dialing back (its records are
        # then repaired by the snapshot) or stopped, and a stopped container's sessions are dead:
        # neither may hold this checkout against a create here. A machine node's `/home/x/repo`
        # is another directory, and is not read.
        if self.mode == "home" and self.remote:
            for host in containers.container_nodes():
                if not (self.links.get(host) or {}).get("up"):
                    continue
                out += [f"{s.id}@{host} ({s.state})" for s in list(self.remote.get(host, {}).values()) if holds(s)]
        for ext in adapters.external_sessions()["items"]:
            if ext.tool_id and ext.tool_id in ours:
                continue  # that is one of ours, seen through the tool's registry
            if Path(ext.cwd).resolve() == directory:
                out.append(f"{ext.name} ({ext.adapter}, outside shiftlead{', ' + ext.status if ext.status else ''})")
        return out

    def pull_occupant(self, directory: Path) -> str | None:
        """The first session in `directory` not at rest, for the pull (design §6 *Pull* (2)): None
        when every one there is at rest or there is none; its name when one is mid-turn; `""` when
        one's state cannot be read, which the pull takes as mid-turn. Unlike `occupants` it counts
        shells (a foreground command may be `git` itself) and reads each record's state: `idle`,
        `exited` and `closed` are at rest, everything else may be a turn under way or about to
        resume. A session outside shiftlead is at rest only when its tool's registry says `idle`."""
        directory = Path(directory).resolve()
        rest = ("idle", "exited", "closed")
        mine = list(self.sessions.values())  # a copy taken in one step: this runs in a thread
        ours = {s.adapter_id for s in mine if s.adapter_id}
        records = [s for s in mine if Path(s.dir).resolve() == directory]
        if self.mode == "home" and self.remote:
            for host in containers.container_nodes():
                if (self.links.get(host) or {}).get("up"):
                    records += [
                        s for s in list(self.remote.get(host, {}).values()) if Path(s.dir).resolve() == directory
                    ]
        for s in records:
            if s.state not in rest:
                return s.name
        for ext in adapters.external_sessions()["items"]:
            if ext.tool_id and ext.tool_id in ours:
                continue
            if Path(ext.cwd).resolve() == directory and ext.status != "idle":
                return ext.name if ext.status in ("busy", "shell") else ""
        return None

    def conversation_holders(self, adapter_id: str) -> list[str]:
        """Who is driving the tool conversation `adapter_id` right now (TD-012): a live record of
        ours, or a live session outside shiftlead whose tool id matches. Two panes on one
        conversation is the failure `resume` must not create; an exited record is superseded
        instead (`_supersede`)."""
        out = [
            f"{s.id} ({s.state})"
            for s in self.sessions.values()
            if s.adapter_id == adapter_id and s.state not in ("exited", "closed")
        ]
        ours = {s.adapter_id for s in self.sessions.values() if s.adapter_id}
        for ext in adapters.external_sessions()["items"]:
            if ext.tool_id == adapter_id and ext.tool_id not in ours:
                out.append(f"{ext.name} ({ext.adapter}, outside shiftlead{', ' + ext.status if ext.status else ''})")
        return out

    async def rpc_occupancy(self, dir: str) -> dict[str, Any]:
        directory = Path(dir).expanduser()
        if not directory.is_dir():
            return {"dir": str(directory), "occupants": [], "git": False}
        occ = await asyncio.to_thread(self.occupants, directory)
        is_git = (directory / ".git").exists() or await asyncio.to_thread(lambda: git_info(directory) is not None)
        return {"dir": str(directory.resolve()), "occupants": occ, "git": bool(is_git)}

    def _start(self, sid: str, cwd: Path, argv: list[str] | None, env: dict[str, str], run_log: Path) -> None:
        self.tmux.ensure_server()
        self.tmux.new_session(sid, cwd, argv, env, logfile=run_log)  # log from the first byte (invariant 3)
        self._pane_cgroup(sid)

    def _pane_cgroup(self, sid: str) -> None:
        """Under the installed home's tmux system unit (§4.1, `Delegate=yes`) tmux reaches no user bus
        to give a pane its own scope, so the host agent gives it a cgroup of its own, the fourth
        identity signal (§4.8a, TD-495). Anywhere else nothing is done: tmux's scope stands where it
        made one. A write that fails leaves the pane in the server's cgroup, and the create goes on:
        the session exists by now, so nothing here may fail it (a tmux call that times out included)."""
        try:
            self._pane_cgroup_write(sid)
        except Exception:  # noqa: BLE001 — a pane without its own cgroup is a weaker signal, never a failed create
            log.exception("%s: making the pane's own cgroup failed", sid)

    def _pane_cgroup_write(self, sid: str) -> None:
        pid = self.tmux.server_pid()
        server = self.proc.cgroup(pid) if pid else None
        if identity.server_placement(server) != "system" or not server:
            return
        pane = self.tmux.pane_pid(sid)
        if not pane:
            return
        live = {p.session for p in self.tmux.list_panes()}
        if identity.pane_cgroup(self.cgroup_root, server, sid, pane, live) is None:
            log.info("%s: no cgroup of its own under %s — the pane keeps the server's", sid, server)

    async def rpc_kill(self, id: str, caller: Any = None, killer: dict[str, Any] | None = None) -> dict[str, Any]:
        """Kill the session's pane and keep its record `exited`. Writes `ended: {how: kill, at, by,
        why?}` (§4.2, TD-490): `by` as `closer_of` reads the caller — `person`, a session's id, or
        the tick's own word handed in as `killer`."""
        s = self._get(id)
        if s.state == "scheduled":
            # nothing runs, so a kill is its Cancel (design §6 *Start time*, TD-328): a record left
            # `exited` would read as a run that never happened, and no policy would ever start it
            return await self._cancel_start(s)
        await asyncio.to_thread(self.tmux.kill_session, id)
        if s.state != "exited":
            who = closer_of(caller, killer, now_iso())
            s.ended = {"how": "kill", "at": who["at"], "by": who["by"]}
            if who["why"]:
                s.ended["why"] = who["why"]
        s.set_state("exited", confidence="tick")
        s.pane = False  # unlike a natural exit, a kill destroys the pane (TD-023)
        self._killed_at[id] = datetime.now(UTC)  # a tick's older pane list must not revive it (TD-063)
        self._killed_run_at[id] = time.monotonic()  # its own SessionEnd may land after a resume (TD-822)
        self.store.save(s)
        await self._push_changes()  # the Focus terminal ends on this delta, not on a retry (TD-029)
        return s.view()

    async def rpc_close(
        self,
        id: str,
        caller: Any = None,
        closer: dict[str, Any] | None = None,
        reap: bool | str = True,
        restart: bool = False,
    ) -> dict[str, Any]:
        """End a session and keep its record (§4.5a **Close**). Writes `closer: {by, why, at}`
        (§4.5 row 5 (b), TD-265): `by` is `person` when the envelope carries no caller, else the
        caller's id. `closer` is the tick's own word (`{"by": "tick", "why": …}`) or the home's,
        handed on to a node over the link; it is taken only from a call with no session caller, so
        a session can never write *closed by the tick* or another's name. `reap` (§4.1 *A close reaps
        the worktree it made*, TD-979): `True` reaps the worktree the record's start made, `False` is a
        restart's and keeps it saying nothing, a string is the home's why to write as `worktree_kept` —
        taken only from a call with no session caller on this socket, as `closer` is. A missing one reaps.
        A run-only member's close marks it `closed_for: {why: run_ended}` (`agent_common.run_ended`, §4.9,
        TD-1166), the home's mark, except `restart`'s: a person's Restart's own close, honoured from no
        session caller."""
        if isinstance(reap, str) and not mail.is_person(caller):
            raise RpcError("a close's reap why is the home's word: a session closes with reap true or false")
        return await self._close(id, caller, closer, reap, restart)

    async def _close(
        self,
        id: str,
        caller: Any = None,
        closer: dict[str, Any] | None = None,
        reap: bool | str = True,
        restart: bool = False,
    ) -> dict[str, Any]:
        """`rpc_close` past its gate. A close the home routed here (`_act`) comes in at this door: a string
        `reap` over the link is the home's why whatever session closed (§4.1), so it is never refused."""
        s = self._get(id)
        if s.state == "scheduled":
            # **Cancel** (design §6 *Start time*, §4.5a): nothing ran, so there is nothing to keep —
            # the record and its launch record are forgotten and the directory's slot is free
            return await self._cancel_start(s, reap)
        if s.state == "closed":
            # a retry (§4.1 *the record*): the reap again, or its branches weighed again; it kills nothing,
            # and the close's stamps stand — but any close clears the tick's mark (§6 rule 2, TD-237), and
            # marks a run-only member's run ended (§4.9, TD-1166)
            mark = None if self.mode == "node" else run_ended(s, caller, restart, s.closed_at or now_iso())
            marked = s.closed_for != mark
            if marked:
                s.closed_for = mark
                self.store.save(s)
            if await self._reap_again(s, reap) or marked:
                await self._push_changes()
            return s.view()
        await asyncio.to_thread(self.tmux.kill_session, id)
        s.set_state("closed", confidence="tick")
        s.pane = False
        s.closed_at = now_iso()
        s.closer = closer_of(caller, closer, s.closed_at)
        # a Close is nobody's restart; the tick writes its own after this returns (§6 rule 2). A run-only
        # member's run ends with it (§4.9, TD-1166): the home's mark, so a node's is written on the home's copy
        s.closed_for = None if self.mode == "node" else run_ended(s, caller, restart, s.closed_at)
        # A `kill` then a `close` before an intervening tick would otherwise strand a `_killed_at`
        # stamp for `CLOSED_KEEP`: the reconcile skips a closed record before it reaches the guard,
        # so nothing else would ever clear it. Harmless — a closed record is never observed either
        # way — but it would make the guard's one-tick bound untrue (review of PR #199).
        self._killed_at.pop(id, None)
        self.store.save(s)
        self._asker_gone(s, self._address(s))  # its open questions to the person close with it (§4.10)
        await self._push_changes()  # the Focus terminal ends on this delta, not on a retry (TD-029)
        if await self._reap(s, reap):  # after the `closed` save, so a crash midway leaves a record to retry
            await self._push_changes()
        return s.view()

    # -- a close's reap of the worktree its start made (design §4.1 *A close reaps the worktree it made*) --

    async def _reap(self, s: Session, reap: bool | str) -> bool:
        """Reap `s`'s worktree as its close's `reap` says, writing the result on the record: `worktree_kept`
        with its why, or `worktree_reaped_at` with `branches_deleted` and `branch_kept`. Only a record with
        an agent whose start made its worktree is reaped; one that named a worktree it did not make reads
        *not made here*. Never raises: a reap that fails leaves the record closed. Answers whether it wrote."""
        if reap is False or not adapters.has_agent(s.adapter):
            return False
        if isinstance(reap, str):
            if not (s.worktree or s.worktree_made):
                return False  # no worktree: nothing to keep, and nothing said
            s.worktree_kept = reap
        elif not s.worktree_made:
            if not s.worktree:
                return False
            s.worktree_kept = "not made here"
        else:
            deadline = time.monotonic() + REAP_WITHIN
            task = asyncio.ensure_future(self._reap_locked(s, deadline))
            task.add_done_callback(lambda t: t.cancelled() or t.exception())  # retrieved, should the close go
            try:
                # shielded: a dropped link or a client that gives up never lets the locks go while the thread
                # is still removing the tree
                await asyncio.shield(task)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — never raise out of the close
                log.warning("%s: its reap failed: %s", s.id, e)
                s.worktree_reaping = None
                s.worktree_kept = f"the reap failed: {str(e) or type(e).__name__}"
        self.store.save(s)
        return True

    async def _reap_again(self, s: Session, reap: bool | str) -> bool:
        """`ao close` on a `closed` record whose start made its worktree (§4.1): its directory there, the reap
        runs again; gone, its branches are weighed again under the per-name worktree lock — the ones
        `branch_kept` names, or, never reaped, the stale registration's branch and the launch branch, then
        `worktree_reaped_at`. A reap still stamped `worktree_reaping` is the start's recovery's. Answers whether
        it wrote; never raises."""
        if reap is False or not s.worktree_made or not adapters.has_agent(s.adapter) or s.worktree_reaping:
            return False
        if Path(s.dir).is_dir():
            return await self._reap(s, reap)
        if s.worktree_reaped_at and not s.branch_kept:
            return False  # reaped, and nothing kept to weigh again
        wt = Path(s.dir)
        try:
            main = await asyncio.to_thread(main_checkout, s.repo or wt.parent.parent.parent)
        except (WorktreeError, OSError) as e:
            # the lock's key is the main checkout as the create resolves it: weighed under another key, a
            # create could check out a branch the retry is deleting
            log.warning("%s: its branches are not weighed again: the main checkout could not be read: %s", s.id, e)
            return False
        task = asyncio.ensure_future(self._reweigh_locked(s, main, s.worktree or wt.name))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())  # retrieved, should the close go
        try:
            return await asyncio.shield(task)  # the lock held, and the record written, until the thread returns
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — never raise out of the close
            log.warning("%s: weighing its branches again failed: %s", s.id, e)
            return False

    async def _reweigh_locked(self, s: Session, main: Path, name: str) -> bool:
        """`_reap_again`'s weigh under the per-name worktree lock `rpc_create` takes, awaited within
        `REAP_WITHIN` (held: *busy*), and the record written before the lock is let go."""
        lock = self._dir_locks[f"worktree:{main}:{name}"]
        try:
            await asyncio.wait_for(lock.acquire(), REAP_WITHIN)
        except TimeoutError:
            s.worktree_kept = "busy: a start is using it"
            self.store.save(s)
            return True
        try:
            got = await asyncio.to_thread(reweigh_gone, main, s.dir, name, s.branch_kept, bool(s.worktree_reaped_at))
            if got is None:
                log.warning(
                    "%s: its worktree %s is gone and git's registration of it was not read and pruned", s.id, s.dir
                )
                return False
            deleted, kept = got
            s.worktree_kept = None
            s.worktree_reaped_at = s.worktree_reaped_at or now_iso()
            s.branches_deleted = list(dict.fromkeys([*(s.branches_deleted or []), *deleted]))
            s.branch_kept = kept
            self.store.save(s)
        finally:
            lock.release()
        log.info("%s: its branches weighed again: deleted %s, kept %s", s.id, deleted, kept)
        return True

    async def _reap_locked(self, s: Session, deadline: float) -> None:
        """The reap under the per-name worktree lock `rpc_create` takes around `ensure_worktree`, then the
        directory's, each awaited only for what is left of `REAP_WITHIN` and both held until the thread
        returns."""
        wt = Path(s.dir)
        name = s.worktree or wt.name
        loop = asyncio.get_running_loop()

        def left() -> float:
            return deadline - time.monotonic()

        try:
            main = await asyncio.to_thread(main_checkout, wt)
        except WorktreeError:
            main = wt.parent.parent.parent
        async with contextlib.AsyncExitStack() as locks:
            for key in (f"worktree:{main}:{name}", str(wt)):
                lock = self._dir_locks[key]
                try:
                    await asyncio.wait_for(lock.acquire(), max(left(), 0.01))
                except TimeoutError:
                    self._reaped(s, {"kept": "busy: a start is using it"})
                    return
                locks.callback(lock.release)
            while await asyncio.to_thread(self.tmux.has_session, s.id):
                if left() <= REAP_STEP:
                    self._reaped(s, {"kept": TIMED_OUT})  # the pane outlived what is left of the deadline
                    return
                await asyncio.sleep(0.1)  # after the kill, once the pane is gone: nothing writes into the tree

            running = [True]

            def stamp(branch: str | None) -> None:
                async def put() -> None:  # on the loop, which owns the record; never after the reap ended
                    if running[0]:
                        s.worktree_reaping = {"at": now_iso(), "branch": branch}
                        self.store.save(s)

                asyncio.run_coroutine_threadsafe(put(), loop).result(REAP_STEP)

            try:
                got = await asyncio.to_thread(
                    reap_worktree, wt, name, deadline=deadline, idle=lambda: self._reap_idle(s, wt), on_reaping=stamp
                )
            finally:
                running[0] = False
            self._reaped(s, got)

    def _reaped(self, s: Session, got: dict[str, Any]) -> None:
        """Write a reap's result on the record, saved here so a close cancelled midway still keeps it, and the log."""
        s.worktree_reaping = None
        if "kept" in got:
            s.worktree_kept = str(got["kept"])
            self.store.save(s)
            log.info("%s: its worktree %s is kept: %s", s.id, s.dir, s.worktree_kept)
            return
        s.worktree_kept = None
        s.worktree_reaped_at = now_iso()
        s.branches_deleted = list(got.get("branches_deleted") or [])
        s.branch_kept = dict(got.get("branch_kept") or {})
        self.store.save(s)
        log.info(
            "%s: its worktree %s is reaped; branches deleted %s, kept %s",
            s.id,
            s.dir,
            s.branches_deleted,
            s.branch_kept,
        )

    def _reap_idle(self, s: Session, wt: Path) -> str | None:
        """The reaper's *idle*, through ShiftLead's own seams (§4.1): no live record of any adapter, a shell's
        included, has its `dir` inside `wt` — this host's, and while their link is up those of the container
        nodes that share the directory (a link down keeps as *<host> unreachable*) — and no session outside
        ShiftLead is inside; a blind adapter keeps. `s` itself, and an outside session whose tool id is one of
        ours, never count. Run in a thread: it reads copies of the maps."""
        wt = wt.resolve()

        def inside(d: str) -> bool:
            p = Path(d).resolve()
            return p == wt or wt in p.parents

        mine = list(self.sessions.values())
        ours = {r.adapter_id for r in mine if r.adapter_id}
        for r in mine:
            if r.id != s.id and r.state not in ("exited", "closed") and r.dir and inside(r.dir):
                return f"in use by {r.id}"
        if self.mode == "home" and self.remote:
            for host in containers.container_nodes():
                if not (self.links.get(host) or {}).get("up"):
                    return f"{host} unreachable"
                for r in list(self.remote.get(host, {}).values()):
                    ours.add(r.adapter_id or "")
                    if r.state not in ("exited", "closed") and r.dir and inside(r.dir):
                        return f"in use by {r.id}@{host}"
        seen = adapters.external_sessions()
        if seen["blind"]:
            return f"{seen['blind'][0]} sessions could not be read"
        for ext in seen["items"]:
            if ext.tool_id and ext.tool_id in ours:
                continue
            if ext.cwd and inside(ext.cwd):
                return f"in use by {ext.name} ({ext.adapter}, outside shiftlead)"
        return None

    def _recover_reaps(self) -> None:
        """At the host agent's start, a record still stamped `worktree_reaping` was cut off midway (a promote,
        a crash): its directory there, it is hydrated again and reads *interrupted*; gone, the remove had
        finished, so it is `worktree_reaped_at`, `git worktree prune` runs and its branches are weighed."""
        for s in list(self.sessions.values()):
            if not s.worktree_reaping or s.host != self.host:
                continue
            wt = Path(s.dir)
            try:
                main = main_checkout(wt if wt.is_dir() else wt.parent.parent.parent)
            except WorktreeError:
                main = wt.parent.parent.parent
            if wt.is_dir():
                rehydrate(main, wt)
                s.worktree_kept = "interrupted"
            else:
                with contextlib.suppress(OSError, subprocess.SubprocessError):
                    subprocess.run(
                        ["git", "-C", str(main), "worktree", "prune"], capture_output=True, timeout=REAP_STEP
                    )
                deleted, kept = weigh_branches(main, [s.worktree_reaping.get("branch"), s.worktree or wt.name])
                s.worktree_kept = None
                s.worktree_reaped_at = now_iso()
                s.branches_deleted, s.branch_kept = deleted, kept
            s.worktree_reaping = None
            log.info("%s: a reap cut off at the last start: %s", s.id, s.worktree_kept or "reaped")
            self.store.save(s)

    async def rpc_restart(self, id: str, caller: Any = None) -> dict[str, Any]:
        """A person's restart (design §6 rule 2 *A person's restart*, TD-250): what the tick would not
        do — an `early` or a `repeat` declaration, a member at its ceiling, one a person closed —
        said in one press and then done the tick's way. The record is closed if it is still there,
        under the tick's own test (`gitinfo.work_left`), and created again from its launch record,
        the prompt refilled as rule 7's replay refills it. The new record starts fresh: no marks,
        and `restarts` the one entry `{at, why: person}`, which never counts toward the ceiling.
        **A person's own**, refused to a session as `set_settings` is, and the home's alone
        (`modes.HOME_EDITS`); a node's member is closed and created over the link. Every refusal is
        made before anything is touched; the reply is the new record."""
        agent_common.person_only(caller, "restart a session", "§6 rule 2", self._graph())
        if self.mode != "home":
            raise RpcError("restart runs at the home (design §6 rule 2): this host is a node")
        s = self._find(id)
        now = datetime.now(UTC)
        params = self._restart_check(s, now)
        entry: dict[str, Any] = {"at": now_iso(), "why": "person"}
        read = await self._refill_prompt(s, params, entry)  # before the close: a read that raises touches nothing
        if s.state == "idle":  # a restart keeps the worktree: the new run takes up its directory and branch
            if s.host == self.host:
                await self.rpc_close(s.id, reap=False, restart=True)  # its own close marks no run ended (§4.9)
            else:
                await self._route_act("close", {"id": s.id, "reap": False, "restart": True}, None, s.host)
        try:
            if s.host == self.host:
                view = await self.rpc_create(**params)
            else:
                view = await self._route_act("create", {**params, "host": s.host}, None, s.host)
        except Exception as e:  # noqa: BLE001 — said to the person who pressed, whatever it was
            log.warning("%s: the person's restart failed: %s", s.id, e)
            raise RpcError(
                f"the restart of {s.name} failed: {str(e) or type(e).__name__} — it is {s.state} and its "
                "marks stand; Restart again, or Resume with changes… (design §6 rule 2)"
            ) from None
        rid, _h = naming.split_address(str((view or {}).get("id") or ""))
        new = self.sessions.get(rid) if s.host == self.host else self.remote.get(s.host, {}).get(rid)
        if new is None or new is s:
            return view  # a node's record the home has not been told of yet: the create's own reply
        new.restarts = [entry]
        new.restart_wanted = new.restart_ceiling = new.restart_blocked = None
        new.brief = read  # the files as this restart read them (as `_replay` writes it)
        self._save(new)
        await self._push_changes()
        log.info("%s restarted by the person from its launch record", self._address(new))
        return self._view(new)

    async def rpc_relaunch(
        self,
        id: str,
        launch: dict[str, Any] | None = None,
        sit_out: bool = False,
        dropped: bool = False,
        caller: Any = None,
    ) -> dict[str, Any]:
        """A person's Apply, one member (design §4.9c *Switching*, TD-309 slice 5): the client composed
        the member under the team's current flow and hands its launch here — `prompt`, `prompt_from`,
        `lane`, `review` and `profile` (`RELAUNCH_KEYS`), each replaced as handed and an absent one
        removed — `profile` kept instead (`RELAUNCH_KEPT`, TD-619) — the rest of the launch record
        standing. A `profile` handed is refused unless the member's adapter runs a profile of that name
        (`doctor_profiles`: the core cannot read `profiles.yml`), checked for a member of this host; a
        node's profiles are its own. The home writes it as the record's launch record, re-records
        `brief` from the new `prompt_from` as a create does, clears `brief_changed`, and marks the record
        `relaunch: {at, lane, review, profile}` (the lane and review as handed, the profile the record now
        names, so a client reads what the member runs next),
        which rule 7 reads as its second trigger (`why: flow`): every replay reads the new record, and a
        create under the name clears the mark. **A person's own**, refused to a session as
        `set_settings` is, and the home's alone (`modes.HOME_EDITS`); never an interactive session, and
        never one with no launch record. Nothing is touched before every check passes;
        the reply is the record.

        **`sit_out: true`** is its other form (slice 5b): a member the flow no longer uses is wound
        down as **Members…**'s remove winds one down — the wrap-up sent now, a working member finishing
        what it holds — but by the home, which writes `sit_out: {at}` and, once the member is settled,
        closes it itself and marks it `closed_for: {why: sit_out}` (the tick's `_sit_out_close`). It
        takes no launch; never a seat (rule 3 fills one when it is due) or a scheduled record.

        **A rename** (design §4.9 *A member renamed or removed in the definition*, TD-706): a launch that
        hands `name` — kept when absent, as `profile` is — and differs from the launch record's is
        marked on `relaunch` as `name`, and the record's next replay (rule 7's restart, rule 8's start,
        rule 3's fill) creates under it, succeeding this record (`create`'s `succeeds`). **`dropped:
        true`** beside `sit_out` is a removal from the definition: it lifts the sit-out's seat refusal,
        since a seat the definition drops is marked as any member is, and rule 3 never fills a sat-out
        seat; it is marked on `sit_out`."""
        agent_common.person_only(caller, "relaunch a session", "§4.9c", self._graph())
        if self.mode != "home":
            raise RpcError("relaunch runs at the home (design §4.9c): this host is a node")
        s = self._find(id)
        rule = "(design §4.9c *Switching*)"
        if sit_out:
            return await self._sit_out(s, launch, rule, dropped=bool(dropped), caller=caller)
        if dropped:
            raise RpcError(f"dropped is the sit-out form's: a removal from the definition {rule}")
        if not isinstance(launch, dict):
            raise RpcError(f"relaunch needs the member's composed launch {rule}")
        stray = sorted(k for k in launch if k not in RELAUNCH_KEYS)
        if stray:
            raise RpcError(f"a relaunch replaces {', '.join(RELAUNCH_KEYS)} alone, not {', '.join(stray)} {rule}")
        kinds = {"prompt": str, "prompt_from": dict, "lane": list, "review": dict, "profile": str, "name": str}
        for k, v in launch.items():
            if v is not None and not isinstance(v, kinds[k]):
                raise RpcError(f"a relaunch's {k} is a {kinds[k].__name__}, not {type(v).__name__} {rule}")
        if launch.get("name") is not None and not str(launch["name"]).strip():
            raise RpcError(f"a relaunch's name is the member's new name, never blank {rule}")
        if not s.unattended:
            raise RpcError(f"{s.name} is interactive: its lane and brief are the person's, never relaunched {rule}")
        if s.superseded_by:
            raise RpcError(f"{s.name} was resumed as {s.superseded_by}: that is the record to relaunch {rule}")
        if isinstance(s.closed_for, dict) and s.closed_for.get("why") == "run_ended":
            raise RpcError(f"{s.name}: its run ended: start the team, or add one from the form (design §4.9)")
        if s.sit_out or work_mod.sat_out(s):
            raise RpcError(f"{s.name} is sat out by its team's flow: a create under the name starts it again {rule}")
        address = self._address(s)
        try:
            if not s.supervised:
                raise RpcError("not supervised")
            params = self._read_launch(address)
        except RpcError:
            raise RpcError(f"{s.name} has no launch record, so there is nothing to relaunch {rule}") from None
        if launch.get("profile") is not None and s.host == self.host:
            await self._relaunch_profile(s, str(launch["profile"]), rule)
        before = params.get("name")
        for k in RELAUNCH_KEYS:
            if k not in RELAUNCH_KEPT or launch.get(k) is not None:
                params.pop(k, None)
        params.update({k: v for k, v in launch.items() if v is not None})
        # a rename is the launch record's name moved off the record's, by this Apply or one before it
        # whose replay has not run yet — a second Apply keeps the first one's rename, and one that hands
        # the record's own name back cancels it (the review of TD-706 slice 2)
        pending = s.relaunch.get("name") if isinstance(s.relaunch, dict) else None
        final = params.get("name")
        renamed = final if final and final != s.name and (final != before or pending == final) else None
        made = params.get("prompt_from")
        # a node member's files are that host's, which rule 7 never reads here (as the replay)
        read = await asyncio.to_thread(brief.record, made, False) if made and s.host == self.host else None
        self._write_launch(address, s, params)
        s.brief, s.brief_changed = read, None
        self._brief_differs.pop(s.id, None)
        s.relaunch = {
            "at": now_iso(),
            "lane": launch.get("lane"),
            "review": launch.get("review"),
            "profile": str(params.get("profile") or ""),
            **({"name": str(renamed)} if renamed else {}),
        }
        self._save(s)
        await self._push_changes()
        log.info("%s relaunched by the person: its launch record replaced", address)
        return self._view(s)

    async def _relaunch_profile(self, s: Session, profile: str, rule: str) -> None:
        """A relaunch's `profile` names one the member's adapter runs (TD-619), as a create's launch
        would find it: read through the adapter's `doctor_profiles`, since `profiles.yml` is not the
        core's to read. Empty is the default profile; an adapter that reads no profiles checks nothing."""
        fn = getattr(adapters.get(s.adapter), "doctor_profiles", None) if profile else None
        if fn is None:
            return
        try:
            rows = await asyncio.to_thread(fn)
        except Exception as e:  # noqa: BLE001 — a profiles file that cannot be read refuses, in its words
            raise RpcError(f"{s.name}'s profiles could not be read ({e}): nothing relaunched {rule}") from None
        bad = next((r["error"] for r in rows if isinstance(r, dict) and r.get("error")), None)
        if bad:
            raise RpcError(f"{s.name}'s profiles could not be read ({bad}): nothing relaunched {rule}")
        known = sorted({str(r.get("profile")) for r in rows if isinstance(r, dict) and r.get("profile")})
        if profile not in known:
            names = ", ".join(known) or "none"
            raise RpcError(f"no profile {profile!r} in profiles.yml (known: {names}): nothing relaunched {rule}")

    async def _sit_out(
        self, s: Session, launch: Any, rule: str, dropped: bool = False, caller: Any = None
    ) -> dict[str, Any]:
        """`relaunch`'s sit-out form: refused, touching nothing, on a launch handed with it, an interactive
        record, a superseded one, a seat or a scheduled one, and when the wrap-up cannot be sent (a
        pending prompt, a link down); said again of a record already sitting out, it does nothing more.
        `dropped` (a removal from the definition, TD-706) lifts the seat refusal and is kept on the mark."""
        if launch is not None:
            raise RpcError(f"a sit-out takes no launch: the member stops, it is not composed again {rule}")
        if not s.unattended:
            raise RpcError(f"{s.name} is interactive: a team act never stops a person's session {rule}")
        if s.superseded_by:
            raise RpcError(f"{s.name} was resumed as {s.superseded_by}: that is the record to sit out {rule}")
        if s.seat is not None and not dropped:
            raise RpcError(f"{s.name} is a seat: rule 3 fills it when it is due, and a flow never sits one out {rule}")
        if s.state == "scheduled":
            raise RpcError(f"{s.name} is scheduled and has not started: Cancel it instead {rule}")
        if s.sit_out or work_mod.sat_out(s):
            return self._view(s)
        if s.state not in ("exited", "closed") and adapters.has_agent(s.adapter):
            try:  # a record with no agent is typed nothing: the sit-out's close stops it (§4.3)
                if s.host == self.host:
                    await self.rpc_send(s.id, WRAPUP_PROMPT, wrapup=True, caller=caller)
                else:  # the caller carried, so the wrap-up's `wrapup_by` is whoever pressed (TD-781)
                    await self._route_act("send", {"id": s.id, "text": WRAPUP_PROMPT, "wrapup": True}, caller, s.host)
            except Exception as e:  # noqa: BLE001 — said to the person who pressed, nothing marked
                raise RpcError(
                    f"{s.name}: the wrap-up could not be sent ({str(e) or type(e).__name__}), "
                    f"so it is not sat out {rule}"
                ) from None
        s.sit_out = {"at": now_iso(), **({"dropped": True} if dropped else {})}
        self._save(s)
        await self._push_changes()
        log.info("%s sat out by the person's Apply: the wrap-up sent", self._address(s))
        return self._view(s)

    def _restart_check(self, s: Session, now: datetime) -> dict[str, Any]:
        """`restart`'s refusals, each by name (design §6 rule 2 *A person's restart*), and the launch
        record as `create`'s arguments when none applies. Nothing is changed here."""
        rule = "(design §6 rule 2)"
        if s.seat is not None:
            raise RpcError(f"{s.name} is a seat: rule 3 fills it when it is due, and Resume is the way to it {rule}")
        if s.suspended:
            raise RpcError(
                f"{s.name} is suspended over an identity alarm: only a person's Resume or Forget lifts that, "
                f"and a restart is neither (design §4.8a)"
            )
        if s.superseded_by:
            raise RpcError(f"{s.name} was resumed as {s.superseded_by}: that is the record to restart {rule}")
        if s.state == "scheduled":
            raise RpcError(f"{s.name} is scheduled and has not started: `ao at {s.id} now` starts it {rule}")
        if isinstance(s.closed_for, dict) and s.closed_for.get("why") == "run_ended":
            raise RpcError(
                f"{s.name}: its run ended: start the team, or add one from the form (design §4.9, §6 rule 2)"
            )
        if s.state not in ("idle", "exited", "closed"):
            raise RpcError(
                f"{s.name} is {s.state}: a restart is of a session that is idle, exited or closed — wait, or "
                f"Wrap up {rule}"
            )
        try:
            if not s.supervised:
                raise RpcError("not supervised")
            launch = self._read_launch(self._address(s))
        except RpcError:
            raise RpcError(
                f"{s.name} has no launch record, so nothing says how it was started: Resume with changes… "
                f"is the way back {rule}"
            ) from None
        scope = s.repo or s.dir
        for r in self._graph().values():
            live = r.state not in ("exited", "closed") and not r.superseded_by
            if r is not s and live and r.host == s.host and r.name == s.name and (r.repo or r.dir) == scope:
                raise RpcError(f"{s.name} is the name of {self._address(r)}, which is {r.state}: one of a name {rule}")
        if s.host == self.host:
            # the create finds what it supersedes at the name's own id: a record under a suffixed id
            # (tmux held the base when it started) is not there, and the create would refuse after the close
            base = naming.base_id(s.dir, s.repo, str(launch.get("name") or ""))
            if self.sessions.get(base) is not s:
                raise RpcError(
                    f"{s.name} ({s.id}) does not hold its launch record's name, {launch.get('name')!r} ({base}): "
                    f"Resume with changes… is the way back {rule}"
                )
        until = launch.get("run_until")
        try:
            passed = bool(until) and now >= _parse(str(until))
        except ValueError:
            passed = False
        if passed:
            raise RpcError(f"{s.name}: its stop time has passed — Resume with changes… {rule}")
        profile, team = str(launch.get("profile") or ""), str(launch.get("team") or "")
        if self._profile_gated(profile, now, team):
            raise RpcError(
                f"{s.name}: its profile {profile or '(default)'} is over its usage line, and the gate would pause "
                f"what the press started — `ao gate` prints the lines {rule}"
            )
        if s.host != self.host and s.host not in self._link_muxes:
            raise RpcError(f"{s.name} runs on {s.host}, whose link is down: a restart waits for it (design §4.4a)")
        if left := work_left(s.git):
            raise RpcError(
                f"{s.name} has {left}: a restart closes a session only with its work committed and pushed {rule}"
            )
        # `keep_mail`: the new record is a new record, so its inbox and outbox move as a seat's fill moves
        # them. Its own open questions to the person end with the close of an idle one, as at any close.
        return {**launch, "supervised": True, "keep_mail": True}

    async def rpc_remove(self, id: str, caller: Any = None) -> None:
        s = self._get(id)
        if s.state == "scheduled":
            await self._cancel_start(s)  # §6 *Start time*: Forget of a scheduled record is its Cancel
            return
        if s.state not in ("exited", "closed"):
            raise RpcError(f"{id} is {s.state}; kill it first")
        # **Forget is the other road out of a suspension** (design §4.8a, TD-077 a2), so it is a
        # person's, as the resume is. The acting gate lets a controller remove an unattended
        # member's record — which for a suspended one would free the name and let the very
        # session under suspicion be started again, unmarked (review of PR #301).
        self._refuse_suspended(s, caller, "forgetting it")
        # The dead pane is kept until now (exit code, last screen); without this it would be
        # re-adopted as a nameless shell on the next tick (first-use finding 2026-09-06).
        # one extra `list-panes -a` per remove, a person-driven action: accepted
        pane = (await asyncio.to_thread(self.tmux.main_panes, naming.PREFIX)).get(id)
        await asyncio.to_thread(self.tmux.kill_session, id)
        self._forget(id)
        self._removed[id] = (pane.created if pane else None, time.monotonic())
        await self._push_changes()

    async def rpc_send(
        self,
        id: str,
        text: str,
        wait: bool = False,
        timeout: float | None = None,
        caller: Any = None,
        wrapup: bool = False,
        key: str | None = None,
    ) -> dict | None:
        """Type a prompt. With `wait` (TD-016, design §4.2): return the record once the session has
        started on *this* prompt and settled again (`SETTLED`). A session that is busy queues the
        prompt behind its current turn, so the wait first lets that turn end, then looks for the
        next one to start. Errors: `prompt-stalled` when nothing starts within `SEND_STALL_SECONDS`
        of the moment it could, `timeout` after `timeout` seconds in total, `removed` if the record
        goes away. Nothing is ever re-sent on a guess (design §4.2). `caller` is the envelope's,
        injected by the dispatcher: every send that reaches the pane is recorded on the record as
        `sends`, with who typed it (design §4.10). `wrapup` says this text is the wrap-up prompt
        (the card's Wrap up, `ao team stop`): it is stamped on the record as `wrapup_at`, which holds
        the doorbell off, and a send without it clears the stamp (§4.10 "A pending stop beats mail").
        `key` is the page's id for this send (§4.10 *A send lands once*, TD-806): a repeat of it from the
        same caller within `SEND_KEY_SECONDS` answers as that send did, before anything else here."""
        s = self._get(id)
        if key:
            first = self._keyed_send(s, caller, str(key))
            if first is not None:
                return await first
        self._refuse_gone(s)
        if s.pending and s.pending.pane_held:
            # a subagent's dialog is not drawn while the hook blocks (§4.2 *A subagent's dialog is held
            # back*, TD-950): the buttons are its one channel until the deadline, never the terminal
            until = _clock_words(s.pending.deadline)
            msg = f"a subagent's permission is pending: press Allow / Deny (the pane shows nothing until {until})"
            raise RpcError(msg)
        if s.pending and s.pending.kind in ("permission", "question"):
            raise RpcError(f"{id} has a pending {s.pending.kind}; answer it in the terminal")
        if wrapup and not adapters.has_agent(s.adapter):
            raise RpcError(f"{s.name}: a shell runs no turns: there is nothing to wrap up — Close it (design §4.3)")
        s.wrapup_at = now_iso() if wrapup else None
        s.wrapup_by = closer_of(caller, None, "")["by"] if wrapup else None  # who stopped it (§6 rule 8, TD-781)
        entry = self._record_send(s, caller, text, key=str(key) if key else None)
        if mail.as_person(caller, self._graph()):
            self._refill(s)
        typing: asyncio.Future[None] | None = None
        if key:
            typing = self._keyed_sends[(id, str(key))] = asyncio.get_running_loop().create_future()
        try:
            state_sent, rev_sent = await self._submit(id, adapters.get(s.adapter), text)
        except RpcError as e:
            entry.verdict = str(e)
            self.store.save(s)
            raise
        except BaseException as e:
            # a failure not put into words (a tmux error from the paste) leaves the entry *submitted*,
            # as a restart does; a repeat waiting on it gets the same exception
            if typing is not None and not typing.done():
                typing.set_exception(e if isinstance(e, Exception) else RpcError(f"{id}: the send was cancelled"))
            raise
        finally:
            if typing is not None:
                self._keyed_sends.pop((id, str(key)), None)
                if not typing.done():
                    if entry.verdict == "submitted":
                        typing.set_result(None)
                    else:
                        typing.set_exception(RpcError(entry.verdict))
                typing.exception()  # read here, so a failure no repeat awaited is not logged as unread
        if not wait:
            return None
        end = None if timeout is None else time.monotonic() + timeout

        def left() -> float | None:
            return None if end is None else max(0.0, end - time.monotonic())

        # The baseline is what the session was doing when the text was typed, read before the paste
        # (TD-204): the tool's UserPromptSubmit lands the moment Enter does, often while `_type` is
        # still confirming the composer emptied, and a baseline read after that took this prompt's
        # own turn for a busy session's and then waited for a further one that never came. Accepted
        # residual: an earlier typist's (the doorbell's, a wrap-up's) start that lands late, inside
        # this paste, reads as this prompt's; nothing ties a hook to the prompt that caused it.
        rev_before = rev_sent
        if state_sent != "idle":
            # Busy: the tool queues the text. Wait for the current turn to end; a stop on anything
            # but idle (a question, an exit) is returned as is — the prompt is still queued behind it.
            if not await self._wait_state(s, lambda x: x.state in SETTLED, left()):
                self._raise_not_settled(s, timeout)
            if s.state != "idle":
                return s.view()
            if s.rev - rev_sent >= 3:
                # working → idle → working → idle inside one poll: the queued turn already ran.
                # Accepted residual: a permission answered *and* the rest of that same turn finishing
                # inside one 0.1 s poll would look the same; a turn does not end that fast.
                return s.view()
            rev_before = s.rev
        # Started: any transition since the baseline (a hook's UserPromptSubmit → working, a scraped
        # working, even an exit) within the stall window.
        stall = agent_common.SEND_STALL_SECONDS if left() is None else min(agent_common.SEND_STALL_SECONDS, left())
        if not await self._wait_state(s, lambda x: x.rev != rev_before, stall):
            if self.sessions.get(id) is not s:
                raise RpcError(f"removed: {id} went away while waiting")
            raise RpcError(f"prompt-stalled: {id} showed no activity within {stall:g} s")
        if not await self._wait_state(s, lambda x: x.state in SETTLED and x.rev != rev_before, left()):
            self._raise_not_settled(s, timeout)
        return s.view()

    @staticmethod
    def _refuse_gone(s: Session) -> None:
        """A record with **no turn to type into** is refused in words (design §4.5a *Focus
        composer*, §4.10 lifecycle). Two of them: a **closed** record — a resumed conversation's
        old id in particular, where only mail is forwarded to the successor, never keystrokes —
        and an **exited** one, whose pane is gone or dead. Exited was not refused until 2026-09-20
        (TD-078): the page disabled its composer, the RPC did not, and a send that arrived anyway
        went to tmux, which answered `no current target` — a tmux error for a records question,
        with nothing in it to say which session had gone or when. That is how the flake was read."""
        if s.state == "closed":
            where = f"; it was resumed as {s.superseded_by}" if s.superseded_by else ""
            raise RpcError(f"{s.id} is closed{where}: nothing is typed into a closed session")
        if s.state == "exited":
            code = f" (code {s.exit_code})" if s.exit_code is not None else ""
            raise RpcError(f"{s.id} has exited{code}: there is no turn to type into — resume it, or forget it")

    def _keyed_send(self, s: Session, caller: Any, key: str) -> Any:
        """The send a keyed repeat answers as (§4.10 *A send lands once*, TD-806), or None when there is
        none: an entry of `s.sends` with this key, from this caller (`from_` as `_record_send` writes
        it), made within `SEND_KEY_SECONDS`. The answer is an awaitable — the first send's outcome
        while it is still typing, else its verdict — so a repeat passes no gate, stamps nothing,
        refills nothing and types nothing, and ignores `wait`."""
        who = PERSON if mail.is_person(caller) else str(caller)
        first = next((e for e in reversed(s.sends) if e.key == key and e.from_ == who), None)
        if first is None:
            return None
        try:
            if (datetime.now(UTC) - _parse(first.at)).total_seconds() > mail.SEND_KEY_SECONDS:
                return None
        except ValueError:
            return None
        typing = self._keyed_sends.get((s.id, key))

        async def answer() -> None:
            if typing is not None:
                await asyncio.shield(typing)
            elif first.verdict != "submitted":
                raise RpcError(first.verdict)

        return answer()

    def _record_send(self, s: Session, caller: Any, text: str, key: str | None = None) -> SendEntry:
        """`sends` (design §4.10): what was typed into this pane and by whom, minted and stamped
        here like a message, bounded to the last `SENDS_KEEP`. Written at the gate — before the
        paste, since a paste that then sticks still reached the pane — and its verdict amended if
        the submit fails."""
        who = PERSON if mail.is_person(caller) else str(caller)
        entry = SendEntry(id="s-" + secrets.token_hex(6), from_=who, at=now_iso(), text=text, key=key)
        s.sends = (s.sends + [entry])[-mail.SENDS_KEEP :]
        self.store.save(s)
        return entry

    async def _submit(self, sid: str, adapter: Any, text: str) -> tuple[str, int]:
        """`_type`, holding the session's typing lock: one typist per pane (TD-094). Returns the
        record's state and `rev` as they were under the lock just before the paste — the baseline
        `send --wait` measures *started* from (TD-204)."""
        async with self._typing[sid]:
            s = self._get(sid)
            before = (s.state, s.rev)
            await self._type(sid, adapter, text)
        return before

    async def _type(self, sid: str, adapter: Any, text: str, lead: str | None = None, lead_in: bool = False) -> None:
        """Paste, Enter, and confirm the prompt left the composer (TD-027, design §4.2). Only an
        adapter that can read its tool's composer (`composer(tail_raw)`, design §4.3) gets the
        confirmation; the rest get the blind paste + Enter. The paste is given a moment to paint
        (Enter sent while the tool is still taking the paste is swallowed — measured 2026-09-10:
        a paste landing within ~0.1 s of the previous submit lost its Enter every time), then the
        composer must empty within `SUBMIT_SECONDS`; one retry with `C-m`, then `prompt-stuck`.
        Only the Enter is ever re-sent, and only with the text visibly still in the composer —
        never the text (design §4.2). A composer that cannot be read (no composer row, or a failed
        capture — `capture_tail` returns [] then) counts as emptied: no evidence is not evidence of a
        stuck prompt.

        `lead` is the fixed line in the person's voice (`mail.BRIEF_LINE`), typed as literal keys
        before the paste, in the same prompt (§4.1 *The brief is the person's word*, TD-347). A paste
        refused while that line is in the composer — typed now, or by an earlier try (`lead_in`) —
        raises `LeadTyped`."""
        reader = getattr(adapter, "composer", None)
        # A pane scrolled back is in copy mode, where the Enter would be the mode's (§4.3, TD-667).
        await asyncio.to_thread(self.tmux.leave_copy_mode, sid)
        if lead:
            await asyncio.to_thread(self.tmux.send_literal, sid, lead + " ")
        try:
            await asyncio.to_thread(self.tmux.paste, sid, text)
        except Exception as e:
            if lead or lead_in:
                raise LeadTyped(f"the paste was refused after the line went in: {e}") from e
            raise
        if reader is None:
            await asyncio.to_thread(self.tmux.send_enter, sid)
            return

        async def composer() -> str | None:
            return reader(await asyncio.to_thread(self.tmux.capture_tail, sid, COMPOSER_LINES, raw=True))

        if not await self._poll(lambda: composer(), PASTE_SHOW_SECONDS):
            log.info(
                "send %s: the paste did not show in the composer within %gs; pressing Enter anyway",
                sid,
                PASTE_SHOW_SECONDS,
            )
        for key in ("Enter", "C-m"):
            await asyncio.to_thread(self.tmux.send_key, sid, key)
            if await self._poll(lambda: _falsy(composer()), agent_common.SUBMIT_SECONDS):
                return
            log.warning(
                "send %s: the composer still shows the prompt %gs after %s", sid, agent_common.SUBMIT_SECONDS, key
            )
        raise RpcError(f"prompt-stuck: {sid} still shows the prompt in its composer after Enter and C-m")

    async def _poll(self, pred: Any, timeout: float) -> bool:
        """Until `await pred()` is truthy; False on timeout."""
        end = time.monotonic() + timeout
        while True:
            if await pred():
                return True
            if time.monotonic() >= end:
                return False
            await asyncio.sleep(0.1)

    def _raise_not_settled(self, s: Session, timeout: float | None) -> None:
        if self.sessions.get(s.id) is not s:
            raise RpcError(f"removed: {s.id} went away while waiting")
        raise RpcError(f"timeout: {s.id} is still {s.state} after {timeout:g} s")

    async def _wait_state(self, s: Session, pred: Any, timeout: float | None) -> bool:
        """Poll the record on the loop until `pred(s)` holds; False on timeout (None: no limit) or
        when the record is gone. Gone is *this* record no longer being the one under its id, not
        the id being empty (TD-261): a record forgotten and its id taken again inside one poll — a
        live pane the tick adopts, a new session under the name — is another session, whose turns
        say nothing about the prompt typed into this one, and a wait with no timeout read it for
        ever."""
        end = None if timeout is None else time.monotonic() + timeout
        while True:
            if self.sessions.get(s.id) is not s:
                return False
            if pred(s):
                return True
            if end is not None and time.monotonic() >= end:
                return False
            await asyncio.sleep(0.1)

    async def rpc_keys(self, id: str, keys: list[str], caller: Any = None) -> None:
        s = self._get(id)
        self._refuse_gone(s)
        self._record_send(s, caller, " ".join(str(k) for k in keys))
        if mail.as_person(caller, self._graph()):
            self._refill(s)  # keys are how a person answers a menu or a question in the pane
        await asyncio.to_thread(lambda: self.tmux.run("send-keys", "-t", f"={id}:", *keys))

    async def rpc_explain(self, id: str, lines: int = 40) -> dict[str, Any]:
        """Why the session shows the state it does (design §4.2, TD-015): the current screen, the
        record's state and confidence, the screen rule that would fire on it with its evidence, and
        whether that verdict applies (no fresher hook state) or is outranked."""
        s = self._get(id)
        adapter = adapters.get(s.adapter)
        tail = [_clean(t) for t in await asyncio.to_thread(self.tmux.capture_tail, id, lines)]
        explain = getattr(adapter, "explain", None)
        now = datetime.now(UTC)
        out: dict[str, Any] = {
            "id": id,
            "adapter": s.adapter,
            "state": s.state,
            "confidence": s.confidence,
            "pending": s.pending.to_dict() if s.pending else None,
            "since": s.since,
            "last_hook": self._last_hook[id].replace(microsecond=0).isoformat().replace("+00:00", "Z")
            if id in self._last_hook
            else None,
            "tail": tail,
            "match": None,
            "reason": "",
        }
        if explain is None:
            src = "foreground process" if adapter.state_source == "scraped" else "hooks only"
            out["reason"] = f"{s.adapter} has no screen rules; its state comes from {src}"
            return out
        if getattr(adapter, "state_in_title", False):
            # the tool's title is its rule (§4.2 *A title the tool writes its state into*), the evidence
            pane = (await asyncio.to_thread(self.tmux.main_panes)).get(id)
            title = pane.title if pane else ""
            m = explain(tail, title=title)
            out["title"], out["match"] = title, m.to_dict() if m else None
            if m is not None and not m.title:  # the adapter's manifest, asked first (§4.3)
                if self._hook_within(s, adapter, now):
                    out["reason"] = f"rule {m.rule} matched, but a hook reported within a tick — the hook state wins"
                elif s.state == m.state == "limited" and s.confidence == "hook":
                    out["reason"] = f"rule {m.rule} matched, but the usage poll's limited stands — its reading kept"
                else:
                    out["reason"] = f"rule {m.rule} matched, applied as scraped; held for its screen"
            else:
                out["reason"] = self._title_reading(s, m, now)[1]
            return out
        m = explain(tail)
        out["match"] = m.to_dict() if m else None
        if m is None:
            out["reason"] = "no screen rule matched"
        elif self._hook_fresh(id, now):
            out["reason"] = f"rule {m.rule} matched, but a hook reported within {STALL_AFTER} — the hook state wins"
        else:
            out["reason"] = f"rule {m.rule} matched and no fresher hook state exists — applied as scraped"
        return out

    async def rpc_attach(
        self,
        id: str = "",
        name: str = "",
        data: str = "",
        upload: str = "",
        offset: int = 0,
        total: int | None = None,
        cancel: bool = False,
        draft: str | None = None,
        caller: Any = None,
    ) -> dict[str, Any]:
        """The Focus composer's **Attach** / drop / paste (design §4.4 *Attachment drop*, §4.5a,
        TD-002), in pieces (TD-478): the person's file, base64 in `data`, written under
        `attachments/<session>/` by its name made safe for a prompt (`paths.attachment_name`, `-2`,
        `-3`… where it is taken), and its path returned for the composer to insert — Claude Code
        reads a path in a prompt. A file of one piece (no `total`, or `data` is all of it) is written
        whole and answers `{path, bytes}`. A first piece short of `total` mints an `upload` id and
        starts `<name>.<upload>.part`, answered `{upload, bytes}`; each later piece names the
        `upload` and its `offset`, refused (and the `.part` deleted) unless the offset is the bytes
        written so far; the piece that makes `total` links the `.part` into its final name and
        answers `{path, bytes}`. `cancel` with the `upload` deletes the `.part`. A file past
        `person.attach.max` (§5) is refused on its first piece, before anything is written. A
        person's own act, for a session on this host only: `_get` refuses a node's, whose copy over
        ssh is §7's phase 2.

        `draft` in place of `id` (§4.4 *The Add entry form's draft*, TD-630): the Add entry form's
        files, before any session exists. `""` on a form's first file mints `draft-<8 hex>`; every
        later call names it, refused once a way out has claimed it (`agent_common.draft_folder`).
        The files land in `attachments/<draft>/` by the same pieces, names and bound, and each answer
        carries `draft`."""
        agent_common.person_only(caller, "attach a file", "§4.5a", self._graph())
        if draft is not None:
            if id:
                raise RpcError("attach: a session's id or a draft, not both")
            if draft == "":
                if upload or cancel:
                    raise RpcError("attach: a later piece names its draft, as the first piece's answer gave it")
                token = _mint_draft()
            else:
                token = (await asyncio.to_thread(agent_common.draft_folder, draft, "attach")).name
            owner, said = token, {"draft": token}
            if paths.attachment_name(name) == paths.DRAFT_CLAIM:
                name = f"attached-{name}"  # the claim's name is the sweep's, never a file of the form's
        else:
            owner, said = self._get(id).id, {}
        if upload:
            up = self._uploads.get(upload)
            if up is None or up["session"] != owner:
                raise RpcError(
                    f"attach: no upload {upload} for {owner} (finished, cancelled, or the host agent restarted)"
                )
            if cancel:
                self._uploads.pop(upload, None)
                await asyncio.to_thread(up["part"].unlink, missing_ok=True)
                return {"upload": upload, "cancelled": True, **said}
        elif cancel:
            raise RpcError("attach: cancel names the upload it cancels")
        try:
            raw = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            raise RpcError("attach: the file did not arrive as base64") from None
        if upload:
            written, why = await asyncio.to_thread(_append_part, up["part"], offset, raw, up["total"])
            if not why and upload not in self._uploads:  # cancelled while this piece was written
                await asyncio.to_thread(up["part"].unlink, missing_ok=True)
                why = "was cancelled"
            if why:
                self._uploads.pop(upload, None)
                raise RpcError(f"attach: upload {upload} {why}")
            if written < up["total"]:
                return {"upload": upload, "bytes": written, **said}
            self._uploads.pop(upload, None)
            path = await asyncio.to_thread(_finish_part, up["part"], up["name"])
            return {"path": str(path), "bytes": written, **said}
        if total is None:
            total = len(raw)
        if isinstance(total, bool) or not isinstance(total, int) or total < len(raw):
            raise RpcError(f"attach: total is the file's whole size in bytes, at least this piece's {len(raw)}")
        bound = await asyncio.to_thread(lambda: settings_mod.attach_max(settings_mod.load()))
        if total > bound:
            label = paths.attachment_name(name)
            raise RpcError(f"attach: {label} is {_mib(total)}, past the {_mib(bound)} a file may be")
        where = paths.attachments_dir() / owner
        if len(raw) == total:
            path = await asyncio.to_thread(_write_attachment, where, name, raw)
            return {"path": str(path), "bytes": len(raw), **said}
        for gone in [k for k, v in self._uploads.items() if not v["part"].exists()]:
            self._uploads.pop(gone)  # cancelled by a closed page and swept: nothing will name it again
        upload = secrets.token_hex(8)
        part = where / f"{paths.attachment_name(name)}.{upload}.part"
        await asyncio.to_thread(_start_part, part, raw)
        self._uploads[upload] = {"session": owner, "part": part, "name": name, "total": total}
        return {"upload": upload, "bytes": len(raw), **said}

    async def rpc_tail(self, id: str, lines: int = 40) -> list[str]:
        self._get(id)
        return await asyncio.to_thread(self.tmux.capture_tail, id, lines)

    async def rpc_transcript(
        self,
        id: str = "",
        before: int | None = None,
        turns: int = 20,
        raw: bool = False,
        adapter: str = "",
        adapter_id: str = "",
        dir: str = "",
        profile: str = "",
    ) -> dict[str, Any]:
        """`ao transcript` and the Transcript page's read (design §4.5 screen 9, §4.7, TD-165): the
        record's tool transcript as the adapter's neutral entries — the last `turns` prompts before
        byte `before`, with the offset that asks for earlier ones — or, with `raw`, the file's last
        `turns` lines. Located from the record's own `adapter_id`, `dir`, `adapter` and `profile`, so
        an exited or superseded record reads the run it held; a Resumable row with no record passes
        those four instead of `id`. Served here, on the record's host — a node's record reaches its
        node through `read` (`NODE_READS`) — and never copied. A read: never gated (§9 invariant 11)."""
        if id:
            s = self._get(id)
            adapter, adapter_id, dir, profile = s.adapter, s.adapter_id or "", s.dir, s.profile
            if not adapter_id:
                why = "a shell has no transcript" if not adapters.has_agent(adapter) else "its hook never reported one"
                raise RpcError(f"{id} carries no tool session id: {why} (design §4.5 screen 9)")
        elif not (adapter and adapter_id and dir):
            raise RpcError("transcript needs id, or adapter, adapter_id and dir (design §4.7)")
        try:
            fn = getattr(adapters.get(adapter), "read_transcript", None)
        except KeyError:
            raise RpcError(f"no adapter {adapter}") from None
        if fn is None:
            raise RpcError(f"the {adapter} adapter reads no transcript (design §4.3)")
        if before is not None and (isinstance(before, bool) or not isinstance(before, int) or before < 0):
            raise RpcError(f"before is a byte offset, not {before!r}")
        turns = max(1, min(int(turns or 20), TRANSCRIPT_TURNS_MAX))
        t = await asyncio.to_thread(fn, adapter_id, Path(dir), profile, before=before, turns=turns, raw=bool(raw))
        if t is None:
            raise RpcError(f"no transcript for {id or adapter_id}: the tool's file is not on {self.host}")
        return t.to_dict()

    async def rpc_paths(
        self, id: str | None = None, runs: list[str] | None = None, repo: str | None = None
    ) -> dict[str, Any]:
        """The Focus pane's file check (design §4.6 *A path in the pane is a link*, TD-501): for each
        run a row of the pane named, the real absolute path when it is a regular file anywhere on this
        host that this user can read (TD-688), its real path judged, so a symlink answers its target —
        else `None`: a directory, a missing or unreadable file, and a path `PATHS_PRIVATE` holds (a
        credential file stays text) alike, since the page needs no reason. A relative run is resolved
        against `dir`, `~` is this user's home. It stats and reads nothing else. Served
        here, on the record's host — a node's record reaches its node through `read` (`NODE_READS`).
        With `repo` in place of `id` (§4.6 *A path in the Inbox and the Queue is a link too*, TD-1108)
        a relative run resolves against that main checkout, answered only when its real path is one of
        the registry's; with neither, only an absolute or `~/` run is resolved, the rest `None`. An
        `id`-less ask has no address to forward by, so it is served where it arrives, the home.
        A read: never gated (§9 invariant 11)."""
        if not isinstance(runs, list) or not all(isinstance(r, str) for r in runs):
            raise RpcError("paths takes runs, a list of strings (design §4.6)")
        if len(runs) > PATHS_RUNS_MAX:
            raise RpcError(f"paths: {len(runs)} runs, past the {PATHS_RUNS_MAX} one row may ask about (design §4.6)")
        if long := [r for r in runs if len(r) > PATHS_RUN_CHARS]:
            raise RpcError(f"paths: a run of {len(long[0])} characters, past the {PATHS_RUN_CHARS} one may be")
        if id is not None and repo is not None:
            raise RpcError("paths takes id or repo, not both (design §4.6)")
        if id is not None:
            return {"paths": await asyncio.to_thread(_resolve_paths, runs, Path(self._get(id).dir))}
        if repo is not None:
            root = await asyncio.to_thread(_registered_checkout, repo)
            if root is None:
                raise RpcError(f"paths: {repo!r} is no checkout in this host's repos registry (design §4.6)")
            return {"paths": await asyncio.to_thread(_resolve_paths, runs, root)}
        bare = [r for r in runs if r.startswith(("/", "~/"))]
        got = await asyncio.to_thread(_resolve_paths, bare, Path.home())
        return {"paths": {r: got.get(r) for r in runs}}

    async def rpc_git_files(self, id: str, pick: str = "tree") -> dict[str, Any]:
        """The Focus Git card's pick (design §4.2 *The Git card's pick*, TD-856): the record's newest ten
        commits on `HEAD`'s first-parent line and the files of `pick` — `tree`, a sha of the ten, or
        `session` — read from git in `dir` on this host, on a pick and never on the tick. Served here, on
        the record's host — a node's record reaches its node through `read` (`NODE_READS`). A read: never
        gated (§9 invariant 11)."""
        s = self._get(id)
        if not isinstance(pick, str):
            raise RpcError(f"git_files: pick is tree, session or a sha, not {pick!r} (design §4.2)")

        def read() -> dict[str, Any]:
            return pick_files(s.dir, ledger_mod.default_ref(s.dir, timeout=5.0), pick)

        try:
            return await asyncio.to_thread(read)
        except GitPickError as e:
            raise RpcError(f"git_files: {e}") from None

    async def rpc_seen(self, id: str) -> dict[str, Any]:
        """A person looked at this session (a visible Focus, a card control used). The look records the
        turn it saw: `seen_at` becomes the larger of itself and the record's turn stamp (`turn_stamp`), the
        clock of the host that ran the turn, and stays as it is where no turn has ended; the UI reads a
        stamp past `seen_at` as the **unseen** mark (design §4.2 *Unseen*, TD-1228)."""
        s = self._find(id)  # a person may look at another host's session: `seen_at` is the home's
        if stamp := turn_stamp({"turn_at": s.turn_at, "since": s.since, "state": s.state}):
            s.seen_at = max(filter(None, (s.seen_at, stamp)))
        self._save(s)
        await self._push_changes()
        return self._view(s)

    async def rpc_set_mode(
        self, id: str, unattended: bool, pause_prompt: str | None = None, resume_prompt: str | None = None
    ) -> dict[str, Any]:
        """The mode toggle and `ao mode`. The usage gate's two texts ride along as the wrap-up's
        ride `set_stop` (design §6, TD-100): a session made unattended after its create would
        otherwise be gated with nothing to type. Given only when set; an empty one clears it."""
        s = self._find(id)  # the home's own copy of another host's record too (4a)
        if unattended and not adapters.has_agent(s.adapter):
            raise RpcError(
                f"{s.name} runs no agent: a shell is the person's and stays interactive "
                f"(design §4.3 A record with no agent, §4.8)"
            )
        if s.state == "scheduled" and not unattended:
            # the tick would start it from its launch record, unattended: the switch silently undone
            # and a policy's act on a session the person made interactive (§6 *Start time*, TD-328)
            raise RpcError(
                f"{s.name} has not started: a scheduled start is unattended — `ao at` moves it, Cancel "
                f"forgets it; switch it to interactive once it runs (design §6 Start time, §9 invariant 5)"
            )
        s.unattended = bool(unattended)
        if pause_prompt is not None:
            s.pause_prompt = str(pause_prompt).strip() or None
        if resume_prompt is not None:
            s.resume_prompt = str(resume_prompt).strip() or None
        self._save(s)
        # pushed now, as `set_stop` is: another tab's Focus re-attaches read-only or with the keyboard
        # at the press, not on the next tick (§4.6, TD-096)
        await self._push_changes()
        return self._view(s)

    async def rpc_keep(self, id: str) -> dict[str, Any]:
        """A size step up adopting a run-only member (design §4.9 *A team's size*, TD-1164): `run_only`
        cleared on the record and in its launch record, so a restart brings it back kept. A home-owned
        edit as `set_mode` is (§4.4a): on a node's member the home's copy takes it once the replica has,
        and the launch record is the home's alone."""
        s = self._find(id)  # the home's own copy of another host's record too (4a)
        s.run_only = False
        self._save(s)
        if self.mode != "node":
            path = paths.launch_dir() / f"{self._address(s)}.json"
            with contextlib.suppress(OSError, ValueError):
                launch = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(launch, dict) and launch.get("run_only"):
                    launch.pop("run_only")
                    self._write_launch(self._address(s), s, {k: v for k, v in launch.items() if k not in ("id", "at")})
        await self._push_changes()
        return self._view(s)

    async def rpc_set_stop(
        self, id: str, run_until: str | None = None, wrapup_prompt: str | None = None
    ) -> dict[str, Any]:
        """`ao until <session> <when>` (design §6, TD-026): set or clear a session's stop time.

        Acting, and gated as one: a stop time ends another session's run, which is the same act as
        `kill` with a delay on it. Passing no time clears it — an unattended session with no stop
        time is where this started, so clearing one is a decision worth being able to make out loud
        rather than by restarting the session.
        """
        s = self._find(id)  # the home's own copy of another host's record too (4a)
        when = _stop_time(run_until)  # a malformed time is an error before anything else is judged
        if when and not s.unattended:
            raise RpcError(f"{id} is interactive: a stop time is a policy, and policies leave it alone (§4.2)")
        if when != s.run_until:
            # A *new* time is a new run, so whatever was asked before is spent. Re-confirming the
            # same one is not: it used to reset this unconditionally, so a session already asked to
            # wrap up and sitting inside its grace would be asked again on the next tick — and,
            # because the ask happens before the grace check, touching the stop time repeatedly
            # deferred the forced kill indefinitely. That is the failure TD-026 gap 1 exists to
            # close, and the Focus control (TD-026, PR #147) put a button in front of it whose
            # pre-fill is exactly this value. Found in that PR's review.
            s.wrapup_sent_at = None
        s.run_until = when
        if wrapup_prompt is not None:
            s.wrapup_prompt = str(wrapup_prompt).strip() or None
        self._save(s)
        await self._push_changes()
        return self._view(s)

    async def _cancel_start(self, s: Session, reap: bool | str = True) -> dict[str, Any]:
        """A scheduled record cancelled (design §6 *Start time*): forgotten with its launch record, and
        its open questions closed with it, as a close does. The worktree its scheduling made is reaped
        under a close's tests (§4.1, TD-979); the record is forgotten, so a kept one is said in the reply."""
        await self._reap(s, reap)
        view = {**s.view(), "state": "closed", "cancelled": True}
        if s.worktree_kept:
            log.info("%s: the cancel kept its worktree %s: %s", s.id, s.dir, s.worktree_kept)
        self._asker_gone(s, self._address(s), how="cancelled")
        self._forget(s.id)
        log.info("%s: its scheduled start cancelled", s.id)
        await self._push_changes()
        return view

    async def rpc_set_start(self, id: str, start_at: str = "", caller: Any = None) -> dict[str, Any]:
        """`ao at <session> <when> | now` (design §6 *Start time*, §4.7, TD-152): move a scheduled
        start, or — with `now` — hand it to the tick's next pass. Acting, and gated as `set_stop` is:
        it starts another session's run. Refused on a record that is not `scheduled`: a live session
        already started."""
        s = self._find(id)
        if s.state != "scheduled":
            raise RpcError(f"{id} is {s.state}, not scheduled: a start time is for a record that has not started")
        if mail.as_person(caller, self._graph()):
            # a person's new time is a new start: a ceiling the failed starts reached, and the count
            # that reached it, are spent — as a person's own Resume starts rule 1's count again (§6)
            s.restart_ceiling = None
            s.restarts = [r for r in s.restarts if not (isinstance(r, dict) and r.get("why") == "start")]
        elif s.restart_ceiling:
            # at the ceiling the record is a person's (§6): a controller moving the time would retry
            # without bound, so a session is refused here and the count is left as it is
            raise RpcError(
                f"{id} reached the restart ceiling ({s.restart_ceiling.get('count')} failed starts): it is a "
                "person's now — a person's ao at spends the ceiling (design §6 Start time)"
            )
        if str(start_at).strip().lower() == "now":
            s.start_at = now_iso()
        else:
            s.start_at = _start_time(start_at, True, s.run_until)
            if not s.start_at:
                raise RpcError("set_start needs a time, or now (design §6 Start time)")
        self._save(s)
        await self._push_changes()
        return self._view(s)

    async def rpc_set_grants(
        self, id: str, add: list[str] | None = None, remove: list[str] | None = None
    ) -> dict[str, Any]:
        """`ao grant` / `ao revoke`, the Focus grants chip (design §4.8): edit `capabilities`. Takes
        effect on the target's next call — the gate reads the record, not a cached copy."""
        s = self._find(id)  # the home's own copy of another host's record too (4a)
        adding, removing = _grants(add or []), _grants(remove or [])
        s.capabilities = [g for g in GRANTS if (g in s.capabilities or g in adding) and g not in removing]
        self._save(s)
        await self._push_changes()
        return self._view(s)

    async def rpc_set_controllers(
        self, id: str, add: list[str] | None = None, remove: list[str] | None = None
    ) -> dict[str, Any]:
        """`ao control <controller> add|remove <session>`, the Focus controllers chip (design §4.8,
        TD-036): edit which sessions may act on this one. Gated on the *target* like `set_grants`,
        so a person always may and a session only if it already controls it — control is handed
        on, never seized; and never at all from a session onto an interactive target (§9
        invariant 5, TD-041 — `_gate` refuses it before this method runs), while a person may hand
        their own session to a controller deliberately. Takes effect on the next call the
        controller makes: the gate reads the record, not a cached copy."""
        s = self._find(id)  # the home's own copy of another host's record too (4a)
        # Stored as the record's own host addresses them (§4.4a, step 4a): bare for that host's
        # sessions, `id@host` for the rest — another host's record keeps its node's form here too.
        adding = [self._to_host(c, s.host) for c in _controllers(add or [])]
        removing = [self._to_host(c, s.host) for c in _controllers(remove or [])]
        if s.id in adding:
            raise RpcError(f"{s.id} cannot be its own controller: it could then drop the ones watching it")
        # One call naming an id in both `add` and `remove` drops it: remove wins, as it already
        # does for grants (`rpc_set_grants`'s `and g not in removing`). Two authority-editing RPCs
        # that disagree on the ambiguous call is how one of them eventually surprises someone, and
        # of the two answers the safe one is the one that takes authority away (review 2026-09-13).
        s.controllers = _controllers([c for c in s.controllers + adding if c not in removing])
        self._save(s)
        await self._push_changes()
        return self._view(s)

    async def rpc_progress(
        self,
        id: str,
        ref: str = "",
        status: str = "claimed",
        pr: int | None = None,
        why: str | None = None,
        source: str = "declared",
        force: bool = False,
        slice: bool = False,
        caller: Any = None,
    ) -> dict[str, Any]:
        """`ao progress claim|done|drop <ref>` (design §4.8): what this session set out to resolve
        and how it went. A report channel is **ungated** — any session may write any record's, the
        Org renders whichever are non-empty — and one reference is one entry, upserted in place.

        `status="none"` is `ao progress none --why` (design §4.9a): no reference and no entry, but
        `out_of_work: {at, why}` on the record. `status="restart"` is the third ending (§4.9a
        *A run that ends with work left*, TD-083): the same shape, setting
        `restart_wanted: {at, why, early?, repeat?, decided?}` — *my run is over and my lane is not*. They are the
        two writes on this channel that are not open to everyone — only the session itself may
        make either, declared, with a reason (§9 invariant 14) — and they refuse each other.

        A declared claim is a **lease** (§4.8, TD-056): refused while another live record holds an
        unexpired declared claim on the same reference, naming the holder; `force` claims anyway and
        the reply carries `lease_overridden`.

        `slice` with `status="done"` is `ao progress done <ref> --pr <n> --slice` (§4.8, §4.9a *A
        slice is work done*, TD-325): the PR is held in the declared claim's `slices` and the claim
        stays `claimed`, its status, `pr` and `why` as they were."""
        s = self._find(id)  # a node's session reports here (step 5): the field is the home's
        said = None
        if status == "done" and _pr(pr) is not None and _source(source) == "declared":
            # TD-637: the PR's checks read at the declaration, before anything is written
            said = await self._checks_at_done(s, _ref(ref), int(_pr(pr) or 0), slice)
        if slice:
            out = await self._slice(s, ref, status, pr, source)
            return {**out, "checks_said": said["line"]} if said and said["line"] else out
        if status in ("none", "restart"):
            if ref or pr is not None:
                raise RpcError(
                    f"progress {status} takes no reference and no PR, only "
                    f'why="{"the search that came up empty" if status == "none" else "why this run is over"}"'
                )
            return await self._ending(s, status, why, source, caller)
        if status not in PROGRESS_STATUSES:
            raise RpcError(
                f"unknown progress status {status!r}; statuses are: {', '.join(PROGRESS_STATUSES)}, none, restart"
            )
        entry = ProgressEntry(ref=_ref(ref), status=status, pr=_pr(pr), why=why, source=_source(source))
        if said and said["word"] == "unknown":
            entry.ci = "unknown"  # pending is refused at the declaration since TD-658: no new `ci: pending`
        new_claim = status == "claimed" and entry.source == "declared"
        if new_claim and (words := self._balance_refusal(s, entry.ref, caller)):
            raise RpcError(words, balance=self._balance_of(s))
        if new_claim and (words := self._settle_refusal(s, entry.ref)):
            raise RpcError(words)  # before the lease: `force` is about another session's claim, not this
        if new_claim and not force and (words := settle_mod.wait_refusal(self._ledger_entry(s, entry.ref))):
            raise RpcError(words)  # a wait's end the session may know: `force` passes it (§4.4, TD-716)
        if (
            new_claim
            and not force
            and (words := settle_mod.team_refusal(self._ledger_entry(s, entry.ref), s.team, s.name or s.id))
        ):
            raise RpcError(words)  # another team's entry, or one that needs a team: `force` passes it (§4.4, TD-730)
        holder = self._lease_holder(s, entry) if new_claim else None
        if holder is not None and not force:
            raise RpcError(
                f"{entry.ref} is claimed by {holder['session']} since {holder['at']} (a lease, design §4.8): pick "
                "another reference, or claim it anyway with --force",
                holder=holder,
            )
        claimed_at = next((e.at for e in s.progress if e.ref == entry.ref and e.status == "claimed"), None)
        applied = s.report_progress(entry)
        if applied and status == "done" and entry.source == "declared" and self.mode != "node":
            try:
                await self._seat_spend_done(s, entry.ref, claimed_at)  # the entry's reading outlives its record
            except Exception:  # noqa: BLE001 — the seat ledger's file never fails a report (§4.4 *Spend per seat*)
                log.exception("the seat ledger did not take the done of %s", entry.ref)
        if applied and status == "claimed" and entry.source == "declared":
            # a session that claims something went on after all — both endings are taken back
            # (§4.9a; `restart_wanted` since TD-083), and a controller must not act on a stale one
            s.out_of_work = s.restart_wanted = None
            s.lane_seen = None  # rule 6's memory goes with the declaration it was about (TD-195)
            if s.balance_refused and not self._balance_of(s):
                s.balance_refused = None  # the line cleared and the member claimed: nothing left to ring
        if applied and status == "dropped" and entry.source == "declared" and mail.as_person(caller, self._graph()):
            # §4.5a *Reports* → Drop, §4.10 (TD-150 slice 3): the session is told its lease went, by a
            # `system` note that wakes it as a person's act does — else it works on, holding nothing
            self._system_note(
                self._address(s),
                f"your claim on {entry.ref} was dropped by the person — the lease is gone; claim again if you "
                "still hold the work",
                wake="person",
            )
        out = await self._report(s, applied, entry)
        if holder is not None and applied:
            out["lease_overridden"] = holder
        if said and said["line"]:
            out["checks_said"] = said["line"]
        return out

    def _settle_refusal(self, s: Session, ref: str) -> str | None:
        """Why a declared claim on a ledger entry is refused because it settles or the person holds it
        (design §4.8 *A claim is a lease*, §4.4 *What settling withholds*, TD-710), read from the home's
        reading of the claimer's repo; None for a reference that is no ledger id, or a repo not read."""
        e = self._ledger_entry(s, ref)
        held = e.get("held") if isinstance(e, dict) else None
        by = self._presser_words(str(held.get("by") or "")) if isinstance(held, dict) else "the person"
        return settle_mod.claim_refusal(e, datetime.now(UTC), by)  # the presser's words (TD-1117)

    def _ledger_entry(self, s: Session, ref: str) -> dict[str, Any] | None:
        """Entry `ref` of the home's reading of the record's repo, marks and all; None for a reference
        that is no ledger id, or a repo not read."""
        if not ref.startswith("TD-"):
            return None
        entries = ((self._repos.get(s.repo or "") or {}).get("ledger") or {}).get("entries") or []
        return next((e for e in entries if isinstance(e, dict) and e.get("id") == ref), None)

    async def _pr_checks(self, s: Session, pr: int) -> dict[str, Any]:
        """PR `pr` read once for its checks (design §4.8 *A `done` with a PR is told what its checks
        read*, TD-637, TD-658): `gh pr view` from the record's checkout, off the loop, folded by
        `reports.at_done` against its base's required names in the repo reading — `{word, sha, failed,
        not_run, other, running, names, rollup, owner}`, or `{word: unknown, why}` for a read the home
        could not make. A failing required Actions job is judged by the reading's `jobs` for the PR when
        they are for this head, else read here (`reports.done_verdicts`, design §4.4 *A `done`'s read*,
        TD-686). One read for a `done` and for an `ask` carrying `pr`, so the two never disagree."""
        root = str(s.repo or "")
        if not root or not Path(root).is_dir():
            view: dict[str, Any] | str = "the record names no checkout here"
        else:
            view = await asyncio.to_thread(reports.pr_view, root, pr, GH_TIMEOUT)
        if isinstance(view, str):
            return {"word": "unknown", "why": view}
        line, why = None, None
        # a fork's PR is gated on the forge's CI alone: its precheck is the person's (TD-1285)
        open_ = str(view.get("state") or "").upper() == "OPEN" and not view.get("mergedAt")
        if open_ and not view.get("isCrossRepository"):
            line, why = await asyncio.to_thread(self._precheck_line, root, pr)
        if why:  # the PR read open: a slice on it is refused still (TD-1036)
            return {"word": "unknown", "why": why, "open": True}
        base = str(view.get("baseRefName") or "")
        reading = (self._repos.get(root) or {}).get("prs") or {}
        required = reading.get("required") or {}
        names = required.get(base) if isinstance(required.get(base), list) else None
        row = next((p for p in reading.get("open") or [] if isinstance(p, dict) and p.get("number") == pr), {})
        verdicts = await asyncio.to_thread(reports.done_verdicts, root, view, names, row.get("jobs"), GH_TIMEOUT)
        got = reports.at_done(view, names, verdicts, line is not None)
        if got.get("precheck_absent"):
            got["hint"] = line
        if got["word"] == "not_run":
            got["owner"] = reports.github_owner(row.get("url")) or reports.github_owner(
                await asyncio.to_thread(reports.git_origin, root)
            )
        return {**got, "names": names, "rollup": bool(view.get("statusCheckRollup"))}

    @staticmethod
    def _precheck_line(root: str, pr: int) -> tuple[str | None, str | None]:
        """Where the repo at `root` sets `precheck` (design §4.8, TD-1036) — `docs/cadence.toml` on
        `origin/<default>` in the registry checkout, as the gate on main reads it (§6 *Where `precheck`
        is read*) — the `precheck.py --pr <pr>` line to run, else None; `(None, why)` only for a file
        that does not parse, which leaves the checks unknown. A file not read (no such rev, a timeout)
        is no `precheck`: the fold runs as it did. Blocking: run it off the loop."""
        from sessionorc import board  # the checkout's default branch, as the pull reads it

        command, why = cadence_mod.precheck_command(root, f"origin/{board.default_branch(Path(root))}")
        if why and why.endswith("does not parse"):
            return None, why
        return (cadence_mod.precheck_typed(root, pr) if command else None), None

    @staticmethod
    def _not_run_refusal(pr: int, ref: str, got: dict[str, Any]) -> RpcError:
        """The refusal of a `done` on a head whose required checks never started (design §4.8, §4.4 *CI
        that never started is the person's*, TD-686): the PR, the head, the reason and the person."""
        why = got.get("not_run_why") or {}
        reason = "billing or spending limit" if why.get("kind") == "billing" else (why.get("reason") or "unknown")
        where = f" in {got['owner']}" if got.get("owner") else ""
        return RpcError(
            f"PR #{pr}'s checks never started on {got['sha'][:7]}: {reason}{where} — the person's to fix (the "
            f"Inbox says so); push nothing for it, report done again once CI runs, or drop the claim with "
            f'`ao progress drop {ref} --why "CI never ran"` and take other work',
            not_run=got["not_run"],
            sha=got["sha"],
        )

    @staticmethod
    def _not_green(pr: int, got: dict[str, Any], failed: str, running: str) -> RpcError | None:
        """The refusal for a head whose required checks failed (ending *fix them and <failed>*) or
        still run (ending *<running>*), TD-637 and TD-658 — or None when neither."""
        if got["word"] not in ("refused", "pending"):
            return None
        sha7 = got["sha"][:7]
        if got["word"] == "pending" and got.get("precheck_absent"):  # the precheck line, never `--watch` (TD-1036)
            run = f"run `{got['hint']}` (in the background), then {failed}"
            if got["running"] == [reports.PRECHECK_CONTEXT]:
                return RpcError(
                    f"PR #{pr}'s head {sha7} carries no {reports.PRECHECK_CONTEXT} — {run}",
                    running=got["running"],
                    sha=got["sha"],
                )
            running = run
        unknown = " — required set unknown, every check read" if got["names"] is None else ""
        if got["word"] == "refused":
            return RpcError(
                f"PR #{pr}'s required checks failed on {sha7}: {', '.join(got['failed'])}{unknown} — fix them "
                f"and {failed}",
                failed=got["failed"],
                sha=got["sha"],
            )
        return RpcError(
            f"PR #{pr}'s required checks are still running on {sha7}: {', '.join(got['running'])}{unknown} — {running}",
            running=got["running"],
            sha=got["sha"],
        )

    async def _checks_at_done(self, s: Session, ref: str, pr: int, slice: bool) -> dict[str, Any]:
        """What a declared `done` naming PR `pr` is told of its checks (design §4.8 *A `done` with a
        PR is told what its checks read, and refused until they are green*, TD-637, TD-658): `{word,
        line}` from `_pr_checks`. A required check red or still running on the head, or a `--slice`
        on a PR not merged, raises — nothing is written; a read the home could not make is *unknown*,
        never a refusal."""
        got = await self._pr_checks(s, pr)
        if slice and got.get("open"):
            raise RpcError(f"a slice is a merged PR — #{pr} is open")
        if got["word"] == "unknown":
            return {"word": "unknown", "line": f"PR #{pr}: checks unknown: {got['why']}"}
        word, sha7 = got["word"], got["sha"][:7]
        if slice and word != "merged":
            raise RpcError(f"a slice is a merged PR — #{pr} is {'closed unmerged' if word == 'closed' else 'open'}")
        again = f"report done again (ao progress done {ref} --pr {pr})"
        if refusal := self._not_green(pr, got, again, f"report done once they pass (`gh pr checks {pr} --watch`)"):
            raise refusal
        if word == "not_run":  # after a real failure, before one still running (TD-686)
            raise self._not_run_refusal(pr, ref, got)
        parts = {
            "merged": "merged",
            "closed": "closed unmerged",
            "green": f"checks green on {sha7}" if got["rollup"] else "no checks",
        }
        line = f"PR #{pr}: {parts[word]}" if word != "merged" else ""
        if got["other"]:
            line += f"; not required, failed: {', '.join(got['other'])}"
        if got["names"] is None and word == "green":
            line += "; required set unknown — every check read"
        return {"word": word, "line": line}

    async def _checks_at_ask(self, sender: str, kind: str, pr: Any) -> str | None:
        """An `ask` carrying `pr`, sent by a session, read as a `done` naming that PR is (design §4.9b
        *The reader*, TD-658): refused while a required check failed or still runs on the head —
        nothing is sent — and the line *checks unknown: <why>* for a read the home could not make,
        which sends. A person's ask, an ask with no `pr`, and a shape `_msg` refuses are not read."""
        if mail.is_person(sender) or kind != "ask" or isinstance(pr, bool) or not isinstance(pr, int) or pr < 1:
            return None
        s = self._graph().get(self._addr(sender))
        if s is None:
            return None  # `_msg` says it has no record of the sender
        got = await self._pr_checks(s, pr)
        if got["word"] == "unknown":
            return f"PR #{pr}: checks unknown: {got['why']}"
        if refusal := self._not_green(pr, got, "ask again", f"ask again once they pass (`gh pr checks {pr} --watch`)"):
            raise refusal
        if got["word"] == "not_run":  # §4.9b names no refusal for it: the ask sends, saying so (TD-686)
            reason = (got.get("not_run_why") or {}).get("reason") or "unknown"
            return f"PR #{pr}: checks never started on {got['sha'][:7]}: {reason}"
        return None

    async def _slice(self, s: Session, ref: str, status: str, pr: int | None, source: str) -> dict[str, Any]:
        """A slice declared (TD-325): refused but for `done` with a PR, declared, on a reference the
        record holds a declared claim on — a slice is a PR of an entry still held."""
        ref, number = _ref(ref), _pr(pr)
        if status != "done" or _source(source) != "declared":
            raise RpcError("--slice goes with `ao progress done <ref> --pr <n>`, declared by the session itself")
        if number is None:
            raise RpcError(f"a slice is a merged PR: ao progress done {ref} --pr <n> --slice")
        claim = next((e for e in s.progress if e.ref == ref and e.source == "declared" and e.status == "claimed"), None)
        if claim is None:
            raise RpcError(
                f"{ref} holds no claim of yours: a slice is a PR of an entry you still hold — "
                f"ao progress claim {ref} first, or report the entry finished with a plain done"
            )
        out = await self._report(s, claim.add_slice(number, "declared"), claim)
        out.pop("refused", None)  # held already is no refusal: the slice is on the claim either way
        out["slice"] = f"#{number} held as a slice of {ref}; {ref} stays claimed — the last slice is a plain done"
        return out

    def _balance_of(self, s: Session) -> dict[str, Any] | None:
        """The balance mark of `s`'s team if `s` is one it refuses (design §6 *Balance*, TD-239): an
        unattended record that is no seat, on a team the home's `host` record marks — read there by
        team, never from a repo's reading, since a `review` crossing may name no repo. A node's member is
        checked here too: `progress` is a report, which its node forwards to the home (`modes.REPORTS`);
        only a node cut off from the home, which refuses reports outright, checks nothing (§6)."""
        if not s.team or not s.unattended or s.seat is not None:
            return None
        mark = ((self._host_rec.get("teams") or {}).get(s.team) or {}).get("balance")
        return mark if isinstance(mark, dict) and mark.get("crossed") else None

    def _balance_refusal(self, s: Session, ref: str | None, caller: Any = None) -> str | None:
        """The words refusing `s` a new claim on `ref` — or, with `ref` None, its `none` — while its
        team is over its line; None when it passes. A renewal (a claim `s` already holds on `ref`, its
        branch's derived one included: the work is in hand) and
        a pull request as the reference pass: finishing one is what brings the count down. A refusal
        of the session's own word is kept on the record (`balance_refused`) so the clearing can ring
        it; one of another's write on its record (a person's `--id`) is not, since the member never
        tried and has nothing to be rung about."""
        mark = self._balance_of(s)
        if mark is None:
            return None
        if ref is not None:
            if ref.startswith("#"):
                return None
            if any(e.ref == ref and e.status == "claimed" for e in s.progress):  # declared or from its branch
                return None
        if self._is_self(s, caller):
            s.balance_refused = {"at": now_iso(), "ref": ref}
            self._save(s)
        return balance_mod.refusal(s.team, mark)

    def _lease_holder(self, s: Session, entry: ProgressEntry) -> dict[str, str] | None:
        """The other live record holding an unexpired declared claim on `entry.ref`, if any. Read and
        acted on in one loop step, so two claims a moment apart get one grant and one refusal."""
        now = datetime.now(UTC)
        for o in self._graph().values():
            if o.id == s.id or o.state in ("exited", "closed"):
                continue
            for e in o.progress:
                if e.ref == entry.ref and e.status == "claimed" and e.source == "declared":
                    with contextlib.suppress(ValueError):
                        if now - _parse(e.at) < LEASE_TTL:
                            return {"session": o.id, "at": e.at}
        return None

    async def _ending(self, s: Session, status: str, why: str | None, source: str, caller: Any) -> dict[str, Any]:
        """The two ways a run ends by the session's own word (design §4.9a): **`none`** — I
        searched and there is nothing I may pick — and **`restart`** — my run is over and my lane
        is not (TD-083). Both are facts about the session, not states, both are written only by
        the session they are about (§9 invariant 14), and **they refuse each other**: a session is
        out of work or it wants another run at it, never both.

        A **third** ending was missing until 2026-09-20 and its absence parked a team for ninety
        minutes: a grinder ended a long run on purpose with work still on the ledger, and could
        say so only in prose — it was not out of work, and a Claude Code `/exit` does not leave,
        so it was never `exited` and no rule of its manager's fired."""
        word = "out of work" if status == "none" else "a restart"
        if _source(source) != "declared":
            raise RpcError(f"{word} is declared, never derived (design §9 invariant 14)")
        if not self._is_self(s, caller):
            said = "declare itself out of work" if status == "none" else "declare a restart of itself"
            raise RpcError(
                f"only {s.id} may {said}: it is the session's own word about its own run (design §9 invariant 14)"
            )
        if not (why or "").strip():
            reason = "the search that came up empty" if status == "none" else "why this run is over"
            raise RpcError(
                f'ao progress {status} needs --why "<{reason}>": a declaration without its '
                "reason is refused (design §4.9a)"
            )
        if owed := s.owed():
            # Design §4.10 *Outcomes*: the person answered; what became of it is owed before this
            # session stops. `dropped` is an honest way out, and one line settles each. A restart
            # owes them for a reason of its own: the fresh run does not carry the conversation the
            # debt was made in, so nobody is left who can report it.
            raise RpcError(
                f"{s.id} owes {len(owed)} outcome{'s' if len(owed) != 1 else ''} to the person: report each with "
                f'ao msg person --outcome done|blocked|dropped "<one line>" --for <id> before declaring '
                f"{word} — {', '.join(owed)} (design §4.9a, §4.10 *Outcomes*)",
                owed=owed,
            )
        if unread := s.unread():
            # Design §4.9a (TD-072, TD-141): winding down is the last moment anyone reads this inbox,
            # and what is unread at it is a `note` nobody triaged or an `ask` whose sender waits on a
            # run about to end. Reading is the triage — `ao inbox` marks mail read (§4.10) — and a
            # restart is refused alike: the next run holds nothing of this inbox it did not read.
            # After the owed check, so a session with both is told the one it clears first.
            raise RpcError(
                f"{s.id} has {unread} unread message{'s' if unread != 1 else ''}: read them with `ao inbox` and "
                f"answer what needs answering before declaring {word} (design §4.9a)",
                unread=unread,
            )
        other = "restart_wanted" if status == "none" else "out_of_work"
        if getattr(s, other):
            said = "wants a restart" if other == "restart_wanted" else "is out of work"
            raise RpcError(
                f"{s.id} already {said} (since {getattr(s, other)['at']}): a session is out of work or it wants "
                "another run at it, never both — claim something to take that back (design §4.9a)"
            )
        if status == "none" and (words := self._balance_refusal(s, None, caller)):
            # a member refused a claim is not out of work (§6 *Balance*): its team idles, never winds down
            raise RpcError(words, balance=self._balance_of(s))
        if status == "none":
            s.out_of_work = {"at": now_iso(), "why": why.strip()}
            s.balance_refused = None  # taken, so the mark has gone: nothing left to ring
            s.lane_seen = None  # a second `none` is a declaration like the first: the tick looks afresh
        else:
            # The word stands whenever it is said — it is the session's — but one said inside
            # `RESTART_EARLY` of this record's own start is marked, and a controller does not act
            # on it: a run that is over before it began did not run out of context. The bound is
            # applied here because the home holds the start time; the controller reads a field.
            mark: dict[str, Any] = {"at": now_iso(), "why": why.strip()}
            # Early is read from the record, not from the clock alone (§4.9a, TD-249): a run that
            # reported new work is not one that never began, and one that reports only what an
            # earlier run did, or leaves a claim a third time, is the person's whenever it says so.
            # A restart its changed brief asked for (§6 rule 7) is neither: the run is not over on
            # its own account, and rule 2 is what brings the new brief; nor is one its team's changed flow
            # asked for (§4.9c *Switching*)
            reading = agent_common._restart_reading(s, datetime.now(UTC))
            if s.brief_changed or s.relaunch:
                reading = {"early": False, "repeat": None, "words": None}
            if reading["early"]:
                mark["early"] = True
                mark["decided"] = reading["words"]  # the row's, the card's and `ao status -v`'s words
            if reading["repeat"]:
                mark["repeat"] = reading["repeat"]
            s.restart_wanted = mark
            out = await self._report(s, True, None)
            if reading["words"]:
                out["decided"] = reading["words"]  # the reply names what decided it; the record keeps the fields
            return out
        return await self._report(s, True, None)

    async def rpc_doing(self, id: str, text: str = "", clear: bool = False, caller: Any = None) -> dict[str, Any]:
        """`ao doing "<line>"` (design §4.8, the third report channel, TD-074): one line, the
        session's own word for what it is doing now. `doing: {text, at}` on the record — a value
        beside the entry lists, as `out_of_work` is, so the last line replaces the one before and
        `--clear` empties it.

        Ungated like the other channels, and, like `out_of_work`, only the session itself may write
        it (§9 invariant 14): it is *the session says*, and a lead describing a member would be
        second-hand. One line (a newline ends it), control bytes stripped as a tail's are, capped at
        200 characters; a line that cleans to nothing is refused. Nothing derives it, nothing keys
        on it and no wake fires on it — it is shown, never acted on, and an exit leaves it in
        place."""
        s = self._find(id)  # a node's session reports here (step 5): the field is the home's
        if not self._is_self(s, caller):
            raise RpcError(
                f"only {s.id} may say what it is doing: it is the session's own word (design §9 invariant 14)"
            )
        if clear:
            s.doing = None
        else:
            line = _clean(str(text or "").split("\n", 1)[0]).strip()
            if not line:
                raise RpcError('ao doing needs a line: `ao doing "<what you are doing now>"`, or --clear (design §4.8)')
            s.doing = {"text": line, "at": now_iso()}
        self._save(s)
        if s.doing and s.team:
            # the doing log (§4.8, TD-176 slice 2): the call, beside the record's latest line — what a
            # team card's Doing facet and the Repo page draw; nothing else reads it
            entry = {"team": s.team, "id": s.id, "text": s.doing["text"], "at": s.doing["at"]}
            self.doing_log.append(entry)
            await self._broadcast({"event": "doing", "team": s.team, "entry": entry})
        await self._push_changes()
        return self._view(s)

    def _rounds_log(self, s: Session) -> Path:
        """The record's round log (§4.8, TD-191): keyed by its name in its repo, never by the run."""
        return paths.rounds_log(naming.base_id(s.dir, s.repo, s.name))

    async def rpc_log(self, id: str, text: str = "", caller: Any = None) -> dict[str, Any]:
        """`ao log "<line>"` (design §4.8 *A session's round log*, TD-191): one line, stamped to the
        minute, appended to the session's round log beside its run logs — the manager's memory
        across runs, never a report and never a commit. Only the session itself writes it (§9
        invariant 14, as `doing`): a person may not, since it is the session's own memory. Served
        where the session runs, as the run log is: a node writes its own. A line is text, never a
        control (TD-071): control bytes stripped, one line, capped at `ROUND_LINE_CAP`."""
        s = self._get(id)
        if not self._is_self(s, caller):
            raise RpcError(f"only {s.id} may write its round log: it is the session's own memory (design §4.8)")
        line = _clean(str(text or "").split("\n", 1)[0], ROUND_LINE_CAP).strip()
        if not line:
            raise RpcError('ao log needs a line: `ao log "<what this round did>"` (design §4.8)')
        entry = {"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "text": line}
        path = self._rounds_log(s)

        def append() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(f"{entry['at']} {line}\n")

        await asyncio.to_thread(append)
        return entry

    async def rpc_log_tail(self, id: str, n: int = 20) -> list[dict[str, str]]:
        """`ao log --tail n` (design §4.8, TD-191): the last `n` lines of the session's round log as
        `{at, text}`, oldest first; empty when it has none. A read, ungated (§9 invariant 11), and
        routed to the node a record runs on, whose disk holds the file."""
        s = self._get(id)
        path = self._rounds_log(s)
        n = max(0, min(int(n), 1000))

        def read() -> list[str]:
            try:
                return path.read_text(encoding="utf-8", errors="replace").splitlines()
            except FileNotFoundError:
                return []

        lines = [x for x in await asyncio.to_thread(read) if x.strip()]
        out = []
        for x in lines[-n:] if n else []:
            at, _, text = x.partition(" ")
            out.append({"at": at, "text": text})
        return out

    async def rpc_finding(
        self, id: str, ref: str, priority: str | None = None, source: str = "declared"
    ) -> dict[str, Any]:
        """`ao finding <ref> [--priority …]` (design §4.8): a reference this session filed on the
        side. Ungated like `progress`, and upserted by reference the same way."""
        s = self._find(id)  # a node's session reports here (step 5): the field is the home's
        entry = FindingEntry(ref=_ref(ref), priority=priority, source=_source(source))
        return await self._report(s, s.report_finding(entry), entry)

    async def _report(self, s: Session, applied: bool, entry: Any) -> dict[str, Any]:
        """Save and announce a report entry the record accepted. A refused one (§9 invariant 10: a
        `derived` or `scraped` entry over a `declared` one) is not an error — the caller gets the
        record as it stands, with `refused` naming the entry that did not land."""
        if applied:
            self._save(s)
            await self._push_changes()
        out = self._view(s)
        if not applied:
            out["refused"] = entry.to_dict()
        return out

    # -- helpers ---------------------------------------------------------------------------------

    def _gate(self, caller: Any, method: str, params: dict[str, Any]) -> None:
        """`mail.act_gate` over this agent's records (design §4.8, §9 invariants 5 and 11): a
        function over a record map, so a node can forward and the home can answer (§4.4a)."""
        if method == "create" and params.get("capabilities"):
            _grants(params["capabilities"])  # an unknown grant name is refused before the gate reads it
        graph = self._graph()
        reason = mail.act_gate(graph, caller, method, params, controllers=self._ctl)
        if reason:
            raise RpcError(reason)
        if method == "send" and not mail.as_person(caller, graph) and params.get("id") != caller:
            # design §6 *Usage gate*: while gated, a controller's send is refused here, at the home,
            # read from the record's `gated` — a node-owned field, so a replica carries it. A person's
            # own send is not (§9 invariant 11): the way past the gate is a person's.
            target = graph.get(self._addr(params.get("id", "")))
            if target is not None and (g := target.gated):
                raise RpcError(
                    f"{params.get('id')} is paused by the usage gate ({g.get('profile')} {g.get('label')} "
                    f"{g.get('pct')}% >= {g.get('line')}%): a controller's send waits for the resume (design §6)"
                )

    def _addr(self, address: Any) -> str:
        """One normaliser for every id on the way in (design §4.4a, TD-057 step 1): a session on
        this host is stored bare, another host's as `id@host`."""
        return naming.qualify(str(address), local=self.host)

    def _is_self(self, s: Session, caller: Any) -> bool:
        """Whether `caller` is the session `s` itself (design §9 invariant 14, TD-302): its address in
        this host's form — a node's session calls the home as `id@<node>` while its record's id is
        bare. The person never is."""
        return caller is not None and not mail.is_person(caller) and self._addr(caller) == self._address(s)

    def _get(self, sid: str) -> Session:
        try:
            return self.sessions[sid]
        except KeyError:
            rid, host = naming.split_address(sid)
            if host and rid in self.remote.get(host, {}):
                raise RpcError(f"{sid} runs on {host}: this call does not cross the link") from None
            raise RpcError(f"no session {sid}") from None

    def _find(self, sid: str) -> Session:
        """A record by id or by address — this host's, or another host's as the home holds it. For
        reads and for what the home owns; `_get` is for everything that touches a pane."""
        rid, host = naming.split_address(sid)
        if host and host != self.host:
            try:
                return self.remote[host][rid]
            except KeyError:
                raise RpcError(f"no session {sid}") from None
        return self._get(rid)

    def _save(self, s: Session) -> None:
        (self.store if s.host == self.host else self._remote_store(s.host)).save(s)

    def _remote_store(self, host: str) -> SessionStore:
        if host not in self._remote_stores:
            self._remote_stores[host] = SessionStore(paths.remote_dir(host))
        return self._remote_stores[host]


async def serve_until_signal(agent: HostAgent, sock: Path | None = None) -> None:
    """Run `agent.serve()` until SIGINT or SIGTERM.

    The signal cancels the serve task rather than stopping the loop, so `serve()`'s `finally`
    (cancel the ticker, unlink the socket file) runs while the loop is still alive and the
    process ends without asyncio's "Task was destroyed but it is pending!" (TD-024).
    """
    # Run this under `asyncio.run`: its shutdown awaits every task still on the loop (the
    # cancelled ticker, a live usage refresh), which is what keeps them from being destroyed pending.
    task = asyncio.ensure_future(agent.serve(sock))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)
    try:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shiftlead-agent", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the host agent (foreground)")
    sub.add_parser("rpc", help="stdin/stdout JSON-lines bridge to the local socket (used over ssh)")
    lk = sub.add_parser(
        "link",
        help="a node's link into this home: the forced command of the node's key in authorized_keys (design §4.4a)",
    )
    lk.add_argument("--host", default="", help="the node's host name — set in authorized_keys, never by the node")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.cmd == "serve":
        # `SHIFTLEAD_TMUX_SOCKET` names a private tmux server (TD-298), as the tests and `scripts/look_home.py`
        # use: a scratch home's agent never lists or drives the default server's sessions.
        tmux = Tmux(socket_name=os.environ.get("SHIFTLEAD_TMUX_SOCKET") or None)
        asyncio.run(serve_until_signal(HostAgent(tmux=tmux)))
        return 0
    if args.cmd == "rpc":
        from sessionorc.client import bridge_stdio

        return asyncio.run(bridge_stdio())
    if args.cmd == "link":
        return asyncio.run(link.bridge(args.host))
    return 2


if __name__ == "__main__":
    sys.exit(main())
