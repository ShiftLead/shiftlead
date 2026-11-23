"""`ao team show <team>`'s read (design §4.9d *Controls and verbs*, TD-2060): the head, the flow with each stage's
model, login now, number and entries, the audits, the built-in set its repo uses, the logins in order and the running
settings.

The host agent calls `call` in a thread through the `shiftlead.home_calls` entry point and hands it what only it holds:
the settings, the login rows and the head. Reads only. The page draws from this same reply.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from sessionorc import logins, teamstore
from shiftlead import flow3, flow_save, repoconfig
from shiftlead.stagerecord import StageStore, StateError

RUNNING_KEYS = ("schedule", "until", "reserve", "balance", "on_work")
NODE_NOTE = "not checked: a node's logins are not read here"
UNREADABLE = (StateError, ValueError, OSError, yaml.YAMLError)


def _root(repo: str, roots: Iterable[str | Path]) -> Path | None:
    return next((p for p in (Path(r).expanduser() for r in roots) if p.name == repo), None)


def _flow_doc(team: str, name: str, store: StageStore | None, roots: Iterable[str | Path]) -> Any:
    """The team's own copy on the state branch, else the flow of that name the org can see."""
    if store is not None:
        text = store.flow(team)
        if text:
            return repoconfig.parse_yaml(text)
    row = next((r for r in flow_save.listing(roots)["flows"] if r["name"] == name), None)
    return row["doc"] if row else None


def _maps(value: Any) -> list[Mapping[str, Any]]:
    """A flow's `stages:` or `audits:`, each row a mapping; a hand-edited copy may hold anything there."""
    return [x for x in value if isinstance(x, Mapping)] if isinstance(value, list) else []


def _now_on(order: list[str], model: Any, rows: Mapping[str, Mapping[str, Any]], on_node: bool) -> dict[str, Any]:
    if on_node:
        return {"login": None, "state": "not_read", "why": NODE_NOTE}
    return teamstore.pick(order, str(model), rows)


def _entries(records: Iterable[Mapping[str, Any]], flow: str, key: str) -> list[dict[str, Any]]:
    held = [r for r in records if r.get("flow") == flow and not r.get("closed_at") and r.get("stage") == key]
    return [
        {"id": r.get("id"), "holder": r.get("holder"), "waits": r.get("waits"), "since": r.get("entered_at")}
        for r in sorted(held, key=lambda r: str(r.get("id")))
    ]


def _login_row(lk: str, rows: Mapping[str, Mapping[str, Any]], names: set[str], on_node: bool) -> dict[str, Any]:
    tool, name = logins.split(lk)
    if on_node:
        return {"login": lk, "tool": None, "name": name, "state": "not_read"}
    row = rows.get(lk) or {}
    return {
        "login": lk,
        "tool": tool,
        "name": name,
        "label": row.get("label"),
        "state": row.get("state") or "unknown",
        "account": row.get("account"),
        "models": list(row.get("models") or ()),
        "why": teamstore.unusable(row),
        "runs_nothing": bool(names) and not any(teamstore.offers(row, m) for m in names),
    }


def view(
    team: str,
    doc: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    head: Mapping[str, Any],
    here: str,
    flow_doc: Any,
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """The reply, from what was read. A team not switched has no flow or logins to show yet."""
    teams = doc.get("teams")
    entry: Mapping[str, Any] = (teams.get(team) if isinstance(teams, Mapping) else None) or {}
    switched = teamstore.switched(doc, team)
    most = entry.get("most") if switched else None
    out: dict[str, Any] = {
        "team": team,
        "switched": switched,
        "version": teamstore.version(doc, team),
        "label": entry.get("label") if switched else None,
        "repo": entry.get("repo") if switched else None,
        "host": entry.get("host") if switched else None,
        "head": {**head, "most": most},
        "settings": {k: entry[k] for k in RUNNING_KEYS if entry.get(k) is not None},
        "flow": None,
        "audits": [],
        "builtins": None,
        "logins": [],
        "cannot_run": None,
        "note": None if switched else teamstore.BEFORE,
    }
    if not switched:
        return out
    repos = doc.get("repos")
    repo_row = repos.get(entry["repo"]) if isinstance(repos, Mapping) else None
    out["builtins"] = (repo_row.get("builtins") if isinstance(repo_row, Mapping) else None) or "default"
    order = [str(lk) for lk in entry.get("logins") or ()]
    on_node = str(entry.get("host") or here) != here
    name = str(entry.get("flow") or "")
    good = isinstance(flow_doc, Mapping)
    stages = _maps(flow_doc.get("stages")) if good else []
    audits = _maps(flow_doc.get("audits")) if good else []
    models = list(dict.fromkeys(str(x["model"]) for x in (*stages, *audits) if x.get("model")))
    numbers = entry.get("at_once") if isinstance(entry.get("at_once"), Mapping) else {}
    keys = [flow3.key_of(s.get("name")) for s in stages]
    held = list(records)
    out["flow"] = {
        "name": name,
        "read": good,
        "stages": [
            {
                "key": key,
                "name": s.get("name"),
                "does": s.get("does"),
                "only_when": s.get("only-when"),
                "model": s.get("model"),
                "now": _now_on(order, s.get("model"), rows, on_node),
                "at_once": numbers.get(key),
                "entries": _entries(held, name, key),
            }
            for key, s in zip(keys, stages, strict=True)
        ],
        "no_such_stage": {k: n for k, n in numbers.items() if good and k not in keys},
    }
    out["audits"] = [
        {
            "name": a.get("name"),
            "model": a.get("model"),
            "every": a.get("every"),
            "now": _now_on(order, a.get("model"), rows, on_node),
        }
        for a in audits
    ]
    out["logins"] = [_login_row(lk, rows, set(models), on_node) for lk in order]
    if on_node:
        out["note"] = NODE_NOTE
    elif good:
        out["cannot_run"] = teamstore.cannot_run(team, name, models, order, rows)
    return out


def call(
    *,
    team: str,
    doc: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    head: Mapping[str, Any],
    here: str,
    roots: Iterable[str | Path],
    entries: bool = True,
) -> dict[str, Any]:
    """The `team_show` RPC's body, in a thread of the host agent. A state branch that cannot be read costs the entries
    and the team's own copy of its flow, said in `unread`, and never the rest of the read."""
    where = [Path(r).expanduser() for r in roots]
    if not teamstore.switched(doc, team):
        return view(team, doc, rows, head, here, None, ())
    teams = doc["teams"]
    root = _root(str(teams[team]["repo"]), where)
    store = StageStore(root) if root is not None else None
    unread = None if root is not None else f"{teams[team]['repo']} is not a registered checkout here"
    records: list[dict[str, Any]] = []
    name = str(teams[team].get("flow") or "")
    flow_doc = None
    try:
        flow_doc = _flow_doc(team, name, store, where)
        if store is not None and entries:
            records = list(store.entries().values())
    except UNREADABLE as e:
        unread = f"the state branch could not be read: {e}"
        if flow_doc is None:
            try:
                flow_doc = _flow_doc(team, name, None, where)
            except UNREADABLE as again:
                unread = f"{unread}; the flow could not be read: {again}"
    return {**view(team, doc, rows, head, here, flow_doc, records), "unread": unread}
