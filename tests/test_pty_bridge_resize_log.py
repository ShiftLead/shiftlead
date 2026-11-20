"""The pty bridge's grid (design §4.6 *Attach behaviour with another client present*, *Fit to window*, TD-1919):
a session's window is pinned, so a `resize` message changes nothing (logged once per attach); a `fit` within
`person.terminal.grid`'s bounds is logged as one `term fit <name> <cols>x<rows>` line and carried out — the window,
read again, the pty, and the `grid` frame — and one outside them is refused. The five-second reading and a fit
share one last-sent grid, so a changed reading resizes the bridge's own pty before its frame goes and a reading
taken before a fit is dropped rather than sent after it."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import pytest
from test_ui_teams import client, world  # noqa: F401 — the fixtures, by name

from shiftlead.ui import app as uiapp
from shiftlead.ui.pty_bridge import GridKeeper, fit_grid, grid_argv, grid_read, pump, resize_window_argv

pytestmark = pytest.mark.unit

LOGGER = "shiftlead.ui.pty_bridge"


class FakePty:
    """A pty that reads nothing until it is closed and records the grid it opened at and each resize."""

    def __init__(self, *_argv, **size):
        self.opened = (size.get("cols"), size.get("rows"))
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


def _lines(caplog, start: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == LOGGER and r.getMessage().startswith(start)]


def _run_pump(frames: list, **kw) -> list:
    fits: list = []

    async def recv():
        await asyncio.sleep(0)
        return frames.pop(0) if frames else None

    async def send(data: bytes) -> None:
        pass

    async def fit(grid):
        fits.append(grid)

    asyncio.run(asyncio.wait_for(pump(kw.pop("pty", FakePty()), send, recv, fit=fit, **kw), 10))
    return fits


def test_a_fit_within_the_bounds_logs_one_line_and_is_carried_out(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    fits = _run_pump([{"fit": [100, 30]}, {"fit": [20, 5]}, {"fit": [500, 200]}, "x"], name="ao-w")
    assert fits == [(100, 30), (20, 5), (500, 200)]
    assert _lines(caplog, "term fit") == ["term fit ao-w 100x30", "term fit ao-w 20x5", "term fit ao-w 500x200"]


def test_a_fit_outside_the_bounds_is_refused_and_logged(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    bad = [[19, 30], [100, 4], [501, 30], [100, 201], ["81", 24], [81.0, 24], [True, 24], [100], "100x30"]
    fits = _run_pump([{"fit": b} for b in bad], name="ao-w")
    assert fits == [] and _lines(caplog, "term fit") == []
    assert len(_lines(caplog, "term ao-w: a fit outside")) == len(bad)
    assert fit_grid([100, 30]) == (100, 30) and fit_grid([19, 30]) is None


def test_a_resize_changes_nothing_and_is_logged_once_per_attach(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER)
    pty = FakePty()
    _run_pump([{"resize": [100, 30]}, {"resize": [81, 24]}], pty=pty, name="ao-w")
    assert pty.resizes == []
    assert len(_lines(caplog, "term ao-w: a resize message changes nothing")) == 1


def test_a_read_only_attach_passes_a_fit():
    """It types nothing, so an `unattended` session is fitted without a Take over (design §4.6)."""
    assert _run_pump([{"fit": [90, 20]}, "x"], read_only=True) == [(90, 20)]


def test_the_reading_and_the_argvs():
    assert grid_read("120 40 off\n") == (120, 40)
    assert grid_read("120 39 on") == (120, 40), "the status bar's lines count, as a client's grid counts them"
    assert grid_read("120 38 2") == (120, 40)
    assert grid_read(None) is None and grid_read("") is None and grid_read("1 120 40 off") is None
    assert grid_argv("ao-x", socket_name="s") == [
        *("tmux", "-L", "s", "display-message", "-p", "-t", "=ao-x:"),
        "#{window_width} #{window_height} #{status}",
    ]
    assert resize_window_argv("ao-x", 90, 20) == ["tmux", "resize-window", "-t", "=ao-x:", "-x", "90", "-y", "20"]


def _keeper(readings: list, sent=(120, 40)):
    pty, frames = FakePty(), []

    async def read():
        await asyncio.sleep(0)
        return readings.pop(0) if readings else None

    async def send_text(t: str):
        frames.append(json.loads(t))

    return GridKeeper(pty, read, send_text, sent), pty, frames


def test_a_changed_reading_resizes_the_pty_before_its_frame_and_an_equal_one_sends_nothing():
    async def go():
        k, pty, frames = _keeper(["120 40 off", None, "100 30 off", "100 30 off"])
        w = asyncio.ensure_future(k.watch(every=0.001))
        for _ in range(200):
            await asyncio.sleep(0.001)
        w.cancel()
        return pty, frames

    pty, frames = asyncio.run(go())
    assert pty.resizes == [(100, 30)] and frames == [{"grid": [100, 30]}]


def test_a_fit_resizes_the_window_reads_it_again_and_answers_with_what_it_kept():
    async def go(reading):
        k, pty, frames = _keeper([reading])
        ran = []

        async def resize(g):
            ran.append(g)

        await k.fit((90, 20), resize)
        return ran, pty.resizes, frames

    assert asyncio.run(go("90 20 off")) == ([(90, 20)], [(90, 20)], [{"grid": [90, 20]}])
    # a failed command: the window kept its grid, and the answer says so, the pty untouched
    assert asyncio.run(go("120 40 off")) == ([(90, 20)], [], [{"grid": [120, 40]}])


def test_a_watcher_reading_taken_before_a_fit_is_dropped():
    async def go():
        gate = asyncio.Event()
        k, pty, frames = _keeper([])

        async def stale_read():  # the watcher's read, still in flight when the fit runs
            await gate.wait()
            return "120 40 off"

        k.read = stale_read
        w = asyncio.ensure_future(k.watch(every=0))
        await asyncio.sleep(0.01)

        async def fresh_read():
            return "90 20 off"

        k.read = fresh_read
        await k.fit((90, 20), lambda g: asyncio.sleep(0))
        gate.set()
        await asyncio.sleep(0.01)
        w.cancel()
        return pty.resizes, frames

    resizes, frames = asyncio.run(go())
    assert frames == [{"grid": [90, 20]}], "the stale 120 x 40 reading is never sent after the fit"
    assert resizes == [(90, 20)]


def test_the_focus_terminal_opens_at_the_window_and_sends_its_grid_first(world, client, monkeypatch, caplog):  # noqa: F811
    """The `/term/<id>` handler reads the window before it attaches, opens the pty at it whatever the address
    says, sends `{"grid": …}` before any pane byte, and passes its session id to `pump` for the fit line."""
    _tmp, fleet = world
    fleet.sessions.append({"id": "ao-w", "name": "w", "state": "working", "pane": True})
    made: list[FakePty] = []
    monkeypatch.setattr(uiapp, "PtySession", lambda *a, **k: made.append(FakePty(*a, **k)) or made[-1])

    async def no_watch(self, every=5.0):
        return None

    monkeypatch.setattr(uiapp.GridKeeper, "watch", no_watch)  # no five-second reading in a unit test
    monkeypatch.setattr(uiapp.asyncio, "create_subprocess_exec", _fake_exec("97 31 off"))
    caplog.set_level(logging.INFO, logger=LOGGER)
    with client.websocket_connect("/term/ao-w?cols=300&rows=100") as ws:
        assert json.loads(ws.receive_text()) == {"grid": [97, 31]}
        ws.send_text('{"fit": [132, 40]}')
        for _ in range(100):  # the handler runs on the test client's loop: wait for the line, bounded
            if _lines(caplog, "term fit"):
                break
            time.sleep(0.02)
    assert made and made[0].opened == (97, 31), "the address's cols and rows are ignored"
    assert _lines(caplog, "term fit") == ["term fit ao-w 132x40"]


def test_a_failed_reading_opens_at_the_persons_grid(world, client, monkeypatch):  # noqa: F811
    _tmp, fleet = world
    fleet.sessions.append({"id": "ao-w", "name": "w", "state": "working", "pane": True})
    made: list[FakePty] = []
    monkeypatch.setattr(uiapp, "PtySession", lambda *a, **k: made.append(FakePty(*a, **k)) or made[-1])

    async def no_watch(self, every=5.0):
        return None

    monkeypatch.setattr(uiapp.GridKeeper, "watch", no_watch)
    monkeypatch.setattr(uiapp.asyncio, "create_subprocess_exec", _fake_exec(None))
    monkeypatch.setattr(uiapp.settings_mod, "load", lambda: {"person": {"terminal": {"grid": [88, 22]}}})
    with client.websocket_connect("/term/ao-w") as ws:
        assert json.loads(ws.receive_text()) == {"grid": [88, 22]}
    assert made[0].opened == (88, 22)
    monkeypatch.setattr(uiapp.settings_mod, "load", lambda: {})
    with client.websocket_connect("/term/ao-w") as ws:
        assert json.loads(ws.receive_text()) == {"grid": [120, 40]}, "nothing set: 120 x 40"


def _fake_exec(out: str | None):
    """`asyncio.create_subprocess_exec` for the handler's tmux reads: `out` from `display-message`, or a failure."""

    class Proc:
        def __init__(self):
            self.returncode = None

        async def communicate(self):
            self.returncode = 0 if out is not None else 1
            return (out or "").encode(), b""

        async def wait(self):
            self.returncode = 0
            return 0

        def kill(self):
            pass

    async def fake(*_argv, **_kw):
        return Proc()

    return fake
