"""Claude Code's repaint across a client's resizes and reattaches, on a real tmux (the 2026-11-16 repaint hunt).

Opt-in: `AO_LIVE_CLAUDE=1 pytest tests/test_resize_repaint_live.py` (the account in `~/.claude`, or the config
directory `AO_LIVE_CLAUDE_CONFIG_DIR` names) — it starts the real `claude` (Haiku) in a
private tmux server, asks for thirty long, uniquely labelled paragraphs, and changes the attached client's
grid while they stream, which spends a small amount of the account's tokens and is never part of the suite.

What it found (2026-11-16, tmux 3.5a, two to five runs per mode; `test_tmux_resize_history_tmux.py` is the control that
tmux's own history is intact):

- no resize: every paragraph once;
- the **width** changes while it streams: paragraphs repeated in tmux's history (5 to 13 of 30);
- the **height** changes: whole paragraphs missing from the history (3 to 4 of 30), none repeated;
- a **reattach** at another size: repeats, and one paragraph missing;
- the prompt echoed twice after any of them;
- a **pinned** window (`window-size manual`; here the real `new_session`, TD-1919; then the same churn and
  reattaches): clean, 8 of 8 runs (two each of steady, width, height and reattach, in a script, then the combined churn here). Waiting for the
  pane to be idle first does not help (a width change repeats the last paragraphs, a height change loses 3 to 4),
  and `attach -f ignore-size` alone does not either (the window still followed the one client).

The known-bad modes are `xfail` (not strict), so a mitigation that holds the pane's grid still turns them into
passes without breaking the file. A mode that starts failing where it passed is a regression.
"""

from __future__ import annotations

import contextlib
import os
import re
import select
import shutil
import subprocess
import time
from collections import Counter

import pytest
from conftest import kill_private_server, private_socket_name

from sessionorc.tmux import Tmux, attach_argv

ptyprocess = pytest.importorskip("ptyprocess")

pytestmark = [
    pytest.mark.timeout(400),  # a streamed reply and its churn outlast the suite's 120 s
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("AO_LIVE_CLAUDE"), reason="opt-in: AO_LIVE_CLAUDE=1 (spends tokens)"),
    pytest.mark.skipif(shutil.which("claude") is None, reason="no `claude` on PATH"),
]

PARAS = 30
# the suite points CLAUDE_CONFIG_DIR at an empty directory; this test is the one that wants the person's own login
_CONFIG = os.environ.get("AO_LIVE_CLAUDE_CONFIG_DIR")
CLAUDE_CMD = (f"env CLAUDE_CONFIG_DIR={_CONFIG} " if _CONFIG else "env -u CLAUDE_CONFIG_DIR ") + "claude --model haiku"
PROMPT = (
    f"Write {PARAS} paragraphs labelled P01 to P{PARAS} (the label starts each paragraph). Each paragraph is one "
    "single long line of about 170 characters of plain ASCII words about tmux wrapping, with only letters, digits, "
    "spaces and commas. No lists, no headings, no emoji, no symbols."
)
SEQUENCES = {
    "columns": [(99, 20), (101, 20), (98, 20), (100, 20)] * 3,
    "rows": [(100, 18), (100, 16), (100, 19), (100, 20)] * 3,
    "both": [(99, 18), (101, 16), (98, 19), (100, 20)] * 3,
    "reattach": [(99, 20), (101, 18), (98, 16), (100, 20)] * 2,
    "pinned": [(99, 18), (101, 16), (98, 19), (100, 20)] * 3,
}
KNOWN_BAD = pytest.mark.xfail(
    reason="Claude Code's repaint loses or repeats rows across a resize", strict=False, raises=AssertionError
)


def _drain(p, secs: float) -> None:
    end = time.monotonic() + secs
    while time.monotonic() < end and p.isalive():
        if select.select([p.fd], [], [], 0.1)[0]:
            with contextlib.suppress(Exception):
                p.read(65536)


def _tmux(sock: str, *args: str) -> str:
    return subprocess.run(["tmux", "-L", sock, *args], capture_output=True, text=True, timeout=10).stdout


def _history(sock: str) -> str:
    return _tmux(sock, "capture-pane", "-p", "-J", "-S", "-", "-t", "=ao-live:")


def _attach(sock: str, cols: int, rows: int):
    return ptyprocess.PtyProcess.spawn(
        attach_argv("ao-live", socket_name=sock), dimensions=(rows, cols), env={**os.environ, "TERM": "xterm-256color"}
    )


def _ready(sock: str, p) -> None:
    """Wait for the input box, answering the one-time trust question a fresh directory brings."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        _drain(p, 1.0)
        screen = _tmux(sock, "capture-pane", "-p", "-t", "=ao-live:")
        if "trust this folder" in screen:
            p.write(b"\x1b[B\r")
        elif "❯" in screen and "No, exit" not in screen:
            return
    pytest.fail("claude never showed its input box:\n" + _tmux(sock, "capture-pane", "-p", "-t", "=ao-live:"))


def _run(sock: str, cwd, mode: str, *, fit: tuple[int, int] | None = None) -> tuple[list[str], list[str], int]:
    """(paragraphs missing, paragraphs repeated, times the prompt is echoed) after a reply streamed through `mode`,
    and, with `fit`, a Fit to window at idle once it has (design §4.6 *Fit to window*, TD-1919)."""
    if mode == "pinned":  # the real start: `new-session -x -y` and `window-size manual` in one invocation (TD-1919)
        Tmux(socket_name=sock).new_session("ao-live", cwd, ["sh", "-c", CLAUDE_CMD], {}, grid=(100, 20))
    else:
        _start_following(sock, cwd)
    p = _attach(sock, 100, 20)
    try:
        p = _stream(sock, p, mode)
        if fit is not None:  # the reply is done and the pane quiet: the person's fit, as the bridge sends it
            _drain(p, 3)
            _tmux(sock, "resize-window", "-t", "=ao-live:", "-x", str(fit[0]), "-y", str(fit[1]))
            _drain(p, 3)
    finally:
        p.terminate(force=True)
    out = _history(sock)
    seen = Counter(re.findall(r"^(?:● | {2})P(\d\d)\b", out, re.M))
    missing = [f"P{i:02d}" for i in range(1, PARAS + 1) if f"{i:02d}" not in seen]
    repeated = sorted(f"P{k}" for k, v in seen.items() if v > 1)
    return missing, repeated, len(re.findall(r"^❯ Write ", out, re.M))


def _start_following(sock: str, cwd) -> None:
    """A window that follows its clients, as every window did before the pin."""
    subprocess.run(
        [
            "tmux",
            "-L",
            sock,
            "new-session",
            "-d",
            "-s",
            "ao-live",
            "-x",
            "100",
            "-y",
            "20",
            "-c",
            str(cwd),
            CLAUDE_CMD,
        ],
        check=True,
    )


def _stream(sock: str, p, mode: str):
    """Ask for the paragraphs, churn the client through `mode` while they stream, and wait for the last; the
    client attached at the end, which a reattach replaces."""
    _ready(sock, p)
    _drain(p, 3)  # the box takes keys a moment after it is drawn
    p.write(PROMPT.encode())
    time.sleep(0.5)
    p.write(b"\r")
    end = time.monotonic() + 15
    while time.monotonic() < end and not re.search(r"^❯ Write ", _history(sock), re.M):
        _drain(p, 0.5)
    if not re.search(r"^❯ Write ", _history(sock), re.M):
        pytest.fail("the prompt was never submitted:\n" + _tmux(sock, "capture-pane", "-p", "-t", "=ao-live:"))
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline and not re.search(r"^● P01", _history(sock), re.M):
        _drain(p, 0.5)  # churn starts once the reply is streaming, so it lands on live paragraphs
    if mode == "reattach":
        for cols, rows in SEQUENCES[mode]:
            p.terminate(force=True)
            p = _attach(sock, cols, rows)
            _drain(p, 1.0)
    else:
        for cols, rows in SEQUENCES.get(mode, []):
            p.setwinsize(rows, cols)
            _drain(p, 1.0)
        if mode == "pinned":
            for cols, rows in SEQUENCES["reattach"][:6]:
                p.terminate(force=True)
                p = _attach(sock, cols, rows)
                _drain(p, 1.0)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not re.search(rf"^(?:● | {{2}})P{PARAS:02d}\b", _history(sock), re.M):
        _drain(p, 0.5)
    return p


@pytest.fixture
def live(tmp_path):
    tmux = Tmux(socket_name=private_socket_name())
    cwd = tmp_path / "work"
    cwd.mkdir()
    try:
        yield tmux.socket_name, cwd
    finally:
        kill_private_server(tmux)


def test_a_steady_pane_draws_every_paragraph_once(live):
    sock, cwd = live
    missing, repeated, echoes = _run(sock, cwd, "none")
    assert (missing, repeated, echoes) == ([], [], 1)


def test_a_pinned_window_leaves_every_paragraph_once_through_any_resize_or_reattach(live):
    sock, cwd = live
    missing, repeated, echoes = _run(sock, cwd, "pinned")
    assert (missing, repeated, echoes) == ([], [], 1)


def test_a_fit_at_idle_that_grows_the_grid_leaves_every_paragraph_once(live):
    sock, cwd = live
    missing, repeated, echoes = _run(sock, cwd, "pinned", fit=(120, 30))
    assert (missing, repeated, echoes) == ([], [], 1)
    assert _tmux(sock, "display-message", "-p", "-t", "=ao-live:", "#{window_width}x#{window_height}") == "120x30"


@pytest.mark.parametrize("mode", [pytest.param(m, marks=KNOWN_BAD) for m in SEQUENCES if m != "pinned"])
def test_a_resize_while_it_streams_leaves_every_paragraph_once(live, mode):
    sock, cwd = live
    missing, repeated, echoes = _run(sock, cwd, mode)
    assert (missing, repeated, echoes) == ([], [], 1)
