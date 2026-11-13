"""The replay kit (design §4.9c *The trial of the new shape*, TD-1772): `prepare` on a scratch repository, the command
and environment `run` builds (never run), how `run --wait` names a run's end, and `audit` over fixture transcripts."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "design_replay.py"


def _load():
    spec = importlib.util.spec_from_file_location("design_replay", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["design_replay"] = mod
    spec.loader.exec_module(mod)
    return mod


dr = _load()

AGENTS = """# AGENTS.md

## First, every session

Run the hook before anything else:

    agent-cadence hook session-start

## How this repo works

The rules.
"""

SETTINGS = {
    "hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": "agent-cadence hook session-start"}]}],
        "PreToolUse": [{"hooks": [{"type": "command", "command": "guard"}]}],
    },
    "permissions": {"allow": []},
}

FLOWS = """# §4.9c Flows

**Before.** Not carried.

**What a design's author prepares before a review** (TD-1720). The author prepares.

**The checklist: fifteen questions.** The brief holds a list. The three are Paul's pick: TD-1557, TD-1569 and TD-1470,
of which only TD-1470's rows are in the file. No row of the replayed designs is drawn from.

**The gate: no reviewer reads a design the script has not passed at that commit.** It holds.

**The trial of the new shape** (TD-1722). Not carried.
"""

BRIEF = """# Designer brief

Draft against the checklist. TD-1569 showed why. Then run the script.

A paragraph naming nothing replayed.
"""

# The trial commit's pre-review script: it reads the scratch commit's prep file and says two tools could not run.
PREP_STUB = """import subprocess, sys
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
assert open("docs/reviews/TD-1.prep.yml").read().startswith("claims: []")
base = sys.argv[sys.argv.index("--base") + 1]
print(f"design-prep: ADVISORY · CANNOT RUN · TD-1 · {head[:12]} · base {base[:12]} · "
      "tests/test_history.py: no such file; tests/test_synopses.py: no such file")
"""

ENTRY = "## TD-1: The design\n\n**Status:** Open\n**Design PR:** #5, #9\n\n**Fix:** Design it.\n"


def _git(repo: Path, *args: str, date: str | None = None) -> str:
    env = dict(os.environ)
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = date
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env).stdout


def put(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)


@pytest.fixture
def src(tmp_path, monkeypatch):
    """A source repository: a base commit before the design PR opened, then the trial commit at `origin/main`."""
    for k, v in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }.items():
        monkeypatch.setenv(k, v)
    r = tmp_path / "src"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    put(
        r,
        {
            "AGENTS.md": AGENTS,
            ".claude/settings.json": json.dumps(SETTINGS),
            ".gitignore": "ignored.txt\n",
            "docs/ledger/TD-1.md": "## TD-1: The design\n\n**Status:** Open\n",
            "src/app.py": "x = 1\n",
        },
    )
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base", date="2026-11-01T00:00:00Z")
    put(
        r,
        {
            "docs/ledger/TD-1.md": ENTRY,
            "docs/briefs/designer-ao-1.md": BRIEF,
            "docs/design/4.9c-flows.md": FLOWS,
            "scripts/design_prep.py": PREP_STUB,
            "src/later.py": "y = 2\n",
        },
    )
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "after the design opened", date="2026-11-05T00:00:00Z")
    _git(r, "update-ref", "refs/remotes/origin/main", "HEAD")
    monkeypatch.chdir(r)
    # the launcher: the pin's tree, `ledger.py new --id` refused (no origin), `ledger.py note` taken
    ac = tmp_path / "ac"
    (ac / "files/scripts").mkdir(parents=True)
    stub = tmp_path / "agent-cadence"
    stub.write_text(
        "#!/bin/sh\n"
        f'case "$*" in *" path "*) echo {ac}/files/scripts/ledger.py;;\n'
        '  *"ledger.py new"*) echo "ledger.py: no origin to take an id from" >&2; exit 1;;\n'
        "  *) exit 0;;\nesac\n"
    )
    stub.chmod(0o755)
    monkeypatch.setattr(dr, "CADENCE", [str(stub)])
    return r


def prepare(tmp_path, *extra: str) -> tuple[int, list[str]]:
    root = tmp_path / "replays"
    args = ["--root", str(root), "prepare", "TD-1", "--python", sys.executable, "--created-at", "2026-11-03T00:00:00Z"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dr.main([*args, *extra])
    return code, buf.getvalue().strip().split("\n")


def test_prepare_builds_run_1_then_run_2(src, tmp_path):
    code, out = prepare(tmp_path)
    assert code == 0, out
    root = tmp_path / "replays"
    trial = _git(src, "rev-parse", "origin/main").strip()
    base = _git(src, "rev-parse", "origin/main~1").strip()
    assert out[0] == f"trial {trial}" and out[1] == f"base {base}"
    assert (root / "trial").read_text().split()[0] == trial
    t1 = root / "TD-1.1"
    assert (root / "TD-1.1.tmp").is_dir()
    # two commits, no remote: the base's files as the root commit, then the overlay
    log = _git(t1, "log", "--format=%s").strip().split("\n")
    assert len(log) == 2 and log[0] == dr.OVERLAY_SUBJECT and log[1].startswith("replay base")
    assert _git(t1, "remote").strip() == ""
    root_files = set(_git(t1, "ls-tree", "-r", "--name-only", "HEAD~1").split())
    assert root_files == set(_git(src, "ls-tree", "-r", "--name-only", base).split())
    assert "src/later.py" not in root_files  # nothing after the base
    assert out[2] == f"overlay {_git(t1, 'rev-parse', 'HEAD').strip()}"
    overlay = set(_git(t1, "diff", "--name-only", "HEAD~1", "HEAD").split())
    assert overlay == {"AGENTS.md", ".claude/settings.json", "REPLAY.md", "scripts/design_prep.py"}
    assert (t1 / "scripts/design_prep.py").read_text() == PREP_STUB
    settings = json.loads((t1 / ".claude/settings.json").read_text())
    assert "SessionStart" not in settings["hooks"] and "PreToolUse" in settings["hooks"]
    agents = (t1 / "AGENTS.md").read_text()
    assert "agent-cadence hook session-start" not in agents and dr.AGENTS_LINE in agents
    assert "## How this repo works" in agents
    replay = (t1 / "REPLAY.md").read_text()
    assert replay.startswith("# Replay of TD-1 (TD-1722)") and f"at the base `{base[:12]}`" in replay
    # the probe's causes and the ledger's refusal are written in; the scratch commit is gone
    assert "- tests/test_history.py: no such file\n- tests/test_synopses.py: no such file\n" in replay
    assert "`ledger.py new --id TD-9001` refuses (ledger.py: no origin to take an id from)" in replay
    assert "`ledger.py note TD-1`" not in replay
    assert not (t1 / "docs/reviews").exists() and _git(t1, "status", "--porcelain") == ""
    # the brief less its sentence naming a replayed design; §4.9c's span, its checklist less theirs
    assert "Draft against the checklist. Then run the script." in replay and "TD-1569 showed" not in replay
    assert "**What a design's author prepares before a review**" in replay and "It holds." in replay
    assert "No row of the replayed designs is drawn from." in replay
    assert "Paul's pick" not in replay and "Not carried" not in replay
    code, out = prepare(tmp_path)
    assert code == 0 and out[-1].startswith("run 2 ")
    assert (root / "TD-1.2/REPLAY.md").exists() and (root / "TD-1.1/REPLAY.md").exists()
    assert (root / "trial").read_text().split()[0] == trial  # one trial commit for every run


def test_prepare_takes_the_script_from_a_later_commit(src, tmp_path):
    put(src, {"scripts/design_prep.py": PREP_STUB + "# fixed\n"})
    _git(src, "commit", "-qam", "fix the tool")
    fix = _git(src, "rev-parse", "HEAD").strip()
    _git(src, "reset", "-q", "--hard", "HEAD~1")
    _git(src, "update-ref", "refs/fix", fix)
    code, out = prepare(tmp_path, "--script-from", fix)
    assert code == 0, out
    root = tmp_path / "replays"
    assert (root / "TD-1.1/scripts/design_prep.py").read_text().endswith("# fixed\n")
    assert f"script-from {fix} TD-1.1" in (root / "trial").read_text()


def test_prepare_stops_when_the_script_cannot_start(src, tmp_path, capsys):
    put(src, {"scripts/design_prep.py": "raise SystemExit('boom')\n"})
    _git(src, "commit", "-qam", "break it")
    _git(src, "update-ref", "refs/remotes/origin/main", "HEAD")
    code = dr.main(
        ["--root", str(tmp_path / "r"), "prepare", "TD-1", "--python", sys.executable, "--created-at", "2026-11-03"]
    )
    assert code == 2 and "design_prep.py cannot start" in capsys.readouterr().err


def test_run_builds_the_command_and_environment(tmp_path):
    env = {"PATH": "/usr/bin", "SHIFTLEAD_SESSION": "x", "SHIFTLEAD_HOME": "/h", "HOME": "/home/u"}
    argv, out = dr.run_command("TD-1", 2, tmp_path, 300, 24, Path("/c/.claude-conformance"), env)
    assert argv[:3] == ["setsid", "sh", "-c"]
    inner = argv[3]
    assert inner.startswith("timeout 86400 claude -p --model claude-opus-5-5 --max-turns 300 ")
    for part in (
        "--permission-mode bypassPermissions",
        "--setting-sources project",
        "--output-format stream-json",
        f"< {tmp_path}/TD-1.2/REPLAY.md",
        f"> {tmp_path}/TD-1.2.stream.jsonl",
        f"echo $? > {tmp_path}/TD-1.2.exit",
    ):
        assert part in inner
    assert not any(k.startswith("SHIFTLEAD_") for k in out)
    assert out["CLAUDE_CONFIG_DIR"] == "/c/.claude-conformance" and out["TMPDIR"] == f"{tmp_path}/TD-1.2.tmp"
    assert out["PATH"] == f"{tmp_path}/TD-1.2.run/bin:/usr/bin" and out["HOME"] == "/home/u"


def test_run_starts_the_newest_run_detached(src, tmp_path, monkeypatch, capsys):
    root = tmp_path / "replays"
    assert prepare(tmp_path)[0] == 0
    put(src, {"docs/reviews/TD-1.md": "".join(f"| R{i} | {i} | design | f | 1 | d |\n" for i in range(1, 8))})
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "record")
    (root / "trial").write_text(_git(src, "rev-parse", "HEAD"))
    seen = {}

    def spawn(argv, cwd, env):
        seen.update(argv=argv, cwd=cwd, env=env)
        return 4242

    monkeypatch.setattr(dr, "spawn", spawn)
    assert dr.main(["--root", str(root), "run", "TD-1"]) == 2
    assert "--max-turns" in capsys.readouterr().err
    assert dr.main(["--root", str(root), "run", "TD-1", "--max-turns", "50"]) == 0
    assert (root / "TD-1.1.pid").read_text().strip() == "4242"
    assert seen["cwd"] == root / "TD-1.1" and seen["env"]["CLAUDE_CONFIG_DIR"].endswith(".claude-conformance")
    assert "timeout 259200 " in seen["argv"][3]  # seven rounds: the long bound
    stub = root / "TD-1.1.run/bin/ao"
    r = subprocess.run([str(stub), "status", "--json"], capture_output=True, text=True)
    assert r.returncode == 2 and "ao status --json" in (root / "TD-1.1.run/calls.log").read_text()
    assert dr.main(["--root", str(root), "run", "TD-1", "--max-turns", "50"]) == 2  # started already
    assert prepare(tmp_path)[0] == 0
    (root / "TD-1.1.pid").write_text(f"{os.getpid()}\n")  # a replay still alive
    assert dr.main(["--root", str(root), "run", "TD-1", "--max-turns", "50"]) == 2
    assert "a replay is running: TD-1.1" in capsys.readouterr().err


def _run(tmp_path, k=1) -> Path:
    tree = tmp_path / f"TD-1.{k}"
    tree.mkdir(parents=True)
    _git(tree, "init", "-q")
    _git(tree, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", dr.OVERLAY_SUBJECT)
    (tmp_path / f"TD-1.{k}.pid").write_text("999999999\n")  # a pid that is not running
    return tree


def wait(tmp_path, capsys) -> tuple[int, str]:
    code = dr.main(["--root", str(tmp_path), "run", "TD-1", "--wait", "--poll", "0.01"])
    return code, capsys.readouterr().out


@pytest.mark.parametrize(
    "exit_code,stream,record,want",
    [
        ("124", None, None, "timeout"),
        ("1", {"type": "result", "subtype": "error_max_turns"}, None, "max-turns"),
        ("1", {"type": "result", "is_error": True, "result": "Claude AI usage limit reached|17000"}, None, "limit"),
        ("0", {"type": "result", "subtype": "success"}, "**Decided:** replay stopped — the line\n", "stopped"),
        ("143", None, None, "signal"),
        ("0", {"type": "result", "subtype": "success"}, None, "other"),
        (None, None, None, "other"),
    ],
)
def test_wait_names_how_a_run_ended(tmp_path, capsys, exit_code, stream, record, want):
    tree = _run(tmp_path)
    if exit_code is not None:
        (tmp_path / "TD-1.1.exit").write_text(exit_code + "\n")
    if stream:
        (tmp_path / "TD-1.1.stream.jsonl").write_text('{"type": "system"}\n' + json.dumps(stream) + "\n")
    if record:
        put(tree, {"docs/reviews/TD-1.md": "# Review record: TD-1\n\n" + record})
    code, out = wait(tmp_path, capsys)
    assert code == 1 and f"run 1 of TD-1: {want} ·" in out


def test_wait_exits_0_on_a_result(tmp_path, capsys):
    tree = _run(tmp_path)
    _git(tree, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", dr.RESULT_SUBJECT)
    (tmp_path / "TD-1.1.exit").write_text("0\n")
    code, out = wait(tmp_path, capsys)
    assert code == 0 and "run 1 of TD-1: result · exit 0" in out


def _use(name: str, **inp) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def audit(tmp_path, capsys, events: dict[str, list[dict]], calls: str | None = None) -> tuple[int, list[str]]:
    root = tmp_path / "replays"
    tree = root / "TD-1.1"
    tree.mkdir(parents=True, exist_ok=True)
    cfg = tmp_path / "cfg"
    proj = dr.project_dir(cfg, tree)
    for rel, evs in events.items():
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text("\n".join(json.dumps({"cwd": str(tree), **e}) for e in evs) + "\n")
    if calls:
        (root / "TD-1.1.run").mkdir(parents=True, exist_ok=True)
        (root / "TD-1.1.run/calls.log").write_text(calls)
    code = dr.main(
        [
            "--root",
            str(root),
            "--config-dir",
            str(cfg),
            "audit",
            "TD-1",
            "1",
            "--cadence-tree",
            str(tmp_path / "ac"),
            "--venv",
            str(tmp_path / "main/.venv"),
        ]
    )
    return code, capsys.readouterr().out.strip().split("\n")


def test_audit_passes_a_clean_run(tmp_path, capsys):
    tree = tmp_path / "replays/TD-1.1"
    clean = [
        _use("Read", file_path=f"{tree}/docs/design.md"),
        _use("Edit", file_path=f"{tree}/docs/design/4.9c-flows.md"),
        _use("Grep", pattern="gate", path=str(tmp_path / "ac/docs")),
        _use("Glob", pattern="docs/**/*.md"),
        _use("Bash", command=f"{tmp_path}/main/.venv/bin/python scripts/design_prep.py --entry TD-1 --base abc"),
        _use("Bash", command="agent-cadence run ledger.py note TD-1 'x' && git log -1 && ls /usr/bin /dev/null"),
        _use("Bash", command=f"cat {tmp_path}/replays/TD-1.1.tmp/out.txt | head; git -C {tree} status"),
        _use("Bash", command=f"cat {tmp_path}/cfg/projects/{dr.project_dir(Path('/'), tree).name}/s.jsonl"),
    ]
    code, out = audit(tmp_path, capsys, {"s.jsonl": clean, "s/subagents/agent-a.jsonl": clean})
    assert code == 0, out
    assert out[0].startswith("design-replay audit · TD-1 run 1 · transcripts 2 · flags 0")
    assert any(ln.startswith("never flagged: /dev/ · /usr/ · /bin/ · /lib/") for ln in out)
    assert "cannot see: a path a script computes for itself" in out


def test_audit_flags_each_forbidden_step(tmp_path, capsys):
    dirty = [
        _use("Read", file_path="/etc/passwd"),
        _use("Write", file_path="~/notes.md"),
        _use("Glob", pattern="/home/kmaster/shiftlead/docs/*.md"),
        _use("Bash", command="ao status --json"),
        _use("Bash", command="cd x && gh pr list"),
        _use("Bash", command="agent-cadence hook session-start"),
        _use("Bash", command="agent-cadence run precheck.py --pr 1"),
        _use("Bash", command="git fetch origin"),
        _use("Bash", command="git -C /other/repo log"),
        _use("Bash", command="cat ~/.shiftlead/home.yml"),
        _use("WebFetch", url="https://example.com"),
    ]
    code, out = audit(tmp_path, capsys, {"s/subagents/agent-b.jsonl": dirty}, calls="2026-11-13T00:00:00Z gh pr view\n")
    flags = [ln for ln in out if ln.startswith("flag · ")]
    assert code == 1
    body = "\n".join(flags)
    for want in (
        "`Read` of /etc/passwd",
        "`Write` of ~/notes.md",
        "`Glob` of /home/kmaster/shiftlead/docs/*.md",
        "`ao` run",
        "`gh` run",
        "`agent-cadence hook` run",
        "`agent-cadence run precheck.py` run",
        "remote `git fetch`",
        "`git -C /other/repo` on another path",
        "Bash names /other/repo",
        "Bash names ~/.shiftlead/home.yml",
        "web tool `WebFetch`",
        "stub · 2026-11-13T00:00:00Z gh pr view",
    ):
        assert want in body, want
    assert all("s/subagents/agent-b.jsonl" in f for f in flags if "stub ·" not in f)


def test_audit_with_no_transcripts_is_no_pass(tmp_path, capsys):
    code, out = audit(tmp_path, capsys, {})
    assert code == 1 and any(ln.startswith("no transcripts under") for ln in out)


def test_names_replayed_needs_the_whole_id():
    assert dr.names_replayed("see TD-1557's rows") and not dr.names_replayed("TD-15570 and TD-155")
