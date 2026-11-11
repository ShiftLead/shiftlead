"""The phone's Focus (design §4.5 *Phone layout*; §4.5a *the strip*, *the Watching line*, *the input bar · ⌨*,
*the sheet* and *the switcher*; TD-003, built by TD-1299): one screen that never scrolls — the strip, the terminal,
the key bar and the input bar — with everything else in sheets, the held link press, and the home-screen manifest."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from conftest import scratch_dir

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
QUERY = "(max-width: 720px), (pointer: coarse) and (max-height: 500px)"

pytestmark = pytest.mark.unit


def _page(tmp_path, monkeypatch, **rec) -> str:
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import templates, view

    base = {
        "id": "ao-x-phone-1", "name": "phone-1", "kind": "agent", "adapter": "claude-code", "dir": str(tmp_path),
        "state": "idle", "since": "2026-11-02T07:00:00Z", "confidence": "hook", "pane": True, "tail": [],
        "created": "2026-11-02T06:00:00Z",
    }  # fmt: skip
    others = [
        {"id": "ao-x-a", "name": "a", "state": "needs-you", "since": "2026-11-02T07:01:00Z", "dir": "/r/one",
         "pending": {"kind": "permission", "text": "Bash: git push"}},
        {"id": "ao-x-b", "name": "b", "state": "working", "since": "2026-11-02T07:02:00Z", "dir": "/r/two"},
    ]  # fmt: skip
    from shiftlead.ui import phone

    s = {**base, **rec}
    v = view(s)
    return templates.get_template("focus.html").render(
        s={**v, "grants_all": [], "ready": []},
        host="h",
        active="Sessions",
        popped=False,
        switch_rows=phone.switch_rows([s, *others], s["id"]),
    )


def _between(html: str, start: str, end: str) -> str:
    return html[html.index(start) : html.index(end, html.index(start))]


def _narrow(html: str) -> str:
    """What the phone's screen draws of Focus: the strip, the two bars and the sheets."""
    return "".join(
        [
            _between(html, 'id="fstrip"', "</div>"),
            _between(html, 'id="fwatch"', "</div>") if 'id="fwatch"' in html else "",
            _between(html, 'id="fibar"', "</div>") if 'id="fibar"' in html else "",
            _between(html, 'id="fscrim"', '<script src="/static/vendor/xterm.js">'),
        ]
    )


def _cls(html: str, eid: str) -> str:
    m = re.search(rf'<\w+[^>]*? class="([^"]*)"[^>]*? id="{eid}"', html)
    assert m, eid
    return m.group(1)


def test_the_narrow_template_draws_the_strip_the_bars_and_a_sheet_row_per_card(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    # the strip stands first in the main column, before the header's two lines it replaces
    assert html.index('id="fstrip"') < html.index('id="fhead"') < html.index('id="facts"')
    strip = _between(html, 'id="fstrip"', "\n    </div>")
    assert 'href="/"' in strip and 'id="fwho"' in strip and 'id="fneeds"' in strip and 'id="fmore"' in strip
    assert "phone-1" in strip and "idle" in strip
    # the input bar: the composer's words, and ⌨
    assert ">✎ Compose a prompt…</button>" in html and "hidden" not in _cls(html, "fkbd")
    assert "hidden" not in _cls(html, "fibar") and "hidden" in _cls(html, "fwatch")
    # the sheet: one row per card the record draws, in the panel's order, and Kill last
    sheet = _between(html, 'id="fsheet"', 'id="fcardsheet"')
    assert re.findall(r'data-card="(\w+)"', sheet) == [
        "working",
        "prompts",
        "git",
        "reports",
        "inbox",
        "sent",
        "ready",
        "session",
    ]
    for card in ("working", "prompts", "git", "reports", "inbox", "sent", "ready", "session"):
        assert f'data-side="{card}"' in html, card  # each row opens a card the side panel draws
    assert sheet.index('data-card="session"') < sheet.index('data-for="fkill"')
    acts = re.findall(r'data-for="(\w+)"', sheet)
    assert acts == [
        "fclose",
        "fmodeact",
        "fmessage",
        "fwrapup",
        "ftranscript",
        "fshell",
        "tpaste",
        "fmodemenu",
        "fkill",
    ]
    for src in acts:
        assert f'id="{src}"' in html, src  # each act presses the control the page already draws
    # nothing of the sheet is a control of its own: no Copy, copy on select, Pop out, VS Code or tmux command
    for word in ("Copy", "copy on select", "Pop out", "popout", "VS Code", "tmux attach", "data-copy"):
        assert word not in sheet, word
    # the switcher, seeded with every record
    rows = json.loads(re.search(r"data-rows='([^']*)'", html).group(1))
    assert [(r["name"], r["state"], r["here"]) for r in rows] == [
        ("phone-1", "idle", True),
        ("a", "needs-you", False),
        ("b", "working", False),
    ]
    assert rows[1]["sub"] == "Bash: git push" and rows[2]["sub"] == "two"


def test_a_record_with_no_agent_types_a_command_and_its_sheet_has_no_agent_acts(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch, kind="shell", adapter="shell", agent=False)
    assert ">Type a command…</button>" in html
    sheet = _between(html, 'id="fsheet"', 'id="fcardsheet"')
    for gone in ("fwrapup", "fmessage", "fmodeact", "fmodemenu"):
        assert f'data-for="{gone}"' not in sheet, gone
    assert re.findall(r'data-card="(\w+)"', sheet) == ["git", "session"]
    assert 'id="fwatch"' not in html


@pytest.mark.parametrize("held", [None, {"name": "Explore", "deadline": "2026-11-02T08:00:00Z"}])
def test_no_narrow_focus_draws_allow_or_deny_a_held_permission_included(tmp_path, monkeypatch, held):
    pend = {"kind": "permission", "text": "Bash: rm -rf build", "tool_use_id": "t1", "deadline": "2026-11-02T08:00:00Z"}
    html = _page(tmp_path, monkeypatch, state="needs-you", pending=pend, **({"held": held} if held else {}))
    narrow = _narrow(html)
    assert 'data-act="allow"' not in narrow and 'data-act="deny"' not in narrow and "denywhy" not in narrow
    # the identity line, where the desktop page draws them, is not drawn on the phone's screen
    css = (UI / "static" / "app.css").read_text()
    assert re.search(r"html\.phonefocus #side, html\.phonefocus #fhead, html\.phonefocus #facts,", css)


def test_an_unattended_record_draws_the_watching_line_and_message_with_no_keyboard(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch, unattended=True)
    watch = _between(html, 'id="fwatch"', "</div>")
    assert "hidden" not in _cls(html, "fwatch")
    assert "Watching. This session runs unattended." in watch and ">Take over</button>" in watch
    assert 'data-act="mode"' in watch and 'data-unattended="1"' in watch
    assert ">Message phone-1…</button>" in html and 'data-mode="message"' in html
    assert "hidden" in _cls(html, "fkbd")


@pytest.mark.parametrize("state", ["exited", "closed"])
def test_an_ended_record_draws_neither_bar(tmp_path, monkeypatch, state):
    html = _page(tmp_path, monkeypatch, state=state, unattended=True)
    assert "hidden" in _cls(html, "fwatch") and "hidden" in _cls(html, "fibar")


def test_a_scheduled_record_draws_neither_bar_nor_the_sheets_acts(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch, state="scheduled", start_at="2026-11-02T09:00:00Z")
    assert 'id="fwatch"' not in html and 'id="fibar"' not in html
    assert 'id="fsheetacts"' not in html and 'data-for="fkill"' not in html
    assert 'id="fstrip"' in html  # the strip is drawn: ‹, the switcher and ⋯ still work


def test_focus_carries_its_own_viewport_and_the_query_before_the_first_paint(tmp_path, monkeypatch):
    html = _page(tmp_path, monkeypatch)
    assert (
        '<meta name="viewport" content="width=device-width, initial-scale=1, '
        'interactive-widget=resizes-content, viewport-fit=cover">'
    ) in html
    head = html[: html.index("</head>")]
    assert f'matchMedia("{QUERY}")' in head and 'classList.add("phonefocus")' in head
    js = (UI / "static" / "app.js").read_text()
    assert f'AO.NARROW_Q = "{QUERY}";' in js
    css = (UI / "static" / "app.css").read_text()
    assert QUERY in css  # the stylesheet's `html.phonefocus` names the query it stands for
    # a popped-out window keeps the desktop page: no query read there
    src = (UI / "templates" / "focus.html").read_text()
    assert "{% if not popped %}<script>try { if (matchMedia(" in src
    # other pages keep base.html's
    base = (UI / "templates" / "base.html").read_text()
    assert "{% block viewport %}width=device-width, initial-scale=1, viewport-fit=cover{% endblock %}" in base
    # …and every page pads the insets the black-translucent status bar leaves it (env() is 0 on a desktop)
    css = (UI / "static" / "app.css").read_text()
    for rule in (
        "body { padding: 0 env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left); }",
        "body.popped { padding-top: env(safe-area-inset-top); }",
        ".topbar { border-top: env(safe-area-inset-top) solid var(--top); }",
        "html.phonefocus body { padding: 0; }",
    ):
        assert rule in css, rule


def test_the_home_screen_manifest_and_the_touch_icon():
    m = json.loads((UI / "static" / "manifest.webmanifest").read_text())
    assert m["display"] == "standalone" and m["start_url"] == "/" and m["scope"] == "/"
    assert m["name"] == "ShiftLead" and m["theme_color"]
    assert sorted(i["sizes"] for i in m["icons"]) == ["192x192", "512x512"]
    for i in m["icons"]:
        png = (UI / "static" / i["src"].removeprefix("/static/")).read_bytes()
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
        assert f"{w}x{h}" == i["sizes"]
    base = (UI / "templates" / "base.html").read_text()
    for tag in (
        '<link rel="manifest" href="/static/manifest.webmanifest">',
        '<link rel="apple-touch-icon" href="/static/icons/app-192.png">',
        '<meta name="apple-mobile-web-app-capable" content="yes">',
        '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">',
    ):
        assert tag in base, tag


def test_the_manifest_and_the_icon_are_served(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from fastapi.testclient import TestClient

    from shiftlead.ui.app import create_app

    with TestClient(create_app()) as c:
        r = c.get("/static/manifest.webmanifest")
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/manifest+json")
        assert r.json()["display"] == "standalone"
        r = c.get("/static/icons/app-192.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"


# -- the page's JavaScript, under node ----------------------------------------------------------------------------

PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, title: "", addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: el };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const opened = [];
window.open = (u) => opened.push(u);
// a scripted finger on the terminal: the TD-986 listeners' events, the clock in our hand
let clock = 0, narrow = true;
const hovers = [], leaves = [];
const touch = (x, y, id = 1) => ({ identifier: id, clientX: x, clientY: y });
const ev = (type, touches) => ({ type, targetTouches: touches, cancelable: true, prevented: false,
  preventDefault() { this.prevented = true; } });
function run(script, mode) {
  const rec = AO.linkPress();
  const el = { title: "" };
  const handler = AO.paneLinkHandler(el, rec);  // the OSC 8 reader: its own hover, the recorder inside
  const web = AO.webLinkOptions(rec);           // the web-links addon's options
  const press = AO.linkTouch(rec, { hover: (x, y) => hovers.push([x, y]), leave: () => leaves.push(1),
    narrow: () => narrow, now: () => clock, tracking: () => mode === "any" });
  const before = opened.length, ends = [];
  for (const step of script) {
    if (step.down) { clock = step.at || 0; press.start(ev("touchstart", [touch(...step.down)])); }
    if (step.two) press.start(ev("touchstart", [touch(0, 0), touch(5, 5, 2)]));
    if (step.move) press.move(ev("touchmove", [touch(...step.move)]));
    if (step.hover) (step.reader === "web" ? web : handler).hover({}, step.hover);
    if (step.leave) (step.reader === "web" ? web : handler).leave({}, step.leave);
    if (step.up != null) { clock = step.up; const e = ev("touchend", []); press.end(e); ends.push(e.prevented); }
  }
  return { opened: opened.slice(before), ends, title: el.title };
}
const url = "https://example.com/pr/1";
const out = {
  held: run([{ down: [10, 10] }, { hover: url }, { up: 500 }]),
  web: run([{ down: [10, 10] }, { hover: url, reader: "web" }, { up: 650 }]),
  soon: run([{ down: [10, 10] }, { hover: url }, { up: 499 }]),
  moved: run([{ down: [10, 10] }, { hover: url }, { move: [10, 20] }, { up: 600 }]),
  still: run([{ down: [10, 10] }, { hover: url }, { move: [15, 16] }, { up: 600 }]),
  second: run([{ down: [10, 10] }, { hover: url }, { two: true }, { up: 600 }]),
  nothing: run([{ down: [10, 10] }, { up: 900 }]),
  left: run([{ down: [10, 10] }, { hover: url }, { leave: url }, { up: 900 }]),
  file: run([{ down: [10, 10] }, { hover: "file:///etc/passwd" }, { up: 900 }]),
  mouse: run([{ hover: url }, { down: [10, 10] }, { up: 900 }]),
  hovers: hovers.length, leaves: leaves.length,
};
// a pane tracking every motion (DECSET 1003) would take the hover's mousemove as typing: no hover, no open; the
// button-only modes report no motion, so the press works there
const h0 = hovers.length;
out.any = run([{ down: [10, 10] }, { hover: url }, { up: 900 }], "any");
out.anyHovers = hovers.length - h0;
out.vt200 = run([{ down: [10, 10] }, { hover: url }, { up: 900 }], "vt200");
out.drag = run([{ down: [10, 10] }, { hover: url }, { up: 900 }], "drag");
narrow = false;
out.wideTap = run([{ down: [10, 10] }, { up: 100 }]);
// a press's event: a modifier, `AO.paneLink`'s first read
const seen = [];
const rec = AO.linkPress();
rec.down(0, 0, 0); rec.record({ uri: url, open: (e) => seen.push(e) });
const l = rec.up(700); l.open({ ctrlKey: true, metaKey: false, type: "touchend" });
out.event = seen[0];
out.latch = {
  typing: AO.narrowNext(false, true, false, true), typingNarrow: AO.narrowNext(true, false, false, true),
  read: AO.narrowNext(false, true, false, false), wide: AO.narrowNext(true, false, false, false),
  popped: AO.narrowNext(false, true, true, false),
};
const rows = [
  { id: "me", name: "me", state: "needs-you", since: "2026-11-02T07:00:00Z" },
  { id: "x", name: "x", state: "needs-you", since: "2026-11-02T07:05:00Z" },
  { id: "y", name: "y", state: "needs-you", since: "2026-11-02T07:01:00Z" },
  { id: "z", name: "z", state: "idle", since: "" }, { id: "w", name: "w", state: "stalled?", since: "" },
  { id: "c", name: "c", state: "closed", since: "" }, { id: "b", name: "b", state: "working", since: "" },
];
out.needs = AO.needsOf(rows, "me");
out.none = AO.needsOf([{ id: "me", state: "needs-you" }], "me");
out.groups = AO.switchGroups(rows).map((g) => [g.label, g.rows.map((r) => r.id)]);
console.log(JSON.stringify(out));
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the phone's rules are JavaScript, and nothing else runs them")
    probe = scratch_dir() / "phone_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_held_press_opens_the_recorded_link_on_the_lift_and_nothing_else_does():
    got = _probe()
    url = "https://example.com/pr/1"
    # held still 500 ms or more and lifted: the link a reader recorded, through `AO.paneLink`
    assert got["held"]["opened"] == [url] and got["web"]["opened"] == [url]
    assert got["held"]["title"] == url  # the OSC 8 reader's own hover still runs: one callback, the recorder inside
    # a lift sooner is a tap; 10 px of travel is a scroll, under it still a press; a second finger a pinch
    assert got["soon"]["opened"] == [] and got["moved"]["opened"] == [] and got["second"]["opened"] == []
    assert got["still"]["opened"] == [url]
    # nothing recorded (no reader answered, or it left) opens nothing; `AO.paneLink`'s gate refuses a non-http(s) one
    assert got["nothing"]["opened"] == [] and got["left"]["opened"] == [] and got["file"]["opened"] == []
    # a mouse's hover outside a held press records nothing
    assert got["mouse"]["opened"] == []
    # every lift on a phone has its default prevented: no emulated mouse event, so nothing focuses the terminal's
    # text box; on the desktop page a tap is left to the browser (it focuses the terminal, as before)
    for case in ("held", "soon", "moved", "nothing", "file"):
        assert got[case]["ends"] == [True], case
    assert got["wideTap"]["ends"] == [False]
    # at each press the page gave its point a hover, and each lift ended it
    assert got["hovers"] >= 10 and got["leaves"] >= 10
    assert got["event"] == {"ctrlKey": True, "metaKey": False, "type": "touchend"}


def test_a_pane_tracking_every_motion_gets_no_hover_and_opens_nothing():
    got = _probe()
    assert got["any"]["opened"] == [] and got["anyHovers"] == 0
    assert got["any"]["ends"] == [True]  # the lift still focuses nothing on a phone
    assert got["vt200"]["opened"] == ["https://example.com/pr/1"] and got["drag"]["opened"] == [
        "https://example.com/pr/1"
    ]
    js = (UI / "static" / "app.js").read_text()
    assert 'tracking: () => !!(term.modes && term.modes.mouseTrackingMode === "any"),' in js


def test_a_crossing_to_the_desktop_page_closes_the_sheet_with_its_hooks():
    js = (UI / "static" / "app.js").read_text()
    phone = js[js.index("AO.phoneFocus = function") :]
    relay = phone[phone.index("const relay = () => {") :]
    relay = relay[: relay.index("\n    };\n")]
    assert "if (!n) close();" in relay and "close(true)" not in relay
    # the composer's sheet folds the composer back in its `closed` hook
    assert "phone.closed((el) => { if (el !== composerEl) return; if (cbar && !cbar.folded()) cbar.fold();" in js


def test_the_query_is_latched_while_typing_and_a_popped_window_is_never_narrow():
    got = _probe()["latch"]
    assert got == {"typing": False, "typingNarrow": True, "read": True, "wide": False, "popped": False}


def test_the_strip_counts_the_others_that_need_you_and_the_switcher_keeps_the_sessions_order():
    got = _probe()
    assert got["needs"] == {"n": 2, "first": "y"}  # this one left out; the one that has waited longest
    assert got["none"] == {"n": 0, "first": None}
    assert got["groups"] == [
        ["Needs you", ["me", "x", "y"]],
        ["Working", ["b", "w"]],
        ["Idle", ["z"]],
        ["closed", ["c"]],
    ]


def test_focus_wires_the_screen_the_press_the_grid_and_the_reconnects():
    js = (UI / "static" / "app.js").read_text()
    focus = js[js.index("  AO.focus = function") :]
    focus = focus[: focus.index("\n  };\n")]
    # each reader is given the recorder: the OSC 8 handler, the web-links addon's options, the path provider
    assert 'linkHandler: AO.paneLinkHandler($("#term"), rec)' in focus
    assert "AO.webLinkOptions(rec)" in focus and "AO.pathProvider(term, id, s.editor, undefined, rec)" in focus
    provider = js[js.index("AO.pathProvider = function") :]
    provider = provider[: provider.index("\n  };\n")]
    assert "hover: () => rec.record(" in provider and "leave: () => rec.clear(" in provider
    # the press rides the TD-986 listeners; its hover is a mousemove on the screen element, never a button
    for part in ("press.start(e);", "press.move(e);", "press.end(e)", "press.cancel()"):
        assert part in focus, part
    assert 'new MouseEvent("mousemove", { clientX: x, clientY: y, bubbles: true })' in focus
    assert (
        '"mousedown"'
        not in focus[focus.index("const press = AO.linkTouch") : focus.index("const press = AO.linkTouch") + 900]
    )
    # no grid while a sheet is open, a refit when it closes; the terminal focused only off the phone
    assert "new ResizeObserver(() => { if (!phone.opened() && !pinch) fit.fit(); })" in focus  # nor mid-pinch (TD-1301)
    assert "phone.closed(() => fit.fit());" in focus and "toTerm();" in focus
    # the keyboard is the terminal's focus, read from xterm.js's helper text box
    assert 'term.textarea.addEventListener("focusin"' in focus and 'term.textarea.addEventListener("focusout"' in focus
    # fill() and the held bar leave the phone's screen alone
    assert 'document.body.classList.contains("popped") || phone.narrow()' in focus
    assert "if (!phone.matches || AO.isNarrow()) return;" in js
    # the terminal and the stream reconnect on visibilitychange and online
    assert (
        focus.count('addEventListener("visibilitychange", revive)') == 1
        and 'addEventListener("online", revive)' in focus
    )
    events = js[js.index("function connectEvents(") :]
    events = events[: events.index("AO.connectEvents = connectEvents")]
    assert 'addEventListener("visibilitychange", revive)' in events and 'addEventListener("online", revive)' in events
    # the disconnected banner opens with *is Tailscale on?*
    assert '"Is Tailscale on? Disconnected — reconnecting"' in js


def test_the_stylesheet_pins_one_screen_and_draws_the_bars_on_a_phone_only():
    css = (UI / "static" / "app.css").read_text()
    assert ".fstrip, .fwatch, .fibar, .nsheet, .nscrim, .csheethead { display: none; }" in css
    screen = css[css.index("html.phonefocus .page.focus {") :]
    screen = screen[: screen.index("}")]
    assert "position: fixed;" in screen and "height: var(--vvh, 100dvh);" in screen and "overflow: hidden;" in screen
    assert "env(safe-area-inset-top)" in screen
    assert "html.phonefocus, html.phonefocus body { height: 100%; overflow: hidden;" in css
    assert "html.phonefocus .topbar { display: none; }" in css
    # the terminal takes the column: no 360 px floor, no fixed height
    assert (
        "html.phonefocus .termwrap .termbox, html.phonefocus .termwrap.cfold .termbox"
        " { flex: 1; min-height: 0; height: auto;" in css
    )
    assert "user-select: none; -webkit-user-select: none; -webkit-touch-callout: none;" in css
    assert "html.phonefocus .termbox .xterm-helper-textarea { font-size: var(--t-field); }" in css
    assert "--t-field: 16px;" in css.split(":root {", 1)[1].split("}", 1)[0]
    assert "html.phonefocus .page.focus.kbdup .fibar { display: none; }" in css
    assert "overscroll-behavior: contain;" in css[css.index("html.phonefocus .nsheet.open {") :][:600]
    # the old narrow Focus is gone: no half-height terminal, no static composer under it
    assert ".termbox { height: 50vh; }" not in css and ".termwrap.cfold .termbox { height: 50vh; }" not in css
    assert "position: static; display: flex; box-shadow: none; max-height: none;" not in css


def test_take_over_and_hand_back_share_the_acts_lines_slot_and_switch_to_unattended_is_more_s(tmp_path, monkeypatch):
    """TD-1408 (TD-964's slice 4, design §4.5a *Focus: Take over*, *more ▾*): Take over on an unattended session and
    Hand back on a held member stand in the acts line's one slot — Hand back a bordered plain `btn sm`, never the
    outlined `next` — with more ▾'s toggle hidden; on an interactive session with no team and no controllers the
    slot is empty and *Switch to unattended* is more ▾'s alone."""

    def slot(html: str) -> tuple[str, str, bool]:
        act = re.search(r'<button class="([^"]*)" id="fmodeact"[^>]*>([^<]*)</button>', html, re.S)
        menu = re.search(r'<button id="fmodemenu"[^>]*?( hidden)?\s+title="[^"]*">([^<]*)</button>', html, re.S)
        assert act and menu
        assert act.group(2) == menu.group(2)  # both read `mode_act`
        return act.group(1), act.group(2), not menu.group(1)

    cls, word, in_menu = slot(_page(tmp_path, monkeypatch, unattended=True))
    # outlined, or plain beside an outlined Close session while the checklist passes (§4.5 *The card's anatomy*)
    assert (word, in_menu) == ("Take over", False) and cls.split() in (["btn", "sm", "next"], ["btn", "sm", "link"])
    for held in ({"team": "t"}, {"controllers": ["ao-x-m"]}):
        cls, word, in_menu = slot(_page(tmp_path, monkeypatch, unattended=False, **held))
        assert (word, in_menu) == ("Hand back", False) and cls.split() == ["btn", "sm"], held
    cls, word, in_menu = slot(_page(tmp_path, monkeypatch, unattended=False))
    assert (word, in_menu) == ("Switch to unattended", True) and "hidden" in cls.split()
    for ended in ("exited", "closed"):  # an ended record draws the toggle nowhere
        for mode in ({"unattended": True}, {"unattended": False, "team": "t"}, {"unattended": False}):
            cls, word, in_menu = slot(_page(tmp_path, monkeypatch, state=ended, **mode))
            assert "hidden" in cls.split() and not in_menu, (ended, mode)


def test_take_over_on_a_member_confirms_wherever_it_is_drawn_and_hand_back_never_does(tmp_path, monkeypatch):
    """TD-1440 (design §4.5 *A taken-over member*, §4.5a *Focus: Take over*): on a member — a team or controllers,
    not the person's own — the acts line's Take over, the Watching line's and the card's more ▾ *Switch to
    interactive* carry the confirm; a non-member's and the person's own team session's are one press; Hand back
    never confirms. The narrow sheet's entry is a proxy that clicks `#fmodeact`, so the confirm runs once."""
    from shiftlead.ui.app import templates, view

    text = (
        "Take over phone-1? While you hold it, its mail does not wake it, and asks to it wait for you. "
        "Hand back returns it."
    )

    def confirms(html: str) -> dict[str, str | None]:
        out = {}
        for eid in ("fmodeact", "fwatchgo"):
            tag = re.search(rf'<button[^>]*id="{eid}"[^>]*>', html, re.S) or re.search(
                rf'<button[^>]*data-unattended="1"[^>]*id="{eid}">', html, re.S
            )
            assert tag, eid
            got = re.search(r'data-confirm="([^"]*)"', tag.group(0))
            out[eid] = got.group(1) if got else None
        return out

    for member in ({"team": "t"}, {"controllers": ["ao-x-m"]}):
        assert confirms(_page(tmp_path, monkeypatch, unattended=True, **member)) == {
            "fmodeact": text,
            "fwatchgo": text,
        }, member
        assert confirms(_page(tmp_path, monkeypatch, unattended=False, **member)) == {
            "fmodeact": None,
            "fwatchgo": None,
        }, "Hand back never confirms"
    for one in ({}, {"team": "t", "by_person": True}):
        assert confirms(_page(tmp_path, monkeypatch, unattended=True, **one)) == {"fmodeact": None, "fwatchgo": None}
    # the narrow sheet's Take over carries no data-act of its own: a press clicks #fmodeact, whose confirm runs once
    sheet = re.search(r'<button[^>]*data-for="fmodeact"[^>]*>', _page(tmp_path, monkeypatch, unattended=True, team="t"))
    assert sheet and "data-act" not in sheet.group(0) and "data-confirm" not in sheet.group(0)

    def card(**rec) -> str | None:
        s = {"id": "ao-x-c", "name": "c", "kind": "agent", "state": "idle", "dir": str(tmp_path), **rec}
        html = templates.get_template("card.html").render(s=view(s))
        tag = re.search(r'<button data-act="mode" data-via="card"[^>]*>', html)
        assert tag, rec
        got = re.search(r'data-confirm="([^"]*)"', tag.group(0))
        return got.group(1) if got else None

    assert card(unattended=True, team="t").startswith("Take over c? While you hold it")
    assert card(unattended=False, team="t") is None and card(unattended=True) is None
    assert view({"id": "x", "state": "idle", "unattended": True, "team": "t", "agent": False})["mode_confirm"] == ""


def test_the_focus_delta_sets_and_clears_take_overs_confirm():
    """TD-1440: app.js's Focus delta handler follows `mode_confirm` onto `#fmodeact` and `#fwatchgo`, so a
    membership change while Focus is open is followed, and the generic confirm check runs before the mode branch."""
    js = (pathlib.Path(__file__).parent.parent / "src/shiftlead/ui/static/app.js").read_text(encoding="utf-8")
    assert 'for (const el of [ma, $("#fwatchgo")]) {' in js
    assert "if (v.mode_confirm) el.dataset.confirm = v.mode_confirm; else delete el.dataset.confirm;" in js
    click = js.index("if (b.dataset.confirm && !confirm(b.dataset.confirm)) return;")
    assert click < js.index('if (action === "mode") body = {', click)


# -- TD-1494: Resume on a member confirms too (§4.5 *Resume on a member confirms too*, §4.5a *Focus (exited /
# closed)*, *Inbox row: restart*, *Inbox row: state*) ---------------------------------------------------------

RESUME_TEXT = (
    "Resume w attended? While you hold it, its mail does not wake it, and asks to it wait for you. Hand back returns "
    "it. To resume it unattended, cancel and use Resume with changes… on its page, with Unattended ticked."
)


def _ended(**kw) -> dict:
    s = {"id": "ao-x-w", "name": "w", "kind": "agent", "adapter": "claude-code", "dir": "/w", "repo": "/w",
         "state": "exited", "pane": False, "tail": [], "since": "2026-11-06T10:00:00Z", "confidence": "hook",
         "adapter_id": "sess-1"}  # fmt: skip
    s.update(kw)
    return s


def test_resume_confirm_is_set_on_an_ended_member_whatever_mode_it_ended_in(tmp_path, monkeypatch):
    """TD-1494: `resume_confirm` on an exited or closed agent record holding a tool session id that is a member — a
    team or controllers, not the person's own — whether it ended unattended or interactive; `member_hold` is the
    shared sentences alone there, the one constant Take over's confirm reads too. Empty on everything else."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import view
    from shiftlead.ui.cards import MEMBER_HOLD

    assert MEMBER_HOLD in RESUME_TEXT
    for member in ({"team": "t"}, {"controllers": ["ao-x-m"]}):
        for mode in (True, False):
            for state in ("exited", "closed"):
                v = view(_ended(unattended=mode, state=state, **member))
                assert v["resume_confirm"] == RESUME_TEXT, (member, mode, state)
                assert v["member_hold"] == MEMBER_HOLD
    # a seat gets the member text and nothing more
    assert view(_ended(team="t", seat={"trigger": "asks"}))["resume_confirm"] == RESUME_TEXT
    # the name, else the id
    assert view(_ended(team="t", name=""))["resume_confirm"].startswith("Resume ao-x-w attended? ")
    for other in (
        {"team": "t", "by_person": True},  # the person's own
        {},  # not a member
        {"team": "t", "adapter_id": ""},  # no tool session id: lands on the form unasked
        {"team": "t", "agent": False},  # a record with no agent
        {"team": "t", "state": "idle", "pane": True},  # a live record (the restart row can stand on one)
    ):
        v = view(_ended(**other))
        assert v["resume_confirm"] == "" and v["member_hold"] == "", other
    # Take over's confirm reads the same constant (TD-1440), so the sites cannot drift
    assert view(_ended(team="t", state="idle", unattended=True))["mode_confirm"] == f"Take over w? {MEMBER_HOLD}"


def test_a_member_resumed_unsupervised_keeps_hand_back_and_is_not_woken_by_mail(tmp_path, monkeypatch):
    """TD-1494: a member the person resumed (attended, `by_person` after) still offers Hand back on its card, and
    while interactive its mail does not wake it — which is what the confirm says. A member a lead started unsupervised
    carries the lead in `controllers` from its create (§4.8), which is what keeps Hand back once it reads `by_person`
    (TD-1681: a team alone, with `by_person`, is the person's own start)."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from sessionorc.mail import mail_wakes
    from sessionorc.models import Session
    from shiftlead.ui.app import view

    v = view(_ended(team="t", controllers=["ao-x-lead"], state="idle", pane=True, unattended=False, by_person=True))
    assert v["mode_act"] == "Hand back" and v["resume_confirm"] == ""
    s = Session(id="ao-x-w", name="w", kind="interactive", adapter="claude-code", dir="/w", state="idle")  # type: ignore[arg-type]
    s.unattended = False
    assert mail_wakes(s) is False


def test_the_ending_banners_resume_carries_the_confirm_through_esc_and_restart_none():
    """TD-1494: the ending banner's Resume sets `data-confirm` from `v.resume_confirm`, escaped, on every render (the
    banner is rebuilt from the view, so a cleared field drops it); Resume with changes…, New session here, Forget and
    Restart carry none of it. The page's one generic `data-confirm` check stands before the resume branch, so a press
    asks first and Cancel sends no create — never a per-`data-act` confirm, since the paused steer's Resume shares
    `data-act="resume"` and stays one press."""
    js = (UI / "static" / "app.js").read_text(encoding="utf-8")
    line = (
        '`<button class="btn sm primary" data-act="resume" data-id="${id}"'
        '${v.resume_confirm ? ` data-confirm="${esc(v.resume_confirm)}"` : ""}>Resume</button> `'
    )
    assert line in js
    banner = js[js.index('const ex = $("#fexited");') : js.index("drawEnd(v);", js.index('const ex = $("#fexited");'))]
    assert line in banner
    restart = banner[banner.index('data-act="restart"') :]
    assert "resume_confirm" not in restart and "member_hold" not in restart
    click = js.index("if (b.dataset.confirm && !confirm(b.dataset.confirm)) return;")
    assert click < js.index('if (action === "resume" || action === "reopen-push") {', click)
    assert js.count("if (b.dataset.confirm && !confirm(b.dataset.confirm)) return;") == 1
    # the esc the banner's line calls escapes a quote, so a name with one cannot end the attribute
    assert """'"': "&quot;\"""" in js[js.index("function esc(t)") :][:200]


def test_the_inbox_restart_and_unpushed_rows_resume_confirms_on_a_member(tmp_path, monkeypatch):
    """TD-1494 (§4.5a *Inbox row: restart*, *Inbox row: state*): the restart row's Resume and the unpushed state row's
    Resume carry the card view's `resume_confirm`, and its Reopen and push its own confirm with `member_hold` after a
    space — on a closed member and a controllers-only one too; on a non-member each is as before. Restart carries
    none. A name with a quote in it is escaped by Jinja."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import state_rows, templates, view
    from shiftlead.ui.cards import MEMBER_HOLD

    git = {"ahead": 3, "dirty": 0, "upstream": "origin/main", "unpushed": 3, "pushed_against": "origin/main"}
    ceiling = {"at": "2026-11-06T11:00:00Z", "count": 3}

    def rows_of(**kw) -> dict[str, dict]:
        r = _ended(git=git, exit_code=1, restart_ceiling=ceiling, **kw)
        return {e["row"]: e for e in state_rows([view(r, [r])])}

    def confirm(html: str, act: str) -> str | None:
        tag = re.search(rf'<button[^>]*data-act="{act}"[^>]*>', html)
        assert tag, act
        got = re.search(r'data-confirm="([^"]*)"', tag.group(0))
        return got.group(1) if got else None

    def render(e: dict) -> str:
        return templates.get_template("inbox_rows.html").render(rows=[e], section="needs")

    reopen = (
        "Reopen w under its own name and ask it to push? It resumes the conversation, attended, with one prompt this "
        "page wrote — push the branch, open or update the PR, then report the outcome."
    )
    cases = (({"team": "t"}, "exited"), ({"team": "t"}, "closed"), ({"controllers": ["ao-x-m"]}, "exited"))
    for member, state in cases:
        by = rows_of(state=state, **member)
        assert {"restart", "unpushed"} <= set(by) or state == "closed", (member, state, sorted(by))
        restart = render(by["restart"])
        assert confirm(restart, "resume") == RESUME_TEXT, (member, state)
        if "restart" in restart and 'data-act="restart"' in restart:
            assert confirm(restart, "restart") is None
        if "unpushed" in by:
            un = render(by["unpushed"])
            assert confirm(un, "resume") == RESUME_TEXT
            assert confirm(un, "reopen-push") == f"{reopen} {MEMBER_HOLD}"
    # a closed member's unpushed row, built straight from its view (state_kind reads `exited` alone today)
    v = view(_ended(state="closed", team="t"))
    un = render({"row": "unpushed", "id": "ao-x-w:unpushed", "sid": "ao-x-w", "name": "w", "text": "3 unpushed",
                 "resume_confirm": v["resume_confirm"], "member_hold": v["member_hold"]})  # fmt: skip
    assert confirm(un, "resume") == RESUME_TEXT and confirm(un, "reopen-push") == f"{reopen} {MEMBER_HOLD}"
    # a non-member: one press, and Reopen and push's own text unchanged
    by = rows_of()
    assert confirm(render(by["restart"]), "resume") is None
    assert confirm(render(by["unpushed"]), "resume") is None
    assert confirm(render(by["unpushed"]), "reopen-push") == reopen
    # a name with a quote is escaped in the attribute
    by = rows_of(team="t", name='w"x')
    assert 'data-confirm="Resume w&#34;x attended? ' in render(by["restart"]) or (
        'data-confirm="Resume w&quot;x attended? ' in render(by["restart"])
    )
