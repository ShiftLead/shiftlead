"""TD-1761 slice 1, design §4.5 screen 12 *The page holds still* (TD-1558): the Queue keeps the drawn copy and the
latest reading, patches values in place, and counts every place change in the bar for **Refresh** to draw. This runs
the pure parts of `app.js` under node on `test_ui_press_draw`'s small DOM — `AO.qModel` (a copy read as cards),
`AO.qDiff` (the bar's difference and the *gone* units), `AO.qBarParts` (its words) and `AO.qRankFrom` (a rank move's
neighbours named from the latest reading) — and pins the page's wiring by its source."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from test_ui_press_draw import APP_JS, PROBE

DOM = PROBE.split("// ---- fixtures")[0]

CASES = r"""
global.CSS = { escape: (s) => s };
const out = {};
const item = (msg) => h("div", "mailrow", { "data-msg": msg }, []);
const sec = (b, msgs) => h("div", "qsec", { "data-sec": b }, msgs.map(item));
const row = (qid) => h("div", "qrow", { "data-qid": qid }, []);
// a card: Decide and Do in its header, its rows under it
const card = (id, o) => h("div", `qcard${o.off ? " qoff" : ""}`,
  { "data-card": id, ...(o.up ? { "data-up": "1" } : {}) }, [
  h("div", "qhead", { "data-qid": id },
    [...(o.decide ? [sec("decide", o.decide)] : []), ...(o.do ? [sec("do", o.do)] : [])]),
  h("div", "qrows", {}, (o.rows || []).map(row))]);
const group = (g, cards) => h("section", "qgroup", { "data-group": g }, [h("div", "qcards", {}, cards)]);
const page = (groups) => h("div", "", {}, groups);
const diff = (a, b, folded, own) => {
  const d = AO.qDiff(AO.qModel(a), AO.qModel(b), new Set(folded || []), own);
  return { asks: d.asks, done: d.done, moved: d.moved, new: d.new, gone: d.gone, same: [...d.same].sort(),
    words: AO.qBarParts(d) };
};
const base = () => page([group("in_progress", [card("A", { rows: ["a1", "a2"] })]),
  group("up_next", [card("B", { up: 1 }), card("C", { up: 1, decide: ["m1"] }), card("D", { up: 1 })])]);

// a value change alone: nothing to count, and every card may be patched whole
out.values = diff(base(), base());
// one card moved to the top counts once, not every card it passed
out.one_moved = diff(base(), page([group("in_progress", [card("A", { rows: ["a1", "a2"] })]),
  group("up_next", [card("D", { up: 1 }), card("B", { up: 1 }), card("C", { up: 1, decide: ["m1"] })])]));
// a card that left, a card that arrived, a card that changed group
out.done_new_group = diff(base(), page([group("in_progress", [card("A", { rows: ["a1", "a2"] }), card("D", {})]),
  group("up_next", [card("C", { up: 1, decide: ["m1"] }), card("E", { up: 1 })])]));
// an ask answered elsewhere: *gone* in its block, the card moved; one answered by the person's own press: nothing
const answered = page([group("in_progress", [card("A", { rows: ["a1", "a2"] })]),
  group("up_next", [card("B", { up: 1 }), card("C", { up: 1 }), card("D", { up: 1 })])]);
out.gone_elsewhere = diff(base(), answered);
out.gone_own = diff(base(), answered, [], (k) => k === "m:m1");
// a new ask on a drawn card and on a card not drawn: counted as asks, those cards in no later part
out.asks = diff(base(), page([group("in_progress", [card("A", { rows: ["a1", "a2"] })]),
  group("up_next", [card("B", { up: 1, do: ["m7"] }), card("C", { up: 1, decide: ["m1"] }), card("D", { up: 1 }),
    card("F", { up: 1, decide: ["m8", "m9"] })])]));
// rows reordered inside a card, and a row arriving: places of the card
out.inside = diff(base(), page([group("in_progress", [card("A", { rows: ["a2", "a1", "a3"] })]),
  group("up_next", [card("B", { up: 1 }), card("C", { up: 1, decide: ["m1"] }), card("D", { up: 1 })])]));
// a card the picks hide in both copies, or in a folded group, counts nothing
const hid = () => page([group("in_progress", [card("A", { rows: ["a1", "a2"] })]),
  group("up_next", [card("B", { up: 1, off: 1 }), card("C", { up: 1, decide: ["m1"] }), card("D", { up: 1 })])]);
out.picks = diff(hid(), page([group("in_progress", [card("A", { rows: ["a1", "a2"] })]),
  group("up_next", [card("C", { up: 1, decide: ["m1"] }), card("D", { up: 1 }), card("B", { up: 1, off: 1 })])]));
out.folded = diff(base(), page([group("in_progress", [card("A", { rows: ["a1"] })]),
  group("up_next", [card("B", { up: 1 }), card("C", { up: 1, decide: ["m1"] }), card("D", { up: 1 })])]),
  ["in_progress"]);
// a card gone to Recently completed is done
out.completed = diff(base(), page([group("completed", [card("A", { rows: ["a1", "a2"] })]),
  group("up_next", [card("B", { up: 1 }), card("C", { up: 1, decide: ["m1"] }), card("D", { up: 1 })])]));

// rank moves: the drawn order places the card, the latest reading names its neighbours
const drawn = ["B", "C", "D"];
out.rank_same = AO.qRankFrom(drawn, ["B", "C", "D"], "D", "up");
// X arrived between B and C in the reading: ↑ on D (after B) names B and X, which the home holds adjacent
out.rank_arrived = AO.qRankFrom(drawn, ["B", "X", "C", "D"], "D", "up");
// ⤒ is before the first
out.rank_top = AO.qRankFrom(drawn, ["X", "B", "C", "D"], "D", "top");
// the anchor left the reading: the other drawn neighbour anchors
out.rank_other = AO.qRankFrom(drawn, ["C", "D"], "D", "up");
// both drawn neighbours gone: nothing is sent
out.rank_none = AO.qRankFrom(drawn, ["D", "Y"], "D", "up");
// a move that leaves the card where it is sends nothing
out.rank_stays = AO.qRankFrom(drawn, ["B", "C", "D"], "B", "top");
// a drop keeps its own anchor: before C
out.rank_drop = AO.qRankFrom(drawn, ["C", "Z", "B", "D"], "D", { before: "C" });
out.lis = [...AO.qLis([0, 3, 1, 2])].sort();
out.age = [AO.qAge(12000), AO.qAge(185000), AO.qAge(7300000)];
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def got(tmp_path_factory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    probe = tmp_path_factory.mktemp("holds_still") / "holds_still_probe.js"
    probe.write_text(DOM + CASES)
    run = subprocess.run(["node", str(probe), str(APP_JS)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(run.stdout.strip().splitlines()[-1])


NOTHING = {"asks": 0, "done": 0, "moved": 0, "new": 0, "gone": [], "words": []}


def _counts(d: dict) -> dict:
    return {k: d[k] for k in NOTHING}


def test_a_value_change_counts_nothing_and_every_card_patches_whole(got):
    assert _counts(got["values"]) == NOTHING
    assert got["values"]["same"] == ["A", "B", "C", "D"]


def test_one_card_moved_is_counted_once_and_not_drawn(got):
    assert _counts(got["one_moved"]) == {**NOTHING, "moved": 1, "words": ["1 card moved"]}


def test_a_card_leaving_arriving_and_changing_group_each_count_in_their_part(got):
    d = got["done_new_group"]
    assert (d["done"], d["moved"], d["new"]) == (1, 1, 1)
    assert d["words"] == ["1 done", "1 card moved", "1 new"]
    assert "D" not in d["same"]  # a card that changed group waits whole for Refresh


def test_an_ask_answered_elsewhere_is_gone_in_its_block_and_moves_its_card(got):
    d = got["gone_elsewhere"]
    assert d["gone"] == [["C", "m:m1"]]
    assert d["moved"] == 1 and "C" not in d["same"]


def test_an_own_press_on_the_only_decide_item_counts_nothing(got):
    d = got["gone_own"]
    assert d["gone"] == [] and d["asks"] == 0 and d["words"] == []


def test_new_asks_count_items_and_their_cards_count_in_no_later_part(got):
    d = got["asks"]
    assert (d["asks"], d["moved"], d["new"]) == (3, 0, 0)
    assert d["words"] == ["3 new asks for you"]


def test_a_place_change_inside_a_card_is_moved(got):
    d = got["inside"]
    assert d["moved"] == 1 and "A" not in d["same"] and d["gone"] == []


def test_a_card_the_picks_hide_or_a_folded_group_holds_counts_nothing(got):
    assert got["picks"]["moved"] == 0
    # the folded group's card counts nothing, but its unit is still *gone*
    assert got["folded"]["moved"] == 0 and got["folded"]["gone"] == [["A", "r:a2"]]


def test_a_card_gone_to_recently_completed_is_done(got):
    d = got["completed"]
    assert d["done"] == 1 and d["words"] == ["1 done"]


def test_a_rank_move_names_the_latest_readings_neighbours(got):
    assert got["rank_same"]["prev"] == "B" and got["rank_same"]["next"] == "C"
    assert got["rank_same"]["order"] == ["B", "D", "C"]
    a = got["rank_arrived"]
    assert (a["prev"], a["next"]) == ("B", "X")
    assert a["order"] == ["B", "D", "C"] and a["latest"] == ["B", "D", "X", "C"]
    assert (got["rank_top"]["prev"], got["rank_top"]["next"]) == ("X", "B")
    assert (got["rank_other"]["prev"], got["rank_other"]["next"]) == (None, "C")
    assert got["rank_none"]["refused"] == "the order changed — Refresh first" and "prev" not in got["rank_none"]
    assert got["rank_stays"] is None
    assert (got["rank_drop"]["prev"], got["rank_drop"]["next"]) == (None, "C")


def test_the_helpers(got):
    assert got["lis"] == [0, 2, 3]
    assert got["age"] == ["12 s ago", "3 min ago", "2 h ago"]


JS = APP_JS.read_text()
Q = JS[JS.index("AO.queue = function") :]
Q = Q[: Q.index("AO.REPO_WINDOWS")]


def test_a_reread_patches_and_only_refresh_and_a_hidden_page_draw_whole():
    read = Q[Q.index("async function reread()") :]
    read = read[: read.index('document.addEventListener("visibilitychange"')]
    assert "lists.innerHTML" not in read
    assert "if ((document.hidden || whole) && !anyBox()) drawWhole(); else patch();" in read
    # a reading that fails, or answers without a served Queue, is no reading
    assert 'if (!fresh || !$("#qcounts", fresh)) { notLive(); return; }' in read
    assert "if (sent < lastMove) return;" in read  # a read that left before the last move is dropped
    assert 'refreshBtn.addEventListener("click"' in Q and "drawWhole();" in Q


def test_a_held_card_waits_and_its_gone_does_not():
    p = Q[Q.index("function patch()") : Q.index("function drawBar(")]
    assert p.index("if (holds(el))") < p.index("patchCard(el, r,")
    assert "AO.qGone(u," in p[p.index("if (holds(el))") :]  # marked after the hold, on every card
    assert "AO.qcardReapply(lists);" in p  # the own press's keep reapplied over the patch


def test_a_patch_never_remarks_the_picks():
    p = Q[Q.index("function patchCard(") : Q.index("function drawBar(")]
    assert "applyPicks" not in p and "apply();" not in p
    assert '["folded", "qoff", "qring", "qlit"].forEach((c) => n.classList.toggle(c, el.classList.contains(c)));' in p


def test_the_bar_and_the_held_mark_are_drawn():
    from pathlib import Path

    t = Path(APP_JS).parents[1] / "templates"
    page = (t / "queue.html").read_text()
    assert page.index('id="qbar" role="status"') < page.index('id="queuelists"')
    assert "help_title('queue-bar')" in page
    assert "help_title('card-held')" in (t / "queue_card.html").read_text()
