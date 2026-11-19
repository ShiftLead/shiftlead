"""The person's own texts in their agent-cadence layer repo (design §4.8 *The person's own additions*, ADR
2026-10-25 *Decision* 7–9, TD-1016).

The person's additions live in their layer repo, in a `shiftlead/` directory at its root beside their cadence
rules: `briefs/<role>.md`, `entry.md`, `work.md` and `preferences.md`. ShiftLead keeps no setting of its own for
where that is: it asks agent-cadence's reader, `cadence_layer.py --json` (dev-cadence TD-132), for each layer's
repo root, kind (`own`, or `followed` at a pinned `ref`) and commit, and reads the `shiftlead/` files itself —
one's own from its working tree, a followed one's at its `ref`. The listing runs under the session's repo when
it holds agent-cadence, else under the agent-cadence source checkout among the home's repos; neither, the layer
is not read, and the start says so by name. Read at the home, never on a node.

The brief's part goes to `sessionorc.brief` as the `{person}` slot's `{layers: [...]}`, so a replay reads the
same files again and rule 7 sees an edit (§6 *Keeping a team running*); `sessionorc` imports nothing of this."""

from __future__ import annotations

import json
import os
import subprocess
import time
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sessionorc import brief as brief_mod
from sessionorc import cadence

LISTING = ("run", "cadence_layer.py", "--json")
LIST_TIMEOUT = 330.0  # one resolve of the pinned tree may clone or fetch it (`cadence.TREE_TIMEOUT`)
DIR = "shiftlead"  # the layer repo's directory of the person's shiftlead texts
NO_SOURCE = "no agent-cadence to list the layers"
# §4.8's words, which `ao prefs` and the Session card's *told at start* row print with no layer set
NO_LAYER = (
    "no agent-cadence layer: the package's texts alone — name one in `~/.config/agent-cadence/cadence.toml`'s "
    "`[[layers]]`"
)
MACHINE_FILE = "cadence.toml"
LISTED_FOR = 60.0  # one listing answers every member of one team start (as `cadence.TREE_FOR`)
_listed: dict[str, tuple[float, list[Layer] | ListingError]] = {}  # a failure too: one per team start


class ListingError(Exception):
    """The layers could not be listed: the start's error, by name — never read as no layer."""


class NoSource(ListingError):
    """Neither the session's repo nor the home's repos hold agent-cadence: the layer is not read (§4.8), which a
    start names and goes on from, unlike a listing that failed."""


@dataclass(frozen=True)
class Layer:
    root: Path
    kind: str  # "own" or "followed"
    ref: str | None  # a followed layer's pin; None for one's own
    commit: str | None  # the commit the listing read it at

    @property
    def own(self) -> bool:
        return self.kind == "own"

    def head(self) -> str:
        """The line a session reads above this layer's text (§4.8): *— from your layer ~/cadence-layer @ 3f2a1c9 —*,
        a followed layer's at its `ref`."""
        home = os.path.expanduser("~").rstrip("/")
        where = str(self.root)
        if home and (where == home or where.startswith(home + "/")):
            where = "~" + where[len(home) :]
        at = (self.commit if self.own else self.ref) or ""
        return f"— from your layer {where}{f' @ {at[:7]}' if at else ''} —"


def machine_file() -> Path:
    """agent-cadence's machine file, where a person names their layers (its `cadence_config.machine_path`)."""
    reg = os.environ.get("AGENT_CADENCE_REG_DIR")
    if not reg:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        reg = os.path.join(base, "agent-cadence")
    return Path(reg) / MACHINE_FILE


def named() -> bool:
    """Whether the machine's file may name a layer: False only where it plainly names none (no file, or a file
    that reads with no `layers`), so the listing — the one reader — is not run for nothing at every start.
    A file that does not read is True: the listing then says what is wrong with it."""
    try:
        data = tomllib.loads(machine_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return True
    return bool(data.get("layers"))


def source_of(roots: Iterable[Path | str]) -> Path | None:
    """The agent-cadence source checkout among `roots` (the home's repos on this host), where a read with no
    served repo lists the layers (§4.8); None without one."""
    for root in roots:
        if root and cadence.is_source(root):
            return Path(root)
    return None


def listing(
    repo: Path | str | None,
    source: Path | str | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[Layer]:
    """The person's layers in agent-cadence's order (one's own last): its `--json` listing, under `repo` where it
    holds agent-cadence, else under `source`. `[]` is no layer set, a success; `ListingError` when the listing
    cannot run or exits non-zero, or neither place has agent-cadence (`NO_SOURCE`). A layer the listing could not
    read (its `error`) is left out."""
    if not named():
        return []
    where = repo if repo is not None and cadence.holds(repo) else source
    if where is None:
        raise NoSource(NO_SOURCE)
    key = str(Path(where).expanduser())
    hit = _listed.get(key)
    if hit is not None and time.monotonic() - hit[0] < LISTED_FOR:
        if isinstance(hit[1], ListingError):
            raise hit[1]
        return list(hit[1])
    try:
        out = _listing(where, run)
    except ListingError as e:
        _listed[key] = (time.monotonic(), e)
        raise
    _listed[key] = (time.monotonic(), out)
    return list(out)


def _listing(where: Path | str, run: Callable[..., subprocess.CompletedProcess[str]]) -> list[Layer]:
    argv, env = cadence.command(where, *LISTING)
    try:
        cp = run(argv, env=env, capture_output=True, text=True, timeout=LIST_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ListingError(f"agent-cadence's layer listing did not run: {e}") from None
    if cp.returncode != 0:
        said = (cp.stderr or cp.stdout or "").strip().splitlines()
        raise ListingError(f"agent-cadence's layer listing exited {cp.returncode}{': ' + said[-1] if said else ''}")
    try:
        data = json.loads(cp.stdout)
    except ValueError:
        raise ListingError("agent-cadence's layer listing printed no JSON") from None
    rows = data.get("layers") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ListingError("agent-cadence's layer listing has no list of layers")
    out: list[Layer] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("error") or not isinstance(row.get("root"), str):
            continue
        kind = "followed" if row.get("kind") == "followed" else "own"
        ref = row.get("ref") if kind == "followed" and isinstance(row.get("ref"), str) else None
        if kind == "followed" and ref is None:
            continue  # a followed layer is read at its pin alone, never its working tree
        commit = row.get("commit") if isinstance(row.get("commit"), str) else None
        out.append(Layer(root=Path(os.path.expanduser(row["root"])), kind=kind, ref=ref, commit=commit))
    return out


def path_of(layer: Layer, rel: str) -> Path:
    return layer.root / DIR / rel


def read(layer: Layer, rel: str) -> tuple[str, str] | None:
    """`(text, sha)` of the layer's `shiftlead/<rel>`, its own from the working tree, a followed one's at its
    `ref`; None when it has none."""
    try:
        return brief_mod.read_layer(str(path_of(layer, rel)), layer.ref, str(layer.root))
    except brief_mod.Unreadable:
        return None


def parts(layers: Iterable[Layer], rel: str) -> list[dict[str, Any]]:
    """The `{layers: …}` slot's parts for `shiftlead/<rel>` (`sessionorc.brief.layered`): each layer that has
    the file, in order, with its path, its `ref` and the head line naming it."""
    return [
        {"path": str(path_of(layer, rel)), "ref": layer.ref, "root": str(layer.root), "head": layer.head()}
        for layer in layers
        if read(layer, rel) is not None
    ]


def brief_parts(role: str, layers: Iterable[Layer]) -> list[dict[str, Any]]:
    """A role's brief additions: each layer's `shiftlead/briefs/<role>.md` (§4.8)."""
    return parts(layers, f"briefs/{role}.md") if role else []


def person(role: str, repo: Path | str | None, roots: Iterable[Path | str] = ()) -> list[dict[str, Any]]:
    """The `{person}` parts a start of `role` in `repo` hands its brief (§4.8): listed under `repo` where it holds
    agent-cadence, else under the agent-cadence source among `roots`; neither, `NoSource`, which the start names
    (`NO_SOURCE`) and goes on from with none. A listing that fails is `ListingError`, the start's error."""
    here = Path(repo).expanduser() if repo is not None else None
    return brief_parts(role, listing(here if here is not None and here.is_dir() else None, source_of(roots)))


def roots_of(org: Any, here: str) -> list[Path]:
    """The home's checkouts of the org's repos on host `here`: where `source_of` looks for agent-cadence."""
    return [Path(c).expanduser() for r in org.checkouts if (c := org.checkout(r, here)) is not None]


def addition(rel: str, repo: Path | str | None, roots: Iterable[Path | str] = ()) -> str:
    """The person's addition to the package's `rel` (`entry.md`, `work.md`; §4.8 *The person's own additions*):
    each layer's `shiftlead/<rel>` in the listing's order, each under the line naming its source, joined; `""`
    when no layer has one or none is set. With no agent-cadence to list them, the text names that (`NO_SOURCE`) in
    their place, so the session and the *told at start* row say it, and the start goes on. A listing that fails
    is `ListingError`, the start's error by name."""
    here = Path(repo).expanduser() if repo is not None else None
    try:
        found = listing(here if here is not None and here.is_dir() else None, source_of(roots))
    except NoSource:
        return f"— {NO_SOURCE}: your own additions are not read —"
    got = parts(found, rel)
    if not got:
        return ""
    text, _sources = brief_mod.layered(got)
    return "" if text == "none" else text
