"""The stage record (design §4.9c *The stage record*, §4.4 *The stage record is a file on the repo's `shiftlead/state`
branch*, TD-2048): where each entry is in its flow, kept as one file per entry on one dedicated branch of the repo.

**The home is the branch's one writer.** Every write here is one commit pushed over the tip it read, never a pull
request and never through a checkout: the commit is built with git's plumbing on a private index, so no working tree
is touched. A push the forge refuses raises `StateRefused`, whose reason makes the team's flow *not usable*.
Nothing is cached: a restarted or reset home reads its records back from the branch.

A **move to the person** is written in the design's order: the record's intent (`record_intent`), the one pull
request holding the entry's gate and its board item (`land_intent`, through `sessionorc.board.ask_on_entry`), then
the record's wait. A crash between leaves an intent with no wait, which `land_intent` lands again and which writes
nothing twice.

`ao stage end` (`shiftlead.stage_end`, TD-2050) is its first reader; the tick's six acts are later builds.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import board

BRANCH = "shiftlead/state"
REF = f"refs/heads/{BRANCH}"
GIT_TIMEOUT = 60.0
PUSH_TRIES = 3
README = (
    "# shiftlead/state\n\nShiftLead's own record of where each ledger entry is in its flow. The home is this "
    "branch's one writer; no session pushes here (design §4.9c *The stage record*).\n"
)
WAITS = (None, "person", "parts", "merging")
OTHER = "Something else: <what>"
OTHER_ANSWER = f"{OTHER} — a session takes your words back to the stage that asked"

_ID = re.compile(r"TD-\d+")
JOB_KEY = re.compile(r"board-[0-9a-f]{8}|pr-[1-9]\d{0,6}")  # a built-in seat's job (§4.9d *How each one runs*)
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_LOCKS: dict[str, threading.RLock] = {}  # re-entrant: a caller holds it from a record's read to its write
_LOCKS_GUARD = threading.Lock()


class StateError(Exception):
    """The branch could not be read or written, and nothing was changed on it."""


class StateRefused(StateError):
    """The forge refused a push to the branch: the team's flow is not usable, for `reason`."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"origin refused the push to {BRANCH} ({reason})")
        self.reason = reason


def _lock(root: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(root.resolve()), threading.RLock())


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_record(
    tid: str, flow: str, stage: str, *, team: str | None = None, holder: str | None = None
) -> dict[str, Any]:
    """A record of an entry entering its flow's first stage, with every field §4.4 names. `team` is whose it is: two
    teams of one repo may run one flow, so the flow's name does not tell their entries apart (§4.9d)."""
    return {
        "id": tid,
        "team": team,
        "flow": flow,
        "stage": stage,
        "holder": holder,
        "branch": None,
        "pr": None,
        "entered_at": _now(),
        "counts": {},
        "moves": 0,
        "offers": 1 if holder else 0,
        "waits": None,
        "blocked": None,
        "answers": None,
        "asked": None,
        "answer": None,
        "verdicts": {},
        "history": [],
        "intent": None,
        "closed_at": None,
        "spent_before": {},
        "flow_hash": None,
    }


VERSIONS = "flows/versions"


def flow_version(text: str, briefs: list[Mapping[str, Any]]) -> tuple[str, str]:
    """A flow version's canonical text and its hash (§4.9c *The flow's content hash*): the JSON object of the flow
    file's text and each stage's resolved brief in the stages' order, sorted and compact, its SHA-256 in hex over the
    UTF-8 bytes. The text is what `flows/versions/<hash>.json` keeps."""
    obj = {"flow": text, "briefs": [{"stage": str(b["stage"]), "text": str(b["text"])} for b in briefs]}
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return canon, hashlib.sha256(canon.encode("utf-8")).hexdigest()


PLAIN_STAGE_WORDS = 4  # the most of a stage's name an Ask says (§4.9c)


def ask_words(stage: str, outcome: str, reason: str) -> tuple[str, str]:
    """The Ask and its Context (§4.9c): the Ask one plain sentence from the stage and the outcome alone, the Context
    the session's whole reason. A stage's name is the flow's to choose, so one that is not a few plain words is said
    as *This stage*; the reason never enters the Ask, whose rules (§4.10 rule 1) it could break."""
    said = " ".join(reason.split())
    words = stage.replace("-", " ").split()
    name = " ".join(words) if 0 < len(words) <= PLAIN_STAGE_WORDS and all(w.isalpha() for w in words) else "this stage"
    head = f"{name[0].upper()}{name[1:]} ended as {outcome.replace('-', ' ')}"
    return f"{head}, what next?", (said or f"{head}.")


def answer_move(answers: Mapping[str, Any], label: str) -> tuple[Any, str]:
    """The move the person's lifted `label` makes, by the record's answer map, and the words kept for the next session
    (§4.9c act 2). A form (`Hold: <note>`) matches by its head, whatever the case; any other is *Something else*."""
    if label in answers:
        return answers[label], label
    if ":" in label:
        head = label.split(":", 1)[0].strip().casefold()
        for offered, move in answers.items():
            is_form = offered != OTHER and offered.endswith(">") and ":" in offered
            if is_form and offered.split(":", 1)[0].strip().casefold() == head:
                return move, label
    return answers.get(OTHER), label


class StageStore:
    """The records of the repo whose checkout is at `root`, read from and written to origin's `shiftlead/state`."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def locked(self) -> threading.RLock:
        """The repo's lock, for a caller that reads a record and writes it back as one step (§4.9c: one repo's calls
        are taken one at a time)."""
        return _lock(self.root)

    # -- git ---------------------------------------------------------------------------------------------

    def _git(
        self, *args: str, env: Mapping[str, str] | None = None, stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",  # a flow version's text is kept as its exact UTF-8 bytes, whatever the locale
                timeout=GIT_TIMEOUT,
                check=False,
                input=stdin,
                env={**os.environ, "LC_ALL": "C", **(env or {})},
            )
        except subprocess.TimeoutExpired:
            raise StateError(f"git {args[0]} did not finish in {GIT_TIMEOUT:g} s") from None
        except OSError as e:
            raise StateError(f"git could not be run: {e}") from None

    def _ok(self, *args: str, env: Mapping[str, str] | None = None, stdin: str | None = None) -> str:
        cp = self._git(*args, env=env, stdin=stdin)
        if cp.returncode != 0:
            raise StateError(f"git {args[0]}: {(cp.stderr or cp.stdout).strip()[:200]}")
        return cp.stdout.strip()

    def tip(self) -> str | None:
        """The branch's commit on origin, fetched so its objects are here; None where it does not exist yet."""
        cp = self._git("ls-remote", "--exit-code", "origin", REF)
        if cp.returncode == 2:
            return None
        if cp.returncode != 0:
            raise StateError(f"origin could not be read: {(cp.stderr or '').strip()[:200]}")
        sha = cp.stdout.split()[0]
        if self._git("cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            self._ok("fetch", "-q", "--no-tags", "origin", REF)
        return sha

    def _read(self, tip: str | None, path: str) -> str | None:
        if tip is None:
            return None
        cp = self._git("show", f"{tip}:{path}")
        return cp.stdout if cp.returncode == 0 else None

    def _list(self, tip: str | None, under: str) -> list[str]:
        if tip is None:
            return []
        return [p for p in self._ok("ls-tree", "-r", "--name-only", tip, "--", under).splitlines() if p]

    def write(self, changes: Mapping[str, str | None], message: str) -> str:
        """One commit of `changes` (a path to its text, None removing it) over the branch's tip, pushed: the commit's
        sha, or the tip where nothing changes. Another push landing first is retried on the new tip; a refusal raises
        `StateRefused` and leaves the branch as it was."""
        with _lock(self.root):
            for _ in range(PUSH_TRIES):
                tip = self.tip()
                sha = self._commit(tip, changes, message)
                if sha == tip:
                    return tip
                lease = f"--force-with-lease={REF}:{tip or ''}"
                cp = self._git("push", "-q", "--no-verify", lease, "origin", f"{sha}:{REF}")
                if cp.returncode == 0:
                    return sha
                said = cp.stderr or cp.stdout or ""
                if "stale info" in said or "fetch first" in said or "non-fast-forward" in said:
                    continue
                reason = board._push_refusal(cp)
                if reason is not None:
                    raise StateRefused(reason)
                raise StateError(f"origin could not be reached: {said.strip()[:200]}")
        raise StateError(f"{BRANCH} kept moving through {PUSH_TRIES} pushes")

    def _commit(self, tip: str | None, changes: Mapping[str, str | None], message: str) -> str:
        with tempfile.TemporaryDirectory(prefix="stage-index") as d:
            env = {"GIT_INDEX_FILE": str(Path(d) / "index")}
            if tip:
                self._ok("read-tree", tip, env=env)
            for path, text in changes.items():
                if text is None:
                    self._ok("update-index", "--force-remove", "--", path, env=env)
                    continue
                blob = self._ok("hash-object", "-w", "--stdin", stdin=text)
                self._ok("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
            tree = self._ok("write-tree", env=env)
        if tip and self._ok("rev-parse", f"{tip}^{{tree}}") == tree:
            return tip
        parent = ["-p", tip] if tip else []
        return self._ok(*board._identity(self.root), "commit-tree", tree, *parent, "-m", message)

    def ensure_branch(self) -> str:
        """The branch, created at a team's first start with a README and no other file (§4.4)."""
        return self.tip() or self.write({"README.md": README}, "shiftlead: start the state branch")

    # -- entries -----------------------------------------------------------------------------------------

    @staticmethod
    def _entry_path(tid: str) -> str:
        if not _ID.fullmatch(tid):
            raise ValueError(f"an entry's id is TD-n, not {tid!r}")
        return f"entries/{tid}.json"

    def entry(self, tid: str) -> dict[str, Any] | None:
        text = self._read(self.tip(), self._entry_path(tid))
        return json.loads(text) if text else None

    def entries(self) -> dict[str, dict[str, Any]]:
        """Every record on the branch, read back whole, by entry id."""
        tip = self.tip()
        out: dict[str, dict[str, Any]] = {}
        for path in self._list(tip, "entries"):
            text = self._read(tip, path)
            if text:
                out[Path(path).stem] = json.loads(text)
        return out

    def put_entry(self, record: Mapping[str, Any], why: str, *, also: Mapping[str, str] | None = None) -> str:
        """The record, and `also`'s files (a path to its text) in the same commit."""
        tid = str(record["id"])
        if record.get("waits") not in WAITS:
            raise ValueError(f"a record waits on one of {WAITS}, not {record.get('waits')!r}")
        text = json.dumps(record, indent=1) + "\n"  # in order: the answers are offered as the flow lists them
        return self.write({**(also or {}), self._entry_path(tid): text}, f"shiftlead: {tid} {why}")

    def drop_entry(self, tid: str, why: str) -> str:
        return self.write({self._entry_path(tid): None}, f"shiftlead: {tid} {why}")

    def drop_entries(self, tids: list[str], why: str) -> str:
        """Several records removed in one commit."""
        return self.write({self._entry_path(t): None for t in tids}, f"shiftlead: {why}")

    def move_entry(self, record: Mapping[str, Any], old: str, why: str) -> str:
        """A renumbered entry's record, under its new id, and its old file gone, in one commit."""
        new = str(record["id"])
        text = json.dumps(record, indent=1) + "\n"
        return self.write({self._entry_path(old): None, self._entry_path(new): text}, f"shiftlead: {new} {why}")

    # -- the jobs of the two built-in seats (§4.9d *How each one runs*) ------------------------------------------

    @staticmethod
    def _job_path(key: str) -> str:
        if not JOB_KEY.fullmatch(key):
            raise ValueError(f"a job's key is board-<item id> or pr-<number>, not {key!r}")
        return f"jobs/{key}.json"

    def job(self, key: str) -> dict[str, Any] | None:
        text = self._read(self.tip(), self._job_path(key))
        return json.loads(text) if text else None

    def jobs(self) -> dict[str, dict[str, Any]]:
        """Every job record on the branch, read back whole, by key."""
        tip = self.tip()
        out: dict[str, dict[str, Any]] = {}
        for path in self._list(tip, "jobs"):
            if (text := self._read(tip, path)) and JOB_KEY.fullmatch(Path(path).stem):
                out[Path(path).stem] = json.loads(text)
        return out

    def put_job(self, record: Mapping[str, Any], why: str) -> str:
        """A job's record, written over a closed one of the same key (an object that came back is a new job)."""
        key = str(record["id"])
        if record.get("waits") not in WAITS:
            raise ValueError(f"a record waits on one of {WAITS}, not {record.get('waits')!r}")
        text = json.dumps(record, indent=1) + "\n"
        return self.write({self._job_path(key): text}, f"shiftlead: {key} {why}")

    # -- audits and the team's last good flow ---------------------------------------------------------------

    @staticmethod
    def _named(kind: str, name: str) -> str:
        if not _NAME.fullmatch(name):
            raise ValueError(f"a {kind} name is letters, digits, dots, dashes and underscores, not {name!r}")
        return name

    def audit(self, team: str, name: str) -> dict[str, Any] | None:
        path = f"audits/{self._named('team', team)}/{self._named('audit', name)}.json"
        text = self._read(self.tip(), path)
        return json.loads(text) if text else None

    def put_audit(self, team: str, name: str, run: Mapping[str, Any]) -> str:
        """The audit's run record: the store alone (what a run writes here, its lease and its count are TD-2053's)."""
        path = f"audits/{self._named('team', team)}/{self._named('audit', name)}.json"
        return self.write({path: json.dumps(run, indent=1, sort_keys=True) + "\n"}, f"shiftlead: audit {team}/{name}")

    def flow(self, team: str) -> str | None:
        return self._read(self.tip(), f"flows/{self._named('team', team)}.yml")

    def put_flow(self, team: str, text: str) -> str:
        """The copy of the flow `team`'s records are written under; the caller has passed it through the check."""
        return self.write({f"flows/{self._named('team', team)}.yml": text}, f"shiftlead: last good flow of {team}")

    @staticmethod
    def version_path(flow_hash: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", flow_hash):
            raise ValueError(f"a flow version is named by its SHA-256 in hex, not {flow_hash!r}")
        return f"{VERSIONS}/{flow_hash}.json"

    def version(self, flow_hash: str) -> str | None:
        """The text a flow version hashed to, as its offer kept it, or None where the branch keeps none."""
        return self._read(self.tip(), self.version_path(flow_hash))

    def drop_flow(self, team: str) -> None:
        """The team's copy of its flow gone, at its Delete (§4.9d *Delete*); no branch or no copy writes nothing."""
        if self.flow(team) is not None:
            self.write({f"flows/{self._named('team', team)}.yml": None}, f"shiftlead: {team} deleted")

    # -- a move to the person --------------------------------------------------------------------------------

    def record_intent(
        self,
        tid: str,
        person: str,
        ask: str,
        context: str,
        answers: Mapping[str, Any],
        *,
        blocked: Any = None,
        base: dict[str, Any] | None = None,
        after_merge: bool = False,
    ) -> dict[str, Any]:
        """The first of the move's three writes: that the entry is to go to the person, with the answer map (each
        offered `<label> — <consequence>` to the move it makes) and what was `blocked`. Returns at once; the tick
        lands it. *Something else* is always offered, its move the record's default. `base` is the record as a caller
        holding the lock has already changed it, so the move and its intent are one commit.
        `after_merge`: the question is asked knowing the pull request has merged, so that merge does not make its
        answer one applied to nothing."""
        record = base if base is not None else self.entry(tid)
        if record is None:
            raise StateError(f"{tid} has no stage record")
        offered = {str(k): v for k, v in answers.items()}
        offered.setdefault(OTHER_ANSWER, None)
        record["intent"] = {
            "person": person,
            "ask": ask,
            "context": context,
            "answers": offered,
            "at": _now(),
            "nonce": uuid.uuid4().hex[:12],  # names this question in the entry's Log, so it is never landed twice
            "after_merge": after_merge,
        }
        record["blocked"] = blocked
        self.put_entry(record, "to the person: intent")
        return record

    def intents(self) -> list[str]:
        """The entries with a question recorded and not yet landed, for reconcile."""
        return sorted(tid for tid, r in self.entries().items() if r.get("intent"))

    def archive(self, tid: str, why: str) -> dict[str, Any]:
        """The home archives the entry in a pull request of its own (§4.9c *Who archives the entry*). The record is not
        touched: it closes when the ledger on the default branch reads the entry archived."""
        return board.archive_entry(self.root, tid, why)

    def note_unapplied(self, tid: str, label: str, mark: str) -> dict[str, Any]:
        """The pull request saying on the entry's Log that the person's answer moved nothing (§4.9c act 2). The record
        is not touched: its caller clears the question once this returns."""
        return board.note_unapplied(self.root, tid, label, mark)

    def clear_question(self, tid: str, person: str, nonce: str, why: str = board.MOVED_WHY) -> dict[str, Any]:
        """The pull request clearing the question this record set on its entry: one moved to another team, or a live
        check's whose pull request merged (§4.9c). The record is not touched: its caller closes it once this returns."""
        return board.clear_question(self.root, tid, person, nonce, why)

    def land_intent(self, tid: str) -> dict[str, Any]:
        """The second and third writes: the one pull request, then the record's wait. Run again after a crash it
        writes nothing twice. An entry gone meanwhile clears the intent, and the reply says `gone`."""
        record = self.entry(tid)
        if record is None:
            raise StateError(f"{tid} has no stage record")
        intent = record.get("intent")
        if not intent:
            return {"nothing": True}
        offered = list(intent["answers"])
        labels = [a.split(" — ", 1)[0] for a in offered]
        got = board.ask_on_entry(
            self.root,
            tid,
            intent["person"],
            intent["ask"],
            intent["context"],
            offered,
            labels,
            nonce=intent["nonce"],
        )
        record["intent"] = None
        if got.get("gone"):
            self.put_entry(record, "to the person: the entry is gone")
            return got
        record["waits"] = "person"
        record["answers"] = {a.split(" — ", 1)[0]: move for a, move in intent["answers"].items()}
        record["asked"] = {
            **{k: intent[k] for k in ("nonce", "ask", "context", "answers")},
            "at": intent.get("at"),
            "after_merge": bool(intent.get("after_merge")),
        }
        self.put_entry(record, "waits on the person")
        return got


HOME = "home"  # the `by` of a row the home writes (§4.9c)
SESSION_FIELDS = ("model", "tool", "tool_version", "login", "login_moves", "created", "person_asks")
"""What a row's `run` copies from the holder's session record (§4.9c *Each holder leaves a `run`*), as the host agent
hands it: `tool` the record's adapter, `created` its `started`, `person_asks` its `asks`."""


def session_fields(s: Any) -> dict[str, Any]:
    """`SESSION_FIELDS` from a session record (`sessionorc.models.Session`), as the host agent hands them to
    `ao stage end`'s row: what the home's own rows copy from the holder's record, a node's session's as mirrored."""
    return {
        "model": getattr(s, "model", None),
        "tool": getattr(s, "adapter", None),
        "tool_version": getattr(s, "tool_version", None),
        "login": getattr(s, "login", None),
        "login_moves": getattr(s, "login_moves", None),
        "created": getattr(s, "created", None),
        "person_asks": getattr(s, "person_asks", None),
    }


HOME_ROWS = ("lost", "ended", "ask")
"""The outcomes of the rows the home writes as it ends a holder or asks the person, which move nothing (§4.9c)."""


def bare(holder: Any) -> str:
    """A holder's session id as `seat_spend.json` keys it: the home's `<id>@<node>` without its `@<node>`."""
    return str(holder).split("@", 1)[0]


def spend_since(now: Any, before: Any) -> dict[str, Any] | None:
    """`run.models` (§4.9c): per model `now` less `before`, each a reading of `seats.record_reading`'s `models`, each
    figure apart by unit and rounded to 4 places. None where either is not a reading, where a model, field or unit of
    `before` is absent from `now`, or where any difference is below zero: the run's spend unknown, never guessed."""
    try:
        return _since(now, before)
    except (TypeError, ValueError):  # a stored value edited by hand into no number: unknown, never a failed end
        return None


def _since(now: Any, before: Any) -> dict[str, Any] | None:
    if not isinstance(now, Mapping) or not isinstance(before, Mapping):
        return None
    if any(name not in now for name in before):
        return None
    out: dict[str, Any] = {}
    for name, n in now.items():
        b = before.get(name) or {}
        if not isinstance(n, Mapping) or not isinstance(b, Mapping):
            return None
        row: dict[str, Any] = {}
        for k in {*n, *b} - {"figure"}:
            if k not in n:
                return None
            d = int(n.get(k) or 0) - int(b.get(k) or 0)
            if d < 0:
                return None
            row[k] = d
        nf, bf = n.get("figure") or {}, b.get("figure") or {}
        if not isinstance(nf, Mapping) or not isinstance(bf, Mapping) or any(u not in nf for u in bf):
            return None
        figure = {u: round(float(f) - float(bf.get(u) or 0.0), 4) for u, f in nf.items()}
        if any(f < 0 for f in figure.values()):
            return None
        out[str(name)] = {**dict(sorted(row.items())), "figure": figure}
    return out


def run_of(
    record: Mapping[str, Any], holder: Any, session: Mapping[str, Any] | None, now: Any, *, ended: str | None = None
) -> dict[str, Any]:
    """The `run` a row that ends `holder` carries (§4.9c *Each holder leaves a `run`*): `session` the holder's
    session record's fields (`SESSION_FIELDS`), None where it is forgotten, which leaves `null` what it supplies;
    `now` that id's `models` reading at this moment, None where it could not be read. `team`, `flow` and `flow_hash`
    are the record's as it stands, and `spent_before` the id's sums at its offer, which `models` is taken less."""
    sid = bare(holder)
    before = (record.get("spent_before") or {}).get(sid)
    s = session or {}
    return {
        "session": sid,
        "team": record.get("team"),
        "flow": record.get("flow"),
        "model": s.get("model"),
        "tool": s.get("tool"),
        "tool_version": s.get("tool_version"),
        "login": s.get("login"),
        "login_moves": s.get("login_moves"),
        "started": s.get("created"),
        "ended": ended or _now(),
        "models": spend_since(now, before) if before is not None else None,
        "spent_before": before,
        "asks": s.get("person_asks"),
        "flow_hash": record.get("flow_hash"),
    }


def where_now(record: Mapping[str, Any]) -> str:
    """Where an entry is now, in the words `ao stage end` answers with (§4.9c, §4.7): `done` for a closed record,
    `person` where it waits on the person, `merge` where it waits `merging` or for its `parts`, else its stage."""
    if record.get("closed_at"):
        return "done"
    if record.get("waits") == "person":
        return "person"
    if record.get("waits") in ("merging", "parts"):
        return "merge"
    return str(record.get("stage"))
