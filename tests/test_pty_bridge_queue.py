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
            await asyncio.sleep(0.6)  # the loop reads the pty meanwhile; nobody takes from the queue
            assert pty._queue.qsize() >= 3  # three writes, three reads at least, and the end
            first = await pty.read()
            rest = await _drain(pty)
        finally:
            pty.close()
        return first, rest

    first, rest = asyncio.run(run())
    assert first == b"onetwothree" and rest == []


def test_past_the_high_mark_the_pty_is_not_read_until_the_queue_drains_and_nothing_is_lost(monkeypatch):
    monkeypatch.setattr(pty_bridge, "QUEUE_HIGH", 4096)
    monkeypatch.setattr(pty_bridge, "QUEUE_LOW", 1024)
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
