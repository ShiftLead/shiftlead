"""The `agent-cadence` console script (design §4.4a, §5 *How the readers find agent-cadence*, TD-1014): the
vendored launcher, `sessionorc/agent_cadence.py`, kept frozen, run as its own `__main__` runs it — a refusal
said on stderr with exit 2, never a traceback — so the venv's `bin` (and a node's `/usr/local/bin`) holds it."""

from __future__ import annotations

import sys

from sessionorc import agent_cadence


def main() -> None:
    try:
        sys.exit(agent_cadence.main(sys.argv[1:]))
    except (agent_cadence.Refusal, OSError) as e:
        print(f"agent-cadence: {e}", file=sys.stderr)
        sys.exit(2)
