"""A seat run live (design §4.3 *The live smoke, unattended*, TD-1648): the seat's brief as the live team
composes it, a scratch clone for it to work in, the seat's launch, one ask as the person and the reply read
from the scratch home's person inbox. Imported by `scripts/conformance.py` (`--smoke`) and by TD-1649's
`scripts/judge.py`; it starts nothing on import and never touches the live home."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEFAULT_ROLE = "fact-checker"
DEFAULT_NAME = "seat-smoke"
REPLY_WAIT = 600.0  # ten minutes for a reply to land on the ask's thread
# the variables a send as the person drops (as `look_home.child_env` does): nobody's session, nobody's pane
NOT_A_SESSION = ("SHIFTLEAD_SESSION", "TMUX", "TMUX_PANE")
# the variables a seat's host agent drops (as `tests/conftest.py` does): a seat profile naming no model never
# reports the builder's
NOT_THE_BUILDERS = ("AGENT_MODEL", "AGENT_MODEL_FILE")
BRIEF_PATHS = (".shiftlead.yml", "src/shiftlead/briefs/")


class SeatRefused(Exception):
    """The seat cannot be composed as asked: a role with no seat line and no `--brief`, a `--seat` naming
    another role's line or none."""


@dataclass
class SeatBrief:
    name: str  # the picked line's, else `seat-smoke`
    role: str
    text: str
    line: str  # the seat line it was composed from, in words, or why none was


def ask_text(nonce: str) -> str:
    """The ask the person sends: the token to reply with, and a last clause naming the options a real ask's
    diff brings, so the inbox read puts them in a shell output before the reply runs (design §4.3)."""
    return (
        f"reply to this ask with the token {nonce} and nothing else; a reply road takes options such as "
        "`--reply-to`, `--json`, `--kind` and `--about`"
    )


def new_nonce() -> str:
    """Twelve hex digits, new each run."""
    return secrets.token_hex(6)


def _seat_lines(checkout: Path, cfg: Any) -> Iterator[Any]:
    """Every record a seat line of the checkout's `.shiftlead.yml` starts (`seat_records()`), across its
    teams in file order — the teams built by `org.merge_repo_teams` on an empty `Org`, no org overlay."""
    from shiftlead import org as orgmod
    from shiftlead import repoconfig

    if not cfg.teams:
        return
    merged = orgmod.merge_repo_teams(orgmod.Org(), checkout, dict(cfg.teams), repoconfig.role_names(cfg))
    for team in merged.teams.values():
        yield from team.seat_records()


def compose(
    checkout: Path,
    role_name: str = DEFAULT_ROLE,
    profile: str = "",
    seat: str | None = None,
    brief_file: Path | None = None,
) -> SeatBrief:
    """The seat's brief as a team start composes it (`teams._brief`), the role resolved from `checkout`'s
    `.shiftlead.yml` over the built-in roles with no org overlay: the line `seat` names, else the one whose
    `profile` is `profile`, else the role's first in file order — its `brief:` in `{repo}`, `{lane}` empty as a
    seat's is, no flow, `{techlead}`, `{manager}` and `{context}` empty. `brief_file` replaces the role's
    template, composed with the same slots; it is the whole of a role with no seat line."""
    from shiftlead import repoconfig, teams

    checkout = Path(checkout).resolve()
    cfg = repoconfig.load(checkout)
    try:
        role = repoconfig.resolve_role(cfg, role_name, {})
    except (KeyError, ValueError) as e:
        raise SeatRefused(f"role {role_name!r}: {str(e).strip(chr(34))}") from None
    lines = list(_seat_lines(checkout, cfg))
    mine = [s for s in lines if s.role == role.name]
    if seat is not None:
        named = [s for s in lines if s.name == seat]
        if not named:
            raise SeatRefused(f"no seat line {seat!r} in {checkout / repoconfig.FILE}")
        if named[0].role != role.name:
            raise SeatRefused(f"seat line {seat!r} is the {named[0].role} role's, not the {role.name} role's (--role)")
        picked, how = named[0], "named by --seat"
    else:
        on_profile = [s for s in mine if profile and s.profile == profile]
        if on_profile:
            picked, how = on_profile[0], f"on profile {profile}"
        elif mine:
            picked, how = mine[0], f"the role's first line (none on profile {profile or '-'}), its brief borrowed"
        else:
            picked, how = None, ""
    if picked is None and brief_file is None:
        raise SeatRefused(f"role {role.name!r} has no seat line in {checkout / repoconfig.FILE}: give --brief <file>")
    template = Path(brief_file).resolve() if brief_file is not None else None
    try:
        text, _from = teams._brief(role, picked, [], template_file=template)
    except ValueError as e:
        raise SeatRefused(str(e)) from None
    if not text:
        raise SeatRefused(f"role {role.name!r} composes no brief")
    line = f"seat line {picked.name} ({how})" if picked is not None else "no seat line"
    if template is not None:
        line += f"; the template replaced by {template}"
    return SeatBrief(name=picked.name if picked is not None else DEFAULT_NAME, role=role.name, text=text, line=line)


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=120
    ).stdout.strip()


def scratch_clone(checkout: Path, where: Path) -> tuple[Path, Path]:
    """A clone of `checkout`'s `HEAD` under `where`, whose `origin` is a local bare repository holding the same
    commits (its `main` at that `HEAD`), so the brief's `git fetch origin` reads. Both share the checkout's
    objects (`--shared`), so nothing is copied. Returns (clone, bare)."""
    checkout = Path(checkout).resolve()
    head = _git("rev-parse", "HEAD", cwd=checkout)
    common = Path(_git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=checkout))
    bare, clone = where / "origin.git", where / "clone"
    _git("clone", "-q", "--bare", "--shared", str(common), str(bare))
    _git("update-ref", "refs/heads/main", head, cwd=bare)
    _git("symbolic-ref", "HEAD", "refs/heads/main", cwd=bare)
    _git("clone", "-q", "--shared", "--branch", "main", str(bare), str(clone))
    return clone, bare


def brief_paths(checkout: Path) -> list[str]:
    """The repo's brief paths: `.shiftlead.yml`, every file a `brief:` key in it names, and the built-in
    templates' directory."""
    import yaml

    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "brief" and isinstance(v, str) and v not in found:
                    found.append(v)
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    with contextlib.suppress(OSError, yaml.YAMLError):
        walk(yaml.safe_load((checkout / ".shiftlead.yml").read_text(encoding="utf-8")))
    return [BRIEF_PATHS[0], *found, BRIEF_PATHS[1]]


def uncommitted(checkout: Path) -> list[str]:
    """`git status --porcelain` lines under the brief paths: what the clone does not hold (the built-in
    templates are read from the running tree all the same)."""
    out = _git("status", "--porcelain", "--", *brief_paths(checkout), cwd=checkout)
    return [line for line in out.splitlines() if line.strip()]


def agent_env(env: dict[str, str]) -> dict[str, str]:
    """A seat's host agent's environment: `env` without the builder's model."""
    return {k: v for k, v in env.items() if k not in NOT_THE_BUILDERS}


def person_env(env: dict[str, str]) -> dict[str, str]:
    """A send as the person: `env` (the scratch home's) without a session or a pane."""
    return {k: v for k, v in env.items() if k not in NOT_A_SESSION}


def launch(call: Callable[..., Any], seat: SeatBrief, adapter: str, profile: str, clone: Path) -> dict[str, Any]:
    """Create the seat as the smoke does: `name`, `adapter`, `profile`, `dir` the clone, `role`, `unattended` and
    the brief as its first prompt — no `seat`, `team`, `supervised`, `controllers` or `worktree`."""
    return call(
        "create",
        name=seat.name,
        adapter=adapter,
        profile=profile,
        dir=str(clone),
        role=seat.role,
        unattended=True,
        prompt=seat.text,
    )


def ask(sid: str, text: str, env: dict[str, str], ao: list[str] | None = None) -> str:
    """One `ao msg --kind ask` to `sid` as the person (`env` the scratch home's, its session and pane dropped);
    the ask's id."""
    cmd = [*(ao or [sys.executable, "-m", "shiftlead.cli"]), "--json", "msg", "--kind", "ask", sid, text]
    cp = subprocess.run(cmd, capture_output=True, text=True, env=person_env(env), timeout=60)
    if cp.returncode:
        raise RuntimeError(f"ao msg exited {cp.returncode}: {(cp.stderr or cp.stdout).strip()}")
    try:  # a warning line may come before the JSON
        got = json.JSONDecoder().raw_decode(cp.stdout[cp.stdout.index("{") :])[0]
        return got["entry"]["id"]
    except (ValueError, KeyError, TypeError):
        raise RuntimeError(f"ao msg printed no entry id: {cp.stdout.strip()[:300]}") from None


def reply_on(entries: list[dict[str, Any]], ask_id: str) -> dict[str, Any] | None:
    """The first reply on `ask_id`'s thread among the person's inbox entries, or None."""
    for e in entries:
        if e.get("kind") == "reply" and ask_id in (e.get("thread"), e.get("reply_to")):
            return e
    return None


@dataclass
class Outcome:
    ok: bool
    step: str  # where it ended: `reply`, `needs-you`, `exited`, `timeout`
    said: str  # what it read
    reply: dict[str, Any] | None = None
    record: dict[str, Any] | None = None


def watch(
    get: Callable[[], dict[str, Any]],
    inbox: Callable[[], list[dict[str, Any]]],
    ask_id: str,
    timeout: float = REPLY_WAIT,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Outcome:
    """Read the seat's record and the person's inbox until a reply lands on the ask's thread (a pass), the
    record reads `needs-you` (a failure, at once), it reads `exited` with no reply (a failure) or `timeout`
    passes (a failure, with the record's state)."""
    end = clock() + timeout
    rec: dict[str, Any] = {}
    while True:
        rec = get()
        if rec.get("state") == "needs-you":  # before the inbox: a prompt met is the failure, reply or none
            pending = rec.get("pending") or {}
            return Outcome(False, "needs-you", f"{pending.get('kind')}: {pending.get('text')}", record=rec)
        got = reply_on(inbox(), ask_id)
        if got is not None:
            return Outcome(True, "reply", got.get("text") or "", reply=got, record=rec)
        if rec.get("state") in ("exited", "closed"):
            return Outcome(False, "exited", f"the seat {rec.get('state')} before a reply landed", record=rec)
        if clock() >= end:
            return Outcome(
                False, "timeout", f"no reply within {timeout:.0f}s; the seat reads {rec.get('state')}", record=rec
            )
        sleep(2.0)


def capture_pane(sock: str, sid: str) -> str:
    """The seat's pane as `capture-pane -e` shows it, or why it could not be read."""
    cp = subprocess.run(
        ["tmux", "-L", sock, "capture-pane", "-e", "-p", "-t", f"={sid}:"], capture_output=True, text=True, timeout=5
    )
    return cp.stdout if cp.returncode == 0 else f"(capture-pane: {cp.stderr.strip()})"


def tool_version(binary: str) -> str:
    """The tool's `--version`, its first line, or `version unknown`."""
    if not shutil.which(binary) and not Path(binary).is_file():
        return "version unknown"
    try:
        cp = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30, env=dict(os.environ))
    except (OSError, subprocess.SubprocessError):
        return "version unknown"
    first = (cp.stdout or cp.stderr).strip().splitlines()
    return first[0] if first else "version unknown"
