"""A read on a daemon thread never holds a stopping host agent (TD-2001): `asyncio.run` joins the loop's executor at
exit, so the Tools read's `--version` probes, run by `asyncio.to_thread`, held a SIGTERM'd agent past its stop."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from sessionorc import agent_common


def test_a_cancelled_read_ends_its_loop_at_once():
    gate = threading.Event()

    def slow() -> str:
        gate.wait(30)
        return "late"

    async def main() -> None:
        task = asyncio.create_task(agent_common.in_daemon_thread(slow))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    t0 = time.monotonic()
    asyncio.run(main())
    assert time.monotonic() - t0 < 5  # `asyncio.to_thread` here waits the whole 30s
    gate.set()


def test_a_read_hands_back_its_value_and_its_error():
    def boom() -> None:
        raise ValueError("no")

    async def main() -> None:
        assert await agent_common.in_daemon_thread(lambda a, b=0: a + b, 1, b=2) == 3
        with pytest.raises(ValueError, match="no"):
            await agent_common.in_daemon_thread(boom)

    asyncio.run(main())
