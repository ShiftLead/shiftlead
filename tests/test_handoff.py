"""The handoff a session moved to its next login is told (design §4.9e *The handoff is one adapter method*,
TD-2069): neutral entries as turns of plain text, newest last, and the newest 24,000 characters of them cut at
a turn's start, under its heading. The three adapters' own reads are held by the conformance suite."""

from __future__ import annotations

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
