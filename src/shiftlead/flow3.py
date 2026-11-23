"""A format-3 flow: its reader and its check (design §4.9c *A flow is records, not prose*, *A flow is usable only
when it flows*, *The built-in flows*; TD-2047, from TD-1954's trial checker).

A format-3 `flow.yml` is stages of one kind each, every outcome with one destination. This module reads one and says
whether it flows (rules 1 to 10), which stages carry the builder's independent review (rule 11), what warns and what
goes to the person. It writes nothing and starts nothing: until the cut-over (§4.9e) no team runs a format-3 flow, and
a team's flow name resolves to the first shape's built-ins (`shiftlead.flowdefs`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from sessionorc import adapters, cadence, paths
from shiftlead import repoconfig

FORMAT = 3
FILE = "flow.yml"
PACKAGE_DIR = Path(__file__).resolve().parent / "flows3"
STANDARD_DIR = Path(__file__).resolve().parent / "briefs" / "standard"
REPO_DIR = Path(".shiftlead") / "flows"
BUILTIN = ("design-wise", "build-review", "build")
OUTCOMES = {
    "design": ("work-pushed", "no-design-needed"),
    "build": ("work-pushed", "design-needs-changing", "not-needed"),
    "review": ("ship", "changes-wanted"),
}
OTHER = "other"
FIXED = ("person", "done", "merge")  # destinations no stage may be named
CAN_MERGE = ("work-pushed", "ship")
WRITES = ("design", "build")
TOP_KEYS = ("format", "name", "max-moves", "stages", "audits")
STAGE_KEYS = ("name", "does", "model", "takes", "only-when", "brief", "also")
AUDIT_KEYS = ("name", "model", "every", "brief", "also")
TAKES = ("design-first", "other", "any")
MAX_MOVES = 25
EVERY = re.compile(r"^[1-9]\d* (merged-pull-requests|hours|days)$")
# the standard briefs (§4.9c *What a stage's session is told*), each with its kind
STANDARD = {
    "design": "design",
    "build": "build",
    "review": "review",
    "docs": "audit",
    "tests": "audit",
    "code": "audit",
}
BRIEF_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
KIND_LINE = re.compile(r"kind:\s*([a-z]+)")

Reader = Callable[[Path], "str | None"]


@dataclass
class Checked:
    """What the check found: `problems` keep the flow from being usable; `info` is what it says of a usable one."""

    problems: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.problems


def key_of(name: Any) -> str:
    """A stage's key: its name in lower case with spaces as hyphens (§4.9c *A stage's key is its name*)."""
    return str(name).strip().lower().replace(" ", "-")


def model_families() -> tuple[str, ...]:
    """Every model family a registered adapter names (§4.2b `models`): what the Tools page can list. An adapter asked
    with no plan offers its whole list; one that does not answer adds nothing."""
    adapters.load_all()
    got: list[str] = []
    for name in adapters.names():
        reader = getattr(adapters.get(name), "models", None)
        if reader is None:
            continue
        try:
            offer = reader(Path("/nonexistent"), None)
        except Exception:  # noqa: BLE001, S112 — a third-party adapter's read is no reason to refuse every flow
            continue
        got += [f for f in (offer.get("families") or []) if f not in got]
    return tuple(got)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def org_briefs() -> Path:
    """The org's own briefs, beside its flows (§4.9c *Where a brief lives*)."""
    return paths.home() / "briefs"


def brief_kind(text: str) -> str | None:
    """A person's brief's kind: the `kind:` line of its front matter (§4.9c *Where a brief lives*), or None."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        if m := KIND_LINE.fullmatch(line.strip()):
            return m.group(1)
    return None


def _brief_problem(name: Any, kind: str, place: str, flow_dir: Path | None, read: Reader) -> str | None:
    """Why `brief: name` cannot serve a stage or audit of `kind` from a flow in `place` (rule 10), or None."""
    if not isinstance(name, str) or not BRIEF_NAME.fullmatch(name):
        return f"`brief: {name}` is not a brief's name"
    if name in STANDARD:
        return (
            None
            if STANDARD[name] == kind
            else f"`brief: {name}` is the standard {STANDARD[name]} brief, not a {kind} one"
        )
    text = read(flow_dir / "briefs" / f"{name}.md") if flow_dir is not None and place != "package" else None
    if text is None and place == "repo":
        if _read(org_briefs() / f"{name}.md") is not None:
            return f"`brief: {name}` is one of the org's, which a repo's flow may not name"
        return f"`brief: {name}` is no standard brief and not in this flow's briefs/"
    if text is None and place != "package":
        text = _read(org_briefs() / f"{name}.md")
    if text is None:
        return f"`brief: {name}` is no standard brief and no brief of the person's own"
    got = brief_kind(text)
    if got is None:
        return f"`brief: {name}` writes no `kind:` in its front matter"
    return None if got == kind else f"`brief: {name}` is a {got} brief, not a {kind} one"


def check(
    doc: Any,
    *,
    place: str = "file",
    flow_dir: Path | None = None,
    repo_root: Path | str | None = None,
    read: Reader | None = None,
) -> Checked:
    """§4.9c's check of a parsed `flow.yml`. `place` is `package`, `org`, `repo` or `file` (rule 10's brief lookup);
    `repo_root`, where given, is the repo the flow is checked against (a `merge` destination needs its gate)."""
    out = Checked()
    bad, info = out.problems, out.info
    reader = read or _read
    if not isinstance(doc, dict) or not isinstance(doc.get("stages"), list) or not doc["stages"]:
        bad.append("the file needs a `stages:` list with at least one stage")
        return out
    for k in doc:
        if k not in TOP_KEYS:
            bad.append(f"unknown key at the top: `{k}`")
    if doc.get("format") != FORMAT or isinstance(doc.get("format"), bool):
        bad.append("`format: 3` is required")
    mm = doc.get("max-moves", MAX_MOVES)
    if not isinstance(mm, int) or isinstance(mm, bool) or mm < 2:
        bad.append("`max-moves` is a whole number, 2 or more (rule 9)")
    models = model_families()
    audits = _audits(doc.get("audits"), models, place, flow_dir, reader, bad)
    stages, takes = _stages(doc["stages"], audits, models, place, flow_dir, reader, bad)
    for kind, who in takes.items():
        if len(who) != 1:
            tip = "; a flow with no design stage writes `takes: any` on its first build stage" if not who else ""
            bad.append(f"new `{kind}` entries need exactly one stage that takes them; found {len(who)}{tip} (rule 6)")
    for st in stages.values():
        for o in (*OUTCOMES[st["kind"]], OTHER):
            _move(st, o, st["outs"].get(o, "person"), stages, audits, bad)
    _loops(stages, bad)
    _reach(stages, takes, bad, info)
    if repo_root is not None and any(st["merges"] for st in stages.values()) and not cadence.holds(repo_root):
        bad.append(
            f"it goes to merge, and {Path(repo_root).name} has no pinned agent-cadence, so no merge gate serves it"
        )
    info.append(f"an entry goes to the person after {mm} moves between stages, wherever it is")
    for st in stages.values():
        if st["asks"]:
            info.append(f"{st['name']}: goes to the person on {', '.join(st['asks'])}")
    for name in audits.values():
        info.append(f"{name}: an audit on its clock; `other` goes to the person")
    out.problems[:] = list(dict.fromkeys(bad))
    out.info[:] = list(dict.fromkeys(info))
    return out


def _audits(
    raw: Any, models: Collection[str], place: str, flow_dir: Path | None, read: Reader, bad: list[str]
) -> dict[str, str]:
    audits: dict[str, str] = {}
    if raw is None:
        return audits
    if not isinstance(raw, list):
        bad.append("`audits:` is a list")
        return audits
    for i, a in enumerate(raw, 1):
        if not isinstance(a, dict) or not a.get("name"):
            bad.append(f"audit {i} has no name (rule 10)")
            continue
        name = str(a["name"])
        for k in a:
            if k not in AUDIT_KEYS:
                bad.append(f"{name}: unknown key `{k}`; an audit has {', '.join(AUDIT_KEYS)} (rule 10)")
        if a.get("model") not in models:
            bad.append(f"{name}: model must be one of {', '.join(models)} (rule 10)")
        if not EVERY.match(str(a.get("every", ""))):
            bad.append(f"{name}: `every` is written like `10 merged-pull-requests`, `6 hours` or `1 days` (rule 10)")
        if not a.get("brief"):
            bad.append(
                f"{name}: an audit needs a `brief:`: docs, tests, code, or a brief of the person's own (rule 10)"
            )
        elif why := _brief_problem(a["brief"], "audit", place, flow_dir, read):
            bad.append(f"{name}: {why} (rule 10)")
        if key_of(name) in audits or key_of(name) in FIXED:
            bad.append(f"{name}: the name is already used, or is a reserved word (rule 7)")
        audits[key_of(name)] = name
    return audits


def _stages(
    raw: list,
    audits: Mapping[str, str],
    models: Collection[str],
    place: str,
    flow_dir: Path | None,
    read: Reader,
    bad: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    stages: dict[str, dict[str, Any]] = {}
    takes: dict[str, list[str]] = {"design-first": [], "other": []}
    for i, st in enumerate(raw, 1):
        if not isinstance(st, dict) or not st.get("name"):
            bad.append(f"stage {i} has no name (rule 7)")
            continue
        name, kind = str(st["name"]), st.get("does")
        key = key_of(name)
        if key in stages or key in FIXED or key in audits:
            bad.append(f"{name}: the name is already used, or is a reserved word (rule 7)")
            continue
        if not isinstance(kind, str) or kind not in OUTCOMES:
            hint = "; an audit goes in the `audits:` list" if kind in ("audit", "hunt") else ""
            hint = "; merge is a destination, not a stage" if kind == "merge" else hint
            hint = "; a stage does one kind of work, so write two stages" if isinstance(kind, list) else hint
            bad.append(f"{name}: `does` must be one of {', '.join(OUTCOMES)}{hint} (rule 7)")
            continue
        if st.get("model") not in models:
            bad.append(f"{name}: model must be one of {', '.join(models)} (rule 7)")
        outs: dict[str, Any] = {}
        for k, v in st.items():
            if k in STAGE_KEYS:
                continue
            if k in OUTCOMES[kind] or k == OTHER:
                outs[k] = v
            elif any(k in o for o in OUTCOMES.values()):
                bad.append(
                    f"{name}: `{k}` is not an outcome of a {kind} stage; its outcomes are "
                    f"{', '.join(OUTCOMES[kind])} and {OTHER} (rule 2)"
                )
            else:
                bad.append(f"{name}: unknown key `{k}`")
        t = st.get("takes")
        if t is not None and t not in TAKES:
            bad.append(f"{name}: takes must be {', '.join(TAKES)}")
        elif t and kind == "review":
            bad.append(f"{name}: a review stage cannot take new entries; it reads work another stage pushed (rule 6)")
        elif t:
            for k in takes:
                if t in (k, "any"):
                    takes[k].append(name)
        only = st.get("only-when")
        if only is not None and (kind != "review" or only != "protected-files"):
            bad.append(f"{name}: `only-when: protected-files` is the one value, and only on a review stage")
        if st.get("brief") is not None and (why := _brief_problem(st["brief"], kind, place, flow_dir, read)):
            bad.append(f"{name}: {why} (rule 10)")
        if st.get("also") is not None and not isinstance(st["also"], str):
            bad.append(f"{name}: `also:` is text")
        stages[key] = {
            "name": name,
            "kind": kind,
            "model": st.get("model"),
            "outs": outs,
            "edges": [],
            "asks": [],
            "ends": False,
            "merges": False,
            "only": only is not None,
        }
    return stages, takes


def _move(
    st: dict[str, Any],
    where: str,
    value: Any,
    stages: Mapping[str, dict[str, Any]],
    audits: Mapping[str, str],
    bad: list[str],
    *,
    top: bool = True,
) -> None:
    """Read one destination of `st` and record its move (§4.9c *Where an outcome goes*; rules 1 and 5)."""
    name, limit, answers, refused = st["name"], None, None, None
    if isinstance(value, dict):
        if "to" not in value or set(value) - {"to", "limit", "answers", "refused"}:
            bad.append(
                f"{name}: `{where}` must be a destination, {{to: …, limit: n}}, {{to: merge, refused: …}} "
                "or {to: person, answers: {…}}"
            )
            return
        limit, answers, refused, value = value.get("limit"), value.get("answers"), value.get("refused"), value["to"]
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
            bad.append(f"{name}: `{where}`: a limit is a whole number, 1 or more")
            return
        if answers is not None and value != "person":
            bad.append(f"{name}: `{where}`: answers belong only with `to: person`")
        if refused is not None and value != "merge":
            bad.append(f"{name}: `{where}`: `refused` belongs only with `to: merge`")
        if limit is not None and isinstance(value, str) and value in FIXED:
            tip = "; put it on `refused`" if value == "merge" else ""
            bad.append(f"{name}: `{where}`: a limit sits on a move to a stage, not to `{value}`{tip}")
    if not isinstance(value, str):
        bad.append(f"{name}: `{where}` has no readable destination")
        return
    to = value if value in FIXED else key_of(value)
    outcome = where.split(".")[0]
    if to == "merge":
        if not top:
            bad.append(f"{name}: `{where}`: a refused merge cannot go to merge again")
        elif outcome not in CAN_MERGE:
            bad.append(f"{name}: `{where}`: only `work-pushed` or `ship` can go to merge (rule 1)")
        else:
            st["ends"] = st["merges"] = True
            _move(st, f"{outcome}.refused", "person" if refused is None else refused, stages, audits, bad, top=False)
    elif to == "person":
        st["asks"].append(where)
        if outcome in CAN_MERGE and top:
            st["ends"] = True
        if answers is not None and not isinstance(answers, dict):
            bad.append(f"{name}: `{where}`: answers are a mapping of a label to a stage")
            answers = None
        for label, a in (answers or {}).items():
            got = a if isinstance(a, str) and a in FIXED else key_of(a)
            if got in stages:
                st["edges"].append((where, got, "person"))
            elif got != "person":
                bad.append(f"{name}: `{where}`: the answer {label!r} goes to `{got}`, which is not a stage (rule 1)")
    elif to == "done":
        tip = (
            "send it to merge, a stage or the person" if outcome in CAN_MERGE else "leave it out, or send it to a stage"
        )
        bad.append(f"{name}: `{where}: done` is not a destination; {tip} (rule 5)")
    elif to in audits:
        bad.append(f"{name}: `{where}` goes to the audit `{to}`; an audit starts on its clock (rule 1)")
    elif to not in stages:
        bad.append(f"{name}: `{where}` goes to `{to}`, which is not a stage (rule 1)")
    else:
        st["edges"].append((where, to, limit))


def _loops(stages: Mapping[str, dict[str, Any]], bad: list[str]) -> None:
    """Rule 3: a route back to a stage, not through the person, carries a limit on one of its moves."""
    free = {k: [to for _, to, limit in st["edges"] if limit is None] for k, st in stages.items()}
    for start, st in stages.items():
        seen: set[str] = set()
        todo = list(free[start])
        while todo:
            k = todo.pop()
            if k == start:
                bad.append(f"{st['name']}: a loop through it has no limit on any of its moves (rule 3)")
                break
            if k not in seen:
                seen.add(k)
                todo += free[k]


def _reachable(stages: Mapping[str, dict[str, Any]], start: str, skip: Collection[str] = ()) -> set[str]:
    seen, todo = {start}, [start]
    while todo:
        for _, to, _limit in stages[todo.pop()]["edges"]:
            if to not in seen and to not in skip:
                seen.add(to)
                todo.append(to)
    return seen


def _reach(
    stages: Mapping[str, dict[str, Any]], takes: Mapping[str, list[str]], bad: list[str], info: list[str]
) -> None:
    """Rules 4, 8 and 11, and the same-model warning."""
    always = {k for k, st in stages.items() if st["kind"] == "review" and not st["only"]}
    for key, st in stages.items():
        if st["kind"] not in WRITES:
            continue
        reach = _reachable(stages, key)
        if not any(stages[k]["ends"] for k in reach):
            bad.append(f"{st['name']}: its pull request can never reach a merge or the person (rule 4)")
        for k in sorted(reach - {key}):
            if stages[k]["kind"] == "review" and stages[k]["model"] == st["model"]:
                info.append(f"warning: {stages[k]['name']} reviews on {st['model']}, the model {st['name']} writes on")
        if any(stages[k]["merges"] for k in _reachable(stages, key, always)):
            info.append(
                f"{st['name']}: merge can be reached with no review that always runs, so its session runs the "
                "cadence's independent review first (rule 11)"
            )
    entered = {to for st in stages.values() for _, to, _limit in st["edges"]}
    entered |= {key_of(n) for who in takes.values() for n in who}
    for key, st in stages.items():
        if key not in entered:
            bad.append(f"{st['name']}: nothing can reach this stage (rule 8)")


def is_format3(text: str | None) -> bool:
    """Whether a `flow.yml`'s text writes `format: 3`: the reader takes a flow by that key (§4.9c)."""
    if text is None:
        return False
    try:
        data = repoconfig.parse_yaml(text)
    except yaml.YAMLError:
        return False
    return isinstance(data, dict) and data.get("format") == FORMAT and not isinstance(data.get("format"), bool)


def check_text(
    text: str,
    *,
    place: str = "file",
    flow_dir: Path | None = None,
    repo_root: Path | str | None = None,
    read: Reader | None = None,
) -> Checked:
    """`check` over a file's text; text that is no YAML is the one problem."""
    try:
        doc = repoconfig.parse_yaml(text)
    except yaml.YAMLError as e:
        return Checked(problems=[f"the file is not valid YAML: {e}"])
    got = check(doc, place=place, flow_dir=flow_dir, repo_root=repo_root, read=read)
    if flow_dir is not None and place in ("org", "repo") and flow_dir.name in BUILTIN:
        got.problems.append(f"{flow_dir.name} is a built-in flow's name: define your own under another name")
    return got


def place_of(path: Path) -> tuple[str, Path | None]:
    """Where a `flow.yml` sits: `(place, repo root)`, the root for a repo's flow alone."""
    d = path.resolve().parent
    if d.parent == PACKAGE_DIR:
        return "package", None
    if d.parent == (paths.home() / "flows").resolve():
        return "org", None
    if d.parent.parts[-2:] == REPO_DIR.parts:
        return "repo", d.parent.parent.parent
    return "file", None


def check_file(path: Path | str, *, repo: Path | str | None = None) -> Checked:
    """`ao flow check <file>`: a repo's flow is checked against its own repo unless `repo` names one."""
    p = Path(path).expanduser()
    text = _read(p)
    if text is None:
        return Checked(problems=[f"{p}: cannot be read"])
    place, root = place_of(p)
    return check_text(text, place=place, flow_dir=p.resolve().parent, repo_root=repo or root)


def builtins() -> list[dict[str, Any]]:
    """The format-3 built-ins, each `{name, source, usable, problems, format, in_use}`: none is in use until the
    cut-over (§4.9e), when they take the names."""
    out: list[dict[str, Any]] = []
    for name in BUILTIN:
        d = PACKAGE_DIR / name
        got = check_text(_read(d / FILE) or "", place="package", flow_dir=d)
        out.append(
            {
                "name": name,
                "source": str(d),
                "usable": got.usable,
                "problems": list(got.problems),
                "format": FORMAT,
                "in_use": False,
            }
        )
    return out


def node_reasons(doc: Any, place: str, flow_dir: Path, team: str, node: str, read: Reader) -> tuple[list[str], bool]:
    """Why a team on `node` cannot follow this flow (§4.9c *An org flow or role is not usable by a team on a node*),
    with whether the answer is known: an org flow never reaches a node, and a repo's is read from the node's checkout
    through `read`, so a file it does not hold is *not followable* and a node that does not answer is *unknown*."""
    if place == "org":
        return [f"an org flow, and {team} runs on {node} — define it in the repo"], True
    if place != "repo":
        return [], True  # a package flow rides the wheel
    wanted = [flow_dir / FILE]
    named = [*(doc.get("stages") or []), *(doc.get("audits") or [])] if isinstance(doc, dict) else []
    for x in named:
        b = x.get("brief") if isinstance(x, dict) else None
        if isinstance(b, str) and b not in STANDARD:
            wanted.append(flow_dir / "briefs" / f"{b}.md")
    out: list[str] = []
    for p in wanted:
        try:
            if read(p) is None:
                out.append(f"{p.relative_to(flow_dir)} is not in {node}'s checkout")
        except (OSError, ValueError):
            return [f"{node} did not answer"], False
    return out, True
