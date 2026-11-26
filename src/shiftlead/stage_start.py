"""A session started for one stage of a format-3 flow, and what it is told (design §4.9c *A stage is one kind of work,
one model, one fresh session*, *What a stage's session is told*; §4.8 *Under a format-3 flow*; TD-2049).

Its opening prompt is, in order: the mechanics, how the stage is ended, the repo's rules, and the stage's brief with
its `also`. `start` creates one only while its team is started, the home's started mark read just before the
create (TD-2065), and no team is marked before the cut-over. On the home's own host a stage's or an audit's session
is launched on the first usable login of the team's list that offers its model (§4.9e *The launch on a login*,
TD-2068), as the team's `team_show` reading names it; a team on a node and a job's session are launched as before.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sessionorc import logins, teamstore
from sessionorc.client import AgentError, AgentUnavailable
from shiftlead import flow3, repoconfig, teams
from shiftlead import org as orgmod

ROLE_OF = {"design": "designer", "build": "grinder", "review": "reviewer"}  # `grinder` until the removal build (§4.8)
STAGE_TEMPLATE = Path(__file__).resolve().parent / "briefs" / "stage.md"
FACTS = {
    "work-pushed": "the entry's branch is pushed and its pull request is open; its precheck is green unless the next "
    "stage is another build; where a build's next is `merge` or a review, the pull request archives the entry",
    "ship": "the pull request's head is the commit you read; give `--findings <n>`, every finding you raised, "
    "0 where it is omitted",
    "changes-wanted": "a reason is given, which is the review, with `--findings <n> --blocking <m>`: every finding "
    "you raised, and of those the ones you would not ship with, at least 1",
    "no-design-needed": "a reason is given",
    "not-needed": "a reason is given",
    "design-needs-changing": "a reason is given",
    flow3.OTHER: "a reason is given; the last choice, when no other outcome fits",
}
CHECK_WAITS = "check-waits"  # a live check's fixed move to merge, written by no flow (§4.9c *A live check …*)
CHECK_WAITS_FACT = (
    "a reason is given; the entry is a live check; its branch is pushed, its pull request open and its precheck green; "
    "the pull request changes only the ledger and the board and does not archive the entry; no review stage has given "
    "it a verdict; and at its head the entry's `Blocked by` adds at least one blocker that holds: an open entry's id, "
    "an `until` after today, an `event (<name>)` whose section is in the entry, or a `decision (<person>)` with its "
    "open `decide` item on the board"
)
LIVE_CHECK = (
    "\n**This entry is a live check** (`Kind: live-check`): this replaces any building the brief below asks for. You "
    "write no code. You read the live copy and never press it: `ao status -v`, a record's fields, `ao promote status`, "
    "a transcript, a headless GET of a page; a check that needs a press is made on a scratch home (design §4.9b *What "
    "the grinder does*). A build you find not live takes a fresh `event` gate by §4.9b's naming rule (*A live check "
    "waits on a gate*), and the check waits on it. A new entry takes its id from `ao td reserve` and is filed with "
    "`ledger.py new --id TD-n`; a note, a gate and an archive are `ledger.py note`, `set` and `archive`; the board's "
    "`decide` item is `board_edit.py add`; a look is `ao msg` (§4.10 *A look*). The check ends one of four ways, each "
    "in a pull request of ledger and board files alone:\n"
    "- **It holds**: what you read is written on the entry and the entry is archived; end with `work-pushed`.\n"
    "- **It does not**: a new entry says what is wrong and the check is `Blocked by` it; end with `check-waits`.\n"
    "- **It waits for an event nobody can cause**, its build not being live among them: what you read is noted and the "
    "entry gains its `event` or `until` gate; end with `check-waits`.\n"
    "- **It is the person's to judge**: send the look first; the entry gains `decision (<person>)`, its Ask naming the "
    "look's mail id, with the board's `decide` item; end with `check-waits`.\n"
    "`check-waits` goes to merge past any review stage, so before it run the cadence's fact-check of the pull request "
    "(a fresh subagent on the cadence's review model) and post its `cadence-review:` comment. A pull request a review "
    "stage has given a verdict is never merged past it: end that one with `other`. A later check of this entry starts "
    "a new branch, its name holding the entry's id and not already on origin, and reads the entry's Log first."
)


@dataclass(frozen=True)
class Work:
    """The entry a stage's session is started for, with the branch and pull request its record already carries, and
    the last move that brought it to this stage (`came`: a review's changes, a refused merge's failing row) and the
    person's own words where their answer sent it here (`answer`)."""

    entry: str
    branch: str | None = None
    pr: int | None = None
    came: str | None = None
    answer: str | None = None
    live_check: bool = False  # the entry's `Kind:` is `live-check`, as the offer read it from the ledger


@dataclass(frozen=True)
class StageLaunch:
    """A stage's session as it would be created, with the model its stage names. `pick` says where the team's
    `team_show` reading names the login it starts on: `("stages", <stage key>)` or `("audits", <audit key>)`; None
    for a launch that reads no team's list (a job's, TD-2068's later slice)."""

    launch: teams.Launch
    model: str
    pick: tuple[str, str] | None = None

    def create_params(self, controllers: list[str]) -> dict[str, Any]:
        """The `create` RPC's arguments: a team session's, supervised, so the tick's nudge and context bound reach it
        and the home never reads it as one the person started (`by_person`); `stage`, so its create reads its tool's
        version (§4.3, TD-2158)."""
        return {**self.launch.create_params(controllers), "stage": True}


def team_started(marks: Mapping[str, Any] | None, team: str) -> bool:
    """Whether the team is started, from the home's team marks (the `host` record's `teams`, or the `host` read's
    `team_marks`): its started mark and nothing else (§4.9d *Started is a mark the home keeps*)."""
    return teamstore.started(marks, team)


def stage_of(doc: dict[str, Any], key: str) -> dict[str, Any]:
    """The stage of `doc` whose key is `key`."""
    for st in doc.get("stages") or []:
        if isinstance(st, dict) and flow3.key_of(st.get("name")) == key:
            return st
    raise teams.TeamError(f"this flow has no stage {key!r}")


def _body(text: str) -> str:
    """A brief's text without its front matter."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                return "\n".join(lines[i + 1 :]).strip()
    return text.strip()


def brief_for(stage: dict[str, Any], place: str, flow_dir: Path | None, read: repoconfig.Reader | None = None) -> str:
    """The stage's brief, its `also` appended (§4.9c): no `brief:` is its kind's standard one; a name is a standard
    brief, one in the flow's own directory, or, for a flow that is not a repo's, one of the org's."""
    name = stage.get("brief") or stage["does"]
    if name in flow3.STANDARD:
        text = (flow3.STANDARD_DIR / f"{name}.md").read_text(encoding="utf-8")
    else:
        reader = read or flow3._read
        try:
            text = reader(flow_dir / "briefs" / f"{name}.md") if flow_dir is not None and place != "package" else None
        except (OSError, ValueError) as e:
            raise teams.TeamError(f"{stage.get('name')}: brief {name!r} cannot be read ({e})") from None
        if text is None and place not in ("repo", "package"):
            text = flow3._read(flow3.org_briefs() / f"{name}.md")
        if text is None:
            raise teams.TeamError(f"{stage.get('name')}: brief {name!r} cannot be read")
    also = stage.get("also")
    return _body(text) + (f"\n\n{also.strip()}" if isinstance(also, str) and also.strip() else "")


def briefs(
    org: orgmod.Org,
    team: orgmod.TeamDef,
    doc: Mapping[str, Any],
    *,
    host: str,
    here: str,
    place: str = "package",
    flow_dir: Path | None = None,
    files: teams.Files | None = None,
) -> list[dict[str, str]]:
    """Each stage's brief as a session's start would read it now, in the stages' order, by the checkout and reader
    `launch` uses (§4.9c *The flow's content hash*). Raises what `launch` would: `TeamError`, or a read's error."""
    _, read = teams._checkout(org, team, team.repo, host, here, files, f"team {team.name}: the flow's briefs")
    return [
        {"stage": flow3.key_of(st.get("name")), "text": brief_for(st, place, flow_dir, read)}
        for st in doc.get("stages") or []
        if isinstance(st, dict)
    ]


def told(stage: dict[str, Any], key: str, work: Work, *, adds_review: bool) -> str:
    """How this stage is taken and ended: the `{flow}` of its session's prompt."""
    kind = stage["does"]
    lines = [f"You hold **{work.entry}** in the stage **{stage['name']}** (`{key}`, a {kind} stage)."]
    if work.branch or work.pr:
        where = " and ".join(
            x
            for x in (f"branch `{work.branch}`" if work.branch else "", f"pull request #{work.pr}" if work.pr else "")
            if x
        )
        lines.append(f"Its record already carries {where}: read what is there and work on that branch.")
    elif kind != "review":
        lines.append("It has no branch yet: branch off the default branch and open its one pull request.")
    if work.came:
        lines.append(f"It came to this stage by a move whose reason was: {work.came}")
    if work.answer:
        lines.append(f"The person's answer that sent it here, in their own words: {work.answer}")
    lines.append(
        '\nEnd the stage with one command, run in your worktree: **`ao stage end <outcome> [--reason "…"]`**. Until '
        "you run it you are working, and a red check or a failing test is no outcome. The home checks each outcome's "
        "fact and refuses one the facts contradict, saying which, and you carry on. Every outcome but `work-pushed` "
        "and `ship` needs `--reason`. The outcomes, and what each is checked on:"
    )
    if kind == "review":
        lines[-1] = lines[-1].replace('[--reason "…"]', '[--reason "…"] [--findings <n> [--blocking <m>]]')
    check = work.live_check and kind in flow3.WRITES
    lines += [f"- `{o}`: {FACTS[o]}" for o in (*flow3.OUTCOMES[kind], flow3.OTHER)]
    if check:
        lines.append(f"- `{CHECK_WAITS}`: {CHECK_WAITS_FACT}")
        lines.append(LIVE_CHECK)
    if adds_review:
        lines.append(
            "\n**Before `work-pushed`, run the cadence's independent review** of your work (a fresh subagent on the "
            "cadence's review model), fix what it finds, and post its `cadence-review:` comment on the pull request: "
            "no review stage reads this work on every route to merge."
        )
    return "\n".join(lines)


def launch(
    org: orgmod.Org,
    team: orgmod.TeamDef,
    doc: dict[str, Any],
    key: str,
    work: Work,
    *,
    host: str,
    here: str,
    place: str = "package",
    flow_dir: Path | None = None,
    files: teams.Files | None = None,
    name: str | None = None,
) -> StageLaunch:
    """The session for `key` on `work`, nothing created: the role of the stage's kind, its lane the one entry (or a
    job's work order, `name` then the session's name, `stage_job_start.review_launch`)."""
    stage = stage_of(doc, key)
    kind, name = stage["does"], name or f"{key}-{work.entry.lower()}"
    where = f"team {team.name}: {name}"
    checkout, read = teams._checkout(org, team, team.repo, host, here, files, where)
    try:
        cfg = repoconfig.load(checkout, read=read)
        cfg.venv = teams.node_venv(host, here)
        role = repoconfig.resolve_role(cfg, ROLE_OF[kind], org.roles)
    except (KeyError, ValueError, OSError) as e:
        raise teams.TeamError(f"{where}: {str(e).strip(chr(34))}") from None
    line = next((m for m in team.members if m.role == role.name), None)
    person, unlisted = teams._person(org, team.repo, role, here, where)
    under = repoconfig.UnderFlow(
        told(stage, key, work, adds_review=key in flow3.independent_review(doc)),
        brief=brief_for(stage, place, flow_dir, read),
    )
    try:
        prompt, made = role.compose(
            [work.entry],
            read=read,
            supplement=line.brief if line is not None and line.brief else None,
            flow=under,
            template_file=None if kind == "review" else STAGE_TEMPLATE,
            person=person,
        )
    except ValueError as e:
        raise teams.TeamError(f"{where}: {e}") from None
    profile = (line.profile if line is not None else None) or role.profile or ""
    adapter = teams.profiles.DEFAULT_ADAPTER
    if profile:
        try:
            adapter = teams.profiles.get(profile).adapter
        except (KeyError, ValueError) as e:
            raise teams.TeamError(f"{where}: {str(e).strip(chr(34))}") from None
        if adapter == teams.profiles.SHELL_ADAPTER:
            raise teams.TeamError(f"{where}: profile {profile!r} runs a shell, and a stage's session is an agent's")
    x = teams.Launch(
        name=name,
        role=role.name,
        home=team.repo,
        dir=checkout,
        team=team.name,
        project=org.project_of(team.repo),
        profile=profile,
        adapter=adapter,
        prompt=prompt,
        grants=list(role.grants),
        lane=[work.entry],
        ledger=cfg.ledger,
        host=host if host != here else "",
        context_bound=role.context_bound,
        prompt_from=made,
        unlisted=unlisted,
    )
    return StageLaunch(x, str(stage["model"]), ("stages", key))


def on_login(call: Any, team: str, got: StageLaunch) -> dict[str, Any] | None:
    """The `create` arguments that put the launch on its login (§4.9e *The launch on a login*): `{}` for a launch
    as before (a team on a node, whose host picks for itself; a launch with no `pick`; a team the home's reading does
    not show switched), else the login the team's reading picks with the model and the list, or None when nothing is
    to start: no login of the list usable (the usage gate holds it) or none offering the model (*cannot run*)."""
    if got.launch.host or got.pick is None:
        return {}
    shown = call("team_show", team=team, entries=False) or {}
    if not shown.get("switched"):
        return {}
    kind, key = got.pick
    rows = (shown.get("flow") or {}).get("stages") if kind == "stages" else shown.get("audits")
    row = next(
        (r for r in rows or () if (r.get("key") if kind == "stages" else flow3.key_of(r.get("name"))) == key), None
    )
    now = (row or {}).get("now") or {}
    if now.get("state") != "usable" or not now.get("login"):
        return None
    login = str(now["login"])
    return {
        "login": login,
        "adapter": logins.split(login)[0],
        "profile": "",
        "seat_model": got.model,
        "login_list": [str(r["login"]) for r in shown.get("logins") or () if r.get("login")],
    }


def start(call: Any, org: orgmod.Org, team: orgmod.TeamDef, got: StageLaunch) -> dict[str, Any] | None:
    """Create the stage's session, or None: the team is not started, a live session holds the name, or no login of
    the team's list can start it now (`on_login`). The started mark is read from the home just before the create, so
    a Wind down during the pass starts nothing after it."""
    if not team_started((call("host") or {}).get("team_marks"), team.name):
        return None
    x = got.launch
    on = {"host": x.host} if x.host else {}
    if call("name_check", dir=str(x.dir), name=x.name, repo=str(x.dir), **on).get("verdict") in ("live", "suspended"):
        return None
    if (login := on_login(call, team.name, got)) is None:
        return None
    return call("create", **{**got.create_params([]), **login})


def holder_of(got: StageLaunch, created: dict[str, Any]) -> str:
    """The created session as its record's holder: on a node, the home's `id@node` form (§4.4a)."""
    sid, host = str(created["id"]), got.launch.host
    return sid if not host or "@" in sid else f"{sid}@{host}"


def claim(call: Any, holder: str, tid: str) -> str | None:
    """Write the holder's claim on the entry (§4.9c act 5): None, or why it was refused."""
    try:
        call("progress", id=holder, ref=tid, status="claimed")
    except AgentError as e:
        return str(e)
    return None


def end(call: Any, holder: str, why: str = "its stage record no longer names it") -> None:
    """Close a session an act took its record from, as the tick closes one. A session of this host already gone is no
    failure. Anything else is, so the caller reports the session as left running: above all a node's `no session`,
    which the home answers from its copy of that node's records, and that copy can lag a session still running."""
    try:
        call("close", id=holder, closer={"by": "tick", "why": why})
    except AgentUnavailable:
        raise
    except AgentError as e:
        if "@" in holder or str(e) != f"no session {holder}":
            raise
