"""The wait guard (design §4.3 *A wait the guard refuses*, TD-991, built by TD-992): an unattended Claude
Code session's foreground CI watch is refused by the `PreToolUse` hook, which asks the host agent the
record's mode with the event (`wait`) and denies when the reply says `refuse_wait`."""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
from pathlib import Path

import pytest
from conftest import run_hook

from sessionorc.client import LocalClient
from shiftlead import kill_guard
from shiftlead.wait_guard import REASON, waits

WATCHES = [
    "gh pr checks 12 --watch",
    "timeout 1800 gh pr checks 12 --watch --interval 30",
    "nohup gh run watch 99",
    "cd x && gh pr checks 12 --watch",
    "nohup gh pr checks 12 --watch >ci.log 2>&1 &",  # a shell `&` is not the background form
    "gh -R a/b pr checks 12 --watch",
    "gh --repo a/b pr checks 12 --watch",
    "gh --repo=a/b pr checks 12 --watch",
    "gh pr checks 12 --watch=true",
]
NOT_WATCHES = [
    "gh pr checks 12",
    "sleep 20; gh pr checks 12",
    'git commit -m "gh pr checks --watch"',
    "cat <<'EOF'\ngh pr checks 12 --watch\nEOF",
    "echo gh run watch",
    "gh run view 99",
    "# gh pr checks 12 --watch",
]


@pytest.mark.parametrize("command", WATCHES)
def test_a_ci_watch_is_read_as_one(command):
    assert waits(command)


@pytest.mark.parametrize("command", NOT_WATCHES)
def test_a_poll_or_a_mention_is_not(command):
    assert not waits(command)


def bash(command: str, **extra) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "u",
        "tool_name": "Bash",
        "tool_input": {"command": command, **extra},
    }


class StubAgent:
    """A host agent on `paths.socket_path()` that records each request and answers `reply`, or never."""

    def __init__(self, home: Path, reply: dict | None, answer: bool = True):
        home.mkdir(parents=True, exist_ok=True)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(home / "agent.sock"))
        self.sock.listen(4)
        self.reply, self.answer, self.got = reply, answer, []
        self.held: list[socket.socket] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            self.got.append(json.loads(buf))
            if self.answer:
                conn.sendall((json.dumps({"id": 1, "result": self.reply}) + "\n").encode())
                conn.close()
            else:
                self.held.append(conn)

    def close(self):
        self.sock.close()
        for c in self.held:
            c.close()


@pytest.fixture
def short_home(monkeypatch):
    """A home short enough for a unix socket's path (memory *scratchpad too long for unix sockets*)."""
    with tempfile.TemporaryDirectory(prefix="aowg", dir="/tmp") as d:
        home = Path(d) / "h"
        monkeypatch.setenv("SHIFTLEAD_HOME", str(home))
        yield home


def deny_of(stdout: str) -> str | None:
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecisionReason"] if stdout.strip() else None


def test_an_unattended_records_foreground_watch_is_refused(short_home):
    stub = StubAgent(short_home, {"refuse_wait": True})
    try:
        cp = run_hook("ao-x-y", bash("timeout 1800 gh pr checks 12 --watch"))
    finally:
        stub.close()
    assert cp.returncode == 0 and deny_of(cp.stdout) == REASON
    [req] = stub.got
    assert req["params"]["wait"] is True and req["params"]["state"] == "working"


def test_an_interactive_records_watch_runs(short_home):
    stub = StubAgent(short_home, None)  # the agent asked, and answered nothing: the record is interactive
    try:
        cp = run_hook("ao-x-y", bash("gh pr checks 12 --watch"))
    finally:
        stub.close()
    assert cp.stdout == "" and stub.got[0]["params"]["wait"] is True


@pytest.mark.parametrize(
    "payload",
    [
        bash("gh pr checks 12 --watch", run_in_background=True),
        {**bash("gh pr checks 12 --watch"), "agent_id": "a1"},
        bash("gh pr checks 12"),
    ],
    ids=["background", "subagent", "a-single-poll"],
)
def test_what_is_not_a_foreground_watch_on_the_main_thread_is_not_asked(short_home, payload):
    stub = StubAgent(short_home, {"refuse_wait": True})
    try:
        cp = run_hook("ao-x-y", payload)
    finally:
        stub.close()
    assert cp.stdout == ""
    assert all("wait" not in r["params"] for r in stub.got)


def test_with_the_host_agent_down_the_watch_runs_and_the_queued_event_has_no_wait(short_home):
    cp = run_hook("ao-x-y", bash("gh pr checks 12 --watch"))
    assert cp.stdout == ""
    got = json.loads((short_home / "events" / "ao-x-y.jsonl").read_text().strip())
    assert got["state"] == "working" and "wait" not in got


def test_a_reply_slower_than_the_wait_lets_it_run(short_home):
    stub = StubAgent(short_home, {"refuse_wait": True}, answer=False)
    try:
        cp = run_hook("ao-x-y", bash("gh pr checks 12 --watch"), env={**os.environ, "SHIFTLEAD_EVENT_WAIT": "0.3"})
    finally:
        stub.close()
    assert cp.stdout == ""
    got = json.loads((short_home / "events" / "ao-x-y.jsonl").read_text().strip())
    assert got["state"] == "working" and "wait" not in got


def test_a_kill_inside_a_watch_is_the_kill_guards_alone(short_home):
    stub = StubAgent(short_home, {"refuse_wait": True})
    try:
        cp = run_hook("ao-x-y", bash("gh pr checks 12 --watch; kill $PPID"))
    finally:
        stub.close()
    assert len(cp.stdout.splitlines()) == 1 and deny_of(cp.stdout) == kill_guard.REASON
    assert all("wait" not in r["params"] for r in stub.got)


@pytest.mark.integration
async def test_the_hook_rpc_answers_refuse_wait_for_an_unattended_record_only(agent, composerstubs, tmp_path):
    async with LocalClient() as c:
        sid = (await c.call("create", name="w", dir=str(tmp_path), adapter="composer0", unattended=True))["id"]
        assert await agent.rpc_hook(sid, state="working", wait=True) == {"refuse_wait": True}
        assert await agent.rpc_hook(sid, state="working") is None
        assert await agent.rpc_hook(sid, state="working", wait=True, mail=True) == {"unread": 0, "refuse_wait": True}
        assert await agent.rpc_hook("ao-nobody", state="working", wait=True) is None
        await c.call("set_mode", id=sid, unattended=False)  # Take over
        assert await agent.rpc_hook(sid, state="working", wait=True) is None
        assert await agent.rpc_hook(sid, state="working", wait=True, mail=True) == {"unread": 0}
