"""A jump on a real tmux (design §4.6 *A jump to a prompt*, TD-977): on a private server, the bridge's read
and landing put the found prompt's row at the view's top, and a miss leaves copy mode."""

from __future__ import annotations

import asyncio
import subprocess

import pytest
from conftest import kill_private_server, private_socket_name, wait_for_sync

from sessionorc.tmux import Tmux
from shiftlead.ui.pty_bridge import run_jump

pytestmark = pytest.mark.integration

SCRIPT = (
    "for i in $(seq 1 200); do echo line $i; done; echo '❯ hello there'; echo '⏺ hi back';"
    " for i in $(seq 1 100); do echo after $i; done; echo '❯ hello there'; sleep 600"
)


@pytest.fixture
def pane():
    tmux = Tmux(socket_name=private_socket_name())
    sock = tmux.socket_name
    subprocess.run(
        ["tmux", "-L", sock, "new-session", "-d", "-s", "ao-j", "-x", "80", "-y", "20", "bash", "-c", SCRIPT],
        check=True,
    )
    try:
        yield sock
    finally:
        kill_private_server(tmux)


def _tmux(sock: str, *args: str) -> str:
    return subprocess.run(["tmux", "-L", sock, *args], capture_output=True, text=True, timeout=5).stdout.strip()


def _jump(sock: str, openings: list[dict]) -> bool:
    async def read(argv):
        p = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(p.communicate(), 5)
        return out.decode()

    async def run(argv):
        p = await asyncio.create_subprocess_exec(*argv)
        await asyncio.wait_for(p.wait(), 5)

    return asyncio.run(run_jump(openings, read, run, "ao-j", socket_name=sock))


def test_a_found_prompt_lands_at_the_top_and_a_miss_leaves_copy_mode(pane):
    sock = pane
    assert wait_for_sync(lambda: "after 100" in _tmux(sock, "capture-pane", "-p", "-t", "=ao-j:"), timeout=8)
    # the older of the two *hello there*s: passed the newer on the way
    assert _jump(sock, [{"drawn": "❯ hello there", "whole": True}, {"drawn": "❯ hello there", "whole": True}])
    assert _tmux(sock, "display-message", "-p", "-t", "=ao-j:", "#{pane_in_mode}") == "1"
    _tmux(sock, "send-keys", "-X", "-t", "=ao-j:", "top-line")
    assert _tmux(sock, "display-message", "-p", "-t", "=ao-j:", "#{copy_cursor_line}").startswith(
        "❯ hello there"
    )  # copy mode's position mark on its right
    _tmux(sock, "send-keys", "-X", "-t", "=ao-j:", "cursor-down")
    assert (
        _tmux(sock, "display-message", "-p", "-t", "=ao-j:", "#{copy_cursor_line}") == "⏺ hi back"
    )  # the reply under it
    assert not _jump(sock, [{"drawn": "❯ never said", "whole": True}])
    assert _tmux(sock, "display-message", "-p", "-t", "=ao-j:", "#{pane_in_mode}") == "0"
