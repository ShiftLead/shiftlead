"""A ledger entry's id is handed out by the home (design §4.4 *A ledger entry's id is handed out by the home*,
TD-693, built by TD-696): `td_next` gives the next free id of a registered repo, or `count` of them in a row,
above the highest of every open PR's added headings, the ledger and its archive on a freshly fetched
`origin/<default>`, and the last id the home gave — under one lock per repo, so two sessions asking at once
get different ids. What it gave is kept in `ids.json`. A mixin `HostAgent` inherits.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sessionorc import agent_common, cadence, hosts, mail, paths
from sessionorc import ledger as ledger_mod
from sessionorc import settle as settle_mod
from sessionorc.agent_common import RpcError, log
from sessionorc.models import PERSON, now_iso
from sessionorc.store import _atomic_write

BUDGET = 45.0  # seconds from the call's arrival to its answer, the lock's wait included
LOCK_BY = 30.0  # a lock not taken this far in refuses: *busy, ask again*
PRS_BY = 30.0  # a PR not read this far in is unread: *budget*
PR_LIMIT = 200  # `gh pr list --limit`: a list that fills it is one unread line
FILES_CAP = 3000  # GitHub lists at most this many files of a PR: a listing that reaches it is cut
PR_READERS = 4  # PRs read at once
GIVEN_KEEP = 200
COUNT_MAX = 10
WHY_CHARS = 200  # a hold's words and a drop notice's, one line (TD-905)
ADDED = re.compile(r"^\+## TD-(\d+):", re.M)
SCRIPTS = ("scripts/ledger_next_id.py", "files/scripts/ledger_next_id.py")  # a syncing repo's; dev-cadence's own
IDS_SCRIPT = "ledger_next_id.py"  # as a pinned tree's `files/scripts/` holds it
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


def is_github(key: str) -> bool:
    return re.fullmatch(r"[^/:@\s]+/[^/:@\s]+", key) is not None


def added_ids(patch: str | None) -> set[int]:
    """The ids a patch adds a `## TD-NNN:` heading for."""
    return {int(n) for n in ADDED.findall(patch or "")}


def files_jq(paths_: tuple[str, ...]) -> str:
    """One line per file of a PR's listing: the patch of a ledger file as `{f, p}` (`p` null where GitHub
    left it out), any other file as `0`, so the lines also count the listing."""
    names = " or ".join(f".filename == {json.dumps(p)}" for p in paths_)
    return f".[] | if ({names}) then {{f: .filename, p: .patch}} else 0 end"


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


def _why(err: str, fallback: str) -> str:
    return ((err or "").strip().splitlines() or [fallback])[-1][:200]


def ids_script(root: str, timeout: float = cadence.TREE_TIMEOUT) -> Path | None:
    """The `ledger_next_id.py` the checkout serving a `td_next` has: in a pinned repo the pinned tree's (§5 *How
    the readers find dev-cadence*, TD-1014) — a pin that does not resolve, or a tree with no id script, refused,
    never the home's own road, which reads no counter; else the first of `SCRIPTS` found."""
    if cadence.pinned(root):
        payload, why = cadence.tree(root, timeout)
        if payload is None:
            raise RpcError(f"{Path(root).name}'s dev-cadence pin did not resolve ({why}): no id script to run")
        if not (script := payload / "scripts" / IDS_SCRIPT).is_file():
            raise RpcError(f"{Path(root).name}'s pinned dev-cadence has no {IDS_SCRIPT}: bump the pin")
        return script
    return next((Path(root) / s for s in SCRIPTS if (Path(root) / s).is_file()), None)


def settle_key(root: str, remote: str) -> str:
    """The settle clock's key for a checkout: its origin as `ids.json` keys it, its path where it has none."""
    return origin_key(remote) if remote else str(root)


class IdsMixin:
    async def rpc_td_hold(
        self,
        repo: str = "",
        id: str = "",
        release: bool = False,
        why: str = "",
        tell: str = "",
        caller: Any = None,
    ) -> dict[str, Any]:
        """`ao td hold` and the Repo page's **Hold** / **Release** (design §4.4 *Hold*, §4.7 *Entries*,
        TD-707, built by TD-710 slice 2, TD-731): the person holds any open entry, settling or settled, or
        releases a held one, on the home's settle clock — no ledger edit. `repo` is a checkout the home
        reads, by its path or its registered name. A person's own act (`mail.PERSON_ONLY`). The reading is
        marked again at once, so a lane and the page read the hold now. A hold on a claimed entry tells
        its unattended holders, and the readers of their PRs (`_hold_tell`). `why` is the hold's optional
        words (TD-905), quoted in those notes; on a held entry new words replace them and nobody is told
        again. **A drop notice** is `tell` (§4.4 *Hold*, TD-905): no hold is written, and the same
        holders and readers are told the entry `<tell>` — **Done…** and **Back to design…** send it
        before their line. Returns `{repo, id, held, settling, told, readers, untold}`."""
        agent_common.person_only(caller, "hold a ledger entry", "§4.4 *Hold*", self._graph())
        why, tell = " ".join(str(why or "").split())[:WHY_CHARS], " ".join(str(tell or "").split())[:WHY_CHARS]
        if tell and (release or why):
            raise RpcError("a drop notice (tell) writes no hold: it takes neither release nor why (design §4.4 *Hold*)")
        if release and why:
            raise RpcError("a release takes no words: why is a hold's (design §4.4 *Hold*)")
        want = str(repo or "").strip()
        roots = [
            r
            for r, v in self._repos.items()
            if want and (r == want or str(Path(r).resolve()) == str(Path(want).expanduser().resolve())
                         or str((v or {}).get("name") or Path(r).name) == want)
        ]  # fmt: skip
        if not roots:
            raise RpcError(f"{want or 'no repo'} is not a repo this home reads (its repos registry)")
        root = roots[0]
        view = self._repos.get(root) or {}
        name = str(view.get("name") or Path(root).name)
        tid = str(id or "").strip().upper()
        entries = [e for e in ((view.get("ledger") or {}).get("entries") or []) if isinstance(e, dict)]
        entry = next((e for e in entries if e.get("id") == tid), None)
        if entry is None:
            raise RpcError(f"{tid or 'no id'} is not an open entry of {name}'s ledger as the home last read it")
        remote = str(view.get("remote") or "")
        if not remote:
            raise RpcError(f"{name}'s origin is not read yet: its clock is keyed by it, so ask again in a minute")
        if tell:
            told, readers, untold = await self._hold_tell(tid, tell=tell)
            return {
                "repo": name,
                "id": tid,
                "held": entry.get("held"),
                "settling": entry.get("settling"),
                "told": told,
                "readers": readers,
                "untold": untold,
            }
        key, spans = settle_key(root, remote), settle_mod.spans(root)
        now = datetime.now(UTC)
        by = PERSON if caller is None or mail.is_person(caller) else str(caller)
        was_held = isinstance(entry.get("held"), dict)
        try:
            await asyncio.to_thread(settle_mod.hold, key, entry, spans, now, by=by, release=bool(release), why=why)
        except settle_mod.Refused as e:
            raise RpcError(str(e)) from None
        settle_mod.mark(entries, key, spans, now)  # on the loop: the lanes and a claim read these dicts there
        told: list[str] = []
        readers: list[str] = []
        untold: list[str] = []
        if not release and not was_held:  # a hold on a held entry tells nobody again
            told, readers, untold = await self._hold_tell(tid, why=why)
        return {
            "repo": name,
            "id": tid,
            "held": entry.get("held"),
            "settling": entry.get("settling"),
            "told": told,
            "readers": readers,
            "untold": untold,
        }

    async def _hold_tell(self, tid: str, why: str = "", tell: str = "") -> tuple[list[str], list[str], list[str]]:
        """Tell a held entry's claimers (design §4.4 *A claimed entry is held all the same*, TD-731), the hold
        already written: a `note` from the person, `about` the id, to each **unattended** live holder of a
        declared lease (`_lease_holders`), and a second to each seat whose inbox holds an open `ask` carrying
        a PR one of those holders' claims names (`pr` or `review_pr`) — once a seat, the person never, being
        no record. A note that cannot be sent is a line of `untold` and never refuses the hold. `why` is the
        hold's words, quoted; `tell` a drop notice's (TD-905), which says the entry `<tell>` in place of
        *is held by the person*, with no Release to wait for. Returns `(told, readers, untold)`: every name
        mailed, the readers among them, and the lines not sent."""
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

        said = f"{tid} {tell}" if tell else f"{tid} is held by the person" + (f" (“{why}”)" if why else "")
        drop = "told by the person" if tell else "held by the person"
        for addr in holders:
            await tell_(
                addr,
                f"{said}: stop at the step in hand, push, leave its PR open and unmerged, and drop the entry: "
                f'`ao progress drop {tid} --why "{drop}"`.' + ("" if tell else " A Release makes it pickable again."),
            )
        for addr, pr in seats.items():
            until = "" if tell else " until they release it"
            if await tell_(addr, f"{said}: leave PR #{pr} unmerged{until}."):
                readers.append(addr)
        return told, readers, untold

    async def rpc_td_next(
        self, repo: str = "", count: int = 1, held: bool = False, caller: Any = None
    ) -> dict[str, Any]:
        """`ao td next` (design §4.4 *A ledger entry's id is handed out by the home*, §4.7 *Entries*): the next
        `count` free ids of the repo named `repo` — its registered name, or its origin's `owner/repo` — and the
        record of who was given them. `by` is the dispatcher's caller, never a parameter. With `held` (`ao td
        next --held`, §4.4 *An entry can land held*, TD-731) each id is held on the settle clock before the
        reply, so its entry lands held until the person's Release: the person's and an interactive
        session's, refused to an unattended caller and to one the graph does not hold. Returns `{repo,
        origin, ids, unread}` — and `held: true` with `held` — `unread` the lines naming the open PRs that
        could not be read, and `reserved`, `why` and `warnings` the script's (on the home's own road `reserved`
        is true, `why` empty and `warnings` none)."""
        start = time.monotonic()
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= COUNT_MAX:
            raise RpcError(f"--count is 1 to {COUNT_MAX}, not {count!r}")
        if held:
            self._held_caller(caller)
        root, key, name = await self._ids_repo(str(repo or "").strip(), start + LOCK_BY)
        lock = self._ids_locks.setdefault(key, asyncio.Lock())
        try:
            await asyncio.wait_for(lock.acquire(), max(0.0, start + LOCK_BY - time.monotonic()))
        except TimeoutError:
            raise RpcError(f"{name}'s ids are being handed out to another caller: busy, ask again") from None
        try:
            left = max(0.1, start + BUDGET - time.monotonic())
            if script := await asyncio.to_thread(ids_script, root, left):
                got = await self._ids_script(root, key, name, script, count, start, caller)
            else:
                ids, unread = await self._ids_give(root, key, count, start, caller)
                got = {"ids": ids, "unread": unread, "reserved": True, "why": "", "warnings": []}
        finally:
            lock.release()
        for line in [*got["unread"], *got["warnings"]] + ([] if got["reserved"] else [f"not reserved: {got['why']}"]):
            log.info("td_next %s: %s", name, line)
        out = {"repo": name, "origin": key, **got}
        if held:  # the clock is keyed by the origin as `settle_key` keys a reading's (an origin is read here)
            by = PERSON if mail.is_person(caller) else str(caller)
            await asyncio.to_thread(settle_mod.prehold, key, got["ids"], by, datetime.now(UTC))
            out["held"] = True
        return out

    def _held_caller(self, caller: Any) -> None:
        """`--held` is the person's and an interactive session's (design §4.4 *An entry can land held*): the
        person, the person's own shell and a session whose record is not `unattended` pass; an unattended
        one, and a caller the graph does not hold, are refused in these words, not `person_only`'s."""
        if mail.is_person(caller):
            return
        r = self._graph().get(caller) if isinstance(caller, str) else None
        if r is None:
            raise RpcError(
                f"--held is the person's and an interactive session's: {caller} is not a session this home holds "
                "(design §4.4 *An entry can land held*)"
            )
        if not r.unattended:  # the person's own shell is interactive too (`mail.person_shell`)
            return
        raise RpcError(
            f"--held is the person's and an interactive session's: {caller} is unattended "
            "(design §4.4 *An entry can land held*)"
        )

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
        self, root: str, key: str, name: str, script: Path, count: int, start: float, caller: Any
    ) -> dict[str, Any]:
        """The road over origin's counter (design §4.4 *A ledger entry's id is handed out by the home*, TD-970): the
        synced script, run in the checkout with this interpreter — a pinned repo's through the resolver (TD-1014) —
        the home's last given as its `--floor`, and killed with its group at the call's deadline. It fetches and
        reads what it needs; the home reads no PR here."""
        rel = await asyncio.to_thread(ledger_mod.ledger_path, root)
        by = PERSON if caller is None or mail.is_person(caller) else str(caller)
        floor = await asyncio.to_thread(_last, key)
        left = start + BUDGET - time.monotonic()
        args = [
            "--count", str(count), "--by", by, "--floor", str(floor),
            "--ledger", rel, "--archive", ledger_mod.archive_path(rel), "--json",
        ]  # fmt: skip
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
        await asyncio.to_thread(_record_given, key, ids, by)
        refs = [str(r) for r in res.get("unread") or [] if str(r).strip()]
        return {
            "ids": ids,
            "unread": [f"open PRs not read: {', '.join(refs)}"] if refs else [],
            "reserved": rc == 0,
            "why": "" if rc == 0 else why,
            "warnings": [str(w) for w in res.get("warnings") or [] if str(w).strip()],
        }

    async def _ids_give(
        self, root: str, key: str, count: int, start: float, caller: Any
    ) -> tuple[list[str], list[str]]:
        rel = await asyncio.to_thread(ledger_mod.ledger_path, root)
        files = (rel, ledger_mod.archive_path(rel))
        # 1. the open PRs' added headings, read before the fetch, so a PR merged between the two is in main
        prs, unread = await self._ids_prs(root, key, files, start + PRS_BY)
        # 2. the fetch, then 3. main's ledger and archive at the fetched ref
        rc, _, err = await _run(["git", "-C", root, "fetch", "-q", "origin"], None, start + BUDGET - time.monotonic())
        if rc != 0:
            raise RpcError(f"the fetch of {Path(root).name}'s origin failed ({_why(err, 'git fetch failed')}): "
                           "main's ids are the floor, so none is given")  # fmt: skip
        ref = await asyncio.to_thread(ledger_mod.default_ref, root, max(0.1, start + BUDGET - time.monotonic()))
        if ref is None:
            raise RpcError(f"{Path(root).name} has no origin/<default> after the fetch: main's ids are the floor")
        main: set[int] = set()
        for f in files:
            rc, out, _ = await _run(["git", "-C", root, "show", f"{ref}:{f}"], None, start + BUDGET - time.monotonic())
            if rc == 0:
                main |= {int(t[3:]) for t in ledger_mod.ids_in(out)}
        # 4. the highest of the three and the last given, then 5. the record
        by = PERSON if caller is None or mail.is_person(caller) else str(caller)
        ids = await asyncio.to_thread(_record, key, max([*prs, *main], default=0), count, by)
        return ids, unread

    async def _ids_prs(self, root: str, key: str, files: tuple[str, ...], by: float) -> tuple[set[int], list[str]]:
        """The ids every open PR adds a heading for in the ledger or its archive, and the unread lines."""
        if not is_github(key):
            return set(), [f"open PRs not read: the origin {key} is not GitHub's"]
        rc, out, err = await _run(
            ["gh", "pr", "list", "--repo", key, "--state", "open", "--limit", str(PR_LIMIT), "--json", "number"],
            root, by - time.monotonic(),
        )  # fmt: skip
        try:
            numbers = [int(p["number"]) for p in json.loads(out)] if rc == 0 else None
        except (ValueError, TypeError, KeyError):
            numbers, err = None, "gh pr list printed something that is not a list of PRs"
        if numbers is None:
            return set(), [f"open PRs not read: {_why(err, 'gh pr list failed')}"]
        unread = [f"open PRs not read: the list filled its {PR_LIMIT}"] if len(numbers) >= PR_LIMIT else []
        gate = asyncio.Semaphore(PR_READERS)
        jq = files_jq(files)

        async def read(n: int) -> set[int] | str:
            async with gate:
                rc, out, err = await _run(
                    ["gh", "api", f"repos/{key}/pulls/{n}/files", "--paginate", "--jq", jq], root, by - time.monotonic()
                )
            if rc != 0:
                return "budget" if err == "timed out" else _why(err, "its files could not be listed")
            lines = [ln for ln in out.splitlines() if ln.strip()]
            if len(lines) >= FILES_CAP:
                return f"its listing is cut at {FILES_CAP} files"
            got: set[int] = set()
            for ln in lines:
                if ln.strip() == "0":
                    continue
                try:
                    f = json.loads(ln)
                except ValueError:
                    return "its listing is not JSON"
                if not isinstance(f, dict):
                    return "its listing is not a list of files"
                if f.get("p") is None:
                    return f"{f.get('f')} has no patch (too large a diff)"
                got |= added_ids(f["p"])
            return got

        tasks = {n: asyncio.create_task(read(n)) for n in numbers}
        if tasks:
            await asyncio.wait(tasks.values(), timeout=max(0.0, by - time.monotonic()))
        ids: set[int] = set()
        for n, t in tasks.items():
            if not t.done():
                t.cancel()
                unread.append(f"open PR #{n} not read: budget")
                continue
            res = t.result()
            if isinstance(res, str):
                unread.append(f"open PR #{n} not read: {res}")
            else:
                ids |= res
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        return ids, unread


_STORE = threading.Lock()  # `ids.json` is one file for every origin, and each origin has its own lock


def _record(key: str, floor: int, count: int, by: str) -> list[str]:
    """Take `count` ids over the highest of `floor` and the origin's `last`, and record them — the read, the
    take and the write as one step under `_STORE`, so two origins handed out at once never drop each other's."""
    with _STORE:
        store = _load()
        rec = store.get(key) if isinstance(store.get(key), dict) else {}
        last = rec.get("last") if isinstance(rec.get("last"), int) else 0
        top = max(floor, last)
        ids = [f"TD-{n:03d}" for n in range(top + 1, top + 1 + count)]
        at = now_iso()
        given = [g for g in rec.get("given") or [] if isinstance(g, dict)]
        given += [{"id": i, "by": by, "at": at} for i in ids]
        store[key] = {"last": top + count, "given": given[-GIVEN_KEEP:]}
        _save(store)
        return ids


def _last(key: str) -> int:
    """The last id the home gave for the origin, 0 where it gave none: the script road's `--floor`."""
    with _STORE:
        rec = _load().get(key)
    return rec["last"] if isinstance(rec, dict) and isinstance(rec.get("last"), int) else 0


def _record_given(key: str, ids: list[str], by: str) -> None:
    """Record ids the script gave, as they are: appended to `given`, `last` moved to the highest of them."""
    with _STORE:
        store = _load()
        rec = store.get(key) if isinstance(store.get(key), dict) else {}
        last = rec.get("last") if isinstance(rec.get("last"), int) else 0
        at = now_iso()
        given = [g for g in rec.get("given") or [] if isinstance(g, dict)]
        given += [{"id": i, "by": by, "at": at} for i in ids]
        store[key] = {"last": max([last, *(int(i[3:]) for i in ids)]), "given": given[-GIVEN_KEEP:]}
        _save(store)


def _load() -> dict[str, Any]:
    try:
        raw = json.loads(paths.ids_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(store: dict[str, Any]) -> None:
    paths.ids_file().parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(paths.ids_file(), json.dumps(store, indent=1, sort_keys=True))
