"""TD-901, design §4.4 *The Queue* (`places`) and *A move lands* (a Repo page's move, `scope`), §4.5 screen
12 *Up next* and §4.5a *Queue page, Up next: the number*, §4.7 `ao repo`: Up next is numbered per repo — two
repos' leaders both read 1, a card spanning repos carries one number per repo — and a Repo page's move names
the repo's own cards as its neighbours, landing in the whole order past other repos' cards between them."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile
from typing import Any

import pytest
from test_rank import NOW, _cards, _entry, _repo, _ups

from sessionorc import rank
from sessionorc.agent_common import RpcError

JS = pathlib.Path(__file__).parents[1] / "src" / "shiftlead" / "ui" / "static" / "app.js"

# two repos interleaved by their implicit keys (High, then Medium, then Low; then id), and a card of a#TD-007
# blocked by b#TD-006, which spans both
A = [
    _entry(1, "a one", Priority="High"),
    _entry(3, "a three", Priority="Medium"),
    _entry(5, "a five", Priority="Low"),
    _entry(7, "a seven", Priority="Low", Blocked_by="b#TD-006"),
]
B = [_entry(2, "b two", Priority="High"), _entry(4, "b four", Priority="Medium"), _entry(6, "b six", Priority="Low")]


def _two(tmp_path) -> list[dict[str, Any]]:
    ra, a = _repo(tmp_path, "a", A)
    rb, b = _repo(tmp_path, "b", B)
    return _cards({ra: a, rb: b})


def _places(cards: list[dict[str, Any]]) -> dict[str, list[tuple[str, int]]]:
    return {c["id"]: [(p["repo"], p["n"]) for p in c["places"]] for c in cards}


@pytest.mark.unit
def test_up_next_is_numbered_per_repo_and_a_spanning_card_carries_a_number_per_repo(tmp_path):
    cards = _two(tmp_path)
    assert _ups(cards) == ["a#TD-001", "b#TD-002", "a#TD-003", "b#TD-004", "a#TD-005", "b#TD-006"]
    assert _places(cards) == {
        "a#TD-001": [("a", 1)],
        "b#TD-002": [("b", 1)],  # two repos' leaders both read 1
        "a#TD-003": [("a", 2)],
        "b#TD-004": [("b", 2)],
        "a#TD-005": [("a", 3)],
        "b#TD-006": [("a", 4), ("b", 3)],  # the card of b#TD-006 and a#TD-007
    }
    assert [c["place"] for c in cards] == [1, 2, 3, 4, 5, 6]  # the whole order's place stays beside them
    # In progress has no number
    cards[0]["group"] = "in_progress"
    rank.number(cards)
    assert cards[0]["place"] is None and cards[0]["places"] == [] and _places(cards)["a#TD-003"] == [("a", 1)]


@pytest.mark.unit
def test_a_repo_page_move_names_the_repos_own_neighbours_and_lands_past_the_others(tmp_path):
    cards = _two(tmp_path)
    at = NOW.isoformat()
    # up one on repo a's page: a#TD-005 between a#TD-001 and a#TD-003, which the whole order does not hold adjacent
    with pytest.raises(rank.Refused, match="not adjacent"):
        rank.intent(cards, ["a#TD-005"], "a#TD-001", "a#TD-003", "person", at)
    it = rank.intent(cards, ["a#TD-005"], "a#TD-001", "a#TD-003", "person", at, scope="a")
    assert it["scope"] == "a" and it["prevs"] == [] and it["nexts"] == ["b#TD-006"]  # the cards remembered: a's
    rank.derive(it, cards, keys := {})
    assert _ups(cards, keys) == ["a#TD-001", "a#TD-005", "b#TD-002", "a#TD-003", "b#TD-004", "b#TD-006"]
    # ⤒ on repo b's page: prev the whole-order card just before b's first, so it lands directly above b#TD-002
    top = rank.intent(cards, ["b#TD-004"], "a#TD-001", "b#TD-002", "person", at, scope="b")
    rank.derive(top, cards, keys := {})
    assert _ups(cards, keys) == ["a#TD-001", "b#TD-004", "b#TD-002", "a#TD-003", "a#TD-005", "b#TD-006"]
    # past b's last card: next the whole-order card after it, none at Up next's end
    last = rank.intent(cards, ["b#TD-004"], "b#TD-006", None, "person", at, scope="b")
    rank.derive(last, cards, keys := {})
    assert _ups(cards, keys)[-1] == "b#TD-004"


@pytest.mark.unit
def test_a_scoped_move_where_it_is_lands_nothing_and_the_refusals(tmp_path):
    cards = _two(tmp_path)
    at = NOW.isoformat()
    # a#TD-003 already sits just after b#TD-002: nothing lands
    assert rank.intent(cards, ["a#TD-003"], "b#TD-002", "a#TD-005", "person", at, scope="a") is None
    with pytest.raises(rank.Refused, match="no entry of a"):
        rank.intent(cards, ["b#TD-004"], "a#TD-001", "a#TD-003", "person", at, scope="a")
    with pytest.raises(rank.Refused, match="not in order"):
        rank.intent(cards, ["a#TD-005"], "a#TD-003", "a#TD-001", "person", at, scope="a")


async def test_rank_move_takes_the_scope_and_the_reading_serves_places(agent, tmp_path):
    from conftest import park_ticks

    await park_ticks(agent)
    ra, a = _repo(tmp_path, "a", A)
    rb, b = _repo(tmp_path, "b", B)
    agent._repos = {ra: a, rb: b}
    await agent._queue_pass(NOW)
    with pytest.raises(RpcError, match="not adjacent"):
        await agent.rpc_rank_move(ids=["a#TD-005"], prev="a#TD-001", next="a#TD-003")
    got = await agent.rpc_rank_move(ids=["a#TD-005"], prev="a#TD-001", next="a#TD-003", scope="a")
    assert got["moved"] and got["place"] == 2
    assert agent.rank_store.load()["intents"][0]["scope"] == "a"
    q = await agent.rpc_queue()
    moved = next(c for c in q["cards"] if c["id"] == "a#TD-005")
    assert moved["pending"] and moved["places"] == [{"repo": "a", "n": 2}]  # the moves applied, renumbered per repo


PROBE = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const s = src.indexOf("AO.rankMoveScoped = function"), e = src.indexOf("\\n  };\\n", s);
const AO = {}; eval(src.slice(s, e + 5));
// the whole Up next order, two repos interleaved; repo a's own cards are a1, a3, a5
const o = ["a1", "b2", "a3", "b4", "a5", "b6"], own = ["a1", "a3", "a5"];
console.log(JSON.stringify([
  AO.rankMoveScoped(o, own, "a5", "up"), AO.rankMoveScoped(o, own, "a3", "top"),
  AO.rankMoveScoped(o, ["b2", "b4", "b6"], "b4", "top"), AO.rankMoveScoped(o, own, "a3", "down"),
  AO.rankMoveScoped(o, ["a1", "a3"], "a1", "down"), AO.rankMoveScoped(o, own, "a1", "top"),
  AO.rankMoveScoped(o, own, "a1", {after: "a5"}), AO.rankMoveScoped(o, own, "b2", "up"),
]));
"""


@pytest.mark.unit
def test_a_repo_page_move_in_the_browser_names_the_neighbours_the_home_takes():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = pathlib.Path(tempfile.mkdtemp()) / "rank_scoped_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(JS)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    up, top, top_b, down, last_down, top_first, after, other = json.loads(out.stdout)
    # up one among the repo's own, past b's card between them, landing just after prev
    assert up == {"prev": "a1", "next": "a3", "order": ["a1", "a5", "b2", "a3", "b4", "b6"]}
    # ⤒: the repo's first is the top of Up next, so no prev
    assert top == {"prev": None, "next": "a1", "order": ["a3", "a1", "b2", "b4", "a5", "b6"]}
    # ⤒ on b: prev the whole-order card just before b's first
    assert top_b == {"prev": "a1", "next": "b2", "order": ["a1", "b4", "b2", "a3", "a5", "b6"]}
    assert down == {"prev": "a5", "next": "b6", "order": ["a1", "b2", "b4", "a5", "a3", "b6"]}
    # past the repo's last card: next the whole-order card just after it
    assert last_down == {"prev": "a3", "next": "b4", "order": ["b2", "a3", "a1", "b4", "a5", "b6"]}
    assert top_first is None and other is None  # where it is; a card the page does not draw
    assert after == {"prev": "a5", "next": "b6", "order": ["b2", "a3", "b4", "a5", "a1", "b6"]}


@pytest.mark.unit
def test_ao_repo_and_ao_rank_list_print_the_place_in_the_repo(tmp_path, monkeypatch, capsys):
    """§4.7 `ao repo` (TD-901): an entry's line ends with its card's place in the repo's Up next, and *(lane
    order may differ)* on an undragged card spanning repos; `--json` carries both. `ao rank --list --repo`
    numbers by the repo's places."""
    from shiftlead import cli

    ra, a = _repo(tmp_path, "a", A)
    rb, b = _repo(tmp_path, "b", B)
    cards = _cards({ra: a, rb: b})
    replies = {"repos": {ra: a, rb: b}, "list": [], "doing_log": {}, "inbox": {}, "queue": {"cards": cards}}
    monkeypatch.setattr(cli, "call_sync", lambda rpc, **kw: replies[rpc])
    assert cli.main(["repo", "a"]) == 0
    out = capsys.readouterr().out
    line = {ln.split()[1]: ln for ln in out.splitlines() if ln.startswith("  pickable") or ln.startswith("  blocked")}
    assert line["TD-001"].endswith("a one · up next 1") and line["TD-005"].endswith("a five · up next 3")
    assert "b#" not in out
    assert cli.main(["--json", "repo", "a"]) == 0
    got = {e["id"]: e for e in json.loads(capsys.readouterr().out)[0]["ledger"]["entries"]}
    assert got["TD-003"]["place"] == 2 and got["TD-003"]["lane_order_may_differ"] is False
    assert got["TD-007"]["place"] == 4 and got["TD-007"]["lane_order_may_differ"] is True  # spanning, undragged
    monkeypatch.setattr(cli, "_td_repo", lambda repo: (f"/x/{repo}", f"/x/{repo}"))
    assert cli.main(["rank", "--list", "--repo", "b"]) == 0
    nums = [ln.split()[0] for ln in capsys.readouterr().out.splitlines()]
    assert nums == ["1", "2", "3"]  # b#TD-002, b#TD-004, and the card spanning both: b's 3, not the whole 6
