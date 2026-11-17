"""The pty bridge logs one `term resize <name> <cols>x<rows>` line per resize message (#4041, TD-1917): the
line names the session the Focus terminal attached to, so a garbled repaint can be lined up with the grids
the page sent before it, and its values are ints, so a client's odd value never reaches the log."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest
from test_ui_teams import client, world  # noqa: F401 — the fixtures, by name

from shiftlead.ui import app as uiapp
from shiftlead.ui.pty_bridge import pump

pytestmark = pytest.mark.unit

LOGGER = "shiftlead.ui.pty_bridge"


class FakePty:
    """A pty that reads nothing until it is closed and records each resize."""

    def __init__(self, *_argv, **_size):
        self.resizes: list[tuple[int, int]] = []
        self._end = asyncio.Event()

    async def read(self):
        await self._end.wait()
        return None

    def write(self, data: bytes) -> None:
        pass

    def resize(self, cols: int, rows: int) -> None:
        self.resizes.append((cols, rows))

    def close(self) -> None:
        self._end.set()

    def exit_status(self):
        return None


def _resize_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER and r.getMessage().startswith("term resize")]


def test_each_resize_message_logs_one_line_naming_the_session_and_its_int_grid(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    pty = FakePty()
    frames = [{"resize": [100, 30]}, {"resize": ["81", 24.0]}, "x"]

    async def recv():
        await asyncio.sleep(0)
        return frames.pop(0) if frames else None

    async def send(data: bytes) -> None:
        pass

    asyncio.run(asyncio.wait_for(pump(pty, send, recv, name="ao-w"), 10))
    assert _resize_lines(caplog) == ["term resize ao-w 100x30", "term resize ao-w 81x24"]
    assert pty.resizes == [(100, 30), (81, 24)]


def test_a_pump_given_no_name_logs_a_dash(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    frames = [{"resize": [90, 20]}]

    async def recv():
        await asyncio.sleep(0)
        return frames.pop(0) if frames else None

    async def send(data: bytes) -> None:
        pass

    asyncio.run(asyncio.wait_for(pump(FakePty(), send, recv), 10))
    assert _resize_lines(caplog) == ["term resize - 90x20"]


def test_the_focus_terminal_names_its_session_in_the_resize_line(world, client, monkeypatch, caplog):  # noqa: F811
    """The `/term/<id>` handler passes its session id to `pump`, so the line names the attached session."""
    _tmp, fleet = world
    fleet.sessions.append({"id": "ao-w", "name": "w", "state": "working", "pane": True})
    monkeypatch.setattr(uiapp, "PtySession", FakePty)

    async def no_watch(*_a, **_k):
        return None

    monkeypatch.setattr(uiapp, "watch_clients", no_watch)  # no tmux read in a unit test
    caplog.set_level(logging.INFO, logger=LOGGER)
    with client.websocket_connect("/term/ao-w") as ws:
        ws.send_text('{"resize": [132, 40]}')
    for _ in range(100):  # the handler runs on the test client's loop: wait for the line, bounded
        if _resize_lines(caplog):
            break
        time.sleep(0.02)
    assert _resize_lines(caplog) == ["term resize ao-w 132x40"]
