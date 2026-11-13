#!/usr/bin/env python3
"""The replay kit of TD-1722's trial (design §4.9c *The trial of the new shape*, TD-1772).

    pdm run python scripts/design_replay.py prepare TD-<n> [--script-from <commit>]
    pdm run python scripts/design_replay.py run TD-<n> --max-turns <n>
    pdm run python scripts/design_replay.py run TD-<n> --wait
    pdm run python scripts/design_replay.py audit TD-<n> <k>

`prepare` builds run `k` of a replay at `<root>/TD-<n>.<k>`: the base's files as the root commit of a repository with
no remote, then the overlay commit `replay overlay (TD-1722)` from the trial commit. `run` starts `claude -p` in the
newest run's tree, detached and bounded, on the conformance profile; `run --wait` only waits and says how it ended.
`audit` reads a run's transcripts and flags every step outside the tree. Every path is under `--root` (default
`~/replays`), run from a worktree of this repository.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path

OVERLAY_SUBJECT = "replay overlay (TD-1722)"
RESULT_SUBJECT = "replay result (TD-1722)"
REPLAYED = ("TD-1557", "TD-1569", "TD-1470")  # Paul's pick (2026-11-12): no sentence naming one is carried over
MODEL = "claude-opus-5-5"
CONFIG_DIR = "~/.claude-conformance"  # the conformance profile, never the person's ~/.claude
LONG_ROUNDS = 6  # a design whose original ran more than this many rounds gets the long timeout
TIMEOUT_HOURS, LONG_TIMEOUT_HOURS = 24, 72
FIRST_REPLAY_ID = "TD-9001"
LEDGER_SCRIPTS_ALLOWED = {"ledger.py", "cadence_config.py"}
HARMLESS = ("/dev", "/usr", "/bin", "/lib")  # never flagged, and listed in the audit's output
CADENCE = ["agent-cadence"]  # the launcher; a test points it at a stub
GIT_TIMEOUT = 300
PREP_TIMEOUT = 1800
EMPTY_PREP = "claims: []\nrules: []\nnew: []\nwaive: []\n"
IDENT = ["-c", "user.name=replay", "-c", "user.email=replay@localhost"]
POLL = 30.0


class Refused(Exception):
    """What stops a subcommand: printed as `design-replay: <why>`, exit 2."""


def git(cwd: Path, *args: str, check: bool = True, data: bytes | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, input=data, timeout=GIT_TIMEOUT, check=False)
    if check and r.returncode != 0:
        raise Refused(f"git {' '.join(args[:3])}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout.decode(errors="replace")


def git_bytes(cwd: Path, *args: str) -> bytes:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=GIT_TIMEOUT, check=False)
    if r.returncode != 0:
        raise Refused(f"git {' '.join(args[:3])}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def source_top() -> Path:
    return Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())


def main_checkout(top: Path) -> Path:
    return Path(git(top, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent


def show(top: Path, commit: str, rel: str) -> str | None:
    r = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=top, capture_output=True, timeout=GIT_TIMEOUT)
    return r.stdout.decode() if r.returncode == 0 else None


def run_dir(root: Path, td: str, k: int) -> Path:
    return root / f"{td}.{k}"


def runs(root: Path, td: str) -> list[int]:
    out = []
    for p in root.glob(f"{td}.*"):
        m = re.fullmatch(rf"{re.escape(td)}\.(\d+)", p.name)
        if m and p.is_dir():
            out.append(int(m.group(1)))
    return sorted(out)


# --- what the trial commit says of the design ----------------------------------------------------------------------


def entry_text(top: Path, commit: str, td: str) -> str:
    for rel in (f"docs/ledger/{td}.md", f"docs/ledger/archive/{td}.md"):
        text = show(top, commit, rel)
        if text is not None:
            return text
    raise Refused(f"no ledger entry {td} at {commit[:12]}")


def first_design_pr(entry: str, td: str) -> int:
    m = re.search(r"^\*\*Design PR:\*\*\s*#(\d+)", entry, re.MULTILINE)
    if not m:
        raise Refused(f"{td} names no Design PR")
    return int(m.group(1))


def pr_created_at(top: Path, pr: int) -> str:
    """When the PR was opened, from the forge (prepare runs outside the replay)."""
    r = subprocess.run(
        ["gh", "pr", "view", str(pr), "--json", "createdAt", "-q", ".createdAt"],
        cwd=top,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise Refused(f"gh pr view {pr}: {r.stderr.strip() or 'no createdAt'}")
    return r.stdout.strip()


def original_rounds(top: Path, commit: str, td: str) -> int:
    """The highest round in the original's review record's table, 0 with no record."""
    text = show(top, commit, f"docs/reviews/{td}.md") or ""
    rounds = [int(m.group(1)) for m in re.finditer(r"^\|\s*R\d+\s*\|\s*(\d+)\s*\|", text, re.MULTILINE)]
    return max(rounds, default=0)


# --- the overlay ---------------------------------------------------------------------------------------------------

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*(`_])")


def names_replayed(text: str) -> bool:
    return any(re.search(rf"(?<![A-Za-z0-9]){t}(?![0-9])", text) for t in REPLAYED)


def drop_sentences(par: str) -> str:
    """A paragraph less each sentence naming a replayed design; the paragraph as it was when none does."""
    if not names_replayed(par):
        return par
    kept = [s for s in SENTENCE_RE.split(" ".join(par.split())) if not names_replayed(s)]
    return "\n".join(_wrap(" ".join(kept))) if kept else ""


def _wrap(text: str, width: int = 120) -> list[str]:
    lines, cur = [], ""
    for w in text.split(" "):
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    return lines + ([cur] if cur else [])


def paragraphs(text: str) -> list[str]:
    return re.split(r"\n\s*\n", text.strip("\n"))


def brief_less_replayed(brief: str) -> str:
    return "\n\n".join(p for p in (drop_sentences(p) for p in paragraphs(brief)) if p) + "\n"


def flows_excerpt(flows: str) -> str:
    """§4.9c from *What a design's author prepares before a review* through *The gate*, the checklist paragraph less
    its sentences naming the replayed designs."""
    pars = paragraphs(flows)
    try:
        lead = "**What a design's author prepares before a review**"
        start = next(i for i, p in enumerate(pars) if p.startswith(lead))
        end = next(i for i, p in enumerate(pars) if i > start and p.startswith("**The gate"))
    except StopIteration:
        raise Refused("§4.9c at the trial commit has no *What a design's author prepares* … *The gate* span") from None
    out = []
    for p in pars[start : end + 1]:
        out.append(drop_sentences(p) if p.startswith("**The checklist") else p)
    return "\n\n".join(p for p in out if p) + "\n"


def settings_without_session_start(text: str) -> str:
    data = json.loads(text)
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        hooks.pop("SessionStart", None)
        if not hooks:
            data.pop("hooks")
    return json.dumps(data, indent=2) + "\n"


AGENTS_LINE = (
    "A replay runs no session-start hook, follows `REPLAY.md`'s rules over this file's, and reads `REPLAY.md` again "
    "after any compaction."
)


def agents_replaced(text: str) -> str:
    m = re.search(r"^## First, every session\n.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        raise Refused("the base's AGENTS.md has no *First, every session* section")
    return text[: m.start()] + f"## First, every session\n\n{AGENTS_LINE}\n\n" + text[m.end() :]


def replay_md(
    td: str,
    base: str,
    tree: Path,
    python: Path,
    brief: str,
    excerpt: str,
    causes: list[str],
    refusals: list[str],
) -> str:
    prep = f"{python} scripts/design_prep.py --entry {td} --rev <the commit it reads> --base <the overlay commit>"
    lines = [
        f"# Replay of {td} (TD-1722)",
        "",
        f"You are the designer of {td}, at the base `{base[:12]}`. Design it by the brief that follows, gated from "
        "round 1, as a design whose round 1 starts now. Where the brief needs the org, these rules win, and the "
        "brief's other additions since the base are accepted as part of what is tried:",
        "",
        "- run no `ao`, no `gh`, no `agent-cadence hook`, no `agent-cadence run` but `ledger.py` and "
        "`cadence_config.py`, no `git fetch` or other remote command, no web tool; read and write nothing outside "
        f"this tree (`{tree}`) but the pinned agent-cadence tree (`agent-cadence path`), the main checkout's `.venv` "
        f"directory, read-only, whose interpreter (`{python}`) runs the script, and the run's own temporary directory "
        "(`$TMPDIR`);",
        "- you apply every round's fixes yourself;",
        f"- file builds under `{FIRST_REPLAY_ID}` up, in order, with `ledger.py new --id`;",
        "- send nothing meant for a person or another seat — a steer, an ask, an act line, the end-of-rounds item, "
        "the fact-check trial's ask: a steer takes its default and an ask the designer's recommendation, each a line "
        "under the review record's `Decided:` saying what it would have sent;",
        "- run each reviewer as a subagent the replay waits on — Fable then Sonnet, the fact-checks Sonnet — given "
        f"this tree's path, its first step `{prep}` and no fetch (the overlay commit is the one whose subject is "
        f"`{OVERLAY_SUBJECT}`);",
        "- send on a pre-review run whose causes of CANNOT RUN are all among those listed below, as the gate sends "
        "on a CANNOT RUN, writing it in the Rounds list and filing nothing; any other CANNOT RUN ends the replay "
        "(`Decided: replay stopped — <the line>`);",
        "- end the rounds by the stop rule or at the cap for the design's class, never with a bought round, since "
        "no one buys one; write the Rounds list, which a PR body would hold, at the end of the review record; once "
        "the closing fact-check's re-run raises nothing, write `Decided: replay ended — <stop rule or cap>` and make "
        f"the last commit, subject `{RESULT_SUBJECT}`: the replay's **result**. Open no PR and merge nothing.",
        "",
        "## Causes of CANNOT RUN a pre-review run may send on",
        "",
    ]
    lines += [f"- {c}" for c in causes] or ["- none: every cause of CANNOT RUN ends the replay"]
    lines += ["", "## Ledger writes the helper refuses here", ""]
    if refusals:
        lines += [f"- {r} — write that entry or line by hand, in the base's own form" for r in refusals]
    else:
        lines.append("- none: `ledger.py new --id` and `ledger.py note` both run in this tree")
    lines += ["", "## The designer brief", "", brief.rstrip("\n"), ""]
    lines += ["## §4.9c, the author's preparation and the gate", "", excerpt.rstrip("\n"), ""]
    return "\n".join(lines)


# --- prepare -------------------------------------------------------------------------------------------------------


def trial_commit(root: Path, top: Path) -> str:
    rec = root / "trial"
    if rec.exists():
        return rec.read_text().split()[0]
    sha = git(top, "rev-parse", "--verify", "origin/main^{commit}").strip()
    rec.write_text(f"{sha}\n")
    return sha


def ensure_pin(tree: Path) -> Path:
    """The base's agent-cadence pin made available (the launcher fetches it once), and its tree's path."""
    r = subprocess.run(
        [*CADENCE, "-C", str(tree), "path", "scripts/ledger.py"], capture_output=True, text=True, timeout=GIT_TIMEOUT
    )
    out = r.stdout.strip().splitlines()
    if r.returncode != 0 or not out:
        raise Refused(f"the base's agent-cadence pin is not available: {r.stderr.strip() or 'no path'}")
    return Path(out[-1]).parents[1]


def prep_causes(tree: Path, td: str, base: str, python: Path) -> list[str]:
    """The causes of CANNOT RUN the script prints on the scratch commit; a run that cannot start stops prepare."""
    cmd = [str(python), "scripts/design_prep.py", "--entry", td, "--advisory", "--base", base]
    try:
        r = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, timeout=PREP_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Refused(f"design_prep.py cannot start: {e}") from None
    lines = r.stdout.strip().splitlines()
    head = "design-prep: ADVISORY · "
    if not lines or not lines[0].startswith(head):
        raise Refused(f"design_prep.py cannot start: {(r.stderr or r.stdout).strip()[-400:] or 'no output'}")
    first = lines[0][len(head) :]
    if first.startswith("CANNOT RUN · "):
        m = re.match(r"CANNOT RUN · TD-\d+ · [0-9a-f]{12} · base [0-9a-f]{12} · (.*)$", first)
        if not m:  # no commit read: the run never started its checks
            raise Refused(f"design_prep.py cannot start: {lines[0]}")
        return [c.strip() for c in m.group(1).split("; ") if c.strip()]
    if first.startswith("NOT PREPARED"):
        raise Refused(f"design_prep.py cannot start on an empty prep file: {lines[0]}")
    return [ln[len("tools · could not run · ") :] for ln in lines[1:] if ln.startswith("tools · could not run · ")]


def ledger_refusals(tree: Path, td: str, tmp: Path) -> list[str]:
    """Run `ledger.py new --id` and `ledger.py note` under the base's pin; each that refuses is named."""
    sec = tmp / "probe-section.md"
    sec.write_text("A probe of the replay kit.\n")
    probes = {
        f"`ledger.py new --id {FIRST_REPLAY_ID}`": [
            "new",
            "--id",
            FIRST_REPLAY_ID,
            "--title",
            "replay probe",
            "--priority",
            "Medium",
            *[a for f in ("--why", "--fix", "--done-when") for a in (f, str(sec))],
        ],
        f"`ledger.py note {td}`": ["note", td, "replay probe"],
    }
    out = []
    for name, args in probes.items():
        try:
            r = subprocess.run(
                [*CADENCE, "-C", str(tree), "run", "ledger.py", *args],
                cwd=tree,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT,
            )
            ok, why = r.returncode == 0, (r.stderr or r.stdout).strip().splitlines()
        except (OSError, subprocess.TimeoutExpired) as e:
            ok, why = False, [str(e)]
        if not ok:
            out.append(f"{name} refuses ({why[-1] if why else 'no output'})")
    sec.unlink(missing_ok=True)
    return out


def prepare(args: argparse.Namespace) -> int:
    td, root = args.td, args.root
    root.mkdir(parents=True, exist_ok=True)
    top = source_top()
    trial = trial_commit(root, top)
    script_from = args.script_from and git(top, "rev-parse", "--verify", f"{args.script_from}^{{commit}}").strip()
    python = args.python or main_checkout(top) / ".venv" / "bin" / "python"
    entry = entry_text(top, trial, td)
    pr = first_design_pr(entry, td)
    created = args.created_at or pr_created_at(top, pr)
    base = git(top, "rev-list", "-1", f"--before={created}", "origin/main").strip()
    if not base:
        raise Refused(f"no origin/main commit before #{pr} was opened ({created})")
    k = max(runs(root, td), default=0) + 1
    tree, tmp = run_dir(root, td, k), root / f"{td}.{k}.tmp"
    tree.mkdir()
    tmp.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(git_bytes(top, "archive", "--format=tar", base))) as tar:
        tar.extractall(tree, filter="tar")
    git(tree, "init", "-q", "-b", "main")
    git(tree, "add", "-A", "-f")
    git(tree, *IDENT, "commit", "-q", "--no-verify", "-m", f"replay base: {td} at {base[:12]} (TD-1722)")
    script = show(top, script_from or trial, "scripts/design_prep.py")
    brief = show(top, trial, "docs/briefs/designer-ao-1.md")
    flows = show(top, trial, "docs/design/4.9c-flows.md")
    if script is None or brief is None or flows is None:
        raise Refused(f"the trial commit {trial[:12]} lacks design_prep.py, the designer brief or §4.9c")
    (tree / "scripts").mkdir(exist_ok=True)
    (tree / "scripts/design_prep.py").write_text(script)
    settings = tree / ".claude/settings.json"
    if settings.exists():
        settings.write_text(settings_without_session_start(settings.read_text()))
    agents = tree / "AGENTS.md"
    agents.write_text(agents_replaced(agents.read_text()))
    brief_out, excerpt = brief_less_replayed(brief), flows_excerpt(flows)

    def write_replay(causes: list[str], refusals: list[str]) -> None:
        (tree / "REPLAY.md").write_text(replay_md(td, base, tree, python, brief_out, excerpt, causes, refusals))

    write_replay([], [])
    git(tree, "add", "-A")
    git(tree, *IDENT, "commit", "-q", "--no-verify", "-m", OVERLAY_SUBJECT)
    overlay = git(tree, "rev-parse", "HEAD").strip()
    ensure_pin(tree)
    prep = tree / f"docs/reviews/{td}.prep.yml"
    prep.parent.mkdir(parents=True, exist_ok=True)
    prep.write_text(EMPTY_PREP)
    git(tree, "add", "-A")
    git(tree, *IDENT, "commit", "-q", "--no-verify", "-m", "replay scratch (dropped)")
    try:
        causes = prep_causes(tree, td, overlay, python)
        refusals = ledger_refusals(tree, td, tmp)
    finally:
        git(tree, "reset", "-q", "--hard", overlay)
        git(tree, "clean", "-q", "-fd")
    write_replay(causes, refusals)
    git(tree, "add", "-A")
    git(tree, *IDENT, "commit", "-q", "--no-verify", "--amend", "-m", OVERLAY_SUBJECT)
    overlay = git(tree, "rev-parse", "HEAD").strip()
    if script_from:
        with (root / "trial").open("a") as f:
            f.write(f"script-from {script_from} {td}.{k}\n")
    print(f"trial {trial}")
    if script_from:
        print(f"script-from {script_from}")
    print(f"base {base}")
    print(f"overlay {overlay}")
    print(f"run {k} {tree}")
    return 0


# --- run -----------------------------------------------------------------------------------------------------------


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid(p: Path) -> int | None:
    try:
        return int(p.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def live_replays(root: Path) -> list[str]:
    out = []
    for p in sorted(root.glob("TD-*.pid")):
        pid = read_pid(p)
        if pid and alive(pid) and not p.with_suffix(".exit").exists():
            out.append(f"{p.stem} (pid {pid})")
    return out


STUB = """#!/bin/sh
printf '%s {name}' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> {log}
for a in "$@"; do printf ' %s' "$a" >> {log}; done
printf '\\n' >> {log}
echo "{name}: not in a replay (TD-1722)" >&2
exit 2
"""


def run_command(
    td: str, k: int, root: Path, max_turns: int, hours: int, config_dir: Path, env: dict[str, str]
) -> tuple[list[str], dict[str, str]]:
    """The detached wrapper's argv and environment: `claude -p` in the tree, bounded, on the conformance profile."""
    tree, tmp, rd = run_dir(root, td, k), root / f"{td}.{k}.tmp", root / f"{td}.{k}.run"
    stubs = rd / "bin"
    claude = [
        "claude",
        "-p",
        "--model",
        MODEL,
        "--max-turns",
        str(max_turns),
        "--permission-mode",
        "bypassPermissions",
        "--setting-sources",
        "project",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    inner = (
        f"timeout {hours * 3600} {shlex.join(claude)} < {shlex.quote(str(tree / 'REPLAY.md'))} "
        f"> {shlex.quote(str(root / f'{td}.{k}.stream.jsonl'))} 2> {shlex.quote(str(rd / 'stderr.log'))}; "
        f"echo $? > {shlex.quote(str(root / f'{td}.{k}.exit'))}"
    )
    out = {k_: v for k_, v in env.items() if not k_.startswith("SHIFTLEAD_")}
    out["CLAUDE_CONFIG_DIR"] = str(config_dir)
    out["TMPDIR"] = str(tmp)
    out["PATH"] = f"{stubs}{os.pathsep}{env.get('PATH', '')}"
    return ["setsid", "sh", "-c", inner], out


def spawn(argv: list[str], cwd: Path, env: dict[str, str]) -> int:
    """Start the wrapper in a session of its own, so it outlives the grinder that started it; its pid."""
    p = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return p.pid


def start(args: argparse.Namespace) -> int:
    td, root = args.td, args.root
    ks = runs(root, td)
    if not ks:
        raise Refused(f"no run of {td} under {root}: prepare one first")
    k = ks[-1]
    if args.max_turns is None:
        raise Refused("run needs --max-turns when it starts a run")
    pidf = root / f"{td}.{k}.pid"
    if pidf.exists():
        raise Refused(f"run {k} of {td} was started already: prepare run {k + 1} for another")
    busy = live_replays(root)
    if busy:
        raise Refused(f"a replay is running: {', '.join(busy)}")
    top = source_top()
    trial = trial_commit(root, top)
    hours = LONG_TIMEOUT_HOURS if original_rounds(top, trial, td) > LONG_ROUNDS else TIMEOUT_HOURS
    rd = root / f"{td}.{k}.run"
    (rd / "bin").mkdir(parents=True, exist_ok=True)
    (root / f"{td}.{k}.tmp").mkdir(exist_ok=True)
    for name in ("ao", "gh"):
        stub = rd / "bin" / name
        stub.write_text(STUB.format(name=name, log=shlex.quote(str(rd / "calls.log"))))
        stub.chmod(0o755)
    argv, env = run_command(td, k, root, args.max_turns, hours, args.config_dir, dict(os.environ))
    pid = spawn(argv, run_dir(root, td, k), env)
    pidf.write_text(f"{pid}\n")
    print(f"run {k} of {td} started · pid {pid} · max-turns {args.max_turns} · timeout {hours}h")
    return 0


LIMIT_RE = re.compile(r"usage limit|hit your limit|limit reached|rate limit", re.IGNORECASE)


def last_event(stream: Path) -> dict | None:
    try:
        lines = [ln for ln in stream.read_text(errors="replace").splitlines() if ln.strip()]
    except OSError:
        return None
    for ln in reversed(lines):
        try:
            return json.loads(ln)
        except ValueError:
            continue
    return None


def how_it_ended(root: Path, td: str, k: int, code: int | None) -> str:
    tree = run_dir(root, td, k)
    if git(tree, "log", "-1", "--format=%s", check=False).strip() == RESULT_SUBJECT:
        return "result"
    if code == 124:
        return "timeout"
    ev = last_event(root / f"{td}.{k}.stream.jsonl") or {}
    if ev.get("type") == "result" and ev.get("subtype") == "error_max_turns":
        return "max-turns"
    text = json.dumps(ev.get("result") or ev.get("message") or ev.get("error") or "")
    if ev and LIMIT_RE.search(text):
        return "limit"
    record = tree / f"docs/reviews/{td}.md"
    if record.exists() and re.search(r"^\**Decided:?\**:? replay stopped", record.read_text(), re.MULTILINE):
        return "stopped"
    if code is not None and code > 128:
        return "signal"
    return "other"


def wait(args: argparse.Namespace) -> int:
    td, root = args.td, args.root
    ks = runs(root, td)
    k = ks[-1] if ks else None
    pidf = root / f"{td}.{k}.pid"
    if k is None or not pidf.exists():
        raise Refused(f"no started run of {td} under {root}")
    exitf, pid = root / f"{td}.{k}.exit", read_pid(pidf)
    while not exitf.exists() and pid and alive(pid):
        time.sleep(args.poll)
    code = None
    if exitf.exists():
        try:
            code = int(exitf.read_text().split()[0])
        except (ValueError, IndexError):
            code = None
    ended = how_it_ended(root, td, k, code)
    print(f"run {k} of {td}: {ended} · exit {code if code is not None else 'none (no exit file)'}")
    return 0 if ended == "result" else 1


# --- audit ---------------------------------------------------------------------------------------------------------

PATH_IN_TEXT_RE = re.compile(r"(?<![\w.:/~$-])(~(?:/[^\s'\"`;|&<>(){}]*)?|/[^\s'\"`;|&<>(){}]+)")
SEGMENT_SPLIT_RE = re.compile(r"\|\||&&|[;|&\n]|\$\(|`|\(|\)")
REMOTE_GIT = {"fetch", "pull", "push", "clone", "ls-remote", "remote", "submodule"}
WEB_TOOLS = {"WebFetch", "WebSearch"}
PATH_TOOLS = {"Read": "file_path", "Edit": "file_path", "Write": "file_path", "Glob": "path", "Grep": "path"}


def project_dir(config_dir: Path, tree: Path) -> Path:
    return config_dir / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(tree))


def under(path: str, place: Path | str) -> bool:
    place = os.path.normpath(str(place))
    return path == place or path.startswith(place.rstrip("/") + "/")


def norm(p: str, cwd: Path) -> str:
    p = os.path.expanduser(p)
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(cwd, p))


def command_flags(cmd: str, tree: Path) -> list[str]:
    out = []
    for seg in SEGMENT_SPLIT_RE.split(cmd):
        try:
            words = shlex.split(seg, comments=True)
        except ValueError:
            words = seg.split()
        while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
            words = words[1:]  # an assignment before the command
        while words and words[0] in {"sudo", "env", "timeout", "nohup", "exec", "command", "time"}:
            words = words[1:]
            while words and (words[0].startswith("-") or words[0].isdigit()):
                words = words[1:]
        if not words:
            continue
        w0 = os.path.basename(words[0])
        if w0 in {"ao", "gh"}:
            out.append(f"`{w0}` run")
        elif w0 == "agent-cadence":
            rest = [w for w in words[1:] if not w.startswith("-")]
            if "-C" in words[1:3]:
                rest = [w for w in words[words.index("-C") + 2 :] if not w.startswith("-")]
            if rest[:1] == ["hook"]:
                out.append("`agent-cadence hook` run")
            elif rest[:1] == ["run"] and (len(rest) < 2 or os.path.basename(rest[1]) not in LEDGER_SCRIPTS_ALLOWED):
                out.append(f"`agent-cadence run {rest[1] if len(rest) > 1 else ''}` run".replace(" `", "`"))
        elif w0 == "git":
            rest, i = words[1:], 0
            while i < len(rest) and rest[i].startswith("-"):
                if rest[i] == "-C" and i + 1 < len(rest):
                    if norm(rest[i + 1], tree) != os.path.normpath(str(tree)):
                        out.append(f"`git -C {rest[i + 1]}` on another path")
                    i += 2
                elif rest[i] == "-c" and i + 1 < len(rest):
                    i += 2
                else:
                    i += 1
            if i < len(rest) and rest[i] in REMOTE_GIT:
                out.append(f"remote `git {rest[i]}`")
    return out


def tool_uses(transcript: Path):
    for ln in transcript.read_text(errors="replace").splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        content = (ev.get("message") or {}).get("content") if isinstance(ev, dict) else None
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                yield ev.get("cwd"), c.get("name") or "", c.get("input") or {}


def audit(args: argparse.Namespace) -> int:
    td, k, root = args.td, args.k, args.root
    tree = run_dir(root, td, k)
    if not tree.is_dir():
        raise Refused(f"no run {k} of {td} under {root}")
    proj = project_dir(args.config_dir, tree)
    cadence = args.cadence_tree or ensure_pin(tree)
    venv = args.venv or main_checkout(source_top()) / ".venv"
    allowed = [tree, cadence, venv, root / f"{td}.{k}.tmp"]
    harmless = [*HARMLESS, str(proj)]

    def outside(p: str) -> bool:
        return not any(under(p, a) for a in allowed) and not any(under(p, h) for h in harmless)

    transcripts = sorted(proj.rglob("*.jsonl")) if proj.is_dir() else []
    flags: list[str] = []
    for t in transcripts:
        rel = t.relative_to(proj)
        for cwd, name, inp in tool_uses(t):
            here = Path(cwd) if cwd else tree
            if name in WEB_TOOLS:
                flags.append(f"{rel} · web tool `{name}`")
            elif name in PATH_TOOLS:
                raw = inp.get(PATH_TOOLS[name]) or (inp.get("pattern") if name == "Glob" else None)
                if raw and (name != "Glob" or inp.get(PATH_TOOLS[name]) or raw.startswith(("/", "~"))):
                    p = norm(raw, here)
                    if outside(p):
                        flags.append(f"{rel} · `{name}` of {raw} outside the allowed places")
            elif name == "Bash":
                cmd = str(inp.get("command") or "")
                for m in PATH_IN_TEXT_RE.finditer(cmd):
                    p = norm(m.group(1), here)
                    if outside(p):
                        flags.append(f"{rel} · Bash names {m.group(1)} outside the allowed places")
                flags += [f"{rel} · {f}" for f in command_flags(cmd, tree)]
    calls = root / f"{td}.{k}.run" / "calls.log"
    if calls.exists():
        flags += [f"stub · {ln.strip()}" for ln in calls.read_text().splitlines() if ln.strip()]
    print(f"design-replay audit · {td} run {k} · transcripts {len(transcripts)} · flags {len(flags)}")
    print("allowed: " + " · ".join(str(a) for a in allowed))
    print("never flagged: " + " · ".join(f"{h}/" for h in HARMLESS) + f" · Claude Code's own files under {proj}")
    print("cannot see: a path a script computes for itself")
    if not transcripts:
        print(f"no transcripts under {proj}")
    for f in flags:
        print(f"flag · {f}")
    return 1 if flags or not transcripts else 0


# --- main ----------------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=Path("~/replays").expanduser(), help="default ~/replays")
    ap.add_argument("--config-dir", type=Path, default=Path(CONFIG_DIR).expanduser(), help="the conformance profile")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="build the next run's cut-off tree")
    p.add_argument("td")
    p.add_argument("--script-from", help="take scripts/design_prep.py from this later commit")
    p.add_argument("--python", type=Path, help="the interpreter that runs design_prep.py (default the main .venv's)")
    p.add_argument("--created-at", help=argparse.SUPPRESS)  # tests: the first design PR's createdAt
    r = sub.add_parser("run", help="start the newest run, or --wait for it")
    r.add_argument("td")
    r.add_argument("--max-turns", type=int)
    r.add_argument("--wait", action="store_true", help="never start a run: wait for it and say how it ended")
    r.add_argument("--poll", type=float, default=POLL, help=argparse.SUPPRESS)
    a = sub.add_parser("audit", help="flag every step of run k outside its tree")
    a.add_argument("td")
    a.add_argument("k", type=int)
    a.add_argument("--cadence-tree", type=Path, help=argparse.SUPPRESS)
    a.add_argument("--venv", type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if not re.fullmatch(r"TD-\d+", args.td):
        ap.error(f"{args.td!r} is not TD-<n>")
    args.root = args.root.expanduser()
    args.config_dir = args.config_dir.expanduser()
    try:
        if args.cmd == "prepare":
            return prepare(args)
        if args.cmd == "run":
            return wait(args) if args.wait else start(args)
        return audit(args)
    except Refused as e:
        print(f"design-replay: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    sys.exit(main())
