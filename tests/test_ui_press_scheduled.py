"""TD-1997 slice 4, design §4.5 screen 6 rule 2 *A press with no row* and screen 12 *Start session* (TD-1968) on a
scheduled session's Focus page, which wires no delta: its Start now, its time badge's move and its controller chips
reload the page at their response, the reload drawing the effect; a record whose start is due (the view's
`starting`) is drawn Start now *starting…* and its time badge off, from the record, and looks every 2 s; Cancel goes
where Forget on its own Focus goes, and in a popped window keeps the page and says it is forgotten. The view and the
template are rendered; the script's wiring is pinned by source."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from test_ui_phone_focus import _page
from test_ui_press_twins import DOM

from shiftlead.ui.cards import starting

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_JS = ROOT / "src" / "shiftlead" / "ui" / "static" / "app.js"
NOW = datetime(2026, 11, 22, 12, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize(
    ("rec", "due"),
    [
        ({"start_at": _iso(NOW)}, True),
        ({"start_at": _iso(NOW - timedelta(seconds=20))}, True),
        ({"start_at": _iso(NOW - timedelta(seconds=21))}, False),  # 20 s past and still scheduled: pressable again
        ({"start_at": _iso(NOW + timedelta(minutes=5))}, False),  # not yet due
        ({"start_at": _iso(NOW), "restart_ceiling": {"why": "fill", "count": 3}}, False),  # the tick skips it
        ({"start_at": _iso(NOW), "state": "idle"}, False),
        ({"start_at": "not a time"}, False),
        ({}, False),
    ],
)
def test_a_scheduled_record_is_starting_while_its_start_is_due(rec, due):
    assert starting({"state": "scheduled", **rec}, NOW) is due


def test_a_due_record_draws_start_now_starting_and_its_time_badge_off(tmp_path, monkeypatch):
    at = _iso(datetime.now(UTC) - timedelta(seconds=2))
    html = _page(tmp_path, monkeypatch, state="scheduled", start_at=at)
    banner = html[html.index('id="fscheduled"') : html.index("</div>", html.index('id="fscheduled"'))]
    assert 'data-starting="1"' in banner
    badge = banner[banner.index('data-ask="1"') : banner.index("</button>", banner.index('data-ask="1"'))]
    assert 'aria-disabled="true" aria-busy="true"' in badge and ">starts " in badge  # keeps its words
    now = banner[banner.index('data-at="now"') : banner.index("</button>", banner.index('data-at="now"'))]
    assert 'aria-disabled="true" aria-busy="true"' in now and now.endswith(">starting…")
    assert 'style="min-width: 6.5em"' in now  # wide enough for both labels, so neither moves Cancel
    cancel = banner[banner.index('data-act="close"') :]
    assert "aria-disabled" not in cancel  # Cancel stays pressable


def test_a_record_not_yet_due_draws_start_now_pressable(tmp_path, monkeypatch):
    at = _iso(datetime.now(UTC) + timedelta(hours=1))
    html = _page(tmp_path, monkeypatch, state="scheduled", start_at=at)
    banner = html[html.index('id="fscheduled"') : html.index("</div>", html.index('id="fscheduled"'))]
    assert "data-starting" not in banner and "aria-disabled" not in banner
    assert ">Start now</button>" in banner


def test_a_ceilinged_record_draws_start_now_pressable(tmp_path, monkeypatch):
    at = _iso(datetime.now(UTC) - timedelta(seconds=2))
    html = _page(tmp_path, monkeypatch, state="scheduled", start_at=at, restart_ceiling={"why": "fill", "count": 3})
    banner = html[html.index('id="fscheduled"') : html.index("</div>", html.index('id="fscheduled"'))]
    assert "aria-disabled" not in banner and ">Start now</button>" in banner


def _src() -> str:
    return APP_JS.read_text()


def test_the_scheduled_page_looks_every_two_seconds_while_due_and_never_under_a_press():
    src = _src()
    branch = src[src.index('    if (s.state === "scheduled") {') :]
    branch = branch[: branch.index("      return;\n    }")]
    assert "AO.scheduledId = id;" in branch
    assert '|| Object.keys(AO.inflight).some((k) => k.startsWith("press:"));' in branch
    assert "AO.scheduledLook = setInterval(() => { if (!busy()) location.reload(); }, due ? 2000 : 20000);" in branch
    # the carried toast is read, said and dropped before the scheduled branch, so a started page says it too
    said = src.index("const said = sessionStorage.getItem(`ao.focussaid.${id}`);")
    assert said < src.index('    if (s.state === "scheduled") {') and said > src.index(
        "AO.focus = function (s, popped)"
    )


def test_a_scheduled_pages_presses_reload_or_leave_at_their_response():
    src = _src()
    block = src[src.index("      if (AO.scheduledId && id === AO.scheduledId) {") :]
    block = block[: block.index("\n      }\n", block.index('if (action === "close") {'))]
    assert 'if (action === "start" || action === "uncontrol") {' in block
    # a move to now carries no toast, the drawn wait its answer; the others' said once on the loaded page
    assert "if (!toNow) try { sessionStorage.setItem(`ao.focussaid.${id}`, words); }" in block
    assert "moving = true; location.reload(); return;" in block
    # Cancel: where Forget goes outside a popped window; in one, the page kept, its look stopped, forgotten drawn
    assert 'if (!AO.poppedId) { moving = true; location.href = "/"; return; }' in block
    assert "clearInterval(AO.scheduledLook);" in block
    assert '["#fscheduled", "#closebtn"].forEach' in block
    assert "AO.focusForgotten(AO.scheduledName || id);" in block
    # the block sits after the request is answered, never before it leaves
    assert src.index("      if (AO.scheduledId && id === AO.scheduledId) {") > src.index(
        "const res = await act(id, action2 || action, body);"
    )


def test_the_gone_event_and_a_popped_cancel_draw_forgotten_alike():
    src = _src()
    assert "else AO.focusForgotten(s.name);" in src
    assert src.count("This session was forgotten: its record is gone.") == 1


SHAPES = (
    DOM
    + r"""
const out = {};
location.pathname = "/focus/w1";
const mk = () => {
  document.body.children.slice().forEach((c) => c.remove());
  Object.keys(AO.inflight).forEach((k) => delete AO.inflight[k]);
  const badge = h("button", "badge", { "data-act": "start", "data-id": "w1", "data-ask": "1", text: "starts 20:00" });
  const now = h("button", "btn sm", { "data-act": "start", "data-id": "w1", "data-at": "now", text: "Start now" });
  document.body.appendChild(h("div", "inline-banner", { id: "fscheduled" }, [badge, now]));
  return [badge, now];
};
let [badge, now] = mk();
AO.pressBegin(badge, "start");
out.move = [badge.textContent, now.textContent, now.getAttribute("aria-disabled"), now.getAttribute("aria-busy")];
AO.remarkPresses(document);
out.move_remarked = now.textContent;
[badge, now] = mk();
AO.pressBegin(now, "start");
out.now = [now.textContent, badge.textContent, badge.getAttribute("aria-disabled")];
console.log(JSON.stringify(out));
"""
)


@pytest.fixture(scope="module")
def shapes(tmp_path_factory) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    f = tmp_path_factory.mktemp("press_sched") / "press_sched_probe.js"
    f.write_text(SHAPES)
    got = subprocess.run(["node", str(f), str(APP_JS)], capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout.strip().splitlines()[-1])


def test_a_time_move_marks_start_now_off_keeping_its_label(shapes):
    assert shapes["move"] == ["starts 20:00", "Start now", "true", "true"]
    assert shapes["move_remarked"] == "Start now"
    assert shapes["now"] == ["starting…", "starts 20:00", "true"]
