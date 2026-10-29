"""Design §6 *Keeping a team running*, rule 12 (TD-247, TD-258): conventions relayed by the tick.
agent-cadence's SessionStart hook prints the new entries of `docs/cadence-changes.md` to a session
that starts, so only a member that outlives a change needs telling: the home runs
`scripts/cadence_changes.py --json` in each registry root that carries it, keeps on each member's
record the headings it has seen, and sends one `note` from `system` for those that landed after
the record was created. Nothing here is typed by a session, and the words are the script's `date`
and `title` fields — in a pinned repo, each entry's `body` as well.

A pinned repo (§5 *How the readers find agent-cadence*, TD-1014) carries no copy: the script is the pinned
tree's, run through the resolver, `cadence.command`, and the changes are agent-cadence's own (TD-1025), so
its note carries each entry's body and names the file by the resolver's command (TD-1046). agent-cadence's
source runs its own, under `files/`.

The reads (`has_script`, which may resolve a pinned tree, and `read`) shell out and are called in a thread;
the rest is pure."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import cadence

SCRIPT = "scripts/cadence_changes.py"
PINNED_SCRIPT = "cadence_changes.py"  # as the pinned tree's `files/scripts/` holds it
SOURCE_SCRIPT = f"files/{SCRIPT}"  # in agent-cadence's own source (`cadence.is_source`)
NAMED = 3  # the entries one note names; the rest are *and n more*
BODY = 300  # a pinned note's body, at most, before its `…`
TIMEOUT = 180.0  # an unpinned root's run; a pinned one's is `cadence.TREE_TIMEOUT`


def has_script(root: Path | str) -> bool:
    """Whether `root` is a checkout the home can see that carries the script — in the pinned tree, for a
    pinned repo, and under `files/` in agent-cadence's source."""
    if cadence.pinned(root):
        payload, _ = cadence.tree(root)
        return payload is not None and (payload / "scripts" / PINNED_SCRIPT).is_file()
    return (Path(root) / (SOURCE_SCRIPT if cadence.is_source(root) else SCRIPT)).is_file()


def read(root: Path | str, timeout: float | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """One run of the script in `root`: `(reading, None)`, the reading `{ref, entries}`, or `(None, why)`
    for **no reading** — no script, an origin with no default branch (exit 2, whose last stderr line says
    so), a run that could not be made or did not end, or output that is not the script's. Unpinned, the
    script asks git once per entry for its `landed`, hence the long bound; in a pinned repo its walk reads
    each pin once, and the run may fetch or clone agent-cadence's source under the launcher's 300 s, so it is
    bounded at `cadence.TREE_TIMEOUT` — `has_script`'s resolve is bounded on its own."""
    if not has_script(root):
        return None, "no script"
    if pinned := cadence.pinned(root):  # the pinned tree's script, through the resolver (TD-1014)
        argv, env = cadence.command(root, "run", PINNED_SCRIPT, "--json")
    else:
        argv, env = ["python3", SOURCE_SCRIPT if cadence.is_source(root) else SCRIPT, "--json"], None
    if timeout is None:
        timeout = cadence.TREE_TIMEOUT if pinned else TIMEOUT
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=str(root), env=env)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout:.0f}s"
    except OSError as e:
        return None, str(e)
    if cp.returncode != 0:
        last = (cp.stderr or "").strip().splitlines()
        return None, last[-1].strip() if last else f"exit {cp.returncode}, no output"
    got = parse(cp.stdout)
    return (got, None) if got is not None else (None, "output is not the script's --json")


def parse(text: str) -> dict[str, Any] | None:
    """`{ref, entries: [{heading, date, title, body, landed}]}` from the script's `--json`, or None when
    it is not that. An entry with no heading is dropped; `landed` is kept as the script gave it,
    None included, and a `body` that is not a string is `""`."""
    try:
        out = json.loads(text or "")
    except json.JSONDecodeError:
        return None
    if not isinstance(out, dict) or not isinstance(out.get("entries"), list):
        return None
    entries = [
        {
            "heading": e["heading"],
            "date": e.get("date"),
            "title": e.get("title"),
            "body": e["body"] if isinstance(e.get("body"), str) else "",
            "landed": e.get("landed"),
        }
        for e in out["entries"]
        if isinstance(e, dict) and isinstance(e.get("heading"), str) and e["heading"]
    ]
    return {"ref": str(out.get("ref") or "origin/main"), "entries": entries}


def _when(iso: Any) -> datetime | None:
    """An instant from the script's `landed` or a record's `created`; a naive one is read as UTC."""
    if not isinstance(iso, str) or not iso:
        return None
    try:
        at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def sort(
    entries: list[dict[str, Any]], seen: list[str] | None, created: str
) -> tuple[list[str], list[dict[str, Any]]] | None:
    """What one reading makes of one record: `(seen, told)` — the headings `conventions_seen` now
    holds, and the entries to tell, in the script's order. With no `seen` yet (the first reading
    after the create) the headings landed at or before `created` are written and nothing is told
    of them; an entry landed after `created` that `seen` does not hold is told and joins it; one
    whose `landed` the script could not read is left for the next reading. None when `created`
    cannot be read: nothing is written."""
    born = _when(created)
    if born is None:
        return None
    held = list(seen or [])
    told: list[dict[str, Any]] = []
    for e in entries:
        landed = _when(e.get("landed"))
        if e["heading"] in held or landed is None:
            continue
        held.append(e["heading"])
        if landed > born:
            told.append(e)
    return held, told


def _name(e: dict[str, Any]) -> str:
    date, title = e.get("date"), e.get("title")
    if date and title:
        return f'"{date} — {title}"'
    return f'"{str(e["heading"]).lstrip("# ").strip()}"'


def _body(e: dict[str, Any]) -> str:
    """An entry's body as a pinned note carries it: its lines joined by a space, cut at `BODY` with `…`."""
    text = " ".join(line.strip() for line in str(e.get("body") or "").splitlines() if line.strip())
    return text[:BODY] + "…" if len(text) > BODY else text


def note(told: list[dict[str, Any]], ref: str, path: str | None = None) -> str:
    """The `system` note's fixed words, three entries named at most. With `path`, the resolver's command
    that prints the file (a pinned repo, which holds no copy): agent-cadence's file, each named entry with its
    body, since a worktree branched before the bump resolves the old pin."""
    count = f"{len(told)} entr{'y' if len(told) == 1 else 'ies'}"
    more = f" and {len(told) - NAMED} more" if len(told) > NAMED else ""
    if path is not None:
        named = ", ".join(_name(e) + (f": {b}" if (b := _body(e)) else "") for e in told[:NAMED])
        return (
            f"agent-cadence's cadence-changes.md gained {count} since you started: {named}{more} — "
            f"after rebasing onto `{ref}`, `{path}` prints its path; go on"
        )
    named = ", ".join(_name(e) for e in told[:NAMED])
    it = "it" if len(told) == 1 else "them"
    return f"docs/cadence-changes.md gained {count} since you started: {named}{more} — read {it} on `{ref}`, then go on"
