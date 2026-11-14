"""`pdm run judge <role> --profile <p>`: a model's fitness for a role, before it takes the role (design §4.9b *A
model's fitness, before the role*, TD-1649). The role's planted-defect set (`tests/judgment/<role>/`, one directory
per case) is run case by case, each case a seat of its own launched as the seat smoke launches one (§4.3 *The live
smoke, unattended*, `scripts/seat_run.py`) in a scratch repository holding none of this repo's history, asked once as
the person, and its reply scored mechanically against the case's planted defects. The run writes one row of
`docs/judgment/<role>.md` (an uncommitted edit, for the PR that quotes it) and says the row on its last line. By
hand, never in CI; it spends one ask per case."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SETS = ROOT / "tests" / "judgment"
ROWS = ROOT / "docs" / "judgment"
STRIPPED = ("tests/judgment", "docs/judgment")  # what no case's repository holds, and no patch touches or names
WIDEST = 20  # lines a cited range may span, and the least gap between a case's locations in one file
CASE_BRANCH = "change"


# --- the set --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    file: str
    a: int
    b: int

    def meets(self, other: Span) -> bool:
        return self.file == other.file and self.a <= other.b and other.a <= self.b


@dataclass
class Defect:
    id: str
    at: Span
    says: str
    refutes: list[Span] = field(default_factory=list)

    def spans(self) -> list[Span]:
        return [self.at, *self.refutes]


@dataclass
class Case:
    name: str
    dir: Path
    pinned: str
    defects: list[Defect]

    @property
    def patch(self) -> Path:
        return self.dir / "change.patch"


def _span(raw: dict[str, Any]) -> Span:
    a, b = raw["lines"]
    return Span(raw["file"], int(a), int(b))


def load_case(d: Path) -> Case:
    raw = tomllib.loads((d / "case.toml").read_text(encoding="utf-8"))
    defects = [
        Defect(x["id"], _span(x), x["says"], [_span(r) for r in x.get("refutes", [])]) for x in raw.get("defect", [])
    ]
    return Case(d.name, d, raw["pinned"], defects)


def load_set(role: str, sets: Path = SETS) -> list[Case]:
    """The role's cases in name order; a case's ordinal is its place here, from 1."""
    root = sets / role
    return [load_case(d) for d in sorted(root.iterdir()) if (d / "case.toml").is_file()]


# --- a case's repository --------------------------------------------------------------------------------------------


def _git(*args: str, cwd: Path, env: dict[str, str] | None = None, stdin: bytes | None = None) -> str:
    cp = subprocess.run(["git", *args], cwd=cwd, env=env, input=stdin, capture_output=True, check=True, timeout=300)
    return cp.stdout.decode("utf-8", "replace").strip()


def pinned_identity(checkout: Path, pinned: str) -> dict[str, str]:
    """The pinned commit's author, committer and dates, which both of a case's commits are made with, so its
    `<sha>` is the same each run."""
    fmt = "%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd"
    an, ae, ad, cn, ce, cd = _git("log", "-1", f"--format={fmt}", "--date=raw", pinned, cwd=checkout).split("\0")
    return {
        "GIT_AUTHOR_NAME": an,
        "GIT_AUTHOR_EMAIL": ae,
        "GIT_AUTHOR_DATE": ad,
        "GIT_COMMITTER_NAME": cn,
        "GIT_COMMITTER_EMAIL": ce,
        "GIT_COMMITTER_DATE": cd,
    }


def case_repo(checkout: Path, case: Case, where: Path) -> tuple[Path, str]:
    """The case's scratch repository (design §4.9b): one parentless commit of the pinned tree less `STRIPPED` on
    `main`, the patch's commit on it as the case's one branch, both pushed to a local bare `origin`, and the seat's
    clone a clone of that `origin` alone. Returns (the clone, the patch commit's sha)."""
    work, bare, clone = where / "work", where / "origin.git", where / "clone"
    work.mkdir(parents=True)
    excludes = [f":(exclude){p}" for p in STRIPPED]
    tar = subprocess.run(
        ["git", "archive", "--format=tar", case.pinned, "--", ".", *excludes],
        cwd=checkout,
        capture_output=True,
        check=True,
        timeout=300,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(work)], input=tar, check=True, timeout=300)
    env = {**os.environ, **pinned_identity(checkout, case.pinned)}
    _git("init", "-q", "-b", "main", cwd=work)
    _git("add", "-A", "-f", ".", cwd=work)
    _git("commit", "-q", "--no-verify", "--no-gpg-sign", "-m", "main", cwd=work, env=env)
    _git("switch", "-q", "-c", CASE_BRANCH, cwd=work)
    _git("apply", "--index", str(case.patch.resolve()), cwd=work)
    _git("commit", "-q", "--no-verify", "--no-gpg-sign", "-m", f"{case.name}: the change", cwd=work, env=env)
    sha = _git("rev-parse", "HEAD", cwd=work)
    _git("clone", "-q", "--bare", str(work), str(bare), cwd=where)
    _git("symbolic-ref", "HEAD", "refs/heads/main", cwd=bare)
    shutil.rmtree(work)
    _git("clone", "-q", "--branch", "main", str(bare), str(clone), cwd=where)
    return clone, sha


def touched(case: Case) -> list[str]:
    """The paths the case's patch touches."""
    out = subprocess.run(
        ["git", "apply", "--numstat", str(case.patch.resolve())], capture_output=True, text=True, check=True
    ).stdout
    return [line.split("\t", 2)[2] for line in out.splitlines() if line.count("\t") >= 2]


def patched(checkout: Path, case: Case, where: Path) -> dict[str, str]:
    """The files the patch touches as they read at the pushed sha: the pinned commit's copies, the patch applied
    in a repository of their own under `where` (raises where it does not apply)."""
    where.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", str(where), cwd=where)
    paths = touched(case)
    for path in paths:
        got = subprocess.run(["git", "show", f"{case.pinned}:{path}"], cwd=checkout, capture_output=True)
        if got.returncode == 0:
            (where / path).parent.mkdir(parents=True, exist_ok=True)
            (where / path).write_bytes(got.stdout)
    _git("apply", str(case.patch.resolve()), cwd=where)
    return {p: (where / p).read_text(encoding="utf-8") for p in paths if (where / p).is_file()}


def lines_in(text: str) -> int:
    return text.count("\n") + (0 if text.endswith("\n") or not text else 1)


def size_at_sha(checkout: Path, case: Case, path: str, files: dict[str, str]) -> int | None:
    """A file's line count at the case's pushed sha (`files`, from `patched`), or None where the stripped tree there
    holds no such file."""
    if any(path == s or path.startswith(s + "/") for s in STRIPPED):
        return None
    if path in files:
        return lines_in(files[path])
    got = subprocess.run(["git", "show", f"{case.pinned}:{path}"], cwd=checkout, capture_output=True)
    return lines_in(got.stdout.decode("utf-8", "replace")) if got.returncode == 0 else None


def ask_text(ordinal: int, sha: str) -> str:
    """The case's ask, one fixed text, as an author's would be."""
    return f"fact-check PR #{ordinal} at {sha}: every claim the diff makes"


# --- the match ------------------------------------------------------------------------------------------------------

LIST_MARKER = re.compile(r"^(?:[-*+]|\d+[.)])\s")
LOCATION = re.compile(r"^(?P<path>[^:\s]+):(?P<a>\d+)(?:[-–](?P<b>\d+))?$")
STRIP = "`\"'()[]{}<>*_"
TRAIL = ".,:;"


def blocks(text: str) -> list[str]:
    """The reply after its first line, cut into blocks: one starts at each top-level list marker and at each
    unindented paragraph outside a list; an indented line, a nested list or an indented paragraph belongs to the
    block above it."""
    out: list[list[str]] = []
    blank = True
    for line in text.splitlines()[1:]:
        if not line.strip():
            blank = True
            continue
        top = not line[0].isspace()
        if top and (LIST_MARKER.match(line) or blank) or not out:
            out.append([line])
        else:
            out[-1].append(line)
        blank = False
    return ["\n".join(b) for b in out]


def _clean(token: str) -> str:
    prev = None
    while prev != token:
        prev = token
        token = token.strip(STRIP)
        token = token.rstrip(TRAIL)
    for lead in ("a/", "b/", "./"):
        if token.startswith(lead):
            token = token[len(lead) :]
    return token


def locations(block: str, sizes: dict[str, int]) -> list[Span]:
    """Every `path:line` or `path:a-b` the block names: the path a file at the pushed sha (`sizes`, its line counts),
    the range in order, at most `WIDEST` lines and inside the file; any other `x:n` token is none."""
    found: list[Span] = []
    for raw in block.split():
        m = LOCATION.match(_clean(raw))
        if not m or m["path"] not in sizes:
            continue
        a = int(m["a"])
        b = int(m["b"]) if m["b"] else a
        if a > b or b - a + 1 > WIDEST or a < 1 or b > sizes[m["path"]]:
            continue
        found.append(Span(m["path"], a, b))
    return found


@dataclass
class Score:
    answered: bool
    why: str = ""  # a `none`'s reason
    caught: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    false: int = 0
    duplicates: int = 0
    model: str = ""


def verdict_line(text: str) -> str | None:
    first = (text or "").strip().splitlines()[:1]
    line = first[0].strip().strip("`").strip() if first else ""
    return line if line.startswith("cadence-review:") else None


def model_of(line: str) -> str:
    """`<adapter>/<model>`, the verdict line's second field."""
    parts = [p.strip() for p in line.split("·")]
    return parts[1] if len(parts) > 1 and "/" in parts[1] else ""


def score(text: str, case: Case, sizes: dict[str, int]) -> Score:
    """The mechanical match (design §4.9b): no `cadence-review:` first line scores `none` (malformed); else, in the
    reply's order, a block naming a location is a finding, which catches every defect not yet caught whose range or
    refuting range it meets; one whose in-range locations meet only defects already caught is a duplicate; one
    meeting none is false; a block naming no location is not scored."""
    line = verdict_line(text)
    if line is None:
        return Score(False, "malformed: no cadence-review: first line")
    got = Score(True, model=model_of(line))
    caught: set[str] = set()
    for block in blocks(text.strip()):
        locs = locations(block, sizes)
        if not locs:
            continue
        hit = [d for d in case.defects if any(s.meets(loc) for s in d.spans() for loc in locs)]
        new = [d for d in hit if d.id not in caught]
        if new:
            for d in new:
                caught.add(d.id)
                got.caught.append(d.id)
        elif hit:
            got.duplicates += 1
        else:
            got.false += 1
    got.missed = [d.id for d in case.defects if d.id not in caught]
    return got


# --- the bar and the row --------------------------------------------------------------------------------------------


@dataclass
class Tally:
    cases: int
    answered: int
    caught: int
    missed: int
    false: int
    false_cases: int
    none: int

    @property
    def passed(self) -> bool:
        """The fact-checker's *alone* bar over the set: misses at most one in ten of the defects in answered cases,
        cases with a false finding at most one in five of the answered, `none` at most one in five of the cases."""
        return (
            self.missed * 10 <= self.caught + self.missed
            and self.false_cases * 5 <= self.answered
            and self.none * 5 <= self.cases
        )


def tally(scores: list[Score]) -> Tally:
    answered = [s for s in scores if s.answered]
    return Tally(
        cases=len(scores),
        answered=len(answered),
        caught=sum(len(s.caught) for s in answered),
        missed=sum(len(s.missed) for s in answered),
        false=sum(s.false for s in answered),
        false_cases=sum(1 for s in answered if s.false),
        none=len(scores) - len(answered),
    )


ROW_HEAD = "| date | profile | model | caught | missed | false | none | minutes | passed |"


def row(day: str, profile: str, model: str, t: Tally, minutes: float) -> str:
    return (
        f"| {day} | {profile} | {model or '—'} | {t.caught} | {t.missed} | {t.false} | {t.none} | "
        f"{minutes:.0f} | {'yes' if t.passed else 'no'} |"
    )


def write_row(path: Path, line: str) -> None:
    """Append the run's row to the role's table (an uncommitted edit, for the PR that quotes it)."""
    text = path.read_text(encoding="utf-8")
    path.write_text(text.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")


# --- the run --------------------------------------------------------------------------------------------------------


def sizes_at(clone: Path, sha: str) -> dict[str, int]:
    """Every file at `sha` and its line count, as a location's path and range are read."""
    names = _git("ls-tree", "-r", "-z", "--name-only", sha, cwd=clone).split("\0")
    out: dict[str, int] = {}
    for name in filter(None, names):
        blob = subprocess.run(["git", "show", f"{sha}:{name}"], cwd=clone, capture_output=True, timeout=60).stdout
        out[name] = lines_in(blob.decode("utf-8", "replace"))
    return out


def run(args: argparse.Namespace, entry: dict[str, Any]) -> int:
    import conformance
    import look_home
    import seat_run

    cases = load_set(args.role)
    if not cases:
        print(f"judge: refused — no cases under {SETS / args.role}", file=sys.stderr)
        return 2
    table = ROWS / f"{args.role}.md"
    if not table.is_file():
        print(f"judge: refused — no table {table.relative_to(ROOT)}", file=sys.stderr)
        return 2
    home = Path(tempfile.mkdtemp(prefix="aoj-", dir="/tmp"))
    sock = f"ao-judge-{uuid.uuid4().hex[:8]}"
    agent: subprocess.Popen | None = None
    call: Callable[..., Any] | None = None
    sid = ""
    scores: list[Score] = []
    started: float | None = None
    print(f"judge: the {args.role} set ({len(cases)} cases) on profile {args.profile}")
    try:
        head, _bare = seat_run.scratch_clone(ROOT, home / "head")
        for line in seat_run.uncommitted(ROOT):
            print(f"uncommitted, not in the clone: {line}")
        try:
            brief = seat_run.compose(
                head, args.role, args.profile, args.seat, Path(args.brief).resolve() if args.brief else None
            )
        except seat_run.SeatRefused as e:
            print(f"judge: refused — {e}", file=sys.stderr)
            return 2
        print(f"brief: role {brief.role}, {brief.line}; each case's seat named {brief.name}")
        conformance.write_profiles(home, args.profile, entry)
        env = seat_run.agent_env(conformance.agent_env(home, sock, None))
        agent = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "look_home.py"), "--agent", sock], env=env)
        if not look_home.wait_for(lambda: (home / "agent.sock").exists() or agent.poll() is not None, 15):
            print("judge: the host agent never opened its socket", file=sys.stderr)
            return 1
        if agent.poll() is not None:
            print(f"judge: the host agent exited {agent.returncode}", file=sys.stderr)
            return 1
        os.environ.update({k: env[k] for k in ("SHIFTLEAD_HOME", "SHIFTLEAD_TMUX_SOCKET")})
        for k in seat_run.NOT_A_SESSION:  # the run is the person
            os.environ.pop(k, None)
        from sessionorc.client import call_sync

        def call(m: str, **p: Any) -> Any:
            return call_sync(m, **p)

        print(f"judge: SHIFTLEAD_HOME={home}, tmux -L {sock}")
        for n, case in enumerate(cases, 1):
            clone, sha = case_repo(ROOT, case, home / "cases" / case.name)
            if started is None:
                started = time.monotonic()
            try:
                rec = seat_run.launch(call, brief, args.adapter, args.profile, clone)
                sid = rec["id"]
                ask_id = seat_run.ask(sid, ask_text(n, sha), env, about=f"#{n}")
            except Exception as e:  # noqa: BLE001 — a refused create or ask is the case's `none`, said
                scores.append(Score(False, f"launch or ask: {type(e).__name__}: {e}"))
                print(f"case {n} {case.name}: none — {scores[-1].why}")
                continue
            got = seat_run.watch(
                lambda s=sid: call("get", id=s), lambda: (call("inbox") or {}).get("entries") or [], ask_id
            )
            if got.ok:
                s = score(got.said, case, sizes_at(clone, sha))
            else:
                s = Score(False, f"{got.step}: {got.said}")
                if got.step == "needs-you":
                    print(f"pending: {json.dumps((got.record or {}).get('pending'))}")
            scores.append(s)
            with contextlib.suppress(Exception):
                call("kill", id=sid)
            sid = ""
            if s.answered:
                print(
                    f"case {n} {case.name}: caught {len(s.caught)} {s.caught} · missed {len(s.missed)} {s.missed}"
                    f" · false {s.false} · duplicates {s.duplicates}"
                )
            else:
                print(f"case {n} {case.name}: none — {s.why}")
        minutes = (time.monotonic() - (started or time.monotonic())) / 60
        t = tally(scores)
        model = next((s.model for s in scores if s.answered and s.model), "")
        line = row(datetime.now(UTC).strftime("%Y-%m-%d"), args.profile, model, t, minutes)
        write_row(table, line)
        if t.none == t.cases:
            print("judge: every case none — a seat whose reply road meets a prompt scores none on each")
        print(f"judge: {'passed' if t.passed else 'failed'} — row written to {table.relative_to(ROOT)}: {line}")
        return 0 if t.passed else 1
    except KeyboardInterrupt:
        print("judge: stopped", file=sys.stderr)
        return 1
    finally:
        if sid and call is not None:
            with contextlib.suppress(Exception):
                call("kill", id=sid)
        look_home.stop(agent)
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(["tmux", "-L", sock, "kill-server"], capture_output=True, timeout=5)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(f"/tmp/tmux-{os.getuid()}/{sock}")
        if args.keep:
            print(f"kept: {home} (the scratch home, each case's repository under cases/)")
        else:
            look_home.remove_home(home)


def main(argv: list[str] | None = None) -> int:
    start_env = dict(os.environ)
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "src"))
    ap = argparse.ArgumentParser(prog="judge", description=__doc__.split("\n\n")[0])
    ap.add_argument("role", help="the role whose set to run, e.g. fact-checker")
    ap.add_argument("--profile", help="the seat profile to judge (required)")
    ap.add_argument("--seat", help="the seat line whose brief and name the seats take, by name")
    ap.add_argument("--brief", help="a template in place of the role's (an older brief)")
    ap.add_argument("--keep", action="store_true", help="keep the scratch home and each case's repository")
    args = ap.parse_args(argv)
    import conformance

    if why := conformance.refusal(start_env, args.profile):
        print(f"judge: refused — {why.replace('the walk', 'the run')}", file=sys.stderr)
        return 2
    from sessionorc import adapters, paths

    adapters.load_all()
    live = paths.home() / "profiles.yml"
    try:
        import yaml

        prof = (yaml.safe_load(live.read_text(encoding="utf-8")) or {}).get("profiles", {}).get(args.profile) or {}
    except OSError as e:
        print(f"judge: refused — {e}", file=sys.stderr)
        return 2
    args.adapter = prof.get("adapter") or ""
    if not args.adapter or args.adapter not in adapters.names() or not adapters.has_agent(args.adapter):
        print(f"judge: refused — profile {args.profile!r} names no agent adapter in {live}", file=sys.stderr)
        return 2
    try:
        entry = conformance.scratch_profile(args.adapter, args.profile, live, env=start_env, smoke=True)
    except conformance.Refused as e:
        print(f"judge: refused — {e}", file=sys.stderr)
        return 2
    return run(args, entry)


if __name__ == "__main__":
    sys.exit(main())
