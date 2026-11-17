"""tmux's own history survives a client's resizes and reattaches (the 2026-11-16 repaint hunt).

Focus resizes the pane to the browser's grid and reattaches a client on every reload, so a line that is
repeated or missing in a pane has to come from tmux or from the program drawing in it. This is the control:
a program that only prints (it never erases or repaints) writes thirty long, uniquely labelled lines while
the attached client changes width, height and sizes; every line must be in tmux's history once. It holds,
so the duplicated and missing paragraphs seen with Claude Code (`test_resize_repaint_live.py`) are the
repaint, not tmux's reflow.
"""

from __future__ import annotations

import contextlib
import os
import re
import select
import subprocess
import time
from collections import Counter

import pytest
from conftest import kill_private_server, private_socket_name

from sessionorc.tmux import Tmux, attach_argv

ptyprocess = pytest.importorskip("ptyprocess")

pytestmark = pytest.mark.integration

LINES = 30
# one long line per label (about 170 characters, so it wraps at 100 columns and again at 98 or 101)
PRINTER = (
    "for i in $(seq -w 1 30); do printf 'L%s %s\\n' \"$i\" "
    '"alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau '
    'upsilon phi chi psi omega alpha beta gamma delta"; sleep 0.12; done; sleep 600'
)
SIZES = [(99, 20), (101, 20), (98, 20), (100, 20)]
SEQUENCES = {
    "none": [],
    "columns": SIZES * 2,
    "rows": [(100, 18), (100, 16), (100, 19), (100, 20)] * 2,
    "both": [(99, 18), (101, 16), (98, 19), (100, 20)] * 2,
}


def _drain(p, secs: float) -> None:
    end = time.monotonic() + secs
    while time.monotonic() < end and p.isalive():
        if select.select([p.fd], [], [], 0.05)[0]:
            with contextlib.suppress(Exception):
                p.read(65536)


def _attach(sock: str, cols: int, rows: int):
    argv = attach_argv("ao-h", socket_name=sock)
    return ptyprocess.PtyProcess.spawn(argv, dimensions=(rows, cols), env={**os.environ, "TERM": "xterm-256color"})


def _history(sock: str) -> str:
    return subprocess.run(
        ["tmux", "-L", sock, "capture-pane", "-p", "-J", "-S", "-", "-t", "=ao-h:"],
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout


@pytest.fixture
def pane():
    tmux = Tmux(socket_name=private_socket_name())
    sock = tmux.socket_name
    subprocess.run(
        ["tmux", "-L", sock, "new-session", "-d", "-s", "ao-h", "-x", "100", "-y", "20", "bash", "-c", PRINTER],
        check=True,
    )
    try:
        yield sock
    finally:
        kill_private_server(tmux)


@pytest.mark.parametrize("mode", [*SEQUENCES, "reattach"])
def test_every_line_is_in_the_history_once(pane, mode):
    sock = pane
    p = _attach(sock, 100, 20)
    try:
        if mode == "reattach":
            for cols, rows in SIZES[:3]:
                _drain(p, 0.5)
                p.terminate(force=True)
                p = _attach(sock, cols, rows)
        else:
            for cols, rows in SEQUENCES[mode]:
                _drain(p, 0.3)
                p.setwinsize(rows, cols)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and f"L{LINES:02d} " not in _history(sock):
            _drain(p, 0.2)
    finally:
        p.terminate(force=True)
    seen = Counter(re.findall(r"^L(\d\d) ", _history(sock), re.M))
    assert sorted(seen) == [f"{i:02d}" for i in range(1, LINES + 1)], (
        f"{mode}: missing {set(range(1, LINES + 1)) - {int(k) for k in seen}}"
    )
    assert [k for k, v in seen.items() if v > 1] == [], f"{mode}: repeated"
