"""TD-940, design §4.7 *ao pr wait*: a block on the home's folded reading of a PR's checks — the
word and its exit code, the wake on the reading's refresh, `--fresh` counting only a later read, a
number the reading does not hold, and the client's words for each."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from conftest import park_ticks

from sessionorc import identity, modes, reports
from sessionorc.client import AgentError, LocalClient


def _row(n: int = 7, checks: str = "pending", conflicting: bool = False, failing: list[str] | None = None):
    return {
        "number": n,
        "url": f"https://example.invalid/pull/{n}",
        "head": "abc1234def",
        "checks": checks,
        "conflicting": conflicting,
        "failing": failing or [],
    }


def _reading(root: str, rows: list[dict], at: datetime) -> dict:
    return {"name": "r", "root": root, "prs": {"open": rows, "at": at.isoformat()}, "at": at.isoformat()}


def test_the_word_puts_a_conflict_first_and_reads_not_run_as_red():
    assert reports.pr_wait_word(_row(checks="pending", conflicting=True)) == "conflicting"
    assert reports.pr_wait_word(_row(checks="none", conflicting=True)) == "conflicting"
    assert reports.pr_wait_word(_row(checks="red")) == "red"
    assert reports.pr_wait_word(_row(checks="not_run")) == "red"
    assert reports.pr_wait_word(_row(checks="green")) == "green"
    assert reports.pr_wait_word(_row(checks="pending")) == "pending"
    assert reports.pr_wait_word({"number": 7}) == "none"
    assert reports.PR_WAIT_EXIT == {"green": 0, "red": 1, "conflicting": 2, "none": 3, "timeout": 4, "gone": 5}


def test_pr_wait_is_a_home_read_that_blocks_on_its_own_connection():
    assert "pr_wait" in identity.READS and "pr_wait" in modes.HOME_READS
    assert {"wait", "pr_wait"} == modes.BLOCKING
    why = modes.offline_refusal("pr_wait", None, {}, host="laptop", home="kmaster")
    assert why and "kmaster (home)" in why


async def test_a_wait_returns_at_the_refresh_that_leaves_pending(agent, tmp_path):
    await park_ticks(agent)
    agent.PR_WAIT_STEP = 0.05
    root = str(tmp_path)
    now = datetime.now(UTC)
    agent._repos[root] = _reading(root, [_row(checks="pending")], now)
    async with LocalClient() as c:
        call = asyncio.create_task(c.call("pr_wait", root=root, pr=7, timeout=10))
        await asyncio.sleep(0.2)
        assert not call.done(), "pending: the wait holds"
        agent._repos[root] = _reading(root, [_row(checks="red", failing=["test (3.12)"])], datetime.now(UTC))
        got = await asyncio.wait_for(call, 5)
    assert got["word"] == "red" and got["failing"] == ["test (3.12)"] and got["head"] == "abc1234def"
    assert got["read_at"] and got["conflicting"] is False and got["pr"] == 7


async def test_a_settled_reading_answers_at_once_and_fresh_waits_for_a_later_read(agent, tmp_path):
    await park_ticks(agent)
    agent.PR_WAIT_STEP = 0.05
    root = str(tmp_path)
    old = datetime.now(UTC) - timedelta(minutes=3)
    agent._repos[root] = _reading(root, [_row(checks="green")], old)
    async with LocalClient() as c:
        got = await c.call("pr_wait", root=root, pr=7, timeout=5)
        assert got["word"] == "green"
        agent._repos_read_at = 0.0
        call = asyncio.create_task(c.call("pr_wait", root=root, pr=7, timeout=10, fresh=True))
        await asyncio.sleep(0.2)
        assert not call.done(), "fresh: the reading before the call does not count"
        assert agent._repos_fresh is True, "fresh makes the next tick's PR pass due"
        agent._repos[root] = _reading(root, [_row(checks="pending", conflicting=True)], datetime.now(UTC))
        got = await asyncio.wait_for(call, 5)
    assert got["word"] == "conflicting"


async def test_a_number_the_reading_does_not_hold_is_gone_only_after_a_later_read(agent, tmp_path):
    await park_ticks(agent)
    agent.PR_WAIT_STEP = 0.05
    root = str(tmp_path)
    agent._repos[root] = _reading(root, [], datetime.now(UTC) - timedelta(minutes=2))
    async with LocalClient() as c:
        call = asyncio.create_task(c.call("pr_wait", root=root, pr=8, timeout=10))
        await asyncio.sleep(0.2)
        assert not call.done(), "a PR opened a minute ago is not yet in the reading before the call"
        agent._repos[root] = _reading(root, [_row(n=7)], datetime.now(UTC))
        got = await asyncio.wait_for(call, 5)
        assert got["word"] == "gone" and got["head"] is None
        got = await c.call("pr_wait", root=root, pr=7, timeout=0.2)
        assert got["word"] == "timeout" and got["checks"] == "pending" and got["read_error"] is None
        agent._repos[root]["prs"]["error"] = "gh: offline"
        got = await c.call("pr_wait", root=root, pr=7, timeout=0.2)
        assert got["word"] == "timeout" and got["read_error"] == "gh: offline"
        with pytest.raises(AgentError, match="holds no reading"):
            await c.call("pr_wait", root=str(tmp_path / "elsewhere"), pr=7, timeout=1)


async def test_a_closed_client_ends_the_wait_at_the_home(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    agent.PR_WAIT_STEP = 0.05
    root = str(tmp_path)
    agent._repos[root] = _reading(root, [_row(checks="pending")], datetime.now(UTC))
    looks = 0
    real = reports.pr_wait_word

    def counting(row):
        nonlocal looks
        looks += 1
        return real(row)

    monkeypatch.setattr(reports, "pr_wait_word", counting)
    c = LocalClient()
    await c.__aenter__()
    call = asyncio.create_task(c.call("pr_wait", root=root, pr=7, timeout=30))
    await asyncio.sleep(0.2)
    assert looks, "the wait looks at the reading"
    call.cancel()
    await c.__aexit__(None, None, None)
    await asyncio.sleep(0.2)
    seen = looks
    await asyncio.sleep(0.3)
    assert looks == seen, "the wait stopped looking once its client went"


async def test_a_fresh_asked_while_a_pass_runs_gets_the_pass_after_it(agent, tmp_path, monkeypatch):
    """The pass clears the ask before its read, so one made during the read survives it (review of TD-940)."""
    await park_ticks(agent)
    asked = []

    def reading(d, now, **kw):
        asked.append(d)
        agent._repos_fresh = True  # a `--fresh` arriving mid-read
        return {"open": [], "windows": {}, "recent": [], "at": now.isoformat()}

    monkeypatch.setattr(reports, "pr_reading", reading)
    import time

    agent._repos_read_at = time.monotonic()  # not due by the clock
    agent._repos_fresh = True
    monkeypatch.setattr("sessionorc.hosts.Host.repos", lambda self: [str(tmp_path)])
    await agent._refresh_repos()
    assert asked, "the asked pass ran though the clock said not due"
    assert agent._repos_fresh is True, "the ask made during it stands for the next"


# -- the client ------------------------------------------------------------------------------------


def _args(**kw) -> argparse.Namespace:
    base = {"action": "wait", "n": 7, "id": None, "timeout": 60.0, "fresh": False, "json": False}
    return argparse.Namespace(**{**base, **kw})


@pytest.mark.parametrize(
    ("word", "code", "said"),
    [
        ("green", 0, "PR #7 green on abc1234"),
        ("red", 1, "PR #7 red on abc1234: test (3.12)"),
        ("conflicting", 2, "PR #7 conflicting on abc1234"),
        ("none", 3, "PR #7 none on abc1234"),
        ("timeout", 4, "PR #7 timeout after 60s, still pending on abc1234"),
    ],
)
def test_ao_pr_wait_says_the_word_and_exits_by_it(monkeypatch, capsys, word, code, said):
    from shiftlead import cli

    calls = []

    def fake(method, **kw):
        calls.append((method, kw))
        if method == "get":
            return {"id": kw["id"], "repo": "/r"}
        row = _row(checks="pending" if word == "timeout" else word, failing=["test (3.12)"] if word == "red" else [])
        return {**row, "pr": 7, "word": word, "read_at": "2026-10-21T00:00:00+00:00"}

    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x")
    monkeypatch.setattr(cli, "call_sync", fake)
    assert cli.cmd_pr(_args()) == code
    assert capsys.readouterr().out.strip() == said
    method, kw = calls[-1]
    assert method == "pr_wait" and kw["root"] == "/r" and kw["pr"] == 7 and kw["fresh"] is False
    assert kw["_timeout"] > kw["timeout"], "the client outlasts the wait it asked for"


def test_ao_pr_wait_refuses_a_number_the_home_does_not_hold_and_an_old_home(monkeypatch, capsys):
    from shiftlead import cli

    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x")
    monkeypatch.setattr(
        cli, "call_sync", lambda m, **kw: {"repo": "/r"} if m == "get" else {"pr": 7, "word": "gone", "head": None}
    )
    assert cli.cmd_pr(_args()) == 5
    assert "not open in the home's reading of /r" in capsys.readouterr().err

    def old(m, **kw):
        if m == "get":
            return {"repo": "/r"}
        raise AgentError("unknown method 'pr_wait'")

    monkeypatch.setattr(cli, "call_sync", old)
    assert cli.cmd_pr(_args(json=True)) == 5
    assert "predates ao pr wait" in capsys.readouterr().out


# -- the fold per forge (slice 2) -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("remote", "want"),
    [
        ("git@github.com:ShiftLead/shiftlead.git", ("github", "")),
        ("https://github.com/ShiftLead/shiftlead", ("github", "")),
        ("/home/k/repo", ("github", "")),
        ("file:///tmp/r.git", ("github", "")),
        ("", ("github", "")),
        ("git@gitlab.com:group/sub/repo.git", ("gitlab", "gitlab.com/group/sub/repo")),
        ("https://gitlab.corp.example/team/repo", ("gitlab", "gitlab.corp.example/team/repo")),
        ("https://gitlab.com/onlygroup", ("other", "gitlab.com")),
        ("https://gitea.example/a/b", ("other", "gitea.example")),
    ],
)
def test_the_forge_is_picked_by_the_origins_host(remote, want):
    assert reports.forge_of(remote) == want


def _mr(iid=3, status: str | None = "running", merge="mergeable", conflicts=False):
    return {
        "iid": iid,
        "title": "t",
        "web_url": f"https://gitlab.com/g/r/-/merge_requests/{iid}",
        "source_branch": "b",
        "target_branch": "main",
        "sha": "fed0987",
        "author": {"username": "u"},
        "created_at": "2026-10-21T00:00:00Z",
        "source_project_id": 1,
        "target_project_id": 1,
        "has_conflicts": conflicts,
        "detailed_merge_status": merge,
        **({"head_pipeline": {"id": 77, "status": status}} if status else {"head_pipeline": None}),
    }


# one fixture per word, on both forges: a GitHub rollup and a GitLab merge request
FOLDS = [
    ("green", [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS", "name": "t"}], "success"),
    ("red", [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE", "name": "t"}], "failed"),
    (
        "red",
        [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "ACTION_REQUIRED", "name": "t"}],
        "manual",
    ),
    ("pending", [{"__typename": "CheckRun", "status": "IN_PROGRESS", "name": "t"}], "running"),
    ("pending", [{"__typename": "StatusContext", "state": "PENDING", "context": "t"}], "a status not yet known"),
    ("none", [], None),
]


@pytest.mark.parametrize(("word", "rollup", "status"), FOLDS)
def test_each_forges_fold_gives_the_same_word(word, rollup, status):
    gh, _ = reports.fold_checks(rollup)
    gl, failing = reports.fold_pipeline(_mr(status=status))
    assert gh == gl == word
    assert failing == (["pipeline 77"] if word == "red" else [])
    for checks in (gh, gl):
        assert reports.pr_wait_word({"checks": checks, "conflicting": False}) == word


def _glab(monkeypatch, mrs, jobs=None, fail=None):
    asked = []

    def fake(directory, host, path, timeout):
        asked.append((host, path))
        if fail and fail in path:
            return None, "glab: HTTP 401"
        if path.endswith("per_page=100") and "/merge_requests?" in path:
            return [{k: v for k, v in m.items() if k != "head_pipeline"} for m in mrs], None
        if "/jobs" in path:
            return jobs or [], None
        iid = int(path.rsplit("/", 1)[1])
        return next(m for m in mrs if m["iid"] == iid), None

    monkeypatch.setattr(reports, "_glab_api", fake)
    return asked


def test_a_gitlab_origin_reads_its_open_mrs_with_the_fold_conflict_and_required(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    jobs = [{"name": "test", "allow_failure": False}, {"name": "lint", "allow_failure": True}, {"name": "build"}]
    asked = _glab(monkeypatch, [_mr(3, "failed"), _mr(4, None, merge="conflict"), _mr(5, "success")], jobs)
    got = reports.pr_reading(tmp_path, now, remote="git@gitlab.com:g/sub/r.git")
    assert asked[0] == (
        "gitlab.com",
        "projects/g%2Fsub%2Fr/merge_requests?state=opened&order_by=created_at&sort=asc&per_page=100",
    )
    rows = {p["number"]: p for p in got["open"]}
    assert rows[3]["checks"] == "red" and rows[3]["failing"] == ["pipeline 77"] and rows[3]["red_since"]
    assert rows[3]["required"] == ["build", "test"] and rows[3]["head"] == "fed0987" and rows[3]["base"] == "main"
    assert rows[4]["checks"] == "none" and rows[4]["conflicting"] is True and "required" not in rows[4]
    assert reports.pr_wait_word(rows[4]) == "conflicting" and reports.pr_wait_word(rows[5]) == "green"
    assert "windows" not in got and "recent" not in got and "not read on GitLab" in got["unread"]
    kept = reports.pr_reading(tmp_path, now + timedelta(minutes=5), remote="git@gitlab.com:g/sub/r.git", old=got)
    assert kept["open"][0]["red_since"] == rows[3]["red_since"], "a red spell keeps its start"


def test_a_gitlab_read_that_fails_is_an_error_and_another_forge_has_no_reading(tmp_path, monkeypatch):
    _glab(monkeypatch, [_mr()], fail="merge_requests?")
    assert reports.pr_reading(tmp_path, datetime.now(UTC), remote="https://gitlab.com/g/r") == {
        "error": "glab: HTTP 401"
    }
    _glab(monkeypatch, [_mr()], fail="/jobs")
    row = reports.pr_reading(tmp_path, datetime.now(UTC), remote="https://gitlab.com/g/r")["open"][0]
    assert row["required_error"] == "glab: HTTP 401" and "required" not in row
    many = [{"name": f"j{i}", "allow_failure": False} for i in range(100)]
    _glab(monkeypatch, [_mr()], jobs=many)
    row = reports.pr_reading(tmp_path, datetime.now(UTC), remote="https://gitlab.com/g/r")["open"][0]
    assert row["required_cut"] is True and len(row["required"]) == 100


async def test_ao_pr_wait_returns_a_gitlab_mrs_word(agent, tmp_path, monkeypatch):
    await park_ticks(agent)
    agent.PR_WAIT_STEP = 0.05
    _glab(monkeypatch, [_mr(3, "failed")])
    root = str(tmp_path)
    prs = reports.pr_reading(tmp_path, datetime.now(UTC), remote="https://gitlab.com/g/r")
    agent._repos[root] = {"name": "r", "root": root, "prs": prs, "at": prs["at"]}
    async with LocalClient() as c:
        got = await c.call("pr_wait", root=root, pr=3, timeout=5)
    assert got["word"] == "red" and got["failing"] == ["pipeline 77"]
    assert reports.PR_WAIT_EXIT[got["word"]] == 1


async def test_a_repo_never_read_is_refused_with_the_readings_why(agent, tmp_path, monkeypatch, capsys):
    await park_ticks(agent)
    root = str(tmp_path)
    why = "gh: none of the git remotes configured for this repository point to a known GitHub host (gitea.example)"
    agent.PR_WAIT_STEP = 0.05
    agent._repos[root] = {
        "name": "r",
        "root": root,
        "remote": "https://github.com/a/b",
        "prs": {"error": "gh: offline"},
    }
    async with LocalClient() as c:
        got = await c.call("pr_wait", root=root, pr=3, timeout=0.3)
        assert got["word"] == "timeout", "a GitHub repo whose first read failed is waited on, never refused"
        agent._repos[root] = {"name": "r", "root": root, "remote": "https://gitea.example/a/b", "prs": {"error": why}}
        got = await c.call("pr_wait", root=root, pr=3, timeout=5)
    assert got["word"] == "gone" and got["read_error"] == why and got["read_at"] is None
    from shiftlead import cli

    monkeypatch.setenv("SHIFTLEAD_SESSION", "ao-x")
    monkeypatch.setattr(cli, "call_sync", lambda m, **kw: {"repo": root} if m == "get" else got)
    assert cli.cmd_pr(_args(n=3)) == 5
    assert "gitea.example" in capsys.readouterr().err
