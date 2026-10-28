"""`ao org` and `ao org check` (design §4.7, §4.9 *The org is an aggregate*; TD-229 slice 6): the org
as the clients aggregate it, printed, and the same reading as a verdict.

Both read what `org.with_repos` already made — the org file plus every registered checkout's
`teams:` — and what a start would check (`teams.plan`), and write nothing: no file, no record, no
RPC that changes anything. The terminal's half (the words in a line, the exit code) is `cli`'s."""

from __future__ import annotations

import subprocess
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

from sessionorc import board, defs, gitinfo, paths
from sessionorc import settings as settings_mod
from shiftlead import flowdefs, repoconfig, teams
from shiftlead import org as orgmod

GIT_TIMEOUT = 5.0
OLD_REPO_FILE = ".agentorc.yml"  # a repo's file before the rename (TD-060): read by nothing, named by the check
# a `.shiftlead.yml` key accepted and read by nothing (`repoconfig.RepoConfig.gone`), and what the check says
GONE = {"gate": "gate: is gone — a repo's extra check is dev-cadence's precheck"}


def where(org: orgmod.Org, team: orgmod.TeamDef, here: str) -> tuple[str, str]:
    """The host a team lands on and why, in `ao org`'s words: a repo's team by the landing rule
    (*place*, *registered here*), the org file's by its own `host:` or,
    with none, the host a start runs on. A landing that cannot be told is `("", <the reason>)`."""
    if team.name in org.unlanded:
        return "", org.unlanded[team.name]
    if team.name in org.landed:
        return org.landed[team.name]
    return (team.host, "host:") if team.host else (here, "no host: — where it is started")


def last_commit(home: Path, name: str) -> str:
    """`<short sha> <date> <subject>` of the last commit that touched `name` under the home, or ""
    when there is none (never committed, or git could not say)."""
    try:
        cp = subprocess.run(
            ["git", "-C", str(home), "log", "-1", "--format=%h %cs %s", "--", name],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return cp.stdout.strip() if cp.returncode == 0 else ""


def remainder(home: Path | None = None) -> dict[str, Any]:
    """What is left at the home (§4.9 *What is left at the home has a history*): each of the three
    definition files, whether it is there, and its last commit; `tree` false when the home is not
    a work tree yet, so nothing has a history."""
    home = home or paths.home()
    tree = defs.is_tree(home)
    files = [
        {
            "name": name,
            "path": str(home / name),
            "exists": (home / name).is_file(),
            "commit": last_commit(home, name) if tree else "",
        }
        for name in defs.TRACKED
    ]
    return {"home": str(home), "tree": tree, "files": files}


def held_elsewhere(
    roots: Collection[str], linked: Collection[str], repos_of: orgmod.ReposOf | None
) -> tuple[list[dict[str, str]], list[str]]:
    """The repos a linked host's registry holds that this one's does not (design §4.9 *A definition
    is read at the home, and only there*, TD-318): `([{host, repo, path}], notes)`, a repo being its
    checkout's directory name, as `_land` reads it. A host whose registry cannot be read (`OSError`:
    unreachable, a build without the `repos` link method) is a note, never read as holding nothing."""
    mine = {Path(str(r)).name for r in roots}
    found: list[dict[str, str]] = []
    notes: list[str] = []
    for host in linked:
        try:
            if repos_of is None:
                raise OSError("nothing here asks a host for its registry")
            theirs = repos_of(host)
        except OSError as e:
            notes.append(f"{host}: its registry could not be read ({e})")
            continue
        for path in theirs:
            repo = Path(str(path)).name
            if repo not in mine and not any(f["host"] == host and f["repo"] == repo for f in found):
                found.append({"host": host, "repo": repo, "path": str(path)})
    return found, notes


def held_line(row: dict[str, str], here: str) -> str:
    """The words `ao org` and its check give a repo held only on a node (§4.9)."""
    return (
        f"{row['repo']} — held only on {row['host']}: its {repoconfig.FILE} is not read; register a checkout at {here}"
    )


def view(
    org: orgmod.Org,
    here: str,
    home: Path | None = None,
    roots: Collection[str] = (),
    linked: Collection[str] = (),
    repos_of: orgmod.ReposOf | None = None,
) -> dict[str, Any]:
    """The org as the clients aggregate it: each team with its source file, its repo and project, the host it
    lands on and why; the names a repo's definition lost to the org file's (`shadowed`) and the
    ones two repos define (`refused`); then the remainder's files with their last commit, and each
    repo a linked host holds that this one does not (`held_elsewhere`, with its `unread` notes)."""
    elsewhere, unread = held_elsewhere(roots, linked, repos_of)
    rows = []
    for name in sorted(org.teams):
        team = org.teams[name]
        host, why = where(org, team, here)
        rows.append(
            {
                "name": name,
                "source": str(team.source) if team.source else "",
                "repo": team.repo,
                "project": org.project_of(team.repo),
                "host": host,
                "why": why,
            }
        )
    return {
        "teams": rows,
        "shadowed": {n: [str(f) for f in fs] for n, fs in org.shadowed.items()},
        "refused": dict(org.refused),
        "flows": flowdefs.visible(roots, org.roles),  # every flow the org can see here (§4.9c)
        "roles": repoconfig.visible(roots),  # every role directory, the org's and the checkouts' (§4.9c, TD-313)
        "remainder": remainder(home),
        "held_elsewhere": elsewhere,
        "unread": unread,
    }


def checkout_warnings(root: Path) -> list[str]:
    """What `ao org check` warns of on a registered checkout that is there: off its default branch,
    or holding changes — a team's definition and its briefs are read from it *as it is checked
    out* (§4.9), so either changes the org while it sits there."""
    info = gitinfo.git_info(root, timeout=GIT_TIMEOUT)
    if info is None:
        return [f"{root}: git could not read it, so its branch and its changes are unknown"]
    out: list[str] = []
    try:
        default = board.default_branch(root)
    except board.Refused:
        default = ""
    if default and info.branch != default:
        out.append(f"{root}: on {info.branch}, not its default branch {default} — the org reads it as checked out")
    if info.dirty:
        out.append(f"{root}: holds {info.dirty} change{'' if info.dirty == 1 else 's'} — the org reads it as it stands")
    return out


def gone_keys(root: Path) -> list[str]:
    """The checkout's `.shiftlead.yml` keys that are read by nothing, each in its words (design §5
    *The seams*, TD-1011); none for a file that does not load, which its own readers name."""
    try:
        cfg = repoconfig.load(root)
    except (ValueError, OSError):
        return []
    return [GONE[key] for key in cfg.gone if key in GONE]


def _git_path(directory: Path, *args: str) -> Path | None:
    """`git -C <directory> <args>`'s one line as a resolved path, or None when git says nothing."""
    try:
        cp = subprocess.run(
            ["git", "-C", str(directory), *args], capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = cp.stdout.strip()
    return Path(out).resolve() if cp.returncode == 0 and out else None


def stand_in_for(directory: str, roots: Collection[str]) -> dict[str, Path]:
    """`ao org check --root <dir>`'s one mapping (design §4.7, TD-942): `{<registry entry>: <dir>}`,
    the entry the checkout of this host's registry whose git common directory is `<dir>`'s — the entry
    that is `<dir>` itself where there is one, else the first in the registry's order. A `<dir>` that is
    not its own work tree's top (a subdirectory, a `.git`, a bare repo, no git at all), or matches no
    entry, is a `ValueError` in the check's words."""
    d = Path(directory).expanduser().resolve()
    refused = ValueError(f"{directory} is not a checkout of a registered repo")
    if not d.is_dir() or _git_path(d, "rev-parse", "--show-toplevel") != d:
        raise refused
    common = _git_path(d, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common is None:
        raise refused
    for root in roots:
        if Path(root).expanduser().resolve() == d:
            return {root: d}
    for root in roots:
        r = Path(root).expanduser()
        if r.is_dir() and _git_path(r, "rev-parse", "--path-format=absolute", "--git-common-dir") == common:
            return {root: d}
    raise refused


def team_lacks(
    org: orgmod.Org, here: str, readings: dict[str, Any], stand_in: Mapping[str, Path] | None = None
) -> list[str]:
    """Where a repo's definitions on this host and its ledger's `Team` declaration disagree (§4.4 *A
    stale team*, *An untagged or unknown entry is handed to a techlead*, TD-730), each a lack: a
    declared name no definition of the repo holds, naming the entries that carry it; where the repo's
    definitions hold two or more teams, each the declaration leaves out, whatever its size; and the
    `needs_team` ids of a repo none of whose teams has a techlead seat. A repo with no reading, or a
    ledger that did not parse, says nothing. A reading of a checkout `stand_in` stands a directory in
    for (`--root`, §4.7, TD-942) is paired with the teams whose checkout is that directory, so the
    ledger as merged is checked against the branch's teams."""
    out: list[str] = []
    stood = {str(Path(k).expanduser().resolve()): Path(v) for k, v in (stand_in or {}).items()}
    for root, r in sorted(readings.items()):
        led = (r or {}).get("ledger") if isinstance(r, dict) else None
        if not isinstance(led, dict) or "declared_teams" not in led or "error" in led:
            continue
        name = r.get("name") or root
        at = stood.get(str(Path(root).expanduser().resolve()), Path(root))
        defs = [t["team"] for t in teams.entry_teams(org, str(at.expanduser().resolve()), here)]
        declared = [str(t) for t in led.get("declared_teams") or []]
        stale = teams.stale_teams(declared, defs, led.get("entries") or [])
        names = [*declared, *(s["team"] for s in stale if s["kind"] == "left-out")]
        for s in stale:
            if s["kind"] == "declared":
                on = f" ({', '.join(s['ids'])} carry it)" if s["ids"] else ""
                out.append(
                    f"{name}: its ledger declares team {s['team']}, which no definition of the repo holds{on} — drop "
                    "it from the Fields: line's Team, or add it back, by PR (design §4.4 A stale team)"
                )
            else:
                out.append(
                    f"{name}: has {len(defs)} teams and its ledger's Fields: line does not declare {s['team']} — add "
                    f"`Team = {' | '.join(names)}`, and a Team: line on each open entry a lane takes, by PR "
                    "(design §4.4 The move from one team to two)"
                )
        need = [str(i) for i in led.get("needs_team") or []]
        if need and not any(org.teams[t].techlead is not None for t in defs if t in org.teams):
            out.append(
                f"{name}: {', '.join(need)} need a team, and no team of the repo has a techlead seat to tag them — "
                "tag them by PR, or give a team a techlead (design §4.4 An entry names its team)"
            )
    return out


def check(  # noqa: PLR0913 — each argument is one thing the verdict reads
    org: orgmod.Org,
    notes: Collection[str],
    here: str,
    roots: Collection[str],
    linked: Collection[str],
    *,
    files: teams.Files | None = None,
    settings: dict[str, Any] | None = None,
    repos_of: orgmod.ReposOf | None = None,
    readings: dict[str, Any] | None = None,
    stand_in: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """`ao org check`: the aggregate as a verdict — `{ok, lacks, warnings}`, `ok` false when
    anything is lacking. `notes` are `with_repos`' own (a repo file that cannot be read, a name
    defined twice, a landing that cannot be told), `roots` this host's registry, `linked` the
    hosts a `place:` may name beside this one, `settings` the settings file as read (None: absent
    or broken, which lacks nothing here).

    A lack, each on its own line: a registered checkout that is not there, or one holding only the
    old `.agentorc.yml` (TD-553); a team a start would
    refuse — its role's profile not in `profiles.yml`, a brief not in the checkout, a checkout
    missing, each in the start's own words (`teams.plan`, which creates nothing); a name defined
    twice; a team whose definition names one session twice (TD-268); a `place:` naming no linked
    host; a team in `settings.yml` no definition names; and, against `readings` (the home's `repos`
    reading, §4.4 *A stale team*, TD-730), a name a repo's ledger declares that no definition of the
    repo holds, a team of a repo with two or more that its ledger does not declare, and entries that
    need a team where no team of the repo has a techlead seat (`team_lacks`). A
    warning, which does not fail it: a registered checkout off its default branch or holding
    changes, a `place:` naming a team no registered repo defines, a repo a linked host's registry
    holds that this one's does not (or a linked registry that could not be read; `repos_of` asks),
    and, per team under a flow, each key it writes that the flow would fill with the same value
    (`teams.flow_redundant`).

    `stand_in` (`ao org check --root <dir>`, §4.7, TD-942) maps a registry entry, as written, to the
    directory read in its place — the same mapping `with_repos` was given: the root loop tests `<dir>`
    and warns of neither path's checkout state, the role directories and flows are read at `<dir>`,
    the ledger reading is paired with the branch's teams, and a team of that repo `place:` puts on
    another host is warned of, its briefs read there and not at `<dir>`."""
    lacks: list[str] = []
    warnings: list[str] = []
    stand_in = stand_in or {}
    seen = [stand_in.get(str(r), r) for r in roots]  # what each reader that takes the roots reads

    def lack(line: str) -> None:
        if line not in lacks:
            lacks.append(line)

    for root in roots:
        at = stand_in.get(str(root))
        path = Path(at if at is not None else root).expanduser()
        if not path.is_dir():
            lack(
                f"{path if at is not None else root}: a registered checkout that is not there — remove its line "
                "from the registry, or clone it"
            )
        else:
            if (path / OLD_REPO_FILE).is_file() and not paths.repo_file(path).is_file():
                lack(
                    f"{path if at is not None else root}: its {OLD_REPO_FILE} is read by nothing — rename it "
                    f"{paths.REPO_FILE} (TD-553)"
                )
            if at is None:  # `<dir>` is on a branch by design, and the checkout it stands for is not read
                warnings.extend(checkout_warnings(path))
            warnings.extend(f"{path if at is not None else root}: {line}" for line in gone_keys(path))
    elsewhere, unread = held_elsewhere(roots, linked, repos_of)
    warnings.extend(held_line(row, here) for row in elsewhere)
    warnings.extend(unread)
    placed_nowhere = {t for t in org.place if t not in org.teams and t not in org.refused}
    for note in notes:
        if any(note.startswith(f"place.{t}:") for t in placed_nowhere):
            warnings.append(note)
        else:
            lack(note)  # an unreadable repo file, a name twice, a landing that cannot be told
    for team, host in org.place.items():
        if team in org.unlanded:
            continue  # its landing's own note says the host could not be asked: one cause, one line
        if host != here and host not in linked:
            lack(
                f"place.{team}: {host} is no linked host of {here} ({', '.join(sorted(linked)) or 'none linked'}) — "
                "name a node under `nodes:` in hosts.yml, or this host"
            )
    for name in sorted(org.teams):
        team = org.teams[name]
        for twice in team.twice_named():
            src = team.source.name if team.source else "its definition"
            # Members… edits the org file only; a repo's team is changed by PR (TD-229)
            hint = " (Members… → Remove keeps the session)" if org.path and team.source == org.path else ""
            lack(f"team {name} names {twice} twice — take one of its lines out of {src}{hint}")
        for key in team.unsized():  # §4.9 *A team's size*: ignored, and said
            lines = ", ".join(m.name for m in team.members) or "none"
            warnings.append(
                f"teams.{name}.size.{key} in settings.yml: no member line of {name} is called {key} "
                f"(its lines: {lines}) — ignored"
            )
        if name in org.unlanded:
            continue  # said above, in the landing's own words
        try:
            teams.plan(org, name, here, files=files)
        except (teams.TeamError, ValueError, OSError) as e:
            lack(str(e).strip('"'))
        else:
            warnings.extend(teams.flow_redundant(org, team, here, here, files))
        for root, at in stand_in.items():
            host = org.landed.get(name, ("", ""))[0]
            if team.repo == Path(root).expanduser().resolve().name and host and host != here:
                warnings.append(f"{name}: briefs read on {host}'s checkout, not at {at}")
    # a flow nobody lists that is not usable (§4.9c): a listed one is the start's refusal, said above
    listed = {f for t in org.teams.values() for f in t.flows}
    for f in flowdefs.visible(seen, org.roles):
        if not f["usable"] and not f.get("shadowed") and f["name"] not in listed:
            lack(f"flow {f['name']} ({f['source']}) is not usable — {'; '.join(f['problems'])}")
    defined = {r["name"] for r in repoconfig.visible(seen) if r["usable"]}
    for name in sorted(org.roles):  # an overlay is not a definition (§4.9c): org.yml's key must name one
        if name not in repoconfig.PRESETS and name not in defined:
            lack(
                f"{org.path.name if org.path else 'org.yml'}: roles.{name} — unknown role: no preset and no role "
                "directory, the org's or a registered checkout's, defines it (an overlay is not a definition, §4.9c)"
            )
    for r in repoconfig.visible(seen):  # a role directory that is not whole, or takes a preset's name
        if not r["usable"] and not r.get("shadowed"):
            lack(f"role {r['name']} ({r['source']}) is not usable — {'; '.join(r['problems'])}")
    for line in team_lacks(org, here, readings or {}, stand_in):
        lack(line)
    for name in sorted(settings_mod.teams(settings or {})):
        if name not in org.teams and name not in org.refused:
            lack(
                f"settings.yml: teams.{name} — no definition names a team {name!r} (a repo renamed its team?); "
                "its settings are read by nothing"
            )
    return {"ok": not lacks, "lacks": lacks, "warnings": warnings}
