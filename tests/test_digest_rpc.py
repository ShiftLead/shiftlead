"""The digest's two reads (design §4.7 *Feedback*, TD-1491, TD-1716): `conversations` over every profile the
adapter lists and `transcript_digest` over one conversation, each bounded by DIGEST_TIMEOUT and read off the
host agent's loop; and the home's forward of either to a node's record at that bound."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from sessionorc import adapters
from sessionorc.adapters import Conversation, Transcript, TranscriptEntry
from sessionorc.agent_common import ACT_TIMEOUT, DIGEST_TIMEOUT, NODE_READS
from sessionorc.agent_remote import RemoteMixin
from sessionorc.client import AgentError, LocalClient
from sessionorc.identity import READS

C = Conversation


class DigestStub:
    """An adapter with conversations under three profiles: `p` (the record's), `q`, and `gone` (unknown)."""

    name, label, state_source = "dstub", "Stub", "hook"
    implements = frozenset({"conversations"})
    marks_errors = True
    gate: threading.Event | None = None
    listed = ("q", "gone")
    bare: tuple = ()  # conversations under `p` with no instants, added by a test

    def launch(self, **_):
        return adapters.LaunchSpec(argv=["bash", "--norc", "--noprofile"], adapter_id="tool-1")

    def classify(self, pane, tail):
        return None

    def profiles(self):
        return [{"name": n} for n in self.listed]

    def conversations(self, cwd, profile):
        return {
            "p": [C("b", "2026-11-04T09:00:00Z", "2026-11-04T10:00:00Z", 5), *self.bare],
            "q": [
                C("a", "2026-11-03T08:00:00Z", "2026-11-04T08:30:00Z", 7),
                C("b", "2026-11-04T09:00:00Z", "2026-11-04T10:00:00Z", 5),
                C("old", "2026-11-01T08:00:00Z", "2026-11-01T09:00:00Z", 3),
            ],
        }.get(profile)

    def read_transcript(self, session_id, cwd, profile, *, before=None, turns=20, raw=False):
        if self.gate is not None:
            self.gate.wait(10)
        if session_id == "missing":
            return None
        e = [
            TranscriptEntry(kind="prompt", at="2026-11-04T09:00:00Z", text=f"{session_id} {profile} {turns}"),
            TranscriptEntry(kind="text", at="2026-11-04T09:01:00Z", text="done"),
        ]
        return Transcript(path="/f", size=1, first_at="2026-11-04T09:00:00Z", entries=e)


class QuietStub(DigestStub):
    """The same listing from an adapter whose transcripts do not mark a failed call."""

    name = "quiet"
    marks_errors = False


class NoListStub(DigestStub):
    name = "nolist"
    implements = frozenset()
    conversations = None  # type: ignore[assignment]


def test_both_reads_are_node_reads_and_never_gated():
    assert {"conversations", "transcript_digest"} <= NODE_READS
    assert {"conversations", "transcript_digest"} <= READS
    assert DIGEST_TIMEOUT == 300.0


@pytest.fixture
def stubs(monkeypatch):
    adapters.load_all()
    stub = DigestStub()
    monkeypatch.setitem(adapters._REGISTRY, "dstub", stub)
    monkeypatch.setitem(adapters._REGISTRY, "nolist", NoListStub())
    monkeypatch.setitem(adapters._REGISTRY, "quiet", QuietStub())
    return stub


@pytest.mark.integration
async def test_conversations_ask_every_profile_once_per_id_oldest_first(agent, tmp_path, stubs):
    async with LocalClient() as person:
        sid = (await person.call("create", name="d", dir=str(tmp_path), adapter="dstub", profile="p"))["id"]
        got = await person.call("conversations", id=sid, since="2026-11-04T00:00:00Z", until="2026-11-05T00:00:00Z")
        assert got == {
            "marks_errors": True,
            "conversations": [
                {
                    "id": "a",
                    "first_at": "2026-11-03T08:00:00Z",
                    "last_at": "2026-11-04T08:30:00Z",
                    "size": 7,
                    "profile": "q",
                },
                {
                    "id": "b",
                    "first_at": "2026-11-04T09:00:00Z",
                    "last_at": "2026-11-04T10:00:00Z",
                    "size": 5,
                    "profile": "p",
                },
            ],
        }  # `old` ends before the window; `b` under the record's own profile; `gone` answers None: none
        stubs.listed = ()  # an adapter whose profiles() omits the record's own: it is asked anyway
        got = await person.call("conversations", id=sid)
        assert [c["id"] for c in got["conversations"]] == ["b"]
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


@pytest.mark.integration
async def test_conversations_window_is_half_open_and_skips_a_conversation_with_no_instants(agent, tmp_path, stubs):
    async with LocalClient() as person:
        sid = (await person.call("create", name="d", dir=str(tmp_path), adapter="dstub", profile="p"))["id"]
        (tmp_path / "quiet").mkdir()
        quiet = (await person.call("create", name="qt", dir=str(tmp_path / "quiet"), adapter="quiet", profile="p"))[
            "id"
        ]
        # `[since, until)`: `a` ends exactly at since and is kept; `b` starts exactly at until and is dropped
        got = await person.call("conversations", id=sid, since="2026-11-04T08:30:00Z", until="2026-11-04T09:00:00Z")
        assert [c["id"] for c in got["conversations"]] == ["a"]
        # a conversation whose instants do not parse is skipped, window or none
        stubs.bare = (C("noat", "", "", 1), C("naive", "2026-11-04T09:00:00", "2026-11-04T09:30:00", 1))
        got = await person.call("conversations", id=sid)
        assert [c["id"] for c in got["conversations"]] == ["old", "a", "b"]
        got = await person.call("conversations", id=sid, since="2026-11-04T00:00:00Z", until="2026-11-05T00:00:00Z")
        assert [c["id"] for c in got["conversations"]] == ["a", "b"]
        stubs.bare = ()
        # a malformed bound is refused, never read as unset
        for bound in ("since", "until"):
            for bad in ("2026-11-04", "2026-11-04T08:00:00", "yesterday", 5):
                with pytest.raises(AgentError, match=f"{bound} is an RFC 3339 instant with its offset"):
                    await person.call("conversations", id=sid, **{bound: bad})
        # marks_errors is the adapter's own: true for one that marks a failed call, false for one that does not
        assert (await person.call("conversations", id=sid))["marks_errors"] is True
        assert (await person.call("conversations", id=quiet))["marks_errors"] is False
        for s in (sid, quiet):
            await person.call("kill", id=s)
            await person.call("remove", id=s)


@pytest.mark.integration
async def test_a_digest_refuses_a_missing_conversation_or_window_and_a_bad_skip(agent, tmp_path, stubs):
    async with LocalClient() as person:
        sid = (await person.call("create", name="d", dir=str(tmp_path), adapter="dstub", profile="p"))["id"]
        window = {"since": "2026-11-04T00:00:00Z", "until": "2026-11-05T00:00:00Z"}
        for conv in ({}, {"conversation": ""}, {"conversation": 5}):
            with pytest.raises(AgentError, match="needs the conversation's id"):
                await person.call("transcript_digest", id=sid, profile="p", **conv, **window)
        for drop in ("since", "until"):
            part = {k: v for k, v in window.items() if k != drop}
            with pytest.raises(AgentError, match="needs since and until"):
                await person.call("transcript_digest", id=sid, conversation="b", profile="p", **part)
        with pytest.raises(AgentError, match="since is an RFC 3339 instant"):
            await person.call("transcript_digest", id=sid, conversation="b", profile="p", since="x", until="y")
        for skip in (-1, True, "1", 1.0):
            with pytest.raises(AgentError, match="skip is a count"):
                await person.call("transcript_digest", id=sid, conversation="b", profile="p", skip=skip, **window)
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


@pytest.mark.integration
async def test_the_reads_refuse_a_shell_an_adapter_with_no_listing_and_an_unknown_own_profile(agent, tmp_path, stubs):
    async with LocalClient() as person:
        sh = (await person.call("create", name="sh", dir=str(tmp_path), adapter="shell", argv=["bash", "--norc"]))["id"]
        (tmp_path / "nl").mkdir()
        (tmp_path / "g").mkdir()
        nl = (await person.call("create", name="nl", dir=str(tmp_path / "nl"), adapter="nolist"))["id"]
        gone = (await person.call("create", name="g", dir=str(tmp_path / "g"), adapter="dstub", profile="gone"))["id"]
        with pytest.raises(AgentError, match="a shell has no transcript"):
            await person.call("conversations", id=sh)
        with pytest.raises(AgentError, match="a shell has no transcript"):
            await person.call("transcript_digest", id=sh, conversation="x", profile="")
        with pytest.raises(AgentError, match="the nolist adapter lists no conversations"):
            await person.call("conversations", id=nl)
        with pytest.raises(AgentError, match=f"{gone}'s profile gone is unknown to the dstub adapter"):
            await person.call("conversations", id=gone)
        for s in (sh, nl, gone):
            await person.call("kill", id=s)
            await person.call("remove", id=s)


@pytest.mark.integration
async def test_a_digest_is_read_off_the_loop_and_bounded(agent, tmp_path, stubs, monkeypatch):
    async with LocalClient() as person:
        sid = (await person.call("create", name="d", dir=str(tmp_path), adapter="dstub", profile="p"))["id"]
        window = {"since": "2026-11-04T00:00:00Z", "until": "2026-11-05T00:00:00Z"}
        got = await person.call(
            "transcript_digest", id=sid, conversation="b", profile="q", zone={"name": "UTC", "offset": 0}, **window
        )
        assert got == {"text": "=== 2026-11-04 ===\n09:00 > b q 100\n09:01 < done", "lines": 3, "next": None}
        with pytest.raises(AgentError, match="needs the profile"):
            await person.call("transcript_digest", id=sid, conversation="b", **window)
        with pytest.raises(AgentError, match="the tool's file is not on"):
            await person.call("transcript_digest", id=sid, conversation="missing", profile="p", **window)
        # another RPC is answered while a digest's read is held
        stubs.gate = threading.Event()
        slow = asyncio.create_task(person.call("transcript_digest", id=sid, conversation="b", profile="p", **window))
        await asyncio.sleep(0.2)
        async with LocalClient() as other:
            assert any(r["id"] == sid for r in await other.call("list"))
        assert not slow.done()
        stubs.gate.set()
        assert (await slow)["lines"] == 3
        # the handler's bound, on a record of its own host
        stubs.gate = threading.Event()
        monkeypatch.setattr("sessionorc.agent.DIGEST_TIMEOUT", 0.2)
        with pytest.raises(AgentError, match="did not finish within 0.2 s"):
            await person.call("transcript_digest", id=sid, conversation="b", profile="p", **window)
        stubs.gate.set()
        stubs.gate = None
        await person.call("kill", id=sid)
        await person.call("remove", id=sid)


@pytest.mark.parametrize(
    ("method", "bound"),
    [("transcript_digest", DIGEST_TIMEOUT), ("conversations", DIGEST_TIMEOUT), ("transcript", ACT_TIMEOUT)],
)
async def test_the_home_forwards_a_digest_read_at_its_own_bound(method, bound):
    asked: dict = {}

    class Mux:
        async def request(self, name, timeout=None, **kw):
            asked.update(name=name, timeout=timeout, **kw)
            return {"ok": True}

    home = SimpleNamespace(remote={"node": {"r1": object()}}, _node_mux=lambda host: Mux(), host="home")
    home._from_host = lambda a, host: a
    got = await RemoteMixin._route_read(home, method, {"id": "r1@node", "since": "x"}, "node")
    assert got == {"ok": True}
    assert asked == {"name": "read", "timeout": bound, "rpc": method, "params": {"id": "r1", "since": "x"}}
