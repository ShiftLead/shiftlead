"""TD-1024 (design §5 *The seams*, §4.2 the line's two modes): the repo reading carries `hook_pinned`, and
the Repo page's words follow it — a pinned repo's per-clone cures name the launcher, not `sync.sh`; its
SessionStart line of a past vintage *predates the pin*; a line no vintage matches but naming dev-cadence's
runner or launcher is *not one this build knows*; and dev-cadence's source still reads as its source once
`sync.sh` retires (`launcher/INTERFACE`)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from sessionorc import cadence, gitinfo, seams, workorders
from shiftlead import doctor
from shiftlead.adapters.claude_code import CADENCE_HOOK_LINE, CADENCE_HOOK_LINES_PAST

pytestmark = pytest.mark.unit

LEDGER = "# Technical debt\n\n## TD-001: One thing\n\n**Priority:** Low\n**Status:** Open.\n\n---\n"
PIN = f'[dev-cadence]\nsource = "https://example.invalid/dev-cadence.git"\nref = "{"a" * 40}"\n'
DEV_CADENCE = Path(os.environ.get("DEV_CADENCE_SOURCE", "~/dev-cadence")).expanduser()
OLD_SHIM = f'#!/bin/sh\n# {seams.SHIM_MARKER} — written by scripts/install_git_hooks.sh\nexec "$hook"\n'
NEW_SHIM = (
    f"#!/usr/bin/env bash\n# {seams.SHIM_MARKER} — written by scripts/install_git_hooks.sh\n"
    'if grep -qsE \'^\\[dev-cadence\\]\' x; then dev-cadence hook "${0##*/}" "$@"; fi\n'
)
UNKNOWN = doctor.UNKNOWN_SESSION_START
NO_LINE = doctor.NO_SESSION_START


def _repo(tmp_path: Path, pinned: bool, name: str = "notes") -> Path:
    """A served checkout with a board and a worktree setup, so only the per-clone and SessionStart words
    are said: pinned (`docs/cadence.toml`'s `[dev-cadence]`, the gate stood for by a resolved reading) or
    on the copy (the lock)."""
    root = tmp_path / name
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "technical_debt.md").write_text(LEDGER)
    (root / workorders.BOARD).write_text("# Board\n")
    (root / "scripts").mkdir()
    (root / cadence.SCRIPT).write_text("")
    hydrate = root / gitinfo.HYDRATE
    hydrate.write_text("#!/bin/sh\n")
    hydrate.chmod(0o755)
    if pinned:
        (root / "docs" / "cadence.toml").write_text(PIN)
    else:
        (root / "docs" / "cadence-sync.lock").write_text("source: x\ncommit: abc\nfiles_commit: abc123\n")
    (root / ".git" / "hooks").mkdir(parents=True)
    return root


def _settings(root: Path, *commands: str) -> None:
    (root / ".claude").mkdir(exist_ok=True)
    hooks = [{"type": "command", "command": c, "timeout": 20} for c in commands]
    (root / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": hooks}]}}))


@pytest.fixture
def roster(tmp_path, monkeypatch):
    path = tmp_path / "config" / "dev-cadence" / "repos.txt"
    path.parent.mkdir(parents=True)
    path.write_text("/elsewhere\n")
    monkeypatch.setattr(seams.hosts, "DEV_CADENCE_ROSTER", str(path))
    monkeypatch.setattr(seams, "descends", lambda *a: (True, None))
    # a pinned repo is served by its resolved tree; these tests read the words, not the resolver
    monkeypatch.setattr(seams, "serve", lambda *a, **k: {"ok": True, "lacks": []})
    monkeypatch.setattr(seams, "ledgerboard", lambda root: None)  # nor the ledgerboard's release
    return path


def _said(root: Path) -> list[str]:
    return doctor.missing_seams(seams.reading(root), root)


def test_a_pinned_repo_with_the_current_line_the_td129_shim_and_a_roster_line_warns_nothing(tmp_path, roster):
    root = _repo(tmp_path, pinned=True)
    _settings(root, CADENCE_HOOK_LINE)
    (root / ".git" / "hooks" / "pre-push").write_text(NEW_SHIM)
    roster.write_text(f"{root.resolve()}\n")
    got = seams.reading(root)
    assert got["hook_pinned"] is True
    assert _said(root) == []
    assert not [w for w in _said(root) if "sync.sh" in w or "sync-all" in w or w == NO_LINE]


def test_a_pinned_repos_pre_pin_line_shim_and_missing_roster_line_each_get_the_launchers_cure(tmp_path, roster):
    root = _repo(tmp_path, pinned=True)
    _settings(root, CADENCE_HOOK_LINES_PAST[0])
    (root / ".git" / "hooks" / "pre-push").write_text(OLD_SHIM)
    assert _said(root) == [
        f"dev-cadence's per-clone setup not run in this checkout — `dev-cadence -C {root} run install_git_hooks.sh`",
        f"not on dev-cadence's roster: its gc may remove the tree this repo pins — "
        f"`dev-cadence -C <dev-cadence> adopt {root}`",
        "SessionStart line predates the pin: a session started outside ShiftLead runs no cadence hook"
        f" — copy the line from `dev-cadence -C {root} path .claude/settings.json`",
    ]
    # the 2026-09-25 line beside the current one is the line: nothing predates the pin
    _settings(root, CADENCE_HOOK_LINES_PAST[0], CADENCE_HOOK_LINE)
    assert not [w for w in _said(root) if "predates the pin" in w]
    # no `.git` to read: the shim is not said, as on the copy
    assert seams.shimmed(tmp_path / "nowhere", pinned=True) is None


def test_an_unpinned_repo_keeps_todays_three_words(tmp_path, roster):
    root = _repo(tmp_path, pinned=False)
    _settings(root, CADENCE_HOOK_LINES_PAST[0])
    assert seams.reading(root)["hook_pinned"] is False
    assert _said(root) == [
        f"dev-cadence's per-clone setup not run in this checkout — `<dev-cadence>/sync.sh --pin {root}`",
        f"not on dev-cadence's roster: the copy is retired, so move it to a pin — `<dev-cadence>/sync.sh --pin {root}`",
    ], "a past vintage on the copy is the line"
    (root / ".git" / "hooks" / "pre-push").write_text(OLD_SHIM)
    roster.write_text(f"{root.resolve()}\n")
    _settings(root, "echo hi")
    assert _said(root) == [NO_LINE]


def test_a_line_one_byte_off_is_not_one_this_build_knows_and_beside_the_current_line_says_nothing():
    base = {"warnings": [], "source": False, "hook_pinned": False}
    off = CADENCE_HOOK_LINE.replace("--session-start", "--session-starts")
    assert off != CADENCE_HOOK_LINE
    assert doctor.missing_seams({**base, "session_start": [off]}) == [UNKNOWN]
    assert doctor.missing_seams({**base, "session_start": [off, CADENCE_HOOK_LINE]}) == []
    assert doctor.missing_seams({**base, "session_start": ["(cd x && dev-cadence hook session-start)"]}) == [UNKNOWN]
    assert doctor.missing_seams({**base, "session_start": ["echo hi"]}) == [NO_LINE]
    assert doctor.missing_seams({**base, "session_start": []}) == [NO_LINE]
    # pinned, the same: a line it does not know is not also *predates the pin*
    assert doctor.missing_seams({**base, "hook_pinned": True, "session_start": [off]}) == [UNKNOWN]


def test_a_reading_without_hook_pinned_reads_unpinned():
    """An older host agent's reading carries no `hook_pinned`: today's words, never *predates the pin*."""
    older = {"warnings": [], "source": False, "session_start": [CADENCE_HOOK_LINES_PAST[0]]}
    assert doctor.missing_seams(older) == []
    assert doctor.missing_seams({**older, "hook_pinned": True}) == [
        doctor.PRE_PIN_SESSION_START.format(root="<checkout>")
    ]


def _shim_at(tmp_path: Path, ref: str) -> str:
    """The pre-push shim dev-cadence's `install_git_hooks.sh` at `ref` writes into a fresh clone."""
    done = subprocess.run(
        ["git", "-C", str(DEV_CADENCE), "archive", ref, "files/scripts"], capture_output=True, timeout=60
    )
    if done.returncode != 0:
        pytest.skip(f"no {ref} in the dev-cadence checkout")
    repo = tmp_path / f"at-{ref}"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as tar:
        tar.extractall(repo, filter="data")
    (repo / "files" / "scripts").rename(repo / "scripts")
    subprocess.run(
        ["bash", str(repo / "scripts" / "install_git_hooks.sh"), str(repo)],
        check=True,
        capture_output=True,
        timeout=60,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
    )
    return (repo / ".git" / "hooks" / "pre-push").read_text()


@pytest.mark.skipif(not (DEV_CADENCE / "launcher" / "INTERFACE").is_file(), reason="no dev-cadence checkout")
def test_dev_cadences_pre_pin_shim_warns_in_a_pinned_repo_and_its_td129_shim_does_not(tmp_path, roster):
    root = _repo(tmp_path, pinned=True)
    words = f"dev-cadence's per-clone setup not run in this checkout — `dev-cadence -C {root} run install_git_hooks.sh`"
    for ref, warned in (("2cc2b88", True), ("ddd2f99", False)):
        shim = _shim_at(tmp_path, ref)
        assert seams.SHIM_MARKER in shim
        (root / ".git" / "hooks" / "pre-push").write_text(shim)
        assert (words in seams.reading(root)["warnings"]) is warned, ref


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def test_dev_cadences_source_with_launcher_interface_and_no_sync_sh_is_its_source(tmp_path, monkeypatch):
    """§5 *The seams*: `files/` beside `sync.sh` or, once that retires, `launcher/INTERFACE` — and the roster's
    dev-cadence checkout `seams.descends` reads the age in is found by the same test."""
    src = tmp_path / "dev-cadence"
    (src / "files").mkdir(parents=True)
    (src / "launcher").mkdir()
    assert cadence.is_source(src) is False
    (src / "launcher" / "INTERFACE").write_text("1\n")
    assert cadence.is_source(src) is True
    _git(tmp_path, "init", "-q", "-b", "main", str(src))
    shas = []
    for n in range(2):
        (src / "files" / "n").write_text(f"{n}\n")
        _git(src, "add", "-A")
        _git(src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"c{n}")
        shas.append(_git(src, "rev-parse", "HEAD"))
    monkeypatch.setattr(cadence, "OLDEST", shas[0])
    assert seams.descends(shas[1], [tmp_path / "elsewhere", src]) == (True, None)
    (src / "files" / "n").unlink()
    (src / "files").rmdir()
    assert cadence.is_source(src) is False, "`files/` is still the mark"


def _source(tmp_path: Path, name: str, commits: int) -> tuple[Path, list[str]]:
    src = tmp_path / name
    (src / "launcher").mkdir(parents=True)
    (src / "launcher" / "INTERFACE").write_text("1\n")
    _git(tmp_path, "init", "-q", "-b", "main", str(src))
    shas = []
    for n in range(commits):
        (src / "files").mkdir(exist_ok=True)
        (src / "files" / "n").write_text(f"{name} {n}\n")
        _git(src, "add", "-A")
        _git(src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"c{n}")
        shas.append(_git(src, "rev-parse", "HEAD"))
    return src, shas


def test_descends_reads_the_first_roster_source_that_holds_both_commits(tmp_path, monkeypatch):
    """TD-1208: with two dev-cadence sources on the roster — the old history and an orphan one (agent-cadence's
    snapshot) — a pin's age is read in whichever holds both commits, in either order, and the forge is asked
    only when none does."""
    old, shas = _source(tmp_path, "dev-cadence", 3)
    orphan, _ = _source(tmp_path, "agent-cadence", 1)
    monkeypatch.setattr(cadence, "OLDEST", shas[1])
    asked = []
    monkeypatch.setattr(seams.reports, "_gh_api", lambda *a: asked.append(a) or (None, "no forge here"))
    for roster in ([old, orphan], [orphan, old]):
        assert seams.descends(shas[2], roster) == (True, None), roster
        assert seams.descends(shas[0], roster) == (False, None), roster
    assert asked == []
    got, why = seams.descends(shas[2], [orphan], "github.com/ShiftLead/dev-cadence")
    assert got is None and "agent-cadence does not hold" in why and "no forge here" in why
    assert [x[1].rsplit("/", 1)[1].split("...")[0] for x in asked] == [shas[1], cadence.SEED], "OLDEST, then the seed"


def test_a_pin_after_agent_cadences_seed_descends_on_either_history(tmp_path, monkeypatch):
    """TD-1208 slice 2, §5 *Which dev-cadence*: agent-cadence's seed is a second oldest point, so a pin on
    the orphan history at or after the seed descends, in either roster order and for `OLDEST_V2` too; a pin
    on neither history does not; with no checkout, the forge's compare of the seed answers once `OLDEST`'s
    cannot be read; and an age read against another seed is read again."""
    old, shas = _source(tmp_path, "dev-cadence", 2)
    new, (seed, after) = _source(tmp_path, "agent-cadence", 2)
    _git(new, "checkout", "-q", "--orphan", "other")
    _git(new, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "neither")
    neither = _git(new, "rev-parse", "HEAD")
    monkeypatch.setattr(cadence, "OLDEST", shas[1])
    monkeypatch.setattr(cadence, "OLDEST_V2", shas[1])
    monkeypatch.setattr(cadence, "SEED", seed)
    monkeypatch.setattr(seams.reports, "_gh_api", lambda *a: pytest.fail(f"the forge was asked: {a}"))
    for roster in ([old, new], [new, old]):
        assert seams.descends(after, roster) == (True, None), roster
        assert seams.descends(seed, roster) == (True, None), roster
        assert seams.descends(after, roster, oldest=cadence.OLDEST_V2) == (True, None), roster
        assert seams.descends(shas[1], roster) == (True, None), roster
        assert seams.descends(shas[0], roster) == (False, None), roster
        assert seams.descends(neither, roster) == (False, None), roster
    status = {cadence.OLDEST: (None, "HTTP 404: Not Found"), seed: ({"status": "ahead"}, None)}
    asked = []
    monkeypatch.setattr(
        seams.reports,
        "_gh_api",
        lambda home, path, t: asked.append(path) or status[path.split("/")[-1].split("...")[0]],
    )
    assert seams.descends(after, [], "https://github.com/ShiftLead/agent-cadence") == (True, None)
    assert asked == [f"repos/shiftlead/agent-cadence/compare/{p}...{after}" for p in (cadence.OLDEST, seed)]
    # TD-1215: a forge repo holding both histories answers *diverged* for `OLDEST`, and the seed still decides
    status[cadence.OLDEST] = ({"status": "diverged"}, None)
    assert seams.descends(after, [], "https://github.com/ShiftLead/agent-cadence") == (True, None)
    status[seed] = ({"status": "behind"}, None)
    assert seams.descends(after, [], "https://github.com/ShiftLead/agent-cadence") == (False, None)
    status[seed] = (None, "HTTP 404: Not Found")
    assert seams.descends(after, [], "https://github.com/ShiftLead/agent-cadence") == (False, None)
    # the age keys on the seed: one read against another seed is read again, one against this one carried
    root = tmp_path / "notes"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "cadence-sync.lock").write_text(f"source: {new}\nfiles_commit: {after}\n")
    got = seams.age(root, [old, new])
    assert got == {"commit": after, "oldest": shas[1], "seed": seed, "descends": True, "why": None}
    assert seams.age(root, [], {**got, "descends": False}) == {**got, "descends": False}, "carried"
    assert seams.age(root, [old, new], {**got, "seed": "f" * 40, "descends": False}) == got, "read again"


def test_a_brief_in_dev_cadences_source_after_sync_sh_names_files_paths(tmp_path):
    """`repoconfig.layout`'s `{gate}` prefix takes `is_source`'s two-way test, read with `there`."""
    from shiftlead import repoconfig

    src = tmp_path / "dev-cadence"
    (src / "files").mkdir(parents=True)
    (src / "launcher").mkdir()
    (src / "launcher" / "INTERFACE").write_text("1\n")
    assert repoconfig.layout(repoconfig.load_text(None, src))["{gate}"].startswith("python3 files/scripts/")
    (src / "launcher" / "INTERFACE").unlink()
    assert repoconfig.layout(repoconfig.load_text(None, src))["{gate}"].startswith("python3 scripts/")
