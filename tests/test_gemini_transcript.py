"""The Gemini CLI adapter's reads (design §4.3 *The second adapter: Gemini CLI*, *Reads*, TD-786 slice 1): the
chat found by the id its first record names, the replay of re-written records and patches, paging by byte
offset, the context and its window, links read once per record, and spend over every chat, subagents' too.
The captured chats are the conformance suite's; these are the record shapes no capture holds yet."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from shiftlead.adapters.gemini import GeminiAdapter
from shiftlead.adapters.gemini import transcript as t

pytestmark = pytest.mark.unit

SID = "0b22427e-9282-4281-88e1-c62d1dc4ecb1"


def _meta(sid: str = SID) -> dict:
    return {"sessionId": sid, "projectHash": "h", "startTime": "2026-10-22T07:05:00.000Z", "kind": "main"}


def _user(mid: str, text: str, at: str = "2026-10-22T07:05:01.000Z") -> dict:
    return {"id": mid, "timestamp": at, "type": "user", "content": [{"text": text}]}


def _gemini(mid: str, text: str, *, tokens: dict | None = None, model: str = "gemini-3.8-flash", **kw) -> dict:
    rec = {"id": mid, "timestamp": "2026-10-22T07:05:02.000Z", "type": "gemini", "content": text, "model": model}
    if tokens is not None:
        rec["tokens"] = tokens
    return {**rec, **kw}


def _write(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profiles.yml").write_text(
        f"default: g\nprofiles:\n  g: {{adapter: gemini, account: g, config_dir: {tmp_path / 'gm'}}}\n"
    )
    return "g"


def _chats(tmp_path: Path, slug: str = "repo") -> Path:
    project = tmp_path / "gm" / ".gemini" / "tmp" / slug
    (project / "chats").mkdir(parents=True, exist_ok=True)
    (project / ".project_root").write_text("/work/repo")
    return project / "chats"


def test_the_chat_is_the_top_level_file_whose_first_record_names_the_id(tmp_path, profile):
    chats = _chats(tmp_path)
    mine = _write(chats / f"session-2026-10-22T07-05-{SID[:8]}.jsonl", [_meta(), _user("u1", "hi")])
    # another session's chat sharing the id's first eight characters, and a subagent's under the parent
    _write(chats / f"session-2026-10-22T07-06-{SID[:8]}.jsonl", [_meta(SID[:8] + "-other")])
    _write(chats / SID / f"session-2026-10-22T07-07-{SID[:8]}.jsonl", [_meta()])
    ad = GeminiAdapter()
    assert ad.transcript_path(SID, Path("/work/repo"), profile) == mine
    assert ad.transcript_path("no-such-session", Path("/work/repo"), profile) is None
    assert ad.transcript_path("*", Path("/work/repo"), profile) is None
    assert ad.read_transcript(SID, Path("/work/repo"), "unknown-profile") is None


def test_a_record_written_again_keeps_its_place_and_its_last_content():
    data = "".join(
        json.dumps(r) + "\n"
        for r in [_meta(), _user("u1", "first"), _gemini("g1", "par"), _user("u2", "second"), _gemini("g1", "partial")]
    ).encode()
    messages, meta = t.replay(data)
    assert list(messages) == ["u1", "g1", "u2"]
    assert messages["g1"][1]["content"] == "partial"
    assert meta["sessionId"] == SID


def test_rewind_drops_the_named_message_and_every_later_one():
    recs = [_meta(), _user("u1", "a"), _gemini("g1", "b"), _user("u2", "c"), _gemini("g2", "d"), {"$rewindTo": "u2"}]
    messages, _ = t.replay("".join(json.dumps(r) + "\n" for r in recs).encode())
    assert list(messages) == ["u1", "g1"]
    messages, _ = t.replay("".join(json.dumps(r) + "\n" for r in [*recs, {"$rewindTo": "gone"}]).encode())
    assert messages == {}  # a rewind to an id it does not hold clears every message, as the tool's reader does


def test_a_patch_amends_content_and_results_removes_and_reorders():
    call = {"id": "c1", "name": "run_shell_command", "args": {"command": "ls"}}
    recs = [
        _meta(),
        _user("u1", "a"),
        _gemini("g1", "b", toolCalls=[call]),
        {"id": "x", "type": "info", "content": "update available"},
        {
            "$patch": {
                "updates": [
                    {"id": "g1", "content": [{"text": "thinking", "thought": True}, {"text": "done"}]},
                    {
                        "id": "g1",
                        "toolCalls": [
                            {
                                "id": "c1",
                                "result": [{"functionResponse": {"id": "c1", "response": {"output": "f.txt"}}}],
                            }
                        ],
                    },
                ],
                "removeIds": ["x"],
                "orderIds": ["g1", "u1"],
            }
        },
    ]
    messages, _ = t.replay("".join(json.dumps(r) + "\n" for r in recs).encode())
    assert list(messages) == ["g1", "u1"]
    entries, prompts = t._entries([rec for _o, rec in messages.values()])
    assert prompts == 1
    text = next(e for e in entries if e.kind == "text")
    assert text.text == "done"  # a thought part is never read as text
    tool = next(e for e in entries if e.kind == "tool")
    assert (tool.name, tool.call, tool.result) == ("run_shell_command", "ls", "f.txt")


def test_the_preamble_is_no_prompt_and_a_function_response_answers_its_call(tmp_path):
    call = {"id": "c1", "name": "read_file", "args": {"absolute_path": "/w/a.py"}}
    path = _write(
        tmp_path / "c.jsonl",
        [
            _meta(),
            _user("p0", "<session_context>\nThis is the Gemini CLI."),
            _user("u1", "read it"),
            _gemini("g1", "", toolCalls=[call], thoughts=[{"subject": "Reading", "description": "the file"}]),
            {
                "id": "r1",
                "type": "user",
                "content": [{"functionResponse": {"id": "c1", "response": {"output": "x = 1"}}}],
            },
        ],
    )
    tr = t.read(path)
    assert tr.turns == 1
    assert [(e.kind, e.text or e.call) for e in tr.entries] == [
        ("prompt", "read it"),
        ("thought", "Reading\nthe file"),
        ("tool", "/w/a.py"),
    ]
    assert tr.entries[-1].result == "x = 1"
    assert tr.first_at == "2026-10-22T07:05:00.000Z" and tr.before is None


def test_a_read_pages_back_by_the_first_line_of_each_message(tmp_path):
    recs = [_meta()]
    for i in range(5):
        recs += [_user(f"u{i}", f"prompt {i}"), _gemini(f"g{i}", f"answer {i}")]
    path = _write(tmp_path / "c.jsonl", recs)
    last = t.read(path, turns=2)
    assert [e.text for e in last.entries] == ["prompt 3", "answer 3", "prompt 4", "answer 4"]
    earlier = t.read(path, turns=2, before=last.before)
    assert [e.text for e in earlier.entries] == ["prompt 1", "answer 1", "prompt 2", "answer 2"]
    first = t.read(path, turns=2, before=earlier.before)
    assert [e.text for e in first.entries] == ["prompt 0", "answer 0"] and first.before is None
    raw = t.read(path, raw=True, turns=3)
    assert len(raw.raw.splitlines()) == 3


def test_context_is_the_last_turns_input_and_the_models_window(tmp_path):
    path = _write(
        tmp_path / "c.jsonl",
        [_meta(), _gemini("g1", "a", tokens={"input": 900, "cached": 100}), _gemini("g2", "b", tokens={"input": 1200})],
    )
    assert t.context(path) == {"tokens": 1200, "at": "2026-10-22T07:05:02.000Z", "window": 1_048_576}
    assert t.model(path) == "gemini-3.8-flash"
    gemma = _write(tmp_path / "m.jsonl", [_meta(), _gemini("g1", "a", tokens={"input": 50}, model="gemma-4-27b")])
    assert t.context(gemma)["window"] == 256_000
    assert t.context(_write(tmp_path / "e.jsonl", [_meta(), _user("u1", "hi")])) is None


def test_links_are_read_once_per_record_at_its_last_line(tmp_path):
    path = _write(
        tmp_path / "c.jsonl",
        [
            _meta(),
            _user("u1", "see https://example.com/asked"),  # a person's prompt holds no link
            _gemini("g1", "PR at https://github.com/o/r/pull/1"),
            _gemini("g1", "PR at https://github.com/o/r/pull/1 and http://localhost:8000/x"),
        ],
    )
    found, cursor = t.links(path)
    assert [x.url for x in found] == ["https://github.com/o/r/pull/1"]
    assert cursor == path.stat().st_size
    assert t.links(path, cursor) == ([], cursor)


def test_spend_reads_every_chat_and_a_subagents_as_its_parents(tmp_path, profile):
    chats = _chats(tmp_path)
    tokens = {"input": 1000, "output": 10, "cached": 600, "thoughts": 5}
    _write(chats / f"session-2026-10-22T07-05-{SID[:8]}.jsonl", [_meta(), _gemini("g1", "a", tokens=tokens)])
    _write(
        chats / SID / "session-2026-10-22T07-06-aaaaaaaa.jsonl",
        [_meta("sub"), _gemini("s1", "b", tokens={"input": 50}), _gemini("s1", "b!", tokens={"input": 60})],
    )
    ad = GeminiAdapter()
    got = ad.spend(profile, {})
    assert got["reason"] == "ok"
    by = {x["id"]: x for x in got["turns"]}
    assert set(by) == {"g1", "s1"}
    g1 = by["g1"]
    assert (g1["input"], g1["cache_read"], g1["output"], g1["cache_write"]) == (400, 600, 15, 0)
    assert (g1["conversation"], g1["cwd"], g1["subagent"], g1["response"]) == (SID, "/work/repo", False, "g1")
    assert (by["s1"]["conversation"], by["s1"]["subagent"], by["s1"]["input"]) == (SID, True, 60)
    again = ad.spend(profile, got["cursors"])
    assert again["turns"] == [] and again["cursors"] == got["cursors"]
    assert ad.spend("unknown-profile", {"x": 3}) == {"turns": [], "cursors": {"x": 3}, "reason": "no_profile"}
    assert ad.billing_for(profile) == {"billing": "subscription", "prices": {}}


def test_a_header_with_messages_and_a_set_of_every_message_page_without_a_gap(tmp_path):
    first = [_user("u0", "prompt 0"), _gemini("g0", "answer 0"), _user("u1", "prompt 1"), _gemini("g1", "answer 1")]
    path = _write(
        tmp_path / "c.jsonl",
        [{**_meta(), "messages": first[:2]}, {"$set": {"messages": first}}, _user("u2", "prompt 2")],
    )
    messages, _ = t.replay(path.read_bytes())
    assert list(messages) == ["u0", "g0", "u1", "g1", "u2"]
    last = t.read(path, turns=2)
    # the two prompts the `$set` wrote share its offset, so the page takes the whole of it
    assert [e.text for e in last.entries] == ["prompt 0", "answer 0", "prompt 1", "answer 1", "prompt 2"]
    assert last.before is None


def test_a_malformed_record_is_skipped_not_raised(tmp_path):
    path = _write(
        tmp_path / "c.jsonl",
        [
            _meta(),
            _user("u1", "a"),
            _gemini("g1", "b", toolCalls=["x", {"name": "ls", "args": {}}], thoughts=7),
            {"$patch": {"updates": 3, "removeIds": 4, "id": "g1", "toolCalls": ["y", {"id": None, "result": []}]}},
            {"id": "r", "type": "user", "content": [{"functionResponse": {"response": {"output": "orphan"}}}]},
        ],
    )
    tr = t.read(path)
    tool = next(e for e in tr.entries if e.kind == "tool")
    assert tool.name == "ls" and tool.result is None  # a response that names no call answers none


def test_a_patch_ordering_some_messages_leaves_the_rest_first():
    recs = [_meta(), _user("u1", "a"), _gemini("g1", "b"), _user("u2", "c"), {"$patch": {"orderIds": ["u1"]}}]
    messages, _ = t.replay("".join(json.dumps(r) + "\n" for r in recs).encode())
    assert list(messages) == ["g1", "u2", "u1"]


def test_of_two_chats_for_one_id_the_newer_is_read(tmp_path):
    chats = _chats(tmp_path)
    old = _write(chats / f"session-2026-10-22T07-05-{SID[:8]}.jsonl", [_meta()])
    new = _write(chats / f"session-2026-10-22T07-09-{SID[:8]}.jsonl", [_meta()])
    os.utime(old, (2_000_000_000, 2_000_000_000))
    os.utime(new, (1_000_000_000, 1_000_000_000))
    assert t.find(chats.parent.parent, SID) == old  # by its mtime, not its name
    os.utime(new, (3_000_000_000, 3_000_000_000))
    assert t.find(chats.parent.parent, SID) == new


def test_an_id_with_a_glob_character_finds_nothing_even_where_a_file_would_match(tmp_path):
    chats = _chats(tmp_path)
    _write(chats / "session-2026-10-22T07-05-abc?.jsonl", [_meta("abc?")])
    assert t.find(chats.parent.parent, "abc?") is None


def test_spend_drops_a_cursor_that_is_not_a_whole_number():
    got = GeminiAdapter().spend("unknown-profile", {"x": 3, "neg": -1, "text": "4", "none": None})
    assert got == {"turns": [], "cursors": {"x": 3}, "reason": "no_profile"}


def test_spend_keeps_the_cursor_of_a_chat_it_cannot_read(tmp_path, profile, monkeypatch):
    chats = _chats(tmp_path)
    chat = _write(chats / f"session-2026-10-22T07-05-{SID[:8]}.jsonl", [_meta(), _gemini("g1", "a")])
    other = _write(chats / "session-2026-10-22T07-06-bbbbbbbb.jsonl", [_meta("other"), _gemini("g2", "b")])

    def turns(path, *a, **kw):
        raise OSError("gone")

    monkeypatch.setattr(t, "turns", turns)
    got = GeminiAdapter().spend(profile, {str(chat): 5})
    # the one it had read keeps its place, so its turns are not counted again; the new one is read next time
    assert got == {"turns": [], "cursors": {str(chat): 5}, "reason": "ok"}
    assert str(other) not in got["cursors"]


def test_spend_says_an_unreadable_root_and_keeps_its_cursors(tmp_path, profile, monkeypatch):
    _chats(tmp_path)

    def glob(self, pattern):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "glob", glob)
    got = GeminiAdapter().spend(profile, {"x": 3})
    assert got["turns"] == [] and got["cursors"] == {"x": 3}
    assert got["reason"].startswith("unreadable: ") and got["reason"].endswith(": PermissionError")
