"""The Focus Prompts card (design §4.5 *The Prompts card*, §4.5a *Focus side panel* **Prompts**, §4.6 *A jump
to a prompt*; TD-975, built by TD-977): the page's half — the rows and their senders, what a press sends,
one press pending at a time and its frame, and the Transcript's `?at=` seek. The bridge's half is
`test_pty_bridge_jump.py`."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from shiftlead.ui import help as helpmod
from shiftlead.ui.cards import view

pytestmark = pytest.mark.unit

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"

PROBE = r"""
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x", search: "" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const P = [
  { at: "2026-10-22T10:05:00Z", text: "yes", drawn: "❯ yes", whole: true, reply: "Done.\nmore", from: "person" },
  { at: "2026-10-22T10:04:00Z", text: "[pasted]", drawn: null, whole: false, reply: null, from: "s-1",
    from_name: "techlead" },
  { at: "2026-10-22T10:03:00Z", text: "the brief\nline two", drawn: "❯ the brief", whole: true, reply: null,
    from: "brief" },
  { at: "2026-10-22T10:02:00Z", text: "pause", drawn: "❯ pause", whole: false, reply: "ok", from: "system" },
];
// timers the test drives: `fire()` runs the pending timeout
const timers = () => {
  let f = null;
  return { set: (fn, ms) => { f = { fn, ms }; return 1; }, clear: () => { f = null; }, fire: () => f && f.fn(),
    get ms() { return f && f.ms; } };
};
(async () => {
  const out = {};
  out.senders = P.map(AO.promptSender).concat([AO.promptSender({ from: "s-9" })]);
  out.openings = [0, 1, 2, 3].map((i) => AO.jumpOpenings(P, i));
  // a press, then its frame; a second press while one waits is ignored; a frame with none pending dropped
  let sent = [], t = timers();
  let j = AO.jumper((ops) => { sent.push(ops); return true; }, t);
  const first = j.press([{ drawn: "❯ yes", whole: true }]);
  out.second = j.press([{ drawn: "❯ x", whole: true }]);
  out.wait = t.ms;
  j.frame({ jumped: true });
  out.landed = await first;
  j.frame({ jumped: false });
  out.sent = sent.length;
  // a miss frame; no frame in time; a socket that closed first; a socket not open
  const miss = j.press([]); j.frame({ jumped: false }); out.miss = await miss;
  const late = j.press([]); t.fire(); out.late = await late;
  const shut = j.press([]); j.closed(); out.shut = await shut;
  j = AO.jumper(() => false, timers()); out.unsent = await j.press([]);
  out.busy = j.busy();
  out.html = AO.promptsHtml(P, "ao x", new Set(["2026-10-22T10:04:00Z"]), false);
  out.gone = AO.promptsHtml(P.slice(0, 1), "ao x", new Set(), true);
  out.summary = AO.promptsSummary(P);
  out.none = AO.promptsSummary([]);
  // the Transcript's seek: found after two fetches; the file's start; fifty fetches; a failed fetch
  const seek = async (findAt, moreFn) => {
    let n = 0;
    const more = () => { n++; return Promise.resolve(moreFn(n)); };
    const r = await AO.transcriptSeek(() => (n >= findAt ? "el" : null), more);
    return { ...r, n };
  };
  out.found = await seek(2, () => true);
  out.start = await seek(99, (n) => (n >= 3 ? null : true));
  out.further = await seek(999, () => true);
  out.failed = await seek(99, () => false);
  console.log(JSON.stringify(out));
})();
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the card's logic is JavaScript, and nothing else runs it")
    probe = pathlib.Path(tempfile.mkdtemp()) / "prompts_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def got() -> dict:
    return _probe()


def test_the_sender_is_drawn_where_it_is_not_the_person(got):
    assert got["senders"] == ["", "techlead", "the brief", "the policy", "s-9"]


def test_a_press_sends_the_openings_from_the_newest_down_to_the_pressed_one(got):
    yes, brief, pause = (
        {"drawn": d, "whole": w} for d, w in (("❯ yes", True), ("❯ the brief", True), ("❯ pause", False))
    )
    assert got["openings"][0] == [yes]
    assert got["openings"][1] is None  # no drawn opening: a miss at the page, nothing sent
    assert got["openings"][2] == [yes, brief]  # the pasted one left out on the way
    assert got["openings"][3] == [yes, brief, pause]


def test_one_press_pending_and_its_frame(got):
    assert got["second"] is None and got["sent"] == 1  # a press while one waits is ignored
    assert got["wait"] == 7000  # JUMP_WITHIN and two seconds more
    assert got["landed"] is True
    assert got["miss"] is False and got["late"] is False and got["shut"] is False
    assert got["unsent"] is False and got["busy"] is False  # a socket not open: a miss at the page


def test_the_rows(got):
    html = got["html"]
    assert html.count('class="prbtn"') == 4 and 'data-i="3"' in html
    assert '<span class="prtext">yes</span>' in html and '<span class="prreply">Done.</span>' in html
    assert '<span class="prfrom">techlead</span>' in html and '<span class="prfrom">the brief</span>' in html
    assert '<span class="prtext">the brief</span>' in html  # the first line alone
    assert 'title="the brief\nline two"' in html  # the hover holds the opening
    # the missed row, and only it, says so with the Transcript at it, URL-encoded
    assert html.count("not in the terminal's history") == 1
    assert 'href="/transcript/ao%20x?at=2026-10-22T10%3A04%3A00Z" target="_blank" rel="noopener">Transcript</a>' in html
    gone = got["gone"]
    assert "disabled" in gone and "Transcript" in gone and "not in the terminal" not in gone
    assert got["summary"].startswith("4 · last ") and got["summary"].endswith(" ago")
    assert got["none"] == ""


def test_the_transcript_seek(got):
    assert got["found"] == {"found": "el", "n": 2}
    assert got["start"] == {"why": "start", "n": 3}
    assert got["further"] == {"why": "further", "n": 50}
    assert got["failed"] == {"why": "failed", "n": 1}


def test_the_frame_is_never_written_to_the_terminal():
    js = (UI / "static" / "app.js").read_text()
    focus = js[js.index("AO.focus = function") :]
    onmsg = focus[focus.index("ws.onmessage = (m) => {") :]
    frame = 'if (c && "jumped" in c) { jumper.frame(c); return; }'
    assert frame in onmsg and onmsg.index(frame) < onmsg.index("term.write(")
    # a socket that closes, a reattach, and the pane's end each resolve the pending press as a miss
    assert focus.count("jumper.closed();") == 3
    assert "ws.send(JSON.stringify({ jump: ops }))" in focus


def test_the_card_sits_between_working_and_git_folded():
    html = (UI / "templates" / "focus.html").read_text()
    card = html[html.index('data-side="prompts"') - 80 :]
    assert html.index('data-side="working"') < html.index('data-side="prompts"') < html.index('data-side="git"')
    tag = card[card.index("<details") : card.index(">", card.index("<details"))]
    assert " open" not in tag and "{% if s.agent %}" in html[html.index('data-side="prompts"') - 120 :][:120]
    assert "help_title('prompts')" in card[:600]


def test_the_view_names_each_prompts_sender():
    s = {
        "id": "a",
        "name": "w",
        "state": "idle",
        "prompts": [{"at": "t1", "from": "b"}, {"at": "t2", "from": "person"}],
    }
    v = view(s, [s, {"id": "b", "name": "techlead", "state": "idle"}])
    assert [p["from_name"] for p in v["prompts"]] == ["techlead", "person"]
    assert view({**s, "prompts": [{"at": "t", "from": "gone"}]}, [s])["prompts"][0]["from_name"] == "gone"


def test_the_help_carries_prompts_under_focus():
    h = {x.key: x for x in helpmod.HELP}["prompts"]
    assert h.name == "Prompts" and h.where == "Focus side panel"
    assert h.text.startswith("The prompts this conversation was sent, newest first")
    assert "prompts" in dict((g[0], g[2]) for g in helpmod.SCREENS)["focus"]
