"""Test-only launcher: a host agent on a private tmux socket, in its own process.

`shiftlead-agent serve` builds `Tmux()` with no socket name, i.e. the user's real tmux server, so
the test suite never spawns it. This script takes the socket name as its one argument and reads
`SHIFTLEAD_HOME` / `SHIFTLEAD_TICK` from its environment like the real agent does.

Stops the way `shiftlead-agent serve` does (`serve_until_signal`, TD-024): SIGTERM cancels the
serve task, `serve()`'s `finally` unlinks the socket file, and the process exits 0 with no
pending-task traceback — `test_agent_restart.py` asserts exactly that on this child.

Ends with whoever started it (TD-2067): `conftest.spawn_agent_child` holds the write end of a pipe and names the read
end in `AO_TEST_OWNER_FD`. The kernel closes the write end however the owner dies, a SIGKILL included, and the EOF here
stops this process the same way a SIGTERM does.
"""

import asyncio
import faulthandler
import logging
import os
import signal
import sys
import threading
import time
from datetime import timedelta

from _stubs import AgentShellStub, HookFedStub

from sessionorc import adapters, gatesweep, hosts, mail, tools
from sessionorc import agent_common as agent_mod
from sessionorc.agent import HostAgent, serve_until_signal
from sessionorc.tmux import Tmux


async def _run(socket_name: str) -> None:
    # never the person's agent-cadence roster: the home reads repo facts (`gh`, git) for every repo
    # on it (design §4.4 *Repo facts*), as conftest's `_no_real_repos_registry` says for this process
    hosts.AGENT_CADENCE_ROSTER = os.path.join(os.environ["SHIFTLEAD_HOME"], "no-roster", "repos.txt")
    # never the host's own /tmp/shiftlead-<uid>: conftest's `_scratch_root` names a short one for the run (TD-1944)
    hosts.DEFAULT_SCRATCH_ROOT = os.environ.get("AO_TEST_SCRATCH_ROOT") or hosts.DEFAULT_SCRATCH_ROOT
    # never the real gate sweep (TD-1376), which opens PRs on the forge: conftest's `_no_real_gate_sweep`
    gatesweep.eligible = lambda root: (False, "tests run no gate sweep")
    # never the person-text check (TD-1846) but in a test marked for it: conftest's `_person_text_off_unless_marked`
    mail.PERSON_TEXT_CHECK = False
    # never this machine's real tools at start (TD-2002): conftest's `_no_start_tools_read`
    tools.READ_AT_START = os.environ.get("AO_TEST_TOOLS_AT_START") == "1"
    adapters.load_all()
    adapters.register(HookFedStub())  # test-only, hook-fed: see _stubs.py
    adapters.register(AgentShellStub())  # test-only, a shell that counts as an agent
    if settle := os.environ.get("AO_TEST_RESTART_SETTLE"):
        # a crash loop run against the clock: the settle after a restart (TD-186) in seconds, not 60
        agent_mod.RESTART_SETTLE = timedelta(seconds=float(settle))
    await serve_until_signal(
        HostAgent(tmux=Tmux(socket_name=socket_name), identity_mode=os.environ.get("AO_TEST_IDENTITY", "off"))
    )


def _end_with_owner() -> None:
    """Watch the owner's pipe (TD-2067); the variable leaves the environment, so no session started here sees it."""
    raw = os.environ.pop("AO_TEST_OWNER_FD", None)
    if raw is None:
        return
    fd = int(raw)
    os.set_inheritable(fd, False)

    def watch() -> None:
        while os.read(fd, 1):
            pass
        os.kill(os.getpid(), signal.SIGTERM)  # serve()'s own way out; before its handler is set, the default ends us
        time.sleep(5)
        os._exit(1)  # the owner is gone, so nothing else would ever stop an agent stuck in its shutdown

    threading.Thread(target=watch, name="owner-watch", daemon=True).start()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # TD-2037: conftest's hang watchdog sends SIGUSR1 to a child agent a test is stuck on, so a request that never
    # comes back shows where the agent is, not only the test's side of the wait
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    _end_with_owner()
    asyncio.run(_run(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
