"""`ao team show <team>`'s read (design §4.9d *Controls and verbs*, TD-2060): the head, the flow with each stage's
model, login now, number and entries, the audits, the built-in set its repo uses, the logins in order and the running
settings.

The host agent calls `call` in a thread through the `shiftlead.home_calls` entry point and hands it what only it holds:
the settings, the login rows and the head. Reads only. The page draws from this same reply.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from sessionorc import builtinstore, gitinfo, logins, teamstore
from shiftlead import flow3, flow_save, flowdefs, repoconfig, stage_audit, stage_audit_pass
from shiftlead import org as orgmod
from shiftlead.stage_acts import switch_case
from shiftlead.stage_read import flow_on
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


def _entry(r: Mapping[str, Any]) -> dict[str, Any]:
    asked = r.get("asked")
    return {
        "id": r.get("id"),
        "stage": r.get("stage"),
        "holder": r.get("holder"),
        "waits": r.get("waits"),
        "since": r.get("entered_at"),
        "asked_at": asked.get("at") if isinstance(asked, Mapping) else None,
    }


def _open(records: Iterable[Mapping[str, Any]], team: str) -> list[Mapping[str, Any]]:
    held = [r for r in records if r.get("team") == team and not r.get("closed_at")]
    return sorted(held, key=lambda r: str(r.get("id")))


def _entries(records: Iterable[Mapping[str, Any]], team: str, key: str) -> list[dict[str, Any]]:
    return [_entry(r) for r in _open(records, team) if r.get("stage") == key]


def _login_row(
    lk: str, rows: Mapping[str, Mapping[str, Any]], names: set[str], on_node: bool, why: str | None
) -> dict[str, Any]:
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
        "why": why,
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
    *,
    director: bool = False,
    rounds: Mapping[str, str] | None = None,
    node_mark: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The reply, from what was read. A team not switched has no flow or logins to show yet. `rounds` is when each
    audit, by key, next comes round (`audit_rounds`); one not read is drawn with none. A team on a node is *cannot
    run* where `node_mark` stands (`node_cannot_run`)."""
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
        "builtins_cannot_run": [],
        "logins": [],
        "cannot_run": None,
        "note": None if switched else teamstore.BEFORE,
    }
    if not switched:
        return out
    out["builtins"] = builtinstore.repo_set(doc, str(entry["repo"]))
    order = [str(lk) for lk in entry.get("logins") or ()]
    on_node = str(entry.get("host") or here) != here
    if not on_node:  # a team on a node says *not checked* instead (§4.9d *The login a seat starts on*)
        held_set = builtinstore.sets(doc)[out["builtins"]]
        out["builtins_cannot_run"] = builtinstore.cannot_run(out["builtins"], held_set, rows, director=director)
    name = str(entry.get("flow") or "")
    good = isinstance(flow_doc, Mapping)
    stages = _maps(flow_doc.get("stages")) if good else []
    audits = _maps(flow_doc.get("audits")) if good else []
    models = list(dict.fromkeys(str(x["model"]) for x in (*stages, *audits) if x.get("model")))
    numbers = entry.get("at_once") if isinstance(entry.get("at_once"), Mapping) else {}
    keys = [flow3.key_of(s.get("name")) for s in stages]
    held = list(records)
    off_flow = [_entry(r) for r in _open(held, team) if r.get("stage") not in keys]  # all of them, a flow not read
    out["flow"] = {
        "name": name,
        "read": good,
        "lines": flow3.route_lines(stages),
        "gone": [e for e in off_flow if good and e["waits"] == "person"],  # *waiting on you, its stage is gone*
        "unplaced": [e for e in off_flow if not good or e["waits"] != "person"],
        "stages": [
            {
                "key": key,
                "name": s.get("name"),
                "does": s.get("does"),
                "only_when": s.get("only-when"),
                "model": s.get("model"),
                "now": _now_on(order, s.get("model"), rows, on_node),
                "at_once": numbers.get(key),
                "entries": _entries(held, team, key),
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
            "next": (rounds or {}).get(flow3.key_of(a.get("name"))) or None,
            "now": _now_on(order, a.get("model"), rows, on_node),
        }
        for a in audits
    ]
    whys = teamstore.reasons(order, rows)
    out["logins"] = [_login_row(lk, rows, set(models), on_node, whys[lk]) for lk in order]
    if on_node:
        out["note"] = NODE_NOTE
        host = str(entry.get("host") or "")
        out["cannot_run"] = node_cannot_run(team, name, order, node_mark, host, models if good else None)
    elif good:
        out["cannot_run"] = teamstore.cannot_run(team, name, models, order, rows)
    return out


def node_cannot_run(
    team: str,
    flow: str,
    order: list[str],
    mark: Mapping[str, Any] | None,
    host: str,
    models: list[str] | None = None,
) -> str | None:
    """A team on a node *cannot run* while the home's mark stands (§4.9d *A team on a node*, §4.9e, TD-2068): the node
    reported that no login of the list offers a model, and the mark holds until the team's list or its flow changes,
    so a mark written for another list or flow is read as none — and so is one whose model no stage or audit of the
    flow asks for any longer (`models`, the flow's as read; None, a flow not read, leaves the mark standing)."""
    if not isinstance(mark, Mapping) or not mark.get("model"):
        return None
    if str(mark.get("flow") or "") != flow or [str(x) for x in mark.get("logins") or ()] != order:
        return None
    if models is not None and str(mark["model"]) not in models:
        return None
    return f"{team} cannot run {flow}: no login in its list offers {mark['model']} on {host}"


def _has_director() -> bool:
    """Whether the org has a director, whose seat answers the prompts a prompts seat otherwise would (§4.9d). An
    `org.yml` that cannot be read names none, so the prompts row stays a pick."""
    try:
        return orgmod.load().director is not None
    except (ValueError, OSError, yaml.YAMLError):
        return False


def builtins_view(
    *,
    name: str,
    doc: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    roots: Iterable[str | Path],
    director: bool | None = None,
) -> dict[str, Any]:
    """`ao builtins show [<set>]` and the Built-in seats page's read (§4.9d *The page*), of the home's logins alone."""
    has_director = _has_director() if director is None else director
    every = builtinstore.sets(doc)
    if name not in every:
        raise ValueError(f"no built-in set {name!r}")
    repos = [Path(r).expanduser().name for r in roots]
    entry = every[name]
    order = list(entry["logins"])
    whys = teamstore.reasons(order, rows)
    models = {builtinstore.model(entry, s[0]) for s in builtinstore.SEATS}
    cut = teamstore.cut_over(doc)
    cannot = builtinstore.cannot_run(name, entry, rows, director=has_director)
    seats = []
    for key, shown, words, does, acts_for in builtinstore.SEATS:
        by_director = has_director and key == builtinstore.PROMPTS
        model = builtinstore.model(entry, key)
        seats.append(
            {
                "key": key,
                "name": shown,
                "does": does,
                "for": acts_for,
                "model": None if by_director else model,
                "director": by_director,
                "now": None if by_director else teamstore.pick(order, model, rows, unasked=key == builtinstore.PROMPTS),
                "cannot_run": next((c for c in cannot if c.startswith(f"{name} cannot run {words}:")), None),
            }
        )
    return {
        "set": name,
        "label": entry["label"],
        "cut_over": cut,
        "note": None if cut else teamstore.BEFORE,
        "version": builtinstore.version(doc),
        "sets": [
            {
                "name": n,
                "label": e["label"],
                "cannot_run": builtinstore.cannot_run(n, e, rows, director=has_director),
            }
            for n, e in every.items()
        ],
        "used_by": builtinstore.using(doc, name, repos),
        "named_by": builtinstore.named_by(doc, name),
        "stored_models": dict(entry["models"]),  # what a model pick sends back, a seat with no pick kept
        "seats": seats,
        "logins": [_login_row(lk, rows, models, False, whys[lk]) if lk in rows else _unread_login(lk) for lk in order],
        "order": order,
        "repos": [{"repo": r, "set": builtinstore.repo_set(doc, r)} for r in repos],
        "cannot_run": cannot,
    }


def _unread_login(lk: str) -> dict[str, Any]:
    """A login the home does not hold, a node's typed by name: drawn *not read here* (§4.9d *The page*)."""
    tool, name = logins.split(lk)
    return {"login": lk, "tool": tool, "name": name, "state": "not_read"}


def new_refusal(repo: str, flow: str, roots: Iterable[str | Path]) -> str | None:
    """Why **+ New team** cannot take this repo and flow (§4.9d *New team*, TD-2063), or None."""
    where = [Path(r).expanduser() for r in roots]
    if _root(repo, where) is None:
        return f"{repo} is not a registered checkout here"
    if flow not in {str(r["name"]) for r in flow_save.listing(where)["flows"]}:
        return f"there is no flow named {flow}"
    return None


def open_records(team: str, repo: str, roots: Iterable[str | Path]) -> list[str]:
    """The team's open stage records in **Delete**'s words (§4.9d *Delete*, TD-2063): *TD-2101 is in build*, *TD-2084
    waits on you*. A state branch that cannot be read raises: a record not read is never read as no record."""
    root = _root(repo, [Path(r).expanduser() for r in roots])
    if root is None:
        raise StateError(f"{repo} is not a registered checkout here")
    held = [r for r in StageStore(root).entries().values() if r.get("team") == team and not r.get("closed_at")]
    return [
        f"{r.get('id')} waits on you" if r.get("waits") == "person" else f"{r.get('id')} is in {r.get('stage')}"
        for r in sorted(held, key=lambda r: str(r.get("id")))
    ]


def drop_copy(team: str, repo: str, roots: Iterable[str | Path]) -> None:
    """The team's copy of its flow removed from the state branch, at its Delete."""
    root = _root(repo, [Path(r).expanduser() for r in roots])
    if root is None:
        raise StateError(f"{repo} is not a registered checkout here")
    StageStore(root).drop_flow(team)


def audit_rounds(
    team: str, flow_doc: Any, store: StageStore | None, root: Path | None, now: datetime | None = None
) -> dict[str, str]:
    """When each of the flow's audits next comes round (`stage_audit.next_round`), by key, from its run record on the
    state branch and, on a `merged-pull-requests` clock, the merges since its base on the default branch. An audit
    whose record cannot be read is left out, so the page draws it with no next clock."""
    if store is None or root is None or not isinstance(flow_doc, Mapping):
        return {}
    now = now or datetime.now(UTC)
    count = None
    out: dict[str, str] = {}
    for a in _maps(flow_doc.get("audits")):
        key, every = flow3.key_of(a.get("name")), stage_audit.clock(a.get("every"))
        try:
            run = store.audit(team, key)
        except UNREADABLE:
            continue
        if run is not None and not isinstance(run, Mapping):
            continue  # a hand-edited record that is no object: unread, never the page's failure
        merged = None
        if every is not None and every.unit == "merged-pull-requests" and run and run.get("base"):
            if count is None:
                count = stage_audit_pass.merged_since(root, f"origin/{gitinfo.default_branch(root)}")
            merged = count(str(run["base"]))
        out[key] = stage_audit.next_round(run, every, merged, now)
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
    node_mark: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The `team_show` RPC's body, in a thread of the host agent. `node_mark` is the home's *cannot run* mark of a
    team on a node (§4.9d *A team on a node*), as the host record keeps it. A state branch that cannot be read costs
    the entries and the team's own copy of its flow, said in `unread`, and never the rest of the read."""
    where = [Path(r).expanduser() for r in roots]
    if not teamstore.switched(doc, team):
        return view(team, doc, rows, head, here, None, ())
    director = _has_director()
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
    rounds = audit_rounds(team, flow_doc, store, root) if unread is None else {}
    reply = view(team, doc, rows, head, here, flow_doc, records, director=director, rounds=rounds, node_mark=node_mark)
    return {**reply, "unread": unread}


# -- the flow pick and a switch (§4.9d *The flow pick and a switch*, TD-2062) ---------------------------------------

NODE_REPO_FLOW = "unknown: a node's checkout is not read here yet"
# which of a repo's flows a node's checkout holds (`{name: held}`), or why it was not read (§4.9d, TD-2062)
OnNode = Mapping[str, bool] | str | None
SWITCH_LINES = {
    "stays": "stays in {stage}, and its session carries on",
    "to-person": "its stage is gone: it comes to you, its branch and pull request kept",
    "re-enters": "its stage is gone and it has made no move: it enters again by {flow}'s way in, its pull request kept",
    "waits": "still waits on you",
    "merging": "merging, not touched",
}
ENDED = "; its session is ended, and what it had not pushed is lost"


def offered(repo: str, roots: Iterable[str | Path]) -> list[Mapping[str, Any]]:
    """The format-3 flows a team of `repo` could be given: the package's, the org's, and its own repo's."""
    rows = flow_save.listing(roots)["flows"]
    return [r for r in rows if r["doc"] is not None and (r["place"] != "repo" or r.get("repo") == repo)]


def _offered(team: str, doc: Mapping[str, Any], roots: Iterable[str | Path]) -> list[Mapping[str, Any]]:
    return offered(str(doc["teams"][team]["repo"]), roots)


def cannot_pick(
    team: str,
    row: Mapping[str, Any],
    entry: Mapping[str, Any],
    rows: Mapping[str, Any],
    here: str,
    on_node: OnNode = None,
) -> Any:
    """Why `team` cannot run the flow of `row`, *cannot run here: …*, or None. For a team on a node, a repo flow is
    judged by `on_node` (§4.9c *An org flow or role is not usable by a team on a node*): which of the repo's flows the
    node's checkout holds, as the host agent read them there (`node_flow_paths`), or why they were not read."""
    if row["problems"]:
        return f"cannot run here: {row['problems'][0]}"
    node = str(entry.get("host") or here)
    if node != here:
        if row["place"] == "own":
            return f"not followable: an org flow, and {team} runs on {node} — define it in the repo"
        if row["place"] == "repo":
            if on_node is None:
                return NODE_REPO_FLOW
            if isinstance(on_node, str):
                return f"unknown: {on_node}"
            if not on_node.get(str(row["name"])):
                return f"not followable: {row['name']} is not in {node}'s checkout of {entry.get('repo')} yet"
            return None
        return None  # a package flow rides the wheel; a node's logins are not read here
    doc = row["doc"]
    models = list(
        dict.fromkeys(str(x["model"]) for x in (*_maps(doc.get("stages")), *_maps(doc.get("audits"))) if x.get("model"))
    )
    why = teamstore.cannot_run(team, str(row["name"]), models, [str(x) for x in entry.get("logins") or ()], rows)
    return f"cannot run here: {why}" if why else None


def node_flow_paths(team: str, doc: Mapping[str, Any], here: str, roots: Iterable[str | Path]) -> dict[str, str]:
    """For a team on a node, the path in its repo's checkout of each of the repo's flows the home sees, `{name:
    path}`, for the host agent to ask the node for (§4.9c: a repo flow the node's checkout does not hold yet is not
    followable); none for a team here."""
    if str(doc["teams"][team].get("host") or here) == here:
        return {}
    where = [Path(r).expanduser() for r in roots]
    return {
        str(r["name"]): str(flowdefs.REPO_DIR / str(r["name"]) / "flow.yml")
        for r in _offered(team, doc, where)
        if r["place"] == "repo"
    }


def node_checkout(team: str, doc: Mapping[str, Any], repos_of: orgmod.ReposOf) -> str:
    """Where a node team's repo is checked out on its node, found as its start finds it (`org.host_checkout`: the org
    file's path for the node first, else the node's one registry entry of the repo, asked through `repos_of`), for
    the host agent to read its flows there (§4.9c). Where it cannot be told, raises with the start's reason, the node
    named first; the pick then reads each repo flow *unknown*."""
    entry = doc["teams"][team]
    host, repo = str(entry.get("host") or ""), str(entry.get("repo") or "")
    try:
        org = orgmod.load()
    except ValueError as e:  # a start refuses on the same file
        raise ValueError(f"{host}'s checkout of {repo} could not be told: {e}") from None
    try:
        got = orgmod.host_checkout(org, repo, host, repos_of)
    except OSError as e:
        raise ValueError(f"{host}'s registry could not be read ({e})") from None
    if isinstance(got, str):
        raise ValueError(f"{host}'s registry {got}")
    return str(got)


def choices(
    team: str,
    doc: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    here: str,
    roots: Iterable[str | Path],
    on_node: OnNode = None,
) -> list[dict[str, Any]]:
    """The flow pick (§4.9d): every flow the team could be given, each it cannot run with its reason, `current` the
    one it runs. One reading, which the switch is refused by too."""
    where = [Path(r).expanduser() for r in roots]
    entry = doc["teams"][team]
    return [
        {
            "name": r["name"],
            "place": r["place"],
            "current": r["name"] == entry.get("flow"),
            "cannot_run": cannot_pick(team, r, entry, rows, here, on_node),
        }
        for r in _offered(team, doc, where)
    ]


def _keys(flow_doc: Mapping[str, Any], old: Any = None) -> list[str]:
    """The new flow's stage keys whose sessions-at-once number a switch keeps: each the old flow has under the same
    kind, or does not have at all (§4.9d: a stage is kept by its key and kind)."""
    was = (
        {flow3.key_of(s.get("name")): s.get("does") for s in _maps(old.get("stages"))}
        if isinstance(old, Mapping)
        else {}
    )
    return [
        k
        for s in _maps(flow_doc.get("stages"))
        if (k := flow3.key_of(s.get("name"))) not in was or was[k] == s.get("does")
    ]


def _picked(
    team: str,
    flow: str,
    doc: Mapping[str, Any],
    rows: Any,
    here: str,
    where: list[Path],
    check: bool = True,
    on_node: OnNode = None,
) -> Mapping[str, Any]:
    """The flow row a switch to `flow` would run, refused (ValueError) where the team cannot run it; with `check`
    False, only where there is no such flow, for a switch a restart finishes, which was checked when it was pressed."""
    entry = doc["teams"][team]
    row = next((r for r in _offered(team, doc, where) if r["name"] == flow), None)
    if row is None:
        raise ValueError(f"there is no flow named {flow} that {team} could be given")
    if flow == entry.get("flow"):
        raise ValueError(f"{team} already runs {flow}")
    why = cannot_pick(team, row, entry, rows, here, on_node) if check else None
    if why:
        raise ValueError(f"{team} cannot be switched to {flow}: {why}")
    return row


def switch_lines(
    records: Iterable[Mapping[str, Any]], team: str, new: Mapping[str, Any], old: Any, live: Iterable[str]
) -> list[dict[str, Any]]:
    """What a switch to `new` does to each of the team's open records, from `old`, the flow they were written under
    where it reads: the line the preview draws and the case the tick's reconcile then takes, one function for both
    (`stage_acts.switch_case` over `stage_read.flow_on`). A session is said to be ended only where it is live."""
    alive = set(live)
    was = old if isinstance(old, Mapping) else None
    out = []
    for r in _open(records, team):
        known = flow_on(r, new, was).stage_known
        case = switch_case(r, known)
        holder = r.get("holder")
        ends = case in ("to-person", "re-enters") and bool(holder) and str(holder) in alive
        words = SWITCH_LINES[case].format(stage=r.get("stage"), flow=new.get("name"))
        out.append(
            {
                "id": r.get("id"),
                "stage": r.get("stage"),
                "holder": holder,
                "case": case,
                "ends": ends,
                "pr": r.get("pr"),
                "line": f"{words}{ENDED if ends else ''}",
            }
        )
    return out


def switch_preview(
    *,
    team: str,
    flow: str,
    doc: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    here: str,
    roots: Iterable[str | Path],
    live: Iterable[str] = (),
    on_node: OnNode = None,
) -> dict[str, Any]:
    """The switch preview (§4.9d): every open record of the team and what a switch to `flow` does to it, and the
    sessions-at-once numbers it drops. `refused` says why the team cannot run it, and Switch now is then disabled. A
    state branch that cannot be read is no preview: a record not read is never read as no record."""
    where = [Path(r).expanduser() for r in roots]
    if not teamstore.switched(doc, team):
        raise ValueError(f"no switched team {team!r}")
    entry = doc["teams"][team]
    out: dict[str, Any] = {
        "team": team,
        "flow": flow,
        "from": entry.get("flow"),
        "version": teamstore.version(doc, team),
    }
    try:
        row = _picked(team, flow, doc, rows, here, where, on_node=on_node)
    except ValueError as e:
        return {**out, "refused": str(e), "records": [], "drops": [], "none_ended": True}
    root = _root(str(entry["repo"]), where)
    if root is None:
        raise StateError(f"{entry['repo']} is not a registered checkout here")
    store = StageStore(root)
    old = _flow_doc(team, str(entry.get("flow") or ""), store, where)
    lines = switch_lines(store.entries().values(), team, row["doc"], old, live)
    keys = set(_keys(row["doc"], old))
    numbers = entry.get("at_once") if isinstance(entry.get("at_once"), Mapping) else {}
    return {
        **out,
        "refused": None,
        "records": lines,
        "drops": sorted(k for k in numbers if k not in keys),
        "none_ended": not any(x["ends"] for x in lines),
    }


def switch_push(
    *,
    team: str,
    flow: str,
    doc: Mapping[str, Any],
    rows: Mapping[str, Mapping[str, Any]],
    here: str,
    roots: Iterable[str | Path],
    check: bool = True,
    on_node: OnNode = None,
) -> list[str]:
    """A switch's commit point (§4.9d): the team's copy of `flow` pushed to the state branch, unless the copy already
    is it (a switch a restart finishes). Its stage keys, for the numbers kept. Raises where the team cannot run the
    flow (ValueError) and where the branch is not written (`StateError`, a refused push `StateRefused`)."""
    where = [Path(r).expanduser() for r in roots]
    row = _picked(team, flow, doc, rows, here, where, check, on_node)
    root = _root(str(doc["teams"][team]["repo"]), where)
    if root is None:
        raise StateError(f"{doc['teams'][team]['repo']} is not a registered checkout here")
    store = StageStore(root)
    old = _flow_doc(team, str(doc["teams"][team].get("flow") or ""), store, where)
    with store.locked():
        if store.flow(team) != row["text"]:
            store.put_flow(team, row["text"])
    return _keys(row["doc"], old)
