"""TD-1023 (design §4.2, §4.3 *A repo's start hooks are every adapter's to run*): the layer's SessionStart
line is dev-cadence's pinned seed, byte for byte, with two modes — in a repo whose main checkout's
`docs/cadence.toml` has a `[dev-cadence]` header it runs `dev-cadence hook session-start` from `PATH`, else
the copied runner — and Gemini's start hooks follow it; a pinned repo carrying a pre-pin line gets the
layer's line beside its own, and either past vintage still counts as the repo's line."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from sessionorc import cadence
from shiftlead import doctor
from shiftlead.adapters.claude_code import (
    CADENCE_HOOK_LINE,
    CADENCE_HOOK_LINES_PAST,
    CADENCE_HOOK_TIMEOUT,
    repo_wires_cadence,
)
from shiftlead.adapters.gemini import hook

DEV_CADENCE = Path(os.environ.get("DEV_CADENCE_SOURCE", "~/dev-cadence")).expanduser()
PIN = '[dev-cadence]  # the pin\nsource = "https://example.invalid/dev-cadence.git"\nref = "abc"\n'
# the stub launcher: records its argv, cwd and stdin, prints a line, and exits with the code in `rc`
STUB = """#!/bin/sh
here=$(dirname "$0")
printf '%s\\n' "$*" > "$here/argv"
pwd > "$here/cwd"
cat > "$here/stdin"
[ -f "$here/sleep" ] && sleep "$(cat "$here/sleep")"
echo "hooked by the pin"
exit "$(cat "$here/rc" 2>/dev/null || echo 0)"
"""
GIT = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]


def _pinned(d: Path) -> Path:
    (d / "docs").mkdir(parents=True, exist_ok=True)
    (d / "docs" / "cadence.toml").write_text(PIN)
    return d


def _stub(tmp_path: Path, rc: int = 0) -> Path:
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "dev-cadence").write_text(STUB)
    (bin_ / "dev-cadence").chmod(0o755)
    (bin_ / "rc").write_text(str(rc))
    return bin_


def _line(project: Path, path: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "PATH": path}
    return subprocess.run(["sh", "-c", CADENCE_HOOK_LINE], env=env, capture_output=True, text=True, timeout=30)


def _settings(d: Path, commands: list[str]) -> None:
    (d / ".claude").mkdir(parents=True, exist_ok=True)
    hooks = [{"type": "command", "command": c, "timeout": 20} for c in commands]
    (d / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": hooks}]}}))


def test_hook_pinned_reads_the_header_as_the_lines_grep_does(tmp_path):
    plain = tmp_path / "plain"  # no git: the directory itself, as the line's `${r:-…}` falls back
    plain.mkdir()
    assert cadence.hook_pinned(plain) is False  # no file
    assert cadence.hook_pinned(_pinned(plain)) is True
    (plain / "docs" / "cadence.toml").write_text("[other]\nx = 1\n[dev-cadence.extra]\n# [dev-cadence]\n")
    assert cadence.hook_pinned(plain) is False  # another table, a sub-table, a comment
    (plain / "docs" / "cadence.toml").write_text("x = 1\n \t[dev-cadence]\t# pinned\n")
    assert cadence.hook_pinned(plain) is True
    (plain / "docs" / "cadence.toml").unlink()
    (plain / "docs" / "cadence.toml").mkdir()  # unreadable as a file
    assert cadence.hook_pinned(plain) is False


def test_hook_pinned_reads_the_main_checkout_not_the_worktrees_branch(tmp_path):
    main = tmp_path / "repo"
    subprocess.run([*GIT, "init", "-q", str(main)], check=True)
    subprocess.run([*GIT, "-C", str(main), "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    wt = tmp_path / "wt"
    subprocess.run([*GIT, "-C", str(main), "worktree", "add", "-q", "--detach", str(wt)], check=True)
    assert cadence.hook_pinned(wt) is False
    _pinned(main)  # the main checkout has the header, the worktree's branch has no docs/cadence.toml
    assert not (wt / "docs" / "cadence.toml").exists()
    assert cadence.hook_pinned(wt) is True and cadence.hook_pinned(main) is True
    # a repo pinned while it still holds its lock is hook-pinned, though the readers' `pinned` reads its copy
    (main / "docs" / "cadence-sync.lock").write_text("{}")
    assert cadence.hook_pinned(main) is True and cadence.pinned(main) is False


def test_the_layers_line_runs_the_launcher_in_a_pinned_repo(tmp_path):
    repo = _pinned(tmp_path / "repo")
    bin_ = _stub(tmp_path)
    path = f"{bin_}:/usr/bin:/bin"
    done = _line(repo, path)
    assert (done.returncode, done.stdout) == (0, "hooked by the pin\n")
    assert (bin_ / "argv").read_text().strip() == "hook session-start"
    assert (bin_ / "cwd").read_text().strip() == str(repo)  # in the session directory
    (bin_ / "rc").write_text("2")  # the launcher could not run the pin: it said why, then the line says so
    done = _line(repo, path)
    assert done.stdout == f"hooked by the pin\n{hook.PIN_FAILED}\n"
    (bin_ / "rc").write_text("3")  # any other exit: the launcher's own words and its exit, nothing added
    done = _line(repo, path)
    assert (done.returncode, done.stdout) == (3, "hooked by the pin\n")
    done = _line(repo, "/usr/bin:/bin")  # no launcher on PATH: the install line, never a silent nothing
    assert done.stdout == f"{hook.NO_LAUNCHER}\n"


def test_the_layers_line_runs_the_copied_runner_in_an_unpinned_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    runner = repo / "scripts" / "cadence_hooks.sh"
    runner.write_text('#!/bin/sh\necho "the runner $1"\n')
    runner.chmod(0o755)
    bin_ = _stub(tmp_path)
    done = _line(repo, f"{bin_}:/usr/bin:/bin")
    assert done.stdout == "the runner --session-start\n"
    assert not (bin_ / "argv").exists()  # the launcher is not asked


def _start(project: Path, monkeypatch) -> str:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    return hook.start_hooks({"hook_event_name": "SessionStart", "source": "startup", "cwd": str(project)})


def test_geminis_start_hooks_follow_the_pin(tmp_path, monkeypatch):
    repo = _pinned(tmp_path / "repo")
    bin_ = _stub(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_}:/usr/bin:/bin")
    assert _start(repo, monkeypatch) == "hooked by the pin\n"
    assert (bin_ / "argv").read_text().strip() == "hook session-start"
    assert (bin_ / "cwd").read_text().strip() == str(repo)
    assert json.loads((bin_ / "stdin").read_text())["hook_event_name"] == "SessionStart"  # the payload passed on
    (bin_ / "rc").write_text("2")
    assert _start(repo, monkeypatch) == f"hooked by the pin\n{hook.PIN_FAILED}"
    (bin_ / "rc").write_text("3")
    assert _start(repo, monkeypatch) == "hooked by the pin\n"
    (bin_ / "rc").write_text("0")
    (bin_ / "sleep").write_text("5")  # a first fetch past the bound: the line's sentence, never ""
    monkeypatch.setattr(hook, "START_HOOKS_TIMEOUT", 0.5)
    assert _start(repo, monkeypatch) == hook.PIN_FAILED
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert _start(repo, monkeypatch) == hook.NO_LAUNCHER


@pytest.mark.unit
def test_geminis_sentences_are_the_lines():
    assert hook.PIN_FAILED in CADENCE_HOOK_LINE and hook.NO_LAUNCHER in CADENCE_HOOK_LINE
    assert " ".join(hook.PINNED_HOOK) in CADENCE_HOOK_LINE


def test_a_pinned_repo_carrying_a_pre_pin_line_gets_the_layers_line_beside_it(tmp_path):
    repo = _pinned(tmp_path / "repo")
    _settings(repo, [CADENCE_HOOK_LINES_PAST[0]])
    assert repo_wires_cadence(repo) is False
    _settings(repo, [CADENCE_HOOK_LINE])
    assert repo_wires_cadence(repo) is True
    unpinned = tmp_path / "unpinned"
    _settings(unpinned, [CADENCE_HOOK_LINES_PAST[0]])
    assert repo_wires_cadence(unpinned) is True  # a copied repo's line of either vintage still runs its runner


@pytest.mark.unit
def test_either_past_vintage_is_the_repos_line():
    words = "no SessionStart line: a session started outside ShiftLead misses the cadence's nudge"
    base = {"serve": {"ok": True, "lacks": []}, "warnings": [], "source": False}
    for line in (CADENCE_HOOK_LINE, *CADENCE_HOOK_LINES_PAST):
        assert doctor.missing_seams({**base, "session_start": [line]}) == []
    assert doctor.missing_seams({**base, "session_start": ["echo hi"]}) == [words]


def _seed(ref: str, path: str = "files/.claude/settings.json") -> dict:
    done = subprocess.run(
        ["git", "-C", str(DEV_CADENCE), "show", f"{ref}:{path}"], capture_output=True, text=True, timeout=30
    )
    if done.returncode != 0:
        pytest.skip(f"no {ref}:{path} in the dev-cadence checkout ({done.stderr.strip()[:80]})")
    return json.loads(done.stdout)["hooks"]["SessionStart"][0]["hooks"][0]


@pytest.mark.skipif(not (DEV_CADENCE / "launcher" / "INTERFACE").is_file(), reason="no dev-cadence checkout")
def test_the_line_is_dev_cadences_seed_at_origin_head():
    seed = _seed("origin/HEAD")
    assert seed["command"] == CADENCE_HOOK_LINE and seed["timeout"] == CADENCE_HOOK_TIMEOUT
    assert hook.PIN_FAILED in seed["command"] and hook.NO_LAUNCHER in seed["command"]
    # dev-cadence's own settings run its runner under `files/`, as `doctor._hook_lines` makes the line
    own = _seed("origin/HEAD", ".claude/settings.json")["command"]
    assert own == CADENCE_HOOK_LINE.replace("/scripts/cadence_hooks.sh", "/files/scripts/cadence_hooks.sh")
    # `hook_pinned`'s header is the launcher's
    words = subprocess.run(
        ["git", "-C", str(DEV_CADENCE), "show", "origin/HEAD:launcher/words.py"], capture_output=True, text=True
    ).stdout
    theirs = re.search(r'^PIN_HEADER_RE = re\.compile\(r"(.*)", re\.M\)', words, re.M)
    assert theirs and theirs.group(1) == cadence.PIN_HEADER_RE.pattern


@pytest.mark.skipif(not (DEV_CADENCE / "launcher" / "INTERFACE").is_file(), reason="no dev-cadence checkout")
def test_the_past_vintages_are_dev_cadences_earlier_seeds():
    assert tuple(_seed(ref)["command"] for ref in ("4316bd4", "267cae5")) == CADENCE_HOOK_LINES_PAST
