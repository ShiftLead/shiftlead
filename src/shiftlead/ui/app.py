"""The shiftlead web UI (design §4.5): server-rendered pages, one `/events` websocket per tab
pushing rendered cards, one `/term/<id>` websocket per open Focus terminal. Phase 1: the local
host only, from `hosts.yml`'s `local` entry; ssh transport arrives in phase 2.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import contextvars
import functools
import gzip
import html
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any
from urllib.parse import parse_qsl, urlencode

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from markupsafe import Markup

from sessionorc import gitinfo, hosts, mail, naming, paths
from sessionorc import ledger as ledger_mod
from sessionorc import settle as settle_mod
from sessionorc.agent_common import PATHS_RUN_CHARS, PATHS_RUNS_MAX
from sessionorc.client import AgentError, AgentUnavailable, LocalClient
from sessionorc.containers import attach_argv_in, container_nodes
from sessionorc.models import (
    GRANTS,
    PERSON,
    has_control,
    permission_entry,
    start_note,
    stop_note,
)
from sessionorc.queue import TD_REF, card_entries, qid
from sessionorc.store import kept as doing_kept
from shiftlead import org as orgmod
from shiftlead import profiles as profiles_mod
from shiftlead import repoconfig, teamrun, teams
from shiftlead import review as reviewmod
from shiftlead.cli import stop_time as clistop

from . import cards as cards_mod
from . import help as helpmod
from . import inbox as inbox_mod
from . import repo_board, timing, uiconf
from . import settings_page as setmod
from .cards import (  # re-exported: routes, templates and tests read these from the app (TD-196)
    BRANCH_SHOWN,  # noqa: F401
    COUNT_ORDER,  # noqa: F401
    DEAD,  # noqa: F401
    DEFS_TTL,  # noqa: F401
    FLOW_ACTS,  # noqa: F401
    FLOW_RENAMES,  # noqa: F401
    FLOWS,  # noqa: F401
    NO_TEAM,  # noqa: F401
    NODE_RESTART,  # noqa: F401
    SHELL_CMD_CUT,  # noqa: F401
    STATE_CLASS,  # noqa: F401
    STATE_ICON_CLASSES,  # noqa: F401
    _clock,  # noqa: F401
    _count,  # noqa: F401
    _declared,  # noqa: F401
    _first_line,  # noqa: F401
    _middle,  # noqa: F401
    alarm_note,  # noqa: F401
    alarm_to_view,  # noqa: F401
    alarm_view,  # noqa: F401
    alarm_words,  # noqa: F401
    answerable,  # noqa: F401
    brief_changed_view,  # noqa: F401
    brief_unsent,  # noqa: F401
    card_order,  # noqa: F401
    card_slot,  # noqa: F401
    closed_keep,  # noqa: F401
    flow_mark,  # noqa: F401
    gated_view,  # noqa: F401
    group_place,  # noqa: F401
    held_words,  # noqa: F401
    host_volatile,  # noqa: F401
    next_act,  # noqa: F401
    pill_title,  # noqa: F401
    pr_repo,  # noqa: F401
    prompt_line,  # noqa: F401
    prs_waiting,  # noqa: F401
    ready_to_close,  # noqa: F401
    record_editor,
    repo_pr_marks,
    restarted_view,  # noqa: F401
    review_wait,  # noqa: F401
    seat_occupant,  # noqa: F401
    shell_cmd,  # noqa: F401
    shells_of,  # noqa: F401
    state_counts,  # noqa: F401
    state_icons,  # noqa: F401
    subagent_held,  # noqa: F401
    suspended_note,  # noqa: F401
    swept_words,  # noqa: F401
    terminal_only,  # noqa: F401
    unseen_count,  # noqa: F401
    view,  # noqa: F401
    waiting_view,  # noqa: F401
    waits_of,
)
from .common import (  # re-exported: routes, templates and tests read these from the app (TD-196)
    _DICT_NAMES,  # noqa: F401
    GRANT_NOTES,  # noqa: F401
    HERE,  # noqa: F401
    ICON_TTL,  # noqa: F401
    METERED_KINDS,  # noqa: F401
    NEAR_CAP,  # noqa: F401
    NO_CONTROLLERS,  # noqa: F401
    NO_GRANTS,  # noqa: F401
    PLACE_TTL,  # noqa: F401
    PLACE_WAIT,  # noqa: F401
    TOPBAR_TITLES,  # noqa: F401
    UNDESCRIBED_GRANT,  # noqa: F401
    USAGE_AGED,  # noqa: F401
    USAGE_FRESH,  # noqa: F401
    USAGE_SOURCE,  # noqa: F401
    USAGE_UNKNOWN,  # noqa: F401
    USAGE_WHY,  # noqa: F401
    WRAPUP_PROMPT,  # noqa: F401
    _age,  # noqa: F401
    _aged,  # noqa: F401
    _amount_says,  # noqa: F401
    _as_session_id,  # noqa: F401
    _countdown,  # noqa: F401
    _getattr,  # noqa: F401
    _icon_cache,  # noqa: F401
    _instant,  # noqa: F401
    _iso,  # noqa: F401
    _jinja_getattr,  # noqa: F401
    _left,  # noqa: F401
    _look_for,  # noqa: F401
    _metered_chip,  # noqa: F401
    _money,  # noqa: F401
    _pace_says,  # noqa: F401
    _place_asking,  # noqa: F401
    _place_cache,  # noqa: F401
    _projected,  # noqa: F401
    _reserve_why,  # noqa: F401
    _short_age,  # noqa: F401
    _str_list,  # noqa: F401
    _Templates,  # noqa: F401
    _usage_hover,  # noqa: F401
    _usage_line,  # noqa: F401
    _usage_profiles,  # noqa: F401
    build_chip,  # noqa: F401
    card_shape,  # noqa: F401
    card_whole,  # noqa: F401
    checkout_of,  # noqa: F401
    close_state,  # noqa: F401
    editor_file,  # noqa: F401
    editor_file_link,  # noqa: F401
    editor_link,  # noqa: F401
    host_name,  # noqa: F401
    identity_note,  # noqa: F401
    ledger_link,
    live_divider,  # noqa: F401
    live_unknown,  # noqa: F401
    log,  # noqa: F401
    md,  # noqa: F401
    node_banner,  # noqa: F401
    node_org_note,  # noqa: F401
    org_here,  # noqa: F401
    page_origin,  # noqa: F401
    paths_ctx,  # noqa: F401
    promote_reading,  # noqa: F401
    repos_of,  # noqa: F401
    restart_note,  # noqa: F401
    role_icons,  # noqa: F401
    role_prompts,  # noqa: F401
    rpc,  # noqa: F401
    shaped,  # noqa: F401
    start_fields,  # noqa: F401
    static_url,  # noqa: F401
    stop_fields,  # noqa: F401
    suggested_answers,  # noqa: F401
    team_brief_ids,
    team_reader,  # noqa: F401
    teams_for_form,  # noqa: F401
    teams_view,  # noqa: F401
    templates,  # noqa: F401
    usage_accounts,  # noqa: F401
    usage_age,  # noqa: F401
    usage_chip,  # noqa: F401
    usage_clock,  # noqa: F401
    usage_read,  # noqa: F401
    vscode_url,  # noqa: F401
    with_lines,  # noqa: F401
)
from .counts import CountsKeeper
from .fanout import FAILED, SAID_MAX, Every, Fanout, OpenRate, Stream
from .inbox import (  # re-exported: routes, templates and tests read these from the app (TD-196)
    _FIND_EDGE,  # noqa: F401
    _REPO_REF,  # noqa: F401
    BOARD_ACTS,  # noqa: F401
    BOARD_WAIT_DAYS,  # noqa: F401
    CI_BILLING_REASON,  # noqa: F401
    GH_USER_TTL,  # noqa: F401
    GH_USER_WAIT,  # noqa: F401
    INBOX_SECTIONS,  # noqa: F401
    LOOK_KINDS,  # noqa: F401
    NEEDS_YOU_ROWS,  # noqa: F401
    ORG_BILLING,  # noqa: F401
    OWING_CLOSES,  # noqa: F401
    OWING_KINDS,  # noqa: F401
    PERSON_ASK_KINDS,  # noqa: F401
    PULLS,  # noqa: F401
    RAIL_KIND_NAMES,  # noqa: F401
    RAIL_KINDS,  # noqa: F401
    RAIL_NO_TEAM,  # noqa: F401
    RAIL_SECTION_NAMES,  # noqa: F401
    RAIL_SECTIONS,  # noqa: F401
    RAIL_UNDER,  # noqa: F401
    RESTART_SUBJECTS,  # noqa: F401
    SHOT_DIR,  # noqa: F401
    SHOT_NAME,  # noqa: F401
    SHOT_TTL,  # noqa: F401
    SHOT_WAIT,  # noqa: F401
    SHOTS_MAX,  # noqa: F401
    STATE_SUBJECTS,  # noqa: F401
    STOPPED_BY,  # noqa: F401
    USER_BILLING,  # noqa: F401
    WORK_IDS,  # noqa: F401
    WORKS,  # noqa: F401
    _added_words,  # noqa: F401
    _ahead_words,  # noqa: F401
    _answered_of,  # noqa: F401
    _board_holder,  # noqa: F401
    _board_named,  # noqa: F401
    _board_order,  # noqa: F401
    _board_split,  # noqa: F401
    _civil,  # noqa: F401
    _decided,  # noqa: F401
    _entry_open,  # noqa: F401
    _find_text,  # noqa: F401
    _gh_user_type,  # noqa: F401
    _gh_user_type_read,  # noqa: F401
    _needs_key,  # noqa: F401
    _next_due,  # noqa: F401
    _order_teams,  # noqa: F401
    _orphan_held,  # noqa: F401
    _outcome_of,  # noqa: F401
    _owing,  # noqa: F401
    _parts_text,  # noqa: F401
    _pr_parts,  # noqa: F401
    _rail_teams,  # noqa: F401
    _resolved,  # noqa: F401
    _same_ref,  # noqa: F401
    _shot_host_down,  # noqa: F401
    _shot_on_host,  # noqa: F401
    _shot_on_origin,  # noqa: F401
    _shot_seen,  # noqa: F401
    _subject_of,  # noqa: F401
    _team_wound,  # noqa: F401
    _trail_rows,  # noqa: F401
    _with_subject,  # noqa: F401
    billing_url,  # noqa: F401
    board_answered,  # noqa: F401
    board_body,  # noqa: F401
    board_card,  # noqa: F401
    board_choices,  # noqa: F401
    board_detail,  # noqa: F401
    board_due_now,  # noqa: F401
    board_head,  # noqa: F401
    board_horizon,  # noqa: F401
    board_line,  # noqa: F401
    board_reading,
    board_rows,  # noqa: F401
    board_standing,  # noqa: F401
    board_standings,  # noqa: F401
    board_subject_text,  # noqa: F401
    board_text,  # noqa: F401
    board_waiting_on,  # noqa: F401
    board_waits,  # noqa: F401
    cadence_marks,  # noqa: F401
    ci_not_run_kinds,
    ci_not_run_rows,
    find_matches,  # noqa: F401
    find_words,  # noqa: F401
    handed_rows,  # noqa: F401
    held_mark,  # noqa: F401
    horizon_left,
    horizon_of,  # noqa: F401
    idle_open_mark,  # noqa: F401
    inbox_sections,  # noqa: F401
    kind_subject,  # noqa: F401
    lanes_hold,  # noqa: F401
    lanes_rows,  # noqa: F401
    ledger_for_you,  # noqa: F401
    ledger_rows,  # noqa: F401
    live_look,  # noqa: F401
    look_pair,  # noqa: F401
    look_review,  # noqa: F401
    look_shots,  # noqa: F401
    origin_case,  # noqa: F401
    origin_firsts,  # noqa: F401
    origin_note,  # noqa: F401
    promote_rows,  # noqa: F401
    pull_tail,  # noqa: F401
    rail_counts,  # noqa: F401
    rail_kind,  # noqa: F401
    rail_picks,  # noqa: F401
    rail_rows,  # noqa: F401
    red_pr_rows,
    restart_mark,  # noqa: F401
    restart_subject,  # noqa: F401
    review_pr,  # noqa: F401
    row_find,  # noqa: F401
    row_subject,  # noqa: F401
    shot_bytes,  # noqa: F401
    shot_root,  # noqa: F401
    state_kind,  # noqa: F401
    state_rows,  # noqa: F401
    unclosed_mark,  # noqa: F401
    with_standings,
    work_finished,  # noqa: F401
    work_held,  # noqa: F401
    work_ids,  # noqa: F401
    work_note,  # noqa: F401
    work_questions,  # noqa: F401
    work_rows,  # noqa: F401
    work_started,  # noqa: F401
)
from .org import (  # re-exported: routes, templates and tests read these from the app (TD-196)
    COMPLETED_HOVER,  # noqa: F401
    COMPLETED_ROWS,  # noqa: F401
    COMPLETED_WORD,  # noqa: F401
    DOER_WIDTH,  # noqa: F401
    FACETS,  # noqa: F401
    HEADS_EVERY,  # noqa: F401
    HOLDERS_WIDTH,  # noqa: F401
    KIND_BARS,  # noqa: F401
    LEDGER_VIEWS,  # noqa: F401
    LIGHT_KEYS,
    MOTION_PRIORITIES,  # noqa: F401
    PHASES,  # noqa: F401
    PRIORITY_BARS,  # noqa: F401
    REF_WIDTH,  # noqa: F401
    ROLLUP_CLS,  # noqa: F401
    ROLLUP_ROWS,  # noqa: F401
    ROLLUP_STATES,  # noqa: F401
    SHAPE_KEYS,
    WINDOWS,  # noqa: F401
    _bars,  # noqa: F401
    _blocks,  # noqa: F401
    _holders_width,  # noqa: F401
    _https,  # noqa: F401
    _own_stop,  # noqa: F401
    _pr_states,  # noqa: F401
    _rollup_block,  # noqa: F401
    _rollup_debt,  # noqa: F401
    answer_blocks,  # noqa: F401
    answer_members,  # noqa: F401
    ask_blocks,  # noqa: F401
    asked_line,  # noqa: F401
    compact_line,  # noqa: F401
    completed_faces,  # noqa: F401
    completed_in,  # noqa: F401
    completed_title,  # noqa: F401
    doing_rows,  # noqa: F401
    drawn_facets,  # noqa: F401
    entries_by_id,
    lane_count,  # noqa: F401
    lanes_line,
    motion_rows,  # noqa: F401
    pr_ref,  # noqa: F401
    repo_facet,  # noqa: F401
    repo_named,  # noqa: F401
    rollup,  # noqa: F401
    rollup_counted,  # noqa: F401
    rollup_rows,  # noqa: F401
    team_lanes,  # noqa: F401
    team_named,  # noqa: F401
    team_repo,  # noqa: F401
    team_summary,  # noqa: F401
)
from .pty_bridge import (
    JUMP_WITHIN,
    LEAVE_WITHIN,
    PtySession,
    attach_argv,
    clients_argv,
    leave_argv,
    pump,
    run_jump,
    scroll_argv,
    watch_clients,
)
from .queue import (
    WINDOW_LABEL,
    WINDOW_WORD,
    apply_picks,
    attach,
    card_index,
    card_session,
    card_wants,
    filter_chips,
    item_start,
    picks_query,
    queue_picks,
    queue_view,
    queue_window,
    same_td,
    send_window,
    split_later,
    waits_on_me,
)
from .repo import (  # re-exported: routes, templates and tests read these from the app (TD-196)
    COMPLETED_FOLD,  # noqa: F401
    ENTRY_PREFIX,
    ENTRY_SLUG_WHY,
    ENTRY_TRIES,
    LEDGER_FLAG,  # noqa: F401
    LEDGER_FLAGS,  # noqa: F401
    LEDGER_FOLD,  # noqa: F401
    LEDGER_LISTS,  # noqa: F401
    LOCAL_ID,  # noqa: F401
    PRIORITY_RANK,  # noqa: F401
    _parts,  # noqa: F401
    _stopped,  # noqa: F401
    _tid,  # noqa: F401
    compact_in,  # noqa: F401
    completed_rows,
    debt_cards,  # noqa: F401
    design_builds,  # noqa: F401
    doing_chips,
    entry_branch_exists,
    entry_hand,
    entry_line,
    entry_role,
    entry_teams,
    flow_head,  # noqa: F401
    ledger_lists,  # noqa: F401
    missing_seams,
    org_layout,
    pr_rows,  # noqa: F401
    pr_standing,  # noqa: F401
    repo_doing,
    repo_items,
    repo_line,  # noqa: F401
    repo_window,
    seat_names,  # noqa: F401
    send_folds,
    settle_mark,  # noqa: F401
    strip_group,  # noqa: F401
    team_groups,
    team_notes,
    who_for_what,  # noqa: F401
)
from .spend import INTERACTIVE as SPEND_INTERACTIVE
from .spend import OUTSIDE as SPEND_OUTSIDE
from .spend import SPEND_TTL, shape_view, spend_picks, spend_view, titles_of
from .transcript import TRANSCRIPT_TURNS, transcript_editor, transcript_paths, transcript_view

# -- the Inbox's board reading, kept here: the suite patches both names on the app (TD-196) --------


def repo_teams(org: orgmod.Org, host: str) -> dict[str, str]:
    """Each checkout on `host` → the first team whose `repo:` is it, in definition order (design §4.9
    *Teams*): a repo has any number of teams, and where one must be named — Add entry's hand-to
    default, the start-on-work row — it is the first. A board row names its repo instead
    (`repo_boards`, TD-741)."""
    out: dict[str, str] = {}
    for tname, t in org.teams.items():
        if path := org.checkout(t.repo, host):
            out.setdefault(str(Path(path).expanduser().resolve()), tname)
    return out


def road_refusal(org: orgmod.Org, root: str, road: str, host: str) -> str:
    """Why **Done…** or **Back to design…** on a ledger row of the checkout `root` is refused before the home
    is asked (design §4.5 screen 12 *any open row*, TD-905), or '': no team's `repo:` is the checkout, so
    nobody would read the decided line; and, for Back to design, no member's lane and no stage of a
    servicing team's current flow takes `design-first`, so nobody would design it. The home reads no
    `org.yml`, so the page says it."""
    want = Path(root).expanduser().resolve()
    serving = [
        t for t in org.teams.values() if (p := org.checkout(t.repo, host)) and Path(p).expanduser().resolve() == want
    ]
    if not serving:
        return f"no team services {want.name}: nobody would read the line"
    if road != "design":
        return ""
    for t in serving:
        if any("design-first" in m.lane for m in t.members):
            return ""
        under = teams.compiled(org, t, t.host or host, host, None)
        if under is not None and any("design-first" in st.lane for st in under.flow.stages):
            return ""
    names = ", ".join(t.name for t in serving)
    return f"no lane of {names} takes design-first: nobody would design it"


def repo_boards(org: orgmod.Org, host: str) -> dict[str, dict[str, Any]]:
    """Each checkout on `host` → what a board row of it carries (§4.5 screen 6 *a board item carries its
    repo*, TD-722, built by TD-741): the board is the repo's, so a row names the repo and no team —
    `name`, the rail's `repo` pick; `label`, *ContractMatch · samscrape* where the repo's project has
    several repos, else the name; and `teams`, every team whose `repo:` it is in definition order, which
    a team pick narrows board rows by and whose rail counts take them in."""
    out: dict[str, dict[str, Any]] = {}

    def entry(repo: str, path: Path) -> dict[str, Any]:
        p = org.heading(repo)
        label = f"{p.title or p.name} · {repo}" if p is not None and len(p.repos) > 1 else repo
        return out.setdefault(str(Path(path).expanduser().resolve()), {"name": repo, "label": label, "teams": []})

    for repo, per_host in org.checkouts.items():
        if path := per_host.get(host):
            entry(repo, path)
    for tname, t in org.teams.items():
        if path := org.checkout(t.repo, host):
            entry(t.repo, path)["teams"].append(tname)
    return out


# -- app -------------------------------------------------------------------------------------------


# design §4.5a Sessions top bar **Inbox** (TD-611): what `/api/person/inbox?counts=1` answers — the top
# bar's numbers, the team headers' *answered for you* marks and the build chip, and nothing rendered
INBOX_COUNTS = ("needs", "fyi_n", "overdue_n", "snoozed_n", "queue_n", "answered_marks", "build_chip", "agent_down")
# The counts with the host agent down: not zero — nothing is *known* to be waiting, which is not
# *nothing is* — and the team headers and the rollup keep what they showed (TD-069, TD-178).
COUNTS_DOWN: dict[str, Any] = {k: None for k in INBOX_COUNTS} | {"snoozed_n": 0, "agent_down": True}


def gzip_ok(request: Request) -> bool:
    """The browser takes a gzipped body: `gzip` among its encodings, not `gzip;q=0`, which says no."""
    return any(
        t.split(";")[0].strip() == "gzip"
        and t.replace(" ", "").partition(";q=")[2] not in ("0", "0.0", "0.00", "0.000")
        for t in request.headers.get("accept-encoding", "").split(",")
    )


def json_body(obj: Any, gz: bool) -> bytes:
    """`obj` as FastAPI encodes a returned dict, gzipped when `gz` — called on a worker thread for a
    body the size of the inbox (TD-611 slice 2), since the loop is the Focus terminal's too."""
    body = json.dumps(jsonable_encoder(obj), ensure_ascii=False, separators=(",", ":")).encode()
    return gzip.compress(body, compresslevel=5) if gz else body


def json_answer(body: bytes, gz: bool) -> Response:
    headers = {"Content-Encoding": "gzip", "Vary": "Accept-Encoding"} if gz else {"Vary": "Accept-Encoding"}
    return Response(body, media_type="application/json", headers=headers)


def tab_counts(sections: Mapping[str, Any]) -> dict[str, int]:
    """The top bar's numbers at first paint (§4.5a *the bar's three groups*, TD-932): the Inbox tab's, the needs-you
    rows the Inbox draws, and the Queue tab's, those drawn on its cards — together `count`, what waits on a person."""
    queue_n = sections.get("queue_n", 0)
    return {"person_needs": sections["count"] - queue_n, "person_queue_n": queue_n, "person_fyi": sections["fyi_n"]}


def counts_of(sections: Mapping[str, Any], build: Any) -> dict[str, Any]:
    """`INBOX_COUNTS` from the Inbox's sections (`inbox_sections`): the one place the top bar's
    numbers are taken from, by the full read, the counts read and the counts keeper alike."""
    return {
        "needs": sections["count"],
        # §4.10 *The Inbox is a queue*: FYI's own quiet number, **never added to the first** — the
        # first is *what needs you*. The page opens the section by itself when this is higher than
        # the browser last saw, which is what stops a folded FYI hiding mail nobody counted.
        "fyi_n": sections["fyi_n"],
        "overdue_n": sections["overdue_n"],  # the Org rollup's *m overdue* (TD-178)
        "snoozed_n": len(sections["snoozed"]),
        # the counted rows the Queue draws on their cards (§4.5 screen 6 *Where a row is drawn*, TD-771): the
        # Queue tab's number, and `needs` less it the Inbox tab's (§4.5a *the bar's three groups*, TD-932)
        "queue_n": sections.get("queue_n", 0),
        # §4.5a **team header** → *answered for you* count (§4.9b, TD-075): each row's team and
        # time, and nothing it says — the browser counts those newer than it last opened the group
        # (that memory is the browser's, as FYI's *new* mark is), so the home keeps no read state
        "answered_marks": [{"team": e.get("team") or "", "at": e.get("at") or ""} for e in sections["answered"]],
        # the top bar's **build** chip is drawn again with the counts (§4.5a, TD-539): a merge shows
        # within the readings' cadence without a reload
        "build_chip": build,
        "agent_down": False,
    }


# design §4.5a **Focus (exited / closed)** → **Resume** (TD-081 step 2; the plumbing is step 1,
# PR #282). What a one-press resume carries, and what it deliberately does not.
RESUME_CARRIES = ("name", "dir", "adapter", "profile", "repo", "role", "team", "project", "lane", "controllers")
# The first prompt **Reopen and push** writes (§4.5a *Inbox row: state*, TD-081). Fixed text, in
# the source: it is the page's sentence, never anything a session said (§4.2), and what comes of it
# returns as an outcome (§4.10 *Outcomes*).
REOPEN_AND_PUSH = (
    "Push your branch and open or update its PR, then report the outcome with "
    '`ao msg person --outcome done|blocked|dropped "<one line>" --for <the question this answers>` '
    "— or, if nothing is owed, say so on docs/user_attention.md."
)


def resume_create(rec: dict[str, Any], *, prompt: str = "") -> dict[str, Any]:
    """The `create` a one-press **Resume** makes from an exited record (design §4.5a).

    It carries the record's own `name` — which is the whole point: the name check answers
    `supersede`, the new session takes the bare name *and* the record's id, the old record is
    replaced in place and its mail stays with it (§4.10 *a resume under the same name*, built by
    TD-081 step 1). And it carries `dir`, `adapter`, `profile`, `role`, `team`, `project`, `lane`
    and `controllers`, so a live team finds its member where it was.

    **And `repo`, when the record has one** (TD-145). A name identifies one session per *scope*
    (§4.1), and the scope of a session in a worktree is its repo, not the worktree directory: the
    record's id is `ao-<repo>-<name>`. A resume that sent `dir` alone put the worktree's basename
    in the scope — and a worktree named after its session (every team member's is) made
    `ao-<name>-<name>`, collapsed to `ao-<name>`, an id nobody held — so the name check answered
    *free*, a second record appeared beside the one being resumed, and the team showed two of the
    seat (2026-09-24: `ao-techlead-ao-1` beside `ao-agentorc-techlead-ao-1`, and the seat's
    trigger dead with it, since a superseded record is never filled).

    **Never `unattended`.** The session a press starts is *attended*, whatever the record was: an
    unattended session answers its own permission prompts, and a press with no form is no place to
    grant that — least of all to a member whose manager has gone and whose `run_until` has passed.
    Also not carried: `run_until` and `wrapup_prompt` (a deadline that has passed is not one),
    the old `prompt`, and `capabilities` — the grants come from the record's **role**, through the
    same preset path the form takes, so nothing is copied and nothing is dropped."""
    lane = rec.get("lane")
    # *a `create` **on the record's host***: a record of a node's is addressed `id@host` and its
    # `host` is its own, so a resume without it would create the session on the **home** instead —
    # under the name that should have superseded the node's record (review of PR #290). Sent only
    # when it lands elsewhere, which is `Member.create_params`'s convention and §4.4's rule that a
    # client never sends a parameter it has not set.
    host = str(rec.get("host") or "")
    got: dict[str, Any] = {
        "name": str(rec.get("name") or ""),
        "dir": str(rec.get("dir") or ""),
        "adapter": str(rec.get("adapter") or "claude-code"),
        "profile": str(rec.get("profile") or ""),
        "role": str(rec.get("role") or ""),
        "team": str(rec.get("team") or ""),
        "project": str(rec.get("project") or ""),
        "lane": [str(x) for x in lane] if isinstance(lane, list) else [],
        "controllers": [str(c) for c in (rec.get("controllers") or [])],
        "resume": str(rec.get("adapter_id") or ""),
        "unattended": False,
        # the scope the name is checked in (§4.1): sent only when the record has one (§4.4 skew rule)
        **({"repo": str(rec["repo"])} if rec.get("repo") else {}),
        **({"host": host} if host and host != host_name() else {}),
    }
    if rec.get("repo") and rec.get("worktree"):
        # the repo as `dir` with the worktree's name, as the restarts' launch record does: a reaped record's
        # directory is gone and the create refuses one that is, so the start makes the worktree again at the
        # same path, where the tool finds its conversation (§4.1 *Started again*, TD-979)
        got["dir"] = str(rec["repo"])
        got["worktree"] = str(rec["worktree"])
    if prompt:
        got["prompt"] = prompt
    # The **grants** and the **ledger** come from the directory's repo through the record's role,
    # exactly as they do when the form's Role picker is used — not copied off the old record, so a
    # grant a preset has since dropped is dropped here too, and one it has gained is gained. A
    # directory or a role that no longer resolves is not decided here: the create refuses it and
    # the press lands on the form with the agent's own words (`resume_blocked`'s docstring).
    with contextlib.suppress(KeyError, ValueError, OSError):
        cfg = repoconfig.discover(got["dir"] or os.getcwd())
        got["ledger"] = cfg.ledger
        if got["role"]:
            preset = repoconfig.resolve_role(cfg, got["role"])
            got["capabilities"] = [g for g in preset.grants if g in GRANTS]
            got["lane"] = got["lane"] or list(preset.lane)
            got["profile"] = got["profile"] or preset.profile or ""
    return got


def resume_blocked(rec: dict[str, Any]) -> str:
    """Why a one-press **Resume** cannot be silent on this record, or "" — *when it cannot be
    silent it is not a guess* (§4.5a): the press lands on the filled-in form with the reason on it.

    Only what is knowable from the record is decided here. Everything else — a directory that is
    gone, a profile or role that no longer exists, a host that is not connected, a name a live
    record has taken since — is the agent's own refusal, which the caller turns into the same
    fall-through in the agent's own words, so no rule of ours can drift from the one that runs."""
    if str(rec.get("state") or "") not in ("exited", "closed"):
        return "this session is still running — there is nothing to resume"
    if not str(rec.get("adapter_id") or ""):
        return "this record holds no tool session id, so there is no conversation to resume"
    if not str(rec.get("name") or "") or not str(rec.get("dir") or ""):
        return "this record has no name or no directory to take back"
    return ""


def resume_form_url(rec: dict[str, Any], why: str = "") -> str:
    """**Resume with changes…**: New session with every field of `resume_create` filled in, which
    is also where a press that cannot be silent lands, with its reason (§4.5a)."""
    got = resume_create(rec)
    # `capabilities` and `ledger` are the create's, not the form's — §4.5a says capabilities are
    # **not carried**, and the form derives both from the Role picker. `host` is the Host pick's
    # (TD-284 slice 3), carried only when it is another host's record, as the create sends it.
    # no `project` in the form's query: the form reads the badge from the directory (§4.9 *Home and reach*)
    q = {k: v for k, v in got.items() if k in RESUME_CARRIES and k not in ("lane", "controllers", "project") and v}
    if got.get("host"):
        q["host"] = got["host"]
    q["resume"] = got["resume"]
    # A worktree record lands on the form as the form says it: **Where** = new worktree, the
    # worktree's name, and the directory field holding the *repo* — which is what the form's own
    # Start sends (`repo=dir` with `worktree`), so the create checks the name in the record's scope
    # and takes its id back, exactly as the one-press Resume does (TD-145). Keyed on the record's
    # own `worktree` — the field the create sets when it made or reused `<repo>/.claude/worktrees/
    # <name>` — never on `dir != repo`: `ao new --repo` scopes a directory that is a worktree of the
    # repo's without going through that flow, and such a record resumes where it is (review of #543).
    repo = q.pop("repo", "")
    if repo and rec.get("worktree"):
        q["worktree"] = str(rec["worktree"])
        q["where"] = "worktree"
        q["dir"] = repo
    q["lane"] = ", ".join(got["lane"])
    q["controllers"] = ",".join(got["controllers"])
    # *Unattended* as the record had it — on the form, where it is next to its stop time
    q["unattended"] = "on" if rec.get("unattended") else ""
    # **The form is filled in from a record, not opened blank** — which is what lets an *empty*
    # controllers list mean *this record had none* rather than *nothing was said*. Without it the
    # repo's default would be re-ticked and a person who did not notice would Start a session with
    # controllers the record never had (review of PR #290).
    q["prefilled"] = "1"
    if why:
        q["why"] = why
    return "/new?" + urlencode({k: v for k, v in q.items() if v})


def ledger_start_form(root: str, name: str, ref: str, team: str, role: str, manager: str, prompt: str, why: str) -> str:
    """Where **Start session** lands when it cannot be silent (§4.5a *Inbox row: ledger entry*, TD-678):
    New session filled in as the press would have started it — the repo, a new worktree `td-<n>` under
    that name, the team, the role, the entry as its lane, the team's manager, the opening prompt — with
    the reason on it, as **Resume**'s press lands (`resume_form_url`). Never *Unattended*: the session
    is the person's."""
    q = {
        "dir": root,
        "where": "worktree",
        "worktree": name,
        "name": name,
        "team": team,
        "role": role,
        "lane": ref,
        "controllers": manager,
        "prompt": prompt,
        "prefilled": "1",
        "why": why,
        "press": "start",
    }
    return "/new?" + urlencode({k: v for k, v in q.items() if v})


def _int_param(raw: str | None, default: int, lo: int, hi: int) -> int:
    try:
        v = int(float(raw)) if raw not in (None, "") else default
    except (TypeError, ValueError, OverflowError):  # "abc", "NaN", "inf" / "1e999"
        return default
    return max(lo, min(hi, v))


class _WsAttemptLog:
    """Log every websocket upgrade the instant it arrives, before any handler runs. uvicorn logs a
    websocket only once the app accepts or rejects it, so "no line at all" could not distinguish
    "never reached the server" from "hung before accept" (first-use finding 2026-09-06)."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") == "websocket":
            client = scope.get("client") or ("?", "?")
            log.info("websocket attempt from %s:%s for %s", client[0], client[1], scope.get("path"))
        await self.app(scope, receive, send)


GZIP_MIN = 1024  # a body under 1 KB goes as it is (§4.5 *Page loads*, *Compressed*)
PACKED = (b"image/", b"font/", b"application/zip", b"application/gzip")  # compressed already: as it is


class _Gzip:
    """A page, a `part=1` fragment and a static file go gzipped to a browser that takes it (design
    §4.5 *Page loads*, TD-880), with `Vary: Accept-Encoding`. Starlette's own `GZipMiddleware`
    compresses on the loop, which every Focus keystroke shares, so the body is held whole and
    compressed on a worker thread, as `json_body` compresses the counts. Only http: the event
    stream and the terminal are websockets and pass by. A response already encoded (the counts'
    JSON), one compressed by its format (`PACKED`: a font, an image), not a 200, or under `GZIP_MIN`
    is sent as it was."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        gz, ranged = gzip_ok(request), "range" in request.headers
        start: dict[str, Any] | None = None
        chunks: list[bytes] = []
        passing = False

        async def wrapped(message: dict[str, Any]) -> None:
            nonlocal start, passing
            if passing:
                await send(message)
                return
            if message["type"] == "http.response.start":
                headers = {k.lower(): v for k, v in message.get("headers") or ()}
                packed = headers.get(b"content-type", b"").startswith(PACKED)
                if message.get("status") != 200 or b"content-encoding" in headers or ranged or packed:
                    passing = True
                    await send(message)
                else:
                    start = message
                return
            if message["type"] != "http.response.body" or start is None:
                if start is not None:  # a `pathsend` or another body form: the start goes first, as it was
                    await send(start)
                    passing = True
                await send(message)
                return
            chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            body = b"".join(chunks)
            headers = [(k, v) for k, v in start.get("headers") or () if k.lower() != b"vary"]
            headers.append((b"vary", b"Accept-Encoding"))
            if gz and len(body) >= GZIP_MIN:
                body = await asyncio.to_thread(gzip.compress, body, 5)
                headers = [(k, v) for k, v in headers if k.lower() != b"content-length"]
                headers += [(b"content-encoding", b"gzip"), (b"content-length", str(len(body)).encode())]
            await send(start | {"headers": headers})
            await send({"type": "http.response.body", "body": body, "more_body": False})

        await self.app(scope, receive, wrapped)


class _Static(StaticFiles):
    """A static file whose URL carries its `?v=` hash (`static_url`) is kept a year and never
    revalidated; one without it is revalidated on each load against its ETag (§4.5 *Page loads*,
    *Cached*, TD-880)."""

    async def get_response(self, path: str, scope: Any) -> Response:
        response = await super().get_response(path, scope)
        hashed = any(k == "v" and v for k, v in parse_qsl(scope.get("query_string", b"").decode("latin-1")))
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if hashed else "no-cache"
        return response


def render_heads(groups: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """The groups as a delta carries them (§4.5a **team groups**): each header, summary and + card
    rendered, the client swapping them in place; `None` is the flat page."""
    if groups is None:
        return None
    head = templates.get_template("group_head.html")
    summary = templates.get_template("team_summary.html")
    plus = templates.get_template("plus_card.html")
    lanecount = templates.get_template("lanecount.html").module.span
    # a project heading and a repo's line (§4.9 *The Sessions page*, TD-725): no cards, their markup whole
    lines = {"heading": templates.get_template("project_head.html"), "repo": templates.get_template("repo_line.html")}
    return [
        {"kind": g["kind"], "key": g["key"], "team": "", "html": lines[g["kind"]].render(g=g)}
        if g.get("kind") in lines
        else {
            "kind": g.get("kind", "team"),
            "key": g.get("key", g["team"]),
            "repo": g.get("repo", ""),
            "project": g.get("project", ""),
            "team": g["team"],
            "manager": (g["manager"] or {}).get("id", ""),
            "live": g["live"],  # what the fold's default keys on: nothing live opens folded (TD-194)
            "ids": g["ids"],
            "html": head.render(g=g),
            # the summary's facets (TD-176 slice 3), swapped by the client as the header is
            "summary": summary.render(g=g) if g.get("summary") and g["summary"].get("drawn") else "",
            # the team's + card (§4.5a *team card: + card*, TD-379): put in by the client when missing
            "plus": plus.render(g=g) if g["team"] and g.get("defined") else "",
            # each member's lane count, by id (TD-484): a claim or a ledger change moves its siblings'
            # counts too, so every delta patches every pill; "" takes the count away
            "lanes": {m["id"]: str(lanecount(m.get("lane_count"))) for m in g.get("members") or []}
            if g.get("summary")
            else {},
        }
        for g in groups
    ]


def refill(held: dict[str, Any], new: Mapping[str, Any]) -> None:
    """`held` made `new` in place, never emptied on the way: a view built on a worker thread (TD-670)
    reads it while the loop refills it, and a `clear()` first would draw that view without its marks."""
    for k in set(held) - set(new):
        held.pop(k, None)
    held.update(new)


async def agent_call(method: str, **params: Any) -> Any:
    """One host-agent RPC as the page makes it: down is a 503, a refusal a 400."""
    try:
        with timing.step(f"rpc_{method}", nests=False):  # a page's `Server-Timing` (§4.5 *Page loads*, TD-881)
            async with LocalClient() as c:
                return await c.call(method, **params)
    except AgentUnavailable as e:
        raise HTTPException(503, f"host agent unreachable: {e}") from e
    except AgentError as e:
        raise HTTPException(400, str(e)) from e


async def paths_for(call: Any, body: dict[str, Any]) -> dict[str, Any]:
    """`POST /api/paths` (§4.6 *A path in the Inbox and the Queue is a link too*, TD-1108): the runs one
    item names, resolved by its context — `id:<record id>` on that record's host by `dir`, `repo:<root>`
    against that checkout at the home, `home` for absolute and `~/` runs alone — with the context's
    editor file form. The grammar and the bounds are a 400 before anything is read; a forgotten record
    or an unregistered repo is a 200 that says `refused`, every run `null`; anything else that fails
    is the RPC's own non-200, so the page caches nothing."""
    runs, ctx = body.get("runs"), body.get("ctx")
    if not isinstance(runs, list) or not all(isinstance(r, str) for r in runs):
        raise HTTPException(400, "paths takes runs, a list of strings (design §4.6)")
    if len(runs) > PATHS_RUNS_MAX or any(len(r) > PATHS_RUN_CHARS for r in runs):
        raise HTTPException(400, f"paths: at most {PATHS_RUNS_MAX} runs of {PATHS_RUN_CHARS} characters (design §4.6)")
    kind, colon, rest = ctx.partition(":") if isinstance(ctx, str) else ("", "", "")
    if not ((kind == "home" and not colon) or (kind in ("id", "repo") and rest)):
        raise HTTPException(400, f"paths: ctx is id:<record>, repo:<root> or home, not {ctx!r} (design §4.6)")
    fl = uiconf.file_link()
    out: dict[str, Any] = {"label": uiconf.open_in().label, "file": None, "wait": fl["wait"]}
    none = dict.fromkeys(runs)
    if kind == "id":
        try:
            s = await call("get", id=rest)
        except HTTPException as e:
            if e.status_code != 400:
                raise
            return {**out, "paths": none, "refused": str(e.detail)}
        ed, reach = record_editor(s)
        if not ed or not (form := editor_file(reach)):
            return {**out, "paths": none}  # no file form: its host is never asked
        got = (await call("paths", id=rest, runs=runs))["paths"]
        folder = ed["url"] if fl["folder_first"] else None
        return {**out, "file": form, "paths": {r: {"path": p, "folder": folder} if p else None for r, p in got.items()}}
    if not (form := editor_file()):
        return {**out, "paths": none}
    if kind == "repo":

        def registered() -> bool:  # two file reads and a realpath each: off the loop
            try:
                real = os.path.realpath(os.path.expanduser(rest))
                return real in {os.path.realpath(os.path.expanduser(r)) for r in hosts.local_host().repos()}
            except (OSError, ValueError, RuntimeError):
                return False

        if not await asyncio.to_thread(registered):
            return {**out, "paths": none, "refused": f"{rest} is no checkout in the repos registry"}
        got = (await call("paths", repo=rest, runs=runs))["paths"]
    else:
        got = (await call("paths", runs=runs))["paths"]

    def folder(path: str) -> str | None:
        root = checkout_of(path) if fl["folder_first"] else ""
        ed = editor_link(root) if root else None
        return ed["url"] if ed else None

    return {**out, "file": form, "paths": {r: {"path": p, "folder": folder(p)} if p else None for r, p in got.items()}}


def not_own_shell(rec: dict[str, Any], name: str, directory: str) -> str | None:
    """Why the live record holding `<session>-shell` is not the person's own shell in `directory`, or
    None when it is (design §4.5a *Focus: Open shell here*, TD-810): `mail.person_shell`'s test — a
    `shell`, interactive, no role, no controllers; a team badge is no bar (TD-821) — read on the
    record's view, and the same directory. The words are the press's refusal."""
    who, cure = rec.get("id") or name, "close it, or open a shell from its Focus"
    if rec.get("adapter") != "shell":
        return f"{name} is held by {who}, which is not a shell — close it, or pick another name"
    if ctl := rec.get("controllers"):
        return f"{name} is a shell with controllers {', '.join(ctl)} — not your own; {cure}"
    if rec.get("unattended"):
        return f"{name} is a shell run unattended — not your own; {cure}"
    if rec.get("role"):
        return f"{name} is a shell with a role — not your own; {cure}"
    if os.path.normpath(str(rec.get("dir") or "")) != os.path.normpath(directory):
        return f"{name} is held by a shell in {rec.get('dir')} — {cure}"
    return None


# One `repos` reading per page request (TD-739): the reading is the repos' whole facts — 1.3 MB on
# the live home, ~40 ms a read — and a page asked for it two or three times (the board, the state
# rows, the ledger's rows). The http middleware gives each request its own memo; a reader with none
# (`ao inbox --counts`) reads each time, and a memo older than `REPOS_MEMO_TTL` is read again, so a
# long-lived request never holds a stale one.
_REPOS_MEMO: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("repos_memo", default=None)
REPOS_MEMO_TTL = 2.0
LANES_WAIT = 5.0  # seconds a team's lanes reading waits on one RPC from its worker thread (TD-781)

# What a page leaves out of the `repos` reading (the RPC's `omit`, design §4.4 *Repo facts*, TD-746):
# the parts no reader of the page draws — the ledger's month of history (`ledger.recent`, which only the
# host agent reads, to build `completed`), the fields of the month's PRs nothing marks (a card's report
# line and *TDs in motion* read a PR's number, state, title and link), and, on the Org, the Repo page
# and a card, each entry's detail block, which only the Inbox's ledger rows show; the Inbox draws no
# facet, so leaves out `completed` instead. An omit, never a list of what to keep: a key the agent
# grows is drawn the day it lands, and only a page that names it loses it.
_RECENT_PR_UNDRAWN = ("head", "base", "branch", "author", "created", "closed", "draft")
REPOS_OMIT_COMMON = ("ledger.recent", *(f"prs.recent.{k}" for k in _RECENT_PR_UNDRAWN))
REPOS_OMIT_PAGE = (*REPOS_OMIT_COMMON, "ledger.entries.detail")
REPOS_OMIT_INBOX = (*REPOS_OMIT_COMMON, "completed")


def repos_omit(paths: tuple[str, ...]) -> None:
    """The `repos` reading this request asks for leaves out `paths` (TD-746): a page route says it
    before its first read; a request that says nothing, and a reader with no memo, reads it whole."""
    memo = _REPOS_MEMO.get()
    if memo is not None and memo.get("omit") != paths:
        memo.clear()
        memo["omit"] = paths


class Readings:
    """The readings the Inbox is counted from (design §4.4 *Each reading has one owner*, *The Inbox's
    counts*; TD-616): the person inbox, the state rows, the board's horizon and the build chip, each
    over the host agent's RPCs, cached as the page reads them. The UI's `create_app` holds one, and
    `ao inbox --counts` makes its own, so both count with the one `counts_now`."""

    def __init__(self, call: Any = None) -> None:
        self.call = call or agent_call
        self.defs_cache: dict[str, Any] = {"at": 0.0, "org": None}
        self.identity_cache: dict[str, Any] = {"at": 0.0, "info": None}
        self.pull_cache: dict[str, Any] = {"at": float("-inf")}
        self.needs_cache: dict[str, Any] = {"rows": []}
        self.waits_cache: dict[str, Any] = {"at": 0.0, "waits": None}
        self.lanes_cache: dict[str, tuple[float, Any]] = {}
        self.spend_cache: dict[str, Any] = {"at": 0.0, "teams": None}

    async def queue_cards(self) -> dict[str, tuple[str, str]]:
        """The open Queue cards' entries (`ui.queue.card_index`), which say where an Inbox row is drawn
        (§4.5 screen 6 *Where a row is drawn*, TD-771): empty from a home that serves no Queue, so every
        row is the Inbox's, as before it."""
        try:
            return card_index(await self.call("queue", omit=["completed"]))
        except Exception:  # an older home, a node's link down: the Inbox draws everything
            return {}

    async def defs(self) -> orgmod.Org:
        """The team definitions, read at most once in `DEFS_TTL` seconds: the events stream
        re-renders every header on every delta — a definition edited by hand shows within that."""
        now = time.monotonic()
        if self.defs_cache["org"] is None or now - self.defs_cache["at"] > DEFS_TTL:
            # off the loop: every open page shares it, and the read is a file per registered repo
            self.defs_cache.update(at=now, org=(await asyncio.to_thread(org_here))[0])
        return self.defs_cache["org"]

    async def seats_of(self, fleet: list[dict[str, Any]]) -> dict[str, str]:
        """The ids in `fleet` a team definition names as a seat — what `view()` draws *on call*
        while nobody is in one (TD-097). Every page that draws a pill asks, so they agree."""
        return teamrun.seat_ids(await self.defs(), fleet)

    async def repos(self) -> Any:
        """The `repos` reading, once per request (`_REPOS_MEMO`, TD-739), without what the request's
        page leaves out (`repos_omit`, TD-746)."""
        memo = _REPOS_MEMO.get()
        if memo is not None and "got" in memo and time.monotonic() - memo["at"] <= REPOS_MEMO_TTL:
            return memo["got"]
        omit = (memo or {}).get("omit")
        got = await (self.call("repos", omit=list(omit)) if omit else self.call("repos"))
        if memo is not None:
            memo.update(got=got, at=time.monotonic())
        return got

    async def repo_facts(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """The home's repo facts and doing log (§4.4 *Repo facts*, TD-176), each `{}` when the agent
        cannot give it — an older agent, a node whose link is down: the facets then read *no repo
        here* and an empty feed rather than taking the page down."""
        repos: dict[str, Any] = {}
        doing: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            repos = await self.repos()
        with contextlib.suppress(Exception):
            doing = await self.call("doing_log")
        return repos, doing

    async def identity_info(self) -> dict[str, Any]:
        """This host's identity mode (design §4.8a), for the Org's one-line note. The `identity`
        RPC is a never-gated read, and it is read at most once every `DEFS_TTL` seconds — the same
        idiom as the team definitions, so a page under a delta storm never asks per render. An
        agent that is down or too old to answer leaves the note off rather than the page."""
        now = time.monotonic()
        if self.identity_cache["info"] is None or now - self.identity_cache["at"] > DEFS_TTL:
            try:
                self.identity_cache.update(at=now, info=await self.call("identity"))
            except HTTPException:
                self.identity_cache.update(at=now, info={})
        return self.identity_cache["info"] or {}

    async def team_spend(self) -> dict[str, Any]:
        """Today's `seats` row by team, for each team card's **spend** figure (§4.5a *team card: spend*,
        TD-832): read at most once in `SPEND_TTL` seconds, since every delta re-renders the headers and
        a day's figure moves by the turn. An agent that is down or too old leaves the figures off."""
        now = time.monotonic()
        if self.spend_cache["teams"] is None or now - self.spend_cache["at"] > SPEND_TTL:
            got: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                got = {str(t.get("team")): t for t in (await self.call("seats", window="day")).get("teams") or []}
            self.spend_cache.update(at=now, teams=got)
        return self.spend_cache["teams"] or {}

    async def pull_marks(self) -> None:
        """The home's pull readings (`host`'s `pulls`, §6 *Pull*) into `inbox.PULLS`, which the
        *behind* origin note's tail reads (TD-263); at most once in `DEFS_TTL`, `work_marks`' idiom.
        An agent that cannot give them — an older one, a node — leaves the note without a tail."""
        now = time.monotonic()
        if now - self.pull_cache["at"] <= DEFS_TTL:
            return
        self.pull_cache["at"] = now
        got: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            got = dict((await self.call("host")).get("pulls") or {})
        refill(inbox_mod.PULLS, got)

    @timing.timed("board")
    async def board_all(self) -> tuple[list[dict[str, Any]], str]:
        """Every open board row of this host's repos and the note beside them (TD-069 step 3), from the
        host agent's `boards` reading on the `repos` RPC (§4.4 *Each reading has one owner*, *The
        boards*, TD-615): the page runs no reader, and a press's write-back is in the reading before its
        RPC answers. Every open row, the ones not yet due too, for the board's horizon (TD-220). On a
        node the org is the home's (§4.4a), so a node draws none; an agent that cannot answer is said."""
        if hosts.is_node():
            return [], ""
        await self.pull_marks()
        try:
            repos = await self.repos()
        except Exception as e:  # noqa: BLE001 — said in words, never an empty board
            return [], f"board items are not shown: the host agent's repo reading could not be read ({e})"
        boards_of = repo_boards(await self.defs(), host_name())
        # off the loop (TD-670): every repo's board rows and their standings run to ~40 ms on the live
        # home, on every recount of the Inbox's counts as on the page's read
        return await asyncio.to_thread(board_reading, repos if isinstance(repos, dict) else {}, boards_of)

    async def board_items(self) -> tuple[list[dict[str, Any]], str]:
        """The Inbox's **due** board rows and the note beside them: what is counted is what is due,
        under every mode (TD-220)."""
        rows, note = await self.board_all()
        return [r for r in rows if r.get("due_now", True)], note

    async def board_view(self, choices: list[dict[str, str]] | None = None) -> tuple[dict[str, Any], str]:
        """The board's horizon (§4.5 screen 6, TD-220) over every open row, sorted by the person's
        `inbox.board_show`, and the note: `due` is `board_items`' rows, `ahead` *Board, coming up*,
        `hidden` the *not shown* fold, and `line` the words that say the mode — None when no board
        was read (a reading that failed says so in its note instead). `choices` the request's own
        `board_choices()`, read once by a route that passes it (§4.5 *Page loads*, TD-879)."""
        rows, note = await self.board_all()
        h = board_horizon(rows, uiconf.board_show())
        h["line"] = board_line(h) if rows or (not note and (board_choices() if choices is None else choices)) else None
        return h, note

    @timing.timed("inbox")
    async def person_states(self, fleet: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The session-state rows of the Inbox (design §4.5 screen 6, TD-069 step 2), from the
        fleet the request already read. Every host the home knows, exactly as the Org shows them —
        the same records and the same `view()` — plus this host's own identity alarms (§4.8a).

        Rendered server-side on the page's load *and* on its poll: a state that changed between
        polls is corrected by the next one, and nothing here has to ride the pushed stream to be
        no more than a few seconds behind the Org."""
        icons = await role_icons(fleet)
        seats = await self.seats_of(fleet)
        # what each waits on (§4.2 *Waiting*, TD-428), so a row's pill is the Org card's
        waits, repos = await self.person_waits(), (await self.repo_facts())[0]
        # every record's view off the loop (TD-670): ~2 ms a record with the live home's repo readings,
        # on every recount of the Inbox's counts as on the page's read
        views = await asyncio.to_thread(
            lambda: [view(s, fleet, icons=icons, seats=seats, repos=repos, waits=waits) for s in fleet]
        )
        info = await self.identity_info()
        rows = state_rows(
            views,
            host_alarms=alarm_view(info.get("alarms")),
            host=str(info.get("host") or host_name()),
            identity_mode=str(info.get("mode") or ""),
        )
        # §4.5a *Inbox row: promote* (TD-132 slice 3): the home's readings; a node has none
        home = await self.call("host")
        # §4.5a *Inbox row: team start* (§6 rule 8, TD-227): the home's `work_waiting` marks, each
        # with the card's own *wound down* instant
        work = home.get("work") or {}
        # …and a defined team with no record whose lanes hold work (§6 rule 8, TD-781): the client's own row
        org = await self.defs()
        teams = [{"name": n, "repo": t.repo} for n, t in org.teams.items()]
        return (
            rows
            + promote_rows(home.get("promotes"))
            + work_rows(work, self.wound_of(fleet) if work else None, records=fleet)
            + lanes_rows(teams, await self.team_lanes(teams, fleet), records=fleet)
            # §4.5a *Inbox row: red PR* (TD-613): a repo no team services, from the repo readings
            + red_pr_rows(repos, fleet)
            # §4.5a *Inbox row: CI not starting* (TD-687): the home's spells, Open's billing page off the loop
            + await asyncio.to_thread(ci_not_run_kinds, ci_not_run_rows(home.get("ci_spells")))
        )

    async def team_lanes(self, teams: list[dict[str, Any]], fleet: list[dict[str, Any]]) -> dict[str, Any]:
        """`teamrun.lanes` for each defined team no unattended record carries (§6 rule 8 *A team with no
        record*, TD-781): what its card's note and its Inbox row say, by team, read off the loop at most
        once in `DEFS_TTL` per team — a plan reads files and the `repos` reading. A read that fails is
        None, which says nothing; a node reads no definition, so has none."""
        if hosts.is_node():
            return {}
        manned = {str(r.get("team") or "") for r in fleet if r.get("unattended") and r.get("team")}
        want = [str(t["name"]) for t in teams if t.get("name") and t["name"] not in manned]
        now = time.monotonic()
        stale = [n for n in want if n not in self.lanes_cache or now - self.lanes_cache[n][0] > DEFS_TTL]
        if stale:
            org, loop, repos = await self.defs(), asyncio.get_running_loop(), None
            with contextlib.suppress(Exception):  # the request's one `repos` reading (TD-739); none is *unknown*
                repos = await self.repos()

            def call(method: str, **params: Any) -> Any:  # this reader's own RPCs, from the worker thread
                if method == "repos":
                    return repos
                fut = asyncio.run_coroutine_threadsafe(self.call(method, **params), loop)
                try:
                    return fut.result(LANES_WAIT)
                finally:
                    fut.cancel()  # a call past its wait is not left running on the loop

            def read() -> dict[str, Any]:
                out: dict[str, Any] = {}
                for n in stale:
                    try:
                        out[n] = teamrun.lanes(call, org, n, host_name())
                    except Exception:  # noqa: BLE001 — one team's read costs its own row and note
                        out[n] = None
                return out

            self.lanes_cache.update({n: (now, got) for n, got in (await asyncio.to_thread(read)).items()})
        return {n: self.lanes_cache[n][1] for n in want}

    async def with_lanes(self, rows: list[dict[str, Any]], fleet: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The definitions' rows (`teamrun.rows`) with what a team with no crew record holds (§4.5a team
        card **work waiting** note, TD-781): `lanes_hold`, the distinct ids its lanes match (None unread),
        and `lanes_line`, Start's *What the lanes hold, before the start*, the note's tooltip."""
        got = await self.team_lanes([r for r in rows if not r.get("records")], fleet)
        for r in rows:
            reading = got.get(str(r.get("name") or "")) if not r.get("records") else None
            ids = lanes_hold(reading)
            r["lanes_hold"], r["lanes_line"] = (
                (len(ids) if ids is not None else None),
                (reading or {}).get("line") or "",
            )
        return rows

    def wound_of(self, fleet: list[dict[str, Any]]) -> dict[str, Any]:
        """`{team: instant}` for the teams the card reads as wound down (`teamrun.rows`)."""
        return {r["name"]: r["wound_down"] for r in teams_view(fleet)["teams"] if r.get("wound_down")}

    async def person_waits(self) -> dict[str, Any]:
        """What each session waits on, from the person inbox (`waits_of`, §4.5a **waiting** mark,
        TD-274), for the surfaces that do not read the inbox themselves — the events stream, Focus,
        the sessions list — read at most once in `DEFS_TTL` seconds, `work_marks`' idiom; `{}` when
        the inbox cannot be read (a node's link down), and no card then says it waits."""
        now = time.monotonic()
        if self.waits_cache["waits"] is None or now - self.waits_cache["at"] > DEFS_TTL:
            got: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                got = dict(await self.call("inbox", id=PERSON))
            self.waits_cache.update(at=now, waits=waits_of(got.get("entries") or []))
        return self.waits_cache["waits"] or {}

    @timing.timed("inbox")
    async def person_inbox(
        self, fleet: list[dict[str, Any]], watching: bool = False, choices: list[dict[str, str]] | None = None
    ) -> dict[str, Any]:
        """The person inbox as every surface here reads it (§4.10, §4.5a): the `inbox` RPC with no
        caller and no id — **a person's read, which sets no `read_at`**, because a person is not
        the session. That is what lets the Inbox page poll it every few seconds without marking
        anything read and without freeing a depth slot an unanswered question still holds; it is
        the rule the dialog this page replaces already relied on, so no `peek` was needed. Each
        sender gets the name it is known by, and `from_open` the id **Open** goes to while that
        record still exists (§4.5 screen 6: a row opens the session that needs the person).
        `watching`: the read is from a visible page, which the home keeps (§4.10 *Looking*, TD-319)."""
        # names `person` (TD-634): no caller's own inbox ever stands in for it — a caller the host reads
        # as a session is refused the person's, and marks nothing
        got = await (self.call("inbox", id=PERSON, watching=True) if watching else self.call("inbox", id=PERSON))
        names = {o.get("id"): o.get("name") or o.get("id") for o in fleet}
        records = {o.get("id"): o for o in fleet}
        # §4.5a *Inbox row: FYI* → **Put on the board** (TD-140): the form's board is the sender's
        # repo's, when this host knows that repo and it carries one; else the person picks
        boards_of = {c["root"]: c["board"] for c in (board_choices() if choices is None else choices)}

        def board_of(sid: Any) -> str:
            repo = str((records.get(sid) or {}).get("repo") or "")
            return boards_of.get(str(Path(repo).expanduser().resolve()), "") if repo else ""

        for t in got.get("trail") or ():
            if isinstance(t, dict):
                t["board_default"] = board_of(t.get("sid"))
        at = datetime.now(UTC)
        here = host_name()
        handed_by = {str(h.get("id")): h for h in got.get("handed") or () if isinstance(h, dict) and h.get("id")}
        for e in got["entries"]:
            e["from_name"] = "person" if e["from"] == "person" else names.get(e["from"], e["from"])
            e["from_open"] = e["from"] if e["from"] in names else ""
            # the Reply dialog's line (§4.10 *When it is read*, TD-168): a reply reads as a note does,
            # but on a handed entry's thread, where it fills a seat on call as an ask does (TD-218)
            rw = (records.get(e["from"]) or {}).get("read_when") or {}
            e["reply_when"] = str((e.get("on_handed") and rw.get("refill")) or rw.get("note") or "")
            e["board_default"] = board_of(e["from"])
            # §4.5a **Inbox row: a look** (§4.10 *A look*, TD-292 slice 3): its screenshots, served
            # from the sender's record's repo — read off the loop, as each is a git read once a minute
            # (TD-300: from the sender's own host where that is not this one, through the home)
            if e.get("shots"):
                sender = records.get(e["from"]) or {}
                repo = str(sender.get("repo") or "")
                e["look_shots"] = await asyncio.to_thread(
                    look_shots, e["shots"], Path(repo).name if repo else "", str(sender.get("host") or "")
                )
                # §4.5a **Send to reviewer** (TD-292 slice 4b): the seat is the sender's team's
                # techlead as this page reads it from `org.yml`; a look already with one reads so
                t = (await self.defs()).teams.get(str(e.get("team") or ""))
                seat = teams.seat_id(await self.defs(), t, t.host or here, here) if t is not None else ""
                look_review(e, seat, t.techlead.name if seat and t and t.techlead else "", handed_by)
            if isinstance(lb := e.get("looked_by"), dict) and lb.get("seat"):
                # the seat's reading names it by the name it is known by, as a sender is (§4.5a)
                e["looked_by"] = {**lb, "name": names.get(str(lb["seat"]), str(lb["seat"]))}
            if isinstance(e.get("pr"), int):  # §4.9b *The reader*: a held PR asked of the person (TD-093)
                sender = records.get(e["from"]) or {}
                e["pr_url"] = reviewmod.pr_url(sender.get("repo") or sender.get("dir"), e["pr"])
            _owing(e, records.get(e["from"]), at)
            # §4.5a *Inbox row: orphaned question* (TD-216 slice 2): its asker is gone, so the row
            # is under the name it asked by, opens nothing, and says where an answer goes — the
            # standing, from the leases the fleet this page read carries
            if standing := mail.orphan_standing(e, fleet, at):
                e["from_name"] = str((e.get("orphaned") or {}).get("name") or e["from_name"])
                e["from_open"] = ""
                e["standing"] = standing
            e["age"] = _age(e.get("at"), at)  # the client keeps it ticking; this is what it opens on
            # §4.5 screen 6 *Layout* (TD-082): a duration is words from here, never a `…` the
            # client fills in — `left` for a `steer`'s bound, `until_words` for a snoozed entry,
            # whose row upgrades to the browser's own clock once the script runs.
            e["left"] = _left(e.get("bound"), at)
            e["until_words"] = _left(e.get("snoozed_until"), at)
            # §4.9b (TD-075 step 3): a question **passed up** is the asker's own entry, and the
            # passer — whose recommendation and suggested answers it carries — is named as a sender is
            rec = e.get("recommend")
            if e.get("passed_up") and isinstance(rec, dict) and rec.get("by"):
                e["passer_name"] = names.get(str(rec["by"]), str(rec["by"]))
            # §4.9b: an *answered for you* row names **who asked** — the session Overrule writes
            # to — by the name it is known by, and opens it while it is here
            asker = str(_answered_of(e).get("asker") or "")
            if asker:
                e["asker_name"] = names.get(asker, asker)
                # Overrule writes to the asker, so its dialog's line is the asker's (TD-168)
                e["asker_when"] = str(((records.get(asker) or {}).get("read_when") or {}).get("note") or "")
                e["asker_open"] = asker if asker in names else ""
        # §4.10 *An entry handed to a seat* (TD-219): the holder's copy of each entry the person
        # handed, drawn under *Waiting on them* (or *Needs you*, once `blocked`) by its id
        got["handed"] = handed_rows(got.get("handed") or (), records, at)
        return got

    async def counts_now(self, watching: bool) -> dict[str, Any]:
        """The top bar's numbers (`INBOX_COUNTS`) from the Inbox's own sections, nothing rendered
        (TD-611 slice 1), the classification on a worker thread (slice 2): what `counts` holds and
        pushes (§4.4 *The Inbox's counts*, TD-616). With the host agent down, the shape that says so —
        no number claimed, the reason in words. Outside a request (the keeper's recount, `ao inbox
        --counts`) it holds a `repos` memo of its own, so the recount reads the reading once, as the
        Inbox does (TD-746)."""
        if (memo := _REPOS_MEMO.get()) is not None:
            if not memo:  # a request that has read nothing yet: the Inbox's reading
                memo["omit"] = REPOS_OMIT_INBOX
            return await self._counts_now(watching)
        token = _REPOS_MEMO.set({"omit": REPOS_OMIT_INBOX})
        try:
            return await self._counts_now(watching)
        finally:
            _REPOS_MEMO.reset(token)

    async def _counts_now(self, watching: bool) -> dict[str, Any]:
        try:
            fleet = await self.call("list")
            choices = board_choices()  # once for the recount (§4.5 *Page loads*, TD-879)
            got, states = (
                await self.person_inbox(fleet, watching=watching, choices=choices),
                await self.person_states(fleet),
            )
        except HTTPException as e:
            if e.status_code != 503:
                raise
            return {**COUNTS_DOWN, "why": str(e.detail)}
        hz, _ = await self.board_view(choices)
        hz = with_standings(hz, fleet)
        build = await chip_build(self.call)
        sections = await asyncio.to_thread(
            inbox_sections,
            got["entries"],
            states=states,
            trail=got.get("trail") or (),
            attention_snoozed=got.get("attention_snoozed"),
            handed=got.get("handed") or (),
            boards=hz["due"] + hz["waiting"],
            fleet=fleet,
            cards=await self.queue_cards(),
        )
        self.needs_cache["rows"] = sections["needs"]  # the Org's *asked you* lines, as the full read keeps it (TD-354)
        return counts_of(sections, build)


def create_app() -> FastAPI:
    app = FastAPI(title="shiftlead")
    app.mount("/static", _Static(directory=str(HERE / "static")), name="static")
    app.add_middleware(_WsAttemptLog)
    app.add_middleware(_Gzip)

    rd = Readings()
    call = rd.call
    defs, seats_of, repo_facts, identity_info = rd.defs, rd.seats_of, rd.repo_facts, rd.identity_info
    board_items, board_view, person_states = rd.board_items, rd.board_view, rd.person_states
    person_waits, person_inbox, counts_now, needs_cache = (
        rd.person_waits,
        rd.person_inbox,
        rd.counts_now,
        rd.needs_cache,
    )

    def render_card(v: dict[str, Any]) -> str:
        return templates.get_template("card.html").render(s=v)

    settings_at = {"at": 0.0}

    @app.middleware("http")
    async def person_settings(request: Request, call_next: Any) -> Any:
        """The person's own (`person:` in the home's `settings.yml`, design §5, TD-146) read through
        the agent's `settings` read at most once in `DEFS_TTL` seconds, before a page is drawn — the
        editor button every card and Focus header draws comes from it. A failed read keeps the last.
        Each request gets its own `repos` memo here (TD-739)."""
        _REPOS_MEMO.set({})
        now = time.monotonic()
        if now - settings_at["at"] > DEFS_TTL and not request.url.path.startswith("/static"):
            settings_at["at"] = now
            try:
                uiconf.set_read(await call("settings"))
            except Exception:  # noqa: BLE001 — a read that failed keeps the last answer; it never costs the page
                log.debug("the settings read failed; the last person: stands", exc_info=True)
        return await call_next(request)

    @app.middleware("http")
    async def server_timing(request: Request, call_next: Any) -> Any:
        """Each page route's `Server-Timing` (§4.5 *Page loads*, *Measured on every load*; TD-881): its RPCs by
        name, the person inbox, the board and ledger reads, the render and the total, the person's settings
        read included — the outermost of the page's middleware, so the total is the whole request's. The
        last twenty per route are kept in memory (`timing.RECENT`)."""
        key = timing.route_key(request.url.path, bool(request.query_params.get("part")))
        if key is None or request.method != "GET":
            return await call_next(request)
        steps, t0 = timing.begin(), time.perf_counter()
        response = await call_next(request)
        response.headers["Server-Timing"] = timing.finish(steps, key, (time.perf_counter() - t0) * 1000)
        return response

    async def team_rows(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The definitions' rows for a delta's headers, with what a team with no record holds (TD-781)."""
        return await rd.with_lanes(_aged(teamrun.rows(await defs(), sessions, await home_waiting())), sessions)

    flow_cache: dict[str, Any] = {"flows": {}}

    async def flow_views(sessions: list[dict[str, Any]], org: orgmod.Org | None = None) -> dict[str, Any]:
        """Each team's `teamrun.flow_view` (§4.9c *What is shown*, *Switching*): read when the Sessions page
        is drawn and after an Apply, off the loop, and kept for the deltas — a plan reads files (a
        node team's over the link), so a delta never reads it. A node draws none: the org is the
        home's (§4.4a). A failed read keeps the last."""
        if hosts.is_node():
            return {}
        here = host_name()

        def read() -> dict[str, Any]:
            with timing.step("flows"):  # each team's plan, its files and its RPCs: a page's step (TD-893)
                o = org or org_here()[0]  # fresh, as the page's strip reads it: not the deltas' cached definitions
                out: dict[str, Any] = {}
                # every team: one with no `flows:` is read on its seats alone, and only while live (TD-399)
                for n in o.teams:
                    try:  # one team that fails to read costs its own header the flow, not every team's
                        out[n] = teamrun.flow_view(rpc, o, n, here, sessions)
                    except Exception:  # noqa: BLE001
                        log.debug("team %s: its flows were not read", n, exc_info=True)
                return out

        try:
            flow_cache["flows"] = await asyncio.to_thread(read)
        except Exception:  # noqa: BLE001 — a read that failed keeps the last; it never costs the page
            log.debug("the flows read failed; the last reading stands", exc_info=True)
        # what every card a delta draws reads of it (`cards.flow_mark`): the flow by team, the acts by id
        got = flow_cache["flows"]
        refill(cards_mod.FLOWS, {n: str(v["flow"]) for n, v in got.items() if v.get("flow")})
        acts = {
            str(d["id"]): str(d.get("act") or "")
            for v in got.values()
            for d in v.get("differences") or []
            if d.get("id")
        }
        refill(cards_mod.FLOW_ACTS, acts)
        to = {str(d["id"]): str(d["to"]) for v in got.values() for d in v.get("differences") or [] if d.get("to")}
        refill(cards_mod.FLOW_RENAMES, to)
        return got

    async def group_heads(
        known: dict[str, dict[str, Any]],
        repos: Mapping[str, Any] | None = None,
        doing: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        """The team groups as the events stream ships them (design §4.5a **team groups**): per group
        its key, the member ids in order, and the header rendered by the same template the page
        uses — so the client moves cards between groups and swaps headers without composing any
        markup of its own. `None` means "flat grid", exactly as the page renders it."""
        return (await heads(known, repos, doing))["groups"]

    async def heads(
        known: dict[str, dict[str, Any]],
        repos: Mapping[str, Any] | None = None,
        doing: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """What every delta carries for the page's layout: the groups (`group_heads`) and the
        rollup's markup (§4.5a *Sessions: rollup*, TD-176 slice 4), both from one grouping of the fleet."""
        fleet = list(known.values())
        seats, waits = await seats_of(fleet), await person_waits()  # *waiting* (§4.2, TD-428)
        rows, marks = await team_rows(fleet), await work_marks()
        flows, balance, needs = flow_cache["flows"], work_cache["balance"], needs_cache["rows"]
        spend = await rd.team_spend()  # each header's *spend* figure (TD-832)
        projects = list((await defs()).projects.values())

        def build() -> dict[str, Any]:
            vs = [view(s, fleet, seats=seats, repos=repos, waits=waits) for s in fleet]
            groups = team_groups(
                vs,
                rows,
                repos,
                doing,
                marks,
                flows,  # the page load's reading: a delta reads no plan
                balance,  # the home's balance marks, read beside `work` (TD-330)
                needs,  # a member's open ask to the person: its team's *asked you* line (TD-354)
                spend,
            )
            # the layout made once, for the groups and the rollup's rows (TD-1204)
            layout = org_layout(groups, repos, projects, vs)
            ro = templates.get_template("rollup.html").render(ro=rollup(layout, vs))
            return {"groups": render_heads(layout), "rollup": ro}

        # off the loop (TD-670): a view of every record and every header rendered held the loop up to
        # ~300 ms a regroup on the live home with a Sessions page open; the events run calls this under
        # its lock, so no delta changes `repos` or `doing` while the thread reads them
        return await asyncio.to_thread(build)

    work_cache: dict[str, Any] = {"at": 0.0, "work": None, "waiting": None, "balance": None}

    async def home_reading(fresh: bool = False) -> None:
        now = time.monotonic()
        if fresh or work_cache["work"] is None or now - work_cache["at"] > DEFS_TTL:
            got: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                got = dict(await call("host"))
            with contextlib.suppress(Exception):  # the teams' stop times, for the headers a delta re-renders (TD-337)
                uiconf.set_read(await call("settings"))
            work_cache.update(
                at=now,
                work=dict(got.get("work") or {}),
                waiting=dict(got.get("waiting") or {}),
                balance=dict(got.get("balance") or {}),
            )

    async def home_waiting(fresh: bool = False) -> dict[str, Any]:
        """What each live session waits on (`host`'s `waiting`, §4.9a *Waiting is read, never
        declared*, TD-274), cached as `work_marks` is: a member with a question out to the person
        keeps its team from *concluded*, as it keeps it from the tick's wind-down. `fresh` reads
        past the cache, for an answer that decides whether Start is offered."""
        await home_reading(fresh)
        return work_cache["waiting"] or {}

    async def work_marks() -> dict[str, Any]:
        """The home's `work_waiting` marks by team (`host`'s `work`, §6 rule 8), `{}` when the agent
        cannot give them — an older agent, a node: the card then carries no note. Read at most once
        in `DEFS_TTL` seconds, `identity_info`'s idiom, so a delta storm never asks per render."""
        await home_reading()
        return work_cache["work"] or {}

    async def person_view() -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The mail and the state rows of one Inbox request — over **one** `list`. Both halves need
        the fleet (the mail for its senders' names, the states for the records themselves), and
        this runs on every page load and every poll: two fleet lists on that path would be two for
        no reason (review of PR #251)."""
        fleet = await call("list")
        return await person_inbox(fleet), await person_states(fleet)

    def inbox_html(sections: dict[str, Any], origin: str = "") -> dict[str, str]:
        """Each section's rows, rendered by the one template the page itself renders them with, so
        a poll replaces a section without the client composing any markup — the shape the events
        stream already uses for team headers. Jinja escapes every field, and a mail row's text goes
        through the closed-subset renderer (`shaped`), which is what keeps what a session wrote
        text and nothing else (TD-071 item 8, TD-138)."""
        rows = templates.get_template("inbox_rows.html")
        return {k: rows.render(rows=sections[k], section=k, origin=origin) for k in INBOX_SECTIONS}

    h = SimpleNamespace(
        call=call,
        render_card=render_card,
        defs=defs,
        team_rows=team_rows,
        home_waiting=home_waiting,
        person_waits=person_waits,
        seats_of=seats_of,
        group_heads=group_heads,
        heads=heads,
        flow_views=flow_views,
        repo_facts=repo_facts,
        repos=rd.repos,  # the `repos` reading, once per request (TD-739)
        with_lanes=rd.with_lanes,  # what a team with no record holds, its card's note (TD-781)
        identity_info=identity_info,
        person_states=person_states,
        person_view=person_view,
        person_inbox=person_inbox,
        board_items=board_items,
        board_view=board_view,
        board_all=rd.board_all,  # every open board row, a Queue card's fold read by its key (TD-891)
        inbox_html=inbox_html,
        settings_at=settings_at,  # the person's settings read's clock: a write here resets it (TD-174)
        queue_cards=rd.queue_cards,  # where an Inbox row is drawn (§4.5 screen 6, TD-771)
        team_spend=rd.team_spend,  # each team card's *spend* figure (TD-832)
        needs_cache=needs_cache,  # the Inbox's needs rows for the Org's *asked you* lines (TD-354)
        # the Inbox's counts, kept once and pushed (§4.4, TD-616); `LocalClient` read when it connects
        counts=CountsKeeper(counts_now, client=lambda: LocalClient(), omit=REPOS_OMIT_PAGE),
    )
    for register in (
        _pages_routes,
        _new_routes,
        _sessions_routes,
        _teams_routes,
        _inbox_routes,
        _help_routes,
        _settings_routes,
        _stream_routes,
    ):
        register(app, h)
    return app


def _pages_routes(app: FastAPI, h: SimpleNamespace) -> None:
    """The Sessions page and Focus (design §4.5)."""
    call, seats_of, identity_info, board_items = h.call, h.seats_of, h.identity_info, h.board_items
    repo_facts, board_view, flow_views = h.repo_facts, h.board_view, h.flow_views

    @app.get("/", response_class=HTMLResponse)
    async def org(request: Request):
        # An unreachable agent still gets a page: the banner + Retry are the recovery path
        # (design §4.5 unreachable hosts), never a bare 503.
        repos_omit(REPOS_OMIT_PAGE)
        agent_down = False
        usage: dict[str, Any] = {}
        person_needs = person_fyi = person_overdue = person_queue_n = 0
        info: dict[str, Any] | None = None
        entries: list[dict[str, Any]] = []
        handed: Any = ()
        try:
            sessions = await call("list")
            usage = await call("usage")
            with contextlib.suppress(Exception):  # an agent before TD-100 slice 1 has no `gate`: no lines
                usage = with_lines(usage, await call("gate"))
            usage = usage_accounts(usage, sessions)  # one chip per account (§4.5a, TD-122)
            info = await call("host")
            try:
                # the top bar's number: the Inbox page's **Needs you** section, and not unread mail
                # (§4.5a **Inbox page**, TD-069 steps 1–2) — mail *and* the session states, from the
                # same `inbox_sections` the page uses, so the two numbers cannot drift apart
                person = await call("inbox")
                entries = person["entries"]
                handed = person.get("handed") or ()
            except HTTPException as e:
                # a node whose link is down refuses the mailbox (§4.4a): the banner says why, and
                # the page is still this host's sessions
                if e.status_code == 503 or (info or {}).get("mode") != "node":
                    raise
        except HTTPException as e:
            if e.status_code != 503:
                raise
            sessions, agent_down = [], True
        icons = await role_icons(sessions)
        seats = await seats_of(sessions)
        repos, doing = ({}, {}) if agent_down else await repo_facts()
        waits = waits_of(entries)  # what each card waits on, from the inbox read above (§4.5a, TD-274)
        # the teams' flows before the cards: a member's flow mark reads them (`cards.flow_mark`)
        flows = {} if agent_down else await flow_views(sessions)
        vs = sorted(
            (view(s, sessions, icons=icons, seats=seats, repos=repos, waits=waits) for s in sessions), key=card_order
        )
        # the needs-you badge is the same predicate the Inbox rows are (review of PR #251): a
        # record the Sessions page counts and the Inbox did not list was the two pages disagreeing in public
        counts = {"needs-you": sum(1 for v in vs if state_kind(v) in NEEDS_YOU_ROWS)}
        counts.update({k: sum(1 for v in vs if v["state"] == k) for k in ("limited", "stalled?")})
        strip = teams_view(sessions, (info or {}).get("waiting") or {})
        if not agent_down:  # what a team with no record holds, its card's note (§6 rule 8, TD-781)
            await h.with_lanes(strip["teams"], sessions)
        id_info = {} if agent_down else await identity_info()
        boards = [] if agent_down else (await board_items())[0]
        # §4.5a *Inbox row: promote* (TD-132 slice 3): the same rows the Inbox counts, from the
        # `host` reading this page already took, so the top bar and the Inbox cannot disagree
        promos = [] if agent_down else promote_rows((info or {}).get("promotes"))
        # …and the team start rows (§4.5a, §6 rule 8), from the same reading
        work = {} if agent_down else (info or {}).get("work") or {}
        promos += work_rows(
            work, {r["name"]: r["wound_down"] for r in strip["teams"] if r.get("wound_down")}, records=sessions
        )
        promos += red_pr_rows(repos, sessions)  # …and a red PR of a repo no team services (§4.5a, TD-613)
        # …and an account whose CI never starts (§4.5a *Inbox row: CI not starting*, TD-687)
        promos += ci_not_run_rows(None if agent_down else (info or {}).get("ci_spells"))
        h.needs_cache["rows"] = []  # the host agent down, or nothing waiting: no *asked you* line (TD-354)
        if entries or handed or vs or boards or promos:
            secs = inbox_sections(
                entries,
                states=state_rows(
                    vs,
                    host_alarms=alarm_view(id_info.get("alarms")),
                    host=str(id_info.get("host") or host_name()),
                    identity_mode=str(id_info.get("mode") or ""),
                )
                + promos,
                boards=boards,
                fleet=sessions,
                handed=handed_rows(handed, {s.get("id"): s for s in sessions}, datetime.now(UTC)),
                cards=await h.queue_cards(),
            )
            # the rollup's *in the Inbox* is the Inbox tab's number (TD-932); *m overdue* still counts both homes
            tabs = tab_counts(secs)
            person_needs, person_queue_n, person_fyi = tabs["person_needs"], tabs["person_queue_n"], tabs["person_fyi"]
            person_overdue = secs["overdue_n"]
            h.needs_cache["rows"] = secs["needs"]
        return templates.TemplateResponse(
            request,
            "org.html",
            {
                "sessions": vs,
                # project → repo → team (§4.9 *The Sessions page*, TD-725), from the team groups
                "groups": (
                    layout := org_layout(
                        team_groups(
                            vs,
                            strip["teams"],
                            repos,
                            doing,
                            work,
                            flows,
                            {} if agent_down else (info or {}).get("balance"),
                            h.needs_cache["rows"],
                            {} if agent_down else await h.team_spend(),
                        ),
                        repos,
                        (await h.defs()).projects.values(),
                        vs,
                    )
                ),
                # the layout's items, the rows in the page's order (TD-1204); the flat page's sessions are `vs`
                "rollup": rollup(layout, vs),
                "strip": strip,
                "counts": counts,
                "host": host_name(),
                "active": "Sessions",
                "agent_down": agent_down,
                "volatile": hosts.local_host().volatile,
                "usage": usage,
                "person_needs": person_needs,
                "person_queue_n": person_queue_n,
                "person_overdue": person_overdue,
                "person_fyi": person_fyi,
                "node_banner": node_banner(info),
                "build_chip": None if agent_down else await chip_build(call, info),
                "identity_note": identity_note(id_info),
                "restart_note": "" if agent_down else restart_note(info, id_info),
                "editor_note": uiconf.open_in().error,
                "migrate_note": uiconf.migrate_note(),
            },
        )

    SHOT_READ_WAIT = 10.0  # seconds one image from another host may take (TD-300): a hung node is a 404

    @app.get("/repo/{name}/shot/{shot}")
    async def repo_shot(name: str, shot: str, host: str = ""):
        """A look's screenshot (design §4.5a **Inbox row: a look**, TD-292 slice 3): one `.png` of
        `docs/mockups/reviews/` of a registered repo, as `origin/<default>` holds it, and nothing
        else — any other name, repo or file is a 404. `host` names the host whose registry holds the
        repo when it is not this one, and the image is read there (`host_shot`, TD-300)."""
        data: bytes | None = None
        if host and host != host_name():
            if SHOT_NAME.fullmatch(shot):
                # unreachable, refused, slow past `SHOT_READ_WAIT`, or bad base64: a 404
                with contextlib.suppress(HTTPException, ValueError, TimeoutError):
                    got = await asyncio.wait_for(call("host_shot", host=host, repo=name, name=shot), SHOT_READ_WAIT)
                    data = base64.b64decode(str((got or {}).get("png") or "")) or None
        else:
            root = shot_root(name)
            data = await asyncio.to_thread(shot_bytes, root, shot) if root is not None else None
        if data is None:
            raise HTTPException(404, "no such screenshot")
        return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})

    @app.get("/repo/{name}", response_class=HTMLResponse)
    async def repo_page(request: Request, name: str, part: str = ""):
        """The **Repo** page (design §4.5 screen 11, TD-176 slice 5, TD-740): the repo's group of the Org,
        expanded — its line with the Repo facet, every servicing team's whole card and its no-team
        strip, by the Org's own layout and partials (`repo_items`) — then the lists behind the
        numbers: Open PRs, Technical debt, Recently completed, Waiting on you, Doing. A registered repo
        no team services has a page too, its line alone above the lists. `part=1` is the page's own
        refresh: the lists without the chrome or the cards, which the Org's deltas keep. A folded list goes
        to its fold and Recently completed to its window (`win`, *day*), the rest by `part=1` with `win` and
        `open`, the lists unfolded and an anchor's id (§4.5 *Page loads*: *only what is shown*, TD-882)."""
        repos_omit(REPOS_OMIT_PAGE)
        now = datetime.now(UTC)
        repos, doing = await repo_facts()
        r = next((v for v in repos.values() if isinstance(v, dict) and v.get("name") == name), None)
        if r is None:
            raise HTTPException(404, f"no registered repo is named {name!r} — ao repo --all lists them")

        def org_files() -> orgmod.Org:
            with timing.step("files"):  # the org file and every registered repo's `teams:` (TD-893)
                return org_here()[0]

        # Every read that waits on no other, at once (§4.5 *Page loads*, TD-893): the RPCs, the board, and
        # the definitions on a worker thread, read fresh once for the page and its flows (the board's and the
        # pills' are the cached `defs`)
        first = await asyncio.gather(
            call("list"),
            call("host"),
            h.person_waits(),  # *waiting* (§4.2, TD-428)
            asyncio.to_thread(org_files),
            board_view(),
            call("queue", omit=["completed"]),
            *(() if part else (call("usage"), call("gate"))),  # the top bar's chip, handed to it below
            return_exceptions=True,
        )
        for x in (first[0], first[2], first[3], first[4]):
            if isinstance(x, BaseException):
                raise x  # the fleet and what never refuses fail the page, as each did read in turn
        sessions, waits, org, (board, _) = first[0], first[2], first[3], first[4]
        # an older agent or a node's link down: the headers lose their notes, and the kind lists stand
        info: dict[str, Any] = {} if isinstance(first[1], Exception) else dict(first[1])
        queue: dict[str, Any] | None = None if isinstance(first[5], Exception) else first[5]
        icons, seats, flows, spend, defs = await asyncio.gather(
            role_icons(sessions), seats_of(sessions), flow_views(sessions, org), h.team_spend(), h.defs()
        )
        with timing.step("views"):
            vs = [view(s, sessions, icons=icons, seats=seats, repos=repos, waits=waits) for s in sessions]
        strip = teams_view(sessions, info.get("waiting") or {})
        await h.with_lanes(strip["teams"], sessions)  # what a team with no record holds (TD-781)
        with timing.step("groups"):
            # the Org's own groups and layout (§4.9 *The Sessions page*), cut to this repo's items (TD-740)
            groups = team_groups(
                vs,
                strip["teams"],
                repos,
                doing,
                info.get("work") or {},
                flows,
                info.get("balance"),
                h.needs_cache["rows"],
                spend,
                repo_page=True,
            )
            # no team anywhere (the Org's flat page): the repo's sessions still stand under its line, as a strip
            groups = groups if groups is not None else [{"team": NO_TEAM, "members": vs}]
            items = repo_items(org_layout(groups, repos, defs.projects.values(), vs, now), name)
        serving = [g for g in items if g["kind"] == "team"]
        here_root = str(Path(str(r.get("root") or "")).resolve())
        named = repo_teams(org, host_name()).get(here_root, "")
        teams = list(dict.fromkeys([*(g["team"] for g in serving), *([named] if named else [])]))
        members = [m for g in serving for m in g["members"]]
        motion = [x for g in serving for x in (g.get("summary") or {}).get("motion") or []]
        facet = next((g.get("facet") for g in items if g["kind"] == "repo"), None)
        # every seat's inbox and sent mail, read as a person's read (§4.9c *What is shown*): a seat by
        # the definitions or its record, running or not — a view's `seat` is only an empty one's
        seat_ids = {*seats, *(str(s.get("id")) for s in sessions if s.get("seat"))}
        readers = [m for m in members if m["id"] in seat_ids or str(m.get("role") or "") == "techlead"]
        mail = await asyncio.gather(  # each seat's two reads, every seat at once
            *(call("inbox", id=m["id"], **sent) for m in readers for sent in ({}, {"sent": True})),
            return_exceptions=True,
        )
        # an older home or a failed read: the asks still say who waits
        entries = [x.get("entries") or [] if isinstance(x, dict) else [] for x in mail]
        reads = [(str(m.get("name") or m["id"]), entries[2 * k], entries[2 * k + 1]) for k, m in enumerate(readers)]
        standing = pr_standing(reads, now)
        rel = (r.get("ledger") or {}).get("path") or ""
        ledger_file = str(Path(str(r.get("root") or "")) / rel) if rel else ""
        # (3) Waiting on you: the Inbox's horizon cut to the repo — due rows, coming up, the fold, the line (TD-220)
        hz = with_standings(horizon_of(board, str(r.get("root") or "")), sessions, now)
        boards = hz["due"]
        # the board's columns are the servicing teams' flows' stages, read off the loop (§4.5 screen 11, TD-903)
        flows_here = await asyncio.to_thread(repo_board.team_stages, org, teams, str(r.get("root") or ""))
        with timing.step("lists"):  # the ledger's lists, the cards and the rows the page draws (TD-893)
            # the teams' lanes over the ledger and the board's work orders (§4.4 *In a team's lanes*, TD-384)
            lanes = teamrun.repo_lanes(teamrun.lane_entries(r), str(r.get("root") or ""), sessions)
            lists = ledger_lists(r, motion, lanes, now)
            # only what is shown (§4.5 *Page loads*, TD-882): the lists unfolded, and an anchor's id not yet sent
            opened = [k for k in str(request.query_params.get("open") or "").split(",") if k]
            cards = debt_cards(queue, name, lists) if (r.get("ledger") or {}).get("entries") is not None else None
            drows = repo_doing(serving)
            newest: dict[str, str] = {}
            for d in drows[0]:  # newest first: each doer's first is its newest kept line
                newest.setdefault(str(d.get("name") or ""), str(d.get("text") or ""))
            bd = repo_board.board(
                cards,
                lists,
                flows_here,
                members,
                name,
                opened,
                newest,
                [e for e in lists[0]["rows"] if e.get("work_order")] if lists else [],
            )
            # For you's rows are the Inbox's ledger rows, and a due board line naming one is drawn in its place
            # and not again under Waiting on you (§4.5 screen 11 *For you*)
            fy = ledger_for_you({str(r.get("root") or ""): r}, sessions, {here_root: named} if named else None, now)
            fy_rows = {str(x.get("id") or ""): x for x in ledger_rows(fy)}
            fy_ids = {str(x["id"]) for g in bd["foryou"]["groups"] for x in g["rows"]} | {
                str(x["id"]) for x in bd["foryou"]["claimed"]
            }
            fy_boards: dict[str, list[dict[str, Any]]] = {}
            for b in boards:
                if hit := next((i for i in b.get("refs") or () if i in fy_ids), None):
                    fy_boards.setdefault(hit, []).append(b)
            placed = {id(b) for bs in fy_boards.values() for b in bs}
            boards = [b for b in boards if id(b) not in placed]
            ctx = {
                "r": r,
                "name": name,
                "groups": items,  # the Org's items, drawn by its partials (TD-740)
                "facet": facet,
                "teams": teams,
                "prs": pr_rows(r, members, standing, now, sessions, [g["members"] for g in serving]),
                "lists": lists,
                # the board: For you, the flows' worker stages, Review, Merged (§4.5 screen 11, TD-903)
                "bd": bd,
                "fy_rows": fy_rows,
                "fy_boards": fy_boards,
                "board_teams": len(teams),
                # (3) Recently completed: the window's closed entries and the PRs that closed them (TD-604)
                "completed": (completed := completed_rows(r, sessions, now, info.get("promotes"))),
                # the count line's lanes line, once per team servicing the repo (§4.4 *In a team's lanes*, TD-361)
                "lanes": [
                    ln
                    for team, got in lanes.items()
                    if (ln := lanes_line(team, got, teamrun.lane_kinds(r), entries_by_id(r)))
                ],
                # under them, *needs a team* and each stale-team note (§4.4 *An entry names its team*, TD-764)
                "team_notes": team_notes(r, [t["team"] for t in entry_teams(org, here_root, host_name())], sessions),
                "boards": boards,
                "horizon": hz,
                "doing": drows[0],
                "chips": doing_chips(drows[0], [g["team"] for g in serving]),
                "doer_w": drows[1],
                # a file link (§4.6, TD-689): the file form with `:1`, the repo's checkout opened first; a v2
                # directory's is the folder form with no line, one launch (§4.5a *Open ledger*, TD-1146)
                "ledger_editor": ledger_link(ledger_file) if ledger_file else None,
                # the seams the repo leaves unset, and a ledger that is not there (§4.5a, TD-591)
                "seams": missing_seams(r),
                "host": host_name(),
                "active": "",
                "part": bool(part),  # the re-read carries the title line and the seams, swapped in place
            }
            # only what is shown (§4.5 *Page loads*, TD-882): the counts read the lists whole first
            ctx["win"] = send_folds(lists, completed, repo_window(request.query_params), opened)
        if not part:  # the page's top bar, from the reads above; the part is the page's body alone
            usage, gate = first[6:8]  # read once: a refused `usage` is no chip, a refused `gate` no lines
            ctx["usage"] = (
                {}
                if isinstance(usage, Exception)
                else await chip_usage(call, sessions, usage=usage, gate={} if isinstance(gate, Exception) else gate)
            )
            ctx["build_chip"] = await chip_build(call, info or None)
        return templates.TemplateResponse(request, "repo_part.html" if part else "repo.html", ctx)

    @app.get("/focus/{sid}", response_class=HTMLResponse)
    async def focus(request: Request, sid: str, window: str = ""):
        repos_omit(REPOS_OMIT_PAGE)
        try:
            # loading the page is not the look (§4.2 *Unseen*, TD-1228): the page sends `seen` once it is visible
            s = await call("get", id=sid)
        except HTTPException as e:
            if e.status_code == 503:
                return RedirectResponse("/", status_code=303)  # the Org shows the down banner
            raise
        known = True
        try:
            fleet = await call("list")
        except HTTPException:  # the record we already have still renders; membership just empties
            fleet, known = [s], False  # …and Ready to close says it does not know, rather than pass
        repos = (await repo_facts())[0]  # the PR's mark on the report line (TD-193)
        v = view(
            s,
            fleet,
            fleet_known=known,
            icons=await role_icons([s]),
            seats=await seats_of([s]),
            repos=repos,
            waits=await h.person_waits(),  # the header's *waiting* chip (§4.5a, TD-274)
        )
        # §4.5a *Git card: changed files* (TD-628): the porcelain's paths are relative to the worktree's top
        # level, the directory or above it — read here, where the links are drawn (a record on this host)
        here = v.get("editor") and v.get("host") == host_name() and v.get("dir")
        v["git_root"] = await asyncio.to_thread(gitinfo.toplevel, Path(str(v["dir"]))) if here else ""
        return templates.TemplateResponse(
            request,
            "focus.html",
            {
                "s": v,
                # §4.5a **Reports**: the session's repo's PR marks, the page's first load of the per-repo
                # map the `repos` push keeps (§4.4 *Per-session views*, TD-617)
                "pr_marks": {v["pr_repo"]: repo_pr_marks(v["pr_repo"], repos[v["pr_repo"]])} if v["pr_repo"] else {},
                "host": host_name(),
                "active": "Sessions",
                "usage": await chip_usage(call, fleet if known else None),
                "build_chip": await chip_build(call),
                # design §4.5a **Pop out** (TD-046): the same Focus, without the nav and the top bar
                "popped": window == "1",
                # §4.5a **Reports** (TD-150): the base a claim in review's PR number links from
                "pr_base": await asyncio.to_thread(reviewmod.repo_web, s.get("repo") or s.get("dir")),
                # §4.5a *Focus composer* **prompt chips** (TD-170): the role's saved prompts, for a
                # session whose composer is open — an interactive one — and none otherwise
                "prompts": [] if s.get("unattended") else await asyncio.to_thread(role_prompts, s),
                # §4.5a *Focus: copy on select* (TD-174): the person's, from `settings.yml`
                "copy_on_select": uiconf.copy_on_select(),
                # §4.5a *Focus composer* **the bar** (TD-500): folded to one bar under the terminal, or open
                "composer": uiconf.composer(),
                # §4.5a *Focus side panel, Session card* **rounds** line (TD-191): display only
                "rounds": rounds_lines(s, await _rounds_tail(call, s)),
            },
        )

    @app.get("/transcript/{sid}", response_class=HTMLResponse)
    async def transcript(request: Request, sid: str, before: int | None = None, part: str = ""):
        """Screen 9, **Transcript** (design §4.5, §4.5a *Transcript*, TD-166): the record's tool
        transcript through the `transcript` RPC on the record's host — a read, gated by nobody (§9
        invariant 11), which never marks the session seen. `part=1` with `before` is *earlier
        turns*: the twenty before the first shown, as the fragment the page puts above them."""
        if part:
            try:
                t = await call("transcript", id=sid, before=before, turns=TRANSCRIPT_TURNS)
            except HTTPException as e:
                return HTMLResponse(f'<p class="note">{html.escape(str(e.detail))}</p>', status_code=e.status_code)
            return templates.TemplateResponse(request, "transcript_turns.html", {"t": transcript_view(t)})
        try:
            s = await call("get", id=sid)
        except HTTPException as e:
            if e.status_code == 503:
                return RedirectResponse("/", status_code=303)  # the Org shows the down banner
            raise
        t, error = None, ""
        try:
            t = transcript_view(await call("transcript", id=sid, before=before, turns=TRANSCRIPT_TURNS))
        except HTTPException as e:  # no tool session id, no file on its host: the page says which
            error = str(e.detail)
        v = view(s)
        here = v["host"] == host_name()
        editor = transcript_editor(t["path"], here) if t else None
        return templates.TemplateResponse(
            request,
            "transcript.html",
            {
                "s": v,
                "t": t,
                "error": error,
                "editor": editor,
                # a path in a turn is a link where **VS Code** is drawn, and absent with it (§4.6, TD-691)
                "paths": transcript_paths(str(v.get("dir") or "")) if editor else None,
                "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "host": host_name(),
                "active": "Sessions",
                "usage": await chip_usage(call),
                "build_chip": await chip_build(call),
            },
        )


async def _rounds_tail(call: Callable[..., Any], s: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The session's last two round-log lines (design §4.8, TD-191), or None when the host agent
    cannot say (an older one, a node out of reach): the line is then left out, never *no round log*."""
    try:
        got = await call("log_tail", id=s["id"], n=2)
    except HTTPException:
        return None
    return got if isinstance(got, list) else None


def rounds_lines(s: dict[str, Any], entries: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The Session card's **rounds** line (design §4.5a, TD-191): the last two lines with their
    stamps, each marked *from an earlier run* when it is older than this record's start; `[]` is
    *no round log*, None is no line at all. Text a session wrote is only text (TD-071)."""
    if entries is None:
        return None
    start = str(s.get("created") or "")[:16] + "Z"  # the stamps are to the minute
    return {
        "lines": [
            {
                "at": str(e.get("at") or ""),
                "text": str(e.get("text") or ""),
                "earlier": bool(start != "Z" and str(e.get("at") or "") < start),
            }
            for e in entries
            if isinstance(e, dict)
        ]
    }


# The Profile pick's *shell (no agent)* (design §4.5a New session **the form**, TD-284): a
# value, not a profile — a shell is the one adapter with no profile, and no profile is named so.
SHELL_PICK = ":shell"


def profile_adapter(profile: str) -> str:
    """The adapter a New session form's pick starts (§4.5a New session **the form**): the named profile's,
    else the default profile's, else Claude Code's — every profile names its adapter, so the form asks
    for the tool once. A name `profiles.yml` does not hold is the create's to refuse, not this."""
    try:
        profs, default = profiles_mod.load()
    except ValueError:
        return profiles_mod.DEFAULT_ADAPTER
    p = profs.get(profile) or profs.get(default)
    return p.adapter if p else profiles_mod.DEFAULT_ADAPTER


def tool_profile(profs: Mapping[str, profiles_mod.Profile], default: str, adapter: str) -> str:
    """The profile a prefill with a tool and no profile lands on (TD-284 slice 2): none when the
    default profile's tool is that one, or for a shell; else the first profile of that tool, so a
    Resume with changes… of a record with no profile does not quietly start another tool."""
    if not adapter or adapter == "shell" or (profs.get(default) and profs[default].adapter == adapter):
        return ""
    return next((k for k, p in profs.items() if p.adapter == adapter), "")


async def chip_build(call: Any, info: Any = None) -> dict[str, str] | None:
    """The top bar's **build** chip on every page (§4.5a, TD-539): `build_chip` over `info`, the
    page's own `host` answer, read here when it holds none. Any failure is no chip, never a page
    that fails: the chip is display only."""
    try:
        return await asyncio.to_thread(build_chip, info if info is not None else await call("host"))
    except Exception:  # noqa: BLE001
        return None


async def chip_usage(call: Any, sessions: Any = None, usage: Any = None, gate: Any = None) -> dict[str, Any]:
    """The top bar's **usage** chip on every page (§4.5a *Sessions top bar* **usage** chip, TD-287): the
    Org's reading — the accounts' windows, the gate's lines, one chip per account a live session's
    profile names. A page that already read `usage` and `gate` hands them over, and they are not read
    again (TD-884). Any failure is no chip, never a page that fails: the chip is display only."""
    try:
        if sessions is None:
            sessions = await call("list")
        if usage is None:
            usage = await call("usage")
        with contextlib.suppress(Exception):  # an agent before TD-100 slice 1 has no `gate`: no lines
            usage = with_lines(usage, gate if gate is not None else await call("gate"))
        return usage_accounts(usage, sessions)
    except Exception:
        return {}


def form_hosts(info: Mapping[str, Any]) -> list[dict[str, Any]]:
    """New session's **Host** pick (§4.5a New session **the form**, TD-284 slice 3): this host, then each
    `nodes:` entry of `hosts.yml` at a home, a container marked so, one with no live link disabled
    with its reason (`host`'s `links`, §4.4a). A node lists itself alone: its home routes the rest."""
    here = host_name()
    out: list[dict[str, Any]] = [{"name": here, "up": True, "note": "", "why": ""}]
    if hosts.is_node():
        return out
    links = info.get("links") or {}
    boxes = container_nodes()
    for name in hosts.nodes():
        if name == here:
            continue
        link = links.get(name) or {}
        up = bool(link.get("up"))
        why = "" if up else f"unreachable: {link.get('why') or 'never linked'}"
        out.append({"name": name, "up": up, "note": "container" if name in boxes else "", "why": why})
    return out


def form_repos(repos: list[str]) -> list[dict[str, str]]:
    """New session's **Repo** pick (§4.5a New session **the form**, TD-284 slice 4): each registered
    checkout on this host as *name · path*, in the registry's order; one whose directory is gone
    is left out rather than offered to fail."""
    out = []
    for r in repos:
        p = Path(r).expanduser()
        if p.is_dir():
            out.append({"name": p.name, "path": str(p)})
    return out


def remote_repos(repos: list[str]) -> list[dict[str, str]]:
    """The Repo pick for another host (§4.4a *The New session form on another host*, TD-294): its
    registry's checkouts as `host_repos` gives them, as they are — whether each is there is that
    host's to say, and its create says it."""
    return [{"name": Path(r).name, "path": str(r)} for r in repos if str(r).strip()]


def silent(host: str, e: HTTPException) -> str:
    """What the form says where a read of `host` failed: the home's words when they name the host
    (*node1 did not answer: …*, *runs on node1: unreachable since …*), else *<host> did not answer*."""
    detail = str(e.detail)
    return detail if host in detail else f"{host} did not answer: {detail}"


class HostSilent(ValueError):
    """The picked host did not answer a read the form needs: said in the note's place (§4.5a)."""


def away_host(host: str) -> str:
    """The picked host when it is not this one, else "" — the form reads this host as it always has."""
    h = host.strip()
    return h if h and h != host_name() else ""


def unanswered(host: str, e: HTTPException | str) -> str:
    """Add entry's words for a read of the team's host that failed (§4.5a *Open a session*, TD-1064):
    *<host> did not answer*, whichever read met it, with what the home said after it."""
    detail = str(e.detail if isinstance(e, HTTPException) else e)
    return detail if detail.startswith(f"{host} did not answer") else f"{host} did not answer: {detail}"


def entry_held_why(got: Mapping[str, Any], name: str) -> str:
    """Add entry's words for a name check's verdict (§4.5a *Add entry form: Name*), or "" where it is
    free: an exited or closed holder is not free here, where New session would supersede it."""
    verdict = got.get("verdict")
    if verdict in ("live", "suspended"):
        return str(got.get("message") or f"{name} is running — switch to it, or pick another name")
    if verdict == "supersede":
        return f"{name} names an exited session — pick another name"
    return ""


async def config_on(call: Any, host: str, directory: str) -> repoconfig.RepoConfig:
    """`directory`'s repo config on another host (§4.4a *The New session form on another host*,
    TD-294): `host_dir` gives the checkout's top level (`root`), and `repoconfig.load` reads its
    `.shiftlead.yml` and the role directories its `roles:` names through `host_files` — a team start's
    loader and reader, so the two cannot disagree (TD-313). The config's `read` blocks on the page's
    loop, so whatever resolves a role from it runs in a worker thread. Outside a checkout, the
    defaults for the directory, reading nothing there. A host that does not answer is `HostSilent`;
    a malformed file is `ValueError` in the loader's words."""
    try:
        seen = await call("host_dir", host=host, dir=directory)
    except HTTPException as e:
        raise HostSilent(silent(host, e)) from None
    root = str((seen or {}).get("root") or "")
    if not root:
        cfg = repoconfig.RepoConfig(root=Path(directory))
        cfg.read = repoconfig.unread  # never this host's disk at the same path
        return cfg
    read = teams.reader_on(files_on(call, asyncio.get_running_loop()), host, Path(root))
    try:
        cfg = await asyncio.to_thread(repoconfig.load, root, read=read)
        cfg.venv = teams.node_venv(host, host_name())  # a container node's briefs name its own launcher (TD-1014)
        return cfg
    except OSError as e:  # the host stopped answering between the two reads
        raise HostSilent(str(e)) from None


def files_on(call: Any, loop: asyncio.AbstractEventLoop) -> teams.Files:
    """`teams.Files` over the page's async `call`, for a compose run in a worker thread: Start on
    another host reads the role's brief there with `host_files` (§4.4a *The New session form on
    another host*, TD-294), through `teams.reader_on` — the team start's reader, confined to the
    checkout. A host that does not answer is `OSError`, which the role reports as its brief unread."""

    def files(host: str, directory: str, paths: list[str]) -> dict[str, str | None]:
        try:
            got = asyncio.run_coroutine_threadsafe(call("host_files", host=host, dir=directory, paths=paths), loop)
            return dict((got.result() or {}).get("files") or {})
        except HTTPException as e:
            raise OSError(silent(host, e)) from None

    return files


def repo_of(choices: list[dict[str, str]], directory: str) -> str:
    """The Repo choice a prefilled directory is (its path), or "" for *another directory…*."""
    if not directory.strip():
        return choices[0]["path"] if choices else ""
    want = os.path.realpath(os.path.expanduser(directory.strip()))
    return next((c["path"] for c in choices if os.path.realpath(c["path"]) == want), "")


async def attach_piece(
    call: Callable[..., Any],
    who: dict[str, Any],
    file: UploadFile | None,
    upload: str,
    offset: int,
    total: int | None,
    cancel: str,
) -> dict[str, Any]:
    """One piece of one file up the attach road (design §4.4 *Attachment drop*, TD-478), for `who` —
    `{id}`, a session's, or `{draft}`, the Add entry form's (§4.4 *The Add entry form's draft*,
    TD-630) — handed to the host agent's `attach`. A piece past `paths.ATTACH_PIECE_BYTES` is refused
    here (413) before the host agent is asked; `cancel` names its `upload`. Answers the route's JSON:
    `{path}` for the last piece, `{upload, bytes}` for one before it, `{cancelled}`; a draft's answer
    carries `draft`, the token the form names on every later piece."""
    if cancel:
        if not upload:
            raise HTTPException(400, "attach: cancel names the upload it cancels")
        got = await call("attach", **who, upload=upload, cancel=True)
        return {"ok": True, "cancelled": True, **_drafted(got)}
    if file is None:
        raise HTTPException(400, "attach: send the file's piece as `file`")
    raw = await file.read(paths.ATTACH_PIECE_BYTES + 1)
    if len(raw) > paths.ATTACH_PIECE_BYTES:
        mib = paths.ATTACH_PIECE_BYTES // (1024 * 1024)
        raise HTTPException(413, f"a piece of {file.filename or 'the file'} is past the {mib} MiB a piece may be")
    params: dict[str, Any] = {**who, "name": file.filename or "", "data": base64.b64encode(raw).decode("ascii")}
    if upload:
        params.update(upload=upload, offset=offset)
    elif total is not None:
        params["total"] = total
    got = await call("attach", **params)
    if "path" in got:
        return {"ok": True, "path": got["path"], **_drafted(got)}
    return {"ok": True, "upload": got["upload"], "bytes": got["bytes"], **_drafted(got)}


def _draft_of(body: dict[str, Any]) -> dict[str, str]:
    """The Add entry form's `draft`, where it attached files (TD-630): handed to the way out, which
    claims the folder at the press (§4.4 *The Add entry form's draft*); none where it attached nothing."""
    draft = body.get("draft")
    if draft is None or draft == "":
        return {}
    if not isinstance(draft, str):
        raise HTTPException(400, "draft is the token the form's first file was answered with")
    return {"draft": draft}


def _drafted(got: Any) -> dict[str, str]:
    """`draft` from an `attach` answer, where it carries one (TD-630)."""
    return {"draft": got["draft"]} if isinstance(got, dict) and got.get("draft") else {}


def _new_routes(app: FastAPI, h: SimpleNamespace) -> None:
    """New session: the form, its checks, and a shell (design §4.5a *New session*)."""
    call = h.call

    @app.get("/new", response_class=HTMLResponse)
    async def new_form(
        request: Request,
        dir: str = "",
        adapter: str = "claude-code",
        resume: str = "",
        # design §4.5a **Resume with changes…** (TD-081 step 2): the same fields a one-press
        # Resume carries, filled into the form instead of used. `why` is set when a press that
        # should have been silent landed here, and the form says so rather than leaving a person
        # to wonder which of the two controls they pressed.
        name: str = "",
        profile: str = "",
        role: str = "",
        team: str = "",
        lane: str = "",
        controllers: str = "",
        unattended: str = "",
        where: str = "here",  # a worktree record's Resume with changes… (TD-145)
        worktree: str = "",
        prefilled: str = "",
        why: str = "",
        host: str = "",
        # the opening prompt **Start session** would have sent (§4.5a *Inbox row: ledger entry*, TD-678)
        prompt: str = "",
        press: str = "",  # `start`: the landing is **Start session**'s, and the warning says so
    ):
        profs, default = profiles_mod.load()
        # registered repos (design §5 *Repos*: the home's roster and agent-cadence's, or `repos_registry`) first,
        # then recent directories; phase 1 reads the local host's file directly
        repos = hosts.local_host().repos()
        recent = repos + [d for d in await call("recent_dirs") if d not in repos]
        # a form filled in for another host (Resume with changes…) reads that host's registry (TD-294)
        picks, repo_why = form_repos(repos), ""
        if elsewhere_host := away_host(host):
            got = await repos_on(elsewhere_host)
            picks, repo_why, recent = got["repos"], got["why"], [r["path"] for r in got["repos"]]
        # design §4.5a New session **Controllers** picker (§4.8): the candidates are the sessions
        # holding `control` — nothing else could act on the new session anyway — live, or a seat on
        # call, whose id and grant survive the close for whoever fills it (TD-269, built by TD-276)
        sessions_now = await call("list")
        control_holders = [
            {"id": o["id"], "name": o.get("name") or o["id"], "on_call": teamrun.on_call(o)}
            for o in sessions_now
            if has_control(o.get("capabilities")) and (o.get("state") not in ("closed", "exited") or teamrun.on_call(o))
        ]
        # design §4.5a New session **Role** pick: the built-ins, plus what the prefilled directory's
        # repo redefines; `/api/roles` refreshes the list as the directory is typed (TD-040 step a).
        roles = await roles_view(dir, host)
        return templates.TemplateResponse(
            request,
            "new.html",
            {
                "host": host_name(),
                "active": "Sessions",
                "usage": await chip_usage(call, sessions_now),
                "build_chip": await chip_build(call),
                "profiles": profs,
                "default_profile": default,
                "recent": recent,
                "form_repos": picks,
                "repo_pick": repo_of(picks, dir),
                "repo_host": elsewhere_host or host_name(),
                "repo_why": repo_why,
                "form_hosts": form_hosts(await call("host")),
                # the Profile pick's last choice (§4.5a New session **the form**, TD-284 slice 2)
                "shell_pick": SHELL_PICK,
                # each of Host, Project and Profile ends its note with its file and **Open file**
                "files": {
                    "hosts": str(hosts.hosts_file()),
                    "profiles": str(profiles_mod.profiles_file()),
                    "org": str(orgmod.org_file()),
                },
                "control_holders": control_holders,
                # design §4.5a New session **Grants** checkboxes: the grants a record may hold
                # (`sessionorc.models.GRANTS`, the same list `ao new --grant` offers), each with
                # the one-line warning the row asks for.
                "grants_all": list(GRANTS),
                # Jinja renders a missing key as empty, so a grant added to GRANTS without a note
                # would ship a silent, unexplained checkbox. Say so on the page instead (review of
                # PR #141); the test still fails first for anyone who runs them.
                "grant_notes": {g: GRANT_NOTES.get(g) or UNDESCRIBED_GRANT for g in GRANTS},
                "roles": roles["roles"],
                "default_controllers": roles.get("controllers") or [],
                # design §4.5a New session **Team** picker (§4.9 *A person in the team*, TD-173)
                "form_teams": teams_for_form(sessions_now),
                "prefill": {
                    "dir": dir,
                    "adapter": adapter,
                    "resume": resume,
                    "name": name,
                    "profile": profile or tool_profile(profs, default, adapter),
                    "role": role,
                    "team": team,
                    "lane": lane,
                    "controllers": [c for c in controllers.split(",") if c.strip()],
                    "unattended": unattended == "on",
                    "where": "worktree" if where == "worktree" else "here",
                    "worktree": worktree,
                    "host": host,
                    "prefilled": prefilled == "1",
                    "why": why,
                    "prompt": prompt,
                    "press": press,
                },
            },
        )

    def _roles_for(dir: str) -> dict[str, Any]:
        """The presets that resolve in `dir`'s repo, and the repo's `controllers:` default, for the
        form's pick-list and the Controllers picker's prefill (design §4.5a, §4.8 "Defaults fill
        membership at launch"). A malformed `.shiftlead.yml` is reported, not raised: the form still
        renders with the built-ins, and Start says what is wrong."""
        try:
            cfg = repoconfig.discover(dir or os.getcwd())
            found = [r.to_dict() for r in repoconfig.roles(cfg)]
        except ValueError as e:
            return {"roles": [r.to_dict() for r in repoconfig.roles(repoconfig.RepoConfig())], "error": str(e)}
        return {"roles": found, "controllers": cfg.controllers, "file": str(cfg.path) if cfg.path else None}

    async def roles_view(dir: str, host: str = "") -> dict[str, Any]:
        """`_roles_for` on the picked host (§4.4a *The New session form on another host*, TD-294):
        another host's repo config read there, the built-ins with the reason when it cannot be."""
        if not (h := away_host(host)):
            return _roles_for(dir)
        builtins = [r.to_dict() for r in repoconfig.roles(repoconfig.RepoConfig())]
        if not dir.strip():
            return {"roles": builtins}
        try:
            cfg = await config_on(call, h, dir.strip())
            found = [r.to_dict() for r in await asyncio.to_thread(repoconfig.roles, cfg)]
        except ValueError as e:  # HostSilent among them: said where the note is
            return {"roles": builtins, "error": str(e)}
        return {"roles": found, "controllers": cfg.controllers, "file": f"{h}:{cfg.path}" if cfg.path else None}

    async def repos_on(host: str) -> dict[str, Any]:
        """The Repo pick's choices on `host` (TD-294): this host's registry checked on this disk, another
        host's from `host_repos`; a host that does not answer gives none and says so."""
        if not (h := away_host(host)):
            return {"host": host_name(), "repos": form_repos(hosts.local_host().repos()), "why": ""}
        try:
            got = await call("host_repos", host=h)
        except HTTPException as e:
            return {"host": h, "repos": [], "why": silent(h, e)}
        return {"host": h, "repos": remote_repos([str(r) for r in (got or {}).get("repos") or []]), "why": ""}

    @app.get("/api/repos")
    async def api_repos(host: str = ""):
        """**Repo**'s choices on the picked host, re-read when Host changes (§4.5a, TD-294)."""
        return await repos_on(host)

    @app.get("/api/team_review")
    async def api_team_review(team: str = "", dir: str = "", host: str = ""):
        """The line under New session's **Team** picker (design §4.5a): the reader a session started
        in `team` from `dir` gets when its role has none — `dir`'s repo read on the picked host."""
        if not team:
            return {"review": None, "line": ""}
        if (h := away_host(host)) and dir.strip():
            try:
                cfg = await config_on(call, h, dir.strip())
            except ValueError as e:
                return {"review": None, "line": f"⚠ {e}"}
            return await asyncio.to_thread(team_reader, team, dir, cfg)
        return await asyncio.to_thread(team_reader, team, dir)

    @app.get("/api/team_line")
    async def api_team_line(team: str = "", line: str = ""):
        """New session's **member line** fill (design §4.5a, §4.9 *A member started from the form*, TD-1167):
        the line's next member as `ao team add` would create it — its name, profile, lane and brief, under a
        flow the current flow's — or `why` it cannot be started (a line the definition does not name, one
        that sits out, a team that is not running, a definition that does not resolve)."""
        org, _notes = org_here()
        sessions = await call("list")
        try:
            t_ = teams.find(org, team)
            got = await asyncio.to_thread(
                teamrun.next_members, org, team, host_name(), sessions, teamrun.files_via(rpc)
            )
        except (teams.TeamError, ValueError, OSError) as e:
            return {"team": team, "line": line, "why": str(e)}
        x = got.get(line)
        if x is None:
            return {"team": team, "line": line, "why": f"team {team} has no member line {line!r}"}
        if isinstance(x, str):
            return {"team": team, "line": line, "why": x}
        return {
            "team": team,
            "line": line,
            "name": x.name,
            "dir": str(x.dir),
            "profile": x.profile,
            "lane": list(x.lane),
            "prompt": x.prompt or "",
            "grants": list(x.grants),
            "not_running": teamrun.not_running(t_, sessions),
            "why": "",
        }

    @app.get("/api/roles")
    async def api_roles(dir: str = "", host: str = ""):
        return await roles_view(dir, host)

    @app.post("/new")
    async def new_submit(
        name: str = Form(...),
        dir: str = Form(...),
        # the form sends none: Profile is the one tool pick (§4.5a New session **the form**, TD-284), and
        # the adapter is the picked profile's; `ao`-shaped posts and the tests may still name one
        adapter: str = Form(""),
        profile: str = Form(""),
        prompt: str = Form(""),
        resume: str = Form(""),
        unattended: str = Form(""),
        where: str = Form("here"),
        worktree: str = Form(""),
        role: str = Form(""),
        lane: str = Form(""),
        team: str = Form(""),
        until: str = Form(""),
        at: str = Form(""),
        controller: Annotated[list[str], Form()] = NO_CONTROLLERS,
        grant: Annotated[list[str], Form()] = NO_GRANTS,
        host: str = Form(""),
        line: str = Form(""),
        keep: str = Form(""),
    ):
        if team.strip() and line.strip() and unattended == "on" and not resume.strip():  # a Resume is the record's
            # a Role a member line names under a Team pick starts **a member** (§4.5a New session
            # **member line** fill, §4.9 *A member started from the form*, TD-1167): `ao team add`'s road
            return await member_submit(team.strip(), line.strip(), keep == "on", name, prompt, lane, profile)
        # the Host pick (TD-284 slice 3): sent only when it names another host — the home routes the
        # create there (§4.4a) — so a form on one host posts exactly what it always did (§4.4 skew rule)
        elsewhere = {"host": host.strip()} if host.strip() and host.strip() != host_name() else {}
        wt = None
        if where == "worktree":
            wt = worktree.strip() or naming.slug(name.strip() or "session")
        # The role preset (design §4.5a, §4.8) fills what the form left empty: the brief from its
        # template, the lane, its grants, and its profile unless one was picked. The Controllers
        # picker was prefilled from the repo's or preset's `controllers:` when the page loaded, so
        # what is ticked is what was meant — a person unticking the default is a decision.
        refs = [r.strip() for r in lane.split(",") if r.strip()]
        if profile == SHELL_PICK:  # *shell (no agent)*, the Profile list's last choice
            adapter, profile = "shell", ""
        preset = brief = ledger = made_from = cfg = None
        away = away_host(host)
        if adapter != "shell":
            try:
                # on another host, what the role resolves — its brief, the ledger, the team's reader —
                # is that host's repo, read there (§4.4a *The New session form on another host*, TD-294)
                cfg = (
                    await config_on(call, away, dir.strip())
                    if away
                    else repoconfig.discover(dir.strip() or os.getcwd())
                )
                ledger = cfg.ledger
                if role.strip():
                    # another host's config reads across the link, which blocks: off the loop
                    preset = (
                        await asyncio.to_thread(repoconfig.resolve_role, cfg, role.strip())
                        if away
                        else repoconfig.resolve_role(cfg, role.strip())
                    )
                    # a Team pick names the team's seat and manager in the brief, as a team start
                    # does for its members (`teams.brief_ids`, TD-253); `none` each without one
                    read = cfg.read if away else None
                    ids = (
                        await asyncio.to_thread(team_brief_ids, team.strip(), preset.name, cfg, read)
                        if team.strip()
                        else {}
                    )
                    if away:
                        brief, made_from = await asyncio.to_thread(preset.compose, refs or None, read=read, **ids)
                    else:
                        brief, made_from = preset.compose(refs or None, **ids)
            except (KeyError, ValueError) as e:
                raise HTTPException(400, str(e).strip('"')) from None
        # design §4.5a New session **Team** picker (§4.9 *A person in the team*, TD-173): a role's own
        # `review:` wins, else the team's reader, as `ao new --team` fills it. The Controllers
        # picker was ticked with the team's live manager when the team was picked.
        profile = profile or (preset.profile if preset else None) or ""
        adapter = adapter or profile_adapter(profile)
        review = preset.review if preset else None
        if team.strip() and adapter != "shell":
            got = await asyncio.to_thread(
                team_reader, team.strip(), dir.strip(), cfg if away else None, preset.name if preset else None
            )
            if got.get("flow") or review is None:  # under a flow the flow's reader, its own set aside (§4.9c)
                review = got["review"]
        text = prompt.strip() or brief
        # what the brief was made from (design §6 rule 7, TD-217): only when the brief is the preset's
        made_from = None if prompt.strip() else made_from
        # §4.9 *Home and reach*: the badge and the Project block are the directory's repo's, as
        # `ao new`'s are, from the same function — there is no Project picker (TD-722). A one-repo
        # project adds no block, and a directory in no known checkout carries neither.
        project, block = await asyncio.to_thread(
            lambda: teams.reach_block(org_here()[0], dir.strip() or os.getcwd(), away or host_name())
        )
        if block and adapter != "shell":
            text = block + text if text else block
            made_from = repoconfig.prefixed(made_from, block)
        s = await call(
            "create",
            name=name.strip() or "session",
            dir=dir.strip(),
            adapter=adapter,
            profile=profile,
            prompt=text,
            resume=resume.strip() or None,
            unattended=unattended == "on",
            **teams.gate_prompts(unattended == "on"),  # the usage gate's two texts (§6, TD-100)
            worktree=wt,
            repo=dir.strip() if wt else None,
            # The Grants checkboxes were ticked from the preset when the page loaded and as the
            # Role changed (design §4.5a), so what is ticked is what was meant — including an
            # untick, which is a person deciding this session does not get the grant.
            capabilities=[g for g in dict.fromkeys(grant) if g in GRANTS],
            lane=refs or (list(preset.lane) if preset else []),
            role=preset.name if preset else "",
            review=review,  # who reads its PRs (design §4.9b *The reader*): the role's, else the team's
            # §4.8 *A role has a context bound*: a default one only for an unattended session (TD-249)
            context_bound=preset.bound_for(unattended == "on") if preset else None,
            **({"prompt_from": made_from} if made_from else {}),
            ledger=ledger,
            controllers=[c for c in controller if c.strip()],
            project=project,  # a badge (§9 invariant 9): the directory's repo's project, as `ao new` sets it
            team=team.strip(),  # the badge and the group, as `ao new --team` sets it (§4.9)
            **stop_fields(until, unattended == "on"),
            **start_fields(at, unattended == "on"),
            **elsewhere,
        )
        # a scheduled record has no terminal yet: the Org shows its card with the *starts* note (§4.5a At)
        return RedirectResponse("/" if s.get("state") == "scheduled" else f"/focus/{s['id']}", status_code=303)

    async def member_submit(
        team: str, line: str, keep: bool, name: str, prompt: str, lane: str, profile: str
    ) -> RedirectResponse:
        """The form's member start (TD-1167): `teamrun.add` — run-only, what the person typed over the line's
        the record's for its run; or ticked *keep as a team member*, the line's size one higher and the
        member the line's alone. Refused on a team that is not running, as `ao team add` is."""
        if hosts.is_node():
            raise HTTPException(409, node_org_note())
        org, _notes = org_here()
        fields: dict[str, Any] = {}
        if not keep:
            try:
                x = (
                    await asyncio.to_thread(
                        teamrun.next_members, org, team, host_name(), await call("list"), teamrun.files_via(rpc)
                    )
                ).get(line)
            except (teams.TeamError, ValueError, OSError) as e:
                raise _team_http(e) from None
            if isinstance(x, teams.Launch):
                refs = [r.strip() for r in lane.split(",") if r.strip()]
                if name.strip() and name.strip() != x.name:
                    fields["name"] = name.strip()
                if prompt.strip() and prompt.strip() != (x.prompt or "").strip():
                    fields.update(prompt=prompt.strip(), prompt_from=None)
                if refs and refs != list(x.lane):
                    fields["lane"] = refs
                if profile and profile != SHELL_PICK and profile != x.profile:
                    fields.update(profile=profile, adapter=profile_adapter(profile))
        try:
            got = await asyncio.to_thread(teamrun.add, rpc, org, team, line, host_name(), keep=keep, fields=fields)
        except (teams.TeamError, ValueError, AgentError, AgentUnavailable) as e:
            raise _team_http(e) from None
        made = got.get("created")
        made = [made] if isinstance(made, dict) else list(made or []) + list(got.get("adopted") or [])
        sid = next((r.get("id") for r in made if isinstance(r, dict) and r.get("id")), None)
        return RedirectResponse(f"/focus/{sid}" if sid else "/", status_code=303)

    @app.post("/shell")
    async def shell(dir: str = Form(...), name: str = Form("")):  # unnamed: the agent names it (TD-030)
        s = await call("create", name=name, dir=dir, adapter="shell")
        return RedirectResponse(f"/focus/{s['id']}", status_code=303)

    @app.get("/api/dir_check")
    async def api_dir_check(dir: str = "", host: str = ""):
        """*another directory…*'s check as it is typed (§4.5a New session **the form**, TD-284 slice 4):
        whether the directory is there on the picked host (`host_dir` for another, TD-294), in the
        words the form prints. A host that does not answer is `exists: null`: said, never a refusal."""
        d = dir.strip()
        if (h := away_host(host)) and d:
            try:
                ok = bool((await call("host_dir", host=h, dir=d) or {}).get("exists"))
            except HTTPException as e:
                return {"dir": d, "exists": None, "why": silent(h, e)}
            return {"dir": d, "exists": ok, "why": "" if ok else f"no such directory on {h}"}
        ok = bool(d) and await asyncio.to_thread(lambda: Path(d).expanduser().is_dir())
        # whether **Where** may offer a worktree (TD-296 #3): a directory in no checkout has none to make
        git = bool(await asyncio.to_thread(gitinfo.toplevel, Path(d).expanduser())) if ok else None
        return {"dir": d, "exists": ok, "git": git, "why": "" if ok or not d else f"no such directory on {host_name()}"}

    @app.get("/api/worktrees")
    async def api_worktrees(repo: str = "", host: str = ""):
        """**Where**'s *or one nobody is in:* (§4.5a New session **the form**, TD-284 slice 4): the repo's
        worktrees under its main checkout's `.claude/worktrees/` that hold no live session and no agent
        the adapters can see — the occupancy check's reading of each — by name, for the chips."""
        if not repo.strip():
            return {"repo": "", "worktrees": []}
        if h := away_host(host):  # listed and their occupancy read where they are (§4.4a, TD-294)
            try:
                got = await call("host_worktrees", host=h, repo=repo.strip())
            except HTTPException as e:
                return {"repo": repo, "worktrees": [], "why": silent(h, e)}
            listed = (got or {}).get("worktrees") or []
            return {
                "repo": repo,
                "worktrees": [{"name": w["name"], "path": w["path"]} for w in listed if not w["occupied"]],
            }
        try:
            root = await asyncio.to_thread(gitinfo.worktree_path, Path(repo.strip()).expanduser(), "")
        except gitinfo.WorktreeError:
            return {"repo": repo, "worktrees": []}

        def listed() -> list[Path]:
            try:
                return sorted(p for p in root.iterdir() if (p / ".git").exists()) if root.is_dir() else []
            except OSError:
                return []

        found = await asyncio.to_thread(listed)
        # one worktree the agent cannot read is left out, not the list (review of #951)
        held = await asyncio.gather(*(call("occupancy", dir=str(p)) for p in found), return_exceptions=True)
        free = [
            {"name": p.name, "path": str(p)}
            for p, o in zip(found, held, strict=True)
            if isinstance(o, dict) and not o.get("occupants")
        ]
        return {"repo": repo, "worktrees": free}

    @app.get("/api/occupancy")
    async def api_occupancy(dir: str = "", host: str = ""):
        if not dir.strip():
            return {"dir": "", "occupants": [], "git": False}
        if h := away_host(host):  # the picked host's reading (§4.4a, TD-294): who holds the slot there
            try:
                got = await call("host_occupancy", host=h, dir=dir.strip())
            except HTTPException as e:
                return {"dir": dir.strip(), "occupants": [], "git": False, "why": silent(h, e)}
        else:
            got = await call("occupancy", dir=dir.strip())
        if isinstance(got, dict) and got.get("occupants"):
            # a holder that is a seat says so, with its state and claim (§4.5a, TD-387); the fleet the
            # page reads, so a list that fails leaves the plain *in use by* words
            with contextlib.suppress(HTTPException):
                got["seat"] = cards_mod.seat_occupant(list(got["occupants"]), await call("list"), datetime.now(UTC))
        return got

    @app.get("/api/name_check")
    async def api_name_check(dir: str = "", name: str = "", worktree: bool = False, host: str = ""):
        """What §4.1's name rule would do (design §4.5a, TD-030): the New session form asks as you
        type, the way it already asks about directory occupancy. `worktree` puts the name in the
        repo's scope, which is where the session would actually land."""
        if not (dir.strip() and name.strip()):
            return {"id": "", "name": name, "verdict": "free", "holder": None, "message": ""}
        on = {"host": host.strip()} if host.strip() and host.strip() != host_name() else {}  # the Host pick's
        return await call(
            "name_check", dir=dir.strip(), name=name.strip(), repo=dir.strip() if worktree else None, **on
        )

    # -- Add entry (design §4.9 *Add an entry to the ledger*, §4.5a **Add entry…**, TD-219 slice 3) ---

    async def entry_name_why(root: str, name: str) -> str:
        """§4.5a *Add entry form: Name* (TD-675, built by TD-677): why `name` cannot be **Open a
        session**'s, or `""` when it is free — the one test for the default and a typed name alike. The
        name is the session's, its worktree's and its branch's unchanged, so §4.1's slug must leave it
        as it is; then the name check in the repo's scope (an exited holder is not free here: an
        entry's session is new work), no worktree of that name, and no local branch of that name
        (`ensure_worktree` would start the session on it)."""
        if naming.slug(name) != name:
            return ENTRY_SLUG_WHY
        if why := entry_held_why(await call("name_check", dir=root, name=name, repo=root), name):
            return why
        with contextlib.suppress(gitinfo.WorktreeError):
            if (await asyncio.to_thread(gitinfo.worktree_path, Path(root), name)).exists():
                return f"a worktree named {name} exists — pick another name"
        if await asyncio.to_thread(entry_branch_exists, root, name):
            return f"a branch named {name} exists — the session would start on it; pick another name"
        return ""

    async def entry_name_on(host: str, path: str, container: bool, name: str, listed: set[str]) -> str:
        """`entry_name_why` on the team's host (§4.5a *Add entry form: Name*, TD-1064), in the row's
        order: the name check routed to `host`, the worktree from `listed` (the plan's one
        `host_worktrees`), the branch — the home's own read for a container node, whose checkout is
        the home's own directory, else `host_branch` — each against the node's checkout `path`. A read
        that fails, and a branch the host cannot tell, is `HostSilent` in the words the plan shows."""
        if naming.slug(name) != name:
            return ENTRY_SLUG_WHY
        try:
            got = await call("name_check", dir=path, name=name, repo=path, host=host)
        except HTTPException as e:
            raise HostSilent(unanswered(host, e)) from None
        if why := entry_held_why(got, name):
            return why
        if name in listed:
            return f"a worktree named {name} exists — pick another name"
        if container:
            exists: bool | None = await asyncio.to_thread(entry_branch_exists, path, name)
        else:
            try:
                exists = (await call("host_branch", host=host, dir=path, name=name) or {}).get("exists")
            except HTTPException as e:
                raise HostSilent(unanswered(host, e)) from None
            if exists is None:  # an older node without `branch`, or a read it could not make
                raise HostSilent(f"{host} did not say whether {name} is free")
        if exists:
            return f"a branch named {name} exists — the session would start on it; pick another name"
        return ""

    async def entry_place(
        org: orgmod.Org, team: str, type_: str, repo: str, root: str, name: str
    ) -> tuple[dict[str, Any], repoconfig.RepoConfig | None]:
        """Where **Open a session** starts and with what name, on the team's host where `place:` puts
        the team on another (§4.9 *It runs on the team's host*, §4.5a *Open a session*, TD-1064):
        `{host, dir, why, role, ledger, default, name_why}`, and the repo config read on a machine node
        (None elsewhere: this host's and a container node's are the home's checkout, read as before).
        `why` is the host's refusal — the team's landing, no checkout there, the host silent — which
        disables the session way and never fails the plan, so **Hand to the techlead** still reads it."""
        t = org.teams.get(team) if team else None
        here = host_name()
        away = (t.host or here) if t is not None else here
        if away == here:
            cfg = await asyncio.to_thread(repoconfig.discover, root)  # ValueError: the caller's 400
            role = await asyncio.to_thread(entry_role, org, team, type_)  # reads the team's flow from disk
            default = ""
            for n in range(1, ENTRY_TRIES + 1):
                cand = f"{ENTRY_PREFIX}-{n}"
                if not await entry_name_why(root, cand):
                    default = cand
                    break
            if not default:
                raise HTTPException(409, f"no {ENTRY_PREFIX}-<n> up to {ENTRY_TRIES} is free in {repo}")
            name_why = await entry_name_why(root, name) if name.strip() else ""
            out = {"host": "", "dir": root, "why": "", "role": role, "ledger": cfg.ledger}
            return {**out, "default": default, "name_why": name_why}, None
        assert t is not None  # `away` is another host only for a team's
        container = away in container_nodes()
        path = org.checkout(t.repo, away)
        node_dir = str(Path(path).expanduser()) if path is not None else ""
        why, node_cfg, files = "", None, None
        if team in org.unlanded:  # the start's own refusal; `teams.plan` is not run (§4.9 *Where a repo's team lands*)
            why = org.unlanded[team]
        elif path is None:
            why = teams.no_checkout(org, t.repo, away, "Open a session")
        elif not container:  # a machine node: its `.shiftlead.yml`, roles and ledger read there (§4.4a)
            try:
                node_cfg = await config_on(call, away, node_dir)
                files = files_on(call, asyncio.get_running_loop())
            except HostSilent as e:
                why = unanswered(away, str(e))
            except ValueError as e:
                why = str(e).strip('"')
        cfg = node_cfg
        if cfg is None and container and not why:
            cfg = await asyncio.to_thread(repoconfig.discover, root)
        role = await asyncio.to_thread(entry_role, org, team, type_, files)
        ledger = cfg.ledger if cfg is not None else repoconfig.DEFAULT_LEDGER
        listed: set[str] = set()
        if not why:
            try:
                got = await call("host_worktrees", host=away, repo=node_dir)  # once per plan, not per candidate
                listed = {str(w.get("name") or "") for w in (got or {}).get("worktrees") or [] if isinstance(w, dict)}
            except HTTPException as e:
                why = unanswered(away, e)
        out = {"host": away, "dir": node_dir, "role": role, "ledger": ledger}
        if why:
            return {**out, "why": why, "default": "", "name_why": why}, node_cfg
        default = ""
        try:  # a candidate that fails is skipped; the first read that fails ends the search
            for n in range(1, ENTRY_TRIES + 1):
                cand = f"{ENTRY_PREFIX}-{n}"
                if cand not in listed and not await entry_name_on(away, node_dir, container, cand, listed):
                    default = cand
                    break
        except HostSilent as e:
            return {**out, "why": str(e), "default": "", "name_why": str(e)}, node_cfg
        if not default:
            raise HTTPException(409, f"no {ENTRY_PREFIX}-<n> up to {ENTRY_TRIES} is free in {t.repo} on {away}")
        try:
            name_why = await entry_name_on(away, node_dir, container, name, listed) if name.strip() else ""
        except HostSilent as e:
            return {**out, "why": str(e), "default": default, "name_why": str(e)}, node_cfg
        return {**out, "why": "", "default": default, "name_why": name_why}, node_cfg

    async def entry_plan(repo: str, type_: str, name: str = "", pick: str = "") -> dict[str, Any]:
        return (await entry_plan_cfg(repo, type_, name, pick))[0]

    async def entry_plan_cfg(
        repo: str, type_: str, name: str = "", pick: str = ""
    ) -> tuple[dict[str, Any], repoconfig.RepoConfig | None]:
        """What **Open a session** would start for `repo` (a registered checkout's name) and `type_`:
        the team whose `repo:` is the checkout, the role its `entries:` names (§4.9), the first
        `entry-<n>` free in the repo (`default`), the name the press takes — `name` as typed in the
        **Name** box, else the default — and `name_why`, why that name is not free (TD-677), the
        team's live manager, and the line under the button. `pick` is the form's **Team** pick
        (TD-740): a servicing team's name puts it first among the teams **Hand to the techlead**
        hands to; blank, or no team of the repo, leaves the first with a techlead seat, in the order
        of the ledger's `Team` vocabulary as the home's repo reading carries it, else definition order
        (§4.10 *An entry handed to a seat*, TD-764)."""
        if type_ not in orgmod.ENTRY_TYPES:
            raise HTTPException(400, f"type is {' or '.join(orgmod.ENTRY_TYPES)}, not {type_!r}")
        root = next((p for p in hosts.local_host().repos() if Path(p).expanduser().name == repo), None)
        if root is None:
            raise HTTPException(404, f"no registered repo is named {repo!r} — ao repo --all lists them")
        root = str(Path(root).expanduser().resolve())
        org, _notes = await asyncio.to_thread(org_here)
        team = repo_teams(org, host_name()).get(root, "")
        try:
            place, node_cfg = await entry_place(org, team, type_, repo, root, name)
        except ValueError as e:
            raise HTTPException(400, str(e).strip('"')) from None
        role, default, name_why = place["role"], place["default"], place["name_why"]
        name = name if name.strip() else default
        manager, records, attach = "", {}, ""
        with contextlib.suppress(HTTPException):  # no list: the hand line reads as a seat nobody fills
            records = {r["id"]: r for r in await call("list")}
        if team:
            t, here = org.teams[team], host_name()
            mid = teams.manager_id(org, t, t.host or here, here)
            manager = mid if mid in {s["id"] for s in teamrun.live(list(records.values()))} else ""
            if (t.host or here) != here:  # **Attach** in the composer's words for a node's session (§4.5a, TD-630)
                attach = f"{team} runs on {t.host}: this call does not cross the link"
        led = next(
            (
                v.get("ledger") or {}
                for v in (await h.repo_facts())[0].values()
                if isinstance(v, dict) and v.get("root") and str(Path(str(v["root"])).expanduser().resolve()) == root
            ),
            {},
        )
        servicing = entry_teams(org, root, host_name(), led.get("declared_teams") or ())
        picked = next((t for t in servicing if t["team"] == pick), None)
        servicing = [picked, *(t for t in servicing if t is not picked)] if picked else servicing
        return {
            "repo": repo,
            "root": root,
            "host": place["host"],  # the team's host where `place:` puts it on another, else "" (TD-1064)
            "dir": place["dir"],  # the repo's checkout there, which the create's `dir` and worktree base are
            "why": place["why"],  # why the session way is refused on that host; Hand to the techlead is not
            "ledger": place["ledger"],
            "type": type_,
            "team": team,
            "role": role,
            "name": name,
            "default": default,  # the **Name** box's prefill and placeholder (§4.5a, TD-677)
            "name_why": name_why,  # stands in place of the line, and disables **Open a session**
            "manager": manager,
            "line": entry_line(role, place["host"]),
            "teams": servicing,  # what `entry_add` is handed (TD-218), the picked team first (TD-740)
            "picked": picked["team"] if picked else "",
            "hand": entry_hand(servicing, records),  # **Hand to the techlead** (TD-219 slice 4)
            "attach": attach,  # why **Attach** refuses, or "" (§4.5a *Add entry form: Attach / drop / paste*)
        }, node_cfg

    @app.get("/api/entry/plan")
    async def api_entry_plan(repo: str = "", type: str = "debt", name: str = "", team: str = ""):
        """The Add entry form's line under **Open a session** (§4.5a), read as the Type changes, the
        **Name** box's verdict as the person types (`name=`, TD-677), and **Hand to the techlead**'s seat
        for the **Team** pick (`team=`, TD-740)."""
        return await entry_plan(repo, type, name, team)

    @app.post("/api/entry/attach")
    async def api_entry_attach(
        file: UploadFile | None = None,
        draft: str = Form(""),
        upload: str = Form(""),
        offset: int = Form(0),
        total: int | None = Form(None),
        cancel: str = Form(""),
    ):
        """§4.5a *Add entry form: Attach / drop / paste* (TD-630, built by TD-633): the composer's
        pieces with the form's `draft` in place of a session — `""` on the form's first file, which the
        host agent answers with a new `draft-<8 hex>`, and that token on every later piece and file
        (§4.4 *The Add entry form's draft*). Every answer carries `draft`; the path is final."""
        return JSONResponse(await attach_piece(call, {"draft": draft}, file, upload, offset, total, cancel))

    @app.post("/api/entry/hand")
    async def api_entry_hand(request: Request):
        """§4.5a Add entry form → **Hand to the techlead** (TD-219 slice 4): `{repo, type, priority, words, team}`
        goes to `entry_add` (TD-218) as the person's `ask` to the techlead seat of the team the **Team**
        pick names (TD-740), carried as `entry.team` (TD-764) beside the **Priority** pick as `entry.priority`
        (TD-851), else the repo's first servicing team with a
        seat in the ledger's `Team` order, marked `handed`, with no
        bound; the host agent refuses in words what the page disables (no team, no seat, no words).
        Answers `{id, to, name, text, href}`: the toast's words, *handed to techlead-ao-1 · m-…*, and the
        message's page in the Inbox."""
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            raise HTTPException(400, "send {repo, type, words}")
        plan = await entry_plan(
            str(body.get("repo") or ""), str(body.get("type") or "debt"), pick=str(body.get("team") or "")
        )
        got = await call(
            "entry_add",
            repo=plan["root"],
            type=plan["type"],
            text=str(body.get("words") or ""),
            teams=[{"team": t["team"], "seat": t["seat"]} for t in plan["teams"]],
            team=plan["picked"],  # `entry.team`: the pick, empty when blank (§4.10, TD-764)
            priority=str(body.get("priority") or ""),  # `entry.priority`, `medium` when absent (TD-851)
            **_draft_of(body),
        )
        name = plan["hand"]["name"] if got.get("to") == plan["hand"]["to"] else got.get("to")
        return {
            "ok": True,
            "id": got["id"],
            "to": got.get("to"),
            "name": name or got.get("to"),
            "read_when": got.get("read_when") or "",
            "text": f"handed to {name or got.get('to')} · {got['id']}",
            "href": f"/inbox/{got['id']}",
        }

    @app.post("/api/entry/session")
    async def api_entry_session(request: Request):
        """§4.5a Add entry form → **Open a session** (TD-219 slice 3): `{repo, type, priority, words, name}` starts
        an **interactive** session in a new worktree of the repo, named what the **Name** box holds
        (`name`, else the plan's `entry-<n>`; a name not free is refused 409 in the box's words, TD-677),
        in its team as a person's own session is (§4.9 *A person in the team*) with the role `entries:`
        names for the Type — `plain` with no badge where no team services the repo — at the prompt: no
        opening prompt and no brief.
        `entry.md`'s lines, filled, are the session's **start context** (§4.3, TD-283 part 2): it holds
        them from its start with no turn run for them, and Focus draws them in the Session card's **told at start** row.
        Answers `{id, text}`: the composer's text — the person's words alone — which the page keeps in
        the browser as that session's draft; nothing is typed into the pane, and the record holds the
        lines, never the words."""
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            raise HTTPException(400, "send {repo, type, words}")
        repo, type_, name = (str(body.get(k) or "") for k in ("repo", "type", "name"))
        priority = str(body.get("priority") or "").strip().lower() or "medium"  # the **Priority** pick (TD-851)
        if priority not in orgmod.ENTRY_PRIORITIES:
            raise HTTPException(400, f"an entry's priority is {', '.join(orgmod.ENTRY_PRIORITIES)}, not {priority!r}")
        plan, node_cfg = await entry_plan_cfg(repo, type_ or "debt", name)
        if plan["name_why"]:  # taken between the check and the press: refused, never replaced by another
            raise HTTPException(409, plan["name_why"])  # the host's refusal too, never a create on the home's path
        root, team, away = plan["root"], plan["team"], plan["host"]
        try:
            cfg = node_cfg or await asyncio.to_thread(repoconfig.discover, root)
            roles = (await asyncio.to_thread(org_here))[0].roles
            # a machine node's config reads across the link, blocking on this loop: a worker thread's
            preset = await asyncio.to_thread(repoconfig.resolve_role, cfg, plan["role"], roles)
            review = preset.review
            if team:  # a role's own `review:` wins, else the team's reader (§4.9) — under a flow, the flow's (§4.9c)
                got = await asyncio.to_thread(team_reader, team, root, node_cfg, preset.name)
                if got.get("flow") or review is None:
                    review = got["review"]
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e).strip('"')) from None
        except OSError as e:  # the node stopped answering between the plan and the role or its reader
            raise HTTPException(409, unanswered(away, str(e))) from None
        # the `project` badge, as New session's: the repo's project, from the same function (§4.9, TD-1043);
        # the badge alone, since this session starts at the prompt with no text to carry a Project block
        project, _block = await asyncio.to_thread(lambda: teams.reach_block(org_here()[0], root, host_name()))
        s = await call(
            "create",
            name=plan["name"],
            dir=plan["dir"],  # the team's checkout on its host (TD-1064); the badge stays keyed by `root`
            adapter="claude-code",
            profile=preset.profile or "",
            prompt="",  # started at the prompt: a role's brief is written for an unattended run (§4.9)
            unattended=False,
            **teams.gate_prompts(False),
            worktree=plan["name"],
            repo=plan["dir"],
            capabilities=[g for g in dict.fromkeys(preset.grants) if g in GRANTS],  # as New session ticks them
            lane=[],
            role=preset.name,
            review=review,
            context_bound=preset.bound_for(False),
            ledger=cfg.ledger,
            controllers=[plan["manager"]] if plan["manager"] else [],
            project=project,
            team=team,  # the badge, as the New session form's Team pick sets it; none without a team
            start_context=repoconfig.entry_text(plan["repo"], plan["type"], priority, plan["ledger"]),
            **({"host": away} if away else {}),  # routed to the team's host, as New session's Host pick is
            **_draft_of(body),
        )
        text = str(body.get("words") or "").strip()  # the composer is the person's (§4.5a **Open a session**)
        return {"ok": True, "id": s["id"], "name": s.get("name") or plan["name"], "text": text}

    @app.post("/api/ledger/hold")
    async def api_ledger_hold(request: Request):
        """§4.5a *Repo page: Hold / Release on an entry* and *Inbox row: held entry* (TD-707, built by
        TD-710 slice 3 and TD-736): `{repo, id, release?, why?}` — the repo by its name, as the page names it —
        to the home's `td_hold`, the person's own act on its settle clock, no ledger edit; the reply's
        `told`, `readers` and `untold` are the Hold toast's. A refusal (*TD-707 has settled*) is
        the toast's, a 400 in its words; the row's mark moves on the next repo reading's push."""
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        repo, ref = (str(body.get("repo") or ""), str(body.get("id") or "")) if isinstance(body, dict) else ("", "")
        if not repo or not ref:
            raise HTTPException(400, "send {repo, id, release?}")
        # the home resolves the repo by the name its reading carries, the page's own (a refusal is the 400)
        why = " ".join(str(body.get("why") or "").split())  # **Hold…**'s words (TD-905), new words replacing old
        more = {"why": why} if why else {}
        got = await call("td_hold", repo=repo, id=ref, release=bool(body.get("release")), **more)
        return JSONResponse({"ok": True, **(got if isinstance(got, dict) else {})})

    @app.post("/api/rank/move")
    async def api_rank_move(request: Request):
        """§4.5a *Queue page, Up next: grip / ⤒ ↑ ↓* and *Repo page: Technical debt cards* (TD-770):
        `{ids, prev, next}` — the moved card's open members and the Up next cards now just before and
        just after it in the whole order, each a member's `<repo>#TD-n` (none: the top, the end) — to the
        home's `rank_move`, the person's (§4.4 *A move lands*). From a Repo page, `scope` too, the repo: the
        neighbours are then adjacent among its own Up next cards (TD-901); a move without it is asked as
        before, and a home older than the page refuses a scoped one until the pair is promoted together. A
        refusal is a 400 in the home's words, which the page draws under the heading as it puts the card back."""
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        ids = [str(i) for i in (body.get("ids") or []) if i] if isinstance(body, dict) else []
        if not ids:
            raise HTTPException(400, "send {ids, prev, next}")
        scope = {"scope": str(body["scope"])} if body.get("scope") else {}
        got = await call("rank_move", ids=ids, prev=body.get("prev") or None, next=body.get("next") or None, **scope)
        return JSONResponse({"ok": True, **(got if isinstance(got, dict) else {})})

    @app.post("/api/ledger/start")
    async def api_ledger_start(request: Request):
        """§4.5a *Inbox row: ledger entry* → **Start session** / **Open session** (TD-676, built by
        TD-678): `{repo, id}` — the repo by its name, as the Add entry form names it — on an entry the
        home's repo facts sort *for you* (refused 409 in words once it is not). A live record of the
        repo claiming the entry, or a live one named `td-<n>` there (a start the tick has not yet
        derived a claim for), answers `{focus: <its id>}` and starts nothing. Else one press, no form,
        as **Resume** is: the person's own **interactive** session on the repo's team, the role its
        `entries:` names for the entry's Type, its profile, grants and `review` as **Open a session**
        takes them, the team's live manager its controller, `lane` the id, in a new worktree and branch
        `td-<n>` under that name, its first prompt `work.md` filled (no `start_context`, no brief) —
        answering `{id}`. **When it cannot be silent it is not a guess**: no team, a team on another
        host, a name not free by Add entry's test (`entry_name_why`), a role or profile that does not
        resolve, or the create refused answers `{form, why}` — New session filled in
        (`ledger_start_form`) with the reason on it.

        **On a Queue card** (TD-909, built by TD-912; §4.5 screen 12 *Three verbs: Start session*): `card`, the
        card's id as the `queue` reading has it, widens the road — the entry must be open and the card's `start`
        now, in place of *for you* (409 in words otherwise); the person's own session on any of the card's
        entries answers `{focus}`, another holder of `start` is refused 409 *held by <name>* (`card_session`);
        `why_key` is the entry's — *yours*, *decision*, else *card* — and the prompt reads *from the Queue*.
        Either way the prompt names the card's ids, waits on me — its Decide and Do items (`waits_on_me`) — and
        the rest (`card_entries`); an entry on no card is the one it names.

        **Started from an item** (TD-1246, §4.5 screen 12): `item`, the item's id — `board:<key>`, `m-…` or
        `<repo>#TD-n` — beside `card`. A ledger item starts on its own entry, which must be one of the card's
        Decide or Do ledger entries or its `start` (409 otherwise); any other item on the card's `start`. The
        holder rules read the entry it starts on (`card_session`'s `on`): another holder is refused 409 *held by
        <name>*, never answered with its Focus. The prompt's first sentence names the item (`WORK_ITEM`)."""
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(body, dict):
            raise HTTPException(400, "send {repo, id}")
        repo, ref = str(body.get("repo") or ""), str(body.get("id") or "")
        card_id = str(body.get("card") or "")
        item = str(body.get("item") or "") if card_id else ""
        root = next((p for p in hosts.local_host().repos() if Path(p).expanduser().name == repo), None)
        if root is None:
            raise HTTPException(404, f"no registered repo is named {repo!r} — ao repo --all lists them")
        here = Path(root).expanduser().resolve()
        root = str(here)
        facts = next(
            (
                r
                for k, r in ((await call("repos")) or {}).items()
                if isinstance(r, dict) and Path(str(r.get("root") or k)).resolve() == here
            ),
            {},
        )
        entry = next(
            (
                e
                for e in (facts.get("ledger") or {}).get("entries") or ()
                if isinstance(e, dict) and same_td(e.get("id"), ref)
            ),
            None,
        )
        ref = str(entry["id"]) if entry is not None else ref  # the ledger's own spelling: a card's is `TD-009`
        cards: list[dict[str, Any]] = []
        with contextlib.suppress(HTTPException):  # an older home serves no `queue`: the prompt names the entry
            got = (await call("queue", omit=["completed"])) or {}
            cards = [c for c in got.get("cards") or [] if isinstance(c, dict)]
        records = await call("list")
        if card_id:  # a Queue card: the entry is the card's `start` now, not *for you*
            card = next((c for c in cards if c.get("id") == card_id), None)
            if card is None or entry is None:
                raise HTTPException(409, f"the card around {card_id} is no longer open — nothing was started")
            here_q = qid(repo, ref)
            if TD_REF.fullmatch(item):  # a ledger item: its own entry, one of the card's Decide or Do entries
                it_repo, _, it_ref = item.rpartition("#")
                if qid(it_repo or repo, it_ref) != here_q or (
                    here_q not in card_entries(card)[0] and card.get("start") != here_q
                ):
                    raise HTTPException(409, f"{item} is not an item of this card's to start on — nothing was started")
            elif card.get("start") != here_q:
                raise HTTPException(
                    409, f"{ref} is no longer the entry this card starts on ({card.get('start')}) — nothing was started"
                )
            met = card_session(card, records, on=here_q)
            if met["own"]:
                return {"ok": True, "focus": met["own"]}
            if met["other"]:
                raise HTTPException(409, f"held by {met['other']} — nothing was started")
        else:
            if entry is None or entry.get("for_page") != "for-you":
                raise HTTPException(409, f"{ref} no longer waits on you in {repo}'s ledger — nothing was started")
            card = next((c for c in cards if qid(repo, ref) in sum(card_entries(c), [])), None)
        mine, rest = card_entries(card) if card is not None else ([qid(repo, ref)], [])
        if card is not None:  # every Decide and Do item, by its id (§4.5 screen 12 *Started from an item*)
            with contextlib.suppress(Exception):  # unread, *waits on me* is the card's ledger entries
                got = (await card_mail(h, records, card_index({"cards": cards})))[1]
                wants = card_wants((got.get("cards") or {}).get(str(card.get("id"))), "", False)
                mine = waits_on_me(mine, wants)
            if item and not TD_REF.fullmatch(item) and item not in mine:  # the item pressed, read or not
                mine.append(item)
        name = ref.lower()  # cadence's work-branch shape: the tick derives the claim from it (§4.8)
        live = [
            s
            for s in records
            if s.get("state") not in ("exited", "closed") and s.get("repo") and Path(str(s["repo"])).resolve() == here
        ]
        holder = next(
            (
                s
                for s in live
                if any(
                    isinstance(p, dict) and p.get("ref") == ref and p.get("status") == "claimed"
                    for p in s.get("progress") or []
                )
            ),
            None,
        ) or next((s for s in live if s.get("name") == name), None)
        if holder is not None and card_id:  # `card_session` met none of the person's: never another's Focus
            raise HTTPException(409, f"held by {holder.get('name') or holder['id']} — nothing was started")
        if holder is not None:  # **Open session**, and a second press before the tick: never a second one
            return {"ok": True, "focus": holder["id"]}
        type_ = str(entry.get("type") or "")
        type_ = type_ if type_ in orgmod.ENTRY_TYPES else orgmod.ENTRY_TYPES[0]
        if str(entry.get("owner") or "").lower() == "paul":
            why_key = "yours"
        elif ledger_mod.decided_by(entry, "paul") or not card_id:
            why_key = "decision"
        else:
            why_key = "card"
        org, _notes = await asyncio.to_thread(org_here)
        team = repo_teams(org, host_name()).get(root, "")
        role = await asyncio.to_thread(entry_role, org, team, type_)
        manager, ledger, cfg_why = "", repoconfig.DEFAULT_LEDGER, ""
        try:
            cfg = await asyncio.to_thread(repoconfig.discover, root)
            ledger = cfg.ledger
        except ValueError as e:
            cfg, cfg_why = None, str(e).strip('"')
        prompt = repoconfig.work_text(
            ref, repo, ledger, why_key, where="Queue" if card_id else "Inbox", mine=mine, rest=rest, item=item
        )
        t = org.teams.get(team) if team else None
        if t is not None:
            mid = teams.manager_id(org, t, t.host or host_name(), host_name())
            manager = mid if mid in {s["id"] for s in teamrun.live(records)} else ""

        def form(why: str, role_: str = role) -> JSONResponse:
            url = ledger_start_form(root, name, ref, team, role_, manager, prompt, why)
            return JSONResponse({"ok": False, "form": url, "why": why})

        if t is None:  # the form's *Interactive*, not `plain`: a role pick there is a team's
            return form(f"no team services {repo}: pick one, or start the session with no team", "")
        if (t.host or host_name()) != host_name():
            return form(f"{team} runs on {t.host}: this press does not cross the link")
        if cfg is None:
            return form(cfg_why)
        if why := await entry_name_why(root, name):
            return form(why)
        try:
            preset = repoconfig.resolve_role(cfg, role, org.roles)
        except (KeyError, ValueError) as e:
            return form(f"the role {role} does not resolve here: {str(e).strip(chr(34))}", "")
        profs, _default = profiles_mod.load()
        if preset.profile and preset.profile not in profs:
            return form(f"the role {preset.name} names the profile {preset.profile}, which is not defined")
        review = preset.review
        got = await asyncio.to_thread(team_reader, team, root, None, preset.name)
        if got.get("flow") or review is None:  # as **Open a session** takes it
            review = got["review"]
        # the `project` badge, as New session's (§4.9, TD-1043): the badge alone, not the Project block
        project, _block = await asyncio.to_thread(teams.reach_block, org, root, host_name())
        try:
            s = await call(
                "create",
                name=name,
                dir=root,
                adapter="claude-code",
                profile=preset.profile or "",
                prompt=prompt,  # the opening prompt, never the role's brief (§4.9)
                unattended=False,
                **teams.gate_prompts(False),
                worktree=name,
                repo=root,
                capabilities=[g for g in dict.fromkeys(preset.grants) if g in GRANTS],
                lane=[ref],
                role=preset.name,
                review=review,
                context_bound=preset.bound_for(False),
                ledger=cfg.ledger,
                controllers=[manager] if manager else [],
                project=project,
                team=team,
            )
        except HTTPException as e:
            return form(str(e.detail).strip('"') or "the host agent refused the start")
        return {"ok": True, "id": s["id"], "name": s.get("name") or name}


def _sessions_routes(app: FastAPI, h: SimpleNamespace) -> None:
    """A session's own controls and reads: resume, the card's actions, its inbox, the list."""
    call, seats_of = h.call, h.seats_of

    # -- actions (every control in design §4.5a that exists in phase 1) --------------------------

    @app.post("/api/sessions/{sid}/resume")
    async def resume_session(sid: str, request: Request):
        """design §4.5a **Focus (exited / closed)** → **Resume**, and **Inbox row: state** →
        **Reopen and push** (TD-081 step 2): *a resume option that requires no input from me*.

        One press, no form: a `create` carrying the record's own name, so the name check answers
        `supersede` and the resumed session takes the bare name and the record's id in place, with
        its mail (§4.10, built by step 1). It is a person's act from the page — **caller-less**, no
        attenuation (§4.8 create rule) — and the session it starts is **attended**, whatever the
        record was.

        **When it cannot be silent it is not a guess.** What the record itself settles is answered
        here; everything else is the agent's own refusal, and either way the answer is the same:
        the filled-in form, with the reason on it, for the person to finish by hand. The client
        follows `form`; nothing is created behind their back and nothing is guessed at."""
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        rec = await call("get", id=sid)
        # **Resume with changes…** asks for the form outright and creates nothing (§4.5a).
        if body.get("form"):
            return JSONResponse({"ok": True, "form": resume_form_url(rec)})
        if why := resume_blocked(rec):
            return JSONResponse({"ok": False, "form": resume_form_url(rec, why), "why": why})
        # *Reopen and push* is the same press with a first prompt **the page wrote** — fixed text
        # in the source, never anything a session said (§4.2, TD-071 item 8).
        prompt = REOPEN_AND_PUSH if body.get("push") else ""
        try:
            new = await call("create", **resume_create(rec, prompt=prompt))
        except HTTPException as e:
            why = str(e.detail).strip('"') or "the host agent refused the resume"
            return JSONResponse({"ok": False, "form": resume_form_url(rec, why), "why": why})
        return JSONResponse({"ok": True, "id": new["id"]})

    @app.post("/api/sessions/{sid}/attach")
    async def attach_file(
        sid: str,
        file: UploadFile | None = None,
        upload: str = Form(""),
        offset: int = Form(0),
        total: int | None = Form(None),
        cancel: str = Form(""),
    ):
        """design §4.5a *Focus composer* **Attach** / drop / paste (§4.4 *Attachment drop*, TD-002), in
        pieces (TD-478): one piece of one file, multipart, handed to the host agent's `attach` — a
        person's act — with the form's `upload`, `offset` and `total`. The first piece carries the
        file's name and `total` and is answered `{upload, bytes}` when more follow; every later piece
        names the `upload` and its `offset`; the piece that makes `total` is answered `{path}`, which
        the page inserts into the composer, sending nothing. `cancel` with the `upload` deletes its
        `.part`. A piece past `paths.ATTACH_PIECE_BYTES` is refused here (413) before the host agent is
        asked; the file's bound, `person.attach.max`, is the host agent's, in its words. One piece is
        read, never the file."""
        return JSONResponse(await attach_piece(call, {"id": sid}, file, upload, offset, total, cancel))

    @app.post("/api/sessions/{sid}/paths")
    async def pane_paths(sid: str, request: Request):
        """design §4.5a *Focus pane: a path is a link* (§4.6, TD-501): the runs one row of the pane
        names, handed to the `paths` read on the record's host — a node's through `read` — and its
        answer back, `{paths: {run: path | null}}`. A read, gated by nobody beyond the UI's own (§9
        invariant 11); its refusals are the host agent's, as the transcript route's are."""
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        return JSONResponse(await call("paths", id=sid, runs=body.get("runs")))

    @app.post("/api/paths")
    async def item_paths(request: Request):
        """design §4.5a **a path is a link** on an Inbox row, the message page, a Queue card's item and
        a Repo page row (§4.6 *A path in the Inbox and the Queue is a link too*, TD-1108): `{runs, ctx}`
        answered `{label, file, wait, paths, refused}` by `paths_for`. A read, gated by nobody beyond
        the UI's own (§9 invariant 11)."""
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        return JSONResponse(await paths_for(call, body if isinstance(body, dict) else {}))

    @app.get("/api/sessions/{sid}/git_files")
    async def git_files(sid: str, pick: str = "tree"):
        """design §4.5a *Focus side panel, Git card: the pick* (§4.2 *The Git card's pick*, TD-856): the
        record's newest ten commits and the files of `pick` — `tree`, a sha of the ten, or `session` —
        through the `git_files` read on the record's host, a node's through `read`. A read, gated by
        nobody beyond the UI's own (§9 invariant 11); its refusals are the host agent's, in its words."""
        return JSONResponse(await call("git_files", id=sid, pick=pick))

    @app.post("/api/sessions/{sid}/{action}")
    async def action(sid: str, action: str, request: Request):
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if action in ("allow", "deny"):
            s = await call("get", id=sid)
            if s.get("permission_channel") is False:  # §4.3 *Permissions: no channel* (TD-785)
                raise HTTPException(409, "this tool has no permission channel: answer it in the terminal")
            # the entry the pressed line names, else the newest permission entry (§4.2, TD-950)
            pend = permission_entry(s, str(body.get("call") or "") or None)
            if pend is None:
                raise HTTPException(409, "no pending permission (answered, timed out, or in the terminal)")
            await call("decide", id=sid, tool_use_id=pend["tool_use_id"], behavior=action, reason=body.get("reason"))
        elif action == "kill":
            await call("kill", id=sid)
        elif action == "close":
            await call("close", id=sid)
        elif action == "restart":
            # design §4.5a **Restart** on the Inbox restart row and the card's *more ▾* (§6 rule 2 *A
            # person's restart*, TD-250): the RPC is a person's alone and makes every refusal before
            # it touches anything, so its words are the toast and the row stands
            s = await call("restart", id=sid)
            return JSONResponse({"ok": True, "id": s.get("id") or sid, "unattended": bool(s.get("unattended"))})
        elif action == "send":
            # the page's key (design §4.10 *A send lands once*, TD-806): a repeat answers as the first
            await call("send", id=sid, text=body.get("text", ""), key=body.get("key"))
        elif action == "wrapup":
            await call("send", id=sid, text=WRAPUP_PROMPT, wrapup=True, key=body.get("key"))
        elif action == "mode":
            on = bool(body.get("unattended"))
            s = await call("set_mode", id=sid, unattended=on, **teams.gate_prompts(on))  # §6's two texts
            due = _instant(s.get("run_until"))
            if s.get("unattended") and due is not None and due <= datetime.now(UTC):
                # **Hand back** (design §4.5a, TD-096): a stop time that fell due while the person held
                # the session is not a deadline any more — the resume's rule — and nothing acted on it
                # while it was interactive, so handing back must not kill it on the next tick. One
                # still ahead stays.
                await call("set_stop", id=sid, run_until=None)
        elif action == "keys":
            await call("keys", id=sid, keys=list(body.get("keys") or []))
        elif action == "shell-here":
            # §4.5a *Focus: Open shell here*, **One shell per session, reopened** (TD-810): the name the
            # create would take is checked first, with exactly what the create sends — on the session's
            # host, so a node session's shell is made on its node in its directory
            s = await call("get", id=sid)
            name = f"{s['name']}-shell"
            where = {"host": s["host"]} if s.get("host") and s["host"] != host_name() else {}

            async def own_shell() -> dict[str, Any] | None:
                """The person's own live shell holding the name; None when nothing live holds it; a
                409 naming why for a live holder that is not one."""
                v = await call("name_check", dir=s["dir"], name=name, **where)
                if v.get("verdict") != "live":
                    return None  # free, or an exited or closed holder `create` supersedes
                if not v.get("holder") or v.get("holder_state") == "unrecorded":
                    raise HTTPException(409, v.get("message") or f"{name} is running")
                rec = await call("get", id=v["holder"])
                if why := not_own_shell(rec, name, s["dir"]):
                    raise HTTPException(409, why)
                return rec

            held = await own_shell()
            if held is None:
                try:
                    # the member's badge, and nothing else of its team's (TD-821): drawn on the team the
                    # person pressed it on, still the person's own shell — no controllers, no role
                    badge = {k: s[k] for k in ("team", "project") if s.get(k)}
                    new = await call("create", name=name, dir=s["dir"], adapter="shell", **badge, **where)
                except HTTPException as refused:
                    # a second press racing this one took the name between the check and the create:
                    # both land on its shell; any other refusal is the create's own, unchanged
                    try:
                        held = await own_shell()
                    except HTTPException:
                        held = None
                    if held is None:
                        raise refused from None
            with contextlib.suppress(HTTPException):
                await call("seen", id=sid)  # acted on this card too (TD-017)
            if held is not None:
                return JSONResponse({"ok": True, "id": held["id"], "reused": True})
            return JSONResponse({"ok": True, "id": new["id"]})
        elif action == "drop":
            # design §4.5a Focus **Reports** → Drop: the person let a claim go, and the record says
            # so rather than losing it — a declaration, so the tick's derived entry cannot undo it.
            ref = str(body.get("ref") or "").strip()
            if not ref:
                raise HTTPException(400, "drop needs the reference to drop")
            # TD-150 slice 2 (§4.5a *Reports*): not while a PR from that claim is open — the claim
            # in review is the one a person reading the panel must not let go (TD-143)
            s = await call("get", id=sid)
            pr = review_pr(s.get("progress") or [], ref)
            if pr:
                # the record cannot yet say whether that PR is still open (slice 3 brings its state),
                # so the refusal says what ends it either way
                raise HTTPException(
                    409,
                    f"{ref} is in review as PR #{pr}: a claim with a PR is not dropped — it ends when the "
                    "session reports it done or dropped, once the PR is merged or closed",
                )
            await call("progress", id=sid, ref=ref, status="dropped", why=body.get("why") or "dropped from Focus")
        elif action == "start":
            # design §4.5a **starts** note on Focus and the banner's / `more ▾`'s **Start now** (§6
            # *Start time*, TD-152): `now`, or a time as `ao at` takes it; the agent refuses a
            # record that already started, in its own words
            when = str(body.get("at") or "now").strip()
            try:
                at = "now" if when.lower() == "now" else clistop(when, "start time")
            except AgentError as e:
                raise HTTPException(400, str(e)) from None
            s = await call("set_start", id=sid, start_at=at)
            return JSONResponse({"ok": True, "start_note": start_note(s), "start_at": s.get("start_at")})
        elif action == "stop":
            # design §4.5a Focus header **stops** badge → click to edit (§6, TD-026). The stop time
            # was settable at New session and from `ao until` and nowhere else, so a person who set
            # `+8h` and wanted another hour had to reach for the CLI. An empty time clears it, which
            # is the decision to let a session run on, made out loud rather than by restarting it.
            when = str(body.get("until") or "").strip()
            try:
                run_until = clistop(when) if when else None
            except AgentError as e:
                raise HTTPException(400, str(e)) from None
            s = await call("set_stop", id=sid, run_until=run_until, wrapup_prompt=WRAPUP_PROMPT if run_until else None)
            with contextlib.suppress(HTTPException):
                await call("seen", id=sid)
            return JSONResponse({"ok": True, "stop_note": stop_note(s), "run_until": s.get("run_until")})
        elif action == "grants":
            s = await call("set_grants", id=sid, add=_str_list(body, "add"), remove=_str_list(body, "remove"))
            with contextlib.suppress(HTTPException):
                await call("seen", id=sid)
            return JSONResponse({"ok": True, "capabilities": s.get("capabilities") or []})
        elif action == "controllers":
            # design §4.5a Focus **controllers** chip (§4.8, TD-036). The UI calls with no `caller`,
            # so it acts as the person it is: the agent's own rules still decide what is allowed.
            # A typed *name* is resolved to an id first — the agent stores whatever it is given and
            # a name would sit in the list forever as a controller that can never act (review).
            fleet = await call("list")
            s = await call(
                "set_controllers",
                id=sid,
                add=[_as_session_id(c, fleet) for c in _str_list(body, "add")],
                remove=[_as_session_id(c, fleet, must_exist=False) for c in _str_list(body, "remove")],
            )
            with contextlib.suppress(HTTPException):
                await call("seen", id=sid)
            return JSONResponse({"ok": True, "controllers": s.get("controllers") or []})
        elif action in ("message", "reply"):
            # design §4.5a **Message** (card `more ▾`, Focus header) and Focus Inbox **Reply**
            # (§4.10): mail, not a send — nothing is typed into any pane. The UI calls with no
            # `caller`, so `from` is the person and the message gate lets it through. A reply names
            # the entry it answers and no addressee: the agent addresses it to that entry's sender.
            text = str(body.get("text") or "")
            if action == "reply":
                ref = str(body.get("reply_to") or "").strip()
                if not ref:
                    raise HTTPException(400, "a reply names the entry it answers")
                got = await call("msg", text=text, kind="reply", reply_to=ref)
            else:
                kind = str(body.get("kind") or "note")
                if kind not in ("note", "ask"):
                    raise HTTPException(400, "a person's Message is a note or an ask")
                about = str(body.get("about") or "").strip() or None
                got = await call("msg", to=[sid], text=text, kind=kind, about=about)
            with contextlib.suppress(HTTPException):
                await call("seen", id=sid)
            return JSONResponse({"ok": True, "id": got["entry"]["id"], "delivered": got["delivered"]})
        elif action == "unmail":
            # design §4.5a Focus **Inbox** → delete (§4.10 lifecycle: a person's hand): this
            # session's copy only; the sender keeps its own.
            ref = str(body.get("msg") or "").strip()
            if not ref:
                raise HTTPException(400, "delete needs the entry's id")
            await call("inbox_delete", id=sid, msg=ref)
        elif action == "remove":
            await call("remove", id=sid)
        elif action == "seen":
            pass  # the mark below is the whole action (a visible Focus sends it while its record is unseen)
        else:
            raise HTTPException(404, f"no action {action}")
        if action != "remove":
            with contextlib.suppress(HTTPException):
                await call("seen", id=sid)  # acting on a card counts as looking at it (TD-017)
        return JSONResponse({"ok": True})

    @app.get("/api/sessions/{sid}/inbox")
    async def api_inbox(sid: str, request: Request):
        """design §4.5a Focus side panel **Inbox** (§4.10 "A bounded body"): bodies never ride the
        pushed record, so the panel fetches them here. No caller — a person's read, which sets no
        `read_at`, because a person is not the session. Each sender gets its name beside its id,
        and its text the two halves the Inbox row draws (`shaped`, TD-138): the panel folds the
        same way, from the same renderer, and composes no markup of its own from a session's text."""
        got = await call("inbox", id=sid)
        fleet = await call("list")
        names = {o.get("id"): o.get("name") or o.get("id") for o in fleet}
        records = {o.get("id"): o for o in fleet}
        origin = page_origin(request)
        for e in got["entries"]:
            e["from_name"] = "person" if e["from"] == "person" else names.get(e["from"], e["from"])
            # the Reply dialog's line (§4.10 *When it is read*, TD-168): a reply reads as a note does
            e["reply_when"] = str(((records.get(e["from"]) or {}).get("read_when") or {}).get("note") or "")
            s = shaped(e.get("text"), origin)
            e["lead_html"], e["rest_html"] = str(s["lead"]), str(s["rest"])
        return got

    @app.get("/api/sessions")
    async def api_sessions():
        repos_omit(REPOS_OMIT_PAGE)
        sessions = await call("list")
        icons = await role_icons(sessions)
        seats = await seats_of(sessions)
        # the readings too, so the PR's mark on a report survives Focus's Members refresh (TD-193)
        repos = (await h.repo_facts())[0]
        waits = await h.person_waits()
        return [view(s, sessions, icons=icons, seats=seats, repos=repos, waits=waits) for s in sessions]


def _team_http(e: Exception) -> HTTPException:
    """One mapping for every way a start or a stop can fail, so the strip reports the agent's
    own message the way every other control does — a toast (design §4.5 "Errors"); New session's member
    start (TD-1167) answers its refusal so."""
    if isinstance(e, AgentUnavailable):
        return HTTPException(503, f"host agent unreachable: {e}")
    if isinstance(e, teamrun.PartialStart):
        # The created sessions are running on the brief, so a stale-brief warning belongs on
        # this path most of all (review of PR #139). `detail` is what the toast renders.
        warnings = " · ".join([*e.plan.warnings, *e.plan.notes])
        return HTTPException(409, f"{e}{' — ' + warnings if warnings else ''}")
    return HTTPException(400, str(e).strip('"'))


def _teams_routes(app: FastAPI, h: SimpleNamespace) -> None:
    """Teams: the list, Start, and Stop / Wind down (design §4.9, §4.9a)."""
    call = h.call

    # -- the Teams strip (design §4.5a Sessions **Teams** strip, §4.9) --------------------------------
    # Start and Stop are `shiftlead.teamrun`'s, the sequence `ao team start|stop` runs: every
    # pre-flight check before any create, and the wrap-up order on the way down. The runner blocks
    # (it waits on states), so it goes to a worker thread and the event loop stays free.

    background: set[asyncio.Task[Any]] = set()  # strong refs: a bare create_task may be collected
    stopping_leads: set[str] = set()  # teams whose lead-stop is already in flight: one per team
    stop_errors: dict[str, str] = {}  # a background lead-stop that failed, until the strip reports it

    def _lead_stopped(team: str, lead: str) -> Any:
        """What becomes of the background half of a stop. A task whose exception nobody retrieves is
        a silent failure path, and §4.5 "Errors" says there is none here — so the outcome is logged
        either way, and a failure is kept for the strip to report on its next refresh, which is the
        only channel a request that has already returned still has (review of PR #124)."""

        def done(task: asyncio.Task[Any]) -> None:
            background.discard(task)
            stopping_leads.discard(team)
            if task.cancelled():
                log.warning("team %s: stopping its lead %s was cancelled", team, lead)
                stop_errors[team] = f"stopping {lead} was cancelled"
                return
            err = task.exception()
            if err is None:
                log.info("team %s: lead %s stopped", team, lead)
                stop_errors.pop(team, None)
                return
            log.error("team %s: stopping its lead %s failed: %s", team, lead, err)
            stop_errors[team] = f"{lead} did not stop: {str(err).strip(chr(34))}"

        return done

    @app.get("/api/teams")
    async def api_teams():
        # read fresh, not from the headers' cache: what this answers is whether Start is offered (TD-274)
        v = teams_view(await call("list"), await h.home_waiting(fresh=True))
        for row in v.get("teams", []):
            if row["name"] in stopping_leads:
                row["stopping"] = True
            failed = stop_errors.pop(row["name"], None)  # reported once, then forgotten
            if failed:
                row["error"] = failed
        return v

    @app.get("/api/teams/{name}/lanes")
    async def api_team_lanes(name: str):
        """What every lane the start creates holds before it (§4.5a team card **Start**, TD-265, TD-563):
        read on the press, so the page opens its Start anyway / Cancel dialog when every lane is empty."""
        if hosts.is_node():
            raise HTTPException(409, node_org_note())
        org, _notes = org_here()
        got = await asyncio.to_thread(teamrun.lanes, rpc, org, name, host_name())
        return JSONResponse(got or {"line": "", "empty": False, "roles": {}})

    @app.post("/api/teams/{name}/start")
    async def api_team_start(name: str, request: Request):
        body: Any = {}
        if request.headers.get("content-type", "").startswith("application/json"):
            with contextlib.suppress(ValueError):  # a body that is not JSON reads as none, never a 500
                body = await request.json()
        body = body if isinstance(body, dict) else {}
        if hosts.is_node():
            raise HTTPException(409, node_org_note())  # the strip's note, as the toast (§4.4a)
        org, _notes = org_here()
        if not body.get("anyway"):
            # every lane empty is the dialog's to ask (§4.5a, TD-265); a press that reaches here
            # without **Start anyway** — the lanes emptied since — is refused, as `ao team start` is
            picks = await asyncio.to_thread(teamrun.lanes, rpc, org, name, host_name())
            if picks and picks["empty"]:
                raise HTTPException(409, f"{teamrun.NOTHING_TO_PICK} ({picks['line']})")
        try:
            _plan, result = await asyncio.to_thread(teamrun.start, rpc, org, name, host_name())
        except (teams.TeamError, ValueError, AgentError, AgentUnavailable) as e:
            # A failed pre-flight check created nothing (§4.9): the toast is the whole outcome.
            raise _team_http(e) from None
        return JSONResponse({"ok": True, **result})

    @app.post("/api/teams/{name}/flow/apply")
    async def api_team_flow_apply(name: str):
        """The team card's **Apply** beside *flow changed* (§4.5a, §4.9c *Switching*; TD-309): what
        `ao team flow <team> --apply` does — the sit-outs, the starts and the relaunches — a person's
        own, and not on a node, as Start is not. The flows are read again after it, so the next
        delta draws what it left."""
        if hosts.is_node():
            raise HTTPException(409, node_org_note())
        org, _notes = org_here()
        try:
            got = await asyncio.to_thread(teamrun.apply, rpc, org, name, host_name())
        except (teams.TeamError, ValueError, OSError, AgentError, AgentUnavailable) as e:
            raise _team_http(e) from None
        with contextlib.suppress(HTTPException):  # applied either way: a failed re-read is the next page load's
            await h.flow_views(await call("list"), org)
        return JSONResponse({"ok": True, **got})

    # design §4.9 *Add or remove a member from the team card*, §4.5a *team card: Members…* and the
    # *Members dialog* (TD-163, built by TD-172): the one control that edits a definition from the
    # page — `org.yml`, as text, through the UI process, never the host agent (§4.4a: the org file
    # is the clients'). A repo-defined team is read here and edited by PR.
    @app.get("/api/teams/{name}/members")
    async def api_team_members(name: str):
        if hosts.is_node():
            raise HTTPException(409, node_org_note())
        org, _notes = org_here()
        roles = [r.name for r in repoconfig.roles(repoconfig.RepoConfig(), org.roles)]
        try:
            v = teamrun.members_view(org, name, await call("list"), roles)
        except (teams.TeamError, ValueError) as e:
            raise _team_http(e) from None
        v["roles"] = roles
        # **Open file** beside a repo team's disabled Add member and Remove (§4.5a *Members… on a
        # repo-defined team*, TD-1165), through the person's `open_in`: None under `none`
        v["open_file"] = editor_file_link(v["source"]) if v["source"] and not v["editable"] else None
        return v

    @app.post("/api/teams/{name}/members")
    async def api_team_members_edit(name: str, request: Request):
        body = await request.json()
        if hosts.is_node():
            raise HTTPException(409, node_org_note())
        org, _notes = org_here()
        try:
            if body.get("action") == "size":
                # **− / +** (§4.5a *Members dialog*, §4.9 *A team's size*, TD-1165): a setting, on every
                # team a repo's included — one step from the line's size now, through `teamrun.resize`
                line, step = str(body.get("line") or ""), int(body.get("step"))
                if step not in (-1, 1):
                    raise HTTPException(400, "step is -1 or 1")
                try:
                    n = len(teams.find(org, name).line(line).names()) + step
                except ValueError as e:
                    raise teams.TeamError(str(e)) from None
                got = await asyncio.to_thread(teamrun.resize, rpc, org, name, line, n, host_name())
                return JSONResponse({"ok": True, **got})
            view_ = teamrun.members_view(org, name, await call("list"))
            if not view_["editable"] or org.path is None:
                raise teams.TeamError(f"team {name} is {view_['note'] or 'not in org.yml'}")
            if body.get("action") == "add":
                lane = [x.strip() for x in str(body.get("lane") or "").split(",") if x.strip()]
                got = await asyncio.to_thread(
                    teamrun.add_member, rpc, org.path, name, host_name(),
                    role=str(body.get("role") or ""), member=str(body.get("name") or "").strip(), lane=lane,
                )  # fmt: skip
            elif body.get("action") == "remove":
                got = await asyncio.to_thread(
                    teamrun.remove_member,
                    rpc,
                    org.path,
                    name,
                    index=int(body.get("index")),
                    role=str(body.get("role") or ""),
                    host=host_name(),
                )
            else:
                raise HTTPException(400, "action is add, remove or size")
        except (teams.TeamError, ValueError, TypeError, AgentError, AgentUnavailable) as e:
            raise _team_http(e) from None
        return JSONResponse({"ok": True, **got})

    @app.post("/api/teams/{name}/stop")
    async def api_team_stop(name: str, request: Request):
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        now = bool(body.get("now"))
        if hosts.is_node():
            raise HTTPException(409, node_org_note())
        org, _notes = org_here()
        try:
            st = await asyncio.to_thread(teamrun.stop_members, rpc, org, name, now=now)
        except (teams.TeamError, ValueError, AgentError, AgentUnavailable) as e:
            raise _team_http(e) from None
        pending = None
        if st.lead is not None and name in stopping_leads:
            # Two presses, or a slow first stop: the lead is already being stopped and a second task
            # would send it a second wrap-up or kill, whose failure the first would swallow.
            return JSONResponse(
                {
                    "ok": True,
                    "team": name,
                    "now": now,
                    "sessions": st.acted,
                    "manager": None,
                    "text": f"{name}: already stopping — its manager follows when the members settle",
                }
            )
        if st.lead is not None:
            # §4.9's order is members, then the lead once they settle — up to the wrap-up window,
            # which is minutes. The page must not hold a request open that long, so the second half
            # runs behind the response and the state deltas on /events show it happening.
            pending = st.lead.get("name") or st.lead["id"]
            stopping_leads.add(name)
            task = asyncio.create_task(asyncio.to_thread(teamrun.stop_lead, rpc, st))
            background.add(task)
            task.add_done_callback(_lead_stopped(name, pending))
        sent = sum(1 for e in st.acted if e["role"] != "person")  # a person's session is left alone (§4.9)
        msg = f"{name}: {'killed' if now else 'wrap-up sent to'} {sent} session{'' if sent == 1 else 's'}"
        if pending:
            msg += f" — {pending} follows when they settle"
        for e in st.acted:
            if e["role"] == "person":
                msg += f"; {e['action']}"
        return JSONResponse(
            {"ok": True, "team": name, "now": now, "sessions": st.acted, "manager": pending, "text": msg}
        )


def _help_routes(app: FastAPI, h: SimpleNamespace) -> None:
    """The Help page (design §4.5 screen 10, §4.5a *Help page*; TD-157, built by TD-167)."""

    @app.get("/help", response_class=HTMLResponse)
    async def help_page(request: Request):
        """Every control that has a paragraph in §4.5a *The help text*, by screen, each under a
        heading whose id is the control's, so a mark's *every control → Help* lands on its group.
        Display only — nothing on it is a control — and fixed text from `help.py`, which
        `tests/test_help.py` holds equal to the design's list."""
        screens = [(sid, title, [helpmod.BY_KEY[k] for k in keys]) for sid, title, keys in helpmod.SCREENS]
        return templates.TemplateResponse(
            request,
            "help.html",
            {
                "screens": screens,
                "host": host_name(),
                "active": "",
                "usage": await chip_usage(h.call),
                "build_chip": await chip_build(h.call),
                "volatile": hosts.local_host().volatile,
            },
        )


async def card_mail(
    h: SimpleNamespace, fleet: list[dict[str, Any]], index: Any, drawn: Any = None, cards: Any = ()
) -> tuple[dict[str, Any], dict[str, Any]]:
    """What is attached to each Queue card (§4.5 screen 12 *What is attached to a card*, TD-771, TD-828): the
    Inbox's own sections over the same reads, and `attach`'s cards, each `home: queue` row in its card's section —
    with *Later*'s ledger rows and the board's lines not yet due, folded or not, whose entry a card holds. `drawn(e,
    section, choices)` draws a row (the Queue page, by the Inbox's own renderer), each Decide or Do item with its
    own Start session on its card of `cards` (`item_start`, TD-1246); the start road draws none and reads each
    item's id."""
    choices = board_choices()  # once for the request, never once a row (§4.5 *Page loads*, TD-879)
    inbox, states = await h.person_inbox(fleet, choices=choices), await h.person_states(fleet)
    hz = with_standings((await h.board_view(choices))[0], fleet)
    sections = inbox_sections(
        inbox["entries"],
        states=states,
        trail=inbox.get("trail") or (),
        attention_snoozed=inbox.get("attention_snoozed"),
        handed=inbox.get("handed") or (),
        boards=hz["due"] + hz["waiting"],
        fleet=fleet,
        cards=index,
    )
    later = split_later(await h.ledger_view(fleet), hz["ahead"], index, hz["hidden"])[2]
    with timing.step("render"):  # each attached row drawn by the Inbox's own renderer
        by_id = {str(c.get("id")): c for c in cards if isinstance(c, dict)}
        mail = attach(
            sections,
            lambda e, sec: drawn(e, sec, choices) if drawn else "",
            later,
            (lambda c, item: item_start(by_id[c], item, fleet) if c in by_id else {}) if by_id else None,
            (lambda c, item: _with_you(by_id.get(c), item)) if by_id else None,
        )
    return sections, mail


def _with_you(card: Any, item: str) -> str | None:
    """The person's own session holding a card's entry `item` (`<repo>#TD-n`), by name, where the card's reading
    says one does (its row's `with_you`, §4.4 *A row's state*, TD-1281); else None."""
    rows = [card.get("top"), *(card.get("rows") or [])] if isinstance(card, dict) else []
    return next(
        (r["with_you"] for r in rows if isinstance(r, dict) and r.get("qid") == item and r.get("with_you")), None
    )


def _settings_routes(app: FastAPI, h: SimpleNamespace) -> None:
    """The Settings page (design §4.5 screen 8, §4.5a *Settings page*; TD-148): the page and its
    writes. Every write goes through the host agent's `set_settings` — a person's own, refused to a
    session — and every read of `settings.yml` through its `settings` read; this process reads only
    the files the clients read (`profiles.yml`, `hosts.yml`, the org, each repo's `.shiftlead.yml`)."""
    call = h.call

    @app.get("/queue", response_class=HTMLResponse)
    async def queue_page(request: Request):
        """design §4.5 screen 12 / §4.5a **Queue page** (TD-748, built by TD-771): one card per effort,
        ranked by the person, in three groups — Recently completed with its window picker, In progress
        with the other work, Up next numbered with the grip and ⤒ ↑ ↓ — from the home's `queue`
        reading (`ui.queue.queue_view`). `part=1` is the lists alone, which the page re-reads on its
        poll and on the `queue` event."""
        agent_down, got, why = False, None, ""
        try:
            got = await call("queue")
        except HTTPException as e:
            if e.status_code == 503:
                agent_down = True
            else:
                why = f"the home did not serve the Queue: {e.detail}"  # an older home: no `queue` RPC
        fleet: list[dict[str, Any]] = []
        mail: dict[str, Any] = {}
        tabs: dict[str, int] = {}  # the top bar's numbers at first paint
        if got is not None:
            # what is attached to a card (§4.5 screen 12, TD-771, TD-828): the Inbox's own sections over the
            # same reads, each `home: queue` row drawn in its card's section by the Inbox's own renderer
            repos_omit(REPOS_OMIT_INBOX)
            with contextlib.suppress(HTTPException):
                fleet = await call("list")
                one = templates.get_template("queue_mail.html")
                origin = page_origin(request)
                sections, mail = await card_mail(
                    h,
                    fleet,
                    card_index(got),
                    lambda e, sec, choices: Markup(one.render(e=e, section=sec, origin=origin, board_choices=choices)),
                    got.get("cards") or (),
                )
                tabs = tab_counts(sections)
        # the filter row (§4.5 screen 12 *Filters*, §4.5a *Queue page: filters, find*): carried in the URL,
        # what it hides marked, never dropped — a move's neighbours are the whole Up next order
        picks = queue_picks(request.query_params)
        teams: dict[str, str] = {}
        with contextlib.suppress(Exception):
            teams = {n: t.repo for n, t in (await h.defs()).teams.items() if t.repo}
        # the promote reading, read once: the completed lines' live mark (TD-904) and the top bar's build chip
        info: dict[str, Any] | None = None
        if not agent_down:
            with contextlib.suppress(Exception):  # display only, as the chip is: no mark, never a failed page
                info = dict(await call("host"))
        promotes = (info or {}).get("promotes")
        # Recently completed sends the picked window's lines alone (§4.5 *Page loads*, TD-882)
        view = send_window(
            apply_picks(queue_view(got, datetime.now(UTC), mail, promotes, fleet), picks, teams),
            queue_window(request.query_params),
        )
        ctx = {
            "q": view,
            "picks": picks,
            "pq": picks_query,
            "chips": filter_chips(teams, view["repos"], picks["team"]),
            "team_repos": teams,  # a team chip's repo, which the browser's apply reads as the server's does (TD-829)
            "labels": WINDOW_LABEL,
            "words": WINDOW_WORD,
            "why": why,
            "agent_down": agent_down,
        }
        if request.query_params.get("part"):
            return templates.TemplateResponse(request, "queue_part.html", ctx)
        with contextlib.suppress(HTTPException):
            fleet = fleet or ([] if agent_down else await call("list"))
        return templates.TemplateResponse(
            request,
            "queue.html",
            {
                **ctx,
                **tabs,
                "host": host_name(),
                "active": "Queue",
                "volatile": hosts.local_host().volatile,
                "usage": {} if agent_down else await chip_usage(call, fleet),
                "build_chip": None if agent_down or info is None else await chip_build(call, info),
            },
        )

    async def spend_reading(picks: dict[str, Any]) -> dict[str, Any]:
        """`seats` over the page's window, period and team (§4.4 *Spend per seat*, TD-859)."""
        args = {"window": picks["window"], **({"at": picks["at"]} if picks["at"] else {})}
        return await call("seats", **args, **({"team": picks["team"]} if picks["team"] else {}))

    @app.get("/api/spend")
    async def spend_api(request: Request):
        """The `seats` reading the Spend page draws, its `window`, `at` and `team` from the query
        (§4.5a *Spend page: Day · Week · Month, the team chips, ‹ ›*)."""
        return await spend_reading(spend_picks(request.query_params))

    @app.get("/api/shape")
    async def shape_api(team: str, window: str = "day"):
        """A team's `shape` reading, which the Spend page's Shape view draws (§4.5a *Spend page: Spend ·
        Shape*, TD-835)."""
        return await call("shape", team=team, window=window)

    async def shape_page(request: Request, picks: dict[str, Any]):
        """The Spend page's Shape view (§4.5 screen 13 *Shape*, TD-835): the `shape` reading of the picked
        team, or of each team on All — the teams the seat ledger read in the window and the teams with a
        record — over the current day or week."""
        from sessionorc.shape import SHAPE_MIN_HOURS

        agent_down, why, readings, teams, failed = False, "", [], set(), []
        try:
            with contextlib.suppress(HTTPException):  # an older home with no seat ledger still has its records
                for t in (await spend_reading({**picks, "team": ""})).get("teams") or []:
                    teams.add(str(t.get("team")))
            teams |= {str(r["team"]) for r in await call("list") if r.get("team")}
            teams -= {SPEND_INTERACTIVE, SPEND_OUTSIDE}
            for t in [picks["team"]] if picks["team"] else sorted(teams):
                try:
                    readings.append(await call("shape", team=t, window=picks["window"]))
                except HTTPException as e:
                    if e.status_code == 503:
                        raise
                    failed.append(f"{t}: {e.detail}")  # one team's failure leaves the others drawn
        except HTTPException as e:
            agent_down = e.status_code == 503
            why = "" if agent_down else f"the home did not serve the team's shape: {e.detail}"
        if failed and not why:
            why = "the home did not serve the team's shape: " + "; ".join(failed)
        ctx = {
            "v": shape_view(readings, picks, sorted(teams), SHAPE_MIN_HOURS)
            if readings or not why
            else {"served": False},
            "picks": picks,
            "why": why,
            "agent_down": agent_down,
        }
        if request.query_params.get("part"):
            return templates.TemplateResponse(request, "shape_part.html", ctx)
        return templates.TemplateResponse(
            request,
            "spend.html",
            {
                **ctx,
                "part": "shape_part.html",
                "host": host_name(),
                "active": "",
                "volatile": hosts.local_host().volatile,
                "usage": {} if agent_down else await chip_usage(call, await call("list")),
                "build_chip": None if agent_down else await chip_build(call),
            },
        )

    @app.get("/spend", response_class=HTMLResponse)
    async def spend_page(request: Request):
        """design §4.5 screen 13 / §4.5a **Spend page** (TD-818, built by TD-832): the seat ledger's reading
        over one window, period and team, shaped by `ui.spend.spend_view`. `part=1` is the body alone,
        which a pick re-reads in place. `view=shape` is the Shape view (`shape_page`, TD-835)."""
        picks = spend_picks(request.query_params)
        if picks["view"] == "shape":
            return await shape_page(request, picks)
        agent_down, got, why = False, None, ""
        try:
            got = await spend_reading(picks)
        except HTTPException as e:
            if e.status_code == 503:
                agent_down = True
            elif e.status_code == 400 and picks["at"]:  # a period the ledger does not hold: the current one, said
                why = f"{e.detail} — the current period is drawn"
                picks["at"] = ""
                with contextlib.suppress(HTTPException):
                    got = await spend_reading(picks)
            else:
                why = f"the home did not serve the seat ledger: {e.detail}"  # an older home: no `seats` RPC
        fleet: list[dict[str, Any]] = []
        all_teams: list[str] = []
        titles: dict[str, str] = {}
        if got is not None:
            with contextlib.suppress(HTTPException):
                fleet = await call("list")
            teams_of = got.get("teams") or []
            if picks["team"]:  # a team's reading lists its own row alone: the chips are All's
                with contextlib.suppress(HTTPException):
                    teams_of = (await spend_reading({**picks, "team": ""})).get("teams") or []
                with contextlib.suppress(HTTPException):
                    titles = titles_of(await call("queue"))
            all_teams = [str(t["team"]) for t in teams_of if t.get("team") not in (SPEND_INTERACTIVE, SPEND_OUTSIDE)]
        ctx = {
            "v": spend_view(got, picks, fleet=fleet, all_teams=all_teams, titles=titles, today=datetime.now().date()),
            "picks": picks,
            "why": why,
            "agent_down": agent_down,
        }
        if request.query_params.get("part"):
            return templates.TemplateResponse(request, "spend_part.html", ctx)
        return templates.TemplateResponse(
            request,
            "spend.html",
            {
                **ctx,
                "host": host_name(),
                "active": "",
                "volatile": hosts.local_host().volatile,
                "usage": {} if agent_down else await chip_usage(call, fleet),
                "build_chip": None if agent_down else await chip_build(call),
            },
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_view(request: Request):
        agent_down, got, usage, info, why = False, {}, {}, {}, ""
        fleet: list[dict[str, Any]] = []
        readings: dict[str, Any] = {}

        async def read(method: str, **params: Any) -> Any:
            try:
                return await call(method, **params)
            except HTTPException as e:
                return e

        # Every read the page makes at once (§4.5 *Page loads*, TD-884): the RPCs, none waiting on
        # another, and this host's files on a worker thread, so the loop is not held by a YAML load
        first, local_files = await asyncio.gather(
            asyncio.gather(
                read("settings"),
                read("usage"),
                read("host"),
                read("list"),
                read("repos", omit=[*REPOS_OMIT_PAGE, "completed"]),  # numbers alone (TD-746)
                read("gate"),  # the usage chip's lines, handed to it below
            ),
            asyncio.to_thread(settings_files),
        )
        for i, r in enumerate(first[:3]):
            if isinstance(r, HTTPException):  # the first of the three refused is the page's, as read in turn
                if r.status_code != 503:
                    why = str(r.detail)  # an agent that refuses the read: its words, the files still drawn
                else:
                    agent_down = True
                break
            if i == 0:
                got = r
            elif i == 1:
                usage = r
            else:
                info = r
        # **balance**'s numbers as they read now (§4.5a, §6 *Balance*): the fleet and the repo readings,
        # which an older agent or a down link may refuse — the settings are still drawn
        if not isinstance(first[3], HTTPException):
            fleet = first[3]
            if not isinstance(first[4], HTTPException):
                readings = first[4]
        # the chip's own reads, handed over where they answered (a refusal: the chip reads it again)
        chip_reads = {
            k: None if isinstance(r, HTTPException) else r
            for k, r in (("usage", first[1]), ("gate", first[5]), ("host", first[2]))
        }
        profiles, default, org, local = (local_files[k] for k in ("profiles", "default", "org", "local"))
        notes: list[str] = [why] if why else []
        notes += local_files["notes"]
        node = (info or {}).get("mode") == "node"
        uiconf.set_read(got or None)
        term = setmod.you(got.get("person"))
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "usage_groups": setmod.usage_cards(profiles, got.get("usage_gate"), usage),
                "max_age": str((got.get("usage") or {}).get("max_age") or ""),
                # **settle** (§4.5a *Settings page: settle*, TD-710): the install's map as the field writes it
                "settle": settle_mod.text_of(got.get("settle")),
                "settle_default": settle_mod.text_of(settle_mod.DEFAULT),
                # **weights** (§4.5a *Settings page: Usage*, TD-832): the prices the seat pass weighs at
                "weights": setmod.weights_card((got.get("spend") or {}).get("weights")),
                "profiles_file": str(profiles_mod.profiles_file()),
                "teams": setmod.team_cards(
                    org.teams,
                    got.get("teams"),
                    sessions=fleet,
                    repos=readings,
                    flows=await asyncio.to_thread(team_flows, org),
                    host=info,
                ),
                "repos": setmod.repo_cards(local_files["repos"], got.get("repos"), (info or {}).get("pulls"), readings),
                # **Sweep** (§4.5a, §4.9b *The switch*, TD-1091): the switch and a line per registered checkout
                "sweep": setmod.sweep_card(got.get("sweep"), local_files["repos"], fleet, readings, profiles),
                "you": term,
                # **Telegram** (§4.5a **You**, §4.10; TD-319 slice 3): the last send is the home's alone
                "telegram": setmod.telegram(
                    got.get("notify"), None if node else (info or {}).get("notify"), reach=got.get("reach")
                ),
                "browser_keys": setmod.BROWSER_KEYS,
                "host_card": local_files["host_card"],
                "profile_cards": setmod.profile_cards(profiles, default),
                "org_cards": setmod.org_cards(org.teams),
                "files": {
                    "settings": str(got.get("file") or ""),
                    "profiles": str(profiles_mod.profiles_file()),
                    "hosts": str(hosts.hosts_file()),
                    "org": str(org.path or orgmod.org_file()),
                },
                "reads": setmod.FILES,
                "set_at": str((info or {}).get("home") or hosts.home_name()) if node else "",
                "notes": notes,
                "migrate": [str(m) for m in got.get("migrate") or []],
                # §4.9b *The person's written rules* (TD-641): what the host refused of `permissions:`
                "permissions_malformed": [str(m) for m in (got.get("permissions") or {}).get("malformed") or []],
                "editor_note": uiconf.open_in().error,
                "host": host_name(),
                "active": "Settings",
                "agent_down": agent_down,
                "volatile": local.volatile,
                "usage": {}
                if agent_down
                else await chip_usage(call, fleet or None, usage=chip_reads["usage"], gate=chip_reads["gate"]),
                "build_chip": None if agent_down else await chip_build(call, chip_reads["host"]),
            },
        )

    def settings_files() -> dict[str, Any]:
        """The Settings page's reads of this host's own files (§4.5 *Page loads*, TD-884) — the profiles,
        the org and every repo's `teams:`, `hosts.yml` and the repos registry — timed as `files`, on a
        worker thread beside the page's RPCs. A malformed profiles file is a note, never a 500."""
        with timing.step("files"):
            notes: list[str] = []
            try:
                profiles, default = profiles_mod.load()
            except ValueError as e:
                profiles, default = {}, ""
                notes.append(str(e))
            org, org_notes = org_here()
            local = hosts.local_host()
            return {
                "profiles": profiles,
                "default": default,
                "org": org,
                "notes": notes + org_notes,
                "local": local,
                "repos": local.repos(),
                "host_card": setmod.host_card(
                    setmod.local_entry(hosts.hosts_file()), local, hosts.home_name(), hosts.nodes()
                ),
            }

    async def body_of(request: Request) -> dict[str, Any]:
        got = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if not isinstance(got, dict):
            raise HTTPException(400, "send a JSON object")
        return got

    def answer(got: Any) -> JSONResponse:
        h.settings_at["at"] = 0.0  # the next page reads the person's settings again (TD-174)
        h.counts.stir()  # the board's horizon is the person's setting: the counts move with it (TD-616)
        return JSONResponse({"ok": True, **(got if isinstance(got, dict) else {})})

    @app.post("/api/settings/usage")
    async def settings_usage(request: Request):
        """§4.5a *Settings page: Usage* → **Save** on a profile card: `{profile, reserves: {label:
        text}}`, each text in `ao gate`'s forms (`30`, `10/day`, empty to clear; on a metered card an
        amount, `$5` or `20M tok`) — refused in place with the same words when it is not one — then
        `set_settings {profile, reserves}`, whose refusal names the billing when the kind is wrong."""
        body = await body_of(request)
        raw = body.get("reserves")
        if not isinstance(raw, dict) or not raw:
            raise HTTPException(400, "usage: send {profile, reserves: {label: reserve}}")
        try:
            reserves = {str(k): setmod.parse_reserve_text(v) for k, v in raw.items()}
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return answer(await call("set_settings", profile=str(body.get("profile") or ""), reserves=reserves))

    @app.post("/api/settings/settle")
    async def settings_settle(request: Request):
        """§4.5a *Settings page: settle* (TD-707, built by TD-710 slice 3): `{settle: text}` — Kind and
        duration pairs, `design-first 5m`, empty for the built-in — refused in place when a pair is not
        one, then `set_settings {settle}`, the whole map replaced."""
        body = await body_of(request)
        try:
            settle = settle_mod.parse_text(str(body.get("settle") or ""))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return answer(await call("set_settings", settle=settle))

    @app.post("/api/settings/spend")
    async def settings_spend(request: Request):
        """§4.5a *Settings page: Usage* → **weights** **Save** (TD-818, built by TD-832): `{rows: [{model,
        input, output, cache_read, cache_write}], as_of}`, the card whole — refused in place when a row is not
        one — to `set_settings {spend}`, the rows that differ from the design's default and nothing else."""
        body = await body_of(request)
        try:
            spend = setmod.weights_body(body.get("rows"), body.get("as_of"))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return answer(await call("set_settings", spend=spend))

    @app.post("/api/settings/sweep")
    async def settings_sweep(request: Request):
        """§4.5a *Settings page* → the **Sweep** card's **Save** (§4.9b *The switch*, TD-1091): `{on: bool,
        every, profile}`, an empty `every` or `profile` cleared — `7d` and the role's precedence — then
        `set_settings {sweep}`, whose refusal names a duration that is not one."""
        body = await body_of(request)
        if not isinstance(body.get("on"), bool):
            raise HTTPException(400, "sweep: send {on: true|false, every, profile}")
        every, profile = str(body.get("every") or "").strip(), str(body.get("profile") or "").strip()
        sweep = {"on": body["on"], "every": every or None, "profile": profile or None}
        return answer(await call("set_settings", sweep=sweep))

    @app.post("/api/settings/max_age")
    async def settings_max_age(request: Request):
        """§4.5a *Settings page: Usage* → **trust a reading for** (TD-233): `{max_age: text}` — an age
        (`90m`, `2h`) or `off`, empty clearing it back to the hour — to `set_settings {usage}`, whose
        refusal names the bounds."""
        body = await body_of(request)
        text = str(body.get("max_age") or "").strip()
        return answer(await call("set_settings", usage={"max_age": text or None}))

    def team_flows(org: orgmod.Org) -> dict[str, list[dict[str, Any]]]:
        """Each team's `teams.flow_rows` for the Settings page's **flow** pick (§4.5a, §4.9c), a team
        whose repo this host cannot read having rows that judge nothing (`unread`). A node draws none:
        the org is the home's (§4.4a)."""
        if hosts.is_node():
            return {}
        here = host_name()
        with timing.step("flows"):  # each team's repo read for its flow's rows (TD-884)
            return {n: teams.flow_rows(org, t, t.host or here, here) for n, t in org.teams.items() if t.flows}

    @app.post("/api/settings/teams")
    async def settings_teams(request: Request):
        """§4.5a *Settings page: Teams* → **Save** / **Clear**: `{team, until?, reserve?, on_work?, balance?}` —
        `until` in the CLI's forms (`06:00`, `+8h`, ISO) read in this host's clock and handed over as
        an instant, `null` to clear; `reserve` a whole percent, `0` or empty clearing it; `on_work`
        (**when work appears**, §6 rule 8) one of `ask`, `start`, `off`, as `ao team on-work`; `balance`
        (§6 *Balance*) the lines whole, `{prs?, oldest?, review?}`, or `null` for the switch off — a
        line left out is a line not drawn, and the agent's refusal names what is wrong. A team the
        org does not define is refused, naming the defined ones, as `ao team until` refuses it."""
        body = await body_of(request)
        team = str(body.get("team") or "")
        defined = org_here()[0].teams
        if team not in defined:
            raise HTTPException(
                400, f"no team {team!r}: the org defines {', '.join(sorted(defined)) or 'none'} (design §4.9)"
            )
        change: dict[str, Any] = {}
        if "until" in body:
            when = str(body.get("until") or "").strip()
            try:
                change["until"] = clistop(when) if when else None
            except AgentError as e:
                raise HTTPException(400, str(e)) from None
        if "reserve" in body:
            r = str(body.get("reserve") if body.get("reserve") is not None else "").strip()
            if r and not r.isdigit():
                raise HTTPException(400, f"reserve priority is a whole percent, not {r!r}")
            change["reserve"] = int(r) if r and int(r) else None  # 0 clears it, as `ao team reserve 0` does
        if "on_work" in body:
            if body.get("on_work") not in setmod.settings_mod.ON_WORK:
                raise HTTPException(400, f"when work appears is ask, start or off, not {body.get('on_work')!r}")
            change["on_work"] = body["on_work"]
        if "balance" in body:
            bal = body.get("balance")
            if bal is not None and not isinstance(bal, dict):
                raise HTTPException(400, "balance is its lines, {prs, oldest, review}, or null for off")
            if bal is not None:
                bal = {k: v for k, v in bal.items() if not (v is None or v is False or v == "")}
                if re.fullmatch(r"[0-9]+", str(bal.get("prs", "")).strip()):
                    bal["prs"] = int(str(bal["prs"]).strip())  # a field's text; anything else the agent refuses
                if not bal:
                    raise HTTPException(
                        400,
                        "balance draws at least one line: open PRs, the oldest or the techlead's queue"
                        " — or turn it off",
                    )
            change["balance"] = bal
        flow = str(body.get("flow") or "") if "flow" in body else None
        if not change and flow is None:
            raise HTTPException(400, "teams: send until, reserve, on_work, balance or flow")
        got: dict[str, Any] = {}
        org = org_here()[0]
        if flow is not None:  # **flow**: checked before anything is written, so a refusal saves nothing
            if hosts.is_node():
                raise HTTPException(409, node_org_note())
            try:
                await asyncio.to_thread(teamrun.check_pick, rpc, org, team, host_name(), flow)
            except (teams.TeamError, ValueError, OSError, AgentError, AgentUnavailable) as e:
                raise HTTPException(400, f"flow not set — {str(e).strip(chr(34))}") from None
        if change:
            got = await call("set_settings", teams={team: change})
            with contextlib.suppress(Exception):  # the header's stops note reads the new time on the next delta
                uiconf.set_read(await call("settings"))
        if flow is not None:  # …then written and nothing more (§4.9c, TD-356)
            try:
                picked = await asyncio.to_thread(teamrun.pick_flow, rpc, org, team, host_name(), flow)
            except (teams.TeamError, ValueError, OSError, AgentError, AgentUnavailable) as e:
                raise HTTPException(400, f"the rest saved; flow not set — {str(e).strip(chr(34))}") from None
            got = {**got, "pick": picked}
        return answer(got)

    @app.post("/api/settings/repos")
    async def settings_repos(request: Request):
        """§4.5a *Settings page: Repos* → the promote's **auto** switch, `{repo, auto: bool}`, written
        to `repos.<repo>.promote.auto`, or the **pull** switch, `{repo, pull: bool}`, written to
        `repos.<repo>.pull` (§6 *Pull*, TD-263), or the **sync** switch, `{repo, sync: bool}`, written to
        `repos.<repo>.sync.auto` (§6 *Sync*, TD-685), or the **Sweep** card's **swept** switch, `{repo, sweep:
        bool}`, written to `repos.<repo>.sweep` (§4.9b *The switch*, TD-1091) — each through `set_settings`,
        one key a press."""
        body = await body_of(request)
        repo, auto, pull, sync = str(body.get("repo") or ""), body.get("auto"), body.get("pull"), body.get("sync")
        keys = [k for k in ("auto", "pull", "sync", "sweep") if k in body]
        if not repo or len(keys) != 1 or not isinstance(body[keys[0]], bool):
            raise HTTPException(
                400,
                "repos: send {repo, auto: true|false}, {repo, pull: true|false}, {repo, sync: true|false} "
                "or {repo, sweep: true|false}",
            )
        if keys == ["sweep"]:
            return answer(await call("set_settings", repos={repo: {"sweep": body["sweep"]}}))
        if keys == ["pull"]:
            return answer(await call("set_settings", repos={repo: {"pull": pull}}))
        if keys == ["sync"]:
            return answer(await call("set_settings", repos={repo: {"sync": {"auto": sync}}}))
        return answer(await call("set_settings", repos={repo: {"promote": {"auto": auto}}}))

    @app.post("/api/settings/you")
    async def settings_you(request: Request):
        """§4.5a *Settings page: You* → **Save**: `{open_in?, file_link?: {folder_first?, wait?}, terminal?: {size?,
        face?, copy_on_select?}, inbox?: {board_show?}, attach?: {max?}, composer?}` into `person:` through
        `set_settings`, which validates each and refuses a session. `open_in` is `vscode`, `none` or `{label, url,
        file}` (TD-536) — a template the UI would
        refuse (§5: its scheme) is refused here in the same words, before it is written; a `null` clears a key."""
        body = await body_of(request)
        change: dict[str, Any] = {}
        if "open_in" in body:
            o = body["open_in"]
            if o is not None:
                got = uiconf.parse_open_in(o)
                if got.error:
                    raise HTTPException(400, got.error)
            change["open_in"] = o
        fl = body.get("file_link")
        if fl is not None:  # **file link** (§4.5a, §5 `person.file_link`, TD-536); `set_settings` refuses a bad value
            if not isinstance(fl, dict) or not set(fl) <= {"folder_first", "wait"}:
                raise HTTPException(400, "you: file_link takes folder_first and wait")
            change["file_link"] = fl
        term = body.get("terminal")
        if term is not None:
            if not isinstance(term, dict) or not set(term) <= {"size", "face", "copy_on_select"}:
                raise HTTPException(400, "you: terminal takes size, face and copy_on_select")
            change["terminal"] = term
        inbox = body.get("inbox")
        if inbox is not None:  # **board items shown** (§4.5a, TD-220 slice 4); `set_settings` refuses a bad value
            if not isinstance(inbox, dict) or not set(inbox) <= {"board_show"}:
                raise HTTPException(400, "you: inbox takes board_show")
            change["inbox"] = inbox
        attach = body.get("attach")
        if attach is not None:  # **attachment bound** (§4.5 screen 8, TD-478); `set_settings` refuses a bad value
            if not isinstance(attach, dict) or not set(attach) <= {"max"}:
                raise HTTPException(400, "you: attach takes max")
            change["attach"] = attach
        if "composer" in body:  # **the bar** (§4.5a *Focus composer*, TD-500); `set_settings` refuses a bad value
            change["composer"] = body["composer"]
        if not change:
            raise HTTPException(400, "you: send open_in, file_link, terminal, inbox, attach or composer")
        return answer(await call("set_settings", person=change))

    @app.post("/api/settings/notify")
    async def settings_notify(request: Request):
        """§4.5a **You**: **Telegram** → **Save**: `{telegram: {on, secrets, link}}` into `notify:` through
        `set_settings` (§4.10, TD-319), an empty field cleared — whose refusal (`on` with no secrets, a
        secrets that is not a `project/config`, a link that is not `http(s)://`) is said in place."""
        body = await body_of(request)
        tg = body.get("telegram")
        if not isinstance(tg, dict) or not tg or not set(tg) <= {"on", "secrets", "link"}:
            raise HTTPException(400, "notify: send {telegram: {on, secrets, link}}")
        change = {k: (v.strip() or None) if isinstance(v, str) else v for k, v in tg.items()}
        return answer(await call("set_settings", notify={"telegram": change}))

    @app.post("/api/settings/notify_test")
    async def settings_notify_test(request: Request):
        """§4.5a **You**: **Telegram** → **Send a test**: `notify_test` (§4.10) — one message now with the
        saved values, whatever the switch says, sent from the home; its result in words."""
        return JSONResponse({"ok": True, **(await call("notify_test"))})


def _inbox_routes(app: FastAPI, h: SimpleNamespace) -> None:
    """The person's Inbox: the page, its payload and its controls (design §4.10, §4.5a)."""
    call, person_view, inbox_html = h.call, h.person_view, h.inbox_html
    board_view = h.board_view

    @timing.timed("ledger")
    async def ledger_view(fleet: list[dict[str, Any]]) -> dict[str, Any]:
        """The ledger's rows of *Later* (§4.5 screen 6, TD-368, TD-565) from the home's repo facts and the
        definitions' team per repo; empty when either cannot be read — nothing is then drawn."""
        repos: dict[str, Any] = {}
        named: dict[str, str] = {}
        with contextlib.suppress(Exception):
            repos = await h.repos()
        with contextlib.suppress(Exception):
            named = repo_teams(await h.defs(), host_name())
        return ledger_for_you(repos, fleet, named)

    h.ledger_view = ledger_view  # the Queue draws these rows on their cards (TD-771)

    @app.get("/inbox", response_class=HTMLResponse)
    async def inbox_page(request: Request):
        """design §4.5 screen 6 / §4.5a **Inbox page** (TD-069 steps 1 and 2): full width, the
        person inbox and the sessions' states in three sections, and the count that means *what is
        waiting on a person*. From step 3 the due board items join **Needs you** too."""
        repos_omit(REPOS_OMIT_INBOX)
        agent_down, fleet = False, []
        choices = board_choices()  # once for the request (§4.5 *Page loads*, TD-879)
        try:
            fleet = await call("list")  # person_view's one list, kept for the usage chip (TD-287)
            got, states = await h.person_inbox(fleet, choices=choices), await h.person_states(fleet)
        except HTTPException as e:
            if e.status_code != 503:
                raise
            got, states, agent_down = {"entries": []}, [], True  # the banner + Retry, never a bare 503
        # with the host agent down nothing is claimed as waiting — the Org's top bar and the poll say
        # the same — so the board is left unread rather than counted on this page alone (review of #472)
        hz, board_note = (
            ({"due": [], "ahead": [], "hidden": [], "waiting": [], "line": None}, "")
            if agent_down
            else await board_view(choices)
        )
        hz = with_standings(hz, fleet)
        cards = {} if agent_down else await h.queue_cards()
        sections = inbox_sections(
            got["entries"],
            states=states,
            trail=got.get("trail") or (),
            attention_snoozed=got.get("attention_snoozed"),
            handed=got.get("handed") or (),
            # due rows, and the answered ones that wait on a session (TD-305), with the fleet for
            # the *waiting on …* words
            boards=hz["due"] + hz["waiting"],
            fleet=fleet,
            cards=cards,
        )
        picks = rail_picks(request.query_params)
        lf = {"n": 0, "groups": []} if agent_down else await ledger_view(fleet)
        # the ledger's rows and the board's lines not yet due whose entry a Queue card holds are drawn there
        # (§4.5 screen 6 *Where a row is drawn*, TD-771): *Later* keeps the rest
        lf, ahead, _, unshown = split_later(lf, hz["ahead"], cards, hz["hidden"])
        hz = horizon_left(hz, ahead, unshown)
        return templates.TemplateResponse(
            request,
            "inbox.html",
            {
                "sections": sections,
                "picks": picks,
                "rail": rail_counts(rail_rows(sections, hz["ahead"], ledger_rows(lf)), picks),
                "origin": page_origin(request),
                "board_note": board_note,
                "horizon": hz,
                "ledger": lf,
                "board_choices": choices,
                **tab_counts(sections),
                "host": host_name(),
                "active": "Inbox",
                "agent_down": agent_down,
                "volatile": hosts.local_host().volatile,
                "usage": {} if agent_down else await chip_usage(call, fleet),
                "build_chip": None if agent_down else await chip_build(call),
            },
        )

    @app.get("/api/fold", response_class=HTMLResponse)
    async def api_fold(request: Request, key: str = ""):
        """design §4.5 *Page loads* (*A row's folded details on a Queue card*, TD-891): one fold's body, read
        on its first open, by the row renderer's own macro — the one source its key names: a board line
        (`board:<root>:<line>`, or `cb:board:…` for its *context* on a card) from the home's board reading, a
        ledger row (`ledger:<repo>:<id>`) from its repo's ledger reading, a mail item's *context* on a card
        (`card:<id>`, TD-911), else a person-inbox entry or a row handed to a seat by its id, a person's read marking
        nothing. A key that names nothing is a 404, which the fold says as *gone — reload*."""
        e: Any = None
        if key.startswith(("board:", "cb:board:")):
            # a board line's details, or its *context* drawn whole on a card (`cb:board:…`, TD-1066)
            kind, bid = ("boardcard", key.removeprefix("cb:")) if key.startswith("cb:") else ("board", key)
            e = next((r for r in (await h.board_all())[0] if r.get("id") == bid), None)
        elif key.startswith("ledger:"):
            kind, fleet = "ledger", []
            with contextlib.suppress(HTTPException):
                fleet = await call("list")
            rows = (r for g in (await h.ledger_view(fleet)).get("groups") or () for r in g.get("rows") or ())
            e = next((r for r in rows if r.get("row_id") == key), None)
        elif key:
            # a mail item drawn whole on a card folds its *context* (`card:<id>`, §4.5 screen 12 *An item's shape*)
            kind, mid = ("card", key.removeprefix("card:")) if key.startswith("card:") else ("mail", key)
            got = await call("inbox", id=PERSON)
            # a row the person handed to a seat is the seat's entry, carried as `handed` (§4.10 *A look*)
            e = next((x for x in [*(got.get("entries") or ()), *(got.get("handed") or ())] if x.get("id") == mid), None)
        if e is None:
            raise HTTPException(404, f"{key or 'no key'}: gone — reload")
        with timing.step("render"):
            html = templates.get_template("fold_body.html").render(kind=kind, e=e, origin=page_origin(request))
        return HTMLResponse(html)

    @app.get("/inbox/{mid}", response_class=HTMLResponse)
    async def inbox_entry_page(request: Request, mid: str):
        """design §4.5 screen 6 *The message page*, §4.5a **Inbox message page** (TD-129, built by
        TD-136): one mail entry whole — its row, drawn by the row's own macro in the section the
        list has it in, so its controls, RPCs and confirms are the list's, with *details* open —
        then its thread from the person-only `thread` read, oldest first, none of it a control.
        **Back** returns to the list the page was opened from (`back`, the list's query) at this
        row. An entry the person inbox no longer holds reads *gone*; a refusal (another host's id,
        §4.4a) reads in the host agent's words. Reading marks nothing (§4.10)."""
        repos_omit(REPOS_OMIT_INBOX)
        back = str(request.query_params.get("back") or "")
        # Back returns to the list the row is drawn in (§4.5 screen 6 *Where a row is drawn*, TD-771): the
        # Inbox's picks (`?…`), or the Queue's page with its picks (`/queue…`) for a row drawn on a card
        on_queue = back == "/queue" or back.startswith("/queue?")
        back = back if back.startswith("?") or on_queue else ""
        ctx: dict[str, Any] = {
            "host": host_name(),
            "active": "Inbox",
            "usage": await chip_usage(call),
            "build_chip": await chip_build(call),
            "volatile": hosts.local_host().volatile,
            "mid": mid,
            "back_url": f"{back}#{mid}" if on_queue else f"/inbox{back}#{mid}",
            "origin": page_origin(request),
            "fold_open": True,
            "board_choices": board_choices(),
            "entry": None,
            "section": "",
            "thread": [],
            "pruned": False,
            "gone": "",
        }
        try:
            got, states = await person_view()
        except HTTPException as e:
            if e.status_code != 503:
                raise
            ctx["gone"] = f"{host_name()}: host agent unreachable — no mail can be read until it is back"
            return templates.TemplateResponse(request, "inbox_entry.html", ctx)
        sections = inbox_sections(
            got["entries"],
            states=states,
            trail=got.get("trail") or (),
            attention_snoozed=got.get("attention_snoozed"),
            handed=got.get("handed") or (),
        )
        for sec in INBOX_SECTIONS:
            e = next((x for x in sections[sec] if x.get("id") == mid and not x.get("row")), None)
            if e is not None:
                ctx["entry"], ctx["section"] = e, sec
                break
        if ctx["entry"] is None:
            ctx["gone"] = f"gone: {mid} is no longer in the person inbox — pruned by retention, or dismissed"
            if "@" in mid:  # another host's entry (§4.4a): the host agent says why in its own words
                try:
                    await call("thread", msg=mid)
                except HTTPException as err:
                    ctx["gone"] = str(err.detail)
            return templates.TemplateResponse(request, "inbox_entry.html", ctx)
        if ctx["entry"].get("handed_row"):
            # a handed entry's one copy is its holder's, and `thread` reads the person inbox alone:
            # its thread here is the person inbox's entries on its root — the seat's questions and
            # the person's answers to them (§4.10 *An entry handed to a seat*)
            th = {"entries": [e for e in got["entries"] if e.get("root") == mid], "pruned": False}
        else:
            th = None
        try:
            th = th or await call("thread", msg=mid)
        except HTTPException as err:
            # an older host agent has no `thread`: the entry still reads whole, the thread says why
            ctx["thread_error"] = str(err.detail)
            th = {"entries": [], "pruned": False}
        # a thread reaches senders the person inbox never heard from (a techlead's reply to its asker)
        names = {o.get("id"): o.get("name") or o.get("id") for o in await call("list")}
        ctx["thread"] = [
            {
                **t,
                "from_name": "person" if t.get("from") == "person" else names.get(t.get("from")) or t.get("from"),
                "from_open": t.get("from") if t.get("from") in names else "",  # its paths' context (TD-1108)
                "age": _age(t.get("at"), datetime.now(UTC)),
            }
            for t in th.get("entries") or ()
            if t.get("id") != mid
        ]
        ctx["pruned"] = bool(th.get("pruned"))
        return templates.TemplateResponse(request, "inbox_entry.html", ctx)

    @app.get("/api/person/inbox")
    async def api_person_inbox(request: Request):
        """design §4.5a Sessions top bar **Inbox** and the **Inbox page** (§4.10): the entries, which
        section each is in, their rendered rows, and `needs` — the count, computed in the one place
        (`inbox_sections`) the page renders from, so the top bar's number and the page cannot
        disagree. Both poll this: the pushed stream carries session records only, and the person
        inbox belongs to none. The read marks nothing (`person_inbox`, above).

        From TD-069 step 2 the **state rows** ride this poll too, rendered from a fresh `list`
        (`person_states`): the Org's pushed stream is per-record and this page is per-person, so
        the simplest correct thing is one snapshot per poll — a row whose state changed in between
        is corrected by the next one, and a permission answered here leaves at once because the
        press refreshes.

        `?counts=1` is the top bar's read on every other page (TD-611): the same `inbox_sections`,
        so the numbers are the page's, but nothing rendered and no entries sent — the full read is
        megabytes of markup on the UI's one loop, which every Focus keystroke shares."""
        repos_omit(REPOS_OMIT_INBOX)
        watching = request.query_params.get("watching") == "1"  # the page is visible (§4.10, TD-319)
        if request.query_params.get("counts") == "1":
            # the keeper's numbers, counted fresh for this page's `watching`; `since=<rev>` it already
            # holds answers `{unchanged: true}` (§4.4 *The Inbox's counts*, TD-616)
            gz = gzip_ok(request)
            return json_answer(json_body(await h.counts.read(watching, request.query_params.get("since")), gz), gz)
        try:
            fleet = await call("list")  # person_view's one list, kept for the board's *waiting on* (TD-305)
            choices = board_choices()  # once for the request (§4.5 *Page loads*, TD-879)
            got, states = await h.person_inbox(fleet, watching=watching, choices=choices), await h.person_states(fleet)
        except HTTPException as e:
            if e.status_code != 503:
                raise
            # The page's own load already answers a host agent that is down with a banner; its
            # **poll** answered a bare 503, which the client could only drop on the floor — the
            # rows would sit there looking current (design §4.5 *there is no silent failure path*,
            # TD-069's leftover). So the poll says it in a shape the page can render: no entries,
            # no counts claimed, and the reason in words — on a `counts` read too, whose
            # `agent_down` and `why` are the same here and the rest is empty.
            return {
                "entries": [],
                "sections": {k: [] for k in INBOX_SECTIONS},
                "needs": None,  # not zero: nothing is *known* to be waiting, which is not *nothing is*
                "fyi_n": None,  # the same rule for the second number: not known is not zero
                "overdue_n": None,  # …and the rollup's overdue count (TD-178)
                "snoozed_n": 0,
                "answered_marks": None,  # not known either: the team headers keep what they showed
                "html": {},
                "unread": None,
                "agent_down": True,
                "why": str(e.detail),
            }
        hz, board_note = await board_view(choices)
        hz = with_standings(hz, fleet)
        build = await chip_build(call)
        lf = await ledger_view(fleet)
        origin = page_origin(request)
        gz = gzip_ok(request)
        cards = await h.queue_cards()
        lf, ahead, _, unshown = split_later(lf, hz["ahead"], cards, hz["hidden"])  # a card's is drawn there (TD-771)
        hz = horizon_left(hz, ahead, unshown)

        def read() -> tuple[list[dict[str, Any]], bytes]:
            """Everything after the awaits, on a worker thread (TD-611 slice 2): the sections, the
            markup and the JSON were half a second of the UI's one loop per full read, which every
            Focus keystroke and output frame shares. The body is encoded here, and gzipped here when
            the browser takes it, so nothing the size of the inbox is touched on the loop."""
            sections = inbox_sections(
                got["entries"],
                states=states,
                trail=got.get("trail") or (),
                attention_snoozed=got.get("attention_snoozed"),
                handed=got.get("handed") or (),
                boards=hz["due"] + hz["waiting"],
                fleet=fleet,
                cards=cards,
            )
            got["board_note"] = board_note
            got["sections"] = {k: [e["id"] for e in sections[k]] for k in INBOX_SECTIONS}
            got.update(counts_of(sections, build))
            got["html"] = inbox_html(sections, origin)
            # the board's horizon (TD-220): coming up, the fold and the line, put back whole by the poll
            got["html"]["horizon"] = templates.get_template("board_horizon.html").render(hz=hz, origin=origin)
            got["html"]["ledger"] = templates.get_template("ledger_for_you.html").render(lf=lf, origin=origin)
            # the rail's *Teams* lines (§4.5 screen 6 *The rail*): a team appears or goes with its
            # rows, so the poll brings the group's markup as it brings the rows'; the script presses
            # the lines the URL picks and recounts every line from the rows on the page
            rail = rail_counts(rail_rows(sections, hz["ahead"], ledger_rows(lf)), rail_picks({}))
            rail_mod = templates.get_template("inbox_rail.html").module
            got["html"]["rail_teams"] = str(rail_mod.teams_group(rail, rail_picks({})))  # type: ignore[attr-defined]
            # …and its *Repos* lines (TD-741), which come and go with the board's rows
            got["html"]["rail_repos"] = str(rail_mod.repos_group(rail, rail_picks({})))  # type: ignore[attr-defined]
            return sections["needs"], json_body(got, gz)

        needs, body = await asyncio.to_thread(read)
        h.needs_cache["rows"] = needs  # the next delta's *asked you* lines on the Org (TD-354)
        return json_answer(body, gz)

    # design §4.5a **Inbox row** controls (§4.10): each is a person's own act on their own inbox,
    # so each calls its RPC **caller-less** — a person is not a session, and every one of these is
    # refused to every session by the agent. The UI adds no rule of its own: a refusal comes back
    # as the toast every other RPC error on the page does.
    PERSON_ACTS = {"pause": "inbox_pause", "resume": "inbox_resume", "gowithit": "inbox_go_with_it"}

    @app.post("/api/settings/person")
    async def api_settings_person(request: Request):
        """A person's own settings from a page (design §5 `person:`, §4.4a *Settings, replicated*):
        today the Focus pane's **copy on select** toggle (§4.5a, TD-174), `{terminal: {copy_on_select}}`
        through `set_settings`, which validates it and refuses a session. The page's next settings
        read takes it up, so the choice survives a reload."""
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        term = body.get("terminal") if isinstance(body, dict) else None
        if (
            not isinstance(term, dict)
            or set(term) != {"copy_on_select"}
            or not isinstance(term["copy_on_select"], bool)
        ):
            raise HTTPException(400, "person: send {terminal: {copy_on_select: true|false}}")
        got = await call("set_settings", person={"terminal": term})
        h.settings_at["at"] = 0.0  # read it again before the next page is drawn
        h.counts.stir()  # the counts move with the person's settings (TD-616)
        return JSONResponse({"ok": True, **(got if isinstance(got, dict) else {})})

    @app.post("/api/person/{action}")
    async def api_person_action(action: str, request: Request):
        """design §4.5a Sessions top bar **person inbox** → Reply and delete (§4.10): a person's reply
        lands in the sender's inbox (the agent addresses it to the entry's sender and closes its
        `ask`); delete removes the entry from the person inbox only — the sender keeps its copy.
        From 2026-09-19 (TD-069 step 1) the Inbox page's own controls join it: **Snooze** and
        a snoozed row's *now* (`inbox_snooze`, with and without an `until`), **Pause** / **Resume**, and
        **Go with it**."""
        body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        if action in PERSON_ACTS or action == "snooze":
            ref = str(body.get("msg") or "").strip()
            if not ref:
                raise HTTPException(400, f"{action} needs the entry's id")
            if action == "snooze":
                # no `until` is the clear — *now* on a snoozed row's Snooze menu (§4.10 *Snooze*, TD-373)
                until = str(body.get("until") or "").strip() or None
                got = await call("inbox_snooze", msg=ref, until=until)
            else:
                got = await call(PERSON_ACTS[action], msg=ref)
            return JSONResponse({"ok": True, **got})
        if action == "hand_look":
            # design §4.5a **Send to reviewer** (§4.10 *A look*, TD-292 slice 4b): one press, no
            # dialog — `inbox_hand {msg, seat}`, the seat being the sender's team's techlead as this
            # page reads it from `org.yml`, since the host agent reads none. No seat is passed as
            # "", and the agent's refusal says so in its own words, as it does a look already answered
            ref, team = str(body.get("msg") or "").strip(), str(body.get("team") or "").strip()
            if not ref:
                raise HTTPException(400, "Send to reviewer needs the look's id")
            org = await h.defs()
            t = org.teams.get(team)
            here = host_name()
            seat = teams.seat_id(org, t, t.host or here, here) if t is not None else ""
            got = await call("inbox_hand", msg=ref, seat=seat)
            return JSONResponse({"ok": True, **(got if isinstance(got, dict) else {})})
        if action == "board":
            # design §4.5a **Due strip / Inbox board row** → **Snooze ▾** and **Done** on a board row
            # (§4.4 *Board write-back*, TD-069 step 3): the host agent edits the one line on origin's
            # head and lands it there by its own PR (TD-264). The row hands back what the reader gave it — the board,
            # the line and its text — and the agent refuses the edit when that line has moved on.
            what = str(body.get("action") or "")
            if what == "reply":
                # §4.5a *Due strip / Inbox board row* → **Reply** (§4.4, TD-142): the person's words
                # appended to the item's own line by `board_reply`, which re-checks the line as an
                # edit does; `refs` are the reader's when it carries them (TD-142 slice 2)
                board, text = str(body.get("board") or ""), str(body.get("text") or "")
                reply = str(body.get("reply") or "").strip()
                try:
                    line = int(body.get("line"))
                except (TypeError, ValueError):
                    raise HTTPException(400, "a board reply names the item's line") from None
                if not board or not text or not reply:
                    raise HTTPException(400, "a board reply names the board, the item's text and the reply")
                refs = [str(r) for r in body.get("refs") or () if str(r).strip()]
                # §4.4 *A board line's id* (TD-603): the row's id, by which the agent finds the line first
                key = str(body.get("key") or "").strip()
                got = await call("board_reply", board=board, line=line, text=text, reply=reply, refs=refs, key=key)
                return JSONResponse({"ok": True, **(got if isinstance(got, dict) else {})})
            if what == "add":
                # §4.5a *Inbox row: FYI* → **Put on the board** (TD-140): the form's board, text and
                # Due, and the entry it comes from; the agent writes the one line, commits it, and
                # only then dismisses the entry — its refusal is the form's, drawn in place
                ref, board, text = (str(body.get(k) or "").strip() for k in ("msg", "board", "text"))
                due = str(body.get("due") or "").strip()
                if not ref or not board or not text or not due:
                    raise HTTPException(400, "Put on the board names the entry, the board, the text and a Due date")
                got = await call("board_edit", board=board, action="add", text=text, due=due, entry=ref)
                return JSONResponse({"ok": True, **(got if isinstance(got, dict) else {})})
            if what not in BOARD_ACTS:
                raise HTTPException(400, f"a board row's act is {', '.join(BOARD_ACTS)}, not {what!r}")
            try:
                line = int(body.get("line"))
            except (TypeError, ValueError):
                raise HTTPException(400, "a board row's act names the item's line") from None
            board, text = str(body.get("board") or ""), str(body.get("text") or "")
            if not board or not text:
                raise HTTPException(400, "a board row's act names the board and the item's text")
            due = str(body.get("due") or "").strip() or None
            if what == "snooze" and not due:
                raise HTTPException(400, "a snooze names the new date, YYYY-MM-DD")
            more: dict[str, Any] = {}
            if what == "decide":
                # §4.5a **answers** / **Go with it** (§4.4 *Decide*, TD-255): the answer pressed and
                # the item's `answers` as the reader gave them to the row, as a Reply's `refs` are
                # handed; the agent refuses an answer that is not one of them word for word
                answer = str(body.get("answer") or "").strip()
                answers = body.get("answers")
                if not answer or not isinstance(answers, list):
                    raise HTTPException(400, "a decide names the answer and the item's answers")
                more = {"answer": answer, "answers": [str(a) for a in answers]}
            key = str(body.get("key") or "").strip()  # the row's id (§4.4 *A board line's id*, TD-603)
            got = await call("board_edit", board=board, line=line, text=text, action=what, due=due, key=key, **more)
            return JSONResponse({"ok": True, **(got if isinstance(got, dict) else {})})
        if action == "ledger":
            # design §4.5a **Inbox row: ledger entry** (§4.5 screen 6, TD-565): an answer by its index,
            # **Go with it** (`go`) or a Reply's `words`, for the entry `id` in the checkout `repo`; the
            # home reads the entry from its repo facts and writes one decided board line, or refuses
            repo, ref = str(body.get("repo") or "").strip(), str(body.get("id") or "").strip()
            if not repo or not ref:
                raise HTTPException(400, "a ledger answer names the repo and the entry")
            more: dict[str, Any] = {}
            if road := str(body.get("road") or ""):
                # **Done…** / **Back to design…** (§4.5 screen 12 *any open row*, TD-905): refused here where
                # nobody would read the line; the home tells, clears a hold and writes it
                if not repo.startswith(("/", "~")):  # a Queue row names its repo: the registered checkout's name
                    repo = next((str(p) for p in hosts.local_host().repos() if Path(p).expanduser().name == repo), repo)
                org, _notes = await asyncio.to_thread(org_here)
                if why := await asyncio.to_thread(road_refusal, org, repo, road, host_name()):
                    raise HTTPException(409, why)
                got = await call("ledger_decide", repo=repo, id=ref, road=road, words=str(body.get("words") or ""))
                return JSONResponse({"ok": True, **(got if isinstance(got, dict) else {})})
            if body.get("go"):
                more["go"] = True
            elif body.get("answer") is not None:
                try:
                    more["answer"] = int(body["answer"])
                except (TypeError, ValueError):
                    raise HTTPException(400, "a ledger answer is the answer's index") from None
            else:
                words = str(body.get("words") or "").strip()
                if not words:
                    raise HTTPException(400, "a ledger Reply needs its words")
                more["words"] = words
            got = await call("ledger_decide", repo=repo, id=ref, **more)
            return JSONResponse({"ok": True, **(got if isinstance(got, dict) else {})})
        if action == "dismiss":
            # design §4.10 *The Inbox is a queue* (TD-079 step 2): **Dismiss** and **Dismiss all**.
            # A **list of ids**, because *Dismiss all* dismisses the entries **this browser has on
            # screen** — mail that arrived after the page was drawn is exactly what must not go
            # unseen — and the ids are the browser's, mail (`m-`) and trail (`t-`) alike. The agent
            # refuses an id that is still an open question, naming it; that comes back as the toast.
            raw = body.get("msg")
            ids = [str(x).strip() for x in (raw if isinstance(raw, list) else [raw]) if str(x or "").strip()]
            if not ids:
                raise HTTPException(400, "dismiss names the entries to dismiss, by id")
            got = await call("inbox_dismiss", msg=ids)
            return JSONResponse({"ok": True, **got})
        if action == "attention_snooze":
            # design §4.5a **Inbox row: state** / §4.10: a **state row's** snooze — `stalled?` and
            # unpushed work, the two that are not on the tool's clock. It is keyed on the record
            # **and the row kind**, because a session's permission and its stalled row are two rows
            # and snoozing one is not snoozing the other; no `until` is the clear (a snoozed row's *now*).
            sid, kind = str(body.get("id") or "").strip(), str(body.get("kind") or "").strip()
            if not sid or not kind:
                raise HTTPException(400, "a state row's snooze names the session and the row kind")
            got = await call("attention_snooze", id=sid, kind=kind, until=str(body.get("until") or "").strip() or None)
            return JSONResponse({"ok": True, **got})
        if action in ("promote", "clear_promote"):
            # design §4.5a **Inbox row: promote** (§6 *Promote*, TD-132 slice 3): **Promote** presses
            # the `promote` RPC with main's head, **Dismiss** on a failure row `clear_promote`. Both
            # are the person's own and the agent refuses them to a session; a refusal — the tree, a
            # run in flight, a failure standing — comes back in its words and is drawn in place.
            repo = str(body.get("repo") or "").strip()
            if not repo:
                raise HTTPException(400, f"{action} names the repo")
            got = await call(action, repo=repo)
            return JSONResponse({"ok": True, **got})
        if action == "ci_rerun":
            # design §4.5a **Inbox row: CI not starting** (TD-687): **Re-run** is the person's own, served
            # by the home alone, which re-runs every run the row names and answers how many it asked for
            # and how many GitHub refused; a refusal (no row, nothing to re-run, a node) in its words
            owner = str(body.get("owner") or "").strip()
            if not owner:
                raise HTTPException(400, "ci_rerun names the account")
            got = await call("ci_rerun", owner=owner)
            return JSONResponse({"ok": True, **got})
        if action == "work_start":
            # design §4.5a **Inbox row: team start** for a team that runs on (§6 rule 8 *A member that
            # finished while its team runs on*, TD-466): **Start** replays the named members alone through
            # `work_start`, the person's own; a bound holding it back is refused in the row's words, which the
            # page puts after its own *not starting:*
            team = str(body.get("team") or "").strip()
            if not team:
                raise HTTPException(400, "work_start names the team")
            got = await call("work_start", team=team)
            if got.get("held"):
                raise HTTPException(409, work_held(got["held"], datetime.now(UTC)))
            if not got.get("started"):
                raise HTTPException(409, f"{team}: no work is waiting for its members")
            return JSONResponse({"ok": True, **got})
        if action == "clear_work":
            # design §4.5a **Inbox row: team start** (§6 rule 8, TD-227): **Dismiss** — `clear_work`,
            # the person's own: the ids go to the members' `lane_seen` and the mark is removed
            team = str(body.get("team") or "").strip()
            if not team:
                raise HTTPException(400, "clear_work names the team")
            got = await call("clear_work", team=team)
            return JSONResponse({"ok": True, **got})
        if action == "clear_mark":
            # design §4.5a **Inbox row: cadence check failed** and **merged without its read** (§6
            # rules 10 and 11, TD-258): **Dismiss** — `clear_mark`, the person's own, on the
            # member's record: `cadence` with the PR whose row it is, `held` for its crossings
            sid, kind = str(body.get("sid") or "").strip(), str(body.get("kind") or "").strip()
            pr = body.get("pr")
            if not sid or kind not in ("cadence", "held"):
                raise HTTPException(400, "clear_mark names the session and the mark: cadence or held")
            if kind == "cadence" and (isinstance(pr, bool) or not isinstance(pr, int)):
                raise HTTPException(400, "clear_mark cadence names the PR")
            got = await call("clear_mark", id=sid, kind=kind, pr=pr if kind == "cadence" else None)
            return JSONResponse({"ok": True, **got})
        if action == "suspend":
            # design §4.8a *An alarm's answers* (TD-077 a2): **Suspend** — a person's own act, and
            # refused to every session by the agent for the reason `identity_ack` is, turned around:
            # a session that could suspend could stop its rival. Caller-less, like every control on
            # this page; `why` is left to the agent, which composes it from the alarm's own words.
            who = str(body.get("id") or "").strip()
            if not who:
                raise HTTPException(400, "suspend names the session to suspend")
            got = await call("suspend", id=who)
            return JSONResponse({"ok": True, **got})
        if action == "identity_log":
            # design §4.5a **Inbox row: identity alarm** (§4.8a *An alarm's answers*, TD-077 b):
            # **Log TD** hands the record's alarms to the session that answers for it, as mail from
            # the person that owes an outcome, and clears the list. The agent picks the controller
            # and composes the words; the page names nobody. A controller that went between the
            # draw and the press is refused by the agent in words, which is the toast.
            who = str(body.get("id") or "").strip()
            if not who:
                raise HTTPException(400, "Log TD names the session whose alarms it hands on")
            got = await call("identity_log", id=who)
            return JSONResponse({"ok": True, **got})
        if action == "identity_ack":
            # design §4.5a **Inbox row: identity alarm** (§4.8a, TD-077 step 2): a person has seen
            # the alarms and decided what they were, so the list is cleared and the row leaves.
            # Caller-less like every other control here — the agent refuses it to every session,
            # and the log keeps every alarm, so acknowledging loses nothing.
            got = await call("identity_ack", id=str(body.get("id") or "").strip() or None)
            return JSONResponse({"ok": True, **got})
        if action == "reply":
            ref = str(body.get("reply_to") or "").strip()
            if not ref:
                raise HTTPException(400, "a reply names the entry it answers")
            # design §4.5a **Inbox row: suggested answers** (§4.10, TD-070): a press sends **the
            # index**, never the label. The text is looked up here, from the entry the home holds,
            # so a tampered DOM cannot make the person "say" something else under a given index —
            # and the RPC re-checks that the two agree, because this route is not the only caller.
            answer = body.get("answer")
            text = str(body.get("text") or "")
            if answer is not None:
                if isinstance(answer, bool) or not isinstance(answer, int):
                    raise HTTPException(400, "a suggested answer is picked by its index")
                held = next((e for e in (await call("inbox"))["entries"] if e.get("id") == ref), None)
                # the labels alone (§4.10 *The answers' split*, TD-913): what the home matches the index by
                offered = suggested_answers({"answers": (held or {}).get("answers")})
                if not 0 <= answer < len(offered):
                    raise HTTPException(400, "that is not one of the suggested answers")
                text = offered[answer]
            got = await call("msg", text=text, kind="reply", reply_to=ref, answer=answer)
            if "entry" not in got:
                # an orphaned question's answer (§4.10, TD-216): no reply entry — it went on the board
                # and to the holders, and `note` is the toast's sentence, the standing as a result
                return JSONResponse({"ok": True, **got})
            return JSONResponse({"ok": True, "id": got["entry"]["id"], "delivered": got["delivered"]})
        if action == "unmail":
            ref = str(body.get("msg") or "").strip()
            if not ref:
                raise HTTPException(400, "delete needs the entry's id")
            got = await call("inbox_delete", msg=ref)
            # design §4.10 *Deleting is declining*: on an open `ask` or `steer` the entry is not
            # stripped — it closes as `declined`, the asker is told, and it stays for retention.
            return JSONResponse({"ok": True, "unread": got["unread"], "declined": bool(got.get("declined"))})
        raise HTTPException(404, f"no action {action}")


def _stream_routes(app: FastAPI, h: SimpleNamespace) -> None:
    """The two websockets: the events stream and the terminal."""
    call, render_card, seats_of, heads = h.call, h.render_card, h.seats_of, h.heads
    repo_facts = h.repo_facts

    # -- live state ------------------------------------------------------------------------------

    # -- the events stream: one subscriber, fanned out (§4.4 *Per-session views*, TD-617) ----------

    async def fan_seed() -> SimpleNamespace:
        # A delta carries one record, but membership is read across records (design §4.8): a card's
        # *under* chip names its controllers, which live on other records. So the run keeps the
        # fleet it has already been told about — seeded once, then updated by the very deltas it is
        # rendering — rather than re-listing per event.
        known: dict[str, dict[str, Any]] = {}
        with contextlib.suppress(Exception):
            known = {o["id"]: o for o in await call("list")}
        # the repo facts and the doing log (TD-176): seeded once, then kept by their own events, so
        # a session delta redraws the summaries without asking the agent again; read without what the
        # pages it feeds omit, as its `repos` events are sent (TD-754)
        token = _REPOS_MEMO.set({"omit": REPOS_OMIT_PAGE})
        try:
            repos, doing = await repo_facts()
        finally:
            _REPOS_MEMO.reset(token)
        acct_of: dict[str, str] = {}  # profile → the account chip it is drawn on (TD-122)
        with contextlib.suppress(Exception):
            for name, acc in usage_accounts(await call("usage")).items():
                for p in acc["profiles"]:
                    acct_of[p["name"]] = name
        return SimpleNamespace(known=known, repos=repos, doing=doing, acct_of=acct_of)

    async def fan_regroup(st: SimpleNamespace) -> dict[str, Any]:
        return await heads(st.known, st.repos, st.doing)

    async def card_delta(s: dict[str, Any], st: SimpleNamespace) -> dict[str, Any]:
        """One record's delta as every stream takes it — its view, compact form and rank — computed
        once however many pages are connected (TD-617); the full streams add its card."""
        v = view(
            s,
            list(st.known.values()),
            icons=await role_icons([s]),
            seats=await seats_of([s]),
            repos=st.repos,
            waits=await h.person_waits(),
        )
        team_def = (await h.defs()).teams.get(str(v.get("team") or ""))  # its repo is the definition's (TD-725)
        compact_in(v, st.known.values(), st.repos, team_def.repo if team_def else "")
        # the view's rank, the card's: waiting and own work move it; the unseen mark sorts within it (TD-1228)
        return {"event": "session", "id": s["id"], "state": s["state"], "rank": v["rank"], "session": v}

    async def fan_kin(run: Any, s: dict[str, Any], was: dict[str, Any]) -> None:
        """Focus's members and its *under* chip are read across records (§4.4 *Per-session views*,
        TD-617): a Focus page is sent its own record's delta again when the record that moved, or
        went, is one of its controllers or members, from the fleet the run keeps — so the page reads
        no `/api/sessions` on a peer's delta. `was` is the record before this delta, so a member
        just released still redraws the list it left."""
        st = run.state
        for f in sorted({x.focus for x in run.light(other=s["id"]) if x.focus}):
            mine = st.known.get(f)
            if mine and (
                s["id"] in (mine.get("controllers") or [])
                or f in (s.get("controllers") or [])
                or f in (was.get("controllers") or [])
            ):
                run.to_all(run.light(focus=f), await card_delta(mine, st))

    async def fan_step(run: Any, ev: dict[str, Any]) -> None:
        st = run.state
        known, repos, doing, acct_of = st.known, st.repos, st.doing, st.acct_of
        if ev.get("event") == "session":
            s = ev["session"]
            was = known.get(s["id"]) or {}
            known[s["id"]] = s
            reshaped = not was or any(s.get(k) != was.get(k) for k in SHAPE_KEYS)
            stirred = reshaped or any(s.get(k) != was.get(k) for k in LIGHT_KEYS)
            moved = s.get("run_until") != was.get("run_until")
            if s.get("team") and moved and s.get("run_until") != uiconf.team_until(str(s["team"])):
                # a team's stop time stamps its members while the Save that moved it is still in
                # flight: read the settings again, or the compact line compares the new stamp with
                # the old time and says it differs (TD-337)
                with contextlib.suppress(Exception):
                    uiconf.set_read(await call("settings"))
            # a light stream (the Focus and Inbox pages) hears that another record moved, not what it
            # now looks like: they re-read what they draw (TD-572)
            if stirred:
                run.to_all(run.light(other=s["id"]), {"event": "session", "id": s["id"], "state": s["state"]})
            try:
                focused = run.light(focus=s["id"])
                if not focused and not run.full:
                    return
                delta = await card_delta(s, st)
                run.to_all(focused, delta)
                # `groups` ride on a delta that can move them (design §4.5a **team groups**): a badge or a
                # `controllers` change on one record can move a card, change a lead, or turn grouping on
                # or off for the whole page, and only the server sees the fleet. Any other delta marks
                # them for the flush. A reshaping delta carries them even when a flush already sent this
                # reading: a new card is placed by its own delta's groups.
                if run.full:
                    delta["html"] = render_card(delta["session"])
                    await run.to_full(delta, always=reshaped)
            finally:
                # after the record's own fan-out, so a kin view that fails to draw costs only itself
                if stirred:
                    await fan_kin(run, s, was)
        elif ev.get("event") in ("repos", "doing"):
            # A checkout's repo facts changed (design §4.4 *Repo facts*, TD-176), or a team member said
            # what it is doing (§4.8 *the doing log*): kept here, passed through as the agent sent it
            # (`repo: null` for a checkout the registry dropped), and the groups marked for the flush,
            # so the team cards' summaries redraw (TD-176 slice 3).
            if ev["event"] == "repos":
                root = str(ev.get("root"))
                marks: dict[str, str] | None = None
                if ev.get("repo") is None:
                    repos.pop(root, None)
                else:
                    repos[root] = ev["repo"]
                    # the repo's PR marks, once for every page (§4.4 *Per-session views*, TD-617): a
                    # card looks its PRs up here, no session view carries them
                    marks = repo_pr_marks(root, ev["repo"])
                    ev = {**ev, "pr_marks": marks}
                run.to_all(run.full, ev)
                # a light stream draws a repo's PR marks and nothing else of its facts, which run to
                # most of a megabyte a push: the root and the marks alone (`pr_marks: null` for a
                # dropped repo) — still on every push, which the Inbox re-reads its boards on (TD-670)
                run.to_all(run.light(), {"event": "repos", "root": root, "pr_marks": marks})
            else:
                if isinstance(ev.get("entry"), dict):
                    # the host agent's keep rule (§4.8 *the doing log*, TD-702), by this process's clock
                    team = str(ev.get("team"))
                    doing[team] = doing_kept([*doing.get(team, []), ev["entry"]], datetime.now(UTC))
                run.to_all(run.live, ev)
            if run.full:
                run.dirty.set()
        elif ev.get("event") == "queue":
            # the Queue's reading moved (§4.4 *Each reading has one owner*, TD-769): a page drawing cards
            # re-reads them (the Repo page, TD-770); the reading itself stays at the home, a page asks
            run.to_all(run.live, {"event": "queue"})
        elif ev.get("event") == "gone":
            # only a `gone` names a session; a `usage` event carries a profile, and popping on it
            # would one day evict a live session by coincidence
            went = str(ev.get("id") or "")
            gone_rec = known.pop(went, None)
            run.to_all(run.light(), ev)
            try:
                if not run.full:
                    return
                await run.to_full(ev, always=True)
                # A card's *under* chip names another record, so the session that went is not the only
                # card now out of date: every card listing it as a controller has to be redrawn, or it
                # keeps naming and linking to a session that is gone until the page is reloaded (review
                # 2026-09-13).
                for other in list(known.values()):
                    if went in (other.get("controllers") or []):
                        od = await card_delta(other, st)
                        od["html"] = render_card(od["session"])
                        run.to_all(run.full, od)
            finally:
                if gone_rec:
                    await fan_kin(run, gone_rec, gone_rec)
        elif ev.get("event") == "usage":
            # The agent pushes a profile's reading; the page draws **one chip per account** (§4.5a
            # **usage**, TD-122), with the lowest line among the account's profiles and each profile's
            # sessions on hover — so the account is regrouped here from the whole reading, the gate's
            # lines and the fleet this run already keeps. A profile that went (`usage: null`) redraws
            # the account it was on, or takes its chip off.
            prof = str(ev.get("profile"))
            was_on = acct_of.pop(prof, prof)
            readings: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                readings = await call("usage")
            with contextlib.suppress(Exception):
                readings = with_lines(readings, await call("gate"))
            grouped = usage_accounts(readings, list(known.values()))
            for name, acc in grouped.items():
                for p in acc["profiles"]:
                    acct_of[p["name"]] = name
            now_on = acct_of.get(prof)
            for name in {was_on, now_on} - {None}:
                run.to_all(run.live, {"event": "usage", "account": name, "usage": grouped.get(name)})

    # the run keeps the reading the Org, the Repo page and a card draw, so it is sent what they read (TD-754)
    fan = Fanout(lambda: LocalClient(), fan_seed, fan_step, fan_regroup, omit=REPOS_OMIT_PAGE)
    # §4.5 *A reconnect reloads once, never in a loop* (TD-694): a page opening `/events` in a loop is
    # one warning line, and the handler's own failure is logged, at most once a minute
    opens, events_failed = OpenRate(), Every(60.0)

    @app.websocket("/events")
    async def events(ws: WebSocket):
        await ws.accept()
        # `page` (the `v=` of the `app.js` the page loaded) and `at` (its path) are the client's word:
        # cut, keyed on as cut, and logged with `%r`
        page, at = (ws.query_params.get(k, "")[:SAID_MAX] for k in ("page", "at"))
        addr = ws.client.host if ws.client else ""
        if n := opens.opened(addr, at, time.monotonic()):
            serves = static_url("app.js").partition("?v=")[2]
            what = "events: %s opened /events %d times in 60s from %r (page %r, this UI serves %s)"
            log.warning(what, addr, n, at, page, serves)
        # `?light=1` is the Focus and Inbox pages' stream: no card markup and no groups, another
        # record's delta only when it can move something (`SHAPE_KEYS`), and `focus`'s own in full —
        # one Focus tab was otherwise as costly to the UI as a Sessions page (TD-572). Every stream is fed
        # by the one subscriber (`fan`), which computes each delta once (TD-617).
        st = Stream(
            ws, light=ws.query_params.get("light") == "1", focus=ws.query_params.get("focus") or "", page=page, at=at
        )

        async def gone() -> None:
            # The page sends one thing on this socket — whether its document is visible, for the
            # counts keeper's Looking (§4.10, TD-616) — so anything else that arrives is its
            # disconnect. Without this watch the handler noticed a closed tab only when the next
            # event's send failed — and uvicorn's shutdown waits on the handler, which is the UI's
            # 40 s stop (TD-058).
            while (got := await ws.receive()).get("type") != "websocket.disconnect":
                with contextlib.suppress(ValueError, TypeError, AttributeError):
                    said = json.loads(got.get("text") or "")
                    if isinstance(said, dict) and isinstance(said.get("visible"), bool):
                        h.counts.visible(ws, said["visible"])

        try:
            tasks = {asyncio.ensure_future(st.pump()), asyncio.ensure_future(gone())}
            try:
                # every page's stream carries the Inbox's counts, light or full (§4.4, TD-616); inside
                # the `try`, so a stream cancelled mid-join still leaves the keeper
                await h.counts.join(ws)
                fan.join(st)
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                fan.leave(st)
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await h.counts.leave(ws)
            for t in done:
                t.result()
        except (WebSocketDisconnect, AgentUnavailable, ConnectionError):
            pass
        except Exception:  # noqa: BLE001
            if events_failed.due(time.monotonic()):
                log.exception("the events handler failed")
            with contextlib.suppress(Exception):
                await ws.send_text(json.dumps({"event": "error", "text": FAILED}))
        finally:
            with contextlib.suppress(Exception):
                await ws.close()

    # -- terminal --------------------------------------------------------------------------------

    @app.websocket("/term/{sid}")
    async def term(ws: WebSocket, sid: str):
        # Size comes from the query, leniently: a bad or missing value falls back to a default
        # instead of a 403 before accept, which a browser can only report as an opaque 1006
        # (first-use finding 2026-09-06). The client re-sends its real size on open anyway.
        cols = _int_param(ws.query_params.get("cols"), 120, 10, 500)
        rows = _int_param(ws.query_params.get("rows"), 32, 2, 200)
        await ws.accept()
        try:
            s = await call("get", id=sid)
        except HTTPException as e:
            await ws.send_bytes(f"\r\n[shiftlead] {e.detail}\r\n".encode())
            await ws.close(code=4404)  # final: the client must not retry
            return
        sid = sid.removesuffix(f"@{host_name()}")  # a self-addressed id is this host's tmux session
        sock = os.environ.get("SHIFTLEAD_TMUX_SOCKET")
        inside: list[str] = []  # the `docker exec` prefix every tmux command takes for a container node's session
        # OSC 8 targets reach xterm.js only when the client says it takes them (§4.6, TD-847)
        argv = attach_argv(sid, socket_name=sock, features=("hyperlinks",))
        if s.get("host") and s["host"] != host_name():
            # Another host's session (design §4.4a "Reach"): a container node on this machine is
            # reached by `docker exec` into it, from what the home derived when it dialed in; a
            # machine node's pane has nothing here that reaches it yet.
            reach = (s.get("host_link") or {}).get("reach") or {}
            if not reach.get("container"):
                await ws.send_bytes(
                    f"\r\n[shiftlead] runs on {s['host']}: no terminal reaches it from here "
                    "(a container node's reach comes with its link; a machine node's waits for the terminal "
                    "over the link, TD-057 *Later*).\r\n".encode()
                )
                await ws.close(code=4404)
                return
            sid, sock = naming.split_address(sid)[0], None  # the bare id, on the user's default server inside
            argv = attach_argv_in(reach["container"], reach.get("user") or "root", sid, features=("hyperlinks",))
            inside = argv[: argv.index("tmux")]
        if s.get("state") == "closed" or not s.get("pane", True):  # no pane to attach (TD-023)
            await ws.send_bytes(b"\r\n[shiftlead] this session's pane is gone (see the banner).\r\n")
            await ws.close(code=4404)
            return
        try:
            pty = PtySession(argv, cols=cols, rows=rows)
        except Exception as e:  # noqa: BLE001 — no silent failure path (design §4.5)
            await ws.send_bytes(f"\r\n[shiftlead] could not attach a terminal: {type(e).__name__}: {e}\r\n".encode())
            await ws.close()
            return

        # design §4.6 *A read-only attach* (TD-096): the mode is read once, here, and a read-only attach
        # tells the page so in its first frame — a text frame, which is the page's to read and not
        # pane output, so it neither counts as a painted screen nor resets the page's backoff. An
        # attach that sends none takes keys. A mode change re-attaches.
        read_only = bool(s.get("unattended"))
        if read_only:
            await ws.send_text(json.dumps({"read_only": True}))
        produced = False

        async def send(data: bytes) -> None:
            nonlocal produced
            produced = True
            await ws.send_bytes(data)

        async def recv() -> Any:
            msg = await ws.receive()  # a disconnect arrives as a message, never as an exception here
            if msg.get("type") == "websocket.disconnect":
                return None
            if msg.get("bytes") is not None:
                return msg["bytes"]
            text = msg.get("text") or ""
            if text.startswith("{"):
                with contextlib.suppress(ValueError):
                    return json.loads(text)
            return text

        reapers: set[asyncio.Future[int]] = set()

        async def run_tmux(argv: list[str]) -> None:
            # One tmux command against the session, through the same prefix and socket, awaited to its
            # end so the next frame's command never overtakes it (design §4.6 *In order*, TD-667);
            # bounded, so a stuck container's `docker exec` holds the key pump no longer than a leave's
            # bound, then is killed and reaped in the background
            devnull = asyncio.subprocess.DEVNULL
            proc = await asyncio.create_subprocess_exec(
                *[a for a in inside if a != "-it"], *argv, stdout=devnull, stderr=devnull
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=LEAVE_WITHIN)
            finally:
                if proc.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    reapers.add(asyncio.ensure_future(proc.wait()))

        async def scroll(direction: str, lines: int | None = None) -> None:
            # A tmux command against the session, not keys into the pane: there is no escape
            # sequence that enters copy mode (TD-022). The wheel's `lines` scroll lines, their absence
            # a page (TD-174). A bad direction or count is the client's bug; ignore.
            try:
                argv = scroll_argv(sid, direction, lines, socket_name=sock)
            except ValueError:
                return
            with contextlib.suppress(TimeoutError):  # a slow scroll is no reason to end the attach
                await run_tmux(argv)

        async def leave() -> None:
            # Back to the live screen before a typed key (design §4.6, TD-667): the pump bounds it
            # and logs a failure
            await run_tmux(leave_argv(sid, socket_name=sock))

        async def read_tmux(argv: list[str], within: float) -> str | None:
            # A tmux command's output, through the same prefix and socket the scroll command takes; a
            # read slower than `within`, or failed, is no reading
            argv = [*[a for a in inside if a != "-it"], *argv]
            pipe, devnull = asyncio.subprocess.PIPE, asyncio.subprocess.DEVNULL
            proc = await asyncio.create_subprocess_exec(*argv, stdout=pipe, stderr=devnull)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=within)
            except TimeoutError:
                return None
            finally:
                # timed out, or cancelled when the pump ended: a hung read (a stuck container's `docker
                # exec`) is killed and reaped in the background, never left running
                if proc.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    reapers.add(asyncio.ensure_future(proc.wait()))
            return out.decode(errors="replace") if proc.returncode == 0 else None

        async def read_clients() -> str | None:
            # tmux's clients and window for the terminal mark (design §4.6, TD-480)
            return await read_tmux(clients_argv(sid, socket_name=sock), 3)

        async def jump(openings: list[dict]) -> bool:
            # A press on a Prompts row (design §4.6 *A jump to a prompt*, TD-975): the read bounded at
            # `JUMP_WITHIN`, the walk and the landing, then the page's text frame — its own word, as
            # `clients` is, never pane output
            read = functools.partial(read_tmux, within=JUMP_WITHIN)
            landed = await run_jump(openings, read, run_tmux, sid, socket_name=sock)
            with contextlib.suppress(Exception):
                await ws.send_text(json.dumps({"jumped": landed}))
            return landed

        watcher = asyncio.ensure_future(watch_clients(read_clients, ws.send_text))
        try:
            await pump(pty, send, recv, scroll, leave=leave, jump=jump, read_only=read_only)
        finally:
            watcher.cancel()
            for f in reapers:
                f.cancel()
            # `pump` has already closed the pty, so the child is reaped and its status is final:
            # a `tmux attach` that exited on its own carries its code, and one the teardown
            # signalled carries None, which is the retryable case (TD-029).
            status = pty.exit_status()
            with contextlib.suppress(Exception):
                if status not in (0, None) or not produced:
                    # A dead attach is final (TD-029): `tmux attach` exits non-zero when its session
                    # is gone, and an attach that never painted a screen attached to nothing. Either
                    # way the record is behind — retrying twice a second would print tmux's "can't
                    # find session" forever, which is what Paul saw on 2026-09-10.
                    await ws.send_bytes(
                        b"\r\n[shiftlead] this session's pane is gone (the attach ended immediately).\r\n"
                    )
                    await ws.close(code=4404)
                else:
                    await ws.close()


app = create_app()


def main(argv: list[str] | None = None) -> int:
    import argparse

    from sessionorc import hosts
    from shiftlead.service import DEFAULT_BIND, DEFAULT_PORT, DEFAULT_ROUTE_PORT
    from shiftlead.ui import listener

    ap = argparse.ArgumentParser(prog="shiftlead-ui")
    ap.add_argument("--bind", default=DEFAULT_BIND, help="the plain port's address (design §4.5: never the LAN)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="the plain port")
    ap.add_argument(
        "--route-port",
        type=int,
        default=DEFAULT_ROUTE_PORT,
        help="the route port a proxy is pointed at, always 127.0.0.1; 0 runs none (design §4.5b)",
    )
    ap.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="NAME",
        help="a name the plain port also serves, beside the loopback names (repeatable; design §4.5b)",
    )
    args = ap.parse_args(argv)
    # lifespan="off" (in `listener.serve`): the app has no startup/shutdown handlers, and with lifespan on,
    # Ctrl+C makes uvicorn log a CancelledError traceback from starlette's lifespan task (seen 2026-09-06).
    asyncio.run(
        listener.serve(
            app,
            bind=args.bind,
            port=args.port,
            route_port=args.route_port,
            allow_hosts=args.allow_host,
            is_node=bool(args.route_port) and hosts.is_node(),
        )
    )
    return 0


async def _wait_agent() -> bool:
    for _ in range(20):
        if paths.socket_path().exists():
            return True
        await asyncio.sleep(0.25)
    return False
