"""TD-1461 (TD-1436's build), design §4.5 screen 6 rule 4 *A Queue card's own state follows the press*: a press that
takes an item out of a card's Decide or Do block takes one off the pill and the block's heading in the press's frame,
a pill left with neither drops and the card is drawn plain (a `data-lneed` card keeps its look and draws *Needs you*),
the summary recounts, a re-read while the press is out keeps the change, and a refusal puts it back. The draw runs
under node on `test_ui_press_draw`'s small DOM (`AO.qcardOff`, `qcardBack`, `qcardReapply`, `qPillText`); the
source pins hold the click handler's and the Queue's wiring."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from test_ui_press_draw import APP_JS, PROBE
from test_ui_queue import NOW, queue

from shiftlead.ui.app import templates
from shiftlead.ui.queue import queue_view

DOM = PROBE.split("// ---- fixtures")[0]

CASES = r"""
global.CSS = { escape: (s) => s };
let page = h("div", "", {}, []);
document.querySelector = (sel) => page.querySelector(sel);
let recounts = [];
const needing = () => page.querySelectorAll(".qcard").filter((c) => c.dataset.status === "needs you").length;
AO.qRecount = () => recounts.push(needing());
const out = {};
const item = (msg) => h("div", "mailrow", { "data-msg": msg }, [h("div", "rowerr")]);
const block = (b, msgs) => h("div", `qsec qwant qsec-${b}`, { "data-sec": b }, [
  h("div", "qsech", {}, [h("span", "", { text: AO.qCountWords(b, msgs.length), "data-n": msgs.length })]),
  h("div", "qmail inboxrows", {}, msgs.map(item))]);
const pillOf = (d, n) => [d ? `Decide ${d}` : "", n ? `Do ${n}` : ""].filter(Boolean).join(" · ");
// a card as the server draws it: Decide and Do in the header, its pill at the header line's end, Read under the rows
const qcard = (id, o) => {
  const d = o.decide || [], n = o.do || [];
  const right = h("span", "qright", {}, [h("span", "qgap"),
    ...(d.length || n.length ? [h("span", "qstatus needsyou qwpill", { text: pillOf(d.length, n.length) })] : [])]);
  const head = h("div", "qhead", { "data-qid": id }, [h("div", "qmain", {}, [right,
    ...(d.length ? [block("decide", d)] : []), ...(n.length ? [block("do", n)] : []),
    ...(o.with ? [h("div", "qsec qwith", { "data-sec": "with_you" }, [item(o.with)])] : [])])]);
  const waiting = { "data-sec": "waiting" };
  const rd = h("div", "qrows", {}, [h("details", "qread", {}, [h("div", "qsec qsec-waiting", waiting, [
    h("div", "qsech", {}, [h("span", "", { text: "One waiting on them", "data-n": 1 })]),
    h("div", "qmail", {}, (o.read || []).map(item))])])]);
  const attrs = { "data-card": id, "data-status": "needs you" };
  if (o.lneed) attrs["data-lneed"] = "";
  return h("div", `qcard edge-needs g-${o.group || "up_next"} st-needs-you wants`, attrs, [head, rd]);
};
const look = (c) => {
  const right = c.querySelector(".qhead .qright");
  return { pill: (c.querySelector(".qwpill") || {}).textContent || null,
    hd: c.querySelectorAll(".qsech span").map((x) => x.textContent),
    n: c.querySelectorAll(".qsech span").map((x) => x.dataset.n),
    cls: c.className.split(" ").sort().join(" "), status: c.dataset.status,
    line: right.children.map((x) => x.className + (x.textContent ? `=${x.textContent}` : "")) };
};
const rowIn = (c, msg) => c.querySelectorAll(".mailrow").find((r) => r.dataset.msg === msg);
const press = (c, msg) => {
  AO.inflight[msg] = { leaves: true, kind: "left" };
  return AO.qcardOff(rowIn(c, msg), msg);
};
const reset = (...cards) => { AO.inflight = {}; recounts = []; page = h("div", "", {}, cards); return cards; };

out.pill = [[2, 1], [0, 1], [1, 0]].map(([d, n]) => AO.qPillText(d, n));
// *The Queue's words* (TD-1809): every heading's words for 0, 1 and 2, the twin of `count_words`
out.words = Object.fromEntries(["decide", "do", "read", "answered", "waiting", "fyi"].map((b) => [b,
  [0, 1, 2].map((n) => AO.qCountWords(b, n))]));

// a Decide press on *Decide 2*: pill and heading one fewer, the look kept
let [c] = reset(qcard("A", { decide: ["m1", "m2"] }));
out.two = { key: press(c, "m1"), look: look(c), recounts };
// *Decide 1 · Do 1* after its Decide reads *Do 1*; the emptied block's heading reads *No decision left for you*
[c] = reset(qcard("B", { decide: ["m1"], do: ["m2"] }));
press(c, "m1"); out.mixed = look(c);
// the last Decide on a card with no Do: the pill, the needs-you look and the status go, the edge the group's
out.plain = ["up_next", "waiting", "in_progress"].map((g) => {
  const [x] = reset(qcard("C", { decide: ["m1"], group: g }));
  press(x, "m1");
  return { look: look(x), recounts, off: x.classList.contains("qoff") };
});
// a card whose ledger status is itself *needs you* keeps its look and draws *Needs you* where its pill was
[c] = reset(qcard("D", { decide: ["m1"], lneed: true }));
press(c, "m1"); out.lneed = look(c);
AO.qcardBack("m1"); out.lneed_back = { look: look(c), keep: !!AO.inflight["qcard:D"] };
// the ⋯ road's Done… takes the card's *ledger · your decision* item off its own block (Do here)
[c] = reset(qcard("E", { decide: ["m1"], do: ["ledger:s:TD-9"] }));
AO.inflight["ledger:s:TD-9"] = { leaves: true, kind: "left" };
AO.qcardOff(rowIn(c, "ledger:s:TD-9"), "ledger:s:TD-9"); out.dots = look(c);
// an item outside Decide and Do — Read's, one *with you* — takes nothing off, and no keep is made
[c] = reset(qcard("F", { decide: ["m1"], read: ["r1"], with: "w1" }));
out.read = { keys: [AO.qcardOff(rowIn(c, "r1"), "r1"), AO.qcardOff(rowIn(c, "w1"), "w1")], look: look(c),
  keep: Object.keys(AO.inflight), recounts };
// a re-read while the press is out: the fresh card, which still draws the item, has it taken off again
[c] = reset(qcard("G", { decide: ["m1", "m2"] }));
press(c, "m1");
let fresh = qcard("G", { decide: ["m1", "m2"] }); page = h("div", "", {}, [fresh]);
AO.qcardReapply(page); out.reread = { look: look(fresh), keys: AO.inflight["qcard:G"].keys };
// …and one that draws the decided board line under Read: the key leaves the keep, the server's count stands
fresh = qcard("G", { decide: ["m2"], read: ["m1"] }); page = h("div", "", {}, [fresh]);
AO.qcardReapply(page); out.landed = { look: look(fresh), keep: !!AO.inflight["qcard:G"] };
// a re-read after an item's minute, the board not yet landed: nothing taken off for it
[c] = reset(qcard("H", { decide: ["m1", "m2"] }));
const said = (until) => ({ kind: "decided", text: "decided: Yes — written on the board", until });
press(c, "m1"); AO.inflight.m1 = said(Date.now() - 1);
fresh = qcard("H", { decide: ["m1", "m2"] }); page = h("div", "", {}, [fresh]);
AO.qcardReapply(page); out.spent = { look: look(fresh), keep: !!AO.inflight["qcard:H"] };
// a decided board line within its minute, the fresh row not drawing it yet: still taken off, the row drawn decided
[c] = reset(qcard("I", { decide: ["m1", "m2"] }));
press(c, "m1"); AO.inflight.m1 = said(Date.now() + 60000);
fresh = qcard("I", { decide: ["m1", "m2"] }); page = h("div", "", {}, [fresh]);
AO.qcardReapply(page); out.minute = look(fresh);
// two presses, the card drawn plain, refused one after the other
[c] = reset(qcard("J", { decide: ["m1", "m2"] }), qcard("K", { decide: ["x"] }));
press(c, "m1"); press(c, "m2"); out.both = look(c);
recounts = [];
AO.qcardBack("m1"); out.back1 = { look: look(c), recounts: [...recounts] };
AO.qcardBack("m2"); out.back2 = { look: look(c), recounts: [...recounts], keep: !!AO.inflight["qcard:J"] };
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def drew(tmp_path_factory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    probe = tmp_path_factory.mktemp("qcard_press") / "qcard_press_probe.js"
    probe.write_text(DOM + CASES)
    got = subprocess.run(["node", str(probe), str(APP_JS)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(got.stdout.strip().splitlines()[-1])


NEEDS = "edge-needs g-up_next qcard st-needs-you wants"  # sorted, as `look` reads it
PILL = "qstatus needsyou qwpill"


def test_the_scripts_pill_text_is_the_macros(drew):
    pill = templates.env.get_template("queue_row.html").module.pill
    for (d, n), js in zip([(2, 1), (0, 1), (1, 0)], drew["pill"], strict=True):
        html = str(pill({"wants": {"n": {"decide": d, "do": n}}}))
        assert re.search(r">([^<]*)</span>$", html)[1] == js


def test_the_scripts_count_words_are_the_macros(drew):
    """§4.5 screen 12 *The Queue's words: Counts in words* (TD-1809): `AO.qCountWords` and `count_words` write the
    same words for every key at 0, 1 and 2."""
    count_words = templates.env.get_template("queue_row.html").module.count_words
    assert set(drew["words"]) == {"decide", "do", "read", "answered", "waiting", "fyi"}
    for block, js in drew["words"].items():
        assert [str(count_words(block, n)) for n in (0, 1, 2)] == js
    assert drew["words"]["decide"] == ["No decision left for you", "One decision for you", "2 decisions for you"]
    assert drew["words"]["do"] == ["Nothing left for you to do", "One thing for you to do", "2 things for you to do"]
    assert drew["words"]["read"] == ["", "One to read", "2 to read"]
    assert drew["words"]["answered"] == ["", "One answered for you", "2 answered for you"]
    assert drew["words"]["waiting"] == ["", "One waiting on them", "2 waiting on them"]
    assert drew["words"]["fyi"] == ["", "One for your information", "2 for your information"]


def test_a_decide_press_takes_one_off_the_pill_and_heading_in_the_press_frame(drew):
    assert drew["two"]["key"] == "qcard:A"
    assert drew["two"]["look"] == {
        "pill": "Decide 1", "hd": ["One decision for you", "One waiting on them"], "n": ["1", "1"], "cls": NEEDS,
        "status": "needs you", "line": ["qgap", f"{PILL}=Decide 1"],
    }  # fmt: skip
    assert drew["two"]["recounts"] == [1]
    assert drew["mixed"]["pill"] == "Do 1"
    assert drew["mixed"]["hd"][:2] == ["No decision left for you", "One thing for you to do"]
    assert drew["mixed"]["n"][:2] == ["0", "1"]  # the words and `data-n` redrawn together


def test_the_last_one_drops_the_pill_and_draws_the_card_plain_on_the_groups_edge(drew):
    groups = ["up_next", "waiting", "in_progress"]
    for got, edge, g in zip(drew["plain"], ["ended", "waiting", "working"], groups, strict=True):
        assert got["look"]["pill"] is None and got["look"]["line"] == ["qgap"]
        assert got["look"]["cls"] == f"edge-{edge} g-{g} qcard" and got["look"]["status"] == ""
        assert got["recounts"] == [0] and got["off"] is False  # recounted, still shown until the next apply


def test_a_card_whose_ledger_needs_you_keeps_its_look_and_says_needs_you(drew):
    assert drew["lneed"]["cls"] == NEEDS and drew["lneed"]["status"] == "needs you"
    assert drew["lneed"]["line"] == ["qgap", "qstatus needsyou=Needs you"]
    # a refusal brings the pill back in the word's place
    assert drew["lneed_back"]["look"]["line"] == ["qgap", f"{PILL}=Decide 1"] and drew["lneed_back"]["keep"] is False


def test_the_dots_road_takes_the_ledger_item_off_its_own_block(drew):
    assert drew["dots"]["pill"] == "Decide 1"
    assert drew["dots"]["hd"][:2] == ["One decision for you", "Nothing left for you to do"]


def test_an_item_outside_decide_and_do_takes_nothing_off(drew):
    assert drew["read"]["keys"] == [None, None] and drew["read"]["keep"] == [] and drew["read"]["recounts"] == []
    assert drew["read"]["look"]["pill"] == "Decide 1"


def test_a_reread_keeps_the_change_while_the_press_is_out(drew):
    assert drew["reread"]["look"]["pill"] == "Decide 1" and drew["reread"]["look"]["hd"][0] == "One decision for you"
    assert drew["reread"]["keys"] == {"decide": ["m1"], "do": []}
    assert drew["minute"]["pill"] == "Decide 1"


def test_a_reread_drawing_the_line_under_read_or_past_its_minute_lets_the_key_go(drew):
    assert drew["landed"]["look"]["pill"] == "Decide 1" and drew["landed"]["keep"] is False
    assert drew["spent"]["look"]["pill"] == "Decide 2" and drew["spent"]["keep"] is False


def test_refusals_put_the_card_back_one_press_at_a_time(drew):
    assert drew["both"]["pill"] is None and drew["both"]["status"] == ""
    assert drew["back1"]["look"] == {
        "pill": "Decide 1", "hd": ["One decision for you", "One waiting on them"], "n": ["1", "1"], "cls": NEEDS,
        "status": "needs you", "line": ["qgap", f"{PILL}=Decide 1"],
    }  # fmt: skip
    assert drew["back1"]["recounts"] == [2]  # the card counts as needing the person again, beside K
    assert drew["back2"]["look"]["pill"] == "Decide 2" and drew["back2"]["look"]["hd"][0] == "2 decisions for you"
    assert drew["back2"]["keep"] is False


JS = APP_JS.read_text()


def test_the_click_handler_and_the_queue_are_wired():
    # the press takes it before the row leaves; a board Reply (and every non-rule-4 press) takes nothing
    pressed = JS[JS.index("const pressed = (text) => {") :]
    assert pressed.index('if (r4 && key !== "board_reply") AO.qcardOff(row, msgOf);') < pressed.index("row.remove()")
    assert "AO.qcardOff(r, qled); AO.handRing(r); r.remove();" in JS  # the ⋯ road, per removed row
    # the two refusal branches alone give the press's one back
    assert JS.count("AO.qcardBack(") == 2
    assert "AO.pressErrs[qled] = words; delete AO.inflight[qled];\n        AO.qcardBack(qled);" in JS
    assert "AO.pressErrs[msgOf] = words;\n          AO.qcardBack(msgOf);" in JS
    # the Queue's re-read reapplies the keep before the items' own keep takes a left row out
    q = JS[JS.index("AO.queue = function") :]
    assert q.index("AO.qcardReapply(lists);") < q.index("AO.restoreRowErrs(lists, errs);")
    assert "AO.qRecount = () => { if (filters) AO.qDrawSummary(" in q
    # the click handler's `finally` never lets a card's keep go
    fin = JS[JS.index("    } finally {\n      // a rule 4 press that was answered") :][:900]
    assert "qcard" not in fin


def test_the_server_marks_a_card_whose_ledger_status_needs_you():
    q = queue()
    q["cards"][0]["status"] = "needs you"
    v = queue_view(q, NOW)
    cards = [*v["in_progress"], *v["waiting"], *v["up_next"]]
    by = {c["id"]: c for c in cards}
    first = by[q["cards"][0]["id"]]
    raw = {c["id"]: c.get("status") == "needs you" for c in q["cards"]}
    assert first["lneed"] is True and all(c["lneed"] is raw[c["id"]] for c in cards) and not all(raw.values())
    card = templates.env.get_template("queue_card.html").module.card
    assert " data-lneed>" in str(card(first))
    assert "data-lneed" not in str(card(next(c for c in cards if not c["lneed"])))
