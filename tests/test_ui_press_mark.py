"""TD-1997 slice 1, design §4.5 screen 6 rule 2 *A press with no row* (TD-1968): a control in no row is itself marked
in the press's frame — off by `aria-disabled` (never `disabled`), `aria-busy`, its width held, its label giving way to
its verb (`data-verb`, else `PRESS_VERBS`, else its label with `…`) — held in `AO.inflight` under its own
`press:<wire name>:<target>` key, and put back at its answer, unless the answer moves the page; a refusal names the
control by its own label. The helpers run under node on `test_ui_press_draw`'s small DOM; the handler's wiring and
the templates' `data-verb` are pinned by source."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from test_ui_press_draw import PROBE

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "src" / "shiftlead" / "ui" / "static" / "app.js"
TEMPLATES = ROOT / "src" / "shiftlead" / "ui" / "templates"

MARK = (
    PROBE.split("// ---- fixtures")[0]
    + r"""
const out = {};
const snapBtn = (b) => ({ text: b.textContent, dis: b.getAttribute("aria-disabled"), busy: b.getAttribute("aria-busy"),
  disabled: b.disabled, width: b.style.minWidth || "", mark: b.dataset.pressMark || "" });
// the Queue card header's Start session: its verb from the table, its width held, then put back
const start = h("button", "btn sm ghost qstart", { "data-act": "ledger_start", "data-id": "person", "data-repo": "s",
  "data-ref": "TD-1", "data-card": "c1", text: "Start session" });
start.offsetWidth = 112;
const was = snap(start);
out.start_key = AO.pressMarkKey(start);
AO.markPress(start, "ledger_start");
out.start_marked = snapBtn(start);
out.start_is_marked = AO.pressMarked(start);
AO.markPress(start, "ledger_start");  // a second mark changes nothing
out.start_twice = start.textContent;
AO.unmarkPress(start);
out.start_back = snap(start) === was;
out.start_unmarked = snapBtn(start);
// Open session: its own `data-verb`
const open = h("button", "btn sm ghost qstart", { "data-act": "ledger_start", "data-verb": "opening…",
  "data-id": "person", "data-repo": "s", "data-ref": "TD-2", "data-card": "c2", text: "Open session" });
AO.markPress(open, "ledger_start");
out.open_text = open.textContent;
out.open_key = AO.pressMarkKey(open);
// a control the table does not name: its label with `…`, never a second `…`
const odd = h("button", "btn sm", { "data-act": "frob", "data-id": "w1", text: "Frob" });
AO.markPress(odd, "frob");
out.odd_text = odd.textContent;
const dots = h("button", "btn sm", { "data-act": "frob", "data-id": "w1", text: "Not right…" });
AO.markPress(dots, "frob");
out.dots_text = dots.textContent;
// a badge keeps its words; a Kill reads its table verb
const badge = h("span", "badge", { "data-act": "start", "data-id": "w1", "data-ask": "1", text: "starts 20:00" });
AO.markPress(badge, "start");
out.badge = snapBtn(badge);
const kill = h("button", "btn sm", { "data-act": "kill", "data-id": "w1", text: "Kill" });
AO.markPress(kill, "kill");
out.kill_text = kill.textContent;
// keys: a session's control by its id, one prompt's Allow by its call, a chip by its grant
const allow = (call) => h("button", "btn sm", { "data-act": "allow", "data-id": "w1", "data-call": call,
  text: "Allow" });
out.allow_keys = [AO.pressMarkKey(allow("c-1")), AO.pressMarkKey(allow("c-2")), AO.pressMarkKey(allow(""))];
out.grant_key = AO.pressMarkKey(h("span", "chip", { "data-act": "grants", "data-id": "w1", "data-grant": "push" }));
console.log(JSON.stringify(out));
"""
)


@pytest.fixture(scope="module")
def marked(tmp_path_factory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    probe = tmp_path_factory.mktemp("press_mark") / "press_mark_probe.js"
    probe.write_text(MARK)
    got = subprocess.run(["node", str(probe), str(APP_JS)], capture_output=True, text=True, timeout=60, check=True)
    return json.loads(got.stdout.strip().splitlines()[-1])


def test_the_queue_headers_start_session_is_marked_and_put_back(marked):
    """Off by `aria-disabled` (never `disabled`), busy, *starting…*, its width held; unmarked, exactly as it was."""
    assert marked["start_marked"] == {
        "text": "starting…", "dis": "true", "busy": "true", "disabled": False, "width": "112px", "mark": "1",
    }  # fmt: skip
    assert marked["start_is_marked"] is True and marked["start_twice"] == "starting…"
    assert marked["start_back"] is True
    assert marked["start_unmarked"]["dis"] is None and marked["start_unmarked"]["text"] == "Start session"


def test_open_session_reads_opening_and_the_verbs_fall_back_to_the_label(marked):
    assert marked["open_text"] == "opening…"
    assert marked["odd_text"] == "Frob…" and marked["dots_text"] == "Not right…"
    assert marked["kill_text"] == "killing…"


def test_a_badge_keeps_its_words(marked):
    b = marked["badge"]
    assert b["text"] == "starts 20:00" and b["dis"] == "true" and b["busy"] == "true"


def test_each_press_holds_a_key_of_its_own(marked):
    """Two Queue headers' Start sessions (both `data-id="person"`) differ by repo, ref and card; two prompts' Allows
    by their call, an empty call falling back to the session's id; a chip by its grant."""
    assert marked["start_key"] == "press:ledger_start:s:TD-1:c1"
    assert marked["open_key"] == "press:ledger_start:s:TD-2:c2"
    assert marked["allow_keys"] == ["press:allow:w1:c-1", "press:allow:w1:c-2", "press:allow:w1"]
    assert marked["grant_key"] == "press:grants:w1:push"


def test_the_new_verbs_are_in_the_table():
    src = APP_JS.read_text()
    table = src[src.index("const PRESS_VERBS = {") : src.index("const PRESS_NOT = {")]
    for k, v in {"start": "starting…", "kill": "killing…", "close": "closing…", "remove": "removing…",
                 "wrapup": "sending…", "message": "sending…"}.items():  # fmt: skip
        assert f'{k}: "{v}"' in table, k


def _handler() -> str:
    src = APP_JS.read_text()
    i = src.index('document.addEventListener("click", async (ev) => {')
    return src[i : src.index("// design §4.5a **Inbox row: details**", i)]


def test_the_handler_sends_nothing_from_a_marked_control_before_it_asks_anything():
    h = _handler()
    guard = h.index("if (AO.pressMarked(b)) { ev.preventDefault(); return; }")
    assert guard < h.index("if (b.dataset.confirm && !confirm(b.dataset.confirm)) return;")
    assert guard < h.index("const notClear =")


def test_a_press_with_no_row_is_marked_by_pressed_and_ends_at_its_answer():
    h = _handler()
    body = h[h.index("const pressed = (text) => {") :]
    nor = body[: body.index("if (!row || !row.isConnected) return;")]
    assert (
        "if (!row && !qt) {" in nor
        and "AO.markPress(b, key);" in nor
        and 'AO.inflight[markKey] = { kind: "press" };' in nor
    )
    fin = h[h.rindex("} finally {") :]
    assert "if (markKey) { delete AO.inflight[markKey]; if (!moving) AO.unmarkPress(b); }" in fin


def test_a_press_whose_answer_moves_the_page_stays_marked():
    """Every `location.href =` the handler sets is preceded by `moving = true`."""
    h = _handler()
    for m in re.finditer(r"location\.href = ", h):
        before = h[max(0, m.start() - 40) : m.start()]
        assert "moving = true;" in before, h[m.start() - 80 : m.start() + 40]


def test_a_refusal_names_the_control_by_its_own_label():
    h = _handler()
    assert 'const atLabel = String(b.textContent || "").trim();' in h
    assert h.index("const atLabel") < h.index("const pressed = (text) => {")
    assert "const name = b.dataset.verb || markKey ? atLabel || named[action] || action : named[action] || action;" in h
    assert "say(`${name} failed: ${e.message}`);" in h


def test_the_row_mark_reads_data_verb_first():
    assert "const verb = b.dataset.verb || AO.pressVerb(key);" in _handler()


def test_the_templates_carry_their_verbs():
    card = (TEMPLATES / "queue_card.html").read_text()
    assert re.search(r'data-act="ledger_start" data-verb="opening…"[^>]*>Open session</button>', card)
    row = (TEMPLATES / "inbox_row.html").read_text()
    assert 'data-act="ledger_start"{% if s.own %} data-verb="opening…"{% endif %}' in row
    assert re.search(r'data-act="ledger_start" data-verb="opening…"[^>]*>Open session</button>', row)
    assert 'data-act="close" data-verb="cancelling…"' in (TEMPLATES / "focus.html").read_text()
    c = (TEMPLATES / "card.html").read_text()
    assert 'data-act="close" data-verb="cancelling…"' in c and c.count('data-act="remove" data-verb="forgetting…"') == 2
    assert 'data-act="remove" data-verb="forgetting…" data-id="${id}">Forget</button>' in APP_JS.read_text()
