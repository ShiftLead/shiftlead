"""The home hands out ledger ids (design §4.4 *A ledger entry's id is handed out by the home*, §4.7 *Entries*;
TD-696): `td_next` over a real origin and checkout, `gh` faked — the open PRs and their files — and every git
call real but `remote get-url`, which names the GitHub origin the fake answers for."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import park_ticks

from sessionorc import agent_ids, modes, paths
from sessionorc.agent_common import RpcError
from sessionorc.models import Session
from shiftlead import cli

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
LEDGER = "docs/technical_debt.md"
ARCHIVE = "docs/technical_debt_archive.md"


def _git(root: Path, *args: str) -> str:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), **GIT_ENV}
    cp = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True, env=env)
    return cp.stdout.strip()


def _ledger(*nums: int) -> str:
    return "# Ledger\n\n" + "".join(f"## TD-{n:03d}: entry {n}\n\nbody\n\n" for n in nums)


def _push(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ledger")
    _git(root, "push", "-q", "origin", "main")


def _repo(tmp_path: Path, name: str, files: dict[str, str], origin: Path | None = None) -> Path:
    """A checkout named `name` of a bare origin (a new one, or `origin`'s), its main carrying `files`."""
    if origin is None:
        origin = tmp_path / f"{name}-{len(list(tmp_path.iterdir()))}.git"
        _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
        seed = tmp_path / f"seed-{origin.stem}"
        seed.mkdir()
        _git(seed, "init", "-q", "-b", "main")
        _git(seed, "remote", "add", "origin", str(origin))
        _push(seed, files)
    root = tmp_path / f"c{len(list(tmp_path.iterdir()))}" / name
    root.parent.mkdir()
    _git(tmp_path, "clone", "-q", str(origin), str(root))
    return root


def _register(*roots: Path | str) -> None:
    reg = paths.home() / "repos.txt"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text("".join(f"{r}\n" for r in roots))


@pytest.fixture
def gh(monkeypatch):
    """The fake: `urls` names each checkout's origin URL; `prs` the open PRs, each a list of `(file, patch)`
    (patch None where GitHub leaves it out) or a string (the listing's error); `slow` a PR's read delay;
    `on_list` runs as the list is read. Every other call is the real `_run`."""
    real = agent_ids._run
    state = {"urls": {}, "prs": {}, "slow": {}, "list_error": None, "on_list": None, "calls": []}

    async def fake(argv, cwd, timeout, **kw):
        state["calls"].append(argv)
        if argv[:1] == ["git"] and argv[3:6] == ["remote", "get-url", "origin"]:
            url = state["urls"].get(argv[2])
            return (0, url + "\n", "") if url else (2, "", "error: No such remote 'origin'")
        if argv[:3] == ["gh", "pr", "list"]:
            if state["on_list"]:
                state["on_list"]()
            if state["list_error"]:
                return 1, "", state["list_error"]
            return 0, json.dumps([{"number": n} for n in state["prs"]]), ""
        if argv[:2] == ["gh", "api"]:
            n = int(argv[2].split("/")[-2])
            jq = argv[argv.index("--jq") + 1]
            if delay := state["slow"].get(n):
                try:
                    await asyncio.wait_for(asyncio.sleep(delay), timeout)
                except TimeoutError:
                    return -1, "", "timed out"
            files = state["prs"][n]
            if isinstance(files, str):
                return 1, "", files
            out = [json.dumps({"f": f, "p": p}) if json.dumps(f) in jq else "0" for f, p in files]
            return 0, "\n".join(out) + "\n", ""
        return await real(argv, cwd, timeout, **kw)

    monkeypatch.setattr(agent_ids, "_run", fake)
    return state


@pytest.fixture
async def home(agent):
    await park_ticks(agent)  # the tick's repo facts would read these checkouts with the real `gh`
    return agent


def _one(tmp_path, gh, name="shiftlead", nums=(1, 2), url="git@github.com:ShiftLead/shiftlead.git", files=None):
    root = _repo(tmp_path, name, files or {LEDGER: _ledger(*nums), ARCHIVE: _ledger()})
    gh["urls"][str(root)] = url
    _register(root)
    return root


# -- pure ---------------------------------------------------------------------------------------------


def test_an_origin_is_owner_repo_for_github_ssh_or_https_and_the_url_otherwise():
    for url in (
        "git@github.com:ShiftLead/shiftlead.git",
        "https://github.com/ShiftLead/shiftlead",
        "https://github.com/shiftlead/shiftlead.git/",
        "ssh://git@github.com/ShiftLead/shiftlead.git",
        "https://token@github.com/ShiftLead/shiftlead.git",
    ):
        assert agent_ids.origin_key(url) == "shiftlead/shiftlead", url
    assert agent_ids.origin_key("https://GitLab.com/a/B.git") == "https://gitlab.com/a/b"
    assert agent_ids.is_github("shiftlead/shiftlead") and not agent_ids.is_github("https://gitlab.com/a/b")


def test_a_patch_adds_the_headings_it_adds():
    patch = "@@ -1 +1 @@\n+## TD-012: new\n-## TD-009: gone\n ## TD-003: kept\n+## TD-7: short\n"
    assert agent_ids.added_ids(patch) == {12, 7}


def test_td_next_is_forwarded_and_refused_offline_for_a_person_too():
    """`ids.json` is the home's alone: a node never serves the call, whoever asks."""
    for caller in (None, "ao-x"):
        why = modes.offline_refusal("td_next", caller, {}, host="laptop", home="kmaster")
        assert why and "ids.json is the home's" in why and "kmaster (home) is unreachable" in why
    assert "td_next" not in modes.HOME_EDITS and "td_next" not in modes.PERSON_NODE_BOUND


# -- the RPC ----------------------------------------------------------------------------------------------


@pytest.mark.integration
async def test_count_gives_ids_in_a_row_and_the_record_keeps_who(home, gh, tmp_path):
    _one(tmp_path, gh, nums=(1, 4))
    got = await home.rpc_td_next(repo="shiftlead", count=3, caller="ao-w")
    assert got == {"repo": "shiftlead", "origin": "shiftlead/shiftlead", "ids": ["TD-005", "TD-006", "TD-007"],
                   "unread": [], "reserved": True, "why": "", "warnings": []}  # fmt: skip
    rec = json.loads(paths.ids_file().read_text())["shiftlead/shiftlead"]
    assert rec["last"] == 7 and [(g["id"], g["by"]) for g in rec["given"]] == [
        ("TD-005", "ao-w"), ("TD-006", "ao-w"), ("TD-007", "ao-w")
    ]  # fmt: skip
    assert (await home.rpc_td_next(repo="shiftlead"))["ids"] == ["TD-008"], "the last given beats main"
    assert json.loads(paths.ids_file().read_text())["shiftlead/shiftlead"]["given"][-1]["by"] == "person"
    for bad in (0, 11, "2", True):
        with pytest.raises(RpcError, match="1 to 10"):
            await home.rpc_td_next(repo="shiftlead", count=bad)


@pytest.mark.integration
async def test_two_calls_at_once_get_different_ids_and_three_all_answer(home, gh, tmp_path):
    _one(tmp_path, gh, nums=(9,))
    gh["prs"] = {50: [("README.md", "+x")]}
    gh["slow"] = {50: 0.2}
    got = await asyncio.wait_for(
        asyncio.gather(*(home.rpc_td_next(repo="shiftlead", caller=f"ao-{i}") for i in range(3))), 120
    )
    assert sorted(i for g in got for i in g["ids"]) == ["TD-010", "TD-011", "TD-012"]


@pytest.mark.integration
async def test_by_is_the_dispatchers_caller_whatever_the_call_carries(home, gh, tmp_path):
    _one(tmp_path, gh)
    req = {"id": 1, "method": "td_next", "caller": "ao-real", "params": {"repo": "shiftlead", "caller": "ao-fake",
                                                                       "by": "ao-fake"}}  # fmt: skip
    resp = await home._dispatch_inner(req)
    assert resp["result"]["ids"] == ["TD-003"], resp
    assert json.loads(paths.ids_file().read_text())["shiftlead/shiftlead"]["given"][0]["by"] == "ao-real"


@pytest.mark.integration
async def test_an_open_prs_added_heading_raises_the_floor_and_the_archive_counts(home, gh, tmp_path):
    _one(tmp_path, gh, nums=(1, 2))
    gh["prs"] = {
        7: [(LEDGER, "+## TD-040: in a PR\n"), ("src/x.py", "+## TD-099: not a ledger\n")],
        8: [(ARCHIVE, "+## TD-041: filed and archived in one PR\n")],
    }
    assert (await home.rpc_td_next(repo="shiftlead"))["ids"] == ["TD-042"]


@pytest.mark.integration
async def test_a_custom_ledger_reads_that_file_and_its_archive(home, gh, tmp_path):
    files = {".shiftlead.yml": "ledger: notes/debt.md\n", "notes/debt.md": _ledger(3),
             "notes/debt_archive.md": _ledger(20), LEDGER: _ledger(90)}  # fmt: skip
    _one(tmp_path, gh, files=files)
    gh["prs"] = {4: [("notes/debt.md", "+## TD-030: x\n"), (LEDGER, "+## TD-095: the default is not this ledger\n")]}
    assert (await home.rpc_td_next(repo="shiftlead"))["ids"] == ["TD-031"]


@pytest.mark.integration
async def test_a_pr_merged_between_the_pr_read_and_the_fetch_is_counted(home, gh, tmp_path):
    root = _one(tmp_path, gh, nums=(1,))
    seed = tmp_path / "late"
    _git(tmp_path, "clone", "-q", _git(root, "remote", "get-url", "origin"), str(seed))
    # the PR merges just as the list is read: it is not listed, and the fetch after the list has it
    gh["on_list"] = lambda: _push(seed, {LEDGER: _ledger(1, 12)})
    assert (await home.rpc_td_next(repo="shiftlead"))["ids"] == ["TD-013"]


@pytest.mark.integration
async def test_prs_not_read_are_named_and_the_ids_still_come(home, gh, tmp_path, monkeypatch):
    _one(tmp_path, gh, nums=(1,))
    gh["prs"] = {
        3: "HTTP 404: Not Found",
        4: [(LEDGER, None)],
        5: [(LEDGER, "+## TD-005: read\n")],
        6: [(LEDGER, "+## TD-060: too slow\n")],
    }
    gh["slow"] = {6: 5.0}
    monkeypatch.setattr(agent_ids, "PRS_BY", 0.5)
    got = await home.rpc_td_next(repo="shiftlead")
    assert got["ids"] == ["TD-006"]
    assert got["unread"] == [
        "open PR #3 not read: HTTP 404: Not Found",
        f"open PR #4 not read: {LEDGER} has no patch (too large a diff)",
        "open PR #6 not read: budget",
    ]
    gh["list_error"] = "API rate limit exceeded"
    assert (await home.rpc_td_next(repo="shiftlead"))["unread"] == ["open PRs not read: API rate limit exceeded"]


@pytest.mark.integration
async def test_a_listing_cut_at_3000_files_is_unread(home, gh, tmp_path):
    _one(tmp_path, gh)
    gh["prs"] = {9: [(f"f{i}", "+x") for i in range(agent_ids.FILES_CAP)]}
    got = await home.rpc_td_next(repo="shiftlead")
    assert got["unread"] == [f"open PR #9 not read: its listing is cut at {agent_ids.FILES_CAP} files"]


@pytest.mark.integration
async def test_a_list_that_fills_its_limit_is_unread_and_one_short_of_it_is_not(home, gh, tmp_path, monkeypatch):
    """TD-708: an open PR past `--limit` would go unread silently, so a list exactly at it is named."""
    monkeypatch.setattr(agent_ids, "PR_LIMIT", 3)
    _one(tmp_path, gh)
    gh["prs"] = {n: [] for n in (5, 6)}
    assert (await home.rpc_td_next(repo="shiftlead"))["unread"] == []
    gh["prs"] = {n: [] for n in (5, 6, 7)}
    got = await home.rpc_td_next(repo="shiftlead")
    assert got["unread"] == ["open PRs not read: the list filled its 3"] and got["ids"] == ["TD-004"]
    assert all(c[c.index("--limit") + 1] == "3" for c in gh["calls"] if c[:3] == ["gh", "pr", "list"])


@pytest.mark.integration
async def test_a_non_github_origin_reads_no_prs_and_names_why(home, gh, tmp_path):
    _one(tmp_path, gh, url="https://gitlab.com/a/b.git")
    got = await home.rpc_td_next(repo="shiftlead")
    assert got["origin"] == "https://gitlab.com/a/b" and got["ids"] == ["TD-003"]
    assert got["unread"] == ["open PRs not read: the origin https://gitlab.com/a/b is not GitHub's"]
    assert not [c for c in gh["calls"] if c[:1] == ["gh"]], "no gh call against a non-GitHub origin"


@pytest.mark.integration
async def test_a_repo_with_no_origin_remote_is_refused(home, gh, tmp_path):
    root = _one(tmp_path, gh)
    del gh["urls"][str(root)]
    with pytest.raises(RpcError, match="shiftlead has no origin remote"):
        await home.rpc_td_next(repo="shiftlead")
    assert not paths.ids_file().exists(), "no id is given"


@pytest.mark.integration
async def test_a_lock_not_taken_by_30_seconds_refuses_busy(home, gh, tmp_path, monkeypatch):
    _one(tmp_path, gh)
    monkeypatch.setattr(agent_ids, "LOCK_BY", 0.2)
    lock = home._ids_locks.setdefault("shiftlead/shiftlead", asyncio.Lock())
    await lock.acquire()
    try:
        with pytest.raises(RpcError, match="busy, ask again"):
            await home.rpc_td_next(repo="shiftlead")
    finally:
        lock.release()


@pytest.mark.integration
async def test_a_failed_fetch_refuses(home, gh, tmp_path):
    root = _one(tmp_path, gh)
    _git(root, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    with pytest.raises(RpcError, match="the fetch of shiftlead's origin failed"):
        await home.rpc_td_next(repo="shiftlead")
    assert not paths.ids_file().exists(), "nothing given, nothing recorded"


@pytest.mark.integration
async def test_given_keeps_the_newest_200(home, gh, tmp_path):
    _one(tmp_path, gh)
    old = [{"id": f"TD-{n:03d}", "by": "x", "at": "2026-10-01T00:00:00Z"} for n in range(1, 201)]
    paths.ids_file().write_text(json.dumps({"shiftlead/shiftlead": {"last": 200, "given": old}}))
    assert (await home.rpc_td_next(repo="shiftlead", count=2))["ids"] == ["TD-201", "TD-202"]
    given = json.loads(paths.ids_file().read_text())["shiftlead/shiftlead"]["given"]
    assert len(given) == 200 and given[0]["id"] == "TD-003" and given[-1]["id"] == "TD-202"


@pytest.mark.integration
async def test_a_shared_name_of_two_origins_is_refused_and_owner_repo_picks_one(home, gh, tmp_path):
    a = _repo(tmp_path, "tools", {LEDGER: _ledger(5)})
    b = _repo(tmp_path, "tools", {LEDGER: _ledger(70)})
    gh["urls"] = {str(a): "git@github.com:One/tools.git", str(b): "https://github.com/Two/tools"}
    _register(a, b)
    with pytest.raises(RpcError, match="different origins") as e:
        await home.rpc_td_next(repo="tools")
    assert str(a) in str(e.value) and str(b) in str(e.value)
    assert (await home.rpc_td_next(repo="Two/tools"))["ids"] == ["TD-071"]
    assert (await home.rpc_td_next(repo="one/tools"))["ids"] == ["TD-006"]


@pytest.mark.integration
async def test_two_checkouts_of_one_origin_ssh_and_https_share_one_counter(home, gh, tmp_path):
    a = _repo(tmp_path, "shiftlead", {LEDGER: _ledger(1)})
    b = _repo(tmp_path, "shiftlead-2", {}, origin=Path(_git(a, "remote", "get-url", "origin")))
    gh["urls"] = {str(a): "git@github.com:ShiftLead/shiftlead.git", str(b): "https://github.com/ShiftLead/shiftlead"}
    _register(a, b)
    assert (await home.rpc_td_next(repo="shiftlead"))["ids"] == ["TD-002"]
    assert (await home.rpc_td_next(repo="shiftlead-2"))["ids"] == ["TD-003"]
    assert (await home.rpc_td_next(repo="ShiftLead/shiftlead"))["ids"] == ["TD-004"]
    assert list(json.loads(paths.ids_file().read_text())) == ["shiftlead/shiftlead"]


@pytest.mark.integration
async def test_a_node_forwards_a_persons_call_by_name_and_refuses_it_offline(home, gh, tmp_path, monkeypatch):
    """The node's checkout is at another path: the call carries the registered name, and the home serves it."""
    _one(tmp_path, gh)
    seen = []

    async def forward(rid, name, params, caller):
        seen.append((name, dict(params), caller))
        return {"id": rid, "result": await home.rpc_td_next(**params, caller=caller)}

    home.mode, home.home = "node", "kmaster"
    monkeypatch.setattr(home, "_forward", forward)
    monkeypatch.setattr(home, "home_reachable", lambda: True)
    resp = await home._dispatch_inner({"id": 1, "method": "td_next", "params": {"repo": "shiftlead"}, "caller": None})
    assert seen == [("td_next", {"repo": "shiftlead"}, None)] and resp["result"]["ids"] == ["TD-003"]
    monkeypatch.setattr(home, "home_reachable", lambda: False)
    resp = await home._dispatch_inner({"id": 2, "method": "td_next", "params": {"repo": "shiftlead"}, "caller": None})
    assert "ids.json is the home's" in resp["error"]


# -- the CLI ------------------------------------------------------------------------------------------------


@pytest.mark.unit
def test_the_cli_sends_a_symlinked_checkouts_registered_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    real = tmp_path / "src" / "real-name"
    real.mkdir(parents=True)
    _git(real, "init", "-q", "-b", "main")
    link = tmp_path / "shiftlead"
    link.symlink_to(real)
    _register(link)
    sent = {}

    def call(method, **params):
        sent.update(params, method=method)
        return {"repo": "shiftlead", "origin": "x", "ids": ["TD-001", "TD-002"], "unread": ["open PR #3 not read: x"]}

    monkeypatch.setattr(cli, "call_sync", call)
    monkeypatch.chdir(real)
    assert cli.main(["td", "next", "--count", "2"]) == 0
    assert sent == {"method": "td_next", "repo": "shiftlead", "count": 2}
    out, err = capsys.readouterr()
    assert out == "TD-001\nTD-002\n" and "open PR #3 not read: x" in err
    assert cli.main(["--json", "td", "next"]) == 0
    assert json.loads(capsys.readouterr().out) == {"repo": "shiftlead", "ids": ["TD-001", "TD-002"],
                                                   "unread": ["open PR #3 not read: x"], "reserved": True,
                                                   "why": "", "warnings": []}  # fmt: skip


@pytest.mark.unit
def test_the_cli_sends_owner_repo_when_the_name_is_shared(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    roots = []
    for owner in ("One", "Two"):
        r = tmp_path / owner / "tools"
        r.mkdir(parents=True)
        _git(r, "init", "-q", "-b", "main")
        _git(r, "remote", "add", "origin", f"git@github.com:{owner}/tools.git")
        roots.append(r)
    _register(*roots)
    sent = {}
    monkeypatch.setattr(cli, "call_sync", lambda m, **p: sent.update(p) or {"ids": [], "unread": []})
    monkeypatch.chdir(roots[1])
    assert cli.main(["td", "next"]) == 0
    assert sent["repo"] == "two/tools"


@pytest.mark.integration
async def test_two_origins_at_once_keep_each_others_record(home, gh, tmp_path):
    a = _repo(tmp_path, "one", {LEDGER: _ledger(1)})
    b = _repo(tmp_path, "two", {LEDGER: _ledger(50)})
    gh["urls"] = {str(a): "git@github.com:O/one.git", str(b): "git@github.com:O/two.git"}
    _register(a, b)
    gh["prs"] = {1: [(LEDGER, "+x")]}
    gh["slow"] = {1: 0.1}
    await asyncio.gather(*(home.rpc_td_next(repo=r) for r in ("one", "two", "one", "two")))
    store = json.loads(paths.ids_file().read_text())
    assert (store["o/one"]["last"], store["o/two"]["last"]) == (3, 52)
    assert len(store["o/one"]["given"]) == len(store["o/two"]["given"]) == 2


@pytest.mark.integration
async def test_a_persons_call_forwarded_from_a_node_is_served_at_the_home(home, gh, tmp_path):
    _one(tmp_path, gh)
    resp = await home._forwarded("laptop", {"rpc": "td_next", "params": {"repo": "shiftlead"}, "caller": None})
    assert resp["result"]["ids"] == ["TD-003"], resp
    assert json.loads(paths.ids_file().read_text())["shiftlead/shiftlead"]["given"][0]["by"] == "person"


@pytest.mark.integration
async def test_a_listing_line_that_is_no_file_is_unread(home, gh, tmp_path, monkeypatch):
    _one(tmp_path, gh)
    gh["prs"] = {5: [(LEDGER, "+## TD-009: x\n")]}
    real = agent_ids._run

    async def null(argv, cwd, timeout):
        rc, out, err = await real(argv, cwd, timeout)
        return (0, "null\n", "") if argv[:2] == ["gh", "api"] else (rc, out, err)

    monkeypatch.setattr(agent_ids, "_run", null)
    got = await home.rpc_td_next(repo="shiftlead")
    assert got["ids"] == ["TD-003"] and got["unread"] == ["open PR #5 not read: its listing is not a list of files"]


@pytest.mark.unit
def test_the_cli_passes_an_origins_owner_repo_through(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    _register()
    sent = {}
    monkeypatch.setattr(cli, "call_sync", lambda m, **p: sent.update(p) or {"ids": ["TD-001"], "unread": []})
    monkeypatch.chdir(tmp_path)
    assert cli.main(["td", "next", "--repo", "ShiftLead/shiftlead"]) == 0
    assert sent == {"repo": "ShiftLead/shiftlead", "count": 1}


# -- TD-731: an entry can land held (§4.4 *An entry can land held*) ---------------------------------------


@pytest.mark.integration
async def test_held_lands_each_id_held_for_the_person_and_an_interactive_session(home, gh, tmp_path):
    _one(tmp_path, gh)
    home.sessions["ao-i"] = Session(id="ao-i", name="i", kind="agent", adapter="claude-code", dir="", unattended=False)
    got = await home.rpc_td_next(repo="shiftlead", count=2, held=True, caller="ao-i")
    assert got["ids"] == ["TD-003", "TD-004"] and got["held"] is True
    seen = json.loads(paths.ledger_seen_file().read_text())["shiftlead/shiftlead"]
    assert set(seen) == {"TD-003", "TD-004"} and seen["TD-003"]["held"]["by"] == "ao-i" and "at" not in seen["TD-003"]
    got = await home.rpc_td_next(repo="shiftlead", held=True)
    assert got["ids"] == ["TD-005"] and got["held"] is True
    assert json.loads(paths.ledger_seen_file().read_text())["shiftlead/shiftlead"]["TD-005"]["held"]["by"] == "person"
    plain = await home.rpc_td_next(repo="shiftlead", caller="ao-i")
    assert (
        "held" not in plain and "TD-006" not in json.loads(paths.ledger_seen_file().read_text())["shiftlead/shiftlead"]
    )


@pytest.mark.integration
async def test_held_is_refused_to_an_unattended_caller_and_one_the_graph_does_not_hold(home, gh, tmp_path):
    _one(tmp_path, gh)
    home.sessions["ao-w"] = Session(id="ao-w", name="w", kind="agent", adapter="claude-code", dir="", unattended=True)
    with pytest.raises(RpcError, match="--held is the person's and an interactive session's: ao-w is unattended"):
        await home.rpc_td_next(repo="shiftlead", held=True, caller="ao-w")
    with pytest.raises(RpcError, match="ao-gone is not a session this home holds"):
        await home.rpc_td_next(repo="shiftlead", held=True, caller="ao-gone")
    assert not paths.ledger_seen_file().exists() and not paths.ids_file().exists(), "nothing written, no id given"


@pytest.mark.unit
def test_the_cli_sends_held_and_says_so_in_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    _register()
    sent = {}
    monkeypatch.setattr(
        cli, "call_sync", lambda m, **p: sent.update(p) or {"ids": ["TD-001"], "unread": [], "held": True}
    )
    monkeypatch.chdir(tmp_path)
    assert cli.main(["td", "next", "--repo", "ShiftLead/shiftlead", "--held", "--json"]) == 0
    assert sent == {"repo": "ShiftLead/shiftlead", "count": 1, "held": True}
    assert json.loads(capsys.readouterr().out)["held"] is True


# -- TD-970: the road over origin's counter (§4.4 *A ledger entry's id is handed out by the home*) ---------------


def _stub(root: Path, rc: int = 0, ids=("TD-050",), why: str = "", unread=(), warnings=(), out=None, sleep=0.0,
          where: str = "scripts") -> Path:  # fmt: skip
    """A stand-in `ledger_next_id.py` in the checkout's working tree: it records its argv, cwd, race budget and
    pid (and a `sleep` child's, in its group) to `<root>.stub.json`, then prints `out` (the script's JSON by
    default) and exits `rc`."""
    log = root.with_suffix(".stub.json")
    body = (
        out
        if out is not None
        else json.dumps(
            {"ids": list(ids), "reserved": rc == 0, "why": why, "unread": list(unread), "warnings": list(warnings)}
        )
    )
    (root / where).mkdir(parents=True, exist_ok=True)
    (root / where / "ledger_next_id.py").write_text(
        "import json, os, subprocess, sys, time\n"
        f"child = subprocess.Popen(['sleep', '60']).pid if {sleep!r} else None\n"
        f"open({str(log)!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd(), 'pid': os.getpid(),"
        " 'child': child, 'race': os.environ.get('LEDGER_IDS_RACE_SECONDS')}))\n"
        f"time.sleep({sleep!r})\n"
        f"print({body!r})\n"
        "print('stub stderr line', file=sys.stderr)\n"
        f"sys.exit({rc})\n"
    )
    return log


def _gone(pid: int) -> bool:
    """Dead or a zombie waiting for its reaper: either way it runs nothing."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ")[1][0] in "ZX"
    except (OSError, IndexError):
        return True


@pytest.mark.integration
async def test_the_script_road_passes_the_floor_by_count_and_ledger_and_records_what_it_gave(home, gh, tmp_path):
    root = _one(tmp_path, gh, nums=(1, 2))
    paths.ids_file().write_text(json.dumps({"shiftlead/shiftlead": {"last": 40, "given": []}}))
    log = _stub(root, ids=("TD-041", "TD-042"))
    got = await home.rpc_td_next(repo="shiftlead", count=2, caller="ao-w")
    assert got == {"repo": "shiftlead", "origin": "shiftlead/shiftlead", "ids": ["TD-041", "TD-042"], "unread": [],
                   "reserved": True, "why": "", "warnings": []}  # fmt: skip
    seen = json.loads(log.read_text())
    assert seen["argv"] == ["--count", "2", "--by", "ao-w", "--floor", "40", "--ledger", LEDGER, "--archive", ARCHIVE,
                            "--json"]  # fmt: skip
    assert Path(seen["cwd"]) == root and float(seen["race"]) <= agent_ids.BUDGET - agent_ids.SCRIPT_SLACK
    rec = json.loads(paths.ids_file().read_text())["shiftlead/shiftlead"]
    assert rec["last"] == 42 and [(g["id"], g["by"]) for g in rec["given"]] == [("TD-041", "ao-w"), ("TD-042", "ao-w")]
    assert not [c for c in gh["calls"] if c[:1] == ["gh"] or "fetch" in c], "the home reads no PR and fetches nothing"
    _stub(root, ids=("TD-043",))
    await home.rpc_td_next(repo="shiftlead")
    assert json.loads(log.read_text())["argv"][3:6] == ["person", "--floor", "42"], "the last given is the next floor"


@pytest.mark.integration
async def test_a_custom_ledger_is_passed_to_the_script(home, gh, tmp_path):
    root = _one(tmp_path, gh, files={".shiftlead.yml": "ledger: notes/debt.md\n", "notes/debt.md": _ledger(3)})
    log = _stub(root)
    await home.rpc_td_next(repo="shiftlead")
    argv = json.loads(log.read_text())["argv"]
    assert argv[argv.index("--ledger") + 1] == "notes/debt.md" and argv[argv.index("--archive") + 1] == (
        "notes/debt_archive.md"
    )


@pytest.mark.integration
async def test_exit_3_gives_the_ids_unreserved_with_why_and_records_them(home, gh, tmp_path):
    root = _one(tmp_path, gh)
    _stub(root, rc=3, ids=("TD-007",), why="the push was refused with the counter unmoved: protected",
          unread=["#12", "the list (cut at 100)"], warnings=["no forge"])  # fmt: skip
    got = await home.rpc_td_next(repo="shiftlead")
    assert got["ids"] == ["TD-007"] and got["reserved"] is False
    assert got["why"] == "the push was refused with the counter unmoved: protected"
    assert got["unread"] == ["open PRs not read: #12, the list (cut at 100)"] and got["warnings"] == ["no forge"]
    assert json.loads(paths.ids_file().read_text())["shiftlead/shiftlead"]["last"] == 7


@pytest.mark.integration
async def test_exit_2_refuses_with_the_scripts_why_and_records_nothing(home, gh, tmp_path):
    root = _one(tmp_path, gh)
    _stub(root, rc=2, ids=(), why="could not fetch origin/main: unreachable")
    with pytest.raises(RpcError, match="shiftlead's ids were not given: could not fetch origin/main: unreachable"):
        await home.rpc_td_next(repo="shiftlead")
    assert not paths.ids_file().exists()


@pytest.mark.integration
async def test_a_reply_that_is_not_the_scripts_json_refuses_naming_the_exit(home, gh, tmp_path):
    root = _one(tmp_path, gh)
    for rc, out in ((2, "usage: ledger_next_id.py: unrecognized arguments: --floor"), (1, None), (0, None)):
        _stub(root, rc=rc, ids=() if rc == 0 else ("TD-009",), out=out)
        with pytest.raises(
            RpcError, match=rf"scripts/ledger_next_id.py did not answer with its JSON \(exit {rc}\): stub"
        ):
            await home.rpc_td_next(repo="shiftlead")
    assert not paths.ids_file().exists()


@pytest.mark.integration
async def test_a_script_past_the_budget_refuses_and_dies_with_its_group(home, gh, tmp_path, monkeypatch):
    root = _one(tmp_path, gh)
    monkeypatch.setattr(agent_ids, "BUDGET", 6.5)
    log = _stub(root, sleep=60.0)
    with pytest.raises(RpcError, match="budget, ask again"):
        await home.rpc_td_next(repo="shiftlead")
    seen = json.loads(log.read_text())
    assert 1.0 <= float(seen["race"]) < 6.5 - agent_ids.SCRIPT_SLACK + 0.01
    for _ in range(40):
        if _gone(seen["pid"]) and _gone(seen["child"]):
            break
        await asyncio.sleep(0.05)
    assert _gone(seen["pid"]) and _gone(seen["child"]), "the script and the git it ran are killed at the deadline"
    assert not paths.ids_file().exists()


@pytest.mark.integration
async def test_dev_cadences_own_checkout_runs_files_scripts(home, gh, tmp_path):
    root = _one(tmp_path, gh)
    log = _stub(root, where="files/scripts", ids=("TD-003",))
    assert (await home.rpc_td_next(repo="shiftlead"))["ids"] == ["TD-003"] and log.exists()
    assert agent_ids.ids_script(str(root)) == root / "files/scripts/ledger_next_id.py"
    _stub(root, where="scripts", ids=("TD-004",))
    assert agent_ids.ids_script(str(root)) == root / "scripts/ledger_next_id.py", "a syncing repo's copy first"


@pytest.mark.integration
async def test_held_holds_the_scripts_ids(home, gh, tmp_path):
    root = _one(tmp_path, gh)
    _stub(root, rc=3, ids=("TD-030",), why="no push")
    got = await home.rpc_td_next(repo="shiftlead", held=True)
    assert got["held"] is True and got["reserved"] is False
    assert "TD-030" in json.loads(paths.ledger_seen_file().read_text())["shiftlead/shiftlead"]


@pytest.mark.integration
async def test_the_home_and_a_direct_run_at_once_take_different_ids_from_one_counter(home, gh, tmp_path):
    """The real synced script, on a bare origin with no forge: one counter, with the home and without it."""
    files = {LEDGER: _ledger(1, 2), ARCHIVE: _ledger()}
    files.update({f"scripts/{p.name}": p.read_text() for p in (Path(__file__).parent.parent / "scripts").glob("*.py")})
    root = _one(tmp_path, gh, files=files)
    other = _repo(tmp_path, "other", {}, origin=Path(_git(root, "remote", "get-url", "origin")))
    env = {**os.environ, **GIT_ENV, "LEDGER_IDS_RACE_SECONDS": "20"}

    def direct() -> str:
        cp = subprocess.run([sys.executable, "scripts/ledger_next_id.py", "--json", "--by", "direct"], cwd=other,
                            capture_output=True, text=True, env=env, timeout=60)  # fmt: skip
        assert cp.returncode == 0, cp.stderr
        return json.loads(cp.stdout)["ids"][0]

    mine, theirs = await asyncio.gather(home.rpc_td_next(repo="shiftlead", caller="ao-w"), asyncio.to_thread(direct))
    assert mine["reserved"] is True and mine["ids"][0] != theirs and {mine["ids"][0], theirs} == {"TD-003", "TD-004"}
    origin = _git(root, "remote", "get-url", "origin")
    assert _git(Path(origin), "show", "cadence/ledger-ids:LAST").strip() == "4"


@pytest.mark.unit
def test_the_cli_says_an_unreserved_id_and_each_warning_on_stderr_and_exits_0(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    _register()
    reply = {"repo": "shiftlead", "ids": ["TD-005"], "unread": [], "reserved": False, "why": "no push rights",
             "warnings": ["the counter's LAST is absent"]}  # fmt: skip
    monkeypatch.setattr(cli, "call_sync", lambda m, **p: reply)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["td", "next", "--repo", "ShiftLead/shiftlead"]) == 0
    out, err = capsys.readouterr()
    assert out == "TD-005\n"
    assert "not reserved on origin's counter: no push rights" in err and "the counter's LAST is absent" in err
    assert cli.main(["--json", "td", "next", "--repo", "ShiftLead/shiftlead"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert (got["reserved"], got["why"], got["warnings"]) == (False, "no push rights", ["the counter's LAST is absent"])


def test_the_offline_refusal_names_the_script():
    why = modes.offline_refusal("td_next", "ao-x", {}, host="laptop", home="kmaster")
    assert "scripts/ledger_next_id.py" in why
