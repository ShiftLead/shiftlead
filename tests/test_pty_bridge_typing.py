"""Typing returns the pane to the live screen (design §4.6, TD-667 / TD-669 slice 1): the bridge marks
itself *scrolled* on any scroll message, and a key frame that counts as typing while the mark stands
leaves tmux's copy mode — awaited — before it is written. Everything else stays copy mode's."""

from __future__ import annotations

import asyncio

import pytest

from shiftlead.ui import pty_bridge
from shiftlead.ui.pty_bridge import counts_as_typing, leave_argv, pump

pytestmark = pytest.mark.unit

# xterm.js's replies to the program's queries come down the same channel as keys (app.js onData)
REPLIES = (b"\x1b[?1;2c", b"\x1b[24;80R", b"\x1b[I")


class FakePty:
    def __init__(self, log: list):
        self.log = log
        self._end = asyncio.Event()

    async def read(self):
        await self._end.wait()
        return None

    def write(self, data: bytes) -> None:
        self.log.append(("write", data))

    def resize(self, cols: int, rows: int) -> None:
        pass

    def close(self) -> None:
        self._end.set()


async def _run(frames: list, *, read_only: bool = False, leave_takes: float = 0.0, leave_fails: bool = False):
    log: list = []
    pty = FakePty(log)
    queue = list(frames)

    async def recv():
        await asyncio.sleep(0)
        return queue.pop(0) if queue else None

    async def send(data: bytes) -> None:
        pass

    async def scroll(direction: str, lines: int | None) -> None:
        await asyncio.sleep(0.01)  # a scroll's command takes time; the leave after it must wait
        log.append(("scroll", direction))

    async def leave() -> None:
        log.append(("leave-start",))
        await asyncio.sleep(leave_takes)
        if leave_fails:
            raise RuntimeError("tmux failed")
        log.append(("leave",))

    await asyncio.wait_for(pump(pty, send, recv, scroll, leave=leave, read_only=read_only), 10)
    return log


def _kinds(log: list) -> list:
    return [e[0] for e in log if e[0] != "leave-start"]


def test_counts_as_typing():
    for frame in (b"x", b"hello", "é".encode(), b"\r", b"\t", b"\x7f", b"\b", b"\x1b[200~text\x1b[201~", b"a\r"):
        assert counts_as_typing(frame), frame
    for frame in (b"\x1b[A", b"\x1bOP", b"\x1bx", b"\x1b", b"\x03", b"\x04", *REPLIES):
        assert not counts_as_typing(frame), frame


def test_a_printable_key_after_a_scroll_leaves_once_then_writes():
    log = asyncio.run(_run([{"scroll": "up", "lines": 3}, "x", "y"]))
    assert _kinds(log) == ["scroll", "leave", "write", "write"]
    assert [e[1] for e in log if e[0] == "write"] == [b"x", b"y"]


def test_keys_that_stay_copy_modes_never_leave():
    frames = [{"scroll": "up"}, "\x1b[A", "\x1b", "\x1bx", "\x03", *(r.decode() for r in REPLIES)]
    log = asyncio.run(_run(frames))
    assert "leave" not in _kinds(log) and _kinds(log).count("write") == 7


def test_a_burst_a_paste_and_enter_each_leave_after_a_scroll():
    for frame in ("burst of text", "\x1b[200~pasted\x1b[201~", "\r", b"\x7f"):
        log = asyncio.run(_run([{"scroll": "up"}, frame]))
        assert _kinds(log) == ["scroll", "leave", "write"], frame


def test_no_scroll_no_leave_and_a_new_scroll_sets_the_mark_again():
    assert _kinds(asyncio.run(_run(["x", "\r"]))) == ["write", "write"]
    log = asyncio.run(_run([{"scroll": "up"}, "x", {"scroll": "down", "lines": 1}, "y"]))
    assert _kinds(log) == ["scroll", "leave", "write", "scroll", "leave", "write"]


def test_a_read_only_pump_leaves_nothing_and_writes_nothing():
    log = asyncio.run(_run([{"scroll": "up"}, "x", "\r"], read_only=True))
    assert _kinds(log) == ["scroll"]


def test_a_slow_or_failed_leave_is_bounded_logged_and_the_key_written_anyway(monkeypatch, caplog):
    monkeypatch.setattr(pty_bridge, "LEAVE_WITHIN", 0.05)
    with caplog.at_level("WARNING", logger=pty_bridge.__name__):
        log = asyncio.run(_run([{"scroll": "up"}, "x"], leave_takes=5))
        assert _kinds(log) == ["scroll", "write"]  # the leave never finished; the key went all the same
        log = asyncio.run(_run([{"scroll": "up"}, "x"], leave_fails=True))
        assert _kinds(log) == ["scroll", "write"]
    found = [r.getMessage() for r in caplog.records if "leaving copy mode" in r.getMessage()]
    assert len(found) == 2 and "TimeoutError" in found[0] and "RuntimeError" in found[1]


def test_the_leave_argv():
    assert leave_argv("ao-x") == ["tmux", "copy-mode", "-q", "-t", "=ao-x:"]
    assert leave_argv("ao-x", socket_name="s")[:3] == ["tmux", "-L", "s"]
