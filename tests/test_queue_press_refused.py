"""TD-1843 step 7 (design §4.5 screen 12 *A press is never left stranded*, case *refused*; §4.5a *Queue card: press
line*): a press the home refused is drawn on its Queue item as a red press line — the stored words with the client's
prefix kept and a capital first, *Nothing was sent.* only where the press wrote nothing, and *It now reads as above;
press again to answer it.* once a re-read draws the item otherwise. The words are run in node; the wiring is read from
the source, as the other press tests read it."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest
from conftest import scratch_dir

APP_JS = pathlib.Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui" / "static" / "app.js"
APP_CSS = APP_JS.with_name("app.css")
JS = APP_JS.read_text()

PROBE = """
const fs = require("fs");
const noop = () => {};
const el = () => ({ dataset: {}, style: {}, addEventListener: noop, appendChild: noop,
  classList: { toggle: noop, add: noop, remove: noop, contains: () => false },
  querySelector: () => null, querySelectorAll: () => [] });
global.window = {};
global.document = { documentElement: el(), body: el(), addEventListener: noop, createElement: el,
  querySelector: () => null, querySelectorAll: () => [] };
global.localStorage = { getItem: () => null, setItem: noop };
global.matchMedia = () => ({ matches: false });
global.setInterval = noop; global.setTimeout = noop; global.clearTimeout = noop;
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
// a row stub: its bar's controls and press line as `querySelectorAll` would find them
const node = (n) => ({ dataset: n.dataset || {}, disabled: !!n.disabled, textContent: n.text });
const row = (nodes) => ({ querySelectorAll: () => nodes.map(node) });
console.log(JSON.stringify({
  lines: cases.lines.map((c) => AO.pressErrLine({ ...AO.pressErr(c.words, c.sent, ""), changed: !!c.changed })),
  sigs: cases.sigs.map((pair) => AO.itemSig(row(pair[0])) === AO.itemSig(row(pair[1]))),
  none: AO.itemSig(null),
}));
"""


def _node(cases: dict) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the press line's words are JavaScript, and nothing else runs them")
    d = scratch_dir()
    (d / "probe.js").write_text(PROBE)
    (d / "cases.json").write_text(json.dumps(cases))
    out = subprocess.run(
        [node, str(d / "probe.js"), str(APP_JS), str(d / "cases.json")], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_refusals_press_line_keeps_its_prefix_capitalised_and_says_what_was_sent():
    got = _node(
        {
            "lines": [
                {"words": "not decided: held by grinder-ao-2", "sent": False},
                {"words": "hold not lifted: TD-12 is not held", "sent": False, "changed": True},
                {"words": "hand-off not finished: the hand-off may have been sent", "sent": True},
                {"words": "sent without its key.", "sent": True, "changed": True},
            ],
            "sigs": [],
        }
    )
    assert got["lines"] == [
        "Not decided: held by grinder-ao-2. Nothing was sent.",
        "Hold not lifted: TD-12 is not held. Nothing was sent. It now reads as above; press again to answer it.",
        "Hand-off not finished: the hand-off may have been sent.",
        "Sent without its key. It now reads as above; press again to answer it.",
    ]


def test_an_items_drawing_changes_with_its_bar_and_not_with_an_age():
    bar = [{"dataset": {"act": "ledger"}, "text": "“Yes”"}, {"text": "Open"}]
    line = {"text": "You answered “Yes”, just now — waiting."}
    later = {"text": "You answered “Yes”, 1 h ago — waiting."}
    got = _node(
        {
            "lines": [],
            "sigs": [
                [[*bar, line], [*bar, later]],  # an age ticking is no change
                [[*bar, line], [*bar[1:], line]],  # an answer gone is
                [bar, [{**bar[0], "disabled": True}, bar[1]]],  # and so is one turned off
                [bar, [{"dataset": {"act": "reply"}, "text": "“Yes”"}, bar[1]]],  # or one on another road
            ],
        }
    )
    assert got["sigs"] == [True, False, False, False]
    assert got["none"] == ""


@pytest.mark.unit
def test_every_refusal_is_stored_with_its_flag_and_drawn_by_the_one_drawer():
    # each writer stores the one shape, its `sent` flag false but where a hand-off may have gone
    for rhs in re.findall(r"AO\.pressErrs\[[^\]]+\] = ([^;]+);", JS):
        # …and the lift whose reply failed after it, which was written (TD-1843 step 5): sent
        assert rhs in ("err", "AO.pressErr(words, AO.maySent(e), atSig)", "AO.pressErr(words, true, atSig)"), rhs
    assert "const err = AO.pressErr(words, !/^not handed: /.test(words), atSig);" in JS
    assert "AO.pressErrs[qled] = AO.pressErr(words, AO.maySent(e), atSig);" in JS
    assert "AO.pressErrs[msgOf] = AO.pressErr(words, AO.maySent(e), atSig);" in JS
    # a refusal with a status wrote nothing; no answer at all, or a verdict unknown, may have
    assert "AO.maySent = (e) => !e || !e.status || e.status === 503;" in JS
    assert "if (row && row.dataset.msg && (left || writes)) AO.pressErrs[row.dataset.msg] = err;" in JS
    # nothing writes a refusal on a row's error line but the drawer
    assert "er.textContent = words" not in JS and "rowerr.textContent" not in JS
    # the item as drawn is read before the press marks it
    h = JS[JS.index("let waiting = null, left = false;") :]
    assert h.index("const atSig = AO.itemSig(") < h.index("const pressed = (text) => {")
    # a re-read marks it changed once, and draws it again
    assert "if (err.was && !err.changed && AO.itemSig(r) !== err.was) err.changed = true;" in JS
    # on a card with a bar, a red press line above the item's own, which it hides while it stands
    d = JS[JS.index("AO.drawPressErr = function") : JS.index("AO.clearPressErr = function")]
    assert 'if (!bar || !row.closest(".qcard"))' in d
    assert 'line.className = "qpress qp-stalled qp-err";' in d
    assert 'const at = row.querySelector(".qpress:not(.qp-err)") || bar;' in d
    assert 'row.querySelectorAll(".qpress:not(.qp-err)").forEach((p) => { p.hidden = true; });' in d
    # the next press takes it away and gives the item's own press line back
    c = JS[JS.index("AO.clearPressErr = function") :]
    assert 'row.querySelectorAll(".qpress[hidden]").forEach((p) => { p.hidden = false; });' in c[:400]
    assert "delete AO.pressErrs[row.dataset.msg];\n      AO.clearPressErr(row);" in JS
    assert ".qpress.qp-stalled { border-left-color: var(--stalled);" in APP_CSS.read_text()
