"""A tool with no permission channel (design §4.3 *Permissions: no channel*, §4.5a **Allow / Deny**,
TD-785 slice 1): the view carries `permission_channel`, a pending permission of such a tool is drawn
with its text and *answer it in the terminal* and no Allow / Deny, `ao allow`/`ao deny` and the page
refuse it in words, the `decide` RPC refuses it as the backstop, and no manager seat is filled for it.
And `confidence: title` (§4.2 *A title the tool writes its state into*) counts as hook-confirmed."""

import argparse

import pytest
from _stubs import HookFedStub

from sessionorc import adapters
from sessionorc.client import AgentError, LocalClient
from sessionorc.models import Pending, Session, attention_kind
from shiftlead import cli
from shiftlead.ui import inbox
from shiftlead.ui.cards import answerable, terminal_only

PERM = {"kind": "permission", "text": "Shell: rm -rf build", "tool_use_id": "tu-1"}


class NoChannelStub(HookFedStub):
    name = "nochannel"
    permission_channel = False


@pytest.fixture
def nochannel(monkeypatch):
    adapters.load_all()
    monkeypatch.setitem(adapters._REGISTRY, NoChannelStub.name, NoChannelStub())


@pytest.mark.unit
def test_the_adapter_says_whether_its_permission_has_a_channel(nochannel):
    """`permission_channel`, True where unset (the test stubs), False for `shell` and a tool without
    one; an adapter this host does not know is taken at the default, as `has_agent` is."""
    assert adapters.permission_channel("claude-code") is True
    assert adapters.permission_channel("hookstub") is True
    assert adapters.permission_channel("shell") is False
    assert adapters.permission_channel("nochannel") is False
    assert adapters.permission_channel("no-such-tool") is True


@pytest.mark.unit
@pytest.mark.parametrize(("confidence", "told"), [("hook", True), ("title", True), ("scraped", False), ("tick", False)])
def test_a_title_reading_is_the_tools_own_word(confidence, told):
    """§4.2: every rule that acts only on a hook-confirmed state takes a title reading as one."""
    s = Session(id="ao-g", name="g", kind="interactive", adapter="hookstub", dir="/r", state="idle")
    s.set_state("idle", confidence=confidence)
    assert s.told is told
    assert "told" not in s.to_dict()  # derived, never stored


@pytest.mark.unit
def test_a_permission_only_the_terminal_answers_is_a_question_row(nochannel):
    """The home's and the page's `state_kind` agree: a permission of a tool with no channel is a
    question row, its text saying *answer it in the terminal*, and never an Allow / Deny."""
    rec = Session(id="ao-g", name="g", kind="interactive", adapter="nochannel", dir="/r", state="needs-you")
    rec.pending = Pending.from_dict(PERM)
    assert attention_kind(rec) == "question"
    rec.adapter = "hookstub"
    assert attention_kind(rec) == "permission"

    view = {"id": "ao-g", "name": "g", "state": "needs-you", "pending": PERM, "permission_channel": False}
    assert inbox.state_kind(view) == "question"
    assert not answerable(view) and terminal_only(view) == " — answer it in the terminal"
    assert inbox.state_kind({**view, "permission_channel": True}) == "permission"
    assert inbox.state_kind({k: v for k, v in view.items() if k != "permission_channel"}) == "permission"
    assert (
        answerable({**view, "permission_channel": True}) and terminal_only({**view, "permission_channel": True}) == ""
    )
    question = {**view, "pending": {"kind": "question", "text": "which branch?"}}
    assert terminal_only(question) == ""  # a question is the terminal's already, and says so as it did


@pytest.mark.unit
def test_the_card_draws_the_text_and_focus_with_no_allow(tmp_path, monkeypatch):
    """The card: no Allow / Deny, no countdown caption; its slot says *answer it in the terminal*."""
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    from shiftlead.ui.app import templates, view

    rec = {
        "id": "ao-g",
        "name": "g",
        "kind": "agent",
        "adapter": "gemini",
        "dir": "/r",
        "state": "needs-you",
        "since": "2026-10-17T01:00:00Z",
        "confidence": "hook",
        "pane": True,
        "pending": PERM,
        "permission_channel": False,
    }
    d = view(rec)
    assert d["next_act"] == "focus" and d["slot"]["caption"] != "via hook"
    assert d["slot"]["text"] == "Shell: rm -rf build — answer it in the terminal"
    html = templates.get_template("card.html").render(s=d)
    assert 'data-act="allow"' not in html and "/focus/ao-g" in html
    with_channel = view({**rec, "permission_channel": True})
    assert with_channel["next_act"] == "allow" and with_channel["slot"]["caption"] == "via hook"


@pytest.mark.unit
def test_ao_allow_refuses_in_words_before_any_call(monkeypatch, capsys):
    """`ao allow`/`ao deny` read the view's `permission_channel` and refuse before `decide` is called."""
    calls = []

    def call_sync(method, **kw):
        calls.append(method)
        return {"id": "ao-g", "state": "needs-you", "pending": PERM, "permission_channel": False}

    monkeypatch.setattr(cli, "call_sync", call_sync)
    args = argparse.Namespace(id="ao-g", behavior="allow", reason=None, json=False)
    assert cli.cmd_decide(args) == 1
    assert calls == ["get"]
    assert "answer it in the terminal" in capsys.readouterr().err


@pytest.mark.integration
async def test_decide_refuses_a_tool_with_no_channel(agent, nochannel, tmp_path):
    """The `decide` RPC is the backstop: refused in the same words, whatever the record's pending."""
    async with LocalClient() as person:
        s = await person.call("create", name="g", dir=str(tmp_path), adapter="nochannel")
        assert (await person.call("get", id=s["id"]))["permission_channel"] is False
        with pytest.raises(AgentError, match="answer it in the terminal"):
            await person.call("decide", id=s["id"], tool_use_id="tu-1", behavior="allow")
        await person.call("kill", id=s["id"])


@pytest.mark.integration
async def test_only_a_permission_with_a_channel_is_a_manager_on_calls_cause(agent, hookstub, nochannel, tmp_path):
    """§6 rule 3: a member's hook-confirmed permission is the on-call manager's `pending` cause only
    where a hook can answer it; the same pending of a tool with no channel is the terminal's (TD-840)."""
    async with LocalClient() as person:
        mgr = await person.call("create", name="mgr", dir=str(tmp_path), adapter="hookstub", seat={"trigger": "team"})
        ids = {}
        for ad in ("hookstub", "nochannel"):
            (tmp_path / ad).mkdir()
            ids[ad] = (
                await person.call("create", name=ad, dir=str(tmp_path / ad), adapter=ad, controllers=[mgr["id"]])
            )["id"]
        for sid in ids.values():
            agent.sessions[sid].supervised = True
            agent.sessions[sid].set_state("needs-you", confidence="hook", pending=Pending.from_dict(PERM))
        records = list(agent.sessions.values())
        causes = agent._team_causes(agent.sessions[mgr["id"]], records)
        assert [(c["by"], c["member"]) for c in causes] == [
            ("pending", agent._address(agent.sessions[ids["hookstub"]]))
        ]
        for sid in (mgr["id"], *ids.values()):
            await person.call("kill", id=sid)


@pytest.mark.unit
def test_the_page_refuses_allow_for_a_tool_with_no_channel(tmp_path, monkeypatch):
    """The page's Allow / Deny route answers 409 in words before any `decide` (TD-840)."""
    from fastapi.testclient import TestClient

    from shiftlead.ui import app as uiapp

    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path))
    calls = []
    record = {"id": "ao-g", "state": "needs-you", "pending": PERM, "permission_channel": False}

    class Fake:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def call(self, method, **kw):
            calls.append(method)
            return record if method == "get" else {}

    monkeypatch.setattr(uiapp, "LocalClient", Fake)
    with TestClient(uiapp.create_app()) as c:
        for act in ("allow", "deny"):
            r = c.post(f"/api/sessions/ao-g/{act}", json={})
            assert r.status_code == 409 and "answer it in the terminal" in r.json()["detail"]
        assert "decide" not in calls
        record["permission_channel"] = True
        assert c.post("/api/sessions/ao-g/allow", json={}).status_code == 200 and "decide" in calls


@pytest.mark.unit
def test_answer_needed_says_answer_it_in_the_terminal(tmp_path, monkeypatch):
    """The team card's **Answer needed** facet: a no-channel member's permission reads *— answer it in
    the terminal* after its text; one with a channel reads its text alone (TD-840)."""
    from shiftlead.ui.org import answer_blocks

    m = {"id": "ao-g", "name": "g", "state": "needs-you", "pending": PERM, "permission_channel": False}
    [row] = answer_blocks([m])
    assert row["text"] == "Shell: rm -rf build — answer it in the terminal"
    [row] = answer_blocks([{**m, "permission_channel": True}])
    assert row["text"] == "Shell: rm -rf build"


@pytest.mark.integration
async def test_a_permission_answered_in_the_terminal_leaves_the_stack(agent, nochannel, tmp_path):
    """§4.2 *Open prompts are a stack*, §4.3 *Permissions: no channel* (TD-786, the live walk on 0.65.0): a
    permission of a tool with no channel has no waiter to end it, so the main thread's next event — the asked
    call's `AfterTool` once the person answered in the terminal — removes it, as it removes a question."""
    async with LocalClient() as person:
        s = await person.call("create", name="g", dir=str(tmp_path), adapter="nochannel")
        sid = s["id"]
        agent._apply_event(sid, {"state": "working", "pending": None, "event": "BeforeTool:run_shell_command"})
        agent._apply_event(sid, {"state": "needs-you", "pending": {"kind": "permission", "text": "Shell: touch x"}})
        rec = await person.call("get", id=sid)
        assert (rec["state"], rec["pending"]["kind"]) == ("needs-you", "permission")
        agent._apply_event(sid, {"state": "working", "pending": None, "event": "AfterTool:run_shell_command"})
        rec = await person.call("get", id=sid)
        assert (rec["state"], rec["pending"], agent.sessions[sid].pendings) == ("working", None, [])
        agent._apply_event(sid, {"state": "idle", "pending": None})
        assert (await person.call("get", id=sid))["state"] == "idle"
        await person.call("kill", id=sid)
