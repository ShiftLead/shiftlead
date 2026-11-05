"""The home's witness log (design §4.4 *The home keeps a log of what it witnesses*, TD-1386, TD-1390): the
log's files, ids, start and months kept, a record's `<repo>` id, `witness_press` and the places that send it,
and the host file."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import tomllib
from datetime import UTC, datetime

import pytest

from sessionorc import agent_common, mail, modes, witness
from sessionorc import push as push_mod
from sessionorc.client import AgentError, LocalClient
from shiftlead import teamrun

T0 = datetime(2026, 11, 4, 12, tzinfo=UTC)


def test_a_record_is_one_line_of_its_months_file_and_reads_in_at_order(tmp_path):
    d = tmp_path / "w"
    assert witness.append("press", "r", "apply t", T0, root=d) is None, "nothing before the log's start"
    witness.ensure_start(datetime(2026, 9, 1, tzinfo=UTC), root=d)
    assert witness.ensure_start(T0, root=d) == datetime(2026, 9, 1, tzinfo=UTC), "start is written once"
    a = witness.append("press", "r", "apply  t\nx", T0, root=d)
    assert a and a["text"] == "apply t x" and a["kind"] == "press" and a["repo"] == "r"
    assert a["at"] == "2026-11-04T12:00:00Z" and a["id"].startswith("w-20261104T120000Z-") and len(a["id"]) == 23
    assert witness.ID_RE.fullmatch(a["id"])
    late = witness.append("press", "o/r", "host-rebuild n", datetime(2026, 10, 30, tzinfo=UTC), root=d)
    assert late and (d / "2026-10.jsonl").is_file() and (d / "2026-11.jsonl").is_file(), "a late record: its month"
    assert witness.append("press", "o/r", "x", datetime(2026, 8, 31, tzinfo=UTC), root=d) is None, "before start"
    with (d / "2026-11.jsonl").open("a") as f:
        f.write("not json\n")
    assert [r["id"] for r in witness.records(d)] == [late["id"], a["id"]], "sorted by at, the bad line skipped"
    with pytest.raises(ValueError, match="not a witness kind"):
        witness.append("msg", "o/r", "x", T0, root=d)
    for empty in ("", "  "):
        with pytest.raises(ValueError, match="names the repo"):
            witness.append("press", empty, "x", T0, root=d)


def test_at_is_written_within_the_readers_subset(tmp_path):
    """TD-045 rule 12: `YYYY-MM-DDTHH:MM[:SS[.ffffff]]Z`."""
    d = tmp_path / "w"
    witness.ensure_start(datetime(2026, 1, 1, tzinfo=UTC), root=d)
    subset = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?Z")
    for at in (T0, datetime(2026, 11, 4, 12, 0, 5, 123456, tzinfo=UTC)):
        assert subset.fullmatch(witness.append("press", "o/r", "x y", at, root=d)["at"])


def test_a_colliding_id_is_drawn_again(tmp_path, monkeypatch):
    d = tmp_path / "w"
    witness.ensure_start(datetime(2026, 1, 1, tzinfo=UTC), root=d)
    tails = iter(["abcd", "abcd", "abcd", "beef"])
    monkeypatch.setattr(witness.secrets, "token_hex", lambda n: next(tails))
    one = witness.append("press", "o/r", "a x", T0, root=d)
    two = witness.append("press", "o/r", "b x", T0, root=d)
    assert one["id"].endswith("-abcd") and two["id"].endswith("-beef")


def test_the_prune_keeps_thirteen_months_counted_from_the_calendar(tmp_path):
    d = tmp_path / "w"
    d.mkdir()
    for m in ("2025-10", "2025-11", "2025-12", "2026-11"):
        (d / f"{m}.jsonl").write_text("")
    assert witness.boundary(T0) == datetime(2025, 11, 1, tzinfo=UTC)
    assert witness.prune(T0, root=d) == ["2025-10.jsonl"]
    assert sorted(f.name for f in d.iterdir()) == ["2025-11.jsonl", "2025-12.jsonl", "2026-11.jsonl"]


def test_the_log_and_its_host_file_are_in_the_nightly_tarball():
    assert "witnessed" in agent_common.BACKUP_MEMBERS and "host-log.toml" in agent_common.BACKUP_MEMBERS


def test_a_directory_maps_to_its_registered_repo_through_a_symlink(tmp_path):
    repo = tmp_path / "shiftlead"
    (repo / ".claude" / "worktrees" / "g").mkdir(parents=True)
    (tmp_path / "link").symlink_to(repo)
    roots = [str(repo), str(tmp_path / "other")]
    assert witness.repo_named(str(tmp_path / "link"), roots) == (str(repo), "shiftlead")
    assert witness.repo_named(str(repo / ".claude" / "worktrees" / "g"), roots) == (str(repo), "shiftlead")
    assert witness.repo_named(str(tmp_path / "elsewhere"), roots) is None
    assert witness.repo_named("", roots) is None and witness.repo_named(None, roots) is None
    # a symlinked registered root matches, and is given as registered (as the repo facts key it)
    assert witness.repo_named(str(repo / "src"), [str(tmp_path / "link")]) == (str(tmp_path / "link"), "link")


def test_witness_press_is_the_persons_own_and_the_homes_alone():
    assert "witness_press" in mail.PERSON_ONLY and "witness_press" in modes.HOME_EDITS
    assert "witness_press" in modes.HOME_ONLY, "refused when forwarded from a node"


ORIGIN = "git@github.com:Org/ShiftLead.git"


def _registered(agent, repo, remote: str = ORIGIN) -> None:
    agent._witness_repo = lambda d: witness.repo_named(d, [str(repo)])
    agent._repos[str(repo)] = {"name": repo.name, "root": str(repo), "remote": remote}


@pytest.mark.integration
async def test_a_press_is_recorded_with_its_repo_and_refused_for_an_unknown_word(agent, tmp_path):
    """A session's call is refused as every person-only RPC is (tests/test_person_only.py)."""
    repo = tmp_path / "shiftlead"
    repo.mkdir()
    _registered(agent, repo)
    assert witness.start() is not None, "start is written at the agent's start"
    async with LocalClient() as person:
        got = await person.call("witness_press", word="apply", target="dc-grind", dir=str(repo))
        assert got["recorded"]
        got = await person.call("witness_press", word="host-rebuild", target="contractmatch")
        assert got["recorded"], "a word with no dir"
        got = await person.call("witness_press", word="new-session", target="", dir=str(repo))
        assert got["recorded"], "no team: the home names the repo"
        with pytest.raises(AgentError, match="target names"):
            await person.call("witness_press", word="host-rebuild", target="")
        for d in ("", str(tmp_path / "nowhere")):
            got = await person.call("witness_press", word="start", target="dc-grind", dir=d)
            assert got["recorded"] is None, "a press on a directory in no registered repo is not recorded"
        with pytest.raises(AgentError, match="not a press word"):
            await person.call("witness_press", word="relaunch", target="x")
    recs = witness.records()
    assert [(r["kind"], r["repo"], r["text"]) for r in recs] == [
        ("press", "org/shiftlead", "apply dc-grind"),
        ("press", "shiftlead/shiftlead", "host-rebuild contractmatch"),
        ("press", "org/shiftlead", "new-session shiftlead"),
    ], "the repo's lowercased origin path in `repo`, its registry name in the text; no dir: OWN_REPO"


@pytest.mark.integration
async def test_a_press_reads_the_origin_once_off_the_loop_where_the_reading_has_none(agent, tmp_path, monkeypatch):
    from sessionorc import reports

    repo = tmp_path / "shiftlead"
    repo.mkdir()
    origins = {"": "", "x": "https://github.com/o/Other.git"}
    reads: list[tuple[str, bool]] = []
    loop_thread = threading.get_ident()

    def git_origin(root):
        reads.append((root, threading.get_ident() != loop_thread))
        return origins["x"]

    monkeypatch.setattr(reports, "git_origin", git_origin)
    agent._witness_repo = lambda d: witness.repo_named(d, [str(repo)])
    agent._repos.pop(str(repo), None)
    assert await agent._witness_press_of("apply", "t", str(repo)), "no reading: read off the loop"
    agent._repos[str(repo)] = {"root": str(repo), "remote": ""}
    assert await agent._witness_press_of("start", "t", str(repo)), "an empty remote: read again"
    assert reads == [(str(repo), True), (str(repo), True)]
    agent._repos[str(repo)] = {"root": str(repo), "remote": ORIGIN}
    assert await agent._witness_press_of("apply", "u", str(repo))
    assert len(reads) == 2, "the reading's remote is the id's, with no read"
    assert [r["repo"] for r in witness.records()] == ["o/other", "o/other", "org/shiftlead"]
    origins["x"] = ""
    agent._repos.pop(str(repo))
    assert await agent._witness_press_of("apply", "v", str(repo)) is None, "no readable origin: nothing recorded"
    assert len(witness.records()) == 3


@pytest.mark.integration
async def test_a_node_writes_no_record_and_refuses_the_press(agent):
    agent.mode = "node"
    try:
        assert agent._witness("press", "o/r", "apply x") is None
        witness.host_file().unlink()
        agent._witness_begin()
        assert not witness.host_file().exists(), "a node keeps no host file"
        with pytest.raises(Exception, match="runs at the home"):
            await agent.rpc_witness_press(word="host-rebuild", target="n")
    finally:
        agent.mode = "home"
    assert witness.records() == []


@pytest.mark.integration
async def test_a_record_from_a_detached_writer_lands_whole_beside_one_from_the_loop(agent):
    t = threading.Thread(target=lambda: agent._witness_soon("press", "o/r", "host-rebuild a" + " x" * 200))
    t.start()
    agent._witness("press", "o/r", "host-rebuild b")
    t.join()
    await asyncio.sleep(0)
    texts = sorted(r["text"][:14] for r in witness.records())
    assert texts == ["host-rebuild a", "host-rebuild b"]
    for line in (witness.directory() / f"{datetime.now(UTC):%Y-%m}.jsonl").read_text().splitlines():
        json.loads(line)


@pytest.mark.integration
async def test_a_writers_failure_leaves_its_act_standing(agent, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(witness, "append", boom)
    async with LocalClient() as person:
        assert (await person.call("witness_press", word="host-rebuild", target="n"))["recorded"] is None


@pytest.mark.integration
async def test_push_on_is_witnessed_for_a_new_endpoint_and_not_for_a_renewal_naming_a_held_device(agent):
    import base64

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    public = b64(b"\x04" + b"k" * 64)
    keys = {"p256dh": b64(b"\x04" + b"p" * 64), "auth": b64(b"a" * 16)}
    push_mod.save({"key": push_mod.KEY, "public_key": public, "devices": []})
    async with LocalClient() as person:
        one = (await person.call("push_subscribe", endpoint="https://p.example.com/1", keys=keys, key=public))["id"]
        await person.call("push_subscribe", endpoint="https://p.example.com/1", keys=keys, key=public)
        await person.call("push_subscribe", endpoint="https://p.example.com/2", keys=keys, key=public, replaces=one)
        await person.call("push_subscribe", endpoint="https://p.example.com/3", keys=keys, key=public, replaces="gone")
    assert [(r["repo"], r["text"]) for r in witness.records()] == [
        (witness.OWN_REPO, f"push-on {one}"),
        (witness.OWN_REPO, f"push-on {push_mod.device_id('https://p.example.com/3')}"),
    ], "a renewal it cannot name reads as a new device; an install's event is tied to OWN_REPO"


def test_the_press_helper_sends_the_word_and_swallows_a_refusal():
    sent: list[dict] = []

    def call(method, **params):
        sent.append({"method": method, **params})
        raise AgentError("a session may not record a press")

    teamrun.witness_press(call, "host-rebuild", "contractmatch")
    teamrun.witness_press(call, "apply", "dc-grind", "/r")
    assert sent == [
        {"method": "witness_press", "word": "host-rebuild", "target": "contractmatch"},
        {"method": "witness_press", "word": "apply", "target": "dc-grind", "dir": "/r"},
    ]


def test_an_apply_that_applied_nothing_sends_no_press(monkeypatch):
    sent: list[str] = []

    def call(method, **params):
        sent.append(method)
        return []

    monkeypatch.setattr(teamrun.teams, "find", lambda org, name: object())
    monkeypatch.setattr(teamrun.teams, "current_flow", lambda team: "td")
    got = teamrun.apply(call, None, "dc-grind", "kmaster")
    assert got["applied"] == [] and "witness_press" not in sent


# ── the `precheck-fail` writer (slice 2) ─────────────────────────────────────────────────────────────

SHA = "a1b2c3d4e5f6" + "0" * 28


def _st(sid, state, at, context="cadence/precheck"):
    return {"id": sid, "state": state, "created_at": at, "context": context, "target_url": ""}


def test_each_red_status_is_one_record_dated_by_its_created_at_and_written_once(tmp_path):
    """fail, pass, fail on one head is two records; a re-read writes none; `error` is red; ids 12 and 123
    are two (the whole-token match); a restart (the cache gone) writes nothing twice."""
    d = tmp_path / "w"
    witness.ensure_start(datetime(2026, 10, 1, tzinfo=UTC), root=d)
    statuses = [
        _st(123, "error", "2026-11-04T10:30:00Z"),
        _st(11, "success", "2026-11-04T10:10:00Z"),
        _st(12, "failure", "2026-11-04T10:00:00Z"),
        _st(13, "pending", "2026-11-04T09:59:00Z"),
    ]
    fails = witness.precheck_fails("shiftlead#7", SHA, statuses)
    assert [(at.isoformat(), text, sid) for at, text, sid in fails] == [
        ("2026-11-04T10:00:00+00:00", "shiftlead#7 a1b2c3d4e5f6 status 12", "12"),
        ("2026-11-04T10:30:00+00:00", "shiftlead#7 a1b2c3d4e5f6 status 123", "123"),
    ], "a PR's names no test"

    def write():
        return [witness.append_precheck_fail("shiftlead", t, sid, at, now=T0, root=d) for at, t, sid in fails]

    assert all(write()) and [r["at"] for r in witness.records(d)] == ["2026-11-04T10:00:00Z", "2026-11-04T10:30:00Z"]
    assert write() == [None, None], "a re-read of an unchanged list writes none"
    witness._recorded.clear()
    assert write() == [None, None], "a restart writes nothing twice"
    assert {r["repo"] for r in witness.records(d)} == {"shiftlead"} and len(witness.records(d)) == 2


def test_a_status_before_start_or_past_the_months_kept_is_not_written(tmp_path):
    d = tmp_path / "w"
    witness.ensure_start(datetime(2026, 11, 4, 9, tzinfo=UTC), root=d)
    before = datetime(2026, 11, 4, 8, tzinfo=UTC)
    assert witness.append_precheck_fail("r", "r@main x status 1", "1", before, now=T0, root=d) is None
    d2 = tmp_path / "w2"
    witness.ensure_start(datetime(2024, 1, 1, tzinfo=UTC), root=d2)
    old = datetime(2025, 10, 31, tzinfo=UTC)  # the boundary on 2026-11-04 is 2025-11-01
    assert witness.append_precheck_fail("r", "r@main x status 2", "2", old, now=T0, root=d2) is None
    assert not (d2 / "2025-10.jsonl").exists(), "a pruned month is never recreated"
    two_months = datetime(2026, 9, 2, tzinfo=UTC)
    assert witness.append_precheck_fail("r", "r@main x status 3", "3", two_months, now=T0, root=d2)
    witness._recorded.clear()
    assert witness.append_precheck_fail("r", "r@main x status 3", "3", two_months, now=T0, root=d2) is None


def test_the_homes_own_run_on_main_names_its_failed_tests_and_no_other_status_does(tmp_path):
    log = tmp_path / "precheck.log"
    log.write_text(
        "...\nFAILED tests/test_a.py::test_x - AssertionError\nFAILED tests/test_b.py::test_y[1]\n"
        "FAILED tests/test_a.py::test_x - again\nFAILED (errors=1)\n 1 failed\n"
    )
    own = {"sha": SHA, "at": "2026-11-04T10:05:00Z", "log": str(log), "exit": 1}
    statuses = [_st(1, "failure", "2026-11-04T10:00:00Z"), _st(2, "failure", "2026-11-04T10:20:00Z")]
    got = [t for _, t, _ in witness.precheck_fails("shiftlead@main", SHA, statuses, own)]
    assert got == [
        "shiftlead@main a1b2c3d4e5f6 status 1",
        "shiftlead@main a1b2c3d4e5f6 status 2 tests/test_a.py::test_x tests/test_b.py::test_y[1]",
    ], "a run set elsewhere before the home's names none"
    for other in ({**own, "sha": "f" * 40}, {**own, "exit": 0}, {**own, "exit": None}):  # another sha; green; unseen
        assert all(len(t.split()) == 4 for _, t, _ in witness.precheck_fails("shiftlead@main", SHA, statuses, other))


def _open_pr(n, head, state, started):
    roll = [{"__typename": "StatusContext", "context": "cadence/precheck", "state": state, "startedAt": started}]
    return {
        "number": n, "title": "t", "url": "u", "state": "OPEN", "createdAt": "2026-11-04T09:00:00Z",
        "headRefName": f"b{n}", "headRefOid": head, "author": {"login": "g"}, "isDraft": False,
        "statusCheckRollup": roll, "mergeStateStatus": "CLEAN", "baseRefName": "main",
    }  # fmt: skip


def test_the_open_pr_read_reads_a_heads_statuses_when_its_precheck_changed(tmp_path, monkeypatch):
    import subprocess

    from sessionorc import reports

    prs = [_open_pr(7, SHA, "FAILURE", "2026-11-04T10:00:00Z")]

    def run(argv, **kw):
        if argv[1] == "api":
            data = {f.split("=", 1)[0]: {"issueCount": 0} for f in argv if "=repo:" in f}
            return subprocess.CompletedProcess(argv, 0, json.dumps({"data": data}), "")
        return subprocess.CompletedProcess(argv, 0, json.dumps(prs if "open" in argv else []), "")

    monkeypatch.setattr(reports.subprocess, "run", run)
    reads: list[str] = []
    answer: list = [[_st(12, "failure", "2026-11-04T10:00:00Z")]]
    monkeypatch.setattr(reports, "precheck_statuses", lambda d, sha, timeout=30.0: reads.append(sha) or answer[0])
    got: list = []
    emit = lambda repo, text, sid, at: got.append((repo, text, sid, at))  # noqa: E731
    repo = tmp_path / "shiftlead"
    repo.mkdir()
    none = reports.pr_reading(repo, T0, emit=emit)
    assert reads == [] and none["open"][0]["precheck_seen"] is None, "no origin, no id: the list is not read"
    remote = "git@github.com:O/ShiftLead.git"
    one = reports.pr_reading(repo, T0, emit=emit, remote=remote)
    assert reads == [SHA] and got == [
        ("o/shiftlead", "shiftlead#7 a1b2c3d4e5f6 status 12", "12", datetime(2026, 11, 4, 10, tzinfo=UTC))
    ], "the record's repo is the id, its text the registry name"
    two = reports.pr_reading(repo, T0, old=one, emit=emit, remote=remote)
    assert reads == [SHA], "an unchanged precheck is not read again"
    prs[0]["statusCheckRollup"][0].update(state="SUCCESS", startedAt="2026-11-04T10:40:00Z")
    answer[0] = "HTTP 502"
    three = reports.pr_reading(repo, T0, old=two, emit=emit, remote=remote)
    assert reads == [SHA, SHA] and three["open"][0]["precheck_seen"] is None, "unread: read again next time"
    answer[0] = [_st(12, "failure", "2026-11-04T10:00:00Z"), _st(14, "success", "2026-11-04T10:40:00Z")]
    reports.pr_reading(repo, T0, old=three, emit=emit, remote=remote)
    assert reads == [SHA] * 3 and len(got) == 2, "12 is handed again (the loop drops it), 14 is green"
    reports.pr_reading(repo, T0)
    assert reads == [SHA] * 3, "no writer, no read"


def test_mains_pass_reads_its_statuses_when_its_precheck_changed_and_names_its_own_runs_tests(tmp_path, monkeypatch):
    from sessionorc import promote, reports

    log = tmp_path / "p.log"
    log.write_text("FAILED tests/test_a.py::test_x - boom\n")
    monkeypatch.setattr(
        promote, "precheck_run", lambda repo: {"sha": SHA, "at": "2026-11-04T09:00:00Z", "log": str(log), "exit": 1}
    )
    reads: list[str] = []
    monkeypatch.setattr(
        reports,
        "precheck_statuses",
        lambda d, sha, timeout=30.0: reads.append(sha) or [_st(5, "failure", "2026-11-04T10:00:00Z")],
    )
    got: list = []
    emit = lambda repo, text, sid, at: got.append((repo, text))  # noqa: E731
    r = {"main": SHA, "origin": "git@github.com:O/ShiftLead.git"}
    promote.witness_main(tmp_path, "shiftlead", r, {}, "failure 5 2026-11-04T10:00:00Z", emit)
    assert got == [("o/shiftlead", "shiftlead@main a1b2c3d4e5f6 status 5 tests/test_a.py::test_x")]
    assert r["precheck_seen"] == "failure 5 2026-11-04T10:00:00Z"
    promote.witness_main(tmp_path, "shiftlead", dict(r), r, r["precheck_seen"], emit)
    assert reads == [SHA], "an unchanged status is not read again"
    gl = {"main": SHA, "origin": "git@gitlab.com:o/r.git"}
    promote.witness_main(tmp_path, "r", gl, {}, "failure 9 x", emit)
    assert reads == [SHA], "a GitLab repo's prechecks are not witnessed"


def test_read_checks_gives_the_precheck_status_it_compares(monkeypatch, tmp_path):
    import subprocess

    from sessionorc import board, promote

    def run(argv, **kw):
        if argv[2].split("?")[0].endswith("/status"):
            st = {"context": "cadence/precheck", "state": "error", "id": 9, "updated_at": "2026-11-04T10:00:00Z"}
            return subprocess.CompletedProcess(argv, 0, json.dumps({"statuses": [st]}), "")
        return subprocess.CompletedProcess(argv, 0, json.dumps({"check_runs": []}), "")

    monkeypatch.setattr(promote.subprocess, "run", run)
    monkeypatch.setattr(promote.cadence, "precheck_command", lambda root, rev: ("x", None))
    monkeypatch.setattr(board, "default_branch", lambda root: "main")
    assert promote.read_checks(tmp_path, SHA)[3] == "failure"
    assert promote._seen.pop(str(tmp_path)) == "error 9 2026-11-04T10:00:00Z"


@pytest.mark.integration
async def test_the_agent_writes_a_precheck_fail_once_and_a_node_none(agent):
    at = datetime.now(UTC)
    assert agent._witness_precheck("shiftlead", "shiftlead#7 abc status 12", "12", at)
    assert agent._witness_precheck("shiftlead", "shiftlead#7 abc status 12", "12", at) is None
    t = threading.Thread(
        target=lambda: agent._witness_precheck_soon("shiftlead", "shiftlead#8 abc status 123", "123", at)
    )
    t.start()
    t.join()
    await asyncio.sleep(0)
    assert [r["text"] for r in witness.records()] == ["shiftlead#7 abc status 12", "shiftlead#8 abc status 123"]
    agent.mode = "node"
    try:
        assert agent._witness_precheck("shiftlead", "shiftlead#9 abc status 1", "1", at) is None
    finally:
        agent.mode = "home"


# ── the host file (TD-1390) ──────────────────────────────────────────────────────────────────────


def test_kinds_carry_a_public_flag_and_no_class():
    assert all("class" not in v and v["public"] is True for v in witness.KINDS.values())
    assert witness.public_kinds() == ["precheck-fail", "press"]


def test_the_host_file_is_written_once_and_left_as_the_person_edited_it(tmp_path):
    store = tmp_path / "home"
    witness.ensure_start(T0, root=store / "witnessed")
    assert witness.ensure_host_file(store) is True
    text = witness.host_file(store).read_text()
    flat = text.replace("\n# ", " ")
    assert text.startswith("# ") and 'table you add replaces [repos."*"] for that repo whole' in flat
    got = tomllib.loads(text)
    here = str((store / "witnessed").resolve())
    assert got["repos"]["*"] == {
        "profiles": [],
        "sources": {"witnessed": {"path": here, "public_kinds": ["precheck-fail", "press"]}},
    }
    assert got["allow"] == [{"root": here, "visibility": "private", "require_repo": True}]
    assert witness.host_file_problem(store) is None
    witness.host_file(store).write_text("# mine\n")
    assert witness.ensure_host_file(store) is False and witness.host_file(store).read_text() == "# mine\n"
    assert not list(store.glob(".host-log.toml.*")), "no temporary file left"


@pytest.mark.parametrize("odd", ['q"uote', "back\\slash", "caf\u00e9", "del\x7fete"])
def test_a_store_path_is_escaped_as_a_toml_basic_string(tmp_path, odd):
    store = tmp_path / odd
    witness.ensure_start(T0, root=store / "witnessed")
    assert witness.ensure_host_file(store)
    got = tomllib.loads(witness.host_file(store).read_text(encoding="utf-8"))
    assert got["allow"][0]["root"] == str((store / "witnessed").resolve())
    assert "\x7f" not in witness.host_file(store).read_text(encoding="utf-8")


@pytest.mark.integration
async def test_a_store_path_not_valid_utf8_writes_no_file_and_warns_at_each_start(agent, caplog, monkeypatch):
    """The store's undecodable bytes are held as surrogates; fed through `host_text`, not made on disk."""
    from pathlib import Path

    with pytest.raises(UnicodeError):
        witness.toml_string("bad\udcff")
    real = witness.host_text
    monkeypatch.setattr(witness, "host_text", lambda w: real(Path(str(w) + "\udcff")))
    witness.host_file().unlink()
    for _ in range(2):
        with caplog.at_level(logging.WARNING, logger="sessionorc"):
            caplog.clear()
            agent._witness_begin()
        assert not witness.host_file().exists()
        msgs = [r.getMessage() for r in caplog.records]
        assert any("not valid UTF-8" in m for m in msgs) and any("host file" in m and "absent" in m for m in msgs)


def test_a_warning_when_no_root_covers_the_current_witnessed(tmp_path):
    store = tmp_path / "home"
    witness.ensure_start(T0, root=store / "witnessed")
    f = witness.host_file(store)
    assert "absent" in witness.host_file_problem(store)
    f.write_text("not [toml")
    assert "does not parse" in witness.host_file_problem(store)
    f.write_text('[repos."*"]\nprofiles = []\n')
    assert "no [[allow]]" in witness.host_file_problem(store)
    f.write_text('[[allow]]\nroot = "/elsewhere/witnessed"\nvisibility = "private"\n')
    why = witness.host_file_problem(store)
    assert "/elsewhere/witnessed" in why and str((store / "witnessed").resolve()) in why
    f.write_text(f"[[allow]]\nroot = {witness.toml_string(str(store))}\n")
    assert witness.host_file_problem(store) is None, "a root widened to the store covers it"


@pytest.mark.integration
async def test_the_home_writes_its_host_file_at_its_start(agent):
    assert witness.host_file().is_file() and witness.host_file_problem() is None


# ── the query is gone (TD-1390) ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_host_log_and_ao_host_log_are_gone(agent, capsys):
    from sessionorc import identity
    from shiftlead import cli

    assert "host_log" not in modes.HOME_READS and "host_log" not in identity.READS
    assert not hasattr(agent, "rpc_host_log") and not hasattr(witness, "query")
    assert not hasattr(witness, "covers_from")
    with pytest.raises(SystemExit) as e:
        cli.main(["host-log", "press", "--since", "2026-11-04"])
    assert e.value.code == 2 and "invalid choice" in capsys.readouterr().err
