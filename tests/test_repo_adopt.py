"""`ao repo add <path> [--adopt]` on a checkout without agent-cadence (design §4.7 **`ao repo add`**, §5 *The
seams*, TD-1010): the adoption is offered from a scratch clone and nothing is added; `--adopt` opens it as a
PR on `cadence-adopt` and adds the repo, unserved until the PR merges. A temp origin stands for GitHub
through `url.<path>.insteadOf`, a stub `sync.sh` (or launcher) for agent-cadence's adopt and a stub `gh` for the PR."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from conftest import park_ticks, served

from sessionorc import hosts, seams
from shiftlead import adopt, cli

URL = "https://github.com/t/notes.git"
LOCK = "source: agent-cadence\ncommit: abc1234\nfiles_commit: abc1234\n"
# agent-cadence's adopt as far as these tests need it: the lock and the gate, and per-clone settings in the
# target's own `.git`, which must never reach the person's checkout
SYNC = f"""#!/bin/sh
set -e
t="$1"
mkdir -p "$t/docs" "$t/scripts"
printf '{LOCK.replace(chr(10), "\\n")}' > "$t/docs/cadence-sync.lock"
echo 'x = 1' > "$t/scripts/check_cadence.py"
git -C "$t" config agent-cadence.shim on
echo '.cadence-scratch' >> "$t/.git/info/exclude"
"""
REF = "4197a277978b1652459ecdf65db0dc033016cb5a"
# the launcher's `adopt` (dev-cadence TD-129) as far as these tests need it: its argv, a seed and the pin
LAUNCHER = f"""import os, sys
open(os.environ["ADOPT_LOG"], "w").write("\\n".join([os.getcwd(), *sys.argv[1:]]))
t = sys.argv[-1]
os.makedirs(os.path.join(t, "docs"), exist_ok=True)
open(os.path.join(t, "AGENTS.md"), "w").write("seeded\\n")
open(os.path.join(t, "docs", "cadence.toml"), "w").write('[agent-cadence]\\nsource = "/src"\\nref = "{REF}"\\n')
"""
GH = """#!/bin/sh
if [ "$2" = list ]; then cat "$GH_OPEN" 2>/dev/null || echo '[]'; exit 0; fi
line=$(printf '%s\\t' "$@"); echo "$line" >> "$GH_LOG"
while [ $# -gt 0 ]; do [ "$1" = --body-file ] && cp "$2" "$GH_LOG.body"; shift; done
echo https://github.com/t/notes/pull/7
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


def _exe(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A GitHub-looking origin with a ledger on `main`, the person's checkout of it, a stub agent-cadence
    checkout on the home's roster, a stub `gh` on PATH, and `$TMPDIR` a directory of the test's own."""
    bare = tmp_path / "origin.git"
    cfg = tmp_path / "gitconfig"
    cfg.write_text(f'[user]\n\tname = t\n\temail = t@t\n[url "{bare}"]\n\tinsteadOf = {URL}\n')
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", URL, str(seed)], check=True, capture_output=True)
    (seed / "docs").mkdir()
    (seed / "docs" / "technical_debt.md").write_text("# Technical debt\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "the ledger")
    git(seed, "push", "-q", "origin", "HEAD:main")
    checkout = tmp_path / "notes"
    subprocess.run(["git", "clone", "-q", URL, str(checkout)], check=True, capture_output=True)
    dc = tmp_path / "agent-cadence"
    _exe(dc / "sync.sh", SYNC)
    (dc / "files").mkdir()
    reg = hosts.default_repos_registry()
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(f"{dc}\n")
    _exe(tmp_path / "bin" / "gh", GH)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("GH_LOG", str(tmp_path / "gh.log"))
    monkeypatch.setenv("GH_OPEN", str(tmp_path / "gh-open.json"))  # what `gh pr list` answers: none
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setenv("TMPDIR", str(scratch))
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return {"origin": bare, "seed": seed, "checkout": checkout, "dc": dc, "tmp": scratch, "log": tmp_path / "gh.log"}


def _calls(world) -> list[list[str]]:
    """Every `gh` call but `pr list`, one argv a line: appended, since a call the test did not make (likeliest a
    read of the agent's still running in a thread when `world` put the fake on PATH) lands in the same log (TD-1211)."""
    log = world["log"]
    return [line.removesuffix("\t").split("\t") for line in log.read_text().splitlines()] if log.exists() else []


def _prs(world) -> list[list[str]]:
    """The `gh pr create` calls: what an adoption opens, and the only call these tests assert on."""
    return [c for c in _calls(world) if c[:2] == ["pr", "create"]]


def _roster() -> list[str]:
    return hosts.default_repos_registry().read_text().splitlines()


def _per_clone(checkout: Path) -> tuple[str, str]:
    return (checkout / ".git" / "config").read_text(), (checkout / ".git" / "info" / "exclude").read_text()


async def test_a_checkout_without_agent_cadence_is_offered_its_adoption_and_nothing_is_added(agent, world, capsys):
    await park_ticks(agent)
    checkout, before = world["checkout"], _per_clone(world["checkout"])
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[:2] == ["docs/cadence-sync.lock", "scripts/check_cadence.py"]
    assert f"`ao repo add {checkout.resolve()} --adopt` opens these 2 files as a PR" in out
    assert _roster() == [str(world["dc"])]  # nothing added
    assert list(world["tmp"].iterdir()) == []  # no clone left
    assert _per_clone(checkout) == before  # the clone's settings never reached the person's checkout
    assert not _prs(world), _calls(world)  # no PR
    assert "cadence-adopt" not in git(world["origin"], "branch")


async def test_adopt_opens_the_pr_adds_the_repo_unserved_and_the_merged_adoption_serves_it(agent, world, capsys):
    await park_ticks(agent)
    checkout, before = world["checkout"].resolve(), _per_clone(world["checkout"])
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout), "--adopt"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("adoption PR #7 open: https://github.com/t/notes/pull/7 — agent-cadence abc1234, 2 files")
    assert f"added notes, unserved until it merges\nonce it merges, run `{world['dc']}/sync.sh {checkout}`" in out
    origin = world["origin"]
    assert git(origin, "log", "-1", "--format=%s", "cadence-adopt").strip() == "adopt agent-cadence abc1234"
    assert git(origin, "log", "-1", "--format=%s", "main").strip() == "the ledger"  # never the default branch
    (argv,) = _prs(world)
    assert argv[:6] == ["pr", "create", "--head", "cadence-adopt", "--base", "main"]
    body = Path(f"{world['log']}.body").read_text()
    assert "agent-cadence at abc1234" in body and f"`{world['dc']}/sync.sh {checkout}`" in body
    assert f"written by `{world['dc']}/sync.sh` in a scratch clone" in body  # no launcher: sync.sh wrote it
    assert _roster() == [str(world["dc"]), str(checkout)]
    assert list(world["tmp"].iterdir()) == []
    assert _per_clone(world["checkout"]) == before
    await agent._refresh_repos()
    assert agent._repos[str(checkout)]["seams"]["serve"]["ok"] is False  # unserved until it merges
    # the person merges it on GitHub; the checkout is pulled, and the next reading serves the repo
    seed = world["seed"]
    git(seed, "fetch", "-q", "origin")
    git(seed, "merge", "-q", "--ff-only", "origin/cadence-adopt")
    git(seed, "push", "-q", "origin", "HEAD:main")
    git(checkout, "pull", "-q", "--ff-only")
    agent._repos_fresh = True  # the next full reading, as after the home's Pull
    await agent._refresh_repos()
    assert agent._repos[str(checkout)]["seams"]["serve"] == {"ok": True, "lacks": []}


async def test_adopt_on_a_registered_repo_lacking_its_gate_opens_the_pr_and_adds_nothing(agent, world, capsys):
    await park_ticks(agent)
    seed, checkout = world["seed"], world["checkout"].resolve()
    (seed / "docs" / "cadence-sync.lock").write_text(LOCK)  # the lock, and no scripts/check_cadence.py
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "a lock")
    git(seed, "push", "-q", "origin", "HEAD:main")
    git(checkout, "pull", "-q", "--ff-only")
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout)]) == 0  # it holds the lock: added
    capsys.readouterr()
    await agent._refresh_repos()
    lacks = agent._repos[str(checkout)]["seams"]["serve"]["lacks"]
    assert [x["words"] for x in lacks] == [
        f"unserved: no gate (no scripts/check_cadence.py) — `ao repo add {checkout} --adopt`"
    ]
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout)]) != 0  # in the roster already
    assert "is in the roster already" in capsys.readouterr().err
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout), "--adopt"]) == 0
    out = capsys.readouterr().out
    assert "agent-cadence abc1234, 1 file\nnotes is unserved until it merges\n" in out
    assert git(world["origin"], "show", "--name-only", "--format=", "cadence-adopt").split() == [
        "scripts/check_cadence.py"
    ]
    assert _roster() == [str(world["dc"]), str(checkout)]  # not added twice


async def test_adopt_refuses_a_served_repo_no_agent_cadence_checkout_and_an_origin_off_github(agent, world, capsys):
    await park_ticks(agent)
    checkout = world["checkout"].resolve()
    hosts.default_repos_registry().write_text("")  # no agent-cadence checkout in the roster
    for argv in (["repo", "add", str(checkout)], ["repo", "add", str(checkout), "--adopt"]):
        assert await asyncio.to_thread(cli.main, argv) != 0
        assert cli.NO_AGENT_CADENCE in capsys.readouterr().err
    hosts.default_repos_registry().write_text(f"{world['dc']}\n")
    git(checkout, "remote", "set-url", "origin", str(world["origin"]))
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout), "--adopt"]) != 0
    assert f"ao repo add opens its PR on GitHub: {checkout}'s origin is {world['origin']}" in capsys.readouterr().err
    served(checkout)
    hosts.default_repos_registry().write_text(f"{world['dc']}\n{checkout}\n")
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout), "--adopt"]) != 0
    assert "in the roster already, and served" in capsys.readouterr().err
    assert not _prs(world), _calls(world)
    assert cli.main(["repo", "notes", "--adopt"]) != 0
    assert "--adopt goes with `ao repo add <path>`" in capsys.readouterr().err


async def test_a_agent_cadence_checkout_without_a_launcher_or_sync_sh_is_picked_and_refused_before_any_clone(
    agent, world, capsys
):
    """TD-1024, §4.7 `ao repo add`: once `sync.sh` retires, an agent-cadence checkout with `launcher/INTERFACE`
    is still the roster's pick, and the adopt — which runs `sync.sh` — refuses it by name, offer and
    `--adopt` alike, with no scratch clone made and nothing pushed."""
    await park_ticks(agent)
    checkout = world["checkout"].resolve()
    dc = world["dc"]
    (dc / "sync.sh").unlink()
    (dc / "launcher").mkdir()
    (dc / "launcher" / "INTERFACE").write_text("1\n")
    assert adopt.agent_cadence(_roster(), checkout) == dc.resolve()
    words = f"agent-cadence at {dc.resolve()} has no launcher or sync.sh: pull it, then run this again"
    for argv in (["repo", "add", str(checkout)], ["repo", "add", str(checkout), "--adopt"]):
        assert await asyncio.to_thread(cli.main, argv) != 0
        assert words in capsys.readouterr().err
        assert list(world["tmp"].iterdir()) == [], "no scratch clone"
    assert not _prs(world), _calls(world)
    assert "cadence-adopt" not in git(world["origin"], "branch")
    assert _roster() == [str(dc)], "nothing added"


async def test_a_rerun_finds_the_open_adoption_pr_and_adds_the_repo_and_a_stale_branch_is_refused(
    agent, world, capsys, monkeypatch, tmp_path
):
    """The PR opened and `add_repo` failed: the re-run pushes nothing, names the PR and adds the repo."""
    await park_ticks(agent)
    checkout = world["checkout"].resolve()

    def down(method, **kw):
        raise cli.AgentError("the host agent is not answering")

    with monkeypatch.context() as m:
        m.setattr(cli, "call_sync", down)
        assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout), "--adopt"]) != 0
    assert "not answering" in capsys.readouterr().err
    assert _roster() == [str(world["dc"])]
    first = git(world["origin"], "rev-parse", "cadence-adopt")
    world["log"].unlink(missing_ok=True)
    (tmp_path / "gh-open.json").write_text('[{"number": 7, "url": "https://github.com/t/notes/pull/7"}]')
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout), "--adopt"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("adoption PR #7 is open already: https://github.com/t/notes/pull/7\nadded notes")
    assert git(world["origin"], "rev-parse", "cadence-adopt") == first and not _prs(world), _calls(world)
    assert _roster() == [str(world["dc"]), str(checkout)]
    (tmp_path / "gh-open.json").write_text("[]")  # the PR closed, the branch left behind
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout), "--adopt"]) != 0
    assert "holds a branch cadence-adopt with no open PR" in capsys.readouterr().err


def test_the_paths_are_read_whole_and_the_clone_goes_under_cadences_own_temp_root(world, tmp_path, monkeypatch):
    """A path with a space comes back unquoted, and with `CADENCE_TEMP_ROOTS` set the clone is made under
    its first root, the one `sync.sh` then counts as temporary."""
    dc = world["dc"]
    (dc / "sync.sh").write_text(SYNC + 'echo x > "$t/a b.md"\necho "$t" > "$CLONE_AT"\n')
    roots = tmp_path / "roots"
    roots.mkdir()
    monkeypatch.setenv("CADENCE_TEMP_ROOTS", f"{roots}:/var/tmp")
    monkeypatch.setenv("CLONE_AT", str(tmp_path / "clone-at"))
    got = adopt.offer(world["checkout"].resolve(), dc)
    assert sorted(got["paths"]) == ["a b.md", "docs/cadence-sync.lock", "scripts/check_cadence.py"]
    assert (tmp_path / "clone-at").read_text().startswith(f"{roots}/ao-adopt-")
    assert list(roots.iterdir()) == []


def test_an_open_adoption_pr_is_the_cure_its_lacks_name():
    """§5 *The seams*: while the PR reading holds an open PR whose head is `cadence-adopt`, each adopt
    cure reads *adoption PR #n open*; a lack no adopt cures keeps its words."""
    adopt_cure = "unserved: no gate (no scripts/check_cadence.py) — `ao repo add /r/notes --adopt`"
    bad = "unserved: the ledger at docs/technical_debt.md does not parse — boom"
    reading = {"serve": {"ok": False, "lacks": [{"key": "gate", "words": adopt_cure}, {"key": "ledger", "words": bad}]}}
    assert seams.with_adoption(reading, "/r/notes", {"open": [{"number": 3, "branch": "td-1"}]}) is reading
    got = seams.with_adoption(reading, "/r/notes", {"open": [{"number": 9, "branch": "cadence-adopt"}]})
    assert [x["words"] for x in got["serve"]["lacks"]] == [
        "unserved: no gate (no scripts/check_cadence.py) — adoption PR #9 open",
        bad,
    ]
    assert seams.with_adoption(None, "/r", {"open": [{"number": 9, "branch": "cadence-adopt"}]}) is None


async def test_a_agent_cadence_checkout_with_a_launcher_adopts_through_its_adopt_and_names_the_pin(
    agent, world, capsys, monkeypatch
):
    """TD-1183 (design §4.7 **`ao repo add`**): an agent-cadence checkout with a launcher adopts through its `adopt`,
    `<dc>/launcher/agent_cadence.py -C <dc> adopt <clone>`, never its `sync.sh` (which no longer copies since
    dev-cadence #429); the PR names the pin's `ref`, and the reply and the body name that `adopt` as the
    person's run after the merge."""
    await park_ticks(agent)
    checkout, dc = world["checkout"].resolve(), world["dc"]
    (dc / "sync.sh").write_text("#!/bin/sh\necho 'sync.sh no longer copies into a repo' >&2\nexit 1\n")
    (dc / "launcher").mkdir()
    (dc / "launcher" / "agent_cadence.py").write_text(LAUNCHER)
    log = world["tmp"].parent / "adopt.log"
    monkeypatch.setenv("ADOPT_LOG", str(log))
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[:2] == ["AGENTS.md", "docs/cadence.toml"]
    cwd, *argv = log.read_text().splitlines()
    assert argv[:3] == ["-C", str(dc), "adopt"] and Path(argv[3]).name == "notes" and Path(argv[3]) != checkout
    assert cwd == argv[3]
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout), "--adopt"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"adoption PR #7 open: https://github.com/t/notes/pull/7 — agent-cadence {REF[:7]}, 2 files")
    assert f"once it merges, run `agent-cadence -C {dc} adopt {checkout}`" in out
    assert git(world["origin"], "log", "-1", "--format=%s", "cadence-adopt").strip() == f"adopt agent-cadence {REF[:7]}"
    body = Path(f"{world['log']}.body").read_text()
    assert f"written by `agent-cadence -C {dc} adopt`" in body and f"`agent-cadence -C {dc} adopt {checkout}`" in body
    assert list(world["tmp"].iterdir()) == []


AGENT_CADENCE = Path(os.environ.get("AGENT_CADENCE_SOURCE", "~/agent-cadence")).expanduser()


def _adoptable(dc: Path) -> str | None:
    """Why the machine's agent-cadence cannot run this test's adopt, or None: no launcher (TD-1183), or one its
    `adopt` refuses to run from — a dirty clone, or a HEAD off origin's default branch (dev-cadence TD-129)."""
    if not (dc / "launcher" / "agent_cadence.py").is_file():
        return "no agent-cadence checkout with a launcher on this machine"
    run = lambda *a: subprocess.run(["git", "-C", str(dc), *a], capture_output=True, text=True)  # noqa: E731
    if run("status", "--porcelain", "--untracked-files=no").stdout.strip():
        return f"{dc} has uncommitted changes: its adopt refuses"
    head = run("symbolic-ref", "-q", "refs/remotes/origin/HEAD").stdout.strip()
    if not head or run("merge-base", "--is-ancestor", "HEAD", head).returncode != 0:
        return f"{dc}'s HEAD is not on origin's default branch: its adopt refuses"
    return None


@pytest.mark.skipif(bool(_adoptable(AGENT_CADENCE)), reason=_adoptable(AGENT_CADENCE) or "")
def test_the_offer_leaves_agent_cadences_roster_as_it_was_and_the_temp_root_is_the_reason(world, tmp_path, monkeypatch):
    """dev-cadence TD-068: its adopt registers a target outside every temp root, so the scratch clone is made
    under `$TMPDIR`. The roster lives outside the temp roots (`CADENCE_TEMP_ROOTS` names the test's
    `$TMPDIR` alone); the offer's real run, the launcher's `adopt` (TD-1183), leaves it byte-identical, and the
    same run on a clone outside the temp roots registers that clone."""
    config = tmp_path / "config"
    roster = config / "agent-cadence" / "repos.txt"
    roster.parent.mkdir(parents=True)
    roster.write_text("/somewhere/else\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.delenv("AGENT_CADENCE_REG_DIR", raising=False)
    monkeypatch.setenv("CADENCE_TEMP_ROOTS", str(world["tmp"]))
    root = world["checkout"].resolve()
    got = adopt.offer(root, AGENT_CADENCE)
    assert "docs/cadence.toml" in got["paths"]
    assert roster.read_text() == "/somewhere/else\n"
    outside = tmp_path / "outside"
    subprocess.run(["git", "clone", "-q", str(root), str(outside)], check=True, capture_output=True)
    launcher = AGENT_CADENCE / "launcher" / "agent_cadence.py"
    subprocess.run(
        [sys.executable, str(launcher), "-C", str(AGENT_CADENCE), "adopt", str(outside)],
        check=True,
        capture_output=True,
        timeout=300,
    )
    assert roster.read_text().splitlines() == ["/somewhere/else", str(outside.resolve())]
    shutil.rmtree(outside)


async def test_a_pinned_checkout_is_added_and_an_adopt_over_a_pinned_origin_is_refused(
    agent, world, capsys, monkeypatch
):
    """TD-1014 (design §4.7 **`ao repo add`**): a checkout holding agent-cadence by its pin (`docs/cadence.toml`'s
    `[agent-cadence]`, no lock) is added as one holding the lock is, served or not as the reading finds it; an
    adopt run where origin's default branch pins agent-cadence is refused before `sync.sh` writes a copy."""
    from sessionorc import cadence

    await park_ticks(agent)
    monkeypatch.setattr(cadence, "tree", lambda root, timeout=0: (None, "no tree in this test"))
    seed, checkout = world["seed"], world["checkout"].resolve()
    (seed / "docs" / "cadence.toml").write_text(f'[agent-cadence]\nsource = "/src"\nref = "{"a" * 40}"\n')
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "the pin")
    git(seed, "push", "-q", "origin", "HEAD:main")
    git(checkout, "pull", "-q", "--ff-only")
    assert cadence.holds(checkout) and not cadence.holds(world["origin"])
    lock = checkout / "docs" / "cadence-sync.lock"
    lock.write_text(LOCK)  # a lock beside the pin: held by the lock, and the copy read
    assert cadence.holds(checkout) and not cadence.pinned(checkout)
    lock.unlink()
    with pytest.raises(
        adopt.AdoptError,
        match=rf"origin/main of {checkout} pins agent-cadence already \(docs/cadence.toml\): pull the checkout",
    ):
        await asyncio.to_thread(adopt.offer, checkout, world["dc"])
    assert list(world["tmp"].iterdir()) == []
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout)]) == 0  # it holds the pin: added
    capsys.readouterr()
    assert _roster() == [str(world["dc"]), str(checkout)]
    assert await asyncio.to_thread(cli.main, ["repo", "add", str(checkout), "--adopt"]) != 0
    assert "pins agent-cadence already" in capsys.readouterr().err
    assert not _prs(world), _calls(world)  # no PR
