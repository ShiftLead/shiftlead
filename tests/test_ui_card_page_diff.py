"""TD-1762, design §4.5 screen 12 *The card's page*: a card's page's bar counts what changed on its one card —
*n new items* (asks first, amber), *moved to <group>*, *done*, *n changed* — and, where the reading holds no card with
the page's id, *done* or *no longer on the Queue* alone, every item and row *gone* but one the person's own press
answered. This runs `AO.cardDiff` and `AO.cardBarParts` under node on `test_ui_holds_still`'s small DOM."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from test_ui_holds_still import CASES as HOLDS
from test_ui_press_draw import APP_JS, PROBE

DOM = PROBE.split("// ---- fixtures")[0]
FIXTURES = HOLDS.split("const diff = ")[0]

CASES = r"""
const cd = (a, b, o) => {
  o = o || {};
  const d = AO.cardDiff(AO.qModel(page([a])), AO.qModel(page(b ? [b] : [])), "A", !!b, o.topDone, o.own);
  return { ...d, words: AO.cardBarParts(d).map((p) => (typeof p === "string" ? p : "ASK " + p.t)) };
};
const A = (g, o) => group(g, [card("A", o)]);
out.same = cd(A("up_next", { decide: ["m1"], rows: ["a1"] }), A("up_next", { decide: ["m1"], rows: ["a1"] }));
out.new_ask = cd(A("up_next", { decide: ["m1"] }), A("up_next", { decide: ["m1", "m2"] }));
out.moved_block = cd(A("up_next", { decide: ["m1"] }), A("up_next", { do: ["m1"] }));
out.moved_group = cd(A("up_next", {}), A("waiting", {}));
out.completed = cd(A("up_next", {}), A("completed", {}));
out.gone_item = cd(A("up_next", { decide: ["m1", "m2"] }), A("up_next", { decide: ["m2"] }));
out.own_press = cd(A("up_next", { decide: ["m1"] }), A("up_next", {}), { own: (k) => k === "m:m1" });
out.row_archived = cd(A("up_next", { rows: ["a1"] }), A("up_next", { rows: ["a1"], archived: ["a1"] }));
out.row_arrives = cd(A("up_next", { rows: ["a1"] }), A("up_next", { rows: ["a1", "a2"] }));
out.reorder = cd(A("up_next", { rows: ["a1", "a2"] }), A("up_next", { rows: ["a2", "a1"] }));
out.left = cd(A("up_next", { decide: ["m1", "m2"], rows: ["a1"] }), null, { own: (k) => k === "m:m2" });
out.left_done = cd(A("up_next", { decide: ["m1"] }), null, { topDone: "1" });
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def got(tmp_path_factory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    probe = tmp_path_factory.mktemp("card_page") / "card_page_probe.js"
    probe.write_text(DOM + FIXTURES + CASES)
    run = subprocess.run(["node", str(probe), str(APP_JS)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_nothing_changed_counts_nothing_and_patches_whole(got):
    assert got["same"]["words"] == [] and got["same"]["same"] is True and not got["same"]["left"]


def test_a_new_ask_is_amber_and_an_item_moving_block_counts_once(got):
    assert got["new_ask"]["words"] == ["ASK 1 new item"]
    assert got["moved_block"]["words"] == ["ASK 1 new item"] and got["moved_block"]["gone"] == ["m:m1"]


def test_moved_names_an_open_group_and_completing_is_done(got):
    assert got["moved_group"]["words"] == ["moved to Waiting"]
    assert got["completed"]["words"] == ["done"]


def test_a_gone_item_an_archived_row_a_row_arriving_and_a_reorder_each_change(got):
    assert got["gone_item"]["words"] == ["1 changed"] and got["gone_item"]["gone"] == ["m:m1"]
    assert got["row_archived"]["words"] == ["1 changed"] and got["row_archived"]["doneUnits"] == ["r:a1"]
    assert got["row_arrives"]["words"] == ["1 changed"]
    assert got["reorder"]["words"] == ["1 changed"]


def test_the_persons_own_press_is_never_gone_or_counted(got):
    assert got["own_press"]["words"] == [] and got["own_press"]["gone"] == []


def test_a_card_the_reading_no_longer_holds_is_gone_whole_its_bar_alone(got):
    assert got["left"]["left"] is True and got["left"]["words"] == ["no longer on the Queue"]
    assert got["left"]["gone"] == ["m:m1", "r:a1"]  # its own press's item keeps its result
    assert got["left_done"]["words"] == ["done"]
