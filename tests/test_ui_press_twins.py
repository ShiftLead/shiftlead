"""TD-1997 slice 2, design §4.5 screen 6 rule 2 *A press with no row* (TD-1968): a press marks its twins with it —
every control with its `data-act` and target, and the other half of an Allow/Deny pair of the same call — a menu
entry's verb going on its menu's `summary`; and a delta-ended press (Kill, Close, a mode switch, a card's Start now,
Allow, Deny and Restart outside a row, the Focus page's grant and controller chips and Drop) ends at the first
redraw that draws its effect, read against a snapshot of its container taken at the press — at the response where
such a redraw came first, else at the redraw, or 5 s after the response — never at the response alone. A refusal
ends it at once. `AO.remarkPresses` marks the press's controls again after a swap. The helpers run under node on
`test_ui_press_draw`'s small DOM; the swap sites' wiring is pinned by source."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
from test_ui_press_draw import PROBE

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "src" / "shiftlead" / "ui" / "static" / "app.js"

DOM = PROBE.split("// ---- fixtures")[0].replace(
    'eval(fs.readFileSync(process.argv[2], "utf8"));',
    r"""Object.defineProperty(El.prototype, "id", { get() { return this.attrs.id || ""; } });
document.querySelectorAll = (sel) => document.body.querySelectorAll(sel);
document.querySelector = (sel) => document.body.querySelector(sel);
document.getElementById = (id) => document.body.descendants().find((e) => e.id === id) || null;
const timers = [];
const cleared = [];
global.setTimeout = (fn) => { timers.push(fn); return timers.length; };
global.clearTimeout = (id) => cleared.push(id);
eval(fs.readFileSync(process.argv[2], "utf8"));""",
)

TWINS = (
    DOM
    + r"""
const out = {};
const st = (b) => ({ text: b.textContent, dis: b.getAttribute("aria-disabled"), busy: b.getAttribute("aria-busy"),
  disabled: b.disabled });
const clear = () => {
  document.body.children.slice().forEach((c) => c.remove());
  Object.keys(AO.inflight).forEach((k) => delete AO.inflight[k]);
  timers.length = 0;
};
// a session card: its bar's Close, its menu's Kill and Close, and two open prompts' Allow and Deny
const card = (o) => {
  const x = o || {};
  const menu = h("details", "more", {}, [h("summary", "", { text: "more ▾" }),
    ...(x.noKill ? [] : [h("button", "", { "data-act": "kill", "data-id": "w1", id: "", text: "Kill" })]),
    h("button", "", { "data-act": "close", "data-id": "w1", text: "Close" })]);
  const c = h("div", "card sc", { id: "card-w1" }, [
    h("button", "btn sm next", { "data-act": "close", "data-id": "w1", text: "Close session" }),
    ...(x.calls || ["c1", "c2"]).flatMap((call) => [
      h("button", "btn sm", { "data-act": "allow", "data-id": "w1", "data-call": call, text: "Allow" }),
      h("button", "btn sm", { "data-act": "deny", "data-id": "w1", "data-call": call, text: "Deny" })]),
    menu]);
  document.body.appendChild(c);
  return c;
};
const swap = (o) => {
  const old = document.getElementById("card-w1");
  if (old) old.remove();
  const c = card(o);
  AO.remarkPresses(c);
  return c;
};
const q = (sel, root) => (root || document.body).querySelector(sel);

// 1. Kill in the card's menu: marked, its verb on the summary; an unrelated redraw keeps it marked across the
// response and a second unrelated redraw; the redraw that draws Kill gone ends it
let c = card();
let kill = q('[data-act="kill"]', c);
const mk = AO.pressBegin(kill, "kill");
out.kill_key = mk;
out.kill = st(kill);
out.kill_summary = [q("summary", c).textContent, q("summary", c).getAttribute("aria-busy")];
out.kill_delta = AO.inflight[mk].delta;
c = swap();
out.kill_after_swap = st(q('[data-act="kill"]', c));
out.summary_after_swap = q("summary", c).textContent;
AO.pressAnswered(mk, false);
out.kill_held_after_response = !!AO.inflight[mk] && st(q('[data-act="kill"]', c)).text;
c = swap();
out.kill_held_second_redraw = !!AO.inflight[mk] && st(q('[data-act="kill"]', c)).text;
c = swap({ noKill: true });
out.kill_ended = !AO.inflight[mk];
out.summary_back = q("summary", c).textContent;
out.no_timer_left = timers.length === 1 && cleared.includes(1);  // the one 5 s timer was set and cleared by the end

// 2. Kill's effect drawn before its response: the mark ends at the response, not 5 s later
clear(); c = card();
const mk2 = AO.pressBegin(q('[data-act="kill"]', c), "kill");
c = swap({ noKill: true });
out.early_still_held = !!AO.inflight[mk2];
AO.pressAnswered(mk2, false);
out.early_ended_at_response = !AO.inflight[mk2] && timers.length === 0;

// 3. a refusal ends it at once, the label back
clear(); c = card();
kill = q('[data-act="kill"]', c);
const mk3 = AO.pressBegin(kill, "kill");
AO.pressAnswered(mk3, true);
out.refused = [!AO.inflight[mk3], kill.textContent, kill.getAttribute("aria-disabled"), q("summary", c).textContent];

// 4. one prompt's Allow marks its own Deny, never the other prompt's
clear(); c = card();
const allows = c.querySelectorAll('[data-act="allow"]'), denies = c.querySelectorAll('[data-act="deny"]');
AO.pressBegin(allows[0], "allow");
out.pair = [st(allows[0]).text, st(denies[0]).text, st(allows[1]).dis, st(denies[1]).dis];

// 5. the bar's Close marks the menu's Close (its own verb, the summary left as it is)
clear(); c = card();
const bar = c.children[0];
AO.pressBegin(bar, "close");
out.close_twin = [st(c.querySelectorAll('[data-act="close"]')[1]).text, q("summary", c).textContent];

// 6. a card taken off the page ends its press
clear(); c = card();
const mk6 = AO.pressBegin(q('[data-act="kill"]', c), "kill");
c.remove(); AO.remarkPresses(document.body);
out.gone_ended = !AO.inflight[mk6];

// 7. a press no redraw answers ends 5 s after the response
clear(); c = card();
const mk7 = AO.pressBegin(q('[data-act="kill"]', c), "kill");
AO.pressAnswered(mk7, false);
out.timer_waits = !!AO.inflight[mk7];
timers.forEach((f) => f());
out.timer_ended = !AO.inflight[mk7] && q('[data-act="kill"]', c).textContent === "Kill";

// 8. a press that is not delta-ended (Message) ends at its response
clear();
const msg = h("button", "btn sm", { "data-act": "message", "data-id": "w1", text: "Message" });
document.body.appendChild(msg);
const mk8 = AO.pressBegin(msg, "message");
AO.pressAnswered(mk8, false);
out.message_ended = [!AO.inflight[mk8], msg.textContent];

// ---- the Focus page ----
clear();
location.pathname = "/focus/w1";
const fclose = h("button", "btn sm next", { id: "fclose", "data-act": "close", "data-id": "w1", text: "Close" });
const fmodeact = h("button", "btn sm", { id: "fmodeact", "data-act": "mode", "data-via": "focus", "data-id": "w1",
  "data-unattended": "1", text: "Switch to unattended" });
const fmenu = h("details", "more", {}, [h("summary", "", { text: "more ▾" }),
  h("button", "", { id: "fmodemenu", "data-act": "mode", "data-via": "focus", "data-id": "w1", "data-unattended": "1",
    text: "Switch to unattended" }),
  h("button", "", { id: "fclosemenu", "data-act": "close", "data-id": "w1", text: "Close" })]);
const closebtn = h("button", "btn sm", { id: "closebtn", "data-act": "close", "data-id": "w1", text: "Close" });
const chip = h("button", "badge", { "data-act": "grants", "data-id": "w1", "data-grant": "push", text: "push" });
const watchgo = h("button", "btn", { id: "fwatchgo", "data-act": "mode", "data-via": "focus", "data-id": "w1",
  "data-unattended": "1", text: "Take over" });
const fwatch = h("div", "", { id: "fwatch" }, [watchgo]);
const drop = h("button", "", { "data-act": "drop", "data-id": "w1", "data-ref": "TD-9", text: "Drop TD-9…" });
const reports = h("details", "more", { id: "reportsmore" }, [h("summary", "", { text: "more ▾" }),
  h("div", "menu", { id: "reportsmenu" }, [drop])]);
[fclose, fmodeact, fmenu, closebtn, chip, fwatch, reports].forEach((e) => document.body.appendChild(e));

// 9. Close in its bar marks its twins; Close drawn off by a delta while the press is out stays off after the unmark
const mk9 = AO.pressBegin(fclose, "close");
out.focus_close = [st(fclose).text, st(document.getElementById("fclosemenu")).text, st(closebtn).text,
  fmenu.children[0].textContent];
document.getElementById("fclosemenu").disabled = true;
AO.remarkPresses(document);
AO.pressAnswered(mk9, false);
out.focus_close_ended = !AO.inflight[mk9];
const fcm = document.getElementById("fclosemenu");
out.closemenu_stays_off = [fcm.disabled, fcm.textContent];

// 10. a mode press: a delta that changes only `next` or `data-confirm` keeps the mark; the one that flips the label
// ends it, the label the page drew
const mk10 = AO.pressBegin(fmodeact, "mode");
out.mode_twins = [st(fmodeact).text, st(document.getElementById("fmodemenu")).text, st(watchgo).text];
fmodeact.classList.add("next"); fmodeact.setAttribute("data-confirm", "Sure?");
AO.pressAnswered(mk10, false);
AO.remarkPresses(document);
out.mode_held = !!AO.inflight[mk10] && fmodeact.textContent;
fmodeact.textContent = "Switch to interactive"; fmodeact.setAttribute("data-unattended", "0");
AO.remarkPresses(document);
out.mode_ended = [!AO.inflight[mk10], fmodeact.textContent, fmodeact.getAttribute("aria-disabled")];

// 11. the watch bar's Take over ends when the delta hides the watch bar
const mk11 = AO.pressBegin(watchgo, "mode");
fwatch.hidden = true;
AO.remarkPresses(document);
out.watch_effect = AO.inflight[mk11] && AO.inflight[mk11].effect;
AO.pressAnswered(mk11, false);
out.watch_ended = !AO.inflight[mk11];

// 12. a grant chip keeps its words and ends at the redraw that flips its `off` class
const mk12 = AO.pressBegin(chip, "grants");
out.chip = st(chip);
AO.pressAnswered(mk12, false);
AO.remarkPresses(document);
out.chip_held = !!AO.inflight[mk12];
chip.classList.add("off");
AO.remarkPresses(document);
out.chip_ended = !AO.inflight[mk12];

// 13. Drop: a `render()` redraw neither ends it nor changes it; the Reports' redraw that takes it away does
const mk13 = AO.pressBegin(drop, "drop");
out.drop_summary = reports.children[0].textContent;
AO.pressAnswered(mk13, false);
AO.remarkPresses(document);
out.drop_held_by_render = !!AO.inflight[mk13];
drop.remove();
AO.remarkPresses(document.getElementById("reportsmenu"));
out.drop_ended = [!AO.inflight[mk13], reports.children[0].textContent];
console.log(JSON.stringify(out));
"""
)


@pytest.fixture(scope="module")
def twins(tmp_path_factory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    probe = tmp_path_factory.mktemp("press_twins") / "press_twins_probe.js"
    probe.write_text(TWINS)
    got = subprocess.run(["node", str(probe), str(APP_JS)], capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout.strip().splitlines()[-1])


def test_a_menu_entry_marks_its_summary_and_stays_marked_across_unrelated_redraws(twins):
    assert twins["kill_key"] == "press:kill:w1"
    assert twins["kill"] == {"text": "killing…", "dis": "true", "busy": "true", "disabled": False}
    assert twins["kill_summary"] == ["killing…", "true"] and twins["kill_delta"] is True
    assert twins["kill_after_swap"]["text"] == "killing…" and twins["summary_after_swap"] == "killing…"
    assert twins["kill_held_after_response"] == "killing…"
    assert twins["kill_held_second_redraw"] == "killing…"


def test_the_redraw_that_draws_kills_effect_ends_the_mark(twins):
    assert twins["kill_ended"] is True and twins["summary_back"] == "more ▾" and twins["no_timer_left"] is True


def test_an_effect_drawn_before_the_response_ends_the_mark_at_the_response(twins):
    assert twins["early_still_held"] is True and twins["early_ended_at_response"] is True


def test_a_refusal_ends_the_mark_at_once(twins):
    assert twins["refused"] == [True, "Kill", None, "more ▾"]


def test_one_prompts_allow_marks_its_own_deny_and_no_other_prompt(twins):
    assert twins["pair"] == ["sending…", "sending…", None, None]


def test_a_twin_in_a_menu_leaves_the_summary_alone(twins):
    assert twins["close_twin"] == ["closing…", "more ▾"]


def test_a_card_taken_off_the_page_ends_its_press(twins):
    assert twins["gone_ended"] is True


def test_a_press_no_redraw_answers_ends_five_seconds_on(twins):
    assert twins["timer_waits"] is True and twins["timer_ended"] is True


def test_a_press_that_is_not_delta_ended_ends_at_its_response(twins):
    assert twins["message_ended"] == [True, "Message"]


def test_the_focus_close_marks_its_twins_and_a_delta_drawn_off_stays_off(twins):
    assert twins["focus_close"] == ["closing…", "closing…", "closing…", "more ▾"]
    assert twins["focus_close_ended"] is True
    assert twins["closemenu_stays_off"] == [True, "Close"]


def test_a_mode_press_ends_at_the_delta_that_flips_its_label(twins):
    assert twins["mode_twins"] == ["switching…", "switching…", "switching…"]
    assert twins["mode_held"] == "switching…"
    assert twins["mode_ended"] == [True, "Switch to interactive", None]


def test_take_over_ends_when_the_watch_bar_is_hidden(twins):
    assert twins["watch_effect"] is True and twins["watch_ended"] is True


def test_a_grant_chip_keeps_its_words_and_ends_when_its_off_class_flips(twins):
    assert twins["chip"]["text"] == "push" and twins["chip"]["dis"] == "true"
    assert twins["chip_held"] is True and twins["chip_ended"] is True


def test_drop_is_ended_by_the_reports_redraw_alone(twins):
    assert twins["drop_summary"] == "Drop TD-9…"  # its own label, already ending in `…`, on the Reports' summary
    assert twins["drop_held_by_render"] is True
    assert twins["drop_ended"] == [True, "more ▾"]


def _src() -> str:
    return APP_JS.read_text()


def test_the_handler_begins_and_answers_a_press_with_no_row():
    src = _src()
    assert "markKey = AO.pressBegin(b, key);" in src
    assert "if (markKey && !moving) AO.pressAnswered(markKey, refusedOn);" in src


def test_every_swap_that_can_redraw_a_marked_control_marks_it_again():
    src = _src()
    assert "old.replaceWith(fresh); AO.restoreDenyWhys(fresh, kept);" in src
    assert src.count("AO.remarkPresses(fresh);") == 2  # a session card's swap, a team summary's
    assert "render(s); AO.remarkPresses(document); phone.render(s);" in src
    assert src.count("AO.remarkPresses(document);") == 2
    assert 'renderReports(reportsV); AO.remarkPresses($("#reportsmenu"));' in src
    assert "AO.remarkPresses(document.body);  // a press whose card went ends with it" in src
    assert src.count("AO.restoreRowErrs(") == src.count("AO.remarkPresses(lists)") + src.count(
        "AO.remarkPresses(el)"
    ) + src.count("AO.remarkPresses(hz)") + src.count("AO.remarkPresses(lf)") + src.count("AO.remarkPresses(n)")
