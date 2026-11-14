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
const row = (qid, cls) => h("div", `qrow${cls ? " " + cls : ""}`, { "data-qid": qid }, []);
// a card: Decide and Do in its header, its rows under it
const card = (id, o) => h("div", `qcard${o.off ? " qoff" : ""}`,
  { "data-card": id, ...(o.up ? { "data-up": "1" } : {}), ...(o.ids ? { "data-ids": o.ids.join(" ") } : {}) }, [
  h("div", "qhead", { "data-qid": id, ...(o.headDone ? { "data-done": "" } : {}) },
    [...(o.decide ? [sec("decide", o.decide)] : []), ...(o.do ? [sec("do", o.do)] : [])]),
  h("div", "qrows", {}, [...(o.rows || []).map((q) => row(q, (o.archived || []).includes(q) ? "archived" : "")),
    ...(o.fold ? [h("details", "qfold", {}, o.fold.map((q) => row(q, "archived")))] : [])])]);
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

// TD-1783: each counting rule in its other direction
const upnext = (cards) => group("up_next", cards);
const inprog = (cards) => group("in_progress", cards);
// a card already in Recently completed in both copies is not done again
out.completed_both = diff(page([group("completed", [card("A", {})]), upnext([card("B", { up: 1 })])]),
  page([group("completed", [card("A", {})]), upnext([card("B", { up: 1 })])]));
// a card that leaves for Recently completed carrying a new ask counts once, as the ask
out.done_with_ask = diff(page([inprog([card("A", {})]), upnext([card("B", { up: 1 })])]),
  page([group("completed", [card("A", { decide: ["m5"] })]), upnext([card("B", { up: 1 })])]));
// a card the picks hide that leaves is not done
out.hidden_leaves = diff(page([inprog([card("A", { off: 1 })]), upnext([card("B", { up: 1 })])]),
  page([inprog([]), upnext([card("B", { up: 1 })])]));
// a card arriving straight in Recently completed is not new
out.new_completed = diff(page([upnext([card("B", { up: 1 })])]),
  page([group("completed", [card("G", {})]), upnext([card("B", { up: 1 })])]));
// a card hidden in one copy only, in its place, is moved
out.revealed = diff(page([upnext([card("B", { up: 1, off: 1 }), card("C", { up: 1 })])]),
  page([upnext([card("B", { up: 1 }), card("C", { up: 1 })])]));
// a row arriving alone, and a reorder alone, are each a place of the card
out.row_arrives = diff(base(), page([inprog([card("A", { rows: ["a1", "a2", "a3"] })]),
  upnext([card("B", { up: 1 }), card("C", { up: 1, decide: ["m1"] }), card("D", { up: 1 })])]));
out.row_reorders = diff(base(), page([inprog([card("A", { rows: ["a2", "a1"] })]),
  upnext([card("B", { up: 1 }), card("C", { up: 1, decide: ["m1"] }), card("D", { up: 1 })])]));
// a new ask on a card the picks hide in both copies, or on a hidden card not drawn, is not counted
out.hidden_asks = diff(page([upnext([card("B", { up: 1, off: 1 }), card("C", { up: 1 })])]),
  page([upnext([card("B", { up: 1, off: 1, do: ["m7"] }), card("C", { up: 1 }),
    card("F", { up: 1, off: 1, decide: ["m8"] })])]));
// an ask the person's own press brought is not a new ask
out.own_ask = diff(page([upnext([card("B", { up: 1 })])]), page([upnext([card("B", { up: 1, do: ["m7"] })])]), [],
  (k) => k === "m:m7");
// TD-1789: the same, into a block the card already draws: no new block keeps it from `same`, its own line does
out.own_ask_in_block = diff(page([upnext([card("B", { up: 1, do: ["m6"] })])]),
  page([upnext([card("B", { up: 1, do: ["m6", "m7"] })])]), [], (k) => k === "m:m7");
// TD-1789: a block whose order differs from the drawn one only by the person's own item is no place change
out.own_reorder = diff(page([upnext([card("B", { up: 1, decide: ["m5", "m1", "m2"] })])]),
  page([upnext([card("B", { up: 1, decide: ["m1", "m5", "m2"] })])]), [], (k) => k === "m:m5");

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
// slice 2: a row whose entry was archived is *done* where it stands, not *gone*: moved into the ✓ n done fold, or
// drawn archived in its place; a header whose top entry was archived (no re-top) is *done*; both count *moved*
const dn = (d) => ({ ...diff(d[0], d[1]), doneUnits: AO.qDiff(AO.qModel(d[0]), AO.qModel(d[1])).doneUnits,
  doneHeads: AO.qDiff(AO.qModel(d[0]), AO.qModel(d[1])).doneHeads });
const one = (o) => page([group("in_progress", [card("A", o)])]);
out.done_fold = dn([one({ rows: ["a1", "a2"] }), one({ rows: ["a1"], fold: ["a2"] })]);
out.done_inline = dn([one({ rows: ["a1", "a2"] }), one({ rows: ["a1", "a2"], archived: ["a2"] })]);
out.done_drawn = dn([one({ rows: ["a1"], fold: ["a2"] }), one({ rows: ["a1"], fold: ["a2"] })]);
// a row drawn archived in its place that the reading moved into the fold: a place change, never *gone*
out.done_folded = dn([one({ rows: ["a1", "a2"], archived: ["a2"] }), one({ rows: ["a1"], fold: ["a2"] })]);
out.done_head = dn([one({ rows: ["a1"] }), one({ rows: ["a1"], headDone: 1 })]);
// slice 3: a re-top — a drawn card whose id is no card's in the reading is the reading's card holding its open
// members, where no drawn card has that card's id; one left over that a reading card holds has joined it
const rt = (a, b) => { const d = AO.qDiff(AO.qModel(a), AO.qModel(b));
  return { ...diff(a, b), retop: d.retop, joined: d.joined }; };
const up = (cards) => page([group("up_next", cards)]);
// B merged: the card is now A, its row A the new top's
out.retop = rt(up([card("B", { up: 1, ids: ["B", "A"], rows: ["A"] }), card("C", { up: 1 })]),
  up([card("A", { up: 1, ids: ["A"] }), card("C", { up: 1 })]));
// the re-read after: the card drawn under its new id, its new top's row still waiting for Refresh, never *gone*
{
  const c = card("A", { up: 1, ids: ["A", "x"], rows: ["A"] }); c.setAttribute("data-newtop", "A");
  out.retop_after = rt(up([c, card("C", { up: 1 })]),
    up([card("A", { up: 1, ids: ["A", "x"] }), card("C", { up: 1 })]));
}
// A archived splits its card in two: the half with most open members is the same card, the other new
out.split = rt(up([card("A", { up: 1, ids: ["A", "B", "C", "D"], rows: ["B", "C", "D"] })]),
  up([card("B", { up: 1, ids: ["B", "C"], rows: ["C"] }), card("D", { up: 1, ids: ["D"] })]));
// a new parent over two drawn cards re-tops the one sharing most members; the other has joined it
out.parent = rt(up([card("A", { up: 1, ids: ["A", "a1"], rows: ["a1"] }), card("B", { up: 1, ids: ["B"] })]),
  up([card("P", { up: 1, ids: ["P", "A", "a1", "B"], rows: ["A", "a1", "B"] })]));
// two hops: the top and a part archived, a blocked entry still open — the same card
out.two_hop = rt(up([card("A", { up: 1, ids: ["A", "B", "C"], rows: ["B", "C"] })]),
  up([card("C", { up: 1, ids: ["C"] })]));
// a drawn card the reading holds under its own id is never re-topped onto: it joined
out.join_drawn = rt(up([card("A", { up: 1, ids: ["A"] }), card("B", { up: 1, ids: ["B"] })]),
  up([card("B", { up: 1, ids: ["B", "A"], rows: ["A"] })]));
// the keys rewritten at once: id, members, header, Start session's card, folds, Up next's place
{
  const c = card("B", { up: 1, ids: ["B", "A"], rows: ["A"] });
  const fold = h("details", "qread", { "data-fold": "B:read" }, []);
  const start = h("button", "qstart", { "data-card": "B", "data-ref": "TD-1" }, []);
  c.children[0].appendChild(start); c.appendChild(fold);
  // its link to its own page, **Its own page** (TD-1763, TD-1808); a link to another card, and one whose id merely
  // starts the same, stay
  const links = ["/card/B", "/card/BB", "/card/C"]
    .map((href, i) => h("a", i ? "" : "qownpage", { href, "data-cardhref": "" }, []));
  links.forEach((a) => c.children[0].appendChild(a));
  const root = page([h("div", "qcards", { id: "qcards", "data-upnext": JSON.stringify(["B", "C"]) }, [c])]);
  root.children[0].id = "qcards";
  const r = card("A", { up: 1, ids: ["A", "x"] });
  AO.qRetop(c, r, root);
  out.rekey = { card: c.dataset.card, ids: c.dataset.ids, qid: c.children[0].dataset.qid, start: start.dataset.card,
    ref: start.dataset.ref, fold: fold.dataset.fold, upnext: JSON.parse(root.children[0].dataset.upnext),
    newtop: c.dataset.newtop, links: links.map((a) => a.getAttribute("href")) };
}

// TD-1784: qRankFrom's own after-anchor and the end of the reading; qModel's folds, nesting, a card twice, Up next
out.rank_after = AO.qRankFrom(drawn, ["B", "X", "C", "D"], "D", { after: "B" });
out.rank_end = AO.qRankFrom(drawn, ["B", "C", "D"], "B", { after: "D" });
const units = (root, id) => AO.qModel(root).cards.get(id).units;
// an item in the Read fold, a row in the ✓ n done fold, beside a Decide item and a row
out.model_blocks = units(page([group("in_progress", [h("div", "qcard", { "data-card": "A" }, [
  h("div", "qhead", { "data-qid": "A" }, [sec("decide", ["m1"]), h("details", "qread", {}, [item("m2")])]),
  h("div", "qrows", {}, [row("a1"), h("details", "qfold", {}, [row("a2", "archived")])])])])]), "A");
// a card nested in a card: each keeps its own units
const nested = page([group("in_progress", [h("div", "qcard", { "data-card": "P" }, [
  h("div", "qrows", {}, [row("p1"), card("N", { rows: ["n1"] })])])])]);
out.model_nested = { P: units(nested, "P"), N: units(nested, "N") };
// a card drawn twice is read once, where it is first
const twice = AO.qModel(page([group("in_progress", [card("A", { rows: ["a1"] })]),
  group("up_next", [card("B", { up: 1 }), card("A", { up: 1, rows: ["a9"] })])]));
out.model_twice = { order: twice.order, group: twice.cards.get("A").group, units: twice.cards.get("A").units };
// Up next's order, and a damaged one read as empty (the probe's selectors have no `#id`, so `#qcards` matches the
// copy's first descendant: the element carrying `data-upnext` stays first)
const withUp = (v) => h("div", "", {}, [h("div", "qcards", { id: "qcards", "data-upnext": v }, []),
  group("up_next", [card("B", { up: 1 })])]);
out.model_upnext = AO.qModel(withUp('["B","C"]')).upnext;
try { out.model_upnext_bad = AO.qModel(withUp("[B,")).upnext; } catch (e) { out.model_upnext_bad = "threw"; }

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


def test_a_card_in_recently_completed_in_both_copies_is_not_done_again(got):
    assert _counts(got["completed_both"]) == NOTHING


def test_a_card_that_leaves_carrying_a_new_ask_counts_once_as_the_ask(got):
    d = got["done_with_ask"]
    assert (d["asks"], d["done"], d["moved"], d["new"]) == (1, 0, 0, 0)


def test_a_hidden_card_that_leaves_is_not_done(got):
    assert _counts(got["hidden_leaves"]) == NOTHING


def test_a_card_arriving_in_recently_completed_is_not_new(got):
    assert _counts(got["new_completed"]) == NOTHING


def test_a_card_hidden_in_one_copy_only_is_moved(got):
    assert _counts(got["revealed"]) == {**NOTHING, "moved": 1, "words": ["1 card moved"]}


def test_a_row_arriving_alone_and_a_reorder_alone_are_each_moved(got):
    for case in ("row_arrives", "row_reorders"):
        d = got[case]
        assert _counts(d) == {**NOTHING, "moved": 1, "words": ["1 card moved"]}, case
        assert "A" not in d["same"], case


def test_asks_on_hidden_cards_and_the_persons_own_are_not_counted(got):
    assert _counts(got["hidden_asks"]) == NOTHING
    # a lagging re-read still holding the item the person's own press took off counts nothing, its card not moved
    # (TD-1785), and the card is not drawn whole from that reading
    assert _counts(got["own_ask"]) == NOTHING
    assert "B" not in got["own_ask"]["same"]
    assert _counts(got["own_ask_in_block"]) == NOTHING
    assert "B" not in got["own_ask_in_block"]["same"]


def test_an_order_changed_only_by_the_persons_own_item_is_no_place_change(got):
    # TD-1789: a lagging re-read in the old order around the person's own press counts nothing
    assert _counts(got["own_reorder"]) == NOTHING


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


def test_a_row_whose_entry_was_archived_is_done_not_gone_and_moves_its_card(got):
    for case in ("done_fold", "done_inline"):
        d = got[case]
        assert d["doneUnits"] == [["A", "r:a2"]] and d["gone"] == [], case
        assert d["moved"] == 1 and d["words"] == ["1 card moved"] and "A" not in d["same"], case
    d = got["done_folded"]
    assert d["gone"] == [] and d["doneUnits"] == [] and d["moved"] == 1
    # a row drawn done already is nothing new
    d = got["done_drawn"]
    assert d["doneUnits"] == [] and _counts(d) == NOTHING


def test_a_header_whose_top_was_archived_is_done(got):
    d = got["done_head"]
    assert d["doneHeads"] == ["A"] and d["moved"] == 1 and d["gone"] == []


def test_a_retopped_card_is_the_same_card_nothing_done_or_new(got):
    d = got["retop"]
    assert d["retop"] == [["B", "A"]] and d["joined"] == []
    # the new top's drawn row is neither *gone* nor patched: it waits for Refresh, a place change
    assert d["gone"] == [] and d["done"] == 0 and d["new"] == 0 and d["moved"] == 1


def test_the_new_tops_row_waits_on_every_reread_until_refresh(got):
    # review of slice 3: the exemption is the card's (`data-newtop`), not the one re-read's that re-topped it
    d = got["retop_after"]
    assert d["retop"] == [] and d["gone"] == [] and d["moved"] == 1 and d["same"] == ["C"]


def test_a_split_card_matches_the_half_with_most_open_members(got):
    d = got["split"]
    assert d["retop"] == [["A", "B"]] and d["new"] == 1 and d["done"] == 0
    assert d["gone"] == [["B", "r:D"]]  # keyed by the card's new id; D's row went to the other half


def test_a_new_parent_retops_one_card_and_the_other_has_joined(got):
    d = got["parent"]
    assert d["retop"] == [["A", "P"]] and d["joined"] == [["B", "P"]]
    assert (d["done"], d["new"], d["moved"]) == (1, 0, 1)


def test_a_two_hop_match_and_a_join_onto_a_drawn_card(got):
    assert got["two_hop"]["retop"] == [["A", "C"]] and got["two_hop"]["new"] == 0
    j = got["join_drawn"]
    assert j["retop"] == [] and j["joined"] == [["A", "B"]]
    assert (j["done"], j["moved"], j["new"]) == (1, 1, 0)


def test_a_retop_rewrites_the_cards_keys_at_once(got):
    assert got["rekey"] == {
        "card": "A",
        "ids": "A x",
        "qid": "A",
        "start": "A",
        "ref": "TD-1",  # a value: it waits with the words
        "fold": "A:read",
        "upnext": ["A", "C"],
        "newtop": "A",
        "links": ["/card/A", "/card/BB", "/card/C"],  # Its own page's (TD-1763, TD-1808)
    }


def test_a_retop_is_applied_before_the_hold_in_a_patch():
    p = Q[Q.index("function patch()") : Q.index("function drawBar(")]
    assert p.index("AO.qRetop(el, byId.get(to), lists)") < p.index("if (holds(el))")
    # the hold follows the card's new id (found by the scratch-home check: a hovered card lost its hold)
    assert "if (pointerOn === from) pointerOn = to;" in p and "if (boxOn === from) boxOn = to;" in p
    # a press sent before the re-top: its refusal and its keep find the card under its new id
    assert "while (renamed.has(id)) id = renamed.get(id);" in Q
    r = JS[JS.index("AO.qRetop = function") :]
    assert 'AO.inflight["qcard:" + to] = AO.inflight["qcard:" + from];' in r[: r.index("\n  };\n")]


def test_a_drop_after_a_card_keeps_its_anchor_and_the_end_sends_no_next(got):
    a = got["rank_after"]
    assert (a["prev"], a["next"]) == ("B", "X") and a["latest"] == ["B", "D", "X", "C"]
    e = got["rank_end"]
    assert e["prev"] == "D" and "next" in e and e["next"] is None  # null, never undefined (dropped by JSON)


def test_a_model_reads_each_block_and_each_card_once(got):
    assert got["model_blocks"] == {"decide": ["m:m1"], "read": ["m:m2"], "rows": ["r:a1"], "done": ["r:a2"]}
    assert got["model_nested"] == {"P": {"rows": ["r:p1"]}, "N": {"rows": ["r:n1"]}}
    assert got["model_twice"] == {"order": ["A", "B"], "group": "in_progress", "units": {"rows": ["r:a1"]}}


def test_a_model_reads_up_next_and_a_damaged_one_as_empty(got):
    assert got["model_upnext"] == ["B", "C"]
    assert got["model_upnext_bad"] == []


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
    assert "if (document.hidden || whole) drawWhole({ keepOpen: true }); else patch();" in read
    # a reading that fails, or answers without a served Queue, is no reading
    assert 'if (!fresh || !$("#qcounts", fresh)) { notLive(); return; }' in read
    assert "if (sent < lastMove) return;" in read  # a read that left before the last move is dropped
    assert 'refreshBtn.addEventListener("click"' in Q and "drawWhole({ slide: true });" in Q


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


def test_a_kept_button_is_wired_once_and_a_hold_ends_when_its_cause_does():
    # review of #TD-1761 slice 1: a patch keeps nodes, so `wire()` must not add Dismiss all's press twice
    w = Q[Q.index("function wire()") :]
    w = w[: w.index("AO.dismissOnScreen(")]
    assert "if (b.dataset.wired) return;" in w
    assert 'document.addEventListener("pointerout"' in Q  # the pointer leaving the window
    assert 'if (!document.querySelector("dialog[open]")) boxOn = "";' in Q  # a press that opened no box


def test_a_refused_press_ends_its_cards_hold():
    # §4.5 screen 12 *The person's own press is drawn at once*: the press handler names its card, and the Queue
    # patches that card past its hold
    assert 'document.dispatchEvent(new CustomEvent("ao:refused", { detail: { card: atCard } }))' in JS
    r = Q[Q.index('document.addEventListener("ao:refused"') :]
    r = r[: r.index("});")]
    assert "freed = id;" in r and "patch();" in r
    h = Q[Q.index("function holds(el)") :]
    h = h[: h.index("\n    }\n")]
    assert "if (id && id === freed) return false;" in h


def test_a_hidden_page_holds_only_by_a_menu_or_a_box():
    h = Q[Q.index("function holds(el)") :]
    h = h[: h.index("\n    }\n")]
    # a menu or a box is read before the page's hidden state, every other hold after it
    assert h.index("details.more[open]") < h.index("if (document.hidden) return false;") < h.index("pointerOn")
    w = Q[Q.index("function drawWhole(opts)") : Q.index("function slide(was)")]
    assert "kept.forEach((k) => k.node.remove());" in w and "there.replaceWith(k.node)" in w
    # focus back on the same card's header, or the next card's where it left
    assert '.qcard[data-card="${CSS.escape(focusCard)}"] > .qhead' in w


def test_refresh_slides_the_cards_in_200_ms_or_at_once_under_reduced_motion():
    s = Q[Q.index("function slide(was)") :]
    s = s[: s.index("\n    }\n")]
    assert "const SLIDE_MS = 200;" in Q
    assert s.index('matchMedia("(prefers-reduced-motion: reduce)").matches) return;') < s.index("translateY")
    assert "sliding = Date.now() + SLIDE_MS;" in s
    # presses during the slide are ignored
    ignored = "if (Date.now() < sliding) { e.preventDefault(); e.stopPropagation(); }"
    assert f'lists.addEventListener("click", (e) => {{ {ignored} }}, true);' in Q


def test_completed_and_other_work_lines_patch_by_key_and_count_nothing():
    # slice 4: §4.5 screen 12 *Values are patched in place* — Recently completed's lines and the other-work lines
    # patch by key, keeping the window's `hidden`, the picks' `qoff` and an opened body; nothing counts them
    from pathlib import Path

    p = Q[Q.index("function patch()") : Q.index("function drawBar(")]
    assert "patchLines();" in p
    lines = Q[Q.index("function patchLines()") :]
    lines = lines[: lines.index("\n    }\n")]
    assert '".qdline[data-key], .qother[data-key]"' in lines
    assert 'n.hidden = hid; n.classList.toggle("qoff", off);' in lines and "if (open) openLine(n);" in lines
    assert "if (!r || !quiet(el)) return;" in lines  # a line gone from the reading stays as drawn
    t = Path(APP_JS).parents[1] / "templates" / "queue_part.html"
    assert 'data-other="1" data-key="{{ o.ref }}"' in t.read_text()
    m = JS[JS.index("AO.qModel = function") :]
    assert ".qgroup .qcard[data-card]" in m[: m.index("\n  };\n")]  # lines are no cards: the bar never counts them
