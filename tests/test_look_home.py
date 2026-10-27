"""`scripts/look_home.py`, the scratch home a builder looks at its UI change in (design §4.9b, TD-291)."""

from __future__ import annotations

import importlib.util
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from conftest import pinned_script

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "look_home.py"


def _load():
    spec = importlib.util.spec_from_file_location("look_home", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_live_home_and_a_long_path_are_refused(tmp_path):
    lh = _load()
    live = Path("~/.shiftlead").expanduser()
    assert "live shiftlead home" in lh.refuse_live(live)
    assert "live shiftlead home" in lh.refuse_live(live / "look")
    assert "too long" in lh.refuse_live(Path("/tmp") / ("x" * 120))
    assert lh.refuse_live(Path("/tmp/aolook-x")) is None
    # the command refuses before it makes anything
    assert lh.main(["--home", str(live / "look")]) == 2
    assert not (live / "look").exists()
    (tmp_path / "there").mkdir()
    assert lh.main(["--home", str(tmp_path / "there")]) == 2  # never an existing directory


def test_it_serves_the_org_with_fixture_sessions_and_leaves_nothing(tmp_path):
    pinned_script("nudge_user_attention.py")  # its fixture repo is made from the pinned tree: skip where it is not
    env = {k: v for k, v in os.environ.items() if k != "SHIFTLEAD_SESSION"}
    err = (tmp_path / "stderr").open("w")  # what the script said, shown when it printed no URL
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT), "--sessions", "2"],
        stdout=subprocess.PIPE,
        stderr=err,
        text=True,
        env=env,
    )
    home = sock = None
    try:
        end = time.monotonic() + 60
        line = ""
        while time.monotonic() < end and proc.poll() is None:
            line = proc.stdout.readline()
            if line.startswith("look home:"):
                break
        m = re.match(r"look home: (http://127\.0\.0\.1:\d+/)\s+\(SHIFTLEAD_HOME=(\S+), tmux -L (\S+)\)", line)
        assert m, f"no URL printed: {line!r}\n{(tmp_path / 'stderr').read_text()}"
        url, home, sock = m.group(1), Path(m.group(2)), m.group(3)
        assert home.is_relative_to("/tmp") and (home / "agent.sock").exists()
        assert sock.startswith("ao-look-")
        page = urllib.request.urlopen(url, timeout=20).read().decode()
        assert "look-shell-1" in page and "look-shell-2" in page and "look-shell-3" not in page
        # the fixture board, read by the reader the fixture repo carries; its lines name TD-001, so they are
        # drawn on that entry's Queue card (design §4.5 screen 6 *Where a row is drawn*, TD-771). The board
        # is read by the host agent's tick, which under a loaded suite lands after the first GET (TD-1104)
        end = time.monotonic() + 60
        while True:
            queue = urllib.request.urlopen(url + "queue", timeout=30).read().decode()
            if "A fixture act line." in queue or time.monotonic() > end:
                break
            time.sleep(0.5)
        assert "A fixture act line." in queue
        # the fixture repo is served (§5 *The seams*, TD-1011): its ledger is drawn, no lack in its place
        repo = urllib.request.urlopen(url + "repo/repo", timeout=30).read().decode()
        assert 'id="unserved"' not in repo and "Technical debt" in repo
    finally:
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == 0
    assert home is not None and not home.exists()  # the home it made is gone
    gone = subprocess.run(["tmux", "-L", sock, "list-sessions"], capture_output=True)
    assert gone.returncode != 0  # and its tmux server with it


def test_the_home_is_removed_again_when_an_exit_hook_writes_into_it_after_the_first_removal(tmp_path):
    """TD-311: a claude-code session killed with the tmux server still runs its exit hooks, which append
    to `<home>/events/` after the first removal; the teardown removes the home until it stays gone."""
    import threading

    lh = _load()
    home = tmp_path / "aolook-x"
    (home / "events").mkdir(parents=True)

    def late_hook():
        time.sleep(0.3)  # after the first removal
        (home / "events").mkdir(parents=True, exist_ok=True)
        (home / "events" / "ao-repo-entry-1.jsonl").write_text("{}\n")

    t = threading.Thread(target=late_hook)
    t.start()
    lh.remove_home(home, quiet=2.0, limit=8.0, step=0.1)  # wide of the hook's 0.3 s, under load too
    t.join()
    assert not home.exists()
    started = time.monotonic()
    lh.remove_home(tmp_path / "never-made", quiet=0.2)  # nothing there: returns after the quiet spell
    assert time.monotonic() - started < 1.0
