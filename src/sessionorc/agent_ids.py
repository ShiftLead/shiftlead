"""A ledger entry's id is handed out by the home (design §4.4 *A ledger entry's id is handed out by the home*,
TD-693, built by TD-696; TD-970, TD-971): `td_next` is a front end over the synced id script, which takes the next
free id of a registered repo, or `count` of them in a row, from origin's counter, floored by the last id the home
gave — under one lock per repo, so two sessions asking at once get different ids. A checkout without the script is
refused, naming the sync. What it gave is kept in `ids.json`. A mixin `HostAgent` inherits.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import os
import re
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from sessionorc import cadence, hosts, ledgerboard, mail, paths
from sessionorc import ledger as ledger_mod
from sessionorc import seams as seams_mod
from sessionorc.agent_common import RpcError, log
from sessionorc.models import PERSON, now_iso
from sessionorc.store import _atomic_write

BUDGET = 45.0  # seconds from the call's arrival to its answer, the lock's wait included
LOCK_BY = 30.0  # a lock not taken this far in refuses: *busy, ask again*
GIVEN_KEEP = 200
COUNT_MAX = 10
LAST_TAKE = "last"  # `ao td reserve --show last`: the caller's newest take (TD-1484)
# the start of the id script's filing question (agent-cadence TD-204): its stderr's last line where the repo sets
# `review-outcomes` on; parity with its `FILING_QUESTION` (cadence.md §7.9)
FILING_QUESTION = "ledger_next_id: if this entry is a defect, did a design miss it?"
SCRIPTS = ("scripts/ledger_next_id.py", "files/scripts/ledger_next_id.py")  # a syncing repo's; agent-cadence's own
IDS_SCRIPT = "ledger_next_id.py"  # as a pinned tree's `files/scripts/` holds it
SYNCED = "232f2ad"  # the agent-cadence release that ships the id script (TD-970); a checkout before it is refused
SCRIPT_SLACK = 5.0  # the script's race ends this far before the call's deadline
TID = re.compile(r"TD-\d+")
GITHUB = re.compile(
    r"^(?:https?://(?:[^@/]+@)?|ssh://(?:[^@/]+@)?|[^@/]+@)github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$"
)


def origin_key(url: str) -> str:
    """The key a repo's counter and lock are kept under: `owner/repo` for a GitHub origin, ssh or https
    alike, else the lowercased URL, so two clones of one repo share one counter."""
    u = url.strip()
    if m := GITHUB.match(u):
        return f"{m.group(1)}/{m.group(2)}".lower()
    return u.lower().removesuffix("/").removesuffix(".git")


def layout(root: str, rel: str) -> tuple[str, str | None, bool]:
    """`(ledger, archive, directory?)` of the checkout's working tree, through `ledger.layout_at`, so a set
    `ledger:` gone from the tree reads the other layout beside it (§4.4 *Either layout*); where neither is
    there, the path as given, as before the split."""
    io = ledger_mod.fs_io(root)
    arch = ledger_mod.archive_path(rel) if rel.endswith(".md") else None
    led, arel = ledger_mod.layout_at(rel, arch, io)
    if io[0](led) is None and io[1](led) is None:
        led, arel = rel, arch
    return led, arel, io[0](led) is not None


async def _run(
    argv: list[str], cwd: str | None, timeout: float, env: dict[str, str] | None = None, group: bool = False
) -> tuple[int, str, str]:
    """A subprocess off the event loop, killed at its deadline (or when the call is cancelled).
    `(returncode, stdout, stderr)`; a deadline passed is `(-1, "", "timed out")`. With `group` it starts in
    its own session and the kill goes to its process group, so a `git` it runs dies with it."""
    if timeout <= 0:
        return -1, "", "timed out"
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, env=env, start_new_session=group,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )  # fmt: skip
    except OSError as e:
        return -1, "", f"{argv[0]} could not be run: {type(e).__name__}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except (TimeoutError, asyncio.CancelledError) as e:
        with contextlib.suppress(ProcessLookupError):
            if group:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        with contextlib.suppress(Exception):
            await asyncio.shield(proc.wait())
        if isinstance(e, asyncio.CancelledError):
            raise
        return -1, "", "timed out"
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def ids_script(root: str, timeout: float = cadence.TREE_TIMEOUT) -> Path | None:
    """The `ledger_next_id.py` the checkout serving a `td_next` has: in a pinned repo the pinned tree's (§5 *How
    the readers find agent-cadence*, TD-1014) — a pin that does not resolve, or a tree with no id script, refused,
    else the first of `SCRIPTS` found, None where the checkout has none (its call is refused, naming the sync)."""
    if cadence.pinned(root):
        payload, why = cadence.tree(root, timeout)
        if payload is None:
            raise RpcError(f"{Path(root).name}'s agent-cadence pin did not resolve ({why}): no id script to run")
        if not (script := payload / "scripts" / IDS_SCRIPT).is_file():
            raise RpcError(f"{Path(root).name}'s pinned agent-cadence has no {IDS_SCRIPT}: bump the pin")
        return script
    return next((Path(root) / s for s in SCRIPTS if (Path(root) / s).is_file()), None)


def id_take_line(script: Path, root: str, rel: str, id_take: str | None) -> str | None:
    """`**Id take:** <nonce>`, the line each new entry carries once the script answers `id_take` (agent-cadence
    TD-188's step 3, design §4.4 *Its answer*, TD-1363), or None where `id_take` is null or the ledger does not
    accept the field: `id take` is in the `CADENCE_FIELDS` of the ledgerboard beside the script run — its
    package's `ledgerboard/__init__.py` (v2.3 on, TD-1330), else a single `ledgerboard.py`, read as a literal,
    never imported — or else the ledger declares no field vocabulary, by the vendored `declared()`, of a directory
    its `README.md`'s preamble as `load()` heads its text (TD-1145). A cadence field since ledgerboard v2.2, so
    written in a ledger that declares a vocabulary too. A missing or non-literal sibling, or a ledger that cannot be
    read (a faulted v2 ledger among them), gives None. No `**Taken by:**` line is given (TD-1360): the pinned
    gate reads `Id take` alone (agent-cadence TD-188's step 4)."""
    return _field_line(script, root, rel, "Id take", id_take)


def _field_line(script: Path, root: str, rel: str, field: str, value: str | None) -> str | None:
    """`**<field>:** <value>` where the ledger beside `script` accepts the field (`id_take_line`'s test), else None."""
    if not value:
        return None
    package = script.parent / "ledgerboard" / "__init__.py"
    fields = _cadence_fields(package if package.is_file() else script.parent / "ledgerboard.py")
    if fields is None:
        return None
    if field.lower() not in fields:
        text = ledger_mod.read_pair(rel, ledger_mod.fs_io(root))[1]
        if text is None or ledgerboard.declared(text)[0]:
            return None
    return f"**{field}:** {value}"


def _cadence_fields(path: Path) -> tuple[str, ...] | None:
    """`CADENCE_FIELDS` of a ledgerboard module file, as a literal tuple of strings, or None."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, SyntaxError):
        return None
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "CADENCE_FIELDS" and node.value is not None:
            try:
                got = ast.literal_eval(node.value)
            except ValueError:
                return None
            ok = isinstance(got, tuple) and all(isinstance(f, str) for f in got)
            return got if ok else None
    return None


async def check_branch(branch: str, timeout: float) -> None:
    """Refuse a `branch` git would not take as a branch name, one whose printed form differs (`@{-1}`
    expands), and `@` (design §4.4 *The branch*), run outside any repository."""
    rc, out, err = await _run(["git", "check-ref-format", "--branch", branch], "/", timeout)
    if (rc, out, err) == (-1, "", "timed out"):
        raise RpcError("the branch could not be checked in time: busy, ask again")
    if rc != 0 or out.strip() != branch or branch == "@":
        raise RpcError(f"branch {branch!r} is not a branch name (git check-ref-format --branch): send none or a name")


def _takes_branch(script: Path) -> bool:
    try:
        return '"--branch"' in script.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False


def settle_key(root: str, remote: str) -> str:
    """The settle clock's key for a checkout: its origin as `ids.json` keys it, its path where it has none."""
    return origin_key(remote) if remote else str(root)


_UNQUOTABLE = re.compile(r'["`$\\]')


class IdsMixin:
    def _presser_words(self, by: str) -> str:
        """A caller in words (`mail.presser_words`), read from the one graph now: the road's *closed by …*."""
        return mail.presser_words(by, self._graph())

    async def _tell_holders(self, tid: str, tell: str) -> tuple[list[str], list[str], list[str]]:
        """The tell, `_ledger_road`'s first step (design §4.4 *The tell*, TD-905, TD-1297): a `note` from the
        person, `about` the id, to each **unattended** live holder of a declared lease (`_lease_holders`),
        saying the entry `<tell>` (the road's words) and asking it to drop the entry with them as its
        `--why`, and a second to each seat whose inbox holds an open `ask` carrying a PR one of those holders'
        claims names (`pr` or `review_pr`) — once a seat, the person never, being no record. A note that
        cannot be sent is a line of `untold`. Returns `(told, readers, untold)`: every name mailed, the
        readers among them, and the lines not sent."""
        graph = self._graph()
        holders: list[str] = []
        prs: set[int] = set()
        for addr in self._lease_holders(tid):
            r = graph.get(addr)
            if r is None or not r.unattended:
                continue  # an interactive holder is the person's own, and is told nothing
            holders.append(addr)
            for p in r.progress:
                if p.ref == tid and p.status == "claimed" and p.source == "declared" and (p.pr or p.review_pr):
                    prs.add(int(p.pr or p.review_pr))
        seats: dict[str, int] = {}
        for addr, r in graph.items():
            if r.state in ("exited", "closed", "scheduled") or addr in holders:
                continue  # a holder is told to drop the entry already, which leaves its PR unmerged
            for a in (r.prs_waiting(home=self.host) or {}).get("asks") or ():
                if a.get("pr") in prs:
                    seats[addr] = int(a["pr"])
                    break
        told: list[str] = []
        readers: list[str] = []
        untold: list[str] = []

        async def tell_(to: str, text: str) -> bool:
            try:
                await self._msg(PERSON, text, [to], "note", tid, None, None, None)
            except RpcError as e:
                untold.append(f"could not tell {to}: {e}")
                return False
            told.append(to)
            return True

        said = f"{tid} {tell}"
        # the notice's words, without what would break or run inside the quoted `--why` (review of #2564)
        drop = _UNQUOTABLE.sub("", tell.removeprefix("is "))
        for addr in holders:
            await tell_(
                addr,
                f"{said}: stop at the step in hand, push, leave its PR open and unmerged, and drop the entry: "
                f'`ao progress drop {tid} --why "{drop}"`.',
            )
        for addr, pr in seats.items():
            if await tell_(addr, f"{said}: leave PR #{pr} unmerged."):
                readers.append(addr)
        return told, readers, untold

    async def rpc_td_next(self, repo: str = "", count: int = 1, branch: str = "", caller: Any = None) -> dict[str, Any]:
        """`ao td reserve` (design §4.4 *A ledger entry's id is handed out by the home*, §4.7 *Entries*): the next
        `count` free ids of the repo named `repo` — its registered name, or its origin's `owner/repo` — and the
        record of who was given them. `by` is the dispatcher's caller, never a parameter. Returns `{repo,
        origin, ids, unread}`, `unread` the lines naming the open PRs that
        could not be read, and `reserved`, `why`, `warnings` and `taken_by` the script's, `id_take` the take's
        nonce and `id_take_line` the header line to write where the ledger accepts it, and `question` the script's
        filing question where the repo sets `review-outcomes` on (§4.4 *The filing question*, TD-1282), else null.
        `branch` is the caller's directory's (§4.4 *The branch*), checked and passed to a script that takes it. A
        checkout with no id script is refused, naming the sync (TD-971): the home has no road of its own."""
        start = time.monotonic()
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= COUNT_MAX:
            raise RpcError(f"--count is 1 to {COUNT_MAX}, not {count!r}")
        branch = branch if isinstance(branch, str) else ""
        if branch:
            await check_branch(branch, start + LOCK_BY - time.monotonic())
        root, key, name = await self._ids_repo(str(repo or "").strip(), start + LOCK_BY)
        lock = self._ids_locks.setdefault(key, asyncio.Lock())
        try:
            await asyncio.wait_for(lock.acquire(), max(0.0, start + LOCK_BY - time.monotonic()))
        except TimeoutError:
            raise RpcError(f"{name}'s ids are being handed out to another caller: busy, ask again") from None
        try:
            left = max(0.1, start + BUDGET - time.monotonic())
            if not (script := await asyncio.to_thread(ids_script, root, left)):
                raise RpcError(f"no {SCRIPTS[0]} in {name}: sync agent-cadence to {SYNCED} or later")
            got = await self._ids_script(root, key, name, script, count, start, caller, branch)
        finally:
            lock.release()
        for line in [*got["unread"], *got["warnings"]] + ([] if got["reserved"] else [f"not reserved: {got['why']}"]):
            log.info("td_next %s: %s", name, line)
        return {"repo": name, "origin": key, **got}

    async def rpc_td_take(self, repo: str = "", take: str = "", caller: Any = None) -> dict[str, Any]:
        """`ao td reserve --show <take>` (design §4.4 *The record*, §4.7 *Entries*; TD-1484): the ids one call
        already gave for the repo, read from `ids.json` again, spending nothing — the call whose take's nonce is
        `take`, or, for `last`, the newest call given to the caller (`by` as `td_next` reads it). Returns `{repo,
        origin, ids, by, at, id_take, id_take_line}`; refused where the record no longer holds the take."""
        start = time.monotonic()
        take = str(take or "").strip()
        if not take or not re.fullmatch(r"[\w-]{1,128}", take):
            raise RpcError(f"name the take: its id_take, or {LAST_TAKE!r} for your newest")
        root, key, name = await self._ids_repo(str(repo or "").strip(), start + LOCK_BY)
        by = PERSON if caller is None or mail.is_person(caller) else str(caller)
        got = await asyncio.to_thread(given_take, key, take, by)
        if not got:
            whose = f"no take given to {by}" if take == LAST_TAKE else f"no take {take}"
            raise RpcError(f"{name}: {whose} in the home's record, which keeps the newest {GIVEN_KEEP} ids")
        id_take = got[-1].get("take") if isinstance(got[-1].get("take"), str) else None
        take_line = None
        left = max(0.1, start + BUDGET - time.monotonic())
        if id_take and (script := await asyncio.to_thread(ids_script, root, left)):
            rel = await asyncio.to_thread(ledger_mod.ledger_path, root)
            led = (await asyncio.to_thread(layout, root, rel))[0]
            take_line = await asyncio.to_thread(id_take_line, script, root, led, id_take)
        return {
            "repo": name,
            "origin": key,
            "ids": [str(g.get("id")) for g in got],
            "by": got[-1].get("by"),
            "at": got[-1].get("at"),
            "id_take": id_take,
            "id_take_line": take_line,
        }

    async def _ids_repo(self, want: str, by: float) -> tuple[str, str, str]:
        """`(root, origin key, name)` for a registered name or an `owner/repo`. A name registered checkouts
        of different origins share is refused, naming them; checkouts of one origin are one repo, so the
        first of them serves."""
        if not want:
            raise RpcError("name the repo: its registered name, or its origin's owner/repo")
        roots = [str(r) for r in hosts.local_host().repos()]

        async def key_of(root: str) -> str:
            rc, out, err = await _run(["git", "-C", root, "remote", "get-url", "origin"], None, by - time.monotonic())
            if rc == 0 and out.strip():
                return origin_key(out)
            if err == "timed out":
                raise RpcError(f"{root}'s origin could not be read in time: busy, ask again")
            return ""

        if "/" in want and not want.startswith(("/", "~", ".")):
            wanted = origin_key(want) if "github.com" in want else want.lower()
            for root in roots:
                if (k := await key_of(root)) and k == wanted:
                    return root, k, Path(root).name
            raise RpcError(f"no registered checkout has the origin {want!r} (the home's registry lists {len(roots)})")
        found = [r for r in roots if Path(r).expanduser().name == want or r == want]
        if not found:
            raise RpcError(f"no registered repo is {want!r} (the home's registry lists {len(roots)})")
        keys = {r: await key_of(r) for r in found}
        if not any(keys.values()):
            raise RpcError(f"{want} has no origin remote: there is no main to read ids from")
        if len({k for k in keys.values() if k}) > 1:
            named = ", ".join(f"{r} ({k or 'no origin'})" for r, k in keys.items())
            raise RpcError(f"{want!r} names checkouts of different origins: {named}; name one by its owner/repo")
        root = next(r for r, k in keys.items() if k)
        return root, keys[root], Path(root).name

    async def _ids_script(
        self, root: str, key: str, name: str, script: Path, count: int, start: float, caller: Any, branch: str = ""
    ) -> dict[str, Any]:
        """The road over origin's counter (design §4.4 *A ledger entry's id is handed out by the home*, TD-970): the
        synced script, run in the checkout with this interpreter — a pinned repo's through the resolver (TD-1014) —
        the home's last given as its `--floor`, and killed with its group at the call's deadline. It fetches and
        reads what it needs; the home reads no PR here. `branch` goes as one `--branch=<name>` only to a script
        whose source declares `"--branch"` (dev-cadence TD-145); one from before has none, and argparse would
        refuse the take. A v2 directory goes as `--ledger <dir>` with no `--archive` (TD-1145), and only to a tree
        that reads one (`_ids_v2_served`)."""
        rel = await asyncio.to_thread(ledger_mod.ledger_path, root)
        led, arel, directory = await asyncio.to_thread(layout, root, rel)
        if directory:
            await self._ids_v2_served(root, name)
        by = PERSON if caller is None or mail.is_person(caller) else str(caller)
        floor = await asyncio.to_thread(_last, key)
        left = start + BUDGET - time.monotonic()
        args = [
            "--count", str(count), "--by", by, "--floor", str(floor), "--ledger", led,
            *([] if directory else ["--archive", arel or ledger_mod.archive_path(led)]), "--json",
        ]  # fmt: skip
        if branch and await asyncio.to_thread(_takes_branch, script):
            args.append(f"--branch={branch}")
        if script.is_relative_to(root):
            argv, env, said = [sys.executable, str(script), *args], dict(os.environ), str(script.relative_to(root))
        else:  # the pinned tree's, which the launcher runs by its name
            (argv, env), said = cadence.command(root, "run", script.name, *args), f"the pinned tree's {script.name}"
        env["LEDGER_IDS_RACE_SECONDS"] = f"{max(1.0, left - SCRIPT_SLACK):g}"
        rc, out, err = await _run(argv, root, left, env=env, group=True)
        if (rc, out, err) == (-1, "", "timed out"):
            raise RpcError(f"{name}'s id script did not answer within the call's {BUDGET:g} s: budget, ask again")
        try:
            res = json.loads(out)
        except ValueError:
            res = None
        ok = (
            isinstance(res, dict)
            and isinstance(res.get("ids"), list)
            and all(isinstance(i, str) and TID.fullmatch(i) for i in res["ids"])
        )
        if not ok or rc not in (0, 2, 3) or (rc != 2 and not res["ids"]):
            first = ((err or "").strip().splitlines() or ["nothing on standard error"])[0][:200]
            raise RpcError(f"{said} did not answer with its JSON (exit {rc}): {first}")
        why = " ".join(str(res.get("why") or "").split())[:200]
        if rc == 2:
            raise RpcError(f"{name}'s ids were not given: {why or 'the script refused'}")
        ids = [str(i) for i in res["ids"]]
        id_take = res.get("id_take") if isinstance(res.get("id_take"), str) and res["id_take"] else None
        await asyncio.to_thread(_record_given, key, ids, by, id_take)
        refs = [str(r) for r in res.get("unread") or [] if str(r).strip()]
        taken_by = res.get("taken_by") if isinstance(res.get("taken_by"), str) and res["taken_by"] else None
        take_line = await asyncio.to_thread(id_take_line, script, root, led, id_take)
        last = ((err or "").strip().splitlines() or [""])[-1].strip()
        question = last if last.startswith(FILING_QUESTION) else None  # review-outcomes on: the script asked
        return {
            "ids": ids,
            "unread": [f"open PRs not read: {', '.join(refs)}"] if refs else [],
            "reserved": rc == 0,
            "why": "" if rc == 0 else why,
            "warnings": [str(w) for w in res.get("warnings") or [] if str(w).strip()],
            "taken_by": taken_by,
            "id_take": id_take,
            "id_take_line": take_line,
            "question": question,
        }

    async def _ids_v2_served(self, root: str, name: str) -> None:
        """Refuse a v2 directory where agent-cadence's tree is older than `cadence.OLDEST_V2` (design §4.4 *Either
        layout*), in the seams' *unserved* words (§5), never handing the script a directory: the age as the
        repo's last seams reading holds it, read again (carried where its commits are the same) against the
        home's checkouts. An age that cannot be read refuses nothing: an old script fails on its own."""
        old = ((self._repos.get(root) or {}).get("seams") or {}).get("cadence_age")
        roster = [str(r) for r in hosts.local_host().repos()]
        got = await asyncio.to_thread(seams_mod.age, root, roster, old if isinstance(old, dict) else None, True)
        if got is not None and False in (got.get("descends"), got.get("descends_v2")):
            led = {"state": "predates", "why": seams_mod.predates_v2(str(got["commit"]))}
            raise RpcError(f"{name}'s ids were not given: {seams_mod.ledger_lack(led, root)}")


_STORE = threading.Lock()  # `ids.json` is one file for every origin, and each origin has its own lock


def _last(key: str) -> int:
    """The last id the home gave for the origin, 0 where it gave none: the script road's `--floor`."""
    with _STORE:
        rec = _load().get(key)
    return rec["last"] if isinstance(rec, dict) and isinstance(rec.get("last"), int) else 0


def _record_given(key: str, ids: list[str], by: str, take: str | None = None) -> None:
    """Record ids the script gave, as they are: appended to `given` with the call's mark and the take's nonce
    where the script answered one (TD-1484), `last` moved to the highest of them."""
    with _STORE:
        store = _load()
        rec = store.get(key) if isinstance(store.get(key), dict) else {}
        last = rec.get("last") if isinstance(rec.get("last"), int) else 0
        at = now_iso()
        given = [g for g in rec.get("given") or [] if isinstance(g, dict)]
        call = uuid.uuid4().hex[:12]
        given += [{"id": i, "by": by, "at": at, "call": call} | ({"take": take} if take else {}) for i in ids]
        store[key] = {"last": max([last, *(int(i[3:]) for i in ids)]), "given": given[-GIVEN_KEEP:]}
        _save(store)


def given_of(key: str) -> list[dict[str, Any]]:
    """The origin's `given` records as `ids.json` holds them (the newest `GIVEN_KEEP`), none where it holds none."""
    with _STORE:
        rec = _load().get(key)
    return [g for g in (rec.get("given") if isinstance(rec, dict) else None) or [] if isinstance(g, dict)]


def given_take(key: str, take: str, by: str) -> list[dict[str, Any]]:
    """The records of one call the home gave for the origin (`ids.json`'s `given`, TD-1484): those of the newest call
    whose `take` is `take`, or, where `take` is `last`, the newest call given to `by`; none where the record no longer
    holds it."""
    with _STORE:
        rec = _load().get(key)
    given = [g for g in (rec.get("given") if isinstance(rec, dict) else None) or [] if isinstance(g, dict)]
    if take == LAST_TAKE:
        mine = [g for g in given if g.get("by") == by]
        if not mine:
            return []
        newest = mine[-1]
        same = ("call", "take") if newest.get("call") else ("at", "take")  # a record from before the mark: its second
        return [g for g in mine if all(g.get(k) == newest.get(k) for k in same)]
    named = [g for g in given if g.get("take") == take]
    if not named:
        return []
    newest = named[-1]  # a nonce a script gave twice names its newest call alone (review of #3096)
    return [g for g in named if g.get("call") == newest.get("call")]


def _load() -> dict[str, Any]:
    try:
        raw = json.loads(paths.ids_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(store: dict[str, Any]) -> None:
    paths.ids_file().parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(paths.ids_file(), json.dumps(store, indent=1, sort_keys=True))
