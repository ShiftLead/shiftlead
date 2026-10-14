"""The pages of a record with no agent (design §4.3 *A record with no agent*, §4.5a *Focus, card: A record
with no agent*, TD-665, built by TD-666 slice 2): every control the row names reads the view's `agent`,
never an adapter's name — Wrap up, Message, the mode toggle, Reports, Inbox, Working, Told at start, the
grants and controllers chips, the adapter id, context and rounds lines and the Ready to close card are
not drawn on a shell; the composer reads *Type a command…*, Send never *Steer*; Close is offered without
the checks, confirming that the shell is killed and the directory left as it is."""

from __future__ import annotations

import pathlib

import pytest
from test_ui import client, wait_state  # noqa: F401 — the fixture, by name

from shiftlead.ui import cards

UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "shiftlead" / "ui"

REC = {
    "id": "ao-r-sh", "name": "sh", "kind": "interactive", "adapter": "shell", "dir": "/tmp/x",
    "state": "idle", "since": "2026-10-14T08:00:00Z", "confidence": "scraped", "tail": [],
    "git": {"branch": "w", "dirty": 3, "unpushed": 2, "files": []},
}  # fmt: skip


@pytest.mark.unit
def test_the_view_of_a_record_with_no_agent_draws_no_checks_and_no_mode_toggle():
    v = cards.view({**REC, "agent": False})
    assert v["agent"] is False
    # no checklist: a dirty tree is the shell's directory, not its work — Close needs no checks
    assert v["ready"] == [] and v["ready_ok"] and v["not_ready"] == []
    assert v["close_confirm"] == "Close sh? The shell is killed; the directory is left as it is."
    assert v["mode_act"] == "" and v["mode_title"] == ""
    assert v["slot"]["caption"] != "ready to close ✓"
    # an agent's view, and one built without the field (an older host), keep every control
    for rec in ({**REC, "adapter": "claude-code", "agent": True}, {**REC, "adapter": "claude-code"}):
        a = cards.view(rec)
        assert a["agent"] is True and a["mode_act"] == "Switch to unattended"
        assert ("tree clean", False) in a["ready"] and not a["ready_ok"]
        assert a["close_confirm"] == "Close sh? It is killed and its worktree reaped."


@pytest.mark.unit
def test_the_card_of_a_shell_draws_no_message_wrap_up_or_mode_toggle(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import templates

    card = templates.get_template("card.html")
    ctx = {"tokens": 50_000, "at": "2026-10-14T08:00:00Z", "window": 1_000_000}
    shell = card.render(s=cards.view({**REC, "agent": False, "context": ctx}))
    agent = card.render(s=cards.view({**REC, "adapter": "claude-code", "agent": True, "context": ctx}))
    for word in ('data-act="wrapup"', 'data-act="message"', 'data-act="mode"', 'class="context'):
        assert word not in shell, word
        assert word in agent, word
    # Close is enabled without the checks, with the shell's confirm; Kill and Open shell here stay
    assert 'data-confirm="Close sh? The shell is killed; the directory is left as it is."' in shell
    assert "not ready to close" not in shell and "not ready to close" in agent
    assert 'data-act="kill"' in shell and 'data-act="shell-here"' in shell
    # the foot's next act on an idle shell is Close session, confirming as more ▾'s does
    assert 'class="btn sm next" data-act="close" data-id="ao-r-sh" data-confirm="Close sh? The shell' in shell


def test_focus_of_a_shell_draws_a_shells_controls_and_an_agents_draws_its_own(client, tmp_path):  # noqa: F811
    (tmp_path / "s").mkdir()
    (tmp_path / "a").mkdir()
    r = client.post("/new", data={"name": "sh", "dir": str(tmp_path / "s"), "adapter": "shell"}, follow_redirects=False)
    shell = r.headers["location"].rsplit("/", 1)[-1]
    form = {"name": "ag", "dir": str(tmp_path / "a"), "adapter": "hookstub"}
    r = client.post("/new", data=form, follow_redirects=False)
    agent = r.headers["location"].rsplit("/", 1)[-1]
    try:
        wait_state(client, shell, "idle")
        sh, ag = client.get(f"/focus/{shell}").text, client.get(f"/focus/{agent}").text
        absent = (
            'data-act="wrapup"', 'data-act="message"', 'id="fmodeact"', 'id="fmodemenu"', 'id="fready"',
            'id="workingcard"', 'id="reportscard"', 'id="inboxcard"', 'data-side="ready"', 'id="adapter_id"',
            'id="fgrants"', 'id="fcontrollers"', "Compose a prompt…",
        )  # fmt: skip
        for word in absent:
            assert word not in sh, word
            assert word in ag, word
        assert 'placeholder="Type a command…"' in sh and "✎ Type a command…" in sh
        # Close session is on the acts line of a live shell, and more ▾'s Close is enabled, both
        # confirming the shell's words; Kill and Open shell here stay
        confirm = 'data-confirm="Close sh? The shell is killed; the directory is left as it is."'
        acts = sh[sh.index('id="fclose"') - 40 : sh.index('id="fclose"') + 200]
        assert "hidden" not in acts.split('id="fclose"')[0] and confirm in acts
        menu = sh[sh.index('id="fclosemenu"') :]
        assert confirm in menu[:200] and "disabled" not in menu[: menu.index(">")]
        assert 'data-act="kill"' in sh and 'data-act="shell-here"' in sh
        # Wrap up and Message on the agent's page, and its acts line holds Close back for the checks
        assert 'data-confirm="Close ag? It is killed and its worktree reaped."' in ag
    finally:
        for sid in (shell, agent):
            client.post(f"/api/sessions/{sid}/kill")


@pytest.mark.unit
def test_focus_renders_a_shell_from_the_view_without_the_agents_cards():
    js = (UI / "static" / "app.js").read_text()
    render = js[js.index("    function render(v) {") :]
    render = render[: render.index("\n    }\n")]
    # Send never steers a shell, and the hint says what Send does to one
    assert "const steering = agent && (" in render and '"types the line and presses Enter"' in render
    # Reports and Inbox are not read for it, and the checks give way to Close on any live state
    assert "if (v.agent !== false) { renderReports(v); renderInbox(v); }" in render
    assert 'const now = v.pane !== false && !["closed", "scheduled"].includes(v.state);' in render
    assert 'const aid = $("#adapter_id"); if (aid)' in render
    # the page's other readers of the cards a shell lacks are guarded
    assert 'if (!$("#inboxcard")) return;' in js
    assert 'reports: txt($("#reportscount"))' in js
