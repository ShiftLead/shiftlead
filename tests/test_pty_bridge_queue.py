"""The pty bridge's queue (TD-611 slice 5): the Focus terminal shares the UI's one asyncio loop, so
whatever stalls the loop holds its output back. What piled up meanwhile goes as one chunk, never one
send per pty read, and the queue is bounded in bytes: past `QUEUE_HIGH` the pty is no longer read
(tmux holds the output, as for any slow client) until the reader has drained it."""

from __future__ import annotations

import asyncio

import pytest

from shiftlead.ui import pty_bridge
from shiftlead.ui.pty_bridge import PtySession

pytestmark = pytest.mark.unit


async def _drain(pty: PtySession) -> list[bytes]:
    got = []
    while (chunk := await asyncio.wait_for(pty.read(), 10)) is not None:
        got.append(chunk)
    return got


def test_what_queued_while_the_loop_was_busy_is_read_as_one_chunk_and_the_end_after_it():
    async def run():
        pty = PtySession(["sh", "-c", "printf one; sleep 0.05; printf two; sleep 0.05; printf three"])
        try:
            for _ in range(100):  # the loop reads the pty meanwhile; nobody takes from the queue
                if pty._queue.qsize() and not pty.proc.isalive():
                    break
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.2)  # the end's own read
            first = await pty.read()
            rest = await _drain(pty)
        finally:
            pty.close()
        return first, rest

    first, rest = asyncio.run(run())
    assert first == b"onetwothree" and rest == []


def test_a_closed_bridge_never_reads_the_pty_again_and_an_ended_one_stays_ended(monkeypatch):
    monkeypatch.setattr(pty_bridge, "QUEUE_HIGH", 4096)

    async def run():
        ended = PtySession(["true"])
        try:
            got = await _drain(ended)
            again = await asyncio.wait_for(ended.read(), 1)
        finally:
            ended.close()
        pty = PtySession(["sh", "-c", "head -c 100000 /dev/zero; sleep 5"])
        await asyncio.sleep(0.5)
        assert pty._paused
        pty.close()
        added = []
        monkeypatch.setattr(pty._loop, "add_reader", lambda *a: added.append(a))
        await pty.read()  # drains below the low mark: a closed bridge adds no reader back
        return added, got, again

    added, got, again = asyncio.run(run())
    assert added == [] and got == [] and again is None


def test_past_the_high_mark_the_pty_is_not_read_until_the_queue_drains_and_nothing_is_lost(monkeypatch):
    monkeypatch.setattr(pty_bridge, "QUEUE_HIGH", 4096)
    monkeypatch.setattr(pty_bridge, "QUEUE_LOW", 1024)
    monkeypatch.setattr(pty_bridge, "JOIN_MAX", 2048)
    n = 300_000

    async def run():
        pty = PtySession(["sh", "-c", f"head -c {n} /dev/zero"])
        try:
            await asyncio.sleep(0.5)
            held = (pty._paused, pty._queued)
            chunks = await _drain(pty)
        finally:
            pty.close()
        return held, chunks

    (paused, queued), chunks = asyncio.run(run())
    assert paused and queued < 4096 + 65536  # one read past the mark at most, never the whole output
    assert sum(len(c) for c in chunks) == n and set(b"".join(chunks)) == {0}
    assert max(len(c) for c in chunks) < 2048 + 65536  # one read joins up to the cap, and one pty read past it
