"""Design §6 *Sync: a mechanical sync PR is merged at the home*: `sync.check` — steps 1 and 2 as one check of
a bump of the pin (TD-1015) — against a fixture dev-cadence and a fixture repo, each a bare origin and a
checkout. The lock's replay (TD-685 slice 1) left once no served repo held a lock: a merge base with no pin is
refused."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from sessionorc import sync

pytestmark = pytest.mark.unit

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@x",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@x",
    "GIT_CONFIG_GLOBAL": "/dev/null",
}
DOC = "docs/cadence.md"


def g(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=ENV
    ).stdout.strip()


def write(root: Path, files: dict[str, str | None]) -> None:
    for path, text in files.items():
        f = root / path
        if text is None:
            f.unlink()
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)


def commit(root: Path, files: dict[str, str | None], msg: str = "c") -> str:
    write(root, files)
    g(root, "add", "-A")
    g(root, "commit", "-q", "-m", msg)
    return g(root, "rev-parse", "HEAD")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def lock(source: str, fc: str, files: dict[str, str], mode: str = "644") -> str:
    lines = ["# Written by dev-cadence sync.sh", f"source: {source}", f"commit: {fc[:7]}", f"files_commit: {fc}"]
    return "\n".join(lines + [f"file: {p} {sha(t)} {mode}" for p, t in files.items()]) + "\n"


PINNED = '# the repo\'s settings\nreview-model = "sonnet"\n\n[dev-cadence]\nsource = "{source}"\nref = "{ref}"\n'


class PinWorld:
    """`World`, but the repo's main pins dev-cadence's first commit in `docs/cadence.toml` and holds no lock."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        for name in ("dc", "repo"):
            g(tmp, "init", "-q", "--bare", "-b", "main", f"{name}.git")
            g(tmp, "clone", "-q", f"{tmp}/{name}.git", name)
            g(tmp / name, "checkout", "-q", "-b", "main")
        self.dc, self.repo, self.source = tmp / "dc", tmp / "repo", f"{tmp}/dc.git"
        self.ref0 = self.dc_commit({DOC: "one\n"})
        commit(self.repo, {sync.PIN: self.pin(self.ref0)})
        g(self.repo, "push", "-q", "origin", "main")
        g(self.repo, "remote", "set-head", "origin", "main")
        g(self.dc, "remote", "set-head", "origin", "main")

    def pin(self, ref: str, source: str | None = None) -> str:
        return PINNED.format(source=source or self.source, ref=ref)

    def dc_commit(self, files: dict[str, str], push: bool = True) -> str:
        c = commit(self.dc, {f"files/{p}": t for p, t in files.items()})
        if push:
            g(self.dc, "push", "-q", "origin", "HEAD:main")
        return c

    def pr(self, files: dict[str, str | None], branch: str = "cadence-sync-1") -> str:
        g(self.repo, "checkout", "-q", "-B", branch, "origin/main")
        head = commit(self.repo, files)
        g(self.repo, "push", "-q", "-f", "origin", branch)
        g(self.repo, "checkout", "-q", "main")
        return head

    def check(self, head: str, branch: str = "cadence-sync-1", **kw) -> dict:
        return sync.check(self.repo, 7, head, branch, clones=[self.dc], **kw)


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    return PinWorld(tmp_path)


def test_a_bump_of_the_pin_alone_that_descends_is_mechanical(pinned):
    ref = pinned.dc_commit({DOC: "two\n"})
    head = pinned.pr({sync.PIN: pinned.pin(ref).replace(f'"{ref}"', f'"{ref}"   # v1.2')})
    got = pinned.check(head)
    assert (got["verdict"], got["why"], got["kind"]) == ("mechanical", "", "bump")
    assert (got["commit"], got["old"], got["files"], got["post_sync"]) == (ref, pinned.ref0, [sync.PIN], False)


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ("source", "the pin's source changed"),
        ("file", "not a routine bump: src/x.py changed"),
        ("line", "not a routine bump: docs/cadence.toml changed beyond the pin's ref"),
        ("same", "not a routine bump: the pin's ref did not move"),
        ("gone", "not a routine bump: docs/cadence.toml holds no [dev-cadence] pin"),
    ],
)
def test_a_bump_that_changes_more_than_the_ref_is_refused_by_name(pinned, change, why):
    ref = pinned.dc_commit({DOC: "two\n"})
    files = {
        "source": {sync.PIN: pinned.pin(ref, source="https://github.com/evil/dc")},
        "file": {sync.PIN: pinned.pin(ref), "src/x.py": "x\n"},
        "line": {sync.PIN: pinned.pin(ref).replace('"sonnet"', '"haiku"')},
        "same": {sync.PIN: pinned.pin(pinned.ref0).replace(f'"{pinned.ref0}"', f'"{pinned.ref0}"  # v1')},
        "gone": {sync.PIN: "# no pin\n"},
    }[change]
    head = pinned.pr(files)
    assert pinned.check(head) == {"head": head, "verdict": "refused", "why": why}


def test_a_ref_that_does_not_descend_or_is_not_on_the_default_branch_is_refused(pinned):
    ref1 = pinned.dc_commit({DOC: "two\n"})
    g(pinned.repo, "checkout", "-q", "main")
    commit(pinned.repo, {sync.PIN: pinned.pin(ref1)})
    g(pinned.repo, "push", "-q", "origin", "main")
    # back to the first commit: on dev-cadence's main, but an ancestor of the pin, not a descendant
    assert pinned.check(pinned.pr({sync.PIN: pinned.pin(pinned.ref0)}))["why"] == (
        f"ref {pinned.ref0[:7]} does not descend from {ref1[:7]}"
    )
    # a commit dev-cadence never put on main: pushed to a side branch only
    g(pinned.dc, "checkout", "-q", "-b", "side")
    side = commit(pinned.dc, {"files/x": "x\n"})
    g(pinned.dc, "push", "-q", "origin", "side")
    g(pinned.dc, "checkout", "-q", "main")
    assert pinned.check(pinned.pr({sync.PIN: pinned.pin(side)}))["why"] == (
        f"ref {side[:7]} is not a full commit on dev-cadence's main"
    )
    # a short ref is no full commit, though it names one; nor is a full one padded with a space
    head = pinned.pr({sync.PIN: pinned.pin(side[:12])})
    assert pinned.check(head)["why"] == f"ref {side[:7]} is not a full commit on dev-cadence's main"
    ref2 = pinned.dc_commit({DOC: "three\n"})
    head = pinned.pr({sync.PIN: pinned.pin(f" {ref2}")})
    assert pinned.check(head)["why"] == f"ref  {ref2[:6]} is not a full commit on dev-cadence's main"


def test_a_bump_with_no_clone_or_on_a_held_path_is_refused(pinned):
    head = pinned.pr({sync.PIN: pinned.pin(pinned.dc_commit({DOC: "two\n"}))})
    assert sync.check(pinned.repo, 7, head, "cadence-sync-1", clones=[])["why"] == (
        "no dev-cadence clone to check the pin against"
    )
    assert pinned.check(head, held=["docs/**"])["why"] == "docs/cadence.toml is a held path"


def test_only_ref_moved_reads_the_pin_table_alone():
    before = PINNED.format(source="s", ref="a" * 40)
    assert sync.only_ref_moved(before, before.replace(f'"{"a" * 40}"', f'"{"b" * 40}"   # v2'))
    assert not sync.only_ref_moved('[other]\nref = "a"\n', '[other]\nref = "b"\n')
    assert not sync.only_ref_moved(before, before + "\n")


def test_a_merge_base_with_a_lock_and_no_pin_is_refused(pinned):
    """The lock's road left `sync.check` (TD-1015): a repo still on a lock is the person's to migrate."""
    fc = pinned.ref0
    g(pinned.repo, "checkout", "-q", "main")
    commit(pinned.repo, {sync.PIN: None, sync.LOCK: lock(pinned.source, fc, {DOC: "one\n"}), DOC: "one\n"})
    g(pinned.repo, "push", "-q", "origin", "main")
    fc2 = pinned.dc_commit({DOC: "two\n"})
    head = pinned.pr({DOC: "two\n", sync.LOCK: lock(pinned.source, fc2, {DOC: "two\n"})})
    assert pinned.check(head) == {
        "head": head,
        "verdict": "refused",
        "why": "no [dev-cadence] pin at the merge base: docs/cadence.toml holds none",
    }


@pytest.mark.parametrize("toml", ['# settings alone\nreview-model = "sonnet"\n', '[dev-cadence\nref = "x"\n'])
def test_a_merge_base_whose_toml_holds_no_pin_or_does_not_parse_is_refused(pinned, toml):
    g(pinned.repo, "checkout", "-q", "main")
    commit(pinned.repo, {sync.PIN: toml})
    g(pinned.repo, "push", "-q", "origin", "main")
    head = pinned.pr({sync.PIN: pinned.pin(pinned.dc_commit({DOC: "two\n"}))})
    assert pinned.check(head)["why"] == "no [dev-cadence] pin at the merge base: docs/cadence.toml holds none"


def test_a_head_that_moved_is_not_checked(pinned):
    head = pinned.pr({sync.PIN: pinned.pin(pinned.dc_commit({DOC: "two\n"}))})
    got = pinned.check("b" * 40)
    assert got["verdict"] == "moved" and got["head"] == "b" * 40
    assert pinned.check(head)["verdict"] == "mechanical"


LAST_OWN_LOCK = """# Written by ShiftLead/dev-cadence sync.sh — do not edit by hand.
source: https://github.com/ShiftLead/dev-cadence
commit: 232f2ad
files_commit: 232f2ad364384929f57011ff2e76b9ba324ab8d7
synced: 2026-10-23T01:54:48Z
file: docs/cadence.md e1f332cb617f8333fb148f401f19e21958ee6d1a6547cbc02791dc67ad63efcd 644
file: docs/cadence-rationale.md f06aecd78c767a0eac466bb0c5e4637b364fc3582cfd6da5d930c1a38498961d 644
"""


def test_parse_lock_reads_a_lock_as_sync_sh_writes_it():
    got = sync.parse_lock(LAST_OWN_LOCK)
    assert got["source"] == "https://github.com/ShiftLead/dev-cadence" and got["files"]["docs/cadence.md"][1] == "644"
    assert sync.parse_lock(None) is None


def test_origins_compare_as_one_repository():
    n = sync._norm_url
    assert n("git@github.com:ShiftLead/dev-cadence.git") == n("https://github.com/shiftlead/dev-cadence/")
    assert n("/tmp/x/dc.git") == n("/tmp/x/dc")
