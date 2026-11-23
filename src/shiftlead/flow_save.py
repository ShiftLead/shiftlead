"""Saving a flow of the person's (design §4.9c *The Flows page*, *A switch or a rename re-keys the records*, TD-2054).

A flow here is `~/.shiftlead/flows/<name>/flow.yml`. `save` writes it only when it passes §4.9c's check, refuses to
remove a stage or change its kind while entries are in it, and moves the open records of a renamed stage to the new key
before the file changes, so a save tried again after a failure finds them already moved. A built-in is never written,
and a first-shape flow is never overwritten, since a team may be running it until the cut-over (§4.9e).
"""

from __future__ import annotations

import copy
import json
import shutil
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from sessionorc import briefs, paths
from shiftlead import flow3, flowdefs, repoconfig
from shiftlead import org as orgmod
from shiftlead.stagerecord import StageStore, StateError

_SAVING = threading.Lock()  # a save reads the file, checks it and writes it as one step


class FlowError(ValueError):
    """A save or delete refused, in words the page shows."""


def _path(name: Any) -> Path:
    if not isinstance(name, str) or not briefs.NAME.fullmatch(name):
        raise FlowError("a flow's name is letters, digits, - and _, starting with a letter or digit")
    if name in flow3.BUILTIN or name in flowdefs.BUILTIN:  # the first shape's `td` is a built-in's name too
        raise FlowError(f"{name} is a built-in flow's name: copy it under another name")
    return paths.home() / "flows" / name / flow3.FILE


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def stages_of(text: str | None) -> dict[str, str]:
    """A flow's stages as `{key: kind}`; a text that cannot be read has none."""
    try:
        doc = repoconfig.parse_yaml(text or "")
    except yaml.YAMLError:
        return {}
    rows = doc.get("stages") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return {}
    return {flow3.key_of(s.get("name")): str(s.get("does")) for s in rows if isinstance(s, dict)}


def open_records(roots: Iterable[str | Path], flow: str) -> list[tuple[Path, dict[str, Any]]]:
    """Every open record of this flow in the repos at `roots`."""
    out: list[tuple[Path, dict[str, Any]]] = []
    for root in roots:
        for record in StageStore(root).entries().values():
            if record.get("flow") == flow and not record.get("closed_at"):
                out.append((Path(root), record))
    return out


def _renames(given: Any, was: Mapping[str, str], now: Mapping[str, str]) -> dict[str, str]:
    """The renames the page names, as keys: each from a stage the saved flow had to one it did not."""
    if given is None:
        return {}
    if not isinstance(given, Mapping):
        raise FlowError("renames name each old stage and its new one")
    out = {flow3.key_of(a): flow3.key_of(b) for a, b in given.items() if flow3.key_of(a) != flow3.key_of(b)}
    for old, new in out.items():
        if old not in was or old in now:
            raise FlowError(f"{old} is not a stage this save renames")
        if new not in now or new in was:
            raise FlowError(f"{old} cannot be renamed to {new}")
    if len(set(out.values())) != len(out):
        raise FlowError("two stages cannot be renamed to one")
    return out


def _refusals(
    held: Mapping[str, list[str]], was: Mapping[str, str], now: Mapping[str, str], renames: Mapping[str, str]
) -> list[str]:
    """Why this save may not leave the entries in `held` (`{stage: ids}`) where they are."""
    out: list[str] = []
    for stage, ids in sorted(held.items()):
        if stage not in was:
            continue  # a record already on a key the flow lacks is the tick's to send to the person (§4.9c)
        to = renames.get(stage, stage)
        named = ", ".join(sorted(ids))
        if to not in now:
            out.append(f"{stage} still holds {named}: it cannot be deleted")
        elif now[to] != was[stage]:
            out.append(f"{stage} still holds {named}: its kind cannot change")
    return out


def _moved(key: Any, renames: Mapping[str, str]) -> Any:
    return renames.get(key, key) if isinstance(key, str) else key


def _count_key(count: Any, renames: Mapping[str, str]) -> Any:
    """A limit's count is `<stage>:<outcome>`."""
    if not isinstance(count, str) or ":" not in count:
        return count
    stage, outcome = count.split(":", 1)
    return f"{_moved(stage, renames)}:{outcome}"


def rekey(record: Mapping[str, Any], renames: Mapping[str, str]) -> dict[str, Any]:
    """The record with every stage key `renames` names moved: where it is, its counts, its verdicts, its moves, what a
    stopped move or a merge remembers, and the stages its open answers go to."""
    out = copy.deepcopy(dict(record))
    out["stage"] = _moved(out.get("stage"), renames)
    out["counts"] = {_count_key(k, renames): v for k, v in (out.get("counts") or {}).items()}
    verdicts: dict[str, Any] = {}
    for key, verdict in (out.get("verdicts") or {}).items():
        if isinstance(verdict, dict) and "stage" in verdict:
            verdict["stage"] = _moved(verdict["stage"], renames)
        verdicts[_moved(key, renames)] = verdict
    out["verdicts"] = verdicts
    for move in out.get("history") or []:
        if isinstance(move, dict):
            move["from"], move["to"] = _moved(move.get("from"), renames), _moved(move.get("to"), renames)
    if isinstance(out.get("blocked"), dict):
        out["blocked"]["to"] = _moved(out["blocked"].get("to"), renames)
        out["blocked"]["count"] = _count_key(out["blocked"].get("count"), renames)
    if isinstance(out.get("merging"), dict):
        out["merging"]["stage"] = _moved(out["merging"].get("stage"), renames)
    for holder in (out, out.get("intent")):
        if isinstance(holder, dict) and isinstance(holder.get("answers"), dict):
            holder["answers"] = {k: _moved(v, renames) for k, v in holder["answers"].items()}
    return out


def _write_records(records: Iterable[tuple[Path, dict[str, Any]]], flow: str, renames: Mapping[str, str]) -> int:
    """Each repo's moved records in one commit, read again under its lock. Returns how many moved."""
    moved = 0
    for root in sorted({r for r, _ in records}):
        store = StageStore(root)
        with store.locked():
            changes: dict[str, str | None] = {}
            for tid, record in store.entries().items():
                if record.get("flow") != flow or record.get("closed_at"):
                    continue
                new = rekey(record, renames)
                if new != record:
                    changes[store._entry_path(tid)] = json.dumps(new, indent=1) + "\n"
            if changes:
                store.write(changes, f"shiftlead: flow {flow} renames a stage ({len(changes)} entries)")
                moved += len(changes)
    return moved


def save(
    name: str,
    text: str,
    version: str | None = None,
    renames: Mapping[str, str] | None = None,
    roots: Iterable[str | Path] = (),
) -> dict[str, Any]:
    """Write a flow of the person's. With no `version` it is new and may not exist; with one, the file must still be
    that version. Returns `{name, version, moved}`, `moved` the records a rename re-keyed."""
    path = _path(name)
    if not isinstance(text, str) or not flow3.is_format3(text):
        raise FlowError("the Flows page saves a `format: 3` flow")
    doc = repoconfig.parse_yaml(text)
    if doc.get("name") != name:
        raise FlowError(f"the flow's `name:` must be {name}, its directory")
    was_text = _read(path)
    if version is None and path.parent.exists():
        raise FlowError(f"a flow named {name} already exists")
    if version is not None and (was_text is None or briefs.version_of(was_text) != version):
        raise FlowError(briefs.STALE)
    if was_text is not None and not flow3.is_format3(was_text):
        raise FlowError(f"{name} is a first-shape flow a team may be running: save this under another name")
    got = flow3.check_text(text, place="org", flow_dir=path.parent)
    if got.problems:
        raise FlowError("; ".join(got.problems))
    was, now = stages_of(was_text), stages_of(text)
    moves = _renames(renames, was, now)
    # only a stage that goes, moves or changes kind can strand an entry, so no other save depends on every repo's origin
    records = open_records(roots, name) if any(now.get(k) != v for k, v in was.items()) else []
    held: dict[str, list[str]] = {}
    for _root, record in records:
        held.setdefault(str(record.get("stage")), []).append(str(record.get("id")))
    if refused := _refusals(held, was, now, moves):
        raise FlowError("; ".join(refused))
    moved = _write_records(records, name, moves) if moves else 0
    briefs._write(path, text)
    return {"name": name, "version": briefs.version_of(text), "moved": moved}


def delete(name: str, version: str | None, running: Iterable[str] = ()) -> dict[str, Any]:
    """Remove a flow of the person's that no team runs (§4.5a), its directory whole."""
    path = _path(name)
    was = _read(path)
    if was is None or version is None or briefs.version_of(was) != version:
        raise FlowError(briefs.STALE)
    if teams := sorted(running):
        raise FlowError(f"{name} is run by {', '.join(teams)}")
    shutil.rmtree(path.parent)
    return {"name": name, "deleted": True}


_delete = delete  # `call`'s parameter of the same name is the RPC's


def running(name: str, roots: Iterable[str | Path]) -> list[str]:
    """The teams that list `name`, or whose setting picks it (a pick the team no longer lists still names it): a team's
    start reads every flow it lists. A repo that could not be read may hold such a team, so that refuses rather than
    answering none."""
    roots = list(roots)
    if gone := [str(r) for r in roots if not Path(r).is_dir()]:
        raise FlowError(f"cannot tell which teams run {name}: no checkout at {', '.join(gone)}")
    org, notes = orgmod.with_repos(orgmod.load(), roots)
    unread = [n for n in notes if n not in org.unlanded.values() and not n.startswith("place.")]
    if unread:
        raise FlowError(f"cannot tell which teams run {name}: {'; '.join(unread)}")
    org = orgmod.with_home_settings(org)
    return sorted(t.name for t in org.teams.values() if name in {*t.flows, t.flow})


class _Dumper(yaml.SafeDumper):
    """Writes a destination on one line, as the built-ins do."""


class _Inline(dict):
    pass


_Dumper.add_representer(_Inline, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v.items(), flow_style=True))


def _inline(value: Any) -> Any:
    return _Inline({k: _inline(v) for k, v in value.items()}) if isinstance(value, Mapping) else value


def render(doc: Mapping[str, Any]) -> str:
    """The `flow.yml` Save would write for the page's flow: top keys in the file's order, each destination inline."""
    out: dict[str, Any] = {k: doc[k] for k in flow3.TOP_KEYS if k in doc}
    out.update({k: v for k, v in doc.items() if k not in out})
    for group in ("stages", "audits"):
        if isinstance(out.get(group), list):
            out[group] = [
                {k: _inline(v) for k, v in row.items()} if isinstance(row, Mapping) else row for row in out[group]
            ]
    return yaml.dump(out, Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000)


def checked(name: str, doc: Any, version: str | None = None) -> dict[str, Any]:
    """§4.9c's check of the flow the page holds, with the text Save would write: what **The file** shows, what Save
    sends, and the words each row draws. Writes nothing."""
    if not isinstance(doc, Mapping):
        return {"text": "", "problems": ["the page sent no flow"], "info": []}
    text = render({**doc, "name": name})
    try:
        path = _path(name)
    except FlowError as e:
        return {"text": text, "problems": [str(e)], "info": []}
    got = flow3.check_text(text, place="org", flow_dir=path.parent)
    problems = list(got.problems)
    if version is None and path.parent.exists():
        problems.append(f"a flow named {name} already exists")
    return {"text": text, "problems": problems, "info": list(got.info)}


def _row(name: str, place: str, d: Path, root: Path | None = None) -> dict[str, Any]:
    text = _read(d / flow3.FILE) or ""
    row: dict[str, Any] = {"name": name, "place": place, "text": text, "doc": None, "info": [], "problems": []}
    if root is not None:
        row["repo"] = root.name
    if flow3.is_format3(text):
        got = flow3.check_text(
            text, place={"builtin": "package", "own": "org"}.get(place, place), flow_dir=d, repo_root=root
        )
        row.update(doc=repoconfig.parse_yaml(text), problems=list(got.problems), info=list(got.info))
    if place == "own":
        row["version"] = briefs.version_of(text)
    return row


def listing(roots: Iterable[str | Path]) -> dict[str, Any]:
    """What the Flows page draws (§4.9c): the format-3 built-ins, then the person's flows, then each repo's, with the
    models and briefs its picks offer. A first-shape flow has no `doc` and is shown read-only; a shadowed one is left
    out, since no team can run it."""
    where = [Path(r).expanduser() for r in roots]
    rows = [_row(name, "builtin", flow3.PACKAGE_DIR / name) for name in flow3.BUILTIN]
    org = (paths.home() / "flows").resolve()
    for seen in flowdefs.visible(where):
        if seen["source"] == "package" or seen.get("shadowed"):
            continue
        d = Path(seen["source"])
        own = d.resolve().parent == org
        row = _row(seen["name"], "own" if own else "repo", d, None if own else d.parent.parent.parent)
        if row["doc"] is None:
            row["problems"] = list(seen.get("problems") or [])
        rows.append(row)
    return {
        "flows": rows,
        "models": list(flow3.model_families()),
        "briefs": {kind: flow3.offered(kind) for kind in briefs.KINDS},
        "max_moves": flow3.MAX_MOVES,
    }


def call(
    *,
    name: str,
    text: str,
    version: str | None,
    renames: Mapping[str, str] | None,
    delete: bool,
    roots: Iterable[str | Path],
) -> dict[str, Any]:
    """The `flow_save` RPC's body, in a thread of the host agent: a refusal is `{refused: <why>}`. A registered repo
    that cannot be read refuses what depends on it: a delete, or a save that removes, renames or re-kinds a stage."""
    where = [Path(r).expanduser() for r in roots]
    try:
        with _SAVING:
            if delete:
                return _delete(name, version, running(name, where))
            return save(name, text, version, renames, where)
    except (ValueError, StateError, yaml.YAMLError, OSError) as e:  # FlowError and a bad org file are ValueErrors
        return {"refused": str(e)}
