"""A session started for one stage of a format-3 flow, and what it is told (design §4.9c *A stage is one kind of work,
one model, one fresh session*, *What a stage's session is told*; §4.8 *Under a format-3 flow*; TD-2049).

Its opening prompt is, in order: the mechanics, how the stage is ended, the repo's rules, and the stage's brief with
its `also`. Nothing calls `start` until the tick's offer (TD-2051), and `team_started` is false until TD-2065 fills it,
so no such session starts before the cut-over. The stage's model is carried on `StageLaunch`; launching on it, on a
login, is TD-2068's.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sessionorc.client import AgentError, AgentUnavailable
from shiftlead import flow3, repoconfig, teams
from shiftlead import org as orgmod

ROLE_OF = {"design": "designer", "build": "grinder", "review": "reviewer"}  # `grinder` until the removal build (§4.8)
STAGE_TEMPLATE = Path(__file__).resolve().parent / "briefs" / "stage.md"
FACTS = {
    "work-pushed": "the entry's branch is pushed and its pull request is open; its precheck is green unless the next "
    "stage is another build; where a build's next is `merge` or a review, the pull request archives the entry",
    "ship": "the pull request's head is the commit you read",
    "changes-wanted": "a reason is given, which is the review",
    "no-design-needed": "a reason is given",
    "not-needed": "a reason is given",
    "design-needs-changing": "a reason is given",
    flow3.OTHER: "a reason is given; the last choice, when no other outcome fits",
}


@dataclass(frozen=True)
class Work:
    """The entry a stage's session is started for, with the branch and pull request its record already carries."""

    entry: str
    branch: str | None = None
    pr: int | None = None


@dataclass(frozen=True)
class StageLaunch:
    """A stage's session as it would be created, with the model its stage names (TD-2068 launches on it)."""

    launch: teams.Launch
    model: str

    def create_params(self, controllers: list[str]) -> dict[str, Any]:
        """The `create` RPC's arguments: a team session's, supervised, so the tick's nudge and context bound reach it
        and the home never reads it as one the person started (`by_person`)."""
        return self.launch.create_params(controllers)


def team_started(_org: orgmod.Org, _team: orgmod.TeamDef) -> bool:
    """Whether the team is started: false until TD-2065 writes the started mark, so nothing starts before it."""
    return False


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
    lines.append(
        '\nEnd the stage with one command, run in your worktree: **`ao stage end <outcome> [--reason "…"]`**. Until '
        "you run it you are working, and a red check or a failing test is no outcome. The home checks each outcome's "
        "fact and refuses one the facts contradict, saying which, and you carry on. Every outcome but `work-pushed` "
        "and `ship` needs `--reason`. The outcomes, and what each is checked on:"
    )
    lines += [f"- `{o}`: {FACTS[o]}" for o in (*flow3.OUTCOMES[kind], flow3.OTHER)]
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
) -> StageLaunch:
    """The session for `key` on `work`, nothing created: the role of the stage's kind, its lane the one entry."""
    stage = stage_of(doc, key)
    kind, name = stage["does"], f"{key}-{work.entry.lower()}"
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
    return StageLaunch(x, str(stage["model"]))


def start(call: Any, org: orgmod.Org, team: orgmod.TeamDef, got: StageLaunch) -> dict[str, Any] | None:
    """Create the stage's session, or None: the team is not started, or a live session holds the name."""
    if not team_started(org, team):
        return None
    x = got.launch
    on = {"host": x.host} if x.host else {}
    if call("name_check", dir=str(x.dir), name=x.name, repo=str(x.dir), **on).get("verdict") in ("live", "suspended"):
        return None
    return call("create", **got.create_params([]))


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
