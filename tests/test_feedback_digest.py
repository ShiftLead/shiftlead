"""`ao feedback digest` (design §4.7 *Feedback*, TD-1491, TD-1716): the run over records, the parts and their
split, the index, `--list`, `--skip`, the caller's own conversation, and a record's failures."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sessionorc import adapters
from sessionorc.adapters import Conversation, Transcript, TranscriptEntry
from sessionorc.agent_common import DIGEST_TIMEOUT
from sessionorc.client import CALL_TIMEOUT, AgentError, LocalClient
from shiftlead import cli, feedback

SINCE = datetime(2026, 11, 4, tzinfo=UTC)
UNTIL = datetime(2026, 11, 5, tzinfo=UTC)
ZONE = {"name": "UTC", "offset": 0}


def conv(cid: str, profile: str = "p", first: str = "2026-11-04T09:00:00Z", last: str = "2026-11-04T10:00:00Z"):
    return {"id": cid, "profile": profile, "first_at": first, "last_at": last, "size": 10}


class Fake:
    """The two reads: `listed[rid]` a listing (or an AgentError), `replies[(rid, cid)]` the replies in turn (or
    an AgentError raised at that call)."""

    def __init__(self, listed, replies, marks=True):
        self.listed, self.replies, self.marks = listed, replies, marks
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method, **kw):
        self.calls.append((method, kw))
        if method == "conversations":
            got = self.listed[kw["id"]]
            if isinstance(got, Exception):
                raise got
            return {"marks_errors": self.marks, "conversations": got}
        if method == "transcript_digest":
            queue = self.replies[(kw["id"], kw["conversation"])]
            got = queue.pop(0)
            if isinstance(got, Exception):
                raise got
            return got
        raise AssertionError(method)


def reply(*lines: str, nxt=None):
    text = "\n".join(lines)
    return {"text": text, "lines": len(lines), "next": nxt}


def go(fake, records, tmp_path, **kw):
    kw.setdefault("skip", [])
    kw.setdefault("own", None)
    return feedback.run(fake, records, since=SINCE, until=UNTIL, zone=ZONE, out=tmp_path, **kw)


def test_one_record_one_part_with_the_index_and_the_wait(tmp_path):
    fake = Fake(
        {"r1": [conv("a"), conv("b", "q")]},
        {
            ("r1", "a"): [reply("=== 2026-11-04 ===", "09:00 > hi", "09:01 < done", "  more")],
            ("r1", "b"): [reply("=== 2026-11-04 ===", "09:30 · 2 calls (Bash 2)")],
        },
    )
    index = go(fake, [("grinder", "r1")], tmp_path)
    assert index == {
        "since": "2026-11-04T00:00:00Z",
        "until": "2026-11-05T00:00:00Z",
        "records": [
            {
                "seat": "grinder",
                "id": "r1",
                "marks_errors": True,
                "conversations": [
                    {**{k: conv("a")[k] for k in ("id", "profile", "first_at", "last_at")}, "lines": 4},
                    {**{k: conv("b", "q")[k] for k in ("id", "profile", "first_at", "last_at")}, "lines": 2},
                ],
                "parts": [str(tmp_path / "r1.txt")],
                "bytes": (tmp_path / "r1.txt").stat().st_size,
                "error": None,
                "failed": None,
            }
        ],
    }
    assert (tmp_path / "r1.txt").read_text() == (
        "## a · p · 2026-11-04 09:00 → 2026-11-04 10:00\n=== 2026-11-04 ===\n09:00 > hi\n09:01 < done\n  more\n"
        "## b · q · 2026-11-04 09:00 → 2026-11-04 10:00\n=== 2026-11-04 ===\n09:30 · 2 calls (Bash 2)\n"
    )  # the day line after every header
    for method, kw in fake.calls:
        assert kw["_timeout"] == DIGEST_TIMEOUT + CALL_TIMEOUT, method
    assert fake.calls[1][1] | {"_timeout": 0} == {
        "id": "r1",
        "conversation": "a",
        "profile": "p",
        "since": "2026-11-04T00:00:00Z",
        "until": "2026-11-05T00:00:00Z",
        "zone": ZONE,
        "skip": 0,
        "_timeout": 0,
    }


def test_next_is_called_with_its_at_and_skip_and_a_repeated_day_line_is_dropped(tmp_path):
    nxt = {"at": "2026-11-04T09:05:00.250Z", "skip": 2}
    fake = Fake(
        {"r1": [conv("a")]},
        {
            ("r1", "a"): [
                reply("=== 2026-11-04 ===", "09:00 > one", "09:05 · 1 calls (Read 1)", nxt=nxt),
                reply("=== 2026-11-04 ===", "09:05 · 2 calls (Read 2)", "=== 2026-11-05 ===", "00:10 < late"),
            ]
        },
    )
    index = go(fake, [("s", "r1")], tmp_path)
    second = fake.calls[2][1]
    assert (second["since"], second["skip"]) == ("2026-11-04T09:05:00.250Z", 2)
    assert (tmp_path / "r1.txt").read_text().splitlines()[1:] == [
        "=== 2026-11-04 ===",
        "09:00 > one",
        "09:05 · 1 calls (Read 1)",
        "09:05 · 2 calls (Read 2)",  # a run the seam split is two lines, as written
        "=== 2026-11-05 ===",
        "00:10 < late",
    ]
    assert index["records"][0]["conversations"][0]["lines"] == 6


def big(hhmm: str, mark: str, n: int) -> list[str]:
    return [f"{hhmm} {mark} " + "x" * 100, *("  " + "y" * 100 for _ in range(n - 1))]


def test_parts_split_at_a_header_then_at_the_last_prompt_with_continued(tmp_path):
    # entries of ~10 KiB against a part of 65536 bytes
    a = ["=== 2026-11-04 ==="] + [ln for i in range(4) for ln in big(f"09:0{i}", "<", 100)]
    b = ["=== 2026-11-04 ==="] + [ln for i in range(3) for ln in big(f"09:1{i}", "<", 100)]
    c = ["=== 2026-11-04 ==="]
    for i in range(12):
        c += big(f"10:{i:02d}", ">" if i % 4 == 0 else "<", 100)
    fake = Fake(
        {"r1": [conv("a"), conv("b"), conv("c")]},
        {("r1", "a"): [reply(*a)], ("r1", "b"): [reply(*b)], ("r1", "c"): [reply(*c)]},
    )
    index = go(fake, [("s", "r1")], tmp_path, bound=65536)
    rec = index["records"][0]
    names = [p.rsplit("/", 1)[1] for p in rec["parts"]]
    assert names == [f"r1.{n}.txt" for n in range(1, 6)]
    texts = [(tmp_path / n).read_text() for n in names]
    heads = [[ln for ln in t.splitlines() if ln.startswith("## ")] for t in texts]
    # b and the opening of c each start a part at their header, the tail from it fitting a part; c is larger
    # than a part, so it then splits inside, at its last prompt before the bound, its header repeated
    # *(continued)* with its day line
    assert [[h.split(" · ")[0] for h in hs] for hs in heads] == [["## a"], ["## b"], ["## c"], ["## c"], ["## c"]]
    assert not any("(continued)" in h for hs in heads[:3] for h in hs)
    for t in texts[3:]:
        head, day, first = t.splitlines()[:3]
        assert head.endswith("(continued)") and day == "=== 2026-11-04 ===" and first.split()[1] == ">"
    for t in texts:
        assert len(t.encode()) <= 65536
    assert rec["bytes"] == sum(len(t.encode()) for t in texts)
    assert not (tmp_path / "r1.txt").exists()
    rows = [ln for t in texts for ln in t.splitlines()]
    c_rows = rows[rows.index(heads[2][0]) :]
    assert rec["conversations"][2]["lines"] == sum(1 for ln in c_rows if not ln.startswith("## "))
    assert [ln for ln in c_rows if not ln.startswith(("## ", "==="))] == c[1:]  # nothing repeated or lost


def test_a_split_with_no_prompt_before_the_bound_and_a_part_at_the_floor_holding_one_entry(tmp_path):
    lines = ["=== 2026-11-04 ==="]
    for i in range(3):
        lines += big(f"11:0{i}", "<", 600)  # each entry ~60 KiB: one to a part
    fake = Fake({"r1": [conv("a")]}, {("r1", "a"): [reply(*lines)]})
    rec = go(fake, [("s", "r1")], tmp_path, bound=65536)["records"][0]
    texts = [Path(p).read_text() for p in rec["parts"]]
    assert len(texts) == 3
    for i, t in enumerate(texts):
        rows = t.splitlines()
        assert rows[0].startswith("## a") and rows[0].endswith("(continued)") == (i > 0)
        assert rows[1] == "=== 2026-11-04 ===" and rows[2].startswith(f"11:0{i} <")
        assert sum(1 for r in rows if not r.startswith("  ")) == 3  # one entry


def test_a_conversation_larger_than_a_part_behind_another_splits_inside_and_a_huge_first_entry_moves_whole(
    tmp_path,
):
    a = ["=== 2026-11-04 ===", "09:00 < short"]
    b = ["=== 2026-11-04 ==="]
    for i, mark in enumerate("<><<"):  # ~20 KiB each: b is larger than a part
        b += big(f"10:0{i}", mark, 200)
    c = ["=== 2026-11-04 ==="] + big("11:00", "<", 660)  # one entry past the bound on its own
    fake = Fake(
        {"r1": [conv("a"), conv("b"), conv("c")]},
        {("r1", "a"): [reply(*a)], ("r1", "b"): [reply(*b)], ("r1", "c"): [reply(*c)]},
    )
    rec = go(fake, [("s", "r1")], tmp_path, bound=65536)["records"][0]
    texts = [Path(p).read_text() for p in rec["parts"]]
    firsts = [[ln for ln in t.splitlines() if not ln.startswith(("  ", "==="))] for t in texts]
    # b does not fit a part from its header, so it is not moved whole: it starts beside a and splits at its last
    # prompt before the bound; c's one entry, larger than a part, opens a part at c's own header, never leaving
    # that header at the end of the part before it
    assert [[f.split(" · ")[0] if f.startswith("##") else f[6:7] for f in fs] for fs in firsts] == [
        ["## a", "<", "## b", "<"],
        ["## b", ">", "<", "<"],
        ["## c", "<"],
    ]
    assert firsts[1][0].endswith("(continued)") and not firsts[2][0].endswith("(continued)")


def test_a_split_inside_a_conversation_never_reaches_back_to_a_prompt_before_its_header(tmp_path):
    a = ["=== 2026-11-04 ===", "09:00 < short", "09:01 > again"]
    b = ["=== 2026-11-04 ==="]
    for i in range(4):  # ~20 KiB each, no prompt: b splits before the entry that passes the bound
        b += big(f"10:0{i}", "<", 200)
    fake = Fake({"r1": [conv("a"), conv("b")]}, {("r1", "a"): [reply(*a)], ("r1", "b"): [reply(*b)]})
    rec = go(fake, [("s", "r1")], tmp_path, bound=65536)["records"][0]
    texts = [Path(p).read_text() for p in rec["parts"]]
    assert [len([ln for ln in t.splitlines() if ln[:2].isdigit()]) for t in texts] == [5, 1]


def test_a_day_line_counts_toward_the_bound(tmp_path):
    entry = lambda hhmm: [f"{hhmm} < " + "x" * 13096]  # noqa: E731  13105 bytes with its newline
    lines = ["=== 2026-11-04 ===", *entry("09:00"), *entry("09:01"), *entry("09:02"), *entry("09:03")]
    lines += ["=== 2026-11-05 ===", *entry("00:01")]
    c = conv("a")
    head = len((feedback.header(c, UTC) + "\n").encode())
    day = len(b"=== 2026-11-04 ===\n")
    fake = Fake({"r1": [c]}, {("r1", "a"): [reply(*lines)]})
    # five entries and one day line fit the bound; the second day line, before the fifth, passes it
    rec = go(fake, [("s", "r1")], tmp_path, bound=head + day + 5 * 13105 + day - 1)["records"][0]
    assert len(rec["parts"]) == 2
    assert Path(rec["parts"][1]).read_text().splitlines()[1] == "=== 2026-11-05 ==="


def test_a_record_named_twice_keeps_its_first_reading_and_a_next_that_does_not_move_is_an_error(tmp_path):
    fake = Fake({"r1": [conv("a")]}, {("r1", "a"): [reply("=== 2026-11-04 ===", "09:00 < a")]})
    index = go(fake, [("one", "r1"), ("two", "r1")], tmp_path)
    assert index["records"][0]["parts"] == [str(tmp_path / "r1.txt")] and (tmp_path / "r1.txt").exists()
    assert index["records"][1]["conversations"] == []
    stuck = {"at": "2026-11-04T00:00:00Z", "skip": 0}
    fake = Fake({"r2": [conv("a")]}, {("r2", "a"): [reply("=== 2026-11-04 ===", "09:00 < a", nxt=stuck)]})
    rec = go(fake, [("s", "r2")], tmp_path)["records"][0]
    assert (rec["failed"], rec["parts"]) == ("a", []) and "does not move on" in rec["error"]


def test_skips_the_callers_own_and_an_earlier_records_conversations(tmp_path):
    fake = Fake(
        {"r1": [conv("a"), conv("mine"), conv("x")], "r2": [conv("a"), conv("y"), conv("z")]},
        {(r, c): [reply("=== 2026-11-04 ===", f"09:00 < {c}")] for r in ("r1", "r2") for c in "axyz"},
    )
    index = go(fake, [("s1", "r1"), ("s2", "r2")], tmp_path, skip=["x", "z"], own="mine")
    assert [[c["id"] for c in r["conversations"]] for r in index["records"]] == [["a"], ["y"]]
    listed = go(fake, [("s1", "r1"), ("s2", "r2")], tmp_path, skip=["x", "z"], own="mine", list_only=True)
    assert [[c["id"] for c in r["conversations"]] for r in listed["records"]] == [["a"], ["y"]]
    assert listed["records"][0] == {
        "seat": "s1",
        "id": "r1",
        "marks_errors": True,
        "conversations": [conv("a")],
        "error": None,
        "failed": None,
    }


def test_a_conversation_that_writes_no_line_is_left_out_and_a_record_with_none_gets_no_file(tmp_path):
    (tmp_path / "r1.txt").write_text("stale")
    (tmp_path / "r1.3.txt").write_text("stale")
    (tmp_path / "r10.txt").write_text("another record's")
    fake = Fake({"r1": [conv("quiet")]}, {("r1", "quiet"): [{"text": "", "lines": 0, "next": None}]})
    rec = go(fake, [("s", "r1")], tmp_path)["records"][0]
    assert (rec["conversations"], rec["parts"], rec["bytes"], rec["error"]) == ([], [], 0, None)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r10.txt"]
    assert go(fake, [("s", "r1")], tmp_path, list_only=True)["records"][0]["conversations"] == [conv("quiet")]


def test_a_failure_ends_the_record_removes_its_parts_and_a_later_record_lists_all_but_the_failed(tmp_path):
    lines = ["=== 2026-11-04 ==="] + big("09:00", "<", 700)
    fake = Fake(
        {
            "r1": [conv("a"), conv("b"), conv("c")],
            "r2": [conv("a"), conv("b"), conv("c")],
            "r3": AgentError("no session"),
        },
        {
            ("r1", "a"): [reply(*lines), reply(*lines)],
            ("r1", "b"): [AgentError("did not answer")],
            ("r2", "a"): [reply("=== 2026-11-04 ===", "09:00 < a")],
            ("r2", "c"): [reply("=== 2026-11-04 ===", "09:00 < c")],
        },
        marks=False,
    )
    fake.replies[("r1", "a")] = [reply(*lines, nxt={"at": "2026-11-04T09:00:00Z", "skip": 1}), reply(*lines)]
    index = go(fake, [("s1", "r1"), ("s2", "r2"), ("s3", "r3")], tmp_path, bound=65536)
    r1, r2, r3 = index["records"]
    assert r1 == {
        "seat": "s1",
        "id": "r1",
        "marks_errors": None,
        "conversations": [],
        "parts": [],
        "bytes": 0,
        "error": "did not answer",
        "failed": "b",
    }
    assert not any(p.name.startswith("r1.") for p in tmp_path.iterdir())  # r1.1.txt was written, then removed
    assert [c["id"] for c in r2["conversations"]] == ["a", "c"]  # b, the read that failed, is read by none
    assert r2["marks_errors"] is False and r2["parts"] == [str(tmp_path / "r2.txt")]
    assert (r3["error"], r3["failed"], r3["marks_errors"], r3["parts"], r3["bytes"]) == (
        "no session",
        None,
        None,
        [],
        0,
    )
    assert not any(m == "transcript_digest" and kw["id"] == "r1" and kw["conversation"] == "c" for m, kw in fake.calls)


def test_list_with_a_failed_record_a_later_one_lists_what_it_shares(tmp_path):
    fake = Fake({"r1": AgentError("did not answer"), "r2": [conv("a")]}, {})
    index = go(fake, [("s1", "r1"), ("s2", "r2")], tmp_path, list_only=True)
    assert index["records"][0] == {
        "seat": "s1",
        "id": "r1",
        "marks_errors": None,
        "conversations": [],
        "error": "did not answer",
        "failed": None,
    }
    assert [c["id"] for c in index["records"][1]["conversations"]] == ["a"]
    assert all(m == "conversations" for m, _ in fake.calls)
    rows = feedback.list_table(index, ZoneInfo("Europe/London"))
    assert rows == ["r1  error: did not answer", "r2  a  p  2026-11-04 09:00 → 2026-11-04 10:00  10"]


def test_the_window_resolves_once_from_a_local_day_or_an_instant():
    london = ZoneInfo("Europe/London")
    assert feedback.resolve_when("2026-07-01", london) == datetime(2026, 6, 30, 23, tzinfo=UTC)
    assert feedback.resolve_when("2026-11-03T08:00:00+02:00", london) == datetime(2026, 11, 3, 6, tzinfo=UTC)
    for bad in ("2026-13-01", "yesterday", "2026-11-03T08:00:00"):
        with pytest.raises(ValueError):
            feedback.resolve_when(bad, london)
    assert feedback.local("2026-07-01T12:30:00Z", london) == "2026-07-01 13:30"


def test_the_zone_is_tz_else_etc_localtime(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/London")
    assert feedback.local_zone(datetime(2026, 7, 1, tzinfo=UTC)) == {"name": "Europe/London", "offset": 60}
    monkeypatch.setenv("TZ", ":America/New_York")
    assert feedback.local_zone(datetime(2026, 1, 1, tzinfo=UTC)) == {"name": "America/New_York", "offset": -300}
    monkeypatch.delenv("TZ")
    monkeypatch.setattr(feedback.os, "readlink", lambda p: "/usr/share/zoneinfo/Asia/Tokyo")
    assert feedback.local_zone(datetime(2026, 1, 1, tzinfo=UTC)) == {"name": "Asia/Tokyo", "offset": 540}
    monkeypatch.setenv("TZ", "Nowhere/Atall")  # a name this machine cannot resolve: no name, the system's offset
    assert feedback.local_zone(datetime(2026, 1, 1, tzinfo=UTC))["name"] is None


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["--since", "2026-11-04", "--out", "o", "--part-bytes", "65535"], "--part-bytes is at least 65536"),
        (["--since", "2026-11-04"], "--out <dir> is needed"),
        (["--since", "soon", "--list"], "neither a local day"),
    ],
)
def test_the_cli_refuses_a_bad_run_before_any_call(argv, says, capsys, monkeypatch):
    monkeypatch.setattr(cli, "call_sync", lambda *a, **k: pytest.fail("called"))
    assert cli.main(["feedback", "digest", "s", *argv]) == 2
    assert says in capsys.readouterr().err


def test_the_cli_passes_each_skip_and_exits_1_on_a_records_error(tmp_path, capsys, monkeypatch):
    fake = Fake(
        {"r1": AgentError("r1: no session"), "r2": [conv("a"), conv("x"), conv("z")]},
        {("r2", "a"): [reply("=== 2026-11-04 ===", "09:00 < a")]},
    )
    monkeypatch.setattr(cli, "call_sync", fake)
    monkeypatch.setattr(cli, "resolve", lambda seat: {"one": "r1", "two": "r2"}[seat])
    monkeypatch.setattr(feedback, "own_conversation", lambda call, caller: None)
    monkeypatch.setenv("TZ", "UTC")
    argv = ["--json", "feedback", "digest", "one", "two", "--since", "2026-11-04T00:00:00Z", "--until", "2026-11-05"]
    assert cli.main([*argv, "--skip", "x", "--skip", "z", "--out", str(tmp_path)]) == 1
    index = json.loads(capsys.readouterr().out)
    assert [(r["seat"], r["id"], r["error"]) for r in index["records"]] == [
        ("one", "r1", "r1: no session"),
        ("two", "r2", None),
    ]
    assert [c["id"] for c in index["records"][1]["conversations"]] == ["a"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["r2.txt"]


def test_a_bare_feedback_prints_its_usage_and_exits_2(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["feedback"])
    assert e.value.code == 2 and "usage: ao feedback" in capsys.readouterr().err


# ── a scratch home's record, end to end ────────────────────────────────────────────────────────


class FeedStub:
    """An adapter whose one conversation holds a failed call, a run of calls and a long prompt."""

    name, label, state_source = "fstub", "Stub", "hook"
    implements = frozenset({"conversations"})
    marks_errors = True

    def launch(self, **_):
        return adapters.LaunchSpec(argv=["bash", "--norc", "--noprofile"], adapter_id="mine")

    def classify(self, pane, tail):
        return None

    def conversations(self, cwd, profile):
        return [
            Conversation("c1", "2026-11-04T09:00:00Z", "2026-11-04T09:10:00Z", 99),
            Conversation("mine", "2026-11-04T09:00:00Z", "2026-11-04T09:10:00Z", 1),
        ]

    def read_transcript(self, session_id, cwd, profile, *, before=None, turns=20, raw=False):
        e = [
            TranscriptEntry(kind="prompt", at="2026-11-04T09:00:00Z", text="do it\n2\n3\n4"),
            TranscriptEntry(kind="tool", at="2026-11-04T09:01:00Z", name="Bash", call="ls", result="no", error=True),
            TranscriptEntry(kind="tool", at="2026-11-04T09:02:00Z", name="Read", call="f", result="ok"),
            TranscriptEntry(kind="tool", at="2026-11-04T09:02:30Z", name="Read", call="g", result="ok"),
            TranscriptEntry(kind="text", at="2026-11-04T09:03:00Z", text="done"),
        ]
        return Transcript(path="/f", size=1, first_at="2026-11-04T09:00:00Z", entries=e)


@pytest.mark.integration
async def test_ao_feedback_digest_over_a_scratch_homes_record(agent, tmp_path, monkeypatch, capsys):
    adapters.load_all()
    monkeypatch.setitem(adapters._REGISTRY, "fstub", FeedStub())
    monkeypatch.setenv("TZ", "UTC")
    async with LocalClient() as person:
        sid = (await person.call("create", name="fb", dir=str(tmp_path), adapter="fstub"))["id"]
    monkeypatch.setattr(feedback, "own_conversation", lambda call, caller: "mine")
    out = tmp_path / "out"
    argv = ["--json", "feedback", "digest", sid, "--since", "2026-11-04", "--until", "2026-11-05", "--out", str(out)]
    assert await asyncio.to_thread(cli.main, argv) == 0
    index = json.loads(capsys.readouterr().out)
    assert index["since"] == "2026-11-04T00:00:00Z" and index["until"] == "2026-11-05T00:00:00Z"
    rec = index["records"][0]
    assert [c["id"] for c in rec["conversations"]] == ["c1"] and rec["marks_errors"] is True
    assert (out / f"{sid}.txt").read_text() == (
        "## c1 ·  · 2026-11-04 09:00 → 2026-11-04 09:10\n"
        "=== 2026-11-04 ===\n"
        "09:00 > do it\n  2\n  3\n  (+1 lines)\n"
        "09:01 ✗ Bash(ls) → no\n"
        "09:02 · 2 calls (Read 2)\n"
        "09:03 < done\n"
    )
    assert await asyncio.to_thread(cli.main, ["feedback", "digest", sid, "--since", "2026-11-04", "--list"]) == 0
    assert capsys.readouterr().out.split() == [sid, "c1", "2026-11-04", "09:00", "→", "2026-11-04", "09:10", "99"]
    async with LocalClient() as person:
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)
