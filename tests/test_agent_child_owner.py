"""A test's agent child ends with the run that started it, however that run ends (TD-2067)."""

import os
import signal
import subprocess
import sys
from pathlib import Path

from conftest import HERE, kill_private_server, scratch_dir, wait_for_sync

from sessionorc.tmux import Tmux

HOLDER = """
import os, time
from pathlib import Path

def test_hold(subprocess_agent):
    out = Path(os.environ["AO_TEST_HOLDER_OUT"])
    out.with_suffix(".tmp").write_text(f"{subprocess_agent.proc.pid} {subprocess_agent.sock_name}")
    out.with_suffix(".tmp").rename(out)
    time.sleep(120)
"""


def _running(pid: int) -> bool:
    """Whether the pid runs: an orphan that exited can stay a zombie until its new parent reaps it."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rpartition(")")[2].split()[0] != "Z"


def test_a_sigkilled_run_s_child_ends_and_a_concurrent_run_s_stays_up(subprocess_agent, tmp_path):
    (tmp_path / "test_holder.py").write_text(HOLDER)
    out = tmp_path / "holder.out"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "AO_TEST_OWNER"))}
    env["AO_TEST_HOLDER_OUT"] = str(out)
    env["PYTHONPATH"] = os.pathsep.join([str(HERE), str(HERE.parent / "src"), env.get("PYTHONPATH", "")])
    log = tmp_path / "holder.log"
    run = subprocess.Popen(
        [sys.executable, "-m", "pytest", "-p", "conftest", "-p", "no:cacheprovider", "-o", "addopts=", "-q"]
        + ["--rootdir", str(tmp_path), f"--basetemp={scratch_dir('o') / 't'}", str(tmp_path / "test_holder.py")],
        cwd=tmp_path,
        env=env,
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
    )
    pid = None
    sock_name = None
    try:
        assert wait_for_sync(lambda: out.exists() or run.poll() is not None, timeout=30.0), "the holder never started"
        assert out.exists(), f"the holder run exited {run.returncode}:\n{log.read_text()}"
        raw_pid, sock_name = out.read_text().split()
        pid = int(raw_pid)
        assert _running(pid)
        run.send_signal(signal.SIGKILL)
        run.wait(timeout=5)
        assert wait_for_sync(lambda: not _running(pid), timeout=10.0), "the killed run's child is still running"
        assert subprocess_agent.proc.poll() is None, "a concurrent run's child was stopped too"
    finally:
        if run.poll() is None:
            run.kill()
            run.wait(timeout=5)
        if pid is not None and _running(pid):
            os.kill(pid, signal.SIGKILL)
        if sock_name is not None:
            kill_private_server(Tmux(socket_name=sock_name))
