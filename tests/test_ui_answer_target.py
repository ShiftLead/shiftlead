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
    classList: { contains: () => false, add: noop, remove: noop, toggle: noop }, setAttribute: noop, removeAttribute: noop,
    getAttribute: () => null, remove: noop, appendChild: noop, insertAdjacentHTML: noop, style: {},
    querySelectorAll: () => [], contains: () => false, focus: noop,
    previousElementSibling: { matches: (s) => s === ".qon", dataset: { on } } };
  r.closest = (sel) => (sel.includes(".boardrow") && kind === "board" ? r : sel === ".mailrow" ? r : null);
  const b = { dataset: data, classList: { contains: () => false }, parentElement: null };
  b.closest = (sel) => (sel === "[data-act], [data-copy]" ? b : sel === ".mailrow" ? r : sel.includes(".boardrow") && kind === "board" ? r : null);
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
const draw = () => {
  const board = row("board:k1", "board", "shiftlead#TD-1437", { act: "board_reply", id: "person", board: "docs/user_attention.md",
    key: "board:k1", line: "17", refs: "[]", name: "shiftlead's board", text: "Decide the end of TD-1437's rounds" });
  const ask = row("m-998", "ask", "shiftlead#TD-1529", { act: "reply", id: "person", msg: "m-998", from: "designer",
    name: "designer", quote: "td-max's shape?" });
  return { board, ask };
};
const out = {};
(async () => {
  // 1. Answer… on the board line; under the open box a re-read reorders the cards, and the pressed button is
  //    rewritten to carry the ask's data (the worst a swap could do): the words still go to the board line
  let p = draw(); live = { "board:k1": p.board, "m-998": p.ask };
  await press(p.board.button);
  out.title = ids["#mailtitle"].textContent;
  const fresh = draw(); live = { "m-998": fresh.ask, "board:k1": fresh.board };
  p.board.isConnected = false; p.ask.isConnected = false;
  p.board.button.dataset = { ...p.ask.button.dataset };
  if (observe) observe();
  ids["#mailtext"].value = "Hold: drop Dismiss";
  box.close("send"); await tick(); await tick();
  out.first = posts.splice(0);
  // 2. Answer… on the ask, with the board line drawn where it was: the words go back as the ask's reply
  p = draw(); live = { "board:k1": p.board, "m-998": p.ask };
  await press(p.ask.button);
  out.askTitle = ids["#mailtitle"].textContent;
  p.ask.button.dataset = { ...p.board.button.dataset };
  ids["#mailtext"].value = "go wide";
  box.close("send"); await tick(); await tick();
  out.second = posts.splice(0);
  // 3. a re-read that takes the item off the page closes the box: nothing is sent, the words are kept and come
  //    back when Answer… is pressed on the same item again
  p = draw(); live = { "board:k1": p.board, "m-998": p.ask };
  await press(p.ask.button);
  ids["#mailtext"].value = "words in flight";
  live = { "board:k1": draw().board };
  if (observe) observe();
  await tick();
  out.gone = { open: box.open, posts: posts.splice(0), toast: toasts[toasts.length - 1] || "" };
  ids["#mailtext"].value = "";
  p = draw(); live = { "m-998": p.ask };
  await press(p.ask.button);
  out.kept = ids["#mailtext"].value;
  box.close("cancel"); await tick();
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
    sent = out["first"][0]["body"]
    assert (sent["action"], sent["line"], sent["key"], sent["reply"]) == ("reply", 17, "board:k1", "Hold: drop Dismiss")
    # a mail item's Answer… is the ask's reply, whatever was drawn where it was
    assert out["second"] == [{"url": "/api/person/reply", "body": {"reply_to": "m-998", "text": "go wide"}}]


def test_a_reread_that_takes_the_item_away_closes_the_box_with_its_words_kept(tmp_path):
    out = run_probe(tmp_path, ANSWER_PROBE)
    assert out["gone"]["open"] is False and out["gone"]["posts"] == []
    assert out["gone"]["toast"].startswith("the item changed — your words are kept")
    assert out["kept"] == "words in flight"


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
  return { c, rows, all: () => c.all, querySelectorAll: (sel) => (sel === "details.more[open]" ? c.all.filter((d) => d.open) : []),
    querySelector: (sel) => homes.find((h) => Object.entries(h.dataset).some(([k, v]) => sel === `[data-${k}="${v}"]`)) || null };
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
