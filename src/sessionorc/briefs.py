"""The person's own briefs: Markdown files beside the org's flows (design §4.9c *Where a brief lives*, TD-2055).

A brief here is `~/.shiftlead/briefs/<name>.md`, its kind in a `---` front matter. This module reads them, and writes
them for `brief_save` alone (the Briefs page's, a person's own act). The standard briefs are the package's and are
never written; only their names and kinds are here, since a person's brief may not take one.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from sessionorc import paths

KINDS = ("design", "build", "review", "audit")
# the standard briefs (§4.9c *What a stage's session is told*), each with its kind
STANDARD = {
    "design": "design",
    "build": "build",
    "review": "review",
    "docs": "audit",
    "tests": "audit",
    "code": "audit",
}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
KIND_LINE = re.compile(r"kind:\s*([a-z]+)")
FLOW_FILE = "flow.yml"
STALE = "changed since this page read it — reload"


class BriefError(ValueError):
    """A save or delete refused, in words the page shows."""


def org_dir() -> Path:
    """The org's own briefs, beside its flows (§4.9c *Where a brief lives*)."""
    return paths.home() / "briefs"


def kind_of(text: str) -> str | None:
    """A person's brief's kind: the `kind:` line of its front matter, or None."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        if m := KIND_LINE.fullmatch(line.strip()):
            return m.group(1)
    return None


def body_of(text: str) -> str:
    """A brief's text without its front matter."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return "".join(lines[i + 1 :]).lstrip("\n")
    return text


def version_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _path(name: str) -> Path:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise BriefError("a brief's name is letters, digits, - and _, starting with a letter or digit")
    return org_dir() / f"{name}.md"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def own() -> list[dict[str, Any]]:
    """Every brief of the person's own, by name. One with no readable kind is listed with `kind` None and is offered
    to no stage."""
    try:
        files = sorted(org_dir().glob("*.md"), key=lambda p: p.stem.casefold())
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for path in files:
        text = _read(path)
        if text is not None and NAME.fullmatch(path.stem):
            out.append({"name": path.stem, "kind": kind_of(text), "text": body_of(text), "version": version_of(text)})
    return out


def flows_naming(name: str) -> list[str]:
    """The org's flows whose stage or audit takes this brief from the org. A flow with its own `briefs/<name>.md` reads
    that one; a flow that cannot be read is named too, since nothing shows it does not use the brief."""
    root = paths.home() / "flows"
    try:
        dirs = sorted(d for d in root.iterdir() if (d / FLOW_FILE).is_file())
    except OSError:
        return []
    out: list[str] = []
    for d in dirs:
        if (d / "briefs" / f"{name}.md").is_file():
            continue
        try:
            doc = yaml.safe_load((d / FLOW_FILE).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            out.append(f"{d.name} (unreadable)")
            continue
        if not isinstance(doc, dict) or doc.get("format") != 3:
            continue  # the first shape names a brief by its file, never the org's
        steps = [*(doc.get("stages") or []), *(doc.get("audits") or [])] if _lists(doc) else []
        if any(isinstance(s, dict) and s.get("brief") == name for s in steps):
            out.append(d.name)
    return out


def _lists(doc: dict[str, Any]) -> bool:
    return all(isinstance(doc.get(k) or [], list) for k in ("stages", "audits"))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save(name: str, kind: str, text: str, version: str | None = None) -> dict[str, Any]:
    """Write a brief. With no `version` it is new and may not exist; with one, the file must still be that version. A
    brief a flow names keeps its kind, since the flow's stage is of that kind (§4.9c rule 10)."""
    path = _path(name)
    if name in STANDARD:
        raise BriefError(f"{name} is a standard brief's name: pick another")
    if kind not in KINDS:
        raise BriefError(f"a brief's kind is one of {', '.join(KINDS)}")
    if not isinstance(text, str) or not text.strip():
        raise BriefError("a brief needs some text")
    was = _read(path)
    if version is None and path.exists():
        raise BriefError(f"a brief named {name} already exists")
    if version is not None and (was is None or version_of(was) != version):
        raise BriefError(STALE)
    if was is not None and kind_of(was) != kind and (using := flows_naming(name)):
        raise BriefError(f"{name} keeps its kind while a flow names it: {', '.join(using)}")
    full = f"---\nkind: {kind}\n---\n\n{text.strip()}\n"
    _write(path, full)
    return {"name": name, "kind": kind, "text": body_of(full), "version": version_of(full)}


def delete(name: str, version: str | None) -> dict[str, Any]:
    """Remove a brief no flow names (§4.5a *Briefs page*); refused naming the flows that do."""
    path = _path(name)
    was = _read(path)
    if was is None or version is None or version_of(was) != version:
        raise BriefError(STALE)
    if using := flows_naming(name):
        raise BriefError(f"{name} is named by a flow: {', '.join(using)}")
    path.unlink()
    return {"name": name, "deleted": True}
