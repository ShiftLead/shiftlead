"""Every open prompt is answerable where it is drawn (design §4.2, §4.5a **Allow / Deny**, TD-950 slice
4b): the card and Focus draw a line per entry under the newest, each permission with its own **Allow** /
**Deny** naming its call, each question with Focus; the team facet a block per entry, *n* counting
members; the Inbox row the newest; `ao allow` / `ao deny` and the page answer the newest *permission*
entry, `--call` (the page's `call`) another; and an idle main thread held only by a subagent's prompt
reads *rung on the restore to idle*, and is the doorbell's again once the prompt ends (§4.10)."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest
from test_claude_adapter import _feed
from test_prompt_stack import STOP, _ask

from sessionorc import mail
from sessionorc.client import LocalClient
from sessionorc.models import open_prompts, permission_entry
from shiftlead import cli

HELD = {
    "kind": "permission",
    "text": "Bash: ls",
    "tool_use_id": "tu-s",
    "deadline": "2026-10-22T09:15:00Z",
    "subagent": "a1",
    "subagent_name": "general-purpose",
    "pane_held": True,
}
MAIN = {"kind": "permission", "text": "Bash: rm x", "tool_use_id": "tu-m", "deadline": "2026-10-22T09:16:00Z"}
ASK = {"kind": "question", "text": "Which branch?"}


def _rec(*pends, **kw):
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
        "pendings": list(pends),
        "pending": pends[-1] if pends else None,
        **kw,
    }


@pytest.mark.unit
def test_the_entry_an_answer_takes():
    rec = _rec(HELD, MAIN, ASK)
    assert [p["text"] for p in open_prompts(rec)] == ["Which branch?", "Bash: rm x", "Bash: ls"]
    assert permission_entry(rec) == MAIN  # the newest permission, never the question on top
    assert permission_entry(rec, "tu-s") == HELD and permission_entry(rec, "tu-nope") is None
    assert permission_entry(_rec(ASK)) is None
    older = {"state": "needs-you", "pending": MAIN}  # a record of an older build: its one pending
    assert open_prompts(older) == [MAIN] and permission_entry(older) == MAIN


@pytest.mark.unit
def test_the_card_draws_a_line_per_entry_each_answering_its_own_call(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import templates, view

    d = view(_rec(HELD, MAIN))
    assert d["slot"]["text"] == "Bash: rm x" and [o["call"] for o in d["others"]] == ["tu-s"]
    assert d["others"][0]["answerable"] and d["others"][0]["held"]["name"] == "general-purpose"
    html = templates.get_template("card.html").render(s=d)
    assert html.count('data-act="allow"') == 2
    assert 'data-call="tu-m">Allow' in html and 'data-call="tu-s" data-line>Allow' in html
    assert "the pane shows nothing until" in html

    d = view(_rec(HELD, ASK))  # a question on top: its Focus, and the permission's buttons under it
    assert d["next_act"] != "allow" and d["others"][0]["call"] == "tu-s"
    html = templates.get_template("card.html").render(s=d)
    assert html.count('data-act="allow"') == 1 and 'data-call="tu-s"' in html

    d = view(_rec(ASK, HELD))  # a question beneath: drawn with Focus, no buttons
    assert d["others"] == [
        {
            "kind": "question",
            "text": "question: Which branch?",
            "call": "",
            "answerable": False,
            "deadline": "",
            "held": None,
        }
    ]
    assert view(_rec(MAIN))["others"] == []


@pytest.mark.unit
def test_focus_draws_the_others_with_their_calls():
    from pathlib import Path

    js = (Path(cli.__file__).parent / "ui" / "static" / "app.js").read_text()
    assert "(v.others || []).map(" in js and 'data-call="${esc(o.call)}"' in js
    assert "b.dataset.call) body.call = b.dataset.call" in js
    # the card's `a` / `d` keys answer the slot's prompt, never a line beneath it (review of 4b)
    assert js.count(""":not([data-line])' },""") == 2


@pytest.mark.unit
def test_the_facet_draws_a_block_per_entry_and_counts_members(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui import inbox
    from shiftlead.ui.app import view
    from shiftlead.ui.org import answer_blocks, answer_members

    blocks = answer_blocks([_rec(HELD, MAIN), {**_rec(ASK), "id": "ao-v", "name": "v"}])
    assert [(b["id"], b["kind"], b["call"]) for b in blocks] == [
        ("ao-w", "permission", "tu-m"),
        ("ao-w", "permission", "tu-s"),
        ("ao-v", "question", ""),
    ]
    assert blocks[1]["text"] == "Bash: ls" and blocks[1]["held"]["name"] == "general-purpose"
    assert answer_members(blocks) == 2
    [row] = inbox.state_rows([view(_rec(HELD, MAIN))])  # the Inbox row keeps the newest, and names its call
    assert row["text"] == "Bash: rm x" and row["call"] == "tu-m"
    from shiftlead.ui.app import templates

    html = templates.get_template("inbox_rows.html").render(rows=[row], section="now")
    assert 'data-call="tu-m">Allow' in html

    from shiftlead.ui.org import rollup, team_summary

    members = [view(_rec(HELD, MAIN)), view({**_rec(ASK), "id": "ao-v", "name": "v"})]
    summ = team_summary("t", members, {}, {})
    assert len(summ["answers"]) == 3 and summ["n_answer"] == 2
    assert summ["answer_key"] == "ao-v:question ao-w:permission ao-w:permission"  # a block per entry
    assert rollup(None, members)["answer_needed"] == 2


@pytest.mark.unit
def test_ao_allow_answers_the_newest_permission_or_the_call_named(monkeypatch, capsys):
    calls = []

    def call_sync(method, **kw):
        calls.append((method, kw))
        return _rec(HELD, MAIN, ASK) if method == "get" else None

    monkeypatch.setattr(cli, "call_sync", call_sync)
    args = argparse.Namespace(id="ao-w", behavior="allow", reason=None, json=False, call=None)
    assert cli.cmd_decide(args) == 0 and calls[-1][1]["tool_use_id"] == "tu-m"
    assert cli.cmd_decide(argparse.Namespace(**{**vars(args), "call": "tu-s"})) == 0
    assert calls[-1][1]["tool_use_id"] == "tu-s"
    assert cli.cmd_decide(argparse.Namespace(**{**vars(args), "call": "tu-x"})) == 1
    assert "no pending permission with call tu-x" in capsys.readouterr().err
    p = cli.build_parser().parse_args(["deny", "ao-w", "--call", "tu-s", "not now"])
    assert p.call == "tu-s" and p.reason == "not now"


@pytest.mark.unit
def test_the_page_answers_the_entry_its_line_names(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from shiftlead.ui import app as uiapp

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    decided = []

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            if method == "decide":
                decided.append(kw["tool_use_id"])
            return _rec(HELD, MAIN, ASK) if method == "get" else {}

    monkeypatch.setattr(uiapp, "LocalClient", Fake)
    with TestClient(uiapp.create_app()) as c:
        assert c.post("/api/sessions/ao-w/allow", json={}).status_code == 200
        assert c.post("/api/sessions/ao-w/deny", json={"call": "tu-s", "reason": "no"}).status_code == 200
        assert c.post("/api/sessions/ao-w/allow", json={"call": "tu-x"}).status_code == 409
    assert decided == ["tu-m", "tu-s"]


@pytest.mark.integration
async def test_an_idle_thread_held_by_a_subagent_is_rung_on_the_restore(agent, hookstub, tmp_path):
    """§4.10's `needs-you` row: only a subagent's prompt over an idle main thread reads *rung on the
    restore to idle*; once its Allow ends it, the record is hook-confirmed idle — the doorbell's again."""
    now = datetime.now(UTC)
    async with LocalClient() as c:
        sid = (await c.call("create", name="r", dir=str(tmp_path), adapter=hookstub.name, unattended=True))["id"]
        await _feed(agent, c, sid, [STOP])
        task, tid = await _ask(agent, c, sid, "one", "s1")
        s = agent.sessions[sid]
        assert s.state == "needs-you" and agent._bell_blocked(s, now) == "not hook-confirmed idle"
        assert mail.read_when(s, "note", now).startswith("rung on the restore to idle")
        await c.call("decide", id=sid, tool_use_id=tid, behavior="allow")
        await task
        s = agent.sessions[sid]
        assert s.state == "idle" and s.told and agent._bell_blocked(s, now) != "not hook-confirmed idle"
        assert not mail.read_when(s, "note", now).startswith("rung on the restore")

        task, tid = await _ask(agent, c, sid, "two")  # a main-thread prompt reads as it did
        assert mail.read_when(agent.sessions[sid], "note", now).startswith("read once its permission")
        await c.call("decide", id=sid, tool_use_id=tid, behavior="allow")
        await task
