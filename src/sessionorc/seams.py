"""A repo's seams as the host agent keeps them (design §4.4 *Repo facts*, *The seams*; §5 *The seams*;
TD-584, built by TD-591; TD-1011): whether its ledger at `ledger:` parses through `ledgerboard.py` and
its `Ledgerboard:` major; for each of `board:` and `worktree_setup:` whether it is *set*, *defaulted*
(the dev-cadence file the checkout holds) or *absent*; whether the repo is **served** — it holds
dev-cadence's tree, the gate and the ledger, or `serve` names each lack in §5's words with its cure —
and the warnings, one sentence each. The Repo page's missing-seam lines (§4.5a) and `ao doctor`'s
**repos** check (§4.7) draw this reading and read nothing themselves; the SessionStart commands are
carried as text, for the clients to compare with the adapter's own line. It also carries the release
the repo's vendored `ledgerboard.py` names in its header beside the wheel's (§5 *ledgerboard by its
header*, TD-1013)."""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Any

from sessionorc import cadence, gitinfo, sync, workorders
from sessionorc import ledger as ledger_mod
from sessionorc import ledgerboard as lb

# a vendored copy's first line: the tagged release it came from and the hash of every byte after it
RELEASE_HEADER = re.compile(r"^# ledgerboard v(\S+) sha256:([0-9a-f]{64})$")
# where a repo keeps its copy: a consumer's, then dev-cadence's own source
LEDGERBOARD_COPIES = ("scripts/ledgerboard.py", "files/scripts/ledgerboard.py")


def ledgerboard_release(text: str) -> str | None:
    """The release a `ledgerboard.py`'s first line names (*1.3* of `# ledgerboard v1.3 sha256:…`), or None
    when that line is not a release header."""
    m = RELEASE_HEADER.match(text.split("\n", 1)[0].rstrip("\r"))
    return m.group(1) if m else None


def _file_release(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8") as f:
            return ledgerboard_release(f.readline())
    except (OSError, UnicodeDecodeError):
        return None


@functools.cache
def wheel_release() -> str | None:
    """The release of the `ledgerboard.py` this build carries (`sessionorc/ledgerboard.py`), read once."""
    return _file_release(Path(lb.__file__))


def ledgerboard(root: Path | str) -> dict[str, Any]:
    """`{release, wheel}`: the release the repo's copy names (the first of `LEDGERBOARD_COPIES` there;
    None for a copy with no release header, or a repo with neither file) and the wheel's."""
    copy = next((Path(root) / rel for rel in LEDGERBOARD_COPIES if (Path(root) / rel).is_file()), None)
    return {"release": _file_release(copy) if copy is not None else None, "wheel": wheel_release()}


def ledger(root: Path | str) -> dict[str, Any]:
    """The ledger seam: `{path, state, major, entries, why}` — `state` *ok* (it parses and its major is
    one `ledgerboard.py` knows; `entries` its count), *absent* (no file at `ledger:`), *unreadable*
    (the file could not be read as text, or `ledger:` names a path outside the repo) or *newer* (its
    `Ledgerboard:` major is past the module's), `why` the reader's reason when not *ok*."""
    rel = ledger_mod.ledger_path(root)
    out: dict[str, Any] = {"path": rel, "state": "ok", "major": None, "entries": None, "why": None}
    if not workorders.inside(Path(rel)):
        return {**out, "state": "unreadable", "why": f"ledger: {rel} is not a path inside the repo"}
    path = Path(root) / rel
    if not path.is_file():
        return {**out, "state": "absent", "why": f"no ledger at {rel}"}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {**out, "state": "unreadable", "why": f"{rel}: {getattr(e, 'strerror', None) or e}"}
    out["major"] = lb.format_major(text)
    why = lb.version_problem(text)
    if why is not None:
        return {**out, "state": "newer", "why": why}
    try:
        out["entries"] = len(lb.entries(text))
    except Exception as e:  # noqa: BLE001 — a ledger the module cannot parse is named, never a failed reading
        return {**out, "state": "unreadable", "why": f"{rel} does not parse: {e}"}
    return out


# dev-cadence's shim in a checkout's common hooks (dev-cadence TD-055): its per-clone setup was run
SHIM_MARKER = "dev-cadence hook shim (TD-055)"


def cure(root: Path | str) -> str:
    """The cure of a lack dev-cadence's adoption supplies (§5 *The seams*), until `ao repo add` (TD-1010)."""
    return f"`<dev-cadence>/sync.sh {root}`, then a PR"


def ledger_lack(led: dict[str, Any] | None, root: Path | str) -> str | None:
    """The ledger seam's lack in §5's words, or None when it parses: *unserved: no ledger at <path> —
    <cure>*, *ledger is Ledgerboard 2, this build reads 1 (sync)*, or *unserved: the ledger at <path>
    does not parse — <the reader's reason>*, which no adoption cures."""
    led = led or {}
    state, path = led.get("state"), led.get("path") or "the ledger path"
    if state in (None, "ok"):
        return None
    if state == "absent":
        return f"unserved: no ledger at {path} — {cure(root)}"
    if state == "newer":
        return f"ledger is Ledgerboard {led.get('major')}, this build reads {lb.FORMAT_MAJOR} (sync)"
    return f"unserved: the ledger at {path} does not parse — {led.get('why') or state}"


def _lock_lack(root: Path) -> str | None:
    """The tree's lack (§5 *The seams*): no lock, or one that does not parse; None for dev-cadence's
    own source, which carries none."""
    if cadence.is_source(root):
        return None
    path = root / sync.LOCK
    if not path.is_file():
        return f"unserved: no dev-cadence (no {sync.LOCK}) — {cure(root)}"
    try:
        lock = sync.parse_lock(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        return f"unserved: dev-cadence's lock does not parse — {getattr(e, 'strerror', None) or e} — {cure(root)}"
    if not (lock or {}).get("files_commit"):
        return f"unserved: dev-cadence's lock does not parse — it has no files_commit line — {cure(root)}"
    return None


def serve(root: Path | str, led: dict[str, Any]) -> dict[str, Any]:
    """`{ok, lacks: [{key, words}]}`: `cadence` (dev-cadence's tree), `gate` (its script) and `ledger`,
    each lack in §5's fixed words with its cure; `ok` when there is none."""
    root = Path(root)
    lacks: list[dict[str, str]] = []
    if words := _lock_lack(root):
        lacks.append({"key": "cadence", "words": words})
    if cadence.gate(root) is None:
        script = cadence.SOURCE_SCRIPT if cadence.is_source(root) else cadence.SCRIPT
        lacks.append({"key": "gate", "words": f"unserved: no gate (no {script}) — {cure(root)}"})
    if words := ledger_lack(led, root):
        lacks.append({"key": "ledger", "words": words})
    return {"ok": not lacks, "lacks": lacks}


def shimmed(root: Path | str) -> bool | None:
    """Whether the checkout's common `.git/hooks/pre-push` carries dev-cadence's shim marker; None
    where the checkout has no `.git` directory to read (a worktree, or no checkout here)."""
    hooks = Path(root) / ".git" / "hooks"
    if not hooks.parent.is_dir():
        return None
    try:
        return SHIM_MARKER in (hooks / "pre-push").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def session_start(root: Path | str) -> list[str]:
    """The SessionStart hook commands of the checkout's `.claude/settings.json`, as text; none for a
    file that is missing or not that shape."""
    try:
        doc = json.loads((Path(root) / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    groups = ((doc.get("hooks") if isinstance(doc, dict) else None) or {}).get("SessionStart")
    out: list[str] = []
    for g in groups if isinstance(groups, list) else []:
        for h in (g.get("hooks") if isinstance(g, dict) else None) or []:
            if isinstance(h, dict) and isinstance(h.get("command"), str):
                out.append(h["command"])
    return out


def warnings(root: Path | str, board: dict[str, Any], setup: dict[str, Any]) -> list[str]:
    """The warnings the host agent can read itself (§5 *The seams*), each one sentence: a missing board,
    no worktree setup, and a checkout without dev-cadence's hook shim. A repo is served whatever they say."""
    out: list[str] = []
    if board.get("state") == "absent" or (board.get("value") and not (Path(root) / board["value"]).is_file()):
        out.append(f"no board at {board.get('value') or workorders.BOARD}")
    if setup.get("state") == "absent":
        out.append("no worktree setup")
    if shimmed(root) is False:
        out.append(f"dev-cadence's per-clone setup not run in this checkout — `<dev-cadence>/sync.sh {root}`")
    return out


def reading(root: Path | str) -> dict[str, Any]:
    """The repo's seams: `{ledger, board, worktree_setup, serve, warnings, session_start, ledgerboard,
    source}` — `ledger` as `ledger()` gives it, `board` and `worktree_setup` each `{state, value}`,
    `value` the board's path or the command (None when *absent*), `serve` as `serve()` gives it,
    `ledgerboard` as `ledgerboard()` does, `source` whether the root is dev-cadence's own source (its
    every dev-cadence path under `files/`)."""
    board_state, board_rel = workorders.board_path(root)
    state, value = gitinfo.worktree_setup(root)
    out: dict[str, Any] = {
        "ledger": ledger(root),
        "board": {"state": board_state, "value": board_rel.as_posix() if board_rel is not None else None},
        "worktree_setup": {"state": state, "value": value},
    }
    out["serve"] = serve(root, out["ledger"])
    out["warnings"] = warnings(root, out["board"], out["worktree_setup"])
    out["session_start"] = session_start(root)
    out["ledgerboard"] = ledgerboard(root)
    out["source"] = cadence.is_source(root)
    return out
