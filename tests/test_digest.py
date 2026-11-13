"""The conversation digest (design §4.7 *Feedback*, TD-1491, TD-1716): the line forms, the instants, the
window, the cut and `next`, read over neutral entries (`sessionorc.digest`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from sessionorc import digest as dg
from sessionorc.adapters import Transcript, TranscriptEntry

pytestmark = pytest.mark.unit

E = TranscriptEntry


def at(h: int, m: int, s: int = 0, frac: str = "") -> str:
    return f"2026-11-04T{h:02d}:{m:02d}:{s:02d}{frac}Z"


def when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def reader(entries: list[TranscriptEntry], page: int = 3):
    """A `read(before)` paging `entries` back `page` at a time, `before` an index standing for the byte offset."""
    calls: list[int | None] = []

    def read(before: int | None) -> Transcript:
        calls.append(before)
        end = len(entries) if before is None else before
        start = max(0, end - page)
        return Transcript(path="x", size=1, entries=entries[start:end], before=start if start > 0 else None)

    read.calls = calls  # type: ignore[attr-defined]
    return read


DAY_START, DAY_END = at(0, 0), at(23, 59)


def run(entries, since=DAY_START, until=DAY_END, zone=UTC, skip=0, page=100, first_at=None, **kw):
    return dg.digest(
        reader(entries, page), first_at=first_at, since=when(since), until=when(until), zone=zone, skip=skip, **kw
    )


def test_each_line_form_and_its_mark():
    sub = E(kind="sidechain", count=4)
    entries = [
        E(kind="prompt", at=at(9, 0), text="one\ntwo\nthree\nfour\nfive"),
        E(kind="thought", at=at(9, 1), text="hidden", lines=1),
        E(kind="tool", at=at(9, 1), name="Bash", call="ls", result="a"),
        E(kind="tool", at=at(9, 2), name="Read", call="/x", result="b"),
        E(kind="tool", at=at(9, 2), name="Bash", call="pwd", result="c"),
        E(kind="tool", at=at(9, 3), name="Bash", call="false " + "x" * 200, result="l1\nl2\nl3\nl4", error=True),
        E(kind="tool", at=at(9, 4), name="Bash", call="true", result=None, error=True),
        E(kind="tool", at=at(9, 5), name="Agent", call="look", result="done", sidechain=sub),
        E(kind="tool", at=at(9, 6), name="Agent", call="fail", result="boom", error=True, sidechain=sub),
        E(kind="sidechain", at=at(9, 7), count=2),
        E(kind="compaction", at=at(9, 8)),
        E(kind="text", at=at(9, 9), text="it got in my way\nbecause"),
    ]
    got = run(entries)
    lines = got["text"].split("\n")
    assert lines == [
        "=== 2026-11-04 ===",
        "09:00 > one",
        "  two",
        "  three",
        "  (+2 lines)",
        "09:01 · 3 calls (Bash 2, Read 1)",
        "09:03 ✗ Bash(false " + "x" * 113 + "…) → l1",
        "  l2",
        "  l3",
        "09:04 ✗ Bash(true) → (no result)",
        "09:05 · subagent Agent(look), 4 entries",
        "09:06 ✗ Agent(fail) → boom, subagent 4 entries",
        "09:07 · subagent, 2 entries",
        "09:08 — compacted —",
        "09:09 < it got in my way",
        "  because",
    ]
    assert got["lines"] == len(lines) and got["next"] is None


def test_a_long_result_is_kept_to_300_characters():
    got = run([E(kind="tool", at=at(9, 0), name="Bash", call="x", result="y" * 400, error=True)])
    assert got["text"].split("\n")[1] == "09:00 ✗ Bash(x) → " + "y" * 299 + "…"


def test_day_lines_fall_in_the_given_zone_across_a_change_of_clocks():
    """Europe/London leaves summer time at 01:00 UTC on 2026-10-25: 23:30 UTC on the 24th is 00:30 local on the
    25th, and 23:30 UTC on the 25th is still the 25th."""
    zone = dg.zone_of({"name": "Europe/London", "offset": 0})
    entries = [
        E(kind="prompt", at="2026-10-24T22:30:00Z", text="a"),
        E(kind="prompt", at="2026-10-24T23:30:00Z", text="b"),
        E(kind="prompt", at="2026-10-25T23:30:00Z", text="c"),
    ]
    got = run(entries, since="2026-10-24T00:00:00Z", until="2026-10-27T00:00:00Z", zone=zone)
    assert got["text"].split("\n") == [
        "=== 2026-10-24 ===",
        "23:30 > a",
        "=== 2026-10-25 ===",
        "00:30 > b",
        "23:30 > c",
    ]


def test_the_zone_falls_back_to_the_offset_where_the_name_does_not_resolve():
    assert dg.zone_of({"name": "No/Such_Zone", "offset": 90}) == timezone(timedelta(minutes=90))
    assert dg.zone_of({"name": None, "offset": -300}) == timezone(timedelta(minutes=-300))
    assert dg.zone_of(None) == UTC


def test_the_window_is_since_inclusive_and_until_exclusive():
    entries = [E(kind="prompt", at=at(9, m), text=str(m)) for m in range(5)]
    got = run(entries, since=at(9, 1), until=at(9, 3))
    assert got["text"].split("\n")[1:] == ["09:01 > 1", "09:02 > 2"]


def test_the_backward_read_stops_at_a_page_older_than_the_window():
    entries = [E(kind="prompt", at=at(9, m), text=str(m)) for m in range(10)]
    read = reader(entries, page=3)
    dg.digest(read, first_at=None, since=when(at(9, 8)), until=when(at(10, 0)), zone=UTC)
    assert read.calls == [None]  # 07, 08, 09: 07 is older than the window
    read = reader([E(kind="compaction"), *entries], page=3)
    dg.digest(read, first_at=None, since=when(at(9, 1)), until=when(at(10, 0)), zone=UTC)
    assert read.calls == [None, 8, 5, 2]  # the page holding 00 opens dated: no page more


def test_a_page_that_opens_undated_reads_one_page_more():
    entries = [E(kind="prompt", at=at(7, 0), text="x"), E(kind="compaction")]
    entries += [E(kind="prompt", at=at(8, 0), text="b"), E(kind="prompt", at=at(9, 5), text="c")]
    read = reader(entries, page=3)
    got = dg.digest(read, first_at=None, since=when(at(7, 0)), until=when(at(10, 0)), zone=UTC)
    assert read.calls == [None, 1]  # 08:00 is older than nothing here, but the page opened undated
    assert got["text"].split("\n")[1:] == ["07:00 > x", "07:00 — compacted —", "08:00 > b", "09:05 > c"]


def test_an_entry_dated_earlier_than_the_one_before_takes_its_instant():
    got = run([E(kind="prompt", at=at(9, 5), text="a"), E(kind="text", at=at(9, 4), text="b")], until=at(9, 5))
    assert got == {"text": "", "lines": 0, "next": None}  # both are 09:05, outside a window ending there


def test_an_undated_first_entry_takes_the_conversations_first_at():
    got = run([E(kind="compaction"), E(kind="prompt", at=at(9, 5), text="a")], first_at=at(9, 2))
    assert got["text"].split("\n")[1] == "09:02 — compacted —"


def test_an_entry_over_64_kib_is_cut_at_a_character_boundary():
    got = run([E(kind="text", at=at(9, 0), text="é" * 50_000)])
    body = got["text"].split("\n", 1)[1]
    assert body.endswith(" (cut)") and len(body.encode("utf-8")) <= dg.ENTRY_BYTES
    body.encode("utf-8").decode("utf-8")


def test_an_empty_window_and_a_window_of_thoughts_answer_nothing():
    assert run([E(kind="prompt", at=at(9, 0), text="a")], since=at(10, 0)) == {"text": "", "lines": 0, "next": None}
    assert run([E(kind="thought", at=at(9, 0), text="t", lines=1)]) == {"text": "", "lines": 0, "next": None}


def test_no_file_is_none():
    assert dg.digest(lambda before: None, first_at=None, since=when(at(0, 0)), until=when(at(1, 0)), zone=UTC) is None


def _whole(entries, limit, **kw):
    """Every reply of a window read as the CLI reads it, `next` fed back as `since` and `skip`."""
    since, skip, texts = at(0, 0), 0, []
    for _ in range(50):
        got = run(entries, since=since, skip=skip, limit=limit, **kw)
        texts.append(got["text"])
        if got["next"] is None:
            return texts
        since, skip = got["next"]["at"], got["next"]["skip"]
    raise AssertionError("never ended")


def _prompts(texts):
    return [line.split("> ", 1)[1] for t in texts for line in t.split("\n") if " > " in line]


def test_a_cut_ends_at_the_last_prompt_and_the_next_reply_starts_there():
    entries = []
    for i in range(6):
        entries += [E(kind="prompt", at=at(9, i), text=f"p{i}"), E(kind="text", at=at(9, i), text="w" * 3000)]
    limit = dg.REPLY_SLACK + 8000
    texts = _whole(entries, limit)
    assert len(texts) > 1 and _prompts(texts) == [f"p{i}" for i in range(6)]
    assert all(t.split("\n")[1].split(" ", 1)[1].startswith(">") for t in texts)  # each opens at a prompt


def test_a_cut_with_no_prompt_before_the_point_ends_at_the_last_entry():
    entries = [E(kind="prompt", at=at(9, 0), text="p")]
    entries += [E(kind="text", at=at(9, 1), text=f"t{i} " + "w" * 3000) for i in range(6)]
    texts = _whole(entries, dg.REPLY_SLACK + 7000)
    said = [line.split("< ", 1)[1][:2] for t in texts for line in t.split("\n") if " < " in line]
    assert len(texts) > 2 and said == [f"t{i}" for i in range(6)]


def test_a_shared_instant_with_fractions_is_neither_repeated_nor_lost():
    entries = [E(kind="prompt", at=at(9, 0, 0, ".100"), text="a")]
    entries += [E(kind="text", at=at(9, 0, 0, ".100"), text=f"s{i} " + "w" * 3000) for i in range(4)]
    entries += [E(kind="text", at=at(9, 0, 0, ".250"), text=f"u{i} " + "w" * 3000) for i in range(3)]
    texts = _whole(entries, dg.REPLY_SLACK + 7000)
    said = [line.split("< ", 1)[1][:2] for t in texts for line in t.split("\n") if " < " in line]
    assert said == [f"s{i}" for i in range(4)] + [f"u{i}" for i in range(3)]


def test_a_cut_before_an_entry_dated_earlier_loses_nothing():
    entries = [E(kind="prompt", at=at(9, 0, 5), text="a")]
    entries += [E(kind="text", at=at(9, 0, 5 if i % 2 == 0 else 4), text=f"t{i} " + "w" * 3000) for i in range(6)]
    texts = _whole(entries, dg.REPLY_SLACK + 7000)
    said = [line.split("< ", 1)[1][:2] for t in texts for line in t.split("\n") if " < " in line]
    assert said == [f"t{i}" for i in range(6)]


def test_a_run_before_the_seam_is_written_in_the_reply_it_ends():
    entries = [E(kind="prompt", at=at(9, 0), text="p")]
    entries += [E(kind="tool", at=at(9, 1), name="Bash", call="c" * 100, result="r") for _ in range(3)]
    entries += [E(kind="text", at=at(9, 2), text="w" * 3000), E(kind="tool", at=at(9, 3), name="Read", call="x")]
    got = run(entries, limit=dg.REPLY_SLACK + 2000)  # the text passes the point: the run before it is written
    assert got["text"].split("\n")[-1] == "09:01 · 3 calls (Bash 3)" and got["next"]["at"] == at(9, 2)


def test_a_cut_reply_holds_at_least_one_entry():
    got = run([E(kind="text", at=at(9, 0), text="w" * 20_000), E(kind="text", at=at(9, 1), text="v")], limit=5000)
    assert got["text"].startswith("=== 2026-11-04 ===\n09:00 < www") and got["next"] == {"at": at(9, 1), "skip": 0}


def test_a_reply_under_the_limit_with_many_runs_is_not_cut():
    entries = []
    for i in range(400):
        entries += [E(kind="text", at=at(9, 0, i % 60), text=f"t{i}"), E(kind="tool", at=at(9, 0, i % 60), name="Bash")]
    whole = run(entries)
    size = len(dg.json.dumps(whole))
    got = run(entries, limit=dg.REPLY_SLACK + size)
    assert got["next"] is None and got["text"] == whole["text"]
