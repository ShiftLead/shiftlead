"""The record's `prompts` (design §4.2 *The record's `prompts`*, §4.3 `prompts`, TD-976): Claude Code's read
of its transcript, the merge that gives each prompt its sender, the tick that runs it, and the view."""

from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import UTC, datetime

import pytest
from conftest import park_ticks

from sessionorc import adapters, mail
from sessionorc.adapters import Prompt
from sessionorc.agent_tick import merge_prompts
from sessionorc.client import LocalClient
from sessionorc.models import NODE_OWNED, PERSON, RECENT_PROMPTS, SYSTEM, SendEntry, Session
from shiftlead.adapters.claude_code import transcript as transcript_mod

FIXTURE = pathlib.Path(__file__).parent / "conformance" / "fixtures" / "claude-code" / "transcripts" / "prompts.jsonl"


def _user(at: str, content, **extra) -> dict:
    return {"type": "user", "timestamp": at, "message": {"content": content}, **extra}


def _text(at: str, text: str, **extra) -> dict:
    return {"type": "assistant", "timestamp": at, "message": {"content": [{"type": "text", "text": text}]}, **extra}


def _write(path: pathlib.Path, entries: list[dict], mode: str = "w") -> None:
    with path.open(mode) as f:
        f.write("".join(json.dumps(e) + "\n" for e in entries))


def _send(i: int, sender: str, text: str, at: str) -> SendEntry:
    return SendEntry(id=f"s-{i}", from_=sender, at=at, text=text)


# -- Claude Code's read -------------------------------------------------------------------------------


@pytest.mark.unit
def test_the_read_leaves_out_what_no_person_typed_and_draws_a_slash_command_as_typed(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(
        p,
        [
            _user("T1", "first prompt"),
            _user("T2", "<local-command-caveat>Caveat: …</local-command-caveat>", isMeta=True),
            _user(
                "T3",
                "<command-name>/simplify</command-name>\n<command-message>simplify</command-message>\n"
                "<command-args>the parser</command-args>",
            ),
            _user("T4", "<local-command-stdout>done</local-command-stdout>"),
            _user("T5", [{"type": "text", "text": "[Request interrupted by user]"}]),
            _user("T6", [{"type": "text", "text": "[Request interrupted by user for tool use]"}]),
            _user("T7", "<task-notification>\n<task-id>b1</task-id>\n</task-notification>"),
            _user("T8", "<system-reminder>\nthe date changed\n</system-reminder>"),
            _user("T9", "summary of what came before", isCompactSummary=True),
            _user("T10", [{"type": "tool_result", "content": "ok"}]),
            _user("T11", "a subagent's prompt", isSidechain=True),
            _user("T12", "typed\n<system-reminder>\nappended\n</system-reminder>"),
            _user("T13", "plain text the tool wrote", isMeta=True),
        ],
    )
    found, leading, cursor = transcript_mod.prompts(p)
    assert [x.text for x in found] == ["first prompt", "/simplify the parser", "typed"]
    assert [x.drawn for x in found] == ["❯ first prompt", "❯ /simplify the parser", "❯ typed"]
    assert leading is None and cursor == p.stat().st_size


@pytest.mark.unit
def test_the_read_cuts_text_at_300_and_drawn_at_40_marking_a_whole_line(tmp_path):
    p = tmp_path / "t.jsonl"
    forty, more = "x" * 40, "y" * 41
    _write(p, [_user("T1", forty), _user("T2", more), _user("T3", "\n  opening   \nsecond"), _user("T4", "z" * 400)])
    a, b, c, d = transcript_mod.prompts(p)[0]
    assert (a.drawn, a.whole) == (f"❯ {forty}", True)
    assert (b.drawn, b.whole) == (f"❯ {'y' * 40}", False)
    assert (c.drawn, c.whole) == ("❯ opening", True)  # the first non-empty line
    assert len(d.text) == 300
    _write(p, [_user("T5", "long"), _text("T6", "w" * 250)])
    assert transcript_mod.prompts(p)[0][0].reply == "w" * 200  # a reply's first line is cut at 200


@pytest.mark.unit
def test_a_reply_is_the_first_text_line_after_its_prompt_and_a_read_from_a_cursor_leads_with_one(tmp_path):
    p = tmp_path / "t.jsonl"
    _write(p, [_user("T1", "one"), _text("T2", "\n\nfirst line\nsecond"), _text("T3", "later"), _user("T4", "two")])
    found, leading, cursor = transcript_mod.prompts(p)
    assert [(x.text, x.reply) for x in found] == [("one", "first line"), ("two", None)]
    _write(p, [_text("T5", "x" * 300, isSidechain=True), _text("T6", "the reply to two"), _user("T7", "three")], "a")
    found, leading, after = transcript_mod.prompts(p, cursor)
    assert leading == "the reply to two" and [x.text for x in found] == ["three"]
    with p.open("a") as f:
        f.write('{"type": "user", "timestamp": "T8", "message"')  # still being written: left for the next read
    assert transcript_mod.prompts(p, after) == ([], None, after)
    assert transcript_mod.prompts(p, 10**9)[0][0].text == "one"  # past the file's end: from 0


@pytest.mark.unit
def test_the_captured_conversation_reads_a_local_command_and_its_output_and_skips_the_interrupt():
    found, _, _ = transcript_mod.prompts(FIXTURE)
    rename = next(x for x in found if x.text.startswith("/rename"))
    assert (rename.text, rename.reply, rename.whole) == (
        "/rename conformance prompts",
        "Session renamed to: conformance prompts",
        True,
    )
    assert sum(x.text == "Reply with the one word: ready. Use no tools." for x in found) == 2  # typed twice
    assert not any("interrupted" in x.text or "named this session" in x.text for x in found)


# -- the merge ------------------------------------------------------------------------------------------


def _p(at: str, text: str, reply: str | None = None) -> Prompt:
    return transcript_mod.prompt(at, text) if reply is None else Prompt(at, text, f"❯ {text[:40]}", True, reply)


@pytest.mark.unit
def test_two_queued_sends_with_one_first_line_are_matched_oldest_first_across_reads():
    sends = [
        _send(1, "ao-a", "rebase and push", "2026-10-22T10:00:00Z"),
        _send(2, "ao-b", "rebase and push\nthen merge", "2026-10-22T10:00:05Z"),
    ]
    one = merge_prompts([], [_p("2026-10-22T10:01:00Z", "rebase and push")], None, sends, from_start=True)
    assert [x["from"] for x in one] == ["ao-a"]
    # the next read: the held entry consumes its send again, so the second prompt is the second send's
    two = merge_prompts(one, [_p("2026-10-22T10:02:00Z", "rebase and push\nthen merge")], None, sends, from_start=False)
    assert [x["from"] for x in two] == ["ao-b", "ao-a"]
    # a third with the same line and no send left is the person's; a send made after its prompt is not its
    late = [*sends, _send(3, "ao-c", "rebase and push", "2026-10-22T10:09:00Z")]
    three = merge_prompts(two, [_p("2026-10-22T10:03:00Z", "rebase and push")], None, late, from_start=False)
    assert three[0]["from"] == PERSON


@pytest.mark.unit
def test_a_send_longer_than_300_characters_is_matched_on_its_cut():
    long = "Please " + "do the long thing " * 30
    sends = [_send(1, "ao-lead", long, "2026-10-22T10:00:00Z")]
    got = merge_prompts([], [_p("2026-10-22T10:00:02Z", long)], None, sends, from_start=True)
    assert got[0]["from"] == "ao-lead" and len(got[0]["text"]) == 300


@pytest.mark.unit
def test_the_brief_is_the_brief_before_its_entry_is_written_and_its_entry_is_then_spent():
    brief = f"{mail.BRIEF_LINE}\n\nYou are a grinder."
    got = merge_prompts([], [_p("2026-10-22T10:00:00Z", brief)], None, [], from_start=True)
    assert got[0]["from"] == "brief"
    # the entry is stamped after the composer took it; a person's prompt within the minute stays theirs
    sends = [_send(1, SYSTEM, "(the brief)", "2026-10-22T10:00:03Z")]
    after = merge_prompts(got, [_p("2026-10-22T10:00:30Z", "hi")], None, sends, from_start=False)
    assert [x["from"] for x in after] == [PERSON, "brief"]


@pytest.mark.unit
def test_a_brief_sent_without_its_line_names_the_earliest_prompt_within_a_minute():
    sends = [_send(1, SYSTEM, "(the brief)", "2026-10-22T10:00:10Z")]
    found = [_p("2026-10-22T10:00:00Z", "the brief, pasted alone"), _p("2026-10-22T10:00:20Z", "next")]
    got = merge_prompts([], found, None, sends, from_start=True)
    assert [x["from"] for x in got] == [PERSON, "brief"]
    far = merge_prompts([], [_p("2026-10-22T10:05:00Z", "much later")], None, sends, from_start=True)
    assert far[0]["from"] == PERSON


@pytest.mark.unit
def test_a_policy_line_is_the_systems_and_the_doorbell_is_left_out():
    sends = [_send(1, SYSTEM, "Resume where you left off.", "2026-10-22T10:00:00Z")]
    found = [_p("2026-10-22T10:00:01Z", "Resume where you left off."), _p("2026-10-22T10:00:02Z", mail.unread_line(3))]
    got = merge_prompts([], found, None, sends, from_start=True)
    assert [(x["text"], x["from"]) for x in got] == [("Resume where you left off.", SYSTEM)]


@pytest.mark.unit
def test_a_send_older_than_the_oldest_kept_prompt_is_spent():
    full = merge_prompts(
        [], [_p(f"2026-10-22T10:{i:02d}:00Z", f"prompt {i}") for i in range(RECENT_PROMPTS)], None, [], from_start=True
    )
    assert len(full) == RECENT_PROMPTS and all(x["from"] == PERSON for x in full)
    # its prompt left the list, so a new prompt with its first line is the person's, not the old sender's
    sends = [_send(1, "ao-old", "rebase and push", "2026-10-22T09:00:00Z")]
    got = merge_prompts(full, [_p("2026-10-22T11:00:00Z", "rebase and push")], None, sends, from_start=False)
    assert (got[0]["text"], got[0]["from"]) == ("rebase and push", PERSON)


@pytest.mark.unit
def test_a_reread_changes_nothing_held_and_the_leading_reply_fills_only_from_a_cursor():
    held = merge_prompts([], [_p("T1", "one")], None, [], from_start=True)
    assert held[0]["reply"] is None
    assert merge_prompts(held, [], "stale", [], from_start=True) == held  # a read from 0 leads with nothing
    filled = merge_prompts(held, [], "the reply", [], from_start=False)
    assert filled[0]["reply"] == "the reply"
    # a reread from 0 (a restart) finds the same prompt: it keeps its `from` and its reply
    sends = [_send(1, "ao-x", "one", "T0")]
    again = merge_prompts(filled, [_p("T1", "one", "another reply")], None, sends, from_start=True)
    assert again == filled


@pytest.mark.unit
def test_the_newest_twenty_are_kept_newest_first():
    found = [_p(f"2026-10-22T10:{i:02d}:00Z", f"prompt {i}") for i in range(RECENT_PROMPTS + 3)]
    got = merge_prompts([], found, None, [], from_start=True)
    assert len(got) == RECENT_PROMPTS and got[0]["text"] == f"prompt {RECENT_PROMPTS + 2}"


# -- the record and its view ----------------------------------------------------------------------------


def _full(n: int) -> list[dict]:
    return [
        {
            "at": f"2026-10-22T10:{i:02d}:00.000Z",
            "text": "t" * 300,
            "drawn": "❯ " + "t" * 40,
            "whole": False,
            "reply": "r" * 200,
            "from": "ao-shiftlead-grinder-ao-1",
        }
        for i in range(n)
    ]


@pytest.mark.unit
def test_prompts_is_the_nodes_and_the_view_trims_each_entry():
    assert "prompts" in NODE_OWNED
    s = Session(id="ao-x", name="x", kind="interactive", dir="/d", adapter="shell")
    assert s.prompts == []
    s.prompts = _full(RECENT_PROMPTS)
    assert Session.from_dict(s.to_dict()).prompts == s.prompts  # the record keeps the whole
    view = s.view()["prompts"]
    assert len(view[0]["text"]) == 120 and len(view[0]["reply"]) == 100 and view[0]["from"] == s.prompts[0]["from"]
    empty = Session(id="ao-x", name="x", kind="interactive", dir="/d", adapter="shell")
    grew = len(json.dumps(s.view())) - len(json.dumps(empty.view()))
    assert grew <= 8 * 1024
    assert len(json.dumps([s.view() for _ in range(30)])) < 1024 * 1024


# -- the tick -------------------------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_tick_gives_a_prompt_its_sender_and_the_next_read_its_reply(agent, tmp_path, monkeypatch):
    batches: list[tuple[list[Prompt], str | None, int]] = []
    asked: list[tuple[str, int]] = []

    def prompts(session_id, cwd, profile="", *, cursor=0):
        asked.append((session_id, cursor))
        return batches.pop(0) if batches else ([], None, cursor)

    monkeypatch.setattr(adapters.get("shell"), "prompts", prompts, raising=False)
    async with LocalClient() as person, LocalClient() as sub:
        sid = (await person.call("create", name="sh", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))[
            "id"
        ]
        await person.call("hook", session=sid, adapter_id="conv-1")
        # every read below is the test's own tick: a loop tick took a batch or added to `asked` (TD-1099)
        await park_ticks(agent)
        now = datetime.now(UTC)
        agent.sessions[sid].sends.append(_send(1, "ao-lead", "look at #12", "2026-10-22T10:00:00Z"))
        batches.append(([_p("2026-10-22T10:00:01Z", "look at #12")], None, 100))
        agent._prompts_checked.clear()
        await sub.call("subscribe")
        await agent.tick()
        got = (await person.call("get", id=sid))["prompts"]
        assert [(x["text"], x["from"], x["reply"]) for x in got] == [("look at #12", "ao-lead", None)]
        # the stream's delta carries it too, trimmed as every view is
        while True:
            ev = json.loads(await asyncio.wait_for(sub._reader.readline(), 5))
            if (ev.get("session") or {}).get("id") == sid and ev["session"].get("prompts"):
                break
        assert ev["session"]["prompts"][0]["from"] == "ao-lead"
        # the next read leads with the reply
        batches.append(([], "On it.", 160))
        agent._prompts_checked.clear()
        await agent.tick()
        assert asked[-1] == ("conv-1", 100)
        assert (await person.call("get", id=sid))["prompts"][0]["reply"] == "On it."
        # a file that shrank is read from 0: its leading text is no reply to the newest held prompt
        batches.append(([_p("2026-10-22T10:02:00Z", "and then?")], None, 200))
        agent._prompts_checked.clear()
        await agent.tick()
        batches.append(([], "unrelated", 10))
        agent._prompts_checked.clear()
        await agent.tick()
        assert asked[-1] == ("conv-1", 200)
        assert (await person.call("get", id=sid))["prompts"][0]["reply"] is None
        # read on the tick after a prompt hook, not once per LINKS_EVERY; a subagent's stop makes none due
        agent._prompts_checked[sid] = now
        n = len(asked)
        await agent.tick()
        assert len(asked) == n
        await agent.rpc_hook(sid, state="idle", subagent="agent-1")
        await agent.tick()
        assert len(asked) == n
        await agent.rpc_hook(sid, state="working", prompt=True)
        await agent.tick()
        assert len(asked) == n + 1
        await agent.rpc_hook(sid, state="idle")
        await agent.tick()
        assert len(asked) == n + 2
        # a new tool session starts the list and the cursor again
        await person.call("hook", session=sid, adapter_id="conv-2")
        batches.append(([_p("2026-10-22T11:00:00Z", "fresh")], None, 40))
        agent._prompts_checked.clear()
        await agent.tick()
        assert asked[-1] == ("conv-2", 0)
        assert [x["text"] for x in (await person.call("get", id=sid))["prompts"]] == ["fresh"]
        await person.call("kill", id=sid)
        await person.call("close", id=sid)
        # a closed record's list is left alone, even with a read due
        agent._prompts_due.add(sid)
        agent._prompts_checked.clear()
        n = len(asked)
        await agent.tick()
        assert len(asked) == n
        await person.call("remove", id=sid)
        assert sid not in agent._prompts_checked and sid not in agent._prompts_cursor and sid not in agent._prompts_due
