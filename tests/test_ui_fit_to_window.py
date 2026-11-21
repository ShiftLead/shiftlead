"""**Fit to window**, the whole control on the wide layout and a Pop out (design §4.6 *Fit to window: the person
resizes on demand*, §4.5a **Fit to window**, TD-1948): it waits for a quiet pane (a record with no agent fits at once),
reads Cancel fit while it waits, ends after five minutes, checks the bridge's bounds at the press and at the send,
is held while the page is hidden, and on the wide layout's own Focus writes the grid as `person.terminal.grid` once the
bridge's `grid` frame on that socket answers. The page's rules run as themselves under node; the wiring is read from
the page's source."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"
APP = UI / "static" / "app.js"

PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [], contains: () => false });
const document = { documentElement: el(), body: el(), querySelector: () => null, querySelectorAll: () => [],
  addEventListener: noop, createElement: () => el() };
global.window = {}; global.document = document;
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const idle = { state: "idle", own_work: "" };
const base = { v: idle, lastByte: 0, now: 10000, hidden: false, box: [100, 30], pane: [120, 40] };
const step = (o, since) => AO.fitStep({ since: since == null ? 9000 : since }, { ...base, ...o });
console.log(JSON.stringify({
  quiet: step({}),
  byte_recent: step({ lastByte: 8500 }),
  byte_two_seconds: step({ lastByte: 8000 }),
  no_byte_yet: step({ lastByte: null }),
  working: step({ v: { state: "working" } }),
  waiting: step({ v: { state: "waiting" } }),
  limited: step({ v: { state: "limited" } }),
  own_work: step({ v: { state: "idle", own_work: "1 agent running" } }),
  no_agent_busy: step({ v: { state: "working", agent: false }, lastByte: 9999 }),
  hidden: step({ hidden: true }),
  no_box: step({ box: null }),
  became_pane: step({ box: [120, 40] }),
  too_small: step({ box: [19, 30] }),
  too_large: step({ box: [100, 201] }),
  limit: step({ v: { state: "working" } }, 10000 - 300000),
  limit_hidden: step({ hidden: true }, 10000 - 300000),
  before_limit: step({ v: { state: "working" } }, 10000 - 299999),
  refused: [AO.fitRefused([100, 30]), AO.fitRefused([20, 4]), AO.fitRefused([501, 40]), AO.fitRefused(null)],
  title: AO.fitTitle([120, 40], [98, 31]),
  pinch: [AO.pinchSays(13, [46, 30], 120), AO.pinchSays(13, null, 120)],
  bounds: [AO.FIT_QUIET, AO.FIT_LIMIT, AO.FIT_ANSWER],
  hold: (() => {
    // the hold's moments, in order: `[ev, now, height, editing, scale]`; each list is one press
    const run = (focused, moments) => {
      const h = AO.holdStart(0, focused, 500, 1);
      return moments.map(([ev, now, height, editing, scale]) =>
        AO.holdStep(h, { ev, now, height, editing: !!editing, scale: scale == null ? 1 : scale }).do);
    };
    return {
      // nothing focused: 100 ms of a steady height from the press keeps the box
      quiet: run(false, [["frame", 50, 500], ["frame", 99, 500], ["frame", 100, 500]]),
      // a height that moves counts the 100 ms again from its last change
      moving: run(false, [["frame", 50, 520], ["frame", 140, 520], ["frame", 150, 520]]),
      // a field focused at the press: nothing until the keyboard's fall (the first resize), then 100 ms from it
      fell: run(true, [["frame", 300, 300], ["resize", 400, 300], ["frame", 450, 640], ["frame", 549, 640],
        ["frame", 550, 640]]),
      // no resize within a second, and nothing focused by then: the box as it is
      no_resize: run(true, [["frame", 999, 300], ["frame", 1000, 300]]),
      // no resize within a second and a field focused: the fallback
      no_resize_focused: run(true, [["frame", 1000, 300, true]]),
      // a zoom's resize (another scale) is never the keyboard's fall
      zoom: run(true, [["resize", 200, 300, false, 2], ["frame", 400, 300], ["frame", 1000, 300]]),
      // the hold's own limit, a second from that resize: still moving, or a field focused, takes the fallback
      hold_limit: run(true, [["resize", 300, 300], ["frame", 1299, 301], ["frame", 1300, 302]]),
      hold_focused: run(false, [["frame", 500, 500, true], ["frame", 1000, 500, true]]),
      limits: [AO.HOLD_STEADY, AO.HOLD_LIMIT],
      notes: [AO.FIT_TURNED, AO.FIT_NO_BOX],
    };
  })(),
}));
"""


def _probe(tmp_path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the rule is JavaScript, and nothing else runs it")
    probe = tmp_path / "fit_probe.js"
    probe.write_text(PROBE)
    run = subprocess.run([node, str(probe), str(APP)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.unit
def test_a_fit_waits_for_a_quiet_pane_and_sends_the_box_then(tmp_path):
    got = _probe(tmp_path)
    send = {"do": "send", "grid": [100, 30]}
    wait = {"do": "wait"}
    assert got["quiet"] == send and got["no_byte_yet"] == send and got["byte_two_seconds"] == send
    assert got["byte_recent"] == wait  # a pane byte within two seconds
    # only `idle` with nothing of its own running is quiet: any other state waits as a busy one does
    assert [got[k] for k in ("working", "waiting", "limited", "own_work")] == [wait] * 4
    assert got["no_agent_busy"] == send  # a record with no agent fits at once


@pytest.mark.unit
def test_a_fit_is_held_ends_quietly_or_says_why(tmp_path):
    got = _probe(tmp_path)
    assert got["hidden"] == {"do": "wait"} and got["no_box"] == {"do": "wait"}  # held, the five minutes counting
    assert got["became_pane"] == {"do": "end", "note": None}  # another browser's fit: quietly
    assert got["too_small"] == {"do": "end", "note": "not fitted — this box is too small"}
    assert got["too_large"] == {"do": "end", "note": "not fitted — this box is too large"}
    busy = {"do": "end", "note": "not fitted — the session stayed busy"}
    assert got["limit"] == busy and got["limit_hidden"] == busy and got["before_limit"] == {"do": "wait"}
    assert got["refused"] == [
        None, "not fitted — this box is too small", "not fitted — this box is too large", None,
    ]  # fmt: skip
    assert got["bounds"] == [2000, 300000, 10000]


@pytest.mark.unit
def test_its_title_and_the_pinchs_note_read_the_box_and_the_pane(tmp_path):
    got = _probe(tmp_path)
    assert got["title"] == (
        "give the pane this window's size (pane 120 × 40, window 98 × 31) — waits until the session is idle;"
        " a smaller size can repeat or drop the last lines of the history"
    )  # §4.5a's own words
    assert got["pinch"] == ["13 px · 46 of 120 columns", "13 px · 120 columns"]


def _focus() -> str:
    js = APP.read_text()
    focus = js[js.index("  AO.focus = function") :]
    return focus[focus.index('    const fitEl = $("#tfit");') : focus.index('    compose.addEventListener("input"')]


@pytest.mark.unit
def test_the_press_waits_cancels_and_folds_the_menu():
    fit = _focus()
    press = fit[fit.index('fitEl.addEventListener("click"') :]
    # the menu folds; a press while it waits is Cancel fit, which measures nothing
    assert (
        press.index("more.open = false")
        < press.index("if (fitHold) return;")
        < press.index("if (fitWait) { fitEnd(); return; }")
        < press.index("if (phone.narrow() || coarse()) { holdBegin(); return; }")
        < press.index("fitPress(AO.boxGrid());")
    )
    # the press checks the equal grid and the bounds before any wait
    measured = fit[fit.index("function fitPress(g, px)") :]
    assert measured.index('AO.toast("already this size", true)') < measured.index("fitWait = { since: Date.now(), px")
    assert measured.index("AO.fitRefused(g)") < measured.index("fitWait = { since: Date.now(), px")
    # the mark stands for it; no pending mark, no disabled or aria-busy on it
    assert "mk.fitting = true; drawMark(); drawFit();" in measured
    assert "disabled" not in fit and "aria-busy" not in fit and "markPending" not in fit
    assert 'fitEl.textContent = fitWait ? "Cancel fit" : fitLabel;' in fit
    # drawn while it waits whatever the box says; otherwise not on an ended record nor at the pane's grid
    assert "!fitWait && (paneGone" in fit and "(!phone.narrow() && (!g || AO.sameGrid(g, pane)))" in fit
    assert "readOnly" not in fit  # drawn on a read-only Focus: it types nothing


@pytest.mark.unit
def test_the_send_and_the_setting_written_on_the_bridges_answer():
    fit = _focus()
    # each moment of the wait is `AO.fitStep`, read each quarter second, on a `grid` frame and on visibility
    assert "fitTick = setInterval(fitRun, 250);" in fit
    assert 'document.addEventListener("visibilitychange", () => { if (fitHold) holdTick("frame"); fitRun(); });' in fit
    run = fit[fit.index("function fitRun()") : fit.index("function fitAnswered(")]
    assert "hidden: document.hidden" in run and "lastByte: mk.lastByte" in run
    assert "ws.send(JSON.stringify({ fit: step.grid }));" in run
    # the setting is the wide layout's own Focus's: never a phone's or a Pop out's
    assert 'const fitOwn = () => !phone.narrow() && !popped && !document.body.classList.contains("popped");' in fit
    assert run.index("if (fitOwn())") < run.index("AO.FIT_ANSWER")
    assert 'AO.toast("not fitted")' in run  # no answer within ten seconds: nothing written
    answered = fit[fit.index("function fitAnswered(") : fit.index("    if (fitEl) {")]
    # the first frame on that socket equal to the grid sent
    assert "fitAnswer.ws !== sock || !AO.sameGrid(grid, fitAnswer.grid)" in answered
    assert "body: JSON.stringify({ terminal: { grid } })," in answered
    assert "fitted, but not kept for later sessions" in answered  # a refused write leaves the fit


@pytest.mark.unit
def test_the_socket_and_the_grid_frame_reach_the_fit():
    js = APP.read_text()
    focus = js[js.index("  AO.focus = function") :]
    assert "keeper.release(); relayout(); drawFit();\n              fitAnswered([gc, gr], sock);" in focus
    assert "const sock = ws;" in focus  # the frame's own socket, never a later attach's
    close = focus[focus.index("      ws.onclose = (e) => {") :]
    assert close.index("if (fitWait) fitEnd();") < close.index("if (paneGone) return;")  # a closed socket cancels
    ended = focus[focus.index("    function endTerm(text) {") :]
    assert ended.index("if (fitWait) fitEnd();") < ended.index("function openTerm()")
    reattach = focus[focus.index("    function reattach() {") :]
    assert reattach.index("if (fitWait) fitEnd();") < reattach.index("openTerm();")  # a mode change's new attach


@pytest.mark.unit
def test_a_pop_out_draws_fit_to_window():
    html = (UI / "templates" / "focus.html").read_text()
    line = next(x for x in html.splitlines() if 'id="tfit"' in x)
    assert "{% if not popped %}" not in line and "⤢ Fit to window" in line


@pytest.mark.unit
def test_the_press_hold_keeps_the_box_once_the_keyboard_has_fallen(tmp_path):
    got = _probe(tmp_path)["hold"]
    assert got["quiet"] == ["wait", "wait", "keep"]
    assert got["moving"] == ["wait", "wait", "keep"]
    assert got["fell"] == ["wait", "wait", "wait", "wait", "keep"]
    assert got["no_resize"] == ["wait", "keep"]
    assert got["no_resize_focused"] == ["fallback"]
    assert got["zoom"] == ["wait", "wait", "keep"]  # the zoom counted nothing: the first limit, nothing focused
    assert got["hold_limit"] == ["wait", "wait", "fallback"]
    assert got["hold_focused"] == ["wait", "fallback"]
    assert got["limits"] == [100, 1000]
    assert got["notes"] == ["not fitted — the screen changed, press again", "put the keyboard down, then press again"]


@pytest.mark.unit
def test_the_phone_keeps_its_pixels_and_a_turn_or_a_crossing_drops_them():
    js = APP.read_text()
    focus = js[js.index("  AO.focus = function") :]
    keep = focus[focus.index("    const keepBox = () => {") :]
    keep = keep[: keep.index("    };")]
    # kept on the phone layout alone, with the keyboard and every sheet down, never during a press's hold
    assert "!phone.narrow() || phone.editing() || phone.opened() || fitHold" in keep
    # pixels of another orientation than the screen's are stale; the phone's helper divides the kept pixels
    assert "if (kept && kept.type !== orient()) kept = null;" in focus
    assert "AO.boxGrid = () => gridOfPx((phone.narrow() && keptNow()) || boxEl.getBoundingClientRect());" in focus
    assert "keeper.release(); schedule(); keepBox(); fitRekeep(); drawFit();" in focus  # on any box change
    fit = _focus()
    turn = fit[fit.index("    const turned = () => {") :]
    turn = turn[: turn.index("    };")]
    assert "if (!coarse()) return;" in turn and "kept = null;" in turn  # a coarse pointer alone
    assert "holdEnd(AO.FIT_TURNED)" in turn and "fitEnd(AO.FIT_TURNED)" in turn
    assert 'screen.orientation.addEventListener("change", turned)' in fit
    assert 'window.addEventListener("orientationchange", turned)' in fit  # where screen.orientation is absent
    js = APP.read_text()
    relaid = js[js.index("    phone.relaid(() => {\n      fill();") :]
    assert "kept = null; if (fitWait) fitEnd(AO.FIT_TURNED);" in relaid[: relaid.index("\n    });\n")]


@pytest.mark.unit
def test_a_phone_or_coarse_press_blurs_holds_then_fits():
    fit = _focus()
    begin = fit[fit.index("function holdBegin()") :]
    assert begin.index("a.blur()") < begin.index("phone.close();") < begin.index("phone.hold(true);")
    tick = fit[fit.index("function holdTick(ev)") : fit.index("function holdBegin()")]
    # the layout is released only once the fit is under way, so a crossing it causes cancels that fit
    assert "holdEnd(null, true);" in tick and "try { fitKept(got, wide); } finally { phone.hold(false); }" in tick
    assert "if (document.hidden) { holdEnd(); return; }" in tick  # a hidden page: nothing kept, no note
    # the phone's hold keeps the phone's pixels and falls back to those kept before; a wide page's are its own
    assert "if (!wide) { if (p) kept = p; p = keptNow(); }" in tick
    assert "if (!p) { pinchNote(AO.FIT_NO_BOX); return; }" in tick  # over the terminal, where the pinch's note shows
    assert "fitPress(gridOfPx(p), wide ? p : null);" in tick
    rekeep = fit[fit.index("function fitRekeep()") :]
    assert "if (!fitWait || !fitWait.px || phone.editing() || phone.opened()) return;" in rekeep
    assert "const fitBox = () => (fitWait && fitWait.px ? gridOfPx(fitWait.px) : AO.boxGrid());" in fit


@pytest.mark.unit
def test_the_layout_holds_and_a_blur_reads_the_query_once_the_keyboard_falls():
    js = APP.read_text()
    phone = js[js.index("  AO.phoneFocus = function") :]
    phone = phone[: phone.index("  AO.focus = function")] if "  AO.focus = function" in phone else phone
    assert "editing() || holding);" in phone  # a running hold reads as editing
    assert "hold(on) { holding = !!on; if (!on) relay(); }," in phone
    out = phone[phone.index('document.addEventListener("focusout"') :]
    out = out[: out.index("    });")]
    assert "setTimeout(go, 1000)" in out and 'vv.addEventListener("resize", go)' in out
    assert "setTimeout(relay, 0)" not in phone


@pytest.mark.unit
def test_the_sheet_draws_fit_to_window_after_paste():
    html = (UI / "templates" / "focus.html").read_text()
    assert "('tpaste', '⎘', 'Paste'), ('tfit', '⤢', 'Fit to window')" in html
    js = APP.read_text()
    assert 'if (al && src && src.id === "tfit") al.textContent' in js  # Cancel fit while it waits
