"""The handoff a session moved to its next login is told (design §4.9e *The handoff is one adapter method*,
TD-2069): neutral entries as turns of plain text, newest last, and the newest 24,000 characters of them cut at
a turn's start, under its heading. The three adapters' own reads are held by the conformance suite, and here
on what its captured transcripts never carry: more turns than the reader's default, and a line it cannot take."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sessionorc import adapters
from sessionorc.adapters import (
    HANDOFF_HEADING,
    ShellAdapter,
    TranscriptEntry,
    handoff_of,
    handoff_text,
    handoff_turns,
)

pytestmark = pytest.mark.unit


def _entries() -> list[TranscriptEntry]:
    return [
        TranscriptEntry(kind="text", text="a banner before any prompt"),
        TranscriptEntry(kind="prompt", text="first ask"),
        TranscriptEntry(kind="thought", text="private reasoning", lines=1),
        TranscriptEntry(kind="tool", name="Bash", call="ls", result="a.py\nb.py"),
        TranscriptEntry(kind="text", text="done"),
        TranscriptEntry(kind="prompt", text="second ask"),
        TranscriptEntry(kind="tool", name="Read", call="x.py", result=None, error=True),
        TranscriptEntry(kind="sidechain", count=3),
        TranscriptEntry(kind="compaction"),
    ]


def test_turns_open_at_each_prompt_newest_last_and_leave_out_thoughts():
    got = handoff_turns(_entries())
    assert got == [
        "a banner before any prompt",
        "Prompt:\nfirst ask\n[Bash] ls\n  -> a.py\ndone",
        "Prompt:\nsecond ask\n[Read failed] x.py\n[a subagent ran 3 entries]\n[the conversation was compacted here]",
    ]
    assert not any("private reasoning" in t for t in got)


def test_a_long_result_keeps_its_first_line_cut():
    got = handoff_turns([TranscriptEntry(kind="tool", name="T", call="c", result="x" * 500 + "\nsecond")])
    assert got == ["[T] c\n  -> " + "x" * adapters.HANDOFF_RESULT]


def test_the_text_keeps_the_newest_turns_that_fit_cut_at_a_turns_start():
    turns = ["a" * 10, "b" * 10, "c" * 10]
    assert handoff_text(turns, limit=22) == f"{HANDOFF_HEADING}\n\n{'b' * 10}\n\n{'c' * 10}"
    assert handoff_text(turns, limit=21) == f"{HANDOFF_HEADING}\n\n{'c' * 10}"
    assert handoff_text(turns) == f"{HANDOFF_HEADING}\n\n" + "\n\n".join(turns)


def test_a_newest_turn_longer_than_the_limit_keeps_its_tail():
    assert handoff_text(["old", "x" * 30 + "end"], limit=10) == f"{HANDOFF_HEADING}\n\n{'x' * 7}end"


def test_no_turns_hand_over_nothing():
    assert handoff_text([]) == ""
    assert handoff_text(None) == ""
    assert handoff_text(["", ""]) == ""


def test_the_default_limit_is_24000_characters():
    turns = [f"{i:05d}" + "y" * 995 for i in range(30)]  # 30 turns of 1,000 characters
    text = handoff_text(turns)
    body = text.removeprefix(f"{HANDOFF_HEADING}\n\n")
    assert len(body) <= 24_000
    assert body.endswith(turns[-1]) and body.startswith(turns[-23][:5])  # 23 turns and 22 separators fit


class _Reads:
    implements = frozenset({"handoff"})

    def __init__(self, got):
        self.got = got
        self.asked: list[Path] = []

    def handoff(self, transcript: Path):
        self.asked.append(transcript)
        if isinstance(self.got, Exception):
            raise self.got
        return self.got


def test_an_adapter_without_the_method_hands_over_nothing(tmp_path):
    assert handoff_of(ShellAdapter(), tmp_path / "t.jsonl") == ""

    class Undeclared(_Reads):
        implements = frozenset()

    assert handoff_of(Undeclared(["turn"]), tmp_path / "t.jsonl") == ""


def test_an_adapter_with_it_hands_over_its_turns_cut(tmp_path):
    ad = _Reads(["one", "two"])
    assert handoff_of(ad, str(tmp_path / "t.jsonl")) == f"{HANDOFF_HEADING}\n\none\n\ntwo"
    assert ad.asked == [tmp_path / "t.jsonl"]
    assert handoff_of(ad, None) == ""
    assert handoff_of(_Reads(None), tmp_path / "t.jsonl") == ""
    assert handoff_of(_Reads(OSError("gone")), tmp_path / "t.jsonl") == ""
    assert handoff_of(_Reads(AttributeError("odd line")), tmp_path / "t.jsonl") == ""


def test_a_blank_tool_result_keeps_the_call_without_a_result():
    got = handoff_turns([TranscriptEntry(kind="tool", name="T", call="c", result="\n  \n\n")])
    assert got == ["[T] c"]


def test_a_thought_alone_before_the_first_prompt_makes_no_empty_turn():
    got = handoff_turns(
        [TranscriptEntry(kind="thought", text="warming up", lines=1), TranscriptEntry(kind="prompt", text="go")]
    )
    assert got == ["Prompt:\ngo"]


# Each adapter's own read (design §4.9e, TD-2069, TD-2295): a line its transcript reader writes for one prompt,
# and a line that reader cannot take, which the conformance suite's captured transcripts never carry.
def _claude_prompt(i: int) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": f"ask {i}"},
        "timestamp": f"2026-11-26T00:{i:02d}:00Z",
    }


def _gemini_prompt(i: int) -> dict:
    return {"id": f"u{i}", "timestamp": f"2026-11-26T00:{i:02d}:00Z", "type": "user", "content": [{"text": f"ask {i}"}]}


def _grok_prompt(i: int) -> dict:
    up = {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": f"ask {i}"}}
    return {"timestamp": i, "method": "session/update", "params": {"sessionId": "s", "update": up}}


_READS = {
    "claude-code": (_claude_prompt, {"type": "user", "message": 3}),
    "gemini": (
        _gemini_prompt,
        {"id": "a", "type": "gemini", "content": "", "toolCalls": [{"name": "x", "status": []}]},
    ),
    "grok": (_grok_prompt, {"params": {"update": {"sessionUpdate": []}}}),
}


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


@pytest.mark.parametrize("name", sorted(_READS))
def test_an_adapters_handoff_reads_past_the_readers_default_of_20_turns(name, tmp_path):
    prompt, _bad = _READS[name]
    t = _write(tmp_path / "t.jsonl", [prompt(i) for i in range(25)])
    got = adapters.get(name).handoff(t)
    assert got == [f"Prompt:\nask {i}" for i in range(25)]


@pytest.mark.parametrize("name", sorted(_READS))
def test_an_adapters_handoff_of_a_line_its_reader_cannot_take_is_none(name, tmp_path):
    prompt, bad = _READS[name]
    t = _write(tmp_path / "t.jsonl", [prompt(0), bad])
    assert adapters.get(name).handoff(t) is None
