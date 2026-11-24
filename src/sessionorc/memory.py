"""How much memory a host has left, and what holds it (design §4.6 *Told when memory runs short*, *The process
reading*, TD-2127; built by TD-2136): the two halves' share free from `/proc/meminfo` and the cgroup tree, each half's
state from one reading to the next, and a bounded walk of this user's processes naming the largest holders; and
from the same walk the processes finished sessions left running (*Told what finished sessions left running*, built
by TD-2137), with the spell they raise.

It only reads: nothing here signals a process, and of a process's environment only `SHIFTLEAD_HOME` and
`SHIFTLEAD_SESSION` are read."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .scratch import (
    LEFT_AGE,
    LEFT_CLEAR,
    LEFT_ENDED_KEEP,
    LEFT_ENDED_RUNS,
    LEFT_RAISE,
    LEFT_SLACK,
    LEFT_WALK_S,
    MEMORY_CLEAR,
    MEMORY_LOW,
)

PROC = "/proc"
CGROUP = "/sys/fs/cgroup"
HALVES = ("ram", "swap")
HOLDERS = 3
ENDED = ("exited", "closed")
_ANCESTORS = 64  # a parent chain longer than this is read no further


# -- the reading ----------------------------------------------------------------------------------------------------


def _kib_lines(path: Path) -> dict[str, int]:
    """`Key:   123 kB` lines as bytes (`/proc/meminfo`, `smaps_rollup`, `status`). Raises OSError where unreadable."""
    out: dict[str, int] = {}
    for line in path.read_text().splitlines():
        key, _, rest = line.partition(":")
        words = rest.split()
        if words and words[0].isdigit():
            out[key.strip()] = int(words[0]) * (1024 if words[1:2] == ["kB"] else 1)
    return out


def _number(path: Path) -> int | None:
    """A cgroup file's one number; None where it is absent, unreadable or `max`."""
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    return int(text) if text.isdigit() else None


def _limit(proc: Path, cgroup: Path, total: int) -> tuple[int, int, int] | None:
    """The lowest numeric `memory.max` below `total` on the agent's cgroup v2 path or a parent of it up to the root,
    with that cgroup's `memory.current` and `inactive_file`; None on cgroup v1, or where no such limit is set."""
    try:
        lines = (proc / "self" / "cgroup").read_text().splitlines()
    except OSError:
        return None
    rel = next((line[3:] for line in lines if line.startswith("0::")), None)
    if rel is None:  # cgroup v1: read as the machine
        return None
    best: tuple[int, Path] | None = None
    at = Path("/") / rel.strip().lstrip("/")
    while True:
        here = cgroup / str(at).lstrip("/")
        cap = _number(here / "memory.max")
        if cap is not None and cap < total and (best is None or cap < best[0]):
            best = (cap, here)
        if at == at.parent:
            break
        at = at.parent
    if best is None:
        return None
    cap, here = best
    current = _number(here / "memory.current")
    if current is None:
        return None
    try:
        inactive = _kib_lines_plain(here / "memory.stat").get("inactive_file", 0)
    except OSError:
        inactive = 0
    return cap, current, inactive


def _kib_lines_plain(path: Path) -> dict[str, int]:
    """`memory.stat`'s `key value` lines, in bytes already."""
    out: dict[str, int] = {}
    for line in path.read_text().splitlines():
        words = line.split()
        if len(words) == 2 and words[1].isdigit():
            out[words[0]] = int(words[1])
    return out


def _share(free: int, total: int) -> float:
    return max(0.0, min(1.0, free / total)) if total > 0 else 0.0


def read_halves(proc: str | Path | None = None, cgroup: str | Path | None = None) -> dict[str, float] | None:
    """Each half's share free, 0 to 1 (§4.6 *Told when memory runs short*): `ram` from `MemAvailable / MemTotal`, and
    `swap` from `SwapFree / SwapTotal` where the host has swap. Under a cgroup limit below `MemTotal` the limit is the
    total, the available bytes the lower of `MemAvailable` and the limit less `memory.current` plus `inactive_file`,
    and `swap` is left out. None where `/proc/meminfo` cannot be read: no reading."""
    p, cg = Path(proc or PROC), Path(cgroup or CGROUP)
    try:
        info = _kib_lines(p / "meminfo")
    except OSError:
        return None
    total, avail = info.get("MemTotal"), info.get("MemAvailable")
    if not total or avail is None:
        return None
    limit = _limit(p, cg, total)
    if limit is not None:
        cap, current, inactive = limit
        return {"ram": _share(min(avail, max(0, cap - current + inactive)), cap)}
    out = {"ram": _share(avail, total)}
    swap_total, swap_free = info.get("SwapTotal"), info.get("SwapFree")
    if swap_total and swap_free is not None:
        out["swap"] = _share(swap_free, swap_total)
    return out


# -- each half's state ----------------------------------------------------------------------------------------------


def _written(now: str, share: float | None, holders: list[dict[str, Any]], cut: bool) -> dict[str, Any]:
    return {"low": True, "since": now, "share_free": share, "holders": holders, "cut": cut}


class Watch:
    """The half of the state kept in memory, so a restart forgets it (§4.6 *Told when memory runs short*): each half's
    run of readings under `MEMORY_LOW`, and the halves *turning*, each with its latest share. The *low* state is the
    caller's, `disk.json`'s `memory`."""

    def __init__(self) -> None:
        self.count: dict[str, int] = {}
        self.turning: dict[str, float] = {}

    def step(
        self, state: dict[str, dict[str, Any]], halves: dict[str, float] | None, now: str, walk: str
    ) -> tuple[dict[str, dict[str, Any]], bool]:
        """The state after one reading, and whether a walk should start now. `walk` is `idle`, `running` or `stuck`
        (past twice `LEFT_WALK_S`). No reading changes nothing. A half the reading lacks is ended; over
        `MEMORY_CLEAR` ends it, *turning* or *low*; under `MEMORY_LOW` twice running makes it *turning*; at or over
        `MEMORY_LOW` breaks the run and otherwise leaves it as it is. While a walk is stuck, a half turning is written
        *low* at once, `cut` with no holders."""
        out = {h: dict(v) for h, v in state.items()}
        if halves is None:
            return out, False
        for half in [h for h in out if h not in halves]:
            del out[half]
        for half in [h for h in {*self.count, *self.turning} if h not in halves]:
            self.count.pop(half, None)
            self.turning.pop(half, None)
        for half, share in halves.items():
            if share > MEMORY_CLEAR:
                out.pop(half, None)
                self.count.pop(half, None)
                self.turning.pop(half, None)
            elif share < MEMORY_LOW:
                self.count[half] = self.count.get(half, 0) + 1
                if half in self.turning or self.count[half] >= 2 and not (out.get(half) or {}).get("low"):
                    self.turning[half] = share
            else:
                self.count[half] = 0
        if self.turning and walk == "stuck":
            for half, share in self.turning.items():
                out[half] = _written(now, share, [], True)
            self.turning.clear()
        return out, bool(self.turning) and walk == "idle"

    def walked(
        self, state: dict[str, dict[str, Any]], got: dict[str, Any] | None, started_for: set[str], now: str
    ) -> dict[str, dict[str, Any]]:
        """The state once a walk returns (§4.6 *The process reading*). `got` is `read_holders`' answer, or None for a
        walk that raised. A half *turning* when the walk started and still is is written *low* with its holders (none,
        `cut`, from a walk that raised); every other *low* half has its holders refreshed by a walk that answered."""
        out = {h: dict(v) for h, v in state.items()}
        written = set()
        for half in [h for h in self.turning if h in started_for]:
            share = self.turning.pop(half)
            held = [] if got is None else list(got.get(half) or [])
            out[half] = _written(now, share, held, True if got is None else bool(got.get("cut")))
            written.add(half)
        if got is not None:
            for half, one in out.items():
                if half not in written and one.get("low"):
                    one.update(holders=list(got.get(half) or []), cut=bool(got.get("cut")))
        return out


def view(state: dict[str, dict[str, Any]], halves: dict[str, float]) -> dict[str, dict[str, Any]]:
    """The `memory` of the host's `disk` reading, by half: every half the host has now, its share free read live, and
    where it is *low* its `since`, holders and `cut`."""
    out: dict[str, dict[str, Any]] = {}
    for half in HALVES:
        if half not in halves:
            continue
        one = state.get(half) or {}
        out[half] = {"low": bool(one.get("low")), "share_free": halves[half]}
        if one.get("low"):
            out[half].update(since=one.get("since"), holders=list(one.get("holders") or []), cut=bool(one.get("cut")))
    return out


# -- the process reading --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    name: str
    start: float  # seconds since the epoch
    ram: int  # `Pss`, or `VmRSS` in the fallback
    swap: int  # `SwapPss`, or `VmSwap`
    home: str | None
    session: str | None
    cwd_gone: bool = False  # its working directory has been deleted


def _stat(path: Path) -> tuple[int, int]:
    """`stat`'s parent pid (field 4) and start time in clock ticks since boot (field 22)."""
    text = (path / "stat").read_text()
    rest = text[text.rindex(")") + 2 :].split()
    return int(rest[1]), int(rest[19])


def _environ(path: Path) -> tuple[str | None, str | None]:
    """The values of `SHIFTLEAD_HOME` and `SHIFTLEAD_SESSION`, and nothing else of the environment."""
    home = session = None
    try:
        raw = (path / "environ").read_bytes()
    except OSError:
        return None, None
    for item in raw.split(b"\0"):
        if item.startswith(b"SHIFTLEAD_HOME="):
            home = item[15:].decode(errors="replace")
        elif item.startswith(b"SHIFTLEAD_SESSION="):
            session = item[18:].decode(errors="replace")
    return home, session


def _sizes(path: Path) -> tuple[int, int]:
    """`Pss` and `SwapPss` from `smaps_rollup`, else `VmRSS` and `VmSwap` from `status`, else nothing."""
    try:
        got = _kib_lines(path / "smaps_rollup")
        if "Pss" in got:
            return got["Pss"], got.get("SwapPss", 0)
    except OSError:
        pass
    try:
        got = _kib_lines(path / "status")
        return got.get("VmRSS", 0), got.get("VmSwap", 0)
    except OSError:
        return 0, 0


def _cwd_gone(path: Path) -> bool:
    """Whether the process's working directory has been deleted: the kernel's link reads `<path> (deleted)`."""
    try:
        return os.readlink(path / "cwd").endswith(" (deleted)")
    except OSError:
        return False


def _boot(proc: Path) -> tuple[float, float]:
    """`/proc/stat`'s `btime` and `CLK_TCK`."""
    btime = 0.0
    try:
        for line in (proc / "stat").read_text().splitlines():
            if line.startswith("btime "):
                btime = float(line.split()[1])
                break
    except OSError:
        pass
    return btime, float(os.sysconf("SC_CLK_TCK"))


def walk(
    proc: str | Path | None = None, limit_s: float = LEFT_WALK_S, uid: int | None = None
) -> tuple[list[Proc], bool]:
    """This user's processes, and whether the walk was cut at `limit_s` (§4.6 *The process reading*). A process whose
    start time changed between the reads around its environment is dropped: its pid was reused."""
    p = Path(proc or PROC)
    me = os.getuid() if uid is None else uid
    deadline = time.monotonic() + limit_s
    btime, tick = _boot(p)
    out: list[Proc] = []
    try:
        entries = sorted((e for e in os.scandir(p) if e.name.isdigit()), key=lambda e: int(e.name))
    except OSError:
        return out, False
    for e in entries:
        if time.monotonic() > deadline:
            return out, True
        path = Path(e.path)
        try:
            if e.stat(follow_symlinks=False).st_uid != me:
                continue
            ppid, start = _stat(path)
            home, session = _environ(path)
            if _stat(path)[1] != start:
                continue
            name = (path / "comm").read_text().strip()
        except (OSError, ValueError, IndexError):  # gone, or not a process's files
            continue
        ram, swap = _sizes(path)
        out.append(Proc(int(e.name), ppid, name, btime + start / tick, ram, swap, home, session, _cwd_gone(path)))
    return out, False


def _epoch(stamp: str) -> float | None:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def live_runs(records: list[Any]) -> dict[str, tuple[str, float]]:
    """The snapshot a walk reads, taken on the loop: each record not `exited` or `closed`, by id, with its name and
    `created` as a time."""
    out: dict[str, tuple[str, float]] = {}
    for r in records:
        created = _epoch(str(getattr(r, "created", "") or ""))
        if getattr(r, "state", None) not in ENDED and created is not None:
            out[str(r.id)] = (str(getattr(r, "name", "") or r.id), created)
    return out


def ended_records(records: list[Any]) -> dict[str, float]:
    """Rule 5's records, in the same snapshot (§4.6 *Told what finished sessions left running*): each unattended
    `exited` or `closed` record, by id, with its `created` as a time."""
    out: dict[str, float] = {}
    for r in records:
        created = _epoch(str(getattr(r, "created", "") or ""))
        if getattr(r, "state", None) in ENDED and getattr(r, "unattended", False) and created is not None:
            out[str(r.id)] = created
    return out


# -- the runs that ended (`ended_runs`) -----------------------------------------------------------------------------


def end_run(ended: dict[str, Any], sid: str, created: str, now: str) -> dict[str, Any]:
    """`ended_runs` with one more run of `sid`, `{"from": <created>, "to": <now>}`, written when an unattended record
    is forgotten or a new run replaces it in place under its id; at most `LEFT_ENDED_RUNS` runs an id."""
    out = {k: {"runs": list(v.get("runs") or [])} for k, v in ended.items() if isinstance(v, dict)}
    runs = out.setdefault(sid, {"runs": []})["runs"]
    runs.append({"from": created, "to": now})
    out[sid]["runs"] = runs[-LEFT_ENDED_RUNS:]
    return out


def trim_runs(ended: dict[str, Any], now: float) -> dict[str, Any]:
    """`ended_runs` without a run whose `to` is past `LEFT_ENDED_KEEP`, or an odd one, and without an id left with
    none; at most `LEFT_ENDED_RUNS` runs an id."""
    out: dict[str, Any] = {}
    for sid, one in ended.items():
        runs = [
            r
            for r in (one.get("runs") if isinstance(one, dict) else None) or []
            if isinstance(r, dict)
            and _epoch(str(r.get("from") or "")) is not None
            and (to := _epoch(str(r.get("to") or ""))) is not None
            and now - to <= LEFT_ENDED_KEEP
        ]
        if runs:
            out[str(sid)] = {"runs": runs[-LEFT_ENDED_RUNS:]}
    return out


def spans(ended: dict[str, Any]) -> dict[str, list[tuple[float, float]]]:
    """`ended_runs` as times, the snapshot a walk reads beside the records."""
    out: dict[str, list[tuple[float, float]]] = {}
    for sid, one in ended.items():
        for r in (one.get("runs") if isinstance(one, dict) else None) or []:
            a = _epoch(str(r.get("from") or "")) if isinstance(r, dict) else None
            b = _epoch(str(r.get("to") or "")) if isinstance(r, dict) else None
            if a is not None and b is not None:
                out.setdefault(str(sid), []).append((a, b))
    return out


# -- what finished sessions left running ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Runs:
    """The snapshot of the records a walk reads (§4.6 *The process reading*): the live runs by id (name, `created`),
    rule 5's ended unattended records by id (`created`), and `ended_runs`' spans by id."""

    live: dict[str, tuple[str, float]]
    ended: dict[str, float]
    spans: dict[str, list[tuple[float, float]]]


def _live_of(live: dict[str, tuple[str, float]], here: str, slack: float):
    """Rule 4's test: the live run a process belongs to, or None."""

    def run_of(p: Proc) -> str | None:
        if not p.session or p.session not in live:
            return None
        if p.home is not None and _resolved(p.home) != here:
            return None
        return p.session if p.start >= live[p.session][1] - slack else None

    return run_of


def _stamp(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def left_behind(
    procs: list[Proc], runs: Runs, home: str | Path, now: float, slack: float = LEFT_SLACK, age: float = LEFT_AGE
) -> tuple[list[dict[str, Any]], set[int]]:
    """The process trees finished sessions left running (§4.6 *Told what finished sessions left running*), largest
    first, and every pid they hold. A root is a process whose parent is pid 1 or this user's `systemd` manager, at
    least `age` old, carrying `SHIFTLEAD_HOME` or `SHIFTLEAD_SESSION`, belonging to no live run, and either of an ended
    run (an unattended `exited` or `closed` record, or a span of `ended_runs`, under this home or none) or of a scratch
    home that is gone (or whose working directory was deleted). Its descendants are counted with it, but a live run's,
    with its own descendants, are left out. It stops no process."""
    here = _resolved(home)
    run_of = _live_of(runs.live, here, slack)
    managers = {p.pid for p in procs if p.name == "systemd" and p.ppid == 1}
    children: dict[int, list[Proc]] = {}
    for p in procs:
        children.setdefault(p.ppid, []).append(p)

    def why(p: Proc) -> dict[str, Any] | None:
        if p.home is None and p.session is None:
            return None  # rule 3: a person's own job, a desktop service, an editor server
        if run_of(p) is not None:
            return None  # rule 4, before any span
        ours = p.home is None or _resolved(p.home) == here
        if ours and p.session:
            created = runs.ended.get(p.session)
            if created is not None and p.start >= created - slack:
                return {"session": p.session}
            if any(a - slack <= p.start <= b for a, b in runs.spans.get(p.session, ())):
                return {"session": p.session}
        if not ours and p.home is not None and (p.cwd_gone or not os.path.isdir(p.home)):
            return {"home": p.home}
        return None

    trees: list[dict[str, Any]] = []
    held: set[int] = set()
    for p in procs:
        if p.ppid not in ({1} | managers) or p.pid in managers or p.start > now - age:
            continue
        judged = why(p)
        if judged is None:
            continue
        tree, todo = [p], list(children.get(p.pid, ()))
        while todo and len(tree) < 100_000:
            q = todo.pop()
            if q.pid in held or run_of(q) is not None:
                continue  # a live run beneath a left-behind root is left out, with its descendants
            tree.append(q)
            todo.extend(children.get(q.pid, ()))
        held.update(q.pid for q in tree)
        size = sum(q.ram + q.swap for q in tree)
        trees.append(
            {
                "pid": p.pid,
                "name": p.name,
                "start": _stamp(p.start),
                "bytes": size,
                "processes": len(tree),
                **judged,
                "cwd_deleted": p.cwd_gone,
            }
        )
    trees.sort(key=lambda t: (-t["bytes"], t["pid"]))
    return trees, held


def holders(
    procs: list[Proc],
    live: dict[str, tuple[str, float]],
    home: str | Path,
    slack: float = LEFT_SLACK,
    left: set[int] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Each half's three largest holders (§4.6 *The process reading*): the processes of a live run, with their
    descendants, under that record's name, everything left behind as one holder, *left behind*, and every other
    process summed by name; `ram` by `Pss`, `swap` by `SwapPss`. A process is a live run's when its `SHIFTLEAD_HOME` is
    this host's home or absent, its `SHIFTLEAD_SESSION` names a live record, and it started no earlier than `slack`
    before that record's `created`."""
    run_of = _live_of(live, _resolved(home), slack)
    by_pid = {p.pid: p for p in procs}
    left = left or set()
    sums: dict[tuple[str, str], list[int]] = {}
    for p in procs:
        key: tuple[str, str] = ("left", "left behind") if p.pid in left else ("name", p.name)
        q: Proc | None = p
        for _ in range(_ANCESTORS):
            if q is None:
                break
            if (sid := run_of(q)) is not None:
                key = ("run", sid)
                break
            q = by_pid.get(q.ppid) if q.ppid != q.pid else None
        got = sums.setdefault(key, [0, 0])
        got[0] += p.ram
        got[1] += p.swap
    out: dict[str, list[dict[str, Any]]] = {}
    for i, half in enumerate(HALVES):
        ranked = sorted(((v[i], k) for k, v in sums.items() if v[i] > 0), key=lambda t: (-t[0], t[1]))
        out[half] = [{"name": live[k[1]][0] if k[0] == "run" else k[1], "bytes": n} for n, k in ranked[:HOLDERS]]
    return out


def _resolved(path: str | Path) -> str:
    try:
        return str(Path(path).resolve())
    except (OSError, RuntimeError):
        return str(path)


def read_holders(
    live: dict[str, tuple[str, float]] | Runs,
    home: str | Path,
    proc: str | Path | None = None,
    limit_s: float = LEFT_WALK_S,
    now: float | None = None,
) -> dict[str, Any]:
    """One walk's answer: each half's holders, `cut` where the walk stopped at its bound, and `left`, what finished
    sessions left running (`processes`, `bytes`, `trees`). In a thread."""
    runs = live if isinstance(live, Runs) else Runs(live, {}, {})
    procs, cut = walk(proc, limit_s)
    trees, held = left_behind(procs, runs, home, time.time() if now is None else now)
    left = {"processes": sum(t["processes"] for t in trees), "bytes": sum(t["bytes"] for t in trees), "trees": trees}
    return {**holders(procs, runs.live, home, left=held), "cut": cut, "left": left}


class LeftWatch:
    """The left-behind spell from walk to walk (§4.6 *Told what finished sessions left running*): the run of
    `LEFT_EVERY` walks at or over `LEFT_RAISE` lives in memory, so a restart starts it again; the spell and the latest
    figures are the caller's, `disk.json`'s `left_behind`."""

    def __init__(self) -> None:
        self.run = 0

    def walked(self, state: dict[str, Any], got: dict[str, Any] | None, every: bool, now: str) -> dict[str, Any]:
        """The state after one walk. Only a `LEFT_EVERY` walk that answered counts: a walk made because a half turned
        low, or one that raised, changes nothing and breaks no run. Two such walks running at or over `LEFT_RAISE`
        start the spell; the first complete one under both of `LEFT_CLEAR`'s bounds ends it. A walk cut at its bound
        counts toward the raise and never ends a spell, and under the raise it breaks no run."""
        left = (got or {}).get("left")
        if not every or got is None or not isinstance(left, dict):
            return dict(state)
        cut = bool(got.get("cut"))
        n, size = int(left.get("processes") or 0), int(left.get("bytes") or 0)
        since = state.get("since")
        if since:
            if not cut and size < LEFT_CLEAR[0] and n < LEFT_CLEAR[1]:
                since = None
                self.run = 0
        elif size >= LEFT_RAISE[0] or n >= LEFT_RAISE[1]:
            self.run += 1
            if self.run >= 2:
                since, self.run = now, 0
        elif not cut:
            self.run = 0
        out = {"at": now, "processes": n, "bytes": size, "cut": cut, "trees": list(left.get("trees") or [])}
        return {"since": since, **out} if since else out
