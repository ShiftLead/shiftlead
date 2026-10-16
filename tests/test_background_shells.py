"""A background shell task (design §4.2 *A background shell task*, §4.3 `background`, §6 rules 3, 4 and 9;
TD-761, built by TD-766): `ProcReader.children`/`cmdline`, the Claude Code adapter's walk to the tool's
process and its command-wrapper children, the tick's `shells`/`shells_at` on an idle record, and
`shells_live` read by the rules beside a live subagent."""

from __future__ import annotations

import builtins
import os
import subprocess
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import park_ticks

from sessionorc import adapters, agent_common, identity, reports, work
from sessionorc.agent import IDLE_NUDGE, SEAT_IDLE_GRACE, SHELL_WAIT
from sessionorc.client import LocalClient
from sessionorc.identity import Proc
from sessionorc.models import ProgressEntry, Session
from shiftlead.adapters.claude_code import ClaudeCodeAdapter

SHELL = {"adapter": "agentshell", "argv": ["bash", "--norc", "--noprofile"], "unattended": True, "supervised": True}
WRAP = ["/bin/bash", "-c", "source /home/u/.claude/shell-snapshots/snapshot-bash-1.sh 2>/dev/null || true && eval x"]
GH = ["timeout", "1500", "gh", "pr", "checks", "1893", "--watch"]


def _iso(t: datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class FakeProc:
    """A process tree: `{pid: (ppid, comm, argv, start)}`."""

    def __init__(self, tree: dict[int, tuple[int, str, list[str], int]]):
        self.tree = tree

    def stat(self, pid):
        t = self.tree.get(pid)
        return Proc(pid=pid, ppid=t[0], sid=0, tty_nr=0, start=t[3]) if t else None

    def comm(self, pid):
        return self.tree[pid][1] if pid in self.tree else None

    def cgroup(self, pid):
        return None

    def children(self, pid):
        return sorted(p for p, t in self.tree.items() if t[0] == pid) if pid in self.tree else None

    def cmdline(self, pid):
        return list(self.tree[pid][2]) if pid in self.tree else None


def _tree() -> dict[int, tuple[int, str, list[str], int]]:
    """A hand-started session: the pane's shell 100, `claude` 101 under it, a wrapper 102 running `gh`
    (with a later child 106 that is not its first), an MCP server 103, and a wrapper 104 with no child."""
    return {
        100: (1, "bash", ["bash"], 10),
        101: (100, "claude", ["claude", "--model", "opus"], 11),
        102: (101, "bash", WRAP, 20),
        105: (102, "timeout", GH, 21),
        106: (102, "sleep", ["sleep", "1"], 25),
        103: (101, "node", ["node", "/opt/mcp/server.js", "-c", "/shell-snapshots/"], 12),
        104: (101, "bash", WRAP, 30),
    }


def test_the_adapter_walks_to_the_tool_and_reads_its_wrappers():
    proc = FakeProc(_tree())
    got = ClaudeCodeAdapter().background(100, proc)
    assert got == [{"pid": 102, "start": 20, "cmd": " ".join(GH)}, {"pid": 104, "start": 30, "cmd": ""}]
    assert ClaudeCodeAdapter().background(101, proc) == got, "the pane's own process is the tool's (an ao launch)"
    # no `claude` under the pane: it cannot tell
    assert ClaudeCodeAdapter().background(100, FakeProc({100: (1, "bash", ["bash"], 10)})) is None
    assert ClaudeCodeAdapter().background(999, proc) is None, "a pane process gone"
    # the binary's own name, as `comm` keeps it (15 characters)
    named = {**_tree(), 101: (100, "claude-nightly-", ["claude-nightly-build"], 11)}
    assert ClaudeCodeAdapter(binary="/opt/bin/claude-nightly-build").background(100, FakeProc(named))[0]["pid"] == 102
    # `cmd` is cut to 120 characters
    long = {**_tree(), 105: (102, "python", ["python", "-c", "x" * 300], 21)}
    assert len(ClaudeCodeAdapter().background(100, FakeProc(long))[0]["cmd"]) == 120


def test_the_linux_reader_reads_children_and_argv_and_falls_back_to_ppid(monkeypatch):
    proc = identity.LinuxProc()
    child = subprocess.Popen(["sleep", "30"])
    try:
        assert child.pid in proc.children(os.getpid())
        assert proc.cmdline(child.pid) == ["sleep", "30"]
        real = builtins.open

        def no_children_file(path, *a, **kw):
            if str(path).endswith("/children"):
                raise FileNotFoundError(path)
            return real(path, *a, **kw)

        monkeypatch.setattr(builtins, "open", no_children_file)
        assert child.pid in proc.children(os.getpid()), "a kernel without the file: read by ppid"
    finally:
        child.kill()
        child.wait()
    assert proc.children(2**22 + 7) is None and proc.cmdline(2**22 + 7) is None


def test_shells_live_reads_since_within_the_wait():
    now = datetime.now(UTC)
    rec = Session(id="x", name="x", dir="/tmp", kind="interactive", adapter="claude-code")
    assert not agent_common.shells_live(rec, now)
    rec.shells = [{"pid": 1, "start": 2, "cmd": "gh", "since": _iso(now - timedelta(minutes=5))}]
    assert agent_common.shells_live(rec, now) and agent_common.on_its_own(rec, now)
    assert not agent_common.shells_live(rec, now + SHELL_WAIT)
    # the idle stretch counts from the later of `since`, `subagent_at` and `shells_at`
    rec.since, rec.shells_at = _iso(now - timedelta(hours=3)), _iso(now - timedelta(minutes=1))
    assert agent_common.idle_from(rec) == (now - timedelta(minutes=1)).replace(microsecond=0)


def test_a_team_whose_member_has_a_live_shell_is_not_finished():
    said = {"at": "2026-10-15T10:00:00Z", "why": "nothing open"}
    member = {"id": "a", "name": "grinder-dc-1", "state": "idle", "unattended": True, "out_of_work": said}
    seat = {"id": "s", "name": "techlead", "state": "idle", "unattended": True, "seat": {"trigger": "asks"}}
    assert work.finished([{**member, "shells_live": True}, seat])["why"] == ["grinder-dc-1 idle, shell live"]
    assert work.finished([member, {**seat, "shells_live": True}])["why"] == ["techlead idle, shell live"]
    assert work.finished([member, seat])["why"] == []


# -- the tick ---------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_gh(monkeypatch):
    monkeypatch.setattr(reports, "merged_prs", lambda *a, **kw: None)


class _WithBackground:
    """The test adapter with a `background` read of `tasks`, a list the test changes."""

    def __init__(self, real, tasks):
        self._real, self.tasks, self.pids = real, tasks, []

    def __getattr__(self, name):
        return getattr(self._real, name)

    def background(self, pid, proc):
        self.pids.append(pid)
        return list(self.tasks)


async def _create(person, tmp_path, name: str, **kw) -> str:
    (tmp_path / name).mkdir(exist_ok=True)
    params = {"name": name, "dir": str(tmp_path / name), "prompt": "the brief"}
    return (await person.call("create", **{**SHELL, **params, **kw}))["id"]


def _idle(rec: Session, now: datetime, ago: timedelta) -> None:
    rec.state, rec.confidence, rec.since = "idle", "hook", _iso(now - ago)
    rec.git = {"branch": "main", "dirty": 0, "unpushed": 0}


@pytest.fixture
def background(monkeypatch):
    real_get = adapters.get
    fake = _WithBackground(real_get("agentshell"), [])
    monkeypatch.setattr(adapters, "get", lambda name: fake if name == "agentshell" else real_get(name))
    return fake


@pytest.mark.integration
async def test_the_tick_writes_an_idle_records_shells_and_keeps_them_otherwise(
    agent, tmp_path, background, monkeypatch
):
    await park_ticks(agent)
    now = datetime.now(UTC)
    pushes = []
    real = agent._push_changes

    async def counted():
        pushes.append(1)
        await real()

    monkeypatch.setattr(agent, "_push_changes", counted)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w")
        rec = agent.sessions[sid]
        panes = {sid: SimpleNamespace(pane_pid=4242)}
        _idle(rec, now, timedelta(minutes=5))
        background.tasks[:] = [{"pid": 7, "start": 70, "cmd": "gh pr checks 1893"}]
        await agent._refresh_shells(now, panes)
        assert background.pids == [4242], "read with the pane's pid"
        assert rec.shells == [{"pid": 7, "start": 70, "cmd": "gh pr checks 1893", "since": now.isoformat()}]
        assert rec.shells_at == now.isoformat() and pushes == [1]
        assert agent._view(rec)["shells_live"] is True and agent._finished_view(rec, now)["shells_live"] is True
        # the same task a tick later: `since` kept, `shells_at` moves, nothing pushed
        later = now + timedelta(seconds=2)
        await agent._refresh_shells(later, panes)
        assert rec.shells[0]["since"] == now.isoformat() and rec.shells_at == later.isoformat() and pushes == [1]
        # mid-turn the last reading is kept; so it is under a live subagent; a record with no pane is not read
        background.tasks[:] = []
        rec.state = "working"
        await agent._refresh_shells(later, panes)
        rec.state, rec.subagents, rec.subagent_at = "idle", 1, _iso(later)
        await agent._refresh_shells(later, panes)
        rec.subagents = 0
        await agent._refresh_shells(later, {})
        assert len(rec.shells) == 1 and len(background.pids) == 2
        # the task ended: an empty list, pushed; `shells_at` is never moved back
        await agent._refresh_shells(later, panes)
        assert rec.shells == [] and rec.shells_at == later.isoformat() and pushes == [1, 1]
        # a read that cannot tell keeps the last reading
        rec.shells = [{"pid": 8, "start": 80, "cmd": "x", "since": later.isoformat()}]
        background.tasks = None  # type: ignore[assignment]
        monkeypatch.setattr(background, "background", lambda pid, proc: None)
        await agent._refresh_shells(later, panes)
        assert rec.shells[0]["pid"] == 8
        # every exit clears them
        await agent.rpc_hook(sid, state="exited", pending=None)
        assert rec.shells == []
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_shells_at_stops_moving_past_the_wait_and_a_flip_is_pushed(agent, tmp_path, background, monkeypatch):
    await park_ticks(agent)
    now = datetime.now(UTC)
    async with LocalClient() as person:
        sid = await _create(person, tmp_path, "w")
        rec = agent.sessions[sid]
        panes = {sid: SimpleNamespace(pane_pid=4242)}
        _idle(rec, now, timedelta(minutes=5))
        background.tasks[:] = [{"pid": 7, "start": 70, "cmd": "python -m http.server"}]
        await agent._refresh_shells(now, panes)
        await agent._subagent_flips(now)
        pushes = []
        real = agent._push_changes

        async def counted():
            pushes.append(1)
            await real()

        monkeypatch.setattr(agent, "_push_changes", counted)
        past = now + SHELL_WAIT + timedelta(minutes=1)
        await agent._refresh_shells(past, panes)
        assert rec.shells_at == now.isoformat(), "a shell past SHELL_WAIT moves it no further"
        assert not agent_common.shells_live(rec, past) and rec.shells, "still named, no longer live"
        await agent._subagent_flips(past)
        assert pushes == [1], "the working-on-its-own reading flipped with no event behind it"
        await person.call("kill", id=sid)


@pytest.mark.integration
async def test_the_rules_read_a_live_shell_as_not_idle_and_one_past_the_wait_as_idle(agent, tmp_path):
    await park_ticks(agent)
    now = datetime.now(UTC)
    live = [{"pid": 7, "start": 70, "cmd": "gh pr checks 1893", "since": _iso(now - timedelta(minutes=1))}]
    stale = [{"pid": 7, "start": 70, "cmd": "server", "since": _iso(now - SHELL_WAIT - timedelta(hours=1))}]
    async with LocalClient() as person:
        # rule 3: a seat idle on a live shell is not closed; past SHELL_WAIT it is
        seat = agent.sessions[await _create(person, tmp_path, "audit", seat={"trigger": "every", "after": "6h"})]
        _idle(seat, now, SEAT_IDLE_GRACE + timedelta(minutes=10))
        seat.shells, seat.shells_at = live, None  # the shell itself holds it, whatever `shells_at` says
        assert not agent._seat_has_run(seat, now)
        seat.shells_at = _iso(now)  # and its last live tick holds the grace
        seat.shells = []
        assert not agent._seat_has_run(seat, now)
        seat.shells, seat.shells_at = stale, _iso(now - timedelta(hours=1))
        assert agent._seat_has_run(seat, now)
        # rule 4: a member is not nudged while its shell runs, and its stretch counts from `shells_at`
        w = agent.sessions[await _create(person, tmp_path, "w")]
        w.progress = [ProgressEntry(ref="TD-001", status="claimed", source="declared")]
        _idle(w, now, IDLE_NUDGE + timedelta(minutes=5))
        w.shells, w.shells_at = live, None
        sent = []

        async def send(s, line):
            sent.append(line)
            return True

        agent._policy_send = send
        await agent._idle_nudge(w, now)
        assert sent == [] and w.nudged_at is None
        w.shells, w.shells_at = [], _iso(now)  # the shell just ended: the stretch counts from its last live tick
        await agent._idle_nudge(w, now)
        assert sent == []
        await agent._idle_nudge(w, now + IDLE_NUDGE)
        assert len(sent) == 1
        # rule 4's `open` cause: a standing mark beside a live shell is none
        mgr = agent.sessions[await _create(person, tmp_path, "mgr", seat={"trigger": "team"})]
        m = agent.sessions[await _create(person, tmp_path, "m", controllers=[mgr.id])]
        _idle(m, now, 2 * IDLE_NUDGE)
        m.idle_open = {"at": _iso(now), "ref": "TD-001"}
        records = list(agent.sessions.values())
        assert [c["by"] for c in agent._team_causes(mgr, records)] == ["open"]
        m.shells = [{**live[0], "since": _iso(datetime.now(UTC))}]
        assert agent._team_causes(mgr, records) == []
        # nor is a new mark written while it runs
        m.idle_open, m.nudged_at = None, _iso(now - IDLE_NUDGE - timedelta(minutes=1))
        m.lane = ["TD-1"]
        await agent._idle_open(m, now)
        assert m.idle_open is None
        for s in (seat, w, mgr, m):
            await person.call("kill", id=s.id)
