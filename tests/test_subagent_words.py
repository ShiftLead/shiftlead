"""A subagent's prompt in words (design §4.2 *A subagent's dialog is held back*, §4.5a **Allow / Deny**,
TD-950 slice 4a): while the pane draws nothing for it (`pane_held`), the card, the Inbox row, the team
facet and Focus say *from the <name> subagent · the pane shows nothing until <deadline>*, the deadline in
the reader's clock; after the fall-through *from the <name> subagent*; a main-thread prompt draws as it
did. A send is refused with the held words, and `ao status` / `ao explain` name the subagent."""

from pathlib import Path

import pytest

from sessionorc.client import AgentError, LocalClient
from sessionorc.models import Pending
from shiftlead import cli
from shiftlead.ui.cards import held_words, subagent_held

DEADLINE = "2026-10-22T09:15:00Z"
HELD = {
    "kind": "permission",
    "text": "Bash: ls",
    "tool_use_id": "tu-1",
    "deadline": DEADLINE,
    "subagent": "a1",
    "subagent_name": "general-purpose",
    "pane_held": True,
}
FELL = {"kind": "question", "text": "Bash: ls", "subagent": "a1", "subagent_name": "general-purpose"}
MAIN = {"kind": "permission", "text": "Bash: ls", "tool_use_id": "tu-1", "deadline": DEADLINE}


def _rec(pend):
    return {
        "id": "ao-w",
        "name": "w",
        "kind": "agent",
        "adapter": "hookstub",
        "dir": "/r",
        "state": "needs-you",
        "since": "2026-10-22T09:00:00Z",
        "confidence": "hook",
        "pane": True,
        "pending": pend,
    }


@pytest.mark.unit
def test_the_held_reading_and_its_words():
    assert subagent_held(HELD) == {"name": "general-purpose", "deadline": DEADLINE}
    assert subagent_held(FELL) == {"name": "general-purpose", "deadline": ""}
    assert subagent_held(MAIN) is None and subagent_held(None) is None
    assert held_words(subagent_held(HELD), "09:15") == (
        "from the general-purpose subagent · the pane shows nothing until 09:15"
    )
    assert held_words(subagent_held(FELL)) == "from the general-purpose subagent"
    assert held_words(None) == ""


@pytest.mark.unit
def test_the_card_draws_the_held_line_and_the_fall_through(tmp_path, monkeypatch):
    """The card keeps its buttons and countdown, and draws the held line under the slot's text, the
    deadline a `.localtime` the page writes in the reader's clock; the fall-through's line has no
    deadline and sits beside Focus; a main-thread prompt has no line."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import templates, view

    d = view(_rec(HELD))
    assert d["next_act"] == "allow" and d["held"] == {"name": "general-purpose", "deadline": DEADLINE}
    assert "the pane shows nothing until" in d["slot"]["full"]
    html = templates.get_template("card.html").render(s=d)
    assert 'data-act="allow"' in html and "from the general-purpose subagent · the pane shows nothing until" in html
    assert f'class="localtime" data-at="{DEADLINE}"' in html

    d = view(_rec(FELL))
    assert d["next_act"] != "allow" and d["held"] == {"name": "general-purpose", "deadline": ""}
    html = templates.get_template("card.html").render(s=d)
    assert "from the general-purpose subagent</div>" in html and "pane shows nothing" not in html

    d = view(_rec(MAIN))
    assert d["held"] is None
    assert "subagent" not in templates.get_template("card.html").render(s=d)
    assert view({**_rec(HELD), "state": "idle"})["held"] is None  # only a needs-you draws it


@pytest.mark.unit
def test_the_inbox_row_and_the_team_facet_draw_the_same_line(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui import inbox
    from shiftlead.ui.app import templates, view
    from shiftlead.ui.org import answer_blocks

    [row] = inbox.state_rows([view(_rec(HELD))])
    assert row["row"] == "permission" and row["held"] == {"name": "general-purpose", "deadline": DEADLINE}
    html = templates.get_template("inbox_rows.html").render(rows=[row], section="now")
    assert "the pane shows nothing until" in html and 'data-act="allow"' in html
    [row] = inbox.state_rows([view(_rec(FELL))])
    assert row["row"] == "question" and row["held"] == {"name": "general-purpose", "deadline": ""}
    [row] = inbox.state_rows([view(_rec(MAIN))])
    assert row["held"] is None

    [block] = answer_blocks([_rec(HELD)])
    assert block["held"] == {"name": "general-purpose", "deadline": DEADLINE}
    assert answer_blocks([_rec(MAIN)])[0]["held"] is None


@pytest.mark.unit
def test_focus_draws_the_held_line():
    """Focus's header, in `app.js`, draws `held_line.html`'s words from the view's `held`."""
    js = (Path(cli.__file__).parent / "ui" / "static" / "app.js").read_text()
    assert "v.held" in js and 'the pane shows nothing until <span class="localtime"' in js


@pytest.mark.unit
def test_ao_status_and_explain_name_the_subagent(capsys):
    assert cli.pending_words(HELD) == "  ← permission: Bash: ls (from the general-purpose subagent)"
    assert cli.pending_words(MAIN) == "  ← permission: Bash: ls"
    assert cli.pending_words(None) == "" and cli.pending_words({}) == ""
    rec = {**_rec(HELD), "adapter": "claude-code", "since": "2026-10-22T09:00:00Z"}
    assert cli.status_line(rec).endswith("(from the general-purpose subagent)")
    cli._print_explanation({**rec, "reason": "a hook said so"})
    assert "(from the general-purpose subagent)" in capsys.readouterr().out.splitlines()[0]


@pytest.mark.integration
async def test_a_send_to_a_held_record_is_refused_with_the_held_words(agent, hookstub, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="w", dir=str(tmp_path), adapter="hookstub"))["id"]
        s = agent.sessions[sid]
        s.state, s.pending = "needs-you", Pending.from_dict(HELD)
        with pytest.raises(AgentError, match=r"a subagent's permission is pending: press Allow / Deny \(the pane"):
            await c.call("send", id=sid, text="hi")
        s.pending = Pending.from_dict(MAIN)
        with pytest.raises(AgentError, match="answer it in the terminal"):
            await c.call("send", id=sid, text="hi")
        await c.call("kill", id=sid)
