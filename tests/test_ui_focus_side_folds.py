"""Focus's side panel opens folded, with a value on each summary (design §4.5 *The Focus screen's
anatomy*, §4.5a *Focus side panel*, TD-964, built by TD-1407): Reports, Inbox, Ready to close and
Session start folded under a new remembered-fold key, the cards whose default did not change fall
back to the old key; Inbox reads *n unread of m* in the rail's blue or *m, all read*; Ready to close
✓ or the first failing check with *+n*, in amber; Session the model, the tool until one is read,
tool · account · model on hover, its heading never shrinking; no Ready to close on a `closed` record."""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
from conftest import scratch_dir

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"

PROBE = """
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
global.location = { pathname: "/", protocol: "http:", host: "x" };
global.fetch = () => Promise.reject(new Error("the probe makes no calls"));
eval(fs.readFileSync(process.argv[2], "utf8"));
const AO = window.AO;
const cards = ["working", "prompts", "git", "reports", "inbox", "sent", "members", "ready", "session"];
console.log(JSON.stringify({
  keys: cards.map(AO.sideFoldKey),
  kept: cards.filter(AO.sideFoldKept),
  inbox: [AO.inboxSummary(1, 5), AO.inboxSummary(0, 6), AO.inboxSummary(0, 0)],
  ready: [
    AO.readySummary([["agent idle", true], ["tree clean", true]]),
    AO.readySummary([["agent idle", true], ["branch pushed", false], ["outcomes reported (1 owed)", false]]),
    AO.readySummary([["branch pushed", false]]),
    AO.readySummary([]),
  ],
}));
"""


def _probe() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed: the summaries are JavaScript, and nothing else runs it")
    probe = scratch_dir() / "side_folds_probe.js"
    probe.write_text(PROBE)
    out = subprocess.run([node, str(probe), str(UI / "static" / "app.js")], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.unit
def test_the_folds_are_read_under_a_new_key_and_only_unchanged_defaults_keep_the_old_one():
    got = _probe()
    assert got["keys"][0] == "focus.fold.working" and all(k.startswith("focus.fold.") for k in got["keys"])
    # a browser that remembered Reports, Inbox, Sent or Ready to close open starts from the new default
    assert got["kept"] == ["working", "prompts", "git", "members", "session"]


@pytest.mark.unit
def test_the_inbox_summary_is_unread_of_total_in_blue_or_all_read_in_grey():
    unread, read, empty = _probe()["inbox"]
    assert unread == '<span class="badge unread">1 unread of 5</span>'
    assert read == "6, all read" and empty == ""


@pytest.mark.unit
def test_the_ready_summary_is_a_tick_or_the_first_failing_check_and_the_rest_counted_in_amber():
    passing, two, one, none = _probe()["ready"]
    assert passing == {"text": "✓", "title": "every check passes", "warn": False}
    assert two["text"] == "✗ branch pushed, +1" and two["warn"]
    assert two["title"] == "✗ branch pushed · ✗ outcomes reported (1 owed)"
    assert one["text"] == "✗ branch pushed" and one["warn"]
    assert none == {"text": "", "title": "", "warn": False}


@pytest.mark.unit
def test_the_page_wires_the_new_key_and_the_summaries_to_the_templates_ids():
    js = (UI / "static" / "app.js").read_text()
    assert "const key = AO.sideFoldKey(d.dataset.side);" in js
    assert "store.get(`focus.side.${d.dataset.side}`, d.open)" in js  # the old key, for unchanged defaults
    assert '$("#inboxcount").innerHTML = AO.inboxSummary(got.unread || 0, es.length);' in js
    assert 'const readySum = $("#readysum");' in js and 'readySum.classList.toggle("warnish", sum.warn)' in js
    assert 'const fmodel = $("#fmodel");' in js and "fmodel.textContent = v.model_short" in js
    css = (UI / "static" / "app.css").read_text()
    assert "details.side > summary .h2 { flex: none; }" in css  # the heading never shrinks for its value
    sumval = next(ln for ln in css.splitlines() if "details.side > summary .sumval {" in ln)
    assert "text-overflow: ellipsis" in sumval and "min-width: 0" in sumval
    assert "details.side > summary .sumval.warnish { color: var(--warn-fg); }" in css


def _render(tmp_path, monkeypatch, **over):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import templates, view

    src = {
        "id": "ao-x-9", "name": "w", "kind": "agent", "adapter": "claude-code", "dir": str(tmp_path),
        "state": "idle", "since": "2026-11-05T16:00:00Z", "confidence": "hook", "pane": True, "tail": ["…"],
        "created": "2026-11-05T15:00:00Z", "unattended": False,
        **over,
    }  # fmt: skip
    v = view(src)
    return v, templates.get_template("focus.html").render(s={**v, "grants_all": [], "ready": []}, host="h")


def _card(html: str, side: str) -> str:
    """The `<details>` opening tag of one side card."""
    at = html.index(f'data-side="{side}"')
    return html[html.rindex("<details", 0, at) : html.index(">", at) + 1]


def test_reports_inbox_ready_and_session_start_folded_and_working_and_git_open(tmp_path, monkeypatch):
    _, html = _render(tmp_path, monkeypatch)
    for side in ("reports", "inbox", "ready", "session", "prompts"):
        assert " open" not in _card(html, side), side
    for side in ("working", "git"):
        assert _card(html, side).endswith(" open>"), side
    ready = html[html.index('data-side="ready"') : html.index("</summary>", html.index('data-side="ready"'))]
    assert 'id="readysum"' in ready  # the value, drawn by the script from the checklist


def test_the_session_summary_is_the_model_with_the_profile_line_on_hover(tmp_path, monkeypatch):
    v, html = _render(tmp_path, monkeypatch, model="claude-opus-5-5")
    assert v["model_short"] == "opus-5-5"
    summary = html[html.index('data-side="session"') : html.index("</summary>", html.index('data-side="session"'))]
    assert f'id="fmodel" title="{v["profile_line"]}">opus-5-5</span>' in summary
    assert "claude-code" in v["profile_line"] and "opus-5-5" in v["profile_line"]
    # the tool alone until a model is read
    v, html = _render(tmp_path, monkeypatch)
    assert v["model_short"] == "claude-code" and 'id="fmodel"' in html


@pytest.mark.parametrize(("state", "drawn"), [("closed", False), ("exited", True), ("idle", True)])
def test_a_closed_record_draws_no_ready_to_close_card(tmp_path, monkeypatch, state, drawn):
    _, html = _render(tmp_path, monkeypatch, state=state, pane=state != "closed")
    assert ('data-side="ready"' in html) is drawn
    # the script survives a record whose card is gone: every use of the checklist's ids is guarded
    js = (UI / "static" / "app.js").read_text()
    assert (
        "if (checkList) checkList.innerHTML = checks.map(" in js and "if (closeBtn) { closeBtn.disabled = !ready;" in js
    )
    assert 'if (readyCard && v.state === "closed") readyCard.remove();' in js
