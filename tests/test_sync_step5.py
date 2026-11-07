"""TD-1419, design §6 *Sync* steps 4 and 5: the home's sync merge is cadence step 5's line where the pinned tree
composes it — the gate run once with `--trailers <dir>/gate`, `forge.py squash-message` under
`AGENT_NAME=shiftlead-sync`, then `gh pr merge` with the composed subject and body, made only when the composed
sha, the proved head and the re-read head are one — and the bare merge where it does not. `gate_dir` never
reaches the reading, and the directory is removed on every road but the one that hands it to the merge."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_sync_pass import HEAD, ROOT, _names, _pr, _reading, agent, gh  # noqa: F401, F811 — fixtures

from sessionorc import cadence, sync

REPO = Path(__file__).resolve().parents[1]


# -- cadence.composes -------------------------------------------------------------------------------


def test_composes_answers_yes_no_or_unreadable_never_unreadable_as_no(tmp_path, monkeypatch):
    payload = tmp_path / "files"
    (payload / "scripts").mkdir(parents=True)
    monkeypatch.setattr(cadence, "tree", lambda root: (payload, None))
    (payload / "scripts" / "forge.py").write_text('q = sub.add_parser("squash-message")\n')
    assert cadence.composes("/r") == (True, None)
    (payload / "scripts" / "forge.py").write_text('i = sub.add_parser("in-flight")\n')
    assert cadence.composes("/r") == (False, None)
    (payload / "scripts" / "forge.py").unlink()
    yes, why = cadence.composes("/r")
    assert yes is None and "scripts/forge.py could not be read" in why
    monkeypatch.setattr(cadence, "tree", lambda root: (None, "the fetch failed"))
    assert cadence.composes("/r") == (None, "the fetch failed")


def test_the_gate_takes_trailers_only_when_given(monkeypatch):
    argvs = []

    def run(argv, **kw):
        argvs.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"prs": [{"pr": 7, "verdict": "pass", "rows": []}]}), "")

    monkeypatch.setattr(cadence, "has_script", lambda root: True)
    monkeypatch.setattr(cadence, "pinned", lambda root: True)
    monkeypatch.setattr(cadence.subprocess, "run", run)
    assert cadence.check("/r", 7, 5.0) == {"verdict": "pass", "failed": []}
    assert "--trailers" not in argvs[-1]
    cadence.check("/r", 7, 5.0, trailers="/tmp/x/gate")
    assert argvs[-1][-2:] == ["--trailers", "/tmp/x/gate"] and "--json" in argvs[-1]


# -- step 4: judge --------------------------------------------------------------------------------


def _gate_seen(gh):  # noqa: F811
    return [c for c in gh["calls"] if c[0] == "gate"]


def test_judge_runs_the_gate_with_trailers_where_the_tree_composes_and_hands_on_the_dir(gh):  # noqa: F811
    gh["composes"] = (True, None)
    seen = {}

    def gate(root, n, timeout, *, trailers):
        seen["trailers"] = trailers
        Path(trailers).write_text(f"pr {n}\nexpect {HEAD}\n")
        return {"verdict": "pass", "failed": []}

    e = sync.judge(ROOT, _pr(), None, [], "T0", gate=gate)
    assert e["ready"] and Path(e["gate_dir"]).is_dir() and seen["trailers"] == Path(e["gate_dir"]) / "gate"
    shutil.rmtree(e["gate_dir"])


def test_judge_where_the_tree_does_not_compose_calls_the_old_gate_shape_and_hands_on_nothing(gh):  # noqa: F811
    gh["composes"] = (False, None)
    e = sync.judge(ROOT, _pr(), None, [], "T0", gate=lambda root, n, timeout: {"verdict": "pass", "failed": []})
    assert e["ready"] and "gate_dir" not in e


def test_judge_an_unreadable_tree_is_no_reading_counted_and_runs_no_gate(gh):  # noqa: F811
    gh["composes"] = (None, "the fetch failed")
    e = sync.judge(ROOT, _pr(), None, [], "T0")
    assert e["tries"] == 1 and "the fetch failed" in e["why"] and not _gate_seen(gh) and "gate_dir" not in e


@pytest.mark.parametrize("road", ["fail", "unknown", "none", "block-not-posted", "raises"])
def test_judge_removes_the_dir_on_every_road_but_ready(gh, monkeypatch, road):  # noqa: F811
    gh["composes"] = (True, None)
    made = []
    real = sync.tempfile.mkdtemp
    monkeypatch.setattr(sync.tempfile, "mkdtemp", lambda **kw: made.append(real(**kw)) or made[-1])
    answer = {
        "fail": {"verdict": "fail", "failed": ["ci"]},
        "unknown": {"verdict": "unknown", "failed": []},
        "none": None,
        "block-not-posted": {"verdict": "fail", "failed": ["ci"]},
    }

    def gate(root, n, timeout, *, trailers):
        if road == "raises":
            raise RuntimeError("boom")
        return answer[road]

    if road == "block-not-posted":
        gh["comment"] = "HTTP 502"
    if road == "raises":
        with pytest.raises(RuntimeError):
            sync.judge(ROOT, _pr(), None, [], "T0", gate=gate)
    else:
        e = sync.judge(ROOT, _pr(), None, [], "T0", gate=gate)
        assert "gate_dir" not in e and not e.get("ready")
    assert made and not any(Path(d).exists() for d in made)


# -- step 5: _sync_merge ----------------------------------------------------------------------------


def _handed(tmp_path, sha=HEAD) -> tuple[dict, Path]:
    d = tmp_path / "gd"
    d.mkdir()
    (d / "gate").write_text(f"pr 1097\nexpect {sha}\n")
    return {"head": HEAD, "verdict": "", "why": "", "tries": 0, "kind": "bump", "commit": "e" * 40,
            "gate_dir": str(d)}, d  # fmt: skip


def _composer(gh, sha=HEAD, why=None):  # noqa: F811
    def compose(root, n, gate_dir):
        gh["calls"].append(("compose", (root, n, str(gate_dir))))
        if why:
            return why
        for name, text in (("subject", "the subject (#1097)"), ("body", "body\n\nMerged-by: shiftlead-sync\n"),
                           ("sha", sha)):  # fmt: skip
            (Path(gate_dir) / name).write_text(text)
        return None

    return compose


async def test_the_composed_merge_runs_in_order_and_drops_the_dir(agent, gh, monkeypatch, tmp_path):  # noqa: F811
    e, d = _handed(tmp_path)
    monkeypatch.setattr(sync, "compose", _composer(gh))
    held = []
    monkeypatch.setattr(agent, "_sync_held_by", lambda root, pr: held.append(len(gh["calls"])) and False)
    got = await agent._sync_merge(ROOT, _pr(), e)
    assert got["verdict"] == "merged" and "gate_dir" not in got and not d.exists()
    assert _names(gh) == ["compose", "head", "merge"]
    assert held == [0, 1], "the holders read before the compose and again after it"
    merge = gh["calls"][-1]
    assert merge[1] == (ROOT, 1097, HEAD)  # positional; the composed words as keywords (recorded below)


async def test_a_sync_merge_rereads_board_and_ledger_against_origin_at_once(agent, gh, monkeypatch, tmp_path):  # noqa: F811
    """TD-1508 (§4.4 *Every write the home lands is read at once*): the merge moved origin, not the board's tree, so
    the repo is read again at once with a fetch first (`fetch=True`, never the tree); a merge that does not land
    re-reads nothing."""
    e, _ = _handed(tmp_path)
    monkeypatch.setattr(sync, "compose", _composer(gh))
    reread: list[tuple[str, bool]] = []

    async def spy(root, *, fetch=False):
        reread.append((str(root), fetch))

    monkeypatch.setattr(agent, "_reread_board", spy)
    got = await agent._sync_merge(ROOT, _pr(), e)
    assert got["verdict"] == "merged" and reread == [(ROOT, True)]
    reread.clear()
    e, _ = _handed(tmp_path)
    monkeypatch.setattr(sync, "merge", lambda root, n, head, **kw: "the forge refused it")
    got = await agent._sync_merge(ROOT, _pr(), e)
    assert (got or {}).get("verdict") != "merged" and reread == []


async def test_the_composed_merge_passes_subject_and_body(agent, gh, monkeypatch, tmp_path):  # noqa: F811
    e, d = _handed(tmp_path)
    monkeypatch.setattr(sync, "compose", _composer(gh))
    got_kw = {}
    monkeypatch.setattr(sync, "merge", lambda root, n, head, **kw: got_kw.update(kw, head=head))
    await agent._sync_merge(ROOT, _pr(), e)
    assert got_kw == {"subject": "the subject (#1097)", "body_file": d / "body", "head": HEAD}


@pytest.mark.parametrize("road", ["sha", "reread", "refused", "off", "held-before", "held-after"])
async def test_every_exit_of_the_merge_removes_the_dir_and_writes_no_gate_dir(agent, gh, monkeypatch, tmp_path, road):  # noqa: F811
    e, d = _handed(tmp_path)
    sha = "b" * 40 if road == "sha" else HEAD
    why = "squash-message: refused — no name" if road == "refused" else None
    monkeypatch.setattr(sync, "compose", _composer(gh, sha=sha, why=why))
    if road == "reread":
        gh["head"] = ("c" * 40, "open")
    if road == "off":
        monkeypatch.setattr(agent, "_sync_on", lambda: {"samscrape": False})
    if road.startswith("held"):
        calls = iter([road == "held-before", True])
        monkeypatch.setattr(agent, "_sync_held_by", lambda root, pr: next(calls))
    got = await agent._sync_merge(ROOT, _pr(), e)
    assert not d.exists() and "merge" not in _names(gh)
    assert got is None or "gate_dir" not in got
    if road in ("sha", "reread"):
        assert got is None, "the moved head: nothing written"
    if road == "refused":
        assert got["tries"] == 1 and got["why"] == "squash-message: refused — no name"
    if road == "held-before":
        assert "compose" not in _names(gh)


async def test_the_pass_never_writes_gate_dir_to_the_reading(agent, gh, monkeypatch):  # noqa: F811
    gh["composes"] = (True, None)
    monkeypatch.setattr(sync, "compose", _composer(gh))
    _reading(agent, _pr())
    await agent._sync_pass()
    entry = agent._repos[ROOT]["sync"]["1097"]
    assert entry["verdict"] == "merged" and "gate_dir" not in entry
    assert _names(gh) == ["login", "check", "gate", "compose", "head", "merge"]
    gate_call = next(c for c in gh["calls"] if c[0] == "gate")
    assert not Path(gh["calls"][3][1][2]).exists(), gate_call


async def test_a_tree_that_does_not_compose_merges_bare(agent, gh):  # noqa: F811
    _reading(agent, _pr())
    await agent._sync_pass()
    assert agent._repos[ROOT]["sync"]["1097"]["verdict"] == "merged"
    assert gh["calls"][-1] == ("merge", (ROOT, 1097, HEAD))


# -- the environment --------------------------------------------------------------------------------


def test_squash_message_runs_as_shiftlead_sync_with_no_model(monkeypatch, tmp_path):
    seen = {}

    def run(argv, **kw):
        seen.update(argv=argv, **kw)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setenv("AGENT_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("AGENT_MODEL_FILE", "/tmp/model")
    monkeypatch.setenv("AGENT_NAME", "grinder-ao-2")
    monkeypatch.setattr(sync.subprocess, "run", run)
    assert sync.compose("/r", 1097, tmp_path) is None
    env = seen["env"]
    assert env["AGENT_NAME"] == "shiftlead-sync" and "AGENT_MODEL" not in env and "AGENT_MODEL_FILE" not in env
    assert env["CADENCE_REPO_ROOT"] == "/r" and seen["cwd"] == "/r" and seen["timeout"] == sync.GATE_TIMEOUT
    assert seen["argv"][-7:] == [
        "forge.py",
        "squash-message",
        "1097",
        "--gate",
        str(tmp_path / "gate"),
        "--out",
        str(tmp_path),
    ]
    monkeypatch.setattr(
        sync.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 2, "", "squash-message: refused — x"),
    )
    assert sync.compose("/r", 1097, tmp_path) == "squash-message: refused — x"


# -- the round trip ---------------------------------------------------------------------------------

GH_SHIM = r"""#!{python}
import json, sys
a = sys.argv[1:]
commit = {{"commit": {{"message": "TD-1: bump the pin\n\nCo-Authored-By: Someone <s@example.com>\n",
                       "author": {{"name": "eyecantell", "email": "e@example.com"}}}}}}
if a[:2] == ["pr", "view"]:
    print(json.dumps({{"number": 1097, "title": "cadence: bump the agent-cadence pin", "url": "u", "state": "OPEN",
                      "commits": [commit]}}))
elif a[0] == "api" and a[-1].endswith("/pulls/1097/commits"):
    print(json.dumps([commit]))
elif a[0] == "api" and a[-1].endswith("/pulls/1097"):
    print(json.dumps({{"commits": 1}}))
else:
    sys.exit("unexpected gh " + " ".join(a))
"""


def test_a_squash_composed_by_the_real_forge_ends_in_merged_by_shiftlead_sync(tmp_path, monkeypatch):
    payload, why = cadence.tree(REPO)
    if payload is None or not cadence.composes(REPO)[0]:
        pytest.skip(f"this repo's pinned tree does not compose here: {why}")
    repo = tmp_path / "r"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=Person", "-c", "user.email=p@example.com"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "remote", "add", "origin", "https://github.com/ShiftLead/sample.git"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "gh").write_text(GH_SHIM.format(python=sys.executable))
    (bin_ / "gh").chmod(0o755)
    d = tmp_path / "gd"
    d.mkdir()
    (d / "gate").write_text(f"pr 1097\nexpect {HEAD}\nReview: SHIP · claude-sonnet-5-5\n")
    base = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "AGENT_MODEL": "claude-opus-5-5"}
    cp = subprocess.run(
        [sys.executable, str(payload / "scripts" / "forge.py"), "squash-message", "1097", "--gate", str(d / "gate"),
         "--out", str(d)],
        cwd=repo, env=sync.squash_env(base), capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert cp.returncode == 0, cp.stderr
    assert (d / "sha").read_text().strip() == HEAD
    subject = (d / "subject").read_text().strip()
    (tmp_path / "msg").write_text(f"{subject}\n\n{(d / 'body').read_text()}")
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-F", str(tmp_path / "msg")], check=True)
    got = subprocess.run(
        [*git, "log", "-1", "--format=%(trailers:key=Merged-by,valueonly)"], capture_output=True, text=True, check=True
    )
    assert got.stdout.strip() == "shiftlead-sync"
