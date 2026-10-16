"""TD-769 slice 3, design §4.4 *The Queue*: *The rank file*, *A move lands*, and §4.7 `ao rank`: a move is an
intent kept at the home and re-derived at the flush against the cards as they are then, its lines landed on
each repo's rank file by the board's road, one PR per repo per kind; joins and prunes found and flushed; the
move the person's and an interactive session's alone."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from sessionorc import board, ledger, queue, rank
from sessionorc import ledgerboard as lb
from sessionorc.agent_common import RpcError
from sessionorc.models import ProgressEntry, Session

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _entry(n: int, title: str, **fields: str) -> str:
    head = "".join(f"**{k.replace('_', ' ').capitalize()}:** {v}\n" for k, v in fields.items())
    return f"## TD-{n:03d}: {title}\n\n{head}\n"


def _repo(tmp: Path, name: str, entries: list[str], archive: list[str] = (), lines: str | None = None):
    root = tmp / name
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "technical_debt.md").write_text("# Technical Debt\n\n" + "".join(entries), encoding="utf-8")
    (root / "docs" / "technical_debt_archive.md").write_text("# Archive\n\n" + "".join(archive), encoding="utf-8")
    if lines is not None:
        (root / "docs" / "technical_debt_rank.yml").write_text(lines, encoding="utf-8")
    led = ledger.reading(root, NOW, with_history=False)
    return str(root), {"name": name, "root": str(root), "remote": f"git@github.com:o/{name}.git", "ledger": led,
                       "prs": {"open": []}}  # fmt: skip


def _rec(rid: str, repo: str, *refs: str, unattended: bool = True) -> Session:
    s = Session(id=rid, name=rid, kind="interactive", adapter="shell", dir=repo, repo=repo, state="working")  # type: ignore[arg-type]
    s.progress = [ProgressEntry(ref=r, at=(NOW - timedelta(hours=1)).isoformat()) for r in refs]
    s.unattended = unattended
    return s


def _cards(repos: dict[str, dict[str, Any]], records: list[Session] = ()) -> list[dict[str, Any]]:
    return queue.reading(repos, list(records), NOW)["cards"]


def _ups(cards: list[dict[str, Any]], keys: dict[str, str] | None = None) -> list[str]:
    return [c["id"] for c in rank.order(cards, keys) if c["group"] == "up_next"]


FIVE = [_entry(n, f"entry {n}", Priority=p) for n, p in ((1, "High"), (2, "High"), (3, "Medium"), (4, "Low"), (5, "Low"))]


def test_a_move_is_an_intent_between_two_adjacent_up_next_cards(tmp_path):
    root, r = _repo(tmp_path, "r", FIVE)
    cards = _cards({root: r})
    assert _ups(cards) == ["r#TD-001", "r#TD-002", "r#TD-003", "r#TD-004", "r#TD-005"]
    it = rank.intent(cards, ["r#TD-005"], "r#TD-001", "r#TD-002", "person", NOW.isoformat())
    assert it["ids"] == ["r#TD-005"] and it["prev"] == "r#TD-001" and it["next"] == "r#TD-002"
    assert it["prevs"] == [] and it["nexts"] == ["r#TD-003", "r#TD-004"]
    card, key = rank.derive(it, cards, keys := {})
    assert card["id"] == "r#TD-005" and lb.key_order(cards[0]["key"]) < lb.key_order(key) < lb.key_order(cards[1]["key"])
    assert _ups(cards, keys) == ["r#TD-001", "r#TD-005", "r#TD-002", "r#TD-003", "r#TD-004"]
    assert rank.place(cards, "r#TD-005", keys) == 2
    # the top: no prev, the first Up next card next
    top = rank.intent(cards, ["r#TD-004"], None, "r#TD-001", "person", NOW.isoformat())
    rank.derive(top, cards, keys)
    assert _ups(cards, keys)[0] == "r#TD-004"


def test_a_move_that_leaves_the_card_where_it_is_lands_nothing_and_the_refusals(tmp_path):
    root, r = _repo(tmp_path, "r", [*FIVE, _entry(6, "after 5", Priority="Low", Blocked_by="TD-005")])
    cards = _cards({root: r}, [_rec("w", root, "TD-001")])
    at = NOW.isoformat()
    assert rank.intent(cards, ["r#TD-003"], "r#TD-002", "r#TD-004", "person", at) is None
    for ids, prev, nxt, why in (
        (["r#TD-099"], None, None, "not on an open card"),
        (["r#TD-001"], None, "r#TD-002", "In progress, which does not move"),
        (["r#TD-003", "r#TD-004"], None, None, "not one card's"),
        (["r#TD-005"], "r#TD-006", None, "on the moved card itself"),
        (["r#TD-004"], "r#TD-001", "r#TD-002", "not in Up next"),
        (["r#TD-004"], "r#TD-002", "r#TD-005", "not adjacent"),
    ):
        with pytest.raises(rank.Refused, match=why):
            rank.intent(cards, ids, prev, nxt, "person", at)
    # every open member of the moved card gets the one key
    it = rank.intent(cards, ["r#TD-006"], None, "r#TD-002", "person", at)
    assert sorted(it["ids"]) == ["r#TD-005", "r#TD-006"]


def test_an_intent_is_re_derived_after_its_neighbour_archives(tmp_path):
    root, r = _repo(tmp_path, "r", FIVE)
    cards = _cards({root: r})
    it = rank.intent(cards, ["r#TD-005"], "r#TD-002", "r#TD-003", "person", NOW.isoformat())
    # TD-002 and TD-003 archive before the flush: the nearest surviving card the intent remembers stands in
    root, r = _repo(tmp_path, "r", [FIVE[0], FIVE[3], FIVE[4]],
                    archive=[_entry(2, "entry 2", Resolved="2026-10-16"), _entry(3, "x", Resolved="2026-10-16")])  # fmt: skip
    later = _cards({root: r})
    card, key = rank.derive(it, later, keys := {})
    assert _ups(later, keys) == ["r#TD-001", "r#TD-005", "r#TD-004"]
    # every member archived: nothing to land
    root, r = _repo(tmp_path, "r", FIVE[:4], archive=[_entry(5, "entry 5", Resolved="2026-10-16")])
    assert rank.derive(it, _cards({root: r}), {}) is None


def test_a_lined_card_keeps_its_place_through_a_priority_edit_and_joins_and_prunes(tmp_path):
    root, r = _repo(tmp_path, "r", FIVE, lines="# rank\nTD-005: 0|5\n")
    cards = _cards({root: r})
    assert _ups(cards)[0] == "r#TD-005"
    root, r = _repo(tmp_path, "r", [*FIVE[:4], _entry(5, "entry 5", Priority="High")], lines="# rank\nTD-005: 0|5\n")
    assert _ups(_cards({root: r}))[0] == "r#TD-005"  # its line, not its Priority
    # a build filed later under the lined card has no line: a join gives it the card's key
    root, r = _repo(
        tmp_path, "r", [*FIVE, _entry(7, "a later build", Priority="Low", Blocked_by="TD-005")], lines="TD-005: 0|5\n"
    )
    cards = _cards({root: r})
    assert rank.joins(cards) == {"r#TD-007": "0|5"}
    # a line whose whole card is archived goes; an archived row of an open card keeps its line
    root, r = _repo(tmp_path, "r", [FIVE[0], _entry(2, "after 9", Priority="High", Blocked_by="TD-009")],
                    archive=[_entry(9, "done", Resolved="2026-10-16"), _entry(8, "done too", Resolved="2026-10-16")])  # fmt: skip
    cards = _cards({root: r})
    assert rank.prunes(cards, {"r": ["TD-009", "TD-008"]}) == {"r#TD-008": None}


def test_two_cards_of_one_key_refuse_a_key_between_them(tmp_path):
    root, r = _repo(tmp_path, "r", FIVE, lines="TD-001: 0|5\nTD-002: 0|5\n")
    cards = _cards({root: r})
    it = rank.intent(cards, ["r#TD-005"], "r#TD-001", "r#TD-002", "person", NOW.isoformat())
    with pytest.raises(rank.Refused, match="no key fits"):
        rank.derive(it, cards, {})


def test_a_cross_repo_card_is_split_into_one_set_of_lines_per_repo():
    assert rank.by_repo({"a#TD-001": "0|5", "b#TD-002": "0|5", "a#TD-003": None}) == {
        "a": {"TD-001": "0|5", "TD-003": None},
        "b": {"TD-002": "0|5"},
    }
    assert rank.changed("TD-001: 0|5\n", {"TD-001": "0|5", "TD-002": "1", "TD-003": None}) == {"TD-002": "1"}


# -- the landing: the board's road ---------------------------------------------------------------------------


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, forge) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    (root / "docs" / "technical_debt.md").write_text("# Technical Debt\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    forge(root)
    return root


def test_a_rank_flush_lands_its_lines_as_one_pr_and_a_second_on_the_new_head(repo):
    rel = "docs/technical_debt_rank.yml"
    got = board.land_rank(repo, rel, {"TD-005": "0|5"}, lb.queue_subject("shiftlead", "rank", ["TD-005"]))
    assert got["pr"] == 1
    git(repo, "fetch", "-q", "origin")
    assert git(repo, "log", "-1", "--format=%s", "origin/main") == "queue: rank TD-005 (shiftlead) (#1)"
    assert git(repo, "show", "--name-only", "--format=", "origin/main") == rel
    assert lb.rank(git(repo, "show", f"origin/main:{rel}"))[0] == {"TD-005": "0|5"}
    assert not (repo / rel).exists()  # the checkout is never written
    # a second flush on a line of its own; then one that changes nothing lands nothing
    board.land_rank(repo, rel, {"TD-007": "0|7", "TD-005": None}, "queue: rank TD-007 (shiftlead)")
    git(repo, "fetch", "-q", "origin")
    assert lb.rank(git(repo, "show", f"origin/main:{rel}"))[0] == {"TD-007": "0|7"}
    assert board.land_rank(repo, rel, {"TD-007": "0|7"}, "queue: rank TD-007 (shiftlead)") is None


# -- the home ------------------------------------------------------------------------------------------------


async def test_rank_move_is_the_persons_and_an_interactive_sessions(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    root, r = _repo(tmp_path, "r", FIVE)
    agent._repos = {root: r}
    await agent._queue_pass(NOW)
    agent.sessions["ao-w"] = Session(id="ao-w", name="w", kind="agent", adapter="claude-code", dir="", unattended=True)
    agent.sessions["ao-i"] = Session(id="ao-i", name="i", kind="agent", adapter="claude-code", dir="", unattended=False)
    with pytest.raises(RpcError, match="ao-w is unattended, and the rank is the person's"):
        await agent.rpc_rank_move(ids=["r#TD-005"], prev=None, next="r#TD-001", caller="ao-w")
    with pytest.raises(RpcError, match="ao-gone is not a session this home holds"):
        await agent.rpc_rank_move(ids=["r#TD-005"], prev=None, next="r#TD-001", caller="ao-gone")
    assert agent.rank_store.load()["intents"] == []
    with pytest.raises(RpcError, match="In progress|not adjacent"):
        await agent.rpc_rank_move(ids=["r#TD-005"], prev="r#TD-001", next="r#TD-003", caller="ao-i")
    got = await agent.rpc_rank_move(ids=["r#TD-005"], prev=None, next="r#TD-001", caller="ao-i")
    assert got["moved"] and got["card"] == "r#TD-005" and got["place"] == 1
    assert agent.rank_store.load()["intents"][0]["by"] == "ao-i"
    # applied on the reading at once, marked pending
    q = await agent.rpc_queue()
    assert [c["id"] for c in q["cards"]][0] == "r#TD-005" and q["cards"][0]["pending"] and q["cards"][0]["place"] == 1
    again = await agent.rpc_rank_move(ids=["r#TD-005"], prev=None, next="r#TD-001")  # the person; where it is
    assert not again["moved"] and len(agent.rank_store.load()["intents"]) == 1


async def test_the_flush_lands_per_repo_and_a_failed_pr_keeps_its_intent(agent, tmp_path, monkeypatch):
    from conftest import park_ticks

    await park_ticks(agent)
    a, ra = _repo(tmp_path, "a", FIVE)
    b, rb = _repo(tmp_path, "b", [_entry(9, "names a", Priority="Low", Blocked_by="a#TD-004")])
    agent._repos = {a: ra, b: rb}
    await agent._queue_pass(NOW)
    await agent.rpc_rank_move(ids=["b#TD-009"], prev=None, next="a#TD-001")
    landed: list[tuple[str, dict, str]] = []

    def land(root, rel, lines, msg):
        if Path(root).name == "b":
            raise board.Refused("the forge refused it")
        landed.append((Path(root).name, dict(lines), msg))
        return {"pr": 7, "commit": "x", "message": msg}

    monkeypatch.setattr(board, "land_rank", land)
    cards = list(agent._queue["cards"])
    agent._rank_flush(cards, agent._rank_repos())
    assert [(n, m) for n, _, m in landed] == [("a", "queue: rank TD-004 (shiftlead)")]
    state = agent.rank_store.load()
    assert len(state["intents"]) == 1 and "the forge refused it" in state["not_landed"]["a#TD-004"]
    assert (await agent.rpc_queue())["cards"][0]["not_landed"]
    # the next flush lands it, and the intent goes
    monkeypatch.setattr(board, "land_rank", lambda root, rel, lines, msg: {"pr": 8})
    agent._rank_flush(cards, agent._rank_repos())
    state = agent.rank_store.load()
    assert state["intents"] == [] and state["not_landed"] == {} and state["moved_at"] is None


async def test_a_flush_is_due_rank_flush_after_the_last_move(agent, tmp_path, monkeypatch):
    from conftest import park_ticks

    await park_ticks(agent)
    root, r = _repo(tmp_path, "r", FIVE)
    agent._repos = {root: r}
    await agent._queue_pass(NOW)
    flushed: list[int] = []
    monkeypatch.setattr(agent, "_rank_flush", lambda cards, repos: flushed.append(len(cards)))
    await agent.rpc_rank_move(ids=["r#TD-005"], prev=None, next="r#TD-001")
    await agent._rank_pass(NOW)
    assert flushed == []  # within RANK_FLUSH of the move
    state = agent.rank_store.load()
    state["moved_at"] -= rank.RANK_FLUSH + 1
    agent.rank_store.save(state)
    await agent._rank_pass(NOW)
    await agent._rank_task
    assert flushed == [5]


# -- ao rank --------------------------------------------------------------------------------------------------


def test_ao_rank_names_the_neighbours_the_design_says(monkeypatch, tmp_path):
    from shiftlead import cli

    root, r = _repo(tmp_path, "r", FIVE)
    cards = _cards({root: r})
    sent: list[dict[str, Any]] = []

    def call(method, **p):
        if method == "queue":
            return {"cards": cards}
        sent.append(p)
        return {"moved": True, "card": p["ids"][0], "entries": 1, "place": 2}

    monkeypatch.setattr(cli, "call_sync", call)
    monkeypatch.setattr(cli, "_td_repo", lambda repo: ("/x/r", "/x/r"))
    assert cli.main(["rank", "TD-5", "--above", "TD-2"]) == 0
    assert cli.main(["rank", "TD-5", "--below", "TD-2"]) == 0
    assert cli.main(["rank", "TD-5", "--top"]) == 0
    assert cli.main(["rank", "r#TD-1", "--below", "TD-5"]) == 0
    assert [(s["ids"], s["prev"], s["next"]) for s in sent] == [
        (["r#TD-005"], "r#TD-001", "r#TD-002"),
        (["r#TD-005"], "r#TD-002", "r#TD-003"),
        (["r#TD-005"], None, "r#TD-001"),
        (["r#TD-001"], "r#TD-005", None),
    ]
    with pytest.raises(cli.AgentError, match="own card"):
        cli.cmd_rank(cli.build_parser().parse_args(["rank", "TD-5", "--above", "TD-5"]))
    with pytest.raises(cli.AgentError, match="on no open card"):
        cli.cmd_rank(cli.build_parser().parse_args(["rank", "TD-50", "--top"]))
