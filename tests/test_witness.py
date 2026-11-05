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
        for d in ("", str(tmp_path / "nowhere")):
            got = await person.call("witness_press", word="start", target="dc-grind", dir=d)
            assert got["recorded"] is None, "a press on a directory in no registered repo is not recorded"
        with pytest.raises(AgentError, match="not a press word"):
            await person.call("witness_press", word="relaunch", target="x")
    recs = witness.records()
    assert [(r["kind"], r["repo"], r["text"]) for r in recs] == [
        ("press", "shiftlead", "apply dc-grind"),
        ("press", "", "host-rebuild contractmatch"),
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
