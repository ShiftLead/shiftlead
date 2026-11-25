"""The pull requests a built-in seat's job holds, for the home's Sync policy (design §6 *Sync*, §4.9c *Two of the five
are not seats today*, TD-2165).

After the cut-over a sync PR nobody holds is a job of the seat for pull requests nobody holds, and its merge is the
team's flow's; the home's Sync policy leaves alone one that an open `pr-<n>` job record names, so the flow's merge and
the policy's never both act on it. A record waiting on the person is left out: the person cures that one by hand and
the policy may merge it. The host agent calls `call` in a thread through the `shiftlead.home_calls` entry point,
since `sessionorc` never imports `shiftlead`; a record that cannot be read raises, and the caller reads that as no
reading.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from shiftlead.stagerecord import StageStore


def numbers(jobs: Mapping[str, Mapping[str, Any]]) -> frozenset[int]:
    """The numbers of the pull requests the open `pr-<n>` job records name, a record waiting on the person aside."""
    out: set[int] = set()
    for key, r in jobs.items():
        if not isinstance(r, Mapping) or not str(key).startswith("pr-") or r.get("closed_at"):
            continue
        if r.get("waits") == "person":
            continue
        try:
            out.add(int(str(key)[3:]))
        except ValueError:
            continue
    return frozenset(out)


def call(root: str | Path) -> frozenset[int]:
    """The repo at `root`'s job-held pull requests, read from its `shiftlead/state` now. Raises where they cannot be
    read (`StateError`, `ValueError`, `OSError`)."""
    return numbers(StageStore(root).jobs())
