"""The home's witness log (design §4.4 *The home keeps a log of what it witnesses*, TD-1386): the log's files,
ids, start and months kept, `witness_press` and the places that send it."""

from __future__ import annotations

import asyncio
import json
import threading
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
    late = witness.append("press", "", "host-rebuild n", datetime(2026, 10, 30, tzinfo=UTC), root=d)
    assert late and (d / "2026-10.jsonl").is_file() and (d / "2026-11.jsonl").is_file(), "a late record: its month"
    assert witness.append("press", "", "x", datetime(2026, 8, 31, tzinfo=UTC), root=d) is None, "before start"
    with (d / "2026-11.jsonl").open("a") as f:
        f.write("not json\n")
    assert [r["id"] for r in witness.records(d)] == [late["id"], a["id"]], "sorted by at, the bad line skipped"
    with pytest.raises(ValueError, match="not a witness kind"):
        witness.append("msg", "", "x", T0, root=d)


def test_a_colliding_id_is_drawn_again(tmp_path, monkeypatch):
    d = tmp_path / "w"
    witness.ensure_start(datetime(2026, 1, 1, tzinfo=UTC), root=d)
    tails = iter(["abcd", "abcd", "abcd", "beef"])
    monkeypatch.setattr(witness.secrets, "token_hex", lambda n: next(tails))
    one = witness.append("press", "", "a x", T0, root=d)
    two = witness.append("press", "", "b x", T0, root=d)
    assert one["id"].endswith("-abcd") and two["id"].endswith("-beef")


def test_the_prune_keeps_thirteen_months_counted_from_the_calendar(tmp_path):
    d = tmp_path / "w"
    d.mkdir()
    for m in ("2025-10", "2025-11", "2025-12", "2026-11"):
        (d / f"{m}.jsonl").write_text("")
    assert witness.boundary(T0) == datetime(2025, 11, 1, tzinfo=UTC)
    assert witness.prune(T0, root=d) == ["2025-10.jsonl"]
    assert sorted(f.name for f in d.iterdir()) == ["2025-11.jsonl", "2025-12.jsonl", "2026-11.jsonl"]
    witness.ensure_start(datetime(2026, 3, 1, tzinfo=UTC), root=d)
    assert witness.covers_from(T0, root=d) == datetime(2026, 3, 1, tzinfo=UTC), "the later of start and boundary"


def test_the_log_is_in_the_nightly_tarball():
    assert "witnessed" in agent_common.BACKUP_MEMBERS


def test_a_directory_maps_to_its_registered_repo_through_a_symlink(tmp_path):
    repo = tmp_path / "shiftlead"
    (repo / ".claude" / "worktrees" / "g").mkdir(parents=True)
    (tmp_path / "link").symlink_to(repo)
    roots = [str(repo), str(tmp_path / "other")]
    assert witness.repo_named(str(tmp_path / "link"), roots) == "shiftlead"
    assert witness.repo_named(str(repo / ".claude" / "worktrees" / "g"), roots) == "shiftlead"
    assert witness.repo_named(str(tmp_path / "elsewhere"), roots) is None
    assert witness.repo_named("", roots) is None and witness.repo_named(None, roots) is None


def test_witness_press_is_the_persons_own_and_the_homes_alone():
    assert "witness_press" in mail.PERSON_ONLY and "witness_press" in modes.HOME_EDITS
    assert "witness_press" in modes.HOME_ONLY, "refused when forwarded from a node"


def _registered(agent, repo) -> None:
    agent._witness_repo = lambda d: witness.repo_named(d, [str(repo)])


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
        ("press", "shiftlead", "apply dc-grind"),
        ("press", "", "host-rebuild contractmatch"),
        ("press", "shiftlead", "new-session shiftlead"),
    ]


@pytest.mark.integration
async def test_a_node_writes_no_record_and_refuses_the_press(agent):
    agent.mode = "node"
    try:
        assert agent._witness("press", "", "apply x") is None
        with pytest.raises(Exception, match="runs at the home"):
            await agent.rpc_witness_press(word="host-rebuild", target="n")
    finally:
        agent.mode = "home"
    assert witness.records() == []


@pytest.mark.integration
async def test_a_record_from_a_detached_writer_lands_whole_beside_one_from_the_loop(agent):
    t = threading.Thread(target=lambda: agent._witness_soon("press", "", "host-rebuild a" + " x" * 200))
    t.start()
    agent._witness("press", "", "host-rebuild b")
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
    assert [r["text"] for r in witness.records()] == [
        f"push-on {one}",
        f"push-on {push_mod.device_id('https://p.example.com/3')}",
    ], "a renewal it cannot name reads as a new device"


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
    one = reports.pr_reading(repo, T0, emit=emit)
    assert reads == [SHA] and got == [
        ("shiftlead", "shiftlead#7 a1b2c3d4e5f6 status 12", "12", datetime(2026, 11, 4, 10, tzinfo=UTC))
    ]
    two = reports.pr_reading(repo, T0, old=one, emit=emit)
    assert reads == [SHA], "an unchanged precheck is not read again"
    prs[0]["statusCheckRollup"][0].update(state="SUCCESS", startedAt="2026-11-04T10:40:00Z")
    answer[0] = "HTTP 502"
    three = reports.pr_reading(repo, T0, old=two, emit=emit)
    assert reads == [SHA, SHA] and three["open"][0]["precheck_seen"] is None, "unread: read again next time"
    answer[0] = [_st(12, "failure", "2026-11-04T10:00:00Z"), _st(14, "success", "2026-11-04T10:40:00Z")]
    reports.pr_reading(repo, T0, old=three, emit=emit)
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
    emit = lambda repo, text, sid, at: got.append(text)  # noqa: E731
    r = {"main": SHA, "origin": "git@github.com:o/shiftlead.git"}
    promote.witness_main(tmp_path, "shiftlead", r, {}, "failure 5 2026-11-04T10:00:00Z", emit)
    assert got == ["shiftlead@main a1b2c3d4e5f6 status 5 tests/test_a.py::test_x"]
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


# ── the query (TD-1387) ─────────────────────────────────────────────────────────────────────────────


def _log(tmp_path):
    d = tmp_path / "w"
    witness.ensure_start(datetime(2026, 9, 1, tzinfo=UTC), root=d)
    for at, kind, repo, text in [
        (datetime(2026, 10, 10, tzinfo=UTC), "press", "shiftlead", "apply dc-grind"),
        (datetime(2026, 11, 3, tzinfo=UTC), "press", "", "host-rebuild contractmatch"),
        (datetime(2026, 11, 2, tzinfo=UTC), "press", "agent-cadence", "start dc-grind"),  # late: read in at order
        (datetime(2026, 11, 1, tzinfo=UTC), "precheck-fail", "shiftlead", "shiftlead@main abc status 7 t.py::x"),
        (datetime(2026, 10, 20, tzinfo=UTC), "press", "shiftlead", "Apply a.b"),
    ]:
        witness.append(kind, repo, text, at, root=d)
    return d


def _texts(got):
    return [r["text"] for r in got["records"]]


def test_the_query_counts_after_an_instant_literally_case_sensitively_and_by_repo(tmp_path):
    d = _log(tmp_path)

    def q(text="", after=datetime(2026, 10, 15, tzinfo=UTC), repo=None, kind="press"):
        return witness.query(kind, text, after, repo, now=T0, root=d)

    got = q()
    assert got["count"] == 3 and _texts(got) == ["Apply a.b", "start dc-grind", "host-rebuild contractmatch"]
    assert got["covers_from"] == "2026-09-01T00:00:00Z", "start, later than the boundary"
    assert _texts(q("dc-grind")) == ["start dc-grind"] and q("apply")["count"] == 0, "case-sensitive"
    assert _texts(q("a.b")) == ["Apply a.b"] and q("a*b")["count"] == 0 and q("Apply.a")["count"] == 0, "literal"
    assert q(after=datetime(2026, 11, 3, tzinfo=UTC))["count"] == 1, "at or after: inclusive"
    assert _texts(q(repo="agent-cadence")) == ["start dc-grind"]
    assert _texts(q(repo="shiftlead")) == ["Apply a.b", "host-rebuild contractmatch"], "no repo ties to shiftlead"
    assert q(repo="contractmatch")["count"] == 0, "a record of no repo is no other repo's"
    assert q(kind="precheck-fail", after=datetime(2026, 1, 1, tzinfo=UTC))["count"] == 1
    with pytest.raises(ValueError, match="not a witness kind"):
        q(kind="msg")


def test_covers_from_before_and_after_a_prune(tmp_path):
    d = tmp_path / "w"
    witness.ensure_start(datetime(2025, 1, 1, tzinfo=UTC), root=d)
    witness.append("press", "", "host-rebuild a", datetime(2025, 6, 1, tzinfo=UTC), root=d)
    old = witness.query("press", "", datetime(2025, 1, 1, tzinfo=UTC), now=datetime(2026, 1, 5, tzinfo=UTC), root=d)
    assert old["covers_from"] == "2025-01-01T00:00:00Z" and old["count"] == 1
    later = datetime(2026, 11, 4, tzinfo=UTC)
    witness.prune(later, root=d)
    got = witness.query("press", "", datetime(2025, 1, 1, tzinfo=UTC), now=later, root=d)
    assert got == {"count": 0, "covers_from": "2025-11-01T00:00:00Z", "records": []}, "nothing refused for age"


def test_host_log_is_a_home_read_forwarded_while_the_link_is_up_and_refused_offline():
    from sessionorc import identity

    assert "host_log" in modes.HOME_READS and "host_log" in identity.READS
    assert "host_log" not in modes.HOME_EDITS and "host_log" not in modes.HOME_ONLY
    for caller in (None, "ao-x"):
        why = modes.offline_refusal("host_log", caller, {}, host="laptop", home="kmaster")
        assert why and "kmaster (home) is unreachable" in why


@pytest.mark.integration
async def test_the_home_answers_host_log_to_a_session_and_to_a_node(agent):
    agent._witness("press", "", "host-rebuild contractmatch")
    after = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    got = await agent.rpc_host_log(kind="press", text="contractmatch", after=after, repo="shiftlead")
    assert got["count"] == 1 and got["records"][0]["text"] == "host-rebuild contractmatch"
    fwd = await agent._forwarded(
        "laptop", {"rpc": "host_log", "params": {"kind": "press", "after": after}, "caller": "ao-x-w", "token": ""}
    )
    assert fwd["result"]["count"] == 1, fwd
    with pytest.raises(Exception, match="not a witness kind"):
        await agent.rpc_host_log(kind="msg", after=after)
    with pytest.raises(Exception, match="after is the instant"):
        await agent.rpc_host_log(kind="press")


def test_ao_host_log_exits_0_1_and_2(monkeypatch, capsys):
    from shiftlead import cli

    asked = []
    rec = {"id": "w-20261104T120000Z-abcd", "at": "2026-11-04T12:00:00Z", "repo": "", "text": "host-rebuild n"}

    def call(method, **kw):
        asked.append((method, kw))
        if kw["kind"] == "msg":
            raise AgentError("host_log: 'msg' is not a witness kind (precheck-fail, press)")
        return {"count": 1, "covers_from": "2026-11-01T00:00:00Z", "records": [rec]}

    monkeypatch.setattr(cli, "call_sync", call)

    def run(*argv):
        try:
            return cli.main(["host-log", *argv])
        except SystemExit as e:
            return e.code

    assert run("press", "host-rebuild", "--since", "2026-11-04") == 0
    assert asked[-1] == (
        "host_log",
        {"kind": "press", "text": "host-rebuild", "after": "2026-11-04T00:00:00+00:00", "repo": None},
    )
    out = capsys.readouterr().out
    assert "1 press since 2026-11-04" in out and rec["id"] in out
    assert run("press", "--since", "2026-11-04", "--times", "2", "--repo", "shiftlead") == 1
    assert asked[-1][1]["repo"] == "shiftlead"
    assert run("msg", "--since", "2026-11-04") == 2
    assert run("press") == 2, "--since is required"
    capsys.readouterr()
    assert run("--kinds") == 0 and "precheck-fail  (public)" in capsys.readouterr().out
    assert run("press", "--since", "2026-11-04", "--json") == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1
