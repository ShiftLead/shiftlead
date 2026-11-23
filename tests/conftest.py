"""Shared fixtures. Read tests/README.md before adding a fixture that touches tmux or a socket.

Two agents are on offer:

- `agent`: an in-process `HostAgent` on this test's event loop. For `async def` tests that talk
  to it through `LocalClient`. Cheap, one per test.
- `subprocess_agent`: a separate process (`tests/_agent_child.py`), module-scoped. For plain
  `def` tests that go through `call_sync` / `cli.main` / the sync FastAPI `TestClient`: those
  call `asyncio.run`, which hangs against the in-process fixture because a sync test body never
  pumps that fixture's loop.

Both use a private tmux server (`-L ao-test-<uuid>`), a temp `SHIFTLEAD_HOME` and a temp
`CLAUDE_CONFIG_DIR` (the default profile's registry; the occupancy check would otherwise see this
machine's live Claude sessions, TD-010 a), never the
user's. `subprocess_agent` sets the env in the test process too: the UI under `TestClient` runs
here and reads `paths.socket_path()` and `SHIFTLEAD_TMUX_SOCKET` from `os.environ` at call time.
"""

from __future__ import annotations

import asyncio
import contextlib
import glob
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest
from _pytest.faulthandler import fault_handler_stderr_fd_key
from _stubs import AgentShellStub, ComposerStub, HookFedStub

from sessionorc import paths
from sessionorc.agent import HostAgent
from sessionorc.tmux import Tmux

HERE = Path(__file__).parent


@pytest.fixture(autouse=True)
def _agentshell(monkeypatch: pytest.MonkeyPatch) -> None:
    """`agentshell` (tests/_stubs.py) beside the built-ins for every test: a shell that counts as an
    agent, for a test that drives an agent's path through a bash pane (design §4.3, TD-665)."""
    from sessionorc import adapters

    adapters.load_all()
    monkeypatch.setitem(adapters._REGISTRY, AgentShellStub.name, AgentShellStub())


@pytest.fixture(autouse=True)
def _identity_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Design §4.8a *Tests*: the suite drives the socket from the pytest process — under no pane —
    and passes `caller=<id>` to stand for a session, which is exactly what the rule table calls a
    forgery. So an agent built here with no mode of its own runs `off`; the classification is
    tested directly (tests/test_identity.py), and `enforce` against real panes there too."""
    from sessionorc import identity

    monkeypatch.setattr(identity, "DEFAULT_MODE", "off")


@pytest.fixture(autouse=True)
def _no_real_repos_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A host with no `repos_registry:` of its own imports agent-cadence's machine roster in the
    person's home only on the default home (TD-298, TD-590: every home reads its own `repos.txt`, which
    `hosts.default_repos_registry()` names) — and from TD-069 step 3 the Inbox runs the board reader
    over every repo on it. A test never reads the person's roster, even one that points
    `SHIFTLEAD_HOME` at the default: it gets an empty one unless it writes its own."""
    from sessionorc import hosts

    monkeypatch.setattr(hosts, "AGENT_CADENCE_ROSTER", str(tmp_path / "no-roster" / "repos.txt"))


@pytest.fixture(autouse=True)
def _no_real_gate_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    """The event runner (TD-1376) sweeps every registered root once a day in process (`gatesweep.sweep`),
    which runs the pinned checks, asks the forge and opens PRs. A test never runs it: every root reads as not
    sweepable, and a test of the sweep itself puts back `gatesweep.ELIGIBLE` / `gatesweep.SWEEP`, the real functions."""
    from sessionorc import gatesweep

    monkeypatch.setattr(gatesweep, "eligible", lambda root: (False, "tests run no gate sweep"))
    monkeypatch.setattr(gatesweep, "sweep", lambda *a, **k: (None, "tests run no gate sweep"))


@pytest.fixture(autouse=True)
def _person_text_off_unless_marked(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Design §4.10 *Text a person reads is checked at its writer* (TD-1846): the home refuses an `ask` or `steer`
    to the person that fails the check. A test of something else sends the person whatever text it needs to drive
    its road, so the check runs only in a test marked `person_text`, which tests the check itself."""
    from sessionorc import mail

    if request.node.get_closest_marker("person_text") is None:
        monkeypatch.setattr(mail, "PERSON_TEXT_CHECK", False)


@pytest.fixture(autouse=True)
def _no_start_tools_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The host agent reads this host's tools when it starts (design §4.2b, TD-1973): every tool's real `--version`,
    a node process each for some. The suite starts hundreds of host agents, so a test makes none of those reads; a
    test of the start's read sets `tools.READ_AT_START` back (a child agent: `AO_TEST_TOOLS_AT_START=1`, TD-2002)."""
    from sessionorc import tools

    monkeypatch.setattr(tools, "READ_AT_START", False)


@pytest.fixture(autouse=True)
def _no_extras_unless_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A team with no `max` key is on td-max's default ceilings (§4.9 *Scaling with the work*, TD-1545), so
    every Start would write two held extras per line and seat beside the sessions a test counts. A test
    writes none: a test of the extras puts back `teams.EXTRAS`, the real function."""
    from shiftlead import teams

    monkeypatch.setattr(teams, "_extras", lambda *a, **k: [])


CHILD = HERE / "_agent_child.py"
FAST_TICK = 0.3


# Which pytest process owns which private tmux server. The sweep below kills leaked servers, and a
# live server whose owner is still running belongs to a *concurrent* run — a reviewer's suite beside
# a worker's, two `pytest` processes in one loop — which must never be swept (TD-025). It lives beside
# the sockets, never under `$TMPDIR`: a precheck gives each run a `TMPDIR` of its own (TD-1052), and runs
# that could not see each other's owners would sweep each other's servers.
OWNERS = Path("/tmp") / f"ao-test-owners-{os.getuid()}"
# Inside each of a run's scratch roots, its pid: what says whose a root in a seat's directory is (design §4.6 *The
# pressure pass*, rule 1). The `OWNERS` files stay for the roots at the top of `/tmp`.
TEST_RUN_MARK = ".shiftlead-test-run"


def private_socket_name() -> str:
    """A socket name for this process's own tmux server, recorded as owned by it."""
    name = f"ao-test-{uuid.uuid4().hex[:8]}"
    with contextlib.suppress(OSError):
        OWNERS.mkdir(exist_ok=True)
        (OWNERS / name).write_text(str(os.getpid()))
    return name


def _owner_alive(name: str) -> bool:
    """Is the pytest process that created this server still running? An unowned socket (a leak from
    a run that predates this bookkeeping) answers False, so it is still swept. A recycled pid can
    make a leaked server look owned; that costs one skipped sweep, and the next run whose glob finds
    it takes it — the cost of being wrong the other way is killing a live run's server."""
    try:
        pid = int((OWNERS / name).read_text().strip())
    except (OSError, ValueError):
        return False
    return pid != os.getpid() and Path(f"/proc/{pid}").exists()


def _forget_owner(name: str) -> None:
    with contextlib.suppress(OSError):
        (OWNERS / name).unlink()


# -- stale servers from a killed run ------------------------------------------------------------


def kill_private_server(tmux: Tmux) -> None:
    """`tmux kill-server` leaves the socket file behind; unlink it so the sweep below stays cheap."""
    tmux.kill_server()
    if tmux.socket_name:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(f"/tmp/tmux-{os.getuid()}/{tmux.socket_name}")
        _forget_owner(tmux.socket_name)


def sweep_stale_test_servers() -> None:
    """A killed pytest run leaves `ao-test-*` tmux servers behind (never the user's). Best effort:
    a live socket accepts a connection and gets kill-server; a dead socket file is unlinked.

    **A server another pytest process is still using is left alone** (TD-025). This sweep used to
    kill every live `ao-test-*` server it found, so a second suite starting six seconds into the
    first one destroyed the first one's tmux server mid-test: its panes vanished from `list-panes`,
    its records froze at `working` with an empty tail, and its next `send-keys` failed with
    `error connecting to /tmp/tmux-…`. That is the whole family of "seen once while a review ran
    the suite beside me" flakes, and it is why the ownership file exists.

    The owner is asked first, before the socket: a refused connect is no proof the server is dead —
    another worker's server between its bind and its listen, or too busy to accept under a loaded run,
    refuses too — and unlinking a live server's socket leaves it running with no way in, which is the
    same `error connecting` (TD-1050)."""
    for sock in glob.glob(f"/tmp/tmux-{os.getuid()}/ao-test-*"):
        name = os.path.basename(sock)
        if _owner_alive(name):
            continue  # a concurrent run is using it
        with socket.socket(socket.AF_UNIX) as s:
            try:
                s.connect(sock)
            except OSError:
                with contextlib.suppress(OSError):
                    os.unlink(sock)
                _forget_owner(name)
                continue
        subprocess.run(["tmux", "-S", sock, "kill-server"], capture_output=True, check=False)
        with contextlib.suppress(OSError):
            os.unlink(sock)
        _forget_owner(name)


def _rmtree_writable(path: str) -> None:
    """Remove a tree even where a test left a read-only directory in it (TD-2015): every directory in it, never
    through a link, is made writable and searchable first; what still cannot be removed is left."""
    if os.path.islink(path) or not os.path.isdir(path):
        return
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)
    for d, dirs, _files in os.walk(path):
        for n in dirs:
            p = os.path.join(d, n)
            if not os.path.islink(p):
                with contextlib.suppress(OSError):
                    os.chmod(p, 0o700)
    shutil.rmtree(path, ignore_errors=True)


def sweep_stale_scratch_roots(base: str = "/tmp", tmpdir: str | None = None) -> None:
    """A test run whose workers are killed, or whose session restarts mid-run, never reaches its scratch
    root's cleanup, so its `aoscr-*` directory used to stay in `/tmp` for good: 182 of them held about
    45,000 inodes of the shared tmpfs on 2026-11-19, which then refused every test's setup (TD-2015). The
    sweep removes the roots of runs that have ended — an owner file naming a pid no longer running — and
    leaves a live run's alone, as the tmux sweep does. A root no owner file names (one made before TD-2015)
    is never touched: whose it is cannot be read, so it is left for a person to clear.

    A root in a seat's directory (TD-2084) is read by the pid in its own `TEST_RUN_MARK`, in every seat's under
    `base`'s `shiftlead-<uid>/` and, where `tmpdir` is a seat's in another pool, under that one's too."""
    for root in glob.glob(os.path.join(base, "aoscr-*")):
        name = os.path.basename(root)
        if not (OWNERS / name).exists() or _owner_alive(name):
            continue
        _rmtree_writable(root)
        _forget_owner(name)
    for holder in _seat_holders(base, tmpdir):
        with contextlib.suppress(OSError):  # one seat's directory going away mid-sweep never stops the others'
            for root in holder.glob("*/aoscr-*"):
                if _marked_run_ended(root):
                    _rmtree_writable(str(root))


def _seat_holders(base: str, tmpdir: str | None) -> list[Path]:
    """The `shiftlead-<uid>/` directories whose seats' scratch roots this run sweeps."""
    name = f"shiftlead-{os.getuid()}"
    holders = [Path(base) / name]
    if tmpdir and Path(tmpdir).parent.name == name and Path(tmpdir).parent not in holders:
        holders.append(Path(tmpdir).parent)
    return [h for h in holders if h.is_dir() and not h.is_symlink()]


def _marked_run_ended(root: Path) -> bool:
    """Does this root's mark name a pid no longer running? No mark, or one still being written, is a run starting."""
    if root.is_symlink() or root.parent.is_symlink():
        return False
    try:
        pid = int((root / TEST_RUN_MARK).read_text().strip())
    except (OSError, ValueError):
        return False
    return pid != os.getpid() and not _pid_running(pid)


def _scratch_parent(tmpdir: str | None) -> str:
    """Where this run's scratch root goes: `$TMPDIR` where the root made there fits `scratch.MAX_ROOT`, else `/tmp`
    (design §4.6 *Temporary space is a pool of its own*, TD-2084). The fit leaves room for `/s/r`, the root
    `test_scratch.py`'s tests make inside this one, which is held to the same bound."""
    from sessionorc.scratch import MAX_ROOT

    if tmpdir and os.path.isabs(tmpdir) and os.path.isdir(tmpdir) and os.access(tmpdir, os.W_OK | os.X_OK):
        parent = os.path.normpath(tmpdir)
        if len(os.fsencode(os.path.join(parent, "aoscr-" + "x" * 8, "s", "r"))) <= MAX_ROOT:  # tempfile's are 8 long
            return parent
    return "/tmp"


def _pid_running(pid: int) -> bool:
    """Is `pid` running? A signal 0 sends nothing; a process of another user's (`PermissionError`) counts as alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError):
        return True  # another user's, or a lock no pid could write: never swept
    return True


def sweep_dead_pytest_runs(own: Path) -> None:
    """Remove each sibling `pytest-N` of this run's base temp whose `.lock` names a pid no longer running (TD-2028).

    pytest keeps one run (`tmp_path_retention_count = 1`, TD-1890), but a run that dies before its end — a
    precheck's timeout, a killed suite, the workers' deaths of TD-2012 — leaves its `.lock`, and pytest's own
    cleanup skips a locked directory until the lock is three days old, so each dead run held 27k–53k inodes of
    the shared `/tmp` for three days in every seat that ran it. A lock that is empty or unreadable is a run still
    starting (pytest creates the file, then writes its pid), so it counts as live, as does a directory with no
    lock (a finished run, pytest's own to keep or remove); `pytest-current`, a link, and this run's own are
    never touched. A recycled pid makes a dead run look live: that costs one skipped sweep.

    Where this run's base temp lies in a seat's scratch (`<root>/shiftlead-<uid>/<token>/pytest-of-<user>/`,
    design §4.6 *A session's scratch*), every seat's `pytest-of-<user>/` under that root is swept, not only this
    one's (TD-2032): a seat that runs no suite after its run died — an idle designer — otherwise kept 160k inodes
    of the shared `/tmp` for as long as it lived, since the host agent's disk sweep never removes a live record's
    scratch. A run outside a seat sweeps its own base temp's parent alone."""
    parent = own.parent
    if not own.name.startswith("pytest-") or not parent.name.startswith("pytest-of-"):
        return  # a --basetemp of the caller's own: not pytest's numbered runs
    for base in _run_parents(parent):
        with contextlib.suppress(OSError):  # one seat's scratch going away mid-sweep never stops the others'
            _sweep_dead_runs_in(base, own)


def _run_parents(parent: Path) -> list[Path]:
    """The `pytest-of-<user>/` directories to sweep: every seat's under this one's `shiftlead-<uid>/` root, where
    this run's lies in a seat's scratch, else this run's alone."""
    root = parent.parent.parent
    if root.name != f"shiftlead-{os.getuid()}" or root.is_symlink():
        return [parent]
    seats = [
        p for p in root.glob(f"*/{parent.name}") if p.is_dir() and not p.is_symlink() and not p.parent.is_symlink()
    ]
    return seats if parent in seats else [parent, *seats]


def _sweep_dead_runs_in(parent: Path, own: Path) -> None:
    for d in parent.glob("pytest-*"):
        if d == own or d.is_symlink() or not d.is_dir():
            continue
        try:
            pid = int((d / ".lock").read_text().strip())
        except (OSError, ValueError):
            continue  # no lock, or one still being written
        if pid != os.getpid() and not _pid_running(pid):
            _rmtree_writable(str(d))


def pytest_sessionstart(session: pytest.Session) -> None:
    """The dead runs' sweep (TD-2028), in the xdist controller alone (a worker's base temp is inside the
    controller's run), from the controller's own base temp,
    over every seat's scratch where it lies in one (TD-2032)."""
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return
    factory = getattr(session.config, "_tmp_path_factory", None)
    if factory is None:
        return
    with contextlib.suppress(OSError, ValueError, OverflowError):  # a sweep never stops the run
        sweep_dead_pytest_runs(factory.getbasetemp())


@pytest.fixture(scope="session", autouse=True)
def _scratch_root():
    """Every run's scratch directory (design §4.6, TD-1944) under a short root of the test run's own, never
    the host's `/tmp/shiftlead-<uid>/`: short, since a root past 48 bytes is refused, so not `tmp_path`.
    The subprocess agent reads it from `AO_TEST_SCRATCH_ROOT` (`_agent_child.py`). It lies under `$TMPDIR` where it
    fits (TD-2084), its owner is recorded, and the roots of runs that have ended are swept first (TD-2015)."""
    from sessionorc import hosts

    tmpdir = os.environ.get("TMPDIR")
    sweep_stale_scratch_roots(tmpdir=tmpdir)
    parent = _scratch_parent(tmpdir)
    with tempfile.TemporaryDirectory(prefix="aoscr-", dir=parent, ignore_cleanup_errors=True) as root:
        name = os.path.basename(root)
        with contextlib.suppress(OSError):
            (Path(root) / TEST_RUN_MARK).write_text(str(os.getpid()))
        if parent == "/tmp":
            with contextlib.suppress(OSError):
                OWNERS.mkdir(exist_ok=True)
                (OWNERS / name).write_text(str(os.getpid()))
        mp = pytest.MonkeyPatch()
        mp.setattr(hosts, "DEFAULT_SCRATCH_ROOT", root)
        mp.setenv("AO_TEST_SCRATCH_ROOT", root)
        try:
            yield root
        finally:
            mp.undo()
            _rmtree_writable(root)
            _forget_owner(name)


@pytest.fixture
def short(_scratch_root):
    """A root of this test's own under the run's short one: `tmp_path` is past the 48 bytes a root may hold, and the
    run's root may lie in a seat's directory (TD-2084), so its name is one letter. A worker runs one test at a time."""
    d = Path(_scratch_root) / "s"
    d.mkdir()
    try:
        yield d
    finally:
        _rmtree_writable(str(d))


@pytest.fixture(scope="session", autouse=True)
def _sweep_stale_test_servers():
    sweep_stale_test_servers()
    yield


@pytest.fixture(scope="session", autouse=True)
def _never_docker():
    """Docker is not in `pdm run test` (TD-057 3c.2): a host agent's container supervisor that
    reaches `containers.Runner` here gets a refusal, never the machine's docker. A test that wants
    the seam builds its own fake on the original class."""
    from sessionorc import containers

    class NoDocker(containers.Runner):
        def run(self, cmd, *, check=True, stream=False):
            raise containers.ContainerError("docker is not in pdm run test: give the agent a fake container_runner")

        def devcontainer(self):
            raise containers.ContainerError("docker is not in pdm run test: give the agent a fake container_runner")

    original = containers.Runner
    containers.Runner = NoDocker
    yield
    containers.Runner = original


@pytest.fixture(autouse=True)
def _no_persons_settings_carried_over():
    """The UI keeps the person's `settings` read in a module global (`uiconf._read`, design §5): a
    test that draws a page leaves it holding its agent's answer, and a later test that renders a
    template directly would draw with it — so a result hung on file order (TD-275). Each test starts
    with nothing read, which is what a fresh UI has."""
    try:
        from shiftlead.ui import uiconf
    except ImportError:  # the `ui` extra is not installed: nothing to reset
        yield
        return
    uiconf.set_read({"person": {}, "migrate": []})
    yield


_SCRATCH: pytest.TempPathFactory | None = None


@pytest.fixture(scope="session", autouse=True)
def _scratch_factory(tmp_path_factory):
    global _SCRATCH
    _SCRATCH = tmp_path_factory
    yield
    _SCRATCH = None


def scratch_dir(name: str = "scratch") -> Path:
    """A new directory under this run's pytest base temp, for a helper that has no `tmp_path` (TD-1053).

    pytest keeps the newest run's base temp alone (`tmp_path_retention_count = 1`, TD-1890) and removes the rest,
    so nothing piles up in `/tmp`
    the way `tempfile.mkdtemp()` did (about 105,000 directories by 2026-10-26, kmaster's whole
    inode table). `tests/test_no_temp_leaks.py` refuses a bare `mkdtemp` in the tests."""
    assert _SCRATCH is not None, "scratch_dir() is for test time, after the session fixtures are set up"
    return _SCRATCH.mktemp(name)


@pytest.fixture(scope="session", autouse=True)
def _never_this_machines_home(tmp_path_factory):
    """No test reads this machine's `~/.shiftlead` or `~/.claude` (TD-044).

    The agent fixtures set their own `SHIFTLEAD_HOME`, but a *unit* test that only calls into
    `shiftlead.cli` sets nothing — and since `org.yml` landed (TD-040), `ao roles` reads it from
    `paths.home()`, so on a machine with a real fleet definition those tests saw Paul's roles and
    failed. Session scope on purpose: it is set up before the module- and function-scoped agent
    fixtures, which then override it with their own temp home for the tests that need one."""
    mp = pytest.MonkeyPatch()
    mp.setenv("SHIFTLEAD_HOME", str(tmp_path_factory.mktemp("unit-home")))
    mp.setenv("CLAUDE_CONFIG_DIR", str(tmp_path_factory.mktemp("unit-claude")))
    mp.delenv("SHIFTLEAD_SESSION", raising=False)  # a test run inside an ao session is not a caller
    # …nor does it hand its model to the private tmux server, whose shells would inherit it (TD-671):
    # the live server is the host agent's, whose own env never carries a session's model (§4.2)
    mp.delenv("AGENT_MODEL", raising=False)
    mp.delenv("AGENT_MODEL_FILE", raising=False)
    # …nor this machine's agent-cadence layers: a brief a test composes carries no person's rules (TD-1016)
    mp.setenv("AGENT_CADENCE_REG_DIR", str(tmp_path_factory.mktemp("no-cadence-machine")))
    # …and nor is its ancestry: the exit-3 sentence reads the pane's environment above `ao` (TD-089)
    from shiftlead import cli

    mp.setattr(cli, "PROC", tmp_path_factory.mktemp("no-proc"))
    yield
    mp.undo()


# -- waiting --------------------------------------------------------------------------------------


async def wait_for(pred: Callable[[], object], timeout: float = 6.0, step: float = 0.1) -> bool:
    """Poll an async or sync predicate until it is truthy. Bounded: returns False on timeout."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        res = pred()
        if asyncio.iscoroutine(res):
            res = await res
        if res:
            return True
        await asyncio.sleep(step)
    return False


def wait_for_sync(pred: Callable[[], object], timeout: float = 5.0, step: float = 0.05) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return False


def pane_line(sid: str) -> str:
    """What tmux itself says about a session's pane, for a wait that timed out (TD-025): the
    record's state and tail alone cannot tell a slow shell start from a pane that never appeared."""
    sock = os.environ.get("SHIFTLEAD_TMUX_SOCKET")
    if not sock:
        return "(no SHIFTLEAD_TMUX_SOCKET: pane not inspected)"
    try:
        pane = Tmux(socket_name=sock).main_panes().get(sid)
    except Exception as e:  # noqa: BLE001 — a diagnostic must never mask the assertion
        return f"(pane lookup failed: {e})"
    return f"pane={pane}" if pane else "pane=none (not in list-panes)"


def wait_screen(sid: str, produce, ok, timeout: float = 8.0, step: float = 0.1, what: str = "what it asserts on"):
    """Read a live pane until it shows the thing the assertion is about, then return that reading
    (TD-033, TD-025): `produce()` is re-run until `ok(value)`. Several tests read a pane once and
    asserted on it, which passes on an idle box and races a loaded one — a pane that has not
    painted yet is not a wrong pane, it is an early read. This is `wait_state` for a screen: bounded,
    on the real signal, and a timeout says what never appeared plus tmux's own pane line."""
    end = time.monotonic() + timeout
    while True:
        value = produce()
        if ok(value):
            return value
        if time.monotonic() >= end:
            raise AssertionError(f"{sid}: {what} never appeared in {timeout}s: {value!r} {pane_line(sid)}")
        time.sleep(step)


async def wait_state(client, sid: str, state: str, timeout: float = 6.0) -> dict:
    s = await client.call("get", id=sid)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if s["state"] == state:
            return s
        await asyncio.sleep(0.1)
        s = await client.call("get", id=sid)
    raise AssertionError(f"{sid} never reached {state}: {s['state']} {s.get('tail')} {pane_line(sid)}")


async def derived(agent, check, timeout: float = 10.0):
    """Drive derivations until `check()` holds, and return what it returned (TD-063).

    `tick()` starts a derivation only when `self._derive_task` is None or done, and the `agent`
    fixture runs a live tick loop at `FAST_TICK`. So a background tick can already own an in-flight
    derive whose snapshot predates whatever the test just changed — a `git checkout`, a `gh` stub —
    and the test's own `tick()` then starts nothing at all: `await agent._derive_task` awaits that
    stale derive, which legitimately still reports the old answer. Seen on CI 2026-09-17 as
    `test_the_tick_retires_a_branch_claim_the_session_abandoned` asserting `progress == []` one
    derive too early. Waiting on the condition instead of on one task is what makes it deterministic:
    a stale derive costs a retry rather than a failure, and nothing here waits on a duration.

    `check` is called after each round and may be a coroutine function.
    """
    end = time.monotonic() + timeout
    while True:
        if (t := agent._derive_task) is not None and not t.done():
            # A derive this helper did not start: whatever it raises belongs to the round that
            # started it, not to this one, and the round below is the one under test.
            with contextlib.suppress(Exception):
                await t  # let a tick's in-flight derive finish before asking for a fresh one
        agent._git_checked.clear()  # the branch read has its own cadence; the derive follows it
        agent._derived_at.clear()
        await agent.tick()
        if (t := agent._derive_task) is not None:
            await t  # not suppressed: this is the derive the round asked for, and its traceback is
            # worth more than the generic timeout below (review of PR #199)
        got = check()
        if asyncio.iscoroutine(got):
            got = await got
        if got:
            return got
        if time.monotonic() > end:
            raise AssertionError(f"the derive never satisfied {getattr(check, '__doc__', None) or check}")
        await asyncio.sleep(0.05)


# -- the in-process agent -----------------------------------------------------------------------


PASS_DRAIN = 30.0  # seconds `park_ticks` waits for a tick's detached passes to land


def gate_on(gate: dict, prof: str) -> dict | None:
    """The `gate` reply's account the profile `prof` is on (design §6 *The readers*, TD-1610), None if none."""
    return next((a for a in gate["accounts"].values() if prof in a["profiles"]), None)


async def park_ticks(agent) -> None:
    """Stop the fixture's tick loop for the rest of the test, so a test that must own the clock
    **owns** it: every tick after this is one the test takes by hand with `await agent.tick()`.

    Narrowing the window is not the same as closing it — TD-078 and TD-088 are both a wait bounded
    on something other than the thing waited for, and a sleep raced against the loop is exactly
    that. Cancelling the task cannot race: it is awaited here, so an in-flight tick is finished or
    cancelled before this returns. Nothing resumes it; `serve`'s own `finally` cancels a cancelled
    task harmlessly at teardown.
    """
    t = getattr(agent, "_ticker", None)
    if t is None:
        return
    t.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await t
    # a tick's detached passes (`_promote_task`, `_repos_task`, …) outlive it: one still in flight lands
    # after the test has set the state it replaces — a late promote reading put back `_promotes` without
    # the test's live commit, and a lane note went unsent (TD-858; TD-752 and TD-753 awaited them by hand)
    # — so each is finished here, and one that has not finished in PASS_DRAIN is cancelled. A pass can start
    # another as it ends (the promote pass starts `_sync_task`, TD-1101), so the drain runs until none is left
    end = time.monotonic() + PASS_DRAIN
    while passes := [
        t for k, t in vars(agent).items() if k.endswith("_task") and isinstance(t, asyncio.Task) and not t.done()
    ]:
        _, late = await asyncio.wait(passes, timeout=max(0.0, end - time.monotonic()))
        if late and time.monotonic() >= end:
            for task in late:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task


@pytest.fixture
async def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("SHIFTLEAD_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))  # never this machine's live registry
    monkeypatch.delenv("SHIFTLEAD_SESSION", raising=False)  # tests run inside an ao session are not a caller
    monkeypatch.setattr("sessionorc.agent_common.TICK_SECONDS", FAST_TICK)
    sock_name = private_socket_name()
    monkeypatch.setenv("SHIFTLEAD_TMUX_SOCKET", sock_name)  # so `pane_line` can look at this server
    tmux = Tmux(socket_name=sock_name)
    a = HostAgent(tmux=tmux)

    async def no_push_child(secrets, mode, stdin=""):
        # never a real Doppler (TD-1304): the pass reads the push key whenever a secrets config is set, Telegram's
        # included; a test that drives the push child sets its own
        return [], "no push child in tests", False

    a._push_run = no_push_child
    task = asyncio.create_task(a.serve(paths.socket_path()))

    # the tick loop too (TD-1087): `serve` binds the socket a loop step before it makes `_ticker`, so a
    # test that parked the ticks in that step found none to park, and the loop started under it
    def up() -> bool:
        return paths.socket_path().exists() and a._ticker is not None

    assert await wait_for(up, timeout=5.0, step=0.05), "agent socket or tick loop never appeared"
    yield a
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
    kill_private_server(tmux)


# -- the subprocess agent -----------------------------------------------------------------------

# **A hang shows the agent's side too** (TD-2037). A test that waits on a child agent past the hang bound is ended by
# pytest-timeout, and pyproject's `faulthandler_timeout` prints the worker's own stacks just before, but those show
# only the test waiting on a reply. So, ten seconds before them, every live child agent is sent SIGUSR1 (it dumps all
# its threads to its stderr file, `_agent_child.py`) and the file's tail is written to the worker's stderr, which
# xdist prints. A test that takes no child agent arms nothing.
_LIVE_CHILDREN: dict[int, Path] = {}  # pid → its stderr file, while the module's agent runs
HANG_WATCH = 100.0  # seconds: below pyproject's faulthandler_timeout (110) and timeout (120)
HANG_TAIL = 20_000  # bytes of each child's stderr shown


def _show_children_stacks(nodeid: str, fd: int) -> None:
    for pid in list(_LIVE_CHILDREN):
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGUSR1)
    time.sleep(1.0)
    for pid, path in list(_LIVE_CHILDREN.items()):
        try:
            tail = path.read_bytes()[-HANG_TAIL:]
        except OSError as e:
            tail = f"(cannot read {path}: {e})".encode()
        head = f"\n--- TD-2037: {nodeid} still running after {HANG_WATCH:.0f}s; child agent {pid}'s stderr tail ---\n"
        with contextlib.suppress(OSError):
            os.write(fd, head.encode() + tail + b"\n--- end of child agent stderr ---\n")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    timer = None
    if _LIVE_CHILDREN or "subprocess_agent" in getattr(item, "fixturenames", ()):
        # the stderr pytest's faulthandler writes to: fd 2 itself is captured while a test runs
        fd = item.config.stash.get(fault_handler_stderr_fd_key, 2)
        timer = threading.Timer(HANG_WATCH, _show_children_stacks, args=(item.nodeid, fd))
        timer.daemon = True
        timer.start()
    try:
        yield
    finally:
        if timer is not None:
            timer.cancel()


def spawn_agent_child(sock_name: str, env: dict[str, str], **popen_kw) -> subprocess.Popen:
    """Start `_agent_child.py` so it ends with this process, however this process ends (TD-2067).

    This process alone holds the pipe's write end (non-inheritable, so no other child gets it); when it dies the child
    reads EOF and stops. A pipe of its own rather than stdin, which the agent's own subprocesses would inherit.
    """
    read_end, write_end = os.pipe()
    try:
        proc = subprocess.Popen(
            [sys.executable, str(CHILD), sock_name],
            env={**env, "AO_TEST_OWNER_FD": str(read_end)},
            pass_fds=(read_end,),
            **popen_kw,
        )
    except BaseException:
        os.close(write_end)
        raise
    finally:
        os.close(read_end)
    weakref.finalize(proc, os.close, write_end)
    return proc


class ChildAgent(NamedTuple):
    home: Path
    sock_name: str
    proc: subprocess.Popen


@pytest.fixture(scope="module")
def subprocess_agent(tmp_path_factory):
    """Module-scoped, so it cannot take the function-scoped `monkeypatch`; a manual MonkeyPatch,
    undone at teardown, sets the env in the test process AND the child."""
    mp = pytest.MonkeyPatch()
    home = tmp_path_factory.mktemp("home")
    sock_name = private_socket_name()
    proc: subprocess.Popen | None = None
    try:
        mp.setenv("SHIFTLEAD_HOME", str(home))
        mp.setenv("CLAUDE_CONFIG_DIR", str(home / "claude"))  # never this machine's live registry
        mp.setenv("SHIFTLEAD_TMUX_SOCKET", sock_name)
        mp.setenv("SHIFTLEAD_TICK", str(FAST_TICK))
        # `ao` sends SHIFTLEAD_SESSION as the caller (design §4.8); a test run from inside an ao
        # session would otherwise be gated as a session acting on another one
        mp.delenv("SHIFTLEAD_SESSION", raising=False)
        # the board write-back lands an edit through `gh` (§4.4, TD-264): the child gets the fake
        mp.setenv("PATH", f"{fake_gh_bin(home / 'fake-bin')}{os.pathsep}{os.environ.get('PATH', '')}")
        # its stderr goes to a file, never an unread pipe (TD-2037): the agent lives for the whole module and logs
        # as it goes, and a pipe nobody drains blocks its next write once full, which freezes every request to it
        err_path = home / "agent.stderr"
        with open(err_path, "w") as err_file:
            proc = spawn_agent_child(sock_name, dict(os.environ), stdout=subprocess.DEVNULL, stderr=err_file, text=True)

        def err() -> str:
            return err_path.read_text(errors="replace")

        _LIVE_CHILDREN[proc.pid] = err_path
        sock = home / "agent.sock"
        if not wait_for_sync(lambda: sock.exists() or proc.poll() is not None, timeout=10.0):
            proc.kill()
            proc.wait(timeout=5)
            raise RuntimeError(f"child agent never opened {sock}:\n{err()}")
        if proc.poll() is not None:
            raise RuntimeError(f"child agent exited {proc.returncode}:\n{err()}")
        yield ChildAgent(home=home, sock_name=sock_name, proc=proc)
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
            raise RuntimeError(f"child agent ignored SIGTERM:\n{err()}") from None
    finally:
        if proc is not None:
            _LIVE_CHILDREN.pop(proc.pid, None)
        # runs on setup failure too, so the env never leaks into later modules
        if proc is not None and proc.poll() is None:
            proc.kill()
        kill_private_server(Tmux(socket_name=sock_name))
        mp.undo()
    if proc.returncode not in (0, -signal.SIGTERM):
        raise RuntimeError(f"child agent exited {proc.returncode}:\n{err()}")


# -- hook-fed stub adapter ----------------------------------------------------------------------


@pytest.fixture
def hookstub(monkeypatch):
    """Register `HookFedStub` for this test only (the registry keeps its built-ins)."""
    from sessionorc import adapters

    adapters.load_all()
    stub = HookFedStub()
    monkeypatch.setitem(adapters._REGISTRY, stub.name, stub)
    return stub


@pytest.fixture
def composerstubs(monkeypatch):
    """Register `composer0`, `composer1`, `composer2` (a pane that swallows that many Enters per
    paste) for this test only (TD-027)."""
    from sessionorc import adapters

    adapters.load_all()
    for n in (0, 1, 2):
        stub = ComposerStub(n)
        monkeypatch.setitem(adapters._REGISTRY, stub.name, stub)


# -- the real hook script -----------------------------------------------------------------------


def run_hook(session: str, payload: dict, wait: str = "5", env: dict[str, str] | None = None):
    """Run `shiftlead-hook` as Claude Code would: payload on stdin, session in the env."""
    env = {**(env or os.environ), "SHIFTLEAD_SESSION": session, "SHIFTLEAD_PERMISSION_WAIT": wait}
    return subprocess.run(
        [sys.executable, "-m", "shiftlead.adapters.claude_code.hook"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


@pytest.fixture
def forge(tmp_path, monkeypatch):
    """A fake `gh` first on `PATH` (`tests/_fake_gh.py`), for the board write-back, which lands an edit
    on origin by a pull request it opens and squash-merges (design §4.4, TD-264). Returns
    `with_origin`, which gives a checkout a bare origin holding its `main`."""
    monkeypatch.setenv("PATH", f"{fake_gh_bin(tmp_path / 'fake-bin')}{os.pathsep}{os.environ.get('PATH', '')}")
    return with_origin


def fake_gh_bin(bin_dir: Path) -> Path:
    """A directory holding `gh`, the fake forge `tests/_fake_gh.py`, to put first on `PATH`."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\nexec {sys.executable} {Path(__file__).parent / "_fake_gh.py"} "$@"\n')
    gh.chmod(0o755)
    return bin_dir


def with_origin(root: Path) -> Path:
    """Give the checkout `root` a bare origin beside it holding its `main`, and return the origin."""
    bare = root.parent / f"{root.name}-origin.git"

    def run(*a: str) -> None:
        subprocess.run(["git", *a], capture_output=True, text=True, check=True)

    run("init", "-q", "--bare", "-b", "main", str(bare))
    run("-C", str(root), "remote", "add", "origin", str(bare))
    run("-C", str(root), "push", "-q", "origin", "main")
    run("-C", str(root), "fetch", "-q", "origin")
    run("-C", str(root), "remote", "set-head", "origin", "main")
    return bare


def served(root) -> None:
    """agent-cadence's tree, its gate and a ledger in `root`, so the home reads it served (§5 *The seams*,
    TD-1011): a registered test repo without them is unserved, and the home writes nothing there."""
    root = Path(root)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    (root / "docs" / "cadence-sync.lock").write_text("source: agent-cadence\ncommit: abc1234\nfiles_commit: abc1234\n")
    (root / "scripts" / "check_cadence.py").write_text("x = 1\n")
    if not (root / "docs" / "technical_debt.md").exists():
        (root / "docs" / "technical_debt.md").write_text("# Technical debt\n")


# What the resolver says when the pinned tree cannot be reached — no network, no token for a private
# source (CI), a slow fetch: a test skips on these. Anything else — a malformed pin, a commit the source
# does not have, an interface this build is too old for — is a broken pin, and fails.
_UNREACHABLE = ("git ", "the launcher gave no answer", "the launcher could not run", "another launcher has held")


def repo_ledger() -> tuple[str, str]:
    """(ledger text, archive text) of this checkout's own ledger, through the reader the home uses
    (`ledger.read_pair`, §4.4 *Either layout*): a v2 `docs/ledger/` reads as the text a v1 file would
    hold, without its summary table, so a test of the repo's own entries never names a layout (TD-1195)."""
    from sessionorc import ledger

    root = Path(__file__).resolve().parents[1]
    _, text, archive, faults = ledger.read_pair(ledger.ledger_path(root), ledger.fs_io(root))
    assert text is not None and not faults, faults or "this checkout's ledger cannot be read"
    return text, archive or ""


def pinned_script(name: str) -> Path:
    """agent-cadence's `scripts/<name>` in the tree this checkout pins (`docs/cadence.toml`'s `[agent-cadence]`,
    dev-cadence TD-129): ShiftLead carries no synced copies, so a test that runs or loads one of
    agent-cadence's scripts — a parity test of the home's reader, a reader as a fixture — takes it from the
    pinned tree, through the same resolver the home uses (`cadence.tree`). Where the tree cannot be
    reached (no network, or no token for a private source, as on CI) the test skips, naming why; a pin
    the resolver refuses fails it, so a broken pin never turns these checks into silent skips."""
    from sessionorc import cadence

    root = Path(__file__).resolve().parents[1]
    try:
        assert cadence.pin(root) is not None, "this checkout has no [agent-cadence] pin in docs/cadence.toml"
    except cadence.PinError as e:
        pytest.fail(f"this checkout's agent-cadence pin is malformed: {e}")
    payload, why = cadence.tree(root)
    if payload is None:
        if why and why.startswith(_UNREACHABLE):
            pytest.skip(f"agent-cadence's pinned tree could not be reached: {why}")
        pytest.fail(f"agent-cadence's pin does not resolve: {why}")
    script = payload / "scripts" / name
    assert script.is_file(), f"the pinned agent-cadence tree has no scripts/{name}"
    return script


def copy_pinned_ledgerboard(scripts: Path) -> Path:
    """The pinned tree's `scripts/ledgerboard/` package (v2.3, TD-1330) copied into `scripts`, beside a
    reader copied there that imports it; returns the copy."""
    pkg = pinned_script("ledgerboard/__init__.py").parent
    dest = Path(scripts) / "ledgerboard"
    dest.mkdir(parents=True, exist_ok=True)
    for f in pkg.glob("*.py"):  # file by file: the pinned tree is read-only, and a copied mode would keep it
        (dest / f.name).write_bytes(f.read_bytes())
    return dest
