"""TD-1555: an Answer… sends to the item it was pressed on, whatever the page re-reads under the open box.

On 2026-11-07 Paul pressed Answer… meaning a board decide line (TD-1437's end-of-rounds item) and his words were
stored as a mail reply to another card's ask (TD-1529's): the Queue's re-read had moved the cards under the
cursor. The box now reads its target from the button when it is pressed, names the item in its title, and is closed
(the words kept) when a re-read takes its item off the page (design §4.5 screen 12 *Three verbs: Answer*).
"""

import json
import shutil
import subprocess

import pytest
from test_ui_queue_cards import FOLDS_PROBE, JS

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

ANSWER_PROBE = (
    FOLDS_PROBE[: FOLDS_PROBE.index("eval(fs.readFileSync")]
    + r"""
global.CSS = { escape: (s) => s };
// the compose box and its fields, by id; a dialog fires its `close` listeners as the browser's does
const field = () => ({ value: "", textContent: "", hidden: false, focus: noop, onchange: null });
const box = { open: false, returnValue: "", heard: [], addEventListener: (t, f) => box.heard.push(f),
  showModal: () => { box.open = true; },
  close: (v) => { box.open = false; box.returnValue = v || ""; box.heard.splice(0).forEach((f) => f()); } };
const ids = { "#mailbox": box, "#mailtitle": field(), "#mailtext": field(), "#mailkind": field(), "#mailabout": field(),
  "#mailquote": field(), "#mailkindrow": field() };
// the page's item rows by their key; a re-read replaces them (the pressed ones are then detached)
let live = {};
document.querySelector = (sel) => {
  if (ids[sel]) return ids[sel];
  const m = /^\.mailrow\[data-msg="(.*)"\]$/.exec(sel);
  return m ? live[m[1]] || null : null;
};
document.querySelectorAll = () => [];
// a row as a Queue card draws it, with its *on <ref>* link before it, and its Answer… button inside it
const row = (msg, kind, on, data) => {
  const r = { dataset: { msg, kind, text: data.text || "" }, isConnected: true, querySelector: () => null,
    classList: { contains: () => false, add: noop, remove: noop, toggle: noop },
    setAttribute: noop, removeAttribute: noop, getAttribute: () => null,
    remove: noop, appendChild: noop, insertAdjacentHTML: noop, style: {},
    querySelectorAll: () => [], contains: () => false, focus: noop,
    previousElementSibling: { matches: (s) => s === ".qon", dataset: { on } } };
  r.closest = (sel) => (sel.includes(".boardrow") && kind === "board" ? r : sel === ".mailrow" ? r : null);
  const b = { dataset: data, classList: { contains: () => false }, parentElement: null };
  b.closest = (sel) =>
    sel === "[data-act], [data-copy]" ? b
      : sel === ".mailrow" ? r : sel.includes(".boardrow") && kind === "board" ? r : null;
  r.button = b;
  return r;
};
let observe = null;
global.MutationObserver = class { constructor(f) { observe = f; } observe() {} disconnect() { observe = null; } };
const posts = [];
global.fetch = (url, o) => { posts.push({ url, body: JSON.parse(o.body) });
  return Promise.resolve({ ok: true, json: () => Promise.resolve({}) }); };
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const toasts = [];
AO.toast = (t) => { toasts.push(t); return { settle: noop }; };
AO.refreshInboxPage = noop;
const tick = () => new Promise((r) => setImmediate(r));
const press = async (b) => { heard.click.forEach((f) => f({ target: b, shiftKey: false })); await tick(); };
// a board row's id names its line's number (`board:<root>:<line>`), its `data-key` the line's own key
const draw = (line) => {
  const board = row(`board:r:${line || 17}`, "board", "shiftlead#TD-1437", { act: "board_reply", id: "person",
    board: "docs/user_attention.md", key: "board:k1", line: String(line || 17), refs: "[]",
    name: "shiftlead's board", text: "Decide the end of TD-1437's rounds" });
  const ask = row("m-998", "ask", "shiftlead#TD-1529", { act: "reply", id: "person", msg: "m-998", from: "designer",
    name: "designer", quote: "td-max's shape?" });
  return { board, ask };
};
const out = {};
(async () => {
  // 1. Answer… on the board line; under the open box a re-read reorders the cards, and the pressed button is
  //    rewritten to carry the ask's data (the worst a swap could do): the words still go to the board line
  let p = draw(); live = { "board:r:17": p.board, "m-998": p.ask };
  await press(p.board.button);
  out.title = ids["#mailtitle"].textContent;
  const fresh = draw(); live = { "m-998": fresh.ask, "board:r:17": fresh.board };
  p.board.isConnected = false; p.ask.isConnected = false;
  p.board.button.dataset = { ...p.ask.button.dataset };
  p.board.dataset = { ...p.ask.dataset };  // and its row, so a send reading the line's text late reads the ask's
  if (observe) observe();
  ids["#mailtext"].value = "Hold: drop Dismiss";
  box.close("send"); await tick(); await tick();
  out.first = posts.splice(0);
  // 2. Answer… on the ask, with the board line drawn where it was: the words go back as the ask's reply
  p = draw(); live = { "board:r:17": p.board, "m-998": p.ask };
  await press(p.ask.button);
  out.askTitle = ids["#mailtitle"].textContent;
  p.ask.button.dataset = { ...p.board.button.dataset };
  ids["#mailtext"].value = "go wide";
  box.close("send"); await tick(); await tick();
  out.second = posts.splice(0);
  // 3. a re-read that takes the item off the page closes the box: nothing is sent, the words are kept and come
  //    back when Answer… is pressed on the same item again
  p = draw(); live = { "board:r:17": p.board, "m-998": p.ask };
  await press(p.ask.button);
  ids["#mailtext"].value = "words in flight";
  live = { "board:r:17": draw().board };
  if (observe) observe();
  await tick();
  out.gone = { open: box.open, posts: posts.splice(0), toast: toasts[toasts.length - 1] || "" };
  ids["#mailtext"].value = "";
  p = draw(); live = { "m-998": p.ask };
  await press(p.ask.button);
  out.kept = ids["#mailtext"].value;
  box.close("cancel"); await tick();
  // 4. a line added above the board line moves it: its row's id changes, so the box closes; its words are kept by
  //    the line's own key and come back on its Answer… at its new place
  p = draw(); live = { "board:r:17": p.board };
  await press(p.board.button);
  ids["#mailtext"].value = "kept across a move";
  const moved = draw(18).board; live = { "board:r:18": moved };
  if (observe) observe();
  await tick();
  out.movedOpen = box.open;
  ids["#mailtext"].value = "";
  await press(moved.button);
  out.movedKept = ids["#mailtext"].value;
  box.close("cancel"); await tick();
  // 5. Not right… (TD-1563): its box names the board line, and its words are kept by the line's own key, so they
  //    come back on its Not right… at the line's new place after a line added above it moved the row's id
  const nr = row("board:r:17", "board", "shiftlead#TD-1437", { ...draw().board.button.dataset, act: "board_notright" });
  live = { "board:r:17": nr };
  await press(nr.button);
  out.nrTitle = ids["#mailtitle"].textContent;
  ids["#mailtext"].value = "Not right: the toast is cut off";
  const nrMoved = row("board:r:18", "board", "shiftlead#TD-1437", { ...nr.button.dataset, line: "18" });
  live = { "board:r:18": nrMoved };
  if (observe) observe();
  await tick();
  out.nrOpen = box.open;
  ids["#mailtext"].value = "";
  await press(nrMoved.button);
  out.nrKept = ids["#mailtext"].value;
  box.close("cancel"); await tick();
  // 6. a ledger entry's roads (TD-1563): Reply, Done… and Back to design… each name the entry in the box's title, and
  //    a re-read that takes the entry's row away closes the box, sending nothing, its words back on the next press
  const ledger = (road) => row("ledger:shiftlead:TD-9", "ledger", "shiftlead#TD-1437", {
    act: road ? "ledger" : "ledger_reply", ...(road ? { road } : {}), repo: "shiftlead", ref: "TD-9",
    name: "shiftlead's board", quote: "Close TD-9?" });
  for (const road of ["", "done", "design"]) {
    let l = ledger(road); live = { "ledger:shiftlead:TD-9": l };
    await press(l.button);
    const title = ids["#mailtitle"].textContent;
    ids["#mailtext"].value = `words for ${road || "reply"}`;
    live = {};
    if (observe) observe();
    await tick();
    const open = box.open, sent = posts.splice(0);
    ids["#mailtext"].value = "";
    l = ledger(road); live = { "ledger:shiftlead:TD-9": l };
    await press(l.button);
    out[`ledger_${road || "reply"}`] = { title, open, sent, kept: ids["#mailtext"].value };
    box.close("cancel"); await tick();
  }
  console.log(JSON.stringify(out));
})();
"""
)


def run_probe(tmp_path, probe):
    f = tmp_path / "probe.js"
    f.write_text(probe)
    got = subprocess.run(["node", str(f), str(JS)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(got.stdout.strip().splitlines()[-1])


def test_answer_sends_to_the_item_it_was_pressed_on_across_a_reread(tmp_path):
    out = run_probe(tmp_path, ANSWER_PROBE)
    # the box names the item, not only the addressee
    assert out["title"] == "Reply to shiftlead's board · the board line board:k1 on shiftlead#TD-1437"
    assert out["askTitle"] == "Reply to designer · the ask on shiftlead#TD-1529"
    # the board line gets the reply; no mail reply is posted
    assert [p["url"] for p in out["first"]] == ["/api/person/board"]
    # the whole body is the press-time copy's: the board file it is written to and the line it is matched against
    # too, though the button and its row now carry the ask's data (TD-1562)
    assert out["first"][0]["body"] == {
        "action": "reply",
        "board": "docs/user_attention.md",
        "line": 17,
        "text": "Decide the end of TD-1437's rounds",
        "key": "board:k1",
        "reply": "Hold: drop Dismiss",
        "refs": [],
    }
    # a mail item's Answer… is the ask's reply, whatever was drawn where it was
    assert out["second"] == [{"url": "/api/person/reply", "body": {"reply_to": "m-998", "text": "go wide"}}]


def test_a_reread_that_takes_the_item_away_closes_the_box_with_its_words_kept(tmp_path):
    out = run_probe(tmp_path, ANSWER_PROBE)
    assert out["gone"]["open"] is False and out["gone"]["posts"] == []
    assert out["gone"]["toast"].startswith("the item changed — your words are kept")
    assert out["kept"] == "words in flight"
    # a board line's words are kept by its own key, which outlives its row's id when the line moves
    assert out["movedOpen"] is False and out["movedKept"] == "kept across a move"


def test_not_right_and_the_ledger_roads_are_bound_to_their_item(tmp_path):
    """§4.5 screen 12 *Three verbs: Answer* binds every road — a mail reply, a board line's, a ledger entry's (TD-1563):
    Not right… keeps its words by the line's `board:<key>`, and Reply, Done… and Back to design… on a ledger entry
    name the entry and close, sending nothing, when a re-read takes its row away."""
    out = run_probe(tmp_path, ANSWER_PROBE)
    assert out["nrTitle"] == "Reply to shiftlead's board · the board line board:k1 on shiftlead#TD-1437"
    assert out["nrOpen"] is False and out["nrKept"] == "Not right: the toast is cut off"
    for road in ("reply", "done", "design"):
        got = out[f"ledger_{road}"]
        assert got["title"] == "Reply to shiftlead's board · the entry TD-9 on shiftlead#TD-1437", road
        assert got["open"] is False and got["sent"] == [], road
        assert got["kept"] == f"words for {road}", road


CARD_MENUS_PROBE = (
    FOLDS_PROBE[: FOLDS_PROBE.index("const AO = window.AO;")]
    + """
const AO = window.AO;
global.CSS = { escape: (s) => s };
// a card (data-qid) with its own two menus and its items' menus inside it, each item a row (data-msg)
const menu = (home, open) => ({ open: !!open, home, closest: () => home, addEventListener: noop,
  querySelector: () => null, querySelectorAll: () => [] });
const card = (items, open) => {
  const c = { dataset: { qid: "s#TD-1" } };
  const rows = items.map((m) => ({ dataset: { msg: m } }));
  rows.forEach((r) => { r.menus = [menu(r, open.includes(r.dataset.msg))]; r.querySelectorAll = () => r.menus; });
  // the card's own menus, its header's ⋯ first and a row's last, the items' between them in their order
  const own = [menu(c, open.includes("head")), menu(c, open.includes("tail"))];
  c.all = [own[0], ...rows.flatMap((r) => r.menus), own[1]];
  c.querySelectorAll = (sel) => (sel === "details.more" ? c.all : []);
  const homes = [c, ...rows];
  const opened = (sel) => (sel === "details.more[open]" ? c.all.filter((d) => d.open) : []);
  const named = (sel) => homes.find((h) => Object.entries(h.dataset).some(([k, v]) => sel === `[data-${k}="${v}"]`));
  return { c, rows, all: () => c.all, querySelectorAll: opened, querySelector: (sel) => named(sel) || null };
};
const before = card(["a", "b", "c"], ["tail", "b"]);
const keys = AO.openMenus(before);
const after = card(["c", "a"], []);  // the re-read reorders the card's items, and item b has left
AO.reopenMenus(after, keys);
console.log(JSON.stringify({ keys, open: after.all().filter((d) => d.open).map((d) => d.home.dataset.msg || "card") ,
  tail: after.c.all[after.c.all.length - 1].open }));
"""
)


def test_a_menu_open_across_a_reread_that_reorders_a_cards_items_reopens_on_its_own_item_or_not_at_all(tmp_path):
    out = run_probe(tmp_path, CARD_MENUS_PROBE)
    # the card's own ⋯ is keyed among the card's own menus, never counting its items'
    assert out["keys"] == [{"k": "msg", "v": "b", "i": 0, "f": 0}, {"k": "qid", "v": "s#TD-1", "i": 1, "f": 0}]
    # the card's ⋯ opens again; the left item's opens nowhere, and no other item's opens in its place
    assert out["open"] == ["card"] and out["tail"] is True
