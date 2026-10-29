"""A repo's seams as the host agent keeps them (design §4.4 *Repo facts*, *The seams*; §5 *The seams*;
TD-584, built by TD-591; TD-1011): whether its ledger at `ledger:` parses through `ledgerboard.py` and
its `Ledgerboard:` major; for each of `board:` and `worktree_setup:` whether it is *set*, *defaulted*
(the dev-cadence file the checkout holds) or *absent*; whether the repo is **served** — it holds
dev-cadence's tree, the gate and the ledger, or `serve` names each lack in §5's words with its cure —
and the warnings, one sentence each. The Repo page's missing-seam lines (§4.5a) and `ao doctor`'s
**repos** check (§4.7) draw this reading and read nothing themselves; the SessionStart commands are
carried as text, for the clients to compare with the adapter's own line. It also carries the release
the repo's vendored `ledgerboard.py` names in its header beside the wheel's (§5 *ledgerboard by its
header*, TD-1013)."""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sessionorc import cadence, gitinfo, hosts, reports, sync, workorders
from sessionorc import ledger as ledger_mod
from sessionorc import ledgerboard as lb

AGE_TIMEOUT = 20.0  # the bound of one ancestry read, git's or the forge's
# a vendored copy's first line: the tagged release it came from and the hash of every byte after it
RELEASE_HEADER = re.compile(r"^# ledgerboard v(\S+) sha256:([0-9a-f]{64})$")
# where a repo keeps its copy: a consumer's, then dev-cadence's own source
LEDGERBOARD_COPIES = ("scripts/ledgerboard.py", "files/scripts/ledgerboard.py")


def ledgerboard_release(text: str) -> str | None:
    """The release a `ledgerboard.py`'s first line names (*1.3* of `# ledgerboard v1.3 sha256:…`), or None
    when that line is not a release header."""
    m = RELEASE_HEADER.match(text.split("\n", 1)[0].rstrip("\r"))
    return m.group(1) if m else None


def _file_release(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8") as f:
            return ledgerboard_release(f.readline())
    except (OSError, UnicodeDecodeError):
        return None


@functools.cache
def wheel_release() -> str | None:
    """The release of the `ledgerboard.py` this build carries (`sessionorc/ledgerboard.py`), read once."""
    return _file_release(Path(lb.__file__))


def ledgerboard(root: Path | str) -> dict[str, Any]:
    """`{release, wheel}`: the release the repo's copy names (the first of `LEDGERBOARD_COPIES` there;
    None for a copy with no release header, or a repo with neither file) and the wheel's. A pinned repo's
    is the pinned tree's (TD-1014), and it carries `pinned`: one whose tree did not resolve has no
    release to compare and is warned of for nothing, its lack saying why."""
    if cadence.pinned(root):
        payload = cadence.tree(root)[0]
        copy = payload / "scripts" / "ledgerboard.py" if payload is not None else None
        return {"release": _file_release(copy) if copy is not None else None, "wheel": wheel_release(), "pinned": True}
    copy = next((Path(root) / rel for rel in LEDGERBOARD_COPIES if (Path(root) / rel).is_file()), None)
    return {"release": _file_release(copy) if copy is not None else None, "wheel": wheel_release()}


def ledger(root: Path | str) -> dict[str, Any]:
    """The ledger seam: `{path, state, major, entries, why, directory}` — `state` *ok* (it parses and its major
    is one `ledgerboard.py` knows; `entries` its count), *absent* (neither a file nor a directory at the
    ledger's path), *unreadable* (the file could not be read as text, `ledger:` names a path outside the repo,
    or a v2 directory is faulted: `why` its `ledger.v2_faults` words) or *newer* (its `Ledgerboard:` major —
    a directory's from its `README.md` — is past the module's), `why` the reader's reason when not *ok*;
    `reading()` makes an *ok* directory *predates* where dev-cadence's tree cannot read one (§5 *Which
    dev-cadence*). `path` is the ledger as read, through `layout_at` (§4.4 *Either layout*): a set `ledger:`
    gone from the tree reads the other layout beside it, and `named` carries the path it names."""
    rel = ledger_mod.ledger_path(root)
    out: dict[str, Any] = {"path": rel, "state": "ok", "major": None, "entries": None, "why": None, "directory": False}
    if not workorders.inside(Path(rel)):
        return {**out, "state": "unreadable", "why": f"ledger: {rel} is not a path inside the repo"}
    io = ledger_mod.fs_io(root)
    led = ledger_mod.layout_at(rel, None, io)[0]
    if led != rel and (Path(root) / led).exists():
        out["path"] = led
        if ledger_mod.ledger_set(root) is not None:
            out["named"] = rel  # the warning's: `ledger:` names <rel>, which is gone
    path = Path(root) / out["path"]
    if path.is_dir():
        text = lb.load(out["path"], *io)[0]
        out["major"], out["directory"] = lb.format_major(text), True
        if (why := lb.version_problem(text)) is not None:
            return {**out, "state": "newer", "why": why}
        if faults := ledger_mod.v2_faults(out["path"], io):
            return {**out, "state": "unreadable", "why": "; ".join(faults)}
        out["entries"] = len(lb.entries(text))
        return out
    if not path.is_file():
        return {**out, "state": "absent", "why": f"no ledger at {out['path']}"}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {**out, "state": "unreadable", "why": f"{out['path']}: {getattr(e, 'strerror', None) or e}"}
    out["major"] = lb.format_major(text)
    why = lb.version_problem(text)
    if why is not None:
        return {**out, "state": "newer", "why": why}
    try:
        out["entries"] = len(lb.entries(text))
    except Exception as e:  # noqa: BLE001 — a ledger the module cannot parse is named, never a failed reading
        return {**out, "state": "unreadable", "why": f"{out['path']} does not parse: {e}"}
    return out


# dev-cadence's shim in a checkout's common hooks (dev-cadence TD-055): its per-clone setup was run
SHIM_MARKER = "dev-cadence hook shim (TD-055)"
# the launcher call only dev-cadence TD-129's shim makes (`dev-cadence hook "${0##*/}"`): the bare
# `dev-cadence hook` is in every shim's SHIM_MARKER, so it tells no era (TD-1024)
PINNED_SHIM = 'dev-cadence hook "'


ADOPT_BRANCH = "cadence-adopt"  # the head `ao repo add --adopt` opens its PR from (§4.7 `ao repo add`)


def cure(root: Path | str) -> str:
    """The cure of a lack dev-cadence's adoption supplies (§5 *The seams*, TD-1010)."""
    return f"`ao repo add {root} --adopt`"


def with_adoption(seams: dict[str, Any] | None, root: Path | str, prs: dict[str, Any] | None) -> dict[str, Any] | None:
    """The reading with each adopt cure read as *adoption PR #n open* while the repo's PR reading holds
    an open PR whose head is `ADOPT_BRANCH` (§5 *The seams*); the reading itself where none is open."""
    pr = next(
        (p for p in (prs or {}).get("open") or [] if isinstance(p, dict) and p.get("branch") == ADOPT_BRANCH),
        None,
    )
    serve = (seams or {}).get("serve")
    if pr is None or not isinstance(serve, dict):
        return seams
    was, now = cure(root), f"adoption PR #{pr.get('number')} open"
    lacks = [{**x, "words": str(x.get("words") or "").replace(was, now)} for x in serve.get("lacks") or []]
    return {**(seams or {}), "serve": {**serve, "lacks": lacks}}


def ledger_lack(led: dict[str, Any] | None, root: Path | str) -> str | None:
    """The ledger seam's lack in §5's words, or None when it parses: *unserved: no ledger at <path> —
    <cure>*, *ledger is Ledgerboard 3, this build reads 2 (sync)*, *unserved: the ledger is a directory and
    dev-cadence at <commit> predates its v2 reader (b9236c8) — sync it* (a pinned repo's *— bump the pin*), or
    *unserved: the ledger at <path> does not parse — <the reader's reason>*, which no adoption cures."""
    led = led or {}
    state, path = led.get("state"), led.get("path") or "the ledger path"
    if state in (None, "ok"):
        return None
    if state == "predates":
        return f"unserved: {led.get('why')} — {'bump the pin' if cadence.pinned(root) else 'sync it'}"
    if state == "absent":
        return f"unserved: no ledger at {path} — {cure(root)}"
    if state == "newer":
        return f"ledger is Ledgerboard {led.get('major')}, this build reads {lb.FORMAT_MAJOR} (sync)"
    return f"unserved: the ledger at {path} does not parse — {led.get('why') or state}"


def _lock(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    """The checkout's lock and the tree's lack (§5 *The seams*): no lock, or one that does not parse;
    `(None, None)` for dev-cadence's own source, which carries none. A pinned repo's pin stands in for the
    lock (`{source, files_commit, pin}`, its `ref` the commit, §5 *How the readers find dev-cadence*,
    TD-1014): one the launcher would refuse, or cannot resolve, is the tree's lack."""
    if cadence.is_source(root):
        return None, None
    if cadence.pinned(root):
        try:
            source, ref = cadence.pin(root) or ("", "")
        except cadence.PinError as e:
            return None, f"unserved: dev-cadence's pin does not parse — {e} — {cure(root)}"
        if (why := cadence.tree(root)[1]) is not None:
            return None, f"unserved: dev-cadence's pin does not resolve — {why}"
        return {"source": source, "commit": ref, "files_commit": ref, "pin": True}, None
    path = root / sync.LOCK
    if not path.is_file():
        return None, f"unserved: no dev-cadence (no pin in {cadence.PIN}, no {sync.LOCK}) — {cure(root)}"
    try:
        lock = sync.parse_lock(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        return None, f"unserved: dev-cadence's lock does not parse — {getattr(e, 'strerror', None) or e} — {cure(root)}"
    if not (lock or {}).get("files_commit"):
        return None, f"unserved: dev-cadence's lock does not parse — it has no files_commit line — {cure(root)}"
    return lock, None


def _forge_repo(source: str) -> str | None:
    """`owner/name` of a lock's `source:` on GitHub, or None for a source elsewhere."""
    host, _, rest = sync._norm_url(source).partition("/")
    return rest if host == "github.com" and rest.count("/") == 1 else None


def descends(
    commit: str, roster: Iterable[Path | str], source: str = "", oldest: str | None = None
) -> tuple[bool | None, str | None]:
    """Whether `commit` descends from `oldest`, `cadence.OLDEST` unless given (§5 *Which dev-cadence*, TD-1012;
    `cadence.OLDEST_V2` for a v2 ledger, TD-1144), or from `cadence.SEED`, agent-cadence's first commit, which
    is newer than both on a history that holds neither (TD-1208): `(True|False, None)`, or `(None, why)` when it
    cannot be read. Read in each of the roster's dev-cadence checkouts in turn (each a source, as the host's
    own fetch left it) with `git merge-base --is-ancestor`, the first that holds both commits of a pair
    answering: a checkout that holds `commit` and either oldest point decides, since one that holds a commit
    after the seed holds the seed too. With none, through the forge's compare of each pair in turn on the
    pin's own `source`. A `+dirty` tree is read at the commit it was synced from; `why` is the read
    against `oldest`."""
    commit, oldest = commit.removesuffix("+dirty"), oldest or cadence.OLDEST
    checkouts = [Path(r) for r in roster if cadence.is_source(r)]
    first = "no dev-cadence checkout in the roster"
    misses = []
    answers = []
    for point in (oldest, cadence.SEED):
        for checkout in checkouts:
            try:
                cp = sync._git(checkout, "merge-base", "--is-ancestor", point, commit, timeout=AGE_TIMEOUT)
            except sync._Error as e:
                if point == oldest:
                    misses.append(str(e))
                continue
            if cp.returncode in (0, 1):
                answers.append(cp.returncode == 0)
                break
            if point == oldest:
                misses.append(f"{checkout} does not hold {commit[:7]} and {oldest[:7]}")
        if True in answers:
            return True, None
    if answers:
        return False, None
    if misses:
        first = "; ".join(misses)
    repo = _forge_repo(source)
    if repo is None:
        return None, f"{first}, and its source {source or '(none)'} is not on GitHub"
    got, why = _compare(repo, oldest, commit)
    if got is not True:
        seed = _compare(repo, cadence.SEED, commit)[0]
        got = seed if got is None or seed is True else got
    if got is None:
        return None, f"{first}; {why}"
    return got, None


def _compare(repo: str, oldest: str, commit: str) -> tuple[bool | None, str | None]:
    """The forge's compare of `oldest...commit` on `repo` (`descends`): `(True|False, None)`, or `(None, why)`."""
    got, why = reports._gh_api(Path.home(), f"repos/{repo}/compare/{oldest}...{commit}", AGE_TIMEOUT)
    if why is not None:
        return None, why
    status = got.get("status") if isinstance(got, dict) else None
    if status in ("ahead", "identical"):
        return True, None
    if status in ("behind", "diverged"):
        return False, None
    return None, f"the compare read no status ({status!r})"


def age(
    root: Path | str, roster: Iterable[Path | str] = (), old: dict[str, Any] | None = None, v2: bool = False
) -> dict[str, Any] | None:
    """The lock's age (§5 *Which dev-cadence*): `{commit, oldest, seed, descends, why}`, `commit` the lock's
    `files_commit` (else `commit`), `descends` whether it is at or after `cadence.OLDEST` or `cadence.SEED`
    (None with `why` when that could not be read); with `v2` (the ledger is a directory, TD-1144) also
    `{oldest_v2, descends_v2}` against `cadence.OLDEST_V2`, read only once `descends` is True. None for
    dev-cadence's source or a lock that is lacking already. A read `old` made of the same commits is carried:
    their ancestry never changes."""
    lock, lack = _lock(Path(root))
    commit = (lock or {}).get("files_commit") or (lock or {}).get("commit")
    if lack or not commit:
        return None
    same = isinstance(old, dict) and (old.get("commit"), old.get("oldest"), old.get("seed")) == (
        commit,
        cadence.OLDEST,
        cadence.SEED,
    )
    if same and old.get("descends") is not None:
        if not v2 or old.get("descends") is False:
            return old
        if old.get("oldest_v2") == cadence.OLDEST_V2 and old.get("descends_v2") is not None:
            return old
    source = str(lock.get("source") or "")
    got, why = descends(commit, roster, source)
    out = {"commit": commit, "oldest": cadence.OLDEST, "seed": cadence.SEED, "descends": got, "why": why}
    if v2 and got is True:
        out["oldest_v2"] = cadence.OLDEST_V2
        out["descends_v2"], out["why"] = descends(commit, roster, source, cadence.OLDEST_V2)
    return out


def predates_v2(commit: str) -> str:
    """A v2 ledger's *predates* reason (§5 *Which dev-cadence*): the tree at `commit` is older than
    `cadence.OLDEST_V2`, so its scripts cannot read a directory."""
    return f"the ledger is a directory and dev-cadence at {commit[:7]} predates its v2 reader ({cadence.OLDEST_V2[:7]})"


def serve(root: Path | str, led: dict[str, Any], dc_age: dict[str, Any] | None = None) -> dict[str, Any]:
    """`{ok, lacks: [{key, words}]}`: `cadence` (dev-cadence's tree: no lock, or one that does not parse),
    `age` (a tree older than `cadence.OLDEST`, as `age()` read it: the one lack a sync cures, §6 *Sync*),
    `gate` (its script) and `ledger`, each lack in §5's fixed words with its cure; `ok` when there is none."""
    root = Path(root)
    lacks: list[dict[str, str]] = []
    pinned = cadence.pinned(root)
    lock, words = _lock(root)
    if words:
        lacks.append({"key": "cadence", "words": words})
    elif dc_age and dc_age.get("descends") is False:
        words = f"unserved: dev-cadence at {dc_age['commit'][:7]} is older than this build reads"
        lacks.append(
            {"key": "age", "words": f"{words} ({dc_age['oldest'][:7]}) — {'bump the pin' if pinned else 'sync it'}"}
        )
    if pinned:  # the pinned tree's gate; a pin that did not resolve has said so already
        if lock is not None and cadence.gate(root) is None:
            lacks.append(
                {
                    "key": "gate",
                    "words": f"unserved: no gate (no {cadence.GATE_SCRIPT} in the pinned tree) — bump the pin",
                }
            )
    elif cadence.gate(root) is None:
        script = cadence.SOURCE_SCRIPT if cadence.is_source(root) else cadence.SCRIPT
        lacks.append({"key": "gate", "words": f"unserved: no gate (no {script}) — {cure(root)}"})
    if words := ledger_lack(led, root):  # *predates* is an older tree's, which the sync cures (§6 *Sync*)
        lacks.append({"key": "ledger_age" if led.get("state") == "predates" else "ledger", "words": words})
    return {"ok": not lacks, "lacks": lacks}


def unserved(r: Any, but: tuple[str, ...] = ()) -> list[str]:
    """The words of each lack that leaves a repo unserved (§5 *The seams*, TD-1011), from its repo facts
    (`r["seams"]["serve"]`), passing over the lacks keyed in `but` (the sync pass's `age` and `ledger_age`, §6
    *Sync*); none for a served repo, and none where no `serve` was read yet (an older host agent's reading, or
    none yet): a repo is never unserved on a guess."""
    seams = r.get("seams") if isinstance(r, dict) else None
    serve = seams.get("serve") if isinstance(seams, dict) else None
    if not isinstance(serve, dict) or serve.get("ok") is not False:
        return []
    lacks = [x for x in serve.get("lacks") or [] if isinstance(x, dict) and x.get("key") not in but]
    return [str(x.get("words") or x.get("key")) for x in lacks]


def shimmed(root: Path | str, pinned: bool = False) -> bool | None:
    """Whether the checkout's common `.git/hooks/pre-push` carries dev-cadence's shim marker — in a `pinned`
    repo (`cadence.hook_pinned`) the TD-129 shim's launcher call too, since an older shim runs a copied hook
    that is gone (TD-1024); None where the checkout has no `.git` directory to read (a worktree, or no
    checkout here)."""
    hooks = Path(root) / ".git" / "hooks"
    if not hooks.parent.is_dir():
        return None
    try:
        text = (hooks / "pre-push").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return SHIM_MARKER in text and (not pinned or PINNED_SHIM in text)


def session_start(root: Path | str) -> list[str]:
    """The SessionStart hook commands of the checkout's `.claude/settings.json`, as text; none for a
    file that is missing or not that shape."""
    try:
        doc = json.loads((Path(root) / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    groups = ((doc.get("hooks") if isinstance(doc, dict) else None) or {}).get("SessionStart")
    out: list[str] = []
    for g in groups if isinstance(groups, list) else []:
        for h in (g.get("hooks") if isinstance(g, dict) else None) or []:
            if isinstance(h, dict) and isinstance(h.get("command"), str):
                out.append(h["command"])
    return out


def on_cadence_roster(root: Path | str) -> bool | None:
    """Whether the checkout is on dev-cadence's own roster (`hosts.DEV_CADENCE_ROSTER`), which its
    `adopt` and `gc` read and ShiftLead never writes (§4.7 `ao repo add`); None where that roster could not
    be read, so nothing is said of it."""
    try:
        lines = Path(hosts.DEV_CADENCE_ROSTER).expanduser().read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    here = Path(root).resolve()
    return any(Path(x.strip()).expanduser().resolve() == here for x in lines if x.strip() and not x.startswith("#"))


def warnings(
    root: Path | str,
    board: dict[str, Any],
    setup: dict[str, Any],
    dc_age: dict[str, Any] | None = None,
    served: bool = False,
    pinned: bool = False,
    led: dict[str, Any] | None = None,
) -> list[str]:
    """The warnings the host agent can read itself (§5 *The seams*), each one sentence: a set `ledger:` gone
    from the tree, which `led` (the ledger seam) reads in the other layout (§4.4 *Either layout*), a missing board,
    no worktree setup, a checkout without dev-cadence's hook shim, dev-cadence's age where it could not
    be read (§5 *Which dev-cadence*), and a `served` repo missing from dev-cadence's own roster (§4.7 `ao
    repo add`, TD-1010) — never dev-cadence's source, which no sync reaches. The two per-clone cures are the
    era's: a repo still on the copy is moved to a pin, `sync.sh --pin` (the copy is retired, TD-1188), the
    launcher in a `pinned` repo (`cadence.hook_pinned`, TD-1024). A repo is served whatever they say."""
    out: list[str] = []
    if (led or {}).get("named"):
        out.append(f"`ledger:` names {led['named']}, which is gone: reading {led.get('path')}")
    if board.get("state") == "absent" or (board.get("value") and not (Path(root) / board["value"]).is_file()):
        out.append(f"no board at {board.get('value') or workorders.BOARD}")
    if setup.get("state") == "absent":
        out.append("no worktree setup")
    if shimmed(root, pinned) is False:
        cure = f"dev-cadence -C {root} run install_git_hooks.sh" if pinned else f"<dev-cadence>/sync.sh --pin {root}"
        out.append(f"dev-cadence's per-clone setup not run in this checkout — `{cure}`")
    if dc_age and dc_age.get("why"):
        out.append(f"dev-cadence's age not read: {dc_age['why']}")
    if served and not cadence.is_source(root) and on_cadence_roster(root) is False:
        if pinned:
            cure = f"its gc may remove the tree this repo pins — `dev-cadence -C <dev-cadence> adopt {root}`"
        else:
            cure = f"the copy is retired, so move it to a pin — `<dev-cadence>/sync.sh --pin {root}`"
        out.append(f"not on dev-cadence's roster: {cure}")
    return out


def reading(root: Path | str, roster: Iterable[Path | str] = (), old: dict[str, Any] | None = None) -> dict[str, Any]:
    """The repo's seams: `{ledger, board, worktree_setup, cadence_age, serve, hook_pinned, warnings,
    session_start, ledgerboard, source}` — `ledger` as `ledger()` gives it, `board` and `worktree_setup`
    each `{state, value}`, `value` the board's path or the command (None when *absent*), `cadence_age` as
    `age()` reads it against the `roster` (the home's checkouts; `old` the last reading, whose age it
    carries), `serve` as `serve()` gives it, `hook_pinned` as `cadence.hook_pinned` (the SessionStart line's
    mode, §4.2, which picks the per-clone cures and the clients' *predates the pin*, TD-1024),
    `ledgerboard` as `ledgerboard()` does, `source` whether the root is dev-cadence's own source (its every
    dev-cadence path under `files/`)."""
    board_state, board_rel = workorders.board_path(root)
    state, value = gitinfo.worktree_setup(root)
    out: dict[str, Any] = {
        "ledger": ledger(root),
        "board": {"state": board_state, "value": board_rel.as_posix() if board_rel is not None else None},
        "worktree_setup": {"state": state, "value": value},
    }
    led = out["ledger"]
    out["cadence_age"] = got = age(root, roster, (old or {}).get("cadence_age"), v2=bool(led.get("directory")))
    if led.get("directory") and led["state"] == "ok" and (got or {}).get("descends_v2") is False:
        out["ledger"] = {**led, "state": "predates", "why": predates_v2(got["commit"])}
    out["serve"] = serve(root, out["ledger"], out["cadence_age"])
    out["hook_pinned"] = cadence.hook_pinned(root)
    out["warnings"] = warnings(
        root,
        out["board"],
        out["worktree_setup"],
        out["cadence_age"],
        out["serve"]["ok"],
        out["hook_pinned"],
        out["ledger"],
    )
    out["session_start"] = session_start(root)
    out["ledgerboard"] = ledgerboard(root)
    out["source"] = cadence.is_source(root)
    return out
