"""A session started for one job of a built-in seat, and what it is told (design §4.9d *How each one runs*, TD-2053).

A job's session is a stage's session in all but its work (`stage_start`): the same mechanics and the same `ao stage
end`, the repo's rules, and a brief — the seat's work order's words as they are today (`briefs/job/<seat>.md`). It is
started on the seat's model, given by the built-in set the repo uses (`builtinstore.seat`), in the build stage's role,
with the work order's reference as its one lane (`board:<8 hex>`, `pr:<n>`), and names no `controllers`. Its outcomes
are `work-pushed` and `other`. Launching on the set's login is TD-2068's, and `stage_start.start` starts nothing
before the team's started mark (TD-2065).

A job whose record stands at one of its flow's review stages is read by that stage's own fresh session
(`review_launch`, §4.9d *Its pull request is reviewed and merged by the team's flow*): a review stage's session as an
entry's would be (`stage_start.launch`: the reviewer role, the stage's model and brief), holding the job's work order
and named `<stage>-job-<key>`, so no entry's session takes its name. Its outcomes are the review stage's.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sessionorc import workorders
from shiftlead import flow3, repoconfig, teams
from shiftlead import org as orgmod
from shiftlead.stage_job import SEATS, key_of
from shiftlead.stage_start import ROLE_OF, StageLaunch, Work
from shiftlead.stage_start import launch as stage_launch

JOB_TEMPLATE = Path(__file__).resolve().parent / "briefs" / "job.md"
JOB_BRIEFS = Path(__file__).resolve().parent / "briefs" / "job"
SEAT_WORDS = {"board-answers": "board answers", "unheld-pull-requests": "pull requests nobody holds"}


def lane_of(record: Mapping[str, Any]) -> str:
    """The work order's reference a job's session holds: `board:<8 hex>` for a board answer, `pr:<n>` for a pull
    request nobody holds — the references the first shape's lanes take today (`workorders`)."""
    seat, obj = str(record.get("seat")), str(record.get("object"))
    key_of(seat, obj)  # refuses an object that is no seat's
    return f"{workorders.PREFIX}{obj}" if seat == "board-answers" else f"{workorders.PR_PREFIX}{int(obj)}"


def name_of(record: Mapping[str, Any]) -> str:
    """The session's name, which no stage's takes: `job-` and the record's key (`job-board-1a2b3c4d`, `job-pr-12`)."""
    return f"job-{key_of(str(record.get('seat')), str(record.get('object')))}"


def job_stage(doc: Mapping[str, Any]) -> str | None:
    """The key of the stage a job's record stands in after `work-pushed`: the one that takes `other` entries (§4.9d)."""
    for st in doc.get("stages") or []:
        if isinstance(st, Mapping) and st.get("takes") in ("other", "any"):
            return flow3.key_of(st.get("name"))
    return None


def brief_of(seat: str) -> str:
    """The seat's brief, the package's own."""
    if seat not in SEATS:
        raise ValueError(f"a job's seat is one of {SEATS}, not {seat!r}")
    return (JOB_BRIEFS / f"{seat}.md").read_text(encoding="utf-8").strip()


def told(record: Mapping[str, Any], *, team: str, adds_review: bool, came: str | None = None) -> str:
    """How the job is taken and ended: the `{flow}` of its session's prompt."""
    seat, lane = str(record["seat"]), lane_of(record)
    lines = [f"You hold the job **{lane}** of the built-in seat **{SEAT_WORDS[seat]}**, for team {team}."]
    branch, pr = record.get("branch"), record.get("pr")
    if seat == "unheld-pull-requests":
        lines.append(f"Its pull request is #{int(record['object'])}: work on its own branch.")
    elif branch or pr:
        where = " and ".join(
            x for x in (f"branch `{branch}`" if branch else "", f"pull request #{pr}" if pr else "") if x
        )
        lines.append(f"Its record already carries {where}: read what is there and work on that branch.")
    else:
        lines.append("It has no branch yet: branch off the default branch and open its one pull request.")
    if came:
        lines.append(f"It came back to you by a move whose reason was: {came}")
    lines.append(
        f'A question goes to your team\'s tech lead: `ao msg --kind ask --team {team} "…"`. Nobody controls you.'
    )
    closes = (
        "the pull request closes the decided line"
        if seat == "board-answers"
        else f"the pull request is #{int(record['object'])}, the one you were given"
    )
    lines.append(
        '\nEnd the job with one command, run in your worktree: **`ao stage end <outcome> [--reason "…"]`**. Until you '
        "run it you are working, and a red check or a failing test is no outcome. The home checks each outcome's fact "
        "and refuses one the facts contradict, saying which, and you carry on. The outcomes, and what each is checked "
        "on:"
    )
    lines.append(
        f"- `work-pushed`: the branch is pushed and its pull request is open, its precheck green, and {closes}; no "
        "entry is archived, a job having none. The team's flow then reviews it and the home merges it."
    )
    if seat == "unheld-pull-requests":
        lines.append(
            "- `closed-unmerged`: a reason is given, and the pull request is closed and not merged: where the cure is "
            "to close it (its work done elsewhere, its filing already landed, or what its order's words say to close "
            "it on), close it with a comment saying why, then end so; the job closes."
        )
    lines.append("- `other`: a reason is given, and the job goes to the person with it; the last choice.")
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
    record: Mapping[str, Any],
    model: str,
    *,
    host: str,
    here: str,
    came: str | None = None,
    files: teams.Files | None = None,
) -> StageLaunch:
    """The job's session, nothing created: in the build stage's role, on `model` (the seat's, from the built-in set the
    repo uses), its lane the job's work order. `team` is the record's, whose host and flow the job runs under."""
    seat, lane, name = str(record.get("seat")), lane_of(record), name_of(record)
    where = f"team {team.name}: {name}"
    checkout, read = teams._checkout(org, team, team.repo, host, here, files, where)
    try:
        cfg = repoconfig.load(checkout, read=read)
        cfg.venv = teams.node_venv(host, here)
        role = repoconfig.resolve_role(cfg, ROLE_OF["build"], org.roles)
    except (KeyError, ValueError, OSError) as e:
        raise teams.TeamError(f"{where}: {str(e).strip(chr(34))}") from None
    line = next((m for m in team.members if m.role == role.name), None)
    person, unlisted = teams._person(org, team.repo, role, here, where)
    stage = job_stage(doc)
    under = repoconfig.UnderFlow(
        told(record, team=team.name, adds_review=stage in flow3.independent_review(doc), came=came),
        brief=brief_of(seat),
    )
    try:
        prompt, made = role.compose(
            [lane],
            read=read,
            supplement=line.brief if line is not None and line.brief else None,
            flow=under,
            template_file=JOB_TEMPLATE,
            person=person,
        )
    except ValueError as e:
        raise teams.TeamError(f"{where}: {e}") from None
    # no member's or role's profile: a job runs on the seat's model and the set's login (§4.9d *The login a seat
    # starts on*), which TD-2068 launches on; until then the package's default adapter, never a shell
    x = teams.Launch(
        name=name,
        role=role.name,
        home=team.repo,
        dir=checkout,
        team=team.name,
        project=org.project_of(team.repo),
        prompt=prompt,
        grants=list(role.grants),
        lane=[lane],
        ledger=cfg.ledger,
        host=host if host != here else "",
        context_bound=role.context_bound,
        prompt_from=made,
        unlisted=unlisted,
    )
    return StageLaunch(x, model)


def review_name(record: Mapping[str, Any]) -> str:
    """The name of a review stage's session on the job: the stage's key, `-job-` and the record's key
    (`review-job-pr-12`), which no entry's stage session (`<stage>-td-<n>`) and no job session (`job-<key>`) takes."""
    return f"{record.get('stage')}-{name_of(record)}"


def review_launch(
    org: orgmod.Org,
    team: orgmod.TeamDef,
    doc: dict[str, Any],
    record: Mapping[str, Any],
    *,
    host: str,
    here: str,
    came: str | None = None,
    place: str = "package",
    flow_dir: Path | None = None,
    files: teams.Files | None = None,
) -> StageLaunch:
    """The session of the review stage the job's record stands at, nothing created: that stage's as an entry's would
    be, on the stage's model, its lane the job's work order, told the job's branch and pull request and the reason of
    the move that brought it there (`came`)."""
    stage = str(record.get("stage") or "")
    st = next(
        (s for s in doc.get("stages") or [] if isinstance(s, Mapping) and flow3.key_of(s.get("name")) == stage), None
    )
    if st is None or st.get("does") != "review":
        raise teams.TeamError(f"team {team.name}: {lane_of(record)} stands at {stage!r}, which is no review stage")
    pr = record.get("pr")
    work = Work(
        entry=lane_of(record),
        branch=str(record["branch"]) if record.get("branch") else None,
        pr=pr if isinstance(pr, int) and not isinstance(pr, bool) else None,
        came=came,
    )
    return stage_launch(
        org,
        team,
        doc,
        stage,
        work,
        host=host,
        here=here,
        place=place,
        flow_dir=flow_dir,
        files=files,
        name=review_name(record),
    )
