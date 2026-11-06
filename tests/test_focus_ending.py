"""The ending banner on Focus (design §4.5 *The Focus screen's anatomy* item 3, §4.5a *Focus (exited / closed)*;
TD-964's slice 1, built by TD-1405): one line of the ending's words and the buttons, the guess at the cause only
where the record does not name the ending, the grey text moved into the **i** panel, Restart where the card draws
it, no composer on an ended record and no retry line for a pane the page knows is gone."""

from __future__ import annotations

import pathlib
import re

import pytest

from shiftlead.ending import ending_unnamed

JS = pathlib.Path(__file__).resolve().parents[1] / "src" / "shiftlead" / "ui" / "static" / "app.js"
AT = "2026-11-05T12:31:00Z"

REC = {
    "id": "ao-x-designer",
    "name": "designer-ao-1",
    "kind": "agent",
    "adapter": "claude-code",
    "adapter_id": "s1",
    "dir": "/r/wt",
    "repo": "/r",
    "state": "exited",
    "since": "2026-09-25T16:12:00Z",
    "created": "2026-09-25T16:00:00Z",
    "confidence": "hook",
}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("rec", "unnamed"),
    [
        ({"state": "exited"}, True),  # no `ended`: bare *exited*
        ({"state": "exited", "ended": {"how": "pane", "code": 1, "at": AT}}, False),  # *exited · code 1*
        ({"state": "exited", "ended": {"how": "tool", "reason": "prompt_input_exit", "at": AT}}, False),
        ({"state": "exited", "ended": {"how": "kill", "by": "person", "at": AT}}, False),  # *killed by you*
        ({"state": "exited", "ended": {"how": "kill", "at": AT}}, True),  # a kill with no killer: bare *killed*
        ({"state": "exited", "ended": {"how": "gone", "found": AT}}, True),  # *pane gone · found …*
        ({"state": "exited", "ended": {"at": AT}, "wrapup_at": "2026-11-05T12:00:00Z"}, True),  # *· after wrap-up*
        ({"state": "closed", "closed_at": AT}, True),  # a close whose closer is not recorded: bare *closed*
        ({"state": "closed", "closed_at": AT, "closer": {"by": "person"}}, False),  # *closed by you*
        ({"state": "idle"}, False),
    ],
)
def test_the_cause_is_guessed_only_where_the_record_does_not_name_the_ending(rec, unnamed):
    assert ending_unnamed(rec) is unnamed


def _focus(tmp_path, monkeypatch, **rec):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import templates, view

    v = view({**REC, **rec})
    return v, templates.get_template("focus.html").render(s={**v, "grants_all": []}, host="h", active="Sessions")


@pytest.mark.unit
def test_an_ended_record_draws_no_composer_and_carries_whether_its_ending_is_named(tmp_path, monkeypatch):
    for state in ("exited", "closed"):
        v, html = _focus(tmp_path, monkeypatch, state=state, closed_at=AT)
        assert re.search(r'class="card composerbar[^"]* hidden"', html), state
        assert re.search(r'<div class="card composer[^"]* hidden" id="composer"', html), state
        assert v["ending_unnamed"] is True, "neither names its ending"
    v, html = _focus(tmp_path, monkeypatch, state="idle")
    assert not re.search(r'class="card composerbar[^"]* hidden"', html), "a live attended session keeps its composer"
    v, _ = _focus(tmp_path, monkeypatch, state="exited", ended={"how": "kill", "by": "person", "at": AT})
    assert v["ending_unnamed"] is False and v["ending_text"].startswith("killed by you")


@pytest.mark.unit
def test_the_i_panel_holds_what_was_grey_text_and_names_the_banners_five_controls(tmp_path, monkeypatch):
    _, html = _focus(tmp_path, monkeypatch, state="closed", closed_at=AT)
    panel = html[html.index('id="help-exited"') :]
    panel = panel[: panel.index("</div>")]
    assert "A closed record is forgotten by itself a day after the close" in panel
    assert 'id="fmemberback"' in panel and "Restart puts it back in its team's run" in panel
    for name in ("Resume", "Resume with changes…", "New session here", "Forget", "Restart"):
        assert f"<b>{name}</b>" in panel, name


@pytest.mark.unit
def test_the_banner_is_the_endings_words_and_its_buttons_with_restart_where_the_card_has_it():
    js = JS.read_text()
    banner = js[js.index("The ending banner (§4.5") : js.index('} else ex.classList.add("hidden");')]
    assert '<b class="endwords">${esc(words)}</b>${guess}' in banner
    assert "v.ending_unnamed && gone" in banner, "the guess only where the record does not name the ending"
    for gone in ("The pane is kept", "read its transcript", "This session's process has", "memberback\">To put"):
        assert gone not in banner, gone
    assert "v.restartable" in banner and 'data-act="restart"' in banner and "v.restart_marked" in banner
    assert 'data-confirm="Restart ${esc(v.name || id)}? It is closed if still there' in banner


@pytest.mark.unit
def test_no_retry_line_for_a_pane_the_page_knows_is_gone_and_no_composer_once_ended():
    js = JS.read_text()
    onclose = js[js.index("ws.onclose = (e) => {") :]
    onclose = onclose[: onclose.index("retry = setTimeout(openTerm, delay)")]
    assert onclose.index('if (AO.paneIsGone(lastV)) { endTerm(""); return; }') < onclose.index("retrying in")
    assert "if (text) term.write(" in js, "an end with no words writes no line"
    assert 'const noComposer = !!v.unattended || v.state === "exited" || v.state === "closed";' in js
