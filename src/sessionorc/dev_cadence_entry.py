"""The `dev-cadence` console script (design §4.4a, §5 *How the readers find dev-cadence*, TD-1014): the
vendored launcher, `sessionorc/dev_cadence.py`, kept frozen, run as its own `__main__` runs it — a refusal
said on stderr with exit 2, never a traceback — so the venv's `bin` (and a node's `/usr/local/bin`) holds it."""

from __future__ import annotations

import sys

from sessionorc import dev_cadence


def main() -> None:
    try:
        sys.exit(dev_cadence.main(sys.argv[1:]))
    except (dev_cadence.Refusal, OSError) as e:
        print(f"dev-cadence: {e}", file=sys.stderr)
        sys.exit(2)
