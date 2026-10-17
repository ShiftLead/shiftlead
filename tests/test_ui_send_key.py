"""The composer's send lands once (design §4.10 *A send lands once*, §4.5a *Focus composer* **Send**, TD-806,
built by TD-813): a press mints a key and holds the text it sent; the box keeps what was typed since; a verdict
ends the hold and an unknown one leaves it standing, so the next press repeats under the same key. The page's
rules run as themselves under node, as the composer bar's do."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile

import pytest

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"

PRELUDE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const docOn = {};  // the page's own document listeners: the press handler every data-act button goes through
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: (k, f) => { (docOn[k] = docOn[k] || []).push(f); }, createElement: el };
global.window = {}; global.document = document; global.Event = class { constructor(t) { this.type = t; } };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const cls = (init) => { const set = new Set(init); return { set, contains: (c) => set.has(c),
  add: (c) => set.add(c), remove: (c) => set.delete(c), toggle: (c, on) => (on ? set.add(c) : set.delete(c)) }; };
const stub = (extra) => { const on = {}; return Object.assign({ on, classList: cls([]), dataset: {},
  addEventListener: (k, f) => { on[k] = f; }, dispatchEvent: (e) => on[e.type] && on[e.type](e),
  focus: noop, click() { if (!this.disabled && on.click) return on.click({}); } }, extra); };
const tick = () => new Promise((r) => setImmediate(r));
"""

PROBE = (
    PRELUDE
    + """
function rig() {
  const posts = [], drafts = [], sents = [], fails = [];
  let n = 0, timer = null;
  const term = stub({ name: "term" });
  const composer = stub({ classList: cls(["overlay", "folded"]) });
  const compose = stub({ value: "", disabled: false, selectionStart: 0, selectionEnd: 0 });
  const text = stub({ textContent: "" }), send = stub({ disabled: false, textContent: "" });
  const sendBtn = stub({ textContent: "→ Send", disabled: false });
  const hint = { textContent: "starts a new turn" }, bar = stub({});
  const cb = AO.wireComposerBar({ bar, text, send, composer, compose, sendBtn, hint, term });
  const s = AO.wireComposerSend({
    sendBtn, compose, hint, redraw: cb.redraw,
    post: (body) => new Promise((ok, no) => posts.push({ body, ok, no })),
    draft: (v) => drafts.push(v), sent: (e) => sents.push(e), fail: (e) => fails.push(e.message),
    mint: () => `k${++n}`, later: (f) => { timer = f; return 1; }, cancel: () => { timer = null; },
  });
  const look = () => ({ label: sendBtn.textContent, disabled: sendBtn.disabled, bar: send.textContent,
    bar_disabled: send.disabled, hint: hint.textContent, value: compose.value });
  return { posts, drafts, sents, fails, compose, sendBtn, s, look, fire: () => timer && timer(), err: (m, st) =>
    Object.assign(new Error(m), { status: st }) };
}

(async () => {
  const out = {};
  // text typed after the press is kept, the draft rewritten from it, and the bar stays unfolded
  let r = rig();
  r.compose.value = "fix the race"; r.sendBtn.click();
  out.waiting = r.look();
  r.s.label("→ Steer");  // a view event during the hold
  out.view_event = r.look();
  r.compose.value = "fix the race\\nand then the test";
  r.posts[0].ok({ ok: true }); await tick();
  out.kept = { ...r.look(), key: r.posts[0].body.key, drafts: [...r.drafts], sents: [...r.sents] };
  out.label_after = r.sendBtn.textContent;  // the label the view set during the hold, now shown
  // all of it sent: the box empties, the draft goes, the bar folds
  r = rig(); r.compose.value = "one line"; r.sendBtn.click(); r.posts[0].ok({}); await tick();
  out.emptied = { value: r.compose.value, drafts: r.drafts, sents: r.sents };
  // a box edited at its start is left whole
  r = rig(); r.compose.value = "fix the race"; r.sendBtn.click();
  r.compose.value = "please fix the race"; r.posts[0].ok({}); await tick();
  out.edited = { value: r.compose.value, drafts: r.drafts, sents: r.sents };
  // a refusal ends the hold, leaves the box, and the next press mints a new key
  r = rig(); r.compose.value = "go"; r.sendBtn.click();
  r.posts[0].no(r.err("prompt-stuck: the composer did not empty", 400)); await tick();
  out.refused = { ...r.look(), fails: r.fails };
  r.sendBtn.click(); out.refused_next = r.posts.map((p) => p.body.key);
  // an unknown verdict leaves the hold standing: Send pressable, the hint, the same key
  out.unknown = {};
  for (const [name, e] of [["503", ["the host agent did not answer", 503]],
    ["dropped", ["the link to h dropped while send was out: its verdict is unknown — read the record", 400]],
    ["timeout", ["n1 did not answer send within 120 s: its verdict is unknown", 400]]]) {
    r = rig(); r.compose.value = "go"; r.sendBtn.click(); r.posts[0].no(r.err(...e)); await tick();
    const after = r.look();
    r.compose.value = "go\\nmore"; r.sendBtn.click();
    out.unknown[name] = { ...after, keys: r.posts.map((p) => p.body.key), texts: r.posts.map((p) => p.body.text) };
  }
  // a late answer for an earlier key changes nothing
  r = rig(); r.compose.value = "first"; r.sendBtn.click();
  r.fire();  // thirty seconds: no answer
  out.unconfirmed = r.look();
  r.s.label("→ Send"); out.unconfirmed_view = { hint: r.s.hint("starts a new turn"), label: r.sendBtn.textContent };
  // the view's newer hint, given during the hold, is the one its end restores
  { const q = rig(); q.compose.value = "a"; q.sendBtn.click(); q.fire(); q.s.hint("steers the turn in flight");
    q.posts[0].ok({}); await tick(); out.hint_after = q.look().hint; }
  r.compose.value = "other words"; r.sendBtn.click();
  r.posts[0].ok({}); await tick();
  out.late = { ...r.look(), sents: [...r.sents], keys: r.posts.map((p) => p.body.key) };
  r.posts[1].ok({}); await tick(); out.late_then = { value: r.compose.value, sents: r.sents };
  // after thirty seconds a repeat goes under the same key; its answer ends the hold
  r = rig(); r.compose.value = "once"; r.sendBtn.click(); r.fire(); r.sendBtn.click();
  out.repeat = { keys: r.posts.map((p) => p.body.key), texts: r.posts.map((p) => p.body.text), look: r.look() };
  r.posts[1].ok({}); await tick(); out.repeat_done = r.look();
  // a press while waiting does nothing; an empty box sends nothing
  r = rig(); r.compose.value = "x"; r.sendBtn.click(); r.s.press(); out.held_press = r.posts.length;
  r = rig(); r.compose.value = "  "; r.sendBtn.click(); out.blank = r.posts.length;
  const refusal = Object.assign(new Error("x"), { status: 400 });
  out.unknown_fn = { none: AO.sendUnknown(null), refusal: AO.sendUnknown(refusal) };
  out.mint = [AO.mintKey(), AO.mintKey()];
  // act's error carries the status, which tells an unknown verdict from a refusal
  global.fetch = async () => ({ ok: false, status: 503, statusText: "x", json: async () => ({ detail: "no answer" }) });
  try { await AO.act("ao-x", "send", {}); } catch (e) {
    out.act_err = { status: e.status, message: e.message, unknown: AO.sendUnknown(e) };
  }
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""
)


def _probe(source: str = PROBE) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the composer is JavaScript, and nothing else runs it")
    probe = pathlib.Path(tempfile.mkdtemp()) / "send_probe.js"
    probe.write_text(source)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def got():
    return _probe()


WAITING = {"label": "Sending…", "disabled": True, "bar": "Sending…", "bar_disabled": True}


@pytest.mark.unit
def test_a_send_that_waits_holds_both_sends_and_a_view_event_keeps_it(got):
    assert {k: got["waiting"][k] for k in WAITING} == WAITING
    assert got["waiting"]["value"] == "fix the race"  # the box stays editable and untouched
    assert {k: got["view_event"][k] for k in WAITING} == WAITING


@pytest.mark.unit
def test_text_typed_after_the_press_is_kept_and_the_draft_rewritten(got):
    k = got["kept"]
    assert k["value"] == "and then the test" and k["drafts"] == ["and then the test"]
    assert k["sents"] == [False]  # the box is not empty: the bar stays open
    assert k["key"] == "k1" and k["disabled"] is False and k["bar_disabled"] is False
    assert got["label_after"] == "→ Steer"
    assert got["emptied"] == {"value": "", "drafts": [""], "sents": [True]}  # the bar folds only now


@pytest.mark.unit
def test_a_box_edited_at_its_start_is_left_whole(got):
    assert got["edited"] == {"value": "please fix the race", "drafts": [], "sents": [False]}


@pytest.mark.unit
def test_a_refusal_ends_the_hold_and_the_next_press_is_a_new_send(got):
    r = got["refused"]
    assert r["value"] == "go" and r["disabled"] is False and r["label"] == "→ Send"
    assert r["fails"] == ["prompt-stuck: the composer did not empty"] and r["hint"] == "starts a new turn"
    assert got["refused_next"] == ["k1", "k2"]


@pytest.mark.unit
@pytest.mark.parametrize("how", ["503", "dropped", "timeout"])
def test_an_unknown_verdict_leaves_the_hold_and_the_next_press_reuses_its_key(got, how):
    u = got["unknown"][how]
    assert u["disabled"] is False and u["label"] == "→ Send" and u["hint"] == "not confirmed — Send repeats it safely"
    assert u["value"] == "go"
    assert u["keys"] == ["k1", "k1"] and u["texts"] == ["go", "go"]  # the held text, not the box's new words


@pytest.mark.unit
def test_after_thirty_seconds_send_is_pressable_and_repeats_under_the_same_key(got):
    u = got["unconfirmed"]
    assert u["disabled"] is False and u["bar_disabled"] is False and u["label"] == "→ Send"
    assert u["hint"] == "not confirmed — Send repeats it safely"
    assert got["unconfirmed_view"] == {"hint": "not confirmed — Send repeats it safely", "label": "→ Send"}
    assert got["hint_after"] == "steers the turn in flight"
    rp = got["repeat"]
    assert rp["keys"] == ["k1", "k1"] and rp["texts"] == ["once", "once"]
    assert {k: rp["look"][k] for k in WAITING} == WAITING
    assert got["repeat_done"]["value"] == "" and got["repeat_done"]["hint"] == "starts a new turn"


@pytest.mark.unit
def test_a_late_answer_for_an_earlier_key_changes_nothing(got):
    late = got["late"]
    assert late["keys"] == ["k1", "k2"]  # other words: a new send
    assert late["value"] == "other words" and late["sents"] == [] and late["disabled"] is True
    assert got["late_then"] == {"value": "", "sents": [True]}


@pytest.mark.unit
def test_one_press_one_send(got):
    assert got["held_press"] == 1 and got["blank"] == 0
    assert got["unknown_fn"] == {"none": False, "refusal": False}
    assert got["act_err"] == {"status": 503, "message": "no answer", "unknown": True}
    a, b = got["mint"]
    assert a != b and len(a) >= 32


PRESS_PROBE = (
    PRELUDE
    + """
(async () => {
  const out = {};
  // Wrap up goes through the page's one press handler: each press posts its own key (TD-806)
  const posts = [];
  global.fetch = async (url, init) => { posts.push({ url, body: JSON.parse(init.body) });
    return { ok: true, status: 200, json: async () => ({ ok: true }) }; };
  const button = { dataset: { act: "wrapup", id: "ao-x" }, classList: cls([]), closest: () => null };
  const press = docOn.click.find((f) => String(f).includes("[data-act], [data-copy]"));
  for (let i = 0; i < 2; i++) {
    try { await press({ target: { closest: () => button } }); } catch (_) { /* the toast's DOM is not here */ }
  }
  out.wrapup = posts;
  // a chip: its text and a key of its own, the chip held until the send answers
  const sends = [], fails = [];
  let shut = 0, done = 0;
  const chip = stub({ dataset: { text: "run the suite" }, disabled: false });
  const compose = stub({ value: "", disabled: false });
  AO.wireChip(chip, { compose, post: (body) => new Promise((ok, no) => sends.push({ body, ok, no })),
    sent: () => done++, closed: () => shut++, fail: (e) => fails.push(e.message) });
  chip.on.click({});
  out.held = chip.disabled;
  chip.on.click({});  // pressed again while the first is out: nothing goes
  out.while_out = sends.length;
  sends[0].ok({ ok: true }); await tick();
  out.released = chip.disabled;
  chip.on.click({}); sends[1].no(new Error("prompt-stuck")); await tick();
  out.chip = { bodies: sends.map((s) => s.body), done, fails, disabled: chip.disabled };
  chip.on.click({ shiftKey: true }); out.shift = { value: compose.value, sends: sends.length };
  compose.disabled = true; chip.on.click({}); out.closed = { shut, sends: sends.length };
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""
)


@pytest.fixture(scope="module")
def pressed():
    return _probe(PRESS_PROBE)


@pytest.mark.unit
def test_each_wrap_up_press_posts_a_key_of_its_own(pressed):
    """§4.5a **Wrap up** (TD-813 slice 2, TD-841): the page's press carries a key, one per press."""
    (a, b) = pressed["wrapup"]
    assert a["url"] == b["url"] == "/api/sessions/ao-x/wrapup"
    assert a["body"]["key"] and b["body"]["key"] and a["body"]["key"] != b["body"]["key"]


@pytest.mark.unit
def test_a_chip_press_sends_its_text_under_its_own_key_and_a_press_while_out_sends_nothing(pressed):
    """§4.5a *Focus composer* **prompt chips** (TD-170, TD-841): the chip is held while its send is out."""
    assert pressed["held"] is True and pressed["while_out"] == 1 and pressed["released"] is False
    first, second = pressed["chip"]["bodies"]
    assert first["text"] == second["text"] == "run the suite"
    assert first["key"] and second["key"] and first["key"] != second["key"]
    assert pressed["chip"] == {**pressed["chip"], "done": 1, "fails": ["prompt-stuck"], "disabled": False}
    assert pressed["shift"] == {"value": "run the suite", "sends": 2}  # Shift fills the box, sends nothing
    assert pressed["closed"] == {"shut": 1, "sends": 2}


@pytest.mark.unit
def test_the_wrapup_route_hands_the_key_to_send(tmp_path, monkeypatch):
    """The route carries the page's key to the host agent's `send`, so a repeat types the prompt once (TD-841)."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    from fastapi.testclient import TestClient

    from shiftlead.ui import app as ui

    calls: list = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            calls.append((method, kw))
            return {}

    monkeypatch.setattr(ui, "LocalClient", Fake)
    c = TestClient(ui.create_app())
    for _ in range(2):
        assert c.post("/api/sessions/ao-x/wrapup", json={"key": "k-1"}).json() == {"ok": True}
    sends = [kw for m, kw in calls if m == "send"]
    assert len(sends) == 2
    assert all(kw["wrapup"] is True and kw["key"] == "k-1" and kw["text"] == ui.WRAPUP_PROMPT for kw in sends)
