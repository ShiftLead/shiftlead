"""`ao stage end`: a session's one way to end its stage (design §4.9c *An outcome is the session's word, checked*, *A
verdict is on the stage record*, *One holder ends a stage*, *Where an outcome goes*, *Limits*; §4.7; TD-2050).

The host agent calls `call` through the `shiftlead.home_calls` entry point, since `sessionorc` never imports this
package. One repo's calls run one at a time: the store's lock is held from the record's read to its write. Each
outcome's fact is read here, from the session's worktree and the forge, never taken from the session. Nothing calls
this until a stage's session exists (TD-2051's offer); an audit's outcomes are TD-2053's.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from sessionorc import board, ledgerboard, reports, workorders
from shiftlead import flow3, repoconfig, stage_work
from shiftlead.stagerecord import StageStore, StateError, _now, ask_words

GIT_TIMEOUT = 30.0
GH_TIMEOUT = 30.0
FILES_CAP = 100  # what `gh pr view --json files` returns at most
NEEDS_NO_REASON = ("work-pushed", "ship")
AUDIT_OUTCOMES = ("findings-filed", "nothing-found")
CARRY_ON = "Carry on — a session takes the move that was stopped, and its counts start again"
ARCHIVE = "Archive the entry — the home archives it"
BUILD_ANYWAY = "Build it anyway — a session builds it in this stage again"
TRY_AGAIN = "Try the merge again — the home runs the gate and merges"


class Refused(Exception):
    """The outcome is not taken and nothing was written: the words name the fact, and the session carries on."""


@dataclass(frozen=True)
class PullRequest:
    number: int
    head: str
    branch: str
    state: str
    fork: bool
    precheck: bool
    files: tuple[str, ...]


class Facts(Protocol):
    """What the home reads for a check: the session's worktree and the forge."""

    def branch(self) -> str | None: ...
    def worktree_head(self) -> str | None: ...
    def fetched_head(self, branch: str) -> str | None: ...
    def pull_request(self, branch: str | None, number: int | None) -> PullRequest | None: ...
    def post_review(self, number: int, body: str) -> None: ...


class ForgeFacts:
    """The facts as git and `gh` give them, from the session's worktree `directory`."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = str(directory)

    def _git(self, *args: str) -> str | None:
        try:
            cp = subprocess.run(
                ["git", "-C", self.directory, *args], capture_output=True, text=True, timeout=GIT_TIMEOUT, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            raise Refused("the session's worktree could not be read: try again") from None
        return cp.stdout.strip() or None if cp.returncode == 0 else None

    def _gh(self, *args: str) -> str:
        try:
            cp = subprocess.run(
                ["gh", *args], capture_output=True, text=True, timeout=GH_TIMEOUT, cwd=self.directory, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            raise Refused("the forge could not be asked: try again") from None
        if cp.returncode != 0:
            said = ((cp.stderr or "").strip().splitlines() or ["no reason given"])[-1][:200]
            raise Refused(f"the forge did not answer ({said}): try again")
        return cp.stdout

    def branch(self) -> str | None:
        return self._git("symbolic-ref", "--short", "-q", "HEAD")

    def worktree_head(self) -> str | None:
        return self._git("rev-parse", "HEAD")

    def fetched_head(self, branch: str) -> str | None:
        """The commit this worktree last fetched for `branch`, from its own `FETCH_HEAD`: `refs/remotes/origin/*` are
        shared by every worktree of the repo, so a sibling's push moves them under a reviewer that never read it."""
        return self.fetched_heads().get(branch)

    def fetched_heads(self) -> dict[str, str]:
        """Every branch this worktree's `FETCH_HEAD` names, with the commit fetched for it (the first line of each)."""
        where = self._git("rev-parse", "--git-path", "FETCH_HEAD")
        if not where:
            return {}
        try:
            text = (Path(self.directory) / where).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {}
        out: dict[str, str] = {}
        for line in text.splitlines():
            sha, _, rest = line.partition("\t")
            _merge, _, said = rest.partition("\t")
            if said.startswith("branch '") and (cut := said.rfind("' of ")) > 0:
                out.setdefault(said[len("branch '") : cut], sha)
        return out

    def pull_request(self, branch: str | None, number: int | None) -> PullRequest | None:
        fields = "number,headRefOid,headRefName,state,isCrossRepository,statusCheckRollup,files"
        if number is not None:
            rows = [json.loads(self._gh("pr", "view", str(number), "--json", fields))]
        elif branch:
            listed = self._gh("pr", "list", "--head", branch, "--state", "open", "--json", fields)
            rows = [r for r in json.loads(listed) if not r.get("isCrossRepository")]
        else:
            return None
        if len(rows) != 1:
            return None
        r = rows[0]
        green = reports.at_done(r, [reports.PRECHECK_CONTEXT], precheck=True)["word"] == "green"
        return PullRequest(
            number=int(r["number"]),
            head=str(r.get("headRefOid") or ""),
            branch=str(r.get("headRefName") or ""),
            state=str(r.get("state") or "").upper(),
            fork=bool(r.get("isCrossRepository")),
            precheck=green,
            files=self._files(r),
        )

    def _files(self, row: dict[str, Any]) -> tuple[str, ...]:
        """The pull request's files: the JSON field stops at 100, so a list that long is read from its diff."""
        files = tuple(str(f.get("path")) for f in row.get("files") or [])
        if len(files) < FILES_CAP:
            return files
        return tuple(self._gh("pr", "diff", str(row["number"]), "--name-only").split("\n")[:-1])

    def post_review(self, number: int, body: str) -> None:
        said = json.loads(self._gh("pr", "view", str(number), "--json", "comments"))
        reviews = [
            c.get("body") for c in said.get("comments") or [] if str(c.get("body")).startswith("cadence-review:")
        ]
        if reviews and reviews[-1] == body:
            return  # a repeated call after a crash; only the latest counts, since the gate's row reads the latest
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            self._gh("pr", "comment", str(number), "--body-file", f.name)


class NodeFacts(ForgeFacts):
    """A node session's facts: its worktree as the node read it (`worktree_reading`), the forge from the home's own
    checkout of the same origin, since the session's directory is not on this machine."""

    def __init__(self, root: str | Path, seen: dict[str, Any]) -> None:
        super().__init__(root)
        self.seen = seen

    def branch(self) -> str | None:
        return self.seen.get("branch") or None

    def worktree_head(self) -> str | None:
        return self.seen.get("head") or None

    def fetched_heads(self) -> dict[str, str]:
        return {str(k): str(v) for k, v in (self.seen.get("fetched") or {}).items()}


def worktree_reading(directory: str) -> dict[str, Any]:
    """What the home needs of a worktree on this node: `{branch, head, fetched, origin}`, or `{refused: …}`."""
    facts = ForgeFacts(directory)
    try:
        return {
            "branch": facts.branch(),
            "head": facts.worktree_head(),
            "fetched": facts.fetched_heads(),
            "origin": facts._git("remote", "get-url", "origin"),
        }
    except Refused as e:
        return {"refused": str(e)}


def destination(stage: dict[str, Any], outcome: str) -> dict[str, Any]:
    """Where `outcome` goes from `stage`, as `{to, limit, answers, refused}`; unwritten, to the person."""
    raw = stage.get(outcome, "person")
    got = dict(raw) if isinstance(raw, dict) else {"to": raw}
    to = str(got.get("to"))
    got["to"] = to if to in flow3.FIXED else flow3.key_of(to)
    return got


def _review_body(stage: dict[str, Any], caller: str, verdict: str, head: str, files: tuple[str, ...], why: str) -> str:
    """The `cadence-review:` comment the gate's review row reads (§4.9c *The gate's review row needs no new input*)."""
    what = "docs" if files and all(f.startswith("docs/") or f.endswith(".md") for f in files) else "code"
    count = 0 if verdict == "SHIP" else 1
    lines = [f"cadence-review: {verdict} · {stage['model']} · {what} · {count} findings", "", f"Read at {head}."]
    if why:
        lines += ["", why]
    return "\n".join([*lines, "", f"— {caller} (stage {flow3.key_of(stage['name'])})"])


def _check_pushed(
    record: dict[str, Any], stage: dict[str, Any], where: dict[str, Any], doc: dict[str, Any], facts: Facts
) -> PullRequest:
    """`work-pushed`'s fact, and the first place the entry's branch and pull request are written (§4.9c)."""
    tid = record["id"]
    branch = record.get("branch") or facts.branch()
    if not branch:
        raise Refused("this worktree is on no branch: work on the entry's branch and push it")
    if not record.get("branch") and stage_work.branch_ids(branch) != {tid}:
        raise Refused(f"the branch {branch} does not name {tid} alone: an entry's branch holds its id and no other")
    pr = facts.pull_request(branch, record.get("pr"))
    if pr is None:
        raise Refused(f"the branch {branch} has no open pull request of this repo: open it, then end the stage")
    if pr.fork or pr.state != "OPEN":
        raise Refused(f"pull request #{pr.number} is not open on this repo")
    if facts.worktree_head() != pr.head:
        raise Refused(f"this worktree's head is not pull request #{pr.number}'s head: push your work")
    after = _stage_or_none(doc, where["to"])
    if not (stage["does"] == "build" and after is not None and after["does"] == "build") and not pr.precheck:
        raise Refused(f"pull request #{pr.number}'s precheck is not green at its head")
    if stage["does"] == "build" and (where["to"] == "merge" or (after is not None and after["does"] == "review")):
        archived = f"docs/ledger/archive/{tid}.md"
        if not any(f == archived or f.endswith(f"/archive/{tid}.md") for f in pr.files):
            raise Refused(f"pull request #{pr.number} does not archive {tid}: archive the entry on the branch")
    return pr


def _check_read(record: dict[str, Any], facts: Facts, *, ship: bool) -> tuple[PullRequest, str]:
    """The pull request a review stage read and the head it read: for `ship`, the head has not moved since."""
    pr = facts.pull_request(record.get("branch"), record.get("pr"))
    if pr is None or pr.state != "OPEN":
        raise Refused("this entry has no open pull request to give a verdict on")
    read = facts.fetched_head(pr.branch)
    if ship and read != pr.head:
        raise Refused(f"pull request #{pr.number}'s head is {pr.head[:12]}, not what you read: fetch and read again")
    return pr, read or pr.head


def _stage_or_none(doc: dict[str, Any], key: str) -> dict[str, Any] | None:
    for st in doc.get("stages") or []:
        if isinstance(st, dict) and flow3.key_of(st.get("name")) == key:
            return st
    return None


def _answers(stage: dict[str, Any], key: str, outcome: str, where: dict[str, Any], stopped: bool) -> dict[str, Any]:
    """The answers a move to the person offers, each to the move it makes (§4.9c): `blocked` takes the stopped move,
    `archive` is the home's, and *Something else* (added by the store) goes back to the stage that asked."""
    out: dict[str, Any] = {}
    if stopped:
        out[CARRY_ON] = {"blocked": True}
    elif outcome == "not-needed":
        out[ARCHIVE] = {"archive": True}
        out[BUILD_ANYWAY] = key
    for label, to in (where.get("answers") or {}).items():
        out[f"{label} — a session takes it to {flow3.key_of(to)}"] = flow3.key_of(to)
    if not out:
        out[f"Back to {stage['name']} — a session takes it back to this stage"] = key
    return out


def _to_person(
    store: StageStore,
    record: dict[str, Any],
    stage: dict[str, Any],
    key: str,
    outcome: str,
    reason: str,
    where: dict[str, Any],
    person: str,
    blocked: dict[str, Any] | None,
) -> None:
    ask, context = ask_words(key, outcome, reason)
    if blocked is not None:
        where = {"to": "person"}
    answers = _answers(stage, key, outcome, where, blocked is not None)
    store.record_intent(record["id"], person, ask, context, answers, blocked=blocked, base=record)


def _apply(
    store: StageStore,
    record: dict[str, Any],
    doc: dict[str, Any],
    stage: dict[str, Any],
    key: str,
    outcome: str,
    reason: str,
    where: dict[str, Any],
    head: str | None,
    person: str,
    by: str,
) -> str:
    """Write the move: returns where the entry went."""
    to, count = where["to"], f"{key}:{outcome}"
    record["holder"] = None
    record["answer"] = None
    went = to
    blocked: dict[str, Any] | None = None
    if to not in flow3.FIXED:
        counts = record.setdefault("counts", {})
        limit = where.get("limit")
        cap = doc.get("max-moves", flow3.MAX_MOVES)
        if limit is not None and int(counts.get(count, 0)) >= int(limit):
            blocked, went = {"to": to, "count": count}, "person"
        elif int(record.get("moves") or 0) >= int(cap):
            blocked, went = {"to": to, "count": count, "cap": True}, "person"
        else:
            counts[count] = int(counts.get(count, 0)) + 1
            record["moves"] = int(record.get("moves") or 0) + 1
            record["stage"] = to
            record["entered_at"] = _now()
            record["offers"] = 0
    record.setdefault("history", []).append(
        {"from": key, "outcome": outcome, "reason": reason, "by": by, "to": went, "head": head, "at": _now()}
    )
    if went == "merge":
        record["waits"] = "merging"
        record["merging"] = {"head": head, "stage": key, "outcome": outcome}
        store.put_entry(record, f"{outcome}: merging")
    elif went == "person":
        _to_person(store, record, stage, key, outcome, reason, where, person, blocked)
    else:
        store.put_entry(record, f"{outcome}: to {went}")
    return went


def end(
    store: StageStore,
    tid: str,
    caller: str,
    outcome: str,
    reason: str,
    doc: dict[str, Any],
    facts: Facts,
    person: str,
) -> dict[str, Any]:
    """Check `outcome` and write its move: `{entry, outcome, went, repeat}`, or `Refused` with nothing written."""
    said = " ".join((reason or "").split())
    with store.locked():
        record = store.entry(tid)
        if record is None:
            raise Refused(f"{tid} has no stage record")
        last = (record.get("history") or [None])[-1]
        if record.get("holder") != caller:
            if last and last.get("by") == caller and last.get("outcome") == outcome:
                return {"entry": tid, "outcome": outcome, "went": last.get("to"), "repeat": True}
            raise Refused("this entry is not yours")
        key = str(record["stage"])
        stage = _stage_or_none(doc, key)
        if stage is None:
            raise Refused(f"the flow has no stage {key}")
        kind = stage["does"]
        if outcome in AUDIT_OUTCOMES or outcome not in (*flow3.OUTCOMES[kind], flow3.OTHER):
            listed = ", ".join((*flow3.OUTCOMES[kind], flow3.OTHER))
            raise Refused(f"{outcome} is not an outcome of a {kind} stage: its outcomes are {listed}")
        if outcome not in NEEDS_NO_REASON and not said:
            raise Refused(f"{outcome} needs --reason")
        where = destination(stage, outcome)
        head: str | None = None
        if outcome == "work-pushed":
            pr = _check_pushed(record, stage, where, doc, facts)
            record["branch"], record["pr"], head = pr.branch, pr.number, pr.head
        elif outcome in ("ship", "changes-wanted"):
            pr, head = _check_read(record, facts, ship=outcome == "ship")
            verdict = "SHIP" if outcome == "ship" else "BLOCK"
            facts.post_review(pr.number, _review_body(stage, caller, verdict, head, pr.files, said))
            record.setdefault("verdicts", {})[key] = {"head": head, "stage": key, "outcome": outcome}
        went = _apply(store, record, doc, stage, key, outcome, said, where, head, person, caller)
    return {"entry": tid, "outcome": outcome, "went": went, "repeat": False}


def _person_of(root: Path) -> str:
    people = ledgerboard.board_people(board._board(root, workorders.board_rel(root)))
    if not people:
        raise Refused("the repo's board names no person to ask")
    return people[0]


def call(
    *,
    root: str,
    directory: str,
    team: str | None,
    tid: str,
    caller: str,
    outcome: str,
    reason: str,
    seen: dict[str, Any] | None = None,
) -> dict:
    """The `stage_end` RPC's body, in a thread of the host agent: a refusal is `{refused: <the fact>}`. `seen` is a
    node session's worktree as its node read it; `root` is then the home's checkout of that repo."""
    store = StageStore(root)
    try:
        text = store.flow(team) if team else None
        if text is None:
            return {"refused": f"team {team} has no flow on the state branch"}
        try:
            doc = repoconfig.parse_yaml(text)
        except yaml.YAMLError:  # a stored flow edited by hand into bad YAML is a refusal, not a failed call (TD-2150)
            return {"refused": f"team {team}'s flow on the state branch cannot be read"}
        return end(
            store,
            tid,
            caller,
            outcome,
            reason,
            doc,
            ForgeFacts(directory) if seen is None else NodeFacts(root, seen),
            _person_of(Path(root)),
        )
    except (Refused, StateError) as e:
        return {"refused": str(e)}


def show(*, root: str, tid: str) -> dict[str, Any]:
    """The `stage_show` RPC's body: the entry's record, or `{refused: …}`."""
    try:
        record = StageStore(root).entry(tid)
    except (StateError, ValueError) as e:
        return {"refused": str(e)}
    return record if record is not None else {"refused": f"{tid} has no stage record"}
