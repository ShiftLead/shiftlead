"""The stub CLI a seat's life runs as its tool (design §4.3 *A seat's life end to end, in CI, with no model*,
TD-1647). One tool-neutral program: it decides nothing a tool decides, and replays the adapter's own captured
fixtures. Run by the wrapper the case writes as the adapter's `binary`:

    stub_cli.py <adapter> <script> -- <the tool's own arguments>

- `--version` alone prints a version line and exits, writing nothing, as a tool answers the read a seat's
  launch makes (design §4.3 *An upgraded seat tool asks for the smoke*);
- its argv after `--`, its `SHIFTLEAD_*` and `CADENCE_*` environment and its pid go to `launch.json` beside
  the script, where the case asserts the launch, never runs it;
- the manifest's `life` payloads from `captured/hooks.jsonl` are handed on stdin to the hook command the
  adapter's layer names (the harness's `hook_command`), run with the pane's environment, the captured session
  id replaced by the launch's (the harness's `session_id`): `start` at once, `turn` for each turn, `end` on
  `SIGHUP` or `SIGTERM` (the host agent's close kills the tmux session), after which a line saying so goes
  to `events.log` and the stub exits;
- the `life.composer` pane is printed after the start and after each turn, so the adapter's own `composer`
  reads it; the terminal echoes nothing typed, so the composer reads empty once a line is submitted;
- the first line typed plays a turn, its text never read; a later line of the doorbell's shape plays a turn
  that runs the script's two commands against the home — the inbox read, then the reply for each open ask,
  `{id}` and `{text}` filled, the text the ask's last word.
"""

from __future__ import annotations

import errno
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import termios
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _harness import HARNESSES, fixture, manifest  # noqa: E402

from sessionorc import mail  # noqa: E402

# the host agent's own match of a ring (agent_tick._DOORBELL), built from the same line
DOORBELL = re.compile(re.escape(mail.unread_line(0)).replace("0", r"\d+") + r"\Z")
PAUSE = 0.4  # between a turn's payloads, so the case's poll sees each state


class Stub:
    def __init__(self, adapter: str, script: Path, argv: list[str]) -> None:
        self.adapter, self.script, self.argv = adapter, script, argv
        self.out = script.parent
        self.env = dict(os.environ)
        harness = HARNESSES[adapter]
        self.hook = harness.hook_command(argv, self.env)
        self.sid, field = harness.session_id(argv, self.env)
        life = manifest(adapter)["life"]
        self.life = life
        hooks = next(h for h in manifest(adapter)["hooks"] if h["file"] == "captured/hooks.jsonl")
        lines = fixture(adapter, hooks["file"]).read_text(encoding="utf-8").splitlines()
        self.payloads = [x for x in lines if x.strip()]
        captured = json.loads(self.payloads[life["start"]])[field]
        if self.sid:
            self.payloads = [x.replace(captured, self.sid) for x in self.payloads]
        self.pane = fixture(adapter, life["composer"]).read_text(encoding="utf-8")
        self.turns = 0
        self.ending = False

    def log(self, line: str) -> None:
        with (self.out / "events.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def play(self, index: int) -> None:
        """One captured payload through the layer's hook command, as the tool hands it."""
        cp = subprocess.run(
            self.hook, shell=True, input=self.payloads[index], capture_output=True, text=True, env=self.env, timeout=60
        )
        self.log(f"played {index} exit {cp.returncode}")
        if cp.returncode != 0:
            self.log(f"hook stderr: {cp.stderr.strip()[-2000:]}")

    def paint(self) -> None:
        try:
            sys.stdout.write("\x1b[2J\x1b[H" + self.pane.rstrip("\n") + "\n")
            sys.stdout.flush()
        except OSError as e:  # the pane closed under the write: its signal is on its way (TD-1749)
            self.log(f"tty write failed: {e.errno}")

    def turn(self, commands: bool) -> None:
        first, *rest = self.life["turn"]
        self.play(first)
        time.sleep(PAUSE)
        if commands:
            self.answer()
        for i in rest:
            self.play(i)
            time.sleep(PAUSE)
        self.turns += 1
        self.log(f"turn {self.turns} done")
        self.paint()

    def answer(self) -> None:
        """The script's two commands: the inbox read, then the reply to each open ask."""
        read, reply = [x for x in self.script.read_text(encoding="utf-8").splitlines() if x.strip()][:2]
        cp = subprocess.run(read, shell=True, capture_output=True, text=True, env=self.env, timeout=60)
        self.log(f"read exit {cp.returncode}")
        try:
            box = json.JSONDecoder().raw_decode(cp.stdout[cp.stdout.index("{") :])[0]
        except ValueError:
            self.log(f"read gave no inbox: {cp.stdout[-500:]!r} {cp.stderr[-500:]!r}")
            return
        for e in box.get("entries") or []:
            if e.get("kind") != "ask" or e.get("closed_by"):
                continue
            words = (e.get("text") or "").split()
            word = re.sub(r"[^\w.-]", "", words[-1] if words else "")  # the script quotes `{text}` itself
            line = reply.format(id=shlex.quote(e["id"]), text=word)
            got = subprocess.run(line, shell=True, capture_output=True, text=True, env=self.env, timeout=60)
            self.log(f"replied {e['id']} exit {got.returncode}")
            if got.returncode != 0:
                self.log(f"reply stderr: {got.stderr.strip()[-2000:]}")

    def end(self, signum: int, frame: Any) -> None:
        if self.ending:
            return
        self.ending = True
        if self.life.get("end") is not None:
            self.play(self.life["end"])
            self.log("end played")
        self.log(f"exit on signal {signum}")
        os._exit(0)

    def run(self) -> None:
        # written beside, then renamed: the test waits for launch.json to exist and reads it at once,
        # so it must never exist half-written (TD-1710)
        tmp = self.out / "launch.json.tmp"
        tmp.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "hook": self.hook,
                    "argv": self.argv,
                    "env": {k: v for k, v in self.env.items() if k.startswith(("SHIFTLEAD_", "CADENCE_"))},
                }
            ),
            encoding="utf-8",
        )
        os.replace(tmp, self.out / "launch.json")
        signal.signal(signal.SIGHUP, self.end)
        signal.signal(signal.SIGTERM, self.end)
        if sys.stdin.isatty():
            attrs = termios.tcgetattr(sys.stdin)
            attrs[3] &= ~termios.ECHO  # nothing typed is painted: the composer row stays the pane's own
            termios.tcsetattr(sys.stdin, termios.TCSANOW, attrs)
        self.play(self.life["start"])
        self.log("started")
        self.paint()
        while True:
            try:
                line = sys.stdin.readline()
            except OSError as e:
                # a closed pane's tty answers a read with EIO, which can land before the close's SIGHUP:
                # raised, it ended the stub before `end` ran (TD-1749); it is the terminal gone, as EOF is
                if e.errno != errno.EIO:
                    raise
                self.log(f"tty read failed: {e.errno}")
                line = ""
            if not line:
                time.sleep(3600)  # the terminal is gone: the close's signal ends the stub
                continue
            text = line.rstrip("\r\n")
            if self.turns == 0:
                self.log("first prompt")
                self.turn(commands=False)
            elif DOORBELL.match(text.strip()):
                self.log("doorbell")
                self.turn(commands=True)
            else:
                self.log(f"ignored a line of {len(text)} characters")


def main() -> None:
    adapter, script, sep, *argv = sys.argv[1:]
    assert sep == "--", f"usage: stub_cli.py <adapter> <script> -- <argv>, not {sys.argv!r}"
    if argv == ["--version"]:  # as a tool answers it, launching nothing: a seat's launch reads it (§4.3, TD-1726)
        print(f"0.0.0 (stub {adapter})")
        return
    Stub(adapter, Path(script), argv).run()


if __name__ == "__main__":
    main()
