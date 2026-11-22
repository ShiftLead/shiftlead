"""TD-1997 slice 3, design §4.5 screen 6 rule 2 *A press with no row* (TD-1968) on the Focus page: its header's
more ▾, Kill with it, is not drawn once the pane is gone (§4.5's exited state, §4.5a *Focus: Kill*), hidden by the
Focus delta before `render()`'s early return for a record with no agent, so a Kill's mark ends at the redraw that
hides it — on a shell's record as on an agent's; and the phone sheet's proxies read the mark (drawn off, the verb
their label) and go with a hidden ancestor. The helpers run under node on `test_ui_press_twins`' small DOM; the
Focus page's wiring is pinned by source."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
from test_ui_press_twins import DOM

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "src" / "shiftlead" / "ui" / "static" / "app.js"
FOCUS = ROOT / "src" / "shiftlead" / "ui" / "templates" / "focus.html"

PROBE = (
    DOM
    + r"""
const out = {};
location.pathname = "/focus/w1";
const kill = h("button", "danger", { id: "fkill", "data-act": "kill", "data-id": "w1", text: "✕ Kill" });
const more = h("details", "more", { id: "fheadmore" },
  [h("summary", "", { text: "more ▾" }), h("div", "menu", {}, [kill])]);
document.body.appendChild(more);

// Kill pressed in the more ▾: an unrelated Focus redraw keeps it marked past its response; the redraw that hides
// the more ▾ (the pane gone) ends it, Kill hidden by its ancestor
const mk = AO.pressBegin(kill, "kill");
out.marked = [kill.textContent, kill.getAttribute("aria-disabled"), more.children[0].textContent];
AO.pressAnswered(mk, false);
AO.remarkPresses(document);
out.held = !!AO.inflight[mk];
more.hidden = true;
AO.remarkPresses(document);
out.ended = [!AO.inflight[mk], kill.getAttribute("aria-disabled"), kill.textContent];
console.log(JSON.stringify(out));
"""
)


@pytest.fixture(scope="module")
def probe(tmp_path_factory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    f = tmp_path_factory.mktemp("press_focus") / "press_focus_probe.js"
    f.write_text(PROBE)
    got = subprocess.run(["node", str(f), str(APP_JS)], capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout.strip().splitlines()[-1])


def test_kill_stays_marked_until_the_redraw_that_hides_the_more_menu(probe):
    assert probe["marked"] == ["killing…", "true", "killing…"]
    assert probe["held"] is True
    assert probe["ended"] == [True, None, "✕ Kill"]


def _render() -> str:
    src = APP_JS.read_text()
    start = src.index("    function render(v) {")
    return src[start : src.index("\n    }\n", start)]


def test_the_focus_delta_hides_the_more_menu_once_the_pane_is_gone_before_a_shells_early_return():
    body = _render()
    hide = body.index("headMore.hidden = gone;")
    assert "const gone = AO.paneIsGone(v);" in body
    assert hide < body.index("if (v.agent === false) {")


def test_the_template_draws_the_more_menu_hidden_on_a_record_whose_pane_is_gone():
    html = FOCUS.read_text()
    drawn = '<details class="more" id="fheadmore"{% if s.state == \'closed\' or s.pane is sameas false %}'
    assert drawn + " hidden{% endif %}>" in html


def test_the_phone_sheet_reads_the_mark_and_a_hidden_ancestor():
    src = APP_JS.read_text()
    sheet = src[src.index("AO.phoneFocus = function") :]
    sheet = sheet[: sheet.index("\n  };\n")]
    assert 'n.hidden || n.classList?.contains("hidden")' in sheet  # shown() walks the ancestors
    assert "const marked = AO.pressMarked(src);" in sheet
    assert "b.disabled = !!(src && (src.disabled || marked));" in sheet
    assert "if (al && src && marked) al.textContent = src.dataset.pressVerb || drawnSheetLabel(src);" in sheet
    assert "else if (al) al.textContent = al.dataset.sheetLabel;" in sheet
    # the sheet fills after the re-mark, on the first draw and on every delta
    assert "render(s); AO.remarkPresses(document); phone.render(s);" in src
    i = src.index("        render(ev.session);\n        AO.remarkPresses(document);")
    assert src.index("phone.render(ev.session);", i) > i
